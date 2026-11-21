"""Payment rules. One place decides what a student owes, what they paid, and when payment unlocks a course.

Rules
* balance = amount_due - (confirmed payments - confirmed refunds). Only `confirmed` rows count; pending/failed/voided never do.
* The course's `payment_policy` decides when access starts: full_payment (balance <= 0), any_payment (something confirmed),
  none (access is independent of payment: the teacher collects separately).
* Payment only ever ACTIVATES a pending enrollment. It never overrides a teacher's decision to suspend/cancel access.
* A full refund (net paid back to 0) revokes access that payment had granted, unless the caller opts out.
"""
import hashlib
import hmac
import json
import uuid
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.base import utcnow
from app.models.lms import LmsCourse, LmsEnrollment
from app.models.payment import LmsInstallment, LmsOrder, LmsPayment
from app.models.user import User
from app.services import access, audit

settings = get_settings()
ZERO = Decimal("0.00")


def D(v) -> Decimal:
    return Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def conflict(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, msg)


# ------------------------------------------------------------------ amounts
def effective_price(course: LmsCourse) -> Decimal:
    price = D(course.price_amount or 0)
    if course.discount_amount is not None and D(course.discount_amount) < price:
        return D(course.discount_amount)
    return price


def confirmed(order: LmsOrder, kind: str) -> Decimal:
    return sum((D(p.amount) for p in order.payments if p.status == "confirmed" and p.kind == kind), ZERO)


def net_paid(order: LmsOrder) -> Decimal:
    return confirmed(order, "payment") - confirmed(order, "refund")


def pending_total(order: LmsOrder) -> Decimal:
    return sum((D(p.amount) for p in order.payments if p.status == "pending" and p.kind == "payment"), ZERO)


def balance(order: LmsOrder) -> Decimal:
    return D(order.amount_due) - net_paid(order)


def installment_plan(order: LmsOrder, today: date | None = None) -> list[dict]:
    """Applies confirmed money to installments oldest-first."""
    today = today or utcnow().date()
    left, cumulative, rows = max(net_paid(order), ZERO), ZERO, []
    for i in order.installments:
        cumulative += D(i.amount)
        paid = min(D(i.amount), max(left, ZERO))
        left -= paid
        state = "paid" if paid >= D(i.amount) else ("partial" if paid > 0 else "unpaid")
        rows.append({"id": str(i.id), "position": i.position, "amount": float(D(i.amount)), "due_date": i.due_date.isoformat(), "paid": float(paid),
                     "status": state, "overdue": state != "paid" and i.due_date < today})
    return rows


def overdue_amount(order: LmsOrder, today: date | None = None) -> Decimal:
    """Scheduled-and-due money that confirmed payments do not cover yet."""
    if order.status == "cancelled":
        return ZERO
    today = today or utcnow().date()
    due_so_far = sum((D(i.amount) for i in order.installments if i.due_date < today), ZERO)
    return max(due_so_far - max(net_paid(order), ZERO), ZERO)


# ------------------------------------------------------------------ orders & access
def policy_satisfied(course: LmsCourse, order: LmsOrder) -> bool:
    if order.status == "cancelled":
        return False
    if course.payment_policy == "none":
        return True
    if course.payment_policy == "any_payment":
        return net_paid(order) > 0 or D(order.amount_due) <= 0
    return balance(order) <= 0


def get_order(db: Session, student_id: uuid.UUID, course_id: uuid.UUID) -> LmsOrder | None:
    return db.scalar(select(LmsOrder).where(LmsOrder.student_id == student_id, LmsOrder.course_id == course_id))


def ensure_order(db: Session, student: User, course: LmsCourse, actor: User | None = None, amount_due: Decimal | None = None, note: str = "") -> LmsOrder:
    """One order per student and course. Creates the (pending) enrollment too, so teacher and student see the same thing."""
    order = get_order(db, student.id, course.id)
    if order is not None:
        return order
    enr = access.get_enrollment(db, student, course.id)
    if enr is None:
        enr = LmsEnrollment(student_id=student.id, course_id=course.id, status="pending", source="purchase", notes="Payment pending")
        db.add(enr)
        db.flush()
    price = effective_price(course)
    order = LmsOrder(student_id=student.id, course_id=course.id, enrollment_id=enr.id, list_price=D(course.price_amount or 0),
                     amount_due=D(amount_due) if amount_due is not None else price, currency=course.currency, note=note,
                     created_by=actor.id if actor else student.id)
    db.add(order)
    db.flush()
    recompute(db, order, course, actor)
    return order


