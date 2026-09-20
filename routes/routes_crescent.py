"""
Personal (Crescent Tracker) Routes
===================================
Integration of the Crescent "TrackGF" mobile-app API into Fleet Manager:
dashboard, live map, vehicles, history playback, trip/alarm reports,
notifications and connection settings.

Sidebar item: "Personal" → /hub/personal (module hub, same as Software view).
"""
import json
from datetime import datetime, timedelta

from flask import render_template, redirect, url_for, flash, request, jsonify, session

from app import app, db
from models import CrescentApiLog, CrescentSettings, CrescentVehicleCache
from routes import _nav_back_ctx
from services import crescent_service as cs


def _personal_hub_back():
    return _nav_back_ctx(
        url_for('module_hub', hub_slug='personal'),
        default_label='Personal Tracking Hub',
    )


@app.before_request
def _crescent_ensure_tables():
    """LOCAL_FAST_BOOT skips startup create_all — make sure Personal tables exist."""
    if request.path.startswith('/personal') or request.path.startswith('/api/personal'):
        cs.ensure_tables()


# ── helpers ──────────────────────────────────────────────────────────────────

def _settings_or_none():
    return cs.get_settings()


def _configured():
    return cs.is_configured()


def _flash_error_once():
    s = _settings_or_none()
    if s and s.last_error:
        flash(f'Crescent Tracker: {s.last_error}', 'warning')


# ── pages ────────────────────────────────────────────────────────────────────

@app.route('/personal')
def personal_dashboard():
    vehicles = cs.cached_vehicles()
    stats = cs.status_counts(vehicles)
    s = _settings_or_none()
    return render_template(
        'personal/dashboard.html',
        vehicles=vehicles, stats=stats, settings=s,
        configured=_configured(),
        poll_seconds=(s.poll_seconds if s else 30),
        **_personal_hub_back(),
    )


@app.route('/personal/live')
def personal_live():
    vehicles = cs.cached_vehicles()
    s = _settings_or_none()
    return render_template(
        'personal/live.html',
        vehicles=vehicles, stats=cs.status_counts(vehicles), settings=s,
        configured=_configured(),
        poll_seconds=(s.poll_seconds if s else 30),
        **_personal_hub_back(),
    )


@app.route('/personal/vehicles')
def personal_vehicles():
    vehicles = cs.cached_vehicles()
    groups = sorted({v.group_name for v in vehicles if v.group_name})
    return render_template(
        'personal/vehicles.html',
        vehicles=vehicles, groups=groups, configured=_configured(),
        **_personal_hub_back(),
    )


@app.route('/personal/vehicle/<int:vid>')
def personal_vehicle_detail(vid):
    v = CrescentVehicleCache.query.get_or_404(vid)
    raw = None
    try:
        raw = json.loads(v.raw_json or 'null')
    except ValueError:
        raw = None
    return render_template(
        'personal/vehicle_detail.html',
        v=v, raw=raw, configured=_configured(), settings=_settings_or_none(),
        **_personal_hub_back(),
    )


@app.route('/personal/history')
def personal_history():
    vehicles = cs.cached_vehicles()
    return render_template(
        'personal/history.html',
        vehicles=vehicles, configured=_configured(),
        **_personal_hub_back(),
    )


@app.route('/personal/trips')
def personal_trips():
    vehicles = cs.cached_vehicles()
    return render_template(
        'personal/trips.html',
        vehicles=vehicles, configured=_configured(),
        **_personal_hub_back(),
    )


@app.route('/personal/alarms')
def personal_alarms():
    vehicles = cs.cached_vehicles()
    return render_template(
        'personal/alarms.html',
        vehicles=vehicles, configured=_configured(),
        **_personal_hub_back(),
    )


@app.route('/personal/notifications')
def personal_notifications():
    return render_template(
        'personal/notifications.html',
        configured=_configured(),
        **_personal_hub_back(),
    )


@app.route('/personal/settings')
def personal_settings():
    s = _settings_or_none()
    logs = []
    if s:
        logs = (CrescentApiLog.query.filter_by(settings_id=s.id)
                .order_by(CrescentApiLog.id.desc()).limit(50).all())
    return render_template(
        'personal/settings.html',
        settings=s, logs=logs, configured=_configured(),
        **_personal_hub_back(),
    )


# ── JSON APIs ────────────────────────────────────────────────────────────────

