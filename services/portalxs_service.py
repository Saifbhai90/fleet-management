"""
PortalXS Service Layer
======================
Wraps the SOAP client with:
- Fernet password encryption (reuse tracker_automation crypto)
- Thread-safe in-memory cache for live positions
- Background polling thread (30s interval)
- DB persistence for vehicle mappings + alerts
- Auto-relogin on session expiry
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

logger = logging.getLogger(__name__)

# ── Password helpers (reuse Fernet from tracker_automation) ──────────────────

def _fernet(app=None):
    from cryptography.fernet import Fernet
    import hashlib, base64
    if app is None:
        from flask import current_app as _app
        secret = _app.config.get('SECRET_KEY')
    else:
        secret = app.config.get('SECRET_KEY')
    if not secret:
        # app.py enforces SECRET_KEY at boot — this is a hard failure, never silently
        # fall back to a known key (would make all encrypted passwords crackable).
        raise RuntimeError("SECRET_KEY is not configured; cannot encrypt/decrypt PortalXS passwords")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def encrypt_password(plain: str, app=None) -> str:
    return _fernet(app).encrypt(plain.encode()).decode()


def decrypt_password(enc: str, app=None) -> str:
    try:
        return _fernet(app).decrypt(enc.encode()).decode()
    except Exception:
        return ''


# ── Landmark helper ──────────────────────────────────────────────────────────

def clean_landmark(raw: str) -> str:
    if not raw:
        return ''
    for prefix in ('0||', '1||', '0 ', '1 '):
        if raw.startswith(prefix):
            return raw[len(prefix):].strip()
    return raw.strip()


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


def _parse_rdt(rdt_str: str) -> Optional[datetime]:
    if not rdt_str:
        return None
    for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S'):
        try:
            return datetime.strptime(rdt_str, fmt)
        except ValueError:
            continue
    return None


def normalize_vehicle(v: dict) -> dict:
    """Normalise a PortalXS vehicle position dict for frontend use."""
    return {
        'RegNo': v.get('RegNo', ''),
        'LAT': _to_float(v.get('LAT')),
        'LON': _to_float(v.get('LON')),
        'Speed': _to_float(v.get('Speed')),
        'Direction': _to_float(v.get('Direction')),
        'Reason': v.get('Reason', ''),
        'LandMark': clean_landmark(v.get('LandMark', '')),
        'VehicleStatus': v.get('VehicleStatus', 'Unknown'),
        'IgnitionStatus': v.get('IgnitionStatus', ''),
        'CurrentStatus': v.get('CurrentStatus', ''),
        'GroupName': v.get('GroupName', ''),
        'RDT': v.get('RDT', ''),
        'TotalMileage': _to_float(v.get('TotalMileage')),
        'TotalTrips': _to_int(v.get('TotalTrips')),
        'MaxSpeed': _to_float(v.get('MaxSpeed')),
        'MakeAndModel': v.get('MakeAndModel', ''),
        'DriverInfo': v.get('DriverInfo', ''),
    }


def normalize_history_point(p: dict) -> dict:
    return {
        'RecordDateTime': p.get('RecordDateTime', ''),
        'LAT': _to_float(p.get('LAT')),
        'LON': _to_float(p.get('LON')),
        'Speed': _to_float(p.get('Speed')),
        'Reason': p.get('Reason', ''),
        'LandMark': clean_landmark(p.get('LandMark', '')),
        'Direction': _to_float(p.get('Direction')),
    }


def normalize_trip(t: dict) -> dict:
    return {
        'IGON_RDT': t.get('IGON_RDT', ''),
        'IGON_LAT': _to_float(t.get('IGON_LAT')),
        'IGON_LON': _to_float(t.get('IGON_LON')),
        'IGON_LandMark': clean_landmark(t.get('IGON_LandMark', '')),
        'IGOFF_RDT': t.get('IGOFF_RDT', ''),
        'IGOFF_LAT': _to_float(t.get('IGOFF_LAT')),
        'IGOFF_LON': _to_float(t.get('IGOFF_LON')),
        'IGOFF_LandMark': clean_landmark(t.get('IGOFF_LandMark', '')),
        'Mileage': _to_float(t.get('Mileage')),
        'TravelTimeS': t.get('TravelTimeS', ''),
        'MaxSpeed': _to_float(t.get('MaxSpeed')),
        'AvgSpeed': _to_float(t.get('AvgSpeed')),
        'TripStatus': t.get('TripStatus', ''),
    }


def normalize_fleet_report(r: dict) -> dict:
    fuel_str = r.get('FuelConsumption', '0')
    fuel_val = 0.0
    if isinstance(fuel_str, str):
        fuel_val = _to_float(fuel_str.replace('ltr', '').strip())
    return {
        'RegNo': r.get('RegNo', ''),
        'VehicleScore': _to_float(r.get('VehicleScore', '0')),
        'FuelConsumption': fuel_val,
        'Trips': _to_int(r.get('Trips')),
        'Duration': _to_int(r.get('Duration')),
        'Distance': _to_float(r.get('Distance')),
        'Alerts': _to_int(r.get('Alerts')),
    }


def _pick_str(m: dict, *names) -> str:
    if not isinstance(m, dict):
        return ''
    lower = {str(k).lower(): v for k, v in m.items()}
    for n in names:
        v = m.get(n)
        if v in (None, ''):
            v = lower.get(str(n).lower())
        if v not in (None, ''):
            return str(v).strip()
    return ''


def _split_date_time(val) -> tuple[str, str]:
    s = str(val or '').strip()
    if not s:
        return '', ''
    s = s.replace('T', ' ')
    parts = s.split()
    if len(parts) >= 2:
        return parts[0], parts[1][:8]
    if len(s) >= 10 and s[4] == '-' and s[7] == '-':
        return s[:10], ''
    return s, ''


def normalize_mileage_report(m: dict, query_from: str = '', query_to: str = '') -> dict:
    """Normalize a mileage report row from PortalXS API.

    PortalXS field names vary (DateFrom vs fdt vs StartDate). Empty date/time
    columns fall back to the requested query range (00:00 / 23:59).
    """
    date_from = _pick_str(m, 'DateFrom', 'dateFrom', 'FromDate', 'StartDate', 'fdt', 'FDT', 'IgnOnDate', 'StartDT')
    time_from = _pick_str(m, 'TimeFrom', 'timeFrom', 'FromTime', 'StartTime', 'IgnOnTime')
    date_to = _pick_str(m, 'DateTo', 'dateTo', 'ToDate', 'EndDate', 'tdt', 'TDT', 'IgnOffDate', 'EndDT')
    time_to = _pick_str(m, 'TimeTo', 'timeTo', 'ToTime', 'EndTime', 'IgnOffTime')

    if date_from and not time_from:
        d, t = _split_date_time(date_from)
        date_from = d or date_from
        time_from = t or time_from
    if date_to and not time_to:
        d, t = _split_date_time(date_to)
        date_to = d or date_to
        time_to = t or time_to

    q_from = (query_from or '')[:10]
    q_to = (query_to or '')[:10]
    if not date_from and q_from:
        date_from = q_from
        time_from = time_from or '00:00:00'
    if not date_to and q_to:
        date_to = q_to
        time_to = time_to or '23:59:59'

    return {
        'ID': _pick_str(m, 'ID', 'id') or '',
        'DateFrom': date_from,
        'TimeFrom': time_from,
        'DateTo': date_to,
        'TimeTo': time_to,
        'Mileage': _to_float(m.get('Mileage', m.get('Distance', m.get('mileage', 0)))),
        'PToP': _to_float(m.get('PToP', m.get('PTOP', m.get('PtoP', m.get('ptop', 0))))),
    }


def normalize_trend(t: dict) -> dict:
    return {
        'RDT': t.get('RDT', ''),
        'Mileage': _to_float(t.get('Mileage')),
        'TravelTimeH': _to_float(t.get('TravelTimeH')),
        'Alerts': _to_int(t.get('Alerts')),
    }


# ── In-memory live position cache ────────────────────────────────────────────

_live_cache: dict[str, list[dict]] = {}  # account_id -> list of normalised vehicles
_live_cache_lock = threading.Lock()
_live_cache_ts: dict[str, float] = {}     # account_id -> timestamp of last refresh
_poll_thread: Optional[threading.Thread] = None
_poll_thread_stop = threading.Event()


def get_cached_positions(account_id: int) -> list[dict]:
    with _live_cache_lock:
        return _live_cache.get(str(account_id), [])


def get_cache_age(account_id: int) -> Optional[float]:
    key = str(account_id)
    with _live_cache_lock:
        if key in _live_cache_ts:
            return time.time() - _live_cache_ts[key]
    return None


def _set_cached_positions(account_id: int, vehicles: list[dict]):
    key = str(account_id)
    with _live_cache_lock:
        _live_cache[key] = vehicles
        _live_cache_ts[key] = time.time()


# ── Client management ────────────────────────────────────────────────────────

_clients: dict[int, 'PortalXSClient'] = {}
_clients_lock = threading.Lock()


def _get_client(account_id: int) -> 'PortalXSClient':
    """Get or create a PortalXSClient for the given account."""
    from services.portalxs_soap_client import PortalXSClient
    from models import PortalXSAccount
    from app import db

    with _clients_lock:
        if account_id in _clients:
            return _clients[account_id]

    acct = db.session.get(PortalXSAccount, account_id)
    if not acct:
        raise ValueError(f"PortalXSAccount {account_id} not found")

    password = decrypt_password(acct.password_enc)
    client = PortalXSClient(acct.username, password, session_key=f"acct{account_id}")
    client.connect()
    acct.last_connected = datetime.now()
    acct.last_error = None
    db.session.commit()

    with _clients_lock:
        _clients[account_id] = client
    return client


def _reset_client(account_id: int):
    with _clients_lock:
        _clients.pop(account_id, None)


# ── Public API ───────────────────────────────────────────────────────────────

def fetch_live_positions(account_id: int, force: bool = False) -> list[dict]:
    """Fetch live positions from PortalXS, update DB cache, return vehicles."""
    from models import PortalXSAccount, PortalXSVehicleMapping
    from app import db

    # Use cache if fresh (< 25 seconds old)
    age = get_cache_age(account_id)
    if not force and age is not None and age < 25:
        return get_cached_positions(account_id)

    try:
        client = _get_client(account_id)
        raw_vehicles = client.get_vehicles()
        if not isinstance(raw_vehicles, list):
            raw_vehicles = []

        vehicles = [normalize_vehicle(v) for v in raw_vehicles]
        _set_cached_positions(account_id, vehicles)

        # Update DB mappings — preload all mappings in ONE query (not N queries)
        acct = db.session.get(PortalXSAccount, account_id)
        if acct:
            acct.vehicle_count = len(vehicles)
            acct.last_error = None

        existing = {
            m.portalxs_regno: m
            for m in PortalXSVehicleMapping.query.filter_by(account_id=account_id).all()
        }
        for v in vehicles:
            mapping = existing.get(v['RegNo'])
            if not mapping:
                mapping = PortalXSVehicleMapping(
                    account_id=account_id,
                    portalxs_regno=v['RegNo'],
                )
                db.session.add(mapping)
                existing[v['RegNo']] = mapping

            mapping.group_name = v.get('GroupName', '')
            mapping.make_model = v.get('MakeAndModel', '')
            mapping.last_lat = v['LAT'] or None
            mapping.last_lon = v['LON'] or None
            mapping.last_speed = v['Speed'] or None
            mapping.last_status = v.get('VehicleStatus', '')
            mapping.last_rdt = _parse_rdt(v.get('RDT', ''))
            mapping.last_ignition = v.get('IgnitionStatus', '')
            mapping.last_landmark = v.get('LandMark', '')
            mapping.last_total_mileage = v.get('TotalMileage') or None
            mapping.last_total_trips = v.get('TotalTrips') or None
            mapping.last_max_speed = v.get('MaxSpeed') or None

        db.session.commit()
        return vehicles

    except Exception as e:
        err_text = str(e)
        if '503' in err_text or 'service is unavailable' in err_text.lower():
            logger.warning(f"PortalXS fetch_live_positions unavailable: {err_text[:200]}")
        else:
            logger.error(f"PortalXS fetch_live_positions error: {e}")
        _reset_client(account_id)
        db.session.rollback()
        try:
            acct = db.session.get(PortalXSAccount, account_id)
            if acct:
                acct.last_error = str(e)[:500]
                db.session.commit()
        except Exception:
            db.session.rollback()
        # Return stale cache if available
        cached = get_cached_positions(account_id)
        if cached:
            return cached
        raise


def fetch_history(account_id: int, regno: str, from_dt: str, to_dt: str) -> list[dict]:
    """Fetch vehicle history points."""
    client = _get_client(account_id)
    raw = client.get_history(regno, from_dt, to_dt)
    if not isinstance(raw, list):
        return []
    return [normalize_history_point(p) for p in raw]


def fetch_trips(account_id: int, regno: str, from_dt: str, to_dt: str) -> list[dict]:
    """Fetch vehicle trips."""
    client = _get_client(account_id)
    raw = client.get_trips(regno, from_dt, to_dt)
    if not isinstance(raw, list):
        return []
    return [normalize_trip(t) for t in raw]


def fetch_fleet_report(account_id: int, regno: str, from_dt: str, to_dt: str) -> list[dict]:
    """Fetch fleet report for a vehicle."""
    client = _get_client(account_id)
    raw = client.get_fleet_report(regno, from_dt, to_dt)
    if not isinstance(raw, list):
        return []
    return [normalize_fleet_report(r) for r in raw]


# ── Fleet report: parallel bulk fetch + short TTL cache ──────────────────────

_fleet_report_cache: dict[tuple, tuple[float, list]] = {}
_fleet_report_cache_lock = threading.Lock()
FLEET_REPORT_CACHE_TTL = 300  # 5 minutes
FLEET_REPORT_MAX_WORKERS = 8


def fetch_fleet_report_bulk(account_id: int, regnos: list[str], from_dt: str, to_dt: str) -> tuple[list[dict], Optional[str]]:
    """Fetch fleet reports for many vehicles in PARALLEL with a 5-min cache.
    Returns (reports, error). Partial results are returned even if some vehicles fail.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    cache_key = (account_id, tuple(sorted(regnos)), from_dt, to_dt)
    now = time.time()
    with _fleet_report_cache_lock:
        hit = _fleet_report_cache.get(cache_key)
        if hit and (now - hit[0]) < FLEET_REPORT_CACHE_TTL:
            return hit[1], None

    # Ensure the client is connected ONCE before parallel calls
    # (avoids N threads racing to login simultaneously)
    _get_client(account_id)

    reports: list[dict] = []
    errors: list[str] = []

    def _one(regno):
        client = _get_client(account_id)
        raw = client.get_fleet_report(regno, from_dt, to_dt)
        if not isinstance(raw, list):
            return []
        return [normalize_fleet_report(r) for r in raw]

    with ThreadPoolExecutor(max_workers=FLEET_REPORT_MAX_WORKERS) as pool:
        futures = {pool.submit(_one, r): r for r in regnos}
        for fut in as_completed(futures):
            regno = futures[fut]
            try:
                for item in fut.result():
                    item['_regno'] = regno
                    reports.append(item)
            except Exception as e:
                errors.append(f"{regno}: {str(e)[:120]}")

    error = None
    if errors:
        error = f"{len(errors)} vehicle(s) failed — " + "; ".join(errors[:3])

    # Cache only fully/partially successful results (something to show)
    if reports:
        with _fleet_report_cache_lock:
            _fleet_report_cache[cache_key] = (now, reports)
            # Evict stale entries to keep memory bounded
            for k in [k for k, (ts, _) in _fleet_report_cache.items() if (now - ts) > FLEET_REPORT_CACHE_TTL * 2]:
                _fleet_report_cache.pop(k, None)

    return reports, error


