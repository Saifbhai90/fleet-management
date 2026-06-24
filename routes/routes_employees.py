"""
Employees: Workforce Lifecycle, Assignments, Import/Export, Profile Reports.

Extracted from routes.py to reduce file size.
"""

from flask import (
    render_template, redirect, url_for, flash, request,
    session, jsonify, make_response, abort,
)
from app import app, db, csrf
from models import (
    Employee, EmployeeDocument, EmployeePost, EmployeeAssignment,
    Project, District, Company, Vehicle, Driver,
    User, Role, SystemSetting, ActivityLog,
    project_district, employee_project, employee_district,
)
from forms import (
    EmployeeForm, EmployeeAssignmentForm, EmployeeLeftForm,
    EmployeeImportForm,
)
from datetime import datetime, date, timedelta
from sqlalchemy import func, text, or_, and_
from werkzeug.utils import secure_filename
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
    _sync_user_active_by_cnic,
    _sync_user_full_name_by_cnic,
    _create_user_for_employee_or_driver,
    _get_user_scope,
    require_login,
    _nav_back_ctx,
    _workforce_nav_back,
    _log_employee_assignment,
    enforce_data_freeze,
    _cnic_digits,
    _master_nav_back,
)

import inspect
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import joinedload
import xlsxwriter
from forms import EmployeeDocumentForm, EmployeeFormStep1, EmployeeFormStep2
from utils import format_cnic, generate_excel_template
from flask import send_file
@app.route('/employees')
def employees_list():
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
    sort_by = request.args.get('sort_by', 'name')
    sort_order = request.args.get('sort_order', 'asc')

    def _dmy(s):
        from datetime import datetime as _dt
        try: return _dt.strptime(s, '%d-%m-%Y').date() if s else None
        except ValueError: return None

    from_date = _dmy(from_date_str)
    to_date = _dmy(to_date_str)

    query = Employee.query

    # Apply user data scope - employees assigned to user's projects/districts
    if not is_master_or_admin:
        if allowed_projects or allowed_districts:
            from sqlalchemy import or_
            filters = []
            if allowed_projects:
                filters.append(Employee.projects.any(Project.id.in_(list(allowed_projects))))
            if allowed_districts:
                filters.append(Employee.districts.any(District.id.in_(list(allowed_districts))))
            if filters:
                query = query.filter(or_(*filters))

    if search:
        flt = _multi_word_filter(search,
            Employee.name, Employee.code, Employee.department,
            Employee.cnic_no, Employee.phone1, Employee.father_name)
        if flt is not None:
            query = query.filter(flt)
    if from_date:
        query = query.filter(Employee.joining_date >= from_date)
    if to_date:
        query = query.filter(Employee.joining_date <= to_date)

    # Apply sorting based on sort_by column
    if sort_by == 'code':
        order_col = Employee.code.asc() if sort_order == 'asc' else Employee.code.desc()
    elif sort_by == 'cnic':
        order_col = Employee.cnic_no.asc() if sort_order == 'asc' else Employee.cnic_no.desc()
    elif sort_by == 'post':
        order_col = Employee.post_id.asc() if sort_order == 'asc' else Employee.post_id.desc()
    elif sort_by == 'department':
        order_col = Employee.department.asc() if sort_order == 'asc' else Employee.department.desc()
    elif sort_by == 'phone':
        order_col = Employee.phone.asc() if sort_order == 'asc' else Employee.phone.desc()
    else:  # default to name
        order_col = Employee.name.asc() if sort_order == 'asc' else Employee.name.desc()

    pagination = query.order_by(order_col).paginate(page=page, per_page=per_page, error_out=False)
    employees = pagination.items
    return render_template('employees_list.html', employees=employees, search=search,
                           from_date=from_date_str, to_date=to_date_str,
                           pagination=pagination, per_page=per_page, sort_by=sort_by, sort_order=sort_order,
                           **_master_nav_back())



