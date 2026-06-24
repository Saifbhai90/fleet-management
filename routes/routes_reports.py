"""
Reports routes - Report Centre, activity logs, AI report, summary reports,
driver profile, vehicle profile, expiry report, parking utilization.

Extracted from routes.py to reduce file size.
Imports shared helpers from routes.py for backward compatibility.
"""
import re
from datetime import datetime, date, timedelta

from flask import (
    render_template, redirect, url_for, flash, request,
    session, abort, jsonify, make_response,
)
from sqlalchemy import func, or_, and_

from app import app, db
from models import (
    Company, Project, Vehicle, Driver, ParkingStation, District,
    User, LoginLog, ActivityLog, ClientActivityLog, ClientDiagnosticLog,
    DriverTransfer, DriverStatusChange, VehicleTransfer,
    PhysicalBook, BookAssignment,
    FuelExpense, MaintenanceExpense, PenaltyRecord, DriverAttendance,
    Party, Product,
    project_district,
)
from vehicle_sort_utils import vehicle_order_by
from utils import (
    parse_date, pk_now, pk_date,
    make_driver_profile_share_token, load_driver_profile_share_token,
)

# Import shared helpers from routes.py
from routes import (
    _multi_word_filter,
    _build_driver_update_whatsapp_parts,
    _oil_change_alert_rows,
)

# ────────────────────────────────────────────────
def _linked_driver_id_for_current_user():
    """If logged-in user matches a driver by CNIC (username), return driver.id for 'my profile' links."""
    try:
        uid = session.get('user_id')
        if not uid:
            return None
        user = db.session.get(User, uid)
        if not user:
            return None
        uname = (user.username or '').strip()
        if not uname:
            return None
        cnic_variants = [uname]
        digits = re.sub(r'\D', '', uname)
        if len(digits) == 13:
            cnic_variants.append(digits[:5] + '-' + digits[5:12] + '-' + digits[12:])
        for c in cnic_variants:
            drv = Driver.query.filter(func.lower(Driver.cnic_no) == c.lower()).first()
            if drv:
                return drv.id
    except Exception:
        return None
    return None


def _report_centre_badge_counts(can_page, is_master):
    """Actionable counts for Report Centre mobile tiles (permission-gated, best-effort)."""
    badges = {}

    def _set(key, val):
        n = int(val or 0)
        if n > 0:
            badges[key] = n if n < 100 else 99

    try:
        if can_page('missing_documents_report'):
            miss_q = Driver.query.filter(Driver.status != 'Left').filter(
                db.or_(
                    Driver.photo_path.is_(None), Driver.photo_path == '',
                    Driver.cnic_front_path.is_(None), Driver.cnic_front_path == '',
                    Driver.cnic_back_path.is_(None), Driver.cnic_back_path == '',
                    Driver.license_front_path.is_(None), Driver.license_front_path == '',
                    Driver.license_back_path.is_(None), Driver.license_back_path == '',
                    Driver.verify_license_photo_path.is_(None), Driver.verify_license_photo_path == '',
                    Driver.document_path.is_(None), Driver.document_path == '',
                )
            )
            _set('missing-docs', miss_q.count())
    except Exception:
        pass

    try:
        if can_page('book_pending_returns'):
            from models import BookAssignment
            _set('book-return', BookAssignment.query.filter_by(status='Active').count())
    except Exception:
        pass

    try:
        if can_page('oil_change_alert_report'):
            from auth_utils import get_user_context
            uid = session.get('user_id')
            ctx = get_user_context(uid) if uid else {}
            rows = _oil_change_alert_rows(
                statuses=['near', 'crossed'],
                allowed_projects=ctx.get('allowed_projects'),
                allowed_districts=ctx.get('allowed_districts'),
                allowed_vehicles=ctx.get('allowed_vehicles'),
                is_master_or_admin=ctx.get('is_master_or_admin', is_master),
            )
            _set('oil-alert', len(rows))
    except Exception:
        pass

    try:
        if can_page('red_task_list'):
            from models import RedTask
            today = pk_date()
            _set('red-task', RedTask.query.filter(RedTask.task_date == today).count())
    except Exception:
        pass

    try:
        if can_page('report_expiry'):
            from datetime import timedelta
            from auth_utils import get_user_context
            uid = session.get('user_id')
            ctx = get_user_context(uid) if uid else {}
            today = pk_date()
            horizon = today + timedelta(days=30)
            exp_q = Driver.query.filter(
                Driver.status != 'Left',
                Driver.vehicle_id.isnot(None),
            )
            if not ctx.get('is_master_or_admin', is_master):
                av = ctx.get('allowed_vehicles') or set()
                if av:
                    exp_q = exp_q.filter(Driver.vehicle_id.in_(list(av)))
            exp_q = exp_q.filter(
                db.or_(
                    db.and_(Driver.license_expiry_date.isnot(None), Driver.license_expiry_date <= horizon),
                    db.and_(Driver.cnic_expiry_date.isnot(None), Driver.cnic_expiry_date <= horizon),
                )
            )
            _set('expiry', exp_q.count())
    except Exception:
        pass

    return badges


