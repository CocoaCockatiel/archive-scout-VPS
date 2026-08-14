# Archive Scout 1.0.1

Archive Scout 1.0.1 is a reliability maintenance release based on a VPS concurrency/resume audit. It preserves the 1.0 interface and feature set while correcting interrupted-index resume behavior, cumulative progress, and shared Wayback throttling across concurrent work.

## Reliability fixes

- Resume continues an unfinished CDX queue before entering download work.
- HTTP 429 and 503 responses close one process-wide Wayback circuit, including 503 responses without Retry-After.
- Concurrent projects share request-start pacing and host recovery state.
- Coordinated pauses use finite safety budgets instead of an unlimited default.
- Download counters remain cumulative after resume and operation progress is persisted.
- Integrations can distinguish recoverable saved pauses with `is_recoverable_pause()`.

All Archive Scout 1.0 AI relevance, external embedded-media, scanning, reporting, project recovery, and analysis features remain available.