def fetch_trends(account_id: int, regno: str, from_dt: str, to_dt: str) -> list[dict]:
    """Fetch daily trends for a vehicle."""
    client = _get_client(account_id)
    raw = client.get_trends(regno, from_dt, to_dt)
    if not isinstance(raw, list):
        return []
    return [normalize_trend(t) for t in raw]


def fetch_mileage(account_id: int, regno: str, from_dt: str, to_dt: str) -> dict:
    """Fetch mileage summary."""
    client = _get_client(account_id)
    raw = client.get_mileage(regno, from_dt, to_dt)
    if isinstance(raw, list) and raw:
        return raw[0] if isinstance(raw[0], dict) else {}
    if isinstance(raw, dict):
        return raw
    return {}


def _query_dates_from_soap(from_dt: str, to_dt: str):
    fd = (from_dt or '')[:10]
    td = (to_dt or '')[:10]
    qf = datetime.strptime(fd, '%Y-%m-%d').date() if fd else None
    qt = datetime.strptime(td, '%Y-%m-%d').date() if td else None
    return qf, qt


def mileage_row_from_cache(row) -> dict:
    return {
        'ID': row.id,
        '_regno': row.regno,
        'vehicle_no': row.vehicle_no or row.regno,
        'DateFrom': row.date_from or '',
        'TimeFrom': row.time_from or '',
        'DateTo': row.date_to or '',
        'TimeTo': row.time_to or '',
        'Mileage': float(row.mileage or 0),
        'PToP': float(row.ptop or 0),
        'source': 'db',
    }


