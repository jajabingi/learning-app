import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DB, CurrentUser, owned
from app.core.config import get_settings
from app.core.security import ai_limiter
from app.models.base import utcnow
from app.models.knowledge import Subject, Topic
from app.models.note import Note
from app.models.question import Question
from app.schemas.question import QuestionCreate
from app.services import analytics as an
from app.services import learning
from app.services.ai import service as ai
from app.services.ai.provider import AIError, get_provider
from app.services.questions import create_question, serialize

router = APIRouter(prefix="/ai", tags=["ai"])
settings = get_settings()


def _wrap(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except AIError as e:
        raise HTTPException(e.status_code, e.message)


@router.get("/status")
def status(user: CurrentUser):
    p = get_provider()
    return {"enabled": p is not None, "provider": p.name if p else None, "model": p.model if p else None}


class GenerateIn(BaseModel):
    text: str = Field(default="", max_length=60000)
    topic_id: uuid.UUID | None = None
    note_id: uuid.UUID | None = None
    count: int = Field(default=5, ge=1, le=20)
    level: Literal["basic", "intermediate", "advanced", "mixed"] = "mixed"
    types: list[str] = Field(default=[], max_length=11)


def _question_context(q: Question) -> str:
    opts = "\n".join(f"- {o.text}{' (correct)' if o.is_correct else ''}" for o in q.options)
    return (f"Question type: {q.question_type}\nTitle: {q.title}\nQuestion: {q.content}\n"
            + (f"Options:\n{opts}\n" if opts else "")
            + (f"Reference answer: {q.answer.answer}\nExplanation: {q.answer.explanation}\n" if q.answer else ""))


def _topic_context(topic: Topic) -> str:
    return f"Topic: {topic.name}\n{topic.description}"


@router.post("/generate-questions", dependencies=[Depends(ai_limiter)])
def generate(data: GenerateIn, db: DB, user: CurrentUser):
    """Returns DRAFT questions only. Nothing is saved until the user confirms via POST /questions/batch."""
    parts, hint, subject_id, topic_ids = [], "", None, []
    if data.text.strip():
        parts.append(data.text.strip())
    if data.topic_id:
        t = owned(db, Topic, data.topic_id, user)
        parts.append(_topic_context(t))
        hint, subject_id, topic_ids = t.name, t.subject_id, [t.id]
        for n in db.scalars(select(Note).where(Note.user_id == user.id, Note.topic_id == t.id).limit(10)):
            parts.append(f"Note — {n.title}\n{n.content}")
    if data.note_id:
        n = owned(db, Note, data.note_id, user)
        parts.append(f"Note — {n.title}\n{n.content}")
    material = "\n\n".join(parts).strip()
    if len(material) < 20:
        raise HTTPException(422, "Provide some text, a topic or a note to generate questions from")
    drafts = _wrap(ai.generate_questions, material=material, count=data.count, level=data.level,
                   types=data.types, topic_hint=hint)
    for d in drafts:
        d["subject_id"], d["topic_ids"] = (str(subject_id) if subject_id else None), [str(i) for i in topic_ids]
    return {"questions": drafts}


class EvaluateIn(BaseModel):
    question_id: uuid.UUID
    answer: str = Field(min_length=1, max_length=10000)


@router.post("/evaluate", dependencies=[Depends(ai_limiter)])
def evaluate(data: EvaluateIn, db: DB, user: CurrentUser):
    answer = data.answer
    if not answer.strip():
        raise HTTPException(422, "Write an answer first")
    q = owned(db, Question, data.question_id, user)
    return _wrap(ai.evaluate_answer, question=f"{q.title}\n{q.content}",
                 reference=q.answer.answer if q.answer else "", explanation=q.answer.explanation if q.answer else "",
                 user_answer=answer)


class TutorIn(BaseModel):
    action: str
    question_id: uuid.UUID | None = None
    topic_id: uuid.UUID | None = None
    other_topic_id: uuid.UUID | None = None
    other_text: str = Field(default="", max_length=4000)
    user_answer: str = Field(default="", max_length=6000)
    message: str = Field(default="", max_length=4000)


@router.post("/tutor", dependencies=[Depends(ai_limiter)])
def tutor(data: TutorIn, db: DB, user: CurrentUser):
    if not (data.question_id or data.topic_id):
        raise HTTPException(422, "question_id or topic_id is required")
    ctx, other = "", data.other_text
    if data.question_id:
        q = owned(db, Question, data.question_id, user)
        ctx = _question_context(q)
    if data.topic_id:
        ctx += ("\n" if ctx else "") + _topic_context(owned(db, Topic, data.topic_id, user))
    if data.other_topic_id:
        other += "\n" + _topic_context(owned(db, Topic, data.other_topic_id, user))
    reply = _wrap(ai.tutor, action=data.action, context=ctx, other=other, user_answer=data.user_answer,
                  message=data.message)
    return {"reply": reply}


class PlanIn(BaseModel):
    goal: str = Field(min_length=3, max_length=1000)
    minutes_per_day: int = Field(default=30, ge=5, le=600)
    days: int = Field(default=7, ge=1, le=90)
    subject_id: uuid.UUID | None = None


@router.post("/study-plan", dependencies=[Depends(ai_limiter)])
def plan(data: PlanIn, db: DB, user: CurrentUser):
    now = utcnow()
    rows = an.question_states(db, user, now)
    if data.subject_id:
        owned(db, Subject, data.subject_id, user)
        rows = [r for r in rows if r[1] == data.subject_id]
    om = an.overall_mastery(rows, now)
    hist = an.review_rows(db, user)
    subs = an.subject_stats(db, user, an.question_states(db, user, now), hist, now)
    weak = an.weak_topics(db, user, now, limit=8)
    lines = [f"Questions: {om['questions']} (new {om['new']}, learning {om['learning']}, reviewing {om['reviewing']}, "
             f"mastered {om['mastered']}); due now: {om['due']}; overall mastery {om['mastery']:.0%}",
             f"Daily new-question limit: {user.daily_new_limit}", "Subjects:"]
    lines += [f"- {s['name']}: {s['questions']} questions, mastery {s['mastery']:.0%}, due {s['due']}, "
              f"accuracy {s['accuracy'] if s['accuracy'] is not None else 'n/a'}" for s in subs]
    lines.append("Weak topics:")
    lines += [f"- {w['name']}: mastery {w['mastery']:.0%}, reasons: {', '.join(w['reasons'])}" for w in weak] or ["- none detected"]
    plan_md = _wrap(ai.study_plan, goal=data.goal, minutes_per_day=data.minutes_per_day, days=data.days,
                    snapshot="\n".join(lines))
    return {"plan": plan_md}