def _report_centre_visibility(linked_driver_id=None):
    """Which Report Centre tabs/columns have at least one permitted link (same rules as can_see_page in template)."""
    from permissions_config import can_see_page as _can_pg

    perms = session.get('permissions') or []
    is_master = session.get('is_master', False)
    linked_id = linked_driver_id if linked_driver_id is not None else _linked_driver_id_for_current_user()

    def c(page_key):
        if is_master:
            return True
        return _can_pg(perms, page_key)

    fleet_vehicle = (
        c('report_vehicle_summary') or c('vehicles_list') or c('report_vehicle_profile')
        or c('report_parking_utilization')
    )
    fleet_project = c('report_project_summary') or c('report_district_summary') or c('report_company_profile')
    fleet_expense = (
        c('fuel_expense_list') or c('oil_expense_list') or c('maintenance_expense_list')
        or c('oil_change_alert_report')
    )
    show_fleet = bool(fleet_vehicle or fleet_project or fleet_expense)

    task_daily = (
        c('task_report_list') or c('task_report_new') or c('task_report_entry') or c('red_task_list') or c('red_task_summary') or c('red_task_summary_detail') or c('without_task_list')
        or c('speed_monitoring_report') or c('mileage_report') or c('tracker_difference_report')
        or c('unauthorized_movement_report') or c('task_start_delay_report') or c('task_turnaround_report')
        or c('unexecuted_task_report')
    )
    task_logbook = c('task_report_logbook_cover')
    task_upload = c('task_report_upload')
    show_task = bool(task_daily or task_logbook or task_upload)

    hr_driver = (
        (bool(linked_id) and c('report_driver_profile'))
        or c('active_drivers_report') or c('driver_seat_available_report') or c('missing_documents_report')
        or c('penalty_record_list') or c('driver_salary_slip')
    )
    hr_att = c('driver_attendance_report') or c('driver_attendance_tra_report') or c('report_expiry')
    hr_workforce = c('driver_job_left_list') or c('driver_rejoin_list')
    show_hr = bool(hr_driver or hr_att or hr_workforce)

    finance_books = (
        c('payment_vouchers_list') or c('receipt_vouchers_list') or c('bank_entries_list')
        or c('journal_vouchers_list')
    )
    finance_ledger = c('accounts_account_ledger') or c('wallet_dashboard') or c('fund_transfers_list')
    finance_final = c('accounts_balance_sheet') or c('chart_of_accounts_list')
    show_finance = bool(finance_books or finance_ledger or finance_final)

    admin_activity = c('activity_log_report')
    admin_ai = c('report_ai')
    admin_books = c('book_inventory_list') or c('book_assignment_list') or c('book_pending_returns')
    show_admin = bool(admin_activity or admin_ai or admin_books)

    order = [
        ('fleet', show_fleet),
        ('task', show_task),
        ('hr', show_hr),
        ('finance', show_finance),
        ('admin', show_admin),
    ]
    first_tab = 'fleet'
    for tid, ok in order:
        if ok:
            first_tab = tid
            break

    any_tab = bool(show_fleet or show_task or show_hr or show_finance or show_admin)

    badges = _report_centre_badge_counts(c, is_master)

    return {
        'first_tab': first_tab,
        'any_tab': any_tab,
        'badges': badges,
        'show_fleet': show_fleet,
        'show_task': show_task,
        'show_hr': show_hr,
        'show_finance': show_finance,
        'show_admin': show_admin,
        'fleet_vehicle_col': fleet_vehicle,
        'fleet_project_col': fleet_project,
        'fleet_expense_col': fleet_expense,
        'task_daily_col': task_daily,
        'task_logbook_col': task_logbook,
        'task_upload_col': task_upload,
        'hr_driver_col': hr_driver,
        'hr_att_col': hr_att,
        'hr_workforce_col': hr_workforce,
        'finance_books_col': finance_books,
        'finance_ledger_col': finance_ledger,
        'finance_final_col': finance_final,
        'admin_activity_col': admin_activity,
        'admin_ai_col': admin_ai,
        'admin_books_col': admin_books,
    }


@app.route('/reports/')
def reports_index():
    _lid = _linked_driver_id_for_current_user()
    rc = _report_centre_visibility(_lid)
    return render_template('reports_index.html', linked_driver_id=_lid, rc=rc)


@app.route('/hub/<hub_slug>')
def module_hub(hub_slug):
    """Module hub launcher (Master Data, Assignments, etc.) — replaces sidebar dropdowns."""
    from flask import abort, session
    from hub_registry import HUBS, build_hub_sections, _hub_access

    if hub_slug not in HUBS:
        abort(404)
    hub_def = HUBS[hub_slug]
    try:
        from permissions_config import can_see_page, can_see_section, can_see_administration_menu
        perms = session.get('permissions') or []
        is_master = session.get('is_master', False)
        can_p = (lambda k: True) if is_master else (lambda k: can_see_page(perms, k))
        can_s = (lambda k: True) if is_master else (lambda k: can_see_section(perms, k))
        can_admin = (lambda: True) if is_master else (lambda: can_see_administration_menu(perms))
    except Exception:
        app.logger.exception('module_hub: permission helpers failed for %s', hub_slug)
        can_p = lambda k: True
        can_s = lambda k: True
        can_admin = lambda: True
        is_master = session.get('is_master', False)

    if not _hub_access(hub_def, can_s, can_p, can_admin, is_master):
        abort(403)

    try:
        hub, sections = build_hub_sections(hub_slug, can_p, is_master=is_master)
    except Exception:
        app.logger.exception('module_hub: build_hub_sections failed for %s', hub_slug)
        abort(500)

    if not hub:
        abort(404)

    hub_page = {
        'title': hub.get('title', 'Module'),
        'header_icon': hub.get('header_icon', 'bi-grid'),
    }
    return render_template(
        'module_hub.html',
        hub_page=hub_page,
        sections=sections or [],
        hub_slug=hub_slug,
    )


_ACTIVITY_LOG_MAX_DAYS = 10


def _activity_log_datetime_in_range(column, date_from, date_to):
    """Calendar-date filter safe for SQLite ISO strings (T) from sync_master."""
    return and_(func.date(column) >= date_from, func.date(column) <= date_to)


