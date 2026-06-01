"""Database migration CLI.

Usage:
    python scripts/manage_migrations.py status
    python scripts/manage_migrations.py check
    python scripts/manage_migrations.py apply
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage PostgreSQL schema migrations.")
    parser.add_argument("command", choices=["status", "check", "apply"])
    args = parser.parse_args(argv)

    from app.core.migrations import (
        MigrationError,
        apply_pending_migrations,
        assert_database_migrations_current,
    )

    try:
        if args.command == "status":
            return _print_status()
        if args.command == "check":
            assert_database_migrations_current()
            print("Database migrations are current.")
            return 0
        if args.command == "apply":
            applied = apply_pending_migrations()
            if not applied:
                print("Database migrations are already current.")
                return 0
            print("Applied migrations:")
            for migration in applied:
                print(f"  - {migration.version}_{migration.name}")
            return 0
    except MigrationError as exc:
        print(f"Migration error: {exc}", file=sys.stderr)
        return 1

    return 2


def _print_status() -> int:
    from app.core.migrations import collect_migration_status

    rows = collect_migration_status()
    for row in rows:
        marker = "applied" if row["applied"] else "pending"
        checksum = "ok" if row["checksum_matches"] else "changed"
        applied_at = _format_applied_at(row["applied_at"])
        print(f"{row['version']}_{row['name']}: {marker}, checksum={checksum}, applied_at={applied_at}")
    return 0 if all(row["applied"] and row["checksum_matches"] for row in rows) else 1


def _format_applied_at(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if value:
        return str(value)
    return "-"


if __name__ == "__main__":
    raise SystemExit(main())
