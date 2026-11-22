"""Per-user, per-day counter of AI calls: the cost control (a student cannot run up the AI bill)."""
import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin


class AiUsage(IdMixin, Base):
    __tablename__ = "ai_usage"
    __table_args__ = (UniqueConstraint("user_id", "usage_date", "kind", name="uq_ai_usage_user_day_kind"),)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    usage_date: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(24))  # student_tutor | teacher
    count: Mapped[int] = mapped_column(Integer, default=0)
