"""
Transfer routes - Project transfers, Vehicle transfers, Driver transfers.

Extracted from routes.py to reduce file size.
Includes list, new, edit, delete, export, print routes for all three transfer types,
plus helper API endpoints for getting current vehicle/driver info and available shifts.
"""
from flask import (
    render_template, redirect, url_for, flash, request,
    session, send_file, jsonify,
)
from sqlalchemy import func, cast
from sqlalchemy import String as SAString

from app import app, db
from models import (
    Company, Project, Vehicle, Driver, ParkingStation, District,
    ProjectTransfer, VehicleTransfer, DriverTransfer,
    DriverStatusChange,
    project_district,
)
from forms import (
    ProjectTransferForm, VehicleTransferForm, EditVehicleTransferForm,
    DriverTransferForm,
)
from vehicle_sort_utils import vehicle_order_by
from utils import pk_now, pk_date

# Import shared helpers from routes.py
from routes import (
    _multi_word_filter,
    _transfers_nav_back,
)

# Transfer Section - Project
import datetime
import io
import xlsxwriter
from models import DriverAttendance
@app.route('/project-transfers')
def project_transfers():
    from auth_utils import get_user_context
    
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)
    
    search = request.args.get('search', '').strip()
    sort_by = request.args.get('sort_by', 'transfer_date')
    sort_order = request.args.get('sort_order', 'desc')
    
    query = ProjectTransfer.query
    
    # Apply user data scope
    if not is_master_or_admin and allowed_projects:
        query = query.filter(ProjectTransfer.project_id.in_(list(allowed_projects)))
    
    if search:
        flt = _multi_word_filter(search, Project.name, Company.name, ProjectTransfer.remarks)
        if flt is not None:
            query = query.join(Project).join(Company, ProjectTransfer.new_company_id == Company.id).filter(flt)
    
    # Apply sorting
    if sort_by == 'project':
        query = query.join(Project)
        order_col = Project.name
    elif sort_by == 'company':
        query = query.join(Company, ProjectTransfer.new_company_id == Company.id)
        order_col = Company.name
    elif sort_by == 'transfer_date':
        order_col = ProjectTransfer.transfer_date
    else:
        order_col = ProjectTransfer.transfer_date
    
    if sort_order == 'asc':
        query = query.order_by(order_col.asc())
    else:
        query = query.order_by(order_col.desc())
    
    transfers = query.all()
    return render_template('project_transfers.html', transfers=transfers, search=search, sort_by=sort_by, sort_order=sort_order, **_transfers_nav_back())

