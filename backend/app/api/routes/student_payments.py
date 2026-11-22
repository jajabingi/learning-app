"""Student side of money: my orders/balances/receipts, hosted-checkout start, and the gateway webhook.
A student sees ONLY their own orders. Card details never touch this server (hosted gateway page)."""
import json
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DB
from app.core.permissions import require_student
from app.core.security import public_limiter
from app.models.lms import LmsCourse
from app.models.payment import LmsOrder, LmsPayment
from app.models.user import User
from app.services import access
from app.services import payments as pay

router = APIRouter(prefix="/student", tags=["student-payments"], dependencies=[Depends(require_student)])
webhooks = APIRouter(prefix="/payments", tags=["payment-webhooks"], dependencies=[Depends(public_limiter)])
Student = Depends(require_student)


def _own_order(db, user: User, order_id: uuid.UUID) -> LmsOrder:
    o = db.get(LmsOrder, order_id)
    if o is None or o.student_id != user.id:
        raise access.NOT_FOUND
    return o


def _order_view(db, o: LmsOrder) -> dict:
    c = db.get(LmsCourse, o.course_id)
    return {
        "id": str(o.id), "course_id": str(c.id), "course_title": c.title, "currency": o.currency, "amount_due": float(pay.D(o.amount_due)),
        "paid": float(pay.net_paid(o)), "balance": float(max(pay.balance(o), Decimal(0))), "pending": float(pay.pending_total(o)), "status": o.status,
        "payment_policy": c.payment_policy, "payment_instructions": c.payment_instructions, "can_pay_online": bool(pay.provider_name()) and o.status == "open",
        "installments": pay.installment_plan(o), "overdue": float(pay.overdue_amount(o)),
        "payments": [{"id": str(p.id), "kind": p.kind, "amount": float(pay.D(p.amount)), "method": p.method, "status": p.status,
                      "date": (p.received_at or p.created_at).isoformat(), "receipt_no": pay.receipt_no(p)} for p in o.payments if p.status != "failed"],
    }


@router.get("/payments")
def my_payments(db: DB, user: User = Student):
    orders = db.scalars(select(LmsOrder).where(LmsOrder.student_id == user.id).order_by(LmsOrder.created_at.desc()))
    return {"online_enabled": bool(pay.provider_name()), "orders": [_order_view(db, o) for o in orders]}


class CheckoutIn(BaseModel):
    amount: Decimal | None = Field(default=None, gt=0, decimal_places=2)


@router.post("/orders/{order_id}/checkout", status_code=201)
def checkout(order_id: uuid.UUID, data: CheckoutIn, db: DB, user: User = Student):
    """Starts a hosted online payment (any amount up to the balance, so installments work). Returns where to send the student."""
    o = _own_order(db, user, order_id)
    p = pay.start_checkout(db, o, user, data.amount)
    return {"payment_id": str(p.id), "provider": p.provider, "amount": float(pay.D(p.amount)),
            # sandbox: an internal page that simulates the gateway. A real provider returns its own hosted-page URL here.
            "redirect": f"/pay/sandbox/{p.id}" if p.provider == "sandbox" else None}


class SandboxIn(BaseModel):
    outcome: str = Field(pattern="^(success|fail)$")


@router.get("/payments/{payment_id}")
def payment_status(payment_id: uuid.UUID, db: DB, user: User = Student):
    p = db.get(LmsPayment, payment_id)
    if p is None or db.get(LmsOrder, p.order_id).student_id != user.id:
        raise access.NOT_FOUND
    return {"id": str(p.id), "status": p.status, "amount": float(pay.D(p.amount)), "provider": p.provider, "order_id": str(p.order_id)}


@router.post("/payments/{payment_id}/sandbox-complete")
def sandbox_complete(payment_id: uuid.UUID, data: SandboxIn, db: DB, user: User = Student):
    """TEST ONLY: stands in for the gateway's confirmation. Does not exist in production (sandbox is refused there)."""
    p = db.get(LmsPayment, payment_id)
    if p is None or db.get(LmsOrder, p.order_id).student_id != user.id or p.provider != "sandbox" or pay.provider_name() != "sandbox":
        raise access.NOT_FOUND
    p = pay.apply_provider_event(db, "sandbox", p.provider_ref, data.outcome, p.amount)
    return {"id": str(p.id), "status": p.status}


@router.get("/payments/{payment_id}/receipt")
def my_receipt(payment_id: uuid.UUID, db: DB, user: User = Student):
    p = db.get(LmsPayment, payment_id)
    if p is None or db.get(LmsOrder, p.order_id).student_id != user.id or p.status != "confirmed":
        raise access.NOT_FOUND
    return pay.receipt_out(db, p)


@webhooks.post("/webhook/{provider}")
async def webhook(provider: str, request: Request, db: DB, x_signature: str = Header(default="")):
    """Gateway -> us. The body must carry a valid signature; events are idempotent and amount-checked.
    (A real gateway adapter replaces verify/parse here; sandbox signs with an HMAC of the body.)"""
    if provider != pay.provider_name():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown provider")
    body = await request.body()
    if not pay.verify_event(body, x_signature):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bad signature")
    try:
        ev = json.loads(body)
        ref, st = str(ev["provider_ref"]), str(ev["status"])
        amount = Decimal(str(ev["amount"])) if ev.get("amount") is not None else None
    except (ValueError, KeyError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Malformed event")
    p = pay.apply_provider_event(db, provider, ref, "success" if st == "success" else "fail", amount)
    return {"status": p.status}
