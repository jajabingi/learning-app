import copy
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Body, HTTPException, Query, status
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.api.deps import DB, CurrentUser, check_owned_optional, owned
from app.models.base import as_utc, utcnow
from app.models.knowledge import Subject, Tag, Topic
from app.models.learning import QuestionReviewHistory, UserQuestionProgress
from app.models.question import Attachment, Question, QuestionAnswer, QuestionOption, question_tags, question_topics
from app.schemas.question import BulkIn, QuestionCreate, QuestionOut, QuestionPage, QuestionUpdate
from app.services import fsrs, learning
from app.services.questions import create_question, serialize, update_question
from app.services.tags import normalize, resolve_tags

router = APIRouter(prefix="/questions", tags=["questions"])

SORTS = {
    "created_desc": lambda: Question.created_at.desc(),
    "created_asc": lambda: Question.created_at.asc(),
    "updated_desc": lambda: Question.updated_at.desc(),
    "title": lambda: Question.title.asc(),
    "due": lambda: UserQuestionProgress.due_at.asc().nulls_last(),
    "lapses": lambda: UserQuestionProgress.lapses.desc().nulls_last(),
}


def filtered_ids(db: Session, user, *, q=None, subject_id=None, topic_id=None, tags=None, question_type=None,
                 difficulty=None, status_=None, archived=False, sort="created_desc", unfiled=False):
    stmt = (
        select(Question.id, UserQuestionProgress)
        .outerjoin(UserQuestionProgress, and_(UserQuestionProgress.question_id == Question.id,
                                              UserQuestionProgress.user_id == user.id))
        .where(Question.user_id == user.id)
    )
    stmt = stmt.where(Question.archived_at.is_not(None) if archived else Question.archived_at.is_(None))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(
            Question.title.ilike(like), Question.content.ilike(like), Question.source.ilike(like),
            Question.id.in_(select(QuestionAnswer.question_id).where(
                or_(QuestionAnswer.answer.ilike(like), QuestionAnswer.explanation.ilike(like)))),
        ))
    if subject_id:
        stmt = stmt.where(Question.subject_id == subject_id)
    if unfiled:
        stmt = stmt.where(~Question.id.in_(select(question_topics.c.question_id)))
    if topic_id:
        ids = learning.descendant_topic_ids(db, user, topic_id)
        stmt = stmt.where(Question.id.in_(select(question_topics.c.question_id).where(question_topics.c.topic_id.in_(ids))))
    for name in tags or []:
        stmt = stmt.where(Question.id.in_(
            select(question_tags.c.question_id).join(Tag, Tag.id == question_tags.c.tag_id)
            .where(Tag.user_id == user.id, Tag.name == normalize(name))))
    if question_type:
        stmt = stmt.where(Question.question_type == question_type)
    if difficulty:
        stmt = stmt.where(Question.difficulty == difficulty)
    stmt = stmt.order_by(SORTS.get(sort, SORTS["created_desc"])(), Question.id)
    rows = db.execute(stmt).all()
    if status_:
        now = utcnow()
        keep = []
        for qid, p in rows:
            st = "new" if p is None else fsrs.derive_status(p.state, p.stability, as_utc(p.last_review_at), p.suspended, now)
            if st == status_ or (status_ == "due" and p is not None and not p.suspended and p.due_at and as_utc(p.due_at) <= now):
                keep.append((qid, p))
        rows = keep
    return [r[0] for r in rows]


@router.get("", response_model=QuestionPage)
def list_questions(
    db: DB, user: CurrentUser,
    q: str | None = None, subject_id: uuid.UUID | None = None, topic_id: uuid.UUID | None = None,
    tag: Annotated[list[str] | None, Query()] = None, question_type: str | None = None,
    difficulty: Literal["easy", "medium", "hard"] | None = None,
    status: Literal["new", "learning", "reviewing", "mastered", "suspended", "due"] | None = None,
    archived: bool = False, unfiled: bool = False, sort: str = "created_desc",
    page: Annotated[int, Query(ge=1)] = 1, page_size: Annotated[int, Query(ge=1, le=200)] = 25,
):
    ids = filtered_ids(db, user, q=q, subject_id=subject_id, topic_id=topic_id, tags=tag, question_type=question_type,
                       difficulty=difficulty, status_=status, archived=archived, sort=sort, unfiled=unfiled)
    page_ids = ids[(page - 1) * page_size: page * page_size]
    objs = {o.id: o for o in db.scalars(select(Question).where(Question.id.in_(page_ids)))} if page_ids else {}
    items = serialize(db, user, [objs[i] for i in page_ids if i in objs])
    return QuestionPage(items=items, total=len(ids), page=page, page_size=page_size)


@router.post("", response_model=QuestionOut, status_code=201)
def create(data: QuestionCreate, db: DB, user: CurrentUser):
    q = create_question(db, user, data)
    return serialize(db, user, [q], include_attachments=True)[0]


@router.post("/batch", response_model=list[QuestionOut], status_code=201)
def create_batch(data: Annotated[list[QuestionCreate], Body(max_length=100)], db: DB, user: CurrentUser):
    """Save several (e.g. AI-generated, user-approved) questions in one transaction."""
    qs = [create_question(db, user, d) for d in data]
    return serialize(db, user, qs)


@router.get("/{question_id}", response_model=QuestionOut)
def get_one(question_id: uuid.UUID, db: DB, user: CurrentUser):
    q = owned(db, Question, question_id, user)
    return serialize(db, user, [q], include_attachments=True)[0]


