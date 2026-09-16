from __future__ import annotations

import sqlite3
from pathlib import Path


EMPTY_DASHBOARD = {
    "captures": 0,
    "documents": 0,
    "matches": 0,
    "errors": 0,
    "recovery_events": 0,
    "skipped_non_text": 0,
    "skipped_url_filter": 0,
    "skipped_other": 0,
    "pending": 0,
    "downloaded_unscanned": 0,
    "downloaded": 0,
}


def _count(database: sqlite3.Connection, sql: str, params: tuple = ()) -> int:
    try:
        row = database.execute(sql, params).fetchone()
        return int(row[0] or 0) if row else 0
    except sqlite3.DatabaseError:
        return 0


def _has_column(database: sqlite3.Connection, table: str, column: str) -> bool:
    try:
        return any(str(row[1]) == column for row in database.execute(f"PRAGMA table_info({table})"))
    except sqlite3.DatabaseError:
        return False


def read_dashboard_counts(database_path: Path) -> dict[str, int]:
    """Read dashboard totals without migrating or mutating the project database."""
    if not database_path.exists():
        return dict(EMPTY_DASHBOARD)
    database = sqlite3.connect(database_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.25)
    try:
        database.execute("PRAGMA query_only=ON")
        database.execute("PRAGMA busy_timeout=250")
        result = dict(EMPTY_DASHBOARD)
        result["captures"] = _count(database, "SELECT COUNT(*) FROM captures")
        result["documents"] = _count(database, "SELECT COUNT(*) FROM documents")
        result["matches"] = _count(database, "SELECT COUNT(*) FROM document_matches")
        result["errors"] = _count(database, "SELECT COUNT(*) FROM errors WHERE resolved=0 AND ignored=0")
        result["pending"] = _count(database, "SELECT COUNT(*) FROM captures WHERE state='pending'")
        result["downloaded_unscanned"] = _count(database, "SELECT COUNT(*) FROM captures WHERE state IN ('downloaded_unscanned','scanning')")
        result["downloaded"] = _count(database, "SELECT COUNT(*) FROM captures WHERE state='downloaded'")
        if _has_column(database, "captures", "skip_reason"):
            result["skipped_non_text"] = _count(
                database,
                "SELECT COUNT(*) FROM captures WHERE state='skipped' AND skip_reason IN ('known_non_text','sniffed_non_text','unsupported_binary')",
            )
            result["skipped_url_filter"] = _count(
                database,
                "SELECT COUNT(*) FROM captures WHERE state='skipped' AND skip_reason='url_keyword_filter'",
            )
            result["skipped_other"] = _count(
                database,
                """SELECT COUNT(*) FROM captures WHERE state='skipped' AND COALESCE(skip_reason,'') NOT IN
                   ('known_non_text','sniffed_non_text','unsupported_binary','url_keyword_filter')""",
            )
        else:
            result["skipped_other"] = _count(database, "SELECT COUNT(*) FROM captures WHERE state='skipped'")
        result["recovery_events"] = _count(database, "SELECT COUNT(*) FROM recovery_events")
        return result
    finally:
        database.close()
