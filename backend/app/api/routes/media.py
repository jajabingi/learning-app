"""Video upload (teacher) and range-capable playback (signed URL). Storage goes through services/storage.py so the
local-disk backend can be swapped for S3 / a video host without touching these routes."""
import uuid
from collections.abc import Iterator

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import StreamingResponse

from app.api.deps import DB
from app.core.config import get_settings
from app.core.permissions import P_COURSES_MANAGE, require_permission
from app.core.security import decode_media_token
from app.models.question import Attachment
from app.models.user import User
from app.services import storage

settings = get_settings()
router = APIRouter(tags=["media"])
CHUNK = 1024 * 1024


@router.post("/teach/videos", status_code=201)
def upload_video(db: DB, user: User = Depends(require_permission(P_COURSES_MANAGE)), file: UploadFile = File(...)):
    head = file.file.read(16)
    file.file.seek(0)
    ctype, name = storage.validate_video(file.filename or "video.mp4", head)
    key, size = storage.save_stream(user.id, file.file, name, settings.max_video_mb * 1024 * 1024)
    a = Attachment(user_id=user.id, filename=name, content_type=ctype, size_bytes=size, storage_key=key)
    db.add(a)
    db.flush()
    return {"id": str(a.id), "filename": a.filename, "content_type": ctype, "size_bytes": size}


def _iter(path, start: int, end: int) -> Iterator[bytes]:
    with open(path, "rb") as f:
        f.seek(start)
        left = end - start + 1
        while left > 0:
            chunk = f.read(min(CHUNK, left))
            if not chunk:
                break
            left -= len(chunk)
            yield chunk


@router.get("/media/video/{attachment_id}")
def stream_video(attachment_id: uuid.UUID, request: Request, db: DB, t: str = ""):
    """Authorised by a signed token (issued only while serving a lesson the caller may read), because <video> tags
    cannot send an Authorization header. The token is bound to this single attachment and expires."""
    if decode_media_token(t) != attachment_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired media link")
    a = db.get(Attachment, attachment_id)
    if a is None or not a.content_type.startswith("video/"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    path = storage.file_path(a.storage_key)
    size = path.stat().st_size
    start, end, code = 0, size - 1, 200
    rng = request.headers.get("range")
    if rng and rng.startswith("bytes="):
        try:
            s, _, e = rng[6:].split(",")[0].partition("-")
            if s == "":  # suffix range: last N bytes
                start = max(0, size - int(e))
            else:
                start = int(s)
                end = min(int(e), size - 1) if e else size - 1
            if start > end or start >= size:
                raise ValueError
            code = 206
        except ValueError:
            raise HTTPException(status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE, "Bad range",
                                headers={"Content-Range": f"bytes */{size}"})
    headers = {"Accept-Ranges": "bytes", "Content-Length": str(end - start + 1), "Cache-Control": "private, max-age=3600",
               "X-Content-Type-Options": "nosniff", "Content-Disposition": "inline"}
    if code == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(_iter(path, start, end), status_code=code, media_type=a.content_type, headers=headers)
