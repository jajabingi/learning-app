"""Student exam taking. The server owns time, attempt state and grading; responses never contain an answer key
until the teacher's result-visibility rules allow it. Access failures return 404."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DB
from app.core.permissions import require_student
from app.core.security import exam_limiter
from app.models.base import utcnow
from app.models.exam import FINAL_ATTEMPT_STATUSES, LmsExam, LmsExamAttempt
from app.models.lms import LmsCourse
from app.models.user import User
from app.services import access
from app.services import exams as ex

router = APIRouter(prefix="/student", tags=["student-exams"], dependencies=[Depends(require_student)])
Student = Depends(require_student)
VISIBLE = ("published", "closed")


class AnswerItem(BaseModel):
    exam_question_id: uuid.UUID
    answer: dict | None = None
    flagged: bool | None = None

    def as_dict(self) -> dict:
        return self.model_dump(exclude_unset=True)


class AnswersIn(BaseModel):
    answers: list[AnswerItem] = Field(min_length=1, max_length=200)


class SubmitIn(BaseModel):
    answers: list[AnswerItem] = Field(default_factory=list, max_length=200)


def _exam(db, user: User, exam_id: uuid.UUID) -> tuple[LmsExam, LmsCourse]:
    e = db.get(LmsExam, exam_id)
    if e is None or e.status not in VISIBLE:
        raise access.NOT_FOUND
    course, _ = access.student_course(db, user, e.course_id)
    return e, course


def _attempt(db, user: User, attempt_id: uuid.UUID) -> tuple[LmsExam, LmsExamAttempt]:
    a = db.get(LmsExamAttempt, attempt_id)
    if a is None or a.student_id != user.id:
        raise access.NOT_FOUND  # someone else's attempt looks exactly like a missing one
    e = db.get(LmsExam, a.exam_id)
    if e is None:
        raise access.NOT_FOUND
    access.student_course(db, user, e.course_id)
    return e, a


def _summary(db, user: User, e: LmsExam, course: LmsCourse, now) -> dict:
    atts = [a for a in ex.attempts_of(db, e.id, user.id) if a.status != "cancelled"]
    for a in atts:
        ex.finalize_if_expired(db, a, now)
    live = next((a for a in atts if a.status == "in_progress"), None)
    eff = ex.effective_status(e, now)
    left = None if e.max_attempts is None else max(0, e.max_attempts - len(atts))
    rows = []
    for a in atts:
        r = ex.student_result(e, a, now)
        rows.append({"id": str(a.id), "attempt_no": a.attempt_no, "status": a.status, "submitted_at": ex.iso(a.submitted_at),
                     "released": r["released"], "percent": r.get("percent"), "passed": r.get("passed")})
    return {
        "id": str(e.id), "course_id": str(course.id), "course_title": course.title, "title": e.title, "description": e.description,
        "instructions": e.instructions, "difficulty": e.difficulty, "category": e.category, "status": eff,
        "question_count": len(e.questions), "total_points": float(ex.total_points(e)), "time_limit_minutes": e.time_limit_minutes,
        "passing_score": e.passing_score, "max_attempts": e.max_attempts, "attempts_used": len(atts), "attempts_left": left,
        "opens_at": ex.iso(e.opens_at), "closes_at": ex.iso(e.closes_at), "allow_back": e.allow_back, "one_per_page": e.one_per_page,
        "in_progress_attempt_id": str(live.id) if live else None, "attempts": rows,
        "can_start": eff == "open" and (live is not None or left is None or left > 0),
    }


@router.get("/exams")
def my_exams(db: DB, user: User = Student):
    now = utcnow()
    out = []
    for course, _enr in access.student_enrolled_courses(db, user):
        for e in db.scalars(select(LmsExam).where(LmsExam.course_id == course.id, LmsExam.status.in_(VISIBLE)).order_by(LmsExam.created_at)):
            out.append(_summary(db, user, e, course, now))
    return out


@router.get("/exams/{exam_id}")
def exam_intro(exam_id: uuid.UUID, db: DB, user: User = Student):
    e, course = _exam(db, user, exam_id)
    return _summary(db, user, e, course, utcnow())


@router.post("/exams/{exam_id}/start", dependencies=[Depends(exam_limiter)])
def start_exam(exam_id: uuid.UUID, db: DB, user: User = Student):
    """Create an attempt (or resume the one in progress). The deadline is computed here and never changes."""
    e, _course = _exam(db, user, exam_id)
    now = utcnow()
    atts = [a for a in ex.attempts_of(db, e.id, user.id) if a.status != "cancelled"]
    for a in atts:
        ex.finalize_if_expired(db, a, now)
    live = next((a for a in atts if a.status == "in_progress"), None)
    if live is not None:
        if e.allow_resume:
            return ex.attempt_state(live, now)
        ex.finalize(db, live, now, auto=False)  # resuming is disabled: leaving the exam forfeits the attempt
    if ex.effective_status(e, now) != "open":
        raise ex.conflict("The exam is not open")
    used = len([a for a in atts])
    if e.max_attempts is not None and used >= e.max_attempts:
        raise ex.conflict("No attempts left")
    if not e.questions:
        raise ex.conflict("The exam has no questions")
    nxt = max((a.attempt_no for a in ex.attempts_of(db, e.id, user.id)), default=0) + 1
    att = ex.build_attempt(db, e, user.id, nxt, now)
    return ex.attempt_state(att, now)


@router.get("/exam-attempts/{attempt_id}")
def get_attempt(attempt_id: uuid.UUID, db: DB, user: User = Student):
    """Resume / reload: remaining time always comes from the stored deadline."""
    e, a = _attempt(db, user, attempt_id)
    now = utcnow()
    ex.finalize_if_expired(db, a, now)
    if a.status == "in_progress":
        return ex.attempt_state(a, now)
    return {"id": str(a.id), "exam_id": str(e.id), "status": a.status, "result": ex.student_result(e, a, now)}


@router.post("/exam-attempts/{attempt_id}/answers", dependencies=[Depends(exam_limiter)])
def save_answers(attempt_id: uuid.UUID, data: AnswersIn, db: DB, user: User = Student):
    """Autosave. Idempotent (same payload twice = same state). Refused once the deadline (+grace) has passed."""
    _e, a = _attempt(db, user, attempt_id)
    now = utcnow()
    ex.finalize_if_expired(db, a, now)
    if a.status != "in_progress":
        raise ex.conflict("This attempt is no longer open for answers")
    out = ex.save_answers(db, a, [i.as_dict() for i in data.answers], now)
    return {"saved_at": ex.iso(out["saved_at"]), "server_now": ex.iso(now),
            "remaining_seconds": max(0, int((ex.as_utc(a.deadline_at) - now).total_seconds())) if a.deadline_at else None}


@router.post("/exam-attempts/{attempt_id}/submit", dependencies=[Depends(exam_limiter)])
def submit_attempt(attempt_id: uuid.UUID, data: SubmitIn, db: DB, user: User = Student):
    """Final submission. Safe to repeat: a second call just returns the stored outcome."""
    e, a = _attempt(db, user, attempt_id)
    now = utcnow()
    ex.finalize_if_expired(db, a, now)  # past deadline + grace -> auto-submitted with the answers already saved
    if a.status == "in_progress":
        if data.answers:
            ex.save_answers(db, a, [i.as_dict() for i in data.answers], now)
        ex.finalize(db, a, now, auto=False)
    return {"id": str(a.id), "status": a.status, "submitted_at": ex.iso(a.submitted_at), "result": ex.student_result(e, a, now)}


@router.get("/exam-attempts/{attempt_id}/result")
def attempt_result(attempt_id: uuid.UUID, db: DB, user: User = Student):
    e, a = _attempt(db, user, attempt_id)
    ex.finalize_if_expired(db, a, utcnow())
    return ex.student_result(e, a, utcnow())
