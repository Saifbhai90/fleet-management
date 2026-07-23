#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pakistan VPS Ufone → Render bridge worker.

Fetches live ambulances / tasks / emergency report from bpocops.ufone.com
using a Pakistan IP, then POSTs raw payloads to Fleet Manager ingest API.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import date
from pathlib import Path

import requests

from ufone_api_client import UfoneClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger('ufone-bridge')

ROOT = Path(__file__).resolve().parent


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _, val = line.partition('=')
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def _env(name: str, default: str = '') -> str:
    return (os.environ.get(name) or default).strip()


def _int_env(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def push_ingest(payload: dict, retries: int = 3) -> dict:
    base = _env('RENDER_INGEST_URL').rstrip('/')
    token = _env('UFONE_BRIDGE_TOKEN')
    if not token:
        secret = _env('SECRET_KEY')
        if secret:
            import hashlib
            import hmac as _hmac
            token = _hmac.new(
                secret.encode('utf-8'), b'ufone-bridge-v1', hashlib.sha256
            ).hexdigest()
    if not base or not token:
        raise RuntimeError(
            'RENDER_INGEST_URL and UFONE_BRIDGE_TOKEN (or SECRET_KEY) required')
    url = base if base.endswith('/ingest') else f'{base}/api/ufone/bridge/ingest'
    headers = {
        'Content-Type': 'application/json',
        'X-Ufone-Bridge-Token': token,
        'User-Agent': 'ufone-bridge/1.0',
    }
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=180)
            if r.status_code >= 500 and attempt < retries:
                time.sleep(3 * attempt)
                continue
            if r.status_code >= 400:
                raise RuntimeError(f'ingest HTTP {r.status_code}: {r.text[:400]}')
            return r.json() if r.content else {'ok': True}
        except (requests.RequestException, RuntimeError) as e:
            last_err = e
            if attempt < retries:
                time.sleep(3 * attempt)
                continue
            raise
    raise RuntimeError(str(last_err))


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _to_float(val, default=0.0):
    try:
        if val is None or val == '':
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def normalize_ambulance(raw: dict) -> dict:
    lat = _to_float(raw.get('Latitude'))
    lon = _to_float(raw.get('Logitude'))  # Ufone typo
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
    return {
        'id': raw.get('id'),
        'task_id': raw.get('TaskId') or raw.get('id'),
        'patient_name': raw.get('name') or raw.get('Name'),
        'phone': raw.get('phone') or raw.get('Phone'),
        'address': raw.get('address') or raw.get('Address'),
        'ambulance': raw.get('Ambulance') or raw.get('ambRegNo'),
        'status': raw.get('Status'),
        'district': (raw.get('district_name') or raw.get('DistrictName')
                     or raw.get('District')),
        'tehsil': (raw.get('tehsil_name') or raw.get('TehsilName')
                   or raw.get('Tehsil')),
        'facility_name': raw.get('facility_name') or raw.get('FacilityName'),
        'request_from': raw.get('RequestFrom'),
        'is_transfer': raw.get('isTransfer') or raw.get('isTransfer2'),
        'created_date': raw.get('CD') or raw.get('CreatedDate'),
        'distance': _to_float(raw.get('Distance') or raw.get('distanceInKM'), None),
        'driver_name': raw.get('Driver_Name'),
        'driver_cell': raw.get('Driver_Cell'),
        'category': raw.get('Category'),
    }


def run_once() -> dict:
    username = _env('UFONE_USERNAME')
    password = _env('UFONE_PASSWORD')
    account_id = _int_env('UFONE_ACCOUNT_ID', 1)
    if not username or not password:
        raise RuntimeError('UFONE_USERNAME and UFONE_PASSWORD required')

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
    emergency_raw = []
    try:
        emergency_raw = [r for r in (client.get_emergency_tasks(
            start_date=today, end_date=today, district='', visit_page=False) or [])
            if isinstance(r, dict)]
    except Exception as e:
        logger.warning('emergency report fetch failed (continuing): %s', e)

    host = _env('HOSTNAME') or (os.uname().nodename if hasattr(os, 'uname') else '')
    batch = _int_env('BRIDGE_VEHICLE_BATCH', 25)
    totals = {'vehicles': 0, 'tasks': 0, 'emergency_report': 0}

    for part in _chunks(vehicles, batch):
        res = push_ingest({
            'account_id': account_id,
            'task_date': today,
            'vehicles': part,
            'source': 'pk-vps-bridge',
            'vps_host': host,
        })
        totals['vehicles'] += (res.get('result') or {}).get('vehicles', len(part))
        time.sleep(0.8)

    if tasks:
        res = push_ingest({
            'account_id': account_id,
            'task_date': today,
            'tasks': tasks,
            'source': 'pk-vps-bridge',
            'vps_host': host,
        })
        totals['tasks'] = (res.get('result') or {}).get('tasks', len(tasks))

    for part in _chunks(emergency_raw, 25):
        res = push_ingest({
            'account_id': account_id,
            'task_date': today,
            'emergency_report': part,
            'source': 'pk-vps-bridge',
            'vps_host': host,
        })
        totals['emergency_report'] += (res.get('result') or {}).get(
            'emergency_report', len(part))
        time.sleep(0.8)

    logger.info(
        'ingest ok account=%s vehicles=%s/%s tasks=%s/%s emg=%s/%s',
        account_id,
        totals['vehicles'], len(vehicles),
        totals['tasks'], len(tasks),
        totals['emergency_report'], len(emergency_raw),
    )
    return {'ok': True, 'result': totals}


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
        # Back off a bit on repeated failures (cap 15 min)
        wait = interval if failures == 0 else min(interval * (2 ** min(failures, 3)), 900)
        logger.info('sleeping %ss', wait)
        time.sleep(wait)


if __name__ == '__main__':
    raise SystemExit(main())
