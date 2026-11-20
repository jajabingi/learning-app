import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Difficulty = Literal["beginner", "intermediate", "advanced", "all"]
EnrollmentType = Literal["free", "paid", "manual"]
PaymentPolicy = Literal["full_payment", "any_payment", "none"]
Money = Field(default=Decimal("0"), ge=0, le=Decimal("10000000"), decimal_places=2)
ShortList = Field(default=[], max_length=30)


class CompletionRule(BaseModel):
    min_lesson_percent: int = Field(default=100, ge=0, le=100)
    require_quizzes: bool = False


class CourseBase(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    subtitle: str = Field(default="", max_length=300)
    description: str = Field(default="", max_length=50000)
    summary: str = Field(default="", max_length=100000)
    instructor_name: str = Field(default="", max_length=120)
    category: str = Field(default="", max_length=80)
    difficulty: Difficulty = "all"
    language: str = Field(default="English", max_length=40)
    price_amount: Decimal = Money
    discount_amount: Decimal | None = Field(default=None, ge=0, le=Decimal("10000000"), decimal_places=2)
    currency: str = Field(default="ILS", pattern=r"^[A-Z]{3}$")
    enrollment_type: EnrollmentType = "manual"
    payment_policy: PaymentPolicy = "full_payment"
    access_days: int | None = Field(default=None, ge=1, le=3650)
    objectives: list[str] = ShortList
    requirements: list[str] = ShortList
    target_audience: str = Field(default="", max_length=5000)
    estimated_minutes: int = Field(default=0, ge=0, le=100000)
    completion_rule: CompletionRule = CompletionRule()
    cover_attachment_id: uuid.UUID | None = None
    institution_id: uuid.UUID | None = None

    @field_validator("objectives", "requirements")
    @classmethod
    def _items(cls, v: list[str]):
        return [s.strip()[:300] for s in v if s.strip()]

    @model_validator(mode="after")
    def _discount(self):
        if self.discount_amount is not None and self.discount_amount >= self.price_amount:
            raise ValueError("Discount price must be lower than the price")
        if self.enrollment_type == "free" and self.price_amount > 0:
            raise ValueError("A free course cannot have a price")
        return self


class CourseCreate(CourseBase):
    pass


class CoursePatch(BaseModel):
    """Partial update. Only fields that are present are changed."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    subtitle: str | None = Field(default=None, max_length=300)
    description: str | None = Field(default=None, max_length=50000)
    summary: str | None = Field(default=None, max_length=100000)
    instructor_name: str | None = Field(default=None, max_length=120)
    category: str | None = Field(default=None, max_length=80)
    difficulty: Difficulty | None = None
    language: str | None = Field(default=None, max_length=40)
    price_amount: Decimal | None = Field(default=None, ge=0, le=Decimal("10000000"), decimal_places=2)
    discount_amount: Decimal | None = Field(default=None, ge=0, le=Decimal("10000000"), decimal_places=2)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    enrollment_type: EnrollmentType | None = None
    payment_policy: PaymentPolicy | None = None
    access_days: int | None = Field(default=None, ge=1, le=3650)
    objectives: list[str] | None = Field(default=None, max_length=30)
    requirements: list[str] | None = Field(default=None, max_length=30)
    target_audience: str | None = Field(default=None, max_length=5000)
    estimated_minutes: int | None = Field(default=None, ge=0, le=100000)
    completion_rule: CompletionRule | None = None
    cover_attachment_id: uuid.UUID | None = None
    institution_id: uuid.UUID | None = None


class StatusIn(BaseModel):
    status: Literal["draft", "published", "archived"]


class ModuleIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    summary: str = Field(default="", max_length=100000)


class ModulePatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    summary: str | None = Field(default=None, max_length=100000)
    is_published: bool | None = None


class LessonIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(default="", max_length=100000)
    estimated_minutes: int = Field(default=0, ge=0, le=10000)
    is_free_preview: bool = False


class LessonPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=100000)
    estimated_minutes: int | None = Field(default=None, ge=0, le=10000)
    is_free_preview: bool | None = None
    is_published: bool | None = None
    module_id: uuid.UUID | None = None  # move to another module of the same course


class BlockIn(BaseModel):
    type: str
    data: dict = {}
    is_visible: bool = True
    position: int | None = Field(default=None, ge=0)  # insert at index; default append


class BlockPatch(BaseModel):
    data: dict | None = None
    is_visible: bool | None = None


class ReorderIn(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=0, max_length=500)


class AdminUserCreate(BaseModel):
    email: str = Field(max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=8, max_length=72)
    display_name: str = Field(default="", max_length=100)
    role: Literal["teacher", "admin"] = "teacher"
    permissions: list[str] | None = None


class AdminUserPatch(BaseModel):
    role: Literal["student", "teacher", "admin"] | None = None
    is_active: bool | None = None
    permissions: list[str] | None = None
    display_name: str | None = Field(default=None, max_length=100)
