"""
System Health, Tracker Automation, and Driver Document Update Portal routes.

Extracted from routes.py to reduce file size.
These routes handle:
  - System health monitoring (/admin/system-health, /health, /network-probe)
  - Tracker automation (/administration/tracker-automation/*)
  - Driver document update portal (/driver-doc-updates, /driver-update-portal/*)

Shared monitoring state (deques, caches) lives in routes.py and is imported here.
The before_request/after_request hooks that populate that state also remain in routes.py.
"""
import time as _sh_time
import os
import uuid
from datetime import datetime, timedelta

from flask import (
    render_template, request, redirect, url_for, flash, jsonify,
    session, abort, make_response, send_file,
)
from sqlalchemy import func, text

from app import app, db
from models import (
    Driver, Project, District, Notification, NotificationRead,
    ActivityLog, LoginLog, LoginAttempt, DeviceFCMToken,
    SystemSetting, User,
)
from utils import pk_now, pk_date

# Import shared monitoring state and helper functions from routes.py
# These are mutable objects (dicts, deques) — imports are references, not copies.
from routes import (
    _health_cache, _HEALTH_CACHE_TTL,
    _api_latency_ms, _latency_history, _session_history,
    _route_perf_log, _last_backup_ts, _health_alert_sent,
    _app_start_time,
    _administration_nav_back, _master_nav_back,
    media_url_filter, _attendance_local_date,
)


# ════════════════════════════════════════════════════════════════════════════════
# HEALTH ALERT (legacy — disabled, notifications v2 handles this)
# ════════════════════════════════════════════════════════════════════════════════

def _maybe_send_health_alert(data):
    """Legacy health notifications disabled (notifications v2)."""
    return
    try:
        if data.get('db_critical') and not _health_alert_sent['db']:
            _health_alert_sent['db'] = True
            _db_title = 'Database Storage Critical'
            _db_msg = (
                f"Database is at {data['db_pct']}% "
                f"({data['db_size_mb']} MB / {data['db_size_limit_mb']} MB). "
                "Upgrade plan or clean up data immediately."
            )
            n = Notification(
                title=_db_title, message=_db_msg,
                notification_type='danger', created_by_user_id=None,
                required_permission='backup,users_manage',
            )
            db.session.add(n)
            db.session.commit()
            try:
                from push_notifications import send_push_to_permitted
                send_push_to_permitted(['backup', 'users_manage'], _db_title, _db_msg)
            except Exception:
                pass
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
    try:
        if data.get('r2_critical') and not _health_alert_sent['r2']:
            _health_alert_sent['r2'] = True
            _r2_title = 'R2 Bucket Storage Critical'
            _r2_limit_gb = round(data.get('r2_size_limit_mb', 10240) / 1024)
            _r2_msg = (
                f"Cloudflare R2 is at {data['r2_pct']}% of its {_r2_limit_gb} GB limit. "
                "Delete unused files or upgrade your R2 plan."
            )
            n2 = Notification(
                title=_r2_title, message=_r2_msg,
                notification_type='danger', created_by_user_id=None,
                required_permission='backup,users_manage',
            )
            db.session.add(n2)
            db.session.commit()
            try:
                from push_notifications import send_push_to_permitted
                send_push_to_permitted(['backup', 'users_manage'], _r2_title, _r2_msg)
            except Exception:
                pass
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass


# ════════════════════════════════════════════════════════════════════════════════
# ROUTE DIAGNOSTICS — performance analysis from in-memory request log
# ════════════════════════════════════════════════════════════════════════════════

