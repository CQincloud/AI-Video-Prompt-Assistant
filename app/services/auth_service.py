"""Phone-code authentication and Aliyun SMS delivery backed by PostgreSQL."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg
from loguru import logger

from app.config import config
from app.core.database import get_connection

PHONE_RE = re.compile(r"^1[3-9]\d{9}$")


class AliyunAccessKeyCredential:
    """Compatibility wrapper for SDK versions expecting provider_name."""

    def __init__(self, access_key_id: str, access_key_secret: str):
        self._access_key_id = access_key_id
        self._access_key_secret = access_key_secret

    def get_credential(self):
        from alibabacloud_credentials import models as credential_models

        credential = credential_models.CredentialModel(
            access_key_id=self._access_key_id,
            access_key_secret=self._access_key_secret,
            security_token="",
            type="access_key",
        )
        credential.provider_name = ""
        return credential

    async def get_credential_async(self):
        return self.get_credential()

    def get_access_key_id(self) -> str:
        return self._access_key_id

    async def get_access_key_id_async(self) -> str:
        return self._access_key_id

    def get_access_key_secret(self) -> str:
        return self._access_key_secret

    async def get_access_key_secret_async(self) -> str:
        return self._access_key_secret

    def get_security_token(self) -> str:
        return ""

    async def get_security_token_async(self) -> str:
        return ""

    def get_bearer_token(self) -> str:
        return ""

    async def get_bearer_token_async(self) -> str:
        return ""

    def get_type(self) -> str:
        return "access_key"

    async def get_type_async(self) -> str:
        return "access_key"


class AuthError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class AuthService:
    SIGNUP_BONUS_POINTS = 1000

    def __init__(self):
        self._schema_ready = False

    def _connect(self) -> psycopg.Connection[dict[str, Any]]:
        return get_connection()

    def _mask_phone(self, phone: str | None) -> str:
        if not phone:
            return "<empty>"
        if len(phone) < 7:
            return "<redacted>"
        return f"{phone[:3]}****{phone[-4:]}"

    def _mask_identifier(self, scope: str, identifier: str | None) -> str:
        if scope == "mobile":
            return self._mask_phone(identifier)
        if scope == "ip":
            return "<redacted-ip>"
        return "<redacted>"

    def mark_schema_ready(self) -> None:
        self._schema_ready = True

    def ensure_schema(self) -> None:
        if not config.database_allow_untracked_schema_ensure:
            raise RuntimeError(
                "Runtime auth schema changes are disabled. Run database migrations first."
            )
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS auth_login_attempts (
                        id BIGSERIAL PRIMARY KEY,
                        mobile VARCHAR(20) NOT NULL,
                        ip VARCHAR(45),
                        success BOOLEAN NOT NULL DEFAULT FALSE,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_auth_login_attempts_mobile_created
                    ON auth_login_attempts(mobile, created_at DESC)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_auth_login_attempts_ip_created
                    ON auth_login_attempts(ip, created_at DESC)
                    WHERE ip IS NOT NULL
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS auth_login_blocks (
                        scope VARCHAR(20) NOT NULL
                            CHECK (scope IN ('mobile', 'ip')),
                        identifier TEXT NOT NULL,
                        blocked_until TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (scope, identifier)
                    )
                    """
                )
        self._schema_ready = True

    def _ensure_schema_ready(self) -> None:
        if not self._schema_ready:
            self.ensure_schema()

    def validate_phone(self, phone: str) -> str:
        normalized = phone.strip()
        if not PHONE_RE.match(normalized):
            raise AuthError("请输入正确的手机号")
        return normalized

    def send_code(self, phone: str, ip: str | None = None) -> dict[str, Any]:
        phone = self.validate_phone(phone)
        self._ensure_schema_ready()
        now = self._now()

        self._assert_send_limits(phone, ip, now)
        code = self._generate_code()
        code_hash = self._hash_code(phone, code)
        expires_at = now + timedelta(minutes=config.sms_code_ttl_minutes)

        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE sms_codes SET used = TRUE WHERE mobile = %s AND used = FALSE",
                    (phone,),
                )
                cursor.execute(
                    """
                    INSERT INTO sms_codes (mobile, code_hash, expires_at, used, created_at, ip)
                    VALUES (%s, %s, %s, FALSE, %s, %s)
                    """,
                    (phone, code_hash, expires_at, now, ip),
                )
                self._deliver_sms(phone, code)

        response: dict[str, Any] = {
            "sent": True,
            "expires_in": config.sms_code_ttl_minutes * 60,
        }
        if self._sms_provider() == "mock" or (
            self._sms_provider() == "console" and config.debug
        ):
            response["debug_code"] = code
        return response

    def login_with_code(
        self,
        phone: str,
        code: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        phone = self.validate_phone(phone)
        code = code.strip()
        code_length = self._code_length()
        if not re.fullmatch(rf"\d{{{code_length}}}", code):
            raise AuthError(f"请输入 {code_length} 位短信验证码")

        now = self._now()
        code_hash = self._hash_code(phone, code)
        self._ensure_schema_ready()

        with self._connect() as conn:
            with conn.cursor() as cursor:
                self._assert_login_allowed(cursor, phone, ip, now)
                cursor.execute(
                    """
                    SELECT id, code_hash
                    FROM sms_codes
                    WHERE mobile = %s
                      AND used = FALSE
                      AND expires_at >= %s
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (phone, now),
                )
                row = cursor.fetchone()

                if not row or not hmac.compare_digest(row["code_hash"], code_hash):
                    self._record_login_attempt(cursor, phone, ip, success=False, now=now)
                    should_block = self._block_if_login_limits_exceeded(cursor, phone, ip, now)
                    conn.commit()
                    if should_block:
                        raise AuthError("验证码错误次数过多，请稍后再试", status_code=429)
                    raise AuthError("验证码错误或已过期", status_code=401)

                cursor.execute("UPDATE sms_codes SET used = TRUE WHERE id = %s", (row["id"],))

                cursor.execute("SELECT id, status FROM users WHERE mobile = %s", (phone,))
                user = cursor.fetchone()
                if user is None:
                    cursor.execute(
                        """
                        INSERT INTO users (mobile, last_login_at, last_login_ip, points)
                        VALUES (%s, %s, %s, %s)
                        RETURNING id
                        """,
                        (phone, now, ip, self.SIGNUP_BONUS_POINTS),
                    )
                    user_id = int(cursor.fetchone()["id"])
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
                        VALUES (%s, 'add', %s, 0, %s, %s, NULL)
                        """,
                        (
                            user_id,
                            self.SIGNUP_BONUS_POINTS,
                            self.SIGNUP_BONUS_POINTS,
                            "手机号注册赠送 AI 能量",
                        ),
                    )
                else:
                    user_id = int(user["id"])
                    if int(user["status"]) == 0:
                        raise AuthError("账号已被禁用", status_code=403)
                    cursor.execute(
                        """
                        UPDATE users
                        SET last_login_at = %s,
                            last_login_ip = %s
                        WHERE id = %s
                        """,
                        (now, ip, user_id),
                    )

                token = secrets.token_urlsafe(32)
                token_hash = self._hash_token(token)
                expires_at = now + timedelta(hours=config.auth_session_ttl_hours)
                cursor.execute(
                    """
                    INSERT INTO sessions
                        (token_hash, user_id, created_at, expires_at, last_seen_at, ip, user_agent)
                    VALUES
                        (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (token_hash, user_id, now, expires_at, now, ip, user_agent),
                )
                self._record_login_attempt(cursor, phone, ip, success=True, now=now)
                self._clear_login_blocks(cursor, phone, ip)

                user_data = self.get_user_by_id(user_id, conn)

        if user_data is None:
            raise AuthError("登录状态创建失败", status_code=500)
        return token, user_data

    def get_user_by_token(self, token: str | None) -> dict[str, Any] | None:
        if not token:
            return None

        token_hash = self._hash_token(token)
        now = self._now()
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT user_id
                    FROM sessions
                    WHERE token_hash = %s
                      AND expires_at >= %s
                    """,
                    (token_hash, now),
                )
                row = cursor.fetchone()
                if row is None:
                    return None

                user = self.get_user_by_id(int(row["user_id"]), conn)
                if user is None:
                    cursor.execute("DELETE FROM sessions WHERE token_hash = %s", (token_hash,))
                    return None
                if user["status"] == 0:
                    cursor.execute("DELETE FROM sessions WHERE user_id = %s", (row["user_id"],))
                    return None

                cursor.execute(
                    "UPDATE sessions SET last_seen_at = %s WHERE token_hash = %s",
                    (now, token_hash),
                )
                return user

    def logout(self, token: str | None) -> None:
        if not token:
            return
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM sessions WHERE token_hash = %s",
                    (self._hash_token(token),),
                )

    def get_user_by_id(
        self,
        user_id: int,
        conn: psycopg.Connection[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        owns_conn = conn is None
        active_conn = conn or self._connect()
        try:
            with active_conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        id,
                        mobile,
                        nickname,
                        role,
                        status,
                        points,
                        created_at,
                        last_login_at,
                        last_login_ip
                    FROM users
                    WHERE id = %s
                    """,
                    (user_id,),
                )
                row = cursor.fetchone()
                return self._serialize_user(row) if row else None
        finally:
            if owns_conn:
                active_conn.close()

    def _assert_send_limits(self, phone: str, ip: str | None, now: datetime) -> None:
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT created_at
                    FROM sms_codes
                    WHERE mobile = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (phone,),
                )
                recent = cursor.fetchone()
                if recent and now - recent["created_at"] < timedelta(
                    seconds=config.sms_resend_interval_seconds
                ):
                    raise AuthError("验证码发送过于频繁，请稍后再试", status_code=429)

                cursor.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM sms_codes
                    WHERE mobile = %s
                      AND created_at >= %s
                    """,
                    (phone, now - timedelta(days=1)),
                )
                day_count = cursor.fetchone()["count"]
                if int(day_count) >= config.sms_daily_limit_per_phone:
                    raise AuthError("今日验证码发送次数已达上限", status_code=429)

                if ip:
                    cursor.execute(
                        """
                        SELECT COUNT(*) AS count
                        FROM sms_codes
                        WHERE ip = %s
                          AND created_at >= %s
                        """,
                        (ip, now - timedelta(hours=1)),
                    )
                    hour_count = cursor.fetchone()["count"]
                    if int(hour_count) >= config.sms_hourly_limit_per_ip:
                        raise AuthError("当前网络请求过于频繁，请稍后再试", status_code=429)

    def _assert_login_allowed(
        self,
        cursor: psycopg.Cursor[dict[str, Any]],
        phone: str,
        ip: str | None,
        now: datetime,
    ) -> None:
        if self._get_active_block(cursor, "mobile", phone, now) is not None:
            raise AuthError("验证码错误次数过多，请稍后再试", status_code=429)
        if ip and self._get_active_block(cursor, "ip", ip, now) is not None:
            raise AuthError("当前网络登录失败次数过多，请稍后再试", status_code=429)

    def _get_active_block(
        self,
        cursor: psycopg.Cursor[dict[str, Any]],
        scope: str,
        identifier: str,
        now: datetime,
    ) -> datetime | None:
        cursor.execute(
            """
            SELECT blocked_until
            FROM auth_login_blocks
            WHERE scope = %s
              AND identifier = %s
            """,
            (scope, identifier),
        )
        row = cursor.fetchone()
        if row is None:
            return None

        blocked_until = row["blocked_until"]
        if blocked_until > now:
            return blocked_until

        cursor.execute(
            "DELETE FROM auth_login_blocks WHERE scope = %s AND identifier = %s",
            (scope, identifier),
        )
        return None

    def _record_login_attempt(
        self,
        cursor: psycopg.Cursor[dict[str, Any]],
        phone: str,
        ip: str | None,
        *,
        success: bool,
        now: datetime,
    ) -> None:
        cursor.execute(
            """
            INSERT INTO auth_login_attempts (mobile, ip, success, created_at)
            VALUES (%s, %s, %s, %s)
            """,
            (phone, ip, success, now),
        )

    def _block_if_login_limits_exceeded(
        self,
        cursor: psycopg.Cursor[dict[str, Any]],
        phone: str,
        ip: str | None,
        now: datetime,
    ) -> bool:
        should_block = False
        if (
            self._count_recent_failed_logins(cursor, "mobile", phone, now)
            >= config.auth_login_attempt_limit_per_phone
        ):
            self._block_login(cursor, "mobile", phone, now)
            should_block = True
        if ip and (
            self._count_recent_failed_logins(cursor, "ip", ip, now)
            >= config.auth_login_attempt_limit_per_ip
        ):
            self._block_login(cursor, "ip", ip, now)
            should_block = True
        return should_block

    def _count_recent_failed_logins(
        self,
        cursor: psycopg.Cursor[dict[str, Any]],
        scope: str,
        identifier: str,
        now: datetime,
    ) -> int:
        window_start = now - timedelta(minutes=config.auth_login_attempt_window_minutes)
        if scope == "mobile":
            cursor.execute(
                """
                SELECT COALESCE(MAX(created_at), %s) AS since
                FROM auth_login_attempts
                WHERE mobile = %s
                  AND success = TRUE
                  AND created_at >= %s
                """,
                (window_start, identifier, window_start),
            )
        else:
            cursor.execute(
                """
                SELECT COALESCE(MAX(created_at), %s) AS since
                FROM auth_login_attempts
                WHERE ip = %s
                  AND success = TRUE
                  AND created_at >= %s
                """,
                (window_start, identifier, window_start),
            )
        since = cursor.fetchone()["since"]
        if scope == "mobile":
            cursor.execute(
                """
                SELECT COUNT(*) AS count
                FROM auth_login_attempts
                WHERE mobile = %s
                  AND success = FALSE
                  AND created_at >= %s
                """,
                (identifier, since),
            )
        else:
            cursor.execute(
                """
                SELECT COUNT(*) AS count
                FROM auth_login_attempts
                WHERE ip = %s
                  AND success = FALSE
                  AND created_at >= %s
                """,
                (identifier, since),
            )
        return int(cursor.fetchone()["count"])

    def _block_login(
        self,
        cursor: psycopg.Cursor[dict[str, Any]],
        scope: str,
        identifier: str,
        now: datetime,
    ) -> None:
        blocked_until = now + timedelta(minutes=config.auth_login_lockout_minutes)
        cursor.execute(
            """
            INSERT INTO auth_login_blocks (scope, identifier, blocked_until, updated_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (scope, identifier)
            DO UPDATE SET
                blocked_until = EXCLUDED.blocked_until,
                updated_at = EXCLUDED.updated_at
            """,
            (scope, identifier, blocked_until, now),
        )
        logger.warning(
            f"Login temporarily blocked: scope={scope}, identifier={self._mask_identifier(scope, identifier)}, "
            f"until={blocked_until.isoformat()}"
        )

    def _clear_login_blocks(
        self,
        cursor: psycopg.Cursor[dict[str, Any]],
        phone: str,
        ip: str | None,
    ) -> None:
        cursor.execute(
            "DELETE FROM auth_login_blocks WHERE scope = 'mobile' AND identifier = %s",
            (phone,),
        )
        if ip:
            cursor.execute(
                "DELETE FROM auth_login_blocks WHERE scope = 'ip' AND identifier = %s",
                (ip,),
            )

    def _deliver_sms(self, phone: str, code: str) -> None:
        provider = self._sms_provider()
        if provider == "mock":
            logger.info(f"SMS mock provider: phone={self._mask_phone(phone)}")
            return

        if provider == "console":
            logger.info(f"SMS console provider: phone={self._mask_phone(phone)}")
            return

        if provider != "aliyun":
            raise AuthError("未知短信服务商配置", status_code=500)

        if not self._has_aliyun_sms_config():
            raise AuthError("短信签名或模板未配置", status_code=503)

        try:
            from alibabacloud_dysmsapi20170525.client import Client as DysmsapiClient
            from alibabacloud_dysmsapi20170525 import models as dysmsapi_models
            from alibabacloud_tea_openapi import models as open_api_models
            from alibabacloud_tea_util import models as util_models
        except ImportError as exc:
            raise AuthError(
                "短信 SDK 未安装，请安装 alibabacloud-dysmsapi20170525",
                status_code=503,
            ) from exc

        access_key_id = (
            config.aliyun_sms_access_key_id or config.alibaba_cloud_access_key_id
        ).strip()
        access_key_secret = (
            config.aliyun_sms_access_key_secret or config.alibaba_cloud_access_key_secret
        ).strip()
        if not access_key_id or not access_key_secret:
            raise AuthError("阿里云短信 AccessKey 未配置", status_code=503)

        client_config = open_api_models.Config(
            credential=AliyunAccessKeyCredential(access_key_id, access_key_secret),
        )
        client_config.endpoint = config.aliyun_sms_endpoint

        client = DysmsapiClient(client_config)
        request = dysmsapi_models.SendSmsRequest(
            phone_numbers=phone,
            sign_name=config.aliyun_sms_sign_name,
            template_code=config.aliyun_sms_template_code,
            template_param=json.dumps({"code": code}, ensure_ascii=False),
        )
        try:
            runtime_options = util_models.RuntimeOptions(
                autoretry=config.aliyun_sms_max_attempts > 1,
                max_attempts=config.aliyun_sms_max_attempts,
                connect_timeout=config.aliyun_sms_connect_timeout_ms,
                read_timeout=config.aliyun_sms_read_timeout_ms,
            )
            response = client.send_sms_with_options(request, runtime_options)
        except Exception as exc:
            message = getattr(exc, "message", str(exc))
            data = getattr(exc, "data", None)
            recommend = data.get("Recommend") if isinstance(data, dict) else None
            logger.error(f"Aliyun SMS request failed: {message}; recommend={recommend}")
            if "NoPermission" in message or "not authorized" in message:
                raise AuthError(
                    "阿里云短信权限不足：请给当前 AccessKey 所属 RAM 用户授权短信服务 SendSms 权限",
                    status_code=403,
                ) from exc
            raise AuthError("短信发送失败，请稍后再试", status_code=502) from exc

        body = getattr(response, "body", None)
        if getattr(body, "code", None) != "OK":
            message = getattr(body, "message", "短信发送失败")
            logger.error(f"Aliyun SMS failed: {message}")
            raise AuthError("短信发送失败，请稍后再试", status_code=502)

    def _has_aliyun_sms_config(self) -> bool:
        return all(
            [
                config.aliyun_sms_sign_name,
                config.aliyun_sms_template_code,
                config.aliyun_sms_endpoint,
            ]
        )

    def _sms_provider(self) -> str:
        return config.sms_provider.strip().lower()

    def _code_length(self) -> int:
        try:
            value = int(config.sms_code_length)
        except (TypeError, ValueError):
            value = 6
        return max(4, min(value, 8))

    def _generate_code(self) -> str:
        length = self._code_length()
        return f"{secrets.randbelow(10**length):0{length}d}"

    def _serialize_user(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "phone": row["mobile"],
            "mobile": row["mobile"],
            "nickname": row["nickname"],
            "role": row["role"],
            "status": int(row["status"]),
            "points": int(row["points"]),
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "last_login_at": (
                row["last_login_at"].isoformat() if row["last_login_at"] else None
            ),
            "last_login_ip": row["last_login_ip"],
        }

    def _hash_code(self, phone: str, code: str) -> str:
        payload = f"{phone}:{code}".encode("utf-8")
        return hmac.new(
            config.auth_secret_key.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()

    def _hash_token(self, token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)


auth_service = AuthService()
