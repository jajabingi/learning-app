"""Lesson content blocks: per-type validation for teachers, and a student-safe projection.

Blocks are stored as `type` + JSON `data`. The data is validated here on every write, so nothing unvalidated is ever
stored, and `student_view` decides exactly what a student may receive (e.g. never answers or the master question bank).
"""
import uuid
from typing import Annotated, Literal

from fastapi import HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import create_media_token
from app.models.question import Attachment, Question
from app.services.video import VideoError, resolve_video

BLOCK_TYPES = (
    "video", "text", "summary", "rich_text", "image", "pdf", "file", "formula", "table", "example", "question",
    "quiz", "assignment", "external_link", "callout", "resource",
)
MD = Field(default="", max_length=100_000)
_url = TypeAdapter(HttpUrl)


class _B(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Video(_B):
    url: str = Field(default="", max_length=2000)
    attachment_id: uuid.UUID | None = None  # uploaded video (served through signed, range-capable media URLs)
    title: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=5000)
    thumbnail_url: str = Field(default="", max_length=2000)


class Markdownish(_B):
    title: str = Field(default="", max_length=200)
    markdown: str = MD


class Image(_B):
    attachment_id: uuid.UUID | None = None
    url: str = Field(default="", max_length=2000)
    alt: str = Field(default="", max_length=300)
    caption: str = Field(default="", max_length=500)


class FileRef(_B):
    attachment_id: uuid.UUID | None = None
    url: str = Field(default="", max_length=2000)
    title: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=2000)


class Formula(_B):
    title: str = Field(default="", max_length=200)
    latex: str = Field(default="", max_length=5000)
    description: str = Field(default="", max_length=5000)


class QuestionRef(_B):
    question_id: uuid.UUID
    show_answer: Literal["never", "after_attempt", "always"] = "after_attempt"


class QuizSettings(_B):
    time_limit_min: int | None = Field(default=None, ge=1, le=600)
    passing_grade: int = Field(default=60, ge=0, le=100)
    attempts: int | None = Field(default=None, ge=1, le=100)  # None = unlimited
    shuffle: bool = False
    show_answers: Literal["immediately", "after_submit", "never"] = "after_submit"


class Quiz(_B):
    title: str = Field(default="", max_length=200)
    question_ids: list[uuid.UUID] = Field(default=[], max_length=200)
    practice_set_id: uuid.UUID | None = None  # students take the quiz through this practice set (access-checked server-side)
    settings: QuizSettings = QuizSettings()


class Assignment(_B):
    title: str = Field(default="", max_length=200)
    instructions: str = MD
    points: int = Field(default=100, ge=0, le=10000)


class Link(_B):
    url: str = Field(max_length=2000)
    title: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=2000)


class Callout(_B):
    variant: Literal["info", "tip", "warning", "important"] = "info"
    markdown: str = MD


MODELS: dict[str, type[_B]] = {
    "video": Video, "text": Markdownish, "summary": Markdownish, "rich_text": Markdownish, "table": Markdownish,
    "example": Markdownish, "image": Image, "pdf": FileRef, "file": FileRef, "resource": FileRef, "formula": Formula,
    "question": QuestionRef, "quiz": Quiz, "assignment": Assignment, "external_link": Link, "callout": Callout,
}


def _bad(msg: str):
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, msg)


def _check_url(u: str, field: str, schemes=("https",)) -> str:
    if not u:
        return u
    try:
        _url.validate_python(u)
    except ValidationError:
        raise _bad(f"{field}: not a valid URL")
    if not u.lower().startswith(tuple(s + "://" for s in schemes)):
        raise _bad(f"{field}: must start with {' or '.join(s + '://' for s in schemes)}")
    return u


