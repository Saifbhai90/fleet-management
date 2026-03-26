"""
Payroll Module Routes
Salary configuration, monthly payroll generation, finalization, payment, and payslip.
Supports both Employees and Drivers.
"""
from flask import render_template, request, redirect, url_for, flash, jsonify, session
from models import (db, Employee, EmployeeSalaryConfig, MonthlyPayroll,
                    DriverAttendance, Driver, Account, JournalEntry, JournalEntryLine, User,
                    Project, District)
from forms import SalaryConfigForm, PayrollGenerateForm, PayrollPaymentForm, DriverBulkSalaryForm
from permissions_config import can_see_page
from finance_utils import generate_entry_number
from utils import pk_now, pk_date
from datetime import datetime, date
from decimal import Decimal
import calendar


def check_auth(permission_code=None):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if permission_code:
        perms = session.get('permissions', [])
        if not session.get('is_master') and not can_see_page(perms, permission_code):
            flash('You do not have permission to access this page.', 'danger')
            return redirect(url_for('dashboard'))
    return None


def _parse_person_id(person_id_str):
    """Parse 'emp_123' or 'drv_456' into (type, id). Returns ('employee', id) or ('driver', id)."""
    if not person_id_str or person_id_str == '0' or person_id_str == '':
        return None, 0
    s = str(person_id_str)
    if s.startswith('emp_'):
        return 'employee', int(s[4:])
    elif s.startswith('drv_'):
        return 'driver', int(s[4:])
    return None, 0


def _build_person_choices(exclude_employee_ids=None, exclude_driver_ids=None, include_emp_id=None, include_drv_id=None):
    """Build combined choices list for Employee + Driver dropdown."""
    exclude_employee_ids = exclude_employee_ids or set()
    exclude_driver_ids = exclude_driver_ids or set()
    choices = [('', '-- Select Employee / Driver --')]

    employees = Employee.query.filter_by(status='Active').order_by(Employee.name).all()
    emp_list = []
    for e in employees:
        if e.id in exclude_employee_ids and not (include_emp_id and e.id == include_emp_id):
            continue
        emp_list.append((f'emp_{e.id}', f"[EMP] {e.code} – {e.name}"))
    if emp_list:
        choices.append(('__emp_header__', '── Employees ──'))
        choices.extend(emp_list)

    drivers = Driver.query.filter_by(status='Active').order_by(Driver.name).all()
    drv_list = []
    for d in drivers:
        if d.id in exclude_driver_ids and not (include_drv_id and d.id == include_drv_id):
            continue
        drv_list.append((f'drv_{d.id}', f"[DRV] {d.driver_id} – {d.name}"))
    if drv_list:
        choices.append(('__drv_header__', '── Drivers ──'))
        choices.extend(drv_list)

    return choices


def _get_driver_for_attendance(employee_id=None, driver_id=None):
    """Get the Driver record for attendance lookup."""
    if driver_id:
        return Driver.query.get(driver_id)
    if employee_id:
        emp = Employee.query.get(employee_id)
        if emp and emp.cnic_no:
            cnic = emp.cnic_no.strip()
            from sqlalchemy import func
            return Driver.query.filter(
                func.replace(Driver.cnic_no, '-', '') == cnic.replace('-', '')
            ).first()
    return None


def _fetch_attendance_stats(employee_id=None, driver_id=None, month=None, year=None):
    """Fetch attendance stats from driver_attendance."""
    driver = _get_driver_for_attendance(employee_id, driver_id)
    total_days = calendar.monthrange(year, month)[1]

    if not driver:
        return {
            'total_days': total_days,
            'present_days': 0, 'absent_days': 0, 'leave_days': 0,
            'late_days': 0, 'half_days': 0, 'off_days': 0,
            'extra_working_days': 0, 'driver_found': False,
        }

    first_day = date(year, month, 1)
    last_day = date(year, month, total_days)

    records = DriverAttendance.query.filter(
        DriverAttendance.driver_id == driver.id,
        DriverAttendance.attendance_date >= first_day,
        DriverAttendance.attendance_date <= last_day,
    ).all()

    stats = {
        'total_days': total_days,
        'present_days': 0, 'absent_days': 0, 'leave_days': 0,
        'late_days': 0, 'half_days': 0, 'off_days': 0,
        'extra_working_days': 0, 'driver_found': True,
    }
    for r in records:
        s = (r.status or '').strip()
        if s == 'Present':
            stats['present_days'] += 1
        elif s == 'Absent':
            stats['absent_days'] += 1
        elif s == 'Leave':
            stats['leave_days'] += 1
        elif s == 'Late':
            stats['late_days'] += 1
            stats['present_days'] += 1
        elif s == 'Half-Day':
            stats['half_days'] += 1
        elif s == 'Off':
            stats['off_days'] += 1

    working_days = total_days - stats['off_days']
    if stats['present_days'] > working_days and working_days > 0:
        stats['extra_working_days'] = stats['present_days'] - working_days

    return stats


