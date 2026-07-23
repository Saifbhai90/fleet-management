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
        'raw_json': json.dumps(raw, default=str),
    }


def db_connect():
    url = _env('DATABASE_URL')
    if not url:
        raise RuntimeError('DATABASE_URL required for PG bridge mode')
    if url.startswith('postgres://'):
        url = 'postgresql://' + url[len('postgres://'):]
    return psycopg2.connect(url, connect_timeout=30)


def _pg_session(conn) -> None:
    """Keep bridge writes from hanging the VPS worker forever."""
    with conn.cursor() as cur:
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


def upsert_tasks(conn, account_id: int, tasks: list) -> int:
    if not tasks:
        return 0
    # task_id unique per account may not have unique constraint; emulate upsert
    n = 0
    with conn.cursor() as cur:
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
            n += 1
    conn.commit()
    return n


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


def upsert_emergency(conn, account_id: int, items: list, today: date) -> int:
    """Bulk-write emergency report rows to Postgres (no Render HTTP)."""
    if not items:
        return 0
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
        return 0

    # Prefer latest duplicate TaskId in the payload
    by_tid = {}
    for row in rows:
        by_tid[row['task_id_ext']] = row
    rows = list(by_tid.values())
    tids = [r['task_id_ext'] for r in rows]

    with conn.cursor() as cur:
        cur.execute(
            "SET statement_timeout = '180s'"
        )
        # One lookup for all ids
        existing = {}
        for i in range(0, len(tids), 500):
            chunk = tids[i:i + 500]
            cur.execute(
                """
                SELECT DISTINCT ON (task_id_ext) id, task_id_ext
                FROM emergency_task_record
                WHERE task_id_ext = ANY(%s)
                ORDER BY task_id_ext, task_date DESC NULLS LAST, id DESC
                """,
                (chunk,),
            )
            for rid, tid in cur.fetchall():
                existing[tid] = rid

        to_update = []
        to_insert = []
        for row in rows:
            rid = existing.get(row['task_id_ext'])
            if rid:
                to_update.append([row.get(c) for c in update_cols] + [rid])
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
            # execute_values injects VALUES lists; append NOW() via SQL template
            template = '(' + ','.join(['%s'] * (len(cols) - 2)) + ', NOW(), NOW())'
            psycopg2.extras.execute_values(
                cur,
                f"INSERT INTO emergency_task_record ({col_sql}) VALUES %s",
                to_insert,
                template=template,
                page_size=100,
            )
    conn.commit()
    logger.info('emg upserted update=%s insert=%s', len(to_update), len(to_insert))
    return len(rows)


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

    logger.info('fetching vehicles…')
    vehicles = [normalize_ambulance(r) for r in (client.get_ambulance_list() or [])
                if isinstance(r, dict) and r.get('Reg_No')]
    logger.info('vehicles=%s; fetching tasks…', len(vehicles))
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
    try:
        _pg_session(conn)
        nd = upsert_districts(conn, districts)
        nv = upsert_vehicles(conn, account_id, vehicles)
        nt = upsert_tasks(conn, account_id, tasks)
        ne = 0
        try:
            ne = upsert_emergency(conn, account_id, emg, today_d)
        except Exception as e:
            conn.rollback()
            logger.warning('emg pg upsert failed (non-fatal): %s', e)
    finally:
        conn.close()

    logger.info('pg ingest ok districts=%s vehicles=%s tasks=%s emg_pg=%s',
                nd, nv, nt, ne)
    return {'districts': nd, 'vehicles': nv, 'tasks': nt, 'emergency_report': ne}


def main() -> int:
    _load_dotenv(ROOT / '.env')
    once = '--once' in sys.argv
    interval = _int_env('BRIDGE_INTERVAL_SEC', 180)
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
