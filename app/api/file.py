"""文件上传接口模块"""

from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from app.config import config
from app.services.auth_service import auth_service
from app.services.vector_index_service import vector_index_service
from loguru import logger

router = APIRouter()

# 文件上传后存储的路径
UPLOAD_DIR = Path("./uploads")
KNOWLEDGE_BASE_DIR = Path(config.knowledge_base_path)
# 支持的文件类型
ALLOWED_EXTENSIONS = ["txt", "md"]
# 单个文件支持最大大小
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
UPLOAD_READ_CHUNK_SIZE = 1024 * 1024


def _require_super_admin(request: Request) -> dict:
    user = auth_service.get_user_by_token(request.cookies.get(config.auth_cookie_name))
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if user.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Only super admins can manage indexes")
    return user


def _path_is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _resolve_index_directory(directory_path: str | None = None) -> Path:
    target_path = Path(directory_path) if directory_path else UPLOAD_DIR
    resolved_path = target_path.resolve()
    allowed_roots = [UPLOAD_DIR.resolve(), KNOWLEDGE_BASE_DIR.resolve()]

    if not any(_path_is_under(resolved_path, root) for root in allowed_roots):
        raise HTTPException(
            status_code=403,
            detail="directory_path must be under uploads or the configured knowledge base",
        )
    if not resolved_path.exists() or not resolved_path.is_dir():
        raise HTTPException(status_code=400, detail="directory_path does not exist or is not a directory")
    return resolved_path


async def _read_upload_with_limit(file: UploadFile, max_size: int) -> bytes:
    content = bytearray()
    while True:
        chunk = await file.read(UPLOAD_READ_CHUNK_SIZE)
        if not chunk:
            break
        if len(content) + len(chunk) > max_size:
            raise HTTPException(status_code=400, detail=f"文件大小超过限制（最大 {max_size} 字节）")
        content.extend(chunk)
    return bytes(content)


@router.post("/upload")
async def upload_file(request: Request, file: UploadFile = File(...)):
    """
    上传文件并自动创建向量索引

    Args:
        file: 上传的文件

    Returns:
        JSONResponse: 上传结果
    """
    try:
        _require_super_admin(request)

        # 1. 验证文件
        if not file.filename:
            raise HTTPException(status_code=400, detail="文件名不能为空")

        # 2. 规范化文件名（去除空格，处理 Windows 上传的文件）
        safe_filename = _sanitize_filename(file.filename)

        # 3. 验证文件扩展名
        file_extension = _get_file_extension(safe_filename)
        if file_extension not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的文件格式，仅支持: {', '.join(ALLOWED_EXTENSIONS)}",
            )

        # 4. 创建上传目录
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

        # 5. 保存文件
        file_path = UPLOAD_DIR / safe_filename

        # 如果文件已存在，先删除旧文件（实现覆盖更新）
        if file_path.exists():
            logger.info(f"文件已存在，将覆盖: {file_path}")
            file_path.unlink()

        # 读取并保存文件内容
        content = await _read_upload_with_limit(file, MAX_FILE_SIZE)

        file_path.write_bytes(content)

        logger.info(f"文件上传成功: {file_path}")

        # 5. 自动创建向量索引
        try:
            logger.info(f"开始为上传文件创建向量索引: {file_path}")
            vector_index_service.index_single_file(str(file_path))
            logger.info(f"向量索引创建成功: {file_path}")
        except Exception as e:
            logger.error(f"向量索引创建失败: {file_path}, 错误: {e}")
            # 注意：即使索引失败，文件上传仍然成功，只是记录错误日志

        # 6. 返回响应
        return JSONResponse(
            status_code=200,
            content={
                "code": 200,
                "message": "success",
                "data": {
                    "filename": safe_filename,
                    "file_path": str(file_path),
                    "size": len(content),
                },
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"文件上传失败: {e}")
        raise HTTPException(status_code=500, detail="文件上传失败，请稍后再试")


@router.post("/index_directory")
async def index_directory(request: Request, directory_path: str | None = None):
    """
    索引指定目录下的所有文件

    Args:
        directory_path: 目录路径（可选，默认使用 uploads 目录）

    Returns:
        JSONResponse: 索引结果
    """
    try:
        _require_super_admin(request)
        safe_directory_path = _resolve_index_directory(directory_path)
        logger.info(f"开始索引目录: {directory_path or 'uploads'}")

        # 执行索引
        result = vector_index_service.index_directory(str(safe_directory_path))

        return JSONResponse(
            status_code=200,
            content={
                "code": 200,
                "message": "success" if result.success else "partial_success",
                "data": result.to_dict(),
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"索引目录失败: {e}")
        raise HTTPException(status_code=500, detail="目录索引失败，请稍后再试")


@router.post("/index_knowledge_base")
async def index_knowledge_base(request: Request):
    """
    索引项目内置知识库目录 docs/knowledge_base。

    该目录用于存放经过整理的 RAG 切片文件；source 子目录中的母文档不会被默认索引。
    """
    try:
        _require_super_admin(request)
        logger.info("开始索引内置知识库目录")
        result = vector_index_service.index_knowledge_base()

        return JSONResponse(
            status_code=200,
            content={
                "code": 200,
                "message": "success" if result.success else "partial_success",
                "data": result.to_dict(),
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"索引内置知识库失败: {e}")
        raise HTTPException(status_code=500, detail="知识库索引失败，请稍后再试")


def _get_file_extension(filename: str) -> str:
    """
    获取文件扩展名

    Args:
        filename: 文件名

    Returns:
        str: 扩展名（小写，不含点）
    """
    parts = filename.rsplit(".", 1)
    if len(parts) == 2:
        return parts[1].lower()
    return ""


def _sanitize_filename(filename: str) -> str:
    """
    规范化文件名，去除空格和特殊字符

    Args:
        filename: 原始文件名

    Returns:
        str: 规范化后的文件名
    """
    # 去除空格
    sanitized = filename.replace(" ", "_")
    # 去除其他可能导致问题的字符
    for char in ['\\', '/', ':', '*', '?', '"', '<', '>', '|']:
        sanitized = sanitized.replace(char, "_")
    return sanitized
