"""
Misc: Global Search, Fleet Map, PWA, File Serving, Image Proxy,
VCard, Blob Upload/Download, Account Profile, Biometric, Mobile Init,
Session Ping, App Logout, Password Set/Change.

Extracted from routes.py to reduce file size.
"""

from flask import (
    render_template, redirect, url_for, flash, request,
    session, jsonify, make_response, abort, send_from_directory,
    send_file, Response, current_app,
)
from app import app, db, csrf
from models import (
    User, Role, Permission, Driver, Vehicle,
    SystemSetting, ActivityLog, LoginLog,
)
from forms import (
    ChangePasswordForm,
)
from datetime import datetime, date, timedelta
from sqlalchemy import func, text, or_, and_
from werkzeug.utils import secure_filename
from auth_utils import user_can_access, check_password
from utils import pk_now, pk_date, parse_date, format_date_ddmmyyyy
import re
import os
import json
import uuid
import tempfile
import hashlib
import hmac
import io
from io import BytesIO, StringIO

# Import shared helpers from routes.py
from routes import (
    _multi_word_filter,
    media_url_filter,
    require_login,
    _get_user_scope,
    _validate_csrf_exempt_origin,
    _persist_client_diagnostic,
    _cnic_digits,
    DEFAULT_FIRST_PASSWORD,
    _biometric_token_valid,
    _time_mod,
)

from models import District, DriverAttendance, Employee, Project
from forms import SetNewPasswordForm
from vehicle_sort_utils import vehicle_order_by
from auth_utils import generate_password_hash
@app.route('/api/global-search')
def api_global_search():
    """Global search: returns matching Drivers and Vehicles as JSON. Used by navbar search bar."""
    q = request.args.get('q', '').strip()
    if not q or len(q) < 2:
        return jsonify({'drivers': [], 'vehicles': []})
    flt_d = _multi_word_filter(q, Driver.name, Driver.driver_id, Driver.cnic_no, Driver.phone1)
    drivers = Driver.query.filter(flt_d).order_by(Driver.name).limit(8).all() if flt_d is not None else []
    flt_v = _multi_word_filter(q, Vehicle.vehicle_no, Vehicle.model, Vehicle.engine_no)
    vehicles = Vehicle.query.filter(flt_v).order_by(*vehicle_order_by()).limit(6).all() if flt_v is not None else []
    return jsonify({
        'drivers': [{'id': d.id, 'name': d.name, 'driver_id': d.driver_id,
                     'status': d.status, 'cnic': d.cnic_no} for d in drivers],
        'vehicles': [{'id': v.id, 'vehicle_no': v.vehicle_no, 'model': v.model,
                      'vehicle_type': v.vehicle_type} for v in vehicles],
    })



@app.route('/api/fleet-map-pins')
def api_fleet_map_pins():
    """Return latest GPS check-in coordinates for active drivers. Used by Live Fleet Map on dashboard."""
    from sqlalchemy import func
    try:
        latest_subq = db.session.query(
            DriverAttendance.driver_id,
            func.max(DriverAttendance.id).label('max_id')
        ).filter(
            DriverAttendance.check_in_latitude.isnot(None),
            DriverAttendance.check_in_longitude.isnot(None)
        ).group_by(DriverAttendance.driver_id).subquery()

        rows = db.session.query(
            DriverAttendance, Driver, Vehicle, Project
        ).join(
            latest_subq, DriverAttendance.id == latest_subq.c.max_id
        ).join(
            Driver, Driver.id == DriverAttendance.driver_id
        ).outerjoin(
            Vehicle, Vehicle.id == Driver.vehicle_id
        ).outerjoin(
            Project, Project.id == DriverAttendance.project_id
        ).filter(Driver.status == 'Active').all()

        pins = []
        for att, drv, veh, proj in rows:
            pins.append({
                'lat': float(att.check_in_latitude),
                'lng': float(att.check_in_longitude),
                'driver': drv.name,
                'driver_id': drv.driver_id or '',
                'vehicle': veh.vehicle_no if veh else '—',
                'project': proj.name if proj else '—',
                'date': att.attendance_date.strftime('%d %b %Y') if att.attendance_date else '',
            })
        return jsonify({'ok': True, 'pins': pins})
    except Exception as e:
        return jsonify({'ok': False, 'pins': [], 'error': str(e)})



@app.route('/manifest.json')
def pwa_manifest():
    return send_from_directory('static', 'manifest.json', mimetype='application/manifest+json')