@app.route('/employee/add', methods=['GET', 'POST'])
@app.route('/employee/edit/<int:id>', methods=['GET', 'POST'])
def employee_form(id=None):
    # Build Employee Post dropdown (id-based, shows full + short name)
    posts = EmployeePost.query.order_by(EmployeePost.full_name).all()
    post_choices = [(0, '-- Select Post --')] + [
        (p.id, f"{p.full_name} ({p.short_name})") for p in posts
    ]

    # Department history (distinct existing departments)
    dept_rows = (
        db.session.query(Employee.department)
        .filter(Employee.department.isnot(None), Employee.department != '')
        .distinct()
        .order_by(Employee.department)
        .all()
    )
    departments = [row[0] for row in dept_rows]

    # Tab: 1=Basic, 2=Contact, 3=Documents (optional)
    tab = request.args.get('tab', 1, type=int)
    if tab < 1 or tab > 3:
        tab = 1
    if not id and tab > 1:
        return redirect(url_for('employee_form', tab=1))

    emp = db.session.get(Employee, id) if id else None
    if id and not emp:
        abort(404)
    title = f"Edit Employee - {emp.name}" if emp else "Add New Employee"

    form1 = EmployeeFormStep1()
    form1.post_id.choices = post_choices
    form2 = EmployeeFormStep2()

    if emp:
        form1.code.data = emp.code
        form1.name.data = emp.name
        form1.post_id.data = emp.post_id or 0
        form1.department.data = emp.department or ''
        form1.father_name.data = emp.father_name or ''
        form1.place_of_birth.data = emp.place_of_birth or ''
        form1.dob.data = parse_date(emp.dob) if isinstance(emp.dob, str) else emp.dob
        form1.education.data = emp.education or ''
        form1.marital_status.data = emp.marital_status or ''
        form1.cnic_no.data = emp.cnic_no or ''
        form1.district.data = emp.district or ''
        form1.address.data = emp.address or ''
        form1.joining_date.data = parse_date(emp.joining_date) if isinstance(emp.joining_date, str) else emp.joining_date
        form2.phone1.data = emp.phone1 or ''
        form2.phone2.data = emp.phone2 or ''
        form2.email.data = emp.email or ''
        form2.status.data = emp.status or 'Active'
        form2.bank_name.data = emp.bank_name or ''
        form2.account_no.data = emp.account_no or ''
        form2.account_title.data = emp.account_title or ''
        form2.remarks.data = emp.remarks or ''

    doc_form = EmployeeDocumentForm()
    employee_documents = list(emp.documents) if emp else []

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'save_step_1':
            form1 = EmployeeFormStep1(request.form)
            form1.post_id.choices = post_choices
            if form1.validate():
                try:
                    code_val = (form1.code.data or '').strip()
                    if not code_val:
                        year = pk_now().year
                        last_emp = Employee.query.order_by(Employee.id.desc()).first()
                        next_num = (last_emp.id + 1) if last_emp else 1
                        code_val = f"EMP-{year}-{next_num:04d}"
                    if not emp:
                        emp = Employee(code=code_val)
                        db.session.add(emp)
                    emp.code = code_val
                    emp.name = (form1.name.data or '').strip()
                    emp.post_id = form1.post_id.data if form1.post_id.data else None
                    emp.department = (form1.department.data or '').strip()
                    emp.father_name = (form1.father_name.data or '').strip()
                    emp.place_of_birth = (form1.place_of_birth.data or '').strip()
                    emp.dob = form1.dob.data
                    emp.education = (form1.education.data or '').strip()
                    emp.marital_status = (form1.marital_status.data or '').strip()
                    emp.cnic_no = (form1.cnic_no.data or '').strip()
                    emp.district = (form1.district.data or '').strip()
                    emp.address = (form1.address.data or '').strip()
                    emp.joining_date = form1.joining_date.data
                    db.session.commit()
                    if emp.cnic_no and (emp.cnic_no or '').strip():
                        _sync_user_full_name_by_cnic(emp.cnic_no.strip(), emp.name)
                    try:
                        from routes_finance import _auto_create_coa_account
                        _auto_create_coa_account('employee', emp.id, emp.name, extra_label=emp.code)
                        db.session.commit()
                    except Exception:
                        pass
                    flash('Step 1 saved. Ab Contact & Job bharo.', 'success')
                    return redirect(url_for('employee_form', id=emp.id, tab=2))
                except Exception as e:
                    db.session.rollback()
                    flash(f'Error: {str(e)}', 'danger')
            tab = 1

        elif action == 'save_step_2' and emp:
            form2 = EmployeeFormStep2(request.form)
            if form2.validate():
                try:
                    emp.phone1 = (form2.phone1.data or '').strip()
                    emp.phone2 = (form2.phone2.data or '').strip()
                    emp.email = (form2.email.data or '').strip()
                    # joining_date pehle hi Step 1 me required aur save ho chuki hoti hai
                    emp.status = (form2.status.data or 'Active').strip()
                    emp.bank_name = (form2.bank_name.data or '').strip()
                    emp.account_no = (form2.account_no.data or '').strip()
                    emp.account_title = (form2.account_title.data or '').strip()
                    emp.remarks = (form2.remarks.data or '').strip()
                    db.session.commit()
                    if emp.cnic_no and (emp.status or '').strip() == 'Active':
                        _sync_user_active_by_cnic(emp.cnic_no.strip(), True)
                    flash('Step 2 saved. Documents tab par jayein (optional) ya Done dabayein.', 'success')
                    return redirect(url_for('employee_form', id=emp.id, tab=3))
                except Exception as e:
                    db.session.rollback()
                    flash(f'Error: {str(e)}', 'danger')
            tab = 2

        elif action == 'add_document' and emp:
            doc_form = EmployeeDocumentForm()
            doc_file = request.files.get('document')
            if doc_file and doc_file.filename:
                try:
                    from werkzeug.utils import secure_filename
                    ext = os.path.splitext(doc_file.filename)[1].lower() or '.bin'
                    allowed = {'.pdf', '.jpg', '.jpeg', '.png', '.gif', '.webp', '.doc', '.docx'}
                    if ext not in allowed:
                        flash('Sirf PDF, image, ya Word file upload karein.', 'danger')
                    else:
                        subdir = os.path.join(app.config['UPLOAD_FOLDER'], 'employees', str(emp.id))
                        os.makedirs(subdir, exist_ok=True)
                        fname = secure_filename(doc_file.filename)
                        if not fname:
                            fname = 'doc' + ext
                        file_path = os.path.join(subdir, fname)
                        doc_file.save(file_path)
                        rel_path = os.path.join('employees', str(emp.id), fname).replace('\\', '/')
                        doc_title = (request.form.get('title') or '').strip() or fname
                        doc = EmployeeDocument(employee_id=emp.id, title=doc_title or None, file_path=rel_path)
                        db.session.add(doc)
                        db.session.commit()
                        flash('Document save ho gaya.', 'success')
                    return redirect(url_for('employee_form', id=emp.id, tab=3))
                except Exception as e:
                    db.session.rollback()
                    flash(f'Error: {str(e)}', 'danger')
            else:
                flash('Pehle file select karein.', 'warning')
                return redirect(url_for('employee_form', id=emp.id, tab=3))
            tab = 3

    step1_done = emp is not None
    step2_done = emp is not None
    employee_documents = list(emp.documents) if emp else []
    return render_template(
        'employee_form.html',
        form1=form1, form2=form2, doc_form=doc_form,
        title=title, employee=emp, departments=departments,
        tab=tab, step1_done=step1_done, step2_done=step2_done,
        employee_documents=employee_documents,
        **_nav_back_ctx(url_for('employees_list')),
    )



@app.route('/employee/<int:id>/print')
def employee_profile_print(id):
    """Professional employee profile view with PDF/Print/Image export."""
    emp = Employee.query.get_or_404(id)
    projects = list(emp.projects)
    districts = list(emp.districts)
    documents = list(emp.documents)
    return render_template(
        'employee_profile_print.html',
        employee=emp,
        projects=projects,
        districts=districts,
        documents=documents,
        now=datetime.now,
    )



@app.route('/employee/<int:id>/document/<int:doc_id>/delete', methods=['POST'])
def employee_document_delete(id, doc_id):
    """Delete one employee document (optional tab)."""
    emp = Employee.query.get_or_404(id)
    doc = EmployeeDocument.query.filter_by(id=doc_id, employee_id=emp.id).first_or_404()
    try:
        base = os.path.abspath(app.config['UPLOAD_FOLDER'])
        full_path = os.path.join(base, doc.file_path)
        if os.path.isfile(full_path):
            os.remove(full_path)
        db.session.delete(doc)
        db.session.commit()
        flash('Document hata diya gaya.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error: {str(e)}', 'danger')
    return redirect(url_for('employee_form', id=emp.id, tab=3))



