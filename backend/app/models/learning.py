import uuid
from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, JSONType, TimestampMixin, TZDateTime, utcnow

# FSRS card states
NEW, LEARNING, REVIEW, RELEARNING = "new", "learning", "review", "relearning"


class UserQuestionProgress(IdMixin, TimestampMixin, Base):
    """Scheduler memory state for one question for one user (FSRS)."""

    __tablename__ = "user_question_progress"
    __table_args__ = (
        UniqueConstraint("user_id", "question_id", name="uq_progress_user_question"),
        Index("ix_progress_user_due", "user_id", "due_at"),
        Index("ix_progress_user_status", "user_id", "status"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), index=True)

    state: Mapped[str] = mapped_column(String(12), default=NEW)
    status: Mapped[str] = mapped_column(String(12), default="new")  # new|learning|reviewing|mastered
    suspended: Mapped[bool] = mapped_column(Boolean, default=False)
    stability: Mapped[float] = mapped_column(Float, default=0.0)  # days until R drops to 90%
    difficulty: Mapped[float] = mapped_column(Float, default=0.0)  # 1..10
    reps: Mapped[int] = mapped_column(Integer, default=0)
    lapses: Mapped[int] = mapped_column(Integer, default=0)
    correct_count: Mapped[int] = mapped_column(Integer, default=0)
    last_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1..5, user-reported
    last_review_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    scheduled_days: Mapped[float] = mapped_column(Float, default=0.0)


class StudySession(IdMixin, TimestampMixin, Base):
    __tablename__ = "study_sessions"
    __table_args__ = (Index("ix_sessions_user_started", "user_id", "started_at"),)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    mode: Mapped[str] = mapped_column(String(24), default="quick_recall")
    status: Mapped[str] = mapped_column(String(12), default="active")  # active|paused|completed|abandoned
    filters: Mapped[dict] = mapped_column(JSONType, default=dict)
    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("topics.id", ondelete="SET NULL"), nullable=True, index=True
    )
    subject_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    started_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    last_activity_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)


class StudySessionQuestion(IdMixin, Base):
    __tablename__ = "study_session_questions"
    __table_args__ = (UniqueConstraint("session_id", "position", name="uq_session_position"),)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("study_sessions.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    answered_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)


class QuestionReviewHistory(IdMixin, Base):
    """Append-only log of every review; used for analytics and (later) parameter optimisation."""

    __tablename__ = "question_review_history"
    __table_args__ = (
        Index("ix_review_user_time", "user_id", "reviewed_at"),
        Index("ix_review_question_time", "question_id", "reviewed_at"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"))
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("study_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reviewed_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    rating: Mapped[int] = mapped_column(Integer)  # 1 again, 2 hard, 3 good, 4 easy
    correct: Mapped[bool] = mapped_column(Boolean)  # rating >= 2 (or MCQ correctness)
    study_mode: Mapped[str] = mapped_column(String(24), default="quick_recall")
    time_ms: Mapped[int] = mapped_column(Integer, default=0)
    state_before: Mapped[str] = mapped_column(String(12))
    state_after: Mapped[str] = mapped_column(String(12))
    stability_before: Mapped[float] = mapped_column(Float, default=0.0)
    stability_after: Mapped[float] = mapped_column(Float, default=0.0)
    difficulty_before: Mapped[float] = mapped_column(Float, default=0.0)
    difficulty_after: Mapped[float] = mapped_column(Float, default=0.0)
    retrievability_before: Mapped[float | None] = mapped_column(Float, nullable=True)
    elapsed_days: Mapped[float] = mapped_column(Float, default=0.0)
    scheduled_days: Mapped[float] = mapped_column(Float, default=0.0)
    response_text: Mapped[str] = mapped_column(Text, default="")
    selected_option_ids: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    ai_score: Mapped[float | None] = mapped_column(Float, nullable=True)
