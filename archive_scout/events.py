from __future__ import annotations

from dataclasses import dataclass, field


class Stopped(RuntimeError):
    pass


class ConnectivityPaused(RuntimeError):
    """A recoverable network pause with the exact queue safely persisted."""


@dataclass(slots=True)
class ProgressEvent:
    stage: str
    message: str
    current: int | None = None
    total: int | None = None
    detail: dict = field(default_factory=dict)
