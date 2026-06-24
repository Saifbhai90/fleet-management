"""
Auth, Users, Roles, Permissions, Form Control, Freeze Settings.

Extracted from routes.py to reduce file size.
"""

from flask import (
    render_template, redirect, url_for, flash, request,
    session, jsonify, make_response, abort, current_app, Response,
)
from app import app, db, csrf
from models import (
    User, Role, Permission, role_permissions, LoginLog, ActivityLog,
    ClientActivityLog, ClientDiagnosticLog, LoginAttempt,
    Employee, EmployeePost, Driver, SystemSetting,
    AttendanceTimeControl, AttendanceTimeOverride, DeviceFCMToken,
    AppRelease,
)
from forms import (
    LoginForm, UserForm, RoleForm, ChangePasswordForm, SetNewPasswordForm,
    AttendanceTimeControlForm, AttendanceTimeOverrideForm,
)
from datetime import datetime, timedelta
from sqlalchemy import func, text
from werkzeug.security import generate_password_hash
from auth_utils import (
    get_required_permission, user_has_permission, user_can_access, check_password,
)
from utils import pk_now, pk_date
from permissions_config import (
    expand_login_permissions, user_has_form_control_tab,
    user_has_any_form_control_tab, FORM_CONTROL_TAB_KEYS,
)
from freeze_utils import (
    get_freeze_config, save_freeze_config, get_freeze_form_catalog,
    is_freeze_protected_request, extract_effective_date, evaluate_freeze,
)
import re
import os
import json

# Import shared helpers from routes.py
from routes import (
    _get_user_scope,
    _sync_user_active_by_cnic,
    _sync_user_full_name_by_cnic,
    _create_user_for_employee_or_driver,
    _persist_client_diagnostic,
    _validate_csrf_exempt_origin,
    _form_control_tab_allowed,
    _any_form_control_tab_allowed,
    _resolve_form_control_settings_tab,
    _form_control_tab_guard,
    require_login,
    _endpoint_description,
    log_activity,
    enforce_data_freeze,
    media_url_filter,
    SimplePagination,
    _administration_nav_back,
    _get_vehicle_family_oil_change_limits,
    _get_vehicle_family_options,
    _multi_word_filter,
    _parse_hhmm_time_optional,
    _save_vehicle_family_oil_change_limits,
)
# Import biometric/mobile helpers from routes_misc.py
from routes_misc import (
    _biometric_hmac_token,
    _ensure_user_biometric_version_column,
    _login_next_path,
    _safe_login_next,
    _is_capacitor_browser,
    _do_login_session,
    _safe_mobile_resume_path,
    _user_profile_avatar_path,
)

from sqlalchemy import delete
from sqlalchemy import insert
from sqlalchemy.orm import joinedload
from sqlalchemy import select
from models import District, Project, Vehicle
from vehicle_sort_utils import vehicle_order_by
from utils import parse_date
@app.route('/login', methods=['GET', 'POST'])
def login():
    from auth_utils import (
        make_trusted_device_token, verify_trusted_device_token,
        TRUSTED_DEVICE_COOKIE, TRUSTED_DEVICE_DAYS
    )
    # GET /login: never wipe an active session (mobile-init clears before redirect here).
    # Auth redirects use ?next= so a still-valid session returns to the intended page.
    if request.method == 'GET':
        _fetch_mode = (request.headers.get('Sec-Fetch-Mode') or '').lower()
        _is_fetch_follow = _fetch_mode in ('cors', 'no-cors', 'same-origin')
        if session.get('user_id') and not _is_fetch_follow:
            _nxt = _safe_login_next(request.args.get('next') or '')
            if _nxt:
                return redirect(_nxt)
            return redirect(url_for('dashboard'))
        session.setdefault('_fleet_login_ready', 1)
        session.modified = True

    form = LoginForm()
    lockout_remaining_seconds = None

    def _login_wants_json():
        if request.method != 'POST':
            return False
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return True
        if request.args.get('ajax') == '1':
            return True
        if request.form.get('_fleet_ajax') == '1':
            return True
        accept = (request.headers.get('Accept') or '').lower()
        return 'application/json' in accept

    def _login_json(**payload):
        return jsonify(payload)

    # Show "no access" message at most once when redirected due to permission failure
    if session.pop('show_no_access', None):
        flash('You do not have access to this page.', 'danger')
    if form.validate_on_submit():
        username = (form.username.data or '').strip()
        # CNIC: normalize digits+hyphens to digits-only; login accept kare 3230409072265 ya 32304-0907226-5 dono
        if username and re.match(r'^[\d\-]+$', username):
            username = re.sub(r'\D', '', username)
        password = (form.password.data or '').strip()

        _lockout_minutes = 15
        _max_failures = 5

        def _compute_lockout_seconds(uname):
            try:
                recent = LoginAttempt.query.filter(
                    LoginAttempt.username == (uname or '').lower(),
                    LoginAttempt.success == False,
                ).order_by(LoginAttempt.created_at.desc()).limit(_max_failures).all()
                if len(recent) < _max_failures:
                    return 0
                oldest_in_top = recent[-1].created_at
                unlock_at = oldest_in_top + timedelta(minutes=_lockout_minutes)
                remaining = int((unlock_at - pk_now()).total_seconds())
                return remaining if remaining > 0 else 0
            except Exception:
                return 0

        try:
            lockout_remaining_seconds = _compute_lockout_seconds(username)
            if lockout_remaining_seconds > 0:
                lock_msg = (
                    f'Account temporarily locked due to {_max_failures} failed attempts. '
                    f'Try again in {max(1, (lockout_remaining_seconds + 59) // 60)} minute(s).'
                )
                if _login_wants_json():
                    return _login_json(
                        ok=False,
                        error=lock_msg,
                        lockout_remaining_seconds=lockout_remaining_seconds,
                    )
                flash(lock_msg, 'danger')
                return render_template(
                    'login.html',
                    form=form,
                    lockout_remaining_seconds=lockout_remaining_seconds
                )
        except Exception:
            pass

        user = User.query.filter(func.lower(User.username) == username.lower()).first()
        # Agar 13 digits mein user na mila to hyphen wala format try karein (DB mein 32304-0907226-5 ho sakta hai)
        if not user and len(username) == 13 and username.isdigit():
            username_formatted = username[:5] + '-' + username[5:12] + '-' + username[12:]
            user = User.query.filter(func.lower(User.username) == username_formatted.lower()).first()
        # CNIC dono format se match (3230409072265 ya 32304-0907226-5) Employee/Driver ke liye
        cnic_variants = [username]
        if len(username) == 13 and username.isdigit():
            cnic_variants.append(username[:5] + '-' + username[5:12] + '-' + username[12:])
        if user and _user_effective_active(user):
            # Auto-fix: agar user ke paas role_id nahi, to Employee/Driver ke post se role assign kar dein
            try:
                role_fixed = False
                if not user.role_id:
                    # 1) Agar user.employee_post_id set hai to uske linked role se bind karein
                    if user.employee_post_id:
                        emp_post = db.session.get(EmployeePost, user.employee_post_id)
                        if emp_post and emp_post.role_id:
                            user.role_id = emp_post.role_id
                            role_fixed = True
                    # 2) Agar employee_post_id nahi, to Employee record (CNIC=username) se post/role lein
                    if not role_fixed:
                        emp = None
                        for c in cnic_variants:
                            emp = Employee.query.filter(func.lower(Employee.cnic_no) == c.lower()).first()
                            if emp:
                                break
                    if emp and emp.post_id:
                        user.employee_post_id = emp.post_id
                        emp_post = db.session.get(EmployeePost, emp.post_id)
                        if emp_post and emp_post.role_id:
                            user.role_id = emp_post.role_id
                            role_fixed = True
                    # 3) Agar phir bhi nahi mila, to Driver record se post (full_name) match karke role lein
                    if not role_fixed:
                        drv = None
                        for c in cnic_variants:
                            drv = Driver.query.filter(func.lower(Driver.cnic_no) == c.lower()).first()
                            if drv:
                                break
                    if drv and drv.post:
                        emp_post = EmployeePost.query.filter(EmployeePost.full_name == (drv.post or '').strip()).first()
                        if emp_post:
                            user.employee_post_id = emp_post.id
                            user.role_id = emp_post.role_id
                            role_fixed = True
                if role_fixed:
                    db.session.commit()
            except Exception:
                db.session.rollback()
            if password == DEFAULT_FIRST_PASSWORD and getattr(user, 'force_password_change', None):
                if check_password(user, DEFAULT_FIRST_PASSWORD):
                    session['must_set_password_user_id'] = user.id
                    if _login_wants_json():
                        return _login_json(
                            ok=True,
                            redirect=url_for('set_new_password'),
                            username=user.username,
                            display_name=(user.full_name or user.username or '').strip(),
                        )
                    return redirect(url_for('set_new_password'))
                # else wrong password
            elif password == DEFAULT_FIRST_PASSWORD and not getattr(user, 'force_password_change', None):
                first_pw_msg = (
                    'Invalid user ID or password. Pehli dafa login ke baad naya password set karein; '
                    'ab 123 kaam nahi karega.'
                )
                if _login_wants_json():
                    return _login_json(ok=False, error=first_pw_msg)
                flash(first_pw_msg, 'danger')
                return redirect(url_for('login'))
            elif check_password(user, password):
                session['user_id'] = user.id
                session['user'] = user.full_name or user.username
                role_name = (user.role.name if user.role else '').strip()
                is_master = bool(role_name == 'Master')
                is_admin = bool(role_name == 'Admin')
                session['is_master'] = is_master
                session['is_admin'] = is_admin
                # Master ke liye role ki value nahi: hamesha saari permissions (DB se sab codes), taake koi cheez miss na ho
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
                session.permanent = True  # Always persistent (30 days); inactivity timer handles web security

                # ── User scope: projects/districts/vehicles/shifts ───────────────────────────────
                allowed_projects = set()
                allowed_districts = set()
                allowed_vehicles = set()
                allowed_shifts = set()
                if not (is_master or is_admin):
                    # Employee assignments (projects/districts) via CNIC
                    try:
                        emp = None
                        for c in cnic_variants:
                            emp = Employee.query.filter(func.lower(Employee.cnic_no) == c.lower()).first()
                            if emp:
                                break
                    except Exception:
                        emp = None
                    if emp:
                        for p in emp.projects:
                            if p and p.id:
                                allowed_projects.add(p.id)
                        for d in emp.districts:
                            if d and d.id:
                                allowed_districts.add(d.id)
                    # Driver assignment (project/vehicle/shift) via CNIC
                    try:
                        drv = None
                        for c in cnic_variants:
                            drv = Driver.query.filter(func.lower(Driver.cnic_no) == c.lower()).first()
                            if drv:
                                break
                    except Exception:
                        drv = None
                    if drv:
                        if getattr(drv, 'project_id', None):
                            allowed_projects.add(drv.project_id)
                        if getattr(drv, 'vehicle_id', None):
                            allowed_vehicles.add(drv.vehicle_id)
                        if getattr(drv, 'district_id', None):
                            allowed_districts.add(drv.district_id)
                        if (drv.shift or '').strip():
                            allowed_shifts.add((drv.shift or '').strip())
                    # Agar kisi bhi cheez ka assignment nahi mila to login block karein
                    if not (allowed_projects or allowed_districts or allowed_vehicles or allowed_shifts):
                        scope_msg = (
                            'Aap ke liye koi Project / District / Vehicle / Shift assign nahi hai. '
                            'Admin se contact karein.'
                        )
                        session.clear()
                        if _login_wants_json():
                            return _login_json(ok=False, error=scope_msg)
                        flash(scope_msg, 'danger')
                        return redirect(url_for('login'))

                session['allowed_projects'] = list(allowed_projects)
                session['allowed_districts'] = list(allowed_districts)
                session['allowed_vehicles'] = list(allowed_vehicles)
                session['allowed_shifts'] = list(allowed_shifts)
                try:
                    login_log = LoginLog(
                        user_id=user.id,
                        ip_address=request.remote_addr,
                        user_agent=(request.headers.get('User-Agent') or '')[:500],
                    )
                    db.session.add(login_log)
                    db.session.add(LoginAttempt(
                        username=username.lower(), ip_address=request.remote_addr,
                        user_agent=(request.headers.get('User-Agent') or '')[:500],
                        success=True,
                    ))
                    db.session.commit()
                    session['login_log_id'] = login_log.id
                except Exception:
                    db.session.rollback()
                # Login ke baad default landing page:
                # 1) Agar dashboard ki access hai (full ya koi bhi card/feature) to Dashboard pe le jao.
                # 2) Agar dashboard nahi hai lekin Attendance hai to Attendance pages pe.
                # 3) Warna bhi fallback Dashboard hi hai (permission check before_request mein ho jayega).
                target_endpoint = None
                codes = set(perms or [])
                # Smart dashboard access check (same as route guard logic)
                has_dashboard_access = (
                    'dashboard' in codes
                    or any(p.startswith('dashboard_card_') for p in codes)
                    or 'view_fleet_map' in codes
                    or 'global_search' in codes
                )
                if has_dashboard_access:
                    target_endpoint = 'dashboard'
                elif 'driver_attendance' in codes:
                    target_endpoint = 'driver_attendance_list'
                elif 'driver_attendance_report' in codes:
                    target_endpoint = 'driver_attendance_report'
                else:
                    target_endpoint = 'dashboard'
                session['play_login_sound'] = 1
                flash(f'Welcome, {session["user"]}!', 'success')
                # Always land on the dashboard (or role landing) after login. We deliberately do NOT
                # restore a previous screen such as an unfinished Task Report. Clear any stale resume cookie.
                resp_target = url_for('dashboard', from_login=1) if target_endpoint == 'dashboard' else url_for(target_endpoint)
                if _login_wants_json():
                    payload = {
                        'ok': True,
                        'redirect': resp_target,
                        'username': user.username,
                        'display_name': (user.full_name or user.username or '').strip(),
                    }
                    if request.form.get('_fleet_bio_link') == '1':
                        _ensure_user_biometric_version_column()
                        payload['token'] = _biometric_hmac_token(user)
                    session.modified = True
                    return _login_json(**payload)
                resp = make_response(redirect(resp_target))
                resp.set_cookie('fleet_resume_path', '', max_age=0, path='/')
                return resp
        try:
            db.session.add(LoginAttempt(
                username=username.lower(), ip_address=request.remote_addr,
                user_agent=(request.headers.get('User-Agent') or '')[:500],
                success=False,
            ))
            db.session.commit()
            lockout_remaining_seconds = _compute_lockout_seconds(username)
            if lockout_remaining_seconds > 0:
                lock_msg = (
                    f'Account temporarily locked due to {_max_failures} failed attempts. '
                    f'Try again in {max(1, (lockout_remaining_seconds + 59) // 60)} minute(s).'
                )
                if _login_wants_json():
                    return _login_json(
                        ok=False,
                        error=lock_msg,
                        lockout_remaining_seconds=lockout_remaining_seconds,
                    )
                flash(lock_msg, 'danger')
                return render_template(
                    'login.html',
                    form=form,
                    lockout_remaining_seconds=lockout_remaining_seconds
                )
        except Exception:
            db.session.rollback()
        if _login_wants_json():
            return _login_json(
                ok=False,
                error='Invalid user ID or password.',
                lockout_remaining_seconds=lockout_remaining_seconds,
            )
        flash('Invalid user ID or password.', 'danger')
    elif request.method == 'POST':
        raw_user = (request.form.get('username') or '').strip()
        if raw_user:
            form.username.data = raw_user
        if form.errors.get('csrf_token'):
            if _login_wants_json():
                return _login_json(ok=False, error='Please tap Sign In again.')
            flash('Please tap Sign In again.', 'warning')
            raw_pass = request.form.get('password') or ''
            if raw_pass:
                form.password.data = raw_pass
    if request.method == 'POST' and _login_wants_json() and not form.validate_on_submit():
        field_errors = []
        for _field, messages in form.errors.items():
            field_errors.extend(messages)
        return _login_json(
            ok=False,
            error=field_errors[0] if field_errors else 'Please check your entries and try again.',
        )
    # Reaching the login screen always discards any pending mobile resume target.
    resp = make_response(render_template('login.html', form=form, lockout_remaining_seconds=lockout_remaining_seconds))
    resp.set_cookie('fleet_resume_path', '', max_age=0, path='/')
    return resp



