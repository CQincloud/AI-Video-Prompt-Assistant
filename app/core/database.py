"""Shared PostgreSQL connection helpers."""

from __future__ import annotations

import threading
from typing import Any

import psycopg
from loguru import logger
from psycopg.rows import dict_row

from app.config import config

try:
    from psycopg_pool import ConnectionPool
except ImportError:  # pragma: no cover - dependency is declared for production installs
    ConnectionPool = None  # type: ignore[assignment]


_pool: Any | None = None
_pool_lock = threading.Lock()


class ManagedConnection:
    """Connection wrapper that keeps current call sites compatible with pooling."""

    def __init__(self, conn: psycopg.Connection[dict[str, Any]], pool: Any | None = None):
        self._conn = conn
        self._pool = pool
        self._closed = False

    def __enter__(self) -> psycopg.Connection[dict[str, Any]]:
        return self._conn

    def __exit__(self, exc_type, exc, tb) -> bool:
        try:
            if exc_type is None:
                self._conn.commit()
            else:
                self._conn.rollback()
        finally:
            self.close()
        return False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)

    def cursor(self, *args, **kwargs):
        return self._conn.cursor(*args, **kwargs)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._pool is not None:
            self._pool.putconn(self._conn)
            return
        self._conn.close()


def _connection_options() -> str:
    options = {
        "statement_timeout": config.database_statement_timeout_ms,
        "lock_timeout": config.database_lock_timeout_ms,
        "idle_in_transaction_session_timeout": config.database_idle_transaction_timeout_ms,
    }
    return " ".join(f"-c {name}={int(value)}" for name, value in options.items())


def _connection_kwargs() -> dict[str, Any]:
    return {
        "host": config.database_host,
        "port": config.database_port,
        "dbname": config.database_name,
        "user": config.database_user,
        "password": config.database_password,
        "connect_timeout": config.database_connect_timeout_seconds,
        "application_name": config.database_application_name,
        "options": _connection_options(),
        "row_factory": dict_row,
    }


def _should_use_pool() -> bool:
    return config.database_pool_enabled and ConnectionPool is not None


def init_connection_pool() -> None:
    """Initialize the PostgreSQL connection pool when available."""
    global _pool

    if not config.database_pool_enabled:
        logger.info("Database connection pool is disabled")
        return

    if ConnectionPool is None:
        message = "psycopg-pool is not installed; database pooling is unavailable"
        if config.is_production:
            raise RuntimeError(message)
        logger.warning(message)
        return

    with _pool_lock:
        if _pool is not None:
            return

        pool = ConnectionPool(
            kwargs=_connection_kwargs(),
            min_size=config.database_pool_min_size,
            max_size=config.database_pool_max_size,
            timeout=config.database_pool_timeout_seconds,
            open=False,
        )
        pool.open()
        pool.wait(timeout=config.database_pool_timeout_seconds)
        _pool = pool
        logger.info(
            "Database connection pool initialized: "
            f"min={config.database_pool_min_size}, max={config.database_pool_max_size}"
        )


def close_connection_pool() -> None:
    """Close the PostgreSQL connection pool if it was initialized."""
    global _pool

    with _pool_lock:
        if _pool is None:
            return
        _pool.close()
        _pool = None
        logger.info("Database connection pool closed")


def get_connection() -> ManagedConnection:
    """Return a managed PostgreSQL connection using the configured settings."""
    if config.database_pool_enabled and ConnectionPool is None and config.is_production:
        raise RuntimeError("psycopg-pool is required when database pooling is enabled")

    if _should_use_pool():
        if _pool is None:
            init_connection_pool()
        if _pool is not None:
            return ManagedConnection(_pool.getconn(), _pool)

    return ManagedConnection(psycopg.connect(**_connection_kwargs()))