def list_mileage_cache(account_id: int, from_dt: str, to_dt: str) -> list[dict]:
    from models import PortalXSMileageCache
    qf, qt = _query_dates_from_soap(from_dt, to_dt)
    if not qf or not qt:
        return []
    rows = (
        PortalXSMileageCache.query
        .filter_by(account_id=account_id, query_from=qf, query_to=qt)
        .order_by(PortalXSMileageCache.regno.asc())
        .all()
    )
    return [mileage_row_from_cache(r) for r in rows]


def missing_mileage_regnos(account_id: int, regnos: list[str], from_dt: str, to_dt: str) -> list[str]:
    from models import PortalXSMileageCache
    qf, qt = _query_dates_from_soap(from_dt, to_dt)
    if not qf or not qt:
        return list(regnos)
    have = {
        r[0] for r in PortalXSMileageCache.query.filter_by(
            account_id=account_id, query_from=qf, query_to=qt
        ).with_entities(PortalXSMileageCache.regno).all()
    }
    return [r for r in regnos if r not in have]


def clear_mileage_cache_range(account_id: int, from_dt: str, to_dt: str) -> int:
    from models import db, PortalXSMileageCache
    qf, qt = _query_dates_from_soap(from_dt, to_dt)
    if not qf or not qt:
        return 0
    n = PortalXSMileageCache.query.filter_by(
        account_id=account_id, query_from=qf, query_to=qt
    ).delete(synchronize_session=False)
    db.session.commit()
    return n


