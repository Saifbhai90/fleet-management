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
        'raw_json': json.dumps(raw, default=str),
    }


def _notify_payload_from_task(t: dict) -> dict:
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
        'minutes_open': t.get('minutes_created'),
    }


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


def _status_is_complete(status) -> bool:
    s = (status or '').strip().lower()
    return ('complete' in s) and ('incomplete' not in s)


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


def _norm_reg_key(val: str) -> str:
    return re.sub(r'[^A-Za-z0-9]', '', (val or '').upper())


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
            base = vn.split()[0].strip()
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
    base = reg.split()[0].strip() if ' ' in reg else reg
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
        if not _mark_event_notify_sent(conn, account_id, tid, 'overdue_close'):
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
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '180s'")
        # Any prior rows? (skip notify flood on empty DB first fill)
        cur.execute(
            "SELECT 1 FROM emergency_task_record "
            "WHERE task_id_ext IS NOT NULL AND task_id_ext <> '' LIMIT 1"
        )
        had_prior = cur.fetchone() is not None

        existing = {}  # tid -> (id, status)
        for i in range(0, len(tids), 500):
            chunk = tids[i:i + 500]
            cur.execute(
                """
                SELECT DISTINCT ON (task_id_ext) id, task_id_ext, status
                FROM emergency_task_record
                WHERE task_id_ext = ANY(%s)
                ORDER BY task_id_ext, task_date DESC NULLS LAST, id DESC
                """,
                (chunk,),
            )
            for rid, tid, st in cur.fetchall():
                existing[tid] = (rid, st)

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
                }
                if prior is None:
                    # Fallback generate: dashboard never saw this task
                    if tid not in cached_tids and not _status_is_complete(new_status):
                        events.append({**payload, 'event': 'generate'})
                elif (not _status_is_complete(prior[1])
                      and _status_is_complete(new_status)):
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
    return len(rows), events[:40]


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


def push_notify_events(events: list) -> int:
    """POST tiny generate/close events to Render (never bulk EMG)."""
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
    try:
        import requests
        r = requests.post(
            url,
            headers={'X-Ufone-Bridge-Token': token, 'User-Agent': 'ufone-bridge-pg/1.0'},
            json={'events': events},
            timeout=30,
        )
        if r.status_code >= 400:
            logger.warning('notify HTTP %s: %s', r.status_code, (r.text or '')[:200])
            return 0
        return int((r.json() or {}).get('sent') or len(events))
    except Exception as e:
        logger.warning('notify failed: %s', e)
        return 0


def _pk_now() -> datetime:
    """Naive Pakistan local datetime (UTC+5)."""
    return datetime.utcnow() + timedelta(hours=5)


def _ambulance_stamp_path() -> Path:
    return Path(_env('UFONE_SESSION_DIR', str(ROOT / 'sessions'))) / 'last_ambulance_sync_date.txt'


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


def run_once() -> dict:
    username = _env('UFONE_USERNAME')
    password = _env('UFONE_PASSWORD')
    account_id = _int_env('UFONE_ACCOUNT_ID', 1)
    if not username or not password:
        raise RuntimeError('UFONE_USERNAME/PASSWORD required')

    session_dir = _env('UFONE_SESSION_DIR', str(ROOT / 'sessions'))
    Path(session_dir).mkdir(parents=True, exist_ok=True)
    os.environ['UFONE_SESSION_DIR'] = session_dir

    client = UfoneClient(username, password, session_key=f'bridge_{account_id}')
    logger.info('connecting to Ufone…')
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
    tasks = [normalize_task(r) for r in (client.get_task_dashboard(
        start_date=today, end_date=today, visit_page=False) or [])
        if isinstance(r, dict)]
    logger.info('tasks=%s; fetching districts…', len(tasks))
    districts = []
    try:
        for d in (client.get_districts() or []):
            if not isinstance(d, dict):
                continue
            code = d.get('district_code') or d.get('DistrictCode') or d.get('code')
            name = (d.get('district_name') or d.get('DistrictName')
                    or d.get('name') or d.get('District'))
            if code is not None and name:
                districts.append({'code': str(code), 'name': str(name).strip()})
    except Exception as e:
        logger.warning('districts fetch failed: %s', e)
    logger.info('districts=%s; fetching emergency report…', len(districts))
    emg = []
    skip_emg = (_env('BRIDGE_SKIP_EMG') or '0').lower() in ('1', 'true', 'yes')
    if skip_emg:
        logger.info('skipping emergency report this cycle')
    else:
        try:
            emg_raw = client._call(
                "ReportEmergencyTask.aspx", "getAmbulanceTaskReport",
                {
                    "startDate": client._to_ufone_date(today),
                    "endDate": client._to_ufone_date(today),
                    "District": "", "Tehsil": "", "UnionCouncil": "", "TaskId": "",
                },
                visit_page=False, timeout=60, retries=1,
            ) or []
            emg = [r for r in emg_raw if isinstance(r, dict)]
            logger.info('emergency rows=%s', len(emg))
        except Exception as e:
            logger.warning('emg fetch failed: %s', e)

    logger.info('writing to Postgres…')
    conn = db_connect()
    notify_events = []
    try:
        _pg_session(conn)
        nd = upsert_districts(conn, districts)
        nv = upsert_vehicles(conn, account_id, vehicles) if vehicles else 0
        nt, dash_events = upsert_tasks(conn, account_id, tasks)
        notify_events.extend(dash_events)
        try:
            overdue_events = collect_overdue_close_events(conn, account_id, tasks)
            notify_events.extend(overdue_events)
        except Exception as e:
            conn.rollback()
            logger.warning('overdue notify collect failed (non-fatal): %s', e)
        ne = 0
        ndet = 0
        try:
            ne, emg_events = upsert_emergency(conn, account_id, emg, today_d)
            notify_events.extend(emg_events)
        except Exception as e:
            conn.rollback()
            logger.warning('emg pg upsert failed (non-fatal): %s', e)
        if emg:
            try:
                detail_batch = max(1, _int_env('BRIDGE_DETAIL_BATCH', 15))
                ndet = upsert_task_details(
                    conn, account_id, client, emg, limit=detail_batch)
            except Exception as e:
                conn.rollback()
                logger.warning('task detail sync failed (non-fatal): %s', e)
    finally:
        conn.close()

    # Cap batch size for Render notify endpoint
    notify_events = notify_events[:80]
    nn = push_notify_events(notify_events)
    logger.info(
        'pg ingest ok districts=%s vehicles=%s tasks=%s emg_pg=%s details=%s notify=%s '
        '(gen/overdue/close mix)',
        nd, nv, nt, ne, ndet, nn,
    )
    return {
        'districts': nd, 'vehicles': nv, 'tasks': nt,
        'emergency_report': ne, 'task_details': ndet, 'notify': nn,
    }


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
    emg_every = max(1, _int_env('BRIDGE_EMG_EVERY_N', 2))  # EMG every Nth cycle
    while True:
        try:
            cycle += 1
            # Patch run_once via env flag for this cycle
            os.environ['BRIDGE_SKIP_EMG'] = '0' if (cycle % emg_every == 1) else '1'
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
