"""Request models for the admin management APIs."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")


def _validate_ai_model_id(value: str) -> str:
    model_id = value.strip()
    if not MODEL_ID_PATTERN.fullmatch(model_id):
        raise ValueError("模型 ID 只能包含字母、数字、点、下划线和短横线")
    return model_id


def _validate_ai_model_provider(value: str) -> str:
    provider = value.strip().lower()
    if provider != "dashscope":
        raise ValueError("当前仅支持 dashscope 模型供应商")
    return provider


class AdminUserUpdateRequest(BaseModel):
    nickname: str | None = Field(default=None, max_length=50)
    role: Literal["user", "admin", "super_admin"] | None = None
    status: Literal[0, 1] | None = None

    @model_validator(mode="after")
    def ensure_has_changes(self) -> "AdminUserUpdateRequest":
        if self.nickname is None and self.role is None and self.status is None:
            raise ValueError("至少需要提供一个要修改的字段")
        return self


class AdminUserStatusRequest(BaseModel):
    status: Literal[0, 1]


class AdminPointsAdjustmentRequest(BaseModel):
    change_type: Literal["add", "subtract", "adjust"]
    change_amount: int | None = Field(default=None, gt=0)
    target_points: int | None = Field(default=None, ge=0)
    reason: str = Field(..., min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_payload(self) -> "AdminPointsAdjustmentRequest":
        if self.change_type in {"add", "subtract"}:
            if self.change_amount is None:
                raise ValueError("增加或扣减积分时必须提供 change_amount")
            if self.target_points is not None:
                raise ValueError("增加或扣减积分时不应提供 target_points")
        elif self.change_type == "adjust":
            if self.target_points is None:
                raise ValueError("直接调整积分时必须提供 target_points")
            if self.change_amount is not None:
                raise ValueError("直接调整积分时不应提供 change_amount")
        return self


class KbDocumentUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    category: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None

    @model_validator(mode="after")
    def ensure_has_changes(self) -> "KbDocumentUpdateRequest":
        if self.title is None and self.category is None and self.description is None:
            raise ValueError("至少需要提供一个要修改的字段")
        return self


class KbDocumentEnabledRequest(BaseModel):
    enabled: bool


class KbDocumentContentUpdateRequest(BaseModel):
    content: str = Field(..., min_length=1)
    reindex: bool = False


class KbSearchTestRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)
    category: str | None = Field(default=None, max_length=100)


class SystemPromptCreateRequest(BaseModel):
    prompt_key: str = Field(..., min_length=1, max_length=100)
    prompt_name: str = Field(..., min_length=1, max_length=100)
    prompt_type: str = Field(..., min_length=1, max_length=100)
    content: str = Field(..., min_length=1)
    remark: str | None = None
    enabled: bool = False


class SystemPromptUpdateRequest(BaseModel):
    prompt_name: str | None = Field(default=None, min_length=1, max_length=100)
    prompt_type: str | None = Field(default=None, min_length=1, max_length=100)
    content: str | None = Field(default=None, min_length=1)
    remark: str | None = None

    @model_validator(mode="after")
    def ensure_has_changes(self) -> "SystemPromptUpdateRequest":
        if (
            self.prompt_name is None
            and self.prompt_type is None
            and self.content is None
            and self.remark is None
        ):
            raise ValueError("至少需要提供一个要修改的字段")
        return self


class SystemPromptTestRequest(BaseModel):
    prompt_key: str = Field(..., min_length=1, max_length=100)
    test_input: str = Field(..., min_length=1, max_length=4000)


class AiModelCreateRequest(BaseModel):
    model_id: str = Field(..., min_length=1, max_length=120)
    display_name: str = Field(..., min_length=1, max_length=120)
    provider: str = Field(default="dashscope", min_length=1, max_length=50)
    enabled: bool = True
    is_default: bool = False
    sort_order: int = Field(default=100, ge=0, le=10000)
    min_membership_level: str | None = Field(default=None, max_length=50)
    access_scope: str = Field(default="all", max_length=50)
    remark: str | None = None

    @field_validator("model_id")
    @classmethod
    def validate_model_id(cls, value: str) -> str:
        return _validate_ai_model_id(value)

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        return _validate_ai_model_provider(value)


class AiModelUpdateRequest(BaseModel):
    model_id: str | None = Field(default=None, min_length=1, max_length=120)
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    provider: str | None = Field(default=None, min_length=1, max_length=50)
    enabled: bool | None = None
    is_default: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=10000)
    min_membership_level: str | None = Field(default=None, max_length=50)
    access_scope: str | None = Field(default=None, max_length=50)
    remark: str | None = None

    @field_validator("model_id")
    @classmethod
    def validate_model_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_ai_model_id(value)

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_ai_model_provider(value)

    @model_validator(mode="after")
    def ensure_has_changes(self) -> "AiModelUpdateRequest":
        if (
            self.model_id is None
            and self.display_name is None
            and self.provider is None
            and self.enabled is None
            and self.is_default is None
            and self.sort_order is None
            and self.min_membership_level is None
            and self.access_scope is None
            and self.remark is None
        ):
            raise ValueError("至少需要提供一个要修改的字段")
        return self


class AiModelEnabledRequest(BaseModel):
    enabled: bool
