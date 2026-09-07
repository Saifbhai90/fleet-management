#!/usr/bin/env python3
"""On-demand Task Detail HTTP server for PK VPS.

Render cannot TLS to bpocops; UI opens Task Detail → Render asks this
server → VPS fetches getTaskDetail + comments from Ufone → writes
ufone_task_detail_cache on Render Postgres → returns JSON.

Auth: header X-Ufone-Bridge-Token (same UFONE_BRIDGE_TOKEN as notify).
"""
from __future__ import annotations

import base64
import json
import logging
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger('ufone-bridge.detail')

# Shared with worker sync so Ufone session isn't used concurrently.
UFONE_IO_LOCK = threading.Lock()

_ROOT = Path(__file__).resolve().parent
# account_id -> UfoneClient (session per UI account)
_clients: dict = {}
_client_meta: dict = {}  # account_id -> (username,)
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


def _get_client(account_id: Optional[int] = None):
    """Reuse UfoneClient for on-demand fetches (login from UI/DB)."""
    from ufone_api_client import UfoneClient
    from ufone_creds import resolve_ufone_login, resolve_ufone_login_for_account

    with _client_lock:
        if account_id and int(account_id) > 0:
            aid, username, password = resolve_ufone_login_for_account(int(account_id))
        else:
            aid, username, password = resolve_ufone_login()

        meta = (username,)
        existing = _clients.get(aid)
        if existing is not None and _client_meta.get(aid) == meta:
            return existing

        session_dir = _env('UFONE_SESSION_DIR', str(_ROOT / 'sessions'))
        Path(session_dir).mkdir(parents=True, exist_ok=True)
        os.environ['UFONE_SESSION_DIR'] = session_dir
        client = UfoneClient(
            username, password, session_key=f'bridge_ondemand_{aid}'
        )
        client.connect(reuse_session=True)
        _clients[aid] = client
        _client_meta[aid] = meta
        return client


def fetch_maintenance_log_anon(maint_id, start_date: str = '') -> list:
    """Portal Update Log — anonymous statewide (PK VPS only)."""
    from ufone_api_client import UfoneClient

    mid = maint_id
    if mid is None or str(mid).strip() == '':
        return []
    with UFONE_IO_LOCK:
        client = UfoneClient('anon', 'anon')
        rows = client.get_maintenance_log(mid, start_date=start_date or '') or []
    return rows if isinstance(rows, list) else []


def _coerce_account_id(account_id) -> int:
    """Resolve a usable ufone_account.id when caller/env passes 0/empty."""
    try:
        aid = int(account_id or 0)
    except (TypeError, ValueError):
        aid = 0
    if aid > 0:
        return aid
    from ufone_creds import resolve_ufone_login

    resolved, _, _ = resolve_ufone_login()
    return int(resolved)


def fetch_and_store_one_task_detail(account_id: int, task_id) -> dict:
    """Fetch detail+comments from Ufone, upsert Postgres, return payload.

    Returns {ok, task_id, detail, comments, error?}.
    """
    bare = str(task_id or '').strip()
    if bare.upper().startswith('PHF-'):
        bare = bare[4:].strip()
    if not bare.isdigit():
        return {'ok': False, 'error': 'invalid task_id', 'task_id': str(task_id)}

    account_id = _coerce_account_id(account_id)

    with UFONE_IO_LOCK:
        client = _get_client(account_id)
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

    account_id = _coerce_account_id(account_id)

    day = (day or '').strip()
    if not _is_ymd(day):
        return {'ok': False, 'error': 'invalid date (YYYY-MM-DD)', 'date': day}
    try:
        day_d = _date.fromisoformat(day)
    except ValueError:
        return {'ok': False, 'error': 'invalid date', 'date': day}

    with UFONE_IO_LOCK:
        client = _get_client(account_id)
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


def _pgrep_running(pattern: str) -> bool:
    try:
        r = subprocess.run(
            ['pgrep', '-f', pattern],
            capture_output=True,
            text=True,
            timeout=3,
        )
        return r.returncode == 0 and bool((r.stdout or '').strip())
    except Exception:
        return False


def _run_text(argv: list, timeout: float = 5.0) -> str:
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            return ''
        return (r.stdout or '').strip()
    except Exception:
        return ''


def _process_etime(pattern: str) -> Optional[str]:
    """Return ps etime for first matching process, e.g. '07:53' or '1-02:10:03'."""
    try:
        r = subprocess.run(
            ['pgrep', '-f', pattern],
            capture_output=True,
            text=True,
            timeout=3,
        )
        pids = [p for p in (r.stdout or '').split() if p.isdigit()]
        if not pids:
            return None
        et = _run_text(['ps', '-o', 'etime=', '-p', pids[0]], timeout=3)
        return et or None
    except Exception:
        return None


