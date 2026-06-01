"""FastAPI application entrypoint."""

import asyncio
from contextlib import asynccontextmanager
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from app.api import admin_auth, admin_kb, admin_prompts, admin_users, aiops, auth, chat, file, health
from app.config import config
from app.core.database import close_connection_pool, init_connection_pool
from app.core.migrations import (
    MigrationError,
    apply_pending_migrations,
    assert_database_migrations_current,
)
from app.core.milvus_client import MilvusSchemaMismatchError, milvus_manager
from app.services.auth_service import auth_service
from app.services.chat_history_service import chat_history_service
from app.services.rag_agent_service import rag_agent_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    warmup_task: asyncio.Task | None = None

    logger.info("=" * 60)
    logger.info(f"{config.app_name} v{config.app_version} starting...")
    logger.info(f"Environment: {'production' if config.is_production else 'development'}")
    logger.info(f"Listen: http://{config.host}:{config.port}")
    if config.docs_enabled:
        logger.info(f"Docs: http://{config.host}:{config.port}/docs")

    try:
        logger.info("Initializing database connection pool...")
        init_connection_pool()
    except Exception as exc:
        if config.is_production:
            logger.error(f"Database pool initialization failed: {exc}")
            raise
        logger.warning(f"Database pool was not initialized during startup: {exc}")

    migrations_verified = False
    try:
        if config.database_auto_migrate_on_startup:
            logger.info("Applying pending database migrations...")
            applied = apply_pending_migrations()
            if applied:
                logger.info(
                    "Applied database migrations: "
                    + ", ".join(f"{migration.version}_{migration.name}" for migration in applied)
                )
            else:
                logger.info("Database migrations are already current")
        elif config.database_validate_migrations_on_startup:
            logger.info("Checking database migrations...")
            assert_database_migrations_current()
            logger.info("Database migrations are current")
        else:
            logger.warning("Database migration validation is disabled")
        migrations_verified = True
        auth_service.mark_schema_ready()
    except MigrationError as exc:
        if config.is_production:
            logger.error(f"Database migrations are not ready: {exc}")
            raise
        logger.warning(f"Database migrations were not verified during startup: {exc}")

    try:
        logger.info("Connecting Milvus...")
        milvus_manager.connect()
        logger.info("Milvus connected")
    except MilvusSchemaMismatchError as exc:
        logger.error(f"Milvus schema mismatch during startup: {exc}")
        raise
    except RuntimeError as exc:
        logger.warning(f"Milvus is unavailable during startup; vector features will retry lazily: {exc}")
    if config.database_allow_untracked_schema_ensure and not migrations_verified:
        try:
            logger.warning("Using untracked runtime schema ensure for auth/chat tables")
            auth_service.ensure_schema()
            chat_history_service.ensure_schema()
        except Exception as exc:
            if config.is_production:
                logger.error(f"Runtime schema initialization failed: {exc}")
                raise
            logger.warning(f"Runtime schema initialization failed: {exc}")

    if config.startup_warmup_enabled:
        async def _run_startup_warmup() -> None:
            try:
                logger.info("Starting background RAG warmup...")
                await rag_agent_service.warmup()
            except Exception as exc:
                logger.warning(f"Background RAG warmup failed: {exc}")

        warmup_task = asyncio.create_task(_run_startup_warmup())
    logger.info("=" * 60)

    yield

    if warmup_task and not warmup_task.done():
        warmup_task.cancel()
        try:
            await warmup_task
        except asyncio.CancelledError:
            logger.info("Background RAG warmup task cancelled during shutdown")

    logger.info("Closing Milvus connection...")
    milvus_manager.close()
    logger.info("Closing database connection pool...")
    close_connection_pool()
    logger.info(f"{config.app_name} stopped")


