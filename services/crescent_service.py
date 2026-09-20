"""
Crescent Tracker (Personal) integration service.

REAL protocol, captured live from the Crescent Android app (com.cresent.app v3.0.6)
via an instrumented emulator (hosts/DNS + iptables REDIRECT + TLS-terminating proxy):

    Base      https://teletixapp.crescenttrack.com:8888/api/   (HTTPS on 8888)
    Login     GET user/verify?uname=<u>&pwd=<p>
              -> JSON string of hex-encoded UTF-16BE, e.g. "30003100..." -> "01,1,10189,NA"
              That decoded string IS the session token (not a JWT).
    Auth      Authorization: Bearer <token>
    Fleet     GET live/status?a=1&t=<token>            (all vehicles, full status)
    Vehicle   GET live/status?c=<ClusterId>&p=<ProcId>&id=<Device#>
    History   GET tripreplay/getall?cmpId=<cmp_id>&type=v&id=<vehicleId>
                       &dateTime1=<YYYY-MM-DD HH:MM:SS>&dateTime2=<YYYY-MM-DD HH:MM:SS>
              -> array of points: SrNo, GpsDateTime, ACC, Speed, Status, Alarm,
                 Location, Dir, Latitude, Longitude
    Push      POST https://crescent-api.progatix.com/token/saveFcmToken
              {fcmToken, userName, vendorName: "teletix"}
    Notifs    GET  https://crescent-api.progatix.com/notification/notificationList
              header: fcmToken: <registered fcmToken>

The vendor's legacy host trackgf.crescenttrack.com:8888 serves a different
(plain-HTTP, older) API whose login endpoint is broken; the live app uses the
teletixapp host above.
"""
import json
import threading
import time
from datetime import datetime, timedelta

import requests
import urllib3

from app import db
from models import CrescentApiLog, CrescentSettings, CrescentVehicleCache

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)  # vendor TLS cert is loose

try:  # flat vs package import both supported
    from services.portalxs_service import decrypt_password, encrypt_password
except Exception:  # pragma: no cover
    from portalxs_service import decrypt_password, encrypt_password  # type: ignore

DEFAULT_API_BASE = 'https://teletixapp.crescenttrack.com:8888/api/'
ALT_API_BASE = 'https://crescent-api.progatix.com/'  # push notifications backend
VENDOR_NAME = 'teletix'
REQUEST_TIMEOUT = 30

_token_lock = threading.Lock()

_tables_checked = False

_EXTRA_COLUMNS = {
    'crescent_settings': [
        ('fcm_token', 'VARCHAR(300)'),
        ('commands_enabled', "BOOLEAN DEFAULT 0"),
    ],
    'crescent_vehicle_cache': [
        ('cmp_id', 'VARCHAR(20)'),
        ('cluster_id', 'VARCHAR(20)'),
        ('proc_id', 'VARCHAR(20)'),
        ('vendor_vehicle_id', 'VARCHAR(50)'),
    ],
}


