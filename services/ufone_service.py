# -*- coding: utf-8 -*-
"""
Ufone BPOCOPS Service Layer
===========================
Flask-aware wrapper around services/ufone_api_client.py.

Mirrors services/portalxs_service.py pattern:
- Fernet password encryption (reuse tracker_automation crypto)
- In-memory cache for live positions (25s TTL) + task dashboard (60s)
- Background polling thread (30s interval)
- Auto re-login on session expiry
- Account CRUD with encrypted password storage
- ThreadPoolExecutor for bulk fetches
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

logger = logging.getLogger(__name__)

# ── Password encryption (reuse Fernet pattern from tracker_automation) ─────

def _fernet(app=None):
    from cryptography.fernet import Fernet
    import hashlib, base64
    if app is None:
        from flask import current_app as _app
        secret = _app.config.get('SECRET_KEY', 'fallback-secret-key')
    else:
        secret = app.config.get('SECRET_KEY', 'fallback-secret-key')
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def encrypt_password(plain: str, app=None) -> str:
    return _fernet(app).encrypt(plain.encode()).decode()


def decrypt_password(enc: str, app=None) -> str:
    try:
        return _fernet(app).decrypt(enc.encode()).decode()
    except Exception:
        return ''


# ── Data normalisation ───────────────────────────────────────────────────────

def _to_float(val, default=0.0):
    try:
        return float(val) if val not in (None, '', 'null') else default
    except (ValueError, TypeError):
        return default


def _to_int(val, default=0):
    try:
        return int(float(val)) if val not in (None, '', 'null') else default
    except (ValueError, TypeError):
        return default


def _parse_ms_date(ms_date_str: str) -> Optional[datetime]:
    """Parse .NET JSON date: /Date(1491805934643)/"""
    if not ms_date_str or not isinstance(ms_date_str, str):
        return None
    if '/Date(' in ms_date_str:
        try:
            ts = int(ms_date_str.split('(')[1].split(')')[0].split('-')[0])
            return datetime.fromtimestamp(ts / 1000)
        except (ValueError, IndexError):
            pass
    # try ISO
    for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
        try:
            return datetime.strptime(ms_date_str[:19], fmt)
        except ValueError:
            continue
    return None


def normalize_ambulance(raw: dict) -> dict:
    """Clean one Ufone ambulance record for UI use."""
    lat = _to_float(raw.get('Latitude'))
    lon = _to_float(raw.get('Logitude'))  # note: typo in Ufone API
    return {
        'id': raw.get('Id'),
        'reg_no': raw.get('Reg_No'),
        'u_track_no': raw.get('UTrackNo'),
        'tracking_world_regno': raw.get('registrationNo_trackingWorld'),
        'chassis': raw.get('Chassis'),
        'make_model': raw.get('MakeModel'),
        'latitude': lat,
        'longitude': lon,
        'location': raw.get('Location'),
        'district': (raw.get('district_name') or raw.get('DistrictName')
                     or raw.get('District') or raw.get('Location') or ''),
        'status': raw.get('Status'),
        'driver_name': raw.get('Driver_Name'),
        'driver_cell': raw.get('Driver_Cell'),
        'facility_name': raw.get('facility_name'),
        'distance': _to_float(raw.get('Distance'), None),
        'has_gps': lat != 0 and lon != 0,
    }


def normalize_task(raw: dict) -> dict:
    """Clean one Ufone task record.

    Handles keys from BOTH sources:
    - Dashboard.aspx/getAmbulanceTaskDashboard (login district)
    - ReportEmergencyTask.aspx/getAmbulanceTaskReport (all districts;
      TaskId comes as 'PHF-1234567', ambulance as 'ambRegNo',
      district as 'DistrictName')
    """
    return {
        'id': raw.get('id'),
        'task_id': raw.get('TaskId') or raw.get('id'),
        'patient_name': raw.get('name') or raw.get('Name'),
        'phone': raw.get('phone') or raw.get('Phone'),
        'address': raw.get('address') or raw.get('Address'),
        'ambulance': raw.get('Ambulance') or raw.get('ambRegNo'),
        'status': raw.get('Status'),
        'status2': raw.get('Status2'),
        'district': (raw.get('district_name') or raw.get('DistrictName')
                     or raw.get('District')),
        'tehsil': (raw.get('tehsil_name') or raw.get('TehsilName')
                   or raw.get('Tehsil')),
        'uc': raw.get('uc_name') or raw.get('UCname') or raw.get('UnionCouncil'),
        'facility_code': raw.get('facility_code') or raw.get('FacilityCode'),
        'facility_name': raw.get('facility_name') or raw.get('FacilityName'),
        'amb_id': raw.get('ambId'),
        'request_from': raw.get('RequestFrom'),
        'is_transfer': raw.get('isTransfer') or raw.get('isTransfer2'),
        'created_date': raw.get('CD') or raw.get('CreatedDate'),
        'distance': _to_float(raw.get('Distance') or raw.get('distanceInKM'), None),
        'driver_name': raw.get('Driver_Name'),
        'driver_cell': raw.get('Driver_Cell'),
        'location': raw.get('location') or raw.get('Location'),
        'category': raw.get('Category'),
        'request_for': raw.get('RequestFor'),
    }


def normalize_maintenance(raw: dict) -> dict:
    """Clean one Ufone maintenance record."""
    days = 0
    send = _parse_date_only(raw.get('Send_Date'))
    ret = _parse_date_only(raw.get('Return_Date'))
    if send and not ret:
        days = (date.today() - send).days
    elif send and ret:
        days = (ret - send).days
    return {
        'id': raw.get('Id'),
        'reg_no': raw.get('Reg_no'),
        'district': raw.get('District'),
        'maintain_type': raw.get('Maintain_Type'),
        'cat_name': raw.get('Cat_Name'),
        'sub_cat_name': raw.get('Sub_Cat_Name'),
        'due_date': raw.get('Due_Date'),
        'send_date': raw.get('Send_Date'),
        'return_date': raw.get('Return_Date'),
        'comments': raw.get('Comments'),
        'days_offline': max(0, days),
        'created_by': raw.get('CreatedBy'),
        'created_date': raw.get('Created_Date'),
    }


def _parse_date_only(s):
    """Parse a calendar date string → datetime.date (never datetime).

    Returning datetime here caused: can't compare datetime.datetime to
    datetime.date in fetch_tasks_report / DB date filters.
    """
    if not s:
        return None
    if isinstance(s, datetime):
        return s.date()
    if isinstance(s, date):
        return s
    for fmt in ('%m/%d/%Y', '%Y-%m-%d', '%d/%m/%Y'):
        try:
            return datetime.strptime(str(s).split()[0][:10], fmt).date()
        except ValueError:
            continue
    return None


def _parse_ufone_datetime(s):
    """Parse a Ufone task created-date string into a datetime.

    Handles: '07/22/2026 12:00:00 AM', '07/22/2026', '2026-07-22T00:55:10',
    '2026-07-22', '22 Jul 2026 00:55:10', '22-07-2026'. Returns None on failure.
    """
    if not s:
        return None
    s = str(s).strip()
    if not s or s.startswith('1900') or s.startswith('01/01/1900'):
        return None
    # ISO
    m = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})([ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?', s)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                            int(m.group(5) or 0), int(m.group(6) or 0), int(m.group(7) or 0))
        except ValueError:
            pass
    # MM/DD/YYYY [HH:MM:SS [AM|PM]]
    m = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{4})(?:[ ]+(\d{1,2}):(\d{2})(?::(\d{2}))?(?:\s*(AM|PM))?)?', s, re.I)
    if m:
        try:
            hh = int(m.group(4) or 0)
            ampm = (m.group(7) or '').upper()
            if ampm == 'PM' and hh < 12:
                hh += 12
            if ampm == 'AM' and hh == 12:
                hh = 0
            return datetime(int(m.group(3)), int(m.group(1)), int(m.group(2)),
                            hh, int(m.group(5) or 0), int(m.group(6) or 0))
        except ValueError:
            pass
    # '22 Jul 2026 00:55:10' / '22-Jul-2026'
    m = re.match(r'^(\d{1,2})[\s-]([A-Za-z]{3,})[\s-](\d{4})(?:[ ]+(\d{1,2}):(\d{2})(?::(\d{2}))?)?', s)
    if m:
        months = {'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
                  'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12}
        mon = months.get(m.group(2).lower())
        if mon:
            try:
                return datetime(int(m.group(3)), mon, int(m.group(1)),
                                int(m.group(4) or 0), int(m.group(5) or 0), int(m.group(6) or 0))
            except ValueError:
                pass
    # dd-mm-yyyy [HH:MM:SS]
    m = re.match(r'^(\d{1,2})-(\d{1,2})-(\d{4})(?:[ ]+(\d{1,2}):(\d{2})(?::(\d{2}))?)?', s)
    if m:
        try:
            return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)),
                            int(m.group(4) or 0), int(m.group(5) or 0), int(m.group(6) or 0))
        except ValueError:
            pass
    # Fallback: date only → midnight datetime
    d = _parse_date_only(s)
    if d:
        return datetime(d.year, d.month, d.day)
    return None


# ── Client pool + cache ──────────────────────────────────────────────────────

_live_cache: dict[int, tuple[float, list]] = {}   # account_id -> (ts, vehicles)
_live_cache_lock = threading.Lock()
_LIVE_CACHE_TTL = 25  # seconds

_task_cache: dict[int, tuple[float, list]] = {}
_task_cache_lock = threading.Lock()
_TASK_CACHE_TTL = 60


# ── Client pool (one UI session + one poller session per account) ────────────
# ASP.NET locks SessionId for the duration of each request. If the background
# poller runs a heavy getAmbulanceList on the SAME SessionId the UI uses,
# Task Detail / Refresh queue behind it and look like "server down".
_clients: dict[tuple[int, str], object] = {}
_clients_lock = threading.Lock()


def _get_client(account_id: int, purpose: str = "ui"):
    """Get or create a UfoneClient for an account.

    purpose='ui'   → interactive clicks (task detail, refresh)
    purpose='poll' → background poller (separate ASP.NET session cookies)
    """
    from models import UfoneAccount
    from services.ufone_api_client import UfoneClient
    from app import db

    if purpose not in ("ui", "poll"):
        purpose = "ui"
    key = (account_id, purpose)
    with _clients_lock:
        if key in _clients:
            return _clients[key]
    acct = UfoneAccount.query.get(account_id)
    if not acct:
        raise RuntimeError(f"UfoneAccount {account_id} not found")
    password = decrypt_password(acct.password_enc)
    if not password:
        raise RuntimeError(f"Cannot decrypt password for account {account_id}")
    session_key = str(account_id) if purpose == "ui" else f"{account_id}_poll"
    client = UfoneClient(acct.username, password, session_key=session_key)
    client.connect(reuse_session=True)
    with _clients_lock:
        _clients[key] = client
    # Update last_connected
    try:
        acct.last_connected = datetime.now()
        acct.last_error = None
        db.session.commit()
    except Exception:
        db.session.rollback()
    return client


def _reset_client(account_id: int, purpose: Optional[str] = None):
    with _clients_lock:
        if purpose:
            _clients.pop((account_id, purpose), None)
        else:
            for p in ("ui", "poll"):
                _clients.pop((account_id, p), None)


# ── Public data fetchers ─────────────────────────────────────────────────────

def fetch_live_positions(account_id: int, force: bool = False,
                         persist: bool = True, for_poll: bool = False) -> list:
    """Fetch live ambulance positions (cached for 25s).

    persist=False on interactive page loads — background poller writes DB.
    for_poll=True uses a separate ASP.NET session so UI clicks are not blocked.
    """
    now = time.time()
    if not force:
        with _live_cache_lock:
            cached = _live_cache.get(account_id)
            if cached and (now - cached[0]) < _LIVE_CACHE_TTL:
                return cached[1]
    purpose = "poll" if for_poll else "ui"
    try:
        client = _get_client(account_id, purpose=purpose)
        raw = client.get_ambulance_list()
        items = [normalize_ambulance(r) for r in (raw or [])]
        with _live_cache_lock:
            _live_cache[account_id] = (now, items)
        if persist:
            _persist_vehicles(account_id, items)
        return items
    except Exception as e:
        msg = str(e)
        if 'ConnectTimeout' in msg or 'ConnectionError' in msg or 'Max retries' in msg:
            logger.warning(
                f"fetch_live_positions({account_id}): Ufone server unreachable "
                f"(serving cached positions) — {msg[:120]}")
        else:
            logger.error(f"fetch_live_positions({account_id}) failed: {e}")
        _reset_client(account_id, purpose=purpose)
        with _live_cache_lock:
            cached = _live_cache.get(account_id)
            return cached[1] if cached else []


def fetch_task_dashboard(account_id: int, force: bool = False,
                         persist: bool = True, for_poll: bool = False) -> list:
    """Fetch active/Incomplete tasks (cached for 60s). Fast path for dashboard."""
    now = time.time()
    if not force:
        with _task_cache_lock:
            cached = _task_cache.get(account_id)
            if cached and (now - cached[0]) < _TASK_CACHE_TTL:
                return cached[1]
    purpose = "poll" if for_poll else "ui"
    try:
        client = _get_client(account_id, purpose=purpose)
        today = datetime.now().strftime("%Y-%m-%d")
        # visit_page=False — session already warm after connect(); skips extra GET
        raw = client.get_task_dashboard(
            start_date=today, end_date=today, visit_page=False
        )
        items = [normalize_task(r) for r in (raw or [])]
        items = sorted(
            items,
            key=lambda t: (_task_status_rank(t), -(int(t.get("task_id") or t.get("id") or 0))),
        )
        with _task_cache_lock:
            _task_cache[account_id] = (now, items)
        if persist:
            _persist_tasks(account_id, items)
        return items
    except Exception as e:
        msg = str(e)
        # Connection/timeout errors = Ufone server unreachable (not our bug).
        # Log as warning (not error) and note that cached data is being served.
        if 'ConnectTimeout' in msg or 'ConnectionError' in msg or 'Max retries' in msg:
            logger.warning(
                f"fetch_task_dashboard({account_id}): Ufone server unreachable "
                f"(serving cached tasks) — {msg[:120]}")
        else:
            logger.error(f"fetch_task_dashboard({account_id}) failed: {e}")
        _reset_client(account_id, purpose=purpose)
        with _task_cache_lock:
            cached = _task_cache.get(account_id)
            return cached[1] if cached else []


def _task_status_rank(task: dict) -> int:
    """Lower = higher priority on dashboard (Incomplete first)."""
    status = (task.get("status") or "").strip().lower()
    if "incomplete" in status or status in ("1", "in-process", "in process", "pending"):
        return 0
    if "complete" in status:
        return 2
    return 1


def _task_key(task: dict):
    return task.get("task_id") or task.get("id")


def fetch_today_tasks_all_districts(account_id: int, force: bool = False,
                                    include_report: bool = False) -> list:
    """Today's tasks. Fast by default (Incomplete via dashboard API only).

    include_report=True also pulls the heavy all-district emergency report —
    use only on explicit report pages, never on dashboard page load.
    """
    if not include_report:
        return fetch_task_dashboard(account_id, force=force, persist=False)

    cache_key = f"all:{account_id}:full"
    now = time.time()
    if not force:
        with _task_cache_lock:
            cached = _task_cache.get(cache_key)
            if cached and (now - cached[0]) < _TASK_CACHE_TTL:
                return cached[1]

    today = datetime.now().strftime("%Y-%m-%d")
    merged: dict = {}

    def _add(rows):
        for raw in (rows or []):
            if not isinstance(raw, dict):
                continue
            item = normalize_task(raw)
            key = _task_key(item)
            if key is None:
                continue
            existing = merged.get(key)
            if existing is None or _task_status_rank(item) < _task_status_rank(existing):
                merged[key] = item

    try:
        client = _get_client(account_id)
        try:
            _add(client.get_task_dashboard(
                start_date=today, end_date=today, district="", visit_page=False
            ))
        except Exception as e:
            logger.warning(f"dashboard tasks failed: {e}")
        try:
            _add(client.get_emergency_tasks(
                start_date=today, end_date=today, district="", visit_page=True
            ))
        except Exception as e:
            logger.warning(f"emergency tasks (all districts) failed: {e}")

        items = sorted(
            merged.values(),
            key=lambda t: (_task_status_rank(t), -(int(t.get("task_id") or t.get("id") or 0))),
        )
        with _task_cache_lock:
            _task_cache[cache_key] = (now, items)
            _task_cache[account_id] = (
                now,
                [t for t in items if _task_status_rank(t) == 0] or items[:50],
            )
        return items
    except Exception as e:
        logger.error(f"fetch_today_tasks_all_districts({account_id}) failed: {e}")
        _reset_client(account_id)
        with _task_cache_lock:
            cached = _task_cache.get(cache_key) or _task_cache.get(account_id)
            return cached[1] if cached else []


# ── Filtered report (all districts) + districts master ──────────────────────
# NOTE: the emergency report is now persisted to emergency_task_record
# (source='api') and read DB-first by fetch_tasks_report(). The in-memory
# _report_cache has been removed — the DB is the cache.

_districts_cache: tuple[float, list] = (0.0, [])
_districts_cache_lock = threading.Lock()
_DISTRICTS_TTL = 3600


def _norm_district(s: str) -> str:
    """Normalize a district name/code for fuzzy matching (lowercase, no
    dots/spaces/hyphens). 'D.G.Khan' == 'dgkhan' == 'd g khan'."""
    if not s:
        return ''
    return re.sub(r'[\s.\-_/]+', '', str(s).lower())


def fetch_tasks_report(account_id: int, start_date: str, end_date: str,
                       district: str = '', force: bool = False) -> list:
    """Emergency Task Report — DB-first (Option B: one row per task).

    Reads emergency_task_record by date range (excel + api unified).
    Freshness rule:
      • today is in the range → fresh if latest synced_at < 3 min ago
      • purely historical range → any rows are fresh (never re-fetch)
    If stale/missing/force, does ONE live all-district fetch on the poll
    session, upserts to DB, then returns. Filters NEVER trigger a live call.

    On live-call failure, returns whatever DB rows exist (stale-but-better).
    """
    from datetime import date as _date

    today = _date.today()
    try:
        from utils import pk_date
        today = pk_date()
    except Exception:
        pass
    sd = _parse_date_only(start_date) if start_date else today
    ed = _parse_date_only(end_date) if end_date else today
    if sd is None:
        sd = today
    if ed is None:
        ed = today
    range_includes_today = sd <= today <= ed

    def _from_db():
        rows = _emg_db_rows_for_range(start_date, end_date)
        if not rows:
            return []
        items = [_emg_row_to_task(r) for r in rows]
        items = sorted(
            items,
            key=lambda t: (_task_status_rank(t), str(t.get('created_date') or '')),
        )
        return _filter_by_district(items, district, account_id)

    # 1. Try DB first
    if not force:
        rows = _emg_db_rows_for_range(start_date, end_date)
        if rows:
            fresh = True
            if range_includes_today:
                latest = _emg_latest_sync()
                fresh = bool(latest and (datetime.now() - latest).total_seconds() < 180)
            # PK VPS owns live Ufone — serve DB even if "stale"
            if fresh or bridge_only_mode():
                return _from_db()

    # 2. Stale/missing/force → live all-district fetch (skip in bridge mode)
    if bridge_only_mode():
        items = _from_db()
        if items:
            return items
        raise RuntimeError(
            'No emergency task rows in DB yet — wait for PK VPS bridge sync.'
        )

    try:
        client = _get_client(account_id, purpose="poll")
        raw = client.get_emergency_tasks(
            start_date=start_date, end_date=end_date,
            district="", visit_page=False,
        )
        raw = [r for r in (raw or []) if isinstance(r, dict)]
        sync_emergency_report_to_db(account_id, raw, default_task_date=start_date)
        items = [normalize_task(r) for r in raw]
        items = sorted(
            items,
            key=lambda t: (_task_status_rank(t), str(t.get('created_date') or '')),
        )
        return _filter_by_district(items, district, account_id)
    except Exception as e:
        logger.warning(f"fetch_tasks_report live failed (serving DB if any): {e}")
        items = _from_db()
        if items:
            return items
        raise


def _filter_by_district(items: list, district: str, account_id: int) -> list:
    """Filter all-district report rows by a Ufone district code or name.

    The filter value from the UI is the district CODE; task rows carry the
    district NAME. We resolve code→name via get_districts_cached and match
    case/dot/space-insensitively so 'D.G.Khan' == 'dgkhan'.
    """
    if not district:
        return items
    target = _norm_district(district)
    # Resolve code → name (filter sends the code)
    names_to_match = set()
    try:
        for d in get_districts_cached(account_id):
            if _norm_district(d.get('code')) == target:
                names_to_match.add(_norm_district(d.get('name')))
    except Exception:
        pass
    names_to_match.add(target)  # also allow matching the raw value as a name
    out = []
    for t in items:
        dn = _norm_district(t.get('district'))
        if not dn:
            continue
        if dn in names_to_match:
            out.append(t)
    return out


def _districts_from_vehicle_cache(account_id: int) -> list:
    """Fallback district options from vehicle/task cache names (bridge mode)."""
    from models import UfoneTaskCache, UfoneVehicleCache
    names = set()
    try:
        for (d,) in (UfoneVehicleCache.query
                     .with_entities(UfoneVehicleCache.district)
                     .filter_by(account_id=account_id)
                     .distinct()):
            if d and str(d).strip():
                names.add(str(d).strip())
    except Exception:
        pass
    try:
        for (d,) in (UfoneTaskCache.query
                     .with_entities(UfoneTaskCache.district)
                     .filter_by(account_id=account_id)
                     .distinct()):
            if d and str(d).strip():
                names.add(str(d).strip())
    except Exception:
        pass
    items = [{'code': n, 'name': n} for n in names]
    items.sort(key=lambda x: x['name'].lower())
    return items


def get_districts_cached(account_id: int) -> list:
    """Master district list [{code, name}] — DB-first (Phase 1).

    Reads ufone_district_cache. If DB empty or oldest synced_at > 7 days,
    does ONE live fetch + upsert (skipped in UFONE_BRIDGE_ONLY). Keeps a 1h
    in-memory layer. Bridge fallback: distinct names from vehicle/task cache.
    """
    global _districts_cache
    now = time.time()
    with _districts_cache_lock:
        ts, items = _districts_cache
        if items and (now - ts) < _DISTRICTS_TTL:
            return items

    # 1. Try DB
    try:
        from models import UfoneDistrictCache
        rows = UfoneDistrictCache.query.all()
        if rows:
            oldest = None
            for r in rows:
                if r.synced_at and (oldest is None or r.synced_at < oldest):
                    oldest = r.synced_at
            stale = bool(oldest and (datetime.now() - oldest).days >= 7)
            # In bridge mode never force a live refresh — serve whatever we have
            if not stale or bridge_only_mode():
                items = [{'code': r.code, 'name': r.name or ''} for r in rows]
                items.sort(key=lambda x: x['name'])
                with _districts_cache_lock:
                    _districts_cache = (now, items)
                return items
    except Exception as e:
        logger.warning(f"get_districts_cached DB read failed: {e}")

    # 2. Live fetch + upsert (Render cannot reach Ufone in bridge mode)
    if bridge_only_mode():
        items = _districts_from_vehicle_cache(account_id)
        if items:
            with _districts_cache_lock:
                _districts_cache = (now, items)
        return items

    try:
        client = _get_client(account_id, purpose="ui")
        raw = client.get_districts() or []
        items = []
        for d in raw:
            if not isinstance(d, dict):
                continue
            code = d.get('district_code') or d.get('DistrictCode') or d.get('code')
            name = (d.get('district_name') or d.get('DistrictName')
                    or d.get('name') or d.get('District'))
            if code is not None and name:
                items.append({'code': str(code), 'name': str(name).strip()})
        items.sort(key=lambda x: x['name'])
        if items:
            with _districts_cache_lock:
                _districts_cache = (now, items)
            # Persist to DB (best-effort)
            try:
                from models import UfoneDistrictCache
                from app import db
                now_dt = datetime.now()
                for it in items:
                    row = UfoneDistrictCache.query.get(it['code'])
                    if not row:
                        row = UfoneDistrictCache(code=it['code'])
                        db.session.add(row)
                    row.name = it['name']
                    row.synced_at = now_dt
                db.session.commit()
            except Exception as de:
                db.session.rollback()
                logger.warning(f"district DB upsert failed (non-fatal): {de}")
        return items
    except Exception as e:
        logger.warning(f"get_districts failed: {e}")
        fallback = _districts_from_vehicle_cache(account_id)
        if fallback:
            return fallback
        with _districts_cache_lock:
            return _districts_cache[1]


# ── Tehsils / UCs: DB-first (Phase 2) ─────────────────────────────────────────

_TEHSILS_TTL_DAYS = 7
_UC_TTL_DAYS = 7


def get_tehsils_cached(account_id: int, district_code: str) -> list:
    """Tehsils for a district — DB-first, weekly refresh.

    Returns the raw Ufone shape [{'tehsil_code', 'tehsil_name'}, ...] so the
    existing templates/routes work unchanged.
    """
    if not district_code:
        return []
    try:
        from models import UfoneTehsilCache
        rows = UfoneTehsilCache.query.filter_by(district_code=str(district_code)).all()
        stale = bool(rows) and all(
            r.synced_at and (datetime.now() - r.synced_at).days >= _TEHSILS_TTL_DAYS
            for r in rows)
        if rows and not stale:
            return [{'tehsil_code': r.tehsil_code, 'tehsil_name': r.tehsil_name or ''}
                    for r in rows]
    except Exception as e:
        logger.warning(f"get_tehsils_cached DB read failed: {e}")

    # Live fetch + upsert
    try:
        client = _get_client(account_id, purpose="ui")
        raw = client.get_tehsils(str(district_code)) or []
        items = []
        for t in raw:
            if not isinstance(t, dict):
                continue
            code = t.get('tehsil_code') or t.get('TehsilCode') or t.get('code')
            name = (t.get('tehsil_name') or t.get('TehsilName')
                    or t.get('name') or t.get('Tehsil'))
            if code is not None:
                items.append({'tehsil_code': str(code),
                               'tehsil_name': str(name or '').strip()})
        if items:
            try:
                from models import UfoneTehsilCache
                from app import db
                now_dt = datetime.now()
                # Replace all tehsils for this district (simple, small set)
                UfoneTehsilCache.query.filter_by(
                    district_code=str(district_code)).delete()
                for it in items:
                    db.session.add(UfoneTehsilCache(
                        district_code=str(district_code),
                        tehsil_code=it['tehsil_code'],
                        tehsil_name=it['tehsil_name'],
                        synced_at=now_dt))
                db.session.commit()
            except Exception as de:
                db.session.rollback()
                logger.warning(f"tehsil DB upsert failed (non-fatal): {de}")
        return items
    except Exception as e:
        logger.warning(f"get_tehsils_cached live failed: {e}")
        # Fall back to whatever DB rows we have (even if stale)
        try:
            from models import UfoneTehsilCache
            rows = UfoneTehsilCache.query.filter_by(
                district_code=str(district_code)).all()
            return [{'tehsil_code': r.tehsil_code, 'tehsil_name': r.tehsil_name or ''}
                    for r in rows]
        except Exception:
            return []


def get_ucs_cached(account_id: int, tehsil_code: str) -> list:
    """Union Councils for a tehsil — DB-first, weekly refresh.

    Returns the raw Ufone shape [{'uc_code', 'uc_name'}, ...].
    """
    if not tehsil_code:
        return []
    try:
        from models import UfoneUCCache
        rows = UfoneUCCache.query.filter_by(tehsil_code=str(tehsil_code)).all()
        stale = bool(rows) and all(
            r.synced_at and (datetime.now() - r.synced_at).days >= _UC_TTL_DAYS
            for r in rows)
        if rows and not stale:
            return [{'uc_code': r.uc_code, 'uc_name': r.uc_name or ''} for r in rows]
    except Exception as e:
        logger.warning(f"get_ucs_cached DB read failed: {e}")

    try:
        client = _get_client(account_id, purpose="ui")
        raw = client.get_union_councils(str(tehsil_code)) or []
        items = []
        for u in raw:
            if not isinstance(u, dict):
                continue
            code = (u.get('uc_code') or u.get('UCcode') or u.get('UCCode')
                    or u.get('code') or u.get('id'))
            name = (u.get('uc_name') or u.get('UCname') or u.get('UCName')
                    or u.get('name') or u.get('UnionCouncil'))
            if code is not None:
                items.append({'uc_code': str(code),
                              'uc_name': str(name or '').strip()})
        if items:
            try:
                from models import UfoneUCCache
                from app import db
                now_dt = datetime.now()
                UfoneUCCache.query.filter_by(
                    tehsil_code=str(tehsil_code)).delete()
                for it in items:
                    db.session.add(UfoneUCCache(
                        tehsil_code=str(tehsil_code),
                        uc_code=it['uc_code'],
                        uc_name=it['uc_name'],
                        synced_at=now_dt))
                db.session.commit()
            except Exception as de:
                db.session.rollback()
                logger.warning(f"uc DB upsert failed (non-fatal): {de}")
        return items
    except Exception as e:
        logger.warning(f"get_ucs_cached live failed: {e}")
        try:
            from models import UfoneUCCache
            rows = UfoneUCCache.query.filter_by(
                tehsil_code=str(tehsil_code)).all()
            return [{'uc_code': r.uc_code, 'uc_name': r.uc_name or ''} for r in rows]
        except Exception:
            return []


# ── Maintenance: DB-first (Phase 2) ───────────────────────────────────────────

_maintenance_cache: dict[int, tuple[float, list]] = {}
_maintenance_cache_lock = threading.Lock()
_MAINTENANCE_CACHE_TTL = 1800  # 30 min — maintenance changes slowly


def _persist_maintenance(account_id: int, items: list):
    """Upsert UfoneMaintenanceCache rows (best-effort)."""
    from models import UfoneMaintenanceCache
    from app import db
    try:
        existing = {
            r.reg_no: r
            for r in UfoneMaintenanceCache.query.filter_by(
                account_id=account_id).all()
        }
        seen_regs = set()
        for m in items:
            reg = m.get('reg_no')
            if not reg:
                continue
            seen_regs.add(reg)
            row = existing.get(reg)
            if not row:
                row = UfoneMaintenanceCache(account_id=account_id, reg_no=reg)
                db.session.add(row)
                existing[reg] = row
            row.district = m.get('district')
            row.maintain_type = m.get('maintain_type')
            row.cat_name = m.get('cat_name')
            row.sub_cat_name = m.get('sub_cat_name')
            row.due_date = _parse_date_only(m.get('due_date'))
            row.send_date = _parse_date_only(m.get('send_date'))
            row.return_date = _parse_date_only(m.get('return_date'))
            row.comments = m.get('comments')
            row.days_offline = m.get('days_offline') or 0
            row.created_by = m.get('created_by')
            row.created_date = _parse_date_only(m.get('created_date'))
        # Remove rows for regs no longer under maintenance
        for reg, row in existing.items():
            if reg not in seen_regs:
                db.session.delete(row)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.warning(f"_persist_maintenance failed (non-fatal): {e}")


def fetch_maintenance(account_id: int, force: bool = False,
                       for_poll: bool = False) -> list:
    """Ambulances under maintenance — DB-first (Phase 2).

    Reads UfoneMaintenanceCache. If fresh (<30 min) returns instantly. On
    stale/missing/force, live fetches on poll session + persists. Returns the
    normalize_maintenance() dict shape so routes/templates work unchanged.
    """
    now = time.time()
    if not force:
        with _maintenance_cache_lock:
            cached = _maintenance_cache.get(account_id)
            if cached and (now - cached[0]) < _MAINTENANCE_CACHE_TTL:
                return cached[1]

    purpose = "poll" if for_poll else "ui"
    try:
        client = _get_client(account_id, purpose=purpose)
        raw = client.get_maintenance() or []
        items = [normalize_maintenance(r) for r in raw if isinstance(r, dict)]
        with _maintenance_cache_lock:
            _maintenance_cache[account_id] = (now, items)
        _persist_maintenance(account_id, items)
        return items
    except Exception as e:
        msg = str(e)
        if 'ConnectTimeout' in msg or 'ConnectionError' in msg or 'Max retries' in msg:
            logger.warning(
                f"fetch_maintenance({account_id}): Ufone unreachable "
                f"(serving cached) — {msg[:120]}")
        else:
            logger.warning(f"fetch_maintenance({account_id}) failed: {e}")
        _reset_client(account_id, purpose=purpose)
        # Serve from DB cache
        try:
            from models import UfoneMaintenanceCache
            rows = UfoneMaintenanceCache.query.filter_by(
                account_id=account_id).all()
            items = [{
                'id': None,
                'reg_no': r.reg_no,
                'district': r.district,
                'maintain_type': r.maintain_type,
                'cat_name': r.cat_name,
                'sub_cat_name': r.sub_cat_name,
                'due_date': r.due_date.strftime('%Y-%m-%d') if r.due_date else None,
                'send_date': r.send_date.strftime('%Y-%m-%d') if r.send_date else None,
                'return_date': r.return_date.strftime('%Y-%m-%d') if r.return_date else None,
                'comments': r.comments,
                'days_offline': r.days_offline or 0,
                'created_by': r.created_by,
                'created_date': r.created_date.strftime('%Y-%m-%d') if r.created_date else None,
            } for r in rows]
            with _maintenance_cache_lock:
                _maintenance_cache[account_id] = (now, items)
            return items
        except Exception:
            with _maintenance_cache_lock:
                cached = _maintenance_cache.get(account_id)
                return cached[1] if cached else []


# ── Generic persisted report cache (Phase 2) ─────────────────────────────────
# Used for patients, patients-ussd, distance, daily/monthly task counts —
# endpoints that return date-range reports. Caches the raw API response per
# (account, report_key, params_hash) in ufone_report_cache with a TTL.

import hashlib as _hashlib


def _report_params_hash(params: dict) -> str:
    if not params:
        return ''
    try:
        s = json.dumps(params, sort_keys=True, default=str)
        return _hashlib.md5(s.encode()).hexdigest()[:16]
    except Exception:
        return ''


def get_cached_report(account_id: int, report_key: str, params: dict = None,
                       max_age_seconds: int = 600):
    """Return cached response (parsed list) if fresh, else None."""
    from models import UfoneReportCache
    try:
        ph = _report_params_hash(params or {})
        row = UfoneReportCache.query.filter_by(
            account_id=account_id, report_key=report_key,
            params_hash=ph).first()
        if not row or not row.synced_at:
            return None
        if (datetime.now() - row.synced_at).total_seconds() > max_age_seconds:
            return None
        return json.loads(row.response_json) if row.response_json else None
    except Exception as e:
        logger.warning(f"get_cached_report({report_key}) failed: {e}")
        return None


def save_cached_report(account_id: int, report_key: str, response,
                        params: dict = None):
    """Upsert a report response into ufone_report_cache."""
    from models import UfoneReportCache
    from app import db
    try:
        ph = _report_params_hash(params or {})
        row = UfoneReportCache.query.filter_by(
            account_id=account_id, report_key=report_key,
            params_hash=ph).first()
        if not row:
            row = UfoneReportCache(
                account_id=account_id, report_key=report_key, params_hash=ph)
            db.session.add(row)
        row.response_json = json.dumps(response, default=str) if response is not None else None
        row.synced_at = datetime.now()
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.warning(f"save_cached_report({report_key}) failed (non-fatal): {e}")


def fetch_report_cached(account_id: int, report_key: str, fetch_fn,
                         params: dict = None, max_age_seconds: int = 600,
                         for_poll: bool = False):
    """DB-first wrapper for any Ufone report endpoint.

    1. Read ufone_report_cache for (account, report_key, params). If fresh, return.
    2. Else live fetch via fetch_fn(client) on poll session, persist, return.
    3. On live failure, return stale cache if available.

    fetch_fn: callable taking a UfoneClient and returning the raw API response.
    """
    cached = get_cached_report(account_id, report_key, params, max_age_seconds)
    if cached is not None:
        return cached
    purpose = "poll" if for_poll else "ui"
    try:
        client = _get_client(account_id, purpose=purpose)
        response = fetch_fn(client)
        save_cached_report(account_id, report_key, response, params)
        return response
    except Exception as e:
        logger.warning(f"fetch_report_cached({report_key}) live failed: {e}")
        _reset_client(account_id, purpose=purpose)
        # Try stale cache (ignore TTL)
        try:
            from models import UfoneReportCache
            ph = _report_params_hash(params or {})
            row = UfoneReportCache.query.filter_by(
                account_id=account_id, report_key=report_key,
                params_hash=ph).first()
            if row and row.response_json:
                return json.loads(row.response_json)
        except Exception:
            pass
        raise


_dash_counts_cache: dict[int, tuple[float, dict]] = {}
_dash_counts_lock = threading.Lock()
# NOTE: counts are now computed DB-first (SQL on emergency_task_record) — no
# TTL needed. The cache just stores the last result for fallback on error.


def _vehicle_cache_count(account_id: int) -> int:
    """Total ambulances from our DB cache (instant — no Ufone HTTP)."""
    from models import UfoneVehicleCache
    from app import db
    try:
        return db.session.query(UfoneVehicleCache).filter_by(
            account_id=account_id).count() or 0
    except Exception:
        return 0


def _maintenance_cache_count(account_id: int) -> int:
    """Ambulances currently under maintenance from our DB cache (instant)."""
    from models import UfoneMaintenanceCache
    from app import db
    try:
        return db.session.query(UfoneMaintenanceCache).filter_by(
            account_id=account_id).count() or 0
    except Exception:
        return 0


def fetch_dashboard_counts(account_id: int, force: bool = False,
                            purpose: str = "ui") -> dict:
    """Dashboard card counts — DB-first (Phase 1). All instant, NO Ufone HTTP.

      • Total Ambulances → ufone_vehicle_cache (DB COUNT, instant)
      • Task Green/Yellow/Red/Orange/In-Process → emergency_task_record
        (source='api', today) Category/Status columns — SQL, instant
      • Total Task Count → sum of the above
      • synced_at → latest sync timestamp (for freshness label)

    Bridge / empty EMG fallback: derive In-Process + synced_at from
    ufone_task_cache / ufone_vehicle_cache (PK VPS writes those).
    """
    from datetime import date as _date
    from models import EmergencyTaskRecord, UfoneTaskCache, UfoneVehicleCache
    now = time.time()
    total_amb = _vehicle_cache_count(account_id)

    try:
        today = _date.today()
        # Prefer PK calendar day when utils available (Render often runs UTC).
        try:
            from utils import pk_date
            today = pk_date()
        except Exception:
            pass
        rows = (EmergencyTaskRecord.query
                .filter(EmergencyTaskRecord.task_date == today)
                .all())
        green = yellow = red = orange = in_process = 0
        latest_sync = None
        for r in rows:
            cat = (r.category or '').strip().lower()
            st = (r.status or '').strip().lower()
            if cat == 'green':
                green += 1
            elif cat == 'yellow':
                yellow += 1
            elif cat == 'red':
                red += 1
            elif cat == 'orange':
                orange += 1
            elif ('incomplete' in st or st == '1'
                  or 'in-process' in st or 'in process' in st):
                in_process += 1
            if r.synced_at and (latest_sync is None or r.synced_at > latest_sync):
                latest_sync = r.synced_at

        task_total = green + yellow + red + orange + in_process

        # Fallback when EMG report not yet synced (common in PK VPS bridge mode)
        if task_total == 0:
            trows = UfoneTaskCache.query.filter_by(account_id=account_id).all()
            for r in trows:
                st = (r.status or '').strip().lower()
                if ('incomplete' in st or st == '1'
                        or 'in-process' in st or 'in process' in st):
                    in_process += 1
                elif 'cancel' in st:
                    pass
                elif 'complete' in st:
                    # keep completed out of colored buckets unless category known
                    pass
            task_total = in_process

        # Last Synced = task/EMG freshness only.
        # Do NOT use vehicle updated_at — getAmbulanceList runs once at 11 PM
        # and its stamp (often mixed TZ) falsely wins max() over live EMG sync.
        candidates = []
        if latest_sync:
            candidates.append(latest_sync)
        latest_t = (UfoneTaskCache.query.filter_by(account_id=account_id)
                    .order_by(UfoneTaskCache.updated_at.desc()).first())
        if latest_t and latest_t.updated_at:
            candidates.append(latest_t.updated_at)
        try:
            any_emg = (EmergencyTaskRecord.query
                       .filter(EmergencyTaskRecord.synced_at.isnot(None))
                       .order_by(EmergencyTaskRecord.synced_at.desc())
                       .first())
            if any_emg and any_emg.synced_at:
                candidates.append(any_emg.synced_at)
        except Exception:
            pass
        if candidates:
            latest_sync = max(candidates)

        synced_iso = None
        if latest_sync:
            # Bridge now writes with SET TIME ZONE Asia/Karachi (naive = PKT).
            # Older UTC-naive rows: if "as PKT" is >1h in the future, treat as UTC.
            from datetime import timezone, timedelta as _td
            pk_now_naive = datetime.utcnow() + _td(hours=5)
            dt = latest_sync.replace(tzinfo=None) if getattr(latest_sync, 'tzinfo', None) else latest_sync
            as_pk = dt
            if as_pk > pk_now_naive + _td(hours=1):
                as_pk = dt + _td(hours=5)
            elif as_pk < pk_now_naive - _td(hours=2):
                # Likely UTC from VPS before TZ fix (e.g. 22:03 UTC → 03:03 PKT)
                converted = dt + _td(hours=5)
                if converted <= pk_now_naive + _td(minutes=30):
                    as_pk = converted
            synced_iso = as_pk.replace(microsecond=0).isoformat() + '+05:00'

        data = {
            'total_ambulances': total_amb,
            'task_green': green,
            'task_yellow': yellow,
            'task_red': red,
            'task_orange': orange,
            'task_in_process': in_process,
            'task_total': task_total,
            'synced_at': synced_iso,
            'fetched_at': now,
        }
        with _dash_counts_lock:
            _dash_counts_cache[account_id] = (now, data)
        return data
    except Exception as e:
        logger.warning(f"fetch_dashboard_counts failed: {e}")
        with _dash_counts_lock:
            cached = _dash_counts_cache.get(account_id)
        if cached:
            cached[1]['total_ambulances'] = total_amb
            cached[1]['fetched_at'] = now
            return cached[1]
        return {
            'total_ambulances': total_amb,
            'task_green': 0, 'task_yellow': 0, 'task_red': 0,
            'task_orange': 0, 'task_in_process': 0, 'task_total': 0,
            'synced_at': None, 'fetched_at': now,
        }


def get_cached_positions(account_id: int) -> list:
    """Get cached positions (no fetch)."""
    with _live_cache_lock:
        cached = _live_cache.get(account_id)
        return cached[1] if cached else []


def get_cached_tasks(account_id: int) -> list:
    """Get in-memory task cache (no fetch)."""
    with _task_cache_lock:
        cached = _task_cache.get(account_id)
        return list(cached[1]) if cached else []


def load_vehicles_from_db(account_id: int) -> list:
    """Read last-known vehicles from UfoneVehicleCache (instant, no Ufone HTTP)."""
    from models import UfoneVehicleCache
    rows = UfoneVehicleCache.query.filter_by(account_id=account_id).all()
    items = []
    for r in rows:
        lat = float(r.last_lat) if r.last_lat is not None else 0.0
        lon = float(r.last_lon) if r.last_lon is not None else 0.0
        try:
            status = int(r.status) if r.status not in (None, '') else None
        except (TypeError, ValueError):
            status = r.status
        items.append({
            'id': None,
            'reg_no': r.reg_no,
            'u_track_no': r.u_track_no,
            'tracking_world_regno': r.tracking_world_regno,
            'chassis': r.chassis,
            'make_model': r.make_model,
            'latitude': lat,
            'longitude': lon,
            'location': r.last_location,
            'district': r.district or '',
            'status': status,
            'driver_name': r.driver_name,
            'driver_cell': r.driver_cell,
            'facility_name': r.facility_name,
            'distance': float(r.last_distance) if r.last_distance is not None else None,
            'has_gps': lat != 0 and lon != 0,
        })
    if items:
        with _live_cache_lock:
            _live_cache[account_id] = (time.time(), items)
    return items


def load_tasks_from_db(account_id: int, limit: int = 50) -> list:
    """Read last-known tasks from UfoneTaskCache (instant, no Ufone HTTP)."""
    from models import UfoneTaskCache
    rows = (
        UfoneTaskCache.query.filter_by(account_id=account_id)
        .order_by(UfoneTaskCache.updated_at.desc())
        .limit(200)
        .all()
    )
    items = []
    for r in rows:
        # created_date: prefer the parsed DB column; fall back to raw_json
        # (older rows may have NULL created_date before the backfill fix).
        cd = r.created_date.isoformat() if r.created_date else None
        if not cd and r.raw_json:
            try:
                rj = json.loads(r.raw_json)
                cd = rj.get('created_date') or rj.get('CD') or rj.get('CreatedDate')
            except Exception:
                cd = None
        items.append({
            'id': r.task_id,
            'task_id': r.task_id,
            'patient_name': r.patient_name,
            'phone': r.phone,
            'address': r.address,
            'ambulance': r.ambulance_reg,
            'status': r.status,
            'status2': None,
            'district': r.district,
            'tehsil': r.tehsil,
            'uc': None,
            'facility_code': None,
            'facility_name': r.facility,
            'amb_id': None,
            'request_from': r.request_from,
            'is_transfer': r.is_transfer,
            'created_date': cd,
            'distance': float(r.distance) if r.distance is not None else None,
            'driver_name': None,
            'driver_cell': None,
            'location': None,
        })
    items = sorted(
        items,
        key=lambda t: (_task_status_rank(t), -(int(t.get('task_id') or 0) if str(t.get('task_id') or '').isdigit() else 0)),
    )
    if limit:
        items = items[:limit]
    if items:
        with _task_cache_lock:
            _task_cache[account_id] = (time.time(), items)
    return items


def load_dashboard_snapshot(account_id: int) -> tuple:
    """Instant dashboard data: memory → SQLite cache. Never calls Ufone HTTP."""
    vehicles = get_cached_positions(account_id)
    if not vehicles:
        vehicles = load_vehicles_from_db(account_id)
    tasks = get_cached_tasks(account_id)
    if not tasks:
        tasks = load_tasks_from_db(account_id)
    stats = get_summary_stats(account_id, vehicles=vehicles)
    return vehicles, tasks, stats


def get_summary_stats(account_id: int, vehicles: list = None) -> dict:
    """Compute summary stats from cached (or provided) positions."""
    if vehicles is None:
        vehicles = get_cached_positions(account_id)
    total = len(vehicles)
    active = sum(1 for v in vehicles if v.get('status') == 1)
    inactive = sum(1 for v in vehicles if v.get('status') == 2)
    with_gps = sum(1 for v in vehicles if v.get('has_gps'))
    return {
        'total': total,
        'active': active,
        'inactive': inactive,
        'with_gps': with_gps,
        'without_gps': total - with_gps,
    }


# ── DB persistence helpers ───────────────────────────────────────────────────

def _persist_vehicles(account_id: int, vehicles: list):
    """Upsert UfoneVehicleCache rows (best-effort). Load only touched regs."""
    from models import UfoneVehicleCache
    from app import db
    try:
        regs = [v.get('reg_no') for v in vehicles if v.get('reg_no')]
        if not regs:
            return
        existing = {
            r.reg_no: r
            for r in UfoneVehicleCache.query.filter_by(account_id=account_id)
            .filter(UfoneVehicleCache.reg_no.in_(regs)).all()
        }
        for v in vehicles:
            reg = v.get('reg_no')
            if not reg:
                continue
            row = existing.get(reg)
            if not row:
                row = UfoneVehicleCache(account_id=account_id, reg_no=reg)
                db.session.add(row)
                existing[reg] = row
            row.u_track_no = v.get('u_track_no')
            row.tracking_world_regno = v.get('tracking_world_regno')
            row.chassis = v.get('chassis')
            row.make_model = v.get('make_model')
            row.last_lat = v.get('latitude')
            row.last_lon = v.get('longitude')
            row.last_location = v.get('location')
            row.district = v.get('district')
            row.status = str(v.get('status') or '')
            row.driver_name = v.get('driver_name')
            row.driver_cell = v.get('driver_cell')
            row.facility_name = v.get('facility_name')
            row.last_distance = v.get('distance')
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.warning(f"_persist_vehicles failed (non-fatal): {e}")


def _persist_tasks(account_id: int, tasks: list):
    """Upsert UfoneTaskCache rows (best-effort). Load only touched task ids."""
    from models import UfoneTaskCache
    from app import db
    try:
        tids = [str(t.get('task_id') or t.get('id') or '') for t in tasks]
        tids = [t for t in tids if t]
        if not tids:
            return
        existing = {
            r.task_id: r
            for r in UfoneTaskCache.query.filter_by(account_id=account_id)
            .filter(UfoneTaskCache.task_id.in_(tids)).all()
        }
        for t in tasks:
            tid = str(t.get('task_id') or t.get('id') or '')
            if not tid:
                continue
            row = existing.get(tid)
            if not row:
                row = UfoneTaskCache(account_id=account_id, task_id=tid)
                db.session.add(row)
                existing[tid] = row
            row.patient_name = t.get('patient_name')
            row.phone = t.get('phone')
            row.address = t.get('address')
            row.ambulance_reg = t.get('ambulance')
            row.status = t.get('status')
            row.district = t.get('district')
            row.tehsil = t.get('tehsil')
            row.facility = t.get('facility_name')
            row.request_from = t.get('request_from')
            row.distance = t.get('distance')
            row.is_transfer = bool(t.get('is_transfer'))
            row.created_date = _parse_ufone_datetime(t.get('created_date'))
            row.raw_json = json.dumps(t, default=str)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.warning(f"_persist_tasks failed (non-fatal): {e}")


def ingest_bridge_payload(account_id: int, payload: dict) -> dict:
    """Accept PK-VPS bridge payload and upsert Ufone caches (+ optional EMG).

    Payload keys (all optional except needing at least one data section):
      vehicles / vehicles_raw — normalized or raw ambulance list
      tasks / tasks_raw — normalized or raw task dashboard rows
      emergency_report — raw getAmbulanceTaskReport rows
      maintenance / maintenance_raw — optional
      task_date — YYYY-MM-DD for emergency sync default
    """
    if not account_id:
        raise ValueError('account_id required')
    result = {
        'account_id': account_id,
        'vehicles': 0,
        'tasks': 0,
        'emergency_report': 0,
        'maintenance': 0,
    }

    vehicles = payload.get('vehicles')
    if vehicles is None and payload.get('vehicles_raw') is not None:
        vehicles = [normalize_ambulance(r) for r in (payload.get('vehicles_raw') or [])
                    if isinstance(r, dict)]
    if vehicles:
        _persist_vehicles(account_id, vehicles)
        with _live_cache_lock:
            _live_cache[account_id] = (time.time(), list(vehicles))
        result['vehicles'] = len(vehicles)

    tasks = payload.get('tasks')
    if tasks is None and payload.get('tasks_raw') is not None:
        tasks = [normalize_task(r) for r in (payload.get('tasks_raw') or [])
                 if isinstance(r, dict)]
    if tasks:
        _persist_tasks(account_id, tasks)
        with _task_cache_lock:
            _task_cache[account_id] = (time.time(), list(tasks))
        result['tasks'] = len(tasks)

    emg = payload.get('emergency_report')
    if emg:
        raw = [r for r in emg if isinstance(r, dict)]
        result['emergency_report'] = sync_emergency_report_to_db(
            account_id, raw, default_task_date=payload.get('task_date'))

    maintenance = payload.get('maintenance')
    if maintenance is None and payload.get('maintenance_raw') is not None:
        maintenance = [normalize_maintenance(r)
                       for r in (payload.get('maintenance_raw') or [])
                       if isinstance(r, dict)]
    if maintenance:
        try:
            _persist_maintenance(account_id, maintenance)
            result['maintenance'] = len(maintenance)
        except Exception as e:
            logger.warning(f"ingest maintenance failed: {e}")

    return result


def bridge_only_mode() -> bool:
    """When true, Render must not call bpocops directly (PK VPS bridge does)."""
    return (os.environ.get('UFONE_BRIDGE_ONLY') or '').strip().lower() in (
        '1', 'true', 'yes', 'on')


# ── DB-first: Emergency Task Report sync ─────────────────────────────────────

# Driver push notifications on task generate / close. Detection happens during
# sync by comparing the incoming report against existing DB rows. Guards below
# prevent spam: only today's tasks fire, and the very first population of an
# account (no prior api rows) is silent.
_NOTIFY_TASK_EVENTS = True


def _status_is_complete(status) -> bool:
    s = (status or '').strip().lower()
    return ('complete' in s) and ('incomplete' not in s)


def _match_vehicle_driver(amb_reg_no):
    """Resolve a Ufone ambulance reg-no to our (Vehicle, Driver). Returns
    (vehicle, driver) or (None, None). Tries exact then normalized match."""
    from models import Vehicle, Driver
    if not amb_reg_no:
        return None, None
    reg = str(amb_reg_no).strip()
    if not reg:
        return None, None
    veh = Vehicle.query.filter_by(vehicle_no=reg).first()
    if not veh:
        norm = reg.upper().replace(' ', '').replace('-', '')
        for v in Vehicle.query.all():
            vn = str(v.vehicle_no or '').upper().replace(' ', '').replace('-', '')
            if vn and vn == norm:
                veh = v
                break
    if not veh or not veh.driver_id:
        return veh, None
    drv = db_get_driver(veh.driver_id)
    return veh, drv


def db_get_driver(driver_pk):
    from models import Driver
    from app import db
    try:
        return db.session.get(Driver, driver_pk)
    except Exception:
        return None


def _display_task_id(tid) -> str:
    """Show numeric id without PHF- prefix when present."""
    s = str(tid or '').strip()
    if s.upper().startswith('PHF-'):
        return s[4:].strip() or s
    return s


def _clean_notify_text(val) -> str:
    """Collapse empty Excel-style commas / extra spaces for push body."""
    s = str(val or '').strip()
    if not s:
        return ''
    s = re.sub(r',{2,}', ', ', s)
    s = re.sub(r'\s+', ' ', s).strip(' ,')
    return s


def _build_task_notify_message(ev: dict) -> str:
    """Driver push body — generate (full) vs close (short)."""
    tid = _display_task_id(ev.get('task_id'))
    phone = _clean_notify_text(ev.get('phone')) or '—'
    name = _clean_notify_text(ev.get('patient_name') or ev.get('name')) or '—'

    if ev.get('event') == 'close':
        category = _clean_notify_text(ev.get('category')) or '—'
        completed = _clean_notify_text(ev.get('completed_date_time')) or '—'
        return (
            f'Task ID: {tid}, Phone no: {phone}, Name: {name}, '
            f'Task Category: {category}, CompletedDateTime: {completed}'
        )

    cli = _clean_notify_text(ev.get('cli')) or '—'
    pickup = _clean_notify_text(ev.get('pickup')) or '—'
    dest = _clean_notify_text(ev.get('destination')) or '—'
    return (
        f'Task ID: {tid}, Phone no: {phone} CLI: {cli}, '
        f'Name: {name}, Pickup: {pickup}, Destination: {dest}'
    )


def _send_task_event_notifications(events: list):
    """events: list of dicts with task fields + event ∈ {'generate','close'}.
    Best-effort — never raises."""
    if not events:
        return
    try:
        from services.notification_service import notify_user
        from services.push_notifications import get_user_id_for_driver
    except Exception:
        try:
            from notification_service import notify_user
            from push_notifications import get_user_id_for_driver
        except Exception as ie:
            logger.warning(f"task-event notify imports failed: {ie}")
            return
    for ev in events:
        try:
            _veh, drv = _match_vehicle_driver(ev.get('amb_reg_no'))
            if not drv:
                continue
            uid = get_user_id_for_driver(drv)
            if not uid:
                continue
            msg = _build_task_notify_message(ev)
            if ev['event'] == 'generate':
                title = 'Nayi Task Assign'
                ntype = 'info'
            else:  # close
                title = 'Task Complete'
                ntype = 'success'
            notify_user(uid, title, msg, notification_type=ntype)
        except Exception as e:
            logger.warning(f"task-event notify failed for {ev}: {e}")


# Legacy alias — dashboard normalize_task() keys -> DB (17 fields).
# Full 57-field report sync uses emergency_report_api_to_fields() in emg_tasks.
TASK_TO_EMG_MAP = {
    'task_id': 'task_id_ext',
    'patient_name': 'name',
    'phone': 'phone',
    'address': 'address',
    'ambulance': 'amb_reg_no',
    'status': 'status',
    'district': 'district_name',
    'tehsil': 'tehsil_name',
    'uc': 'uc_name',
    'facility_code': 'facility_code',
    'facility_name': 'facility_name',
    'request_from': 'request_from',
    'created_date': 'excel_created_date',
    'distance': 'distance_in_km',
    'location': 'location',
    'category': 'category',
    'request_for': 'request_for',
}


def _emg_row_to_task(row) -> dict:
    """Convert an EmergencyTaskRecord row back to normalize_task() dict shape
    so routes/templates work unchanged."""
    cd = row.excel_created_date
    if not cd and row.synced_at:
        cd = row.synced_at.strftime('%Y-%m-%d %H:%M:%S')
    return {
        'id': row.task_id_ext,
        'task_id': row.task_id_ext,
        'patient_name': row.name,
        'phone': row.phone,
        'address': row.address,
        'ambulance': row.amb_reg_no,
        'status': row.status,
        'status2': None,
        'district': row.district_name,
        'tehsil': row.tehsil_name,
        'uc': row.uc_name,
        'facility_code': row.facility_code,
        'facility_name': row.facility_name,
        'amb_id': None,
        'request_from': row.request_from,
        'is_transfer': None,
        'created_date': cd,
        'distance': _to_float(row.distance_in_km, None) if row.distance_in_km else None,
        'driver_name': None,
        'driver_cell': None,
        'location': row.location,
        'category': row.category,
        'request_for': row.request_for,
    }


def sync_emergency_report_to_db(account_id: int, items: list,
                                default_task_date=None) -> int:
    """Upsert Emergency Task Report rows — one row per task (Option B).

    Accepts raw getAmbulanceTaskReport dicts (57 fields). Keyed by
    (task_id_ext, task_date). Returns count upserted.
    """
    from models import EmergencyTaskRecord
    from app import db
    from datetime import date as _date
    from emg_tasks import (
        find_emergency_row, apply_api_fields_to_row, emergency_report_api_to_fields,
    )

    if not items:
        return 0
    try:
        existing = {
            r.task_id_ext: r
            for r in EmergencyTaskRecord.query.filter(
                EmergencyTaskRecord.task_id_ext.isnot(None),
                EmergencyTaskRecord.task_id_ext != '',
            ).all()
        }
        had_prior = bool(existing)
        try:
            from utils import pk_date
            today = pk_date()
        except Exception:
            today = _date.today()
        events = []
        now_dt = datetime.now()
        default_d = None
        if default_task_date:
            if isinstance(default_task_date, _date):
                default_d = default_task_date
            else:
                default_d = _parse_date_only(str(default_task_date))
        if default_d is None:
            default_d = today
        upserted = 0
        for raw in items:
            if not isinstance(raw, dict):
                continue
            fields = emergency_report_api_to_fields(raw)
            tid = str(
                fields.get('task_id_ext') or raw.get('TaskId') or raw.get('id') or ''
            ).strip()
            if not tid:
                continue
            fields['task_id_ext'] = tid
            cdt = _parse_ufone_datetime(fields.get('excel_created_date'))
            tdate = cdt.date() if cdt else default_d
            new_status = fields.get('status') or ''
            prior = existing.get(tid)
            is_new = prior is None
            if _NOTIFY_TASK_EVENTS and had_prior and tdate == today:
                notify_payload = {
                    'task_id': tid,
                    'amb_reg_no': fields.get('amb_reg_no'),
                    'patient_name': fields.get('name'),
                    'phone': fields.get('phone'),
                    'cli': fields.get('cli'),
                    'pickup': fields.get('address') or '',
                    'destination': fields.get('facility_name') or '',
                    'category': fields.get('category') or '',
                    'completed_date_time': fields.get('completed_date_time') or '',
                }
                if is_new:
                    events.append({**notify_payload, 'event': 'generate'})
                elif prior and (not _status_is_complete(prior.status)
                                and _status_is_complete(new_status)):
                    events.append({**notify_payload, 'event': 'close'})
            row = find_emergency_row(tid, tdate)
            if not row:
                row = EmergencyTaskRecord(
                    task_id_ext=tid, task_date=tdate, upload_date=tdate)
                db.session.add(row)
            apply_api_fields_to_row(row, fields, account_id, now_dt)
            existing[tid] = row
            upserted += 1
        db.session.commit()
        if events:
            try:
                _send_task_event_notifications(events)
            except Exception as ne:
                logger.warning(f"task-event notifications failed: {ne}")
        return upserted
    except Exception as e:
        db.session.rollback()
        logger.warning(f"sync_emergency_report_to_db failed (non-fatal): {e}")
        return 0


def _emg_db_rows_for_range(start_date: str, end_date: str) -> list:
    """Read emergency_task_record rows for a date range (unified excel+api)."""
    from models import EmergencyTaskRecord
    from datetime import date as _date
    try:
        sd = _parse_date_only(start_date) if start_date else None
        ed = _parse_date_only(end_date) if end_date else None
        if sd is None:
            sd = _date.today()
        if ed is None:
            ed = sd
        q = (EmergencyTaskRecord.query
             .filter(EmergencyTaskRecord.task_date >= sd)
             .filter(EmergencyTaskRecord.task_date <= ed))
        return q.all()
    except Exception as e:
        logger.warning(f"_emg_db_rows_for_range failed: {e}")
        return []


def _emg_latest_sync() -> Optional[datetime]:
    """Most recent synced_at from API sync (any task)."""
    from models import EmergencyTaskRecord
    try:
        r = (EmergencyTaskRecord.query
             .filter(EmergencyTaskRecord.synced_at.isnot(None))
             .order_by(EmergencyTaskRecord.synced_at.desc())
             .first())
        return r.synced_at if r else None
    except Exception:
        return None


# ── DB-first: Task detail + comments cache ───────────────────────────────────

# Task detail is heavy (76 fields) and rarely changes once a task is closed.
# Cache full detail + comments per (account, task) in ufone_task_detail_cache.
# First click → live fetch + cache. Subsequent clicks → instant DB read.
# Refresh (?live=1) → live fetch + re-cache. Writes invalidate the row.

def get_task_detail_cached(account_id: int, task_id, max_age_seconds: int = 3600):
    """Return (detail_dict, comments_list, synced_at) from DB cache, or (None, [], None).

    Closed tasks are considered fresh forever (status contains 'complete').
    Open tasks are fresh if synced_at < max_age_seconds old.
    """
    from models import UfoneTaskDetailCache
    try:
        row = UfoneTaskDetailCache.query.filter_by(
            account_id=account_id, task_id=str(task_id)).first()
        if not row:
            return None, [], None
        st = (row.task_status or '').lower()
        is_closed = ('complete' in st) or ('cancel' in st)
        if not is_closed and row.synced_at:
            age = (datetime.now() - row.synced_at).total_seconds()
            if age > max_age_seconds:
                return None, [], None  # stale for open tasks
        detail = json.loads(row.detail_json) if row.detail_json else None
        comments = json.loads(row.comments_json) if row.comments_json else []
        return detail, comments, row.synced_at
    except Exception as e:
        logger.warning(f"get_task_detail_cached failed: {e}")
        return None, [], None


def save_task_detail_cache(account_id: int, task_id, detail: dict,
                           comments: list, status: str = None):
    """Upsert full task detail + comments into ufone_task_detail_cache."""
    from models import UfoneTaskDetailCache
    from app import db
    try:
        row = UfoneTaskDetailCache.query.filter_by(
            account_id=account_id, task_id=str(task_id)).first()
        if not row:
            row = UfoneTaskDetailCache(
                account_id=account_id, task_id=str(task_id))
            db.session.add(row)
        row.detail_json = json.dumps(detail, default=str) if detail else None
        row.comments_json = json.dumps(comments, default=str) if comments else None
        row.task_status = status or (detail.get('Status') if detail else None)
        row.synced_at = datetime.now()
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.warning(f"save_task_detail_cache failed (non-fatal): {e}")


def invalidate_task_detail_cache(account_id: int, task_id):
    """Delete the cached detail+comments for a task (after a write)."""
    from models import UfoneTaskDetailCache
    from app import db
    try:
        row = UfoneTaskDetailCache.query.filter_by(
            account_id=account_id, task_id=str(task_id)).first()
        if row:
            db.session.delete(row)
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.warning(f"invalidate_task_detail_cache failed (non-fatal): {e}")


def _task_id_lookup_keys(task_id) -> list:
    """Numeric / PHF- prefixed variants for DB lookups."""
    s = str(task_id or '').strip()
    if not s:
        return []
    keys = [s]
    bare = s.upper().replace('PHF-', '').strip()
    if bare and bare != s:
        keys.append(bare)
        keys.append(f'PHF-{bare}')
    if not s.upper().startswith('PHF-') and s.isdigit():
        keys.append(f'PHF-{s}')
    # unique preserve order
    out = []
    seen = set()
    for k in keys:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def build_task_detail_from_db(account_id: int, task_id) -> dict:
    """Compose Task Detail popup fields from EMG + vehicle cache (no Ufone HTTP).

    Used in UFONE_BRIDGE_ONLY when Render cannot reach bpocops.
    """
    from models import EmergencyTaskRecord, UfoneTaskCache, UfoneVehicleCache

    keys = _task_id_lookup_keys(task_id)
    if not keys:
        return {}

    detail = {}

    # 1) Emergency report row (richest structured fields)
    try:
        emg = (EmergencyTaskRecord.query
               .filter(EmergencyTaskRecord.task_id_ext.in_(keys))
               .order_by(EmergencyTaskRecord.task_date.desc(),
                         EmergencyTaskRecord.id.desc())
               .first())
    except Exception:
        emg = None
    if emg:
        detail.update({
            'id': emg.task_id_ext,
            'TaskId': emg.task_id_ext,
            'RequestFrom': emg.request_from,
            'ReceivedBy': emg.received_by,
            'phone': emg.phone,
            'Phone': emg.phone,
            'CLI': emg.cli,
            'name': emg.name,
            'Name': emg.name,
            'husband': emg.husband,
            'address': emg.address,
            'Address': emg.address,
            'location': emg.location,
            'Location': emg.location,
            'HouseColor': emg.house_color,
            'DoorColor': emg.door_color,
            'NearestLandmark': emg.nearest_landmark,
            'EDD': emg.edd,
            'ClinicalDetails': emg.clinical_details,
            'district_name': emg.district_name,
            'tehsil_name': emg.tehsil_name,
            'uc_name': emg.uc_name,
            'Ambulance': emg.amb_reg_no,
            'ambRegNo': emg.amb_reg_no,
            'Status': emg.status,
            'facility_code': emg.facility_code,
            'FacilityCode': emg.facility_code,
            'facility_name': emg.facility_name,
            'FacilityName': emg.facility_name,
            'facilityType': emg.facility_type,
            'CD': emg.excel_created_date,
            'CreatedDate': emg.excel_created_date,
            'CreatedTime': emg.created_time,
            'Category': emg.category,
            'ClosingRemarks': emg.closing_remarks,
            'CallerName': emg.caller_name,
            'RequestFor': emg.request_for,
            'distanceInKM': emg.distance_in_km,
        })

    # 2) Task list cache / raw_json fill gaps
    try:
        trow = (UfoneTaskCache.query
                .filter(UfoneTaskCache.account_id == account_id,
                        UfoneTaskCache.task_id.in_(keys))
                .order_by(UfoneTaskCache.updated_at.desc())
                .first())
    except Exception:
        trow = None
    if trow:
        if trow.raw_json:
            try:
                raw = json.loads(trow.raw_json)
                if isinstance(raw, dict):
                    for k, v in raw.items():
                        if v is not None and v != '' and not detail.get(k):
                            detail[k] = v
            except Exception:
                pass
        fills = {
            'id': trow.task_id,
            'TaskId': trow.task_id,
            'name': trow.patient_name,
            'phone': trow.phone,
            'address': trow.address,
            'Ambulance': trow.ambulance_reg,
            'Status': trow.status,
            'district_name': trow.district,
            'tehsil_name': trow.tehsil,
            'facility_name': trow.facility,
            'RequestFrom': trow.request_from,
        }
        for k, v in fills.items():
            if v is not None and v != '' and not detail.get(k):
                detail[k] = v

    # 3) Driver from vehicle cache by ambulance reg
    amb = (detail.get('Ambulance') or detail.get('ambRegNo')
           or detail.get('amReg_No') or '')
    amb = str(amb).strip()
    if amb:
        try:
            vrow = (UfoneVehicleCache.query
                    .filter_by(account_id=account_id, reg_no=amb)
                    .first())
            if not vrow:
                # case-insensitive fallback
                vrow = (UfoneVehicleCache.query
                        .filter(UfoneVehicleCache.account_id == account_id,
                                UfoneVehicleCache.reg_no.ilike(amb))
                        .first())
            if vrow:
                if vrow.driver_name and not detail.get('Driver_Name'):
                    detail['Driver_Name'] = vrow.driver_name
                if vrow.driver_cell and not detail.get('Driver_Cell'):
                    detail['Driver_Cell'] = vrow.driver_cell
                    detail['MobNo'] = detail.get('MobNo') or vrow.driver_cell
        except Exception:
            pass

    return detail


# ── Background polling thread ────────────────────────────────────────────────

_poll_thread: Optional[threading.Thread] = None
_poll_thread_stop = threading.Event()
_POLL_INTERVAL = 60  # seconds between task polls (light today-only call)
_POLL_MAX_BACKOFF = 300  # cap at 5 min when Ufone keeps timing out
_POLL_AMBULANCE_INTERVAL = 600  # 10 min between heavy getAmbulanceList (1394 rows)
_POLL_EMG_SYNC_INTERVAL = 180  # 3 min between heavy getAmbulanceTaskReport syncs
_POLL_MAINTENANCE_INTERVAL = 1800  # 30 min between maintenance syncs

# Idle-aware polling: when nobody is actively viewing the Ufone hub, stretch
# the heavy intervals to cut load on the Ufone portal. Freshness is preserved
# whenever a user is active (any ufone_* request within IDLE_THRESHOLD).
# EMG stays at 5 min when idle so Task Generate/Close driver notifications
# are not delayed up to 15 min.
_IDLE_THRESHOLD = 900          # 15 min with no UI activity → considered idle
_IDLE_DASHBOARD_INTERVAL = 300  # 60s → 5 min when idle
_IDLE_AMBULANCE_INTERVAL = 1800  # 10 min → 30 min when idle
_IDLE_EMG_SYNC_INTERVAL = 300    # 3 min → 5 min when idle (notifications stay timely)
_last_ui_activity: float = 0.0


def note_ui_activity():
    """Record that a user just hit a Ufone page (called from before_request).
    Used by the poll loop to decide active vs idle cadence."""
    global _last_ui_activity
    _last_ui_activity = time.time()


def _is_idle(now: float) -> bool:
    return (now - _last_ui_activity) > _IDLE_THRESHOLD

# Per-account last-sync timestamps (epoch seconds) for the heavy calls so
# they decouple from the 60s light-poll cadence.
_last_ambulance_sync: dict[int, float] = {}
_last_emg_sync: dict[int, float] = {}
_last_maintenance_sync: dict[int, float] = {}


def _sync_emergency_report_live(account_id: int) -> bool:
    """Live-fetch today's all-district Emergency Task Report and persist to DB.
    Returns True on success. Uses poll session so UI is never blocked."""
    try:
        from datetime import date as _date
        today = _date.today().strftime("%Y-%m-%d")
        client = _get_client(account_id, purpose="poll")
        raw = client.get_emergency_tasks(
            start_date=today, end_date=today, district="", visit_page=False)
        raw = [r for r in (raw or []) if isinstance(r, dict)]
        sync_emergency_report_to_db(account_id, raw, default_task_date=today)
        return True
    except Exception as e:
        logger.warning(f"poll EMG sync for account {account_id} failed: {e}")
        return False


def _poll_loop(app):
    consecutive_failures = 0
    with app.app_context():
        while not _poll_thread_stop.is_set():
            from models import UfoneAccount
            cycle_ok = False
            now = time.time()
            idle = _is_idle(now)
            amb_interval = _IDLE_AMBULANCE_INTERVAL if idle else _POLL_AMBULANCE_INTERVAL
            emg_interval = _IDLE_EMG_SYNC_INTERVAL if idle else _POLL_EMG_SYNC_INTERVAL
            for acct in UfoneAccount.query.filter_by(is_active=True).all():
                try:
                    # Heavy ambulance sync — every 10 min (30 min when idle)
                    last_amb = _last_ambulance_sync.get(acct.id, 0.0)
                    if now - last_amb >= amb_interval:
                        fetch_live_positions(
                            acct.id, force=True, persist=True, for_poll=True)
                        _last_ambulance_sync[acct.id] = now
                    # Light today-only task dashboard — skip entirely when idle
                    # (the 3-min EMG sync below still keeps today's rows warm).
                    if not idle:
                        fetch_task_dashboard(
                            acct.id, force=True, persist=True, for_poll=True)
                    # Heavy EMG report sync — every 3 min (5 min when idle)
                    last_emg = _last_emg_sync.get(acct.id, 0.0)
                    if now - last_emg >= emg_interval:
                        if _sync_emergency_report_live(acct.id):
                            _last_emg_sync[acct.id] = now
                    # Maintenance sync — every 30 min per account
                    last_mnt = _last_maintenance_sync.get(acct.id, 0.0)
                    if now - last_mnt >= _POLL_MAINTENANCE_INTERVAL:
                        try:
                            fetch_maintenance(acct.id, force=True, for_poll=True)
                            _last_maintenance_sync[acct.id] = now
                        except Exception as me:
                            logger.debug(f"maintenance sync failed: {me}")
                    cycle_ok = True
                except Exception as e:
                    logger.error(f"ufone poll account {acct.id}: {e}")
            # Exponential backoff jab Ufone timeout de raha ho
            if cycle_ok:
                consecutive_failures = 0
                wait = _IDLE_DASHBOARD_INTERVAL if idle else _POLL_INTERVAL
            else:
                consecutive_failures += 1
                wait = min(_POLL_INTERVAL * (2 ** consecutive_failures),
                           _POLL_MAX_BACKOFF)
                logger.warning(
                    f"ufone poll: {consecutive_failures} failed cycle(s), "
                    f"next retry in {wait}s")
            _poll_thread_stop.wait(wait)


def start_polling(app):
    global _poll_thread
    if bridge_only_mode():
        logger.info(
            "Ufone polling skipped (UFONE_BRIDGE_ONLY=1) — PK VPS bridge owns sync")
        return
    if _poll_thread and _poll_thread.is_alive():
        return
    _poll_thread_stop.clear()
    _poll_thread = threading.Thread(target=_poll_loop, args=(app,),
                                    daemon=True, name='ufone-poll')
    _poll_thread.start()
    logger.info("Ufone polling thread started")


def stop_polling():
    _poll_thread_stop.set()


def is_polling() -> bool:
    return bool(_poll_thread and _poll_thread.is_alive()
                and not _poll_thread_stop.is_set())


# ── Account CRUD ─────────────────────────────────────────────────────────────

def create_account(label: str, username: str, password: str,
                   role: str = 'Operator', app=None) -> int:
    from models import UfoneAccount
    from app import db
    acct = UfoneAccount(
        label=label or 'Default',
        username=username,
        password_enc=encrypt_password(password, app),
        role=role,
        is_active=True,
    )
    db.session.add(acct)
    db.session.commit()
    return acct.id


def update_account(account_id: int, label: str = None, username: str = None,
                   password: str = None, role: str = None,
                   is_active: bool = None, app=None):
    from models import UfoneAccount
    from app import db
    acct = UfoneAccount.query.get(account_id)
    if not acct:
        raise RuntimeError(f"Account {account_id} not found")
    if label is not None:
        acct.label = label
    if username is not None:
        acct.username = username
    if password:
        acct.password_enc = encrypt_password(password, app)
    if role is not None:
        acct.role = role
    if is_active is not None:
        acct.is_active = is_active
    db.session.commit()
    _reset_client(account_id)


def delete_account(account_id: int):
    from models import (UfoneAccount, UfoneVehicleCache,
                        UfoneTaskCache, UfoneMaintenanceCache)
    from app import db
    UfoneVehicleCache.query.filter_by(account_id=account_id).delete()
    UfoneTaskCache.query.filter_by(account_id=account_id).delete()
    UfoneMaintenanceCache.query.filter_by(account_id=account_id).delete()
    UfoneAccount.query.filter_by(id=account_id).delete()
    db.session.commit()
    _reset_client(account_id)
    # purge caches
    with _live_cache_lock:
        _live_cache.pop(account_id, None)
    with _task_cache_lock:
        _task_cache.pop(account_id, None)


def test_connection(username: str, password: str, app=None) -> tuple[bool, str]:
    """Test login without saving. Returns (success, message)."""
    from services.ufone_api_client import UfoneClient
    try:
        c = UfoneClient(username, password, session_key=f"test_{username}")
        c.connect(reuse_session=False)
        amb = c.get_ambulance_list()
        return True, f"OK - {len(amb)} ambulances"
    except Exception as e:
        return False, str(e)[:200]
