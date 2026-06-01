"""Admin user-management APIs."""

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app.config import config
from app.models.admin import (
    AdminPointsAdjustmentRequest,
    AdminUserStatusRequest,
    AdminUserUpdateRequest,
)
from app.services.admin_user_service import AdminError, admin_user_service
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


@router.get("/users")
async def list_users(
    request: Request,
    mobile: str | None = None,
    role: str | None = Query(default=None, pattern="^(user|admin|super_admin)$"),
    status: int | None = Query(default=None, ge=0, le=1),
    level: str | None = Query(default=None, pattern="^(normal|premium|super)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
):
    try:
        actor = _current_admin(request)
        data = admin_user_service.list_users(
            actor,
            mobile=mobile,
            role=role,
            status=status,
            level=level,
            page=page,
            page_size=page_size,
        )
        return {"code": 200, "message": "success", "data": data}
    except AdminError as exc:
        return _error_response(exc)


@router.get("/users/{user_id}")
async def get_user(user_id: int, request: Request):
    try:
        actor = _current_admin(request)
        data = admin_user_service.get_user(actor, user_id)
        return {"code": 200, "message": "success", "data": data}
    except AdminError as exc:
        return _error_response(exc)


@router.put("/users/{user_id}")
async def update_user(user_id: int, payload: AdminUserUpdateRequest, request: Request):
    try:
        actor = _current_admin(request)
        data = admin_user_service.update_user(actor, user_id, payload)
        return {"code": 200, "message": "success", "data": data}
    except AdminError as exc:
        return _error_response(exc)


@router.patch("/users/{user_id}/status")
async def update_status(user_id: int, payload: AdminUserStatusRequest, request: Request):
    try:
        actor = _current_admin(request)
        data = admin_user_service.update_status(actor, user_id, payload.status)
        return {"code": 200, "message": "success", "data": data}
    except AdminError as exc:
        return _error_response(exc)


@router.post("/users/{user_id}/points")
async def adjust_points(user_id: int, payload: AdminPointsAdjustmentRequest, request: Request):
    try:
        actor = _current_admin(request)
        data = admin_user_service.adjust_points(actor, user_id, payload)
        return {"code": 200, "message": "success", "data": data}
    except AdminError as exc:
        return _error_response(exc)


@router.get("/users/{user_id}/points-logs")
async def list_points_logs(
    user_id: int,
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
):
    try:
        actor = _current_admin(request)
        data = admin_user_service.list_points_logs(
            actor,
            user_id,
            page=page,
            page_size=page_size,
        )
        return {"code": 200, "message": "success", "data": data}
    except AdminError as exc:
        return _error_response(exc)