@app.route('/logout')
def logout():
    from auth_utils import TRUSTED_DEVICE_COOKIE
    inactivity = request.args.get('inactivity') == '1'
    pre_sound = request.args.get('pre_sound') == '1'
    play_logout_sound = 'auto' if inactivity else 'manual'
    # Mark logout time for current session's login log if any
    try:
        log_id = session.get('login_log_id')
        if log_id:
            LoginLog.query.filter_by(id=log_id).update({'logout_at': pk_now()})
            db.session.commit()
    except Exception:
        db.session.rollback()
    session.clear()  # Destroy ALL session data
    if not (play_logout_sound == 'manual' and pre_sound):
        session['play_logout_sound'] = play_logout_sound
    msg = 'Session expired due to inactivity.' if inactivity else 'You have been logged out.'
    flash(msg, 'info' if inactivity else 'info')
    # Add clear_bio=1 parameter to signal login.html to clear biometric localStorage
    response = redirect(url_for('login', clear_bio=1))
    # ALWAYS delete trusted device cookie on logout (mobile + web)
    # Use path='/' to ensure browser properly removes it
    response.delete_cookie(TRUSTED_DEVICE_COOKIE, path='/')
    response.delete_cookie(TRUSTED_DEVICE_COOKIE, path='/', samesite='Lax')
    # Drop any pending mobile resume target so re-login lands on the dashboard.
    response.set_cookie('fleet_resume_path', '', max_age=0, path='/')
    return response



@app.route('/api/log-activity', methods=['POST'])
def api_log_activity():
    """Accept client-side activity log: action, device_id, latitude, longitude, accuracy. User from session."""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'ok': False, 'error': 'Not logged in'}), 401
    data = request.get_json(silent=True) or {}
    action = (data.get('action') or '').strip()[:200] or 'Activity'
    device_id = (data.get('device_id') or '').strip()[:80] or None
    lat = data.get('latitude')
    lng = data.get('longitude')
    accuracy = data.get('accuracy')
    try:
        lat = float(lat) if lat is not None else None
    except (TypeError, ValueError):
        lat = None
    try:
        lng = float(lng) if lng is not None else None
    except (TypeError, ValueError):
        lng = None
    try:
        accuracy = float(accuracy) if accuracy is not None else None
    except (TypeError, ValueError):
        accuracy = None
    ip_address = (request.remote_addr or '')[:64] or None
    try:
        log = ClientActivityLog(
            user_id=user_id,
            device_id=device_id,
            action=action,
            latitude=lat,
            longitude=lng,
            accuracy=accuracy,
            ip_address=ip_address,
        )
        db.session.add(log)
        db.session.commit()
        return jsonify({'ok': True, 'id': log.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500



@app.route('/api/client-diagnostics', methods=['POST'])
@csrf.exempt
def api_client_diagnostics():
    """Batch client-side diagnostics: slow pages, JS errors, offline (per user + device)."""
    if not _validate_csrf_exempt_origin():
        return jsonify({'ok': False, 'error': 'Cross-origin request blocked'}), 403
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'ok': False, 'error': 'Not logged in'}), 401
    data = request.get_json(silent=True) or {}
    events = data.get('events') or []
    if not isinstance(events, list):
        return jsonify({'ok': False, 'error': 'Invalid payload'}), 400
    saved = 0
    ua = (request.headers.get('User-Agent') or '')[:500] or None
    login_log_id = session.get('login_log_id')
    for raw in events[:10]:
        if not isinstance(raw, dict):
            continue
        event_type = (raw.get('event_type') or 'client')[:40]
        try:
            db.session.add(ClientDiagnosticLog(
                user_id=user_id,
                login_log_id=login_log_id,
                device_id=(raw.get('device_id') or '')[:80] or None,
                user_agent=ua,
                event_type=event_type,
                page_path=(raw.get('page_path') or '')[:500] or None,
                message=(raw.get('message') or '')[:2000] or None,
                duration_ms=int(raw['duration_ms']) if raw.get('duration_ms') is not None else None,
                status_code=int(raw['status_code']) if raw.get('status_code') is not None else None,
                device_model=(raw.get('device_model') or '')[:120] or None,
                os_version=(raw.get('os_version') or '')[:80] or None,
                network_type=(raw.get('network_type') or '')[:40] or None,
            ))
            saved += 1
        except (TypeError, ValueError):
            continue
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)[:200]}), 500
    return jsonify({'ok': True, 'saved': saved})