# ════════════════════════════════════════════════════════════════════════════════
# SALARY CONFIGURATION
# ════════════════════════════════════════════════════════════════════════════════

def payroll_salary_config_list():
    auth_check = check_auth('payroll_config_list')
    if auth_check:
        return auth_check

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)
    search = request.args.get('search', '').strip()

    query = EmployeeSalaryConfig.query.outerjoin(
        Employee, EmployeeSalaryConfig.employee_id == Employee.id
    ).outerjoin(
        Driver, EmployeeSalaryConfig.driver_id == Driver.id
    )
    if search:
        terms = search.split()
        for term in terms:
            query = query.filter(
                db.or_(
                    Employee.name.ilike(f'%{term}%'),
                    Employee.code.ilike(f'%{term}%'),
                    Driver.name.ilike(f'%{term}%'),
                    Driver.driver_id.ilike(f'%{term}%'),
                    Driver.cnic_no.ilike(f'%{term}%'),
                )
            )
    query = query.order_by(
        db.case((Employee.name != None, Employee.name), else_=Driver.name)
    )
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    configs = pagination.items

    return render_template('payroll/salary_config_list.html',
                           configs=configs, pagination=pagination,
                           page=page, per_page=per_page, search=search)


def payroll_salary_config_form(pk=None):
    auth_check = check_auth('payroll_config_add' if not pk else 'payroll_config_edit')
    if auth_check:
        return auth_check

    config = EmployeeSalaryConfig.query.get_or_404(pk) if pk else None
    form = SalaryConfigForm(obj=config)

    already_emp = set()
    if not pk:
        for c in EmployeeSalaryConfig.query.filter(EmployeeSalaryConfig.employee_id != None).with_entities(EmployeeSalaryConfig.employee_id).all():
            already_emp.add(c.employee_id)

    employees = Employee.query.filter_by(status='Active').order_by(Employee.name).all()
    choices = [('', '-- Select Employee --')]
    for e in employees:
        if e.id in already_emp and not (config and config.employee_id == e.id):
            continue
        choices.append((f'emp_{e.id}', f"{e.code} – {e.name}"))
    form.person_id.choices = choices

    if config:
        if config.employee_id:
            form.person_id.data = f'emp_{config.employee_id}'
        elif config.driver_id:
            form.person_id.data = f'drv_{config.driver_id}'

    if request.method == 'POST' and form.validate_on_submit():
        ptype, pid = _parse_person_id(form.person_id.data)
        if not ptype or not pid:
            flash('Please select a valid Employee.', 'danger')
            return render_template('payroll/salary_config_form.html', form=form, title='New Employee Salary Configuration', config=config)

        if config:
            config.basic_salary = form.basic_salary.data
            config.extra_day_rate = form.extra_day_rate.data
            config.absent_penalty_rate = form.absent_penalty_rate.data
            config.payment_mode = form.payment_mode.data
            config.is_active = form.is_active.data
            config.remarks = form.remarks.data
        else:
            if ptype == 'employee':
                existing = EmployeeSalaryConfig.query.filter_by(employee_id=pid).first()
            else:
                existing = EmployeeSalaryConfig.query.filter_by(driver_id=pid).first()
            if existing:
                flash('Salary configuration already exists. Please edit the existing one.', 'warning')
                return redirect(url_for('payroll_salary_config_list'))
            config = EmployeeSalaryConfig(
                employee_id=pid if ptype == 'employee' else None,
                driver_id=pid if ptype == 'driver' else None,
                basic_salary=form.basic_salary.data,
                extra_day_rate=form.extra_day_rate.data,
                absent_penalty_rate=form.absent_penalty_rate.data,
                payment_mode=form.payment_mode.data,
                is_active=form.is_active.data,
                remarks=form.remarks.data,
            )
            db.session.add(config)
        db.session.commit()
        flash('Salary configuration saved successfully.', 'success')
        return redirect(url_for('payroll_salary_config_list'))

    title = 'Edit Salary Configuration' if pk else 'New Employee Salary Configuration'
    return render_template('payroll/salary_config_form.html', form=form, title=title, config=config)


