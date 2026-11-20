import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


def _check_password(v: str) -> str:
    if len(v) < 8:
        raise ValueError("Password must be at least 8 characters")
    if len(v.encode()) > 72:
        raise ValueError("Password must be at most 72 bytes")
    return v


class RegisterIn(BaseModel):
    email: EmailStr
    password: str
    display_name: str = Field(default="", max_length=100)

    _pw = field_validator("password")(_check_password)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=200)


class RefreshIn(BaseModel):
    refresh_token: str


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: str
    display_name: str
    role: str = "student"
    permissions: list[str] = []
    desired_retention: float
    daily_new_limit: int
    daily_review_goal: int
    timezone: str


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=100)
    desired_retention: float | None = Field(default=None, ge=0.7, le=0.97)
    daily_new_limit: int | None = Field(default=None, ge=0, le=500)
    daily_review_goal: int | None = Field(default=None, ge=1, le=2000)
    timezone: str | None = Field(default=None, max_length=64)


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str

    _pw = field_validator("new_password")(_check_password)
