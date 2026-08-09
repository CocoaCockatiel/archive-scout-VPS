from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path

from .constants import DEFAULT_IMAGE_EXTENSIONS, DEFAULT_VIDEO_EXTENSIONS, VERSION
from .scanning.keywords import keyword_rules_to_lines, parse_keyword_rules
from .utils import atomic_write_text, normalize_cdx_date, normalize_target, parse_cdx_parameter_lines


def normalize_extension(value: str) -> str:
    value = value.strip().casefold()
    if not value:
        return ""
    return value if value.startswith(".") else "." + value


@dataclass(slots=True)
class KeywordSetConfig:
    name: str
    rules: list[str] = field(default_factory=list)
    selected: bool = True

    def normalized(self) -> "KeywordSetConfig":
        name = self.name.strip() or "Keyword set"
        normalized_rules = keyword_rules_to_lines(parse_keyword_rules(self.rules))
        return KeywordSetConfig(name=name, rules=normalized_rules, selected=bool(self.selected))

    def to_payload(self) -> dict:
        return asdict(self.normalized())


@dataclass(slots=True)
class MediaConfig:
    enabled: bool = False
    targets: list[str] = field(default_factory=list)
    include_images: bool = True
    include_videos: bool = True
    include_extensions: list[str] = field(
        default_factory=lambda: list(DEFAULT_IMAGE_EXTENSIONS) + list(DEFAULT_VIDEO_EXTENSIONS)
    )
    exclude_extensions: list[str] = field(default_factory=list)
    discover_embedded: bool = True
    allow_external_embeds: bool = False
    snapshot_strategy: str = "earliest"
    max_file_mb: float = 500.0
    preserve_paths: bool = True

    def normalized(self) -> "MediaConfig":
        targets = list(dict.fromkeys(normalize_target(value) for value in self.targets if value.strip()))
        include = [normalize_extension(value) for value in self.include_extensions]
        exclude = [normalize_extension(value) for value in self.exclude_extensions]
        include = list(dict.fromkeys(value for value in include if value))
        exclude = list(dict.fromkeys(value for value in exclude if value))
        strategy = self.snapshot_strategy.strip().casefold()
        if strategy not in {"earliest", "latest", "all"}:
            raise ValueError("media snapshot strategy must be earliest, latest, or all")
        return MediaConfig(
            enabled=bool(self.enabled),
            targets=targets,
            include_images=bool(self.include_images),
            include_videos=bool(self.include_videos),
            include_extensions=include,
            exclude_extensions=exclude,
            discover_embedded=bool(self.discover_embedded),
            allow_external_embeds=bool(self.allow_external_embeds),
            snapshot_strategy=strategy,
            max_file_mb=max(0.1, float(self.max_file_mb)),
            preserve_paths=bool(self.preserve_paths),
        )

    @property
    def max_file_bytes(self) -> int:
        return int(self.max_file_mb * 1024 * 1024)

    def to_payload(self) -> dict:
        return asdict(self.normalized())


@dataclass(slots=True)
class AnalysisConfig:
    forum_profile: str = "auto"
    reconstruct_threads: bool = True
    extract_legacy_embeds: bool = True
    extractor_rules: list[str] = field(default_factory=list)
    search_external_assets: bool = False
    external_domains: list[str] = field(default_factory=list)
    external_asset_limit: int = 5000
    duplicate_threshold: float = 0.90
    compare_snapshots: bool = True
    build_provenance: bool = True
    merge_source: str = ""

    def normalized(self) -> "AnalysisConfig":
        profile = self.forum_profile.strip().casefold() or "auto"
        if profile not in {"auto", "generic", "vbulletin", "phpbb", "invision", "futaba", "2channel"}:
            raise ValueError("unsupported forum profile")
        domains = []
        for value in self.external_domains:
            value = value.strip().casefold()
            if value.startswith("http://") or value.startswith("https://"):
                from urllib.parse import urlsplit
                value = urlsplit(value).hostname or ""
            value = value.strip("./")
            if value and value not in domains:
                domains.append(value)
        rules = [value.strip() for value in self.extractor_rules if value.strip()]
        return AnalysisConfig(
            forum_profile=profile,
            reconstruct_threads=bool(self.reconstruct_threads),
            extract_legacy_embeds=bool(self.extract_legacy_embeds),
            extractor_rules=rules,
            search_external_assets=bool(self.search_external_assets),
            external_domains=domains,
            external_asset_limit=min(100000, max(1, int(self.external_asset_limit))),
            duplicate_threshold=min(1.0, max(0.5, float(self.duplicate_threshold))),
            compare_snapshots=bool(self.compare_snapshots),
            build_provenance=bool(self.build_provenance),
            merge_source=str(self.merge_source).strip(),
        )

    def to_payload(self) -> dict:
        return asdict(self.normalized())