@app.route('/employee/assignment', methods=['GET', 'POST'])
def employee_assignment_form():
    """Separate form for Project & District assignment. Save here saves employee (from session draft) + assignment."""
    projects_list = Project.query.order_by(Project.name).all()
    districts_list = District.query.order_by(District.name).all()
    project_choices = [(p.id, p.name) for p in projects_list]
    district_choices = [(d.id, d.name) for d in districts_list]

    form = EmployeeAssignmentForm()
    form.project_ids.choices = project_choices
    form.district_ids.choices = district_choices

    draft = session.get('employee_draft')
    draft_employee_id = session.get('employee_draft_id')
    emp = None
    if draft_employee_id:
        emp = db.session.get(Employee, draft_employee_id)
    if not draft and not emp:
        flash('Pehle Add New Employee form par jaa kar details bharo aur "Project & District Assignment" dabayein.', 'warning')
        return redirect(url_for('employee_form'))

    if request.method == 'GET':
        if emp:
            form.project_ids.data = [p.id for p in emp.projects]
            form.district_ids.data = [d.id for d in emp.districts]
            draft_summary = f"{emp.code} — {emp.name}"
        elif draft:
            form.project_ids.data = draft.get('project_ids') or []
            form.district_ids.data = draft.get('district_ids') or []
            draft_summary = f"{draft.get('code') or '-'} — {draft.get('name') or '-'}"
        else:
            draft_summary = None
        return render_template('employee_assignment_form.html', form=form, draft=draft, employee=emp, draft_summary=draft_summary)

    # POST: Save employee (if draft) + assignment
    if form.validate_on_submit():
        try:
            if draft and not emp:
                # Create new employee from draft
                code_val = (draft.get('code') or '').strip()
                if not code_val:
                    year = pk_now().year
                    last_emp = Employee.query.order_by(Employee.id.desc()).first()
                    next_num = (last_emp.id + 1) if last_emp else 1
                    code_val = f"EMP-{year}-{next_num:04d}"
                emp = Employee(
                    code=code_val,
                    name=(draft.get('name') or '').strip(),
                    post_id=draft.get('post_id') if draft.get('post_id') else None,
                    department=(draft.get('department') or '').strip(),
                    father_name=(draft.get('father_name') or '').strip(),
                    place_of_birth=(draft.get('place_of_birth') or '').strip(),
                    dob=parse_date(draft['dob']) if isinstance(draft.get('dob'), str) else None,
                    education=(draft.get('education') or '').strip(),
                    marital_status=(draft.get('marital_status') or '').strip(),
                    cnic_no=(draft.get('cnic_no') or '').strip(),
                    district=(draft.get('district') or '').strip(),
                    address=(draft.get('address') or '').strip(),
                    phone1=(draft.get('phone1') or '').strip(),
                    phone2=(draft.get('phone2') or '').strip(),
                    email=(draft.get('email') or '').strip(),
                    joining_date=parse_date(draft['joining_date']) if isinstance(draft.get('joining_date'), str) else None,
                    status=(draft.get('status') or 'Active').strip(),
                    bank_name=(draft.get('bank_name') or '').strip(),
                    account_no=(draft.get('account_no') or '').strip(),
                    account_title=(draft.get('account_title') or '').strip(),
                    remarks=(draft.get('remarks') or '').strip(),
                )
                db.session.add(emp)
                db.session.flush()
                # Create login user if Active + CNIC
                if emp.cnic_no and (emp.status or '').strip() == 'Active':
                    post = db.session.get(EmployeePost, emp.post_id) if emp.post_id else None
                    role_id = post.role_id if post else None
                    _create_user_for_employee_or_driver(emp.cnic_no.strip(), emp.name, emp.post_id, role_id)
            elif not emp:
                flash('Session expired. Pehle employee form bharo.', 'danger')
                session.pop('employee_draft', None)
                session.pop('employee_draft_id', None)
                return redirect(url_for('employee_form'))

            project_ids = [x for x in (form.project_ids.data or []) if x]
            district_ids = [x for x in (form.district_ids.data or []) if x]
            emp.projects = [db.session.get(Project, pid) for pid in project_ids if db.session.get(Project, pid)]
            emp.districts = [db.session.get(District, did) for did in district_ids if db.session.get(District, did)]

            today = pk_date()
            for pid in project_ids:
                _log_employee_assignment(emp.id, 'initial', project_id=pid, effective_date=today)
            for did in district_ids:
                _log_employee_assignment(emp.id, 'initial', district_id=did, effective_date=today)

            db.session.commit()
            try:
                from routes_finance import _auto_create_coa_account
                _auto_create_coa_account('employee', emp.id, emp.name, extra_label=emp.code)
                db.session.commit()
            except Exception:
                pass

            session.pop('employee_draft', None)
            session.pop('employee_draft_id', None)
            flash('Employee aur Project/District assignment dono save ho gaye.', 'success')
            return redirect(url_for('employees_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {str(e)}', 'danger')

    form.project_ids.choices = project_choices
    form.district_ids.choices = district_choices
    draft_summary = f"{emp.code} — {emp.name}" if emp else (f"{draft.get('code') or '-'} — {draft.get('name') or '-'}" if draft else None)
    return render_template('employee_assignment_form.html', form=form, draft=draft, employee=emp, draft_summary=draft_summary)



@app.route('/employee/delete/<int:id>', methods=['POST'])
def employee_delete(id):
    emp = Employee.query.get_or_404(id)
    try:
        db.session.delete(emp)
        db.session.commit()
        flash('Employee deleted.', 'success')
    except Exception as e:
        flash(f'Error deleting employee: {str(e)}', 'danger')
    return redirect(url_for('employees_list'))



@app.route('/employee/lifecycle/assign', methods=['GET', 'POST'])
def employee_lifecycle_assign():
    active_emps = Employee.query.filter(Employee.status != 'Left').order_by(Employee.name).all()
    emp_choices = [(0, '-- Select Employee --')] + [(e.id, f"{e.name} ({e.code})") for e in active_emps]
    projects_list = Project.query.order_by(Project.name).all()
    districts_list = District.query.order_by(District.name).all()
    project_choices = [(p.id, p.name) for p in projects_list]
    district_choices = [(d.id, d.name) for d in districts_list]

    sel_emp_id = 0
    sel_project_ids = []
    sel_district_ids = []
    sel_date = ''
    sel_remarks = ''

    if request.method == 'POST':
        sel_emp_id = request.form.get('employee_id', 0, type=int)
        sel_project_ids = [int(x) for x in request.form.getlist('project_ids') if x]
        sel_district_ids = [int(x) for x in request.form.getlist('district_ids') if x]
        sel_date = request.form.get('effective_date', '').strip()
        sel_remarks = request.form.get('remarks', '').strip()

        emp = db.session.get(Employee, sel_emp_id) if sel_emp_id else None
        if not emp:
            flash('Employee select karein.', 'danger')
        elif not sel_project_ids or not sel_district_ids:
            flash('Kam se kam 1 Project AUR 1 District dono select karein.', 'danger')
        else:
            try:
                eff_date = parse_date(sel_date) if sel_date else pk_date()
                old_project_ids = set(p.id for p in emp.projects)
                old_district_ids = set(d.id for d in emp.districts)
                new_project_ids = set(sel_project_ids)
                new_district_ids = set(sel_district_ids)

                for pid in sel_project_ids:
                    proj = db.session.get(Project, pid)
                    if proj and proj not in emp.projects.all():
                        emp.projects.append(proj)
                for did in sel_district_ids:
                    dist = db.session.get(District, did)
                    if dist and dist not in emp.districts.all():
                        emp.districts.append(dist)

                is_initial = not old_project_ids and not old_district_ids
                action_type = 'initial' if is_initial else 'assign_project'
                for pid in (new_project_ids - old_project_ids):
                    _log_employee_assignment(emp.id, action_type, project_id=pid,
                                             effective_date=eff_date, remarks=sel_remarks)
                action_type_d = 'initial' if is_initial else 'assign_district'
                for did in (new_district_ids - old_district_ids):
                    _log_employee_assignment(emp.id, action_type_d, district_id=did,
                                             effective_date=eff_date, remarks=sel_remarks)

                db.session.commit()
                added = len(new_project_ids - old_project_ids) + len(new_district_ids - old_district_ids)
                flash(f'{added} assignment(s) saved for {emp.name}.', 'success')
                return redirect(url_for('employee_lifecycle_assign_list'))
            except Exception as e:
                db.session.rollback()
                flash(f'Error: {str(e)}', 'danger')

    return render_template('employee_lifecycle_assign.html',
                           title='Assign District/Project',
                           emp_choices=emp_choices,
                           project_choices=project_choices,
                           district_choices=district_choices,
                           sel_emp_id=sel_emp_id,
                           sel_project_ids=sel_project_ids,
                           sel_district_ids=sel_district_ids,
                           sel_date=sel_date,
                           sel_remarks=sel_remarks, **_workforce_nav_back())



@app.route('/employee/lifecycle/deassign', methods=['GET', 'POST'])
def employee_lifecycle_deassign():
    active_emps = Employee.query.filter(Employee.status != 'Left').order_by(Employee.name).all()
    emp_choices = [(0, '-- Select Employee --')] + [(e.id, f"{e.name} ({e.code})") for e in active_emps]

    sel_emp_id = request.args.get('employee_id', 0, type=int)
    sel_project_ids = []
    sel_district_ids = []
    sel_date = ''
    sel_reason = ''
    sel_remarks = ''
    cur_projects = []
    cur_districts = []

    if request.method == 'POST':
        action = request.form.get('action', '')
        sel_emp_id = request.form.get('employee_id', 0, type=int)

        if action == 'select_employee':
            pass
        else:
            sel_project_ids = [int(x) for x in request.form.getlist('project_ids') if x]
            sel_district_ids = [int(x) for x in request.form.getlist('district_ids') if x]
            sel_date = request.form.get('effective_date', '').strip()
            sel_reason = request.form.get('reason', '').strip()
            sel_remarks = request.form.get('remarks', '').strip()

            emp = db.session.get(Employee, sel_emp_id) if sel_emp_id else None
            if not emp:
                flash('Employee select karein.', 'danger')
            elif not sel_project_ids and not sel_district_ids:
                flash('Kam se kam 1 Project ya 1 District select karein jo remove karna hai.', 'danger')
            else:
                try:
                    eff_date = parse_date(sel_date) if sel_date else pk_date()
                    removed = 0
                    for pid in sel_project_ids:
                        proj = db.session.get(Project, pid)
                        if proj and proj in emp.projects.all():
                            emp.projects.remove(proj)
                            _log_employee_assignment(emp.id, 'deassign_project', project_id=pid,
                                                     effective_date=eff_date, reason=sel_reason, remarks=sel_remarks)
                            removed += 1
                    for did in sel_district_ids:
                        dist = db.session.get(District, did)
                        if dist and dist in emp.districts.all():
                            emp.districts.remove(dist)
                            _log_employee_assignment(emp.id, 'deassign_district', district_id=did,
                                                     effective_date=eff_date, reason=sel_reason, remarks=sel_remarks)
                            removed += 1
                    db.session.commit()
                    flash(f'{removed} assignment(s) removed from {emp.name}.', 'success')
                    return redirect(url_for('employee_lifecycle_deassign_list'))
                except Exception as e:
                    db.session.rollback()
                    flash(f'Error: {str(e)}', 'danger')

    emp_name = ''
    if sel_emp_id:
        emp = db.session.get(Employee, sel_emp_id)
        if emp:
            cur_projects = list(emp.projects)
            cur_districts = list(emp.districts)
            emp_name = f"{emp.name} ({emp.code})"

    return render_template('employee_lifecycle_deassign.html', title='Remove Assignment',
                           emp_choices=emp_choices, cur_projects=cur_projects, cur_districts=cur_districts,
                           sel_emp_id=sel_emp_id, emp_name=emp_name,
                           sel_project_ids=sel_project_ids, sel_district_ids=sel_district_ids,
                           sel_date=sel_date, sel_reason=sel_reason, sel_remarks=sel_remarks, **_workforce_nav_back())



@app.route('/employee/lifecycle/left', methods=['GET', 'POST'])
def employee_lifecycle_left():
    form = EmployeeLeftForm()
    active_emps = Employee.query.filter(Employee.status != 'Left').order_by(Employee.name).all()
    form.employee_id.choices = [(0, '-- Select Employee --')] + [(e.id, f"{e.name} ({e.code})") for e in active_emps]

    if form.validate_on_submit():
        emp = db.session.get(Employee, form.employee_id.data)
        if not emp:
            flash('Employee not found.', 'danger')
            return redirect(url_for('employee_lifecycle_left'))
        try:
            reason_val = form.reason.data
            if reason_val == 'Other':
                reason_val = (form.other_reason.data or '').strip() or 'Other'
            emp.status = 'Left'
            _log_employee_assignment(emp.id, 'left',
                                     effective_date=form.leave_date.data,
                                     reason=reason_val, remarks=form.remarks.data)
            db.session.commit()
            flash(f'{emp.name} marked as Left.', 'success')
            return redirect(url_for('employee_lifecycle_left_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {str(e)}', 'danger')

    return render_template('employee_lifecycle_left.html', form=form, title='Employee Left',
                           active_emps=active_emps, **_workforce_nav_back())



@app.route('/employee/lifecycle/rejoin', methods=['GET', 'POST'])
def employee_lifecycle_rejoin():
    left_emps = Employee.query.filter_by(status='Left').order_by(Employee.name).all()
    emp_choices = [(0, '-- Select Employee --')] + [(e.id, f"{e.name} ({e.code})") for e in left_emps]
    projects_list = Project.query.order_by(Project.name).all()
    districts_list = District.query.order_by(District.name).all()
    project_choices = [(p.id, p.name) for p in projects_list]
    district_choices = [(d.id, d.name) for d in districts_list]

    sel_emp_id = 0
    sel_project_ids = []
    sel_district_ids = []
    sel_date = ''
    sel_remarks = ''

    if request.method == 'POST':
        sel_emp_id = request.form.get('employee_id', 0, type=int)
        sel_project_ids = [int(x) for x in request.form.getlist('project_ids') if x]
        sel_district_ids = [int(x) for x in request.form.getlist('district_ids') if x]
        sel_date = request.form.get('rejoin_date', '').strip()
        sel_remarks = request.form.get('remarks', '').strip()

        emp = db.session.get(Employee, sel_emp_id) if sel_emp_id else None
        if not emp:
            flash('Employee select karein.', 'danger')
        elif not sel_project_ids or not sel_district_ids:
            flash('Kam se kam 1 Project AUR 1 District dono select karein.', 'danger')
        else:
            try:
                eff_date = parse_date(sel_date) if sel_date else pk_date()
                emp.status = 'Active'
                emp.projects = [db.session.get(Project, pid) for pid in sel_project_ids if db.session.get(Project, pid)]
                emp.districts = [db.session.get(District, did) for did in sel_district_ids if db.session.get(District, did)]
                _log_employee_assignment(emp.id, 'rejoin', effective_date=eff_date, remarks=sel_remarks)
                for pid in sel_project_ids:
                    _log_employee_assignment(emp.id, 'assign_project', project_id=pid, effective_date=eff_date)
                for did in sel_district_ids:
                    _log_employee_assignment(emp.id, 'assign_district', district_id=did, effective_date=eff_date)
                db.session.commit()
                flash(f'{emp.name} rejoined successfully.', 'success')
                return redirect(url_for('employee_lifecycle_rejoin_list'))
            except Exception as e:
                db.session.rollback()
                flash(f'Error: {str(e)}', 'danger')

    return render_template('employee_lifecycle_rejoin.html', title='Employee Rejoin',
                           emp_choices=emp_choices, project_choices=project_choices,
                           district_choices=district_choices, sel_emp_id=sel_emp_id,
                           sel_project_ids=sel_project_ids, sel_district_ids=sel_district_ids,
                           sel_date=sel_date, sel_remarks=sel_remarks, **_workforce_nav_back())



@app.route('/employee/lifecycle/history')
def employee_lifecycle_history():
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    ctx = get_user_context(user_id) if user_id else {}
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)
    search = request.args.get('search', '').strip()
    action_filter = request.args.get('action', '').strip()
    district_id = request.args.get('district_id', 0, type=int)
    project_id = request.args.get('project_id', 0, type=int)

    try:
        _insp = inspect(db.engine)
        if 'employee_assignment' not in _insp.get_table_names():
            db.create_all()
    except Exception:
        pass

    try:
        query = EmployeeAssignment.query.options(
            joinedload(EmployeeAssignment.employee),
            joinedload(EmployeeAssignment.district),
            joinedload(EmployeeAssignment.project),
            joinedload(EmployeeAssignment.created_by),
        )
        if search:
            query = query.join(Employee).filter(
                or_(Employee.name.ilike(f'%{search}%'), Employee.code.ilike(f'%{search}%'))
            )
        if action_filter:
            query = query.filter(EmployeeAssignment.action == action_filter)
        if district_id:
            query = query.filter(EmployeeAssignment.district_id == district_id)
        if project_id:
            query = query.filter(EmployeeAssignment.project_id == project_id)

        if ctx.get('district_ids'):
            emp_ids_sub = db.session.query(employee_district.c.employee_id).filter(
                employee_district.c.district_id.in_(ctx['district_ids'])
            )
            query = query.filter(EmployeeAssignment.employee_id.in_(emp_ids_sub))

        query = query.order_by(EmployeeAssignment.effective_date.desc(), EmployeeAssignment.created_at.desc())
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    except OperationalError:
        db.session.rollback()
        try:
            db.create_all()
            db.session.commit()
        except Exception:
            pass
        pagination = EmployeeAssignment.query.paginate(page=1, per_page=per_page, error_out=False)

    districts = District.query.order_by(District.name).all()
    projects = Project.query.order_by(Project.name).all()
    actions = list(EmployeeAssignment.ACTION_LABELS.items())

    raw_records = pagination.items
    grouped = []
    seen = {}
    for r in raw_records:
        key = (r.employee_id, r.effective_date, r.action)
        if key not in seen:
            seen[key] = {
                'employee': r.employee,
                'employee_id': r.employee_id,
                'effective_date': r.effective_date,
                'action': r.action,
                'action_label': r.action_label,
                'action_color': r.action_color,
                'districts': [],
                'projects': [],
                'reason': r.reason,
                'remarks': r.remarks,
                'created_by': r.created_by,
            }
            grouped.append(seen[key])
        entry = seen[key]
        if r.district and r.district.name not in entry['districts']:
            entry['districts'].append(r.district.name)
        if r.project and r.project.name not in entry['projects']:
            entry['projects'].append(r.project.name)

    return render_template('employee_lifecycle_history.html',
                           records=grouped, pagination=pagination,
                           search=search, action_filter=action_filter,
                           district_id=district_id, project_id=project_id,
                           districts=districts, projects=projects,
                           actions=actions, per_page=per_page,
                           title='Employee Assignment History', **_workforce_nav_back())



@app.route('/employee/lifecycle/history/export')
def employee_lifecycle_history_export():
    search = request.args.get('search', '').strip()
    action_filter = request.args.get('action', '').strip()

    try:
        _insp = inspect(db.engine)
        if 'employee_assignment' not in _insp.get_table_names():
            db.create_all()
    except Exception:
        pass

    query = EmployeeAssignment.query.options(
        joinedload(EmployeeAssignment.employee),
        joinedload(EmployeeAssignment.district),
        joinedload(EmployeeAssignment.project),
    ).order_by(EmployeeAssignment.effective_date.desc())

    if search:
        query = query.join(Employee).filter(
            or_(Employee.name.ilike(f'%{search}%'), Employee.code.ilike(f'%{search}%'))
        )
    if action_filter:
        query = query.filter(EmployeeAssignment.action == action_filter)

    records = query.all()
    output = BytesIO()
    wb = xlsxwriter.Workbook(output)
    ws = wb.add_worksheet('History')
    headers = ['#', 'Employee', 'Code', 'Action', 'District', 'Project', 'Date', 'Reason', 'Remarks']
    hfmt = wb.add_format({'bold': True, 'bg_color': '#4472C4', 'font_color': 'white', 'border': 1})
    dfmt = wb.add_format({'border': 1, 'text_wrap': True})
    for c, h in enumerate(headers):
        ws.write(0, c, h, hfmt)
    for i, r in enumerate(records, 1):
        ws.write(i, 0, i, dfmt)
        ws.write(i, 1, r.employee.name if r.employee else '', dfmt)
        ws.write(i, 2, r.employee.code if r.employee else '', dfmt)
        ws.write(i, 3, r.action_label, dfmt)
        ws.write(i, 4, r.district.name if r.district else '-', dfmt)
        ws.write(i, 5, r.project.name if r.project else '-', dfmt)
        ws.write(i, 6, r.effective_date.strftime('%d-%m-%Y') if r.effective_date else '', dfmt)
        ws.write(i, 7, r.reason or '', dfmt)
        ws.write(i, 8, r.remarks or '', dfmt)
    ws.autofit()
    wb.close()
    output.seek(0)
    return send_file(output, download_name='employee_assignment_history.xlsx', as_attachment=True,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')



@app.route('/employee/lifecycle/history/print')
def employee_lifecycle_history_print():
    search = request.args.get('search', '').strip()
    action_filter = request.args.get('action', '').strip()

    try:
        _insp = inspect(db.engine)
        if 'employee_assignment' not in _insp.get_table_names():
            db.create_all()
    except Exception:
        pass

    query = EmployeeAssignment.query.options(
        joinedload(EmployeeAssignment.employee),
        joinedload(EmployeeAssignment.district),
        joinedload(EmployeeAssignment.project),
    ).order_by(EmployeeAssignment.effective_date.desc())

    if search:
        query = query.join(Employee).filter(
            or_(Employee.name.ilike(f'%{search}%'), Employee.code.ilike(f'%{search}%'))
        )
    if action_filter:
        query = query.filter(EmployeeAssignment.action == action_filter)

    records = query.all()
    return render_template('employee_lifecycle_history_print.html', records=records,
                           title='Employee Assignment History')



@app.route('/employee/<int:id>/profile')
def employee_profile_report(id):
    emp = Employee.query.get_or_404(id)
    projects = list(emp.projects)
    districts = list(emp.districts)
    documents = list(emp.documents)
    try:
        _insp = inspect(db.engine)
        if 'employee_assignment' not in _insp.get_table_names():
            db.create_all()
    except Exception:
        pass
    try:
        raw_history = EmployeeAssignment.query.filter_by(employee_id=emp.id)\
            .order_by(EmployeeAssignment.effective_date.desc(), EmployeeAssignment.created_at.desc()).all()
    except Exception:
        db.session.rollback()
        raw_history = []

    grouped_history = []
    seen_keys = {}
    for h in raw_history:
        key = (h.effective_date, h.action)
        if key not in seen_keys:
            seen_keys[key] = {
                'effective_date': h.effective_date,
                'action': h.action,
                'action_label': h.action_label,
                'action_color': h.action_color,
                'districts': [],
                'projects': [],
                'reason': h.reason,
                'remarks': h.remarks,
            }
            grouped_history.append(seen_keys[key])
        entry = seen_keys[key]
        if h.district and h.district.name not in entry['districts']:
            entry['districts'].append(h.district.name)
        if h.project and h.project.name not in entry['projects']:
            entry['projects'].append(h.project.name)

    return render_template('employee_profile_report.html',
                           employee=emp, projects=projects, districts=districts,
                           documents=documents, history=grouped_history,
                           title=f'Employee Profile – {emp.name}')



def _employee_lifecycle_list(action_types, title, add_url, add_label, template_name):
    """Generic list for employee lifecycle filtered by action type(s)."""
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    ctx = get_user_context(user_id) if user_id else {}
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)
    search = request.args.get('search', '').strip()
    district_id = request.args.get('district_id', 0, type=int)
    project_id = request.args.get('project_id', 0, type=int)
    from_date = request.args.get('from_date', '').strip()
    to_date = request.args.get('to_date', '').strip()

    try:
        _insp = inspect(db.engine)
        if 'employee_assignment' not in _insp.get_table_names():
            db.create_all()
    except Exception:
        pass

    try:
        query = EmployeeAssignment.query.options(
            joinedload(EmployeeAssignment.employee),
            joinedload(EmployeeAssignment.district),
            joinedload(EmployeeAssignment.project),
            joinedload(EmployeeAssignment.created_by),
        ).filter(EmployeeAssignment.action.in_(action_types))

        if search:
            query = query.join(Employee).filter(
                or_(Employee.name.ilike(f'%{search}%'), Employee.code.ilike(f'%{search}%'))
            )
        if district_id:
            query = query.filter(EmployeeAssignment.district_id == district_id)
        if project_id:
            query = query.filter(EmployeeAssignment.project_id == project_id)
        if from_date:
            try:
                fd = parse_date(from_date)
                if fd:
                    query = query.filter(EmployeeAssignment.effective_date >= fd)
            except Exception:
                pass
        if to_date:
            try:
                td = parse_date(to_date)
                if td:
                    query = query.filter(EmployeeAssignment.effective_date <= td)
            except Exception:
                pass
        if ctx.get('district_ids'):
            emp_ids_sub = db.session.query(employee_district.c.employee_id).filter(
                employee_district.c.district_id.in_(ctx['district_ids'])
            )
            query = query.filter(EmployeeAssignment.employee_id.in_(emp_ids_sub))

        query = query.order_by(EmployeeAssignment.effective_date.desc(), EmployeeAssignment.created_at.desc())
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    except OperationalError:
        db.session.rollback()
        try:
            db.create_all()
            db.session.commit()
        except Exception:
            pass
        pagination = EmployeeAssignment.query.paginate(page=1, per_page=per_page, error_out=False)

    districts = District.query.order_by(District.name).all()
    projects = Project.query.order_by(Project.name).all()

    raw_records = pagination.items
    grouped = []
    seen = {}
    for r in raw_records:
        key = (r.employee_id, r.effective_date, r.action)
        if key not in seen:
            seen[key] = {
                'employee': r.employee,
                'employee_id': r.employee_id,
                'effective_date': r.effective_date,
                'action': r.action,
                'action_label': r.action_label,
                'action_color': r.action_color,
                'districts': [],
                'projects': [],
                'reason': r.reason,
                'remarks': r.remarks,
                'created_by': r.created_by,
            }
            grouped.append(seen[key])
        entry = seen[key]
        if r.district and r.district.name not in entry['districts']:
            entry['districts'].append(r.district.name)
        if r.project and r.project.name not in entry['projects']:
            entry['projects'].append(r.project.name)

    return render_template(template_name,
                           records=grouped, pagination=pagination,
                           search=search, district_id=district_id, project_id=project_id,
                           from_date=from_date, to_date=to_date,
                           districts=districts, projects=projects,
                           per_page=per_page, title=title,
                           add_url=add_url, add_label=add_label,
                           **_workforce_nav_back())



@app.route('/employee/lifecycle/assign/list')
def employee_lifecycle_assign_list():
    """Show employees with their current district+project assignments grouped."""
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    ctx = get_user_context(user_id) if user_id else {}
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)
    search = request.args.get('search', '').strip()
    district_id = request.args.get('district_id', 0, type=int)
    project_id = request.args.get('project_id', 0, type=int)

    query = Employee.query

    if search:
        query = query.filter(or_(Employee.name.ilike(f'%{search}%'), Employee.code.ilike(f'%{search}%')))

    if district_id:
        sub = db.session.query(employee_district.c.employee_id).filter(employee_district.c.district_id == district_id)
        query = query.filter(Employee.id.in_(sub))
    if project_id:
        sub = db.session.query(employee_project.c.employee_id).filter(employee_project.c.project_id == project_id)
        query = query.filter(Employee.id.in_(sub))

    if ctx.get('district_ids'):
        sub = db.session.query(employee_district.c.employee_id).filter(employee_district.c.district_id.in_(ctx['district_ids']))
        query = query.filter(Employee.id.in_(sub))

    query = query.order_by(Employee.name)
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    rows = []
    for emp in pagination.items:
        emp_districts = list(emp.districts)
        emp_projects = list(emp.projects)
        last_ea = EmployeeAssignment.query.filter(
            EmployeeAssignment.employee_id == emp.id,
            EmployeeAssignment.action.in_(['assign_district', 'assign_project', 'initial'])
        ).order_by(EmployeeAssignment.effective_date.desc()).first()
        rows.append({
            'employee': emp,
            'districts': emp_districts,
            'projects': emp_projects,
            'last_date': last_ea.effective_date if last_ea else None,
            'remarks': last_ea.remarks if last_ea else '',
            'created_by': last_ea.created_by if last_ea else None,
        })

    districts = District.query.order_by(District.name).all()
    projects = Project.query.order_by(Project.name).all()

    return render_template('employee_lifecycle_assign_list.html',
                           rows=rows, pagination=pagination,
                           search=search, district_id=district_id, project_id=project_id,
                           districts=districts, projects=projects,
                           per_page=per_page, title='Employee Assignments',
                           add_url='employee_lifecycle_assign', add_label='New Assignment', **_workforce_nav_back())



