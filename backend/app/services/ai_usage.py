"""Daily AI quota per user. `consume` is part of the request's transaction: if the AI call then fails, the request errors out,
the transaction rolls back, and the failed attempt is NOT counted."""
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ai_usage import AiUsage
from app.models.base import utcnow
from app.models.user import User


def _row(db: Session, user: User, kind: str) -> AiUsage:
    today = utcnow().date()
    row = db.scalar(select(AiUsage).where(AiUsage.user_id == user.id, AiUsage.usage_date == today, AiUsage.kind == kind))
    if row is None:
        row = AiUsage(user_id=user.id, usage_date=today, kind=kind, count=0)
        db.add(row)
        db.flush()
    return row


def used_today(db: Session, user: User, kind: str) -> int:
    today = utcnow().date()
    return db.scalar(select(AiUsage.count).where(AiUsage.user_id == user.id, AiUsage.usage_date == today, AiUsage.kind == kind)) or 0


def consume(db: Session, user: User, kind: str, limit: int) -> int:
    """Counts one use; returns how many remain today. limit <= 0 means unlimited."""
    if limit <= 0:
        return 10**6
    row = _row(db, user, kind)
    if row.count >= limit:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, f"Daily AI limit reached ({limit} per day). It resets tomorrow.")
    row.count += 1
    db.flush()
    return limit - row.count