def fetch_and_store_one_mileage(account_id: int, regno: str, from_dt: str, to_dt: str, vehicle_no: str = '') -> dict:
    """Fetch one vehicle from PortalXS and upsert into DB cache."""
    from models import db, PortalXSMileageCache
    from utils import pk_now

    qf, qt = _query_dates_from_soap(from_dt, to_dt)
    client = _get_client(account_id)
    raw = client.get_mileage(regno, from_dt, to_dt)
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list) or not raw:
        item = normalize_mileage_report({}, query_from=from_dt, query_to=to_dt)
    else:
        # Combine numeric totals if API returns multiple slices; keep first date fields.
        first = normalize_mileage_report(raw[0] if isinstance(raw[0], dict) else {}, query_from=from_dt, query_to=to_dt)
        miles = 0.0
        ptop = 0.0
        for chunk in raw:
            if not isinstance(chunk, dict):
                continue
            n = normalize_mileage_report(chunk, query_from=from_dt, query_to=to_dt)
            miles += float(n.get('Mileage') or 0)
            ptop += float(n.get('PToP') or 0)
            if not first.get('DateFrom') and n.get('DateFrom'):
                first = n
        item = dict(first)
        item['Mileage'] = miles or first.get('Mileage') or 0
        item['PToP'] = ptop or first.get('PToP') or 0

    row = PortalXSMileageCache.query.filter_by(
        account_id=account_id, query_from=qf, query_to=qt, regno=regno
    ).first()
    if not row:
        row = PortalXSMileageCache(
            account_id=account_id, query_from=qf, query_to=qt, regno=regno
        )
        db.session.add(row)
    row.vehicle_no = vehicle_no or regno
    row.date_from = item.get('DateFrom') or (from_dt[:10] if from_dt else '')
    row.time_from = item.get('TimeFrom') or '00:00:00'
    row.date_to = item.get('DateTo') or (to_dt[:10] if to_dt else '')
    row.time_to = item.get('TimeTo') or '23:59:59'
    row.mileage = item.get('Mileage') or 0
    row.ptop = item.get('PToP') or 0
    row.fetched_at = pk_now()
    db.session.commit()
    out = mileage_row_from_cache(row)
    out['source'] = 'portalxs'
    return out