@app.route('/employee/lifecycle/deassign/list')
def employee_lifecycle_deassign_list():
    return _employee_lifecycle_list(
        ['deassign_district', 'deassign_project'],
        'Employee Deassignments', 'employee_lifecycle_deassign', 'Remove Assignment',
        'employee_lifecycle_list.html')



@app.route('/employee/lifecycle/left/list')
def employee_lifecycle_left_list():
    return _employee_lifecycle_list(
        ['left'],
        'Employees Left', 'employee_lifecycle_left', 'Mark Left',
        'employee_lifecycle_list.html')



@app.route('/employee/lifecycle/rejoin/list')
def employee_lifecycle_rejoin_list():
    return _employee_lifecycle_list(
        ['rejoin'],
        'Employee Rejoins', 'employee_lifecycle_rejoin', 'Rejoin',
        'employee_lifecycle_list.html')



@app.route('/api/employee/<int:emp_id>/assignments')
def api_employee_assignments(emp_id):
    # S-02: IDOR fix — only master/admin or the employee themselves can access
    user_id = session.get('user_id')
    ctx = get_user_context(user_id) if user_id else {}
    if not ctx.get('is_master_or_admin'):
        emp_record = ctx.get('employee_record')
        if not emp_record or emp_record.id != emp_id:
            return jsonify({'ok': False, 'error': 'Not authorized'}), 403
    emp = Employee.query.get_or_404(emp_id)
    return jsonify({
        'districts': [{'id': d.id, 'name': d.name} for d in emp.districts],
        'projects': [{'id': p.id, 'name': p.name} for p in emp.projects],
    })



