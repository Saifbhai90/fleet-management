"""
Workforce: Driver Job Left, Rejoin, Leave Requests, Driver Posts.

Extracted from routes.py to reduce file size.
"""

from flask import (
    render_template, redirect, url_for, flash, request,
    session, jsonify, make_response, abort,
    Response, current_app,
)
from app import app, db, csrf
from models import (
    Vehicle, Driver, Project, District, Company, ParkingStation,
    DriverStatusChange, DriverTransfer, EmployeePost,
    LeaveRequest, Employee, EmployeeAssignment,
    VehicleDailyTask, DriverAttendance,
    SystemSetting, User, ActivityLog,
)
from forms import (
    DriverJobLeftForm, DriverRejoinForm,
    EmployeePostForm,
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
    _workforce_nav_back,
    _sync_user_active_by_cnic,
    _sync_user_full_name_by_cnic,
    _create_user_for_employee_or_driver,
    enforce_data_freeze,
    _norm_district_name_key,
    _normalize_vehicle_no,
    _cnic_digits,
    SimplePagination,
)

from sqlalchemy import String as SAString
from sqlalchemy import cast
import xlsxwriter
from models import project_district
from flask import send_file
@app.route('/driver/job-left/new', methods=['GET', 'POST'])
def driver_job_left_new():
    form = DriverJobLeftForm()
    
    # Page load pe project choices set karo (dropdown populate ke liye)
    projects = Project.query.order_by(Project.name).all()
    form.project_id.choices = [(0, '-- Select Project --')] + [(p.id, p.name) for p in projects]
    
    # Default empty choices cascading fields ke liye (validation crash na ho)
    form.district_id.choices = [(0, '-- Select District --')]
    form.vehicle_id.choices = [(0, '-- Select Vehicle --')]
    form.driver_id.choices = [(0, '-- Select Driver --')]
    
    if form.is_submitted():  # Yeh check POST request pe chalega (submit hone pe)
        # Step 1: Selected values lo
        selected_project = form.project_id.data
        selected_district = form.district_id.data
        selected_vehicle = form.vehicle_id.data
        
        # Step 2: Choices ko re-build karo taake validation pass ho
        # District choices re-create based on selected project
        if selected_project and selected_project != 0:
            districts = District.query.join(project_district)\
                               .filter(project_district.c.project_id == selected_project)\
                               .order_by(District.name).all()
            form.district_id.choices = [(0, '-- Select District --')] + [(d.id, d.name) for d in districts]
        
        # Vehicle choices re-create based on project + district
        if selected_project != 0 and selected_district != 0:
            vehicles = Vehicle.query.filter(
                Vehicle.project_id == selected_project,
                Vehicle.district_id == selected_district
            ).order_by(*vehicle_order_by()).all()
            form.vehicle_id.choices = [(0, '-- Select Vehicle --')] + [(v.id, v.vehicle_no) for v in vehicles]
        
        # Driver choices re-create based on vehicle
        if selected_vehicle != 0:
            drivers = Driver.query.filter_by(vehicle_id=selected_vehicle).all()
            form.driver_id.choices = [(0, '-- Select Driver --')] + \
                                    [(d.id, f"{d.name} ({d.driver_id or 'No ID'}) - {d.shift or 'No Shift'}") for d in drivers]
        
        # Ab form ko dobara validate karo (choices updated hain)
        if form.validate():
            driver = db.session.get(Driver, form.driver_id.data)
            
            if not driver:
                flash("Invalid driver selected.", "danger")
            elif driver.vehicle_id != form.vehicle_id.data:
                flash("This driver is not assigned to the selected vehicle.", "danger")
            else:
                reason = form.reason.data
                if reason == 'Other':
                    reason = form.other_reason.data.strip() or 'Other (unspecified)'
                
                # Save to database
                status_change = DriverStatusChange(
                    driver_id=driver.id,
                    action_type='left',
                    reason=reason,
                    change_date=form.leave_date.data,
                    remarks=form.remarks.data,
                    left_project_id=form.project_id.data if form.project_id.data != 0 else None,
                    left_district_id=form.district_id.data if form.district_id.data != 0 else None,
                    left_vehicle_id=form.vehicle_id.data if form.vehicle_id.data != 0 else None,
                    left_shift=driver.shift
                )
                db.session.add(status_change)
                
                # Clear driver's current assignment
                driver.vehicle_id = None
                driver.shift = None
                driver.district_id = None  # agar Driver model mein hai
                driver.project_id = None  # <-- Ye bhi add karein, taake project se bhi hat jaye
                driver.status = 'Left'    # <-- Ye naya add karein

                db.session.commit()
                # Driver job left → us CNIC wale User ka login band
                _sync_user_active_by_cnic(driver.cnic_no, False)

                flash(f"Driver {driver.name} successfully marked as Job Left!", "success")
                return redirect(url_for('drivers_list'))
        else:
            flash("Please correct the errors below.", "danger")
    
    return render_template('driver_job_left_new.html', form=form, **_workforce_nav_back())



