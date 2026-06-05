"""AI model catalog and usage tracking service."""

from __future__ import annotations

import re
from math import ceil
from time import monotonic
from typing import Any

from loguru import logger
from psycopg.types.json import Jsonb

from app.config import config
from app.core.database import get_connection
from app.services.admin_user_service import AdminError


class ModelCatalogError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class ModelService:
    CACHE_TTL_SECONDS = 30
    SUPPORTED_PROVIDERS = {"dashscope", "deepseek"}
    MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")

    def __init__(self) -> None:
        self._available_cache: tuple[float, list[dict[str, Any]]] | None = None

    def list_available_models(self, *, use_cache: bool = True) -> list[dict[str, Any]]:
        cached = self._available_cache
        now = monotonic()
        if use_cache and cached and now - cached[0] < self.CACHE_TTL_SECONDS:
            return cached[1]

        try:
            with get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT *
                        FROM ai_models
                        WHERE enabled = TRUE AND is_deleted = FALSE
                        ORDER BY is_default DESC, sort_order ASC, id ASC
                        """
                    )
                    rows = cursor.fetchall()
        except Exception as exc:
            logger.error(f"Failed to load model whitelist: {exc}")
            raise ModelCatalogError("模型白名单暂不可用，请稍后再试", status_code=503) from exc

        models = [self._serialize_model(row) for row in rows]
        if not models:
            raise ModelCatalogError("暂无可用模型，请联系管理员", status_code=503)

        if use_cache:
            self._available_cache = (now, models)
        return models

    def default_model(self, *, use_cache: bool = True) -> dict[str, Any]:
        models = self.list_available_models(use_cache=use_cache)
        for model in models:
            if model["isDefault"]:
                return model
        return models[0]

    def resolve_chat_model(self, requested_model: str | None = None) -> dict[str, Any]:
        clean_model = (requested_model or "").strip()
        if not clean_model:
            return self.default_model(use_cache=False)

        requested_provider: str | None = None
        requested_model_id = clean_model
        if ":" in clean_model:
            provider_part, model_part = clean_model.split(":", 1)
            try:
                requested_provider = self._clean_provider(provider_part)
                requested_model_id = self._clean_model_id(model_part)
            except AdminError as exc:
                raise ModelCatalogError(exc.message, status_code=exc.status_code) from exc

        matches: list[dict[str, Any]] = []
        for model in self.list_available_models(use_cache=False):
            if requested_provider:
                if model["provider"] == requested_provider and model["modelId"] == requested_model_id:
                    return model
            elif model["modelId"] == requested_model_id or model.get("modelKey") == clean_model:
                matches.append(model)

        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ModelCatalogError("模型供应商不明确，请重新选择模型", status_code=400)

        raise ModelCatalogError("模型不在白名单或已停用", status_code=400)

    def list_models(
        self,
        actor: dict[str, Any],
        *,
        enabled: bool | None = None,
        keyword: str | None = None,
        include_deleted: bool = False,
        page: int = 1,
        page_size: int = 10,
    ) -> dict[str, Any]:
        self._require_admin(actor)
        page = max(page, 1)
        page_size = min(max(page_size, 1), 100)

        conditions: list[str] = []
        params: list[Any] = []
        if not include_deleted:
            conditions.append("m.is_deleted = FALSE")
        if enabled is not None:
            conditions.append("m.enabled = %s")
            params.append(enabled)
        if keyword:
            like = f"%{keyword.strip()}%"
            conditions.append(
                "(m.model_id ILIKE %s OR m.display_name ILIKE %s OR m.provider ILIKE %s)"
            )
            params.extend([like, like, like])
        where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(f"SELECT COUNT(*) AS total FROM ai_models m {where_sql}", params)
                total = int(cursor.fetchone()["total"])
                cursor.execute(
                    f"""
                    SELECT
                        m.*,
                        uu.nickname AS updated_by_nickname,
                        uu.mobile AS updated_by_mobile,
                        COALESCE(stats.usage_total, 0) AS usage_total,
                        COALESCE(stats.usage_today, 0) AS usage_today,
                        COALESCE(stats.usage_month, 0) AS usage_month,
                        COALESCE(stats.failure_total, 0) AS failure_total,
                        stats.avg_duration_ms,
                        stats.last_used_at
                    FROM ai_models m
                    LEFT JOIN users uu ON uu.id = m.updated_by
                    LEFT JOIN (
                        SELECT
                            ai_model_id,
                            COUNT(*) AS usage_total,
                            COUNT(*) FILTER (WHERE created_at >= CURRENT_DATE) AS usage_today,
                            COUNT(*) FILTER (
                                WHERE created_at >= date_trunc('month', CURRENT_TIMESTAMP)
                            ) AS usage_month,
                            COUNT(*) FILTER (WHERE success = FALSE) AS failure_total,
                            ROUND(AVG(duration_ms)) AS avg_duration_ms,
                            MAX(created_at) AS last_used_at
                        FROM model_usage_logs
                        GROUP BY ai_model_id
                    ) stats ON stats.ai_model_id = m.id
                    {where_sql}
                    ORDER BY m.is_default DESC, m.sort_order ASC, m.id ASC
                    LIMIT %s OFFSET %s
                    """,
                    [*params, page_size, (page - 1) * page_size],
                )
                rows = cursor.fetchall()

        return {
            "list": [self._serialize_model(row, include_stats=True) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": ceil(total / page_size) if total else 0,
        }

    def get_model(self, actor: dict[str, Any], model_pk: int) -> dict[str, Any]:
        self._require_admin(actor)
        row = self._fetch_model(model_pk)
        if row is None:
            raise AdminError("模型不存在", status_code=404)
        return self._serialize_model(row, include_stats=True)

    def create_model(
        self,
        actor: dict[str, Any],
        *,
        model_id: str,
        display_name: str,
        provider: str = "dashscope",
        enabled: bool = True,
        is_default: bool = False,
        sort_order: int = 100,
        min_membership_level: str | None = None,
        access_scope: str = "all",
        remark: str | None = None,
    ) -> dict[str, Any]:
        self._require_admin(actor)
        clean_provider = provider.strip() or "dashscope"
        clean_model_id = model_id.strip()
        if not clean_model_id:
            raise AdminError("模型 ID 不能为空", status_code=400)
        clean_provider = self._clean_provider(clean_provider)
        clean_model_id = self._clean_model_id(clean_model_id)
        if is_default and not enabled:
            raise AdminError("停用模型不能设为默认模型", status_code=400)

        with get_connection() as conn:
            with conn.cursor() as cursor:
                if is_default:
                    cursor.execute(
                        """
                        UPDATE ai_models
                        SET is_default = FALSE
                        WHERE is_deleted = FALSE
                        """,
                    )
                try:
                    cursor.execute(
                        """
                        INSERT INTO ai_models (
                            provider,
                            model_id,
                            display_name,
                            enabled,
                            is_default,
                            sort_order,
                            min_membership_level,
                            access_scope,
                            remark,
                            created_by,
                            updated_by
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (
                            clean_provider,
                            clean_model_id,
                            display_name.strip(),
                            enabled,
                            is_default,
                            sort_order,
                            self._clean_optional(min_membership_level),
                            (access_scope or "all").strip() or "all",
                            self._clean_optional(remark),
                            actor["id"],
                            actor["id"],
                        ),
                    )
                except Exception as exc:
                    if "uniq_ai_models_provider_model_active" in str(exc):
                        raise AdminError("同供应商下模型 ID 已存在", status_code=409) from exc
                    raise
                model_pk = int(cursor.fetchone()["id"])

        self.clear_cache()
        return self.get_model(actor, model_pk)

    def update_model(
        self,
        actor: dict[str, Any],
        model_pk: int,
        *,
        model_id: str | None = None,
        display_name: str | None = None,
        provider: str | None = None,
        enabled: bool | None = None,
        is_default: bool | None = None,
        sort_order: int | None = None,
        min_membership_level: str | None = None,
        access_scope: str | None = None,
        remark: str | None = None,
    ) -> dict[str, Any]:
        self._require_admin(actor)
        current = self._fetch_model(model_pk)
        if current is None:
            raise AdminError("模型不存在", status_code=404)
        if current["is_deleted"]:
            raise AdminError("已删除模型不能编辑", status_code=400)
        if enabled is False and current["is_default"]:
            raise AdminError("默认模型不能停用，请先设置其他默认模型", status_code=400)

        target_provider = (
            self._clean_provider(provider) if provider is not None else current["provider"]
        )
        target_default = bool(is_default) if is_default is not None else bool(current["is_default"])
        assignments = ["updated_by = %s"]
        params: list[Any] = [actor["id"]]
        if model_id is not None:
            assignments.append("model_id = %s")
            params.append(self._clean_model_id(model_id))
        if display_name is not None:
            assignments.append("display_name = %s")
            params.append(display_name.strip())
        if provider is not None:
            assignments.append("provider = %s")
            params.append(target_provider)
        if enabled is not None:
            assignments.append("enabled = %s")
            params.append(enabled)
        if is_default is not None:
            assignments.append("is_default = %s")
            params.append(target_default)
            if target_default and enabled is False:
                raise AdminError("停用模型不能设为默认模型", status_code=400)
        if sort_order is not None:
            assignments.append("sort_order = %s")
            params.append(sort_order)
        if min_membership_level is not None:
            assignments.append("min_membership_level = %s")
            params.append(self._clean_optional(min_membership_level))
        if access_scope is not None:
            assignments.append("access_scope = %s")
            params.append((access_scope or "all").strip() or "all")
        if remark is not None:
            assignments.append("remark = %s")
            params.append(self._clean_optional(remark))

        with get_connection() as conn:
            with conn.cursor() as cursor:
                if target_default:
                    cursor.execute(
                        """
                        UPDATE ai_models
                        SET is_default = FALSE
                        WHERE id <> %s AND is_deleted = FALSE
                        """,
                        (model_pk,),
                    )
                    if enabled is None and not current["enabled"]:
                        assignments.append("enabled = TRUE")
                try:
                    cursor.execute(
                        f"""
                        UPDATE ai_models
                        SET {', '.join(assignments)}
                        WHERE id = %s
                        """,
                        [*params, model_pk],
                    )
                except Exception as exc:
                    if "uniq_ai_models_provider_model_active" in str(exc):
                        raise AdminError("同供应商下模型 ID 已存在", status_code=409) from exc
                    raise

        self.clear_cache()
        return self.get_model(actor, model_pk)

    def set_enabled(self, actor: dict[str, Any], model_pk: int, enabled: bool) -> dict[str, Any]:
        return self.update_model(actor, model_pk, enabled=enabled)

    def set_default(self, actor: dict[str, Any], model_pk: int) -> dict[str, Any]:
        return self.update_model(actor, model_pk, enabled=True, is_default=True)

    def delete_model(self, actor: dict[str, Any], model_pk: int) -> dict[str, Any]:
        self._require_admin(actor)
        current = self._fetch_model(model_pk)
        if current is None:
            raise AdminError("模型不存在", status_code=404)
        if current["is_default"]:
            raise AdminError("默认模型不能删除，请先设置其他默认模型", status_code=400)

        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE ai_models
                    SET is_deleted = TRUE,
                        enabled = FALSE,
                        is_default = FALSE,
                        updated_by = %s
                    WHERE id = %s
                    """,
                    (actor["id"], model_pk),
                )

        self.clear_cache()
        return {"id": model_pk, "deleted": True}

    def usage_detail(self, actor: dict[str, Any], model_pk: int, days: int = 30) -> dict[str, Any]:
        self._require_admin(actor)
        model = self.get_model(actor, model_pk)
        days = min(max(days, 1), 365)
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        COUNT(*) AS total,
                        COUNT(*) FILTER (WHERE success = TRUE) AS success_total,
                        COUNT(*) FILTER (WHERE success = FALSE) AS failure_total,
                        ROUND(AVG(duration_ms)) AS avg_duration_ms,
                        MAX(created_at) AS last_used_at
                    FROM model_usage_logs
                    WHERE ai_model_id = %s
                      AND created_at >= CURRENT_TIMESTAMP - (%s::text || ' days')::interval
                    """,
                    (model_pk, days),
                )
                summary = cursor.fetchone()
                cursor.execute(
                    """
                    SELECT
                        u.id AS user_id,
                        u.mobile,
                        u.nickname,
                        COUNT(*) AS usage_total,
                        MAX(l.created_at) AS last_used_at
                    FROM model_usage_logs l
                    LEFT JOIN users u ON u.id = l.user_id
                    WHERE l.ai_model_id = %s
                      AND l.created_at >= CURRENT_TIMESTAMP - (%s::text || ' days')::interval
                    GROUP BY u.id, u.mobile, u.nickname
                    ORDER BY usage_total DESC, last_used_at DESC
                    LIMIT 10
                    """,
                    (model_pk, days),
                )
                top_users = cursor.fetchall()

        return {
            "model": model,
            "days": days,
            "summary": {
                "total": int(summary["total"] or 0),
                "successTotal": int(summary["success_total"] or 0),
                "failureTotal": int(summary["failure_total"] or 0),
                "avgDurationMs": self._optional_int(summary.get("avg_duration_ms")),
                "lastUsedAt": self._iso(summary.get("last_used_at")),
            },
            "topUsers": [
                {
                    "userId": int(row["user_id"]) if row.get("user_id") is not None else None,
                    "mobile": row.get("mobile"),
                    "nickname": row.get("nickname"),
                    "usageTotal": int(row["usage_total"] or 0),
                    "lastUsedAt": self._iso(row.get("last_used_at")),
                }
                for row in top_users
            ],
        }

    def record_usage(
        self,
        *,
        user_id: int | None,
        model: dict[str, Any],
        session_id: str | None,
        mode: str,
        prompt_template: str | None = None,
        success: bool = True,
        duration_ms: int | None = None,
        error_message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        try:
            with get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO model_usage_logs (
                            user_id,
                            ai_model_id,
                            provider,
                            model_id,
                            session_id,
                            mode,
                            prompt_template,
                            success,
                            duration_ms,
                            error_message,
                            metadata
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            user_id,
                            model.get("id"),
                            model.get("provider") or "dashscope",
                            model.get("modelId") or config.rag_model,
                            session_id,
                            mode,
                            prompt_template,
                            success,
                            duration_ms,
                            (error_message or "")[:1000] or None,
                            Jsonb(metadata or {}),
                        ),
                    )
        except Exception as exc:
            logger.warning(f"Failed to record model usage: {exc}")

    def clear_cache(self) -> None:
        self._available_cache = None

    def _fetch_model(self, model_pk: int) -> dict[str, Any] | None:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        m.*,
                        uu.nickname AS updated_by_nickname,
                        uu.mobile AS updated_by_mobile,
                        COALESCE(stats.usage_total, 0) AS usage_total,
                        COALESCE(stats.usage_today, 0) AS usage_today,
                        COALESCE(stats.usage_month, 0) AS usage_month,
                        COALESCE(stats.failure_total, 0) AS failure_total,
                        stats.avg_duration_ms,
                        stats.last_used_at
                    FROM ai_models m
                    LEFT JOIN users uu ON uu.id = m.updated_by
                    LEFT JOIN (
                        SELECT
                            ai_model_id,
                            COUNT(*) AS usage_total,
                            COUNT(*) FILTER (WHERE created_at >= CURRENT_DATE) AS usage_today,
                            COUNT(*) FILTER (
                                WHERE created_at >= date_trunc('month', CURRENT_TIMESTAMP)
                            ) AS usage_month,
                            COUNT(*) FILTER (WHERE success = FALSE) AS failure_total,
                            ROUND(AVG(duration_ms)) AS avg_duration_ms,
                            MAX(created_at) AS last_used_at
                        FROM model_usage_logs
                        GROUP BY ai_model_id
                    ) stats ON stats.ai_model_id = m.id
                    WHERE m.id = %s
                    """,
                    (model_pk,),
                )
                return cursor.fetchone()

    def _serialize_model(self, row: dict[str, Any], *, include_stats: bool = False) -> dict[str, Any]:
        data = {
            "id": int(row["id"]),
            "provider": row["provider"],
            "modelId": row["model_id"],
            "modelKey": self._model_key(row["provider"], row["model_id"]),
            "displayName": row["display_name"],
            "enabled": bool(row["enabled"]),
            "isDefault": bool(row["is_default"]),
            "isDeleted": bool(row["is_deleted"]),
            "sortOrder": int(row["sort_order"]),
            "minMembershipLevel": row.get("min_membership_level"),
            "accessScope": row.get("access_scope") or "all",
            "remark": row.get("remark"),
            "updatedBy": {
                "id": int(row["updated_by"]),
                "mobile": row.get("updated_by_mobile"),
                "nickname": row.get("updated_by_nickname"),
            }
            if row.get("updated_by") is not None
            else None,
            "createdAt": self._iso(row.get("created_at")),
            "updatedAt": self._iso(row.get("updated_at")),
        }
        if include_stats:
            data["usage"] = {
                "total": int(row.get("usage_total") or 0),
                "today": int(row.get("usage_today") or 0),
                "month": int(row.get("usage_month") or 0),
                "failureTotal": int(row.get("failure_total") or 0),
                "avgDurationMs": self._optional_int(row.get("avg_duration_ms")),
                "lastUsedAt": self._iso(row.get("last_used_at")),
            }
        return data

    def _fallback_model(self) -> dict[str, Any]:
        model_id = config.rag_model or config.dashscope_model or "qwen3.7-plus"
        return {
            "id": None,
            "provider": "dashscope",
            "modelId": model_id,
            "modelKey": self._model_key("dashscope", model_id),
            "displayName": model_id,
            "enabled": True,
            "isDefault": True,
            "isDeleted": False,
            "sortOrder": 0,
            "minMembershipLevel": None,
            "accessScope": "all",
            "remark": "配置兜底模型",
            "updatedBy": None,
            "createdAt": None,
            "updatedAt": None,
        }

    def _require_admin(self, actor: dict[str, Any]) -> None:
        if actor["role"] not in {"admin", "super_admin"}:
            raise AdminError("无后台权限", status_code=403)

    def _clean_optional(self, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    def _clean_provider(self, value: str | None) -> str:
        provider = (value or "dashscope").strip().lower()
        if provider not in self.SUPPORTED_PROVIDERS:
            raise AdminError("当前仅支持 dashscope 或 deepseek 模型供应商", status_code=400)
        return provider

    def _model_key(self, provider: str, model_id: str) -> str:
        return f"{provider}:{model_id}"

    def _clean_model_id(self, value: str) -> str:
        model_id = value.strip()
        if not self.MODEL_ID_PATTERN.fullmatch(model_id):
            raise AdminError("模型 ID 只能包含字母、数字、点、下划线和短横线", status_code=400)
        return model_id

    def _optional_int(self, value: Any) -> int | None:
        if value is None:
            return None
        return int(value)

    def _iso(self, value: Any) -> str | None:
        return value.isoformat() if value else None


model_service = ModelService()
