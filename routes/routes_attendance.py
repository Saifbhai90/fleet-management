"""
Attendance routes - Driver attendance list, mark, check-in/out, GPS check-in/out,
manual check-in/out, bulk operations, pending, missing checkout, reports,
daily reports, TRA report, media gallery, and attendance API endpoints.

Extracted from routes.py to reduce file size.
"""
import os
import io
import csv
import tempfile
from io import BytesIO, StringIO
from decimal import Decimal
from datetime import datetime, date, time, timedelta
from calendar import monthrange

import xlsxwriter
from flask import (
    render_template, redirect, url_for, flash, request,
    session, send_file, send_from_directory, jsonify,
    after_this_request, make_response, abort,
)
from sqlalchemy import func, text, or_, and_, cast
from sqlalchemy import String as SAString
from werkzeug.utils import secure_filename

from app import app, db
from models import (
    Company, Project, Vehicle, Driver, ParkingStation, District,
    DriverAttendance, DriverStatusChange,
    VehicleTransfer, DriverTransfer, ProjectTransfer,
    AttendanceTimeControl, AttendanceTimeOverride,
    LeaveRequest,
    DeviceFCMToken,
    User,
)
from forms import (
    DriverAttendanceFilterForm, DriverAttendanceReportForm,
    ATTENDANCE_STATUS_CHOICES,
    ATTENDANCE_LIST_STATUS_FILTER_OPTIONS,
)
from vehicle_sort_utils import vehicle_order_by
from utils import (
    parse_date, pk_now, pk_date, pk_time,
    format_phone, format_cnic,
)
from r2_storage import upload_image_file, upload_image_bytes
from auth_utils import user_can_access

# Import shared helpers from routes.py
from routes import (
    _multi_word_filter,
    _nav_back_ctx,
    _time_to_minutes_day,
    _alternate_checkin_window_active,
    _attendance_local_date,
    _attendance_local_now,
    _attendance_local_time,
    _attendance_checkin_stamp,
    _attendance_list_resolve_per_page,
    _attendance_list_manual_edit_allowed,
    _attendance_list_manual_checkout_allowed,
    _attendance_list_manual_delete_allowed,
    _attendance_mark_record_clearable,
    _attendance_status_abbr,
    _attendance_daily_cell_tooltip,
    _attendance_daily_slot_key,
    _attendance_is_empty_gps_shell,
    _attendance_record_counts_in_report,
    _build_attendance_media_gallery_items,
    _driver_attendance_flat_rows,
    _driver_attendance_list_redirect_params_from_form,
    _driver_attendance_mark_redirect_url,
    _driver_attendance_record_allowed_for_user,
    _driver_excluded_from_missing_checkin_list,
    _driver_has_open_segment,
    _driver_marked_duty_off_no_checkin,
    _duty_shift_label,
    _duty_shift_passes_filter,
    _filter_attendance_rows_by_duty_shift,
    _filter_attendance_rows_by_status,
    _get_checked_in_vehicle_ids,
    _get_user_scope,
    _gps_marked_attendance_row,
    _manual_checkin_blocked_by_vehicle_rules,
    _next_attendance_segment,
    _open_driver_attendance_for_manual_checkout,
    _open_gps_driver_attendance_for_checkout,
    _open_gps_driver_attendance_session,
    _parse_attendance_status_filter_request,
    _parse_duty_shift_filter_request,
    _preserve_nav_from,
    _vehicle_capacity_value,
    _vehicle_label,
    _vehicle_oldest_pending_checkout,
    _vehicle_pending_checkout_block_message,
    _delete_stored_attendance_photo,
    _count_driver_segments_with_checkin,
    _count_month_present_days,
    _daily_attendance_fill_segment_boundary_cells,
    _daily_attendance_grid_cell_skip_totals,
    _daily_attendance_grid_cell_value,
    _daily_attendance_row_lifecycle_badges,
    SimplePagination,
    _maintenance_attachment_local_full_path,
    _maintenance_attachment_read_bytes,
    media_url_filter,
)

import re
import uuid
import zipfile
from sqlalchemy.orm import joinedload
from models import MaintenanceExpense
from utils import format_time_ampm, generate_excel_template
from models import project_district
@app.route('/driver-attendance/')
def driver_attendance_list():
    from auth_utils import get_user_context
    
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    allowed_shifts = user_context.get('allowed_shifts', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)
    
    form = DriverAttendanceFilterForm()
    # Sirf assigned projects (company assign kiye gaye)
    project_q = Project.query.filter(Project.company_id.isnot(None))
    if not is_master_or_admin and allowed_projects:
        project_q = project_q.filter(Project.id.in_(list(allowed_projects)))
    form.project_id.choices = [(0, '-- All Projects --')] + [(p.id, p.name) for p in project_q.order_by(Project.name).all()]
    # Default: aaj ki date; from/to support ke liye base date phir bhi chahiye
    view_date = _attendance_local_date()
    def _int_arg(name):
        v = request.args.get(name)
        if v is None or v == '':
            return None
        try:
            n = int(v)
            return n if n != 0 else None
        except (TypeError, ValueError):
            return None
    project_id = _int_arg('project_id')
    district_id = _int_arg('district_id')
    vehicle_id = _int_arg('vehicle_id')
    driver_id = _int_arg('driver_id')
    shift = (request.args.get('shift') or '').strip()
    search = (request.args.get('search') or '').strip()
    duty_shift_filter = _parse_duty_shift_filter_request()
    status_filter_selected = _parse_attendance_status_filter_request()
    list_filter = (request.args.get('list_filter') or '').strip().lower()
    if list_filter not in ('', 'missing_co'):
        list_filter = ''
    # From / To date range (strings in dd-mm-yyyy)
    from_date_str = (request.args.get('from_date') or '').strip()
    to_date_str = (request.args.get('to_date') or '').strip()

    from_date = None
    to_date = None
    try:
        if from_date_str:
            from_date = parse_date(from_date_str)
    except ValueError:
        from_date = None
    try:
        if to_date_str:
            to_date = parse_date(to_date_str)
    except ValueError:
        to_date = None

    # Agar single-date filter (purana param) diya ho to usse from/to ke roop mein treat karein
    if request.args.get('date') and not from_date and not to_date:
        view_date = parse_date(request.args.get('date')) or view_date
        from_date = to_date = view_date
        from_date_str = to_date_str = view_date.strftime('%d-%m-%Y')

    # Auto-select & disable if only 1 option allowed
    disable_project = False
    disable_district = False
    disable_vehicle = False
    disable_shift = False
    if not is_master_or_admin:
        if len(allowed_projects) == 1:
            if project_id is None:
                project_id = next(iter(allowed_projects))
            disable_project = True
        if len(allowed_districts) == 1:
            if district_id is None:
                district_id = next(iter(allowed_districts))
            disable_district = True
        if len(allowed_vehicles) == 1:
            if vehicle_id is None:
                vehicle_id = next(iter(allowed_vehicles))
            disable_vehicle = True
        if len(allowed_shifts) == 1:
            if not shift:
                shift = next(iter(allowed_shifts))
            disable_shift = True

    form.attendance_date.data = view_date
    form.project_id.data = project_id if project_id else 0
    if project_id and project_id != 0:
        districts_q = District.query.join(project_district).filter(project_district.c.project_id == project_id)
        if not is_master_or_admin and allowed_districts:
            districts_q = districts_q.filter(District.id.in_(list(allowed_districts)))
        districts = districts_q.order_by(District.name).all()
        form.district_id.choices = [(0, '-- All Districts --')] + [(d.id, d.name) for d in districts]
        if district_id:
            vehicles_q = Vehicle.query.filter(Vehicle.project_id == project_id, Vehicle.district_id == district_id)
        else:
            vehicles_q = Vehicle.query.filter(Vehicle.project_id == project_id)
        if not is_master_or_admin and allowed_vehicles:
            vehicles_q = vehicles_q.filter(Vehicle.id.in_(list(allowed_vehicles)))
        vehicles = vehicles_q.order_by(*vehicle_order_by()).all()
    else:
        districts_q = District.query
        if not is_master_or_admin and allowed_districts:
            districts_q = districts_q.filter(District.id.in_(list(allowed_districts)))
        form.district_id.choices = [(0, '-- All Districts --')] + [(d.id, d.name) for d in districts_q.order_by(District.name).all()]
        if district_id:
            vehicles_q = Vehicle.query.filter(Vehicle.district_id == district_id)
        else:
            vehicles_q = Vehicle.query.filter(Vehicle.project_id.isnot(None))
        if not is_master_or_admin and allowed_vehicles:
            vehicles_q = vehicles_q.filter(Vehicle.id.in_(list(allowed_vehicles)))
        vehicles = vehicles_q.order_by(*vehicle_order_by()).all()
    form.vehicle_id.choices = [(0, '-- All Vehicles --')] + [(v.id, v.vehicle_no) for v in vehicles]
    if vehicle_id and not any(v.id == vehicle_id for v in vehicles):
        v = db.session.get(Vehicle, vehicle_id)
        if v:
            form.vehicle_id.choices.append((v.id, v.vehicle_no))
    form.vehicle_id.data = vehicle_id if vehicle_id else 0
    shift_rows = db.session.query(Driver.shift).filter(Driver.shift.isnot(None), Driver.shift != '').distinct().order_by(Driver.shift).all()
    form.shift.choices = [('', '-- All Shifts --')] + [(s[0], s[0]) for s in shift_rows]
    form.shift.data = shift
    form.district_id.data = district_id if district_id else 0

    # Sirf wo records jo Mark Attendance form se mark hue (DriverAttendance table mein hain)
    # Agar from/to diya ho to date range, warna single view_date
    # Build vehicle_drivers list for driver dropdown
    vd_q = Driver.query.filter(Driver.status == 'Active', Driver.vehicle_id.isnot(None))
    if project_id:
        vd_q = vd_q.filter(Driver.project_id == project_id)
    elif not is_master_or_admin and allowed_projects:
        vd_q = vd_q.filter(Driver.project_id.in_(list(allowed_projects)))
    if district_id or (not is_master_or_admin and allowed_districts):
        vd_q = vd_q.outerjoin(Vehicle, Driver.vehicle_id == Vehicle.id)
        if district_id:
            vd_q = vd_q.filter(db.or_(Driver.district_id == district_id, Vehicle.district_id == district_id))
        elif not is_master_or_admin and allowed_districts:
            vd_q = vd_q.filter(db.or_(Driver.district_id.in_(list(allowed_districts)), Vehicle.district_id.in_(list(allowed_districts))))
    if vehicle_id:
        vd_q = vd_q.filter(Driver.vehicle_id == vehicle_id)
    if shift:
        vd_q = vd_q.filter(Driver.shift == shift)
    if not is_master_or_admin and allowed_vehicles:
        vd_q = vd_q.filter(Driver.vehicle_id.in_(list(allowed_vehicles)))
    vehicle_drivers = vd_q.order_by(Driver.name).all()

    uc = get_user_context(user_id) if user_id else {}
    attendance_rows_full = _driver_attendance_flat_rows(
        project_id,
        district_id,
        vehicle_id,
        shift,
        search,
        driver_id,
        uc,
        from_date=from_date,
        to_date=to_date,
        single_date=view_date if not from_date and not to_date else None,
    )
    if duty_shift_filter:
        attendance_rows_full = _filter_attendance_rows_by_duty_shift(attendance_rows_full, duty_shift_filter)
    if list_filter == 'missing_co':
        attendance_rows_full = [
            r for r in attendance_rows_full
            if r.get('rec') and r['rec'].check_in and not r['rec'].check_out
        ]

    att_counts = {'present': 0, 'late': 0, 'leave': 0, 'half_day': 0, 'off': 0, 'absent': 0, 'missing_co': 0}
    for row in attendance_rows_full:
        rec = row['rec']
        s = (rec.status or '').lower()
        if s == 'present':
            att_counts['present'] += 1
        elif s == 'late':
            att_counts['late'] += 1
        elif s == 'leave':
            att_counts['leave'] += 1
        elif s == 'half-day':
            att_counts['half_day'] += 1
        elif s == 'off':
            att_counts['off'] += 1
        elif s == 'absent':
            att_counts['absent'] += 1
        if rec.check_in and not rec.check_out:
            att_counts['missing_co'] += 1

    if status_filter_selected:
        attendance_rows_full = _filter_attendance_rows_by_status(attendance_rows_full, status_filter_selected)

    absent_whatsapp_rows = []
    for row in attendance_rows_full:
        rec = row.get('rec')
        if not rec or (rec.status or '') != 'Absent':
            continue
        d = row['driver']
        absent_whatsapp_rows.append({
            'vehicle': (d.vehicle.vehicle_no if d.vehicle else '-') or '-',
            'name': (d.name or '').strip(),
            'duty_shift': (row.get('duty_shift') or '-').strip() or '-',
            'phone': (d.phone1 or '').strip(),
            'date': rec.attendance_date.strftime('%d-%m-%Y') if rec.attendance_date else '',
        })

    page = request.args.get('page', 1, type=int)
    total_att = len(attendance_rows_full)
    per_page = _attendance_list_resolve_per_page(request, total_att)
    pagination = SimplePagination(attendance_rows_full, page, per_page)
    attendance_rows = pagination.items
    attendance_list_show_all = total_att > 0 and per_page >= total_att
    _perms = session.get('permissions') or []
    can_att_list_manual_checkout = user_can_access(_perms, 'driver_attendance_list_manual_checkout')
    can_att_list_manual_edit = user_can_access(_perms, 'driver_attendance_list_manual_edit')
    can_att_list_manual_delete = user_can_access(_perms, 'driver_attendance_list_manual_delete')
    return render_template(
        'driver_attendance_list.html',
        form=form,
        view_date=view_date,
        attendance_rows=attendance_rows,
        project_id=project_id,
        district_id=district_id,
        vehicle_id=vehicle_id,
        shift=shift,
        driver_id=driver_id,
        vehicle_drivers=vehicle_drivers,
        search=search,
        from_date=from_date_str,
        to_date=to_date_str,
        disable_project=disable_project,
        disable_district=disable_district,
        disable_vehicle=disable_vehicle,
        disable_shift=disable_shift,
        pagination=pagination,
        per_page=per_page,
        attendance_list_show_all=attendance_list_show_all,
        att_counts=att_counts,
        duty_shift_filter=duty_shift_filter,
        status_filter_selected=status_filter_selected,
        status_filter_options=ATTENDANCE_LIST_STATUS_FILTER_OPTIONS,
        absent_whatsapp_rows=absent_whatsapp_rows,
        list_filter=list_filter,
        can_att_list_manual_checkout=can_att_list_manual_checkout,
        can_att_list_manual_edit=can_att_list_manual_edit,
        can_att_list_manual_delete=can_att_list_manual_delete,
        **_nav_back_ctx(url_for('module_hub', hub_slug='attendance'), show_without_nav_from=True),
    )


def _attendance_media_gallery_flat_and_items_from_request():
    """Shared list filters + gallery_shift/gallery_photo for gallery, zip, and share JSON."""
    from auth_utils import get_user_context

    uid = session.get('user_id')
    uc = get_user_context(uid) if uid else {}
    view_date = _attendance_local_date()
    from_date_str = (request.args.get('from_date') or '').strip()
    to_date_str = (request.args.get('to_date') or '').strip()
    from_date = parse_date(from_date_str) if from_date_str else None
    to_date = parse_date(to_date_str) if to_date_str else None
    if request.args.get('date') and not from_date and not to_date:
        view_date = parse_date(request.args.get('date')) or view_date
        from_date = to_date = view_date

    def _iq(name):
        v = request.args.get(name)
        if v is None or v == '':
            return None
        try:
            n = int(v)
            return n if n != 0 else None
        except (TypeError, ValueError):
            return None

    project_id = _iq('project_id')
    district_id = _iq('district_id')
    vehicle_id = _iq('vehicle_id')
    driver_id = _iq('driver_id')
    shift = (request.args.get('shift') or '').strip()
    search = (request.args.get('search') or '').strip()
    duty_shift_filter = (request.args.get('duty_shift') or '').strip().lower()
    if duty_shift_filter not in ('', 'morning', 'evening'):
        duty_shift_filter = ''

    gallery_shift = (request.args.get('gallery_shift') or 'both').strip().lower()
    gallery_photo = (request.args.get('gallery_photo') or 'both').strip().lower()
    if gallery_shift not in ('morning', 'evening', 'both'):
        gallery_shift = 'both'
    if gallery_photo not in ('checkin', 'checkout', 'both'):
        gallery_photo = 'both'

    flat = _driver_attendance_flat_rows(
        project_id,
        district_id,
        vehicle_id,
        shift,
        search,
        driver_id,
        uc,
        from_date=from_date,
        to_date=to_date,
        single_date=view_date if not from_date and not to_date else None,
    )
    if duty_shift_filter:
        flat = _filter_attendance_rows_by_duty_shift(flat, duty_shift_filter)
    list_filter = (request.args.get('list_filter') or '').strip().lower()
    if list_filter == 'missing_co':
        flat = [r for r in flat if r.get('rec') and r['rec'].check_in and not r['rec'].check_out]
    status_filter_selected = _parse_attendance_status_filter_request()
    if status_filter_selected:
        flat = _filter_attendance_rows_by_status(flat, status_filter_selected)

    media_items = _build_attendance_media_gallery_items(flat, gallery_shift, gallery_photo)
    return media_items, gallery_shift, gallery_photo


@app.route('/driver-attendance/media-gallery')
def driver_attendance_media_gallery():
    """Full filtered attendance set (no pagination). page/per_page in query are ignored."""
    media_items, gallery_shift, gallery_photo = _attendance_media_gallery_flat_and_items_from_request()
    media_items_display = [{k: v for k, v in it.items() if k != 'stored_path'} for it in media_items]

    list_q = {}
    for key in ('from_date', 'to_date', 'project_id', 'district_id', 'vehicle_id', 'shift', 'driver_id', 'search', 'duty_shift'):
        val = request.args.get(key)
        if val is not None and str(val).strip() != '':
            list_q[key] = val
    back_url = url_for('driver_attendance_list', **list_q)
    qs = request.query_string.decode()
    download_all_url = url_for('driver_attendance_media_gallery_zip') + ('?' + qs if qs else '')

    if gallery_shift != 'both':
        duty_lbl = 'Morning duty' if gallery_shift == 'morning' else 'Evening duty'
        hdr_duty = 'Duty shift images: ' + duty_lbl
    else:
        hdr_duty = 'Duty shift images: Morning & Evening'
    if gallery_photo != 'both':
        hdr_photo = 'Check-in photos only' if gallery_photo == 'checkin' else 'Check-out photos only'
    else:
        hdr_photo = 'Check-in & Check-out photos'
    media_header_subline = hdr_duty + ' · ' + hdr_photo

    return render_template(
        'maintenance_expense_media.html',
        rec=None,
        media_items=media_items_display,
        media_title='Attendance Image Gallery',
        media_header_subline=media_header_subline,
        media_date_label='',
        back_url=back_url,
        back_link_label='Back to Attendance List',
        download_all_url=download_all_url,
        media_empty_hint='Is selection ke liye koi photo nahi mili — filters ya duty shift badal kar dekhein.',
    )


@app.route('/driver-attendance/media-gallery/photo-urls.json')
def driver_attendance_media_gallery_photo_urls():
    """Photo URLs for Attendance List share (full filtered set, not paginated)."""
    media_items, gallery_shift, gallery_photo = _attendance_media_gallery_flat_and_items_from_request()
    urls = []
    root = request.url_root.rstrip('/')
    for it in media_items:
        u = (it.get('download_url') or it.get('url') or '').strip()
        if not u:
            continue
        if u.startswith('http://') or u.startswith('https://'):
            urls.append(u)
        elif u.startswith('/'):
            urls.append(root + u)
        else:
            urls.append(u)
    return jsonify(
        ok=True,
        count=len(urls),
        urls=urls,
        gallery_shift=gallery_shift,
        gallery_photo=gallery_photo,
    )