@app.route('/driver/rejoin/new', methods=['GET', 'POST'])
def driver_rejoin_new():
    form = DriverRejoinForm()
    projects = Project.query.order_by(Project.name).all()

    # 1. Base Choices (Initial)
    form.project_id.choices = [(0, '-- Select Project --')] + [(p.id, p.name) for p in projects]
    form.district_id.choices = [(0, '-- Select District --')]
    form.vehicle_id.choices = [(0, '-- Select Vehicle --')]
    form.driver_id.choices = [(0, '-- Select Driver --')]
    form.shift.choices = [('', 'Select'), ('Morning', 'Morning'), ('Night', 'Night')]

    # For Previous Context (Old Project/District/Vehicle) – preserve selections on validation error
    old_project_id = None
    old_district_id = None
    old_vehicle_id = None
    old_districts = []
    old_vehicles = []

    # 2. Re-populate choices BEFORE validation if it's a POST request
    if request.method == 'POST':
        # Previous Context values from POST (not part of WTForms form)
        try:
            old_project_id = int(request.form.get('old_project') or 0) or None
        except ValueError:
            old_project_id = None
        try:
            old_district_id = int(request.form.get('old_district') or 0) or None
        except ValueError:
            old_district_id = None
        try:
            old_vehicle_id = int(request.form.get('old_vehicle') or 0) or None
        except ValueError:
            old_vehicle_id = None

        # Build district / vehicle lists so that Old dropdowns don't reset on errors
        if old_project_id:
            old_districts = District.query.join(project_district).filter(
                project_district.c.project_id == old_project_id
            ).order_by(District.name).all()
        if old_project_id and old_district_id:
            old_vehicles = Vehicle.query.filter_by(
                project_id=old_project_id,
                district_id=old_district_id
            ).order_by(*vehicle_order_by()).all()

        # Hum posted data se choices dubara bana rahe hain taake validation pass ho
        if form.project_id.data and form.project_id.data != 0:
            p_id = form.project_id.data
            districts = District.query.join(project_district).filter(project_district.c.project_id == p_id).all()
            form.district_id.choices = [(d.id, d.name) for d in districts]
            
            d_id = request.form.get('district_id', type=int)
            if d_id:
                vehicles = Vehicle.query.filter_by(district_id=d_id).all()
                form.vehicle_id.choices = [(v.id, v.vehicle_no) for v in vehicles]
                
                v_id = request.form.get('vehicle_id', type=int)
                if v_id:
                    # 'Left' drivers load karna taake validation pass ho sake
                    left_drivers = Driver.query.filter_by(status='Left').all()
                    form.driver_id.choices = [(d.id, d.name) for d in left_drivers]

    # 3. Validation and Saving
    if form.validate_on_submit():
        try:
            driver = db.session.get(Driver, form.driver_id.data)
            if not driver:
                flash("Error: Selected driver not found.", "danger")
                return redirect(url_for('driver_rejoin_new'))

            # Updates
            driver.status = 'Active'
            driver.project_id = form.project_id.data
            driver.district_id = form.district_id.data
            driver.vehicle_id = form.vehicle_id.data
            driver.shift = form.shift.data

            rejoin_log = DriverStatusChange(
                driver_id=driver.id,
                action_type='rejoin',
                change_date=form.rejoin_date.data,
                remarks=form.remarks.data,
                new_project_id=form.project_id.data,
                new_district_id=form.district_id.data,
                new_vehicle_id=form.vehicle_id.data,
                new_shift=form.shift.data
            )
            db.session.add(rejoin_log)
            db.session.commit()
            # Driver rejoin → us CNIC wale User ka login wapas on
            _sync_user_active_by_cnic(driver.cnic_no, True)
            
            flash(f"Success! Driver {driver.name} is now ACTIVE.", "success")
            return redirect(url_for('driver_rejoin_list'))
            
        except Exception as e:
            db.session.rollback()
            app.logger.exception('Database error in company_form: %s', e)
            flash("Database error occurred.", "danger")
    else:
        # AGAR VALIDATION FAIL HO TO TERMINAL MEIN DEKHO KYUN FAIL HUI
        if request.method == 'POST':
            app.logger.warning('Company form validation errors: %s', form.errors)
            flash("Form validation failed. Check terminal for details.", "warning")

    return render_template(
        'driver_rejoin_new.html',
        form=form,
        projects=projects,
        old_project_id=old_project_id,
        old_district_id=old_district_id,
        old_vehicle_id=old_vehicle_id,
        old_districts=old_districts,
        old_vehicles=old_vehicles,
    **_workforce_nav_back(),
    )



