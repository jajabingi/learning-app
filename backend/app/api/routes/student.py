"""Student portal API. Every route requires a student account; course content additionally requires a valid
enrollment (see services/access.py). The catalog exposes only public marketing fields — never lesson content."""
import re
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DB
from app.api.routes.notes import attachment_response
from app.core.permissions import require_student
from app.models.base import as_utc, utcnow
from app.models.lms import LmsBlock, LmsCourse, LmsEnrollment, LmsLesson, LmsModule
from app.models.question import Attachment
from app.models.user import User
from app.services import access, lms, progress

router = APIRouter(prefix="/student", tags=["student"], dependencies=[Depends(require_student)])
Student = Depends(require_student)


def _money(c: LmsCourse) -> dict:
    return {"price_amount": lms.money(c.price_amount), "discount_amount": lms.money(c.discount_amount), "currency": c.currency}


def _card(c: LmsCourse, e: LmsEnrollment | None) -> dict:
    has_access = access.enrollment_grants_access(e)
    return {
        "id": str(c.id), "title": c.title, "subtitle": c.subtitle, "instructor_name": c.instructor_name,
        "category": c.category, "difficulty": c.difficulty, "language": c.language,
        "estimated_minutes": c.estimated_minutes, "enrollment_type": c.enrollment_type, **_money(c),
        "enrollment_status": e.status if e else None, "has_access": has_access,
        # only free courses can be joined without the teacher; paid ones await the payments release
        "can_self_enroll": e is None and c.enrollment_type == "free",
    }


# ---------------- my courses & dashboard ----------------
@router.get("/courses")
def my_courses(db: DB, user: User = Student):
    """Only courses with a currently valid enrollment — never merely because the account exists."""
    out = []
    for c, e in access.student_enrolled_courses(db, user):
        p = progress.course_progress(db, user.id, c)
        out.append({**_card(c, e), "expires_at": as_utc(e.expires_at).isoformat() if e.expires_at else None,
                    "progress": {k: p[k] for k in ("percent", "completed_lessons", "total_lessons", "resume_lesson_id", "last_activity_at")}})
    return out


@router.get("/dashboard")
def dashboard(db: DB, user: User = Student):
    courses = []
    for c, e in access.student_enrolled_courses(db, user):
        p = progress.course_progress(db, user.id, c)
        courses.append({**_card(c, e), "progress": p})
    started = [c for c in courses if c["progress"]["last_activity_at"] and c["progress"]["percent"] < 100]
    started.sort(key=lambda c: c["progress"]["last_activity_at"], reverse=True)
    cont = started[0] if started else next((c for c in courses if c["progress"]["percent"] < 100 and c["progress"]["total_lessons"]), None)
    titles = {}
    if cont:
        for les in progress.visible_lessons(db, uuid.UUID(cont["id"])):
            titles[str(les.id)] = les.title
    return {
        "continue_learning": ({"course_id": cont["id"], "course_title": cont["title"], "lesson_id": cont["progress"]["resume_lesson_id"],
                               "lesson_title": titles.get(cont["progress"]["resume_lesson_id"] or ""), "percent": cont["progress"]["percent"]} if cont and cont["progress"]["resume_lesson_id"] else None),
        "courses": [{**{k: v for k, v in c.items() if k != "progress"},
                     "progress": {k: c["progress"][k] for k in ("percent", "completed_lessons", "total_lessons", "resume_lesson_id", "next_lesson_id", "time_spent_seconds")}} for c in courses],
        "totals": {"courses": len(courses), "completed_courses": sum(1 for c in courses if c["enrollment_status"] == "completed"),
                   "lessons_completed": sum(c["progress"]["completed_lessons"] for c in courses),
                   "time_spent_seconds": sum(c["progress"]["time_spent_seconds"] for c in courses)},
    }


@router.get("/courses/{course_id}")
def my_course(course_id: uuid.UUID, db: DB, user: User = Student):
    c, e = access.student_course(db, user, course_id)
    base = {k: v for k, v in lms.course_out(c).items() if k not in ("created_at", "updated_at", "slug", "status", "enrollment_type", "payment_policy")}
    p = progress.course_progress(db, user.id, c)
    cur = lms.curriculum(db, c, teacher=False)
    done = set(p["completed_ids"])
    for m in cur:
        for les in m["lessons"]:
            les["completed"] = les["id"] in done
    return {**base, "enrollment_status": e.status, "curriculum": cur, "progress": p}