def _read_phone_battery() -> dict:
    """Best-effort Termux battery snapshot (termux-api)."""
    out = {
        'battery_pct': None,
        'battery_status': None,
        'battery_plugged': None,
        'battery_health': None,
        'battery_temp_c': None,
        'battery_charging': None,
        'battery_low': None,
    }
    try:
        raw = _run_text(['termux-battery-status'], timeout=5)
        if not raw:
            return out
        data = json.loads(raw)
        pct = data.get('percentage')
        try:
            pct_i = int(pct) if pct is not None else None
        except (TypeError, ValueError):
            pct_i = None
        plugged = (data.get('plugged') or '').strip() or None
        status = (data.get('status') or '').strip() or None
        charging = False
        if status and status.upper() == 'CHARGING':
            charging = True
        if plugged and plugged.upper() not in ('', 'UNPLUGGED'):
            charging = True
        out.update({
            'battery_pct': pct_i,
            'battery_status': status,
            'battery_plugged': plugged,
            'battery_health': (data.get('health') or None),
            'battery_temp_c': data.get('temperature'),
            'battery_charging': charging,
            'battery_low': bool(pct_i is not None and pct_i <= 15 and not charging),
        })
    except Exception:
        pass
    return out


def _read_phone_wifi() -> dict:
    out = {
        'wifi_ssid': None,
        'wifi_rssi': None,
        'wifi_link_mbps': None,
        'wifi_ip': None,
        'wifi_freq_mhz': None,
        'wifi_connected': None,
    }
    try:
        raw = _run_text(['termux-wifi-connectioninfo'], timeout=5)
        if not raw:
            return out
        data = json.loads(raw)
        ssid = (data.get('ssid') or '').strip()
        if ssid in ('<unknown ssid>', 'unknown ssid', '0x'):
            ssid = None
        rssi = data.get('rssi')
        try:
            rssi_i = int(rssi) if rssi is not None else None
        except (TypeError, ValueError):
            rssi_i = None
        link = data.get('link_speed_mbps')
        try:
            link_i = int(link) if link is not None else None
        except (TypeError, ValueError):
            link_i = None
        state = (data.get('supplicant_state') or '').upper()
        out.update({
            'wifi_ssid': ssid,
            'wifi_rssi': rssi_i,
            'wifi_link_mbps': link_i,
            'wifi_ip': (data.get('ip') or None),
            'wifi_freq_mhz': data.get('frequency_mhz'),
            'wifi_connected': bool(state == 'COMPLETED' or data.get('ip')),
        })
    except Exception:
        pass
    return out


def _read_phone_storage_mem() -> dict:
    out = {
        'storage_total_gb': None,
        'storage_used_gb': None,
        'storage_free_gb': None,
        'storage_pct': None,
        'mem_total_mb': None,
        'mem_used_mb': None,
        'mem_available_mb': None,
        'mem_used_pct': None,
        'load_1': None,
        'load_5': None,
        'load_15': None,
        'uptime_text': None,
    }
    try:
        # df -kP /data  → 1K blocks
        df = _run_text(['df', '-k', '/data'], timeout=4)
        lines = [ln for ln in df.splitlines() if ln.strip()]
        if len(lines) >= 2:
            parts = lines[-1].split()
            if len(parts) >= 4 and parts[1].isdigit():
                total_k = int(parts[1])
                used_k = int(parts[2])
                free_k = int(parts[3])
                out['storage_total_gb'] = round(total_k / (1024 * 1024), 1)
                out['storage_used_gb'] = round(used_k / (1024 * 1024), 1)
                out['storage_free_gb'] = round(free_k / (1024 * 1024), 1)
                out['storage_pct'] = round(100.0 * used_k / total_k, 1) if total_k else None
    except Exception:
        pass
    try:
        free = _run_text(['free', '-m'], timeout=4)
        for ln in free.splitlines():
            if ln.lower().startswith('mem:'):
                parts = ln.split()
                # Mem: total used free shared buff/cache available
                if len(parts) >= 7 and parts[1].isdigit():
                    total = int(parts[1])
                    used = int(parts[2])
                    avail = int(parts[6])
                    out['mem_total_mb'] = total
                    out['mem_used_mb'] = used
                    out['mem_available_mb'] = avail
                    out['mem_used_pct'] = round(100.0 * used / total, 1) if total else None
                break
    except Exception:
        pass
    try:
        up = _run_text(['uptime'], timeout=3)
        out['uptime_text'] = up or None
        # load average: a, b, c
        if 'load average:' in up:
            tail = up.split('load average:', 1)[1].strip()
            bits = [b.strip().rstrip(',') for b in tail.split(',')]
            if len(bits) >= 3:
                try:
                    out['load_1'] = float(bits[0])
                    out['load_5'] = float(bits[1])
                    out['load_15'] = float(bits[2])
                except ValueError:
                    pass
    except Exception:
        pass
    return out


