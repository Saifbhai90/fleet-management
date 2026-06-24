"""
Dashboard, Notifications, Reminders, App Updates, Personal Tools, FCM, Mobile APIs.

Extracted from routes.py to reduce file size.
"""

from flask import (
    render_template, redirect, url_for, flash, request,
    session, jsonify, make_response, abort, send_from_directory,
    send_file, Response, current_app, after_this_request,
)
from app import app, db, csrf
from models import (
    User, Role, Permission, Notification, NotificationRead,
    Reminder, AppRelease, DeviceFCMToken, SystemSetting,
    LoginLog, ActivityLog, ClientActivityLog, ClientDiagnosticLog,
    Driver, Vehicle, Project, District, Company, ParkingStation,
    DriverAttendance, VehicleDailyTask, FuelExpense, DriverTransfer,
    MaintenanceExpense, MaintenanceWorkOrder,
    DeviceAppVersion,
)
from forms import (
    NotificationForm, ReminderForm, ChangePasswordForm,
)
from datetime import datetime, date, time, timedelta
from sqlalchemy import func, text, or_, and_
from utils import (
    pk_now, pk_date, pk_time, parse_date,
    format_date_ddmmyyyy, format_time_ampm,
)
from auth_utils import user_can_access, check_password
from vehicle_sort_utils import vehicle_order_by, sort_vehicles_in_memory
import re
import os
import json
import uuid
import tempfile
import mimetypes
import zipfile
import time as _time_mod
import threading
from io import StringIO, BytesIO
import io
from werkzeug.utils import secure_filename
from urllib.request import Request, urlopen

# Import shared helpers from routes.py
from routes import (
    _multi_word_filter,
    media_url_filter,
    _require_master_admin,
    _validate_csrf_exempt_origin,
    _load_pdf_writer_reader,
    _html_to_pdf_bytes,
    _parse_time,
    _time_input_value,
    _get_user_scope,
    require_login,
    _nav_back_ctx,
    _notifications_nav_back,
    _cnic_digits,
    _health_cache,
    SimplePagination,
)
# Import biometric/mobile helpers from routes_misc.py
from routes_misc import (
    _is_capacitor_browser,
    _safe_mobile_resume_path,
    _login_next_path,
    _safe_login_next,
    _do_login_session,
    _biometric_hmac_token,
    _ensure_user_biometric_version_column,
    _user_profile_avatar_path,
)

def _is_parking_full_notification(notification):
    """True if this notification is about parking full (do not show to user)."""
    if not notification:
        return False
    t = ((notification.title or '') + ' ' + (notification.message or '')).lower()
    return 'parking' in t and 'full' in t



def _unread_notifications_for_user(user_id, limit=20):
    """Unread inbox for dashboard dropdown — same rules as bell badge."""
    from notification_service import unread_inbox_for_user

    user_perms = set(session.get('permissions') or [])
    is_master = session.get('is_master', False)
    return unread_inbox_for_user(user_id, user_perms, is_master)[:limit]



import base64
@app.route('/api/v1/me')
def api_me():
    """Mobile API: returns current user identity + full permission list.
    Used by the mobile app to hide/show icons and actions based on strict role hierarchy."""
    if not session.get('user_id'):
        return jsonify({'error': 'Not authenticated', 'authenticated': False}), 401
    is_master = session.get('is_master', False)
    permissions = list(session.get('permissions') or [])
    # Master gets a synthetic 'master' flag so mobile can render superuser UI
    return jsonify({
        'authenticated': True,
        'user_id': session.get('user_id'),
        'username': session.get('user', ''),
        'full_name': session.get('full_name', ''),
        'role': session.get('role', ''),
        'is_master': is_master,
        'permissions': permissions,
        'permission_count': len(permissions),
    })



def _is_valid_apk_on_disk(file_path):
    """Reject corrupt/unsigned-looking APKs (must be ZIP with PK header, reasonable size)."""
    try:
        size = os.path.getsize(file_path)
        if size < 500_000:
            return False
        with open(file_path, 'rb') as fh:
            return fh.read(2) == b'PK'
    except OSError:
        return False



def _parse_apk_version(fname):
    ver = fname.replace('fleet-manager-', '').replace('.apk', '')
    parts = ver.split('.')
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return None
    return tuple(int(p) for p in parts), ver



def _best_signed_apk_from_static():
    apps_dir = os.path.join(app.static_folder, 'apps')
    if not os.path.isdir(apps_dir):
        return None
    best = None
    for fname in os.listdir(apps_dir):
        if not fname.startswith('fleet-manager-') or not fname.endswith('.apk'):
            continue
        parsed = _parse_apk_version(fname)
        if not parsed:
            continue
        path = os.path.join(apps_dir, fname)
        if not _is_valid_apk_on_disk(path):
            continue
        ver_tuple, ver_str = parsed
        row = (ver_tuple, ver_str, fname, os.path.getsize(path))
        if best is None or row[0] > best[0]:
            best = row
    if not best:
        return None
    return {'version': best[1], 'apk_filename': best[2], 'file_size_bytes': best[3]}



@app.route('/api/app/check-update')
def app_check_update():
    """Returns latest app version info — reads from DB (AppRelease)."""
    latest = AppRelease.query.filter_by(is_latest=True).first()
    static_best = _best_signed_apk_from_static()

    if latest:
        disk_path = os.path.join(app.static_folder, 'apps', latest.apk_filename)
        disk_ok = _is_valid_apk_on_disk(disk_path)
        r2_ok = bool(latest.apk_r2_url)
        if not disk_ok and not r2_ok:
            latest = None

    if not latest and static_best:
        try:
            latest = AppRelease(
                version=static_best['version'],
                apk_filename=static_best['apk_filename'],
                force_update=False,
                is_latest=True,
                file_size_bytes=static_best['file_size_bytes'],
            )
            db.session.add(latest)
            db.session.commit()
        except Exception:
            db.session.rollback()
            latest = None

    if not latest:
        return jsonify({
            'latest_version': '0.0.0',
            'apk_url': '',
            'apk_filename': '',
            'force_update': False,
            'file_size_bytes': 0,
        })

    if static_best and _parse_apk_version(latest.apk_filename):
        db_ver = _parse_apk_version(latest.apk_filename)[0]
        if static_best['version'] and _parse_apk_version(static_best['apk_filename'])[0] > db_ver:
            latest.version = static_best['version']
            latest.apk_filename = static_best['apk_filename']
            latest.file_size_bytes = static_best['file_size_bytes']

    apk_path = os.path.join(app.static_folder, 'apps', latest.apk_filename)
    file_size = latest.file_size_bytes or (os.path.getsize(apk_path) if os.path.isfile(apk_path) else 0)

    # Prefer R2 URL (persistent across Render deploys); fallback to local static URL
    if latest.apk_r2_url:
        apk_url = latest.apk_r2_url
    else:
        apk_url = request.url_root.rstrip('/') + url_for('static', filename=f'apps/{latest.apk_filename}')
    return jsonify({
        'latest_version': latest.version,
        'apk_url': apk_url,
        'apk_filename': latest.apk_filename,
        'force_update': latest.force_update,
        'file_size_bytes': file_size,
    })


