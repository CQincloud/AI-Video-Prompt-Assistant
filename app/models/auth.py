"""Authentication request and response models."""

from pydantic import BaseModel, Field


class SendCodeRequest(BaseModel):
    phone: str = Field(..., min_length=11, max_length=11, description="Chinese mainland phone number")


class LoginRequest(BaseModel):
    phone: str = Field(..., min_length=11, max_length=11, description="Chinese mainland phone number")
    code: str = Field(..., min_length=6, max_length=6, description="SMS verification code")