@router.patch("/{question_id}", response_model=QuestionOut)
def patch(question_id: uuid.UUID, data: QuestionUpdate, db: DB, user: CurrentUser):
    q = owned(db, Question, question_id, user)
    update_question(db, user, q, data)
    return serialize(db, user, [q], include_attachments=True)[0]


@router.delete("/{question_id}", status_code=204)
def delete(question_id: uuid.UUID, db: DB, user: CurrentUser):
    db.delete(owned(db, Question, question_id, user))


@router.post("/{question_id}/duplicate", response_model=QuestionOut, status_code=201)
def duplicate(question_id: uuid.UUID, db: DB, user: CurrentUser):
    src = owned(db, Question, question_id, user)
    q = Question(user_id=user.id, subject_id=src.subject_id, title=(src.title + " (copy)")[:300], content=src.content,
                 question_type=src.question_type, difficulty=src.difficulty, source=src.source)
    q.answer = QuestionAnswer(answer=src.answer.answer if src.answer else "", explanation=src.answer.explanation if src.answer else "")
    q.options = [QuestionOption(text=o.text, is_correct=o.is_correct, position=o.position) for o in src.options]
    q.topics, q.tags = list(src.topics), list(src.tags)
    db.add(q)
    db.flush()
    return serialize(db, user, [q])[0]


@router.post("/{question_id}/progress/reset", status_code=204)
def reset_progress(question_id: uuid.UUID, db: DB, user: CurrentUser):
    q = owned(db, Question, question_id, user)
    _reset(db, user, [q.id])


@router.post("/{question_id}/suspend", status_code=204)
def suspend(question_id: uuid.UUID, db: DB, user: CurrentUser, suspended: bool = True):
    q = owned(db, Question, question_id, user)
    p = learning.get_progress(db, user, q.id)
    p.suspended = suspended
    learning.refresh_status(p)


@router.get("/{question_id}/history")
def history(question_id: uuid.UUID, db: DB, user: CurrentUser):
    q = owned(db, Question, question_id, user)
    rows = db.scalars(select(QuestionReviewHistory).where(QuestionReviewHistory.question_id == q.id)
                      .order_by(QuestionReviewHistory.reviewed_at.desc()).limit(100))
    return [{"id": str(h.id), "reviewed_at": as_utc(h.reviewed_at).isoformat(), "rating": h.rating,
             "correct": h.correct, "study_mode": h.study_mode, "time_ms": h.time_ms,
             "stability_after": round(h.stability_after, 2), "scheduled_days": round(h.scheduled_days, 2),
             "retrievability_before": h.retrievability_before, "response_text": h.response_text,
             "ai_score": h.ai_score} for h in rows]


def _reset(db: Session, user, qids):
    for p in db.scalars(select(UserQuestionProgress).where(UserQuestionProgress.user_id == user.id,
                                                            UserQuestionProgress.question_id.in_(qids))):
        p.state, p.status, p.stability, p.difficulty = "new", "new", 0.0, 0.0
        p.reps = p.lapses = p.correct_count = 0
        p.last_review_at = p.due_at = p.last_rating = None
        p.scheduled_days = 0.0


@router.post("/bulk/apply")
def bulk(data: BulkIn, db: DB, user: CurrentUser):
    qs = list(db.scalars(select(Question).where(Question.id.in_(data.ids), Question.user_id == user.id)))
    if len(qs) != len(set(data.ids)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Some questions were not found")
    a = data.action
    if a == "delete":
        for q in qs:
            db.delete(q)
    elif a in ("archive", "unarchive"):
        for q in qs:
            q.archived_at = utcnow() if a == "archive" else None
    elif a in ("add_tags", "remove_tags"):
        tags = resolve_tags(db, user, data.tags)
        if not tags:
            raise HTTPException(422, "No tags provided")
        for q in qs:
            if a == "add_tags":
                q.tags = list({t.id: t for t in [*q.tags, *tags]}.values())
            else:
                rm = {t.id for t in tags}
                q.tags = [t for t in q.tags if t.id not in rm]
    elif a == "set_subject":
        check_owned_optional(db, Subject, data.subject_id, user)
        for q in qs:
            q.subject_id = data.subject_id
    elif a == "add_topic":
        if not data.topic_id:
            raise HTTPException(422, "topic_id required")
        topic = owned(db, Topic, data.topic_id, user)
        for q in qs:
            if topic not in q.topics:
                q.topics.append(topic)
            if q.subject_id is None:
                q.subject_id = topic.subject_id
    elif a == "set_difficulty":
        if not data.difficulty:
            raise HTTPException(422, "difficulty required")
        for q in qs:
            q.difficulty = data.difficulty
    elif a in ("suspend", "unsuspend"):
        for q in qs:
            p = learning.get_progress(db, user, q.id)
            p.suspended = a == "suspend"
            learning.refresh_status(p)
    elif a == "reset_progress":
        _reset(db, user, [q.id for q in qs])
    return {"affected": len(qs)}


# ---------- attachments ----------
@router.get("/{question_id}/attachments")
def list_attachments(question_id: uuid.UUID, db: DB, user: CurrentUser):
    owned(db, Question, question_id, user)
    return [{"id": str(a.id), "filename": a.filename, "content_type": a.content_type, "size_bytes": a.size_bytes}
            for a in db.scalars(select(Attachment).where(Attachment.question_id == question_id))]