@app.route('/driver-attendance/media-gallery/download-all')
def driver_attendance_media_gallery_zip():
    """ZIP of all gallery images for the same full (non-paginated) filter set."""
    from auth_utils import get_user_context

    uid = session.get('user_id')
    uc = get_user_context(uid) if uid else {}
    view_date = _attendance_local_date()
    from_date_str = (request.args.get('from_date') or '').strip()
    to_date_str = (request.args.get('to_date') or '').strip()
    from_date = parse_date(from_date_str) if from_date_str else None
    to_date = parse_date(to_date_str) if to_date_str else None
    if request.args.get('date') and not from_date and not to_date:
        view_date = parse_date(request.args.get('date')) or view_date
        from_date = to_date = view_date

    def _iq2(name):
        v = request.args.get(name)
        if v is None or v == '':
            return None
        try:
            n = int(v)
            return n if n != 0 else None
        except (TypeError, ValueError):
            return None

    project_id = _iq2('project_id')
    district_id = _iq2('district_id')
    vehicle_id = _iq2('vehicle_id')
    driver_id = _iq2('driver_id')
    shift = (request.args.get('shift') or '').strip()
    search = (request.args.get('search') or '').strip()
    duty_shift_filter = (request.args.get('duty_shift') or '').strip().lower()
    if duty_shift_filter not in ('', 'morning', 'evening'):
        duty_shift_filter = ''
    gallery_shift = (request.args.get('gallery_shift') or 'both').strip().lower()
    gallery_photo = (request.args.get('gallery_photo') or 'both').strip().lower()
    if gallery_shift not in ('morning', 'evening', 'both'):
        gallery_shift = 'both'
    if gallery_photo not in ('checkin', 'checkout', 'both'):
        gallery_photo = 'both'

    flat = _driver_attendance_flat_rows(
        project_id,
        district_id,
        vehicle_id,
        shift,
        search,
        driver_id,
        uc,
        from_date=from_date,
        to_date=to_date,
        single_date=view_date if not from_date and not to_date else None,
    )
    if duty_shift_filter:
        flat = _filter_attendance_rows_by_duty_shift(flat, duty_shift_filter)

    media_items = _build_attendance_media_gallery_items(flat, gallery_shift, gallery_photo)
    if not media_items:
        flash('Download ke liye koi photo nahi mili.', 'warning')
        q = request.query_string.decode()
        return redirect(url_for('driver_attendance_media_gallery') + ('?' + q if q else ''))

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
    zip_path = tmp.name
    tmp.close()
    used_names = set()
    added = 0
    try:
        with zipfile.ZipFile(zip_path, mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
            for idx, it in enumerate(media_items):
                path = (it.get('stored_path') or '').strip()
                if not path:
                    continue
                root = secure_filename((it.get('name') or f'photo_{idx+1}').replace(' — ', '_')) or f'photo_{idx+1}'
                ext = os.path.splitext(path)[1] or '.jpg'
                arc = f'{idx+1:04d}_{root[:100]}{ext}'
                n = 2
                while arc.lower() in used_names:
                    stem, _e = os.path.splitext(root[:80] or 'pic')
                    arc = f'{idx+1:04d}_{stem}_{n}{ext}'
                    n += 1
                used_names.add(arc.lower())
                local_full = _maintenance_attachment_local_full_path(path)
                if local_full:
                    try:
                        zf.write(local_full, arcname=arc)
                        added += 1
                        continue
                    except OSError:
                        pass
                try:
                    blob, _mime = _maintenance_attachment_read_bytes(path)
                    if blob:
                        zf.writestr(arc, blob)
                        added += 1
                except Exception:
                    pass
        if added == 0:
            try:
                os.remove(zip_path)
            except OSError:
                pass
            flash('ZIP tayar nahi ho saka (files read nahi ho saken).', 'danger')
            q = request.query_string.decode()
            return redirect(url_for('driver_attendance_media_gallery') + ('?' + q if q else ''))
    except Exception as ex:
        try:
            os.remove(zip_path)
        except OSError:
            pass
        app.logger.warning('Attendance gallery zip failed: %s', ex)
        flash('ZIP error.', 'danger')
        return redirect(url_for('driver_attendance_list'))

    @after_this_request
    def _cleanup_att_gal_zip(resp):
        try:
            os.remove(zip_path)
        except OSError:
            pass
        return resp

    d0 = from_date or view_date
    d1 = to_date or view_date
    archive_name = f'attendance_photos_{d0.strftime("%Y%m%d")}_{d1.strftime("%Y%m%d")}.zip'
    return send_file(zip_path, as_attachment=True, download_name=archive_name, mimetype='application/zip', max_age=0)


@app.route('/driver-attendance/media/item/<int:rec_id>/<kind>/download')
def driver_attendance_media_item_download(rec_id, kind):
    from auth_utils import get_user_context

    if kind not in ('checkin', 'checkout'):
        abort(404)
    uid = session.get('user_id')
    uc = get_user_context(uid) if uid else {}
    rec = DriverAttendance.query.options(
        joinedload(DriverAttendance.driver).joinedload(Driver.vehicle),
    ).get(rec_id)
    _is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or 'fetch' in (request.headers.get('Sec-Fetch-Mode') or '') or request.accept_mimetypes.accept_json
    if not rec or not rec.driver or not _driver_attendance_record_allowed_for_user(rec, uc):
        if _is_ajax:
            return jsonify(ok=False, error='Access denied'), 403
        flash('Access denied ya record nahi mila.', 'danger')
        return redirect(url_for('driver_attendance_list'))

    path = (rec.check_in_photo_path if kind == 'checkin' else rec.check_out_photo_path) or ''
    path = path.strip()
    if not path:
        if _is_ajax:
            return jsonify(ok=False, error='Photo not found'), 404
        flash('Photo maujood nahi.', 'warning')
        return redirect(url_for('driver_attendance_list'))

    d = rec.driver
    base = secure_filename(f"{rec.attendance_date.strftime('%Y%m%d')}_{d.driver_id or d.id}_{kind}") or 'attendance_photo'
    ext = os.path.splitext(path)[1] or '.jpg'
    dl_name = base + ext

    local_full = _maintenance_attachment_local_full_path(path)
    if local_full:
        return send_file(local_full, as_attachment=True, download_name=dl_name, conditional=True, max_age=0)
    try:
        blob, mime = _maintenance_attachment_read_bytes(path)
    except Exception as ex:
        app.logger.warning('Attendance media download failed (%s): %s', rec_id, ex)
        if _is_ajax:
            return jsonify(ok=False, error='Download failed'), 500
        flash('Download fail.', 'danger')
        return redirect(url_for('driver_attendance_list'))
    if not blob:
        if _is_ajax:
            return jsonify(ok=False, error='Empty file'), 404
        flash('Empty file.', 'warning')
        return redirect(url_for('driver_attendance_list'))
    return send_file(
        BytesIO(blob),
        as_attachment=True,
        download_name=dl_name,
        mimetype=mime or 'application/octet-stream',
        max_age=0,
    )


def _attendance_check_in_remarks(rec):
    """Check-in remarks: GPS+Camera auto text, else manual form reason."""
    if not rec:
        return ''
    if rec.check_in_photo_path or (rec.check_in_latitude is not None and rec.check_in_longitude is not None):
        return 'Check-in via GPS & Camera'
    r = rec.remarks or ''
    if 'Manual check-in:' in r:
        part = r.split('Manual check-in:')[1].split(' | ')[0].strip()
        return part or 'Manual check-in'
    return ''


def _attendance_check_out_remarks(rec):
    """Check-out remarks: GPS+Camera auto text, else manual form reason."""
    if not rec:
        return ''
    if rec.check_out_photo_path or (rec.check_out_latitude is not None and rec.check_out_longitude is not None):
        return 'Check-out via GPS & Camera'
    r = rec.remarks or ''
    if 'Auto check-out:' in r:
        part = r.split('Auto check-out:', 1)[1].split(' | ')[0].strip()
        return ('Auto check-out: ' + part).strip() if part else GPS_AUTO_CHECKOUT_REMARK
    if 'Manual check-out' in r:
        part = r.split('Manual check-out', 1)[1].split(' | ')[0].strip()
        if part.startswith(': '):
            part = part[2:].strip()
        return part or 'Manual check-out'
    return ''


@app.route('/driver-attendance/export')
def driver_attendance_export():
    from auth_utils import get_user_context as _guc_att_export

    view_date = _attendance_local_date()
    from_date_str = (request.args.get('from_date') or '').strip()
    to_date_str = (request.args.get('to_date') or '').strip()
    from_date = parse_date(from_date_str) if from_date_str else None
    to_date = parse_date(to_date_str) if to_date_str else None
    if request.args.get('date') and not from_date and not to_date:
        view_date = parse_date(request.args.get('date')) or view_date
        from_date = to_date = view_date
    project_id = request.args.get('project_id', type=int) or None
    district_id = request.args.get('district_id', type=int) or None
    vehicle_id = request.args.get('vehicle_id', type=int) or None
    driver_id = request.args.get('driver_id', type=int) or None
    if driver_id == 0:
        driver_id = None
    shift = (request.args.get('shift') or '').strip() or None
    search = (request.args.get('search') or '').strip()
    duty_shift_filter = (request.args.get('duty_shift') or '').strip().lower()
    if duty_shift_filter not in ('', 'morning', 'evening'):
        duty_shift_filter = ''
    uid = session.get('user_id')
    uc = _guc_att_export(uid) if uid else {}
    flat = _driver_attendance_flat_rows(
        project_id,
        district_id,
        vehicle_id,
        shift,
        search,
        driver_id,
        uc,
        from_date=from_date,
        to_date=to_date,
        single_date=view_date if not from_date and not to_date else None,
    )
    if duty_shift_filter:
        flat = _filter_attendance_rows_by_duty_shift(flat, duty_shift_filter)
    status_filter_selected = _parse_attendance_status_filter_request()
    list_filter = (request.args.get('list_filter') or '').strip().lower()
    if list_filter == 'missing_co':
        flat = [r for r in flat if r.get('rec') and r['rec'].check_in and not r['rec'].check_out]
    if status_filter_selected:
        flat = _filter_attendance_rows_by_status(flat, status_filter_selected)
    headers = [
        'S.No',
        'Date',
        'Driver ID',
        'Name',
        'Project / District / Parking',
        'Vehicle No',
        'Vehicle Type',
        'Assigned shift',
        'Duty shift',
        'Status',
        'Check In',
        'Check In Photo',
        'Check In Remarks',
        'Check Out',
        'Check Out Photo',
        'Check Out Remarks',
    ]
    rows = []
    for i, item in enumerate(flat, 1):
        d = item['driver']
        rec = item['rec']
        duty = item.get('duty_shift') or '-'
        district_name = d.district.name if d.district else (d.vehicle.district.name if d.vehicle and d.vehicle.district else '-')
        parking_name = d.vehicle.parking_station.name if d.vehicle and d.vehicle.parking_station else '-'
        project_district_parking = f"{(d.project.name if d.project else '-')} / {district_name} / {parking_name}"
        ad = rec.attendance_date.strftime('%Y-%m-%d') if rec else '-'
        rows.append([
            i,
            ad,
            d.driver_id or '-',
            d.name or '',
            project_district_parking,
            d.vehicle.vehicle_no if d.vehicle else '-',
            (d.vehicle.vehicle_type if d.vehicle else '') or '-',
            d.shift or '-',
            duty,
            rec.status if rec else '-',
            format_time_ampm(rec.check_in) if rec and rec.check_in else '-',
            'Yes' if rec and rec.check_in_photo_path else '-',
            _attendance_check_in_remarks(rec) or '-',
            (
                format_time_ampm(rec.check_out)
                + (
                    ' (' + rec.check_out_date.strftime('%d-%m-%Y') + ')'
                    if rec.check_out_date and rec.check_out_date != rec.attendance_date
                    else ''
                )
            )
            if rec and rec.check_out
            else '-',
            'Yes' if rec and rec.check_out_photo_path else '-',
            _attendance_check_out_remarks(rec) or '-',
        ])
    if flat:
        d0 = flat[0]['rec'].attendance_date
        d1 = flat[-1]['rec'].attendance_date
    else:
        d0 = d1 = view_date
    filename = f'driver_attendance_{d0.strftime("%Y%m%d")}_{d1.strftime("%Y%m%d")}.xlsx'
    return generate_excel_template(headers, rows, required_columns=[], filename=filename)


@app.route('/driver-attendance/print')
def driver_attendance_print():
    from auth_utils import get_user_context as _guc_att_print

    view_date = _attendance_local_date()
    from_date_str = (request.args.get('from_date') or '').strip()
    to_date_str = (request.args.get('to_date') or '').strip()
    from_date = parse_date(from_date_str) if from_date_str else None
    to_date = parse_date(to_date_str) if to_date_str else None
    if request.args.get('date') and not from_date and not to_date:
        view_date = parse_date(request.args.get('date')) or view_date
        from_date = to_date = view_date
    project_id = request.args.get('project_id', type=int) or None
    district_id = request.args.get('district_id', type=int) or None
    vehicle_id = request.args.get('vehicle_id', type=int) or None
    driver_id = request.args.get('driver_id', type=int) or None
    if driver_id == 0:
        driver_id = None
    shift = (request.args.get('shift') or '').strip() or None
    search = (request.args.get('search') or '').strip()
    duty_shift_filter = (request.args.get('duty_shift') or '').strip().lower()
    if duty_shift_filter not in ('', 'morning', 'evening'):
        duty_shift_filter = ''
    uid = session.get('user_id')
    uc = _guc_att_print(uid) if uid else {}
    attendance_rows = _driver_attendance_flat_rows(
        project_id,
        district_id,
        vehicle_id,
        shift,
        search,
        driver_id,
        uc,
        from_date=from_date,
        to_date=to_date,
        single_date=view_date if not from_date and not to_date else None,
    )
    if duty_shift_filter:
        attendance_rows = _filter_attendance_rows_by_duty_shift(attendance_rows, duty_shift_filter)
    list_filter = (request.args.get('list_filter') or '').strip().lower()
    if list_filter == 'missing_co':
        attendance_rows = [
            r for r in attendance_rows
            if r.get('rec') and r['rec'].check_in and not r['rec'].check_out
        ]
    status_filter_selected = _parse_attendance_status_filter_request()
    if status_filter_selected:
        attendance_rows = _filter_attendance_rows_by_status(attendance_rows, status_filter_selected)
    return render_template(
        'driver_attendance_print.html',
        attendance_rows=attendance_rows,
        view_date=view_date,
        from_date=from_date_str,
        to_date=to_date_str,
        project_id=project_id,
        district_id=district_id,
        vehicle_id=vehicle_id,
        shift=shift,
        search=search,
        driver_id=driver_id,
    )


@app.route('/driver-attendance/mark/clear', methods=['POST'])
def driver_attendance_mark_clear():
    """Remove mistaken manual status (Leave/Late/Half-Day/Off/Absent) from mark form."""
    from auth_utils import get_user_context

    if not user_can_access(session.get('permissions') or [], 'driver_attendance_mark'):
        flash('Access denied.', 'danger')
        return redirect(url_for('driver_attendance_list'))

    uid = session.get('user_id')
    uc = get_user_context(uid) if uid else {}
    back_url = _driver_attendance_mark_redirect_url()

    attendance_id = request.form.get('attendance_id', type=int)
    if not attendance_id:
        flash('Invalid request.', 'danger')
        return redirect(back_url)

    rec = DriverAttendance.query.options(joinedload(DriverAttendance.driver)).get(attendance_id)
    if not rec:
        flash('Attendance record nahi mila.', 'danger')
        return redirect(back_url)
    if not _driver_attendance_record_allowed_for_user(rec, uc):
        flash('Access denied.', 'danger')
        return redirect(back_url)
    if not _attendance_mark_record_clearable(rec):
        flash(
            'Ye entry delete nahi ho sakti — GPS/Camera check-in hai ya photo/GPS data maujood hai. '
            'Attendance List se check-in delete karein, ya status change karein.',
            'warning',
        )
        return redirect(back_url)

    driver_name = rec.driver.name if rec.driver else 'Driver'
    status_was = rec.status or ''
    att_date = rec.attendance_date
    try:
        _delete_stored_attendance_photo(rec.check_in_photo_path)
        _delete_stored_attendance_photo(rec.check_out_photo_path)
        db.session.delete(rec)
        db.session.commit()
        flash(
            f'{driver_name} ki {att_date.strftime("%d-%m-%Y")} wali {status_was} entry hata di gayi.',
            'success',
        )
    except Exception as e:
        db.session.rollback()
        flash(f'Error: {str(e)}', 'danger')
    return redirect(back_url)


@app.route('/driver-attendance/mark', methods=['GET', 'POST'])
def driver_attendance_mark():
    form = DriverAttendanceFilterForm()
    scope_projects, scope_districts, scope_vehicles, scope_shifts = _get_user_scope()
    project_query = Project.query.filter(Project.company_id.isnot(None)).order_by(Project.name)
    if scope_projects:
        project_query = project_query.filter(Project.id.in_(scope_projects))
    form.project_id.choices = [(0, '-- All Projects --')] + [(p.id, p.name) for p in project_query.all()]
    has_single_scope = bool(
        scope_projects and len(scope_projects) == 1 and
        scope_districts and len(scope_districts) == 1 and
        scope_vehicles and len(scope_vehicles) == 1 and
        scope_shifts and len(scope_shifts) == 1
    )
    view_date = _attendance_local_date()
    project_id = request.args.get('project_id', type=int) or request.form.get('project_id', type=int)
    district_id = request.args.get('district_id', type=int) or request.form.get('district_id', type=int)
    vehicle_id = request.args.get('vehicle_id', type=int) or request.form.get('vehicle_id', type=int)
    shift = (request.args.get('shift') or request.form.get('shift') or '').strip()
    driver_id = request.args.get('driver_id', type=int) or request.form.get('driver_id', type=int)
    search = (request.args.get('search') or request.form.get('search') or '').strip()
    
    # Auto-select if only 1 option available
    disable_project = False
    disable_district = False
    if scope_projects and len(scope_projects) == 1:
        if not project_id or project_id == 0:
            project_id = next(iter(scope_projects))
        disable_project = True
    if scope_districts and len(scope_districts) == 1:
        if not district_id or district_id == 0:
            district_id = next(iter(scope_districts))
        disable_district = True
    
    if project_id == 0:
        project_id = None
    if district_id == 0:
        district_id = None
    if vehicle_id == 0:
        vehicle_id = None
    if driver_id == 0:
        driver_id = None
    if request.args.get('date'):
        view_date = parse_date(request.args.get('date')) or view_date
    if request.method == 'POST' and request.form.get('attendance_date'):
        candidate = parse_date(request.form.get('attendance_date')) or view_date
        # Future date par Leave / Late / Half-Day / Off ya koi bhi manual status allow na karein
        if candidate and candidate > _attendance_local_date():
            flash('Attendance status cannot be marked for a future date.', 'danger')
            return redirect(url_for('driver_attendance_mark', date=_attendance_local_date().strftime('%d-%m-%Y'), project_id=project_id or '', district_id=district_id or '', vehicle_id=vehicle_id or '', shift=shift or '', driver_id=driver_id or '', search=search))
        view_date = candidate
        project_id = request.form.get('project_id', type=int) or None
        if project_id == 0:
            project_id = None
        district_id = request.form.get('district_id', type=int) or None
        if district_id == 0:
            district_id = None
        vehicle_id = request.form.get('vehicle_id', type=int) or None
        if vehicle_id == 0:
            vehicle_id = None
        shift = (request.form.get('shift') or '').strip()
        driver_id = request.form.get('driver_id', type=int) or None
        if driver_id == 0:
            driver_id = None
    if request.method == 'GET' and form.validate_on_submit():
        view_date = form.attendance_date.data
        project_id = form.project_id.data if form.project_id.data else None
        if project_id == 0:
            project_id = None
        district_id = form.district_id.data if form.district_id.data else None
        if district_id == 0:
            district_id = None
        vehicle_id = request.args.get('vehicle_id', type=int) or None
        if vehicle_id == 0:
            vehicle_id = None
        shift = (request.args.get('shift') or '').strip()
        driver_id = request.args.get('driver_id', type=int) or None
        if driver_id == 0:
            driver_id = None
        return redirect(url_for('driver_attendance_mark', date=view_date.strftime('%d-%m-%Y'), project_id=project_id or '', district_id=district_id or '', vehicle_id=request.args.get('vehicle_id') or '', shift=request.args.get('shift') or '', driver_id=request.args.get('driver_id') or '', search=search))
    if request.method == 'GET':
        form.attendance_date.data = view_date
        form.project_id.data = project_id if project_id else 0
    if project_id and project_id != 0:
        districts_query = District.query.join(project_district).filter(project_district.c.project_id == project_id).order_by(District.name)
        if scope_districts:
            districts_query = districts_query.filter(District.id.in_(scope_districts))
        districts = districts_query.all()
        form.district_id.choices = [(0, '-- All Districts --')] + [(d.id, d.name) for d in districts]
    else:
        districts_query = District.query.order_by(District.name)
        if scope_districts:
            districts_query = districts_query.filter(District.id.in_(scope_districts))
        form.district_id.choices = [(0, '-- All Districts --')] + [(d.id, d.name) for d in districts_query.all()]
    if request.method == 'GET':
        form.district_id.data = district_id if district_id else 0
    vehicles = []
    if project_id and district_id:
        vq = Vehicle.query.filter(Vehicle.project_id == project_id, Vehicle.district_id == district_id)
        if scope_vehicles:
            vq = vq.filter(Vehicle.id.in_(scope_vehicles))
        if scope_projects:
            vq = vq.filter(Vehicle.project_id.in_(scope_projects))
        if scope_districts:
            vq = vq.filter(Vehicle.district_id.in_(scope_districts))
        vehicles = vq.order_by(*vehicle_order_by()).all()
    elif project_id:
        vq = Vehicle.query.filter(Vehicle.project_id == project_id)
        if scope_vehicles:
            vq = vq.filter(Vehicle.id.in_(scope_vehicles))
        if scope_districts:
            vq = vq.filter(Vehicle.district_id.in_(scope_districts))
        vehicles = vq.order_by(*vehicle_order_by()).all()
    elif district_id:
        vq = Vehicle.query.filter(Vehicle.district_id == district_id)
        if scope_vehicles:
            vq = vq.filter(Vehicle.id.in_(scope_vehicles))
        if scope_projects:
            vq = vq.filter(Vehicle.project_id.in_(scope_projects))
        vehicles = vq.order_by(*vehicle_order_by()).all()
    else:
        vq = Vehicle.query.filter(Vehicle.project_id.isnot(None))
        if scope_vehicles:
            vq = vq.filter(Vehicle.id.in_(scope_vehicles))
        if scope_projects:
            vq = vq.filter(Vehicle.project_id.in_(scope_projects))
        if scope_districts:
            vq = vq.filter(Vehicle.district_id.in_(scope_districts))
        vehicles = vq.order_by(*vehicle_order_by()).all()
    drivers_query = Driver.query.filter(
        Driver.status == 'Active',
        Driver.vehicle_id.isnot(None),
    ).outerjoin(Vehicle, Driver.vehicle_id == Vehicle.id)
    if scope_projects:
        drivers_query = drivers_query.filter(
            db.or_(Driver.project_id.in_(scope_projects),
                   Vehicle.project_id.in_(scope_projects))
        )
    if scope_districts:
        drivers_query = drivers_query.filter(
            db.or_(Driver.district_id.in_(scope_districts),
                   Vehicle.district_id.in_(scope_districts))
        )
    if scope_vehicles:
        drivers_query = drivers_query.filter(Driver.vehicle_id.in_(scope_vehicles))
    if scope_shifts:
        drivers_query = drivers_query.filter(Driver.shift.in_(scope_shifts))
    if project_id:
        drivers_query = drivers_query.filter(
            db.or_(Driver.project_id == project_id, Vehicle.project_id == project_id)
        )
    if district_id:
        drivers_query = drivers_query.filter(
            db.or_(Driver.district_id == district_id, Vehicle.district_id == district_id)
        )
    if vehicle_id:
        drivers_query = drivers_query.filter(Driver.vehicle_id == vehicle_id)
    if shift:
        drivers_query = drivers_query.filter(Driver.shift == shift)
    if search:
        flt = _multi_word_filter(search, Driver.name, Driver.driver_id, Vehicle.vehicle_no)
        if flt is not None:
            drivers_query = drivers_query.filter(flt)
    vehicle_drivers = drivers_query.distinct().order_by(Driver.name).all()
    if driver_id:
        drivers_query = drivers_query.filter(Driver.id == driver_id)
    drivers = drivers_query.order_by(Driver.name).all()
    existing = {}
    for a in (
        DriverAttendance.query.filter_by(attendance_date=view_date)
        .order_by(DriverAttendance.driver_id.asc(), DriverAttendance.attendance_segment.asc())
        .all()
    ):
        existing.setdefault(a.driver_id, a)
    if request.method == 'POST' and request.form.get('save_attendance'):
        gps_cam_remark = 'Ye GPS + Camera se attendance lagi hai.'
        for d in drivers:
            did = d.id
            rec = existing.get(did)
            if rec and rec.remarks and gps_cam_remark in (rec.remarks or ''):
                continue
            status = request.form.get(f'driver_{did}_status', '').strip()
            if not status:
                continue
            check_in_s = request.form.get(f'driver_{did}_check_in', '')
            check_out_s = request.form.get(f'driver_{did}_check_out', '')
            reason_code = request.form.get(f'driver_{did}_reason', '').strip()
            user_remarks = request.form.get(f'driver_{did}_remarks', '').strip()
            _audit_user = session.get('user', '')
            remarks_parts = []
            if reason_code:
                remarks_parts.append(reason_code)
            if user_remarks:
                remarks_parts.append(user_remarks)
            remarks = ' | '.join(remarks_parts) if remarks_parts else 'Manual entry form ki entry'
            if _audit_user:
                remarks += f' [by {_audit_user}]'
            check_in_t = None
            check_out_t = None
            if check_in_s:
                try:
                    parts = check_in_s.strip().split(':')
                    if len(parts) >= 2:
                        check_in_t = time(int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0)
                except (ValueError, IndexError):
                    pass
            if check_out_s:
                try:
                    parts = check_out_s.strip().split(':')
                    if len(parts) >= 2:
                        check_out_t = time(int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0)
                except (ValueError, IndexError):
                    pass
            photo_path = None
            photo = request.files.get(f'driver_{did}_photo')
            if photo and photo.filename:
                try:
                    # Upload resized/compressed image to Cloudflare R2 (no local disk usage)
                    photo.stream.seek(0)
                    photo_path = upload_image_file(photo, folder="attendance")
                except Exception:
                    # Agar R2 upload fail ho jaye to silently ignore (status phir bhi save ho jaye)
                    photo_path = None
            if rec:
                if rec.check_in is not None and not check_in_t:
                    check_in_t = rec.check_in
                if rec.check_out is not None and not check_out_t:
                    check_out_t = rec.check_out
                rec.status = status
                rec.check_in = check_in_t
                rec.check_out = check_out_t
                rec.check_out_date = view_date if check_out_t else rec.check_out_date
                if not rec.remarks or 'GPS' not in rec.remarks:
                    rec.remarks = remarks
                rec.project_id = project_id
                rec.updated_at = pk_now()
                if photo_path:
                    rec.check_in_photo_path = photo_path
            else:
                rec = DriverAttendance(
                    driver_id=did, attendance_date=view_date, status=status,
                    check_in=check_in_t, check_out=check_out_t,
                    check_out_date=view_date if check_out_t else None,
                    remarks=remarks,
                    project_id=project_id, check_in_photo_path=photo_path
                )
                db.session.add(rec)
        try:
            db.session.commit()
            flash('Status saved successfully.', 'success')
            return redirect(url_for('driver_attendance_list', date=view_date.strftime('%d-%m-%Y'), project_id=project_id or '', district_id=district_id or '', search=search))
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {str(e)}', 'danger')
    # ── Build 7-day mini status history per driver ──
    driver_history = {}
    if drivers:
        _hist_ids = [d.id for d in drivers]
        _hist_start = view_date - timedelta(days=7)
        _hist_recs = DriverAttendance.query.filter(
            DriverAttendance.driver_id.in_(_hist_ids),
            DriverAttendance.attendance_date >= _hist_start,
            DriverAttendance.attendance_date < view_date,
        ).all()
        _hist_map = {}
        for hr in _hist_recs:
            _hist_map.setdefault(hr.driver_id, {})[hr.attendance_date] = hr
        _status_cls = {'Present': 'present', 'Late': 'late', 'Leave': 'leave',
                       'Half-Day': 'half', 'Off': 'off', 'Absent': 'absent'}
        _status_label = {'Present': 'P', 'Late': 'L', 'Leave': 'Lv', 'Half-Day': 'H', 'Off': 'O', 'Absent': 'A'}
        for did in _hist_ids:
            days = []
            for i in range(7, 0, -1):
                dt = view_date - timedelta(days=i)
                rec_h = _hist_map.get(did, {}).get(dt)
                if rec_h:
                    st = rec_h.status or 'Present'
                    days.append({'date': dt.strftime('%d-%m'), 'status': st,
                                 'cls': _status_cls.get(st, 'none'), 'label': _status_label.get(st, '?')})
                else:
                    days.append({'date': dt.strftime('%d-%m'), 'status': 'No Record', 'cls': 'none', 'label': '-'})
            driver_history[did] = days

    mark_clearable = {d.id: _attendance_mark_record_clearable(existing.get(d.id)) for d in drivers}
    return render_template(
        'driver_attendance_mark.html',
        form=form,
        view_date=view_date,
        drivers=drivers,
        existing=existing,
        project_id=project_id,
        district_id=district_id,
        vehicle_id=vehicle_id,
        shift=shift,
        driver_id=driver_id,
        search=search,
        status_choices=ATTENDANCE_STATUS_CHOICES,
        vehicles=vehicles,
        vehicle_drivers=vehicle_drivers,
        has_single_scope=has_single_scope,
        disable_project=disable_project,
        disable_district=disable_district,
        driver_history=driver_history,
        mark_clearable=mark_clearable,
        **_nav_back_ctx(_driver_attendance_mark_redirect_url(), show_without_nav_from=True),
    )


@app.route('/driver-attendance/bulk-off', methods=['GET', 'POST'])
def driver_attendance_bulk_off():
    """Bulk Status: Select District + Project + Date range, mark drivers Off/Leave/Half-Day."""
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)

    districts_q = District.query.join(project_district, District.id == project_district.c.district_id).distinct()
    if not is_master_or_admin and allowed_districts:
        districts_q = districts_q.filter(District.id.in_(list(allowed_districts)))
    districts = districts_q.order_by(District.name).all()

    today = _attendance_local_date()
    view_date = today
    district_id = request.args.get('district_id', type=int) or request.form.get('district_id', type=int)
    project_id = request.args.get('project_id', type=int) or request.form.get('project_id', type=int)

    from_date_str = request.args.get('from_date') or request.args.get('date') or ''
    to_date_str = request.args.get('to_date') or ''
    from_date_parsed = parse_date(from_date_str) if from_date_str else None
    to_date_parsed = parse_date(to_date_str) if to_date_str else None
    if from_date_parsed:
        view_date = from_date_parsed

    if request.form.get('bulk_off_from_date'):
        from_date_parsed = parse_date(request.form.get('bulk_off_from_date')) or today
        view_date = from_date_parsed
    if request.form.get('bulk_off_to_date'):
        to_date_parsed = parse_date(request.form.get('bulk_off_to_date')) or from_date_parsed or today

    if district_id == 0:
        district_id = None
    if project_id == 0:
        project_id = None

    disable_district = False
    disable_project = False
    if not is_master_or_admin:
        if len(allowed_districts) == 1:
            if district_id is None:
                district_id = next(iter(allowed_districts))
            disable_district = True
        if len(allowed_projects) == 1:
            if project_id is None:
                project_id = next(iter(allowed_projects))
            disable_project = True
    projects = []
    if district_id:
        proj_q = Project.query.join(project_district).filter(project_district.c.district_id == district_id)
        if not is_master_or_admin and allowed_projects:
            proj_q = proj_q.filter(Project.id.in_(list(allowed_projects)))
        projects = proj_q.order_by(Project.name).all()
    else:
        proj_q = Project.query
        if not is_master_or_admin and allowed_projects:
            proj_q = proj_q.filter(Project.id.in_(list(allowed_projects)))
        projects = proj_q.order_by(Project.name).all()

    drivers_query = Driver.query.filter(
        Driver.status == 'Active',
        Driver.vehicle_id.isnot(None),
    )
    if project_id:
        drivers_query = drivers_query.filter(Driver.project_id == project_id)
    elif not is_master_or_admin and allowed_projects:
        drivers_query = drivers_query.filter(Driver.project_id.in_(list(allowed_projects)))
    if district_id:
        drivers_query = drivers_query.filter(
            db.or_(
                Driver.district_id == district_id,
                Driver.district_id.is_(None),
            )
        )
    elif not is_master_or_admin and allowed_districts:
        drivers_query = drivers_query.outerjoin(Vehicle, Driver.vehicle_id == Vehicle.id).filter(
            db.or_(Driver.district_id.in_(list(allowed_districts)), Vehicle.district_id.in_(list(allowed_districts)))
        )
    all_drivers = drivers_query.order_by(Driver.name).all()
    existing_att_ids = {a.driver_id for a in DriverAttendance.query.filter_by(attendance_date=view_date).all()}
    drivers = [d for d in all_drivers if d.id not in existing_att_ids]

    # ── Undo handler ──
    if request.method == 'POST' and request.form.get('undo_bulk'):
        _audit_user = session.get('user', '')
        undo_tag = f'Bulk [by {_audit_user}]' if _audit_user else 'Bulk'
        recent = DriverAttendance.query.filter(
            DriverAttendance.remarks.ilike(f'%{undo_tag}%'),
            DriverAttendance.check_in.is_(None),
        ).order_by(DriverAttendance.updated_at.desc()).limit(500).all()
        if not recent:
            recent = DriverAttendance.query.filter(
                DriverAttendance.remarks.ilike('%Bulk%'),
                DriverAttendance.check_in.is_(None),
            ).order_by(DriverAttendance.updated_at.desc()).limit(500).all()
        if recent:
            last_ts = recent[0].updated_at
            undo_count = 0
            for r in recent:
                if last_ts and r.updated_at and abs((last_ts - r.updated_at).total_seconds()) < 120:
                    db.session.delete(r)
                    undo_count += 1
            try:
                db.session.commit()
                flash(f'{undo_count} bulk record(s) undo kar diye gaye.', 'success')
            except Exception as e:
                db.session.rollback()
                flash(f'Undo error: {str(e)}', 'danger')
        else:
            flash('Koi recent bulk action nahi mili undo karne ke liye.', 'warning')
        return redirect(url_for('driver_attendance_bulk_off',
                                from_date=view_date.strftime('%d-%m-%Y'),
                                district_id=district_id or '', project_id=project_id or ''))

    # ── Main bulk mark handler (date range + status choice) ──
    if request.method == 'POST' and request.form.get('confirm_bulk_off'):
        bulk_status = request.form.get('bulk_status', 'Off').strip() or 'Off'
        _bulk_allowed = {v for v, _ in ATTENDANCE_STATUS_CHOICES}
        if bulk_status not in _bulk_allowed:
            bulk_status = 'Off'

        start_d = from_date_parsed or view_date
        end_d = to_date_parsed or start_d
        if end_d < start_d:
            end_d = start_d
        if start_d > today:
            flash('Future date ke liye Bulk status nahi laga sakte.', 'danger')
            return redirect(url_for('driver_attendance_bulk_off',
                                    from_date=today.strftime('%d-%m-%Y'),
                                    district_id=district_id or '', project_id=project_id or ''))
        if end_d > today:
            end_d = today
        max_range = 30
        if (end_d - start_d).days > max_range:
            flash(f'Maximum {max_range} din ka range select kar sakte hain.', 'danger')
            return redirect(url_for('driver_attendance_bulk_off',
                                    from_date=start_d.strftime('%d-%m-%Y'), to_date=end_d.strftime('%d-%m-%Y'),
                                    district_id=district_id or '', project_id=project_id or ''))

        selected_ids = set()
        for v in request.form.getlist('selected_drivers'):
            try:
                selected_ids.add(int(v))
            except (ValueError, TypeError):
                pass
        if not selected_ids:
            flash('Kam az kam ek driver select karein.', 'warning')
            return redirect(url_for('driver_attendance_bulk_off',
                                    from_date=view_date.strftime('%d-%m-%Y'),
                                    district_id=district_id or '', project_id=project_id or ''))

        total_count = 0
        total_skipped = 0
        _audit_user = session.get('user', '')
        _bulk_tag = f'Bulk {bulk_status} [by {_audit_user}]' if _audit_user else f'Bulk {bulk_status}'
        cur_d = start_d
        while cur_d <= end_d:
            for d in all_drivers:
                if d.id not in selected_ids:
                    continue
                any_ci = (
                    db.session.query(DriverAttendance.id)
                    .filter(
                        DriverAttendance.driver_id == d.id,
                        DriverAttendance.attendance_date == cur_d,
                        DriverAttendance.check_in.isnot(None),
                    )
                    .first()
                )
                if any_ci:
                    total_skipped += 1
                    continue
                rec = (
                    DriverAttendance.query.filter_by(driver_id=d.id, attendance_date=cur_d)
                    .order_by(DriverAttendance.attendance_segment.asc())
                    .first()
                )
                if rec:
                    rec.status = bulk_status
                    rec.check_in = None
                    rec.check_out = None
                    rec.check_out_date = None
                    rec.remarks = (rec.remarks or '').rstrip() + (' | ' + _bulk_tag if (rec.remarks or '').strip() else _bulk_tag)
                    rec.updated_at = pk_now()
                else:
                    rec = DriverAttendance(
                        driver_id=d.id,
                        attendance_date=cur_d,
                        status=bulk_status,
                        project_id=d.project_id,
                        remarks=_bulk_tag,
                    )
                    db.session.add(rec)
                total_count += 1
            cur_d += timedelta(days=1)
        try:
            db.session.commit()
            date_label = start_d.strftime('%d-%m-%Y')
            if end_d != start_d:
                date_label += f' to {end_d.strftime("%d-%m-%Y")}'
            msg = f'{total_count} record(s) ko {date_label} ke liye {bulk_status} mark kar diya gaya.'
            if total_skipped:
                msg += f' {total_skipped} skip kiye gaye (GPS/Manual check-in already recorded).'
            flash(msg, 'success')
            return redirect(url_for('driver_attendance_bulk_off',
                                    from_date=start_d.strftime('%d-%m-%Y'), to_date=end_d.strftime('%d-%m-%Y'),
                                    district_id=district_id or '', project_id=project_id or ''))
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {str(e)}', 'danger')

    # ── Build history log + last action for undo strip ──
    last_bulk_action = None
    bulk_history = []
    _bulk_recs = DriverAttendance.query.filter(
        DriverAttendance.remarks.ilike('%Bulk%'),
    ).order_by(DriverAttendance.updated_at.desc()).limit(500).all()
    if _bulk_recs:
        from collections import defaultdict
        _groups = defaultdict(lambda: {'count': 0, 'status': '', 'date': '', 'user': '', 'ts': None})
        for br in _bulk_recs:
            _rm = br.remarks or ''
            _u = ''
            if '[by ' in _rm:
                _u = _rm.split('[by ')[-1].rstrip(']').strip()
            _key = f'{br.attendance_date}|{br.status}|{_u}'
            g = _groups[_key]
            g['count'] += 1
            g['status'] = br.status or 'Off'
            g['date'] = br.attendance_date.strftime('%d-%m-%Y') if br.attendance_date else ''
            g['user'] = _u or 'System'
            if g['ts'] is None or (br.updated_at and br.updated_at > g['ts']):
                g['ts'] = br.updated_at
        _sorted = sorted(_groups.values(), key=lambda x: x['ts'] or datetime.min, reverse=True)
        for i, g in enumerate(_sorted[:10]):
            ago_str = ''
            if g['ts']:
                _delta = pk_now() - g['ts']
                if _delta.days > 0:
                    ago_str = f"{_delta.days}d ago"
                elif _delta.seconds >= 3600:
                    ago_str = f"{_delta.seconds // 3600}h ago"
                else:
                    ago_str = f"{max(1, _delta.seconds // 60)}m ago"
            entry = {'count': g['count'], 'status': g['status'], 'date': g['date'], 'user': g['user'], 'ago': ago_str}
            if i == 0:
                last_bulk_action = entry
            bulk_history.append(entry)

    return render_template(
        'driver_attendance_bulk_off.html',
        districts=districts,
        projects=projects,
        drivers=drivers,
        view_date=view_date,
        from_date=from_date_str or view_date.strftime('%d-%m-%Y'),
        to_date=to_date_str or view_date.strftime('%d-%m-%Y'),
        district_id=district_id,
        project_id=project_id,
        disable_district=disable_district,
        disable_project=disable_project,
        last_bulk_action=last_bulk_action,
        bulk_history=bulk_history,
        status_choices=ATTENDANCE_STATUS_CHOICES,
        **_nav_back_ctx(url_for('driver_attendance_list'), show_without_nav_from=True),
    )


