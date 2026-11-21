"""Teacher side of the exam system: build, configure, publish, review attempts, grade manually, analytics."""
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DB
from app.core.permissions import P_COURSES_MANAGE, require_permission
from app.models.base import utcnow
from app.models.exam import FINAL_ATTEMPT_STATUSES, LmsExam, LmsExamAttempt, LmsExamQuestion
from app.models.lms import LmsCourse, LmsModule
from app.models.question import Question
from app.models.user import User
from app.schemas.lms import ReorderIn
from app.services import exams as ex
from app.services import lms

router = APIRouter(prefix="/teach", tags=["teacher-exams"], dependencies=[Depends(require_permission(P_COURSES_MANAGE))])
Teacher = Depends(require_permission(P_COURSES_MANAGE))

NULLABLE = {"time_limit_minutes", "opens_at", "closes_at", "max_attempts", "results_release_at", "module_id"}
# Settings that define the exam's rules: frozen once the exam leaves draft or has any attempt.
STRUCTURE_FIELDS = {"time_limit_minutes", "passing_score", "partial_credit", "max_attempts", "allow_resume", "allow_back",
                    "allow_change_answers", "one_per_page", "shuffle_questions", "shuffle_options"}


# ---------------------------------------------------------------- schemas
class ExamSettings(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=20000)
    instructions: str | None = Field(default=None, max_length=20000)
    category: str | None = Field(default=None, max_length=80)
    difficulty: Literal["easy", "medium", "hard"] | None = None
    module_id: uuid.UUID | None = None
    time_limit_minutes: int | None = Field(default=None, ge=1, le=1440)
    opens_at: datetime | None = None
    closes_at: datetime | None = None
    max_attempts: int | None = Field(default=None, ge=1, le=50)
    grade_policy: Literal["highest", "latest"] | None = None
    allow_resume: bool | None = None
    allow_back: bool | None = None
    allow_change_answers: bool | None = None
    one_per_page: bool | None = None
    shuffle_questions: bool | None = None
    shuffle_options: bool | None = None
    passing_score: int | None = Field(default=None, ge=0, le=100)
    partial_credit: bool | None = None
    show_score: bool | None = None
    show_pass_fail: bool | None = None
    show_answers: bool | None = None
    show_explanations: bool | None = None
    results_release: Literal["immediate", "manual", "scheduled"] | None = None
    results_release_at: datetime | None = None
    release_partial: bool | None = None


class ExamCreate(ExamSettings):
    course_id: uuid.UUID
    title: str = Field(min_length=1, max_length=200)


class AddQuestions(BaseModel):
    question_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    points: float = Field(default=1, gt=0, le=1000)


class OptionIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    is_correct: bool = False


class CustomQuestion(BaseModel):
    type: Literal["multiple_choice", "true_false", "calculation", "short_answer", "open_ended", "case_study"] = "multiple_choice"
    content: str = Field(min_length=1, max_length=20000)
    options: list[OptionIn] = Field(default_factory=list, max_length=12)
    answer: str = Field(default="", max_length=20000)
    explanation: str = Field(default="", max_length=20000)
    tolerance: float = Field(default=0, ge=0)
    points: float = Field(default=1, gt=0, le=1000)
    grading: Literal["auto", "manual"] | None = None


class QuestionPatch(BaseModel):
    points: float | None = Field(default=None, gt=0, le=1000)
    grading: Literal["auto", "manual"] | None = None
    tolerance: float | None = Field(default=None, ge=0)
    refresh: bool = False  # re-copy the question from the bank (only possible for bank questions, draft exams)


class StatusIn(BaseModel):
    action: Literal["publish", "unpublish", "close", "archive"]


class GradeItem(BaseModel):
    exam_question_id: uuid.UUID
    points: float = Field(ge=0)
    feedback: str = Field(default="", max_length=5000)


class GradeIn(BaseModel):
    grades: list[GradeItem] = Field(min_length=1, max_length=500)


# ---------------------------------------------------------------- helpers
def _own_exam(db, user: User, exam_id: uuid.UUID) -> LmsExam:
    e = db.get(LmsExam, exam_id)
    if e is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Exam not found")
    lms.own_course(db, user, e.course_id)
    return e