def _current_user_is_master():
    return session.get('is_master', False)



def _is_admin_role_user(user):
    """True if this user's assigned role is the built-in Admin role (name == 'Admin')."""
    return bool(user and user.role and (user.role.name or '').strip() == 'Admin')



def _master_may_post_user_edit(target_user):
    """Master may change only their own account or users who have the Admin role (password, post, etc.)."""
    if not target_user:
        return False
    if target_user.id == session.get('user_id'):
        return True
    return _is_admin_role_user(target_user)



def _role_perm_debug_enabled():
    """Enable verbose role-permission diagnostics via env or request flag."""
    env_on = (os.environ.get('ROLE_PERM_DEBUG') or '').strip().lower() in ('1', 'true', 'yes', 'on')
    req_on = (
        (request.args.get('role_perm_debug') or '').strip() == '1'
        or (request.form.get('role_perm_debug') or '').strip() == '1'
    )
    return bool(env_on or req_on)



def _log_role_perm_debug(stage, role, payload):
    if not _role_perm_debug_enabled():
        return
    try:
        data = {
            'stage': stage,
            'role_id': role.id if role else None,
            'role_name': (role.name if role else None),
            'user_id': session.get('user_id'),
            'is_master': bool(session.get('is_master')),
            'path': request.path,
            'method': request.method,
            'payload': payload or {},
        }
        current_app.logger.warning('ROLE_PERM_DEBUG %s', json.dumps(data, ensure_ascii=True, default=str))
    except Exception:
        pass



def _reconcile_roles_to_admin_cap(admin_role):
    """
    After Admin role permissions change: every other role (except Master) may only keep
    permissions that still exist on the Admin role. Removes permissions Master revoked from Admin
    from Driver / Accountant / … roles everywhere.
    """
    if not admin_role:
        return
    try:
        db.session.refresh(admin_role)
    except Exception:
        pass
    admin_ids = {p.id for p in (admin_role.permissions or [])}
    others = Role.query.filter(Role.name != 'Master').all()
    for r in others:
        if r.id == admin_role.id:
            continue
        keep = [p.id for p in (r.permissions or []) if p.id in admin_ids]
        if set(keep) != {p.id for p in (r.permissions or [])}:
            _replace_role_permissions(r, keep)



def _clamp_role_to_admin_cap(role):
    """Non-master role edits: ensure role never keeps permissions the Admin role no longer has."""
    if not role or role.name in ('Master', 'Admin'):
        return
    admin = Role.query.filter_by(name='Admin').first()
    if not admin:
        return
    try:
        db.session.refresh(admin)
    except Exception:
        pass
    admin_ids = {p.id for p in (admin.permissions or [])}
    keep = [p.id for p in (role.permissions or []) if p.id in admin_ids]
    if set(keep) != {p.id for p in (role.permissions or [])}:
        _replace_role_permissions(role, keep)



def _current_user_assignable_permission_codes():
    """
    Exact permission codes on the current user's role (no section-full expansion).
    Role form / grant caps use this so Admin only sees permissions Master actually assigned.
    """
    if session.get('is_master'):
        return None
    user_id = session.get('user_id')
    if not user_id:
        return set()
    user = db.session.get(User, user_id)
    if not user or not user.role:
        return set()
    return set(user.permission_codes())



def _current_user_effective_permission_codes():
    """Effective permission codes for current user, including section-level expansions."""
    codes = set(session.get('permissions') or [])
    try:
        from permissions_config import expand_login_permissions
        codes = set(expand_login_permissions(list(codes)))
    except Exception:
        pass
    return codes



def _role_effective_permission_codes(role):
    """Effective permission codes for a role, including section-level expansions."""
    if not role:
        return set()
    try:
        codes = set(role.permission_codes())
    except Exception:
        codes = set()
    try:
        from permissions_config import expand_login_permissions
        codes = set(expand_login_permissions(list(codes)))
    except Exception:
        pass
    return codes



def _user_has_full_scope():
    """Master/Admin users ko full access (koi project/district/vehicle/shift filter nahi)."""
    if session.get('is_master'):
        return True
    return bool(session.get('is_admin'))



def _role_name(role):
    return (role.name if role else '').strip()



def _user_can_edit_user(editor_is_master, target_user):
    """Only Master can edit users with role Master or Admin. Others can be edited by Master or Admin."""
    if not target_user or not target_user.role:
        return True
    rname = _role_name(target_user.role)
    if rname in ('Master', 'Admin'):
        return editor_is_master
    return True



DEFAULT_FIRST_PASSWORD = '123'




def _user_effective_active(user):
    """Login ke liye: User.is_active + agar Employee/Driver se link hai to unka status bhi Active hona chahiye."""
    if not user or not user.is_active:
        return False
    username = (user.username or '').strip()
    if len(username) < 5:
        return True
    emp = Employee.query.filter(func.lower(Employee.cnic_no) == username.lower()).first()
    if emp:
        return (emp.status or '').strip() == 'Active'
    driver = Driver.query.filter(func.lower(Driver.cnic_no) == username.lower()).first()
    if driver:
        return (driver.status or '').strip() == 'Active'
    return True



@app.route('/users')
def user_list():
    search = request.args.get('search', '').strip()
    query = User.query
    if search:
        flt = _multi_word_filter(search, User.username, User.full_name)
        if flt is not None:
            query = query.filter(flt)
    users = query.order_by(User.username).all()
    if not _current_user_is_master():
        # Admin login: Master user ki koi information show na ho
        users = [u for u in users if not (u.role and u.role.name == 'Master')]
    users_all = users
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    pagination = SimplePagination(users_all, page, per_page)
    users = pagination.items
    return render_template('user_list.html', users=users, search=search, pagination=pagination, per_page=per_page, **_administration_nav_back())



@app.route('/users/<int:pk>/delete', methods=['POST'])
def user_delete(pk):
    user = User.query.get_or_404(pk)
    is_master = _current_user_is_master()
    if is_master:
        flash('Users delete sirf Admin login kar sakta hai.', 'danger')
        return redirect(url_for('user_list'))
    # Master/Admin users ko kabhi delete na karein yahan se
    if user.role and _role_name(user.role) in ('Master', 'Admin'):
        flash('Master / Admin users delete nahi kiye ja sakte.', 'danger')
        return redirect(url_for('user_list'))
    try:
        # Pehle is user ke saare logs clean karein (FK/NOT NULL issues avoid)
        ActivityLog.query.filter_by(user_id=user.id).delete()
        ClientActivityLog.query.filter_by(user_id=user.id).delete()
        LoginLog.query.filter_by(user_id=user.id).delete()
        db.session.delete(user)
        db.session.commit()
        flash('User deleted successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting user: {str(e)}', 'danger')
    return redirect(url_for('user_list'))



@app.route('/users/sync-from-employees-drivers', methods=['POST'])
def users_sync_from_employees_drivers():
    """Create User for existing Employees and Drivers who have CNIC and no user yet. Returns JSON {created, total}."""
    import json as json_module

    if session.get('is_master'):
        return jsonify({'ok': False, 'error': 'Only Admin can run this sync.'}), 403

    def _candidates():
        out = []
        # Employees: sirf Active wale (Employees Management – sirf Active employees ke users)
        for emp in Employee.query.filter(
            Employee.cnic_no.isnot(None), Employee.cnic_no != '',
            Employee.status == 'Active'
        ).all():
            cnic = (emp.cnic_no or '').strip()
            if len(cnic) < 5:
                continue
            out.append(('employee', emp))
        # Drivers: sirf jinke paas vehicle assign hai aur status Active (Driver Registration – vehicle-assigned only)
        for driver in Driver.query.filter(
            Driver.cnic_no.isnot(None), Driver.cnic_no != '',
            Driver.status == 'Active',
            Driver.vehicle_id.isnot(None)
        ).all():
            cnic = (driver.cnic_no or '').strip()
            if len(cnic) < 5:
                continue
            out.append(('driver', driver))
        return out

    try:
        candidates = _candidates()
        total = len(candidates)
        created = 0
        for kind, rec in candidates:
            if kind == 'employee':
                emp = rec
                cnic = (emp.cnic_no or '').strip()
                post = db.session.get(EmployeePost, emp.post_id) if emp.post_id else None
                role_id = post.role_id if post else None
                u = _create_user_for_employee_or_driver(cnic, emp.name, emp.post_id, role_id)
                if u:
                    created += 1
            else:
                driver = rec
                cnic = (driver.cnic_no or '').strip()
                post_id, role_id = None, None
                if driver.post and (driver.post or '').strip():
                    emp_post = EmployeePost.query.filter(EmployeePost.full_name == (driver.post or '').strip()).first()
                    if emp_post:
                        post_id = emp_post.id
                        role_id = emp_post.role_id
                u = _create_user_for_employee_or_driver(cnic, driver.name, post_id, role_id)
                if u:
                    created += 1
        return jsonify(created=created, total=total)
    except Exception as e:
        db.session.rollback()
        return jsonify(error=str(e)), 500



