import re
import uuid
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.api.deps import DB, CurrentUser, check_owned_optional, owned
from app.core.config import get_settings
from app.models.base import utcnow
from app.models.knowledge import Chapter, Course, Subject, Topic
from app.models.note import Note, NoteLink
from app.models.question import Attachment, Question
from app.schemas.knowledge import TagOut
from app.schemas.question import NoteIn, NoteOut, NotePatch
from app.services import storage
from app.services.tags import resolve_tags

router = APIRouter(tags=["notes"])
settings = get_settings()
WIKI = re.compile(r"\[\[([^\[\]\n]{1,300})\]\]")


def _sync_links(db: Session, user, note: Note) -> None:
    db.execute(delete(NoteLink).where(NoteLink.source_note_id == note.id))
    titles = {m.strip().lower() for m in WIKI.findall(note.content or "")}
    if not titles:
        db.flush()
        return
    targets = db.scalars(select(Note).where(Note.user_id == user.id, Note.id != note.id))
    for t in targets:
        if t.title.strip().lower() in titles:
            db.add(NoteLink(user_id=user.id, source_note_id=note.id, target_note_id=t.id))
    db.flush()


def _out(db: Session, n: Note) -> NoteOut:
    links = db.execute(select(Note.id, Note.title).join(NoteLink, NoteLink.target_note_id == Note.id)
                       .where(NoteLink.source_note_id == n.id)).all()
    return NoteOut(
        id=n.id, title=n.title, content=n.content, kind=n.kind, subject_id=n.subject_id, course_id=n.course_id,
        chapter_id=n.chapter_id, topic_id=n.topic_id, question_id=n.question_id,
        tags=[TagOut.model_validate(t) for t in n.tags], created_at=n.created_at, updated_at=n.updated_at,
        links_to=[{"id": str(i), "title": t} for i, t in links],
    )


def _check_refs(db, user, d: dict):
    for key, model in (("subject_id", Subject), ("course_id", Course), ("chapter_id", Chapter),
                       ("topic_id", Topic), ("question_id", Question)):
        check_owned_optional(db, model, d.get(key), user)


@router.get("/notes")
def list_notes(db: DB, user: CurrentUser, q: str | None = None, subject_id: uuid.UUID | None = None,
               course_id: uuid.UUID | None = None, chapter_id: uuid.UUID | None = None,
               topic_id: uuid.UUID | None = None, question_id: uuid.UUID | None = None,
               kind: Literal["note", "definition", "formula"] | None = None, limit: int = 200):
    stmt = select(Note).where(Note.user_id == user.id)
    for col, val in ((Note.subject_id, subject_id), (Note.course_id, course_id), (Note.chapter_id, chapter_id),
                     (Note.topic_id, topic_id), (Note.question_id, question_id), (Note.kind, kind)):
        if val:
            stmt = stmt.where(col == val)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Note.title.ilike(like), Note.content.ilike(like)))
    notes = list(db.scalars(stmt.order_by(Note.updated_at.desc()).limit(min(limit, 500))))
    return [_out(db, n) for n in notes]


@router.post("/notes", response_model=NoteOut, status_code=201)
def create_note(data: NoteIn, db: DB, user: CurrentUser):
    d = data.model_dump(exclude={"tags"})
    _check_refs(db, user, d)
    n = Note(user_id=user.id, **d)
    n.tags = resolve_tags(db, user, data.tags)
    db.add(n)
    db.flush()
    _sync_links(db, user, n)
    return _out(db, n)


@router.get("/notes/{note_id}", response_model=NoteOut)
def get_note(note_id: uuid.UUID, db: DB, user: CurrentUser):
    return _out(db, owned(db, Note, note_id, user))


@router.patch("/notes/{note_id}", response_model=NoteOut)
def patch_note(note_id: uuid.UUID, data: NotePatch, db: DB, user: CurrentUser):
    n = owned(db, Note, note_id, user)
    fields = data.model_dump(exclude_unset=True, exclude={"tags", "set_links"})
    link_keys = {"subject_id", "course_id", "chapter_id", "topic_id", "question_id"}
    for k, v in fields.items():
        if k in link_keys:
            if data.set_links or v is not None:
                check_owned_optional(db, {"subject_id": Subject, "course_id": Course, "chapter_id": Chapter,
                                          "topic_id": Topic, "question_id": Question}[k], v, user)
                setattr(n, k, v)
        elif v is not None:
            setattr(n, k, v)
    if data.tags is not None:
        n.tags = resolve_tags(db, user, data.tags)
    n.updated_at = utcnow()
    db.flush()
    _sync_links(db, user, n)
    return _out(db, n)


@router.delete("/notes/{note_id}", status_code=204)
def delete_note(note_id: uuid.UUID, db: DB, user: CurrentUser):
    db.delete(owned(db, Note, note_id, user))


@router.get("/notes/{note_id}/backlinks")
def backlinks(note_id: uuid.UUID, db: DB, user: CurrentUser):
    n = owned(db, Note, note_id, user)
    rows = db.execute(select(Note.id, Note.title).join(NoteLink, NoteLink.source_note_id == Note.id)
                      .where(NoteLink.target_note_id == n.id)).all()
    return [{"id": str(i), "title": t} for i, t in rows]


# ---------- attachments (images / files for questions and notes) ----------
@router.post("/attachments", status_code=201)
async def upload(user: CurrentUser, db: DB, file: UploadFile = File(...), question_id: uuid.UUID | None = Form(None),
                 note_id: uuid.UUID | None = Form(None)):
    check_owned_optional(db, Question, question_id, user)
    check_owned_optional(db, Note, note_id, user)
    data = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"File exceeds {settings.max_upload_mb} MB")
    ctype, safe_name = storage.validate_upload(file.filename or "file", file.content_type, data)
    key = storage.save(user.id, data, safe_name)
    a = Attachment(user_id=user.id, question_id=question_id, note_id=note_id, filename=safe_name,
                   content_type=ctype, size_bytes=len(data), storage_key=key)
    db.add(a)
    db.flush()
    return {"id": str(a.id), "filename": a.filename, "content_type": a.content_type, "size_bytes": a.size_bytes,
            "url": f"/api/attachments/{a.id}/file"}


@router.get("/attachments/{att_id}/file")
def download(att_id: uuid.UUID, db: DB, user: CurrentUser):
    return attachment_response(owned(db, Attachment, att_id, user))


def attachment_response(a: Attachment) -> Response:
    data = storage.read(a.storage_key)
    inline = a.content_type.startswith("image/") and a.content_type != "image/svg+xml"
    headers = {
        "Content-Disposition": f'{"inline" if inline else "attachment"}; filename="{a.filename}"',
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "Cache-Control": "private, max-age=3600",
    }
    return Response(content=data, media_type=a.content_type if inline else "application/octet-stream", headers=headers)


@router.delete("/attachments/{att_id}", status_code=204)
def delete_attachment(att_id: uuid.UUID, db: DB, user: CurrentUser):
    a = owned(db, Attachment, att_id, user)
    storage.delete(a.storage_key)
    db.delete(a)