@app.route('/driver-attendance/pending', methods=['GET'])
def driver_attendance_pending():
    """Report: same filters as Mark Attendance, but list only drivers who have NOT marked attendance for the selected date."""
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    allowed_shifts = user_context.get('allowed_shifts', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)

    form = DriverAttendanceFilterForm()
    proj_q = Project.query.filter(Project.company_id.isnot(None))
    if not is_master_or_admin and allowed_projects:
        proj_q = proj_q.filter(Project.id.in_(list(allowed_projects)))
    form.project_id.choices = [(0, '-- All Projects --')] + [(p.id, p.name) for p in proj_q.order_by(Project.name).all()]
    view_date = _attendance_local_date()
    if request.args.get('date'):
        view_date = parse_date(request.args.get('date')) or view_date
    project_id = request.args.get('project_id', type=int) or None
    district_id = request.args.get('district_id', type=int) or None
    vehicle_id = request.args.get('vehicle_id', type=int) or None
    shift = (request.args.get('shift') or '').strip()
    driver_id = request.args.get('driver_id', type=int) or None
    search = (request.args.get('search') or '').strip()
    duty_shift_filter = _parse_duty_shift_filter_request()
    if project_id == 0: project_id = None
    if district_id == 0: district_id = None
    if vehicle_id == 0: vehicle_id = None
    if driver_id == 0: driver_id = None
    # Auto-select & disable if only 1 option allowed
    disable_project = False
    disable_district = False
    disable_vehicle = False
    disable_shift = False
    if not is_master_or_admin:
        if len(allowed_projects) == 1:
            if project_id is None:
                project_id = next(iter(allowed_projects))
            disable_project = True
        if len(allowed_districts) == 1:
            if district_id is None:
                district_id = next(iter(allowed_districts))
            disable_district = True
        if len(allowed_vehicles) == 1:
            if vehicle_id is None:
                vehicle_id = next(iter(allowed_vehicles))
            disable_vehicle = True
        if len(allowed_shifts) == 1:
            if not shift:
                shift = next(iter(allowed_shifts))
            disable_shift = True
    form.attendance_date.data = view_date
    form.project_id.data = project_id if project_id else 0
    if project_id and project_id != 0:
        dist_q = District.query.join(project_district).filter(project_district.c.project_id == project_id)
        if not is_master_or_admin and allowed_districts:
            dist_q = dist_q.filter(District.id.in_(list(allowed_districts)))
        form.district_id.choices = [(0, '-- All Districts --')] + [(d.id, d.name) for d in dist_q.order_by(District.name).all()]
    else:
        dist_q = District.query
        if not is_master_or_admin and allowed_districts:
            dist_q = dist_q.filter(District.id.in_(list(allowed_districts)))
        form.district_id.choices = [(0, '-- All Districts --')] + [(d.id, d.name) for d in dist_q.order_by(District.name).all()]
    form.district_id.data = district_id if district_id else 0
    vehicles = []
    if project_id and district_id:
        vehicles = Vehicle.query.filter(Vehicle.project_id == project_id, Vehicle.district_id == district_id).order_by(*vehicle_order_by()).all()
    elif project_id:
        vehicles = Vehicle.query.filter(Vehicle.project_id == project_id).order_by(*vehicle_order_by()).all()
    elif district_id:
        vehicles = Vehicle.query.filter(Vehicle.district_id == district_id).order_by(*vehicle_order_by()).all()
    else:
        veh_q = Vehicle.query.filter(Vehicle.project_id.isnot(None))
        if not is_master_or_admin and allowed_projects:
            veh_q = veh_q.filter(Vehicle.project_id.in_(list(allowed_projects)))
        vehicles = veh_q.order_by(*vehicle_order_by()).all()
    drivers_query = Driver.query.filter(Driver.status == 'Active').filter(Driver.vehicle_id.isnot(None))
    if project_id:
        drivers_query = drivers_query.filter(Driver.project_id == project_id)
    elif not is_master_or_admin and allowed_projects:
        drivers_query = drivers_query.filter(Driver.project_id.in_(list(allowed_projects)))
    need_vehicle_join_pending = bool(district_id or search or (not is_master_or_admin and allowed_districts))
    if need_vehicle_join_pending:
        drivers_query = drivers_query.outerjoin(Vehicle, Driver.vehicle_id == Vehicle.id)
    if district_id:
        drivers_query = drivers_query.filter(
            db.or_(Driver.district_id == district_id, Vehicle.district_id == district_id)
        )
    elif not is_master_or_admin and allowed_districts:
        drivers_query = drivers_query.filter(
            db.or_(Driver.district_id.in_(list(allowed_districts)), Vehicle.district_id.in_(list(allowed_districts)))
        )
    if vehicle_id:
        drivers_query = drivers_query.filter(Driver.vehicle_id == vehicle_id)
    if shift:
        drivers_query = drivers_query.filter(Driver.shift == shift)
    if search:
        flt = _multi_word_filter(search, Driver.name, Driver.driver_id, Vehicle.vehicle_no)
        if flt is not None:
            drivers_query = drivers_query.filter(flt)
    drivers_query = drivers_query.options(joinedload(Driver.vehicle))
    vehicle_drivers = drivers_query.order_by(Driver.name).all()
    if driver_id:
        drivers_query = drivers_query.filter(Driver.id == driver_id)
    all_filtered_drivers = drivers_query.order_by(Driver.name).all()
    checked_in_vehicle_count = len(_get_checked_in_vehicle_ids(view_date))
    pending_rows = []
    for d in all_filtered_drivers:
        if _driver_excluded_from_missing_checkin_list(d, view_date):
            continue
        duty = _duty_shift_label(d, d.vehicle, 1, None)
        pending_rows.append({'driver': d, 'duty_shift': duty})
    if duty_shift_filter:
        pending_rows = [r for r in pending_rows if _duty_shift_passes_filter(r.get('duty_shift'), duty_shift_filter)]
    if (request.args.get('export') or '').strip().lower() == 'excel':
        headers = ['#', 'Project', 'District', 'Vehicle No', 'Vehicle Type', 'Shift', 'Duty shift', 'Driver', 'Driver ID']
        rows = []
        for i, item in enumerate(pending_rows, start=1):
            d = item['driver']
            rows.append([
                i,
                d.project.name if d.project else '',
                d.district.name if d.district else (d.vehicle.district.name if d.vehicle and d.vehicle.district else ''),
                d.vehicle.vehicle_no if d.vehicle else '',
                (d.vehicle.vehicle_type if d.vehicle and d.vehicle.vehicle_type else '') or '',
                d.shift or '',
                item.get('duty_shift') or '-',
                d.name,
                d.driver_id or '',
            ])
        fn = f'missing_checkin_{view_date.strftime("%Y%m%d")}.xlsx'
        return generate_excel_template(headers, rows, required_columns=[], filename=fn)
    return render_template(
        'driver_attendance_pending.html',
        form=form,
        view_date=view_date,
        pending_rows=pending_rows,
        project_id=project_id,
        district_id=district_id,
        vehicle_id=vehicle_id,
        shift=shift,
        driver_id=driver_id,
        search=search,
        duty_shift_filter=duty_shift_filter,
        vehicles=vehicles,
        vehicle_drivers=vehicle_drivers,
        disable_project=disable_project,
        disable_district=disable_district,
        disable_vehicle=disable_vehicle,
        disable_shift=disable_shift,
        checked_in_vehicle_count=checked_in_vehicle_count,
        **_nav_back_ctx(url_for('driver_attendance_list', date=view_date.strftime('%d-%m-%Y')), show_without_nav_from=True),
    )


def _missing_checkout_records(view_date, project_id, district_id, vehicle_id, shift, driver_id, search, user_context):
    """Drivers with check-in but no check-out for view_date, scoped like Missing Check-outs filters."""
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)
    need_vehicle_join = bool(district_id or search or (not is_master_or_admin and allowed_districts))
    query = DriverAttendance.query.filter(
        DriverAttendance.attendance_date == view_date,
        DriverAttendance.check_in.isnot(None),
        DriverAttendance.check_out.is_(None),
    ).join(Driver, DriverAttendance.driver_id == Driver.id).options(db.joinedload(DriverAttendance.driver))
    if need_vehicle_join:
        query = query.outerjoin(Vehicle, Driver.vehicle_id == Vehicle.id)
    if project_id:
        query = query.filter(Driver.project_id == project_id)
    elif not is_master_or_admin and allowed_projects:
        query = query.filter(Driver.project_id.in_(list(allowed_projects)))
    if district_id:
        query = query.filter(db.or_(Driver.district_id == district_id, Vehicle.district_id == district_id))
    elif not is_master_or_admin and allowed_districts:
        query = query.filter(
            db.or_(
                Driver.district_id.in_(list(allowed_districts)),
                Vehicle.district_id.in_(list(allowed_districts)),
            )
        )
    if vehicle_id:
        query = query.filter(Driver.vehicle_id == vehicle_id)
    if shift:
        query = query.filter(Driver.shift == shift)
    if driver_id:
        query = query.filter(Driver.id == driver_id)
    if search:
        flt = _multi_word_filter(search, Driver.name, Driver.driver_id, Vehicle.vehicle_no)
        if flt is not None:
            query = query.filter(flt)
    return query.order_by(Driver.name).all()


@app.route('/driver-attendance/missing-checkout', methods=['GET'])
def driver_attendance_missing_checkout():
    """Report: drivers who have check-in for the selected date but no check-out (same filters as Pending Attendance)."""
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    allowed_shifts = user_context.get('allowed_shifts', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)

    form = DriverAttendanceFilterForm()
    proj_q = Project.query.filter(Project.company_id.isnot(None))
    if not is_master_or_admin and allowed_projects:
        proj_q = proj_q.filter(Project.id.in_(list(allowed_projects)))
    form.project_id.choices = [(0, '-- All Projects --')] + [(p.id, p.name) for p in proj_q.order_by(Project.name).all()]
    view_date = _attendance_local_date()
    if request.args.get('date'):
        view_date = parse_date(request.args.get('date')) or view_date
    project_id = request.args.get('project_id', type=int) or None
    district_id = request.args.get('district_id', type=int) or None
    vehicle_id = request.args.get('vehicle_id', type=int) or None
    shift = (request.args.get('shift') or '').strip()
    driver_id = request.args.get('driver_id', type=int) or None
    search = (request.args.get('search') or '').strip()
    duty_shift_filter = _parse_duty_shift_filter_request()
    if project_id == 0: project_id = None
    if district_id == 0: district_id = None
    if vehicle_id == 0: vehicle_id = None
    if driver_id == 0: driver_id = None
    # Auto-select & disable if only 1 option allowed
    disable_project = False
    disable_district = False
    disable_vehicle = False
    disable_shift = False
    if not is_master_or_admin:
        if len(allowed_projects) == 1:
            if project_id is None:
                project_id = next(iter(allowed_projects))
            disable_project = True
        if len(allowed_districts) == 1:
            if district_id is None:
                district_id = next(iter(allowed_districts))
            disable_district = True
        if len(allowed_vehicles) == 1:
            if vehicle_id is None:
                vehicle_id = next(iter(allowed_vehicles))
            disable_vehicle = True
        if len(allowed_shifts) == 1:
            if not shift:
                shift = next(iter(allowed_shifts))
            disable_shift = True
    form.attendance_date.data = view_date
    form.project_id.data = project_id if project_id else 0
    if project_id and project_id != 0:
        dist_q = District.query.join(project_district).filter(project_district.c.project_id == project_id)
        if not is_master_or_admin and allowed_districts:
            dist_q = dist_q.filter(District.id.in_(list(allowed_districts)))
        form.district_id.choices = [(0, '-- All Districts --')] + [(d.id, d.name) for d in dist_q.order_by(District.name).all()]
    else:
        dist_q = District.query
        if not is_master_or_admin and allowed_districts:
            dist_q = dist_q.filter(District.id.in_(list(allowed_districts)))
        form.district_id.choices = [(0, '-- All Districts --')] + [(d.id, d.name) for d in dist_q.order_by(District.name).all()]
    form.district_id.data = district_id if district_id else 0
    vehicles = []
    if project_id and district_id:
        vehicles = Vehicle.query.filter(Vehicle.project_id == project_id, Vehicle.district_id == district_id).order_by(*vehicle_order_by()).all()
    elif project_id:
        vehicles = Vehicle.query.filter(Vehicle.project_id == project_id).order_by(*vehicle_order_by()).all()
    elif district_id:
        vehicles = Vehicle.query.filter(Vehicle.district_id == district_id).order_by(*vehicle_order_by()).all()
    else:
        veh_q = Vehicle.query.filter(Vehicle.project_id.isnot(None))
        if not is_master_or_admin and allowed_projects:
            veh_q = veh_q.filter(Vehicle.project_id.in_(list(allowed_projects)))
        vehicles = veh_q.order_by(*vehicle_order_by()).all()
    vehicle_drivers_q = Driver.query.filter(Driver.status == 'Active', Driver.vehicle_id.isnot(None))
    if project_id:
        vehicle_drivers_q = vehicle_drivers_q.filter(Driver.project_id == project_id)
    elif not is_master_or_admin and allowed_projects:
        vehicle_drivers_q = vehicle_drivers_q.filter(Driver.project_id.in_(list(allowed_projects)))
    need_vehicle_for_drivers = bool(district_id or search or (not is_master_or_admin and allowed_districts))
    if need_vehicle_for_drivers:
        vehicle_drivers_q = vehicle_drivers_q.outerjoin(Vehicle, Driver.vehicle_id == Vehicle.id)
    if district_id:
        vehicle_drivers_q = vehicle_drivers_q.filter(
            db.or_(Driver.district_id == district_id, Vehicle.district_id == district_id)
        )
    elif not is_master_or_admin and allowed_districts:
        vehicle_drivers_q = vehicle_drivers_q.filter(
            db.or_(Driver.district_id.in_(list(allowed_districts)), Vehicle.district_id.in_(list(allowed_districts)))
        )
    if vehicle_id:
        vehicle_drivers_q = vehicle_drivers_q.filter(Driver.vehicle_id == vehicle_id)
    if shift:
        vehicle_drivers_q = vehicle_drivers_q.filter(Driver.shift == shift)
    if search:
        flt = _multi_word_filter(search, Driver.name, Driver.driver_id, Vehicle.vehicle_no)
        if flt is not None:
            vehicle_drivers_q = vehicle_drivers_q.filter(flt)
    vehicle_drivers = vehicle_drivers_q.order_by(Driver.name).all()
    records = _missing_checkout_records(
        view_date, project_id, district_id, vehicle_id, shift, driver_id, search, user_context
    )
    record_rows = []
    for rec in records:
        d = rec.driver
        duty = _duty_shift_label(d, d.vehicle, getattr(rec, 'attendance_segment', 1), rec)
        record_rows.append({'rec': rec, 'driver': d, 'duty_shift': duty})
    if duty_shift_filter:
        record_rows = [r for r in record_rows if _duty_shift_passes_filter(r.get('duty_shift'), duty_shift_filter)]

    if (request.args.get('export') or '').strip().lower() == 'excel':
        headers = ['#', 'Project', 'District', 'Vehicle No', 'Vehicle Type', 'Shift', 'Duty shift', 'Driver', 'Driver ID', 'Check-in Time']
        rows = []
        for i, item in enumerate(record_rows, start=1):
            rec = item['rec']
            d = item['driver']
            rows.append([
                i,
                rec.project.name if rec.project else (d.project.name if d.project else ''),
                d.district.name if d.district else (d.vehicle.district.name if d.vehicle and d.vehicle.district else ''),
                d.vehicle.vehicle_no if d.vehicle else '',
                (d.vehicle.vehicle_type if d.vehicle and d.vehicle.vehicle_type else '') or '',
                d.shift or '',
                item.get('duty_shift') or '-',
                d.name,
                d.driver_id or '',
                format_time_ampm(rec.check_in) if rec.check_in else '',
            ])
        fn = f'missing_checkout_{view_date.strftime("%Y%m%d")}.xlsx'
        return generate_excel_template(headers, rows, required_columns=[], filename=fn)

    return render_template(
        'driver_attendance_missing_checkout.html',
        form=form,
        view_date=view_date,
        record_rows=record_rows,
        project_id=project_id,
        district_id=district_id,
        vehicle_id=vehicle_id,
        shift=shift,
        driver_id=driver_id,
        search=search,
        duty_shift_filter=duty_shift_filter,
        vehicles=vehicles,
        vehicle_drivers=vehicle_drivers,
        disable_project=disable_project,
        disable_district=disable_district,
        disable_vehicle=disable_vehicle,
        disable_shift=disable_shift,
        **_nav_back_ctx(url_for('driver_attendance_list', date=view_date.strftime('%d-%m-%Y')), show_without_nav_from=True),
    )


def _manual_attendance_driver_id():
    """Resolve driver_id when query string repeats keys (e.g. filter driver_id=0 + row driver_id). Last positive id wins."""
    merged = []
    merged.extend(request.args.getlist('driver_id'))
    merged.extend(request.form.getlist('driver_id'))
    for raw in reversed(merged):
        try:
            n = int(raw)
            if n > 0:
                return n
        except (TypeError, ValueError):
            continue
    return None


@app.route('/driver-attendance/manual-checkin', methods=['GET', 'POST'])
def driver_attendance_manual_checkin():
    """Manual check-in form: new check-in, or edit existing check-in time when attendance_id is set."""
    from auth_utils import get_user_context

    uid = session.get('user_id')
    uc = get_user_context(uid) if uid else {}
    local_today = _attendance_local_date()
    driver_id = _manual_attendance_driver_id()
    attendance_id = request.args.get('attendance_id', type=int) or request.form.get('attendance_id', type=int)
    date_str = request.args.get('date') or request.form.get('date')
    view_date = parse_date(date_str) if date_str else local_today
    if view_date > local_today:
        flash('Manual check-in cannot be recorded for a future date.', 'danger')
        return redirect(url_for('driver_attendance_pending', date=local_today.strftime('%d-%m-%Y')))
    back_params = {}
    for k in ('project_id', 'district_id', 'vehicle_id', 'shift', 'search', 'from_date', 'to_date', 'driver_id', 'duty_shift', 'page', 'per_page'):
        v = request.args.get(k) or request.form.get(k)
        if v is not None and v != '':
            back_params[k] = v
    back_to = request.args.get('back_to') or request.form.get('back_to') or ''
    if back_to:
        back_params['back_to'] = back_to
    if back_to == 'attendance_list':
        list_params = {k: v for k, v in back_params.items() if k != 'back_to'}
        back_url = url_for('driver_attendance_list', **list_params)
    else:
        bp = {k: v for k, v in back_params.items() if k != 'back_to'}
        back_url = url_for('driver_attendance_pending', date=view_date.strftime('%d-%m-%Y'), **bp)

    if not driver_id:
        flash('Driver select karein.', 'danger')
        return redirect(back_url)

    driver = Driver.query.options(joinedload(Driver.vehicle)).get(driver_id)
    if not driver:
        flash('Driver nahi mila.', 'danger')
        return redirect(back_url)

    edit_rec = None
    if attendance_id:
        edit_rec = db.session.get(DriverAttendance, attendance_id)
        if not edit_rec or edit_rec.driver_id != driver_id or edit_rec.attendance_date != view_date:
            flash('Attendance record mismatch.', 'danger')
            return redirect(back_url)
        if not _driver_attendance_record_allowed_for_user(edit_rec, uc):
            flash('Access denied.', 'danger')
            return redirect(back_url)
        if not edit_rec.check_in:
            flash('Is record par check-in maujood nahi — edit nahi ho sakta.', 'warning')
            return redirect(back_url)
    else:
        cap = _vehicle_capacity_value(driver.vehicle)
        blocked = _manual_checkin_blocked_by_vehicle_rules(driver_id, driver.vehicle, view_date)
        if blocked:
            flash(blocked, 'warning')
            return redirect(back_url)
        if _driver_has_open_segment(driver_id, view_date):
            flash(
                'Is driver ka is date par session abhi khula hai (check-out pending). Pehle check-out karein.',
                'warning',
            )
            return redirect(back_url)
        if _count_driver_segments_with_checkin(driver_id, view_date) >= cap:
            flash(
                f'Is driver ke liye is date par maximum {cap} shift/session ho chuki hain — mazeed manual check-in allow nahi.',
                'warning',
            )
            return redirect(back_url)
        if _driver_marked_duty_off_no_checkin(driver_id, view_date):
            flash(
                'Aaj ki is date par is driver ki duty Bulk Status se Off mark hai — manual check-in list mein nahi aate aur yahan check-in allow nahi.',
                'warning',
            )
            return redirect(back_url)

    if back_to == 'attendance_list' and attendance_id:
        if not _attendance_list_manual_edit_allowed():
            flash('Attendance List se check-in edit karne ki permission nahi hai.', 'danger')
            return redirect(back_url)

    tpl = dict(
        driver=driver,
        view_date=view_date,
        back_url=back_url,
        back_params=_preserve_nav_from({k: v for k, v in back_params.items() if k != 'back_to'}),
        edit_mode=bool(edit_rec),
        edit_rec=edit_rec,
        back_to=back_to,
        **_nav_back_ctx(back_url, show_without_nav_from=True),
    )

    if request.method == 'POST':
        time_str = (request.form.get('check_in_time') or '').strip()
        remarks_add = (request.form.get('remarks') or '').strip()
        post_aid = request.form.get('attendance_id', type=int)
        if not time_str:
            flash('Check-in time zaroori hai.', 'danger')
            return render_template('driver_attendance_manual_checkin.html', **tpl)
        if not remarks_add:
            flash('Reason zaroori hai (manual check-in / edit ka reason).', 'danger')
            return render_template('driver_attendance_manual_checkin.html', **tpl)
        try:
            from datetime import time as dt_time
            parts = time_str.split(':')
            h = int(parts[0]) if len(parts) > 0 else 0
            m = int(parts[1]) if len(parts) > 1 else 0
            s = int(parts[2]) if len(parts) > 2 else 0
            check_in_t = dt_time(h, m, s)
        except (ValueError, IndexError):
            flash('Invalid check-in time. HH:MM format use karein.', 'danger')
            return render_template('driver_attendance_manual_checkin.html', **tpl)
        photo_path = None
        photo = request.files.get('photo')
        if photo and photo.filename:
            try:
                photo.stream.seek(0)
                photo_path = upload_image_file(photo, folder="attendance")
            except Exception as e:
                flash(f'Photo save nahi hua (cloud storage): {str(e)}', 'warning')
        if post_aid:
            rec = db.session.get(DriverAttendance, post_aid)
            if not rec or rec.driver_id != driver_id or rec.attendance_date != view_date:
                flash('Invalid attendance record.', 'danger')
                return redirect(back_url)
            if not _driver_attendance_record_allowed_for_user(rec, uc):
                flash('Access denied.', 'danger')
                return redirect(back_url)
            rec.check_in = check_in_t
            if photo_path:
                rec.check_in_photo_path = photo_path
            tag = 'Manual check-in edit'
            rec.remarks = (rec.remarks or '').rstrip() + (' | ' + tag + ': ' + remarks_add if remarks_add else (' | ' + tag))
            rec.updated_at = pk_now()
            try:
                db.session.commit()
                flash('Check-in update ho gaya.', 'success')
                return redirect(back_url)
            except Exception as e:
                db.session.rollback()
                flash(f'Error: {str(e)}', 'danger')
            return render_template('driver_attendance_manual_checkin.html', **tpl)

        seg = _next_attendance_segment(driver_id, view_date)
        rec = DriverAttendance(
            driver_id=driver_id,
            attendance_date=view_date,
            attendance_segment=seg,
            status='Present',
            check_in=check_in_t,
            project_id=driver.project_id,
            remarks='Manual check-in' + (': ' + remarks_add if remarks_add else ''),
            check_in_photo_path=photo_path,
        )
        db.session.add(rec)
        try:
            db.session.commit()
            flash('Manual check-in save ho gaya.', 'success')
            return redirect(back_url)
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {str(e)}', 'danger')
    return render_template('driver_attendance_manual_checkin.html', **tpl)


@app.route('/driver-attendance/manual-checkout', methods=['GET', 'POST'])
def driver_attendance_manual_checkout():
    """Manual check-out: new checkout for open session, or edit existing checkout when attendance_id is set."""
    from auth_utils import get_user_context

    uid = session.get('user_id')
    uc = get_user_context(uid) if uid else {}
    local_today = _attendance_local_date()
    driver_id = _manual_attendance_driver_id()
    attendance_id = request.args.get('attendance_id', type=int) or request.form.get('attendance_id', type=int)
    date_str = request.args.get('date') or request.form.get('date')
    view_date = parse_date(date_str) if date_str else local_today
    if view_date > local_today:
        flash('Manual check-out cannot be recorded for a future date.', 'danger')
        return redirect(url_for('driver_attendance_missing_checkout', date=local_today.strftime('%d-%m-%Y')))
    back_params = {}
    for k in ('project_id', 'district_id', 'vehicle_id', 'shift', 'search', 'from_date', 'to_date', 'driver_id', 'duty_shift', 'page', 'per_page'):
        v = request.args.get(k) or request.form.get(k)
        if v is not None and v != '':
            back_params[k] = v
    back_to = request.args.get('back_to') or request.form.get('back_to') or ''
    if back_to:
        back_params['back_to'] = back_to
    if back_to == 'attendance_list':
        list_params = {k: v for k, v in back_params.items() if k != 'back_to'}
        back_url = url_for('driver_attendance_list', **list_params)
    else:
        back_url = url_for('driver_attendance_missing_checkout', date=view_date.strftime('%d-%m-%Y'), **{k: v for k, v in back_params.items() if k != 'back_to'})

    if not driver_id:
        flash('Driver select karein.', 'danger')
        return redirect(back_url)

    driver = Driver.query.options(joinedload(Driver.vehicle)).get(driver_id)
    if not driver:
        flash('Driver nahi mila.', 'danger')
        return redirect(back_url)

    rec = None
    if attendance_id:
        rec = DriverAttendance.query.options(joinedload(DriverAttendance.driver)).get(attendance_id)
        if not rec or rec.driver_id != driver_id or rec.attendance_date != view_date:
            flash('Attendance record mismatch.', 'danger')
            return redirect(back_url)
        if not _driver_attendance_record_allowed_for_user(rec, uc):
            flash('Access denied.', 'danger')
            return redirect(back_url)
        if not rec.check_in:
            flash('Is record par check-in maujood nahi — check-out edit nahi ho sakta.', 'warning')
            return redirect(back_url)
    else:
        rec = _open_driver_attendance_for_manual_checkout(driver_id, view_date)
        if not rec:
            flash('Is date ke liye khula check-in session nahi mila — ya check-out pehle hi ho chuka hai.', 'danger')
            return redirect(back_url)

    if back_to == 'attendance_list':
        if rec.check_out:
            if not _attendance_list_manual_edit_allowed():
                flash('Attendance List se check-out edit karne ki permission nahi hai.', 'danger')
                return redirect(back_url)
        else:
            if not _attendance_list_manual_checkout_allowed():
                flash('Attendance List se manual check-out karne ki permission nahi hai.', 'danger')
                return redirect(back_url)

    checkout_edit_mode = bool(attendance_id and rec.check_out)
    _glob_setting = AttendanceTimeOverride.query.filter_by(scope='global').first()
    allow_future = _glob_setting.allow_future_checkout if _glob_setting else False
    tpl_kwargs = dict(
        driver=driver,
        rec=rec,
        view_date=view_date,
        back_url=back_url,
        back_params=_preserve_nav_from({k: v for k, v in back_params.items() if k != 'back_to'}),
        allow_future_checkout=allow_future,
        back_to=back_to,
        checkout_edit_mode=checkout_edit_mode,
        **_nav_back_ctx(back_url, show_without_nav_from=True),
    )

    if request.method == 'POST':
        post_aid = request.form.get('attendance_id', type=int)
        if post_aid:
            rec = db.session.get(DriverAttendance, post_aid)
            if not rec or rec.driver_id != driver_id or rec.attendance_date != view_date:
                flash('Invalid attendance record.', 'danger')
                return redirect(back_url)
            if not _driver_attendance_record_allowed_for_user(rec, uc):
                flash('Access denied.', 'danger')
                return redirect(back_url)
            if not rec.check_in:
                flash('Check-in zaroori hai.', 'danger')
                return redirect(back_url)
        else:
            rec = _open_driver_attendance_for_manual_checkout(driver_id, view_date)
            if not rec:
                flash('Is date ke liye khula check-in session nahi mila.', 'danger')
                return redirect(back_url)
        tpl_kwargs['rec'] = rec
        tpl_kwargs['checkout_edit_mode'] = bool(rec.check_out)

        if back_to == 'attendance_list':
            if rec.check_out:
                if not _attendance_list_manual_edit_allowed():
                    flash('Attendance List se check-out edit karne ki permission nahi hai.', 'danger')
                    return redirect(back_url)
            else:
                if not _attendance_list_manual_checkout_allowed():
                    flash('Attendance List se manual check-out karne ki permission nahi hai.', 'danger')
                    return redirect(back_url)

        time_str = (request.form.get('check_out_time') or '').strip()
        checkout_date_str = (request.form.get('check_out_date') or '').strip()
        remarks_add = (request.form.get('remarks') or '').strip()
        if not time_str:
            flash('Check-out time zaroori hai.', 'danger')
            return render_template('driver_attendance_manual_checkout.html', **tpl_kwargs)
        if not remarks_add:
            flash('Reason zaroori hai (manual check-out / edit ka reason).', 'danger')
            return render_template('driver_attendance_manual_checkout.html', **tpl_kwargs)
        try:
            from datetime import time as dt_time, timedelta
            parts = time_str.split(':')
            h = int(parts[0]) if len(parts) > 0 else 0
            m = int(parts[1]) if len(parts) > 1 else 0
            s = int(parts[2]) if len(parts) > 2 else 0
            check_out_t = dt_time(h, m, s)
        except (ValueError, IndexError):
            flash('Invalid check-out time. HH:MM format use karein.', 'danger')
            return render_template('driver_attendance_manual_checkout.html', **tpl_kwargs)
        check_out_d = parse_date(checkout_date_str) if checkout_date_str else view_date
        if check_out_d is None:
            check_out_d = view_date
        max_allowed_date = view_date + timedelta(days=1)
        if check_out_d < view_date:
            flash('Check-out date attendance date se pehle nahi ho sakti.', 'danger')
            return render_template('driver_attendance_manual_checkout.html', **tpl_kwargs)
        if check_out_d > max_allowed_date:
            flash('Check-out date zyada se zyada attendance date ke agle din tak ho sakti hai.', 'danger')
            return render_template('driver_attendance_manual_checkout.html', **tpl_kwargs)
        if not allow_future:
            now_pk = _attendance_local_now()
            check_out_dt = datetime.combine(check_out_d, check_out_t)
            if check_out_dt > now_pk:
                flash('Check-out date/time future mein nahi ho sakti (abhi: ' + now_pk.strftime('%d-%m-%Y %I:%M %p') + '). Admin Settings se "Allow Future Manual Check-out" ON karein agar night shift ke liye zaroorat hai.', 'danger')
                return render_template('driver_attendance_manual_checkout.html', **tpl_kwargs)
        if check_out_d == view_date and rec.check_in and check_out_t < rec.check_in:
            flash('Check-out time check-in time se pehle hai — kya ye night shift hai? Agar haan to Check-out Date ko agle din par set karein.', 'warning')
            return render_template('driver_attendance_manual_checkout.html', **tpl_kwargs)
        photo_path = None
        photo = request.files.get('photo')
        if photo and photo.filename:
            try:
                photo.stream.seek(0)
                photo_path = upload_image_file(photo, folder="attendance")
            except Exception as e:
                flash(f'Photo save nahi hua (cloud storage): {str(e)}', 'warning')
        was_existing_checkout = rec.check_out is not None
        rec.check_out = check_out_t
        rec.check_out_date = check_out_d
        tag = 'Manual check-out edit' if was_existing_checkout else 'Manual check-out'
        rec.remarks = (rec.remarks or '').rstrip() + (' | ' + tag + (': ' + remarks_add if remarks_add else ''))
        if photo_path:
            rec.check_out_photo_path = photo_path
        rec.updated_at = pk_now()
        try:
            db.session.commit()
            flash('Check-out update ho gaya.' if was_existing_checkout else 'Manual check-out save ho gaya.', 'success')
            return redirect(back_url)
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {str(e)}', 'danger')
    return render_template('driver_attendance_manual_checkout.html', **tpl_kwargs)


