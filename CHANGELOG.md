# Changelog

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