@router.get("/lessons/{lesson_id}")
def my_lesson(lesson_id: uuid.UUID, db: DB, user: User = Student):
    _course, _module, lesson = access.student_lesson(db, user, lesson_id)
    row = progress.progress_rows(db, user.id, lesson.course_id).get(lesson.id)
    return {**lms.lesson_detail(db, lesson, teacher=False), "completed": bool(row and row.completed_at)}


class PingIn(BaseModel):
    seconds: int = Field(default=0, ge=0, le=120)  # time since the last ping; capped so it cannot be inflated


@router.post("/lessons/{lesson_id}/progress")
def ping(lesson_id: uuid.UUID, data: PingIn, db: DB, user: User = Student):
    """Called when a lesson is opened (seconds=0) and periodically while it is open."""
    _c, _m, lesson = access.student_lesson(db, user, lesson_id)
    p = progress.touch_lesson(db, user.id, lesson, data.seconds)
    return {"time_spent_seconds": p.time_spent_seconds}


class CompleteIn(BaseModel):
    completed: bool = True


@router.post("/lessons/{lesson_id}/complete")
def complete(lesson_id: uuid.UUID, data: CompleteIn, db: DB, user: User = Student):
    course, _m, lesson = access.student_lesson(db, user, lesson_id)
    enr = access.get_enrollment(db, user, course.id)
    p = progress.touch_lesson(db, user.id, lesson)
    p.completed_at = utcnow() if data.completed else None
    db.flush()
    progress.sync_completion(db, enr, course)
    prog = progress.course_progress(db, user.id, course)
    return {"completed": data.completed, "course_percent": prog["percent"], "course_completed": enr.status == "completed",
            "next_lesson_id": prog["next_lesson_id"]}


# ---------------- catalog & enrollment ----------------
def _published_course(db, course_id: uuid.UUID) -> LmsCourse:
    c = db.get(LmsCourse, course_id)
    if c is None or c.status != "published":
        raise access.NOT_FOUND
    return c


@router.get("/catalog")
def catalog(db: DB, user: User = Student, q: str | None = None):
    stmt = select(LmsCourse).where(LmsCourse.status == "published")
    if q:
        stmt = stmt.where(LmsCourse.title.ilike(f"%{q}%") | LmsCourse.subtitle.ilike(f"%{q}%") | LmsCourse.category.ilike(f"%{q}%"))
    courses = list(db.scalars(stmt.order_by(LmsCourse.title).limit(200)))
    enr = {e.course_id: e for e in db.scalars(select(LmsEnrollment).where(LmsEnrollment.student_id == user.id))}
    return [_card(c, enr.get(c.id)) for c in courses]


@router.get("/catalog/{course_id}")
def catalog_detail(course_id: uuid.UUID, db: DB, user: User = Student):
    """Public course page: marketing fields and the outline (titles only). No lesson content, no summaries."""
    c = _published_course(db, course_id)
    e = access.get_enrollment(db, user, c.id)
    outline = [{"title": m["title"], "lessons": [{"id": les["id"], "title": les["title"], "is_free_preview": les["is_free_preview"]} for les in m["lessons"]]}
               for m in lms.curriculum(db, c, teacher=False)]
    return {**_card(c, e), "description": c.description, "objectives": c.objectives or [], "requirements": c.requirements or [],
            "target_audience": c.target_audience, "access_days": c.access_days, "outline": outline}


@router.get("/catalog/{course_id}/preview/{lesson_id}")
def free_preview(course_id: uuid.UUID, lesson_id: uuid.UUID, db: DB, user: User = Student):
    """A lesson the teacher flagged as a free preview may be read without enrollment (still must be published)."""
    c = _published_course(db, course_id)
    les = db.get(LmsLesson, lesson_id)
    m = db.get(LmsModule, les.module_id) if les else None
    if les is None or les.course_id != c.id or not les.is_free_preview or not les.is_published or not m or not m.is_published:
        raise access.NOT_FOUND
    return lms.lesson_detail(db, les, teacher=False)