@app.route('/driver-attendance/list-clear-times', methods=['POST'])
def driver_attendance_list_clear_times():
    """From Attendance List: delete check-out only, or clear check-in (and check-out) GPS/times/photos."""
    from auth_utils import get_user_context

    uid = session.get('user_id')
    uc = get_user_context(uid) if uid else {}
    list_params = _driver_attendance_list_redirect_params_from_form()
    back_url = url_for('driver_attendance_list', **list_params)

    if not _attendance_list_manual_delete_allowed():
        flash('Attendance List se check-in / check-out delete karne ki permission nahi hai.', 'danger')
        return redirect(back_url)

    attendance_id = request.form.get('attendance_id', type=int)
    date_str = (request.form.get('date') or '').strip()
    clear_kind = (request.form.get('clear_kind') or '').strip().lower()
    view_date = parse_date(date_str) if date_str else None

    if not attendance_id or clear_kind not in ('checkout', 'checkin'):
        flash('Invalid request.', 'danger')
        return redirect(back_url)

    rec = DriverAttendance.query.options(joinedload(DriverAttendance.driver)).get(attendance_id)
    if not rec or not view_date or rec.attendance_date != view_date:
        flash('Attendance record mismatch.', 'danger')
        return redirect(back_url)
    if not _driver_attendance_record_allowed_for_user(rec, uc):
        flash('Access denied.', 'danger')
        return redirect(back_url)

    tag_note = ''
    try:
        if clear_kind == 'checkout':
            if not rec.check_out:
                flash('Is record par check-out maujood nahi.', 'info')
                return redirect(back_url)
            _delete_stored_attendance_photo(rec.check_out_photo_path)
            rec.check_out = None
            rec.check_out_date = None
            rec.check_out_latitude = None
            rec.check_out_longitude = None
            rec.check_out_photo_path = None
            tag_note = 'List delete check-out'
        else:
            if not rec.check_in:
                flash('Is record par check-in maujood nahi.', 'info')
                return redirect(back_url)
            if rec.check_out:
                flash(
                    'Pehle check-out delete karein, phir check-in delete ho sakta hai.',
                    'warning',
                )
                return redirect(back_url)
            _delete_stored_attendance_photo(rec.check_in_photo_path)
            _delete_stored_attendance_photo(rec.check_out_photo_path)
            rec.check_in = None
            rec.check_in_latitude = None
            rec.check_in_longitude = None
            rec.check_in_photo_path = None
            rec.parking_station_id = None
            rec.check_out = None
            rec.check_out_date = None
            rec.check_out_latitude = None
            rec.check_out_longitude = None
            rec.check_out_photo_path = None
            tag_note = 'List delete check-in (+cleared check-out if any)'
        if tag_note:
            rec.remarks = (rec.remarks or '').rstrip() + (' | ' + tag_note)
        rec.updated_at = pk_now()
        if _attendance_is_empty_gps_shell(rec):
            db.session.delete(rec)
            flash(
                'Check-in / check-out hat gaye aur attendance ki row list se remove ho gayi.',
                'success',
            )
        else:
            flash(
                'Check-out hat diya gaya.' if clear_kind == 'checkout'
                else 'Check-in / check-out timing aur GPS data hat diya gaya.',
                'success',
            )
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        flash(f'Error: {str(e)}', 'danger')
    return redirect(back_url)


@app.route('/driver-attendance/bulk-manual-checkout', methods=['POST'])
def driver_attendance_bulk_manual_checkout():
    """Same rules as manual check-out, applied to multiple drivers from Missing Check-outs (one time/date/reason)."""
    from auth_utils import get_user_context
    from datetime import time as dt_time_cls

    local_today = _attendance_local_date()
    date_str = (request.form.get('date') or '').strip()
    view_date = parse_date(date_str) if date_str else local_today

    def _int_or_none(key):
        raw = request.form.get(key)
        if raw is None or raw == '':
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    project_id = _int_or_none('project_id')
    district_id = _int_or_none('district_id')
    vehicle_id = _int_or_none('vehicle_id')
    shift = (request.form.get('shift') or '').strip()
    driver_filter_id = _int_or_none('driver_id')
    search = (request.form.get('search') or '').strip()
    if project_id == 0:
        project_id = None
    if district_id == 0:
        district_id = None
    if vehicle_id == 0:
        vehicle_id = None
    if driver_filter_id == 0:
        driver_filter_id = None

    back_params = {}
    for k in ('project_id', 'district_id', 'vehicle_id', 'shift', 'search', 'duty_shift'):
        v = request.form.get(k)
        if v is not None and v != '':
            back_params[k] = v
    back_url = url_for('driver_attendance_missing_checkout', date=view_date.strftime('%d-%m-%Y'), **back_params)

    if view_date > local_today:
        flash('Manual check-out cannot be recorded for a future date.', 'danger')
        return redirect(back_url)

    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_records = _missing_checkout_records(
        view_date, project_id, district_id, vehicle_id, shift, driver_filter_id, search, user_context
    )
    allowed_ids = {r.driver_id for r in allowed_records}

    requested = set()
    for x in request.form.getlist('driver_ids'):
        try:
            requested.add(int(x))
        except (TypeError, ValueError):
            continue
    to_process = sorted(allowed_ids & requested)

    _BULK_MAX = 150
    if len(to_process) > _BULK_MAX:
        flash(f'Ek dafa mein maximum {_BULK_MAX} drivers select kar sakte hain.', 'warning')
        to_process = to_process[:_BULK_MAX]

    time_str = (request.form.get('check_out_time') or '').strip()
    checkout_date_str = (request.form.get('check_out_date') or '').strip()
    remarks_add = (request.form.get('remarks') or '').strip()

    if not to_process:
        flash('Koi driver select nahi kiya ya selected drivers is filter / scope ke mutabiq allowed nahi.', 'danger')
        return redirect(back_url)
    if not time_str:
        flash('Check-out time zaroori hai.', 'danger')
        return redirect(back_url)
    if not remarks_add:
        flash('Reason zaroori hai (manual check-out kyun kar rahe hain).', 'danger')
        return redirect(back_url)

    try:
        parts = time_str.replace('.', ':').split(':')
        h = int(parts[0]) if len(parts) > 0 else 0
        m = int(parts[1]) if len(parts) > 1 else 0
        s = int(parts[2]) if len(parts) > 2 else 0
        check_out_t = dt_time_cls(h, m, s)
    except (ValueError, IndexError):
        flash('Invalid check-out time. HH:MM format use karein.', 'danger')
        return redirect(back_url)

    check_out_d = parse_date(checkout_date_str) if checkout_date_str else view_date
    if check_out_d is None:
        check_out_d = view_date

    _glob_setting = AttendanceTimeOverride.query.filter_by(scope='global').first()
    allow_future = _glob_setting.allow_future_checkout if _glob_setting else False
    max_allowed_date = view_date + timedelta(days=1)
    if check_out_d < view_date:
        flash('Check-out date attendance date se pehle nahi ho sakti.', 'danger')
        return redirect(back_url)
    if check_out_d > max_allowed_date:
        flash('Check-out date zyada se zyada attendance date ke agle din tak ho sakti hai.', 'danger')
        return redirect(back_url)
    if not allow_future:
        now_pk = _attendance_local_now()
        check_out_dt = datetime.combine(check_out_d, check_out_t)
        if check_out_dt > now_pk:
            flash(
                'Check-out date/time future mein nahi ho sakti. Admin Settings se "Allow Future Manual Check-out" ON karein agar zaroorat hai.',
                'danger',
            )
            return redirect(back_url)

    photo_path = None
    photo = request.files.get('photo')
    if photo and photo.filename:
        try:
            photo.stream.seek(0)
            photo_path = upload_image_file(photo, folder='attendance')
        except Exception as e:
            flash(f'Photo save nahi hua (cloud storage): {str(e)}', 'warning')

    ok_count = 0
    skip_count = 0
    for did in to_process:
        rec = _open_driver_attendance_for_manual_checkout(did, view_date)
        if not rec or not rec.check_in or rec.check_out:
            skip_count += 1
            continue
        if check_out_d == view_date and rec.check_in and check_out_t < rec.check_in:
            skip_count += 1
            continue
        rec.check_out = check_out_t
        rec.check_out_date = check_out_d
        rec.remarks = (rec.remarks or '').rstrip() + (' | Manual check-out' + (': ' + remarks_add if remarks_add else ''))
        if photo_path:
            rec.check_out_photo_path = photo_path
        rec.updated_at = pk_now()
        ok_count += 1

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        flash(f'Error: {str(e)}', 'danger')
        return redirect(back_url)

    if ok_count:
        msg = f'{ok_count} driver(s) ka check-out save ho gaya.'
        if skip_count:
            msg += f' {skip_count} skip (pehle se check-out / check-in se pehle time — night shift ke liye alag date).'
        flash(msg, 'success')
    else:
        flash('Koi check-out save nahi hua — sab skip (invalid state ya time).', 'warning')
    return redirect(back_url)


# ────────────────────────────────────────────────
# Geofenced attendance: driver at parking station + selfie
# ────────────────────────────────────────────────
@app.route('/api/parking-stations-with-coords')
def api_parking_stations_with_coords():
    """Return parking stations that have latitude and longitude set (for geofence dropdown)."""
    stations = ParkingStation.query.filter(
        ParkingStation.latitude.isnot(None),
        ParkingStation.longitude.isnot(None)
    ).order_by(ParkingStation.name).all()
    return jsonify([{
        'id': s.id,
        'name': s.name,
        'district': s.district or '',
        'latitude': float(s.latitude),
        'longitude': float(s.longitude),
    } for s in stations])


@app.route('/api/attendance/projects')
def api_attendance_projects():
    """Projects linked to the given district (via project_district)."""
    district_id = request.args.get('district_id', type=int)
    if not district_id:
        return jsonify([])
    projects_query = Project.query.join(project_district).filter(
        project_district.c.district_id == district_id
    )
    # User scope: agar specific projects allowed hain to wahi dikhayein
    scope_projects, scope_districts, scope_vehicles, scope_shifts = _get_user_scope()
    if scope_projects:
        projects_query = projects_query.filter(Project.id.in_(scope_projects))
    projects = projects_query.distinct().order_by(Project.name).all()
    return jsonify([{'id': p.id, 'name': p.name} for p in projects])


@app.route('/api/attendance/vehicles')
def api_attendance_vehicles():
    """Vehicles for the given project and district; include parking_station_id and lat/lng if set."""
    project_id = request.args.get('project_id', type=int)
    district_id = request.args.get('district_id', type=int)
    if not project_id:
        return jsonify([])
    query = Vehicle.query.options(joinedload(Vehicle.parking_station)).filter(Vehicle.project_id == project_id)
    if district_id:
        query = query.filter(Vehicle.district_id == district_id)
    scope_projects, scope_districts, scope_vehicles, scope_shifts = _get_user_scope()
    if scope_projects:
        query = query.filter(Vehicle.project_id.in_(scope_projects))
    if scope_districts:
        query = query.filter(Vehicle.district_id.in_(scope_districts))
    if scope_vehicles:
        query = query.filter(Vehicle.id.in_(scope_vehicles))
    vehicles = query.order_by(*vehicle_order_by()).all()
    out = []
    for v in vehicles:
        ps = v.parking_station
        out.append({
            'id': v.id,
            'vehicle_no': v.vehicle_no,
            'vehicle_type': v.vehicle_type or '',
            'parking_station_id': v.parking_station_id,
            'parking_name': ps.name if ps else '',
            'latitude': float(ps.latitude) if ps and ps.latitude is not None else None,
            'longitude': float(ps.longitude) if ps and ps.longitude is not None else None,
            'driver_id': v.driver_id,
        })
    return jsonify(out)


@app.route('/api/attendance/drivers')
def api_attendance_drivers():
    """Drivers: Vehicle + Shift ke hisaab se — sirf wohi driver jo selected vehicle aur selected shift par maujood ho."""
    project_id = request.args.get('project_id', type=int)
    vehicle_id = request.args.get('vehicle_id', type=int)
    shift = (request.args.get('shift') or '').strip()
    today = _attendance_local_date()
    if not project_id:
        return jsonify([])
    query = Driver.query.filter_by(project_id=project_id, status='Active')
    scope_projects, scope_districts, scope_vehicles, scope_shifts = _get_user_scope()
    if scope_projects:
        query = query.filter(Driver.project_id.in_(scope_projects))
    if scope_vehicles:
        query = query.filter(Driver.vehicle_id.in_(scope_vehicles))
    if scope_shifts:
        query = query.filter(Driver.shift.in_(scope_shifts))
    if vehicle_id:
        query = query.filter(Driver.vehicle_id == vehicle_id)
    if shift:
        query = query.filter(Driver.shift == shift)
    drivers = query.order_by(Driver.name).all()
    return jsonify(
        [
            {
                'id': d.id,
                'name': d.name,
                'driver_id': d.driver_id,
                'shift': d.shift or '',
                'duty_off': _driver_marked_duty_off_no_checkin(d.id, today),
            }
            for d in drivers
        ]
    )


def _ov_to_dict(ov, source_label=None):
    """Convert an AttendanceTimeOverride row to a time-window dict."""
    d = {
        'morning_start': ov.morning_start, 'morning_end': ov.morning_end,
        'night_start': ov.night_start, 'night_end': ov.night_end,
        'source': source_label or getattr(ov, 'scope_label', ''),
    }
    for f in ('morning_checkout_start', 'morning_checkout_end', 'night_checkout_start', 'night_checkout_end'):
        d[f] = getattr(ov, f, None)
    return d


def _attendance_time_in_window(t, start_t, end_t):
    if start_t is None or end_t is None:
        return True
    if end_t < start_t:
        return t >= start_t or t <= end_t
    return start_t <= t <= end_t


def _attendance_allow_morning_driver_night_gps_checkin():
    glob = AttendanceTimeOverride.query.filter_by(scope='global').first()
    return bool(glob and glob.allow_morning_driver_night_gps_checkin)


def _attendance_allow_night_driver_morning_gps_checkin():
    glob = AttendanceTimeOverride.query.filter_by(scope='global').first()
    return bool(glob and glob.allow_night_driver_morning_gps_checkin)


def _attendance_auto_gps_checkout_on_window_end_enabled():
    glob = AttendanceTimeOverride.query.filter_by(scope='global').first()
    return bool(glob and glob.auto_gps_checkout_on_window_end)


def _attendance_capacity_one_checkin_mode():
    """Global policy for capacity-1 vehicles: both / morning_only / night_only."""
    glob = AttendanceTimeOverride.query.filter_by(scope='global').first()
    raw = ((glob.capacity_one_checkin_mode if glob else None) or 'both').strip().lower()
    if raw in ('morning', 'morning_only', 'morning-only'):
        return 'morning_only'
    if raw in ('night', 'evening', 'night_only', 'night-only', 'evening_only', 'evening-only'):
        return 'night_only'
    return 'both'


def _checkin_in_morning_window(tw, check_in_time):
    return _attendance_time_in_window(
        check_in_time, tw.get('morning_start'), tw.get('morning_end'),
    )


def _checkin_in_night_window(tw, check_in_time):
    return _attendance_time_in_window(
        check_in_time, tw.get('night_start'), tw.get('night_end'),
    )


def _gps_checkin_was_cross_shift(driver, check_in_time, tw):
    """True when GPS check-in used the opposite window (toggle path), not assigned shift window."""
    if not driver or not check_in_time:
        return False
    shift_l = (driver.shift or '').strip().lower()
    in_m = _checkin_in_morning_window(tw, check_in_time)
    in_n = _checkin_in_night_window(tw, check_in_time)
    if shift_l == 'morning':
        return bool(
            _attendance_allow_morning_driver_night_gps_checkin()
            and in_n
            and not in_m
        )
    if shift_l == 'night':
        return bool(
            _attendance_allow_night_driver_morning_gps_checkin()
            and in_m
            and not in_n
        )
    return False


def _gps_checkout_window_bounds(driver, tw, check_in_time):
    """GPS check-out window from check-in context: cross-shift uses opposite Check-OUT override."""
    shift_l = (driver.shift or '').strip().lower() if driver else ''
    cross = _gps_checkin_was_cross_shift(driver, check_in_time, tw)
    co_s = co_e = None
    if shift_l == 'morning':
        if cross:
            co_s = tw.get('night_checkout_start')
            co_e = tw.get('night_checkout_end')
            if not co_s and not co_e:
                co_s = tw.get('night_start')
                co_e = tw.get('night_end')
        else:
            co_s = tw.get('morning_checkout_start')
            co_e = tw.get('morning_checkout_end')
            if not co_s and not co_e:
                co_s = tw.get('night_start')
                co_e = tw.get('night_end')
    elif shift_l == 'night':
        if cross:
            co_s = tw.get('morning_checkout_start')
            co_e = tw.get('morning_checkout_end')
            if not co_s and not co_e:
                co_s = tw.get('night_start')
                co_e = tw.get('night_end')
        else:
            co_s = tw.get('night_checkout_start')
            co_e = tw.get('night_checkout_end')
            if not co_s and not co_e:
                co_s = tw.get('morning_start')
                co_e = tw.get('morning_end')
    return co_s, co_e, cross


def _checkout_window_end_datetime(attendance_date, check_in_time, start_t, end_t):
    """Datetime when this session's checkout window ends (must be after check-in)."""
    if not attendance_date or not end_t:
        return None
    if start_t and end_t and end_t < start_t:
        end_date = attendance_date + timedelta(days=1)
    else:
        end_date = attendance_date
    end_dt = datetime.combine(end_date, end_t)
    if check_in_time:
        check_in_dt = datetime.combine(attendance_date, check_in_time)
        if end_dt <= check_in_dt:
            end_dt = datetime.combine(end_date + timedelta(days=1), end_t)
    return end_dt


def _checkout_window_end_passed(attendance_date, check_in_time, start_t, end_t, now_dt):
    end_dt = _checkout_window_end_datetime(attendance_date, check_in_time, start_t, end_t)
    if not end_dt or not now_dt:
        return False
    return now_dt >= end_dt


GPS_AUTO_CHECKOUT_REMARK = 'Auto check-out: Checkout window ended (system setting)'


def _gps_checkout_window_ok(driver, now_time, tw, check_in_time):
    co_s, co_e, cross = _gps_checkout_window_bounds(driver, tw, check_in_time)
    if not _attendance_time_in_window(now_time, co_s, co_e):
        shift_l = (driver.shift or '').strip().lower() if driver else ''
        if cross and shift_l == 'morning':
            return False, 'Is session ki check-in night window mein thi — night check-out window ke dauran check-out karein.'
        if cross and shift_l == 'night':
            return False, 'Is session ki check-in morning window mein thi — morning check-out window ke dauran check-out karein.'
        if shift_l == 'morning':
            return False, 'Morning check-out time-window allowed nahi.'
        if shift_l == 'night':
            return False, 'Night check-out time-window allowed nahi.'
        return False, 'Check-out time-window allowed nahi.'
    return True, None


def _gps_checkin_shift_window_ok(shift, now_time, tw, driver=None, vehicle=None):
    """GPS check-in allowed for assigned shift and configured windows."""
    v = vehicle or (driver.vehicle if driver is not None else None)
    cap = _vehicle_capacity_value(v)
    if cap == 1:
        cap_mode = _attendance_capacity_one_checkin_mode()
        if cap_mode == 'morning_only':
            if _attendance_time_in_window(now_time, tw.get('morning_start'), tw.get('morning_end')):
                return True, None
            return False, 'Capacity-1 vehicle: attendance sirf morning window mein allowed hai (settings).'
        if cap_mode == 'night_only':
            if _attendance_time_in_window(now_time, tw.get('night_start'), tw.get('night_end')):
                return True, None
            return False, 'Capacity-1 vehicle: attendance sirf evening/night window mein allowed hai (settings).'

    shift_l = (shift or '').strip().lower()
    if shift_l == 'morning':
        if _attendance_time_in_window(now_time, tw.get('morning_start'), tw.get('morning_end')):
            return True, None
        if _attendance_allow_morning_driver_night_gps_checkin() and _attendance_time_in_window(
            now_time, tw.get('night_start'), tw.get('night_end')
        ):
            return True, None
        if _attendance_allow_morning_driver_night_gps_checkin():
            return False, (
                'Morning shift driver: abhi na morning na night check-in window mein. '
                'Settings → Attendance → GPS Check-in settings aur Night window check karein.'
            )
        return False, 'Morning shift ki attendance sirf morning time window mein lag sakti hai.'
    if shift_l == 'night':
        if _attendance_time_in_window(now_time, tw.get('night_start'), tw.get('night_end')):
            return True, None
        if _attendance_allow_night_driver_morning_gps_checkin() and _attendance_time_in_window(
            now_time, tw.get('morning_start'), tw.get('morning_end')
        ):
            return True, None
        if _attendance_allow_night_driver_morning_gps_checkin():
            return False, (
                'Night shift driver: abhi na night na morning check-in window mein. '
                'Settings → Attendance → GPS Check-in settings aur Morning window check karein.'
            )
        return False, 'Night shift ki attendance sirf night time window mein lag sakti hai.'
    return True, None


def _get_effective_time_window(driver=None, vehicle_id=None, project_id=None):
    """Hierarchical time lookup: Vehicle > District > Project > Global.
    Accepts driver object OR explicit vehicle_id/project_id for early lookup
    before a driver is selected."""
    _vehicle = None
    _project_id = project_id
    _district_id = None

    if driver:
        _vehicle = driver.vehicle if driver.vehicle_id else None
        if not _project_id:
            _project_id = driver.project_id
    if vehicle_id and not _vehicle:
        _vehicle = db.session.get(Vehicle, vehicle_id)
    if _vehicle:
        if not _project_id:
            _project_id = _vehicle.project_id
        _district_id = _vehicle.district_id

    if _vehicle:
        ov = AttendanceTimeOverride.query.filter_by(scope='vehicle', vehicle_id=_vehicle.id).first()
        if ov:
            return _ov_to_dict(ov)
    if _district_id and _project_id:
        ov = AttendanceTimeOverride.query.filter_by(scope='district', project_id=_project_id, district_id=_district_id).first()
        if ov:
            return _ov_to_dict(ov)
    if _project_id:
        ov = AttendanceTimeOverride.query.filter_by(scope='project', project_id=_project_id).first()
        if ov:
            return _ov_to_dict(ov)

    glob = AttendanceTimeOverride.query.filter_by(scope='global').first()
    if glob:
        return _ov_to_dict(glob, 'Global Default')
    ctrl = AttendanceTimeControl.query.first()
    if ctrl:
        return {
            'morning_start': ctrl.morning_start, 'morning_end': ctrl.morning_end,
            'night_start': ctrl.night_start, 'night_end': ctrl.night_end,
            'morning_checkout_start': None, 'morning_checkout_end': None,
            'night_checkout_start': None, 'night_checkout_end': None,
            'source': 'Global Default (Legacy)',
        }
    return {
        'morning_start': None, 'morning_end': None,
        'night_start': None, 'night_end': None,
        'morning_checkout_start': None, 'morning_checkout_end': None,
        'night_checkout_start': None, 'night_checkout_end': None,
        'source': 'None',
    }


@app.route('/api/attendance-time-window')
def api_attendance_time_window():
    """Return configured attendance time window.
    Accepts driver_id, vehicle_id, or project_id for hierarchical lookup."""
    driver_id = request.args.get('driver_id', type=int)
    vehicle_id_param = request.args.get('vehicle_id', type=int)
    project_id_param = request.args.get('project_id', type=int)
    driver = db.session.get(Driver, driver_id) if driver_id else None
    w = _get_effective_time_window(driver=driver, vehicle_id=vehicle_id_param, project_id=project_id_param)
    def t_str(t):
        return t.strftime('%H:%M') if t else None
    mco_s = w.get('morning_checkout_start')
    mco_e = w.get('morning_checkout_end')
    nco_s = w.get('night_checkout_start')
    nco_e = w.get('night_checkout_end')
    if not mco_s and not mco_e:
        mco_s = w.get('night_start')
        mco_e = w.get('night_end')
    if not nco_s and not nco_e:
        nco_s = w.get('morning_start')
        nco_e = w.get('morning_end')
    return jsonify({
        'morning_start': t_str(w['morning_start']),
        'morning_end': t_str(w['morning_end']),
        'night_start': t_str(w['night_start']),
        'night_end': t_str(w['night_end']),
        'morning_checkout_start': t_str(mco_s),
        'morning_checkout_end': t_str(mco_e),
        'night_checkout_start': t_str(nco_s),
        'night_checkout_end': t_str(nco_e),
        'source': w.get('source', ''),
        'allow_morning_driver_night_gps_checkin': _attendance_allow_morning_driver_night_gps_checkin(),
        'allow_night_driver_morning_gps_checkin': _attendance_allow_night_driver_morning_gps_checkin(),
        'capacity_one_checkin_mode': _attendance_capacity_one_checkin_mode(),
        'auto_gps_checkout_on_window_end': _attendance_auto_gps_checkout_on_window_end_enabled(),
    })


def _gps_checkin_submit_status(driver_id, vehicle_id=None, project_id=None):
    """Whether GPS check-in can be submitted now (prevents duplicate selfie + misleading local pending)."""
    today = _attendance_local_date()
    now_time = _attendance_local_time()
    driver = Driver.query.options(joinedload(Driver.vehicle)).get(driver_id) if driver_id else None
    if driver_id and not driver:
        return {'ok': False, 'can_submit': False, 'state': 'blocked', 'message': 'Invalid driver.'}
    vehicle = None
    if vehicle_id:
        vehicle = db.session.get(Vehicle, vehicle_id)
    if not vehicle and driver:
        vehicle = driver.vehicle
    if not driver_id and vehicle_id:
        pending_msg = _vehicle_pending_checkout_block_message(0, vehicle)
        if pending_msg:
            return {
                'ok': True,
                'can_submit': False,
                'state': 'blocked',
                'message': pending_msg,
                'vehicle_blocked': True,
            }
        return {'ok': True, 'can_submit': True, 'state': 'allowed', 'message': '', 'vehicle_ok': True}
    if _driver_marked_duty_off_no_checkin(driver_id, today):
        return {
            'ok': True,
            'can_submit': False,
            'state': 'blocked',
            'message': 'Aaj ki date par is driver ki duty Off mark hai — GPS/Camera se attendance nahi lag sakti.',
        }

    tw = _get_effective_time_window(driver=driver, vehicle_id=vehicle_id, project_id=project_id)
    vno = _vehicle_label(vehicle)
    cap = _vehicle_capacity_value(vehicle)

    open_rec_self = _open_gps_driver_attendance_session(driver_id, today)
    if open_rec_self and _gps_marked_attendance_row(open_rec_self):
        ci_t = open_rec_self.check_in.strftime('%H:%M') if open_rec_self.check_in else None
        dt_s, ci_s = _attendance_checkin_stamp(open_rec_self)
        if not _alternate_checkin_window_active(tw, open_rec_self.check_in, now_time):
            return {
                'ok': True,
                'can_submit': False,
                'state': 'complete',
                'message': (
                    'Aap ka check-in complete ho gaya hai. Dubara Mark Attendance ki zaroorat nahi — '
                    'check-out ke liye Check-out page use karein.'
                ),
                'check_in_time': ci_t,
                'has_open_session': True,
                'awaiting_checkout': True,
            }
        return {
            'ok': True,
            'can_submit': False,
            'state': 'checkout_pending',
            'message': (
                f'{vno}: aap ka {dt_s} ka check-in ({ci_s}) abhi check-out pending hai — '
                'pehle us session ka check-out complete karein, phir naya check-in ho ga.'
            ),
            'check_in_time': ci_t,
            'has_open_session': True,
        }

    pending_rec, pending_driver = (None, None)
    if vehicle and getattr(vehicle, 'id', None):
        pending_rec, pending_driver = _vehicle_oldest_pending_checkout(vehicle.id)

    if pending_rec and pending_driver and pending_driver.id != driver_id:
        pd_name = (pending_driver.name or '').strip() or 'Driver'
        dt_s, ci_s = _attendance_checkin_stamp(pending_rec)
        other_shift_on = _alternate_checkin_window_active(tw, pending_rec.check_in, now_time)
        if other_shift_on:
            return {
                'ok': True,
                'can_submit': False,
                'state': 'blocked',
                'message': (
                    f'{vno}: {pd_name} ka check-out abhi pending hai ({dt_s} check-in {ci_s}) — '
                    'un se check-out karwaen, phir aap ka check-in ho ga.'
                ),
                'vehicle_blocked': True,
                'pending_driver_name': pd_name,
            }
        return {
            'ok': True,
            'can_submit': False,
            'state': 'blocked',
            'message': (
                f'Is gari ke dusre driver {pd_name} ne {dt_s} ko {ci_s} par attendance laga di hai. '
                'Jab tak wo check-out nahi karte, aap ki attendance nahi lag sakti.'
            ),
            'vehicle_blocked': True,
            'pending_driver_name': pd_name,
        }

    blocked_msg = _manual_checkin_blocked_by_vehicle_rules(driver_id, vehicle, today)
    if blocked_msg:
        return {'ok': True, 'can_submit': False, 'state': 'blocked', 'message': blocked_msg}

    cap = _vehicle_capacity_value(vehicle)
    if _count_driver_segments_with_checkin(driver_id, today) >= cap:
        last = (
            DriverAttendance.query.filter(
                DriverAttendance.driver_id == driver_id,
                DriverAttendance.attendance_date == today,
                DriverAttendance.check_in.isnot(None),
            )
            .order_by(DriverAttendance.attendance_segment.desc(), DriverAttendance.id.desc())
            .first()
        )
        ci_t = last.check_in.strftime('%H:%M') if last and last.check_in else None
        return {
            'ok': True,
            'can_submit': False,
            'state': 'complete',
            'message': (
                'Aaj ka check-in pehle ho chuka hai'
                + ((' (' + format_time_ampm(last.check_in) + ')') if last and last.check_in else '')
                + '. Dubara selfie ya check-in ki zaroorat nahi.'
            ),
            'check_in_time': ci_t,
            'segments_used': int(_count_driver_segments_with_checkin(driver_id, today)),
            'capacity': cap,
        }
    shift = (driver.shift or '').strip().lower() if driver else ''
    ci_ok, ci_msg = _gps_checkin_shift_window_ok(shift, now_time, tw, driver=driver, vehicle=vehicle)
    if not ci_ok:
        return {'ok': True, 'can_submit': False, 'state': 'blocked', 'message': ci_msg}
    return {'ok': True, 'can_submit': True, 'state': 'allowed', 'message': ''}


def _gps_checkout_submit_status(driver_id, vehicle_id=None, project_id=None):
    """Whether GPS check-out can be submitted now."""
    today = _attendance_local_date()
    driver = db.session.get(Driver, driver_id)
    if not driver:
        return {'ok': False, 'can_submit': False, 'state': 'blocked', 'message': 'Invalid driver.'}
    open_rec = _open_gps_driver_attendance_for_checkout(driver_id, today)
    if open_rec:
        ci_t = open_rec.check_in.strftime('%H:%M') if open_rec.check_in else None
        return {
            'ok': True,
            'can_submit': True,
            'state': 'checkout_pending',
            'message': '',
            'check_in_time': ci_t,
            'has_open_session': True,
        }
    done = (
        DriverAttendance.query.filter(
            DriverAttendance.driver_id == driver_id,
            DriverAttendance.attendance_date == today,
            DriverAttendance.check_in.isnot(None),
            DriverAttendance.check_out.isnot(None),
        )
        .order_by(DriverAttendance.attendance_segment.desc(), DriverAttendance.id.desc())
        .first()
    )
    if done and _gps_marked_attendance_row(done):
        co_t = done.check_out.strftime('%H:%M') if done.check_out else None
        return {
            'ok': True,
            'can_submit': False,
            'state': 'complete',
            'message': (
                'Aaj ka check-out pehle ho chuka hai'
                + ((' (' + co_t + ')') if co_t else '')
                + '. Dubara selfie ki zaroorat nahi.'
            ),
            'check_out_time': co_t,
            'check_in_time': done.check_in.strftime('%H:%M') if done.check_in else None,
        }
    return {
        'ok': True,
        'can_submit': False,
        'state': 'no_checkin',
        'message': 'Pehle Mark Attendance se check-in karein, phir check-out karein.',
    }