@app.route('/project-transfer/new', methods=['GET', 'POST'])
def project_transfer_new():
    form = ProjectTransferForm()
    projects = Project.query.filter(Project.company_id.isnot(None)).order_by(Project.name).all()
    form.project_id.choices = [(0, '-- Select Project --')] + [
        (p.id, f"{p.name} (Current: {p.company.name if p.company else 'Unassigned'})")
        for p in projects
    ]
    form.new_company_id.choices = [(0, '-- Select Transfer to Company --')] + [(c.id, c.name) for c in Company.query.order_by(Company.name).all()]

    if form.validate_on_submit():
        if not form.project_id.data or form.project_id.data == 0:
            flash('Please select a project.', 'danger')
            return render_template('project_transfer_new.html', form=form, **_transfers_nav_back())
        if not form.new_company_id.data or form.new_company_id.data == 0:
            flash('Please select transfer to company.', 'danger')
            return render_template('project_transfer_new.html', form=form, **_transfers_nav_back())
        try:
            project = Project.query.get_or_404(form.project_id.data)
            new_company = Company.query.get_or_404(form.new_company_id.data)
            if project.company_id == new_company.id:
                flash(f'Project already belongs to "{new_company.name}".', 'info')
                return redirect(url_for('project_transfer_new'))
            old_company = project.company
            old_company_name = old_company.name if old_company else 'Unassigned'
            
            transfer = ProjectTransfer(
                project_id=project.id,
                old_company_id=project.company_id,
                new_company_id=new_company.id,
                transfer_date=form.transfer_date.data,
                remarks=form.remarks.data
            )
            project.company_id = new_company.id
            project.assign_date = form.transfer_date.data
            project.assign_remarks = form.remarks.data
            db.session.add(transfer)
            db.session.commit()
            flash(f'Project "{project.name}" transferred from "{old_company_name}" to "{new_company.name}".', 'success')
            return redirect(url_for('project_transfers'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error during transfer: {str(e)}', 'danger')

    return render_template('project_transfer_new.html', form=form, **_transfers_nav_back())

@app.route('/project-transfer/edit/<int:id>', methods=['GET', 'POST'])
def project_transfer_edit(id):
    transfer = ProjectTransfer.query.get_or_404(id)
    form = ProjectTransferForm(obj=transfer)
    form.project_id.choices = [(0, '-- Select Project --')] + [(p.id, p.name) for p in Project.query.order_by(Project.name).all()]
    form.new_company_id.choices = [(0, '-- Select Transfer to Company --')] + [(c.id, c.name) for c in Company.query.order_by(Company.name).all()]
    if form.validate_on_submit():
        transfer.project_id = form.project_id.data
        transfer.new_company_id = form.new_company_id.data
        transfer.transfer_date = form.transfer_date.data
        transfer.remarks = form.remarks.data
        db.session.commit()
        flash('Transfer updated successfully!', 'success')
        return redirect(url_for('project_transfers'))
    return render_template('project_transfer_edit.html', form=form, transfer=transfer, **_transfers_nav_back())

@app.route('/project-transfer/delete/<int:id>', methods=['POST'])
def project_transfer_delete(id):
    transfer_record = ProjectTransfer.query.get_or_404(id)
    try:
        db.session.delete(transfer_record)
        db.session.commit()
        flash('Transfer record permanently deleted.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting record: {str(e)}', 'danger')
    return redirect(url_for('project_transfers'))

@app.route('/project-transfers/export')
def project_transfers_export():
    search = request.args.get('search', '').strip()
    query = ProjectTransfer.query
    
    if search:
        flt = _multi_word_filter(search, Project.name, Company.name, ProjectTransfer.remarks)
        if flt is not None:
            query = query.join(Project).join(Company, ProjectTransfer.new_company_id == Company.id).filter(flt)
    
    transfers = query.order_by(ProjectTransfer.transfer_date.desc()).all()
    
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output)
    worksheet = workbook.add_worksheet('Project Transfers')
    
    header_format = workbook.add_format({'bold': True, 'bg_color': '#ff5722', 'font_color': 'white', 'border': 1})
    cell_format = workbook.add_format({'border': 1, 'text_wrap': True})
    
    headers = ['Sr No', 'Project Name', 'Old Company', 'New Company', 'Transfer Date', 'Remarks']
    for col, header in enumerate(headers):
        worksheet.write(0, col, header, header_format)
    
    for idx, t in enumerate(transfers, start=1):
        worksheet.write(idx, 0, idx, cell_format)
        worksheet.write(idx, 1, t.project.name if t.project else '', cell_format)
        worksheet.write(idx, 2, t.old_company.name if t.old_company else 'Initial', cell_format)
        worksheet.write(idx, 3, t.new_company.name if t.new_company else '', cell_format)
        worksheet.write(idx, 4, t.transfer_date.strftime('%d %b, %Y') if t.transfer_date else '', cell_format)
        worksheet.write(idx, 5, t.remarks or '', cell_format)
    
    worksheet.set_column(0, 0, 8)
    worksheet.set_column(1, 1, 30)
    worksheet.set_column(2, 3, 25)
    worksheet.set_column(4, 4, 15)
    worksheet.set_column(5, 5, 30)
    
    workbook.close()
    output.seek(0)
    
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'project_transfers_{pk_now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    )

@app.route('/project-transfers/print')
def project_transfers_print():
    search = request.args.get('search', '').strip()
    query = ProjectTransfer.query
    
    if search:
        flt = _multi_word_filter(search, Project.name, Company.name, ProjectTransfer.remarks)
        if flt is not None:
            query = query.join(Project).join(Company, ProjectTransfer.new_company_id == Company.id).filter(flt)
    
    transfers = query.order_by(ProjectTransfer.transfer_date.desc()).all()
    return render_template('project_transfers_print.html', transfers=transfers, search=search)

# ==========================================
# VEHICLE TRANSFER ROUTES
# ==========================================

@app.route('/vehicle-transfers')
def vehicle_transfers():
    from auth_utils import get_user_context
    
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)
    
    # Optional filters (destination side): Project + District
    project_id = request.args.get('project_id', type=int) or 0
    district_id = request.args.get('district_id', type=int) or 0
    q = (request.args.get('q') or '').strip()
    sort_by = request.args.get('sort_by', 'transfer_date')
    sort_order = request.args.get('sort_order', 'desc')
    
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

    query = VehicleTransfer.query
    
    # Apply user data scope
    if not is_master_or_admin:
        if allowed_projects:
            query = query.filter(VehicleTransfer.new_project_id.in_(list(allowed_projects)))
        if allowed_districts:
            query = query.filter(VehicleTransfer.new_district_id.in_(list(allowed_districts)))
        if allowed_vehicles:
            query = query.filter(VehicleTransfer.vehicle_id.in_(list(allowed_vehicles)))
    
    if project_id:
        query = query.filter(VehicleTransfer.new_project_id == project_id)
    if district_id:
        query = query.filter(VehicleTransfer.new_district_id == district_id)
    if q:
        query = query.join(Vehicle) \
                     .outerjoin(Project,  VehicleTransfer.new_project_id  == Project.id) \
                     .outerjoin(District, VehicleTransfer.new_district_id == District.id)
        flt = _multi_word_filter(q,
            Vehicle.vehicle_no, Project.name, District.name,
            VehicleTransfer.remarks, cast(VehicleTransfer.transfer_date, SAString))
        if flt is not None:
            query = query.filter(flt)

    # Apply sorting
    if sort_by == 'vehicle':
        query = query.join(Vehicle)
        order_col = Vehicle.vehicle_no
    elif sort_by == 'project':
        query = query.join(Project, VehicleTransfer.new_project_id == Project.id)
        order_col = Project.name
    elif sort_by == 'district':
        query = query.join(District, VehicleTransfer.new_district_id == District.id)
        order_col = District.name
    elif sort_by == 'transfer_date':
        order_col = VehicleTransfer.transfer_date
    else:
        order_col = VehicleTransfer.transfer_date
    
    if sort_order == 'asc':
        query = query.order_by(order_col.asc())
    else:
        query = query.order_by(order_col.desc())

    page     = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    transfers  = pagination.items

    # Filter dropdown choices by user scope
    project_q = Project.query
    if not is_master_or_admin and allowed_projects:
        project_q = project_q.filter(Project.id.in_(list(allowed_projects)))
    projects = [(0, '-- All Projects --')] + [(p.id, p.name) for p in project_q.order_by(Project.name).all()]
    
    district_q = District.query
    if not is_master_or_admin and allowed_districts:
        district_q = district_q.filter(District.id.in_(list(allowed_districts)))
    districts = [(0, '-- All Districts --')] + [(d.id, d.name) for d in district_q.order_by(District.name).all()]
    
    return render_template(
        'vehicle_transfers.html',
        transfers=transfers,
        pagination=pagination,
        per_page=per_page,
        project_id=project_id,
        district_id=district_id,
        q=q,
        sort_by=sort_by,
        sort_order=sort_order,
        project_choices=projects,
        district_choices=districts,
        disable_project=disable_project,
        disable_district=disable_district,
    **_transfers_nav_back(),
    )

