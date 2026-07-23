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


def push_ingest(payload: dict) -> dict:
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
    r = requests.post(url, headers=headers, json=payload, timeout=120)
    if r.status_code >= 400:
        raise RuntimeError(f'ingest HTTP {r.status_code}: {r.text[:400]}')
    return r.json() if r.content else {'ok': True}


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
    vehicles_raw = client.get_ambulance_list() or []
    tasks_raw = client.get_task_dashboard(
        start_date=today, end_date=today, visit_page=False) or []
    emergency_raw = []
    try:
        emergency_raw = client.get_emergency_tasks(
            start_date=today, end_date=today, district='', visit_page=False) or []
    except Exception as e:
        logger.warning('emergency report fetch failed (continuing): %s', e)

    payload = {
        'account_id': account_id,
        'task_date': today,
        'vehicles_raw': [r for r in vehicles_raw if isinstance(r, dict)],
        'tasks_raw': [r for r in tasks_raw if isinstance(r, dict)],
        'emergency_report': [r for r in emergency_raw if isinstance(r, dict)],
        'source': 'pk-vps-bridge',
        'vps_host': _env('HOSTNAME') or os.uname().nodename if hasattr(os, 'uname') else '',
    }
    result = push_ingest(payload)
    logger.info(
        'ingest ok account=%s vehicles=%s tasks=%s emg=%s → %s',
        account_id,
        len(payload['vehicles_raw']),
        len(payload['tasks_raw']),
        len(payload['emergency_report']),
        json.dumps(result.get('result') or result)[:300],
    )
    return result


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