@dataclass(slots=True)
class AIConfig:
    provider: str = "openai"
    model: str = "gpt-5-mini"
    candidate_limit: int = 200
    batch_size: int = 8
    minimum_relevance: int = 50
    excerpt_chars: int = 5000
    request_timeout: float = 120.0

    def normalized(self) -> "AIConfig":
        provider = self.provider.strip().casefold() or "openai"
        if provider != "openai":
            raise ValueError("AI provider must be openai")
        model = self.model.strip() or "gpt-5-mini"
        return AIConfig(
            provider=provider,
            model=model,
            candidate_limit=min(2000, max(10, int(self.candidate_limit))),
            batch_size=min(20, max(1, int(self.batch_size))),
            minimum_relevance=min(100, max(0, int(self.minimum_relevance))),
            excerpt_chars=min(12000, max(1000, int(self.excerpt_chars))),
            request_timeout=min(600.0, max(15.0, float(self.request_timeout))),
        )

    def to_payload(self) -> dict:
        return asdict(self.normalized())


@dataclass(slots=True)
class NetworkConfig:
    backend: str = "auto"
    trust_environment: bool = True
    endpoint_mode: str = "auto"
    index_strategy: str = "auto"
    page_blocks: int = 9
    cdx_workers: int = 10
    persistent_retries: bool = True
    retry_base_seconds: float = 5.0
    retry_max_seconds: float = 300.0
    failure_pause_threshold: int = 8
    connection_failure_pause_threshold: int = 3
    connection_retry_seconds: float = 3.0
    diagnostics: bool = True

    def normalized(self) -> "NetworkConfig":
        backend = self.backend.strip().casefold() or "auto"
        if backend not in {"auto", "httpx", "urllib3", "curl"}:
            raise ValueError("network backend must be auto, httpx, urllib3, or curl")
        endpoint = self.endpoint_mode.strip().casefold() or "auto"
        if endpoint not in {"auto", "cdx", "timemap"}:
            raise ValueError("CDX endpoint mode must be auto, cdx, or timemap")
        strategy = self.index_strategy.strip().casefold() or "auto"
        if strategy not in {"auto", "paged", "resume"}:
            raise ValueError("CDX index strategy must be auto, paged, or resume")
        return NetworkConfig(
            backend=backend,
            trust_environment=bool(self.trust_environment),
            endpoint_mode=endpoint,
            index_strategy=strategy,
            page_blocks=min(50, max(1, int(self.page_blocks))),
            cdx_workers=min(12, max(1, int(self.cdx_workers))),
            persistent_retries=bool(self.persistent_retries),
            retry_base_seconds=max(1.0, float(self.retry_base_seconds)),
            retry_max_seconds=max(float(self.retry_base_seconds), float(self.retry_max_seconds)),
            failure_pause_threshold=min(100, max(2, int(self.failure_pause_threshold))),
            connection_failure_pause_threshold=min(10, max(2, int(self.connection_failure_pause_threshold))),
            connection_retry_seconds=min(30.0, max(1.0, float(self.connection_retry_seconds))),
            diagnostics=bool(self.diagnostics),
        )

    def to_payload(self) -> dict:
        return asdict(self.normalized())


