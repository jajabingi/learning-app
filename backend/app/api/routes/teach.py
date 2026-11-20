"""Teacher workspace: course management. Every route requires a staff account with the right permission,
and every object is resolved through own_* helpers (owner or admin only)."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select

from app.api.deps import DB
from app.core.permissions import P_COURSES_MANAGE, P_COURSES_PUBLISH, permissions_of, require_permission
from app.models.base import utcnow
from app.models.lms import LmsBlock, LmsCourse, LmsEnrollment, LmsLesson, LmsModule
from app.models.user import User
from app.schemas.lms import (
    BlockIn, BlockPatch, CourseCreate, CoursePatch, LessonIn, LessonPatch, ModuleIn, ModulePatch, ReorderIn, StatusIn,
)
from app.services import lms
from app.services.lms_blocks import BLOCK_TYPES, clean_block, decorate

manage = Depends(require_permission(P_COURSES_MANAGE))
router = APIRouter(prefix="/teach", tags=["teacher"], dependencies=[manage])
Teacher = Depends(require_permission(P_COURSES_MANAGE))


def _courses_query(user: User):
    q = select(LmsCourse)
    if user.role != "admin":
        q = q.where(LmsCourse.owner_id == user.id)
    return q


@router.get("/dashboard")
def dashboard(db: DB, user: User = Teacher):
    courses = list(db.scalars(_courses_query(user).order_by(LmsCourse.updated_at.desc())))
    counts = lms.course_counts(db, [c.id for c in courses])
    by_status = {s: sum(1 for c in courses if c.status == s) for s in ("draft", "published", "archived")}
    return {
        "courses": by_status | {"total": len(courses)},
        "modules": sum(v["module_count"] for v in counts.values()),
        "lessons": sum(v["lesson_count"] for v in counts.values()),
        "published_lessons": sum(v["published_lesson_count"] for v in counts.values()),
        "enrollments": sum(v["enrollment_count"] for v in counts.values()),
        "pending_requests": db.scalar(select(func.count()).select_from(LmsEnrollment).where(
            LmsEnrollment.status == "pending", LmsEnrollment.course_id.in_([c.id for c in courses]))) if courses else 0,
        "recent_courses": [lms.course_out(c, counts[c.id]) for c in courses[:5]],
    }


# ---------------- courses ----------------
@router.get("/courses")
def list_courses(db: DB, user: User = Teacher, status_: str | None = None):
    q = _courses_query(user)
    if status_:
        q = q.where(LmsCourse.status == status_)
    courses = list(db.scalars(q.order_by(LmsCourse.updated_at.desc())))
    counts = lms.course_counts(db, [c.id for c in courses])
    return [lms.course_out(c, counts[c.id]) for c in courses]


@router.post("/courses", status_code=201)
def create_course(data: CourseCreate, db: DB, user: User = Teacher):
    lms.cover_ok(db, user.id, data.cover_attachment_id)
    lms.institution_ok(db, user, data.institution_id)
    payload = data.model_dump(exclude={"completion_rule"})
    c = LmsCourse(owner_id=user.id, slug=lms.slugify(data.title), completion_rule=data.completion_rule.model_dump(),
                  status="draft", **payload)
    if not c.instructor_name:
        c.instructor_name = user.display_name
    db.add(c)
    db.flush()
    return lms.course_out(c, lms.course_counts(db, [c.id])[c.id])


@router.get("/courses/{course_id}")
def get_course(course_id: uuid.UUID, db: DB, user: User = Teacher):
    c = lms.own_course(db, user, course_id)
    return {**lms.course_out(c, lms.course_counts(db, [c.id])[c.id]), "curriculum": lms.curriculum(db, c, teacher=True)}


@router.patch("/courses/{course_id}")
def patch_course(course_id: uuid.UUID, data: CoursePatch, db: DB, user: User = Teacher):
    c = lms.own_course(db, user, course_id)
    changes = data.model_dump(exclude_unset=True)
    if "cover_attachment_id" in changes:
        lms.cover_ok(db, c.owner_id, changes["cover_attachment_id"])
    if "institution_id" in changes:
        lms.institution_ok(db, user, changes["institution_id"])
    for k, v in changes.items():
        if v is None and k not in ("discount_amount", "access_days", "cover_attachment_id", "institution_id"):
            continue  # null only clears the optional fields
        setattr(c, k, v if k != "completion_rule" else dict(v))
    if c.discount_amount is not None and c.discount_amount >= c.price_amount:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Discount price must be lower than the price")
    if c.enrollment_type == "free" and c.price_amount > 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A free course cannot have a price")
    if c.status == "published" and lms.publish_problems(db, c):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, lms.publish_problems(db, c)[0])
    lms.touch(c)
    db.flush()
    return lms.course_out(c, lms.course_counts(db, [c.id])[c.id])


@router.post("/courses/{course_id}/status")
def set_status(course_id: uuid.UUID, data: StatusIn, db: DB, user: User = Depends(require_permission(P_COURSES_PUBLISH))):
    c = lms.own_course(db, user, course_id)
    if data.status == "published":
        problems = lms.publish_problems(db, c)
        if problems:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Cannot publish: " + "; ".join(problems))
        c.published_at = c.published_at or utcnow()
    c.status = data.status
    lms.touch(c)
    return lms.course_out(c, lms.course_counts(db, [c.id])[c.id])


@router.delete("/courses/{course_id}", status_code=204)
def delete_course(course_id: uuid.UUID, db: DB, user: User = Teacher):
    c = lms.own_course(db, user, course_id)
    n = db.scalar(select(func.count()).select_from(LmsEnrollment).where(LmsEnrollment.course_id == c.id))
    if n:
        raise HTTPException(status.HTTP_409_CONFLICT, "This course has enrollments. Archive it instead of deleting it.")
    db.delete(c)


# ---------------- modules ----------------
@router.post("/courses/{course_id}/modules", status_code=201)
def create_module(course_id: uuid.UUID, data: ModuleIn, db: DB, user: User = Teacher):
    c = lms.own_course(db, user, course_id)
    m = LmsModule(course_id=c.id, position=lms.next_position(db, LmsModule, LmsModule.course_id == c.id), **data.model_dump())
    db.add(m)
    lms.touch(c)
    db.flush()
    return {"id": str(m.id), "title": m.title, "position": m.position, "is_published": m.is_published, "lessons": []}


@router.post("/courses/{course_id}/modules/reorder", status_code=204)
def reorder_modules(course_id: uuid.UUID, data: ReorderIn, db: DB, user: User = Teacher):
    c = lms.own_course(db, user, course_id)
    lms.apply_order(db, list(c.modules), data.ids)


@router.patch("/modules/{module_id}")
def patch_module(module_id: uuid.UUID, data: ModulePatch, db: DB, user: User = Teacher):
    m = lms.own_module(db, user, module_id)
    for k, v in data.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(m, k, v)
    if data.is_published is False:  # un-publishing the last published module of a live course is blocked
        c = db.get(LmsCourse, m.course_id)
        db.flush()
        if c.status == "published" and lms.publish_problems(db, c):
            raise HTTPException(status.HTTP_409_CONFLICT, "The course is published; unpublish the course first or keep another published lesson")
    return {"id": str(m.id), "title": m.title, "is_published": m.is_published}


@router.delete("/modules/{module_id}", status_code=204)
def delete_module(module_id: uuid.UUID, db: DB, user: User = Teacher):
    m = lms.own_module(db, user, module_id)
    c = db.get(LmsCourse, m.course_id)
    db.delete(m)
    db.flush()
    db.expire(c)
    if c.status == "published" and lms.publish_problems(db, c):
        raise HTTPException(status.HTTP_409_CONFLICT, "This would leave the published course without published lessons")


# ---------------- lessons ----------------
@router.post("/modules/{module_id}/lessons", status_code=201)
def create_lesson(module_id: uuid.UUID, data: LessonIn, db: DB, user: User = Teacher):
    m = lms.own_module(db, user, module_id)
    les = LmsLesson(course_id=m.course_id, module_id=m.id, position=lms.next_position(db, LmsLesson, LmsLesson.module_id == m.id), **data.model_dump())
    db.add(les)
    db.flush()
    return lms.lesson_detail(db, les, teacher=True)


@router.post("/modules/{module_id}/lessons/reorder", status_code=204)
def reorder_lessons(module_id: uuid.UUID, data: ReorderIn, db: DB, user: User = Teacher):
    m = lms.own_module(db, user, module_id)
    lms.apply_order(db, list(m.lessons), data.ids)


@router.get("/lessons/{lesson_id}")
def get_lesson(lesson_id: uuid.UUID, db: DB, user: User = Teacher):
    return lms.lesson_detail(db, lms.own_lesson(db, user, lesson_id), teacher=True)


@router.patch("/lessons/{lesson_id}")
def patch_lesson(lesson_id: uuid.UUID, data: LessonPatch, db: DB, user: User = Teacher):
    les = lms.own_lesson(db, user, lesson_id)
    ch = data.model_dump(exclude_unset=True)
    new_module = ch.pop("module_id", None)
    for k, v in ch.items():
        if v is not None:
            setattr(les, k, v)
    if new_module and new_module != les.module_id:
        target = lms.own_module(db, user, new_module)
        if target.course_id != les.course_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A lesson can only move within its course")
        les.module_id = target.id
        les.position = lms.next_position(db, LmsLesson, LmsLesson.module_id == target.id)
    db.flush()
    c = db.get(LmsCourse, les.course_id)
    db.expire(c)
    if "is_published" in ch and c.status == "published" and lms.publish_problems(db, c):
        raise HTTPException(status.HTTP_409_CONFLICT, "The course is published; keep at least one published lesson or unpublish the course first")
    return lms.lesson_detail(db, les, teacher=True)


@router.delete("/lessons/{lesson_id}", status_code=204)
def delete_lesson(lesson_id: uuid.UUID, db: DB, user: User = Teacher):
    les = lms.own_lesson(db, user, lesson_id)
    c = db.get(LmsCourse, les.course_id)
    db.delete(les)
    db.flush()
    db.expire(c)
    if c.status == "published" and lms.publish_problems(db, c):
        raise HTTPException(status.HTTP_409_CONFLICT, "This would leave the published course without published lessons")


@router.post("/lessons/{lesson_id}/duplicate", status_code=201)
def duplicate_lesson(lesson_id: uuid.UUID, db: DB, user: User = Teacher):
    return lms.lesson_detail(db, lms.duplicate_lesson(db, lms.own_lesson(db, user, lesson_id)), teacher=True)


# ---------------- blocks ----------------
@router.get("/block-types")
def block_types():
    return list(BLOCK_TYPES)


@router.post("/lessons/{lesson_id}/blocks", status_code=201)
def create_block(lesson_id: uuid.UUID, data: BlockIn, db: DB, user: User = Teacher):
    les = lms.own_lesson(db, user, lesson_id)
    owner = db.get(LmsCourse, les.course_id).owner_id
    cleaned = clean_block(db, owner, data.type, data.data)
    blocks = list(les.blocks)
    b = LmsBlock(lesson_id=les.id, type=data.type, data=cleaned, is_visible=data.is_visible)
    idx = len(blocks) if data.position is None else min(data.position, len(blocks))
    blocks.insert(idx, b)
    lms.normalise(blocks)
    db.add(b)
    db.flush()
    return {"id": str(b.id), "type": b.type, "position": b.position, "is_visible": b.is_visible, "data": decorate(b.type, b.data)}


@router.post("/lessons/{lesson_id}/blocks/reorder", status_code=204)
def reorder_blocks(lesson_id: uuid.UUID, data: ReorderIn, db: DB, user: User = Teacher):
    les = lms.own_lesson(db, user, lesson_id)
    lms.apply_order(db, list(les.blocks), data.ids)


@router.patch("/blocks/{block_id}")
def patch_block(block_id: uuid.UUID, data: BlockPatch, db: DB, user: User = Teacher):
    b = lms.own_block(db, user, block_id)
    if data.data is not None:
        owner = db.get(LmsCourse, db.get(LmsLesson, b.lesson_id).course_id).owner_id
        b.data = clean_block(db, owner, b.type, data.data)
    if data.is_visible is not None:
        b.is_visible = data.is_visible
    db.flush()
    return {"id": str(b.id), "type": b.type, "position": b.position, "is_visible": b.is_visible, "data": decorate(b.type, b.data)}


@router.delete("/blocks/{block_id}", status_code=204)
def delete_block(block_id: uuid.UUID, db: DB, user: User = Teacher):
    b = lms.own_block(db, user, block_id)
    les = db.get(LmsLesson, b.lesson_id)
    db.delete(b)
    db.flush()
    db.expire(les)
    lms.normalise(list(les.blocks))


@router.post("/blocks/{block_id}/duplicate", status_code=201)
def duplicate_block(block_id: uuid.UUID, db: DB, user: User = Teacher):
    b = lms.own_block(db, user, block_id)
    les = db.get(LmsLesson, b.lesson_id)
    blocks = list(les.blocks)
    copy = LmsBlock(lesson_id=les.id, type=b.type, data=dict(b.data or {}), is_visible=b.is_visible)
    blocks.insert(blocks.index(b) + 1, copy)
    lms.normalise(blocks)
    db.add(copy)
    db.flush()
    return {"id": str(copy.id), "type": copy.type, "position": copy.position, "is_visible": copy.is_visible, "data": decorate(copy.type, copy.data)}


# ---------------- preview as a student ----------------
@router.get("/courses/{course_id}/preview")
def preview_course(course_id: uuid.UUID, db: DB, user: User = Teacher, include_drafts: bool = True):
    """The course exactly as a student would receive it. `include_drafts` shows unpublished modules/lessons (flagged)."""
    c = lms.own_course(db, user, course_id)
    cur = lms.curriculum(db, c, teacher=include_drafts)
    return {**{k: v for k, v in lms.course_out(c).items() if k not in ("created_at", "updated_at")},
            "curriculum": cur, "preview": True, "includes_drafts": include_drafts}


@router.get("/lessons/{lesson_id}/preview")
def preview_lesson(lesson_id: uuid.UUID, db: DB, user: User = Teacher):
    les = lms.own_lesson(db, user, lesson_id)
    d = lms.lesson_detail(db, les, teacher=False)  # student projection (hidden blocks removed, answers stripped)
    d["is_published"] = les.is_published
    return d | {"preview": True}


@router.get("/permissions/me")
def my_permissions(db: DB, user: User = Teacher):
    return sorted(permissions_of(db, user))
