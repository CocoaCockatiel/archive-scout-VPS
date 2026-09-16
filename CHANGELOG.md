# Changelog

## 1.0.6.2

- Added **Index and download only (no scanning)** to the Operations tab. It indexes the target and downloads textual captures without creating scanner workers, scan runs, documents, matches, research indexes, media jobs, or scan reports.
- Kept SQLite as a lightweight durable manifest/resume queue instead of replacing it with filename-only state, preserving exact URL/timestamp mapping, retries, crash recovery, and Search with Hitlist coverage.
- Added a dedicated acquisition-only replay loop with batched completion writes and reduced operation-progress commits; saved files remain `downloaded_unscanned` for later Hitlist search or local rescan.
- Made the requested fast Settings-tab profile the defaults: 10 download workers, automatic scanner workers, 25 MB text pages, 0.75 s CDX spacing, 0.125 s replay spacing, automatic network choices, 10 parallel CDX requests, automatic page blocks, 30/300 s shared rate-limit pauses, 5/300 s retry backoff, and automatic backups disabled.
- Removed the Ogrish-specific preset and replaced it with general-purpose web archive, legacy forum, lost-media, and blank-project presets.

## 1.0.6.1

- Restored the v1.0.5 high-throughput replay philosophy: ten download workers at the configured 0.125-second shared start spacing are no longer throttled by local scanner backlog.
- Returned SQLite WAL durability to `synchronous=NORMAL` and the 10,000-page auto-checkpoint profile; durable file/state reconciliation still preserves restart safety.
- Batched pre-download state transitions and added an index on `captures.local_path` so URL-derived collision checks do not scan huge capture tables.
- Kept scanner memory bounded while allowing downloaded-but-unscanned work to accumulate durably in SQLite and drain locally after acquisition finishes.
- Deferred exact-byte CoW deduplication for text and media to Compact Project / maintenance instead of performing filesystem compaction in the replay hot path.
- Progress now exposes replay-start, download, scan, and backlog rates separately so network throughput is distinguishable from local CPU throughput.
- Kept all v1.0.6 recall, URL-filename, hitlist, crash-recovery, storage-compaction, dashboard, and indexing-checkpoint features.

## 1.0.6

- Split Wayback replay acquisition from local parsing/scanning so ten replay workers remain focused on retrieval while a separate CPU-oriented scanner pool handles saved captures. Downloaded payloads are checkpointed as `downloaded_unscanned` before analysis, allowing restart/reboot recovery without repeating completed network work.
- Raised scanning recall: full raw source is searched without the old 500,000-character source truncation; UTF-16/UTF-32 BOMs and legacy charset hints are recognized; JavaScript/JSON hex escapes and markup-split text are searchable; conflicting/weak MIME and extension metadata are sniffed instead of silently discarded; SVG and legacy `.dhtml`, `.phtml`, `.php3`, `.php4`, `.php5` text are supported.
- Turned native Aho-Corasick into the direct ordinary-literal counter/scorer while retaining regex, case-sensitive, and whole-word paths for advanced rules.
- Added resumable **Search with Hitlist** for one keyword, pasted lists, or `.txt` hitlists. It searches all indexed URLs and complete locally saved capture contents without research scoring/enrichment and reports explicit coverage.
- Added schema 8 durable state: explicit capture skip reasons/classifier revision, `local_path`/content metadata, quick-search state/results, and per-page index checkpoints. Completed numbered Timemap pages are not repeated merely because a process stops inside a larger scheduling group.
- Reworked intentional skips and the Dashboard: known non-text captures and URL-filter exclusions are auditable skip counts rather than Open Errors; transient recovered network/index events remain separate from active failures; changing from URL-keyword-only scope to thorough text mode requeues applicable captures.
- Standardized new text and media filenames on one portable, recognizable full-URL-derived naming policy with deterministic timestamp/length fallbacks only when needed to prevent collisions or exceed filesystem limits. Existing files are not destructively renamed.
- Added storage-efficiency work: canonical replay payloads stay on disk instead of duplicating full body text in SQLite, FTS5 uses a contentless token index, exact duplicate files may use safe copy-on-write clones where supported, backups are compressed/budgeted, WAL growth is bounded/checkpointed, and Compact Project can reclaim verified redundant/regenerable storage without deleting unique captures.
- Added safer partial-download persistence and recovery plus stronger pause/save checkpoints.
- Kept v1.0.5's Timemap-first `pageSize=9`, ten-worker, ~80-request/minute indexing envelope; v1.0.6 focuses indexing changes on durable per-page completion state rather than replacing the acquisition architecture.
- On macOS only, the packaged outer product remains `Archive Scout.app` while the inner executable/process identity is `Wayback Machine Downloader` as a best-effort Discord automatic-activity naming change.

## 1.0.5

- Changed automatic CDX indexing to the fast Timemap numbered-page pipeline: fixed pageSize=9, ten concurrent page workers, Timemap JSON first, and a rolling queue of up to 1,000 pages. Auto mode forces the reference page grouping even when an older saved queue carried a different numbered-page block value.
- Preserved resume-key traversal as the recovery path for unavailable pagination, repeated slow pages, and explicit resume mode.
- Applied the same parallel Timemap acquisition logic to direct-media indexing.
- Standardized media output to exactly two flat directories: `media/images/` and `media/videos/`.
- Media files now use the original URL filename without timestamp, database-id, host, or path prefixes; raw percent-escaped URL spelling is preserved whenever portable filesystems allow it.
- Media replay fetching now follows the reference downloader's `if_` behavior (`oe_` for SWF), keeps the ten-worker/eight-starts-per-second envelope, uses at least five transient retries, prioritizes known-small files, and skips network work when the exact destination already exists.
- Project merge media copies now honor the same flat images/videos layout.

