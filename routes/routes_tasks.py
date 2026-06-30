"""
Task Reports: Core Task Reports, Logbooks, Task Entry, Pending Tasks.

Extracted from routes.py to reduce file size.
"""

from flask import (
    render_template, redirect, url_for, flash, request,
    session, jsonify, make_response, abort, send_file,
    Response, current_app,
)
from app import app, db, csrf
from models import (
    Vehicle, Driver, Project, District, Company, ParkingStation,
    VehicleDailyTask, EmergencyTaskRecord, VehicleMileageRecord,
    VehicleActivityRecord, RedTask, VehicleMoveWithoutTask,
    DriverAttendance, SystemSetting, User, Role, ActivityLog,
)
from forms import (
    TaskReportForm, TaskReportFilterForm, EmergencyTaskUploadForm,
    TaskReportUploadBothForm,
)
from datetime import datetime, date, timedelta
from sqlalchemy import func, text, or_, and_, false
from werkzeug.utils import secure_filename
from auth_utils import user_can_access, get_user_context
from utils import pk_now, pk_date, parse_date, format_date_ddmmyyyy
from vehicle_sort_utils import vehicle_order_by, sort_vehicles_in_memory
import re
import os
import json
import csv
import io
from io import BytesIO, StringIO

# Import shared helpers from routes.py
from routes import (
    _multi_word_filter,
    media_url_filter,
    _get_user_scope,
    require_login,
    _nav_back_ctx,
    _cnic_digits,
    enforce_data_freeze,
    _vehicle_query_task_report_scope,
    _persist_client_diagnostic,
    SimplePagination,
    _attendance_local_time,
    _build_upload_error_message,
    _build_vehicle_rows,
    _decode_attendance_photo_b64,
    _default_task_entry_date_for_project,
    _filter_pending_task_rows,
    _html_to_pdf_bytes,
    _json_task_date,
    _logbook_vehicle_aggregate,
    _parse_activity_report_excels,
    _parse_activity_report_single_file,
    _parse_emergency_excel,
    _parse_mileage_excel,
    _show_task_batch_totals,
    _task_entry_date_hint_for_project,
    _task_entry_date_save_ok,
    _task_entry_record_in_user_scope,
    _task_entry_resolve_start_reading,
    _task_report_entry_scope_context,
    _task_report_vehicle_period_detail_impl,
    _upload_attendance_image_bytes_with_fallback,
)

from models import AttendanceSettings
from forms import VehicleMileageUploadForm
from models import project_district
@app.route('/task-report', methods=['GET', 'POST'])
def task_report_list():
    from auth_utils import get_user_context
    
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)
    
    form = TaskReportFilterForm()
    
    # Filter dropdown choices by user scope (Master/Admin = all)
    district_q = District.query
    project_q = Project.query
    if not is_master_or_admin:
        ap, ad, av = allowed_projects, allowed_districts, allowed_vehicles
        if not ap and not ad and not av:
            district_q = district_q.filter(District.id.in_([-1]))
            project_q = project_q.filter(Project.id.in_([-1]))
        else:
            if ad:
                district_q = district_q.filter(District.id.in_(list(ad)))
            elif ap:
                district_q = (
                    district_q.join(project_district, project_district.c.district_id == District.id)
                    .filter(project_district.c.project_id.in_(list(ap)))
                    .distinct()
                )
            elif av:
                d_ids = [
                    r[0] for r in db.session.query(Vehicle.district_id)
                    .filter(Vehicle.id.in_(list(av)), Vehicle.district_id.isnot(None))
                    .distinct().all()
                ]
                district_q = district_q.filter(District.id.in_(d_ids or [-1]))
            if ap:
                project_q = project_q.filter(Project.id.in_(list(ap)))
            if ad:
                project_q = (
                    project_q.join(project_district, project_district.c.project_id == Project.id)
                    .filter(project_district.c.district_id.in_(list(ad)))
                    .distinct()
                )
            if not ap and not ad and av:
                p_ids = [
                    r[0] for r in db.session.query(Vehicle.project_id)
                    .filter(Vehicle.id.in_(list(av)), Vehicle.project_id.isnot(None))
                    .distinct().all()
                ]
                project_q = project_q.filter(Project.id.in_(p_ids or [-1]))
    form.district_id.choices = [(0, '-- All Districts --')] + [(d.id, d.name) for d in district_q.order_by(District.name).all()]
    form.project_id.choices = [(0, '-- All Projects --')] + [(p.id, p.name) for p in project_q.order_by(Project.name).all()]

    today = pk_date()
    from_date = today
    to_date = today

    lad = set(allowed_districts) if allowed_districts else set()
    lap = set(allowed_projects) if allowed_projects else set()
    lav = set(allowed_vehicles) if allowed_vehicles else set()

    def coerce_task_report_scope(did, pid, vid=0):
        vd = {c[0] for c in form.district_id.choices}
        vp = {c[0] for c in form.project_id.choices}
        lk = {'lock_district': False, 'lock_project': False, 'lock_vehicle': False}
        if did and did not in vd:
            did = 0
        if pid and pid not in vp:
            pid = 0
        if not is_master_or_admin:
            if len(lad) == 1:
                only_d = next(iter(lad))
                if only_d in vd:
                    did = only_d
                    lk['lock_district'] = True
            if len(lad) == 1 and len(lap) == 1 and len(lav) == 1:
                only_p = next(iter(lap))
                if only_p in vp:
                    pid = only_p
                    lk['lock_project'] = True
        vehicle_q = _vehicle_query_task_report_scope(
            is_master_or_admin, allowed_projects, allowed_districts, allowed_vehicles
        )
        if did:
            vehicle_q = vehicle_q.filter(Vehicle.district_id == did)
        if pid:
            vehicle_q = vehicle_q.filter(Vehicle.project_id == pid)
        form.vehicle_id.choices = [(0, '-- All Vehicles --')] + [
            (v.id, v.vehicle_no) for v in vehicle_q.order_by(*vehicle_order_by()).all()
        ]
        vv = {c[0] for c in form.vehicle_id.choices}
        if vid and vid not in vv:
            vid = 0
        if not is_master_or_admin and len(lav) == 1:
            only_v = next(iter(lav))
            if only_v in vv:
                vid = only_v
                lk['lock_vehicle'] = True
        return did, pid, vid, lk

    if request.method == 'POST':
        from_date = parse_date(request.form.get('from_date')) or today
        to_date = parse_date(request.form.get('to_date')) or today
        district_id = request.form.get('district_id', type=int) or 0
        project_id = request.form.get('project_id', type=int) or 0
        vehicle_id = request.form.get('vehicle_id', type=int) or 0
        if from_date and to_date and from_date > to_date:
            from_date, to_date = to_date, from_date
        district_id, project_id, vehicle_id, _ = coerce_task_report_scope(district_id, project_id, vehicle_id)
        return redirect(url_for('task_report_list', from_date=from_date.strftime('%d-%m-%Y') if from_date else '', to_date=to_date.strftime('%d-%m-%Y') if to_date else '', district_id=district_id, project_id=project_id, vehicle_id=vehicle_id))

    district_id = request.args.get('district_id', type=int) or 0
    project_id = request.args.get('project_id', type=int) or 0
    vehicle_id = request.args.get('vehicle_id', type=int) or 0
    from_str = request.args.get('from_date', '')
    to_str = request.args.get('to_date', '')
    if from_str:
        from_date = parse_date(from_str) or from_date
    if to_str:
        to_date = parse_date(to_str) or to_date
    if from_date and to_date and from_date > to_date:
        from_date, to_date = to_date, from_date
    district_id, project_id, vehicle_id, task_report_filter_lock = coerce_task_report_scope(district_id, project_id, vehicle_id)
    form.from_date.data = from_date
    form.to_date.data = to_date
    form.district_id.data = district_id
    form.project_id.data = project_id
    form.vehicle_id.data = vehicle_id
    query = VehicleDailyTask.query.filter(
        VehicleDailyTask.task_date >= from_date,
        VehicleDailyTask.task_date <= to_date
    )
    vehicle_joined = False

    def _ensure_vehicle_join():
        nonlocal query, vehicle_joined
        if not vehicle_joined:
            query = query.join(Vehicle, Vehicle.id == VehicleDailyTask.vehicle_id)
            vehicle_joined = True

    if not is_master_or_admin:
        ap, ad, av = allowed_projects, allowed_districts, allowed_vehicles
        if not ap and not ad and not av:
            query = query.filter(false())
        else:
            _ensure_vehicle_join()
            scope_parts = []
            if av:
                scope_parts.append(Vehicle.id.in_(list(av)))
            if ap:
                scope_parts.append(
                    or_(
                        VehicleDailyTask.project_id.in_(list(ap)),
                        Vehicle.project_id.in_(list(ap)),
                    )
                )
            if ad:
                scope_parts.append(
                    or_(
                        VehicleDailyTask.district_id.in_(list(ad)),
                        Vehicle.district_id.in_(list(ad)),
                    )
                )
            if scope_parts:
                query = query.filter(and_(*scope_parts))

    if district_id:
        _ensure_vehicle_join()
        query = query.filter(
            or_(
                VehicleDailyTask.district_id == district_id,
                and_(VehicleDailyTask.district_id.is_(None), Vehicle.district_id == district_id),
            )
        )
    if project_id:
        query = query.filter(VehicleDailyTask.project_id == project_id)
    if vehicle_id:
        query = query.filter(VehicleDailyTask.vehicle_id == vehicle_id)
    tasks = query.order_by(VehicleDailyTask.task_date.desc(), VehicleDailyTask.id).all()
    rows = []
    for t in tasks:
        v = t.vehicle
        task_d = t.task_date
        prev = VehicleDailyTask.query.filter(
            VehicleDailyTask.vehicle_id == t.vehicle_id,
            VehicleDailyTask.task_date < task_d
        ).order_by(VehicleDailyTask.task_date.desc()).first()
        if prev and prev.close_reading is not None:
            start_reading = float(prev.close_reading)
        elif t.start_reading is not None:
            start_reading = float(t.start_reading)
        else:
            start_reading = 0
        close_reading = float(t.close_reading)
        kms_driven = close_reading - start_reading
        if kms_driven < 0:
            kms_driven = 0
        emg_tasks = EmergencyTaskRecord.query.filter(
            EmergencyTaskRecord.task_date == task_d,
            EmergencyTaskRecord.amb_reg_no == v.vehicle_no,
            EmergencyTaskRecord.category.in_(['Green', 'Yellow']),
        ).count()
        _mil_rec = VehicleMileageRecord.query.filter_by(task_date=task_d, reg_no=v.vehicle_no).first()
        tracker_km = _mil_rec.effective_km() if _mil_rec else 0
        kms_diff = kms_driven - tracker_km
        pct_diff = round((kms_diff / kms_driven) * 100, 1) if kms_driven and kms_driven != 0 else None
        rows.append({
            'task': t, 'vehicle': v, 'task_date': task_d,
            'start_reading': start_reading, 'close_reading': close_reading,
            'kms_driven': round(kms_driven, 2), 'tasks_count': t.tasks_count,
            'emg_tasks': emg_tasks, 'tracker_km': round(tracker_km, 2),
            'kms_diff': round(kms_diff, 2), 'pct_diff': pct_diff,
            'odometer_photo_path': (getattr(t, 'odometer_photo_path', None) or '').strip(),
        })
    search = (request.args.get('search') or '').strip()
    if search:
        tokens = [t.lower() for t in search.split() if t]
        def _match(r):
            blob = ' '.join([
                str(r['task_date']), r['vehicle'].vehicle_no,
                r['vehicle'].district.name if r['vehicle'].district else '',
                r['vehicle'].parking_station.tehsil if r['vehicle'].parking_station else '',
                r['vehicle'].parking_station.name if r['vehicle'].parking_station else '',
                r['vehicle'].vehicle_type or '',
                str(r['kms_driven']), str(r['tasks_count']), str(r['emg_tasks']),
                str(r.get('odometer_photo_path') or ''),
            ]).lower()
            return all(tok in blob for tok in tokens)
        rows = [r for r in rows if _match(r)]

    total_kms = sum(r['kms_driven'] for r in rows)
    total_tracker = sum(r['tracker_km'] for r in rows)
    total_diff = round(total_kms - total_tracker, 2)
    total_pct = round((total_diff / total_kms * 100), 1) if total_kms else None
    total_tasks = sum(r['tasks_count'] for r in rows)
    total_emg = sum(r['emg_tasks'] for r in rows)
    total_task_diff = total_tasks - total_emg
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    pagination = SimplePagination(rows, page, per_page)
    rows = pagination.items
    return render_template('task_report_list.html', form=form, rows=rows, from_date=from_date, to_date=to_date,
                           total_kms=total_kms, total_tracker=total_tracker, total_diff=total_diff, total_pct=total_pct,
                           total_tasks=total_tasks, total_emg=total_emg, total_task_diff=total_task_diff,
                           pagination=pagination, per_page=per_page, search=search,
                           task_report_filter_lock=task_report_filter_lock,
                           **_nav_back_ctx(url_for('module_hub', hub_slug='task-logbook'), show_without_nav_from=True))