@app.route('/sw.js')
def service_worker():
    resp = send_from_directory('static', 'sw.js', mimetype='application/javascript')
    resp.headers['Service-Worker-Allowed'] = '/'
    resp.headers['Cache-Control'] = 'no-cache'
    return resp



@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    """Serve files from UPLOAD_FOLDER. Path must be under uploads (no traversal)."""
    base = os.path.abspath(app.config['UPLOAD_FOLDER'])
    path = os.path.abspath(os.path.join(base, filename))
    if not path.startswith(base) or not os.path.isfile(path):
        return '', 404
    return send_from_directory(base, filename)



@app.route('/image-proxy')
def image_proxy():
    """Proxy an external image (R2) through Flask so html2canvas can capture it same-origin."""
    import urllib.request as _urllib_req
    from urllib.parse import urlparse as _urlparse
    import ipaddress as _ipaddr
    url = request.args.get('url', '').strip()
    if not url or not (url.startswith('https://') or url.startswith('http://')):
        return '', 400
    parsed = _urlparse(url)
    hostname = (parsed.hostname or '').lower()
    if not hostname:
        return '', 400
    # SE-05: Block SSRF — reject private/loopback/link-local/reserved IPs
    try:
        ip = _ipaddr.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return '', 403
    except ValueError:
        if hostname in ('localhost', '0.0.0.0', '::1'):
            return '', 403
    # SE-05: Host whitelist — only allow R2 hosts and configured public URL
    from r2_storage import R2_PUBLIC_URL as _r2_pub
    allow_hosts = set()
    if _r2_pub:
        try:
            allow_hosts.add(_urlparse(_r2_pub).netloc.lower())
        except Exception:
            pass
    if not (hostname.endswith('.r2.dev') or hostname.endswith('.r2.cloudflarestorage.com') or hostname in allow_hosts):
        return '', 403
    try:
        req_obj = _urllib_req.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with _urllib_req.urlopen(req_obj, timeout=10) as resp:
            data = resp.read()
            content_type = resp.headers.get('Content-Type', 'image/jpeg')
            if not content_type.startswith('image/'):
                return '', 403
        return data, 200, {
            'Content-Type': content_type,
            'Cache-Control': 'public, max-age=3600',
            'Access-Control-Allow-Origin': '*',
        }
    except Exception:
        return '', 502



@app.route('/download-vcard/<int:driver_id>')
def download_vcard(driver_id):
    d = Driver.query.get_or_404(driver_id)
    parts = [d.name or 'Driver']
    if d.vehicle:
        parts.append(d.vehicle.vehicle_no)
    if d.project:
        parts.append(d.project.name)
    if d.district:
        parts.append(d.district.name)
    full_name = ' - '.join(parts)
    lines = ['BEGIN:VCARD', 'VERSION:3.0', f'FN:{full_name}']
    if d.phone1:
        lines.append(f'TEL;TYPE=CELL:{d.phone1}')
    if d.phone2:
        lines.append(f'TEL;TYPE=CELL:{d.phone2}')
    lines.append('END:VCARD')
    vcard_str = '\r\n'.join(lines) + '\r\n'
    safe_name = (d.name or 'driver').replace(' ', '_')
    resp = make_response(vcard_str)
    resp.headers['Content-Type'] = 'text/vcard; charset=utf-8'
    resp.headers['Content-Disposition'] = f'attachment; filename="{safe_name}.vcf"'
    return resp



_BLOB_DIR = os.path.join(tempfile.gettempdir(), 'fleet_blobs')


@app.route('/upload-blob', methods=['POST'])
@csrf.exempt
def upload_blob():
    """Accept a blob file upload, store to temp dir, return a download token.
    Uses filesystem so it works across multiple Gunicorn workers."""
    if not _validate_csrf_exempt_origin():
        return jsonify(error='Cross-origin request blocked'), 403
    import uuid as _uuid, json as _json
    f = request.files.get('file')
    if not f:
        return jsonify(error='No file'), 400
    fname = request.form.get('filename', f.filename or 'download')
    mime = f.content_type or 'application/octet-stream'
    token = str(_uuid.uuid4())
    data_path = os.path.join(_BLOB_DIR, token + '.dat')
    meta_path = os.path.join(_BLOB_DIR, token + '.meta')
    f.save(data_path)
    with open(meta_path, 'w') as mf:
        _json.dump({'filename': fname, 'mime': mime, 'ts': _time_mod.time()}, mf)
    for old in os.listdir(_BLOB_DIR):
        if old.endswith('.meta'):
            mp = os.path.join(_BLOB_DIR, old)
            try:
                with open(mp) as omf:
                    m = _json.load(omf)
                if _time_mod.time() - m.get('ts', 0) > 300:
                    os.remove(mp)
                    dp = mp.replace('.meta', '.dat')
                    if os.path.exists(dp):
                        os.remove(dp)
            except Exception:
                pass
    return jsonify(token=token)



