from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from ..config import MediaConfig, normalize_extension
from ..constants import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS


MEDIA_SUFFIX_PATTERN = re.compile(r"(?i)(\.[a-z0-9]{1,10})(?=$|[?&#;])")


def extension_from_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
        path = unquote(parsed.path or "")
        suffix = Path(path).suffix.casefold()
        if suffix and re.fullmatch(r"\.[a-z0-9]{1,10}", suffix, re.IGNORECASE):
            return suffix
        # Some archived URLs contain tracking data attached with '&' or ';'
        # directly to the path, so pathlib sees '.jpg&ref=...' as the suffix.
        matches = list(MEDIA_SUFFIX_PATTERN.finditer(path))
        if matches:
            return matches[-1].group(1).casefold()
        # Media can also be passed as a query value, for example file=clip.wmv.
        matches = list(MEDIA_SUFFIX_PATTERN.finditer(unquote(parsed.query)))
        return matches[-1].group(1).casefold() if matches else ""
    except Exception:
        return ""


def media_kind(extension: str, mimetype: str = "") -> str | None:
    extension = normalize_extension(extension)
    mime = (mimetype or "").split(";", 1)[0].casefold()
    if extension in IMAGE_EXTENSIONS or mime.startswith("image/"):
        return "image"
    if extension in VIDEO_EXTENSIONS or mime.startswith("video/") or mime in {
        "application/x-shockwave-flash",
        "application/futuresplash",
        "application/vnd.rn-realmedia",
        "application/x-mplayer2",
    }:
        return "video"
    return None


def selected_extensions(config: MediaConfig) -> list[str]:
    media = config.normalized()
    excluded = set(media.exclude_extensions)
    selected: list[str] = []
    for extension in media.include_extensions:
        kind = media_kind(extension)
        if extension in excluded or kind is None:
            continue
        if kind == "image" and not media.include_images:
            continue
        if kind == "video" and not media.include_videos:
            continue
        selected.append(extension)
    return list(dict.fromkeys(selected))


def allowed_media_url(url: str, config: MediaConfig, mimetype: str = "") -> tuple[bool, str | None, str]:
    extension = extension_from_url(url)
    kind = media_kind(extension, mimetype)
    if not kind:
        return False, None, extension
    selected = set(selected_extensions(config))
    if extension and extension not in selected:
        return False, kind, extension
    if extension in set(config.normalized().exclude_extensions):
        return False, kind, extension
    if kind == "image" and not config.include_images:
        return False, kind, extension
    if kind == "video" and not config.include_videos:
        return False, kind, extension
    return True, kind, extension
