from __future__ import annotations

import concurrent.futures
import os
import sqlite3
import threading
import time
import urllib.parse
from collections import deque
from pathlib import Path
from typing import Callable, Iterator

from ..cdx.client import HttpClient, RateLimitDeferred
from ..cdx.parameters import cdx_query_signature
from ..config import ProjectConfig
from ..constants import REPLAY_URL
from ..content import (
    classify_replay_content,
    classify_text_candidate,
    decode_bytes,
    detect_encoding,
    looks_textual_bytes,
    parse_page,
)
from ..database.repositories import (
    mark_capture_skipped,
    record_error,
    record_site_issue,
    requeue_reclassifiable_skips,
    resolve_errors,
    save_match,
    upsert_document,
)
from ..events import ProgressEvent, Stopped
from ..parsing.embeds import extract_embed_candidates_fast
from ..site_status import host_from_url, should_surface_site_issue, site_issue_message
from ..scanning.jobs import ScanJob
from ..scanning.keywords import compile_prefilter
from ..scanning.scoring import analyze_content, prepare_analysis_fields
from ..storage import capture_path as url_capture_path, deduplicate_exact_file, sha256_file
from ..utils import hash_text, normalize_search, utc_now
from .rate_limit import SharedFixedRateLimiter, shared_host_gate
from .validation import classify_exception

CLASSIFIER_REVISION = 1


def replay_url(timestamp: str, original: str, modifier: str = "id_") -> str:
    encoded = urllib.parse.quote(original, safe=":/?&=#%+;,[]@!$'()*")
    clean_modifier = modifier if modifier in {"id_", "if_", "oe_"} else "id_"
    return f"{REPLAY_URL}/{timestamp}{clean_modifier}/{encoded}"


def capture_path(root: Path, capture_id: int, timestamp: str, original: str) -> Path:
    """Compatibility wrapper using the v1.0.6 URL-derived filename policy."""
    del capture_id
    return url_capture_path(root, timestamp, original)


def _allocate_capture_path(database: sqlite3.Connection, root: Path, row: sqlite3.Row) -> Path:
    existing = str(row["local_path"] or "") if "local_path" in row.keys() else ""
    if existing:
        return Path(existing)
    candidate = url_capture_path(root, str(row["timestamp"]), str(row["original_url"]))
    conflict = database.execute(
        "SELECT id FROM captures WHERE id<>? AND local_path=? LIMIT 1",
        (int(row["id"]), str(candidate)),
    ).fetchone()
    if conflict or candidate.exists():
        # Existing v1.0.x archives can contain a path not yet backfilled into
        # captures.local_path. Preserve it and minimally disambiguate this capture.
        return url_capture_path(
            root, str(row["timestamp"]), str(row["original_url"]), disambiguate=True
        )
    return candidate


def cumulative_download_progress(
    database: sqlite3.Connection,
    config: ProjectConfig,
    queued_total: int,
    capture_ids: list[int] | None = None,
) -> tuple[int, int]:
    if capture_ids:
        return 0, max(0, int(queued_total))
    signature = cdx_query_signature(config)
    total = int(database.execute(
        "SELECT COUNT(*) FROM captures WHERE query_signature=?", (signature,)
    ).fetchone()[0])
    unfinished = int(database.execute(
        """SELECT COUNT(*) FROM captures
           WHERE query_signature=? AND state IN ('pending','downloading','downloaded_unscanned','scanning')""",
        (signature,),
    ).fetchone()[0])
    return max(0, total - unfinished), total


