# Archive Scout 1.0.2

Archive Scout 1.0.2 is the Research Intelligence, fast-indexing, and automation release. It preserves the 1.0 desktop workflow while removing the broad-CDX page-count bottleneck and adding a bot-safe command-line contract.

## Research Intelligence

- Added a persistent project-wide research index over downloaded documents.
- Added hybrid local retrieval using full-text evidence, compact vectors, extracted entities, deterministic Archive Scout scores, duplicate clusters, and relationship edges.
- Added evidence graph/timeline relationships from hyperlinks, duplicate groups, provenance analysis, and reconstructed forum threads.
- Added optional citation-grounded deep AI review. Archived source text is treated as hostile data, and unsupported document-ID citations are discarded.
- Added incremental indexing: unchanged document hashes are not re-embedded/re-extracted.
- Added dependency-free `local-hash` retrieval and an optional FastEmbed backend for source installations.

## Faster broad indexing

- Removed the old forced nine-ZipNum-block CDX page size for broad paginated queries.
- Broad paging now uses the CDX server's configured large page grouping by default, drastically reducing HTTP page count for very large sites.
- Large server-sized page bodies use a bounded three-request concurrency cap; explicit smaller page sizes can use more overlap.
- Existing resume-key recovery, year windows, persistence, site-issue reporting, and shared Wayback rate coordination are preserved.
- Untouched 1.0.1 `page_blocks=9` projects automatically adopt the new default; deliberately customized page sizes remain unchanged.

## Automation and bots

- Added `run`, `init`, `status`, `search`, `results`, `errors`, `research-index`, `research`, and `ai-review` CLI commands.
- Added `text`, `json`, and streaming `jsonl` output and serialized ProgressEvent records.
- Added stable exit codes: 0 success, 1 unexpected failure, 2 arguments/configuration, 3 safely deferred network/rate condition, and 130 interruption.
- Ctrl+C uses the same stop event as the GUI so resumable work is preserved.
- Read-only commands use SQLite query-only mode.
- Release packages now contain a separate `ArchiveScoutCLI` executable alongside the GUI.
- Added `AGENTS.md`, `CLAUDE.md`, `docs/AUTOMATION.md`, and a noninteractive example project.

## AI providers and secrets

- Added provider-neutral AI request/service interfaces with dedicated OpenAI Responses and OpenRouter chat-completions adapters.
- Added ignored `.env` developer support through `python-dotenv`; real environment variables retain precedence.
- Added `.env.example`. API keys are never persisted in project/database/report state and are never printed.

## Compatibility

- Database schema is version 7 with automatic safety-backed migration from schema 6.
- Archive Scout 1.0.0/1.0.1 project databases remain supported.
- Existing AI relevance, external embedded media, scanning, review, reports, recovery, analysis, diagnostics, and merge features remain available.