def clean_block(db: Session, owner_id: uuid.UUID, block_type: str, data: dict) -> dict:
    """Validate and normalise block data. References (files, questions) must belong to the course owner."""
    model = MODELS.get(block_type)
    if model is None:
        raise _bad(f"Unknown block type: {block_type}")
    if block_type == "video":  # derived fields are recomputed, never trusted from the client
        data = {k: v for k, v in (data or {}).items() if k not in ("resolved", "playback_url")}
    try:
        obj = model.model_validate(data or {})
    except ValidationError as e:
        err = e.errors()[0]
        raise _bad(f"{'.'.join(str(x) for x in err['loc']) or 'data'}: {err['msg']}")
    out = obj.model_dump(mode="json")

    if block_type == "video":
        if out["attachment_id"]:
            att = db.get(Attachment, uuid.UUID(out["attachment_id"]))
            if att is None or att.user_id != owner_id or not att.content_type.startswith("video/"):
                raise _bad("Video file not found")
            out["url"] = ""
            out["resolved"] = {"provider": "upload", "kind": "upload", "embed_url": None, "url": None, "external_id": out["attachment_id"]}
        else:
            if not out["url"]:
                raise _bad("Upload a video or paste a video URL")
            try:
                out["resolved"] = resolve_video(out["url"])
            except VideoError as e:
                raise _bad(str(e))
        out["thumbnail_url"] = _check_url(out["thumbnail_url"], "thumbnail_url")
    elif block_type in ("image", "pdf", "file", "resource"):
        out["url"] = _check_url(out["url"], "url", ("https",) if block_type == "image" else ("https", "http"))
        if not out["attachment_id"] and not out["url"]:
            raise _bad("Provide an uploaded file or a URL")
        if out["attachment_id"]:
            att = db.get(Attachment, uuid.UUID(out["attachment_id"]))
            if att is None or att.user_id != owner_id:
                raise _bad("File not found")
    elif block_type == "external_link":
        out["url"] = _check_url(out["url"], "url", ("https", "http"))
    elif block_type == "question":
        q = db.get(Question, uuid.UUID(out["question_id"]))
        if q is None or q.user_id != owner_id:
            raise _bad("Question not found in your question bank")
    elif block_type == "quiz":
        ids = [uuid.UUID(i) for i in out["question_ids"]]
        found = set(db.scalars(select(Question.id).where(Question.id.in_(ids), Question.user_id == owner_id)))
        if len(found) != len(set(ids)):
            raise _bad("Some questions were not found in your question bank")
    return out


def decorate(block_type: str, data: dict) -> dict:
    """Add render-time fields (not stored): a signed playback URL for uploaded videos."""
    d = dict(data or {})
    if block_type == "video" and d.get("attachment_id"):
        d["playback_url"] = f"/api/media/video/{d['attachment_id']}?t={create_media_token(uuid.UUID(d['attachment_id']))}"
    return d


# ---------------- student-safe projection ----------------
def _question_view(q: Question, include_answer: bool) -> dict:
    v = {"id": str(q.id), "title": q.title, "content": q.content, "question_type": q.question_type,
         # option ids/text only: correctness is never sent with the question
         "options": [{"id": str(o.id), "text": o.text} for o in q.options]}
    if include_answer and q.answer:
        v["answer"] = {"answer": q.answer.answer, "explanation": q.answer.explanation}
    return v


def student_view(db: Session, block) -> dict:
    """What a student may see of a block. Never includes the master question bank, answers, or teacher-only fields."""
    d = dict(block.data or {})
    out = {"id": str(block.id), "type": block.type, "position": block.position}
    if block.type == "question":
        q = db.get(Question, uuid.UUID(d["question_id"]))
        out["data"] = {"question": _question_view(q, include_answer=False) if q else None,
                       "show_answer": d.get("show_answer", "after_attempt")}
    elif block.type == "quiz":
        ids = [uuid.UUID(i) for i in d.get("question_ids", [])]
        qs = {q.id: q for q in db.scalars(select(Question).where(Question.id.in_(ids)))} if ids else {}
        out["data"] = {"title": d.get("title", ""), "settings": d.get("settings", {}), "practice_set_id": d.get("practice_set_id"),
                       "question_count": len(ids), "questions": [_question_view(qs[i], False) for i in ids if i in qs]}
    else:
        out["data"] = decorate(block.type, d)
    return out