@app.route('/vehicle-transfer/new', methods=['GET', 'POST'])
def vehicle_transfer_new():
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)
    
    form = VehicleTransferForm()
    proj_q = Project.query.order_by(Project.name)
    if not is_master_or_admin and allowed_projects:
        proj_q = proj_q.filter(Project.id.in_(list(allowed_projects)))
    all_projects = [(p.id, p.name) for p in proj_q.all()]
    form.from_project_id.choices = [(0, '-- Select From Project --')] + all_projects
    form.new_project_id.choices = [(0, '-- Select New Project --')] + all_projects
    
    # Auto-select if only 1 project/district allowed
    disable_from_project = False
    disable_new_project = False
    if not is_master_or_admin and len(allowed_projects) == 1:
        single_proj = next(iter(allowed_projects))
        if not form.from_project_id.data or form.from_project_id.data == 0:
            form.from_project_id.data = single_proj
        if not form.new_project_id.data or form.new_project_id.data == 0:
            form.new_project_id.data = single_proj
        disable_from_project = True
        disable_new_project = True

    if request.method == 'POST':
        form.from_district_id.choices = [(int(request.form.get('from_district_id') or 0), '')]
        form.vehicle_id.choices = [(int(request.form.get('vehicle_id') or 0), '')]
        form.new_district_id.choices = [(int(request.form.get('new_district_id') or 0), '')]
        form.new_parking_id.choices = [(int(request.form.get('new_parking_id') or 0), '')]

    if form.validate_on_submit():
        try:
            vehicle = Vehicle.query.get_or_404(form.vehicle_id.data)
            old_p_id = vehicle.project_id
            old_d_id = vehicle.district_id
            old_park_id = vehicle.parking_station_id
            
            new_p_id = form.new_project_id.data
            new_d_id = form.new_district_id.data
            new_park_id = form.new_parking_id.data

            if old_p_id == new_p_id and old_d_id == new_d_id and old_park_id == new_park_id:
                flash("Cannot transfer! The vehicle is already at this exact Location.", "danger")
                return redirect(url_for('vehicle_transfer_new'))

            if new_park_id:
                parking = db.session.get(ParkingStation, new_park_id)
                occupied = Vehicle.query.filter_by(parking_station_id=new_park_id).count()
                if occupied >= parking.capacity:
                    flash(f"Transfer Failed! '{parking.name}' is FULL.", "danger")
                    return redirect(url_for('vehicle_transfer_new'))

            drivers_freed = 0
            if old_p_id != new_p_id or old_d_id != new_d_id:
                attached_drivers = Driver.query.filter_by(vehicle_id=vehicle.id).all()
                for d in attached_drivers:
                    d.vehicle_id = None
                    d.shift = None
                    drivers_freed += 1
            
            transfer = VehicleTransfer(
                vehicle_id=vehicle.id,
                old_project_id=old_p_id, old_district_id=old_d_id, old_parking_id=old_park_id,
                new_project_id=new_p_id, new_district_id=new_d_id, new_parking_id=new_park_id,
                transfer_date=form.transfer_date.data,
                remarks=form.remarks.data
            )
            
            vehicle.project_id = new_p_id
            vehicle.district_id = new_d_id
            vehicle.parking_station_id = new_park_id

            db.session.add(transfer)
            db.session.commit()

            msg = f"Vehicle {vehicle.vehicle_no} transferred successfully."
            if drivers_freed > 0:
                msg += f" {drivers_freed} driver(s) were unassigned."
                flash(msg, 'warning')
            else:
                flash(msg, 'success')

            return redirect(url_for('vehicle_transfers'))

        except Exception as e:
            db.session.rollback()
            flash(f"Error: {str(e)}", "danger")

    if not form.from_district_id.choices: form.from_district_id.choices = [(0, '-- Select District --')]
    if not form.vehicle_id.choices: form.vehicle_id.choices = [(0, '-- Select Vehicle --')]
    if not form.new_district_id.choices: form.new_district_id.choices = [(0, '-- Select District --')]
    if not form.new_parking_id.choices: form.new_parking_id.choices = [(0, '-- Select Parking --')]

    return render_template('vehicle_transfer_new.html', form=form, disable_from_project=disable_from_project, disable_new_project=disable_new_project, **_transfers_nav_back())

@app.route('/vehicle-transfer/edit/<int:id>', methods=['GET', 'POST'])
def vehicle_transfer_edit(id):
    transfer = VehicleTransfer.query.get_or_404(id)
    vehicle = transfer.vehicle
    form = EditVehicleTransferForm()

    form.new_project_id.choices = [(0, '-- Select Project --')] + [(p.id, p.name) for p in Project.query.order_by(Project.name).all()]

    pid = form.new_project_id.data if request.method == 'POST' else transfer.new_project_id
    did = form.new_district_id.data if request.method == 'POST' else transfer.new_district_id
    
    if pid and pid != 0:
        proj = db.session.get(Project, pid)
        form.new_district_id.choices = [(0, '-- Select District --')] + [(d.id, d.name) for d in proj.districts]
    else:
        form.new_district_id.choices = [(0, '-- Select District --')]

    if did and did != 0:
        dist = db.session.get(District, did)
        stations = ParkingStation.query.filter_by(district=dist.name).all()
        form.new_parking_id.choices = [(0, '-- Select Parking --')] + [(s.id, s.name) for s in stations]
    else:
        form.new_parking_id.choices = [(0, '-- Select Parking --')]

    if request.method == 'GET':
        form.new_project_id.data = transfer.new_project_id
        form.new_district_id.data = transfer.new_district_id
        form.new_parking_id.data = transfer.new_parking_id if transfer.new_parking_id else 0
        form.transfer_date.data = transfer.transfer_date
        form.remarks.data = transfer.remarks

    if form.validate_on_submit():
        new_park_id = form.new_parking_id.data
        
        if new_park_id and new_park_id != transfer.new_parking_id:
            parking = db.session.get(ParkingStation, new_park_id)
            occupied = Vehicle.query.filter(Vehicle.parking_station_id == new_park_id, Vehicle.id != vehicle.id).count()
            if occupied >= parking.capacity:
                flash(f"Cannot update! '{parking.name}' is FULL.", "danger")
                return render_template('vehicle_transfer_edit.html', form=form, transfer=transfer, **_transfers_nav_back())

        try:
            transfer.new_project_id = form.new_project_id.data
            transfer.new_district_id = form.new_district_id.data
            transfer.new_parking_id = new_park_id
            transfer.transfer_date = form.transfer_date.data
            transfer.remarks = form.remarks.data
            
            vehicle.project_id = form.new_project_id.data
            vehicle.district_id = form.new_district_id.data
            vehicle.parking_station_id = new_park_id

            db.session.commit()
            flash("Transfer record updated successfully.", "success")
            return redirect(url_for('vehicle_transfers'))
        except Exception as e:
            db.session.rollback()
            flash(f"Error: {str(e)}", "danger")

    return render_template('vehicle_transfer_edit.html', form=form, transfer=transfer, **_transfers_nav_back())