@app.route('/download-blob/<token>')
def download_blob(token):
    """Serve a temporarily stored blob as a downloadable file."""
    import json as _json
    data_path = os.path.join(_BLOB_DIR, token + '.dat')
    meta_path = os.path.join(_BLOB_DIR, token + '.meta')
    if not os.path.exists(data_path) or not os.path.exists(meta_path):
        return 'Expired or not found', 404
    with open(meta_path) as mf:
        meta = _json.load(mf)
    with open(data_path, 'rb') as df:
        data = df.read()
    try:
        os.remove(data_path)
        os.remove(meta_path)
    except Exception:
        pass
    resp = make_response(data)
    resp.headers['Content-Type'] = meta.get('mime', 'application/octet-stream')
    resp.headers['Content-Disposition'] = f'attachment; filename="{meta.get("filename", "download")}"'
    resp.headers['Content-Length'] = len(data)
    resp.headers['Cache-Control'] = 'no-store'
    return resp



def _ensure_user_biometric_version_column():
    """SQLite/PostgreSQL-safe: add user.biometric_token_version if missing."""
    try:
        from sqlalchemy import inspect, text
        insp = inspect(db.engine)
        cols = [c['name'] for c in insp.get_columns('user')]
        if 'biometric_token_version' not in cols:
            tbl = '"user"' if db.engine.dialect.name == 'postgresql' else 'user'
            db.session.execute(text(
                f'ALTER TABLE {tbl} ADD COLUMN biometric_token_version INTEGER NOT NULL DEFAULT 0'
            ))
            db.session.commit()
    except Exception:
        db.session.rollback()



def _biometric_hmac_token(user):
    """HMAC token for biometric login; version bumps invalidate old tokens on disable."""
    import hmac as _hmac, hashlib
    ver = int(getattr(user, 'biometric_token_version', 0) or 0)
    return _hmac.new(
        app.config['SECRET_KEY'].encode('utf-8'),
        f"{user.username}:biometric-v1:{ver}".encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()



def _user_profile_avatar_path(user):
    """Driver photo_path when login username matches driver CNIC (same variants as login)."""
    from utils import user_profile_avatar_path
    return user_profile_avatar_path(user)



@app.route('/account/profile')
def account_profile():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    user = User.query.get_or_404(user_id)
    login_count = LoginLog.query.filter_by(user_id=user.id).count()
    profile_avatar_path = _user_profile_avatar_path(user)
    return render_template(
        'account_profile.html',
        user=user,
        login_count=login_count,
        profile_avatar_path=profile_avatar_path,
    )



@app.route('/auth/biometric-token')
def biometric_token():
    """Return HMAC token for the currently logged-in user (used to enable biometric login)."""
    _ensure_user_biometric_version_column()
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'ok': False}), 401
    user = db.session.get(User, user_id)
    if not user or not user.is_active:
        return jsonify({'ok': False}), 401
    token = _biometric_hmac_token(user)
    display_name = (user.full_name or user.username or '').strip()
    return jsonify({'ok': True, 'token': token, 'username': user.username, 'display_name': display_name})



@app.route('/api/biometric/enable', methods=['POST'])
@csrf.exempt
def api_biometric_enable():
    """Issue biometric token after client-side fingerprint verification (logged-in user)."""
    if not _validate_csrf_exempt_origin():
        return jsonify({'ok': False, 'error': 'Cross-origin request blocked'}), 403
    _ensure_user_biometric_version_column()
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'ok': False, 'error': 'Login required'}), 401
    user = db.session.get(User, user_id)
    if not user or not user.is_active:
        return jsonify({'ok': False, 'error': 'Unauthorized'}), 401
    token = _biometric_hmac_token(user)
    display_name = (user.full_name or user.username or '').strip()
    return jsonify({
        'ok': True,
        'token': token,
        'username': user.username,
        'display_name': display_name,
    })



