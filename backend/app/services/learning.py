"""Learning engine: progress rows, applying reviews, building study queues, mastery aggregation."""
import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.models.base import as_utc, utcnow
from app.models.knowledge import Topic
from app.models.learning import (
    QuestionReviewHistory,
    StudySession,
    StudySessionQuestion,
    UserQuestionProgress,
)
from app.models.question import Question, question_topics
from app.models.user import User
from app.services import fsrs

SECONDS_PER_REVIEW_DEFAULT = 45


def get_progress(db: Session, user: User, question_id: uuid.UUID) -> UserQuestionProgress:
    p = db.scalar(
        select(UserQuestionProgress).where(
            UserQuestionProgress.user_id == user.id, UserQuestionProgress.question_id == question_id
        )
    )
    if p is None:
        p = UserQuestionProgress(user_id=user.id, question_id=question_id, state="new", status="new")
        db.add(p)
        db.flush()
    return p


def card_of(p: UserQuestionProgress) -> fsrs.CardState:
    return fsrs.CardState(p.state, p.stability, p.difficulty, p.reps, p.lapses, as_utc(p.last_review_at))


def refresh_status(p: UserQuestionProgress, now: datetime | None = None) -> str:
    p.status = fsrs.derive_status(p.state, p.stability, as_utc(p.last_review_at), p.suspended, now or utcnow())
    return p.status


def apply_review(
    db: Session,
    user: User,
    question: Question,
    rating: int,
    *,
    session: StudySession | None = None,
    time_ms: int = 0,
    response_text: str = "",
    selected_option_ids: list[str] | None = None,
    ai_score: float | None = None,
    correct: bool | None = None,
    confidence: int | None = None,
    now: datetime | None = None,
) -> tuple[UserQuestionProgress, QuestionReviewHistory]:
    now = now or utcnow()
    p = get_progress(db, user, question.id)
    before = (p.state, p.stability, p.difficulty)
    res = fsrs.review(card_of(p), rating, now, user.desired_retention)

    p.state, p.stability, p.difficulty = res.state, res.stability, res.difficulty
    p.reps, p.lapses = res.reps, res.lapses
    p.last_review_at, p.due_at, p.scheduled_days = now, res.due_at, res.scheduled_days
    p.last_rating = rating
    is_correct = (rating >= 2) if correct is None else correct
    if is_correct:
        p.correct_count += 1
    if confidence is not None:
        p.confidence = confidence
    refresh_status(p, now)

    h = QuestionReviewHistory(
        user_id=user.id, question_id=question.id, session_id=session.id if session else None,
        reviewed_at=now, rating=rating, correct=is_correct,
        study_mode=session.mode if session else "manual", time_ms=max(0, min(time_ms, 30 * 60 * 1000)),
        state_before=before[0], state_after=res.state,
        stability_before=before[1], stability_after=res.stability,
        difficulty_before=before[2], difficulty_after=res.difficulty,
        retrievability_before=res.retrievability_before, elapsed_days=res.elapsed_days,
        scheduled_days=res.scheduled_days, response_text=response_text[:20000],
        selected_option_ids=selected_option_ids, ai_score=ai_score,
    )
    db.add(h)
    return p, h


def descendant_topic_ids(db: Session, user: User, topic_id: uuid.UUID) -> set[uuid.UUID]:
    rows = db.execute(select(Topic.id, Topic.parent_id).where(Topic.user_id == user.id)).all()
    children: dict[uuid.UUID | None, list[uuid.UUID]] = {}
    for tid, pid in rows:
        children.setdefault(pid, []).append(tid)
    out, stack = set(), [topic_id]
    while stack:
        cur = stack.pop()
        if cur in out:
            continue
        out.add(cur)
        stack.extend(children.get(cur, []))
    return out


def new_started_today(db: Session, user: User, now: datetime) -> int:
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return db.scalar(
        select(func.count()).select_from(QuestionReviewHistory).where(
            QuestionReviewHistory.user_id == user.id,
            QuestionReviewHistory.state_before == "new",
            QuestionReviewHistory.reviewed_at >= start,
        )
    ) or 0


@dataclass
class SessionConfig:
    mode: str = "quick_recall"
    count: int = 20
    subject_id: uuid.UUID | None = None
    topic_id: uuid.UUID | None = None
    difficulty: str | None = None
    question_type: str | None = None
    selection: str = "mixed"  # due | new | weak | mixed | all
    shuffle: bool = True


def base_question_query(user: User, cfg: SessionConfig, topic_ids: set[uuid.UUID] | None):
    q = select(Question).where(Question.user_id == user.id, Question.archived_at.is_(None))
    if cfg.subject_id:
        q = q.where(Question.subject_id == cfg.subject_id)
    if topic_ids:
        q = q.where(Question.id.in_(select(question_topics.c.question_id).where(question_topics.c.topic_id.in_(topic_ids))))
    if cfg.difficulty:
        q = q.where(Question.difficulty == cfg.difficulty)
    if cfg.question_type:
        q = q.where(Question.question_type == cfg.question_type)
    if cfg.mode == "multiple_choice":
        q = q.where(Question.question_type.in_(("multiple_choice", "true_false")))
    elif cfg.mode == "calculation":
        q = q.where(Question.question_type.in_(("calculation", "formula")))
    return q


