#!/usr/bin/env python3
"""One-shot: fetch Ufone from this machine and ingest into DATABASE_URL (Render Postgres).

Used to prove the bridge payload path when VPS SSH or Render HTTP token
is not yet available. Prefer the VPS HTTP worker in production.
"""
from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Load project .env for DATABASE_URL / SECRET_KEY without overriding existing env
for env_path in (ROOT / '.env', ROOT / '.env.local', Path(__file__).resolve().parent / '.env'):
    if not env_path.is_file():
        continue
    for line in env_path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, _, v = line.partition('=')
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v

os.environ.pop('LOCAL_DB_GUARANTEED', None)
os.environ['UFONE_SESSION_DIR'] = str(Path(__file__).resolve().parent / 'sessions')
Path(os.environ['UFONE_SESSION_DIR']).mkdir(exist_ok=True)

from ufone_api_client import UfoneClient  # noqa: E402


def main() -> int:
    username = os.environ.get('UFONE_USERNAME', 'Faisalabad').strip()
    password = os.environ.get('UFONE_PASSWORD', '').strip()
    if not password:
        # fall back to bridge .env
        bridge_env = Path(__file__).resolve().parent / '.env'
        if bridge_env.is_file():
            for line in bridge_env.read_text(encoding='utf-8').splitlines():
                if line.startswith('UFONE_PASSWORD='):
                    password = line.split('=', 1)[1].strip()
                if line.startswith('UFONE_USERNAME='):
                    username = line.split('=', 1)[1].strip() or username
    account_id = int(os.environ.get('UFONE_ACCOUNT_ID', '1'))
    if not password:
        print('UFONE_PASSWORD required', file=sys.stderr)
        return 1

    session_dir = Path(__file__).resolve().parent / 'sessions'
    session_dir.mkdir(exist_ok=True)
    os.environ['UFONE_SESSION_DIR'] = str(session_dir)

    client = UfoneClient(username, password, session_key=f'bridge_prod_{account_id}')
    client.connect(reuse_session=True)
    today = date.today().strftime('%Y-%m-%d')
    vehicles_raw = [r for r in (client.get_ambulance_list() or []) if isinstance(r, dict)]
    tasks_raw = [r for r in (client.get_task_dashboard(
        start_date=today, end_date=today, visit_page=False) or []) if isinstance(r, dict)]
    try:
        emg = [r for r in (client.get_emergency_tasks(
            start_date=today, end_date=today, district='', visit_page=False) or [])
            if isinstance(r, dict)]
    except Exception as e:
        print('emg warn:', e)
        emg = []

    from app import app
    from services.ufone_service import ingest_bridge_payload
    with app.app_context():
        result = ingest_bridge_payload(account_id, {
            'vehicles_raw': vehicles_raw,
            'tasks_raw': tasks_raw,
            'emergency_report': emg,
            'task_date': today,
        })
        print('PROD_INGEST', result)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