def payroll_salary_config_delete(pk):
    auth_check = check_auth('payroll_config_delete')
    if auth_check:
        return auth_check
    config = EmployeeSalaryConfig.query.get_or_404(pk)
    q = MonthlyPayroll.query
    if config.employee_id:
        q = q.filter_by(employee_id=config.employee_id)
    elif config.driver_id:
        q = q.filter_by(driver_id=config.driver_id)
    if q.count() > 0:
        flash('Cannot delete: payroll records exist.', 'danger')
        return redirect(url_for('payroll_salary_config_list'))
    db.session.delete(config)
    db.session.commit()
    flash('Salary configuration deleted.', 'success')
    return redirect(url_for('payroll_salary_config_list'))


# ════════════════════════════════════════════════════════════════════════════════
# PAYROLL GENERATION & LIST
# ════════════════════════════════════════════════════════════════════════════════

def payroll_list():
    auth_check = check_auth('payroll_list')
    if auth_check:
        return auth_check

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)
    search = request.args.get('search', '').strip()
    status_filter = request.args.get('status', '').strip()
    month_filter = request.args.get('month', 0, type=int)
    year_filter = request.args.get('year', 0, type=int)

    query = MonthlyPayroll.query.outerjoin(
        Employee, MonthlyPayroll.employee_id == Employee.id
    ).outerjoin(
        Driver, MonthlyPayroll.driver_id == Driver.id
    )
    if search:
        terms = search.split()
        for term in terms:
            query = query.filter(
                db.or_(
                    Employee.name.ilike(f'%{term}%'),
                    Employee.code.ilike(f'%{term}%'),
                    Driver.name.ilike(f'%{term}%'),
                    Driver.driver_id.ilike(f'%{term}%'),
                )
            )
    if status_filter:
        query = query.filter(MonthlyPayroll.status == status_filter)
    if month_filter:
        query = query.filter(MonthlyPayroll.month == month_filter)
    if year_filter:
        query = query.filter(MonthlyPayroll.year == year_filter)

    query = query.order_by(MonthlyPayroll.year.desc(), MonthlyPayroll.month.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    payrolls = pagination.items

    years = db.session.query(db.distinct(MonthlyPayroll.year)).order_by(MonthlyPayroll.year.desc()).all()
    year_list = [y[0] for y in years] if years else [pk_date().year]

    return render_template('payroll/payroll_list.html',
                           payrolls=payrolls, pagination=pagination,
                           page=page, per_page=per_page, search=search,
                           status_filter=status_filter, month_filter=month_filter,
                           year_filter=year_filter, year_list=year_list)


def payroll_generate():
    auth_check = check_auth('payroll_generate')
    if auth_check:
        return auth_check

    form = PayrollGenerateForm()

    configs = EmployeeSalaryConfig.query.filter_by(is_active=True).all()
    choices = [('', '-- Select Employee / Driver --')]
    emp_list = []
    drv_list = []
    for c in configs:
        if c.employee_id and c.employee:
            if c.employee.status == 'Active':
                emp_list.append((f'emp_{c.employee_id}', f"[EMP] {c.employee.code} – {c.employee.name}"))
        elif c.driver_id and c.driver:
            if c.driver.status == 'Active':
                drv_list.append((f'drv_{c.driver_id}', f"[DRV] {c.driver.driver_id} – {c.driver.name}"))
    if emp_list:
        choices.append(('__emp_header__', '── Employees ──'))
        choices.extend(sorted(emp_list, key=lambda x: x[1]))
    if drv_list:
        choices.append(('__drv_header__', '── Drivers ──'))
        choices.extend(sorted(drv_list, key=lambda x: x[1]))

    form.person_id.choices = choices

    current_year = pk_date().year
    form.year.choices = [(y, str(y)) for y in range(current_year - 2, current_year + 2)]
    form.month.default = pk_date().month
    form.year.default = current_year

    if request.method == 'POST' and form.validate_on_submit():
        ptype, pid = _parse_person_id(form.person_id.data)
        m = form.month.data
        y = form.year.data

        if not ptype or not pid:
            flash('Please select a valid Employee or Driver.', 'danger')
            return redirect(url_for('payroll_generate'))

        emp_id = pid if ptype == 'employee' else None
        drv_id = pid if ptype == 'driver' else None

        existing = MonthlyPayroll.query.filter_by(employee_id=emp_id, driver_id=drv_id, month=m, year=y).first()
        if existing:
            flash(f'Payroll already exists for {calendar.month_name[m]} {y}. Use the edit option.', 'warning')
            return redirect(url_for('payroll_view', pk=existing.id))

        if ptype == 'employee':
            config = EmployeeSalaryConfig.query.filter_by(employee_id=pid).first()
        else:
            config = EmployeeSalaryConfig.query.filter_by(driver_id=pid).first()
        if not config:
            flash('No salary configuration found.', 'danger')
            return redirect(url_for('payroll_generate'))

        stats = _fetch_attendance_stats(employee_id=emp_id, driver_id=drv_id, month=m, year=y)
        name = config.person_name

        payroll = MonthlyPayroll(
            employee_id=emp_id,
            driver_id=drv_id,
            month=m, year=y,
            total_days=stats['total_days'],
            present_days=stats['present_days'],
            absent_days=stats['absent_days'],
            leave_days=stats['leave_days'],
            late_days=stats['late_days'],
            half_days=stats['half_days'],
            off_days=stats['off_days'],
            extra_working_days=stats['extra_working_days'],
            basic_salary=config.basic_salary,
            bonus=form.bonus.data or 0,
            manual_fine=form.manual_fine.data or 0,
            mpg_fine=form.mpg_fine.data or 0,
            loan_deduction=form.loan_deduction.data or 0,
            other_deduction=form.other_deduction.data or 0,
            remarks=form.remarks.data,
            status='Draft',
        )
        payroll.calculate()
        db.session.add(payroll)
        db.session.commit()
        flash(f'Payroll generated for {name} – {calendar.month_name[m]} {y}.', 'success')
        return redirect(url_for('payroll_view', pk=payroll.id))

    return render_template('payroll/payroll_generate.html', form=form)


def payroll_view(pk):
    auth_check = check_auth('payroll_list')
    if auth_check:
        return auth_check
    payroll = MonthlyPayroll.query.get_or_404(pk)
    return render_template('payroll/payroll_view.html', payroll=payroll)


def payroll_edit(pk):
    auth_check = check_auth('payroll_edit')
    if auth_check:
        return auth_check

    payroll = MonthlyPayroll.query.get_or_404(pk)
    if payroll.status != 'Draft':
        flash('Only Draft payrolls can be edited.', 'warning')
        return redirect(url_for('payroll_view', pk=pk))

    form = PayrollGenerateForm(obj=payroll)
    if payroll.employee_id:
        form.person_id.choices = [(f'emp_{payroll.employee_id}', f"[EMP] {payroll.person_code} – {payroll.person_name}")]
        form.person_id.data = f'emp_{payroll.employee_id}'
    else:
        form.person_id.choices = [(f'drv_{payroll.driver_id}', f"[DRV] {payroll.person_code} – {payroll.person_name}")]
        form.person_id.data = f'drv_{payroll.driver_id}'

    current_year = pk_date().year
    form.year.choices = [(y, str(y)) for y in range(current_year - 2, current_year + 2)]

    if request.method == 'POST' and form.validate_on_submit():
        payroll.bonus = form.bonus.data or 0
        payroll.manual_fine = form.manual_fine.data or 0
        payroll.mpg_fine = form.mpg_fine.data or 0
        payroll.loan_deduction = form.loan_deduction.data or 0
        payroll.other_deduction = form.other_deduction.data or 0
        payroll.remarks = form.remarks.data
        payroll.calculate()
        db.session.commit()
        flash('Payroll updated successfully.', 'success')
        return redirect(url_for('payroll_view', pk=pk))

    return render_template('payroll/payroll_edit.html', form=form, payroll=payroll)


def payroll_recalc_attendance(pk):
    auth_check = check_auth('payroll_edit')
    if auth_check:
        return auth_check

    payroll = MonthlyPayroll.query.get_or_404(pk)
    if payroll.status != 'Draft':
        flash('Only Draft payrolls can be recalculated.', 'warning')
        return redirect(url_for('payroll_view', pk=pk))

    stats = _fetch_attendance_stats(
        employee_id=payroll.employee_id, driver_id=payroll.driver_id,
        month=payroll.month, year=payroll.year
    )
    payroll.total_days = stats['total_days']
    payroll.present_days = stats['present_days']
    payroll.absent_days = stats['absent_days']
    payroll.leave_days = stats['leave_days']
    payroll.late_days = stats['late_days']
    payroll.half_days = stats['half_days']
    payroll.off_days = stats['off_days']
    payroll.extra_working_days = stats['extra_working_days']
    payroll.calculate()
    db.session.commit()
    flash('Attendance data refreshed and payroll recalculated.', 'success')
    return redirect(url_for('payroll_view', pk=pk))


# ════════════════════════════════════════════════════════════════════════════════
# FINALIZE & PAY
# ════════════════════════════════════════════════════════════════════════════════

def payroll_finalize(pk):
    auth_check = check_auth('payroll_finalize')
    if auth_check:
        return auth_check

    payroll = MonthlyPayroll.query.get_or_404(pk)
    if payroll.status != 'Draft':
        flash('Only Draft payrolls can be finalized.', 'warning')
        return redirect(url_for('payroll_view', pk=pk))

    payroll.calculate()
    payroll.status = 'Finalized'
    payroll.finalized_at = pk_now()
    payroll.finalized_by_user_id = session.get('user_id')
    db.session.commit()
    flash(f'Payroll finalized for {payroll.person_name}. Net payable: Rs. {payroll.net_payable:,.2f}', 'success')
    return redirect(url_for('payroll_view', pk=pk))


def payroll_pay(pk):
    auth_check = check_auth('payroll_pay')
    if auth_check:
        return auth_check

    payroll = MonthlyPayroll.query.get_or_404(pk)
    if payroll.status != 'Finalized':
        flash('Only Finalized payrolls can be marked as Paid.', 'warning')
        return redirect(url_for('payroll_view', pk=pk))

    form = PayrollPaymentForm()
    accounts = Account.query.filter(
        Account.is_active == True,
        Account.account_type.in_(['Asset'])
    ).order_by(Account.code).all()
    form.payment_account_id.choices = [(0, '-- Select Source Account --')] + [
        (a.id, f"{a.code} – {a.name}") for a in accounts
    ]

    if request.method == 'POST' and form.validate_on_submit():
        payroll.status = 'Paid'
        payroll.payment_date = form.payment_date.data
        payroll.payment_method = form.payment_method.data
        payroll.payment_account_id = form.payment_account_id.data
        payroll.paid_at = pk_now()
        payroll.paid_by_user_id = session.get('user_id')
        if form.remarks.data:
            payroll.remarks = (payroll.remarks or '') + '\nPayment: ' + form.remarks.data

        salary_account = Account.query.filter_by(code='5300').first()
        source_account = Account.query.get(form.payment_account_id.data)

        if salary_account and source_account:
            entry_number = generate_entry_number('JE', form.payment_date.data)
            desc = f"Salary payment – {payroll.person_name} ({payroll.person_code}) – {calendar.month_name[payroll.month]} {payroll.year}"

            je = JournalEntry(
                entry_number=entry_number,
                entry_date=form.payment_date.data,
                entry_type='Expense',
                description=desc,
                reference_type='MonthlyPayroll',
                reference_id=payroll.id,
                created_by_user_id=session.get('user_id'),
                is_posted=True,
                posted_at=pk_now(),
            )
            db.session.add(je)
            db.session.flush()

            debit_line = JournalEntryLine(
                journal_entry_id=je.id, account_id=salary_account.id,
                debit=payroll.net_payable, credit=0,
                description=f"Salary expense – {payroll.person_name}", sort_order=1,
            )
            credit_line = JournalEntryLine(
                journal_entry_id=je.id, account_id=source_account.id,
                debit=0, credit=payroll.net_payable,
                description=f"Payment from {source_account.name}", sort_order=2,
            )
            db.session.add_all([debit_line, credit_line])

            salary_account.current_balance += payroll.net_payable
            source_account.current_balance -= payroll.net_payable
            payroll.journal_entry_id = je.id

        db.session.commit()
        flash(f'Payment recorded for {payroll.person_name}. Journal entry created.', 'success')
        return redirect(url_for('payroll_view', pk=pk))

    return render_template('payroll/payroll_pay.html', form=form, payroll=payroll)


def payroll_revert(pk):
    auth_check = check_auth('payroll_finalize')
    if auth_check:
        return auth_check
    payroll = MonthlyPayroll.query.get_or_404(pk)
    if payroll.status != 'Finalized':
        flash('Only Finalized payrolls can be reverted to Draft.', 'warning')
        return redirect(url_for('payroll_view', pk=pk))
    payroll.status = 'Draft'
    payroll.finalized_at = None
    payroll.finalized_by_user_id = None
    db.session.commit()
    flash('Payroll reverted to Draft.', 'info')
    return redirect(url_for('payroll_view', pk=pk))


def payroll_delete(pk):
    auth_check = check_auth('payroll_delete')
    if auth_check:
        return auth_check
    payroll = MonthlyPayroll.query.get_or_404(pk)
    if payroll.status == 'Paid':
        flash('Cannot delete a paid payroll. Reverse the payment first.', 'danger')
        return redirect(url_for('payroll_view', pk=pk))
    db.session.delete(payroll)
    db.session.commit()
    flash('Payroll record deleted.', 'success')
    return redirect(url_for('payroll_list'))


# ════════════════════════════════════════════════════════════════════════════════
# PENDING SALARIES DASHBOARD
# ════════════════════════════════════════════════════════════════════════════════

def payroll_pending():
    auth_check = check_auth('payroll_pending')
    if auth_check:
        return auth_check

    pending = MonthlyPayroll.query.filter_by(status='Finalized').order_by(
        MonthlyPayroll.year.asc(), MonthlyPayroll.month.asc()
    ).all()

    total_pending = sum(float(p.net_payable) for p in pending)
    by_month = {}
    for p in pending:
        key = f"{calendar.month_name[p.month]} {p.year}"
        if key not in by_month:
            by_month[key] = {'records': [], 'total': 0}
        by_month[key]['records'].append(p)
        by_month[key]['total'] += float(p.net_payable)

    return render_template('payroll/payroll_pending.html',
                           pending=pending, total_pending=total_pending, by_month=by_month)


# ════════════════════════════════════════════════════════════════════════════════
# BULK GENERATE
# ════════════════════════════════════════════════════════════════════════════════

def payroll_bulk_generate():
    auth_check = check_auth('payroll_generate')
    if auth_check:
        return auth_check

    if request.method == 'POST':
        month = request.form.get('month', type=int)
        year = request.form.get('year', type=int)
        if not month or not year:
            flash('Please select month and year.', 'danger')
            return redirect(url_for('payroll_bulk_generate'))

        configs = EmployeeSalaryConfig.query.filter_by(is_active=True).all()
        created = 0
        skipped = 0
        for config in configs:
            emp_id = config.employee_id
            drv_id = config.driver_id

            existing = MonthlyPayroll.query.filter_by(
                employee_id=emp_id, driver_id=drv_id, month=month, year=year
            ).first()
            if existing:
                skipped += 1
                continue

            if emp_id:
                person = Employee.query.get(emp_id)
                if not person or person.status != 'Active':
                    skipped += 1
                    continue
            elif drv_id:
                person = Driver.query.get(drv_id)
                if not person or person.status != 'Active':
                    skipped += 1
                    continue
            else:
                skipped += 1
                continue

            stats = _fetch_attendance_stats(employee_id=emp_id, driver_id=drv_id, month=month, year=year)
            payroll = MonthlyPayroll(
                employee_id=emp_id, driver_id=drv_id,
                month=month, year=year,
                total_days=stats['total_days'],
                present_days=stats['present_days'],
                absent_days=stats['absent_days'],
                leave_days=stats['leave_days'],
                late_days=stats['late_days'],
                half_days=stats['half_days'],
                off_days=stats['off_days'],
                extra_working_days=stats['extra_working_days'],
                basic_salary=config.basic_salary,
                status='Draft',
            )
            payroll.calculate()
            db.session.add(payroll)
            created += 1

        db.session.commit()
        flash(f'Bulk generation complete: {created} created, {skipped} skipped.', 'success')
        return redirect(url_for('payroll_list', month=month, year=year))

    current_year = pk_date().year
    years = list(range(current_year - 2, current_year + 2))
    return render_template('payroll/payroll_bulk_generate.html', years=years,
                           now_month=pk_date().month, now_year=current_year)


# ════════════════════════════════════════════════════════════════════════════════
# API ENDPOINTS (AJAX)
# ════════════════════════════════════════════════════════════════════════════════

def api_payroll_attendance_preview():
    person_id_str = request.args.get('person_id', '')
    month = request.args.get('month', 0, type=int)
    year = request.args.get('year', 0, type=int)

    ptype, pid = _parse_person_id(person_id_str)
    if not ptype or not pid or not month or not year:
        return jsonify({'error': 'Missing parameters'}), 400

    emp_id = pid if ptype == 'employee' else None
    drv_id = pid if ptype == 'driver' else None

    if ptype == 'employee':
        config = EmployeeSalaryConfig.query.filter_by(employee_id=pid).first()
    else:
        config = EmployeeSalaryConfig.query.filter_by(driver_id=pid).first()

    stats = _fetch_attendance_stats(employee_id=emp_id, driver_id=drv_id, month=month, year=year)

    basic_salary = float(config.basic_salary) if config else 0
    extra_rate = float(config.extra_day_rate) if config else 0
    absent_rate = float(config.absent_penalty_rate) if config else 0

    extra_pay = stats['extra_working_days'] * extra_rate
    absent_fine = stats['absent_days'] * absent_rate
    gross = basic_salary + extra_pay
    net = gross - absent_fine

    return jsonify({
        'stats': stats,
        'config': {'basic_salary': basic_salary, 'extra_day_rate': extra_rate, 'absent_penalty_rate': absent_rate},
        'preview': {'calculated_basic': basic_salary, 'extra_working_pay': extra_pay,
                    'absent_fine': absent_fine, 'gross_pay': gross, 'net_estimate': net},
    })


def payroll_driver_bulk_salary():
    """Assign salary config to multiple drivers by Project / District / Individual."""
    auth_check = check_auth('payroll_config_add')
    if auth_check:
        return auth_check

    form = DriverBulkSalaryForm()
    projects = Project.query.filter_by(status='Active').order_by(Project.name).all()
    districts = District.query.order_by(District.name).all()
    drivers = Driver.query.filter_by(status='Active').order_by(Driver.name).all()

    form.project_id.choices = [(0, '-- Select Project --')] + [(p.id, p.name) for p in projects]
    form.district_id.choices = [(0, '-- Select District --')] + [(d.id, d.name) for d in districts]
    form.driver_id.choices = [(0, '-- Select Driver --')] + [(d.id, f"{d.driver_id} – {d.name}") for d in drivers]

    result = None

    if request.method == 'POST' and form.validate_on_submit():
        mode = form.assignment_mode.data
        overwrite = form.overwrite_existing.data
        target_drivers = []

        if mode == 'project':
            pid = form.project_id.data
            if not pid:
                flash('Please select a Project.', 'danger')
                return render_template('payroll/driver_bulk_salary.html', form=form, result=None)
            target_drivers = Driver.query.filter_by(project_id=pid, status='Active').all()
        elif mode == 'district':
            did = form.district_id.data
            if not did:
                flash('Please select a District.', 'danger')
                return render_template('payroll/driver_bulk_salary.html', form=form, result=None)
            target_drivers = Driver.query.filter_by(district_id=did, status='Active').all()
        elif mode == 'both':
            pid = form.project_id.data
            did = form.district_id.data
            if not pid or not did:
                flash('Please select both Project and District.', 'danger')
                return render_template('payroll/driver_bulk_salary.html', form=form, result=None)
            target_drivers = Driver.query.filter_by(project_id=pid, district_id=did, status='Active').all()
        elif mode == 'individual':
            did = form.driver_id.data
            if not did:
                flash('Please select a Driver.', 'danger')
                return render_template('payroll/driver_bulk_salary.html', form=form, result=None)
            d = Driver.query.get(did)
            if d:
                target_drivers = [d]

        if not target_drivers:
            flash('No active drivers found for this selection.', 'warning')
            return render_template('payroll/driver_bulk_salary.html', form=form, result=None)

        created = 0
        updated = 0
        skipped = 0
        for drv in target_drivers:
            existing = EmployeeSalaryConfig.query.filter_by(driver_id=drv.id).first()
            if existing:
                if overwrite:
                    existing.basic_salary = form.basic_salary.data
                    existing.extra_day_rate = form.extra_day_rate.data
                    existing.absent_penalty_rate = form.absent_penalty_rate.data
                    existing.payment_mode = form.payment_mode.data
                    existing.is_active = True
                    existing.remarks = form.remarks.data or existing.remarks
                    updated += 1
                else:
                    skipped += 1
            else:
                config = EmployeeSalaryConfig(
                    driver_id=drv.id,
                    basic_salary=form.basic_salary.data,
                    extra_day_rate=form.extra_day_rate.data,
                    absent_penalty_rate=form.absent_penalty_rate.data,
                    payment_mode=form.payment_mode.data,
                    is_active=True,
                    remarks=form.remarks.data,
                )
                db.session.add(config)
                created += 1

        db.session.commit()
        result = {'total': len(target_drivers), 'created': created, 'updated': updated, 'skipped': skipped}
        flash(f'Done! {created} created, {updated} updated, {skipped} skipped (already configured).', 'success')

    return render_template('payroll/driver_bulk_salary.html', form=form, result=result)


def api_driver_bulk_preview():
    """AJAX: Preview drivers that match a Project/District filter."""
    mode = request.args.get('mode', '')
    project_id = request.args.get('project_id', 0, type=int)
    district_id = request.args.get('district_id', 0, type=int)
    driver_id = request.args.get('driver_id', 0, type=int)

    query = Driver.query.filter_by(status='Active')
    if mode == 'project' and project_id:
        query = query.filter_by(project_id=project_id)
    elif mode == 'district' and district_id:
        query = query.filter_by(district_id=district_id)
    elif mode == 'both' and project_id and district_id:
        query = query.filter_by(project_id=project_id, district_id=district_id)
    elif mode == 'individual' and driver_id:
        query = query.filter_by(id=driver_id)
    else:
        return jsonify({'drivers': [], 'total': 0, 'already_configured': 0})

    drivers_list = query.order_by(Driver.name).all()
    already_configured_ids = {c.driver_id for c in
        EmployeeSalaryConfig.query.filter(EmployeeSalaryConfig.driver_id.in_([d.id for d in drivers_list])).all()
    } if drivers_list else set()

    result = []
    for d in drivers_list:
        result.append({
            'id': d.id,
            'driver_id': d.driver_id,
            'name': d.name,
            'has_config': d.id in already_configured_ids,
        })

    return jsonify({
        'drivers': result,
        'total': len(result),
        'already_configured': len(already_configured_ids),
    })


def payroll_payslip(pk):
    auth_check = check_auth('payroll_list')
    if auth_check:
        return auth_check
    payroll = MonthlyPayroll.query.get_or_404(pk)
    generated_at = pk_now().strftime('%d %b %Y, %I:%M %p')
    return render_template('payroll/payslip.html', payroll=payroll, generated_at=generated_at)
