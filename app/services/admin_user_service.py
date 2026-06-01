"""Admin user-management service backed by PostgreSQL."""

from __future__ import annotations

from math import ceil
from typing import Any

from app.core.database import get_connection
from app.models.admin import AdminPointsAdjustmentRequest, AdminUserUpdateRequest


class AdminError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class AdminUserService:
    ADMIN_ROLES = {"admin", "super_admin"}

    def list_users(
        self,
        actor: dict[str, Any],
        *,
        mobile: str | None = None,
        role: str | None = None,
        status: int | None = None,
        level: str | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> dict[str, Any]:
        self._require_admin(actor)
        page = max(page, 1)
        page_size = min(max(page_size, 1), 100)

        conditions, params = self._build_filters(actor, mobile, role, status, level)
        where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        offset = (page - 1) * page_size

        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT COUNT(*) AS total
                    FROM users u
                    LEFT JOIN membership_levels ml
                        ON u.points >= ml.min_points
                       AND (ml.max_points IS NULL OR u.points < ml.max_points)
                    {where_sql}
                    """,
                    params,
                )
                total = int(cursor.fetchone()["total"])

                cursor.execute(
                    f"""
                    SELECT
                        u.id,
                        u.mobile,
                        u.nickname,
                        u.avatar_url,
                        u.role,
                        u.status,
                        u.points,
                        u.last_login_at,
                        u.last_login_ip,
                        u.created_at,
                        ml.code AS membership_code,
                        ml.name AS membership_name
                    FROM users u
                    LEFT JOIN membership_levels ml
                        ON u.points >= ml.min_points
                       AND (ml.max_points IS NULL OR u.points < ml.max_points)
                    {where_sql}
                    ORDER BY u.created_at DESC, u.id DESC
                    LIMIT %s OFFSET %s
                    """,
                    [*params, page_size, offset],
                )
                rows = cursor.fetchall()

        return {
            "list": [self._serialize_user(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": ceil(total / page_size) if total else 0,
        }

    def get_user(self, actor: dict[str, Any], user_id: int) -> dict[str, Any]:
        self._require_admin(actor)
        with get_connection() as conn:
            with conn.cursor() as cursor:
                row = self._fetch_user(cursor, user_id)
        if row is None:
            raise AdminError("用户不存在", status_code=404)
        self._ensure_can_manage(actor, row)
        return self._serialize_user(row)

    def update_user(
        self,
        actor: dict[str, Any],
        user_id: int,
        payload: AdminUserUpdateRequest,
    ) -> dict[str, Any]:
        self._require_admin(actor)
        with get_connection() as conn:
            with conn.cursor() as cursor:
                target = self._fetch_user(cursor, user_id, for_update=True)
                if target is None:
                    raise AdminError("用户不存在", status_code=404)
                self._ensure_can_manage(actor, target)
                self._ensure_update_allowed(actor, target, payload)

                assignments: list[str] = []
                params: list[Any] = []
                if payload.nickname is not None:
                    assignments.append("nickname = %s")
                    params.append(payload.nickname.strip())
                if payload.role is not None:
                    assignments.append("role = %s")
                    params.append(payload.role)
                if payload.status is not None:
                    self._ensure_status_change_allowed(actor, target, payload.status)
                    assignments.append("status = %s")
                    params.append(payload.status)

                cursor.execute(
                    f"UPDATE users SET {', '.join(assignments)} WHERE id = %s",
                    [*params, user_id],
                )
                if payload.status is not None:
                    self._revoke_sessions_if_disabled(cursor, user_id, payload.status)
                updated = self._fetch_user(cursor, user_id)

        return self._serialize_user(updated)

    def update_status(
        self,
        actor: dict[str, Any],
        user_id: int,
        status: int,
    ) -> dict[str, Any]:
        self._require_admin(actor)
        with get_connection() as conn:
            with conn.cursor() as cursor:
                target = self._fetch_user(cursor, user_id, for_update=True)
                if target is None:
                    raise AdminError("用户不存在", status_code=404)
                self._ensure_can_manage(actor, target)
                self._ensure_status_change_allowed(actor, target, status)
                cursor.execute("UPDATE users SET status = %s WHERE id = %s", (status, user_id))
                self._revoke_sessions_if_disabled(cursor, user_id, status)
                updated = self._fetch_user(cursor, user_id)
        return self._serialize_user(updated)

    def adjust_points(
        self,
        actor: dict[str, Any],
        user_id: int,
        payload: AdminPointsAdjustmentRequest,
    ) -> dict[str, Any]:
        self._require_admin(actor)
        with get_connection() as conn:
            with conn.cursor() as cursor:
                target = self._fetch_user(cursor, user_id, for_update=True)
                if target is None:
                    raise AdminError("用户不存在", status_code=404)
                self._ensure_can_manage(actor, target)

                before_points = int(target["points"])
                if payload.change_type == "add":
                    change_amount = int(payload.change_amount or 0)
                    after_points = before_points + change_amount
                elif payload.change_type == "subtract":
                    change_amount = int(payload.change_amount or 0)
                    after_points = before_points - change_amount
                else:
                    target_points = int(payload.target_points or 0)
                    if target_points == before_points:
                        raise AdminError("调整前后积分一致，无需修改")
                    change_amount = abs(target_points - before_points)
                    after_points = target_points

                if after_points < 0:
                    raise AdminError("积分不能小于 0")

                cursor.execute(
                    "UPDATE users SET points = %s WHERE id = %s",
                    (after_points, user_id),
                )
                cursor.execute(
                    """
                    INSERT INTO user_points_logs (
                        user_id,
                        change_type,
                        change_amount,
                        before_points,
                        after_points,
                        reason,
                        operator_id
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        user_id,
                        payload.change_type,
                        change_amount,
                        before_points,
                        after_points,
                        payload.reason.strip(),
                        actor["id"],
                    ),
                )
                updated = self._fetch_user(cursor, user_id)

        return self._serialize_user(updated)

    def list_points_logs(
        self,
        actor: dict[str, Any],
        user_id: int,
        *,
        page: int = 1,
        page_size: int = 10,
    ) -> dict[str, Any]:
        self._require_admin(actor)
        page = max(page, 1)
        page_size = min(max(page_size, 1), 100)

        with get_connection() as conn:
            with conn.cursor() as cursor:
                target = self._fetch_user(cursor, user_id)
                if target is None:
                    raise AdminError("用户不存在", status_code=404)
                self._ensure_can_manage(actor, target)

                cursor.execute(
                    "SELECT COUNT(*) AS total FROM user_points_logs WHERE user_id = %s",
                    (user_id,),
                )
                total = int(cursor.fetchone()["total"])
                cursor.execute(
                    """
                    SELECT
                        l.id,
                        l.user_id,
                        l.change_type,
                        l.change_amount,
                        l.before_points,
                        l.after_points,
                        l.reason,
                        l.operator_id,
                        l.created_at,
                        o.mobile AS operator_mobile,
                        o.nickname AS operator_nickname
                    FROM user_points_logs l
                    LEFT JOIN users o ON o.id = l.operator_id
                    WHERE l.user_id = %s
                    ORDER BY l.created_at DESC, l.id DESC
                    LIMIT %s OFFSET %s
                    """,
                    (user_id, page_size, (page - 1) * page_size),
                )
                logs = cursor.fetchall()

        return {
            "list": [self._serialize_points_log(row) for row in logs],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": ceil(total / page_size) if total else 0,
        }

    def _build_filters(
        self,
        actor: dict[str, Any],
        mobile: str | None,
        role: str | None,
        status: int | None,
        level: str | None,
    ) -> tuple[list[str], list[Any]]:
        conditions: list[str] = []
        params: list[Any] = []

        if actor["role"] == "admin":
            conditions.append("u.role = 'user'")
        elif role:
            conditions.append("u.role = %s")
            params.append(role)

        if mobile:
            conditions.append("u.mobile ILIKE %s")
            params.append(f"%{mobile.strip()}%")
        if status is not None:
            conditions.append("u.status = %s")
            params.append(status)
        if level:
            conditions.append("ml.code = %s")
            params.append(level)
        return conditions, params

    def _fetch_user(
        self,
        cursor: Any,
        user_id: int,
        *,
        for_update: bool = False,
    ) -> dict[str, Any] | None:
        lock_clause = "FOR UPDATE OF u" if for_update else ""
        cursor.execute(
            f"""
            SELECT
                u.id,
                u.mobile,
                u.nickname,
                u.avatar_url,
                u.role,
                u.status,
                u.points,
                u.last_login_at,
                u.last_login_ip,
                u.created_at,
                ml.code AS membership_code,
                ml.name AS membership_name
            FROM users u
            LEFT JOIN membership_levels ml
                ON u.points >= ml.min_points
               AND (ml.max_points IS NULL OR u.points < ml.max_points)
            WHERE u.id = %s
            {lock_clause}
            """,
            (user_id,),
        )
        return cursor.fetchone()

    def _require_admin(self, actor: dict[str, Any]) -> None:
        if actor["role"] not in self.ADMIN_ROLES:
            raise AdminError("无后台权限", status_code=403)

    def _ensure_can_manage(self, actor: dict[str, Any], target: dict[str, Any]) -> None:
        if actor["role"] == "super_admin":
            return
        if actor["role"] == "admin" and target["role"] == "user":
            return
        raise AdminError("无权管理该用户", status_code=403)

    def _ensure_update_allowed(
        self,
        actor: dict[str, Any],
        target: dict[str, Any],
        payload: AdminUserUpdateRequest,
    ) -> None:
        if actor["role"] == "super_admin":
            return
        if payload.role is not None:
            raise AdminError("管理员不能修改用户角色", status_code=403)
        if target["role"] != "user":
            raise AdminError("管理员只能管理普通用户", status_code=403)

    def _ensure_status_change_allowed(
        self,
        actor: dict[str, Any],
        target: dict[str, Any],
        status: int,
    ) -> None:
        if actor["id"] == target["id"] and status == 0:
            raise AdminError("不能禁用当前登录账号")
        if actor["role"] == "admin" and target["role"] != "user":
            raise AdminError("管理员只能管理普通用户", status_code=403)

    def _revoke_sessions_if_disabled(self, cursor: Any, user_id: int, status: int) -> None:
        if status == 0:
            cursor.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))

    def _serialize_user(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "mobile": row["mobile"],
            "phone": row["mobile"],
            "nickname": row["nickname"],
            "avatar_url": row["avatar_url"],
            "role": row["role"],
            "status": int(row["status"]),
            "points": int(row["points"]),
            "membership_level": {
                "code": row["membership_code"],
                "name": row["membership_name"],
            }
            if row["membership_code"]
            else None,
            "last_login_at": (
                row["last_login_at"].isoformat() if row["last_login_at"] else None
            ),
            "last_login_ip": row["last_login_ip"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        }

    def _serialize_points_log(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "user_id": int(row["user_id"]),
            "change_type": row["change_type"],
            "change_amount": int(row["change_amount"]),
            "before_points": int(row["before_points"]),
            "after_points": int(row["after_points"]),
            "reason": row["reason"],
            "operator": {
                "id": int(row["operator_id"]),
                "mobile": row["operator_mobile"],
                "nickname": row["operator_nickname"],
            }
            if row["operator_id"] is not None
            else None,
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        }


admin_user_service = AdminUserService()
