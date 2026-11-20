"""Roles and permissions. All authorization decisions go through this module."""
import uuid

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import get_current_user
from app.models.user import STAFF_ROLES, User, UserPermission

P_COURSES_MANAGE = "courses.manage"
P_COURSES_PUBLISH = "courses.publish"
P_STUDENTS_MANAGE = "students.manage"
P_ENROLLMENTS_MANAGE = "enrollments.manage"
P_PAYMENTS_MANAGE = "payments.manage"
P_FINANCE_VIEW = "finance.view"
P_ANNOUNCEMENTS_MANAGE = "announcements.manage"

ALL_PERMISSIONS = (P_COURSES_MANAGE, P_COURSES_PUBLISH, P_STUDENTS_MANAGE, P_ENROLLMENTS_MANAGE,
                   P_PAYMENTS_MANAGE, P_FINANCE_VIEW, P_ANNOUNCEMENTS_MANAGE)
DEFAULT_TEACHER_PERMISSIONS = ALL_PERMISSIONS


def is_staff(user: User) -> bool:
    return user.role in STAFF_ROLES


def permissions_of(db: Session, user: User) -> set[str]:
    if user.role == "admin":
        return set(ALL_PERMISSIONS)
    if user.role != "teacher":
        return set()
    return set(db.scalars(select(UserPermission.permission).where(UserPermission.user_id == user.id)))


def set_permissions(db: Session, user: User, perms: list[str]) -> None:
    unknown = set(perms) - set(ALL_PERMISSIONS)
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown permission: {sorted(unknown)[0]}")
    db.query(UserPermission).filter(UserPermission.user_id == user.id).delete()
    for p in dict.fromkeys(perms):
        db.add(UserPermission(user_id=user.id, permission=p))
    db.flush()


def require_staff(user: User = Depends(get_current_user)) -> User:
    """Teacher workspace gate: ADMIN or TEACHER only."""
    if not is_staff(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Teacher access required")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator access required")
    return user


def require_student(user: User = Depends(get_current_user)) -> User:
    if user.role != "student":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Student account required")
    return user


def require_permission(permission: str):
    def dep(user: User = Depends(require_staff), db: Session = Depends(get_db)) -> User:
        if permission not in permissions_of(db, user):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing permission: {permission}")
        return user

    return dep


def new_user_id() -> uuid.UUID:
    return uuid.uuid4()