@app.route('/reports/activity-log')
def activity_log_report():
    """Single report: (1) Login sessions + server-side activity, (2) Client activity with device ID & geolocation (lat/long, View on Map)."""
    date_from_s = request.args.get('date_from', '').strip()
    date_to_s = request.args.get('date_to', '').strip()
    user_id_q = request.args.get('user_id', type=int)
    username_q = request.args.get('username', '').strip()
    device_id_q = request.args.get('device_id', '').strip()

    sessions = []
    activities_by_log = {}
    client_logs = []
    diagnostic_logs = []
    report_ready = False
    report_message = (
        'Pehle <strong>Date From</strong> aur <strong>Date To</strong> select karein '
        f'(zyada se zyada {_ACTIVITY_LOG_MAX_DAYS} din), phir <strong>Search</strong> dabayein. '
        'Report tabhi load hogi.'
    )
    report_message_level = 'info'

    date_from_dt = None
    date_to_dt = None
    if date_from_s or date_to_s:
        if not date_from_s or not date_to_s:
            report_message = (
                f'Dono dates zaroori hain — Date From aur Date To (maximum {_ACTIVITY_LOG_MAX_DAYS} din).'
            )
            report_message_level = 'warning'
        else:
            date_from_parsed = parse_date(date_from_s)
            date_to_parsed = parse_date(date_to_s)
            if not date_from_parsed or not date_to_parsed:
                report_message = 'Dates sahi format mein hon (dd-mm-yyyy).'
                report_message_level = 'warning'
            else:
                date_from_s = date_from_parsed.strftime('%d-%m-%Y')
                date_to_s = date_to_parsed.strftime('%d-%m-%Y')
                date_from_dt = date_from_parsed
                date_to_dt = date_to_parsed
                if date_to_dt < date_from_dt:
                    report_message = 'Date To, Date From se pehle nahi ho sakti.'
                    report_message_level = 'warning'
                else:
                    span_days = (date_to_dt - date_from_dt).days + 1
                    if span_days > _ACTIVITY_LOG_MAX_DAYS:
                        report_message = (
                            f'Sirf {_ACTIVITY_LOG_MAX_DAYS} din ya us se kam ki range select karein '
                            f'(aap ne {span_days} din select kiye).'
                        )
                        report_message_level = 'warning'
                    else:
                        report_ready = True
                        report_message = None

    if report_ready and date_from_dt and date_to_dt:
        # ─── 1. Login sessions (LoginLog + ActivityLog) ───
        query_sessions = (
            LoginLog.query.join(User)
            .filter(_activity_log_datetime_in_range(LoginLog.login_at, date_from_dt, date_to_dt))
            .order_by(LoginLog.login_at.desc())
        )
        if user_id_q:
            query_sessions = query_sessions.filter(LoginLog.user_id == user_id_q)
        if username_q:
            flt = _multi_word_filter(username_q, User.username, User.full_name)
            if flt is not None:
                query_sessions = query_sessions.filter(flt)
        sessions = query_sessions.limit(500).all()
        log_ids = [s.id for s in sessions]
        if log_ids:
            for a in (
                ActivityLog.query.filter(
                    ActivityLog.login_log_id.in_(log_ids),
                    _activity_log_datetime_in_range(ActivityLog.created_at, date_from_dt, date_to_dt),
                )
                .order_by(ActivityLog.created_at.asc())
                .all()
            ):
                activities_by_log.setdefault(a.login_log_id, []).append(a)

        # ─── 2. Client activity logs (device_id, lat/long, View on Map) ───
        query_client = (
            ClientActivityLog.query.join(User)
            .filter(_activity_log_datetime_in_range(ClientActivityLog.created_at, date_from_dt, date_to_dt))
            .order_by(ClientActivityLog.created_at.desc())
        )
        if user_id_q:
            query_client = query_client.filter(ClientActivityLog.user_id == user_id_q)
        if device_id_q:
            flt = _multi_word_filter(device_id_q, ClientActivityLog.device_id)
            if flt is not None:
                query_client = query_client.filter(flt)
        if username_q:
            flt = _multi_word_filter(username_q, User.username, User.full_name)
            if flt is not None:
                query_client = query_client.filter(flt)
        client_logs = query_client.limit(1000).all()

        query_diag = (
            ClientDiagnosticLog.query.join(User)
            .filter(_activity_log_datetime_in_range(ClientDiagnosticLog.created_at, date_from_dt, date_to_dt))
            .order_by(ClientDiagnosticLog.created_at.desc())
        )
        if user_id_q:
            query_diag = query_diag.filter(ClientDiagnosticLog.user_id == user_id_q)
        if device_id_q:
            flt = _multi_word_filter(device_id_q, ClientDiagnosticLog.device_id)
            if flt is not None:
                query_diag = query_diag.filter(flt)
        if username_q:
            flt = _multi_word_filter(username_q, User.username, User.full_name)
            if flt is not None:
                query_diag = query_diag.filter(flt)
        diagnostic_logs = query_diag.limit(500).all()

    users_for_filter = User.query.order_by(User.username).all()
    return render_template(
        'reports/activity_log.html',
        sessions=sessions,
        activities_by_log=activities_by_log,
        client_logs=client_logs,
        diagnostic_logs=diagnostic_logs,
        users_for_filter=users_for_filter,
        date_from=date_from_s,
        date_to=date_to_s,
        user_id_q=user_id_q,
        username_q=username_q,
        device_id_q=device_id_q,
        report_ready=report_ready,
        report_message=report_message,
        report_message_level=report_message_level,
        activity_log_max_days=_ACTIVITY_LOG_MAX_DAYS,
    )


@app.route('/reports/activity-logs-geo')
def activity_logs_geo_report():
    """Redirect to combined Activity & Login Log report."""
    return redirect(url_for('activity_log_report', **request.args))


