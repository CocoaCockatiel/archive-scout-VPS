# Archive Scout 1.0.4

Archive Scout 1.0.4 is the high-throughput replay release. It preserves schema version 7 and the v1.0.3 resume-key CDX architecture while bringing text replay throughput much closer to the fast standalone Wayback downloader profile.

## High-throughput text replay

- New projects default to 10 text replay workers with 0.125-second request-start spacing, allowing up to eight replay starts per second while retaining the process-wide Wayback host gate.
- Untouched v1.0.3 replay defaults (4 workers / 0.5 seconds) migrate automatically; customized replay settings are preserved.
- Rust-backed `ahocorasick-rs` accelerates literal keyword discovery and releases the GIL while matching.
- `selectolax`/Lexbor accelerates HTML title/text/link extraction, with the existing Python parser retained as a fallback.
- Literal prefiltering now discovers candidates and positive matches in one traversal instead of scanning normalized fields twice.
- Document hashing reuses the already-normalized visible body instead of normalizing it again.

## Text formats

Archive Scout now explicitly treats `.htm`, `.shtm`, `.dhtm`, `.xhtm`, `.phtm`, `.cgi`, `.php`, `.dat`, and `.txt` as scannable text-page formats, alongside the existing HTML/XML/JSON/script formats.

## Index-only reports

`Index URLs only` now writes `reports/all_indexed_urls.txt`, `reports/summary.txt`, `reports/errors.txt`, and `reports/site_issues.txt` immediately after CDX indexing. `Regenerate reports only` also works on an index-only project even when no scan run exists.

## Compatibility

- Public version: 1.0.4.
- Database schema remains version 7.
- Existing projects remain compatible.
- Faster replay defaults retain coordinated HTTP 429/503 pauses, retries, bounded in-flight work, and saved resume state.

---

# Archive Scout 1.0.3

Archive Scout 1.0.3 is the final performance-focused release. It keeps the 1.0.2 interface and feature set, but replaces the slowest acquisition architecture and applies a full hot-path optimization pass across indexing, media, scanning, analysis, reports, SQLite, and Research Intelligence.

## Indexing

- Automatic broad indexing is now resume-key-first instead of numbered-page-first.
- Default resume batches increase from 50,000 to 100,000 CDX rows.
- Existing unfinished 1.0.2 numbered queues are converted safely on resume; already indexed captures remain in SQLite.
- `urlkey` is retained in CDX fields so continuation ordering is explicit and reliable while compact stored row shape remains unchanged.
- Healthy target-years begin as one large resumable window and subdivide only when Wayback actually times out or rejects the request.
- Explicit paged indexing remains available for compatibility and troubleshooting.
- Shared process-wide request pacing, host gating, finite 429/503 pause budgets, transport fallback, and exact saved recovery state remain intact.

## Media

- Direct media indexing uses the same resume-key-first traversal.
- Automatic `page_blocks=0` is no longer capable of degrading into `pageSize=1`.
- Earliest/latest exact embedded-media lookups request only the capture needed instead of traversing a large result set.
- Embedded discovery avoids a second full HTML parser pass and batches local discovery writes.
- External asset/media lookups use bounded concurrency under the same shared Wayback limiter.
- Media extension and allow/exclude policies are compiled and reused instead of rebuilt for every candidate URL.

## Local scanning and analysis

- Literal candidate collection reuses output sets instead of allocating one per field.
- Regex matches are streamed instead of materialized into temporary lists.
- Proximity scoring uses ordered two-pointer distance calculation instead of Cartesian keyword-position comparisons.
- Single-keyword matches skip sentence/paragraph/proximity passes that cannot change their score.
- HTML title extraction is folded into the existing parser pass; URL extraction and extension checks avoid unnecessary temporary objects.
- Duplicate SimHash generation, snapshot comparison, first-appearance searching, extraction work, and analysis writes were tightened for large projects.

## Database, reports, and Research Intelligence

- Compact CDX rows are unpacked once per insert instead of repeating mapping/position work for every field.
- Error identity lookups are sargable and backed by targeted indexes.
- Additional indexes accelerate document-match, duplicate, forum, and legacy-asset relationship queries.
- Research Intelligence bulk-fetches candidate entities/relationships and avoids project-sized Python sets during stale-vector cleanup.
- Evidence graph rebuilding is skipped when its dependencies are unchanged.
- Report replacement and several analysis stages avoid unnecessary filesystem/database work.

## Compatibility

- Public version: 1.0.4.
- Database schema remains version 7.
- Existing 1.0.0–1.0.2 projects remain supported.
- GUI, CLI/bot automation, AI providers, external embedded media, review/report workflows, project recovery, diagnostics, and Research Intelligence remain available.
