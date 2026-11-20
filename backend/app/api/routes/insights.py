"""Dashboard, analytics and global search."""
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, or_, select

from app.api.deps import DB, CurrentUser
from app.models.base import as_utc, utcnow
from app.models.knowledge import Chapter, Course, Subject, Tag, Topic
from app.models.learning import QuestionReviewHistory, StudySession
from app.models.note import Note
from app.models.question import Question, QuestionAnswer, question_tags, question_topics
from app.services import analytics as an
from app.services import learning

router = APIRouter(tags=["insights"])


@router.get("/dashboard")
def dashboard(db: DB, user: CurrentUser):
    now = utcnow()
    today = now.date()
    rows = an.question_states(db, user, now)
    om = an.overall_mastery(rows, now)
    hist30 = an.review_rows(db, user, now - timedelta(days=90))
    days = an.active_days(db, user)
    streak, longest = an.streaks(days, today)
    n_subjects = db.scalar(select(func.count()).select_from(Subject).where(Subject.user_id == user.id, Subject.archived_at.is_(None)))
    n_topics = db.scalar(select(func.count()).select_from(Topic).where(Topic.user_id == user.id, Topic.archived_at.is_(None)))
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    reviewed_today = sum(1 for h in hist30 if as_utc(h.reviewed_at) >= today_start)

    # continue learning: topics most recently studied
    recent = db.execute(
        select(question_topics.c.topic_id, func.max(QuestionReviewHistory.reviewed_at).label("last"))
        .join(QuestionReviewHistory, QuestionReviewHistory.question_id == question_topics.c.question_id)
        .where(QuestionReviewHistory.user_id == user.id).group_by(question_topics.c.topic_id)
        .order_by(func.max(QuestionReviewHistory.reviewed_at).desc()).limit(5)).all()
    stats = learning.topic_mastery_map(db, user, now)
    topic_map = {t.id: t for t in db.scalars(select(Topic).where(Topic.id.in_([r[0] for r in recent])))} if recent else {}
    cont = []
    for tid, last in recent:
        t = topic_map.get(tid)
        if t and t.archived_at is None:
            agg = learning.rollup(stats, learning.descendant_topic_ids(db, user, tid))
            cont.append({"topic_id": str(tid), "name": t.name, "subject_id": str(t.subject_id),
                         "last_studied": as_utc(last).isoformat(), "mastery": round(agg["mastery"], 3),
                         "questions": agg["questions"], "due": agg["due"]})

    # recent activity feed
    feed = []
    for q in db.scalars(select(Question).where(Question.user_id == user.id).order_by(Question.created_at.desc()).limit(5)):
        feed.append({"type": "question", "id": str(q.id), "title": q.title or q.content[:80], "at": as_utc(q.created_at).isoformat()})
    for n in db.scalars(select(Note).where(Note.user_id == user.id).order_by(Note.updated_at.desc()).limit(5)):
        feed.append({"type": "note", "id": str(n.id), "title": n.title or "Untitled note", "at": as_utc(n.updated_at).isoformat()})
    for t in db.scalars(select(Topic).where(Topic.user_id == user.id).order_by(Topic.created_at.desc()).limit(5)):
        feed.append({"type": "topic", "id": str(t.id), "title": t.name, "at": as_utc(t.created_at).isoformat()})
    for s in db.scalars(select(StudySession).where(StudySession.user_id == user.id).order_by(StudySession.started_at.desc()).limit(5)):
        n = db.scalar(select(func.count()).select_from(QuestionReviewHistory).where(QuestionReviewHistory.session_id == s.id))
        feed.append({"type": "session", "id": str(s.id), "title": f"{s.mode.replace('_', ' ')} session · {n} answered",
                     "at": as_utc(s.started_at).isoformat()})
    feed.sort(key=lambda x: x["at"], reverse=True)

    start = today - timedelta(days=29)
    series = an.daily_series([h for h in hist30 if an.day_of(h.reviewed_at) >= start], start, today)
    per_review = learning.avg_seconds_per_review(db, user)
    return {
        "totals": {"subjects": n_subjects, "topics": n_topics, "questions": om["questions"],
                   "mastered": om["mastered"], "needs_review": om["due"] + om["learning"],
                   "due_today": om["due"], "streak": streak, "longest_streak": longest,
                   "mastery": round(om["mastery"], 3), "reviewed_today": reviewed_today,
                   "daily_goal": user.daily_review_goal},
        "review_today": {"due": om["due"], "estimated_seconds": int(om["due"] * per_review),
                         "new_available": max(0, min(om["new"], user.daily_new_limit - learning.new_started_today(db, user, now)))},
        "status_distribution": {k: om[k] for k in ("new", "learning", "reviewing", "mastered", "suspended")},
        "continue_learning": cont,
        "subjects": an.subject_stats(db, user, rows, hist30, now),
        "weak_areas": an.weak_topics(db, user, now, limit=5),
        "recent_activity": feed[:10],
        "activity_series": series,
        "retention_trend": an.retention_trend(hist30, 8, today),
    }