def ensure_tables():
    """Create the crescent_* tables/columns if missing.

    LOCAL_FAST_BOOT (run-local.bat) skips the global db.create_all() at startup,
    so the Personal section repairs just its own schema lazily on first use.
    """
    global _tables_checked
    if _tables_checked:
        return
    try:
        db.metadata.create_all(db.engine, tables=[
            CrescentSettings.__table__, CrescentVehicleCache.__table__, CrescentApiLog.__table__,
        ])
        is_pg = 'postgres' in str(db.engine.url)
        for table, cols in _EXTRA_COLUMNS.items():
            for col, ddl in cols:
                try:
                    if is_pg:
                        db.session.execute(db.text(
                            f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {ddl}'))
                    else:
                        db.session.execute(db.text(
                            f'ALTER TABLE {table} ADD COLUMN {col} {ddl}'))
                except Exception:
                    pass  # column already exists
        db.session.commit()
        _tables_checked = True
    except Exception:
        pass  # leave flag False so the next request retries


# ── Settings ─────────────────────────────────────────────────────────────────

def get_settings():
    """Active CrescentSettings row (first active) or None."""
    ensure_tables()
    return CrescentSettings.query.filter_by(is_active=True).order_by(CrescentSettings.id).first()


def save_settings(api_base, username, password=None, alt_api_base=None, poll_seconds=30, fcm_token=None,
                  commands_enabled=None):
    """Create/update the single active settings row. Empty password keeps the old one."""
    s = get_settings()
    if s is None:
        s = CrescentSettings(api_base=api_base or DEFAULT_API_BASE, username=username or '')
        db.session.add(s)
    else:
        s.api_base = api_base or s.api_base or DEFAULT_API_BASE
        s.username = username or s.username
    if alt_api_base is not None:
        s.alt_api_base = alt_api_base or None
    if fcm_token is not None:  # empty string clears, None keeps
        s.fcm_token = fcm_token.strip() or None
    if commands_enabled is not None:
        s.commands_enabled = bool(commands_enabled)
    s.poll_seconds = int(poll_seconds or 30)
    if password:
        s.password_enc = encrypt_password(password)
        s.token_enc = None  # invalidate cached token on credential change
        s.token_expires_at = None
    db.session.commit()
    return s


def is_configured():
    s = get_settings()
    return bool(s and s.username and s.password_enc)


# ── Low-level HTTP with logging ──────────────────────────────────────────────

def _log_call(settings_id, endpoint, method, status_code, ok, duration_ms, error, req_snip, resp_snip):
    try:
        db.session.add(CrescentApiLog(
            settings_id=settings_id, endpoint=endpoint[:200], method=method,
            status_code=status_code, ok=bool(ok), duration_ms=int(duration_ms),
            error=(error or '')[:500],
            request_snip=(req_snip or '')[:2000], response_snip=(resp_snip or '')[:2000],
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()


def _url(base, path):
    return base.rstrip('/') + '/' + path.lstrip('/')


# ── Token management ─────────────────────────────────────────────────────────

def _decode_token(raw):
    """user/verify returns a JSON string of hex-encoded UTF-16LE text, e.g.
    "30003100..." -> bytes 30 00 31 00 -> utf-16-le -> "01...\"."""
    if isinstance(raw, str):
        try:
            return bytes.fromhex(raw).decode('utf-16-le')
        except ValueError:
            return raw
    return str(raw)


def login(settings):
    """GET user/verify?uname=&pwd= → hex-encoded token string (used as-is everywhere).

    The body is a JSON string of hex bytes (UTF-16LE text like "01,2,10303,NA").
    The app sends the RAW HEX STRING in both the t= query param and the
    Authorization: Bearer header — the decoded form is only for our insight.
    """
    url = _url(settings.api_base or DEFAULT_API_BASE, 'user/verify')
    t0 = time.time()
    try:
        resp = requests.get(
            url, params={'uname': settings.username or '',
                         'pwd': decrypt_password(settings.password_enc or '')},
            headers={'Accept': 'application/json', 'Content-Type': 'application/json'},
            timeout=REQUEST_TIMEOUT, verify=False,  # vendor serves a cert chains may reject
        )
    except requests.RequestException as e:
        settings.last_error = f'Login network error: {e}'
        db.session.commit()
        _log_call(settings.id, '/api/user/verify', 'GET', 0, False, (time.time() - t0) * 1000,
                  str(e), 'uname=***', '')
        return False, settings.last_error

    body_snip = (resp.text or '')[:400]
    ok = resp.status_code == 200
    token = ''
    if ok:
        try:
            j = resp.json()
            token = j if isinstance(j, str) and all(c in '0123456789abcdefABCDEF' for c in j) else ''
        except (ValueError, json.JSONDecodeError):
            token = ''
    if ok and token:
        with _token_lock:
            settings.token_enc = encrypt_password(token)
            # vendor tokens are session-scoped; refresh daily to be safe
            settings.token_expires_at = datetime.utcnow() + timedelta(hours=12)
            settings.last_login_at = datetime.utcnow()
            settings.last_error = None
        db.session.commit()
        _log_call(settings.id, '/api/user/verify', 'GET', 200, True, (time.time() - t0) * 1000,
                  None, 'uname=***', f'token={token[:60]}')
        return True, None

    err = f'HTTP {resp.status_code}'
    if resp.text:
        err += f': {resp.text[:150]}'
    settings.last_error = f'Login failed: {err}'
    db.session.commit()
    _log_call(settings.id, '/api/user/verify', 'GET', resp.status_code, False,
              (time.time() - t0) * 1000, err, 'uname=***', body_snip)
    return False, settings.last_error


def get_token(settings, force=False):
    """Return the cached session token, re-logging-in when missing/expired."""
    if not force and settings.token_enc and settings.token_expires_at \
            and datetime.utcnow() < settings.token_expires_at:
        return decrypt_password(settings.token_enc)
    ok, err = login(settings)
    return decrypt_password(settings.token_enc) if ok else None


# ── Endpoint wrappers ────────────────────────────────────────────────────────

def _api_get(settings, path, params=None, use_alt_base=False, extra_headers=None):
    base = (settings.alt_api_base or ALT_API_BASE) if use_alt_base else (settings.api_base or DEFAULT_API_BASE)
    url = _url(base, path)
    token = get_token(settings)
    if not token and not extra_headers:
        return {'ok': False, 'status': 0, 'data': None, 'error': settings.last_error or 'Not logged in'}
    headers = {'Accept': 'application/json'}
    if extra_headers:
        headers.update(extra_headers)
    if token:
        headers['Authorization'] = f'Bearer {token}'
    t0 = time.time()
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT, verify=False)
    except requests.RequestException as e:
        _log_call(settings.id, path, 'GET', 0, False, (time.time() - t0) * 1000, str(e), '', '')
        return {'ok': False, 'status': 0, 'data': None, 'error': f'Network error: {e}'}
    dur = (time.time() - t0) * 1000
    try:
        data = resp.json()
    except ValueError:
        data = None
    _log_call(settings.id, path, 'GET', resp.status_code, resp.status_code == 200, dur, None,
              str(params or '')[:800], (resp.text or '')[:800])
    if resp.status_code == 200:
        return {'ok': True, 'status': 200, 'data': data, 'error': None}
    if resp.status_code == 401 and token:
        token = get_token(settings, force=True)
        if token:
            headers['Authorization'] = f'Bearer {token}'
            try:
                resp = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT, verify=False)
                data = resp.json()
            except (requests.RequestException, ValueError) as e:
                return {'ok': False, 'status': 0, 'data': None, 'error': f'Retry error: {e}'}
            if resp.status_code == 200:
                return {'ok': True, 'status': 200, 'data': data, 'error': None}
    err = None
    if isinstance(data, dict):
        err = data.get('Message') or data.get('message') or data.get('error')
    err = str(err) if err is not None else None
    return {'ok': False, 'status': resp.status_code, 'data': data,
            'error': err or f'HTTP {resp.status_code}'}


def live_fleet(settings):
    """All vehicles with full live status."""
    token = get_token(settings)
    if not token:
        return {'ok': False, 'status': 0, 'data': None, 'error': settings.last_error or 'Not logged in'}
    return _api_get(settings, 'live/status', params={'a': '1', 't': token})


def user_change_check(settings):
    return _api_get(settings, 'user/isanychange', params={'uname': settings.username})


def history_points(settings, vehicle, date_from, date_to, time_from='00:00:00', time_to='23:59:59'):
    """History playback points for one cached vehicle row between datetimes."""
    params = {
        'cmpId': vehicle.cmp_id or '1',
        'type': 'v',
        'id': vehicle.vendor_vehicle_id or '',
        'dateTime1': f'{date_from} {(time_from or "00:00:00")}:00'[:19],
        'dateTime2': f'{date_to} {(time_to or "23:59:59")}:00'[:19],
    }
    return _api_get(settings, 'tripreplay/getall', params=params)


def notifications(settings):
    """Vendor requires a REAL registered FCM device token (server validates against
    Firebase — synthetic tokens are rejected). Use the one captured/entered from the
    user's own Crescent app; without it, point the user to the Alarms page."""
    if not settings.fcm_token:
        return {'ok': False, 'status': 0, 'data': None,
                'error': 'FCM token set nahi hai (Settings mein paste karein). Wahi alert data Alarms page par milta hai.'}
    res = _api_get(settings, 'notification/notificationList', use_alt_base=True,
                   extra_headers={'fcmToken': settings.fcm_token})
    if not res['ok'] and res['status'] == 401:
        res['error'] = 'FCM token expire/galat hai — naya token Settings mein paste karein. (Alarms page par wahi alerts history se milte hain.)'
    return res


# ── Engine immobilizer (Engine Kill / Release) ───────────────────────────────
# Vendor wire format is undocumented; the app binary exposes Command/send
# (trackgf cluster) and CmdCtrl/ImoblizerOn|Off action names. The request below
# follows the same GET + query-param style as every other endpoint in this API
# family. commands_enabled gates real sends; while disabled the exact request
# is written to the API Log as DRY-RUN so the format can be verified safely.

IMMOBILIZER_ACTIONS = {
    'engine_off': ('ImoblizerOn', 'ENGINE OFF (Kill)'),
    'engine_on': ('ImoblizerOff', 'ENGINE ON (Release)'),
}

LEGACY_COMMAND_BASE = 'http://trackgf.crescenttrack.com:8888/api/'  # Command/send confirmed here


def send_command(settings, vehicle, action, dry_run_forced=False):
    """Send an immobilizer command for one cached vehicle.

    Returns dict(ok, dry_run, request_url, vendor_status, vendor_body, message).
    """
    if action not in IMMOBILIZER_ACTIONS:
        return {'ok': False, 'error': f'Unknown action: {action}'}
    cmd_action, label = IMMOBILIZER_ACTIONS[action]
    token = get_token(settings)
    if not token:
        return {'ok': False, 'error': settings.last_error or 'Not logged in'}

    params = {
        'uname': settings.username,
        'vid': vehicle.vendor_vehicle_id or '',
        'id': vehicle.device_id,
        'cmd': cmd_action,
    }
    url = _url(settings.api_base or DEFAULT_API_BASE, 'Command/send')

    dry = dry_run_forced or not settings.commands_enabled
    if dry:
        _log_call(settings.id, f'Command/send [DRY-RUN {label}]', 'GET', 0, False, 0,
                  'commands disabled — nothing sent', str(params), '')
        return {
            'ok': True, 'dry_run': True,
            'request_url': url + '?' + '&'.join(f'{k}={v}' for k, v in params.items()),
            'message': f'DRY-RUN — commands disabled hain. Yeh request bheji nahi gayi. '
                       f'Settings se commands enable karne ke baad test karein. ({label})',
        }

    t0 = time.time()
    qs = '&'.join(f'{k}={v}' for k, v in params.items())
    # primary base, with automatic legacy-cluster fallback (Command/send 404s on teletixapp)
    attempts = [(url + '?' + qs, False)]
    if not url.startswith('http://trackgf'):
        attempts.append((_url(LEGACY_COMMAND_BASE, 'Command/send') + '?' + qs, True))

    last = {'ok': False, 'error': 'no attempt'}
    for attempt_url, is_legacy in attempts:
        try:
            resp = requests.get(attempt_url,
                                headers={'Authorization': f'Bearer {token}', 'Accept': 'application/json'},
                                timeout=REQUEST_TIMEOUT, verify=False)
        except requests.RequestException as e:
            _log_call(settings.id, f'Command/send{" [legacy]" if is_legacy else ""}', 'GET', 0, False,
                      (time.time() - t0) * 1000, str(e), str(params), '')
            last = {'ok': False, 'error': f'Network error: {e}'}
            continue

        dur = (time.time() - t0) * 1000
        body = (resp.text or '')[:400]
        _log_call(settings.id, f'Command/send [{label}]{" [legacy]" if is_legacy else ""}', 'GET',
                  resp.status_code, resp.status_code == 200, dur, None, str(params), body)

        if resp.status_code == 404 and not is_legacy:
            last = {'ok': False, 'error': 'route missing on primary — trying legacy cluster'}
            continue  # fall through to legacy base

        ok = resp.status_code == 200 and 'error' not in body.lower()
        last = {'ok': ok, 'dry_run': False, 'vendor_status': resp.status_code,
                'vendor_body': body, 'message': body or f'HTTP {resp.status_code}',
                'request_url': attempt_url}
        break
    return last


# ── Normalization (live/status field names) ──────────────────────────────────

def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_dt(raw):
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw
    s = str(raw).strip()
    for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%d/%m/%Y %H:%M:%S',
                '%d-%m-%Y %H:%M:%S', '%m/%d/%Y %H:%M:%S', '%Y-%m-%dT%H:%M:%SZ'):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace('Z', '+00:00')).replace(tzinfo=None)
    except ValueError:
        return None


