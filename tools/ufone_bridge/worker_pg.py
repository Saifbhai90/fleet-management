#!/usr/bin/env python3
"""Ufone bridge worker that writes directly to Render Postgres (no HTTP ingest).

IMPORTANT: Never POST large payloads to Render's web service — that OOMs the
free dyno and causes periodic 502s (~every BRIDGE_INTERVAL_SEC). All writes
go straight to DATABASE_URL from this VPS.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import psycopg2
import psycopg2.extras

from ufone_api_client import UfoneClient

# getAmbulanceTaskReport API keys → emergency_task_record columns (subset used
# for dashboard filters / KPI cards). Keep in sync with services/emg_tasks.py.
REPORT_API_TO_EMG = {
    'TaskId': 'task_id_ext',
    'RequestFrom': 'request_from',
    'Phone': 'phone',
    'CLI': 'cli',
    'Name': 'name',
    'Husband': 'husband',
    'Address': 'address',
    'Location': 'location',
    'HouseColor': 'house_color',
    'DoorColor': 'door_color',
    'NearestLandmark': 'nearest_landmark',
    'EDD': 'edd',
    'ClinicalDetails': 'clinical_details',
    'DistrictName': 'district_name',
    'TehsilName': 'tehsil_name',
    'UCname': 'uc_name',
    'ambRegNo': 'amb_reg_no',
    'Status': 'status',
    'ReceivedBy': 'received_by',
    'Category': 'category',
    'SubCategory': 'sub_category',
    'FacilityName': 'facility_name',
    'FacilityCode': 'facility_code',
    'facilityType': 'facility_type',
    'ChangeFacilityComments': 'change_facility_comments',
    'CreatedDate': 'excel_created_date',
    'CompletedDateTime': 'completed_date_time',
    'CreatedBy': 'created_by',
    'CreatedDate1': 'created_date1',
    'CreatedTime': 'created_time',
    'ClosingRemarks': 'closing_remarks',
    'TaskClosedBy': 'task_closed_by',
    'PatientCNIC': 'patient_cnic',
    'PatientAdmissionNo': 'patient_admission_no',
    'RequestFor': 'request_for',
    'Closed_By': 'closed_by',
    'CallerName': 'caller_name',
    'taskStartLat': 'task_start_lat',
    'taskStartLon': 'task_start_lon',
    'taskEndLat': 'task_end_lat',
    'taskEndLon': 'task_end_lon',
    'rasCow': 'ras_cow',
    'distanceInKM': 'distance_in_km',
    'nearrestHealthFacility': 'nearrest_health_facility',
}

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger('ufone-bridge-pg')
ROOT = Path(__file__).resolve().parent


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _, val = line.partition('=')
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def _pk_today() -> date:
    """Pakistan calendar date (UTC+5). VPS/Render 'today' is often UTC."""
    return (datetime.utcnow() + timedelta(hours=5)).date()


def _env(name: str, default: str = '') -> str:
    return (os.environ.get(name) or default).strip()


def _int_env(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _to_float(val, default=None):
    try:
        if val is None or val == '':
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def normalize_ambulance(raw: dict) -> dict:
    lat = _to_float(raw.get('Latitude'), 0.0) or 0.0
    lon = _to_float(raw.get('Logitude'), 0.0) or 0.0
    return {
        'reg_no': raw.get('Reg_No'),
        'u_track_no': raw.get('UTrackNo'),
        'tracking_world_regno': raw.get('registrationNo_trackingWorld'),
        'chassis': raw.get('Chassis'),
        'make_model': raw.get('MakeModel'),
        'last_lat': lat,
        'last_lon': lon,
        'last_location': raw.get('Location'),
        'district': (raw.get('district_name') or raw.get('DistrictName')
                     or raw.get('District') or ''),
        'status': str(raw.get('Status') or ''),
        'driver_name': raw.get('Driver_Name'),
        'driver_cell': raw.get('Driver_Cell'),
        'facility_name': raw.get('facility_name'),
        'last_distance': _to_float(raw.get('Distance')),
    }


def _to_int(val, default=None):
    try:
        if val is None or val == '':
            return default
        return int(float(val))
    except (TypeError, ValueError):
        return default


def normalize_task(raw: dict) -> dict:
    return {
        'task_id': str(raw.get('TaskId') or raw.get('id') or ''),
        'patient_name': raw.get('name') or raw.get('Name'),
        'phone': raw.get('phone') or raw.get('Phone'),
        'address': raw.get('address') or raw.get('Address'),
        'ambulance_reg': raw.get('Ambulance') or raw.get('ambRegNo'),
        'status': raw.get('Status'),
        'district': (raw.get('district_name') or raw.get('DistrictName')
                     or raw.get('District')),
        'tehsil': raw.get('tehsil_name') or raw.get('TehsilName') or raw.get('Tehsil'),
        'facility': raw.get('facility_name') or raw.get('FacilityName'),
        'request_from': raw.get('RequestFrom'),
        'distance': _to_float(raw.get('Distance') or raw.get('distanceInKM')),
        'is_transfer': bool(raw.get('isTransfer') or raw.get('isTransfer2')),
        # Ufone dashboard age (minutes since create) — used for overdue notify
        'minutes_created': _to_int(raw.get('MinutsCreated') or raw.get('MinutesCreated')),
        'cli': raw.get('CLI') or raw.get('cli') or '',
        'category': raw.get('Category') or raw.get('category') or '',
        'created_date_time': (
            raw.get('CD') or raw.get('CreatedDate') or raw.get('CreatedDate1')
            or raw.get('created_date') or raw.get('Created_Date') or ''
        ),
        'raw_json': json.dumps(raw, default=str),
    }


def _notify_payload_from_task(t: dict) -> dict:
    created = (
        t.get('created_date_time')
        or ''
    )
    if not created:
        # Approximate from dashboard age when CreatedDate missing
        mins = t.get('minutes_created')
        try:
            if mins is not None:
                created = (
                    datetime.now() - timedelta(minutes=int(mins))
                ).strftime('%d %b %Y %H:%M:%S')
        except (TypeError, ValueError):
            created = ''
    return {
        'task_id': t.get('task_id'),
        'amb_reg_no': t.get('ambulance_reg'),
        'patient_name': t.get('patient_name'),
        'phone': t.get('phone'),
        'cli': t.get('cli') or '',
        'pickup': t.get('address') or '',
        'destination': t.get('facility') or '',
        'category': t.get('category') or '',
        'completed_date_time': '',
        'task_create_date_time': created,
        'minutes_open': t.get('minutes_created'),
    }


def _detail_create_datetime(detail: dict) -> str:
    """Same join as Task Detail UI: CD + CD_time (or CreatedDate + CreatedTime)."""
    if not isinstance(detail, dict):
        return ''
    cd = str(detail.get('CD') or detail.get('CreatedDate') or '').strip()
    ct = str(detail.get('CD_time') or detail.get('CreatedTime') or '').strip()
    if cd and ct:
        return f'{cd} {ct}'.strip()
    return (cd or ct or '').strip()


def _detail_cli(detail: dict) -> str:
    """Task Detail UI maps CLI → phone2 (primary), then CLI/Cli."""
    if not isinstance(detail, dict):
        return ''
    for k in ('phone2', 'CLI', 'Cli', 'cli'):
        v = detail.get(k)
        if v is not None and str(v).strip() and str(v).strip() not in ('0', '—', '-'):
            return str(v).strip()
    return ''


def _detail_completed_datetime(detail: dict) -> str:
    if not isinstance(detail, dict):
        return ''
    end_d = str(detail.get('EndDate') or '').strip()
    end_t = str(detail.get('EndTime') or '').strip()
    joined = f'{end_d} {end_t}'.strip()
    if joined:
        return joined
    for k in ('CompletedDateTime', 'CompletedDate', 'completed_date'):
        v = str(detail.get(k) or '').strip()
        if v:
            return v
    return ''


def _datetime_missing_time(val) -> bool:
    """True when empty or date-only / midnight (dashboard CD date w/o clock)."""
    s = str(val or '').strip()
    if not s:
        return True
    m = re.search(r'(\d{1,2}):(\d{2})(?::(\d{2}))?', s)
    if not m:
        return True
    h, mi, se = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
    # Dashboard CD is date-only → formatted as 00:00:00 — treat as missing time
    return h == 0 and mi == 0 and se == 0


def _save_task_detail_row(conn, account_id: int, bare: str, detail: dict,
                          comments: list | None = None) -> None:
    """Upsert ufone_task_detail_cache from a getTaskDetail payload."""
    if not bare or not isinstance(detail, dict) or not detail:
        return
    status = str(detail.get('Status') or '')
    detail_json = json.dumps(detail, default=str)
    comments_json = json.dumps(comments if comments is not None else [], default=str)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM ufone_task_detail_cache
            WHERE account_id=%s AND task_id=%s
            """,
            (account_id, bare),
        )
        found = cur.fetchone()
        if found:
            cur.execute(
                """
                UPDATE ufone_task_detail_cache SET
                  detail_json=%s, comments_json=%s, task_status=%s,
                  synced_at=NOW()
                WHERE id=%s
                """,
                (detail_json, comments_json, status, found[0]),
            )
        else:
            cur.execute(
                """
                INSERT INTO ufone_task_detail_cache (
                  account_id, task_id, detail_json, comments_json,
                  task_status, synced_at, created_at
                ) VALUES (%s,%s,%s,%s,%s,NOW(),NOW())
                """,
                (account_id, bare, detail_json, comments_json, status),
            )
    conn.commit()


def apply_detail_to_notify_event(ev: dict, detail: dict) -> dict:
    """Build notify fields from getTaskDetail — detail is the PRIMARY source
    (same as Task Detail popup / close scan); prior event values are only
    fallbacks for fields the detail payload does not carry."""
    if not isinstance(ev, dict) or not isinstance(detail, dict) or not detail:
        return ev
    created = _detail_create_datetime(detail)
    if created:
        ev['task_create_date_time'] = created
    cli = _detail_cli(detail)
    if cli:
        ev['cli'] = cli
    phone = str(detail.get('phone') or '').strip()
    if phone and phone not in ('0', 'None'):
        ev['phone'] = phone
    name = str(detail.get('name') or '').strip()
    if name:
        ev['patient_name'] = name
    addr = str(detail.get('address') or '').strip()
    if addr:
        ev['pickup'] = addr
    fac = str(detail.get('facility_name') or '').strip()
    if fac and fac != '0':
        ev['destination'] = fac
    amb = str(detail.get('amReg_No') or detail.get('Ambulance') or '').strip()
    if amb:
        ev['amb_reg_no'] = amb
    completed = _detail_completed_datetime(detail)
    if completed and ev.get('event') == 'close':
        ev['completed_date_time'] = completed
    return ev