@router.get("/analytics")
def analytics(db: DB, user: CurrentUser, days: Annotated[int, Query(ge=7, le=730)] = 30):
    now = utcnow()
    today = now.date()
    since = now - timedelta(days=days)
    all_hist = an.review_rows(db, user)
    hist = [h for h in all_hist if as_utc(h.reviewed_at) >= since]
    rows = an.question_states(db, user, now)
    om = an.overall_mastery(rows, now)
    streak, longest = an.streaks({an.day_of(h.reviewed_at) for h in all_hist}, today)

    n = len(hist)
    ret = [h for h in hist if h.state_before == "review"]
    completed = sum(1 for h in hist if h.state_before != "new")
    since_start = since
    still_overdue = sum(1 for _q, _s, _t, _c, p in rows if p and not p.suspended and p.state != "new" and p.due_at
                        and since_start <= as_utc(p.due_at) <= now)
    completion = completed / (completed + still_overdue) if (completed + still_overdue) else None

    subjects = an.subject_stats(db, user, rows, hist, now)
    ranked = [s for s in subjects if s["questions"] >= 1 and s["reviews"] >= 1]
    topics = []
    stats = learning.topic_mastery_map(db, user, now)
    tnames = {t.id: t for t in db.scalars(select(Topic).where(Topic.user_id == user.id, Topic.archived_at.is_(None)))}
    for tid, d in stats.items():
        t = tnames.get(tid)
        if t and d["questions"]:
            topics.append({"topic_id": str(tid), "name": t.name, "subject_id": str(t.subject_id),
                           "questions": d["questions"], "mastery": round(d["mastery_sum"] / d["questions"], 3),
                           "accuracy": round(d["correct"] / d["reps"], 3) if d["reps"] else None,
                           "reviews": d["reps"], "lapses": d["lapses"], "due": d["due"]})
    topics.sort(key=lambda x: x["mastery"])

    series_start = max(today - timedelta(days=days - 1), today - timedelta(days=364))
    return {
        "period_days": days,
        "summary": {
            "total_questions": om["questions"], "questions_answered": len({h.question_id for h in hist}),
            "reviews": n, "accuracy": round(sum(h.correct for h in hist) / n, 3) if n else None,
            "retention": round(sum(h.correct for h in ret) / len(ret), 3) if ret else None,
            "retention_sample": len(ret), "mastery": round(om["mastery"], 3), "mastered": om["mastered"],
            "streak": streak, "longest_streak": longest,
            "study_minutes": round(sum(h.time_ms for h in hist) / 60000, 1),
            "completion_rate": round(completion, 3) if completion is not None else None,
            "active_days": len({an.day_of(h.reviewed_at) for h in hist}),
        },
        "status_distribution": {k: om[k] for k in ("new", "learning", "reviewing", "mastered", "suspended")},
        "daily": an.daily_series(hist, series_start, today),
        "retention_trend": an.retention_trend(all_hist, max(4, min(days // 7, 26)), today),
        "subjects": subjects,
        "strongest_subjects": sorted(ranked, key=lambda s: -s["mastery"])[:3],
        "weakest_subjects": sorted(ranked, key=lambda s: s["mastery"])[:3],
        "topics": topics[:50],
        "weak_topics": an.weak_topics(db, user, now, limit=10),
        "most_forgotten": an.most_forgotten(db, user),
        "definitions": {
            "accuracy": "Share of answers rated Hard, Good or Easy (not Again).",
            "retention": "Accuracy on reviews of already-learned questions. Compare to your target retention.",
            "mastery": "Recall probability × memory maturity, averaged over all questions. Unstudied questions count as 0 and mastery decays without review.",
            "completion": "Share of reviews that fell due in the period that you actually completed.",
            "activity": "Volume only: reviews, minutes and streak. Not a measure of knowledge.",
        },
    }


# ---------- global search ----------
@router.get("/search")
def search(db: DB, user: CurrentUser, q: Annotated[str, Query(min_length=1, max_length=200)],
           types: Annotated[list[str] | None, Query()] = None, limit: Annotated[int, Query(ge=1, le=50)] = 8):
    like = f"%{q.strip()}%"
    want = set(types) if types else {"subject", "course", "topic", "question", "answer", "note", "tag"}
    out: list[dict] = []

    def snippet(text: str) -> str:
        i = text.lower().find(q.strip().lower())
        if i < 0:
            return text[:120]
        return ("…" if i > 40 else "") + text[max(0, i - 40): i + 100].replace("\n", " ")

    if "subject" in want:
        for s in db.scalars(select(Subject).where(Subject.user_id == user.id, or_(Subject.name.ilike(like), Subject.description.ilike(like))).limit(limit)):
            out.append({"type": "subject", "id": str(s.id), "title": s.name, "snippet": snippet(s.description), "subject_id": str(s.id)})
    if "course" in want:
        for c in db.scalars(select(Course).where(Course.user_id == user.id, or_(Course.name.ilike(like), Course.description.ilike(like))).limit(limit)):
            out.append({"type": "course", "id": str(c.id), "title": c.name, "snippet": snippet(c.description), "subject_id": str(c.subject_id)})
    if "topic" in want:
        for t in db.scalars(select(Topic).where(Topic.user_id == user.id, or_(Topic.name.ilike(like), Topic.description.ilike(like))).limit(limit)):
            out.append({"type": "topic", "id": str(t.id), "title": t.name, "snippet": snippet(t.description), "subject_id": str(t.subject_id)})
    if "question" in want:
        for x in db.scalars(select(Question).where(Question.user_id == user.id, or_(Question.title.ilike(like), Question.content.ilike(like))).limit(limit)):
            out.append({"type": "question", "id": str(x.id), "title": x.title or x.content[:80], "snippet": snippet(x.content)})
    if "answer" in want:
        for qq, a in db.execute(select(Question, QuestionAnswer).join(QuestionAnswer, QuestionAnswer.question_id == Question.id)
                                .where(Question.user_id == user.id, or_(QuestionAnswer.answer.ilike(like), QuestionAnswer.explanation.ilike(like))).limit(limit)).all():
            if not any(o["type"] == "question" and o["id"] == str(qq.id) for o in out):
                out.append({"type": "answer", "id": str(qq.id), "title": qq.title or qq.content[:80],
                            "snippet": snippet(a.answer if q.lower() in a.answer.lower() else a.explanation)})
    if "note" in want:
        for n in db.scalars(select(Note).where(Note.user_id == user.id, or_(Note.title.ilike(like), Note.content.ilike(like))).limit(limit)):
            out.append({"type": "note", "id": str(n.id), "title": n.title or "Untitled note", "snippet": snippet(n.content)})
    if "tag" in want:
        for t in db.scalars(select(Tag).where(Tag.user_id == user.id, Tag.name.ilike(like)).limit(limit)):
            cnt = db.scalar(select(func.count()).select_from(question_tags).where(question_tags.c.tag_id == t.id))
            out.append({"type": "tag", "id": str(t.id), "title": t.name, "snippet": f"{cnt} questions"})

    def rank(r):  # exact/prefix title matches first
        t = r["title"].lower()
        ql = q.strip().lower()
        return (0 if t == ql else 1 if t.startswith(ql) else 2 if ql in t else 3)

    out.sort(key=rank)
    return {"query": q, "results": out}