def _own_attempt(db, user: User, attempt_id: uuid.UUID) -> tuple[LmsExam, LmsExamAttempt]:
    a = db.get(LmsExamAttempt, attempt_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attempt not found")
    return _own_exam(db, user, a.exam_id), a


def _own_exam_question(db, user: User, qid: uuid.UUID) -> tuple[LmsExam, LmsExamQuestion]:
    q = db.get(LmsExamQuestion, qid)
    if q is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Exam question not found")
    return _own_exam(db, user, q.exam_id), q


def _locked(db, e: LmsExam) -> bool:
    return e.status != "draft" or ex.has_attempts(db, e.id)


def _require_unlocked(db, e: LmsExam) -> None:
    if _locked(db, e):
        raise ex.conflict("The exam can no longer be restructured: unpublish it and make sure it has no attempts, or duplicate it")


def _exam_question_out(q: LmsExamQuestion) -> dict:
    s = q.snapshot
    return {"id": str(q.id), "question_id": str(q.question_id) if q.question_id else None, "position": q.position,
            "points": float(q.points), "grading": q.grading, "problem": ex.question_problem(q), "type": s["type"],
            "title": s["title"], "content": s["content"], "options": s["options"], "answer": s["answer"],
            "explanation": s["explanation"], "tolerance": s.get("tolerance", 0)}


def _exam_out(db, e: LmsExam, detail: bool = False) -> dict:
    now = utcnow()
    st = ex.exam_stats(db, e)
    d = {
        "id": str(e.id), "course_id": str(e.course_id), "course_title": db.get(LmsCourse, e.course_id).title,
        "module_id": str(e.module_id) if e.module_id else None, "title": e.title, "description": e.description,
        "instructions": e.instructions, "category": e.category, "difficulty": e.difficulty, "status": e.status,
        "effective_status": ex.effective_status(e, now), "question_count": len(e.questions), "total_points": float(ex.total_points(e)),
        "time_limit_minutes": e.time_limit_minutes, "opens_at": ex.iso(e.opens_at), "closes_at": ex.iso(e.closes_at),
        "max_attempts": e.max_attempts, "grade_policy": e.grade_policy, "allow_resume": e.allow_resume, "allow_back": e.allow_back,
        "allow_change_answers": e.allow_change_answers, "one_per_page": e.one_per_page, "shuffle_questions": e.shuffle_questions,
        "shuffle_options": e.shuffle_options, "passing_score": e.passing_score, "partial_credit": e.partial_credit,
        "show_score": e.show_score, "show_pass_fail": e.show_pass_fail, "show_answers": e.show_answers,
        "show_explanations": e.show_explanations, "results_release": e.results_release, "results_release_at": ex.iso(e.results_release_at),
        "results_released_at": ex.iso(e.results_released_at), "release_partial": e.release_partial,
        "students": st["enrolled"], "submissions": st["submitted"], "average": st["average"], "pass_rate": st["pass_rate"],
        "locked": _locked(db, e), "created_at": ex.iso(e.created_at), "updated_at": ex.iso(e.updated_at),
    }
    if detail:
        d["questions"] = [_exam_question_out(q) for q in e.questions]
        d["problems"] = ex.publish_problems(e)
    return d


def _apply(db, e: LmsExam, data: dict) -> None:
    locked = _locked(db, e)
    if "module_id" in data and data["module_id"] is not None:
        m = db.get(LmsModule, data["module_id"])
        if m is None or m.course_id != e.course_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Module not found in this course")
    for k, v in data.items():
        if k in STRUCTURE_FIELDS and locked and getattr(e, k) != v:
            raise ex.conflict(f"'{k}' can only be changed while the exam is an unpublished draft without attempts")
        if v is None and k not in NULLABLE:
            continue
        setattr(e, k, v)
    if e.opens_at and e.closes_at and ex.as_utc(e.closes_at) <= ex.as_utc(e.opens_at):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The closing time must be after the opening time")


def _owned_exams(db, user: User, course_id: uuid.UUID | None = None) -> list[LmsExam]:
    q = select(LmsExam).join(LmsCourse, LmsCourse.id == LmsExam.course_id)
    if user.role != "admin":
        q = q.where(LmsCourse.owner_id == user.id)
    if course_id:
        q = q.where(LmsExam.course_id == course_id)
    return list(db.scalars(q.order_by(LmsExam.created_at.desc())))


# ---------------------------------------------------------------- exam CRUD
@router.get("/exams")
def list_exams(db: DB, course_id: uuid.UUID | None = None, user: User = Teacher):
    return [_exam_out(db, e) for e in _owned_exams(db, user, course_id)]


@router.post("/exams", status_code=201)
def create_exam(data: ExamCreate, db: DB, user: User = Teacher):
    lms.own_course(db, user, data.course_id)
    vals = data.model_dump(exclude_unset=True, exclude={"course_id"})
    e = LmsExam(course_id=data.course_id, title=data.title)
    db.add(e)
    db.flush()
    _apply(db, e, vals)
    db.flush()
    return _exam_out(db, e, detail=True)


@router.get("/exams/{exam_id}")
def get_exam(exam_id: uuid.UUID, db: DB, user: User = Teacher):
    return _exam_out(db, _own_exam(db, user, exam_id), detail=True)


@router.patch("/exams/{exam_id}")
def patch_exam(exam_id: uuid.UUID, data: ExamSettings, db: DB, user: User = Teacher):
    e = _own_exam(db, user, exam_id)
    _apply(db, e, data.model_dump(exclude_unset=True))
    db.flush()
    return _exam_out(db, e, detail=True)


@router.delete("/exams/{exam_id}", status_code=204)
def delete_exam(exam_id: uuid.UUID, db: DB, user: User = Teacher):
    e = _own_exam(db, user, exam_id)
    if e.status != "draft" and ex.has_attempts(db, e.id):
        raise ex.conflict("This exam has student attempts: archive it instead")
    db.delete(e)


@router.post("/exams/{exam_id}/duplicate", status_code=201)
def duplicate_exam(exam_id: uuid.UUID, db: DB, user: User = Teacher):
    src = _own_exam(db, user, exam_id)
    cols = {c.name: getattr(src, c.name) for c in LmsExam.__table__.columns
            if c.name not in ("id", "created_at", "updated_at", "status", "title", "results_released_at")}
    e = LmsExam(**cols, title=f"{src.title} (copy)"[:200], status="draft")
    db.add(e)
    db.flush()
    for q in src.questions:
        db.add(LmsExamQuestion(exam_id=e.id, question_id=q.question_id, position=q.position, points=q.points,
                               grading=q.grading, snapshot=dict(q.snapshot)))
    db.flush()
    db.expire(e)
    return _exam_out(db, e, detail=True)


@router.post("/exams/{exam_id}/status")
def change_status(exam_id: uuid.UUID, data: StatusIn, db: DB, user: User = Teacher):
    e = _own_exam(db, user, exam_id)
    if data.action == "publish":
        if e.status not in ("draft", "closed"):
            raise ex.conflict("Only a draft or closed exam can be published")
        problems = ex.publish_problems(e)
        if problems:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "; ".join(problems))
        e.status = "published"
    elif data.action == "unpublish":
        if e.status != "published":
            raise ex.conflict("The exam is not published")
        now = utcnow()
        for a in db.scalars(select(LmsExamAttempt).where(LmsExamAttempt.exam_id == e.id, LmsExamAttempt.status == "in_progress")):
            ex.finalize_if_expired(db, a, now)
            if a.status == "in_progress":
                raise ex.conflict("Students are taking this exam right now: close it instead")
        e.status = "draft"
    elif data.action == "close":
        if e.status != "published":
            raise ex.conflict("Only a published exam can be closed")
        e.status = "closed"
    else:
        e.status = "archived"
    db.flush()
    return _exam_out(db, e, detail=True)