def enrich_generate_events_from_detail(client, events: list, conn=None,
                                       account_id: int | None = None) -> list:
    """Build every fleet generate notification body from getTaskDetail.

    Dashboard only triggers the event (task id first seen) — the message data
    (create date+time, CLI, name, phone, pickup, destination) comes from
    getTaskDetail, exactly like the close notification path. Non-fleet events
    are skipped: they never match a driver on Render, so no wasted calls.
    """
    if not events or client is None:
        return events
    try:
        from detail_ops import UFONE_IO_LOCK
    except Exception:
        UFONE_IO_LOCK = None  # type: ignore

    fleet_keys = set()
    if conn is not None:
        try:
            fleet_keys = _fleet_reg_keys(conn)
        except Exception:
            fleet_keys = set()

    out = []
    for ev in events:
        if not isinstance(ev, dict) or ev.get('event') != 'generate':
            out.append(ev)
            continue
        bare = _bare_task_id(ev.get('task_id'))
        if not bare:
            out.append(ev)
            continue
        # Only fleet ambulances produce driver notifications
        if fleet_keys and not _amb_matches_fleet(ev.get('amb_reg_no'), fleet_keys):
            out.append(ev)
            continue
        try:
            if UFONE_IO_LOCK is not None:
                UFONE_IO_LOCK.acquire()
            try:
                detail = client.get_task_detail(bare, quick=True) or {}
            finally:
                if UFONE_IO_LOCK is not None:
                    UFONE_IO_LOCK.release()
            if isinstance(detail, dict) and detail:
                apply_detail_to_notify_event(ev, detail)
                if conn is not None and account_id is not None:
                    try:
                        _save_task_detail_row(conn, account_id, bare, detail)
                    except Exception as ce:
                        conn.rollback()
                        logger.warning('detail cache on generate %s: %s', bare, ce)
        except Exception as e:
            logger.warning('generate detail enrich %s failed: %s', bare, e)
        # Still date-only → approximate from minutes_open if we have it
        if _datetime_missing_time(ev.get('task_create_date_time')):
            mins = ev.get('minutes_open')
            try:
                if mins is not None:
                    ev['task_create_date_time'] = (
                        _pk_now() - timedelta(minutes=int(mins))
                    ).strftime('%d %b %Y %H:%M:%S')
            except (TypeError, ValueError):
                pass
        out.append(ev)
    return out


def ensure_task_event_notify_table(conn) -> None:
    """Dedupe table for one-shot events (e.g. overdue_close)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ufone_task_event_notify (
              id SERIAL PRIMARY KEY,
              account_id INTEGER NOT NULL,
              task_id VARCHAR(50) NOT NULL,
              event_type VARCHAR(30) NOT NULL,
              sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              UNIQUE (account_id, task_id, event_type)
            )
            """
        )
    conn.commit()


def _mark_event_notify_sent(conn, account_id: int, task_id: str, event_type: str) -> bool:
    """Return True if this is the first send (row inserted), False if already sent."""
    if not task_id:
        return False
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ufone_task_event_notify (account_id, task_id, event_type)
            VALUES (%s, %s, %s)
            ON CONFLICT (account_id, task_id, event_type) DO NOTHING
            RETURNING id
            """,
            (account_id, str(task_id), event_type),
        )
        row = cur.fetchone()
    conn.commit()
    return row is not None


def _bare_task_id(tid) -> str:
    """Normalize PHF-7571234 / 7571234 → 7571234."""
    s = str(tid or '').strip()
    if s.upper().startswith('PHF-'):
        return s[4:].strip() or s
    return s


# In-app notification titles per event type (used for deliver-verified marking)
_EVENT_NOTIF_TITLES = {
    'generate': ('New Task Generate', 'Nayi Task Assign'),
    'close': ('Task Complete',),
    'overdue_close': ('Task close karwa dein',),
}


def _event_already_marked(conn, account_id: int, task_id: str,
                          event_type: str) -> bool:
    bare = _bare_task_id(task_id)
    if not bare:
        return False
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM ufone_task_event_notify
            WHERE account_id = %s AND event_type = %s
              AND task_id IN (%s, %s, %s)
            LIMIT 1
            """,
            (account_id, event_type, bare, f'PHF-{bare}', str(task_id)),
        )
        return cur.fetchone() is not None


def _event_generate_already_marked(conn, account_id: int, task_id: str) -> bool:
    return _event_already_marked(conn, account_id, task_id, 'generate')


def _task_notif_exists(conn, bare_tid: str, since_date: date,
                       titles: tuple) -> bool:
    """True if an in-app notification of any given title exists for this task id."""
    if not bare_tid or not titles:
        return False
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM notification
            WHERE title = ANY(%s)
              AND created_at >= %s
              AND message ILIKE %s
            LIMIT 1
            """,
            (list(titles), since_date, f'%{bare_tid}%'),
        )
        return cur.fetchone() is not None


def _nayi_task_notif_exists(conn, bare_tid: str, since_date: date) -> bool:
    """True if in-app generate notify already logged for this task id."""
    return _task_notif_exists(
        conn, bare_tid, since_date, _EVENT_NOTIF_TITLES['generate'])


def _fleet_reg_keys(conn) -> set:
    """Normalized keys for all Master Data vehicles (48 fleet)."""
    keys = set()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT vehicle_no FROM vehicle
            WHERE vehicle_no IS NOT NULL AND TRIM(vehicle_no) <> ''
            """
        )
        for (vn,) in cur.fetchall():
            vn = (vn or '').strip()
            if not vn:
                continue
            keys.add(_norm_reg_key(vn))
            base = _strip_reg_tag(vn)
            if base:
                keys.add(_norm_reg_key(base))
    keys.discard('')
    return keys


def _amb_matches_fleet(amb_reg_no, fleet_keys: set) -> bool:
    if not amb_reg_no or not fleet_keys:
        return False
    reg = str(amb_reg_no).strip()
    if not reg:
        return False
    return (
        _norm_reg_key(reg) in fleet_keys
        or _norm_reg_key(_strip_reg_tag(reg)) in fleet_keys
    )


def collect_fleet_generate_safety_net(
    conn, account_id: int, today: date
) -> list:
    """Retry generate ONLY for recent fleet misses — not a delayed first send.

    Primary notify still fires on first dash/EMG insert (~3 min).
    This only re-sends if that attempt failed, and only within
    BRIDGE_GENERATE_RETRY_MINUTES (default 45) of emg created_at —
    so a 07:00 task is NOT notified at 10:00.
    """
    ensure_task_event_notify_table(conn)
    fleet_keys = _fleet_reg_keys(conn)
    if not fleet_keys:
        return []

    retry_mins = max(5, _int_env('BRIDGE_GENERATE_RETRY_MINUTES', 45))
    cutoff = _pk_now() - timedelta(minutes=retry_mins)

    events = []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (task_id_ext)
              task_id_ext, amb_reg_no, name, phone, cli, address,
              facility_name, category, completed_date_time, status, created_at
            FROM emergency_task_record
            WHERE account_id = %s
              AND task_date = %s
              AND task_id_ext IS NOT NULL AND task_id_ext <> ''
              AND amb_reg_no IS NOT NULL AND TRIM(amb_reg_no) <> ''
              AND created_at >= %s
            ORDER BY task_id_ext, id DESC
            """,
            (account_id, today, cutoff),
        )
        rows = cur.fetchall()

    healed = 0
    for (
        tid_ext, amb, name, phone, cli, addr, fac, cat, completed, status,
        _created_at,
    ) in rows:
        if _status_is_complete(status):
            continue
        if not _amb_matches_fleet(amb, fleet_keys):
            continue
        bare = _bare_task_id(tid_ext)
        if not bare:
            continue
        if _event_generate_already_marked(conn, account_id, bare):
            continue
        # Already delivered → heal mark only (never duplicate)
        if _nayi_task_notif_exists(conn, bare, today):
            _mark_event_notify_sent(conn, account_id, bare, 'generate')
            healed += 1
            continue
        events.append({
            'event': 'generate',
            'task_id': bare,
            'amb_reg_no': amb,
            'patient_name': name,
            'phone': phone,
            'cli': cli or '',
            'pickup': addr or '',
            'destination': fac or '',
            'category': cat or '',
            'completed_date_time': completed or '',
        })

    if healed:
        logger.info('fleet generate safety-net healed marks=%s', healed)
    if events:
        logger.info(
            'fleet generate safety-net retry=%s (within %sm, fleet only)',
            len(events), retry_mins,
        )
    return events


def _parse_completed_dt(val) -> datetime | None:
    """Parse Ufone completed_date_time text like '03 Aug 2026 16:03:46'."""
    if not val:
        return None
    s = re.sub(r'\s+', ' ', str(val).strip())
    for fmt in ('%d %b %Y %H:%M:%S', '%d %B %Y %H:%M:%S',
                '%Y-%m-%d %H:%M:%S', '%d-%m-%Y %H:%M:%S'):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def collect_fleet_close_safety_net(
    conn, account_id: int, today: date
) -> list:
    """Retry 'Task Complete' for fleet tasks closed recently but never notified.

    Close events fire on the incomplete→complete EMG edge; if that push/fanout
    fails once, the edge never re-appears. This scans today's completed fleet
    rows closed within BRIDGE_CLOSE_RETRY_MINUTES (default 45) and re-emits any
    that have neither a 'close' mark nor a 'Task Complete' notification row.
    """
    ensure_task_event_notify_table(conn)
    fleet_keys = _fleet_reg_keys(conn)
    if not fleet_keys:
        return []

    retry_mins = max(5, _int_env('BRIDGE_CLOSE_RETRY_MINUTES', 45))
    now = _pk_now()
    # completed_date_time is display text — cheap prefilter on today's prefix
    day_prefix = now.strftime('%d %b %Y') + ' %'

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (task_id_ext)
              task_id_ext, amb_reg_no, name, phone, cli, address,
              facility_name, category, completed_date_time, excel_created_date,
              status
            FROM emergency_task_record
            WHERE account_id = %s
              AND task_date = %s
              AND task_id_ext IS NOT NULL AND task_id_ext <> ''
              AND amb_reg_no IS NOT NULL AND TRIM(amb_reg_no) <> ''
              AND completed_date_time LIKE %s
              AND lower(COALESCE(status, '')) LIKE '%%complete%%'
              AND lower(COALESCE(status, '')) NOT LIKE '%%incomplete%%'
            ORDER BY task_id_ext, id DESC
            """,
            (account_id, today, day_prefix),
        )
        rows = cur.fetchall()

    events = []
    healed = 0
    for (
        tid_ext, amb, name, phone, cli, addr, fac, cat, completed,
        created_dt, _status,
    ) in rows:
        if not _amb_matches_fleet(amb, fleet_keys):
            continue
        closed_at = _parse_completed_dt(completed)
        if closed_at is None:
            continue
        age_min = (now - closed_at).total_seconds() / 60.0
        # Skip too-recent closes (primary EMG edge may still deliver this
        # cycle) and anything older than the retry window.
        if age_min < 4 or age_min > retry_mins:
            continue
        bare = _bare_task_id(tid_ext)
        if not bare:
            continue
        if _event_already_marked(conn, account_id, bare, 'close'):
            continue
        if _task_notif_exists(conn, bare, today,
                              _EVENT_NOTIF_TITLES['close']):
            _mark_event_notify_sent(conn, account_id, bare, 'close')
            healed += 1
            continue
        events.append({
            'event': 'close',
            'task_id': bare,
            'amb_reg_no': amb,
            'patient_name': name,
            'phone': phone,
            'cli': cli or '',
            'pickup': addr or '',
            'destination': fac or '',
            'category': cat or '',
            'completed_date_time': completed or '',
            'task_create_date_time': created_dt or '',
        })

    if healed:
        logger.info('fleet close safety-net healed marks=%s', healed)
    if events:
        logger.info(
            'fleet close safety-net retry=%s (within %sm, fleet only)',
            len(events), retry_mins,
        )
    return events


