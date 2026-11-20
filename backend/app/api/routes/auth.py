import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.deps import DB, CurrentUser
from app.core.config import get_settings
from app.core.permissions import permissions_of
from app.core.security import (
    auth_limiter, create_access_token, create_refresh_token, decode_token, hash_password, verify_password,
)
from app.models.user import User
from app.schemas.auth import (
    ChangePasswordIn, LoginIn, RefreshIn, RegisterIn, TokenOut, UserOut, UserUpdate,
)

router = APIRouter(prefix="/auth", tags=["auth"])
log = logging.getLogger("recall.auth")
settings = get_settings()

# Verified against when the email is unknown, so login time doesn't reveal whether an account exists.
_DUMMY_HASH = hash_password("dummy-password-for-timing")


def _tokens(user: User) -> TokenOut:
    return TokenOut(access_token=create_access_token(user.id), refresh_token=create_refresh_token(user.id))


@router.post("/register", response_model=TokenOut, status_code=201, dependencies=[Depends(auth_limiter)])
def register(data: RegisterIn, db: DB):
    if not settings.allow_registration:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Registration is disabled")
    email = data.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")
    # Public registration can only ever create STUDENT accounts. Staff are created by an admin / the CLI.
    user = User(email=email, password_hash=hash_password(data.password), role="student",
                display_name=data.display_name or email.split("@")[0])
    db.add(user)
    db.flush()
    log.info("registered user %s", user.id)
    return _tokens(user)


@router.post("/login", response_model=TokenOut, dependencies=[Depends(auth_limiter)])
def login(data: LoginIn, db: DB):
    user = db.scalar(select(User).where(User.email == data.email.lower()))
    ok = verify_password(data.password, user.password_hash if user else _DUMMY_HASH)
    if not user or not ok or not user.is_active:
        log.warning("failed login for %s", data.email.lower())
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    return _tokens(user)


@router.post("/refresh", response_model=TokenOut, dependencies=[Depends(auth_limiter)])
def refresh(data: RefreshIn, db: DB):
    user = db.get(User, decode_token(data.refresh_token, "refresh"))
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid user")
    return _tokens(user)


def _me(db, user: User) -> UserOut:
    out = UserOut.model_validate(user)
    out.permissions = sorted(permissions_of(db, user))
    return out


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser, db: DB):
    return _me(db, user)


@router.patch("/me", response_model=UserOut)
def update_me(data: UserUpdate, user: CurrentUser, db: DB):
    for k, v in data.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(user, k, v)
    return _me(db, user)


@router.post("/change-password", status_code=204)
def change_password(data: ChangePasswordIn, user: CurrentUser):
    if not verify_password(data.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    user.password_hash = hash_password(data.new_password)
