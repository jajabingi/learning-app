import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import check_owned_optional, owned_many
from app.models.base import as_utc, utcnow
from app.models.knowledge import Subject, Topic
from app.models.learning import UserQuestionProgress
from app.models.question import Attachment, Question, QuestionAnswer, QuestionOption
from app.models.user import User
from app.schemas.question import (
    AnswerIn, AttachmentOut, OptionOut, ProgressOut, QuestionBase, QuestionOut, TopicMini,
)
from app.schemas.knowledge import TagOut
from app.services import fsrs
from app.services.tags import resolve_tags


def progress_out(p: UserQuestionProgress | None) -> ProgressOut:
    if p is None:
        return ProgressOut()
    now = utcnow()
    last = as_utc(p.last_review_at)
    return ProgressOut(
        status=fsrs.derive_status(p.state, p.stability, last, p.suspended, now),
        state=p.state, suspended=p.suspended, stability=round(p.stability, 2),
        difficulty=round(p.difficulty, 2), reps=p.reps, lapses=p.lapses, correct_count=p.correct_count,
        confidence=p.confidence, last_review_at=last, due_at=as_utc(p.due_at),
        retrievability=fsrs.current_retrievability(p.stability, last, now),
        mastery=round(fsrs.mastery_score(p.state, p.stability, last, now), 3),
    )


def serialize(db: Session, user: User, questions: list[Question], *, include_attachments: bool = False) -> list[QuestionOut]:
    ids = [q.id for q in questions]
    prog = {}
    atts: dict[uuid.UUID, list[Attachment]] = {}
    if ids:
        prog = {p.question_id: p for p in db.scalars(
            select(UserQuestionProgress).where(UserQuestionProgress.user_id == user.id,
                                               UserQuestionProgress.question_id.in_(ids)))}
        if include_attachments:
            for a in db.scalars(select(Attachment).where(Attachment.question_id.in_(ids))):
                atts.setdefault(a.question_id, []).append(a)
    out = []
    for q in questions:
        out.append(QuestionOut(
            id=q.id, title=q.title, content=q.content, question_type=q.question_type, difficulty=q.difficulty,
            source=q.source, subject_id=q.subject_id,
            topics=[TopicMini.model_validate(t) for t in q.topics],
            tags=[TagOut.model_validate(t) for t in q.tags],
            answer=AnswerIn(answer=q.answer.answer, explanation=q.answer.explanation) if q.answer else AnswerIn(),
            options=[OptionOut.model_validate(o) for o in q.options],
            attachments=[AttachmentOut.model_validate(a) for a in atts.get(q.id, [])],
            archived=q.archived_at is not None, created_at=q.created_at, updated_at=q.updated_at,
            progress=progress_out(prog.get(q.id)),
        ))
    return out


def _validate_refs(db: Session, user: User, subject_id, topic_ids):
    check_owned_optional(db, Subject, subject_id, user)
    topics = owned_many(db, Topic, topic_ids or [], user)
    return topics


def set_options(q: Question, options) -> None:
    q.options.clear()
    for i, o in enumerate(options):
        q.options.append(QuestionOption(text=o.text, is_correct=o.is_correct, position=i))


def create_question(db: Session, user: User, data: QuestionBase) -> Question:
    topics = _validate_refs(db, user, data.subject_id, data.topic_ids)
    subject_id = data.subject_id or (topics[0].subject_id if topics else None)
    q = Question(
        user_id=user.id, subject_id=subject_id, title=data.title.strip(), content=data.content,
        question_type=data.question_type, difficulty=data.difficulty, source=data.source,
    )
    q.answer = QuestionAnswer(answer=data.answer.answer, explanation=data.answer.explanation)
    set_options(q, data.options)
    q.topics = topics
    q.tags = resolve_tags(db, user, data.tags)
    db.add(q)
    db.flush()
    return q


def update_question(db: Session, user: User, q: Question, patch) -> Question:
    fields = patch.model_fields_set
    for f in ("title", "content", "question_type", "difficulty", "source"):
        if f in fields and getattr(patch, f) is not None:
            setattr(q, f, getattr(patch, f).strip() if f == "title" else getattr(patch, f))
    if patch.set_subject:
        check_owned_optional(db, Subject, patch.subject_id, user)
        q.subject_id = patch.subject_id
    if patch.topic_ids is not None:
        q.topics = owned_many(db, Topic, patch.topic_ids, user)
        if q.subject_id is None and q.topics:
            q.subject_id = q.topics[0].subject_id
    if patch.tags is not None:
        q.tags = resolve_tags(db, user, patch.tags)
    if patch.answer is not None:
        if q.answer is None:
            q.answer = QuestionAnswer()
        q.answer.answer, q.answer.explanation = patch.answer.answer, patch.answer.explanation
    if patch.options is not None:
        set_options(q, patch.options)
    if patch.archived is not None:
        q.archived_at = utcnow() if patch.archived else None
    if patch.confidence is not None:
        from app.services.learning import get_progress
        get_progress(db, user, q.id).confidence = patch.confidence
    q.updated_at = utcnow()
    db.flush()
    return q
