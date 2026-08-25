from __future__ import annotations

import hashlib
import json
from datetime import datetime

from ..config import ProjectConfig
from ..utils import parse_cdx_parameter_lines


def cdx_query_signature(config: ProjectConfig, page_size: int | None = None) -> str:
    payload = {
        "from": config.from_date,
        "to": config.to_date,
        "filters": config.cdx_filters,
        "collapses": config.cdx_collapses,
        "match_type": config.cdx_match_type,
        "extra": config.cdx_extra_params,
        "page_size": int(config.page_size if page_size is None else page_size),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]

def cdx_query_signatures(config: ProjectConfig) -> tuple[str, ...]:
    """Return the current signature plus compatible earlier page-size variants.

    Page size affects how the same result set is transported, not its meaning.
    Earlier Archive Scout builds included it in the signature, so the current engine can
    adopt completed work created with the earlier defaults instead of forcing
    an expensive re-index.
    """
    sizes = [config.page_size, 5000, 25000, 1000, 10000, 50000]
    return tuple(dict.fromkeys(cdx_query_signature(config, size) for size in sizes))


def cdx_year_window(config: ProjectConfig, year: int) -> tuple[str, str] | None:
    start = max(config.from_date, f"{year:04d}0101000000")
    end = min(config.to_date, f"{year:04d}1231235959")
    if start > end:
        return None
    return start, end


def cdx_target_value(target: str, match_type: str) -> str:
    if match_type in {"exact", "prefix", "host", "domain"}:
        target = target.rstrip("*")
    if match_type in {"host", "domain"}:
        target = target.rstrip("/")
    return target


def build_cdx_params(
    config: ProjectConfig,
    target: str,
    start: str,
    end: str,
    resume: str | None = None,
    page_size: int | None = None,
) -> list[tuple[str, str]]:
    params = [
        ("url", cdx_target_value(target, config.cdx_match_type)),
        ("from", start),
        ("to", end),
        ("output", "json"),
        ("fl", "timestamp,original,mimetype,statuscode,digest,length"),
    ]
    if config.cdx_match_type:
        params.append(("matchType", config.cdx_match_type))
    params.extend(("filter", value) for value in config.cdx_filters)
    params.extend(("collapse", value) for value in config.cdx_collapses)
    params.extend(parse_cdx_parameter_lines(config.cdx_extra_params))
    params.extend([("limit", str(page_size or config.page_size)), ("showResumeKey", "true")])
    if resume:
        params.append(("resumeKey", resume))
    return params


def parse_cdx(payload: object) -> tuple[list[dict[str, str]], str | None]:
    if payload in (None, []):
        return [], None
    if isinstance(payload, dict):
        message = str(payload.get("message") or payload.get("error") or payload)
        lowered = message.lower()
        if "no capture" in lowered or "no result" in lowered or "not found" in lowered:
            return [], None
        raise RuntimeError(message)
    if not isinstance(payload, list) or not payload:
        return [], None
    header = payload[0]
    if not isinstance(header, list):
        raise RuntimeError("unexpected CDX response header")
    body = payload[1:]
    resume = None
    if len(body) >= 2 and body[-2] == [] and isinstance(body[-1], list) and len(body[-1]) == 1:
        resume = str(body[-1][0])
        body = body[:-2]
    rows: list[dict[str, str]] = []
    for item in body:
        if not item or not isinstance(item, list) or len(item) != len(header):
            continue
        row = dict(zip(header, item))
        if row.get("timestamp") and row.get("original"):
            rows.append(row)
    return rows, resume


def cdx_endpoints(config: ProjectConfig) -> tuple[str, ...]:
    from ..constants import CDX_URL, CDX_TIMEMAP_JSON_URL, CDX_TIMEMAP_URL
    mode = config.network.normalized().endpoint_mode
    if mode == "cdx":
        return (CDX_URL,)
    if mode == "timemap":
        return (CDX_TIMEMAP_URL, CDX_TIMEMAP_JSON_URL)
    return (CDX_URL, CDX_TIMEMAP_URL, CDX_TIMEMAP_JSON_URL)


def is_broad_cdx_query(config: ProjectConfig, target: str) -> bool:
    if config.cdx_match_type in {"prefix", "host", "domain"}:
        return True
    value = target.strip()
    return value.endswith("/*") or value.startswith("*.") or value.endswith("*")


def preferred_index_strategy(config: ProjectConfig, target: str) -> str:
    strategy = config.network.normalized().index_strategy
    if strategy != "auto":
        return strategy
    return "paged" if is_broad_cdx_query(config, target) else "resume"


def build_num_pages_params(
    config: ProjectConfig,
    target: str,
    start: str,
    end: str,
    page_blocks: int | None = None,
) -> list[tuple[str, str]]:
    params = build_cdx_params(config, target, start, end, page_size=config.page_size)
    params = [(key, value) for key, value in params if key not in {"limit", "showResumeKey", "resumeKey"}]
    params.append(("showNumPages", "true"))
    blocks = config.network.normalized().page_blocks if page_blocks is None else int(page_blocks)
    # 0 deliberately means "use Internet Archive's server-selected page size".
    # The server default groups substantially more ZipNum blocks than the old
    # hard-coded pageSize=9, which avoids turning broad sites into thousands of
    # tiny page requests while keeping the official pagination mechanism.
    if blocks > 0:
        params.append(("pageSize", str(blocks)))
    return params


def build_paged_cdx_params(
    config: ProjectConfig,
    target: str,
    start: str,
    end: str,
    page: int,
    page_blocks: int | None = None,
) -> list[tuple[str, str]]:
    params = build_cdx_params(config, target, start, end, page_size=config.page_size)
    params = [(key, value) for key, value in params if key not in {"limit", "showResumeKey", "resumeKey"}]
    params.append(("page", str(max(0, int(page)))))
    blocks = config.network.normalized().page_blocks if page_blocks is None else int(page_blocks)
    if blocks > 0:
        params.append(("pageSize", str(blocks)))
    return params


def parse_num_pages(payload: object) -> int:
    if isinstance(payload, int):
        return max(0, payload)
    if isinstance(payload, str) and payload.strip().isdigit():
        return max(0, int(payload.strip()))
    if isinstance(payload, list):
        candidates = payload
        while isinstance(candidates, list) and len(candidates) == 1:
            candidates = candidates[0]
        if isinstance(candidates, int):
            return max(0, candidates)
        if isinstance(candidates, str) and candidates.strip().isdigit():
            return max(0, int(candidates.strip()))
    if isinstance(payload, dict):
        for key in ("pages", "numPages", "num_pages"):
            value = payload.get(key)
            if str(value).isdigit():
                return max(0, int(value))
    raise RuntimeError(f"unexpected CDX page-count response: {payload!r}")