@app.route('/api/app/report-version', methods=['POST'])
@csrf.exempt
def app_report_version():
    """Receive device app version from mobile app for admin stats."""
    try:
        data = request.get_json(silent=True) or {}
        version = (data.get('version') or '').strip()
        if not version:
            return jsonify({'ok': False}), 400
        uid = session.get('user_id')
        if not uid:
            return jsonify({'ok': False}), 401
        existing = DeviceAppVersion.query.filter_by(user_id=uid).first()
        if existing:
            existing.app_version = version
            existing.last_seen = pk_now()
        else:
            dv = DeviceAppVersion(user_id=uid, app_version=version)
            db.session.add(dv)
        db.session.commit()
        return jsonify({'ok': True})
    except Exception as e:
        db.session.rollback()
        app.logger.warning('report-version failed: %s', e)
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/app/version-users/<version>')
def app_version_users(version):
    """Return list of users using a specific app version (for admin popup)."""
    if not session.get('is_master'):
        return jsonify({'ok': False, 'error': 'Admin only'}), 403
    records = DeviceAppVersion.query.filter_by(app_version=version).all()
    result = []
    for r in records:
        user = r.user
        if not user:
            continue
        # Find vehicle: match Driver.name to User.full_name, then Vehicle.driver_id
        vehicle_no = ''
        try:
            drv = Driver.query.filter_by(name=user.full_name, status='Active').first()
            if drv:
                v = Vehicle.query.filter_by(driver_id=drv.id).first()
                if v:
                    vehicle_no = v.vehicle_no or ''
        except Exception:
            pass
        result.append({
            'user_id': user.id,
            'name': user.full_name or user.username,
            'username': user.username,
            'vehicle_no': vehicle_no,
            'last_seen': r.last_seen.strftime('%d-%b-%Y %I:%M %p') if r.last_seen else '',
        })
    return jsonify({'ok': True, 'users': result})


@app.route('/admin/app-releases', methods=['GET', 'POST'])
def admin_app_releases():
    """Admin page: upload APK, manage releases, toggle force-update."""
    if not session.get('is_master'):
        flash('Only master admin can manage app releases.', 'danger')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        action = request.form.get('action', '')

        if action == 'upload':
            apk_file = request.files.get('apk_file')
            if not apk_file or not apk_file.filename:
                flash('APK file select karein.', 'danger')
                return redirect(url_for('admin_app_releases'))

            fname = secure_filename(apk_file.filename)
            if not fname.startswith('fleet-manager-') or not fname.endswith('.apk'):
                flash('APK filename "fleet-manager-X.Y.Z.apk" format mein hona chahiye.', 'danger')
                return redirect(url_for('admin_app_releases'))

            version = fname.replace('fleet-manager-', '').replace('.apk', '')
            parts = version.split('.')
            if len(parts) != 3 or not all(p.isdigit() for p in parts):
                flash(f'Version "{version}" valid nahi hai. Format: X.Y.Z (e.g. 1.2.0)', 'danger')
                return redirect(url_for('admin_app_releases'))

            existing = AppRelease.query.filter_by(version=version).first()
            if existing:
                flash(f'Version {version} already uploaded hai. Delete karein pehle ya naya version use karein.', 'warning')
                return redirect(url_for('admin_app_releases'))

            # Read file data for validation + R2 upload
            apk_data = apk_file.read()
            file_size = len(apk_data)
            if file_size < 500_000 or apk_data[:2] != b'PK':
                flash('Uploaded file valid APK nahi hai (corrupt ya unsigned). Dubara signed APK upload karein.', 'danger')
                return redirect(url_for('admin_app_releases'))

            # Upload to R2 (persistent storage — survives Render deploys)
            r2_url = None
            try:
                from services.r2_storage import upload_apk_file, R2_PUBLIC_URL
                import io as _io
                from werkzeug.datastructures import FileStorage as _FS
                # Re-wrap data for R2 upload
                apk_file.stream = _io.BytesIO(apk_data)
                r2_url = upload_apk_file(apk_file, fname)
                app.logger.info('APK uploaded to R2: %s', r2_url)
            except Exception as r2_err:
                app.logger.warning('R2 upload failed, falling back to local disk: %s', r2_err)
                r2_url = None

            # Also save to local disk as fallback (works on local dev)
            apps_dir = os.path.join(app.static_folder, 'apps')
            os.makedirs(apps_dir, exist_ok=True)
            file_path = os.path.join(apps_dir, fname)
            with open(file_path, 'wb') as f:
                f.write(apk_data)

            AppRelease.query.update({AppRelease.is_latest: False})

            force = request.form.get('force_update') == 'on'
            notes = request.form.get('release_notes', '').strip() or None
            rel = AppRelease(
                version=version,
                apk_filename=fname,
                apk_r2_url=r2_url,
                force_update=force,
                is_latest=True,
                release_notes=notes,
                file_size_bytes=file_size,
                uploaded_by=session.get('user_id'),
            )
            db.session.add(rel)
            db.session.commit()

            # Notify all active users about new app version
            try:
                from notification_service import notify_user
                from push_notifications import broadcast_push_all
                from models import User
                _notif_title = f'📱 App Update Available — v{version}'
                _notif_body = (
                    f'Fleet Manager ka naya version v{version} available hai. '
                    f'App khol kar update install karein.'
                )
                broadcast_push_all(_notif_title, _notif_body,
                                   link='/mobile-init')
                for _u in User.query.filter_by(is_active=True).all():
                    notify_user(_u.id, _notif_title, _notif_body,
                                notification_type='info', link=None, push=False)
            except Exception as _ne:
                app.logger.warning('App update notification failed: %s', _ne)

            flash(f'v{version} uploaded successfully.', 'success')

            return redirect(url_for('admin_app_releases'))

        if action == 'set_latest':
            rel_id = request.form.get('release_id', type=int)
            rel = AppRelease.query.get_or_404(rel_id)
            AppRelease.query.update({AppRelease.is_latest: False})
            rel.is_latest = True
            db.session.commit()

            # Notify all active users about newly activated version
            try:
                from notification_service import notify_user
                from push_notifications import broadcast_push_all
                from models import User
                _notif_title = f'📱 App Update Available — v{rel.version}'
                _notif_body = (
                    f'Fleet Manager ka naya version v{rel.version} available hai. '
                    f'App khol kar update install karein.'
                )
                broadcast_push_all(_notif_title, _notif_body,
                                   link='/mobile-init')
                for _u in User.query.filter_by(is_active=True).all():
                    notify_user(_u.id, _notif_title, _notif_body,
                                notification_type='info', link=None, push=False)
            except Exception as _ne:
                app.logger.warning('App update notification failed: %s', _ne)

            flash(f'v{rel.version} ab latest version hai.', 'success')
            return redirect(url_for('admin_app_releases'))

        if action == 'toggle_force':
            rel_id = request.form.get('release_id', type=int)
            rel = AppRelease.query.get_or_404(rel_id)
            rel.force_update = not rel.force_update
            db.session.commit()
            state = 'ON' if rel.force_update else 'OFF'
            flash(f'v{rel.version} force update {state}.', 'info')
            return redirect(url_for('admin_app_releases'))

        if action == 'delete':
            rel_id = request.form.get('release_id', type=int)
            rel = AppRelease.query.get_or_404(rel_id)
            # Delete from R2 if exists
            if rel.apk_r2_url:
                try:
                    from services.r2_storage import delete_apk_by_url
                    delete_apk_by_url(rel.apk_r2_url)
                except Exception:
                    pass
            # Delete from local disk if exists
            file_path = os.path.join(app.static_folder, 'apps', rel.apk_filename)
            if os.path.exists(file_path):
                os.remove(file_path)
            was_latest = rel.is_latest
            db.session.delete(rel)
            db.session.commit()
            if was_latest:
                newest = AppRelease.query.order_by(AppRelease.id.desc()).first()
                if newest:
                    newest.is_latest = True
                    db.session.commit()
            flash(f'v{rel.version} deleted.', 'success')
            return redirect(url_for('admin_app_releases'))

    releases = AppRelease.query.order_by(AppRelease.id.desc()).all()
    latest = AppRelease.query.filter_by(is_latest=True).first()
    # Build version usage counts: { '2.0.8': 5, '1.9.13': 3, ... }
    version_counts = {}
    for row in db.session.query(DeviceAppVersion.app_version, func.count(DeviceAppVersion.id)).group_by(DeviceAppVersion.app_version).all():
        version_counts[row[0]] = row[1]
    return render_template('admin_app_releases.html', releases=releases, latest=latest, version_counts=version_counts)



