"""Admin AI model whitelist APIs."""

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app.config import config
from app.models.admin import AiModelCreateRequest, AiModelEnabledRequest, AiModelUpdateRequest
from app.services.admin_user_service import AdminError
from app.services.auth_service import auth_service
from app.services.model_service import model_service

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


@router.get("/model-catalog")
@router.get("/models")
async def list_models(
    request: Request,
    enabled: bool | None = None,
    keyword: str | None = None,
    include_deleted: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
):
    try:
        actor = _current_admin(request)
        data = model_service.list_models(
            actor,
            enabled=enabled,
            keyword=keyword,
            include_deleted=include_deleted,
            page=page,
            page_size=page_size,
        )
        return {"code": 200, "message": "success", "data": data}
    except AdminError as exc:
        return _error_response(exc)


@router.get("/model-catalog/{model_pk}")
@router.get("/models/{model_pk}")
async def get_model(model_pk: int, request: Request):
    try:
        actor = _current_admin(request)
        data = model_service.get_model(actor, model_pk)
        return {"code": 200, "message": "success", "data": data}
    except AdminError as exc:
        return _error_response(exc)


@router.post("/model-catalog")
@router.post("/models")
async def create_model(payload: AiModelCreateRequest, request: Request):
    try:
        actor = _current_admin(request)
        data = model_service.create_model(
            actor,
            model_id=payload.model_id,
            display_name=payload.display_name,
            provider=payload.provider,
            enabled=payload.enabled,
            is_default=payload.is_default,
            sort_order=payload.sort_order,
            min_membership_level=payload.min_membership_level,
            access_scope=payload.access_scope,
            remark=payload.remark,
        )
        return {"code": 200, "message": "success", "data": data}
    except AdminError as exc:
        return _error_response(exc)


@router.put("/model-catalog/{model_pk}")
@router.put("/models/{model_pk}")
async def update_model(model_pk: int, payload: AiModelUpdateRequest, request: Request):
    try:
        actor = _current_admin(request)
        data = model_service.update_model(
            actor,
            model_pk,
            model_id=payload.model_id,
            display_name=payload.display_name,
            provider=payload.provider,
            enabled=payload.enabled,
            is_default=payload.is_default,
            sort_order=payload.sort_order,
            min_membership_level=payload.min_membership_level,
            access_scope=payload.access_scope,
            remark=payload.remark,
        )
        return {"code": 200, "message": "success", "data": data}
    except AdminError as exc:
        return _error_response(exc)


@router.patch("/model-catalog/{model_pk}/enabled")
@router.patch("/models/{model_pk}/enabled")
async def set_model_enabled(model_pk: int, payload: AiModelEnabledRequest, request: Request):
    try:
        actor = _current_admin(request)
        data = model_service.set_enabled(actor, model_pk, payload.enabled)
        return {"code": 200, "message": "success", "data": data}
    except AdminError as exc:
        return _error_response(exc)


@router.patch("/model-catalog/{model_pk}/default")
@router.patch("/models/{model_pk}/default")
async def set_default_model(model_pk: int, request: Request):
    try:
        actor = _current_admin(request)
        data = model_service.set_default(actor, model_pk)
        return {"code": 200, "message": "success", "data": data}
    except AdminError as exc:
        return _error_response(exc)


@router.delete("/model-catalog/{model_pk}")
@router.delete("/models/{model_pk}")
async def delete_model(model_pk: int, request: Request):
    try:
        actor = _current_admin(request)
        data = model_service.delete_model(actor, model_pk)
        return {"code": 200, "message": "success", "data": data}
    except AdminError as exc:
        return _error_response(exc)


@router.get("/model-catalog/{model_pk}/usage")
@router.get("/models/{model_pk}/usage")
async def model_usage_detail(
    model_pk: int,
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
):
    try:
        actor = _current_admin(request)
        data = model_service.usage_detail(actor, model_pk, days=days)
        return {"code": 200, "message": "success", "data": data}
    except AdminError as exc:
        return _error_response(exc)
