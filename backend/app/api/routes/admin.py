"""Administrator-only: user directory, roles, account status, permissions and the audit trail.
Every change is enforced here on the server and recorded in the audit log."""
import uuid
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select

from app.api.deps import DB
from app.core.config import get_settings
from app.core.permissions import ALL_PERMISSIONS, DEFAULT_TEACHER_PERMISSIONS, permissions_of, require_admin, set_permissions
from app.core.security import hash_password
from app.models.lms import LmsCourse, LmsEnrollment, LmsLessonProgress
from app.models.user import AuditLog, User
from app.schemas.lms import AdminUserCreate, AdminUserPatch
from app.services import audit, identity
from app.services.email import send_email

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _out(db, u: User) -> dict:
    return {"id": str(u.id), "email": u.email, "display_name": u.display_name, "role": u.role, "is_active": u.is_active,
            "status": u.status, "permissions": sorted(permissions_of(db, u)), "created_at": u.created_at.isoformat(),
            "email_verified": u.email_verified_at is not None}


def _get(db, user_id: uuid.UUID) -> User:
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return u


def _active_admins(db) -> int:
    return db.scalar(select(func.count()).select_from(User).where(User.role == "admin", User.status == "active")) or 0


@router.get("/permissions")
def list_permissions():
    return {"all": list(ALL_PERMISSIONS), "teacher_defaults": list(DEFAULT_TEACHER_PERMISSIONS)}


@router.get("/users")
def list_users(db: DB, role: str | None = None, q: str | None = None, limit: int = 200):
    """Simple list (used by the team/permissions screen). See /admin/users/directory for search + pagination."""
    stmt = select(User)
    if role:
        stmt = stmt.where(User.role == role)
    if q:
        stmt = stmt.where(User.email.ilike(f"%{q}%") | User.display_name.ilike(f"%{q}%"))
    return [_out(db, u) for u in db.scalars(stmt.order_by(User.created_at).limit(min(limit, 500)))]


SORTS = {"created": User.created_at, "name": User.display_name, "email": User.email, "role": User.role, "status": User.status}


@router.get("/users/directory")
def user_directory(db: DB, q: str | None = None, role: Literal["student", "teacher", "admin"] | None = None,
                   status_: Literal["active", "suspended", "pending_verification"] | None = Query(default=None, alias="status"),
                   sort: Literal["created", "name", "email", "role", "status"] = "created", order: Literal["asc", "desc"] = "desc",
                   page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100)):
    stmt = select(User)
    if role:
        stmt = stmt.where(User.role == role)
    if status_:
        stmt = stmt.where(User.status == status_)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.email.ilike(like), User.display_name.ilike(like)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    col = SORTS[sort]
    rows = list(db.scalars(stmt.order_by(col.desc() if order == "desc" else col.asc(), User.id).offset((page - 1) * page_size).limit(page_size)))
    ids = [u.id for u in rows]
    enrolled = dict(db.execute(select(LmsEnrollment.student_id, func.count()).where(LmsEnrollment.student_id.in_(ids)).group_by(LmsEnrollment.student_id)).all()) if ids else {}
    items = []
    for u in rows:
        items.append({**_out(db, u), "providers": sorted({i.provider for i in identity.identities_of(db, u)}) + (["password"] if identity.has_password(u) else []),
                      "enrolled_courses": enrolled.get(u.id, 0)})
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/users/summary")
def user_summary(db: DB):
    by_role = dict(db.execute(select(User.role, func.count()).group_by(User.role)).all())
    by_status = dict(db.execute(select(User.status, func.count()).group_by(User.status)).all())
    recent = db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(10))
    return {"by_role": by_role, "by_status": by_status, "total": sum(by_role.values()), "recent": [_audit_out(db, a) for a in recent]}


@router.get("/users/{user_id}")
def user_detail(user_id: uuid.UUID, db: DB):
    u = _get(db, user_id)
    enr = db.execute(select(LmsEnrollment, LmsCourse).join(LmsCourse, LmsCourse.id == LmsEnrollment.course_id)
                     .where(LmsEnrollment.student_id == u.id).order_by(LmsEnrollment.created_at.desc())).all()
    owned = db.scalar(select(func.count()).select_from(LmsCourse).where(LmsCourse.owner_id == u.id)) or 0
    last = db.scalar(select(func.max(LmsLessonProgress.last_opened_at)).where(LmsLessonProgress.student_id == u.id))
    events = db.scalars(select(AuditLog).where((AuditLog.target_user_id == u.id) | (AuditLog.actor_id == u.id)).order_by(AuditLog.created_at.desc()).limit(50))
    return {**_out(db, u), "providers": sorted({i.provider for i in identity.identities_of(db, u)}) + (["password"] if identity.has_password(u) else []),
            "enrollments": [{"course_id": str(c.id), "course_title": c.title, "status": e.status, "source": e.source} for e, c in enr],
            "owned_courses": owned, "last_learning_activity": last.isoformat() if last else None, "activity": [_audit_out(db, a) for a in events]}


