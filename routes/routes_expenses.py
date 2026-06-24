"""
Expense routes - Vehicle reading setup, Fuel, Oil, and Maintenance expenses,
Maintenance work orders, and all expense media routes.

Extracted from routes.py to reduce file size.
Contains all workspace expense helper functions and ~80 routes.
"""
import os
import io
import csv
import tempfile
from io import BytesIO, StringIO
from decimal import Decimal
from datetime import datetime, date, timedelta

import xlsxwriter
from flask import (
    render_template, redirect, url_for, flash, request,
    session, send_file, send_from_directory, jsonify,
    after_this_request, make_response,
)
from sqlalchemy import func, text, or_, cast
from sqlalchemy import String as SAString
from werkzeug.utils import secure_filename

from app import app, db
from models import (
    Company, Project, Vehicle, Driver, ParkingStation, District,
    FuelExpense, FuelExpenseAttachment,
    OilExpense, OilExpenseItem, OilExpenseAttachment,
    MaintenanceWorkOrder, MaintenanceWorkOrderAttachment,
    MaintenanceExpense, MaintenanceExpenseItem, MaintenanceExpenseAttachment,
    ProductBalance, Product, Party,
    WorkspaceProduct, WorkspaceParty, WorkspaceAccount,
    WorkspaceJournalEntry, WorkspaceJournalEntryLine,
    WorkspaceVehicleReadingSetup, WorkspaceVehicleMaintenanceBaseline,
    WorkspaceExpense, ExpenseDeleteCleanupJob,
)
from forms import (
    FuelExpenseFilterForm, FuelExpenseForm,
    OilExpenseFilterForm, OilExpenseForm,
    MaintenanceExpenseFilterForm, MaintenanceExpenseForm,
)
from vehicle_sort_utils import vehicle_order_by
from utils import (
    generate_excel_template, format_reading,
    pk_now, pk_date, parse_date,
)

# Import shared helpers from routes.py
from routes import (
    _get_vehicle_family_options,
    _get_maintenance_job_categories,
    SimplePagination,
    _append_expense_upload_manifest,
    _expense_attachment_max_bytes,
    _fuel_expense_add_form_ctx,
    _fuel_expense_last_entry_payload,
    _fuel_expense_location_cascade_dict,
    _fuel_expense_month_mpg,
    _latest_expense_cleanup_status,
    _prepare_fuel_upload_manifest,
    _prepare_maintenance_upload_manifest,
    _prepare_oil_upload_manifest,
    _prepare_work_order_upload_manifest,
    _read_fuel_market_scan,
    _start_expense_delete_cleanup_worker,
    _start_fuel_upload_worker,
    _start_maintenance_upload_worker,
    _start_oil_upload_worker,
    _start_work_order_upload_worker,
    media_url_filter,
)

# ────────────────────────────────────────────────
# Fuel Expense
# ────────────────────────────────────────────────
_vehicle_maintenance_baseline_schema_ready = {'ok': False}


def _ensure_vehicle_maintenance_baseline_schema():
    if _vehicle_maintenance_baseline_schema_ready.get('ok'):
        return
    stmts = [
        """
        CREATE TABLE IF NOT EXISTS workspace_vehicle_maintenance_baseline (
            id SERIAL PRIMARY KEY,
            employee_id INTEGER NOT NULL,
            district_id INTEGER NULL,
            project_id INTEGER NULL,
            vehicle_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            job_category VARCHAR(120) NULL,
            interval_mode VARCHAR(20) NULL,
            interval_value INTEGER NULL,
            last_done_date DATE NULL,
            last_done_reading NUMERIC(12, 2) NULL,
            remarks TEXT NULL,
            created_by_user_id INTEGER NULL,
            created_at TIMESTAMP NULL DEFAULT NOW(),
            updated_at TIMESTAMP NULL DEFAULT NOW()
        )
        """,
        "ALTER TABLE workspace_vehicle_maintenance_baseline ADD COLUMN IF NOT EXISTS employee_id INTEGER",
        "ALTER TABLE workspace_vehicle_maintenance_baseline ADD COLUMN IF NOT EXISTS district_id INTEGER",
        "ALTER TABLE workspace_vehicle_maintenance_baseline ADD COLUMN IF NOT EXISTS project_id INTEGER",
        "ALTER TABLE workspace_vehicle_maintenance_baseline ADD COLUMN IF NOT EXISTS vehicle_id INTEGER",
        "ALTER TABLE workspace_vehicle_maintenance_baseline ADD COLUMN IF NOT EXISTS product_id INTEGER",
        "ALTER TABLE workspace_vehicle_maintenance_baseline ADD COLUMN IF NOT EXISTS job_category VARCHAR(120)",
        "ALTER TABLE workspace_vehicle_maintenance_baseline ADD COLUMN IF NOT EXISTS interval_mode VARCHAR(20)",
        "ALTER TABLE workspace_vehicle_maintenance_baseline ADD COLUMN IF NOT EXISTS interval_value INTEGER",
        "ALTER TABLE workspace_vehicle_maintenance_baseline ADD COLUMN IF NOT EXISTS last_done_date DATE",
        "ALTER TABLE workspace_vehicle_maintenance_baseline ADD COLUMN IF NOT EXISTS last_done_reading NUMERIC(12, 2)",
        "ALTER TABLE workspace_vehicle_maintenance_baseline ADD COLUMN IF NOT EXISTS remarks TEXT",
        "ALTER TABLE workspace_vehicle_maintenance_baseline ADD COLUMN IF NOT EXISTS created_by_user_id INTEGER",
        "ALTER TABLE workspace_vehicle_maintenance_baseline ADD COLUMN IF NOT EXISTS created_at TIMESTAMP",
        "ALTER TABLE workspace_vehicle_maintenance_baseline ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP",
        "CREATE INDEX IF NOT EXISTS ix_ws_maint_baseline_employee_id ON workspace_vehicle_maintenance_baseline (employee_id)",
        "CREATE INDEX IF NOT EXISTS ix_ws_maint_baseline_vehicle_id ON workspace_vehicle_maintenance_baseline (vehicle_id)",
        "CREATE INDEX IF NOT EXISTS ix_ws_maint_baseline_product_id ON workspace_vehicle_maintenance_baseline (product_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_ws_vehicle_maint_emp_vehicle_product ON workspace_vehicle_maintenance_baseline (employee_id, vehicle_id, product_id)",
    ]
    for stmt in stmts:
        try:
            db.session.execute(text(stmt))
            db.session.commit()
        except Exception:
            db.session.rollback()
    for stmt in [
        "ALTER TABLE workspace_vehicle_maintenance_baseline ALTER COLUMN product_id DROP NOT NULL",
        "DROP INDEX IF EXISTS uq_ws_vehicle_maint_emp_vehicle_product",
        "CREATE INDEX IF NOT EXISTS ix_ws_maint_baseline_emp_veh_jobcat ON workspace_vehicle_maintenance_baseline (employee_id, vehicle_id, job_category)",
    ]:
        try:
            db.session.execute(text(stmt))
            db.session.commit()
        except Exception:
            db.session.rollback()
    _vehicle_maintenance_baseline_schema_ready['ok'] = True


def _vehicle_latest_recorded_reading(vehicle_id):
    if not vehicle_id:
        return None
    latest_values = []
    last_fuel = FuelExpense.query.filter(
        FuelExpense.vehicle_id == vehicle_id,
        FuelExpense.current_reading.isnot(None)
    ).order_by(FuelExpense.fueling_date.desc(), FuelExpense.id.desc()).first()
    if last_fuel and last_fuel.current_reading is not None:
        latest_values.append(float(last_fuel.current_reading))
    last_oil = OilExpense.query.filter(
        OilExpense.vehicle_id == vehicle_id,
        OilExpense.current_reading.isnot(None)
    ).order_by(OilExpense.expense_date.desc(), OilExpense.id.desc()).first()
    if last_oil and last_oil.current_reading is not None:
        latest_values.append(float(last_oil.current_reading))
    last_maint = MaintenanceExpense.query.filter(
        MaintenanceExpense.vehicle_id == vehicle_id,
        MaintenanceExpense.current_reading.isnot(None)
    ).order_by(MaintenanceExpense.expense_date.desc(), MaintenanceExpense.id.desc()).first()
    if last_maint and last_maint.current_reading is not None:
        latest_values.append(float(last_maint.current_reading))
    return max(latest_values) if latest_values else None


def _job_category_config_by_name(name):
    if not name or not str(name).strip():
        return None
    n = (name or '').strip().lower()
    for j in _get_maintenance_job_categories() or []:
        if (j.get('name') or '').strip().lower() == n:
            return j
    return None


def _canonical_job_category_name(user_input):
    u = (user_input or '').strip()
    if not u:
        return None
    for j in _get_maintenance_job_categories() or []:
        jn = (j.get('name') or '').strip()
        if jn and jn.lower() == u.lower():
            return jn
    return None


def _merged_interval_for_baseline(baseline):
    """Row-stored interval (legacy) or from Add Maintenance job category settings."""
    mode = getattr(baseline, 'interval_mode', None) or None
    val = getattr(baseline, 'interval_value', None)
    try:
        val = int(val) if val is not None else None
    except (TypeError, ValueError):
        val = None
    if mode in ('interval_km', 'interval_day') and val and val > 0:
        return mode, val
    jc = getattr(baseline, 'job_category', None)
    cfg = _job_category_config_by_name(jc) if jc else None
    if not cfg:
        return None, None
    m = (cfg.get('interval_mode') or '').strip()
    if m not in ('interval_km', 'interval_day'):
        m = None
    try:
        v = int(float(cfg.get('interval_value')))
    except (TypeError, ValueError):
        v = None
    if m and v and v > 0:
        return m, v
    return None, None


def _format_baseline_reading_display(val):
    """Odometer / km: no trailing .00 (e.g. 2.00 -> 2; 19493.5 stays 19493.5)."""
    if val is None:
        return '-'
    try:
        x = float(val)
    except (TypeError, ValueError):
        return '-'
    r = round(x, 8)
    if abs(r - round(r)) < 1e-7:
        return str(int(round(r)))
    s = f'{r:.8f}'.rstrip('0').rstrip('.')
    return s


def _baseline_status(baseline, latest_reading=None):
    today = pk_date()
    status = 'No Interval'
    next_due_date = None
    next_due_reading = None
    remaining_days = None
    remaining_km = None
    mode, ival = _merged_interval_for_baseline(baseline)
    if mode == 'interval_day' and ival and baseline.last_done_date:
        next_due_date = baseline.last_done_date + timedelta(days=int(ival))
        remaining_days = (next_due_date - today).days
        if remaining_days < 0:
            status = 'Overdue'
        elif remaining_days <= 7:
            status = 'Due Soon'
        else:
            status = 'On Track'
    elif mode == 'interval_km' and ival and baseline.last_done_reading is not None:
        next_due_reading = float(baseline.last_done_reading) + float(ival)
        if latest_reading is None:
            status = 'Reading Needed'
        else:
            remaining_km = next_due_reading - float(latest_reading)
            if remaining_km < 0:
                status = 'Overdue'
            elif remaining_km <= 500:
                status = 'Due Soon'
            else:
                status = 'On Track'
    return {
        'status': status,
        'next_due_date': next_due_date,
        'next_due_date_label': next_due_date.strftime('%d-%m-%Y') if next_due_date else '-',
        'next_due_reading': next_due_reading,
        'next_due_reading_label': _format_baseline_reading_display(next_due_reading)
        if next_due_reading is not None
        else '-',
        'remaining_days': remaining_days,
        'remaining_days_label': str(remaining_days) if remaining_days is not None else '-',
        'remaining_km': remaining_km,
        'remaining_km_label': _format_baseline_reading_display(remaining_km) if remaining_km is not None else '-',
    }


import inspect
import json
import mimetypes
import re
import zipfile
from sqlalchemy.exc import IntegrityError
from urllib.request import Request
from sqlalchemy import and_
from sqlalchemy.orm import joinedload
from urllib.request import urlopen
from models import Employee, VehicleDailyTask
from utils import format_date_ddmmyyyy
from finance_utils import ensure_workspace_base_accounts, ensure_workspace_counterparty_account, workspace_create_journal_entry, workspace_reverse_journal_entry
from models import project_district
@app.route('/expenses/vehicle-reading-setup', methods=['GET', 'POST'])
def vehicle_reading_setup_form():
    _ensure_vehicle_maintenance_baseline_schema()
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return _guard
    workspace_employee_id = _workspace_employee_id_for_expenses()

    districts = District.query.order_by(District.name).all()
    projects = Project.query.order_by(Project.name).all()
    vehicles = Vehicle.query.order_by(*vehicle_order_by()).all()
    job_categories = _get_maintenance_job_categories()

    selected_vehicle_id = request.args.get('vehicle_id', type=int) or 0
    row = None
    baseline_rows = []
    latest_vehicle_reading = None
    if selected_vehicle_id:
        row = WorkspaceVehicleReadingSetup.query.filter_by(
            employee_id=workspace_employee_id,
            vehicle_id=selected_vehicle_id,
        ).first()
        baseline_rows = WorkspaceVehicleMaintenanceBaseline.query.filter_by(
            employee_id=workspace_employee_id,
            vehicle_id=selected_vehicle_id,
        ).order_by(WorkspaceVehicleMaintenanceBaseline.updated_at.desc(), WorkspaceVehicleMaintenanceBaseline.id.desc()).all()
        latest_vehicle_reading = _vehicle_latest_recorded_reading(selected_vehicle_id)

    def vrs_prefill_payload():
        if row:
            return {
                'district_id': row.district_id,
                'project_id': row.project_id,
                'vehicle_id': row.vehicle_id,
                'setup_date': row.setup_date.strftime('%d-%m-%Y') if row.setup_date else None,
                'fuel_previous_reading': float(row.fuel_previous_reading) if row.fuel_previous_reading is not None else None,
                'oil_previous_reading': float(row.oil_previous_reading) if row.oil_previous_reading is not None else None,
                'remarks': row.remarks or '',
            }
        if selected_vehicle_id:
            return {'vehicle_id': selected_vehicle_id}
        return None

    vrs_prefill = vrs_prefill_payload()

    if request.method == 'POST':
        district_id = request.form.get('district_id', type=int) or None
        project_id = request.form.get('project_id', type=int) or None
        vehicle_id = request.form.get('vehicle_id', type=int) or None
        setup_date = parse_date(request.form.get('setup_date'))
        fuel_prev_raw = (request.form.get('fuel_previous_reading') or '').strip()
        oil_prev_raw = (request.form.get('oil_previous_reading') or '').strip()
        remarks = (request.form.get('remarks') or '').strip() or None
        baselines_json_raw = (request.form.get('baselines_data') or '').strip()
        if not vehicle_id:
            flash('Please select vehicle.', 'danger')
            return render_template(
                'vehicle_reading_setup_form.html',
                districts=districts, projects=projects, vehicles=vehicles,
                row=row, selected_vehicle_id=selected_vehicle_id,
                job_categories=job_categories,
                latest_vehicle_reading=latest_vehicle_reading,
                vrs_prefill=vrs_prefill,
                initial_baselines_json=baselines_json_raw or '[]',
            )
        if not setup_date:
            flash('Please select setup date.', 'danger')
            return render_template(
                'vehicle_reading_setup_form.html',
                districts=districts, projects=projects, vehicles=vehicles,
                row=row, selected_vehicle_id=selected_vehicle_id,
                job_categories=job_categories,
                latest_vehicle_reading=latest_vehicle_reading,
                vrs_prefill=vrs_prefill,
                initial_baselines_json=baselines_json_raw or '[]',
            )

        def _to_dec(raw):
            if not raw:
                return None
            return Decimal(str(raw))

        try:
            fuel_prev = _to_dec(fuel_prev_raw)
            oil_prev = _to_dec(oil_prev_raw)
        except Exception:
            flash('Fuel / Oil previous reading numeric honi chahiye.', 'danger')
            return render_template(
                'vehicle_reading_setup_form.html',
                districts=districts, projects=projects, vehicles=vehicles,
                row=row, selected_vehicle_id=selected_vehicle_id,
                job_categories=job_categories,
                baseline_rows=[],
                latest_vehicle_reading=latest_vehicle_reading,
                vrs_prefill=vrs_prefill,
                initial_baselines_json='[]',
            )

        # Parse job-category baselines (same pattern as product lines on Add Maintenance)
        bl_parsed = []
        try:
            bl_parsed = json.loads(baselines_json_raw) if baselines_json_raw else []
        except (json.JSONDecodeError, TypeError, ValueError):
            bl_parsed = []
        if not isinstance(bl_parsed, list):
            bl_parsed = []

        bl_for_save = []
        seen_cat = set()
        baseline_error = None
        for item in bl_parsed:
            if not isinstance(item, dict):
                continue
            jn = (item.get('job_category') or '').strip()
            if not jn:
                continue
            cat_name = _canonical_job_category_name(jn)
            if not cat_name:
                baseline_error = f'Job category manzoor shuda list se ho: {jn}'
                break
            ck = cat_name.lower()
            if ck in seen_cat:
                baseline_error = f'Duplicate job category: {cat_name}'
                break
            seen_cat.add(ck)
            ds = (item.get('last_done_date') or '').strip()
            ldd = parse_date(ds) if ds else None
            lrraw = (item.get('last_done_reading') or '').strip()
            lr = None
            if lrraw:
                try:
                    lr = _to_dec(lrraw)
                except Exception:
                    baseline_error = f'Last done reading number honi chahiye ({cat_name})'
                    break
            brem = (item.get('remarks') or '').strip() or None
            bl_for_save.append({
                'cat_name': cat_name,
                'last_done_date': ldd,
                'last_reading': lr,
                'remarks': brem,
            })

        if baseline_error:
            flash(baseline_error, 'danger')
            return render_template(
                'vehicle_reading_setup_form.html',
                districts=districts, projects=projects, vehicles=vehicles,
                row=row, selected_vehicle_id=selected_vehicle_id,
                job_categories=job_categories,
                latest_vehicle_reading=latest_vehicle_reading,
                vrs_prefill=vrs_prefill,
                initial_baselines_json=baselines_json_raw or '[]',
            )

        rec = WorkspaceVehicleReadingSetup.query.filter_by(
            employee_id=workspace_employee_id,
            vehicle_id=vehicle_id,
        ).first()
        if not rec:
            rec = WorkspaceVehicleReadingSetup(
                employee_id=workspace_employee_id,
                vehicle_id=vehicle_id,
            )
            db.session.add(rec)

        rec.district_id = district_id
        rec.project_id = project_id
        rec.setup_date = setup_date
        rec.fuel_previous_reading = fuel_prev
        rec.oil_previous_reading = oil_prev
        rec.remarks = remarks
        rec.created_by_user_id = session.get('user_id')

        # Replace baselines for this vehicle (table = full state)
        WorkspaceVehicleMaintenanceBaseline.query.filter_by(
            employee_id=workspace_employee_id,
            vehicle_id=vehicle_id,
        ).delete()
        for bl in bl_for_save:
            cfg = _job_category_config_by_name(bl['cat_name'])
            base = WorkspaceVehicleMaintenanceBaseline(
                employee_id=workspace_employee_id,
                vehicle_id=vehicle_id,
                product_id=None,
                job_category=bl['cat_name'],
                district_id=district_id,
                project_id=project_id,
            )
            if cfg:
                base.interval_mode = cfg.get('interval_mode')
                try:
                    base.interval_value = int(float(cfg.get('interval_value', 0)))
                except (TypeError, ValueError):
                    base.interval_value = None
            base.last_done_date = bl['last_done_date']
            base.last_done_reading = bl['last_reading']
            base.remarks = bl['remarks']
            base.created_by_user_id = session.get('user_id')
            db.session.add(base)

        db.session.commit()
        nbl = len(bl_for_save)
        if nbl:
            flash(
                f'Vehicle setup save ho gaya. {nbl} job category baseline(s) update.',
                'success',
            )
        else:
            flash('Vehicle previous reading setup save ho gaya.', 'success')
        return redirect(url_for('vehicle_reading_setup_list'))

    initial_baseline_list = []
    if baseline_rows:
        for b in baseline_rows:
            initial_baseline_list.append({
                'job_category': (b.job_category or '').strip(),
                'last_done_date': b.last_done_date.strftime('%d-%m-%Y') if b.last_done_date else '',
                'last_done_reading': f'{float(b.last_done_reading):.2f}' if b.last_done_reading is not None else '',
                'remarks': (b.remarks or '').strip(),
            })
    initial_baselines_json = json.dumps(initial_baseline_list, ensure_ascii=True)

    return render_template(
        'vehicle_reading_setup_form.html',
        districts=districts,
        projects=projects,
        vehicles=vehicles,
        row=row,
        selected_vehicle_id=selected_vehicle_id,
        job_categories=job_categories,
        latest_vehicle_reading=latest_vehicle_reading,
        vrs_prefill=vrs_prefill,
        initial_baselines_json=initial_baselines_json,
    )


@app.route('/expenses/vehicle-reading-setups')
def vehicle_reading_setup_list():
    _ensure_vehicle_maintenance_baseline_schema()
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return _guard
    workspace_employee_id = _workspace_employee_id_for_expenses()

    from_date = parse_date(request.args.get('from_date'))
    to_date = parse_date(request.args.get('to_date'))
    district_id = request.args.get('district_id', type=int) or 0
    project_id = request.args.get('project_id', type=int) or 0
    vehicle_id = request.args.get('vehicle_id', type=int) or 0
    search = (request.args.get('search') or '').strip()

    q = WorkspaceVehicleReadingSetup.query.filter_by(employee_id=workspace_employee_id)
    if from_date:
        q = q.filter(WorkspaceVehicleReadingSetup.setup_date >= from_date)
    if to_date:
        q = q.filter(WorkspaceVehicleReadingSetup.setup_date <= to_date)
    if district_id:
        q = q.filter(WorkspaceVehicleReadingSetup.district_id == district_id)
    if project_id:
        q = q.filter(WorkspaceVehicleReadingSetup.project_id == project_id)
    if vehicle_id:
        q = q.filter(WorkspaceVehicleReadingSetup.vehicle_id == vehicle_id)
    if search:
        like = f"%{search}%"
        q = q.join(Vehicle, WorkspaceVehicleReadingSetup.vehicle_id == Vehicle.id).filter(
            or_(
                Vehicle.vehicle_no.ilike(like),
                WorkspaceVehicleReadingSetup.remarks.ilike(like),
            )
        )

    rows = q.order_by(
        WorkspaceVehicleReadingSetup.setup_date.desc(),
        WorkspaceVehicleReadingSetup.id.desc(),
    ).all()

    page = max(request.args.get('page', 1, type=int) or 1, 1)
    per_page = request.args.get('per_page', 20, type=int) or 20
    if per_page not in (10, 20, 50, 100):
        per_page = 20
    pagination = SimplePagination(rows, page, per_page)

    districts = District.query.order_by(District.name).all()
    projects = Project.query.order_by(Project.name).all()
    vehicles = Vehicle.query.order_by(*vehicle_order_by()).all()
    vehicle_ids = [r.vehicle_id for r in pagination.items if r.vehicle_id]
    baseline_counts = {}
    overdue_counts = {}
    if vehicle_ids:
        bl_rows = WorkspaceVehicleMaintenanceBaseline.query.filter(
            WorkspaceVehicleMaintenanceBaseline.employee_id == workspace_employee_id,
            WorkspaceVehicleMaintenanceBaseline.vehicle_id.in_(vehicle_ids),
        ).all()
        for b in bl_rows:
            baseline_counts[b.vehicle_id] = baseline_counts.get(b.vehicle_id, 0) + 1
            stat = _baseline_status(b, latest_reading=_vehicle_latest_recorded_reading(b.vehicle_id))
            if stat['status'] == 'Overdue':
                overdue_counts[b.vehicle_id] = overdue_counts.get(b.vehicle_id, 0) + 1

    return render_template(
        'vehicle_reading_setup_list.html',
        rows=pagination.items,
        pagination=pagination,
        per_page=per_page,
        from_date=from_date,
        to_date=to_date,
        district_id=district_id,
        project_id=project_id,
        vehicle_id=vehicle_id,
        search=search,
        districts=districts,
        projects=projects,
        vehicles=vehicles,
        baseline_counts=baseline_counts,
        overdue_counts=overdue_counts,
    )


def _vehicle_reading_setup_rows(employee_id, from_date=None, to_date=None, district_id=0, project_id=0, vehicle_id=0, search=''):
    q = WorkspaceVehicleReadingSetup.query.filter_by(employee_id=employee_id)
    if from_date:
        q = q.filter(WorkspaceVehicleReadingSetup.setup_date >= from_date)
    if to_date:
        q = q.filter(WorkspaceVehicleReadingSetup.setup_date <= to_date)
    if district_id:
        q = q.filter(WorkspaceVehicleReadingSetup.district_id == district_id)
    if project_id:
        q = q.filter(WorkspaceVehicleReadingSetup.project_id == project_id)
    if vehicle_id:
        q = q.filter(WorkspaceVehicleReadingSetup.vehicle_id == vehicle_id)
    if search:
        like = f"%{search}%"
        q = q.join(Vehicle, WorkspaceVehicleReadingSetup.vehicle_id == Vehicle.id).filter(
            or_(
                Vehicle.vehicle_no.ilike(like),
                WorkspaceVehicleReadingSetup.remarks.ilike(like),
            )
        )
    return q.order_by(
        WorkspaceVehicleReadingSetup.setup_date.desc(),
        WorkspaceVehicleReadingSetup.id.desc(),
    ).all()


@app.route('/expenses/vehicle-reading-setups/export')
def vehicle_reading_setup_export():
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return _guard
    workspace_employee_id = _workspace_employee_id_for_expenses()
    from_date = parse_date(request.args.get('from_date'))
    to_date = parse_date(request.args.get('to_date'))
    district_id = request.args.get('district_id', type=int) or 0
    project_id = request.args.get('project_id', type=int) or 0
    vehicle_id = request.args.get('vehicle_id', type=int) or 0
    search = (request.args.get('search') or '').strip()

    rows = _vehicle_reading_setup_rows(
        workspace_employee_id,
        from_date=from_date,
        to_date=to_date,
        district_id=district_id,
        project_id=project_id,
        vehicle_id=vehicle_id,
        search=search,
    )

    headers = ['S.No', 'Date', 'District', 'Project', 'Vehicle', 'Fuel Previous', 'Oil Previous', 'Remarks']
    data_rows = []
    for i, r in enumerate(rows, 1):
        data_rows.append([
            i,
            r.setup_date.strftime('%d-%m-%Y') if r.setup_date else '',
            r.district.name if r.district else '',
            r.project.name if r.project else '',
            r.vehicle.vehicle_no if r.vehicle else '',
            float(r.fuel_previous_reading) if r.fuel_previous_reading is not None else '',
            float(r.oil_previous_reading) if r.oil_previous_reading is not None else '',
            r.remarks or '',
        ])
    return generate_excel_template(headers, data_rows, required_columns=[], filename='vehicle_reading_setup.xlsx')


@app.route('/expenses/vehicle-reading-setups/print')
def vehicle_reading_setup_print():
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return _guard
    workspace_employee_id = _workspace_employee_id_for_expenses()
    from_date = parse_date(request.args.get('from_date'))
    to_date = parse_date(request.args.get('to_date'))
    district_id = request.args.get('district_id', type=int) or 0
    project_id = request.args.get('project_id', type=int) or 0
    vehicle_id = request.args.get('vehicle_id', type=int) or 0
    search = (request.args.get('search') or '').strip()

    rows = _vehicle_reading_setup_rows(
        workspace_employee_id,
        from_date=from_date,
        to_date=to_date,
        district_id=district_id,
        project_id=project_id,
        vehicle_id=vehicle_id,
        search=search,
    )
    return render_template(
        'vehicle_reading_setup_print.html',
        rows=rows,
        from_date=from_date,
        to_date=to_date,
        district_id=district_id,
        project_id=project_id,
        vehicle_id=vehicle_id,
        search=search,
    )


@app.route('/expenses/vehicle-reading-setup/import', methods=['GET', 'POST'])
def vehicle_reading_setup_import():
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return _guard
    workspace_employee_id = _workspace_employee_id_for_expenses()
    import_errors = []

    if request.method == 'POST':
        file_obj = request.files.get('file')
        if not file_obj or not (file_obj.filename or '').strip():
            flash('Please select an Excel or CSV file.', 'warning')
            return redirect(url_for('vehicle_reading_setup_import'))
        filename = file_obj.filename or ''
        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
        if ext not in ('xlsx', 'xls', 'csv'):
            flash('Unsupported file type. Use .xlsx, .xls or .csv.', 'danger')
            return redirect(url_for('vehicle_reading_setup_import'))

        try:
            import pandas as pd
            if ext in ('xlsx', 'xls'):
                df = pd.read_excel(file_obj)
            else:
                df = pd.read_csv(file_obj)

            required_cols = ['setup_date', 'district', 'project', 'vehicle']
            missing = [c for c in required_cols if c not in df.columns]
            if missing:
                flash(f"Missing required columns: {', '.join(missing)}", 'danger')
                return redirect(url_for('vehicle_reading_setup_import'))

            district_map = {d.name.strip().lower(): d.id for d in District.query.order_by(District.name).all() if d.name}
            project_map = {p.name.strip().lower(): p.id for p in Project.query.order_by(Project.name).all() if p.name}
            vehicle_map = {v.vehicle_no.strip().lower(): v.id for v in Vehicle.query.order_by(*vehicle_order_by()).all() if v.vehicle_no}
            rows_to_save = []

            def _to_dec(raw):
                if raw is None:
                    return None
                s = str(raw).strip()
                if not s or s.lower() == 'nan':
                    return None
                return Decimal(s)

            def _to_date(raw):
                if raw is None:
                    return None
                if hasattr(raw, 'date'):
                    try:
                        return raw.date()
                    except Exception:
                        pass
                s = str(raw).strip()
                if not s or s.lower() == 'nan':
                    return None
                d = parse_date(s)
                if d:
                    return d
                try:
                    return pd.to_datetime(s, errors='coerce').date()
                except Exception:
                    return None

            for idx, row in df.iterrows():
                row_no = idx + 2
                issues = []
                setup_date = _to_date(row.get('setup_date'))
                if not setup_date:
                    issues.append('"setup_date" is required.')

                district_name = str(row.get('district', '')).strip() if not pd.isna(row.get('district')) else ''
                district_id = district_map.get(district_name.lower()) if district_name else None
                if not district_id:
                    issues.append(f'District "{district_name or "-"}" not found.')

                project_name = str(row.get('project', '')).strip() if not pd.isna(row.get('project')) else ''
                project_id = project_map.get(project_name.lower()) if project_name else None
                if not project_id:
                    issues.append(f'Project "{project_name or "-"}" not found.')

                vehicle_no = str(row.get('vehicle', '')).strip() if not pd.isna(row.get('vehicle')) else ''
                vehicle_id = vehicle_map.get(vehicle_no.lower()) if vehicle_no else None
                if not vehicle_id:
                    issues.append(f'Vehicle "{vehicle_no or "-"}" not found.')

                try:
                    fuel_prev = _to_dec(row.get('fuel_previous_reading'))
                    oil_prev = _to_dec(row.get('oil_previous_reading'))
                except Exception:
                    issues.append('Fuel/Oil previous reading must be numeric.')
                    fuel_prev = oil_prev = None

                if issues:
                    import_errors.append({
                        'row': row_no,
                        'identifier': vehicle_no or '-',
                        'message': '; '.join(issues),
                    })
                    continue

                remarks = str(row.get('remarks', '')).strip() if 'remarks' in df.columns and not pd.isna(row.get('remarks')) else ''
                rows_to_save.append({
                    'setup_date': setup_date,
                    'district_id': district_id,
                    'project_id': project_id,
                    'vehicle_id': vehicle_id,
                    'fuel_previous_reading': fuel_prev,
                    'oil_previous_reading': oil_prev,
                    'remarks': remarks or None,
                })

            if import_errors:
                return render_template('vehicle_reading_setup_import.html', import_errors=import_errors)

            for payload in rows_to_save:
                rec = WorkspaceVehicleReadingSetup.query.filter_by(
                    employee_id=workspace_employee_id,
                    vehicle_id=payload['vehicle_id'],
                ).first()
                if not rec:
                    rec = WorkspaceVehicleReadingSetup(
                        employee_id=workspace_employee_id,
                        vehicle_id=payload['vehicle_id'],
                    )
                    db.session.add(rec)
                rec.setup_date = payload['setup_date']
                rec.district_id = payload['district_id']
                rec.project_id = payload['project_id']
                rec.fuel_previous_reading = payload['fuel_previous_reading']
                rec.oil_previous_reading = payload['oil_previous_reading']
                rec.remarks = payload['remarks']
                rec.created_by_user_id = session.get('user_id')

            db.session.commit()
            flash(f"{len(rows_to_save)} vehicle reading setup rows imported successfully.", 'success')
            return redirect(url_for('vehicle_reading_setup_list'))
        except Exception as exc:
            db.session.rollback()
            flash(f"Import failed: {exc}", 'danger')

    return render_template('vehicle_reading_setup_import.html', import_errors=import_errors)


@app.route('/expenses/vehicle-reading-setup/import/template')
def vehicle_reading_setup_import_template():
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return _guard
    headers = ['setup_date', 'district', 'project', 'vehicle', 'fuel_previous_reading', 'oil_previous_reading', 'remarks']
    rows = [
        ['01-03-2026', 'Muzaffargarh', 'RAS-1034', 'LEA-1064', 125000, 125000, 'Initial readings'],
        ['01-03-2026', 'Muzaffargarh', 'RAS-1034', 'LEA-1065', 98000, 98000, 'Initial readings'],
    ]
    return generate_excel_template(headers, rows, required_columns=['setup_date', 'district', 'project', 'vehicle'], filename='vehicle_reading_setup_import_template.xlsx')


@app.route('/api/vehicle-reading-setup')
def api_vehicle_reading_setup():
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return jsonify({})
    workspace_employee_id = _workspace_employee_id_for_expenses()
    vehicle_id = request.args.get('vehicle_id', type=int)
    if not vehicle_id:
        return jsonify({})

    row = WorkspaceVehicleReadingSetup.query.filter_by(
        employee_id=workspace_employee_id,
        vehicle_id=vehicle_id,
    ).first()
    payload = {
        'fuel_previous_reading': float(row.fuel_previous_reading) if row and row.fuel_previous_reading is not None else None,
        'oil_previous_reading': float(row.oil_previous_reading) if row and row.oil_previous_reading is not None else None,
        'district_id': row.district_id if row else None,
        'project_id': row.project_id if row else None,
        'setup_date': row.setup_date.strftime('%d-%m-%Y') if row and row.setup_date else None,
        'remarks': row.remarks if row else '',
    }
    if row:
        return jsonify(payload)

    last_fuel = FuelExpense.query.filter_by(vehicle_id=vehicle_id).order_by(FuelExpense.fueling_date.desc(), FuelExpense.id.desc()).first()
    last_oil = OilExpense.query.filter_by(vehicle_id=vehicle_id).order_by(OilExpense.expense_date.desc(), OilExpense.id.desc()).first()
    payload['fuel_previous_reading'] = float(last_fuel.current_reading) if last_fuel and last_fuel.current_reading is not None else None
    payload['oil_previous_reading'] = float(last_oil.current_reading) if last_oil and last_oil.current_reading is not None else None
    return jsonify(payload)


def _fuel_expense_task_readings(vehicle_id, task_date):
    """Return (km_out_day_start, km_in_day_close) from VehicleDailyTask for given vehicle and date. None if no task."""
    task = VehicleDailyTask.query.filter_by(vehicle_id=vehicle_id, task_date=task_date).first()
    if not task:
        return None, None
    prev = VehicleDailyTask.query.filter(
        VehicleDailyTask.vehicle_id == vehicle_id,
        VehicleDailyTask.task_date < task_date
    ).order_by(VehicleDailyTask.task_date.desc()).first()
    km_out = float(prev.close_reading) if prev else None
    km_in = float(task.close_reading)
    return km_out, km_in


def _fuel_expense_previous_reading(vehicle_id, fueling_date=None, exclude_id=None, workspace_employee_id=None, current_reading=None):
    if not vehicle_id:
        return None
    q = FuelExpense.query.filter(FuelExpense.vehicle_id == vehicle_id)
    if exclude_id:
        q = q.filter(FuelExpense.id != exclude_id)
    if fueling_date and current_reading is not None:
        try:
            curr_val = float(current_reading)
        except (TypeError, ValueError):
            curr_val = None
        if curr_val is not None:
            same_day_prev = q.filter(
                FuelExpense.fueling_date == fueling_date,
                FuelExpense.current_reading.isnot(None),
                FuelExpense.current_reading < curr_val,
            ).order_by(
                FuelExpense.current_reading.desc(),
                FuelExpense.id.desc(),
            ).first()
            if same_day_prev and same_day_prev.current_reading is not None:
                return float(same_day_prev.current_reading)
    if fueling_date:
        if current_reading is not None:
            q = q.filter(FuelExpense.fueling_date < fueling_date)
        elif exclude_id:
            q = q.filter(
                db.or_(
                    FuelExpense.fueling_date < fueling_date,
                    db.and_(FuelExpense.fueling_date == fueling_date, FuelExpense.id < int(exclude_id)),
                )
            )
        else:
            q = q.filter(FuelExpense.fueling_date <= fueling_date)
    last_entry = q.order_by(FuelExpense.fueling_date.desc(), FuelExpense.id.desc()).first()
    if last_entry and last_entry.current_reading is not None:
        return float(last_entry.current_reading)
    return _fallback_vehicle_previous_reading(workspace_employee_id, vehicle_id, 'fuel')