def store_mileage_stub(account_id: int, regno: str, from_dt: str, to_dt: str, vehicle_no: str = '', error: str = '') -> dict:
    """Save a placeholder so progressive fetch can skip a failed vehicle."""
    from models import db, PortalXSMileageCache
    from utils import pk_now
    qf, qt = _query_dates_from_soap(from_dt, to_dt)
    row = PortalXSMileageCache.query.filter_by(
        account_id=account_id, query_from=qf, query_to=qt, regno=regno
    ).first()
    if not row:
        row = PortalXSMileageCache(
            account_id=account_id, query_from=qf, query_to=qt, regno=regno
        )
        db.session.add(row)
    row.vehicle_no = vehicle_no or regno
    row.date_from = (from_dt or '')[:10]
    row.time_from = '00:00:00'
    row.date_to = (to_dt or '')[:10]
    row.time_to = '23:59:59'
    row.mileage = 0
    row.ptop = 0
    row.fetched_at = pk_now()
    db.session.commit()
    out = mileage_row_from_cache(row)
    out['source'] = 'error'
    out['error'] = error
    return out


# ── Mileage report: parallel bulk fetch + short TTL cache ─────────────────────

_mileage_report_cache: dict[tuple, tuple[float, list]] = {}
_mileage_report_cache_lock = threading.Lock()
MILEAGE_REPORT_CACHE_TTL = 300  # 5 minutes
# Stay under Render/proxy ~30s request timeout while PortalXS SOAP is slow.
MILEAGE_REPORT_DEADLINE_SEC = 22


