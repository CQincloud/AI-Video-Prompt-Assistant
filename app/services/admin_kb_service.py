"""Admin knowledge-base file management service."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from math import ceil
from pathlib import Path
from typing import Any

from langchain_core.documents import Document
from loguru import logger
from psycopg.types.json import Jsonb

from app.config import config
from app.core.database import get_connection
from app.core.milvus_client import milvus_manager
from app.services.admin_user_service import AdminError
from app.services.document_splitter_service import document_splitter_service
from app.services.vector_embedding_service import vector_embedding_service
from app.services.vector_store_manager import vector_store_manager


class AdminKbService:
    SUPPORTED_EXTENSIONS = {".md", ".txt"}
    UPLOAD_DIR = Path("uploads/kb")

    def list_documents(
        self,
        actor: dict[str, Any],
        *,
        keyword: str | None = None,
        category: str | None = None,
        vector_status: str | None = None,
        enabled: bool | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> dict[str, Any]:
        self._require_admin(actor)
        page = max(page, 1)
        page_size = min(max(page_size, 1), 100)
        offset = (page - 1) * page_size

        conditions = ["d.is_deleted = FALSE"]
        params: list[Any] = []
        if keyword:
            conditions.append("(d.original_file_name ILIKE %s OR d.title ILIKE %s)")
            like = f"%{keyword.strip()}%"
            params.extend([like, like])
        if category:
            conditions.append("d.category = %s")
            params.append(category)
        if vector_status:
            conditions.append("d.vector_status = %s")
            params.append(vector_status)
        if enabled is not None:
            conditions.append("d.enabled = %s")
            params.append(enabled)

        where_sql = f"WHERE {' AND '.join(conditions)}"

        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(f"SELECT COUNT(*) AS total FROM kb_documents d {where_sql}", params)
                total = int(cursor.fetchone()["total"])
                cursor.execute(
                    f"""
                    SELECT
                        d.*,
                        cu.nickname AS created_by_nickname,
                        cu.mobile AS created_by_mobile
                    FROM kb_documents d
                    LEFT JOIN users cu ON cu.id = d.created_by
                    {where_sql}
                    ORDER BY d.created_at DESC, d.id DESC
                    LIMIT %s OFFSET %s
                    """,
                    [*params, page_size, offset],
                )
                rows = cursor.fetchall()
                cursor.execute(
                    """
                    SELECT DISTINCT category
                    FROM kb_documents
                    WHERE is_deleted = FALSE
                    ORDER BY category
                    """
                )
                categories = [row["category"] for row in cursor.fetchall()]

        return {
            "list": [self._serialize_document(row) for row in rows],
            "categories": categories,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": ceil(total / page_size) if total else 0,
        }

    def get_document(self, actor: dict[str, Any], document_id: int) -> dict[str, Any]:
        self._require_admin(actor)
        row = self._fetch_document(document_id)
        if row is None:
            raise AdminError("知识库文件不存在", status_code=404)
        return self._serialize_document(row)

    def get_document_content(self, actor: dict[str, Any], document_id: int) -> dict[str, Any]:
        self._require_admin(actor)
        document = self._fetch_document(document_id)
        if document is None:
            raise AdminError("知识库文件不存在", status_code=404)
        if document["is_deleted"]:
            raise AdminError("已删除文件不能编辑")
        path = Path(document["file_path"])
        if path.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
            raise AdminError("仅支持编辑 .md 和 .txt 文件")
        if not path.exists() or not path.is_file():
            raise AdminError("原始文件不存在", status_code=404)

        return {
            "document": self._serialize_document(document),
            "content": path.read_text(encoding="utf-8"),
        }

    def upload_document(
        self,
        actor: dict[str, Any],
        *,
        original_file_name: str,
        content_type: str | None,
        content: bytes,
        category: str,
        description: str | None,
    ) -> dict[str, Any]:
        self._require_admin(actor)
        if not content:
            raise AdminError("上传文件不能为空")

        original_name = Path(original_file_name).name
        extension = Path(original_name).suffix.lower()
        if extension not in self.SUPPORTED_EXTENSIONS:
            raise AdminError("第一版仅支持 .md 和 .txt 文件")

        self.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        file_hash = hashlib.sha256(content).hexdigest()
        stored_name = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex}{extension}"
        file_path = self.UPLOAD_DIR / stored_name
        file_path.write_bytes(content)

        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO kb_documents (
                        original_file_name,
                        stored_file_name,
                        file_path,
                        file_type,
                        mime_type,
                        file_size,
                        file_hash,
                        title,
                        description,
                        category,
                        collection_name,
                        embedding_model,
                        created_by,
                        updated_by
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        original_name,
                        stored_name,
                        file_path.as_posix(),
                        extension.lstrip("."),
                        content_type,
                        len(content),
                        file_hash,
                        Path(original_name).stem,
                        (description or "").strip() or None,
                        category.strip() or "default",
                        vector_store_manager.collection_name,
                        config.dashscope_embedding_model,
                        actor["id"],
                        actor["id"],
                    ),
                )
                document_id = int(cursor.fetchone()["id"])

        self.index_document(actor, document_id, task_type="upload_index")
        return self.get_document(actor, document_id)

    def import_existing_documents(
        self,
        actor: dict[str, Any],
        *,
        reindex: bool = False,
    ) -> dict[str, Any]:
        self._require_admin(actor)
        base_path = Path(config.knowledge_base_path)
        if not base_path.exists() or not base_path.is_dir():
            raise AdminError("知识库目录不存在", status_code=404)

        files = [
            path
            for path in sorted(base_path.iterdir())
            if path.is_file() and path.suffix.lower() in self.SUPPORTED_EXTENSIONS
        ]
        imported: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        reindexed = 0

        for path in files:
            resolved_path = path.resolve()
            file_path = resolved_path.as_posix()
            try:
                content = resolved_path.read_bytes()
                file_hash = hashlib.sha256(content).hexdigest()
                existing = self._fetch_document_by_path(file_path)
                if existing is not None:
                    skipped.append({"file_name": path.name, "document_id": int(existing["id"])})
                    continue

                text = content.decode("utf-8")
                docs = document_splitter_service.split_document(text, file_path)
                document_id = self._insert_existing_document(
                    actor,
                    path=resolved_path,
                    content=content,
                    file_hash=file_hash,
                    category=self._infer_category(path.name),
                    chunk_count=len(docs),
                )
                self._replace_chunks_without_vectors(
                    document_id,
                    docs,
                    file_name=path.name,
                    category=self._infer_category(path.name),
                    file_path=file_path,
                )
                imported.append({"file_name": path.name, "document_id": document_id})
                if reindex:
                    self.index_document(actor, document_id, task_type="reindex")
                    reindexed += 1
            except Exception as exc:
                logger.exception(f"Import existing knowledge document failed: {path}")
                failed.append({"file_name": path.name, "error": str(exc)})

        return {
            "total_files": len(files),
            "imported_count": len(imported),
            "skipped_count": len(skipped),
            "failed_count": len(failed),
            "reindexed_count": reindexed,
            "imported": imported,
            "skipped": skipped,
            "failed": failed,
        }

    def update_document(
        self,
        actor: dict[str, Any],
        document_id: int,
        *,
        title: str | None = None,
        category: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        self._require_admin(actor)
        assignments: list[str] = ["updated_by = %s"]
        params: list[Any] = [actor["id"]]
        if title is not None:
            assignments.append("title = %s")
            params.append(title.strip() or None)
        if category is not None:
            assignments.append("category = %s")
            params.append(category.strip() or "default")
        if description is not None:
            assignments.append("description = %s")
            params.append(description.strip() or None)

        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    UPDATE kb_documents
                    SET {', '.join(assignments)}
                    WHERE id = %s AND is_deleted = FALSE
                    RETURNING id
                    """,
                    [*params, document_id],
                )
                if cursor.fetchone() is None:
                    raise AdminError("知识库文件不存在", status_code=404)
        return self.get_document(actor, document_id)

    def update_document_content(
        self,
        actor: dict[str, Any],
        document_id: int,
        *,
        content: str,
        reindex: bool = False,
    ) -> dict[str, Any]:
        self._require_admin(actor)
        if not content.strip():
            raise AdminError("文档内容不能为空")

        document = self._fetch_document(document_id)
        if document is None:
            raise AdminError("知识库文件不存在", status_code=404)
        if document["is_deleted"]:
            raise AdminError("已删除文件不能编辑")

        path = Path(document["file_path"])
        if path.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
            raise AdminError("仅支持编辑 .md 和 .txt 文件")
        if not path.exists() or not path.is_file():
            raise AdminError("原始文件不存在", status_code=404)

        normalized_content = content.replace("\r\n", "\n")
        content_bytes = normalized_content.encode("utf-8")
        path.write_text(normalized_content, encoding="utf-8", newline="\n")
        file_hash = hashlib.sha256(content_bytes).hexdigest()

        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE kb_documents
                    SET file_size = %s,
                        file_hash = %s,
                        updated_by = %s,
                        error_message = NULL
                    WHERE id = %s AND is_deleted = FALSE
                    """,
                    (len(content_bytes), file_hash, actor["id"], document_id),
                )

        if reindex:
            return self.index_document(actor, document_id, task_type="reindex")

        docs = document_splitter_service.split_document(normalized_content, path.as_posix())
        self._replace_chunks_without_vectors(
            document_id,
            docs,
            file_name=document["original_file_name"],
            category=document["category"],
            file_path=path.as_posix(),
            enabled=bool(document["enabled"]),
        )
        try:
            vector_store_manager.delete_by_document_id(document_id)
            vector_store_manager.delete_by_source(path.as_posix())
        except Exception as exc:
            logger.warning(f"Failed to delete old vectors after content edit: {exc}")

        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE kb_documents
                    SET vector_status = 'pending',
                        chunk_count = %s,
                        error_message = NULL,
                        updated_by = %s
                    WHERE id = %s
                    """,
                    (len(docs), actor["id"], document_id),
                )
        return self.get_document(actor, document_id)

    def set_enabled(self, actor: dict[str, Any], document_id: int, enabled: bool) -> dict[str, Any]:
        self._require_admin(actor)
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE kb_documents
                    SET enabled = %s, updated_by = %s
                    WHERE id = %s AND is_deleted = FALSE
                    RETURNING id
                    """,
                    (enabled, actor["id"], document_id),
                )
                if cursor.fetchone() is None:
                    raise AdminError("知识库文件不存在", status_code=404)
                cursor.execute(
                    "UPDATE kb_document_chunks SET enabled = %s WHERE document_id = %s",
                    (enabled, document_id),
                )
        return self.get_document(actor, document_id)

    def soft_delete(self, actor: dict[str, Any], document_id: int) -> dict[str, Any]:
        self._require_admin(actor)
        with get_connection() as conn:
            with conn.cursor() as cursor:
                row = self._fetch_document_for_update(cursor, document_id)
                if row is None:
                    raise AdminError("知识库文件不存在", status_code=404)
                cursor.execute(
                    """
                    UPDATE kb_documents
                    SET enabled = FALSE,
                        is_deleted = TRUE,
                        updated_by = %s
                    WHERE id = %s
                    """,
                    (actor["id"], document_id),
                )
                cursor.execute(
                    "UPDATE kb_document_chunks SET enabled = FALSE WHERE document_id = %s",
                    (document_id,),
                )

        task_id = self._create_task(actor, document_id, "delete_index")
        deleted_count = vector_store_manager.delete_by_document_id(document_id)
        self._finish_task(task_id, "success", vector_count=deleted_count)
        return {"document_id": document_id, "deleted_vectors": deleted_count}

    def index_document(
        self,
        actor: dict[str, Any],
        document_id: int,
        *,
        task_type: str = "reindex",
    ) -> dict[str, Any]:
        self._require_admin(actor)
        document = self._fetch_document(document_id)
        if document is None:
            raise AdminError("知识库文件不存在", status_code=404)
        if document["is_deleted"]:
            raise AdminError("已删除文件不能向量化")

        task_id = self._create_task(actor, document_id, task_type)
        self._mark_document_status(document_id, "processing", error_message=None)

        try:
            path = Path(document["file_path"])
            if not path.exists() or not path.is_file():
                raise RuntimeError("原始文件不存在")

            content = path.read_text(encoding="utf-8")
            docs = document_splitter_service.split_document(content, path.as_posix())
            vector_store_manager.delete_by_document_id(document_id)
            vector_store_manager.delete_by_source(path.as_posix())

            with get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("DELETE FROM kb_document_chunks WHERE document_id = %s", (document_id,))
                    chunk_rows: list[dict[str, Any]] = []
                    for index, doc in enumerate(docs):
                        metadata = dict(doc.metadata or {})
                        metadata.update(
                            {
                                "document_id": document_id,
                                "file_name": document["original_file_name"],
                                "category": document["category"],
                                "enabled": bool(document["enabled"]),
                                "is_deleted": False,
                                "_source": path.as_posix(),
                            }
                        )
                        cursor.execute(
                            """
                            INSERT INTO kb_document_chunks (
                                document_id,
                                chunk_index,
                                content,
                                content_hash,
                                token_count,
                                collection_name,
                                enabled,
                                metadata
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            RETURNING id
                            """,
                            (
                                document_id,
                                index,
                                doc.page_content,
                                hashlib.sha256(doc.page_content.encode("utf-8")).hexdigest(),
                                len(doc.page_content),
                                vector_store_manager.collection_name,
                                bool(document["enabled"]),
                                Jsonb(metadata),
                            ),
                        )
                        chunk_id = int(cursor.fetchone()["id"])
                        metadata["chunk_id"] = chunk_id
                        metadata["chunk_index"] = index
                        chunk_rows.append(
                            {
                                "id": chunk_id,
                                "index": index,
                                "content": doc.page_content,
                                "metadata": metadata,
                            }
                        )

            vector_docs = [
                Document(page_content=row["content"], metadata=row["metadata"])
                for row in chunk_rows
            ]
            vector_ids = [
                f"doc-{document_id}-chunk-{row['id']}-{uuid.uuid4().hex[:8]}"
                for row in chunk_rows
            ]
            if vector_docs:
                vector_store_manager.add_documents(vector_docs, ids=vector_ids)

            with get_connection() as conn:
                with conn.cursor() as cursor:
                    for row, vector_id in zip(chunk_rows, vector_ids, strict=False):
                        cursor.execute(
                            "UPDATE kb_document_chunks SET vector_id = %s WHERE id = %s",
                            (vector_id, row["id"]),
                        )
                    cursor.execute(
                        """
                        UPDATE kb_documents
                        SET vector_status = 'success',
                            chunk_count = %s,
                            error_message = NULL,
                            updated_by = %s
                        WHERE id = %s
                        """,
                        (len(chunk_rows), actor["id"], document_id),
                    )

            self._finish_task(
                task_id,
                "success",
                chunk_count=len(chunk_rows),
                vector_count=len(vector_ids),
            )
            return self.get_document(actor, document_id)
        except Exception as exc:
            logger.exception(f"Knowledge document indexing failed: document_id={document_id}")
            message = str(exc)
            self._mark_document_status(document_id, "failed", error_message=message)
            self._finish_task(task_id, "failed", error_message=message)
            raise AdminError(f"向量化失败：{message}", status_code=500) from exc

    def list_chunks(
        self,
        actor: dict[str, Any],
        document_id: int,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        self._require_admin(actor)
        if self._fetch_document(document_id) is None:
            raise AdminError("知识库文件不存在", status_code=404)
        page = max(page, 1)
        page_size = min(max(page_size, 1), 100)
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) AS total FROM kb_document_chunks WHERE document_id = %s",
                    (document_id,),
                )
                total = int(cursor.fetchone()["total"])
                cursor.execute(
                    """
                    SELECT *
                    FROM kb_document_chunks
                    WHERE document_id = %s
                    ORDER BY chunk_index
                    LIMIT %s OFFSET %s
                    """,
                    (document_id, page_size, (page - 1) * page_size),
                )
                rows = cursor.fetchall()
        return {
            "list": [self._serialize_chunk(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": ceil(total / page_size) if total else 0,
        }

    def search_test(
        self,
        actor: dict[str, Any],
        *,
        query: str,
        top_k: int = 5,
        category: str | None = None,
    ) -> dict[str, Any]:
        self._require_admin(actor)
        try:
            query_vector = vector_embedding_service.embed_query(query)
            milvus_manager.connect()
            collection = milvus_manager.get_collection()
            expr_parts = ['metadata["enabled"] == true', 'metadata["is_deleted"] == false']
            if category:
                expr_parts.append(f'metadata["category"] == "{category}"')
            expr = " and ".join(expr_parts)
            results = collection.search(
                data=[query_vector],
                anns_field="vector",
                param={"metric_type": "L2", "params": {"nprobe": 10}},
                limit=top_k,
                expr=expr,
                output_fields=["id", "content", "metadata"],
            )
        except Exception as exc:
            logger.warning(f"Milvus search-test expr search failed, retrying without expr: {exc}")
            query_vector = vector_embedding_service.embed_query(query)
            milvus_manager.connect()
            collection = milvus_manager.get_collection()
            results = collection.search(
                data=[query_vector],
                anns_field="vector",
                param={"metric_type": "L2", "params": {"nprobe": 10}},
                limit=top_k * 3,
                output_fields=["id", "content", "metadata"],
            )

        items: list[dict[str, Any]] = []
        seen_chunk_ids: set[int] = set()
        for hits in results:
            for hit in hits:
                metadata = hit.entity.get("metadata", {}) or {}
                document_id = metadata.get("document_id")
                chunk_id = metadata.get("chunk_id")
                if not document_id or not chunk_id:
                    continue
                try:
                    chunk_id_int = int(chunk_id)
                except (TypeError, ValueError):
                    continue
                if chunk_id_int in seen_chunk_ids:
                    continue
                chunk = self._fetch_active_chunk(chunk_id_int, category=category)
                if not chunk:
                    continue
                seen_chunk_ids.add(chunk_id_int)
                items.append(
                    {
                        "document_id": int(chunk["document_id"]),
                        "file_name": chunk["original_file_name"],
                        "chunk_id": chunk_id_int,
                        "chunk_index": int(chunk["chunk_index"]),
                        "content": chunk["content"],
                        "score": float(hit.distance),
                        "metadata": metadata,
                    }
                )
                if len(items) >= top_k:
                    break
            if len(items) >= top_k:
                break
        return {"results": items}

    def _fetch_document_by_path(self, file_path: str) -> dict[str, Any] | None:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM kb_documents
                    WHERE file_path = %s AND is_deleted = FALSE
                    LIMIT 1
                    """,
                    (file_path,),
                )
                return cursor.fetchone()

    def _insert_existing_document(
        self,
        actor: dict[str, Any],
        *,
        path: Path,
        content: bytes,
        file_hash: str,
        category: str,
        chunk_count: int,
    ) -> int:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO kb_documents (
                        original_file_name,
                        stored_file_name,
                        file_path,
                        file_type,
                        mime_type,
                        file_size,
                        file_hash,
                        title,
                        description,
                        category,
                        vector_status,
                        chunk_count,
                        collection_name,
                        embedding_model,
                        created_by,
                        updated_by
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending', %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        path.name,
                        path.name,
                        path.as_posix(),
                        path.suffix.lower().lstrip("."),
                        "text/markdown" if path.suffix.lower() == ".md" else "text/plain",
                        len(content),
                        file_hash,
                        path.stem,
                        "从现有知识库目录导入",
                        category,
                        chunk_count,
                        vector_store_manager.collection_name,
                        config.dashscope_embedding_model,
                        actor["id"],
                        actor["id"],
                    ),
                )
                return int(cursor.fetchone()["id"])

    def _replace_chunks_without_vectors(
        self,
        document_id: int,
        docs: list[Document],
        *,
        file_name: str,
        category: str,
        file_path: str,
        enabled: bool = True,
    ) -> None:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM kb_document_chunks WHERE document_id = %s", (document_id,))
                for index, doc in enumerate(docs):
                    metadata = dict(doc.metadata or {})
                    metadata.update(
                        {
                            "document_id": document_id,
                            "file_name": file_name,
                            "category": category,
                            "enabled": enabled,
                            "is_deleted": False,
                            "_source": file_path,
                            "chunk_index": index,
                        }
                    )
                    cursor.execute(
                        """
                        INSERT INTO kb_document_chunks (
                            document_id,
                            chunk_index,
                            content,
                            content_hash,
                            token_count,
                            collection_name,
                            enabled,
                            metadata
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (
                            document_id,
                            index,
                            doc.page_content,
                            hashlib.sha256(doc.page_content.encode("utf-8")).hexdigest(),
                            len(doc.page_content),
                            vector_store_manager.collection_name,
                            enabled,
                            Jsonb(metadata),
                        ),
                    )

    def _infer_category(self, file_name: str) -> str:
        lower_name = file_name.lower()
        rules = [
            (("action", "动作"), "动作提示词"),
            (("three_view", "三视图"), "角色三视图"),
            (("expression", "voice", "表情", "语气"), "表情语气"),
            (("scene", "场景"), "场景提示词"),
            (("script", "剧本", "剧情"), "剧情生成"),
            (("shot", "分镜"), "分镜生成"),
            (("style", "aesthetics", "风格", "美学"), "风格美学"),
            (("character", "角色", "人物"), "角色生成"),
            (("catalog", "目录"), "知识库目录"),
        ]
        for keywords, category in rules:
            if any(keyword in lower_name or keyword in file_name for keyword in keywords):
                return category
        return "default"

    def _require_admin(self, actor: dict[str, Any]) -> None:
        if actor["role"] not in {"admin", "super_admin"}:
            raise AdminError("无后台权限", status_code=403)

    def _fetch_document(self, document_id: int) -> dict[str, Any] | None:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                return self._fetch_document_for_update(cursor, document_id, for_update=False)

    def _fetch_document_for_update(
        self,
        cursor: Any,
        document_id: int,
        *,
        for_update: bool = True,
    ) -> dict[str, Any] | None:
        lock_clause = "FOR UPDATE OF d" if for_update else ""
        cursor.execute(
            f"""
            SELECT
                d.*,
                cu.nickname AS created_by_nickname,
                cu.mobile AS created_by_mobile
            FROM kb_documents d
            LEFT JOIN users cu ON cu.id = d.created_by
            WHERE d.id = %s
            {lock_clause}
            """,
            (document_id,),
        )
        return cursor.fetchone()

    def _create_task(self, actor: dict[str, Any], document_id: int, task_type: str) -> int:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO kb_index_tasks (document_id, task_type, status, created_by, started_at)
                    VALUES (%s, %s, 'processing', %s, CURRENT_TIMESTAMP)
                    RETURNING id
                    """,
                    (document_id, task_type, actor["id"]),
                )
                return int(cursor.fetchone()["id"])

    def _finish_task(
        self,
        task_id: int,
        status: str,
        *,
        chunk_count: int = 0,
        vector_count: int = 0,
        error_message: str | None = None,
    ) -> None:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE kb_index_tasks
                    SET status = %s,
                        chunk_count = %s,
                        vector_count = %s,
                        error_message = %s,
                        finished_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (status, chunk_count, vector_count, error_message, task_id),
                )

    def _mark_document_status(
        self,
        document_id: int,
        status: str,
        *,
        error_message: str | None,
    ) -> None:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE kb_documents
                    SET vector_status = %s, error_message = %s
                    WHERE id = %s
                    """,
                    (status, error_message, document_id),
                )

    def _fetch_active_chunk(
        self,
        chunk_id: int,
        *,
        category: str | None = None,
    ) -> dict[str, Any] | None:
        conditions = [
            "c.id = %s",
            "c.enabled = TRUE",
            "d.enabled = TRUE",
            "d.is_deleted = FALSE",
            "d.vector_status = 'success'",
        ]
        params: list[Any] = [chunk_id]
        if category:
            conditions.append("d.category = %s")
            params.append(category)
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT c.*, d.original_file_name
                    FROM kb_document_chunks c
                    JOIN kb_documents d ON d.id = c.document_id
                    WHERE {' AND '.join(conditions)}
                    """,
                    params,
                )
                return cursor.fetchone()

    def _serialize_document(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "original_file_name": row["original_file_name"],
            "stored_file_name": row["stored_file_name"],
            "file_path": row["file_path"],
            "file_type": row["file_type"],
            "mime_type": row["mime_type"],
            "file_size": int(row["file_size"]),
            "file_hash": row["file_hash"],
            "title": row["title"],
            "description": row["description"],
            "category": row["category"],
            "enabled": bool(row["enabled"]),
            "is_deleted": bool(row["is_deleted"]),
            "vector_status": row["vector_status"],
            "chunk_count": int(row["chunk_count"]),
            "collection_name": row["collection_name"],
            "embedding_model": row["embedding_model"],
            "created_by": {
                "id": int(row["created_by"]),
                "mobile": row["created_by_mobile"],
                "nickname": row["created_by_nickname"],
            }
            if row.get("created_by") is not None
            else None,
            "error_message": row["error_message"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        }

    def _serialize_chunk(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "document_id": int(row["document_id"]),
            "chunk_index": int(row["chunk_index"]),
            "content": row["content"],
            "content_hash": row["content_hash"],
            "token_count": int(row["token_count"]),
            "vector_id": row["vector_id"],
            "collection_name": row["collection_name"],
            "enabled": bool(row["enabled"]),
            "metadata": row["metadata"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        }


admin_kb_service = AdminKbService()
