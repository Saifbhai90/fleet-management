#!/usr/bin/env python3
"""On-demand Task Detail HTTP server for PK VPS.

Render cannot TLS to bpocops; UI opens Task Detail → Render asks this
server → VPS fetches getTaskDetail + comments from Ufone → writes
ufone_task_detail_cache on Render Postgres → returns JSON.

Auth: header X-Ufone-Bridge-Token (same UFONE_BRIDGE_TOKEN as notify).
"""
from __future__ import annotations

import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger('ufone-bridge.detail')

# Shared with worker sync so Ufone session isn't used concurrently.
UFONE_IO_LOCK = threading.Lock()

_ROOT = Path(__file__).resolve().parent
_client = None
_client_lock = threading.Lock()


def _env(name: str, default: str = '') -> str:
    return (os.environ.get(name) or default).strip()


def _int_env(name: str, default: int) -> int:
    try:
        return int(_env(name) or default)
    except ValueError:
        return default


def _load_dotenv() -> None:
    path = _ROOT / '.env'
    if not path.is_file():
        return
    for line in path.read_text(encoding='utf-8', errors='ignore').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, _, v = line.partition('=')
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _db_connect():
    import psycopg2
    url = _env('DATABASE_URL')
    if not url:
        raise RuntimeError('DATABASE_URL required')
    if url.startswith('postgres://'):
        url = 'postgresql://' + url[len('postgres://'):]
    conn = psycopg2.connect(url, connect_timeout=20)
    with conn.cursor() as cur:
        cur.execute("SET TIME ZONE 'Asia/Karachi'")
        cur.execute("SET statement_timeout = '60s'")
    conn.commit()
    return conn


def _get_client():
    """Reuse one UfoneClient (session) for on-demand fetches."""
    global _client
    from ufone_api_client import UfoneClient
    with _client_lock:
        if _client is not None:
            return _client
        username = _env('UFONE_USERNAME')
        password = _env('UFONE_PASSWORD')
        account_id = _int_env('UFONE_ACCOUNT_ID', 1)
        if not username or not password:
            raise RuntimeError('UFONE_USERNAME/PASSWORD required')
        session_dir = _env('UFONE_SESSION_DIR', str(_ROOT / 'sessions'))
        Path(session_dir).mkdir(parents=True, exist_ok=True)
        os.environ['UFONE_SESSION_DIR'] = session_dir
        _client = UfoneClient(
            username, password, session_key=f'bridge_ondemand_{account_id}'
        )
        _client.connect(reuse_session=True)
        return _client


def fetch_and_store_one_task_detail(account_id: int, task_id) -> dict:
    """Fetch detail+comments from Ufone, upsert Postgres, return payload.

    Returns {ok, task_id, detail, comments, error?}.
    """
    bare = str(task_id or '').strip()
    if bare.upper().startswith('PHF-'):
        bare = bare[4:].strip()
    if not bare.isdigit():
        return {'ok': False, 'error': 'invalid task_id', 'task_id': str(task_id)}

    with UFONE_IO_LOCK:
        client = _get_client()
        try:
            detail = client.get_task_detail(bare, quick=True) or {}
        except Exception as e:
            logger.warning('getTaskDetail %s failed: %s', bare, e)
            return {'ok': False, 'error': f'detail fetch failed: {e}'[:200], 'task_id': bare}
        if not isinstance(detail, dict) or not detail:
            return {'ok': False, 'error': 'empty detail', 'task_id': bare}
        comments = []
        try:
            comments = client.get_task_comments(bare, quick=True) or []
        except Exception as e:
            logger.warning('getTaskComments %s failed: %s', bare, e)
            comments = []
        if not isinstance(comments, list):
            comments = []

    status = str(detail.get('Status') or '')
    detail_json = json.dumps(detail, default=str)
    comments_json = json.dumps(comments, default=str)
    conn = _db_connect()
    try:
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
    finally:
        conn.close()

    return {
        'ok': True,
        'task_id': bare,
        'detail': detail,
        'comments': comments,
    }


def fetch_and_store_emg_day(account_id: int, day: str) -> dict:
    """Fetch getAmbulanceTaskReport for ONE calendar day and upsert Postgres.

    From must equal To (caller-enforced). skip_notify so historical import
    does not flood drivers with generate/close events.
    """
    from datetime import date as _date

    day = (day or '').strip()
    if not _is_ymd(day):
        return {'ok': False, 'error': 'invalid date (YYYY-MM-DD)', 'date': day}
    try:
        day_d = _date.fromisoformat(day)
    except ValueError:
        return {'ok': False, 'error': 'invalid date', 'date': day}

    with UFONE_IO_LOCK:
        client = _get_client()
        try:
            raw = client._call(
                'ReportEmergencyTask.aspx', 'getAmbulanceTaskReport',
                {
                    'startDate': client._to_ufone_date(day),
                    'endDate': client._to_ufone_date(day),
                    'District': '', 'Tehsil': '', 'UnionCouncil': '', 'TaskId': '',
                },
                visit_page=False, timeout=90, retries=1,
            )
        except Exception as e:
            logger.warning('emg-day %s fetch failed: %s', day, e)
            return {'ok': False, 'error': f'Ufone fetch failed: {e}'[:200], 'date': day}

    items = [r for r in (raw or []) if isinstance(r, dict)]
    if not items:
        return {'ok': True, 'count': 0, 'date': day, 'warning': 'Ufone returned 0 rows'}

    # Lazy import — worker_pg imports detail_ops at runtime (avoid cycle)
    from worker_pg import upsert_emergency

    conn = _db_connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '180s'")
        count, _events = upsert_emergency(
            conn, account_id, items, day_d, skip_notify=True,
        )
        conn.commit()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.exception('emg-day upsert failed')
        return {'ok': False, 'error': f'DB upsert failed: {e}'[:200], 'date': day}
    finally:
        conn.close()

    return {'ok': True, 'count': int(count or 0), 'date': day}