def normalize_vehicle(raw):
    """Map a live/status record into our standard vehicle dict."""
    if not isinstance(raw, dict):
        return None
    low = {str(k).lower(): v for k, v in raw.items()}

    def pick(*keys, default=None):
        for k in keys:
            if k in low and low[k] not in (None, ''):
                return low[k]
        return default

    point = str(pick('point', default='') or '')
    lat = lon = None
    if ',' in point:
        a, _, b = point.partition(',')
        lat, lon = _to_float(a.strip()), _to_float(b.strip())

    device_id = str(pick('device#', 'deviceid', 'vehicleid', default='') or '')
    out = {
        'device_id': device_id,
        'regno': str(pick('vrn', 'regno', default=device_id or '—')),
        'lat': lat, 'lon': lon,
        'speed': _to_float(pick('speed', default=0)) or 0.0,
        'status_raw': str(pick('status', default='') or ''),
        'datetime_raw': pick('gpsdatetime', 'recdatetime'),
        'ignition': str(pick('acc', default='') or ''),
        'mileage': _to_float(pick('mileage', default=None)),
        'address': pick('location'),
        'driver': pick('driver'),
        'group': pick('groupname'),
        'vehicle_type': pick('assettype'),
        'cmp_id': str(pick('cmp_id', default='') or ''),
        'cluster_id': str(pick('clusterid', default='') or ''),
        'proc_id': str(pick('procid', default='') or ''),
        'vendor_vehicle_id': str(pick('vehicleid', default='') or ''),
        'online': pick('online'),
        'device_status': pick('devicestatus'),
        'gsm_signal': pick('gsmsignal'),
        'gps_satellite': pick('gpssatelite', 'gpssatellite'),
        'ext_battery': _to_float(pick('extbatv')),
        'int_battery': _to_float(pick('intbatpercent')),
        'fence': pick('fence'),
        'alarm': pick('alarm'),
        'dir_angle': pick('dirangle'),
        '_raw': raw,
    }
    out['status'] = derive_status(out)
    return out


