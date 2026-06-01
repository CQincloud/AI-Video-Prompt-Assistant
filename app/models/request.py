"""请求数据模型

定义 API 请求的 Pydantic 模型
"""

from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """对话请求"""

    id: str = Field(..., description="会话 ID", alias="Id")
    question: str = Field(..., description="用户问题", alias="Question")
    model_question: str | None = Field(None, description="发送给模型的增强问题", alias="ModelQuestion")
    prompt_template: str | None = Field(None, description="提示词模板类型", alias="PromptTemplate")
    client_message_id: str | None = Field(None, alias="ClientMessageId")
    assistant_message_id: str | None = Field(None, alias="AssistantMessageId")
    is_retry: bool = Field(False, alias="IsRetry")
    retry_of: str | None = Field(None, alias="RetryOf")

    class Config:
        populate_by_name = True
        json_schema_extra = {
            "example": {
                "Id": "session-123",
                "Question": "什么是向量数据库？"
            }
        }


class ClearRequest(BaseModel):
    """清空会话请求"""

    session_id: str = Field(..., description="会话 ID", alias="sessionId")

    class Config:
        populate_by_name = True


class ChatSessionCreateRequest(BaseModel):
    """Create a persisted chat session."""

    session_id: str | None = Field(None, alias="sessionId")
    title: str | None = None

    class Config:
        populate_by_name = True


class ChatMessageAppendRequest(BaseModel):
    """Append a raw chat message to a persisted session."""

    role: str
    content: str
    client_message_id: str | None = Field(None, alias="clientMessageId")
    parent_message_id: int | None = Field(None, alias="parentMessageId")
    metadata: dict[str, Any] = Field(default_factory=dict)

    class Config:
        populate_by_name = True


class ImageGenerationRequest(BaseModel):
    """Generate images from an AI video prompt."""

    session_id: str = Field(..., alias="sessionId")
    prompt: str
    client_message_id: str | None = Field(None, alias="clientMessageId")
    assistant_message_id: str | None = Field(None, alias="assistantMessageId")
    size: str = "1024*1024"
    count: int = Field(1, ge=1, le=4)
    style: str | None = None

    class Config:
        populate_by_name = True