@router.post("/courses/{course_id}/enroll", status_code=201)
def self_enroll(course_id: uuid.UUID, db: DB, user: User = Student):
    """Self-service enrollment, allowed ONLY for free courses. Paid / manual courses are granted by the teacher or
    after verified payment — a student can never enroll themselves in them."""
    c = _published_course(db, course_id)
    if c.enrollment_type != "free":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This course is not open for self-enrollment")
    e = access.get_enrollment(db, user, c.id)
    if e is not None:
        if access.enrollment_grants_access(e):
            return {"id": str(e.id), "status": e.status}
        raise HTTPException(status.HTTP_409_CONFLICT, "Your access to this course was changed by your teacher. Please contact them.")
    now = utcnow()
    e = LmsEnrollment(student_id=user.id, course_id=c.id, status="active", source="free", starts_at=now,
                      expires_at=now + timedelta(days=c.access_days) if c.access_days else None)
    db.add(e)
    db.flush()
    return {"id": str(e.id), "status": e.status}


# ---------------- files ----------------
@router.get("/files/{attachment_id}")
def my_file(attachment_id: uuid.UUID, db: DB, user: User = Student):
    """A file is served only if a visible block (or the cover) of a published course the student is validly
    enrolled in references it. Knowing an attachment id is never enough."""
    wanted = str(attachment_id)
    for course, _enr in access.student_enrolled_courses(db, user):
        if course.cover_attachment_id and str(course.cover_attachment_id) == wanted:
            break
        blocks = db.scalars(
            select(LmsBlock).join(LmsLesson, LmsLesson.id == LmsBlock.lesson_id)
            .join(LmsModule, LmsModule.id == LmsLesson.module_id)
            .where(LmsLesson.course_id == course.id, LmsLesson.is_published.is_(True), LmsModule.is_published.is_(True),
                   LmsBlock.is_visible.is_(True)))
        if any(wanted == str((b.data or {}).get("attachment_id")) or wanted in _markdown_refs(b.data) for b in blocks):
            break
    else:
        raise HTTPException(404, "Not found")
    att = db.get(Attachment, attachment_id)
    if att is None:
        raise HTTPException(404, "Not found")
    return attachment_response(att)


_ATT = re.compile(r"/api/attachments/([0-9a-f-]{36})/file")


def _markdown_refs(data) -> set[str]:
    """Attachment ids embedded in a block's Markdown fields (images/links inserted by the editor)."""
    out: set[str] = set()
    for v in (data or {}).values():
        if isinstance(v, str):
            out.update(_ATT.findall(v))
    return out


# ---------------- practice by topic ----------------
from app.models.lms import LmsPracticeAttempt, LmsPracticeItem, LmsPracticeSet  # noqa: E402
from app.models.question import Question  # noqa: E402
from app.services.lms_blocks import _question_view  # noqa: E402


def _student_set(db, user: User, set_id: uuid.UUID) -> tuple[LmsCourse, LmsPracticeSet]:
    s = db.get(LmsPracticeSet, set_id)
    if s is None or not s.is_published:
        raise access.NOT_FOUND
    course, _enr = access.student_course(db, user, s.course_id)  # enrollment + published course, else 404
    return course, s


def _student_item(db, user: User, item_id: uuid.UUID) -> tuple[LmsPracticeSet, LmsPracticeItem]:
    it = db.get(LmsPracticeItem, item_id)
    if it is None:
        raise access.NOT_FOUND
    _c, s = _student_set(db, user, it.set_id)
    return s, it


def _solution(q: Question) -> dict:
    return {"answer": q.answer.answer if q.answer else "", "explanation": q.answer.explanation if q.answer else "",
            "correct_option_ids": [str(o.id) for o in q.options if o.is_correct]}


@router.get("/practice")
def practice_overview(db: DB, user: User = Student):
    """Published practice sets of every course the student is validly enrolled in, with their own progress."""
    out = []
    for course, _e in access.student_enrolled_courses(db, user):
        sets = list(db.scalars(select(LmsPracticeSet).where(LmsPracticeSet.course_id == course.id, LmsPracticeSet.is_published.is_(True))
                               .order_by(LmsPracticeSet.position)))
        rows = []
        for s in sets:
            ids = [i.id for i in s.items]
            att = list(db.scalars(select(LmsPracticeAttempt).where(LmsPracticeAttempt.student_id == user.id, LmsPracticeAttempt.item_id.in_(ids)))) if ids else []
            rows.append({"id": str(s.id), "title": s.title, "description": s.description, "kind": s.kind, "total": len(ids),
                         "revealed": len(att), "correct": sum(1 for a in att if a.is_correct)})
        if rows:
            out.append({"course_id": str(course.id), "course_title": course.title, "sets": rows})
    return out