def _build_route_diagnostics(window_minutes=15):
    now_ts = int(_sh_time.time())
    cutoff = now_ts - (int(window_minutes) * 60)
    all_perf = list(_route_perf_log)
    recent = [x for x in all_perf if int(x.get('ts', 0)) >= cutoff]
    history_route_times = {}
    for row in all_perf:
        method = str(row.get('method') or 'GET').upper()
        endpoint_or_path = row.get('endpoint') or row.get('path') or 'unknown'
        hist_key = f'{method} {endpoint_or_path}'
        t = float(row.get('ms') or 0)
        if t <= 0:
            continue
        history_route_times.setdefault(hist_key, []).append(t)

    def _fmt_size(bytes_val):
        try:
            n = float(bytes_val or 0)
        except Exception:
            n = 0.0
        if n >= (1024 * 1024):
            return f'{round(n / (1024 * 1024), 2)} MB'
        if n >= 1024:
            return f'{round(n / 1024, 1)} KB'
        return f'{int(n)} B'

    route_buckets = {}
    for row in recent:
        method = str(row.get('method') or 'GET').upper()
        endpoint_or_path = row.get('endpoint') or row.get('path') or 'unknown'
        key = f'{method} {endpoint_or_path}'
        b = route_buckets.setdefault(key, {'times': [], 'errors': 0, 'path': row.get('path') or '', 'payloads': []})
        t = float(row.get('ms') or 0)
        if t > 0:
            b['times'].append(t)
        payload_bytes = int(row.get('payload_bytes') or 0)
        if payload_bytes > 0:
            b['payloads'].append(payload_bytes)
        st = int(row.get('status') or 0)
        if st >= 500:
            b['errors'] += 1

    top_slow = []
    for route_key, b in route_buckets.items():
        times = sorted(b['times'])
        if not times:
            continue
        hits = len(times)
        avg = round(sum(times) / hits, 1)
        p95 = round(times[max(0, int(hits * 0.95) - 1)], 1)
        mx = round(times[-1], 1)
        payloads = b.get('payloads') or []
        avg_payload_bytes = int(round(sum(payloads) / len(payloads))) if payloads else 0
        top_slow.append({
            'route': route_key,
            'path': b['path'],
            'hits': hits,
            'avg_ms': avg,
            'p95_ms': p95,
            'max_ms': mx,
            'error_count': int(b['errors']),
            'avg_payload_bytes': avg_payload_bytes,
            'avg_payload_size': _fmt_size(avg_payload_bytes),
        })
    top_slow.sort(key=lambda x: (x['p95_ms'], x['avg_ms']), reverse=True)
    top_slow = top_slow[:8]

    recent_errors = []
    for row in sorted(recent, key=lambda x: x.get('ts', 0), reverse=True):
        st = int(row.get('status') or 0)
        if st < 500:
            continue
        recent_errors.append({
            'time': datetime.utcfromtimestamp(int(row.get('ts', now_ts))).strftime('%H:%M:%S'),
            'route': row.get('endpoint') or row.get('path') or 'unknown',
            'status': st,
            'ms': round(float(row.get('ms') or 0), 1),
        })
        if len(recent_errors) >= 8:
            break

    overall_times = sorted([float(r.get('ms') or 0) for r in recent if float(r.get('ms') or 0) > 0])
    req_count = len(overall_times)
    avg_ms = round(sum(overall_times) / req_count, 1) if req_count else None
    p95_ms = round(overall_times[max(0, int(req_count * 0.95) - 1)], 1) if req_count else None
    err_count = sum(1 for r in recent if int(r.get('status') or 0) >= 500)
    slow_count = sum(1 for t in overall_times if t >= 1000)
    slow_rate_pct = round((slow_count * 100.0) / req_count, 1) if req_count else 0.0

    analysis = []
    if err_count > 0:
        analysis.append({
            'level': 'danger',
            'text': f'Found {err_count} server error response(s) in the last {window_minutes} minutes.',
        })
    if p95_ms is not None and p95_ms >= 1800:
        analysis.append({
            'level': 'danger',
            'text': f'High backend response time detected (p95 {p95_ms} ms). Software/database slowdown likely.',
        })
    elif p95_ms is not None and p95_ms >= 900:
        analysis.append({
            'level': 'warning',
            'text': f'Moderate slowdown detected (p95 {p95_ms} ms). Check heavy routes below.',
        })
    if req_count < 20:
        analysis.append({
            'level': 'info',
            'text': f'Low sample volume in the last {window_minutes} minutes. Trigger normal user actions for stronger diagnosis.',
        })
    smart_candidates = []
    for r in top_slow:
        hist = history_route_times.get(r['route']) or []
        if len(hist) < 40 or int(r.get('hits') or 0) < 5:
            continue
        baseline_avg = sum(hist) / len(hist)
        curr_avg = float(r.get('avg_ms') or 0)
        if baseline_avg <= 0 or curr_avg < 300:
            continue
        slow_pct = ((curr_avg - baseline_avg) / baseline_avg) * 100.0
        if slow_pct >= 20:
            smart_candidates.append((slow_pct, r['route']))
    if smart_candidates:
        smart_candidates.sort(reverse=True, key=lambda x: x[0])
        slow_pct, route_name = smart_candidates[0]
        analysis.append({
            'level': 'warning',
            'text': f"Warning: '{route_name}' is performing {round(slow_pct, 1)}% slower than usual.",
        })
    if top_slow:
        top_max = max(top_slow, key=lambda x: float(x.get('max_ms') or 0))
        top_max_ms = float(top_max.get('max_ms') or 0)
        if top_max_ms >= 2500:
            analysis.append({
                'level': 'warning',
                'text': f'Outlier spike detected on {top_max.get("route")} (max {round(top_max_ms, 1)} ms, hits {top_max.get("hits")}).',
            })
    if slow_rate_pct >= 15:
        analysis.append({
            'level': 'warning',
            'text': f'High slow-request ratio detected: {slow_rate_pct}% requests are >= 1000 ms.',
        })
    if not analysis:
        analysis.append({
            'level': 'success',
            'text': 'No major software bottleneck detected in recent server timings.',
        })

    return {
        'window_minutes': int(window_minutes),
        'request_count': req_count,
        'avg_ms': avg_ms,
        'p95_ms': p95_ms,
        'error_count': err_count,
        'slow_count': slow_count,
        'slow_rate_pct': slow_rate_pct,
        'top_slow_routes': top_slow,
        'recent_errors': recent_errors,
        'analysis': analysis,
    }


# ════════════════════════════════════════════════════════════════════════════════
# HEALTH DATA BUILDER — fetch live infrastructure metrics
# ════════════════════════════════════════════════════════════════════════════════