@app.route('/task-report/export-pdf', methods=['GET'])
def task_report_list_export_pdf():
    from auth_utils import get_user_context

    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)

    today = pk_date()
    from_date = parse_date(request.args.get('from_date', '')) or today
    to_date = parse_date(request.args.get('to_date', '')) or today
    if from_date and to_date and from_date > to_date:
        from_date, to_date = to_date, from_date
    district_id = request.args.get('district_id', type=int) or 0
    project_id = request.args.get('project_id', type=int) or 0
    vehicle_id = request.args.get('vehicle_id', type=int) or 0
    search = (request.args.get('search') or '').strip()

    query = VehicleDailyTask.query.filter(
        VehicleDailyTask.task_date >= from_date,
        VehicleDailyTask.task_date <= to_date,
    )
    vehicle_joined = False

    def _ensure_vehicle_join():
        nonlocal query, vehicle_joined
        if not vehicle_joined:
            query = query.join(Vehicle, Vehicle.id == VehicleDailyTask.vehicle_id)
            vehicle_joined = True

    if not is_master_or_admin:
        ap, ad, av = allowed_projects, allowed_districts, allowed_vehicles
        if not ap and not ad and not av:
            return jsonify({'error': 'No access to export this report.'}), 403
        _ensure_vehicle_join()
        scope_parts = []
        if av:
            scope_parts.append(Vehicle.id.in_(list(av)))
        if ap:
            scope_parts.append(
                or_(
                    VehicleDailyTask.project_id.in_(list(ap)),
                    Vehicle.project_id.in_(list(ap)),
                )
            )
        if ad:
            scope_parts.append(
                or_(
                    VehicleDailyTask.district_id.in_(list(ad)),
                    Vehicle.district_id.in_(list(ad)),
                )
            )
        if scope_parts:
            query = query.filter(and_(*scope_parts))

    if district_id:
        _ensure_vehicle_join()
        query = query.filter(
            or_(
                VehicleDailyTask.district_id == district_id,
                and_(VehicleDailyTask.district_id.is_(None), Vehicle.district_id == district_id),
            )
        )
    if project_id:
        query = query.filter(VehicleDailyTask.project_id == project_id)
    if vehicle_id:
        query = query.filter(VehicleDailyTask.vehicle_id == vehicle_id)

    tasks = query.order_by(VehicleDailyTask.task_date.desc(), VehicleDailyTask.id).all()
    rows = []
    for t in tasks:
        v = t.vehicle
        task_d = t.task_date
        prev = VehicleDailyTask.query.filter(
            VehicleDailyTask.vehicle_id == t.vehicle_id,
            VehicleDailyTask.task_date < task_d,
        ).order_by(VehicleDailyTask.task_date.desc()).first()
        if prev and prev.close_reading is not None:
            start_reading = float(prev.close_reading)
        elif t.start_reading is not None:
            start_reading = float(t.start_reading)
        else:
            start_reading = 0
        close_reading = float(t.close_reading)
        kms_driven = close_reading - start_reading
        if kms_driven < 0:
            kms_driven = 0
        emg_tasks = EmergencyTaskRecord.query.filter(
            EmergencyTaskRecord.task_date == task_d,
            EmergencyTaskRecord.amb_reg_no == v.vehicle_no,
            EmergencyTaskRecord.category.in_(['Green', 'Yellow']),
        ).count()
        _mil_rec = VehicleMileageRecord.query.filter_by(task_date=task_d, reg_no=v.vehicle_no).first()
        tracker_km = _mil_rec.effective_km() if _mil_rec else 0
        kms_diff = kms_driven - tracker_km
        pct_diff = round((kms_diff / kms_driven) * 100, 1) if kms_driven and kms_driven != 0 else None
        rows.append({
            'task': t,
            'vehicle': v,
            'task_date': task_d,
            'start_reading': start_reading,
            'close_reading': close_reading,
            'kms_driven': round(kms_driven, 2),
            'tasks_count': t.tasks_count,
            'emg_tasks': emg_tasks,
            'tracker_km': round(tracker_km, 2),
            'kms_diff': round(kms_diff, 2),
            'pct_diff': pct_diff,
        })

    if search:
        tokens = [tok.lower() for tok in search.split() if tok]

        def _match(r):
            blob = ' '.join([
                str(r['task_date']),
                r['vehicle'].vehicle_no,
                r['vehicle'].district.name if r['vehicle'].district else '',
                r['vehicle'].parking_station.tehsil if r['vehicle'].parking_station else '',
                r['vehicle'].parking_station.name if r['vehicle'].parking_station else '',
                r['vehicle'].vehicle_type or '',
                str(r['kms_driven']),
                str(r['tasks_count']),
                str(r['emg_tasks']),
            ]).lower()
            return all(tok in blob for tok in tokens)

        rows = [r for r in rows if _match(r)]

    if not rows:
        return jsonify({'error': 'Export ke liye koi row nahi mili.'}), 400

    total_kms = sum(r['kms_driven'] for r in rows)
    total_tracker = sum(r['tracker_km'] for r in rows)
    total_diff = round(total_kms - total_tracker, 2)
    total_pct = round((total_diff / total_kms * 100), 1) if total_kms else None
    total_tasks = sum(r['tasks_count'] for r in rows)
    total_emg = sum(r['emg_tasks'] for r in rows)
    total_task_diff = total_tasks - total_emg

    try:
        html = render_template(
            'task_report_list_print.html',
            rows=rows,
            from_date=from_date,
            to_date=to_date,
            total_kms=total_kms,
            total_tracker=total_tracker,
            total_diff=total_diff,
            total_pct=total_pct,
            total_tasks=total_tasks,
            total_emg=total_emg,
            total_task_diff=total_task_diff,
        )
        pdf_bytes = _html_to_pdf_bytes(html, landscape=True)
    except Exception as exc:
        app.logger.exception('Daily task report PDF export failed')
        return jsonify({'error': f'PDF generation failed: {exc}'}), 500

    fname = f'Daily_Task_Report_{from_date.strftime("%d-%m-%Y")}_to_{to_date.strftime("%d-%m-%Y")}.pdf'
    return Response(
        pdf_bytes,
        mimetype='application/pdf',
        headers={'Content-Disposition': f'attachment; filename="{fname}"'},
    )