def _resequence_vehicle_fuel_expenses(vehicle_id, workspace_employee_id=None):
    if not vehicle_id:
        return
    rows = FuelExpense.query.filter(
        FuelExpense.vehicle_id == vehicle_id
    ).order_by(
        FuelExpense.fueling_date.asc(),
        db.case((FuelExpense.current_reading.is_(None), 1), else_=0).asc(),
        FuelExpense.current_reading.asc(),
        FuelExpense.id.asc(),
    ).all()
    previous_current = None
    for idx, row in enumerate(rows):
        if idx == 0:
            if row.previous_reading is None:
                row.previous_reading = _fallback_vehicle_previous_reading(
                    workspace_employee_id or row.employee_id, vehicle_id, 'fuel'
                )
        else:
            row.previous_reading = previous_current

        prev_val = float(row.previous_reading) if row.previous_reading is not None else None
        curr_val = float(row.current_reading) if row.current_reading is not None else None
        row.km = (curr_val - prev_val) if (prev_val is not None and curr_val is not None) else None
        liters_val = float(row.liters) if row.liters is not None else None
        row.mpg = round(float(row.km) / liters_val, 2) if (row.km is not None and liters_val and liters_val > 0) else None

        previous_current = curr_val


@app.route('/api/fuel-expense/last-reading')
def api_fuel_expense_last_reading():
    """Return last fueling entry's current_reading for vehicle_id (for Previous Reading)."""
    vehicle_id = request.args.get('vehicle_id', type=int)
    fueling_date = parse_date(request.args.get('fueling_date', ''))
    exclude_id = request.args.get('exclude_id', type=int)
    current_reading = request.args.get('current_reading', type=float)
    if not vehicle_id:
        return jsonify({'previous_reading': None, 'fuel_type': None})
    vehicle = db.session.get(Vehicle, vehicle_id)
    vehicle_fuel_type = (vehicle.fuel_type if vehicle and vehicle.fuel_type else 'Petrol')
    workspace_employee_id = _workspace_employee_id_for_expenses()
    previous_reading = _fuel_expense_previous_reading(
        vehicle_id=vehicle_id,
        fueling_date=fueling_date,
        exclude_id=exclude_id,
        workspace_employee_id=workspace_employee_id,
        current_reading=current_reading,
    )
    return jsonify({'previous_reading': previous_reading, 'fuel_type': vehicle_fuel_type})


@app.route('/api/fuel-expense/last-entry')
def api_fuel_expense_last_entry():
    """Latest fuel expense for a specific vehicle (shown under Vehicle No on the form)."""
    vehicle_id = request.args.get('vehicle_id', type=int)
    exclude_id = request.args.get('exclude_id', type=int)
    if not vehicle_id:
        return jsonify({'ok': True, 'entry': None})
    q = FuelExpense.query.filter(FuelExpense.vehicle_id == vehicle_id)
    if exclude_id:
        q = q.filter(FuelExpense.id != exclude_id)
    rec = q.options(
        joinedload(FuelExpense.workspace_pump),
        joinedload(FuelExpense.fuel_pump),
        joinedload(FuelExpense.district),
        joinedload(FuelExpense.project),
        joinedload(FuelExpense.vehicle),
    ).order_by(FuelExpense.fueling_date.desc(), FuelExpense.id.desc()).first()
    return jsonify({'ok': True, 'entry': _fuel_expense_last_entry_payload(rec)})


@app.route('/api/fuel-expense/detail/<int:pk>')
def api_fuel_expense_detail(pk):
    """Full fuel entry payload for detail popups (Last Saved, etc.)."""
    workspace_employee_id = _workspace_employee_id_for_expenses()
    q = FuelExpense.query.options(
        joinedload(FuelExpense.workspace_pump),
        joinedload(FuelExpense.fuel_pump),
        joinedload(FuelExpense.district),
        joinedload(FuelExpense.project),
        joinedload(FuelExpense.vehicle),
    ).filter_by(id=pk)
    if workspace_employee_id:
        q = q.filter_by(employee_id=workspace_employee_id)
    rec = q.first()
    if not rec:
        return jsonify({'ok': False, 'entry': None}), 404
    return jsonify({'ok': True, 'entry': _fuel_expense_last_entry_payload(rec)})


@app.route('/api/fuel-expense/task-readings')
def api_fuel_expense_task_readings():
    """Return km_out (Day Start) and km_in (Day Close) from task report for vehicle_id and fueling_date."""
    vehicle_id = request.args.get('vehicle_id', type=int)
    date_str = request.args.get('fueling_date', '')
    if not vehicle_id or not date_str:
        return jsonify({'km_out_task': None, 'km_in_task': None})
    task_date = parse_date(date_str)
    if not task_date:
        return jsonify({'km_out_task': None, 'km_in_task': None})
    km_out, km_in = _fuel_expense_task_readings(vehicle_id, task_date)
    return jsonify({'km_out_task': km_out, 'km_in_task': km_in})


@app.route('/api/fuel-expense/suggested-price')
def api_fuel_expense_suggested_price():
    """Return suggested fuel price by same date and/or same pump context."""
    fuel_type = request.args.get('fuel_type', '').strip()
    normalized = 'Super' if fuel_type == 'Petrol' else fuel_type
    fuel_pump_id = request.args.get('fuel_pump_id', type=int)
    fueling_date = parse_date(request.args.get('fueling_date', ''))
    exclude_id = request.args.get('exclude_id', type=int) or request.args.get('current_id', type=int)
    workspace_employee_id = _workspace_employee_id_for_expenses()
    if normalized not in ('Diesel', 'Super'):
        return jsonify({'fuel_price': None, 'source': ''})
    if normalized == 'Super':
        fuel_filter = FuelExpense.fuel_type.in_(('Super', 'Petrol'))
    else:
        fuel_filter = FuelExpense.fuel_type == normalized
    base_q = FuelExpense.query.filter(fuel_filter, FuelExpense.fuel_price.isnot(None))
    if workspace_employee_id:
        base_q = base_q.filter(FuelExpense.employee_id == workspace_employee_id)
    if exclude_id:
        base_q = base_q.filter(FuelExpense.id != exclude_id)

    suggested_row = None
    source = ''
    if fuel_pump_id and fueling_date:
        suggested_row = base_q.filter(
            FuelExpense.workspace_pump_id == fuel_pump_id,
            FuelExpense.fueling_date == fueling_date,
        ).order_by(FuelExpense.id.desc()).first()
        if suggested_row:
            source = 'same_date_same_pump'
    if not suggested_row and fueling_date:
        suggested_row = base_q.filter(
            FuelExpense.fueling_date == fueling_date,
        ).order_by(FuelExpense.id.desc()).first()
        if suggested_row:
            source = 'same_date'
    if not suggested_row and fuel_pump_id:
        suggested_row = base_q.filter(
            FuelExpense.workspace_pump_id == fuel_pump_id,
        ).order_by(FuelExpense.fueling_date.desc(), FuelExpense.id.desc()).first()
        if suggested_row:
            source = 'same_pump'
    return jsonify({
        'fuel_price': float(suggested_row.fuel_price) if suggested_row and suggested_row.fuel_price is not None else None,
        'source': source,
    })


@app.route('/api/fuel-expense/price-hint')
def api_fuel_expense_price_hint():
    """Return last 2 entries for current pump + fuel_type, and 2 other pumps' latest entry (same fuel_type) for price reference."""
    fuel_type = request.args.get('fuel_type', '').strip()
    normalized = 'Super' if fuel_type == 'Petrol' else fuel_type
    fuel_pump_id = request.args.get('fuel_pump_id', type=int)
    employee_id = _workspace_employee_id_for_expenses()
    if normalized not in ('Diesel', 'Super'):
        return jsonify({'current_pump': [], 'other_pumps': []})
    if normalized == 'Super':
        fuel_filter = FuelExpense.fuel_type.in_(('Super', 'Petrol'))
    else:
        fuel_filter = FuelExpense.fuel_type == normalized
    current_pump = []
    if fuel_pump_id:
        q = FuelExpense.query.filter(
            FuelExpense.workspace_pump_id == fuel_pump_id,
            fuel_filter,
            FuelExpense.fuel_price.isnot(None)
        )
        if employee_id:
            q = q.filter(FuelExpense.employee_id == employee_id)
        rows = q.order_by(FuelExpense.fueling_date.desc(), FuelExpense.id.desc()).limit(2).all()
        pump = db.session.get(WorkspaceParty, fuel_pump_id)
        pump_name = pump.name if pump else ''
        for r in rows:
            current_pump.append({
                'fuel_price': float(r.fuel_price),
                'date': r.fueling_date.strftime('%d-%m-%Y') if r.fueling_date else '',
                'pump_name': pump_name,
            })
    other_pumps = []
    q_other = db.session.query(FuelExpense.workspace_pump_id).filter(
        fuel_filter,
        FuelExpense.fuel_price.isnot(None),
        FuelExpense.workspace_pump_id.isnot(None),
    )
    if employee_id:
        q_other = q_other.filter(FuelExpense.employee_id == employee_id)
    if fuel_pump_id:
        q_other = q_other.filter(FuelExpense.workspace_pump_id != fuel_pump_id)
    other_pump_ids = [x[0] for x in q_other.distinct().limit(2).all() if x[0]]
    for pid in other_pump_ids:
        q = FuelExpense.query.filter(
            FuelExpense.workspace_pump_id == pid,
            fuel_filter,
            FuelExpense.fuel_price.isnot(None)
        )
        if employee_id:
            q = q.filter(FuelExpense.employee_id == employee_id)
        last_row = q.order_by(FuelExpense.fueling_date.desc(), FuelExpense.id.desc()).first()
        if last_row:
            p = db.session.get(WorkspaceParty, pid)
            other_pumps.append({
                'pump_name': p.name if p else '',
                'fuel_price': float(last_row.fuel_price),
                'date': last_row.fueling_date.strftime('%d-%m-%Y') if last_row.fueling_date else '',
            })
    return jsonify({'current_pump': current_pump, 'other_pumps': other_pumps})


@app.route('/api/fuel-expense/price-history')
def api_fuel_expense_price_history():
    """Return price insights for fuel form side panel."""
    fuel_type = request.args.get('fuel_type', '').strip()
    normalized = 'Super' if fuel_type == 'Petrol' else fuel_type
    fuel_pump_id = request.args.get('fuel_pump_id', type=int)
    fueling_date = parse_date(request.args.get('fueling_date', ''))
    employee_id = _workspace_employee_id_for_expenses()
    any_price_q = FuelExpense.query.filter(
        FuelExpense.fuel_price.isnot(None),
    )
    if employee_id:
        any_price_q = any_price_q.filter(FuelExpense.employee_id == employee_id)

    def _fmt_row(r):
        pump_name = ''
        if r.workspace_pump:
            pump_name = r.workspace_pump.name or ''
        elif r.fuel_pump:
            pump_name = r.fuel_pump.name or ''
        return {
            'date': r.fueling_date.strftime('%d-%m-%Y') if r.fueling_date else '',
            'pump_name': pump_name,
            'vehicle_no': r.vehicle.vehicle_no if r.vehicle else '',
            'fuel_price': float(r.fuel_price),
        }

    if normalized not in ('Diesel', 'Super'):
        return jsonify({'pump_or_date': [], 'selected_pump': [], 'all_pumps': [], 'date_snapshot': []})

    if normalized == 'Super':
        fuel_filter = FuelExpense.fuel_type.in_(('Super', 'Petrol'))
    else:
        fuel_filter = FuelExpense.fuel_type == normalized

    base_q = any_price_q.filter(fuel_filter)
    pump_or_date_rows = []
    # Strict rule for this card:
    # show rows only when BOTH selected pump and selected date are provided and matched.
    # Fuel type filter is mandatory for this section as well.
    if fuel_pump_id and fueling_date:
        strict_rows = base_q.filter(
            or_(FuelExpense.workspace_pump_id == fuel_pump_id, FuelExpense.fuel_pump_id == fuel_pump_id),
            FuelExpense.fueling_date == fueling_date,
        ).order_by(
            FuelExpense.id.desc(),
        ).limit(3).all()
        pump_or_date_rows = [_fmt_row(r) for r in strict_rows]

    selected_pump_rows = []
    if fuel_pump_id:
        selected_q = base_q.filter(FuelExpense.workspace_pump_id == fuel_pump_id).order_by(
            FuelExpense.fueling_date.desc(),
            FuelExpense.id.desc(),
        ).limit(3).all()
        selected_pump_rows = [_fmt_row(r) for r in selected_q]

    all_rows = base_q.order_by(FuelExpense.fueling_date.desc(), FuelExpense.id.desc()).limit(3).all()
    date_snapshot_rows = []
    if fueling_date:
        same_date_rows = base_q.filter(
            FuelExpense.fueling_date == fueling_date
        ).order_by(FuelExpense.id.desc()).all()
        seen_pumps = set()
        for r in same_date_rows:
            pump_key = ('workspace', int(r.workspace_pump_id or 0), int(r.fuel_pump_id or 0))
            if pump_key in seen_pumps:
                continue
            seen_pumps.add(pump_key)
            date_snapshot_rows.append(_fmt_row(r))
            if len(date_snapshot_rows) >= 5:
                break
    return jsonify({
        'pump_or_date': pump_or_date_rows,
        'selected_pump': selected_pump_rows,
        'all_pumps': [_fmt_row(r) for r in all_rows],
        'date_snapshot': date_snapshot_rows,
    })


@app.route('/api/fuel-expense/check-duplicate')
def api_fuel_expense_check_duplicate():
    """Warn when an identical fuel entry already exists."""
    vehicle_id = request.args.get('vehicle_id', type=int)
    fuel_pump_id = request.args.get('fuel_pump_id', type=int)
    fueling_date = parse_date(request.args.get('fueling_date', ''))
    current_reading = request.args.get('current_reading', type=float)
    amount = request.args.get('amount', type=float)
    exclude_id = request.args.get('exclude_id', type=int)
    if not all([vehicle_id, fuel_pump_id, fueling_date, current_reading is not None, amount is not None]):
        return jsonify({'duplicate': False})
    workspace_employee_id = _workspace_employee_id_for_expenses()
    q = FuelExpense.query.filter(
        FuelExpense.vehicle_id == vehicle_id,
        FuelExpense.workspace_pump_id == fuel_pump_id,
        FuelExpense.fueling_date == fueling_date,
        FuelExpense.current_reading == current_reading,
        FuelExpense.amount == amount,
    )
    if workspace_employee_id:
        q = q.filter(FuelExpense.employee_id == workspace_employee_id)
    if exclude_id:
        q = q.filter(FuelExpense.id != exclude_id)
    existing = q.order_by(FuelExpense.id.desc()).first()
    if not existing:
        return jsonify({'duplicate': False})
    return jsonify({
        'duplicate': True,
        'summary': ' | '.join(filter(None, [
            existing.district.name if existing.district else '',
            existing.vehicle.vehicle_no if existing.vehicle else '',
            existing.fueling_date.strftime('%d-%m-%Y') if existing.fueling_date else '',
            'Rs {:,.0f}'.format(float(existing.amount)) if existing.amount is not None else '',
        ])),
        'id': existing.id,
        'vehicle_no': existing.vehicle.vehicle_no if existing.vehicle else '',
        'pump_name': existing.workspace_pump.name if existing.workspace_pump else '',
        'fueling_date': existing.fueling_date.strftime('%d-%m-%Y') if existing.fueling_date else '',
        'current_reading': float(existing.current_reading) if existing.current_reading is not None else None,
        'amount': float(existing.amount) if existing.amount is not None else None,
    })


@app.route('/api/fuel-expense/month-mpg')
def api_fuel_expense_month_mpg():
    vehicle_id = request.args.get('vehicle_id', type=int)
    fueling_date = parse_date(request.args.get('fueling_date', ''))
    exclude_id = request.args.get('exclude_id', type=int)
    if not vehicle_id or not fueling_date:
        return jsonify({'ok': False})
    workspace_employee_id = _workspace_employee_id_for_expenses()
    payload = _fuel_expense_month_mpg(
        vehicle_id, fueling_date, workspace_employee_id, exclude_id=exclude_id,
    )
    if not payload:
        return jsonify({'ok': False})
    return jsonify({'ok': True, **payload})


@app.route('/api/fuel-market-scan-trend')
def api_fuel_market_scan_trend():
    """Last 7 days of cached PSO scan rates."""
    scan_data = _read_fuel_market_scan()
    rates = scan_data.get('rates') or {}
    trend = []
    for date_key in sorted(rates.keys(), reverse=True)[:7]:
        entry = rates.get(date_key) or {}
        trend.append({
            'date': date_key,
            'scanned_at': entry.get('scanned_at', ''),
            'ok': bool(entry.get('ok')),
            'petrol': entry.get('petrol'),
            'diesel': entry.get('diesel'),
            'error': entry.get('error', ''),
        })
    trend.reverse()
    return jsonify({
        'source': 'PSO',
        'scanned_at': scan_data.get('scanned_at', ''),
        'trend': trend,
    })


@app.route('/api/fuel-expense/km-gap-limit')
def api_fuel_expense_km_gap_limit():
    from fuel_expense_settings import resolve_fuel_km_gap_max
    district_id = request.args.get('district_id', type=int)
    project_id = request.args.get('project_id', type=int)
    vehicle_id = request.args.get('vehicle_id', type=int)
    vehicle_family = (request.args.get('vehicle_family') or '').strip()
    if vehicle_id and not vehicle_family:
        vehicle = db.session.get(Vehicle, vehicle_id)
        if vehicle:
            vehicle_family = vehicle.vehicle_family or ''
            if not district_id:
                district_id = vehicle.district_id
            if not project_id:
                project_id = vehicle.project_id
    max_km = resolve_fuel_km_gap_max(district_id, project_id, vehicle_family)
    return jsonify({'ok': True, 'max_km': max_km})


@app.route('/expenses/fuel', methods=['GET', 'POST'])
def fuel_expense_list():
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return _guard
    workspace_employee_id = _workspace_employee_id_for_expenses()
    from auth_utils import get_user_context
    
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)
    
    form = FuelExpenseFilterForm()
    
    # Filter district choices by user scope
    district_q = District.query
    if not is_master_or_admin and allowed_districts:
        district_q = district_q.filter(District.id.in_(list(allowed_districts)))
    form.district_id.choices = [(0, '-- Select District --')] + [(d.id, d.name) for d in district_q.order_by(District.name).all()]
    
    form.project_id.choices = [(0, '-- Select Project --')]
    form.vehicle_id.choices = [(0, '-- All Vehicles --')]
    today = pk_date()
    from_date = request.args.get('from_date')
    to_date = request.args.get('to_date')
    district_id = request.args.get('district_id', type=int) or 0
    project_id = request.args.get('project_id', type=int) or 0
    vehicle_id = request.args.get('vehicle_id', type=int) or 0
    search_q = (request.args.get('q') or '').strip()
    if request.method == 'POST':
        from_date = request.form.get('from_date')
        to_date = request.form.get('to_date')
        district_id = request.form.get('district_id', type=int) or 0
        project_id = request.form.get('project_id', type=int) or 0
        vehicle_id = request.form.get('vehicle_id', type=int) or 0
        search_q = (request.form.get('q') or '').strip()
        return redirect(url_for('fuel_expense_list', from_date=from_date or '', to_date=to_date or '', district_id=district_id, project_id=project_id, vehicle_id=vehicle_id, q=search_q))
    from_d = parse_date(from_date) if from_date else today
    to_d = parse_date(to_date) if to_date else today
    if from_d and to_d and from_d > to_d:
        from_d, to_d = to_d, from_d
    form.from_date.data = from_d
    form.to_date.data = to_d
    form.district_id.data = district_id
    form.project_id.data = project_id
    form.vehicle_id.data = vehicle_id
    if district_id:
        projects = Project.query.join(project_district).filter(project_district.c.district_id == district_id).order_by(Project.name).all()
        form.project_id.choices = [(0, '-- Select Project --')] + [(p.id, p.name) for p in projects]
    if project_id:
        veh_q = Vehicle.query.filter(Vehicle.project_id == project_id)
        if district_id:
            veh_q = veh_q.filter(Vehicle.district_id == district_id)
        vehicles = veh_q.order_by(*vehicle_order_by()).all()
        form.vehicle_id.choices = [(0, '-- All Vehicles --')] + [(v.id, v.vehicle_no) for v in vehicles]
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int) or 50
    if per_page in (25, 50, 100, 200):
        pass
    elif per_page >= 99999:
        per_page = 500  # F-02: cap to prevent OOM
    else:
        per_page = 50

    query = FuelExpense.query.filter(
        FuelExpense.fueling_date >= from_d,
        FuelExpense.fueling_date <= to_d
    )
    if workspace_employee_id:
        query = query.filter(
            db.or_(
                FuelExpense.employee_id == workspace_employee_id,
                FuelExpense.employee_id.is_(None),
            )
        )
    
    # Apply user data scope
    if not is_master_or_admin:
        if allowed_projects:
            query = query.filter(FuelExpense.project_id.in_(list(allowed_projects)))
        if allowed_districts:
            query = query.filter(FuelExpense.district_id.in_(list(allowed_districts)))
        if allowed_vehicles:
            query = query.filter(FuelExpense.vehicle_id.in_(list(allowed_vehicles)))
    
    if district_id:
        query = query.filter(FuelExpense.district_id == district_id)
    if project_id:
        query = query.filter(FuelExpense.project_id == project_id)
    if vehicle_id:
        query = query.filter(FuelExpense.vehicle_id == vehicle_id)
    if search_q:
        search_filter = _fuel_expense_list_search_filter(search_q, workspace_employee_id)
        if search_filter is not None:
            query = query.filter(search_filter)
    query = query.order_by(
        FuelExpense.fueling_date.asc(),
        db.case((FuelExpense.current_reading.is_(None), 1), else_=0).asc(),
        FuelExpense.current_reading.asc(),
        FuelExpense.id.asc(),
    )

    # Aggregate totals from all matching rows (before pagination)
    all_rows = query.all()
    totals = {}
    if all_rows:
        total_km = sum(float(r.km or 0) for r in all_rows)
        total_liters = sum(float(r.liters or 0) for r in all_rows)
        total_amount = sum(float(r.amount or 0) for r in all_rows)
        first_prev = all_rows[-1].previous_reading
        last_curr = all_rows[0].current_reading
        avg_mpg = round(total_km / total_liters, 2) if total_liters else None
        avg_fuel_price = round(total_amount / total_liters, 2) if total_liters else None
        totals = {'total_km': total_km, 'total_liters': total_liters, 'total_amount': total_amount,
                  'first_previous_reading': float(first_prev) if first_prev else None,
                  'last_current_reading': float(last_curr) if last_curr else None,
                  'avg_mpg': avg_mpg,
                  'avg_fuel_price': avg_fuel_price}

    from list_visibility import expense_or_work_order_needs_upload_media_columns
    show_upload_media_columns = (
        any(expense_or_work_order_needs_upload_media_columns(r) for r in all_rows) if all_rows else False
    )

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    rows = pagination.items
    expense_by_labels = {}
    if workspace_employee_id and rows:
        expense_by_labels = _workspace_expense_by_labels_for_references(
            workspace_employee_id, 'FuelExpense', [r.id for r in rows]
        )
    cleanup_status = _latest_expense_cleanup_status('fuel', workspace_employee_id)
    return render_template('fuel_expense_list.html', form=form, rows=rows,
                           from_date=from_d, to_date=to_d, totals=totals,
                           pagination=pagination, page=page, per_page=per_page,
                           district_id=district_id, project_id=project_id, vehicle_id=vehicle_id,
                           q=search_q,
                           expense_by_labels=expense_by_labels,
                           cleanup_status=cleanup_status,
                           show_upload_media_columns=show_upload_media_columns,
                           location_cascade=_fuel_expense_location_cascade_dict())


@app.route('/expenses/fuel/backfill-task-readings', methods=['POST'])
def fuel_expense_backfill_task_readings():
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return _guard
    workspace_employee_id = _workspace_employee_id_for_expenses()
    from auth_utils import get_user_context

    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)

    from_date_raw = (request.form.get('from_date') or '').strip()
    to_date_raw = (request.form.get('to_date') or '').strip()
    district_id = request.form.get('district_id', type=int) or 0
    project_id = request.form.get('project_id', type=int) or 0
    vehicle_id = request.form.get('vehicle_id', type=int) or 0

    today = pk_date()
    from_d = parse_date(from_date_raw) if from_date_raw else today
    to_d = parse_date(to_date_raw) if to_date_raw else today
    if from_d and to_d and from_d > to_d:
        from_d, to_d = to_d, from_d

    q = FuelExpense.query.filter(
        FuelExpense.fueling_date >= from_d,
        FuelExpense.fueling_date <= to_d,
        FuelExpense.km_out_task.is_(None),
        FuelExpense.km_in_task.is_(None),
    )
    if workspace_employee_id:
        q = q.filter(
            db.or_(
                FuelExpense.employee_id == workspace_employee_id,
                FuelExpense.employee_id.is_(None),
            )
        )
    if not is_master_or_admin:
        if allowed_projects:
            q = q.filter(FuelExpense.project_id.in_(list(allowed_projects)))
        if allowed_districts:
            q = q.filter(FuelExpense.district_id.in_(list(allowed_districts)))
        if allowed_vehicles:
            q = q.filter(FuelExpense.vehicle_id.in_(list(allowed_vehicles)))
    if district_id:
        q = q.filter(FuelExpense.district_id == district_id)
    if project_id:
        q = q.filter(FuelExpense.project_id == project_id)
    if vehicle_id:
        q = q.filter(FuelExpense.vehicle_id == vehicle_id)

    rows = q.order_by(FuelExpense.fueling_date.asc(), FuelExpense.id.asc()).all()
    if not rows:
        flash('No fuel expense records found with missing KM Out/KM In in selected filters.', 'info')
        return redirect(url_for(
            'fuel_expense_list',
            from_date=from_d.strftime('%d-%m-%Y') if from_d else '',
            to_date=to_d.strftime('%d-%m-%Y') if to_d else '',
            district_id=district_id,
            project_id=project_id,
            vehicle_id=vehicle_id,
        ))

    updated = 0
    skipped_no_task = 0
    skipped_no_curr = 0
    for rec in rows:
        km_out_task, km_in_task = _fuel_expense_task_readings(rec.vehicle_id, rec.fueling_date)
        if km_out_task is None or km_in_task is None:
            skipped_no_task += 1
            continue
        rec.km_out_task = km_out_task
        rec.km_in_task = km_in_task
        if rec.current_reading is None:
            rec.meter_reading_matched = 'No'
            skipped_no_curr += 1
            updated += 1
            continue
        try:
            curr = float(rec.current_reading)
            lo = min(float(km_out_task), float(km_in_task))
            hi = max(float(km_out_task), float(km_in_task))
            rec.meter_reading_matched = 'Yes' if lo <= curr <= hi else 'No'
        except Exception:
            rec.meter_reading_matched = 'No'
        updated += 1

    if updated > 0:
        db.session.commit()
    else:
        db.session.rollback()

    flash(
        f'Backfill complete. Updated: {updated}, skipped (task missing): {skipped_no_task}, '
        f'skipped (current reading missing): {skipped_no_curr}.',
        'success' if updated > 0 else 'warning'
    )
    return redirect(url_for(
        'fuel_expense_list',
        from_date=from_d.strftime('%d-%m-%Y') if from_d else '',
        to_date=to_d.strftime('%d-%m-%Y') if to_d else '',
        district_id=district_id,
        project_id=project_id,
        vehicle_id=vehicle_id,
    ))


def _workspace_expense_by_choices(employee_id):
    ensure_workspace_base_accounts(employee_id)
    rows = WorkspaceAccount.query.filter_by(employee_id=employee_id, is_active=True).order_by(WorkspaceAccount.code.asc()).all()
    driver_ids = sorted({
        int(a.entity_id) for a in rows
        if (a.entity_type or '').strip().lower() == 'driver' and a.entity_id
    })
    drivers_by_id = {}
    if driver_ids:
        for drv in Driver.query.filter(Driver.id.in_(driver_ids)).all():
            drivers_by_id[int(drv.id)] = drv
    vehicle_ids = sorted({
        int(getattr(drv, 'vehicle_id', 0) or 0)
        for drv in drivers_by_id.values()
        if getattr(drv, 'vehicle_id', None)
    })
    vehicles_by_id = {}
    if vehicle_ids:
        for veh in Vehicle.query.filter(Vehicle.id.in_(vehicle_ids)).all():
            vehicles_by_id[int(veh.id)] = veh

    choices = [('', '-- Default (Auto from Workspace COA) --')]

    def _balance_side(account_type, bal):
        if account_type in ('Asset', 'Expense'):
            return 'Dr' if bal >= 0 else 'Cr'
        return 'Cr' if bal >= 0 else 'Dr'

    for a in rows:
        # Show only likely payment/counterparty heads for cleaner dropdown.
        if a.account_type == 'Expense' or a.code in ('1000', '5000', '5100'):
            continue
        label = f"{a.code} - {a.name} ({a.account_type})"
        if (a.entity_type or '').strip().lower() == 'driver' and a.entity_id:
            drv = drivers_by_id.get(int(a.entity_id))
            veh = vehicles_by_id.get(int(drv.vehicle_id)) if drv and getattr(drv, 'vehicle_id', None) else None
            vehicle_no = (veh.vehicle_no if veh and getattr(veh, 'vehicle_no', None) else None) or ''
            if vehicle_no:
                label = f"{label} | Vehicle: {vehicle_no}"
        bal = Decimal(str(a.current_balance or 0))
        side = _balance_side(a.account_type, bal)
        sign = '+' if bal > 0 else ('-' if bal < 0 else '')
        label = f"{label} | Bal: {sign}{abs(bal):,.2f} {side}"
        choices.append((f'acct-{a.id}', label))
    return choices


def _workspace_default_cash_expense_by(employee_id):
    if not employee_id:
        return ''
    ensure_workspace_base_accounts(employee_id)
    cash_account = WorkspaceAccount.query.filter_by(
        employee_id=employee_id,
        code='1100',
        is_active=True,
    ).first()
    return f'acct-{cash_account.id}' if cash_account else ''


def _workspace_default_hbl_expense_by(employee_id):
    if not employee_id:
        return ''
    ensure_workspace_base_accounts(employee_id)
    hbl_account = WorkspaceAccount.query.filter_by(
        employee_id=employee_id,
        code='1110',
        is_active=True,
    ).first()
    return f'acct-{hbl_account.id}' if hbl_account else ''


def _workspace_account_id_from_expense_by(expense_by_val, employee_id):
    if not expense_by_val:
        return None
    parts = str(expense_by_val).split('-', 1)
    if len(parts) != 2 or parts[0] != 'acct' or not parts[1].isdigit():
        return None
    acct_id = int(parts[1])
    acct = WorkspaceAccount.query.filter_by(id=acct_id, employee_id=employee_id, is_active=True).first()
    return acct.id if acct else None


def _workspace_journal_expense_by_account_id(journal_entry, lines_by_je, exclude_account_ids, accounts_by_id):
    """Credit-side workspace account used to pay/settle an expense (Expense By)."""
    lines = lines_by_je.get(journal_entry.id, [])
    credit_lines = sorted(
        [
            ln for ln in lines
            if Decimal(str(ln.credit or 0)) > 0 and ln.account_id not in exclude_account_ids
        ],
        key=lambda x: Decimal(str(x.credit or 0)),
        reverse=True,
    )
    for ln in credit_lines:
        acct = accounts_by_id.get(ln.account_id)
        if acct and acct.code not in ('5100', '5000'):
            return acct.id
    return None


def _workspace_expense_by_account_id_for_reference(employee_id, reference_type, reference_id):
    if not employee_id or not reference_type or not reference_id:
        return None
    rows = WorkspaceJournalEntry.query.filter_by(
        employee_id=employee_id,
        reference_type=reference_type,
        reference_id=reference_id,
    ).order_by(WorkspaceJournalEntry.id.desc()).all()
    if not rows:
        return None
    lines_by_je = {}
    line_rows = WorkspaceJournalEntryLine.query.filter(
        WorkspaceJournalEntryLine.journal_entry_id.in_([je.id for je in rows])
    ).all()
    for ln in line_rows:
        lines_by_je.setdefault(ln.journal_entry_id, []).append(ln)
    ensure_workspace_base_accounts(employee_id)
    expense_head = WorkspaceAccount.query.filter_by(employee_id=employee_id, code='5100').first()
    exclude_ids = {expense_head.id} if expense_head else set()
    acct_ids = {ln.account_id for ln in line_rows}
    accounts_by_id = {}
    if acct_ids:
        for acct in WorkspaceAccount.query.filter(
            WorkspaceAccount.id.in_(list(acct_ids)),
            WorkspaceAccount.employee_id == employee_id,
            WorkspaceAccount.is_active == True,
        ).all():
            accounts_by_id[acct.id] = acct
    transfer_rows = [je for je in rows if (je.entry_type or '').strip().lower() == 'transfer']
    expense_rows = [je for je in rows if (je.entry_type or '').strip().lower() == 'expense']
    for group in (transfer_rows, expense_rows):
        for je in group:
            acct_id = _workspace_journal_expense_by_account_id(je, lines_by_je, exclude_ids, accounts_by_id)
            if acct_id:
                return acct_id
    return None


def _workspace_expense_by_label_for_reference(employee_id, reference_type, reference_id):
    acct_id = _workspace_expense_by_account_id_for_reference(employee_id, reference_type, reference_id)
    if not acct_id:
        return ''
    acct = WorkspaceAccount.query.filter_by(id=acct_id, employee_id=employee_id, is_active=True).first()
    if not acct:
        return ''
    return f"{acct.code} - {acct.name}"


def _workspace_expense_by_labels_for_references(employee_id, reference_type, reference_ids):
    ids = sorted({int(x) for x in reference_ids if x})
    if not employee_id or not reference_type or not ids:
        return {}
    entries = WorkspaceJournalEntry.query.filter(
        WorkspaceJournalEntry.employee_id == employee_id,
        WorkspaceJournalEntry.reference_type == reference_type,
        WorkspaceJournalEntry.reference_id.in_(ids),
    ).order_by(
        WorkspaceJournalEntry.reference_id.asc(),
        WorkspaceJournalEntry.id.desc(),
    ).all()
    if not entries:
        return {ref_id: '' for ref_id in ids}
    lines_by_je = {}
    line_rows = WorkspaceJournalEntryLine.query.filter(
        WorkspaceJournalEntryLine.journal_entry_id.in_([je.id for je in entries])
    ).all()
    for ln in line_rows:
        lines_by_je.setdefault(ln.journal_entry_id, []).append(ln)
    ensure_workspace_base_accounts(employee_id)
    expense_head = WorkspaceAccount.query.filter_by(employee_id=employee_id, code='5100').first()
    exclude_ids = {expense_head.id} if expense_head else set()
    acct_ids = {ln.account_id for ln in line_rows}
    accounts_by_id = {}
    if acct_ids:
        for acct in WorkspaceAccount.query.filter(
            WorkspaceAccount.id.in_(list(acct_ids)),
            WorkspaceAccount.employee_id == employee_id,
            WorkspaceAccount.is_active == True,
        ).all():
            accounts_by_id[acct.id] = acct
    by_ref = {}
    for je in entries:
        by_ref.setdefault(je.reference_id, []).append(je)
    labels = {}
    for ref_id in ids:
        acct_id = None
        je_list = by_ref.get(ref_id, [])
        transfer_rows = [je for je in je_list if (je.entry_type or '').strip().lower() == 'transfer']
        expense_rows = [je for je in je_list if (je.entry_type or '').strip().lower() == 'expense']
        for group in (transfer_rows, expense_rows):
            for je in group:
                acct_id = _workspace_journal_expense_by_account_id(je, lines_by_je, exclude_ids, accounts_by_id)
                if acct_id:
                    break
            if acct_id:
                break
        acct = accounts_by_id.get(acct_id) if acct_id else None
        labels[ref_id] = f"{acct.code} - {acct.name}" if acct else ''
    return labels


def _workspace_expense_by_for_reference(employee_id, reference_type, reference_id):
    acct_id = _workspace_expense_by_account_id_for_reference(employee_id, reference_type, reference_id)
    return f'acct-{acct_id}' if acct_id else ''


def _fuel_expense_ids_matching_expense_by_search(employee_id, search_token):
    """Fuel expense IDs whose Workspace COA payer account matches a single search token."""
    if not employee_id or not search_token:
        return None
    like_q = f"%{search_token.strip()}%"
    driver_join = db.and_(
        func.lower(WorkspaceAccount.entity_type) == 'driver',
        WorkspaceAccount.entity_id == Driver.id,
    )
    return (
        db.session.query(WorkspaceJournalEntry.reference_id)
        .join(
            WorkspaceJournalEntryLine,
            WorkspaceJournalEntryLine.journal_entry_id == WorkspaceJournalEntry.id,
        )
        .join(
            WorkspaceAccount,
            WorkspaceAccount.id == WorkspaceJournalEntryLine.account_id,
        )
        .outerjoin(Driver, driver_join)
        .filter(
            WorkspaceJournalEntry.employee_id == employee_id,
            WorkspaceJournalEntry.reference_type == 'FuelExpense',
            WorkspaceJournalEntry.reference_id.isnot(None),
            WorkspaceJournalEntry.entry_type.in_(['Expense', 'Transfer']),
            WorkspaceJournalEntryLine.credit > 0,
            WorkspaceAccount.employee_id == employee_id,
            ~WorkspaceAccount.code.in_(['5100', '5000']),
            or_(
                WorkspaceAccount.name.ilike(like_q),
                WorkspaceAccount.code.ilike(like_q),
                (WorkspaceAccount.code + ' - ' + WorkspaceAccount.name).ilike(like_q),
                Driver.name.ilike(like_q),
            ),
        )
        .distinct()
    )


