"""
Master Data: Companies, Projects, Vehicles, Drivers, Parking, Districts,
Driver Posts, Parties, Products, Backup, Whats New, Fuel Market Rates, Filter APIs.

Extracted from routes.py to reduce file size.
"""

from flask import (
    render_template, redirect, url_for, flash, request,
    session, jsonify, make_response, abort, send_file,
    Response, current_app, after_this_request,
)
from flask_wtf.csrf import CSRFError
from werkzeug.exceptions import HTTPException
from app import app, db, csrf
from models import (
    User, Role, Permission, Company, Project, District, Vehicle, Driver,
    ParkingStation, EmployeePost, Party, Product,
    SystemSetting, DriverAttendance, VehicleDailyTask,
    FuelExpense, DriverTransfer, DriverStatusChange,
    Employee, EmployeeAssignment, ProjectTransfer, VehicleTransfer,
    ActivityLog,
)
from forms import (
    CompanyForm, ProjectForm, VehicleForm, DriverForm, ParkingForm,
    DistrictForm, EmployeePostForm, PartyForm, ProductForm,
    VehicleImportForm, DriverImportForm, ParkingImportForm,
)
from datetime import datetime, date, timedelta
from sqlalchemy import func, text, or_, and_
from werkzeug.utils import secure_filename
from auth_utils import user_can_access, check_password
from utils import (
    pk_now, pk_date, parse_date, format_date_ddmmyyyy,
    generate_csv_response,
)
from vehicle_sort_utils import vehicle_order_by, sort_vehicles_in_memory
from r2_storage import upload_image_bytes, delete_file_by_url, upload_image_file
from backup_utils import create_backup_zip, send_backup_email
from freeze_utils import is_freeze_protected_request, extract_effective_date, evaluate_freeze
import re
import os
import json
import uuid
import tempfile
import zipfile
import csv
import io
from io import BytesIO, StringIO
from werkzeug.datastructures import FileStorage

# Import shared helpers from routes.py
from routes import (
    _multi_word_filter,
    media_url_filter,
    _get_vehicle_family_options,
    _get_maintenance_job_categories,
    _scan_fuel_market_rates,
    _read_fuel_market_scan,
    _FUEL_MARKET_SCAN_KEY,
    _VEHICLE_FAMILY_SETTING_KEY,
    _driver_update_field_data,
    _format_driver_update_whatsapp_body,
    _build_driver_update_whatsapp_parts,
    _build_driver_update_whatsapp_header,
    _build_driver_update_whatsapp_text,
    _fuel_expense_location_cascade_dict,
    _vehicle_query_task_report_scope,
    _norm_district_name_key,
    _normalize_vehicle_no,
    _log_employee_assignment,
    _sync_user_active_by_cnic,
    _sync_user_full_name_by_cnic,
    _create_user_for_employee_or_driver,
    _get_user_scope,
    require_login,
    _nav_back_ctx,
    _master_nav_back,
    _cnic_digits,
    _persist_client_diagnostic,
    _safe_internal_path,
    enforce_data_freeze,
    _expense_attachment_max_bytes,
    _save_expense_attachment_path,
    _expense_attachment_r2_ready,
    _maintenance_attachment_read_bytes,
    _maintenance_attachment_local_full_path,
    _last_backup_ts,
    _preserve_nav_from,
    _save_maintenance_job_categories,
    _save_vehicle_family_options,
    _workspace_employee_id_for_expenses,
)

import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload
from forms import ProductImportForm
from utils import format_cnic, format_phone, generate_excel_template
from models import project_district
@app.route('/api/fuel-market-rates')
def api_fuel_market_rates():
    data = _scan_fuel_market_rates(force=False)
    return jsonify(data or {})



@app.route('/api/fuel-market-rate-for-date')
def api_fuel_market_rate_for_date():
    """Return PSO rate for a specific date.

    Scan policy:
    - Today: live scan allowed (if DB record missing).
    - Non-today dates: DB-only (no live scan).
    """
    date_input = (request.args.get('date') or '').strip()
    parsed_date = parse_date(date_input)
    date_str = parsed_date.strftime('%Y-%m-%d') if parsed_date else date_input
    scan_data = _read_fuel_market_scan()
    rates = scan_data.get('rates') or {}

    today_s = pk_date().strftime('%Y-%m-%d')
    if date_str == today_s:
        scan_data = _scan_fuel_market_rates(force=False)
        rates = scan_data.get('rates') or {}

    if date_str in rates and rates[date_str].get('ok'):
        entry = rates[date_str]
        return jsonify({
            'ok': True,
            'petrol': entry.get('petrol'),
            'diesel': entry.get('diesel'),
            'scan_date': date_str,
            'scanned_at': entry.get('scanned_at', ''),
        })

    return jsonify({
        'ok': False,
        'petrol': None,
        'diesel': None,
        'scan_date': date_str,
        'scanned_at': '',
        'no_record_date': date_input or date_str,
    })



@app.route('/api/check-cnic')
def api_check_cnic():
    """Returns { exists: bool, message: str }. Call with ?cnic=xxx&exclude_driver_id=1 (optional, for edit)."""
    cnic = request.args.get('cnic', '').strip()
    digits = _cnic_digits(cnic)
    if not cnic or len(digits) != 13:
        return jsonify({'exists': False, 'message': ''})
    exclude = request.args.get('exclude_driver_id', type=int)
    query = db.session.query(Driver.id, Driver.name, Driver.driver_id, Driver.cnic_no).filter(
        Driver.cnic_no.isnot(None), Driver.cnic_no != '')
    if exclude:
        query = query.filter(Driver.id != exclude)
    for row in query.yield_per(200):
        if _cnic_digits(row.cnic_no) == digits:
            return jsonify({'exists': True, 'message': f'CNIC already registered for driver: {row.name} ({row.driver_id})'})
    return jsonify({'exists': False, 'message': ''})



@app.route('/api/check-license')
def api_check_license():
    """Returns { exists: bool, message: str }. Call with ?license=xxx&exclude_driver_id=1 (optional)."""
    license_no = request.args.get('license', '').strip()
    if not license_no:
        return jsonify({'exists': False, 'message': ''})
    exclude = request.args.get('exclude_driver_id', type=int)
    q = Driver.query.filter(Driver.license_no.ilike(license_no))
    if exclude:
        q = q.filter(Driver.id != exclude)
    other = q.first()
    if other:
        return jsonify({'exists': True, 'message': f'License number already registered for driver: {other.name} ({other.driver_id})'})
    return jsonify({'exists': False, 'message': ''})



@app.route('/api/filter/projects-by-district')
def api_filter_projects_by_district():
    """Projects that are assigned to the given district (project_district M2M), scoped to allowed_projects."""
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)
    district_id = request.args.get('district_id', type=int) or 0
    if not district_id:
        return jsonify([])
    q = (
        Project.query.join(project_district, Project.id == project_district.c.project_id)
        .filter(project_district.c.district_id == district_id)
    )
    if not is_master_or_admin and allowed_projects:
        q = q.filter(Project.id.in_(list(allowed_projects)))
    projects = q.order_by(Project.name).all()
    return jsonify([{'id': p.id, 'name': p.name} for p in projects])



@app.route('/api/filter/districts-by-project')
def api_filter_districts_by_project():
    """Return districts assigned to a project, scoped to user's allowed_districts."""
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_districts = user_context.get('allowed_districts', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)
    project_id = request.args.get('project_id', type=int) or 0
    if not project_id:
        return jsonify([])
    q = District.query.join(project_district).filter(project_district.c.project_id == project_id)
    if not is_master_or_admin and allowed_districts:
        q = q.filter(District.id.in_(list(allowed_districts)))
    districts = q.order_by(District.name).all()
    return jsonify([{'id': d.id, 'name': d.name} for d in districts])



@app.route('/api/filter/vehicles-by-project-district')
def api_filter_vehicles_by_project_district():
    """Return active-driver vehicles for project+district, scoped to user's allowed_vehicles."""
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)
    project_id = request.args.get('project_id', type=int) or 0
    district_id = request.args.get('district_id', type=int) or 0
    q = db.session.query(Vehicle).join(Driver, Vehicle.id == Driver.vehicle_id).filter(
        Driver.vehicle_id.isnot(None), Driver.status != 'Left'
    ).distinct()
    if project_id:
        q = q.filter(or_(Vehicle.project_id == project_id, Driver.project_id == project_id))
    if district_id:
        q = q.filter(Vehicle.district_id == district_id)
    if not is_master_or_admin and allowed_vehicles:
        q = q.filter(Vehicle.id.in_(list(allowed_vehicles)))
    vehicles = q.order_by(*vehicle_order_by()).all()
    return jsonify([{'id': v.id, 'vehicle_no': v.vehicle_no} for v in vehicles])



@app.route('/api/filter/all-vehicles-by-project-district')
def api_filter_all_vehicles_by_project_district():
    """Return ALL project-assigned vehicles for project+district (not filtered by driver status), scoped to user's allowed_vehicles."""
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    allowed_projects = user_context.get('allowed_projects', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)
    project_id = request.args.get('project_id', type=int) or 0
    district_id = request.args.get('district_id', type=int) or 0
    q = Vehicle.query.filter(Vehicle.project_id.isnot(None))
    if project_id:
        q = q.filter(Vehicle.project_id == project_id)
    elif not is_master_or_admin and allowed_projects:
        q = q.filter(Vehicle.project_id.in_(list(allowed_projects)))
    if district_id:
        q = q.filter(Vehicle.district_id == district_id)
    if not is_master_or_admin and allowed_vehicles:
        q = q.filter(Vehicle.id.in_(list(allowed_vehicles)))
    vehicles = q.order_by(*vehicle_order_by()).all()
    return jsonify([{'id': v.id, 'vehicle_no': v.vehicle_no, 'vehicle_type': v.vehicle_type or ''} for v in vehicles])



@app.route('/api/attendance/filtered-drivers')
def api_attendance_filtered_drivers():
    """Return active drivers scoped to user's allowed assignments, filtered by project/district/vehicle/shift."""
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)
    project_id = request.args.get('project_id', type=int) or 0
    district_id = request.args.get('district_id', type=int) or 0
    vehicle_id = request.args.get('vehicle_id', type=int) or 0
    shift = (request.args.get('shift') or '').strip()
    q = Driver.query.filter(Driver.status == 'Active', Driver.vehicle_id.isnot(None))
    need_veh_join = bool(district_id or (not is_master_or_admin and allowed_districts))
    if need_veh_join:
        q = q.outerjoin(Vehicle, Driver.vehicle_id == Vehicle.id)
    if not is_master_or_admin:
        if allowed_projects:
            q = q.filter(Driver.project_id.in_(list(allowed_projects)))
        if allowed_districts:
            q = q.filter(or_(Driver.district_id.in_(list(allowed_districts)), Vehicle.district_id.in_(list(allowed_districts))))
        if allowed_vehicles:
            q = q.filter(Driver.vehicle_id.in_(list(allowed_vehicles)))
    if project_id:
        q = q.filter(Driver.project_id == project_id)
    if district_id:
        q = q.filter(or_(Driver.district_id == district_id, Vehicle.district_id == district_id))
    if vehicle_id:
        q = q.filter(Driver.vehicle_id == vehicle_id)
    if shift:
        q = q.filter(Driver.shift == shift)
    drivers = q.order_by(Driver.name).all()
    return jsonify([{'id': d.id, 'name': d.name, 'driver_id': d.driver_id or '', 'shift': d.shift or ''} for d in drivers])



@app.route('/api/filter/parking-stations')
def api_filter_parking_stations():
    """Return parking stations filtered by project/district/vehicle, scoped to user's allowed_projects."""
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)
    project_id = request.args.get('project_id', type=int) or 0
    district_id = request.args.get('district_id', type=int) or 0
    vehicle_id = request.args.get('vehicle_id', type=int) or 0
    ps_vq = Vehicle.query.filter(Vehicle.parking_station_id.isnot(None))
    if not is_master_or_admin and allowed_projects:
        ps_vq = ps_vq.filter(Vehicle.project_id.in_(list(allowed_projects)))
    if project_id:
        ps_vq = ps_vq.filter(Vehicle.project_id == project_id)
    if district_id:
        ps_vq = ps_vq.filter(Vehicle.district_id == district_id)
    if vehicle_id:
        ps_vq = ps_vq.filter(Vehicle.id == vehicle_id)
    assigned_ps_ids = [row.parking_station_id for row in ps_vq.with_entities(Vehicle.parking_station_id).distinct().all()]
    if not assigned_ps_ids:
        return jsonify([])
    stations = ParkingStation.query.filter(ParkingStation.id.in_(assigned_ps_ids)).order_by(ParkingStation.name).all()
    return jsonify([{'id': ps.id, 'name': ps.name} for ps in stations])