@app.route('/users/new', methods=['GET', 'POST'])
def user_form():
    form = UserForm()
    is_master = _current_user_is_master()
    if is_master:
        flash('Naye users sirf Admin login bana sakta hai.', 'warning')
        return redirect(url_for('user_list'))
    master_user_form_read_only = False
    posts = EmployeePost.query.order_by(EmployeePost.full_name).all()
    form.employee_post_id.choices = [(0, '-- No Post --')] + [(p.id, p.full_name) for p in posts]

    if request.method == 'GET':
        return render_template('user_form.html', form=form, user=None, allowed_roles_master_only=is_master, master_user_form_read_only=master_user_form_read_only, **_administration_nav_back())
    if form.validate_on_submit():
        employee_post_id = form.employee_post_id.data if form.employee_post_id.data else None
        role_id = None
        if employee_post_id:
            post = db.session.get(EmployeePost, employee_post_id)
            if post and post.role_id:
                role_id = post.role_id
                role = db.session.get(Role, role_id)
                if role and _role_name(role) in ('Master',) and not is_master:
                    flash('Only Master (Developer) can assign Master access.', 'danger')
                    return render_template('user_form.html', form=form, user=None, allowed_roles_master_only=is_master, master_user_form_read_only=master_user_form_read_only, **_administration_nav_back())
                # Delegation rule: non-master can only assign roles whose effective permissions are subset of their own
                if role and not is_master:
                    current_codes = _current_user_effective_permission_codes()
                    role_codes = _role_effective_permission_codes(role)
                    if not role_codes.issubset(current_codes):
                        flash('Aap apne se zyada access assign nahi kar sakte. Pehle apne permissions update karwayen.', 'danger')
                        return render_template('user_form.html', form=form, user=None, allowed_roles_master_only=is_master, master_user_form_read_only=master_user_form_read_only, **_administration_nav_back())
        username = (form.username.data or '').strip()
        if User.query.filter(func.lower(User.username) == username.lower()).first():
            flash('Username already exists.', 'danger')
            return render_template('user_form.html', form=form, user=None, allowed_roles_master_only=is_master, master_user_form_read_only=master_user_form_read_only, **_administration_nav_back())

        password = (form.password.data or '').strip()
        if not password or len(password) < 4:
            flash('Password must be at least 4 characters.', 'danger')
            return render_template('user_form.html', form=form, user=None, allowed_roles_master_only=is_master, master_user_form_read_only=master_user_form_read_only, **_administration_nav_back())
        user = User(
            username=username,
            password_hash=generate_password_hash(password),
            full_name=(form.full_name.data or '').strip() or None,
            role_id=role_id,
            employee_post_id=employee_post_id,
            is_active=form.is_active.data
        )
        db.session.add(user)
        db.session.commit()
        flash('User created successfully.', 'success')
        return redirect(url_for('user_list'))
    return render_template('user_form.html', form=form, user=None, allowed_roles_master_only=is_master, master_user_form_read_only=master_user_form_read_only, **_administration_nav_back())



@app.route('/users/<int:pk>/edit', methods=['GET', 'POST'])
def user_edit(pk):
    user = User.query.get_or_404(pk)
    is_master = _current_user_is_master()

    # Admin ko Master user ki koi info na dikhe – 404
    if not is_master and user.role and user.role.name == 'Master':
        abort(404)
    if not _user_can_edit_user(is_master, user):
        flash('Only Master (Developer) can edit Admin or Master users.', 'danger')
        return redirect(url_for('user_list'))
    form = UserForm()
    posts = EmployeePost.query.order_by(EmployeePost.full_name).all()
    form.employee_post_id.choices = [(0, '-- No Post --')] + [(p.id, p.full_name) for p in posts]
    master_user_form_read_only = bool(is_master and not _master_may_post_user_edit(user))

    if request.method == 'GET':
        form.username.data = user.username
        form.full_name.data = user.full_name
        form.employee_post_id.data = user.employee_post_id or 0
        form.is_active.data = user.is_active
        return render_template(
            'user_form.html',
            form=form,
            user=user,
            allowed_roles_master_only=is_master,
            master_user_form_read_only=master_user_form_read_only,
        **_administration_nav_back(),
    )
    if form.validate_on_submit():
        if is_master and not _master_may_post_user_edit(user):
            flash('Master sirf apna account ya Admin role wale user ki details yahan badal sakta hai.', 'danger')
            return redirect(url_for('user_list'))
        employee_post_id = form.employee_post_id.data if form.employee_post_id.data else None
        role_id = None
        if employee_post_id:
            post = db.session.get(EmployeePost, employee_post_id)
            if post and post.role_id:
                role_id = post.role_id
                role = db.session.get(Role, role_id)
                if role and _role_name(role) in ('Master',) and not is_master:
                    flash('Only Master (Developer) can assign Master access.', 'danger')
                    return render_template(
                        'user_form.html',
                        form=form,
                        user=user,
                        allowed_roles_master_only=is_master,
                        master_user_form_read_only=master_user_form_read_only,
                    **_administration_nav_back(),
    )
                if role and not is_master:
                    current_codes = _current_user_effective_permission_codes()
                    role_codes = _role_effective_permission_codes(role)
                    if not role_codes.issubset(current_codes):
                        flash('Aap apne se zyada access assign nahi kar sakte. Pehle apne permissions update karwayen.', 'danger')
                        return render_template(
                            'user_form.html',
                            form=form,
                            user=user,
                            allowed_roles_master_only=is_master,
                            master_user_form_read_only=master_user_form_read_only,
                        **_administration_nav_back(),
    )
        username = (form.username.data or '').strip()
        other = User.query.filter(func.lower(User.username) == username.lower()).filter(User.id != pk).first()
        if other:
            flash('Username already exists.', 'danger')
            return render_template(
                'user_form.html',
                form=form,
                user=user,
                allowed_roles_master_only=is_master,
                master_user_form_read_only=master_user_form_read_only,
            **_administration_nav_back(),
    )

        user.username = username
        user.full_name = (form.full_name.data or '').strip() or None
        user.role_id = role_id
        user.employee_post_id = employee_post_id
        user.is_active = form.is_active.data

        password = (form.password.data or '').strip()
        reset_flag = bool(form.reset_password.data)
        if password:
            if len(password) < 4:
                flash('Password must be at least 4 characters.', 'danger')
                return render_template(
                    'user_form.html',
                    form=form,
                    user=user,
                    allowed_roles_master_only=is_master,
                    master_user_form_read_only=master_user_form_read_only,
                **_administration_nav_back(),
    )
            user.password_hash = generate_password_hash(password)
            # Manual new password set kiya gaya: first-login flag hata dein
            if getattr(user, 'force_password_change', None):
                user.force_password_change = False
        elif reset_flag:
            # Reset to default first-time password and force change on next login
            user.password_hash = generate_password_hash(DEFAULT_FIRST_PASSWORD)
            user.force_password_change = True
        db.session.commit()
        flash('User updated successfully.', 'success')
        return redirect(url_for('user_list'))
    return render_template(
        'user_form.html',
        form=form,
        user=user,
        allowed_roles_master_only=is_master,
        master_user_form_read_only=master_user_form_read_only,
    **_administration_nav_back(),
    )



@app.route('/roles')
def role_list():
    roles = Role.query.order_by(Role.name).all()
    if not _current_user_is_master():
        # Admin login: Master role show na ho
        roles = [r for r in roles if r.name != 'Master']
    roles_all = roles
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    pagination = SimplePagination(roles_all, page, per_page)
    roles = pagination.items
    return render_template('role_list.html', roles=roles, pagination=pagination, per_page=per_page, **_administration_nav_back())