def select_questions(db: Session, user: User, cfg: SessionConfig, now: datetime | None = None) -> list[uuid.UUID]:
    """Pick question ids for a session according to the chosen selection strategy."""
    now = now or utcnow()
    topic_ids = descendant_topic_ids(db, user, cfg.topic_id) if cfg.topic_id else None
    q = base_question_query(user, cfg, topic_ids)
    qids = list(db.scalars(q.with_only_columns(Question.id)))
    if not qids:
        return []
    progress = {
        p.question_id: p
        for p in db.scalars(
            select(UserQuestionProgress).where(
                UserQuestionProgress.user_id == user.id, UserQuestionProgress.question_id.in_(qids)
            )
        )
    }
    due, new, weak, other = [], [], [], []
    for qid in qids:
        p = progress.get(qid)
        if p is not None and p.suspended:
            continue
        if p is None or p.state == "new":
            new.append(qid)
            continue
        is_due = p.due_at is not None and as_utc(p.due_at) <= now
        if is_due:
            due.append((as_utc(p.due_at), qid))
        is_weak = p.lapses >= 2 or (p.reps >= 2 and p.correct_count / p.reps < 0.6) or p.last_rating == 1
        if is_weak:
            weak.append((p.lapses, qid))
        other.append(qid)

    due_ids = [qid for _, qid in sorted(due)]  # most overdue first
    weak_ids = [qid for _, qid in sorted(weak, key=lambda x: -x[0])]
    new_budget = max(0, user.daily_new_limit - new_started_today(db, user, now))
    # The daily new-question limit throttles mixed sessions; an explicit "new only" session is not capped.
    new_ids = new if cfg.selection == "new" else new[:new_budget]
    picked: list[uuid.UUID]
    if cfg.mode == "weakness" or cfg.selection == "weak":
        picked = weak_ids
    elif cfg.selection == "due":
        picked = due_ids
    elif cfg.selection == "new":
        picked = new_ids
    elif cfg.selection == "all":
        picked = list(qids)
    else:  # mixed: reviews that are due first, then new questions, then the weak ones not yet included
        picked = due_ids + new_ids + weak_ids
    picked = list(dict.fromkeys(picked))
    head = picked[: cfg.count]
    if cfg.shuffle and cfg.selection != "due":
        random.shuffle(head)
    return head


def create_session(db: Session, user: User, cfg: SessionConfig, qids: list[uuid.UUID]) -> StudySession:
    now = utcnow()
    s = StudySession(
        user_id=user.id, mode=cfg.mode, status="active", topic_id=cfg.topic_id, subject_id=cfg.subject_id,
        filters={"count": cfg.count, "difficulty": cfg.difficulty, "question_type": cfg.question_type,
                 "selection": cfg.selection},
        started_at=now, last_activity_at=now,
    )
    db.add(s)
    db.flush()
    for i, qid in enumerate(qids):
        db.add(StudySessionQuestion(session_id=s.id, question_id=qid, position=i))
    db.flush()
    return s


def due_filter(now: datetime):
    return and_(
        UserQuestionProgress.suspended.is_(False),
        UserQuestionProgress.state != "new",
        UserQuestionProgress.due_at <= now,
    )


def avg_seconds_per_review(db: Session, user: User) -> float:
    avg = db.scalar(
        select(func.avg(QuestionReviewHistory.time_ms)).where(
            QuestionReviewHistory.user_id == user.id, QuestionReviewHistory.time_ms > 0
        )
    )
    return float(avg) / 1000 if avg else SECONDS_PER_REVIEW_DEFAULT


def topic_mastery_map(db: Session, user: User, now: datetime | None = None) -> dict[uuid.UUID, dict]:
    """Per-topic stats (direct questions only): count, mastery, accuracy, reviews, lapses, due."""
    now = now or utcnow()
    rows = db.execute(
        select(question_topics.c.topic_id, Question.id, UserQuestionProgress)
        .join(Question, Question.id == question_topics.c.question_id)
        .outerjoin(
            UserQuestionProgress,
            and_(UserQuestionProgress.question_id == Question.id, UserQuestionProgress.user_id == user.id),
        )
        .where(Question.user_id == user.id, Question.archived_at.is_(None))
    ).all()
    out: dict[uuid.UUID, dict] = {}
    for tid, _qid, p in rows:
        d = out.setdefault(tid, dict(questions=0, mastery_sum=0.0, reps=0, correct=0, lapses=0, due=0,
                                     mastered=0, unreviewed=0, new=0, repeated=0, forgotten=0))
        d["questions"] += 1
        if p is None or p.state == "new":
            d["new"] += 1
            d["unreviewed"] += 1
            continue
        d["mastery_sum"] += fsrs.mastery_score(p.state, p.stability, as_utc(p.last_review_at), now)
        d["reps"] += p.reps
        d["correct"] += p.correct_count
        d["lapses"] += p.lapses
        if p.lapses >= 2:
            d["repeated"] += 1
        r_now = fsrs.current_retrievability(p.stability, as_utc(p.last_review_at), now)
        if p.lapses >= 1 and r_now is not None and r_now < 0.7:
            d["forgotten"] += 1
        if not p.suspended and p.due_at and as_utc(p.due_at) <= now:
            d["due"] += 1
        if fsrs.derive_status(p.state, p.stability, as_utc(p.last_review_at), p.suspended, now) == "mastered":
            d["mastered"] += 1
    return out


def rollup(stats: dict[uuid.UUID, dict], topic_ids: set[uuid.UUID]) -> dict:
    agg = dict(questions=0, mastery_sum=0.0, reps=0, correct=0, lapses=0, due=0, mastered=0, unreviewed=0, new=0,
               repeated=0, forgotten=0)
    for t in topic_ids:
        d = stats.get(t)
        if d:
            for k in agg:
                agg[k] += d[k]
    n = agg["questions"]
    agg["mastery"] = agg["mastery_sum"] / n if n else 0.0
    agg["accuracy"] = agg["correct"] / agg["reps"] if agg["reps"] else None
    return agg
