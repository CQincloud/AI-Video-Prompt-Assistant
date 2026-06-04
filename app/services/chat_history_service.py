"""Persistent chat history storage backed by PostgreSQL."""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from typing import Any

import psycopg
from loguru import logger
from psycopg.types.json import Jsonb

from app.config import config
from app.core.database import get_connection


SESSION_ID_RE = re.compile(r"^[A-Za-z0-9:_-]{1,120}$")
DEFAULT_TITLE = "New chat"


class ChatHistoryError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class ChatHistoryService:
    """Store raw chat sessions and messages with strict user ownership."""

    def _connect(self) -> psycopg.Connection[dict[str, Any]]:
        return get_connection()

    def ensure_schema(self) -> None:
        """Create chat history tables when the app starts."""
        if not config.database_allow_untracked_schema_ensure:
            raise RuntimeError(
                "Runtime chat schema changes are disabled. Run database migrations first."
            )
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE OR REPLACE FUNCTION update_updated_at_column()
                    RETURNS TRIGGER AS $$
                    BEGIN
                        NEW.updated_at = CURRENT_TIMESTAMP;
                        RETURN NEW;
                    END;
                    $$ LANGUAGE plpgsql;
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS chat_sessions (
                        id TEXT PRIMARY KEY,
                        user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        title VARCHAR(120) NOT NULL DEFAULT 'New chat',
                        status VARCHAR(20) NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active', 'deleted')),
                        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                        last_message_at TIMESTAMPTZ,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_updated
                    ON chat_sessions(user_id, updated_at DESC)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_status
                    ON chat_sessions(user_id, status)
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS chat_messages (
                        id BIGSERIAL PRIMARY KEY,
                        session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
                        user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        role VARCHAR(20) NOT NULL
                            CHECK (role IN ('user', 'assistant', 'system', 'tool')),
                        content TEXT NOT NULL DEFAULT '',
                        client_message_id TEXT,
                        parent_message_id BIGINT REFERENCES chat_messages(id) ON DELETE SET NULL,
                        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_chat_messages_session_created
                    ON chat_messages(session_id, created_at, id)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_chat_messages_user_created
                    ON chat_messages(user_id, created_at DESC)
                    """
                )
                cursor.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_messages_session_client_id
                    ON chat_messages(session_id, client_message_id)
                    WHERE client_message_id IS NOT NULL
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS chat_attachments (
                        id BIGSERIAL PRIMARY KEY,
                        message_id BIGINT REFERENCES chat_messages(id) ON DELETE CASCADE,
                        session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
                        user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        purpose VARCHAR(40) NOT NULL
                            CHECK (purpose IN (
                                'vision',
                                'generation_reference',
                                'generated_image'
                            )),
                        file_name TEXT NOT NULL DEFAULT '',
                        file_path TEXT,
                        file_url TEXT,
                        mime_type VARCHAR(120) NOT NULL DEFAULT '',
                        file_size BIGINT NOT NULL DEFAULT 0,
                        width INTEGER,
                        height INTEGER,
                        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_chat_attachments_message
                    ON chat_attachments(message_id)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_chat_attachments_user_created
                    ON chat_attachments(user_id, created_at DESC)
                    """
                )
                cursor.execute(
                    """
                    DROP TRIGGER IF EXISTS trigger_chat_sessions_updated_at
                    ON chat_sessions
                    """
                )
                cursor.execute(
                    """
                    CREATE TRIGGER trigger_chat_sessions_updated_at
                    BEFORE UPDATE ON chat_sessions
                    FOR EACH ROW
                    EXECUTE FUNCTION update_updated_at_column()
                    """
                )
        logger.info("Chat history schema is ready")

    def create_session(
        self,
        user_id: int,
        session_id: str | None = None,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session_id = self._normalize_session_id(session_id)
        normalized_title = self._normalize_title(title)
        with self._connect() as conn:
            with conn.cursor() as cursor:
                self._ensure_session(
                    cursor,
                    user_id=user_id,
                    session_id=session_id,
                    title=normalized_title,
                    metadata=metadata,
                )
                row = self._fetch_session(cursor, user_id, session_id)
                if row is None:
                    raise ChatHistoryError("Chat session was not created", 500)
                return self._serialize_session(row)

    def list_sessions(self, user_id: int, limit: int = 50) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 100))
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        s.id,
                        s.user_id,
                        s.title,
                        s.status,
                        s.last_message_at,
                        s.created_at,
                        s.updated_at,
                        COUNT(m.id) AS message_count
                    FROM chat_sessions s
                    LEFT JOIN chat_messages m ON m.session_id = s.id
                    WHERE s.user_id = %s
                      AND s.status = 'active'
                    GROUP BY s.id
                    ORDER BY COALESCE(s.last_message_at, s.updated_at) DESC
                    LIMIT %s
                    """,
                    (user_id, safe_limit),
                )
                return [self._serialize_session(row) for row in cursor.fetchall()]

    def get_messages(
        self,
        user_id: int,
        session_id: str,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        session_id = self._validate_session_id(session_id)
        with self._connect() as conn:
            with conn.cursor() as cursor:
                session = self._fetch_session(cursor, user_id, session_id)
                if session is None:
                    raise ChatHistoryError("Chat session not found", 404)
                cursor.execute(
                    """
                    SELECT
                        id,
                        session_id,
                        user_id,
                        role,
                        content,
                        client_message_id,
                        parent_message_id,
                        metadata,
                        created_at
                    FROM chat_messages
                    WHERE session_id = %s
                      AND user_id = %s
                    ORDER BY created_at ASC, id ASC
                    """,
                    (session_id, user_id),
                )
                messages = [self._serialize_message(row) for row in cursor.fetchall()]
                self._attach_attachments(cursor, user_id, messages)
                return self._serialize_session(session), messages

    def append_message(
        self,
        user_id: int,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        client_message_id: str | None = None,
        parent_message_id: int | None = None,
    ) -> dict[str, Any]:
        session_id = self._validate_session_id(session_id)
        role = self._validate_role(role)
        content = content or ""

        with self._connect() as conn:
            with conn.cursor() as cursor:
                self._ensure_session(
                    cursor,
                    user_id=user_id,
                    session_id=session_id,
                    title=self._title_from_content(content) if role == "user" else None,
                )
                cursor.execute(
                    """
                    INSERT INTO chat_messages (
                        session_id,
                        user_id,
                        role,
                        content,
                        client_message_id,
                        parent_message_id,
                        metadata,
                        created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (session_id, client_message_id)
                    WHERE client_message_id IS NOT NULL
                    DO UPDATE SET
                        content = CASE
                            WHEN char_length(EXCLUDED.content) >= char_length(chat_messages.content)
                            THEN EXCLUDED.content
                            ELSE chat_messages.content
                        END,
                        parent_message_id = COALESCE(
                            EXCLUDED.parent_message_id,
                            chat_messages.parent_message_id
                        ),
                        metadata = chat_messages.metadata || EXCLUDED.metadata
                    RETURNING
                        id,
                        session_id,
                        user_id,
                        role,
                        content,
                        client_message_id,
                        parent_message_id,
                        metadata,
                        created_at
                    """,
                    (
                        session_id,
                        user_id,
                        role,
                        content,
                        client_message_id,
                        parent_message_id,
                        Jsonb(metadata or {}),
                        self._now(),
                    ),
                )
                row = cursor.fetchone()

                self._touch_session(
                    cursor,
                    user_id=user_id,
                    session_id=session_id,
                    title=self._title_from_content(content) if role == "user" else None,
                )
                if row is None:
                    raise ChatHistoryError("Chat message was not saved", 500)
                return self._serialize_message(row)

    def append_attachment(
        self,
        user_id: int,
        session_id: str,
        message_id: int,
        purpose: str,
        file_name: str = "",
        file_path: str | None = None,
        file_url: str | None = None,
        mime_type: str = "",
        file_size: int = 0,
        width: int | None = None,
        height: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session_id = self._validate_session_id(session_id)
        purpose = self._validate_attachment_purpose(purpose)
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id
                    FROM chat_messages
                    WHERE id = %s
                      AND session_id = %s
                      AND user_id = %s
                    """,
                    (message_id, session_id, user_id),
                )
                if cursor.fetchone() is None:
                    raise ChatHistoryError("Chat message not found", 404)

                cursor.execute(
                    """
                    INSERT INTO chat_attachments (
                        message_id,
                        session_id,
                        user_id,
                        purpose,
                        file_name,
                        file_path,
                        file_url,
                        mime_type,
                        file_size,
                        width,
                        height,
                        metadata
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING
                        id,
                        message_id,
                        session_id,
                        user_id,
                        purpose,
                        file_name,
                        file_path,
                        file_url,
                        mime_type,
                        file_size,
                        width,
                        height,
                        metadata,
                        created_at
                    """,
                    (
                        message_id,
                        session_id,
                        user_id,
                        purpose,
                        file_name,
                        file_path,
                        file_url,
                        mime_type,
                        file_size,
                        width,
                        height,
                        Jsonb(metadata or {}),
                    ),
                )
                row = cursor.fetchone()
                if row is None:
                    raise ChatHistoryError("Chat attachment was not saved", 500)
                return self._serialize_attachment(row)

    def get_attachment(self, user_id: int, attachment_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        id,
                        message_id,
                        session_id,
                        user_id,
                        purpose,
                        file_name,
                        file_path,
                        file_url,
                        mime_type,
                        file_size,
                        width,
                        height,
                        metadata,
                        created_at
                    FROM chat_attachments
                    WHERE id = %s
                      AND user_id = %s
                    """,
                    (attachment_id, user_id),
                )
                row = cursor.fetchone()
                return self._serialize_attachment(row) if row else None

    def get_message_by_client_id(
        self,
        user_id: int,
        session_id: str,
        client_message_id: str,
    ) -> dict[str, Any]:
        if not client_message_id:
            raise ChatHistoryError("Client message id is required", 400)
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        id,
                        session_id,
                        user_id,
                        role,
                        content,
                        client_message_id,
                        parent_message_id,
                        metadata,
                        created_at
                    FROM chat_messages
                    WHERE session_id = %s
                      AND user_id = %s
                      AND client_message_id = %s
                    """,
                    (session_id, user_id, client_message_id),
                )
                row = cursor.fetchone()
                if row is None:
                    raise ChatHistoryError("Chat message not found", 404)
                return self._serialize_message(row)

    def delete_session(self, user_id: int, session_id: str) -> bool:
        session_id = self._validate_session_id(session_id)
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM chat_sessions WHERE id = %s AND user_id = %s",
                    (session_id, user_id),
                )
                return cursor.rowcount > 0

    def clear_session(self, user_id: int, session_id: str) -> bool:
        session_id = self._validate_session_id(session_id)
        with self._connect() as conn:
            with conn.cursor() as cursor:
                session = self._fetch_session(cursor, user_id, session_id)
                if session is None:
                    return False
                cursor.execute(
                    "DELETE FROM chat_messages WHERE session_id = %s AND user_id = %s",
                    (session_id, user_id),
                )
                self._touch_session(cursor, user_id=user_id, session_id=session_id)
                return True

    def agent_thread_id(self, user_id: int, session_id: str) -> str:
        session_id = self._validate_session_id(session_id)
        return f"user-{user_id}:chat-{session_id}"

    def _ensure_session(
        self,
        cursor: psycopg.Cursor[dict[str, Any]],
        user_id: int,
        session_id: str,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        cursor.execute(
            "SELECT user_id, status FROM chat_sessions WHERE id = %s",
            (session_id,),
        )
        row = cursor.fetchone()
        if row is not None:
            if int(row["user_id"]) != user_id:
                raise ChatHistoryError("Chat session not found", 404)
            if row["status"] != "active":
                cursor.execute(
                    """
                    UPDATE chat_sessions
                    SET status = 'active',
                        updated_at = %s
                    WHERE id = %s
                      AND user_id = %s
                    """,
                    (self._now(), session_id, user_id),
                )
            return

        cursor.execute(
            """
            INSERT INTO chat_sessions (
                id,
                user_id,
                title,
                metadata,
                created_at,
                updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                session_id,
                user_id,
                self._normalize_title(title),
                Jsonb(metadata or {}),
                self._now(),
                self._now(),
            ),
        )

    def _fetch_session(
        self,
        cursor: psycopg.Cursor[dict[str, Any]],
        user_id: int,
        session_id: str,
    ) -> dict[str, Any] | None:
        cursor.execute(
            """
            SELECT
                s.id,
                s.user_id,
                s.title,
                s.status,
                s.last_message_at,
                s.created_at,
                s.updated_at,
                COUNT(m.id) AS message_count
            FROM chat_sessions s
            LEFT JOIN chat_messages m ON m.session_id = s.id
            WHERE s.id = %s
              AND s.user_id = %s
              AND s.status = 'active'
            GROUP BY s.id
            """,
            (session_id, user_id),
        )
        return cursor.fetchone()

    def _touch_session(
        self,
        cursor: psycopg.Cursor[dict[str, Any]],
        user_id: int,
        session_id: str,
        title: str | None = None,
    ) -> None:
        now = self._now()
        if title:
            cursor.execute(
                """
                UPDATE chat_sessions
                SET title = CASE
                        WHEN title = %s THEN %s
                        ELSE title
                    END,
                    last_message_at = %s,
                    updated_at = %s
                WHERE id = %s
                  AND user_id = %s
                """,
                (DEFAULT_TITLE, title, now, now, session_id, user_id),
            )
        else:
            cursor.execute(
                """
                UPDATE chat_sessions
                SET last_message_at = %s,
                    updated_at = %s
                WHERE id = %s
                  AND user_id = %s
                """,
                (now, now, session_id, user_id),
            )

    def _serialize_session(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "userId": int(row["user_id"]),
            "title": row["title"],
            "status": row["status"],
            "messageCount": int(row.get("message_count") or 0),
            "lastMessageAt": self._iso(row.get("last_message_at")),
            "createdAt": self._iso(row.get("created_at")),
            "updatedAt": self._iso(row.get("updated_at")),
        }

    def _serialize_message(self, row: dict[str, Any]) -> dict[str, Any]:
        metadata = row.get("metadata") or {}
        role = row["role"]
        return {
            "id": str(row["id"]),
            "serverId": int(row["id"]),
            "sessionId": row["session_id"],
            "userId": int(row["user_id"]),
            "role": role,
            "type": "user" if role == "user" else "assistant",
            "content": row["content"],
            "clientMessageId": row.get("client_message_id"),
            "parentMessageId": row.get("parent_message_id"),
            "metadata": metadata,
            "prompt": metadata.get("prompt") if isinstance(metadata, dict) else None,
            "modelPrompt": metadata.get("modelPrompt") if isinstance(metadata, dict) else None,
            "model": metadata.get("model") if isinstance(metadata, dict) else None,
            "modelDisplayName": (
                metadata.get("modelDisplayName") if isinstance(metadata, dict) else None
            ),
            "modelProvider": metadata.get("modelProvider") if isinstance(metadata, dict) else None,
            "promptTemplate": metadata.get("promptTemplate") if isinstance(metadata, dict) else None,
            "retryOf": metadata.get("retryOf") if isinstance(metadata, dict) else None,
            "timestamp": self._iso(row.get("created_at")),
            "createdAt": self._iso(row.get("created_at")),
            "attachments": [],
        }

    def _serialize_attachment(self, row: dict[str, Any]) -> dict[str, Any]:
        file_url = row.get("file_url") or f"/api/chat/attachments/{row['id']}/content"
        return {
            "id": str(row["id"]),
            "serverId": int(row["id"]),
            "messageId": int(row["message_id"]) if row.get("message_id") else None,
            "sessionId": row["session_id"],
            "userId": int(row["user_id"]),
            "purpose": row["purpose"],
            "fileName": row.get("file_name") or "",
            "filePath": row.get("file_path"),
            "fileUrl": file_url,
            "url": file_url,
            "mimeType": row.get("mime_type") or "",
            "fileSize": int(row.get("file_size") or 0),
            "width": row.get("width"),
            "height": row.get("height"),
            "metadata": row.get("metadata") or {},
            "createdAt": self._iso(row.get("created_at")),
        }

    def _attach_attachments(
        self,
        cursor: psycopg.Cursor[dict[str, Any]],
        user_id: int,
        messages: list[dict[str, Any]],
    ) -> None:
        message_ids = [int(message["serverId"]) for message in messages if message.get("serverId")]
        if not message_ids:
            return
        cursor.execute(
            """
            SELECT
                id,
                message_id,
                session_id,
                user_id,
                purpose,
                file_name,
                file_path,
                file_url,
                mime_type,
                file_size,
                width,
                height,
                metadata,
                created_at
            FROM chat_attachments
            WHERE user_id = %s
              AND message_id = ANY(%s)
            ORDER BY created_at ASC, id ASC
            """,
            (user_id, message_ids),
        )
        attachments_by_message: dict[int, list[dict[str, Any]]] = {}
        for row in cursor.fetchall():
            attachment = self._serialize_attachment(row)
            attachments_by_message.setdefault(int(row["message_id"]), []).append(attachment)
        for message in messages:
            message["attachments"] = attachments_by_message.get(int(message["serverId"]), [])

    def _normalize_session_id(self, session_id: str | None = None) -> str:
        if session_id:
            return self._validate_session_id(session_id)
        return f"session-{int(datetime.now(timezone.utc).timestamp() * 1000)}-{secrets.token_urlsafe(6)}"

    def _validate_session_id(self, session_id: str) -> str:
        normalized = (session_id or "").strip()
        if not SESSION_ID_RE.fullmatch(normalized):
            raise ChatHistoryError("Invalid chat session id", 400)
        return normalized

    def _validate_role(self, role: str) -> str:
        normalized = (role or "").strip().lower()
        if normalized not in {"user", "assistant", "system", "tool"}:
            raise ChatHistoryError("Invalid chat message role", 400)
        return normalized

    def _validate_attachment_purpose(self, purpose: str) -> str:
        normalized = (purpose or "").strip().lower()
        if normalized not in {"vision", "generation_reference", "generated_image"}:
            raise ChatHistoryError("Invalid chat attachment purpose", 400)
        return normalized

    def _normalize_title(self, title: str | None) -> str:
        normalized = " ".join((title or "").split())
        if not normalized:
            return DEFAULT_TITLE
        return self._truncate(normalized, 60)

    def _title_from_content(self, content: str) -> str:
        normalized = " ".join((content or "").split())
        if not normalized:
            return DEFAULT_TITLE
        return self._truncate(normalized, 30)

    def _truncate(self, value: str, max_length: int) -> str:
        if len(value) <= max_length:
            return value
        return f"{value[:max_length]}..."

    def _iso(self, value: Any) -> str | None:
        return value.isoformat() if value else None

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)


chat_history_service = ChatHistoryService()
