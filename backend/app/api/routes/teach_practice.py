"""Teacher workspace: topic-based practice sets / exams. Questions are picked from the teacher's PRIVATE bank; only the
questions placed in a published set ever reach students (see student.py)."""
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import DB
from app.core.permissions import P_COURSES_MANAGE, require_permission
from app.models.lms import LmsCourse, LmsPracticeItem, LmsPracticeSet
from app.models.question import Question
from app.models.user import User
from app.schemas.lms import ReorderIn
from app.services import lms

router = APIRouter(prefix="/teach", tags=["teacher-practice"], dependencies=[Depends(require_permission(P_COURSES_MANAGE))])
Teacher = Depends(require_permission(P_COURSES_MANAGE))


def _own_set(db, user: User, set_id: uuid.UUID) -> LmsPracticeSet:
    s = db.get(LmsPracticeSet, set_id)
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Practice set not found")
    lms.own_course(db, user, s.course_id)
    return s


def _out(db, s: LmsPracticeSet) -> dict:
    qs = {q.id: q for q in db.scalars(select(Question).where(Question.id.in_([i.question_id for i in s.items])))} if s.items else {}
    return {"id": str(s.id), "course_id": str(s.course_id), "title": s.title, "description": s.description, "kind": s.kind,
            "position": s.position, "is_published": s.is_published, "question_count": len(s.items),
            "items": [{"id": str(i.id), "question_id": str(i.question_id), "position": i.position,
                       "title": (qs[i.question_id].title or qs[i.question_id].content[:80]) if i.question_id in qs else "",
                       "question_type": qs[i.question_id].question_type if i.question_id in qs else ""} for i in s.items]}


class SetIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=20000)
    kind: Literal["practice", "exam"] = "practice"


class SetPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=20000)
    kind: Literal["practice", "exam"] | None = None
    is_published: bool | None = None


class AddItems(BaseModel):
    question_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)


@router.get("/courses/{course_id}/practice-sets")
def list_sets(course_id: uuid.UUID, db: DB, user: User = Teacher):
    c = lms.own_course(db, user, course_id)
    return [_out(db, s) for s in db.scalars(select(LmsPracticeSet).where(LmsPracticeSet.course_id == c.id).order_by(LmsPracticeSet.position))]


@router.post("/courses/{course_id}/practice-sets", status_code=201)
def create_set(course_id: uuid.UUID, data: SetIn, db: DB, user: User = Teacher):
    c = lms.own_course(db, user, course_id)
    s = LmsPracticeSet(course_id=c.id, position=lms.next_position(db, LmsPracticeSet, LmsPracticeSet.course_id == c.id), **data.model_dump())
    db.add(s)
    db.flush()
    return _out(db, s)


@router.post("/courses/{course_id}/practice-sets/reorder", status_code=204)
def reorder_sets(course_id: uuid.UUID, data: ReorderIn, db: DB, user: User = Teacher):
    c = lms.own_course(db, user, course_id)
    lms.apply_order(db, list(db.scalars(select(LmsPracticeSet).where(LmsPracticeSet.course_id == c.id))), data.ids)


@router.patch("/practice-sets/{set_id}")
def patch_set(set_id: uuid.UUID, data: SetPatch, db: DB, user: User = Teacher):
    s = _own_set(db, user, set_id)
    for k, v in data.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(s, k, v)
    if s.is_published and not s.items:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Add at least one question before publishing")
    db.flush()
    return _out(db, s)


@router.delete("/practice-sets/{set_id}", status_code=204)
def delete_set(set_id: uuid.UUID, db: DB, user: User = Teacher):
    db.delete(_own_set(db, user, set_id))


@router.post("/practice-sets/{set_id}/items", status_code=201)
def add_items(set_id: uuid.UUID, data: AddItems, db: DB, user: User = Teacher):
    s = _own_set(db, user, set_id)
    owner = db.get(LmsCourse, s.course_id).owner_id
    ids = list(dict.fromkeys(data.question_ids))
    found = set(db.scalars(select(Question.id).where(Question.id.in_(ids), Question.user_id == owner)))
    if len(found) != len(ids):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Some questions were not found in your question bank")
    have = {i.question_id for i in s.items}
    pos = len(s.items)
    for qid in ids:
        if qid not in have:
            db.add(LmsPracticeItem(set_id=s.id, question_id=qid, position=pos))
            pos += 1
    db.flush()
    db.expire(s)
    return _out(db, s)


@router.post("/practice-sets/{set_id}/items/reorder", status_code=204)
def reorder_items(set_id: uuid.UUID, data: ReorderIn, db: DB, user: User = Teacher):
    s = _own_set(db, user, set_id)
    lms.apply_order(db, list(s.items), data.ids)


@router.delete("/practice-items/{item_id}", status_code=204)
def delete_item(item_id: uuid.UUID, db: DB, user: User = Teacher):
    it = db.get(LmsPracticeItem, item_id)
    if it is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    s = _own_set(db, user, it.set_id)
    db.delete(it)
    db.flush()
    db.expire(s)
    lms.normalise(list(s.items))
    if s.is_published and not s.items:
        s.is_published = False