def prepare_download_rows(
    database: sqlite3.Connection,
    config: ProjectConfig,
    patterns,
    states: tuple[str, ...] = ("pending",),
    capture_ids: list[int] | None = None,
) -> tuple[int, Iterator[sqlite3.Row]]:
    """Classify indexed captures and create a bounded SQLite-backed replay queue.

    Intentional non-text/URL-filter decisions are auditable skip reasons, never
    Open Errors. Ambiguous metadata is downloaded and sniffed rather than lost.
    """
    requeue_reclassifiable_skips(database, config.download_scope, CLASSIFIER_REVISION)
    database.execute("DROP TABLE IF EXISTS temp.archive_scout_download_queue")
    database.execute(
        """CREATE TEMP TABLE archive_scout_download_queue(
               id INTEGER PRIMARY KEY,
               priority INTEGER NOT NULL,
               length INTEGER NOT NULL
           ) WITHOUT ROWID"""
    )
    database.execute(
        "CREATE INDEX archive_scout_download_queue_order ON archive_scout_download_queue(priority,length,id)"
    )
    database.execute("DROP TABLE IF EXISTS temp.archive_scout_capture_selection")

    source = "captures c"
    clauses: list[str] = []
    params: list[object] = []
    if capture_ids:
        database.execute(
            "CREATE TEMP TABLE archive_scout_capture_selection(id INTEGER PRIMARY KEY) WITHOUT ROWID"
        )
        database.executemany(
            "INSERT OR IGNORE INTO archive_scout_capture_selection(id) VALUES(?)",
            ((int(value),) for value in capture_ids),
        )
        source += " JOIN archive_scout_capture_selection s ON s.id=c.id"
    else:
        clauses.extend(["c.query_signature=?", "c.download_attempts<?"])
        params.extend([cdx_query_signature(config), config.max_attempts])
    if states:
        clauses.append("c.state IN (" + ",".join("?" for _ in states) + ")")
        params.extend(states)

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    cursor = database.execute(
        "SELECT c.id,c.original_url,c.mimetype,c.length FROM " + source + where + " ORDER BY c.id",
        params,
    )
    url_prefilter = compile_prefilter(patterns) if patterns else None
    while True:
        chunk = cursor.fetchmany(2000)
        if not chunk:
            break
        selected_ids: list[tuple[int, int, int]] = []
        with database:
            for row in chunk:
                capture_id = int(row["id"])
                classification = classify_text_candidate(
                    str(row["original_url"]), str(row["mimetype"] or "")
                )
                if classification == "binary":
                    mark_capture_skipped(database, capture_id, "known_non_text", CLASSIFIER_REVISION)
                    continue
                if config.download_scope == "keyword_urls" and url_prefilter is not None:
                    original_url = str(row["original_url"])
                    normalized_url = normalize_search(original_url)
                    if (
                        not url_prefilter.has_positive_rules
                        or not url_prefilter.matches(
                            {"url": original_url}, {"url": normalized_url}
                        )
                    ):
                        mark_capture_skipped(
                            database, capture_id, "url_keyword_filter", CLASSIFIER_REVISION
                        )
                        continue
                length = max(0, int(row["length"] or 0))
                selected_ids.append((capture_id, 1 if length <= 0 else 0, length))
            if selected_ids:
                database.executemany(
                    "INSERT OR IGNORE INTO archive_scout_download_queue(id,priority,length) VALUES(?,?,?)",
                    selected_ids,
                )
    total = int(database.execute(
        "SELECT COUNT(*) FROM archive_scout_download_queue"
    ).fetchone()[0])

    def iter_rows() -> Iterator[sqlite3.Row]:
        last_priority = -1
        last_length = -1
        last_id = 0
        while True:
            batch = database.execute(
                """
                SELECT c.* FROM captures c
                JOIN archive_scout_download_queue q ON q.id=c.id
                WHERE (q.priority,q.length,q.id)>(?,?,?)
                ORDER BY q.priority,q.length,q.id LIMIT 1000
                """,
                (last_priority, last_length, last_id),
            ).fetchall()
            if not batch:
                return
            for row in batch:
                length = max(0, int(row["length"] or 0))
                last_priority = 1 if length <= 0 else 0
                last_length = length
                last_id = int(row["id"])
                yield row

    return total, iter_rows()


def select_download_rows(
    database: sqlite3.Connection,
    config: ProjectConfig,
    patterns,
    states: tuple[str, ...] = ("pending",),
    capture_ids: list[int] | None = None,
) -> list[sqlite3.Row]:
    _total, rows = prepare_download_rows(
        database, config, patterns, states=states, capture_ids=capture_ids
    )
    return list(rows)