@app.route('/control', methods=['GET', 'POST'])
def form_control():
    """Attendance time windows: Global + hierarchical overrides (Project / District / Vehicle)."""
    global_form = AttendanceTimeControlForm()
    override_form = AttendanceTimeOverrideForm()

    projects = Project.query.order_by(Project.name).all()
    districts = District.query.order_by(District.name).all()
    vehicles = Vehicle.query.order_by(*vehicle_order_by()).all()
    override_form.project_id.choices = [(0, '-- Select Project --')] + [(p.id, p.name) for p in projects]
    override_form.district_id.choices = [(0, '-- Select District --')] + [(d.id, d.name) for d in districts]
    override_form.vehicle_id.choices = [(0, '-- Select Vehicle --')] + [(v.id, f"{v.vehicle_no} ({v.vehicle_type or ''})") for v in vehicles]

    glob = AttendanceTimeOverride.query.filter_by(scope='global').first()
    if not glob:
        old = AttendanceTimeControl.query.first()
        if old:
            glob = AttendanceTimeOverride(scope='global',
                morning_start=old.morning_start, morning_end=old.morning_end,
                night_start=old.night_start, night_end=old.night_end)
            db.session.add(glob)
            db.session.commit()

    overrides = AttendanceTimeOverride.query.filter(AttendanceTimeOverride.scope != 'global')\
        .order_by(AttendanceTimeOverride.scope, AttendanceTimeOverride.updated_at.desc()).all()

    from models import AttendanceSettings
    att_settings = AttendanceSettings.query.first()
    freeze_cfg = get_freeze_config()
    freeze_forms = get_freeze_form_catalog()
    freeze_allowed_set = set(freeze_cfg.get('allowed_set') or set())
    def _build_freeze_matrix_rows(forms_catalog, allowed_set):
        rows_map = {}
        for form_label, endpoint_code in (forms_catalog or []):
            lbl = (form_label or '').strip()
            ep = (endpoint_code or '').strip()
            lower = lbl.lower()
            op = None
            base_label = lbl
            if lower.endswith(' add'):
                op = 'add'
                base_label = lbl[:-4].strip()
            elif lower.endswith(' edit'):
                op = 'edit'
                base_label = lbl[:-5].strip()
            elif lower.endswith(' delete'):
                op = 'delete'
                base_label = lbl[:-7].strip()
            row = rows_map.setdefault(base_label, {
                'label': base_label,
                'add': None,
                'edit': None,
                'delete': None,
                'other': [],
            })
            cell = {
                'endpoint': ep,
                'applied': ep not in allowed_set,  # tick = freeze apply
            }
            if op in ('add', 'edit', 'delete'):
                row[op] = cell
            else:
                row['other'].append({
                    'label': lbl,
                    'endpoint': ep,
                    'applied': ep not in allowed_set,
                })
        return sorted(rows_map.values(), key=lambda x: x['label'].lower())
    freeze_matrix_rows = _build_freeze_matrix_rows(freeze_forms, freeze_allowed_set)
    oil_family_options = _get_vehicle_family_options()
    oil_change_limits = _get_vehicle_family_oil_change_limits()
    from fuel_expense_settings import fuel_expense_settings_payload, get_fuel_km_gap_rules
    fuel_expense_cfg = get_fuel_km_gap_rules()
    fuel_expense_settings = fuel_expense_settings_payload()

    requested_tab = request.args.get('settings_tab', 'attendance')
    active_tab = _resolve_form_control_settings_tab(requested_tab)
    if not active_tab:
        flash('You do not have permission to access Settings.', 'danger')
        return redirect(url_for('user_list'))
    fc_tab_allowed = {k: _form_control_tab_allowed(k) for k in (
        'attendance', 'freeze', 'oil_limits', 'daily_task_entry', 'vehicle_sort', 'accounting_maintenance', 'fuel_expense',
    )}
    vehicle_sort_project_id = request.args.get('project_id', type=int) or (
        projects[0].id if projects else None
    )
    vehicle_sort_rows = []
    if vehicle_sort_project_id:
        vehicle_sort_rows = (
            Vehicle.query.options(joinedload(Vehicle.district))
            .filter_by(project_id=vehicle_sort_project_id)
            .order_by(*vehicle_order_by())
            .all()
        )

    if request.method == 'GET':
        if glob:
            global_form.morning_start.data = glob.morning_start.strftime('%H:%M') if glob.morning_start else ''
            global_form.morning_end.data = glob.morning_end.strftime('%H:%M') if glob.morning_end else ''
            global_form.night_start.data = glob.night_start.strftime('%H:%M') if glob.night_start else ''
            global_form.night_end.data = glob.night_end.strftime('%H:%M') if glob.night_end else ''
        return render_template(
            'control_form.html',
            global_form=global_form,
            override_form=override_form,
            overrides=overrides,
            global_override=glob,
            att_settings=att_settings,
            projects=projects,
            districts=districts,
            vehicle_sort_project_id=vehicle_sort_project_id,
            vehicle_sort_rows=vehicle_sort_rows,
            freeze_cfg=freeze_cfg,
            freeze_forms=freeze_forms,
            freeze_matrix_rows=freeze_matrix_rows,
            freeze_allowed_set=freeze_allowed_set,
            oil_family_options=oil_family_options,
            oil_change_limits=oil_change_limits,
            fuel_expense_cfg=fuel_expense_cfg,
            fuel_expense_settings=fuel_expense_settings,
            settings_active_tab=active_tab,
            fc_tab_allowed=fc_tab_allowed,
        **_administration_nav_back(),
    )

    action = request.form.get('action', '')
    def parse_time(s):
        if not s or not str(s).strip():
            return None
        try:
            return datetime.strptime(str(s).strip()[:5], '%H:%M').time()
        except ValueError:
            return None

    if action == 'run_transfer_mirror_backfill':
        denied = _form_control_tab_guard('accounting_maintenance', 'You do not have permission to run accounting maintenance.')
        if denied:
            return denied
        try:
            from routes_finance import _backfill_workspace_company_funding_mirrors
            created = int(_backfill_workspace_company_funding_mirrors() or 0)
            db.session.commit()
            flash(f'Fund transfer mirror backfill completed. Workspace journal(s) created: {created}.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Fund transfer mirror backfill failed: {e}', 'danger')
        return redirect(url_for('form_control', settings_tab='accounting_maintenance'))

    if action == 'run_opening_entries_backfill':
        denied = _form_control_tab_guard('accounting_maintenance', 'You do not have permission to run accounting maintenance.')
        if denied:
            return denied
        try:
            from finance_utils import reconcile_workspace_opening_expense_postings
            updated_total = 0
            failed = 0
            employees = Employee.query.order_by(Employee.id.asc()).all()
            for emp in employees:
                try:
                    updated_total += int(reconcile_workspace_opening_expense_postings(emp.id) or 0)
                except Exception:
                    failed += 1
            db.session.commit()
            msg = f'Opening entries maintenance completed. Updated posting(s): {updated_total}.'
            if failed:
                msg += f' Failed employee workspace(s): {failed}.'
            flash(msg, 'success' if not failed else 'warning')
        except Exception as e:
            db.session.rollback()
            flash(f'Opening entries maintenance failed: {e}', 'danger')
        return redirect(url_for('form_control', settings_tab='accounting_maintenance'))

    if action == 'save_global':
        denied = _form_control_tab_guard('attendance')
        if denied:
            return denied
        if not glob:
            glob = AttendanceTimeOverride(scope='global')
            db.session.add(glob)
        glob.morning_start = parse_time(global_form.morning_start.data)
        glob.morning_end = parse_time(global_form.morning_end.data)
        glob.night_start = parse_time(global_form.night_start.data)
        glob.night_end = parse_time(global_form.night_end.data)
        glob.morning_checkout_start = parse_time(request.form.get('morning_checkout_start'))
        glob.morning_checkout_end = parse_time(request.form.get('morning_checkout_end'))
        glob.night_checkout_start = parse_time(request.form.get('night_checkout_start'))
        glob.night_checkout_end = parse_time(request.form.get('night_checkout_end'))
        db.session.commit()
        flash('Global default time saved.', 'success')
        return redirect(url_for('form_control'))

    if action == 'save_checkout_settings':
        denied = _form_control_tab_guard('attendance')
        if denied:
            return denied
        if not glob:
            glob = AttendanceTimeOverride(scope='global')
            db.session.add(glob)
        glob.allow_future_checkout = bool(request.form.get('allow_future_checkout'))
        glob.auto_gps_checkout_on_window_end = bool(request.form.get('auto_gps_checkout_on_window_end'))
        db.session.commit()
        flash('Manual check-out setting saved.', 'success')
        return redirect(url_for('form_control'))

    if action == 'save_gps_checkin_settings':
        denied = _form_control_tab_guard('attendance')
        if denied:
            return denied
        if not glob:
            glob = AttendanceTimeOverride(scope='global')
            db.session.add(glob)
        glob.allow_morning_driver_night_gps_checkin = bool(
            request.form.get('allow_morning_driver_night_gps_checkin')
        )
        glob.allow_night_driver_morning_gps_checkin = bool(
            request.form.get('allow_night_driver_morning_gps_checkin')
        )
        mode_raw = (request.form.get('capacity_one_checkin_mode') or 'both').strip().lower()
        if mode_raw not in ('both', 'morning_only', 'night_only'):
            mode_raw = 'both'
        glob.capacity_one_checkin_mode = mode_raw
        db.session.commit()
        flash('GPS check-in setting saved.', 'success')
        return redirect(url_for('form_control'))

    if action == 'save_geofence':
        denied = _form_control_tab_guard('attendance')
        if denied:
            return denied
        from models import AttendanceSettings
        att_s = AttendanceSettings.query.first()
        if not att_s:
            att_s = AttendanceSettings()
            db.session.add(att_s)
        att_s.geofence_radius_meters = int(request.form.get('geofence_radius', 150) or 150)
        att_s.geofence_enabled = bool(request.form.get('geofence_enabled'))
        att_s.checkin_reminder_minutes = int(request.form.get('checkin_reminder_minutes', 20) or 20)
        att_s.checkout_reminder_minutes = int(request.form.get('checkout_reminder_minutes', 30) or 30)
        att_s.notify_on_attendance_mark = bool(request.form.get('notify_on_mark'))
        db.session.commit()
        flash('Geofence & Notification settings saved.', 'success')
        return redirect(url_for('form_control'))

    if action == 'save_daily_task_entry_settings':
        denied = _form_control_tab_guard('daily_task_entry')
        if denied:
            return denied
        att_s = AttendanceSettings.query.first()
        if not att_s:
            att_s = AttendanceSettings()
            db.session.add(att_s)
        raw_max = (request.form.get('daily_task_entry_max_kms_driven') or '').strip()
        if not raw_max:
            att_s.daily_task_entry_max_kms_driven = None
        else:
            try:
                mx = int(float(raw_max))
                att_s.daily_task_entry_max_kms_driven = mx if mx > 0 else None
            except (TypeError, ValueError):
                flash('Max KM invalid — number likhein ya khali chhor dein.', 'warning')
                return redirect(url_for('form_control', settings_tab='daily_task_entry'))
        att_s.daily_task_odometer_photo_required = bool(request.form.get('daily_task_odometer_photo_required'))
        invalid_projects = []
        for p in Project.query.all():
            raw = (request.form.get(f'task_entry_yesterday_until_{p.id}') or '').strip()
            if raw and _parse_hhmm_time_optional(raw) is None:
                invalid_projects.append(p.name)
                continue
            p.task_entry_yesterday_default_until = _parse_hhmm_time_optional(raw)
        if invalid_projects:
            flash(
                'Invalid time (HH:MM) for: ' + ', '.join(invalid_projects[:8])
                + ('…' if len(invalid_projects) > 8 else ''),
                'warning',
            )
            return redirect(url_for('form_control', settings_tab='daily_task_entry'))
        db.session.commit()
        flash('New Task Entry settings saved.', 'success')
        return redirect(url_for('form_control', settings_tab='daily_task_entry'))

    if action == 'save_vehicle_sort_order':
        denied = _form_control_tab_guard('vehicle_sort')
        if denied:
            return denied
        project_id = request.form.get('project_id', type=int)
        if not project_id:
            flash('Project select karein.', 'warning')
            return redirect(url_for('form_control', settings_tab='vehicle_sort'))
        raw_ids = request.form.getlist('vehicle_sort_ids[]')
        if not raw_ids:
            raw_ids = [x.strip() for x in (request.form.get('vehicle_sort_ids') or '').split(',') if x.strip()]
        seen = set()
        ordered_ids = []
        for vid_s in raw_ids:
            try:
                vid = int(vid_s)
            except (TypeError, ValueError):
                continue
            if vid in seen:
                continue
            seen.add(vid)
            ordered_ids.append(vid)
        project_vehicles = {
            v.id: v
            for v in Vehicle.query.filter_by(project_id=project_id).all()
        }
        for idx, vid in enumerate(ordered_ids, start=1):
            v = project_vehicles.get(vid)
            if v:
                v.project_sort_order = idx * 10
        for vid, v in project_vehicles.items():
            if vid not in seen:
                v.project_sort_order = None
        db.session.commit()
        flash('Vehicle sort order saved.', 'success')
        return redirect(url_for('form_control', settings_tab='vehicle_sort', project_id=project_id))

    if action == 'save_oil_change_limits':
        denied = _form_control_tab_guard('oil_limits')
        if denied:
            return denied
        posted_families = request.form.getlist('oil_family')
        posted_limits = request.form.getlist('oil_limit_value')
        posted_near = request.form.getlist('oil_near_percent_value')
        limits_payload = {}
        for idx, fam in enumerate(posted_families):
            fam_name = (fam or '').strip()
            if not fam_name:
                continue
            raw = posted_limits[idx] if idx < len(posted_limits) else ''
            raw_val = (raw or '').strip()
            if not raw_val:
                continue
            try:
                km_limit = int(float(raw_val))
            except Exception:
                continue
            if km_limit > 0:
                near_raw = posted_near[idx] if idx < len(posted_near) else ''
                limits_payload[fam_name] = {
                    'limit_km': km_limit,
                    'near_percent': near_raw,
                }
        _save_vehicle_family_oil_change_limits(limits_payload)
        flash('Vehicle family oil change limits saved successfully.', 'success')
        return redirect(url_for('form_control', settings_tab='oil_limits'))

    if action == 'save_fuel_expense_settings':
        denied = _form_control_tab_guard('fuel_expense')
        if denied:
            return denied
        from fuel_expense_settings import save_fuel_price_tolerance_rs, save_fuel_km_gap_rules
        save_fuel_price_tolerance_rs(request.form.get('fuel_price_tolerance_rs'))
        default_max = request.form.get('fuel_km_gap_default_max_km')
        posted_districts = request.form.getlist('fuel_km_gap_district_id')
        posted_projects = request.form.getlist('fuel_km_gap_project_id')
        posted_families = request.form.getlist('fuel_km_gap_vehicle_family')
        posted_max_km = request.form.getlist('fuel_km_gap_max_km')
        rules = []
        for idx, d_raw in enumerate(posted_districts):
            rules.append({
                'district_id': d_raw,
                'project_id': posted_projects[idx] if idx < len(posted_projects) else '',
                'vehicle_family': posted_families[idx] if idx < len(posted_families) else '',
                'max_km': posted_max_km[idx] if idx < len(posted_max_km) else '',
            })
        save_fuel_km_gap_rules(default_max, rules)
        flash('Fuel expense settings saved successfully.', 'success')
        return redirect(url_for('form_control', settings_tab='fuel_expense'))

    if action == 'add_override':
        denied = _form_control_tab_guard('attendance')
        if denied:
            return denied
        scope = override_form.scope.data
        proj = override_form.project_id.data if override_form.project_id.data else None
        dist = override_form.district_id.data if override_form.district_id.data else None
        veh = override_form.vehicle_id.data if override_form.vehicle_id.data else None
        if proj == 0: proj = None
        if dist == 0: dist = None
        if veh == 0: veh = None

        if scope == 'project' and not proj:
            flash('Project select karein.', 'danger')
            return redirect(url_for('form_control'))
        if scope == 'district' and (not proj or not dist):
            flash('Project aur District dono select karein.', 'danger')
            return redirect(url_for('form_control'))
        if scope == 'vehicle' and not veh:
            flash('Vehicle select karein.', 'danger')
            return redirect(url_for('form_control'))

        if scope == 'project':
            dist = None; veh = None
        elif scope == 'district':
            veh = None
        elif scope == 'vehicle':
            proj = None; dist = None

        existing = AttendanceTimeOverride.query.filter_by(scope=scope, project_id=proj, district_id=dist, vehicle_id=veh).first()
        if existing:
            flash('Is scope ka override pehle se exist karta hai. Us ko edit karein ya delete kar ke naya banayein.', 'warning')
            return redirect(url_for('form_control'))

        ov = AttendanceTimeOverride(
            scope=scope, project_id=proj, district_id=dist, vehicle_id=veh,
            morning_start=parse_time(request.form.get('morning_start')),
            morning_end=parse_time(request.form.get('morning_end')),
            night_start=parse_time(request.form.get('night_start')),
            night_end=parse_time(request.form.get('night_end')),
            morning_checkout_start=parse_time(request.form.get('morning_checkout_start')),
            morning_checkout_end=parse_time(request.form.get('morning_checkout_end')),
            night_checkout_start=parse_time(request.form.get('night_checkout_start')),
            night_checkout_end=parse_time(request.form.get('night_checkout_end')),
            remarks=override_form.remarks.data,
        )
        db.session.add(ov)
        db.session.commit()
        flash(f'{scope.title()} override added.', 'success')
        return redirect(url_for('form_control'))

    if action == 'save_freeze_data':
        denied = _form_control_tab_guard('freeze', 'You do not have permission to manage freeze settings.')
        if denied:
            return denied

        enabled = bool(request.form.get('freeze_enabled'))
        allow_future_entries = bool(request.form.get('freeze_allow_future_entries'))
        before_date = parse_date(request.form.get('freeze_before_date'))
        after_date = parse_date(request.form.get('freeze_after_date'))
        reason = (request.form.get('freeze_reason') or '').strip()
        selected_apply = set(request.form.getlist('freeze_apply_endpoints'))
        catalog_codes = {ep for _, ep in freeze_forms}
        selected_apply = {ep for ep in selected_apply if ep in catalog_codes}
        selected_allowed = catalog_codes - selected_apply

        if enabled and not (before_date or after_date):
            flash('Enable freeze ke liye Before Date ya After Date me se kam az kam aik date dena zaroori hai.', 'danger')
            return redirect(url_for('form_control', settings_tab='freeze'))

        updated_by = (session.get('user') or '').strip()
        updated_at = pk_now().strftime('%Y-%m-%d %H:%M:%S')
        save_freeze_config(
            enabled=enabled,
            before_date=before_date,
            after_date=after_date,
            allow_future_entries=allow_future_entries,
            reason=reason,
            allowed_endpoints=selected_allowed,
            updated_by=updated_by,
            updated_at=updated_at,
        )
        flash('Freeze Data settings saved successfully.', 'success')
        return redirect(url_for('form_control', settings_tab='freeze'))

    return render_template(
        'control_form.html',
        global_form=global_form,
        override_form=override_form,
        overrides=overrides,
        global_override=glob,
        att_settings=att_settings,
        freeze_cfg=freeze_cfg,
        freeze_forms=freeze_forms,
        freeze_matrix_rows=freeze_matrix_rows,
        freeze_allowed_set=freeze_allowed_set,
        oil_family_options=oil_family_options,
        oil_change_limits=oil_change_limits,
        fuel_expense_cfg=fuel_expense_cfg,
        fuel_expense_settings=fuel_expense_settings,
        projects=projects,
        districts=districts,
        settings_active_tab=active_tab,
        fc_tab_allowed=fc_tab_allowed,
    **_administration_nav_back(),
    )