@app.route('/driver/job-left/list')
def driver_job_left_list():
    from auth_utils import get_user_context
    
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)
    
    # Optional filters: Project + District + Date Range + Search
    project_id = request.args.get('project_id', type=int) or 0
    district_id = request.args.get('district_id', type=int) or 0
    q = (request.args.get('q') or '').strip()
    from_date_str = (request.args.get('from_date') or '').strip()
    to_date_str = (request.args.get('to_date') or '').strip()
    
    # Auto-select if only 1 option available
    disable_project = False
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

    from_date = None
    to_date = None
    try:
        if from_date_str:
            # UI uses day-month-year (dd-mm-yyyy) via datepicker
            from_date = datetime.strptime(from_date_str, '%d-%m-%Y').date()
    except ValueError:
        from_date = None
    try:
        if to_date_str:
            to_date = datetime.strptime(to_date_str, '%d-%m-%Y').date()
    except ValueError:
        to_date = None

    query = DriverStatusChange.query.filter_by(action_type='left')

    if project_id:
        query = query.filter(DriverStatusChange.left_project_id == project_id)
    if district_id:
        query = query.filter(DriverStatusChange.left_district_id == district_id)
    if from_date:
        query = query.filter(DriverStatusChange.change_date >= from_date)
    if to_date:
        query = query.filter(DriverStatusChange.change_date <= to_date)
    if q:
        query = query.join(Driver) \
                     .outerjoin(Project,  DriverStatusChange.left_project_id  == Project.id) \
                     .outerjoin(District, DriverStatusChange.left_district_id == District.id)
        flt = _multi_word_filter(q,
            Driver.name, Driver.driver_id, Project.name, District.name,
            DriverStatusChange.reason, DriverStatusChange.remarks,
            cast(DriverStatusChange.change_date, SAString))
        if flt is not None:
            query = query.filter(flt)

    left_records = query.order_by(DriverStatusChange.change_date.desc()).all()

    # Filter dropdown choices by user scope
    project_q = Project.query
    if not is_master_or_admin and allowed_projects:
        project_q = project_q.filter(Project.id.in_(list(allowed_projects)))
    projects = [(0, '-- All Projects --')] + [(p.id, p.name) for p in project_q.order_by(Project.name).all()]
    
    district_q = District.query
    if not is_master_or_admin and allowed_districts:
        district_q = district_q.filter(District.id.in_(list(allowed_districts)))
    districts = [(0, '-- All Districts --')] + [(d.id, d.name) for d in district_q.order_by(District.name).all()]

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    pagination = SimplePagination(left_records, page, per_page)
    left_records = pagination.items
    return render_template(
        'driver_job_left_list.html',
        records=left_records,
        title="Driver Job Left History",
        project_id=project_id,
        district_id=district_id,
        q=q,
        from_date=from_date_str,
        to_date=to_date_str,
        project_choices=projects,
        district_choices=districts,
        disable_project=disable_project,
        disable_district=disable_district,
        pagination=pagination,
        per_page=per_page,
    **_workforce_nav_back(),
    )