app = FastAPI(
    title=config.app_name,
    version=config.app_version,
    description="AI video prompt knowledge-base assistant",
    lifespan=lifespan,
    docs_url="/docs" if config.docs_enabled else None,
    redoc_url="/redoc" if config.docs_enabled else None,
    openapi_url="/openapi.json" if config.docs_enabled else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def protect_api_routes(request: Request, call_next):
    """Require login for app APIs except auth endpoints."""
    path = request.url.path
    if path.startswith("/api/aiops"):
        user = auth_service.get_user_by_token(request.cookies.get(config.auth_cookie_name))
        if not user:
            return JSONResponse(
                status_code=401,
                content={"code": 401, "message": "请先登录", "data": None},
            )
        if user["role"] != "super_admin":
            return JSONResponse(
                status_code=403,
                content={"code": 403, "message": "仅超级管理员可使用 AIOps 功能", "data": None},
            )
    elif path.startswith("/api/admin/") and not path.startswith("/api/admin/auth"):
        user = auth_service.get_user_by_token(request.cookies.get(config.auth_cookie_name))
        if not user:
            return JSONResponse(
                status_code=401,
                content={"code": 401, "message": "请先登录", "data": None},
            )
        if user["role"] not in {"admin", "super_admin"}:
            return JSONResponse(
                status_code=403,
                content={"code": 403, "message": "无后台权限", "data": None},
            )
    elif (
        path.startswith("/api/")
        and not path.startswith("/api/auth")
        and not path.startswith("/api/admin/auth")
    ):
        user = auth_service.get_user_by_token(request.cookies.get(config.auth_cookie_name))
        if not user:
            return JSONResponse(
                status_code=401,
                content={"code": 401, "message": "请先登录", "data": None},
            )
    return await call_next(request)


@app.middleware("http")
async def add_static_cache_headers(request: Request, call_next):
    """Cache versioned static assets aggressively for faster repeat visits."""
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/static/") and response.status_code == 200:
        if request.query_params.get("v") or path.startswith("/static/assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "public, max-age=3600"
    return response


app.include_router(health.router, tags=["健康检查"])
app.include_router(auth.router, prefix="/api", tags=["登录认证"])
app.include_router(admin_auth.router, prefix="/api/admin", tags=["后台认证"])
app.include_router(admin_users.router, prefix="/api/admin", tags=["后台用户管理"])
app.include_router(admin_kb.router, prefix="/api/admin", tags=["后台知识库管理"])
app.include_router(admin_prompts.router, prefix="/api/admin", tags=["后台提示词管理"])
app.include_router(chat.router, prefix="/api", tags=["对话"])
app.include_router(file.router, prefix="/api", tags=["文件管理"])
app.include_router(aiops.router, prefix="/api", tags=["AIOps智能运维"])

static_dir = "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/login")
async def login_page():
    login_path = os.path.join(static_dir, "login.html")
    if os.path.exists(login_path):
        return FileResponse(login_path)
    return RedirectResponse(url="/")


@app.get("/admin/login")
async def admin_login_page(request: Request):
    user = auth_service.get_user_by_token(request.cookies.get(config.auth_cookie_name))
    if user and user["role"] in {"admin", "super_admin"}:
        return RedirectResponse(url="/admin/users")
    if user:
        return RedirectResponse(url="/")

    login_path = os.path.join(static_dir, "admin-login.html")
    if os.path.exists(login_path):
        return FileResponse(login_path)
    return RedirectResponse(url="/login")


@app.get("/admin/users")
async def admin_users_page(request: Request):
    user = auth_service.get_user_by_token(request.cookies.get(config.auth_cookie_name))
    if not user or user["role"] not in {"admin", "super_admin"}:
        return RedirectResponse(url="/admin/login")

    page_path = os.path.join(static_dir, "admin-users.html")
    if os.path.exists(page_path):
        return FileResponse(page_path)
    return RedirectResponse(url="/")


@app.get("/admin/kb-files")
async def admin_kb_files_page(request: Request):
    user = auth_service.get_user_by_token(request.cookies.get(config.auth_cookie_name))
    if not user or user["role"] not in {"admin", "super_admin"}:
        return RedirectResponse(url="/admin/login")

    page_path = os.path.join(static_dir, "admin-users.html")
    if os.path.exists(page_path):
        return FileResponse(page_path)
    return RedirectResponse(url="/")


@app.get("/admin/prompts")
async def admin_prompts_page(request: Request):
    user = auth_service.get_user_by_token(request.cookies.get(config.auth_cookie_name))
    if not user or user["role"] not in {"admin", "super_admin"}:
        return RedirectResponse(url="/admin/login")

    page_path = os.path.join(static_dir, "admin-users.html")
    if os.path.exists(page_path):
        return FileResponse(page_path)
    return RedirectResponse(url="/")


@app.get("/")
async def root(request: Request):
    user = auth_service.get_user_by_token(request.cookies.get(config.auth_cookie_name))
    if not user:
        return RedirectResponse(url="/login")

    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {
        "message": f"Welcome to {config.app_name} API",
        "version": config.app_version,
        "docs": "/docs",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=config.host,
        port=config.port,
        reload=config.debug,
        log_level="info",
    )
