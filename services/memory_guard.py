"""Keep the web process inside its instance memory limit.

The service runs on a 512 MB Render instance and boots at roughly 350 MB, so the
headroom for report rendering and in-process caches is small. When the resident
set crossed the limit Render restarted the instance, which showed up as 502s and
a cold cache for every user.

This watchdog samples RSS on a timer and, once it crosses a threshold, releases
the in-process caches that are safe to rebuild (rendered dashboards, PortalXS
report buckets, notification counts) before the platform has a reason to kill the
process. Everything it drops is a cache, so the only cost of a trim is that the
next request for that data does its own work again.

Thresholds are relative to the instance limit and can be tuned without a code
change:

    MEMORY_GUARD_ENABLED=0        disable the watchdog
    MEMORY_LIMIT_MB=512           instance memory limit
    MEMORY_GUARD_SOFT_PCT=72      trim caches above this share of the limit
    MEMORY_GUARD_HARD_PCT=85      drop every cache and force a full GC
    MEMORY_GUARD_INTERVAL=45      seconds between samples
"""
from __future__ import annotations

import ctypes
import ctypes.util
import gc
import logging
import os
import platform
import threading
import time

try:
    import psutil
except ImportError:  # optional dependency — the guard simply stays off
    psutil = None

logger = logging.getLogger(__name__)

_thread: threading.Thread | None = None
_stop = threading.Event()
_state = {'last_rss_mb': 0.0, 'soft_trims': 0, 'hard_trims': 0, 'peak_rss_mb': 0.0}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except (TypeError, ValueError):
        return default


def _rss_mb() -> float | None:
    if psutil is None:
        return None
    try:
        return psutil.Process().memory_info().rss / 1048576.0
    except Exception:
        return None


# ── Cache registry ───────────────────────────────────────────────────────────
# Each trimmer returns the number of items it released.
#
# The cache owners (`app`, `routes_dashboard`, `portalxs_service`) all import from
# `app`, which imports this module during startup, so importing them at module
# level here would be circular. The imports therefore stay inside the trimmers,
# which also means a module that failed to load cannot take the watchdog with it.

def _trim_dashboard_html(expired_only: bool) -> int:
    from routes_dashboard import _dashboard_cache, _DASHBOARD_CACHE_TTL
    now = time.time()
    keys = list(_dashboard_cache)
    if expired_only:
        keys = [k for k in keys
                if (now - _dashboard_cache[k]['ts']) > _DASHBOARD_CACHE_TTL / 2]
    for key in keys:
        _dashboard_cache.pop(key, None)
    return len(keys)


def _trim_fleet_report(expired_only: bool) -> int:
    from services import portalxs_service as pxs
    with pxs._fleet_report_cache_lock:
        if expired_only:
            before = len(pxs._fleet_report_cache)
            pxs._fleet_cache_prune(time.time())
            return before - len(pxs._fleet_report_cache)
        count = len(pxs._fleet_report_cache)
        pxs._fleet_report_cache.clear()
        return count


def _trim_mileage_report(expired_only: bool) -> int:
    from services import portalxs_service as pxs
    now = time.time()
    with pxs._mileage_report_cache_lock:
        keys = list(pxs._mileage_report_cache)
        if expired_only:
            keys = [k for k in keys
                    if (now - pxs._mileage_report_cache[k][0]) > pxs.MILEAGE_REPORT_CACHE_TTL / 2]
        for key in keys:
            pxs._mileage_report_cache.pop(key, None)
        return len(keys)


def _trim_notification_counts(expired_only: bool) -> int:
    import app as app_module
    cache = app_module._notif_cache
    if expired_only:
        return 0
    count = len(cache)
    cache.clear()
    return count


_TRIMMERS = (
    ('dashboard_html', _trim_dashboard_html),
    ('fleet_report', _trim_fleet_report),
    ('mileage_report', _trim_mileage_report),
    ('notification_counts', _trim_notification_counts),
)