@app.route('/task-report/vehicle-period-detail', methods=['GET', 'POST'])
def task_report_vehicle_period_detail():
    return _task_report_vehicle_period_detail_impl(
        'task_report_vehicle_period_detail',
        'task_report_vehicle_period_detail.html',
    )



@app.route('/task-report/vehicle-period-detail/export-pdf', methods=['GET'])
def task_report_vehicle_period_detail_export_pdf():
    return _task_report_vehicle_period_detail_impl(
        'task_report_vehicle_period_detail',
        'task_report_vehicle_period_detail.html',
        export_pdf=True,
    )



@app.route('/task-report/logbook-cover', methods=['GET', 'POST'])
def task_report_logbook_cover():
    form = TaskReportFilterForm()
    form.district_id.choices = [(0, '-- Select District --')] + [(d.id, d.name) for d in District.query.order_by(District.name).all()]
    form.project_id.choices = [(0, '-- Select Project --')] + [(p.id, p.name) for p in Project.query.order_by(Project.name).all()]
    today = pk_date()
    from_date = today
    to_date = today
    district_id = request.args.get('district_id', type=int) or 0
    project_id = request.args.get('project_id', type=int) or 0
    if request.method == 'POST':
        from_date = parse_date(request.form.get('from_date')) or today
        to_date = parse_date(request.form.get('to_date')) or today
        district_id = request.form.get('district_id', type=int) or 0
        project_id = request.form.get('project_id', type=int) or 0
        if from_date and to_date and from_date > to_date:
            from_date, to_date = to_date, from_date
        return redirect(url_for('task_report_logbook_cover', from_date=from_date.strftime('%d-%m-%Y') if from_date else '', to_date=to_date.strftime('%d-%m-%Y') if to_date else '', district_id=district_id, project_id=project_id))
    from_str = request.args.get('from_date', '')
    to_str = request.args.get('to_date', '')
    if from_str:
        from_date = parse_date(from_str) or from_date
    if to_str:
        to_date = parse_date(to_str) or to_date
    if from_date and to_date and from_date > to_date:
        from_date, to_date = to_date, from_date
    form.from_date.data = from_date
    form.to_date.data = to_date
    form.district_id.data = district_id
    form.project_id.data = project_id
    if district_id:
        projects = Project.query.join(project_district).filter(project_district.c.district_id == district_id).order_by(Project.name).all()
        form.project_id.choices = [(0, '-- Select Project --')] + [(p.id, p.name) for p in projects]
    rows = []
    if project_id:
        q = Vehicle.query.filter(Vehicle.project_id == project_id)
        if district_id:
            q = q.filter(Vehicle.district_id == district_id)
        vehicles = q.order_by(*vehicle_order_by()).all()
        project = db.session.get(Project, project_id)
        district = db.session.get(District, district_id) if district_id else None
        for v in vehicles:
            agg = _logbook_vehicle_aggregate(v.id, from_date, to_date)
            district_name = v.district.name if v.district else (district.name if district else '-')
            tehsil_name = v.parking_station.tehsil if v.parking_station and v.parking_station.tehsil else '-'
            if agg:
                rows.append({
                    'vehicle': v, 'vehicle_id': v.id, 'from_date': from_date, 'to_date': to_date,
                    'district_name': district_name, 'tehsil_name': tehsil_name,
                    'start_reading': agg['start_reading'], 'close_reading': agg['close_reading'],
                    'total_kms': agg['total_kms'], 'total_task': agg['total_task'],
                    'project': project, 'project_name': project.name if project else '',
                })
            else:
                rows.append({
                    'vehicle': v, 'vehicle_id': v.id, 'from_date': from_date, 'to_date': to_date,
                    'district_name': district_name, 'tehsil_name': tehsil_name,
                    'start_reading': None, 'close_reading': None, 'total_kms': None, 'total_task': None,
                    'project': project, 'project_name': project.name if project else '',
                })
    search = (request.args.get('search') or '').strip()
    if search:
        tokens = [t.lower() for t in search.split() if t]
        def _match(r):
            blob = ' '.join([
                r['vehicle'].vehicle_no,
                r.get('district_name') or '',
                r.get('tehsil_name') or '',
                r.get('project_name') or '',
            ]).lower()
            return all(tok in blob for tok in tokens)
        rows = [r for r in rows if _match(r)]
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    pagination = SimplePagination(rows, page, per_page)
    rows = pagination.items
    return render_template('logbook_cover_list.html', form=form, rows=rows, from_date=from_date, to_date=to_date, pagination=pagination, per_page=per_page, search=search,
                          **_nav_back_ctx(url_for('reports_index'), show_without_nav_from=True))



@app.route('/task-report/logbook-view')
def task_report_logbook_view():
    vehicle_id = request.args.get('vehicle_id', type=int)
    from_str = request.args.get('from_date', '')
    to_str = request.args.get('to_date', '')
    if not vehicle_id or not from_str or not to_str:
        flash('Missing vehicle or date range.', 'warning')
        return redirect(url_for('task_report_logbook_cover'))
    from_date = parse_date(from_str)
    to_date = parse_date(to_str)
    if not from_date or not to_date:
        flash('Invalid date range.', 'warning')
        return redirect(url_for('task_report_logbook_cover'))
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    agg = _logbook_vehicle_aggregate(vehicle_id, from_date, to_date)
    if not agg:
        flash('No task data for this vehicle in the selected period.', 'warning')
        return redirect(url_for('task_report_logbook_cover'))
    project = vehicle.project
    project_name = project.name if project else ''
    district_name = vehicle.district.name if vehicle.district else '-'
    tehsil_name = vehicle.parking_station.tehsil if vehicle.parking_station and vehicle.parking_station.tehsil else '-'
    data = {
        'vehicle_no': vehicle.vehicle_no,
        'from_date': from_date,
        'to_date': to_date,
        'district_name': district_name,
        'tehsil_name': tehsil_name,
        'total_task': agg['total_task'],
        'start_reading': agg['start_reading'],
        'close_reading': agg['close_reading'],
        'total_kms': agg['total_kms'],
        'project_name': project_name,
    }
    return render_template('verification_claim_report.html', rows=[data], project_name=project_name)



@app.route('/task-report/logbook-view-all')
def task_report_logbook_view_all():
    from_str = request.args.get('from_date', '')
    to_str = request.args.get('to_date', '')
    district_id = request.args.get('district_id', type=int) or 0
    project_id = request.args.get('project_id', type=int) or 0
    if not from_str or not to_str or not project_id:
        flash('From Date, To Date aur Project select karein.', 'warning')
        return redirect(url_for('task_report_logbook_cover'))
    from_date = parse_date(from_str)
    to_date = parse_date(to_str)
    if not from_date or not to_date:
        flash('Invalid date range.', 'warning')
        return redirect(url_for('task_report_logbook_cover'))
    q = Vehicle.query.filter(Vehicle.project_id == project_id)
    if district_id:
        q = q.filter(Vehicle.district_id == district_id)
    vehicles = q.order_by(*vehicle_order_by()).all()
    project = db.session.get(Project, project_id)
    project_name = project.name if project else ''
    district = db.session.get(District, district_id) if district_id else None
    rows_with_data = []
    for v in vehicles:
        agg = _logbook_vehicle_aggregate(v.id, from_date, to_date)
        if not agg:
            continue
        district_name = v.district.name if v.district else (district.name if district else '-')
        tehsil_name = v.parking_station.tehsil if v.parking_station and v.parking_station.tehsil else '-'
        rows_with_data.append({
            'vehicle_no': v.vehicle_no,
            'from_date': from_date,
            'to_date': to_date,
            'district_name': district_name,
            'tehsil_name': tehsil_name,
            'total_task': agg['total_task'],
            'start_reading': agg['start_reading'],
            'close_reading': agg['close_reading'],
            'total_kms': agg['total_kms'],
        })
    if not rows_with_data:
        flash('Is period mein kisi vehicle ke paas task data nahi mila.', 'warning')
        return redirect(url_for('task_report_logbook_cover', from_date=from_date.strftime('%d-%m-%Y'), to_date=to_date.strftime('%d-%m-%Y'), district_id=district_id, project_id=project_id))
    return render_template('verification_claim_report.html', rows=rows_with_data, project_name=project_name)