@app.route('/api/biometric/disable', methods=['POST'])
@csrf.exempt
def api_biometric_disable():
    """Revoke biometric tokens server-side (increment version) and clear device association."""
    if not _validate_csrf_exempt_origin():
        return jsonify({'ok': False, 'error': 'Cross-origin request blocked'}), 403
    _ensure_user_biometric_version_column()
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'ok': False, 'error': 'Login required'}), 401
    user = db.session.get(User, user_id)
    if not user or not user.is_active:
        return jsonify({'ok': False, 'error': 'Unauthorized'}), 401
    try:
        user.biometric_token_version = int(getattr(user, 'biometric_token_version', 0) or 0) + 1
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'ok': False, 'error': 'Server error'}), 500
    return jsonify({'ok': True})



def _safe_mobile_resume_path(path):
    """Relative in-app path only — used after native camera kills the WebView."""
    if not path or not path.startswith('/') or path.startswith('//'):
        return None
    low = path.lower()
    if low.startswith('/login') or low.startswith('/mobile-init'):
        return None
    return path.split('#')[0] or None



def _login_next_path():
    """Current path+query for ?next= after auth redirect (relative only)."""
    path = request.path or '/'
    if request.query_string:
        path = path + '?' + request.query_string.decode('utf-8', errors='ignore')
    return path



def _safe_login_next(target):
    if not target or not str(target).startswith('/') or str(target).startswith('//'):
        return None
    low = str(target).lower()
    if low.startswith('/login') or low.startswith('/mobile-init'):
        return None
    return str(target).split('#')[0] or None



def _is_capacitor_browser():
    ua = (request.headers.get('User-Agent') or '')
    return 'Capacitor' in ua



@app.route('/mobile-init')
def mobile_init():
    """Capacitor cold start / force-close reopen: always log out and show the login screen.
    Never restores a previous screen (e.g. an unfinished Task Report) — after login the user
    always lands on the dashboard. Any stale resume cookie is cleared here."""
    try:
        log_id = session.get('login_log_id')
        if log_id:
            LoginLog.query.filter_by(id=log_id).update({'logout_at': pk_now()})
            db.session.commit()
    except Exception:
        db.session.rollback()
    session.clear()
    resp = make_response(redirect(url_for('login')))
    resp.set_cookie('fleet_resume_path', '', max_age=0, path='/')
    return resp



@app.route('/auth/session-ping', methods=['GET'])
def session_ping():
    """Prime session cookie for Capacitor WebView before first login POST (CSRF needs session)."""
    session.setdefault('_fleet_session_ping', 1)
    session.modified = True
    return ('', 204)



@app.route('/auth/app-logout', methods=['POST'])
@csrf.exempt
def app_logout():
    """Silent AJAX logout for mobile app auto-logout when app goes to background/closes."""
    if not _validate_csrf_exempt_origin():
        return jsonify({'ok': False, 'error': 'Cross-origin request blocked'}), 403
    try:
        log_id = session.get('login_log_id')
        if log_id:
            LoginLog.query.filter_by(id=log_id).update({'logout_at': pk_now()})
            db.session.commit()
    except Exception:
        db.session.rollback()
    session.clear()
    return jsonify({'ok': True})



@app.route('/auth/biometric-login', methods=['POST'])
@csrf.exempt
def biometric_login():
    """Validate biometric token and create a new session (no password needed)."""
    if not _validate_csrf_exempt_origin():
        return jsonify({'ok': False, 'error': 'Cross-origin request blocked'}), 403
    _ensure_user_biometric_version_column()
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    token    = (data.get('token') or '').strip()
    if not username or not token:
        return jsonify({'ok': False, 'error': 'Missing fields'}), 400
    user = User.query.filter_by(username=username, is_active=True).first()
    if not user:
        return jsonify({'ok': False, 'error': 'User not found'}), 401
    if not _biometric_token_valid(user, token):
        return jsonify({'ok': False, 'error': 'Invalid token'}), 401
    _do_login_session(user, request)
    return jsonify({'ok': True, 'redirect': url_for('dashboard')})