def _fuel_expense_list_search_filter(search_q, workspace_employee_id):
    """Multi-word AND search: each token must match at least one searchable field."""
    tokens = [t for t in (search_q or '').split() if t]
    if not tokens:
        return None
    search_columns = [
        FuelExpense.slip_no,
        FuelExpense.payment_type,
        FuelExpense.fuel_type,
        cast(FuelExpense.id, SAString),
        cast(FuelExpense.current_reading, SAString),
        cast(FuelExpense.previous_reading, SAString),
        cast(FuelExpense.amount, SAString),
        cast(FuelExpense.liters, SAString),
        cast(FuelExpense.km, SAString),
        cast(FuelExpense.fueling_date, SAString),
        cast(FuelExpense.card_swipe_date, SAString),
    ]
    token_clauses = []
    for tok in tokens:
        like_tok = f'%{tok}%'
        token_or_parts = [col.ilike(like_tok) for col in search_columns]
        token_or_parts.extend([
            FuelExpense.vehicle_id.in_(db.session.query(Vehicle.id).filter(Vehicle.vehicle_no.ilike(like_tok))),
            FuelExpense.project_id.in_(db.session.query(Project.id).filter(Project.name.ilike(like_tok))),
            FuelExpense.district_id.in_(db.session.query(District.id).filter(District.name.ilike(like_tok))),
            FuelExpense.workspace_pump_id.in_(db.session.query(WorkspaceParty.id).filter(WorkspaceParty.name.ilike(like_tok))),
            FuelExpense.fuel_pump_id.in_(db.session.query(Party.id).filter(Party.name.ilike(like_tok))),
        ])
        expense_by_ids = _fuel_expense_ids_matching_expense_by_search(workspace_employee_id, tok)
        if expense_by_ids is not None:
            token_or_parts.append(FuelExpense.id.in_(expense_by_ids))
        token_clauses.append(or_(*token_or_parts))
    return and_(*token_clauses)


def _require_workspace_employee_for_expense_management():
    """Expense Management is now part of Employee Workspace."""
    if not session.get('workspace_employee_id'):
        flash('Employee Workspace select karna zaroori hai.', 'warning')
        return redirect(url_for('workspace_dashboard'))
    return None


def _workspace_employee_id_for_expenses():
    return session.get('workspace_employee_id')


def _safe_internal_path(return_to, default_path):
    """App-relative path only: prevents open redirects from return_to query param."""
    from urllib.parse import unquote
    if not return_to or not isinstance(return_to, str):
        return default_path
    raw = unquote(return_to.strip())
    if not raw or not raw.startswith('/') or raw.startswith('//'):
        return default_path
    if any(c in raw for c in '\n\r\x00'):
        return default_path
    if len(raw) > 2000:
        return default_path
    return raw


def _workspace_employee_default_district_id(employee_id):
    if not employee_id:
        return None
    emp = db.session.get(Employee, employee_id)
    if not emp:
        return None
    try:
        first_district = emp.districts.order_by(District.name.asc()).first()
    except Exception:
        first_district = None
    return first_district.id if first_district else None


def _workspace_employee_default_project_id(employee_id, preferred_district_id=None):
    if not employee_id:
        return None
    emp = db.session.get(Employee, employee_id)
    if not emp:
        return None
    preferred_district_id = int(preferred_district_id) if preferred_district_id else None
    try:
        emp_projects = list(emp.projects)
    except Exception:
        emp_projects = []
    if not emp_projects:
        return None
    emp_projects.sort(key=lambda p: (p.name or '').lower())
    if preferred_district_id:
        for p in emp_projects:
            try:
                linked = p.districts.filter(District.id == preferred_district_id).first() if hasattr(p.districts, 'filter') else None
            except Exception:
                linked = None
            if linked:
                return p.id
    return emp_projects[0].id


def _fallback_vehicle_previous_reading(employee_id, vehicle_id, mode):
    if not vehicle_id:
        return None
    setup = None
    if employee_id:
        setup = WorkspaceVehicleReadingSetup.query.filter_by(
            employee_id=employee_id,
            vehicle_id=vehicle_id,
        ).first()
    if not setup:
        setup = WorkspaceVehicleReadingSetup.query.filter_by(
            vehicle_id=vehicle_id,
        ).order_by(WorkspaceVehicleReadingSetup.id.desc()).first()
    if not setup:
        return None
    if mode == 'fuel':
        raw = setup.fuel_previous_reading
    elif mode == 'oil':
        raw = setup.oil_previous_reading
    elif mode == 'maintenance':
        _ensure_vehicle_maintenance_baseline_schema()
        baseline_q = WorkspaceVehicleMaintenanceBaseline.query.filter(
            WorkspaceVehicleMaintenanceBaseline.vehicle_id == vehicle_id
        )
        if employee_id:
            baseline_q = baseline_q.filter(WorkspaceVehicleMaintenanceBaseline.employee_id == employee_id)
        baseline = baseline_q.order_by(
            db.case((WorkspaceVehicleMaintenanceBaseline.last_done_date.is_(None), 1), else_=0).asc(),
            WorkspaceVehicleMaintenanceBaseline.last_done_date.desc(),
            db.case((WorkspaceVehicleMaintenanceBaseline.last_done_reading.is_(None), 1), else_=0).asc(),
            WorkspaceVehicleMaintenanceBaseline.last_done_reading.desc(),
            WorkspaceVehicleMaintenanceBaseline.id.desc(),
        ).first()
        if baseline and baseline.last_done_reading is not None:
            return float(baseline.last_done_reading)
        raw = None
    else:
        raw = None
    return float(raw) if raw is not None else None


def _workspace_reverse_expense_journals(reference_type, reference_id, employee_id):
    if not employee_id:
        return
    rows = WorkspaceJournalEntry.query.filter_by(
        employee_id=employee_id,
        reference_type=reference_type,
        reference_id=reference_id
    ).all()
    for je in rows:
        workspace_reverse_journal_entry(je.id)


_WORKSPACE_REGULAR_EXPENSE_SYNC_AVAILABLE = None


def _workspace_regular_expense_sync_available():
    global _WORKSPACE_REGULAR_EXPENSE_SYNC_AVAILABLE
    if _WORKSPACE_REGULAR_EXPENSE_SYNC_AVAILABLE is not None:
        return _WORKSPACE_REGULAR_EXPENSE_SYNC_AVAILABLE
    try:
        insp = inspect(db.engine)
        if not insp.has_table('workspace_expense'):
            _WORKSPACE_REGULAR_EXPENSE_SYNC_AVAILABLE = False
            return False
        cols = {c.get('name') for c in insp.get_columns('workspace_expense')}
        required = {
            'employee_id', 'expense_number', 'expense_date', 'expense_type',
            'description', 'amount', 'payment_mode', 'category',
            'workspace_party_id', 'journal_entry_id',
        }
        _WORKSPACE_REGULAR_EXPENSE_SYNC_AVAILABLE = required.issubset(cols)
    except Exception:
        _WORKSPACE_REGULAR_EXPENSE_SYNC_AVAILABLE = False
    return _WORKSPACE_REGULAR_EXPENSE_SYNC_AVAILABLE


def _workspace_regular_expense_number(reference_type, reference_id):
    if not reference_type or not reference_id:
        return ''
    key = str(reference_type).strip()
    try:
        rid = int(reference_id)
    except (TypeError, ValueError):
        return ''
    mapping = {
        'FuelExpense': 'FUEL',
        'OilExpense': 'OIL',
        'MaintenanceExpense': 'MAINT',
    }
    prefix = mapping.get(key, key.upper()[:12])
    return f'{prefix}-{rid}'


def _workspace_sync_regular_expense(employee_id, reference_type, reference_id, expense_date, amount,
                                    description, expense_type, payment_mode, category,
                                    workspace_party_id=None, journal_entry_id=None):
    if not _workspace_regular_expense_sync_available():
        return None
    if not employee_id:
        return None
    exp_no = _workspace_regular_expense_number(reference_type, reference_id)
    if not exp_no:
        return None
    amount_val = Decimal(str(amount or 0))
    existing = WorkspaceExpense.query.filter_by(
        employee_id=employee_id,
        expense_number=exp_no,
    ).first()
    if amount_val <= Decimal('0'):
        if existing:
            db.session.delete(existing)
        return None
    if not existing:
        existing = WorkspaceExpense(
            employee_id=employee_id,
            expense_number=exp_no,
            created_by_user_id=session.get('user_id'),
        )
        db.session.add(existing)
    existing.expense_date = expense_date or pk_date()
    existing.expense_type = expense_type or reference_type or 'Expense'
    existing.workspace_party_id = workspace_party_id
    existing.workspace_product_id = None
    existing.to_driver_id = None
    existing.description = description or existing.expense_type
    existing.amount = amount_val
    existing.payment_mode = payment_mode or 'Cash'
    existing.category = category or None
    existing.journal_entry_id = journal_entry_id
    return existing


def _workspace_delete_regular_expense(employee_id, reference_type, reference_id):
    if not _workspace_regular_expense_sync_available():
        return
    if not employee_id:
        return
    exp_no = _workspace_regular_expense_number(reference_type, reference_id)
    if not exp_no:
        return
    row = WorkspaceExpense.query.filter_by(employee_id=employee_id, expense_number=exp_no).first()
    if row:
        db.session.delete(row)


def _workspace_post_expense_journal(employee_id, reference_type, reference_id, expense_date, amount, description, category_code, workspace_party_id=None, credit_account_id=None):
    if not employee_id:
        return None
    amount_val = Decimal(str(amount or 0))
    if amount_val <= Decimal("0"):
        return None

    ensure_workspace_base_accounts(employee_id)
    expense_head = WorkspaceAccount.query.filter_by(employee_id=employee_id, code='5100').first()
    cash_head = WorkspaceAccount.query.filter_by(employee_id=employee_id, code='1100').first()
    if not (expense_head and cash_head):
        return None

    selected_credit_id = credit_account_id
    credit_account_id = cash_head.id
    if selected_credit_id:
        user_credit = WorkspaceAccount.query.filter_by(id=selected_credit_id, employee_id=employee_id, is_active=True).first()
        if user_credit:
            credit_account_id = user_credit.id
    if workspace_party_id:
        try:
            party_acct = ensure_workspace_counterparty_account(employee_id, party_id=workspace_party_id)
            if party_acct:
                # Explicit selected account takes priority; otherwise party account.
                if not credit_account_id or credit_account_id == cash_head.id:
                    credit_account_id = party_acct.id
        except Exception:
            pass

    line_desc = description or 'Expense posted'
    return workspace_create_journal_entry(
        employee_id=employee_id,
        entry_type='Expense',
        entry_date=expense_date or pk_date(),
        description=description or reference_type,
        lines=[
            {'account_id': expense_head.id, 'debit': amount_val, 'credit': 0, 'description': line_desc},
            {'account_id': credit_account_id, 'debit': 0, 'credit': amount_val, 'description': line_desc},
        ],
        reference_type=reference_type,
        reference_id=reference_id,
        created_by_user_id=session.get('user_id'),
        category=category_code,
    )


def _workspace_post_credit_settlement_journal(employee_id, reference_type, reference_id, expense_date, amount,
                                              category_code, workspace_party_id, credit_account_id, description):
    if not employee_id or not workspace_party_id or not credit_account_id:
        return None
    settle_amount = Decimal(str(amount or 0))
    if settle_amount <= 0:
        return None
    try:
        party_acct = ensure_workspace_counterparty_account(employee_id, party_id=workspace_party_id)
    except Exception:
        party_acct = None
    if not party_acct or int(credit_account_id) == int(party_acct.id):
        return None
    settle_desc = description or 'Credit settlement'
    return workspace_create_journal_entry(
        employee_id=employee_id,
        entry_type='Transfer',
        entry_date=expense_date or pk_date(),
        description=settle_desc,
        lines=[
            {
                'account_id': party_acct.id,
                'debit': settle_amount,
                'credit': 0,
                'description': settle_desc,
            },
            {
                'account_id': credit_account_id,
                'debit': 0,
                'credit': settle_amount,
                'description': settle_desc,
            },
        ],
        reference_type=reference_type,
        reference_id=reference_id,
        created_by_user_id=session.get('user_id'),
        category=category_code,
    )


@app.route('/expenses/fuel/add', methods=['GET', 'POST'])
def fuel_expense_add():
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return _guard
    workspace_employee_id = _workspace_employee_id_for_expenses()
    form = FuelExpenseForm()
    form.district_id.choices = [(0, '-- Select District --')] + [(d.id, d.name) for d in District.query.order_by(District.name).all()]
    form.project_id.choices = [(0, '-- Select Project --')]
    form.vehicle_id.choices = [(0, '-- Select Vehicle --')]
    pumps = WorkspaceParty.query.filter_by(employee_id=workspace_employee_id, party_type='Pump').order_by(WorkspaceParty.name).all()
    form.fuel_pump_id.choices = [(0, '-- Select Pump --')] + [(p.id, p.name) for p in pumps]
    form.expense_by.choices = _workspace_expense_by_choices(workspace_employee_id)
    default_district_id = _workspace_employee_default_district_id(workspace_employee_id)
    selected_district_id = request.args.get('district_id', type=int) if request.method == 'GET' else request.form.get('district_id', type=int)
    selected_project_id = request.args.get('project_id', type=int) if request.method == 'GET' else request.form.get('project_id', type=int)
    selected_vehicle_id = request.args.get('vehicle_id', type=int) if request.method == 'GET' else None
    selected_payment_type = request.args.get('payment_type', '') if request.method == 'GET' else ''
    last_id = request.args.get('last_id', type=int) if request.method == 'GET' else None
    add_ctx = _fuel_expense_add_form_ctx(workspace_employee_id, last_id)
    if request.method == 'GET' and not selected_district_id and default_district_id:
        selected_district_id = default_district_id
    if selected_district_id:
        projects = Project.query.join(project_district).filter(project_district.c.district_id == selected_district_id).order_by(Project.name).all()
        form.project_id.choices = [(0, '-- Select Project --')] + [(p.id, p.name) for p in projects]
    if selected_project_id:
        q = Vehicle.query.filter(Vehicle.project_id == selected_project_id)
        if selected_district_id:
            q = q.filter(Vehicle.district_id == selected_district_id)
        vehicles = q.order_by(*vehicle_order_by()).all()
        form.vehicle_id.choices = [(0, '-- Select Vehicle --')] + [(v.id, v.vehicle_no) for v in vehicles]
    if request.method == 'GET':
        form.district_id.data = selected_district_id or 0
        form.project_id.data = selected_project_id or 0
        if selected_vehicle_id:
            form.vehicle_id.data = selected_vehicle_id
            _prev_veh = db.session.get(Vehicle, selected_vehicle_id)
            if _prev_veh and _prev_veh.fuel_type:
                form.fuel_type.data = _prev_veh.fuel_type
        if selected_payment_type:
            form.payment_type.data = selected_payment_type
        if not form.fueling_date.data:
            form.fueling_date.data = pk_date()
    if request.method == 'POST' and form.validate_on_submit():
        vehicle_id = form.vehicle_id.data
        if vehicle_id == 0:
            flash('Please select a vehicle.', 'danger')
            return render_template(
                'fuel_expense_form.html',
                form=form,
                title='Add Fuel Expense',
                **add_ctx,
            )
        vehicle = Vehicle.query.get_or_404(vehicle_id)
        district_id = form.district_id.data or None
        if district_id == 0:
            district_id = None
        project_id = form.project_id.data or None
        if project_id == 0:
            project_id = vehicle.project_id
        fueling_date = form.fueling_date.data
        card_swipe_date = form.card_swipe_date.data
        payment_type = (form.payment_type.data or '').strip()
        allowed_payment_types = ('Cash', 'Credit', 'Tp/Card', 'Shl/Card')
        if payment_type not in allowed_payment_types:
            flash('Please select a valid payment type.', 'danger')
            return render_template(
                'fuel_expense_form.html',
                form=form,
                title='Add Fuel Expense',
                **add_ctx,
            )
        if payment_type in ('Cash', 'Credit'):
            card_swipe_date = None
        slip_no = (form.slip_no.data or '').strip() or None
        fuel_type = (vehicle.fuel_type or 'Petrol').strip() or 'Petrol'
        workspace_pump_id = form.fuel_pump_id.data or None
        if workspace_pump_id == 0:
            workspace_pump_id = None
        if not workspace_pump_id:
            flash('Please select a fuel pump name.', 'danger')
            return render_template(
                'fuel_expense_form.html',
                form=form,
                title='Add Fuel Expense',
                **add_ctx,
            )
        previous_reading = form.previous_reading.data
        current_reading = form.current_reading.data
        if previous_reading is None:
            previous_reading = _fuel_expense_previous_reading(
                vehicle_id=vehicle_id,
                fueling_date=fueling_date,
                workspace_employee_id=workspace_employee_id,
                current_reading=current_reading,
            ) or 0
        prev_f = float(previous_reading)
        curr_f = float(current_reading)
        km = curr_f - prev_f
        amount = form.amount.data
        fuel_price = form.fuel_price.data
        amount_f = float(amount) if amount else 0
        fuel_price_f = float(fuel_price) if fuel_price else 0
        liters = round(amount_f / fuel_price_f, 2) if fuel_price_f else None
        mpg = round(km / float(liters), 2) if liters and km else None
        km_out_task, km_in_task = _fuel_expense_task_readings(vehicle_id, fueling_date)
        if km_out_task is not None and km_in_task is not None:
            lo = min(float(km_out_task), float(km_in_task))
            hi = max(float(km_out_task), float(km_in_task))
            meter_reading_matched = 'Yes' if lo <= curr_f <= hi else 'No'
        else:
            meter_reading_matched = 'No'
        expense_by_val = form.expense_by.data or ''
        if payment_type == 'Cash':
            expense_by_val = expense_by_val or _workspace_default_hbl_expense_by(workspace_employee_id)
        selected_credit_account_id = _workspace_account_id_from_expense_by(expense_by_val, workspace_employee_id)
        reading_text = f"{prev_f:g} to {curr_f:g}"
        fuel_expense_desc = f"Fueling expense / {vehicle.vehicle_no} / Reading {reading_text}"
        rec = FuelExpense(
            district_id=district_id, project_id=project_id, vehicle_id=vehicle_id,
            employee_id=workspace_employee_id,
            fueling_date=fueling_date, card_swipe_date=card_swipe_date,
            payment_type=payment_type, slip_no=slip_no, fuel_type=fuel_type, workspace_pump_id=workspace_pump_id,
            previous_reading=previous_reading, current_reading=current_reading,
            km=km, fuel_price=fuel_price, liters=liters, mpg=mpg, amount=amount,
            km_out_task=km_out_task, km_in_task=km_in_task, meter_reading_matched=meter_reading_matched
        )
        db.session.add(rec)
        db.session.flush()
        _resequence_vehicle_fuel_expenses(vehicle_id, workspace_employee_id)
        fuel_je = _workspace_post_expense_journal(
            employee_id=workspace_employee_id,
            reference_type='FuelExpense',
            reference_id=rec.id,
            expense_date=fueling_date,
            amount=amount_f,
            description=fuel_expense_desc,
            category_code='Fuel',
            workspace_party_id=workspace_pump_id if payment_type == 'Credit' else None,
            credit_account_id=(selected_credit_account_id if payment_type == 'Cash' else None),
        )
        if payment_type == 'Credit' and workspace_pump_id and selected_credit_account_id:
            selected_credit = WorkspaceAccount.query.filter_by(
                id=selected_credit_account_id,
                employee_id=workspace_employee_id,
                is_active=True,
            ).first()
            pump_obj = WorkspaceParty.query.filter_by(employee_id=workspace_employee_id, id=workspace_pump_id).first()
            _workspace_post_credit_settlement_journal(
                employee_id=workspace_employee_id,
                reference_type='FuelExpense',
                reference_id=rec.id,
                expense_date=fueling_date,
                amount=amount_f,
                category_code='Fuel',
                workspace_party_id=workspace_pump_id,
                credit_account_id=selected_credit_account_id,
                description=(
                    f"Cash paid by {(selected_credit.name if selected_credit else f'Account {selected_credit_account_id}')}"
                    f" to {(pump_obj.name if pump_obj else 'Pump')} for Cash fueling"
                ),
            )
        _workspace_sync_regular_expense(
            employee_id=workspace_employee_id,
            reference_type='FuelExpense',
            reference_id=rec.id,
            expense_date=fueling_date,
            amount=amount_f,
            description=fuel_expense_desc,
            expense_type='Fuel Expense',
            payment_mode=payment_type,
            category='Fuel',
            workspace_party_id=(workspace_pump_id if payment_type == 'Credit' else None),
            journal_entry_id=(fuel_je.id if fuel_je else None),
        )

        db.session.commit()
        files = request.files.getlist('attachments')
        has_new_files = bool(files and any(f and getattr(f, 'filename', None) for f in files))
        if has_new_files:
            try:
                manifest, skipped_att = _prepare_fuel_upload_manifest(files, rec.id)
                rec.upload_total = len(manifest)
                rec.upload_done = 0
                rec.upload_failed = 0
                rec.upload_error = None
                rec.upload_finished_at = None
                if manifest:
                    rec.upload_status = 'processing'
                    rec.upload_started_at = pk_now()
                    rec.upload_manifest_json = json.dumps(manifest)
                else:
                    rec.upload_status = 'success'
                    rec.upload_started_at = None
                    rec.upload_manifest_json = None
                    rec.upload_finished_at = pk_now()
                db.session.commit()
                if manifest:
                    _start_fuel_upload_worker(rec.id)
                    flash(f'Upload background me start ho gaya ({len(manifest)} file). Status list me live dekhein.', 'info')
                if skipped_att:
                    flash('Kuch files queue me nahi gayin: ' + '; '.join(skipped_att), 'warning')
            except Exception:
                db.session.rollback()
                app.logger.exception('Fuel async attachment queue save')
                flash('Fuel save ho gaya lekin files queue me add nahi ho sakin.', 'warning')
        flash('Fuel expense saved.', 'success')
        if request.form.get('_save_action') == 'save_list':
            return redirect(url_for('fuel_expense_list'))
        return redirect(url_for('fuel_expense_add',
            district_id=rec.district_id or 0,
            project_id=rec.project_id or 0,
            vehicle_id=rec.vehicle_id,
            payment_type=payment_type,
            last_id=rec.id))
    elif request.method == 'POST' and form.errors:
        flash('Fuel form save nahi hua. Required fields aur selected options check karein.', 'danger')
    return render_template(
        'fuel_expense_form.html',
        form=form,
        rec=None,
        title='Add Fuel Expense',
        **add_ctx,
    )


@app.route('/expenses/fuel/<int:pk>/edit', methods=['GET', 'POST'])
def fuel_expense_edit(pk):
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return _guard
    workspace_employee_id = _workspace_employee_id_for_expenses()
    rec = FuelExpense.query.get_or_404(pk)
    default_back = url_for('fuel_expense_list')
    back_url = _safe_internal_path(request.args.get('return_to') or request.form.get('return_to'), default_back)
    if workspace_employee_id and rec.employee_id and rec.employee_id != workspace_employee_id:
        flash('This expense does not belong to selected workspace employee.', 'danger')
        return redirect(back_url)
    form = FuelExpenseForm(obj=rec)
    form.expense_by.choices = _workspace_expense_by_choices(workspace_employee_id)
    form.district_id.choices = [(0, '-- Select District --')] + [(d.id, d.name) for d in District.query.order_by(District.name).all()]
    if rec.district_id:
        projects = Project.query.join(project_district).filter(project_district.c.district_id == rec.district_id).order_by(Project.name).all()
        form.project_id.choices = [(0, '-- Select Project --')] + [(p.id, p.name) for p in projects]
    else:
        form.project_id.choices = [(0, '-- Select Project --')]
    q = Vehicle.query
    if rec.project_id:
        q = q.filter(Vehicle.project_id == rec.project_id)
    if rec.district_id:
        q = q.filter(Vehicle.district_id == rec.district_id)
    vehicles = q.order_by(*vehicle_order_by()).all()
    form.vehicle_id.choices = [(0, '-- Select Vehicle --')] + [(v.id, v.vehicle_no) for v in vehicles]
    pumps = WorkspaceParty.query.filter_by(employee_id=workspace_employee_id, party_type='Pump').order_by(WorkspaceParty.name).all()
    form.fuel_pump_id.choices = [(0, '-- Select Pump --')] + [(p.id, p.name) for p in pumps]
    if request.method == 'GET':
        form.district_id.data = rec.district_id or 0
        form.project_id.data = rec.project_id or 0
        form.vehicle_id.data = rec.vehicle_id
        form.fueling_date.data = rec.fueling_date
        form.card_swipe_date.data = rec.card_swipe_date
        form.payment_type.data = rec.payment_type or ''
        form.slip_no.data = rec.slip_no or ''
        form.fuel_type.data = (rec.vehicle.fuel_type if rec.vehicle and rec.vehicle.fuel_type else (rec.fuel_type or 'Petrol'))
        form.fuel_pump_id.data = rec.workspace_pump_id or 0
        form.previous_reading.data = rec.previous_reading
        form.current_reading.data = rec.current_reading
        form.amount.data = rec.amount
        form.fuel_price.data = rec.fuel_price
        form.expense_by.data = _workspace_expense_by_for_reference(workspace_employee_id, 'FuelExpense', rec.id)
    if request.method == 'POST' and form.validate_on_submit():
        vehicle_id = form.vehicle_id.data
        if vehicle_id == 0:
            flash('Please select a vehicle.', 'danger')
            return render_template(
                'fuel_expense_form.html',
                form=form,
                title='Edit Fuel Expense',
                rec=rec,
                location_cascade=_fuel_expense_location_cascade_dict(),
            )
        district_id = form.district_id.data or None
        if district_id == 0:
            district_id = None
        project_id = form.project_id.data or None
        if project_id == 0:
            project_id = None
        fueling_date = form.fueling_date.data
        card_swipe_date = form.card_swipe_date.data
        payment_type = (form.payment_type.data or '').strip()
        allowed_payment_types = ('Cash', 'Credit', 'Tp/Card', 'Shl/Card')
        if payment_type not in allowed_payment_types:
            flash('Please select a valid payment type.', 'danger')
            return render_template(
                'fuel_expense_form.html',
                form=form,
                title='Edit Fuel Expense',
                rec=rec,
                location_cascade=_fuel_expense_location_cascade_dict(),
            )
        if payment_type in ('Cash', 'Credit'):
            card_swipe_date = None
        slip_no = (form.slip_no.data or '').strip() or None
        vehicle_obj = Vehicle.query.get_or_404(vehicle_id)
        fuel_type = (vehicle_obj.fuel_type or 'Petrol').strip() or 'Petrol'
        workspace_pump_id = form.fuel_pump_id.data or None
        if workspace_pump_id == 0:
            workspace_pump_id = None
        if not workspace_pump_id:
            flash('Please select a fuel pump name.', 'danger')
            return render_template(
                'fuel_expense_form.html',
                form=form,
                title='Edit Fuel Expense',
                rec=rec,
                location_cascade=_fuel_expense_location_cascade_dict(),
            )
        previous_reading = form.previous_reading.data
        current_reading = form.current_reading.data
        if previous_reading is None:
            previous_reading = _fuel_expense_previous_reading(
                vehicle_id=vehicle_id,
                fueling_date=fueling_date,
                exclude_id=pk,
                workspace_employee_id=workspace_employee_id,
                current_reading=current_reading,
            ) or 0
        prev_f = float(previous_reading)
        curr_f = float(current_reading)
        km = curr_f - prev_f
        amount = form.amount.data
        fuel_price = form.fuel_price.data
        amount_f = float(amount) if amount else 0
        fuel_price_f = float(fuel_price) if fuel_price else 0
        liters = round(amount_f / fuel_price_f, 2) if fuel_price_f else None
        mpg = round(km / float(liters), 2) if liters and km else None
        km_out_task, km_in_task = _fuel_expense_task_readings(vehicle_id, fueling_date)
        if km_out_task is not None and km_in_task is not None:
            lo = min(float(km_out_task), float(km_in_task))
            hi = max(float(km_out_task), float(km_in_task))
            meter_reading_matched = 'Yes' if lo <= curr_f <= hi else 'No'
        else:
            meter_reading_matched = 'No'
        try:
            expense_by_val = form.expense_by.data or ''
            if payment_type == 'Cash':
                expense_by_val = expense_by_val or _workspace_default_hbl_expense_by(workspace_employee_id)
            selected_credit_account_id = _workspace_account_id_from_expense_by(expense_by_val, workspace_employee_id)
            reading_text = f"{prev_f:g} to {curr_f:g}"
            fuel_expense_desc = f"Fueling expense / {vehicle_obj.vehicle_no} / Reading {reading_text}"
            _workspace_reverse_expense_journals('FuelExpense', rec.id, workspace_employee_id)
            rec.district_id = district_id
            rec.project_id = project_id
            rec.vehicle_id = vehicle_id
            rec.employee_id = workspace_employee_id
            rec.fueling_date = fueling_date
            rec.card_swipe_date = card_swipe_date
            rec.payment_type = payment_type
            rec.slip_no = slip_no
            rec.fuel_type = fuel_type
            rec.workspace_pump_id = workspace_pump_id
            rec.previous_reading = previous_reading
            rec.current_reading = current_reading
            rec.km = km
            rec.fuel_price = fuel_price
            rec.liters = liters
            rec.mpg = mpg
            rec.amount = amount
            rec.km_out_task = km_out_task
            rec.km_in_task = km_in_task
            rec.meter_reading_matched = meter_reading_matched
            _resequence_vehicle_fuel_expenses(vehicle_id, workspace_employee_id)
            fuel_je = _workspace_post_expense_journal(
                employee_id=workspace_employee_id,
                reference_type='FuelExpense',
                reference_id=rec.id,
                expense_date=fueling_date,
                amount=amount_f,
                description=fuel_expense_desc,
                category_code='Fuel',
                workspace_party_id=workspace_pump_id if payment_type == 'Credit' else None,
                credit_account_id=(selected_credit_account_id if payment_type == 'Cash' else None),
            )
            if payment_type == 'Credit' and workspace_pump_id and selected_credit_account_id:
                selected_credit = WorkspaceAccount.query.filter_by(
                    id=selected_credit_account_id,
                    employee_id=workspace_employee_id,
                    is_active=True,
                ).first()
                pump_obj = WorkspaceParty.query.filter_by(employee_id=workspace_employee_id, id=workspace_pump_id).first()
                _workspace_post_credit_settlement_journal(
                    employee_id=workspace_employee_id,
                    reference_type='FuelExpense',
                    reference_id=rec.id,
                    expense_date=fueling_date,
                    amount=amount_f,
                    category_code='Fuel',
                    workspace_party_id=workspace_pump_id,
                    credit_account_id=selected_credit_account_id,
                    description=(
                        f"Cash paid by {(selected_credit.name if selected_credit else f'Account {selected_credit_account_id}')}"
                        f" to {(pump_obj.name if pump_obj else 'Pump')} for Cash fueling"
                    ),
                )
            _workspace_sync_regular_expense(
                employee_id=workspace_employee_id,
                reference_type='FuelExpense',
                reference_id=rec.id,
                expense_date=fueling_date,
                amount=amount_f,
                description=fuel_expense_desc,
                expense_type='Fuel Expense',
                payment_mode=payment_type,
                category='Fuel',
                workspace_party_id=(workspace_pump_id if payment_type == 'Credit' else None),
                journal_entry_id=(fuel_je.id if fuel_je else None),
            )
            db.session.commit()
            files = request.files.getlist('attachments')
            has_new_files = bool(files and any(f and getattr(f, 'filename', None) for f in files))
            if has_new_files:
                try:
                    manifest, skipped_att = _prepare_fuel_upload_manifest(files, rec.id)
                    rec.upload_total = len(manifest)
                    rec.upload_done = 0
                    rec.upload_failed = 0
                    rec.upload_error = None
                    rec.upload_finished_at = None
                    if manifest:
                        rec.upload_status = 'processing'
                        rec.upload_started_at = pk_now()
                        rec.upload_manifest_json = json.dumps(manifest)
                    else:
                        rec.upload_status = 'success'
                        rec.upload_started_at = None
                        rec.upload_manifest_json = None
                        rec.upload_finished_at = pk_now()
                    db.session.commit()
                    if manifest:
                        _start_fuel_upload_worker(rec.id)
                        flash(f'Upload background me start ho gaya ({len(manifest)} file). Status list me live dekhein.', 'info')
                    if skipped_att:
                        flash('Kuch files queue me nahi gayin: ' + '; '.join(skipped_att), 'warning')
                except Exception:
                    db.session.rollback()
                    app.logger.exception('Fuel async attachment queue save (edit)')
                    flash('Fuel update save ho gayi lekin files queue me add nahi ho sakin.', 'warning')
            flash('Fuel expense updated.', 'success')
            return redirect(back_url)
        except Exception:
            db.session.rollback()
            raise
    from fuel_expense_settings import fuel_expense_settings_payload
    return render_template(
        'fuel_expense_form.html',
        form=form,
        title='Edit Fuel Expense',
        rec=rec,
        back_url=back_url,
        return_to_path=request.full_path,
        fuel_market_scan=_read_fuel_market_scan() or None,
        location_cascade=_fuel_expense_location_cascade_dict(),
        fuel_expense_settings=fuel_expense_settings_payload(),
    )


@app.route('/expenses/fuel/<int:pk>/view')
def fuel_expense_view(pk):
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return _guard
    workspace_employee_id = _workspace_employee_id_for_expenses()
    rec = FuelExpense.query.get_or_404(pk)
    if workspace_employee_id and rec.employee_id and rec.employee_id != workspace_employee_id:
        flash('This expense does not belong to selected workspace employee.', 'danger')
        return redirect(url_for('fuel_expense_list'))
    default_back = url_for('fuel_expense_list')
    back_url = _safe_internal_path(request.args.get('return_to'), default_back)
    expense_by_label = _workspace_expense_by_label_for_reference(workspace_employee_id, 'FuelExpense', rec.id)
    return render_template(
        'fuel_expense_detail.html',
        rec=rec,
        expense_by_label=expense_by_label,
        title='Fuel Expense Detail',
        back_url=back_url,
        return_to_path=request.full_path,
    )


@app.route('/expenses/fuel/<int:pk>/delete', methods=['POST'])
def fuel_expense_delete(pk):
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return _guard
    workspace_employee_id = _workspace_employee_id_for_expenses()
    rec = FuelExpense.query.get_or_404(pk)
    default_back = url_for('fuel_expense_list')
    back_url = _safe_internal_path(request.args.get('return_to'), default_back)
    if workspace_employee_id and rec.employee_id and rec.employee_id != workspace_employee_id:
        flash('This expense does not belong to selected workspace employee.', 'danger')
        return redirect(back_url)
    attachment_paths = [att.file_path for att in rec.attachments.all() if att and getattr(att, 'file_path', None)]
    rec_id = rec.id
    initiated_by_user_id = session.get('user_id')
    vehicle_id = rec.vehicle_id
    _workspace_reverse_expense_journals('FuelExpense', rec.id, workspace_employee_id)
    _workspace_delete_regular_expense(workspace_employee_id, 'FuelExpense', rec.id)
    db.session.delete(rec)
    _resequence_vehicle_fuel_expenses(vehicle_id, workspace_employee_id)
    db.session.commit()
    _start_expense_delete_cleanup_worker('fuel', rec_id, attachment_paths, employee_id=workspace_employee_id, initiated_by_user_id=initiated_by_user_id)
    flash('Fuel expense deleted. Media cleanup background me continue ho rahi hai.', 'success')
    return redirect(back_url)


@app.route('/workspace/expense-delete-cleanup/<int:job_id>/retry')
def expense_delete_cleanup_retry(job_id):
    job = ExpenseDeleteCleanupJob.query.get_or_404(job_id)
    workspace_employee_id = _workspace_employee_id_for_expenses()
    if not workspace_employee_id and job.employee_id:
        session['workspace_employee_id'] = int(job.employee_id)
        workspace_employee_id = int(job.employee_id)
    if workspace_employee_id and job.employee_id and int(job.employee_id) != int(workspace_employee_id):
        flash('This cleanup job does not belong to selected workspace employee.', 'danger')
        return redirect(url_for('workspace_dashboard'))
    kind = (job.expense_kind or '').strip().lower()
    redirect_map = {
        'fuel': 'fuel_expense_list',
        'oil': 'oil_expense_list',
        'maintenance': 'maintenance_expense_list',
    }
    redirect_endpoint = redirect_map.get(kind, 'workspace_dashboard')
    try:
        pending_paths = json.loads(job.pending_paths_json or '[]')
    except Exception:
        pending_paths = []
    pending_paths = [str(p).strip() for p in pending_paths if str(p).strip()]
    if not pending_paths:
        flash('No failed files left to retry for this cleanup job.', 'info')
        return redirect(url_for(redirect_endpoint))
    started = _start_expense_delete_cleanup_worker(
        kind,
        int(job.expense_id or 0),
        pending_paths,
        cleanup_job_id=job.id,
        initiated_by_user_id=session.get('user_id'),
    )
    if started:
        flash('Cleanup retry started in background. Notification bell me result mil jayega.', 'info')
    else:
        flash('Cleanup retry already running or could not be started.', 'warning')
    return redirect(url_for(redirect_endpoint))


