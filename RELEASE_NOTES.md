# Archive Scout 1.0.0

Archive Scout 1.0.0 is the first official release. It keeps the established project workflow and interface while promoting the hardened indexing, download, scan, review, recovery, media, and analysis systems into the stable product line.

## AI relevance review

A new optional AI relevance page can rank the existing results of a completed scan against a natural-language research goal. It uses the OpenAI Responses API with structured output and stores relevance, confidence, category, reasoning, and evidence summaries separately from deterministic Archive Scout scores and human reviews.

The API key is never stored in project configuration or normal application settings. AI review is opt-in and is not required for any other feature.

## External embedded media

The external-media operation received a major reliability and performance overhaul while preserving its intended sequence: index the requested site, download and scan its text pages, discover embedded media, resolve archived media captures, then download them.

Highlights include a persistent discovery queue, document-content reuse, bounded local discovery workers, bounded exact-CDX lookup overlap, host-level exclusion circuits, improved lazy/social/CSS/legacy media extraction, Wayback replay URL unwrapping, extensionless media support, direct-to-disk streaming, and size-aware scheduling.

## Clearer Wayback diagnostics

Archive Scout now records and surfaces site-specific archive conditions such as Wayback exclusions, robots.txt restrictions, missing captures, access-restricted index requests, archived origin errors, invalid replay redirects, rate limiting, timeouts, and other service failures. Confirmed permanent host restrictions prevent repeated futile work while unrelated targets continue.

## Performance and reliability

The official release retains and extends the optimized execution engine: persistent work queues, bulk SQLite writes, keyset pagination, bounded concurrency, resumable indexing, large literal-rule automata, no-op repeated writes, bounded local rescanning, atomic exports, and direct-to-disk media handling.

## Compatibility

Project database schema version is 6. Supported earlier schemas are migrated in place after a safety backup. Existing review records, scan history, media captures, reports, analysis data, and project settings remain supported.