_last_fast_close_scan = 0.0


def fleet_fast_close_scan(conn, account_id: int, client, today: date) -> list:
    """getTaskDetail poll for open Master-Data (fleet) tasks — close + enrich.

    Runs every BRIDGE_FAST_CLOSE_SEC (default 60). Non-fleet open tasks stay on
    the normal 15/batch detail rotation. Load: one tiny lookup per open fleet
    task (typically 5–15).
    """
    global _last_fast_close_scan
    every = max(30, _int_env('BRIDGE_FAST_CLOSE_SEC', 60))
    now_mono = time.monotonic()
    if _last_fast_close_scan and (now_mono - _last_fast_close_scan) < every:
        return []
    _last_fast_close_scan = now_mono

    fleet_keys = _fleet_reg_keys(conn)
    if not fleet_keys:
        return []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (task_id_ext)
              task_id_ext, amb_reg_no, name, phone, cli, address,
              facility_name, category, excel_created_date, status
            FROM emergency_task_record
            WHERE account_id = %s AND task_date = %s
              AND task_id_ext IS NOT NULL AND task_id_ext <> ''
              AND amb_reg_no IS NOT NULL AND TRIM(amb_reg_no) <> ''
            ORDER BY task_id_ext, id DESC
            """,
            (account_id, today),
        )
        rows = cur.fetchall()

    open_fleet = [
        r for r in rows
        if not _status_is_complete(r[9]) and _amb_matches_fleet(r[1], fleet_keys)
    ]
    cap = max(1, _int_env('BRIDGE_FAST_CLOSE_CAP', 25))
    open_fleet = open_fleet[:cap]
    if not open_fleet:
        return []

    try:
        from detail_ops import UFONE_IO_LOCK
    except Exception:
        UFONE_IO_LOCK = None  # type: ignore

    events = []
    closed = 0
    for (tid_ext, amb, name, phone, cli, addr, fac, cat,
         created_dt, _st) in open_fleet:
        bare = _bare_task_id(tid_ext)
        if not bare:
            continue
        try:
            if UFONE_IO_LOCK is not None:
                UFONE_IO_LOCK.acquire()
            try:
                detail = client.get_task_detail(bare, quick=True) or {}
            finally:
                if UFONE_IO_LOCK is not None:
                    UFONE_IO_LOCK.release()
        except Exception as e:
            logger.warning('fleet detail %s failed: %s', bare, e)
            continue
        if not isinstance(detail, dict) or not detail:
            continue
        try:
            _save_task_detail_row(conn, account_id, bare, detail)
        except Exception as e:
            conn.rollback()
            logger.warning('fleet detail cache %s: %s', bare, e)

        created_full = _detail_create_datetime(detail) or created_dt or ''
        cli_full = _detail_cli(detail) or cli or ''
        name_d = (str(detail.get('name') or '').strip() or name)
        phone_d = (str(detail.get('phone') or '').strip() or phone)
        addr_d = (str(detail.get('address') or '').strip() or addr)
        fac_d = str(detail.get('facility_name') or '').strip()
        if not fac_d or fac_d == '0':
            fac_d = fac or ''
        amb_d = (str(detail.get('amReg_No') or detail.get('Ambulance') or '').strip()
                 or amb)
        status = str(detail.get('Status') or '').strip()

        if not _status_is_complete(status):
            continue

        completed = _detail_completed_datetime(detail)
        if not completed:
            completed = _pk_now().strftime('%d %b %Y %H:%M:%S')
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE emergency_task_record
                    SET status=%s, completed_date_time=%s,
                        excel_created_date=COALESCE(NULLIF(%s,''), excel_created_date),
                        cli=COALESCE(NULLIF(%s,''), cli)
                    WHERE account_id=%s AND task_date=%s AND task_id_ext=%s
                    """,
                    (status, completed, created_full, cli_full,
                     account_id, today, tid_ext),
                )
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.warning('fleet close row update %s failed: %s', bare, e)
        closed += 1
        if _event_already_marked(conn, account_id, bare, 'close'):
            continue
        if _task_notif_exists(conn, bare, today, _EVENT_NOTIF_TITLES['close']):
            _mark_event_notify_sent(conn, account_id, bare, 'close')
            continue
        events.append({
            'event': 'close',
            'task_id': bare,
            'amb_reg_no': amb_d,
            'patient_name': name_d,
            'phone': phone_d,
            'cli': cli_full,
            'pickup': addr_d,
            'destination': fac_d,
            'category': cat or '',
            'completed_date_time': completed,
            'task_create_date_time': created_full,
        })

    if closed or events:
        logger.info(
            'fleet detail scan: checked=%s closed=%s close_notify=%s',
            len(open_fleet), closed, len(events),
        )
    return events


def open_nonfleet_task_ids(conn, account_id: int, today: date) -> list:
    """Bare task ids still incomplete today, excluding Master Data vehicles."""
    fleet_keys = _fleet_reg_keys(conn)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (task_id_ext)
              task_id_ext, amb_reg_no, status
            FROM emergency_task_record
            WHERE account_id = %s AND task_date = %s
              AND task_id_ext IS NOT NULL AND task_id_ext <> ''
            ORDER BY task_id_ext, id DESC
            """,
            (account_id, today),
        )
        rows = cur.fetchall()
    out = []
    for tid_ext, amb, status in rows:
        if _status_is_complete(status):
            continue
        if fleet_keys and _amb_matches_fleet(amb, fleet_keys):
            continue
        bare = _bare_task_id(tid_ext)
        if bare:
            out.append(bare)
    return out


_last_nonfleet_detail = 0.0


def upsert_nonfleet_task_details(conn, account_id: int, client, today: date,
                                 limit: int = 15) -> int:
    """15-task stale-first getTaskDetail for non-fleet open tasks.

    Runs every BRIDGE_NONFLEET_DETAIL_SEC (default 360 = 6 min) — non-fleet
    drivers get no notifications, their detail cache is popup-only, so a slow
    rotation is enough and keeps portal load down.
    """
    global _last_nonfleet_detail
    every = max(60, _int_env('BRIDGE_NONFLEET_DETAIL_SEC', 360))
    now_mono = time.monotonic()
    if _last_nonfleet_detail and (now_mono - _last_nonfleet_detail) < every:
        return 0
    _last_nonfleet_detail = now_mono

    open_ids = open_nonfleet_task_ids(conn, account_id, today)
    if not open_ids:
        return 0
    # Prefer EMG open set when provided path used emg-based picker via open_ids only
    batch = _pick_stale_detail_batch(conn, account_id, open_ids, limit)
    if not batch:
        return 0
    logger.info(
        'non-fleet task detail batch %s/%s open (stale-first): %s',
        len(batch), len(open_ids),
        ','.join(batch[:5]) + ('…' if len(batch) > 5 else ''),
    )
    fake_emg = [{'TaskId': t, 'id': t, 'Status': 'Incomplete'} for t in batch]
    # Reuse emg-path writer but with pre-picked ids only
    return upsert_task_details(conn, account_id, client, fake_emg, limit=limit)


def _dedupe_notify_events(events: list) -> list:
    """Keep one event per (bare_task_id, event_type); prefer earlier entries."""
    seen = set()
    out = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        key = (_bare_task_id(ev.get('task_id')), ev.get('event'))
        if not key[0] or key[1] is None:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(ev)
    return out


def _status_is_complete(status) -> bool:
    s = (status or '').strip().lower()
    return ('complete' in s) and ('incomplete' not in s)


def _status_is_open(status) -> bool:
    """In-process / incomplete — keeps a prior calendar day on the EMG fetch list."""
    s = (status or '').strip().lower()
    if not s or 'cancel' in s:
        return False
    if _status_is_complete(s):
        return False
    return (
        'incomplete' in s or s == '1' or 'pending' in s
        or 'in-process' in s or 'in process' in s
    )


def emg_lookback_days() -> int:
    """Max prior-day window for open-task EMG catch-up (hard-capped at 7)."""
    return max(1, min(_int_env('BRIDGE_EMG_LOOKBACK_DAYS', 7), 7))


def previous_open_emg_dates(conn, account_id: int, today_d: date,
                            lookback_days: int = 7) -> list:
    """Prior calendar dates (not today) that still have in-process EMG rows.

    Only these dates are fetched from Ufone in addition to today. If a prior
    date has zero open tasks, it is NOT requested from the portal — lowest load.
    """
    lookback_days = max(1, min(int(lookback_days or 7), 7))
    oldest = today_d - timedelta(days=lookback_days - 1)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT task_date::date AS d
            FROM emergency_task_record
            WHERE account_id = %s
              AND task_date IS NOT NULL
              AND task_date::date >= %s
              AND task_date::date < %s
              AND status IS NOT NULL
              AND (
                lower(status) LIKE '%%incomplete%%'
                OR lower(status) IN ('1', 'pending')
                OR lower(status) LIKE '%%in-process%%'
                OR lower(status) LIKE '%%in process%%'
              )
              AND NOT (
                lower(status) LIKE '%%complete%%'
                AND lower(status) NOT LIKE '%%incomplete%%'
              )
              AND lower(status) NOT LIKE '%%cancel%%'
            ORDER BY 1 ASC
            """,
            (account_id, oldest, today_d),
        )
        return [r[0] for r in cur.fetchall() if r[0]]


def fetch_emg_report_day(client: UfoneClient, day: date) -> list:
    """One calendar day from getAmbulanceTaskReport (all districts)."""
    day_s = day.strftime('%Y-%m-%d')
    emg_raw = client._call(
        'ReportEmergencyTask.aspx', 'getAmbulanceTaskReport',
        {
            'startDate': client._to_ufone_date(day_s),
            'endDate': client._to_ufone_date(day_s),
            'District': '', 'Tehsil': '', 'UnionCouncil': '', 'TaskId': '',
        },
        visit_page=False, timeout=60, retries=1,
    ) or []
    return [r for r in emg_raw if isinstance(r, dict)]


def db_connect():
    url = _env('DATABASE_URL')
    if not url:
        raise RuntimeError('DATABASE_URL required for PG bridge mode')
    if url.startswith('postgres://'):
        url = 'postgresql://' + url[len('postgres://'):]
    return psycopg2.connect(url, connect_timeout=30)


def _pg_session(conn) -> None:
    """Keep bridge writes from hanging; store wall-clock as Pakistan time."""
    with conn.cursor() as cur:
        cur.execute("SET TIME ZONE 'Asia/Karachi'")
        cur.execute("SET statement_timeout = '120s'")
        cur.execute("SET lock_timeout = '30s'")
    conn.commit()


def upsert_districts(conn, districts: list) -> int:
    if not districts:
        return 0
    sql = """
    INSERT INTO ufone_district_cache (code, name, synced_at)
    VALUES (%(code)s, %(name)s, NOW())
    ON CONFLICT (code) DO UPDATE SET
      name = EXCLUDED.name,
      synced_at = EXCLUDED.synced_at
    """
    with conn.cursor() as cur:
        for d in districts:
            cur.execute(sql, d)
    conn.commit()
    return len(districts)