def _download_capture(
    row: dict[str, object],
    path: Path,
    config: ProjectConfig,
    client: HttpClient,
) -> dict:
    original = str(row["original_url"])
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        size, digest = sha256_file(path)
        preview = path.read_bytes()[:16384]
        return {
            "kind": "downloaded",
            "capture_id": int(row["id"]), "path": path, "bytes_saved": size,
            "content_hash": digest, "http_status": 200,
            "final_url": replay_url(str(row["timestamp"]), original),
            "content_type": str(row.get("mimetype") or ""), "preview": preview,
        }
    temp = path.with_name(path.name + ".part")
    # The old 25 MB setting must not silently discard a known larger text page.
    # For known CDX lengths, allow the advertised payload plus headroom while
    # retaining the configured budget for unknown-length responses.
    known_length = max(0, int(row.get("length") or 0))
    stream_limit = max(config.max_file_bytes, known_length + 1024 * 1024)
    response = client.download_to_path(
        replay_url(str(row["timestamp"]), original), temp, stream_limit
    )
    content_type = (
        response["headers"].get("content-type")
        or response["headers"].get("Content-Type")
        or row.get("mimetype")
        or ""
    )
    preview = bytes(response.get("preview") or b"")
    if not looks_textual_bytes(preview, str(content_type)):
        temp.unlink(missing_ok=True)
        return {
            "kind": "non_text", "capture_id": int(row["id"]),
            "content_type": str(content_type), "http_status": response["status"],
            "final_url": response["final_url"],
        }
    preview_text = decode_bytes(preview, str(content_type))
    replay_problem = classify_replay_content(preview_text, str(response["final_url"]))
    if replay_problem:
        temp.unlink(missing_ok=True)
        raise RuntimeError(replay_problem)
    os.replace(temp, path)
    return {
        "kind": "downloaded",
        "capture_id": int(row["id"]), "path": path,
        "bytes_saved": int(response["bytes"]),
        "content_hash": str(response["content_hash"]),
        "http_status": response["status"], "final_url": response["final_url"],
        "content_type": str(content_type), "preview": preview,
    }


def _scan_saved_capture(
    row: dict[str, object], path: Path, config: ProjectConfig, jobs: list[ScanJob]
) -> dict:
    data = path.read_bytes()
    content_type = str(row.get("mimetype") or "")
    if not looks_textual_bytes(data[:16384], content_type):
        return {"kind": "non_text", "capture_id": int(row["id"]), "path": path}
    encoding = detect_encoding(data[:65536], content_type)
    raw = decode_bytes(data, content_type)
    replay_problem = classify_replay_content(raw, str(row.get("final_url") or replay_url(str(row["timestamp"]), str(row["original_url"]))))
    if replay_problem:
        raise RuntimeError(replay_problem)
    original = str(row["original_url"])
    title, visible, links = parse_page(raw, original)
    if config.media.enabled and config.media.discover_embedded:
        embed_urls = {candidate.url for candidate in extract_embed_candidates_fast(raw, original)}
        if embed_urls:
            links = sorted(set(links).union(embed_urls))
    prepared_fields, prepared_normalized_fields = prepare_analysis_fields(
        original, title, visible, raw, links
    )
    analyses = {
        job.scan_run_id: analyze_content(
            original, title, visible, raw, links, job.patterns, job.prefilter,
            prepared_fields, prepared_normalized_fields,
        )
        for job in jobs
    }
    return {
        "kind": "scanned", "capture_id": int(row["id"]), "path": path,
        "title": title, "visible": visible, "links": links,
        "analyses": analyses, "content_hash": str(row.get("content_hash") or sha256_file(path)[1]),
        "normalized_hash": hash_text(prepared_normalized_fields["body"]),
        "bytes_saved": path.stat().st_size, "encoding": encoding,
    }


def fetch_parse_scan(row: sqlite3.Row, config: ProjectConfig, jobs: list[ScanJob], client: HttpClient) -> dict:
    """Legacy extension API; v1.0.6's main pipeline calls download and scan separately."""
    row_dict = dict(row)
    path = url_capture_path(config.output_dir, str(row["timestamp"]), str(row["original_url"]))
    downloaded = _download_capture(row_dict, path, config, client)
    if downloaded["kind"] != "downloaded":
        raise RuntimeError("downloaded response was not textual")
    row_dict.update(downloaded)
    return _scan_saved_capture(row_dict, path, config, jobs)