def _build_health_data():
    """Fetch live infrastructure metrics from Render API, PostgreSQL, R2, and internal sources."""
    import json
    import urllib.request
    import platform
    import flask as _flask_mod

    _db_limit = int(os.environ.get('DB_SIZE_LIMIT_MB', '1024'))
    _r2_limit = int(os.environ.get('R2_SIZE_LIMIT_GB', '10')) * 1024

    result = {
        'service':          None,
        'last_deploy':      None,
        'recent_deploys':   [],
        'db_size_mb':       None,
        'db_size_limit_mb': _db_limit,
        'r2_size_mb':       None,
        'r2_total_objects': 0,
        'r2_size_limit_mb': _r2_limit,
        'active_sessions':  None,
        'api_avg_ms':       None,
        'api_p95_ms':       None,
        'api_sample_count': 0,
        'last_backup_ts':   _last_backup_ts.get('ts'),
        'checks':           {},
        'errors':           [],
        'fetched_at':       pk_now().strftime('%d-%m-%Y %H:%M UTC'),
        'ram_mb':           None,
        'ram_limit_mb':     int(os.environ.get('RAM_LIMIT_MB', '512')),
        'ram_pct':          None,
        'upload_size_mb':   None,
        'upload_file_count': 0,
        'db_table_stats':   [],
        'fcm_total':        0,
        'fcm_active':       0,
        'fcm_inactive':     0,
        'sys_python':       platform.python_version(),
        'sys_flask':        _flask_mod.__version__,
        'sys_os':           f'{platform.system()} {platform.release()}',
        'sys_timezone':     app.config.get('APP_TIMEZONE', 'UTC'),
        'sys_server_time':  pk_now().strftime('%d-%m-%Y %H:%M:%S'),
        'sys_uptime_sec':   int(_sh_time.time() - _app_start_time),
        'latency_history':  list(_latency_history),
        'session_history':  list(_session_history),
        'backup_schedule_enabled': app.config.get('BACKUP_SCHEDULE_ENABLED', False),
        'backup_schedule_time':    app.config.get('BACKUP_SCHEDULE_TIME', '02:00'),
        'backup_email_to':         app.config.get('BACKUP_EMAIL_TO', ''),
        'diagnostics':             {},
    }

    render_key = os.environ.get('RENDER_API_KEY', '').strip()
    service_id = os.environ.get('RENDER_SERVICE_ID', '').strip()

    # 1. Render Service + Deploy History
    if render_key and service_id:
        try:
            hdr = {'Authorization': f'Bearer {render_key}', 'Accept': 'application/json'}
            req = urllib.request.Request(
                f'https://api.render.com/v1/services/{service_id}', headers=hdr)
            with urllib.request.urlopen(req, timeout=8) as r:
                result['service'] = json.loads(r.read())
            req2 = urllib.request.Request(
                f'https://api.render.com/v1/services/{service_id}/deploys?limit=5', headers=hdr)
            with urllib.request.urlopen(req2, timeout=8) as r2:
                deploys = json.loads(r2.read())
                parsed = [d.get('deploy', d) for d in deploys] if deploys else []
                result['recent_deploys'] = parsed
                if parsed:
                    result['last_deploy'] = parsed[0]
            svc_name   = (result['service'] or {}).get('name', service_id)
            svc_status = (result['service'] or {}).get('status', '?')
            result['checks']['render_api'] = {'status': 'ok', 'msg': f'{svc_name} is {svc_status}'}
        except Exception as e:
            msg = str(e)[:120]
            result['checks']['render_api'] = {'status': 'error', 'msg': msg}
            result['errors'].append(f'Render API: {msg}')
    else:
        result['checks']['render_api'] = {
            'status': 'skip', 'msg': 'RENDER_API_KEY or RENDER_SERVICE_ID not configured'}

    # 2. Database Size
    try:
        db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
        if 'postgresql' in db_uri:
            row = db.session.execute(text('SELECT pg_database_size(current_database()) AS sz')).fetchone()
            if row:
                result['db_size_mb'] = round(row.sz / (1024 * 1024), 1)
        else:
            db_path = db_uri.replace('sqlite:///', '')
            if db_path and os.path.isfile(db_path):
                result['db_size_mb'] = round(os.path.getsize(db_path) / (1024 * 1024), 1)
                result['db_size_limit_mb'] = 512
        result['checks']['db_size'] = {'status': 'ok', 'msg': f'{result["db_size_mb"]} MB used'}
    except Exception as e:
        msg = str(e)[:120]
        result['checks']['db_size'] = {'status': 'error', 'msg': msg}
        result['errors'].append(f'DB size: {msg}')

    # 3. Cloudflare R2 Bucket
    try:
        from r2_storage import _get_s3_client, R2_BUCKET_NAME
        client = _get_s3_client()
        paginator = client.get_paginator('list_objects_v2')
        total_bytes, total_objs = 0, 0
        for page in paginator.paginate(Bucket=R2_BUCKET_NAME):
            for obj in page.get('Contents', []):
                total_bytes += obj.get('Size', 0)
                total_objs += 1
        result['r2_size_mb']       = round(total_bytes / (1024 * 1024), 1)
        result['r2_total_objects'] = total_objs
        result['checks']['r2_storage'] = {
            'status': 'ok', 'msg': f'{result["r2_size_mb"]} MB, {total_objs} objects'}
    except Exception as e:
        msg = str(e)[:120]
        result['checks']['r2_storage'] = {'status': 'error', 'msg': msg}
        result['errors'].append(f'R2 storage: {msg}')

    # 4. Active Sessions
    try:
        cutoff = pk_now() - timedelta(minutes=30)
        active = db.session.query(ActivityLog.user_id).filter(
            ActivityLog.created_at >= cutoff).distinct().count()
        result['active_sessions'] = active
        result['checks']['sessions'] = {'status': 'ok', 'msg': f'{active} user(s) active in last 30 min'}
        _session_history.append(active)
    except Exception as e:
        result['checks']['sessions'] = {'status': 'error', 'msg': str(e)[:80]}

    # 5. API Latency
    if _api_latency_ms:
        samples = list(_api_latency_ms)
        avg = round(sum(samples) / len(samples), 1)
        result['api_avg_ms']       = avg
        result['api_sample_count'] = len(samples)
        p95_idx                    = max(0, int(len(samples) * 0.95) - 1)
        result['api_p95_ms']       = sorted(samples)[p95_idx]
        result['checks']['api_latency'] = {
            'status': 'ok',
            'msg': f'avg {avg}ms, p95 {result["api_p95_ms"]}ms ({len(samples)} samples)'}
        _latency_history.append(avg)
    else:
        result['checks']['api_latency'] = {
            'status': 'na', 'msg': 'No /api/* calls recorded yet in this session'}

    # 6. RAM / Memory Usage
    try:
        import resource
        rss_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
        result['ram_mb'] = round(rss_bytes / (1024 * 1024), 1)
    except Exception:
        try:
            import psutil
            result['ram_mb'] = round(psutil.Process().memory_info().rss / (1024 * 1024), 1)
        except Exception:
            pass
    if result['ram_mb'] is not None and result['ram_limit_mb']:
        result['ram_pct'] = round(result['ram_mb'] / result['ram_limit_mb'] * 100, 1)

    # 7. Upload Folder Size
    try:
        upload_dir = app.config.get('UPLOAD_FOLDER', '')
        if upload_dir and os.path.isdir(upload_dir):
            total_sz, total_cnt = 0, 0
            for dirpath, _dirnames, filenames in os.walk(upload_dir):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    try:
                        total_sz += os.path.getsize(fp)
                        total_cnt += 1
                    except OSError:
                        pass
            result['upload_size_mb'] = round(total_sz / (1024 * 1024), 1)
            result['upload_file_count'] = total_cnt
    except Exception:
        pass

    # 8. Database Table Stats (PostgreSQL only)
    try:
        db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
        if 'postgresql' in db_uri:
            tbl_q = text("""
                SELECT relname AS name,
                       n_live_tup AS row_count,
                       pg_total_relation_size(relid) AS size_bytes
                FROM pg_stat_user_tables
                ORDER BY pg_total_relation_size(relid) DESC
                LIMIT 10
            """)
            rows = db.session.execute(tbl_q).fetchall()
            result['db_table_stats'] = [
                {'name': r.name, 'rows': r.row_count,
                 'size_mb': round(r.size_bytes / (1024 * 1024), 2)}
                for r in rows
            ]
    except Exception:
        pass

    # 9. FCM / Notification Stats
    try:
        result['fcm_total']    = DeviceFCMToken.query.count()
        result['fcm_active']   = DeviceFCMToken.query.filter_by(is_active=True).count()
        result['fcm_inactive'] = result['fcm_total'] - result['fcm_active']
    except Exception:
        pass

    # 10. Security — Login Attempts (last 24h)
    try:
        _sec_cutoff = pk_now() - timedelta(hours=24)
        result['failed_logins_24h'] = LoginAttempt.query.filter(
            LoginAttempt.success == False,
            LoginAttempt.created_at >= _sec_cutoff
        ).count()
        result['success_logins_24h'] = LoginAttempt.query.filter(
            LoginAttempt.success == True,
            LoginAttempt.created_at >= _sec_cutoff
        ).count()
        _top_ips_q = db.session.query(
            LoginAttempt.ip_address, func.count(LoginAttempt.id).label('cnt')
        ).filter(
            LoginAttempt.success == False,
            LoginAttempt.created_at >= _sec_cutoff
        ).group_by(LoginAttempt.ip_address).order_by(func.count(LoginAttempt.id).desc()).limit(5).all()
        result['top_fail_ips'] = [{'ip': r[0] or 'unknown', 'count': r[1]} for r in _top_ips_q]
        _active_users = db.session.query(
            User.full_name, ActivityLog.created_at
        ).join(User, User.id == ActivityLog.user_id).filter(
            ActivityLog.created_at >= pk_now() - timedelta(minutes=30)
        ).group_by(User.id, User.full_name, ActivityLog.created_at).order_by(
            ActivityLog.created_at.desc()
        ).limit(20).all()
        _seen = set()
        _active_list = []
        for name, ts in _active_users:
            if name not in _seen:
                _seen.add(name)
                _active_list.append({'name': name, 'last_seen': ts.strftime('%H:%M') if ts else '?'})
        result['active_user_list'] = _active_list[:10]
    except Exception:
        result['failed_logins_24h'] = 0
        result['success_logins_24h'] = 0
        result['top_fail_ips'] = []
        result['active_user_list'] = []

    # 11. Row counts for cleanup targets
    try:
        result['row_count_activity'] = ActivityLog.query.count()
        result['row_count_login'] = LoginLog.query.count()
        result['row_count_notifications'] = Notification.query.count()
        result['row_count_login_attempts'] = LoginAttempt.query.count()
    except Exception:
        result['row_count_activity'] = 0
        result['row_count_login'] = 0
        result['row_count_notifications'] = 0
        result['row_count_login_attempts'] = 0

    # 12. Persistent backup info from SystemSetting
    try:
        result['last_backup_ts_persistent'] = SystemSetting.get('last_backup_ts')
        result['last_backup_result'] = SystemSetting.get('last_backup_result', 'unknown')
        result['last_backup_size'] = SystemSetting.get('last_backup_size')
    except Exception:
        result['last_backup_ts_persistent'] = None
        result['last_backup_result'] = 'unknown'
        result['last_backup_size'] = None

    # Percentages & Critical Flags
    result['db_pct']       = round(result['db_size_mb'] / result['db_size_limit_mb'] * 100, 1) if result['db_size_mb'] is not None else None
    result['r2_pct']       = round(result['r2_size_mb'] / result['r2_size_limit_mb'] * 100, 1) if result['r2_size_mb'] is not None else None
    result['db_critical']  = bool(result['db_pct'] is not None and result['db_pct'] >= 80)
    result['r2_critical']  = bool(result['r2_pct'] is not None and result['r2_pct'] >= 80)
    result['any_critical'] = result['db_critical'] or result['r2_critical']

    # 13. Software diagnostics from route-level timings
    try:
        result['diagnostics'] = _build_route_diagnostics(window_minutes=15)
    except Exception as e:
        result['diagnostics'] = {
            'window_minutes': 15,
            'request_count': 0,
            'avg_ms': None,
            'p95_ms': None,
            'error_count': 0,
            'top_slow_routes': [],
            'recent_errors': [],
            'analysis': [{'level': 'danger', 'text': f'Diagnostics engine error: {str(e)[:120]}'}],
        }

    _maybe_send_health_alert(result)
    return result