@app.route('/api/attendance/gps-submit-status')
def api_attendance_gps_submit_status():
    """Pre-flight: can driver submit GPS check-in/out now? Avoids duplicate selfie + false local pending."""
    driver_id = request.args.get('driver_id', type=int)
    kind = (request.args.get('kind') or 'checkin').strip().lower()
    vehicle_id = request.args.get('vehicle_id', type=int)
    project_id = request.args.get('project_id', type=int)
    if not driver_id and not vehicle_id:
        return jsonify({'ok': False, 'message': 'Driver or vehicle is required.'}), 400
    if not driver_id and kind == 'checkout':
        return jsonify({'ok': False, 'message': 'Driver is required for check-out.'}), 400
    if kind == 'checkout':
        payload = _gps_checkout_submit_status(driver_id, vehicle_id, project_id)
    else:
        payload = _gps_checkin_submit_status(driver_id, vehicle_id, project_id)
    payload['kind'] = kind
    return jsonify(payload)


@app.route('/api/attendance-has-gps-checkin')
def api_attendance_has_gps_checkin():
    """Check if driver has GPS+Camera check-in for today (for Check-out form: button enable only if true)."""
    driver_id = request.args.get('driver_id', type=int)
    vehicle_id_param = request.args.get('vehicle_id', type=int)
    project_id_param = request.args.get('project_id', type=int)
    if not driver_id:
        return jsonify({'has_gps_checkin': False})
    today = _attendance_local_date()
    rec = _open_gps_driver_attendance_for_checkout(driver_id, today)
    payload = {'has_gps_checkin': bool(rec)}
    if rec:
        driver = db.session.get(Driver, driver_id)
        tw = _get_effective_time_window(
            driver=driver, vehicle_id=vehicle_id_param, project_id=project_id_param,
        )
        co_s, co_e, cross = _gps_checkout_window_bounds(driver, tw, rec.check_in)
        def t_str(t):
            return t.strftime('%H:%M') if t else None
        payload['effective_checkout_start'] = t_str(co_s)
        payload['effective_checkout_end'] = t_str(co_e)
        payload['checkout_cross_shift'] = cross
        payload['check_in_time'] = t_str(rec.check_in)
    return jsonify(payload)


def _attendance_media_payload(rec, kind):
    path_val = ''
    time_val = None
    if kind == 'checkin':
        path_val = (rec.check_in_photo_path or '').strip()
        time_val = rec.check_in
    else:
        path_val = (rec.check_out_photo_path or '').strip()
        time_val = rec.check_out
    media_url = media_url_filter(path_val) if path_val else None
    return {
        'has_media': bool(path_val),
        'media_path': path_val or None,
        'media_url': media_url,
        'uploaded': bool(path_val),
        'time': time_val.strftime('%H:%M') if time_val else None,
    }


@app.route('/api/attendance/latest-gps-media')
def api_attendance_latest_gps_media():
    """Latest current-date GPS attendance media/status for selected driver."""
    driver_id = request.args.get('driver_id', type=int)
    kind = (request.args.get('kind') or 'checkin').strip().lower()
    if kind not in ('checkin', 'checkout'):
        kind = 'checkin'
    if not driver_id:
        return jsonify({'ok': False, 'message': 'Driver is required.'}), 400
    rec_date = request.args.get('attendance_date', '').strip()
    if rec_date:
        try:
            use_date = datetime.strptime(rec_date, '%d-%m-%Y').date()
        except ValueError:
            use_date = _attendance_local_date()
    else:
        use_date = _attendance_local_date()
    q = DriverAttendance.query.filter(
        DriverAttendance.driver_id == driver_id,
        DriverAttendance.attendance_date == use_date,
    )
    rec = q.order_by(DriverAttendance.attendance_segment.desc(), DriverAttendance.id.desc()).first()
    if not rec:
        return jsonify({
            'ok': True,
            'has_record': False,
            'pending_text': 'Check IN pending' if kind == 'checkin' else 'Check-out pending',
            'attendance_date': use_date.strftime('%d-%m-%Y'),
            'kind': kind,
        })
    media = _attendance_media_payload(rec, kind)
    if kind == 'checkout' and not rec.check_in:
        pending_text = 'Check IN pending'
    elif kind == 'checkout' and rec.check_in and not rec.check_out:
        pending_text = 'Check-out pending'
    elif kind == 'checkin' and not rec.check_in:
        pending_text = 'Check IN pending'
    else:
        pending_text = None if media.get('has_media') else ('Check IN pending' if kind == 'checkin' else 'Check-out pending')
    return jsonify({
        'ok': True,
        'has_record': True,
        'attendance_date': use_date.strftime('%d-%m-%Y'),
        'kind': kind,
        'check_in_time': rec.check_in.strftime('%H:%M') if rec.check_in else None,
        'check_out_time': rec.check_out.strftime('%H:%M') if rec.check_out else None,
        'status': rec.status or '',
        'remarks': rec.remarks or '',
        'pending_text': pending_text,
        'media': media,
    })


def _decode_attendance_photo_b64(photo_b64):
    """Decode a data-URL or raw base64 string into image bytes. Returns None if invalid."""
    import base64

    if not (photo_b64 or '').strip():
        return None
    s = photo_b64.strip()
    m = re.match(r'data:image/[^;]+;base64,(.+)', s, re.DOTALL)
    raw_b64 = m.group(1) if m else s
    try:
        return base64.b64decode(raw_b64)
    except Exception:
        return None


def _upload_attendance_image_bytes_with_fallback(data, folder='attendance'):
    """Upload via R2 (WebP); if R2 misconfigured or fails, save JPEG bytes under uploads/."""
    if not data:
        return None
    try:
        return upload_image_bytes(data, folder=folder)
    except Exception as exc:
        app.logger.warning('Attendance photo R2 upload failed (%s), using disk fallback', exc)
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        upload_dir = os.path.join(root, 'uploads', folder)
        os.makedirs(upload_dir, exist_ok=True)
        fname = uuid.uuid4().hex + '.jpg'
        fpath = os.path.join(upload_dir, fname)
        with open(fpath, 'wb') as out:
            out.write(data)
        return '/uploads/%s/%s' % (folder, fname)
    except Exception as exc2:
        app.logger.exception('Attendance photo local save failed: %s', exc2)
        return None


def _upload_attendance_photo_from_form_or_b64(photo_file, photo_b64, *, required=True):
    """Resolve a werkzeug FileStorage and/or base64 payload to a stored path URL."""
    data = None
    if photo_file and getattr(photo_file, 'filename', None):
        photo_file.stream.seek(0)
        data = photo_file.read()
    elif photo_b64:
        data = _decode_attendance_photo_b64(photo_b64)
    photo_path = _upload_attendance_image_bytes_with_fallback(data) if data else None
    if not photo_path:
        if required:
            raise ValueError('Image required.')
        return None
    return photo_path


@app.route('/api/attendance/gps-checkin-submit', methods=['POST'])
def api_attendance_gps_checkin_submit():
    """Async GPS+Camera check-in upload endpoint used by web UI retry flow."""
    try:
        body = request.get_json(silent=True) or {}
        driver_id = int(body.get('driver_id') or 0)
        parking_station_id = int(body.get('parking_station_id') or 0)
        lat_val = float(body.get('latitude')) if body.get('latitude') not in (None, '') else None
        lng_val = float(body.get('longitude')) if body.get('longitude') not in (None, '') else None
        photo_b64 = (body.get('photo_base64') or '').strip()
        if not driver_id:
            return jsonify({'ok': False, 'message': 'Please select a driver.'}), 400
        if not parking_station_id:
            return jsonify({'ok': False, 'message': 'Please select a parking station.'}), 400
        driver = Driver.query.options(joinedload(Driver.vehicle)).get(driver_id)
        if not driver:
            return jsonify({'ok': False, 'message': 'Invalid driver.'}), 404
        today = _attendance_local_date()

        # --- Delayed-sync: honour capture_date from payload (offline retry support) ---
        # JS sends capture_date (dd-mm-yyyy) = date when photo was actually taken.
        # We allow max 1 calendar day back (overnight shift: captured 23:xx, retried next morning).
        # Anything older than 1 day = reject (prevents fake backdated attendance).
        _raw_capture_date = (body.get('capture_date') or '').strip()
        is_delayed_sync = False
        attendance_date = today
        if _raw_capture_date and _raw_capture_date != today.strftime('%d-%m-%Y'):
            try:
                from datetime import datetime as _dt
                _cap_date = _dt.strptime(_raw_capture_date, '%d-%m-%Y').date()
                _days_back = (today - _cap_date).days
                if _days_back < 0:
                    return jsonify({'ok': False, 'message': 'Capture date future mein nahi ho sakti.'}), 400
                if _days_back > 1:
                    return jsonify({'ok': False, 'message': f'Purani photo upload allowed nahi ({_days_back} din pehle ki). Sirf kal tak ki photo accept hoti hai.'}), 400
                attendance_date = _cap_date
                is_delayed_sync = True
            except (ValueError, TypeError):
                pass  # Malformed date — fall back to today silently

        # --- Delayed-sync: check if record already exists for this driver+date ---
        # If record exists and check_in_photo_path is empty → fill photo only (no new record).
        # If record exists and photo already set → duplicate, reject silently (data integrity).
        if is_delayed_sync:
            existing_rec = DriverAttendance.query.filter_by(
                driver_id=driver_id, attendance_date=attendance_date
            ).filter(DriverAttendance.check_in.isnot(None)).first()
            if existing_rec:
                if existing_rec.check_in_photo_path:
                    app.logger.info(
                        'GPS checkin delayed-sync: duplicate photo ignored for driver=%s date=%s',
                        driver_id, attendance_date
                    )
                    return jsonify({
                        'ok': True,
                        'message': 'Photo pehle se upload ho chuki hai (duplicate ignored).',
                        'record': {
                            'check_in_time': existing_rec.check_in.strftime('%H:%M') if existing_rec.check_in else None,
                            'media': _attendance_media_payload(existing_rec, 'checkin'),
                        },
                    })
                # Photo slot is empty — fill it (delayed sync)
                try:
                    photo_path = _upload_attendance_photo_from_form_or_b64(None, photo_b64, required=True)
                except ValueError as ve:
                    return jsonify({'ok': False, 'message': str(ve) or 'Image required.'}), 400
                except Exception as photo_exc:
                    app.logger.warning('GPS check-in delayed photo upload failed: %s', photo_exc)
                    return jsonify({'ok': False, 'message': 'Image upload failed. Network check karein.'}), 502
                existing_rec.check_in_photo_path = photo_path
                existing_rec.check_in_latitude = existing_rec.check_in_latitude or lat_val
                existing_rec.check_in_longitude = existing_rec.check_in_longitude or lng_val
                existing_rec.updated_at = pk_now()
                _sync_note = f' | Photo delayed-sync {today.strftime("%d-%m-%Y")}'
                if _sync_note not in (existing_rec.remarks or ''):
                    existing_rec.remarks = (existing_rec.remarks or '').rstrip() + _sync_note
                db.session.commit()
                app.logger.info(
                    'GPS checkin delayed-sync: photo filled for driver=%s date=%s', driver_id, attendance_date
                )
                return jsonify({
                    'ok': True,
                    'message': f'Check-in photo sync ho gaya ({attendance_date.strftime("%d-%m-%Y")} ki attendance update).',
                    'record': {
                        'check_in_time': existing_rec.check_in.strftime('%H:%M') if existing_rec.check_in else None,
                        'media': _attendance_media_payload(existing_rec, 'checkin'),
                    },
                })
            # No existing record for that date and it's a delayed date → reject.
            # We cannot create a backdated attendance record without the original context.
            return jsonify({
                'ok': False,
                'message': f'{attendance_date.strftime("%d-%m-%Y")} ka koi check-in record nahi mila. Delayed photo upload sirf existing record pe hi ho sakti hai.',
            }), 400

        # --- Normal (same-day) path ---
        if _driver_marked_duty_off_no_checkin(driver_id, attendance_date):
            return jsonify({'ok': False, 'message': 'Driver duty off hai; GPS/Camera attendance allowed nahi.'}), 400
        cap = _vehicle_capacity_value(driver.vehicle)
        blocked_msg = _manual_checkin_blocked_by_vehicle_rules(driver_id, driver.vehicle, attendance_date)
        if blocked_msg:
            return jsonify({'ok': False, 'message': blocked_msg}), 400
        if _driver_has_open_segment(driver_id, attendance_date):
            return jsonify({'ok': False, 'message': 'Check-out pending hai. Pehle previous session close karein.'}), 400
        if _count_driver_segments_with_checkin(driver_id, attendance_date) >= cap:
            return jsonify({'ok': False, 'message': f'Aaj maximum {cap} GPS check-in allowed hain.'}), 400
        now = pk_now()
        now_time = _attendance_local_time()
        _ci_vehicle_id = int(body.get('vehicle_id') or 0) or None
        _ci_project_id = int(body.get('project_id') or 0) or None
        tw = _get_effective_time_window(driver=driver, vehicle_id=_ci_vehicle_id, project_id=_ci_project_id)
        shift = (driver.shift or '').strip().lower()
        ci_ok, ci_msg = _gps_checkin_shift_window_ok(shift, now_time, tw, driver=driver, vehicle=driver.vehicle)
        if not ci_ok:
            return jsonify({'ok': False, 'message': ci_msg}), 400
        try:
            photo_path = _upload_attendance_photo_from_form_or_b64(None, photo_b64, required=True)
        except ValueError as ve:
            return jsonify({'ok': False, 'message': str(ve) or 'Image required.'}), 400
        except Exception as photo_exc:
            app.logger.warning('GPS check-in photo upload failed: %s', photo_exc)
            return jsonify({'ok': False, 'message': 'Image upload failed. Network check karein.'}), 502
        rec = DriverAttendance(
            driver_id=driver_id,
            attendance_date=attendance_date,
            attendance_segment=_next_attendance_segment(driver_id, attendance_date),
            status='Present',
            check_in=now.time(),
            project_id=driver.project_id,
            parking_station_id=parking_station_id,
            check_in_latitude=lat_val,
            check_in_longitude=lng_val,
            check_in_photo_path=photo_path,
            remarks='Ye GPS + Camera se attendance lagi hai.',
        )
        db.session.add(rec)
        db.session.commit()
        try:
            from notification_service import notify_gps_checkin
            _v = db.session.get(Vehicle, _ci_vehicle_id) if _ci_vehicle_id else None
            notify_gps_checkin(driver, photo_path, vehicle=_v)
        except Exception:
            pass
        return jsonify({
            'ok': True,
            'message': 'Check-in upload ho gaya.',
            'record': {
                'check_in_time': rec.check_in.strftime('%H:%M') if rec.check_in else None,
                'media': _attendance_media_payload(rec, 'checkin'),
            },
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'message': f'Upload failed: {str(e)}'}), 500


@app.route('/api/attendance/gps-checkout-submit', methods=['POST'])
def api_attendance_gps_checkout_submit():
    """Async GPS+Camera check-out upload endpoint used by web UI retry flow."""
    try:
        body = request.get_json(silent=True) or {}
        driver_id = int(body.get('driver_id') or 0)
        parking_station_id = int(body.get('parking_station_id') or 0)
        lat_val = float(body.get('latitude')) if body.get('latitude') not in (None, '') else None
        lng_val = float(body.get('longitude')) if body.get('longitude') not in (None, '') else None
        photo_b64 = (body.get('photo_base64') or '').strip()
        if not driver_id:
            return jsonify({'ok': False, 'message': 'Please select a driver.'}), 400
        if not parking_station_id:
            return jsonify({'ok': False, 'message': 'Please select a parking station.'}), 400
        driver = db.session.get(Driver, driver_id)
        if not driver:
            return jsonify({'ok': False, 'message': 'Invalid driver.'}), 404
        today = _attendance_local_date()

        # --- Delayed-sync: honour capture_date from payload (offline retry support) ---
        _raw_capture_date = (body.get('capture_date') or '').strip()
        is_delayed_sync = False
        lookup_date = today
        if _raw_capture_date and _raw_capture_date != today.strftime('%d-%m-%Y'):
            try:
                from datetime import datetime as _dt
                _cap_date = _dt.strptime(_raw_capture_date, '%d-%m-%Y').date()
                _days_back = (today - _cap_date).days
                if _days_back < 0:
                    return jsonify({'ok': False, 'message': 'Capture date future mein nahi ho sakti.'}), 400
                if _days_back > 1:
                    return jsonify({'ok': False, 'message': f'Purani photo upload allowed nahi ({_days_back} din pehle ki). Sirf kal tak ki photo accept hoti hai.'}), 400
                lookup_date = _cap_date
                is_delayed_sync = True
            except (ValueError, TypeError):
                pass

        existing = _open_gps_driver_attendance_for_checkout(driver_id, lookup_date)

        if is_delayed_sync and existing:
            # Delayed-sync checkout: only fill photo slot if empty; reject duplicate.
            if existing.check_out_photo_path:
                app.logger.info(
                    'GPS checkout delayed-sync: duplicate photo ignored for driver=%s date=%s',
                    driver_id, lookup_date
                )
                return jsonify({
                    'ok': True,
                    'message': 'Check-out photo pehle se upload ho chuki hai (duplicate ignored).',
                    'record': {
                        'check_out_time': existing.check_out.strftime('%H:%M') if existing.check_out else None,
                        'media': _attendance_media_payload(existing, 'checkout'),
                    },
                })
            try:
                photo_path = _upload_attendance_photo_from_form_or_b64(None, photo_b64, required=True)
            except ValueError as ve:
                return jsonify({'ok': False, 'message': str(ve) or 'Image required.'}), 400
            except Exception as photo_exc:
                app.logger.warning('GPS check-out delayed photo upload failed: %s', photo_exc)
                return jsonify({'ok': False, 'message': 'Image upload failed. Network check karein.'}), 502
            existing.check_out_photo_path = photo_path
            existing.check_out_latitude = existing.check_out_latitude or lat_val
            existing.check_out_longitude = existing.check_out_longitude or lng_val
            existing.updated_at = pk_now()
            _sync_note = f' | Checkout photo delayed-sync {today.strftime("%d-%m-%Y")}'
            if _sync_note not in (existing.remarks or ''):
                existing.remarks = (existing.remarks or '').rstrip() + _sync_note
            db.session.commit()
            app.logger.info(
                'GPS checkout delayed-sync: photo filled for driver=%s date=%s', driver_id, lookup_date
            )
            return jsonify({
                'ok': True,
                'message': f'Check-out photo sync ho gaya ({lookup_date.strftime("%d-%m-%Y")} ki attendance update).',
                'record': {
                    'check_out_time': existing.check_out.strftime('%H:%M') if existing.check_out else None,
                    'media': _attendance_media_payload(existing, 'checkout'),
                },
            })

        if is_delayed_sync and not existing:
            return jsonify({
                'ok': False,
                'message': f'{lookup_date.strftime("%d-%m-%Y")} ka koi open check-in session nahi mila. Delayed photo upload sirf existing record pe hi ho sakti hai.',
            }), 400

        # --- Normal (same-day) path ---
        if not existing:
            return jsonify({'ok': False, 'message': 'Current date ke liye GPS check-in nahi mila.'}), 400
        now = pk_now()
        now_time = _attendance_local_time()
        _co_vehicle_id = int(body.get('vehicle_id') or 0) or None
        _co_project_id = int(body.get('project_id') or 0) or None
        tw = _get_effective_time_window(driver=driver, vehicle_id=_co_vehicle_id, project_id=_co_project_id)
        co_ok, co_msg = _gps_checkout_window_ok(driver, now_time, tw, existing.check_in)
        if not co_ok:
            return jsonify({'ok': False, 'message': co_msg}), 400
        try:
            photo_path = _upload_attendance_photo_from_form_or_b64(None, photo_b64, required=True)
        except ValueError as ve:
            return jsonify({'ok': False, 'message': str(ve) or 'Image required.'}), 400
        except Exception as photo_exc:
            app.logger.warning('GPS check-out photo upload failed: %s', photo_exc)
            return jsonify({'ok': False, 'message': 'Image upload failed. Network check karein.'}), 502
        check_out_time = now.time()
        is_overnight = (existing.attendance_date != today)
        if not is_overnight and existing.check_in is not None and check_out_time <= existing.check_in:
            return jsonify({'ok': False, 'message': 'Check-out time check-in se pehle ya barabar nahi ho sakta.'}), 400
        existing.check_out = check_out_time
        existing.check_out_date = today
        existing.check_out_latitude = lat_val
        existing.check_out_longitude = lng_val
        existing.check_out_photo_path = photo_path
        existing.updated_at = now
        if not existing.remarks or 'GPS' not in (existing.remarks or ''):
            existing.remarks = (existing.remarks or '').rstrip() + ' | Check-out GPS+Cam'
        db.session.commit()
        try:
            from notification_service import notify_gps_checkout
            _v = db.session.get(Vehicle, _co_vehicle_id) if _co_vehicle_id else None
            notify_gps_checkout(driver, existing.check_out_photo_path, vehicle=_v)
        except Exception:
            pass
        return jsonify({
            'ok': True,
            'message': 'Check-out upload ho gaya.',
            'record': {
                'check_out_time': existing.check_out.strftime('%H:%M') if existing.check_out else None,
                'media': _attendance_media_payload(existing, 'checkout'),
            },
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'message': f'Upload failed: {str(e)}'}), 500

@app.route('/driver-attendance/checkin', methods=['GET', 'POST'])
def driver_attendance_checkin():
    """Geofenced check-in: District → Project → Vehicle → Parking (auto) → Shift → Driver. Then location + selfie."""
    scope_projects, scope_districts, scope_vehicles, scope_shifts = _get_user_scope()
    _eff_projects = list(scope_projects) if scope_projects else []
    _eff_districts = list(scope_districts) if scope_districts else []
    if scope_vehicles:
        _scope_vehs = Vehicle.query.options(joinedload(Vehicle.parking_station)).filter(Vehicle.id.in_(scope_vehicles)).all()
        for _v in _scope_vehs:
            if _v.district_id and _v.district_id not in _eff_districts:
                _eff_districts.append(_v.district_id)
            if not _eff_projects and _v.project_id:
                _eff_projects.append(_v.project_id)
    else:
        _scope_vehs = []
    districts_query = District.query.join(project_district, District.id == project_district.c.district_id)
    if _eff_districts:
        districts_query = districts_query.filter(District.id.in_(_eff_districts))
    elif _eff_projects:
        districts_query = districts_query.filter(project_district.c.project_id.in_(_eff_projects))
    districts = districts_query.distinct().order_by(District.name).all()

    auto_district_id = districts[0].id if len(districts) == 1 else None
    pre_projects = []
    auto_project_id = None
    if auto_district_id:
        pq = Project.query.join(project_district).filter(project_district.c.district_id == auto_district_id)
        if _eff_projects:
            pq = pq.filter(Project.id.in_(_eff_projects))
        pre_projects = pq.distinct().order_by(Project.name).all()
        if len(pre_projects) == 1:
            auto_project_id = pre_projects[0].id
    pre_vehicles_data = []
    auto_vehicle_id = None
    def _build_vehicle_dict(v):
        ps = v.parking_station
        return {
            'id': v.id, 'vehicle_no': v.vehicle_no, 'vehicle_type': v.vehicle_type or '',
            'parking_station_id': v.parking_station_id,
            'parking_name': ps.name if ps else '',
            'latitude': float(ps.latitude) if ps and ps.latitude is not None else None,
            'longitude': float(ps.longitude) if ps and ps.longitude is not None else None,
            'driver_id': v.driver_id,
        }
    if scope_vehicles and len(scope_vehicles) == 1:
        sv = _scope_vehs[0] if _scope_vehs else None
        if sv:
            pre_vehicles_data = [_build_vehicle_dict(sv)]
            auto_vehicle_id = sv.id
    elif auto_project_id:
        vq = Vehicle.query.options(joinedload(Vehicle.parking_station)).filter(Vehicle.project_id == auto_project_id)
        if auto_district_id:
            vq = vq.filter(Vehicle.district_id == auto_district_id)
        if scope_vehicles:
            vq = vq.filter(Vehicle.id.in_(scope_vehicles))
        for v in vq.order_by(*vehicle_order_by()).all():
            pre_vehicles_data.append(_build_vehicle_dict(v))
        if len(pre_vehicles_data) == 1:
            auto_vehicle_id = pre_vehicles_data[0]['id']
    scope_shifts_list = sorted(scope_shifts) if scope_shifts else []
    auto_shift = scope_shifts_list[0] if len(scope_shifts_list) == 1 else None

    today = _attendance_local_date()
    if request.method == 'POST':
        driver_id = request.form.get('driver_id', type=int)
        parking_station_id = request.form.get('parking_station_id', type=int)
        lat_s = request.form.get('latitude', '').strip()
        lng_s = request.form.get('longitude', '').strip()
        if not driver_id:
            flash('Please select a driver.', 'danger')
            return redirect(url_for('driver_attendance_checkin'))
        if not parking_station_id:
            flash('Please select a parking station.', 'danger')
            return redirect(url_for('driver_attendance_checkin'))
        try:
            lat_val = float(lat_s) if lat_s else None
            lng_val = float(lng_s) if lng_s else None
        except ValueError:
            lat_val = lng_val = None
        driver = Driver.query.options(joinedload(Driver.vehicle)).get(driver_id)
        if not driver:
            flash('Invalid driver.', 'danger')
            return redirect(url_for('driver_attendance_checkin'))
        if _driver_marked_duty_off_no_checkin(driver_id, today):
            flash(
                'Aaj ki date par is driver ki duty Off mark hai — GPS/Camera se attendance nahi lag sakti.',
                'warning',
            )
            return redirect(url_for('driver_attendance_checkin'))
        cap = _vehicle_capacity_value(driver.vehicle)
        blocked_vehicle_first = _vehicle_pending_checkout_block_message(driver_id, driver.vehicle)
        if blocked_vehicle_first:
            flash(blocked_vehicle_first, 'warning')
            return redirect(url_for('driver_attendance_checkin'))
        if _driver_has_open_segment(driver_id, today):
            flash(
                'Pehle Mark Attendance check-out complete karein — check-out pending session hai.',
                'warning',
            )
            return redirect(url_for('driver_attendance_checkin'))
        if _count_driver_segments_with_checkin(driver_id, today) >= cap:
            flash(
                f'Is vehicle ki capacity ke mutabiq aaj maximum {cap} GPS check-in ho sakti hain.',
                'danger',
            )
            return redirect(url_for('driver_attendance_checkin'))
        blocked_msg = _manual_checkin_blocked_by_vehicle_rules(driver_id, driver.vehicle, today)
        if blocked_msg:
            flash(blocked_msg, 'warning')
            return redirect(url_for('driver_attendance_checkin'))
        now = pk_now()
        now_time = _attendance_local_time()
        _ci_vehicle_id = request.form.get('vehicle_id', type=int)
        _ci_project_id = request.form.get('project_id', type=int)
        tw = _get_effective_time_window(driver=driver, vehicle_id=_ci_vehicle_id, project_id=_ci_project_id)
        shift = (driver.shift or '').strip()
        ci_ok, ci_msg = _gps_checkin_shift_window_ok(shift, now_time, tw, driver=driver, vehicle=driver.vehicle)
        if not ci_ok:
            flash(ci_msg, 'danger')
            return redirect(url_for('driver_attendance_checkin'))

        photo = request.files.get('photo')
        b64 = request.form.get('photo_base64', '').strip()
        try:
            photo_path = _upload_attendance_photo_from_form_or_b64(
                photo if (photo and photo.filename) else None,
                b64 or None,
                required=False,
            )
        except Exception:
            flash('Image upload failed. Please check your internet and try taking attendance again.', 'danger')
            return redirect(url_for('driver_attendance_checkin'))
        gps_cam_remark = 'Ye GPS + Camera se attendance lagi hai.'
        seg = _next_attendance_segment(driver_id, today)
        rec = DriverAttendance(
            driver_id=driver_id,
            attendance_date=today,
            attendance_segment=seg,
            status='Present',
            check_in=now.time(),
            project_id=driver.project_id,
            parking_station_id=parking_station_id,
            check_in_latitude=lat_val,
            check_in_longitude=lng_val,
            check_in_photo_path=photo_path,
            remarks=gps_cam_remark,
        )
        db.session.add(rec)
        try:
            db.session.commit()
            try:
                from notification_service import notify_gps_checkin
                _v = db.session.get(Vehicle, _ci_vehicle_id) if _ci_vehicle_id else None
                notify_gps_checkin(driver, photo_path, vehicle=_v)
            except Exception:
                pass
            flash('Attendance marked successfully. Check-in recorded with photo.', 'success')
            return redirect(url_for('driver_attendance_list', date=today.strftime('%d-%m-%Y')))
        except Exception as e:
            db.session.rollback()
            flash(f'Error saving: {str(e)}', 'danger')
    all_vehicles_by_project = {}
    _avq = Vehicle.query.options(joinedload(Vehicle.parking_station))
    if _eff_districts:
        _avq = _avq.filter(Vehicle.district_id.in_(_eff_districts))
    elif _eff_projects:
        _avq = _avq.filter(Vehicle.project_id.in_(_eff_projects))
    if scope_vehicles:
        _avq = _avq.filter(Vehicle.id.in_(scope_vehicles))
    for _av in _avq.order_by(*vehicle_order_by()).all():
        _pk = str(_av.project_id or 0)
        if _pk not in all_vehicles_by_project:
            all_vehicles_by_project[_pk] = []
        all_vehicles_by_project[_pk].append(_build_vehicle_dict(_av))
    from models import AttendanceSettings
    _att_s = AttendanceSettings.query.first()
    _geofence_radius = _att_s.geofence_radius_meters if _att_s else 150
    _geofence_enabled = _att_s.geofence_enabled if _att_s else True
    return render_template('driver_attendance_checkin.html',
        districts=districts, drivers=[], parking_stations=[],
        pre_projects=pre_projects, pre_vehicles_data=pre_vehicles_data,
        auto_district_id=auto_district_id, auto_project_id=auto_project_id,
        auto_vehicle_id=auto_vehicle_id, auto_shift=auto_shift,
        scope_shifts_list=scope_shifts_list,
        all_vehicles_by_project=all_vehicles_by_project,
        geofence_radius=_geofence_radius,
        geofence_enabled=_geofence_enabled,
        **_nav_back_ctx(url_for('driver_attendance_list'), show_without_nav_from=True),
    )