@app.route('/api/fuel-expense/upload-status/<int:pk>')
def api_fuel_expense_upload_status(pk):
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    workspace_employee_id = _workspace_employee_id_for_expenses()
    q = FuelExpense.query.filter_by(id=pk)
    if workspace_employee_id:
        q = q.filter_by(employee_id=workspace_employee_id)
    rec = q.first_or_404()
    total = int(rec.upload_total or 0)
    done = int(rec.upload_done or 0)
    failed = int(rec.upload_failed or 0)
    status = (rec.upload_status or ('success' if total == 0 else 'processing')).strip().lower()
    pct = int(round((done / total) * 100)) if total > 0 else 100
    return jsonify({
        'ok': True,
        'id': rec.id,
        'status': status,
        'total': total,
        'done': done,
        'failed': failed,
        'percent': max(0, min(100, pct)),
        'error': (rec.upload_error or ''),
    })


@app.route('/fuel-expense/<int:pk>/upload-resume', methods=['POST'])
def fuel_expense_upload_resume(pk):
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    workspace_employee_id = _workspace_employee_id_for_expenses()
    rec = FuelExpense.query.get_or_404(pk)
    if workspace_employee_id and rec.employee_id and rec.employee_id != workspace_employee_id:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    try:
        manifest = json.loads(rec.upload_manifest_json or '[]')
    except Exception:
        manifest = []
    if not manifest:
        return jsonify({'ok': False, 'error': 'nothing_to_resume'})
    rec.upload_status = 'processing'
    rec.upload_error = None
    rec.upload_started_at = pk_now()
    rec.upload_finished_at = None
    db.session.commit()
    started = _start_fuel_upload_worker(rec.id)
    return jsonify({'ok': True, 'started': bool(started)})


# ────────────────────────────────────────────────
# Oil Expense
# ────────────────────────────────────────────────
@app.route('/api/oil-expense/last-reading')
def api_oil_expense_last_reading():
    vehicle_id = request.args.get('vehicle_id', type=int)
    expense_date = parse_date(request.args.get('expense_date', ''))
    exclude_id = request.args.get('exclude_id', type=int)
    current_reading = request.args.get('current_reading', type=float)
    if not vehicle_id:
        return jsonify({})
    workspace_employee_id = _workspace_employee_id_for_expenses()
    previous_reading = _oil_expense_previous_reading(
        vehicle_id=vehicle_id,
        expense_date=expense_date,
        exclude_id=exclude_id,
        workspace_employee_id=workspace_employee_id,
        current_reading=current_reading,
    )
    if previous_reading is None:
        return jsonify({})
    return jsonify({'previous_reading': previous_reading})


def _oil_expense_previous_reading(vehicle_id, expense_date=None, exclude_id=None, workspace_employee_id=None, current_reading=None):
    if not vehicle_id:
        return None
    q = OilExpense.query.filter(OilExpense.vehicle_id == vehicle_id)
    if exclude_id:
        q = q.filter(OilExpense.id != exclude_id)
    if expense_date and current_reading is not None:
        try:
            curr_val = float(current_reading)
        except (TypeError, ValueError):
            curr_val = None
        if curr_val is not None:
            same_day_prev = q.filter(
                OilExpense.expense_date == expense_date,
                OilExpense.current_reading.isnot(None),
                OilExpense.current_reading < curr_val,
            ).order_by(
                OilExpense.current_reading.desc(),
                OilExpense.id.desc(),
            ).first()
            if same_day_prev and same_day_prev.current_reading is not None:
                return float(same_day_prev.current_reading)
    if expense_date:
        if current_reading is not None:
            q = q.filter(OilExpense.expense_date < expense_date)
        elif exclude_id:
            q = q.filter(
                db.or_(
                    OilExpense.expense_date < expense_date,
                    db.and_(OilExpense.expense_date == expense_date, OilExpense.id < int(exclude_id)),
                )
            )
        else:
            q = q.filter(OilExpense.expense_date <= expense_date)
    last_entry = q.order_by(OilExpense.expense_date.desc(), OilExpense.id.desc()).first()
    if last_entry and last_entry.current_reading is not None:
        return float(last_entry.current_reading)
    return _fallback_vehicle_previous_reading(workspace_employee_id, vehicle_id, 'oil')


def _resequence_vehicle_oil_expenses(vehicle_id, workspace_employee_id=None):
    if not vehicle_id:
        return
    rows = OilExpense.query.filter(
        OilExpense.vehicle_id == vehicle_id
    ).order_by(
        OilExpense.expense_date.asc(),
        db.case((OilExpense.current_reading.is_(None), 1), else_=0).asc(),
        OilExpense.current_reading.asc(),
        OilExpense.id.asc(),
    ).all()
    previous_current = None
    for idx, row in enumerate(rows):
        if idx == 0:
            if row.previous_reading is None:
                row.previous_reading = _fallback_vehicle_previous_reading(
                    workspace_employee_id or row.employee_id, vehicle_id, 'oil'
                )
        else:
            row.previous_reading = previous_current

        prev_val = float(row.previous_reading) if row.previous_reading is not None else None
        curr_val = float(row.current_reading) if row.current_reading is not None else None
        row.km = (curr_val - prev_val) if (prev_val is not None and curr_val is not None) else None
        previous_current = curr_val


@app.route('/api/oil-expense/products-for-oil')
def api_oil_expense_products_for_oil():
    workspace_employee_id = _workspace_employee_id_for_expenses()
    products = _workspace_products_for_expense_form(workspace_employee_id, 'Oil')
    return jsonify([
        {
            'id': p.id,
            'name': p.name,
            'default_price': float(p.default_price) if p.default_price is not None else None,
        }
        for p in products
    ])


@app.route('/api/oil-expense/product-balance/<int:product_id>')
def api_oil_expense_product_balance(product_id):
    bal = ProductBalance.query.filter_by(product_id=product_id).first()
    qty = float(bal.balance_qty) if bal and bal.balance_qty is not None else 0
    return jsonify({'product_id': product_id, 'balance_qty': qty})


def _expense_history_num_label(val):
    try:
        n = float(val)
    except (TypeError, ValueError):
        return '-'
    return f'{n:.2f}'


def _build_oil_product_price_history(product_id, workspace_party_id=None, current_id=None, workspace_employee_id=None, expense_date=None):
    q = db.session.query(OilExpenseItem, OilExpense, WorkspaceParty).join(
        OilExpense, OilExpense.id == OilExpenseItem.oil_expense_id
    ).outerjoin(
        WorkspaceParty, WorkspaceParty.id == OilExpense.workspace_party_id
    ).filter(
        OilExpenseItem.product_id == product_id
    )
    if workspace_employee_id:
        q = q.filter(OilExpense.employee_id == workspace_employee_id)
    if current_id:
        q = q.filter(OilExpense.id != current_id)
    rows = q.order_by(OilExpense.expense_date.desc(), OilExpense.id.desc(), OilExpenseItem.id.desc()).limit(120).all()

    same_party = []
    other_parties = []
    match_same_date_same_party = None
    match_same_date = None
    match_same_party = None
    match_any = None
    for it, rec, party in rows:
        qty = float(it.purchase_qty if it.purchase_qty is not None else (it.qty if it.qty is not None else 0))
        price = float(it.price or 0)
        if qty <= 0 and price <= 0:
            continue
        total = float(it.amount) if it.amount is not None else (qty * price)
        row = {
            'date_label': rec.expense_date.strftime('%d-%m-%Y') if rec.expense_date else '-',
            'invoice_no': f'OIL-{rec.id}',
            'party_name': (party.name if party else '-'),
            'qty_label': _expense_history_num_label(qty),
            'price_label': _expense_history_num_label(price),
            'total_label': _expense_history_num_label(total),
        }
        if workspace_party_id and rec.workspace_party_id == workspace_party_id:
            same_party.append(row)
        elif rec.workspace_party_id and rec.workspace_party_id != workspace_party_id:
            other_parties.append(row)
        elif not workspace_party_id:
            other_parties.append(row)
        if price <= 0:
            continue
        rec_date = rec.expense_date
        if match_any is None:
            match_any = price
        if workspace_party_id and rec.workspace_party_id == workspace_party_id and match_same_party is None:
            match_same_party = price
        if expense_date and rec_date == expense_date and match_same_date is None:
            match_same_date = price
        if expense_date and workspace_party_id and rec_date == expense_date and rec.workspace_party_id == workspace_party_id and match_same_date_same_party is None:
            match_same_date_same_party = price
    suggested_price = match_same_date_same_party
    if suggested_price is None:
        suggested_price = match_same_date
    if suggested_price is None:
        suggested_price = match_same_party
    if suggested_price is None:
        suggested_price = match_any
    return same_party[:8], other_parties[:8], suggested_price


def _build_maintenance_product_price_history(product_id, workspace_party_id=None, current_id=None, workspace_employee_id=None, expense_date=None):
    q = db.session.query(MaintenanceExpenseItem, MaintenanceExpense, WorkspaceParty).join(
        MaintenanceExpense, MaintenanceExpense.id == MaintenanceExpenseItem.maintenance_expense_id
    ).outerjoin(
        WorkspaceParty, WorkspaceParty.id == MaintenanceExpense.workspace_party_id
    ).filter(
        MaintenanceExpenseItem.product_id == product_id
    )
    if workspace_employee_id:
        q = q.filter(MaintenanceExpense.employee_id == workspace_employee_id)
    if current_id:
        q = q.filter(MaintenanceExpense.id != current_id)
    rows = q.order_by(MaintenanceExpense.expense_date.desc(), MaintenanceExpense.id.desc(), MaintenanceExpenseItem.id.desc()).limit(120).all()

    same_party = []
    other_parties = []
    match_same_date_same_party = None
    match_same_date = None
    match_same_party = None
    match_any = None
    for it, rec, party in rows:
        qty = float(it.qty or 0)
        price = float(it.price or 0)
        if qty <= 0 and price <= 0:
            continue
        total = float(it.amount) if it.amount is not None else (qty * price)
        row = {
            'date_label': rec.expense_date.strftime('%d-%m-%Y') if rec.expense_date else '-',
            'invoice_no': f'MAINT-{rec.id}',
            'party_name': (party.name if party else '-'),
            'qty_label': _expense_history_num_label(qty),
            'price_label': _expense_history_num_label(price),
            'total_label': _expense_history_num_label(total),
        }
        if workspace_party_id and rec.workspace_party_id == workspace_party_id:
            same_party.append(row)
        elif rec.workspace_party_id and rec.workspace_party_id != workspace_party_id:
            other_parties.append(row)
        elif not workspace_party_id:
            other_parties.append(row)
        if price <= 0:
            continue
        rec_date = rec.expense_date
        if match_any is None:
            match_any = price
        if workspace_party_id and rec.workspace_party_id == workspace_party_id and match_same_party is None:
            match_same_party = price
        if expense_date and rec_date == expense_date and match_same_date is None:
            match_same_date = price
        if expense_date and workspace_party_id and rec_date == expense_date and rec.workspace_party_id == workspace_party_id and match_same_date_same_party is None:
            match_same_date_same_party = price
    suggested_price = match_same_date_same_party
    if suggested_price is None:
        suggested_price = match_same_date
    if suggested_price is None:
        suggested_price = match_same_party
    if suggested_price is None:
        suggested_price = match_any
    return same_party[:8], other_parties[:8], suggested_price


@app.route('/api/oil-expense/product-price-history')
def api_oil_expense_product_price_history():
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    product_id = request.args.get('product_id', type=int)
    if not product_id:
        return jsonify({'ok': True, 'same_party': [], 'other_parties': [], 'suggested_price': None})
    workspace_party_id = request.args.get('workspace_party_id', type=int)
    current_id = request.args.get('current_id', type=int)
    expense_date = parse_date(request.args.get('expense_date', ''))
    workspace_employee_id = _workspace_employee_id_for_expenses()
    same_party, other_parties, suggested_price = _build_oil_product_price_history(
        product_id=product_id,
        workspace_party_id=workspace_party_id,
        current_id=current_id,
        workspace_employee_id=workspace_employee_id,
        expense_date=expense_date,
    )
    return jsonify({'ok': True, 'same_party': same_party, 'other_parties': other_parties, 'suggested_price': suggested_price})


def _get_or_create_product_balance(product_id):
    bal = ProductBalance.query.filter_by(product_id=product_id).first()
    if not bal:
        bal = ProductBalance(product_id=product_id, balance_qty=0)
        db.session.add(bal)
    return bal


def _apply_oil_expense_items_balance(items, reverse=False):
    for item in items:
        bal = _get_or_create_product_balance(item.product_id)
        purchase_qty = float(item.purchase_qty or 0)
        used_qty = float(item.used_qty or 0)
        delta = (purchase_qty - used_qty) if not reverse else (used_qty - purchase_qty)
        if delta:
            from decimal import Decimal
            bal.balance_qty = Decimal(str(bal.balance_qty or 0)) + Decimal(str(delta))
    db.session.flush()


def _workspace_products_for_expense_form(employee_id, form_token):
    """Return Product rows for workspace products, creating master Product mirrors when needed.

    Oil/Maintenance item tables reference master Product FK, so workspace products are mapped by
    name and auto-synced on demand.
    """
    token = (form_token or '').strip()
    if not employee_id:
        rows = Product.query.filter(
            db.or_(
                Product.used_in_forms.is_(None),
                Product.used_in_forms == '',
                Product.used_in_forms.like(f'%{token}%'),
            )
        ).order_by(Product.name).all()
        for p in rows:
            # Product table may not have default_price; keep template/API access safe.
            if not hasattr(p, 'default_price'):
                setattr(p, 'default_price', None)
        return rows

    ws_query = WorkspaceProduct.query.filter(
        WorkspaceProduct.employee_id == employee_id,
        WorkspaceProduct.is_active.is_(True),
    )
    if token:
        ws_query = ws_query.filter(
            db.or_(
                WorkspaceProduct.used_in_forms.is_(None),
                WorkspaceProduct.used_in_forms == '',
                WorkspaceProduct.used_in_forms.ilike(f'%{token}%'),
            )
        )
    ws_rows = ws_query.order_by(WorkspaceProduct.name.asc()).all()
    ws_default_price_by_name = {}
    for ws in ws_rows:
        key = (ws.name or '').strip().lower()
        if not key:
            continue
        # Prefer latest non-null configured default price per workspace product name.
        if key not in ws_default_price_by_name or ws.default_price is not None:
            ws_default_price_by_name[key] = ws.default_price

    mapped = []
    changed = False
    for ws in ws_rows:
        name = (ws.name or '').strip()
        if not name:
            continue
        prod = Product.query.filter(func.lower(Product.name) == name.lower()).first()
        if not prod:
            prod = Product(name=name, used_in_forms=token or None, remarks=ws.remarks)
            db.session.add(prod)
            try:
                db.session.flush()
                changed = True
            except IntegrityError:
                db.session.rollback()
                prod = Product.query.filter(func.lower(Product.name) == name.lower()).first()
                if not prod:
                    continue
        elif token:
            existing_tokens = [x.strip() for x in (prod.used_in_forms or '').split(',') if x.strip()]
            if token not in existing_tokens:
                existing_tokens.append(token)
                prod.used_in_forms = ','.join(existing_tokens)
                changed = True
        default_price = ws_default_price_by_name.get(name.lower())
        if not hasattr(prod, 'default_price'):
            setattr(prod, 'default_price', default_price)
        else:
            prod.default_price = default_price
        mapped.append(prod)

    if changed:
        db.session.commit()
    # Keep deterministic ordering and avoid duplicates if names collide by case.
    uniq = {}
    for p in mapped:
        key = (p.name or '').strip().lower()
        if not hasattr(p, 'default_price'):
            setattr(p, 'default_price', ws_default_price_by_name.get(key))
        uniq[p.id] = p
    return sorted(uniq.values(), key=lambda x: (x.name or '').lower())


@app.route('/oil-expenses')
def oil_expense_list():
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return _guard
    workspace_employee_id = _workspace_employee_id_for_expenses()
    from auth_utils import get_user_context
    
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)
    
    form = OilExpenseFilterForm()
    
    # Filter dropdown choices by user scope
    district_q = District.query
    if not is_master_or_admin and allowed_districts:
        district_q = district_q.filter(District.id.in_(list(allowed_districts)))
    form.district_id.choices = [(0, '-- Select District --')] + [(d.id, d.name) for d in district_q.order_by(District.name).all()]
    
    project_q = Project.query
    if not is_master_or_admin and allowed_projects:
        project_q = project_q.filter(Project.id.in_(list(allowed_projects)))
    form.project_id.choices = [(0, '-- Select Project --')] + [(p.id, p.name) for p in project_q.order_by(Project.name).all()]
    
    vehicle_q = Vehicle.query
    if not is_master_or_admin and allowed_vehicles:
        vehicle_q = vehicle_q.filter(Vehicle.id.in_(list(allowed_vehicles)))
    form.vehicle_id.choices = [(0, '-- All Vehicles --')] + [(v.id, v.vehicle_no) for v in vehicle_q.order_by(*vehicle_order_by()).all()]
    today = pk_date()
    from_date = request.args.get('from_date', '').strip()
    to_date = request.args.get('to_date', '').strip()
    district_id = request.args.get('district_id', type=int) or 0
    project_id = request.args.get('project_id', type=int) or 0
    vehicle_id = request.args.get('vehicle_id', type=int) or 0
    work_order_no = (request.args.get('work_order_no') or '').strip()
    from_d = parse_date(from_date) if from_date else today
    to_d = parse_date(to_date) if to_date else today
    if not from_d:
        from_d = today
    if not to_d:
        to_d = today
    if from_d > to_d:
        from_d, to_d = to_d, from_d
    form.from_date.data = from_d
    form.to_date.data = to_d
    form.district_id.data = district_id
    form.project_id.data = project_id
    form.vehicle_id.data = vehicle_id

    query = OilExpense.query.filter(
        OilExpense.expense_date >= from_d,
        OilExpense.expense_date <= to_d
    )
    if workspace_employee_id:
        query = query.filter(
            db.or_(
                OilExpense.employee_id == workspace_employee_id,
                OilExpense.employee_id.is_(None),
            )
        )

    # Apply user data scope
    if not is_master_or_admin:
        if allowed_projects:
            query = query.filter(OilExpense.project_id.in_(list(allowed_projects)))
        if allowed_districts:
            query = query.filter(OilExpense.district_id.in_(list(allowed_districts)))
        if allowed_vehicles:
            query = query.filter(OilExpense.vehicle_id.in_(list(allowed_vehicles)))

    if district_id:
        query = query.filter(OilExpense.district_id == district_id)
    if project_id:
        query = query.filter(OilExpense.project_id == project_id)
    if vehicle_id:
        query = query.filter(OilExpense.vehicle_id == vehicle_id)
    rows = query.order_by(
        OilExpense.expense_date.asc(),
        db.case((OilExpense.current_reading.is_(None), 1), else_=0).asc(),
        OilExpense.current_reading.asc(),
        OilExpense.id.asc(),
    ).all()
    from list_visibility import expense_or_work_order_needs_upload_media_columns
    show_upload_media_columns = (
        any(expense_or_work_order_needs_upload_media_columns(r) for r in rows) if rows else False
    )
    # Attach item totals per row for list display
    rows_with_totals = []
    overall_purchase_qty = 0
    overall_used_qty = 0
    overall_balance_qty = 0
    overall_amount = 0
    for r in rows:
        total_purchase = sum(float(it.purchase_qty or 0) for it in r.items)
        total_used = sum(float(it.used_qty or 0) for it in r.items)
        total_balance = total_purchase - total_used
        total_amount = sum(float(it.amount or 0) for it in r.items)
        rows_with_totals.append({
            'rec': r,
            'total_purchase_qty': total_purchase,
            'total_used_qty': total_used,
            'total_balance_qty': total_balance,
            'total_amount': total_amount
        })
        overall_purchase_qty += total_purchase
        overall_used_qty += total_used
        overall_balance_qty += total_balance
        overall_amount += total_amount
    totals = {
        'count': len(rows),
        'purchase_qty': overall_purchase_qty,
        'used_qty': overall_used_qty,
        'balance_qty': overall_balance_qty,
        'amount': overall_amount
    }
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    pagination = SimplePagination(rows_with_totals, page, per_page)
    rows_with_totals = pagination.items
    # Page subtotals
    page_subtotal_purchase = sum(item['total_purchase_qty'] for item in rows_with_totals)
    page_subtotal_used = sum(item['total_used_qty'] for item in rows_with_totals)
    page_subtotal_balance = sum(item['total_balance_qty'] for item in rows_with_totals)
    page_subtotal_amount = sum(item['total_amount'] for item in rows_with_totals)
    cleanup_status = _latest_expense_cleanup_status('oil', workspace_employee_id)
    return render_template(
        'oil_expense_list.html',
        form=form,
        rows=rows_with_totals,
        from_date=from_d,
        to_date=to_d,
        totals=totals,
        pagination=pagination,
        per_page=per_page,
        cleanup_status=cleanup_status,
        page_subtotal_purchase=page_subtotal_purchase,
        page_subtotal_used=page_subtotal_used,
        page_subtotal_balance=page_subtotal_balance,
        page_subtotal_amount=page_subtotal_amount,
        show_upload_media_columns=show_upload_media_columns,
        location_cascade=_fuel_expense_location_cascade_dict(),
        workspace_employee_id=workspace_employee_id,
    )


@app.route('/oil-expense/add', methods=['GET', 'POST'])
@app.route('/oil-expense/edit/<int:pk>', methods=['GET', 'POST'])
def oil_expense_form(pk=None):
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return _guard
    workspace_employee_id = _workspace_employee_id_for_expenses()
    oil_attachment_max_mb = _expense_attachment_max_bytes() // (1024 * 1024)
    default_district_id = _workspace_employee_default_district_id(workspace_employee_id)
    rec = OilExpense.query.get_or_404(pk) if pk else None
    if rec and workspace_employee_id and rec.employee_id and rec.employee_id != workspace_employee_id:
        flash('This expense does not belong to selected workspace employee.', 'danger')
        return redirect(url_for('oil_expense_list'))
    form = OilExpenseForm(obj=rec)
    total_bill_error = ''
    party_error = ''
    entered_total_bill = (
        (request.form.get('total_bill_amount') or '').strip()
        if request.method == 'POST'
        else (f"{float(rec.total_bill_amount):.2f}" if rec and rec.total_bill_amount is not None else '')
    )
    selected_party_id = (request.form.get('workspace_party_id') or '').strip() if request.method == 'POST' else ''
    workspace_parties = WorkspaceParty.query.filter_by(
        employee_id=workspace_employee_id,
        is_active=True
    ).order_by(WorkspaceParty.name).all()
    form.expense_by.choices = _workspace_expense_by_choices(workspace_employee_id)
    hbl_expense_by_value = _workspace_default_hbl_expense_by(workspace_employee_id)
    products_for_oil = _workspace_products_for_expense_form(workspace_employee_id, 'Oil')
    form.district_id.choices = [(0, '-- Select District --')] + [(d.id, d.name) for d in District.query.order_by(District.name).all()]
    selected_district_id = None
    selected_project_id = None
    if request.method == 'POST':
        selected_district_id = form.district_id.data or None
        selected_project_id = form.project_id.data or None
    elif rec:
        selected_district_id = rec.district_id or None
        selected_project_id = rec.project_id or None
    else:
        selected_district_id = default_district_id or None
    if selected_district_id == 0:
        selected_district_id = None
    if selected_project_id == 0:
        selected_project_id = None

    project_q = Project.query
    if selected_district_id:
        project_q = project_q.join(project_district).filter(project_district.c.district_id == selected_district_id)
    form.project_id.choices = [(0, '-- Select Project --')] + [(p.id, p.name) for p in project_q.order_by(Project.name).all()]

    if selected_project_id:
        vehicle_q = Vehicle.query.filter(Vehicle.project_id == selected_project_id)
        if selected_district_id:
            vehicle_q = vehicle_q.filter(Vehicle.district_id == selected_district_id)
        form.vehicle_id.choices = [(0, '-- Select Vehicle --')] + [(v.id, v.vehicle_no) for v in vehicle_q.order_by(*vehicle_order_by()).all()]
    else:
        form.vehicle_id.choices = [(0, '-- Select Vehicle --')]

    if request.method == 'GET' and rec:
        if rec.district_id:
            form.district_id.data = rec.district_id
        if rec.project_id:
            form.project_id.data = rec.project_id
        if rec.vehicle_id:
            form.vehicle_id.data = rec.vehicle_id
        form.expense_by.data = _workspace_expense_by_for_reference(workspace_employee_id, 'OilExpense', rec.id)
        form.payment_type.data = rec.payment_type or ''
        if rec.total_bill_amount is not None:
            entered_total_bill = f"{float(rec.total_bill_amount):.2f}"
        if getattr(rec, 'workspace_party_id', None):
            selected_party_id = str(rec.workspace_party_id)
        if getattr(rec, 'total_bill_amount', None) is not None:
            entered_total_bill = f"{float(rec.total_bill_amount):.2f}"
    elif request.method == 'GET':
        if default_district_id:
            form.district_id.data = default_district_id
        form.payment_type.data = ''
        if not form.expense_date.data:
            form.expense_date.data = pk_date()

    if form.validate_on_submit():
        vehicle_id = form.vehicle_id.data
        if not vehicle_id:
            flash('Select vehicle.', 'danger')
            return render_template(
                'oil_expense_form.html',
                form=form,
                rec=rec,
                title='Edit Oil Expense' if rec else 'Add Oil Expense',
                products_for_oil=products_for_oil,
                workspace_parties=workspace_parties,
                selected_party_id=selected_party_id,
                entered_total_bill=entered_total_bill,
                total_bill_error=total_bill_error,
                party_error=party_error,
                hbl_expense_by_value=hbl_expense_by_value,
                oil_attachment_max_mb=oil_attachment_max_mb,
                location_cascade=_fuel_expense_location_cascade_dict(),
            )
        expense_date = form.expense_date.data
        payment_type = (form.payment_type.data or '').strip() or None
        if payment_type not in ('Cash', 'Credit'):
            payment_type = None
        if not payment_type:
            flash('Payment Type required hai.', 'danger')
            return render_template(
                'oil_expense_form.html',
                form=form,
                rec=rec,
                title='Edit Oil Expense' if rec else 'Add Oil Expense',
                products_for_oil=products_for_oil,
                workspace_parties=workspace_parties,
                selected_party_id=selected_party_id,
                entered_total_bill=entered_total_bill,
                total_bill_error=total_bill_error,
                party_error=party_error,
                hbl_expense_by_value=hbl_expense_by_value,
                oil_attachment_max_mb=oil_attachment_max_mb,
                location_cascade=_fuel_expense_location_cascade_dict(),
            )
        prev_reading = form.previous_reading.data
        curr_reading = form.current_reading.data
        if prev_reading is None:
            prev_reading = _oil_expense_previous_reading(
                vehicle_id=vehicle_id,
                expense_date=expense_date,
                exclude_id=(rec.id if rec else None),
                workspace_employee_id=workspace_employee_id,
                current_reading=curr_reading,
            )
        km = None
        if prev_reading is not None and curr_reading is not None:
            try:
                km = float(curr_reading) - float(prev_reading)
            except (TypeError, ValueError):
                pass
        remarks = form.remarks.data
        selected_party_id = (request.form.get('workspace_party_id') or '').strip()
        selected_party_id_int = int(selected_party_id) if selected_party_id.isdigit() else None
        if selected_party_id_int:
            valid_party = WorkspaceParty.query.filter_by(
                employee_id=workspace_employee_id,
                id=selected_party_id_int,
                is_active=True
            ).first()
            if not valid_party:
                party_error = 'Selected party is invalid for this workspace.'
                selected_party_id_int = None
        if not selected_party_id_int:
            party_error = 'Party Name (Workspace) select karna zaroori hai.'
        entered_total_bill = (request.form.get('total_bill_amount') or '').strip()
        total_bill_amount = None
        if entered_total_bill:
            try:
                total_bill_amount = Decimal(entered_total_bill)
            except Exception:
                total_bill_amount = None
        if total_bill_amount is not None and total_bill_amount <= Decimal('0'):
            total_bill_error = 'Total Bill Amount must be greater than zero.'

        product_ids = request.form.getlist('product_id')
        purchase_qtys = request.form.getlist('purchase_qty')
        used_qtys = request.form.getlist('used_qty')
        prices = request.form.getlist('price')
        line_amounts = request.form.getlist('line_amount')
        items_data = []
        n = max(
            len(product_ids or [0]), len(purchase_qtys or [0]), len(used_qtys or [0]), len(prices or [0]),
            len(line_amounts or [0])
        )
        for i in range(n):
            pid = product_ids[i] if i < len(product_ids or []) else None
            try:
                pid = int(pid) if pid else None
            except (TypeError, ValueError):
                pid = None
            if not pid:
                continue
            try:
                purchase_qty = float(purchase_qtys[i]) if i < len(purchase_qtys or []) and purchase_qtys[i] else 0
            except (TypeError, ValueError):
                purchase_qty = 0
            try:
                used_qty = float(used_qtys[i]) if i < len(used_qtys or []) and used_qtys[i] else 0
            except (TypeError, ValueError):
                used_qty = 0
            try:
                price = float(prices[i]) if i < len(prices or []) and prices[i] else 0
            except (TypeError, ValueError):
                price = 0
            line_amt = None
            if i < len(line_amounts or []):
                raw = line_amounts[i]
                if raw is not None and str(raw).strip() != '':
                    try:
                        line_amt = float(raw)
                    except (TypeError, ValueError):
                        line_amt = None
            if line_amt is not None:
                amount = line_amt
                if purchase_qty and purchase_qty > 0:
                    price = float(line_amt) / float(purchase_qty)
            elif purchase_qty and price:
                amount = float(purchase_qty) * float(price)
            else:
                amount = None
            items_data.append({
                'product_id': pid,
                'purchase_qty': purchase_qty, 'used_qty': used_qty,
                'price': price, 'amount': amount
            })

        try:
            if rec:
                old_items = list(rec.items.all())
                _apply_oil_expense_items_balance(old_items, reverse=True)
                OilExpenseItem.query.filter_by(oil_expense_id=rec.id).delete()
            else:
                rec = OilExpense(
                    district_id=form.district_id.data or None,
                    project_id=form.project_id.data or None,
                    employee_id=workspace_employee_id,
                    vehicle_id=vehicle_id,
                    expense_date=expense_date,
                    card_swipe_date=None,
                    payment_type=payment_type,
                    previous_reading=prev_reading,
                    current_reading=curr_reading,
                    km=km,
                    remarks=remarks
                )
                db.session.add(rec)
            db.session.flush()

            if rec.id:
                rec.district_id = form.district_id.data or None
                rec.project_id = form.project_id.data or None
                rec.employee_id = workspace_employee_id
                rec.vehicle_id = vehicle_id
                rec.expense_date = expense_date
                rec.card_swipe_date = None
                rec.payment_type = payment_type
                rec.previous_reading = prev_reading
                rec.current_reading = curr_reading
                rec.km = km
                rec.remarks = remarks
            _resequence_vehicle_oil_expenses(vehicle_id, workspace_employee_id)

            for idx, it in enumerate(items_data):
                item = OilExpenseItem(
                    oil_expense_id=rec.id,
                    product_id=it['product_id'],
                    payment_type=None,
                    purchase_qty=it['purchase_qty'],
                    used_qty=it['used_qty'],
                    qty=it['purchase_qty'],
                    price=it['price'],
                    amount=it['amount'],
                    sort_order=idx
                )
                db.session.add(item)
            db.session.flush()
            _apply_oil_expense_items_balance(rec.items.all(), reverse=False)
            _workspace_reverse_expense_journals('OilExpense', rec.id, workspace_employee_id)
            items_total = sum(float(it.amount or 0) for it in rec.items)
            if total_bill_amount is None:
                total_bill_error = 'Total Bill Amount is required.'
            elif abs(float(total_bill_amount) - float(items_total)) > 0.01:
                total_bill_error = 'Total Bill Amount must match product lines total.'

            if total_bill_error or party_error:
                db.session.rollback()
                if total_bill_error:
                    flash(total_bill_error, 'danger')
                if party_error:
                    flash(party_error, 'danger')
                return render_template(
                    'oil_expense_form.html',
                    form=form,
                    rec=rec if rec and rec.id else None,
                    title='Edit Oil Expense' if rec else 'Add Oil Expense',
                    products_for_oil=products_for_oil,
                    workspace_parties=workspace_parties,
                    selected_party_id=selected_party_id,
                    entered_total_bill=entered_total_bill,
                    total_bill_error=total_bill_error,
                    party_error=party_error,
                    hbl_expense_by_value=hbl_expense_by_value,
                    oil_attachment_max_mb=oil_attachment_max_mb,
                    location_cascade=_fuel_expense_location_cascade_dict(),
                )

            rec.workspace_party_id = selected_party_id_int
            rec.total_bill_amount = total_bill_amount
            expense_by_val = form.expense_by.data or ''
            oil_payment_type = payment_type or 'Cash'
            if oil_payment_type == 'Cash':
                expense_by_val = expense_by_val or _workspace_default_hbl_expense_by(workspace_employee_id)
            selected_credit_account_id = _workspace_account_id_from_expense_by(expense_by_val, workspace_employee_id)
            oil_je = _workspace_post_expense_journal(
                employee_id=workspace_employee_id,
                reference_type='OilExpense',
                reference_id=rec.id,
                expense_date=expense_date,
                amount=items_total,
                description=f'Oil expense vehicle {rec.vehicle.vehicle_no if rec.vehicle else rec.vehicle_id}',
                category_code='Oil',
                workspace_party_id=(selected_party_id_int if oil_payment_type == 'Credit' else None),
                credit_account_id=(selected_credit_account_id if oil_payment_type == 'Cash' else None),
            )
            if oil_payment_type == 'Credit' and selected_party_id_int and selected_credit_account_id:
                selected_credit = WorkspaceAccount.query.filter_by(
                    id=selected_credit_account_id,
                    employee_id=workspace_employee_id,
                    is_active=True,
                ).first()
                party_obj = WorkspaceParty.query.filter_by(employee_id=workspace_employee_id, id=selected_party_id_int).first()
                _workspace_post_credit_settlement_journal(
                    employee_id=workspace_employee_id,
                    reference_type='OilExpense',
                    reference_id=rec.id,
                    expense_date=expense_date,
                    amount=items_total,
                    category_code='Oil',
                    workspace_party_id=selected_party_id_int,
                    credit_account_id=selected_credit_account_id,
                    description=(
                        f"Cash paid by {(selected_credit.name if selected_credit else f'Account {selected_credit_account_id}')}"
                        f" to {(party_obj.name if party_obj else 'Party')} for Oil expense"
                    ),
                )
            _workspace_sync_regular_expense(
                employee_id=workspace_employee_id,
                reference_type='OilExpense',
                reference_id=rec.id,
                expense_date=expense_date,
                amount=items_total,
                description=f'Oil expense vehicle {rec.vehicle.vehicle_no if rec.vehicle else rec.vehicle_id}',
                expense_type='Oil Expense',
                payment_mode=oil_payment_type,
                category='Oil',
                workspace_party_id=selected_party_id_int if oil_payment_type == 'Credit' else None,
                journal_entry_id=(oil_je.id if oil_je else None),
            )
            db.session.commit()

            split_upload = request.headers.get('X-Oil-Split-Upload') == '1'
            if split_upload:
                return jsonify({
                    'ok': True,
                    'id': rec.id,
                    'edit': bool(pk),
                    'list_url': url_for('oil_expense_list'),
                })

            files = request.files.getlist('attachments')
            has_new_files = bool(files and any(f and getattr(f, 'filename', None) for f in files))
            if has_new_files:
                try:
                    manifest, skipped_att = _prepare_oil_upload_manifest(files, rec.id)
                    rec.upload_total = len(manifest)
                    rec.upload_done = 0
                    rec.upload_failed = 0
                    rec.upload_error = None
                    rec.upload_finished_at = None
                    if manifest:
                        rec.upload_status = 'processing'
                        rec.upload_started_at = pk_now()
                        rec.upload_manifest_json = json.dumps(manifest)
                    else:
                        rec.upload_status = 'success'
                        rec.upload_started_at = None
                        rec.upload_manifest_json = None
                        rec.upload_finished_at = pk_now()
                    db.session.commit()
                    if manifest:
                        _start_oil_upload_worker(rec.id)
                        flash(f'Upload background me start ho gaya ({len(manifest)} file). Status list me live dekhein.', 'info')
                    if skipped_att:
                        flash('Kuch files queue me nahi gayin: ' + '; '.join(skipped_att), 'warning')
                except Exception:
                    db.session.rollback()
                    app.logger.exception('Oil async attachment queue save')
                    flash('Oil save ho gaya lekin files queue me add nahi ho sakin.', 'warning')

            flash('Oil expense saved.', 'success')
            return redirect(url_for('oil_expense_list'))
        except Exception:
            db.session.rollback()
            raise
    return render_template(
        'oil_expense_form.html',
        form=form,
        rec=rec,
        title='Edit Oil Expense' if rec else 'Add Oil Expense',
        products_for_oil=products_for_oil,
        workspace_parties=workspace_parties,
        selected_party_id=selected_party_id,
        entered_total_bill=entered_total_bill,
        total_bill_error=total_bill_error,
        party_error=party_error,
        hbl_expense_by_value=hbl_expense_by_value,
        oil_attachment_max_mb=oil_attachment_max_mb,
        location_cascade=_fuel_expense_location_cascade_dict(),
    )


