"""Request models for the admin management APIs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


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