@app.route('/api/task-entry-default-date')
def api_task_entry_default_date():
    project_id = request.args.get('project_id', type=int)
    d = _default_task_entry_date_for_project(project_id)
    project = db.session.get(Project, project_id) if project_id else None
    return jsonify({
        'date': d.strftime('%d-%m-%Y'),
        'hint': _task_entry_date_hint_for_project(project, d),
        'yesterday_default_active': bool(
            project
            and project.task_entry_yesterday_default_until
            and _attendance_local_time() < project.task_entry_yesterday_default_until
        ),
    })



@app.route('/task-report/new', methods=['GET', 'POST'])
def task_report_new():
    from auth_utils import get_user_context

    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)

    district_q = District.query
    project_q_all = Project.query
    if not is_master_or_admin:
        ap, ad, av = allowed_projects, allowed_districts, allowed_vehicles
        if not ap and not ad and not av:
            district_q = district_q.filter(District.id.in_([-1]))
            project_q_all = project_q_all.filter(Project.id.in_([-1]))
        else:
            if ad:
                district_q = district_q.filter(District.id.in_(list(ad)))
            elif ap:
                district_q = (
                    district_q.join(project_district, project_district.c.district_id == District.id)
                    .filter(project_district.c.project_id.in_(list(ap)))
                    .distinct()
                )
            elif av:
                d_ids = [
                    r[0] for r in db.session.query(Vehicle.district_id)
                    .filter(Vehicle.id.in_(list(av)), Vehicle.district_id.isnot(None))
                    .distinct().all()
                ]
                district_q = district_q.filter(District.id.in_(d_ids or [-1]))
            if ap:
                project_q_all = project_q_all.filter(Project.id.in_(list(ap)))
            if ad:
                project_q_all = (
                    project_q_all.join(project_district, project_district.c.project_id == Project.id)
                    .filter(project_district.c.district_id.in_(list(ad)))
                    .distinct()
                )
            if not ap and not ad and av:
                p_ids = [
                    r[0] for r in db.session.query(Vehicle.project_id)
                    .filter(Vehicle.id.in_(list(av)), Vehicle.project_id.isnot(None))
                    .distinct().all()
                ]
                project_q_all = project_q_all.filter(Project.id.in_(p_ids or [-1]))

    districts = district_q.order_by(District.name).all()
    valid_district_ids = {d.id for d in districts}
    scoped_project_ids = None
    if not is_master_or_admin:
        scoped_project_ids = {p.id for p in project_q_all.order_by(Project.name).all()}

    lad = set(allowed_districts) if allowed_districts else set()
    lap = set(allowed_projects) if allowed_projects else set()
    lav = set(allowed_vehicles) if allowed_vehicles else set()

    def apply_task_entry_assignment_locks(did, pid, vid=0):
        """Non-admin: single district → fix district; single district+project+vehicle → fix project too."""
        if is_master_or_admin:
            return did, pid, vid, {'lock_district': False, 'lock_project': False, 'lock_vehicle': False}
        tef = {'lock_district': False, 'lock_project': False, 'lock_vehicle': False}
        if len(lad) == 1:
            only_d = next(iter(lad))
            did = only_d
            tef['lock_district'] = True
        if len(lad) == 1 and len(lap) == 1 and len(lav) == 1:
            only_p = next(iter(lap))
            if scoped_project_ids is None or only_p in scoped_project_ids:
                pid = only_p
                tef['lock_project'] = True
        if len(lav) == 1:
            only_v = next(iter(lav))
            vid = only_v
            tef['lock_vehicle'] = True
        if did and valid_district_ids and did not in valid_district_ids:
            did = 0
        if pid and scoped_project_ids is not None and pid not in scoped_project_ids:
            pid = 0
        return did, pid, vid, tef

    def _task_report_new_vehicles_ui(did, pid):
        q = _vehicle_query_task_report_scope(is_master_or_admin, allowed_projects, allowed_districts, allowed_vehicles)
        if pid:
            q = q.filter(Vehicle.project_id == pid)
        if did:
            q = q.filter(Vehicle.district_id == did)
        return q.order_by(*vehicle_order_by()).all()

    def _task_report_new_scoped_vehicle_ids(did, pid):
        return {v.id for v in _task_report_new_vehicles_ui(did, pid)}

    def _task_report_new_vehicle_query(did, pid, vid=0):
        q = _vehicle_query_task_report_scope(is_master_or_admin, allowed_projects, allowed_districts, allowed_vehicles)
        if pid:
            q = q.filter(Vehicle.project_id == pid)
        if did:
            q = q.filter(Vehicle.district_id == did)
        if vid:
            q = q.filter(Vehicle.id == vid)
        return q.order_by(*vehicle_order_by())

    _explicit_task_date = parse_date(request.args.get('date') or request.form.get('task_date'))
    if request.method == 'POST':
        district_id = request.form.get('district_id', type=int) or request.args.get('district_id', type=int) or 0
        project_id = request.form.get('project_id', type=int) or request.args.get('project_id', type=int) or 0
        vehicle_id = request.form.get('vehicle_id', type=int) or request.args.get('vehicle_id', type=int) or 0
    else:
        district_id = request.args.get('district_id', type=int) or request.form.get('district_id', type=int) or 0
        project_id = request.args.get('project_id', type=int) or request.form.get('project_id', type=int) or 0
        vehicle_id = request.args.get('vehicle_id', type=int) or request.form.get('vehicle_id', type=int) or 0
    if district_id and valid_district_ids and district_id not in valid_district_ids:
        district_id = 0
    if project_id and scoped_project_ids is not None and project_id not in scoped_project_ids:
        project_id = 0
    district_id, project_id, vehicle_id, task_entry_filter = apply_task_entry_assignment_locks(district_id, project_id, vehicle_id)
    if vehicle_id and vehicle_id not in _task_report_new_scoped_vehicle_ids(district_id, project_id):
        vehicle_id = 0

    if _explicit_task_date:
        view_date = _explicit_task_date
    elif project_id:
        view_date = _default_task_entry_date_for_project(project_id)
    else:
        view_date = pk_date()
    _att_cfg = AttendanceSettings.query.first()
    max_km_setting = getattr(_att_cfg, 'daily_task_entry_max_kms_driven', None) if _att_cfg else None
    odom_required_setting = bool(getattr(_att_cfg, 'daily_task_odometer_photo_required', False) if _att_cfg else False)
    from auth_utils import user_can_access
    _perms = session.get('permissions') or []
    can_edit_saved_task_rows = bool(session.get('is_master') or user_can_access(_perms, 'task_report_entry_edit'))
    can_delete_saved_task_rows = bool(session.get('is_master') or user_can_access(_perms, 'task_report_entry_delete'))

    def _task_report_new_projects_ui(did):
        if did:
            pq = Project.query.join(project_district).filter(project_district.c.district_id == did)
            if scoped_project_ids is not None:
                pq = pq.filter(Project.id.in_(list(scoped_project_ids)))
            return pq.order_by(Project.name).all()
        if scoped_project_ids is not None:
            return Project.query.filter(Project.id.in_(list(scoped_project_ids))).order_by(Project.name).all()
        return Project.query.order_by(Project.name).all()

    def _task_report_new_render(rows_list, v_date):
        _tp = db.session.get(Project, project_id) if project_id else None
        _hint = _task_entry_date_hint_for_project(_tp, v_date)
        _tef = dict(task_entry_filter or {})
        _tef.setdefault('lock_district', False)
        _tef.setdefault('lock_project', False)
        _tef.setdefault('lock_vehicle', False)
        resp = make_response(render_template(
            'task_report_new.html',
            rows=rows_list,
            view_date=v_date,
            district_id=district_id or 0,
            project_id=project_id or 0,
            vehicle_id=vehicle_id or 0,
            districts=districts,
            projects=_task_report_new_projects_ui(district_id),
            filter_vehicles=_task_report_new_vehicles_ui(district_id, project_id),
            show_batch_totals=_show_task_batch_totals(user_context, rows_list),
            task_entry_filter=_tef,
            can_edit_saved_task_rows=can_edit_saved_task_rows,
            can_delete_saved_task_rows=can_delete_saved_task_rows,
            task_entry_max_km_driven=max_km_setting,
            task_entry_odometer_required=odom_required_setting,
            task_entry_date_hint=_hint,
            pending_task_count=len(_filter_pending_task_rows(rows_list)) if rows_list else 0,
            **_nav_back_ctx(url_for('module_hub', hub_slug='task-logbook'), show_without_nav_from=True),
        ))
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        resp.headers['Pragma'] = 'no-cache'
        return resp

    if request.method == 'POST' and request.form.get('save_batch'):
        task_date = parse_date(request.form.get('task_date')) or view_date
        district_id = request.form.get('district_id', type=int) or 0
        project_id = request.form.get('project_id', type=int) or 0
        vehicle_id = request.form.get('vehicle_id', type=int) or 0
        if district_id and valid_district_ids and district_id not in valid_district_ids:
            district_id = 0
        if project_id and scoped_project_ids is not None and project_id not in scoped_project_ids:
            project_id = 0
        district_id, project_id, vehicle_id, task_entry_filter = apply_task_entry_assignment_locks(district_id, project_id, vehicle_id)
        if vehicle_id and vehicle_id not in _task_report_new_scoped_vehicle_ids(district_id, project_id):
            vehicle_id = 0
        if not project_id:
            flash('Project select karna zaroori hai — baghair project ke save nahi ho sakta.', 'danger')
            view_date = task_date
            return _task_report_new_render([], view_date)
        _save_project = db.session.get(Project, project_id)
        ok_date, date_msg = _task_entry_date_save_ok(_save_project, task_date)
        if not ok_date:
            flash(date_msg, 'danger')
            view_date = task_date
            q = _task_report_new_vehicle_query(district_id, project_id, vehicle_id)
            vehicles = q.all()
            rows = _build_vehicle_rows(vehicles, task_date, request.form)
            return _task_report_new_render(rows, view_date)
        q = _task_report_new_vehicle_query(district_id, project_id, vehicle_id)
        vehicles = q.all()
        missing = []
        to_save = []
        for v in vehicles:
            existing = VehicleDailyTask.query.filter_by(vehicle_id=v.id, task_date=task_date).first()
            edit_mode = request.form.get('row_%s_edit_mode' % v.id, '1')
            if existing and str(edit_mode) != '1':
                # Locked row: skip update unless explicitly switched to edit mode.
                continue
            close_val = request.form.get('vehicle_%s_close_reading' % v.id)
            tasks_val = request.form.get('vehicle_%s_tasks_count' % v.id)
            start_val = request.form.get('vehicle_%s_start_reading' % v.id)
            try:
                close_reading = float(close_val) if close_val not in (None, '') else None
            except (TypeError, ValueError):
                close_reading = None
            tasks_count = int(float(tasks_val)) if tasks_val not in (None, '') else 0
            try:
                user_start = float(start_val) if start_val not in (None, '') else None
            except (TypeError, ValueError):
                user_start = None
            if close_reading is None:
                missing.append(v.vehicle_no)
            else:
                to_save.append((v, existing, close_reading, tasks_count, user_start))
        if missing:
            flash('Sab vehicles ke liye Close Reading zaroori hai. Missing: ' + ', '.join(missing), 'danger')
            view_date = task_date
            rows = _build_vehicle_rows(vehicles, task_date, request.form)
            return _task_report_new_render(rows, view_date)
        if not to_save:
            _all_already_saved = all(
                VehicleDailyTask.query.filter_by(vehicle_id=v.id, task_date=task_date).first() is not None
                for v in vehicles
            )
            if _all_already_saved:
                flash('Task entries pehle se saved hain — duplicate save nahi hua.', 'info')
                return redirect(url_for(
                    'task_report_new',
                    date=task_date.strftime('%d-%m-%Y'),
                    district_id=district_id,
                    project_id=project_id,
                    batch_saved='1',
                ))
            flash(
                'Koi record save nahi hua: tamam rows locked thin (Edit ke baghair) ya koi row update ke liye tayyar nahi. '
                'Zarurat ho to pehle row par Edit karein, phir Close Reading bharen aur dubara Save All dabaen.',
                'danger',
            )
            view_date = task_date
            rows = _build_vehicle_rows(vehicles, task_date, request.form)
            return _task_report_new_render(rows, view_date)
        validation_msgs = []
        try:
            max_km_cap = int(max_km_setting) if max_km_setting is not None else 0
        except (TypeError, ValueError):
            max_km_cap = 0
        for v, existing, close_reading, tasks_count, user_start in to_save:
            if existing and not can_edit_saved_task_rows:
                validation_msgs.append(
                    '%s: pehle se saved row — Edit ki ijazat nahi (admin se "New Task Entry – Edit saved rows" mangwain).'
                    % (v.vehicle_no,)
                )
            start_eff = _task_entry_resolve_start_reading(v, task_date, request.form)
            kms = float(close_reading) - float(start_eff)
            if kms < 0:
                validation_msgs.append(
                    '%s: Close Reading Start Reading se kam nahi ho sakti (KM %.2f).' % (v.vehicle_no, kms)
                )
            if max_km_cap > 0 and kms > max_km_cap:
                validation_msgs.append(
                    '%s: KMs driven %.2f hai; Settings ki max limit %s KM hai.' % (v.vehicle_no, kms, max_km_cap)
                )
            photo_url = (request.form.get('vehicle_%s_odometer_photo_url' % v.id) or '').strip()
            if odom_required_setting and not photo_url:
                validation_msgs.append('%s: Odoo meter photo zaroori hai (Settings).' % (v.vehicle_no,))
        if validation_msgs:
            flash('Save nahi ho saka: ' + ' '.join(validation_msgs), 'danger')
            view_date = task_date
            rows = _build_vehicle_rows(vehicles, task_date, request.form)
            return _task_report_new_render(rows, view_date)
        for v, existing, close_reading, tasks_count, user_start in to_save:
            photo_url = (request.form.get('vehicle_%s_odometer_photo_url' % v.id) or '').strip()
            if existing:
                existing.close_reading = close_reading
                existing.tasks_count = tasks_count
                if user_start is not None:
                    existing.start_reading = user_start
                existing.odometer_photo_path = photo_url or None
            else:
                db.session.add(VehicleDailyTask(
                    vehicle_id=v.id, project_id=project_id or None, district_id=district_id or None,
                    task_date=task_date, close_reading=close_reading, tasks_count=tasks_count,
                    start_reading=user_start,
                    odometer_photo_path=photo_url or None,
                ))
        try:
            db.session.commit()
            try:
                from notification_service import notify_task_report_saved
                for v, existing, close_reading, tasks_count, user_start in to_save:
                    notify_task_report_saved(v, task_date)
            except Exception:
                pass
            flash('Task entries saved successfully.', 'success')
            _redirect_kwargs = {
                'date': task_date.strftime('%d-%m-%Y'),
                'district_id': district_id or None,
                'project_id': project_id or None,
                'batch_saved': '1',
            }
            if vehicle_id:
                _redirect_kwargs['vehicle_id'] = vehicle_id
            return redirect(url_for('task_report_new', **_redirect_kwargs))
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {str(e)}', 'danger')
            view_date = task_date
            rows = _build_vehicle_rows(vehicles, task_date, request.form)
            return _task_report_new_render(rows, view_date)

    rows = []
    _has_filter = request.args.get('date') is not None
    if _has_filter or district_id or project_id:
        vehicles = _task_report_new_vehicle_query(district_id, project_id, vehicle_id).all()
        rows = _build_vehicle_rows(vehicles, view_date, request.form)
    return _task_report_new_render(rows, view_date)



