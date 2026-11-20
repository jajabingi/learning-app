"""Analytics. Metric definitions (kept deliberately separate so they are never conflated):

- Accuracy   : share of review answers rated Hard/Good/Easy (i.e. not "Again") — about answers given.
- Retention  : accuracy restricted to reviews of questions that were already learned (state review) — the
               scheduler's real success rate, comparable to the desired-retention target.
- Mastery    : per-question score = current recall probability x memory maturity (stability / 21d, max 1);
               averaged over ALL questions, so unstudied material lowers it. It decays when you stop reviewing.
- Completion : of the reviews that came due in the period, the share that were actually done.
- Activity   : raw volume — reviews per day, study time, streak. Says nothing about quality.
"""
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.base import as_utc, utcnow
from app.models.knowledge import Subject, Topic
from app.models.learning import QuestionReviewHistory, UserQuestionProgress
from app.models.question import Question
from app.models.user import User
from app.services import fsrs, learning

WEAK_MIN_REVIEWS = 5


def day_of(dt: datetime) -> date:
    return as_utc(dt).date()


def review_rows(db: Session, user: User, since: datetime | None = None):
    stmt = select(QuestionReviewHistory).where(QuestionReviewHistory.user_id == user.id)
    if since:
        stmt = stmt.where(QuestionReviewHistory.reviewed_at >= since)
    return list(db.scalars(stmt.order_by(QuestionReviewHistory.reviewed_at)))


def streaks(days_with_activity: set[date], today: date) -> tuple[int, int]:
    """(current, longest). The current streak survives until the end of the day after the last active day."""
    if not days_with_activity:
        return 0, 0
    cur = 0
    d = today if today in days_with_activity else today - timedelta(days=1)
    while d in days_with_activity:
        cur += 1
        d -= timedelta(days=1)
    longest = run = 0
    prev = None
    for d in sorted(days_with_activity):
        run = run + 1 if prev and (d - prev).days == 1 else 1
        longest = max(longest, run)
        prev = d
    return cur, longest


def daily_series(rows, start: date, end: date) -> list[dict]:
    per: dict[date, list] = {}
    for h in rows:
        per.setdefault(day_of(h.reviewed_at), []).append(h)
    out, d = [], start
    while d <= end:
        hs = per.get(d, [])
        n = len(hs)
        out.append({"date": d.isoformat(), "reviews": n,
                    "accuracy": round(sum(h.correct for h in hs) / n, 3) if n else None,
                    "minutes": round(sum(h.time_ms for h in hs) / 60000, 1),
                    "new_learned": sum(1 for h in hs if h.state_before == "new")})
        d += timedelta(days=1)
    return out


def retention_trend(rows, weeks: int, today: date) -> list[dict]:
    out = []
    for w in range(weeks - 1, -1, -1):
        end = today - timedelta(days=7 * w)
        start = end - timedelta(days=6)
        hs = [h for h in rows if start <= day_of(h.reviewed_at) <= end and h.state_before == "review"]
        out.append({"week_start": start.isoformat(), "reviews": len(hs),
                    "retention": round(sum(h.correct for h in hs) / len(hs), 3) if hs else None})
    return out


def question_states(db: Session, user: User, now: datetime):
    """All non-archived questions with their progress (None = never studied)."""
    return db.execute(
        select(Question.id, Question.subject_id, Question.title, Question.content, UserQuestionProgress)
        .outerjoin(UserQuestionProgress, (UserQuestionProgress.question_id == Question.id)
                   & (UserQuestionProgress.user_id == user.id))
        .where(Question.user_id == user.id, Question.archived_at.is_(None))
    ).all()


def overall_mastery(rows, now: datetime) -> dict:
    n = len(rows)
    m_sum, mastered, due, learning_n, new, review_n, susp = 0.0, 0, 0, 0, 0, 0, 0
    for _qid, _sid, _t, _c, p in rows:
        if p is None or p.state == "new":
            new += 1
            continue
        last = as_utc(p.last_review_at)
        m_sum += fsrs.mastery_score(p.state, p.stability, last, now)
        st = fsrs.derive_status(p.state, p.stability, last, p.suspended, now)
        mastered += st == "mastered"
        learning_n += st == "learning"
        review_n += st == "reviewing"
        susp += st == "suspended"
        if not p.suspended and p.due_at and as_utc(p.due_at) <= now:
            due += 1
    return {"questions": n, "mastery": (m_sum / n) if n else 0.0, "mastered": mastered, "due": due,
            "learning": learning_n, "reviewing": review_n, "new": new, "suspended": susp}


