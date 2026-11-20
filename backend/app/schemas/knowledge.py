import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RelationType = Literal["related_to", "prerequisite_for", "part_of", "contrasts_with", "depends_on", "applied_in"]
Color = Field(default=None, max_length=16, pattern=r"^(#[0-9a-fA-F]{3,8})?$")


class TagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    color: str


class TagIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    color: str = Field(default="", max_length=16)


class SubjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    color: str | None = Color
    icon: str | None = Field(default=None, max_length=40)


class SubjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    color: str | None = Color
    icon: str | None = Field(default=None, max_length=40)
    archived: bool | None = None


class CourseIn(BaseModel):
    subject_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)


class CoursePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    archived: bool | None = None
    subject_id: uuid.UUID | None = None  # move to another subject


class ChapterIn(BaseModel):
    course_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)


class ChapterPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    archived: bool | None = None
    course_id: uuid.UUID | None = None  # move to another course


class TopicIn(BaseModel):
    subject_id: uuid.UUID | None = None  # optional when a parent topic is given
    chapter_id: uuid.UUID | None = None
    parent_id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=20000)
    color: str | None = Color
    icon: str | None = Field(default=None, max_length=40)
    tag_ids: list[uuid.UUID] = []


class TopicPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=20000)
    color: str | None = Color
    icon: str | None = Field(default=None, max_length=40)
    archived: bool | None = None
    tag_ids: list[uuid.UUID] | None = None
    # Moving: provide `move=True` together with the new placement (null = detach).
    move: bool = False
    subject_id: uuid.UUID | None = None
    chapter_id: uuid.UUID | None = None
    parent_id: uuid.UUID | None = None


class MoveIn(BaseModel):
    direction: Literal["up", "down"]


class RelationshipIn(BaseModel):
    source_topic_id: uuid.UUID
    target_topic_id: uuid.UUID
    relation_type: RelationType = "related_to"
    note: str = Field(default="", max_length=300)


class RelationshipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    source_topic_id: uuid.UUID
    target_topic_id: uuid.UUID
    relation_type: str
    note: str


class TopicRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    subject_id: uuid.UUID


class TimestampedOut(BaseModel):
    created_at: datetime
    updated_at: datetime