def upsert_vehicles(conn, account_id: int, vehicles: list) -> int:
    if not vehicles:
        return 0
    sql = """
    INSERT INTO ufone_vehicle_cache (
      account_id, reg_no, u_track_no, tracking_world_regno, chassis, make_model,
      last_lat, last_lon, last_location, district, status, driver_name, driver_cell,
      facility_name, last_distance, updated_at, created_at
    ) VALUES (
      %(account_id)s, %(reg_no)s, %(u_track_no)s, %(tracking_world_regno)s, %(chassis)s,
      %(make_model)s, %(last_lat)s, %(last_lon)s, %(last_location)s, %(district)s,
      %(status)s, %(driver_name)s, %(driver_cell)s, %(facility_name)s, %(last_distance)s,
      NOW(), NOW()
    )
    ON CONFLICT (account_id, reg_no) DO UPDATE SET
      u_track_no = EXCLUDED.u_track_no,
      tracking_world_regno = EXCLUDED.tracking_world_regno,
      chassis = EXCLUDED.chassis,
      make_model = EXCLUDED.make_model,
      last_lat = EXCLUDED.last_lat,
      last_lon = EXCLUDED.last_lon,
      last_location = EXCLUDED.last_location,
      district = EXCLUDED.district,
      status = EXCLUDED.status,
      driver_name = EXCLUDED.driver_name,
      driver_cell = EXCLUDED.driver_cell,
      facility_name = EXCLUDED.facility_name,
      last_distance = EXCLUDED.last_distance,
      updated_at = NOW()
    """
    rows = []
    for v in vehicles:
        if not v.get('reg_no'):
            continue
        row = dict(v)
        row['account_id'] = account_id
        rows.append(row)
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, sql, rows, page_size=200)
    conn.commit()
    return len(rows)


def _parse_maint_date(val):
    """Parse Ufone maintenance date string → date or None."""
    s = _coerce_str(val)
    if not s:
        return None
    s0 = s.split()[0][:10]
    for fmt in ('%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y', '%d-%m-%Y'):
        try:
            return datetime.strptime(s0, fmt).date()
        except ValueError:
            continue
    # Portal: "Jun 20 2026 10:06AM"
    spaced = re.sub(r'(?i)(\d)(AM|PM)\b', r'\1 \2', s)
    for fmt in ('%b %d %Y %I:%M %p', '%b %d %Y',
                '%B %d %Y %I:%M %p', '%B %d %Y'):
        try:
            return datetime.strptime(spaced, fmt).date()
        except ValueError:
            continue
    return None


def _to_int_or_none(val):
    if val is None or str(val).strip() == '':
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def map_maintenance_row(raw: dict) -> dict | None:
    """Map getAmbulanceUnderMaintenance row → ufone_maintenance_cache fields."""
    if not isinstance(raw, dict):
        return None
    reg = _coerce_str(
        raw.get('Reg_no') or raw.get('Reg_No') or raw.get('reg_no')
        or raw.get('Ambulance') or raw.get('ambRegNo')
    )
    if not reg:
        return None
    send = _parse_maint_date(raw.get('Send_Date') or raw.get('SendDate')
                             or raw.get('send_date'))
    ret = _parse_maint_date(raw.get('Return_Date') or raw.get('ReturnDate')
                            or raw.get('return_date'))
    days = _to_int_or_none(raw.get('Days') if raw.get('Days') is not None
                           else raw.get('days'))
    if days is None:
        days = 0
        try:
            today = _pk_today()
            if send and not ret:
                days = max(0, (today - send).days)
            elif send and ret:
                days = max(0, (ret - send).days)
        except Exception:
            days = 0
    ext_id = _to_int_or_none(raw.get('id') or raw.get('Id') or raw.get('ext_id'))
    created_raw = (
        raw.get('Created_Date') or raw.get('CreatedDate')
        or raw.get('created_date') or raw.get('created_date_text')
    )
    return {
        'ext_id': ext_id,
        'reg_no': reg,
        'district': _coerce_str(raw.get('District') or raw.get('district')),
        'maintain_type': _coerce_str(
            raw.get('Maintain_Type') or raw.get('MaintainType')
            or raw.get('maintain_type')
        ),
        'cat_name': _coerce_str(
            raw.get('Cat_Name') or raw.get('CatName') or raw.get('cat_name')),
        'sub_cat_name': _coerce_str(
            raw.get('Sub_Cat_Name') or raw.get('SubCatName')
            or raw.get('sub_cat_name')),
        'due_date': _parse_maint_date(
            raw.get('Due_Date') or raw.get('DueDate') or raw.get('due_date')),
        'send_date': send,
        'return_date': ret,
        'comments': _coerce_str(raw.get('Comments') or raw.get('comments')),
        'days_offline': days,
        'hours': _to_int_or_none(
            raw.get('Hours') if raw.get('Hours') is not None else raw.get('hours')),
        'minute': _to_int_or_none(
            raw.get('Minute') if raw.get('Minute') is not None
            else raw.get('minute')),
        'created_by': _coerce_str(
            raw.get('CreatedBy') or raw.get('Created_By') or raw.get('created_by')),
        'created_date': _parse_maint_date(created_raw),
        'created_date_text': _coerce_str(created_raw) or None,
        'modified_by': _coerce_str(
            raw.get('ModifiedBy') or raw.get('modified_by')),
        'modified_date': _coerce_str(
            raw.get('Modified_Date') or raw.get('modified_date')) or None,
        'start_date': _coerce_str(
            raw.get('startDate') or raw.get('start_date')) or None,
        'start_time': _coerce_str(
            raw.get('startTime') or raw.get('start_time')) or None,
        'end_date': _coerce_str(
            raw.get('endDate') or raw.get('end_date')) or None,
        'end_time': _coerce_str(
            raw.get('endTime') or raw.get('end_time')) or None,
    }


def ensure_maintenance_columns(conn) -> None:
    """Add full portal columns to open-cache + ensure history table."""
    alters = [
        "ALTER TABLE ufone_maintenance_cache ADD COLUMN IF NOT EXISTS ext_id INTEGER",
        "ALTER TABLE ufone_maintenance_cache ADD COLUMN IF NOT EXISTS hours INTEGER",
        "ALTER TABLE ufone_maintenance_cache ADD COLUMN IF NOT EXISTS minute INTEGER",
        "ALTER TABLE ufone_maintenance_cache ADD COLUMN IF NOT EXISTS created_date_text VARCHAR(80)",
        "ALTER TABLE ufone_maintenance_cache ADD COLUMN IF NOT EXISTS modified_by VARCHAR(100)",
        "ALTER TABLE ufone_maintenance_cache ADD COLUMN IF NOT EXISTS modified_date VARCHAR(80)",
        "ALTER TABLE ufone_maintenance_cache ADD COLUMN IF NOT EXISTS start_date VARCHAR(30)",
        "ALTER TABLE ufone_maintenance_cache ADD COLUMN IF NOT EXISTS start_time VARCHAR(30)",
        "ALTER TABLE ufone_maintenance_cache ADD COLUMN IF NOT EXISTS end_date VARCHAR(30)",
        "ALTER TABLE ufone_maintenance_cache ADD COLUMN IF NOT EXISTS end_time VARCHAR(30)",
    ]
    with conn.cursor() as cur:
        for sql in alters:
            try:
                cur.execute(sql)
            except Exception as e:
                logger.warning('maint column ensure failed: %s (%s)', sql, e)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ufone_maintenance_history (
              id SERIAL PRIMARY KEY,
              account_id INTEGER NOT NULL,
              ext_id INTEGER NOT NULL,
              reg_no VARCHAR(50),
              district VARCHAR(100),
              maintain_type VARCHAR(50),
              cat_name VARCHAR(100),
              sub_cat_name VARCHAR(100),
              due_date DATE,
              send_date DATE,
              return_date DATE,
              comments TEXT,
              days_offline INTEGER DEFAULT 0,
              hours INTEGER,
              minute INTEGER,
              created_by VARCHAR(100),
              created_date DATE,
              modified_by VARCHAR(100),
              modified_date VARCHAR(50),
              start_date VARCHAR(30),
              start_time VARCHAR(30),
              end_date VARCHAR(30),
              end_time VARCHAR(30),
              is_open BOOLEAN DEFAULT TRUE,
              first_seen_at TIMESTAMPTZ DEFAULT NOW(),
              last_seen_at TIMESTAMPTZ DEFAULT NOW(),
              closed_at TIMESTAMPTZ,
              created_at TIMESTAMPTZ DEFAULT NOW(),
              updated_at TIMESTAMPTZ DEFAULT NOW(),
              UNIQUE (account_id, ext_id)
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS ix_ufone_maint_hist_open "
            "ON ufone_maintenance_history (account_id, is_open)"
        )
    conn.commit()