@router.get("/exams/{exam_id}/preview")
def preview_exam(exam_id: uuid.UUID, db: DB, user: User = Teacher):
    """The exam exactly as a student sees it (no attempt is created and nothing is saved)."""
    e = _own_exam(db, user, exam_id)
    return {"title": e.title, "instructions": e.instructions, "description": e.description, "one_per_page": e.one_per_page,
            "allow_back": e.allow_back, "time_limit_minutes": e.time_limit_minutes, "passing_score": e.passing_score,
            "max_attempts": e.max_attempts, "total_points": float(ex.total_points(e)), "opens_at": ex.iso(e.opens_at),
            "closes_at": ex.iso(e.closes_at), "questions": [ex.student_question({"id": str(q.id), "points": float(q.points), "snapshot": q.snapshot}, None) for q in e.questions]}


# ---------------------------------------------------------------- questions
@router.post("/exams/{exam_id}/questions", status_code=201)
def add_questions(exam_id: uuid.UUID, data: AddQuestions, db: DB, user: User = Teacher):
    e = _own_exam(db, user, exam_id)
    _require_unlocked(db, e)
    owner = db.get(LmsCourse, e.course_id).owner_id
    ids = list(dict.fromkeys(data.question_ids))
    found = {q.id: q for q in db.scalars(select(Question).where(Question.id.in_(ids), Question.user_id == owner))}
    if len(found) != len(ids):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Some questions were not found in your question bank")
    have = {q.question_id for q in e.questions}
    pos = len(e.questions)
    for qid in ids:
        if qid in have:
            continue
        snap = ex.snapshot_question(found[qid])
        db.add(LmsExamQuestion(exam_id=e.id, question_id=qid, position=pos, points=ex.D(data.points), grading=ex.default_grading(snap), snapshot=snap))
        pos += 1
    db.flush()
    db.expire(e)
    return _exam_out(db, e, detail=True)


