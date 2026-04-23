from __future__ import annotations

from datetime import datetime

from pydantic import EmailStr, Field

from app.models.user import UserRole
from app.schemas.common import ORMModel


class UserPublic(ORMModel):
    id: int
    full_name: str
    role: UserRole
    profile_image_url: str | None = None
    created_at: datetime


class UserMe(UserPublic):
    email: EmailStr
    phone: str | None = None
    is_active: bool


class UserUpdate(ORMModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    profile_image_url: str | None = Field(default=None, max_length=1024)