@app.route('/form-control/override/<int:ov_id>/delete', methods=['POST'])
def form_control_delete_override(ov_id):
    denied = _form_control_tab_guard('attendance')
    if denied:
        return denied
    ov = AttendanceTimeOverride.query.get_or_404(ov_id)
    if ov.scope == 'global':
        flash('Global default delete nahi kar saktay.', 'danger')
        return redirect(url_for('form_control'))
    label = ov.scope_label
    db.session.delete(ov)
    db.session.commit()
    flash(f'Override "{label}" delete ho gaya.', 'success')
    return redirect(url_for('form_control'))



@app.route('/form-control/override/<int:ov_id>/edit', methods=['POST'])
def form_control_edit_override(ov_id):
    denied = _form_control_tab_guard('attendance')
    if denied:
        return denied
    ov = AttendanceTimeOverride.query.get_or_404(ov_id)
    def parse_time(s):
        if not s or not str(s).strip():
            return None
        try:
            return datetime.strptime(str(s).strip()[:5], '%H:%M').time()
        except ValueError:
            return None
    ov.morning_start = parse_time(request.form.get('morning_start'))
    ov.morning_end = parse_time(request.form.get('morning_end'))
    ov.night_start = parse_time(request.form.get('night_start'))
    ov.night_end = parse_time(request.form.get('night_end'))
    ov.morning_checkout_start = parse_time(request.form.get('morning_checkout_start'))
    ov.morning_checkout_end = parse_time(request.form.get('morning_checkout_end'))
    ov.night_checkout_start = parse_time(request.form.get('night_checkout_start'))
    ov.night_checkout_end = parse_time(request.form.get('night_checkout_end'))
    ov.remarks = request.form.get('remarks', '')
    db.session.commit()
    flash(f'Override "{ov.scope_label}" updated.', 'success')
    return redirect(url_for('form_control'))