@app.route('/task-report/pending')
def task_report_pending():
    """Vehicles with missing Close Reading and/or Task's after same filters as New Task Entry."""
    from auth_utils import get_user_context

    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    sc = _task_report_entry_scope_context(user_context)
    allowed_projects = sc['allowed_projects']
    allowed_districts = sc['allowed_districts']
    allowed_vehicles = sc['allowed_vehicles']
    is_master_or_admin = sc['is_master_or_admin']
    districts = sc['districts']
    valid_district_ids = sc['valid_district_ids']
    scoped_project_ids = sc['scoped_project_ids']

    lad = set(allowed_districts) if allowed_districts else set()
    lap = set(allowed_projects) if allowed_projects else set()
    lav = set(allowed_vehicles) if allowed_vehicles else set()

    district_id = request.args.get('district_id', type=int) or 0
    project_id = request.args.get('project_id', type=int) or 0
    if district_id and valid_district_ids and district_id not in valid_district_ids:
        district_id = 0
    if project_id and scoped_project_ids is not None and project_id not in scoped_project_ids:
        project_id = 0

    disable_project = False
    disable_district = False
    if not is_master_or_admin:
        if len(lad) == 1:
            district_id = district_id or next(iter(lad))
            disable_district = True
        if len(lad) == 1 and len(lap) == 1 and len(lav) == 1:
            project_id = project_id or next(iter(lap))
            disable_project = True

    task_entry_filter = {'lock_district': disable_district, 'lock_project': disable_project}
    _explicit_task_date = parse_date(request.args.get('date'))
    if _explicit_task_date:
        view_date = _explicit_task_date
    elif project_id:
        view_date = _default_task_entry_date_for_project(project_id)
    else:
        view_date = pk_date()

    def _projects_ui(did):
        if did:
            pq = Project.query.join(project_district).filter(project_district.c.district_id == did)
            if scoped_project_ids is not None:
                pq = pq.filter(Project.id.in_(list(scoped_project_ids)))
            return pq.order_by(Project.name).all()
        if scoped_project_ids is not None:
            return Project.query.filter(Project.id.in_(list(scoped_project_ids))).order_by(Project.name).all()
        return Project.query.order_by(Project.name).all()

    all_rows = []
    pending_rows = []
    _has_filter = request.args.get('date') is not None
    if _has_filter:
        q = _vehicle_query_task_report_scope(is_master_or_admin, allowed_projects, allowed_districts, allowed_vehicles)
        if project_id:
            q = q.filter(Vehicle.project_id == project_id)
        if district_id:
            q = q.filter(Vehicle.district_id == district_id)
        vehicles = q.order_by(*vehicle_order_by()).all()
        all_rows = _build_vehicle_rows(vehicles, view_date, None)
        pending_rows = _filter_pending_task_rows(all_rows)

    pending_qs = ''
    if view_date:
        pending_qs = 'date=' + view_date.strftime('%d-%m-%Y')
        if district_id:
            pending_qs += '&district_id=' + str(district_id)
        if project_id:
            pending_qs += '&project_id=' + str(project_id)

    return render_template(
        'task_report_pending.html',
        pending_rows=pending_rows,
        total_loaded=len(all_rows),
        view_date=view_date,
        district_id=district_id,
        project_id=project_id,
        districts=districts,
        projects=_projects_ui(district_id),
        task_entry_filter=task_entry_filter,
        pending_filter_qs=pending_qs,
        **_nav_back_ctx(url_for('module_hub', hub_slug='task-logbook'), show_without_nav_from=True),
    )



