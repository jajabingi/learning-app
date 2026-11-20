"""Teacher workspace: institutions (universities / schools / brands) that group courses on the public landing page."""
import re
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import DB
from app.core.permissions import P_COURSES_MANAGE, require_permission
from app.models.lms import LmsCourse, LmsInstitution
from app.models.user import User
from app.services import lms

router = APIRouter(prefix="/teach/institutions", tags=["teacher-institutions"], dependencies=[Depends(require_permission(P_COURSES_MANAGE))])
Teacher = Depends(require_permission(P_COURSES_MANAGE))


class InstIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    is_published: bool = False


class InstPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    is_published: bool | None = None


def _own(db, user: User, inst_id: uuid.UUID) -> LmsInstitution:
    i = db.get(LmsInstitution, inst_id)
    if i is None or (user.role != "admin" and i.owner_id != user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Institution not found")
    return i


def _out(db, i: LmsInstitution) -> dict:
    n = db.scalar(select(func.count()).select_from(LmsCourse).where(LmsCourse.institution_id == i.id))
    return {"id": str(i.id), "slug": i.slug, "name": i.name, "description": i.description, "is_published": i.is_published, "course_count": n}


@router.get("")
def list_institutions(db: DB, user: User = Teacher):
    q = select(LmsInstitution)
    if user.role != "admin":
        q = q.where(LmsInstitution.owner_id == user.id)
    return [_out(db, i) for i in db.scalars(q.order_by(LmsInstitution.position, LmsInstitution.name))]


@router.post("", status_code=201)
def create_institution(data: InstIn, db: DB, user: User = Teacher):
    base = re.sub(r"[^a-z0-9]+", "-", data.name.lower()).strip("-")[:40] or "inst"
    i = LmsInstitution(owner_id=user.id, slug=f"{base}-{secrets.token_hex(3)}", position=lms.next_position(db, LmsInstitution), **data.model_dump())
    db.add(i)
    db.flush()
    return _out(db, i)


@router.patch("/{inst_id}")
def patch_institution(inst_id: uuid.UUID, data: InstPatch, db: DB, user: User = Teacher):
    i = _own(db, user, inst_id)
    for k, v in data.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(i, k, v)
    db.flush()
    return _out(db, i)


@router.delete("/{inst_id}", status_code=204)
def delete_institution(inst_id: uuid.UUID, db: DB, user: User = Teacher):
    db.delete(_own(db, user, inst_id))  # its courses are kept (institution_id becomes empty)
