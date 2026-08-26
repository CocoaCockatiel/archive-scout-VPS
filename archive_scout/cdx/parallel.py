from __future__ import annotations

import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Callable, Iterable, Iterator

from ..events import Stopped
from .client import CDXRow, HttpClient, request_cdx_rows


@dataclass(slots=True)
class PageFetchResult:
    page: int
    rows: list[CDXRow]
    elapsed: float
    error: BaseException | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None


def effective_page_workers(requested_workers: int, page_blocks: int) -> int:
    """Bound concurrent page bodies while favoring fewer, server-sized pages.

    ``page_blocks == 0`` in the explicit paged compatibility strategy means
    pageSize is omitted and Internet Archive chooses its normal page grouping.
    Those bodies can be much larger than old fixed-block pages, so three
    concurrent requests are enough to hide latency without multiplying memory
    use. Explicit smaller page sizes may still use more workers.
    """
    requested = max(1, int(requested_workers))
    blocks = int(page_blocks)
    if blocks <= 0:
        return min(requested, 3)
    memory_cap = max(2, 48 // max(1, blocks))
    return min(requested, memory_cap)


def iter_cdx_pages(
    client: HttpClient,
    endpoints: Iterable[str],
    pages: list[int],
    params_for_page: Callable[[int], list[tuple[str, str]]],
    stop_event: threading.Event,
    workers: int,
    max_bytes: int = 64 * 1024 * 1024,
) -> Iterator[PageFetchResult]:
    """Yield independent CDX pages as soon as each page completes.

    Older builds waited for every page in a batch and retained all parsed page
    dictionaries until the slowest sibling finished. Yielding completed compact
    pages lets the indexer write and release each result immediately.
    """
    if not pages:
        return
    worker_count = min(max(1, int(workers)), len(pages))
    endpoint_tuple = tuple(endpoints)

    def fetch(page: int) -> PageFetchResult:
        if stop_event.is_set():
            raise Stopped
        started = time.monotonic()
        try:
            result = request_cdx_rows(
                client,
                endpoint_tuple,
                params_for_page(page),
                max_bytes=max_bytes,
                prefer_text=True,
            )
            return PageFetchResult(page, result.rows, time.monotonic() - started)
        except Stopped:
            raise
        except Exception as exc:
            return PageFetchResult(page, [], time.monotonic() - started, exc)

    executor = ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="archive-scout-cdx")
    pending: dict[Future[PageFetchResult], int] = {}
    try:
        for page in pages:
            future = executor.submit(fetch, int(page))
            pending[future] = int(page)
        while pending:
            if stop_event.is_set():
                raise Stopped
            done, _ = wait(tuple(pending), timeout=0.25, return_when=FIRST_COMPLETED)
            if not done:
                continue
            for future in done:
                pending.pop(future, None)
                yield future.result()
    except Exception:
        for future in pending:
            future.cancel()
        raise
    finally:
        executor.shutdown(wait=True, cancel_futures=True)


def fetch_cdx_pages(
    client: HttpClient,
    endpoints: Iterable[str],
    pages: list[int],
    params_for_page: Callable[[int], list[tuple[str, str]]],
    stop_event: threading.Event,
    workers: int,
    max_bytes: int = 64 * 1024 * 1024,
) -> list[PageFetchResult]:
    """Compatibility wrapper returning deterministic page order."""
    results = list(
        iter_cdx_pages(
            client,
            endpoints,
            pages,
            params_for_page,
            stop_event,
            workers,
            max_bytes=max_bytes,
        )
    )
    results.sort(key=lambda item: item.page)
    return results
