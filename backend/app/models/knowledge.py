import uuid
from datetime import datetime

from sqlalchemy import Column, ForeignKey, Index, Integer, String, Table, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import IdMixin, TimestampMixin, TZDateTime


class Subject(IdMixin, TimestampMixin, Base):
    __tablename__ = "subjects"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    color: Mapped[str] = mapped_column(String(16), default="#6366f1")
    icon: Mapped[str] = mapped_column(String(40), default="book")
    position: Mapped[int] = mapped_column(Integer, default=0)
    archived_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)

    courses: Mapped[list["Course"]] = relationship(cascade="all, delete-orphan", passive_deletes=True)


class Course(IdMixin, TimestampMixin, Base):
    __tablename__ = "courses"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    subject_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    color: Mapped[str] = mapped_column(String(16), default="")
    icon: Mapped[str] = mapped_column(String(40), default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    archived_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)

    chapters: Mapped[list["Chapter"]] = relationship(cascade="all, delete-orphan", passive_deletes=True)


class Chapter(IdMixin, TimestampMixin, Base):
    __tablename__ = "chapters"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    archived_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)


class Topic(IdMixin, TimestampMixin, Base):
    """A topic always belongs to a subject. `chapter_id` places it in the Course/Chapter structure
    (optional so topics can live directly under a subject). `parent_id` makes subtopics (any depth)."""

    __tablename__ = "topics"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    subject_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"), index=True)
    chapter_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("chapters.id", ondelete="SET NULL"), nullable=True, index=True
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("topics.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    color: Mapped[str] = mapped_column(String(16), default="")
    icon: Mapped[str] = mapped_column(String(40), default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    archived_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)

    tags: Mapped[list["Tag"]] = relationship(secondary="topic_tags", lazy="selectin")


class Tag(IdMixin, Base):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_tag_user_name"),)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    color: Mapped[str] = mapped_column(String(16), default="")


topic_tags = Table(
    "topic_tags",
    Base.metadata,
    Column("topic_id", Uuid, ForeignKey("topics.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Uuid, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)

RELATION_TYPES = ("related_to", "prerequisite_for", "part_of", "contrasts_with", "depends_on", "applied_in")


class TopicRelationship(IdMixin, Base):
    __tablename__ = "topic_relationships"
    __table_args__ = (
        UniqueConstraint("source_topic_id", "target_topic_id", "relation_type", name="uq_topic_relationship"),
        Index("ix_topic_rel_user", "user_id"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    source_topic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), index=True)
    target_topic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), index=True)
    relation_type: Mapped[str] = mapped_column(String(32), default="related_to")
    note: Mapped[str] = mapped_column(String(300), default="")