@app.route('/reports/ai', methods=['GET', 'POST'])
def report_ai():
    """AI-style custom report: user describes what they want; we show a temp view. Close = discard."""
    result_html = None
    report_title = None
    if request.method == 'POST':
        desc = (request.form.get('description') or '').strip().lower()
        if not desc:
            flash('Please describe the report you need.', 'warning')
            return redirect(url_for('report_ai'))
        try:
            if any(w in desc for w in ['driver', 'drivers', 'personnel']):
                drivers = Driver.query.order_by(Driver.name).all()
                report_title = 'Drivers List'
                rows = [{'name': d.name, 'driver_id': d.driver_id, 'cnic': d.cnic_no, 'license': d.license_no, 'phone': d.phone1, 'status': d.status} for d in drivers]
                result_html = _render_ai_report_table(['Name', 'Driver ID', 'CNIC', 'License', 'Phone', 'Status'], rows)
            elif any(w in desc for w in ['vehicle', 'vehicles', 'fleet']):
                vehicles = Vehicle.query.order_by(*vehicle_order_by()).all()
                report_title = 'Vehicles List'
                rows = [{'v_no': v.vehicle_no, 'model': v.model, 'type': v.vehicle_type, 'phone': v.phone_no} for v in vehicles]
                result_html = _render_ai_report_table(['Vehicle No', 'Model', 'Type', 'Phone'], rows)
            elif any(w in desc for w in ['project', 'projects']):
                projects = Project.query.order_by(Project.name).all()
                report_title = 'Project Summary'
                rows = [{'name': p.name, 'vehicles': len(p.vehicles), 'drivers': len(p.drivers), 'status': p.status} for p in projects]
                result_html = _render_ai_report_table(['Project', 'Vehicles', 'Drivers', 'Status'], rows)
            elif any(w in desc for w in ['district', 'districts']):
                districts = District.query.order_by(District.name).all()
                report_title = 'District Summary'
                rows = []
                for d in districts:
                    vc = Vehicle.query.filter_by(district_id=d.id).count()
                    dc = Driver.query.filter_by(district_id=d.id).count()
                    rows.append({'name': d.name, 'vehicles': vc, 'drivers': dc})
                result_html = _render_ai_report_table(['District', 'Vehicles', 'Drivers'], rows)
            elif any(w in desc for w in ['expiry', 'license', 'cnic', 'expiring']):
                from datetime import timedelta
                today = pk_date()
                end = today + timedelta(days=60)
                drivers = Driver.query.filter(Driver.status == 'Active').all()
                expiring = []
                for d in drivers:
                    if (d.license_expiry_date and today <= d.license_expiry_date <= end) or (d.cnic_expiry_date and today <= d.cnic_expiry_date <= end):
                        expiring.append({'name': d.name, 'license_expiry': d.license_expiry_date, 'cnic_expiry': d.cnic_expiry_date})
                report_title = 'License / CNIC Expiry (next 60 days)'
                rows = [{'name': r['name'], 'license_expiry': str(r['license_expiry']) if r['license_expiry'] else '-', 'cnic_expiry': str(r['cnic_expiry']) if r['cnic_expiry'] else '-'} for r in expiring]
                result_html = _render_ai_report_table(['Driver', 'License Expiry', 'CNIC Expiry'], rows)
            elif any(w in desc for w in ['company', 'companies']):
                companies = Company.query.order_by(Company.name).all()
                report_title = 'Companies'
                rows = [{'name': c.name, 'mobile': c.mobile or '-', 'email': c.email or '-'} for c in companies]
                result_html = _render_ai_report_table(['Company', 'Mobile', 'Email'], rows)
            elif any(w in desc for w in ['parking', 'utilization', 'station']):
                stations = ParkingStation.query.order_by(ParkingStation.name).all()
                report_title = 'Parking Utilization'
                rows = []
                for s in stations:
                    occ = Vehicle.query.filter_by(parking_station_id=s.id).count()
                    rows.append({'name': s.name, 'capacity': s.capacity, 'occupied': occ, 'available': s.capacity - occ})
                result_html = _render_ai_report_table(['Station', 'Capacity', 'Occupied', 'Available'], rows)
            elif any(w in desc for w in ['product', 'products', 'item']):
                products = Product.query.order_by(Product.name).all()
                report_title = 'Products (Master)'
                rows = [{'name': p.name, 'used_in': getattr(p, 'used_in_forms', None) or '-'} for p in products]
                result_html = _render_ai_report_table(['Product', 'Used in forms'], rows)
            elif any(w in desc for w in ['party', 'parties']):
                parties = Party.query.order_by(Party.name).all()
                report_title = 'Parties'
                rows = [{'name': p.name, 'contact': (getattr(p, 'contact', None) or '-')[:40]} for p in parties]
                result_html = _render_ai_report_table(['Party', 'Contact'], rows)
            elif any(w in desc for w in ['fuel', 'diesel', 'petrol']):
                # Fuel expenses: last 30 days
                from datetime import timedelta
                today = pk_date()
                start = today - timedelta(days=30)
                q = FuelExpense.query.filter(FuelExpense.fueling_date >= start).order_by(FuelExpense.fueling_date.desc())
                expenses = q.limit(500).all()
                report_title = 'Fuel Expenses (last 30 days)'
                rows = []
                for f in expenses:
                    rows.append({
                        'date': f.fueling_date.strftime('%Y-%m-%d') if f.fueling_date else '',
                        'vehicle': f.vehicle.vehicle_no if f.vehicle else '',
                        'project': f.project.name if f.project else '',
                        'fuel_type': f.fuel_type or '',
                        'liters': f.liters,
                        'amount': f.amount,
                        'km': f.km,
                        'mpg': f.mpg,
                    })
                result_html = _render_ai_report_table(
                    ['Date', 'Vehicle', 'Project', 'Fuel Type', 'Liters', 'Amount', 'KM', 'KM per liter'],
                    rows
                )
            elif any(w in desc for w in ['maintenance', 'repair', 'service']):
                # Maintenance expenses: last 90 days
                from datetime import timedelta
                today = pk_date()
                start = today - timedelta(days=90)
                q = MaintenanceExpense.query.filter(MaintenanceExpense.expense_date >= start).order_by(MaintenanceExpense.expense_date.desc())
                recs = q.limit(500).all()
                report_title = 'Maintenance Expenses (last 90 days)'
                rows = []
                for r in recs:
                    rows.append({
                        'date': r.expense_date.strftime('%Y-%m-%d') if r.expense_date else '',
                        'vehicle': r.vehicle.vehicle_no if r.vehicle else '',
                        'project': r.project.name if r.project else '',
                        'district': r.district.name if r.district else '',
                        'remarks': (r.remarks or '')[:80],
                    })
                result_html = _render_ai_report_table(
                    ['Date', 'Vehicle', 'Project', 'District', 'Remarks'],
                    rows
                )
            elif any(w in desc for w in ['penalty', 'penalties', 'fine', 'fines']):
                # Penalty records: last 60 days
                from datetime import timedelta
                today = pk_date()
                start = today - timedelta(days=60)
                q = PenaltyRecord.query.filter(PenaltyRecord.record_date >= start).order_by(PenaltyRecord.record_date.desc())
                recs = q.limit(500).all()
                report_title = 'Penalties (last 60 days)'
                rows = []
                for r in recs:
                    rows.append({
                        'date': r.record_date.strftime('%Y-%m-%d') if r.record_date else '',
                        'driver': r.driver.name if r.driver else '',
                        'vehicle': r.vehicle.vehicle_no if r.vehicle else '',
                        'project': r.project.name if r.project else '',
                        'fine': r.fine or '',
                        'remarks': (r.remarks or '')[:80],
                    })
                result_html = _render_ai_report_table(
                    ['Date', 'Driver', 'Vehicle', 'Project', 'Fine', 'Remarks'],
                    rows
                )
            elif any(w in desc for w in ['attendance', 'absent', 'present']):
                # Driver attendance summary: last 30 days
                from datetime import timedelta
                today = pk_date()
                start = today - timedelta(days=30)
                q = DriverAttendance.query.filter(DriverAttendance.attendance_date >= start).order_by(DriverAttendance.attendance_date.desc())
                recs = q.limit(500).all()
                report_title = 'Driver Attendance (last 30 days)'
                rows = []
                for r in recs:
                    rows.append({
                        'date': r.attendance_date.strftime('%Y-%m-%d') if r.attendance_date else '',
                        'driver': r.driver.name if r.driver else '',
                        'project': r.project.name if r.project else '',
                        'status': r.status,
                        'remarks': (r.remarks or '')[:80],
                    })
                result_html = _render_ai_report_table(
                    ['Date', 'Driver', 'Project', 'Status', 'Remarks'],
                    rows
                )
            else:
                report_title = 'Suggested reports'
                result_html = (
                    '<p class="text-muted">Try: "list of drivers", "vehicles", "project summary", "district summary", '
                    '"license expiry", "companies", "parking utilization", "products", "parties", '
                    '"fuel expenses", "maintenance expenses", "penalties", or "attendance summary".</p>'
                )
        except Exception as e:
            app.logger.exception(e)
            report_title = 'Error'
            result_html = f'<p class="text-danger">Report could not be generated. Try another keyword (e.g. drivers, vehicles, projects).</p>'
    return render_template('report_ai.html', result_html=result_html, report_title=report_title)


def _render_ai_report_table(headers, rows):
    from markupsafe import escape as _esc
    if not rows:
        return '<p class="text-muted">No data found.</p>'
    keys = list(rows[0].keys()) if rows else []
    h = '<thead class="table-light"><tr>' + ''.join(f'<th>{_esc(x)}</th>' for x in headers) + '</tr></thead>'
    body = '<tbody>'
    for r in rows:
        body += '<tr>' + ''.join(f'<td>{_esc(r.get(k, ""))}</td>' for k in keys) + '</tr>'
    body += '</tbody>'
    return '<table class="table table-bordered table-sm">' + h + body + '</table>'


