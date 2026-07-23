#!/usr/bin/env python3
"""Ufone bridge worker that writes directly to Render Postgres (no HTTP ingest)."""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path

import psycopg2
import psycopg2.extras
import requests

from ufone_api_client import UfoneClient

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


def push_emg_http(account_id: int, items: list, today: str) -> int:
    """Optional small HTTP batches for emergency report (best-effort)."""
    token = _env('UFONE_BRIDGE_TOKEN')
    base = _env('RENDER_INGEST_URL').rstrip('/')
    if not token or not base or not items:
        return 0
    url = base if base.endswith('/ingest') else f'{base}/api/ufone/bridge/ingest'
    total = 0
    for i in range(0, len(items), 10):
        part = items[i:i + 10]
        try:
            r = requests.post(
                url,
                headers={'X-Ufone-Bridge-Token': token, 'User-Agent': 'ufone-bridge-pg/1.0'},
                json={'account_id': account_id, 'task_date': today, 'emergency_report': part},
                timeout=90,
            )
            if r.status_code < 400:
                total += (r.json().get('result') or {}).get('emergency_report', len(part))
            time.sleep(1.0)
        except Exception as e:
            logger.warning('emg http batch failed: %s', e)
            break
    return total


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
    client.connect(reuse_session=True)
    today = date.today().strftime('%Y-%m-%d')

    vehicles = [normalize_ambulance(r) for r in (client.get_ambulance_list() or [])
                if isinstance(r, dict) and r.get('Reg_No')]
    tasks = [normalize_task(r) for r in (client.get_task_dashboard(
        start_date=today, end_date=today, visit_page=False) or [])
        if isinstance(r, dict)]
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
    emg = []
    try:
        emg = [r for r in (client.get_emergency_tasks(
            start_date=today, end_date=today, district='', visit_page=False) or [])
            if isinstance(r, dict)]
    except Exception as e:
        logger.warning('emg fetch failed: %s', e)

    conn = db_connect()
    try:
        nd = upsert_districts(conn, districts)
        nv = upsert_vehicles(conn, account_id, vehicles)
        nt = upsert_tasks(conn, account_id, tasks)
    finally:
        conn.close()

    ne = push_emg_http(account_id, emg, today)
    logger.info('pg ingest ok districts=%s vehicles=%s tasks=%s emg_http=%s',
                nd, nv, nt, ne)
    return {'districts': nd, 'vehicles': nv, 'tasks': nt, 'emergency_report': ne}


def main() -> int:
    _load_dotenv(ROOT / '.env')
    once = '--once' in sys.argv
    interval = _int_env('BRIDGE_INTERVAL_SEC', 180)
    failures = 0
    while True:
        try:
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