def _target_page_dims(page_size, orientation):
    # PDF points (1 inch = 72 pt)
    sizes = {
        'a4': (595.276, 841.890),
        'letter': (612.000, 792.000),
    }
    w, h = sizes.get((page_size or '').lower(), (None, None))
    if not w or not h:
        return None, None
    if (orientation or '').lower() == 'landscape':
        return h, w
    return w, h



def _image_to_pdf_page_bytes(fs):
    """Convert an uploaded image file to a one-page PDF bytes."""
    from PIL import Image

    img = Image.open(fs.stream)
    if img.mode in ('RGBA', 'LA', 'P'):
        bg = Image.new('RGB', img.size, (255, 255, 255))
        bg.paste(img.convert('RGBA'), mask=img.convert('RGBA').split()[-1])
        img = bg
    elif img.mode != 'RGB':
        img = img.convert('RGB')

    out = BytesIO()
    img.save(out, format='PDF', resolution=200.0)
    out.seek(0)
    return out



def _normalize_writer_pages(writer, target_w, target_h):
    """Fit each page to target size keeping aspect ratio."""
    if not target_w or not target_h:
        return writer

    try:
        from pypdf import PdfWriter as _Writer, Transformation
    except Exception:
        from PyPDF2 import PdfWriter as _Writer
        Transformation = None

    out_writer = _Writer()
    for src in writer.pages:
        src_w = float(src.mediabox.width or 0) or 1.0
        src_h = float(src.mediabox.height or 0) or 1.0
        scale = min(float(target_w) / src_w, float(target_h) / src_h)
        draw_w = src_w * scale
        draw_h = src_h * scale
        tx = (float(target_w) - draw_w) / 2.0
        ty = (float(target_h) - draw_h) / 2.0
        blank = out_writer.add_blank_page(width=float(target_w), height=float(target_h))

        if Transformation is not None and hasattr(blank, 'merge_transformed_page'):
            blank.merge_transformed_page(src, Transformation().scale(scale).translate(tx, ty))
        else:
            # Fallback for older APIs
            blank.mergeScaledTranslatedPage(src, scale, tx, ty)  # type: ignore[attr-defined]
    return out_writer



def _personal_tools_jobs_dir():
    root = os.path.join(app.static_folder, 'personal_tools_jobs')
    os.makedirs(root, exist_ok=True)
    return root



def _personal_tool_job_path(job_id):
    safe = re.sub(r'[^a-zA-Z0-9_\-]', '', (job_id or ''))
    return os.path.join(_personal_tools_jobs_dir(), safe)



def _fleet_personal_pc_desktop_template_kwargs():
    """Iframe URL for Fleet Personal PC + flag when static export was never built/deployed."""
    external = (os.environ.get('FLEET_PERSONAL_PC_URL') or '').strip()
    if external:
        return {'fleet_pc_iframe_src': external, 'fleet_pc_missing': False}

    static_folder = current_app.static_folder or ''
    index_path = os.path.join(static_folder, 'fleet_personal_pc', 'index.html')
    if os.path.isfile(index_path):
        return {
            'fleet_pc_iframe_src': url_for('static', filename='fleet_personal_pc/index.html'),
            'fleet_pc_missing': False,
        }

    return {'fleet_pc_iframe_src': '', 'fleet_pc_missing': True}



def _serve_fleet_personal_pc_asset(root_name: str, asset_path: str):
    """Serve daedalOS absolute asset paths when app runs under /static/fleet_personal_pc/."""
    static_folder = current_app.static_folder or ''
    root_abs = os.path.abspath(os.path.join(static_folder, 'fleet_personal_pc', root_name))
    target_abs = os.path.abspath(os.path.join(root_abs, asset_path or ''))

    if not target_abs.startswith(root_abs):
        abort(404)

    if not os.path.exists(target_abs):
        abort(404)

    return send_from_directory(root_abs, asset_path)



