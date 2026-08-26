# Changelog

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
