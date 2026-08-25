from __future__ import annotations

import json
import math
import re
import sqlite3
from dataclasses import dataclass, field

from ..config import ProjectConfig
from ..utils import clean_space, normalize_search, utc_now
from .embeddings import cosine, decode_int8_vector, encode_text, vector_bands

WORD_RE = re.compile(r"[\w'-]+", re.UNICODE)


@dataclass(slots=True)
class ResearchResult:
    document_id: int
    score: float
    vector_score: float
    text_score: float
    entity_score: float
    archive_score: float
    timestamp: str
    original_url: str
    title: str
    snippet: str
    duplicate_group_id: int | None = None
    related_document_ids: list[int] = field(default_factory=list)
    relationships: list[dict] = field(default_factory=list)
    entities: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "document_id": self.document_id,
            "score": round(self.score, 6),
            "vector_score": round(self.vector_score, 6),
            "text_score": round(self.text_score, 6),
            "entity_score": round(self.entity_score, 6),
            "archive_score": round(self.archive_score, 6),
            "timestamp": self.timestamp,
            "original_url": self.original_url,
            "title": self.title,
            "snippet": self.snippet,
            "duplicate_group_id": self.duplicate_group_id,
            "related_document_ids": self.related_document_ids,
            "relationships": self.relationships,
            "entities": self.entities,
        }


def _fts_query(query: str) -> str:
    tokens = [token.replace('"', '') for token in WORD_RE.findall(query) if len(token) > 1]
    return " OR ".join(f'"{token}"' for token in tokens[:24])


