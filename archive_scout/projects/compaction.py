from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Callable

from ..document_store import compress_text, document_body
from ..events import ProgressEvent, Stopped
from ..storage import deduplicate_exact_file
from ..utils import utc_now


def _directory_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for item in path.rglob('*'):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            pass
    return total


def _dedupe_group(paths: list[Path]) -> int:
    existing = [path for path in paths if path.is_file()]
    if len(existing) < 2:
        return 0
    canonical = existing[0]
    saved = 0
    size = canonical.stat().st_size
    for path in existing[1:]:
        method = deduplicate_exact_file(path, canonical)
        if method == 'clone':
            saved += size
    return saved


def compact_project_storage(
    root: Path,
    database: sqlite3.Connection,
    stop_event: threading.Event,
    callback: Callable[[ProgressEvent], None] | None = None,
) -> dict[str, int]:
    """Safely compact regenerable/duplicate project storage.

    No unique capture payload is deleted. Visible-body database copies are
    compressed only when the canonical local capture is present, and exact-file
    dedupe uses copy-on-write clones where the filesystem supports them.
    """
    root = Path(root)
    before_db = (root / 'archive_scout.sqlite3').stat().st_size if (root / 'archive_scout.sqlite3').exists() else 0
    compacted_docs = 0
    dedupe_saved = 0

    rows = database.execute(
        """SELECT d.*,c.original_url FROM documents d JOIN captures c ON c.id=d.capture_id
           WHERE COALESCE(d.body_text,'')<>'' ORDER BY d.id"""
    ).fetchall()
    for index, row in enumerate(rows, 1):
        if stop_event.is_set():
            raise Stopped
        path = Path(str(row['path'] or ''))
        if not path.is_file():
            continue
        body = str(row['body_text'] or '')
        with database:
            database.execute(
                """UPDATE documents SET body_zlib=NULL,body_chars=?,body_text='',original_url=COALESCE(NULLIF(original_url,''),?),updated_at=? WHERE id=?""",
                (len(body), str(row['original_url'] or ''), utc_now(), int(row['id'])),
            )
        compacted_docs += 1
        if callback and index % 250 == 0:
            callback(ProgressEvent('compact', f'Compressed database text {index:,}/{len(rows):,}', index, len(rows)))

    # v1.0.5 and earlier duplicated every match's hit counts/fields in both
    # document_matches JSON and keyword_hits. v1.0.6 reads the canonical JSON
    # only, so the legacy rows are fully regenerable and safe to reclaim.
    legacy_keyword_hit_rows = int(database.execute("SELECT COUNT(*) FROM keyword_hits").fetchone()[0])
    if legacy_keyword_hit_rows:
        with database:
            database.execute("DELETE FROM keyword_hits")

    # Exact-byte duplicates: capture text and media are safe to CoW-clone.
    for table, hash_col, path_col in (
        ('documents', 'content_hash', 'path'),
        ('media_captures', 'content_hash', 'path'),
    ):
        groups = database.execute(
            f"SELECT {hash_col},COUNT(*) FROM {table} WHERE COALESCE({hash_col},'')<>'' AND COALESCE({path_col},'')<>'' GROUP BY {hash_col} HAVING COUNT(*)>1"
        ).fetchall()
        for group in groups:
            if stop_event.is_set():
                raise Stopped
            paths = [Path(str(row[0])) for row in database.execute(
                f"SELECT {path_col} FROM {table} WHERE {hash_col}=? ORDER BY id", (group[0],)
            )]
            dedupe_saved += _dedupe_group(paths)

    # Rebuild the lean external-content FTS index from canonical compressed text.
    fts = database.execute("SELECT value FROM project_meta WHERE key='fts5'").fetchone()
    if fts and fts['value'] == '1':
        database.execute("DROP TABLE IF EXISTS documents_fts")
        database.execute(
            "CREATE VIRTUAL TABLE documents_fts USING fts5(title,body_text,original_url,content='documents',content_rowid='id')"
        )
        for row in database.execute(
            """SELECT d.*,c.original_url AS capture_original_url FROM documents d JOIN captures c ON c.id=d.capture_id ORDER BY d.id"""
        ):
            body = document_body(row)
            database.execute(
                "INSERT INTO documents_fts(rowid,title,body_text,original_url) VALUES(?,?,?,?)",
                (int(row['id']), str(row['title'] or ''), body, str(row['capture_original_url'] or '')),
            )
        database.commit()

    database.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    database.commit()
    # VACUUM is intentionally outside a transaction and only in the explicit
    # Compact operation, never the normal hot path.
    database.execute("VACUUM")
    database.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    after_db = (root / 'archive_scout.sqlite3').stat().st_size if (root / 'archive_scout.sqlite3').exists() else 0
    result = {
        'documents_compacted': compacted_docs,
        'redundant_keyword_hit_rows_removed': legacy_keyword_hit_rows,
        'database_bytes_before': before_db,
        'database_bytes_after': after_db,
        'database_bytes_saved': max(0, before_db - after_db),
        'cow_bytes_saved_estimate': dedupe_saved,
        'captures_bytes': _directory_size(root / 'captures'),
        'media_bytes': _directory_size(root / 'media'),
        'backups_bytes': _directory_size(root / 'backups'),
        'reports_bytes': _directory_size(root / 'reports'),
    }
    if callback:
        callback(ProgressEvent('compact', f"Storage compaction complete; database saved {result['database_bytes_saved']:,} bytes; CoW dedupe estimate {dedupe_saved:,} bytes"))
    return result
