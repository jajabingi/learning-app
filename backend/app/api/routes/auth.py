"""Authentication: e-mail/password, Google sign-in (server-verified OIDC), password reset, e-mail verification,
provider linking and logout. Public registration / OAuth can only ever create STUDENT accounts."""
import logging
import secrets
import uuid
from datetime import timedelta

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select

from app.api.deps import DB, CurrentUser
from app.core.config import get_settings
from app.core.permissions import permissions_of
from app.core.security import (
    auth_limiter, create_access_token, create_refresh_token, hash_password, user_for_token, verify_password,
)
from app.models.base import utcnow
from app.models.user import User, UserIdentity
from app.schemas.auth import (
    ChangePasswordIn, CodeIn, EmailIn, LoginIn, RefreshIn, RegisterIn, ResetIn, TokenIn, TokenOut, UserOut, UserUpdate,
)
from app.services import audit, google, identity
from app.services.email import send_email

router = APIRouter(prefix="/auth", tags=["auth"])
log = logging.getLogger("recall.auth")
settings = get_settings()
OAUTH_COOKIE = "recall_oauth"

# Verified against when the email is unknown, so login time doesn't reveal whether an account exists.
_DUMMY_HASH = hash_password("dummy-password-for-timing")


def _tokens(user: User) -> TokenOut:
    return TokenOut(access_token=create_access_token(user.id, user.token_version), refresh_token=create_refresh_token(user.id, user.token_version))


def _me(db, user: User) -> UserOut:
    out = UserOut.model_validate(user)
    out.permissions = sorted(permissions_of(db, user))
    out.has_password = identity.has_password(user)
    out.providers = sorted({i.provider for i in identity.identities_of(db, user)})
    out.email_verified = user.email_verified_at is not None
    return out


def _send_verification(db, user: User) -> None:
    raw = identity.issue_token(db, "email_verify", user.id, timedelta(hours=settings.verify_token_hours))
    send_email(user.email, "Verify your Recall email", f"Welcome to Recall!\n\nConfirm your email address:\n{identity.web_url('/verify-email', token=raw)}\n")


@router.get("/config")
def public_config():
    """What the login screen needs to know (no secrets)."""
    return {"google_enabled": settings.google_enabled, "registration_enabled": settings.allow_registration,
            "email_verification_required": settings.require_email_verification}


# ---------------------------------------------------------------- e-mail + password
@router.post("/register", response_model=TokenOut, status_code=201, dependencies=[Depends(auth_limiter)])
def register(data: RegisterIn, db: DB):
    if not settings.allow_registration:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Registration is disabled")
    if identity.find_by_email(db, data.email):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")
    # Public registration can only ever create STUDENT accounts (the schema has no role field at all).
    user = identity.create_student(db, data.email, data.password, data.display_name)
    audit.log_event(db, "user_registered", actor=user, target=user, method="password")
    log.info("registered user %s", user.id)
    if settings.require_email_verification:
        identity.set_status(user, "pending_verification")
        _send_verification(db, user)
        db.commit()
        return JSONResponse({"verification_required": True}, status_code=202)
    return _tokens(user)


@router.post("/login", response_model=TokenOut, dependencies=[Depends(auth_limiter)])
def login(data: LoginIn, db: DB):
    user = identity.find_by_email(db, data.email)
    ok = verify_password(data.password, user.password_hash if user else _DUMMY_HASH)
    if not user or not ok:
        log.warning("failed login for %s", identity.normalize_email(data.email))
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    if user.status == "suspended":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account is suspended. Contact an administrator.")
    if user.status == "pending_verification":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Please verify your email address first. Check your inbox.")
    return _tokens(user)


@router.post("/refresh", response_model=TokenOut, dependencies=[Depends(auth_limiter)])
def refresh(data: RefreshIn, db: DB):
    return _tokens(user_for_token(db, data.refresh_token, "refresh"))  # revoked / suspended users cannot refresh