def _snippet(body: str, query: str, limit: int = 520) -> str:
    body = clean_space(body)
    if not body:
        return ""
    lowered = normalize_search(body)
    positions = [lowered.find(normalize_search(token)) for token in WORD_RE.findall(query) if len(token) > 2]
    positions = [pos for pos in positions if pos >= 0]
    center = min(positions) if positions else 0
    start = max(0, center - limit // 3)
    end = min(len(body), start + limit)
    prefix = "…" if start else ""
    suffix = "…" if end < len(body) else ""
    return prefix + body[start:end] + suffix


def _candidate_ids(database: sqlite3.Connection, query: str, query_vector: tuple[float, ...], limit: int) -> tuple[set[int], dict[int, float]]:
    candidates: set[int] = set()
    fts_scores: dict[int, float] = {}
    enabled = database.execute("SELECT value FROM project_meta WHERE key='fts5'").fetchone()
    if enabled and enabled[0] == "1":
        fts = _fts_query(query)
        if fts:
            try:
                rows = database.execute(
                    "SELECT rowid,bm25(documents_fts) AS rank FROM documents_fts WHERE documents_fts MATCH ? ORDER BY rank LIMIT ?",
                    (fts, max(100, min(limit, 10000))),
                ).fetchall()
                for rank_index, row in enumerate(rows):
                    document_id = int(row[0])
                    candidates.add(document_id)
                    # Rank-based normalization is stable across FTS build versions.
                    fts_scores[document_id] = max(0.0, 1.0 - (rank_index / max(1, len(rows))))
            except sqlite3.OperationalError:
                pass

    bands = vector_bands(query_vector)
    for band, bucket in bands:
        for row in database.execute(
            "SELECT document_id FROM research_vector_bands WHERE band=? AND bucket=? LIMIT ?",
            (band, bucket, max(100, limit)),
        ):
            candidates.add(int(row[0]))
            if len(candidates) >= limit * 2:
                break
    # Entity references often surface filenames/usernames/domains that vector
    # hashing intentionally downweights. Include them as candidates.
    terms = [normalize_search(token) for token in WORD_RE.findall(query) if len(token) > 2][:12]
    for term in terms:
        for row in database.execute(
            """
            SELECT rde.document_id FROM research_entities re
            JOIN research_document_entities rde ON rde.entity_id=re.id
            WHERE re.normalized LIKE ? LIMIT ?
            """,
            ("%" + term + "%", max(50, limit // 4)),
        ):
            candidates.add(int(row[0]))
    if not candidates:
        for row in database.execute("SELECT document_id FROM research_vectors ORDER BY document_id LIMIT ?", (max(100, limit),)):
            candidates.add(int(row[0]))
    return candidates, fts_scores


def search_research(
    config: ProjectConfig,
    database: sqlite3.Connection,
    query: str,
    limit: int | None = None,
    *,
    save_query: bool = True,
) -> list[ResearchResult]:
    config = config.normalized()
    research = config.research.normalized()
    query = clean_space(query)
    if not query:
        return []
    indexed = database.execute("SELECT COUNT(*) FROM research_vectors").fetchone()[0]
    if not indexed:
        raise RuntimeError("Research Intelligence index is empty. Build/refresh it first.")
    limit = min(research.result_limit, max(1, int(limit or research.result_limit)))
    backend_row = database.execute("SELECT backend,dimensions FROM research_vectors ORDER BY document_id LIMIT 1").fetchone()
    backend = "fastembed" if backend_row and str(backend_row[0]).startswith("fastembed") else "local-hash"
    dimensions = int(backend_row[1]) if backend_row else research.vector_dimensions
    _, encoded = encode_text(query, backend, dimensions)
    candidate_ids, fts_scores = _candidate_ids(database, query, encoded.values, research.candidate_limit)

    results: list[ResearchResult] = []
    query_terms = {normalize_search(token) for token in WORD_RE.findall(query) if len(token) > 2}
    for chunk_start in range(0, len(candidate_ids), 800):
        chunk = list(candidate_ids)[chunk_start:chunk_start + 800]
        placeholders = ",".join("?" for _ in chunk)
        rows = database.execute(
            f"""
            SELECT rv.document_id,rv.vector_blob,rv.dimensions,d.title,d.body_text,c.original_url,c.timestamp,
                   COALESCE((SELECT MAX(score) FROM document_matches m WHERE m.document_id=d.id AND m.excluded=0 AND m.required_missing=0),0) AS archive_score,
                   (SELECT dm.group_id FROM duplicate_members dm WHERE dm.document_id=d.id LIMIT 1) AS duplicate_group_id
            FROM research_vectors rv
            JOIN documents d ON d.id=rv.document_id JOIN captures c ON c.id=d.capture_id
            WHERE rv.document_id IN ({placeholders})
            """,
            tuple(chunk),
        ).fetchall()
        for row in rows:
            document_id = int(row["document_id"])
            vector = decode_int8_vector(bytes(row["vector_blob"]), int(row["dimensions"]))
            vector_score = max(0.0, min(1.0, (cosine(encoded.values, vector) + 1.0) / 2.0)) if vector else 0.0
            text_score = fts_scores.get(document_id, 0.0)
            entities = [dict(item) for item in database.execute(
                """
                SELECT re.kind,re.value,re.normalized FROM research_document_entities rde
                JOIN research_entities re ON re.id=rde.entity_id WHERE rde.document_id=? ORDER BY re.kind,re.normalized LIMIT 24
                """,
                (document_id,),
            )]
            entity_norms = " ".join(str(item["normalized"]) for item in entities)
            entity_hits = sum(1 for term in query_terms if term and term in entity_norms)
            entity_score = min(1.0, entity_hits / max(1, min(4, len(query_terms))))
            raw_archive = float(row["archive_score"] or 0.0)
            archive_score = min(1.0, math.log1p(max(0.0, raw_archive)) / math.log(101.0))
            score = 0.58 * vector_score + 0.24 * text_score + 0.10 * entity_score + 0.08 * archive_score
            relationship_rows = database.execute(
                """
                SELECT e.edge_type,e.weight,e.evidence,
                       CASE WHEN e.source_document_id=? THEN e.target_document_id ELSE e.source_document_id END AS related_document_id,
                       c.timestamp,d.title,c.original_url
                FROM research_edges e
                JOIN documents d ON d.id=CASE WHEN e.source_document_id=? THEN e.target_document_id ELSE e.source_document_id END
                JOIN captures c ON c.id=d.capture_id
                WHERE e.source_document_id=? OR e.target_document_id=?
                ORDER BY c.timestamp,e.weight DESC,e.id LIMIT 20
                """,
                (document_id, document_id, document_id, document_id),
            ).fetchall()
            relationships = [dict(item) for item in relationship_rows]
            related = list(dict.fromkeys(int(item["related_document_id"]) for item in relationships))[:12]
            results.append(ResearchResult(
                document_id=document_id,
                score=score,
                vector_score=vector_score,
                text_score=text_score,
                entity_score=entity_score,
                archive_score=archive_score,
                timestamp=str(row["timestamp"] or ""),
                original_url=str(row["original_url"] or ""),
                title=str(row["title"] or ""),
                snippet=_snippet(str(row["body_text"] or ""), query),
                duplicate_group_id=int(row["duplicate_group_id"]) if row["duplicate_group_id"] is not None else None,
                related_document_ids=related,
                relationships=relationships,
                entities=entities,
            ))
    results.sort(key=lambda item: (-item.score, -item.vector_score, item.timestamp, item.document_id))
    results = results[:limit]

    if save_query:
        with database:
            cursor = database.execute(
                "INSERT INTO research_queries(query,backend,result_count,created_at) VALUES(?,?,?,?)",
                (query, backend, len(results), utc_now()),
            )
            query_id = int(cursor.lastrowid)
            database.executemany(
                """
                INSERT INTO research_query_results(query_id,document_id,rank,score,vector_score,text_score,entity_score,archive_score,explanation_json)
                VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (
                    (query_id, item.document_id, rank, item.score, item.vector_score, item.text_score, item.entity_score,
                     item.archive_score, json.dumps({"snippet": item.snippet, "related": item.related_document_ids}, ensure_ascii=False))
                    for rank, item in enumerate(results, 1)
                ),
            )
    return results