@app.route('/vehicle-transfer/delete/<int:id>', methods=['POST'])
def vehicle_transfer_delete(id):
    transfer_record = VehicleTransfer.query.get_or_404(id)
    try:
        # Pehle check karein ke is vehicle ke sath koi driver assigned tu nahi
        vehicle = transfer_record.vehicle
        if vehicle:
            assigned_driver = Driver.query.filter_by(vehicle_id=vehicle.id).first()
            if assigned_driver:
                flash(
                    f"Cannot delete transfer log. Driver '{assigned_driver.name}' (ID: {assigned_driver.driver_id}) is currently assigned to vehicle {vehicle.vehicle_no}. "
                    "Please free/unassign the driver first.",
                    'danger'
                )
                return redirect(url_for('vehicle_transfers'))

            # Revert vehicle back to old (From) project, district and parking before deleting transfer
            vehicle.project_id = transfer_record.old_project_id
            vehicle.district_id = transfer_record.old_district_id
            vehicle.parking_station_id = transfer_record.old_parking_id

        db.session.delete(transfer_record)
        db.session.commit()
        flash('Transfer record deleted. Vehicle reverted to previous project, district and parking.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting record: {str(e)}', 'danger')
    return redirect(url_for('vehicle_transfers'))

@app.route('/vehicle-transfers/export')
def vehicle_transfers_export():
    project_id = request.args.get('project_id', type=int) or 0
    district_id = request.args.get('district_id', type=int) or 0
    q = (request.args.get('q') or '').strip()
    
    query = VehicleTransfer.query
    if project_id:
        query = query.filter(VehicleTransfer.new_project_id == project_id)
    if district_id:
        query = query.filter(VehicleTransfer.new_district_id == district_id)
    if q:
        query = query.join(Vehicle) \
                     .outerjoin(Project,  VehicleTransfer.new_project_id  == Project.id) \
                     .outerjoin(District, VehicleTransfer.new_district_id == District.id)
        flt = _multi_word_filter(q,
            Vehicle.vehicle_no, Project.name, District.name,
            VehicleTransfer.remarks, cast(VehicleTransfer.transfer_date, SAString))
        if flt is not None:
            query = query.filter(flt)

    transfers = query.order_by(VehicleTransfer.transfer_date.desc()).all()

    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output)
    worksheet = workbook.add_worksheet('Vehicle Transfers')
    
    header_format = workbook.add_format({'bold': True, 'bg_color': '#00bcd4', 'font_color': 'white', 'border': 1})
    cell_format = workbook.add_format({'border': 1, 'text_wrap': True})
    
    headers = ['Sr No', 'Vehicle No', 'Old Project', 'Old District', 'Old Parking', 'New Project', 'New District', 'New Parking', 'Transfer Date', 'Remarks']
    for col, header in enumerate(headers):
        worksheet.write(0, col, header, header_format)
    
    for idx, t in enumerate(transfers, start=1):
        worksheet.write(idx, 0, idx, cell_format)
        worksheet.write(idx, 1, t.vehicle.vehicle_no if t.vehicle else '', cell_format)
        worksheet.write(idx, 2, t.old_project.name if t.old_project else '-', cell_format)
        worksheet.write(idx, 3, t.old_district.name if t.old_district else '-', cell_format)
        worksheet.write(idx, 4, t.old_parking.name if t.old_parking else 'Free', cell_format)
        worksheet.write(idx, 5, t.new_project.name if t.new_project else '-', cell_format)
        worksheet.write(idx, 6, t.new_district.name if t.new_district else '-', cell_format)
        worksheet.write(idx, 7, t.new_parking.name if t.new_parking else 'Free', cell_format)
        worksheet.write(idx, 8, t.transfer_date.strftime('%d %b, %Y') if t.transfer_date else '', cell_format)
        worksheet.write(idx, 9, t.remarks or '', cell_format)
    
    worksheet.set_column(0, 0, 8)
    worksheet.set_column(1, 1, 15)
    worksheet.set_column(2, 7, 20)
    worksheet.set_column(8, 8, 15)
    worksheet.set_column(9, 9, 30)
    
    workbook.close()
    output.seek(0)
    
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'vehicle_transfers_{pk_now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    )

@app.route('/vehicle-transfers/print')
def vehicle_transfers_print():
    project_id = request.args.get('project_id', type=int) or 0
    district_id = request.args.get('district_id', type=int) or 0
    q = (request.args.get('q') or '').strip()
    
    query = VehicleTransfer.query
    if project_id:
        query = query.filter(VehicleTransfer.new_project_id == project_id)
    if district_id:
        query = query.filter(VehicleTransfer.new_district_id == district_id)
    if q:
        flt = _multi_word_filter(q, Vehicle.vehicle_no, Project.name, District.name, VehicleTransfer.remarks, cast(VehicleTransfer.transfer_date, SAString))
        if flt is not None:
            query = query.join(Vehicle).outerjoin(Project, VehicleTransfer.new_project_id == Project.id).outerjoin(
                District, VehicleTransfer.new_district_id == District.id
            ).filter(flt)
    
    transfers = query.order_by(VehicleTransfer.transfer_date.desc()).all()
    return render_template('vehicle_transfers_print.html', transfers=transfers, q=q, project_id=project_id, district_id=district_id)