@app.route('/driver-job-left/view/<int:id>')
def driver_job_left_view(id):
    record = DriverStatusChange.query.get_or_404(id)
    return render_template('driver_job_left_view.html', record=record, **_workforce_nav_back())



@app.route('/driver-job-left/edit/<int:id>', methods=['GET', 'POST'])
def driver_job_left_edit(id):
    record = DriverStatusChange.query.get_or_404(id)
    
    # Form initialize karein aur populate karein
    form = DriverJobLeftForm()
    
    # Dropdowns ko populate karein
    form.project_id.choices = [(p.id, p.name) for p in Project.query.all()]
    form.district_id.choices = [(d.id, d.name) for d in District.query.all()]
    form.vehicle_id.choices = [(v.id, v.vehicle_no) for v in Vehicle.query.all()]
    form.driver_id.choices = [(d.id, d.name) for d in Driver.query.all()]

    if request.method == 'GET':
        # Pre-fill data from DB to Form
        form.project_id.data = record.left_project_id
        form.district_id.data = record.left_district_id
        form.vehicle_id.data = record.left_vehicle_id
        form.driver_id.data = record.driver_id
        form.reason.data = record.reason
        form.leave_date.data = record.change_date
        form.remarks.data = record.remarks

    if form.validate_on_submit():
        record.reason = form.reason.data
        if form.reason.data == 'Other':
            record.reason = form.other_reason.data
        record.change_date = form.leave_date.data
        record.remarks = form.remarks.data
        record.driver_id = form.driver_id.data
        record.left_project_id = form.project_id.data
        record.left_district_id = form.district_id.data
        record.left_vehicle_id = form.vehicle_id.data
        
        db.session.commit()
        flash('Record updated successfully!', 'success')
        return redirect(url_for('driver_job_left_view', id=record.id))
        
    return render_template('driver_job_left_edit.html', record=record, form=form, **_workforce_nav_back())



@app.route('/driver-job-left/delete/<int:id>', methods=['POST'])
def driver_job_left_delete(id):
    record = DriverStatusChange.query.get_or_404(id)
    
    try:
        # Optionally Revert Driver Status back to Active
        driver = record.driver
        if driver:
            driver.status = 'Active'
            # Agar assignments wapas deni hain:
            # driver.project_id = record.left_project_id
            # driver.district_id = record.left_district_id
            # driver.vehicle_id = record.left_vehicle_id
            # driver.shift = record.left_shift
            
        db.session.delete(record)
        db.session.commit()
        flash('Job left record has been deleted and driver activated.', 'warning')
    except Exception as e:
        db.session.rollback()
        flash('Error deleting record.', 'danger')
        
    return redirect(url_for('driver_job_left_list'))