@dataclass(slots=True)
class ProjectConfig:
    output_dir: Path
    targets: list[str]
    keywords: list[str]
    keyword_set_name: str = "Current keywords"
    keyword_sets: list[KeywordSetConfig | dict] = field(default_factory=list)
    from_year: int = 2000
    to_year: int = datetime.now().year
    from_date: str = ""
    to_date: str = ""
    cdx_filters: list[str] = field(default_factory=lambda: ["statuscode:200"])
    cdx_collapses: list[str] = field(default_factory=lambda: ["urlkey"])
    cdx_match_type: str = ""
    cdx_extra_params: list[str] = field(default_factory=list)
    workers: int = 4
    download_scope: str = "all_text"
    minimum_score: int = 1
    max_file_mb: float = 25.0
    page_size: int = 50000
    cdx_delay: float = 0.75
    download_delay: float = 0.5
    retries: int = 4
    rate_limit_base_pause: float = 30.0
    rate_limit_max_pause: float = 300.0
    rate_limit_max_wait: float = 0.0
    rate_limit_attempts: int = 0
    connect_timeout: float = 30.0
    read_timeout: float = 180.0
    max_attempts: int = 4
    user_agent: str = "ArchiveScout/1.0 public web archive research client"
    retry_error_categories: list[str] = field(default_factory=list)
    retry_capture_ids: list[int] = field(default_factory=list)
    retry_media_capture_ids: list[int] = field(default_factory=list)
    media: MediaConfig | dict = field(default_factory=MediaConfig)
    analysis: AnalysisConfig | dict = field(default_factory=AnalysisConfig)
    ai: AIConfig | dict = field(default_factory=AIConfig)
    network: NetworkConfig | dict = field(default_factory=NetworkConfig)
    target_settings: dict[str, dict] = field(default_factory=dict)
    auto_backup: bool = True
    backup_keep: int = 5
    import_source: str = ""

    def normalized_keyword_sets(self) -> list[KeywordSetConfig]:
        sets: list[KeywordSetConfig] = []
        for value in self.keyword_sets:
            if isinstance(value, KeywordSetConfig):
                item = value
            elif isinstance(value, dict):
                item = KeywordSetConfig(
                    name=str(value.get("name") or "Keyword set"),
                    rules=list(value.get("rules") or value.get("keywords") or []),
                    selected=bool(value.get("selected", True)),
                )
            else:
                continue
            item = item.normalized()
            if item.rules:
                sets.append(item)
        if not sets and self.keywords:
            sets.append(KeywordSetConfig(self.keyword_set_name, list(self.keywords), True).normalized())
        unique: dict[str, KeywordSetConfig] = {}
        for item in sets:
            base = item.name
            name = base
            suffix = 2
            while name.casefold() in unique:
                name = f"{base} {suffix}"
                suffix += 1
            if name != item.name:
                item = KeywordSetConfig(name, item.rules, item.selected)
            unique[name.casefold()] = item
        return list(unique.values())

    def selected_keyword_sets(self) -> list[KeywordSetConfig]:
        return [item for item in self.normalized_keyword_sets() if item.selected]

    def normalized(self) -> "ProjectConfig":
        targets = list(dict.fromkeys(normalize_target(value) for value in self.targets if value.strip()))
        keyword_sets = self.normalized_keyword_sets()
        first = keyword_sets[0] if keyword_sets else KeywordSetConfig(self.keyword_set_name, [], True)
        output_dir = Path(self.output_dir).expanduser().resolve()
        from_date = normalize_cdx_date(self.from_date or str(self.from_year), end=False)
        to_date = normalize_cdx_date(self.to_date or str(self.to_year), end=True)
        filters = list(dict.fromkeys(value.strip() for value in self.cdx_filters if value.strip()))
        collapses = list(dict.fromkeys(value.strip() for value in self.cdx_collapses if value.strip()))
        match_type = self.cdx_match_type.strip()
        if match_type not in {"", "exact", "prefix", "host", "domain"}:
            raise ValueError("matchType must be exact, prefix, host, domain, or blank")
        extra_params = [f"{key}={value}" for key, value in parse_cdx_parameter_lines(self.cdx_extra_params)]
        media = self.media if isinstance(self.media, MediaConfig) else MediaConfig(**self.media)
        media = media.normalized()
        analysis = self.analysis if isinstance(self.analysis, AnalysisConfig) else AnalysisConfig(**self.analysis)
        analysis = analysis.normalized()
        ai = self.ai if isinstance(self.ai, AIConfig) else AIConfig(**self.ai)
        ai = ai.normalized()
        network = self.network if isinstance(self.network, NetworkConfig) else NetworkConfig(**self.network)
        network = network.normalized()
        target_settings: dict[str, dict] = {}
        for raw_target, raw_settings in (self.target_settings or {}).items():
            target = normalize_target(str(raw_target))
            if not target or not isinstance(raw_settings, dict):
                continue
            cleaned = {str(key): value for key, value in raw_settings.items() if value not in (None, "", [], {})}
            if cleaned:
                target_settings[target] = cleaned
        return ProjectConfig(
            output_dir=output_dir,
            targets=targets,
            keywords=list(first.rules),
            keyword_set_name=first.name,
            keyword_sets=keyword_sets,
            from_year=int(from_date[:4]),
            to_year=int(to_date[:4]),
            from_date=from_date,
            to_date=to_date,
            cdx_filters=filters,
            cdx_collapses=collapses,
            cdx_match_type=match_type,
            cdx_extra_params=extra_params,
            workers=min(32, max(1, int(self.workers))),
            download_scope=self.download_scope if self.download_scope in {"all_text", "keyword_urls", "index_only"} else "all_text",
            minimum_score=max(1, int(self.minimum_score)),
            max_file_mb=max(0.1, float(self.max_file_mb)),
            page_size=min(50000, max(100, int(self.page_size))),
            cdx_delay=max(0.0, float(self.cdx_delay)),
            download_delay=max(0.0, float(self.download_delay)),
            retries=min(12, max(1, int(self.retries))),
            rate_limit_base_pause=max(1.0, float(self.rate_limit_base_pause)),
            rate_limit_max_pause=max(float(self.rate_limit_base_pause), float(self.rate_limit_max_pause)),
            rate_limit_max_wait=max(0.0, float(self.rate_limit_max_wait)),
            rate_limit_attempts=min(1000, max(0, int(self.rate_limit_attempts))),
            connect_timeout=max(1.0, float(self.connect_timeout)),
            read_timeout=max(1.0, float(self.read_timeout)),
            max_attempts=min(20, max(1, int(self.max_attempts))),
            user_agent=self.user_agent.strip() or "ArchiveScout/1.0 public web archive research client",
            retry_error_categories=list(dict.fromkeys(value.strip() for value in self.retry_error_categories if value.strip())),
            retry_capture_ids=sorted({int(value) for value in self.retry_capture_ids if int(value) > 0}),
            retry_media_capture_ids=sorted({int(value) for value in self.retry_media_capture_ids if int(value) > 0}),
            media=media,
            analysis=analysis,
            ai=ai,
            network=network,
            target_settings=target_settings,
            auto_backup=bool(self.auto_backup),
            backup_keep=min(50, max(1, int(self.backup_keep))),
            import_source=str(self.import_source).strip(),
        )

    def settings_for_target(self, target: str) -> dict:
        normalized = normalize_target(target)
        return dict(self.target_settings.get(normalized) or {})

    def for_target(self, target: str) -> "ProjectConfig":
        settings = self.settings_for_target(target)
        allowed = {
            "from_date", "to_date", "cdx_filters", "cdx_collapses", "cdx_match_type",
            "cdx_extra_params", "page_size", "cdx_delay", "download_delay", "workers",
        }
        overrides = {key: value for key, value in settings.items() if key in allowed}
        return replace(self, targets=[normalize_target(target)], **overrides).normalized()

    @property
    def max_file_bytes(self) -> int:
        return int(self.max_file_mb * 1024 * 1024)

    def to_payload(self) -> dict:
        config = self.normalized()
        payload = asdict(config)
        payload["output_dir"] = str(config.output_dir)
        payload["keyword_sets"] = [item.to_payload() for item in config.normalized_keyword_sets()]
        payload["media"] = config.media.to_payload() if isinstance(config.media, MediaConfig) else dict(config.media)
        payload["analysis"] = config.analysis.to_payload() if isinstance(config.analysis, AnalysisConfig) else dict(config.analysis)
        payload["ai"] = config.ai.to_payload() if isinstance(config.ai, AIConfig) else dict(config.ai)
        payload["network"] = config.network.to_payload() if isinstance(config.network, NetworkConfig) else dict(config.network)
        payload["version"] = VERSION
        return payload