@app.route('/System/<path:asset_path>')
def fleet_personal_pc_system_asset(asset_path):
    return _serve_fleet_personal_pc_asset('System', asset_path)



@app.route('/Program Files/<path:asset_path>')
def fleet_personal_pc_program_files_asset(asset_path):
    return _serve_fleet_personal_pc_asset('Program Files', asset_path)



@app.route('/Users/<path:asset_path>')
def fleet_personal_pc_users_asset(asset_path):
    return _serve_fleet_personal_pc_asset('Users', asset_path)



@app.route('/Drives/<path:asset_path>')
def fleet_personal_pc_drives_asset(asset_path):
    return _serve_fleet_personal_pc_asset('Drives', asset_path)



@app.route('/fleet-brand/<path:asset_path>')
def fleet_personal_pc_brand_asset(asset_path):
    return _serve_fleet_personal_pc_asset('fleet-brand', asset_path)



@app.route('/admin/personal-tools', methods=['GET', 'POST'])
def admin_personal_tools():
    """Fleet Personal PC desktop entrypoint (daedalOS iframe only)."""
    if not _require_master_admin():
        return redirect(url_for('dashboard'))
    return render_template(
        'admin_personal_tools_desktop.html',
        **_fleet_personal_pc_desktop_template_kwargs(),
    )



@app.route('/admin/personal-tools/quick-print', methods=['GET', 'POST'])
def admin_personal_tools_quick_print():
    """Standalone multi file select + print tool from desktop launcher."""
    if not _require_master_admin():
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        ok, payload = _build_personal_tools_quick_print_payload()
        if not ok:
            flash(payload.get('error', 'Print batch error'), 'danger')
            return redirect(url_for('admin_personal_tools_quick_print'))

        return render_template(
            'admin_personal_tools_print_ready.html',
            pdf_url=payload['pdf_url'],
            pages=payload['pages'],
            files_count=payload['files_count'],
            page_size=payload['page_size'],
            orientation=payload['orientation'],
            order_by=payload['order_by'],
            job_id='',
        )

    return render_template('admin_personal_tools_quick_print.html')



def _build_personal_tools_quick_print_payload(include_content=False):
    files = request.files.getlist('print_files')
    files = [f for f in files if f and (f.filename or '').strip()]
    if not files:
        return False, {'error': 'Kam az kam 1 PDF/Image file select karein.'}

    page_size = (request.form.get('page_size') or 'original').strip().lower()
    orientation = (request.form.get('orientation') or 'portrait').strip().lower()
    order_by = (request.form.get('order_by') or 'as_uploaded').strip().lower()
    if page_size not in {'original', 'a4', 'letter'}:
        page_size = 'original'
    if orientation not in {'portrait', 'landscape'}:
        orientation = 'portrait'
    if order_by not in {'as_uploaded', 'name_asc', 'name_desc'}:
        order_by = 'as_uploaded'
    if order_by in {'name_asc', 'name_desc'}:
        files = sorted(files, key=lambda f: secure_filename(f.filename or '').lower(), reverse=(order_by == 'name_desc'))

    try:
        PdfReader, PdfWriter = _load_pdf_writer_reader()
        writer = PdfWriter()
        allowed_img = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif', '.tif', '.tiff'}
        added_pages = 0
        for fs in files:
            ext = os.path.splitext(secure_filename(fs.filename or ''))[1].lower()
            if ext == '.pdf':
                reader = PdfReader(fs.stream)
                for p in reader.pages:
                    writer.add_page(p)
                    added_pages += 1
            elif ext in allowed_img:
                page_pdf = _image_to_pdf_page_bytes(fs)
                reader = PdfReader(page_pdf)
                for p in reader.pages:
                    writer.add_page(p)
                    added_pages += 1
        if added_pages <= 0:
            return False, {'error': 'Selected files me printable pages nahi milin.'}

        tw, th = _target_page_dims(page_size, orientation)
        if tw and th:
            writer = _normalize_writer_pages(writer, tw, th)
        tmp_dir = os.path.join(app.static_folder, 'tmp_print')
        os.makedirs(tmp_dir, exist_ok=True)
        fname = f'fleet-print-{uuid.uuid4().hex}.pdf'
        fpath = os.path.join(tmp_dir, fname)
        with open(fpath, 'wb') as f:
            out = BytesIO()
            writer.write(out)
            out.seek(0)
            pdf_bytes = out.read()
            f.write(pdf_bytes)

        payload = {
            'files_count': len(files),
            'order_by': order_by,
            'orientation': orientation,
            'page_size': page_size,
            'pages': added_pages,
            'pdf_name': fname,
            'pdf_url': url_for('api_personal_tools_quick_print_file', filename=fname),
        }
        if include_content:
            payload['pdf_base64'] = base64.b64encode(pdf_bytes).decode('ascii')

        return True, payload
    except Exception as e:
        return False, {'error': f'Print batch error: {e}'}



@app.route('/api/personal-tools/quick-print', methods=['POST'])
def api_personal_tools_quick_print():
    if not _validate_csrf_exempt_origin():
        return jsonify({'error': 'Cross-origin request blocked', 'success': False}), 403
    if not _require_master_admin():
        return jsonify({'error': 'Unauthorized access', 'success': False}), 403

    ok, payload = _build_personal_tools_quick_print_payload(include_content=True)
    if not ok:
        return jsonify({'error': payload.get('error', 'Print batch error'), 'success': False}), 400

    payload['success'] = True
    return jsonify(payload)



@app.route('/api/personal-tools/quick-print/file/<path:filename>', methods=['GET'])
def api_personal_tools_quick_print_file(filename):
    if not _require_master_admin():
        return jsonify({'error': 'Unauthorized access'}), 403

    safe_name = secure_filename(filename or '')
    if not safe_name.lower().endswith('.pdf'):
        abort(404)

    tmp_dir = os.path.join(app.static_folder, 'tmp_print')
    fpath = os.path.abspath(os.path.join(tmp_dir, safe_name))
    base = os.path.abspath(tmp_dir)
    if not fpath.startswith(base) or not os.path.exists(fpath):
        abort(404)

    return send_from_directory(tmp_dir, safe_name, mimetype='application/pdf')



