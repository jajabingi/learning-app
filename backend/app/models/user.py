import uuid
from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, JSONType, TimestampMixin, TZDateTime, utcnow


ROLES = ("student", "teacher", "admin")
STAFF_ROLES = ("teacher", "admin")
USER_STATUSES = ("active", "suspended", "pending_verification")
UNUSABLE_PASSWORD = "!"  # stored for accounts that have no password (Google-only); bcrypt can never match it


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    display_name: Mapped[str] = mapped_column(String(100), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)  # kept in sync with `status` (status == "active")
    status: Mapped[str] = mapped_column(String(24), default="active", server_default="active", index=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    # Bumped on suspension, logout, password change/reset: every token issued before the bump stops working.
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    role: Mapped[str] = mapped_column(String(16), default="student", server_default="student", index=True)
    # Learning preferences
    desired_retention: Mapped[float] = mapped_column(Float, default=0.9)
    daily_new_limit: Mapped[int] = mapped_column(Integer, default=20)
    daily_review_goal: Mapped[int] = mapped_column(Integer, default=30)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")


class UserPermission(Base):
    """Fine-grained permission granted to a staff user (admins implicitly have all)."""

    __tablename__ = "user_permissions"
    __table_args__ = (UniqueConstraint("user_id", "permission", name="uq_user_permission"),)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    permission: Mapped[str] = mapped_column(String(64), primary_key=True)


class UserIdentity(IdMixin, Base):
    """An external sign-in method attached to a user (e.g. Google). `provider_subject` is the provider's stable id."""

    __tablename__ = "user_identities"
    __table_args__ = (UniqueConstraint("provider", "provider_subject", name="uq_identity_provider_subject"),)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(24))
    provider_subject: Mapped[str] = mapped_column(String(255))
    provider_email: Mapped[str] = mapped_column(String(320), default="")
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)


class AuditLog(IdMixin, Base):
    """Append-only record of sensitive actions. Never stores passwords or tokens."""

    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_target_created", "target_user_id", "created_at"),)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    target_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    details: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, index=True)


class AuthToken(IdMixin, Base):
    """Single-use, expiring secrets (password reset, email verification, Google link confirmation, login codes).
    Only a SHA-256 hash of the secret is stored."""

    __tablename__ = "auth_tokens"
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(24))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    payload: Mapped[dict] = mapped_column(JSONType, default=dict)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime())
    used_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