@router.post("/exams/{exam_id}/questions/custom", status_code=201)
def add_custom_question(exam_id: uuid.UUID, data: CustomQuestion, db: DB, user: User = Teacher):
    e = _own_exam(db, user, exam_id)
    _require_unlocked(db, e)
    if data.type == "true_false" and not data.options:
        data.options = [OptionIn(text="נכון", is_correct=False), OptionIn(text="לא נכון", is_correct=False)]
    snap = ex.custom_snapshot(data.type, data.content, [o.model_dump() for o in data.options], data.answer, data.explanation, data.tolerance)
    q = LmsExamQuestion(exam_id=e.id, position=len(e.questions), points=ex.D(data.points), grading=data.grading or ex.default_grading(snap), snapshot=snap)
    db.add(q)
    db.flush()
    db.expire(e)
    return _exam_out(db, e, detail=True)


@router.patch("/exam-questions/{qid}")
def patch_exam_question(qid: uuid.UUID, data: QuestionPatch, db: DB, user: User = Teacher):
    e, q = _own_exam_question(db, user, qid)
    _require_unlocked(db, e)
    if data.points is not None:
        q.points = ex.D(data.points)
    if data.grading is not None:
        q.grading = data.grading
    if data.tolerance is not None:
        q.snapshot = {**q.snapshot, "tolerance": data.tolerance}
    if data.refresh:
        src = db.get(Question, q.question_id) if q.question_id else None
        if src is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "This question has no source in the bank")
        q.snapshot = ex.snapshot_question(src)
        q.grading = ex.default_grading(q.snapshot)
    db.flush()
    db.expire(e)
    return _exam_out(db, e, detail=True)


@router.delete("/exam-questions/{qid}", status_code=204)
def delete_exam_question(qid: uuid.UUID, db: DB, user: User = Teacher):
    e, q = _own_exam_question(db, user, qid)
    _require_unlocked(db, e)
    db.delete(q)
    db.flush()
    db.expire(e)
    lms.normalise(list(e.questions))


@router.post("/exams/{exam_id}/questions/reorder", status_code=204)
def reorder_questions(exam_id: uuid.UUID, data: ReorderIn, db: DB, user: User = Teacher):
    e = _own_exam(db, user, exam_id)
    _require_unlocked(db, e)
    lms.apply_order(db, list(e.questions), data.ids)


# ---------------------------------------------------------------- attempts, grading, results
def _attempt_row(db, a: LmsExamAttempt) -> dict:
    s = db.get(User, a.student_id)
    return {"id": str(a.id), "student_id": str(a.student_id), "student_name": s.display_name, "student_email": s.email,
            "attempt_no": a.attempt_no, "status": a.status, "auto_submitted": a.auto_submitted, "started_at": ex.iso(a.started_at), "submitted_at": ex.iso(a.submitted_at),
            "score": float(a.score) if a.score is not None else None, "max_score": float(a.max_score) if a.max_score is not None else None,
            "percent": float(a.percent) if a.percent is not None else None, "passed": a.passed,
            "pending_manual": sum(1 for x in a.answers if x.grading_status == "pending"),
            "released": a.released_at is not None}