def derive_status(v):
    """Moving / Idle / Parked / Offline from vendor status + freshness."""
    ts = _parse_dt(v.get('datetime_raw'))
    # vendor timestamps are local (PKT); compare against local now, not utc
    if ts and (datetime.now() - ts).total_seconds() > 1800:
        return 'Offline'
    s_raw = (v.get('status_raw') or '').strip()
    if s_raw:
        return s_raw[:20]
    if (v.get('speed') or 0) > 3:
        return 'Moving'
    ign = (v.get('ignition') or '').lower()
    if ign in ('on', 'true', '1'):
        return 'Idle'
    return 'Parked'


def _extract_points(obj):
    """Flatten a tripreplay/getall response into standardized point dicts."""
    out = []
    rows = obj if isinstance(obj, list) else []
    for r in rows:
        if not isinstance(r, dict):
            continue
        out.append({
            'lat': _to_float(r.get('Latitude')),
            'lon': _to_float(r.get('Longitude')),
            'speed': _to_float(r.get('Speed')) or 0.0,
            'datetime_raw': r.get('GpsDateTime'),
            'ignition': r.get('ACC'),
            'status': r.get('Status'),
            'alarm': r.get('Alarm'),
            'address': r.get('Location'),
            'direction': r.get('Dir'),
            '_ts': _parse_dt(r.get('GpsDateTime')),
        })
    return out


