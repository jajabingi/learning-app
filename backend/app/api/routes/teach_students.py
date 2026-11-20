"""Teacher workspace: students and enrollments.

Privacy: a teacher sees only students enrolled in one of THEIR courses (admins see everyone). Finding a student to
enrol is done by exact email, and returns only id / name / email."""
import uuid
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import DB
from app.core.permissions import P_ENROLLMENTS_MANAGE, P_STUDENTS_MANAGE, require_permission
from app.models.base import as_utc, utcnow
from app.models.lms import ENROLLMENT_STATUSES, LmsCourse, LmsEnrollment, LmsLesson, LmsLessonProgress
from app.models.user import User
from app.services import lms, progress

router = APIRouter(prefix="/teach", tags=["teacher-students"])
StudentsMgr = Depends(require_permission(P_STUDENTS_MANAGE))
EnrollMgr = Depends(require_permission(P_ENROLLMENTS_MANAGE))


def _my_course_ids(db, user: User):
    q = select(LmsCourse.id)
    if user.role != "admin":
        q = q.where(LmsCourse.owner_id == user.id)
    return q


def _enrollment_out(db, e: LmsEnrollment, course: LmsCourse, with_progress=True) -> dict:
    d = {"id": str(e.id), "student_id": str(e.student_id), "course_id": str(e.course_id), "course_title": course.title,
         "status": e.status, "source": e.source, "notes": e.notes,
         "starts_at": as_utc(e.starts_at).isoformat() if e.starts_at else None,
         "expires_at": as_utc(e.expires_at).isoformat() if e.expires_at else None,
         "completed_at": as_utc(e.completed_at).isoformat() if e.completed_at else None,
         "created_at": e.created_at.isoformat()}
    if with_progress:
        p = progress.course_progress(db, e.student_id, course)
        d["progress"] = {k: p[k] for k in ("percent", "completed_lessons", "total_lessons", "time_spent_seconds", "last_activity_at")}
    return d


def _owned_enrollment(db, user: User, enrollment_id: uuid.UUID) -> tuple[LmsEnrollment, LmsCourse]:
    e = db.get(LmsEnrollment, enrollment_id)
    if e is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Enrollment not found")
    course = lms.own_course(db, user, e.course_id)  # 404 unless it is the teacher's course
    return e, course


@router.get("/students")
def list_students(db: DB, user: User = StudentsMgr, q: str | None = None, course_id: uuid.UUID | None = None):
    if course_id:
        lms.own_course(db, user, course_id)
    mine = select(LmsEnrollment.student_id).where(LmsEnrollment.course_id.in_([course_id] if course_id else _my_course_ids(db, user)))
    stmt = select(User).where(User.role == "student", User.id.in_(mine))
    if q:
        stmt = stmt.where(User.email.ilike(f"%{q}%") | User.display_name.ilike(f"%{q}%"))
    students = list(db.scalars(stmt.order_by(User.display_name).limit(500)))
    out = []
    for s in students:
        enr = list(db.scalars(select(LmsEnrollment).where(LmsEnrollment.student_id == s.id, LmsEnrollment.course_id.in_(_my_course_ids(db, user)))))
        last = db.scalar(select(func.max(LmsLessonProgress.last_opened_at)).where(
            LmsLessonProgress.student_id == s.id, LmsLessonProgress.course_id.in_(_my_course_ids(db, user))))
        out.append({"id": str(s.id), "email": s.email, "display_name": s.display_name, "is_active": s.is_active,
                    "enrollments": len(enr), "active_enrollments": sum(1 for e in enr if e.status in ("active", "completed")),
                    "last_activity_at": as_utc(last).isoformat() if last else None, "joined_at": s.created_at.isoformat()})
    return out


@router.get("/students/lookup")
def lookup_student(email: str, db: DB, user: User = EnrollMgr):
    s = db.scalar(select(User).where(User.email == email.strip().lower(), User.role == "student", User.is_active.is_(True)))
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No student account with that email. Ask the student to register first.")
    return {"id": str(s.id), "email": s.email, "display_name": s.display_name}