@router.get("/practice/sets/{set_id}")
def practice_set(set_id: uuid.UUID, db: DB, user: User = Student):
    """Questions WITHOUT answers or correctness. A solution is included only for items the student already revealed."""
    course, s = _student_set(db, user, set_id)
    qs = {q.id: q for q in db.scalars(select(Question).where(Question.id.in_([i.question_id for i in s.items])))} if s.items else {}
    att = {a.item_id: a for a in db.scalars(select(LmsPracticeAttempt).where(
        LmsPracticeAttempt.student_id == user.id, LmsPracticeAttempt.item_id.in_([i.id for i in s.items])))} if s.items else {}
    items = []
    for it in s.items:
        q = qs.get(it.question_id)
        if q is None:
            continue
        a = att.get(it.id)
        items.append({"item_id": str(it.id), "position": it.position, "question": _question_view(q, include_answer=False),
                      "revealed": a is not None, "selected_option_ids": a.selected_option_ids if a else None,
                      "is_correct": a.is_correct if a else None, "solution": _solution(q) if a else None})
    return {"id": str(s.id), "title": s.title, "description": s.description, "kind": s.kind, "course_id": str(course.id),
            "course_title": course.title, "items": items}


class RevealIn(BaseModel):
    selected_option_ids: list[uuid.UUID] | None = None


@router.post("/practice/items/{item_id}/reveal")
def reveal(item_id: uuid.UUID, data: RevealIn, db: DB, user: User = Student):
    """The ONLY way a solution is delivered. Records the attempt (and correctness for multiple-choice questions)."""
    _s, it = _student_item(db, user, item_id)
    q = db.get(Question, it.question_id)
    att = db.scalar(select(LmsPracticeAttempt).where(LmsPracticeAttempt.student_id == user.id, LmsPracticeAttempt.item_id == it.id))
    if att is None:
        selected, correct = None, None
        if data.selected_option_ids is not None and q.options:
            valid = {o.id for o in q.options}
            if not set(data.selected_option_ids) <= valid:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown option selected")
            selected = [str(i) for i in data.selected_option_ids]
            correct = set(data.selected_option_ids) == {o.id for o in q.options if o.is_correct}
        att = LmsPracticeAttempt(student_id=user.id, item_id=it.id, selected_option_ids=selected, is_correct=correct, revealed_at=utcnow())
        db.add(att)
        db.flush()
    return {"is_correct": att.is_correct, "selected_option_ids": att.selected_option_ids, **_solution(q)}


@router.post("/practice/items/{item_id}/reset", status_code=204)
def reset_item(item_id: uuid.UUID, db: DB, user: User = Student):
    """Let the student try the question again (their own attempt only)."""
    _s, it = _student_item(db, user, item_id)
    att = db.scalar(select(LmsPracticeAttempt).where(LmsPracticeAttempt.student_id == user.id, LmsPracticeAttempt.item_id == it.id))
    if att:
        db.delete(att)


@router.post("/courses/{course_id}/request-access", status_code=201)
def request_access(course_id: uuid.UUID, db: DB, user: User = Student):
    """Ask to buy / join a non-free course. Creates a PENDING enrollment, which grants nothing: the teacher activates it
    once payment is confirmed. (Online card payment arrives with the payments release.)"""
    c = _published_course(db, course_id)
    if c.enrollment_type == "free":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This course is free: enroll directly")
    e = access.get_enrollment(db, user, c.id)
    if e is not None:
        if access.enrollment_grants_access(e) or e.status == "pending":
            return {"id": str(e.id), "status": e.status}
        if e.status == "expired":
            e.status = "pending"
            return {"id": str(e.id), "status": e.status}
        raise HTTPException(status.HTTP_409_CONFLICT, "Your access to this course was changed by your teacher. Please contact them.")
    e = LmsEnrollment(student_id=user.id, course_id=c.id, status="pending", source="purchase", notes="Access requested by the student")
    db.add(e)
    db.flush()
    return {"id": str(e.id), "status": e.status}