@app.route('/oil-expense/<int:pk>/view')
def oil_expense_view(pk):
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return _guard
    workspace_employee_id = _workspace_employee_id_for_expenses()
    rec = OilExpense.query.get_or_404(pk)
    if workspace_employee_id and rec.employee_id and rec.employee_id != workspace_employee_id:
        flash('This expense does not belong to selected workspace employee.', 'danger')
        return redirect(url_for('oil_expense_list'))
    default_back = url_for('oil_expense_list')
    back_url = _safe_internal_path(request.args.get('return_to'), default_back)
    return render_template(
        'oil_expense_detail.html',
        rec=rec,
        title='Oil Expense Detail',
        back_url=back_url,
        return_to_path=request.full_path,
    )


@app.route('/oil-expense/delete/<int:pk>', methods=['POST'])
def oil_expense_delete(pk):
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return _guard
    workspace_employee_id = _workspace_employee_id_for_expenses()
    rec = OilExpense.query.get_or_404(pk)
    if workspace_employee_id and rec.employee_id and rec.employee_id != workspace_employee_id:
        flash('This expense does not belong to selected workspace employee.', 'danger')
        return redirect(url_for('oil_expense_list'))
    attachment_paths = [att.file_path for att in rec.attachments.all() if att and getattr(att, 'file_path', None)]
    rec_id = rec.id
    initiated_by_user_id = session.get('user_id')
    vehicle_id = rec.vehicle_id
    _workspace_reverse_expense_journals('OilExpense', rec.id, workspace_employee_id)
    _workspace_delete_regular_expense(workspace_employee_id, 'OilExpense', rec.id)
    items = list(rec.items.all())
    _apply_oil_expense_items_balance(items, reverse=True)
    db.session.delete(rec)
    _resequence_vehicle_oil_expenses(vehicle_id, workspace_employee_id)
    db.session.commit()
    _start_expense_delete_cleanup_worker('oil', rec_id, attachment_paths, employee_id=workspace_employee_id, initiated_by_user_id=initiated_by_user_id)
    flash('Oil expense deleted. Media cleanup background me continue ho rahi hai.', 'success')
    return redirect(url_for('oil_expense_list'))


@app.route('/api/oil-expense/upload-status/<int:pk>')
def api_oil_expense_upload_status(pk):
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    workspace_employee_id = _workspace_employee_id_for_expenses()
    q = OilExpense.query.filter_by(id=pk)
    if workspace_employee_id:
        q = q.filter_by(employee_id=workspace_employee_id)
    rec = q.first_or_404()
    total = int(rec.upload_total or 0)
    done = int(rec.upload_done or 0)
    failed = int(rec.upload_failed or 0)
    status = (rec.upload_status or ('success' if total == 0 else 'processing')).strip().lower()
    pct = int(round((done / total) * 100)) if total > 0 else 100
    return jsonify({
        'ok': True,
        'id': rec.id,
        'status': status,
        'total': total,
        'done': done,
        'failed': failed,
        'percent': max(0, min(100, pct)),
        'error': (rec.upload_error or ''),
    })


@app.route('/api/oil-expense/<int:pk>/queue-files', methods=['POST'])
def api_oil_expense_queue_files(pk):
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    workspace_employee_id = _workspace_employee_id_for_expenses()
    rec = OilExpense.query.get_or_404(pk)
    if workspace_employee_id and rec.employee_id and rec.employee_id != workspace_employee_id:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    files = request.files.getlist('attachments')
    if not files or not any(f and getattr(f, 'filename', None) for f in files):
        return jsonify({'ok': False, 'error': 'no_files'}), 400
    try:
        start_worker = request.headers.get('X-Oil-Batch-Final') == '1'
        queued, skipped = _append_expense_upload_manifest(rec, 'oil', files, start_worker=start_worker)
        return jsonify({
            'ok': True,
            'id': rec.id,
            'queued': queued,
            'skipped': skipped,
            'total': int(rec.upload_total or 0),
            'done': int(rec.upload_done or 0),
            'status': rec.upload_status or 'processing',
        })
    except Exception as ex:
        db.session.rollback()
        app.logger.exception('Oil queue-files failed expense=%s', pk)
        return jsonify({'ok': False, 'error': str(ex)}), 500


@app.route('/oil-expense/<int:pk>/upload-resume', methods=['POST'])
def oil_expense_upload_resume(pk):
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    workspace_employee_id = _workspace_employee_id_for_expenses()
    rec = OilExpense.query.get_or_404(pk)
    if workspace_employee_id and rec.employee_id and rec.employee_id != workspace_employee_id:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    try:
        manifest = json.loads(rec.upload_manifest_json or '[]')
    except Exception:
        manifest = []
    if not manifest:
        return jsonify({'ok': False, 'error': 'nothing_to_resume'})
    rec.upload_status = 'processing'
    rec.upload_error = None
    rec.upload_started_at = pk_now()
    rec.upload_finished_at = None
    db.session.commit()
    started = _start_oil_upload_worker(rec.id)
    return jsonify({'ok': True, 'started': bool(started)})


# ────────────────────────────────────────────────
# Maintenance Expense
# ────────────────────────────────────────────────
@app.route('/api/maintenance-expense/last-reading')
def api_maintenance_expense_last_reading():
    vehicle_id = request.args.get('vehicle_id', type=int)
    expense_date = parse_date(request.args.get('expense_date', ''))
    exclude_id = request.args.get('exclude_id', type=int)
    current_reading = request.args.get('current_reading', type=float)
    if not vehicle_id:
        return jsonify({})
    workspace_employee_id = _workspace_employee_id_for_expenses()
    previous_reading = _maintenance_expense_previous_reading(
        vehicle_id=vehicle_id,
        expense_date=expense_date,
        exclude_id=exclude_id,
        workspace_employee_id=workspace_employee_id,
        current_reading=current_reading,
    )
    if previous_reading is None:
        return jsonify({})
    return jsonify({'previous_reading': previous_reading})


@app.route('/api/maintenance-expense/live-summary')
def api_maintenance_expense_live_summary():
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403

    workspace_employee_id = _workspace_employee_id_for_expenses()
    district_id = request.args.get('district_id', type=int)
    project_id = request.args.get('project_id', type=int)
    vehicle_id = request.args.get('vehicle_id', type=int)
    product_id = request.args.get('product_id', type=int)
    expense_date = parse_date(request.args.get('expense_date', ''))
    current_id = request.args.get('current_id', type=int)

    q = MaintenanceExpense.query.options(
        joinedload(MaintenanceExpense.district),
        joinedload(MaintenanceExpense.project),
        joinedload(MaintenanceExpense.vehicle),
        joinedload(MaintenanceExpense.workspace_party),
    )
    if workspace_employee_id:
        q = q.filter(
            db.or_(
                MaintenanceExpense.employee_id == workspace_employee_id,
                MaintenanceExpense.employee_id.is_(None),
            )
        )
    if district_id:
        q = q.filter(MaintenanceExpense.district_id == district_id)
    if project_id:
        q = q.filter(MaintenanceExpense.project_id == project_id)
    if vehicle_id:
        q = q.filter(MaintenanceExpense.vehicle_id == vehicle_id)
    if expense_date:
        q = q.filter(MaintenanceExpense.expense_date <= expense_date)
    if current_id:
        q = q.filter(MaintenanceExpense.id != current_id)
    if product_id:
        q = q.join(MaintenanceExpenseItem, MaintenanceExpenseItem.maintenance_expense_id == MaintenanceExpense.id)
        q = q.filter(MaintenanceExpenseItem.product_id == product_id)

    rec = q.order_by(MaintenanceExpense.expense_date.desc(), MaintenanceExpense.id.desc()).first()
    if not rec:
        return jsonify({'ok': True, 'found': False})

    line_rows = []
    line_total = 0.0
    for it in rec.items.order_by(MaintenanceExpenseItem.sort_order.asc(), MaintenanceExpenseItem.id.asc()).all():
        qty = float(it.qty or 0)
        price = float(it.price or 0)
        amount = float(it.amount or (qty * price))
        line_total += amount
        line_rows.append({
            'product_name': (it.product.name if it.product else f'Product #{it.product_id}'),
            'qty': qty,
            'price': price,
            'amount': amount,
            'qty_label': f'{qty:.2f}',
            'price_label': f'{price:.2f}',
            'amount_label': f'{amount:.2f}',
        })

    return jsonify({
        'ok': True,
        'found': True,
        'expense_id': rec.id,
        'invoice_no': f'MAINT-{rec.id}',
        'expense_date': rec.expense_date.isoformat() if rec.expense_date else None,
        'expense_date_label': rec.expense_date.strftime('%d-%m-%Y') if rec.expense_date else '-',
        'current_reading': float(rec.current_reading) if rec.current_reading is not None else None,
        'current_reading_label': f'{float(rec.current_reading):.2f}' if rec.current_reading is not None else '-',
        'previous_reading': float(rec.previous_reading) if rec.previous_reading is not None else None,
        'previous_reading_label': f'{float(rec.previous_reading):.2f}' if rec.previous_reading is not None else '-',
        'district_name': rec.district.name if rec.district else '-',
        'project_name': rec.project.name if rec.project else '-',
        'vehicle_no': rec.vehicle.vehicle_no if rec.vehicle else '-',
        'party_name': rec.workspace_party.name if rec.workspace_party else '-',
        'payment_type': rec.payment_type or '-',
        'total_bill_amount': float(rec.total_bill_amount or 0),
        'total_bill_label': f'{float(rec.total_bill_amount or 0):.2f}',
        'lines_total_label': f'{line_total:.2f}',
        'items_count': len(line_rows),
        'items': line_rows,
    })


@app.route('/api/maintenance-expense/invoice-detail/<int:pk>')
def api_maintenance_expense_invoice_detail(pk):
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    workspace_employee_id = _workspace_employee_id_for_expenses()
    q = MaintenanceExpense.query.options(
        joinedload(MaintenanceExpense.district),
        joinedload(MaintenanceExpense.project),
        joinedload(MaintenanceExpense.vehicle),
        joinedload(MaintenanceExpense.workspace_party),
    ).filter_by(id=pk)
    if workspace_employee_id:
        q = q.filter_by(employee_id=workspace_employee_id)
    rec = q.first_or_404()

    rows = []
    grand_total = 0.0
    total_qty = 0.0
    for it in rec.items.order_by(MaintenanceExpenseItem.sort_order.asc(), MaintenanceExpenseItem.id.asc()).all():
        qty = float(it.qty or 0)
        price = float(it.price or 0)
        amount = float(it.amount or (qty * price))
        total_qty += qty
        grand_total += amount
        rows.append({
            'product_name': (it.product.name if it.product else f'Product #{it.product_id}'),
            'qty': qty,
            'price': price,
            'amount': amount,
            'qty_label': f'{qty:.2f}',
            'price_label': f'{price:.2f}',
            'amount_label': f'{amount:.2f}',
        })

    return jsonify({
        'ok': True,
        'invoice_no': f'MAINT-{rec.id}',
        'expense_id': rec.id,
        'expense_date_label': rec.expense_date.strftime('%d-%m-%Y') if rec.expense_date else '-',
        'district_name': rec.district.name if rec.district else '-',
        'project_name': rec.project.name if rec.project else '-',
        'vehicle_no': rec.vehicle.vehicle_no if rec.vehicle else '-',
        'party_name': rec.workspace_party.name if rec.workspace_party else '-',
        'payment_type': rec.payment_type or '-',
        'previous_reading_label': f'{float(rec.previous_reading):.2f}' if rec.previous_reading is not None else '-',
        'current_reading_label': f'{float(rec.current_reading):.2f}' if rec.current_reading is not None else '-',
        'total_qty_label': f'{total_qty:.2f}',
        'line_total_label': f'{grand_total:.2f}',
        'bill_total_label': f'{float(rec.total_bill_amount or 0):.2f}',
        'remarks': rec.remarks or '',
        'items': rows,
    })


def _maintenance_approval_qty_label(qty_val):
    try:
        qv = Decimal(str(qty_val))
    except Exception:
        qv = Decimal('0')
    qv = qv.quantize(Decimal('0.01'))
    s = format(qv, 'f')
    if '.' in s:
        s = s.rstrip('0').rstrip('.')
    return s or '0'


def _maintenance_approval_detail_line(p_name, qty, amount):
    amt = int(round(float(amount or 0)))
    if 'labour' in (p_name or '').lower():
        return f'* {p_name} = Rs. {amt:,}'
    qty_lbl = _maintenance_approval_qty_label(qty)
    return f'* {p_name} ×{qty_lbl} = Rs. {amt:,}'


def _maintenance_approval_total_line(total):
    amt = int(round(float(total or 0)))
    return f'💰 Total Amount: Rs. {amt:,}/-'


@app.route('/api/maintenance-expense/approval-text/<int:pk>')
def api_maintenance_expense_approval_text(pk):
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    workspace_employee_id = _workspace_employee_id_for_expenses()
    rec = MaintenanceExpense.query.options(
        joinedload(MaintenanceExpense.district),
        joinedload(MaintenanceExpense.project),
        joinedload(MaintenanceExpense.vehicle).joinedload(Vehicle.drivers),
    ).get_or_404(pk)
    if workspace_employee_id and rec.employee_id and rec.employee_id != workspace_employee_id:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403

    vehicle = rec.vehicle
    selected_driver_id = request.args.get('driver_id', type=int)
    driver_name = '-'
    driver_options = []
    if vehicle:
        active_drivers = [d for d in (vehicle.drivers or []) if (d.status or '').lower() == 'active']
        fallback_drivers = active_drivers or list(vehicle.drivers or [])
        fallback_drivers.sort(key=lambda d: ((d.name or '').lower(), d.id or 0))
        selected_driver = None
        if selected_driver_id:
            selected_driver = next((d for d in fallback_drivers if d.id == selected_driver_id), None)
        if not selected_driver and fallback_drivers:
            selected_driver = fallback_drivers[0]
        if selected_driver:
            driver_name = selected_driver.name or '-'
            selected_driver_id = selected_driver.id
        driver_options = [
            {
                'id': d.id,
                'name': d.name or f'Driver #{d.id}',
                'status': (d.status or '').lower(),
            }
            for d in fallback_drivers
        ]

    item_rows = rec.items.order_by(MaintenanceExpenseItem.sort_order.asc(), MaintenanceExpenseItem.id.asc()).all()
    detail_lines = []
    total_amount = 0.0
    current_product_ids = []
    current_product_names = {}

    for it in item_rows:
        qty = float(it.qty or 0)
        price = float(it.price or 0)
        amount = float(it.amount or (qty * price))
        total_amount += amount
        p_name = (it.product.name if it.product else f'Product #{it.product_id}')
        detail_lines.append(_maintenance_approval_detail_line(p_name, qty, amount))
        if it.product_id and it.product_id not in current_product_ids:
            current_product_ids.append(it.product_id)
            current_product_names[it.product_id] = p_name

    # Previous similar product usage detail for context in approval message.
    previous_work_lines = []
    if vehicle and current_product_ids:
        for product_id in current_product_ids:
            prev_item = db.session.query(MaintenanceExpenseItem, MaintenanceExpense).join(
                MaintenanceExpense, MaintenanceExpense.id == MaintenanceExpenseItem.maintenance_expense_id
            ).filter(
                MaintenanceExpense.vehicle_id == vehicle.id,
                MaintenanceExpenseItem.product_id == product_id,
                db.or_(
                    MaintenanceExpense.expense_date < rec.expense_date,
                    db.and_(MaintenanceExpense.expense_date == rec.expense_date, MaintenanceExpense.id < rec.id),
                )
            ).order_by(
                MaintenanceExpense.expense_date.desc(),
                MaintenanceExpense.id.desc(),
                MaintenanceExpenseItem.id.desc(),
            ).first()
            if not prev_item:
                continue
            p_it, p_exp = prev_item
            p_name = current_product_names.get(p_it.product_id) or (p_it.product.name if p_it.product else f'Product #{p_it.product_id}')
            p_date = p_exp.expense_date.strftime('%d-%m-%Y') if p_exp.expense_date else '-'
            p_reading = f"{float(p_exp.current_reading):,.0f}" if p_exp.current_reading is not None else '-'
            previous_work_lines.append(f"{p_name} last work was on {p_date} at a reading of {p_reading} km.")

    district_name = rec.district.name if rec.district else '-'
    project_name = rec.project.name if rec.project else '-'
    custom_location = (request.args.get('location') or '').strip()
    location_default = district_name if district_name and district_name != '-' else ''
    location = custom_location or location_default or '-'
    vehicle_no = vehicle.vehicle_no if vehicle else '-'
    vehicle_label = f"{vehicle_no} ({project_name})" if project_name and project_name != '-' else vehicle_no
    reading_txt = f"{float(rec.current_reading):.0f}" if rec.current_reading is not None else '-'
    date_txt = rec.expense_date.strftime('%d-%m-%Y') if rec.expense_date else '-'
    bill_total = float(rec.total_bill_amount if rec.total_bill_amount is not None else total_amount)

    message_mode = (request.args.get('message_mode') or 'approval_required').strip().lower()
    heading_text = "Work done" if message_mode == 'work_done' else "Approval Required"
    lines = [
        heading_text,
        vehicle_label,
        f"Date: {date_txt}",
        f"Reading: {reading_txt}",
        f"Driver: {driver_name}",
        f"Location: {location}",
        "Detail:",
    ]
    lines.extend(detail_lines or ['-'])
    lines.extend([
        _maintenance_approval_total_line(bill_total),
        "Previous Work Detail:",
    ])
    lines.extend(previous_work_lines or ['No previous work record found.'])
    approval_text = '\n'.join(lines)
    return jsonify({
        'ok': True,
        'approval_text': approval_text,
        'vehicle_no': vehicle_no,
        'vehicle_label': vehicle_label,
        'date': date_txt,
        'driver_options': driver_options,
        'selected_driver_id': selected_driver_id,
        'location_default': location_default,
        'location_used': location,
    })


@app.route('/api/maintenance-work-orders/for-vehicle')
def api_maintenance_work_orders_for_vehicle():
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    workspace_employee_id = _workspace_employee_id_for_expenses()
    vehicle_id = request.args.get('vehicle_id', type=int)
    if not vehicle_id:
        return jsonify({'ok': True, 'work_orders': []})
    q = MaintenanceWorkOrder.query.filter(
        MaintenanceWorkOrder.vehicle_id == vehicle_id,
        MaintenanceWorkOrder.status != 'closed',
    )
    if workspace_employee_id:
        q = q.filter(
            db.or_(
                MaintenanceWorkOrder.employee_id == workspace_employee_id,
                MaintenanceWorkOrder.employee_id.is_(None),
            )
        )
    rows = q.order_by(MaintenanceWorkOrder.opened_on.desc(), MaintenanceWorkOrder.id.desc()).limit(100).all()
    return jsonify({
        'ok': True,
        'work_orders': [
            {'id': w.id, 'label': f'{w.work_order_no} | {w.title}'}
            for w in rows
        ]
    })


@app.route('/api/maintenance-work-order/approval-text/<int:pk>')
def api_maintenance_work_order_approval_text(pk):
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    workspace_employee_id = _workspace_employee_id_for_expenses()
    wo = MaintenanceWorkOrder.query.options(
        joinedload(MaintenanceWorkOrder.district),
        joinedload(MaintenanceWorkOrder.project),
        joinedload(MaintenanceWorkOrder.vehicle).joinedload(Vehicle.drivers),
    ).get_or_404(pk)
    if workspace_employee_id and wo.employee_id and wo.employee_id != workspace_employee_id:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403

    expenses = wo.expenses.order_by(MaintenanceExpense.expense_date.asc(), MaintenanceExpense.id.asc()).all()
    vehicle = wo.vehicle
    selected_driver_id = request.args.get('driver_id', type=int)
    driver_name = '-'
    driver_options = []
    if vehicle:
        active_drivers = [d for d in (vehicle.drivers or []) if (d.status or '').lower() == 'active']
        fallback_drivers = active_drivers or list(vehicle.drivers or [])
        fallback_drivers.sort(key=lambda d: ((d.name or '').lower(), d.id or 0))
        selected_driver = None
        if selected_driver_id:
            selected_driver = next((d for d in fallback_drivers if d.id == selected_driver_id), None)
        if not selected_driver and fallback_drivers:
            selected_driver = fallback_drivers[0]
        if selected_driver:
            driver_name = selected_driver.name or '-'
            selected_driver_id = selected_driver.id
        driver_options = [
            {
                'id': d.id,
                'name': d.name or f'Driver #{d.id}',
                'status': (d.status or '').lower(),
            }
            for d in fallback_drivers
        ]

    district_name = (wo.district.name if wo.district else '-') if wo else '-'
    project_name = (wo.project.name if wo.project else '-') if wo else '-'
    custom_location = (request.args.get('location') or '').strip()
    location_default = district_name if district_name and district_name != '-' else ''
    location = custom_location or location_default or '-'
    vehicle_no = vehicle.vehicle_no if vehicle else '-'
    vehicle_label = f"{vehicle_no} ({project_name})" if project_name and project_name != '-' else vehicle_no
    wo_date = wo.opened_on.strftime('%d-%m-%Y') if wo.opened_on else '-'

    detail_lines = []
    grand_total = 0.0
    current_product_ids = []
    current_product_names = {}

    for ex in expenses:
        ex_total = float(ex.total_bill_amount or 0)
        if ex_total <= 0:
            ex_total = sum(float(it.amount or (float(it.qty or 0) * float(it.price or 0))) for it in ex.items.all())
        grand_total += ex_total
        for it in ex.items.order_by(MaintenanceExpenseItem.sort_order.asc(), MaintenanceExpenseItem.id.asc()).all():
            p_name = (it.product.name if it.product else f'Product #{it.product_id}')
            qty = float(it.qty or 0)
            price = float(it.price or 0)
            amount = float(it.amount or (qty * price))
            detail_lines.append(_maintenance_approval_detail_line(p_name, qty, amount))
            if it.product_id and it.product_id not in current_product_ids:
                current_product_ids.append(it.product_id)
                current_product_names[it.product_id] = p_name

    if not detail_lines:
        detail_lines = ['-']

    previous_work_lines = []
    if vehicle and current_product_ids:
        first_expense = expenses[0] if expenses else None
        boundary_date = first_expense.expense_date if first_expense and first_expense.expense_date else wo.opened_on
        boundary_id = first_expense.id if first_expense else 0
        for pidx, product_id in enumerate(current_product_ids, 1):
            prev_item = db.session.query(MaintenanceExpenseItem, MaintenanceExpense).join(
                MaintenanceExpense, MaintenanceExpense.id == MaintenanceExpenseItem.maintenance_expense_id
            ).filter(
                MaintenanceExpense.vehicle_id == vehicle.id,
                MaintenanceExpenseItem.product_id == product_id,
                db.or_(
                    MaintenanceExpense.expense_date < boundary_date,
                    db.and_(MaintenanceExpense.expense_date == boundary_date, MaintenanceExpense.id < boundary_id),
                )
            ).order_by(
                MaintenanceExpense.expense_date.desc(),
                MaintenanceExpense.id.desc(),
                MaintenanceExpenseItem.id.desc(),
            ).first()
            p_name = current_product_names.get(product_id) or f'Product #{product_id}'
            if prev_item:
                p_it, p_exp = prev_item
                p_date = p_exp.expense_date.strftime('%d-%m-%Y') if p_exp.expense_date else '-'
                p_reading = f"{float(p_exp.current_reading):,.0f}" if p_exp.current_reading is not None else '-'
                previous_work_lines.append(f"{pidx}- {p_name} last work was on {p_date} at a reading of {p_reading} km.")
    if not previous_work_lines:
        previous_work_lines = ['No previous work record found.']

    message_mode = (request.args.get('message_mode') or 'approval_required').strip().lower()
    heading_text = "Work done" if message_mode == 'work_done' else "Approval Required"
    lines = [
        heading_text,
        vehicle_label,
        f"Date: {wo_date}",
        f"Driver: {driver_name}",
        f"Location: {location}",
        "Detail:",
    ]
    lines.extend(detail_lines)
    lines.extend([
        _maintenance_approval_total_line(grand_total),
        "Previous Work Detail:",
    ])
    lines.extend(previous_work_lines)

    return jsonify({
        'ok': True,
        'approval_text': '\n'.join(lines),
        'work_order_no': wo.work_order_no or '-',
        'vehicle_no': vehicle_no,
        'vehicle_label': vehicle_label,
        'date': wo_date,
        'driver_options': driver_options,
        'selected_driver_id': selected_driver_id,
        'location_default': location_default,
        'location_used': location,
    })


@app.route('/api/oil-expense/approval-text/<int:pk>')
def api_oil_expense_approval_text(pk):
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    workspace_employee_id = _workspace_employee_id_for_expenses()
    q = OilExpense.query.options(
        joinedload(OilExpense.district),
        joinedload(OilExpense.project),
        joinedload(OilExpense.vehicle).joinedload(Vehicle.drivers),
    ).filter_by(id=pk)
    if workspace_employee_id:
        q = q.filter_by(employee_id=workspace_employee_id)
    rec = q.first_or_404()

    vehicle = rec.vehicle
    selected_driver_id = request.args.get('driver_id', type=int)
    driver_name = '-'
    driver_options = []
    if vehicle:
        active_drivers = [d for d in (vehicle.drivers or []) if (d.status or '').lower() == 'active']
        fallback_drivers = active_drivers or list(vehicle.drivers or [])
        fallback_drivers.sort(key=lambda d: ((d.name or '').lower(), d.id or 0))
        selected_driver = None
        if selected_driver_id:
            selected_driver = next((d for d in fallback_drivers if d.id == selected_driver_id), None)
        if not selected_driver and fallback_drivers:
            selected_driver = fallback_drivers[0]
        if selected_driver:
            driver_name = selected_driver.name or '-'
            selected_driver_id = selected_driver.id
        driver_options = [
            {
                'id': d.id,
                'name': d.name or f'Driver #{d.id}',
                'status': (d.status or '').lower(),
            }
            for d in fallback_drivers
        ]

    district_name = rec.district.name if rec.district else '-'
    project_name = rec.project.name if rec.project else '-'
    custom_location = (request.args.get('location') or '').strip()
    location_default = district_name if district_name and district_name != '-' else ''
    location = custom_location or location_default or '-'
    vehicle_no = vehicle.vehicle_no if vehicle else '-'
    vehicle_label = f"{vehicle_no} ({project_name})" if project_name and project_name != '-' else vehicle_no

    payment_mode_raw = (request.args.get('payment_mode') or '').strip()
    payment_mode = payment_mode_raw or (rec.payment_type or 'Cash')
    allowed_payment_modes = ['Cash', 'Credit', 'Card', 'In Hand Stock']
    if payment_mode not in allowed_payment_modes:
        payment_mode = 'Cash'

    oil_date_txt = rec.expense_date.strftime('%d-%m-%Y') if rec.expense_date else '-'
    prev_reading = f"{float(rec.previous_reading):.0f}" if rec.previous_reading is not None else '-'
    curr_reading = f"{float(rec.current_reading):.0f}" if rec.current_reading is not None else '-'
    km_txt = f"{float(rec.km):.0f}" if rec.km is not None else '-'

    def _approval_qty_label(qty_val):
        try:
            qv = Decimal(str(qty_val))
        except Exception:
            qv = Decimal('0')
        qv = qv.quantize(Decimal('0.01'))
        s = format(qv, 'f')
        if '.' in s:
            s = s.rstrip('0').rstrip('.')
        return s or '0'

    detail_lines = []
    total_amount = 0.0
    for it in rec.items.order_by(OilExpenseItem.sort_order.asc(), OilExpenseItem.id.asc()).all():
        p_name = (it.product.name if it.product else f'Product #{it.product_id}')
        qty = float(it.purchase_qty if it.purchase_qty is not None else (it.qty or 0))
        price = float(it.price or 0)
        amount = float(it.amount or (qty * price))
        total_amount += amount
        detail_lines.append(f"{len(detail_lines) + 1}- {p_name} {_approval_qty_label(qty)}x{price:.0f}={amount:.0f}")
    if not detail_lines:
        detail_lines = ['-']

    lines = [
        "Oil Change Done",
        vehicle_label,
        f"Oil Change Date: {oil_date_txt}",
        f"last Oil change Reading: {prev_reading}",
        f"Current Oil Change Reading: {curr_reading} ({km_txt} km)",
        f"Driver: {driver_name}",
        f"Location: {location}",
        "Detail:",
        f"Payment Mode: {payment_mode}",
    ]
    lines.extend(detail_lines)
    lines.append(f"Total: {total_amount:.0f}")

    return jsonify({
        'ok': True,
        'approval_text': '\n'.join(lines),
        'vehicle_no': vehicle_no,
        'vehicle_label': vehicle_label,
        'date': oil_date_txt,
        'driver_options': driver_options,
        'selected_driver_id': selected_driver_id,
        'location_default': location_default,
        'location_used': location,
        'payment_mode': payment_mode,
        'payment_modes': allowed_payment_modes,
    })


def _maintenance_expense_previous_reading(vehicle_id, expense_date=None, exclude_id=None, workspace_employee_id=None, current_reading=None):
    if not vehicle_id:
        return None
    q = MaintenanceExpense.query.filter(MaintenanceExpense.vehicle_id == vehicle_id)
    if exclude_id:
        q = q.filter(MaintenanceExpense.id != exclude_id)
    if expense_date and current_reading is not None:
        try:
            curr_val = float(current_reading)
        except (TypeError, ValueError):
            curr_val = None
        if curr_val is not None:
            same_day_prev = q.filter(
                MaintenanceExpense.expense_date == expense_date,
                MaintenanceExpense.current_reading.isnot(None),
                MaintenanceExpense.current_reading < curr_val,
            ).order_by(
                MaintenanceExpense.current_reading.desc(),
                MaintenanceExpense.id.desc(),
            ).first()
            if same_day_prev and same_day_prev.current_reading is not None:
                return float(same_day_prev.current_reading)
    if expense_date:
        if current_reading is not None:
            q = q.filter(MaintenanceExpense.expense_date < expense_date)
        elif exclude_id:
            q = q.filter(
                db.or_(
                    MaintenanceExpense.expense_date < expense_date,
                    db.and_(MaintenanceExpense.expense_date == expense_date, MaintenanceExpense.id < int(exclude_id)),
                )
            )
        else:
            q = q.filter(MaintenanceExpense.expense_date <= expense_date)
    last_entry = q.order_by(MaintenanceExpense.expense_date.desc(), MaintenanceExpense.id.desc()).first()
    if last_entry and last_entry.current_reading is not None:
        return float(last_entry.current_reading)
    fallback = _fallback_vehicle_previous_reading(workspace_employee_id, vehicle_id, 'maintenance')
    return float(fallback) if fallback is not None else None


def _resequence_vehicle_maintenance_expenses(vehicle_id, workspace_employee_id=None):
    if not vehicle_id:
        return
    rows = MaintenanceExpense.query.filter(
        MaintenanceExpense.vehicle_id == vehicle_id
    ).order_by(
        MaintenanceExpense.expense_date.asc(),
        db.case((MaintenanceExpense.current_reading.is_(None), 1), else_=0).asc(),
        MaintenanceExpense.current_reading.asc(),
        MaintenanceExpense.id.asc(),
    ).all()
    previous_current = None
    for idx, row in enumerate(rows):
        if idx == 0:
            if row.previous_reading is None:
                row.previous_reading = _maintenance_expense_previous_reading(
                    vehicle_id=vehicle_id,
                    expense_date=row.expense_date,
                    exclude_id=row.id,
                    workspace_employee_id=(workspace_employee_id or row.employee_id),
                )
        else:
            row.previous_reading = previous_current

        prev_val = float(row.previous_reading) if row.previous_reading is not None else None
        curr_val = float(row.current_reading) if row.current_reading is not None else None
        row.km = (curr_val - prev_val) if (prev_val is not None and curr_val is not None) else None
        previous_current = curr_val


@app.route('/api/maintenance-expense/products-for-maintenance')
def api_maintenance_expense_products():
    workspace_employee_id = _workspace_employee_id_for_expenses()
    products = _workspace_products_for_expense_form(workspace_employee_id, 'Maintenance')
    return jsonify([
        {
            'id': p.id,
            'name': p.name,
            'default_price': float(p.default_price) if p.default_price is not None else None,
        }
        for p in products
    ])


@app.route('/api/maintenance-expense/product-price-history')
def api_maintenance_expense_product_price_history():
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    product_id = request.args.get('product_id', type=int)
    if not product_id:
        return jsonify({'ok': True, 'same_party': [], 'other_parties': [], 'suggested_price': None})
    workspace_party_id = request.args.get('workspace_party_id', type=int)
    current_id = request.args.get('current_id', type=int)
    expense_date = parse_date(request.args.get('expense_date', ''))
    workspace_employee_id = _workspace_employee_id_for_expenses()
    same_party, other_parties, suggested_price = _build_maintenance_product_price_history(
        product_id=product_id,
        workspace_party_id=workspace_party_id,
        current_id=current_id,
        workspace_employee_id=workspace_employee_id,
        expense_date=expense_date,
    )
    return jsonify({'ok': True, 'same_party': same_party, 'other_parties': other_parties, 'suggested_price': suggested_price})


@app.route('/api/maintenance-expense/<int:pk>/queue-files', methods=['POST'])
def api_maintenance_expense_queue_files(pk):
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    workspace_employee_id = _workspace_employee_id_for_expenses()
    rec = MaintenanceExpense.query.get_or_404(pk)
    if workspace_employee_id and rec.employee_id and rec.employee_id != workspace_employee_id:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    files = request.files.getlist('attachments')
    if not files or not any(f and getattr(f, 'filename', None) for f in files):
        return jsonify({'ok': False, 'error': 'no_files'}), 400
    try:
        start_worker = request.headers.get('X-Maint-Batch-Final') == '1'
        queued, skipped = _append_expense_upload_manifest(rec, 'maintenance', files, start_worker=start_worker)
        return jsonify({
            'ok': True,
            'id': rec.id,
            'queued': queued,
            'skipped': skipped,
            'total': int(rec.upload_total or 0),
            'done': int(rec.upload_done or 0),
            'status': rec.upload_status or 'processing',
        })
    except Exception as ex:
        db.session.rollback()
        app.logger.exception('Maintenance queue-files failed expense=%s', pk)
        return jsonify({'ok': False, 'error': str(ex)}), 500


@app.route('/api/maintenance-expense/upload-status/<int:pk>')
def api_maintenance_expense_upload_status(pk):
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    workspace_employee_id = _workspace_employee_id_for_expenses()
    q = MaintenanceExpense.query.filter_by(id=pk)
    if workspace_employee_id:
        q = q.filter_by(employee_id=workspace_employee_id)
    rec = q.first_or_404()
    total = int(rec.upload_total or 0)
    done = int(rec.upload_done or 0)
    failed = int(rec.upload_failed or 0)
    status = (rec.upload_status or ('success' if total == 0 else 'processing')).strip().lower()
    pct = int(round((done / total) * 100)) if total > 0 else 100
    return jsonify({
        'ok': True,
        'id': rec.id,
        'status': status,
        'total': total,
        'done': done,
        'failed': failed,
        'percent': max(0, min(100, pct)),
        'error': (rec.upload_error or ''),
    })


@app.route('/maintenance-expense/<int:pk>/upload-resume', methods=['POST'])
def maintenance_expense_upload_resume(pk):
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    workspace_employee_id = _workspace_employee_id_for_expenses()
    rec = MaintenanceExpense.query.get_or_404(pk)
    if workspace_employee_id and rec.employee_id and rec.employee_id != workspace_employee_id:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    try:
        manifest = json.loads(rec.upload_manifest_json or '[]')
    except Exception:
        manifest = []
    if not manifest:
        return jsonify({'ok': False, 'error': 'nothing_to_resume'})
    rec.upload_status = 'processing'
    rec.upload_error = None
    rec.upload_started_at = pk_now()
    rec.upload_finished_at = None
    db.session.commit()
    started = _start_maintenance_upload_worker(rec.id)
    return jsonify({'ok': True, 'started': bool(started)})


def _next_maintenance_work_order_no(opened_on=None):
    dt = opened_on or pk_date()
    yymm = dt.strftime('%y%m')
    prefix = f"MWO-{yymm}-"
    latest = MaintenanceWorkOrder.query.filter(
        MaintenanceWorkOrder.work_order_no.like(f"{prefix}%")
    ).order_by(MaintenanceWorkOrder.id.desc()).first()
    serial = 1
    if latest and latest.work_order_no:
        try:
            serial = int(str(latest.work_order_no).split('-')[-1]) + 1
        except Exception:
            serial = 1
    return f"{prefix}{serial:04d}"