@app.route('/api/personal/positions')
def api_personal_positions():
    """Cached positions for live map/dashboard polling (full telemetry)."""
    vehicles = cs.cached_vehicles()
    s = _settings_or_none()
    return jsonify({
        'ok': True,
        'server_time': datetime.utcnow().isoformat(),
        'poll_seconds': (s.poll_seconds if s else 30),
        'stats': cs.status_counts(vehicles),
        'vehicles': [{
            'id': v.id, 'device_id': v.device_id, 'regno': v.regno,
            'lat': float(v.lat) if v.lat is not None else None,
            'lon': float(v.lon) if v.lon is not None else None,
            'speed': float(v.speed) if v.speed is not None else None,
            'status': v.status, 'ignition': v.ignition,
            'mileage': float(v.mileage) if v.mileage is not None else None,
            'address': v.address, 'driver': v.driver_name,
            'group': v.group_name, 'vehicle_type': v.vehicle_type,
            'dir': _raw_field(v, 'DirAngle'),
            'online': _raw_field(v, 'Online'),
            'fence': _raw_field(v, 'Fence'),
            'alarm': _raw_field(v, 'Alarm'),
            'device_status': _raw_field(v, 'DeviceStatus'),
            'gsm': _raw_field(v, 'GsmSignal'),
            'gps_sat': _raw_field(v, 'GpsSatelite'),
            'ext_bat': _raw_num(v, 'ExtBatV'),
            'int_bat': _raw_num(v, 'IntBatPercent'),
            'device_time': v.device_time.isoformat() if v.device_time else None,
            'updated_at': v.updated_at.isoformat() if v.updated_at else None,
        } for v in vehicles],
    })


def _raw_field(v, key):
    """Read a field from the cached raw vendor JSON (tolerant)."""
    try:
        raw = json.loads(v.raw_json or '{}')
        return raw.get(key)
    except (ValueError, AttributeError):
        return None


def _raw_num(v, key):
    val = _raw_field(v, key)
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


@app.route('/api/personal/refresh', methods=['POST'])
def api_personal_refresh():
    """Pull fresh data from Crescent into the local cache."""
    s = _settings_or_none()
    if not s:
        return jsonify({'ok': False, 'error': 'Crescent not configured — Personal → Settings mein credentials save karein.'}), 400
    res = cs.sync_vehicles(s)
    status = 200 if res.get('ok') else 502
    return jsonify(res), status


@app.route('/api/personal/vehicles')
def api_personal_vehicles():
    vehicles = cs.cached_vehicles()
    return jsonify({'ok': True, 'count': len(vehicles), 'vehicles': [
        {'id': v.id, 'device_id': v.device_id, 'regno': v.regno, 'group': v.group_name}
        for v in vehicles]})