@app.route('/reports/project-summary')
def report_project_summary():
    from auth_utils import get_user_context
    
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)
    
    from_date_str = (request.args.get('from_date') or '').strip()
    to_date_str = (request.args.get('to_date') or '').strip()
    project_id = request.args.get('project_id', type=int) or 0

    from_date = parse_date(from_date_str) if from_date_str else None
    to_date = parse_date(to_date_str) if to_date_str else None

    projects_q = Project.query
    
    # Apply user data scope
    if not is_master_or_admin and allowed_projects:
        projects_q = projects_q.filter(Project.id.in_(list(allowed_projects)))
    
    projects_q = projects_q.order_by(Project.name)
    if project_id:
        projects_q = projects_q.filter(Project.id == project_id)

    projects = projects_q.all()
    data = []
    for p in projects:
        vehicle_q = Vehicle.query.filter(Vehicle.project_id == p.id)
        if from_date:
            vehicle_q = vehicle_q.filter(Vehicle.active_date >= from_date)
        if to_date:
            vehicle_q = vehicle_q.filter(Vehicle.active_date <= to_date)

        vehicles = vehicle_q.all()
        vehicle_ids = [v.id for v in vehicles]

        driver_q = Driver.query.filter(Driver.project_id == p.id)
        if vehicle_ids:
            driver_q = driver_q.filter(Driver.vehicle_id.in_(vehicle_ids))
        drivers = driver_q.all()

        data.append({
            'project': p,
            'vehicle_count': len(vehicles),
            'driver_count': len(drivers),
            'parking_count': len(p.parking_stations),
            'district_count': p.districts.count(),
        })

    project_choices = [(0, '-- All Projects --')] + [(p.id, p.name) for p in Project.query.order_by(Project.name).all()]

    return render_template(
        'report_project_summary.html',
        data=data,
        from_date=from_date_str,
        to_date=to_date_str,
        project_id=project_id,
        project_choices=project_choices,
    )


@app.route('/reports/district-summary')
def report_district_summary():
    from sqlalchemy import func
    from auth_utils import get_user_context

    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects  = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles  = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)

    district_id = request.args.get('district_id', type=int) or 0
    project_id  = request.args.get('project_id', type=int) or 0

    districts_q = District.query.order_by(District.name)
    if not is_master_or_admin and allowed_districts:
        districts_q = districts_q.filter(District.id.in_(list(allowed_districts)))

    if district_id:
        districts_q = districts_q.filter(District.id == district_id)

    if project_id:
        district_ids_for_project = [
            r[0] for r in db.session.query(project_district.c.district_id)
            .filter(project_district.c.project_id == project_id).all()
        ]
        if district_ids_for_project:
            districts_q = districts_q.filter(District.id.in_(district_ids_for_project))
        else:
            districts_q = districts_q.filter(District.id == -1)

    districts = districts_q.all()
    district_ids = [d.id for d in districts]

    vehicle_counts = {}
    driver_counts = {}
    active_driver_counts = {}
    parking_counts = {}
    project_counts = {}

    if district_ids:
        v_q = db.session.query(Vehicle.district_id, func.count(Vehicle.id)).filter(
            Vehicle.district_id.in_(district_ids)
        )
        if not is_master_or_admin and allowed_vehicles:
            v_q = v_q.filter(Vehicle.id.in_(list(allowed_vehicles)))
        elif not is_master_or_admin and allowed_projects:
            v_q = v_q.filter(Vehicle.project_id.in_(list(allowed_projects)))
        vehicle_counts = dict(v_q.group_by(Vehicle.district_id).all())

        d_q = db.session.query(Driver.district_id, func.count(Driver.id)).filter(
            Driver.district_id.in_(district_ids)
        )
        if not is_master_or_admin and allowed_projects:
            d_q = d_q.filter(Driver.project_id.in_(list(allowed_projects)))
        driver_counts = dict(d_q.group_by(Driver.district_id).all())

        ad_q = db.session.query(Driver.district_id, func.count(Driver.id)).filter(
            Driver.district_id.in_(district_ids),
            Driver.status == 'Active',
            Driver.vehicle_id.isnot(None)
        )
        if not is_master_or_admin and allowed_projects:
            ad_q = ad_q.filter(Driver.project_id.in_(list(allowed_projects)))
        active_driver_counts = dict(ad_q.group_by(Driver.district_id).all())

        pk_sub = db.session.query(
            Vehicle.district_id,
            func.count(func.distinct(Vehicle.parking_station_id))
        ).filter(
            Vehicle.district_id.in_(district_ids),
            Vehicle.parking_station_id.isnot(None)
        )
        if not is_master_or_admin and allowed_vehicles:
            pk_sub = pk_sub.filter(Vehicle.id.in_(list(allowed_vehicles)))
        elif not is_master_or_admin and allowed_projects:
            pk_sub = pk_sub.filter(Vehicle.project_id.in_(list(allowed_projects)))
        parking_counts = dict(pk_sub.group_by(Vehicle.district_id).all())

        project_counts = dict(
            db.session.query(
                project_district.c.district_id,
                func.count(project_district.c.project_id)
            ).filter(
                project_district.c.district_id.in_(district_ids)
            ).group_by(project_district.c.district_id).all()
        )

        cap_q = db.session.query(
            Vehicle.district_id,
            func.coalesce(func.sum(Vehicle.driver_capacity), 0)
        ).filter(Vehicle.district_id.in_(district_ids))
        if not is_master_or_admin and allowed_vehicles:
            cap_q = cap_q.filter(Vehicle.id.in_(list(allowed_vehicles)))
        elif not is_master_or_admin and allowed_projects:
            cap_q = cap_q.filter(Vehicle.project_id.in_(list(allowed_projects)))
        capacity_counts = dict(cap_q.group_by(Vehicle.district_id).all())

    total_vehicles = sum(vehicle_counts.values())
    total_drivers  = sum(driver_counts.values())
    total_active   = sum(active_driver_counts.values())
    total_parking  = sum(parking_counts.values())
    total_vacant   = 0

    data = []
    for d in districts:
        cap = int(capacity_counts.get(d.id, 0) or 0)
        assigned = active_driver_counts.get(d.id, 0)
        vacant = max(0, cap - assigned)
        total_vacant += vacant
        data.append({
            'district': d,
            'vehicle_count': vehicle_counts.get(d.id, 0),
            'driver_count': driver_counts.get(d.id, 0),
            'active_driver_count': active_driver_counts.get(d.id, 0),
            'parking_count': parking_counts.get(d.id, 0),
            'project_count': project_counts.get(d.id, 0),
            'vacant_seats': vacant,
        })

    dist_choices_q = District.query.order_by(District.name)
    if not is_master_or_admin and allowed_districts:
        dist_choices_q = dist_choices_q.filter(District.id.in_(list(allowed_districts)))
    district_choices = [(0, '-- All Districts --')] + [(d.id, d.name) for d in dist_choices_q.all()]

    proj_choices_q = Project.query.order_by(Project.name)
    if not is_master_or_admin and allowed_projects:
        proj_choices_q = proj_choices_q.filter(Project.id.in_(list(allowed_projects)))
    project_choices = [(0, '-- All Projects --')] + [(p.id, p.name) for p in proj_choices_q.all()]

    return render_template('report_district_summary.html',
        data=data,
        district_id=district_id,
        project_id=project_id,
        district_choices=district_choices,
        project_choices=project_choices,
        total_districts=len(districts),
        total_vehicles=total_vehicles,
        total_drivers=total_drivers,
        total_active=total_active,
        total_parking=total_parking,
        total_vacant=total_vacant,
    )


