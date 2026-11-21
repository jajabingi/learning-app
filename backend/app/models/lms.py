"""Teaching / LMS tables. Prefixed `lms_` to stay distinct from the personal-library Course/Chapter models."""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import IdMixin, JSONType, TimestampMixin, TZDateTime

COURSE_STATUSES = ("draft", "published", "archived")
ENROLLMENT_STATUSES = ("pending", "active", "suspended", "completed", "expired", "cancelled")
ENROLLMENT_SOURCES = ("manual", "free", "purchase", "online")
# statuses that can grant access to content (subject to start/expiry dates)
ACCESS_STATUSES = ("active", "completed")


class LmsInstitution(IdMixin, TimestampMixin, Base):
    """A university / school / brand that groups courses on the public landing page."""

    __tablename__ = "lms_institutions"
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False)


class LmsCourse(IdMixin, TimestampMixin, Base):
    __tablename__ = "lms_courses"
    __table_args__ = (Index("ix_lms_courses_status", "status"),)

    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    institution_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("lms_institutions.id", ondelete="SET NULL"), nullable=True, index=True)
    slug: Mapped[str] = mapped_column(String(160), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    subtitle: Mapped[str] = mapped_column(String(300), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")  # course-level summary / study notes (Markdown)
    cover_attachment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("attachments.id", ondelete="SET NULL"), nullable=True)
    instructor_name: Mapped[str] = mapped_column(String(120), default="")
    category: Mapped[str] = mapped_column(String(80), default="")
    difficulty: Mapped[str] = mapped_column(String(16), default="all")  # beginner|intermediate|advanced|all
    language: Mapped[str] = mapped_column(String(40), default="English")
    status: Mapped[str] = mapped_column(String(12), default="draft")
    published_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)

    # pricing / enrollment configuration (payments themselves arrive in a later phase)
    price_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    discount_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="ILS")
    enrollment_type: Mapped[str] = mapped_column(String(12), default="manual")  # free | paid | manual
    payment_policy: Mapped[str] = mapped_column(String(24), default="full_payment")  # full_payment | any_payment | none
    access_days: Mapped[int | None] = mapped_column(Integer, nullable=True)  # null = lifetime access
    payment_instructions: Mapped[str] = mapped_column(Text, default="", server_default="")  # how to pay offline (bank details, Bit, ...)

    objectives: Mapped[list] = mapped_column(JSONType, default=list)
    requirements: Mapped[list] = mapped_column(JSONType, default=list)
    target_audience: Mapped[str] = mapped_column(Text, default="")
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=0)
    completion_rule: Mapped[dict] = mapped_column(JSONType, default=dict)

    modules: Mapped[list["LmsModule"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, order_by="LmsModule.position"
    )


class LmsModule(IdMixin, TimestampMixin, Base):
    __tablename__ = "lms_modules"
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lms_courses.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False)

    lessons: Mapped[list["LmsLesson"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, order_by="LmsLesson.position"
    )


class LmsLesson(IdMixin, TimestampMixin, Base):
    __tablename__ = "lms_lessons"
    # course_id is denormalised so a lesson's course can be checked without a join
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lms_courses.id", ondelete="CASCADE"), index=True)
    module_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lms_modules.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False)
    is_free_preview: Mapped[bool] = mapped_column(Boolean, default=False)
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=0)

    blocks: Mapped[list["LmsBlock"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, order_by="LmsBlock.position"
    )


class LmsBlock(IdMixin, TimestampMixin, Base):
    __tablename__ = "lms_blocks"
    lesson_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lms_lessons.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(24))
    position: Mapped[int] = mapped_column(Integer, default=0)
    is_visible: Mapped[bool] = mapped_column(Boolean, default=True)  # hidden blocks are never sent to students
    data: Mapped[dict] = mapped_column(JSONType, default=dict)


class LmsEnrollment(IdMixin, TimestampMixin, Base):
    """A student's entitlement to one course. Separate from the user; one user can hold many."""

    __tablename__ = "lms_enrollments"
    __table_args__ = (
        UniqueConstraint("student_id", "course_id", name="uq_enrollment_student_course"),
        Index("ix_enrollment_student_status", "student_id", "status"),
    )
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lms_courses.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(12), default="pending")
    source: Mapped[str] = mapped_column(String(12), default="manual")
    starts_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    granted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    completed_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)


class LmsLessonProgress(IdMixin, TimestampMixin, Base):
    """One row per student per lesson: completion, resume position and time actually spent."""

    __tablename__ = "lms_lesson_progress"
    __table_args__ = (
        UniqueConstraint("student_id", "lesson_id", name="uq_lesson_progress_student_lesson"),
        Index("ix_lesson_progress_student_course", "student_id", "course_id"),
    )
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    lesson_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lms_lessons.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lms_courses.id", ondelete="CASCADE"))
    completed_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    last_opened_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    time_spent_seconds: Mapped[int] = mapped_column(Integer, default=0)


class LmsPracticeSet(IdMixin, TimestampMixin, Base):
    """A topic-based set of practice/exam questions inside a course. Students only ever receive the questions
    placed in published sets of courses they are enrolled in; the teacher's master question bank stays private."""

    __tablename__ = "lms_practice_sets"
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lms_courses.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(12), default="practice")  # practice | exam (label; timed exams come later)
    position: Mapped[int] = mapped_column(Integer, default=0)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False)

    items: Mapped[list["LmsPracticeItem"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, order_by="LmsPracticeItem.position"
    )


class LmsPracticeItem(IdMixin, Base):
    __tablename__ = "lms_practice_items"
    __table_args__ = (UniqueConstraint("set_id", "question_id", name="uq_practice_set_question"),)
    set_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lms_practice_sets.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)


class LmsPracticeAttempt(IdMixin, Base):
    """The student's latest attempt at one practice item (answer revealed = solution seen)."""

    __tablename__ = "lms_practice_attempts"
    __table_args__ = (UniqueConstraint("student_id", "item_id", name="uq_practice_attempt_student_item"),)
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lms_practice_items.id", ondelete="CASCADE"), index=True)
    selected_option_ids: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    revealed_at: Mapped[datetime] = mapped_column(TZDateTime())
