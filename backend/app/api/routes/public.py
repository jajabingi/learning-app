"""PUBLIC catalog (no login): institutions, their published courses, a course's public page and its free-preview
lessons. Exposes only marketing fields and outline titles — never lesson content, summaries or files of paid lessons.
Rate limited per IP."""
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.api.deps import DB
from app.core.security import public_limiter
from app.api.routes.notes import attachment_response
from app.models.lms import LmsBlock, LmsCourse, LmsInstitution, LmsLesson, LmsModule
from app.models.question import Attachment
from app.services import access, lms

router = APIRouter(prefix="/public", tags=["public"], dependencies=[Depends(public_limiter)])


def _card(db, c: LmsCourse) -> dict:
    inst = db.get(LmsInstitution, c.institution_id) if c.institution_id else None
    return {
        "id": str(c.id), "title": c.title, "subtitle": c.subtitle, "instructor_name": c.instructor_name, "category": c.category,
        "difficulty": c.difficulty, "language": c.language, "estimated_minutes": c.estimated_minutes,
        "enrollment_type": c.enrollment_type, "price_amount": lms.money(c.price_amount), "discount_amount": lms.money(c.discount_amount),
        "currency": c.currency, "access_days": c.access_days, "has_cover": c.cover_attachment_id is not None,
        "institution": {"id": str(inst.id), "slug": inst.slug, "name": inst.name} if inst and inst.is_published else None,
    }


def _published_course(db, course_id: uuid.UUID) -> LmsCourse:
    c = db.get(LmsCourse, course_id)
    if c is None or c.status != "published":
        raise access.NOT_FOUND
    return c


@router.get("/institutions")
def institutions(db: DB):
    out = []
    for i in db.scalars(select(LmsInstitution).where(LmsInstitution.is_published.is_(True)).order_by(LmsInstitution.position, LmsInstitution.name)):
        n = db.scalar(select(func.count()).select_from(LmsCourse).where(LmsCourse.institution_id == i.id, LmsCourse.status == "published"))
        out.append({"id": str(i.id), "slug": i.slug, "name": i.name, "description": i.description, "course_count": n})
    return out


@router.get("/institutions/{slug}")
def institution(slug: str, db: DB):
    i = db.scalar(select(LmsInstitution).where(LmsInstitution.slug == slug, LmsInstitution.is_published.is_(True)))
    if i is None:
        raise access.NOT_FOUND
    courses = db.scalars(select(LmsCourse).where(LmsCourse.institution_id == i.id, LmsCourse.status == "published").order_by(LmsCourse.title))
    return {"id": str(i.id), "slug": i.slug, "name": i.name, "description": i.description, "courses": [_card(db, c) for c in courses]}


@router.get("/courses")
def courses(db: DB, q: str | None = None):
    stmt = select(LmsCourse).where(LmsCourse.status == "published")
    if q:
        stmt = stmt.where(LmsCourse.title.ilike(f"%{q}%") | LmsCourse.subtitle.ilike(f"%{q}%") | LmsCourse.category.ilike(f"%{q}%"))
    return [_card(db, c) for c in db.scalars(stmt.order_by(LmsCourse.title).limit(100))]


@router.get("/courses/{course_id}")
def course_page(course_id: uuid.UUID, db: DB):
    c = _published_course(db, course_id)
    kinds: dict[str, set[str]] = {}
    for lid, btype in db.execute(select(LmsBlock.lesson_id, LmsBlock.type).join(LmsLesson, LmsLesson.id == LmsBlock.lesson_id)
                                 .where(LmsLesson.course_id == c.id, LmsBlock.is_visible.is_(True))).all():
        kinds.setdefault(str(lid), set()).add(btype)

    def kind_of(lid: str) -> list[str]:  # coarse lesson content kinds for the outline icons
        t = kinds.get(lid, set())
        return [k for k, group in (("video", {"video"}), ("quiz", {"quiz", "question", "assignment"}), ("file", {"pdf", "file", "resource"})) if t & group]

    outline = [{"title": m["title"], "description": m["description"],
                "lessons": [{"id": x["id"], "title": x["title"], "is_free_preview": x["is_free_preview"],
                             "estimated_minutes": x["estimated_minutes"], "kinds": kind_of(x["id"])} for x in m["lessons"]]}
               for m in lms.curriculum(db, c, teacher=False)]
    free = sum(1 for m in outline for x in m["lessons"] if x["is_free_preview"])
    return {**_card(db, c), "description": c.description, "objectives": c.objectives or [], "requirements": c.requirements or [],
            "target_audience": c.target_audience, "outline": outline, "free_lessons": free,
            "lesson_count": sum(len(m["lessons"]) for m in outline)}


@router.get("/courses/{course_id}/preview/{lesson_id}")
def free_lesson(course_id: uuid.UUID, lesson_id: uuid.UUID, db: DB):
    """A lesson flagged as a free preview, readable without an account (it must be published)."""
    c = _published_course(db, course_id)
    les = db.get(LmsLesson, lesson_id)
    m = db.get(LmsModule, les.module_id) if les else None
    if les is None or les.course_id != c.id or not les.is_free_preview or not les.is_published or not m or not m.is_published:
        raise access.NOT_FOUND
    return lms.lesson_detail(db, les, teacher=False)


@router.get("/courses/{course_id}/cover")
def course_cover(course_id: uuid.UUID, db: DB):
    """The cover image of a PUBLISHED course (images only), served without login so it can be used in <img> tags."""
    c = _published_course(db, course_id)
    a = db.get(Attachment, c.cover_attachment_id) if c.cover_attachment_id else None
    if a is None or not a.content_type.startswith("image/"):
        raise access.NOT_FOUND
    resp = attachment_response(a)
    resp.headers["Cache-Control"] = "public, max-age=300"
    return resp
