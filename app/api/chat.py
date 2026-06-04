"""Chat APIs for RAG responses and persisted conversation history."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sse_starlette.sse import EventSourceResponse

from app.config import config
from app.models.request import (
    ChatMessageAppendRequest,
    ChatRequest,
    ChatSessionCreateRequest,
    ClearRequest,
    ImageGenerationRequest,
)
from app.models.response import ApiResponse, SessionInfoResponse
from app.services.auth_service import auth_service
from app.services.chat_history_service import ChatHistoryError, chat_history_service
from app.services.image_ai_service import ImageAIError, image_ai_service
from app.services.model_service import ModelCatalogError, model_service
from app.services.rag_agent_service import rag_agent_service
from loguru import logger

router = APIRouter()

CHAT_IMAGE_DIR = Path("./uploads/chat_images")
ALLOWED_IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}
UPLOAD_READ_CHUNK_SIZE = 1024 * 1024

COMPACT_PROMPT_TEMPLATE_INSTRUCTIONS = {
    "character": (
        "任务类型：角色生成 / 人物设定 / 角色三视图\n"
        "请按角色生成模板输出，必须包含人物三视图设定卡要求；保留用户指定画风，未指定画风时默认真人写实风格。\n"
        "人物提示词必须写入「人设记忆点」；记忆点来自剧本依据或合理推断，并转化为外貌、眼神、发型、气质或姿态方向。\n"
        "主要角色必须符合 AI 真人短剧大众审美：自然耐看、五官协调、镜头友好、有辨识度；避免网红脸、整容感、模板脸、畸形怪脸。\n"
        "服装必须先判断角色主要身份，只跟随剧本年代、主要身份、阶层和处境；副业、技能、兴趣、隐藏身份、人物关系或剧情功能不得自动转化为服装元素。\n"
        "剧本未明确服装细节时，只写“符合某年代某主要身份的服装”，不要自行细化颜色、面料、鞋履、外套或配饰。"
    ),
    "scene": (
        "任务类型：场景提示词\n"
        "请按导演级空场景资产图模板输出，先锁定时间天气，再聚焦空间、尺度、前景/中景/远景、主体预留区、光影、色彩、构图和影像风格。\n"
        "最终标题使用【示例提示词：导演级空场景资产图】，最终提示词必须按【美学】【主题】【时间天气】【尺度】【前景】【中景】【主体预留区】【远景】【关键元素】【光影】【色彩】【镜头质感】【避免】【比例】输出。\n"
        "场景类只允许输出一套最终可复制提示词：在【示例提示词：导演级空场景资产图】下先写“正向提示词：”并包含上述字段，再写“负面提示词：”；不得在后面再次输出“## 正向提示词”“## 负面提示词”、压缩版、二次整理版或重复可复制区块。\n"
        "【回答自检】必须放在最终提示词区块之后，且不属于可复制提示词内容。\n"
        "冷开场、开场钩子、预告钩子、片头钩子和高能开场不作为单一场景生成；应选择其中具体地点或具体场景片段。\n"
        "除非用户明确要求近景、特写、局部或俯拍，默认使用全景/远景环境构图，完整展示空间结构和主要环境关系。\n"
        "场景提示词默认生成空场景资产图，不出现任何人物、角色、人体、背影、剪影、手部、面部或人群。\n"
        "必须保留主体预留区，说明后续人物入画的空置表演区、行动通道、视线焦点和镜头调度空间。\n"
        "如果原始需求包含人物动作，只能转写为环境状态、空间需求、主体预留区或痕迹，例如门半开、卷宗散落、雨水脚印、灯火未熄、桌前留出空椅，不得让人物出现在画面中。\n"
        "输出前必须先做空间逻辑建模：登记核心家具与关键道具数量，判断哪些物件唯一存在；同一核心家具跨越前景/中景/远景时，必须写明“同一张/同一组/同一件”，不得写成第二件同类家具。\n"
        "前景、中景、远景必须属于同一个连续空间，不是三个独立陈设区；除非用户明确要求桌面近景或特写，全景/远景空场景的前景不得把主书案、主桌、供桌、床、柜台等核心家具写成独立前景物件，可改用门框、柱脚、地面光影、书架侧边、屏风边缘或暗部墙角做框景。\n"
        "如果场景只有一张主书案/主桌/供桌/柜台，最终提示词必须明确“全场仅一张”，并在【关键元素】或【避免】中排除第二张桌、重复案几、额外工作台、副桌和重复桌面。\n"
        "输出前做同类物件重复检查：案桌/书桌/书案/桌面/工作台、烛台/灯具、床榻/坐榻、书架/柜架、门窗等在不同景别中反复出现时，必须判断是否为同一物件；若剧本未明确多件，自动合并为一件核心物件。\n"
        "文字类载体按剧情需要处理：牌匾、卷宗、报纸、招牌、门牌等可以作为场景道具存在，但不要强制模型生成可读文字；具体文字内容建议后期合成或以留白/模糊区域处理。\n"
        "【时间天气】必须单独输出，优先锁定用户或剧本给出的早、午、晚、白日、夜晚、黄昏、下雨、晴天、阴天等信息；不得把白日写成夜晚，不得把黄昏写成深夜/月光，不得把未写雨的场景写成雨夜。\n"
        "【比例】必须同时写场景图比例和视频比例；所有场景默认横版 16:9，核心视觉锚点、关键道具和主体预留区保持在横屏安全构图内，并保留中轴可裁切空间。\n"
        "必须锁定用户给出的时间、天气、地点和道具状态；不要把黄昏写成夜晚/月光/雨夜，不要把晴天写成雨天，不要把木窗写成玻璃窗，除非原文或用户明确要求。\n"
        "场景资产图任务不得输出【可选增强】、动态化建议、声音设计或视频镜头调度；这些只在用户明确要求视频分镜时输出。"
    ),
    "expression": (
        "任务类型：表情语气模板\n"
        "请按表情语气模板输出，只聚焦脸部表情、眼神和声音/台词语气。"
    ),
    "storyboard": (
        "任务类型：分镜脚本 / 镜头表格\n"
        "请按分镜脚本模板输出连续镜头，包含镜号、景别、镜头角度/运动和画面提示词。"
    ),
    "plot": (
        "任务类型：剧情策划 / 剧情结构\n"
        "请按剧情提示词模板输出剧情核心、人物关系、冲突推进、情绪弧线和结尾钩子；不要默认拆分镜。"
    ),
}


def _require_user(request: Request) -> dict[str, Any]:
    user = auth_service.get_user_by_token(request.cookies.get(config.auth_cookie_name))
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user


def _api_error(exc: ChatHistoryError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.status_code, "message": exc.message, "data": None},
    )


def _image_ai_error(exc: ImageAIError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.status_code, "message": exc.message, "data": None},
    )


def _model_error(exc: ModelCatalogError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.status_code, "message": exc.message, "data": None},
    )


def _model_metadata(model: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": model.get("modelId"),
        "modelDisplayName": model.get("displayName"),
        "modelProvider": model.get("provider"),
    }


def _public_model(model: dict[str, Any]) -> dict[str, Any]:
    return {
        "modelId": model.get("modelId"),
        "displayName": model.get("displayName"),
        "provider": model.get("provider"),
        "isDefault": bool(model.get("isDefault")),
    }


def _build_compact_model_question(
    *,
    question: str,
    prompt_template: str | None,
    fallback_model_question: str | None = None,
) -> str:
    """Use a compact task envelope instead of forwarding long UI templates."""
    clean_question = question.strip()
    template_key = (prompt_template or "").strip()
    instruction = COMPACT_PROMPT_TEMPLATE_INSTRUCTIONS.get(template_key)
    if not instruction:
        return clean_question
    fallback_question = (fallback_model_question or "").strip()
    if fallback_question.startswith("【剧本引用提示词生成任务】"):
        clean_question = fallback_question
    return f"{instruction}\n\n原始需求：\n{clean_question}"


async def _read_image_uploads(files: list[UploadFile]) -> list[dict[str, Any]]:
    if not files:
        raise HTTPException(status_code=400, detail="请先上传图片")
    if len(files) > config.image_upload_max_count:
        raise HTTPException(
            status_code=400,
            detail=f"一次最多上传 {config.image_upload_max_count} 张图片",
        )

    images = []
    for file in files:
        content = await _read_upload_with_limit(
            file,
            config.image_upload_max_size,
            f"单张图片不能超过 {config.image_upload_max_size // 1024 // 1024}MB",
        )
        mime_type = _detect_image_mime_type(content)
        if mime_type not in ALLOWED_IMAGE_MIME_TYPES:
            raise HTTPException(
                status_code=400,
                detail="图片格式仅支持 PNG、JPG、JPEG、WEBP",
            )
        if len(content) > config.image_upload_max_size:
            raise HTTPException(
                status_code=400,
                detail=f"单张图片不能超过 {config.image_upload_max_size // 1024 // 1024}MB",
            )
        images.append(
            {
                "filename": _sanitize_filename(file.filename or "image"),
                "mime_type": mime_type,
                "content": content,
                "size": len(content),
            }
        )
    return images


async def _read_upload_with_limit(
    file: UploadFile,
    max_size: int,
    detail: str,
) -> bytes:
    content = bytearray()
    while True:
        chunk = await file.read(UPLOAD_READ_CHUNK_SIZE)
        if not chunk:
            break
        if len(content) + len(chunk) > max_size:
            raise HTTPException(status_code=400, detail=detail)
        content.extend(chunk)
    return bytes(content)


def _detect_image_mime_type(content: bytes) -> str | None:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return None


def _save_chat_image(user_id: int, session_id: str, image: dict[str, Any]) -> Path:
    target_dir = CHAT_IMAGE_DIR / str(user_id) / session_id
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4().hex}_{image['filename']}"
    target_path = target_dir / filename
    target_path.write_bytes(image["content"])
    return target_path


def _sanitize_filename(filename: str) -> str:
    sanitized = filename.strip().replace(" ", "_") or "image"
    for char in ['\\', '/', ':', '*', '?', '"', '<', '>', '|']:
        sanitized = sanitized.replace(char, "_")
    return sanitized[:120]


def _format_generated_images_markdown(images: list[dict[str, Any]]) -> str:
    lines = ["图片已生成："]
    for index, image in enumerate(images, start=1):
        lines.append(f"\n![生成图 {index}]({image['url']})")
    return "\n".join(lines)


@router.get("/chat/model-options")
@router.get("/chat/models")
async def list_chat_models(request: Request):
    _require_user(request)
    try:
        models = model_service.list_available_models()
        default_model = model_service.default_model()
    except ModelCatalogError as exc:
        return _model_error(exc)
    return {
        "code": 200,
        "message": "success",
        "data": {
            "models": [_public_model(model) for model in models],
            "defaultModel": _public_model(default_model),
        },
    }


@router.get("/chat/sessions")
async def list_chat_sessions(request: Request):
    user = _require_user(request)
    sessions = chat_history_service.list_sessions(int(user["id"]))
    return {"code": 200, "message": "success", "data": {"sessions": sessions}}


@router.post("/chat/sessions")
async def create_chat_session(payload: ChatSessionCreateRequest, request: Request):
    user = _require_user(request)
    try:
        session = chat_history_service.create_session(
            user_id=int(user["id"]),
            session_id=payload.session_id,
            title=payload.title,
        )
        return {"code": 200, "message": "success", "data": {"session": session}}
    except ChatHistoryError as exc:
        return _api_error(exc)


@router.get("/chat/sessions/{session_id}/messages")
async def get_chat_messages(session_id: str, request: Request):
    user = _require_user(request)
    try:
        session, messages = chat_history_service.get_messages(int(user["id"]), session_id)
        return {
            "code": 200,
            "message": "success",
            "data": {"session": session, "messages": messages},
        }
    except ChatHistoryError as exc:
        return _api_error(exc)


@router.post("/chat/sessions/{session_id}/messages")
async def append_chat_message(
    session_id: str,
    payload: ChatMessageAppendRequest,
    request: Request,
):
    user = _require_user(request)
    try:
        message = chat_history_service.append_message(
            user_id=int(user["id"]),
            session_id=session_id,
            role=payload.role,
            content=payload.content,
            metadata=payload.metadata,
            client_message_id=payload.client_message_id,
            parent_message_id=payload.parent_message_id,
        )
        return {"code": 200, "message": "success", "data": {"message": message}}
    except ChatHistoryError as exc:
        return _api_error(exc)


@router.delete("/chat/sessions/{session_id}")
async def delete_chat_session(session_id: str, request: Request):
    user = _require_user(request)
    try:
        deleted = chat_history_service.delete_session(int(user["id"]), session_id)
        return {"code": 200, "message": "success", "data": {"deleted": deleted}}
    except ChatHistoryError as exc:
        return _api_error(exc)


@router.get("/chat/attachments/{attachment_id}/content")
async def get_attachment_content(attachment_id: int, request: Request):
    user = _require_user(request)
    attachment = chat_history_service.get_attachment(int(user["id"]), attachment_id)
    if not attachment or not attachment.get("filePath"):
        raise HTTPException(status_code=404, detail="Attachment not found")

    file_path = Path(str(attachment["filePath"]))
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Attachment file not found")

    return FileResponse(
        file_path,
        media_type=attachment.get("mimeType") or "application/octet-stream",
        filename=attachment.get("fileName") or file_path.name,
    )


@router.post("/chat_vision")
async def chat_vision(
    request: Request,
    session_id: str = Form(...),
    question: str = Form(""),
    client_message_id: str | None = Form(None),
    assistant_message_id: str | None = Form(None),
    files: list[UploadFile] = File(...),
):
    """Analyze uploaded images and persist the raw conversation plus attachments."""
    user = _require_user(request)
    user_id = int(user["id"])

    try:
        images = await _read_image_uploads(files)
        user_message = chat_history_service.append_message(
            user_id=user_id,
            session_id=session_id,
            role="user",
            content=question or "请分析这些图片",
            metadata={
                "mode": "vision",
                "imageCount": len(images),
            },
            client_message_id=client_message_id,
        )
        attachments = []
        for image in images:
            saved_path = _save_chat_image(user_id, session_id, image)
            attachment = chat_history_service.append_attachment(
                user_id=user_id,
                session_id=session_id,
                message_id=int(user_message["serverId"]),
                purpose="vision",
                file_name=image["filename"],
                file_path=str(saved_path),
                mime_type=image["mime_type"],
                file_size=image["size"],
            )
            attachments.append(attachment)

        answer = await image_ai_service.analyze_images(question, images)
        assistant_message = chat_history_service.append_message(
            user_id=user_id,
            session_id=session_id,
            role="assistant",
            content=answer,
            metadata={
                "mode": "vision",
                "prompt": question,
                "sourceImageCount": len(images),
            },
            client_message_id=assistant_message_id,
        )

        return {
            "code": 200,
            "message": "success",
            "data": {
                "success": True,
                "sessionId": session_id,
                "answer": answer,
                "userMessage": {**user_message, "attachments": attachments},
                "assistantMessage": assistant_message,
                "attachments": attachments,
            },
        }
    except ChatHistoryError as exc:
        return _api_error(exc)
    except ImageAIError as exc:
        return _image_ai_error(exc)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Vision chat API error: {exc}")
        return JSONResponse(
            status_code=500,
            content={"code": 500, "message": "图片分析失败，请稍后再试", "data": None},
        )


@router.post("/images/generate")
async def generate_image(payload: ImageGenerationRequest, request: Request):
    """Generate AI video reference images from a text prompt."""
    user = _require_user(request)
    user_id = int(user["id"])

    try:
        user_message = chat_history_service.append_message(
            user_id=user_id,
            session_id=payload.session_id,
            role="user",
            content=payload.prompt,
            metadata={
                "mode": "image_generation",
                "size": payload.size,
                "count": payload.count,
                "style": payload.style,
            },
            client_message_id=payload.client_message_id,
        )
        generation = await image_ai_service.generate_images(
            prompt=payload.prompt,
            size=payload.size,
            count=payload.count,
            style=payload.style,
        )
        answer = _format_generated_images_markdown(generation["images"])
        assistant_message = chat_history_service.append_message(
            user_id=user_id,
            session_id=payload.session_id,
            role="assistant",
            content=answer,
            metadata={
                "mode": "image_generation",
                "prompt": generation["prompt"],
                "taskId": generation["taskId"],
                "images": generation["images"],
            },
            client_message_id=payload.assistant_message_id,
        )
        attachments = []
        for image in generation["images"]:
            attachment = chat_history_service.append_attachment(
                user_id=user_id,
                session_id=payload.session_id,
                message_id=int(assistant_message["serverId"]),
                purpose="generated_image",
                file_name=f"generated-{image.get('index', len(attachments) + 1)}.png",
                file_url=image["url"],
                mime_type="image/png",
                metadata={
                    "taskId": generation["taskId"],
                    "prompt": generation["prompt"],
                    "size": payload.size,
                },
            )
            attachments.append(attachment)

        return {
            "code": 200,
            "message": "success",
            "data": {
                "success": True,
                "sessionId": payload.session_id,
                "answer": answer,
                "userMessage": user_message,
                "assistantMessage": {**assistant_message, "attachments": attachments},
                "images": generation["images"],
                "taskId": generation["taskId"],
            },
        }
    except ChatHistoryError as exc:
        return _api_error(exc)
    except ImageAIError as exc:
        return _image_ai_error(exc)
    except Exception as exc:
        logger.error(f"Image generation API error: {exc}")
        return JSONResponse(
            status_code=500,
            content={"code": 500, "message": "图片生成失败，请稍后再试", "data": None},
        )


@router.post("/chat")
async def chat(payload: ChatRequest, request: Request):
    """Non-streaming RAG chat with raw message persistence."""
    user = _require_user(request)
    user_id = int(user["id"])
    agent_thread_id = chat_history_service.agent_thread_id(user_id, payload.id)
    model_question = _build_compact_model_question(
        question=payload.question,
        prompt_template=payload.prompt_template,
        fallback_model_question=payload.model_question,
    )

    try:
        selected_model = model_service.resolve_chat_model(payload.model)
    except ModelCatalogError as exc:
        return _model_error(exc)

    usage_started_at = perf_counter()
    try:
        logger.info(f"[chat {payload.id}] received non-stream question")
        if not payload.is_retry:
            chat_history_service.append_message(
                user_id=user_id,
                session_id=payload.id,
                role="user",
                content=payload.question,
                metadata={"mode": "quick", **_model_metadata(selected_model)},
                client_message_id=payload.client_message_id,
            )

        answer = await rag_agent_service.query(
            model_question,
            session_id=agent_thread_id,
            model_name=selected_model["modelId"],
        )
        duration_ms = int((perf_counter() - usage_started_at) * 1000)
        model_service.record_usage(
            user_id=user_id,
            model=selected_model,
            session_id=payload.id,
            mode="quick",
            prompt_template=payload.prompt_template,
            success=True,
            duration_ms=duration_ms,
        )
        assistant_message = chat_history_service.append_message(
            user_id=user_id,
            session_id=payload.id,
            role="assistant",
            content=answer,
            metadata={
                "mode": "quick",
                "prompt": payload.question,
                "modelPrompt": model_question,
                "promptTemplate": payload.prompt_template,
                "retryOf": payload.retry_of,
                **_model_metadata(selected_model),
            },
            client_message_id=payload.assistant_message_id,
        )

        logger.info(f"[chat {payload.id}] non-stream response complete")
        return {
            "code": 200,
            "message": "success",
            "data": {
                "success": True,
                "sessionId": payload.id,
                "answer": answer,
                "assistantMessage": assistant_message,
                "model": _public_model(selected_model),
                "errorMessage": None,
            },
        }

    except ChatHistoryError as exc:
        return _api_error(exc)
    except Exception as exc:
        model_service.record_usage(
            user_id=user_id,
            model=selected_model,
            session_id=payload.id,
            mode="quick",
            prompt_template=payload.prompt_template,
            success=False,
            duration_ms=int((perf_counter() - usage_started_at) * 1000),
            error_message=str(exc),
        )
        logger.error(f"Chat API error: {exc}")
        return {
            "code": 500,
            "message": "error",
            "data": {
                "success": False,
                "answer": None,
                "errorMessage": "对话服务暂时不可用，请稍后再试",
            },
        }


@router.post("/chat_stream")
async def chat_stream(payload: ChatRequest, request: Request):
    """Streaming RAG chat with raw message persistence."""
    user = _require_user(request)
    user_id = int(user["id"])
    model_question = _build_compact_model_question(
        question=payload.question,
        prompt_template=payload.prompt_template,
        fallback_model_question=payload.model_question,
    )

    try:
        selected_model = model_service.resolve_chat_model(payload.model)
    except ModelCatalogError as exc:
        return _model_error(exc)

    try:
        agent_thread_id = chat_history_service.agent_thread_id(user_id, payload.id)
        if not payload.is_retry:
            chat_history_service.append_message(
                user_id=user_id,
                session_id=payload.id,
                role="user",
                content=payload.question,
                metadata={"mode": "stream", **_model_metadata(selected_model)},
                client_message_id=payload.client_message_id,
            )
    except ChatHistoryError as exc:
        return _api_error(exc)

    logger.info(f"[chat {payload.id}] received stream question")

    async def event_generator():
        usage_started_at = perf_counter()
        usage_recorded = False
        try:
            yield {
                "event": "message",
                "data": json.dumps(
                    {"type": "status", "data": "火宝正在检索知识库..."},
                    ensure_ascii=False,
                ),
            }

            final_answer = ""
            async for chunk in rag_agent_service.query_stream(
                model_question,
                session_id=agent_thread_id,
                model_name=selected_model["modelId"],
                emit_auxiliary_events=False,
            ):
                chunk_type = chunk.get("type", "unknown")
                chunk_data = chunk.get("data", None)

                if chunk_type == "content":
                    yield {
                        "event": "message",
                        "data": json.dumps(
                            {"type": "content", "data": chunk_data},
                            ensure_ascii=False,
                        ),
                    }
                elif chunk_type == "complete":
                    final_answer = (
                        chunk_data.get("answer", "") if isinstance(chunk_data, dict) else ""
                    )
                    assistant_message = chat_history_service.append_message(
                        user_id=user_id,
                        session_id=payload.id,
                        role="assistant",
                        content=final_answer,
                        metadata={
                            "mode": "stream",
                            "prompt": payload.question,
                            "modelPrompt": model_question,
                            "promptTemplate": payload.prompt_template,
                            "retryOf": payload.retry_of,
                            **_model_metadata(selected_model),
                        },
                        client_message_id=payload.assistant_message_id,
                    )
                    model_service.record_usage(
                        user_id=user_id,
                        model=selected_model,
                        session_id=payload.id,
                        mode="stream",
                        prompt_template=payload.prompt_template,
                        success=True,
                        duration_ms=int((perf_counter() - usage_started_at) * 1000),
                    )
                    usage_recorded = True
                    data = dict(chunk_data) if isinstance(chunk_data, dict) else {}
                    data["assistantMessage"] = assistant_message
                    data["model"] = _public_model(selected_model)
                    yield {
                        "event": "message",
                        "data": json.dumps({"type": "done", "data": data}, ensure_ascii=False),
                    }
                elif chunk_type == "error":
                    yield {
                        "event": "message",
                        "data": json.dumps(
                            {"type": "error", "data": str(chunk_data)},
                            ensure_ascii=False,
                        ),
                    }

            logger.info(f"[chat {payload.id}] stream response complete")

        except asyncio.CancelledError:
            if not usage_recorded:
                model_service.record_usage(
                    user_id=user_id,
                    model=selected_model,
                    session_id=payload.id,
                    mode="stream",
                    prompt_template=payload.prompt_template,
                    success=False,
                    duration_ms=int((perf_counter() - usage_started_at) * 1000),
                    error_message="client disconnected",
                    metadata={"cancelled": True},
                )
            logger.info(f"[chat {payload.id}] stream cancelled by client")
            raise
        except Exception as exc:
            if not usage_recorded:
                model_service.record_usage(
                    user_id=user_id,
                    model=selected_model,
                    session_id=payload.id,
                    mode="stream",
                    prompt_template=payload.prompt_template,
                    success=False,
                    duration_ms=int((perf_counter() - usage_started_at) * 1000),
                    error_message=str(exc),
                )
            logger.error(f"Streaming chat API error: {exc}")
            yield {
                "event": "message",
                "data": json.dumps(
                    {"type": "error", "data": "对话服务暂时不可用，请稍后再试"},
                    ensure_ascii=False,
                ),
            }

    return EventSourceResponse(
        event_generator(),
        ping=10,
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/chat/clear", response_model=ApiResponse)
async def clear_session(payload: ClearRequest, request: Request):
    user = _require_user(request)
    user_id = int(user["id"])
    try:
        agent_thread_id = chat_history_service.agent_thread_id(user_id, payload.session_id)
        memory_cleared = rag_agent_service.clear_session(agent_thread_id)
        db_cleared = chat_history_service.clear_session(user_id, payload.session_id)
        success = memory_cleared or db_cleared
        return ApiResponse(
            status="success" if success else "error",
            message="Session cleared" if success else "Session clear failed",
            data=None,
        )
    except ChatHistoryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    except Exception as exc:
        logger.error(f"Clear chat session error: {exc}")
        raise HTTPException(status_code=500, detail="清空会话失败，请稍后再试") from exc


@router.get("/chat/session/{session_id}", response_model=SessionInfoResponse)
async def get_session_info(session_id: str, request: Request) -> SessionInfoResponse:
    user = _require_user(request)
    user_id = int(user["id"])
    try:
        _, messages = chat_history_service.get_messages(user_id, session_id)
        return SessionInfoResponse(
            session_id=session_id,
            message_count=len(messages),
            history=messages,
        )
    except ChatHistoryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    except Exception as exc:
        logger.error(f"Get chat session info error: {exc}")
        raise HTTPException(status_code=500, detail="获取会话信息失败，请稍后再试") from exc