## 1.0.4

- Raised the default replay-download envelope to ten persistent workers with 0.125-second request-start spacing (up to eight starts/second), while retaining coordinated 429/503 host pauses, bounded in-flight work, retries, and resumability.
- Added native `ahocorasick-rs` matching and `selectolax`/Lexbor HTML parsing to the hot scan path, with the existing Python implementations retained as safe fallbacks.
- Removed a duplicate literal-prefilter traversal and reused the already-normalized body when computing document hashes.
- Added legacy text-page extensions `.shtm`, `.dhtm`, `.xhtm`, `.phtm`, and `.dat`; existing `.htm`, `.cgi`, `.php`, and `.txt` support remains.
- Fixed `Index URLs only` so it immediately writes `reports/all_indexed_urls.txt`, `summary.txt`, `errors.txt`, and `site_issues.txt`; report regeneration now also works for index-only projects without a scan run.

## 1.0.3

- Replaced automatic numbered CDX paging with resume-key-first traversal for broad indexes, eliminating the thousands-of-pages failure mode on very large sites.
- Automatically converts unfinished v1.0.2 numbered-page queues to resumable row batches without deleting captures already stored in SQLite.
- Increased the default resumable CDX batch to 100,000 rows while preserving adaptive date-window subdivision, shared request pacing, finite pause budgets, and explicit paged mode for diagnostics.
- Applied the same resume-key-first strategy to direct-media indexing and fixed automatic media paging so `page_blocks=0` can never become `pageSize=1`.
- Reduced embedded-media exact lookups to the minimum CDX data required for earliest/latest policies and parallelized bounded external-asset/media discovery.
- Optimized CDX parsing/ingestion, error lookups, HTML parsing, media URL policy checks, keyword/proximity scoring, duplicate analysis, snapshot analysis, report replacement, and analysis batching.
- Reworked Research Intelligence indexing/search hot paths to reduce N+1 queries, project-sized temporary state, redundant graph rebuilds, and unnecessary entity/vector work.
- Added database indexes for hot review/error/analysis relationships without changing schema version 7.
- Added regression coverage for automatic resume traversal, v1.0.2 queue conversion, 100,000-row continuation, media indexing, URL-key continuation, and compact CDX row semantics.
- Centralized product version reporting in the CLI and AI provider user agents to prevent release metadata drift.

## 1.0.2

- Added project-wide Research Intelligence with local hybrid vector/full-text/entity retrieval, duplicate clustering, evidence relationships, and chronological connection context.
- Added citation-grounded deep AI research over a bounded evidence set while keeping deterministic scores and human review authoritative.
- Added optional FastEmbed local neural embeddings while retaining a dependency-free local-hash backend.
- Replaced the old forced `pageSize=9` broad-CDX default with server-selected large pagination and bounded concurrent large response bodies.
- Added a complete bot/automation CLI with JSON/JSONL progress, stable exit codes, graceful interruption, noninteractive init, and read-only inspection commands.
- Added separate packaged CLI executables on Windows, Linux, and universal macOS.
- Added OpenAI/OpenRouter provider adapters and safe ignored `.env` developer configuration without credential persistence.
- Added schema version 7 and migration coverage for Research Intelligence tables.
- Added agent/automation/provider documentation and expanded release regression coverage.

## 1.0.1

- Resume now re-enters any saved incomplete CDX index queue before downloading, so an interrupted indexing run cannot be mistaken for a complete project.
- Wayback 503 responses now enter the same process-wide coordinated host pause as 429 responses even when Retry-After is absent.
- All archive/index/media clients in one process now share request-start coordination and a host recovery gate, preventing concurrent projects on one machine or VPS from multiplying traffic independently.
- Coordinated pause budgets are finite by default (15 minutes / 8 incidents); legacy zero values normalize to the safety defaults instead of waiting indefinitely.
- Download progress is cumulative across resumes and operation progress is persisted in operation_runs for external integrations.
- Added is_recoverable_pause() as a stable integration contract so bot/front-end wrappers can report saved network pauses separately from failures.
- Added regression coverage for the audit findings.

## 1.0.0

- First official Archive Scout release.
- Added optional OpenAI-powered AI relevance review for completed scan reports.
- Added structured, explainable AI relevance results without replacing deterministic scores or human reviews.
- Added schema version 6 for AI runs/results, persistent external-media discovery, and site-specific Wayback issue tracking.
- Rebuilt external embedded-media discovery around persistent queues, bounded parallel discovery, bounded exact-CDX lookups, host-level policy circuits, and broader modern/legacy embed extraction.
- Preserved the intended external-media workflow: index site → download/scan text → discover external media → resolve archived captures → stream media downloads.
- Added explicit communication for Wayback exclusions, robots.txt restrictions, unavailable captures, access restrictions, invalid replay pages, origin errors, rate limits, timeouts, connection failures, TLS issues, and service errors.
- Retained persistent/resumable CDX work, request pacing, transport fallback, date-window recovery, bulk database insertion, keyset pagination, no-op writes, size-aware scheduling, and direct-to-disk media downloads.
- Retained multi-keyword-set scanning, FTS search, review statuses/notes/tags, report exports, scan comparison, forum reconstruction, legacy embed extraction, provenance, duplicate analysis, first-appearance analysis, project repair, backups, diagnostics, and secure project merging.
- Rebranded product-facing documentation, metadata, startup UI, packaging, and release workflows to the official Archive Scout name and version 1.0.0.
