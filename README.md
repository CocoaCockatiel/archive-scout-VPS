# Archive Scout

## Run continuously on a VPS with Discord

This fork includes a locked-down Discord slash-command bot and Docker deployment. It can create,
run, resume, stop, and inspect Archive Scout projects while keeping SQLite databases, captures, and
reports in a persistent VPS directory.

See [VPS and Discord deployment](docs/VPS_DISCORD.md) for the complete setup. The short version is:

```bash
cp .env.example .env
# Add your Discord bot token, server ID, and allowed operator IDs to .env.
docker compose up -d --build
```

The bot registers `/scout` commands and the `restart: unless-stopped` policy keeps it running after
crashes and normal VPS reboots.

Archive Scout is a cross-platform desktop research workspace for indexing, downloading, searching, reviewing, reconstructing, and analyzing public captures from the Internet Archive's Wayback Machine.

The official release keeps the established project-based workflow while adding AI-assisted relevance review, a substantially expanded external embedded-media pipeline, clearer site-specific Wayback diagnostics, and further large-project performance work.

## Downloads

- [Download for Windows x64](https://github.com/DearStrike4940/archive-scout/releases/download/v1.0.0/ArchiveScout-Windows-x64.zip)
- [Download for Linux x64](https://github.com/DearStrike4940/archive-scout/releases/download/v1.0.0/ArchiveScout-Linux-x64.zip)
- [Download for macOS Intel and Apple Silicon](https://github.com/DearStrike4940/archive-scout/releases/download/v1.0.0/ArchiveScout-macOS-Universal.zip)

## Core workflow

A typical research project follows this sequence:

1. Add one or more sites, URL prefixes, or exact URLs.
2. Set the archive date range and optional CDX parameters.
3. Define one or more keyword sets.
4. Index archived captures from Wayback.
5. Download textual captures with bounded, rate-limited workers.
6. Parse and scan downloaded pages locally.
7. Review, search, filter, tag, and export matching pages.
8. Optionally ask the AI relevance reviewer to rank report matches for a natural-language research goal.
9. Optionally discover, resolve, and download archived images and videos embedded by the scanned pages.
10. Use recovery, comparison, forum reconstruction, provenance, diagnostics, and project-management tools as needed.

Archive Scout stores project state in SQLite so long jobs can be stopped and resumed without starting over.

## AI relevance review

The AI relevance page is an optional second-stage research tool. It does not replace keyword matching or alter Archive Scout's deterministic scores.

After a scan has produced a report, enter a natural-language description of what you are trying to find. Archive Scout:

- selects a bounded set of existing report matches;
- gives prompt-relevant full-text candidates first consideration and fills the remaining candidate budget from the normal Archive Scout ranking;
- sends compact page evidence rather than complete project archives;
- asks the OpenAI Responses API for a structured relevance score, confidence value, category, short reason, and evidence summary;
- stores the AI ranking separately from the original match and review records;
- generates CSV, JSON, and Markdown AI relevance reports.

The default model is `gpt-5-mini`. The model name, candidate count, batching, excerpt size, and minimum displayed relevance can be adjusted in the interface.

### API key and privacy

Archive Scout does not bundle an API key. Enter your own OpenAI API key in the AI relevance page or provide `OPENAI_API_KEY` in the launch environment. A key typed into the application is session-only and is not written to `project.json` or application settings.

AI review is opt-in. Normal indexing, downloading, scanning, reports, and media workflows do not require OpenAI. When AI review is run, the research prompt and selected page excerpts are sent to the OpenAI API. Archive Scout requests non-stored Responses and instructs the model to treat archived page content as untrusted source material rather than instructions.

## External embedded media

The dedicated operation **Index, download, scan, then download external embedded media** preserves the established sequence while making the media stage much more comprehensive and resumable:

1. The specified site is indexed.
2. Textual captures are downloaded and parsed.
3. Keyword scanning and normal reports finish first.
4. Archive Scout discovers media references from the downloaded pages.
5. External candidates are placed in a persistent discovery queue.
6. Exact Wayback lookups resolve archived captures for those media URLs.
7. Resolved media captures are downloaded directly to disk using bounded workers.

Discovery covers standard and legacy page structures including `img`, lazy-image attributes, `srcset`, `video`, `source`, posters, `object`, `embed`, legacy Flash/player configuration, CSS `url(...)`, social-preview image/video metadata, preload hints, background attributes, direct media links, and extensionless image/video endpoints identified by HTML context. Wayback replay URLs embedded inside archived HTML are unwrapped to their original URLs before exact lookup.

The discovery queue is persistent and keyed to document content, so unchanged pages are not repeatedly reparsed. Exact media lookups use bounded parallelism while retaining Archive Scout's shared request-start limiter. Known Wayback-excluded or robots-blocked hosts are short-circuited so thousands of media references from the same unavailable host do not generate thousands of pointless requests.

Media downloads are streamed directly to disk with incremental hashing and bounded validation previews. Known file sizes are scheduled smallest-first to improve visible progress and reduce long-tail stalls.

## Site-specific Wayback issues

Archive Scout distinguishes archive-policy and site-specific failures from ordinary transient network errors. The Errors page contains a dedicated **Site-specific Wayback issues** table and records repeated occurrences by host and workflow stage.

Examples include:

- material explicitly excluded from Wayback;
- archived replays blocked by robots.txt restrictions;
- unavailable captures;
- invalid replay redirects;
- access-restricted CDX requests;
- archived origin/server-unavailable pages;
- rate limits, timeouts, connection problems, TLS failures, and Wayback service errors.

Confirmed exclusion and robots restrictions are treated as host-level circuit conditions where appropriate, allowing Archive Scout to preserve useful work and continue other targets instead of repeatedly retrying the same unavailable host.

## Search and review

Archive Scout supports:

- multiple independent keyword sets;
- literal, required, excluded, exact, regex, whole-word, field-specific, weighted, and proximity-aware rules;
- a compiled Aho-Corasick literal prefilter for large rule sets;
- SQLite FTS search over downloaded documents;
- persistent scan history;
- review statuses, notes, and tags;
- local and Wayback opening from results;
- CSV, JSON, Markdown, and review-package exports;
- scan comparison and score-change reports.

AI relevance results remain linked to the same underlying match records, so human review and deterministic evidence remain authoritative.

## Archive analysis

The analysis workspace includes:

- generic and profile-aware forum reconstruction;
- legacy embedded-player extraction;
- custom identifier extraction;
- duplicate and near-duplicate analysis;
- snapshot differences;
- provenance and mirror relationships;
- first-appearance timelines;
- controlled external asset lookup;
- project merging with path-containment checks and automatic safety backup.

## Performance and resilience

The execution engine is designed around bounded work rather than project-sized in-memory lists. Important behaviors include:

- persistent SQLite work queues;
- WAL mode and tuned project connections;
- keyset pagination for large local tables;
- bulk capture and queue writes;
- resumable CDX pages and resume keys;
- fixed shared request-start pacing with bounded overlap;
- endpoint/backend recovery and date-window subdivision for transient CDX failures;
- bounded local parallel rescanning;
- stored-parse reuse for unchanged documents;
- no-op database writes when CDX/document/match data is unchanged;
- size-aware text and media scheduling;
- direct-to-disk media streaming;
- bounded GUI progress queues;
- atomic report and export replacement.

The offline benchmark runner can exercise large CDX parsing, database insertion, result pagination, keyword matching, and no-op repeated indexing without contacting the Internet Archive.

## Project safety and recovery

Projects are self-contained folders. Archive Scout can:

- automatically back up a project before schema migration and high-risk operations;
- resume interrupted index/download queues;
- retry selected error categories or selected capture IDs;
- check missing/orphaned files;
- repair project indexes and derived state;
- export privacy-reduced diagnostic packages;
- merge another Archive Scout project while preventing source paths or symlinks from escaping the selected project root.

Existing supported project databases are upgraded in place to the current schema after a safety backup.

## Installation

### Windows

Download `ArchiveScout-Windows-x64.zip`, verify its checksum, extract it, and run `ArchiveScout.exe`. Tagged official releases are intended to use the repository's configured Windows Artifact Signing workflow.

### macOS

Download `ArchiveScout-macOS-Universal.zip`, extract it completely, move `Archive Scout.app` to Applications, and open it. The packaging script preserves symlinks, verifies the frozen runtime, performs a startup probe, and validates the packaged application before publication.

### Linux

Download `ArchiveScout-Linux-x64.tar.gz`, extract it, and run the included application or install it with the provided user-local installer.

## Source development

Archive Scout requires Python 3.11 or newer.

Install the package and run the test suite with the standard Python packaging workflow for your development environment. The repository's Tests workflow exercises Linux, Windows, Intel macOS, and Apple Silicon macOS on Python 3.11 and 3.12.

See the `docs` directory for architecture, AI review, external media, network recovery, migration, development, and release guidance.

## Responsible use

Archive Scout is intended for research involving publicly archived material. Respect applicable law, archive access restrictions, site policies, personal privacy, and the context of sensitive historical material. The software deliberately uses bounded request pacing and records exclusions rather than attempting to bypass Wayback restrictions.

## License

MIT. See `LICENSE`.
