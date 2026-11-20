import uuid
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser, check_owned_optional, owned
from app.models.base import as_utc, utcnow
from app.models.knowledge import Subject, Topic
from app.models.learning import QuestionReviewHistory, StudySession, StudySessionQuestion, UserQuestionProgress
from app.models.question import Question
from app.services import fsrs, learning
from app.services.questions import progress_out, serialize

router = APIRouter(tags=["study"])

Mode = Literal["quick_recall", "written_recall", "multiple_choice", "calculation", "topic", "subject", "mixed", "weakness"]


class SessionCreate(BaseModel):
    mode: Mode = "quick_recall"
    count: int = Field(default=20, ge=1, le=200)
    subject_id: uuid.UUID | None = None
    topic_id: uuid.UUID | None = None
    difficulty: Literal["easy", "medium", "hard"] | None = None
    question_type: str | None = None
    selection: Literal["due", "new", "weak", "mixed", "all"] = "mixed"
    shuffle: bool = True


class AnswerIn(BaseModel):
    question_id: uuid.UUID
    rating: int = Field(ge=1, le=4)
    time_ms: int = Field(default=0, ge=0, le=3_600_000)
    response_text: str = Field(default="", max_length=20000)
    selected_option_ids: list[uuid.UUID] | None = None
    ai_score: float | None = Field(default=None, ge=0, le=100)
    confidence: int | None = Field(default=None, ge=1, le=5)


def _cfg(d: SessionCreate) -> learning.SessionConfig:
    return learning.SessionConfig(**d.model_dump())


@router.post("/study/preview")
def preview(data: SessionCreate, db: DB, user: CurrentUser):
    check_owned_optional(db, Subject, data.subject_id, user)
    check_owned_optional(db, Topic, data.topic_id, user)
    ids = learning.select_questions(db, user, _cfg(data))
    return {"available": len(ids), "estimated_seconds": int(len(ids) * learning.avg_seconds_per_review(db, user))}


@router.post("/study/sessions", status_code=201)
def create_session(data: SessionCreate, db: DB, user: CurrentUser):
    check_owned_optional(db, Subject, data.subject_id, user)
    check_owned_optional(db, Topic, data.topic_id, user)
    cfg = _cfg(data)
    qids = learning.select_questions(db, user, cfg)
    if not qids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No questions match these settings")
    s = learning.create_session(db, user, cfg, qids)
    return {"id": str(s.id), "total": len(qids)}


def _session_summary(db, s: StudySession):
    rows = db.execute(select(StudySessionQuestion.answered_at, StudySessionQuestion.rating)
                      .where(StudySessionQuestion.session_id == s.id)).all()
    total = len(rows)
    answered = sum(1 for a, _ in rows if a is not None)
    return {"id": str(s.id), "mode": s.mode, "status": s.status, "filters": s.filters,
            "topic_id": str(s.topic_id) if s.topic_id else None,
            "subject_id": str(s.subject_id) if s.subject_id else None,
            "started_at": as_utc(s.started_at).isoformat(),
            "ended_at": as_utc(s.ended_at).isoformat() if s.ended_at else None,
            "last_activity_at": as_utc(s.last_activity_at).isoformat(), "total": total, "answered": answered}


@router.get("/study/sessions")
def list_sessions(db: DB, user: CurrentUser, status_: Literal["open", "completed", "all"] = "open", limit: int = 20):
    stmt = select(StudySession).where(StudySession.user_id == user.id)
    if status_ == "open":
        stmt = stmt.where(StudySession.status.in_(("active", "paused")))
    elif status_ == "completed":
        stmt = stmt.where(StudySession.status == "completed")
    rows = db.scalars(stmt.order_by(StudySession.last_activity_at.desc()).limit(min(limit, 100)))
    return [_session_summary(db, s) for s in rows]


