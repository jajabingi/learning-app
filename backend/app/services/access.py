"""Course access decisions for students. The single place that answers "may this student see this content?".

Rules (all must hold):
  1. the course is published (and the module / lesson being read are published),
  2. the student has an enrollment for that course whose status grants access (active/completed),
  3. the enrollment has started and has not expired.
Failures raise 404 (not 403) so that ids of courses/lessons the student cannot see cannot be probed.
"""
import uuid
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.base import as_utc, utcnow
from app.models.lms import ACCESS_STATUSES, LmsCourse, LmsEnrollment, LmsLesson, LmsModule
from app.models.user import User

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


def enrollment_grants_access(e: LmsEnrollment | None, now: datetime | None = None) -> bool:
    if e is None or e.status not in ACCESS_STATUSES:
        return False
    now = now or utcnow()
    if e.starts_at and as_utc(e.starts_at) > now:
        return False
    if e.expires_at and as_utc(e.expires_at) <= now:
        return False
    return True


def get_enrollment(db: Session, student: User, course_id: uuid.UUID) -> LmsEnrollment | None:
    return db.scalar(select(LmsEnrollment).where(LmsEnrollment.student_id == student.id,
                                                 LmsEnrollment.course_id == course_id))


def student_course(db: Session, student: User, course_id: uuid.UUID) -> tuple[LmsCourse, LmsEnrollment]:
    course = db.get(LmsCourse, course_id)
    enr = get_enrollment(db, student, course_id)
    if course is None or course.status != "published" or not enrollment_grants_access(enr):
        raise NOT_FOUND
    return course, enr


def student_lesson(db: Session, student: User, lesson_id: uuid.UUID) -> tuple[LmsCourse, LmsModule, LmsLesson]:
    lesson = db.get(LmsLesson, lesson_id)
    if lesson is None:
        raise NOT_FOUND
    course, _ = student_course(db, student, lesson.course_id)  # enrollment is checked against the lesson's own course
    module = db.get(LmsModule, lesson.module_id)
    if module is None or not module.is_published or not lesson.is_published:
        raise NOT_FOUND
    return course, module, lesson


def student_enrolled_courses(db: Session, student: User) -> list[tuple[LmsCourse, LmsEnrollment]]:
    now = utcnow()
    rows = db.execute(
        select(LmsCourse, LmsEnrollment).join(LmsEnrollment, LmsEnrollment.course_id == LmsCourse.id)
        .where(LmsEnrollment.student_id == student.id, LmsCourse.status == "published")
        .order_by(LmsCourse.title)
    ).all()
    return [(c, e) for c, e in rows if enrollment_grants_access(e, now)]