@app.route('/get_vehicle_current_info/<int:vehicle_id>')
def get_vehicle_current_info(vehicle_id):
    v = db.session.get(Vehicle, vehicle_id)
    if not v:
        return jsonify({"parking_name": "Not Found"})
    if v.parking_station:
        return jsonify({"parking_name": v.parking_station.name})
    else:
        return jsonify({"parking_name": "No Parking Assigned (Free)"})

# ==========================================
# DRIVER TRANSFER ROUTES & APIs
# ==========================================

@app.route('/get_assigned_drivers/<int:project_id>')
def get_assigned_drivers(project_id):
    if project_id == 0:
        drivers = Driver.query.filter(Driver.vehicle_id.isnot(None)).all()
    else:
        drivers = Driver.query.filter(Driver.vehicle_id.isnot(None), Driver.project_id == project_id).all()
    return jsonify([{"id": d.id, "name": f"{d.name} ({d.driver_id})"} for d in drivers])

@app.route('/get_driver_current_info/<int:driver_id>')
def get_driver_current_info(driver_id):
    d = db.session.get(Driver, driver_id)
    if not d or not d.vehicle:
        return jsonify({"info": "Not Assigned", "shift": None, "vehicle_id": None, "capacity": 1, "partner": None})
    cap = d.vehicle.driver_capacity or 1
    cur_shift = (d.shift or '').strip()
    partner = None
    if cap >= 2:
        p = Driver.query.filter(
            Driver.vehicle_id == d.vehicle_id, Driver.id != d.id,
            Driver.status == 'Active'
        ).first()
        if p:
            partner = {"id": p.id, "name": p.name, "shift": (p.shift or '').strip()}
    return jsonify({
        "info": f"{d.vehicle.vehicle_no} ({cur_shift} Shift)" if cur_shift else f"{d.vehicle.vehicle_no}",
        "shift": cur_shift,
        "vehicle_id": d.vehicle_id,
        "vehicle_no": d.vehicle.vehicle_no if d.vehicle else '',
        "capacity": cap,
        "partner": partner,
    })

@app.route('/get_available_shifts/<int:vehicle_id>')
def get_available_shifts(vehicle_id):
    v = db.session.get(Vehicle, vehicle_id)
    if not v: return jsonify([])
    
    cap = v.driver_capacity or 1
    driver_id_to_exclude = request.args.get('exclude_driver_id', type=int)
    
    query = Driver.query.filter_by(vehicle_id=v.id)
    if driver_id_to_exclude:
        query = query.filter(Driver.id != driver_id_to_exclude)
        
    existing_shifts = [(d.shift or '').strip().title() for d in query.all()]
    
    shifts = []
    if cap == 1:
        if "Morning" not in existing_shifts:
            shifts.append({"id": "Morning", "name": "Morning"})
    else:
        if "Morning" not in existing_shifts:
            shifts.append({"id": "Morning", "name": "Morning"})
        if "Night" not in existing_shifts:
            shifts.append({"id": "Night", "name": "Night"})
        
    return jsonify(shifts)

@app.route('/driver-transfers')
def driver_transfers():
    from auth_utils import get_user_context
    
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)
    
    # Optional filters: Project + District (destination side)
    project_id   = request.args.get('project_id', type=int) or 0
    district_id  = request.args.get('district_id', type=int) or 0
    q            = (request.args.get('q') or '').strip()
    sort_by      = request.args.get('sort_by', 'transfer_date')
    sort_order   = request.args.get('sort_order', 'desc')
    from_date_str = (request.args.get('from_date') or '').strip()
    to_date_str   = (request.args.get('to_date') or '').strip()
    from_date_val = None
    to_date_val   = None
    try:
        if from_date_str:
            from_date_val = datetime.strptime(from_date_str, '%d-%m-%Y').date()
    except ValueError:
        from_date_str = ''
    try:
        if to_date_str:
            to_date_val = datetime.strptime(to_date_str, '%d-%m-%Y').date()
    except ValueError:
        to_date_str = ''
    
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

    query = DriverTransfer.query
    joined_vehicle = False
    joined_driver  = False

    # Apply user data scope
    if not is_master_or_admin:
        if allowed_vehicles:
            query = query.filter(DriverTransfer.new_vehicle_id.in_(list(allowed_vehicles)))

    if project_id:
        query = query.filter(DriverTransfer.new_project_id == project_id)
    if district_id:
        query = query.join(Vehicle, DriverTransfer.new_vehicle_id == Vehicle.id).filter(
            Vehicle.district_id == district_id
        )
        joined_vehicle = True
    if from_date_val:
        query = query.filter(DriverTransfer.transfer_date >= from_date_val)
    if to_date_val:
        query = query.filter(DriverTransfer.transfer_date <= to_date_val)
    if q:
        if not joined_driver:
            query = query.join(Driver)
            joined_driver = True
        if not joined_vehicle:
            query = query.join(Vehicle, DriverTransfer.new_vehicle_id == Vehicle.id)
            joined_vehicle = True
        query = query.outerjoin(Project,  DriverTransfer.new_project_id == Project.id) \
                     .outerjoin(District, Vehicle.district_id            == District.id)
        flt = _multi_word_filter(q,
            Driver.name, Driver.driver_id,
            Vehicle.vehicle_no, Project.name, District.name,
            DriverTransfer.remarks, cast(DriverTransfer.transfer_date, SAString))
        if flt is not None:
            query = query.filter(flt)

    # Apply sorting (avoid duplicate joins)
    if sort_by == 'driver':
        if not joined_driver:
            query = query.join(Driver)
        order_col = Driver.name
    elif sort_by == 'vehicle':
        if not joined_vehicle:
            query = query.join(Vehicle, DriverTransfer.new_vehicle_id == Vehicle.id)
        order_col = Vehicle.vehicle_no
    elif sort_by == 'project':
        query = query.join(Project, DriverTransfer.new_project_id == Project.id)
        order_col = Project.name
    elif sort_by == 'transfer_date':
        order_col = DriverTransfer.transfer_date
    else:
        order_col = DriverTransfer.transfer_date
    
    if sort_order == 'asc':
        query = query.order_by(order_col.asc())
    else:
        query = query.order_by(order_col.desc())

    page     = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    transfers  = pagination.items

    # Filter dropdown choices by user scope
    project_q = Project.query
    if not is_master_or_admin and allowed_projects:
        project_q = project_q.filter(Project.id.in_(list(allowed_projects)))
    projects = [(0, '-- All Projects --')] + [(p.id, p.name) for p in project_q.order_by(Project.name).all()]
    
    district_q = District.query
    if not is_master_or_admin and allowed_districts:
        district_q = district_q.filter(District.id.in_(list(allowed_districts)))
    districts = [(0, '-- All Districts --')] + [(d.id, d.name) for d in district_q.order_by(District.name).all()]
    
    return render_template(
        'driver_transfers.html',
        transfers=transfers,
        pagination=pagination,
        per_page=per_page,
        project_id=project_id,
        district_id=district_id,
        sort_by=sort_by,
        sort_order=sort_order,
        q=q,
        from_date=from_date_str,
        to_date=to_date_str,
        project_choices=projects,
        district_choices=districts,
        disable_project=disable_project,
        disable_district=disable_district,
    **_transfers_nav_back(),
    )