@app.route('/driver-attendance/checkout', methods=['GET', 'POST'])
def driver_attendance_checkout():
    """Geofenced check-out: same flow as check-in. Location + selfie, then save check_out time and coords."""
    scope_projects, scope_districts, scope_vehicles, scope_shifts = _get_user_scope()
    _eff_projects = list(scope_projects) if scope_projects else []
    _eff_districts = list(scope_districts) if scope_districts else []
    if scope_vehicles:
        _scope_vehs = Vehicle.query.options(joinedload(Vehicle.parking_station)).filter(Vehicle.id.in_(scope_vehicles)).all()
        for _v in _scope_vehs:
            if _v.district_id and _v.district_id not in _eff_districts:
                _eff_districts.append(_v.district_id)
            if not _eff_projects and _v.project_id:
                _eff_projects.append(_v.project_id)
    else:
        _scope_vehs = []
    districts_q = District.query.join(project_district, District.id == project_district.c.district_id)
    if _eff_districts:
        districts_q = districts_q.filter(District.id.in_(_eff_districts))
    elif _eff_projects:
        districts_q = districts_q.filter(project_district.c.project_id.in_(_eff_projects))
    districts = districts_q.distinct().order_by(District.name).all()
    auto_district_id = districts[0].id if len(districts) == 1 else None
    pre_projects = []
    auto_project_id = None
    if auto_district_id:
        pq = Project.query.join(project_district).filter(project_district.c.district_id == auto_district_id)
        if _eff_projects:
            pq = pq.filter(Project.id.in_(_eff_projects))
        pre_projects = pq.distinct().order_by(Project.name).all()
        if len(pre_projects) == 1:
            auto_project_id = pre_projects[0].id
    pre_vehicles_data = []
    auto_vehicle_id = None
    def _build_vehicle_dict(v):
        ps = v.parking_station
        return {
            'id': v.id, 'vehicle_no': v.vehicle_no, 'vehicle_type': v.vehicle_type or '',
            'parking_station_id': v.parking_station_id,
            'parking_name': ps.name if ps else '',
            'latitude': float(ps.latitude) if ps and ps.latitude is not None else None,
            'longitude': float(ps.longitude) if ps and ps.longitude is not None else None,
            'driver_id': v.driver_id,
        }
    if scope_vehicles and len(scope_vehicles) == 1:
        sv = _scope_vehs[0] if _scope_vehs else None
        if sv:
            pre_vehicles_data = [_build_vehicle_dict(sv)]
            auto_vehicle_id = sv.id
    elif auto_project_id:
        vq = Vehicle.query.options(joinedload(Vehicle.parking_station)).filter(Vehicle.project_id == auto_project_id)
        if auto_district_id:
            vq = vq.filter(Vehicle.district_id == auto_district_id)
        if scope_vehicles:
            vq = vq.filter(Vehicle.id.in_(scope_vehicles))
        for v in vq.order_by(*vehicle_order_by()).all():
            pre_vehicles_data.append(_build_vehicle_dict(v))
        if len(pre_vehicles_data) == 1:
            auto_vehicle_id = pre_vehicles_data[0]['id']
    scope_shifts_list = sorted(scope_shifts) if scope_shifts else []
    auto_shift = scope_shifts_list[0] if len(scope_shifts_list) == 1 else None

    today = _attendance_local_date()
    if request.method == 'POST':
        driver_id = request.form.get('driver_id', type=int)
        parking_station_id = request.form.get('parking_station_id', type=int)
        lat_s = request.form.get('latitude', '').strip()
        lng_s = request.form.get('longitude', '').strip()
        if not driver_id:
            flash('Please select a driver.', 'danger')
            return redirect(url_for('driver_attendance_checkout'))
        if not parking_station_id:
            flash('Please select a parking station.', 'danger')
            return redirect(url_for('driver_attendance_checkout'))
        try:
            lat_val = float(lat_s) if lat_s else None
            lng_val = float(lng_s) if lng_s else None
        except ValueError:
            lat_val = lng_val = None
        driver = db.session.get(Driver, driver_id)
        if not driver:
            flash('Invalid driver.', 'danger')
            return redirect(url_for('driver_attendance_checkout'))
        existing = _open_gps_driver_attendance_for_checkout(driver_id, today)
        if not existing:
            flash(
                'Mark At Attendance (GPS + Camera) se khula check-in session nahi mila — pehle check-in karein.',
                'danger',
            )
            return redirect(url_for('driver_attendance_checkout'))
        now = pk_now()
        now_time = _attendance_local_time()
        _co_vehicle_id = request.form.get('vehicle_id', type=int)
        _co_project_id = request.form.get('project_id', type=int)
        tw = _get_effective_time_window(driver=driver, vehicle_id=_co_vehicle_id, project_id=_co_project_id)
        co_ok, co_msg = _gps_checkout_window_ok(driver, now_time, tw, existing.check_in)
        if not co_ok:
            co_s, co_e, _cross = _gps_checkout_window_bounds(driver, tw, existing.check_in)
            src = tw.get('source', '')
            detail = (
                f' Allowed: {co_s.strftime("%H:%M") if co_s else "–"} – {co_e.strftime("%H:%M") if co_e else "–"} ({src}).'
                if co_s or co_e else ''
            )
            flash((co_msg or 'Check-out abhi allowed nahi.') + detail, 'danger')
            return redirect(url_for('driver_attendance_checkout'))
        photo = request.files.get('photo')
        b64 = request.form.get('photo_base64', '').strip()
        try:
            photo_path = _upload_attendance_photo_from_form_or_b64(
                photo if (photo and photo.filename) else None,
                b64 or None,
                required=False,
            )
        except Exception:
            flash('Image upload failed. Please check your internet and try taking attendance again.', 'danger')
            return redirect(url_for('driver_attendance_checkout'))
        if existing:
            check_out_time = now.time()
            is_overnight = (existing.attendance_date != today)
            if not is_overnight and existing.check_in is not None and check_out_time <= existing.check_in:
                flash('Check-out ka time check-in time se pehle ya barabar nahi ho sakta. Pehle check-in time check karein.', 'danger')
                return redirect(url_for('driver_attendance_checkout'))
            existing.check_out = check_out_time
            existing.check_out_date = today
            existing.check_out_latitude = lat_val
            existing.check_out_longitude = lng_val
            if photo_path:
                existing.check_out_photo_path = photo_path
            existing.updated_at = now
            if not existing.remarks or 'GPS' not in (existing.remarks or ''):
                existing.remarks = (existing.remarks or '').rstrip() + (' | Check-out GPS+Cam' if photo_path else ' | Check-out GPS')
        else:
            flash('Is driver ki aaj ki Check-in attendance maujood nahi. Pehle Check-in karein.', 'danger')
            return redirect(url_for('driver_attendance_checkout'))
        try:
            db.session.commit()
            try:
                from notification_service import notify_gps_checkout
                _v = db.session.get(Vehicle, _co_vehicle_id) if _co_vehicle_id else None
                notify_gps_checkout(driver, photo_path or existing.check_out_photo_path, vehicle=_v)
            except Exception:
                pass
            flash('Check-out recorded successfully with photo.', 'success')
            return redirect(url_for('driver_attendance_list', date=today.strftime('%d-%m-%Y')))
        except Exception as e:
            db.session.rollback()
            flash(f'Error saving: {str(e)}', 'danger')
    all_vehicles_by_project = {}
    _avq = Vehicle.query.options(joinedload(Vehicle.parking_station))
    if _eff_districts:
        _avq = _avq.filter(Vehicle.district_id.in_(_eff_districts))
    elif _eff_projects:
        _avq = _avq.filter(Vehicle.project_id.in_(_eff_projects))
    if scope_vehicles:
        _avq = _avq.filter(Vehicle.id.in_(scope_vehicles))
    for _av in _avq.order_by(*vehicle_order_by()).all():
        _pk = str(_av.project_id or 0)
        if _pk not in all_vehicles_by_project:
            all_vehicles_by_project[_pk] = []
        all_vehicles_by_project[_pk].append(_build_vehicle_dict(_av))
    from models import AttendanceSettings
    _att_s = AttendanceSettings.query.first()
    _geofence_radius = _att_s.geofence_radius_meters if _att_s else 150
    _geofence_enabled = _att_s.geofence_enabled if _att_s else True
    return render_template('driver_attendance_checkout.html',
        districts=districts, drivers=[], parking_stations=[],
        pre_projects=pre_projects, pre_vehicles_data=pre_vehicles_data,
        auto_district_id=auto_district_id, auto_project_id=auto_project_id,
        auto_vehicle_id=auto_vehicle_id, auto_shift=auto_shift,
        scope_shifts_list=scope_shifts_list,
        all_vehicles_by_project=all_vehicles_by_project,
        geofence_radius=_geofence_radius,
        geofence_enabled=_geofence_enabled,
        **_nav_back_ctx(url_for('driver_attendance_list'), show_without_nav_from=True),
    )


@app.route('/driver-attendance/report', methods=['GET', 'POST'])
def driver_attendance_report():
    from auth_utils import get_user_context
    
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    allowed_shifts = user_context.get('allowed_shifts', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)
    
    # Convert sets to lists for compatibility
    scope_projects = list(allowed_projects) if allowed_projects else []
    scope_districts = list(allowed_districts) if allowed_districts else []
    scope_vehicles = list(allowed_vehicles) if allowed_vehicles else []
    scope_shifts = list(allowed_shifts) if allowed_shifts else []
    
    form = DriverAttendanceReportForm()
    has_single_scope = bool(
        scope_projects and len(scope_projects) == 1 and
        scope_districts and len(scope_districts) == 1 and
        scope_vehicles and len(scope_vehicles) == 1 and
        scope_shifts and len(scope_shifts) == 1
    )
    single_vehicle = None
    if has_single_scope and scope_vehicles:
        single_vehicle = db.session.get(Vehicle, scope_vehicles[0])

    # Auto-select if only 1 option available
    disable_project = False
    disable_district = False
    if scope_projects and len(scope_projects) == 1:
        disable_project = True
    if scope_districts and len(scope_districts) == 1:
        disable_district = True
    
    project_query = Project.query.filter(Project.company_id.isnot(None))
    if scope_projects:
        project_query = project_query.filter(Project.id.in_(scope_projects))
    form.project_id.choices = [(0, '-- All Projects --')] + [(p.id, p.name) for p in project_query.order_by(Project.name).all()]
    
    # Auto-select if only 1 available (GET and POST both)
    if disable_project:
        form.project_id.data = scope_projects[0]
    if disable_district:
        form.district_id.data = scope_districts[0]

    # District choices: project ke hisaab se, warna scope/districts ke hisaab se
    if request.method == 'POST':
        try:
            pid = request.form.get('project_id', type=int) or 0
        except (TypeError, ValueError):
            pid = 0
        # If project select was disabled, value not submitted - use scoped value
        if not pid and disable_project and scope_projects:
            pid = scope_projects[0]
        if pid and pid != 0:
            districts_query = District.query.join(project_district).filter(project_district.c.project_id == pid)
        else:
            districts_query = District.query
        if scope_districts:
            districts_query = districts_query.filter(District.id.in_(scope_districts))
        districts = districts_query.order_by(District.name).all()
        form.district_id.choices = [(0, '-- All Districts --')] + [(d.id, d.name) for d in districts]
    else:
        districts_query = District.query
        if scope_districts:
            districts_query = districts_query.filter(District.id.in_(scope_districts))
        districts = districts_query.order_by(District.name).all()
        form.district_id.choices = [(0, '-- All Districts --')] + [(d.id, d.name) for d in districts]
    today = pk_date()
    form.month.data = form.month.data or today.month
    form.year.data = form.year.data or today.year
    report = []
    selected_vehicle_id = 0
    selected_shift = ''
    vehicle_choices = []  # [(id, label), ...] for multi-scope POST so dropdown retains selection
    if request.method == 'POST':
        try:
            selected_vehicle_id = request.form.get('vehicle_id', type=int) or 0
        except (TypeError, ValueError):
            selected_vehicle_id = 0
        selected_shift = (request.form.get('shift') or '').strip()
        # Build vehicle options for POST so template can render them (no reset)
        pid = form.project_id.data or 0
        did = form.district_id.data or 0
        if pid and did:
            vq = Vehicle.query.filter(Vehicle.project_id == pid, Vehicle.district_id == did)
            if scope_vehicles:
                vq = vq.filter(Vehicle.id.in_(scope_vehicles))
            if scope_projects:
                vq = vq.filter(Vehicle.project_id.in_(scope_projects))
            if scope_districts:
                vq = vq.filter(Vehicle.district_id.in_(scope_districts))
            for v in vq.order_by(*vehicle_order_by()).all():
                label = v.vehicle_no + ((' (' + v.vehicle_type + ')') if v.vehicle_type else '')
                vehicle_choices.append((v.id, label))
    if request.method == 'POST' and form.validate_on_submit():
        month = form.month.data
        year = form.year.data
        project_id = form.project_id.data or 0
        if project_id == 0:
            project_id = None
        district_id = form.district_id.data or 0
        if district_id == 0:
            district_id = None
        vehicle_id = request.form.get('vehicle_id', type=int) or 0
        if vehicle_id == 0:
            vehicle_id = None
        shift = (request.form.get('shift') or '').strip()
        search = (form.search.data or '').strip()
        drivers_query = Driver.query.filter(
            Driver.status == 'Active',
            Driver.vehicle_id.isnot(None),
        ).outerjoin(Vehicle, Driver.vehicle_id == Vehicle.id)
        # Scope enforce - use OR so NULL driver fields fall back to vehicle fields
        if scope_projects:
            drivers_query = drivers_query.filter(
                db.or_(Driver.project_id.in_(scope_projects),
                       Vehicle.project_id.in_(scope_projects))
            )
        if scope_districts:
            drivers_query = drivers_query.filter(
                db.or_(Driver.district_id.in_(scope_districts),
                       Vehicle.district_id.in_(scope_districts))
            )
        if scope_vehicles:
            drivers_query = drivers_query.filter(Driver.vehicle_id.in_(scope_vehicles))
        if scope_shifts:
            drivers_query = drivers_query.filter(Driver.shift.in_(scope_shifts))
        if project_id:
            drivers_query = drivers_query.filter(
                db.or_(Driver.project_id == project_id, Vehicle.project_id == project_id)
            )
        if district_id:
            drivers_query = drivers_query.filter(
                db.or_(Driver.district_id == district_id, Vehicle.district_id == district_id)
            )
        if vehicle_id:
            drivers_query = drivers_query.filter(Driver.vehicle_id == vehicle_id)
        if shift:
            drivers_query = drivers_query.filter(Driver.shift == shift)
        driver_id_filter = request.form.get('driver_id', type=int) or 0
        if driver_id_filter:
            drivers_query = drivers_query.filter(Driver.id == driver_id_filter)
        if search:
            flt = _multi_word_filter(search, Driver.name, Driver.driver_id, Vehicle.vehicle_no)
            if flt is not None:
                drivers_query = drivers_query.filter(flt)
        drivers = drivers_query.distinct().order_by(Driver.name).all()
        from calendar import monthrange
        _, ndays = monthrange(year, month)
        start_d = date(year, month, 1)
        end_d = date(year, month, ndays)
        for d in drivers:
            rows = (
                DriverAttendance.query.filter(
                    DriverAttendance.driver_id == d.id,
                    DriverAttendance.attendance_date >= start_d,
                    DriverAttendance.attendance_date <= end_d,
                )
                .order_by(DriverAttendance.attendance_date, DriverAttendance.attendance_segment)
                .all()
            )
            by_status = {}
            distinct_present_days = set()
            counted_rows = 0
            for r in rows:
                if not _attendance_record_counts_in_report(r):
                    continue
                counted_rows += 1
                status = (r.status or '').strip()
                by_status[status] = by_status.get(status, 0) + 1
                if status == 'Present':
                    distinct_present_days.add(r.attendance_date)
            report.append({
                'driver': d,
                'present': by_status.get('Present', 0),
                'absent': by_status.get('Absent', 0),
                'leave': by_status.get('Leave', 0),
                'late': by_status.get('Late', 0),
                'half_day': by_status.get('Half-Day', 0),
                'off': by_status.get('Off', 0),
                'total_marked': counted_rows,
                'distinct_present_days': len(distinct_present_days),
                'days_in_month': ndays,
            })
    # Driver dropdown choices (scoped, for cascade)
    vd_q = Driver.query.filter(Driver.status == 'Active', Driver.vehicle_id.isnot(None))
    if scope_projects:
        vd_q = vd_q.filter(Driver.project_id.in_(scope_projects))
    if scope_vehicles:
        vd_q = vd_q.filter(Driver.vehicle_id.in_(scope_vehicles))
    vehicle_drivers = vd_q.order_by(Driver.name).all()
    selected_driver_id = (request.form.get('driver_id', type=int) or 0) if request.method == 'POST' else 0
    return render_template('driver_attendance_report.html', form=form, report=report, single_vehicle=single_vehicle, has_single_scope=has_single_scope, selected_vehicle_id=selected_vehicle_id, selected_shift=selected_shift, vehicle_choices=vehicle_choices, disable_project=disable_project, disable_district=disable_district, vehicle_drivers=vehicle_drivers, selected_driver_id=selected_driver_id, **_nav_back_ctx(url_for('reports_index'), show_without_nav_from=True))


def _build_driver_daily_attendance_report_payload(
    month,
    year,
    project_id,
    district_id,
    vehicle_id=None,
    driver_id_filter=0,
    search='',
    scope_projects=None,
    scope_districts=None,
    scope_vehicles=None,
    scope_shifts=None,
):
    """Build day-wise attendance grid data for page render or Excel export."""
    from calendar import monthrange

    scope_projects = scope_projects or []
    scope_districts = scope_districts or []
    scope_vehicles = scope_vehicles or []
    scope_shifts = scope_shifts or []
    status_columns = ['Present', 'Absent', 'Leave', 'Late', 'Half-Day', 'Off']

    if not month or not year or not project_id or not district_id:
        return None

    _, ndays = monthrange(year, month)
    start_d = date(year, month, 1)
    end_d = date(year, month, ndays)
    day_headers = [date(year, month, d) for d in range(1, ndays + 1)]
    report_title = f'Day Wise Attendance — {start_d.strftime("%d-%b-%Y")} to {end_d.strftime("%d-%b-%Y")}'
    empty_totals = {s: 0 for s in status_columns}

    # Same driver pool + assignment rules as TRA Attendance Sheet
    eligible_ids = _tra_report_driver_ids_for_month(
        start_d,
        end_d,
        project_id,
        district_id,
        vehicle_id,
        None,
        scope_projects,
        scope_districts,
        scope_vehicles,
        scope_shifts,
    )
    if driver_id_filter:
        eligible_ids = {driver_id_filter} if driver_id_filter in eligible_ids else set()
    if not eligible_ids:
        return {
            'report': [],
            'day_headers': day_headers,
            'report_title': report_title,
            'ndays': ndays,
            'grand_totals': empty_totals,
            'status_columns': status_columns,
        }

    drivers = (
        Driver.query.filter(Driver.id.in_(eligible_ids))
        .order_by(Driver.name)
        .all()
    )
    tra_cache = _TraMonthCache(start_d, end_d, eligible_ids)
    tra_cache.load()
    tra_cache.prewarm(drivers)

    att_by_driver = {did: [] for did in eligible_ids}
    att_rows = (
        DriverAttendance.query.options(
            joinedload(DriverAttendance.driver).joinedload(Driver.vehicle),
        )
        .filter(
            DriverAttendance.driver_id.in_(eligible_ids),
            DriverAttendance.attendance_date >= start_d,
            DriverAttendance.attendance_date <= end_d,
        )
        .order_by(DriverAttendance.attendance_date, DriverAttendance.attendance_segment)
        .all()
    )
    for r in att_rows:
        if not _attendance_record_counts_in_report(r):
            continue
        att_by_driver[r.driver_id].append(r)

    report = []
    grand_totals = {s: 0 for s in status_columns}
    for d in drivers:
        if not tra_cache.driver_on_duty_in_month(d):
            continue

        records = att_by_driver.get(d.id, [])
        for segment in tra_cache.segments(d):
            eff = segment['eff']
            seg_start = segment['segment_start']
            seg_end = segment['segment_end']
            eff_vehicle_id = eff.get('vehicle_id')

            if search and not _tra_search_matches(search, d, eff):
                continue
            if not _tra_driver_matches_scope(
                eff,
                project_id,
                district_id,
                vehicle_id,
                None,
                scope_projects,
                scope_districts,
                scope_vehicles,
                scope_shifts,
            ):
                continue

            vehicle = eff.get('vehicle')
            display_district = eff.get('district')
            display_project = eff.get('project')
            grid = {}
            status_totals = {s: 0 for s in status_columns}

            for r in records:
                att_d = r.attendance_date
                if att_d < seg_start or att_d > seg_end:
                    continue
                if not tra_cache.driver_duty_on_date(d.id, att_d):
                    continue
                if tra_cache.vehicle_id_on_date(d.id, att_d) != eff_vehicle_id:
                    continue

                day_num = att_d.day
                slot = _attendance_daily_slot_key(r, driver=d, vehicle=vehicle)
                status = (r.status or '').strip()
                abbr = _attendance_status_abbr(status)
                if day_num not in grid:
                    grid[day_num] = {}
                grid[day_num][slot] = {'v': abbr, 'tip': _attendance_daily_cell_tooltip(r)}
                if status in status_totals:
                    status_totals[status] += 1
                    grand_totals[status] += 1

            left_rec = tra_cache.left_rec(d.id)
            left_date = None
            if left_rec and left_rec.change_date and start_d <= left_rec.change_date <= end_d:
                left_date = left_rec.change_date
            _daily_attendance_fill_segment_boundary_cells(
                grid, year, month, seg_start, seg_end, segment, d, left_date, tra_cache,
            )
            lifecycle_badges = _daily_attendance_row_lifecycle_badges(
                d, segment, tra_cache, start_d, end_d, seg_start,
            )

            report.append({
                'district_name': (
                    (display_district.name if display_district else None)
                    or (vehicle.district.name if vehicle and vehicle.district else None)
                    or '-'
                ),
                'project_name': (
                    (display_project.name if display_project else None)
                    or (vehicle.project.name if vehicle and vehicle.project else None)
                    or '-'
                ),
                'vehicle_no': (vehicle.vehicle_no if vehicle else '-') or '-',
                'shift': (eff.get('shift') or d.shift or '-') or '-',
                'driver_name': (d.name or '-') or '-',
                'date_of_leaving': left_date,
                'lifecycle_badges': lifecycle_badges,
                'month_present_days': _count_month_present_days(grid),
                'days_in_month': ndays,
                'grid': grid,
                'status_totals': status_totals,
            })

    report.sort(key=lambda row: (row.get('driver_name') or '', row.get('vehicle_no') or ''))

    return {
        'report': report,
        'day_headers': day_headers,
        'report_title': report_title,
        'ndays': ndays,
        'grand_totals': grand_totals,
        'status_columns': status_columns,
    }


def _daily_attendance_slot_day_totals(report, ndays):
    """Per-day M/E counts across all drivers (for Excel total row)."""
    totals = {(day, slot): 0 for day in range(1, ndays + 1) for slot in ('M', 'E')}
    for row in report:
        grid = row.get('grid') or {}
        for day in range(1, ndays + 1):
            slots = grid.get(day) or {}
            for slot in ('M', 'E'):
                cell = slots.get(slot) or {}
                if _daily_attendance_grid_cell_skip_totals(cell):
                    continue
                if _daily_attendance_grid_cell_value(cell):
                    totals[(day, slot)] += 1
    return totals


def _generate_driver_daily_attendance_excel(payload):
    """Export formatted Day Wise Attendance Report (.xlsx)."""
    report = payload['report']
    day_headers = payload['day_headers']
    report_title = payload['report_title']
    ndays = payload['ndays']
    grand_totals = payload['grand_totals']
    status_columns = payload['status_columns']

    info_cols = 6
    day_slot_cols = ndays * 2
    sum_cols = len(status_columns)
    last_col = info_cols + day_slot_cols + sum_cols - 1
    hdr_row_top = 2
    hdr_row_sub = 3
    data_start = 4

    output = BytesIO()
    wb = xlsxwriter.Workbook(output, {'in_memory': True})
    ws = wb.add_worksheet('Day Wise Attendance')

    dark = '#1B4332'
    dark2 = '#2D6A4F'
    white = '#FFFFFF'
    border_white = '#FFFFFF'
    border_grey = '#CBD5E1'
    zebra = '#F8FAFC'
    total_bg = '#D1FAE5'

    title_fmt = wb.add_format({
        'bold': True, 'font_size': 16, 'font_color': white,
        'bg_color': dark, 'align': 'center', 'valign': 'vcenter',
    })
    sub_fmt = wb.add_format({
        'bold': True, 'font_size': 12, 'font_color': white,
        'bg_color': dark2, 'align': 'center', 'valign': 'vcenter',
    })
    hdr_fmt = wb.add_format({
        'bold': True, 'font_color': white, 'bg_color': dark,
        'align': 'center', 'valign': 'vcenter', 'border': 1, 'border_color': border_white,
    })
    cell_fmt = wb.add_format({
        'border': 1, 'border_color': border_grey, 'align': 'center', 'valign': 'vcenter',
    })
    cell_left_fmt = wb.add_format({
        'border': 1, 'border_color': border_grey, 'align': 'left', 'valign': 'vcenter',
    })
    zebra_fmt = wb.add_format({
        'border': 1, 'border_color': border_grey, 'align': 'center', 'valign': 'vcenter',
        'bg_color': zebra,
    })
    zebra_left_fmt = wb.add_format({
        'border': 1, 'border_color': border_grey, 'align': 'left', 'valign': 'vcenter',
        'bg_color': zebra,
    })
    ex_cell_fmt = wb.add_format({
        'border': 1, 'border_color': border_grey, 'align': 'center', 'valign': 'vcenter',
        'font_color': '#64748B', 'bg_color': '#E2E8F0', 'bold': True,
    })
    ex_cell_zebra_fmt = wb.add_format({
        'border': 1, 'border_color': border_grey, 'align': 'center', 'valign': 'vcenter',
        'font_color': '#64748B', 'bg_color': '#CBD5E1', 'bold': True,
    })
    inactive_cell_fmt = wb.add_format({
        'border': 1, 'border_color': border_grey, 'align': 'center', 'valign': 'vcenter',
        'font_color': '#94A3B8', 'bg_color': '#F8FAFC', 'italic': True,
    })
    inactive_cell_zebra_fmt = wb.add_format({
        'border': 1, 'border_color': border_grey, 'align': 'center', 'valign': 'vcenter',
        'font_color': '#94A3B8', 'bg_color': '#F1F5F9', 'italic': True,
    })
    transfer_cell_fmt = wb.add_format({
        'border': 1, 'border_color': border_grey, 'align': 'center', 'valign': 'vcenter',
        'font_color': '#1D4ED8', 'bg_color': '#DBEAFE', 'bold': True,
    })
    transfer_cell_zebra_fmt = wb.add_format({
        'border': 1, 'border_color': border_grey, 'align': 'center', 'valign': 'vcenter',
        'font_color': '#1D4ED8', 'bg_color': '#BFDBFE', 'bold': True,
    })
    total_fmt = wb.add_format({
        'bold': True, 'bg_color': total_bg, 'border': 1, 'border_color': border_grey,
        'align': 'center', 'valign': 'vcenter',
    })
    total_left_fmt = wb.add_format({
        'bold': True, 'bg_color': total_bg, 'border': 1, 'border_color': border_grey,
        'align': 'left', 'valign': 'vcenter',
    })

    ws.set_row(0, 22)
    ws.set_row(1, 18)
    ws.merge_range(0, 0, 0, last_col, 'Day Wise Attendance Report', title_fmt)
    ws.merge_range(1, 0, 1, last_col, report_title, sub_fmt)

    info_labels = ['Sr', 'District', 'Project', 'Vehicle', 'Shift', 'Driver']
    for c, label in enumerate(info_labels):
        ws.merge_range(hdr_row_top, c, hdr_row_sub, c, label, hdr_fmt)

    for i, _d in enumerate(day_headers):
        c0 = info_cols + i * 2
        ws.merge_range(hdr_row_top, c0, hdr_row_top, c0 + 1, f'{_d.day:02d}', hdr_fmt)
        ws.write(hdr_row_sub, c0, 'M', hdr_fmt)
        ws.write(hdr_row_sub, c0 + 1, 'E', hdr_fmt)

    for j, st in enumerate(status_columns):
        c = info_cols + day_slot_cols + j
        ws.merge_range(hdr_row_top, c, hdr_row_sub, c, st, hdr_fmt)

    slot_totals = _daily_attendance_slot_day_totals(report, ndays)
    row_idx = data_start
    for i, row in enumerate(report, 1):
        use_zebra = i % 2 == 0
        cf = zebra_fmt if use_zebra else cell_fmt
        lf = zebra_left_fmt if use_zebra else cell_left_fmt
        driver_label = (
            f"{row['driver_name']} ({row['month_present_days']}/{row['days_in_month']})"
        )
        ws.write(row_idx, 0, i, cf)
        ws.write(row_idx, 1, row['district_name'], lf)
        ws.write(row_idx, 2, row['project_name'], lf)
        ws.write(row_idx, 3, row['vehicle_no'], lf)
        ws.write(row_idx, 4, row['shift'], lf)
        ws.write(row_idx, 5, driver_label, lf)
        grid = row.get('grid') or {}
        for day in range(1, ndays + 1):
            slots = grid.get(day) or {}
            for si, slot in enumerate(('M', 'E')):
                cell = slots.get(slot) or {}
                v = _daily_attendance_grid_cell_value(cell)
                if isinstance(cell, dict) and cell.get('kind') == 'left':
                    slot_cf = ex_cell_zebra_fmt if use_zebra else ex_cell_fmt
                elif isinstance(cell, dict) and cell.get('kind') == 'inactive':
                    slot_cf = inactive_cell_zebra_fmt if use_zebra else inactive_cell_fmt
                elif isinstance(cell, dict) and cell.get('kind') == 'transfer':
                    slot_cf = transfer_cell_zebra_fmt if use_zebra else transfer_cell_fmt
                else:
                    slot_cf = cf
                ws.write(row_idx, info_cols + (day - 1) * 2 + si, v or '', slot_cf)
        for j, st in enumerate(status_columns):
            ws.write(row_idx, info_cols + day_slot_cols + j, row['status_totals'].get(st, 0), cf)
        row_idx += 1

    ws.write(row_idx, 0, 'Total', total_left_fmt)
    for c in range(1, info_cols):
        ws.write(row_idx, c, '', total_fmt)
    for day in range(1, ndays + 1):
        for si, slot in enumerate(('M', 'E')):
            ws.write(row_idx, info_cols + (day - 1) * 2 + si, slot_totals.get((day, slot), 0), total_fmt)
    for j, st in enumerate(status_columns):
        ws.write(row_idx, info_cols + day_slot_cols + j, grand_totals.get(st, 0), total_fmt)

    data_end = row_idx
    att_first = info_cols
    att_last = info_cols + day_slot_cols - 1
    if data_end >= data_start and att_last >= att_first:
        green_fmt = wb.add_format({'font_color': '#166534', 'border': 1, 'border_color': border_grey})
        red_fmt = wb.add_format({'font_color': '#991b1b', 'border': 1, 'border_color': border_grey})
        ws.conditional_format(data_start, att_first, data_end, att_last, {
            'type': 'text', 'criteria': 'containing', 'value': 'P', 'format': green_fmt,
        })
        ws.conditional_format(data_start, att_first, data_end, att_last, {
            'type': 'text', 'criteria': 'containing', 'value': 'A', 'format': red_fmt,
        })

    ws.freeze_panes(data_start, info_cols)
    ws.autofilter(hdr_row_sub, 0, data_end, last_col)

    ws.set_column(0, 0, 5)
    ws.set_column(1, 4, 14)
    ws.set_column(5, 5, 32)
    if day_slot_cols:
        ws.set_column(info_cols, info_cols + day_slot_cols - 1, 3.5)
    if sum_cols:
        ws.set_column(info_cols + day_slot_cols, last_col, 9)

    wb.close()
    output.seek(0)
    fname = f"Day_Wise_Attendance_{pk_now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return send_file(
        output,
        download_name=fname,
        as_attachment=True,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )


@app.route('/driver-attendance/daily-report/export')
def driver_attendance_daily_report_export():
    """Download formatted Day Wise Attendance Report as .xlsx."""
    from auth_utils import get_user_context

    if not user_can_access(session.get('permissions') or [], 'driver_attendance_daily_report'):
        flash('Access denied.', 'danger')
        return redirect(url_for('driver_attendance_daily_report'))

    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    scope_projects = list(user_context.get('allowed_projects') or [])
    scope_districts = list(user_context.get('allowed_districts') or [])
    scope_vehicles = list(user_context.get('allowed_vehicles') or [])
    scope_shifts = list(user_context.get('allowed_shifts') or [])

    month = request.args.get('month', type=int)
    year = request.args.get('year', type=int)
    project_id = request.args.get('project_id', type=int) or 0
    district_id = request.args.get('district_id', type=int) or 0
    if scope_projects and len(scope_projects) == 1:
        project_id = scope_projects[0]
    if scope_districts and len(scope_districts) == 1:
        district_id = scope_districts[0]

    vehicle_id = request.args.get('vehicle_id', type=int) or 0
    if vehicle_id == 0:
        vehicle_id = None
    driver_id_filter = request.args.get('driver_id', type=int) or 0
    search = (request.args.get('search') or '').strip()

    if not project_id or not district_id:
        flash('Excel export ke liye Project aur District select karein.', 'warning')
        return redirect(url_for('driver_attendance_daily_report'))

    payload = _build_driver_daily_attendance_report_payload(
        month, year, project_id, district_id,
        vehicle_id=vehicle_id,
        driver_id_filter=driver_id_filter,
        search=search,
        scope_projects=scope_projects,
        scope_districts=scope_districts,
        scope_vehicles=scope_vehicles,
        scope_shifts=scope_shifts,
    )
    if not payload or not payload.get('report'):
        flash('Is filter par koi data nahi mila.', 'warning')
        return redirect(url_for('driver_attendance_daily_report'))

    return _generate_driver_daily_attendance_excel(payload)


@app.route('/driver-attendance/daily-report', methods=['GET', 'POST'])
def driver_attendance_daily_report():
    """Day-wise attendance grid: M/E slots per calendar day (complete check-in + check-out only)."""
    from auth_utils import get_user_context
    from calendar import monthrange
    from datetime import date

    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    allowed_shifts = user_context.get('allowed_shifts', set())

    scope_projects = list(allowed_projects) if allowed_projects else []
    scope_districts = list(allowed_districts) if allowed_districts else []
    scope_vehicles = list(allowed_vehicles) if allowed_vehicles else []
    scope_shifts = list(allowed_shifts) if allowed_shifts else []

    form = DriverAttendanceReportForm()
    has_single_scope = bool(
        scope_projects and len(scope_projects) == 1 and
        scope_districts and len(scope_districts) == 1 and
        scope_vehicles and len(scope_vehicles) == 1 and
        scope_shifts and len(scope_shifts) == 1
    )
    single_vehicle = db.session.get(Vehicle, scope_vehicles[0]) if has_single_scope and scope_vehicles else None

    disable_project = bool(scope_projects and len(scope_projects) == 1)
    disable_district = bool(scope_districts and len(scope_districts) == 1)

    project_query = Project.query.filter(Project.company_id.isnot(None))
    if scope_projects:
        project_query = project_query.filter(Project.id.in_(scope_projects))
    form.project_id.choices = [(0, '-- Select Project --')] + [(p.id, p.name) for p in project_query.order_by(Project.name).all()]

    if disable_project:
        form.project_id.data = scope_projects[0]
    if disable_district:
        form.district_id.data = scope_districts[0]

    if request.method == 'POST':
        try:
            pid = request.form.get('project_id', type=int) or 0
        except (TypeError, ValueError):
            pid = 0
        if not pid and disable_project and scope_projects:
            pid = scope_projects[0]
        if pid and pid != 0:
            districts_query = District.query.join(project_district).filter(project_district.c.project_id == pid)
        else:
            districts_query = District.query.filter(False)
        if scope_districts:
            districts_query = districts_query.filter(District.id.in_(scope_districts))
        districts = districts_query.order_by(District.name).all()
        form.district_id.choices = [(0, '-- Select District --')] + [(d.id, d.name) for d in districts]
    else:
        districts_query = District.query
        if scope_districts:
            districts_query = districts_query.filter(District.id.in_(scope_districts))
        districts = districts_query.order_by(District.name).all()
        form.district_id.choices = [(0, '-- Select District --')] + [(d.id, d.name) for d in districts]

    today = pk_date()
    form.month.data = form.month.data or today.month
    form.year.data = form.year.data or today.year

    report = []
    day_headers = []
    report_title = ''
    filter_message = None
    selected_vehicle_id = 0
    vehicle_choices = []
    ndays = 0
    grand_totals = {}
    status_columns = ['Present', 'Absent', 'Leave', 'Late', 'Half-Day', 'Off']

    def _build_vehicle_choices(pid, did):
        vq = Vehicle.query.filter(Vehicle.project_id.isnot(None))
        if scope_projects:
            vq = vq.filter(Vehicle.project_id.in_(scope_projects))
        if scope_districts:
            vq = vq.filter(Vehicle.district_id.in_(scope_districts))
        if scope_vehicles:
            vq = vq.filter(Vehicle.id.in_(scope_vehicles))
        if pid:
            vq = vq.filter(Vehicle.project_id == pid)
        if did:
            vq = vq.filter(Vehicle.district_id == did)
        out = []
        for v in vq.order_by(*vehicle_order_by()).all():
            label = v.vehicle_no + ((' (' + v.vehicle_type + ')') if v.vehicle_type else '')
            out.append((v.id, label))
        return out

    if request.method == 'POST':
        try:
            selected_vehicle_id = request.form.get('vehicle_id', type=int) or 0
        except (TypeError, ValueError):
            selected_vehicle_id = 0
        pid = form.project_id.data or 0
        did = form.district_id.data or 0
        vehicle_choices = _build_vehicle_choices(pid, did)

        project_id_early = int(form.project_id.data or 0)
        district_id_early = int(form.district_id.data or 0)
        if disable_project and scope_projects:
            project_id_early = scope_projects[0]
        if disable_district and scope_districts:
            district_id_early = scope_districts[0]
        if not project_id_early or not district_id_early:
            if not project_id_early and not district_id_early:
                filter_message = 'Pehle Project aur District select karein, phir Show button dabayein.'
            elif not project_id_early:
                filter_message = 'Pehle Project select karein, phir Show button dabayein.'
            else:
                filter_message = 'Pehle District select karein, phir Show button dabayein.'

    if request.method == 'POST' and not filter_message and form.validate_on_submit():
        month = form.month.data
        year = form.year.data
        project_id = int(form.project_id.data or 0)
        district_id = int(form.district_id.data or 0)
        if disable_project and scope_projects:
            project_id = scope_projects[0]
        if disable_district and scope_districts:
            district_id = scope_districts[0]

        if project_id and district_id:
            vehicle_id = request.form.get('vehicle_id', type=int) or 0
            if vehicle_id == 0:
                vehicle_id = None
            search = (form.search.data or '').strip()
            driver_id_filter = request.form.get('driver_id', type=int) or 0
            payload = _build_driver_daily_attendance_report_payload(
                month, year, project_id, district_id,
                vehicle_id=vehicle_id,
                driver_id_filter=driver_id_filter,
                search=search,
                scope_projects=scope_projects,
                scope_districts=scope_districts,
                scope_vehicles=scope_vehicles,
                scope_shifts=scope_shifts,
            )
            if payload:
                report = payload['report']
                day_headers = payload['day_headers']
                report_title = payload['report_title']
                ndays = payload['ndays']
                grand_totals = payload['grand_totals']

    district_options = [{'id': d.id, 'name': d.name} for d in (
        District.query.filter(District.id.in_(scope_districts)).order_by(District.name).all()
        if scope_districts else District.query.order_by(District.name).all()
    )]

    vd_q = Driver.query.filter(Driver.status == 'Active', Driver.vehicle_id.isnot(None))
    if scope_projects:
        vd_q = vd_q.filter(Driver.project_id.in_(scope_projects))
    if scope_vehicles:
        vd_q = vd_q.filter(Driver.vehicle_id.in_(scope_vehicles))
    vehicle_drivers = vd_q.order_by(Driver.name).all()
    selected_driver_id = (request.form.get('driver_id', type=int) or 0) if request.method == 'POST' else 0

    cal_today_day = None
    if report is not None:
        try:
            _m = int(form.month.data)
            _y = int(form.year.data)
            _today = date.today()
            if _m == _today.month and _y == _today.year:
                cal_today_day = _today.day
        except (TypeError, ValueError):
            cal_today_day = None

    return render_template(
        'driver_attendance_daily_report.html',
        form=form,
        report=report,
        day_headers=day_headers,
        report_title=report_title,
        ndays=ndays,
        single_vehicle=single_vehicle,
        has_single_scope=has_single_scope,
        selected_vehicle_id=selected_vehicle_id,
        vehicle_choices=vehicle_choices,
        disable_project=disable_project,
        disable_district=disable_district,
        vehicle_drivers=vehicle_drivers,
        selected_driver_id=selected_driver_id,
        district_options=district_options,
        grand_totals=grand_totals,
        status_columns=status_columns,
        filter_message=filter_message,
        cal_today_day=cal_today_day,
        **_nav_back_ctx(url_for('reports_index'), show_without_nav_from=True),
    )


def _tra_pack_rejoin_assignment(rejoin_rec):
    """Assignment captured on Driver Rejoin form."""
    return {
        'vehicle': rejoin_rec.new_vehicle,
        'vehicle_id': rejoin_rec.new_vehicle_id,
        'project': rejoin_rec.new_project,
        'district': rejoin_rec.new_district,
        'shift': rejoin_rec.new_shift,
    }


def _tra_status_events_up_to(driver_id, on_date, status_events=None):
    """Left/rejoin timeline up to and including on_date (ascending)."""
    if status_events is not None:
        return [ev for ev in status_events if ev.change_date and ev.change_date <= on_date]
    return (
        DriverStatusChange.query.filter(
            DriverStatusChange.driver_id == driver_id,
            DriverStatusChange.action_type.in_(['left', 'rejoin']),
            DriverStatusChange.change_date <= on_date,
        )
        .order_by(DriverStatusChange.change_date.asc(), DriverStatusChange.id.asc())
        .all()
    )


def _tra_applicable_rejoin_on_date(driver_id, on_date, status_events=None):
    """Latest rejoin effective on on_date (must follow a prior left)."""
    events = _tra_status_events_up_to(driver_id, on_date, status_events)
    last_left = None
    applicable = None
    for ev in events:
        if ev.action_type == 'left':
            last_left = ev
            applicable = None
        elif (
            ev.action_type == 'rejoin'
            and last_left
            and ev.change_date
            and last_left.change_date
            and ev.change_date > last_left.change_date
        ):
            applicable = ev
    if applicable and applicable.change_date and applicable.change_date <= on_date:
        return applicable
    return None


def _tra_driver_duty_active_on_date(driver, on_date, status_events=None):
    """On duty on a calendar day — respects assign_date and left/rejoin cycles."""
    if driver.assign_date and on_date < driver.assign_date:
        return False
    events = _tra_status_events_up_to(driver.id, on_date, status_events)
    last_left = None
    last_rejoin = None
    for ev in events:
        if ev.action_type == 'left' and ev.change_date and ev.change_date <= on_date:
            last_left = ev.change_date
        elif ev.action_type == 'rejoin' and ev.change_date and ev.change_date <= on_date:
            last_rejoin = ev.change_date
    if last_left is None:
        return True
    if last_rejoin and last_rejoin >= last_left:
        return True
    if (
        driver.vehicle_id
        and driver.assign_date
        and driver.assign_date > last_left
        and driver.assign_date <= on_date
    ):
        return True
    return False


def _tra_effective_assignment(driver, left_rec=None, rejoin_rec=None):
    """Project/vehicle/district/shift for TRA row when Job Left cleared current assignment."""
    if driver and driver.vehicle_id and driver.vehicle:
        return {
            'vehicle': driver.vehicle,
            'vehicle_id': driver.vehicle_id,
            'project': driver.project,
            'district': driver.district,
            'shift': driver.shift,
        }
    if rejoin_rec and rejoin_rec.new_vehicle_id:
        return _tra_pack_rejoin_assignment(rejoin_rec)
    if left_rec:
        veh = left_rec.left_vehicle
        return {
            'vehicle': veh,
            'vehicle_id': left_rec.left_vehicle_id,
            'project': left_rec.left_project,
            'district': left_rec.left_district,
            'shift': left_rec.left_shift,
        }
    return {
        'vehicle': None,
        'vehicle_id': None,
        'project': None,
        'district': None,
        'shift': None,
    }


def _tra_pack_transfer_side(transfer, side):
    if side == 'old':
        return {
            'vehicle': transfer.old_vehicle,
            'vehicle_id': transfer.old_vehicle_id,
            'project': transfer.old_project,
            'district': transfer.old_district,
            'shift': transfer.old_shift,
        }
    return {
        'vehicle': transfer.new_vehicle,
        'vehicle_id': transfer.new_vehicle_id,
        'project': transfer.new_project,
        'district': transfer.new_district,
        'shift': transfer.new_shift,
    }


def _tra_non_shift_transfer_filter():
    return db.or_(DriverTransfer.is_shift_only == False, DriverTransfer.is_shift_only.is_(None))


def _tra_assignment_for_report_month(driver, left_rec, start_d, end_d):
    """Vehicle/project/district/shift as they were during the report month (not current assignment)."""
    rejoin_during = DriverStatusChange.query.filter(
        DriverStatusChange.driver_id == driver.id,
        DriverStatusChange.action_type == 'rejoin',
        DriverStatusChange.change_date >= start_d,
        DriverStatusChange.change_date <= end_d,
    ).order_by(DriverStatusChange.change_date.desc(), DriverStatusChange.id.desc()).first()
    if not driver.vehicle_id and rejoin_during and rejoin_during.new_vehicle_id:
        return _tra_pack_rejoin_assignment(rejoin_during)
    if not driver.vehicle_id and left_rec:
        if left_rec.change_date and left_rec.change_date > end_d:
            return _tra_effective_assignment(driver, left_rec)
        if left_rec.change_date and left_rec.change_date < start_d:
            return _tra_effective_assignment(driver, left_rec)
        if left_rec.change_date and start_d <= left_rec.change_date <= end_d:
            return _tra_effective_assignment(driver, left_rec)

    sf = _tra_non_shift_transfer_filter()

    future_t = DriverTransfer.query.filter(
        DriverTransfer.driver_id == driver.id,
        sf,
        DriverTransfer.transfer_date > end_d,
    ).order_by(DriverTransfer.transfer_date.asc(), DriverTransfer.id.asc()).first()
    if future_t:
        return _tra_pack_transfer_side(future_t, 'old')

    during_t = DriverTransfer.query.filter(
        DriverTransfer.driver_id == driver.id,
        sf,
        DriverTransfer.transfer_date >= start_d,
        DriverTransfer.transfer_date <= end_d,
    ).order_by(DriverTransfer.transfer_date.desc(), DriverTransfer.id.desc()).first()
    if during_t:
        return _tra_pack_transfer_side(during_t, 'new')

    before_t = DriverTransfer.query.filter(
        DriverTransfer.driver_id == driver.id,
        sf,
        DriverTransfer.transfer_date < start_d,
    ).order_by(DriverTransfer.transfer_date.desc(), DriverTransfer.id.desc()).first()
    if before_t:
        return _tra_pack_transfer_side(before_t, 'new')

    return _tra_effective_assignment(driver, left_rec)


def _tra_assignment_as_of(driver, left_rec, as_of_date):
    """Vehicle assignment on a specific calendar date."""
    if not driver.vehicle_id and left_rec:
        if left_rec.change_date and left_rec.change_date > as_of_date:
            return _tra_effective_assignment(driver, left_rec)
        if left_rec.change_date and left_rec.change_date <= as_of_date:
            return _tra_effective_assignment(driver, left_rec)

    sf = _tra_non_shift_transfer_filter()
    future_t = DriverTransfer.query.filter(
        DriverTransfer.driver_id == driver.id,
        sf,
        DriverTransfer.transfer_date > as_of_date,
    ).order_by(DriverTransfer.transfer_date.asc(), DriverTransfer.id.asc()).first()
    if future_t:
        return _tra_pack_transfer_side(future_t, 'old')

    past_t = DriverTransfer.query.filter(
        DriverTransfer.driver_id == driver.id,
        sf,
        DriverTransfer.transfer_date <= as_of_date,
    ).order_by(DriverTransfer.transfer_date.desc(), DriverTransfer.id.desc()).first()
    if past_t:
        if past_t.transfer_date == as_of_date:
            return _tra_pack_transfer_side(past_t, 'old')
        return _tra_pack_transfer_side(past_t, 'new')

    return _tra_effective_assignment(driver, left_rec)


def _tra_driver_duty_on_date(driver, left_rec, on_date):
    return _tra_driver_duty_active_on_date(driver, on_date)


def _tra_vehicle_id_from_transfer_list(transfers, on_date, driver=None, left_rec=None):
    """Vehicle on a calendar date from non-shift transfer history (transfer day = last day on old vehicle)."""
    future = [t for t in transfers if t.transfer_date > on_date]
    if future:
        return future[0].old_vehicle_id
    past = [t for t in transfers if t.transfer_date <= on_date]
    if past:
        t = past[-1]
        if t.transfer_date == on_date:
            return t.old_vehicle_id
        return t.new_vehicle_id
    if driver and driver.vehicle_id:
        return driver.vehicle_id
    if left_rec:
        return left_rec.left_vehicle_id
    return None


def _tra_build_in_month_transfer_segments(
    transfers,
    start_d,
    end_d,
    driver,
    left_date,
    rejoin_rec,
):
    """
    Build vehicle segments for in-month transfers.
    Transfer date D is the last day on the old vehicle; new vehicle starts D+1.
    """
    segments = []
    cursor = start_d
    for t in transfers:
        t_date = t.transfer_date
        old_eff = _tra_pack_transfer_side(t, 'old')
        if t_date >= cursor and old_eff.get('vehicle_id'):
            seg_s, seg_e = _tra_clamp_segment_bounds(
                cursor, t_date, start_d, end_d, driver.assign_date, left_date,
            )
            if rejoin_rec and rejoin_rec.change_date and seg_s and rejoin_rec.change_date > seg_s:
                seg_s = max(seg_s, rejoin_rec.change_date)
            if seg_s is not None and seg_s <= seg_e:
                segments.append({
                    'eff': old_eff,
                    'segment_start': seg_s,
                    'segment_end': seg_e,
                    'transfer_in': None,
                    'transfer_out': t,
                })
        cursor = t_date + timedelta(days=1)

    if transfers and cursor <= end_d:
        last_t = transfers[-1]
        new_eff = _tra_pack_transfer_side(last_t, 'new')
        if new_eff.get('vehicle_id'):
            seg_s, seg_e = _tra_clamp_segment_bounds(
                cursor, end_d, start_d, end_d, driver.assign_date, left_date,
            )
            if rejoin_rec and rejoin_rec.change_date and seg_s and rejoin_rec.change_date > seg_s:
                seg_s = max(seg_s, rejoin_rec.change_date)
            if seg_s is not None and seg_s <= seg_e:
                segments.append({
                    'eff': new_eff,
                    'segment_start': seg_s,
                    'segment_end': seg_e,
                    'transfer_in': last_t,
                    'transfer_out': None,
                })
    return segments


def _tra_clamp_segment_bounds(seg_start, seg_end, month_start, month_end, assign_date, left_date):
    seg_s = max(seg_start, month_start)
    seg_e = min(seg_end, month_end)
    if assign_date and assign_date > seg_s:
        if assign_date > seg_e:
            return None, None
        seg_s = assign_date
    if left_date and left_date < seg_e:
        seg_e = left_date
    if seg_s > seg_e:
        return None, None
    return seg_s, seg_e


def _tra_driver_vehicle_segments(driver, left_rec, start_d, end_d):
    """One segment per vehicle stint when driver transfers mid-month."""
    sf = _tra_non_shift_transfer_filter()
    left_date = None
    if left_rec and left_rec.change_date and start_d <= left_rec.change_date <= end_d:
        left_date = left_rec.change_date

    rejoin_rec = DriverStatusChange.query.filter(
        DriverStatusChange.driver_id == driver.id,
        DriverStatusChange.action_type == 'rejoin',
        DriverStatusChange.change_date >= start_d,
        DriverStatusChange.change_date <= end_d,
    ).order_by(DriverStatusChange.change_date.desc()).first()

    transfers = DriverTransfer.query.filter(
        DriverTransfer.driver_id == driver.id,
        sf,
        DriverTransfer.transfer_date >= start_d,
        DriverTransfer.transfer_date <= end_d,
    ).order_by(DriverTransfer.transfer_date.asc(), DriverTransfer.id.asc()).all()

    segments = []

    if not transfers:
        eff = _tra_assignment_for_report_month(driver, left_rec, start_d, end_d)
        if not eff.get('vehicle_id'):
            return []
        seg_s, seg_e = _tra_clamp_segment_bounds(
            start_d, end_d, start_d, end_d, driver.assign_date, left_date
        )
        if rejoin_rec and rejoin_rec.change_date and seg_s and rejoin_rec.change_date > seg_s:
            seg_s = max(seg_s, rejoin_rec.change_date)
        if seg_s is None or seg_s > seg_e:
            return []
        segments.append({
            'eff': eff,
            'segment_start': seg_s,
            'segment_end': seg_e,
            'transfer_in': None,
            'transfer_out': None,
        })
        return segments

    return _tra_build_in_month_transfer_segments(
        transfers, start_d, end_d, driver, left_date, rejoin_rec,
    )


def _tra_count_drivers_on_vehicle_day(vehicle_id, on_date, month_start, month_end):
    """How many drivers were assigned to this vehicle on a calendar date."""
    candidate_ids = _tra_vehicle_driver_ids_in_month(vehicle_id, month_start, month_end)
    count = 0
    for pid in candidate_ids:
        partner = db.session.get(Driver, pid)
        if not partner:
            continue
        p_left = _tra_status_rec(pid, 'left')
        if not _tra_driver_duty_on_date(partner, p_left, on_date):
            continue
        eff = _tra_assignment_as_of(partner, p_left, on_date)
        if eff.get('vehicle_id') == vehicle_id:
            count += 1
    return count


def _tra_segment_solo_days(vehicle_id, seg_start, seg_end, month_start, month_end):
    """Days in segment with only one driver on vehicle (eligible for double duty)."""
    solo = 0
    d = seg_start
    while d <= seg_end:
        if _tra_count_drivers_on_vehicle_day(vehicle_id, d, month_start, month_end) == 1:
            solo += 1
        d += timedelta(days=1)
    return solo


def _tra_search_matches(search, driver, eff):
    tokens = [t for t in (search or '').split() if t]
    if not tokens:
        return True
    veh_no = eff.get('vehicle').vehicle_no if eff.get('vehicle') else ''
    haystacks = [driver.name or '', driver.driver_id or '', veh_no]
    return all(
        any(tok.lower() in (h or '').lower() for h in haystacks)
        for tok in tokens
    )


def _tra_driver_matches_scope(
    eff,
    project_id,
    district_id,
    vehicle_id,
    shift,
    scope_projects,
    scope_districts,
    scope_vehicles,
    scope_shifts,
):
    """Whether effective assignment matches TRA report filters."""
    veh = eff.get('vehicle')
    veh_id = eff.get('vehicle_id')
    proj_id = eff.get('project').id if eff.get('project') else None
    dist_id = eff.get('district').id if eff.get('district') else (
        veh.district_id if veh else None
    )
    eff_shift = eff.get('shift')

    if scope_projects and proj_id not in scope_projects and not (
        veh and veh.project_id in scope_projects
    ):
        return False
    if scope_districts and dist_id not in scope_districts:
        return False
    if scope_vehicles and veh_id not in scope_vehicles:
        return False
    if scope_shifts and eff_shift not in scope_shifts:
        return False
    if project_id and proj_id != project_id and not (veh and veh.project_id == project_id):
        return False
    if district_id and dist_id != district_id:
        return False
    if vehicle_id and veh_id != vehicle_id:
        return False
    if shift and eff_shift != shift:
        return False
    return True


def _tra_driver_on_duty_in_month(driver_id, start_d, end_d, assign_date):
    """Whether driver belongs on TRA sheet for this calendar month."""
    if assign_date and assign_date > end_d:
        has_att = DriverAttendance.query.filter(
            DriverAttendance.driver_id == driver_id,
            DriverAttendance.attendance_date >= start_d,
            DriverAttendance.attendance_date <= end_d,
        ).first()
        if has_att:
            return True
        sf = _tra_non_shift_transfer_filter()
        transferred_in_month = DriverTransfer.query.filter(
            DriverTransfer.driver_id == driver_id,
            sf,
            DriverTransfer.transfer_date >= start_d,
            DriverTransfer.transfer_date <= end_d,
        ).first()
        if transferred_in_month:
            return True
        rejoined_in_month = DriverStatusChange.query.filter(
            DriverStatusChange.driver_id == driver_id,
            DriverStatusChange.action_type == 'rejoin',
            DriverStatusChange.change_date >= start_d,
            DriverStatusChange.change_date <= end_d,
        ).first()
        if rejoined_in_month:
            return True
        left_in_month = DriverStatusChange.query.filter(
            DriverStatusChange.driver_id == driver_id,
            DriverStatusChange.action_type == 'left',
            DriverStatusChange.change_date >= start_d,
            DriverStatusChange.change_date <= end_d,
        ).first()
        return left_in_month is not None

    left_before_month = DriverStatusChange.query.filter(
        DriverStatusChange.driver_id == driver_id,
        DriverStatusChange.action_type == 'left',
        DriverStatusChange.change_date < start_d,
    ).order_by(DriverStatusChange.change_date.desc()).first()

    if left_before_month:
        driver = db.session.get(Driver, driver_id)
        if (
            driver
            and driver.vehicle_id
            and assign_date
            and assign_date > left_before_month.change_date
            and assign_date <= end_d
        ):
            return True
        rejoined = DriverStatusChange.query.filter(
            DriverStatusChange.driver_id == driver_id,
            DriverStatusChange.action_type == 'rejoin',
            DriverStatusChange.change_date > left_before_month.change_date,
            DriverStatusChange.change_date <= end_d,
        ).first()
        if not rejoined:
            return False

    return True


def _tra_report_driver_ids_for_month(
    start_d,
    end_d,
    project_id,
    district_id,
    vehicle_id,
    shift,
    scope_projects,
    scope_districts,
    scope_vehicles,
    scope_shifts,
):
    """Drivers on TRA sheet: currently assigned or who worked during the selected month."""
    ids = set()

    assigned_q = Driver.query.filter(
        Driver.vehicle_id.isnot(None),
    ).outerjoin(Vehicle, Driver.vehicle_id == Vehicle.id)
    if scope_projects:
        assigned_q = assigned_q.filter(
            db.or_(Driver.project_id.in_(scope_projects), Vehicle.project_id.in_(scope_projects))
        )
    if scope_districts:
        assigned_q = assigned_q.filter(
            db.or_(Driver.district_id.in_(scope_districts), Vehicle.district_id.in_(scope_districts))
        )
    if scope_vehicles:
        assigned_q = assigned_q.filter(Driver.vehicle_id.in_(scope_vehicles))
    if scope_shifts:
        assigned_q = assigned_q.filter(Driver.shift.in_(scope_shifts))
    if project_id:
        assigned_q = assigned_q.filter(
            db.or_(Driver.project_id == project_id, Vehicle.project_id == project_id)
        )
    if district_id:
        assigned_q = assigned_q.filter(
            db.or_(Driver.district_id == district_id, Vehicle.district_id == district_id)
        )
    if vehicle_id:
        assigned_q = assigned_q.filter(Driver.vehicle_id == vehicle_id)
    if shift:
        assigned_q = assigned_q.filter(Driver.shift == shift)
    for row in assigned_q.with_entities(Driver.id).distinct():
        ids.add(row[0])

    att_q = DriverAttendance.query.filter(
        DriverAttendance.attendance_date >= start_d,
        DriverAttendance.attendance_date <= end_d,
    )
    if project_id:
        att_q = att_q.filter(DriverAttendance.project_id == project_id)
    for row in att_q.with_entities(DriverAttendance.driver_id).distinct():
        ids.add(row[0])

    worked_left_q = DriverStatusChange.query.join(Driver).filter(
        DriverStatusChange.action_type == 'left',
        db.or_(
            db.and_(
                DriverStatusChange.change_date >= start_d,
                DriverStatusChange.change_date <= end_d,
            ),
            db.and_(
                DriverStatusChange.change_date > end_d,
                db.or_(Driver.assign_date.is_(None), Driver.assign_date <= end_d),
            ),
        ),
    )
    if scope_projects:
        worked_left_q = worked_left_q.filter(
            DriverStatusChange.left_project_id.in_(scope_projects)
        )
    if scope_districts:
        worked_left_q = worked_left_q.filter(
            DriverStatusChange.left_district_id.in_(scope_districts)
        )
    if scope_vehicles:
        worked_left_q = worked_left_q.filter(
            DriverStatusChange.left_vehicle_id.in_(scope_vehicles)
        )
    if scope_shifts:
        worked_left_q = worked_left_q.filter(
            DriverStatusChange.left_shift.in_(scope_shifts)
        )
    if project_id:
        worked_left_q = worked_left_q.filter(
            DriverStatusChange.left_project_id == project_id
        )
    if district_id:
        worked_left_q = worked_left_q.filter(
            DriverStatusChange.left_district_id == district_id
        )
    if vehicle_id:
        worked_left_q = worked_left_q.filter(
            DriverStatusChange.left_vehicle_id == vehicle_id
        )
    if shift:
        worked_left_q = worked_left_q.filter(
            DriverStatusChange.left_shift == shift
        )
    for row in worked_left_q.with_entities(DriverStatusChange.driver_id).distinct():
        ids.add(row[0])

    rejoin_q = DriverStatusChange.query.join(Driver).filter(
        DriverStatusChange.action_type == 'rejoin',
        DriverStatusChange.change_date >= start_d,
        DriverStatusChange.change_date <= end_d,
    )
    if scope_projects:
        rejoin_q = rejoin_q.filter(
            DriverStatusChange.new_project_id.in_(scope_projects)
        )
    if scope_districts:
        rejoin_q = rejoin_q.filter(
            DriverStatusChange.new_district_id.in_(scope_districts)
        )
    if scope_vehicles:
        rejoin_q = rejoin_q.filter(
            DriverStatusChange.new_vehicle_id.in_(scope_vehicles)
        )
    if scope_shifts:
        rejoin_q = rejoin_q.filter(
            DriverStatusChange.new_shift.in_(scope_shifts)
        )
    if project_id:
        rejoin_q = rejoin_q.filter(
            DriverStatusChange.new_project_id == project_id
        )
    if district_id:
        rejoin_q = rejoin_q.filter(
            DriverStatusChange.new_district_id == district_id
        )
    if vehicle_id:
        rejoin_q = rejoin_q.filter(
            DriverStatusChange.new_vehicle_id == vehicle_id
        )
    if shift:
        rejoin_q = rejoin_q.filter(
            DriverStatusChange.new_shift == shift
        )
    for row in rejoin_q.with_entities(DriverStatusChange.driver_id).distinct():
        ids.add(row[0])

    vehicle_ids_to_scan = []
    if vehicle_id:
        vehicle_ids_to_scan = [vehicle_id]
    elif scope_vehicles:
        vehicle_ids_to_scan = list(scope_vehicles)
    for vid in vehicle_ids_to_scan:
        ids.update(_tra_vehicle_driver_ids_in_month(vid, start_d, end_d))

    return ids