_maintenance_work_order_schema_ready = {'ok': False}


def _ensure_maintenance_work_order_schema():
    """Safety net for environments where migration is delayed/missed.

    Keeps maintenance pages functional by creating required table/columns if absent.

    NOTE: SQLite does NOT support `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
    (raises "near EXISTS: syntax error") nor `SERIAL`. So we use SQLAlchemy's
    inspector to check existing columns and only add genuinely missing ones,
    which is valid on both SQLite and PostgreSQL.
    """
    if _maintenance_work_order_schema_ready.get('ok'):
        return
    is_sqlite = db.engine.dialect.name == 'sqlite'
    # CREATE TABLE IF NOT EXISTS works on both dialects; SERIAL is PG-only.
    _pk_def = 'INTEGER PRIMARY KEY AUTOINCREMENT' if is_sqlite else 'SERIAL PRIMARY KEY'
    create_stmts = [
        f"""
        CREATE TABLE IF NOT EXISTS maintenance_work_order (
            id {_pk_def},
            work_order_no VARCHAR(40),
            district_id INTEGER NULL,
            project_id INTEGER NULL,
            employee_id INTEGER NULL,
            vehicle_id INTEGER NULL,
            opened_on DATE NULL,
            closed_on DATE NULL,
            work_type VARCHAR(120) NULL,
            title VARCHAR(180) NULL,
            status VARCHAR(20) NULL DEFAULT 'open',
            remarks TEXT NULL,
            created_at TIMESTAMP NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_maintenance_work_order_work_order_no ON maintenance_work_order (work_order_no)",
        f"""
        CREATE TABLE IF NOT EXISTS maintenance_work_order_attachment (
            id {_pk_def},
            work_order_id INTEGER NOT NULL,
            file_path VARCHAR(2048) NOT NULL,
            file_type VARCHAR(20),
            original_name VARCHAR(255),
            created_at TIMESTAMP
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_mwo_attachment_work_order_id ON maintenance_work_order_attachment (work_order_id)",
        "CREATE INDEX IF NOT EXISTS ix_maintenance_expense_work_order_id ON maintenance_expense (work_order_id)",
    ]
    # Columns that should exist (table, column, SQL type). Added only if missing.
    required_columns = [
        ('maintenance_work_order', 'work_order_no', 'VARCHAR(40)'),
        ('maintenance_work_order', 'district_id', 'INTEGER'),
        ('maintenance_work_order', 'project_id', 'INTEGER'),
        ('maintenance_work_order', 'employee_id', 'INTEGER'),
        ('maintenance_work_order', 'vehicle_id', 'INTEGER'),
        ('maintenance_work_order', 'opened_on', 'DATE'),
        ('maintenance_work_order', 'closed_on', 'DATE'),
        ('maintenance_work_order', 'work_type', 'VARCHAR(120)'),
        ('maintenance_work_order', 'title', 'VARCHAR(180)'),
        ('maintenance_work_order', 'status', 'VARCHAR(20)'),
        ('maintenance_work_order', 'remarks', 'TEXT'),
        ('maintenance_work_order', 'created_at', 'TIMESTAMP'),
        ('maintenance_work_order', 'upload_status', 'VARCHAR(20)'),
        ('maintenance_work_order', 'upload_total', 'INTEGER DEFAULT 0'),
        ('maintenance_work_order', 'upload_done', 'INTEGER DEFAULT 0'),
        ('maintenance_work_order', 'upload_failed', 'INTEGER DEFAULT 0'),
        ('maintenance_work_order', 'upload_error', 'TEXT'),
        ('maintenance_work_order', 'upload_manifest_json', 'TEXT'),
        ('maintenance_work_order', 'upload_started_at', 'TIMESTAMP'),
        ('maintenance_work_order', 'upload_finished_at', 'TIMESTAMP'),
        ('maintenance_expense', 'work_order_id', 'INTEGER'),
    ]
    try:
        existing_tables = set(inspect(db.engine).get_table_names())
        # 1) CREATE TABLE / INDEX statements (idempotent on both dialects)
        for stmt in create_stmts:
            db.session.execute(text(stmt))
        db.session.commit()
        # 2) Add genuinely missing columns only (avoids SQLite IF NOT EXISTS gap)
        for _tbl, _col, _coltype in required_columns:
            if _tbl not in existing_tables:
                continue  # table just created above with all columns
            _existing_cols = {c['name'] for c in inspect(db.engine).get_columns(_tbl)}
            if _col not in _existing_cols:
                db.session.execute(text(f'ALTER TABLE {_tbl} ADD COLUMN {_col} {_coltype}'))
        db.session.commit()
        _maintenance_work_order_schema_ready['ok'] = True
    except Exception:
        db.session.rollback()
        app.logger.exception('Maintenance work-order schema safety sync failed')


@app.route('/maintenance-work-orders')
def maintenance_work_order_list():
    _ensure_maintenance_work_order_schema()
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return _guard
    workspace_employee_id = _workspace_employee_id_for_expenses()
    from auth_utils import get_user_context

    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)

    today = pk_date()
    from_d = parse_date(request.args.get('from_date', '').strip()) or today
    to_d = parse_date(request.args.get('to_date', '').strip()) or today
    if from_d > to_d:
        from_d, to_d = to_d, from_d
    status = (request.args.get('status') or '').strip().lower()
    district_id = request.args.get('district_id', type=int) or 0
    project_id = request.args.get('project_id', type=int) or 0
    vehicle_id = request.args.get('vehicle_id', type=int) or 0

    query = MaintenanceWorkOrder.query.filter(
        MaintenanceWorkOrder.opened_on >= from_d,
        MaintenanceWorkOrder.opened_on <= to_d,
    )
    if workspace_employee_id:
        query = query.filter(
            db.or_(
                MaintenanceWorkOrder.employee_id == workspace_employee_id,
                MaintenanceWorkOrder.employee_id.is_(None),
            )
        )
    if not is_master_or_admin:
        if allowed_projects:
            query = query.filter(MaintenanceWorkOrder.project_id.in_(list(allowed_projects)))
        if allowed_districts:
            query = query.filter(MaintenanceWorkOrder.district_id.in_(list(allowed_districts)))
        if allowed_vehicles:
            query = query.filter(MaintenanceWorkOrder.vehicle_id.in_(list(allowed_vehicles)))
    if status in ('open', 'in_progress', 'closed'):
        query = query.filter(MaintenanceWorkOrder.status == status)
    if district_id:
        query = query.filter(MaintenanceWorkOrder.district_id == district_id)
    if project_id:
        query = query.filter(MaintenanceWorkOrder.project_id == project_id)
    if vehicle_id:
        query = query.filter(MaintenanceWorkOrder.vehicle_id == vehicle_id)

    # Note: do not use selectinload(MaintenanceWorkOrder.attachments) — attachments is lazy='dynamic'
    # and SQLAlchemy rejects eager loading on dynamic relationships (500 on this page).
    work_orders = query.order_by(
        MaintenanceWorkOrder.opened_on.desc(), MaintenanceWorkOrder.id.desc()
    ).all()
    from list_visibility import expense_or_work_order_needs_upload_media_columns
    show_upload_media_columns = (
        any(expense_or_work_order_needs_upload_media_columns(wo) for wo in work_orders) if work_orders else False
    )
    rows = []
    for wo in work_orders:
        expenses = wo.expenses.order_by(MaintenanceExpense.expense_date.asc(), MaintenanceExpense.id.asc()).all()
        total_amount = sum(float(e.total_bill_amount or 0) for e in expenses)
        media_count = sum(e.attachments.count() for e in expenses)
        rows.append({
            'rec': wo,
            'bill_count': len(expenses),
            'total_amount': total_amount,
            'media_count': media_count,
        })

    district_q = District.query
    if not is_master_or_admin and allowed_districts:
        district_q = district_q.filter(District.id.in_(list(allowed_districts)))
    project_q = Project.query
    if not is_master_or_admin and allowed_projects:
        project_q = project_q.filter(Project.id.in_(list(allowed_projects)))
    vehicle_q = Vehicle.query
    if not is_master_or_admin and allowed_vehicles:
        vehicle_q = vehicle_q.filter(Vehicle.id.in_(list(allowed_vehicles)))
    d_list = district_q.order_by(District.name).all()
    p_list = project_q.order_by(Project.name).all()
    v_list = vehicle_q.order_by(*vehicle_order_by()).all()
    district_choices = [(0, '-- Select District --')] + [(d.id, d.name) for d in d_list]
    project_choices = [(0, '-- Select Project --')] + [(p.id, p.name) for p in p_list]
    vehicle_choices = [(0, '-- All Vehicles --')] + [(v.id, v.vehicle_no) for v in v_list]
    return render_template(
        'maintenance_work_order_list.html',
        rows=rows,
        from_date=from_d,
        to_date=to_d,
        selected_status=status,
        selected_district_id=district_id,
        selected_project_id=project_id,
        selected_vehicle_id=vehicle_id,
        district_choices=district_choices,
        project_choices=project_choices,
        vehicle_choices=vehicle_choices,
        show_upload_media_columns=show_upload_media_columns,
        location_cascade=_fuel_expense_location_cascade_dict(),
        workspace_employee_id=workspace_employee_id,
    )


@app.route('/maintenance-work-orders/export')
def maintenance_work_order_export():
    _ensure_maintenance_work_order_schema()
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return _guard
    workspace_employee_id = _workspace_employee_id_for_expenses()
    from auth_utils import get_user_context

    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)

    today = pk_date()
    from_d = parse_date(request.args.get('from_date', '').strip()) or today
    to_d = parse_date(request.args.get('to_date', '').strip()) or today
    if from_d > to_d:
        from_d, to_d = to_d, from_d
    status = (request.args.get('status') or '').strip().lower()
    district_id = request.args.get('district_id', type=int) or 0
    project_id = request.args.get('project_id', type=int) or 0
    vehicle_id = request.args.get('vehicle_id', type=int) or 0

    query = MaintenanceWorkOrder.query.filter(
        MaintenanceWorkOrder.opened_on >= from_d,
        MaintenanceWorkOrder.opened_on <= to_d,
    )
    if workspace_employee_id:
        query = query.filter(
            db.or_(
                MaintenanceWorkOrder.employee_id == workspace_employee_id,
                MaintenanceWorkOrder.employee_id.is_(None),
            )
        )
    if not is_master_or_admin:
        if allowed_projects:
            query = query.filter(MaintenanceWorkOrder.project_id.in_(list(allowed_projects)))
        if allowed_districts:
            query = query.filter(MaintenanceWorkOrder.district_id.in_(list(allowed_districts)))
        if allowed_vehicles:
            query = query.filter(MaintenanceWorkOrder.vehicle_id.in_(list(allowed_vehicles)))
    if status in ('open', 'in_progress', 'closed'):
        query = query.filter(MaintenanceWorkOrder.status == status)
    if district_id:
        query = query.filter(MaintenanceWorkOrder.district_id == district_id)
    if project_id:
        query = query.filter(MaintenanceWorkOrder.project_id == project_id)
    if vehicle_id:
        query = query.filter(MaintenanceWorkOrder.vehicle_id == vehicle_id)

    work_orders = query.order_by(MaintenanceWorkOrder.opened_on.desc(), MaintenanceWorkOrder.id.desc()).all()

    status_label = {'open': 'Open', 'in_progress': 'In Progress', 'closed': 'Closed'}
    headers = [
        'Sr', 'Work Order', 'Open Date', 'District', 'Project', 'Vehicle', 'Title', 'Status',
        'Bills', 'Total Cost',
    ]
    data_rows = []
    for i, wo in enumerate(work_orders, 1):
        expenses = wo.expenses.order_by(MaintenanceExpense.expense_date.asc(), MaintenanceExpense.id.asc()).all()
        total_amount = sum(float(e.total_bill_amount or 0) for e in expenses)
        st = (wo.status or '').lower()
        data_rows.append([
            i,
            wo.work_order_no or '',
            wo.opened_on.strftime('%d-%m-%Y') if wo.opened_on else '',
            wo.district.name if wo.district else '-',
            wo.project.name if wo.project else '-',
            wo.vehicle.vehicle_no if wo.vehicle else '-',
            (wo.title or '').replace('\n', ' ').strip(),
            status_label.get(st, st or '-'),
            len(expenses),
            round(total_amount, 2),
        ])

    return generate_excel_template(
        headers,
        data_rows,
        required_columns=[],
        filename=f'maintenance_work_orders_{pk_now().strftime("%Y%m%d_%H%M%S")}.xlsx',
    )


@app.route('/maintenance-work-order/add', methods=['GET', 'POST'])
@app.route('/maintenance-work-order/edit/<int:pk>', methods=['GET', 'POST'])
def maintenance_work_order_form(pk=None):
    _ensure_maintenance_work_order_schema()
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return _guard
    workspace_employee_id = _workspace_employee_id_for_expenses()
    rec = MaintenanceWorkOrder.query.get_or_404(pk) if pk else None
    if rec and workspace_employee_id and rec.employee_id and rec.employee_id != workspace_employee_id:
        flash('This work order does not belong to selected workspace employee.', 'danger')
        return redirect(url_for('maintenance_work_order_list'))

    default_district_id = _workspace_employee_default_district_id(workspace_employee_id)
    default_project_id = _workspace_employee_default_project_id(workspace_employee_id, default_district_id)

    districts = District.query.order_by(District.name.asc()).all()
    if request.method == 'POST':
        district_id = request.form.get('district_id', type=int)
        project_id = request.form.get('project_id', type=int)
        vehicle_id = request.form.get('vehicle_id', type=int)
    elif rec:
        district_id = rec.district_id
        project_id = rec.project_id
        vehicle_id = rec.vehicle_id
    else:
        district_id = default_district_id
        project_id = default_project_id
        vehicle_id = None

    project_q = Project.query
    if district_id:
        project_q = project_q.join(project_district).filter(project_district.c.district_id == district_id)
    projects = project_q.order_by(Project.name.asc()).all()
    vehicle_q = Vehicle.query
    if project_id:
        vehicle_q = vehicle_q.filter(Vehicle.project_id == project_id)
    if district_id:
        vehicle_q = vehicle_q.filter(Vehicle.district_id == district_id)
    vehicles = vehicle_q.order_by(*vehicle_order_by()).all()

    if request.method == 'POST':
        opened_on = parse_date((request.form.get('opened_on') or '').strip()) or pk_date()
        closed_on = parse_date((request.form.get('closed_on') or '').strip())
        status = (request.form.get('status') or 'open').strip().lower()
        if status not in ('open', 'in_progress', 'closed'):
            status = 'open'
        title = (request.form.get('title') or '').strip()
        work_type = (request.form.get('work_type') or '').strip() or None
        remarks = (request.form.get('remarks') or '').strip() or None
        if not vehicle_id:
            flash('Vehicle select karna zaroori hai.', 'danger')
        elif not title:
            flash('Work title required hai.', 'danger')
        else:
            if rec:
                rec.district_id = district_id or None
                rec.project_id = project_id or None
                rec.vehicle_id = vehicle_id
                rec.opened_on = opened_on
                rec.closed_on = closed_on
                rec.status = status
                rec.title = title
                rec.work_type = work_type
                rec.remarks = remarks
            else:
                rec = MaintenanceWorkOrder(
                    work_order_no=_next_maintenance_work_order_no(opened_on),
                    district_id=district_id or None,
                    project_id=project_id or None,
                    employee_id=workspace_employee_id,
                    vehicle_id=vehicle_id,
                    opened_on=opened_on,
                    closed_on=closed_on,
                    status=status,
                    title=title,
                    work_type=work_type,
                    remarks=remarks,
                )
                db.session.add(rec)
            db.session.commit()
            files = request.files.getlist('attachments')
            has_new_files = bool(files and any(f and getattr(f, 'filename', None) for f in files))
            if has_new_files:
                try:
                    manifest, skipped_att = _prepare_work_order_upload_manifest(files, rec.id)
                    rec.upload_total = len(manifest)
                    rec.upload_done = 0
                    rec.upload_failed = 0
                    rec.upload_error = None
                    rec.upload_finished_at = None
                    if manifest:
                        rec.upload_status = 'processing'
                        rec.upload_started_at = pk_now()
                        rec.upload_manifest_json = json.dumps(manifest)
                    else:
                        rec.upload_status = 'success'
                        rec.upload_started_at = None
                        rec.upload_manifest_json = None
                        rec.upload_finished_at = pk_now()
                    db.session.commit()
                    if manifest:
                        _start_work_order_upload_worker(rec.id)
                        flash(f'Work order saved. Upload background me start ho gaya ({len(manifest)} file).', 'success')
                    else:
                        flash('Maintenance work order saved.', 'success')
                    if skipped_att:
                        flash('Kuch files queue me nahi gayin: ' + '; '.join(skipped_att), 'warning')
                except Exception as ex:
                    app.logger.exception('WO upload prep failed: %s', ex)
                    flash('Work order saved lekin files upload nahi ho sakein. Try again.', 'warning')
            else:
                flash('Maintenance work order saved.', 'success')
            return redirect(url_for('maintenance_work_order_detail', pk=rec.id))

    return render_template(
        'maintenance_work_order_form.html',
        rec=rec,
        districts=districts,
        projects=projects,
        vehicles=vehicles,
        selected_district_id=(district_id or 0),
        selected_project_id=(project_id or 0),
        selected_vehicle_id=(vehicle_id or 0),
        location_cascade=_fuel_expense_location_cascade_dict(),
    )


@app.route('/maintenance-work-order/delete/<int:pk>', methods=['POST'])
def maintenance_work_order_delete(pk):
    _ensure_maintenance_work_order_schema()
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return _guard
    workspace_employee_id = _workspace_employee_id_for_expenses()
    rec = MaintenanceWorkOrder.query.get_or_404(pk)
    if workspace_employee_id and rec.employee_id and rec.employee_id != workspace_employee_id:
        flash('This work order does not belong to selected workspace employee.', 'danger')
        return redirect(request.referrer or url_for('maintenance_work_order_list'))
    if rec.expenses.count() > 0:
        flash('Work order delete nahi ho sakta: is par pehle se maintenance bill(s) / invoice link hain. Pehle bills alag karein ya delete karein.', 'danger')
        return redirect(request.referrer or url_for('maintenance_work_order_list'))
    attachment_paths = [att.file_path for att in rec.attachments.all() if att and getattr(att, 'file_path', None)]
    rec_id = rec.id
    initiated_by_user_id = session.get('user_id')
    db.session.delete(rec)
    db.session.commit()
    if attachment_paths and workspace_employee_id:
        _start_expense_delete_cleanup_worker('mwo', rec_id, attachment_paths, employee_id=workspace_employee_id, initiated_by_user_id=initiated_by_user_id)
    flash('Work order delete ho gaya.' + (' Job photos ki files background me saaf ho rahi hain.' if attachment_paths else ''), 'success')
    return redirect(request.referrer or url_for('maintenance_work_order_list'))


@app.route('/maintenance-work-order/<int:pk>/close', methods=['POST'])
def maintenance_work_order_close(pk):
    _ensure_maintenance_work_order_schema()
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return jsonify({'ok': False, 'error': 'Not authorized'}), 403
    workspace_employee_id = _workspace_employee_id_for_expenses()
    rec = MaintenanceWorkOrder.query.get_or_404(pk)
    if workspace_employee_id and rec.employee_id and rec.employee_id != workspace_employee_id:
        return jsonify({'ok': False, 'error': 'Not allowed'}), 403
    close_date_str = (request.json or {}).get('close_date') or ''
    close_date = parse_date(close_date_str) if close_date_str else pk_date()
    rec.status = 'closed'
    rec.closed_on = close_date
    db.session.commit()
    return jsonify({'ok': True, 'work_order_no': rec.work_order_no, 'closed_on': format_date_ddmmyyyy(close_date)})


@app.route('/api/work-order/upload-status/<int:pk>')
def api_work_order_upload_status(pk):
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    workspace_employee_id = _workspace_employee_id_for_expenses()
    q = MaintenanceWorkOrder.query.filter_by(id=pk)
    if workspace_employee_id:
        q = q.filter_by(employee_id=workspace_employee_id)
    rec = q.first_or_404()
    total = int(rec.upload_total or 0)
    done = int(rec.upload_done or 0)
    failed = int(rec.upload_failed or 0)
    status = (rec.upload_status or ('success' if total == 0 else 'processing')).strip().lower()
    pct = int(round((done / total) * 100)) if total > 0 else 100
    return jsonify({
        'ok': True,
        'id': rec.id,
        'status': status,
        'total': total,
        'done': done,
        'failed': failed,
        'percent': max(0, min(100, pct)),
        'error': (rec.upload_error or ''),
    })


@app.route('/maintenance-work-order/<int:pk>/upload-resume', methods=['POST'])
def maintenance_work_order_upload_resume(pk):
    _ensure_maintenance_work_order_schema()
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    workspace_employee_id = _workspace_employee_id_for_expenses()
    rec = MaintenanceWorkOrder.query.get_or_404(pk)
    if workspace_employee_id and rec.employee_id and rec.employee_id != workspace_employee_id:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    try:
        manifest = json.loads(rec.upload_manifest_json or '[]')
    except Exception:
        manifest = []
    if not manifest:
        return jsonify({'ok': False, 'error': 'nothing_to_resume'}), 400
    rec.upload_status = 'processing'
    rec.upload_error = None
    rec.upload_started_at = pk_now()
    rec.upload_finished_at = None
    db.session.commit()
    started = _start_work_order_upload_worker(rec.id)
    return jsonify({'ok': True, 'started': bool(started)})


@app.route('/maintenance-work-order/<int:pk>')
def maintenance_work_order_detail(pk):
    _ensure_maintenance_work_order_schema()
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return _guard
    workspace_employee_id = _workspace_employee_id_for_expenses()
    rec = MaintenanceWorkOrder.query.get_or_404(pk)
    if workspace_employee_id and rec.employee_id and rec.employee_id != workspace_employee_id:
        flash('This work order does not belong to selected workspace employee.', 'danger')
        return redirect(url_for('maintenance_work_order_list'))
    expenses = rec.expenses.order_by(MaintenanceExpense.expense_date.asc(), MaintenanceExpense.id.asc()).all()
    total_bill = sum(float(x.total_bill_amount or 0) for x in expenses)
    total_media = sum(x.attachments.count() for x in expenses)
    wo_media = rec.attachments.count()
    from urllib.parse import urlencode
    mwo_preserve_qs = urlencode(request.args) if request.args else None
    return render_template(
        'maintenance_work_order_detail.html',
        rec=rec,
        expenses=expenses,
        total_bill=total_bill,
        total_media=total_media,
        wo_media=wo_media,
        mwo_preserve_qs=mwo_preserve_qs,
    )


@app.route('/maintenance-work-order/<int:pk>/invoices')
def maintenance_work_order_invoices(pk):
    """Consolidated WO + all linked maintenance bills (invoice bodies) on one page."""
    _ensure_maintenance_work_order_schema()
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return _guard
    workspace_employee_id = _workspace_employee_id_for_expenses()
    rec = MaintenanceWorkOrder.query.get_or_404(pk)
    if workspace_employee_id and rec.employee_id and rec.employee_id != workspace_employee_id:
        flash('This work order does not belong to selected workspace employee.', 'danger')
        return redirect(url_for('maintenance_work_order_list'))
    expenses = rec.expenses.order_by(MaintenanceExpense.expense_date.asc(), MaintenanceExpense.id.asc()).all()
    total_bill = sum(float(x.total_bill_amount or 0) for x in expenses)
    total_media = sum(x.attachments.count() for x in expenses)
    wo_media = rec.attachments.count()
    from urllib.parse import urlencode
    mwo_preserve_qs = urlencode(request.args) if request.args else None
    return render_template(
        'maintenance_work_order_invoices.html',
        rec=rec,
        expenses=expenses,
        total_bill=total_bill,
        total_media=total_media,
        wo_media=wo_media,
        mwo_preserve_qs=mwo_preserve_qs,
        this_page_path=request.full_path,
    )


@app.route('/maintenance-work-order/<int:pk>/invoices/export')
def maintenance_work_order_invoices_export(pk):
    _ensure_maintenance_work_order_schema()
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return _guard
    workspace_employee_id = _workspace_employee_id_for_expenses()
    wo = MaintenanceWorkOrder.query.get_or_404(pk)
    if workspace_employee_id and wo.employee_id and wo.employee_id != workspace_employee_id:
        flash('This work order does not belong to selected workspace employee.', 'danger')
        return redirect(url_for('maintenance_work_order_list'))
    expenses = wo.expenses.order_by(MaintenanceExpense.expense_date.asc(), MaintenanceExpense.id.asc()).all()
    headers = [
        'Work Order', 'Bill No', 'Date', 'Party', 'Payment', 'Job category', 'Amount', 'Line items (count)',
    ]
    data_rows = []
    for e in expenses:
        line_ct = e.items.count() if e.items else 0
        data_rows.append([
            wo.work_order_no or '',
            f'MAINT-{e.id}',
            e.expense_date.strftime('%d-%m-%Y') if e.expense_date else '',
            e.workspace_party.name if e.workspace_party else '',
            e.payment_type or '',
            e.job_category or '',
            round(float(e.total_bill_amount or 0), 2),
            line_ct,
        ])
    return generate_excel_template(
        headers,
        data_rows,
        required_columns=[],
        filename=f'wo_{wo.work_order_no or pk}_bills_{pk_now().strftime("%Y%m%d_%H%M%S")}.xlsx',
    )


@app.route('/maintenance-work-order/<int:pk>/media/download/<int:att_id>')
def maintenance_work_order_media_download(pk, att_id):
    _ensure_maintenance_work_order_schema()
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return _guard
    workspace_employee_id = _workspace_employee_id_for_expenses()
    wo = MaintenanceWorkOrder.query.get_or_404(pk)
    if workspace_employee_id and wo.employee_id and wo.employee_id != workspace_employee_id:
        flash('This work order does not belong to selected workspace employee.', 'danger')
        return redirect(url_for('maintenance_work_order_list'))
    att = MaintenanceWorkOrderAttachment.query.filter_by(id=att_id, work_order_id=wo.id).first()
    if not att:
        flash('Attachment not found.', 'warning')
        return redirect(url_for('maintenance_work_order_detail', pk=pk))
    dl_name = _maintenance_attachment_download_name(att)
    local_full = _maintenance_attachment_local_full_path(att.file_path or '')
    if local_full:
        return send_file(local_full, as_attachment=True, download_name=dl_name, conditional=True, max_age=0)
    try:
        blob, mime = _maintenance_attachment_read_bytes(att.file_path or '')
    except Exception as ex:
        app.logger.warning('WO media download failed (%s): %s', att.id, ex)
        flash('Download failed for this attachment.', 'danger')
        return redirect(url_for('maintenance_work_order_unified_media', pk=pk))
    if not blob:
        flash('Attachment file is empty.', 'warning')
        return redirect(url_for('maintenance_work_order_unified_media', pk=pk))
    return send_file(BytesIO(blob), as_attachment=True, download_name=dl_name, mimetype=(mime or 'application/octet-stream'), max_age=0)


def _mwo_unified_gallery_build_items(wo):
    """Build combined media_items for bill + WO attachments (same shape as maintenance_expense_media)."""

    def _human_size(n):
        if n is None:
            return ''
        size = float(n)
        units = ['B', 'KB', 'MB', 'GB', 'TB']
        idx = 0
        while size >= 1024 and idx < len(units) - 1:
            size /= 1024.0
            idx += 1
        if idx == 0:
            return f"{int(size)} {units[idx]}"
        return f"{size:.1f} {units[idx]}"

    def _local_sz(stored_path):
        if not stored_path:
            return None
        p = str(stored_path).strip()
        if p.startswith('http://') or p.startswith('https://'):
            return None
        upload_root = os.path.abspath(app.config.get('UPLOAD_FOLDER', ''))
        if not upload_root:
            return None
        rel = p.replace('\\', '/').lstrip('/')
        if rel.startswith('uploads/'):
            rel = rel[len('uploads/'):]
        full = os.path.abspath(os.path.join(upload_root, rel.replace('/', os.sep)))
        if not full.startswith(upload_root):
            return None
        try:
            return os.path.getsize(full)
        except OSError:
            return None

    def _local_fp(stored_path):
        if not stored_path:
            return None
        p = str(stored_path).strip()
        if p.startswith('http://') or p.startswith('https://'):
            return None
        upload_root = os.path.abspath(app.config.get('UPLOAD_FOLDER', ''))
        if not upload_root:
            return None
        rel = p.replace('\\', '/').lstrip('/')
        if rel.startswith('uploads/'):
            rel = rel[len('uploads/'):]
        full = os.path.abspath(os.path.join(upload_root, rel.replace('/', os.sep)))
        if not full.startswith(upload_root):
            return None
        return full if os.path.isfile(full) else None

    media_items = []
    expenses = wo.expenses.order_by(MaintenanceExpense.expense_date.asc(), MaintenanceExpense.id.asc()).all()
    for exp in expenses:
        for att in exp.attachments.order_by(MaintenanceExpenseAttachment.created_at.asc(), MaintenanceExpenseAttachment.id.asc()).all():
            url = media_url_filter(att.file_path or '')
            if not url:
                continue
            ftype = (att.file_type or '').strip().lower()
            if ftype not in ('image', 'video'):
                path = (att.file_path or '').lower()
                if any(path.endswith(x) for x in ('.mp4', '.webm', '.mov')):
                    ftype = 'video'
                else:
                    ftype = 'image'
            size_bytes = _local_sz(att.file_path or '')
            created_at = att.created_at
            label = f"Bill MAINT-{exp.id}"
            media_items.append({
                'url': url,
                'type': ftype,
                'name': f"{label} — {att.original_name or os.path.basename(att.file_path or '') or 'Attachment'}",
                'created_at': created_at.strftime('%d-%m-%Y %I:%M %p') if created_at else '',
                'created_at_iso': created_at.isoformat() if created_at else '',
                'size_bytes': size_bytes,
                'size_label': _human_size(size_bytes),
                'download_url': url_for('maintenance_expense_media_download', pk=exp.id, att_id=att.id),
                'is_local_file': bool(_local_fp(att.file_path or '')),
            })
    wo_start = len(media_items)
    for att in wo.attachments.order_by(MaintenanceWorkOrderAttachment.created_at.asc(), MaintenanceWorkOrderAttachment.id.asc()).all():
        url = media_url_filter(att.file_path or '')
        if not url:
            continue
        ftype = (att.file_type or '').strip().lower()
        if ftype not in ('image', 'video'):
            path = (att.file_path or '').lower()
            if any(path.endswith(x) for x in ('.mp4', '.webm', '.mov')):
                ftype = 'video'
            else:
                ftype = 'image'
        size_bytes = _local_sz(att.file_path or '')
        created_at = att.created_at
        media_items.append({
            'url': url,
            'type': ftype,
            'name': f"WO {wo.work_order_no or ''} — {att.original_name or os.path.basename(att.file_path or '') or 'Attachment'}",
            'created_at': created_at.strftime('%d-%m-%Y %I:%M %p') if created_at else '',
            'created_at_iso': created_at.isoformat() if created_at else '',
            'size_bytes': size_bytes,
            'size_label': _human_size(size_bytes),
            'download_url': url_for('maintenance_work_order_media_download', pk=wo.id, att_id=att.id),
            'is_local_file': bool(_local_fp(att.file_path or '')),
        })
    return media_items, wo_start


def _mwo_job_gallery_build_items(wo):
    def _human_size(n):
        if n is None:
            return ''
        size = float(n)
        units = ['B', 'KB', 'MB', 'GB', 'TB']
        idx = 0
        while size >= 1024 and idx < len(units) - 1:
            size /= 1024.0
            idx += 1
        if idx == 0:
            return f"{int(size)} {units[idx]}"
        return f"{size:.1f} {units[idx]}"

    def _local_sz(stored_path):
        if not stored_path:
            return None
        p = str(stored_path).strip()
        if p.startswith('http://') or p.startswith('https://'):
            return None
        upload_root = os.path.abspath(app.config.get('UPLOAD_FOLDER', ''))
        if not upload_root:
            return None
        rel = p.replace('\\', '/').lstrip('/')
        if rel.startswith('uploads/'):
            rel = rel[len('uploads/'):]
        full = os.path.abspath(os.path.join(upload_root, rel.replace('/', os.sep)))
        if not full.startswith(upload_root):
            return None
        try:
            return os.path.getsize(full)
        except OSError:
            return None

    def _local_fp(stored_path):
        if not stored_path:
            return None
        p = str(stored_path).strip()
        if p.startswith('http://') or p.startswith('https://'):
            return None
        upload_root = os.path.abspath(app.config.get('UPLOAD_FOLDER', ''))
        if not upload_root:
            return None
        rel = p.replace('\\', '/').lstrip('/')
        if rel.startswith('uploads/'):
            rel = rel[len('uploads/'):]
        full = os.path.abspath(os.path.join(upload_root, rel.replace('/', os.sep)))
        if not full.startswith(upload_root):
            return None
        return full if os.path.isfile(full) else None

    media_items = []
    for att in wo.attachments.order_by(MaintenanceWorkOrderAttachment.created_at.asc(), MaintenanceWorkOrderAttachment.id.asc()).all():
        url = media_url_filter(att.file_path or '')
        if not url:
            continue
        ftype = (att.file_type or '').strip().lower()
        if ftype not in ('image', 'video'):
            path = (att.file_path or '').lower()
            if any(path.endswith(x) for x in ('.mp4', '.webm', '.mov')):
                ftype = 'video'
            else:
                ftype = 'image'
        size_bytes = _local_sz(att.file_path or '')
        created_at = att.created_at
        media_items.append({
            'url': url,
            'type': ftype,
            'name': att.original_name or os.path.basename(att.file_path or '') or 'Attachment',
            'created_at': created_at.strftime('%d-%m-%Y %I:%M %p') if created_at else '',
            'created_at_iso': created_at.isoformat() if created_at else '',
            'size_bytes': size_bytes,
            'size_label': _human_size(size_bytes),
            'download_url': url_for('maintenance_work_order_media_download', pk=wo.id, att_id=att.id),
            'is_local_file': bool(_local_fp(att.file_path or '')),
        })
    return media_items


@app.route('/maintenance-work-order/<int:pk>/all-media')
def maintenance_work_order_unified_media(pk):
    _ensure_maintenance_work_order_schema()
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return _guard
    workspace_employee_id = _workspace_employee_id_for_expenses()
    wo = MaintenanceWorkOrder.query.get_or_404(pk)
    if workspace_employee_id and wo.employee_id and wo.employee_id != workspace_employee_id:
        flash('This work order does not belong to selected workspace employee.', 'danger')
        return redirect(url_for('maintenance_work_order_list'))
    default_back = url_for('maintenance_work_order_detail', pk=pk)
    back_url = _safe_internal_path(request.args.get('return_to'), default_back)
    media_items, wo_start_index = _mwo_unified_gallery_build_items(wo)
    return render_template(
        'maintenance_work_order_unified_media.html',
        rec=wo,
        media_items=media_items,
        back_url=back_url,
        wo_start_index=wo_start_index,
        media_title='Work order — all media (bills + job photos)',
        media_date_label=(wo.opened_on.strftime('%d-%m-%Y') if wo.opened_on else '-'),
    )


@app.route('/maintenance-work-order/<int:pk>/job-media')
def maintenance_work_order_job_media(pk):
    _ensure_maintenance_work_order_schema()
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return _guard
    workspace_employee_id = _workspace_employee_id_for_expenses()
    wo = MaintenanceWorkOrder.query.get_or_404(pk)
    if workspace_employee_id and wo.employee_id and wo.employee_id != workspace_employee_id:
        flash('This work order does not belong to selected workspace employee.', 'danger')
        return redirect(url_for('maintenance_work_order_list'))
    default_back = url_for('maintenance_work_order_detail', pk=pk)
    back_url = _safe_internal_path(request.args.get('return_to'), default_back)
    media_items = _mwo_job_gallery_build_items(wo)
    return render_template(
        'maintenance_expense_media.html',
        rec=wo,
        media_items=media_items,
        back_url=back_url,
        media_title='Work order job photos / videos',
        media_date_label=(wo.opened_on.strftime('%d-%m-%Y') if wo.opened_on else None),
        show_download_all=False,
    )