# ── Cache sync ───────────────────────────────────────────────────────────────

def sync_vehicles(settings=None):
    """Fetch live/status and refresh crescent_vehicle_cache. Returns summary."""
    s = settings or get_settings()
    if not s:
        return {'ok': False, 'error': 'Crescent not configured. Add credentials in Personal → Settings.'}
    if not s.username or not s.password_enc:
        return {'ok': False, 'error': 'Username/password missing in Personal → Settings.'}

    res = live_fleet(s)
    if not res['ok']:
        return {'ok': False, 'error': res['error'], 'status': res['status']}

    data = res['data']
    rows = data if isinstance(data, list) else []
    norm = [n for n in (normalize_vehicle(r) for r in rows) if n and n.get('device_id')]
    if not norm:
        return {'ok': False,
                'error': 'Response 200 lekin vehicle fields samajh nahi aaye — Personal → Settings → API Log dekhein.',
                'raw_snip': json.dumps(data)[:800]}

    now = datetime.utcnow()
    existing = {cv.device_id: cv for cv in CrescentVehicleCache.query.filter_by(settings_id=s.id)}
    for n in norm:
        cv = existing.get(n['device_id'])
        if cv is None:
            cv = CrescentVehicleCache(settings_id=s.id, device_id=n['device_id'])
            db.session.add(cv)
        cv.regno = n['regno']
        cv.group_name = n.get('group')
        cv.vehicle_type = n.get('vehicle_type')
        cv.driver_name = n.get('driver')
        cv.lat = n.get('lat')
        cv.lon = n.get('lon')
        cv.speed = n.get('speed')
        cv.status = n.get('status')
        cv.ignition = n.get('ignition')
        cv.mileage = n.get('mileage')
        cv.address = n.get('address')
        cv.device_time = _parse_dt(n.get('datetime_raw'))
        cv.cmp_id = n.get('cmp_id')
        cv.cluster_id = n.get('cluster_id')
        cv.proc_id = n.get('proc_id')
        cv.vendor_vehicle_id = n.get('vendor_vehicle_id')
        cv.raw_json = json.dumps(n['_raw'], default=str)[:4000]
        cv.updated_at = now
    s.last_sync_at = now
    s.last_error = None
    db.session.commit()
    return {'ok': True, 'count': len(norm)}