def fetch_mileage_report_bulk(account_id: int, regnos: list[str], from_dt: str, to_dt: str) -> tuple[list[dict], Optional[str]]:
    """Fetch mileage report for many vehicles in PARALLEL via ConnectApp_GetMileageReport.
    Returns (rows, error). Each row gets _regno appended.
    Stops after MILEAGE_REPORT_DEADLINE_SEC so the HTTP worker is not killed (502)."""
    from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeout

    cache_key = (account_id, tuple(sorted(regnos)), from_dt, to_dt)
    now = time.time()
    with _mileage_report_cache_lock:
        hit = _mileage_report_cache.get(cache_key)
        if hit and (now - hit[0]) < MILEAGE_REPORT_CACHE_TTL:
            return hit[1], None

    _get_client(account_id)  # connect once before parallel calls

    rows: list[dict] = []
    errors: list[str] = []
    seq = 0
    done = 0

    def _one(regno):
        client = _get_client(account_id)
        raw = client.get_mileage(regno, from_dt, to_dt)
        if isinstance(raw, dict):
            raw = [raw]
        if not isinstance(raw, list):
            return []
        return [normalize_mileage_report(m, query_from=from_dt, query_to=to_dt) for m in raw if isinstance(m, dict)]

    pool = ThreadPoolExecutor(max_workers=min(4, FLEET_REPORT_MAX_WORKERS))
    try:
        futures = {pool.submit(_one, r): r for r in regnos}
        try:
            for fut in as_completed(futures, timeout=MILEAGE_REPORT_DEADLINE_SEC):
                regno = futures[fut]
                done += 1
                try:
                    for item in fut.result():
                        seq += 1
                        row = dict(item)
                        if not row.get('ID'):
                            row['ID'] = seq
                        row['_regno'] = regno
                        rows.append(row)
                except Exception as e:
                    errors.append(f"{regno}: {str(e)[:120]}")
        except FuturesTimeout:
            pass
        for fut in futures:
            if not fut.done():
                fut.cancel()
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    rows.sort(key=lambda x: (x.get('DateFrom', ''), x.get('TimeFrom', '')), reverse=True)

    error = None
    unfinished = max(0, len(regnos) - done)
    if unfinished:
        error = (
            f'PortalXS slow — {done}/{len(regnos)} vehicles loaded before timeout. '
            'Generate dobara dabayein (cache fill hota rahega) ya chhoti date range use karein.'
        )
    if errors:
        fail_bit = f"{len(errors)} vehicle(s) failed — " + "; ".join(errors[:3])
        error = (error + ' ' + fail_bit) if error else fail_bit

    if rows and unfinished == 0:
        with _mileage_report_cache_lock:
            _mileage_report_cache[cache_key] = (now, rows)
            for k in [k for k, (ts, _) in _mileage_report_cache.items() if (now - ts) > MILEAGE_REPORT_CACHE_TTL * 2]:
                _mileage_report_cache.pop(k, None)

    return rows, error


ALERT_CACHE_MAX_ROWS = 500  # per account


def fetch_alerts(account_id: int) -> list[dict]:
    """Fetch alerts; insert only NEW ones into cache (no delete-all churn).
    Alert history is preserved up to ALERT_CACHE_MAX_ROWS per account."""
    from models import PortalXSAlertCache
    from app import db

    client = _get_client(account_id)
    raw = client.get_alerts()
    if not isinstance(raw, list):
        raw = []

    # Existing alert keys (regno + type + time) to dedupe against
    existing_keys = {
        (c.regno or '', c.alert_type or '', c.alert_time.isoformat() if c.alert_time else '')
        for c in PortalXSAlertCache.query.filter_by(account_id=account_id)
        .with_entities(PortalXSAlertCache.regno, PortalXSAlertCache.alert_type, PortalXSAlertCache.alert_time)
        .all()
    }

    alerts = []
    inserted = 0
    for a in raw:
        if not isinstance(a, dict):
            continue
        regno = a.get('RegNo', a.get('regNo', ''))
        alert_type = a.get('AlertType', a.get('Type', ''))
        alert_msg = a.get('AlertMsg', a.get('Message', str(a)))
        alert_time_str = a.get('RDT', a.get('AlertTime', a.get('DateTime', '')))
        alert_time = _parse_rdt(alert_time_str) if alert_time_str else None

        key = (regno or '', alert_type or '', alert_time.isoformat() if alert_time else '')
        if key not in existing_keys:
            db.session.add(PortalXSAlertCache(
                account_id=account_id,
                regno=regno,
                alert_type=alert_type,
                alert_msg=alert_msg,
                alert_time=alert_time,
                severity=a.get('Severity', ''),
                raw_json=json.dumps(a, ensure_ascii=False),
            ))
            existing_keys.add(key)
            inserted += 1

        alerts.append({
            'regno': regno,
            'alert_type': alert_type,
            'alert_msg': alert_msg,
            'alert_time': alert_time_str,
            'severity': a.get('Severity', ''),
        })

    if inserted:
        db.session.commit()
        # Trim oldest rows beyond cap
        ids_to_keep = [r.id for r in PortalXSAlertCache.query.filter_by(account_id=account_id)
                       .order_by(PortalXSAlertCache.created_at.desc())
                       .with_entities(PortalXSAlertCache.id)
                       .limit(ALERT_CACHE_MAX_ROWS).all()]
        if ids_to_keep:
            deleted = PortalXSAlertCache.query.filter(
                PortalXSAlertCache.account_id == account_id,
                ~PortalXSAlertCache.id.in_(ids_to_keep)
            ).delete(synchronize_session=False)
            if deleted:
                db.session.commit()
    return alerts