@app.route('/maintenance-expenses')
def maintenance_expense_list():
    _ensure_maintenance_work_order_schema()
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return _guard
    workspace_employee_id = _workspace_employee_id_for_expenses()
    from auth_utils import get_user_context
    
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)
    
    form = MaintenanceExpenseFilterForm()
    
    # Filter dropdown choices by user scope
    district_q = District.query
    if not is_master_or_admin and allowed_districts:
        district_q = district_q.filter(District.id.in_(list(allowed_districts)))
    form.district_id.choices = [(0, '-- Select District --')] + [(d.id, d.name) for d in district_q.order_by(District.name).all()]
    
    project_q = Project.query
    if not is_master_or_admin and allowed_projects:
        project_q = project_q.filter(Project.id.in_(list(allowed_projects)))
    form.project_id.choices = [(0, '-- Select Project --')] + [(p.id, p.name) for p in project_q.order_by(Project.name).all()]
    
    vehicle_q = Vehicle.query
    if not is_master_or_admin and allowed_vehicles:
        vehicle_q = vehicle_q.filter(Vehicle.id.in_(list(allowed_vehicles)))
    form.vehicle_id.choices = [(0, '-- All Vehicles --')] + [(v.id, v.vehicle_no) for v in vehicle_q.order_by(*vehicle_order_by()).all()]
    today = pk_date()
    from_date = request.args.get('from_date', '').strip()
    to_date = request.args.get('to_date', '').strip()
    district_id = request.args.get('district_id', type=int) or 0
    project_id = request.args.get('project_id', type=int) or 0
    vehicle_id = request.args.get('vehicle_id', type=int) or 0
    work_order_no = (request.args.get('work_order_no') or '').strip()
    from_d = parse_date(from_date) if from_date else today
    to_d = parse_date(to_date) if to_date else today
    if not from_d:
        from_d = today
    if not to_d:
        to_d = today
    if from_d > to_d:
        from_d, to_d = to_d, from_d
    form.from_date.data = from_d
    form.to_date.data = to_d
    form.district_id.data = district_id
    form.project_id.data = project_id
    form.vehicle_id.data = vehicle_id

    query = MaintenanceExpense.query.filter(
        MaintenanceExpense.expense_date >= from_d,
        MaintenanceExpense.expense_date <= to_d
    )
    if workspace_employee_id:
        query = query.filter(
            db.or_(
                MaintenanceExpense.employee_id == workspace_employee_id,
                MaintenanceExpense.employee_id.is_(None),
            )
        )

    # Apply user data scope
    if not is_master_or_admin:
        if allowed_projects:
            query = query.filter(MaintenanceExpense.project_id.in_(list(allowed_projects)))
        if allowed_districts:
            query = query.filter(MaintenanceExpense.district_id.in_(list(allowed_districts)))
        if allowed_vehicles:
            query = query.filter(MaintenanceExpense.vehicle_id.in_(list(allowed_vehicles)))

    if district_id:
        query = query.filter(MaintenanceExpense.district_id == district_id)
    if project_id:
        query = query.filter(MaintenanceExpense.project_id == project_id)
    if vehicle_id:
        query = query.filter(MaintenanceExpense.vehicle_id == vehicle_id)
    if work_order_no:
        query = query.join(
            MaintenanceWorkOrder,
            MaintenanceWorkOrder.id == MaintenanceExpense.work_order_id,
        ).filter(MaintenanceWorkOrder.work_order_no.ilike(f"%{work_order_no}%"))
    rows = query.order_by(
        MaintenanceExpense.expense_date.asc(),
        db.case((MaintenanceExpense.current_reading.is_(None), 1), else_=0).asc(),
        MaintenanceExpense.current_reading.asc(),
        MaintenanceExpense.id.asc(),
    ).all()
    from list_visibility import expense_or_work_order_needs_upload_media_columns
    show_upload_media_columns = (
        any(expense_or_work_order_needs_upload_media_columns(r) for r in rows) if rows else False
    )
    rows_with_totals = []
    overall_total_qty = 0
    overall_total_amount = 0
    overall_total_bill = 0
    for r in rows:
        total_qty = sum(float(it.qty or 0) for it in r.items)
        total_amount = sum(float(it.amount or 0) for it in r.items)
        total_bill = float(r.total_bill_amount or 0)
        rows_with_totals.append({'rec': r, 'total_qty': total_qty, 'total_amount': total_amount})
        overall_total_qty += total_qty
        overall_total_amount += total_amount
        overall_total_bill += total_bill
    totals = {
        'count': len(rows),
        'total_qty': overall_total_qty,
        'total_amount': overall_total_amount,
        'total_bill': overall_total_bill
    }
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    pagination = SimplePagination(rows_with_totals, page, per_page)
    rows_with_totals = pagination.items
    # Page subtotals
    page_subtotal_qty = sum(item['total_qty'] for item in rows_with_totals)
    page_subtotal_amount = sum(item['total_amount'] for item in rows_with_totals)
    page_subtotal_bill = sum(float(item['rec'].total_bill_amount or 0) for item in rows_with_totals)
    cleanup_status = _latest_expense_cleanup_status('maintenance', workspace_employee_id)
    wo_q = MaintenanceWorkOrder.query.filter(MaintenanceWorkOrder.status != 'closed')
    if workspace_employee_id:
        wo_q = wo_q.filter(
            db.or_(
                MaintenanceWorkOrder.employee_id == workspace_employee_id,
                MaintenanceWorkOrder.employee_id.is_(None),
            )
        )
    if not is_master_or_admin:
        if allowed_projects:
            wo_q = wo_q.filter(MaintenanceWorkOrder.project_id.in_(list(allowed_projects)))
        if allowed_districts:
            wo_q = wo_q.filter(MaintenanceWorkOrder.district_id.in_(list(allowed_districts)))
        if allowed_vehicles:
            wo_q = wo_q.filter(MaintenanceWorkOrder.vehicle_id.in_(list(allowed_vehicles)))
    open_work_orders = wo_q.order_by(MaintenanceWorkOrder.opened_on.desc(), MaintenanceWorkOrder.id.desc()).limit(200).all()
    return render_template(
        'maintenance_expense_list.html',
        form=form,
        rows=rows_with_totals,
        from_date=from_d,
        to_date=to_d,
        work_order_no=work_order_no,
        totals=totals,
        pagination=pagination,
        per_page=per_page,
        cleanup_status=cleanup_status,
        open_work_orders=open_work_orders,
        show_upload_media_columns=show_upload_media_columns,
        location_cascade=_fuel_expense_location_cascade_dict(),
        workspace_employee_id=workspace_employee_id,
    )


@app.route('/maintenance-expenses/export')
def maintenance_expense_export():
    _ensure_maintenance_work_order_schema()
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return _guard
    workspace_employee_id = _workspace_employee_id_for_expenses()
    from auth_utils import get_user_context

    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)

    today = pk_date()
    from_date = request.args.get('from_date', '').strip()
    to_date = request.args.get('to_date', '').strip()
    district_id = request.args.get('district_id', type=int) or 0
    project_id = request.args.get('project_id', type=int) or 0
    vehicle_id = request.args.get('vehicle_id', type=int) or 0
    work_order_no = (request.args.get('work_order_no') or '').strip()

    from_d = parse_date(from_date) if from_date else today
    to_d = parse_date(to_date) if to_date else today
    if not from_d:
        from_d = today
    if not to_d:
        to_d = today
    if from_d > to_d:
        from_d, to_d = to_d, from_d

    query = MaintenanceExpense.query.filter(
        MaintenanceExpense.expense_date >= from_d,
        MaintenanceExpense.expense_date <= to_d
    )
    if workspace_employee_id:
        query = query.filter(
            db.or_(
                MaintenanceExpense.employee_id == workspace_employee_id,
                MaintenanceExpense.employee_id.is_(None),
            )
        )

    if not is_master_or_admin:
        if allowed_projects:
            query = query.filter(MaintenanceExpense.project_id.in_(list(allowed_projects)))
        if allowed_districts:
            query = query.filter(MaintenanceExpense.district_id.in_(list(allowed_districts)))
        if allowed_vehicles:
            query = query.filter(MaintenanceExpense.vehicle_id.in_(list(allowed_vehicles)))

    if district_id:
        query = query.filter(MaintenanceExpense.district_id == district_id)
    if project_id:
        query = query.filter(MaintenanceExpense.project_id == project_id)
    if vehicle_id:
        query = query.filter(MaintenanceExpense.vehicle_id == vehicle_id)
    if work_order_no:
        query = query.join(
            MaintenanceWorkOrder,
            MaintenanceWorkOrder.id == MaintenanceExpense.work_order_id,
        ).filter(MaintenanceWorkOrder.work_order_no.ilike(f"%{work_order_no}%"))

    rows = query.order_by(
        MaintenanceExpense.expense_date.asc(),
        db.case((MaintenanceExpense.current_reading.is_(None), 1), else_=0).asc(),
        MaintenanceExpense.current_reading.asc(),
        MaintenanceExpense.id.asc(),
    ).all()

    headers = [
        'Sr', 'District', 'Project', 'Vehicle', 'Work Order', 'Date', 'Job Category',
        'Current Reading', 'Items', 'Total Qty', 'Amount', 'Payment Type', 'Party Name', 'Total Bill'
    ]
    data_rows = []
    for i, r in enumerate(rows, 1):
        total_qty = sum(float(it.qty or 0) for it in r.items)
        total_amount = sum(float(it.amount or 0) for it in r.items)
        item_names = []
        for it in r.items:
            nm = (it.product.name if it.product else '').strip()
            nm = re.sub(r'\s+', ' ', nm).strip().strip(',')
            if nm:
                item_names.append(nm)
        items_text = ','.join(item_names) if item_names else '-'
        data_rows.append([
            i,
            r.district.name if r.district else '-',
            r.project.name if r.project else '-',
            r.vehicle.vehicle_no if r.vehicle else '-',
            r.work_order.work_order_no if r.work_order else '-',
            r.expense_date.strftime('%d-%m-%Y') if r.expense_date else '-',
            r.job_category or '-',
            float(r.current_reading) if r.current_reading is not None else '',
            items_text,
            round(total_qty, 2),
            round(total_amount, 2),
            r.payment_type or '-',
            r.workspace_party.name if r.workspace_party else '-',
            float(r.total_bill_amount or 0),
        ])

    return generate_excel_template(
        headers,
        data_rows,
        required_columns=[],
        filename=f'maintenance_expense_{pk_now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    )


@app.route('/maintenance-expenses/history')
def maintenance_expense_history():
    _ensure_maintenance_work_order_schema()
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return _guard
    workspace_employee_id = _workspace_employee_id_for_expenses()
    from auth_utils import get_user_context

    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)

    form = MaintenanceExpenseFilterForm()
    district_q = District.query
    if not is_master_or_admin and allowed_districts:
        district_q = district_q.filter(District.id.in_(list(allowed_districts)))
    form.district_id.choices = [(0, '-- All Districts --')] + [(d.id, d.name) for d in district_q.order_by(District.name).all()]

    project_q = Project.query
    if not is_master_or_admin and allowed_projects:
        project_q = project_q.filter(Project.id.in_(list(allowed_projects)))
    form.project_id.choices = [(0, '-- All Projects --')] + [(p.id, p.name) for p in project_q.order_by(Project.name).all()]

    vehicle_q = Vehicle.query
    if not is_master_or_admin and allowed_vehicles:
        vehicle_q = vehicle_q.filter(Vehicle.id.in_(list(allowed_vehicles)))
    form.vehicle_id.choices = [(0, '-- All Vehicles --')] + [(v.id, v.vehicle_no) for v in vehicle_q.order_by(*vehicle_order_by()).all()]

    products_for_maintenance = _workspace_products_for_expense_form(workspace_employee_id, 'Maintenance')
    product_choices = [(0, '-- All Products --')] + [(p.id, p.name) for p in products_for_maintenance]

    today = pk_date()
    from_date = request.args.get('from_date', '').strip()
    to_date = request.args.get('to_date', '').strip()
    district_id = request.args.get('district_id', type=int) or 0
    project_id = request.args.get('project_id', type=int) or 0
    vehicle_id = request.args.get('vehicle_id', type=int) or 0
    product_id = request.args.get('product_id', type=int) or 0

    from_d = parse_date(from_date) if from_date else (today - timedelta(days=90))
    to_d = parse_date(to_date) if to_date else today
    if not from_d:
        from_d = today - timedelta(days=90)
    if not to_d:
        to_d = today
    if from_d > to_d:
        from_d, to_d = to_d, from_d

    form.from_date.data = from_d
    form.to_date.data = to_d
    form.district_id.data = district_id
    form.project_id.data = project_id
    form.vehicle_id.data = vehicle_id

    query = MaintenanceExpense.query.options(
        joinedload(MaintenanceExpense.district),
        joinedload(MaintenanceExpense.project),
        joinedload(MaintenanceExpense.vehicle),
        joinedload(MaintenanceExpense.workspace_party),
    ).filter(
        MaintenanceExpense.expense_date >= from_d,
        MaintenanceExpense.expense_date <= to_d
    )
    if workspace_employee_id:
        query = query.filter(
            db.or_(
                MaintenanceExpense.employee_id == workspace_employee_id,
                MaintenanceExpense.employee_id.is_(None),
            )
        )
    if not is_master_or_admin:
        if allowed_projects:
            query = query.filter(MaintenanceExpense.project_id.in_(list(allowed_projects)))
        if allowed_districts:
            query = query.filter(MaintenanceExpense.district_id.in_(list(allowed_districts)))
        if allowed_vehicles:
            query = query.filter(MaintenanceExpense.vehicle_id.in_(list(allowed_vehicles)))
    if district_id:
        query = query.filter(MaintenanceExpense.district_id == district_id)
    if project_id:
        query = query.filter(MaintenanceExpense.project_id == project_id)
    if vehicle_id:
        query = query.filter(MaintenanceExpense.vehicle_id == vehicle_id)
    if product_id:
        query = query.join(MaintenanceExpenseItem, MaintenanceExpenseItem.maintenance_expense_id == MaintenanceExpense.id)
        query = query.filter(MaintenanceExpenseItem.product_id == product_id)

    rows = query.order_by(MaintenanceExpense.expense_date.desc(), MaintenanceExpense.id.desc()).all()
    invoice_ids = [r.id for r in rows]
    repeat_map = {}
    if invoice_ids:
        repeat_rows = db.session.query(
            MaintenanceExpense.vehicle_id,
            MaintenanceExpenseItem.product_id,
            db.func.count(db.distinct(MaintenanceExpense.id)).label('changed_count')
        ).join(
            MaintenanceExpenseItem, MaintenanceExpenseItem.maintenance_expense_id == MaintenanceExpense.id
        ).filter(
            MaintenanceExpense.id.in_(invoice_ids)
        ).group_by(
            MaintenanceExpense.vehicle_id,
            MaintenanceExpenseItem.product_id
        ).all()
        repeat_map = {
            (int(x.vehicle_id or 0), int(x.product_id or 0)): int(x.changed_count or 0)
            for x in repeat_rows
        }

    rows_with_meta = []
    total_bill = 0.0
    total_qty = 0.0
    total_lines = 0
    for r in rows:
        item_rows = r.items.order_by(MaintenanceExpenseItem.sort_order.asc(), MaintenanceExpenseItem.id.asc()).all()
        detail_items = []
        invoice_qty = 0.0
        invoice_amount = 0.0
        max_repeat = 0
        for it in item_rows:
            qty = float(it.qty or 0)
            price = float(it.price or 0)
            amount = float(it.amount or (qty * price))
            invoice_qty += qty
            invoice_amount += amount
            repeat_count = repeat_map.get((int(r.vehicle_id or 0), int(it.product_id or 0)), 0)
            if repeat_count > max_repeat:
                max_repeat = repeat_count
            detail_items.append({
                'product_name': it.product.name if it.product else f'Product #{it.product_id}',
                'qty_label': f'{qty:.2f}',
                'price_label': f'{price:.2f}',
                'amount_label': f'{amount:.2f}',
                'repeat_count': repeat_count,
            })
        if r.total_bill_amount is None:
            row_bill = invoice_amount
        else:
            row_bill = float(r.total_bill_amount or 0)
        total_bill += row_bill
        total_qty += invoice_qty
        total_lines += len(detail_items)
        rows_with_meta.append({
            'rec': r,
            'items': detail_items,
            'invoice_qty': invoice_qty,
            'invoice_amount': invoice_amount,
            'bill_amount': row_bill,
            'max_repeat': max_repeat,
        })

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)
    pagination = SimplePagination(rows_with_meta, page, per_page)
    rows_with_meta = pagination.items

    repeat_summary = sorted(
        [
            {'vehicle_id': v_id, 'product_id': p_id, 'changed_count': changed_count}
            for (v_id, p_id), changed_count in repeat_map.items()
        ],
        key=lambda x: x['changed_count'],
        reverse=True,
    )[:10]
    product_name_map = {p.id: p.name for p in products_for_maintenance}
    vehicle_name_map = {v.id: v.vehicle_no for v in Vehicle.query.filter(Vehicle.id.in_([x['vehicle_id'] for x in repeat_summary])).all()} if repeat_summary else {}
    for item in repeat_summary:
        item['vehicle_no'] = vehicle_name_map.get(item['vehicle_id'], f"Vehicle #{item['vehicle_id']}")
        item['product_name'] = product_name_map.get(item['product_id'], f"Product #{item['product_id']}")

    return render_template(
        'maintenance_expense_history.html',
        title='Maintenance History Report',
        form=form,
        rows=rows_with_meta,
        from_date=from_d,
        to_date=to_d,
        district_id=district_id,
        project_id=project_id,
        vehicle_id=vehicle_id,
        product_id=product_id,
        product_choices=product_choices,
        totals={
            'invoice_count': len(rows),
            'total_qty': total_qty,
            'total_bill': total_bill,
            'total_lines': total_lines,
        },
        repeat_summary=repeat_summary,
        pagination=pagination,
        per_page=per_page,
    )


@app.route('/maintenance-baseline-alert-report')
def maintenance_baseline_alert_report():
    _ensure_vehicle_maintenance_baseline_schema()
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return _guard
    workspace_employee_id = _workspace_employee_id_for_expenses()
    from auth_utils import get_user_context

    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)

    form = MaintenanceExpenseFilterForm()
    district_q = District.query
    if not is_master_or_admin and allowed_districts:
        district_q = district_q.filter(District.id.in_(list(allowed_districts)))
    form.district_id.choices = [(0, '-- All Districts --')] + [(d.id, d.name) for d in district_q.order_by(District.name).all()]

    project_q = Project.query
    if not is_master_or_admin and allowed_projects:
        project_q = project_q.filter(Project.id.in_(list(allowed_projects)))
    form.project_id.choices = [(0, '-- All Projects --')] + [(p.id, p.name) for p in project_q.order_by(Project.name).all()]

    vehicle_q = Vehicle.query
    if not is_master_or_admin and allowed_vehicles:
        vehicle_q = vehicle_q.filter(Vehicle.id.in_(list(allowed_vehicles)))
    form.vehicle_id.choices = [(0, '-- All Vehicles --')] + [(v.id, v.vehicle_no) for v in vehicle_q.order_by(*vehicle_order_by()).all()]

    job_category_choices = sorted({(j.get('name') or '').strip() for j in (_get_maintenance_job_categories() or []) if (j.get('name') or '').strip()})

    district_id = request.args.get('district_id', type=int) or 0
    project_id = request.args.get('project_id', type=int) or 0
    vehicle_id = request.args.get('vehicle_id', type=int) or 0
    job_category = (request.args.get('job_category') or '').strip()
    status = (request.args.get('status') or 'all').strip().lower()

    q = WorkspaceVehicleMaintenanceBaseline.query.options(
        joinedload(WorkspaceVehicleMaintenanceBaseline.district),
        joinedload(WorkspaceVehicleMaintenanceBaseline.project),
        joinedload(WorkspaceVehicleMaintenanceBaseline.vehicle),
    ).filter(WorkspaceVehicleMaintenanceBaseline.employee_id == workspace_employee_id)

    if not is_master_or_admin:
        if allowed_projects:
            q = q.filter(WorkspaceVehicleMaintenanceBaseline.project_id.in_(list(allowed_projects)))
        if allowed_districts:
            q = q.filter(WorkspaceVehicleMaintenanceBaseline.district_id.in_(list(allowed_districts)))
        if allowed_vehicles:
            q = q.filter(WorkspaceVehicleMaintenanceBaseline.vehicle_id.in_(list(allowed_vehicles)))
    if district_id:
        q = q.filter(WorkspaceVehicleMaintenanceBaseline.district_id == district_id)
    if project_id:
        q = q.filter(WorkspaceVehicleMaintenanceBaseline.project_id == project_id)
    if vehicle_id:
        q = q.filter(WorkspaceVehicleMaintenanceBaseline.vehicle_id == vehicle_id)
    if job_category:
        q = q.filter(WorkspaceVehicleMaintenanceBaseline.job_category.ilike(f"%{job_category}%"))

    baselines = q.order_by(WorkspaceVehicleMaintenanceBaseline.updated_at.desc(), WorkspaceVehicleMaintenanceBaseline.id.desc()).all()
    latest_reading_cache = {}

    def _latest_reading_for_vehicle(v_id):
        if v_id not in latest_reading_cache:
            latest_reading_cache[v_id] = _vehicle_latest_recorded_reading(v_id)
        return latest_reading_cache[v_id]

    rows = []
    for b in baselines:
        last_invoice = None
        cat = (b.job_category or '').strip()
        if cat:
            inv_q = MaintenanceExpense.query.filter(
                MaintenanceExpense.vehicle_id == b.vehicle_id,
                func.lower(func.trim(MaintenanceExpense.job_category)) == cat.lower(),
            )
            if workspace_employee_id:
                inv_q = inv_q.filter(
                    db.or_(
                        MaintenanceExpense.employee_id == workspace_employee_id,
                        MaintenanceExpense.employee_id.is_(None),
                    )
                )
            last_invoice = inv_q.order_by(MaintenanceExpense.expense_date.desc(), MaintenanceExpense.id.desc()).first()
        elif b.product_id:
            invoice_pair = db.session.query(MaintenanceExpense, MaintenanceExpenseItem).join(
                MaintenanceExpenseItem, MaintenanceExpenseItem.maintenance_expense_id == MaintenanceExpense.id
            ).filter(
                MaintenanceExpense.vehicle_id == b.vehicle_id,
                MaintenanceExpenseItem.product_id == b.product_id,
            )
            if workspace_employee_id:
                invoice_pair = invoice_pair.filter(
                    db.or_(
                        MaintenanceExpense.employee_id == workspace_employee_id,
                        MaintenanceExpense.employee_id.is_(None),
                    )
                )
            latest_pair = invoice_pair.order_by(MaintenanceExpense.expense_date.desc(), MaintenanceExpense.id.desc()).first()
            last_invoice = latest_pair[0] if latest_pair else None

        effective_date = b.last_done_date
        effective_reading = float(b.last_done_reading) if b.last_done_reading is not None else None
        source_label = 'Baseline'
        last_invoice_no = '-'
        if last_invoice:
            inv_date = last_invoice.expense_date
            inv_read = float(last_invoice.current_reading) if last_invoice.current_reading is not None else None
            if inv_date and (effective_date is None or inv_date >= effective_date):
                effective_date = inv_date
                effective_reading = inv_read
                source_label = 'Invoice'
            last_invoice_no = f"MAINT-{last_invoice.id}"

        class _Tmp:
            pass
        m_mode, m_val = _merged_interval_for_baseline(b)
        tmp = _Tmp()
        tmp.interval_mode = m_mode
        tmp.interval_value = m_val
        tmp.last_done_date = effective_date
        tmp.last_done_reading = effective_reading
        latest_v_read = _latest_reading_for_vehicle(b.vehicle_id)
        stat = _baseline_status(tmp, latest_reading=latest_v_read)

        if status in ('overdue', 'due_soon', 'on_track', 'reading_needed', 'no_interval'):
            mapped = {
                'overdue': 'Overdue',
                'due_soon': 'Due Soon',
                'on_track': 'On Track',
                'reading_needed': 'Reading Needed',
                'no_interval': 'No Interval',
            }[status]
            if stat['status'] != mapped:
                continue

        rows.append({
            'baseline': b,
            'display_interval_mode': m_mode,
            'display_interval_value': m_val,
            'status': stat['status'],
            'next_due_date_label': stat['next_due_date_label'],
            'next_due_reading_label': stat['next_due_reading_label'],
            'remaining_days_label': stat['remaining_days_label'],
            'remaining_km_label': stat['remaining_km_label'],
            'effective_last_date_label': effective_date.strftime('%d-%m-%Y') if effective_date else '-',
            'effective_last_reading_label': _format_baseline_reading_display(effective_reading)
            if effective_reading is not None
            else '-',
            'latest_vehicle_reading_label': _format_baseline_reading_display(latest_v_read) if latest_v_read is not None else '-',
            'source_label': source_label,
            'last_invoice_no': last_invoice_no,
            'last_invoice_id': (last_invoice.id if last_invoice else None),
        })

    totals = {
        'count': len(rows),
        'overdue': sum(1 for r in rows if r['status'] == 'Overdue'),
        'due_soon': sum(1 for r in rows if r['status'] == 'Due Soon'),
        'on_track': sum(1 for r in rows if r['status'] == 'On Track'),
    }

    page = request.args.get('page', 1, type=int) or 1
    # fleetPrintExport fetches with per_page=99999 to get full table for print/CSV; cap to prevent OOM
    _std_pp = (10, 20, 25, 50, 100)
    raw_per_page = request.args.get('per_page', 25, type=int) or 25
    if raw_per_page in _std_pp:
        per_page = raw_per_page
    elif raw_per_page >= 1000:
        per_page = min(len(rows), 500) if rows else 500  # F-02: cap at 500
    else:
        per_page = 25
    pagination = SimplePagination(rows, page, per_page)

    return render_template(
        'maintenance_baseline_alert_report.html',
        title='Maintenance Baseline Alert Report',
        form=form,
        rows=pagination.items,
        pagination=pagination,
        per_page=per_page,
        totals=totals,
        district_id=district_id,
        project_id=project_id,
        vehicle_id=vehicle_id,
        job_category=job_category,
        status=status,
        job_category_choices=job_category_choices,
    )


@app.route('/maintenance-expense/add', methods=['GET', 'POST'])
@app.route('/maintenance-expense/edit/<int:pk>', methods=['GET', 'POST'])
def maintenance_expense_form(pk=None):
    _ensure_maintenance_work_order_schema()
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return _guard
    workspace_employee_id = _workspace_employee_id_for_expenses()
    # User-requested flow: keep uploads in backend processing (no blocking modal on form submit).
    maintenance_direct_r2 = False
    maintenance_attachment_max_mb = _expense_attachment_max_bytes() // (1024 * 1024)
    default_district_id = _workspace_employee_default_district_id(workspace_employee_id)
    rec = MaintenanceExpense.query.get_or_404(pk) if pk else None
    if rec and workspace_employee_id and rec.employee_id and rec.employee_id != workspace_employee_id:
        flash('This expense does not belong to selected workspace employee.', 'danger')
        return redirect(url_for('maintenance_expense_list'))
    requested_work_order_id = request.args.get('work_order_id', type=int) or 0
    requested_work_order = None
    if requested_work_order_id and not rec and request.method == 'GET':
        requested_work_order = MaintenanceWorkOrder.query.filter_by(id=requested_work_order_id).first()
        if not requested_work_order:
            requested_work_order_id = 0
        elif workspace_employee_id and requested_work_order.employee_id and requested_work_order.employee_id != workspace_employee_id:
            requested_work_order_id = 0
            requested_work_order = None
    form = MaintenanceExpenseForm(obj=rec)
    maintenance_form_focus = None
    total_bill_error = ''
    entered_total_bill = (
        (request.form.get('total_bill_amount') or '').strip()
        if request.method == 'POST'
        else (f"{float(rec.total_bill_amount):.2f}" if rec and rec.total_bill_amount is not None else '')
    )
    entered_labour_amount = (request.form.get('labour_amount') or '').strip() if request.method == 'POST' else ''
    party_error = ''
    labour_split_error = ''
    selected_payment_type = (request.form.get('payment_type') or (getattr(rec, 'payment_type', None) if rec else '') or '').strip()
    selected_party_id = (request.form.get('workspace_party_id') or (str(getattr(rec, 'workspace_party_id', '') or '') if rec else '')).strip()
    selected_labour_party_id = (request.form.get('labour_workspace_party_id') or '').strip()

    def _render_maintenance_form():
        return render_template(
            'maintenance_expense_form.html',
            form=form,
            rec=rec,
            title='Edit Maintenance' if rec else 'Add Maintenance',
            products_for_maintenance=products_for_maintenance,
            job_categories=job_categories,
            total_bill_error=total_bill_error,
            entered_total_bill=entered_total_bill,
            entered_labour_amount=entered_labour_amount,
            party_error=party_error,
            labour_split_error=labour_split_error,
            selected_payment_type=selected_payment_type,
            selected_party_id=selected_party_id,
            selected_labour_party_id=selected_labour_party_id,
            workspace_parties=workspace_parties,
            maintenance_direct_r2=maintenance_direct_r2,
            maintenance_attachment_max_mb=maintenance_attachment_max_mb,
            requested_work_order=requested_work_order,
            maintenance_form_focus=maintenance_form_focus,
            location_cascade=_fuel_expense_location_cascade_dict(),
        )
    form.expense_by.choices = _workspace_expense_by_choices(workspace_employee_id)
    products_for_maintenance = _workspace_products_for_expense_form(workspace_employee_id, 'Maintenance')
    job_categories = _get_maintenance_job_categories()
    workspace_parties = WorkspaceParty.query.filter_by(
        employee_id=workspace_employee_id,
        is_active=True,
    ).order_by(WorkspaceParty.name.asc()).all()
    form.district_id.choices = [(0, '-- Select District --')] + [(d.id, d.name) for d in District.query.order_by(District.name).all()]
    selected_district_id = None
    selected_project_id = None
    if request.method == 'POST':
        selected_district_id = form.district_id.data or None
        selected_project_id = form.project_id.data or None
    elif rec:
        selected_district_id = rec.district_id or None
        selected_project_id = rec.project_id or None
    elif requested_work_order:
        selected_district_id = requested_work_order.district_id or None
        selected_project_id = requested_work_order.project_id or None
    else:
        selected_district_id = default_district_id or None
    if selected_district_id == 0:
        selected_district_id = None
    if selected_project_id == 0:
        selected_project_id = None

    project_q = Project.query
    if selected_district_id:
        project_q = project_q.join(project_district).filter(project_district.c.district_id == selected_district_id)
    form.project_id.choices = [(0, '-- Select Project --')] + [(p.id, p.name) for p in project_q.order_by(Project.name).all()]

    vehicle_q = Vehicle.query
    if selected_project_id:
        vehicle_q = vehicle_q.filter(Vehicle.project_id == selected_project_id)
    if selected_district_id:
        vehicle_q = vehicle_q.filter(Vehicle.district_id == selected_district_id)
    if not selected_project_id and not selected_district_id:
        form.vehicle_id.choices = [(0, '-- Select Vehicle --')]
    else:
        form.vehicle_id.choices = [(0, '-- Select Vehicle --')] + [(v.id, v.vehicle_no) for v in vehicle_q.order_by(*vehicle_order_by()).all()]
    selected_vehicle_id = None
    if request.method == 'POST':
        selected_vehicle_id = form.vehicle_id.data or None
    elif rec:
        selected_vehicle_id = rec.vehicle_id or None
    elif requested_work_order:
        selected_vehicle_id = requested_work_order.vehicle_id or None
    work_order_q = MaintenanceWorkOrder.query
    if workspace_employee_id:
        work_order_q = work_order_q.filter(
            db.or_(
                MaintenanceWorkOrder.employee_id == workspace_employee_id,
                MaintenanceWorkOrder.employee_id.is_(None),
            )
        )
    if selected_vehicle_id:
        work_order_q = work_order_q.filter(MaintenanceWorkOrder.vehicle_id == selected_vehicle_id)
    work_order_q = work_order_q.filter(MaintenanceWorkOrder.status != 'closed')
    work_orders = work_order_q.order_by(MaintenanceWorkOrder.opened_on.desc(), MaintenanceWorkOrder.id.desc()).limit(250).all()
    form.work_order_id.choices = [(0, '-- No Work Order --')] + [
        (w.id, f'{w.work_order_no} | {w.title}')
        for w in work_orders
    ]
    if request.method == 'GET' and rec:
        if rec.district_id:
            form.district_id.data = rec.district_id
        if rec.project_id:
            form.project_id.data = rec.project_id
        if rec.vehicle_id:
            form.vehicle_id.data = rec.vehicle_id
        if rec.work_order_id:
            form.work_order_id.data = rec.work_order_id
        form.expense_by.data = _workspace_expense_by_for_reference(workspace_employee_id, 'MaintenanceExpense', rec.id)
        if rec.total_bill_amount is not None:
            entered_total_bill = f"{float(rec.total_bill_amount):.2f}"
    elif request.method == 'GET':
        if requested_work_order:
            form.district_id.data = requested_work_order.district_id or 0
            form.project_id.data = requested_work_order.project_id or 0
            form.vehicle_id.data = requested_work_order.vehicle_id
            form.work_order_id.data = requested_work_order.id
            form.expense_date.data = requested_work_order.opened_on or pk_date()
        else:
            if default_district_id:
                form.district_id.data = default_district_id
            form.expense_date.data = pk_date()
        selected_payment_type = ''
    if request.method == 'GET' and not rec:
        maintenance_form_focus = 'job_category' if requested_work_order else 'expense_date'

    if form.validate_on_submit():
        vehicle_id = form.vehicle_id.data
        if not vehicle_id:
            flash('Select vehicle.', 'danger')
            return _render_maintenance_form()
        district_id = form.district_id.data or None
        if district_id == 0:
            district_id = None
        project_id = form.project_id.data or None
        if project_id == 0:
            project_id = None
        vehicle_obj = Vehicle.query.get_or_404(vehicle_id)
        if project_id and int(vehicle_obj.project_id or 0) != int(project_id):
            flash('Selected vehicle does not belong to selected project.', 'danger')
            return _render_maintenance_form()
        if district_id and int(vehicle_obj.district_id or 0) != int(district_id):
            flash('Selected vehicle does not belong to selected district.', 'danger')
            return _render_maintenance_form()
        if district_id and project_id:
            linked = Project.query.join(project_district).filter(
                Project.id == project_id,
                project_district.c.district_id == district_id,
            ).first()
            if not linked:
                flash('Selected project is not linked with selected district.', 'danger')
                return _render_maintenance_form()
        if not project_id:
            project_id = vehicle_obj.project_id
        if not district_id:
            district_id = vehicle_obj.district_id
        work_order_id = form.work_order_id.data or None
        if work_order_id == 0:
            work_order_id = None
        work_order_obj = None
        if work_order_id:
            work_order_obj = MaintenanceWorkOrder.query.filter_by(id=work_order_id).first()
            if not work_order_obj:
                flash('Selected work order not found.', 'danger')
                return _render_maintenance_form()
            if workspace_employee_id and work_order_obj.employee_id and work_order_obj.employee_id != workspace_employee_id:
                flash('Selected work order is not allowed for current workspace employee.', 'danger')
                return _render_maintenance_form()
            if int(work_order_obj.vehicle_id or 0) != int(vehicle_id):
                flash('Selected work order vehicle does not match expense vehicle.', 'danger')
                return _render_maintenance_form()
        expense_date = form.expense_date.data
        curr_reading = form.current_reading.data
        remarks = form.remarks.data
        job_category = (request.form.get('job_category') or '').strip() or None
        job_interval_mode = (request.form.get('job_interval_mode') or '').strip().lower()
        if job_interval_mode not in ('interval_km', 'interval_day'):
            job_interval_mode = None
        task_start_reading, task_close_reading = _fuel_expense_task_readings(vehicle_id, expense_date)
        prev_reading = _maintenance_expense_previous_reading(
            vehicle_id=vehicle_id,
            expense_date=expense_date,
            exclude_id=(rec.id if rec else None),
            workspace_employee_id=workspace_employee_id,
            current_reading=curr_reading,
        )
        if prev_reading is None and task_start_reading is not None:
            prev_reading = float(task_start_reading)
        close_reading = float(task_close_reading) if task_close_reading is not None else None
        if curr_reading is None and close_reading is not None:
            curr_reading = close_reading
        try:
            curr_reading = float(curr_reading) if curr_reading is not None else None
        except (TypeError, ValueError):
            curr_reading = None
        if prev_reading is None:
            prev_reading = _fallback_vehicle_previous_reading(workspace_employee_id, vehicle_id, 'maintenance')
        km_reading = None
        if prev_reading is not None and curr_reading is not None:
            km_reading = float(curr_reading) - float(prev_reading)
        payment_type = (request.form.get('payment_type') or '').strip()
        if payment_type not in ('Cash', 'Credit'):
            flash('Payment Type select karna zaroori hai.', 'danger')
            return _render_maintenance_form()
        selected_payment_type = payment_type
        workspace_party_id_raw = (request.form.get('workspace_party_id') or '').strip()
        workspace_party_id = int(workspace_party_id_raw) if workspace_party_id_raw.isdigit() else None
        selected_party_id = str(workspace_party_id or '')
        labour_workspace_party_id_raw = (request.form.get('labour_workspace_party_id') or '').strip()
        labour_workspace_party_id = int(labour_workspace_party_id_raw) if labour_workspace_party_id_raw.isdigit() else None
        selected_labour_party_id = str(labour_workspace_party_id or '')

        product_ids = request.form.getlist('product_id')
        qtys = request.form.getlist('qty')
        prices = request.form.getlist('price')
        items_data = []
        n = max(len(product_ids or [0]), len(qtys or [0]), len(prices or [0]))
        for i in range(n):
            pid = product_ids[i] if i < len(product_ids or []) else None
            try:
                pid = int(pid) if pid else None
            except (TypeError, ValueError):
                pid = None
            if not pid:
                continue
            try:
                qty = float(qtys[i]) if i < len(qtys or []) and qtys[i] else 0
            except (TypeError, ValueError):
                qty = 0
            try:
                price = float(prices[i]) if i < len(prices or []) and prices[i] else 0
            except (TypeError, ValueError):
                price = 0
            amount = (qty * price) if price else None
            items_data.append({'product_id': pid, 'qty': qty, 'price': price, 'amount': amount})

        items_total = sum(float((it.get('amount') or 0)) for it in items_data)
        try:
            entered_total_bill_num = float(entered_total_bill) if entered_total_bill else 0.0
        except (TypeError, ValueError):
            entered_total_bill_num = 0.0
        try:
            labour_amount_num = float(entered_labour_amount) if entered_labour_amount else 0.0
        except (TypeError, ValueError):
            labour_amount_num = -1.0

        if entered_total_bill_num <= 0:
            total_bill_error = 'Total Bill Amount enter karein (0 se bara).'
            flash('Form save nahi hua. Total Bill Amount required hai.', 'danger')
            return _render_maintenance_form()

        if abs(items_total - entered_total_bill_num) > 0.01:
            total_bill_error = f'Total mismatch: list total {items_total:.2f} aur entered total {entered_total_bill_num:.2f} equal nahi.'
            flash('Form save nahi hua. Product list total aur Total Bill Amount equal karein.', 'danger')
            return _render_maintenance_form()

        if labour_amount_num < 0:
            labour_split_error = 'Labour amount numeric hona chahiye (0 ya us se bara).'
            flash('Form save nahi hua. Labour amount theek karein.', 'danger')
            return _render_maintenance_form()
        if labour_amount_num > entered_total_bill_num + 0.01:
            labour_split_error = 'Labour amount total bill se zyada nahi ho sakta.'
            flash('Form save nahi hua. Labour amount total bill se zyada hai.', 'danger')
            return _render_maintenance_form()

        if labour_amount_num < 0.005:
            labour_amount_num = 0.0
        parts_amount_num = max(0.0, entered_total_bill_num - labour_amount_num)
        if parts_amount_num <= 0 and labour_amount_num <= 0:
            total_bill_error = 'Parts/Labour split invalid hai.'
            flash('Form save nahi hua. Split amount check karein.', 'danger')
            return _render_maintenance_form()

        if payment_type == 'Credit':
            if parts_amount_num > 0 and not workspace_party_id:
                party_error = 'Credit payment me Parts amount ke liye Party Name select karna zaroori hai.'
                flash('Form save nahi hua. Parts party required hai.', 'danger')
                return _render_maintenance_form()
            if labour_amount_num > 0 and not labour_workspace_party_id:
                labour_split_error = 'Credit payment me Labour amount ke liye Labour Party select karna zaroori hai.'
                flash('Form save nahi hua. Labour party required hai.', 'danger')
                return _render_maintenance_form()

        try:
            if rec:
                MaintenanceExpenseItem.query.filter_by(maintenance_expense_id=rec.id).delete()
            else:
                rec = MaintenanceExpense(
                    district_id=district_id,
                    project_id=project_id,
                    employee_id=workspace_employee_id,
                    vehicle_id=vehicle_id,
                    expense_date=expense_date,
                    current_reading=curr_reading,
                    previous_reading=prev_reading,
                    km=km_reading,
                    job_category=job_category,
                    job_interval_mode=job_interval_mode,
                    payment_type=payment_type,
                    workspace_party_id=(workspace_party_id if (payment_type == 'Credit' and parts_amount_num > 0) else None),
                    work_order_id=work_order_id,
                    total_bill_amount=entered_total_bill_num,
                    remarks=remarks
                )
                db.session.add(rec)
            db.session.flush()
            if rec.id:
                rec.district_id = district_id
                rec.project_id = project_id
                rec.employee_id = workspace_employee_id
                rec.vehicle_id = vehicle_id
                rec.expense_date = expense_date
                rec.current_reading = curr_reading
                rec.previous_reading = prev_reading
                rec.km = km_reading
                rec.job_category = job_category
                rec.job_interval_mode = job_interval_mode
                rec.payment_type = payment_type
                rec.workspace_party_id = workspace_party_id if (payment_type == 'Credit' and parts_amount_num > 0) else None
                rec.work_order_id = work_order_id
                rec.total_bill_amount = entered_total_bill_num
                rec.remarks = remarks
            _resequence_vehicle_maintenance_expenses(vehicle_id, workspace_employee_id)
            for idx, it in enumerate(items_data):
                item = MaintenanceExpenseItem(
                    maintenance_expense_id=rec.id,
                    product_id=it['product_id'],
                    qty=it['qty'],
                    price=it['price'],
                    amount=it['amount'],
                    sort_order=idx
                )
                db.session.add(item)
            _workspace_reverse_expense_journals('MaintenanceExpense', rec.id, workspace_employee_id)
            expense_by_val = form.expense_by.data or ''
            if payment_type == 'Cash':
                expense_by_val = expense_by_val or _workspace_default_hbl_expense_by(workspace_employee_id)
            selected_credit_account_id = _workspace_account_id_from_expense_by(expense_by_val, workspace_employee_id)
            base_desc = f'Maintenance expense vehicle {rec.vehicle.vehicle_no if rec.vehicle else rec.vehicle_id}'
            maintenance_je = None
            if parts_amount_num > 0:
                maintenance_je = _workspace_post_expense_journal(
                    employee_id=workspace_employee_id,
                    reference_type='MaintenanceExpense',
                    reference_id=rec.id,
                    expense_date=expense_date,
                    amount=parts_amount_num,
                    description=base_desc + ' (Parts)',
                    category_code='Maintenance',
                    workspace_party_id=workspace_party_id if payment_type == 'Credit' else None,
                    credit_account_id=(selected_credit_account_id if payment_type == 'Cash' else None),
                )
            if labour_amount_num > 0:
                labour_je = _workspace_post_expense_journal(
                    employee_id=workspace_employee_id,
                    reference_type='MaintenanceExpense',
                    reference_id=rec.id,
                    expense_date=expense_date,
                    amount=labour_amount_num,
                    description=base_desc + ' (Labour)',
                    category_code='Maintenance',
                    workspace_party_id=labour_workspace_party_id if payment_type == 'Credit' else None,
                    credit_account_id=(selected_credit_account_id if payment_type == 'Cash' else None),
                )
                if not maintenance_je:
                    maintenance_je = labour_je

            if payment_type == 'Credit' and selected_credit_account_id:
                selected_credit = WorkspaceAccount.query.filter_by(
                    id=selected_credit_account_id,
                    employee_id=workspace_employee_id,
                    is_active=True,
                ).first()
                selected_credit_name = selected_credit.name if selected_credit else f'Account {selected_credit_account_id}'
                if parts_amount_num > 0 and workspace_party_id:
                    parts_party_obj = WorkspaceParty.query.filter_by(employee_id=workspace_employee_id, id=workspace_party_id).first()
                    _workspace_post_credit_settlement_journal(
                        employee_id=workspace_employee_id,
                        reference_type='MaintenanceExpense',
                        reference_id=rec.id,
                        expense_date=expense_date,
                        amount=parts_amount_num,
                        category_code='Maintenance',
                        workspace_party_id=workspace_party_id,
                        credit_account_id=selected_credit_account_id,
                        description=(
                            f"Cash paid by {selected_credit_name} to {(parts_party_obj.name if parts_party_obj else 'Parts Party')}"
                            f" for Maintenance parts expense"
                        ),
                    )
                if labour_amount_num > 0 and labour_workspace_party_id:
                    labour_party_obj = WorkspaceParty.query.filter_by(employee_id=workspace_employee_id, id=labour_workspace_party_id).first()
                    _workspace_post_credit_settlement_journal(
                        employee_id=workspace_employee_id,
                        reference_type='MaintenanceExpense',
                        reference_id=rec.id,
                        expense_date=expense_date,
                        amount=labour_amount_num,
                        category_code='Maintenance',
                        workspace_party_id=labour_workspace_party_id,
                        credit_account_id=selected_credit_account_id,
                        description=(
                            f"Cash paid by {selected_credit_name} to {(labour_party_obj.name if labour_party_obj else 'Labour Party')}"
                            f" for Maintenance labour expense"
                        ),
                    )
            _workspace_sync_regular_expense(
                employee_id=workspace_employee_id,
                reference_type='MaintenanceExpense',
                reference_id=rec.id,
                expense_date=expense_date,
                amount=items_total,
                description=(
                    f'{base_desc} (Parts {parts_amount_num:.2f}'
                    + (f', Labour {labour_amount_num:.2f}' if labour_amount_num > 0 else '')
                    + ')'
                ),
                expense_type='Maintenance Expense',
                payment_mode=(payment_type or 'Cash'),
                category='Maintenance',
                workspace_party_id=(workspace_party_id if (payment_type == 'Credit' and parts_amount_num > 0) else (labour_workspace_party_id if payment_type == 'Credit' else None)),
                journal_entry_id=(maintenance_je.id if maintenance_je else None),
            )
            db.session.commit()

            split_upload = request.headers.get('X-Maint-Split-Upload') == '1'
            if split_upload:
                return jsonify({
                    'ok': True,
                    'id': rec.id,
                    'edit': bool(pk),
                    'list_url': url_for('maintenance_expense_list'),
                })

            files = request.files.getlist('attachments')
            has_new_files = bool(files and any(f and getattr(f, 'filename', None) for f in files))
            if has_new_files:
                try:
                    manifest, skipped_att = _prepare_maintenance_upload_manifest(files, rec.id)
                    rec.upload_total = len(manifest)
                    rec.upload_done = 0
                    rec.upload_failed = 0
                    rec.upload_error = None
                    rec.upload_finished_at = None
                    if manifest:
                        rec.upload_status = 'processing'
                        rec.upload_started_at = pk_now()
                        rec.upload_manifest_json = json.dumps(manifest)
                    else:
                        rec.upload_status = 'success'
                        rec.upload_started_at = None
                        rec.upload_manifest_json = None
                        rec.upload_finished_at = pk_now()
                    db.session.commit()
                    if manifest:
                        _start_maintenance_upload_worker(rec.id)
                        flash(f'Upload background me start ho gaya ({len(manifest)} file). Status list me live dekhein.', 'info')
                    if skipped_att:
                        flash('Kuch files queue me nahi gayin: ' + '; '.join(skipped_att), 'warning')
                except Exception:
                    db.session.rollback()
                    app.logger.exception('Maintenance async attachment queue save')
                    flash('Maintenance save ho gaya lekin files queue me add nahi ho sakin.', 'warning')
            flash('Maintenance expense saved.', 'success')
            return redirect(url_for('maintenance_expense_list'))
        except Exception as _save_exc:
            db.session.rollback()
            app.logger.exception('Maintenance expense save failed')
            if request.headers.get('X-Maint-Split-Upload') == '1':
                return jsonify({'ok': False, 'error': str(_save_exc)}), 500
            raise
    elif request.method == 'POST':
        if form.errors:
            flash('Form save nahi hua. Required fields check karein.', 'danger')
        else:
            flash('Form save nahi hua. Data dobara check karein.', 'danger')
    return _render_maintenance_form()


