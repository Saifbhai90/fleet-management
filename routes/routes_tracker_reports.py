"""
Tracker & Operations Reports: Active Drivers, Oil Change, Speed Monitoring,
Mileage, Unauthorized Movement, Task Start Delay, Task Turnaround,
Tracker Difference, Driver Seat, Missing Documents.

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
    VehicleActivityRecord, DriverAttendance, FuelExpense,
    DriverTransfer, DriverStatusChange, Employee, EmployeePost,
    SystemSetting, User, ActivityLog,
)
from datetime import datetime, date, timedelta
from sqlalchemy import func, text, or_, and_
from auth_utils import user_can_access, get_user_context
from utils import pk_now, pk_date, parse_date, format_date_ddmmyyyy, generate_csv_response
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
    _oil_change_alert_rows,
    _vehicle_query_task_report_scope,
    _norm_district_name_key,
    _normalize_vehicle_no,
    _build_driver_update_whatsapp_parts,
    _parse_time,
    _time_input_value,
    _load_pdf_writer_reader,
    _html_to_pdf_bytes,
    _active_drivers_data,
    _build_salary_slip_driver_choices,
    _build_umr_timeline_excel,
    _build_unauthorized_movement_timeline,
    _coerce_salary_slip_chain,
    _driver_accessible_for_salary_slip,
    _driver_response_vehicle_activity_request,
    _driver_to_salary_slip_payload,
    _filter_task_start_delay_rows,
    _filter_task_turnaround_rows,
    _filter_unauthorized_movement_rows,
    _get_vehicle_family_oil_change_limits,
    _mileage_report_preview_context,
    _mileage_report_rows,
    _parse_active_driver_filters,
    _parse_duration_limit_hhmm,
    _parse_salary_slip_filters,
    _seat_available_data,
    _speed_monitoring_report_preview_context,
    _speed_monitoring_rows,
    _task_start_delay_report_filters_from_request,
    _task_start_delay_report_preview_context,
    _task_start_delay_rows,
    _task_turnaround_report_preview_context,
    _task_turnaround_rows,
    _tracker_difference_report_preview_context,
    _tracker_difference_rows,
    _unauthorized_movement_preview_context,
    _unauthorized_movement_rows,
    _workspace_employee_id_for_expenses,
)

from sqlalchemy.orm import joinedload
from utils import format_reading, generate_excel_template
from models import project_district
@app.route('/api/salary-slip/driver/<int:driver_id>')
def api_salary_slip_driver(driver_id):
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    driver = Driver.query.options(
        joinedload(Driver.vehicle),
        joinedload(Driver.district),
        joinedload(Driver.project),
    ).filter_by(id=driver_id).first()
    if not driver or not _driver_accessible_for_salary_slip(driver, user_context):
        return jsonify({'ok': False, 'error': 'Driver not found or access denied.'}), 404
    return jsonify({'ok': True, 'driver': _driver_to_salary_slip_payload(driver)})



@app.route('/api/salary-slip/drivers-for-vehicle')
def api_salary_slip_drivers_for_vehicle():
    """Active drivers on the selected vehicle (for salary slip), scoped to user assignments."""
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    vehicle_id = request.args.get('vehicle_id', type=int) or 0
    if not vehicle_id:
        return jsonify([])
    rows = (
        Driver.query.filter(Driver.vehicle_id == vehicle_id, Driver.status == 'Active')
        .order_by(Driver.name)
        .all()
    )
    out = []
    for d in rows:
        if _driver_accessible_for_salary_slip(d, user_context):
            out.append(
                {
                    'id': d.id,
                    'name': d.name,
                    'driver_id': d.driver_id or '',
                    'label': f"{d.name} ({d.driver_id or '-'})",
                }
            )
    return jsonify(out)



@app.route('/reports/driver-salary-slip')
def driver_salary_slip():
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)

    district_id, project_id, vehicle_id, selected_driver_id = _parse_salary_slip_filters()

    disable_district = False
    disable_project = False
    disable_vehicle = False
    if not is_master_or_admin:
        if len(allowed_districts) == 1:
            if not district_id:
                district_id = next(iter(allowed_districts))
            disable_district = True
        if len(allowed_projects) == 1:
            only_p = next(iter(allowed_projects))
            if (district_id
                    and db.session.query(project_district).filter_by(
                        district_id=district_id, project_id=only_p).first()):
                if not project_id:
                    project_id = only_p
                disable_project = True
        if len(allowed_vehicles) == 1:
            only_v = next(iter(allowed_vehicles))
            if (not vehicle_id) and district_id and project_id:
                vrow = db.session.get(Vehicle, only_v)
                if (vrow and vrow.district_id == district_id
                        and (vrow.project_id or 0) == (project_id or 0)):
                    vehicle_id = only_v
            if vehicle_id == only_v:
                disable_vehicle = True

    district_id, project_id, vehicle_id, selected_driver_id = _coerce_salary_slip_chain(
        district_id, project_id, vehicle_id, selected_driver_id, user_context
    )

    # District: all in scope
    dist_q = District.query.order_by(District.name)
    if not is_master_or_admin and allowed_districts:
        dist_q = dist_q.filter(District.id.in_(list(allowed_districts)))
    district_choices = [(0, '— Select district —')] + [(d.id, d.name) for d in dist_q.all()]

    # Project: only if linked to selected district
    if not district_id:
        project_choices = [(0, '— Select district first —')]
    else:
        proj_q = (
            Project.query.join(project_district, Project.id == project_district.c.project_id)
            .filter(project_district.c.district_id == district_id)
        )
        if not is_master_or_admin and allowed_projects:
            proj_q = proj_q.filter(Project.id.in_(list(allowed_projects)))
        p_rows = proj_q.order_by(Project.name).all()
        if not p_rows:
            project_choices = [(0, '— No project in this district —')]
        else:
            project_choices = [(0, '— Select project —')] + [(p.id, p.name) for p in p_rows]

    # Vehicle: same district + project as master assignment (all-vehicles query)
    if not district_id or not project_id:
        vehicle_choices = [(0, '— Select district & project first —')]
    else:
        veh_q = Vehicle.query.filter(
            Vehicle.project_id == project_id,
            Vehicle.district_id == district_id,
        )
        if not is_master_or_admin and allowed_vehicles:
            veh_q = veh_q.filter(Vehicle.id.in_(list(allowed_vehicles)))
        v_rows = veh_q.order_by(*vehicle_order_by()).all()
        if not v_rows:
            vehicle_choices = [(0, '— No vehicle for this project & district —')]
        else:
            vehicle_choices = [(0, '— Select vehicle —')] + [(v.id, v.vehicle_no) for v in v_rows]

    # Driver: only on selected vehicle
    if not vehicle_id:
        driver_choices = []
    else:
        driver_choices = _build_salary_slip_driver_choices(vehicle_id, user_context)

    valid_d_ids = {d[0] for d in driver_choices}
    if selected_driver_id and selected_driver_id not in valid_d_ids:
        selected_driver_id = 0

    return render_template(
        'driver_salary_slip.html',
        project_id=project_id,
        district_id=district_id,
        vehicle_id=vehicle_id,
        selected_driver_id=selected_driver_id,
        project_choices=project_choices,
        district_choices=district_choices,
        vehicle_choices=vehicle_choices,
        driver_choices=driver_choices,
        disable_project=disable_project,
        disable_district=disable_district,
        disable_vehicle=disable_vehicle,
        cert_date_default=pk_date().strftime('%d-%m-%Y'),
    )



@app.route('/active-drivers-report')
def active_drivers_report():
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects  = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles  = user_context.get('allowed_vehicles', set())
    allowed_shifts    = user_context.get('allowed_shifts', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)

    project_id, district_id, vehicle_id, shift, \
        from_date_str, to_date_str, from_date_val, to_date_val = _parse_active_driver_filters()

    # Auto-select if user has exactly 1 option for each field
    disable_project  = False
    disable_district = False
    disable_vehicle  = False
    disable_shift    = False
    if not is_master_or_admin:
        if len(allowed_projects) == 1:
            if not project_id:
                project_id = next(iter(allowed_projects))
            disable_project = True
        if len(allowed_districts) == 1:
            if not district_id:
                district_id = next(iter(allowed_districts))
            disable_district = True
        if len(allowed_vehicles) == 1:
            if not vehicle_id:
                vehicle_id = next(iter(allowed_vehicles))
            disable_vehicle = True
        if len(allowed_shifts) == 1:
            if not shift:
                shift = next(iter(allowed_shifts))
            disable_shift = True

    results = _active_drivers_data(
        project_id=project_id, district_id=district_id, vehicle_id=vehicle_id,
        shift=shift, from_date_val=from_date_val, to_date_val=to_date_val,
        allowed_vehicles=allowed_vehicles, allowed_projects=allowed_projects,
        allowed_districts=allowed_districts, is_master_or_admin=is_master_or_admin
    )

    proj_q = Project.query.order_by(Project.name)
    if not is_master_or_admin and allowed_projects:
        proj_q = proj_q.filter(Project.id.in_(list(allowed_projects)))
    project_choices = [(0, '-- All Projects --')] + [(p.id, p.name) for p in proj_q.all()]

    dist_q = District.query.order_by(District.name)
    if not is_master_or_admin and allowed_districts:
        dist_q = dist_q.filter(District.id.in_(list(allowed_districts)))
    if project_id:
        dist_q = dist_q.join(project_district).filter(project_district.c.project_id == project_id)
    district_choices = [(0, '-- All Districts --')] + [(d.id, d.name) for d in dist_q.all()]

    veh_q = db.session.query(Vehicle).join(Driver, Vehicle.id == Driver.vehicle_id).filter(
        Driver.vehicle_id.isnot(None), Driver.status != 'Left'
    ).distinct().order_by(*vehicle_order_by())
    if not is_master_or_admin and allowed_vehicles:
        veh_q = veh_q.filter(Vehicle.id.in_(list(allowed_vehicles)))
    if project_id:
        veh_q = veh_q.filter(or_(Vehicle.project_id == project_id, Driver.project_id == project_id))
    if district_id:
        veh_q = veh_q.filter(Vehicle.district_id == district_id)
    vehicle_choices = [(0, '-- All Vehicles --')] + [(v.id, v.vehicle_no) for v in veh_q.all()]

    return render_template(
        'active_driver_summary.html',
        results=results,
        project_id=project_id, district_id=district_id,
        vehicle_id=vehicle_id, shift=shift,
        from_date=from_date_str, to_date=to_date_str,
        project_choices=project_choices,
        district_choices=district_choices,
        vehicle_choices=vehicle_choices,
        total=len(results),
        disable_project=disable_project,
        disable_district=disable_district,
        disable_vehicle=disable_vehicle,
        disable_shift=disable_shift,
    )



@app.route('/active-drivers-report/export')
def active_drivers_report_export():
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles  = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)
    project_id, district_id, vehicle_id, shift, \
        from_date_str, to_date_str, from_date_val, to_date_val = _parse_active_driver_filters()

    results = _active_drivers_data(
        project_id=project_id, district_id=district_id, vehicle_id=vehicle_id,
        shift=shift, from_date_val=from_date_val, to_date_val=to_date_val,
        allowed_vehicles=allowed_vehicles, allowed_projects=allowed_projects,
        allowed_districts=allowed_districts, is_master_or_admin=is_master_or_admin,
    )

    headers = ['Sr No', 'Project', 'District', 'Vehicle No (Model) (Type)', 'Driver Name (ID)', 'Shift', 'Assign Date', 'Rejoin Date']
    rows = []
    for i, (driver, vehicle, project, district, rejoin_date) in enumerate(results, 1):
        veh_str = vehicle.vehicle_no if vehicle else '-'
        if vehicle and vehicle.model:
            veh_str += f' ({vehicle.model})'
        if vehicle and vehicle.vehicle_type:
            veh_str += f' ({vehicle.vehicle_type})'
        rows.append([
            i,
            project.name if project else '-',
            district.name if district else '-',
            veh_str,
            f"{driver.name} ({driver.driver_id})" if driver else '-',
            driver.shift or '-',
            driver.assign_date.strftime('%d-%m-%Y') if driver and driver.assign_date else '-',
            rejoin_date.strftime('%d-%m-%Y') if rejoin_date else '-',
        ])
    return generate_excel_template(
        headers, rows, required_columns=[],
        filename=f'active_drivers_{pk_now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    )



@app.route('/active-drivers-report/print')
def active_drivers_report_print():
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles  = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)
    project_id, district_id, vehicle_id, shift, \
        from_date_str, to_date_str, from_date_val, to_date_val = _parse_active_driver_filters()

    results = _active_drivers_data(
        project_id=project_id, district_id=district_id, vehicle_id=vehicle_id,
        shift=shift, from_date_val=from_date_val, to_date_val=to_date_val,
        allowed_vehicles=allowed_vehicles, allowed_projects=allowed_projects,
        allowed_districts=allowed_districts, is_master_or_admin=is_master_or_admin,
    )

    return render_template(
        'active_driver_summary_print.html',
        results=results, total=len(results),
        from_date=from_date_str, to_date=to_date_str,
        now=datetime.now,
    )



@app.route('/oil-change-alert-report')
def oil_change_alert_report():
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)
    workspace_employee_id = _workspace_employee_id_for_expenses()

    from_date = parse_date(request.args.get('from_date'))
    to_date = parse_date(request.args.get('to_date'))
    if from_date and to_date and from_date > to_date:
        from_date, to_date = to_date, from_date
    project_id = request.args.get('project_id', type=int) or 0
    district_id = request.args.get('district_id', type=int) or 0
    vehicle_family = (request.args.get('vehicle_family') or '').strip()
    status_values = []
    for s in request.args.getlist('status'):
        sv = (s or '').strip().lower()
        if sv in ('safe', 'near', 'crossed') and sv not in status_values:
            status_values.append(sv)
    custom_km_raw = (request.args.get('custom_km') or '').strip()
    custom_km_mode = (request.args.get('custom_km_mode') or '').strip().lower()
    if custom_km_mode not in ('', 'above', 'below'):
        custom_km_mode = ''
    custom_km = None
    if custom_km_raw:
        try:
            custom_km = float(custom_km_raw)
            if custom_km < 0:
                custom_km = None
                custom_km_raw = ''
        except Exception:
            custom_km = None
            custom_km_raw = ''

    rows = _oil_change_alert_rows(
        project_id=project_id,
        district_id=district_id,
        vehicle_family=vehicle_family,
        from_date=from_date,
        to_date=to_date,
        statuses=status_values,
        custom_km=custom_km,
        custom_km_mode=custom_km_mode,
        workspace_employee_id=workspace_employee_id,
        allowed_projects=allowed_projects,
        allowed_districts=allowed_districts,
        allowed_vehicles=allowed_vehicles,
        is_master_or_admin=is_master_or_admin,
    )

    project_q = Project.query.order_by(Project.name)
    if not is_master_or_admin and allowed_projects:
        project_q = project_q.filter(Project.id.in_(list(allowed_projects)))
    project_choices = [(0, '-- All Projects --')] + [(p.id, p.name) for p in project_q.all()]

    district_q = District.query.order_by(District.name)
    if not is_master_or_admin and allowed_districts:
        district_q = district_q.filter(District.id.in_(list(allowed_districts)))
    if project_id:
        district_q = district_q.join(project_district).filter(project_district.c.project_id == project_id)
    district_choices = [(0, '-- All Districts --')] + [(d.id, d.name) for d in district_q.all()]

    limits = _get_vehicle_family_oil_change_limits()
    family_choices = [('', '-- All Families --')] + [
        (k, f"{k} ({v.get('limit_km')} KM / Near {v.get('near_percent')}%)")
        for k, v in sorted(limits.items())
    ]

    ahead_count = None
    behind_count = None
    if custom_km is not None:
        ahead_count = sum(1 for r in rows if r.get('custom_state') == 'ahead')
        behind_count = sum(1 for r in rows if r.get('custom_state') == 'behind')

    return render_template(
        'oil_change_alert_report.html',
        rows=rows,
        total=len(rows),
        from_date=from_date,
        to_date=to_date,
        project_id=project_id,
        district_id=district_id,
        vehicle_family=vehicle_family,
        status_values=status_values,
        project_choices=project_choices,
        district_choices=district_choices,
        family_choices=family_choices,
        custom_km=custom_km_raw,
        custom_km_mode=custom_km_mode,
        ahead_count=ahead_count,
        behind_count=behind_count,
    )



@app.route('/oil-change-alert-report/export')
def oil_change_alert_report_export():
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)
    workspace_employee_id = _workspace_employee_id_for_expenses()

    from_date = parse_date(request.args.get('from_date'))
    to_date = parse_date(request.args.get('to_date'))
    if from_date and to_date and from_date > to_date:
        from_date, to_date = to_date, from_date
    project_id = request.args.get('project_id', type=int) or 0
    district_id = request.args.get('district_id', type=int) or 0
    vehicle_family = (request.args.get('vehicle_family') or '').strip()
    status_values = []
    for s in request.args.getlist('status'):
        sv = (s or '').strip().lower()
        if sv in ('safe', 'near', 'crossed') and sv not in status_values:
            status_values.append(sv)
    custom_km_raw = (request.args.get('custom_km') or '').strip()
    custom_km_mode = (request.args.get('custom_km_mode') or '').strip().lower()
    if custom_km_mode not in ('', 'above', 'below'):
        custom_km_mode = ''
    custom_km = None
    if custom_km_raw:
        try:
            custom_km = float(custom_km_raw)
            if custom_km < 0:
                custom_km = None
                custom_km_raw = ''
        except Exception:
            custom_km = None
            custom_km_raw = ''

    rows = _oil_change_alert_rows(
        project_id=project_id,
        district_id=district_id,
        vehicle_family=vehicle_family,
        from_date=from_date,
        to_date=to_date,
        statuses=status_values,
        custom_km=custom_km,
        custom_km_mode=custom_km_mode,
        workspace_employee_id=workspace_employee_id,
        allowed_projects=allowed_projects,
        allowed_districts=allowed_districts,
        allowed_vehicles=allowed_vehicles,
        is_master_or_admin=is_master_or_admin,
    )

    headers = [
        'Sr No', 'Project', 'District', 'Tehsil', 'Vehicle No', 'Model', 'Type', 'Family',
        'Limit KM', 'Near %', 'Last Oil Change Date', 'Base Reading', 'Current Reading', 'KM After Oil', 'Remaining KM', 'Status', 'Custom KM Check',
        'Base Source', 'Current Source'
    ]
    data_rows = []
    for idx, r in enumerate(rows, 1):
        v = r['vehicle']
        data_rows.append([
            idx,
            r['project'].name if r['project'] else '-',
            r['district'].name if r['district'] else '-',
            r.get('tehsil') or '-',
            v.vehicle_no if v else '-',
            v.model if v and v.model else '-',
            v.vehicle_type if v and v.vehicle_type else '-',
            r['vehicle_family'],
            r['limit_km'],
            r['near_percent'],
            r['last_oil_change_date'].strftime('%d-%m-%Y') if r.get('last_oil_change_date') else '-',
            r['base_reading'],
            r['current_reading'],
            r['kms_after_oil'],
            r['remaining_km'],
            'Crossed' if r['status'] == 'crossed' else 'Near' if r['status'] == 'near' else 'Safe',
            (
                f"Ahead ({abs(r['custom_diff']):.2f})" if r.get('custom_state') == 'ahead'
                else f"Behind ({abs(r['custom_diff']):.2f})" if r.get('custom_state') == 'behind'
                else "Equal (0.00)" if r.get('custom_state') == 'equal'
                else '-'
            ),
            r['base_source'] or '-',
            r['current_source'] or '-',
        ])
    return generate_excel_template(
        headers, data_rows, required_columns=[],
        filename=f'oil_change_alert_{pk_now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    )



@app.route('/oil-change-alert-report/print')
def oil_change_alert_report_print():
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)
    workspace_employee_id = _workspace_employee_id_for_expenses()

    from_date = parse_date(request.args.get('from_date'))
    to_date = parse_date(request.args.get('to_date'))
    if from_date and to_date and from_date > to_date:
        from_date, to_date = to_date, from_date
    project_id = request.args.get('project_id', type=int) or 0
    district_id = request.args.get('district_id', type=int) or 0
    vehicle_family = (request.args.get('vehicle_family') or '').strip()
    status_values = []
    for s in request.args.getlist('status'):
        sv = (s or '').strip().lower()
        if sv in ('safe', 'near', 'crossed') and sv not in status_values:
            status_values.append(sv)
    custom_km_raw = (request.args.get('custom_km') or '').strip()
    custom_km_mode = (request.args.get('custom_km_mode') or '').strip().lower()
    if custom_km_mode not in ('', 'above', 'below'):
        custom_km_mode = ''
    custom_km = None
    if custom_km_raw:
        try:
            custom_km = float(custom_km_raw)
            if custom_km < 0:
                custom_km = None
                custom_km_raw = ''
        except Exception:
            custom_km = None
            custom_km_raw = ''

    rows = _oil_change_alert_rows(
        project_id=project_id,
        district_id=district_id,
        vehicle_family=vehicle_family,
        from_date=from_date,
        to_date=to_date,
        statuses=status_values,
        custom_km=custom_km,
        custom_km_mode=custom_km_mode,
        workspace_employee_id=workspace_employee_id,
        allowed_projects=allowed_projects,
        allowed_districts=allowed_districts,
        allowed_vehicles=allowed_vehicles,
        is_master_or_admin=is_master_or_admin,
    )

    return render_template(
        'oil_change_alert_report_print.html',
        rows=rows,
        total=len(rows),
        from_date=from_date,
        to_date=to_date,
        status_values=status_values,
        custom_km=custom_km_raw,
        custom_km_mode=custom_km_mode,
        now=datetime.now,
    )



@app.route('/speed-monitoring-report')
def speed_monitoring_report():
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)

    from_date = parse_date(request.args.get('from_date')) or pk_date()
    to_date = parse_date(request.args.get('to_date')) or pk_date()
    if from_date and to_date and from_date > to_date:
        from_date, to_date = to_date, from_date

    project_id = request.args.get('project_id', type=int) or 0
    district_id = request.args.get('district_id', type=int) or 0
    vehicle_id = request.args.get('vehicle_id', type=int) or 0
    check_type = (request.args.get('check_type') or '').strip().lower()
    if check_type not in ('', 'above', 'below'):
        check_type = ''

    speed_limit_raw = (request.args.get('speed_limit') or '').strip()
    speed_limit = None
    if speed_limit_raw:
        try:
            speed_limit = float(speed_limit_raw)
            if speed_limit < 0:
                speed_limit = None
                speed_limit_raw = ''
        except Exception:
            speed_limit = None
            speed_limit_raw = ''

    rows = []
    must_filter_missing = False
    if not district_id or not project_id or not check_type or speed_limit is None:
        must_filter_missing = True
        if request.args:
            flash('Please select required filters: District, Project, Check Type, and Speed Limit.', 'warning')
    else:
        rows = _speed_monitoring_rows(
            from_date=from_date,
            to_date=to_date,
            project_id=project_id,
            district_id=district_id,
            vehicle_id=vehicle_id,
            check_type=check_type,
            speed_limit=speed_limit,
            allowed_projects=allowed_projects,
            allowed_districts=allowed_districts,
            allowed_vehicles=allowed_vehicles,
            is_master_or_admin=is_master_or_admin,
        )

    project_q = Project.query.order_by(Project.name)
    if not is_master_or_admin and allowed_projects:
        project_q = project_q.filter(Project.id.in_(list(allowed_projects)))
    project_choices = [(0, '-- All Projects --')] + [(p.id, p.name) for p in project_q.all()]

    district_q = District.query.order_by(District.name)
    if not is_master_or_admin and allowed_districts:
        district_q = district_q.filter(District.id.in_(list(allowed_districts)))
    if project_id:
        district_q = district_q.join(project_district).filter(project_district.c.project_id == project_id)
    district_choices = [(0, '-- All Districts --')] + [(d.id, d.name) for d in district_q.all()]

    vehicle_q = Vehicle.query.order_by(*vehicle_order_by())
    if not is_master_or_admin and allowed_vehicles:
        vehicle_q = vehicle_q.filter(Vehicle.id.in_(list(allowed_vehicles)))
    if project_id:
        vehicle_q = vehicle_q.filter(Vehicle.project_id == project_id)
    if district_id:
        vehicle_q = vehicle_q.filter(Vehicle.district_id == district_id)
    vehicle_choices = [(0, '-- All Vehicles --')] + [(v.id, v.vehicle_no) for v in vehicle_q.all()]

    unique_vehicle_count = len({r['vehicle'].id for r in rows if r.get('vehicle')})

    return render_template(
        'speed_monitoring_report.html',
        rows=rows,
        total=len(rows),
        unique_vehicle_count=unique_vehicle_count,
        must_filter_missing=must_filter_missing,
        from_date=from_date,
        to_date=to_date,
        project_id=project_id,
        district_id=district_id,
        vehicle_id=vehicle_id,
        check_type=check_type,
        speed_limit=speed_limit_raw,
        project_choices=project_choices,
        district_choices=district_choices,
        vehicle_choices=vehicle_choices,
        **_nav_back_ctx(url_for('reports_index'), show_without_nav_from=True),
    )



@app.route('/speed-monitoring-report/export')
def speed_monitoring_report_export():
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)

    from_date = parse_date(request.args.get('from_date')) or pk_date()
    to_date = parse_date(request.args.get('to_date')) or pk_date()
    if from_date and to_date and from_date > to_date:
        from_date, to_date = to_date, from_date

    project_id = request.args.get('project_id', type=int) or 0
    district_id = request.args.get('district_id', type=int) or 0
    vehicle_id = request.args.get('vehicle_id', type=int) or 0
    check_type = (request.args.get('check_type') or '').strip().lower()
    if check_type not in ('', 'above', 'below'):
        check_type = ''

    speed_limit_raw = (request.args.get('speed_limit') or '').strip()
    speed_limit = None
    if speed_limit_raw:
        try:
            speed_limit = float(speed_limit_raw)
            if speed_limit < 0:
                speed_limit = None
        except Exception:
            speed_limit = None

    rows = _speed_monitoring_rows(
        from_date=from_date,
        to_date=to_date,
        project_id=project_id,
        district_id=district_id,
        vehicle_id=vehicle_id,
        check_type=check_type,
        speed_limit=speed_limit,
        allowed_projects=allowed_projects,
        allowed_districts=allowed_districts,
        allowed_vehicles=allowed_vehicles,
        is_master_or_admin=is_master_or_admin,
    )
    table_search = (request.args.get('table_search') or '').strip().lower()
    if table_search:
        def _matches_search(r):
            blob = ' '.join([
                r['district'].name if r.get('district') else '',
                r['project'].name if r.get('project') else '',
                r['vehicle'].vehicle_no if r.get('vehicle') else (r['rec'].vehicle_no or ''),
                r['record_dt'].strftime('%d-%m-%Y %I:%M %p') if r.get('record_dt') else (r['rec'].record_date_time or ''),
                f"{r.get('speed', 0):.2f}",
                r['rec'].reason or '',
                r.get('location_text') or '',
                r.get('check_result') or '',
            ]).lower()
            return table_search in blob
        rows = [r for r in rows if _matches_search(r)]

    headers = ['Sr No', 'District', 'Project', 'Vehicle', 'Record Date Time', 'Speed', 'Reason', 'Location', 'Check Result']
    data_rows = []
    for i, r in enumerate(rows, 1):
        data_rows.append([
            i,
            r['district'].name if r['district'] else '-',
            r['project'].name if r['project'] else '-',
            r['vehicle'].vehicle_no if r['vehicle'] else (r['rec'].vehicle_no or '-'),
            r['record_dt'].strftime('%d-%m-%Y %I:%M %p') if r['record_dt'] else (r['rec'].record_date_time or '-'),
            r['speed'],
            r['rec'].reason or '-',
            r['location_text'] or '-',
            r['check_result'] or '-',
        ])
    return generate_excel_template(
        headers, data_rows, required_columns=[],
        filename=f'speed_monitoring_report_{pk_now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    )



@app.route('/speed-monitoring-report/preview')
def speed_monitoring_report_preview():
    return render_template('speed_monitoring_report_print.html', **_speed_monitoring_report_preview_context())



@app.route('/speed-monitoring-report/print')
def speed_monitoring_report_print():
    # Backward compatibility: keep old print route but use same preview page.
    return render_template('speed_monitoring_report_print.html', **_speed_monitoring_report_preview_context())



@app.route('/mileage-report')
def mileage_report():
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)

    from_date = parse_date(request.args.get('from_date')) or pk_date()
    to_date = parse_date(request.args.get('to_date')) or pk_date()
    if from_date and to_date and from_date > to_date:
        from_date, to_date = to_date, from_date

    project_id = request.args.get('project_id', type=int) or 0
    district_id = request.args.get('district_id', type=int) or 0
    vehicle_id = request.args.get('vehicle_id', type=int) or 0
    check_type = (request.args.get('check_type') or '').strip().lower()
    if check_type not in ('', 'above', 'below'):
        check_type = ''

    km_limit_raw = (request.args.get('km_limit') or '').strip()
    km_limit = None
    if km_limit_raw:
        try:
            km_limit = float(km_limit_raw)
            if km_limit < 0:
                km_limit = None
                km_limit_raw = ''
        except Exception:
            km_limit = None
            km_limit_raw = ''

    rows = _mileage_report_rows(
        from_date=from_date,
        to_date=to_date,
        project_id=project_id,
        district_id=district_id,
        vehicle_id=vehicle_id,
        check_type=check_type,
        km_limit=km_limit,
        allowed_projects=allowed_projects,
        allowed_districts=allowed_districts,
        allowed_vehicles=allowed_vehicles,
        is_master_or_admin=is_master_or_admin,
    )

    project_q = Project.query.order_by(Project.name)
    if not is_master_or_admin and allowed_projects:
        project_q = project_q.filter(Project.id.in_(list(allowed_projects)))
    project_choices = [(0, '-- All Projects --')] + [(p.id, p.name) for p in project_q.all()]

    district_q = District.query.order_by(District.name)
    if not is_master_or_admin and allowed_districts:
        district_q = district_q.filter(District.id.in_(list(allowed_districts)))
    if project_id:
        district_q = district_q.join(project_district).filter(project_district.c.project_id == project_id)
    district_choices = [(0, '-- All Districts --')] + [(d.id, d.name) for d in district_q.all()]

    vehicle_q = Vehicle.query.order_by(*vehicle_order_by())
    if not is_master_or_admin and allowed_vehicles:
        vehicle_q = vehicle_q.filter(Vehicle.id.in_(list(allowed_vehicles)))
    if project_id:
        vehicle_q = vehicle_q.filter(Vehicle.project_id == project_id)
    if district_id:
        vehicle_q = vehicle_q.filter(Vehicle.district_id == district_id)
    vehicle_choices = [(0, '-- All Vehicles --')] + [(v.id, v.vehicle_no) for v in vehicle_q.all()]

    unique_vehicle_count = len({r['vehicle'].id for r in rows if r.get('vehicle')})

    return render_template(
        'mileage_report.html',
        rows=rows,
        total=len(rows),
        unique_vehicle_count=unique_vehicle_count,
        from_date=from_date,
        to_date=to_date,
        project_id=project_id,
        district_id=district_id,
        vehicle_id=vehicle_id,
        check_type=check_type,
        km_limit=km_limit_raw,
        project_choices=project_choices,
        district_choices=district_choices,
        vehicle_choices=vehicle_choices,
        **_nav_back_ctx(url_for('reports_index'), show_without_nav_from=True),
    )



@app.route('/mileage-report/export')
def mileage_report_export():
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)

    from_date = parse_date(request.args.get('from_date')) or pk_date()
    to_date = parse_date(request.args.get('to_date')) or pk_date()
    if from_date and to_date and from_date > to_date:
        from_date, to_date = to_date, from_date
    project_id = request.args.get('project_id', type=int) or 0
    district_id = request.args.get('district_id', type=int) or 0
    vehicle_id = request.args.get('vehicle_id', type=int) or 0
    check_type = (request.args.get('check_type') or '').strip().lower()
    if check_type not in ('', 'above', 'below'):
        check_type = ''
    km_limit_raw = (request.args.get('km_limit') or '').strip()
    km_limit = None
    if km_limit_raw:
        try:
            km_limit = float(km_limit_raw)
            if km_limit < 0:
                km_limit = None
        except Exception:
            km_limit = None

    rows = _mileage_report_rows(
        from_date=from_date, to_date=to_date, project_id=project_id, district_id=district_id,
        vehicle_id=vehicle_id, check_type=check_type, km_limit=km_limit,
        allowed_projects=allowed_projects, allowed_districts=allowed_districts, allowed_vehicles=allowed_vehicles,
        is_master_or_admin=is_master_or_admin,
    )
    table_search = (request.args.get('table_search') or '').strip().lower()
    if table_search:
        def _m(r):
            v = r.get('vehicle')
            tehsil_txt = ''
            vtype_txt = ''
            if v:
                ps = getattr(v, 'parking_station', None)
                if ps:
                    tehsil_txt = ps.tehsil or ''
                vtype_txt = v.vehicle_type or ''
            blob = ' '.join([
                r['rec'].task_date.strftime('%d-%m-%Y') if r['rec'].task_date else '',
                r['district'].name if r.get('district') else '',
                tehsil_txt,
                r['project'].name if r.get('project') else '',
                vtype_txt,
                v.vehicle_no if v else '',
                format_reading(r['start_reading']),
                format_reading(r['close_reading']),
                f"{r['total_km']:.2f}",
                str(r['tasks_count']),
                r.get('check_result') or '',
            ]).lower()
            return table_search in blob
        rows = [r for r in rows if _m(r)]

    headers = ['Sr', 'Date', 'District', 'Tehsil', 'Project', 'Vehicle Type', 'Vehicle', 'Start Reading', 'Close Reading', 'Total KMs', 'Task', 'Check Result']
    data_rows = []
    for i, r in enumerate(rows, 1):
        v = r.get('vehicle')
        tehsil_disp = '-'
        vtype_disp = '-'
        if v:
            ps = getattr(v, 'parking_station', None)
            tehsil_disp = ps.tehsil if ps and ps.tehsil else '-'
            vtype_disp = v.vehicle_type or '-'
        data_rows.append([
            i,
            r['rec'].task_date.strftime('%d-%m-%Y') if r['rec'].task_date else '-',
            r['district'].name if r['district'] else '-',
            tehsil_disp,
            r['project'].name if r['project'] else '-',
            vtype_disp,
            v.vehicle_no if v else '-',
            format_reading(r['start_reading']),
            format_reading(r['close_reading']),
            r['total_km'],
            r['tasks_count'],
            r['check_result'] or '-',
        ])
    return generate_excel_template(
        headers, data_rows, required_columns=[],
        filename=f'mileage_report_{pk_now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    )



@app.route('/mileage-report/preview')
def mileage_report_preview():
    return render_template('mileage_report_print.html', **_mileage_report_preview_context())



@app.route('/mileage-report/print')
def mileage_report_print():
    return render_template('mileage_report_print.html', **_mileage_report_preview_context())



@app.route('/unauthorized-movement-report')
def unauthorized_movement_report():
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)

    from_date = parse_date(request.args.get('from_date')) or pk_date()
    to_date = parse_date(request.args.get('to_date')) or pk_date()
    if from_date and to_date and from_date > to_date:
        from_date, to_date = to_date, from_date

    project_id = request.args.get('project_id', type=int) or 0
    district_id = request.args.get('district_id', type=int) or 0
    vehicle_id = request.args.get('vehicle_id', type=int) or 0
    check_type = (request.args.get('check_type') or '').strip().lower()
    if check_type not in ('', 'above', 'below'):
        check_type = ''
    without_task_move_limit_raw = (request.args.get('without_task_move_limit') or '').strip()
    without_task_move_limit = None
    if without_task_move_limit_raw:
        try:
            without_task_move_limit = float(without_task_move_limit_raw)
            if without_task_move_limit < 0:
                without_task_move_limit = None
                without_task_move_limit_raw = ''
        except Exception:
            without_task_move_limit = None
            without_task_move_limit_raw = ''

    rows = _unauthorized_movement_rows(
        from_date=from_date,
        to_date=to_date,
        project_id=project_id,
        district_id=district_id,
        vehicle_id=vehicle_id,
        check_type=check_type,
        without_task_move_limit=without_task_move_limit,
        allowed_projects=allowed_projects,
        allowed_districts=allowed_districts,
        allowed_vehicles=allowed_vehicles,
        is_master_or_admin=is_master_or_admin,
    )

    project_q = Project.query.order_by(Project.name)
    if not is_master_or_admin and allowed_projects:
        project_q = project_q.filter(Project.id.in_(list(allowed_projects)))
    project_choices = [(0, '-- All Projects --')] + [(p.id, p.name) for p in project_q.all()]

    district_q = District.query.order_by(District.name)
    if not is_master_or_admin and allowed_districts:
        district_q = district_q.filter(District.id.in_(list(allowed_districts)))
    if project_id:
        district_q = district_q.join(project_district).filter(project_district.c.project_id == project_id)
    district_choices = [(0, '-- All Districts --')] + [(d.id, d.name) for d in district_q.all()]

    vehicle_q = Vehicle.query.order_by(*vehicle_order_by())
    if not is_master_or_admin and allowed_vehicles:
        vehicle_q = vehicle_q.filter(Vehicle.id.in_(list(allowed_vehicles)))
    if project_id:
        vehicle_q = vehicle_q.filter(Vehicle.project_id == project_id)
    if district_id:
        vehicle_q = vehicle_q.filter(Vehicle.district_id == district_id)
    vehicle_choices = [(0, '-- All Vehicles --')] + [(v.id, v.vehicle_no) for v in vehicle_q.all()]

    unique_vehicle_count = len({r['vehicle'].id for r in rows if r.get('vehicle')})

    return render_template(
        'unauthorized_movement_report.html',
        rows=rows,
        total=len(rows),
        unique_vehicle_count=unique_vehicle_count,
        from_date=from_date,
        to_date=to_date,
        project_id=project_id,
        district_id=district_id,
        vehicle_id=vehicle_id,
        check_type=check_type,
        without_task_move_limit=without_task_move_limit_raw,
        project_choices=project_choices,
        district_choices=district_choices,
        vehicle_choices=vehicle_choices,
        **_nav_back_ctx(url_for('reports_index'), show_without_nav_from=True),
    )



@app.route('/unauthorized-movement-report/history')
def unauthorized_movement_report_history():
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = set(user_context.get('allowed_projects', set()) or [])
    allowed_districts = set(user_context.get('allowed_districts', set()) or [])
    allowed_vehicles = set(user_context.get('allowed_vehicles', set()) or [])
    is_master_or_admin = user_context.get('is_master_or_admin', False)

    vehicle_id = request.args.get('vehicle_id', type=int) or 0
    from_date = parse_date(request.args.get('from_date')) or pk_date()
    to_date = parse_date(request.args.get('to_date')) or pk_date()
    if from_date > to_date:
        from_date, to_date = to_date, from_date
    if not vehicle_id:
        return jsonify({'ok': False, 'message': 'Vehicle is required.'}), 400

    vq = Vehicle.query.filter(Vehicle.id == vehicle_id)
    if not is_master_or_admin:
        if allowed_vehicles:
            vq = vq.filter(Vehicle.id.in_(list(allowed_vehicles)))
        if allowed_projects:
            vq = vq.filter(Vehicle.project_id.in_(list(allowed_projects)))
        if allowed_districts:
            vq = vq.filter(Vehicle.district_id.in_(list(allowed_districts)))
    v = vq.first()
    if not v:
        return jsonify({'ok': False, 'message': 'Vehicle not found or not allowed.'}), 404

    payload = _build_unauthorized_movement_timeline(v, from_date, to_date)
    payload.update({
        'ok': True,
        'vehicle_id': vehicle_id,
        'vehicle_no': v.vehicle_no or '-',
        'from_date': from_date.strftime('%d-%m-%Y'),
        'to_date': to_date.strftime('%d-%m-%Y'),
    })
    return jsonify(payload)



@app.route('/unauthorized-movement-report/history/export')
def unauthorized_movement_report_history_export():
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = set(user_context.get('allowed_projects', set()) or [])
    allowed_districts = set(user_context.get('allowed_districts', set()) or [])
    allowed_vehicles = set(user_context.get('allowed_vehicles', set()) or [])
    is_master_or_admin = user_context.get('is_master_or_admin', False)

    vehicle_id = request.args.get('vehicle_id', type=int) or 0
    from_date = parse_date(request.args.get('from_date')) or pk_date()
    to_date = parse_date(request.args.get('to_date')) or pk_date()
    if from_date > to_date:
        from_date, to_date = to_date, from_date
    if not vehicle_id:
        flash('Vehicle is required for export.', 'danger')
        return redirect(url_for('unauthorized_movement_report'))

    vq = Vehicle.query.options(
        joinedload(Vehicle.project),
        joinedload(Vehicle.district),
    ).filter(Vehicle.id == vehicle_id)
    if not is_master_or_admin:
        if allowed_vehicles:
            vq = vq.filter(Vehicle.id.in_(list(allowed_vehicles)))
        if allowed_projects:
            vq = vq.filter(Vehicle.project_id.in_(list(allowed_projects)))
        if allowed_districts:
            vq = vq.filter(Vehicle.district_id.in_(list(allowed_districts)))
    v = vq.first()
    if not v:
        flash('Vehicle not found or not allowed.', 'danger')
        return redirect(url_for('unauthorized_movement_report'))

    payload = _build_unauthorized_movement_timeline(v, from_date, to_date)
    project_name = v.project.name if getattr(v, 'project', None) else '-'
    district_name = v.district.name if getattr(v, 'district', None) else '-'
    output = _build_umr_timeline_excel(
        payload,
        vehicle_no=v.vehicle_no or '-',
        project_name=project_name,
        district_name=district_name,
        from_date=from_date,
        to_date=to_date,
    )
    safe_vehicle = re.sub(r'[^\w\-]+', '_', (v.vehicle_no or 'vehicle'))
    download_name = f'Movement_Timeline_{safe_vehicle}_{from_date.strftime("%d-%m-%Y")}_to_{to_date.strftime("%d-%m-%Y")}.xlsx'
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=download_name,
    )



@app.route('/unauthorized-movement-report/export')
def unauthorized_movement_report_export():
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)

    from_date = parse_date(request.args.get('from_date')) or pk_date()
    to_date = parse_date(request.args.get('to_date')) or pk_date()
    if from_date and to_date and from_date > to_date:
        from_date, to_date = to_date, from_date
    project_id = request.args.get('project_id', type=int) or 0
    district_id = request.args.get('district_id', type=int) or 0
    vehicle_id = request.args.get('vehicle_id', type=int) or 0
    check_type = (request.args.get('check_type') or '').strip().lower()
    if check_type not in ('', 'above', 'below'):
        check_type = ''
    without_task_move_limit_raw = (request.args.get('without_task_move_limit') or '').strip()
    without_task_move_limit = None
    if without_task_move_limit_raw:
        try:
            without_task_move_limit = float(without_task_move_limit_raw)
            if without_task_move_limit < 0:
                without_task_move_limit = None
        except Exception:
            without_task_move_limit = None

    rows = _unauthorized_movement_rows(
        from_date=from_date,
        to_date=to_date,
        project_id=project_id,
        district_id=district_id,
        vehicle_id=vehicle_id,
        check_type=check_type,
        without_task_move_limit=without_task_move_limit,
        allowed_projects=allowed_projects,
        allowed_districts=allowed_districts,
        allowed_vehicles=allowed_vehicles,
        is_master_or_admin=is_master_or_admin,
    )
    rows = _filter_unauthorized_movement_rows(rows, request.args.get('table_search'))

    headers = [
        'Sr', 'District', 'Project', 'Vehicle', "Km's Driven", "Tracker Km's",
        "Task Running Km's", "Return To Parking Place Km's", 'Without Task Move',
    ]
    data_rows = []
    for i, r in enumerate(rows, 1):
        data_rows.append([
            i,
            r['district'].name if r['district'] else '-',
            r['project'].name if r['project'] else '-',
            r['vehicle'].vehicle_no if r['vehicle'] else '-',
            r['km_driven'],
            r['tracker_km'],
            r['task_running_km'],
            r['return_to_parking_km'],
            r['without_task_move'],
        ])
    return generate_excel_template(
        headers, data_rows, required_columns=[],
        filename=f'unauthorized_movement_report_{pk_now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    )



@app.route('/unauthorized-movement-report/preview')
def unauthorized_movement_report_preview():
    return render_template('unauthorized_movement_report_print.html', **_unauthorized_movement_preview_context())



@app.route('/unauthorized-movement-report/print')
def unauthorized_movement_report_print():
    return render_template('unauthorized_movement_report_print.html', **_unauthorized_movement_preview_context())



@app.route('/task-start-delay-report')
def task_start_delay_report():
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)

    filters = _task_start_delay_report_filters_from_request(request.args)
    rows = _task_start_delay_rows(
        from_date=filters['from_date'], to_date=filters['to_date'],
        project_id=filters['project_id'], district_id=filters['district_id'], vehicle_id=filters['vehicle_id'],
        check_type=filters['check_type'], delay_limit=filters['delay_limit'],
        start_time_limit=filters['start_time_limit'], end_time_limit=filters['end_time_limit'],
        allowed_projects=allowed_projects, allowed_districts=allowed_districts, allowed_vehicles=allowed_vehicles,
        is_master_or_admin=is_master_or_admin, status=filters['status'],
    )

    project_q = Project.query.order_by(Project.name)
    if not is_master_or_admin and allowed_projects:
        project_q = project_q.filter(Project.id.in_(list(allowed_projects)))
    project_choices = [(0, '-- All Projects --')] + [(p.id, p.name) for p in project_q.all()]

    district_q = District.query.order_by(District.name)
    if not is_master_or_admin and allowed_districts:
        district_q = district_q.filter(District.id.in_(list(allowed_districts)))
    if filters['project_id']:
        district_q = district_q.join(project_district).filter(project_district.c.project_id == filters['project_id'])
    district_choices = [(0, '-- All Districts --')] + [(d.id, d.name) for d in district_q.all()]

    vehicle_q = Vehicle.query.order_by(*vehicle_order_by())
    if not is_master_or_admin and allowed_vehicles:
        vehicle_q = vehicle_q.filter(Vehicle.id.in_(list(allowed_vehicles)))
    if filters['project_id']:
        vehicle_q = vehicle_q.filter(Vehicle.project_id == filters['project_id'])
    if filters['district_id']:
        vehicle_q = vehicle_q.filter(Vehicle.district_id == filters['district_id'])
    vehicle_choices = [(0, '-- All Vehicles --')] + [(v.id, v.vehicle_no) for v in vehicle_q.all()]

    unique_vehicle_count = len({r['vehicle'].id for r in rows if r.get('vehicle')})

    return render_template(
        'task_start_delay_report.html',
        rows=rows,
        total=len(rows),
        unique_vehicle_count=unique_vehicle_count,
        from_date=filters['from_date'], to_date=filters['to_date'],
        project_id=filters['project_id'], district_id=filters['district_id'], vehicle_id=filters['vehicle_id'],
        check_type=filters['check_type'], delay_limit=filters['delay_limit_raw'],
        start_time=_time_input_value(filters['start_time_raw']),
        end_time=_time_input_value(filters['end_time_raw']),
        delay_mode=filters['delay_mode'], time_mode=filters['time_mode'], status=filters['status'],
        filter_group='time' if filters['time_mode'] else ('delay' if filters['delay_mode'] else ''),
        project_choices=project_choices, district_choices=district_choices, vehicle_choices=vehicle_choices,
        **_nav_back_ctx(url_for('reports_index'), show_without_nav_from=True),
    )



@app.route('/task-start-delay-report/export')
def task_start_delay_report_export():
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)

    filters = _task_start_delay_report_filters_from_request(request.args)
    rows = _task_start_delay_rows(
        from_date=filters['from_date'], to_date=filters['to_date'],
        project_id=filters['project_id'], district_id=filters['district_id'], vehicle_id=filters['vehicle_id'],
        check_type=filters['check_type'], delay_limit=filters['delay_limit'],
        start_time_limit=filters['start_time_limit'], end_time_limit=filters['end_time_limit'],
        allowed_projects=allowed_projects, allowed_districts=allowed_districts, allowed_vehicles=allowed_vehicles,
        is_master_or_admin=is_master_or_admin, status=filters['status'],
    )
    rows = _filter_task_start_delay_rows(rows, request.args.get('table_search'))
    headers = [
        'Sr', 'Date', 'District', 'Project', 'Parking', 'Vehicle', 'Task ID', 'Category',
        'Task Create (Assign)', 'Task Close', 'Vehicle Start', 'Delay (min)', 'Delay',
    ]
    data_rows = []
    for i, r in enumerate(rows, 1):
        emg = r['emg']
        data_rows.append([
            i,
            emg.task_date.strftime('%d-%m-%Y') if emg.task_date else '-',
            r['district'].name if r.get('district') else '-',
            r['project'].name if r.get('project') else '-',
            r['vehicle'].parking_station.name if r.get('vehicle') and r['vehicle'].parking_station else '-',
            r['vehicle'].vehicle_no if r.get('vehicle') else '-',
            r['task_id'],
            r['category'],
            r['assign_dt'].strftime('%d-%m-%Y %I:%M %p') if r.get('assign_dt') else '-',
            r['close_dt'].strftime('%d-%m-%Y %I:%M %p') if r.get('close_dt') else '-',
            r['vehicle_start_dt'].strftime('%d-%m-%Y %I:%M %p') if r.get('vehicle_start_dt') else '-',
            r['delay_minutes'] if r.get('delay_minutes') is not None else '',
            r.get('delay_display') or '-',
        ])
    return generate_excel_template(
        headers, data_rows, required_columns=[],
        filename=f'driver_response_time_report_{pk_now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    )



@app.route('/task-start-delay-report/preview')
def task_start_delay_report_preview():
    return render_template('task_start_delay_report_print.html', **_task_start_delay_report_preview_context())



@app.route('/task-start-delay-report/print')
def task_start_delay_report_print():
    return render_template('task_start_delay_report_print.html', **_task_start_delay_report_preview_context())



@app.route('/api/driver-response-time/vehicle-activity')
def api_driver_response_time_vehicle_activity():
    """Vehicle start/stop + ignition activity (with km) within selected range for popup."""
    data, err = _driver_response_vehicle_activity_request()
    if err:
        return jsonify({'ok': False, 'error': err, 'rows': []})
    return jsonify({
        'ok': True,
        'vehicle_no': data['vehicle_no'],
        'from_date': data['from_date'].strftime('%d-%m-%Y'),
        'to_date': data['to_date'].strftime('%d-%m-%Y'),
        'time_from': data['time_from'] or '',
        'time_to': data['time_to'] or '',
        'rows': data['rows'],
        'count': len(data['rows']),
        'total_km': data['total_km'],
        'moving_km': data['moving_km'],
    })



@app.route('/driver-response-time/vehicle-activity/export')
def driver_response_time_vehicle_activity_export():
    """Excel export for the vehicle activity detail popup."""
    data, err = _driver_response_vehicle_activity_request()
    if err:
        return jsonify({'ok': False, 'error': err}), 400
    headers = ['Sr', 'Date & Time', 'Reason', 'Speed (km/h)', 'Distance (km)', 'Travel Time', 'Stop Time', 'Location']
    data_rows = []
    for i, r in enumerate(data['rows'], 1):
        data_rows.append([
            i, r['record_dt'], r['reason'], r['speed'], r['distance'],
            r['travel_time'], r['stop_time'], r['location'],
        ])
    safe_vno = re.sub(r'[^A-Za-z0-9_-]+', '_', data['vehicle_no']) or 'vehicle'
    return generate_excel_template(
        headers, data_rows, required_columns=[],
        filename=f'vehicle_activity_{safe_vno}_{pk_now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    )



@app.route('/task-turnaround-report')
def task_turnaround_report():
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)

    from_date = parse_date(request.args.get('from_date')) or pk_date()
    to_date = parse_date(request.args.get('to_date')) or pk_date()
    if from_date and to_date and from_date > to_date:
        from_date, to_date = to_date, from_date
    project_id = request.args.get('project_id', type=int) or 0
    district_id = request.args.get('district_id', type=int) or 0
    vehicle_id = request.args.get('vehicle_id', type=int) or 0
    check_type = (request.args.get('check_type') or '').strip().lower()
    if check_type not in ('', 'above', 'below'):
        check_type = ''
    duration_limit_raw = (request.args.get('duration_limit') or '').strip()
    time_limit = _parse_duration_limit_hhmm(duration_limit_raw)
    apply_limit = time_limit if (check_type in ('above', 'below') and time_limit is not None) else None

    rows = _task_turnaround_rows(
        from_date=from_date, to_date=to_date, project_id=project_id, district_id=district_id, vehicle_id=vehicle_id,
        check_type=check_type, time_limit=apply_limit,
        allowed_projects=allowed_projects, allowed_districts=allowed_districts, allowed_vehicles=allowed_vehicles,
        is_master_or_admin=is_master_or_admin,
    )

    project_q = Project.query.order_by(Project.name)
    if not is_master_or_admin and allowed_projects:
        project_q = project_q.filter(Project.id.in_(list(allowed_projects)))
    project_choices = [(0, '-- All Projects --')] + [(p.id, p.name) for p in project_q.all()]

    district_q = District.query.order_by(District.name)
    if not is_master_or_admin and allowed_districts:
        district_q = district_q.filter(District.id.in_(list(allowed_districts)))
    if project_id:
        district_q = district_q.join(project_district).filter(project_district.c.project_id == project_id)
    district_choices = [(0, '-- All Districts --')] + [(d.id, d.name) for d in district_q.all()]

    vehicle_q = Vehicle.query.order_by(*vehicle_order_by())
    if not is_master_or_admin and allowed_vehicles:
        vehicle_q = vehicle_q.filter(Vehicle.id.in_(list(allowed_vehicles)))
    if project_id:
        vehicle_q = vehicle_q.filter(Vehicle.project_id == project_id)
    if district_id:
        vehicle_q = vehicle_q.filter(Vehicle.district_id == district_id)
    vehicle_choices = [(0, '-- All Vehicles --')] + [(v.id, v.vehicle_no) for v in vehicle_q.all()]

    unique_vehicle_count = len({r['vehicle'].id for r in rows if r.get('vehicle')})

    return render_template(
        'task_turnaround_report.html',
        rows=rows,
        total=len(rows),
        unique_vehicle_count=unique_vehicle_count,
        from_date=from_date, to_date=to_date, project_id=project_id, district_id=district_id, vehicle_id=vehicle_id,
        check_type=check_type, duration_limit=duration_limit_raw,
        project_choices=project_choices, district_choices=district_choices, vehicle_choices=vehicle_choices,
        **_nav_back_ctx(url_for('reports_index'), show_without_nav_from=True),
    )



@app.route('/task-turnaround-report/export')
def task_turnaround_report_export():
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)

    from_date = parse_date(request.args.get('from_date')) or pk_date()
    to_date = parse_date(request.args.get('to_date')) or pk_date()
    if from_date and to_date and from_date > to_date:
        from_date, to_date = to_date, from_date
    project_id = request.args.get('project_id', type=int) or 0
    district_id = request.args.get('district_id', type=int) or 0
    vehicle_id = request.args.get('vehicle_id', type=int) or 0
    check_type = (request.args.get('check_type') or '').strip().lower()
    if check_type not in ('', 'above', 'below'):
        check_type = ''
    duration_limit_raw = (request.args.get('duration_limit') or '').strip()
    time_limit = _parse_duration_limit_hhmm(duration_limit_raw)
    apply_limit = time_limit if (check_type in ('above', 'below') and time_limit is not None) else None

    rows = _task_turnaround_rows(
        from_date=from_date, to_date=to_date, project_id=project_id, district_id=district_id, vehicle_id=vehicle_id,
        check_type=check_type, time_limit=apply_limit,
        allowed_projects=allowed_projects, allowed_districts=allowed_districts, allowed_vehicles=allowed_vehicles,
        is_master_or_admin=is_master_or_admin,
    )
    rows = _filter_task_turnaround_rows(rows, request.args.get('table_search'))
    headers = [
        'Sr', 'Date', 'District', 'Project', 'Vehicle', 'Task ID', 'Category',
        'Task Create (Assign)', 'Task Close', 'Time taken (HH:MM)',
    ]
    data_rows = []
    for i, r in enumerate(rows, 1):
        emg = r['emg']
        data_rows.append([
            i,
            emg.task_date.strftime('%d-%m-%Y') if emg.task_date else '-',
            r['district'].name if r.get('district') else '-',
            r['project'].name if r.get('project') else '-',
            r['vehicle'].vehicle_no if r.get('vehicle') else '-',
            r['task_id'],
            r['category'],
            r['assign_dt'].strftime('%d-%m-%Y %I:%M %p') if r.get('assign_dt') else '-',
            r['close_dt'].strftime('%d-%m-%Y %I:%M %p') if r.get('close_dt') else '-',
            r.get('duration_display') or '-',
        ])
    return generate_excel_template(
        headers, data_rows, required_columns=[],
        filename=f'task_turnaround_report_{pk_now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    )



@app.route('/task-turnaround-report/preview')
def task_turnaround_report_preview():
    return render_template('task_turnaround_report_print.html', **_task_turnaround_report_preview_context())



@app.route('/task-turnaround-report/print')
def task_turnaround_report_print():
    return render_template('task_turnaround_report_print.html', **_task_turnaround_report_preview_context())



@app.route('/tracker-difference-report')
def tracker_difference_report():
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)

    from_date = parse_date(request.args.get('from_date')) or pk_date()
    to_date = parse_date(request.args.get('to_date')) or pk_date()
    if from_date and to_date and from_date > to_date:
        from_date, to_date = to_date, from_date

    project_id = request.args.get('project_id', type=int) or 0
    district_id = request.args.get('district_id', type=int) or 0
    vehicle_id = request.args.get('vehicle_id', type=int) or 0
    check_type = (request.args.get('check_type') or '').strip().lower()
    if check_type not in ('', 'above', 'below'):
        check_type = ''

    diff_pct_limit_raw = (request.args.get('diff_pct_limit') or '').strip()
    diff_pct_limit = None
    if diff_pct_limit_raw:
        try:
            diff_pct_limit = float(diff_pct_limit_raw)
            if diff_pct_limit < 0:
                diff_pct_limit = None
                diff_pct_limit_raw = ''
        except Exception:
            diff_pct_limit = None
            diff_pct_limit_raw = ''

    rows = _tracker_difference_rows(
        from_date=from_date, to_date=to_date, project_id=project_id, district_id=district_id,
        vehicle_id=vehicle_id, check_type=check_type, diff_pct_limit=diff_pct_limit,
        allowed_projects=allowed_projects, allowed_districts=allowed_districts, allowed_vehicles=allowed_vehicles,
        is_master_or_admin=is_master_or_admin,
    )

    project_q = Project.query.order_by(Project.name)
    if not is_master_or_admin and allowed_projects:
        project_q = project_q.filter(Project.id.in_(list(allowed_projects)))
    project_choices = [(0, '-- All Projects --')] + [(p.id, p.name) for p in project_q.all()]

    district_q = District.query.order_by(District.name)
    if not is_master_or_admin and allowed_districts:
        district_q = district_q.filter(District.id.in_(list(allowed_districts)))
    if project_id:
        district_q = district_q.join(project_district).filter(project_district.c.project_id == project_id)
    district_choices = [(0, '-- All Districts --')] + [(d.id, d.name) for d in district_q.all()]

    vehicle_q = Vehicle.query.order_by(*vehicle_order_by())
    if not is_master_or_admin and allowed_vehicles:
        vehicle_q = vehicle_q.filter(Vehicle.id.in_(list(allowed_vehicles)))
    if project_id:
        vehicle_q = vehicle_q.filter(Vehicle.project_id == project_id)
    if district_id:
        vehicle_q = vehicle_q.filter(Vehicle.district_id == district_id)
    vehicle_choices = [(0, '-- All Vehicles --')] + [(v.id, v.vehicle_no) for v in vehicle_q.all()]

    unique_vehicle_count = len({r['vehicle'].id for r in rows if r.get('vehicle')})

    return render_template(
        'tracker_difference_report.html',
        rows=rows,
        total=len(rows),
        unique_vehicle_count=unique_vehicle_count,
        from_date=from_date,
        to_date=to_date,
        project_id=project_id,
        district_id=district_id,
        vehicle_id=vehicle_id,
        check_type=check_type,
        diff_pct_limit=diff_pct_limit_raw,
        project_choices=project_choices,
        district_choices=district_choices,
        vehicle_choices=vehicle_choices,
        **_nav_back_ctx(url_for('reports_index'), show_without_nav_from=True),
    )



@app.route('/tracker-difference-report/export')
def tracker_difference_report_export():
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)

    from_date = parse_date(request.args.get('from_date')) or pk_date()
    to_date = parse_date(request.args.get('to_date')) or pk_date()
    if from_date and to_date and from_date > to_date:
        from_date, to_date = to_date, from_date
    project_id = request.args.get('project_id', type=int) or 0
    district_id = request.args.get('district_id', type=int) or 0
    vehicle_id = request.args.get('vehicle_id', type=int) or 0
    check_type = (request.args.get('check_type') or '').strip().lower()
    if check_type not in ('', 'above', 'below'):
        check_type = ''

    diff_pct_limit_raw = (request.args.get('diff_pct_limit') or '').strip()
    diff_pct_limit = None
    if diff_pct_limit_raw:
        try:
            diff_pct_limit = float(diff_pct_limit_raw)
            if diff_pct_limit < 0:
                diff_pct_limit = None
        except Exception:
            diff_pct_limit = None

    rows = _tracker_difference_rows(
        from_date=from_date, to_date=to_date, project_id=project_id, district_id=district_id,
        vehicle_id=vehicle_id, check_type=check_type, diff_pct_limit=diff_pct_limit,
        allowed_projects=allowed_projects, allowed_districts=allowed_districts, allowed_vehicles=allowed_vehicles,
        is_master_or_admin=is_master_or_admin,
    )
    table_search = (request.args.get('table_search') or '').strip().lower()
    if table_search:
        def _m(r):
            blob = ' '.join([
                r['rec'].task_date.strftime('%d-%m-%Y') if r['rec'].task_date else '',
                r['district'].name if r.get('district') else '',
                r['project'].name if r.get('project') else '',
                r['vehicle'].vehicle_no if r.get('vehicle') else '',
                format_reading(r['start_reading']),
                format_reading(r['close_reading']),
                f"{r['total_km']:.2f}",
                f"{r['tracker_mileage']:.2f}",
                f"{r['diff_km']:.2f}",
                f"{r['diff_pct']:.2f}%" if r['diff_pct'] is not None else '',
                r.get('check_result') or '',
            ]).lower()
            return table_search in blob
        rows = [r for r in rows if _m(r)]

    headers = ['Sr', 'Date', 'District', 'Project', 'Vehicle', 'Start Reading', 'Close Reading', 'Total KMs', 'Tracker Mileage', "Diff Km's", '% Diff', 'Check Result']
    data_rows = []
    for i, r in enumerate(rows, 1):
        data_rows.append([
            i,
            r['rec'].task_date.strftime('%d-%m-%Y') if r['rec'].task_date else '-',
            r['district'].name if r['district'] else '-',
            r['project'].name if r['project'] else '-',
            r['vehicle'].vehicle_no if r['vehicle'] else '-',
            format_reading(r['start_reading']),
            format_reading(r['close_reading']),
            r['total_km'],
            r['tracker_mileage'],
            r['diff_km'],
            r['diff_pct'] if r['diff_pct'] is not None else '',
            r['check_result'] or '-',
        ])
    return generate_excel_template(
        headers, data_rows, required_columns=[],
        filename=f'tracker_difference_report_{pk_now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    )



@app.route('/tracker-difference-report/preview')
def tracker_difference_report_preview():
    return render_template('tracker_difference_report_print.html', **_tracker_difference_report_preview_context())



@app.route('/tracker-difference-report/print')
def tracker_difference_report_print():
    return render_template('tracker_difference_report_print.html', **_tracker_difference_report_preview_context())



@app.route('/driver-seat-available-report')
def driver_seat_available_report():
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects  = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles  = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)

    project_id  = request.args.get('project_id', type=int) or 0
    district_id = request.args.get('district_id', type=int) or 0
    vehicle_type = (request.args.get('vehicle_type') or '').strip()

    results = _seat_available_data(
        project_id=project_id, district_id=district_id, vehicle_type=vehicle_type,
        allowed_vehicles=allowed_vehicles, allowed_projects=allowed_projects,
        allowed_districts=allowed_districts, is_master_or_admin=is_master_or_admin,
    )

    disable_project  = False
    disable_district = False
    if not is_master_or_admin:
        if len(allowed_projects) == 1:
            if not project_id:
                project_id = next(iter(allowed_projects))
            disable_project = True
        if len(allowed_districts) == 1:
            if not district_id:
                district_id = next(iter(allowed_districts))
            disable_district = True

    proj_q = Project.query.order_by(Project.name)
    if not is_master_or_admin and allowed_projects:
        proj_q = proj_q.filter(Project.id.in_(list(allowed_projects)))
    project_choices = [(0, '-- All Projects --')] + [(p.id, p.name) for p in proj_q.all()]

    dist_q = District.query.order_by(District.name)
    if not is_master_or_admin and allowed_districts:
        dist_q = dist_q.filter(District.id.in_(list(allowed_districts)))
    if project_id:
        dist_q = dist_q.join(project_district).filter(project_district.c.project_id == project_id)
    district_choices = [(0, '-- All Districts --')] + [(d.id, d.name) for d in dist_q.all()]

    veh_types = db.session.query(Vehicle.vehicle_type).filter(
        Vehicle.vehicle_type.isnot(None), Vehicle.vehicle_type != ''
    ).distinct().order_by(Vehicle.vehicle_type).all()
    vehicle_type_choices = [('', '-- All Types --')] + [(vt[0], vt[0]) for vt in veh_types]

    total_vacant = sum(r[5] for r in results)

    return render_template(
        'driver_seat_available.html',
        results=results,
        project_id=project_id, district_id=district_id,
        vehicle_type=vehicle_type,
        project_choices=project_choices,
        district_choices=district_choices,
        vehicle_type_choices=vehicle_type_choices,
        total=len(results), total_vacant=total_vacant,
        disable_project=disable_project,
        disable_district=disable_district,
    )



@app.route('/driver-seat-available-report/export')
def driver_seat_available_export():
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects  = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles  = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)

    project_id  = request.args.get('project_id', type=int) or 0
    district_id = request.args.get('district_id', type=int) or 0
    vehicle_type = (request.args.get('vehicle_type') or '').strip()

    results = _seat_available_data(
        project_id=project_id, district_id=district_id, vehicle_type=vehicle_type,
        allowed_vehicles=allowed_vehicles, allowed_projects=allowed_projects,
        allowed_districts=allowed_districts, is_master_or_admin=is_master_or_admin,
    )

    headers = ['Sr No', 'Project', 'District', 'Vehicle No', 'Model', 'Type', 'Capacity', 'Assigned', 'Vacant Seats']
    rows = []
    for i, (vehicle, project, district, cap, asgn, vacant) in enumerate(results, 1):
        rows.append([
            i,
            project.name if project else '-',
            district.name if district else '-',
            vehicle.vehicle_no,
            vehicle.model or '-',
            vehicle.vehicle_type or '-',
            cap, asgn, vacant,
        ])
    return generate_excel_template(
        headers, rows, required_columns=[],
        filename=f'driver_seat_available_{pk_now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    )



@app.route('/driver-seat-available-report/print')
def driver_seat_available_print():
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects  = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles  = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)

    project_id  = request.args.get('project_id', type=int) or 0
    district_id = request.args.get('district_id', type=int) or 0
    vehicle_type = (request.args.get('vehicle_type') or '').strip()

    results = _seat_available_data(
        project_id=project_id, district_id=district_id, vehicle_type=vehicle_type,
        allowed_vehicles=allowed_vehicles, allowed_projects=allowed_projects,
        allowed_districts=allowed_districts, is_master_or_admin=is_master_or_admin,
    )

    total_vacant = sum(r[5] for r in results)

    return render_template(
        'driver_seat_available_print.html',
        results=results, total=len(results), total_vacant=total_vacant,
        now=datetime.now,
    )



@app.route('/missing-documents-report')
def missing_documents_report():
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    is_master_or_admin = user_context.get('is_master_or_admin', False)
    allowed_projects   = user_context.get('allowed_projects', set())
    allowed_districts  = user_context.get('allowed_districts', set())
    allowed_vehicles   = user_context.get('allowed_vehicles', set())
    allowed_shifts     = user_context.get('allowed_shifts', set())

    project_id  = request.args.get('project_id', type=int) or 0
    district_id = request.args.get('district_id', type=int) or 0

    DOC_FIELDS = [
        ('photo',         'photo_path',         'Driver Photo'),
        ('cnic_front',    'cnic_front_path',     'CNIC Front'),
        ('cnic_back',     'cnic_back_path',       'CNIC Back'),
        ('license_front', 'license_front_path',   'License Front'),
        ('license_back',  'license_back_path',    'License Back'),
        ('verify_license','verify_license_photo_path', 'Verify License'),
        ('driver_file',   'document_path',        'Complete Driver File'),
    ]
    all_doc_keys = [k for k, _, _ in DOC_FIELDS]

    doc_filters = request.args.getlist('doc_filter')
    is_first_load = 'doc_filter' not in request.args and 'project_id' not in request.args
    if is_first_load:
        doc_filters = list(all_doc_keys)

    query = Driver.query.filter(Driver.status != 'Left')

    if not is_master_or_admin:
        if allowed_vehicles:
            query = query.filter(Driver.vehicle_id.in_(list(allowed_vehicles)))
        elif allowed_projects or allowed_districts:
            if allowed_projects:
                query = query.filter(Driver.project_id.in_(list(allowed_projects)))
            if allowed_districts:
                query = query.filter(Driver.district_id.in_(list(allowed_districts)))
        if allowed_shifts:
            query = query.filter(Driver.shift.in_(list(allowed_shifts)))

    if project_id:
        query = query.filter(Driver.project_id == project_id)
    if district_id:
        query = query.filter(Driver.district_id == district_id)

    if doc_filters:
        field_map = {k: v for k, v, _ in DOC_FIELDS}
        conditions = []
        for df in doc_filters:
            col_name = field_map.get(df)
            if col_name:
                col = getattr(Driver, col_name)
                conditions.append(or_(col.is_(None), col == ''))
        if conditions:
            query = query.filter(db.or_(*conditions))

    all_drivers = query.options(
        db.joinedload(Driver.vehicle),
        db.joinedload(Driver.district),
    ).order_by(Driver.name).all()

    proj_q = Project.query.order_by(Project.name)
    if not is_master_or_admin and allowed_projects:
        proj_q = proj_q.filter(Project.id.in_(list(allowed_projects)))
    all_projects = proj_q.all()
    project_map = {p.id: p.name for p in all_projects}

    auto_project_id = 0
    auto_district_id = 0
    if not is_master_or_admin:
        if len(all_projects) == 1:
            auto_project_id = all_projects[0].id
    if is_first_load and auto_project_id and not project_id:
        project_id = auto_project_id

    project_choices = [(0, '-- All Projects --')] + [(p.id, p.name) for p in all_projects]

    dist_q = District.query.order_by(District.name)
    if not is_master_or_admin and allowed_districts:
        dist_q = dist_q.filter(District.id.in_(list(allowed_districts)))
    all_districts_list = dist_q.all()

    if not is_master_or_admin:
        if len(all_districts_list) == 1:
            auto_district_id = all_districts_list[0].id
    if is_first_load and auto_district_id and not district_id:
        district_id = auto_district_id

    district_choices = [(0, '-- All Districts --')] + [(d2.id, d2.name) for d2 in all_districts_list]

    selected_attrs = set()
    if doc_filters:
        field_map = {k: v for k, v, _ in DOC_FIELDS}
        for df in doc_filters:
            a = field_map.get(df)
            if a:
                selected_attrs.add(a)

    rows = []
    for d in all_drivers:
        missing = []
        for key, attr, label in DOC_FIELDS:
            val = getattr(d, attr, None)
            if not val:
                missing.append(label)
        if not missing:
            continue
        if selected_attrs:
            has_selected_missing = False
            for key, attr, label in DOC_FIELDS:
                if attr in selected_attrs and not getattr(d, attr, None):
                    has_selected_missing = True
                    break
            if not has_selected_missing:
                continue
        rows.append({
            'driver':       d,
            'missing':      missing,
            'project_name': project_map.get(d.project_id, '-') if d.project_id else '-',
            'district_name': d.district.name if d.district else '-',
            'vehicle_no':   d.vehicle.vehicle_no if d.vehicle else '-',
        })

    return render_template(
        'missing_docs_report.html',
        rows=rows, total=len(rows),
        project_id=project_id, district_id=district_id,
        doc_filters=doc_filters,
        project_choices=project_choices,
        district_choices=district_choices,
        doc_fields=DOC_FIELDS,
        auto_project_id=auto_project_id,
        auto_district_id=auto_district_id,
        is_master_or_admin=is_master_or_admin,
    )



@app.route('/missing-documents-report/print')
def missing_documents_report_print():
    from auth_utils import get_user_context
    from datetime import datetime as _dt
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    is_master_or_admin = user_context.get('is_master_or_admin', False)
    allowed_projects   = user_context.get('allowed_projects', set())
    allowed_districts  = user_context.get('allowed_districts', set())
    allowed_vehicles   = user_context.get('allowed_vehicles', set())
    allowed_shifts     = user_context.get('allowed_shifts', set())

    project_id  = request.args.get('project_id', type=int) or 0
    district_id = request.args.get('district_id', type=int) or 0

    DOC_FIELDS = [
        ('photo',         'photo_path',         'Driver Photo'),
        ('cnic_front',    'cnic_front_path',     'CNIC Front'),
        ('cnic_back',     'cnic_back_path',       'CNIC Back'),
        ('license_front', 'license_front_path',   'License Front'),
        ('license_back',  'license_back_path',    'License Back'),
        ('verify_license','verify_license_photo_path', 'Verify License'),
        ('driver_file',   'document_path',        'Complete Driver File'),
    ]
    all_doc_keys = [k for k, _, _ in DOC_FIELDS]

    doc_filters = request.args.getlist('doc_filter')
    if not doc_filters:
        doc_filters = list(all_doc_keys)

    query = Driver.query.filter(Driver.status != 'Left')

    if not is_master_or_admin:
        if allowed_vehicles:
            query = query.filter(Driver.vehicle_id.in_(list(allowed_vehicles)))
        elif allowed_projects or allowed_districts:
            if allowed_projects:
                query = query.filter(Driver.project_id.in_(list(allowed_projects)))
            if allowed_districts:
                query = query.filter(Driver.district_id.in_(list(allowed_districts)))
        if allowed_shifts:
            query = query.filter(Driver.shift.in_(list(allowed_shifts)))

    if project_id:
        query = query.filter(Driver.project_id == project_id)
    if district_id:
        query = query.filter(Driver.district_id == district_id)

    if doc_filters:
        field_map = {k: v for k, v, _ in DOC_FIELDS}
        conditions = []
        for df in doc_filters:
            col_name = field_map.get(df)
            if col_name:
                col = getattr(Driver, col_name)
                conditions.append(or_(col.is_(None), col == ''))
        if conditions:
            query = query.filter(db.or_(*conditions))

    all_drivers = query.options(
        db.joinedload(Driver.vehicle),
        db.joinedload(Driver.district),
    ).order_by(Driver.name).all()

    project_map = {p.id: p.name for p in Project.query.all()}

    selected_attrs = set()
    if doc_filters:
        fm = {k: v for k, v, _ in DOC_FIELDS}
        for df in doc_filters:
            a = fm.get(df)
            if a:
                selected_attrs.add(a)

    rows = []
    for d in all_drivers:
        missing = []
        for key, attr, label in DOC_FIELDS:
            val = getattr(d, attr, None)
            if not val:
                missing.append(label)
        if not missing:
            continue
        if selected_attrs:
            has_selected_missing = False
            for key, attr, label in DOC_FIELDS:
                if attr in selected_attrs and not getattr(d, attr, None):
                    has_selected_missing = True
                    break
            if not has_selected_missing:
                continue
        rows.append({
            'driver':        d,
            'missing':       missing,
            'project_name':  project_map.get(d.project_id, '-') if d.project_id else '-',
            'district_name': d.district.name if d.district else '-',
            'vehicle_no':    d.vehicle.vehicle_no if d.vehicle else '-',
        })

    project_label = None
    district_label = None
    if project_id:
        project_label = project_map.get(project_id)
    if district_id:
        dist = db.session.get(District, district_id)
        district_label = dist.name if dist else None

    lbl_map = {k: lbl for k, _, lbl in DOC_FIELDS}
    doc_filter_labels = [lbl_map[df] for df in doc_filters if df in lbl_map]

    return render_template(
        'missing_docs_report_print.html',
        rows=rows, total=len(rows),
        project_id=project_id, district_id=district_id,
        doc_filters=doc_filters,
        doc_fields=DOC_FIELDS,
        project_label=project_label,
        district_label=district_label,
        doc_filter_labels=doc_filter_labels,
        now=_dt.now().strftime('%d %b %Y, %I:%M %p'),
    )