def release_malloc_arenas() -> bool:
    """Hand glibc's freed arena pages back to the kernel.

    Rendering a large report allocates and frees tens of MB. CPython returns
    those blocks to glibc, but glibc keeps them in per-thread arenas, so the
    process RSS stays at its peak long after the request finished. That is why
    idle memory sat near the plateau of the busiest report of the day instead of
    falling back. ``malloc_trim`` releases the unused top of each arena; it is a
    no-op anywhere glibc is not the allocator (Windows, musl, macOS).
    """
    if platform.system() != 'Linux':
        return False
    try:
        libc_name = ctypes.util.find_library('c') or 'libc.so.6'
        libc = ctypes.CDLL(libc_name)
        if not hasattr(libc, 'malloc_trim'):
            return False
        libc.malloc_trim(0)
        return True
    except Exception as exc:
        logger.debug('memory guard: malloc_trim unavailable (%s)', exc)
        return False


def trim_caches(expired_only: bool = True) -> dict:
    """Release in-process caches. Returns {cache_name: items_released}."""
    released: dict[str, int] = {}
    for name, fn in _TRIMMERS:
        try:
            freed = fn(expired_only)
            if freed:
                released[name] = freed
        except Exception as exc:
            logger.debug('memory guard: %s trim skipped (%s)', name, exc)
    gc.collect()
    if release_malloc_arenas():
        released.setdefault('malloc_trim', 1)
    return released


def stats() -> dict:
    """Snapshot for /health and diagnostics."""
    out = dict(_state)
    rss = _rss_mb()
    if rss is not None:
        out['rss_mb'] = round(rss, 1)
    out['limit_mb'] = _env_float('MEMORY_LIMIT_MB', 512.0)
    return out


def _watch_once(soft_mb: float, hard_mb: float) -> None:
    rss = _rss_mb()
    if rss is None:
        return
    _state['last_rss_mb'] = round(rss, 1)
    _state['peak_rss_mb'] = max(_state['peak_rss_mb'], round(rss, 1))
    if rss < soft_mb:
        return

    hard = rss >= hard_mb
    released = trim_caches(expired_only=not hard)
    after = _rss_mb() or rss
    _state['hard_trims' if hard else 'soft_trims'] += 1
    logger.warning(
        'memory guard %s trim: %.1f MB -> %.1f MB, released=%s',
        'hard' if hard else 'soft', rss, after, released or '{}',
    )


def _loop(interval: float, soft_mb: float, hard_mb: float) -> None:
    while not _stop.is_set():
        try:
            _watch_once(soft_mb, hard_mb)
        except Exception as exc:
            logger.debug('memory guard sample failed: %s', exc)
        _stop.wait(interval)


def start_memory_guard(app=None) -> None:
    global _thread
    if (os.environ.get('MEMORY_GUARD_ENABLED', '1') or '1').strip().lower() in ('0', 'false', 'no'):
        return
    if _thread and _thread.is_alive():
        return
    if _rss_mb() is None:
        logger.info('memory guard not started (psutil unavailable)')
        return

    limit_mb = _env_float('MEMORY_LIMIT_MB', 512.0)
    soft_mb = limit_mb * _env_float('MEMORY_GUARD_SOFT_PCT', 72.0) / 100.0
    hard_mb = limit_mb * _env_float('MEMORY_GUARD_HARD_PCT', 85.0) / 100.0
    interval = _env_float('MEMORY_GUARD_INTERVAL', 45.0)

    _stop.clear()
    _thread = threading.Thread(
        target=_loop, args=(interval, soft_mb, hard_mb),
        daemon=True, name='memory-guard',
    )
    _thread.start()
    msg = (f'Memory guard started (limit {limit_mb:.0f} MB, soft {soft_mb:.0f} MB, '
           f'hard {hard_mb:.0f} MB, every {interval:.0f}s).')
    logger.info(msg)
    if app is not None and hasattr(app, 'logger'):
        app.logger.info(msg)


def stop_memory_guard() -> None:
    global _thread
    _stop.set()
    _thread = None