@app.route('/task-report/new/delete', methods=['POST'])
def task_report_new_delete_row():
    from auth_utils import get_user_context, user_can_access

    perms = session.get('permissions') or []
    if not (session.get('is_master') or user_can_access(perms, 'task_report_entry_delete')):
        return jsonify({'ok': False, 'message': 'Delete ki ijazat nahi — role mein "Delete saved rows" add karein.'}), 403

    body = request.get_json(silent=True) or {}
    task_id = body.get('task_id') or request.form.get('task_id', type=int)
    if not task_id:
        return jsonify({'ok': False, 'message': 'Task record ID missing hai.'}), 400

    rec = db.session.get(VehicleDailyTask, task_id)
    if not rec:
        return jsonify({'ok': False, 'message': 'Record nahi mila (pehle se delete ho chuka ho sakta hai).'}), 404

    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    if not _task_entry_record_in_user_scope(
        rec,
        user_context.get('is_master_or_admin', False),
        user_context.get('allowed_projects', set()),
        user_context.get('allowed_districts', set()),
        user_context.get('allowed_vehicles', set()),
    ):
        return jsonify({'ok': False, 'message': 'Is record par aap ki scope ki ijazat nahi.'}), 403

    vno = rec.vehicle.vehicle_no if rec.vehicle else str(rec.vehicle_id)
    task_date = rec.task_date
    vehicle_id = rec.vehicle_id
    try:
        db.session.delete(rec)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        app.logger.warning('task_report_new_delete_row: %s', e)
        return jsonify({'ok': False, 'message': 'Delete nahi ho saka: %s' % (str(e) or 'error')}), 500

    return jsonify({
        'ok': True,
        'message': '%s (%s) ki entry delete ho gayi.' % (vno, task_date.strftime('%d-%m-%Y')),
        'vehicle_id': vehicle_id,
        'task_date': task_date.strftime('%d-%m-%Y'),
    })



@app.route('/api/task-report/odometer-photo-upload', methods=['POST'])
def api_task_report_odometer_photo_upload():
    """Upload Odoo/odometer display photo (optional) for daily task entry — R2 WebP like attendance."""
    try:
        body = request.get_json(silent=True) or {}
        photo_b64 = (body.get('photo_base64') or '').strip()
        if not photo_b64:
            return jsonify({'ok': False, 'message': 'Koi image nahi bheji.'}), 400
        data = _decode_attendance_photo_b64(photo_b64)
        if not data or len(data) < 80:
            return jsonify({'ok': False, 'message': 'Image decode nahi ho saki.'}), 400
        if len(data) > 12 * 1024 * 1024:
            return jsonify({'ok': False, 'message': 'Image bahut bari hai.'}), 400
        url = _upload_attendance_image_bytes_with_fallback(data, folder='task_odometer')
        if not url:
            return jsonify({'ok': False, 'message': 'Upload save nahi ho saka.'}), 502
        _link_vehicle_id = body.get('vehicle_id')
        _link_task_date = parse_date(body.get('task_date') or '')
        if _link_vehicle_id and _link_task_date:
            try:
                _vdt = VehicleDailyTask.query.filter_by(
                    vehicle_id=int(_link_vehicle_id), task_date=_link_task_date
                ).first()
                if _vdt and not (_vdt.odometer_photo_path or '').strip():
                    _vdt.odometer_photo_path = url
                    db.session.commit()
            except Exception:
                db.session.rollback()
        return jsonify({'ok': True, 'url': url})
    except Exception as e:
        app.logger.warning('task odometer photo upload: %s', e)
        return jsonify({'ok': False, 'message': str(e) or 'Upload failed.'}), 500



@app.route('/api/task-report/emg-detail')
def api_emg_detail():
    """Return EMG task rows (Green+Yellow) for a given vehicle + date or date range."""
    task_date = parse_date(request.args.get('date'))
    from_date = parse_date(request.args.get('from_date'))
    to_date = parse_date(request.args.get('to_date'))
    vehicle_no = (request.args.get('vehicle_no') or '').strip()
    vehicle_nos_raw = (request.args.get('vehicle_nos') or '').strip()
    q = EmergencyTaskRecord.query.filter(
        EmergencyTaskRecord.category.in_(['Green', 'Yellow']),
    )
    if vehicle_no:
        q = q.filter(EmergencyTaskRecord.amb_reg_no == vehicle_no)
    elif vehicle_nos_raw:
        vehicle_nos = [v.strip() for v in vehicle_nos_raw.split(',') if v.strip()]
        if vehicle_nos:
            q = q.filter(EmergencyTaskRecord.amb_reg_no.in_(vehicle_nos))
    if task_date:
        q = q.filter(EmergencyTaskRecord.task_date == task_date)
    elif from_date and to_date:
        if from_date > to_date:
            from_date, to_date = to_date, from_date
        q = q.filter(
            EmergencyTaskRecord.task_date >= from_date,
            EmergencyTaskRecord.task_date <= to_date,
        )
    else:
        return jsonify([])
    rows = q.order_by(EmergencyTaskRecord.task_date, EmergencyTaskRecord.id).all()
    def _fmt_dt(s):
        if not s:
            return ''
        from datetime import datetime as _dt
        for fmt in ('%Y-%m-%d %H:%M:%S', '%d %b %Y %H:%M:%S', '%Y-%m-%d %H:%M', '%d-%m-%Y %H:%M:%S', '%d-%m-%Y %H:%M'):
            try:
                d = _dt.strptime(s.strip(), fmt)
                return d.strftime('%d-%m-%Y %I:%M %p')
            except (ValueError, AttributeError):
                continue
        return s
    return jsonify([{
        'task_date': r.task_date.strftime('%d-%m-%Y') if r.task_date else '',
        'task_id': r.task_id_ext or '',
        'phone': r.phone or '',
        'cli': r.cli or '',
        'name': r.name or '',
        'address': r.address or '',
        'amb_reg_no': r.amb_reg_no or '',
        'received_by': r.received_by or '',
        'category': r.category or '',
        'facility_name': r.facility_name or '',
        'created_date': _fmt_dt(r.excel_created_date),
        'completed_date_time': _fmt_dt(r.completed_date_time),
    } for r in rows])



