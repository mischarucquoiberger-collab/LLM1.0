"""Concurrency utilities for parallel I/O-bound operations.

Centralises ThreadPoolExecutor usage so every call-site gets consistent
error handling and worker-pool sizing.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def run_concurrent(
    tasks: List[Callable[[], T]],
    max_workers: int = 10,
) -> List[T]:
    """Run *tasks* in parallel and return results **in submission order**.

    Each element of *tasks* must be a zero-argument callable.  Exceptions
    raised inside a task are caught and replaced with ``None`` so that one
    failing task does not prevent the others from completing.
    """
    if not tasks:
        return []

    results: List[T | None] = [None] * len(tasks)

    with ThreadPoolExecutor(max_workers=min(max_workers, len(tasks))) as pool:
        future_to_idx = {pool.submit(fn): idx for idx, fn in enumerate(tasks)}
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                results[idx] = future.result()
            except Exception:
                logger.debug("run_concurrent task %d failed", idx, exc_info=True)
                results[idx] = None

    return results  # type: ignore[return-value]


def run_concurrent_dict(
    tasks: Dict[str, Callable[[], Any]],
    max_workers: int = 10,
) -> Dict[str, Any]:
    """Run *tasks* in parallel and return ``{name: result}``."""
    if not tasks:
        return {}

    results: Dict[str, Any] = {}

    with ThreadPoolExecutor(max_workers=min(max_workers, len(tasks))) as pool:
        future_to_key = {pool.submit(fn): key for key, fn in tasks.items()}
        for future in as_completed(future_to_key):
            key = future_to_key[future]
            try:
                results[key] = future.result()
            except Exception:
                logger.debug("run_concurrent_dict task %r failed", key, exc_info=True)
                results[key] = None

    return results
