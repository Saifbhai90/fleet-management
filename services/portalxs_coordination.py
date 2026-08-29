"""Coordination primitives for PortalXS work running in one app process."""

from __future__ import annotations

from contextlib import contextmanager
import logging
import threading
import time

logger = logging.getLogger(__name__)

_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(account_id: int) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(int(account_id), threading.Lock())


@contextmanager
def portalxs_work(
    account_id: int,
    operation: str,
    *,
    wait: bool = False,
):
    """Acquire an account-scoped PortalXS slot.

    Scheduled jobs use ``wait=True`` so jobs from separate schedulers run one
    after another. Live polling uses the default non-blocking mode and serves
    the cache instead of adding another upstream request while a bulk sync is
    active.
    """
    lock = _lock_for(account_id)
    acquired = lock.acquire(blocking=wait)
    if not acquired:
        logger.debug(
            'PortalXS work skipped account=%s operation=%s (another job active)',
            account_id,
            operation,
        )
        yield False
        return

    started = time.monotonic()
    logger.info('PortalXS work started account=%s operation=%s', account_id, operation)
    try:
        yield True
    finally:
        elapsed = time.monotonic() - started
        lock.release()
        logger.info(
            'PortalXS work finished account=%s operation=%s elapsed=%.1fs',
            account_id,
            operation,
            elapsed,
        )
