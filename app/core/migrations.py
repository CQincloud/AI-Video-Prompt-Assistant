"""Controlled PostgreSQL migration runner."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from app.config import config
from app.core.database import get_connection


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_FILE_RE = re.compile(r"^(?P<version>\d{3,})_(?P<name>[a-z0-9_]+)\.sql$")
MIGRATION_LOCK_ID = 7320528


class MigrationError(RuntimeError):
    """Raised when database migrations cannot be applied or verified."""


@dataclass(frozen=True)
class Migration:
    version: str
    name: str
    path: Path
    checksum_sha256: str
    sql: str


def load_migrations() -> list[Migration]:
    migrations_dir = _migrations_dir()
    if not migrations_dir.exists():
        raise MigrationError(f"Migration directory does not exist: {migrations_dir}")

    migrations: list[Migration] = []
    seen_versions: set[str] = set()
    for path in sorted(migrations_dir.glob("*.sql")):
        match = MIGRATION_FILE_RE.fullmatch(path.name)
        if not match:
            raise MigrationError(
                f"Invalid migration filename '{path.name}'. Expected '<version>_<name>.sql'."
            )

        version = match.group("version")
        if version in seen_versions:
            raise MigrationError(f"Duplicate migration version: {version}")
        seen_versions.add(version)

        sql_text = path.read_text(encoding="utf-8")
        migrations.append(
            Migration(
                version=version,
                name=match.group("name"),
                path=path,
                checksum_sha256=hashlib.sha256(sql_text.encode("utf-8")).hexdigest(),
                sql=sql_text,
            )
        )

    if not migrations:
        raise MigrationError(f"No migration files found in {migrations_dir}")
    return migrations


def apply_pending_migrations() -> list[Migration]:
    migrations = load_migrations()
    applied_now: list[Migration] = []

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", (MIGRATION_LOCK_ID,))
            _ensure_schema_migrations_table(cursor)
            applied = _load_applied_migrations(cursor)
            _assert_known_migrations_only(applied, migrations)

            for migration in migrations:
                applied_row = applied.get(migration.version)
                if applied_row:
                    _assert_checksum_matches(migration, applied_row)
                    continue

                logger.info(f"Applying database migration {migration.version}_{migration.name}")
                cursor.execute(_strip_transaction_wrapper(migration.sql))
                cursor.execute(
                    """
                    INSERT INTO schema_migrations (version, name, checksum_sha256)
                    VALUES (%s, %s, %s)
                    """,
                    (migration.version, migration.name, migration.checksum_sha256),
                )
                applied_now.append(migration)

    return applied_now


def assert_database_migrations_current() -> None:
    migrations = load_migrations()

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", (MIGRATION_LOCK_ID,))
            if not _schema_migrations_table_exists(cursor):
                raise MigrationError(
                    "schema_migrations table is missing. Run the migration command before "
                    "starting the application."
                )

            applied = _load_applied_migrations(cursor)
            _assert_known_migrations_only(applied, migrations)

            pending: list[str] = []
            for migration in migrations:
                applied_row = applied.get(migration.version)
                if not applied_row:
                    pending.append(f"{migration.version}_{migration.name}")
                    continue
                _assert_checksum_matches(migration, applied_row)

            if pending:
                raise MigrationError(
                    "Pending database migrations: "
                    + ", ".join(pending)
                    + ". Run the migration command before starting the application."
                )


def collect_migration_status() -> list[dict[str, Any]]:
    migrations = load_migrations()
    applied: dict[str, dict[str, Any]] = {}

    with get_connection() as conn:
        with conn.cursor() as cursor:
            if _schema_migrations_table_exists(cursor):
                applied = _load_applied_migrations(cursor)

    return [
        {
            "version": migration.version,
            "name": migration.name,
            "path": str(migration.path),
            "checksum_sha256": migration.checksum_sha256,
            "applied": migration.version in applied,
            "checksum_matches": (
                migration.version not in applied
                or applied[migration.version]["checksum_sha256"] == migration.checksum_sha256
            ),
            "applied_at": applied.get(migration.version, {}).get("applied_at"),
        }
        for migration in migrations
    ]


def _migrations_dir() -> Path:
    path = Path(config.database_migrations_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def _ensure_schema_migrations_table(cursor: Any) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            checksum_sha256 TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def _schema_migrations_table_exists(cursor: Any) -> bool:
    cursor.execute("SELECT to_regclass('schema_migrations') IS NOT NULL AS exists")
    row = cursor.fetchone()
    return bool(row and row["exists"])


def _load_applied_migrations(cursor: Any) -> dict[str, dict[str, Any]]:
    cursor.execute(
        """
        SELECT version, name, checksum_sha256, applied_at
        FROM schema_migrations
        ORDER BY version
        """
    )
    return {row["version"]: row for row in cursor.fetchall()}


def _assert_known_migrations_only(
    applied: dict[str, dict[str, Any]],
    migrations: list[Migration],
) -> None:
    known_versions = {migration.version for migration in migrations}
    unknown_versions = sorted(set(applied) - known_versions)
    if unknown_versions:
        raise MigrationError(
            "Database contains applied migrations that are not present in this deploy: "
            + ", ".join(unknown_versions)
        )


def _assert_checksum_matches(migration: Migration, applied_row: dict[str, Any]) -> None:
    if applied_row["checksum_sha256"] != migration.checksum_sha256:
        raise MigrationError(
            f"Migration {migration.version}_{migration.name} was modified after it was applied. "
            "Create a new migration instead of editing applied migration files."
        )


def _strip_transaction_wrapper(sql_text: str) -> str:
    sql_text = sql_text.strip()
    sql_text = re.sub(r"^\ufeff?\s*BEGIN\s*;\s*", "", sql_text, flags=re.IGNORECASE)
    sql_text = re.sub(r"\s*COMMIT\s*;\s*$", "", sql_text, flags=re.IGNORECASE)
    if not sql_text.strip():
        raise MigrationError("Migration file is empty after removing transaction wrapper")
    return sql_text