def _fetch_system_health(force=False):
    import time as _t
    now = _t.time()
    if (not force) and _health_cache['data'] and _health_cache['ts'] and (now - _health_cache['ts']) < _HEALTH_CACHE_TTL:
        return _health_cache['data']
    data = _build_health_data()
    _health_cache['data'] = data
    _health_cache['ts']   = now
    return data


# ════════════════════════════════════════════════════════════════════════════════
# SYSTEM HEALTH ROUTES
# ════════════════════════════════════════════════════════════════════════════════

@app.route('/admin/system-health')
def system_health():
    """System Health & Cloud Status page — Master only."""
    if not session.get('is_master'):
        abort(403)
    force = request.args.get('refresh') == '1'
    data  = _fetch_system_health(force=force)
    env_vars_set = {k: bool(os.environ.get(k, '').strip()) for k in [
        'RENDER_API_KEY', 'RENDER_SERVICE_ID',
        'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY', 'R2_ENDPOINT_URL', 'R2_BUCKET_NAME',
        'DATABASE_URL', 'SECRET_KEY',
    ]}
    return render_template('system_health.html', data=data, env_vars_set=env_vars_set, **_administration_nav_back())


@app.route('/admin/system-health/api')
def system_health_api():
    """JSON API for auto-refresh — Master only."""
    if not session.get('is_master'):
        return jsonify({'error': 'Forbidden'}), 403
    data = _fetch_system_health(force=False)
    return jsonify(data)


