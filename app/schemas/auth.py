from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from app.models.user import UserRole


class CustomerRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=32)


class DriverRegister(CustomerRegister):
    license_number: str = Field(min_length=3, max_length=64)
    vehicle_type: str = Field(min_length=1, max_length=64)
    vehicle_plate: str = Field(min_length=1, max_length=32)
    vehicle_capacity_kg: float | None = Field(default=None, gt=0)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    role: UserRole = Field(..., description="'customer' or 'driver'")


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str


class GoogleTokenRequest(BaseModel):
    """Frontend sends the Google ID token it obtained client-side."""

    id_token: str
    role: UserRole = Field(..., description="'customer' or 'driver'")


class GoogleIdTokenRequest(BaseModel):
    """Simplified payload for POST /auth/google.

    Accepts only an ID token; role defaults to 'customer'.
    Use role='driver' explicitly when signing in as a driver.
    """

    id_token: str
    role: UserRole = Field(default=UserRole.CUSTOMER, description="'customer' or 'driver'")


class GoogleCallbackRequest(BaseModel):
    """Backend callback: code + state sent by Google redirect."""

    code: str
    state: str  # contains role


class GoogleAuthUrlResponse(BaseModel):
    url: str