@app.route('/driver-transfer/new', methods=['GET', 'POST'])
def driver_transfer_new():
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)

    form = DriverTransferForm()

    proj_q = Project.query.order_by(Project.name)
    if not is_master_or_admin and allowed_projects:
        proj_q = proj_q.filter(Project.id.in_(list(allowed_projects)))
    all_projects = [(p.id, p.name) for p in proj_q.all()]
    form.from_project_id.choices = [(0, '-- Select Project --')] + all_projects
    form.new_project_id.choices = [(0, '-- Select Project --')] + all_projects

    # Auto-select if only 1 project allowed
    disable_from_project = False
    disable_new_project = False
    if not is_master_or_admin and len(allowed_projects) == 1:
        single_proj = next(iter(allowed_projects))
        if not form.from_project_id.data or form.from_project_id.data == 0:
            form.from_project_id.data = single_proj
        if not form.new_project_id.data or form.new_project_id.data == 0:
            form.new_project_id.data = single_proj
        disable_from_project = True
        disable_new_project = True

    form.new_shift.choices = [
        ('', '-- Select Shift --'),
        ('Morning', 'Morning'),
        ('Night', 'Night')
    ]

    form.from_district_id.choices = [(0, '-- Select Project first --')]
    form.from_vehicle_id.choices  = [(0, '-- Select District first --')]
    form.driver_id.choices        = [(0, '-- Select Vehicle first --')]
    form.new_district_id.choices  = [(0, '-- Select Project first --')]
    form.new_vehicle_id.choices   = [(0, '-- Select District first --')]

    if request.method == 'POST':
        # Dynamically populate choices based on selections (for validation & UX)
        if form.from_project_id.data and form.from_project_id.data != 0:
            districts = District.query.join(project_district).filter(
                project_district.c.project_id == form.from_project_id.data
            ).order_by(District.name).all()
            form.from_district_id.choices = [(0, '-- Select District --')] + [(d.id, d.name) for d in districts]

            if form.from_district_id.data and form.from_district_id.data != 0:
                vehicles = Vehicle.query.filter_by(
                    project_id=form.from_project_id.data, district_id=form.from_district_id.data
                ).order_by(*vehicle_order_by()).all()
                form.from_vehicle_id.choices = [(0, '-- Select Vehicle --')] + [(v.id, v.vehicle_no) for v in vehicles]

                if form.from_vehicle_id.data and form.from_vehicle_id.data != 0:
                    drivers = Driver.query.filter_by(vehicle_id=form.from_vehicle_id.data).order_by(Driver.name).all()
                    form.driver_id.choices = [(0, '-- Select Driver --')] + [(d.id, f"{d.name} ({d.driver_id})") for d in drivers]

        if form.new_project_id.data and form.new_project_id.data != 0:
            districts = District.query.join(project_district).filter(
                project_district.c.project_id == form.new_project_id.data
            ).order_by(District.name).all()
            form.new_district_id.choices = [(0, '-- Select District --')] + [(d.id, d.name) for d in districts]

            if form.new_district_id.data and form.new_district_id.data != 0:
                vehicles = Vehicle.query.filter_by(
                    project_id=form.new_project_id.data, district_id=form.new_district_id.data
                ).order_by(*vehicle_order_by()).all()
                form.new_vehicle_id.choices = [(0, '-- Select Vehicle --')] + [(v.id, v.vehicle_no) for v in vehicles]

    is_shift_only = request.form.get('is_shift_only') == '1'

    if is_shift_only and request.method == 'POST':
        driver_id_val = request.form.get('driver_id', type=int) or 0
        transfer_date_raw = (request.form.get('transfer_date') or '').strip()
        remarks_val = (request.form.get('remarks') or '').strip()

        if driver_id_val and transfer_date_raw:
            _drv = db.session.get(Driver, driver_id_val)
            if _drv and _drv.shift:
                new_shift_val = 'Night' if _drv.shift.strip().lower() == 'morning' else 'Morning'
            else:
                new_shift_val = (request.form.get('new_shift') or '').strip()
        else:
            new_shift_val = (request.form.get('new_shift') or '').strip()
        if driver_id_val and new_shift_val and transfer_date_raw:
            try:
                from datetime import datetime as _dt
                t_date = _dt.strptime(transfer_date_raw, '%d-%m-%Y').date()
                if t_date > pk_date():
                    flash('Transfer date cannot be in the future.', 'danger')
                    return render_template('driver_transfer_new.html', form=form, disable_from_project=disable_from_project, disable_new_project=disable_new_project, **_transfers_nav_back())

                driver = Driver.query.get_or_404(driver_id_val)
                target_vehicle = driver.vehicle
                if not target_vehicle:
                    flash("Driver is not assigned to any vehicle.", "danger")
                    return render_template('driver_transfer_new.html', form=form, disable_from_project=disable_from_project, disable_new_project=disable_new_project, **_transfers_nav_back())

                if (target_vehicle.driver_capacity or 1) < 2:
                    flash(f"Vehicle {target_vehicle.vehicle_no} has capacity 1 — shift change is not applicable.", "danger")
                    return render_template('driver_transfer_new.html', form=form, disable_from_project=disable_from_project, disable_new_project=disable_new_project, **_transfers_nav_back())

                if driver.shift == new_shift_val:
                    flash(f"Driver '{driver.name}' is already on {new_shift_val} shift.", "warning")
                    return render_template('driver_transfer_new.html', form=form, disable_from_project=disable_from_project, disable_new_project=disable_new_project, **_transfers_nav_back())

                other_driver = Driver.query.filter(
                    Driver.vehicle_id == target_vehicle.id,
                    Driver.id != driver.id,
                    Driver.shift == new_shift_val,
                ).first()

                old_shift = driver.shift
                transfer1 = DriverTransfer(
                    driver_id=driver.id,
                    old_project_id=driver.project_id,
                    old_vehicle_id=driver.vehicle_id,
                    old_shift=old_shift,
                    old_district_id=driver.district_id,
                    new_project_id=driver.project_id,
                    new_vehicle_id=driver.vehicle_id,
                    new_shift=new_shift_val,
                    new_district_id=driver.district_id,
                    transfer_date=t_date,
                    is_shift_only=True,
                    remarks=remarks_val or f'Shift changed from {old_shift} to {new_shift_val}'
                )
                db.session.add(transfer1)
                driver.shift = new_shift_val

                if other_driver:
                    transfer2 = DriverTransfer(
                        driver_id=other_driver.id,
                        old_project_id=other_driver.project_id,
                        old_vehicle_id=other_driver.vehicle_id,
                        old_shift=other_driver.shift,
                        old_district_id=other_driver.district_id,
                        new_project_id=other_driver.project_id,
                        new_vehicle_id=other_driver.vehicle_id,
                        new_shift=old_shift,
                        new_district_id=other_driver.district_id,
                        transfer_date=t_date,
                        is_shift_only=True,
                        remarks=f'Auto-swapped: shift changed from {other_driver.shift} to {old_shift} (swap with {driver.name})'
                    )
                    db.session.add(transfer2)
                    other_driver.shift = old_shift
                    db.session.commit()
                    flash(f"Shifts swapped: '{driver.name}' → {new_shift_val}, '{other_driver.name}' → {old_shift}.", "success")
                else:
                    db.session.commit()
                    flash(f"Driver '{driver.name}' shift changed to '{new_shift_val}' successfully.", "success")

                return redirect(url_for('driver_transfers'))

            except Exception as e:
                db.session.rollback()
                flash(f"Error: {str(e)}", "danger")
        else:
            flash("Please select Driver, New Shift and Date.", "danger")

        return render_template('driver_transfer_new.html', form=form, disable_from_project=disable_from_project, disable_new_project=disable_new_project, **_transfers_nav_back())

    if form.validate_on_submit():
        try:
            driver = Driver.query.get_or_404(form.driver_id.data)
            new_vehicle = Vehicle.query.get_or_404(form.new_vehicle_id.data)

            existing_count = Driver.query.filter(
                Driver.vehicle_id == new_vehicle.id,
                Driver.id != driver.id
            ).count()

            if existing_count >= (new_vehicle.driver_capacity or 1):
                flash(f"Vehicle {new_vehicle.vehicle_no} is full (capacity reached).", "danger")
                return render_template('driver_transfer_new.html', form=form, disable_from_project=disable_from_project, disable_new_project=disable_new_project, **_transfers_nav_back())

            shift_taken = Driver.query.filter(
                Driver.vehicle_id == new_vehicle.id,
                Driver.shift == form.new_shift.data,
                Driver.id != driver.id
            ).first()

            if shift_taken:
                flash(f"Shift '{form.new_shift.data}' already assigned in vehicle {new_vehicle.vehicle_no}.", "danger")
                return render_template('driver_transfer_new.html', form=form, disable_from_project=disable_from_project, disable_new_project=disable_new_project, **_transfers_nav_back())

            transfer = DriverTransfer(
                driver_id=driver.id,
                old_project_id=driver.project_id,
                old_vehicle_id=driver.vehicle_id,
                old_shift=driver.shift,
                old_district_id=driver.district_id,
                new_project_id=form.new_project_id.data,
                new_vehicle_id=new_vehicle.id,
                new_shift=form.new_shift.data,
                new_district_id=form.new_district_id.data,
                transfer_date=form.transfer_date.data,
                remarks=form.remarks.data
            )
            db.session.add(transfer)

            driver.project_id = form.new_project_id.data
            driver.district_id = form.new_district_id.data
            driver.vehicle_id = new_vehicle.id
            driver.shift = form.new_shift.data

            db.session.commit()

            flash(f"Driver '{driver.name}' successfully transferred to vehicle '{new_vehicle.vehicle_no}'.", "success")
            return redirect(url_for('driver_transfers'))

        except Exception as e:
            db.session.rollback()
            flash(f"Error: {str(e)}", "danger")

    return render_template('driver_transfer_new.html', form=form, disable_from_project=disable_from_project, disable_new_project=disable_new_project, **_transfers_nav_back())