@router.get("/students/{student_id}")
def student_profile(student_id: uuid.UUID, db: DB, user: User = StudentsMgr):
    s = db.get(User, student_id)
    enrollments = list(db.execute(
        select(LmsEnrollment, LmsCourse).join(LmsCourse, LmsCourse.id == LmsEnrollment.course_id)
        .where(LmsEnrollment.student_id == student_id, LmsEnrollment.course_id.in_(_my_course_ids(db, user)))
        .order_by(LmsEnrollment.created_at.desc())).all())
    if s is None or s.role != "student" or not enrollments:  # not one of this teacher's students → indistinguishable from missing
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")
    my_courses = {c.id for _e, c in enrollments}
    recent = db.execute(
        select(LmsLessonProgress, LmsLesson.title).join(LmsLesson, LmsLesson.id == LmsLessonProgress.lesson_id)
        .where(LmsLessonProgress.student_id == student_id, LmsLessonProgress.course_id.in_(my_courses),
               LmsLessonProgress.last_opened_at.is_not(None))
        .order_by(LmsLessonProgress.last_opened_at.desc()).limit(15)).all()
    return {
        "id": str(s.id), "email": s.email, "display_name": s.display_name, "is_active": s.is_active, "joined_at": s.created_at.isoformat(),
        "enrollments": [_enrollment_out(db, e, c) for e, c in enrollments],
        "activity": [{"lesson_id": str(p.lesson_id), "lesson_title": t, "course_id": str(p.course_id),
                      "last_opened_at": as_utc(p.last_opened_at).isoformat(), "time_spent_seconds": p.time_spent_seconds,
                      "completed": p.completed_at is not None} for p, t in recent],
    }


@router.get("/courses/{course_id}/enrollments")
def course_enrollments(course_id: uuid.UUID, db: DB, user: User = StudentsMgr):
    course = lms.own_course(db, user, course_id)
    rows = db.execute(select(LmsEnrollment, User).join(User, User.id == LmsEnrollment.student_id)
                      .where(LmsEnrollment.course_id == course.id).order_by(User.display_name)).all()
    return [{**_enrollment_out(db, e, course), "student": {"id": str(u.id), "email": u.email, "display_name": u.display_name}} for e, u in rows]


class EnrollIn(BaseModel):
    student_id: uuid.UUID
    course_id: uuid.UUID
    source: Literal["manual", "free"] = "manual"
    starts_at: datetime | None = None
    expires_at: datetime | None = None
    notes: str = Field(default="", max_length=2000)


@router.post("/enrollments", status_code=201)
def enroll(data: EnrollIn, db: DB, user: User = EnrollMgr):
    """Manually grant access (or re-grant, which updates the existing enrollment — one per student and course)."""
    course = lms.own_course(db, user, data.course_id)
    student = db.get(User, data.student_id)
    if student is None or student.role != "student" or not student.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")
    now = utcnow()
    expires = data.expires_at or (now + timedelta(days=course.access_days) if course.access_days else None)
    if expires and expires <= now:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The expiry date must be in the future")
    e = db.scalar(select(LmsEnrollment).where(LmsEnrollment.student_id == student.id, LmsEnrollment.course_id == course.id))
    if e is None:
        e = LmsEnrollment(student_id=student.id, course_id=course.id)
        db.add(e)
    e.status, e.source, e.granted_by, e.notes = "active", data.source, user.id, data.notes
    e.starts_at, e.expires_at = data.starts_at or now, expires
    db.flush()
    progress.sync_completion(db, e, course)
    return _enrollment_out(db, e, course)


class EnrollmentPatch(BaseModel):
    status: Literal["pending", "active", "suspended", "completed", "expired", "cancelled"] | None = None
    expires_at: datetime | None = None
    clear_expiry: bool = False
    notes: str | None = Field(default=None, max_length=2000)


@router.patch("/enrollments/{enrollment_id}")
def update_enrollment(enrollment_id: uuid.UUID, data: EnrollmentPatch, db: DB, user: User = EnrollMgr):
    """Suspend / revoke / reactivate / extend access. Takes effect on the student's very next request."""
    e, course = _owned_enrollment(db, user, enrollment_id)
    if data.status is not None:
        assert data.status in ENROLLMENT_STATUSES
        if data.status == "active" and e.status in ("pending", "expired", "cancelled") and e.expires_at is None and course.access_days and not data.clear_expiry:
            e.expires_at = utcnow() + timedelta(days=course.access_days)   # a (re)granted access starts its duration now
        if data.status == "active" and e.starts_at is None:
            e.starts_at = utcnow()
        e.status = data.status
        if data.status != "completed":
            e.completed_at = None
    if data.clear_expiry:
        e.expires_at = None
    elif data.expires_at is not None:
        e.expires_at = data.expires_at
    if data.notes is not None:
        e.notes = data.notes
    if data.status in ("active", "completed"):
        progress.sync_completion(db, e, course)
    db.flush()
    return _enrollment_out(db, e, course)
