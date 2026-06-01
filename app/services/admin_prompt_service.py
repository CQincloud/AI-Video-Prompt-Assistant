"""Admin system prompt version-management service."""

from __future__ import annotations

from math import ceil
from time import monotonic
from typing import Any

from app.core.database import get_connection
from app.services.admin_user_service import AdminError


class AdminPromptService:
    CACHE_TTL_SECONDS = 300

    def __init__(self) -> None:
        self._active_cache: dict[str, tuple[float, str]] = {}

    def list_prompts(
        self,
        actor: dict[str, Any],
        *,
        prompt_type: str | None = None,
        enabled: bool | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> dict[str, Any]:
        self._require_admin(actor)
        page = max(page, 1)
        page_size = min(max(page_size, 1), 100)
        conditions: list[str] = []
        params: list[Any] = []
        if prompt_type:
            conditions.append("p.prompt_type = %s")
            params.append(prompt_type)
        if enabled is not None:
            conditions.append("p.enabled = %s")
            params.append(enabled)
        if keyword:
            conditions.append("(p.prompt_key ILIKE %s OR p.prompt_name ILIKE %s OR p.content ILIKE %s)")
            like = f"%{keyword.strip()}%"
            params.extend([like, like, like])
        where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(f"SELECT COUNT(*) AS total FROM system_prompts p {where_sql}", params)
                total = int(cursor.fetchone()["total"])
                cursor.execute(
                    f"""
                    SELECT
                        p.*,
                        uu.nickname AS updated_by_nickname,
                        uu.mobile AS updated_by_mobile
                    FROM system_prompts p
                    LEFT JOIN users uu ON uu.id = p.updated_by
                    {where_sql}
                    ORDER BY p.prompt_key, p.version DESC, p.id DESC
                    LIMIT %s OFFSET %s
                    """,
                    [*params, page_size, (page - 1) * page_size],
                )
                rows = cursor.fetchall()
                cursor.execute("SELECT DISTINCT prompt_type FROM system_prompts ORDER BY prompt_type")
                types = [row["prompt_type"] for row in cursor.fetchall()]

        return {
            "list": [self._serialize_prompt(row) for row in rows],
            "types": types,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": ceil(total / page_size) if total else 0,
        }

    def get_prompt(self, actor: dict[str, Any], prompt_id: int) -> dict[str, Any]:
        self._require_admin(actor)
        row = self._fetch_prompt(prompt_id)
        if row is None:
            raise AdminError("系统提示词不存在", status_code=404)
        return self._serialize_prompt(row)

    def create_prompt(
        self,
        actor: dict[str, Any],
        *,
        prompt_key: str,
        prompt_name: str,
        prompt_type: str,
        content: str,
        remark: str | None = None,
        enabled: bool = False,
    ) -> dict[str, Any]:
        self._require_admin(actor)
        clean_key = prompt_key.strip()
        version = self._next_version(clean_key)
        with get_connection() as conn:
            with conn.cursor() as cursor:
                if enabled:
                    cursor.execute(
                        "UPDATE system_prompts SET enabled = FALSE WHERE prompt_key = %s",
                        (clean_key,),
                    )
                cursor.execute(
                    """
                    INSERT INTO system_prompts (
                        prompt_key,
                        prompt_name,
                        prompt_type,
                        content,
                        version,
                        enabled,
                        remark,
                        created_by,
                        updated_by
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        clean_key,
                        prompt_name.strip(),
                        prompt_type.strip(),
                        content.strip(),
                        version,
                        enabled,
                        (remark or "").strip() or None,
                        actor["id"],
                        actor["id"],
                    ),
                )
                prompt_id = int(cursor.fetchone()["id"])
        self.clear_cache(clean_key)
        return self.get_prompt(actor, prompt_id)

    def update_prompt(
        self,
        actor: dict[str, Any],
        prompt_id: int,
        *,
        prompt_name: str | None = None,
        prompt_type: str | None = None,
        content: str | None = None,
        remark: str | None = None,
    ) -> dict[str, Any]:
        self._require_admin(actor)
        assignments = ["updated_by = %s"]
        params: list[Any] = [actor["id"]]
        if prompt_name is not None:
            assignments.append("prompt_name = %s")
            params.append(prompt_name.strip())
        if prompt_type is not None:
            assignments.append("prompt_type = %s")
            params.append(prompt_type.strip())
        if content is not None:
            assignments.append("content = %s")
            params.append(content.strip())
        if remark is not None:
            assignments.append("remark = %s")
            params.append(remark.strip() or None)

        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    UPDATE system_prompts
                    SET {', '.join(assignments)}
                    WHERE id = %s
                    RETURNING prompt_key
                    """,
                    [*params, prompt_id],
                )
                row = cursor.fetchone()
                if row is None:
                    raise AdminError("系统提示词不存在", status_code=404)
                prompt_key = row["prompt_key"]
        self.clear_cache(prompt_key)
        return self.get_prompt(actor, prompt_id)

    def copy_prompt(self, actor: dict[str, Any], prompt_id: int) -> dict[str, Any]:
        self._require_admin(actor)
        source = self._fetch_prompt(prompt_id)
        if source is None:
            raise AdminError("系统提示词不存在", status_code=404)
        return self.create_prompt(
            actor,
            prompt_key=source["prompt_key"],
            prompt_name=source["prompt_name"],
            prompt_type=source["prompt_type"],
            content=source["content"],
            remark=source["remark"],
            enabled=False,
        )

    def enable_prompt(self, actor: dict[str, Any], prompt_id: int) -> dict[str, Any]:
        self._require_admin(actor)
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT prompt_key FROM system_prompts WHERE id = %s", (prompt_id,))
                row = cursor.fetchone()
                if row is None:
                    raise AdminError("系统提示词不存在", status_code=404)
                prompt_key = row["prompt_key"]
                cursor.execute(
                    "UPDATE system_prompts SET enabled = FALSE WHERE prompt_key = %s",
                    (prompt_key,),
                )
                cursor.execute(
                    """
                    UPDATE system_prompts
                    SET enabled = TRUE, updated_by = %s
                    WHERE id = %s
                    """,
                    (actor["id"], prompt_id),
                )
        self.clear_cache(prompt_key)
        return self.get_prompt(actor, prompt_id)

    def disable_prompt(self, actor: dict[str, Any], prompt_id: int) -> dict[str, Any]:
        self._require_admin(actor)
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE system_prompts
                    SET enabled = FALSE, updated_by = %s
                    WHERE id = %s
                    RETURNING prompt_key
                    """,
                    (actor["id"], prompt_id),
                )
                row = cursor.fetchone()
                if row is None:
                    raise AdminError("系统提示词不存在", status_code=404)
                prompt_key = row["prompt_key"]
        self.clear_cache(prompt_key)
        return self.get_prompt(actor, prompt_id)

    def versions(self, actor: dict[str, Any], prompt_key: str) -> dict[str, Any]:
        self._require_admin(actor)
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM system_prompts
                    WHERE prompt_key = %s
                    ORDER BY version DESC, id DESC
                    """,
                    (prompt_key,),
                )
                rows = cursor.fetchall()
        return {"list": [self._serialize_prompt(row) for row in rows]}

    def test_prompt(self, actor: dict[str, Any], prompt_key: str, test_input: str) -> dict[str, Any]:
        self._require_admin(actor)
        prompt = self.get_active_prompt(prompt_key)
        return {
            "prompt_key": prompt_key,
            "system_prompt": prompt,
            "test_input": test_input,
            "preview": f"{prompt}\n\n用户输入：\n{test_input}",
        }

    def get_active_prompt(self, prompt_key: str, default: str | None = None) -> str:
        clean_key = prompt_key.strip()
        cached = self._active_cache.get(clean_key)
        now = monotonic()
        if cached and now - cached[0] < self.CACHE_TTL_SECONDS:
            return cached[1]

        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT content
                    FROM system_prompts
                    WHERE prompt_key = %s AND enabled = TRUE
                    ORDER BY version DESC
                    LIMIT 1
                    """,
                    (clean_key,),
                )
                row = cursor.fetchone()
        if row is None:
            if default is not None:
                return default
            raise AdminError("没有启用的系统提示词", status_code=404)

        content = row["content"]
        self._active_cache[clean_key] = (now, content)
        return content

    def clear_cache(self, prompt_key: str | None = None) -> None:
        if prompt_key:
            self._active_cache.pop(prompt_key, None)
            return
        self._active_cache.clear()

    def _next_version(self, prompt_key: str) -> int:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT COALESCE(MAX(version), 0) + 1 AS next_version FROM system_prompts WHERE prompt_key = %s",
                    (prompt_key,),
                )
                return int(cursor.fetchone()["next_version"])

    def _fetch_prompt(self, prompt_id: int) -> dict[str, Any] | None:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        p.*,
                        uu.nickname AS updated_by_nickname,
                        uu.mobile AS updated_by_mobile
                    FROM system_prompts p
                    LEFT JOIN users uu ON uu.id = p.updated_by
                    WHERE p.id = %s
                    """,
                    (prompt_id,),
                )
                return cursor.fetchone()

    def _require_admin(self, actor: dict[str, Any]) -> None:
        if actor["role"] not in {"admin", "super_admin"}:
            raise AdminError("无后台权限", status_code=403)

    def _serialize_prompt(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "prompt_key": row["prompt_key"],
            "prompt_name": row["prompt_name"],
            "prompt_type": row["prompt_type"],
            "content": row["content"],
            "version": int(row["version"]),
            "enabled": bool(row["enabled"]),
            "remark": row["remark"],
            "updated_by": {
                "id": int(row["updated_by"]),
                "mobile": row.get("updated_by_mobile"),
                "nickname": row.get("updated_by_nickname"),
            }
            if row.get("updated_by") is not None
            else None,
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        }


admin_prompt_service = AdminPromptService()