@router.get("/study/sessions/{session_id}")
def get_session(session_id: uuid.UUID, db: DB, user: CurrentUser):
    s = owned(db, StudySession, session_id, user)
    sqs = list(db.scalars(select(StudySessionQuestion).where(StudySessionQuestion.session_id == s.id)
                          .order_by(StudySessionQuestion.position)))
    qs = {q.id: q for q in db.scalars(select(Question).where(Question.id.in_([x.question_id for x in sqs])))}
    ordered = [qs[x.question_id] for x in sqs if x.question_id in qs]
    out_by_id = {o.id: o for o in serialize(db, user, ordered, include_attachments=True)}
    now = utcnow()
    items = []
    for x in sqs:
        if x.question_id not in out_by_id:
            continue
        o = out_by_id[x.question_id]
        p = db.scalar(select(UserQuestionProgress).where(UserQuestionProgress.user_id == user.id,
                                                          UserQuestionProgress.question_id == x.question_id))
        card = learning.card_of(p) if p else fsrs.CardState("new", 0, 0, 0, 0, None)
        items.append({"position": x.position, "answered": x.answered_at is not None, "rating": x.rating,
                      "question": o, "intervals": fsrs.preview_intervals(card, now, user.desired_retention)})
    return {**_session_summary(db, s), "items": items}


