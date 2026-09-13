"""Coordination primitives for PortalXS work running in one app process."""

from __future__ import annotations

from contextlib import contextmanager
import logging
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

PORTALXS_BULK_OPERATIONS = frozenset({
    'mileage-auto-sync',
    'activity-auto-sync',
    'fleet-score-snapshot',
})

_locks: dict[int, threading.Lock] = {}
_holders: dict[int, str] = {}
_locks_guard = threading.Lock()


def _lock_for(account_id: int) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(int(account_id), threading.Lock())


def current_portalxs_operation(account_id: int) -> Optional[str]:
    """Operation currently holding the account lock, if any."""
    with _locks_guard:
        return _holders.get(int(account_id))


def is_portalxs_bulk_operation(operation: Optional[str]) -> bool:
    return operation in PORTALXS_BULK_OPERATIONS


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
    key = int(account_id)
    lock = _lock_for(key)
    acquired = lock.acquire(blocking=wait)
    if not acquired:
        logger.debug(
            'PortalXS work skipped account=%s operation=%s (another job active)',
            account_id,
            operation,
        )
        yield False
        return

    with _locks_guard:
        _holders[key] = operation
    started = time.monotonic()
    logger.info('PortalXS work started account=%s operation=%s', account_id, operation)
    try:
        yield True
    finally:
        elapsed = time.monotonic() - started
        with _locks_guard:
            if _holders.get(key) == operation:
                _holders.pop(key, None)
        lock.release()
        logger.info(
            'PortalXS work finished account=%s operation=%s elapsed=%.1fs',
            account_id,
            operation,
            elapsed,
        )
