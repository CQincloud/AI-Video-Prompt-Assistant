"""Admin system prompt APIs."""

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app.config import config
from app.models.admin import (
    SystemPromptCreateRequest,
    SystemPromptTestRequest,
    SystemPromptUpdateRequest,
)
from app.services.admin_prompt_service import admin_prompt_service
from app.services.admin_user_service import AdminError
from app.services.auth_service import auth_service

router = APIRouter()


def _current_admin(request: Request) -> dict:
    user = auth_service.get_user_by_token(request.cookies.get(config.auth_cookie_name))
    if not user:
        raise AdminError("未登录", status_code=401)
    if user["role"] not in {"admin", "super_admin"}:
        raise AdminError("无后台权限", status_code=403)
    return user


def _error_response(exc: AdminError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.status_code, "message": exc.message, "data": None},
    )


@router.get("/prompts")
async def list_prompts(
    request: Request,
    prompt_type: str | None = None,
    enabled: bool | None = None,
    keyword: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
):
    try:
        actor = _current_admin(request)
        data = admin_prompt_service.list_prompts(
            actor,
            prompt_type=prompt_type,
            enabled=enabled,
            keyword=keyword,
            page=page,
            page_size=page_size,
        )
        return {"code": 200, "message": "success", "data": data}
    except AdminError as exc:
        return _error_response(exc)


@router.get("/prompts/{prompt_id}")
async def get_prompt(prompt_id: int, request: Request):
    try:
        actor = _current_admin(request)
        data = admin_prompt_service.get_prompt(actor, prompt_id)
        return {"code": 200, "message": "success", "data": data}
    except AdminError as exc:
        return _error_response(exc)


@router.post("/prompts")
async def create_prompt(payload: SystemPromptCreateRequest, request: Request):
    try:
        actor = _current_admin(request)
        data = admin_prompt_service.create_prompt(
            actor,
            prompt_key=payload.prompt_key,
            prompt_name=payload.prompt_name,
            prompt_type=payload.prompt_type,
            content=payload.content,
            remark=payload.remark,
            enabled=payload.enabled,
        )
        return {"code": 200, "message": "success", "data": data}
    except AdminError as exc:
        return _error_response(exc)


@router.put("/prompts/{prompt_id}")
async def update_prompt(prompt_id: int, payload: SystemPromptUpdateRequest, request: Request):
    try:
        actor = _current_admin(request)
        data = admin_prompt_service.update_prompt(
            actor,
            prompt_id,
            prompt_name=payload.prompt_name,
            prompt_type=payload.prompt_type,
            content=payload.content,
            remark=payload.remark,
        )
        return {"code": 200, "message": "success", "data": data}
    except AdminError as exc:
        return _error_response(exc)


@router.post("/prompts/{prompt_id}/copy")
async def copy_prompt(prompt_id: int, request: Request):
    try:
        actor = _current_admin(request)
        data = admin_prompt_service.copy_prompt(actor, prompt_id)
        return {"code": 200, "message": "success", "data": data}
    except AdminError as exc:
        return _error_response(exc)


@router.patch("/prompts/{prompt_id}/enable")
async def enable_prompt(prompt_id: int, request: Request):
    try:
        actor = _current_admin(request)
        data = admin_prompt_service.enable_prompt(actor, prompt_id)
        return {"code": 200, "message": "success", "data": data}
    except AdminError as exc:
        return _error_response(exc)


@router.patch("/prompts/{prompt_id}/disable")
async def disable_prompt(prompt_id: int, request: Request):
    try:
        actor = _current_admin(request)
        data = admin_prompt_service.disable_prompt(actor, prompt_id)
        return {"code": 200, "message": "success", "data": data}
    except AdminError as exc:
        return _error_response(exc)


@router.get("/prompts/key/{prompt_key}/versions")
async def list_versions(prompt_key: str, request: Request):
    try:
        actor = _current_admin(request)
        data = admin_prompt_service.versions(actor, prompt_key)
        return {"code": 200, "message": "success", "data": data}
    except AdminError as exc:
        return _error_response(exc)


@router.post("/prompts/test")
async def test_prompt(payload: SystemPromptTestRequest, request: Request):
    try:
        actor = _current_admin(request)
        data = admin_prompt_service.test_prompt(actor, payload.prompt_key, payload.test_input)
        return {"code": 200, "message": "success", "data": data}
    except AdminError as exc:
        return _error_response(exc)
