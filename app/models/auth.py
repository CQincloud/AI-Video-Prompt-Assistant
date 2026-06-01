"""Authentication request and response models."""

from datetime import datetime

from pydantic import BaseModel, Field


class SendCodeRequest(BaseModel):
    phone: str = Field(..., min_length=11, max_length=11, description="Chinese mainland phone number")


class LoginRequest(BaseModel):
    phone: str = Field(..., min_length=11, max_length=11, description="Chinese mainland phone number")
    code: str = Field(..., min_length=6, max_length=6, description="SMS verification code")


class AuthUser(BaseModel):
    id: int
    phone: str
    mobile: str
    nickname: str
    role: str
    status: int
    points: int
    created_at: datetime
    last_login_at: datetime | None = None
    last_login_ip: str | None = None
