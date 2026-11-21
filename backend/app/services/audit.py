"""Audit trail for sensitive actions. Never records secrets."""
import uuid

from sqlalchemy.orm import Session

from app.models.user import AuditLog, User

_FORBIDDEN = ("password", "token", "secret", "code", "hash", "credential")


def _clean(details: dict) -> dict:
    out = {}
    for k, v in (details or {}).items():
        if any(w in k.lower() for w in _FORBIDDEN):
            continue
        out[k] = v if isinstance(v, (str, int, float, bool, type(None), list, dict)) else str(v)
    return out


def log_event(db: Session, action: str, actor: User | uuid.UUID | None = None, target: User | uuid.UUID | None = None, **details) -> AuditLog:
    actor_id = actor.id if isinstance(actor, User) else actor
    target_id = target.id if isinstance(target, User) else target
    row = AuditLog(actor_id=actor_id, target_user_id=target_id, action=action, details=_clean(details))
    db.add(row)
    db.flush()
    return row