@router.post("/study/sessions/{session_id}/answer")
def answer(session_id: uuid.UUID, data: AnswerIn, db: DB, user: CurrentUser):
    s = owned(db, StudySession, session_id, user)
    if s.status in ("completed", "abandoned"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Session is finished")
    sq = db.scalar(select(StudySessionQuestion).where(
        StudySessionQuestion.session_id == s.id, StudySessionQuestion.question_id == data.question_id,
        StudySessionQuestion.answered_at.is_(None)).order_by(StudySessionQuestion.position))
    if sq is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Question is not pending in this session")
    q = owned(db, Question, data.question_id, user)

    rating, correct = data.rating, None
    if data.selected_option_ids is not None and q.options:
        valid = {o.id for o in q.options}
        if not set(data.selected_option_ids) <= valid:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown option selected")
        correct = set(data.selected_option_ids) == {o.id for o in q.options if o.is_correct}
        if not correct:
            rating = 1  # a wrong multiple-choice answer is always a lapse, whatever the button said
    now = utcnow()
    p, h = learning.apply_review(db, user, q, rating, session=s, time_ms=data.time_ms,
                                 response_text=data.response_text,
                                 selected_option_ids=[str(i) for i in data.selected_option_ids] if data.selected_option_ids is not None else None,
                                 ai_score=data.ai_score, correct=correct, confidence=data.confidence, now=now)
    sq.answered_at, sq.rating = now, rating
    s.last_activity_at = now
    s.status = "active"

    db.flush()  # autoflush is off: make the answered row visible to the queries below
    if rating == 1:  # show it again at the end of this session (active recall of failed items)
        pending_same = db.scalar(select(func.count()).select_from(StudySessionQuestion).where(
            StudySessionQuestion.session_id == s.id, StudySessionQuestion.question_id == q.id,
            StudySessionQuestion.answered_at.is_(None)))
        if not pending_same:
            last = db.scalar(select(func.max(StudySessionQuestion.position)).where(StudySessionQuestion.session_id == s.id))
            db.add(StudySessionQuestion(session_id=s.id, question_id=q.id, position=(last or 0) + 1))
    db.flush()
    remaining = db.scalar(select(func.count()).select_from(StudySessionQuestion).where(
        StudySessionQuestion.session_id == s.id, StudySessionQuestion.answered_at.is_(None)))
    if remaining == 0:
        s.status, s.ended_at = "completed", now
    return {"progress": progress_out(p), "rating": rating, "correct": h.correct, "remaining": remaining,
            "completed": remaining == 0, "scheduled_days": h.scheduled_days}


@router.post("/study/sessions/{session_id}/{action}")
def session_action(session_id: uuid.UUID, action: Literal["pause", "resume", "complete", "abandon"], db: DB,
                   user: CurrentUser):
    s = owned(db, StudySession, session_id, user)
    now = utcnow()
    if action == "pause" and s.status == "active":
        s.status = "paused"
    elif action == "resume" and s.status == "paused":
        s.status = "active"
    elif action in ("complete", "abandon") and s.status in ("active", "paused"):
        s.status = "completed" if action == "complete" else "abandoned"
        s.ended_at = now
    s.last_activity_at = now
    return _session_summary(db, s)


@router.get("/study/sessions/{session_id}/summary")
def summary(session_id: uuid.UUID, db: DB, user: CurrentUser):
    s = owned(db, StudySession, session_id, user)
    hist = list(db.scalars(select(QuestionReviewHistory).where(QuestionReviewHistory.session_id == s.id)
                           .order_by(QuestionReviewHistory.reviewed_at)))
    titles = {q.id: q.title or q.content[:80] for q in db.scalars(
        select(Question).where(Question.id.in_({h.question_id for h in hist})))} if hist else {}
    n = len(hist)
    dist = {r: sum(1 for h in hist if h.rating == r) for r in (1, 2, 3, 4)}
    return {**_session_summary(db, s), "reviews": n, "correct": sum(1 for h in hist if h.correct),
            "accuracy": (sum(1 for h in hist if h.correct) / n) if n else None, "ratings": dist,
            "time_seconds": round(sum(h.time_ms for h in hist) / 1000),
            "missed": [{"question_id": str(h.question_id), "title": titles.get(h.question_id, "")}
                       for h in hist if not h.correct]}


# ---------- review queue ----------
@router.get("/review/queue")
def review_queue(db: DB, user: CurrentUser, upcoming_days: int = 14, limit: int = 100):
    now = utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    base = (select(UserQuestionProgress, Question).join(Question, Question.id == UserQuestionProgress.question_id)
            .where(UserQuestionProgress.user_id == user.id, UserQuestionProgress.suspended.is_(False),
                   UserQuestionProgress.state != "new", Question.archived_at.is_(None)))
    due_rows = db.execute(base.where(UserQuestionProgress.due_at <= now).order_by(UserQuestionProgress.due_at)).all()
    upcoming_rows = db.execute(base.where(UserQuestionProgress.due_at > now,
                                          UserQuestionProgress.due_at < now + timedelta(days=upcoming_days))).all()

    def lite(p, q):
        due = as_utc(p.due_at)
        return {"question_id": str(q.id), "title": q.title or q.content[:100], "question_type": q.question_type,
                "subject_id": str(q.subject_id) if q.subject_id else None, "due_at": due.isoformat(),
                "overdue_days": (today_start.date() - due.date()).days if due < today_start else 0,
                "status": progress_out(p).status, "stability": round(p.stability, 1), "lapses": p.lapses}

    overdue = [r for r in due_rows if as_utc(r[0].due_at) < today_start]
    by_day: dict[str, int] = {}
    for p, _ in upcoming_rows:
        by_day[as_utc(p.due_at).date().isoformat()] = by_day.get(as_utc(p.due_at).date().isoformat(), 0) + 1
    start = today_start.date()
    upcoming = [{"date": (start + timedelta(days=i)).isoformat(), "count": by_day.get((start + timedelta(days=i)).isoformat(), 0)}
                for i in range(upcoming_days)]
    reviewed_today = db.scalar(select(func.count()).select_from(QuestionReviewHistory).where(
        QuestionReviewHistory.user_id == user.id, QuestionReviewHistory.reviewed_at >= today_start)) or 0
    new_available = db.scalar(
        select(func.count()).select_from(Question).outerjoin(
            UserQuestionProgress, (UserQuestionProgress.question_id == Question.id) & (UserQuestionProgress.user_id == user.id))
        .where(Question.user_id == user.id, Question.archived_at.is_(None),
               (UserQuestionProgress.id.is_(None)) | (UserQuestionProgress.state == "new")
               & (UserQuestionProgress.suspended.is_(False)))) or 0
    new_budget = max(0, user.daily_new_limit - learning.new_started_today(db, user, now))
    per = learning.avg_seconds_per_review(db, user)
    open_sessions = db.scalars(select(StudySession).where(StudySession.user_id == user.id,
                                                          StudySession.status.in_(("active", "paused")))
                               .order_by(StudySession.last_activity_at.desc()).limit(5))
    return {
        "due_now": len(due_rows), "overdue": len(overdue), "due_today": len(due_rows) - len(overdue),
        "reviewed_today": reviewed_today, "daily_goal": user.daily_review_goal,
        "completion_today": reviewed_today / max(reviewed_today + len(due_rows), 1),
        "new_available": min(new_available, new_budget), "estimated_seconds": int((len(due_rows)) * per),
        "seconds_per_review": round(per, 1),
        "items": [lite(p, q) for p, q in due_rows[:limit]], "upcoming": upcoming,
        "open_sessions": [_session_summary(db, s) for s in open_sessions],
    }