@app.route('/reports/vehicle-summary')
def report_vehicle_summary():
    from auth_utils import get_user_context
    
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)
    
    from_date_str = (request.args.get('from_date') or '').strip()
    to_date_str = (request.args.get('to_date') or '').strip()
    project_id = request.args.get('project_id', type=int) or 0
    district_id = request.args.get('district_id', type=int) or 0
    vehicle_id = request.args.get('vehicle_id', type=int) or 0

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

    from_date = parse_date(from_date_str) if from_date_str else None
    to_date = parse_date(to_date_str) if to_date_str else None

    # Base query: only vehicles assigned to a project (deployed vehicles)
    query = Vehicle.query.filter(Vehicle.project_id.isnot(None))
    
    # Apply user data scope
    if not is_master_or_admin:
        if allowed_projects:
            query = query.filter(Vehicle.project_id.in_(list(allowed_projects)))
        if allowed_districts:
            query = query.filter(Vehicle.district_id.in_(list(allowed_districts)))
        if allowed_vehicles:
            query = query.filter(Vehicle.id.in_(list(allowed_vehicles)))
    
    if project_id:
        query = query.filter(Vehicle.project_id == project_id)
    if district_id:
        query = query.filter(Vehicle.district_id == district_id)
    if vehicle_id:
        query = query.filter(Vehicle.id == vehicle_id)
    # Shift filter via joined drivers (current assignment)

    if from_date:
        query = query.filter(Vehicle.active_date >= from_date)
    if to_date:
        query = query.filter(Vehicle.active_date <= to_date)

    vehicles = query.order_by(*vehicle_order_by()).all()

    # Dropdown choices (scoped + cascaded)
    pq = Project.query
    if not is_master_or_admin and allowed_projects:
        pq = pq.filter(Project.id.in_(list(allowed_projects)))
    project_choices = [(0, '-- All Projects --')] + [(p.id, p.name) for p in pq.order_by(Project.name).all()]

    dq = District.query
    if project_id:
        dq = dq.join(project_district).filter(project_district.c.project_id == project_id)
    if not is_master_or_admin and allowed_districts:
        dq = dq.filter(District.id.in_(list(allowed_districts)))
    district_choices = [(0, '-- All Districts --')] + [(d.id, d.name) for d in dq.order_by(District.name).all()]

    vcq = Vehicle.query.filter(Vehicle.project_id.isnot(None))
    if project_id:
        vcq = vcq.filter(Vehicle.project_id == project_id)
    elif not is_master_or_admin and allowed_projects:
        vcq = vcq.filter(Vehicle.project_id.in_(list(allowed_projects)))
    if district_id:
        vcq = vcq.filter(Vehicle.district_id == district_id)
    elif not is_master_or_admin and allowed_districts:
        vcq = vcq.filter(Vehicle.district_id.in_(list(allowed_districts)))
    if not is_master_or_admin and allowed_vehicles:
        vcq = vcq.filter(Vehicle.id.in_(list(allowed_vehicles)))
    vehicle_choices = [(0, '-- All Vehicles --')] + [(v.id, v.vehicle_no) for v in vcq.order_by(*vehicle_order_by()).all()]

    return render_template(
        'report_vehicle_summary.html',
        vehicles=vehicles,
        from_date=from_date_str,
        to_date=to_date_str,
        project_id=project_id,
        district_id=district_id,
        vehicle_id=vehicle_id,
        project_choices=project_choices,
        district_choices=district_choices,
        vehicle_choices=vehicle_choices,
    )


def _driver_profile_view_core(driver_id):
    """Shared template context for driver profile (authenticated + public share link)."""
    driver = Driver.query.get_or_404(driver_id)
    transfers = DriverTransfer.query.filter_by(driver_id=driver_id).order_by(DriverTransfer.transfer_date.asc()).all()
    status_changes = DriverStatusChange.query.filter_by(driver_id=driver_id).order_by(DriverStatusChange.change_date.asc()).all()

    job_history = []
    if driver.assign_date:
        if transfers:
            first_t = transfers[0]
            _assign_snap = type('Snap', (), {
                'vehicle': first_t.old_vehicle,
                'project': first_t.old_project,
                'district': first_t.old_district,
                'shift': first_t.old_shift,
                'assign_remarks': driver.assign_remarks,
            })()
        else:
            _assign_snap = driver
        job_history.append({'date': driver.assign_date, 'type': 'assignment', 'data': _assign_snap})
    for t in transfers:
        job_history.append({'date': t.transfer_date, 'type': 'transfer', 'data': t})
    for s in status_changes:
        job_history.append({'date': s.change_date, 'type': 'status', 'data': s})
    job_history.sort(key=lambda x: x['date'])

    from datetime import date as _date
    _today_d = _date.today()
    for i, h in enumerate(job_history):
        next_date = job_history[i + 1]['date'] if i + 1 < len(job_history) else _today_d
        h['duration_days'] = (next_date - h['date']).days

    total_actions = len(job_history)
    last_action = job_history[-1]['date'] if job_history else None
    last_action_type = None
    if job_history:
        _la = job_history[-1]
        if _la['type'] == 'assignment':
            last_action_type = 'Assigned'
        elif _la['type'] == 'transfer':
            last_action_type = 'Transferred'
        elif _la['type'] == 'status':
            last_action_type = 'Left' if _la['data'].action_type == 'left' else 'Rejoined'

    _today = pk_date()
    service_days = (_today - driver.application_date).days if driver.application_date else None
    driver_age = None
    if driver.dob:
        driver_age = _today.year - driver.dob.year - ((_today.month, _today.day) < (driver.dob.month, driver.dob.day))
    doc_fields = [driver.photo_path, driver.cnic_front_path, driver.cnic_back_path,
                  driver.license_front_path, driver.license_back_path,
                  driver.verify_license_photo_path, driver.document_path]
    doc_uploaded = sum(1 for d in doc_fields if d)
    doc_total = len(doc_fields)
    jh_counts = {'assignment': 0, 'transfer': 0, 'shift_change': 0, 'left': 0, 'rejoin': 0}
    for h in job_history:
        if h['type'] == 'assignment':
            jh_counts['assignment'] += 1
        elif h['type'] == 'transfer':
            if h['data'].is_shift_only:
                jh_counts['shift_change'] += 1
            else:
                jh_counts['transfer'] += 1
        elif h['type'] == 'status':
            if h['data'].action_type == 'left':
                jh_counts['left'] += 1
            else:
                jh_counts['rejoin'] += 1

    return {
        'driver': driver,
        'job_history': job_history,
        'total_actions': total_actions,
        'last_action': last_action,
        'last_action_type': last_action_type,
        'today': _today,
        'service_days': service_days,
        'driver_age': driver_age,
        'doc_uploaded': doc_uploaded,
        'doc_total': doc_total,
        'jh_counts': jh_counts,
    }