@app.route('/admin/system-health/diagnostics/api')
def system_health_diagnostics_api():
    """Diagnostics-only JSON payload for live tab refresh."""
    if not session.get('is_master'):
        return jsonify({'error': 'Forbidden'}), 403
    return jsonify(_build_route_diagnostics(window_minutes=15))


@app.route('/network-probe')
def network_probe():
    """Small payload endpoint used by frontend to estimate network speed."""
    kb = request.args.get('kb', type=int) or 32
    kb = max(8, min(kb, 256))
    payload = ('x' * 1024) * kb
    resp = make_response(payload)
    resp.headers['Content-Type'] = 'text/plain; charset=utf-8'
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return resp


@app.route('/health')
def health_check():
    """Public health check for external monitoring (UptimeRobot, etc.)."""
    try:
        db.session.execute(text('SELECT 1'))
        db_ok = True
    except Exception:
        db_ok = False
    uptime = int(_sh_time.time() - _app_start_time)
    status_code = 200 if db_ok else 503
    return jsonify({
        'status': 'ok' if db_ok else 'degraded',
        'db': db_ok,
        'uptime_seconds': uptime,
    }), status_code


@app.route('/admin/system-health/cleanup', methods=['POST'])
def system_health_cleanup():
    """Purge old data from specified table. Master only."""
    if not session.get('is_master'):
        return jsonify({'error': 'Forbidden'}), 403
    target = request.form.get('target', '')
    days = int(request.form.get('days', '90'))
    cutoff = pk_now() - timedelta(days=days)
    deleted = 0
    try:
        if target == 'activity_log':
            deleted = ActivityLog.query.filter(ActivityLog.created_at < cutoff).delete()
        elif target == 'login_log':
            deleted = LoginLog.query.filter(LoginLog.login_at < cutoff).delete()
        elif target == 'notifications':
            read_ids = db.session.query(NotificationRead.notification_id).filter(
                NotificationRead.read_at < cutoff
            ).subquery()
            deleted = Notification.query.filter(
                Notification.id.in_(db.session.query(read_ids)),
                Notification.created_at < cutoff
            ).delete(synchronize_session='fetch')
        elif target == 'login_attempts':
            deleted = LoginAttempt.query.filter(LoginAttempt.created_at < cutoff).delete()
        else:
            return jsonify({'error': 'Unknown target'}), 400
        db.session.commit()
        _health_cache['data'] = None
        return jsonify({'ok': True, 'deleted': deleted, 'target': target, 'days': days})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)[:200]}), 500


@app.cli.command('fix-driver-status')
def fix_driver_status():
    """One-time backfill: calculate cnic_status and license_status for all drivers where it is blank."""
    today = pk_date()
    drivers = Driver.query.all()
    updated = 0
    for d in drivers:
        changed = False
        if d.cnic_expiry_date:
            correct = 'Valid' if d.cnic_expiry_date >= today else 'Expired'
            if d.cnic_status != correct:
                d.cnic_status = correct
                changed = True
        if d.license_expiry_date:
            correct = 'Valid' if d.license_expiry_date >= today else 'Expired'
            if d.license_status != correct:
                d.license_status = correct
                changed = True
        if changed:
            updated += 1
    db.session.commit()
    app.logger.info('Driver photo path fix: %d/%d updated.', updated, len(drivers))


# ════════════════════════════════════════════════════════════════════════════════
# Tracker Automation — TrackingWorld portal robot
# ════════════════════════════════════════════════════════════════════════════════

@app.route('/administration/tracker-automation', methods=['GET'])
def tracker_automation():
    """Main Tracker Automation page — settings + start job + live status."""
    if not session.get('is_master'):
        abort(403)
    from models import TrackerAutomationSettings, TrackerAutomationJob
    settings = TrackerAutomationSettings.query.first()
    today = _attendance_local_date().strftime('%Y-%m-%d')
    # Latest job (running or most recent)
    job = TrackerAutomationJob.query.filter(
        TrackerAutomationJob.status.in_(['running', 'pending'])
    ).order_by(TrackerAutomationJob.id.desc()).first()
    if not job:
        job = TrackerAutomationJob.query.order_by(TrackerAutomationJob.id.desc()).first()
    active_job = TrackerAutomationJob.query.filter(
        TrackerAutomationJob.status.in_(['running', 'pending'])
    ).first()
    past_jobs = TrackerAutomationJob.query.filter(
        TrackerAutomationJob.status.in_(['done', 'failed'])
    ).order_by(TrackerAutomationJob.id.desc()).limit(10).all()
    return render_template(
        'tracker_automation.html',
        settings=settings,
        job=job,
        active_job=active_job,
        past_jobs=past_jobs,
        today=today,
        **_administration_nav_back(),
    )


@app.route('/administration/tracker-automation/save-settings', methods=['POST'])
def tracker_automation_save_settings():
    """Save portal credentials (password encrypted with Fernet)."""
    if not session.get('is_master'):
        abort(403)
    from models import TrackerAutomationSettings
    from tracker_automation import encrypt_password
    portal_url = (request.form.get('portal_url') or '').strip()
    username = (request.form.get('username') or '').strip()
    password_plain = (request.form.get('password') or '').strip()
    settings = TrackerAutomationSettings.query.first()
    if not settings:
        settings = TrackerAutomationSettings()
        db.session.add(settings)
    settings.portal_url = portal_url
    settings.username = username
    if password_plain:
        settings.password_enc = encrypt_password(password_plain)
    db.session.commit()
    flash('Settings save ho gayi.', 'success')
    return redirect(url_for('tracker_automation'))


