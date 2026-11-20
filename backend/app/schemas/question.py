import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.knowledge import TagOut

QuestionType = Literal[
    "open_ended", "multiple_choice", "true_false", "short_answer", "calculation", "formula",
    "definition", "conceptual", "case_study", "comparison", "scenario",
]
Difficulty = Literal["easy", "medium", "hard"]
TEXT_MAX = 50000


class OptionIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    is_correct: bool = False


class OptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    text: str
    is_correct: bool
    position: int


class AnswerIn(BaseModel):
    answer: str = Field(default="", max_length=TEXT_MAX)
    explanation: str = Field(default="", max_length=TEXT_MAX)


class QuestionBase(BaseModel):
    title: str = Field(default="", max_length=300)
    content: str = Field(default="", max_length=TEXT_MAX)
    question_type: QuestionType = "open_ended"
    difficulty: Difficulty = "medium"
    source: str = Field(default="", max_length=500)
    subject_id: uuid.UUID | None = None
    topic_ids: list[uuid.UUID] = []
    tags: list[str] = Field(default=[], max_length=30)  # tag names; created on demand
    answer: AnswerIn = AnswerIn()
    options: list[OptionIn] = Field(default=[], max_length=12)


class QuestionCreate(QuestionBase):
    @model_validator(mode="after")
    def _need_text(self):
        if not (self.title.strip() or self.content.strip()):
            raise ValueError("A question needs a title or content")
        if self.question_type in ("multiple_choice", "true_false") and self.options:
            if not any(o.is_correct for o in self.options):
                raise ValueError("Mark at least one option as correct")
        return self


class QuestionUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    content: str | None = Field(default=None, max_length=TEXT_MAX)
    question_type: QuestionType | None = None
    difficulty: Difficulty | None = None
    source: str | None = Field(default=None, max_length=500)
    subject_id: uuid.UUID | None = None
    set_subject: bool = False  # distinguishes "leave subject" from "clear subject"
    topic_ids: list[uuid.UUID] | None = None
    tags: list[str] | None = None
    answer: AnswerIn | None = None
    options: list[OptionIn] | None = None
    archived: bool | None = None
    confidence: int | None = Field(default=None, ge=1, le=5)


class ProgressOut(BaseModel):
    status: str = "new"
    state: str = "new"
    suspended: bool = False
    stability: float = 0.0
    difficulty: float = 0.0
    reps: int = 0
    lapses: int = 0
    correct_count: int = 0
    confidence: int | None = None
    last_review_at: datetime | None = None
    due_at: datetime | None = None
    retrievability: float | None = None
    mastery: float = 0.0


class AttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int


class TopicMini(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str


class QuestionOut(BaseModel):
    id: uuid.UUID
    title: str
    content: str
    question_type: str
    difficulty: str
    source: str
    subject_id: uuid.UUID | None
    topics: list[TopicMini]
    tags: list[TagOut]
    answer: AnswerIn
    options: list[OptionOut]
    attachments: list[AttachmentOut] = []
    archived: bool
    created_at: datetime
    updated_at: datetime
    progress: ProgressOut


class QuestionPage(BaseModel):
    items: list[QuestionOut]
    total: int
    page: int
    page_size: int


class BulkIn(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=1000)
    action: Literal[
        "archive", "unarchive", "delete", "add_tags", "remove_tags", "set_subject", "add_topic",
        "set_difficulty", "suspend", "unsuspend", "reset_progress",
    ]
    tags: list[str] = []
    subject_id: uuid.UUID | None = None
    topic_id: uuid.UUID | None = None
    difficulty: Difficulty | None = None


class NoteIn(BaseModel):
    title: str = Field(default="", max_length=300)
    content: str = Field(default="", max_length=200000)
    kind: Literal["note", "definition", "formula"] = "note"
    subject_id: uuid.UUID | None = None
    course_id: uuid.UUID | None = None
    chapter_id: uuid.UUID | None = None
    topic_id: uuid.UUID | None = None
    question_id: uuid.UUID | None = None
    tags: list[str] = Field(default=[], max_length=30)


class NotePatch(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    content: str | None = Field(default=None, max_length=200000)
    kind: Literal["note", "definition", "formula"] | None = None
    subject_id: uuid.UUID | None = None
    course_id: uuid.UUID | None = None
    chapter_id: uuid.UUID | None = None
    topic_id: uuid.UUID | None = None
    question_id: uuid.UUID | None = None
    tags: list[str] | None = None
    set_links: bool = False  # True: replace the attachment fields (subject/course/... may be null)


class NoteOut(BaseModel):
    id: uuid.UUID
    title: str
    content: str
    kind: str
    subject_id: uuid.UUID | None
    course_id: uuid.UUID | None
    chapter_id: uuid.UUID | None
    topic_id: uuid.UUID | None
    question_id: uuid.UUID | None
    tags: list[TagOut]
    created_at: datetime
    updated_at: datetime
    links_to: list[dict] = []
