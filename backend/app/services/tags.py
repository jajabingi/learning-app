from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.knowledge import Tag
from app.models.user import User

PALETTE = ["#6366f1", "#0ea5e9", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#14b8a6"]


def normalize(name: str) -> str:
    return " ".join(name.strip().lower().split())[:60]


def resolve_tags(db: Session, user: User, names: list[str]) -> list[Tag]:
    """Return Tag rows for the given names, creating missing ones."""
    wanted = list(dict.fromkeys(n for n in (normalize(x) for x in names) if n))
    if not wanted:
        return []
    existing = {t.name: t for t in db.scalars(select(Tag).where(Tag.user_id == user.id, Tag.name.in_(wanted)))}
    out = []
    for i, name in enumerate(wanted):
        tag = existing.get(name)
        if tag is None:
            tag = Tag(user_id=user.id, name=name, color=PALETTE[hash(name) % len(PALETTE)])
            db.add(tag)
            db.flush()
        out.append(tag)
    return out