def _driver_update_vehicle_choices(driver=None):
    """Vehicle numbers from Vehicle Parking Inventory (permission-scoped)."""
    from auth_utils import get_user_context

    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)

    q = Vehicle.query.filter(
        Vehicle.parking_station_id.isnot(None),
        Vehicle.vehicle_no.isnot(None),
        Vehicle.vehicle_no != '',
    )
    if not is_master_or_admin:
        if allowed_projects:
            q = q.filter(Vehicle.project_id.in_(list(allowed_projects)))
        if allowed_districts:
            q = q.filter(Vehicle.district_id.in_(list(allowed_districts)))
        if allowed_vehicles:
            q = q.filter(Vehicle.id.in_(list(allowed_vehicles)))
    vehicles = q.order_by(*vehicle_order_by()).all()

    choices = []
    seen = set()
    for v in vehicles:
        vno = (v.vehicle_no or '').strip()
        key = vno.lower()
        if vno and key not in seen:
            seen.add(key)
            choices.append(vno)

    if driver:
        default = (driver.vehicle.vehicle_no if getattr(driver, 'vehicle', None) else '') or ''
        default = default.strip()
        if default and default.lower() not in seen:
            choices.insert(0, default)
    return choices


@app.route('/reports/driver-profile/<int:driver_id>')
def report_driver_profile(driver_id):
    ctx = _driver_profile_view_core(driver_id)
    _from = request.args.get('from', '').strip()
    _ref = request.args.get('ref', '').strip()
    _back_map = {
        'master': url_for('drivers_list'),
        'missing_docs': url_for('missing_documents_report'),
        'active_drivers': url_for('active_drivers_report'),
    }
    ref = _back_map.get(_from) or _ref or ''
    hide_edit = (_from != 'master')
    came_from = _from
    profile_url = url_for('report_driver_profile', driver_id=driver_id, _external=True)
    share_tok = make_driver_profile_share_token(app.config['SECRET_KEY'], driver_id)
    public_share_url = url_for('report_driver_profile_public', token=share_tok, _external=True)
    driver_update_parts = None
    driver_update_vehicle_choices = []
    try:
        from permissions_config import can_see_page
        _perms = session.get('permissions') or []
        _is_master = session.get('is_master', False)
        if _is_master or can_see_page(_perms, 'driver_update_text'):
            driver_update_parts = _build_driver_update_whatsapp_parts(ctx['driver'])
            driver_update_vehicle_choices = _driver_update_vehicle_choices(ctx['driver'])
    except Exception:
        pass
    doc_history_counts = {'cnic': 0, 'license': 0, 'bank_uniform': 0}
    if session.get('is_master'):
        from driver_doc_history_utils import backfill_driver_doc_batch_ids, fetch_driver_doc_history_counts
        backfill_driver_doc_batch_ids(db.session)
        doc_history_counts = fetch_driver_doc_history_counts(db.session, driver_id)
    return render_template(
        'report_driver_profile.html',
        public_view=False,
        public_share_url=public_share_url,
        profile_url=profile_url,
        ref=ref,
        came_from=came_from,
        hide_edit=hide_edit,
        driver_update_parts=driver_update_parts,
        driver_update_vehicle_choices=driver_update_vehicle_choices,
        doc_history_counts=doc_history_counts,
        **ctx,
    )


@app.route('/p/driver-profile/<token>')
def report_driver_profile_public(token):
    """Time-limited read-only driver profile (no login). Token expires after 24 hours."""
    driver_id = load_driver_profile_share_token(app.config['SECRET_KEY'], token)
    if not driver_id:
        return render_template('share_link_expired.html'), 410
    ctx = _driver_profile_view_core(driver_id)
    public_url = url_for('report_driver_profile_public', token=token, _external=True)
    return render_template(
        'report_driver_profile.html',
        public_view=True,
        public_share_url=None,
        profile_url=public_url,
        ref='',
        came_from='public',
        hide_edit=True,
        **ctx,
    )


@app.route('/reports/vehicle-profile/<int:vehicle_id>')
def report_vehicle_profile(vehicle_id):
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    transfers = VehicleTransfer.query.filter_by(vehicle_id=vehicle_id).order_by(VehicleTransfer.transfer_date.desc()).all()
    driver_history = DriverTransfer.query.filter(
        (DriverTransfer.old_vehicle_id == vehicle_id) | (DriverTransfer.new_vehicle_id == vehicle_id)
    ).order_by(DriverTransfer.transfer_date.desc()).all()
    book_assignments = db.session.query(BookAssignment).filter(
        BookAssignment.vehicle_id == vehicle_id
    ).join(PhysicalBook, BookAssignment.book_id == PhysicalBook.id).order_by(
        BookAssignment.issue_date.desc()
    ).all()
    return render_template('report_vehicle_profile.html', vehicle=vehicle, transfers=transfers, driver_history=driver_history, book_assignments=book_assignments, generated_at=pk_now().strftime('%d %b %Y, %I:%M %p'))