@app.route('/maintenance-expense/<int:pk>/view')
def maintenance_expense_view(pk):
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return _guard
    workspace_employee_id = _workspace_employee_id_for_expenses()
    rec = MaintenanceExpense.query.get_or_404(pk)
    if workspace_employee_id and rec.employee_id and rec.employee_id != workspace_employee_id:
        flash('This expense does not belong to selected workspace employee.', 'danger')
        return redirect(url_for('maintenance_expense_list'))
    default_back = url_for('maintenance_expense_list')
    back_url = _safe_internal_path(request.args.get('return_to'), default_back)
    return render_template(
        'maintenance_expense_detail.html',
        rec=rec,
        title='Maintenance Expense Detail',
        back_url=back_url,
        return_to_path=request.full_path,
    )


@app.route('/maintenance-expense/delete/<int:pk>', methods=['POST'])
def maintenance_expense_delete(pk):
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return _guard
    workspace_employee_id = _workspace_employee_id_for_expenses()
    rec = MaintenanceExpense.query.get_or_404(pk)
    if workspace_employee_id and rec.employee_id and rec.employee_id != workspace_employee_id:
        flash('This expense does not belong to selected workspace employee.', 'danger')
        return redirect(url_for('maintenance_expense_list'))
    attachment_paths = [att.file_path for att in rec.attachments.all() if att and getattr(att, 'file_path', None)]
    initiated_by_user_id = session.get('user_id')
    vehicle_id = rec.vehicle_id
    _workspace_reverse_expense_journals('MaintenanceExpense', rec.id, workspace_employee_id)
    _workspace_delete_regular_expense(workspace_employee_id, 'MaintenanceExpense', rec.id)
    rec_id = rec.id
    db.session.delete(rec)
    _resequence_vehicle_maintenance_expenses(vehicle_id, workspace_employee_id)
    db.session.commit()
    _start_expense_delete_cleanup_worker('maintenance', rec_id, attachment_paths, employee_id=workspace_employee_id, initiated_by_user_id=initiated_by_user_id)
    flash('Maintenance expense deleted. Media cleanup background me continue ho rahi hai.', 'success')
    return redirect(url_for('maintenance_expense_list'))


@app.route('/maintenance-expense/<int:pk>/media')
@app.route('/maintenance-expenses/<int:pk>/media')
def maintenance_expense_media(pk):
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return _guard
    workspace_employee_id = _workspace_employee_id_for_expenses()
    rec = MaintenanceExpense.query.filter_by(id=pk).first()
    if not rec:
        flash('Media record not found (maybe deleted).', 'warning')
        return redirect(url_for('maintenance_expense_list'))
    if workspace_employee_id and rec.employee_id and rec.employee_id != workspace_employee_id:
        flash('This expense does not belong to selected workspace employee.', 'danger')
        return redirect(url_for('maintenance_expense_list'))
    def _human_size(n):
        if n is None:
            return ''
        size = float(n)
        units = ['B', 'KB', 'MB', 'GB', 'TB']
        idx = 0
        while size >= 1024 and idx < len(units) - 1:
            size /= 1024.0
            idx += 1
        if idx == 0:
            return f"{int(size)} {units[idx]}"
        return f"{size:.1f} {units[idx]}"

    def _local_attachment_size_bytes(stored_path):
        if not stored_path:
            return None
        p = str(stored_path).strip()
        if p.startswith('http://') or p.startswith('https://'):
            return None
        upload_root = os.path.abspath(app.config.get('UPLOAD_FOLDER', ''))
        if not upload_root:
            return None
        rel = p.replace('\\', '/').lstrip('/')
        if rel.startswith('uploads/'):
            rel = rel[len('uploads/'):]
        full = os.path.abspath(os.path.join(upload_root, rel.replace('/', os.sep)))
        if not full.startswith(upload_root):
            return None
        try:
            return os.path.getsize(full)
        except OSError:
            return None

    def _local_attachment_full_path(stored_path):
        if not stored_path:
            return None
        p = str(stored_path).strip()
        if p.startswith('http://') or p.startswith('https://'):
            return None
        upload_root = os.path.abspath(app.config.get('UPLOAD_FOLDER', ''))
        if not upload_root:
            return None
        rel = p.replace('\\', '/').lstrip('/')
        if rel.startswith('uploads/'):
            rel = rel[len('uploads/'):]
        full = os.path.abspath(os.path.join(upload_root, rel.replace('/', os.sep)))
        if not full.startswith(upload_root):
            return None
        return full if os.path.isfile(full) else None

    media_items = []
    for att in rec.attachments.order_by(MaintenanceExpenseAttachment.created_at.asc(), MaintenanceExpenseAttachment.id.asc()).all():
        url = media_url_filter(att.file_path or '')
        if not url:
            continue
        ftype = (att.file_type or '').strip().lower()
        if ftype not in ('image', 'video'):
            path = (att.file_path or '').lower()
            if any(path.endswith(x) for x in ('.mp4', '.webm', '.mov')):
                ftype = 'video'
            else:
                ftype = 'image'
        size_bytes = _local_attachment_size_bytes(att.file_path or '')
        created_at = att.created_at
        media_items.append({
            'url': url,
            'type': ftype,
            'name': att.original_name or os.path.basename(att.file_path or '') or 'Attachment',
            'created_at': created_at.strftime('%d-%m-%Y %I:%M %p') if created_at else '',
            'created_at_iso': created_at.isoformat() if created_at else '',
            'size_bytes': size_bytes,
            'size_label': _human_size(size_bytes),
            'download_url': url_for('maintenance_expense_media_download', pk=rec.id, att_id=att.id),
            'is_local_file': bool(_local_attachment_full_path(att.file_path or '')),
        })
    default_back = url_for('maintenance_expense_list')
    back_url = _safe_internal_path(request.args.get('return_to'), default_back)
    return render_template(
        'maintenance_expense_media.html',
        rec=rec,
        media_items=media_items,
        back_url=back_url,
        media_date_label=format_date_ddmmyyyy(rec.expense_date) if rec.expense_date else None,
    )


def _maintenance_attachment_download_name(att):
    name = secure_filename((att.original_name or '').strip())
    if not name:
        base = secure_filename(os.path.basename(att.file_path or '').strip()) or f'attachment_{att.id}'
        name = base
    if '.' not in name:
        if (att.file_type or '').lower() == 'video':
            name += '.mp4'
        else:
            name += '.jpg'
    return name


def _maintenance_attachment_local_full_path(stored_path):
    if not stored_path:
        return None
    p = str(stored_path).strip()
    if p.startswith('http://') or p.startswith('https://'):
        return None
    upload_root = os.path.abspath(app.config.get('UPLOAD_FOLDER', ''))
    if not upload_root:
        return None
    rel = p.replace('\\', '/').lstrip('/')
    if rel.startswith('uploads/'):
        rel = rel[len('uploads/'):]
    full = os.path.abspath(os.path.join(upload_root, rel.replace('/', os.sep)))
    if not full.startswith(upload_root):
        return None
    return full if os.path.isfile(full) else None


def _maintenance_attachment_read_bytes(stored_path):
    full = _maintenance_attachment_local_full_path(stored_path)
    if full:
        with open(full, 'rb') as fh:
            data = fh.read()
        mt, _ = mimetypes.guess_type(full)
        return data, (mt or 'application/octet-stream')

    url = media_url_filter(stored_path or '')
    if not url:
        return b'', 'application/octet-stream'
    req = Request(url, headers={'User-Agent': 'fleet-manager/maintenance-media-download'})
    with urlopen(req, timeout=90) as resp:
        data = resp.read()
        ct = (resp.headers.get('Content-Type') or 'application/octet-stream').split(';')[0].strip()
    return data, (ct or 'application/octet-stream')


@app.route('/maintenance-expense/<int:pk>/media/download/<int:att_id>')
@app.route('/maintenance-expenses/<int:pk>/media/download/<int:att_id>')
def maintenance_expense_media_download(pk, att_id):
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return _guard
    workspace_employee_id = _workspace_employee_id_for_expenses()
    rec = MaintenanceExpense.query.filter_by(id=pk).first()
    if not rec:
        flash('Media record not found (maybe deleted).', 'warning')
        return redirect(url_for('maintenance_expense_list'))
    if workspace_employee_id and rec.employee_id and rec.employee_id != workspace_employee_id:
        flash('This expense does not belong to selected workspace employee.', 'danger')
        return redirect(url_for('maintenance_expense_list'))
    att = MaintenanceExpenseAttachment.query.filter_by(id=att_id, maintenance_expense_id=rec.id).first()
    if not att:
        flash('Attachment not found.', 'warning')
        return redirect(url_for('maintenance_expense_media', pk=rec.id))

    dl_name = _maintenance_attachment_download_name(att)
    local_full = _maintenance_attachment_local_full_path(att.file_path or '')
    if local_full:
        return send_file(local_full, as_attachment=True, download_name=dl_name, conditional=True, max_age=0)

    try:
        blob, mime = _maintenance_attachment_read_bytes(att.file_path or '')
    except Exception as ex:
        app.logger.warning('Maintenance media download failed (%s): %s', att.id, ex)
        flash('Download failed for this attachment.', 'danger')
        return redirect(url_for('maintenance_expense_media', pk=rec.id))
    if not blob:
        flash('Attachment file is empty.', 'warning')
        return redirect(url_for('maintenance_expense_media', pk=rec.id))
    return send_file(BytesIO(blob), as_attachment=True, download_name=dl_name, mimetype=(mime or 'application/octet-stream'), max_age=0)


@app.route('/maintenance-expense/<int:pk>/media/download-all')
@app.route('/maintenance-expenses/<int:pk>/media/download-all')
def maintenance_expense_media_download_all(pk):
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return _guard
    workspace_employee_id = _workspace_employee_id_for_expenses()
    rec = MaintenanceExpense.query.filter_by(id=pk).first()
    if not rec:
        flash('Media record not found (maybe deleted).', 'warning')
        return redirect(url_for('maintenance_expense_list'))
    if workspace_employee_id and rec.employee_id and rec.employee_id != workspace_employee_id:
        flash('This expense does not belong to selected workspace employee.', 'danger')
        return redirect(url_for('maintenance_expense_list'))

    atts = rec.attachments.order_by(MaintenanceExpenseAttachment.created_at.asc(), MaintenanceExpenseAttachment.id.asc()).all()
    if not atts:
        flash('No media files available for download.', 'warning')
        return redirect(url_for('maintenance_expense_media', pk=rec.id))

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
    zip_path = tmp.name
    tmp.close()
    added = 0
    used = set()
    try:
        with zipfile.ZipFile(zip_path, mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
            for idx, att in enumerate(atts, 1):
                base_name = _maintenance_attachment_download_name(att)
                file_name = base_name
                n = 2
                while file_name.lower() in used:
                    root, ext = os.path.splitext(base_name)
                    file_name = f'{root}_{n}{ext}'
                    n += 1
                used.add(file_name.lower())

                local_full = _maintenance_attachment_local_full_path(att.file_path or '')
                if local_full:
                    try:
                        zf.write(local_full, arcname=file_name)
                        added += 1
                        continue
                    except Exception as ex:
                        app.logger.warning('Maintenance zip local add failed (%s): %s', att.id, ex)
                try:
                    blob, _mime = _maintenance_attachment_read_bytes(att.file_path or '')
                    if blob:
                        zf.writestr(file_name, blob)
                        added += 1
                except Exception as ex:
                    app.logger.warning('Maintenance zip remote fetch failed (%s): %s', att.id, ex)
        if added == 0:
            try:
                os.remove(zip_path)
            except OSError:
                pass
            flash('No files could be packed for download.', 'danger')
            return redirect(url_for('maintenance_expense_media', pk=rec.id))
    except Exception as ex:
        try:
            os.remove(zip_path)
        except OSError:
            pass
        app.logger.warning('Maintenance zip creation failed (%s): %s', rec.id, ex)
        flash('Unable to prepare media ZIP right now.', 'danger')
        return redirect(url_for('maintenance_expense_media', pk=rec.id))

    @after_this_request
    def _cleanup_zip(resp):
        try:
            os.remove(zip_path)
        except OSError:
            pass
        return resp

    veh = secure_filename((rec.vehicle.vehicle_no if rec.vehicle else 'vehicle') or 'vehicle')
    date_part = rec.expense_date.strftime('%Y%m%d') if rec.expense_date else pk_now().strftime('%Y%m%d')
    archive_name = f'maintenance_media_{veh}_{date_part}.zip'
    return send_file(zip_path, as_attachment=True, download_name=archive_name, mimetype='application/zip', max_age=0)


@app.route('/fuel-expense/<int:pk>/media')
@app.route('/fuel-expenses/<int:pk>/media')
def fuel_expense_media(pk):
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return _guard
    workspace_employee_id = _workspace_employee_id_for_expenses()
    rec = FuelExpense.query.filter_by(id=pk).first()
    if not rec:
        flash('Media record not found (maybe deleted).', 'warning')
        return redirect(url_for('fuel_expense_list'))
    if workspace_employee_id and rec.employee_id and rec.employee_id != workspace_employee_id:
        flash('This expense does not belong to selected workspace employee.', 'danger')
        return redirect(url_for('fuel_expense_list'))

    def _human_size(n):
        if n is None:
            return ''
        size = float(n)
        units = ['B', 'KB', 'MB', 'GB', 'TB']
        idx = 0
        while size >= 1024 and idx < len(units) - 1:
            size /= 1024.0
            idx += 1
        if idx == 0:
            return f"{int(size)} {units[idx]}"
        return f"{size:.1f} {units[idx]}"

    media_items = []
    for att in rec.attachments.order_by(FuelExpenseAttachment.created_at.asc(), FuelExpenseAttachment.id.asc()).all():
        url = media_url_filter(att.file_path or '')
        if not url:
            continue
        ftype = (att.file_type or '').strip().lower()
        if ftype not in ('image', 'video'):
            path = (att.file_path or '').lower()
            if any(path.endswith(x) for x in ('.mp4', '.webm', '.mov')):
                ftype = 'video'
            else:
                ftype = 'image'
        local_full = _maintenance_attachment_local_full_path(att.file_path or '')
        size_bytes = os.path.getsize(local_full) if local_full else None
        created_at = att.created_at
        media_items.append({
            'url': url,
            'type': ftype,
            'name': att.original_name or os.path.basename(att.file_path or '') or 'Attachment',
            'created_at': created_at.strftime('%d-%m-%Y %I:%M %p') if created_at else '',
            'created_at_iso': created_at.isoformat() if created_at else '',
            'size_bytes': size_bytes,
            'size_label': _human_size(size_bytes),
            'download_url': url_for('fuel_expense_media_download', pk=rec.id, att_id=att.id),
            'is_local_file': bool(local_full),
        })
    date_label = rec.fueling_date.strftime('%d-%m-%Y') if rec.fueling_date else '-'
    return render_template(
        'maintenance_expense_media.html',
        rec=rec,
        media_items=media_items,
        media_title='Fuel Media Gallery',
        media_date_label=date_label,
        back_url=url_for('fuel_expense_list'),
        download_all_url=url_for('fuel_expense_media_download_all', pk=rec.id),
    )


@app.route('/fuel-expense/<int:pk>/media/download/<int:att_id>')
@app.route('/fuel-expenses/<int:pk>/media/download/<int:att_id>')
def fuel_expense_media_download(pk, att_id):
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return _guard
    workspace_employee_id = _workspace_employee_id_for_expenses()
    rec = FuelExpense.query.filter_by(id=pk).first()
    if not rec:
        flash('Media record not found (maybe deleted).', 'warning')
        return redirect(url_for('fuel_expense_list'))
    if workspace_employee_id and rec.employee_id and rec.employee_id != workspace_employee_id:
        flash('This expense does not belong to selected workspace employee.', 'danger')
        return redirect(url_for('fuel_expense_list'))
    att = FuelExpenseAttachment.query.filter_by(id=att_id, fuel_expense_id=rec.id).first()
    if not att:
        flash('Attachment not found.', 'warning')
        return redirect(url_for('fuel_expense_media', pk=rec.id))

    dl_name = _maintenance_attachment_download_name(att)
    local_full = _maintenance_attachment_local_full_path(att.file_path or '')
    if local_full:
        return send_file(local_full, as_attachment=True, download_name=dl_name, conditional=True, max_age=0)
    try:
        blob, mime = _maintenance_attachment_read_bytes(att.file_path or '')
    except Exception as ex:
        app.logger.warning('Fuel media download failed (%s): %s', att.id, ex)
        flash('Download failed for this attachment.', 'danger')
        return redirect(url_for('fuel_expense_media', pk=rec.id))
    if not blob:
        flash('Attachment file is empty.', 'warning')
        return redirect(url_for('fuel_expense_media', pk=rec.id))
    return send_file(BytesIO(blob), as_attachment=True, download_name=dl_name, mimetype=(mime or 'application/octet-stream'), max_age=0)


@app.route('/fuel-expense/<int:pk>/media/download-all')
@app.route('/fuel-expenses/<int:pk>/media/download-all')
def fuel_expense_media_download_all(pk):
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return _guard
    workspace_employee_id = _workspace_employee_id_for_expenses()
    rec = FuelExpense.query.filter_by(id=pk).first()
    if not rec:
        flash('Media record not found (maybe deleted).', 'warning')
        return redirect(url_for('fuel_expense_list'))
    if workspace_employee_id and rec.employee_id and rec.employee_id != workspace_employee_id:
        flash('This expense does not belong to selected workspace employee.', 'danger')
        return redirect(url_for('fuel_expense_list'))
    atts = rec.attachments.order_by(FuelExpenseAttachment.created_at.asc(), FuelExpenseAttachment.id.asc()).all()
    if not atts:
        flash('No media files available for download.', 'warning')
        return redirect(url_for('fuel_expense_media', pk=rec.id))

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
    zip_path = tmp.name
    tmp.close()
    added = 0
    used = set()
    try:
        with zipfile.ZipFile(zip_path, mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
            for att in atts:
                base_name = _maintenance_attachment_download_name(att)
                file_name = base_name
                n = 2
                while file_name.lower() in used:
                    root, ext = os.path.splitext(base_name)
                    file_name = f'{root}_{n}{ext}'
                    n += 1
                used.add(file_name.lower())
                local_full = _maintenance_attachment_local_full_path(att.file_path or '')
                if local_full:
                    try:
                        zf.write(local_full, arcname=file_name)
                        added += 1
                        continue
                    except Exception:
                        pass
                try:
                    blob, _mime = _maintenance_attachment_read_bytes(att.file_path or '')
                    if blob:
                        zf.writestr(file_name, blob)
                        added += 1
                except Exception:
                    pass
        if added == 0:
            try:
                os.remove(zip_path)
            except OSError:
                pass
            flash('No files could be packed for download.', 'danger')
            return redirect(url_for('fuel_expense_media', pk=rec.id))
    except Exception as ex:
        try:
            os.remove(zip_path)
        except OSError:
            pass
        app.logger.warning('Fuel zip creation failed (%s): %s', rec.id, ex)
        flash('Unable to prepare media ZIP right now.', 'danger')
        return redirect(url_for('fuel_expense_media', pk=rec.id))

    @after_this_request
    def _cleanup_fuel_zip(resp):
        try:
            os.remove(zip_path)
        except OSError:
            pass
        return resp

    veh = secure_filename((rec.vehicle.vehicle_no if rec.vehicle else 'vehicle') or 'vehicle')
    date_part = rec.fueling_date.strftime('%Y%m%d') if rec.fueling_date else pk_now().strftime('%Y%m%d')
    archive_name = f'fuel_media_{veh}_{date_part}.zip'
    return send_file(zip_path, as_attachment=True, download_name=archive_name, mimetype='application/zip', max_age=0)


@app.route('/oil-expense/<int:pk>/media')
@app.route('/oil-expenses/<int:pk>/media')
def oil_expense_media(pk):
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return _guard
    workspace_employee_id = _workspace_employee_id_for_expenses()
    rec = OilExpense.query.filter_by(id=pk).first()
    if not rec:
        flash('Media record not found (maybe deleted).', 'warning')
        return redirect(url_for('oil_expense_list'))
    if workspace_employee_id and rec.employee_id and rec.employee_id != workspace_employee_id:
        flash('This expense does not belong to selected workspace employee.', 'danger')
        return redirect(url_for('oil_expense_list'))

    def _human_size(n):
        if n is None:
            return ''
        size = float(n)
        units = ['B', 'KB', 'MB', 'GB', 'TB']
        idx = 0
        while size >= 1024 and idx < len(units) - 1:
            size /= 1024.0
            idx += 1
        if idx == 0:
            return f"{int(size)} {units[idx]}"
        return f"{size:.1f} {units[idx]}"

    media_items = []
    for att in rec.attachments.order_by(OilExpenseAttachment.created_at.asc(), OilExpenseAttachment.id.asc()).all():
        url = media_url_filter(att.file_path or '')
        if not url:
            continue
        ftype = (att.file_type or '').strip().lower()
        if ftype not in ('image', 'video'):
            path = (att.file_path or '').lower()
            if any(path.endswith(x) for x in ('.mp4', '.webm', '.mov')):
                ftype = 'video'
            else:
                ftype = 'image'
        local_full = _maintenance_attachment_local_full_path(att.file_path or '')
        size_bytes = os.path.getsize(local_full) if local_full else None
        created_at = att.created_at
        media_items.append({
            'url': url,
            'type': ftype,
            'name': att.original_name or os.path.basename(att.file_path or '') or 'Attachment',
            'created_at': created_at.strftime('%d-%m-%Y %I:%M %p') if created_at else '',
            'created_at_iso': created_at.isoformat() if created_at else '',
            'size_bytes': size_bytes,
            'size_label': _human_size(size_bytes),
            'download_url': url_for('oil_expense_media_download', pk=rec.id, att_id=att.id),
            'is_local_file': bool(local_full),
        })
    date_label = rec.expense_date.strftime('%d-%m-%Y') if rec.expense_date else '-'
    return render_template(
        'maintenance_expense_media.html',
        rec=rec,
        media_items=media_items,
        media_title='Oil Media Gallery',
        media_date_label=date_label,
        back_url=url_for('oil_expense_list'),
        download_all_url=url_for('oil_expense_media_download_all', pk=rec.id),
    )


@app.route('/oil-expense/<int:pk>/media/download/<int:att_id>')
@app.route('/oil-expenses/<int:pk>/media/download/<int:att_id>')
def oil_expense_media_download(pk, att_id):
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return _guard
    workspace_employee_id = _workspace_employee_id_for_expenses()
    rec = OilExpense.query.filter_by(id=pk).first()
    if not rec:
        flash('Media record not found (maybe deleted).', 'warning')
        return redirect(url_for('oil_expense_list'))
    if workspace_employee_id and rec.employee_id and rec.employee_id != workspace_employee_id:
        flash('This expense does not belong to selected workspace employee.', 'danger')
        return redirect(url_for('oil_expense_list'))
    att = OilExpenseAttachment.query.filter_by(id=att_id, oil_expense_id=rec.id).first()
    if not att:
        flash('Attachment not found.', 'warning')
        return redirect(url_for('oil_expense_media', pk=rec.id))

    dl_name = _maintenance_attachment_download_name(att)
    local_full = _maintenance_attachment_local_full_path(att.file_path or '')
    if local_full:
        return send_file(local_full, as_attachment=True, download_name=dl_name, conditional=True, max_age=0)
    try:
        blob, mime = _maintenance_attachment_read_bytes(att.file_path or '')
    except Exception as ex:
        app.logger.warning('Oil media download failed (%s): %s', att.id, ex)
        flash('Download failed for this attachment.', 'danger')
        return redirect(url_for('oil_expense_media', pk=rec.id))
    if not blob:
        flash('Attachment file is empty.', 'warning')
        return redirect(url_for('oil_expense_media', pk=rec.id))
    return send_file(BytesIO(blob), as_attachment=True, download_name=dl_name, mimetype=(mime or 'application/octet-stream'), max_age=0)


@app.route('/oil-expense/<int:pk>/media/download-all')
@app.route('/oil-expenses/<int:pk>/media/download-all')
def oil_expense_media_download_all(pk):
    _guard = _require_workspace_employee_for_expense_management()
    if _guard:
        return _guard
    workspace_employee_id = _workspace_employee_id_for_expenses()
    rec = OilExpense.query.filter_by(id=pk).first()
    if not rec:
        flash('Media record not found (maybe deleted).', 'warning')
        return redirect(url_for('oil_expense_list'))
    if workspace_employee_id and rec.employee_id and rec.employee_id != workspace_employee_id:
        flash('This expense does not belong to selected workspace employee.', 'danger')
        return redirect(url_for('oil_expense_list'))
    atts = rec.attachments.order_by(OilExpenseAttachment.created_at.asc(), OilExpenseAttachment.id.asc()).all()
    if not atts:
        flash('No media files available for download.', 'warning')
        return redirect(url_for('oil_expense_media', pk=rec.id))

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
    zip_path = tmp.name
    tmp.close()
    added = 0
    used = set()
    try:
        with zipfile.ZipFile(zip_path, mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
            for att in atts:
                base_name = _maintenance_attachment_download_name(att)
                file_name = base_name
                n = 2
                while file_name.lower() in used:
                    root, ext = os.path.splitext(base_name)
                    file_name = f'{root}_{n}{ext}'
                    n += 1
                used.add(file_name.lower())
                local_full = _maintenance_attachment_local_full_path(att.file_path or '')
                if local_full:
                    try:
                        zf.write(local_full, arcname=file_name)
                        added += 1
                        continue
                    except Exception:
                        pass
                try:
                    blob, _mime = _maintenance_attachment_read_bytes(att.file_path or '')
                    if blob:
                        zf.writestr(file_name, blob)
                        added += 1
                except Exception:
                    pass
        if added == 0:
            try:
                os.remove(zip_path)
            except OSError:
                pass
            flash('No files could be packed for download.', 'danger')
            return redirect(url_for('oil_expense_media', pk=rec.id))
    except Exception as ex:
        try:
            os.remove(zip_path)
        except OSError:
            pass
        app.logger.warning('Oil zip creation failed (%s): %s', rec.id, ex)
        flash('Unable to prepare media ZIP right now.', 'danger')
        return redirect(url_for('oil_expense_media', pk=rec.id))

    @after_this_request
    def _cleanup_oil_zip(resp):
        try:
            os.remove(zip_path)
        except OSError:
            pass
        return resp

    veh = secure_filename((rec.vehicle.vehicle_no if rec.vehicle else 'vehicle') or 'vehicle')
    date_part = rec.expense_date.strftime('%Y%m%d') if rec.expense_date else pk_now().strftime('%Y%m%d')
    archive_name = f'oil_media_{veh}_{date_part}.zip'
    return send_file(zip_path, as_attachment=True, download_name=archive_name, mimetype='application/zip', max_age=0)