@app.route('/driver-transfer/delete/<int:id>', methods=['POST'])
def driver_transfer_delete(id):
    transfer = DriverTransfer.query.get_or_404(id)
    driver = transfer.driver

    if not driver:
        flash("Associated driver record not found.", "danger")
        return redirect(url_for('driver_transfers'))

    # NEW RULE: Before delete, ensure driver has no attendance on the NEW vehicle
    # on or after this transfer's effective date.
    try:
        conflict_attendance = DriverAttendance.query.filter(
            DriverAttendance.driver_id == driver.id,
            DriverAttendance.attendance_date >= transfer.transfer_date,
            DriverAttendance.project_id == transfer.new_project_id
        ).first()

        if conflict_attendance:
            flash(
                "This transfer record cannot be deleted because the driver has already performed duty on the new assignment "
                "on or after the effective date.",
                "danger"
            )
            return redirect(url_for('driver_transfers'))
    except Exception:
        # In case of any unexpected error during safety check, just block deletion
        flash(
            "Unable to delete this transfer record because the system detected existing duty records for this driver.",
            "danger"
        )
        return redirect(url_for('driver_transfers'))

    try:
        # Revert driver to OLD values from this transfer
        driver.project_id = transfer.old_project_id
        driver.vehicle_id = transfer.old_vehicle_id
        driver.shift = transfer.old_shift
        driver.district_id = transfer.old_district_id

        # Optional: string district field revert (agar use kar rahe ho)
        # if transfer.old_district:
        #     driver.driver_district = transfer.old_district.name
        # else:
        #     driver.driver_district = None

        db.session.delete(transfer)
        db.session.commit()

        flash("Transfer record deleted. Driver reverted to previous assignment.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting transfer: {str(e)}", "danger")

    return redirect(url_for('driver_transfers'))