@app.route('/api/task-report/emg-task-detail')
def api_emg_task_detail():
    """Return one Emergency Task detail by id or task reference."""
    emg_id = request.args.get('emg_id', type=int)
    task_id = (request.args.get('task_id') or '').strip()
    task_date = parse_date(request.args.get('task_date'))
    vehicle_no = (request.args.get('vehicle_no') or '').strip()

    rec = None
    if emg_id:
        rec = db.session.get(EmergencyTaskRecord, emg_id)
    elif task_id and task_date:
        q = EmergencyTaskRecord.query.filter(
            EmergencyTaskRecord.task_id_ext == task_id,
            EmergencyTaskRecord.task_date == task_date,
        )
        if vehicle_no:
            q = q.filter(EmergencyTaskRecord.amb_reg_no == vehicle_no)
        rec = q.order_by(EmergencyTaskRecord.id.desc()).first()
    else:
        return jsonify({'ok': False, 'message': 'Missing emg_id or task reference'}), 400

    if not rec:
        return jsonify({'ok': False, 'message': 'Task not found'}), 404

    def _fmt_dt(s):
        if not s:
            return ''
        from datetime import datetime as _dt
        for fmt in ('%Y-%m-%d %H:%M:%S', '%d %b %Y %H:%M:%S', '%Y-%m-%d %H:%M', '%d-%m-%Y %H:%M:%S', '%d-%m-%Y %H:%M'):
            try:
                d = _dt.strptime(s.strip(), fmt)
                return d.strftime('%d-%m-%Y %I:%M %p')
            except (ValueError, AttributeError):
                continue
        return s

    return jsonify({
        'ok': True,
        'id': rec.id,
        'task_id': rec.task_id_ext or '',
        'vehicle_no': rec.amb_reg_no or '',
        'category': rec.category or '',
        'sub_category': rec.sub_category or '',
        'request_from': rec.request_from or '',
        'phone': rec.phone or '',
        'name': rec.name or '',
        'address': rec.address or '',
        'received_by': rec.received_by or '',
        'facility_name': rec.facility_name or '',
        'district_name': rec.district_name or '',
        'tehsil_name': rec.tehsil_name or '',
        'status': rec.status or '',
        'created_date': _fmt_dt(rec.excel_created_date),
        'completed_date_time': _fmt_dt(rec.completed_date_time),
    })



@app.route('/api/task-report/tracker-detail')
def api_tracker_detail():
    """Return mileage record(s) for a given vehicle + date or date range."""
    task_date = parse_date(request.args.get('date'))
    from_date = parse_date(request.args.get('from_date'))
    to_date = parse_date(request.args.get('to_date'))
    vehicle_no = (request.args.get('vehicle_no') or '').strip()
    if not vehicle_no:
        return jsonify({})

    if from_date and to_date and not task_date:
        if from_date > to_date:
            from_date, to_date = to_date, from_date
        recs = VehicleMileageRecord.query.filter(
            VehicleMileageRecord.reg_no == vehicle_no,
            VehicleMileageRecord.task_date >= from_date,
            VehicleMileageRecord.task_date <= to_date,
        ).order_by(VehicleMileageRecord.task_date).all()
        if not recs:
            return jsonify({'range': True, 'rows': []})

        def _fmt_d_range(s):
            if not s:
                return ''
            from datetime import datetime as _dt
            for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%d-%m-%Y %H:%M:%S', '%d-%m-%Y %H:%M', '%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y %H:%M:%S'):
                try:
                    return _dt.strptime(s.strip(), fmt).strftime('%d-%m-%Y')
                except (ValueError, AttributeError):
                    continue
            return s

        def _fmt_t_range(s):
            if not s:
                return ''
            from datetime import datetime as _dt
            for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%d-%m-%Y %H:%M:%S', '%d-%m-%Y %H:%M', '%H:%M:%S', '%H:%M', '%d/%m/%Y %H:%M:%S'):
                try:
                    return _dt.strptime(s.strip(), fmt).strftime('%I:%M %p')
                except (ValueError, AttributeError):
                    continue
            return s

        return jsonify({
            'range': True,
            'rows': [{
                'id': rec.id,
                'task_date': rec.task_date.strftime('%d-%m-%Y') if rec.task_date else '',
                'reg_no': rec.reg_no or '',
                'date_from': _fmt_d_range(rec.date_time_c),
                'time_from': _fmt_t_range(rec.date_time_c),
                'date_to': _fmt_d_range(rec.date_time_e),
                'time_to': _fmt_t_range(rec.date_time_e),
                'mileage': float(rec.mileage or 0),
                'ptop': float(rec.ptop or 0),
                'selected_km': float(rec.selected_km) if rec.selected_km is not None else None,
                'effective_km': rec.effective_km(),
            } for rec in recs],
        })

    if not task_date:
        return jsonify({})
    rec = VehicleMileageRecord.query.filter_by(task_date=task_date, reg_no=vehicle_no).first()
    if not rec:
        return jsonify({})
    def _fmt_d(s):
        if not s:
            return ''
        from datetime import datetime as _dt
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%d-%m-%Y %H:%M:%S', '%d-%m-%Y %H:%M', '%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y %H:%M:%S'):
            try:
                return _dt.strptime(s.strip(), fmt).strftime('%d-%m-%Y')
            except (ValueError, AttributeError):
                continue
        return s
    def _fmt_t(s):
        if not s:
            return ''
        from datetime import datetime as _dt
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%d-%m-%Y %H:%M:%S', '%d-%m-%Y %H:%M', '%H:%M:%S', '%H:%M', '%d/%m/%Y %H:%M:%S'):
            try:
                return _dt.strptime(s.strip(), fmt).strftime('%I:%M %p')
            except (ValueError, AttributeError):
                continue
        return s
    return jsonify({
        'id': rec.id,
        'reg_no': rec.reg_no or '',
        'date_from': _fmt_d(rec.date_time_c),
        'time_from': _fmt_t(rec.date_time_c),
        'date_to': _fmt_d(rec.date_time_e),
        'time_to': _fmt_t(rec.date_time_e),
        'mileage': float(rec.mileage or 0),
        'ptop': float(rec.ptop or 0),
        'selected_km': float(rec.selected_km) if rec.selected_km is not None else None,
        'effective_km': rec.effective_km(),
    })



@app.route('/api/task-report/tracker-save', methods=['POST'])
def api_tracker_save():
    """Save user-edited tracker KM override."""
    data = request.get_json(silent=True) or {}
    rec_id = data.get('id')
    new_val = data.get('selected_km')
    if not rec_id:
        return jsonify({'ok': False, 'error': 'Missing record id'}), 400
    rec = db.session.get(VehicleMileageRecord, rec_id)
    if not rec:
        return jsonify({'ok': False, 'error': 'Record not found'}), 404
    try:
        rec.selected_km = float(new_val) if new_val not in (None, '', 'null') else None
        db.session.commit()
        return jsonify({'ok': True, 'effective_km': rec.effective_km()})
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500



@app.route('/task-report/upload/emergency', methods=['GET', 'POST'])
def task_report_upload_emergency():
    form = EmergencyTaskUploadForm()
    if request.method == 'POST' and form.validate_on_submit():
        f = form.file.data
        if not f:
            flash('Please select an Excel file.', 'warning')
            return redirect(url_for('task_report_upload_emergency'))
        task_date = form.task_date.data
        try:
            c = _parse_emergency_excel(f, task_date)
            db.session.commit()
            flash(f'EmergencyTaskReport uploaded: {c} record(s).', 'success')
            return redirect(url_for('task_report_list', date=task_date.strftime('%d-%m-%Y')))
        except Exception as e:
            db.session.rollback()
            app.logger.exception("EmergencyTaskReport upload failed for date=%s", task_date)
            flash(_build_upload_error_message('EmergencyTaskReport', e), 'danger')
    return render_template('task_report_upload_emergency.html', form=form,
                          **_nav_back_ctx(url_for('module_hub', hub_slug='task-logbook'), show_without_nav_from=True))



@app.route('/task-report/upload/mileage', methods=['GET', 'POST'])
def task_report_upload_mileage():
    form = VehicleMileageUploadForm()
    if request.method == 'POST' and form.validate_on_submit():
        f = form.file.data
        if not f:
            flash('Please select an Excel file.', 'warning')
            return redirect(url_for('task_report_upload_mileage'))
        task_date = form.task_date.data
        try:
            c = _parse_mileage_excel(f, task_date)
            db.session.commit()
            flash(f'Vehicle Mileage report uploaded: {c} record(s).', 'success')
            return redirect(url_for('task_report_list', date=task_date.strftime('%d-%m-%Y')))
        except Exception as e:
            db.session.rollback()
            app.logger.exception("Vehicle Mileage upload failed for date=%s", task_date)
            flash(_build_upload_error_message('Vehicle Mileage report', e), 'danger')
    return render_template('task_report_upload_mileage.html', form=form,
                          **_nav_back_ctx(url_for('module_hub', hub_slug='task-logbook'), show_without_nav_from=True))



@app.route('/task-report/upload/core', methods=['POST'])
def task_report_upload_core():
    """Import emergency + mileage only; short JSON request to avoid proxy timeout with large activity batches."""
    task_date = _json_task_date()
    if not task_date:
        return jsonify({'ok': False, 'error': 'Invalid or missing report date.'}), 400
    fe = request.files.get('file_emergency')
    fm = request.files.get('file_mileage')
    has_fe = fe and getattr(fe, 'filename', '').strip()
    has_fm = fm and getattr(fm, 'filename', '').strip()
    if not has_fe and not has_fm:
        return jsonify({'ok': False, 'error': 'No emergency or mileage file.'}), 400
    try:
        c1 = c2 = 0
        if has_fe:
            c1 = _parse_emergency_excel(fe, task_date)
        if has_fm:
            c2 = _parse_mileage_excel(fm, task_date)
        db.session.commit()
        return jsonify({'ok': True, 'emergency_count': c1, 'mileage_count': c2, 'task_date': task_date.strftime('%d-%m-%Y')})
    except ValueError as ex:
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(ex)}), 400
    except Exception:
        db.session.rollback()
        app.logger.exception('task_report_upload_core')
        return jsonify({'ok': False, 'error': 'Emergency/Mileage processing failed.'}), 500