@app.route('/driver-job-left/export')
def driver_job_left_export():
    project_id = request.args.get('project_id', type=int) or 0
    district_id = request.args.get('district_id', type=int) or 0
    q = (request.args.get('q') or '').strip()
    
    query = DriverStatusChange.query.filter_by(action_type='left')
    if project_id:
        query = query.filter(DriverStatusChange.left_project_id == project_id)
    if district_id:
        query = query.filter(DriverStatusChange.left_district_id == district_id)
    if q:
        flt = _multi_word_filter(q, Driver.name, Driver.driver_id, Project.name, District.name, DriverStatusChange.reason, DriverStatusChange.remarks)
        if flt is not None:
            query = query.join(Driver).outerjoin(Project, DriverStatusChange.left_project_id == Project.id).outerjoin(
                District, DriverStatusChange.left_district_id == District.id
            ).filter(flt)
    
    records = query.order_by(DriverStatusChange.change_date.desc()).all()
    
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output)
    worksheet = workbook.add_worksheet('Driver Job Left')
    
    header_format = workbook.add_format({'bold': True, 'bg_color': '#dc3545', 'font_color': 'white', 'border': 1})
    cell_format = workbook.add_format({'border': 1, 'text_wrap': True})
    
    headers = ['Sr No', 'Exit Date', 'Driver Name', 'Driver ID', 'Project', 'District', 'Vehicle', 'Shift', 'Reason', 'Remarks']
    for col, header in enumerate(headers):
        worksheet.write(0, col, header, header_format)
    
    for idx, record in enumerate(records, start=1):
        worksheet.write(idx, 0, idx, cell_format)
        worksheet.write(idx, 1, record.change_date.strftime('%d %b, %Y') if record.change_date else '', cell_format)
        worksheet.write(idx, 2, record.driver.name if record.driver else '', cell_format)
        worksheet.write(idx, 3, record.driver.driver_id if record.driver else '', cell_format)
        worksheet.write(idx, 4, record.left_project.name if record.left_project else '-', cell_format)
        worksheet.write(idx, 5, record.left_district.name if record.left_district else '-', cell_format)
        worksheet.write(idx, 6, record.left_vehicle.vehicle_no if record.left_vehicle else '-', cell_format)
        worksheet.write(idx, 7, record.left_shift or '-', cell_format)
        worksheet.write(idx, 8, record.reason or '', cell_format)
        worksheet.write(idx, 9, record.remarks or '', cell_format)
    
    worksheet.set_column(0, 0, 8)
    worksheet.set_column(1, 1, 15)
    worksheet.set_column(2, 3, 18)
    worksheet.set_column(4, 7, 18)
    worksheet.set_column(8, 8, 15)
    worksheet.set_column(9, 9, 30)
    
    workbook.close()
    output.seek(0)
    
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'driver_job_left_{pk_now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    )



@app.route('/driver-job-left/print')
def driver_job_left_print():
    project_id = request.args.get('project_id', type=int) or 0
    district_id = request.args.get('district_id', type=int) or 0
    q = (request.args.get('q') or '').strip()
    
    query = DriverStatusChange.query.filter_by(action_type='left')
    if project_id:
        query = query.filter(DriverStatusChange.left_project_id == project_id)
    if district_id:
        query = query.filter(DriverStatusChange.left_district_id == district_id)
    if q:
        flt = _multi_word_filter(q, Driver.name, Driver.driver_id, Project.name, District.name, DriverStatusChange.reason, DriverStatusChange.remarks)
        if flt is not None:
            query = query.join(Driver).outerjoin(Project, DriverStatusChange.left_project_id == Project.id).outerjoin(
                District, DriverStatusChange.left_district_id == District.id
            ).filter(flt)
    
    records = query.order_by(DriverStatusChange.change_date.desc()).all()
    return render_template('driver_job_left_print.html', records=records, q=q, project_id=project_id, district_id=district_id)



