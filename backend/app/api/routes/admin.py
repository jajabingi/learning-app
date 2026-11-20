"""Administrator-only: manage staff accounts, roles and permissions."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select

from app.api.deps import DB
from app.core.permissions import ALL_PERMISSIONS, DEFAULT_TEACHER_PERMISSIONS, permissions_of, require_admin, set_permissions
from app.core.security import hash_password
from app.models.user import User
from app.schemas.lms import AdminUserCreate, AdminUserPatch

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _out(db, u: User) -> dict:
    return {"id": str(u.id), "email": u.email, "display_name": u.display_name, "role": u.role, "is_active": u.is_active,
            "permissions": sorted(permissions_of(db, u)), "created_at": u.created_at.isoformat()}


@router.get("/permissions")
def list_permissions():
    return {"all": list(ALL_PERMISSIONS), "teacher_defaults": list(DEFAULT_TEACHER_PERMISSIONS)}


@router.get("/users")
def list_users(db: DB, role: str | None = None, q: str | None = None, limit: int = 200):
    stmt = select(User)
    if role:
        stmt = stmt.where(User.role == role)
    if q:
        stmt = stmt.where(User.email.ilike(f"%{q}%") | User.display_name.ilike(f"%{q}%"))
    return [_out(db, u) for u in db.scalars(stmt.order_by(User.created_at).limit(min(limit, 500)))]


@router.post("/users", status_code=201)
def create_user(data: AdminUserCreate, db: DB):
    email = data.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")
    u = User(email=email, password_hash=hash_password(data.password), display_name=data.display_name or email.split("@")[0],
             role=data.role)
    db.add(u)
    db.flush()
    if u.role == "teacher":
        set_permissions(db, u, data.permissions if data.permissions is not None else list(DEFAULT_TEACHER_PERMISSIONS))
    return _out(db, u)


@router.patch("/users/{user_id}")
def patch_user(user_id: uuid.UUID, data: AdminUserPatch, db: DB, admin: User = Depends(require_admin)):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    admins = db.scalar(select(func.count()).select_from(User).where(User.role == "admin", User.is_active.is_(True)))
    losing_admin = u.role == "admin" and ((data.role and data.role != "admin") or data.is_active is False)
    if losing_admin and admins <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "Cannot remove the last active administrator")
    if u.id == admin.id and (data.is_active is False or (data.role and data.role != "admin")):
        raise HTTPException(status.HTTP_409_CONFLICT, "You cannot demote or deactivate your own account")
    if data.role is not None:
        became_teacher = data.role == "teacher" and u.role != "teacher"
        u.role = data.role
        if became_teacher and data.permissions is None:
            set_permissions(db, u, list(DEFAULT_TEACHER_PERMISSIONS))
    if data.is_active is not None:
        u.is_active = data.is_active
    if data.display_name is not None:
        u.display_name = data.display_name
    if data.permissions is not None:
        set_permissions(db, u, data.permissions)
    db.flush()
    return _out(db, u)