@app.route('/administration/tracker-automation/start', methods=['POST'])
def tracker_automation_start():
    """Create a new job and launch background Playwright thread."""
    if not session.get('is_master'):
        abort(403)
    from models import TrackerAutomationJob, TrackerAutomationSettings
    from tracker_automation import launch_tracker_job
    settings = TrackerAutomationSettings.query.first()
    if not settings or not settings.portal_url:
        flash('Pehle portal credentials save karein.', 'warning')
        return redirect(url_for('tracker_automation'))
    # Block if a job is already running
    active = TrackerAutomationJob.query.filter(
        TrackerAutomationJob.status.in_(['running', 'pending'])
    ).first()
    if active:
        flash(f'Job #{active.id} abhi chal raha hai. Pehle complete hone dein.', 'warning')
        return redirect(url_for('tracker_automation'))
    date_from_str = (request.form.get('date_from') or '').strip()
    date_to_str = (request.form.get('date_to') or '').strip()
    try:
        from datetime import datetime as _dt
        date_from = _dt.strptime(date_from_str, '%Y-%m-%d').date()
        date_to = _dt.strptime(date_to_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        flash('Date format galat hai.', 'danger')
        return redirect(url_for('tracker_automation'))
    if date_from > date_to:
        flash('From date, To date se pehle honi chahiye.', 'warning')
        return redirect(url_for('tracker_automation'))
    job = TrackerAutomationJob(
        date_from=date_from,
        date_to=date_to,
        status='pending',
        log_text='Job queue mein hai...',
    )
    db.session.add(job)
    db.session.commit()
    launch_tracker_job(job.id, app)
    flash(f'Job #{job.id} shuru ho gaya. Status neeche dekhein.', 'success')
    return redirect(url_for('tracker_automation'))


@app.route('/api/tracker-automation/job-status/<int:job_id>')
def tracker_automation_job_status(job_id):
    """JSON polling endpoint for live job status update."""
    if not session.get('is_master'):
        return jsonify({'ok': False}), 403
    from models import TrackerAutomationJob
    job = TrackerAutomationJob.query.get_or_404(job_id)
    return jsonify({
        'ok': True,
        'status': job.status,
        'total_vehicles': job.total_vehicles,
        'done_vehicles': job.done_vehicles,
        'failed_vehicles': job.failed_vehicles,
        'log_text': job.log_text or '',
        'zip_path': job.zip_path or '',
        'finished_at': job.finished_at.strftime('%d-%m-%Y %H:%M:%S') if job.finished_at else None,
    })


@app.route('/administration/tracker-automation/download-zip/<int:job_id>')
def tracker_automation_download_zip(job_id):
    """Stream the completed ZIP file to the browser."""
    if not session.get('is_master'):
        abort(403)
    from models import TrackerAutomationJob
    import pathlib
    job = TrackerAutomationJob.query.get_or_404(job_id)
    if job.status != 'done' or not job.zip_path:
        flash('ZIP file abhi ready nahi hai.', 'warning')
        return redirect(url_for('tracker_automation'))
    zip_path = pathlib.Path(job.zip_path)
    if not zip_path.exists():
        flash('ZIP file server pe nahi mili (shayad expire ho gaya).', 'danger')
        return redirect(url_for('tracker_automation'))
    from flask import send_file
    download_name = f'activity_reports_{job.date_from.strftime("%d-%m-%Y")}_to_{job.date_to.strftime("%d-%m-%Y")}.zip'
    return send_file(
        str(zip_path),
        as_attachment=True,
        download_name=download_name,
        mimetype='application/zip',
    )


# ════════════════════════════════════════════════════════════════════════════════
# DRIVER DOCUMENT UPDATE PORTAL – LIST + PORTAL
# ════════════════════════════════════════════════════════════════════════════════
@app.route('/driver-doc-updates')
def driver_doc_updates_list():
    if not session.get('is_master'):
        abort(403)
    from driver_doc_history_utils import (
        backfill_driver_doc_batch_ids,
        count_doc_update_stats,
        paginate_doc_update_events,
    )

    backfill_driver_doc_batch_ids(db.session)

    project_id = request.args.get('project_id', type=int) or 0
    district_id = request.args.get('district_id', type=int) or 0
    update_type = request.args.get('update_type', '').strip()
    q = (request.args.get('q') or '').strip()
    per_page = request.args.get('per_page', 20, type=int)
    page = request.args.get('page', 1, type=int)

    pagination = paginate_doc_update_events(
        db.session,
        page=page,
        per_page=per_page,
        project_id=project_id,
        district_id=district_id,
        update_type=update_type,
        q=q,
    )
    stats = count_doc_update_stats(
        db.session,
        project_id=project_id,
        district_id=district_id,
        update_type=update_type,
        q=q,
    )

    projects_list = Project.query.order_by(Project.name).all()
    project_choices = [(0, '-- All Projects --')] + [(p.id, p.name) for p in projects_list]
    districts_list = District.query.order_by(District.name).all()
    district_choices = [(0, '-- All Districts --')] + [(d2.id, d2.name) for d2 in districts_list]

    return render_template(
        'driver_doc_updates_list.html',
        events=pagination['items'],
        pagination=pagination,
        stats=stats,
        per_page=per_page,
        project_id=project_id,
        district_id=district_id,
        update_type=update_type,
        q=q,
        project_choices=project_choices,
        district_choices=district_choices,
        **_master_nav_back(),
    )


@app.route('/driver-doc-updates/delete/<batch_id>', methods=['POST'])
def driver_doc_update_delete(batch_id):
    if not session.get('is_master'):
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'ok': False, 'message': 'Access denied'}), 403
        abort(403)
    update_type = (request.form.get('update_type') or '').strip() or None
    if update_type and update_type not in ('cnic', 'license', 'bank_uniform'):
        return jsonify({'ok': False, 'message': 'Invalid update type'}), 400
    from driver_doc_history_utils import delete_doc_update_batch
    ok, msg = delete_doc_update_batch(db.session, batch_id, update_type=update_type)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'ok': ok, 'message': msg}), (200 if ok else 400)
    flash(msg, 'success' if ok else 'danger')
    return redirect(request.referrer or url_for('driver_doc_updates_list'))


@app.route('/driver-update-portal')
def driver_update_portal():
    if not session.get('is_master'):
        abort(403)
    projects = Project.query.order_by(Project.name).all()
    active_tab = request.args.get('tab', 'cnic')
    if active_tab == 'bank':
        active_tab = 'bank_uniform'
    preselect_driver_id = request.args.get('driver_id', type=int)
    from_profile = request.args.get('from') == 'profile'
    tab_map = {'cnic': 'cnic', 'license': 'license', 'bank_uniform': 'bank'}
    portal_tab = tab_map.get(active_tab, 'cnic')
    return render_template(
        'driver_update_portal.html',
        projects=projects,
        active_tab=active_tab if active_tab != 'bank_uniform' else 'bank',
        portal_tab=portal_tab,
        preselect_driver_id=preselect_driver_id,
        from_profile=from_profile,
        update_source_value='profile' if from_profile else 'portal',
        **_master_nav_back(),
    )