@app.route('/api/personal/history', methods=['POST'])
def api_personal_history():
    """History playback points for one device between two datetimes."""
    s = _settings_or_none()
    if not _configured():
        return jsonify({'ok': False, 'error': 'Crescent credentials missing (Personal → Settings).'}), 400
    p = request.get_json(silent=True) or {}
    device_id = (p.get('device_id') or '').strip()
    if not device_id:
        return jsonify({'ok': False, 'error': 'Vehicle select karein.'}), 400
    v = CrescentVehicleCache.query.filter_by(device_id=device_id).first()
    if not v:
        return jsonify({'ok': False, 'error': 'Vehicle cache mein nahi mili — pehle Refresh karein.'}), 404
    date_from = (p.get('date_from') or '').strip()
    date_to = (p.get('date_to') or '').strip()
    if not (date_from and date_to):
        return jsonify({'ok': False, 'error': 'From/To dates required.'}), 400

    res = cs.history_points(s, v, date_from, date_to,
                            p.get('time_from') or '00:00', p.get('time_to') or '23:59')
    if not res['ok']:
        return jsonify({'ok': False, 'error': res['error'], 'status': res['status']}), 502

    points = cs._extract_points(res['data'])
    points.sort(key=lambda x: (x['_ts'] is not None, x['_ts'] or datetime.utcnow()))
    stats = {'points': len(points)}
    if points:
        speeds = [pt['speed'] for pt in points]
        stats['max_speed'] = max(speeds)
        stats['avg_speed'] = round(sum(speeds) / len(speeds), 1)
        dist = 0.0
        prev = None
        for pt in points:
            if prev is not None and pt['lat'] is not None and prev['lat'] is not None:
                from math import radians, sin, cos, asin, sqrt
                r = 6371.0
                la1, lo1, la2, lo2 = map(radians, (prev['lat'], prev['lon'], pt['lat'], pt['lon']))
                h = sin((la2 - la1) / 2) ** 2 + cos(la1) * cos(la2) * sin((lo2 - lo1) / 2) ** 2
                d = 2 * r * asin(sqrt(h))
                if 0 <= d < 100:
                    dist += d
            prev = pt
        stats['distance'] = round(dist, 1)
        moving_secs = 0
        for i in range(1, len(points)):
            a, b = points[i - 1], points[i]
            if a['_ts'] and b['_ts'] and (a.get('speed') or 0) > 2:
                moving_secs += (b['_ts'] - a['_ts']).total_seconds()
        stats['moving_time_min'] = round(moving_secs / 60)

    # stops: consecutive parked/idle points >= 5 minutes at ~same spot
    stops = []
    cur = None
    for pt in points:
        st = (pt.get('status') or '').lower()
        stopped = ('park' in st or 'idle' in st) and (pt.get('speed') or 0) < 2
        if stopped:
            if cur is None:
                cur = {'start': pt, 'end': pt}
            else:
                cur['end'] = pt
        else:
            if cur is not None:
                stops.append(cur)
                cur = None
    if cur is not None:
        stops.append(cur)
    stops_out = []
    for st in stops:
        a, b = st['start'], st['end']
        if a['_ts'] and b['_ts'] and (b['_ts'] - a['_ts']).total_seconds() >= 300:
            stops_out.append({
                'start': a['_ts'].isoformat() if a['_ts'] else a['datetime_raw'],
                'end': b['_ts'].isoformat() if b['_ts'] else b['datetime_raw'],
                'duration_min': round((b['_ts'] - a['_ts']).total_seconds() / 60),
                'lat': a['lat'], 'lon': a['lon'],
                'address': a.get('address'),
                'status': (a.get('status') or '').title(),
            })

    return jsonify({'ok': True, 'stats': stats, 'stops': stops_out, 'points': [
        {
            'lat': pt['lat'], 'lon': pt['lon'], 'speed': pt['speed'],
            'time': pt['_ts'].isoformat() if pt['_ts'] else pt['datetime_raw'],
            'ignition': pt['ignition'], 'status': pt['status'], 'alarm': pt['alarm'],
            'address': pt['address'], 'dir': pt.get('direction'),
        } for pt in points if pt['lat'] is not None and pt['lon'] is not None]})


@app.route('/api/personal/trips', methods=['POST'])
def api_personal_trips():
    """Trips derived from the vendor history (movement bursts between stops)."""
    s = _settings_or_none()
    if not _configured():
        return jsonify({'ok': False, 'error': 'Crescent credentials missing (Personal → Settings).'}), 400
    p = request.get_json(silent=True) or {}
    device_id = (p.get('device_id') or '').strip()
    v = CrescentVehicleCache.query.filter_by(device_id=device_id).first() if device_id else None
    if not v:
        return jsonify({'ok': False, 'error': 'Vehicle select karein (trips per-vehicle hain).'}), 400
    date_from, date_to = (p.get('date_from') or '').strip(), (p.get('date_to') or '').strip()
    if not (date_from and date_to):
        return jsonify({'ok': False, 'error': 'From/To dates required.'}), 400

    res = cs.history_points(s, v, date_from, date_to)
    if not res['ok']:
        return jsonify({'ok': False, 'error': res['error'], 'status': res['status']}), 502
    points = cs._extract_points(res['data'])
    trips = cs.derive_trips(points)
    total_km = round(sum(t.get('Distance (km)') or 0 for t in trips), 1)
    return jsonify({'ok': True, 'count': len(trips), 'total_km': total_km, 'rows': trips})


@app.route('/api/personal/alarms', methods=['POST'])
def api_personal_alarms():
    """Alarm events = history points carrying a non-empty Alarm field."""
    s = _settings_or_none()
    if not _configured():
        return jsonify({'ok': False, 'error': 'Crescent credentials missing (Personal → Settings).'}), 400
    p = request.get_json(silent=True) or {}
    device_id = (p.get('device_id') or '').strip()
    v = CrescentVehicleCache.query.filter_by(device_id=device_id).first() if device_id else None
    if not v:
        return jsonify({'ok': False, 'error': 'Vehicle select karein (alarms per-vehicle hain).'}), 400
    date_from, date_to = (p.get('date_from') or '').strip(), (p.get('date_to') or '').strip()
    if not (date_from and date_to):
        return jsonify({'ok': False, 'error': 'From/To dates required.'}), 400

    res = cs.history_points(s, v, date_from, date_to)
    if not res['ok']:
        return jsonify({'ok': False, 'error': res['error'], 'status': res['status']}), 502
    points = cs._extract_points(res['data'])
    rows = [{
        'Time': pt['_ts'].strftime('%d-%b %H:%M:%S') if pt['_ts'] else pt['datetime_raw'],
        'Vehicle': v.regno,
        'Alarm': pt['alarm'],
        'Status': pt['status'],
        'Speed (km/h)': pt['speed'],
        'Location': pt['address'],
        'Lat': pt['lat'], 'Lon': pt['lon'],
    } for pt in points if (pt.get('alarm') or '').strip()]
    return jsonify({'ok': True, 'count': len(rows), 'rows': rows})