@app.route('/driver-transfers/export')
def driver_transfers_export():
    project_id = request.args.get('project_id', type=int) or 0
    district_id = request.args.get('district_id', type=int) or 0
    q = (request.args.get('q') or '').strip()
    
    query = DriverTransfer.query
    if project_id:
        query = query.filter(DriverTransfer.new_project_id == project_id)
    if district_id:
        query = query.join(Vehicle, DriverTransfer.new_vehicle_id == Vehicle.id).filter(
            Vehicle.district_id == district_id
        )
    if q:
        flt = _multi_word_filter(q, Driver.name, Driver.driver_id, Vehicle.vehicle_no, Project.name, District.name, DriverTransfer.remarks, cast(DriverTransfer.transfer_date, SAString))
        if flt is not None:
            query = query.join(Driver).join(Vehicle, DriverTransfer.new_vehicle_id == Vehicle.id).outerjoin(
                Project, DriverTransfer.new_project_id == Project.id
            ).outerjoin(
                District, Vehicle.district_id == District.id
            ).filter(flt)
    
    transfers = query.order_by(DriverTransfer.transfer_date.desc()).all()
    
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output)
    worksheet = workbook.add_worksheet('Driver Transfers')
    
    header_format = workbook.add_format({'bold': True, 'bg_color': '#9c27b0', 'font_color': 'white', 'border': 1})
    cell_format = workbook.add_format({'border': 1, 'text_wrap': True})
    
    headers = ['Sr No', 'Type', 'Driver Name', 'Driver ID', 'Old Project', 'Old District', 'Old Vehicle', 'Old Shift', 'New Project', 'New District', 'New Vehicle', 'New Shift', 'Transfer Date', 'Remarks']
    for col, header in enumerate(headers):
        worksheet.write(0, col, header, header_format)
    
    for idx, t in enumerate(transfers, start=1):
        worksheet.write(idx, 0, idx, cell_format)
        worksheet.write(idx, 1, 'Shift Change' if t.is_shift_only else 'Transfer', cell_format)
        worksheet.write(idx, 2, t.driver.name if t.driver else '', cell_format)
        worksheet.write(idx, 3, t.driver.driver_id if t.driver else '', cell_format)
        worksheet.write(idx, 4, t.old_project.name if t.old_project else 'Initial', cell_format)
        worksheet.write(idx, 5, t.old_vehicle.district.name if t.old_vehicle and t.old_vehicle.district else '-', cell_format)
        worksheet.write(idx, 6, t.old_vehicle.vehicle_no if t.old_vehicle else '-', cell_format)
        worksheet.write(idx, 7, t.old_shift or '-', cell_format)
        worksheet.write(idx, 8, t.new_project.name if t.new_project else '-', cell_format)
        worksheet.write(idx, 9, t.new_vehicle.district.name if t.new_vehicle and t.new_vehicle.district else '-', cell_format)
        worksheet.write(idx, 10, t.new_vehicle.vehicle_no if t.new_vehicle else '-', cell_format)
        worksheet.write(idx, 11, t.new_shift or '-', cell_format)
        worksheet.write(idx, 12, t.transfer_date.strftime('%d %b, %Y') if t.transfer_date else '', cell_format)
        worksheet.write(idx, 13, t.remarks or '', cell_format)
    
    worksheet.set_column(0, 0, 8)
    worksheet.set_column(1, 1, 14)
    worksheet.set_column(2, 3, 15)
    worksheet.set_column(4, 11, 18)
    worksheet.set_column(12, 12, 15)
    worksheet.set_column(13, 13, 30)
    
    workbook.close()
    output.seek(0)
    
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'driver_transfers_{pk_now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    )

@app.route('/driver-transfers/print')
def driver_transfers_print():
    project_id = request.args.get('project_id', type=int) or 0
    district_id = request.args.get('district_id', type=int) or 0
    q = (request.args.get('q') or '').strip()
    
    query = DriverTransfer.query
    if project_id:
        query = query.filter(DriverTransfer.new_project_id == project_id)
    if district_id:
        query = query.join(Vehicle, DriverTransfer.new_vehicle_id == Vehicle.id).filter(
            Vehicle.district_id == district_id
        )
    if q:
        flt = _multi_word_filter(q, Driver.name, Driver.driver_id, Vehicle.vehicle_no, Project.name, District.name, DriverTransfer.remarks, cast(DriverTransfer.transfer_date, SAString))
        if flt is not None:
            query = query.join(Driver).join(Vehicle, DriverTransfer.new_vehicle_id == Vehicle.id).outerjoin(
                Project, DriverTransfer.new_project_id == Project.id
            ).outerjoin(
                District, Vehicle.district_id == District.id
            ).filter(flt)
    
    transfers = query.order_by(DriverTransfer.transfer_date.desc()).all()
    return render_template('driver_transfers_print.html', transfers=transfers, q=q, project_id=project_id, district_id=district_id)