class _TraMonthCache:
    """Preload month data once to avoid N+1 queries in TRA report."""

    def __init__(self, start_d, end_d, driver_ids):
        self.start_d = start_d
        self.end_d = end_d
        self.driver_ids = set(driver_ids or [])
        self.drivers = {}
        self.left_by_driver = {}
        self.rejoin_in_month = {}
        self.status_events_by_driver = {}
        self.transfers_by_driver = {}
        self._att_in_month = set()
        self._vehicle_on_date = {}
        self._segments = {}
        self._vehicle_candidates = {}
        self._vehicle_day_counts = {}
        self._maint_by_vehicle = {}
        self._loaded = False

    def load(self):
        if self._loaded:
            return
        if not self.driver_ids:
            self._loaded = True
            return

        self.drivers = {
            d.id: d
            for d in Driver.query.filter(Driver.id.in_(self.driver_ids)).all()
        }
        ids = list(self.driver_ids)

        self.status_events_by_driver = {did: [] for did in ids}
        for sc in DriverStatusChange.query.filter(
            DriverStatusChange.driver_id.in_(ids),
            DriverStatusChange.action_type.in_(['left', 'rejoin']),
        ).order_by(DriverStatusChange.change_date.asc(), DriverStatusChange.id.asc()):
            self.status_events_by_driver.setdefault(sc.driver_id, []).append(sc)
        for sc in reversed(
            DriverStatusChange.query.filter(
                DriverStatusChange.driver_id.in_(ids),
                DriverStatusChange.action_type.in_(['left', 'rejoin']),
            ).order_by(DriverStatusChange.change_date.desc(), DriverStatusChange.id.desc()).all()
        ):
            if sc.action_type == 'left' and sc.driver_id not in self.left_by_driver:
                self.left_by_driver[sc.driver_id] = sc
            elif (
                sc.action_type == 'rejoin'
                and sc.change_date
                and self.start_d <= sc.change_date <= self.end_d
                and sc.driver_id not in self.rejoin_in_month
            ):
                self.rejoin_in_month[sc.driver_id] = sc

        self.transfers_by_driver = {did: [] for did in ids}
        for t in DriverTransfer.query.filter(
            DriverTransfer.driver_id.in_(ids),
            _tra_non_shift_transfer_filter(),
        ).order_by(DriverTransfer.transfer_date.asc(), DriverTransfer.id.asc()):
            self.transfers_by_driver.setdefault(t.driver_id, []).append(t)

        self._att_in_month = {
            row[0]
            for row in DriverAttendance.query.filter(
                DriverAttendance.driver_id.in_(ids),
                DriverAttendance.attendance_date >= self.start_d,
                DriverAttendance.attendance_date <= self.end_d,
            ).with_entities(DriverAttendance.driver_id).distinct()
        }
        self._loaded = True

    def _add_drivers(self, new_ids):
        new_ids = {i for i in new_ids if i and i not in self.drivers}
        if not new_ids:
            return
        self.driver_ids.update(new_ids)
        for d in Driver.query.filter(Driver.id.in_(new_ids)).all():
            self.drivers[d.id] = d
        for sc in DriverStatusChange.query.filter(
            DriverStatusChange.driver_id.in_(new_ids),
            DriverStatusChange.action_type.in_(['left', 'rejoin']),
        ).order_by(DriverStatusChange.change_date.asc(), DriverStatusChange.id.asc()):
            self.status_events_by_driver.setdefault(sc.driver_id, []).append(sc)
        for sc in reversed(
            DriverStatusChange.query.filter(
                DriverStatusChange.driver_id.in_(new_ids),
                DriverStatusChange.action_type.in_(['left', 'rejoin']),
            ).order_by(DriverStatusChange.change_date.desc(), DriverStatusChange.id.desc()).all()
        ):
            if sc.action_type == 'left' and sc.driver_id not in self.left_by_driver:
                self.left_by_driver[sc.driver_id] = sc
            elif (
                sc.action_type == 'rejoin'
                and sc.change_date
                and self.start_d <= sc.change_date <= self.end_d
                and sc.driver_id not in self.rejoin_in_month
            ):
                self.rejoin_in_month[sc.driver_id] = sc
        for t in DriverTransfer.query.filter(
            DriverTransfer.driver_id.in_(new_ids),
            _tra_non_shift_transfer_filter(),
        ).order_by(DriverTransfer.transfer_date.asc(), DriverTransfer.id.asc()):
            self.transfers_by_driver.setdefault(t.driver_id, []).append(t)
        for row in DriverAttendance.query.filter(
            DriverAttendance.driver_id.in_(new_ids),
            DriverAttendance.attendance_date >= self.start_d,
            DriverAttendance.attendance_date <= self.end_d,
        ).with_entities(DriverAttendance.driver_id).distinct():
            self._att_in_month.add(row[0])
        self._segments = {}
        self._vehicle_candidates = {}
        self._vehicle_day_counts = {}

    def left_rec(self, driver_id):
        return self.left_by_driver.get(driver_id)

    def driver_on_duty_in_month(self, driver):
        assign_date = driver.assign_date
        if assign_date and assign_date > self.end_d:
            if driver.id in self._att_in_month:
                return True
            if any(
                t.transfer_date
                and self.start_d <= t.transfer_date <= self.end_d
                for t in self.transfers_by_driver.get(driver.id, [])
            ):
                return True
            rejoin_rec = self.rejoin_in_month.get(driver.id)
            if rejoin_rec and rejoin_rec.change_date:
                return True
            return any(
                sc.change_date and self.start_d <= sc.change_date <= self.end_d
                for sc in [self.left_by_driver.get(driver.id)]
                if sc
            )
        left_rec = self.left_by_driver.get(driver.id)
        if left_rec and left_rec.change_date:
            if (
                driver.vehicle_id
                and assign_date
                and assign_date > left_rec.change_date
                and assign_date <= self.end_d
            ):
                return True
            if left_rec.change_date < self.start_d:
                rejoined = any(
                    sc.change_date
                    and sc.change_date > left_rec.change_date
                    and sc.change_date <= self.end_d
                    for sc in [self.rejoin_in_month.get(driver.id)]
                    if sc
                )
                if not rejoined:
                    return False
        return True

    def vehicle_id_on_date(self, driver_id, on_date):
        key = (driver_id, on_date)
        if key in self._vehicle_on_date:
            return self._vehicle_on_date[key]
        driver = self.drivers.get(driver_id)
        if not driver:
            self._vehicle_on_date[key] = None
            return None
        status_events = self.status_events_by_driver.get(driver_id, [])
        rejoin = _tra_applicable_rejoin_on_date(driver_id, on_date, status_events)
        if rejoin and rejoin.new_vehicle_id and rejoin.change_date and on_date >= rejoin.change_date:
            self._vehicle_on_date[key] = rejoin.new_vehicle_id
            return rejoin.new_vehicle_id
        left = self.left_rec(driver_id)
        if not driver.vehicle_id and left and left.change_date and left.change_date > on_date:
            vid = left.left_vehicle_id
            self._vehicle_on_date[key] = vid
            return vid

        transfers = self.transfers_by_driver.get(driver_id, [])
        vid = _tra_vehicle_id_from_transfer_list(transfers, on_date, driver, left)
        self._vehicle_on_date[key] = vid
        return vid

    def driver_duty_on_date(self, driver_id, on_date):
        driver = self.drivers.get(driver_id)
        if not driver:
            return False
        return _tra_driver_duty_active_on_date(
            driver, on_date, self.status_events_by_driver.get(driver_id),
        )

    def segments(self, driver):
        if driver.id in self._segments:
            return self._segments[driver.id]
        left_rec = self.left_rec(driver.id)
        rejoin_rec = self.rejoin_in_month.get(driver.id)
        left_date = None
        if left_rec and left_rec.change_date and self.start_d <= left_rec.change_date <= self.end_d:
            left_date = left_rec.change_date

        transfers = [
            t for t in self.transfers_by_driver.get(driver.id, [])
            if self.start_d <= t.transfer_date <= self.end_d
        ]
        segments = []

        if not transfers:
            eff = _tra_assignment_for_report_month(driver, left_rec, self.start_d, self.end_d)
            if not eff.get('vehicle_id'):
                self._segments[driver.id] = []
                return []
            seg_s, seg_e = _tra_clamp_segment_bounds(
                self.start_d, self.end_d, self.start_d, self.end_d,
                driver.assign_date, left_date,
            )
            if rejoin_rec and rejoin_rec.change_date and seg_s and rejoin_rec.change_date > seg_s:
                seg_s = max(seg_s, rejoin_rec.change_date)
            if seg_s is None or seg_s > seg_e:
                self._segments[driver.id] = []
                return []
            segments.append({
                'eff': eff,
                'segment_start': seg_s,
                'segment_end': seg_e,
                'transfer_in': None,
                'transfer_out': None,
            })
            self._segments[driver.id] = segments
            return segments

        segments = _tra_build_in_month_transfer_segments(
            transfers, self.start_d, self.end_d, driver, left_date, rejoin_rec,
        )
        self._segments[driver.id] = segments
        return segments

    def _expand_for_vehicles(self, vehicle_ids):
        if not vehicle_ids:
            return
        sf = _tra_non_shift_transfer_filter()
        new_ids = set()
        for vid in vehicle_ids:
            for row in Driver.query.filter(Driver.vehicle_id == vid).with_entities(Driver.id):
                new_ids.add(row[0])
            for row in DriverTransfer.query.filter(
                sf, DriverTransfer.new_vehicle_id == vid, DriverTransfer.transfer_date <= self.end_d,
            ).with_entities(DriverTransfer.driver_id):
                new_ids.add(row[0])
            for row in DriverTransfer.query.filter(
                sf,
                DriverTransfer.old_vehicle_id == vid,
                db.or_(
                    DriverTransfer.transfer_date >= self.start_d,
                    DriverTransfer.transfer_date > self.end_d,
                ),
            ).with_entities(DriverTransfer.driver_id):
                new_ids.add(row[0])
            for row in DriverStatusChange.query.filter(
                DriverStatusChange.action_type == 'left',
                DriverStatusChange.left_vehicle_id == vid,
                DriverStatusChange.change_date >= self.start_d,
            ).with_entities(DriverStatusChange.driver_id):
                new_ids.add(row[0])
        self._add_drivers(new_ids)

    def _vehicle_candidate_ids(self, vehicle_id):
        if vehicle_id in self._vehicle_candidates:
            return self._vehicle_candidates[vehicle_id]
        ids = set()
        for did, driver in self.drivers.items():
            if not self.driver_on_duty_in_month(driver):
                continue
            for seg in self.segments(driver):
                if seg['eff'].get('vehicle_id') == vehicle_id:
                    ids.add(did)
                    break
        self._vehicle_candidates[vehicle_id] = ids
        return ids

    def ensure_vehicle_day_counts(self, vehicle_ids):
        vehicle_ids = [vid for vid in (vehicle_ids or []) if vid]
        missing = [
            vid for vid in vehicle_ids
            if not any(k[0] == vid for k in self._vehicle_day_counts)
        ]
        if not missing:
            return
        self._expand_for_vehicles(set(missing))
        for vid in missing:
            self._vehicle_candidates.pop(vid, None)
            candidates = self._vehicle_candidate_ids(vid)
            d = self.start_d
            while d <= self.end_d:
                count = 0
                for pid in candidates:
                    if not self.driver_duty_on_date(pid, d):
                        continue
                    if self.vehicle_id_on_date(pid, d) == vid:
                        count += 1
                self._vehicle_day_counts[(vid, d)] = count
                d += timedelta(days=1)

    def prewarm(self, drivers):
        """Build segment + vehicle-day caches before the report row loop."""
        vehicle_ids = set()
        for d in drivers:
            for seg in self.segments(d):
                vid = seg['eff'].get('vehicle_id')
                if vid:
                    vehicle_ids.add(vid)
        if vehicle_ids:
            self.ensure_vehicle_day_counts(list(vehicle_ids))

    def segment_solo_days(self, vehicle_id, seg_start, seg_end):
        self.ensure_vehicle_day_counts([vehicle_id])
        solo = 0
        d = seg_start
        while d <= seg_end:
            if self._vehicle_day_counts.get((vehicle_id, d), 0) == 1:
                solo += 1
            d += timedelta(days=1)
        return solo

    def ensure_maint_data(self, vehicle_ids):
        missing = [vid for vid in vehicle_ids if vid and vid not in self._maint_by_vehicle]
        if not missing:
            return
        for row in MaintenanceExpense.query.filter(
            MaintenanceExpense.vehicle_id.in_(missing),
            MaintenanceExpense.expense_date >= self.start_d,
            MaintenanceExpense.expense_date <= self.end_d,
        ).with_entities(MaintenanceExpense.vehicle_id, MaintenanceExpense.expense_date):
            self._maint_by_vehicle.setdefault(row[0], set()).add(row[1])

    def maint_count(self, vehicle_id, seg_start, seg_end):
        if not vehicle_id:
            return 0
        self.ensure_maint_data([vehicle_id])
        dates = self._maint_by_vehicle.get(vehicle_id, set())
        return sum(1 for d in dates if seg_start <= d <= seg_end)


def _tra_status_rec(driver_id, action_type):
    return DriverStatusChange.query.filter(
        DriverStatusChange.driver_id == driver_id,
        DriverStatusChange.action_type == action_type,
    ).order_by(DriverStatusChange.change_date.desc()).first()


def _tra_transfer_rec(driver_id, vehicle_id, side, start_d, end_d):
    if not vehicle_id:
        return None
    q = DriverTransfer.query.filter(
        DriverTransfer.driver_id == driver_id,
        _tra_non_shift_transfer_filter(),
        DriverTransfer.transfer_date >= start_d,
        DriverTransfer.transfer_date <= end_d,
    )
    if side == 'in':
        q = q.filter(DriverTransfer.new_vehicle_id == vehicle_id)
    else:
        q = q.filter(DriverTransfer.old_vehicle_id == vehicle_id)
    return q.order_by(DriverTransfer.transfer_date.desc()).first()


def _tra_duty_window(
    start_d,
    end_d,
    assign_date,
    rejoin_date,
    transfer_in_date,
    left_date,
    transfer_out_date,
):
    drv_start = start_d
    drv_end = end_d
    if assign_date and assign_date > start_d:
        drv_start = assign_date
    if rejoin_date and start_d <= rejoin_date <= end_d and rejoin_date > drv_start:
        drv_start = rejoin_date
    if transfer_in_date and start_d <= transfer_in_date <= end_d and transfer_in_date > drv_start:
        drv_start = transfer_in_date
    if left_date and start_d <= left_date <= end_d and left_date < drv_end:
        drv_end = left_date
    if transfer_out_date and start_d <= transfer_out_date <= end_d:
        t_last = transfer_out_date - timedelta(days=1)
        if t_last >= start_d and t_last < drv_end:
            drv_end = t_last
    if drv_start > drv_end:
        return drv_start, drv_end, 0
    return drv_start, drv_end, (drv_end - drv_start).days + 1


def _tra_vehicle_driver_ids_in_month(vehicle_id, start_d, end_d):
    candidates = set()
    sf = _tra_non_shift_transfer_filter()
    for row in DriverTransfer.query.filter(sf, DriverTransfer.new_vehicle_id == vehicle_id).with_entities(
        DriverTransfer.driver_id, DriverTransfer.transfer_date
    ):
        if row[1] <= end_d:
            candidates.add(row[0])
    for row in DriverTransfer.query.filter(
        sf,
        DriverTransfer.old_vehicle_id == vehicle_id,
        DriverTransfer.transfer_date >= start_d,
        DriverTransfer.transfer_date <= end_d,
    ).with_entities(DriverTransfer.driver_id):
        candidates.add(row[0])
    for row in DriverTransfer.query.filter(
        sf,
        DriverTransfer.old_vehicle_id == vehicle_id,
        DriverTransfer.transfer_date > end_d,
    ).with_entities(DriverTransfer.driver_id):
        candidates.add(row[0])
    for row in Driver.query.filter(Driver.vehicle_id == vehicle_id).with_entities(Driver.id):
        candidates.add(row[0])
    for row in DriverStatusChange.query.filter(
        DriverStatusChange.action_type == 'left',
        DriverStatusChange.left_vehicle_id == vehicle_id,
        DriverStatusChange.change_date >= start_d,
    ).with_entities(DriverStatusChange.driver_id):
        candidates.add(row[0])

    ids = set()
    for pid in candidates:
        partner = db.session.get(Driver, pid)
        if not partner:
            continue
        p_left = _tra_status_rec(pid, 'left')
        if not _tra_driver_on_duty_in_month(pid, start_d, end_d, partner.assign_date):
            continue
        on_vehicle = False
        for seg in _tra_driver_vehicle_segments(partner, p_left, start_d, end_d):
            if seg['eff'].get('vehicle_id') == vehicle_id:
                on_vehicle = True
                break
        if on_vehicle:
            ids.add(pid)
    return ids


def _tra_build_segment_remarks(
    driver,
    eff,
    segment,
    active_days,
    working_days,
    solo_days,
    ndays,
    start_d,
    end_d,
    rejoin_in_month,
    left_rec,
    left_date,
):
    parts = []
    veh_no = eff.get('vehicle').vehicle_no if eff.get('vehicle') else '-'
    seg_s = segment['segment_start']
    seg_e = segment['segment_end']
    transfer_in_rec = segment.get('transfer_in')
    transfer_out_rec = segment.get('transfer_out')

    if transfer_in_rec:
        old_v = transfer_in_rec.old_vehicle.vehicle_no if transfer_in_rec.old_vehicle else '?'
        new_v = transfer_in_rec.new_vehicle.vehicle_no if transfer_in_rec.new_vehicle else '?'
        t_date = transfer_in_rec.transfer_date.strftime('%d-%m-%Y')
        parts.append(
            f'Transferred from {old_v} to {new_v} on {t_date}. '
            f'Duty on {new_v}: {active_days} day(s) ({seg_s.strftime("%d-%m-%Y")} to {seg_e.strftime("%d-%m-%Y")}).'
        )
        if transfer_in_rec.remarks:
            parts.append(transfer_in_rec.remarks.strip())
    elif transfer_out_rec:
        old_v = transfer_out_rec.old_vehicle.vehicle_no if transfer_out_rec.old_vehicle else '?'
        new_v = transfer_out_rec.new_vehicle.vehicle_no if transfer_out_rec.new_vehicle else '?'
        t_date = transfer_out_rec.transfer_date.strftime('%d-%m-%Y')
        parts.append(
            f'Transferred from {old_v} to {new_v} on {t_date}. '
            f'Worked {active_days} day(s) on {old_v} ({seg_s.strftime("%d-%m-%Y")} to {seg_e.strftime("%d-%m-%Y")}).'
        )
        if transfer_out_rec.remarks:
            parts.append(transfer_out_rec.remarks.strip())

    if rejoin_in_month and rejoin_in_month.change_date and not transfer_in_rec:
        if seg_s <= rejoin_in_month.change_date <= seg_e:
            r_date = rejoin_in_month.change_date.strftime('%d-%m-%Y')
            parts.append(f'Rejoined on {r_date}. Working days after rejoin on {veh_no}: {active_days}.')

    if left_date and seg_s <= left_date <= seg_e and not transfer_out_rec:
        l_date = left_date.strftime('%d-%m-%Y')
        msg = f'Left on {l_date}. Worked {active_days} day(s) on {veh_no} before leaving.'
        if left_rec and left_rec.reason:
            msg += f' Reason: {left_rec.reason}.'
        parts.append(msg)
    elif (
        driver.assign_date
        and start_d <= driver.assign_date <= end_d
        and seg_s <= driver.assign_date <= seg_e
        and not transfer_in_rec
        and not rejoin_in_month
        and active_days > 0
    ):
        parts.append(
            f'Joined duty on {driver.assign_date.strftime("%d-%m-%Y")}. '
            f'Working days on {veh_no}: {active_days}.'
        )
    elif active_days < ndays and not transfer_in_rec and not transfer_out_rec and not left_date:
        parts.append(
            f'Duty on {veh_no} from {seg_s.strftime("%d-%m-%Y")} to {seg_e.strftime("%d-%m-%Y")} '
            f'({active_days} day(s)).'
        )

    if solo_days > 0:
        if solo_days >= active_days:
            parts.append(
                f'No second driver on {veh_no} for this period; double duty for '
                f'{solo_days} day(s) ({working_days} total working days).'
            )
        else:
            paired_days = active_days - solo_days
            parts.append(
                f'Second driver present for {paired_days} day(s). '
                f'No second driver for remaining {solo_days} day(s); double duty applied '
                f'({working_days} total working days).'
            )

    return ' '.join(p for p in parts if p)


def _tra_compute_segment_metrics(driver, segment, start_d, end_d, ndays, cache=None):
    eff = segment['eff']
    vehicle = eff.get('vehicle')
    vehicle_id = eff.get('vehicle_id')
    seg_s = segment['segment_start']
    seg_e = segment['segment_end']
    active_days = (seg_e - seg_s).days + 1

    if cache:
        left_rec = cache.left_rec(driver.id)
        rejoin_in_month = cache.rejoin_in_month.get(driver.id)
    else:
        left_rec = _tra_status_rec(driver.id, 'left')
        rejoin_rec = _tra_status_rec(driver.id, 'rejoin')
        rejoin_in_month = (
            rejoin_rec
            if rejoin_rec and rejoin_rec.change_date and start_d <= rejoin_rec.change_date <= end_d
            else None
        )
    left_date = None
    if left_rec and left_rec.change_date and start_d <= left_rec.change_date <= end_d:
        left_date = left_rec.change_date

    working_days = active_days
    solo_days = 0
    capacity = vehicle.driver_capacity if vehicle else 1

    if capacity >= 2 and vehicle_id and active_days > 0:
        if cache:
            solo_days = cache.segment_solo_days(vehicle_id, seg_s, seg_e)
        else:
            solo_days = _tra_segment_solo_days(vehicle_id, seg_s, seg_e, start_d, end_d)
        working_days = active_days + solo_days

    remarks = _tra_build_segment_remarks(
        driver,
        eff,
        segment,
        active_days,
        working_days,
        solo_days,
        ndays,
        start_d,
        end_d,
        rejoin_in_month,
        left_rec,
        left_date,
    )

    transfer_in = segment.get('transfer_in')
    transfer_out = segment.get('transfer_out')
    return {
        'working_days': working_days,
        'active_days': active_days,
        'remarks': remarks,
        'transfer_date': (
            transfer_in.transfer_date if transfer_in
            else (transfer_out.transfer_date if transfer_out else None)
        ),
        'date_of_leaving': left_date if left_date and seg_s <= left_date <= seg_e else None,
        'date_of_rejoining': (
            rejoin_in_month.change_date
            if rejoin_in_month and seg_s <= rejoin_in_month.change_date <= seg_e
            else None
        ),
    }


# ────────────────────────────────────────────────
# TRA Attendance Sheet (Monthly with Transfer/Rejoin)
# ────────────────────────────────────────────────
@app.route('/driver-attendance/tra-report', methods=['GET', 'POST'])
def driver_attendance_tra_report():
    from auth_utils import get_user_context
    from calendar import monthrange

    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    allowed_shifts = user_context.get('allowed_shifts', set())

    scope_projects = list(allowed_projects) if allowed_projects else []
    scope_districts = list(allowed_districts) if allowed_districts else []
    scope_vehicles = list(allowed_vehicles) if allowed_vehicles else []
    scope_shifts = list(allowed_shifts) if allowed_shifts else []

    form = DriverAttendanceReportForm()
    has_single_scope = bool(scope_projects and len(scope_projects) == 1 and scope_districts and len(scope_districts) == 1 and scope_vehicles and len(scope_vehicles) == 1 and scope_shifts and len(scope_shifts) == 1)
    single_vehicle = db.session.get(Vehicle, scope_vehicles[0]) if has_single_scope and scope_vehicles else None

    disable_project = bool(scope_projects and len(scope_projects) == 1)
    disable_district = bool(scope_districts and len(scope_districts) == 1)

    project_query = Project.query.filter(Project.company_id.isnot(None))
    if scope_projects:
        project_query = project_query.filter(Project.id.in_(scope_projects))
    form.project_id.choices = [(0, '-- All Projects --')] + [(p.id, p.name) for p in project_query.order_by(Project.name).all()]

    if disable_project:
        form.project_id.data = scope_projects[0]
    if disable_district:
        form.district_id.data = scope_districts[0]

    if request.method == 'POST':
        pid = request.form.get('project_id', type=int) or 0
        if not pid and disable_project and scope_projects:
            pid = scope_projects[0]
        districts_query = District.query.join(project_district).filter(project_district.c.project_id == pid) if pid else District.query
        if scope_districts:
            districts_query = districts_query.filter(District.id.in_(scope_districts))
        form.district_id.choices = [(0, '-- All Districts --')] + [(d.id, d.name) for d in districts_query.order_by(District.name).all()]
    else:
        districts_query = District.query
        if scope_districts:
            districts_query = districts_query.filter(District.id.in_(scope_districts))
        form.district_id.choices = [(0, '-- All Districts --')] + [(d.id, d.name) for d in districts_query.order_by(District.name).all()]

    today = pk_date()
    form.month.data = form.month.data or today.month
    form.year.data = form.year.data or today.year
    report = []
    selected_vehicle_id = 0
    selected_shift = ''
    vehicle_choices = []
    report_title = ''

    if request.method == 'POST':
        selected_vehicle_id = request.form.get('vehicle_id', type=int) or 0
        selected_shift = (request.form.get('shift') or '').strip()
        pid = form.project_id.data or 0
        did = form.district_id.data or 0
        if pid and did:
            vq = Vehicle.query.filter(Vehicle.project_id == pid, Vehicle.district_id == did)
            if scope_vehicles:
                vq = vq.filter(Vehicle.id.in_(scope_vehicles))
            for v in vq.order_by(*vehicle_order_by()).all():
                vehicle_choices.append((v.id, v.vehicle_no + ((' (' + v.vehicle_type + ')') if v.vehicle_type else '')))

    if request.method == 'POST' and form.validate_on_submit():
        month = form.month.data
        year = form.year.data
        project_id = form.project_id.data or None
        if project_id == 0:
            project_id = None
        district_id = form.district_id.data or None
        if district_id == 0:
            district_id = None
        vehicle_id = request.form.get('vehicle_id', type=int) or None
        if vehicle_id == 0:
            vehicle_id = None
        shift = (request.form.get('shift') or '').strip()
        search = (form.search.data or '').strip()

        _, ndays = monthrange(year, month)
        start_d = date(year, month, 1)
        end_d = date(year, month, ndays)

        proj_name = ''
        dist_name = ''
        if project_id:
            proj_obj = db.session.get(Project, project_id)
            proj_name = proj_obj.name if proj_obj else ''
        if district_id:
            dist_obj = db.session.get(District, district_id)
            dist_name = dist_obj.name if dist_obj else ''
        month_names = ['', 'January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
        company_name = ''
        if project_id and proj_obj and proj_obj.company:
            company_name = proj_obj.company.name
        title_parts = []
        if company_name:
            title_parts.append(company_name)
        if proj_name:
            title_parts.append(proj_name)
        if dist_name:
            title_parts.append(dist_name)
        report_title = (' - '.join(title_parts) if title_parts else 'All Projects') + " \u2014 Driver's Attendance Sheet For the Month of " + month_names[month] + '-' + str(year)

        driver_id_filter = request.form.get('driver_id', type=int) or 0
        eligible_ids = _tra_report_driver_ids_for_month(
            start_d,
            end_d,
            project_id,
            district_id,
            vehicle_id,
            shift,
            scope_projects,
            scope_districts,
            scope_vehicles,
            scope_shifts,
        )
        if driver_id_filter:
            eligible_ids = {driver_id_filter} if driver_id_filter in eligible_ids else set()
        drivers_query = Driver.query.filter(Driver.id.in_(eligible_ids)) if eligible_ids else Driver.query.filter(False)
        drivers = drivers_query.distinct().order_by(Driver.name).all()

        tra_cache = _TraMonthCache(start_d, end_d, eligible_ids)
        tra_cache.load()
        tra_cache.prewarm(drivers)

        for d in drivers:
            if not tra_cache.driver_on_duty_in_month(d):
                continue

            segments = tra_cache.segments(d)
            for segment in segments:
                eff = segment['eff']
                eff_vehicle_id = eff.get('vehicle_id')
                if search and not _tra_search_matches(search, d, eff):
                    continue
                if not _tra_driver_matches_scope(
                    eff,
                    project_id,
                    district_id,
                    vehicle_id,
                    shift,
                    scope_projects,
                    scope_districts,
                    scope_vehicles,
                    scope_shifts,
                ):
                    continue

                vehicle = eff.get('vehicle')
                metrics = _tra_compute_segment_metrics(
                    d, segment, start_d, end_d, ndays, cache=tra_cache,
                )

                working_days = metrics['working_days']
                total_working_days = working_days - ndays

                report.append({
                    'driver': d,
                    'display_district': eff.get('district'),
                    'display_project': eff.get('project'),
                    'display_vehicle': vehicle,
                    'display_shift': eff.get('shift') or d.shift,
                    'date_of_joining': d.assign_date,
                    'date_of_leaving': metrics['date_of_leaving'],
                    'date_of_rejoining': metrics['date_of_rejoining'],
                    'transfer_date': metrics['transfer_date'],
                    'working_days': working_days,
                    'present_days': ndays,
                    'maintenance_days': '',
                    'total_working_days': total_working_days,
                    'remarks': metrics['remarks'],
                })

    vd_q = Driver.query.filter(Driver.status == 'Active', Driver.vehicle_id.isnot(None))
    if scope_projects:
        vd_q = vd_q.filter(Driver.project_id.in_(scope_projects))
    if scope_vehicles:
        vd_q = vd_q.filter(Driver.vehicle_id.in_(scope_vehicles))
    vehicle_drivers = vd_q.order_by(Driver.name).all()
    selected_driver_id = (request.form.get('driver_id', type=int) or 0) if request.method == 'POST' else 0

    return render_template('driver_attendance_tra_report.html',
        form=form, report=report, report_title=report_title,
        single_vehicle=single_vehicle, has_single_scope=has_single_scope,
        selected_vehicle_id=selected_vehicle_id, selected_shift=selected_shift,
        vehicle_choices=vehicle_choices, disable_project=disable_project,
        disable_district=disable_district, vehicle_drivers=vehicle_drivers,
        selected_driver_id=selected_driver_id,
        **_nav_back_ctx(url_for('reports_index'), show_without_nav_from=True),
    )
