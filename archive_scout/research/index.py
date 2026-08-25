from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from typing import Callable

from ..analysis.duplicates import cluster_duplicates
from ..config import ProjectConfig
from ..events import ProgressEvent, Stopped
from ..utils import utc_now
from .embeddings import encode_text, vector_bands
from .entities import extract_entities


@dataclass(slots=True)
class ResearchIndexSummary:
    indexed: int = 0
    unchanged: int = 0
    removed: int = 0
    entities: int = 0
    edges: int = 0
    duplicate_groups: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "indexed": self.indexed,
            "unchanged": self.unchanged,
            "removed": self.removed,
            "entities": self.entities,
            "edges": self.edges,
            "duplicate_groups": self.duplicate_groups,
        }


def _emit(callback: Callable[[ProgressEvent], None] | None, event: ProgressEvent) -> None:
    if callback:
        callback(event)


def _document_text(row: sqlite3.Row, excerpt_chars: int) -> str:
    body = str(row["body_text"] or "")
    if len(body) > excerpt_chars * 8:
        body = body[: excerpt_chars * 8]
    return "\n".join(part for part in (str(row["title"] or ""), str(row["original_url"] or ""), body) if part)


def _replace_entities(database: sqlite3.Connection, document_id: int, entities) -> int:
    database.execute("DELETE FROM research_document_entities WHERE document_id=?", (document_id,))
    unique = {(entity.kind, entity.normalized): entity for entity in entities if entity.normalized}
    if not unique:
        return 0
    database.executemany(
        "INSERT OR IGNORE INTO research_entities(kind,value,normalized) VALUES(?,?,?)",
        ((entity.kind, entity.value, entity.normalized) for entity in unique.values()),
    )
    ids: dict[tuple[str, str], int] = {}
    normalized_values = list(dict.fromkeys(entity.normalized for entity in unique.values()))
    for offset in range(0, len(normalized_values), 400):
        chunk = normalized_values[offset:offset + 400]
        placeholders = ",".join("?" for _ in chunk)
        for row in database.execute(
            f"SELECT id,kind,normalized FROM research_entities WHERE normalized IN ({placeholders})",
            tuple(chunk),
        ):
            ids[(str(row["kind"]), str(row["normalized"]))] = int(row["id"])
    links = [
        (document_id, ids[key], 1)
        for key in unique
        if key in ids
    ]
    if links:
        database.executemany(
            "INSERT OR IGNORE INTO research_document_entities(document_id,entity_id,occurrence_count) VALUES(?,?,?)",
            links,
        )
    return len(links)


def _rebuild_graph(database: sqlite3.Connection, stop_event: threading.Event) -> int:
    database.execute("DELETE FROM research_edges")
    now = utc_now()
    edge_rows: list[tuple[int, int, str, float, str, str]] = []

    def flush_edges() -> None:
        if not edge_rows:
            return
        database.executemany(
            "INSERT OR IGNORE INTO research_edges(source_document_id,target_document_id,edge_type,weight,evidence,created_at) VALUES(?,?,?,?,?,?)",
            edge_rows,
        )
        edge_rows.clear()

    def add_edge(edge: tuple[int, int, str, float, str, str]) -> None:
        edge_rows.append(edge)
        if len(edge_rows) >= 5000:
            flush_edges()

    # Explicit archived hyperlinks are strong provenance edges.
    for row in database.execute("SELECT id,links_json FROM documents WHERE COALESCE(links_json,'')<>'' ORDER BY id"):
        if stop_event.is_set():
            raise Stopped
        source_id = int(row["id"])
        try:
            links = json.loads(str(row["links_json"] or "[]"))
        except Exception:
            links = []
        seen: set[int] = set()
        for link in links[:300]:
            target = database.execute(
                "SELECT d.id FROM captures c JOIN documents d ON d.capture_id=c.id WHERE c.original_url=? ORDER BY c.timestamp LIMIT 1",
                (str(link),),
            ).fetchone()
            if not target:
                continue
            target_id = int(target[0])
            if target_id == source_id or target_id in seen:
                continue
            seen.add(target_id)
            add_edge((source_id, target_id, "hyperlink", 1.0, str(link)[:1000], now))
    # Existing duplicate clusters become explicit graph relationships.
    for row in database.execute(
        """
        SELECT dm.document_id,dg.representative_document_id,dm.similarity,dg.method
        FROM duplicate_members dm JOIN duplicate_groups dg ON dg.id=dm.group_id
        WHERE dm.document_id<>dg.representative_document_id
        """
    ):
        add_edge((int(row[0]), int(row[1]), "duplicate:" + str(row[3]), float(row[2]), "", now))

    # Provenance analysis is already a high-confidence relationship source; fold
    # those links into the same evidence graph instead of making researchers
    # cross-reference a second subsystem manually.
    for row in database.execute(
        "SELECT source_document_id,mirror_document_id,method,similarity FROM provenance_edges"
    ):
        if int(row[0]) != int(row[1]):
            add_edge((int(row[0]), int(row[1]), "provenance:" + str(row[2]), float(row[3]), "", now))

    # Forum reconstruction also contributes temporal relationships. Connect each
    # archived post-document to the first document seen for its reconstructed
    # thread. This avoids a dense all-to-all graph for large threads.
    for row in database.execute(
        """
        SELECT fp.document_id,firsts.representative_document_id,fp.thread_id
        FROM forum_posts fp
        JOIN (SELECT thread_id,MIN(document_id) AS representative_document_id FROM forum_posts GROUP BY thread_id) firsts
          ON firsts.thread_id=fp.thread_id
        WHERE fp.document_id<>firsts.representative_document_id
        """
    ):
        add_edge((int(row[0]), int(row[1]), "forum_thread", 0.9, f"thread:{int(row[2])}", now))
    flush_edges()
    return int(database.execute("SELECT COUNT(*) FROM research_edges").fetchone()[0])