def upsert_maintenance(conn, account_id: int, items: list) -> int:
    """Upsert under-maintenance rows; full-snapshot replace when multi-district."""
    ensure_maintenance_columns(conn)
    rows = []
    for raw in items or []:
        mapped = map_maintenance_row(raw) if isinstance(raw, dict) else None
        if mapped and mapped.get('reg_no'):
            rows.append(mapped)

    # Dedupe by reg_no (last wins)
    by_reg = {r['reg_no']: r for r in rows}
    rows = list(by_reg.values())
    seen = {r['reg_no'] for r in rows}

    touched_districts = {
        (r.get('district') or '').strip().casefold()
        for r in rows if (r.get('district') or '').strip()
    }
    # District login (1 district) → only purge that district.
    # Multi-district payload → full snapshot. Empty payload → no deletes.
    scoped = bool(rows) and len(touched_districts) <= 1

    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, reg_no, district FROM ufone_maintenance_cache "
            "WHERE account_id=%s",
            (account_id,),
        )
        existing = {}
        existing_dist = {}
        for rid, reg, dist in cur.fetchall():
            if not reg:
                continue
            existing[reg] = rid
            existing_dist[reg] = (dist or '').strip().casefold()

        for r in rows:
            reg = r['reg_no']
            vals = (
                r.get('ext_id'), r.get('district'), r.get('maintain_type'),
                r.get('cat_name'), r.get('sub_cat_name'), r.get('due_date'),
                r.get('send_date'), r.get('return_date'), r.get('comments'),
                r.get('days_offline') or 0, r.get('hours'), r.get('minute'),
                r.get('created_by'), r.get('created_date'),
                r.get('created_date_text'), r.get('modified_by'),
                r.get('modified_date'), r.get('start_date'), r.get('start_time'),
                r.get('end_date'), r.get('end_time'),
            )
            if reg in existing:
                cur.execute(
                    """
                    UPDATE ufone_maintenance_cache SET
                      ext_id=%s, district=%s, maintain_type=%s, cat_name=%s,
                      sub_cat_name=%s, due_date=%s, send_date=%s, return_date=%s,
                      comments=%s, days_offline=%s, hours=%s, minute=%s,
                      created_by=%s, created_date=%s, created_date_text=%s,
                      modified_by=%s, modified_date=%s, start_date=%s,
                      start_time=%s, end_date=%s, end_time=%s, updated_at=NOW()
                    WHERE id=%s
                    """,
                    vals + (existing[reg],),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO ufone_maintenance_cache (
                      account_id, reg_no, ext_id, district, maintain_type,
                      cat_name, sub_cat_name, due_date, send_date, return_date,
                      comments, days_offline, hours, minute, created_by,
                      created_date, created_date_text, modified_by, modified_date,
                      start_date, start_time, end_date, end_time,
                      updated_at, created_at
                    ) VALUES (
                      %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                      %s,%s,%s,%s,NOW(),NOW()
                    )
                    """,
                    (account_id, reg) + vals,
                )

        removed = 0
        if rows:
            for reg, rid in existing.items():
                if reg in seen:
                    continue
                if scoped:
                    row_dist = existing_dist.get(reg) or ''
                    if row_dist and row_dist not in touched_districts:
                        continue
                cur.execute(
                    "DELETE FROM ufone_maintenance_cache WHERE id=%s", (rid,))
                removed += 1

    conn.commit()
    logger.info(
        'maintenance upserted=%s districts=%s (removed stale=%s, scoped=%s)',
        len(rows), len(touched_districts), removed, scoped)
    # Keep multi-district closed History archive in sync
    try:
        archive_maintenance_snapshot(
            conn, account_id, rows, statewide=len(touched_districts) >= 2)
    except Exception as e:
        logger.warning('maintenance archive failed (non-fatal): %s', e)
    return len(rows)


def archive_maintenance_snapshot(conn, account_id: int, rows: list,
                                 statewide: bool = False) -> int:
    """Upsert open tickets into history; mark missing as closed when statewide."""
    ensure_maintenance_columns(conn)
    if not rows:
        return 0
    seen_ext = set()
    touched = {
        (r.get('district') or '').strip().casefold()
        for r in rows if (r.get('district') or '').strip()
    }
    n = 0
    with conn.cursor() as cur:
        for r in rows:
            ext_id = r.get('ext_id')
            if ext_id is None:
                continue
            seen_ext.add(int(ext_id))
            cur.execute(
                """
                INSERT INTO ufone_maintenance_history (
                  account_id, ext_id, reg_no, district, maintain_type, cat_name,
                  sub_cat_name, due_date, send_date, return_date, comments,
                  days_offline, hours, minute, created_by, created_date,
                  modified_by, modified_date, start_date, start_time,
                  end_date, end_time, is_open, first_seen_at, last_seen_at,
                  closed_at, created_at, updated_at
                ) VALUES (
                  %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                  %s,%s,TRUE,NOW(),NOW(),NULL,NOW(),NOW()
                )
                ON CONFLICT (account_id, ext_id) DO UPDATE SET
                  reg_no=EXCLUDED.reg_no, district=EXCLUDED.district,
                  maintain_type=EXCLUDED.maintain_type, cat_name=EXCLUDED.cat_name,
                  sub_cat_name=EXCLUDED.sub_cat_name, due_date=EXCLUDED.due_date,
                  send_date=EXCLUDED.send_date, return_date=EXCLUDED.return_date,
                  comments=EXCLUDED.comments, days_offline=EXCLUDED.days_offline,
                  hours=EXCLUDED.hours, minute=EXCLUDED.minute,
                  created_by=EXCLUDED.created_by, created_date=EXCLUDED.created_date,
                  modified_by=EXCLUDED.modified_by,
                  modified_date=EXCLUDED.modified_date,
                  start_date=EXCLUDED.start_date, start_time=EXCLUDED.start_time,
                  end_date=EXCLUDED.end_date, end_time=EXCLUDED.end_time,
                  is_open=TRUE, last_seen_at=NOW(), closed_at=NULL,
                  updated_at=NOW()
                """,
                (
                    account_id, int(ext_id), r.get('reg_no'), r.get('district'),
                    r.get('maintain_type'), r.get('cat_name'), r.get('sub_cat_name'),
                    r.get('due_date'), r.get('send_date'), r.get('return_date'),
                    r.get('comments'), r.get('days_offline') or 0,
                    r.get('hours'), r.get('minute'), r.get('created_by'),
                    r.get('created_date'), r.get('modified_by'),
                    r.get('modified_date'), r.get('start_date'),
                    r.get('start_time'), r.get('end_date'), r.get('end_time'),
                ),
            )
            n += 1

        # Mark tickets that left the open list as closed
        cur.execute(
            "SELECT id, ext_id, district FROM ufone_maintenance_history "
            "WHERE account_id=%s AND is_open=TRUE",
            (account_id,),
        )
        closed = 0
        for hid, ext_id, dist in cur.fetchall():
            if ext_id in seen_ext:
                continue
            if not statewide:
                row_dist = (dist or '').strip().casefold()
                if row_dist and row_dist not in touched:
                    continue
            cur.execute(
                """
                UPDATE ufone_maintenance_history
                SET is_open=FALSE, closed_at=NOW(), updated_at=NOW()
                WHERE id=%s
                """,
                (hid,),
            )
            closed += 1
    conn.commit()
    logger.info('maintenance archive upserted=%s closed=%s statewide=%s',
                n, closed, statewide)
    return n


def upsert_login_maintenance_history(conn, account_id: int, items: list) -> int:
    """Merge login-scoped closed history API rows into archive (is_open=False)."""
    ensure_maintenance_columns(conn)
    n = 0
    with conn.cursor() as cur:
        for raw in items or []:
            if not isinstance(raw, dict):
                continue
            mapped = map_maintenance_row(raw)
            if not mapped or mapped.get('ext_id') is None:
                continue
            ext_id = int(mapped['ext_id'])
            # Skip if still open in live cache
            cur.execute(
                "SELECT 1 FROM ufone_maintenance_cache "
                "WHERE account_id=%s AND (ext_id=%s OR UPPER(reg_no)=UPPER(%s)) "
                "LIMIT 1",
                (account_id, ext_id, mapped.get('reg_no') or ''),
            )
            if cur.fetchone():
                continue
            cur.execute(
                """
                INSERT INTO ufone_maintenance_history (
                  account_id, ext_id, reg_no, district, maintain_type, cat_name,
                  sub_cat_name, due_date, send_date, return_date, comments,
                  days_offline, hours, minute, created_by, created_date,
                  modified_by, modified_date, start_date, start_time,
                  end_date, end_time, is_open, first_seen_at, last_seen_at,
                  closed_at, created_at, updated_at
                ) VALUES (
                  %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                  %s,%s,FALSE,NOW(),NOW(),NOW(),NOW(),NOW()
                )
                ON CONFLICT (account_id, ext_id) DO UPDATE SET
                  reg_no=EXCLUDED.reg_no, district=EXCLUDED.district,
                  maintain_type=EXCLUDED.maintain_type, cat_name=EXCLUDED.cat_name,
                  sub_cat_name=EXCLUDED.sub_cat_name, due_date=EXCLUDED.due_date,
                  send_date=EXCLUDED.send_date, return_date=EXCLUDED.return_date,
                  comments=EXCLUDED.comments, days_offline=EXCLUDED.days_offline,
                  hours=EXCLUDED.hours, minute=EXCLUDED.minute,
                  created_by=EXCLUDED.created_by, created_date=EXCLUDED.created_date,
                  modified_by=EXCLUDED.modified_by,
                  modified_date=EXCLUDED.modified_date,
                  start_date=EXCLUDED.start_date, start_time=EXCLUDED.start_time,
                  end_date=EXCLUDED.end_date, end_time=EXCLUDED.end_time,
                  updated_at=NOW()
                WHERE ufone_maintenance_history.is_open = FALSE
                """,
                (
                    account_id, ext_id, mapped.get('reg_no'), mapped.get('district'),
                    mapped.get('maintain_type'), mapped.get('cat_name'),
                    mapped.get('sub_cat_name'), mapped.get('due_date'),
                    mapped.get('send_date'), mapped.get('return_date'),
                    mapped.get('comments'), mapped.get('days_offline') or 0,
                    mapped.get('hours'), mapped.get('minute'),
                    mapped.get('created_by'), mapped.get('created_date'),
                    mapped.get('modified_by'), mapped.get('modified_date'),
                    mapped.get('start_date'), mapped.get('start_time'),
                    mapped.get('end_date'), mapped.get('end_time'),
                ),
            )
            n += 1
    conn.commit()
    logger.info('login maintenance history merged=%s', n)
    return n


def upsert_tasks(conn, account_id: int, tasks: list) -> tuple[int, list]:
    """Upsert dashboard tasks. Returns (count, generate_notify_events).

    Generate fires when a task_id is first seen in ufone_task_cache (every ~3 min
    scan). Skips flood when cache was empty (first fill).
    """
    if not tasks:
        return 0, []
    events = []
    n = 0
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM ufone_task_cache WHERE account_id=%s LIMIT 1",
            (account_id,),
        )
        had_prior = cur.fetchone() is not None
        for t in tasks:
            tid = t.get('task_id')
            if not tid:
                continue
            cur.execute(
                "SELECT id FROM ufone_task_cache WHERE account_id=%s AND task_id=%s",
                (account_id, tid),
            )
            found = cur.fetchone()
            if found:
                cur.execute(
                    """
                    UPDATE ufone_task_cache SET
                      patient_name=%s, phone=%s, address=%s, ambulance_reg=%s,
                      status=%s, district=%s, tehsil=%s, facility=%s,
                      request_from=%s, distance=%s, is_transfer=%s, raw_json=%s,
                      updated_at=NOW()
                    WHERE id=%s
                    """,
                    (
                        t.get('patient_name'), t.get('phone'), t.get('address'),
                        t.get('ambulance_reg'), t.get('status'), t.get('district'),
                        t.get('tehsil'), t.get('facility'), t.get('request_from'),
                        t.get('distance'), t.get('is_transfer'), t.get('raw_json'),
                        found[0],
                    ),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO ufone_task_cache (
                      account_id, task_id, patient_name, phone, address, ambulance_reg,
                      status, district, tehsil, facility, request_from, distance,
                      is_transfer, raw_json, created_at, updated_at
                    ) VALUES (
                      %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),NOW()
                    )
                    """,
                    (
                        account_id, tid, t.get('patient_name'), t.get('phone'),
                        t.get('address'), t.get('ambulance_reg'), t.get('status'),
                        t.get('district'), t.get('tehsil'), t.get('facility'),
                        t.get('request_from'), t.get('distance'),
                        t.get('is_transfer'), t.get('raw_json'),
                    ),
                )
                if had_prior and not _status_is_complete(t.get('status')):
                    events.append({**_notify_payload_from_task(t), 'event': 'generate'})
            n += 1
    conn.commit()
    return n, events


_UFONE_REG_TAG_RE = re.compile(
    r'[\s\-]+(COW|USG\+P|USG|RAS|MNHC|EMS|NHP)\s*$',
    re.IGNORECASE,
)


def _norm_reg_key(val: str) -> str:
    s = (val or '').strip()
    s = _UFONE_REG_TAG_RE.sub('', s).strip()
    if ' ' in s:
        s = s.split()[0].strip()
    return re.sub(r'[^A-Za-z0-9]', '', s.upper())


def _strip_reg_tag(val: str) -> str:
    s = (val or '').strip()
    s = _UFONE_REG_TAG_RE.sub('', s).strip()
    if ' ' in s:
        s = s.split()[0].strip()
    return s