def fetch_geofences(account_id: int) -> list[dict]:
    client = _get_client(account_id)
    raw = client.get_geofences()
    if not isinstance(raw, list):
        return []
    return raw


# ── Background polling thread ────────────────────────────────────────────────

def _poll_loop(app):
    """Background thread: poll all active accounts every 30 seconds."""
    with app.app_context():
        from app import db
        from models import PortalXSAccount
        while not _poll_thread_stop.is_set():
            try:
                accounts = PortalXSAccount.query.filter_by(is_active=True).all()
                for acct in accounts:
                    try:
                        fetch_live_positions(acct.id, force=True)
                        logger.info(f"[PortalXS] Polled account {acct.id} ({acct.label})")
                    except Exception as e:
                        db.session.rollback()
                        logger.error(f"[PortalXS] Poll error for account {acct.id}: {e}")
            except Exception as e:
                db.session.rollback()
                logger.error(f"[PortalXS] Poll loop error: {e}")
            _poll_thread_stop.wait(30)


def start_polling(app):
    """Start the background polling thread (call once at app startup)."""
    global _poll_thread
    if _poll_thread and _poll_thread.is_alive():
        return
    _poll_thread_stop.clear()
    _poll_thread = threading.Thread(target=_poll_loop, args=(app,), daemon=True, name='portalxs-poll')
    _poll_thread.start()
    logger.info("[PortalXS] Background polling thread started")


def stop_polling():
    _poll_thread_stop.set()


def is_polling() -> bool:
    """True if the background polling thread is currently running."""
    return bool(_poll_thread and _poll_thread.is_alive() and not _poll_thread_stop.is_set())


# ── Account management ───────────────────────────────────────────────────────

def create_account(label: str, username: str, password: str, app=None) -> int:
    """Create a new PortalXS account and return its ID."""
    from models import PortalXSAccount
    from app import db
    acct = PortalXSAccount(
        label=label,
        username=username,
        password_enc=encrypt_password(password, app),
    )
    db.session.add(acct)
    db.session.commit()
    return acct.id


def update_account(account_id: int, label: str = None, username: str = None,
                   password: str = None, is_active: bool = None, app=None):
    from models import PortalXSAccount
    from app import db
    acct = db.session.get(PortalXSAccount, account_id)
    if not acct:
        raise ValueError("Account not found")
    if label is not None:
        acct.label = label
    if username is not None:
        acct.username = username
    if password:
        acct.password_enc = encrypt_password(password, app)
    if is_active is not None:
        acct.is_active = is_active
    db.session.commit()
    _reset_client(account_id)


def delete_account(account_id: int):
    from models import PortalXSAccount, PortalXSVehicleMapping, PortalXSAlertCache
    from app import db
    PortalXSVehicleMapping.query.filter_by(account_id=account_id).delete()
    PortalXSAlertCache.query.filter_by(account_id=account_id).delete()
    PortalXSAccount.query.filter_by(id=account_id).delete()
    db.session.commit()
    _reset_client(account_id)


def test_connection(username: str, password: str) -> dict:
    """Test PortalXS credentials without saving. Returns {success, vehicle_count, error}."""
    from services.portalxs_soap_client import PortalXSClient
    try:
        client = PortalXSClient(username, password)
        client.connect()
        vehicles = client.get_vehicles()
        count = len(vehicles) if isinstance(vehicles, list) else 0
        return {'success': True, 'vehicle_count': count, 'login_id': client.login_id}
    except Exception as e:
        return {'success': False, 'error': str(e)[:300]}