@app.route('/driver/rejoin/list')
def driver_rejoin_list():
    from auth_utils import get_user_context
    
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)
    
    # Filters: date range, project, district, search
    search = (request.args.get('search') or '').strip()
    project_id = request.args.get('project_id', type=int) or 0
    district_id = request.args.get('district_id', type=int) or 0
    from_date_str = (request.args.get('from_date') or '').strip()
    to_date_str = (request.args.get('to_date') or '').strip()
    
    # Auto-select if only 1 option available
    disable_project = False
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

    from_date = None
    to_date = None
    try:
        if from_date_str:
            from_date = datetime.strptime(from_date_str, '%d-%m-%Y').date()
    except ValueError:
        from_date = None
    try:
        if to_date_str:
            to_date = datetime.strptime(to_date_str, '%d-%m-%Y').date()
    except ValueError:
        to_date = None

    query = DriverStatusChange.query.filter_by(action_type='rejoin') \
        .join(Driver, DriverStatusChange.driver_id == Driver.id) \
        .outerjoin(Project, DriverStatusChange.new_project_id == Project.id) \
        .outerjoin(Vehicle, DriverStatusChange.new_vehicle_id == Vehicle.id) \
        .outerjoin(District, DriverStatusChange.new_district_id == District.id)

    if project_id:
        query = query.filter(DriverStatusChange.new_project_id == project_id)
    if district_id:
        query = query.filter(DriverStatusChange.new_district_id == district_id)
    if from_date:
        query = query.filter(DriverStatusChange.change_date >= from_date)
    if to_date:
        query = query.filter(DriverStatusChange.change_date <= to_date)
    if search:
        flt = _multi_word_filter(search,
            Driver.name, Driver.driver_id,
            Project.name, District.name, Vehicle.vehicle_no)
        if flt is not None:
            query = query.filter(flt)

    rejoin_records = query.order_by(DriverStatusChange.change_date.desc()).all()

    # Filter dropdown choices by user scope
    project_q = Project.query
    if not is_master_or_admin and allowed_projects:
        project_q = project_q.filter(Project.id.in_(list(allowed_projects)))
    projects = [(0, '-- All Projects --')] + [(p.id, p.name) for p in project_q.order_by(Project.name).all()]
    
    district_q = District.query
    if not is_master_or_admin and allowed_districts:
        district_q = district_q.filter(District.id.in_(list(allowed_districts)))
    districts = [(0, '-- All Districts --')] + [(d.id, d.name) for d in district_q.order_by(District.name).all()]

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    pagination = SimplePagination(rejoin_records, page, per_page)
    rejoin_records = pagination.items
    return render_template(
        'driver_rejoin_list.html',
        records=rejoin_records,
        search=search,
        title="Driver Rejoin History",
        project_id=project_id,
        district_id=district_id,
        from_date=from_date_str,
        to_date=to_date_str,
        project_choices=projects,
        district_choices=districts,
        disable_project=disable_project,
        disable_district=disable_district,
        pagination=pagination,
        per_page=per_page,
    **_workforce_nav_back(),
    )



@app.route('/driver/rejoin/print')
def driver_rejoin_print():
    search = request.args.get('search', '').strip()
    query = DriverStatusChange.query.filter_by(action_type='rejoin') \
                         .join(Driver, DriverStatusChange.driver_id == Driver.id) \
                         .outerjoin(Project, DriverStatusChange.new_project_id == Project.id) \
                         .outerjoin(Vehicle, DriverStatusChange.new_vehicle_id == Vehicle.id)
    if search:
        flt = _multi_word_filter(search, Driver.name, Driver.driver_id, Project.name, Vehicle.vehicle_no)
        if flt is not None:
            query = query.filter(flt)
    records = query.order_by(DriverStatusChange.change_date.desc()).all()
    return render_template('driver_rejoin_print.html', records=records, search=search)



