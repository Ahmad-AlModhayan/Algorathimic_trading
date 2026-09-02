"""Thin Postgres helpers. Schema lives in `sql/` and is applied in file order."""

from __future__ import annotations

from pathlib import Path

import psycopg

from core.config import get_settings

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


def connect(dsn: str | None = None) -> psycopg.Connection:
    return psycopg.connect(dsn or str(get_settings().database_url))


def apply_schema(conn: psycopg.Connection, sql_dir: Path = SQL_DIR) -> list[str]:
    """Apply every `sql/*.sql` file in name order. Files must be idempotent (IF NOT EXISTS)."""
    applied: list[str] = []
    with conn, conn.cursor() as cur:
        for path in sorted(sql_dir.glob("*.sql")):
            cur.execute(path.read_text(encoding="utf-8"))
            applied.append(path.name)
    return applied
