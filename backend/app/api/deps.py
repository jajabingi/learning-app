import uuid
from typing import Annotated, TypeVar

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import get_current_user
from app.models.user import User

DB = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
M = TypeVar("M")


def owned(db: Session, model: type[M], obj_id: uuid.UUID, user: User) -> M:
    """Fetch a row only if it belongs to `user`. Returns 404 (not 403) so ids can't be probed."""
    obj = db.scalar(select(model).where(model.id == obj_id, model.user_id == user.id))
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{model.__name__} not found")
    return obj


def owned_many(db: Session, model: type[M], ids: list[uuid.UUID], user: User) -> list[M]:
    ids = list(dict.fromkeys(ids))
    if not ids:
        return []
    rows = list(db.scalars(select(model).where(model.id.in_(ids), model.user_id == user.id)))
    if len(rows) != len(ids):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{model.__name__} not found")
    return rows


def check_owned_optional(db: Session, model, obj_id: uuid.UUID | None, user: User) -> None:
    if obj_id is not None:
        owned(db, model, obj_id, user)