@app.route('/api/get_left_drivers_by_vehicle/<int:vid>')
def get_left_drivers_by_vehicle(vid):
    # Query: Wo drivers jinka status 'Left' hai 
    # Aur unka DriverStatusChange table mein aakhri record is Vehicle ID ka ho
    from sqlalchemy import func
    
    drivers = db.session.query(Driver).join(DriverStatusChange).filter(
        func.lower(Driver.status) == 'left',
        DriverStatusChange.left_vehicle_id == vid,
        DriverStatusChange.action_type == 'left'
    ).all()

    results = []
    for d in drivers:
        results.append({
            'id': d.id,
            'name': d.name,
            'driver_id': d.driver_id
        })
    return jsonify(results)



@app.route('/api/check_vehicle_shifts/<int:vid>')
def check_vehicle_shifts(vid):
    vehicle = Vehicle.query.get_or_404(vid)
    active_drivers = Driver.query.filter_by(vehicle_id=vid, status='Active').all()
    occupied_shifts = [d.shift for d in active_drivers if d.shift]
    
    return jsonify({
        'capacity': vehicle.driver_capacity or 1,
        'occupied_shifts': occupied_shifts
    })



@app.route('/driver_rejoin_view/<int:id>')
def driver_rejoin_view(id):
    """
    Yeh function driver ke rejoin hone ki report dikhayega.
    'id' woh unique ID hai jo rejoin hone ke waqt history table mein save hui thi.
    """
    # 1. Database se record dhoondo, agar nahi milta toh 404 error dikhao
    # 'DriverRejoin' ki jagah apne Model ka naam likhein agar mukhtalif hai
    record = DriverStatusChange.query.get_or_404(id)
    
    # 2. Record ko 'driver_rejoin_view.html' template par bhej do
    return render_template('driver_rejoin_view.html', record=record, **_workforce_nav_back())



