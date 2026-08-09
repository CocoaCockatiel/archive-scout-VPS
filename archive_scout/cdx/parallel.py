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
    """Keep enough requests in flight without multiplying huge page buffers.

    A CDX pageSize block is roughly a few thousand records. Archive Scout can
    still use ten workers for small pages, but large nine-block pages are capped
    at four simultaneous parsed results. The shared rate limiter is unchanged;
    this cap protects memory without reducing request-start speed for the slow,
    large responses that need concurrency most.
    """
    requested = max(1, int(requested_workers))
    blocks = max(1, int(page_blocks))
    # Four nine-block pages are enough to keep the fixed 0.75-second
    # request-start limiter saturated for responses taking up to three seconds,
    # while avoiding six simultaneous ~54k-row buffers on lower-memory systems.
    memory_cap = max(2, 36 // blocks)
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