@app.route('/admin/personal-tools/os-notes', methods=['GET'])
def admin_personal_tools_os_notes():
    """Minimal Notes page opened from Fleet Personal PC (Browser / desktop shortcuts)."""
    if not _require_master_admin():
        return redirect(url_for('dashboard'))
    return render_template('admin_personal_tools_os_notes.html')



@app.route('/admin/personal-tools/os-calculator', methods=['GET'])
def admin_personal_tools_os_calculator():
    """Minimal Calculator for Fleet Personal PC shortcuts."""
    if not _require_master_admin():
        return redirect(url_for('dashboard'))
    return render_template('admin_personal_tools_os_calculator.html')



@app.route('/admin/personal-tools/library', methods=['GET'])
def admin_personal_tools_library():
    if not _require_master_admin():
        return redirect(url_for('dashboard'))

    jobs = []
    base = _personal_tools_jobs_dir()
    for job_id in os.listdir(base):
        jdir = _personal_tool_job_path(job_id)
        mpath = os.path.join(jdir, 'metadata.json')
        if not os.path.isdir(jdir) or not os.path.exists(mpath):
            continue
        try:
            with open(mpath, 'r', encoding='utf-8') as f:
                meta = json.load(f)
            jobs.append(meta)
        except Exception:
            continue
    jobs.sort(key=lambda j: j.get('created_at') or '', reverse=True)
    return render_template('admin_personal_tools_library.html', jobs=jobs)



@app.route('/admin/personal-tools/library/<job_id>', methods=['GET'])
def admin_personal_tools_library_detail(job_id):
    if not _require_master_admin():
        return redirect(url_for('dashboard'))

    jdir = _personal_tool_job_path(job_id)
    mpath = os.path.join(jdir, 'metadata.json')
    if not os.path.exists(mpath):
        abort(404)
    with open(mpath, 'r', encoding='utf-8') as f:
        meta = json.load(f)
    return render_template('admin_personal_tools_library_detail.html', meta=meta)



@app.route('/api/register-fcm-token', methods=['POST'])
def web_register_fcm_token():
    """Register FCM push token for web-session user (Capacitor or browser).
    Bank-app style: if a new user logs into the same physical device,
    the token is transferred and deactivated for the old user."""
    uid = session.get('user_id')
    if not uid:
        return jsonify({'error': 'Not authenticated'}), 401

    data = request.get_json(silent=True) or {}
    token = (data.get('token') or '').strip()
    if not token:
        return jsonify({'error': 'token required'}), 400

    device_id = (data.get('device_unique_id') or '').strip() or None
    device_info = (data.get('device_info') or '')[:255]

    if device_id:
        DeviceFCMToken.query.filter(
            DeviceFCMToken.device_unique_id == device_id,
            DeviceFCMToken.user_id != uid,
        ).update({DeviceFCMToken.is_active: False}, synchronize_session=False)

        existing = DeviceFCMToken.query.filter_by(
            user_id=uid, device_unique_id=device_id
        ).first()
        if existing:
            existing.fcm_token = token
            existing.device_info = device_info or existing.device_info
            existing.is_active = True
            db.session.commit()
            return jsonify({'status': 'refreshed'})
    else:
        existing = DeviceFCMToken.query.filter_by(
            user_id=uid, fcm_token=token
        ).first()
        if existing:
            existing.is_active = True
            existing.device_info = device_info or existing.device_info
            db.session.commit()
            return jsonify({'status': 'refreshed'})

    new_tok = DeviceFCMToken(
        user_id=uid, fcm_token=token,
        device_unique_id=device_id,
        device_info=device_info, is_active=True
    )
    db.session.add(new_tok)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        if device_id:
            dup = DeviceFCMToken.query.filter_by(
                user_id=uid, device_unique_id=device_id
            ).first()
            if dup:
                dup.fcm_token = token
                dup.is_active = True
                db.session.commit()
    return jsonify({'status': 'registered'})



@app.route('/api/poll-notifications')
def poll_notifications():
    """Session-based JSON endpoint for the native polling service.
    Returns unread notifications filtered by user's role permissions."""
    uid = session.get('user_id')
    if not uid:
        return jsonify({'error': 'Not authenticated'}), 401

    user_perms = set(session.get('permissions') or [])
    is_master = session.get('is_master', False)
    from notification_service import unread_inbox_for_user

    result = []
    for n in unread_inbox_for_user(uid, user_perms, is_master)[:20]:
        result.append({
            'id': n.id,
            'title': n.title,
            'message': n.message or '',
            'link': n.link,
            'created_at': n.created_at.isoformat() if n.created_at else None,
        })

    return jsonify({'notifications': result})