def cached_vehicles(settings=None):
    s = settings or get_settings()
    if not s:
        return []
    return (CrescentVehicleCache.query.filter_by(settings_id=s.id)
            .order_by(CrescentVehicleCache.regno).all())


def status_counts(vehicles):
    counts = {'total': len(vehicles), 'Moving': 0, 'Idle': 0, 'Parked': 0, 'Offline': 0}
    for v in vehicles:
        counts[v.status if v.status in counts else 'Offline'] += 1
    return counts


# ── Trips derivation (from history points) ───────────────────────────────────

def derive_trips(points, min_stop_minutes=5):
    """Segment history points into trips (movement bursts) with haversine distance."""
    import math

    def hav(a_lat, a_lon, b_lat, b_lon):
        r = 6371.0
        p1, p2 = math.radians(a_lat), math.radians(b_lat)
        dp = math.radians(b_lat - a_lat)
        dl = math.radians(b_lon - a_lon)
        a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return 2 * r * math.asin(math.sqrt(a))

    trips = []
    cur = None
    last_parked = None
    for pt in points:
        st = (pt.get('status') or '').lower()
        if cur is None:
            if 'park' in st or 'off' in st:
                last_parked = pt
                continue
            cur = {'points': [pt], 'start': pt, 'end': pt}
            continue
        if 'park' in st or 'off' in st:
            cur['points'].append(pt)
            cur['end'] = pt
            if last_parked is None:
                last_parked = pt
            trips.append(cur)
            cur = None
            continue
        cur['points'].append(pt)
        cur['end'] = pt
    if cur:
        trips.append(cur)

    rows = []
    for t in trips:
        pts = t['points']
        dist = 0.0
        max_speed = 0.0
        prev = None
        for p in pts:
            if p['lat'] is not None and p['lon'] is not None and prev and \
                    prev['lat'] is not None and prev['lon'] is not None:
                dist += hav(prev['lat'], prev['lon'], p['lat'], p['lon'])
            max_speed = max(max_speed, p.get('speed') or 0)
            prev = p
        start, end = t['start'], t['end']
        dur_min = None
        if start['_ts'] and end['_ts']:
            dur_min = round((end['_ts'] - start['_ts']).total_seconds() / 60, 1)
        rows.append({
            'Start Time': start['_ts'].strftime('%d-%b %H:%M') if start['_ts'] else start['datetime_raw'],
            'Start Location': start.get('address') or '',
            'End Time': end['_ts'].strftime('%d-%b %H:%M') if end['_ts'] else end['datetime_raw'],
            'End Location': end.get('address') or '',
            'Duration (min)': dur_min if dur_min is not None else '',
            'Distance (km)': round(dist, 1),
            'Max Speed (km/h)': max_speed,
            'Points': len(pts),
        })
    return rows


# ── Connection test (Settings page) ──────────────────────────────────────────

def test_connection(settings=None):
    """Try login + each known endpoint; return structured per-endpoint results."""
    s = settings or get_settings()
    if not s:
        return {'ok': False, 'error': 'Pehle credentials save karein.'}
    if not s.username or not s.password_enc:
        return {'ok': False, 'error': 'Username/password required.'}

    out = {'ok': False, 'steps': []}
    ok, err = login(s)
    out['steps'].append({'step': 'Login (user/verify)', 'ok': ok, 'detail': err or 'token received'})
    if not ok:
        out['error'] = err
        return out

    checks = [
        ('live/status (fleet)', lambda: live_fleet(s)),
        ('user/isanychange', lambda: user_change_check(s)),
        ('notification/notificationList', lambda: notifications(s)),
    ]
    ok_count = 1
    for name, fn in checks:
        r = fn()
        detail = f"HTTP {r['status']}" if r['ok'] else (r['error'] or '')[:160]
        n = ''
        if r['ok'] and isinstance(r['data'], list):
            n = f' ({len(r["data"])} rows)'
        out['steps'].append({'step': name + n, 'ok': r['ok'], 'detail': detail})
        ok_count += 1 if r['ok'] else 0
    out['ok'] = ok_count >= 2
    return out