def _is_ymd(s: str) -> bool:
    if not s or len(s) != 10:
        return False
    if s[4] != '-' or s[7] != '-':
        return False
    return s[:4].isdigit() and s[5:7].isdigit() and s[8:10].isdigit()


class _DetailHandler(BaseHTTPRequestHandler):
    server_version = 'UfoneDetailServer/1.0'

    def log_message(self, fmt, *args):
        logger.info('%s - ' + fmt, self.address_string(), *args)

    def _token_ok(self) -> bool:
        expected = _env('UFONE_BRIDGE_TOKEN')
        if not expected:
            return False
        got = (self.headers.get('X-Ufone-Bridge-Token') or '').strip()
        return got == expected

    def _send(self, code: int, payload: dict):
        body = json.dumps(payload, default=str).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ('/health', '/'):
            self._send(200, {'ok': True, 'service': 'ufone-detail'})
            return
        self._send(404, {'ok': False, 'error': 'not found'})

    def do_POST(self):
        path = urlparse(self.path).path
        if path in ('/task-detail', '/api/task-detail'):
            self._handle_task_detail()
            return
        if path in ('/emg-day', '/api/emg-day'):
            self._handle_emg_day()
            return
        self._send(404, {'ok': False, 'error': 'not found'})

    def _handle_task_detail(self):
        if not self._token_ok():
            self._send(401, {'ok': False, 'error': 'unauthorized'})
            return
        length = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(length) if length > 0 else b'{}'
        try:
            data = json.loads(raw.decode('utf-8') or '{}')
        except Exception:
            self._send(400, {'ok': False, 'error': 'invalid json'})
            return
        task_id = data.get('task_id') or data.get('id')
        account_id = int(data.get('account_id') or _int_env('UFONE_ACCOUNT_ID', 1))
        try:
            result = fetch_and_store_one_task_detail(account_id, task_id)
            code = 200 if result.get('ok') else 502
            self._send(code, result)
        except Exception as e:
            logger.exception('task-detail failed')
            self._send(500, {'ok': False, 'error': str(e)[:300]})

    def _handle_emg_day(self):
        if not self._token_ok():
            self._send(401, {'ok': False, 'error': 'unauthorized'})
            return
        length = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(length) if length > 0 else b'{}'
        try:
            data = json.loads(raw.decode('utf-8') or '{}')
        except Exception:
            self._send(400, {'ok': False, 'error': 'invalid json'})
            return
        from_date = (data.get('from_date') or data.get('date') or '').strip()
        to_date = (data.get('to_date') or data.get('date') or from_date or '').strip()
        if not from_date or not to_date:
            self._send(400, {'ok': False, 'error': 'from_date and to_date required'})
            return
        if from_date != to_date:
            self._send(400, {
                'ok': False,
                'error': 'From Date and To Date must be the same day (1 day only)',
            })
            return
        account_id = int(data.get('account_id') or _int_env('UFONE_ACCOUNT_ID', 1))
        try:
            result = fetch_and_store_emg_day(account_id, from_date)
            code = 200 if result.get('ok') else 502
            self._send(code, result)
        except Exception as e:
            logger.exception('emg-day failed')
            self._send(500, {'ok': False, 'error': str(e)[:300]})


def start_detail_http_server(background: bool = True) -> Optional[ThreadingHTTPServer]:
    """Bind 0.0.0.0:BRIDGE_DETAIL_PORT (default 8787)."""
    _load_dotenv()
    port = _int_env('BRIDGE_DETAIL_PORT', 8787)
    if port <= 0:
        logger.info('detail HTTP server disabled (BRIDGE_DETAIL_PORT=%s)', port)
        return None
    server = ThreadingHTTPServer(('0.0.0.0', port), _DetailHandler)
    logger.info('detail HTTP listening on 0.0.0.0:%s', port)
    if background:
        t = threading.Thread(target=server.serve_forever, name='detail-http', daemon=True)
        t.start()
    return server


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
    _load_dotenv()
    srv = start_detail_http_server(background=False)
    if srv:
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