def recompute(db: Session, order: LmsOrder, course: LmsCourse | None = None, actor: User | None = None) -> None:
    course = course or db.get(LmsCourse, order.course_id)
    db.flush()
    db.expire(order, ["payments", "installments"])  # reload from the database so every confirmed row is counted
    if order.status != "cancelled":
        order.status = "paid" if balance(order) <= 0 else "open"
    sync_access(db, order, course, actor)


def sync_access(db: Session, order: LmsOrder, course: LmsCourse, actor: User | None = None) -> None:
    enr = db.get(LmsEnrollment, order.enrollment_id) if order.enrollment_id else None
    if enr is None:
        enr = db.scalar(select(LmsEnrollment).where(LmsEnrollment.student_id == order.student_id, LmsEnrollment.course_id == order.course_id))
        if enr is not None:
            order.enrollment_id = enr.id
    if enr is None or not policy_satisfied(course, order):
        return
    if enr.status == "pending":  # only ever activates; never overrides a suspension/cancellation by the teacher
        now = utcnow()
        enr.status, enr.source, enr.starts_at = "active", "purchase", now
        enr.expires_at = now + timedelta(days=course.access_days) if course.access_days else None
        enr.granted_by = actor.id if actor else enr.granted_by
        audit.log_event(db, "access_granted_by_payment", actor=actor, target=order.student_id, course_id=str(course.id), order_id=str(order.id))
    db.flush()


# ------------------------------------------------------------------ ledger
def next_receipt_seq(db: Session) -> int:
    return (db.scalar(select(func.max(LmsPayment.receipt_seq))) or 0) + 1


def receipt_no(p: LmsPayment) -> str | None:
    if p.receipt_seq is None:
        return None
    return f"{'R' if p.kind == 'payment' else 'C'}-{p.receipt_seq:06d}"


def confirm(db: Session, p: LmsPayment) -> None:
    p.status = "confirmed"
    p.received_at = p.received_at or utcnow()
    if p.receipt_seq is None:
        p.receipt_seq = next_receipt_seq(db)
    db.flush()


def record_payment(db: Session, order: LmsOrder, amount: Decimal, method: str, actor: User, reference: str = "", note: str = "",
                   received_at: datetime | None = None) -> LmsPayment:
    if order.status == "cancelled":
        raise conflict("The order is cancelled")
    amount = D(amount)
    if amount <= 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Amount must be greater than zero")
    if amount > balance(order):
        raise conflict(f"The amount exceeds the balance due ({balance(order)}). Adjust the order price first if the student owes more.")
    p = LmsPayment(order_id=order.id, kind="payment", amount=amount, method=method, status="pending", provider="manual", reference=reference[:200],
                   note=note, received_at=received_at, recorded_by=actor.id)
    db.add(p)
    order.payments.append(p)
    confirm(db, p)
    recompute(db, order, actor=actor)
    audit.log_event(db, "payment_recorded", actor=actor, target=order.student_id, order_id=str(order.id), amount=str(amount), method=method, receipt=receipt_no(p))
    return p


def void_payment(db: Session, order: LmsOrder, p: LmsPayment, actor: User, reason: str) -> None:
    if p.status == "voided":
        return
    if p.status != "confirmed":
        raise conflict("Only a confirmed payment can be voided")
    p.status, p.voided_at, p.void_reason = "voided", utcnow(), reason
    recompute(db, order, actor=actor)
    audit.log_event(db, "payment_voided", actor=actor, target=order.student_id, order_id=str(order.id), amount=str(p.amount), reason=reason[:200])


def refund(db: Session, order: LmsOrder, amount: Decimal, actor: User, reason: str, revoke_access: bool = True) -> LmsPayment:
    amount = D(amount)
    if amount <= 0 or amount > net_paid(order):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"A refund must be between 0.01 and the amount paid ({net_paid(order)})")
    r = LmsPayment(order_id=order.id, kind="refund", amount=amount, method="other", status="pending", provider="manual", note=reason, recorded_by=actor.id)
    db.add(r)
    order.payments.append(r)
    confirm(db, r)
    recompute(db, order, actor=actor)
    if revoke_access and net_paid(order) <= 0:
        enr = db.get(LmsEnrollment, order.enrollment_id) if order.enrollment_id else None
        if enr is not None and enr.source == "purchase" and enr.status in ("active", "completed"):
            enr.status = "cancelled"
    audit.log_event(db, "payment_refunded", actor=actor, target=order.student_id, order_id=str(order.id), amount=str(amount), reason=reason[:200])
    return r