def save_project_config(config: ProjectConfig) -> Path:
    config = config.normalized()
    path = config.output_dir / "project.json"
    atomic_write_text(path, json.dumps(config.to_payload(), indent=2, ensure_ascii=False) + "\n")
    return path


def load_project_config(path: Path) -> ProjectConfig:
    payload = json.loads(path.read_text(encoding="utf-8"))
    keyword_sets = list(payload.get("keyword_sets") or [])
    media_payload = payload.get("media") or {}
    analysis_payload = payload.get("analysis") or {}
    ai_payload = payload.get("ai") or {}
    network_payload = payload.get("network") or {}
    loaded_page_size = int(payload.get("page_size", 50000))
    loaded_cdx_delay = float(payload.get("cdx_delay", 0.75))
    loaded_page_blocks = int(network_payload.get("page_blocks", 9))
    loaded_cdx_workers = int(network_payload.get("cdx_workers", 10))

    # Preserve compatibility with early prerelease projects without exposing old
    # product branding. Only untouched historical default combinations are
    # upgraded; user-customized transport settings remain exactly as saved.
    if loaded_page_size == 5000 and loaded_cdx_delay == 1.0 and loaded_page_blocks == 1:
        loaded_page_size = 25000
        loaded_cdx_delay = 0.75
        loaded_page_blocks = 6
        if "cdx_workers" not in network_payload:
            loaded_cdx_workers = 6
    untouched_legacy_defaults = (
        loaded_page_size == 25000
        and loaded_cdx_delay == 0.75
        and loaded_page_blocks == 6
        and loaded_cdx_workers == 6
    )
    if untouched_legacy_defaults:
        loaded_page_size = 50000
        loaded_page_blocks = 9
        loaded_cdx_workers = 10
    return ProjectConfig(
        output_dir=Path(payload.get("output_dir") or path.parent),
        targets=list(payload.get("targets") or []),
        keywords=list(payload.get("keywords") or []),
        keyword_set_name=str(payload.get("keyword_set_name") or "Current keywords"),
        keyword_sets=keyword_sets,
        from_year=int(payload.get("from_year", 2000)),
        to_year=int(payload.get("to_year", datetime.now().year)),
        from_date=str(payload.get("from_date") or payload.get("from_year", 2000)),
        to_date=str(payload.get("to_date") or payload.get("to_year", datetime.now().year)),
        cdx_filters=list(payload["cdx_filters"]) if "cdx_filters" in payload else ["statuscode:200"],
        cdx_collapses=list(payload["cdx_collapses"]) if "cdx_collapses" in payload else ["urlkey"],
        cdx_match_type=str(payload.get("cdx_match_type", "")),
        cdx_extra_params=list(payload.get("cdx_extra_params") or []),
        workers=int(payload.get("workers", 4)),
        download_scope=str(payload.get("download_scope", "all_text")),
        minimum_score=int(payload.get("minimum_score", 1)),
        max_file_mb=float(payload.get("max_file_mb", 25.0)),
        page_size=loaded_page_size,
        cdx_delay=loaded_cdx_delay,
        download_delay=float(payload.get("download_delay", 0.5)),
        retries=int(payload.get("retries", 4)),
        rate_limit_base_pause=float(payload.get("rate_limit_base_pause", 30.0)),
        rate_limit_max_pause=float(payload.get("rate_limit_max_pause", 300.0)),
        rate_limit_max_wait=float(payload.get("rate_limit_max_wait", 0.0)),
        rate_limit_attempts=int(payload.get("rate_limit_attempts", 0)),
        connect_timeout=float(payload.get("connect_timeout", 30.0)),
        read_timeout=float(payload.get("read_timeout", 180.0)),
        max_attempts=int(payload.get("max_attempts", 4)),
        user_agent=str(payload.get("user_agent", "ArchiveScout/1.0 public web archive research client")),
        retry_error_categories=list(payload.get("retry_error_categories") or []),
        retry_capture_ids=[int(value) for value in payload.get("retry_capture_ids") or []],
        retry_media_capture_ids=[int(value) for value in payload.get("retry_media_capture_ids") or []],
        media=MediaConfig(
            enabled=bool(media_payload.get("enabled", False)),
            targets=list(media_payload.get("targets") or []),
            include_images=bool(media_payload.get("include_images", True)),
            include_videos=bool(media_payload.get("include_videos", True)),
            include_extensions=list(media_payload.get("include_extensions") or list(DEFAULT_IMAGE_EXTENSIONS) + list(DEFAULT_VIDEO_EXTENSIONS)),
            exclude_extensions=list(media_payload.get("exclude_extensions") or []),
            discover_embedded=bool(media_payload.get("discover_embedded", True)),
            allow_external_embeds=bool(media_payload.get("allow_external_embeds", False)),
            snapshot_strategy=str(media_payload.get("snapshot_strategy", "earliest")),
            max_file_mb=float(media_payload.get("max_file_mb", 500.0)),
            preserve_paths=bool(media_payload.get("preserve_paths", True)),
        ),
        analysis=AnalysisConfig(
            forum_profile=str(analysis_payload.get("forum_profile", "auto")),
            reconstruct_threads=bool(analysis_payload.get("reconstruct_threads", True)),
            extract_legacy_embeds=bool(analysis_payload.get("extract_legacy_embeds", True)),
            extractor_rules=list(analysis_payload.get("extractor_rules") or []),
            search_external_assets=bool(analysis_payload.get("search_external_assets", False)),
            external_domains=list(analysis_payload.get("external_domains") or []),
            external_asset_limit=int(analysis_payload.get("external_asset_limit", 5000)),
            duplicate_threshold=float(analysis_payload.get("duplicate_threshold", 0.90)),
            compare_snapshots=bool(analysis_payload.get("compare_snapshots", True)),
            build_provenance=bool(analysis_payload.get("build_provenance", True)),
            merge_source=str(analysis_payload.get("merge_source", "")),
        ),
        ai=AIConfig(
            provider=str(ai_payload.get("provider", "openai")),
            model=str(ai_payload.get("model", "gpt-5-mini")),
            candidate_limit=int(ai_payload.get("candidate_limit", 200)),
            batch_size=int(ai_payload.get("batch_size", 8)),
            minimum_relevance=int(ai_payload.get("minimum_relevance", 50)),
            excerpt_chars=int(ai_payload.get("excerpt_chars", 5000)),
            request_timeout=float(ai_payload.get("request_timeout", 120.0)),
        ),
        network=NetworkConfig(
            backend=str(network_payload.get("backend", "auto")),
            trust_environment=bool(network_payload.get("trust_environment", True)),
            endpoint_mode=str(network_payload.get("endpoint_mode", "auto")),
            index_strategy=str(network_payload.get("index_strategy", "auto")),
            page_blocks=loaded_page_blocks,
            cdx_workers=loaded_cdx_workers,
            persistent_retries=bool(network_payload.get("persistent_retries", True)),
            retry_base_seconds=float(network_payload.get("retry_base_seconds", 5.0)),
            retry_max_seconds=float(network_payload.get("retry_max_seconds", 300.0)),
            failure_pause_threshold=int(network_payload.get("failure_pause_threshold", 8)),
            connection_failure_pause_threshold=int(network_payload.get("connection_failure_pause_threshold", 3)),
            connection_retry_seconds=float(network_payload.get("connection_retry_seconds", 3.0)),
            diagnostics=bool(network_payload.get("diagnostics", True)),
        ),
        target_settings=dict(payload.get("target_settings") or {}),
        auto_backup=bool(payload.get("auto_backup", True)),
        backup_keep=int(payload.get("backup_keep", 5)),
        import_source=str(payload.get("import_source", "")),
    ).normalized()
