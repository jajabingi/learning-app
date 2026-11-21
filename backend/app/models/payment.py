"""Money. Three separate concerns (see docs/PAYMENTS.md):
  User/Enrollment  -> who the student is and what they may access
  Order            -> what they owe for ONE course (a snapshot of the price at order time)
  Payment          -> an append-only ledger of money received / refunded against an order

Nothing here stores card data: online cards go through a hosted gateway page and only the gateway's reference is kept.
Ledger rows are never deleted; a mistake is VOIDED (and audited) so the books stay explainable."""
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import IdMixin, TimestampMixin, TZDateTime

ORDER_STATUSES = ("open", "paid", "cancelled")
PAYMENT_KINDS = ("payment", "refund")
PAYMENT_METHODS = ("cash", "bank_transfer", "check", "card", "bit_paybox", "other")
PAYMENT_STATUSES = ("pending", "confirmed", "failed", "voided")


class LmsOrder(IdMixin, TimestampMixin, Base):
    __tablename__ = "lms_orders"
    __table_args__ = (UniqueConstraint("student_id", "course_id", name="uq_order_student_course"),
                      Index("ix_lms_orders_course_status", "course_id", "status"))

    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lms_courses.id", ondelete="RESTRICT"), index=True)
    enrollment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("lms_enrollments.id", ondelete="SET NULL"), nullable=True)
    list_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))     # course price when the order was created
    amount_due: Mapped[Decimal] = mapped_column(Numeric(12, 2))     # what the student actually owes (discounts / teacher adjustments)
    currency: Mapped[str] = mapped_column(String(3), default="ILS")
    status: Mapped[str] = mapped_column(String(12), default="open")
    note: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    payments: Mapped[list["LmsPayment"]] = relationship(cascade="all, delete-orphan", passive_deletes=True,
                                                        order_by="LmsPayment.created_at", lazy="selectin")
    installments: Mapped[list["LmsInstallment"]] = relationship(cascade="all, delete-orphan", passive_deletes=True,
                                                                order_by="LmsInstallment.position", lazy="selectin")


class LmsPayment(IdMixin, TimestampMixin, Base):
    __tablename__ = "lms_payments"
    __table_args__ = (UniqueConstraint("provider", "provider_ref", name="uq_payment_provider_ref"),)

    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lms_orders.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(8), default="payment")           # payment | refund (amount is always positive)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    method: Mapped[str] = mapped_column(String(16), default="cash")
    status: Mapped[str] = mapped_column(String(10), default="confirmed")
    provider: Mapped[str] = mapped_column(String(24), default="manual")       # manual | sandbox | <gateway name>
    provider_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)  # gateway transaction id (idempotency key)
    reference: Mapped[str] = mapped_column(String(200), default="")          # cheque no., transfer reference, ...
    note: Mapped[str] = mapped_column(Text, default="")
    received_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    receipt_seq: Mapped[int | None] = mapped_column(Integer, nullable=True, unique=True)
    voided_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    void_reason: Mapped[str] = mapped_column(Text, default="")


class LmsInstallment(IdMixin, Base):
    """A scheduled slice of the order. Payments are applied oldest-first; an installment is overdue when its cumulative
    scheduled amount is not yet covered by confirmed payments and its due date has passed."""

    __tablename__ = "lms_installments"
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lms_orders.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    due_date: Mapped[date] = mapped_column(Date)
