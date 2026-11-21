import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db

settings = get_settings()
bearer = HTTPBearer(auto_error=False)
ALGO = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode()[:72], hashed.encode())
    except ValueError:
        return False


def _make_token(user_id: uuid.UUID, kind: str, delta: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "type": kind, "iat": now, "exp": now + delta, "jti": uuid.uuid4().hex}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGO)


def create_access_token(user_id: uuid.UUID) -> str:
    return _make_token(user_id, "access", timedelta(minutes=settings.access_token_minutes))


def create_refresh_token(user_id: uuid.UUID) -> str:
    return _make_token(user_id, "refresh", timedelta(days=settings.refresh_token_days))


def create_media_token(attachment_id: uuid.UUID, minutes: int = 360) -> str:
    """Short-lived signed token that lets a <video> tag stream ONE attachment without an Authorization header.
    It is only ever handed out while serving a lesson the caller is already authorised to read."""
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": str(attachment_id), "type": "media", "iat": now, "exp": now + timedelta(minutes=minutes)},
                      settings.secret_key, algorithm=ALGO)


def decode_media_token(token: str) -> uuid.UUID:
    try:
        p = jwt.decode(token, settings.secret_key, algorithms=[ALGO])
        if p.get("type") != "media":
            raise ValueError
        return uuid.UUID(p["sub"])
    except (jwt.PyJWTError, ValueError, KeyError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired media link")


def decode_token(token: str, kind: str) -> uuid.UUID:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGO])
        if payload.get("type") != kind:
            raise ValueError("wrong token type")
        return uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, ValueError, KeyError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)
):
    from app.models.user import User

    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    user_id = decode_token(creds.credentials, "access")
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid user")
    return user


class RateLimiter:
    """Small in-process sliding-window limiter keyed by client IP (+ bucket name).

    Good for a single instance. Behind multiple workers/replicas swap for Redis.
    """

    def __init__(self, bucket: str, per_minute_getter):
        self.bucket = bucket
        self.get_limit = per_minute_getter
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def __call__(self, request: Request):
        limit = self.get_limit()
        if limit <= 0:
            return
        key = f"{self.bucket}:{request.client.host if request.client else 'unknown'}"
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= limit:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests, slow down")
        q.append(now)


auth_limiter = RateLimiter("auth", lambda: settings.rate_limit_auth_per_min)
ai_limiter = RateLimiter("ai", lambda: settings.rate_limit_ai_per_min)
public_limiter = RateLimiter("public", lambda: settings.rate_limit_public_per_min)
exam_limiter = RateLimiter("exam", lambda: settings.rate_limit_exam_per_min)