@app.route('/')
@app.route('/dashboard')
def dashboard():
    from auth_utils import get_user_context
    
    # Get user data context for scoping
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)
    
    # Determine what sections this user can see (skip expensive queries for hidden cards)
    _perms = set(session.get('permissions') or [])
    _is_master = session.get('is_master', False)
    try:
        from permissions_config import can_see_page as _csp
        def _can(key):
            return True if _is_master else _csp(_perms, key)
    except Exception:
        def _can(key):
            return True

    today_dt = pk_date()

    allowed_shifts = user_context.get('allowed_shifts', set())
    allowed_parking = user_context.get('allowed_parking', set())

    def _scope_vehicle_q(q):
        if is_master_or_admin:
            return q
        if allowed_vehicles:
            return q.filter(Vehicle.id.in_(list(allowed_vehicles)))
        if allowed_projects:
            q = q.filter(Vehicle.project_id.in_(list(allowed_projects)))
        if allowed_districts:
            q = q.filter(Vehicle.district_id.in_(list(allowed_districts)))
        return q

    def _scope_driver_q(q):
        if is_master_or_admin:
            return q
        if allowed_vehicles:
            return q.filter(Driver.vehicle_id.in_(list(allowed_vehicles)))
        if allowed_projects:
            q = q.filter(Driver.project_id.in_(list(allowed_projects)))
        if allowed_districts:
            q = q.filter(Driver.district_id.in_(list(allowed_districts)))
        if allowed_shifts:
            q = q.filter(Driver.shift.in_(list(allowed_shifts)))
        return q

    # ── Bento KPI cards (only query what the user can see) ────────────────
    total_companies  = Company.query.count() if _can('dashboard_card_companies') else 0

    project_q = Project.query
    if not is_master_or_admin and allowed_projects:
        project_q = project_q.filter(Project.id.in_(list(allowed_projects)))
    total_projects = project_q.count() if _can('dashboard_card_projects') else 0

    total_vehicles = _scope_vehicle_q(Vehicle.query).count() if (_can('dashboard_card_vehicles') or _can('dashboard_card_utilization')) else 0

    total_drivers = _scope_driver_q(Driver.query).count() if _can('dashboard_card_drivers') else 0

    total_parking = 0
    if _can('dashboard_card_parking'):
        if is_master_or_admin:
            total_parking = ParkingStation.query.count()
        else:
            scoped_v = _scope_vehicle_q(Vehicle.query).with_entities(Vehicle.parking_station_id).filter(
                Vehicle.parking_station_id.isnot(None)
            ).distinct()
            parking_ids_from_vehicles = {r[0] for r in scoped_v.all()}
            if allowed_parking:
                parking_ids_from_vehicles |= allowed_parking
            if parking_ids_from_vehicles:
                total_parking = ParkingStation.query.filter(
                    ParkingStation.id.in_(list(parking_ids_from_vehicles))
                ).count()
            elif allowed_projects:
                total_parking = ParkingStation.query.filter(
                    ParkingStation.project_id.in_(list(allowed_projects))
                ).count()

    district_q = District.query
    if not is_master_or_admin and allowed_districts:
        district_q = district_q.filter(District.id.in_(list(allowed_districts)))
    total_districts = district_q.count() if _can('dashboard_card_districts') else 0

    active_drivers = _scope_driver_q(
        Driver.query.filter(Driver.status == 'Active', Driver.vehicle_id.isnot(None))
    ).count() if _can('dashboard_card_drivers') else 0

    assigned_vehicles = _scope_vehicle_q(
        Vehicle.query.filter(Vehicle.district_id.isnot(None))
    ).count() if _can('dashboard_card_vehicles') else 0

    attendance_q = DriverAttendance.query.filter_by(attendance_date=today_dt)
    if not is_master_or_admin and allowed_projects:
        attendance_q = attendance_q.filter(DriverAttendance.project_id.in_(list(allowed_projects)))
    today_attendance = attendance_q.count() if _can('dashboard_card_attendance') else 0

    transfer_q = DriverTransfer.query.filter_by(transfer_date=today_dt)
    if not is_master_or_admin and allowed_projects:
        transfer_q = transfer_q.filter(
            or_(
                DriverTransfer.old_project_id.in_(list(allowed_projects)),
                DriverTransfer.new_project_id.in_(list(allowed_projects))
            )
        )
    today_transfers = transfer_q.count() if _can('dashboard_card_transfers') else 0

    # Monthly fuel cost + 30-day trend (only if user can see fuel expense)
    monthly_fuel = 0.0
    fuel_chart_labels, fuel_chart_values = [], []
    if _can('dashboard_card_fuel'):
        try:
            from sqlalchemy import extract
            fuel_q = db.session.query(func.sum(FuelExpense.amount)).filter(
                extract('month', FuelExpense.fueling_date) == today_dt.month,
                extract('year', FuelExpense.fueling_date) == today_dt.year
            )
            # Apply user data scope to fuel expenses
            if not is_master_or_admin:
                if allowed_projects:
                    fuel_q = fuel_q.filter(FuelExpense.project_id.in_(list(allowed_projects)))
                if allowed_districts:
                    fuel_q = fuel_q.filter(FuelExpense.district_id.in_(list(allowed_districts)))
            monthly_fuel = fuel_q.scalar() or 0
            monthly_fuel = float(monthly_fuel)
        except Exception:
            monthly_fuel = 0.0
        try:
            from datetime import timedelta
            _start30 = today_dt - timedelta(days=29)
            _daily_q = db.session.query(
                FuelExpense.fueling_date,
                func.sum(FuelExpense.amount)
            ).filter(
                FuelExpense.fueling_date >= _start30,
                FuelExpense.fueling_date <= today_dt
            )
            # Apply user data scope
            if not is_master_or_admin:
                if allowed_projects:
                    _daily_q = _daily_q.filter(FuelExpense.project_id.in_(list(allowed_projects)))
                if allowed_districts:
                    _daily_q = _daily_q.filter(FuelExpense.district_id.in_(list(allowed_districts)))
            _daily_rows = _daily_q.group_by(FuelExpense.fueling_date).all()
            _daily_map = {str(r[0]): float(r[1] or 0) for r in _daily_rows}
            for i in range(29, -1, -1):
                _d = today_dt - timedelta(days=i)
                fuel_chart_labels.append(_d.strftime('%d %b'))
                fuel_chart_values.append(_daily_map.get(str(_d), 0))
        except Exception:
            fuel_chart_labels, fuel_chart_values = [], []

    # ── Vehicle utilization doughnut (only if user can see vehicles) ──────
    vehicle_util_data = [0, 0, 0]
    if _can('dashboard_card_utilization'):
        try:
            v_active = _scope_vehicle_q(Vehicle.query.filter(Vehicle.driver_id.isnot(None))).count()
            v_deployed = _scope_vehicle_q(Vehicle.query.filter(Vehicle.project_id.isnot(None), Vehicle.driver_id.is_(None))).count()
            v_idle = _scope_vehicle_q(Vehicle.query.filter(Vehicle.project_id.is_(None), Vehicle.driver_id.is_(None))).count()
            vehicle_util_data = [v_active, v_deployed, v_idle]
        except Exception:
            vehicle_util_data = [0, 0, 0]

    # ── Financial Health chart (only if user can see accounts) ───────────
    fin_chart_labels, fin_chart_receipts, fin_chart_expenses = [], [], []
    if _can('dashboard_card_finance'):
        try:
            from sqlalchemy import extract as _extr
            from models import JournalEntry, JournalEntryLine
            _rec_rows = db.session.query(
                Project.name,
                func.sum(JournalEntryLine.credit).label('total_credit')
            ).join(JournalEntry, JournalEntry.id == JournalEntryLine.journal_entry_id
            ).join(Project, Project.id == JournalEntry.project_id).filter(
                JournalEntry.entry_type == 'Receipt',
                _extr('month', JournalEntry.entry_date) == today_dt.month,
                _extr('year',  JournalEntry.entry_date) == today_dt.year,
                JournalEntry.project_id.isnot(None)
            ).group_by(Project.name).all()
            _exp_rows = db.session.query(
                Project.name,
                func.sum(JournalEntryLine.debit).label('total_debit')
            ).join(JournalEntry, JournalEntry.id == JournalEntryLine.journal_entry_id
            ).join(Project, Project.id == JournalEntry.project_id).filter(
                JournalEntry.entry_type.in_(['Payment', 'Expense']),
                _extr('month', JournalEntry.entry_date) == today_dt.month,
                _extr('year',  JournalEntry.entry_date) == today_dt.year,
                JournalEntry.project_id.isnot(None)
            ).group_by(Project.name).all()
            _rec_map = {r[0]: round(float(r[1] or 0), 0) for r in _rec_rows}
            _exp_map = {r[0]: round(float(r[1] or 0), 0) for r in _exp_rows}
            _fin_projects = sorted(set(list(_rec_map.keys()) + list(_exp_map.keys())),
                                   key=lambda n: (_rec_map.get(n, 0) + _exp_map.get(n, 0)), reverse=True)[:6]
            fin_chart_labels   = _fin_projects
            fin_chart_receipts = [_rec_map.get(p, 0) for p in _fin_projects]
            fin_chart_expenses = [_exp_map.get(p, 0) for p in _fin_projects]
            if not _fin_projects and _can('dashboard_card_fuel'):
                _proj_rows = db.session.query(
                    Project.name, func.sum(FuelExpense.amount).label('total')
                ).join(FuelExpense, FuelExpense.project_id == Project.id).filter(
                    _extr('month', FuelExpense.fueling_date) == today_dt.month,
                    _extr('year',  FuelExpense.fueling_date) == today_dt.year
                ).group_by(Project.name).order_by(func.sum(FuelExpense.amount).desc()).limit(6).all()
                fin_chart_labels   = [r[0] for r in _proj_rows]
                fin_chart_receipts = []
                fin_chart_expenses = [round(float(r[1]), 0) for r in _proj_rows]
        except Exception:
            fin_chart_labels, fin_chart_receipts, fin_chart_expenses = [], [], []
    # Keep legacy vars for template compatibility
    project_chart_labels = fin_chart_labels
    project_chart_values = fin_chart_expenses

    # ── Maintenance KPIs ──────────────────────────────────────────────────
    monthly_maintenance = 0.0
    open_work_orders = 0
    if _can('dashboard_card_maintenance'):
        try:
            from sqlalchemy import extract as _mext
            _maint_q = db.session.query(func.sum(MaintenanceExpense.total_bill_amount)).filter(
                _mext('month', MaintenanceExpense.expense_date) == today_dt.month,
                _mext('year',  MaintenanceExpense.expense_date) == today_dt.year
            )
            if not is_master_or_admin:
                if allowed_projects:
                    _maint_q = _maint_q.filter(MaintenanceExpense.project_id.in_(list(allowed_projects)))
                if allowed_districts:
                    _maint_q = _maint_q.filter(MaintenanceExpense.district_id.in_(list(allowed_districts)))
            monthly_maintenance = float(_maint_q.scalar() or 0)
            _wo_q = MaintenanceWorkOrder.query.filter(MaintenanceWorkOrder.status != 'closed')
            if not is_master_or_admin:
                if allowed_projects:
                    _wo_q = _wo_q.filter(MaintenanceWorkOrder.project_id.in_(list(allowed_projects)))
                if allowed_districts:
                    _wo_q = _wo_q.filter(MaintenanceWorkOrder.district_id.in_(list(allowed_districts)))
            open_work_orders = _wo_q.count()
        except Exception:
            monthly_maintenance, open_work_orders = 0.0, 0

    # ── Document Health: expiry in next 15 days / already expired ────────
    expiry_soon, expiry_already = 0, 0
    if _can('dashboard_card_doc_health'):
        try:
            from datetime import timedelta as _td
            _cutoff15 = today_dt + _td(days=15)
            _exp_q = _scope_driver_q(Driver.query.filter(Driver.status == 'Active'))
            for _drv in _exp_q.all():
                _lic, _cn = _drv.license_expiry_date, _drv.cnic_expiry_date
                if (_lic and today_dt <= _lic <= _cutoff15) or (_cn and today_dt <= _cn <= _cutoff15):
                    expiry_soon += 1
                elif (_lic and _lic < today_dt) or (_cn and _cn < today_dt):
                    expiry_already += 1
        except Exception:
            expiry_soon, expiry_already = 0, 0

    user_id = session.get('user_id')
    notifications = []
    # Inbox / poll: only users with notification list permission
    if _can('notification_list') and user_id:
        try:
            notifications = _unread_notifications_for_user(user_id, 20)
        except Exception:
            notifications = []

    # Critical health alert from cache (master only, no extra API calls)
    health_alert = None
    if session.get('is_master') and _health_cache.get('data') and _health_cache['data'].get('any_critical'):
        health_alert = _health_cache['data']

    return render_template('dashboard.html',
                           total_companies=total_companies,
                           total_projects=total_projects,
                           total_vehicles=total_vehicles,
                           total_drivers=total_drivers,
                           total_parking=total_parking,
                           total_districts=total_districts,
                           active_drivers=active_drivers,
                           assigned_vehicles=assigned_vehicles,
                           today_attendance=today_attendance,
                           today_transfers=today_transfers,
                           monthly_fuel=monthly_fuel,
                           fuel_chart_labels=fuel_chart_labels,
                           fuel_chart_values=fuel_chart_values,
                           vehicle_util_data=vehicle_util_data,
                           project_chart_labels=project_chart_labels,
                           project_chart_values=project_chart_values,
                           fin_chart_labels=fin_chart_labels,
                           fin_chart_receipts=fin_chart_receipts,
                           fin_chart_expenses=fin_chart_expenses,
                           expiry_soon=expiry_soon,
                           expiry_already=expiry_already,
                           notifications=notifications,
                           health_alert=health_alert,
                           monthly_maintenance=monthly_maintenance,
                           open_work_orders=open_work_orders,
                           now_dt=today_dt,
                           dashboard_time=pk_now().strftime('%H:%M:%S'),
                           from_login=request.args.get('from_login') == '1')