def _do_login_session(user, req):
    """Populate Flask session for a successfully authenticated user (shared by password + trusted-device flows)."""
    role_name = (user.role.name if user.role else '').strip()
    is_master  = role_name == 'Master'
    is_admin   = role_name == 'Admin'
    session['user_id']   = user.id
    session['user']      = user.full_name or user.username
    session['is_master'] = is_master
    session['is_admin']  = is_admin
    if is_master:
        perms = [p.code for p in Permission.query.all()]
    else:
        perms = user.permission_codes()
    try:
        from permissions_config import expand_login_permissions
        perms = expand_login_permissions(perms)
    except Exception:
        pass
    session['permissions'] = perms
    session.permanent = True
    # ── Scope: projects / districts / vehicles / shifts ──────────────────
    allowed_projects  = set()
    allowed_districts = set()
    allowed_vehicles  = set()
    allowed_shifts    = set()
    if not (is_master or is_admin):
        uname = (user.username or '').strip()
        cnic_variants = [uname, uname.replace('-', '')]
        try:
            emp = None
            for c in cnic_variants:
                emp = Employee.query.filter(func.lower(Employee.cnic_no) == c.lower()).first()
                if emp:
                    break
            if emp:
                for p in (emp.projects or []):
                    if p and p.id:
                        allowed_projects.add(p.id)
                for d in (emp.districts or []):
                    if d and d.id:
                        allowed_districts.add(d.id)
        except Exception:
            pass
        try:
            drv = None
            for c in cnic_variants:
                drv = Driver.query.filter(func.lower(Driver.cnic_no) == c.lower()).first()
                if drv:
                    break
            if drv:
                if getattr(drv, 'project_id', None):
                    allowed_projects.add(drv.project_id)
                if getattr(drv, 'vehicle_id', None):
                    allowed_vehicles.add(drv.vehicle_id)
                if getattr(drv, 'district_id', None):
                    allowed_districts.add(drv.district_id)
                if (drv.shift or '').strip():
                    allowed_shifts.add((drv.shift or '').strip())
                # Comprehensive enrichment from assigned vehicle
                for _vid in list(allowed_vehicles):
                    _veh = db.session.get(Vehicle, _vid)
                    if not _veh:
                        continue
                    if _veh.district_id:
                        allowed_districts.add(_veh.district_id)
                    if not allowed_projects and _veh.project_id:
                        allowed_projects.add(_veh.project_id)
                    if not allowed_districts:
                        _ps = _veh.parking_station
                        if _ps:
                            if not allowed_projects and _ps.project_id:
                                allowed_projects.add(_ps.project_id)
                            if not allowed_districts and (_ps.district or '').strip():
                                _pd = District.query.filter(
                                    func.lower(District.name) == _ps.district.strip().lower()
                                ).first()
                                if _pd:
                                    allowed_districts.add(_pd.id)
        except Exception:
            pass
    session['allowed_projects']  = list(allowed_projects)
    session['allowed_districts'] = list(allowed_districts)
    session['allowed_vehicles']  = list(allowed_vehicles)
    session['allowed_shifts']    = list(allowed_shifts)
    try:
        log = LoginLog(user_id=user.id,
                       ip_address=(req.remote_addr or '')[:64],
                       user_agent=(req.headers.get('User-Agent') or '')[:500])
        db.session.add(log)
        db.session.commit()
        session['login_log_id'] = log.id
    except Exception:
        db.session.rollback()



@app.route('/set-new-password', methods=['GET', 'POST'])
def set_new_password():
    """First-time password set (after login with 123). User not fully logged in yet."""
    user_id = session.get('must_set_password_user_id')
    if not user_id:
        flash('Invalid session. Please login again.', 'danger')
        return redirect(url_for('login'))
    user = User.query.get_or_404(user_id)
    form = SetNewPasswordForm()
    if form.validate_on_submit():
        if form.new_password.data != form.confirm_password.data:
            flash('Passwords do not match.', 'danger')
            return render_template('set_new_password.html', form=form)
        user.password_hash = generate_password_hash(form.new_password.data)
        user.force_password_change = False
        db.session.commit()
        session.pop('must_set_password_user_id', None)
        flash('Password set successfully. Please login with your new password.', 'success')
        return redirect(url_for('login'))
    return render_template('set_new_password.html', form=form, username=user.username)



@app.route('/account/change-password', methods=['GET', 'POST'])
def account_change_password():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    user = User.query.get_or_404(user_id)
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not check_password(user, form.current_password.data):
            flash('Current password is incorrect.', 'danger')
            return render_template('account_change_password.html', form=form)
        user.password_hash = generate_password_hash(form.new_password.data)
        if getattr(user, 'force_password_change', None):
            user.force_password_change = False
        db.session.commit()
        flash('Password changed successfully. Please login again.', 'success')
        session.pop('user_id', None)
        session.pop('user', None)
        session.pop('permissions', None)
        return redirect(url_for('login'))
    return render_template('account_change_password.html', form=form)


