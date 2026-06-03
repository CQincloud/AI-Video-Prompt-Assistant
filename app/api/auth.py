"""Phone-code authentication API."""

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from app.config import config
from app.models.auth import LoginRequest, SendCodeRequest
from app.api.request_utils import get_client_ip, should_use_secure_auth_cookie
from app.services.auth_service import AuthError, auth_service
from loguru import logger

router = APIRouter()


@router.post("/auth/send-code")
async def send_code(payload: SendCodeRequest, request: Request):
    try:
        data = auth_service.send_code(payload.phone, ip=get_client_ip(request))
        return {"code": 200, "message": "验证码已发送", "data": data}
    except AuthError as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.status_code, "message": exc.message, "data": None},
        )
    except Exception as exc:
        logger.exception(f"Send code API error: {exc}")
        return JSONResponse(
            status_code=500,
            content={"code": 500, "message": "验证码发送失败，请稍后再试", "data": None},
        )


@router.post("/auth/login")
async def login(payload: LoginRequest, request: Request, response: Response):
    try:
        token, user = auth_service.login_with_code(
            payload.phone,
            payload.code,
            ip=get_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
        response.set_cookie(
            key=config.auth_cookie_name,
            value=token,
            max_age=config.auth_session_ttl_hours * 3600,
            httponly=True,
            secure=should_use_secure_auth_cookie(request),
            samesite="lax",
            path="/",
        )
        return {"code": 200, "message": "登录成功", "data": {"user": user}}
    except AuthError as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.status_code, "message": exc.message, "data": None},
        )
    except Exception as exc:
        logger.exception(f"Login API error: {exc}")
        return JSONResponse(
            status_code=500,
            content={"code": 500, "message": "登录失败，请稍后再试", "data": None},
        )


@router.get("/auth/me")
async def me(request: Request):
    user = auth_service.get_user_by_token(request.cookies.get(config.auth_cookie_name))
    if not user:
        return JSONResponse(status_code=401, content={"code": 401, "message": "未登录", "data": None})
    return {"code": 200, "message": "success", "data": {"user": user}}


@router.post("/auth/logout")
async def logout(request: Request, response: Response):
    auth_service.logout(request.cookies.get(config.auth_cookie_name))
    response.delete_cookie(
        config.auth_cookie_name,
        path="/",
        secure=should_use_secure_auth_cookie(request),
        httponly=True,
        samesite="lax",
    )
    return {"code": 200, "message": "已退出登录", "data": None}