def build_research_index(
    config: ProjectConfig,
    database: sqlite3.Connection,
    stop_event: threading.Event | None = None,
    callback: Callable[[ProgressEvent], None] | None = None,
) -> ResearchIndexSummary:
    config = config.normalized()
    research = config.research.normalized()
    stop_event = stop_event or threading.Event()
    total = int(database.execute("SELECT COUNT(*) FROM documents WHERE COALESCE(body_text,'')<>''").fetchone()[0])
    summary = ResearchIndexSummary()
    _emit(callback, ProgressEvent("research_index", f"Building local Research Intelligence index for {total:,} documents…", 0, total))

    existing_ids = {int(row[0]) for row in database.execute("SELECT document_id FROM research_vectors")}
    live_ids: set[int] = set()
    processed = 0
    for row in database.execute(
        """
        SELECT d.id,d.title,d.body_text,d.links_json,d.content_hash,c.original_url,c.timestamp
        FROM documents d JOIN captures c ON c.id=d.capture_id
        WHERE COALESCE(d.body_text,'')<>'' ORDER BY d.id
        """
    ):
        if stop_event.is_set():
            raise Stopped
        document_id = int(row["id"])
        live_ids.add(document_id)
        content_hash = str(row["content_hash"] or "")
        existing = database.execute(
            "SELECT content_hash,backend,dimensions FROM research_vectors WHERE document_id=?",
            (document_id,),
        ).fetchone()
        desired_backend = research.vector_backend
        backend_matches = bool(existing and (
            (desired_backend == "local-hash" and str(existing["backend"]).startswith("local-hash"))
            or (desired_backend == "fastembed" and str(existing["backend"]).startswith("fastembed"))
        ))
        if existing and str(existing["content_hash"] or "") == content_hash and backend_matches:
            summary.unchanged += 1
        else:
            text = _document_text(row, research.excerpt_chars)
            backend_name, vector = encode_text(text, research.vector_backend, research.vector_dimensions)
            links: list[str]
            try:
                links = list(json.loads(str(row["links_json"] or "[]")))
            except Exception:
                links = []
            with database:
                database.execute(
                    """
                    INSERT INTO research_vectors(document_id,content_hash,backend,dimensions,vector_blob,norm,token_count,indexed_at)
                    VALUES(?,?,?,?,?,?,?,?)
                    ON CONFLICT(document_id) DO UPDATE SET
                      content_hash=excluded.content_hash,backend=excluded.backend,dimensions=excluded.dimensions,
                      vector_blob=excluded.vector_blob,norm=excluded.norm,token_count=excluded.token_count,indexed_at=excluded.indexed_at
                    """,
                    (document_id, content_hash, backend_name, len(vector.values), vector.blob, vector.norm, vector.token_count, utc_now()),
                )
                database.execute("DELETE FROM research_vector_bands WHERE document_id=?", (document_id,))
                database.executemany(
                    "INSERT INTO research_vector_bands(document_id,band,bucket) VALUES(?,?,?)",
                    ((document_id, band, bucket) for band, bucket in vector_bands(vector.values)),
                )
                if research.entity_extraction:
                    entities = extract_entities(str(row["title"] or ""), str(row["body_text"] or ""), str(row["original_url"] or ""), links)
                    summary.entities += _replace_entities(database, document_id, entities)
            summary.indexed += 1
        processed += 1
        if processed % 100 == 0 or processed == total:
            _emit(callback, ProgressEvent(
                "research_index",
                f"Research Intelligence indexed {processed:,}/{total:,} documents ({summary.indexed:,} updated; {summary.unchanged:,} unchanged)",
                processed,
                total,
            ))

    stale = existing_ids - live_ids
    if stale:
        placeholders = ",".join("?" for _ in stale)
        with database:
            database.execute(f"DELETE FROM research_vectors WHERE document_id IN ({placeholders})", tuple(stale))
        summary.removed = len(stale)

    if research.duplicate_clustering:
        _emit(callback, ProgressEvent("research_index", "Clustering exact and near-duplicate documents…", processed, total))
        duplicate_summary = cluster_duplicates(database)
        summary.duplicate_groups = duplicate_summary.exact_groups + duplicate_summary.near_groups
    _emit(callback, ProgressEvent("research_index", "Building evidence relationships…", processed, total))
    with database:
        summary.edges = _rebuild_graph(database, stop_event)
        database.execute("INSERT OR REPLACE INTO project_meta(key,value) VALUES('research_index_version','1')")
        database.execute("INSERT OR REPLACE INTO project_meta(key,value) VALUES('research_indexed_at',?)", (utc_now(),))
    _emit(callback, ProgressEvent(
        "research_index",
        f"Research Intelligence ready: {total:,} documents, {summary.duplicate_groups:,} duplicate groups, {summary.edges:,} evidence edges.",
        total,
        total,
        summary.to_dict(),
    ))
    return summary