@router.get("/exams/{exam_id}/attempts")
def exam_attempts(exam_id: uuid.UUID, db: DB, status_filter: str | None = None, user: User = Teacher):
    e = _own_exam(db, user, exam_id)
    now = utcnow()
    rows = list(db.scalars(select(LmsExamAttempt).where(LmsExamAttempt.exam_id == e.id).order_by(LmsExamAttempt.started_at.desc())))
    for a in rows:
        ex.finalize_if_expired(db, a, now)
    return [_attempt_row(db, a) for a in rows if not status_filter or a.status == status_filter]


@router.get("/exams/{exam_id}/stats")
def exam_statistics(exam_id: uuid.UUID, db: DB, user: User = Teacher):
    e = _own_exam(db, user, exam_id)
    now = utcnow()
    for a in db.scalars(select(LmsExamAttempt).where(LmsExamAttempt.exam_id == e.id, LmsExamAttempt.status == "in_progress")):
        ex.finalize_if_expired(db, a, now)
    st = ex.exam_stats(db, e)
    order = {q["id"]: i for i, q in enumerate(st["questions"])}
    st["questions"].sort(key=lambda q: order[q["id"]])
    return st


@router.get("/exam-attempts/{attempt_id}")
def review_attempt(attempt_id: uuid.UUID, db: DB, user: User = Teacher):
    e, a = _own_attempt(db, user, attempt_id)
    ex.finalize_if_expired(db, a)
    am = ex.answer_map(a)
    qs = []
    for i, f in enumerate(ex.frozen_questions(a), 1):
        s, ans = f["snapshot"], am.get(f["id"])
        qs.append({"id": f["id"], "number": i, "type": s["type"], "content": s["content"], "title": s["title"], "points": f["points"],
                   "grading": f["grading"], "options": s["options"], "expected_answer": s["answer"], "explanation": s["explanation"],
                   "answer": ans.answer if ans else None, "flagged": bool(ans and ans.flagged),
                   "grading_status": ans.grading_status if ans else "pending", "points_awarded": float(ans.points_awarded) if ans and ans.points_awarded is not None else None,
                   "is_correct": ans.is_correct if ans else None, "feedback": ans.feedback if ans else ""})
    return {**_attempt_row(db, a), "exam_id": str(e.id), "exam_title": e.title, "questions": qs}


@router.post("/exam-attempts/{attempt_id}/grade")
def grade_attempt(attempt_id: uuid.UUID, data: GradeIn, db: DB, user: User = Teacher):
    _e, a = _own_attempt(db, user, attempt_id)
    ex.grade_manually(db, a, [g.model_dump() for g in data.grades], user.id, utcnow())
    return _attempt_row(db, a)


@router.post("/exam-attempts/{attempt_id}/release")
def release_attempt(attempt_id: uuid.UUID, db: DB, user: User = Teacher):
    _e, a = _own_attempt(db, user, attempt_id)
    if a.status not in FINAL_ATTEMPT_STATUSES:
        raise ex.conflict("The attempt has not been submitted")
    a.released_at = utcnow()
    db.flush()
    return _attempt_row(db, a)


@router.post("/exam-attempts/{attempt_id}/cancel")
def cancel_attempt(attempt_id: uuid.UUID, db: DB, user: User = Teacher):
    """Void an attempt (e.g. a technical failure): it no longer counts toward the student's attempt limit."""
    _e, a = _own_attempt(db, user, attempt_id)
    a.status = "cancelled"
    db.flush()
    return _attempt_row(db, a)


@router.post("/exams/{exam_id}/release-results")
def release_results(exam_id: uuid.UUID, db: DB, user: User = Teacher):
    e = _own_exam(db, user, exam_id)
    e.results_released_at = utcnow()
    db.flush()
    return _exam_out(db, e)


@router.get("/students/{student_id}/exams")
def student_exam_grades(student_id: uuid.UUID, db: DB, user: User = Teacher):
    """Exam results of one student, restricted to exams in courses the caller owns."""
    owned = {e.id: e for e in _owned_exams(db, user)}
    rows = db.scalars(select(LmsExamAttempt).where(LmsExamAttempt.student_id == student_id, LmsExamAttempt.exam_id.in_(list(owned) or [uuid.uuid4()]),
                                                   LmsExamAttempt.status != "cancelled").order_by(LmsExamAttempt.started_at.desc()))
    return [{**_attempt_row(db, a), "exam_id": str(a.exam_id), "exam_title": owned[a.exam_id].title} for a in rows]