def save_success(database: sqlite3.Connection, result: dict) -> None:
    document_id = upsert_document(
        database, result["capture_id"], result["path"], result["title"],
        result["visible"], result["links"], result["content_hash"],
        result["normalized_hash"], result["bytes_saved"],
    )
    database.execute(
        "UPDATE captures SET state='downloaded',detected_encoding=?,updated_at=? WHERE id=?",
        (result.get("encoding") or "", utc_now(), result["capture_id"]),
    )
    for scan_run_id, analysis in result["analyses"].items():
        save_match(database, int(scan_run_id), document_id, analysis)
    resolve_errors(database, capture_id=result["capture_id"], document_id=document_id)


def _pending_scan_rows(
    database: sqlite3.Connection, config: ProjectConfig, capture_ids: list[int] | None = None
) -> Iterator[sqlite3.Row]:
    clauses = ["state='downloaded_unscanned'", "local_path IS NOT NULL"]
    params: list[object] = []
    if capture_ids:
        placeholders = ",".join("?" for _ in capture_ids)
        clauses.append(f"id IN ({placeholders})")
        params.extend(int(value) for value in capture_ids)
    else:
        clauses.append("query_signature=?")
        params.append(cdx_query_signature(config))
    last = 0
    while True:
        rows = database.execute(
            "SELECT * FROM captures WHERE " + " AND ".join(clauses) + " AND id>? ORDER BY id LIMIT 1000",
            [*params, last],
        ).fetchall()
        if not rows:
            return
        for row in rows:
            last = int(row["id"])
            yield row


