from __future__ import annotations

import sqlite3
from pathlib import Path


EMPTY_DASHBOARD = {
    "captures": 0,
    "documents": 0,
    "matches": 0,
    "errors": 0,
}


def read_dashboard_counts(database_path: Path) -> dict[str, int]:
    """Read dashboard totals without migrating or mutating the project database."""
    if not database_path.exists():
        return dict(EMPTY_DASHBOARD)
    database = sqlite3.connect(database_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.25)
    try:
        database.execute("PRAGMA query_only=ON")
        database.execute("PRAGMA busy_timeout=250")
        row = database.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM captures),
                (SELECT COUNT(*) FROM documents),
                (SELECT COUNT(*) FROM document_matches),
                (SELECT COUNT(*) FROM errors WHERE resolved=0 AND ignored=0)
            """
        ).fetchone()
        if row is None:
            return dict(EMPTY_DASHBOARD)
        return {
            "captures": int(row[0] or 0),
            "documents": int(row[1] or 0),
            "matches": int(row[2] or 0),
            "errors": int(row[3] or 0),
        }
    finally:
        database.close()