def subject_stats(db: Session, user: User, rows, hist, now: datetime) -> list[dict]:
    subjects = list(db.scalars(select(Subject).where(Subject.user_id == user.id, Subject.archived_at.is_(None))
                               .order_by(Subject.position)))
    by_subject: dict[uuid.UUID | None, list] = {}
    for r in rows:
        by_subject.setdefault(r[1], []).append(r)
    q_subject = {r[0]: r[1] for r in rows}
    out = []
    for s in subjects:
        rs = by_subject.get(s.id, [])
        om = overall_mastery(rs, now)
        hs = [h for h in hist if q_subject.get(h.question_id) == s.id]
        ret = [h for h in hs if h.state_before == "review"]
        out.append({"id": str(s.id), "name": s.name, "color": s.color, **om,
                    "reviews": len(hs), "accuracy": round(sum(h.correct for h in hs) / len(hs), 3) if hs else None,
                    "retention": round(sum(h.correct for h in ret) / len(ret), 3) if ret else None,
                    "minutes": round(sum(h.time_ms for h in hs) / 60000, 1)})
    return out


def weak_topics(db: Session, user: User, now: datetime, limit: int = 8) -> list[dict]:
    stats = learning.topic_mastery_map(db, user, now)
    topics = {t.id: t for t in db.scalars(select(Topic).where(Topic.user_id == user.id, Topic.archived_at.is_(None)))}
    out = []
    for tid, d in stats.items():
        t = topics.get(tid)
        if not t or d["questions"] == 0:
            continue
        n, reviewed = d["questions"], d["questions"] - d["unreviewed"]
        mastery = d["mastery_sum"] / n
        accuracy = d["correct"] / d["reps"] if d["reps"] else None
        reasons = []
        if accuracy is not None and d["reps"] >= WEAK_MIN_REVIEWS and accuracy < 0.7:
            reasons.append("low_accuracy")
        if reviewed and d["reps"] >= 3 and mastery < 0.35:
            reasons.append("low_mastery")
        if d["repeated"] >= 1:
            reasons.append("repeated_mistakes")
        if d["forgotten"] >= 1:
            reasons.append("forgotten")
        if n >= 3 and d["unreviewed"] / n >= 0.5:
            reasons.append("insufficient_practice")
        if not reasons:
            continue
        score = len(reasons) * 2 + (1 - mastery) + ((1 - accuracy) if accuracy is not None else 0.3)
        out.append({"topic_id": str(tid), "name": t.name, "subject_id": str(t.subject_id), "questions": n,
                    "mastery": round(mastery, 3), "accuracy": round(accuracy, 3) if accuracy is not None else None,
                    "reviews": d["reps"], "due": d["due"], "reasons": reasons, "_score": score})
    out.sort(key=lambda x: -x["_score"])
    for o in out:
        o.pop("_score")
    return out[:limit]


def most_forgotten(db: Session, user: User, limit: int = 10) -> list[dict]:
    rows = db.execute(
        select(Question.id, Question.title, Question.content, Question.subject_id, UserQuestionProgress.lapses,
               UserQuestionProgress.reps)
        .join(UserQuestionProgress, UserQuestionProgress.question_id == Question.id)
        .where(Question.user_id == user.id, UserQuestionProgress.user_id == user.id, UserQuestionProgress.lapses > 0,
               Question.archived_at.is_(None))
        .order_by(UserQuestionProgress.lapses.desc(), UserQuestionProgress.reps.desc()).limit(limit)
    ).all()
    return [{"question_id": str(i), "title": t or c[:100], "subject_id": str(s) if s else None, "lapses": l, "reviews": r}
            for i, t, c, s, l, r in rows]


def active_days(db: Session, user: User) -> set[date]:
    return {day_of(d) for (d,) in db.execute(select(QuestionReviewHistory.reviewed_at)
                                             .where(QuestionReviewHistory.user_id == user.id)).all()}
