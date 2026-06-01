"""Admin knowledge-base file APIs."""

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import JSONResponse

from app.config import config
from app.models.admin import (
    KbDocumentContentUpdateRequest,
    KbDocumentEnabledRequest,
    KbDocumentUpdateRequest,
    KbSearchTestRequest,
)
from app.services.admin_kb_service import admin_kb_service
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


@router.post("/kb/documents/upload")
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    category: str = Form(default="default"),
    description: str | None = Form(default=None),
):
    try:
        actor = _current_admin(request)
        content = await file.read()
        data = admin_kb_service.upload_document(
            actor,
            original_file_name=file.filename or "document.txt",
            content_type=file.content_type,
            content=content,
            category=category,
            description=description,
        )
        return {"code": 200, "message": "success", "data": data}
    except AdminError as exc:
        return _error_response(exc)


@router.post("/kb/documents/import-existing")
async def import_existing_documents(request: Request, reindex: bool = Query(default=False)):
    try:
        actor = _current_admin(request)
        data = admin_kb_service.import_existing_documents(actor, reindex=reindex)
        return {"code": 200, "message": "success", "data": data}
    except AdminError as exc:
        return _error_response(exc)


@router.get("/kb/documents")
async def list_documents(
    request: Request,
    keyword: str | None = None,
    category: str | None = None,
    vector_status: str | None = Query(default=None, pattern="^(pending|processing|success|failed)$"),
    enabled: bool | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
):
    try:
        actor = _current_admin(request)
        data = admin_kb_service.list_documents(
            actor,
            keyword=keyword,
            category=category,
            vector_status=vector_status,
            enabled=enabled,
            page=page,
            page_size=page_size,
        )
        return {"code": 200, "message": "success", "data": data}
    except AdminError as exc:
        return _error_response(exc)


@router.get("/kb/documents/{document_id}")
async def get_document(document_id: int, request: Request):
    try:
        actor = _current_admin(request)
        data = admin_kb_service.get_document(actor, document_id)
        return {"code": 200, "message": "success", "data": data}
    except AdminError as exc:
        return _error_response(exc)


@router.get("/kb/documents/{document_id}/content")
async def get_document_content(document_id: int, request: Request):
    try:
        actor = _current_admin(request)
        data = admin_kb_service.get_document_content(actor, document_id)
        return {"code": 200, "message": "success", "data": data}
    except AdminError as exc:
        return _error_response(exc)


@router.put("/kb/documents/{document_id}")
async def update_document(document_id: int, payload: KbDocumentUpdateRequest, request: Request):
    try:
        actor = _current_admin(request)
        data = admin_kb_service.update_document(
            actor,
            document_id,
            title=payload.title,
            category=payload.category,
            description=payload.description,
        )
        return {"code": 200, "message": "success", "data": data}
    except AdminError as exc:
        return _error_response(exc)


@router.put("/kb/documents/{document_id}/content")
async def update_document_content(
    document_id: int,
    payload: KbDocumentContentUpdateRequest,
    request: Request,
):
    try:
        actor = _current_admin(request)
        data = admin_kb_service.update_document_content(
            actor,
            document_id,
            content=payload.content,
            reindex=payload.reindex,
        )
        return {"code": 200, "message": "success", "data": data}
    except AdminError as exc:
        return _error_response(exc)


@router.patch("/kb/documents/{document_id}/enabled")
async def update_enabled(document_id: int, payload: KbDocumentEnabledRequest, request: Request):
    try:
        actor = _current_admin(request)
        data = admin_kb_service.set_enabled(actor, document_id, payload.enabled)
        return {"code": 200, "message": "success", "data": data}
    except AdminError as exc:
        return _error_response(exc)


@router.post("/kb/documents/{document_id}/reindex")
async def reindex_document(document_id: int, request: Request):
    try:
        actor = _current_admin(request)
        data = admin_kb_service.index_document(actor, document_id, task_type="reindex")
        return {"code": 200, "message": "success", "data": data}
    except AdminError as exc:
        return _error_response(exc)


@router.delete("/kb/documents/{document_id}")
async def delete_document(document_id: int, request: Request):
    try:
        actor = _current_admin(request)
        data = admin_kb_service.soft_delete(actor, document_id)
        return {"code": 200, "message": "success", "data": data}
    except AdminError as exc:
        return _error_response(exc)


@router.get("/kb/documents/{document_id}/chunks")
async def list_chunks(
    document_id: int,
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    try:
        actor = _current_admin(request)
        data = admin_kb_service.list_chunks(actor, document_id, page=page, page_size=page_size)
        return {"code": 200, "message": "success", "data": data}
    except AdminError as exc:
        return _error_response(exc)


@router.post("/kb/search-test")
async def search_test(payload: KbSearchTestRequest, request: Request):
    try:
        actor = _current_admin(request)
        data = admin_kb_service.search_test(
            actor,
            query=payload.query,
            top_k=payload.top_k,
            category=payload.category,
        )
        return {"code": 200, "message": "success", "data": data}
    except AdminError as exc:
        return _error_response(exc)
