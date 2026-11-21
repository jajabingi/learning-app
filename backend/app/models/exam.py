"""Timed & graded exams.

Design notes
- `LmsExam` holds the configuration; `LmsExamQuestion` the ordered questions with an exam-specific point value and a
  frozen `snapshot` of the question (content, options, answer key). Editing the question bank never changes an exam.
- Structure (questions, points, time limit, grading rules) is editable only while the exam is a draft. Presentation /
  result-release / date settings may still change while published.
- `LmsExamAttempt` copies the settings and the (possibly shuffled) question list into its own JSON snapshots when it is
  started, so an attempt is immune to any later edit. The server owns `started_at` / `deadline_at`.
- `LmsExamAnswer` is one row per (attempt, question): the student's answer, flag, and the grading outcome.
"""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import IdMixin, JSONType, TimestampMixin, TZDateTime

EXAM_STATUSES = ("draft", "published", "closed", "archived")
ATTEMPT_STATUSES = ("in_progress", "submitted", "auto_submitted", "graded", "cancelled")
FINAL_ATTEMPT_STATUSES = ("submitted", "auto_submitted", "graded")
GRADING_STATUSES = ("auto", "pending", "graded")  # per answer


class LmsExam(IdMixin, TimestampMixin, Base):
    __tablename__ = "lms_exams"

    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lms_courses.id", ondelete="CASCADE"), index=True)
    module_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("lms_modules.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    instructions: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(80), default="")
    difficulty: Mapped[str] = mapped_column(String(10), default="medium")
    status: Mapped[str] = mapped_column(String(12), default="draft", index=True)

    # time
    time_limit_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    opens_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    closes_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)  # nobody may start after; attempts end by then
    # attempts
    max_attempts: Mapped[int | None] = mapped_column(Integer, nullable=True)  # None = unlimited
    grade_policy: Mapped[str] = mapped_column(String(8), default="highest")  # highest | latest
    allow_resume: Mapped[bool] = mapped_column(Boolean, default=True)
    # navigation / presentation
    allow_back: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_change_answers: Mapped[bool] = mapped_column(Boolean, default=True)
    one_per_page: Mapped[bool] = mapped_column(Boolean, default=False)
    shuffle_questions: Mapped[bool] = mapped_column(Boolean, default=False)
    shuffle_options: Mapped[bool] = mapped_column(Boolean, default=False)
    # grading
    passing_score: Mapped[int] = mapped_column(Integer, default=60)  # percent
    partial_credit: Mapped[bool] = mapped_column(Boolean, default=True)
    # results
    show_score: Mapped[bool] = mapped_column(Boolean, default=True)
    show_pass_fail: Mapped[bool] = mapped_column(Boolean, default=True)
    show_answers: Mapped[bool] = mapped_column(Boolean, default=False)
    show_explanations: Mapped[bool] = mapped_column(Boolean, default=False)
    results_release: Mapped[str] = mapped_column(String(10), default="immediate")  # immediate | manual | scheduled
    results_release_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    results_released_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)  # manual publication
    release_partial: Mapped[bool] = mapped_column(Boolean, default=False)  # show results while manual grading is pending

    questions: Mapped[list["LmsExamQuestion"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, order_by="LmsExamQuestion.position", lazy="selectin"
    )


class LmsExamQuestion(IdMixin, Base):
    __tablename__ = "lms_exam_questions"
    __table_args__ = (Index("ix_lms_exam_questions_exam_pos", "exam_id", "position"),)

    exam_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lms_exams.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("questions.id", ondelete="SET NULL"), nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    points: Mapped[Decimal] = mapped_column(Numeric(7, 2), default=Decimal("1"))
    grading: Mapped[str] = mapped_column(String(8), default="auto")  # auto | manual
    snapshot: Mapped[dict] = mapped_column(JSONType)  # {type,title,content,options:[{id,text,is_correct}],answer,explanation,tolerance}


class LmsExamAttempt(IdMixin, TimestampMixin, Base):
    __tablename__ = "lms_exam_attempts"
    __table_args__ = (
        UniqueConstraint("exam_id", "student_id", "attempt_no", name="uq_lms_exam_attempt_no"),
        Index("ix_lms_exam_attempts_exam_student", "exam_id", "student_id"),
    )

    exam_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lms_exams.id", ondelete="CASCADE"), index=True)
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    attempt_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(14), default="in_progress")
    auto_submitted: Mapped[bool] = mapped_column(Boolean, default=False)  # ended by the server clock, not by the student
    started_at: Mapped[datetime] = mapped_column(TZDateTime())
    deadline_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)  # server-authoritative
    submitted_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    settings_snapshot: Mapped[dict] = mapped_column(JSONType)
    order_snapshot: Mapped[dict] = mapped_column(JSONType)  # {"questions": [exam_question_id...], "options": {qid: [option_id...]}}
    score: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    max_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    graded_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)  # per-attempt manual release

    answers: Mapped[list["LmsExamAnswer"]] = relationship(cascade="all, delete-orphan", passive_deletes=True, lazy="selectin")


class LmsExamAnswer(IdMixin, TimestampMixin, Base):
    __tablename__ = "lms_exam_answers"
    __table_args__ = (UniqueConstraint("attempt_id", "exam_question_id", name="uq_lms_exam_answer"),)

    attempt_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lms_exam_attempts.id", ondelete="CASCADE"), index=True)
    exam_question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lms_exam_questions.id", ondelete="CASCADE"))
    answer: Mapped[dict | None] = mapped_column(JSONType, nullable=True)  # {"option_ids": [...]} | {"text": "..."}
    flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    grading_status: Mapped[str] = mapped_column(String(8), default="pending")
    points_awarded: Mapped[Decimal | None] = mapped_column(Numeric(7, 2), nullable=True)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    feedback: Mapped[str] = mapped_column(Text, default="")
    graded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