@app.route('/api/driver-profile/<int:driver_id>/doc-update-history/<update_type>')
def api_driver_doc_update_history(driver_id, update_type):
    """JSON — grouped document update history for one driver + type (profile popup)."""
    if not session.get('is_master'):
        return jsonify({'error': 'Access denied'}), 403
    if update_type not in ('cnic', 'license', 'bank_uniform'):
        return jsonify({'error': 'Invalid update type'}), 400
    driver = db.session.get(Driver, driver_id)
    if not driver:
        return jsonify({'error': 'Driver not found'}), 404
    from driver_doc_history_utils import fetch_driver_doc_events_json
    events = fetch_driver_doc_events_json(db.session, driver_id, update_type, limit=50)
    for ev in events:
        for fld in ev.get('fields') or []:
            if fld.get('old_is_media') and fld.get('old_value'):
                fld['old_media_url'] = media_url_filter(fld['old_value'])
            if fld.get('new_is_media') and fld.get('new_value'):
                fld['new_media_url'] = media_url_filter(fld['new_value'])
    labels = {'cnic': 'CNIC', 'license': 'License', 'bank_uniform': 'Bank & Uniform'}
    return jsonify({
        'driver_id': driver_id,
        'driver_name': driver.name or '',
        'update_type': update_type,
        'update_label': labels.get(update_type, update_type),
        'events': events,
        'total': len(events),
    })


@app.route('/api/driver-update-portal/driver-info/<int:driver_id>')
def driver_update_portal_info(driver_id):
    """JSON API — returns driver details for the update portal."""
    if not session.get('is_master'):
        return jsonify({'error': 'Access denied'}), 403
    driver = db.session.get(Driver, driver_id)
    if not driver:
        return jsonify({'error': 'Driver not found'}), 404

    def _fmt_date(d):
        if not d:
            return ''
        return d.strftime('%d-%m-%Y')

    vehicle_no = ''
    if driver.vehicle:
        vehicle_no = driver.vehicle.vehicle_no

    return jsonify({
        'id': driver.id,
        'driver_id': driver.driver_id or '',
        'name': driver.name or '',
        'father_name': driver.father_name or '',
        'phone1': driver.phone1 or '',
        'driver_district': driver.driver_district or '',
        'vehicle_no': vehicle_no,
        'project_id': driver.project_id,
        'district_id': driver.district_id,
        'vehicle_id': driver.vehicle_id,
        'photo_url': media_url_filter(driver.photo_path) if driver.photo_path else '',
        # CNIC
        'cnic_no': driver.cnic_no or '',
        'cnic_issue_date': _fmt_date(driver.cnic_issue_date),
        'cnic_expiry_date': _fmt_date(driver.cnic_expiry_date),
        'cnic_status': driver.cnic_status or '',
        'cnic_front_url': media_url_filter(driver.cnic_front_path) if driver.cnic_front_path else '',
        'cnic_back_url': media_url_filter(driver.cnic_back_path) if driver.cnic_back_path else '',
        # License
        'license_no': driver.license_no or '',
        'license_type': driver.license_type or '',
        'issue_district': driver.issue_district or '',
        'license_issue_date': _fmt_date(driver.license_issue_date),
        'license_valid_from': _fmt_date(driver.license_valid_from),
        'license_valid_to': _fmt_date(driver.license_expiry_date),
        'license_status': driver.license_status or '',
        'license_front_url': media_url_filter(driver.license_front_path) if driver.license_front_path else '',
        'license_back_url': media_url_filter(driver.license_back_path) if driver.license_back_path else '',
        'verify_license_url': media_url_filter(driver.verify_license_photo_path) if driver.verify_license_photo_path else '',
        # Bank & Uniform
        'bank_name': driver.bank_name or '',
        'account_no': driver.account_no or '',
        'account_title': driver.account_title or '',
        'shirt_size': driver.shirt_size or '',
        'trouser_size': driver.trouser_size or '',
        'jacket_size': driver.jacket_size or '',
    })