@app.route('/reports/expiry')
def report_expiry():
    from datetime import timedelta
    from auth_utils import get_user_context
    
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    
    today = pk_date()
    # days=None or 0 → current (already expired) only; days>0 → expired + next N days
    days = request.args.get('days', type=int)
    if days is None:
        days = 0
    only = (request.args.get('only') or 'all').lower()
    project_id = request.args.get('project_id', type=int) or 0
    district_id = request.args.get('district_id', type=int) or 0
    vehicle_id = request.args.get('vehicle_id', type=int) or 0
    shift = (request.args.get('shift') or '').strip()
    end = today + timedelta(days=days) if days > 0 else today

    # ── Data Context Enforcement ──────────────────────────────────────────
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    allowed_shifts = user_context.get('allowed_shifts', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)
    
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

    # Base driver query with optional filters
    # Sirf woh drivers jinke sath koi vehicle assigned hai
    driver_q = Driver.query.filter(
        Driver.status == 'Active',
        Driver.vehicle_id.isnot(None),
    ).outerjoin(Vehicle, Driver.vehicle_id == Vehicle.id)
    
    # Apply user data scope (non-Master/Admin users)
    if not is_master_or_admin:
        if allowed_projects:
            driver_q = driver_q.filter(
                or_(Driver.project_id.in_(list(allowed_projects)),
                    Vehicle.project_id.in_(list(allowed_projects)))
            )
        if allowed_districts:
            driver_q = driver_q.filter(
                or_(Driver.district_id.in_(list(allowed_districts)),
                    Vehicle.district_id.in_(list(allowed_districts)))
            )
        if allowed_vehicles:
            driver_q = driver_q.filter(Driver.vehicle_id.in_(list(allowed_vehicles)))
    
    if project_id:
        driver_q = driver_q.filter(
            or_(Driver.project_id == project_id, Vehicle.project_id == project_id)
        )
    if district_id:
        driver_q = driver_q.filter(
            or_(Driver.district_id == district_id, Vehicle.district_id == district_id)
        )
    if vehicle_id:
        driver_q = driver_q.filter(Driver.vehicle_id == vehicle_id)
    if shift:
        driver_q = driver_q.filter(Driver.shift == shift)

    drivers = driver_q.distinct().all()
    expiring = []
    for d in drivers:
        row = {'driver': d, 'license_expiry': d.license_expiry_date, 'cnic_expiry': d.cnic_expiry_date}
        row['license_expired'] = bool(d.license_expiry_date and d.license_expiry_date < today)
        row['cnic_expired'] = bool(d.cnic_expiry_date and d.cnic_expiry_date < today)
        row['license_soon'] = bool(days > 0 and d.license_expiry_date and today <= d.license_expiry_date <= end)
        row['cnic_soon'] = bool(days > 0 and d.cnic_expiry_date and today <= d.cnic_expiry_date <= end)

        has_license_issue = row['license_expired'] or row['license_soon']
        has_cnic_issue = row['cnic_expired'] or row['cnic_soon']

        if only == 'license' and not has_license_issue:
            continue
        if only == 'cnic' and not has_cnic_issue:
            continue
        if not (has_license_issue or has_cnic_issue):
            continue

        expiring.append(row)

    # Dropdown choices (scoped to user's assignments)
    project_q = Project.query
    if not is_master_or_admin and allowed_projects:
        project_q = project_q.filter(Project.id.in_(list(allowed_projects)))
    project_choices = [(0, '-- All Projects --')] + [(p.id, p.name) for p in project_q.order_by(Project.name).all()]
    
    district_q = District.query
    if project_id:
        district_q = district_q.join(project_district).filter(project_district.c.project_id == project_id)
    if not is_master_or_admin and allowed_districts:
        district_q = district_q.filter(District.id.in_(list(allowed_districts)))
    district_choices = [(0, '-- All Districts --')] + [(d.id, d.name) for d in district_q.order_by(District.name).all()]
    
    vehicle_choices = [(0, '-- All Vehicles --')]
    base_vehicle_q = Vehicle.query.filter(Vehicle.project_id.isnot(None))
    if not is_master_or_admin and allowed_vehicles:
        base_vehicle_q = base_vehicle_q.filter(Vehicle.id.in_(list(allowed_vehicles)))
    if project_id:
        base_vehicle_q = base_vehicle_q.filter(Vehicle.project_id == project_id)
    if district_id:
        base_vehicle_q = base_vehicle_q.filter(Vehicle.district_id == district_id)
    vehicle_choices += [(v.id, v.vehicle_no) for v in base_vehicle_q.order_by(*vehicle_order_by()).all()]

    # Shift list from active drivers (scoped)
    shift_q = db.session.query(Driver.shift).filter(Driver.shift.isnot(None), Driver.shift != '')
    if not is_master_or_admin and allowed_shifts:
        shift_q = shift_q.filter(Driver.shift.in_(list(allowed_shifts)))
    shift_rows = shift_q.distinct().order_by(Driver.shift).all()
    shift_choices = [('', '-- All Shifts --')] + [(s[0], s[0]) for s in shift_rows]

    return render_template(
        'report_expiry.html',
        expiring=expiring,
        days=days,
        only=only,
        project_choices=project_choices,
        district_choices=district_choices,
        vehicle_choices=vehicle_choices,
        shift_choices=shift_choices,
        disable_project=disable_project,
        disable_district=disable_district,
        project_id=project_id,
        district_id=district_id,
        vehicle_id=vehicle_id,
        shift=shift,
        user_context=user_context,
    )


@app.route('/reports/parking-utilization')
def report_parking_utilization():
    from auth_utils import get_user_context

    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)

    project_id          = request.args.get('project_id', type=int) or 0
    district_id         = request.args.get('district_id', type=int) or 0
    vehicle_id          = request.args.get('vehicle_id', type=int) or 0
    parking_station_id  = request.args.get('parking_station_id', type=int) or 0

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

    # Main query: only vehicles with parking station assigned
    vq = Vehicle.query.filter(Vehicle.parking_station_id.isnot(None))
    if not is_master_or_admin:
        if allowed_projects:
            vq = vq.filter(Vehicle.project_id.in_(list(allowed_projects)))
        if allowed_districts:
            vq = vq.filter(Vehicle.district_id.in_(list(allowed_districts)))
    if project_id:
        vq = vq.filter(Vehicle.project_id == project_id)
    if district_id:
        vq = vq.filter(Vehicle.district_id == district_id)
    if vehicle_id:
        vq = vq.filter(Vehicle.id == vehicle_id)
    if parking_station_id:
        vq = vq.filter(Vehicle.parking_station_id == parking_station_id)
    vehicles = vq.order_by(*vehicle_order_by()).all()

    # Project choices
    pq = Project.query
    if not is_master_or_admin and allowed_projects:
        pq = pq.filter(Project.id.in_(list(allowed_projects)))
    project_choices = [(0, '-- All Projects --')] + [(p.id, p.name) for p in pq.order_by(Project.name).all()]

    # District choices (cascaded by project)
    dq = District.query
    if project_id:
        dq = dq.join(project_district).filter(project_district.c.project_id == project_id)
    if not is_master_or_admin and allowed_districts:
        dq = dq.filter(District.id.in_(list(allowed_districts)))
    district_choices = [(0, '-- All Districts --')] + [(d.id, d.name) for d in dq.order_by(District.name).all()]

    # Vehicle choices (only parking-assigned vehicles, scoped + cascaded)
    vcq = Vehicle.query.filter(Vehicle.parking_station_id.isnot(None))
    if not is_master_or_admin:
        if allowed_projects:
            vcq = vcq.filter(Vehicle.project_id.in_(list(allowed_projects)))
        if allowed_districts:
            vcq = vcq.filter(Vehicle.district_id.in_(list(allowed_districts)))
    if project_id:
        vcq = vcq.filter(Vehicle.project_id == project_id)
    if district_id:
        vcq = vcq.filter(Vehicle.district_id == district_id)
    vehicle_choices = [(0, '-- All Vehicles --')] + [(v.id, v.vehicle_no) for v in vcq.order_by(*vehicle_order_by()).all()]

    # Parking station choices (cascaded by project/district/vehicle)
    ps_vq = Vehicle.query.filter(Vehicle.parking_station_id.isnot(None))
    if not is_master_or_admin and allowed_projects:
        ps_vq = ps_vq.filter(Vehicle.project_id.in_(list(allowed_projects)))
    if project_id:
        ps_vq = ps_vq.filter(Vehicle.project_id == project_id)
    if district_id:
        ps_vq = ps_vq.filter(Vehicle.district_id == district_id)
    if vehicle_id:
        ps_vq = ps_vq.filter(Vehicle.id == vehicle_id)
    assigned_ps_ids = db.session.query(ps_vq.subquery().c.parking_station_id).distinct()
    psq = ParkingStation.query.filter(ParkingStation.id.in_(assigned_ps_ids))
    parking_station_choices = [(0, '-- All Parking Stations --')] + [
        (ps.id, ps.name) for ps in psq.order_by(ParkingStation.name).all()
    ]

    return render_template(
        'report_parking_utilization.html',
        vehicles=vehicles,
        project_id=project_id,
        district_id=district_id,
        vehicle_id=vehicle_id,
        parking_station_id=parking_station_id,
        project_choices=project_choices,
        district_choices=district_choices,
        vehicle_choices=vehicle_choices,
        parking_station_choices=parking_station_choices,
        disable_project=disable_project,
        disable_district=disable_district,
    )
# ════════════════════════════════════════════════════════════════════════════════
