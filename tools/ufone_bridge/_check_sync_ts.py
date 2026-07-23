#!/usr/bin/env python3
"""One-shot: print cache/EMG sync timestamps vs UTC and PKT."""
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg2


def load_dotenv(path: Path) -> None:
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


def main() -> None:
    root = Path(__file__).resolve().parent
    load_dotenv(root / '.env')
    url = (os.environ.get('DATABASE_URL') or '').strip()
    if url.startswith('postgres://'):
        url = 'postgresql://' + url[len('postgres://'):]
    pkt = timezone(timedelta(hours=5))
    print('utc_now', datetime.now(timezone.utc).isoformat())
    print('pkt_now', datetime.now(pkt).isoformat())
    print('vps_date_today', datetime.utcnow().date().isoformat(), '(UTC)')
    print('pkt_date_today', datetime.now(pkt).date().isoformat())

    conn = psycopg2.connect(url, connect_timeout=20)
    cur = conn.cursor()
    cur.execute('SELECT MAX(updated_at), COUNT(*) FROM ufone_vehicle_cache')
    print('vehicles max_updated,count', cur.fetchone())
    cur.execute('SELECT MAX(updated_at), COUNT(*) FROM ufone_task_cache')
    print('tasks max_updated,count', cur.fetchone())
    cur.execute(
        'SELECT task_date, MAX(synced_at), COUNT(*) '
        'FROM emergency_task_record GROUP BY task_date '
        'ORDER BY task_date DESC LIMIT 5'
    )
    print('emg by task_date:')
    for row in cur.fetchall():
        print(' ', row)
    cur.execute('SELECT MAX(synced_at) FROM emergency_task_record')
    print('emg global max synced_at', cur.fetchone()[0])
    conn.close()


if __name__ == '__main__':
    main()
