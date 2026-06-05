"""配置管理模块

使用 Pydantic Settings 实现类型安全的配置管理
"""

from typing import Dict, Any
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # 应用配置
    app_name: str = "SuperBizAgent"
    app_version: str = "1.0.0"
    app_env: str = "development"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 9900
    docs_enabled: bool = True
    cors_allowed_origins: str = ""

    # Auth and SMS settings
    auth_secret_key: str = "change-me-in-production"
    auth_cookie_name: str = "jucheng_session"
    auth_cookie_secure: bool = False
    auth_session_ttl_hours: int = 168
    auth_trusted_proxy_ips: str = "127.0.0.1,::1"
    auth_login_attempt_limit_per_phone: int = 5
    auth_login_attempt_limit_per_ip: int = 20
    auth_login_attempt_window_minutes: int = 10
    auth_login_lockout_minutes: int = 10
    sms_provider: str = "aliyun"
    sms_mock_code: str = "123456"
    sms_code_length: int = 6
    sms_code_ttl_minutes: int = 5
    sms_resend_interval_seconds: int = 60
    sms_daily_limit_per_phone: int = 10
    sms_hourly_limit_per_ip: int = 30
    alibaba_cloud_access_key_id: str = ""
    alibaba_cloud_access_key_secret: str = ""
    aliyun_sms_access_key_id: str = ""
    aliyun_sms_access_key_secret: str = ""
    aliyun_sms_sign_name: str = "武汉炬成科技"
    aliyun_sms_template_code: str = "SMS_333837184"
    aliyun_sms_endpoint: str = "dysmsapi.aliyuncs.com"
    aliyun_sms_connect_timeout_ms: int = 3000
    aliyun_sms_read_timeout_ms: int = 10000
    aliyun_sms_max_attempts: int = 2

    # PostgreSQL database settings
    database_host: str = "localhost"
    database_port: int = 5432
    database_name: str = "postgres"
    database_user: str = "postgres"
    database_password: str = ""
    database_application_name: str = "super_biz_agent"
    database_connect_timeout_seconds: int = 5
    database_statement_timeout_ms: int = 30000
    database_lock_timeout_ms: int = 5000
    database_idle_transaction_timeout_ms: int = 30000
    database_pool_enabled: bool = True
    database_pool_min_size: int = 1
    database_pool_max_size: int = 10
    database_pool_timeout_seconds: float = 5.0
    database_migrations_path: str = "database/migrations"
    database_validate_migrations_on_startup: bool = True
    database_auto_migrate_on_startup: bool = False
    database_allow_untracked_schema_ensure: bool = False

    # DashScope 配置
    dashscope_api_key: str = ""  # 默认空字符串，实际使用需从环境变量加载
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    dashscope_task_base_url: str = "https://dashscope.aliyuncs.com/api/v1"
    dashscope_model: str = "qwen3.7-plus"
    dashscope_vision_model: str = "qwen-vl-plus"
    dashscope_image_generation_model: str = "wanx2.1-t2i-turbo"
    dashscope_embedding_model: str = "text-embedding-v4"  # v4 支持多种维度（默认 1024）
    dashscope_request_timeout_seconds: float = 60.0
    dashscope_connect_timeout_seconds: float = 10.0
    dashscope_max_retries: int = 2
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_request_timeout_seconds: float = 60.0
    deepseek_max_retries: int = 2
    image_upload_max_size: int = 10 * 1024 * 1024
    image_upload_max_count: int = 4
    image_generation_poll_timeout_seconds: int = 120
    image_generation_poll_interval_seconds: int = 2

    # Milvus 配置
    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_timeout: int = 10000  # 毫秒
    milvus_allow_destructive_schema_reset: bool = False

    # RAG 配置
    rag_top_k: int = 3
    rag_grounding_top_k: int = 5
    rag_catalog_top_k: int = 3
    rag_model: str = "qwen3.7-plus"  # 使用快速响应模型，不带扩展思考
    rag_strict_grounding: bool = True
    rag_grounding_cache_ttl_seconds: int = 60
    rag_grounding_cache_max_entries: int = 128
    knowledge_base_path: str = "./docs/knowledge_base"
    startup_warmup_enabled: bool = True

    # 文档分块配置
    chunk_max_size: int = 800
    chunk_overlap: int = 100

    # MCP 服务配置
    mcp_cls_transport: str = "streamable-http"
    mcp_cls_url: str = "http://localhost:8003/mcp"
    mcp_monitor_transport: str = "streamable-http"
    mcp_monitor_url: str = "http://localhost:8004/mcp"

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        runtime_errors: list[str] = []
        if self.dashscope_request_timeout_seconds <= 0:
            runtime_errors.append("DASHSCOPE_REQUEST_TIMEOUT_SECONDS must be positive")
        if self.dashscope_connect_timeout_seconds <= 0:
            runtime_errors.append("DASHSCOPE_CONNECT_TIMEOUT_SECONDS must be positive")
        if self.dashscope_connect_timeout_seconds > self.dashscope_request_timeout_seconds:
            runtime_errors.append(
                "DASHSCOPE_CONNECT_TIMEOUT_SECONDS must be less than or equal to "
                "DASHSCOPE_REQUEST_TIMEOUT_SECONDS"
            )
        if self.dashscope_max_retries < 0 or self.dashscope_max_retries > 5:
            runtime_errors.append("DASHSCOPE_MAX_RETRIES must be between 0 and 5")
        if self.deepseek_request_timeout_seconds <= 0:
            runtime_errors.append("DEEPSEEK_REQUEST_TIMEOUT_SECONDS must be positive")
        if self.deepseek_max_retries < 0 or self.deepseek_max_retries > 5:
            runtime_errors.append("DEEPSEEK_MAX_RETRIES must be between 0 and 5")
        if self.aliyun_sms_connect_timeout_ms <= 0:
            runtime_errors.append("ALIYUN_SMS_CONNECT_TIMEOUT_MS must be positive")
        if self.aliyun_sms_read_timeout_ms <= 0:
            runtime_errors.append("ALIYUN_SMS_READ_TIMEOUT_MS must be positive")
        if self.aliyun_sms_max_attempts < 1 or self.aliyun_sms_max_attempts > 5:
            runtime_errors.append("ALIYUN_SMS_MAX_ATTEMPTS must be between 1 and 5")
        if self.database_connect_timeout_seconds <= 0:
            runtime_errors.append("DATABASE_CONNECT_TIMEOUT_SECONDS must be positive")
        if self.database_statement_timeout_ms <= 0:
            runtime_errors.append("DATABASE_STATEMENT_TIMEOUT_MS must be positive")
        if self.database_lock_timeout_ms <= 0:
            runtime_errors.append("DATABASE_LOCK_TIMEOUT_MS must be positive")
        if self.database_idle_transaction_timeout_ms <= 0:
            runtime_errors.append("DATABASE_IDLE_TRANSACTION_TIMEOUT_MS must be positive")
        if self.database_pool_min_size < 0:
            runtime_errors.append("DATABASE_POOL_MIN_SIZE must be greater than or equal to 0")
        if self.database_pool_max_size < 1:
            runtime_errors.append("DATABASE_POOL_MAX_SIZE must be greater than 0")
        if self.database_pool_min_size > self.database_pool_max_size:
            runtime_errors.append("DATABASE_POOL_MIN_SIZE must be <= DATABASE_POOL_MAX_SIZE")
        if self.database_pool_timeout_seconds <= 0:
            runtime_errors.append("DATABASE_POOL_TIMEOUT_SECONDS must be positive")
        if not self.database_migrations_path.strip():
            runtime_errors.append("DATABASE_MIGRATIONS_PATH must not be empty")

        if runtime_errors:
            raise ValueError("Invalid runtime configuration: " + "; ".join(runtime_errors))

        if not self.is_production:
            return self

        errors: list[str] = []
        if self.debug:
            errors.append("DEBUG must be False when APP_ENV=production")
        if self.auth_secret_key.strip() in {"", "change-me-in-production"}:
            errors.append("AUTH_SECRET_KEY must be set to a strong random value")
        elif len(self.auth_secret_key) < 32:
            errors.append("AUTH_SECRET_KEY must be at least 32 characters")
        if not self.auth_cookie_secure:
            errors.append("AUTH_COOKIE_SECURE must be True")
        if not self.cors_origins:
            errors.append("CORS_ALLOWED_ORIGINS must list the production web origin(s)")
        if "*" in self.cors_origins:
            errors.append("CORS_ALLOWED_ORIGINS must not contain '*'")
        insecure_origins = [
            origin for origin in self.cors_origins if not origin.startswith("https://")
        ]
        if insecure_origins:
            errors.append("CORS_ALLOWED_ORIGINS must use https:// in production")
        if self.sms_provider.strip().lower() in {"mock", "console"}:
            errors.append("SMS_PROVIDER must not be mock or console")
        if not self.database_validate_migrations_on_startup:
            errors.append("DATABASE_VALIDATE_MIGRATIONS_ON_STARTUP must be True in production")
        if self.database_auto_migrate_on_startup:
            errors.append("DATABASE_AUTO_MIGRATE_ON_STARTUP must be False in production")
        if self.database_allow_untracked_schema_ensure:
            errors.append("DATABASE_ALLOW_UNTRACKED_SCHEMA_ENSURE must be False in production")
        if self.milvus_allow_destructive_schema_reset:
            errors.append("MILVUS_ALLOW_DESTRUCTIVE_SCHEMA_RESET must be False in production")

        if errors:
            raise ValueError("Unsafe production configuration: " + "; ".join(errors))
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() in {"production", "prod"} or not self.debug

    @property
    def cors_origins(self) -> list[str]:
        return [
            origin.strip().rstrip("/")
            for origin in self.cors_allowed_origins.split(",")
            if origin.strip()
        ]

    @property
    def mcp_servers(self) -> Dict[str, Dict[str, Any]]:
        """获取完整的 MCP 服务器配置"""
        return {
            "cls": {
                "transport": self.mcp_cls_transport,
                "url": self.mcp_cls_url,
            },
            "monitor": {
                "transport": self.mcp_monitor_transport,
                "url": self.mcp_monitor_url,
            }
        }


# 全局配置实例
config = Settings()
