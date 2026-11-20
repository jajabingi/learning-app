"""Course management helpers shared by teacher routes and (later) the student portal."""
import re
import secrets
import uuid

from fastapi import HTTPException, status
from sqlalchemy import Integer, func, select
from sqlalchemy.orm import Session

from app.models.base import utcnow
from app.models.lms import LmsBlock, LmsCourse, LmsLesson, LmsModule
from app.models.question import Attachment
from app.models.user import User
from app.services.lms_blocks import decorate, student_view


def own_course(db: Session, user: User, course_id: uuid.UUID) -> LmsCourse:
    """Teachers reach only their own courses; admins reach all. 404 otherwise (no existence leak)."""
    c = db.get(LmsCourse, course_id)
    if c is None or (user.role != "admin" and c.owner_id != user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not found")
    return c


def own_module(db: Session, user: User, module_id: uuid.UUID) -> LmsModule:
    m = db.get(LmsModule, module_id)
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Module not found")
    own_course(db, user, m.course_id)
    return m


def own_lesson(db: Session, user: User, lesson_id: uuid.UUID) -> LmsLesson:
    les = db.get(LmsLesson, lesson_id)
    if les is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lesson not found")
    own_course(db, user, les.course_id)
    return les


def own_block(db: Session, user: User, block_id: uuid.UUID) -> LmsBlock:
    b = db.get(LmsBlock, block_id)
    if b is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Block not found")
    own_lesson(db, user, b.lesson_id)
    return b


def slugify(title: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or "course"
    return f"{base}-{secrets.token_hex(3)}"


def next_position(db: Session, model, *conds) -> int:
    m = db.scalar(select(func.max(model.position)).where(*conds))
    return 0 if m is None else m + 1


def apply_order(db: Session, items: list, ids: list[uuid.UUID]) -> None:
    """Set `position` from a full ordered id list; the list must contain exactly the existing ids."""
    if sorted(map(str, ids)) != sorted(str(i.id) for i in items):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "ids must list every item exactly once")
    by_id = {i.id: i for i in items}
    for pos, i in enumerate(ids):
        by_id[i].position = pos
    db.flush()


def normalise(items: list) -> None:
    for i, it in enumerate(items):
        it.position = i


def money(v) -> float | None:
    return None if v is None else float(v)


def course_out(c: LmsCourse, counts: dict | None = None) -> dict:
    d = {
        "id": str(c.id), "slug": c.slug, "title": c.title, "subtitle": c.subtitle, "description": c.description,
        "summary": c.summary, "cover_attachment_id": str(c.cover_attachment_id) if c.cover_attachment_id else None,
        "institution_id": str(c.institution_id) if c.institution_id else None, "instructor_name": c.instructor_name, "category": c.category, "difficulty": c.difficulty,
        "language": c.language, "status": c.status, "published_at": c.published_at.isoformat() if c.published_at else None,
        "price_amount": money(c.price_amount), "discount_amount": money(c.discount_amount), "currency": c.currency,
        "enrollment_type": c.enrollment_type, "payment_policy": c.payment_policy, "access_days": c.access_days,
        "objectives": c.objectives or [], "requirements": c.requirements or [], "target_audience": c.target_audience,
        "estimated_minutes": c.estimated_minutes, "completion_rule": c.completion_rule or {},
        "created_at": c.created_at.isoformat(), "updated_at": c.updated_at.isoformat(),
    }
    if counts is not None:
        d.update(counts)
    return d


def course_counts(db: Session, course_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict]:
    out = {i: {"module_count": 0, "lesson_count": 0, "published_lesson_count": 0, "enrollment_count": 0} for i in course_ids}
    if not course_ids:
        return out
    from app.models.lms import LmsEnrollment
    for cid, n in db.execute(select(LmsModule.course_id, func.count()).where(LmsModule.course_id.in_(course_ids)).group_by(LmsModule.course_id)):
        out[cid]["module_count"] = n
    for cid, n, pub in db.execute(select(LmsLesson.course_id, func.count(), func.sum(LmsLesson.is_published.cast(Integer)))
                                  .where(LmsLesson.course_id.in_(course_ids)).group_by(LmsLesson.course_id)):
        out[cid]["lesson_count"], out[cid]["published_lesson_count"] = n, int(pub or 0)
    for cid, n in db.execute(select(LmsEnrollment.course_id, func.count()).where(LmsEnrollment.course_id.in_(course_ids)).group_by(LmsEnrollment.course_id)):
        out[cid]["enrollment_count"] = n
    return out


def publish_problems(db: Session, c: LmsCourse) -> list[str]:
    """Reasons a course cannot be published yet (empty list = OK)."""
    problems = []
    if not c.title.strip():
        problems.append("The course needs a title")
    if c.enrollment_type == "paid" and (c.price_amount or 0) <= 0:
        problems.append("A paid course needs a price above zero")
    n = db.scalar(select(func.count()).select_from(LmsLesson).join(LmsModule, LmsModule.id == LmsLesson.module_id)
                  .where(LmsLesson.course_id == c.id, LmsLesson.is_published.is_(True), LmsModule.is_published.is_(True)))
    if not n:
        problems.append("Publish at least one lesson inside a published module")
    return problems


def cover_ok(db: Session, owner_id: uuid.UUID, attachment_id: uuid.UUID | None) -> None:
    if attachment_id is None:
        return
    a = db.get(Attachment, attachment_id)
    if a is None or a.user_id != owner_id or not a.content_type.startswith("image/"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Cover must be an image you uploaded")


def institution_ok(db: Session, user: User, institution_id: uuid.UUID | None) -> None:
    from app.models.lms import LmsInstitution
    if institution_id is None:
        return
    i = db.get(LmsInstitution, institution_id)
    if i is None or (user.role != "admin" and i.owner_id != user.id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Institution not found")


def lesson_brief(db: Session, les: LmsLesson, teacher: bool) -> dict:
    d = {"id": str(les.id), "title": les.title, "position": les.position, "estimated_minutes": les.estimated_minutes,
         "is_free_preview": les.is_free_preview}
    if teacher:
        d["is_published"] = les.is_published
    return d


def curriculum(db: Session, c: LmsCourse, *, teacher: bool) -> list[dict]:
    """Modules with lessons. teacher=True includes drafts and block counts; teacher=False only published items."""
    counts = dict(db.execute(select(LmsBlock.lesson_id, func.count()).join(LmsLesson, LmsLesson.id == LmsBlock.lesson_id)
                             .where(LmsLesson.course_id == c.id).group_by(LmsBlock.lesson_id)).all())
    out = []
    for m in c.modules:
        if not teacher and not m.is_published:
            continue
        lessons = []
        for les in m.lessons:
            if not teacher and not les.is_published:
                continue
            b = lesson_brief(db, les, teacher)
            if teacher:
                b["block_count"] = counts.get(les.id, 0)
            lessons.append(b)
        md = {"id": str(m.id), "title": m.title, "description": m.description, "summary": m.summary,
              "position": m.position, "lessons": lessons}
        if teacher:
            md["is_published"] = m.is_published
        out.append(md)
    return out


def lesson_detail(db: Session, les: LmsLesson, *, teacher: bool) -> dict:
    d = lesson_brief(db, les, teacher)
    d.update({"summary": les.summary, "module_id": str(les.module_id), "course_id": str(les.course_id)})
    if teacher:
        d["blocks"] = [{"id": str(b.id), "type": b.type, "position": b.position, "is_visible": b.is_visible, "data": decorate(b.type, b.data)}
                       for b in les.blocks]
    else:
        d["blocks"] = [student_view(db, b) for b in les.blocks if b.is_visible]
    return d


def duplicate_lesson(db: Session, les: LmsLesson) -> LmsLesson:
    copy = LmsLesson(course_id=les.course_id, module_id=les.module_id, title=(les.title + " (copy)")[:200],
                     summary=les.summary, estimated_minutes=les.estimated_minutes, is_free_preview=les.is_free_preview,
                     is_published=False, position=les.position + 1)
    for b in les.blocks:
        copy.blocks.append(LmsBlock(type=b.type, position=b.position, is_visible=b.is_visible, data=dict(b.data or {})))
    siblings = [x for x in db.scalars(select(LmsLesson).where(LmsLesson.module_id == les.module_id).order_by(LmsLesson.position))]
    for x in siblings:
        if x.position > les.position:
            x.position += 1
    db.add(copy)
    db.flush()
    return copy


def touch(course: LmsCourse) -> None:
    course.updated_at = utcnow()
