"""Teacher/admin side of money: orders, the payment ledger, installment plans, refunds and the finance dashboard.
A teacher only ever sees orders of THEIR OWN courses (admins see all). Writes need `payments.manage`, the dashboard
and exports need `finance.view`."""
import csv
import io
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DB
from app.core.permissions import P_FINANCE_VIEW, P_PAYMENTS_MANAGE, require_permission
from app.models.base import utcnow
from app.models.lms import LmsCourse
from app.models.payment import PAYMENT_METHODS, LmsOrder, LmsPayment
from app.models.user import User
from app.services import audit, lms
from app.services import payments as pay

router = APIRouter(prefix="/teach", tags=["teacher-payments"])
Manager = Depends(require_permission(P_PAYMENTS_MANAGE))
Finance = Depends(require_permission(P_FINANCE_VIEW))
Method = Literal["cash", "bank_transfer", "check", "card", "bit_paybox", "other"]


class OrderIn(BaseModel):
    student_id: uuid.UUID
    course_id: uuid.UUID
    amount_due: Decimal | None = Field(default=None, ge=0, le=Decimal("10000000"), decimal_places=2)
    note: str = Field(default="", max_length=2000)


class OrderPatch(BaseModel):
    amount_due: Decimal | None = Field(default=None, ge=0, le=Decimal("10000000"), decimal_places=2)
    note: str | None = Field(default=None, max_length=2000)
    status: Literal["open", "cancelled"] | None = None
    reason: str = Field(default="", max_length=500)


class PaymentIn(BaseModel):
    amount: Decimal = Field(gt=0, le=Decimal("10000000"), decimal_places=2)
    method: Method = "cash"
    reference: str = Field(default="", max_length=200)
    note: str = Field(default="", max_length=2000)
    received_at: datetime | None = None


class VoidIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class RefundIn(BaseModel):
    amount: Decimal = Field(gt=0, decimal_places=2)
    reason: str = Field(min_length=3, max_length=500)
    revoke_access: bool = True


class InstallmentItem(BaseModel):
    amount: Decimal = Field(gt=0, decimal_places=2)
    due_date: date


class InstallmentsIn(BaseModel):
    count: int | None = Field(default=None, ge=1, le=36)       # split the order evenly, one per month ...
    first_due: date | None = None                               # ... starting here
    items: list[InstallmentItem] | None = Field(default=None, max_length=36)  # or an explicit schedule
    clear: bool = False


def _own_order(db, user: User, order_id: uuid.UUID) -> tuple[LmsOrder, LmsCourse]:
    o = db.get(LmsOrder, order_id)
    if o is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    return o, lms.own_course(db, user, o.course_id)  # 404 unless it is the teacher's course


def payment_out(p: LmsPayment) -> dict:
    return {"id": str(p.id), "kind": p.kind, "amount": float(pay.D(p.amount)), "method": p.method, "status": p.status, "provider": p.provider,
            "reference": p.reference, "note": p.note, "received_at": p.received_at.isoformat() if p.received_at else None,
            "created_at": p.created_at.isoformat(), "receipt_no": pay.receipt_no(p), "void_reason": p.void_reason}


def order_out(db, o: LmsOrder, detail: bool = False) -> dict:
    s = db.get(User, o.student_id)
    c = db.get(LmsCourse, o.course_id)
    d = {"id": str(o.id), "student_id": str(o.student_id), "student_name": s.display_name, "student_email": s.email, "course_id": str(o.course_id),
         "course_title": c.title, "currency": o.currency, "list_price": float(pay.D(o.list_price)), "amount_due": float(pay.D(o.amount_due)),
         "paid": float(pay.net_paid(o)), "balance": float(pay.balance(o)), "pending": float(pay.pending_total(o)), "status": o.status,
         "overdue": float(pay.overdue_amount(o)), "note": o.note, "created_at": o.created_at.isoformat(), "enrollment_id": str(o.enrollment_id) if o.enrollment_id else None}
    if detail:
        d["payments"] = [payment_out(p) for p in o.payments]
        d["installments"] = pay.installment_plan(o)
    return d


def _my_orders(db, user: User, course_id: uuid.UUID | None = None) -> list[LmsOrder]:
    q = select(LmsOrder).join(LmsCourse, LmsCourse.id == LmsOrder.course_id)
    if user.role != "admin":
        q = q.where(LmsCourse.owner_id == user.id)
    if course_id:
        q = q.where(LmsOrder.course_id == course_id)
    return list(db.scalars(q.order_by(LmsOrder.created_at.desc())))