@app.route('/employees/export')
def employees_export():
    """Export employees list (with optional search) to CSV."""
    search = request.args.get('search', '').strip()
    query = Employee.query
    if search:
        flt = _multi_word_filter(search, Employee.name, Employee.code, Employee.department, Employee.cnic_no)
        if flt is not None:
            query = query.filter(flt)
    employees = query.order_by(Employee.id.asc()).all()
    headers = ['ID', 'Code', 'Name', 'Father Name', 'CNIC', 'Post', 'Department', 'Phone', 'Email', 'Joining Date', 'Status']
    rows = []
    for e in employees:
        rows.append([
            e.id,
            e.code,
            e.name,
            e.father_name or '',
            e.cnic_no or '',
            e.post.full_name if e.post else '',
            e.department or '',
            e.phone1 or e.phone2 or '',
            e.email or '',
            e.joining_date.strftime('%Y-%m-%d') if e.joining_date else '',
            e.status or '',
        ])
    filename = 'employees.csv' if not search else f'employees_search_{search}.csv'
    return generate_csv_response(headers, rows, filename=filename)



@app.route('/employees/import/template')
def employees_import_template():
    """Download Excel template for employee import (Basic + Contact tabs data)."""
    headers = [
        'code', 'name', 'post', 'department',
        'father_name', 'place_of_birth', 'dob', 'education', 'marital_status',
        'cnic_no', 'district', 'address',
        'phone1', 'phone2', 'email',
        'joining_date', 'status',
        'bank_name', 'account_no', 'account_title', 'remarks'
    ]
    rows = [
        ['EMP-2026-0001', 'Ali Ahmad', 'Accountant', 'Accounts', 'Ahmad Khan', 'Lahore', '01-01-1990',
         'Graduate', 'Single', '32304-1111111-5', 'Lahore', 'House 1, Street 1, Lahore',
         '0300-1112233', '0300-2223344', 'ali@example.com',
         '01-01-2024', 'Active',
         'XYZ Bank', '1234567890', 'Ali Ahmad', ''],
        ['EMP-2026-0002', 'Sara Khan', 'Data Entry', 'IT', 'Khan Sahib', 'Karachi', '15-05-1992',
         'Intermediate', 'Married', '32304-2222222-5', 'Karachi', 'Block A, Karachi',
         '0300-3334455', '0300-4445566', 'sara@example.com',
         '15-02-2024', 'Active',
         '', '', '', ''],
    ]
    required_cols = ['name', 'post', 'department', 'father_name', 'cnic_no', 'phone1', 'phone2', 'joining_date']
    return generate_excel_template(headers, rows, required_columns=required_cols, filename='employees_import_template.xlsx')



