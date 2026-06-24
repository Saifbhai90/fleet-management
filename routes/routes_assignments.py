"""
Assignment routes - Project-Company, Project-District, Vehicle-District,
Vehicle-Parking, Driver-Vehicle assignments.

Extracted from routes.py to reduce file size.
Includes list, new, edit, delete, export, print routes for all assignment types,
plus helper API endpoints for dropdowns and driver details.
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
    project_district,
)
from forms import (
    AssignProjectToCompanyForm, EditProjectAssignmentForm,
    AssignProjectToDistrictForm, AssignVehicleToDistrictForm,
    AssignVehicleToParkingForm, AssignDriverToVehicleForm,
)
from vehicle_sort_utils import vehicle_order_by
from utils import (
    generate_csv_response, pk_now, pk_date, parse_date,
)

# parse_date_dmy is used in the parking assignment code;
# it's the same as parse_date (accepts dd-mm-yyyy or yyyy-mm-dd).
parse_date_dmy = parse_date

# Import shared helpers from routes.py
from routes import (
    _multi_word_filter,
    _assignments_nav_back,
    _nav_back_ctx,
    SimplePagination,
    _get_user_scope,
    _preserve_nav_from,
)

from sqlalchemy import or_
from utils import generate_excel_template
@app.route('/project/<int:id>/export_vehicles')
def export_vehicles(id):
    project = Project.query.get_or_404(id)
    headers = ['ID', 'Vehicle No#', 'Model', 'Engine No', 'Chassis No', 'Vehicle Type', 'Phone No', 'Active Date']
    rows = []
    for v in project.vehicles:
        rows.append([
            v.id, v.vehicle_no, v.model, v.engine_no, v.chassis_no,
            v.vehicle_type, v.phone_no,
            v.active_date.strftime('%Y-%m-%d') if v.active_date else ''
        ])
    return generate_csv_response(headers, rows, f"vehicles_project_{id}.csv")


# ────────────────────────────────────────────────
# Assignment: Project → Company
# ────────────────────────────────────────────────
def _assign_project_to_company_data(search=None, sort_by='assign_date', sort_order='desc'):
    """Query assigned projects (optionally filtered by search). Returns list of Project."""
    q = Project.query.filter(Project.company_id.isnot(None))
    if search:
        flt = _multi_word_filter(search, Project.name, Company.name)
        if flt is not None:
            q = q.outerjoin(Company, Project.company_id == Company.id).filter(flt)
    
    # Apply sorting - database level for performance
    if sort_by == 'project':
        order_col = Project.name
    elif sort_by == 'company':
        q = q.join(Company, Project.company_id == Company.id)
        order_col = Company.name
    elif sort_by == 'assign_date':
        order_col = Project.assign_date
    else:
        order_col = Project.assign_date
    
    if sort_order == 'asc':
        q = q.order_by(order_col.asc())
    else:
        q = q.order_by(order_col.desc())
    
    return q.all()


@app.route('/assign_project_to_company')
def assign_project_to_company():
    from auth_utils import get_user_context

    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)

    search = request.args.get('search', '').strip()
    from_date_str = request.args.get('from_date', '').strip()
    to_date_str = request.args.get('to_date', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    sort_by = request.args.get('sort_by', 'assign_date')
    sort_order = request.args.get('sort_order', 'desc')

    def _dmy(s):
        from datetime import datetime as _dt
        try: return _dt.strptime(s, '%d-%m-%Y').date() if s else None
        except ValueError: return None

    from_date = _dmy(from_date_str)
    to_date = _dmy(to_date_str)

    q = Project.query.filter(Project.company_id.isnot(None))
    if search:
        q = q.outerjoin(Company, Project.company_id == Company.id)
        flt = _multi_word_filter(search, Project.name, Company.name)
        if flt is not None:
            q = q.filter(flt)
    if from_date:
        q = q.filter(Project.assign_date >= from_date)
    if to_date:
        q = q.filter(Project.assign_date <= to_date)
    if not is_master_or_admin and allowed_projects:
        q = q.filter(Project.id.in_(list(allowed_projects)))

    if sort_by == 'project':
        order_col = Project.name
    elif sort_by == 'company':
        q = q.join(Company, Project.company_id == Company.id)
        order_col = Company.name
    else:
        order_col = Project.assign_date
    q = q.order_by(order_col.asc() if sort_order == 'asc' else order_col.desc())

    pagination = q.paginate(page=page, per_page=per_page, error_out=False)
    assigned_projects = pagination.items

    project_ids_with_districts = set(
        r[0] for r in db.session.query(project_district.c.project_id).distinct().all()
    )
    return render_template(
        'assign_project_to_company.html',
        assigned_projects=assigned_projects,
        search=search,
        from_date=from_date_str,
        to_date=to_date_str,
        sort_by=sort_by,
        sort_order=sort_order,
        pagination=pagination,
        per_page=per_page,
        project_ids_with_districts=project_ids_with_districts,
        **_assignments_nav_back(),
    )


@app.route('/assign_project_to_company/export')
def assign_project_to_company_export():
    search = request.args.get('search', '').strip()
    assigned_projects = _assign_project_to_company_data(search)
    headers = ['Project Name', 'Project ID', 'Company', 'Assign Date', 'Remarks']
    rows = []
    for proj in assigned_projects:
        rows.append([
            proj.name or '',
            proj.id,
            proj.company.name if proj.company else '',
            proj.assign_date.strftime('%Y-%m-%d') if proj.assign_date else '-',
            (proj.assign_remarks or '').replace('\r\n', ' ').replace('\n', ' ')
        ])
    filename = 'project_company_assignments.xlsx' if not search else f'project_company_assignments_{search[:30].replace("/", "-")}.xlsx'
    return generate_excel_template(headers, rows, required_columns=[], filename=filename)


@app.route('/assign_project_to_company/print')
def assign_project_to_company_print():
    search = request.args.get('search', '').strip()
    assigned_projects = _assign_project_to_company_data(search)
    return render_template(
        'assign_project_to_company_print.html',
        assigned_projects=assigned_projects,
        search=search
    )


@app.route('/assign_project_to_company/new', methods=['GET', 'POST'])
def assign_project_to_company_new():
    form = AssignProjectToCompanyForm()
    form.company_id.choices = [(0, '-- Select Company --')] + [
        (c.id, c.name) for c in Company.query.order_by(Company.name).all()
    ]
    form.project_id.choices = [(0, '-- Select Project --')] + [
        (p.id, p.name) for p in Project.query.filter(Project.company_id.is_(None)).order_by(Project.name).all()
    ]
    if request.method == 'GET':
        form.company_id.data = 0
        form.project_id.data = 0
    if form.validate_on_submit():
        try:
            company = Company.query.get_or_404(form.company_id.data)
            project = Project.query.get_or_404(form.project_id.data)
            if project.company_id:
                flash(f'Project "{project.name}" already assigned.', 'warning')
            else:
                project.company_id = company.id
                project.assign_date = form.assign_date.data
                project.assign_remarks = form.assign_remarks.data
                db.session.commit()
                flash(f'Project "{project.name}" assigned to "{company.name}".', 'success')
                return redirect(url_for('assign_project_to_company', **_preserve_nav_from()))
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {str(e)}', 'danger')
    return render_template('assign_project_to_company_new.html', form=form,
                           **_nav_back_ctx(url_for('assign_project_to_company')))


@app.route('/assign_project_to_company/edit/<int:project_id>', methods=['GET', 'POST'])
def assign_project_to_company_edit(project_id):
    old_project = Project.query.get_or_404(project_id)
    # Lock edit if project has districts linked
    if db.session.query(project_district.c.project_id).filter_by(project_id=project_id).first():
        flash(
            f'Cannot edit: Project "{old_project.name}" is linked to district(s). '
            'Remove district assignment first (Assignment → District → Project).',
            'danger'
        )
        return redirect(url_for('assign_project_to_company', **_preserve_nav_from()))
    form = EditProjectAssignmentForm()
    form.company_id.choices = [(c.id, c.name) for c in Company.query.order_by(Company.name).all()]
    available_projects = Project.query.filter((Project.company_id == None) | (Project.id == project_id)).all()
    form.project_id.choices = [(p.id, p.name) for p in available_projects]
    
    if request.method == 'GET':
        form.company_id.data = old_project.company_id
        form.project_id.data = old_project.id
        form.assign_date.data = old_project.assign_date
        form.assign_remarks.data = old_project.assign_remarks
    
    if form.validate_on_submit():
        try:
            new_project_id = int(form.project_id.data)
            if new_project_id != old_project.id:
                new_project = db.session.get(Project, new_project_id)
                new_project.company_id = form.company_id.data
                new_project.assign_date = form.assign_date.data
                new_project.assign_remarks = form.assign_remarks.data
                old_project.company_id = None
                old_project.assign_date = None
                old_project.assign_remarks = None
            else:
                old_project.company_id = form.company_id.data
                old_project.assign_date = form.assign_date.data
                old_project.assign_remarks = form.assign_remarks.data
            
            db.session.commit()
            flash('Assignment updated successfully.', 'success')
            return redirect(url_for('assign_project_to_company', **_preserve_nav_from()))
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {str(e)}', 'danger')
    return render_template('assign_project_to_company_edit.html', form=form, project=old_project,
                           **_nav_back_ctx(url_for('assign_project_to_company')))


@app.route('/assign_project_to_company/desassign/<int:project_id>', methods=['POST'])
def desassign_project_from_company(project_id):
    project = Project.query.get_or_404(project_id)
    if not project.company_id:
        flash("This project is not assigned to any company.", 'info')
        return redirect(url_for('assign_project_to_company', **_preserve_nav_from()))
    # Block deassign if project is linked to any district
    if project.districts.count() > 0:
        district_names = ', '.join(d.name for d in project.districts.all())
        flash(
            f'Cannot deassign: Project "{project.name}" is linked to district(s): {district_names}. '
            'Remove district assignment first (Assignment → District → Project).',
            'danger'
        )
        return redirect(url_for('assign_project_to_company', **_preserve_nav_from()))
    try:
        company_name = project.company.name if project.company else 'N/A'
        project.company_id = None
        project.assign_date = None
        project.assign_remarks = None
        db.session.commit()
        flash(f'Project "{project.name}" successfully desassigned from "{company_name}".', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error desassigning project: {str(e)}', 'danger')
    return redirect(url_for('assign_project_to_company', **_preserve_nav_from()))


# ────────────────────────────────────────────────
# Assignment: Project → District
# ────────────────────────────────────────────────
@app.route('/assign_project_to_district')
def assign_project_to_district():
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
    sort_by = request.args.get('sort_by', 'project')
    sort_order = request.args.get('sort_order', 'asc')
    project_id = request.args.get('project_id', type=int)
    district_id = request.args.get('district_id', type=int)

    def _dmy(s):
        from datetime import datetime as _dt
        try: return _dt.strptime(s, '%d-%m-%Y').date() if s else None
        except ValueError: return None

    from_date = _dmy(from_date_str)
    to_date = _dmy(to_date_str)

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

    all_assigned = _assign_project_to_district_data(search=search, project_id=project_id, district_id=district_id)

    # Apply user data scope
    if not is_master_or_admin and (allowed_projects or allowed_districts):
        all_assigned = [
            (link_data, proj, dist) for link_data, proj, dist in all_assigned
            if (not allowed_projects or proj.id in allowed_projects) and
               (not allowed_districts or dist.id in allowed_districts)
        ]

    # Apply date range filter
    if from_date:
        all_assigned = [(l, p, d) for l, p, d in all_assigned
                        if l.get('assign_date') and l['assign_date'] >= from_date]
    if to_date:
        all_assigned = [(l, p, d) for l, p, d in all_assigned
                        if l.get('assign_date') and l['assign_date'] <= to_date]

    # Apply sort
    from datetime import date as _date_type
    _rev = sort_order == 'desc'
    if sort_by == 'district':
        all_assigned.sort(key=lambda x: (x[2].name or '').lower(), reverse=_rev)
    elif sort_by == 'assign_date':
        all_assigned.sort(key=lambda x: x[0].get('assign_date') or _date_type.min, reverse=_rev)
    else:
        all_assigned.sort(key=lambda x: (x[1].name or '').lower(), reverse=_rev)

    # Manual pagination
    total = len(all_assigned)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    assigned_page = all_assigned[start:start + per_page]

    class _Pagination:
        def __init__(self):
            self.page = page
            self.per_page = per_page
            self.total = total
            self.pages = total_pages
            self.has_prev = page > 1
            self.has_next = page < total_pages
            self.prev_num = page - 1
            self.next_num = page + 1
            self.items = assigned_page
        def iter_pages(self, left_edge=1, right_edge=1, left_current=2, right_current=2):
            last = 0
            for num in range(1, self.pages + 1):
                if (num <= left_edge or
                        self.page - left_current - 1 < num < self.page + right_current or
                        num > self.pages - right_edge):
                    if last + 1 != num:
                        yield None
                    yield num
                    last = num

    pagination = _Pagination()

    # Filter dropdown choices by user scope
    project_q = Project.query.filter(Project.company_id.isnot(None))
    if not is_master_or_admin and allowed_projects:
        project_q = project_q.filter(Project.id.in_(list(allowed_projects)))
    projects = [(0, '-- All Projects --')] + [(p.id, p.name) for p in project_q.order_by(Project.name).all()]

    district_q = District.query
    if not is_master_or_admin and allowed_districts:
        district_q = district_q.filter(District.id.in_(list(allowed_districts)))
    districts = [(0, '-- All Districts --')] + [(d.id, d.name) for d in district_q.order_by(District.name).all()]
    return render_template(
        'assign_project_to_district.html',
        assigned=assigned_page,
        search=search,
        from_date=from_date_str,
        to_date=to_date_str,
        project_id=project_id or 0,
        district_id=district_id or 0,
        project_choices=projects,
        district_choices=districts,
        disable_project=disable_project,
        disable_district=disable_district,
        pagination=pagination,
        per_page=per_page,
        sort_by=sort_by,
        sort_order=sort_order,
        **_assignments_nav_back(),
    )


def _assign_project_to_district_data(search=None, project_id=None, district_id=None):
    """Shared query for list, print, export. Optional filter by project_id and/or district_id."""
    query = db.session.query(
        Project, District, project_district.c.assign_date, project_district.c.remarks
    ).join(project_district, Project.id == project_district.c.project_id).join(
        District, District.id == project_district.c.district_id
    )
    if project_id:
        query = query.filter(Project.id == project_id)
    if district_id:
        query = query.filter(District.id == district_id)
    if search:
        flt = _multi_word_filter(search,
            Project.name, District.name,
            project_district.c.remarks,
            cast(project_district.c.assign_date, SAString))
        if flt is not None:
            query = query.filter(flt)
    results = query.order_by(Project.name).all()
    assigned_structured = []
    for proj, dist, a_date, a_remarks in results:
        assigned_structured.append(({'assign_date': a_date, 'remarks': a_remarks}, proj, dist))
    return assigned_structured


@app.route('/assign_project_to_district/export')
def assign_project_to_district_export():
    search = request.args.get('search', '').strip()
    project_id = request.args.get('project_id', type=int)
    district_id = request.args.get('district_id', type=int)
    assigned_structured = _assign_project_to_district_data(search=search, project_id=project_id, district_id=district_id)
    headers = ['Project Name', 'District Name', 'Assign Date', 'Remarks']
    rows = []
    for link_data, proj, dist in assigned_structured:
        rows.append([
            proj.name or '',
            dist.name or '',
            link_data['assign_date'].strftime('%Y-%m-%d') if link_data.get('assign_date') else '-',
            link_data.get('remarks') or '-'
        ])
    filename = 'project_district_assignments.xlsx' if not search else f'project_district_assignments_{search[:30].replace("/", "-")}.xlsx'
    return generate_excel_template(headers, rows, required_columns=[], filename=filename)


@app.route('/assign_project_to_district/print')
def assign_project_to_district_print():
    search = request.args.get('search', '').strip()
    project_id = request.args.get('project_id', type=int)
    district_id = request.args.get('district_id', type=int)
    assigned_structured = _assign_project_to_district_data(search=search, project_id=project_id, district_id=district_id)
    return render_template('assign_project_to_district_print.html', assigned=assigned_structured, search=search)


@app.route('/get_unassigned_districts_by_project/<int:project_id>')
def get_unassigned_districts_by_project(project_id):
    """Districts that are NOT yet assigned to this project (for District-to-Project form)."""
    assigned_ids = [r[0] for r in db.session.query(project_district.c.district_id).filter_by(project_id=project_id).all()]
    if not assigned_ids:
        districts = District.query.order_by(District.name).all()
    else:
        districts = District.query.filter(~District.id.in_(assigned_ids)).order_by(District.name).all()
    return jsonify([{"id": d.id, "name": d.name} for d in districts])


@app.route('/assign_project_to_district/new', methods=['GET', 'POST'])
def assign_project_to_district_new():
    form = AssignProjectToDistrictForm()
    form.project_id.choices = [(0, '-- Select Project --')] + [
        (p.id, p.name) for p in Project.query.filter(Project.company_id.isnot(None)).order_by(Project.name).all()
    ]
    # District choices: only placeholder on GET; on POST with errors, fill with unassigned districts for selected project
    form.district_id.choices = [(0, '-- Select District --')]
    if request.method == 'GET':
        form.project_id.data = 0
        form.district_id.data = 0
    elif request.method == 'POST' and form.project_id.data and form.project_id.data != 0:
        # Repopulate district dropdown: only districts NOT linked to this project
        assigned_ids = [r[0] for r in db.session.query(project_district.c.district_id).filter_by(project_id=form.project_id.data).all()]
        if not assigned_ids:
            unassigned = District.query.order_by(District.name).all()
        else:
            unassigned = District.query.filter(~District.id.in_(assigned_ids)).order_by(District.name).all()
        form.district_id.choices = [(0, '-- Select District --')] + [(d.id, d.name) for d in unassigned]
    if form.validate_on_submit():
        try:
            project = Project.query.get_or_404(form.project_id.data)
            district = District.query.get_or_404(form.district_id.data)
            exists = db.session.query(project_district).filter_by(
                project_id=project.id, district_id=district.id
            ).first()
            if exists:
                flash(f'District "{district.name}" already assigned to "{project.name}".', 'warning')
            else:
                db.session.execute(
                    project_district.insert().values(
                        project_id=project.id,
                        district_id=district.id,
                        assign_date=form.assign_date.data,
                        remarks=form.remarks.data
                    )
                )
                db.session.commit()
                flash(f'District "{district.name}" assigned to "{project.name}".', 'success')
                return redirect(url_for('assign_project_to_district', **_preserve_nav_from()))
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {str(e)}', 'danger')
    return render_template('assign_project_to_district_new.html', form=form,
                           **_nav_back_ctx(url_for('assign_project_to_district')))


@app.route('/assign_project_to_district/edit/<int:project_id>/<int:district_id>', methods=['GET', 'POST'])
def assign_project_to_district_edit(project_id, district_id):
    link = db.session.query(project_district).filter_by(project_id=project_id, district_id=district_id).first()
    if not link:
        flash("Assignment not found.", 'danger')
        return redirect(url_for('assign_project_to_district', **_preserve_nav_from()))
    project = Project.query.get_or_404(project_id)
    district = District.query.get_or_404(district_id)
    form = AssignProjectToDistrictForm()
    form.project_id.choices = [(p.id, p.name) for p in Project.query.all()]
    form.district_id.choices = [(d.id, d.name) for d in District.query.all()]
    if request.method == 'GET':
        form.project_id.data = project_id
        form.district_id.data = district_id
        form.assign_date.data = link.assign_date
        form.remarks.data = link.remarks
    if form.validate_on_submit():
        try:
            db.session.execute(
                project_district.update().where(
                    project_district.c.project_id == project_id,
                    project_district.c.district_id == district_id
                ).values(
                    assign_date=form.assign_date.data,
                    remarks=form.remarks.data
                )
            )
            db.session.commit()
            flash("Assignment updated successfully!", "success")
            return redirect(url_for('assign_project_to_district', **_preserve_nav_from()))
        except Exception as e:
            db.session.rollback()
            flash(f"Error: {str(e)}", "danger")
    return render_template('assign_project_to_district_edit.html', form=form, project=project, district=district,
                           **_nav_back_ctx(url_for('assign_project_to_district')))


@app.route('/assign_project_to_district/desassign/<int:project_id>/<int:district_id>', methods=['POST'])
def desassign_district_from_project(project_id, district_id):
    district = District.query.get_or_404(district_id)
    # Block deassign if district is linked to any vehicle
    linked_vehicles = Vehicle.query.filter(Vehicle.district_id == district_id).all()
    if linked_vehicles:
        vehicle_nos = ', '.join(v.vehicle_no for v in linked_vehicles[:10])
        if len(linked_vehicles) > 10:
            vehicle_nos += f' and {len(linked_vehicles) - 10} more'
        flash(
            f'Cannot deassign: District "{district.name}" is linked to vehicle(s): {vehicle_nos}. '
            'Remove vehicle assignment first (Assignment → Vehicle → District).',
            'danger'
        )
        return redirect(url_for('assign_project_to_district', **_preserve_nav_from()))
    try:
        db.session.execute(
            project_district.delete().where(
                project_district.c.project_id == project_id,
                project_district.c.district_id == district_id
            )
        )
        db.session.commit()
        flash('District successfully desassigned from project.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error desassigning: {str(e)}', 'danger')
    return redirect(url_for('assign_project_to_district', **_preserve_nav_from()))


# ────────────────────────────────────────────────
# Assignment: Vehicle → District
# ────────────────────────────────────────────────
def _assign_vehicle_to_district_data(search=None, project_id=None, district_id=None, sort_by='assign_date', sort_order='desc'):
    """Query assigned vehicles (optionally filtered by search, project_id, district_id). Returns list of Vehicle."""
    query = Vehicle.query.filter(Vehicle.district_id.isnot(None))
    if project_id:
        query = query.filter(Vehicle.project_id == project_id)
    if district_id:
        query = query.filter(Vehicle.district_id == district_id)
    if search:
        query = query.outerjoin(Project,  Vehicle.project_id  == Project.id) \
                     .outerjoin(District, Vehicle.district_id == District.id)
        flt = _multi_word_filter(search, Vehicle.vehicle_no, Vehicle.model, Project.name, District.name)
        if flt is not None:
            query = query.filter(flt)
    
    # Apply sorting - database level for performance
    if sort_by == 'vehicle':
        order_col = Vehicle.vehicle_no
    elif sort_by == 'project':
        query = query.join(Project, Vehicle.project_id == Project.id)
        order_col = Project.name
    elif sort_by == 'district':
        query = query.join(District, Vehicle.district_id == District.id)
        order_col = District.name
    elif sort_by == 'assign_date':
        order_col = Vehicle.assign_to_district_date
    else:
        order_col = Vehicle.assign_to_district_date
    
    if sort_order == 'asc':
        query = query.order_by(order_col.asc())
    else:
        query = query.order_by(order_col.desc())
    
    return query.all()


@app.route('/assign_vehicle_to_district')
def assign_vehicle_to_district():
    from auth_utils import get_user_context
    
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)
    
    search = request.args.get('search', '').strip()
    project_id = request.args.get('project_id', type=int)
    district_id = request.args.get('district_id', type=int)
    sort_by = request.args.get('sort_by', 'assign_date')
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
    
    assigned = _assign_vehicle_to_district_data(search=search, project_id=project_id, district_id=district_id, sort_by=sort_by, sort_order=sort_order)
    
    # Apply user data scope to assigned vehicles
    if not is_master_or_admin:
        if allowed_projects or allowed_districts or allowed_vehicles:
            assigned = [
                v for v in assigned
                if (not allowed_projects or (v.project_id and v.project_id in allowed_projects)) and
                   (not allowed_districts or (v.district_id and v.district_id in allowed_districts)) and
                   (not allowed_vehicles or v.id in allowed_vehicles)
            ]
    
    # Filter dropdown choices by user scope
    project_q = Project.query.filter(Project.company_id.isnot(None))
    if not is_master_or_admin and allowed_projects:
        project_q = project_q.filter(Project.id.in_(list(allowed_projects)))
    projects = [(0, '-- All Projects --')] + [(p.id, p.name) for p in project_q.order_by(Project.name).all()]
    
    district_q = District.query
    if not is_master_or_admin and allowed_districts:
        district_q = district_q.filter(District.id.in_(list(allowed_districts)))
    districts = [(0, '-- All Districts --')] + [(d.id, d.name) for d in district_q.order_by(District.name).all()]
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    pagination = SimplePagination(assigned, page, per_page)
    assigned = pagination.items
    return render_template(
        'assign_vehicle_to_district_List.html',
        assigned_vehicles=assigned,
        search=search,
        project_id=project_id or 0,
        district_id=district_id or 0,
        sort_by=sort_by,
        sort_order=sort_order,
        project_choices=projects,
        district_choices=districts,
        disable_project=disable_project,
        disable_district=disable_district,
        pagination=pagination,
        per_page=per_page,
        **_assignments_nav_back(),
    )


@app.route('/assign_vehicle_to_district/export')
def assign_vehicle_to_district_export():
    search = request.args.get('search', '').strip()
    project_id = request.args.get('project_id', type=int)
    district_id = request.args.get('district_id', type=int)
    assigned = _assign_vehicle_to_district_data(search=search, project_id=project_id, district_id=district_id)
    headers = ['Vehicle No', 'Model', 'Project', 'District', 'Assignment Date', 'Remarks']
    rows = []
    for v in assigned:
        rows.append([
            v.vehicle_no or '',
            v.model or '',
            v.project.name if v.project else '',
            v.district.name if v.district else '',
            v.assign_to_district_date.strftime('%Y-%m-%d') if v.assign_to_district_date else '-',
            (v.assignment_remarks or '').replace('\r\n', ' ').replace('\n', ' ')[:200]
        ])
    filename = 'vehicle_district_assignments.xlsx' if not search else f'vehicle_district_assignments_{search[:30].replace("/", "-")}.xlsx'
    return generate_excel_template(headers, rows, required_columns=[], filename=filename)


@app.route('/assign_vehicle_to_district/print')
def assign_vehicle_to_district_print():
    search = request.args.get('search', '').strip()
    project_id = request.args.get('project_id', type=int)
    district_id = request.args.get('district_id', type=int)
    assigned = _assign_vehicle_to_district_data(search=search, project_id=project_id, district_id=district_id)
    return render_template(
        'assign_vehicle_to_district_print.html',
        assigned_vehicles=assigned,
        search=search
    )


@app.route('/assign_vehicle_to_district/new', methods=['GET', 'POST'])
def assign_vehicle_to_district_new():
    form = AssignVehicleToDistrictForm()
    form.project_id.choices = [(0, '-- Select Project --')] + [
        (p.id, p.name) for p in Project.query.filter(Project.company_id.isnot(None)).order_by(Project.name).all()
    ]
    form.district_id.choices = [(0, '-- Select District --')]  # Loaded via AJAX when project selected
    # Only show vehicles not yet assigned (so they can't be assigned twice)
    unassigned_vehicles = Vehicle.query.filter(Vehicle.district_id.is_(None)).order_by(*vehicle_order_by()).all()
    form.vehicle_id.choices = [(0, '-- Select Vehicle --')] + [(v.id, f"{v.vehicle_no} ({v.model})") for v in unassigned_vehicles]
    if request.method == 'POST':
        p_id = request.form.get('project_id', type=int)
        if p_id:
            project = db.session.get(Project, p_id)
            form.district_id.choices = [(0, '-- Select District --')] + ([(d.id, d.name) for d in project.districts] if project else [])
        else:
            form.district_id.choices = [(0, '-- Select District --')]

    if form.validate_on_submit():
        try:
            vehicle = db.session.get(Vehicle, form.vehicle_id.data)
            project = db.session.get(Project, form.project_id.data)
            district = db.session.get(District, form.district_id.data)
            if not vehicle:
                flash("Selected vehicle not found.", "danger")
            elif not project:
                flash("Selected project does not exist.", "danger")
            elif not district:
                flash("Selected district does not exist.", "danger")
            else:
                vehicle.project_id = project.id
                vehicle.district_id = district.id
                vehicle.assign_to_district_date = form.assign_date.data
                vehicle.assignment_remarks = form.remarks.data
                db.session.commit()
                flash(f"Vehicle {vehicle.vehicle_no} assigned successfully!", "success")
                return redirect(url_for('assign_vehicle_to_district', **_preserve_nav_from()))
        except Exception as e:
            db.session.rollback()
            flash(f"Error: {str(e)}", "danger")
    return render_template('assign_vehicle_to_district_new.html', form=form,
                           **_nav_back_ctx(url_for('assign_vehicle_to_district')))


@app.route('/get_districts_by_project/<int:project_id>')
def get_districts_by_project(project_id):
    districts = District.query.join(project_district) \
                     .filter(project_district.c.project_id == project_id) \
                     .order_by(District.name).all()
    scope_projects, scope_districts, scope_vehicles, scope_shifts = _get_user_scope()
    if scope_districts:
        allowed = set(scope_districts)
        districts = [d for d in districts if d.id in allowed]
    if scope_projects and project_id not in (scope_projects or []):
        districts = []
    return jsonify([{"id": d.id, "name": d.name} for d in districts])


@app.route('/get_all_districts')
def get_all_districts():
    """Return all districts for filter dropdown when no project selected."""
    districts = District.query.order_by(District.name).all()
    scope_projects, scope_districts, scope_vehicles, scope_shifts = _get_user_scope()
    if scope_districts:
        allowed = set(scope_districts)
        districts = [d for d in districts if d.id in allowed]
    return jsonify([{"id": d.id, "name": d.name} for d in districts])


@app.route('/assign_vehicle_to_district/desassign/<int:vehicle_id>', methods=['POST'])
def desassign_vehicle_from_district(vehicle_id):
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    if vehicle.parking_station_id or vehicle.driver_id:
        parts = []
        if vehicle.parking_station_id:
            parts.append('Parking')
        if vehicle.driver_id:
            parts.append('Driver')
        flash(
            f'Cannot deassign: Vehicle "{vehicle.vehicle_no}" is linked with {" and ".join(parts)}. '
            'Remove parking assignment or driver assignment first.',
            'danger'
        )
        return redirect(url_for('assign_vehicle_to_district', **_preserve_nav_from()))
    vehicle.district_id = None
    vehicle.assign_to_district_date = None
    vehicle.assignment_remarks = None
    db.session.commit()
    flash("Vehicle desassigned successfully.", "info")
    return redirect(url_for('assign_vehicle_to_district', **_preserve_nav_from()))

@app.route('/company/report/<int:id>')
def company_report(id):
    company = Company.query.get_or_404(id)
    today = pk_date().strftime('%d %b, %Y')
    return render_template('company_report.html', company=company, current_date=today)


@app.route('/assign_vehicle_to_district/edit/<int:vehicle_id>', methods=['GET', 'POST'])
def assign_vehicle_to_district_edit(vehicle_id):
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    if vehicle.parking_station_id or vehicle.driver_id:
        parts = []
        if vehicle.parking_station_id:
            parts.append('Parking')
        if vehicle.driver_id:
            parts.append('Driver')
        flash(
            f'Cannot edit: Vehicle "{vehicle.vehicle_no}" is linked with {" and ".join(parts)}. '
            'Remove parking or driver assignment first.',
            'danger'
        )
        return redirect(url_for('assign_vehicle_to_district', **_preserve_nav_from()))
    form = AssignVehicleToDistrictForm()
    form.project_id.choices = [
        (p.id, p.name) for p in Project.query.filter(Project.company_id.isnot(None)).order_by(Project.name).all()
    ]
    # Show current vehicle + only unassigned vehicles (so already-assigned vehicles can't be selected for another project/district)
    form.vehicle_id.choices = [
        (v.id, f"{v.vehicle_no} ({v.model})")
        for v in Vehicle.query.filter(
            or_(Vehicle.district_id.is_(None), Vehicle.id == vehicle_id)
        ).order_by(*vehicle_order_by()).all()
    ]
    
    current_p_id = request.form.get('project_id', type=int) or vehicle.project_id
    if current_p_id:
        project = db.session.get(Project, current_p_id)
        form.district_id.choices = [(d.id, d.name) for d in project.districts]
    else:
        form.district_id.choices = []

    if request.method == 'GET':
        form.project_id.data = vehicle.project_id
        form.district_id.data = vehicle.district_id
        form.vehicle_id.data = vehicle.id
        form.assign_date.data = vehicle.assign_to_district_date
        form.remarks.data = vehicle.assignment_remarks

    if form.validate_on_submit():
        try:
            if vehicle.id != form.vehicle_id.data:
                vehicle.project_id = None
                vehicle.district_id = None
                vehicle = db.session.get(Vehicle, form.vehicle_id.data)
            
            vehicle.project_id = form.project_id.data
            vehicle.district_id = form.district_id.data
            vehicle.assign_to_district_date = form.assign_date.data
            vehicle.assignment_remarks = form.remarks.data
            
            db.session.commit()
            flash("Assignment updated successfully!", "success")
            return redirect(url_for('assign_vehicle_to_district', **_preserve_nav_from()))
        except Exception as e:
            db.session.rollback()
            flash(f"Error: {str(e)}", "danger")

    return render_template('assign_vehicle_to_district_edit.html', form=form, vehicle=vehicle,
                           **_nav_back_ctx(url_for('assign_vehicle_to_district')))


@app.route('/get_parking_by_project/<int:project_id>')
def get_parking_by_project(project_id):
    project = db.session.get(Project, project_id)
    if not project:
        return jsonify([])
    stations = [{"id": p.id, "name": p.name} for p in project.parking_stations]
    return jsonify(stations)

@app.route('/assign_vehicle_to_parking/new', methods=['GET', 'POST'])
def assign_vehicle_to_parking_new():
    form = AssignVehicleToParkingForm()
    form.project_id.choices = [(0, "Select Project")] + [
        (p.id, p.name) for p in Project.query.filter(Project.company_id.isnot(None)).order_by(Project.name).all()
    ]

    if request.method == 'POST':
        p_id = request.form.get('project_id', type=int) or form.project_id.data
        d_id = request.form.get('district_id', type=int) or form.district_id.data
        # Repopulate choices so submitted values are preserved when validation fails (form does not reset)
        if p_id:
            proj = db.session.get(Project, p_id)
            form.district_id.choices = [(0, '-- Select District --')] + [(d.id, d.name) for d in (proj.districts.order_by(District.name).all() if proj else [])]
        else:
            form.district_id.choices = [(0, '-- Select District --')]
        if d_id and p_id:
            dist_obj = db.session.get(District, d_id)
            vehicles = Vehicle.query.filter(
                Vehicle.project_id == p_id,
                Vehicle.district_id == d_id,
                Vehicle.parking_station_id.is_(None)
            ).order_by(*vehicle_order_by()).all()
            form.vehicle_id.choices = [(0, '-- Select Vehicle --')] + [(v.id, v.vehicle_no) for v in vehicles]
            if dist_obj:
                stations = ParkingStation.query.filter_by(district=dist_obj.name).all()
                form.parking_station_id.choices = [(0, '-- Select Parking --')] + [(s.id, s.name) for s in stations]
            else:
                form.parking_station_id.choices = [(0, '-- Select Parking --')]
        else:
            form.vehicle_id.choices = [(0, '-- Select Vehicle --')]
            form.parking_station_id.choices = [(0, '-- Select Parking --')]
    else:
        form.district_id.choices = [(0, '-- Select District --')]
        form.vehicle_id.choices = [(0, '-- Select Vehicle --')]
        form.parking_station_id.choices = [(0, '-- Select Parking --')]

    if form.validate_on_submit():
        try:
            vehicle = db.session.get(Vehicle, form.vehicle_id.data)
            vehicle.parking_station_id = form.parking_station_id.data
            vehicle.parking_assign_date = form.assign_date.data 
            vehicle.parking_remarks = form.remarks.data
            db.session.commit()
            flash("Vehicle assigned to parking successfully!", "success")
            return redirect(url_for('assign_vehicle_to_parking_list', **_preserve_nav_from()))
        except Exception as e:
            db.session.rollback()
            flash(f"Error: {str(e)}", "danger")

    return render_template('assign_vehicle_to_parking_new.html', form=form,
                           **_nav_back_ctx(url_for('assign_vehicle_to_parking_list')))

@app.route('/get_vehicles_by_district/<int:project_id>/<int:district_id>')
def get_vehicles_by_district(project_id, district_id):
    vehicles = Vehicle.query.filter(
        Vehicle.project_id == project_id,
        Vehicle.district_id == district_id
    ).order_by(*vehicle_order_by()).all()
    return jsonify([{"id": v.id, "no": v.vehicle_no} for v in vehicles])


@app.route('/get_vehicles_by_district_no_parking/<int:project_id>/<int:district_id>')
def get_vehicles_by_district_no_parking(project_id, district_id):
    """Vehicles in project+district that have NO parking assigned. Optional ?include_vehicle_id=X to include that vehicle (for edit form)."""
    include_id = request.args.get('include_vehicle_id', type=int)
    query = Vehicle.query.filter(
        Vehicle.project_id == project_id,
        Vehicle.district_id == district_id
    )
    if include_id:
        query = query.filter(
            (Vehicle.parking_station_id.is_(None)) | (Vehicle.id == include_id)
        )
    else:
        query = query.filter(Vehicle.parking_station_id.is_(None))
    vehicles = query.order_by(*vehicle_order_by()).all()
    return jsonify([{"id": v.id, "no": v.vehicle_no} for v in vehicles])

@app.route('/get_parking_by_district/<int:district_id>')
def get_parking_by_district(district_id):
    district = db.session.get(District, district_id)
    if not district:
        return jsonify([])
    stations = ParkingStation.query.filter_by(district=district.name).all()
    output = []
    for s in stations:
        occupied = Vehicle.query.filter_by(parking_station_id=s.id).count()
        available = s.capacity - occupied
        output.append({
            "id": s.id, 
            "name": f"{s.name} (Available: {available}/{s.capacity})",
            "is_full": available <= 0
        })
    return jsonify(output)


@app.route('/assign_vehicle_to_parking')
def assign_vehicle_to_parking_list():
    from auth_utils import get_user_context
    
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)
    
    search = request.args.get('search', '').strip()
    project_id = request.args.get('project_id', type=int)
    district_id = request.args.get('district_id', type=int)
    from_date_str = request.args.get('from_date', '').strip()
    to_date_str = request.args.get('to_date', '').strip()
    sort_by = request.args.get('sort_by', 'assign_date')
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
    
    from_date = parse_date_dmy(from_date_str) if from_date_str else None
    to_date = parse_date_dmy(to_date_str) if to_date_str else None
    parked_vehicles = _assign_vehicle_to_parking_data(search=search, project_id=project_id, district_id=district_id, from_date=from_date, to_date=to_date, sort_by=sort_by, sort_order=sort_order)
    
    # Filter dropdown choices by user scope
    project_q = Project.query.filter(Project.company_id.isnot(None))
    if not is_master_or_admin and allowed_projects:
        project_q = project_q.filter(Project.id.in_(list(allowed_projects)))
    projects = [(0, '-- All Projects --')] + [(p.id, p.name) for p in project_q.order_by(Project.name).all()]
    
    district_q = District.query
    if not is_master_or_admin and allowed_districts:
        district_q = district_q.filter(District.id.in_(list(allowed_districts)))
    districts = [(0, '-- All Districts --')] + [(d.id, d.name) for d in district_q.order_by(District.name).all()]
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    pagination = SimplePagination(parked_vehicles, page, per_page)
    parked_vehicles = pagination.items
    return render_template(
        'assign_vehicle_to_parking_list.html',
        parked_vehicles=parked_vehicles,
        search=search,
        project_id=project_id or 0,
        district_id=district_id or 0,
        from_date=from_date_str,
        to_date=to_date_str,
        project_choices=projects,
        district_choices=districts,
        sort_by=sort_by,
        sort_order=sort_order,
        disable_project=disable_project,
        disable_district=disable_district,
        pagination=pagination,
        per_page=per_page,
        **_assignments_nav_back(),
    )


def _assign_vehicle_to_parking_data(search=None, project_id=None, district_id=None, from_date=None, to_date=None, sort_by='assign_date', sort_order='desc'):
    """Query vehicles with parking assigned (optionally filtered by search, project_id, district_id, date range). Returns list of Vehicle."""
    query = Vehicle.query.filter(Vehicle.parking_station_id.isnot(None))
    if project_id:
        query = query.filter(Vehicle.project_id == project_id)
    if district_id:
        query = query.filter(Vehicle.district_id == district_id)
    if from_date:
        query = query.filter(Vehicle.parking_assign_date >= from_date)
    if to_date:
        query = query.filter(Vehicle.parking_assign_date <= to_date)

    # Track which joins have already been applied to avoid duplicates
    _joined_project  = False
    _joined_district = False
    _joined_parking  = False

    if search:
        # Use outerjoin so vehicles with NULL project_id / district_id are NOT excluded
        query = query.outerjoin(Project,        Vehicle.project_id         == Project.id) \
                     .outerjoin(District,       Vehicle.district_id        == District.id) \
                     .outerjoin(ParkingStation, Vehicle.parking_station_id == ParkingStation.id)
        _joined_project  = True
        _joined_district = True
        _joined_parking  = True
        flt = _multi_word_filter(search,
            Vehicle.vehicle_no, Vehicle.model,
            Project.name, District.name, ParkingStation.name)
        if flt is not None:
            query = query.filter(flt)

    # Apply sorting — reuse existing joins if already present
    if sort_by == 'vehicle':
        order_col = Vehicle.vehicle_no
    elif sort_by == 'project':
        if not _joined_project:
            query = query.outerjoin(Project, Vehicle.project_id == Project.id)
        order_col = Project.name
    elif sort_by == 'district':
        if not _joined_district:
            query = query.outerjoin(District, Vehicle.district_id == District.id)
        order_col = District.name
    elif sort_by == 'parking':
        if not _joined_parking:
            query = query.outerjoin(ParkingStation, Vehicle.parking_station_id == ParkingStation.id)
        order_col = ParkingStation.name
    elif sort_by == 'assign_date':
        order_col = Vehicle.parking_assign_date
    else:
        order_col = Vehicle.parking_assign_date

    query = query.order_by(order_col.asc() if sort_order == 'asc' else order_col.desc())
    return query.all()


@app.route('/assign_vehicle_to_parking/export')
def assign_vehicle_to_parking_export():
    search = request.args.get('search', '').strip()
    project_id = request.args.get('project_id', type=int)
    district_id = request.args.get('district_id', type=int)
    from_date_str = request.args.get('from_date', '').strip()
    to_date_str = request.args.get('to_date', '').strip()
    from_date = parse_date_dmy(from_date_str) if from_date_str else None
    to_date = parse_date_dmy(to_date_str) if to_date_str else None
    parked_vehicles = _assign_vehicle_to_parking_data(search=search, project_id=project_id, district_id=district_id, from_date=from_date, to_date=to_date)
    headers = ['Vehicle No', 'Model', 'Project', 'Parking Station', 'District', 'Assign Date', 'Remarks']
    rows = []
    for v in parked_vehicles:
        rows.append([
            v.vehicle_no or '',
            v.model or '',
            v.project.name if v.project else '',
            v.parking_station.name if v.parking_station else '',
            v.district.name if v.district else '',
            v.parking_assign_date.strftime('%d-%m-%Y') if v.parking_assign_date else '',
            (v.parking_remarks or '').replace('\r\n', ' ').replace('\n', ' ')[:200]
        ])
    filename = 'vehicle_parking_assignments.xlsx' if not search else f'vehicle_parking_assignments_{search[:30].replace("/", "-")}.xlsx'
    return generate_excel_template(headers, rows, required_columns=[], filename=filename)


@app.route('/assign_vehicle_to_parking/print')
def assign_vehicle_to_parking_print():
    search = request.args.get('search', '').strip()
    project_id = request.args.get('project_id', type=int)
    district_id = request.args.get('district_id', type=int)
    from_date_str = request.args.get('from_date', '').strip()
    to_date_str = request.args.get('to_date', '').strip()
    from_date = parse_date_dmy(from_date_str) if from_date_str else None
    to_date = parse_date_dmy(to_date_str) if to_date_str else None
    parked_vehicles = _assign_vehicle_to_parking_data(search=search, project_id=project_id, district_id=district_id, from_date=from_date, to_date=to_date)
    return render_template(
        'assign_vehicle_to_parking_print.html',
        parked_vehicles=parked_vehicles,
        search=search,
        project_id=project_id or 0,
        district_id=district_id or 0,
        from_date=from_date_str,
        to_date=to_date_str,
    )


@app.route('/assign_vehicle_to_parking/desassign/<int:vehicle_id>', methods=['POST'])
def desassign_vehicle_from_parking(vehicle_id):
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    has_driver = Driver.query.filter_by(vehicle_id=vehicle.id).first() is not None
    if has_driver:
        flash(
            f'Cannot deassign: Vehicle "{vehicle.vehicle_no}" has a driver attached. '
            'Remove driver assignment first (Assignment → Driver to Vehicle).',
            'danger'
        )
        return redirect(url_for('assign_vehicle_to_parking_list', **_preserve_nav_from()))
    station_name = vehicle.parking_station.name if vehicle.parking_station else "Parking"
    vehicle.parking_station_id = None
    db.session.commit()
    flash(f"Vehicle {vehicle.vehicle_no} removed from {station_name}.", "info")
    return redirect(url_for('assign_vehicle_to_parking_list', **_preserve_nav_from()))

@app.route('/assign_vehicle_to_parking/edit/<int:vehicle_id>', methods=['GET', 'POST'])
def assign_vehicle_to_parking_edit(vehicle_id):
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    has_driver = Driver.query.filter_by(vehicle_id=vehicle.id).first() is not None
    if has_driver:
        flash(
            f'Cannot edit: Vehicle "{vehicle.vehicle_no}" has a driver attached. '
            'Remove driver assignment first (Assignment → Driver to Vehicle).',
            'danger'
        )
        return redirect(url_for('assign_vehicle_to_parking_list', **_preserve_nav_from()))
    form = AssignVehicleToParkingForm()
    
    form.project_id.choices = [
        (p.id, p.name) for p in Project.query.filter(Project.company_id.isnot(None)).order_by(Project.name).all()
    ]
    p_id = request.form.get('project_id', type=int) or vehicle.project_id
    d_id = request.form.get('district_id', type=int) or vehicle.district_id
    # Vehicle list: only those without parking in this project+district, or the current vehicle (for edit)
    if p_id and d_id:
        vehicles_for_choice = Vehicle.query.filter(
            Vehicle.project_id == p_id,
            Vehicle.district_id == d_id
        ).filter(
            (Vehicle.parking_station_id.is_(None)) | (Vehicle.id == vehicle_id)
        ).order_by(*vehicle_order_by()).all()
        form.vehicle_id.choices = [(v.id, f"{v.vehicle_no} ({v.model})") for v in vehicles_for_choice]
    else:
        form.vehicle_id.choices = []
    

    if p_id:
        proj = db.session.get(Project, p_id)
        form.district_id.choices = [(d.id, d.name) for d in proj.districts.all()]
    else:
        form.district_id.choices = []

    if d_id:
        dist_obj = db.session.get(District, d_id)
        stations = ParkingStation.query.filter_by(district=dist_obj.name).all()
        form.parking_station_id.choices = [(s.id, s.name) for s in stations]
    else:
        form.parking_station_id.choices = []

    if request.method == 'GET':
        form.project_id.data = vehicle.project_id
        form.district_id.data = vehicle.district_id
        form.vehicle_id.data = vehicle.id
        form.parking_station_id.data = vehicle.parking_station_id
        form.assign_date.data = vehicle.parking_assign_date
        form.remarks.data = vehicle.parking_remarks 

    if form.validate_on_submit():
        try:
            new_ps_id = form.parking_station_id.data
            if new_ps_id != vehicle.parking_station_id:
                parking = db.session.get(ParkingStation, new_ps_id)
                occupied = Vehicle.query.filter_by(parking_station_id=new_ps_id).count()
                if occupied >= parking.capacity:
                    flash(f"Error: {parking.name} is full!", "danger")
                    return render_template('assign_vehicle_to_parking_edit.html', form=form, vehicle=vehicle,
                                           **_nav_back_ctx(url_for('assign_vehicle_to_parking_list')))
            
            if vehicle.id != form.vehicle_id.data:
                vehicle.parking_station_id = None
                vehicle = db.session.get(Vehicle, form.vehicle_id.data)

            vehicle.parking_station_id = new_ps_id
            vehicle.parking_assign_date = form.assign_date.data
            vehicle.parking_remarks = form.remarks.data
            db.session.commit()
            flash("Parking assignment updated successfully!", "success")
            return redirect(url_for('assign_vehicle_to_parking_list', **_preserve_nav_from()))
        except Exception as e:
            db.session.rollback()
            flash(f"Error: {str(e)}", "danger")

    return render_template('assign_vehicle_to_parking_edit.html', form=form, vehicle=vehicle,
                           **_nav_back_ctx(url_for('assign_vehicle_to_parking_list')))

@app.route('/get_driver_details/<int:driver_id>')
def get_driver_details(driver_id):
    d = Driver.query.get_or_404(driver_id)
    district_name = d.district.name if d.district else (d.driver_district or '-')
    photo_url = d.photo_path if d.photo_path else None
    proj_obj = db.session.get(Project, d.project_id) if d.project_id else None
    project_name = proj_obj.name if proj_obj else '-'

    # ── Build Job History ──
    history = []

    # 1. Initial Assignment event
    if d.assign_date:
        transfers_sorted = sorted(d.transfer_history, key=lambda t: t.transfer_date)
        if transfers_sorted:
            ft = transfers_sorted[0]
            init_veh = ft.old_vehicle.vehicle_no if ft.old_vehicle else '-'
            if ft.old_vehicle and ft.old_vehicle.model:
                init_veh += f" ({ft.old_vehicle.model})"
            init_dist = ft.old_district.name if ft.old_district else '-'
            init_proj = ft.old_project.name if ft.old_project else '-'
            init_shift = ft.old_shift or '-'
        else:
            init_veh = (d.vehicle.vehicle_no + (f" ({d.vehicle.model})" if d.vehicle.model else '')) if d.vehicle else '-'
            init_dist  = district_name
            init_proj  = project_name
            init_shift = d.shift or '-'
        history.append({
            'date_sort': d.assign_date.isoformat(),
            'date':  d.assign_date.strftime('%d-%m-%Y'),
            'type':  'assignment',
            'title': 'ASSIGNMENT',
            'line1': f"To Vehicle: {init_veh}",
            'line2': f"Project: {init_proj}",
            'line3': f"District: {init_dist} | Shift: {init_shift}",
            'remarks': d.assign_remarks or '',
        })

    # 2. Transfers
    for t in sorted(d.transfer_history, key=lambda x: x.transfer_date):
        new_veh = t.new_vehicle.vehicle_no if t.new_vehicle else '-'
        if t.new_vehicle and t.new_vehicle.model:
            new_veh += f" ({t.new_vehicle.model})"
        if t.is_shift_only:
            history.append({
                'date_sort': t.transfer_date.isoformat(),
                'date':  t.transfer_date.strftime('%d-%m-%Y'),
                'type':  'shift_change',
                'title': 'SHIFT CHANGE',
                'line1': f"Vehicle: {new_veh}",
                'line2': f"Shift: {t.old_shift or '-'} → {t.new_shift or '-'}",
                'line3': f"Project: {t.new_project.name if t.new_project else '-'} | District: {t.new_district.name if t.new_district else '-'}",
                'remarks': t.remarks or '',
            })
        else:
            history.append({
                'date_sort': t.transfer_date.isoformat(),
                'date':  t.transfer_date.strftime('%d-%m-%Y'),
                'type':  'transfer',
                'title': 'TRANSFER',
                'line1': f"To Vehicle: {new_veh}",
                'line2': f"Project: {t.new_project.name if t.new_project else '-'}",
                'line3': f"District: {t.new_district.name if t.new_district else '-'} | Shift: {t.new_shift or '-'}",
                'remarks': t.remarks or '',
            })

    # 3. Status Changes (left / rejoin)
    for sc in sorted(d.status_changes, key=lambda x: x.change_date):
        if sc.action_type == 'left':
            lv = sc.left_vehicle.vehicle_no if sc.left_vehicle else '-'
            if sc.left_vehicle and sc.left_vehicle.model:
                lv += f" ({sc.left_vehicle.model})"
            history.append({
                'date_sort': sc.change_date.isoformat(),
                'date':  sc.change_date.strftime('%d-%m-%Y'),
                'type':  'left',
                'title': 'JOB LEFT',
                'line1': f"Reason: {sc.reason or '-'}",
                'line2': f"From Vehicle: {lv}",
                'line3': f"District: {sc.left_district.name if sc.left_district else '-'} | Project: {sc.left_project.name if sc.left_project else '-'}",
                'remarks': sc.remarks or '',
            })
        elif sc.action_type == 'rejoin':
            rv = sc.new_vehicle.vehicle_no if sc.new_vehicle else '-'
            if sc.new_vehicle and sc.new_vehicle.model:
                rv += f" ({sc.new_vehicle.model})"
            history.append({
                'date_sort': sc.change_date.isoformat(),
                'date':  sc.change_date.strftime('%d-%m-%Y'),
                'type':  'rejoin',
                'title': 'REJOINED',
                'line1': f"To Vehicle: {rv}",
                'line2': f"Project: {sc.new_project.name if sc.new_project else '-'}",
                'line3': f"District: {sc.new_district.name if sc.new_district else '-'} | Shift: {sc.new_shift or '-'}",
                'remarks': sc.remarks or '',
            })

    history.sort(key=lambda x: x['date_sort'])
    for h in history:
        del h['date_sort']

    return jsonify({
        'name':        d.name,
        'driver_id':   d.driver_id or '-',
        'post':        d.post or 'Driver',
        'status':      d.status or 'Active',
        'district':    district_name,
        'shift':       d.shift or '-',
        'photo_url':   photo_url,
        'father_name': d.father_name or '-',
        'cnic_no':     d.cnic_no or '-',
        'phone1':      d.phone1 or '-',
        'phone2':      d.phone2 or '-',
        'address':     d.address or '-',
        'history':     history,
    })

@app.route('/assign_driver_to_vehicle/new', methods=['GET', 'POST'])
def assign_driver_to_vehicle_new():
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)

    form = AssignDriverToVehicleForm()
    proj_q = Project.query.filter(Project.company_id.isnot(None)).order_by(Project.name)
    if not is_master_or_admin and allowed_projects:
        proj_q = proj_q.filter(Project.id.in_(list(allowed_projects)))
    form.project_id.choices = [(0, '-- Select Project --')] + [(p.id, p.name) for p in proj_q.all()]
    
    # Auto-select if only 1 project allowed
    disable_project = False
    if not is_master_or_admin and len(allowed_projects) == 1:
        single_proj = next(iter(allowed_projects))
        if not form.project_id.data or form.project_id.data == 0:
            form.project_id.data = single_proj
        disable_project = True

    selected_project_id = None
    selected_district_id = None

    if request.method == 'POST':
        selected_project_id = form.project_id.data
        selected_district_id = form.district_id.data

        if selected_project_id and selected_project_id != 0:
            project = db.session.get(Project, selected_project_id)
            if project:
                form.district_id.choices = [(d.id, d.name) for d in project.districts]

                if selected_district_id and selected_district_id != 0:
                    vehicles = Vehicle.query.filter_by(
                        project_id=selected_project_id,
                        district_id=selected_district_id
                    ).all()
                    form.vehicle_id.choices = [
                        (v.id, f"{v.vehicle_no} – {v.model or 'N/A'}") for v in vehicles
                    ]

    unassigned_drivers = Driver.query.filter(Driver.vehicle_id.is_(None)).order_by(Driver.name).all()
    form.driver_id.choices = [(0, '-- Select Driver --')] + [
        (d.id, f"{d.name} ({d.driver_id})") for d in unassigned_drivers
    ]

    if form.validate_on_submit():
        vehicle = db.session.get(Vehicle, form.vehicle_id.data)
        driver = db.session.get(Driver, form.driver_id.data)

        if not vehicle or not driver:
            flash("Selected vehicle or driver not found.", "danger")
            return render_template('assign_driver_to_vehicle_new.html', form=form,
                                   **_nav_back_ctx(url_for('assign_driver_to_vehicle_list')))

        if not vehicle.parking_station_id:
            flash("Pehle es vehicle ko Parking Station assign karo.", "danger")
            if not form.district_id.choices or form.district_id.choices == [(0, '-- Select District --')]:
                if selected_project_id and selected_project_id != 0:
                    project = db.session.get(Project, selected_project_id)
                    if project:
                        form.district_id.choices = [(d.id, d.name) for d in project.districts]
                if selected_district_id and selected_district_id != 0:
                    vehicles = Vehicle.query.filter_by(
                        project_id=selected_project_id,
                        district_id=selected_district_id
                    ).all()
                    form.vehicle_id.choices = [
                        (v.id, f"{v.vehicle_no} – {v.model or 'N/A'}") for v in vehicles
                    ]
            if not form.district_id.choices: form.district_id.choices = [(0, '-- Select District --')]
            if not form.vehicle_id.choices:  form.vehicle_id.choices  = [(0, '-- Select Vehicle --')]
            return render_template('assign_driver_to_vehicle_new.html', form=form, disable_project=disable_project,
                                   **_nav_back_ctx(url_for('assign_driver_to_vehicle_list')))

        current_count = Driver.query.filter_by(vehicle_id=vehicle.id).count()
        if current_count >= (vehicle.driver_capacity or 1):
            flash(f"Vehicle capacity ({vehicle.driver_capacity or 1}) already reached!", "danger")
            return render_template('assign_driver_to_vehicle_new.html', form=form, disable_project=disable_project,
                                   **_nav_back_ctx(url_for('assign_driver_to_vehicle_list')))

        shift_taken = Driver.query.filter_by(vehicle_id=vehicle.id, shift=form.shift.data).first()
        if shift_taken:
            flash(f"{form.shift.data} shift already assigned to this vehicle!", "danger")
            return render_template('assign_driver_to_vehicle_new.html', form=form, disable_project=disable_project,
                                   **_nav_back_ctx(url_for('assign_driver_to_vehicle_list')))

        cap = vehicle.driver_capacity or 1
        if cap == 1 and form.shift.data != 'Morning':
            flash("Is vehicle ki capacity 1 hai — sirf Morning shift allowed.", "danger")
            return render_template('assign_driver_to_vehicle_new.html', form=form, disable_project=disable_project,
                                   **_nav_back_ctx(url_for('assign_driver_to_vehicle_list')))

        try:
            driver.vehicle_id = vehicle.id
            driver.shift = form.shift.data
            driver.project_id = form.project_id.data
            driver.district_id = form.district_id.data if (form.district_id.data and form.district_id.data != 0) else vehicle.district_id
            driver.assign_date = form.assign_date.data
            driver.assign_remarks = form.remarks.data
            if (driver.status or '').strip().lower() == 'left':
                driver.status = 'Active'
            db.session.commit()
            flash(f"Driver {driver.name} assigned to {vehicle.vehicle_no} ({form.shift.data}) successfully!", "success")
            return redirect(url_for('assign_driver_to_vehicle_list', **_preserve_nav_from()))
        except Exception as e:
            db.session.rollback()
            flash(f"Error saving assignment: {str(e)}", "danger")

    if not form.district_id.choices: form.district_id.choices = [(0, '-- Select District --')]
    if not form.vehicle_id.choices:  form.vehicle_id.choices  = [(0, '-- Select Vehicle --')]
    return render_template('assign_driver_to_vehicle_new.html', form=form, disable_project=disable_project,
                           **_nav_back_ctx(url_for('assign_driver_to_vehicle_list')))

@app.route('/get_vehicle_capacity_info/<int:vehicle_id>')
def get_vehicle_capacity_info(vehicle_id):
    vehicle = db.session.get(Vehicle, vehicle_id)
    if not vehicle:
        return jsonify({"error": "Not found"}), 404
    assigned_drivers = Driver.query.filter_by(vehicle_id=vehicle_id).all()
    occupied_shifts = [d.shift for d in assigned_drivers]
    return jsonify({
        "capacity": vehicle.driver_capacity or 1,
        "occupied_shifts": occupied_shifts,
        "available_morning": "Morning" not in occupied_shifts,
        "available_night": "Night" not in occupied_shifts
    })


@app.route('/get_vehicle_parking/<int:vehicle_id>')
def get_vehicle_parking(vehicle_id):
    """Returns parking station info for a vehicle (for Driver-to-Vehicle form)."""
    vehicle = db.session.get(Vehicle, vehicle_id)
    if not vehicle:
        return jsonify({"error": "Not found"}), 404
    if not vehicle.parking_station_id:
        return jsonify({"parking_station_id": None, "parking_station_name": None})
    ps = db.session.get(ParkingStation, vehicle.parking_station_id)
    return jsonify({
        "parking_station_id": vehicle.parking_station_id,
        "parking_station_name": ps.name if ps else None
    })

@app.route('/assign_driver_to_vehicle')
def assign_driver_to_vehicle_list():
    from auth_utils import get_user_context
    
    try:
        user_id = session.get('user_id')
        user_context = get_user_context(user_id) if user_id else {}
        allowed_projects = user_context.get('allowed_projects', set())
        allowed_districts = user_context.get('allowed_districts', set())
        allowed_vehicles = user_context.get('allowed_vehicles', set())
        is_master_or_admin = user_context.get('is_master_or_admin', False)
        
        search = request.args.get('search', '').strip()
        project_id = request.args.get('project_id', type=int)
        district_id = request.args.get('district_id', type=int)
        sort_by = request.args.get('sort_by', 'driver')
        sort_order = request.args.get('sort_order', 'asc')
        
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
        
        assigned_drivers = _assign_driver_to_vehicle_data(search=search, project_id=project_id, district_id=district_id, sort_by=sort_by, sort_order=sort_order)
    except Exception as e:
        app.logger.exception('assign_driver_to_vehicle_list error: %s', e)
        flash(f"Error loading page: {str(e)}", "danger")
        return redirect(url_for('dashboard'))
    
    # Apply user data scope to assigned drivers
    # Note: assigned_drivers contains (Driver, Vehicle) tuples
    # District is stored on Vehicle (vehicle.district_id), not Driver
    if not is_master_or_admin:
        if allowed_projects or allowed_districts or allowed_vehicles:
            assigned_drivers = [
                (driver, vehicle) for driver, vehicle in assigned_drivers
                if (not allowed_projects or (driver.project_id and driver.project_id in allowed_projects)) and
                   (not allowed_districts or (vehicle.district_id and vehicle.district_id in allowed_districts)) and
                   (not allowed_vehicles or (driver.vehicle_id and driver.vehicle_id in allowed_vehicles))
            ]
    
    # Filter dropdown choices by user scope
    project_q = Project.query.filter(Project.company_id.isnot(None))
    if not is_master_or_admin and allowed_projects:
        project_q = project_q.filter(Project.id.in_(list(allowed_projects)))
    projects = [(0, '-- All Projects --')] + [(p.id, p.name) for p in project_q.order_by(Project.name).all()]
    
    district_q = District.query
    if not is_master_or_admin and allowed_districts:
        district_q = district_q.filter(District.id.in_(list(allowed_districts)))
    districts = [(0, '-- All Districts --')] + [(d.id, d.name) for d in district_q.order_by(District.name).all()]
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    pagination = SimplePagination(assigned_drivers, page, per_page)
    assigned_drivers = pagination.items
    return render_template(
        'assign_driver_to_vehicle_list.html',
        assigned_drivers=assigned_drivers,
        search=search,
        project_id=project_id or 0,
        district_id=district_id or 0,
        sort_by=sort_by,
        sort_order=sort_order,
        project_choices=projects,
        district_choices=districts,
        disable_project=disable_project,
        disable_district=disable_district,
        pagination=pagination,
        per_page=per_page,
        **_assignments_nav_back(),
    )


def _assign_driver_to_vehicle_data(search=None, project_id=None, district_id=None, sort_by='driver', sort_order='asc'):
    """Query (Driver, Vehicle) pairs for assigned drivers. Optional filter by project_id, district_id."""
    query = db.session.query(Driver, Vehicle).join(Vehicle, Driver.vehicle_id == Vehicle.id)
    if project_id:
        query = query.filter(Driver.project_id == project_id)
    if district_id:
        query = query.filter(Vehicle.district_id == district_id)

    _joined_project  = False
    _joined_district = False

    if search:
        query = query.outerjoin(Project,  Driver.project_id   == Project.id) \
                     .outerjoin(District, Vehicle.district_id == District.id)
        _joined_project  = True
        _joined_district = True
        flt = _multi_word_filter(search,
            Driver.name, Driver.driver_id, Driver.cnic_no, Driver.shift,
            Vehicle.vehicle_no, Vehicle.model,
            Project.name, District.name)
        if flt is not None:
            query = query.filter(flt)

    # Apply sorting — reuse joins already applied
    if sort_by == 'driver':
        order_col = Driver.name
    elif sort_by == 'vehicle':
        order_col = Vehicle.vehicle_no
    elif sort_by == 'project':
        if not _joined_project:
            query = query.outerjoin(Project, Driver.project_id == Project.id)
        order_col = Project.name
    elif sort_by == 'district':
        if not _joined_district:
            query = query.outerjoin(District, Vehicle.district_id == District.id)
        order_col = District.name
    else:
        order_col = Driver.name

    query = query.order_by(order_col.asc() if sort_order == 'asc' else order_col.desc())
    return query.all()


@app.route('/assign_driver_to_vehicle/export')
def assign_driver_to_vehicle_export():
    search = request.args.get('search', '').strip()
    project_id = request.args.get('project_id', type=int)
    district_id = request.args.get('district_id', type=int)
    assigned_drivers = _assign_driver_to_vehicle_data(search=search, project_id=project_id, district_id=district_id)
    headers = ['S.No', 'Driver Name', 'Driver ID', 'Project', 'District', 'Vehicle No', 'Model', 'Shift']
    rows = []
    for i, (driver, vehicle) in enumerate(assigned_drivers, 1):
        rows.append([
            i,
            driver.name or '',
            driver.driver_id or '',
            driver.project.name if driver.project else '',
            vehicle.district.name if vehicle.district else '',
            vehicle.vehicle_no or '',
            vehicle.model or '',
            driver.shift or ''
        ])
    filename = 'driver_vehicle_assignments.xlsx' if not search else f'driver_vehicle_assignments_{search[:30].replace("/", "-")}.xlsx'
    return generate_excel_template(headers, rows, required_columns=[], filename=filename)


@app.route('/assign_driver_to_vehicle/print')
def assign_driver_to_vehicle_print():
    search = request.args.get('search', '').strip()
    project_id = request.args.get('project_id', type=int)
    district_id = request.args.get('district_id', type=int)
    assigned_drivers = _assign_driver_to_vehicle_data(search=search, project_id=project_id, district_id=district_id)
    return render_template(
        'assign_driver_to_vehicle_print.html',
        assigned_drivers=assigned_drivers,
        search=search
    )

@app.route('/assign_driver_to_vehicle/desassign/<int:driver_id>', methods=['POST'])
def desassign_driver_from_vehicle(driver_id):
    driver = Driver.query.get_or_404(driver_id)
    vehicle = db.session.get(Vehicle, driver.vehicle_id) if driver.vehicle_id else None
    vehicle_no = vehicle.vehicle_no if vehicle else "Vehicle"
    
    driver.vehicle_id = None
    driver.shift = None
    db.session.commit()
    
    flash(f"Driver '{driver.name}' successfully removed from Vehicle '{vehicle_no}'.", "info")
    return redirect(url_for('assign_driver_to_vehicle_list', **_preserve_nav_from()))

@app.route('/assign_driver_to_vehicle/edit/<int:driver_id>', methods=['GET', 'POST'])
def assign_driver_to_vehicle_edit(driver_id):
    driver = Driver.query.get_or_404(driver_id)
    current_vehicle = db.session.get(Vehicle, driver.vehicle_id) if driver.vehicle_id else None

    form = AssignDriverToVehicleForm()
    form.project_id.choices = [(0, '-- Select Project --')] + [
        (p.id, p.name) for p in Project.query.filter(Project.company_id.isnot(None)).order_by(Project.name).all()
    ]

    pid = form.project_id.data if request.method == 'POST' else driver.project_id
    did = form.district_id.data if request.method == 'POST' else (current_vehicle.district_id if current_vehicle else None)

    form.district_id.choices = [(0, '-- Select District --')]
    form.vehicle_id.choices = [(0, '-- Select Vehicle --')]

    if pid and pid != 0:
        proj = db.session.get(Project, pid)
        if proj:
            form.district_id.choices += [(d.id, d.name) for d in proj.districts]
            if did and did != 0:
                vehicles = Vehicle.query.filter_by(project_id=pid, district_id=did).all()
                form.vehicle_id.choices += [(v.id, f"{v.vehicle_no} – {v.model or 'N/A'}") for v in vehicles]

    current_driver_choice = (driver.id, f"{driver.name} ({driver.driver_id}) – Current")
    unassigned = Driver.query.filter(Driver.vehicle_id.is_(None), Driver.id != driver.id).order_by(Driver.name).all()
    unassigned_choices = [(d.id, f"{d.name} ({d.driver_id}) – Unassigned") for d in unassigned]
    form.driver_id.choices = [current_driver_choice] + unassigned_choices

    if request.method == 'GET':
        form.project_id.data    = driver.project_id
        form.district_id.data   = current_vehicle.district_id if current_vehicle else None
        form.vehicle_id.data    = driver.vehicle_id
        form.driver_id.data     = driver.id
        form.shift.data         = driver.shift
        form.assign_date.data   = driver.assign_date or pk_date()
        form.remarks.data       = driver.assign_remarks or ''

    if form.validate_on_submit():
        vehicle = db.session.get(Vehicle, form.vehicle_id.data)
        if not vehicle:
            flash("Vehicle not found", "danger")
            return render_template('assign_driver_to_vehicle_edit.html', form=form, driver=driver,
                                   **_nav_back_ctx(url_for('assign_driver_to_vehicle_list')))

        if vehicle.id != driver.vehicle_id:
            count = Driver.query.filter_by(vehicle_id=vehicle.id).count()
            if count >= (vehicle.driver_capacity or 1):
                flash("Target vehicle capacity reached", "danger")
                return render_template('assign_driver_to_vehicle_edit.html', form=form, driver=driver,
                                   **_nav_back_ctx(url_for('assign_driver_to_vehicle_list')))

        conflict = Driver.query.filter(
            Driver.vehicle_id == vehicle.id, Driver.shift == form.shift.data, Driver.id != driver.id
        ).first()
        if conflict:
            flash(f"{form.shift.data} shift already taken", "danger")
            return render_template('assign_driver_to_vehicle_edit.html', form=form, driver=driver,
                                   **_nav_back_ctx(url_for('assign_driver_to_vehicle_list')))

        cap = vehicle.driver_capacity or 1
        if cap == 1 and form.shift.data != 'Morning':
            flash("Is vehicle ki capacity 1 hai — sirf Morning shift allowed.", "danger")
            return render_template('assign_driver_to_vehicle_edit.html', form=form, driver=driver,
                                   **_nav_back_ctx(url_for('assign_driver_to_vehicle_list')))

        try:
            new_driver_id = form.driver_id.data
            if new_driver_id != driver.id:
                driver.vehicle_id = None
                driver.shift = None
                driver.assign_date = None
                driver.assign_remarks = None

                new_driver = db.session.get(Driver, new_driver_id)
                if new_driver:
                    new_driver.vehicle_id = vehicle.id
                    new_driver.shift = form.shift.data
                    new_driver.project_id = form.project_id.data
                    new_driver.assign_date = form.assign_date.data
                    new_driver.assign_remarks = form.remarks.data
                    if (new_driver.status or '').strip().lower() == 'left':
                        new_driver.status = 'Active'
            else:
                driver.vehicle_id = vehicle.id
                driver.shift = form.shift.data
                driver.project_id = form.project_id.data
                driver.assign_date = form.assign_date.data
                driver.assign_remarks = form.remarks.data
                if (driver.status or '').strip().lower() == 'left':
                    driver.status = 'Active'

            db.session.commit()
            flash("Assignment updated successfully", "success")
            return redirect(url_for('assign_driver_to_vehicle_list', **_preserve_nav_from()))
        except Exception as e:
            db.session.rollback()
            flash(f"Error: {str(e)}", "danger")

    return render_template('assign_driver_to_vehicle_edit.html', form=form, driver=driver,
                           **_nav_back_ctx(url_for('assign_driver_to_vehicle_list')))