@app.route('/leave-requests')
def leave_request_list():
    """List all leave requests with filters."""
    status_filter = request.args.get('status', '').strip()
    driver_id_filter = request.args.get('driver_id', type=int)
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    query = LeaveRequest.query.join(Driver, LeaveRequest.driver_id == Driver.id)
    if status_filter:
        query = query.filter(LeaveRequest.status == status_filter)
    if driver_id_filter:
        query = query.filter(LeaveRequest.driver_id == driver_id_filter)

    search = request.args.get('search', '').strip()
    if search:
        flt = _multi_word_filter(search, Driver.name, Driver.driver_id)
        if flt is not None:
            query = query.filter(flt)

    total = query.count()
    requests_list = query.order_by(LeaveRequest.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    total_pages = max(1, (total + per_page - 1) // per_page)

    counts = {
        'total': LeaveRequest.query.count(),
        'pending': LeaveRequest.query.filter_by(status='Pending').count(),
        'approved': LeaveRequest.query.filter_by(status='Approved').count(),
        'rejected': LeaveRequest.query.filter_by(status='Rejected').count(),
    }

    drivers = Driver.query.filter(Driver.status == 'Active', Driver.vehicle_id.isnot(None)).order_by(Driver.name).all()

    return render_template('leave_request_list.html',
        requests=requests_list, counts=counts, drivers=drivers,
        status_filter=status_filter, driver_id_filter=driver_id_filter,
        search=search, page=page, per_page=per_page,
        total=total, total_pages=total_pages,
        **_nav_back_ctx(url_for('driver_attendance_list'), show_without_nav_from=True),
    )



@app.route('/leave-requests/new', methods=['GET', 'POST'])
def leave_request_new():
    """Driver leave request form."""
    drivers = Driver.query.filter(Driver.status == 'Active', Driver.vehicle_id.isnot(None)).order_by(Driver.name).all()

    if request.method == 'POST':
        driver_id = request.form.get('driver_id', type=int)
        from_date_s = request.form.get('from_date', '').strip()
        to_date_s = request.form.get('to_date', '').strip()
        leave_type = request.form.get('leave_type', 'Leave').strip()
        reason = request.form.get('reason', '').strip()

        if not driver_id or not from_date_s or not to_date_s:
            flash('Driver, From Date aur To Date required hain.', 'danger')
            return redirect(url_for('leave_request_new'))

        from_d = parse_date(from_date_s)
        to_d = parse_date(to_date_s)
        if not from_d or not to_d:
            flash('Invalid date format. dd-mm-yyyy use karein.', 'danger')
            return redirect(url_for('leave_request_new'))
        if to_d < from_d:
            flash('To Date, From Date se pehle nahi ho sakti.', 'danger')
            return redirect(url_for('leave_request_new'))

        existing = LeaveRequest.query.filter(
            LeaveRequest.driver_id == driver_id,
            LeaveRequest.status.in_(['Pending', 'Approved']),
            LeaveRequest.from_date <= to_d,
            LeaveRequest.to_date >= from_d,
        ).first()
        if existing:
            flash(f'Is driver ki pehle se ek overlapping leave request hai ({existing.from_date.strftime("%d-%m-%Y")} to {existing.to_date.strftime("%d-%m-%Y")}, {existing.status}).', 'warning')
            return redirect(url_for('leave_request_new'))

        lr = LeaveRequest(
            driver_id=driver_id,
            from_date=from_d,
            to_date=to_d,
            leave_type=leave_type,
            reason=reason,
            status='Pending',
        )
        db.session.add(lr)
        db.session.commit()
        flash('Leave request submit ho gayi hai. Supervisor ke approval ka wait karein.', 'success')
        return redirect(url_for('leave_request_list'))

    return render_template('leave_request_form.html', drivers=drivers, **_nav_back_ctx(url_for('leave_request_list'), show_without_nav_from=True))



@app.route('/leave-requests/<int:req_id>/review', methods=['POST'])
def leave_request_review(req_id):
    """Approve or reject a leave request. If approved, auto-mark attendance."""
    lr = LeaveRequest.query.get_or_404(req_id)
    action = request.form.get('action', '').strip()
    review_remarks = request.form.get('review_remarks', '').strip()

    if action not in ('approve', 'reject'):
        flash('Invalid action.', 'danger')
        return redirect(url_for('leave_request_list'))

    if lr.status != 'Pending':
        flash('Ye request already reviewed hai.', 'warning')
        return redirect(url_for('leave_request_list'))

    lr.reviewed_by = session.get('user_id')
    lr.reviewed_at = pk_now()
    lr.review_remarks = review_remarks

    if action == 'approve':
        lr.status = 'Approved'
        _audit_user = session.get('user', '')
        cur_d = lr.from_date
        marked = 0
        while cur_d <= lr.to_date:
            any_ci_lr = (
                db.session.query(DriverAttendance.id)
                .filter(
                    DriverAttendance.driver_id == lr.driver_id,
                    DriverAttendance.attendance_date == cur_d,
                    DriverAttendance.check_in.isnot(None),
                )
                .first()
            )
            if any_ci_lr:
                cur_d += timedelta(days=1)
                continue
            rec = (
                DriverAttendance.query.filter_by(driver_id=lr.driver_id, attendance_date=cur_d)
                .order_by(DriverAttendance.attendance_segment.asc())
                .first()
            )
            remark = f'{lr.leave_type} (Leave Request #{lr.id}) [approved by {_audit_user}]'
            if rec:
                rec.status = lr.leave_type
                rec.remarks = remark
                rec.updated_at = pk_now()
            else:
                rec = DriverAttendance(
                    driver_id=lr.driver_id,
                    attendance_date=cur_d,
                    status=lr.leave_type,
                    project_id=lr.driver.project_id if lr.driver else None,
                    remarks=remark,
                )
                db.session.add(rec)
            marked += 1
            cur_d += timedelta(days=1)
        db.session.commit()
        flash(f'Leave request approved. {marked} din ka {lr.leave_type} mark kar diya.', 'success')
    else:
        lr.status = 'Rejected'
        db.session.commit()
        flash('Leave request rejected.', 'info')

    return redirect(url_for('leave_request_list'))