def _load_vehicle_project_reminder_map(conn) -> dict:
    """Map normalized vehicle_no → ufone_close_reminder_minutes (0 = off).

    Also indexes exact and base-token keys for Ufone tags like 'GBF-25-425 COW'.
    """
    # Ensure column exists on older DBs (Render may not have run migration yet)
    with conn.cursor() as cur:
        cur.execute(
            """
            ALTER TABLE project
            ADD COLUMN IF NOT EXISTS ufone_close_reminder_minutes INTEGER DEFAULT 0
            """
        )
    conn.commit()

    mapping = {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT v.vehicle_no, COALESCE(p.ufone_close_reminder_minutes, 0) AS mins
            FROM vehicle v
            LEFT JOIN project p ON p.id = v.project_id
            WHERE v.vehicle_no IS NOT NULL AND TRIM(v.vehicle_no) <> ''
            """
        )
        for vehicle_no, mins in cur.fetchall():
            vn = (vehicle_no or '').strip()
            if not vn:
                continue
            try:
                mins_i = int(mins or 0)
            except (TypeError, ValueError):
                mins_i = 0
            mapping[vn] = mins_i
            mapping[_norm_reg_key(vn)] = mins_i
            base = _strip_reg_tag(vn)
            if base and base != vn:
                mapping[base] = mins_i
                mapping[_norm_reg_key(base)] = mins_i
    return mapping


def _reminder_minutes_for_amb(amb_reg_no, reminder_map: dict) -> int:
    """Resolve project reminder minutes for an ambulance reg; 0 = off / unknown."""
    if not amb_reg_no or not reminder_map:
        return 0
    reg = str(amb_reg_no).strip()
    if not reg:
        return 0
    base = _strip_reg_tag(reg)
    for key in (reg, base, _norm_reg_key(reg), _norm_reg_key(base)):
        if key in reminder_map:
            return int(reminder_map[key] or 0)
    return 0


def collect_overdue_close_events(conn, account_id: int, tasks: list) -> list:
    """Open dashboard tasks past per-project threshold → one-shot overdue_close.

    Threshold comes from Project.ufone_close_reminder_minutes via Vehicle.project_id.
    0 / missing project / unmatched vehicle = skip (no reminder).
    """
    if not tasks:
        return []
    ensure_task_event_notify_table(conn)
    reminder_map = _load_vehicle_project_reminder_map(conn)
    events = []
    for t in tasks:
        tid = t.get('task_id')
        if not tid or _status_is_complete(t.get('status')):
            continue
        mins = t.get('minutes_created')
        if mins is None:
            continue
        threshold = _reminder_minutes_for_amb(t.get('ambulance_reg'), reminder_map)
        if threshold <= 0 or mins < threshold:
            continue
        # Mark AFTER delivery (in push_notify_events), not before send —
        # otherwise one failed POST/fanout permanently silences the reminder.
        if _event_already_marked(conn, account_id, tid, 'overdue_close'):
            continue
        bare = _bare_task_id(tid)
        if _task_notif_exists(conn, bare, _pk_now().date(),
                              _EVENT_NOTIF_TITLES['overdue_close']):
            # Delivered on an earlier cycle but mark was lost — heal it.
            _mark_event_notify_sent(conn, account_id, tid, 'overdue_close')
            continue
        payload = _notify_payload_from_task(t)
        payload['minutes_open'] = mins
        payload['event'] = 'overdue_close'
        events.append(payload)
    return events


def _coerce_str(val):
    if val is None:
        return None
    if isinstance(val, float) and val != val:  # NaN
        return None
    if isinstance(val, (int, float)):
        return str(val)
    s = str(val).strip()
    return s if s else None


def _parse_task_date(raw: dict, fallback: date) -> date:
    s = _coerce_str(raw.get('CreatedDate') or raw.get('CreatedDate1') or '')
    if not s:
        return fallback
    s0 = s.split()[0][:10]
    for fmt in ('%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y'):
        try:
            return datetime.strptime(s0, fmt).date()
        except ValueError:
            continue
    m = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{4})', s)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        except ValueError:
            pass
    return fallback


def map_emg_row(raw: dict, account_id: int, today: date) -> dict | None:
    tid = _coerce_str(raw.get('TaskId') or raw.get('id'))
    if not tid:
        return None
    fields = {}
    for api_key, db_col in REPORT_API_TO_EMG.items():
        val = _coerce_str(raw.get(api_key))
        if val is not None:
            fields[db_col] = val
    fields['task_id_ext'] = tid
    fields['task_date'] = _parse_task_date(raw, today)
    fields['upload_date'] = today
    fields['account_id'] = account_id
    fields['source'] = 'api'
    return fields


def upsert_emergency(conn, account_id: int, items: list, today: date,
                     *, skip_notify: bool = False) -> tuple[int, list]:
    """Bulk-write emergency report rows to Postgres (no Render HTTP).

    Returns (upsert_count, notify_events).
    - close: status transition to complete (primary close source)
    - generate: FALLBACK only when task was never in ufone_task_cache
      (dashboard is primary generate source every ~3 min)
    - skip_notify=True: used for historical one-day fetch (no driver floods)
    """
    if not items:
        return 0, []
    update_cols = [
        'request_from', 'phone', 'cli', 'name', 'husband', 'address', 'location',
        'house_color', 'door_color', 'nearest_landmark', 'edd', 'clinical_details',
        'district_name', 'tehsil_name', 'uc_name', 'amb_reg_no', 'status',
        'received_by', 'category', 'sub_category', 'facility_name', 'facility_code',
        'facility_type', 'change_facility_comments', 'excel_created_date',
        'completed_date_time', 'created_by', 'created_date1', 'created_time',
        'closing_remarks', 'task_closed_by', 'patient_cnic', 'patient_admission_no',
        'request_for', 'closed_by', 'caller_name', 'task_start_lat', 'task_start_lon',
        'task_end_lat', 'task_end_lon', 'ras_cow', 'distance_in_km',
        'nearrest_health_facility', 'task_date', 'upload_date', 'account_id', 'source',
    ]
    rows = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        row = map_emg_row(raw, account_id, today)
        if row:
            rows.append(row)
    if not rows:
        return 0, []

    # Prefer latest duplicate TaskId in the payload
    by_tid = {}
    for row in rows:
        by_tid[row['task_id_ext']] = row
    rows = list(by_tid.values())
    tids = [r['task_id_ext'] for r in rows]

    events = []
    # Close notifications only matter for Master Data (fleet) vehicles — only
    # their drivers have app logins. Filtering here keeps a mass-close Ufone
    # window (hundreds of closes in one report) from flooding the notify POST.
    fleet_keys = _fleet_reg_keys(conn)
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '180s'")
        # Any prior rows? (skip notify flood on empty DB first fill)
        cur.execute(
            "SELECT 1 FROM emergency_task_record "
            "WHERE task_id_ext IS NOT NULL AND task_id_ext <> '' LIMIT 1"
        )
        had_prior = cur.fetchone() is not None

        existing = {}  # tid -> (id, status, excel_created_date, created_date1, created_time)
        for i in range(0, len(tids), 500):
            chunk = tids[i:i + 500]
            cur.execute(
                """
                SELECT DISTINCT ON (task_id_ext)
                       id, task_id_ext, status,
                       excel_created_date, created_date1, created_time
                FROM emergency_task_record
                WHERE task_id_ext = ANY(%s)
                ORDER BY task_id_ext, task_date DESC NULLS LAST, id DESC
                """,
                (chunk,),
            )
            for rid, tid, st, ecd, cd1, ct in cur.fetchall():
                existing[tid] = (rid, st, ecd, cd1, ct)

        # task_ids already known to dashboard cache → skip EMG generate
        cached_tids = set()
        for i in range(0, len(tids), 500):
            chunk = tids[i:i + 500]
            cur.execute(
                """
                SELECT task_id FROM ufone_task_cache
                WHERE account_id=%s AND task_id = ANY(%s)
                """,
                (account_id, chunk),
            )
            for (tid,) in cur.fetchall():
                cached_tids.add(tid)

        to_update = []
        to_insert = []
        for row in rows:
            tid = row['task_id_ext']
            prior = existing.get(tid)
            new_status = row.get('status') or ''
            if (not skip_notify) and had_prior and row.get('task_date') == today:
                created_dt = (
                    row.get('excel_created_date')
                    or row.get('created_date1')
                    or row.get('created_time')
                    or (prior[2] if prior else None)
                    or (prior[3] if prior else None)
                    or (prior[4] if prior else None)
                    or ''
                )
                payload = {
                    'task_id': tid,
                    'amb_reg_no': row.get('amb_reg_no'),
                    'patient_name': row.get('name'),
                    'phone': row.get('phone'),
                    'cli': row.get('cli'),
                    'pickup': row.get('address') or '',
                    'destination': row.get('facility_name') or '',
                    'category': row.get('category') or '',
                    'completed_date_time': row.get('completed_date_time') or '',
                    'task_create_date_time': created_dt,
                }
                if prior is None:
                    # Fallback generate: dashboard never saw this task
                    if tid not in cached_tids and not _status_is_complete(new_status):
                        events.append({**payload, 'event': 'generate'})
                elif (not _status_is_complete(prior[1])
                      and _status_is_complete(new_status)):
                    # Fleet-only: non-fleet ambulances never match a driver on
                    # Render, so pushing them only wastes the notify budget.
                    if _amb_matches_fleet(row.get('amb_reg_no'), fleet_keys):
                        events.append({**payload, 'event': 'close'})

            if prior:
                to_update.append([row.get(c) for c in update_cols] + [prior[0]])
            else:
                to_insert.append(
                    [row['task_id_ext']] + [row.get(c) for c in update_cols]
                )

        if to_update:
            sets = ', '.join(f'{c}=%s' for c in update_cols)
            psycopg2.extras.execute_batch(
                cur,
                f"UPDATE emergency_task_record SET {sets}, synced_at=NOW() WHERE id=%s",
                to_update,
                page_size=100,
            )
        if to_insert:
            cols = ['task_id_ext'] + update_cols + ['synced_at', 'created_at']
            col_sql = ', '.join(cols)
            template = '(' + ','.join(['%s'] * (len(cols) - 2)) + ', NOW(), NOW())'
            psycopg2.extras.execute_values(
                cur,
                f"INSERT INTO emergency_task_record ({col_sql}) VALUES %s",
                to_insert,
                template=template,
                page_size=100,
            )
    conn.commit()
    logger.info('emg upserted update=%s insert=%s notify_events=%s',
                len(to_update), len(to_insert), len(events))
    # No cap: a mass-close window (hundreds of tasks closed between two EMG
    # scans) must not silently drop events — push_notify_events chunks them.
    return len(rows), events


def _open_task_ids_from_emg(emg_items: list) -> list:
    """Numeric TaskIds for incomplete/in-process rows only (deduped)."""
    open_ids = []
    seen = set()
    for raw in emg_items:
        if not isinstance(raw, dict):
            continue
        tid = str(raw.get('TaskId') or raw.get('id') or '').strip()
        if not tid or tid in seen:
            continue
        st = str(raw.get('Status') or '').lower()
        if 'complete' in st and 'incomplete' not in st:
            continue
        if 'cancel' in st:
            continue
        bare = tid.upper().replace('PHF-', '').strip()
        if not bare.isdigit():
            continue
        seen.add(tid)
        open_ids.append(bare)
    # Stable old → new among equals (TaskId ascending)
    open_ids.sort(key=lambda x: int(x))
    return open_ids


def _pick_stale_detail_batch(conn, account_id: int, open_ids: list,
                             limit: int) -> list:
    """Prefer never-synced, then oldest synced_at, then older TaskId.

    Industry-style cache backfill: fill gaps first, then refresh stalest.
    """
    if not open_ids or limit <= 0:
        return []
    synced = {}  # task_id -> synced_at (or None)
    with conn.cursor() as cur:
        for i in range(0, len(open_ids), 500):
            chunk = open_ids[i:i + 500]
            cur.execute(
                """
                SELECT task_id, synced_at
                FROM ufone_task_detail_cache
                WHERE account_id=%s AND task_id = ANY(%s)
                """,
                (account_id, chunk),
            )
            for tid, ts in cur.fetchall():
                synced[str(tid)] = ts

    def sort_key(tid: str):
        ts = synced.get(tid)
        # missing first (0), then by synced_at ascending, then TaskId asc
        if ts is None and tid not in synced:
            return (0, datetime.min, int(tid))
        if ts is None:
            return (0, datetime.min, int(tid))
        return (1, ts, int(tid))

    ranked = sorted(open_ids, key=sort_key)
    return ranked[:limit]


def upsert_task_details(conn, account_id: int, client, emg_items: list,
                        limit: int = 15) -> int:
    """Fetch getTaskDetail for open tasks (stale-first batch) → Render DB.

    Each EMG cycle takes up to `limit` open tasks:
      1) never cached
      2) oldest synced_at
      3) older TaskId (old → new)
    So 70 open rotate fairly without hammering the portal.
    """
    if not emg_items:
        return 0
    limit = max(1, int(limit or 15))
    open_ids = _open_task_ids_from_emg(emg_items)
    if not open_ids:
        return 0
    batch = _pick_stale_detail_batch(conn, account_id, open_ids, limit)
    if not batch:
        return 0
    logger.info(
        'task detail batch %s/%s open (stale-first): %s',
        len(batch), len(open_ids), ','.join(batch[:5]) + ('…' if len(batch) > 5 else ''),
    )

    # Avoid racing on-demand detail HTTP with the same Ufone session.
    try:
        from detail_ops import UFONE_IO_LOCK
    except Exception:
        UFONE_IO_LOCK = None  # type: ignore

    n = 0
    with conn.cursor() as cur:
        for bare in batch:
            try:
                if UFONE_IO_LOCK is not None:
                    UFONE_IO_LOCK.acquire()
                try:
                    detail = client.get_task_detail(bare, quick=True) or {}
                    if not isinstance(detail, dict) or not detail:
                        continue
                    comments = []
                    try:
                        comments = client.get_task_comments(bare, quick=True) or []
                    except Exception:
                        comments = []
                finally:
                    if UFONE_IO_LOCK is not None:
                        UFONE_IO_LOCK.release()
                status = str(detail.get('Status') or '')
                detail_json = json.dumps(detail, default=str)
                comments_json = json.dumps(comments, default=str)
                cur.execute(
                    """
                    SELECT id FROM ufone_task_detail_cache
                    WHERE account_id=%s AND task_id=%s
                    """,
                    (account_id, bare),
                )
                found = cur.fetchone()
                if found:
                    cur.execute(
                        """
                        UPDATE ufone_task_detail_cache SET
                          detail_json=%s, comments_json=%s, task_status=%s,
                          synced_at=NOW()
                        WHERE id=%s
                        """,
                        (detail_json, comments_json, status, found[0]),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO ufone_task_detail_cache (
                          account_id, task_id, detail_json, comments_json,
                          task_status, synced_at, created_at
                        ) VALUES (%s,%s,%s,%s,%s,NOW(),NOW())
                        """,
                        (account_id, bare, detail_json, comments_json, status),
                    )
                n += 1
            except Exception as e:
                logger.warning('task detail %s failed: %s', bare, e)
    conn.commit()
    return n