def _audit_out(db, a: AuditLog) -> dict:
    actor = db.get(User, a.actor_id) if a.actor_id else None
    target = db.get(User, a.target_user_id) if a.target_user_id else None
    return {"id": str(a.id), "action": a.action, "actor": actor.email if actor else None, "target": target.email if target else None,
            "target_id": str(a.target_user_id) if a.target_user_id else None, "details": a.details, "created_at": a.created_at.isoformat()}


@router.get("/audit")
def audit_log(db: DB, action: str | None = None, target_user_id: uuid.UUID | None = None, page: int = Query(default=1, ge=1), page_size: int = Query(default=30, ge=1, le=100)):
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if target_user_id:
        stmt = stmt.where(AuditLog.target_user_id == target_user_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(AuditLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size))
    return {"items": [_audit_out(db, a) for a in rows], "total": total, "page": page, "page_size": page_size}


@router.post("/users", status_code=201)
def create_user(data: AdminUserCreate, db: DB, admin: User = Depends(require_admin)):
    email = identity.normalize_email(data.email)
    if identity.find_by_email(db, email):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")
    u = User(email=email, password_hash=hash_password(data.password), display_name=data.display_name or email.split("@")[0],
             role=data.role, status="active", is_active=True)
    db.add(u)
    db.flush()
    if u.role == "teacher":
        set_permissions(db, u, data.permissions if data.permissions is not None else list(DEFAULT_TEACHER_PERMISSIONS))
    audit.log_event(db, "user_created", actor=admin, target=u, role=u.role)
    return _out(db, u)


@router.patch("/users/{user_id}")
def patch_user(user_id: uuid.UUID, data: AdminUserPatch, db: DB, admin: User = Depends(require_admin)):
    u = _get(db, user_id)
    new_status = data.status
    if data.is_active is not None and new_status is None:  # legacy flag
        new_status = "active" if data.is_active else "suspended"
    losing_admin = u.role == "admin" and ((data.role and data.role != "admin") or new_status == "suspended")
    if losing_admin and _active_admins(db) <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "Cannot remove the last active administrator")
    if u.id == admin.id and (new_status == "suspended" or (data.role and data.role != "admin")):
        raise HTTPException(status.HTTP_409_CONFLICT, "You cannot demote or deactivate your own account")
    if data.role is not None and data.role != u.role:
        old = u.role
        became_teacher = data.role == "teacher"
        u.role = data.role
        identity.revoke_sessions(u)  # the user's old tokens carried the previous role's expectations: sign in again
        audit.log_event(db, "role_changed", actor=admin, target=u, from_role=old, to_role=data.role)
        if became_teacher and data.permissions is None:
            set_permissions(db, u, list(DEFAULT_TEACHER_PERMISSIONS))
    if new_status is not None and new_status != u.status:
        old = u.status
        identity.set_status(u, new_status)  # suspending also revokes every session
        audit.log_event(db, "user_suspended" if new_status == "suspended" else "user_reactivated", actor=admin, target=u, from_status=old, to_status=new_status)
    if data.display_name is not None and data.display_name != u.display_name:
        audit.log_event(db, "profile_edited", actor=admin, target=u, field="display_name")
        u.display_name = data.display_name
    if data.permissions is not None:
        set_permissions(db, u, data.permissions)
        audit.log_event(db, "permissions_changed", actor=admin, target=u, permissions=sorted(data.permissions))
    db.flush()
    return _out(db, u)


@router.post("/users/{user_id}/send-reset", status_code=202)
def send_reset(user_id: uuid.UUID, db: DB, admin: User = Depends(require_admin)):
    """E-mail the user a password-reset link (the admin never sees or sets their password)."""
    u = _get(db, user_id)
    if u.status == "suspended":
        raise HTTPException(status.HTTP_409_CONFLICT, "The account is suspended")
    settings = get_settings()
    raw = identity.issue_token(db, "password_reset", u.id, timedelta(minutes=settings.reset_token_minutes))
    link = identity.web_url("/reset-password", token=raw)
    body = "An administrator sent you a link to choose a new password:" + chr(10) + link + chr(10) + chr(10) + f"It works once and expires in {settings.reset_token_minutes} minutes." + chr(10)
    send_email(u.email, "Reset your Recall password", body)
    audit.log_event(db, "password_reset_requested", actor=admin, target=u, by="admin")
    return {"detail": "Reset email sent"}
