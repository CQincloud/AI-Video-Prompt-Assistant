"""Script-referenced prompt generation APIs."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import BaseModel, Field

from app.config import config
from app.services.auth_service import auth_service
from app.services.script_prompt_service import (
    ScriptPromptError,
    ScriptPromptRequest,
    script_prompt_service,
)

router = APIRouter()
MAX_SCRIPT_UPLOAD_SIZE = 15 * 1024 * 1024


class ScriptPromptParseRequest(BaseModel):
    script_text: str = Field(..., alias="scriptText")
    title: str | None = None

    class Config:
        populate_by_name = True


class ScriptPromptReferenceRequest(BaseModel):
    parsed_script: dict[str, Any] | None = Field(None, alias="parsedScript")
    script_text: str | None = Field(None, alias="scriptText")
    title: str | None = None
    generation_type: Literal["character", "scene"] = Field("character", alias="generationType")
    target: str = ""
    platform: str = "general"
    user_requirement: str = Field("", alias="userRequirement")
    include_english: bool = Field(False, alias="includeEnglish")

    class Config:
        populate_by_name = True


def _require_user(request: Request) -> dict[str, Any]:
    user = auth_service.get_user_by_token(request.cookies.get(config.auth_cookie_name))
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user


def _service_error(exc: ScriptPromptError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.status_code, "message": exc.message, "data": None},
    )


async def _read_upload_with_limit(file: UploadFile) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_SCRIPT_UPLOAD_SIZE:
            raise ScriptPromptError("单个剧本文档请控制在 15MB 以内")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/script-prompts/upload")
async def upload_script_prompt_file(request: Request, file: UploadFile = File(...)):
    _require_user(request)
    try:
        content = await _read_upload_with_limit(file)
        extracted = script_prompt_service.extract_script_text_from_file(file.filename or "", content)
        return {
            "code": 200,
            "message": "success",
            "data": {
                "filename": extracted["filename"],
                "title": extracted["title"],
                "extension": extracted["extension"],
                "size": len(content),
                "text": extracted["text"],
            },
        }
    except ScriptPromptError as exc:
        return _service_error(exc)
    except Exception as exc:
        logger.error(f"Script upload API error: {exc}")
        return JSONResponse(
            status_code=500,
            content={"code": 500, "message": "剧本文档读取失败，请稍后再试", "data": None},
        )


@router.post("/script-prompts/parse")
async def parse_script_prompt(payload: ScriptPromptParseRequest, request: Request):
    _require_user(request)
    try:
        parsed = script_prompt_service.parse_script(payload.script_text, title=payload.title)
        return {
            "code": 200,
            "message": "success",
            "data": {"script": parsed},
        }
    except ScriptPromptError as exc:
        return _service_error(exc)
    except Exception as exc:
        logger.error(f"Script parse API error: {exc}")
        return JSONResponse(
            status_code=500,
            content={"code": 500, "message": "剧本解析失败，请稍后再试", "data": None},
        )


@router.post("/script-prompts/references")
async def get_script_prompt_references(payload: ScriptPromptReferenceRequest, request: Request):
    _require_user(request)
    try:
        parsed_script = payload.parsed_script
        if not parsed_script:
            if not payload.script_text:
                raise ScriptPromptError("请先粘贴并解析剧本")
            parsed_script = script_prompt_service.parse_script(payload.script_text, title=payload.title)
        prompt_request = ScriptPromptRequest(
            generation_type=payload.generation_type,
            target=payload.target,
            platform=payload.platform or "general",
            user_requirement=payload.user_requirement,
            include_english=payload.include_english,
        )
        script_prompt_service.validate_reference_request(parsed_script, prompt_request)
        references = script_prompt_service.retrieve_references(parsed_script, prompt_request)
        return {
            "code": 200,
            "message": "success",
            "data": {
                "script": {
                    "script_id": parsed_script.get("script_id"),
                    "title": parsed_script.get("title"),
                    "stats": parsed_script.get("stats") or {},
                    "visualContext": parsed_script.get("visual_context") or {},
                },
                "generationType": payload.generation_type,
                "target": payload.target,
                "platform": payload.platform or "general",
                "includeEnglish": payload.include_english,
                "references": references,
            },
        }
    except ScriptPromptError as exc:
        return _service_error(exc)
    except Exception as exc:
        logger.error(f"Script prompt references API error: {exc}")
        return JSONResponse(
            status_code=500,
            content={"code": 500, "message": "剧本引用检索失败，请稍后再试", "data": None},
        )
