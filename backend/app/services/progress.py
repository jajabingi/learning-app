"""Student progress. Progress is only ever derived from what the student explicitly completed and time actually
spent — opening a lesson never completes it, and a course is completed only when its completion rule is met."""
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.base import as_utc, utcnow
from app.models.lms import LmsCourse, LmsEnrollment, LmsLesson, LmsLessonProgress, LmsModule


def visible_lessons(db: Session, course_id: uuid.UUID) -> list[LmsLesson]:
    """Published lessons of published modules, in curriculum order (what a student can actually take)."""
    return list(db.scalars(
        select(LmsLesson).join(LmsModule, LmsModule.id == LmsLesson.module_id)
        .where(LmsLesson.course_id == course_id, LmsLesson.is_published.is_(True), LmsModule.is_published.is_(True))
        .order_by(LmsModule.position, LmsLesson.position)))


def progress_rows(db: Session, student_id: uuid.UUID, course_id: uuid.UUID) -> dict[uuid.UUID, LmsLessonProgress]:
    return {p.lesson_id: p for p in db.scalars(select(LmsLessonProgress).where(
        LmsLessonProgress.student_id == student_id, LmsLessonProgress.course_id == course_id))}


def course_progress(db: Session, student_id: uuid.UUID, course: LmsCourse) -> dict:
    lessons = visible_lessons(db, course.id)
    rows = progress_rows(db, student_id, course.id)
    visible_ids = [l.id for l in lessons]
    done = [i for i in visible_ids if rows.get(i) and rows[i].completed_at]
    nxt = next((i for i in visible_ids if i not in done), None)
    opened = [r for r in rows.values() if r.last_opened_at and r.lesson_id in visible_ids]
    last = max(opened, key=lambda r: as_utc(r.last_opened_at), default=None)
    total = len(visible_ids)
    return {
        "total_lessons": total, "completed_lessons": len(done), "percent": round(100 * len(done) / total) if total else 0,
        "completed_ids": [str(i) for i in done], "next_lesson_id": str(nxt) if nxt else None,
        # resume where the student stopped: the most recently opened unfinished lesson, else the next unfinished one
        "resume_lesson_id": str(last.lesson_id) if last and last.lesson_id not in done else (str(nxt) if nxt else None),
        "time_spent_seconds": sum(r.time_spent_seconds for r in rows.values()),
        "last_activity_at": as_utc(last.last_opened_at).isoformat() if last else None,
    }


def meets_completion_rule(course: LmsCourse, prog: dict) -> bool:
    rule = course.completion_rule or {}
    need = rule.get("min_lesson_percent", 100)
    if prog["total_lessons"] == 0:
        return False
    # NOTE: require_quizzes is stored but only enforceable once quizzes exist (Phase 4/5).
    return prog["percent"] >= need


def sync_completion(db: Session, enrollment: LmsEnrollment, course: LmsCourse) -> None:
    """Flip an enrollment between active and completed according to the course's completion rule.
    Other statuses (suspended, cancelled, expired, pending) are never touched here."""
    if enrollment.status not in ("active", "completed"):
        return
    prog = course_progress(db, enrollment.student_id, course)
    if meets_completion_rule(course, prog):
        if enrollment.status != "completed":
            enrollment.status, enrollment.completed_at = "completed", utcnow()
    elif enrollment.status == "completed":
        enrollment.status, enrollment.completed_at = "active", None


def touch_lesson(db: Session, student_id: uuid.UUID, lesson: LmsLesson, seconds: int = 0) -> LmsLessonProgress:
    p = db.scalar(select(LmsLessonProgress).where(LmsLessonProgress.student_id == student_id,
                                                  LmsLessonProgress.lesson_id == lesson.id))
    if p is None:
        p = LmsLessonProgress(student_id=student_id, lesson_id=lesson.id, course_id=lesson.course_id, time_spent_seconds=0)
        db.add(p)
    p.last_opened_at = utcnow()
    p.time_spent_seconds = (p.time_spent_seconds or 0) + max(0, seconds)
    db.flush()
    return p


def enrollment_counts(db: Session, course_ids: list[uuid.UUID]) -> dict:
    if not course_ids:
        return {}
    return dict(db.execute(select(LmsEnrollment.course_id, func.count()).where(LmsEnrollment.course_id.in_(course_ids))
                           .group_by(LmsEnrollment.course_id)).all())