@app.route('/notification/<int:pk>/read', methods=['GET', 'POST'])
def notification_read(pk):
    """Mark read and redirect (Open link uses GET; AJAX may POST)."""
    n = Notification.query.get_or_404(pk)
    user_id = session.get('user_id')
    if user_id:
        user_perms = set(session.get('permissions') or [])
        is_master = session.get('is_master', False)
        from notification_service import notification_visible_to_user, _invalidate_notif_cache
        if not notification_visible_to_user(n, user_id, user_perms, is_master):
            flash('You do not have access to this notification.', 'danger')
            return redirect(url_for('notification_list'))
        nr = NotificationRead.query.filter_by(notification_id=pk, user_id=user_id).first()
        if not nr:
            nr = NotificationRead(notification_id=pk, user_id=user_id, read_at=pk_now())
            db.session.add(nr)
        else:
            nr.read_at = pk_now()
        db.session.commit()
        _invalidate_notif_cache([user_id])
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'ok': True})
    next_url = request.args.get('next') or n.link or url_for('dashboard')
    return redirect(next_url)



@app.route('/notification/<int:pk>/dismiss', methods=['POST'])
def notification_dismiss(pk):
    """Remove notification from this user's inbox — delete personal rows, hide broadcasts."""
    if not session.get('user_id'):
        return jsonify({'ok': False, 'message': 'Not signed in.'}), 401
    if not session.get('is_master') and not user_can_access(session.get('permissions') or [], 'notification_list'):
        return jsonify({'ok': False, 'message': 'Permission denied.'}), 403
    n = Notification.query.get_or_404(pk)
    user_id = session.get('user_id')
    user_perms = set(session.get('permissions') or [])
    is_master = session.get('is_master', False)
    from notification_service import notification_visible_to_user, _invalidate_notif_cache
    if not notification_visible_to_user(n, user_id, user_perms, is_master):
        return jsonify({'ok': False, 'message': 'Permission denied.'}), 403
    tid = getattr(n, 'target_user_id', None)
    if tid is not None and int(tid) == int(user_id):
        db.session.delete(n)
    else:
        nr = NotificationRead.query.filter_by(notification_id=pk, user_id=user_id).first()
        if not nr:
            nr = NotificationRead(notification_id=pk, user_id=user_id, read_at=pk_now())
            db.session.add(nr)
        else:
            nr.read_at = pk_now()
    db.session.commit()
    _invalidate_notif_cache([user_id])
    return jsonify({'ok': True, 'message': 'Notification deleted.'})



