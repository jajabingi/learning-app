import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, ForeignKey, Index, Integer, String, Table, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import IdMixin, TimestampMixin, TZDateTime, utcnow

QUESTION_TYPES = (
    "open_ended", "multiple_choice", "true_false", "short_answer", "calculation", "formula",
    "definition", "conceptual", "case_study", "comparison", "scenario",
)
DIFFICULTIES = ("easy", "medium", "hard")

question_topics = Table(
    "question_topics",
    Base.metadata,
    Column("question_id", Uuid, ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True),
    Column("topic_id", Uuid, ForeignKey("topics.id", ondelete="CASCADE"), primary_key=True, index=True),
)

question_tags = Table(
    "question_tags",
    Base.metadata,
    Column("question_id", Uuid, ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Uuid, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True, index=True),
)


class Question(IdMixin, TimestampMixin, Base):
    __tablename__ = "questions"
    __table_args__ = (Index("ix_questions_user_subject", "user_id", "subject_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(300), default="")
    content: Mapped[str] = mapped_column(Text, default="")  # Markdown + LaTeX
    question_type: Mapped[str] = mapped_column(String(24), default="open_ended")
    difficulty: Mapped[str] = mapped_column(String(10), default="medium")
    source: Mapped[str] = mapped_column(String(500), default="")
    archived_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)

    answer: Mapped["QuestionAnswer | None"] = relationship(
        uselist=False, cascade="all, delete-orphan", passive_deletes=True, lazy="selectin"
    )
    options: Mapped[list["QuestionOption"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, order_by="QuestionOption.position", lazy="selectin"
    )
    topics: Mapped[list["Topic"]] = relationship(secondary=question_topics, lazy="selectin")  # noqa: F821
    tags: Mapped[list["Tag"]] = relationship(secondary=question_tags, lazy="selectin")  # noqa: F821


class QuestionAnswer(IdMixin, Base):
    __tablename__ = "question_answers"
    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), unique=True
    )
    answer: Mapped[str] = mapped_column(Text, default="")
    explanation: Mapped[str] = mapped_column(Text, default="")


class QuestionOption(IdMixin, Base):
    __tablename__ = "question_options"
    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    position: Mapped[int] = mapped_column(Integer, default=0)


class Attachment(IdMixin, Base):
    __tablename__ = "attachments"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    note_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("notes.id", ondelete="CASCADE"), nullable=True, index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    storage_key: Mapped[str] = mapped_column(String(300), unique=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
