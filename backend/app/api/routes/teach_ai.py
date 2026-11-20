"""Teacher AI studio: turn a prompt into a DRAFT module or DRAFT questions. Nothing is saved by generation; the teacher
reviews the draft and explicitly imports it. Keys stay on the server (see services/ai/provider.py)."""
import logging
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import DB
from app.core.permissions import P_COURSES_MANAGE, require_permission
from app.core.security import ai_limiter
from app.models.lms import LmsBlock, LmsCourse, LmsLesson, LmsModule
from app.models.user import User
from app.services import lms
from app.services.ai import service as ai
from app.services.ai.provider import AIError, get_provider
from app.services.lms_blocks import clean_block

router = APIRouter(prefix="/teach/ai", tags=["teacher-ai"], dependencies=[Depends(require_permission(P_COURSES_MANAGE))])
Teacher = Depends(require_permission(P_COURSES_MANAGE))
log = logging.getLogger("recall.ai")
Lang = Literal["he", "en"]


def _wrap(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except AIError as e:
        raise HTTPException(e.status_code, e.message)


@router.get("/status")
def status():
    p = get_provider()
    return {"enabled": p is not None, "provider": p.name if p else None, "model": p.model if p else None}


class ModulePrompt(BaseModel):
    prompt: str = Field(min_length=10, max_length=20000)
    lessons: int = Field(default=4, ge=1, le=10)
    language: Lang = "he"


@router.post("/module-draft", dependencies=[Depends(ai_limiter)])
def module_draft(data: ModulePrompt, user: User = Teacher):
    return {"draft": _wrap(ai.generate_module_draft, prompt=data.prompt, language=data.language, lessons=data.lessons)}


class ImportDraft(BaseModel):
    draft: dict


@router.post("/courses/{course_id}/import-module", status_code=201)
def import_module(course_id: uuid.UUID, data: ImportDraft, db: DB, user: User = Teacher):
    """Saves a reviewed draft as a new UNPUBLISHED module. Every block is validated like a hand-made one; invalid
    blocks are skipped and counted."""
    c = lms.own_course(db, user, course_id)
    try:
        d = ai.DraftModule.model_validate(data.draft)
    except Exception:
        raise HTTPException(422, "The draft is not valid")
    m = LmsModule(course_id=c.id, title=d.title, summary=d.summary, is_published=False,
                  position=lms.next_position(db, LmsModule, LmsModule.course_id == c.id))
    db.add(m)
    db.flush()
    skipped = lessons = blocks = 0
    for li, dl in enumerate(d.lessons):
        les = LmsLesson(course_id=c.id, module_id=m.id, title=dl.title, summary=dl.summary, position=li,
                        estimated_minutes=dl.estimated_minutes, is_published=False)
        db.add(les)
        db.flush()
        lessons += 1
        pos = 0
        for b in dl.blocks:
            if b.type not in ai.GEN_BLOCK_TYPES:
                skipped += 1
                continue
            try:
                cleaned = clean_block(db, c.owner_id, b.type, b.data)
            except HTTPException:
                skipped += 1
                continue
            db.add(LmsBlock(lesson_id=les.id, type=b.type, position=pos, data=cleaned, is_visible=True))
            pos += 1
            blocks += 1
    lms.touch(c)
    return {"module_id": str(m.id), "lessons": lessons, "blocks": blocks, "skipped_blocks": skipped}


class QuestionPrompt(BaseModel):
    prompt: str = Field(min_length=10, max_length=20000)
    count: int = Field(default=5, ge=1, le=20)
    language: Lang = "he"
    steps: bool = True
    level: Literal["basic", "intermediate", "advanced", "mixed"] = "mixed"
    types: list[str] = Field(default=[], max_length=11)


@router.post("/question-drafts", dependencies=[Depends(ai_limiter)])
def question_drafts(data: QuestionPrompt, user: User = Teacher):
    """Draft questions (with step-by-step solutions). Save the ones you keep with POST /questions/batch, then add them
    to a practice set."""
    qs = _wrap(ai.generate_questions, material=data.prompt, count=data.count, level=data.level, types=data.types,
               language=data.language, steps=data.steps)
    return {"questions": qs}