@router.post("/logout", status_code=204)
def logout(user: CurrentUser):
    """Server-side logout: all tokens issued to this account so far are revoked (this and other devices)."""
    identity.revoke_sessions(user)


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
def change_password(data: ChangePasswordIn, user: CurrentUser, db: DB):
    if identity.has_password(user) and not verify_password(data.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    user.password_hash = hash_password(data.new_password)
    identity.revoke_sessions(user)  # other devices must sign in again
    audit.log_event(db, "password_changed", actor=user, target=user)


# ---------------------------------------------------------------- password reset & e-mail verification
@router.post("/password/forgot", status_code=202, dependencies=[Depends(auth_limiter)])
def forgot_password(data: EmailIn, db: DB):
    """Always answers the same way, whether or not the address has an account."""
    user = identity.find_by_email(db, data.email)
    if user and user.status != "suspended":
        raw = identity.issue_token(db, "password_reset", user.id, timedelta(minutes=settings.reset_token_minutes))
        send_email(user.email, "Reset your Recall password",
                   f"Someone asked to reset the password of this account. If it was you, open:\n{identity.web_url('/reset-password', token=raw)}\n\n"
                   f"The link works once and expires in {settings.reset_token_minutes} minutes. If it was not you, ignore this email.\n")
        audit.log_event(db, "password_reset_requested", target=user)
    return {"detail": "If the address has an account, an email with instructions was sent."}


@router.post("/password/reset", status_code=204, dependencies=[Depends(auth_limiter)])
def reset_password(data: ResetIn, db: DB):
    t = identity.consume_token(db, data.token, "password_reset")
    user = db.get(User, t.user_id)
    if user is None or user.status == "suspended":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This link is invalid or has expired")
    user.password_hash = hash_password(data.new_password)
    if user.email_verified_at is None:
        user.email_verified_at = t.used_at  # the reset proves control of the mailbox
    if user.status == "pending_verification":
        identity.set_status(user, "active")
    identity.revoke_sessions(user)
    audit.log_event(db, "password_reset_completed", actor=user, target=user)


@router.post("/email/verify", response_model=TokenOut, dependencies=[Depends(auth_limiter)])
def verify_email(data: TokenIn, db: DB):
    t = identity.consume_token(db, data.token, "email_verify")
    user = db.get(User, t.user_id)
    if user is None or user.status == "suspended":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This link is invalid or has expired")
    user.email_verified_at = t.used_at
    if user.status == "pending_verification":
        identity.set_status(user, "active")
    audit.log_event(db, "email_verified", actor=user, target=user)
    return _tokens(user)


@router.post("/email/resend", status_code=202, dependencies=[Depends(auth_limiter)])
def resend_verification(data: EmailIn, db: DB):
    user = identity.find_by_email(db, data.email)
    if user and user.email_verified_at is None and user.status == "pending_verification":
        _send_verification(db, user)
    return {"detail": "If the address needs verification, a new email was sent."}


# ---------------------------------------------------------------- Google sign-in
def _cookie_token(data: dict) -> str:
    """Signed, short-lived OAuth session (state, nonce, PKCE verifier) kept in an httpOnly cookie."""
    return jwt.encode({**data, "type": "oauth_state", "exp": utcnow() + timedelta(minutes=10)}, settings.secret_key, algorithm="HS256")


def _start_google(purpose: str, uid: str | None) -> tuple[str, str]:
    if not settings.google_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Google sign-in is not configured")
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    verifier, challenge = google.new_pkce()
    cookie = _cookie_token({"state": state, "nonce": nonce, "verifier": verifier, "purpose": purpose, "uid": uid})
    return google.build_auth_url(state, nonce, challenge), cookie


def _set_cookie(resp: Response, value: str) -> None:
    resp.set_cookie(OAUTH_COOKIE, value, max_age=600, httponly=True, samesite="lax", secure=settings.is_production, path="/api/auth/google")


@router.get("/google/start", dependencies=[Depends(auth_limiter)])
def google_start():
    """Browser navigation target of the 'Continue with Google' button: redirects to Google."""
    url, cookie = _start_google("login", None)
    resp = RedirectResponse(url, status_code=302)
    _set_cookie(resp, cookie)
    return resp


@router.post("/google/link/start", dependencies=[Depends(auth_limiter)])
def google_link_start(user: CurrentUser):
    """A signed-in user attaches their Google account (the link is bound to THIS user in the signed state cookie)."""
    url, cookie = _start_google("link", str(user.id))
    resp = JSONResponse({"url": url})
    _set_cookie(resp, cookie)
    return resp


def _fail(code: str) -> RedirectResponse:
    resp = RedirectResponse(identity.web_url("/auth/callback", error=code), status_code=302)
    resp.delete_cookie(OAUTH_COOKIE, path="/api/auth/google")
    return resp


@router.get("/google/callback", dependencies=[Depends(auth_limiter)])
def google_callback(request: Request, db: DB, code: str = "", state: str = "", error: str = ""):
    raw = request.cookies.get(OAUTH_COOKIE)
    if error or not code or not state or not raw:
        return _fail("google_denied" if error else "google_failed")
    try:
        sess = jwt.decode(raw, settings.secret_key, algorithms=["HS256"])
        if sess.get("type") != "oauth_state" or not secrets.compare_digest(str(sess["state"]), state):  # CSRF check
            raise ValueError("state mismatch")
        claims = google.verify_id_token(google.exchange_code(code, sess["verifier"]), sess["nonce"])
    except (jwt.PyJWTError, ValueError, KeyError, google.GoogleError) as e:
        log.warning("google callback rejected: %s", e)
        return _fail("google_failed")
    sub, email = str(claims["sub"]), identity.normalize_email(claims["email"])
    ident = db.scalar(select(UserIdentity).where(UserIdentity.provider == "google", UserIdentity.provider_subject == sub))

    if sess.get("purpose") == "link":  # attach to the signed-in user recorded in the signed cookie
        target = db.get(User, uuid.UUID(sess["uid"])) if sess.get("uid") else None
        if target is None or target.status != "active":
            return _fail("google_failed")
        if ident is not None and ident.user_id != target.id:
            return _fail("google_in_use")
        if ident is None:
            db.add(UserIdentity(user_id=target.id, provider="google", provider_subject=sub, provider_email=email))
            audit.log_event(db, "identity_linked", actor=target, target=target, provider="google")
        db.commit()
        resp = RedirectResponse(identity.web_url("/auth/callback", linked="google"), status_code=302)
        resp.delete_cookie(OAUTH_COOKIE, path="/api/auth/google")
        return resp

    user = db.get(User, ident.user_id) if ident else None
    if user is None:
        existing = identity.find_by_email(db, email)
        if existing is not None:
            # Same address, but Google alone is not proof the person owns THIS account: require a confirmation link
            # sent to the account's own mailbox (or linking while signed in). Nothing is linked yet.
            tok = identity.issue_token(db, "link_google", existing.id, timedelta(hours=1), {"sub": sub, "email": email})
            send_email(existing.email, "Confirm linking Google to your Recall account",
                       f"Someone signed in with Google using this email address. To connect Google to your account, open:\n{identity.web_url('/auth/link', token=tok)}\n\n"
                       "If it was not you, ignore this email: nothing was changed.\n")
            audit.log_event(db, "identity_link_requested", target=existing, provider="google")
            db.commit()
            return _fail("account_exists")
        if not settings.allow_registration:
            return _fail("registration_disabled")
        user = identity.create_student(db, email, None, claims.get("name", ""), verified=True)  # always a student
        db.add(UserIdentity(user_id=user.id, provider="google", provider_subject=sub, provider_email=email))
        audit.log_event(db, "user_registered", actor=user, target=user, method="google")
    if user.status == "suspended":
        db.commit()
        return _fail("suspended")
    if user.status == "pending_verification":
        identity.set_status(user, "active")  # Google verified the address
    if user.email_verified_at is None and email == user.email:
        user.email_verified_at = utcnow()
    audit.log_event(db, "login_google", actor=user, target=user)
    one_time = identity.issue_token(db, "login_code", user.id, timedelta(seconds=120))
    db.commit()
    resp = RedirectResponse(identity.web_url("/auth/callback", code=one_time), status_code=302)
    resp.delete_cookie(OAUTH_COOKIE, path="/api/auth/google")
    return resp


@router.post("/google/exchange", response_model=TokenOut, dependencies=[Depends(auth_limiter)])
def google_exchange(data: CodeIn, db: DB):
    """The SPA trades the single-use code from the redirect for real tokens (no tokens ever travel in a URL)."""
    t = identity.consume_token(db, data.code, "login_code")
    user = db.get(User, t.user_id)
    if user is None or user.status != "active":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This link is invalid or has expired")
    return _tokens(user)


@router.post("/link/confirm", response_model=TokenOut, dependencies=[Depends(auth_limiter)])
def confirm_link(data: TokenIn, db: DB):
    """Opened from the e-mail sent to the existing account: proves mailbox control, then attaches the Google identity."""
    t = identity.consume_token(db, data.token, "link_google")
    user = db.get(User, t.user_id)
    if user is None or user.status != "active":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This link is invalid or has expired")
    sub = t.payload["sub"]
    other = db.scalar(select(UserIdentity).where(UserIdentity.provider == "google", UserIdentity.provider_subject == sub))
    if other is not None and other.user_id != user.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "This Google account is already linked to another user")
    if other is None:
        db.add(UserIdentity(user_id=user.id, provider="google", provider_subject=sub, provider_email=t.payload.get("email", "")))
    if user.email_verified_at is None:
        user.email_verified_at = t.used_at
    audit.log_event(db, "identity_linked", actor=user, target=user, provider="google", via="email_confirmation")
    return _tokens(user)


@router.get("/identities")
def list_identities(user: CurrentUser, db: DB):
    return {"has_password": identity.has_password(user), "identities": [
        {"id": str(i.id), "provider": i.provider, "email": i.provider_email} for i in identity.identities_of(db, user)]}


@router.delete("/identities/{identity_id}", status_code=204)
def unlink_identity(identity_id: str, user: CurrentUser, db: DB):
    try:
        ident = db.get(UserIdentity, uuid.UUID(identity_id))
    except ValueError:
        ident = None
    if ident is None or ident.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if not identity.has_password(user) and len(identity.identities_of(db, user)) <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "Set a password first: this is your only way to sign in")
    db.delete(ident)
    audit.log_event(db, "identity_unlinked", actor=user, target=user, provider=ident.provider)