@app.route('/settings/freeze-data', methods=['GET', 'POST'])
def freeze_data_settings():
    return redirect(url_for('form_control', settings_tab='freeze'))



def _matrix_assignable_permission_ids(permission_matrix):
    """DB ids for permissions shown on the role matrix (checkboxes the editor can toggle)."""
    ids = set()
    for row in permission_matrix or []:
        if not isinstance(row, dict) or row.get('type') != 'page':
            continue
        cells = row.get('cells') or {}
        for key in ('full', 'list', 'add', 'edit', 'delete'):
            cell = cells.get(key)
            if cell and isinstance(cell, dict) and cell.get('id') is not None:
                ids.add(int(cell['id']))
        for cell in cells.get('other') or []:
            if cell and isinstance(cell, dict) and cell.get('id') is not None:
                ids.add(int(cell['id']))
    return ids



def _replace_role_permissions(role, permission_id_list):
    """Replace role_permissions rows via DELETE + INSERT (ORM secondary assign can miss sync in some cases)."""
    rid = role.id
    unique = []
    seen = set()
    for x in permission_id_list or []:
        try:
            i = int(x)
        except (TypeError, ValueError):
            continue
        if i not in seen:
            seen.add(i)
            unique.append(i)
    db.session.execute(delete(role_permissions).where(role_permissions.c.role_id == rid))
    db.session.flush()
    if unique:
        rows = [{'role_id': rid, 'permission_id': pid} for pid in unique]
        db.session.execute(insert(role_permissions), rows)
    db.session.flush()
    try:
        db.session.expire(role, ['permissions'])
        db.session.refresh(role)
    except Exception:
        pass



def _apply_role_permissions_from_form(
    role,
    perm_ids_raw,
    *,
    is_master,
    allowed_permission_ids,
    permission_matrix,
    permission_by_code,
):
    """
    Apply POSTed permission_ids to role (with dependency expansion).

    Master: full replace — unchecked permissions are removed.

    Non-master: merge — keep existing permissions that are NOT on the matrix (editor cannot see
    or change them, e.g. Task & Logbook when editor lacks that section). Replace only matrix-visible
    permissions with the submitted selection + dependencies (capped to allowed_permission_ids).
    """
    from permissions_config import expand_permission_dependencies

    assignable_matrix_ids = _matrix_assignable_permission_ids(permission_matrix)
    perm_ids = [i for i in (perm_ids_raw or []) if i is not None]

    def _codes_from_perm_ids(pid_list):
        if not pid_list:
            return set()
        return {p.code for p in Permission.query.filter(Permission.id.in_(pid_list)).all()}

    if is_master:
        codes = _codes_from_perm_ids(perm_ids)
        expanded = expand_permission_dependencies(codes)
        new_ids = [permission_by_code[c].id for c in expanded if permission_by_code.get(c)]
        _replace_role_permissions(role, new_ids)
        try:
            db.session.refresh(role)
        except Exception:
            pass
        return

    allowed_ids = allowed_permission_ids or set()
    submitted_ids = set(perm_ids)
    blocked_ids = submitted_ids - allowed_ids
    if blocked_ids:
        blocked_names = [p.name for p in Permission.query.filter(Permission.id.in_(blocked_ids)).all()]
        flash(
            f'Security: {len(blocked_ids)} permission(s) blocked — you cannot grant access you do not have: {", ".join(blocked_names[:5])}.',
            'warning',
        )
    submitted_allowed = submitted_ids & allowed_ids
    codes = _codes_from_perm_ids(list(submitted_allowed))
    expanded = expand_permission_dependencies(codes)
    managed_ids = {
        permission_by_code[c].id
        for c in expanded
        if permission_by_code.get(c) and permission_by_code[c].id in allowed_ids
    }
    managed_objs = Permission.query.filter(Permission.id.in_(managed_ids)).all() if managed_ids else []

    # Normal: preserve only DB rows not shown on the matrix (editor cannot toggle them).
    # If the matrix failed to build (empty assignable) but we still know what the editor may grant,
    # preserve only permissions outside that set — otherwise "preserve all on matrix" blocks removals.
    if assignable_matrix_ids:
        preserved = [p for p in role.permissions if p.id not in assignable_matrix_ids]
    elif allowed_permission_ids is not None and allowed_ids:
        preserved = [p for p in role.permissions if p.id not in allowed_ids]
    else:
        preserved = [p for p in role.permissions if p.id not in assignable_matrix_ids]
    by_id = {p.id: p for p in preserved}
    for p in managed_objs:
        by_id[p.id] = p

    _replace_role_permissions(role, list(by_id.keys()))



@app.route('/roles/new', methods=['GET', 'POST'])
def role_form():
    form = RoleForm()
    posts = EmployeePost.query.order_by(EmployeePost.full_name).all()
    form.post_id.choices = [(0, '-- Select Post (searchable) --')] + [(p.id, p.full_name) for p in posts]
    # Current user sirf apne paas wale permissions hi kisi role ko de sakta hai (exact DB grants, no section-full expansion)
    is_master = _current_user_is_master()
    assignable_codes = _current_user_assignable_permission_codes()
    from auth_utils import ensure_config_permissions_exist
    from permissions_config import (
        get_permission_tree_grouped_filtered,
        PERMISSION_DEPENDENCIES,
        build_permission_matrix_rows,
    )
    ensure_config_permissions_exist()
    permission_by_code = {p.code: p for p in Permission.query.all()}
    codes_for_allowed = list(assignable_codes or [])
    allowed_permission_ids = None if is_master else {
        p.id for p in Permission.query.filter(Permission.code.in_(codes_for_allowed)).all()
    }
    try:
        permission_tree = get_permission_tree_grouped_filtered(
            permission_by_code, allowed_codes=assignable_codes
        )
        permission_matrix = build_permission_matrix_rows(permission_tree)
    except Exception:
        current_app.logger.exception('role_form: permission tree/matrix build failed')
        permission_tree = []
        permission_matrix = []
    master_role_matrix_read_only = bool(is_master)
    if request.method == 'GET':
        return render_template(
            'role_form.html',
            form=form,
            role=None,
            permission_tree=permission_tree,
            permission_matrix=permission_matrix,
            permission_dependencies=PERMISSION_DEPENDENCIES,
            master_role_matrix_read_only=master_role_matrix_read_only,
        **_administration_nav_back(),
    )
    if form.validate_on_submit():
        if is_master:
            flash('Naye roles sirf Admin login bana sakta hai. Master sirf Admin role ki permissions change kar sakta hai.', 'warning')
            return redirect(url_for('role_list'))
        post_id = form.post_id.data if form.post_id.data else 0
        if post_id == 0:
            flash('Please select a Post from Employee Posts.', 'danger')
            return render_template(
                'role_form.html',
                form=form,
                role=None,
                permission_tree=permission_tree,
                permission_matrix=permission_matrix,
                permission_dependencies=PERMISSION_DEPENDENCIES,
                master_role_matrix_read_only=master_role_matrix_read_only,
            **_administration_nav_back(),
    )
        post = db.session.get(EmployeePost, post_id)
        if not post:
            flash('Selected post not found.', 'danger')
            return render_template(
                'role_form.html',
                form=form,
                role=None,
                permission_tree=permission_tree,
                permission_matrix=permission_matrix,
                permission_dependencies=PERMISSION_DEPENDENCIES,
                master_role_matrix_read_only=master_role_matrix_read_only,
            **_administration_nav_back(),
    )
        name = (post.full_name or '').strip()
        if not name:
            flash('Post has no name.', 'danger')
            return render_template(
                'role_form.html',
                form=form,
                role=None,
                permission_tree=permission_tree,
                permission_matrix=permission_matrix,
                permission_dependencies=PERMISSION_DEPENDENCIES,
                master_role_matrix_read_only=master_role_matrix_read_only,
            **_administration_nav_back(),
    )
        if Role.query.filter(func.lower(Role.name) == name.lower()).first():
            flash('A role with this post name already exists. Select another post or edit the existing role.', 'danger')
            return render_template(
                'role_form.html',
                form=form,
                role=None,
                permission_tree=permission_tree,
                permission_matrix=permission_matrix,
                permission_dependencies=PERMISSION_DEPENDENCIES,
                master_role_matrix_read_only=master_role_matrix_read_only,
            **_administration_nav_back(),
    )
        role = Role(name=name, description=(form.description.data or '').strip() or None)
        db.session.add(role)
        db.session.commit()
        # Agar koi Employee Post select ki gayi thi to usko is naye Role se link karein
        if post_id:
            emp_post = db.session.get(EmployeePost, post_id)
            if emp_post:
                emp_post.role_id = role.id
                db.session.commit()
        perm_ids_raw = request.form.getlist('permission_ids', type=int)
        _apply_role_permissions_from_form(
            role,
            perm_ids_raw,
            is_master=is_master,
            allowed_permission_ids=allowed_permission_ids,
            permission_matrix=permission_matrix,
            permission_by_code=permission_by_code,
        )
        _clamp_role_to_admin_cap(role)
        db.session.commit()
        flash('Role created successfully and linked to selected Post.', 'success')
        return redirect(url_for('role_list'))
    return render_template(
                'role_form.html',
                form=form,
                role=None,
                permission_tree=permission_tree,
                permission_matrix=permission_matrix,
                permission_dependencies=PERMISSION_DEPENDENCIES,
                master_role_matrix_read_only=master_role_matrix_read_only,
            **_administration_nav_back(),
    )