@app.route('/notifications')
def notification_list():
    """List notifications visible to the current user based on role permissions."""
    user_id = session.get('user_id')
    user_perms = set(session.get('permissions') or [])
    is_master = session.get('is_master', False)
    read_ids = set()
    if user_id:
        read_ids = {r.notification_id for r in NotificationRead.query.filter_by(user_id=user_id).all()}
    from notification_service import unread_inbox_for_user

    filtered = unread_inbox_for_user(user_id, user_perms, is_master)

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    pagination = SimplePagination(filtered, page, per_page)
    notifications = pagination.items
    return render_template('notification_list.html', notifications=notifications, read_ids=read_ids, pagination=pagination, per_page=per_page, **_notifications_nav_back())



@app.route('/notifications/new', methods=['GET', 'POST'])
def notification_add():
    """Create notification (requires notification_add permission)."""
    if not session.get('is_master') and not user_can_access(session.get('permissions') or [], 'notification_add'):
        flash('You do not have permission to create notifications.', 'danger')
        return redirect(url_for('notification_list'))
    form = NotificationForm()
    if form.validate_on_submit():
        flash(
            'Manual notification create is temporarily disabled. '
            'Attendance (GPS+Camera) and Task Report save alerts are sent automatically.',
            'info',
        )
        return redirect(url_for('notification_list'))
    return render_template('notification_form.html', form=form, **_notifications_nav_back())



@app.route('/reminders')
def reminder_list():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    reminders = Reminder.query.filter_by(user_id=user_id).order_by(Reminder.reminder_date.desc(), Reminder.reminder_time).all()
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    pagination = SimplePagination(reminders, page, per_page)
    reminders = pagination.items
    return render_template('reminder_list.html', reminders=reminders, pagination=pagination, per_page=per_page, **_notifications_nav_back())



@app.route('/reminders/new', methods=['GET', 'POST'])
def reminder_add():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    form = ReminderForm()
    if form.validate_on_submit():
        t = _parse_time(form.reminder_time.data)
        r = Reminder(
            user_id=user_id,
            title=form.title.data.strip(),
            message=(form.message.data or '').strip() or None,
            reminder_date=form.reminder_date.data,
            reminder_time=t,
            is_completed=False
        )
        db.session.add(r)
        db.session.commit()
        flash('Reminder saved.', 'success')
        return redirect(url_for('reminder_list'))
    return render_template('reminder_form.html', form=form, **_notifications_nav_back())



@app.route('/reminders/<int:pk>/edit', methods=['GET', 'POST'])
def reminder_edit(pk):
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    r = Reminder.query.filter_by(id=pk, user_id=user_id).first_or_404()
    form = ReminderForm(obj=r)
    if form.validate_on_submit():
        r.title = form.title.data.strip()
        r.message = (form.message.data or '').strip() or None
        r.reminder_date = form.reminder_date.data
        r.reminder_time = _parse_time(form.reminder_time.data)
        db.session.commit()
        flash('Reminder updated.', 'success')
        return redirect(url_for('reminder_list'))
    if request.method == 'GET':
        form.reminder_time.data = r.reminder_time.strftime('%H:%M') if r.reminder_time else ''
    return render_template('reminder_form.html', form=form, reminder=r, **_notifications_nav_back())



@app.route('/reminders/<int:pk>/delete', methods=['POST'])
def reminder_delete(pk):
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    r = Reminder.query.filter_by(id=pk, user_id=user_id).first_or_404()
    db.session.delete(r)
    db.session.commit()
    flash('Reminder deleted.', 'success')
    return redirect(url_for('reminder_list'))



@app.route('/reminders/<int:pk>/toggle', methods=['POST'])
def reminder_toggle(pk):
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    r = Reminder.query.filter_by(id=pk, user_id=user_id).first_or_404()
    r.is_completed = not r.is_completed
    db.session.commit()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'ok': True, 'is_completed': r.is_completed})
    return redirect(url_for('reminder_list'))



def fleet_not_found_redirect(e):
    """Mobile WebView can restore a stale deep link (old route/bookmark) while the session
    cookie is still valid — Flask then shows a bare 404 before any JS runs. Send HTML
    navigations back through /mobile-init so the user always gets the login screen."""
    path = request.path or ''
    if path.startswith('/api/'):
        return jsonify({'ok': False, 'error': 'Not found'}), 404
    if request.method not in ('GET', 'HEAD'):
        return e
    if path in ('/mobile-init', '/login', '/health'):
        return e
    accept = (request.headers.get('Accept') or '').lower()
    if accept and 'application/json' in accept and 'text/html' not in accept and '*/*' not in accept:
        return jsonify({'ok': False, 'error': 'Not found'}), 404
    if not _is_capacitor_browser():
        return e
    return redirect(url_for('mobile_init'))


