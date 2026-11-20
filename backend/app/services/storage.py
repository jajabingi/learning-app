"""Local-disk attachment storage. Swap this module for S3/GCS without touching the routes."""
import re
import uuid
from pathlib import Path

from fastapi import HTTPException, status

from app.core.config import get_settings

settings = get_settings()
ALLOWED = {
    "image/png": (b"\x89PNG",), "image/jpeg": (b"\xff\xd8\xff",), "image/gif": (b"GIF8",),
    "image/webp": (b"RIFF",), "application/pdf": (b"%PDF",), "text/plain": None, "text/csv": None,
    "text/markdown": None, "application/json": None,
}
EXT_TYPE = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
            ".webp": "image/webp", ".pdf": "application/pdf", ".txt": "text/plain", ".csv": "text/csv",
            ".md": "text/markdown", ".json": "application/json"}


def _root() -> Path:
    p = Path(settings.upload_dir).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def validate_upload(filename: str, declared: str | None, data: bytes) -> tuple[str, str]:
    safe = re.sub(r"[^A-Za-z0-9._ -]", "_", Path(filename).name)[:200] or "file"
    ctype = EXT_TYPE.get(Path(safe).suffix.lower())
    if ctype is None or ctype not in ALLOWED:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Unsupported file type")
    magic = ALLOWED[ctype]
    if magic and not any(data.startswith(m) for m in magic):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "File content does not match its type")
    return ctype, safe


def save(user_id: uuid.UUID, data: bytes, filename: str) -> str:
    key = f"{user_id}/{uuid.uuid4().hex}{Path(filename).suffix.lower()}"
    path = _root() / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return key


def _path(key: str) -> Path:
    p = (_root() / key).resolve()
    if _root() not in p.parents:  # path-traversal guard
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Bad storage key")
    return p


def read(key: str) -> bytes:
    p = _path(key)
    if not p.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File missing")
    return p.read_bytes()


def delete(key: str) -> None:
    p = _path(key)
    if p.exists():
        p.unlink()


# ---------------- videos ----------------
VIDEO_TYPES = {".mp4": "video/mp4", ".m4v": "video/mp4", ".webm": "video/webm"}


def validate_video(filename: str, head: bytes) -> tuple[str, str]:
    safe = re.sub(r"[^A-Za-z0-9._ -]", "_", Path(filename).name)[:200] or "video"
    ctype = VIDEO_TYPES.get(Path(safe).suffix.lower())
    if ctype is None:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Unsupported video format. Upload MP4 (H.264) or WebM.")
    ok = head[4:8] == b"ftyp" if ctype == "video/mp4" else head.startswith(bytes([0x1A, 0x45, 0xDF, 0xA3]))
    if not ok:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "File content does not match its video type")
    return ctype, safe


def save_stream(user_id: uuid.UUID, fileobj, filename: str, max_bytes: int) -> tuple[str, int]:
    """Copy an upload to storage in chunks (never loads the whole video in memory)."""
    key = f"{user_id}/{uuid.uuid4().hex}{Path(filename).suffix.lower()}"
    path = _root() / key
    path.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    try:
        with open(path, "wb") as out:
            while chunk := fileobj.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"Video exceeds {max_bytes // (1024 * 1024)} MB")
                out.write(chunk)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return key, size


def file_path(key: str) -> Path:
    p = _path(key)
    if not p.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File missing")
    return p