@app.route('/driver-update-portal/save/<update_type>', methods=['POST'])
def driver_update_portal_save(update_type):
    """Save CNIC / License / Bank & Uniform updates with history."""
    if not session.get('is_master'):
        abort(403)

    from models import DriverDocumentHistory
    from driver_doc_history_utils import ensure_driver_doc_history_schema

    ensure_driver_doc_history_schema(db.session)

    driver_id = request.form.get('driver_id', type=int)
    if not driver_id:
        flash('Driver not selected.', 'danger')
        return redirect(url_for('driver_update_portal', tab=update_type))

    driver = db.session.get(Driver, driver_id)
    if not driver:
        flash('Driver not found.', 'danger')
        return redirect(url_for('driver_update_portal', tab=update_type))

    updated_by = session.get('user_id_display') or session.get('user_id') or 'system'
    batch_id = str(uuid.uuid4())
    update_source = (request.form.get('update_source') or 'portal').strip()
    if update_source not in ('profile', 'portal'):
        update_source = 'portal'

    def _portal_redirect(tab, did=None):
        kw = {'tab': tab}
        if did:
            kw['driver_id'] = did
        if update_source == 'profile':
            kw['from'] = 'profile'
        return redirect(url_for('driver_update_portal', **kw))

    # R2 upload helper (same pattern as driver_form)
    from r2_storage import upload_image_file as _r2_img, R2_PUBLIC_URL as _r2_url
    from r2_storage import R2_ACCESS_KEY_ID as _r2_key, R2_ENDPOINT_URL as _r2_ep, R2_BUCKET_NAME as _r2_bkt
    _use_r2 = bool(_r2_url and _r2_key and _r2_ep and _r2_bkt)

    def _upload_img(file_storage, r2_folder):
        if not (file_storage and file_storage.filename):
            return None
        file_storage.seek(0)
        if _use_r2:
            try:
                url = _r2_img(file_storage, folder=r2_folder)
                return url
            except Exception as e:
                app.logger.error('R2 upload failed: %s', e)
                return None
        return None

    def _record_change(field_name, old_val, new_val):
        if str(old_val or '') != str(new_val or ''):
            db.session.add(DriverDocumentHistory(
                batch_id=batch_id,
                driver_id=driver.id,
                update_type=update_type,
                field_name=field_name,
                old_value=str(old_val or ''),
                new_value=str(new_val or ''),
                updated_by=str(updated_by),
                update_source=update_source,
            ))
            return True
        return False

    def _handle_photo_field(field_name, file_key, folder, archive_if_missing):
        """Upload new photo, or archive current photo to history when doc fields changed but file not re-uploaded."""
        old = getattr(driver, field_name) or ''
        uploaded = _upload_img(request.files.get(file_key), folder)
        if uploaded:
            if _record_change(field_name, old, uploaded):
                setattr(driver, field_name, uploaded)
            return True
        if archive_if_missing and old:
            if _record_change(field_name, old, ''):
                setattr(driver, field_name, None)
            return True
        return False

    changes_made = False

    def _track(ok):
        nonlocal changes_made
        if ok:
            changes_made = True

    try:
        if update_type == 'cnic':
            # Parse new expiry date
            expiry_raw = (request.form.get('cnic_expiry_date') or '').strip()
            new_expiry = None
            if expiry_raw:
                from datetime import datetime as _dt
                try:
                    new_expiry = _dt.strptime(expiry_raw, '%d-%m-%Y').date()
                except ValueError:
                    flash('Invalid CNIC Expiry Date format. Use dd-mm-yyyy.', 'danger')
                    return redirect(url_for('driver_update_portal', tab='cnic'))

            doc_fields_changed = False
            if new_expiry:
                if _record_change('cnic_expiry_date', driver.cnic_expiry_date, new_expiry):
                    driver.cnic_expiry_date = new_expiry
                    doc_fields_changed = True
                    changes_made = True
                _today = pk_date()
                new_status = 'Valid' if new_expiry >= _today else 'Expired'
                if _record_change('cnic_status', driver.cnic_status, new_status):
                    driver.cnic_status = new_status
                    doc_fields_changed = True
                    changes_made = True

            _track(_handle_photo_field('cnic_front_path', 'cnic_front', 'drivers/cnic', doc_fields_changed))
            _track(_handle_photo_field('cnic_back_path', 'cnic_back', 'drivers/cnic', doc_fields_changed))

            if not changes_made:
                flash('No changes to save.', 'warning')
                return _portal_redirect('cnic', driver_id)

            db.session.commit()
            flash(f"CNIC details for '{driver.name}' updated successfully!", 'success')

        elif update_type == 'license':
            # Parse dates
            valid_from_raw = (request.form.get('license_valid_from') or '').strip()
            valid_to_raw = (request.form.get('license_valid_to') or '').strip()
            from datetime import datetime as _dt

            new_valid_from = None
            if valid_from_raw:
                try:
                    new_valid_from = _dt.strptime(valid_from_raw, '%d-%m-%Y').date()
                except ValueError:
                    flash('Invalid License Valid From date format.', 'danger')
                    return redirect(url_for('driver_update_portal', tab='license'))

            new_valid_to = None
            if valid_to_raw:
                try:
                    new_valid_to = _dt.strptime(valid_to_raw, '%d-%m-%Y').date()
                except ValueError:
                    flash('Invalid License Valid To date format.', 'danger')
                    return redirect(url_for('driver_update_portal', tab='license'))

            doc_fields_changed = False
            if new_valid_from is not None:
                if _record_change('license_valid_from', driver.license_valid_from, new_valid_from):
                    driver.license_valid_from = new_valid_from
                    doc_fields_changed = True
                    changes_made = True

            if new_valid_to:
                if _record_change('license_expiry_date', driver.license_expiry_date, new_valid_to):
                    driver.license_expiry_date = new_valid_to
                    doc_fields_changed = True
                    changes_made = True
                _today = pk_date()
                new_status = 'Valid' if new_valid_to >= _today else 'Expired'
                if _record_change('license_status', driver.license_status, new_status):
                    driver.license_status = new_status
                    doc_fields_changed = True
                    changes_made = True

            _track(_handle_photo_field('license_front_path', 'license_front', 'drivers/license', doc_fields_changed))
            _track(_handle_photo_field('license_back_path', 'license_back', 'drivers/license', doc_fields_changed))
            _track(_handle_photo_field('verify_license_photo_path', 'verify_license_photo', 'drivers/license', doc_fields_changed))

            if not changes_made:
                flash('No changes to save.', 'warning')
                return _portal_redirect('license', driver_id)

            db.session.commit()
            flash(f"License details for '{driver.name}' updated successfully!", 'success')

        elif update_type == 'bank_uniform':
            fields = {
                'bank_name': request.form.get('bank_name', '').strip(),
                'account_no': request.form.get('account_no', '').strip(),
                'account_title': request.form.get('account_title', '').strip(),
                'shirt_size': request.form.get('shirt_size', '').strip(),
                'trouser_size': request.form.get('trouser_size', '').strip(),
                'jacket_size': request.form.get('jacket_size', '').strip(),
            }
            for field_name, new_val in fields.items():
                old_val = getattr(driver, field_name, '') or ''
                if new_val != old_val:
                    if _record_change(field_name, old_val, new_val):
                        setattr(driver, field_name, new_val or None)
                        changes_made = True

            if not changes_made:
                flash('No changes to save.', 'warning')
                return _portal_redirect('bank', driver_id)

            db.session.commit()
            flash(f"Bank & Uniform details for '{driver.name}' updated successfully!", 'success')

        else:
            flash('Invalid update type.', 'danger')

    except Exception as e:
        db.session.rollback()
        flash(f'Error saving update: {str(e)}', 'danger')

    tab_redirect = 'bank' if update_type == 'bank_uniform' else update_type
    return _portal_redirect(tab_redirect, driver_id)