def _build_phone_status() -> dict:
    """Snapshot for System Health: processes + Ufone/network/device."""
    import time as _t
    from urllib.request import urlopen, Request

    home = Path('/data/data/com.termux/files/home')
    detail_ok = False
    detail_ms = None
    try:
        t0 = _t.perf_counter()
        with urlopen('http://127.0.0.1:8787/health', timeout=3) as r:
            detail_ok = r.status == 200
        detail_ms = round((_t.perf_counter() - t0) * 1000)
    except Exception:
        detail_ok = False

    ufone_ok = False
    ufone_ms = None
    try:
        t0 = _t.perf_counter()
        req = Request(
            'https://bpocops.ufone.com/login.aspx',
            headers={'User-Agent': 'ufone-phone-status/1.0'},
        )
        with urlopen(req, timeout=8) as r:
            ufone_ok = int(getattr(r, 'status', 200) or 200) < 500
        ufone_ms = round((_t.perf_counter() - t0) * 1000)
    except Exception:
        ufone_ok = False

    public_ip = None
    try:
        with urlopen('https://ifconfig.me/ip', timeout=5) as r:
            public_ip = (r.read() or b'').decode('utf-8', errors='replace').strip()[:64]
    except Exception:
        try:
            with urlopen('https://api.ipify.org', timeout=5) as r:
                public_ip = (r.read() or b'').decode('utf-8', errors='replace').strip()[:64]
        except Exception:
            public_ip = None

    battery = _read_phone_battery()
    wifi = _read_phone_wifi()
    host_stats = _read_phone_storage_mem()

    worker = _pgrep_running('worker_pg.py')
    cloudflared = _pgrep_running('cloudflared tunnel')
    sshd = _pgrep_running('sshd')
    autossh = _pgrep_running('autossh')
    watch = _pgrep_running('watch_tunnel.sh')
    vps_disabled = (home / 'remote' / 'DISABLE_VPS_TUNNEL').is_file()
    worker_etime = _process_etime('python worker_pg.py') if worker else None
    cloudflared_etime = _process_etime('cloudflared tunnel') if cloudflared else None

    storage_low = bool(
        host_stats.get('storage_pct') is not None and host_stats['storage_pct'] >= 90
    )
    wifi_weak = bool(
        wifi.get('wifi_connected')
        and wifi.get('wifi_rssi') is not None
        and wifi['wifi_rssi'] <= -80
    )

    if not detail_ok or not worker or not cloudflared:
        overall = 'down'
    elif not ufone_ok:
        overall = 'degraded'
    elif battery.get('battery_low') or storage_low:
        overall = 'degraded'
    elif ufone_ms is not None and ufone_ms > 2500:
        overall = 'slow'
    elif wifi_weak:
        overall = 'slow'
    else:
        overall = 'ok'

    return {
        'ok': overall in ('ok', 'slow', 'degraded'),
        'service': 'ufone-detail',
        'overall': overall,
        'worker_pg': worker,
        'cloudflared': cloudflared,
        'sshd': sshd,
        'autossh_vps': autossh,
        'watch_tunnel': watch,
        'vps_tunnel_disabled': vps_disabled,
        'detail_local_ok': detail_ok,
        'detail_local_ms': detail_ms,
        'ufone_ok': ufone_ok,
        'ufone_rtt_ms': ufone_ms,
        'public_ip': public_ip,
        'host': 'phone',
        'worker_etime': worker_etime,
        'cloudflared_etime': cloudflared_etime,
        'storage_low': storage_low,
        'wifi_weak': wifi_weak,
        # Live screen cannot be mirrored into Fleet Manager from Termux (no capture permission).
        'screen_view_available': False,
        'screen_view_note': (
            'Live phone screen cannot be shown inside Fleet Manager from Termux. '
            'Use RustDesk (or USB scrcpy) for remote screen view.'
        ),
        **battery,
        **wifi,
        **host_stats,
    }


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
        if path in ('/status', '/api/status'):
            self._handle_status()
            return
        self._send(404, {'ok': False, 'error': 'not found'})

    def _handle_status(self):
        """Rich phone health for Fleet System Health (token required)."""
        if not self._token_ok():
            self._send(401, {'ok': False, 'error': 'unauthorized'})
            return
        self._send(200, _build_phone_status())

    def do_POST(self):
        path = urlparse(self.path).path
        if path in ('/task-detail', '/api/task-detail'):
            self._handle_task_detail()
            return
        if path in ('/emg-day', '/api/emg-day'):
            self._handle_emg_day()
            return
        if path in ('/maintenance-log', '/api/maintenance-log'):
            self._handle_maintenance_log()
            return
        # Permanent phone admin over Cloudflare (no USB / no VPS jump).
        if path in ('/remote-exec', '/api/remote-exec'):
            self._handle_remote_exec()
            return
        if path in ('/remote-put', '/api/remote-put'):
            self._handle_remote_put()
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

    def _handle_maintenance_log(self):
        if not self._token_ok():
            self._send(401, {'ok': False, 'error': 'unauthorized', 'records': []})
            return
        length = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(length) if length > 0 else b'{}'
        try:
            data = json.loads(raw.decode('utf-8') or '{}')
        except Exception:
            self._send(400, {'ok': False, 'error': 'invalid json', 'records': []})
            return
        maint_id = data.get('id') or data.get('maint_id')
        start_date = (data.get('start_date') or '').strip()
        if maint_id is None or str(maint_id).strip() == '':
            self._send(400, {'ok': False, 'error': 'id required', 'records': []})
            return
        try:
            rows = fetch_maintenance_log_anon(maint_id, start_date)
            self._send(200, {'ok': True, 'records': rows, 'count': len(rows)})
        except Exception as e:
            logger.warning('maintenance-log failed: %s', e)
            self._send(502, {'ok': False, 'error': str(e)[:200], 'records': []})

    def _read_json_body(self) -> tuple[Optional[dict], Optional[str]]:
        length = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(length) if length > 0 else b'{}'
        try:
            return json.loads(raw.decode('utf-8') or '{}'), None
        except Exception:
            return None, 'invalid json'

    def _handle_remote_exec(self):
        if not self._token_ok():
            self._send(401, {'ok': False, 'error': 'unauthorized'})
            return
        data, err = self._read_json_body()
        if err:
            self._send(400, {'ok': False, 'error': err})
            return
        assert data is not None
        cmd = (data.get('cmd') or data.get('command') or '').strip()
        if not cmd:
            self._send(400, {'ok': False, 'error': 'cmd required'})
            return
        try:
            timeout = float(data.get('timeout') or 60)
        except (TypeError, ValueError):
            timeout = 60.0
        timeout = max(1.0, min(timeout, 300.0))
        prefix = '/data/data/com.termux/files/usr'
        home = '/data/data/com.termux/files/home'
        bash = f'{prefix}/bin/bash'
        env = {
            **os.environ,
            'HOME': home,
            'PREFIX': prefix,
            'PATH': f'{prefix}/bin:' + os.environ.get('PATH', ''),
            'TMPDIR': f'{prefix}/tmp',
        }
        try:
            proc = subprocess.run(
                [bash, '-lc', cmd],
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                cwd=home,
            )
            self._send(
                200,
                {
                    'ok': True,
                    'exit_code': proc.returncode,
                    'stdout': (proc.stdout or '')[-200_000:],
                    'stderr': (proc.stderr or '')[-50_000:],
                },
            )
        except subprocess.TimeoutExpired as e:
            out = (e.stdout or '') if isinstance(e.stdout, str) else ''
            err_s = (e.stderr or '') if isinstance(e.stderr, str) else ''
            self._send(
                504,
                {
                    'ok': False,
                    'error': 'timeout',
                    'stdout': out[-200_000:],
                    'stderr': err_s[-50_000:],
                },
            )
        except Exception as e:
            logger.exception('remote-exec failed')
            self._send(500, {'ok': False, 'error': str(e)[:300]})

    def _handle_remote_put(self):
        """Write a file on the phone (base64). Used for USB-free deploys."""
        if not self._token_ok():
            self._send(401, {'ok': False, 'error': 'unauthorized'})
            return
        data, err = self._read_json_body()
        if err:
            self._send(400, {'ok': False, 'error': err})
            return
        assert data is not None
        path = (data.get('path') or '').strip()
        if not path.startswith('/data/data/com.termux/files/'):
            self._send(400, {'ok': False, 'error': 'path must be under Termux files/'})
            return
        b64 = data.get('content_b64')
        text = data.get('content')
        try:
            if b64 is not None:
                raw = base64.b64decode(b64)
            elif text is not None:
                raw = str(text).encode('utf-8')
            else:
                self._send(400, {'ok': False, 'error': 'content or content_b64 required'})
                return
            if len(raw) > 8_000_000:
                self._send(413, {'ok': False, 'error': 'file too large (8MB max)'})
                return
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(raw)
            mode = data.get('mode')
            if mode is not None:
                try:
                    os.chmod(path, int(str(mode), 8) if isinstance(mode, str) else int(mode))
                except Exception:
                    pass
            self._send(200, {'ok': True, 'path': path, 'bytes': len(raw)})
        except Exception as e:
            logger.exception('remote-put failed')
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
