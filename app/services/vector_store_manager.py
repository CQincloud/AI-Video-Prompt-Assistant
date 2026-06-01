"""Milvus vector-store manager with lazy initialization."""

from __future__ import annotations

from threading import Lock
from time import perf_counter
from typing import List

from langchain_core.documents import Document
from langchain_milvus import Milvus
from loguru import logger

from app.config import config
from app.core.milvus_client import milvus_manager
from app.services.vector_embedding_service import vector_embedding_service

COLLECTION_NAME = "biz"


class VectorStoreManager:
    """Manage the LangChain Milvus vector store."""

    def __init__(self) -> None:
        self.vector_store: Milvus | None = None
        self.collection_name = COLLECTION_NAME
        self._init_lock = Lock()

    def _ensure_initialized(self) -> Milvus:
        if self.vector_store is not None:
            return self.vector_store

        with self._init_lock:
            if self.vector_store is not None:
                return self.vector_store

            milvus_manager.connect()
            self.vector_store = Milvus(
                embedding_function=vector_embedding_service,
                collection_name=self.collection_name,
                connection_args={"host": config.milvus_host, "port": config.milvus_port},
                auto_id=False,
                drop_old=False,
                text_field="content",
                vector_field="vector",
                primary_field="id",
                metadata_field="metadata",
            )
            logger.info(
                f"VectorStore initialized: {config.milvus_host}:{config.milvus_port}, "
                f"collection={self.collection_name}"
            )
        return self.vector_store

    def add_documents(self, documents: List[Document], ids: list[str] | None = None) -> List[str]:
        import time
        import uuid

        start_time = time.time()
        vector_store = self._ensure_initialized()
        ids = ids or [str(uuid.uuid4()) for _ in documents]
        result_ids = vector_store.add_documents(documents, ids=ids)
        try:
            milvus_manager.get_collection().flush()
        except Exception as exc:
            logger.warning(f"Milvus flush after add_documents failed: {exc}")
        elapsed = time.time() - start_time
        logger.info(f"Added {len(documents)} documents to VectorStore in {elapsed:.2f}s")
        return result_ids

    def delete_by_source(self, file_path: str) -> int:
        try:
            milvus_manager.connect()
            collection = milvus_manager.get_collection()
            expr = f'metadata["_source"] == "{file_path}"'
            result = collection.delete(expr)
            deleted_count = result.delete_count if hasattr(result, "delete_count") else 0
            logger.info(f"Deleted indexed documents for {file_path}: {deleted_count}")
            return deleted_count
        except Exception as exc:
            logger.warning(f"Failed to delete indexed documents for {file_path}: {exc}")
            return 0

    def delete_by_document_id(self, document_id: int) -> int:
        try:
            milvus_manager.connect()
            collection = milvus_manager.get_collection()
            expr = f'metadata["document_id"] == {int(document_id)}'
            result = collection.delete(expr)
            deleted_count = result.delete_count if hasattr(result, "delete_count") else 0
            logger.info(f"Deleted indexed chunks for document_id={document_id}: {deleted_count}")
            return deleted_count
        except Exception as exc:
            logger.warning(f"Failed to delete indexed chunks for document_id={document_id}: {exc}")
            return 0

    def get_vector_store(self) -> Milvus:
        return self._ensure_initialized()

    def similarity_search(self, query: str, k: int = 3, expr: str | None = None) -> List[Document]:
        try:
            started_at = perf_counter()
            kwargs = {"k": k}
            if expr:
                kwargs["expr"] = expr
            docs = self._ensure_initialized().similarity_search(query, **kwargs)
            logger.info(
                "VectorStore similarity search completed: "
                f"k={k}, expr={bool(expr)}, count={len(docs)}, "
                f"elapsed={(perf_counter() - started_at) * 1000:.1f}ms"
            )
            return docs
        except Exception as exc:
            logger.error(f"VectorStore similarity search failed: {exc}, expr={expr!r}")
            return []


vector_store_manager = VectorStoreManager()