@app.route('/task-report/upload/activity-one', methods=['POST'])
def task_report_upload_activity_one():
    """Import a single Tracker Activity workbook per request (multi-step upload)."""
    task_date = _json_task_date()
    if not task_date:
        return jsonify({'ok': False, 'error': 'Invalid or missing report date.'}), 400
    clear_activity = request.form.get('clear_activity') in ('1', 'true', 'on', 'yes')
    fa = request.files.get('file_activity')
    if not fa or not getattr(fa, 'filename', '').strip():
        return jsonify({'ok': False, 'error': 'No activity file.'}), 400
    try:
        if clear_activity:
            VehicleActivityRecord.query.filter_by(task_date=task_date).delete()
        today = pk_date()
        seen_rows = set()
        rows_added, processed = _parse_activity_report_single_file(fa, task_date, today, seen_rows)
        if not processed:
            db.session.rollback()
            return jsonify({'ok': False, 'error': f"No usable data in '{fa.filename}' (empty file or sheet missing activity rows)."}), 400
        db.session.commit()
        return jsonify({'ok': True, 'rows': rows_added, 'filename': fa.filename, 'task_date': task_date.strftime('%d-%m-%Y')})
    except ValueError as ex:
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(ex)}), 400
    except Exception:
        db.session.rollback()
        app.logger.exception('task_report_upload_activity_one')
        return jsonify({'ok': False, 'error': 'Tracker Activity Report processing failed.'}), 500



@app.route('/task-report/upload', methods=['GET', 'POST'])
def task_report_upload():
    """Single form: upload both EmergencyTaskReport and Vehicle Mileage Excel."""
    form = TaskReportUploadBothForm()
    if request.method == 'POST' and form.validate_on_submit():
        task_date = form.task_date.data
        fe = form.file_emergency.data
        fm = form.file_mileage.data
        fa = [f for f in request.files.getlist('file_activity_reports') if f and getattr(f, 'filename', '').strip()]
        if not fe and not fm and not fa:
            flash('Please select at least one Excel file.', 'warning')
            return redirect(url_for('task_report_upload'))
        try:
            c1 = c2 = 0
            c3_files = c3_rows = 0
            if fe:
                try:
                    c1 = _parse_emergency_excel(fe, task_date)
                except Exception as ex:
                    if isinstance(ex, ValueError):
                        raise
                    raise ValueError(f"EmergencyTaskReport processing failed: {ex.__class__.__name__}") from ex
            if fm:
                try:
                    c2 = _parse_mileage_excel(fm, task_date)
                except Exception as ex:
                    if isinstance(ex, ValueError):
                        raise
                    raise ValueError(f"Vehicle Mileage report processing failed: {ex.__class__.__name__}") from ex
            if fa:
                try:
                    c3 = _parse_activity_report_excels(fa, task_date)
                    c3_files = c3.get('files', 0)
                    c3_rows = c3.get('rows', 0)
                except Exception as ex:
                    if isinstance(ex, ValueError):
                        raise
                    raise ValueError(f"Tracker Activity Report processing failed: {ex.__class__.__name__}") from ex
            db.session.commit()
            msg = []
            if c1:
                msg.append(f'EmergencyTaskReport: {c1} record(s)')
            if c2:
                msg.append(f'Mileage report: {c2} record(s)')
            if c3_files:
                msg.append(f'Activity report: {c3_rows} record(s) from {c3_files} file(s)')
            flash('Uploaded. ' + '; '.join(msg) if msg else 'No data imported.', 'success')
            return redirect(url_for('task_report_list', date=task_date.strftime('%d-%m-%Y')))
        except Exception as e:
            db.session.rollback()
            app.logger.exception(
                "Upload Workbooks failed for date=%s (has_emergency=%s, has_mileage=%s, has_activity=%s)",
                task_date,
                bool(fe),
                bool(fm),
                bool(fa),
            )
            flash(_build_upload_error_message('Upload Workbooks', e), 'danger')
    return render_template('task_report_upload.html', form=form,
                          **_nav_back_ctx(url_for('module_hub', hub_slug='task-logbook'), show_without_nav_from=True))



@app.route('/task-report/upload/list', methods=['GET'])
def task_report_upload_list():
    """Read-only log: workbook import stats from Emergency / Mileage / Activity tables (no separate upload log table)."""
    today = pk_date()
    default_from = today - timedelta(days=90)
    from_date = parse_date(request.args.get('from_date')) or default_from
    to_date = parse_date(request.args.get('to_date')) or today
    if from_date > to_date:
        from_date, to_date = to_date, from_date

    form = TaskReportFilterForm()
    form.from_date.data = from_date
    form.to_date.data = to_date
    form.district_id.choices = [(0, '--')]
    form.project_id.choices = [(0, '--')]

    emg_stats = {
        row[0]: {'count': int(row[1]), 'last_at': row[2]}
        for row in db.session.query(
            EmergencyTaskRecord.task_date,
            func.count(EmergencyTaskRecord.id),
            func.max(EmergencyTaskRecord.created_at),
        ).filter(
            EmergencyTaskRecord.task_date >= from_date,
            EmergencyTaskRecord.task_date <= to_date,
        ).group_by(EmergencyTaskRecord.task_date).all()
    }

    mil_stats = {
        row[0]: {'count': int(row[1]), 'last_at': row[2]}
        for row in db.session.query(
            VehicleMileageRecord.task_date,
            func.count(VehicleMileageRecord.id),
            func.max(VehicleMileageRecord.created_at),
        ).filter(
            VehicleMileageRecord.task_date >= from_date,
            VehicleMileageRecord.task_date <= to_date,
        ).group_by(VehicleMileageRecord.task_date).all()
    }

    activity_cap = 1200
    act_q = (
        db.session.query(
            VehicleActivityRecord.task_date,
            VehicleActivityRecord.source_file,
            func.count(VehicleActivityRecord.id),
            func.max(VehicleActivityRecord.created_at),
        )
        .filter(
            VehicleActivityRecord.task_date >= from_date,
            VehicleActivityRecord.task_date <= to_date,
        )
        .group_by(VehicleActivityRecord.task_date, VehicleActivityRecord.source_file)
        .order_by(VehicleActivityRecord.task_date.desc(), VehicleActivityRecord.source_file.asc())
    )
    act_rows_all = act_q.all()

    act_by_date = {}
    for row in act_rows_all:
        td = row[0]
        fn = row[1] or '(unknown file)'
        cnt = int(row[2])
        la = row[3]
        act_by_date.setdefault(td, {'files': 0, 'rows': 0, 'last_at': None})
        act_by_date[td]['files'] += 1
        act_by_date[td]['rows'] += cnt
        if la and (act_by_date[td]['last_at'] is None or la > act_by_date[td]['last_at']):
            act_by_date[td]['last_at'] = la

    act_detail = []
    for row in act_rows_all[:activity_cap]:
        act_detail.append({
            'task_date': row[0],
            'filename': row[1] or '(unknown file)',
            'rows': int(row[2]),
            'last_at': row[3],
        })
    activity_truncated = len(act_rows_all) > activity_cap

    all_dates = sorted(set(emg_stats.keys()) | set(mil_stats.keys()) | set(act_by_date.keys()), reverse=True)
    summary_rows = []
    for td in all_dates:
        em = emg_stats.get(td, {})
        mi = mil_stats.get(td, {})
        ac = act_by_date.get(td, {})
        summary_rows.append({
            'task_date': td,
            'emergency_count': em.get('count', 0),
            'emergency_last': em.get('last_at'),
            'mileage_count': mi.get('count', 0),
            'mileage_last': mi.get('last_at'),
            'activity_files': ac.get('files', 0),
            'activity_rows': ac.get('rows', 0),
            'activity_last': ac.get('last_at'),
        })

    page = request.args.get('page', 1, type=int) or 1
    per_page = request.args.get('per_page', 25, type=int) or 25
    pagination = SimplePagination(summary_rows, page, per_page)

    return render_template(
        'task_report_upload_list.html',
        form=form,
        summary_rows=pagination.items,
        activity_detail=act_detail,
        activity_truncated=activity_truncated,
        activity_cap=activity_cap,
        activity_file_total=len(act_rows_all),
        from_date=from_date,
        to_date=to_date,
        pagination=pagination,
        per_page=per_page,
        **_nav_back_ctx(url_for('module_hub', hub_slug='task-logbook'), show_without_nav_from=True),
    )