# ---------------------------------------------------------------- orders
@router.get("/courses/{course_id}/orders")
def course_orders(course_id: uuid.UUID, db: DB, user: User = Manager):
    c = lms.own_course(db, user, course_id)
    return [order_out(db, o) for o in _my_orders(db, user, c.id)]


@router.post("/orders", status_code=201)
def create_order(data: OrderIn, db: DB, user: User = Manager):
    course = lms.own_course(db, user, data.course_id)
    student = db.get(User, data.student_id)
    if student is None or student.role != "student" or student.status != "active":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")
    existing = pay.get_order(db, student.id, course.id)
    if existing is not None:
        raise pay.conflict("This student already has an order for the course")
    o = pay.ensure_order(db, student, course, actor=user, amount_due=data.amount_due, note=data.note)
    audit.log_event(db, "order_created", actor=user, target=student, order_id=str(o.id), course_id=str(course.id), amount_due=str(o.amount_due))
    return order_out(db, o, detail=True)


@router.get("/orders/{order_id}")
def get_order(order_id: uuid.UUID, db: DB, user: User = Manager):
    o, _c = _own_order(db, user, order_id)
    return order_out(db, o, detail=True)


@router.patch("/orders/{order_id}")
def patch_order(order_id: uuid.UUID, data: OrderPatch, db: DB, user: User = Manager):
    o, course = _own_order(db, user, order_id)
    if data.amount_due is not None and pay.D(data.amount_due) != pay.D(o.amount_due):
        if pay.D(data.amount_due) < pay.net_paid(o):
            raise pay.conflict("The new amount is lower than what was already paid: refund the difference first")
        audit.log_event(db, "order_adjusted", actor=user, target=o.student_id, order_id=str(o.id), old=str(o.amount_due), new=str(data.amount_due), reason=data.reason)
        o.amount_due = pay.D(data.amount_due)
        o.installments.clear()  # a schedule no longer matches the new total
    if data.note is not None:
        o.note = data.note
    if data.status == "cancelled":
        if pay.net_paid(o) > 0:
            raise pay.conflict("The order has payments: refund them before cancelling")
        o.status = "cancelled"
        audit.log_event(db, "order_cancelled", actor=user, target=o.student_id, order_id=str(o.id), reason=data.reason)
    elif data.status == "open" and o.status == "cancelled":
        o.status = "open"
    pay.recompute(db, o, course, user)
    return order_out(db, o, detail=True)


# ---------------------------------------------------------------- ledger
@router.post("/orders/{order_id}/payments", status_code=201)
def add_payment(order_id: uuid.UUID, data: PaymentIn, db: DB, user: User = Manager):
    o, _c = _own_order(db, user, order_id)
    if data.received_at and data.received_at > utcnow() + timedelta(days=1):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The payment date cannot be in the future")
    p = pay.record_payment(db, o, data.amount, data.method, user, data.reference, data.note, data.received_at)
    return {"payment": payment_out(p), "order": order_out(db, o, detail=True)}