_NOTIFY_CHUNK = 80
_NOTIFY_EVENT_PRIORITY = {
    'generate': 0,
    'close': 1,
    'overdue_close': 2,
}


def _sort_notify_events(events: list) -> list:
    """Prefer generate so new-task alerts are not starved by close/overdue flood."""
    return sorted(
        events,
        key=lambda ev: (
            _NOTIFY_EVENT_PRIORITY.get((ev or {}).get('event'), 9),
            str((ev or {}).get('task_id') or ''),
        ),
    )


def push_notify_events(
    events: list,
    *,
    conn=None,
    account_id: int | None = None,
) -> int:
    """POST tiny generate/close events to Render in chunks (never drop / never bulk EMG).

    After each successful chunk, mark generate events so the fleet safety-net
    does not resend. Failed chunks stay unmarked → retried next cycle.
    """
    if not events:
        return 0
    token = _env('UFONE_BRIDGE_TOKEN')
    base = (_env('RENDER_BASE_URL') or _env('RENDER_INGEST_URL') or '').rstrip('/')
    if not token or not base:
        logger.warning('notify skipped — set RENDER_BASE_URL + UFONE_BRIDGE_TOKEN')
        return 0
    if base.endswith('/ingest'):
        base = base[: -len('/ingest')]
    if base.endswith('/api/ufone/bridge'):
        url = f'{base}/notify'
    else:
        url = f'{base}/api/ufone/bridge/notify'

    ordered = _sort_notify_events(_dedupe_notify_events(events))
    sent_total = 0
    try:
        import requests
        for i in range(0, len(ordered), _NOTIFY_CHUNK):
            chunk = ordered[i:i + _NOTIFY_CHUNK]
            r = requests.post(
                url,
                headers={
                    'X-Ufone-Bridge-Token': token,
                    'User-Agent': 'ufone-bridge-pg/1.0',
                },
                json={'events': chunk},
                timeout=60,
            )
            if r.status_code >= 400:
                logger.warning(
                    'notify HTTP %s chunk %s-%s: %s',
                    r.status_code, i, i + len(chunk), (r.text or '')[:200],
                )
                break
            sent_total += int((r.json() or {}).get('sent') or len(chunk))
            # Mark an event ONLY when its in-app notification actually exists
            # (deliver-verified). Failed fanout stays unmarked → retried by the
            # generate/close safety-nets and the overdue collector next cycle.
            if conn is not None and account_id is not None:
                try:
                    today = _pk_now().date()
                except Exception:
                    today = datetime.utcnow().date()
                for ev in chunk:
                    etype = ev.get('event')
                    titles = _EVENT_NOTIF_TITLES.get(etype)
                    if not titles:
                        continue
                    bare = _bare_task_id(ev.get('task_id'))
                    if _task_notif_exists(conn, bare, today, titles):
                        _mark_event_notify_sent(
                            conn, account_id, bare, etype,
                        )
        if len(ordered) > _NOTIFY_CHUNK:
            logger.info(
                'notify sent in %s chunk(s), events=%s sent=%s',
                (len(ordered) + _NOTIFY_CHUNK - 1) // _NOTIFY_CHUNK,
                len(ordered),
                sent_total,
            )
        return sent_total
    except Exception as e:
        logger.warning('notify failed: %s', e)
        return sent_total


def _pk_now() -> datetime:
    """Naive Pakistan local datetime (UTC+5)."""
    return datetime.utcnow() + timedelta(hours=5)


def _ambulance_stamp_path() -> Path:
    return Path(_env('UFONE_SESSION_DIR', str(ROOT / 'sessions'))) / 'last_ambulance_sync_date.txt'


def _districts_stamp_path() -> Path:
    return Path(_env('UFONE_SESSION_DIR', str(ROOT / 'sessions'))) / 'last_districts_sync_at.txt'


def _maintenance_stamp_path() -> Path:
    return Path(_env('UFONE_SESSION_DIR', str(ROOT / 'sessions'))) / 'last_maintenance_sync_at.txt'


def should_fetch_ambulances() -> bool:
    """getAmbulanceList only once per PK day at/after 23:00 (11:00 PM).

    BRIDGE_FORCE_AMBULANCES=1 → fetch this cycle (ops override).
    """
    if (_env('BRIDGE_FORCE_AMBULANCES') or '').lower() in ('1', 'true', 'yes', 'on'):
        return True
    now = _pk_now()
    if now.hour != 23:
        return False
    stamp = _ambulance_stamp_path()
    today = now.date().isoformat()
    try:
        if stamp.is_file() and stamp.read_text(encoding='utf-8').strip() == today:
            return False
    except Exception:
        pass
    return True


def mark_ambulances_fetched() -> None:
    stamp = _ambulance_stamp_path()
    try:
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text(_pk_now().date().isoformat(), encoding='utf-8')
    except Exception as e:
        logger.warning('could not write ambulance stamp: %s', e)


def _stamp_age_seconds(path: Path):
    try:
        if not path.is_file():
            return None
        text = path.read_text(encoding='utf-8').strip()
        if not text:
            return None
        try:
            return max(0.0, time.time() - float(text))
        except ValueError:
            dt = datetime.fromisoformat(text)
            return max(0.0, (_pk_now() - dt).total_seconds())
    except Exception:
        return None


def _write_stamp_now(path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(time.time()), encoding='utf-8')
    except Exception as e:
        logger.warning('could not write stamp %s: %s', path, e)


def should_fetch_districts() -> bool:
    """Districts master list — once per 24h."""
    if (_env('BRIDGE_FORCE_DISTRICTS') or '').lower() in ('1', 'true', 'yes', 'on'):
        return True
    interval = _int_env('BRIDGE_DISTRICTS_INTERVAL_SEC', 86400)
    age = _stamp_age_seconds(_districts_stamp_path())
    return age is None or age >= interval


def should_fetch_maintenance() -> bool:
    """Open under-maintenance — every 10 min."""
    if (_env('BRIDGE_FORCE_MAINTENANCE') or '').lower() in ('1', 'true', 'yes', 'on'):
        return True
    interval = _int_env('BRIDGE_MAINT_INTERVAL_SEC', 600)
    age = _stamp_age_seconds(_maintenance_stamp_path())
    return age is None or age >= interval