@app.route('/companies/')
def companies():
    search = request.args.get('search', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    sort_by = request.args.get('sort_by', 'name')
    sort_order = request.args.get('sort_order', 'asc')

    query = Company.query
    if search:
        flt = _multi_word_filter(search,
            Company.name, Company.email, Company.mobile,
            Company.phone, Company.office_address,
            Company.district, Company.state)
        if flt is not None:
            query = query.filter(flt)

    order_col = Company.id.asc() if (sort_by == 'id' and sort_order == 'asc') else \
                Company.id.desc() if sort_by == 'id' else \
                Company.name.desc() if sort_order == 'desc' else Company.name.asc()
    pagination = query.order_by(order_col).paginate(page=page, per_page=per_page, error_out=False)
    return render_template('companies.html', companies=pagination.items, search=search,
                           pagination=pagination, per_page=per_page, sort_by=sort_by, sort_order=sort_order,
                           **_master_nav_back())



@app.route('/company/add', methods=['GET', 'POST'])
@app.route('/company/edit/<int:id>', methods=['GET', 'POST'])
def company_form(id=None):
    company = Company.query.get_or_404(id) if id else None
    form = CompanyForm(obj=company)
    if form.validate_on_submit():
        try:
            if not company:
                company = Company()
            form.populate_obj(company)
            if not id:
                db.session.add(company)
            db.session.commit()
            try:
                from routes_finance import _auto_create_coa_account
                _auto_create_coa_account('company', company.id, company.name)
                db.session.commit()
            except Exception:
                pass
            flash('Company saved successfully!', 'success')
            return redirect(url_for('companies'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error saving company: {str(e)}', 'danger')
    return render_template('company_form.html', form=form, title='Company', back_url=url_for('companies'),
                           **_nav_back_ctx(url_for('companies')))



@app.route('/company/delete/<int:id>', methods=['POST'])
def delete_company(id):
    company = Company.query.get_or_404(id)
    if company.projects:
        flash(f'Cannot delete "{company.name}". It has {len(company.projects)} project(s). Delete projects first.', 'danger')
        return redirect(url_for('companies'))
    try:
        db.session.delete(company)
        db.session.commit()
        flash('Company deleted successfully.', 'success')
    except Exception as e:
        flash(f'Error deleting company: {str(e)}', 'danger')
    return redirect(url_for('companies'))



@app.route('/companies/print')
def companies_print():
    search = request.args.get('search', '').strip()
    query = Company.query
    if search:
        flt = _multi_word_filter(search,
            Company.name, Company.email, Company.mobile, Company.office_address)
        if flt is not None:
            query = query.filter(flt)
    companies_list = query.order_by(Company.name).all()
    return render_template('companies_print.html', companies=companies_list, search=search)



@app.route('/companies/export')
def companies_export():
    """Export companies list to CSV."""
    import csv, io as _io
    search = request.args.get('search', '').strip()
    query = Company.query
    if search:
        flt = _multi_word_filter(search, Company.name, Company.email, Company.mobile, Company.office_address)
        if flt is not None:
            query = query.filter(flt)
    companies_list = query.order_by(Company.name).all()
    output = _io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Company Name', 'Email', 'Mobile', 'Phone', 'Office Address', 'District', 'State', 'Remarks'])
    for c in companies_list:
        writer.writerow([c.id, c.name, c.email or '', c.mobile or '', c.phone or '',
                         c.office_address or '', c.district or '', c.state or '', c.remarks or ''])
    output.seek(0)
    filename = f'companies{"_" + search if search else ""}.csv'
    return Response(output.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename={filename}'})



@app.route('/projects/')
def projects_list():
    from auth_utils import get_user_context
    
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)
    
    search = request.args.get('search', '').strip()
    from_date_str = request.args.get('from_date', '').strip()
    to_date_str = request.args.get('to_date', '').strip()
    sort_by = request.args.get('sort_by', 'name')
    sort_order = request.args.get('sort_order', 'asc')

    def _dmy(s):
        from datetime import datetime as _dt
        try: return _dt.strptime(s, '%d-%m-%Y').date() if s else None
        except ValueError: return None

    from_date = _dmy(from_date_str)
    to_date = _dmy(to_date_str)

    query = Project.query

    # Apply user data scope
    if not is_master_or_admin and allowed_projects:
        query = query.filter(Project.id.in_(list(allowed_projects)))

    if search:
        flt = _multi_word_filter(search, Project.name, Project.status, Project.remarks)
        if flt is not None:
            query = query.filter(flt)
    if from_date:
        query = query.filter(Project.start_date >= from_date)
    if to_date:
        query = query.filter(Project.start_date <= to_date)

    # Apply sorting based on sort_by column
    if sort_by == 'id':
        order_col = Project.id.asc() if sort_order == 'asc' else Project.id.desc()
    elif sort_by == 'start_date':
        order_col = Project.start_date.asc() if sort_order == 'asc' else Project.start_date.desc()
    elif sort_by == 'status':
        order_col = Project.status.asc() if sort_order == 'asc' else Project.status.desc()
    else:  # default to name
        order_col = Project.name.asc() if sort_order == 'asc' else Project.name.desc()

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    pagination = query.order_by(order_col).paginate(page=page, per_page=per_page, error_out=False)
    projects = pagination.items
    return render_template('projects_list.html', projects=projects, search=search,
                           from_date=from_date_str, to_date=to_date_str,
                           sort_by=sort_by, sort_order=sort_order, pagination=pagination, per_page=per_page,
                           **_master_nav_back())



@app.route('/projects/export')
def projects_export():
    """Export projects list (with optional search) to CSV."""
    search = request.args.get('search', '').strip()
    query = Project.query
    if search:
        flt = _multi_word_filter(search, Project.name)
        if flt is not None:
            query = query.filter(flt)
    projects = query.order_by(Project.name).all()
    headers = ['ID', 'Project Name', 'Start Date', 'Status']
    rows = []
    for p in projects:
        rows.append([
            p.id,
            p.name,
            p.start_date.strftime('%Y-%m-%d') if getattr(p, 'start_date', None) else '',
            p.status
        ])
    filename = 'projects.csv' if not search else f'projects_search_{search}.csv'
    return generate_csv_response(headers, rows, filename=filename)



@app.route('/projects/print')
def projects_print():
    """Print/Preview projects list."""
    search = request.args.get('search', '').strip()
    query = Project.query
    if search:
        flt = _multi_word_filter(search, Project.name)
        if flt is not None:
            query = query.filter(flt)
    projects = query.order_by(Project.name).all()
    return render_template('projects_print.html', projects=projects, search=search)



@app.route('/project/<int:id>')
def project_detail(id):
    project = Project.query.get_or_404(id)
    v_search = request.args.get('v_search', '')
    d_search = request.args.get('d_search', '')
    p_search = request.args.get('p_search', '')
    vehicles = project.vehicles
    if v_search:
        words = v_search.lower().split()
        vehicles = [v for v in vehicles if all(
            any(w in col for col in [v.vehicle_no.lower(), v.model.lower(), v.vehicle_type.lower()])
            for w in words
        )]
    drivers = project.drivers
    if d_search:
        words = d_search.lower().split()
        drivers = [d for d in drivers if all(
            any(w in col for col in [d.name.lower(), (d.cnic_no or '').lower(), (d.license_no or '').lower()])
            for w in words
        )]
    parkings = project.parking_stations
    if p_search:
        words = p_search.lower().split()
        parkings = [p for p in parkings if all(
            any(w in col for col in [p.name.lower(), (p.district or '').lower(), (p.address_location or '').lower()])
            for w in words
        )]
    return render_template('project_detail.html',
                           project=project,
                           vehicles=vehicles,
                           drivers=drivers,
                           parkings=parkings,
                           v_search=v_search,
                           d_search=d_search,
                           p_search=p_search)



@app.route('/company/<int:company_id>/projects/')
def company_projects(company_id):
    company = Company.query.get_or_404(company_id)
    search = request.args.get('search', '')
    query = Project.query.filter_by(company_id=company_id)
    if search:
        flt = _multi_word_filter(search, Project.name)
        if flt is not None:
            query = query.filter(flt)
    projects = query.all()
    return render_template('projects.html', company=company, projects=projects, search=search)



@app.route('/project/add', methods=['GET', 'POST'])
@app.route('/project/edit/<int:id>', methods=['GET', 'POST'])
def project_form(id=None):
    project = Project.query.get_or_404(id) if id else None
    form = ProjectForm(obj=project)
    if form.validate_on_submit():
        try:
            if not project:
                project = Project()
            form.populate_obj(project)
            if form.status.data == 'Inactive' and not form.inactive_date.data:
                flash('Inactive Date is required when status is Inactive.', 'danger')
                return render_template('project_form.html', form=form, title='Project', back_url=url_for('projects_list'),
                                       **_nav_back_ctx(url_for('projects_list')))
            if not id:
                db.session.add(project)
            db.session.commit()
            flash('Project saved successfully!', 'success')
            return redirect(url_for('projects_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error saving project: {str(e)}', 'danger')
    back_url = url_for('projects_list')
    return render_template('project_form.html', form=form, title='Project', back_url=back_url,
                           **_nav_back_ctx(url_for('projects_list')))



@app.route('/project/delete/<int:id>', methods=['POST'])
def delete_project(id):
    project = Project.query.get_or_404(id)
    linked_districts = db.session.query(project_district).filter_by(project_id=project.id).count()
    if linked_districts > 0:
        flash(f'Cannot delete "{project.name}". It is linked to {linked_districts} district(s). Remove district assignments first.', 'danger')
        return redirect(url_for('assign_project_to_company', **_preserve_nav_from()))
    try:
        db.session.delete(project)
        db.session.commit()
        flash(f'Project "{project.name}" deleted successfully.', 'success')
    except Exception as e:
        flash(f'Error deleting project: {str(e)}', 'danger')
    return redirect(url_for('projects_list'))



@app.route('/project/toggle_status/<int:id>', methods=['POST'])
def toggle_project_status(id):
    project = Project.query.get_or_404(id)
    if project.status == 'Active':
        project.status = 'Inactive'
        flash('Project marked as Inactive. Update Inactive Date from Edit if needed.', 'info')
    else:
        project.status = 'Active'
        project.inactive_date = None
        flash('Project marked as Active.', 'success')
    db.session.commit()
    return redirect(url_for('projects_list'))


@app.route('/vehicles/')
def vehicles_list():
    from auth_utils import get_user_context
    
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)
    
    search = request.args.get('search', '').strip()
    from_date_str = request.args.get('from_date', '').strip()
    to_date_str = request.args.get('to_date', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    sort_by = request.args.get('sort_by', 'vehicle_no')
    sort_order = request.args.get('sort_order', 'asc')

    def _dmy(s):
        from datetime import datetime as _dt
        try: return _dt.strptime(s, '%d-%m-%Y').date() if s else None
        except ValueError: return None

    from_date = _dmy(from_date_str)
    to_date = _dmy(to_date_str)

    query = Vehicle.query

    # Apply user data scope
    if not is_master_or_admin:
        if allowed_projects:
            query = query.filter(Vehicle.project_id.in_(list(allowed_projects)))
        if allowed_districts:
            query = query.filter(Vehicle.district_id.in_(list(allowed_districts)))

    if search:
        query = query.outerjoin(Project,  Vehicle.project_id  == Project.id) \
                     .outerjoin(District, Vehicle.district_id == District.id)
        flt = _multi_word_filter(search,
            Vehicle.vehicle_no, Vehicle.model, Vehicle.vehicle_type, Vehicle.vehicle_family, Vehicle.fuel_type,
            Vehicle.phone_no, Vehicle.engine_no, Vehicle.chassis_no,
            Project.name, District.name)
        if flt is not None:
            query = query.filter(flt)
    if from_date:
        query = query.filter(Vehicle.active_date >= from_date)
    if to_date:
        query = query.filter(Vehicle.active_date <= to_date)

    # Apply sorting based on sort_by column
    pagination = None
    if sort_by == 'id':
        order_col = Vehicle.id.asc() if sort_order == 'asc' else Vehicle.id.desc()
    elif sort_by == 'model':
        order_col = Vehicle.model.asc() if sort_order == 'asc' else Vehicle.model.desc()
    elif sort_by == 'vehicle_type':
        order_col = Vehicle.vehicle_type.asc() if sort_order == 'asc' else Vehicle.vehicle_type.desc()
    elif sort_by == 'vehicle_family':
        order_col = Vehicle.vehicle_family.asc() if sort_order == 'asc' else Vehicle.vehicle_family.desc()
    elif sort_by == 'fuel_type':
        order_col = Vehicle.fuel_type.asc() if sort_order == 'asc' else Vehicle.fuel_type.desc()
    elif sort_by == 'active_date':
        order_col = Vehicle.active_date.asc() if sort_order == 'asc' else Vehicle.active_date.desc()
    elif sort_by == 'project':
        order_col = Vehicle.project_id.asc() if sort_order == 'asc' else Vehicle.project_id.desc()
    elif sort_by == 'district':
        order_col = Vehicle.district_id.asc() if sort_order == 'asc' else Vehicle.district_id.desc()
    elif sort_by == 'vehicle_no' and sort_order == 'desc':
        order_col = Vehicle.vehicle_no.desc()
    else:
        if not search:
            query = query.outerjoin(Project, Vehicle.project_id == Project.id)
        pagination = query.order_by(*vehicle_order_by(Project.name)).paginate(
            page=page, per_page=per_page, error_out=False
        )
    if pagination is None:
        pagination = query.order_by(order_col).paginate(page=page, per_page=per_page, error_out=False)
    vehicles = pagination.items
    return render_template('vehicles_list.html', vehicles=vehicles, search=search,
                           from_date=from_date_str, to_date=to_date_str,
                           pagination=pagination, per_page=per_page, sort_by=sort_by, sort_order=sort_order,
                           **_master_nav_back())



@app.route('/whats-new')
def whats_new():
    """What's New page: only latest 15 entries (newest first)."""
    entries = [
        {
            'title': 'Roles & Permissions: hierarchical permissions, dependencies, Notifications & What\'s New',
            'label': 'Latest',
            'bullets': [
                'Add/Edit Role form: Permissions are now shown in a clear hierarchy (Section → Page → Buttons). For example, under Master Data you see Companies with List/View, Add New, Edit, Delete, Report; you select List/View first, then Add/Edit etc.',
                'Permission dependencies: If you give a role "Companies – Add New", the system automatically adds "Companies – List / View" so users can open the list before adding. Same for Edit, Delete, Report and for other modules (Projects, Drivers, Users, Roles, Notifications).',
                'Notifications & What\'s New are now assignable permissions: In Roles & Permissions you can grant "Notifications – List / View", "Notifications – Create", and "What\'s New". Only users with these permissions see the Notifications block and What\'s New link in the sidebar and navbar; others do not.',
                'Master Data sidebar order updated: Parking Stations → Designations → Employees → Drivers → Parties → Products (Companies, Projects, Districts, Vehicles remain at top).',
                'Master login: Master user gets all permissions from the database at login; role value is not used. All sidebar links and routes are available to Master regardless of role. No permission is missed.',
                'Role form shows only permissions the current user can assign: If you have only Fuel under Expense Management, you can assign only Fuel to other roles; Oil/Maintenance stay hidden and cannot be given. When editing a role, permissions you don\'t have are preserved (not removed).',
            ],
        },
        {
            'title': 'Login & access: redirect and error message fixes',
            'label': 'Previous update',
            'bullets': [
                'Redirect fix: When a user has no permission for a page, the app now redirects to the login page instead of the dashboard, so the previous redirect loop is resolved.',
                "Login page error stack fixed: The 'You do not have access to this page.' message was showing many times on the login screen. Now it is shown only once when redirected due to permission failure (using a session flag instead of flashing on every request).",
            ],
        },
        {
            'title': 'Assignment modules: validations, locks, exports & print preview',
            'label': 'Previous update',
            'bullets': [
                'Driver to Vehicle: Required field errors shown below each field. Assign date must be entered by user (no auto-select). Cancel button added. Selected vehicle\'s parking station shown below Vehicle dropdown. If vehicle has no parking station, Finalize shows message and form is not saved or reset. Unassign form now includes CSRF token (fixes Bad Request).',
                'Project to Company list: Projects that have districts linked now have Edit and Deassign locked (with lock icon). Export to Excel and Report Preview (print) buttons added. List search filter applied to export and print.',
                'New Project Assignment & District to Project: Company/Project and Project/District must be selected by user (no auto-select); placeholder options and validation. District to Project: Select Project shows only projects assigned to a company. After selecting a project, District dropdown shows only districts not already linked to that project (via AJAX).',
                'Vehicle to District: Project dropdown shows only company-assigned projects. Clear button resets Project and District to placeholder. Required field errors shown below fields.',
                'Vehicle to Parking: Project dropdown shows only company-assigned projects. Vehicle list shows only vehicles without parking assigned (and current vehicle on edit). Vehicles with a driver attached have Edit and Deassign locked on parking list; edit and deassign routes also block when driver is attached. Export to Excel and Print Preview buttons added on list.',
                'Driver to Vehicle: Project dropdown shows only company-assigned projects. Export to Excel and Print Preview buttons added on list.',
            ],
        },
        {
            'title': 'Backup, Drivers (search/print/export/post), Import (list-only + progress)',
            'label': 'Previous update',
            'bullets': [
                'Backup: Download and Send to Email only (Save to Path removed). Scheduled backup runs daily and sends backup to email only. Left menu: Backup link above What\'s New.',
                'What\'s New: Always shown at the bottom of the left menu (below Backup).',
                'Import only on list pages: Import Excel button removed from Driver, Vehicle, and Parking entry forms. Import is available only from Drivers List, Vehicles List, and Parking List.',
                'Import progress: When uploading a file for import, an overlay shows file name, upload percentage, and "Processing…" so users know the system is working and don\'t refresh.',
                'Driver delete: Deleting a driver from the list now correctly removes related records (status changes, transfers, attendance) so no database error occurs.',
                'Driver list search: Search filters only by columns shown on the list (Driver ID, Name, CNIC No, CNIC Status, License No, License Status, Phone, Driver District). You can search by "Valid" or "Expired" for status.',
                'Driver print/PDF & Export Excel: Print view and Excel export use the same columns as the list. Export now downloads a real .xlsx file.',
                'Driver form – Post: Post dropdown shows only full name (short name removed). On edit, if the driver\'s post was set by import and is not in the master list, it is kept and not changed.',
                'Driver import: CNIC Status and License Status are set automatically from expiry dates during import (Valid/Expired). License No "0" or blank is treated as invalid and the row is skipped with an error.',
                'Driver list delete: CSRF token added to the delete form so "Bad Request" no longer appears when deleting a driver.',
            ],
        },
        {
            'title': 'Excel import templates, strong validation & error tables',
            'label': 'Previous update',
            'bullets': [
                'Excel templates with highlighted required columns: Parking, Vehicles, and Drivers import templates are now real .xlsx files.',
                'Per‑row validation on import: Required fields and duplicate checks (Vehicle No, Driver ID, CNIC, License No, Parking name+district).',
                'Safe "all‑or‑nothing" import: If even one row has an issue, the entire file is rolled back.',
                'Detailed error table on screen: Row #, key column, Issue so user can fix Excel and re‑upload.',
                'Cleaner text values on import: Optional blank fields stored as N/A.',
                'Login username made case‑insensitive.',
                'Party & Product lists pagination/search.',
            ],
        },
        {
            'title': 'Login screen, employee module enhancements & clean reports',
            'label': 'Most recent updates',
            'bullets': [
                'Login screen added with default credentials admin / admin.',
                'Employee Posts (Master): short name + full name + remarks for Driver and Employee forms.',
                'Employees Management: list and entry form for non-driver staff with validation and department suggestions.',
                'Employee details: Father Name, DOB, Education, Marital Status, District, Address, CNIC, bank info.',
                'Employee CNIC & reports: CSV export and print/PDF.',
                'Driver Form – Post field driven by Employee Posts master.',
                'Parking Station Form: Capacity, Create Date, District and Tehsil mandatory.',
                'Vehicle Entry validation strengthened.',
                'Duplicate checks: user-friendly messages for duplicate Vehicle Number or Parking Station Name.',
                'Print views cleaned up: report-only layout without sidebar or navbar.',
            ],
        },
        {
            'title': 'Realtime search, notifications, AI reports, districts, parking, vehicles & drivers',
            'label': 'Previous major update',
            'bullets': [
                'Navbar notification bell with unread count.',
                'Realtime search on list pages: Drivers, Vehicles, Projects, Companies, Districts, Parking, Party, Products.',
                'AI reports: fuel expenses, maintenance expenses, penalties, attendance summary.',
                'Dashboard notification: alerts when many active drivers have no attendance in the last 7 days.',
                'What\'s New / Updates page in the sidebar.',
                'District list: Excel export and print/PDF.',
                'Company, Parking, and Driver forms use District master (typeahead).',
                'Parking Stations: Excel/CSV import with template and upload screen.',
                'Parking Station Entry Form: date picker fixed.',
                'Parking Station list: Excel export and print/PDF.',
                'Vehicles: Excel/CSV import, Excel export, print/PDF.',
                'Drivers: Excel/CSV import, Excel export, print/PDF.',
            ],
        },
        {
            'title': 'Project & Forms improvements',
            'label': '',
            'bullets': [
                'Project Entry Form date validation fixed and errors shown clearly.',
                'District form: friendly message if duplicate district name is entered.',
            ],
        },
        {
            'title': 'Lists & Exports',
            'label': '',
            'bullets': [
                'Drivers, Vehicles, and Projects lists have CSV export buttons.',
                'Export respects current search filters.',
            ],
        },
    ]
    # Only latest 15 entries (each timeline block = 1 entry)
    entries = entries[:15]
    return render_template('whats_new.html', entries=entries)



@app.route('/accounts/future-entry')
def accounts_future_entry():
    return render_template('accounts_placeholder.html', title='Future Entry', description='Future-dated entries. (Coming soon)')



@app.route('/backup')
def backup_index():
    """Backup page: download, email configuration, send to email."""
    from backup_config import get_backup_settings, mail_is_configured

    settings = get_backup_settings(app)
    mail_configured = mail_is_configured(app)
    freq_labels = {
        'daily': 'Daily',
        'weekly': 'Weekly',
        'twice_daily': 'Twice daily',
    }
    weekday_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    try:
        wd = int(settings.get('schedule_weekday') or 0)
    except (TypeError, ValueError):
        wd = 0
    wd = max(0, min(6, wd))
    return render_template(
        'backup.html',
        backup_settings=settings,
        mail_configured=mail_configured,
        schedule_enabled=settings.get('schedule_enabled'),
        schedule_time=settings.get('schedule_time'),
        backup_email_to=settings.get('email_to'),
        schedule_frequency=settings.get('schedule_frequency'),
        schedule_frequency_label=freq_labels.get(settings.get('schedule_frequency'), 'Daily'),
        schedule_weekday_name=weekday_names[wd],
        mail_missing=[],
        schedule_missing=[],
    )



@app.route('/backup/settings', methods=['POST'])
def backup_settings_save():
    """Save backup email & auto-backup schedule (SystemSetting)."""
    from backup_config import save_backup_settings

    if request.is_json:
        data = request.get_json(silent=True) or {}
    else:
        data = request.form.to_dict()
    ok, msg = save_backup_settings(app, data)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
        return jsonify({
            'ok': ok,
            'message': msg,
            'error': None if ok else msg,
        })
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('backup_index'))



@app.route('/backup/download')
def backup_download():
    """Legacy direct download URL — use Backup page button (async job + progress)."""
    flash('Use Download Backup on the Backup page to see progress and download.', 'info')
    return redirect(url_for('backup_index'))



@app.route('/backup/job/start', methods=['POST'])
def backup_job_start():
    """Create backup job; client polls /status (runs backup while queued)."""
    from backup_jobs import create_job
    from backup_config import mail_is_configured, get_backup_settings

    try:
        uid = session.get('user_id')
        if not uid:
            return jsonify({'ok': False, 'error': 'Not logged in'}), 401
        job_type = (request.form.get('type') or request.args.get('type') or 'download').strip().lower()
        if job_type == 'email':
            if not mail_is_configured(app):
                return jsonify({
                    'ok': False,
                    'error': 'Email not configured. Open settings below and save Gmail sender, App Password, and recipient.',
                }), 400
            settings = get_backup_settings(app)
            email_to = (request.form.get('email_to') or settings.get('email_to') or '').strip()
            job_id = create_job(app, uid, job_type='email', email_to=email_to)
        else:
            job_id = create_job(app, uid, job_type='download')
        return jsonify({'ok': True, 'job_id': job_id, 'job_type': job_type})
    except Exception as ex:
        app.logger.exception('backup_job_start failed: %s', ex)
        return jsonify({'ok': False, 'error': str(ex)}), 500



@app.route('/backup/job/<job_id>/execute', methods=['POST'])
def backup_job_execute(job_id):
    """Legacy: same as polling /status while queued. Kept for older clients."""
    return backup_job_status(job_id)



@app.route('/backup/job/<job_id>/status')
def backup_job_status(job_id):
    """Poll progress; queued jobs start in a background thread so HTTP stays short (avoids Render 502)."""
    from backup_jobs import read_job, has_worker_claim
    from backup_utils import start_backup_job_background

    try:
        job = read_job(app, job_id)
        if not job:
            return jsonify({'ok': False, 'error': 'Job not found'}), 404
        owner = job.get('user_id')
        if owner != session.get('user_id') and not session.get('is_master'):
            return jsonify({'ok': False, 'error': 'Forbidden'}), 403

        if job.get('status') == 'queued' and not has_worker_claim(app, job_id):
            start_backup_job_background(app, job_id)

        job = read_job(app, job_id) or job

        err_val = job.get('error')
        if err_val is None:
            err_val = ''
        else:
            err_val = str(err_val).strip()
        return jsonify({
            'ok': True,
            'status': job.get('status'),
            'step': job.get('step') or '',
            'percent': int(job.get('percent') or 0),
            'message': job.get('message') or '',
            'error': err_val if err_val else None,
            'failure_detail': err_val,
            'download_name': job.get('download_name'),
            'job_type': job.get('job_type') or 'download',
        })
    except Exception as ex:
        app.logger.exception('backup_job_status failed: %s', ex)
        return jsonify({'ok': False, 'error': str(ex)}), 500



@app.route('/backup/job/<job_id>/download')
def backup_job_download(job_id):
    from backup_jobs import read_job, delete_job

    job = read_job(app, job_id)
    if not job:
        abort(404)
    owner = job.get('user_id')
    if owner != session.get('user_id') and not session.get('is_master'):
        abort(403)
    if job.get('status') != 'done':
        flash('Backup is not ready yet.', 'warning')
        return redirect(url_for('backup_index'))
    zip_path = job.get('zip_path')
    if not zip_path or not os.path.isfile(zip_path):
        flash('Backup file missing. Please create a new backup.', 'danger')
        delete_job(app, job_id)
        return redirect(url_for('backup_index'))
    friendly = job.get('download_name') or os.path.basename(zip_path)
    _last_backup_ts['ts'] = pk_now()
    ext = os.path.splitext(friendly)[1].lower()
    mimetype = {
        '.zip': 'application/zip',
        '.gz': 'application/gzip',
        '.dump': 'application/octet-stream',
        '.sqlite': 'application/x-sqlite3',
    }.get(ext, 'application/octet-stream')

    resp = send_file(
        zip_path,
        as_attachment=True,
        download_name=friendly,
        mimetype=mimetype,
        max_age=0,
    )

    @resp.call_on_close
    def _cleanup_backup_job():
        delete_job(app, job_id)

    return resp



@app.route('/backup/email', methods=['POST'])
def backup_email():
    """Create backup and send to given email."""
    from backup_utils import create_backup_zip, send_backup_email
    to_email = (request.form.get('email') or '').strip()
    if not to_email:
        flash('Please enter an email address.', 'warning')
        return redirect(url_for('backup_index'))
    zip_path, err = create_backup_zip(app)
    if err:
        flash(f'Backup failed: {err}', 'danger')
        return redirect(url_for('backup_index'))
    try:
        ok, msg = send_backup_email(app, zip_path, to_email)
        if ok:
            flash(msg, 'success')
        else:
            flash(f'Email failed: {msg}', 'danger')
    finally:
        try:
            if zip_path and os.path.exists(zip_path):
                os.remove(zip_path)
        except Exception:
            pass
    return redirect(url_for('backup_index'))



@app.route('/backup/save', methods=['POST'])
def backup_save():
    """Create backup and save to user-selected path (local/server folder)."""
    from backup_utils import create_backup_zip
    import shutil
    path = (request.form.get('path') or '').strip()
    if not path:
        flash('Please enter a folder path.', 'warning')
        return redirect(url_for('backup_index'))
    path = os.path.abspath(path)
    app_root = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    if path == app_root or path.startswith(app_root + os.sep):
        flash('Cannot save backup inside the application folder.', 'danger')
        return redirect(url_for('backup_index'))
    if not os.path.isdir(path):
        try:
            os.makedirs(path, exist_ok=True)
        except Exception as e:
            flash(f'Could not create folder: {e}', 'danger')
            return redirect(url_for('backup_index'))
    zip_path, err = create_backup_zip(app)
    if err:
        flash(f'Backup failed: {err}', 'danger')
        return redirect(url_for('backup_index'))
    try:
        friendly = f'fleet_backup_{pk_now().strftime("%Y%m%d_%H%M%S")}.zip'
        dest = os.path.join(path, friendly)
        shutil.copy2(zip_path, dest)
        flash(f'Backup saved to: {dest}', 'success')
    finally:
        try:
            if zip_path and os.path.exists(zip_path):
                os.remove(zip_path)
        except Exception:
            pass
    return redirect(url_for('backup_index'))



@app.route('/vehicles/export')
def vehicles_export():
    """Export vehicles list (with optional search) to CSV."""
    search = request.args.get('search', '').strip()
    query = Vehicle.query
    if search:
        flt = _multi_word_filter(search, Vehicle.vehicle_no, Vehicle.model, Vehicle.vehicle_type, Vehicle.vehicle_family, Vehicle.fuel_type)
        if flt is not None:
            query = query.filter(flt)
    vehicles = query.order_by(Vehicle.id).all()
    headers = ['ID', 'Vehicle No', 'Model', 'Type', 'Family', 'Fuel Type', 'Driver Capacity', 'Phone', 'Active Date']
    rows = []
    for v in vehicles:
        rows.append([
            v.id,
            v.vehicle_no,
            v.model,
            v.vehicle_type,
            v.vehicle_family or '',
            v.fuel_type or 'Petrol',
            getattr(v, 'driver_capacity', None),
            v.phone_no,
            v.active_date.strftime('%Y-%m-%d') if getattr(v, 'active_date', None) else ''
        ])
    filename = 'vehicles.csv' if not search else f'vehicles_search_{search}.csv'
    return generate_csv_response(headers, rows, filename=filename)



@app.route('/vehicles/import', methods=['GET', 'POST'])
def vehicles_import():
    """
    Import vehicles from Excel/CSV.
    """
    form = VehicleImportForm()
    if request.method == 'POST' and form.validate_on_submit():
        f = form.file.data
        if not f:
            flash('Please select an Excel/CSV file.', 'warning')
            return redirect(url_for('vehicles_import'))
        try:
            import pandas as pd
            filename = f.filename or ''
            ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
            if ext in ('xlsx', 'xls'):
                df = pd.read_excel(f)
            elif ext == 'csv':
                df = pd.read_csv(f)
            else:
                flash('Unsupported file type. Please upload .xlsx, .xls or .csv.', 'danger')
                return redirect(url_for('vehicles_import'))

            # Required + optional columns (baqi extra columns aayein to bhi allowed hain)
            required_cols = ['vehicle_no', 'model', 'vehicle_type', 'engine_no', 'chassis_no', 'driver_capacity', 'active_date']
            expected_cols = required_cols + ['phone_no', 'remarks']
            missing = [c for c in expected_cols if c not in df.columns]
            if missing:
                flash(f'Missing required columns in file: {", ".join(missing)}', 'danger')
                return redirect(url_for('vehicles_import'))

            # NaN ko human-friendly 'N/A' bana ne ke liye helper
            def clean_text(value):
                if pd.isna(value):
                    return 'N/A'
                v = str(value or '').strip()
                return v or 'N/A'

            from utils import parse_date
            import_errors = []
            vehicles_to_add = []
            # Track values seen within this file to catch intra-file duplicates
            seen_vnos    = set()
            seen_engines = set()
            seen_chassis = set()

            # Row-wise validation + duplicate checks
            for idx, row in df.iterrows():
                row_num = idx + 2  # 1 header row + 1-based index
                row_issues = []

                vno_raw = row.get('vehicle_no')
                if pd.isna(vno_raw) or not str(vno_raw).strip():
                    row_issues.append('Field "vehicle_no" is required.')
                    vno = ''
                else:
                    vno = str(vno_raw).strip()

                # Required field checks
                for col in required_cols:
                    val = row.get(col)
                    if pd.isna(val) or not str(val).strip():
                        row_issues.append(f'Field "{col}" is required.')

                eng_raw = row.get('engine_no')
                eng_val = str(eng_raw).strip() if pd.notna(eng_raw) and str(eng_raw).strip() else ''

                chs_raw = row.get('chassis_no')
                chs_val = str(chs_raw).strip() if pd.notna(chs_raw) and str(chs_raw).strip() else ''

                # Duplicate checks — DB (already saved) AND within this file
                if vno:
                    if Vehicle.query.filter(Vehicle.vehicle_no == vno).first():
                        row_issues.append(f'Vehicle No "{vno}" already exists in system.')
                    elif vno in seen_vnos:
                        row_issues.append(f'Vehicle No "{vno}" is duplicated within this file.')
                    else:
                        seen_vnos.add(vno)

                if eng_val and eng_val.upper() != 'N/A':
                    if Vehicle.query.filter(Vehicle.engine_no == eng_val).first():
                        row_issues.append(f'Engine No "{eng_val}" already exists in system.')
                    elif eng_val in seen_engines:
                        row_issues.append(f'Engine No "{eng_val}" is duplicated within this file.')
                    else:
                        seen_engines.add(eng_val)

                if chs_val and chs_val.upper() != 'N/A':
                    if Vehicle.query.filter(Vehicle.chassis_no == chs_val).first():
                        row_issues.append(f'Chassis No "{chs_val}" already exists in system.')
                    elif chs_val in seen_chassis:
                        row_issues.append(f'Chassis No "{chs_val}" is duplicated within this file.')
                    else:
                        seen_chassis.add(chs_val)

                # driver_capacity numeric parse
                cap_val = row.get('driver_capacity')
                try:
                    driver_capacity = int(cap_val) if pd.notna(cap_val) else None
                except Exception:
                    row_issues.append('"driver_capacity" must be a number.')
                    driver_capacity = None

                # Active date parse
                active_raw = row.get('active_date')
                active_date = None
                if pd.notna(active_raw):
                    if isinstance(active_raw, str):
                        active_date = parse_date(active_raw)
                    else:
                        try:
                            import pandas as pd  # safe re-import
                            active_date = pd.to_datetime(active_raw).date()
                        except Exception:
                            active_date = None
                if not active_date:
                    row_issues.append('"active_date" is invalid or missing (expected dd-mm-yyyy).')

                if row_issues:
                    for msg in row_issues:
                        import_errors.append({
                            'row': row_num,
                            'identifier': vno,
                            'message': msg
                        })
                    continue

                v = Vehicle(
                    vehicle_no=vno,
                    model=clean_text(row.get('model')),
                    engine_no=clean_text(row.get('engine_no')),
                    chassis_no=clean_text(row.get('chassis_no')),
                    vehicle_type=clean_text(row.get('vehicle_type')),
                    fuel_type=clean_text(row.get('fuel_type')) if 'fuel_type' in df.columns and clean_text(row.get('fuel_type')) != 'N/A' else 'Petrol',
                    driver_capacity=driver_capacity,
                    phone_no=clean_text(row.get('phone_no')),
                    active_date=active_date,
                    remarks=clean_text(row.get('remarks')),
                )
                vehicles_to_add.append(v)

            # Agar kisi bhi row mein issue ho to poori file import na ho
            if import_errors:
                db.session.rollback()
                # Yahan flash sirf top message ke liye, detail neeche table mein dikhe gi
                flash('Import failed. Please review the error table on this page.', 'danger')
                return render_template('vehicles_import.html', form=form, import_errors=import_errors)

            # All good → save all rows in one go
            for v in vehicles_to_add:
                db.session.add(v)
            db.session.commit()

            flash(f'{len(vehicles_to_add)} vehicle(s) imported successfully.', 'success')
            return redirect(url_for('vehicles_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error importing vehicles: {str(e)}', 'danger')
    return render_template('vehicles_import.html', form=form)



@app.route('/vehicles/import/template')
def vehicles_import_template():
    """
    Downloadable template for vehicle import (open in Excel and fill).
    Required fields ka detail description import page par diya gaya hai.
    """
    headers = ['vehicle_no', 'model', 'vehicle_type', 'fuel_type', 'engine_no', 'chassis_no', 'driver_capacity', 'phone_no', 'active_date', 'remarks']
    rows = [
        ['LEA-1234', 'Suzuki Cultus', 'Ambulance', 'Petrol', 'ENG123', 'CHS123', 1, '0300-1112233', '01-01-2024', 'Example row 1'],
        ['LEA-5678', 'Toyota Hiace', 'Passanger', 'Diesel', 'ENG456', 'CHS456', 2, '0300-2223344', '05-02-2024', 'Example row 2'],
    ]
    required_cols = ['vehicle_no', 'model', 'vehicle_type', 'engine_no', 'chassis_no', 'driver_capacity', 'active_date']
    return generate_excel_template(headers, rows, required_columns=required_cols, filename='vehicles_import_template.xlsx')



@app.route('/vehicles/print')
def vehicles_print():
    """Print-friendly view of vehicles (browser print to PDF)."""
    search = request.args.get('search', '').strip()
    query = Vehicle.query
    if search:
        flt = _multi_word_filter(search, Vehicle.vehicle_no, Vehicle.model, Vehicle.vehicle_type, Vehicle.vehicle_family, Vehicle.fuel_type)
        if flt is not None:
            query = query.filter(flt)
    vehicles = query.order_by(Vehicle.id).all()
    return render_template('vehicles_print.html', vehicles=vehicles, search=search)



@app.route('/api/vehicle-family-options', methods=['GET'])
def vehicle_family_options_api():
    return jsonify(_get_vehicle_family_options())



@app.route('/api/vehicle-family-options/add', methods=['POST'])
def vehicle_family_option_add_api():
    name = (request.get_json(silent=True) or {}).get('name', '')
    name = (name or '').strip()
    if not name:
        return jsonify({'ok': False, 'message': 'Name is required'}), 400
    options = _get_vehicle_family_options()
    options.append(name)
    clean = _save_vehicle_family_options(options)
    return jsonify({'ok': True, 'name': name, 'options': clean})



@app.route('/api/maintenance-job-categories', methods=['GET'])
def maintenance_job_categories_api():
    return jsonify(_get_maintenance_job_categories())



@app.route('/api/maintenance-job-categories/add', methods=['POST'])
def maintenance_job_category_add_api():
    payload = request.get_json(silent=True) or {}
    name = (payload.get('name') or '').strip()
    interval_km_value = payload.get('interval_km_value')
    interval_day_value = payload.get('interval_day_value')
    if not name:
        return jsonify({'ok': False, 'message': 'Category name is required'}), 400
    km_val = None
    day_val = None
    try:
        if interval_km_value not in (None, ''):
            km_val = int(float(interval_km_value))
    except Exception:
        km_val = None
    try:
        if interval_day_value not in (None, ''):
            day_val = int(float(interval_day_value))
    except Exception:
        day_val = None
    km_ok = km_val is not None and km_val > 0
    day_ok = day_val is not None and day_val > 0
    if km_ok and day_ok:
        return jsonify({'ok': False, 'message': 'Only one interval is allowed (KM or Day).'}), 400
    if not km_ok and not day_ok:
        return jsonify({'ok': False, 'message': 'Enter interval in KM or Day.'}), 400
    interval_mode = 'interval_km' if km_ok else 'interval_day'
    interval_value = km_val if km_ok else day_val
    options = _get_maintenance_job_categories()
    for e in options:
        if (e.get('name') or '').strip().lower() == name.lower():
            return jsonify({'ok': False, 'message': 'Yeh category pehle se maujood hai. Manage se edit karein.'}), 400
    options.append({'name': name, 'interval_mode': interval_mode, 'interval_value': interval_value})
    clean = _save_maintenance_job_categories(options)
    return jsonify({
        'ok': True,
        'item': {'name': name, 'interval_mode': interval_mode, 'interval_value': interval_value},
        'options': clean
    })



@app.route('/api/maintenance-job-categories/update', methods=['POST'])
def maintenance_job_category_update_api():
    payload = request.get_json(silent=True) or {}
    old_name = (payload.get('old_name') or '').strip()
    name = (payload.get('name') or '').strip()
    interval_km_value = payload.get('interval_km_value')
    interval_day_value = payload.get('interval_day_value')
    if not old_name:
        return jsonify({'ok': False, 'message': 'old_name required'}), 400
    if not name:
        return jsonify({'ok': False, 'message': 'Category name is required'}), 400
    km_val = None
    day_val = None
    try:
        if interval_km_value not in (None, ''):
            km_val = int(float(interval_km_value))
    except Exception:
        km_val = None
    try:
        if interval_day_value not in (None, ''):
            day_val = int(float(interval_day_value))
    except Exception:
        day_val = None
    km_ok = km_val is not None and km_val > 0
    day_ok = day_val is not None and day_val > 0
    if km_ok and day_ok:
        return jsonify({'ok': False, 'message': 'Only one interval is allowed (KM or Day).'}), 400
    if not km_ok and not day_ok:
        return jsonify({'ok': False, 'message': 'Enter interval in KM or Day.'}), 400
    interval_mode = 'interval_km' if km_ok else 'interval_day'
    interval_value = km_val if km_ok else day_val
    opts = list(_get_maintenance_job_categories())
    idx = None
    for i, e in enumerate(opts):
        if (e.get('name') or '').strip().lower() == old_name.lower():
            idx = i
            break
    if idx is None:
        return jsonify({'ok': False, 'message': 'Category not found.'}), 404
    for i, e in enumerate(opts):
        if i == idx:
            continue
        if (e.get('name') or '').strip().lower() == name.lower():
            return jsonify({'ok': False, 'message': 'Dusri category yeh naam pehle se use kar rahi hai.'}), 400
    opts[idx] = {'name': name, 'interval_mode': interval_mode, 'interval_value': interval_value}
    clean = _save_maintenance_job_categories(opts)
    return jsonify({
        'ok': True,
        'item': {'name': name, 'interval_mode': interval_mode, 'interval_value': interval_value},
        'options': clean,
    })



@app.route('/api/maintenance-job-categories/delete', methods=['POST'])
def maintenance_job_category_delete_api():
    payload = request.get_json(silent=True) or {}
    name = (payload.get('name') or '').strip()
    if not name:
        return jsonify({'ok': False, 'message': 'Category name is required'}), 400
    original = _get_maintenance_job_categories()
    opts = [e for e in original if (e.get('name') or '').strip().lower() != name.lower()]
    if len(opts) == len(original):
        return jsonify({'ok': False, 'message': 'Category not found.'}), 404
    clean = _save_maintenance_job_categories(opts)
    return jsonify({'ok': True, 'options': clean})



@app.route('/vehicle/add', methods=['GET', 'POST'])
@app.route('/vehicle/edit/<int:id>', methods=['GET', 'POST'])
def vehicle_form(id=None):
    vehicle = Vehicle.query.get_or_404(id) if id else None
    form = VehicleForm(obj=vehicle)
    family_choices = [('', '-- Select Vehicle Family --')] + [(v, v) for v in _get_vehicle_family_options()]
    if vehicle and vehicle.vehicle_family:
        existing = vehicle.vehicle_family.strip()
        if existing and all(existing != val for val, _lbl in family_choices):
            family_choices.append((existing, existing))
    form.vehicle_family.choices = family_choices
    if form.validate_on_submit():
        try:
            if not vehicle:
                vehicle = Vehicle()
            # Normalize vehicle number (trim spaces)
            vehicle_no_normalized = (form.vehicle_no.data or '').strip()
            form.populate_obj(vehicle)
            vehicle.vehicle_no = vehicle_no_normalized
            vehicle.target_mpg = form.target_mpg.data if form.target_mpg.data is not None else 0
            vehicle.fuel_tank_capacity = form.fuel_tank_capacity.data if form.fuel_tank_capacity.data is not None else 0

            # Duplicate vehicle_no check (case-insensitive, ignore current record)
            existing_q = Vehicle.query.filter(
                func.lower(Vehicle.vehicle_no) == vehicle_no_normalized.lower()
            )
            if id:
                existing_q = existing_q.filter(Vehicle.id != vehicle.id)
            if existing_q.first():
                flash('This Vehicle Number is already registered', 'danger')
                target = url_for('vehicle_form', id=id) if id else url_for('vehicle_form')
                return redirect(target)

            if not id:
                db.session.add(vehicle)
            db.session.commit()
            doc_file = request.files.get('document')
            if doc_file and doc_file.filename:
                ext = (os.path.splitext(secure_filename(doc_file.filename))[1] or '.pdf').lower()
                if ext != '.pdf':
                    ext = '.pdf'
                subdir = os.path.join(app.config['UPLOAD_FOLDER'], 'vehicles', str(vehicle.id))
                os.makedirs(subdir, exist_ok=True)
                fname = secure_filename('document') + ext
                filepath = os.path.join(subdir, fname)
                doc_file.save(filepath)
                vehicle.document_path = os.path.join('vehicles', str(vehicle.id), fname).replace('\\', '/')
                db.session.commit()
            flash('Vehicle saved successfully!', 'success')
            return redirect(url_for('vehicles_list'))
        except IntegrityError:
            db.session.rollback()
            flash('This Vehicle Number is already registered', 'danger')
            target = url_for('vehicle_form', id=id) if id else url_for('vehicle_form')
            return redirect(target)
        except Exception as e:
            db.session.rollback()
            flash(f'Error saving vehicle: {str(e)}', 'danger')
    back_url = url_for('vehicles_list')
    return render_template('vehicle_form.html', form=form, vehicle=vehicle, title='Vehicle', back_url=back_url,
                           **_nav_back_ctx(url_for('vehicles_list')))



@app.route('/vehicle/delete/<int:id>', methods=['POST'])
def delete_vehicle(id):
    vehicle = Vehicle.query.get_or_404(id)
    try:
        db.session.delete(vehicle)
        db.session.commit()
        flash('Vehicle deleted.', 'success')
    except Exception as e:
        flash(f'Error deleting vehicle: {str(e)}', 'danger')
    return redirect(url_for('vehicles_list'))



@app.route('/drivers')
def drivers_list():
    from auth_utils import get_user_context

    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)

    search = request.args.get('search', '').strip()
    f_status = request.args.get('status', '').strip()

    query = (
        db.session.query(Driver, Project)
        .outerjoin(Project, Driver.project_id == Project.id)
        .outerjoin(Vehicle, Driver.vehicle_id == Vehicle.id)
        .outerjoin(District, Driver.district_id == District.id)
        .options(db.joinedload(Driver.vehicle), db.joinedload(Driver.district))
    )

    if not is_master_or_admin:
        if allowed_projects:
            query = query.filter(Driver.project_id.in_(list(allowed_projects)))
        if allowed_districts:
            query = query.filter(Driver.district_id.in_(list(allowed_districts)))
        if allowed_vehicles:
            query = query.filter(Driver.vehicle_id.in_(list(allowed_vehicles)))

    if f_status in ('Active', 'Left'):
        query = query.filter(Driver.status == f_status)

    if search:
        flt = _multi_word_filter(search,
            Driver.driver_id, Driver.name, Driver.father_name, Driver.cnic_no,
            Driver.cnic_status, Driver.license_no, Driver.license_status,
            Driver.phone1, Driver.driver_district, Driver.shift,
            Vehicle.vehicle_no, Project.name, District.name)
        if flt is not None:
            query = query.filter(flt)

    rows = query.order_by(Driver.name.asc()).all()
    drivers = []
    driver_projects = {}
    for drv, proj in rows:
        drivers.append(drv)
        driver_projects[drv.id] = proj

    today = pk_date()
    stats = {
        'total': len(drivers),
        'active': sum(1 for d in drivers if d.status == 'Active'),
        'left': sum(1 for d in drivers if d.status == 'Left'),
    }

    districts_list = sorted(set(d.driver_district for d in drivers if d.driver_district))

    return render_template('drivers_list.html', drivers=drivers, search=search, today=today,
                           stats=stats, driver_projects=driver_projects,
                           districts_list=districts_list,
                           f_status=f_status,
                           **_master_nav_back())



@app.route('/api/driver/update-text/<int:pk>')
def api_driver_update_text(pk):
    from auth_utils import get_user_context

    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)

    driver = Driver.query.options(
        joinedload(Driver.vehicle),
        joinedload(Driver.district),
    ).get_or_404(pk)

    if not is_master_or_admin:
        if allowed_projects and driver.project_id and driver.project_id not in allowed_projects:
            return jsonify({'ok': False, 'error': 'forbidden'}), 403
        if allowed_districts and driver.district_id and driver.district_id not in allowed_districts:
            return jsonify({'ok': False, 'error': 'forbidden'}), 403
        if allowed_vehicles and driver.vehicle_id and driver.vehicle_id not in allowed_vehicles:
            return jsonify({'ok': False, 'error': 'forbidden'}), 403

    parts = _build_driver_update_whatsapp_parts(driver)
    return jsonify({
        'ok': True,
        'driver_name': driver.name or '-',
        'vehicle_no': parts['vehicle_no'],
        'report_date': parts['report_date'],
        'detail_text': parts['detail_text'],
        'update_text': _build_driver_update_whatsapp_text(driver),
    })



@app.route('/drivers/export')
def drivers_export():
    """Export drivers list (with optional search) to CSV."""
    search = request.args.get('search', '').strip()
    query = Driver.query
    if search:
        flt = _multi_word_filter(search, Driver.driver_id, Driver.name, Driver.father_name, Driver.cnic_no, Driver.cnic_status, Driver.license_no, Driver.license_status, Driver.phone1, Driver.driver_district)
        if flt is not None:
            query = query.filter(flt)
    drivers = query.order_by(Driver.id.asc()).all()
    # List/Print jaisi same columns: Driver ID, Name, Father Name, CNIC No, License No, Phone, Driver District
    headers = ['Driver ID', 'Name', 'Father Name', 'CNIC No', 'License No', 'Phone', 'Driver District']
    rows = []
    for d in drivers:
        rows.append([
            d.driver_id or '',
            d.name or '',
            d.father_name or '-',
            format_cnic(d.cnic_no) if d.cnic_no else '-',
            d.license_no or '-',
            format_phone(d.phone1) if d.phone1 else '-',
            d.driver_district or '-',
        ])
    filename_xlsx = 'drivers.xlsx' if not search else f'drivers_search_{search[:25].replace("/", "-")}.xlsx'
    return generate_excel_template(headers, rows, required_columns=[], filename=filename_xlsx)



@app.route('/drivers/import', methods=['GET', 'POST'])
def drivers_import():
    """
    Import drivers from Excel/CSV (basic fields).
    """
    form = DriverImportForm()
    if request.method == 'POST' and form.validate_on_submit():
        f = form.file.data
        if not f:
            flash('Please select an Excel/CSV file.', 'warning')
            return redirect(url_for('drivers_import'))
        try:
            import pandas as pd
            filename = f.filename or ''
            ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
            if ext in ('xlsx', 'xls'):
                df = pd.read_excel(f)
            elif ext == 'csv':
                df = pd.read_csv(f)
            else:
                flash('Unsupported file type. Please upload .xlsx, .xls or .csv.', 'danger')
                return redirect(url_for('drivers_import'))

            # Required basic fields (form ke mutabiq core identity)
            required_cols = [
                'driver_id', 'name', 'phone1', 'driver_district',
                'cnic_no', 'license_no'
            ]
            expected_cols = required_cols + ['father_name', 'status']
            missing = [c for c in expected_cols if c not in df.columns]
            if missing:
                flash(f'Missing required columns in file: {", ".join(missing)}', 'danger')
                return redirect(url_for('drivers_import'))

            # NaN ko 'N/A' mein convert karne ke liye helper (sirf text fields ke liye)
            def clean_text(value):
                if pd.isna(value):
                    return 'N/A'
                v = str(value or '').strip()
                return v or 'N/A'

            # Excel se date ko safe parse karne ke liye helper
            def parse_import_date(value):
                if pd.isna(value) or value is None or str(value).strip() == '':
                    return None
                if isinstance(value, str):
                    return parse_date(value)
                try:
                    return pd.to_datetime(value).date()
                except Exception:
                    return None

            import_errors = []
            drivers_to_add = []

            for idx, row in df.iterrows():
                row_num = idx + 2
                row_issues = []

                did_raw = row.get('driver_id')
                if pd.isna(did_raw) or not str(did_raw).strip():
                    row_issues.append('Field "driver_id" is required.')
                    did = ''
                else:
                    did = str(did_raw).strip()

                # Required field checks (license_no: 0 or blank = invalid)
                for col in required_cols:
                    val = row.get(col)
                    if col == 'license_no' and val is not None and str(val).strip() == '0':
                        val = ''  # Excel 0 → treat as missing
                    if pd.isna(val) or not str(val).strip():
                        row_issues.append(f'Field "{col}" is required.')

                # Duplicate checks (driver_id, CNIC, license) – same rules as forms
                if did:
                    existing_id = Driver.query.filter(Driver.driver_id == did).first()
                    if existing_id:
                        row_issues.append(f'Driver ID "{did}" already exists in system.')

                cnic_val = row.get('cnic_no')
                cnic = str(cnic_val).strip() if not pd.isna(cnic_val) else ''
                if cnic:
                    existing_cnic = Driver.query.filter(Driver.cnic_no == cnic).first()
                    if existing_cnic:
                        row_issues.append(f'CNIC "{cnic}" already exists in system.')

                lic_val = row.get('license_no')
                lic = str(lic_val).strip() if not pd.isna(lic_val) else ''
                if lic == '0':
                    lic = ''  # Excel number 0 = no license
                if lic:
                    existing_lic = Driver.query.filter(Driver.license_no == lic).first()
                    if existing_lic:
                        row_issues.append(f'License No "{lic}" already exists in system.')

                raw_status = row.get('status')
                if pd.isna(raw_status) or not str(raw_status).strip():
                    status = 'Active'
                else:
                    status = str(raw_status).strip()

                if row_issues:
                    identifier = did or cnic or lic or f'Row {row_num}'
                    for msg in row_issues:
                        import_errors.append({
                            'row': row_num,
                            'identifier': identifier,
                            'message': msg
                        })
                    continue

                application_date = parse_import_date(row.get('application_date'))
                dob = parse_import_date(row.get('dob'))
                cnic_issue_date = parse_import_date(row.get('cnic_issue_date'))
                cnic_expiry_date = parse_import_date(row.get('cnic_expiry_date'))
                license_issue_date = parse_import_date(row.get('license_issue_date'))
                license_expiry_date = parse_import_date(row.get('license_expiry_date'))

                from datetime import date as _date
                if not application_date:
                    application_date = pk_date()

                def _expiry_status(expiry_date):
                    if expiry_date is None:
                        return None
                    return "Expired" if expiry_date < pk_date() else "Valid"

                d = Driver(
                    driver_id=did,
                    post=clean_text(row.get('post')),
                    application_date=application_date,
                    name=clean_text(row.get('name')),
                    father_name=clean_text(row.get('father_name')),
                    dob=dob,
                    phone1=clean_text(row.get('phone1')),
                    phone2=clean_text(row.get('phone2')),
                    emergency_no=clean_text(row.get('emergency_no')),
                    address=clean_text(row.get('address')),
                    education=clean_text(row.get('education')),
                    blood_group=clean_text(row.get('blood_group')),
                    driver_district=clean_text(row.get('driver_district')),
                    cnic_no=cnic or 'N/A',
                    cnic_issue_date=cnic_issue_date,
                    cnic_expiry_date=cnic_expiry_date,
                    cnic_status=_expiry_status(cnic_expiry_date),
                    license_no=lic or 'N/A',
                    license_type=clean_text(row.get('license_type')),
                    issue_district=clean_text(row.get('issue_district')),
                    license_issue_date=license_issue_date,
                    license_expiry_date=license_expiry_date,
                    license_status=_expiry_status(license_expiry_date),
                    bank_name=clean_text(row.get('bank_name')),
                    account_no=clean_text(row.get('account_no')),
                    account_title=clean_text(row.get('account_title')),
                    shirt_size=clean_text(row.get('shirt_size')),
                    trouser_size=clean_text(row.get('trouser_size')),
                    jacket_size=clean_text(row.get('jacket_size')),
                    status=status,
                )
                drivers_to_add.append(d)

            if import_errors:
                db.session.rollback()
                flash('Import failed. Please review the error table on this page.', 'danger')
                return render_template('drivers_import.html', form=form, import_errors=import_errors)

            for d in drivers_to_add:
                db.session.add(d)
            db.session.commit()

            flash(f'{len(drivers_to_add)} driver(s) imported successfully.', 'success')
            return redirect(url_for('drivers_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error importing drivers: {str(e)}', 'danger')
    return render_template('drivers_import.html', form=form)



@app.route('/drivers/import/template')
def drivers_import_template():
    """
    Downloadable template for driver import (open in Excel and fill).
    Required/Optional fields ka detail text import page par diya gaya hai.
    """
    headers = [
        'driver_id', 'post', 'application_date', 'name', 'father_name', 'dob',
        'phone1', 'phone2', 'emergency_no', 'address',
        'education', 'blood_group', 'driver_district',
        'cnic_no', 'cnic_issue_date', 'cnic_expiry_date',
        'license_no', 'license_type', 'issue_district',
        'license_issue_date', 'license_expiry_date',
        'bank_name', 'account_no', 'account_title',
        'shirt_size', 'trouser_size', 'jacket_size',
        'status'
    ]
    rows = [
        ['DRV-2024-1001', 'Driver', '01-01-2024', 'Ali Ahmad', 'Ahmad Khan', '01-01-1990',
         '0300-1112233', '0300-2223344', '0300-3334455', 'House #1, Street #1, Lahore',
         'Matric', 'O+', 'Lahore',
         '32304-1111111-5', '01-01-2015', '01-01-2030',
         'LTV-12345', 'LTV', 'Lahore',
         '01-01-2015', '01-01-2030',
         'XYZ Bank', '1234567890', 'Ali Ahmad',
         'M', '32', 'M',
         'Active'],
        ['DRV-2024-1002', 'Senior Driver', '05-02-2024', 'Bilal Hussain', 'Hussain Raza', '05-05-1988',
         '0300-2223344', '0300-4445566', '0300-5556677', 'House #2, Street #5, Lahore',
         'Intermediate', 'A+', 'Lahore',
         '32304-2222222-5', '05-05-2014', '05-05-2029',
         'HTV-56789', 'HTV', 'Lahore',
         '05-05-2014', '05-05-2029',
         'ABC Bank', '9876543210', 'Bilal Hussain',
         'L', '34', 'L',
         'Active'],
    ]
    required_cols = ['driver_id', 'name', 'phone1', 'driver_district', 'cnic_no', 'license_no']
    return generate_excel_template(headers, rows, required_columns=required_cols, filename='drivers_import_template.xlsx')



@app.route('/drivers/print')
def drivers_print():
    """Print-friendly view of drivers (browser print to PDF)."""
    search = request.args.get('search', '').strip()
    query = Driver.query
    if search:
        flt = _multi_word_filter(search, Driver.driver_id, Driver.name, Driver.father_name, Driver.cnic_no, Driver.cnic_status, Driver.license_no, Driver.license_status, Driver.phone1, Driver.driver_district)
        if flt is not None:
            query = query.filter(flt)
    drivers = query.order_by(Driver.id.asc()).all()
    return render_template('drivers_print.html', drivers=drivers, search=search)



@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    """Redirect back to the originating page with a helpful flash instead of bare 400."""
    if request.path.startswith('/api/'):
        return jsonify({'ok': False, 'error': 'CSRF token missing or invalid. Please refresh and try again.'}), 400
    flash('Session expired or form was re-submitted. Please try again.', 'warning')
    referrer = request.referrer or url_for('dashboard')
    return redirect(referrer)



@app.errorhandler(Exception)
def handle_unhandled_exception(e):
    """Ensure API endpoints never leak HTML pages on failures."""
    if request.path.startswith('/api/'):
        try:
            db.session.rollback()
        except Exception:
            pass
        if isinstance(e, HTTPException):
            return jsonify({'ok': False, 'error': e.description or 'HTTP error'}), int(e.code or 500)
        return jsonify({'ok': False, 'error': f'API internal error: {e}'}), 500
    if isinstance(e, HTTPException):
        return e
    raise e



@app.route('/r2-proxy')
def r2_proxy():
    """Serve an R2 object through Flask so JS canvas can draw it without CORS taint."""
    from urllib.parse import urlparse
    import urllib.request
    import urllib.error
    from r2_storage import R2_PUBLIC_URL as _r2_pub

    url = request.args.get('url', '').strip()
    if not url:
        return make_response('Missing url', 400)

    p = urlparse(url)
    if p.scheme not in ('http', 'https') or not p.netloc:
        return make_response('Invalid url', 400)

    allow_hosts = set()
    if _r2_pub:
        try:
            allow_hosts.add(urlparse(_r2_pub).netloc.lower())
        except Exception:
            pass
    host = (p.netloc or '').lower()
    if not (host.endswith('.r2.dev') or host.endswith('.r2.cloudflarestorage.com') or host in allow_hosts):
        return make_response(f'Host not allowed: {host}', 400)

    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'image/avif,image/webp,image/apng,image/*,*/*;q=0.8',
        })
        with urllib.request.urlopen(req, timeout=25) as r:
            data = r.read()
            ct = r.headers.get('Content-Type') or 'application/octet-stream'

        if not data:
            return make_response('Upstream returned empty response', 502)
        if ct.lower().startswith('text/html'):
            return make_response('Upstream returned HTML, not an image. File may be missing on R2.', 502)

        resp = make_response(data)
        resp.headers['Content-Type'] = ct
        resp.headers['Cache-Control'] = 'private, max-age=3600'
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return resp
    except urllib.error.HTTPError as e:
        code = e.code or 502
        body = ''
        try:
            body = e.read(500).decode('utf-8', errors='ignore')
        except Exception:
            pass
        return make_response(f'Upstream {code}: {body[:200]}', code)
    except Exception as e:
        return make_response(f'Proxy failed: {str(e)}', 502)



@app.route('/driver/<int:driver_id>/delete-document', methods=['POST'])
def driver_delete_document(driver_id):
    """AJAX: delete a single saved document/photo field from DB + R2."""
    ALLOWED_FIELDS = {
        'photo_path', 'cnic_front_path', 'cnic_back_path',
        'license_front_path', 'license_back_path', 'document_path'
    }
    data = request.get_json(force=True) or {}
    field = data.get('field', '').strip()
    if field not in ALLOWED_FIELDS:
        return jsonify({'ok': False, 'error': 'Invalid field'}), 400
    driver = Driver.query.get_or_404(driver_id)
    current_val = getattr(driver, field, None)
    if current_val:
        try:
            from r2_storage import delete_file_by_url as _r2_del
            _r2_del(current_val)
        except Exception:
            pass
        setattr(driver, field, None)
        db.session.commit()
    return jsonify({'ok': True})



@app.route('/driver/add', methods=['GET', 'POST'])
@app.route('/driver/edit/<int:id>', methods=['GET', 'POST'])
def driver_form(id=None):
    # Post dropdown: sirf Full Name (short name nahi)
    posts = EmployeePost.query.order_by(EmployeePost.full_name).all()
    post_choices = [('', '-- Select Post --')] + [
        (p.full_name, p.full_name) for p in posts
    ]

    if id:
        driver = Driver.query.get_or_404(id)
        form = DriverForm(obj=driver)
        # Edit: agar driver ki post import se aayi hai aur master mein nahi hai, to choices mein add karo taake change na ho
        if driver.post and driver.post.strip():
            existing_values = [c[0] for c in post_choices]
            if driver.post.strip() not in existing_values:
                post_choices = post_choices + [(driver.post.strip(), driver.post.strip())]
        form.post.choices = post_choices
        if driver.application_date:
            if isinstance(driver.application_date, str):
                form.application_date.data = parse_date(driver.application_date)
            else:
                form.application_date.data = driver.application_date
        title = f"Edit Driver - {driver.name}"
    else:
        driver = Driver()
        form = DriverForm()
        form.post.choices = post_choices
        title = "Add New Driver"
    if form.validate_on_submit():
        try:
            u = None
            form.populate_obj(driver)
            # Always recalculate status server-side — do not rely on JS hidden fields
            _today = pk_date()
            driver.cnic_status = ('Valid' if driver.cnic_expiry_date >= _today else 'Expired') if driver.cnic_expiry_date else None
            driver.license_status = ('Valid' if driver.license_expiry_date >= _today else 'Expired') if driver.license_expiry_date else None
            if not id:
                db.session.add(driver)
            db.session.commit()
            try:
                from routes_finance import _auto_create_coa_account
                _auto_create_coa_account('driver', driver.id, driver.name, extra_label=driver.driver_id)
                db.session.commit()
            except Exception:
                pass
            from r2_storage import upload_image_file as _r2_img, upload_pdf_file as _r2_pdf, R2_PUBLIC_URL as _r2_url
            from r2_storage import R2_ACCESS_KEY_ID as _r2_key, R2_ENDPOINT_URL as _r2_ep, R2_BUCKET_NAME as _r2_bkt
            _use_r2 = bool(_r2_url and _r2_key and _r2_ep and _r2_bkt)
            _any_upload = False

            _r2_warnings = []

            def _save_image(file_storage, field_attr, r2_folder, local_fname):
                nonlocal _any_upload
                if not (file_storage and file_storage.filename):
                    return
                file_storage.seek(0)
                if _use_r2:
                    try:
                        url = _r2_img(file_storage, folder=r2_folder)
                        if url:
                            setattr(driver, field_attr, url)
                            _any_upload = True
                            return
                    except Exception as e:
                        app.logger.error('R2 upload failed for %s: %s', field_attr, e)
                        _r2_warnings.append(field_attr)
                        return
                else:
                    _r2_warnings.append(field_attr)
                    return

            def _save_pdf(file_storage, field_attr, r2_folder, local_fname):
                nonlocal _any_upload
                if not (file_storage and file_storage.filename):
                    return
                file_storage.seek(0)
                if _use_r2:
                    try:
                        url = _r2_pdf(file_storage, folder=r2_folder)
                        if url:
                            setattr(driver, field_attr, url)
                            _any_upload = True
                            return
                    except Exception as e:
                        app.logger.error('R2 PDF upload failed for %s: %s', field_attr, e)
                        _r2_warnings.append(field_attr)
                        return
                else:
                    _r2_warnings.append(field_attr)
                    return

            _save_image(request.files.get('photo'),         'photo_path',         'drivers/photos',   'photo')
            _save_image(request.files.get('cnic_front'),    'cnic_front_path',    'drivers/cnic',     'cnic_front')
            _save_image(request.files.get('cnic_back'),     'cnic_back_path',     'drivers/cnic',     'cnic_back')
            _save_image(request.files.get('license_front'), 'license_front_path', 'drivers/license',  'license_front')
            _save_image(request.files.get('license_back'),  'license_back_path',  'drivers/license',  'license_back')
            _save_image(request.files.get('verify_license_photo'), 'verify_license_photo_path', 'drivers/license', 'verify_license')
            _save_pdf(request.files.get('document'),        'document_path',      'drivers/documents','document')

            if _any_upload:
                db.session.commit()
            if _r2_warnings:
                flash(f"Warning: {len(_r2_warnings)} file(s) could not be uploaded — Cloudflare R2 is not configured. Files skipped: {', '.join(_r2_warnings)}. Please set R2 environment variables.", 'warning')
            if not id and driver.cnic_no and (driver.cnic_no or '').strip() and driver.vehicle_id:
                post_id, role_id = None, None
                if driver.post and (driver.post or '').strip():
                    emp_post = EmployeePost.query.filter(EmployeePost.full_name == (driver.post or '').strip()).first()
                    if emp_post:
                        post_id = emp_post.id
                        role_id = emp_post.role_id
                u = _create_user_for_employee_or_driver(driver.cnic_no.strip(), driver.name, post_id, role_id)
                if u:
                    flash("Driver saved! Login user bhi ban gaya: User ID = CNIC, pehli dafa password 123 se login karein, phir naya password set karein.", 'success')
            if driver.cnic_no and (driver.cnic_no or '').strip():
                _sync_user_full_name_by_cnic(driver.cnic_no.strip(), driver.name)
            if id or not (not id and driver.cnic_no and (driver.cnic_no or '').strip() and u):
                flash(f"Driver '{driver.name}' successfully {'updated' if id else 'added'}!", 'success')
            return redirect(url_for('drivers_list'))
        except IntegrityError:
            db.session.rollback()
            flash('Duplicate entry: Driver ID, CNIC, or License No already exists in the system.', 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f"Error saving driver: {str(e)}", 'danger')
    relation_suggestions = [
        r[0] for r in db.session.query(Driver.emergency_relation)
        .filter(Driver.emergency_relation != None, Driver.emergency_relation != '')
        .distinct().order_by(Driver.emergency_relation).all()
    ]
    return render_template('driver_form.html', form=form, title=title, driver=driver,
                           relation_suggestions=relation_suggestions,
                           **_nav_back_ctx(url_for('drivers_list')))


@app.route('/driver/delete/<int:id>', methods=['POST'])
def delete_driver(id):
    driver = Driver.query.get_or_404(id)
    try:
        # Delete related records that have NOT NULL driver_id (else IntegrityError)
        DriverStatusChange.query.filter_by(driver_id=driver.id).delete()
        DriverTransfer.query.filter_by(driver_id=driver.id).delete()
        DriverAttendance.query.filter_by(driver_id=driver.id).delete()
        db.session.delete(driver)
        db.session.commit()
        flash('Driver deleted.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting driver: {str(e)}', 'danger')
    return redirect(url_for('drivers_list'))


@app.route('/parking/')
def parking_list():
    from auth_utils import get_user_context
    
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)
    
    search = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    sort_by = request.args.get('sort_by', 'name')
    sort_order = request.args.get('sort_order', 'asc')

    query = ParkingStation.query
    
    # Apply user data scope - parking stations assigned to user's projects
    if not is_master_or_admin and allowed_projects:
        query = query.filter(ParkingStation.project_id.in_(list(allowed_projects)))
    
    if search:
        flt = _multi_word_filter(search, ParkingStation.name, ParkingStation.district, ParkingStation.address_location)
        if flt is not None:
            query = query.filter(flt)
    
    # Apply sorting based on sort_by column
    if sort_by == 'id':
        order_col = ParkingStation.id.asc() if sort_order == 'asc' else ParkingStation.id.desc()
    elif sort_by == 'district':
        order_col = ParkingStation.district.asc() if sort_order == 'asc' else ParkingStation.district.desc()
    elif sort_by == 'tehsil':
        order_col = ParkingStation.tehsil.asc() if sort_order == 'asc' else ParkingStation.tehsil.desc()
    elif sort_by == 'capacity':
        order_col = ParkingStation.capacity.asc() if sort_order == 'asc' else ParkingStation.capacity.desc()
    elif sort_by == 'create_date':
        order_col = ParkingStation.create_date.asc() if sort_order == 'asc' else ParkingStation.create_date.desc()
    else:  # default to name
        order_col = ParkingStation.name.asc() if sort_order == 'asc' else ParkingStation.name.desc()
    
    parkings_pagination = query.order_by(order_col).paginate(page=page, per_page=per_page, error_out=False)
    parkings = parkings_pagination.items
    return render_template('parking_list.html', parkings=parkings, search=search,
                           pagination=parkings_pagination, per_page=per_page,
                           sort_by=sort_by, sort_order=sort_order,
                           **_master_nav_back())