@app.route('/employees/import', methods=['GET', 'POST'])
def employees_import():
    """Import employees from Excel/CSV (Basic + Contact data). Assignment & Documents form se fill karein."""
    form = EmployeeImportForm()
    if request.method == 'POST' and form.validate_on_submit():
        f = form.file.data
        if not f:
            flash('Please select an Excel/CSV file.', 'warning')
            return redirect(url_for('employees_import'))
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
                return redirect(url_for('employees_import'))

            required_cols = ['name', 'post', 'department', 'father_name', 'cnic_no', 'phone1', 'phone2', 'joining_date']
            missing = [c for c in required_cols if c not in df.columns]
            if missing:
                flash(f'Missing required columns: {", ".join(missing)}', 'danger')
                return redirect(url_for('employees_import'))

            def clean_text(value):
                if pd.isna(value):
                    return ''
                return str(value or '').strip()

            def parse_import_date(value):
                if pd.isna(value) or value is None or not str(value).strip():
                    return None
                if isinstance(value, str):
                    return parse_date(value)
                try:
                    return pd.to_datetime(value).date()
                except Exception:
                    return None

            def resolve_post_id(post_str):
                if pd.isna(post_str) or not str(post_str).strip():
                    return None
                p = str(post_str).strip()
                post = EmployeePost.query.filter(
                    db.or_(EmployeePost.full_name == p, EmployeePost.short_name == p)
                ).first()
                return post.id if post else None

            import_errors = []
            employees_to_add = []

            for idx, row in df.iterrows():
                row_num = idx + 2
                row_issues = []

                name = clean_text(row.get('name'))
                if not name:
                    row_issues.append('Field "name" is required.')
                post_str = clean_text(row.get('post'))
                post_id = resolve_post_id(post_str) if post_str else None
                if post_str and not post_id:
                    row_issues.append(f'Post "{post_str}" not found in Post master. Add post first or use exact name.')
                department = clean_text(row.get('department'))
                if not department:
                    row_issues.append('Field "department" is required.')
                father_name = clean_text(row.get('father_name'))
                if not father_name:
                    row_issues.append('Field "father_name" is required.')
                cnic_raw = row.get('cnic_no')
                cnic = clean_text(cnic_raw)
                if not cnic:
                    row_issues.append('Field "cnic_no" is required.')
                if cnic:
                    cnic = format_cnic(cnic)
                    existing_cnic = Employee.query.filter(Employee.cnic_no == cnic).first()
                    if existing_cnic:
                        row_issues.append(f'CNIC "{cnic}" already exists.')

                phone1 = clean_text(row.get('phone1'))
                if not phone1:
                    row_issues.append('Field "phone1" is required.')
                phone2 = clean_text(row.get('phone2'))
                if not phone2:
                    row_issues.append('Field "phone2" is required.')
                joining_date = parse_import_date(row.get('joining_date'))
                if not joining_date:
                    row_issues.append('Field "joining_date" is required (e.g. 01-01-2024).')

                code_val = clean_text(row.get('code'))
                if code_val:
                    existing_code = Employee.query.filter(Employee.code == code_val).first()
                    if existing_code:
                        row_issues.append(f'Employee code "{code_val}" already exists.')

                if row_issues:
                    ident = name or code_val or cnic or f'Row {row_num}'
                    for msg in row_issues:
                        import_errors.append({'row': row_num, 'identifier': ident, 'message': msg})
                    continue

                if not code_val:
                    year = pk_now().year
                    last_emp = Employee.query.order_by(Employee.id.desc()).first()
                    next_num = (last_emp.id + 1) if last_emp else 1
                    code_val = f"EMP-{year}-{next_num:04d}"

                status = clean_text(row.get('status')) or 'Active'
                if status not in ('Active', 'Inactive', 'Left'):
                    status = 'Active'

                emp = Employee(
                    code=code_val,
                    name=name,
                    post_id=post_id,
                    department=department,
                    father_name=father_name,
                    place_of_birth=clean_text(row.get('place_of_birth')),
                    dob=parse_import_date(row.get('dob')),
                    education=clean_text(row.get('education')) or None,
                    marital_status=clean_text(row.get('marital_status')) or None,
                    cnic_no=cnic,
                    district=clean_text(row.get('district')) or None,
                    address=clean_text(row.get('address')) or None,
                    phone1=phone1,
                    phone2=phone2,
                    email=clean_text(row.get('email')) or None,
                    joining_date=joining_date,
                    status=status,
                    bank_name=clean_text(row.get('bank_name')) or None,
                    account_no=clean_text(row.get('account_no')) or None,
                    account_title=clean_text(row.get('account_title')) or None,
                    remarks=clean_text(row.get('remarks')) or None,
                )
                employees_to_add.append(emp)

            if import_errors:
                db.session.rollback()
                flash('Import failed. Please fix errors shown below.', 'danger')
                return render_template('employees_import.html', form=form, import_errors=import_errors)

            for emp in employees_to_add:
                db.session.add(emp)
            db.session.commit()
            try:
                from routes_finance import _auto_create_coa_account
                for emp in employees_to_add:
                    _auto_create_coa_account('employee', emp.id, emp.name, extra_label=emp.code)
                db.session.commit()
            except Exception:
                pass
            flash(f'{len(employees_to_add)} employee(s) imported. Ab Assignment aur Documents form se assign karein.', 'success')
            return redirect(url_for('employees_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error importing: {str(e)}', 'danger')
    return render_template('employees_import.html', form=form)



@app.route('/employees/print')
def employees_print():
    """Print-friendly view of employees (browser print to PDF)."""
    search = request.args.get('search', '').strip()
    query = Employee.query
    if search:
        flt = _multi_word_filter(search, Employee.name, Employee.code, Employee.department, Employee.cnic_no)
        if flt is not None:
            query = query.filter(flt)
    employees = query.order_by(Employee.id.asc()).all()
    return render_template('employees_print.html', employees=employees, search=search)

