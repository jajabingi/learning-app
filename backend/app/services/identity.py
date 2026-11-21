"""Account helpers shared by the auth and admin routes: e-mail normalisation, status, session revocation,
single-use tokens and account creation. Public registration and OAuth can only ever create STUDENTS."""
import hashlib
import secrets
import uuid
from datetime import timedelta
from urllib.parse import urlencode

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.models.base import as_utc, utcnow
from app.models.user import UNUSABLE_PASSWORD, AuthToken, User, UserIdentity

settings = get_settings()


def normalize_email(email: str) -> str:
    return email.strip().lower()


def has_password(user: User) -> bool:
    return user.password_hash != UNUSABLE_PASSWORD


def set_status(user: User, new: str) -> None:
    user.status = new
    user.is_active = new == "active"
    if new != "active":
        revoke_sessions(user)


def revoke_sessions(user: User) -> None:
    """Every access/refresh token issued so far stops working."""
    user.token_version = (user.token_version or 0) + 1


def find_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == normalize_email(email)))


def create_student(db: Session, email: str, password: str | None, display_name: str = "", verified: bool = False) -> User:
    email = normalize_email(email)
    u = User(email=email, password_hash=hash_password(password) if password else UNUSABLE_PASSWORD, role="student",  # NEVER from input
             display_name=(display_name or email.split("@")[0])[:100], status="active", is_active=True,
             email_verified_at=utcnow() if verified else None)
    db.add(u)
    db.flush()
    return u


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def issue_token(db: Session, kind: str, user_id: uuid.UUID | None, ttl: timedelta, payload: dict | None = None) -> str:
    raw = secrets.token_urlsafe(32)
    db.add(AuthToken(user_id=user_id, kind=kind, token_hash=_hash(raw), payload=payload or {}, expires_at=utcnow() + ttl))
    db.flush()
    return raw


def consume_token(db: Session, raw: str, kind: str) -> AuthToken:
    """Single use: valid, unexpired, unused and of the right kind - otherwise 400."""
    t = db.scalar(select(AuthToken).where(AuthToken.token_hash == _hash(raw or ""), AuthToken.kind == kind))
    if t is None or t.used_at is not None or as_utc(t.expires_at) <= utcnow():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This link is invalid or has expired")
    t.used_at = utcnow()
    db.flush()
    return t


def identities_of(db: Session, user: User) -> list[UserIdentity]:
    return list(db.scalars(select(UserIdentity).where(UserIdentity.user_id == user.id)))


def web_url(path: str, **params) -> str:
    return f"{settings.frontend_url.rstrip('/')}{path}" + (f"?{urlencode(params)}" if params else "")