@app.route('/parking/import', methods=['GET', 'POST'])
def parking_import():
    """
    Import parking locations from Excel/CSV.
    User can also download a template.
    """
    form = ParkingImportForm()
    if request.method == 'POST' and form.validate_on_submit():
        f = form.file.data
        if not f:
            flash('Please select an Excel/CSV file.', 'warning')
            return redirect(url_for('parking_import'))
        try:
            import pandas as pd
            filename = f.filename or ''
            ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
            if ext in ('xlsx', 'xls'):
                df = pd.read_excel(f)
            elif ext == 'csv':
                df = pd.read_csv(f)
            else:
                flash('Unsupported file type. Please upload .xlsx, .xls or .csv.', 'danger')
                return redirect(url_for('parking_import'))

            # Required vs optional columns (Parking form ke mutabiq)
            required_cols = ['name', 'district', 'tehsil', 'capacity', 'create_date']
            expected_cols = required_cols + [
                'mouza', 'uc_name',
                'address_location', 'remarks',
                'latitude', 'longitude'
            ]
            missing = [c for c in expected_cols if c not in df.columns]
            if missing:
                flash(f'Missing required columns in file: {", ".join(missing)}', 'danger')
                return redirect(url_for('parking_import'))

            # NaN ko 'N/A' mein convert karne ke liye helper (sirf text fields ke liye)
            def clean_text(value):
                if pd.isna(value):
                    return 'N/A'
                v = str(value or '').strip()
                return v or 'N/A'

            from utils import parse_date
            import_errors = []
            parkings_to_add = []

            for idx, row in df.iterrows():
                row_num = idx + 2
                row_issues = []

                name_raw = row.get('name')
                if pd.isna(name_raw) or not str(name_raw).strip():
                    row_issues.append('Field "name" is required.')
                    name = ''
                else:
                    name = str(name_raw).strip()

                # Required field checks
                for col in required_cols:
                    val = row.get(col)
                    if pd.isna(val) or not str(val).strip():
                        row_issues.append(f'Field "{col}" is required.')

                # Duplicate check (same logic as form: name + district)
                district_text = clean_text(row.get('district'))
                if name and district_text:
                    existing = ParkingStation.query.filter(
                        ParkingStation.name == name,
                        ParkingStation.district == district_text
                    ).first()
                    if existing:
                        row_issues.append(f'Parking Station "{name}" in district "{district_text}" already exists.')

                capacity_val = row.get('capacity')
                try:
                    capacity = int(capacity_val) if pd.notna(capacity_val) else 0
                except Exception:
                    row_issues.append('"capacity" must be a number.')
                    capacity = 0

                # Create Date parse (required)
                create_raw = row.get('create_date')
                create_date = None
                if pd.notna(create_raw):
                    if isinstance(create_raw, str):
                        create_date = parse_date(create_raw)
                    else:
                        try:
                            create_date = pd.to_datetime(create_raw).date()
                        except Exception:
                            create_date = None
                if not create_date:
                    row_issues.append('"create_date" is invalid or missing (expected dd-mm-yyyy).')

                # Latitude / Longitude parse (optional)
                lat_val = row.get('latitude')
                lon_val = row.get('longitude')
                try:
                    latitude = float(lat_val) if pd.notna(lat_val) else None
                except Exception:
                    latitude = None
                try:
                    longitude = float(lon_val) if pd.notna(lon_val) else None
                except Exception:
                    longitude = None

                if row_issues:
                    for msg in row_issues:
                        import_errors.append({
                            'row': row_num,
                            'identifier': name,
                            'message': msg
                        })
                    continue

                p = ParkingStation(
                    name=name,
                    district=district_text,
                    tehsil=clean_text(row.get('tehsil')),
                    mouza=clean_text(row.get('mouza')),
                    uc_name=clean_text(row.get('uc_name')),
                    capacity=capacity or 0,
                    address_location=clean_text(row.get('address_location')),
                    remarks=clean_text(row.get('remarks')),
                    create_date=create_date,
                    latitude=latitude,
                    longitude=longitude,
                )
                parkings_to_add.append(p)

            if import_errors:
                db.session.rollback()
                flash('Import failed. Please review the error table on this page.', 'danger')
                return render_template('parking_import.html', form=form, import_errors=import_errors)

            for p in parkings_to_add:
                db.session.add(p)
            db.session.commit()

            flash(f'{len(parkings_to_add)} parking station(s) imported successfully.', 'success')
            return redirect(url_for('parking_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error importing parking locations: {str(e)}', 'danger')
    return render_template('parking_import.html', form=form)



@app.route('/parking/import/template')
def parking_import_template():
    """
    Downloadable template for parking import (open in Excel and fill).
    Ab is mein complete form fields shamil hain.
    """
    headers = [
        'name', 'district', 'tehsil', 'mouza', 'uc_name',
        'capacity', 'address_location', 'remarks',
        'create_date', 'latitude', 'longitude'
    ]
    # Sample rows only (Required/Optional info description mein diya gaya hai)
    rows = [
        ['Central Parking A', 'Lahore', 'Model Town', 'Mouza 1', 'UC-1', 20, 'Near Main Road, Model Town', 'Example row 1', '01-01-2024', 31.520370, 74.358749],
        ['Central Parking B', 'Lahore', 'Johar Town', 'Mouza 2', 'UC-2', 15, 'Near Hospital, Johar Town', 'Example row 2', '05-02-2024', 31.500000, 74.350000],
    ]
    required_cols = ['name', 'district', 'tehsil', 'capacity', 'create_date']
    return generate_excel_template(headers, rows, required_columns=required_cols, filename='parking_import_template.xlsx')



@app.route('/parking/export')
def parking_export():
    """Export parking list (with optional search) to CSV/Excel."""
    search = request.args.get('search', '').strip()
    query = ParkingStation.query
    if search:
        flt = _multi_word_filter(search, ParkingStation.name, ParkingStation.district, ParkingStation.address_location)
        if flt is not None:
            query = query.filter(flt)
    parkings = query.order_by(ParkingStation.id).all()
    headers = ['ID', 'Station Name', 'District', 'Tehsil', 'Capacity', 'Address/Location']
    rows = []
    for p in parkings:
        rows.append([
            p.id,
            p.name,
            p.district or '',
            p.tehsil or '',
            p.capacity,
            p.address_location or '',
        ])
    return generate_csv_response(headers, rows, filename='parking_stations.csv')



@app.route('/parking/print')
def parking_print():
    """Print-friendly view of parking stations (browser print to PDF)."""
    search = request.args.get('search', '').strip()
    query = ParkingStation.query
    if search:
        flt = _multi_word_filter(search, ParkingStation.name, ParkingStation.district, ParkingStation.address_location)
        if flt is not None:
            query = query.filter(flt)
    parkings = query.order_by(ParkingStation.id).all()
    return render_template('parking_print.html', parkings=parkings, search=search)



@app.route('/parking/add', methods=['GET', 'POST'])
@app.route('/parking/edit/<int:id>', methods=['GET', 'POST'])
def parking_form(id=None):
    parking = ParkingStation.query.get_or_404(id) if id else None
    form = ParkingForm(obj=parking)
    if form.validate_on_submit():
        try:
            if not parking:
                parking = ParkingStation()
            # Normalize name (trim spaces)
            name_normalized = (form.name.data or '').strip()
            form.populate_obj(parking)
            parking.name = name_normalized

            # Duplicate name check (case-insensitive, ignore current record)
            existing_q = ParkingStation.query.filter(
                func.lower(ParkingStation.name) == name_normalized.lower()
            )
            if id:
                existing_q = existing_q.filter(ParkingStation.id != parking.id)
            if existing_q.first():
                flash('Parking Station with this name already exists. Please use a different name.', 'danger')
                return render_template('parking_form.html', form=form, title='Parking Station', back_url=url_for('parking_list'),
                                       **_nav_back_ctx(url_for('parking_list')))

            if not id:
                db.session.add(parking)
            db.session.commit()
            flash('Parking Station saved successfully!', 'success')
            return redirect(url_for('parking_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error saving parking station: {str(e)}', 'danger')
    back_url = url_for('parking_list')
    return render_template('parking_form.html', form=form, title='Parking Station', back_url=back_url,
                           **_nav_back_ctx(url_for('parking_list')))



@app.route('/parking/delete/<int:id>', methods=['POST'])
def delete_parking(id):
    parking = ParkingStation.query.get_or_404(id)
    try:
        db.session.delete(parking)
        db.session.commit()
        flash('Parking Station deleted.', 'success')
    except Exception as e:
        flash(f'Error deleting parking station: {str(e)}', 'danger')
    return redirect(url_for('parking_list'))



@app.route('/districts/')
def districts_list():
    search = request.args.get('search', '').strip()
    from_date_str = request.args.get('from_date', '').strip()
    to_date_str = request.args.get('to_date', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    sort_by = request.args.get('sort_by', 'name')
    sort_order = request.args.get('sort_order', 'asc')

    def _dmy(s):
        from datetime import datetime as _dt
        try: return _dt.strptime(s, '%d-%m-%Y').date() if s else None
        except ValueError: return None

    from_date = _dmy(from_date_str)
    to_date = _dmy(to_date_str)

    query = District.query
    if search:
        flt = _multi_word_filter(search, District.name, District.province)
        if flt is not None:
            query = query.filter(flt)
    if from_date:
        query = query.filter(District.created_at >= from_date)
    if to_date:
        from datetime import timedelta
        query = query.filter(District.created_at < (to_date + timedelta(days=1)))

    # Apply sorting based on sort_by column
    if sort_by == 'id':
        order_col = District.id.asc() if sort_order == 'asc' else District.id.desc()
    elif sort_by == 'province':
        order_col = District.province.asc() if sort_order == 'asc' else District.province.desc()
    elif sort_by == 'created_at':
        order_col = District.created_at.asc() if sort_order == 'asc' else District.created_at.desc()
    else:  # default to name
        order_col = District.name.asc() if sort_order == 'asc' else District.name.desc()

    districts_pagination = query.order_by(order_col).paginate(page=page, per_page=per_page, error_out=False)
    districts = districts_pagination.items
    return render_template('districts_list.html', districts=districts, search=search,
                           from_date=from_date_str, to_date=to_date_str,
                           pagination=districts_pagination, per_page=per_page,
                           sort_by=sort_by, sort_order=sort_order,
                           **_master_nav_back())



@app.route('/districts/export')
def districts_export():
    """Export districts list (with optional search) to CSV/Excel."""
    search = request.args.get('search', '').strip()
    query = District.query
    if search:
        flt = _multi_word_filter(search, District.name, District.province)
        if flt is not None:
            query = query.filter(flt)
    districts = query.order_by(District.name.asc()).all()
    headers = ['ID', 'District Name', 'Province/Region', 'Remarks', 'Created']
    rows = []
    for d in districts:
        rows.append([
            d.id,
            d.name,
            d.province or '',
            (d.remarks or '')[:200] if getattr(d, 'remarks', None) else '',
            d.created_at.strftime('%Y-%m-%d') if getattr(d, 'created_at', None) else '',
        ])
    return generate_csv_response(headers, rows, filename='districts.csv')



@app.route('/districts/print')
def districts_print():
    """Print-friendly view of districts list (browser print to PDF)."""
    search = request.args.get('search', '').strip()
    query = District.query
    if search:
        flt = _multi_word_filter(search, District.name, District.province)
        if flt is not None:
            query = query.filter(flt)
    districts = query.order_by(District.id).all()
    return render_template('districts_print.html', districts=districts, search=search)



@app.route('/district/add', methods=['GET', 'POST'])
@app.route('/district/edit/<int:id>', methods=['GET', 'POST'])
def district_form(id=None):
    district = District.query.get_or_404(id) if id else None
    form = DistrictForm(obj=district)
    if form.validate_on_submit():
        try:
            if not district:
                district = District()
            form.populate_obj(district)
            if not id:
                db.session.add(district)
            db.session.commit()
            flash('District saved successfully!', 'success')
            return redirect(url_for('districts_list'))
        except IntegrityError:
            db.session.rollback()
            flash('This district name already exists', 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'Error saving district: {str(e)}', 'danger')
    back_url = url_for('districts_list')
    return render_template('district_form.html', form=form, title='District', back_url=back_url,
                           **_nav_back_ctx(url_for('districts_list')))



@app.route('/district/delete/<int:id>', methods=['POST'])
def delete_district(id):
    district = District.query.get_or_404(id)
    try:
        db.session.delete(district)
        db.session.commit()
        flash('District deleted.', 'success')
    except Exception as e:
        flash(f'Error deleting district: {str(e)}', 'danger')
    return redirect(url_for('districts_list'))



@app.route('/get_drivers_by_vehicle/<int:vehicle_id>')
def get_drivers_by_vehicle(vehicle_id):
    drivers = Driver.query.filter_by(vehicle_id=vehicle_id).all()
    return jsonify([{
        "id": d.id,
        "name": f"{d.name} ({d.driver_id or 'No ID'}) - {d.shift or 'No Shift'}"
    } for d in drivers])



@app.route('/get_projects_by_district/<int:district_id>')
def get_projects_by_district(district_id):
    if not district_id:
        return jsonify([])
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)
    q = Project.query.join(project_district).filter(project_district.c.district_id == district_id)
    if not is_master_or_admin and allowed_projects:
        q = q.filter(Project.id.in_(list(allowed_projects)))
    projects = q.order_by(Project.name).all()
    resp = make_response(jsonify([{'id': p.id, 'name': p.name} for p in projects]))
    resp.headers['Cache-Control'] = 'private, max-age=120'
    return resp



@app.route('/get_vehicles_by_project_district')
def get_vehicles_by_project_district():
    project_id = request.args.get('project_id', type=int) or 0
    district_id = request.args.get('district_id', type=int) or 0
    if project_id and district_id:
        q = Vehicle.query.filter(Vehicle.project_id == project_id, Vehicle.district_id == district_id)
    elif project_id:
        q = Vehicle.query.filter(Vehicle.project_id == project_id)
    elif district_id:
        q = Vehicle.query.filter(Vehicle.district_id == district_id)
    else:
        q = Vehicle.query.filter(Vehicle.project_id.isnot(None))
    scope_projects, scope_districts, scope_vehicles, scope_shifts = _get_user_scope()
    if scope_projects:
        q = q.filter(Vehicle.project_id.in_(scope_projects))
    if scope_districts:
        q = q.filter(Vehicle.district_id.in_(scope_districts))
    if scope_vehicles:
        q = q.filter(Vehicle.id.in_(scope_vehicles))
    vehicles = q.order_by(*vehicle_order_by()).all()
    resp = make_response(jsonify([{
        'id': v.id,
        'vehicle_no': v.vehicle_no,
        'vehicle_type': v.vehicle_type or '',
        'fuel_type': v.fuel_type or 'Petrol',
        'fuel_tank_capacity': float(v.fuel_tank_capacity or 0),
        'vehicle_family': v.vehicle_family or '',
    } for v in vehicles]))
    resp.headers['Cache-Control'] = 'private, max-age=60'
    return resp



@app.route('/api/fuel-expense/location-cascade')
def api_fuel_expense_location_cascade():
    """JSON: full district→projects + scoped vehicles; same payload embedded in form page."""
    if not _workspace_employee_id_for_expenses():
        return jsonify({"error": "no_workspace", "projects_by_district": {}, "vehicles": []}), 403
    r = _fuel_expense_location_cascade_dict()
    resp = make_response(jsonify(r))
    resp.headers["Cache-Control"] = "private, max-age=60"
    return resp



@app.route('/driver-posts')
def driver_post_list():
    search = request.args.get('search', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    sort_by = request.args.get('sort_by', 'full_name')
    sort_order = request.args.get('sort_order', 'asc')
    
    query = EmployeePost.query
    if search:
        flt = _multi_word_filter(search, EmployeePost.full_name)
        if flt is not None:
            query = query.filter(flt)
    
    # Apply sorting
    if sort_by == 'id':
        order_col = EmployeePost.id.asc() if sort_order == 'asc' else EmployeePost.id.desc()
    elif sort_by == 'short_name':
        order_col = EmployeePost.short_name.asc() if sort_order == 'asc' else EmployeePost.short_name.desc()
    else:  # default to full_name
        order_col = EmployeePost.full_name.asc() if sort_order == 'asc' else EmployeePost.full_name.desc()
    
    pagination = query.order_by(order_col).paginate(page=page, per_page=per_page, error_out=False)
    posts = pagination.items
    
    return render_template('driver_post_list.html', posts=posts, search=search,
                         pagination=pagination, per_page=per_page, sort_by=sort_by, sort_order=sort_order,
                         **_master_nav_back())



@app.route('/driver-post/add', methods=['GET', 'POST'])
@app.route('/driver-post/edit/<int:id>', methods=['GET', 'POST'])
def driver_post_form(id=None):
    post = EmployeePost.query.get_or_404(id) if id else None
    form = EmployeePostForm(obj=post)
    form.role_id.choices = [(0, '-- No access role --')] + [(r.id, r.name) for r in Role.query.filter(func.lower(Role.name) != 'master').order_by(Role.name).all()]
    if form.validate_on_submit():
        if not post:
            post = EmployeePost()
        post.short_name = form.short_name.data.strip()
        post.full_name = form.full_name.data.strip()
        post.role_id = form.role_id.data if form.role_id.data else None
        post.remarks = form.remarks.data.strip() if form.remarks.data else None
        if not id:
            db.session.add(post)
        db.session.commit()
        flash('Post saved.', 'success')
        return redirect(url_for('driver_post_list'))
    if request.method == 'GET' and post:
        form.role_id.data = post.role_id or 0
    return render_template('driver_post_form.html', form=form, post=post,
                           **_nav_back_ctx(url_for('driver_post_list')))



@app.route('/driver-post/delete/<int:id>', methods=['POST'])
def driver_post_delete(id):
    post = EmployeePost.query.get_or_404(id)
    db.session.delete(post)
    db.session.commit()
    flash('Post deleted.', 'success')
    return redirect(url_for('driver_post_list'))



@app.route('/driver-posts/export')
def driver_post_export():
    search = request.args.get('search', '').strip()
    query = EmployeePost.query
    if search:
        flt = _multi_word_filter(search, EmployeePost.full_name)
        if flt is not None:
            query = query.filter(flt)
    posts = query.order_by(EmployeePost.full_name).all()
    headers = ['ID', 'Short Name', 'Full Name', 'Remarks']
    rows = []
    for p in posts:
        rows.append([p.id, p.short_name, p.full_name, p.remarks or ''])
    filename = 'employee_posts.csv' if not search else f'employee_posts_search_{search}.csv'
    return generate_csv_response(headers, rows, filename=filename)



@app.route('/driver-posts/print')
def driver_post_print():
    search = request.args.get('search', '').strip()
    query = EmployeePost.query
    if search:
        flt = _multi_word_filter(search, EmployeePost.full_name)
        if flt is not None:
            query = query.filter(flt)
    posts = query.order_by(EmployeePost.full_name).all()
    return render_template('driver_post_print.html', posts=posts, search=search)



@app.route('/parties')
def party_list():
    flash('Master Party module removed. Please use Employee Workspace > Parties.', 'info')
    return redirect(url_for('workspace_parties_list'))



@app.route('/party/add', methods=['GET', 'POST'])
@app.route('/party/edit/<int:id>', methods=['GET', 'POST'])
def party_form(id=None):
    flash('Master Party form removed. Please use Employee Workspace > Add Workspace Party.', 'info')
    return redirect(url_for('workspace_party_new'))



@app.route('/party/delete/<int:id>', methods=['POST'])
def party_delete(id):
    flash('Master party delete disabled — use Employee Workspace > Parties.', 'info')
    return redirect(url_for('workspace_parties_list'))



@app.route('/parties/export')
def party_export():
    return redirect(url_for('workspace_party_export', **dict(request.args)))



@app.route('/parties/print')
def party_print():
    return redirect(url_for('workspace_party_print', **dict(request.args)))



@app.route('/parties/import', methods=['GET', 'POST'])
def party_import():
    return redirect(url_for('workspace_party_import'))



@app.route('/parties/import/template')
def party_import_template():
    return redirect(url_for('workspace_party_import_template'))



def _ensure_product_used_in_forms_column():
    """Add used_in_forms column to product table if missing (e.g. old DB before migration)."""
    try:
        insp = inspect(db.engine)
        if 'product' not in insp.get_table_names():
            return
        cols = [c['name'] for c in insp.get_columns('product')]
        if 'used_in_forms' in cols:
            return
        db.session.execute(text('ALTER TABLE product ADD COLUMN used_in_forms VARCHAR(100)'))
        db.session.commit()
    except Exception:
        db.session.rollback()



@app.route('/products')
def product_list():
    _ensure_product_used_in_forms_column()
    search = request.args.get('search', '').strip()
    per_page_default = session.get('per_page_default', 20)
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', per_page_default, type=int)
    sort_by = request.args.get('sort_by', 'name')
    sort_order = request.args.get('sort_order', 'asc')

    query = Product.query
    if search:
        flt = _multi_word_filter(search, Product.name)
        if flt is not None:
            query = query.filter(flt)
    
    # Apply sorting
    if sort_by == 'name':
        order_col = Product.name.asc() if sort_order == 'asc' else Product.name.desc()
    elif sort_by == 'used_in_forms':
        order_col = Product.used_in_forms.asc() if sort_order == 'asc' else Product.used_in_forms.desc()
    else:  # default to name
        order_col = Product.name.asc() if sort_order == 'asc' else Product.name.desc()
    
    pagination = query.order_by(order_col).paginate(page=page, per_page=per_page, error_out=False)
    products = pagination.items
    session['per_page_default'] = per_page
    return render_template('product_list.html', products=products, search=search,
                           pagination=pagination, per_page=per_page, sort_by=sort_by, sort_order=sort_order)



@app.route('/product/add', methods=['GET', 'POST'])
@app.route('/product/edit/<int:id>', methods=['GET', 'POST'])
def product_form(id=None):
    _ensure_product_used_in_forms_column()
    product = Product.query.get_or_404(id) if id else None
    form = ProductForm(obj=product)
    if request.method == 'GET' and product and product.used_in_forms:
        form.used_in_forms.data = [x.strip() for x in product.used_in_forms.split(',') if x.strip()]
    if form.validate_on_submit():
        if not product:
            product = Product()
        form.populate_obj(product)
        product.used_in_forms = ','.join(form.used_in_forms.data) if form.used_in_forms.data else None
        if not id:
            db.session.add(product)
        db.session.commit()
        flash('Product saved.', 'success')
        next_url = request.form.get('next') or request.args.get('next') or url_for('product_list')
        return redirect(next_url)
    return render_template('product_form.html', form=form, product=product, title='Edit Product' if id else 'Create Product Name')



@app.route('/product/delete/<int:id>', methods=['POST'])
def product_delete(id):
    product = Product.query.get_or_404(id)
    db.session.delete(product)
    db.session.commit()
    flash('Product deleted.', 'success')
    return redirect(url_for('product_list'))



def _product_list_query(search=None):
    query = Product.query
    if search:
        flt = _multi_word_filter(search, Product.name)
        if flt is not None:
            query = query.filter(flt)
    return query.order_by(Product.name)



@app.route('/products/export')
def product_export():
    search = request.args.get('search', '').strip()
    products = _product_list_query(search=search).all()
    headers = ['S.No', 'Product Name', 'Used in Form', 'Remarks']
    rows = []
    for i, p in enumerate(products, 1):
        rows.append([
            i,
            p.name or '',
            p.used_in_forms or '',
            (p.remarks or '')[:200]
        ])
    filename = 'products.xlsx' if not search else f'products_{search[:30].replace("/", "-")}.xlsx'
    return generate_excel_template(headers, rows, required_columns=[], filename=filename)



@app.route('/products/print')
def product_print():
    search = request.args.get('search', '').strip()
    products = _product_list_query(search=search).all()
    return render_template('product_print.html', products=products, search=search)



@app.route('/products/import', methods=['GET', 'POST'])
def product_import():
    form = ProductImportForm()
    if request.method == 'POST' and form.validate_on_submit():
        f = form.file.data
        if not f:
            flash('Please select an Excel/CSV file.', 'warning')
            return redirect(url_for('product_import'))
        try:
            import pandas as pd
            filename = f.filename or ''
            ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
            if ext in ('xlsx', 'xls'):
                df = pd.read_excel(f)
            elif ext == 'csv':
                df = pd.read_csv(f)
            else:
                flash('Unsupported file type. Use .xlsx, .xls or .csv.', 'danger')
                return redirect(url_for('product_import'))
            if 'name' not in df.columns:
                flash('Missing required column: name', 'danger')
                return redirect(url_for('product_import'))
            import_errors = []
            products_to_add = []
            for idx, row in df.iterrows():
                row_num = idx + 2
                name = str(row.get('name', '')).strip() if not pd.isna(row.get('name')) else ''
                if not name:
                    import_errors.append({'row': row_num, 'identifier': '-', 'message': '"name" is required.'})
                    continue
                used_in = row.get('used_in_forms')
                used_in = '' if pd.isna(used_in) else str(used_in).strip()[:100]
                remarks = row.get('remarks')
                remarks = '' if pd.isna(remarks) else str(remarks).strip()
                products_to_add.append(Product(name=name, used_in_forms=used_in or None, remarks=remarks or None))
            if import_errors:
                return render_template('product_import.html', form=form, import_errors=import_errors)
            for p in products_to_add:
                db.session.add(p)
            db.session.commit()
            flash(f'{len(products_to_add)} product(s) imported successfully.', 'success')
            return redirect(url_for('product_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error importing: {str(e)}', 'danger')
    return render_template('product_import.html', form=form)



@app.route('/products/import/template')
def product_import_template():
    headers = ['name', 'used_in_forms', 'remarks']
    rows = [
        ['Diesel', 'Fueling', 'Fuel product'],
        ['Engine Oil', 'Oil,Maintenance', 'Oil and maintenance'],
    ]
    return generate_excel_template(headers, rows, required_columns=['name'], filename='product_import_template.xlsx')