@app.route('/api/personal/notifications')
def api_personal_notifications():
    s = _settings_or_none()
    if not _configured():
        return jsonify({'ok': False, 'error': 'Crescent credentials missing (Personal → Settings).'}), 400
    res = cs.notifications(s)
    if not res['ok']:
        return jsonify({'ok': False, 'error': res['error'], 'status': res['status']}), 502
    data = res['data']
    rows = data.get('rows') if isinstance(data, dict) else data
    rows = rows or []
    return jsonify({'ok': True, 'count': len(rows), 'rows': rows})


@app.route('/api/personal/test-connection', methods=['POST'])
def api_personal_test_connection():
    s = _settings_or_none()
    if not s:
        return jsonify({'ok': False, 'error': 'Pehle credentials save karein.'}), 400
    res = cs.test_connection(s)
    return jsonify(res), (200 if res.get('ok') else 502)


@app.route('/api/personal/settings/save', methods=['POST'])
def api_personal_settings_save():
    p = request.get_json(silent=True) or {}
    api_base = (p.get('api_base') or '').strip() or None
    if api_base and not api_base.lower().startswith('http'):
        return jsonify({'ok': False, 'error': 'API base URL http:// ya https:// se shuru hona chahiye.'}), 400
    alt = (p.get('alt_api_base') or '').strip()
    if alt and not alt.lower().startswith('http'):
        return jsonify({'ok': False, 'error': 'Alt API base URL http:// ya https:// se shuru hona chahiye.'}), 400
    try:
        poll = int(p.get('poll_seconds') or 30)
    except (TypeError, ValueError):
        poll = 30
    s = cs.save_settings(
        api_base=api_base or cs.DEFAULT_API_BASE,
        username=(p.get('username') or '').strip(),
        password=(p.get('password') or '').strip() or None,
        alt_api_base=alt,
        poll_seconds=max(10, min(poll, 600)),
        fcm_token=(p.get('fcm_token') if 'fcm_token' in p else None),
        commands_enabled=(bool(p.get('commands_enabled')) if 'commands_enabled' in p else None),
    )
    return jsonify({'ok': True, 'message': 'Settings saved.', 'id': s.id})


@app.route('/api/personal/vehicle/<int:vid>/command', methods=['POST'])
def api_personal_vehicle_command(vid):
    """Engine Kill / Release (immobilizer) — dangerous, fully audited.

    Safety gates: commands must be enabled in Settings, vehicle speed must be
    under 5 km/h, and the request must echo the reg no as confirmation.
    """
    s = _settings_or_none()
    if not _configured():
        return jsonify({'ok': False, 'error': 'Crescent credentials missing (Personal → Settings).'}), 400
    v = CrescentVehicleCache.query.get_or_404(vid)
    p = request.get_json(silent=True) or {}
    action = (p.get('action') or '').strip()
    confirm = (p.get('confirm') or '').strip()

    if action not in cs.IMMOBILIZER_ACTIONS:
        return jsonify({'ok': False, 'error': 'Action engine_off ya engine_on hona chahiye.'}), 400
    if confirm.upper() != (v.regno or '').upper():
        return jsonify({'ok': False, 'error': f'Confirmation ghalat — reg no exactly type karein ({v.regno}).'}), 400
    if (v.speed or 0) >= 5:
        return jsonify({'ok': False, 'error': f'Vehicle moving hai ({v.speed} km/h) — command sirf speed < 5 par bhej sakte hain.'}), 400

    res = cs.send_command(s, v, action)
    status = 200 if res.get('ok') else 502
    return jsonify(res), status


@app.route('/api/personal/log/clear', methods=['POST'])
def api_personal_log_clear():
    s = _settings_or_none()
    if s:
        CrescentApiLog.query.filter_by(settings_id=s.id).delete()
        db.session.commit()
    return jsonify({'ok': True})