@router.post("/payments/{payment_id}/void")
def void(payment_id: uuid.UUID, data: VoidIn, db: DB, user: User = Manager):
    p = db.get(LmsPayment, payment_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payment not found")
    o, _c = _own_order(db, user, p.order_id)
    pay.void_payment(db, o, p, user, data.reason)
    return order_out(db, o, detail=True)


@router.post("/orders/{order_id}/refunds", status_code=201)
def add_refund(order_id: uuid.UUID, data: RefundIn, db: DB, user: User = Manager):
    o, _c = _own_order(db, user, order_id)
    pay.refund(db, o, data.amount, user, data.reason, data.revoke_access)
    return order_out(db, o, detail=True)


@router.post("/orders/{order_id}/installments")
def set_plan(order_id: uuid.UUID, data: InstallmentsIn, db: DB, user: User = Manager):
    o, _c = _own_order(db, user, order_id)
    if data.clear:
        o.installments.clear()
        db.flush()
    elif data.items:
        pay.set_installments(db, o, [(i.amount, i.due_date) for i in data.items])
    elif data.count and data.first_due:
        pay.set_installments(db, o, pay.split_evenly(o.amount_due, data.count, data.first_due))
    else:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Give a count and first due date, an explicit list, or clear")
    audit.log_event(db, "installments_set", actor=user, target=o.student_id, order_id=str(o.id), count=len(o.installments))
    return order_out(db, o, detail=True)


# ---------------------------------------------------------------- finance dashboard / exports
@router.get("/finance/summary")
def finance_summary(db: DB, course_id: uuid.UUID | None = None, user: User = Finance):
    if course_id:
        lms.own_course(db, user, course_id)
    orders = [o for o in _my_orders(db, user, course_id) if o.status != "cancelled"]
    collected = outstanding = overdue = refunded = pending = Decimal(0)
    by_method: dict[str, Decimal] = {}
    by_month: dict[str, Decimal] = {}
    by_course: dict[str, dict] = {}
    late = []
    for o in orders:
        paid, bal, od = pay.net_paid(o), max(pay.balance(o), Decimal(0)), pay.overdue_amount(o)
        collected += paid
        outstanding += bal
        overdue += od
        pending += pay.pending_total(o)
        refunded += pay.confirmed(o, "refund")
        row = by_course.setdefault(str(o.course_id), {"course_id": str(o.course_id), "course_title": db.get(LmsCourse, o.course_id).title, "orders": 0, "billed": Decimal(0), "collected": Decimal(0), "outstanding": Decimal(0)})
        row["orders"] += 1
        row["billed"] += pay.D(o.amount_due)
        row["collected"] += paid
        row["outstanding"] += bal
        for p in o.payments:
            if p.status == "confirmed" and p.kind == "payment":
                by_method[p.method] = by_method.get(p.method, Decimal(0)) + pay.D(p.amount)
                month = (p.received_at or p.created_at).strftime("%Y-%m")
                by_month[month] = by_month.get(month, Decimal(0)) + pay.D(p.amount)
        if od > 0:
            late.append({**order_out(db, o), "overdue": float(od)})
    cur = {c for _, c in [(0, o.currency) for o in orders]}
    return {"currency": next(iter(cur)) if len(cur) == 1 else "mixed", "orders": len(orders), "billed": float(sum((pay.D(o.amount_due) for o in orders), Decimal(0))),
            "collected": float(collected), "outstanding": float(outstanding), "overdue": float(overdue), "pending_online": float(pending), "refunded": float(refunded),
            "by_method": {k: float(v) for k, v in by_method.items()}, "by_month": [{"month": k, "amount": float(v)} for k, v in sorted(by_month.items())],
            "by_course": [{**r, "billed": float(r["billed"]), "collected": float(r["collected"]), "outstanding": float(r["outstanding"])} for r in by_course.values()],
            "overdue_orders": sorted(late, key=lambda r: -r["overdue"])[:50]}


def _csv(rows: list[list], header: list[str]) -> Response:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for r in rows:
        # neutralise spreadsheet formula injection in text cells
        w.writerow([("'" + c) if isinstance(c, str) and c[:1] in ("=", "+", "-", "@") else c for c in r])
    return Response(("﻿" + buf.getvalue()).encode("utf-8"), media_type="text/csv; charset=utf-8")


@router.get("/finance/ledger.csv")
def ledger_csv(db: DB, course_id: uuid.UUID | None = None, user: User = Finance):
    if course_id:
        lms.own_course(db, user, course_id)
    rows = []
    for o in _my_orders(db, user, course_id):
        s, c = db.get(User, o.student_id), db.get(LmsCourse, o.course_id)
        for p in o.payments:
            rows.append([(p.received_at or p.created_at).date().isoformat(), pay.receipt_no(p) or "", s.display_name, s.email, c.title, p.kind, p.status, float(pay.D(p.amount)), o.currency, p.method, p.provider, p.reference])
    return _csv(rows, ["date", "receipt", "student", "email", "course", "kind", "status", "amount", "currency", "method", "provider", "reference"])


@router.get("/students-export.csv")
def students_csv(db: DB, course_id: uuid.UUID | None = None, user: User = Depends(require_permission(P_PAYMENTS_MANAGE))):
    """Students of the caller's courses with enrollment and balance (for spreadsheets)."""
    from app.models.lms import LmsEnrollment
    if course_id:
        lms.own_course(db, user, course_id)
    mine = select(LmsCourse.id) if user.role == "admin" else select(LmsCourse.id).where(LmsCourse.owner_id == user.id)
    if course_id:
        mine = select(LmsCourse.id).where(LmsCourse.id == course_id)
    rows = []
    for e in db.scalars(select(LmsEnrollment).where(LmsEnrollment.course_id.in_(mine))):
        s, c = db.get(User, e.student_id), db.get(LmsCourse, e.course_id)
        o = pay.get_order(db, e.student_id, e.course_id)
        rows.append([s.display_name, s.email, c.title, e.status, e.source, e.expires_at.date().isoformat() if e.expires_at else "",
                     float(pay.D(o.amount_due)) if o else "", float(pay.net_paid(o)) if o else "", float(pay.balance(o)) if o else ""])
    return _csv(rows, ["name", "email", "course", "enrollment", "source", "expires", "amount_due", "paid", "balance"])