def set_installments(db: Session, order: LmsOrder, rows: list[tuple[Decimal, date]]) -> None:
    total = sum((D(a) for a, _ in rows), ZERO)
    if total != D(order.amount_due):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"The installments add up to {total}, but the order is {D(order.amount_due)}")
    for i in list(order.installments):
        order.installments.remove(i)
    db.flush()
    for pos, (amt, due) in enumerate(sorted(rows, key=lambda r: r[1])):
        order.installments.append(LmsInstallment(position=pos, amount=D(amt), due_date=due))
    db.flush()


def split_evenly(total: Decimal, count: int, first_due: date) -> list[tuple[Decimal, date]]:
    total = D(total)
    base = (total / count).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    amounts = [base] * count
    amounts[-1] = total - base * (count - 1)  # the last one absorbs the rounding difference
    out = []
    for i, a in enumerate(amounts):
        month = first_due.month - 1 + i
        year, m = first_due.year + month // 12, month % 12 + 1
        day = min(first_due.day, 28)
        out.append((a, date(year, m, day)))
    return out


# ------------------------------------------------------------------ online provider (hosted checkout) + webhooks
def provider_name() -> str:
    """Active online provider. `sandbox` is a TEST double and can never be enabled in production."""
    name = (settings.payment_provider or "").strip().lower()
    if name == "sandbox" and settings.is_production:
        return ""
    return name


def sign_event(body: bytes) -> str:
    return hmac.new(settings.secret_key.encode(), body, hashlib.sha256).hexdigest()


def verify_event(body: bytes, signature: str) -> bool:
    return hmac.compare_digest(sign_event(body), signature or "")


def apply_provider_event(db: Session, provider: str, ref: str, new_status: str, amount: Decimal | None) -> LmsPayment:
    """Idempotent: a repeated event for an already-settled payment changes nothing. The amount must match what we asked for."""
    p = db.scalar(select(LmsPayment).where(LmsPayment.provider == provider, LmsPayment.provider_ref == ref))
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown payment")
    if p.status != "pending":
        return p
    order = db.get(LmsOrder, p.order_id)
    if new_status == "success":
        if amount is not None and D(amount) != D(p.amount):
            raise HTTPException(status.HTTP_409_CONFLICT, "Amount mismatch")
        confirm(db, p)
        recompute(db, order)
        audit.log_event(db, "payment_confirmed_online", target=order.student_id, order_id=str(order.id), amount=str(p.amount), provider=provider)
    else:
        p.status = "failed"
    db.flush()
    return p


def start_checkout(db: Session, order: LmsOrder, student: User, amount: Decimal | None) -> LmsPayment:
    if not provider_name():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Online payment is not available. Use the offline payment instructions.")
    if order.status == "cancelled":
        raise conflict("The order is cancelled")
    due = balance(order)
    amt = D(amount) if amount is not None else due
    if amt <= 0 or amt > due:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Choose an amount up to {due}")
    p = LmsPayment(order_id=order.id, kind="payment", amount=amt, method="card", status="pending", provider=provider_name(),
                   provider_ref=uuid.uuid4().hex, recorded_by=student.id)
    db.add(p)
    order.payments.append(p)
    db.flush()
    return p


def receipt_out(db: Session, p: LmsPayment) -> dict:
    order = db.get(LmsOrder, p.order_id)
    course = db.get(LmsCourse, order.course_id)
    student = db.get(User, order.student_id)
    seller = db.get(User, course.owner_id)
    return {"receipt_no": receipt_no(p), "kind": p.kind, "date": (p.received_at or p.created_at).isoformat(), "amount": float(D(p.amount)), "currency": order.currency,
            "method": p.method, "reference": p.reference, "student": {"name": student.display_name, "email": student.email},
            "course": course.title, "issued_by": course.instructor_name or seller.display_name, "order_total": float(D(order.amount_due)),
            "paid_to_date": float(net_paid(order)), "balance_after": float(balance(order)), "status": p.status}