def run_once_for_account(account_id: int, username: str, password: str) -> dict:
    """One Ufone portal login + sync cycle for a single Fleet UI account."""
    session_dir = _env('UFONE_SESSION_DIR', str(ROOT / 'sessions'))
    Path(session_dir).mkdir(parents=True, exist_ok=True)
    os.environ['UFONE_SESSION_DIR'] = session_dir

    client = UfoneClient(username, password, session_key=f'bridge_{account_id}')
    logger.info(
        'connecting to Ufone account_id=%s username=%s…',
        account_id, username,
    )
    client.connect(reuse_session=True)
    today_d = _pk_today()
    today = today_d.strftime('%Y-%m-%d')
    logger.info('using PK calendar date %s (VPS UTC date would be %s)',
                today, date.today().isoformat())

    vehicles = []
    if should_fetch_ambulances():
        logger.info('fetching vehicles (daily 11:00 PM PKT window)…')
        vehicles = [normalize_ambulance(r) for r in (client.get_ambulance_list() or [])
                    if isinstance(r, dict) and r.get('Reg_No')]
        logger.info('vehicles=%s', len(vehicles))
        if vehicles:
            mark_ambulances_fetched()
    else:
        logger.info('skipping getAmbulanceList (only once daily at 11:00 PM PKT)')

    logger.info('fetching tasks…')
    skip_dash = (_env('BRIDGE_SKIP_DASHBOARD') or '0').lower() in ('1', 'true', 'yes')
    if skip_dash:
        tasks = []
        logger.info('skipping task dashboard this cycle')
    else:
        tasks = [normalize_task(r) for r in (client.get_task_dashboard(
            start_date=today, end_date=today, visit_page=False) or [])
            if isinstance(r, dict)]
        logger.info('tasks=%s', len(tasks))

    districts = []
    if should_fetch_districts():
        logger.info('fetching districts (24h cadence)…')
        try:
            raw_dist = client.get_districts_anonymous() or client.get_districts() or []
            for d in raw_dist:
                if not isinstance(d, dict):
                    continue
                code = d.get('district_code') or d.get('DistrictCode') or d.get('code')
                name = (d.get('district_name') or d.get('DistrictName')
                        or d.get('name') or d.get('District'))
                if code is not None and name:
                    districts.append({'code': str(code), 'name': str(name).strip()})
            if districts:
                _write_stamp_now(_districts_stamp_path())
            logger.info('districts=%s', len(districts))
        except Exception as e:
            logger.warning('districts fetch failed: %s', e)
    else:
        logger.info('skipping getDistrict (next fetch after 24h)')

    logger.info('fetching emergency report…')
    emg = []
    emg_by_day = []  # [(date, rows)] — upsert each day with its own default_task_date
    skip_emg = (_env('BRIDGE_SKIP_EMG') or '0').lower() in ('1', 'true', 'yes')
    if skip_emg:
        logger.info('skipping emergency report this cycle')
    else:
        lookback = emg_lookback_days()
        # 1) Always today — primary live feed
        try:
            today_rows = fetch_emg_report_day(client, today_d)
            emg.extend(today_rows)
            emg_by_day.append((today_d, today_rows))
            logger.info('emergency rows today(%s)=%s', today, len(today_rows))
        except Exception as e:
            logger.warning('emg fetch failed for today %s: %s', today, e)

        # 2) Previous dates ONLY if DB still has in-process tasks on that date.
        #    No open tasks on a prior date ⇒ no Ufone call for that date (low load).
        prev_dates = []
        try:
            qconn = db_connect()
            try:
                _pg_session(qconn)
                prev_dates = previous_open_emg_dates(
                    qconn, account_id, today_d, lookback)
            finally:
                qconn.close()
        except Exception as e:
            logger.warning('open-date lookup failed (today-only EMG): %s', e)

        if prev_dates:
            logger.info(
                'prior open EMG dates within %sd — fetching: %s',
                lookback, ','.join(d.isoformat() for d in prev_dates),
            )
            for prior in prev_dates:
                try:
                    prior_rows = fetch_emg_report_day(client, prior)
                    emg.extend(prior_rows)
                    emg_by_day.append((prior, prior_rows))
                    logger.info(
                        'emergency rows prior(%s)=%s',
                        prior.isoformat(), len(prior_rows),
                    )
                except Exception as e:
                    logger.warning(
                        'emg fetch failed for prior %s: %s', prior, e)
        else:
            logger.info(
                'no prior-day in-process tasks within %sd — '
                'skip prior EMG fetch (Ufone not called for past dates)',
                lookback,
            )

    maintenance_raw = []
    hist_raw = []
    did_fetch_maint = False
    if should_fetch_maintenance():
        did_fetch_maint = True
        try:
            # Anonymous statewide — logged-in Faisalabad session is 1 district only
            logger.info('fetching open maintenance (anonymous statewide, 10m)…')
            maintenance_raw = [
                r for r in (client.get_maintenance() or []) if isinstance(r, dict)
            ]
            dists = sorted({
                (r.get('District') or r.get('district') or '').strip()
                for r in maintenance_raw
                if (r.get('District') or r.get('district'))
            })
            logger.info('maintenance rows=%s districts=%s',
                        len(maintenance_raw), len(dists))
            _write_stamp_now(_maintenance_stamp_path())
        except Exception as e:
            logger.warning('maintenance fetch failed: %s', e)
            did_fetch_maint = False
        try:
            hist_from = (today_d - timedelta(days=90)).strftime('%Y-%m-%d')
            hist_raw = [
                r for r in (
                    client.get_maintenance_history(hist_from, today, "") or []
                ) if isinstance(r, dict)
            ]
            logger.info('login maintenance history rows=%s', len(hist_raw))
        except Exception as e:
            logger.warning('login maintenance history failed: %s', e)
    else:
        logger.info('skipping open maintenance (next fetch after 10 min)')

    logger.info('writing to Postgres…')
    conn = db_connect()
    notify_events = []
    nm = 0
    nh = 0
    ne = 0
    ndet = 0
    nd = 0
    nv = 0
    nt = 0
    nn = 0
    try:
        _pg_session(conn)
        nd = upsert_districts(conn, districts) if districts else 0
        nv = upsert_vehicles(conn, account_id, vehicles) if vehicles else 0
        nt, dash_events = upsert_tasks(conn, account_id, tasks)
        notify_events.extend(dash_events)
        try:
            overdue_events = collect_overdue_close_events(conn, account_id, tasks)
            notify_events.extend(overdue_events)
        except Exception as e:
            conn.rollback()
            logger.warning('overdue notify collect failed (non-fatal): %s', e)
        try:
            ne = 0
            for day_d, day_rows in emg_by_day:
                n, emg_events = upsert_emergency(
                    conn, account_id, day_rows, day_d)
                ne += n
                notify_events.extend(emg_events)
        except Exception as e:
            conn.rollback()
            logger.warning('emg pg upsert failed (non-fatal): %s', e)
        try:
            if did_fetch_maint:
                # Empty list still syncs so cleared portal list removes DB rows
                nm = upsert_maintenance(conn, account_id, maintenance_raw)
            if hist_raw:
                nh = upsert_login_maintenance_history(conn, account_id, hist_raw)
        except Exception as e:
            conn.rollback()
            logger.warning('maintenance pg upsert failed (non-fatal): %s', e)
        # Non-fleet open tasks: 15/batch every cycle.
        # Master-Data fleet is covered by fleet_fast_close_scan (1 min).
        try:
            detail_batch = max(1, _int_env('BRIDGE_DETAIL_BATCH', 15))
            ndet = upsert_nonfleet_task_details(
                conn, account_id, client, today_d, limit=detail_batch)
        except Exception as e:
            conn.rollback()
            logger.warning('non-fleet detail batch failed (non-fatal): %s', e)
        # Master Data vehicles: getTaskDetail every ~1 min for fast close
        try:
            fast_close = fleet_fast_close_scan(conn, account_id, client, today_d)
            notify_events.extend(fast_close)
        except Exception as e:
            conn.rollback()
            logger.warning('fleet fast-close scan failed (non-fatal): %s', e)
        # Fleet guarantee: retry any Master Data vehicle task still missing generate
        try:
            safety = collect_fleet_generate_safety_net(conn, account_id, today_d)
            notify_events.extend(safety)
        except Exception as e:
            conn.rollback()
            logger.warning('fleet generate safety-net failed (non-fatal): %s', e)
        # Fleet guarantee: retry any recently-closed fleet task still missing
        # its 'Task Complete' notification (dropped edge / failed push).
        try:
            close_safety = collect_fleet_close_safety_net(conn, account_id, today_d)
            notify_events.extend(close_safety)
        except Exception as e:
            conn.rollback()
            logger.warning('fleet close safety-net failed (non-fatal): %s', e)

        # Generate body needs Task Detail create time + CLI (dashboard lacks both)
        try:
            notify_events = enrich_generate_events_from_detail(
                client, notify_events, conn=conn, account_id=account_id,
            )
        except Exception as e:
            logger.warning('generate detail enrich failed (non-fatal): %s', e)

        # Chunked POST to Render (generate prioritized; mark only after success)
        nn = push_notify_events(
            notify_events, conn=conn, account_id=account_id,
        )
    finally:
        conn.close()

    logger.info(
        'pg ingest ok account_id=%s districts=%s vehicles=%s tasks=%s '
        'emg_pg=%s maint=%s hist=%s details=%s notify=%s '
        '(gen/overdue/close mix)',
        account_id, nd, nv, nt, ne, nm, nh, ndet, nn,
    )
    return {
        'account_id': account_id,
        'districts': nd, 'vehicles': nv, 'tasks': nt,
        'emergency_report': ne, 'maintenance': nm,
        'maintenance_history': nh,
        'task_details': ndet, 'notify': nn,
    }


def run_once() -> dict:
    """Sync using credentials from Fleet UI (ufone_account), else VPS env."""
    from ufone_creds import resolve_ufone_logins

    logins = resolve_ufone_logins()
    if not logins:
        raise RuntimeError('No Ufone login resolved')

    totals = {
        'districts': 0, 'vehicles': 0, 'tasks': 0,
        'emergency_report': 0, 'maintenance': 0,
        'maintenance_history': 0,
        'task_details': 0, 'notify': 0,
        'accounts': 0,
    }
    errors = []
    for account_id, username, password in logins:
        try:
            part = run_once_for_account(account_id, username, password)
            for k in totals:
                if k == 'accounts':
                    continue
                totals[k] += int(part.get(k) or 0)
            totals['accounts'] += 1
        except Exception as e:
            logger.error(
                'sync failed for account_id=%s username=%s: %s',
                account_id, username, e,
            )
            errors.append((account_id, e))
    if totals['accounts'] == 0 and errors:
        raise errors[0][1]
    return totals


def main() -> int:
    _load_dotenv(ROOT / '.env')
    once = '--once' in sys.argv
    interval = _int_env('BRIDGE_INTERVAL_SEC', 180)
    # On-demand Task Detail HTTP (Render → VPS) — same process as sync worker.
    if not once:
        try:
            from detail_ops import start_detail_http_server
            start_detail_http_server(background=True)
        except Exception as e:
            logger.warning('detail HTTP server failed to start: %s', e)
    # Single-instance lock — overlapping syncs hang on Ufone session + PG.
    lock_path = Path(_env('BRIDGE_LOCK_FILE', '/tmp/ufone-bridge.lock'))
    lock_fh = open(lock_path, 'w')
    try:
        import fcntl
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except Exception:
        logger.error('another bridge worker holds the lock — exiting')
        return 1
    failures = 0
    cycle = 0
    # Loop default 60s so fleet getTaskDetail can run every minute.
    # Dashboard / EMG gated by EVERY_N to keep their own cadence.
    emg_every = max(1, _int_env('BRIDGE_EMG_EVERY_N', 6))
    dash_every = max(1, _int_env('BRIDGE_DASHBOARD_EVERY_N', 1))
    while True:
        try:
            cycle += 1
            # (cycle-1) % n == 0 → runs on cycles 1, 1+n, 1+2n…
            # NOTE: `cycle % n == 1` breaks at n=1 (x % 1 is always 0).
            os.environ['BRIDGE_SKIP_EMG'] = (
                '0' if ((cycle - 1) % emg_every == 0) else '1'
            )
            os.environ['BRIDGE_SKIP_DASHBOARD'] = (
                '0' if ((cycle - 1) % dash_every == 0) else '1'
            )
            run_once()
            failures = 0
        except Exception as e:
            failures += 1
            logger.error('sync failed (%s): %s', failures, e)
            if once:
                return 1
        if once:
            return 0
        wait = interval if failures == 0 else min(interval * (2 ** min(failures, 3)), 900)
        logger.info('sleeping %ss', wait)
        time.sleep(wait)


if __name__ == '__main__':
    raise SystemExit(main())