def download_archive(
    config: ProjectConfig,
    database: sqlite3.Connection,
    scan_run_id: int,
    stop_event: threading.Event,
    callback: Callable[[ProgressEvent], None] | None,
    states: tuple[str, ...] = ("pending",),
    capture_ids: list[int] | None = None,
    scan_jobs: list[ScanJob] | None = None,
) -> None:
    if config.download_scope == "index_only":
        if callback:
            callback(ProgressEvent("download", "Index-only mode selected; downloads skipped."))
        return
    jobs = scan_jobs or [ScanJob.create(scan_run_id, config.keyword_set_name, config.keywords)]
    if not jobs or any(not job.patterns for job in jobs):
        raise ValueError("at least one keyword rule is required")
    combined_patterns = [item for job in jobs for item in job.patterns]
    with database:
        database.execute("UPDATE captures SET state='pending' WHERE state='downloading'")
        database.execute("UPDATE captures SET state='downloaded_unscanned' WHERE state='scanning'")
    total, row_iter = prepare_download_rows(
        database, config, combined_patterns, states=states, capture_ids=capture_ids
    )
    completed_before, cumulative_total = cumulative_download_progress(database, config, total, capture_ids)

    limiter = SharedFixedRateLimiter(config.download_delay)
    host_gate = shared_host_gate(config.rate_limit_base_pause, config.rate_limit_max_pause)

    def on_retry(attempt: int, total_attempts: int, reason: str, wait_seconds: float) -> None:
        if callback:
            stage = "rate_limit" if "all Wayback requests paused" in reason else "download_retry"
            callback(ProgressEvent(stage, f"{reason}. Retry {attempt}/{total_attempts} in {wait_seconds:.1f}s…"))

    client = HttpClient(
        limiter, config.retries, max(config.connect_timeout, config.read_timeout),
        config.user_agent, stop_event, retry_callback=on_retry,
        connect_timeout=config.connect_timeout, read_timeout=config.read_timeout,
        pool_size=config.workers, host_gate=host_gate,
        rate_limit_attempts=config.rate_limit_attempts,
        rate_limit_max_wait=config.rate_limit_max_wait,
        network_backend=config.network.normalized().backend,
        trust_environment=config.network.normalized().trust_environment,
        network_callback=(lambda message: callback(ProgressEvent("network", message)) if callback else None),
    )

    scan_workers = config.scan_workers or min(8, max(1, (os.cpu_count() or 4) - 1))
    scan_workers = max(1, min(32, scan_workers))
    download_limit = max(config.workers, config.workers * 2)
    scan_limit = max(scan_workers, scan_workers * 3)
    download_futures: dict[concurrent.futures.Future, dict[str, object]] = {}
    scan_futures: dict[concurrent.futures.Future, dict[str, object]] = {}
    waiting_scan: deque[dict[str, object]] = deque()
    rows_exhausted = False
    completed_downloads = completed_scans = matched = failures = 0
    started = time.monotonic()

    def emit_progress() -> None:
        if not callback:
            return
        elapsed = max(0.001, time.monotonic() - started)
        done = completed_scans + failures
        cumulative = min(cumulative_total, completed_before + done)
        callback(ProgressEvent(
            "download",
            f"Downloaded {completed_downloads:,}; scanned {completed_scans:,}; matches {matched:,}; "
            f"errors {failures:,}; {done/elapsed:.1f}/s; project {cumulative:,}/{cumulative_total:,}",
            cumulative, cumulative_total,
            {"downloaded": completed_downloads, "scanned": completed_scans, "matched": matched,
             "failures": failures, "download_workers": config.workers, "scan_workers": scan_workers},
        ))

    def schedule_waiting(scan_pool: concurrent.futures.ThreadPoolExecutor) -> None:
        while waiting_scan and len(scan_futures) < scan_limit:
            item = waiting_scan.popleft()
            capture_id = int(item["id"])
            path = Path(str(item["local_path"]))
            with database:
                database.execute("UPDATE captures SET state='scanning',updated_at=? WHERE id=?", (utc_now(), capture_id))
            future = scan_pool.submit(_scan_saved_capture, item, path, config, jobs)
            scan_futures[future] = item

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=config.workers, thread_name_prefix="archive-download") as download_pool, concurrent.futures.ThreadPoolExecutor(max_workers=scan_workers, thread_name_prefix="archive-scan") as scan_pool:
            # Resume durable downloaded-but-unscanned work before requesting more bytes.
            for row in _pending_scan_rows(database, config, capture_ids):
                waiting_scan.append(dict(row))
                if len(waiting_scan) >= scan_limit:
                    break
            schedule_waiting(scan_pool)

            while True:
                if stop_event.is_set():
                    raise Stopped

                # Feed replay workers only while scanner backlog remains bounded.
                while not rows_exhausted and len(download_futures) < download_limit and (len(waiting_scan) + len(scan_futures)) < scan_limit * 2:
                    try:
                        row = next(row_iter)
                    except StopIteration:
                        rows_exhausted = True
                        break
                    row_dict = dict(row)
                    path = _allocate_capture_path(database, config.output_dir, row)
                    row_dict["assigned_path"] = str(path)
                    with database:
                        database.execute(
                            "UPDATE captures SET state='downloading',local_path=?,download_attempts=download_attempts+1,updated_at=? WHERE id=?",
                            (str(path), utc_now(), int(row["id"])),
                        )
                    download_futures[download_pool.submit(_download_capture, row_dict, path, config, client)] = row_dict

                if download_futures:
                    done_downloads, _ = concurrent.futures.wait(
                        tuple(download_futures), timeout=0.05, return_when=concurrent.futures.FIRST_COMPLETED
                    )
                else:
                    done_downloads = set()
                for future in done_downloads:
                    row = download_futures.pop(future)
                    capture_id = int(row["id"])
                    try:
                        result = future.result()
                        if result["kind"] == "non_text":
                            with database:
                                mark_capture_skipped(database, capture_id, "sniffed_non_text", CLASSIFIER_REVISION)
                            completed_downloads += 1
                            continue
                        path = Path(result["path"])
                        content_hash = str(result["content_hash"])
                        # Best-effort exact-byte CoW dedupe. Never hard-link.
                        storage_method = "file"
                        if config.compact_storage:
                            existing = database.execute(
                                """SELECT local_path FROM captures WHERE id<>? AND content_hash=? AND local_path IS NOT NULL LIMIT 1""",
                                (capture_id, content_hash),
                            ).fetchone()
                            if existing and Path(str(existing["local_path"])).is_file():
                                storage_method = deduplicate_exact_file(path, Path(str(existing["local_path"])))
                        with database:
                            database.execute(
                                """UPDATE captures SET state='downloaded_unscanned',local_path=?,content_hash=?,http_status=?,final_url=?,bytes_saved=?,skip_reason=NULL,classifier_revision=?,updated_at=? WHERE id=?""",
                                (str(path), content_hash, result["http_status"], result["final_url"], result["bytes_saved"], CLASSIFIER_REVISION, utc_now(), capture_id),
                            )
                            database.execute(
                                """INSERT INTO storage_objects(content_hash,canonical_path,size_bytes,reference_count,storage_method,updated_at)
                                   VALUES(?,?,?,?,?,?)
                                   ON CONFLICT(content_hash) DO UPDATE SET reference_count=storage_objects.reference_count+1,updated_at=excluded.updated_at""",
                                (content_hash, str(path), int(result["bytes_saved"]), 1, storage_method, utc_now()),
                            )
                        row.update(result)
                        row["local_path"] = str(path)
                        waiting_scan.append(row)
                        completed_downloads += 1
                    except RateLimitDeferred:
                        with database:
                            database.execute("UPDATE captures SET state='pending',updated_at=? WHERE id=?", (utc_now(), capture_id))
                        raise
                    except Exception as exc:
                        failures += 1
                        category, status, retryable = classify_exception(exc)
                        issue_message = site_issue_message(category, str(row["original_url"]), "text download", status)
                        with database:
                            database.execute("UPDATE captures SET state='error',http_status=?,updated_at=? WHERE id=?", (status, utc_now(), capture_id))
                            record_error(database, "download", category, repr(exc), capture_id=capture_id, http_status=status, retryable=retryable)
                            if should_surface_site_issue(category):
                                record_site_issue(database, host_from_url(str(row["original_url"])), "text_download", category, issue_message, target=str(row["original_url"]), http_status=status)

                schedule_waiting(scan_pool)

                if scan_futures:
                    done_scans, _ = concurrent.futures.wait(
                        tuple(scan_futures), timeout=0.05, return_when=concurrent.futures.FIRST_COMPLETED
                    )
                else:
                    done_scans = set()
                scan_results: list[tuple[dict[str, object], dict | BaseException]] = []
                for future in done_scans:
                    row = scan_futures.pop(future)
                    try:
                        scan_results.append((row, future.result()))
                    except Exception as exc:
                        scan_results.append((row, exc))
                if scan_results:
                    # One transaction for a whole completed scanner group.
                    with database:
                        for row, outcome in scan_results:
                            capture_id = int(row["id"])
                            if isinstance(outcome, BaseException):
                                failures += 1
                                record_error(database, "scan", "scan_failure", repr(outcome), capture_id=capture_id, retryable=True)
                                database.execute("UPDATE captures SET state='downloaded_unscanned',updated_at=? WHERE id=?", (utc_now(), capture_id))
                                continue
                            if outcome.get("kind") == "non_text":
                                mark_capture_skipped(database, capture_id, "sniffed_non_text", CLASSIFIER_REVISION)
                                continue
                            save_success(database, outcome)
                            completed_scans += 1
                            matched += int(any(
                                int(analysis.get("score") or 0) >= config.minimum_score
                                and not analysis.get("excluded") and not analysis.get("required_missing")
                                for analysis in outcome["analyses"].values()
                            ))
                    emit_progress()

                schedule_waiting(scan_pool)

                if rows_exhausted and not download_futures and not waiting_scan and not scan_futures:
                    # There may be additional durable scan rows not initially loaded.
                    extra = list(_pending_scan_rows(database, config, capture_ids))[:scan_limit]
                    if extra:
                        waiting_scan.extend(dict(row) for row in extra)
                        schedule_waiting(scan_pool)
                        continue
                    break
    except Stopped:
        for future in download_futures:
            future.cancel()
        for future in scan_futures:
            future.cancel()
        with database:
            database.execute("UPDATE captures SET state='pending' WHERE state='downloading'")
            database.execute("UPDATE captures SET state='downloaded_unscanned' WHERE state='scanning'")
        raise
    finally:
        client.close()