def get_all_vehicles_for_account(account_id: int) -> list[dict]:
    """Get all vehicles from DB mapping (no SOAP call)."""
    from models import PortalXSVehicleMapping
    mappings = PortalXSVehicleMapping.query.filter_by(account_id=account_id).all()
    result = []
    for m in mappings:
        result.append({
            'id': m.id,
            'portalxs_regno': m.portalxs_regno,
            'vehicle_id': m.vehicle_id,
            'vehicle_no': m.vehicle.vehicle_no if m.vehicle else None,
            'vehicle_model': m.vehicle.model if m.vehicle else None,
            'group_name': m.group_name or '',
            'make_model': m.make_model or '',
            'last_lat': float(m.last_lat) if m.last_lat else None,
            'last_lon': float(m.last_lon) if m.last_lon else None,
            'last_speed': float(m.last_speed) if m.last_speed else 0.0,
            'last_status': m.last_status or 'Unknown',
            'last_rdt': m.last_rdt.isoformat() if m.last_rdt else None,
            'last_ignition': m.last_ignition or '',
            'last_landmark': m.last_landmark or '',
            'last_total_mileage': float(m.last_total_mileage) if m.last_total_mileage else 0.0,
            'last_total_trips': m.last_total_trips or 0,
            'last_max_speed': float(m.last_max_speed) if m.last_max_speed else 0.0,
        })
    return result


def link_vehicle(mapping_id: int, vehicle_id: int):
    """Link a PortalXS RegNo to an internal Vehicle."""
    from models import PortalXSVehicleMapping
    from app import db
    m = db.session.get(PortalXSVehicleMapping, mapping_id)
    if not m:
        raise ValueError("Mapping not found")
    m.vehicle_id = vehicle_id if vehicle_id else None
    db.session.commit()


def auto_link_vehicles(account_id: int) -> dict:
    """Auto-link PortalXS vehicles to internal Vehicle records by matching RegNo → vehicle_no.
    Uses normalized comparison (case-insensitive, stripped suffixes like COW/USG/RAS etc.).
    Only links mappings that are currently unlinked (vehicle_id is None).
    Returns {'linked': count, 'already_linked': count, 'unmatched': count, 'unmatched_list': [regno, ...]}.
    """
    import re
    from models import PortalXSVehicleMapping, Vehicle
    from app import db

    _SUFFIX_RE = re.compile(r'[\s\-]+(COW|USG\+P|USG|RAS|MNHC|EMS|NHP)\s*$', re.IGNORECASE)

    def _norm(s):
        if not s:
            return ''
        s = str(s).strip().upper()
        s = _SUFFIX_RE.sub('', s)       # strip suffix FIRST (needs space/hyphen before it)
        s = s.replace(' ', '')          # then remove remaining spaces
        return s

    mappings = PortalXSVehicleMapping.query.filter_by(account_id=account_id).all()
    if not mappings:
        return {'linked': 0, 'already_linked': 0, 'unmatched': 0, 'unmatched_list': []}

    # Build lookup: normalized vehicle_no -> Vehicle.id
    vehicles = Vehicle.query.all()
    norm_to_vid = {}
    for v in vehicles:
        key = _norm(v.vehicle_no)
        if key:
            norm_to_vid[key] = v.id

    linked = 0
    already = 0
    unmatched = 0
    unmatched_list = []

    for m in mappings:
        if m.vehicle_id:
            already += 1
            continue
        key = _norm(m.portalxs_regno)
        if key and key in norm_to_vid:
            m.vehicle_id = norm_to_vid[key]
            linked += 1
        else:
            unmatched += 1
            unmatched_list.append(m.portalxs_regno)

    if linked:
        db.session.commit()

    return {
        'linked': linked,
        'already_linked': already,
        'unmatched': unmatched,
        'unmatched_list': unmatched_list,
    }


def get_summary_stats(account_id: int) -> dict:
    """Get summary stats from cached positions."""
    vehicles = get_cached_positions(account_id)
    total = len(vehicles)
    moving = sum(1 for v in vehicles if v.get('VehicleStatus') == 'Moving')
    stopped = sum(1 for v in vehicles if v.get('VehicleStatus') == 'Stopped')
    idle = total - moving - stopped
    return {
        'total': total,
        'moving': moving,
        'stopped': stopped,
        'idle': idle,
    }