@app.route('/roles/<int:pk>/edit', methods=['GET', 'POST'])
def role_edit(pk):
    role = Role.query.get_or_404(pk)
    is_master = _current_user_is_master()
    # Admin ko Master role ki koi info na dikhe – 404
    if not is_master and role.name == 'Master':
        abort(404)
    # Admin apni (Admin) role edit na kar sake – sirf Master change kar sakta hai; yahan lock dikhayenge, URL se bhi 404
    if not is_master and role.name == 'Admin':
        abort(404)
    # Current user sirf apne paas wale permissions hi is role ko assign kar sakta hai (exact DB grants, no section-full expansion)
    assignable_codes = _current_user_assignable_permission_codes()
    from auth_utils import ensure_config_permissions_exist
    from permissions_config import (
        get_permission_tree_grouped_filtered,
        PERMISSION_DEPENDENCIES,
        build_permission_matrix_rows,
    )
    ensure_config_permissions_exist()
    permission_by_code = {p.code: p for p in Permission.query.all()}
    codes_for_allowed = list(assignable_codes or [])
    allowed_permission_ids = None if is_master else {
        p.id for p in Permission.query.filter(Permission.code.in_(codes_for_allowed)).all()
    }
    try:
        permission_tree = get_permission_tree_grouped_filtered(
            permission_by_code, allowed_codes=assignable_codes
        )
        permission_matrix = build_permission_matrix_rows(permission_tree)
    except Exception:
        current_app.logger.exception('role_edit: permission tree/matrix build failed')
        permission_tree = []
        permission_matrix = []
    form = RoleForm()
    form.post_id.choices = [(0, '—')]
    master_role_matrix_read_only = bool(is_master and role.name != 'Admin')
    if request.method == 'GET':
        if is_master and (role.name or '').strip() == 'Admin':
            db_ids_get = set(
                r[0]
                for r in db.session.execute(
                    select(role_permissions.c.permission_id).where(role_permissions.c.role_id == role.id)
                ).all()
            )
            orm_ids_get = {p.id for p in (role.permissions or [])}
            _log_role_perm_debug(
                'role_edit_get_admin',
                role,
                {
                    'db_ids_count': len(db_ids_get),
                    'orm_ids_count': len(orm_ids_get),
                    'only_in_db': sorted(list(db_ids_get - orm_ids_get))[:50],
                    'only_in_orm': sorted(list(orm_ids_get - db_ids_get))[:50],
                },
            )
        # Edit mode: Role name/description sirf read-only dikhaani hain (change ki ijazat nahi)
        resp = make_response(render_template(
            'role_form.html',
            form=form,
            role=role,
            permission_tree=permission_tree,
            permission_matrix=permission_matrix,
            permission_dependencies=PERMISSION_DEPENDENCIES,
            master_role_matrix_read_only=master_role_matrix_read_only,
        **_administration_nav_back(),
    ))
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        return resp
    if form.validate_on_submit():
        role_name = (role.name or '').strip()
        if is_master and role_name != 'Admin':
            flash('Master sirf Admin role ki permissions change kar sakta hai. Baqi roles par sirf dekh sakta hai.', 'danger')
            return redirect(url_for('role_list'))
        # Role Details (name/description) ko edit ki permission nahi – sirf permissions update honge
        perm_ids_raw = request.form.getlist('permission_ids', type=int)
        if is_master and role_name == 'Admin':
            # Master -> Admin path: apply deterministic full replace and verify persisted rows.
            from permissions_config import PERMISSION_DEPENDENCIES
            raw_perm_ids = request.form.getlist('permission_ids')
            before_codes = {p.code for p in (role.permissions or [])}
            selected_ids = []
            seen = set()
            for x in perm_ids_raw or []:
                if x is None:
                    continue
                try:
                    i = int(x)
                except (TypeError, ValueError):
                    continue
                if i not in seen:
                    seen.add(i)
                    selected_ids.append(i)
            selected_codes = {
                p.code for p in Permission.query.filter(Permission.id.in_(selected_ids)).all()
            } if selected_ids else set()
            # Keep explicit unticks authoritative:
            # instead of auto-adding missing dependencies, drop dependents whose requirements
            # are not selected (downward closure).
            constrained_codes = set(selected_codes)
            dropped_codes = set()
            changed = True
            while changed:
                changed = False
                for code in list(constrained_codes):
                    reqs = set(PERMISSION_DEPENDENCIES.get(code, []))
                    if reqs and not reqs.issubset(constrained_codes):
                        constrained_codes.remove(code)
                        dropped_codes.add(code)
                        changed = True
            intended_ids = [
                permission_by_code[c].id for c in constrained_codes if permission_by_code.get(c)
            ]
            _log_role_perm_debug(
                'role_edit_post_admin_before_apply',
                role,
                {
                    'template_version': (request.form.get('role_form_template_version') or ''),
                    'submit_marker': (request.form.get('role_form_submit_marker') or ''),
                    'raw_perm_ids_count': len(raw_perm_ids),
                    'raw_perm_ids_head': raw_perm_ids[:40],
                    'before_codes_count': len(before_codes),
                    'parsed_perm_ids_count': len(selected_ids),
                    'selected_codes_count': len(selected_codes),
                    'added_codes_count': len(selected_codes - before_codes),
                    'removed_codes_count': len(before_codes - selected_codes),
                    'added_codes_head': sorted(list(selected_codes - before_codes))[:30],
                    'removed_codes_head': sorted(list(before_codes - selected_codes))[:30],
                    'selected_has_whats_new': ('whats_new' in selected_codes),
                    'selected_has_dashboard_card_drivers': ('dashboard_card_drivers' in selected_codes),
                    'constrained_codes_count': len(constrained_codes),
                    'dropped_codes_count': len(dropped_codes),
                    'dropped_codes_head': sorted(list(dropped_codes))[:40],
                    'intended_ids_count': len(intended_ids),
                    'intended_ids_head': sorted(list(set(intended_ids)))[:60],
                },
            )
            if dropped_codes:
                flash(
                    f"{len(dropped_codes)} dependent permission(s) were removed because their required base permission was unchecked.",
                    'warning',
                )
            _replace_role_permissions(role, intended_ids)
            _reconcile_roles_to_admin_cap(role)
            db.session.commit()
            persisted_ids = set(
                r[0]
                for r in db.session.execute(
                    select(role_permissions.c.permission_id).where(role_permissions.c.role_id == role.id)
                ).all()
            )
            intended_set = set(intended_ids)
            if persisted_ids != intended_set:
                # Safety net: if any race/ORM edge appears, force one more exact sync.
                _replace_role_permissions(role, list(intended_set))
                _reconcile_roles_to_admin_cap(role)
                db.session.commit()
                persisted_ids = set(
                    r[0]
                    for r in db.session.execute(
                        select(role_permissions.c.permission_id).where(role_permissions.c.role_id == role.id)
                    ).all()
                )
            _log_role_perm_debug(
                'role_edit_post_admin_after_commit',
                role,
                {
                    'intended_ids_count': len(intended_set),
                    'persisted_ids_count': len(persisted_ids),
                    'extra_in_db': sorted(list(persisted_ids - intended_set))[:80],
                    'missing_in_db': sorted(list(intended_set - persisted_ids))[:80],
                },
            )
        else:
            _apply_role_permissions_from_form(
                role,
                perm_ids_raw,
                is_master=is_master,
                allowed_permission_ids=allowed_permission_ids,
                permission_matrix=permission_matrix,
                permission_by_code=permission_by_code,
            )
            if not is_master and role.name not in ('Master', 'Admin'):
                _clamp_role_to_admin_cap(role)
            db.session.commit()
        flash('Role updated successfully.', 'success')
        return redirect(url_for('role_list'))
    if request.method == 'POST':
        flash('Role save nahi ho saka — form check karein (CSRF / fields).', 'danger')
    return render_template(
        'role_form.html',
        form=form,
        role=role,
        permission_tree=permission_tree,
        permission_matrix=permission_matrix,
        permission_dependencies=PERMISSION_DEPENDENCIES,
        master_role_matrix_read_only=master_role_matrix_read_only,
    **_administration_nav_back(),
    )



@app.route('/roles/<int:pk>/delete', methods=['POST'])
def role_delete(pk):
    role = Role.query.get_or_404(pk)
    is_master = _current_user_is_master()
    if is_master:
        flash('Roles delete sirf Admin login kar sakta hai.', 'danger')
        return redirect(url_for('role_list'))
    # Master/Admin roles kabhi delete nahi ho sakte
    if role.name in ('Master', 'Admin'):
        flash('Master / Admin role delete nahi kiya ja sakta.', 'danger')
        return redirect(url_for('role_list'))
    # Agar is role ke saath users linked hain to delete block karein
    if role.users:
        flash('Is role ke saath users linked hain. Pehle users ko kisi aur role par shift karein, phir delete karein.', 'danger')
        return redirect(url_for('role_list'))
    try:
        db.session.delete(role)
        db.session.commit()
        flash('Role deleted successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting role: {str(e)}', 'danger')
    return redirect(url_for('role_list'))


