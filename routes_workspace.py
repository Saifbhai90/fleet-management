import difflib
import json
import os
import re
import tempfile
import zipfile
from datetime import datetime, date, timedelta
from calendar import monthrange
from decimal import Decimal, InvalidOperation
from io import BytesIO

from flask import flash, redirect, render_template, request, session, url_for, make_response, jsonify, send_file, after_this_request, current_app
from werkzeug.utils import secure_filename
from sqlalchemy import and_, or_, not_, cast, String, select, exists, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased, joinedload

from models import (
    db, Employee, Driver, Party, Account, District, Project, Vehicle,
    VehicleDailyTask,
    JournalEntry, JournalEntryLine,
    EmployeeAssignment, FundTransfer, FundTransferCategory,
    WorkspaceParty, WorkspaceProduct, WorkspaceAccount,
    WorkspaceExpense, WorkspaceOpeningExpense, WorkspaceFuelOilOpeningExpense, WorkspaceFundTransfer, WorkspaceJournalEntry, WorkspaceJournalEntryLine, WorkspaceMonthClose, WorkspaceFuelOilMonthClose,
    WorkspaceSlipProfile, WorkspaceSlipProfileField,
    WorkspaceMpgReportInput,
    FuelExpense, OilExpense, MaintenanceExpense, EmployeeExpense,
)
from routes_finance import check_auth, _ft_media_items_from_path
from auth_utils import get_user_context
from finance_utils import (
    get_account_ledger,
    ensure_workspace_base_accounts,
    ensure_workspace_opening_expense_accounts,
    ensure_workspace_fuel_oil_opening_accounts,
    ensure_workspace_counterparty_account,
    reconcile_workspace_opening_expense_postings,
    workspace_post_expense,
    workspace_post_opening_expense,
    workspace_post_fuel_oil_opening_expense,
    workspace_post_transfer,
    workspace_reverse_journal_entry,
    reverse_company_journal_entry,
    workspace_get_account_ledger,
    workspace_close_month,
    workspace_close_fuel_oil_month,
)
from utils import pk_date, parse_date, generate_excel_template


def _upload_workspace_transfer_attachment(file_storage):
    if not file_storage or not getattr(file_storage, "filename", None):
        return None
    try:
        from r2_storage import upload_image_file as _r2_up, R2_PUBLIC_URL, R2_ACCESS_KEY_ID, R2_ENDPOINT_URL, R2_BUCKET_NAME
        if not all([R2_PUBLIC_URL, R2_ACCESS_KEY_ID, R2_ENDPOINT_URL, R2_BUCKET_NAME]):
            return None
        file_storage.seek(0)
        return _r2_up(file_storage, folder="workspace_transfers")
    except Exception:
        return None


def _delete_workspace_transfer_attachment(url):
    if not url:
        return
    try:
        from r2_storage import delete_file_by_url
        delete_file_by_url(url)
    except Exception:
        pass


def _ws_ft_attachment_download_name(stored_path, display_name='Receipt'):
    name = secure_filename((display_name or '').strip())
    path_only = (stored_path or '').split('?')[0]
    if not name or name.lower() == 'receipt':
        name = secure_filename(os.path.basename(path_only.replace('\\', '/'))) or 'receipt'
    if '.' not in name:
        low = path_only.lower()
        if any(low.endswith(x) for x in ('.mp4', '.webm', '.mov', '.m4v')):
            name += '.mp4'
        elif low.endswith('.pdf'):
            name += '.pdf'
        else:
            name += '.jpg'
    return name


def _ws_ft_read_attachment_bytes(stored_path):
    from routes import _maintenance_attachment_read_bytes
    return _maintenance_attachment_read_bytes(stored_path)


def _ws_ft_media_items_for_transfer(row):
    items = _ft_media_items_from_path(row.attachment, 'Receipt')
    if not items:
        return []
    for item in items:
        item['download_url'] = url_for('workspace_fund_transfer_media_download', pk=row.id)
    return items


def _ws_ft_get_transfer_for_media(pk):
    guard, emp = _workspace_guard('workspace_transfer_list')
    if guard:
        return guard, None
    row = WorkspaceFundTransfer.query.filter_by(employee_id=emp.id, id=pk).first()
    if not row:
        flash('Transfer not found.', 'warning')
        return redirect(url_for('workspace_fund_transfers_list')), None
    return None, row


def _workspace_multi_word_filter(search_text, *columns):
    words = [w.strip() for w in (search_text or "").split() if w.strip()]
    if not words:
        return None
    and_parts = []
    for word in words:
        pattern = f"%{word}%"
        and_parts.append(or_(*[col.ilike(pattern) for col in columns]))
    return and_(*and_parts)


def _workspace_driver_vehicle_no(drv):
    if not drv:
        return None
    if getattr(drv, "vehicle", None) and getattr(drv.vehicle, "vehicle_no", None):
        return drv.vehicle.vehicle_no
    if getattr(drv, "vehicle_id", None):
        v = db.session.get(Vehicle, drv.vehicle_id)
        if v and v.vehicle_no:
            return v.vehicle_no
    v = Vehicle.query.filter_by(driver_id=drv.id).order_by(Vehicle.id.desc()).first()
    return v.vehicle_no if v and v.vehicle_no else None


def _build_workspace_account_display_map(employee_id, active_only=True):
    """Label for workspace accounts; driver-linked rows include vehicle no (same as transfer form dropdown)."""
    q = WorkspaceAccount.query.filter_by(employee_id=employee_id)
    if active_only:
        q = q.filter_by(is_active=True)
    accounts = q.order_by(WorkspaceAccount.code).all()
    driver_ids = sorted(
        int(a.entity_id)
        for a in accounts
        if (a.entity_type or "").strip().lower() == "driver" and a.entity_id
    )
    drivers_by_id = {}
    if driver_ids:
        for drv in Driver.query.options(joinedload(Driver.vehicle)).filter(Driver.id.in_(driver_ids)).all():
            drivers_by_id[int(drv.id)] = drv
    account_display_map = {}
    for a in accounts:
        base = f"{a.code} - {a.name}"
        if (a.entity_type or "").strip().lower() == "driver" and a.entity_id:
            drv = drivers_by_id.get(int(a.entity_id))
            if drv:
                v_no = _workspace_driver_vehicle_no(drv)
                if v_no:
                    base = f"{base} | Vehicle: {v_no}"
        account_display_map[a.id] = base
    return account_display_map


def _workspace_fund_transfer_search_like_variants(word):
    """Plain and hyphen/space-stripped ILIKE patterns (e.g. LEG181076 matches LEG-18-1076)."""
    w = (word or "").strip()
    like = f"%{w}%"
    compact = re.sub(r"[\s\-]+", "", w)
    like_compact = f"%{compact}%" if compact else like
    return like, like_compact


def _workspace_fund_transfer_vehicle_no_match(veh_col, like, like_compact):
    bare = func.replace(func.replace(func.coalesce(veh_col, ""), "-", ""), " ", "")
    return or_(veh_col.ilike(like), bare.ilike(like_compact))


def _workspace_fund_transfer_driver_vehicle_match(drv, veh, like, like_compact):
    return or_(
        drv.name.ilike(like),
        func.coalesce(drv.driver_id, "").ilike(like),
        _workspace_fund_transfer_vehicle_no_match(veh.vehicle_no, like, like_compact),
    )


def _workspace_fund_transfer_account_driver_vehicle_match(acct_alias, like, like_compact):
    """Match driver-linked From/To accounts by driver name, driver ID, or vehicle number."""
    drv = aliased(Driver)
    veh = aliased(Vehicle)
    et = func.lower(func.trim(func.coalesce(acct_alias.entity_type, "")))
    return exists(
        select(1)
        .select_from(drv)
        .outerjoin(veh, or_(veh.id == drv.vehicle_id, veh.driver_id == drv.id))
        .where(
            et == "driver",
            acct_alias.entity_id.isnot(None),
            acct_alias.entity_id == drv.id,
            _workspace_fund_transfer_driver_vehicle_match(drv, veh, like, like_compact),
        )
    )


def _workspace_fund_transfer_to_driver_id_match(like, like_compact):
    """Match transfer.to_driver_id when set (driver / vehicle on To side)."""
    drv = aliased(Driver)
    veh = aliased(Vehicle)
    return exists(
        select(1)
        .select_from(drv)
        .outerjoin(veh, or_(veh.id == drv.vehicle_id, veh.driver_id == drv.id))
        .where(
            WorkspaceFundTransfer.to_driver_id.isnot(None),
            WorkspaceFundTransfer.to_driver_id == drv.id,
            _workspace_fund_transfer_driver_vehicle_match(drv, veh, like, like_compact),
        )
    )


def _workspace_fund_transfer_search_filter(query, search, from_acct, to_acct):
    """Search all visible transfer columns including driver vehicle numbers on From/To."""
    words = [w.strip() for w in (search or "").split() if w.strip()]
    if not words:
        return query
    amt_col = cast(WorkspaceFundTransfer.amount, String)
    date_col = cast(WorkspaceFundTransfer.transfer_date, String)
    for w in words:
        like, like_compact = _workspace_fund_transfer_search_like_variants(w)
        query = query.filter(
            or_(
                WorkspaceFundTransfer.transfer_number.ilike(like),
                WorkspaceFundTransfer.category.ilike(like),
                WorkspaceFundTransfer.payment_mode.ilike(like),
                WorkspaceFundTransfer.reference_no.ilike(like),
                WorkspaceFundTransfer.description.ilike(like),
                amt_col.ilike(like),
                date_col.ilike(like),
                from_acct.code.ilike(like),
                from_acct.name.ilike(like),
                from_acct.account_type.ilike(like),
                func.coalesce(from_acct.description, "").ilike(like),
                to_acct.code.ilike(like),
                to_acct.name.ilike(like),
                to_acct.account_type.ilike(like),
                func.coalesce(to_acct.description, "").ilike(like),
                _workspace_fund_transfer_account_driver_vehicle_match(from_acct, like, like_compact),
                _workspace_fund_transfer_account_driver_vehicle_match(to_acct, like, like_compact),
                _workspace_fund_transfer_to_driver_id_match(like, like_compact),
            )
        )
    return query


def _get_workspace_employee():
    emp_id = session.get("workspace_employee_id")
    if not emp_id:
        return None
    return db.session.get(Employee, emp_id)


def _can_access_employee(employee_id):
    """Workspace isolation guard:
    - Master/Admin can open any employee workspace.
    - Employee-linked users can open only their own employee workspace.
    """
    user_id = session.get("user_id")
    if not user_id:
        return False
    ctx = get_user_context(user_id)
    if ctx.get("is_master_or_admin"):
        return True
    emp = ctx.get("employee_record")
    return bool(emp and emp.id == employee_id)


def _workspace_guard(permission_code="workspace_dashboard"):
    auth = check_auth(permission_code)
    if auth:
        return auth, None
    emp = _get_workspace_employee()
    if not emp:
        flash("Please select employee first to open workspace.", "warning")
        return redirect(url_for("workspace_dashboard")), None
    if not _can_access_employee(emp.id):
        session.pop("workspace_employee_id", None)
        flash("You cannot access another employee workspace.", "danger")
        return redirect(url_for("workspace_dashboard")), None
    return None, emp


# Workspace product: normalized name + fuzzy "same word different spelling" guard
_WS_PROD_SIMILAR_MIN = 0.86


def _normalize_ws_product_name(s):
    if s is None:
        return ""
    s = str(s).strip()
    s = re.sub(r"\s+", " ", s)
    return s.lower()


def _ws_product_name_similarity(norm_a, norm_b):
    if not norm_a or not norm_b:
        return 0.0
    if norm_a == norm_b:
        return 1.0
    return difflib.SequenceMatcher(None, norm_a, norm_b).ratio()


def _workspace_product_name_conflicts(employee_id, name, exclude_id=None):
    """exact = duplicate normalized name; similar = best fuzzy match in [_WS_PROD_SIMILAR_MIN, 1)."""
    norm = _normalize_ws_product_name(name)
    out = {"exact": None, "similar": None, "similarity": 0.0}
    if not norm:
        return out
    q = WorkspaceProduct.query.filter_by(employee_id=employee_id)
    if exclude_id:
        q = q.filter(WorkspaceProduct.id != exclude_id)
    best_p, best_r = None, 0.0
    for p in q.all():
        pn = _normalize_ws_product_name(p.name)
        if pn == norm:
            out["exact"] = p
            return out
        r = _ws_product_name_similarity(norm, pn)
        if r >= _WS_PROD_SIMILAR_MIN and r > best_r:
            best_p, best_r = p, r
    if best_p:
        out["similar"], out["similarity"] = best_p, best_r
    return out


def _workspace_party_name_conflicts(employee_id, name, exclude_id=None):
    """Same as workspace product: unique (employee, name) on workspace_party."""
    norm = _normalize_ws_product_name(name)
    out = {"exact": None, "similar": None, "similarity": 0.0}
    if not norm:
        return out
    q = WorkspaceParty.query.filter_by(employee_id=employee_id)
    if exclude_id:
        q = q.filter(WorkspaceParty.id != exclude_id)
    best_p, best_r = None, 0.0
    for p in q.all():
        pn = _normalize_ws_product_name(p.name)
        if pn == norm:
            out["exact"] = p
            return out
        r = _ws_product_name_similarity(norm, pn)
        if r >= _WS_PROD_SIMILAR_MIN and r > best_r:
            best_p, best_r = p, r
    if best_p:
        out["similar"], out["similarity"] = best_p, best_r
    return out


def _is_master_or_admin_user():
    user_id = session.get("user_id")
    if not user_id:
        return False
    ctx = get_user_context(user_id)
    return bool(ctx.get("is_master_or_admin"))


def _can_manage_slip_profiles():
    """Master: no permission required. Others: workspace_slip_design_manage via Role Management."""
    if session.get('is_master'):
        return True
    user_id = session.get("user_id")
    if not user_id:
        return False
    from models import User
    from auth_utils import user_can_access
    user = db.session.get(User, user_id)
    if not user or not user.role:
        return False
    codes = [p.code for p in (user.role.permissions or [])]
    return user_can_access(codes, 'workspace_slip_design_manage')


def _workspace_has_closed_month_for_date(employee_id, target_date, district_id=None, project_id=None):
    if not employee_id or not target_date:
        return False
    q = db.session.query(WorkspaceMonthClose.id).filter(
        WorkspaceMonthClose.employee_id == employee_id,
        WorkspaceMonthClose.status == "Closed",
        WorkspaceMonthClose.period_start <= target_date,
        WorkspaceMonthClose.period_end >= target_date,
    )
    # Match the exact scope (district/project). A close in one scope
    # must not block postings for another district/project.
    if district_id is None:
        q = q.filter(WorkspaceMonthClose.district_id.is_(None))
    else:
        q = q.filter(WorkspaceMonthClose.district_id == district_id)
    if project_id is None:
        q = q.filter(WorkspaceMonthClose.project_id.is_(None))
    else:
        q = q.filter(WorkspaceMonthClose.project_id == project_id)
    return q.first() is not None


def _workspace_has_closed_fuel_oil_month_for_date(employee_id, target_date, district_id=None, project_id=None):
    if not employee_id or not target_date:
        return False
    q = db.session.query(WorkspaceFuelOilMonthClose.id).filter(
        WorkspaceFuelOilMonthClose.employee_id == employee_id,
        WorkspaceFuelOilMonthClose.status == "Closed",
        WorkspaceFuelOilMonthClose.period_start <= target_date,
        WorkspaceFuelOilMonthClose.period_end >= target_date,
    )
    # Match the exact scope (district/project). A close in one scope
    # must not block postings for another district/project.
    if district_id is None:
        q = q.filter(WorkspaceFuelOilMonthClose.district_id.is_(None))
    else:
        q = q.filter(WorkspaceFuelOilMonthClose.district_id == district_id)
    if project_id is None:
        q = q.filter(WorkspaceFuelOilMonthClose.project_id.is_(None))
    else:
        q = q.filter(WorkspaceFuelOilMonthClose.project_id == project_id)
    return q.first() is not None


def _pending_month_close_spells(employee_id):
    """
    Build month-close spell summary (01-15, 16-last-day) for unclosed rows.
    Only include spells with amount > 0 and with district/project available.
    """
    bucket = {}

    def _spell_key(dt):
        y, m = dt.year, dt.month
        last = monthrange(y, m)[1]
        if dt.day <= 15:
            return y, m, 1, 15
        return y, m, 16, last

    def _add_bucket(exp_date, district_id, project_id, amount):
        if not exp_date or not district_id or not project_id:
            return False
        amt = Decimal(str(amount or 0))
        if amt <= 0:
            return False
        y, m, sday, eday = _spell_key(exp_date)
        k = (district_id, project_id, y, m, sday, eday)
        bucket[k] = bucket.get(k, Decimal("0")) + amt
        return True

    # Opening expenses (always scoped by district/project).
    for row in WorkspaceOpeningExpense.query.filter(
        WorkspaceOpeningExpense.employee_id == employee_id,
        WorkspaceOpeningExpense.month_close_id.is_(None),
        WorkspaceOpeningExpense.total_expense > 0,
    ).all():
        _add_bucket(row.opening_date, row.district_id, row.project_id, row.total_expense)

    # Regular workspace expenses.
    # Backward compatibility: some setups don't have district/project columns in workspace_expense.
    # In that case, resolve scope from source form row via expense_number (FuelExpense-123, etc.).
    has_dist = hasattr(WorkspaceExpense, "district_id")
    has_proj = hasattr(WorkspaceExpense, "project_id")
    covered_expense_numbers = set()
    closed_expense_numbers = {
        (r[0] or "").strip()
        for r in db.session.query(WorkspaceExpense.expense_number).filter(
            WorkspaceExpense.employee_id == employee_id,
            WorkspaceExpense.month_close_id.isnot(None),
        ).all()
        if r and r[0]
    }
    for row in WorkspaceExpense.query.filter(
        WorkspaceExpense.employee_id == employee_id,
        WorkspaceExpense.month_close_id.is_(None),
        WorkspaceExpense.amount > 0,
    ).all():
        district_id = getattr(row, "district_id", None) if has_dist else None
        project_id = getattr(row, "project_id", None) if has_proj else None
        exp_date = getattr(row, "expense_date", None)
        exp_no = (getattr(row, "expense_number", None) or "").strip()

        if (not district_id or not project_id) and exp_no and "-" in exp_no:
            ref_type, ref_id = exp_no.split("-", 1)
            ref_obj = None
            try:
                ref_id_int = int(ref_id)
            except (TypeError, ValueError):
                ref_id_int = None
            if ref_id_int:
                if ref_type == "FuelExpense":
                    ref_obj = db.session.get(FuelExpense, ref_id_int)
                    if ref_obj:
                        exp_date = exp_date or ref_obj.fueling_date
                elif ref_type == "OilExpense":
                    ref_obj = db.session.get(OilExpense, ref_id_int)
                    if ref_obj:
                        exp_date = exp_date or ref_obj.expense_date
                elif ref_type == "MaintenanceExpense":
                    ref_obj = db.session.get(MaintenanceExpense, ref_id_int)
                    if ref_obj:
                        exp_date = exp_date or ref_obj.expense_date
                elif ref_type == "EmployeeExpense":
                    ref_obj = db.session.get(EmployeeExpense, ref_id_int)
                    if ref_obj:
                        exp_date = exp_date or ref_obj.expense_date
                if ref_obj:
                    district_id = district_id or getattr(ref_obj, "district_id", None)
                    project_id = project_id or getattr(ref_obj, "project_id", None)

        if _add_bucket(exp_date, district_id, project_id, row.amount) and exp_no:
            covered_expense_numbers.add(exp_no)

    # Fallback source scan: if regular sync is missing for any form row,
    # still show it in pending spell summary.
    for row in FuelExpense.query.filter(
        FuelExpense.employee_id == employee_id,
        FuelExpense.amount > 0,
    ).all():
        exp_no = f"FuelExpense-{row.id}"
        if exp_no in covered_expense_numbers or exp_no in closed_expense_numbers:
            continue
        _add_bucket(row.fueling_date, row.district_id, row.project_id, row.amount)

    for row in OilExpense.query.filter(
        OilExpense.employee_id == employee_id,
        OilExpense.total_bill_amount > 0,
    ).all():
        exp_no = f"OilExpense-{row.id}"
        if exp_no in covered_expense_numbers or exp_no in closed_expense_numbers:
            continue
        _add_bucket(row.expense_date, row.district_id, row.project_id, row.total_bill_amount)

    for row in MaintenanceExpense.query.filter(
        MaintenanceExpense.employee_id == employee_id,
        MaintenanceExpense.total_bill_amount > 0,
    ).all():
        exp_no = f"MaintenanceExpense-{row.id}"
        if exp_no in covered_expense_numbers or exp_no in closed_expense_numbers:
            continue
        _add_bucket(row.expense_date, row.district_id, row.project_id, row.total_bill_amount)

    for row in EmployeeExpense.query.filter(
        EmployeeExpense.employee_id == employee_id,
        EmployeeExpense.amount > 0,
    ).all():
        exp_no = f"EmployeeExpense-{row.id}"
        if exp_no in covered_expense_numbers or exp_no in closed_expense_numbers:
            continue
        _add_bucket(row.expense_date, row.district_id, row.project_id, row.amount)

    if not bucket:
        return []

    district_map = {d.id: d.name for d in District.query.all()}
    project_map = {p.id: p.name for p in Project.query.all()}
    out = []
    for (district_id, project_id, y, m, sday, eday), amt in bucket.items():
        if amt <= 0:
            continue
        start_dt = date(y, m, sday)
        end_dt = date(y, m, eday)
        out.append({
            "district_id": district_id,
            "project_id": project_id,
            "district_name": district_map.get(district_id, "-"),
            "project_name": project_map.get(project_id, "-"),
            "period_start": start_dt,
            "period_end": end_dt,
            "spell_label": f"{sday:02d}-{eday:02d}({start_dt.strftime('%m-%y')})",
            "amount": amt,
        })
    out.sort(key=lambda r: (r["period_start"], r["district_name"], r["project_name"]), reverse=True)
    return out


def _list_employees_for_workspace():
    user_id = session.get("user_id")
    if not user_id:
        return []
    ctx = get_user_context(user_id)
    if ctx.get("is_master_or_admin"):
        return Employee.query.filter_by(status="Active").order_by(Employee.name).all()
    emp = ctx.get("employee_record")
    if emp and emp.status == "Active":
        return [emp]
    return []


def _get_employee_scope_summary(employee):
    """Resolve assigned district/project labels for dashboard header."""
    if not employee:
        return {"districts": [], "projects": []}
    districts = [d.name for d in employee.districts.order_by(District.name).all()]
    projects = [p.name for p in employee.projects.order_by(Project.name).all()]

    # Fallback for legacy setups: read from assignment history if M2M is empty.
    if not districts:
        rows = EmployeeAssignment.query.filter(
            EmployeeAssignment.employee_id == employee.id,
            EmployeeAssignment.action.in_(["assign_district", "initial"]),
            EmployeeAssignment.district_id.isnot(None),
        ).order_by(EmployeeAssignment.effective_date.desc(), EmployeeAssignment.id.desc()).all()
        seen = set()
        for r in rows:
            if r.district and r.district.name not in seen:
                districts.append(r.district.name)
                seen.add(r.district.name)
    if not projects:
        rows = EmployeeAssignment.query.filter(
            EmployeeAssignment.employee_id == employee.id,
            EmployeeAssignment.action.in_(["assign_project", "initial"]),
            EmployeeAssignment.project_id.isnot(None),
        ).order_by(EmployeeAssignment.effective_date.desc(), EmployeeAssignment.id.desc()).all()
        seen = set()
        for r in rows:
            if r.project and r.project.name not in seen:
                projects.append(r.project.name)
                seen.add(r.project.name)
    return {"districts": districts, "projects": projects}


def _ensure_workspace_driver_accounts(employee):
    """Auto-load driver accounts for assigned district/project scope into workspace COA."""
    if not employee:
        return 0
    ensure_workspace_base_accounts(employee.id)
    district_ids = [d.id for d in employee.districts.all()]
    project_ids = [p.id for p in employee.projects.all()]
    if not district_ids and not project_ids:
        return 0
    q = Driver.query.filter_by(status="Active")
    if district_ids:
        q = q.filter(Driver.district_id.in_(district_ids))
    if project_ids:
        q = q.filter(Driver.project_id.in_(project_ids))
    candidates = q.order_by(Driver.name).all()
    if not candidates:
        return 0
    candidate_ids = [int(d.id) for d in candidates]
    existing_ids = {
        int(r[0]) for r in db.session.query(WorkspaceAccount.entity_id).filter(
            WorkspaceAccount.employee_id == employee.id,
            WorkspaceAccount.entity_type == "driver",
            WorkspaceAccount.entity_id.in_(candidate_ids),
        ).all() if r and r[0]
    }
    created = 0
    for drv in candidates:
        if int(drv.id) in existing_ids:
            continue
        ensure_workspace_counterparty_account(employee.id, driver_id=drv.id)
        created += 1
    return created


def workspace_dashboard():
    auth = check_auth("workspace_dashboard")
    if auth:
        return auth
    employees = _list_employees_for_workspace()
    selected_employee = _get_workspace_employee()
    # If employee is already selected and still accessible, jump straight to workspace home.
    if selected_employee and _can_access_employee(selected_employee.id):
        resp = make_response(redirect(url_for("workspace_home")))
        resp.set_cookie("workspace_sidebar_open", "0", max_age=31536000, path="/", samesite="Lax")
        return resp

    # If user can access exactly one employee, auto-select and auto-load workspace.
    if len(employees) == 1:
        only_emp = employees[0]
        session["workspace_employee_id"] = only_emp.id
        ensure_workspace_base_accounts(only_emp.id)
        db.session.commit()
        resp = make_response(redirect(url_for("workspace_home")))
        resp.set_cookie("workspace_sidebar_open", "0", max_age=31536000, path="/", samesite="Lax")
        return resp

    resp = make_response(render_template("workspace/select_employee.html", employees=employees, selected_employee=selected_employee))
    resp.set_cookie("workspace_sidebar_open", "0", max_age=31536000, path="/", samesite="Lax")
    return resp


def workspace_home():
    guard, emp = _workspace_guard("workspace_dashboard")
    if guard:
        return guard
    _ensure_workspace_driver_accounts(emp)
    db.session.commit()
    scope = _get_employee_scope_summary(emp)
    fuel_expenses = Decimal(str(
        db.session.query(db.func.coalesce(db.func.sum(FuelExpense.amount), 0))
        .filter(FuelExpense.employee_id == emp.id)
        .scalar() or 0
    ))
    oil_expenses = Decimal(str(
        db.session.query(db.func.coalesce(db.func.sum(OilExpense.total_bill_amount), 0))
        .filter(OilExpense.employee_id == emp.id)
        .scalar() or 0
    ))
    maintenance_expenses = Decimal(str(
        db.session.query(db.func.coalesce(db.func.sum(MaintenanceExpense.total_bill_amount), 0))
        .filter(MaintenanceExpense.employee_id == emp.id)
        .scalar() or 0
    ))
    employee_expenses = Decimal(str(
        db.session.query(db.func.coalesce(db.func.sum(EmployeeExpense.amount), 0))
        .filter(EmployeeExpense.employee_id == emp.id)
        .scalar() or 0
    ))
    opening_expenses = Decimal(str(
        db.session.query(db.func.coalesce(db.func.sum(WorkspaceOpeningExpense.total_expense), 0))
        .filter(WorkspaceOpeningExpense.employee_id == emp.id)
        .scalar() or 0
    ))
    fuel_oil_openings = Decimal(str(
        db.session.query(db.func.coalesce(db.func.sum(WorkspaceFuelOilOpeningExpense.total_amount), 0))
        .filter(WorkspaceFuelOilOpeningExpense.employee_id == emp.id)
        .scalar() or 0
    ))
    total_expenses = (
        fuel_expenses
        + oil_expenses
        + maintenance_expenses
        + employee_expenses
        + opening_expenses
        + fuel_oil_openings
    )
    total_transfers = sum((x.amount or 0) for x in WorkspaceFundTransfer.query.filter_by(employee_id=emp.id).all())

    # Live ledger position:
    # User convention for dashboard card:
    # last ledger balance + total credit posted under close categories.
    wallet_balance = Decimal("0")
    close_credit_total = Decimal("0")
    wallet_acct = db.session.get(Account, emp.wallet_account_id) if emp.wallet_account_id else None
    if wallet_acct:
        # Use ledger closing balance (last running balance) as source of truth.
        ledger_data = get_account_ledger(wallet_acct.id)
        if ledger_data and isinstance(ledger_data, dict):
            wallet_balance = Decimal(str(ledger_data.get("closing_balance") or 0))
        else:
            wallet_balance = Decimal(str(wallet_acct.current_balance or 0))
        rows = db.session.query(JournalEntryLine).join(JournalEntry).filter(
            JournalEntryLine.account_id == wallet_acct.id,
            JournalEntry.is_posted == True,
            JournalEntry.category.in_(["Workspace Close", "Workspace Fuel/Oil Close"]),
        ).all()
        for ln in rows:
            credit = Decimal(str(ln.credit or 0))
            if credit > 0:
                close_credit_total += credit

    adjusted_ledger_end = wallet_balance + close_credit_total
    # User convention: Net = Account Ledger End Balance - Total Expenses
    net_balance = adjusted_ledger_end - Decimal(str(total_expenses or 0))
    if net_balance > 0:
        net_balance_status = "Payable to Company"
    elif net_balance < 0:
        net_balance_status = "Receivable from Company"
    else:
        net_balance_status = "Settled"

    snapshot = _workspace_dashboard_financial_snapshot(emp.id)

    stats = {
        "parties": WorkspaceParty.query.filter_by(employee_id=emp.id, is_active=True).count(),
        "products": WorkspaceProduct.query.filter_by(employee_id=emp.id, is_active=True).count(),
        "expenses": total_expenses,
        "opening_expenses": opening_expenses,
        "fuel_oil_openings": fuel_oil_openings,
        "transfers": total_transfers,
        "ledger_end_balance": adjusted_ledger_end,
        "net_balance": net_balance,
        "net_balance_status": net_balance_status,
        "month_close_adjustment": close_credit_total,
        "bank_balance_total": snapshot["bank_total"],
        "receivable_total": snapshot["receivable_total"],
        "payable_total": snapshot["payable_total"],
        "open_closes": WorkspaceMonthClose.query.filter(
            WorkspaceMonthClose.employee_id == emp.id,
            WorkspaceMonthClose.status != "Closed",
        ).count(),
    }
    return render_template("workspace/dashboard.html", employee=emp, stats=stats, scope=scope)


def _workspace_dashboard_financial_snapshot(employee_id):
    accounts = (
        WorkspaceAccount.query
        .filter_by(employee_id=employee_id, is_active=True)
        .order_by(WorkspaceAccount.code.asc(), WorkspaceAccount.id.asc())
        .all()
    )
    account_ids = [a.id for a in accounts]
    jnl_map = {}
    if account_ids:
        rows = (
            db.session.query(
                WorkspaceJournalEntryLine.account_id,
                db.func.coalesce(db.func.sum(WorkspaceJournalEntryLine.debit), 0),
                db.func.coalesce(db.func.sum(WorkspaceJournalEntryLine.credit), 0),
            )
            .join(WorkspaceJournalEntry, WorkspaceJournalEntry.id == WorkspaceJournalEntryLine.journal_entry_id)
            .filter(
                WorkspaceJournalEntry.employee_id == employee_id,
                WorkspaceJournalEntry.is_posted == True,
                WorkspaceJournalEntryLine.account_id.in_(account_ids),
            )
            .group_by(WorkspaceJournalEntryLine.account_id)
            .all()
        )
        for r in rows:
            jnl_map[int(r[0])] = (Decimal(str(r[1] or 0)), Decimal(str(r[2] or 0)))

    party_ids = [a.entity_id for a in accounts if a.entity_type == "party" and a.entity_id]
    driver_ids = [a.entity_id for a in accounts if a.entity_type == "driver" and a.entity_id]
    party_map = {p.id: p for p in WorkspaceParty.query.filter(WorkspaceParty.id.in_(party_ids)).all()} if party_ids else {}
    driver_map = {d.id: d for d in Driver.query.filter(Driver.id.in_(driver_ids)).all()} if driver_ids else {}

    bank_keywords = (
        "bank", "hbl", "ubl", "mcb", "meezan", "alfalah", "allied", "askari", "faysal", "soneri", "habib",
        "easypaisa", "jazzcash", "jazz cash", "wallet",
    )

    def _signed_balance(acc, opening, debit, credit):
        if (acc.account_type or "") in ("Asset", "Expense"):
            return opening + debit - credit
        return opening + credit - debit

    def _side(acc_type, bal):
        if (acc_type or "") in ("Asset", "Expense"):
            return "Dr" if bal >= 0 else "Cr"
        return "Cr" if bal >= 0 else "Dr"

    def _display_name(acc):
        if acc.entity_type == "party" and acc.entity_id and acc.entity_id in party_map:
            p = party_map[acc.entity_id]
            p_type = (p.party_type or "").strip()
            return f"{p.name} ({p_type})" if p_type else p.name
        if acc.entity_type == "driver" and acc.entity_id and acc.entity_id in driver_map:
            d = driver_map[acc.entity_id]
            vehicle_no = d.vehicle.vehicle_no if getattr(d, "vehicle", None) else ""
            return f"{d.name} | {vehicle_no}" if vehicle_no else d.name
        return acc.name or "-"

    bank_rows = []
    receivable_rows = []
    payable_rows = []

    for acc in accounts:
        opening = Decimal(str(acc.opening_balance or 0))
        debit, credit = jnl_map.get(acc.id, (Decimal("0"), Decimal("0")))
        balance = _signed_balance(acc, opening, debit, credit)
        side = _side(acc.account_type, balance)
        row = {
            "account": acc,
            "display_name": _display_name(acc),
            "opening": opening,
            "debit": debit,
            "credit": credit,
            "balance": balance,
            "side": side,
            "abs_balance": abs(balance),
        }

        text_blob = f"{acc.code or ''} {acc.name or ''} {acc.description or ''}".lower()
        is_bank = (
            (acc.account_type == "Asset")
            and (acc.entity_type not in ("party", "driver"))
            and any(k in text_blob for k in bank_keywords)
        )
        if is_bank:
            bank_rows.append(row)

        if acc.entity_type in ("party", "driver"):
            # Counterparty accounts are Asset heads:
            # +ve (Dr) means receivable from party/driver, -ve (Cr) means payable to them.
            if balance > 0:
                rec_row = dict(row)
                rec_row["abs_balance"] = abs(balance)
                rec_row["side"] = "Dr"
                receivable_rows.append(rec_row)
            elif balance < 0:
                pay_row = dict(row)
                pay_row["abs_balance"] = abs(balance)
                pay_row["side"] = "Cr"
                payable_rows.append(pay_row)

    return {
        "bank_rows": bank_rows,
        "receivable_rows": receivable_rows,
        "payable_rows": payable_rows,
        "bank_total": sum((r["balance"] for r in bank_rows), Decimal("0")),
        "receivable_total": sum((r["abs_balance"] for r in receivable_rows), Decimal("0")),
        "payable_total": sum((r["abs_balance"] for r in payable_rows), Decimal("0")),
    }


def workspace_select_employee():
    auth = check_auth("workspace_dashboard")
    if auth:
        return auth
    emp_id = request.form.get("employee_id", type=int)
    emp = db.session.get(Employee, emp_id) if emp_id else None
    if not emp:
        flash("Select a valid employee.", "danger")
        return redirect(url_for("workspace_dashboard"))
    if not _can_access_employee(emp.id):
        flash("You cannot load this employee workspace.", "danger")
        return redirect(url_for("workspace_dashboard"))
    session["workspace_employee_id"] = emp.id
    ensure_workspace_base_accounts(emp.id)
    db.session.commit()
    flash(f"Workspace loaded for {emp.name}.", "success")
    return redirect(url_for("workspace_home"))


def workspace_clear_employee():
    auth = check_auth("workspace_dashboard")
    if auth:
        return auth
    session.pop("workspace_employee_id", None)
    flash("Workspace employee context cleared.", "info")
    return redirect(url_for("workspace_dashboard"))


def workspace_parties_list():
    guard, emp = _workspace_guard("workspace_party_list")
    if guard:
        return guard
    search = (request.args.get("search") or "").strip()
    party_type = (request.args.get("type") or "").strip()
    page = max(request.args.get("page", 1, type=int) or 1, 1)
    per_page = request.args.get("per_page", 20, type=int) or 20
    if per_page not in (10, 20, 50, 100):
        per_page = 20
    sort_by = (request.args.get("sort_by") or "name").strip()
    sort_order = (request.args.get("sort_order") or "asc").strip().lower()
    sort_order = "desc" if sort_order == "desc" else "asc"

    query = WorkspaceParty.query.filter_by(employee_id=emp.id)
    if party_type:
        query = query.filter(WorkspaceParty.party_type == party_type)
    if search:
        flt = _workspace_multi_word_filter(
            search,
            WorkspaceParty.name,
            WorkspaceParty.party_type,
            WorkspaceParty.contact,
            WorkspaceParty.phone,
            WorkspaceParty.address,
            WorkspaceParty.remarks,
        )
        if flt is not None:
            query = query.filter(flt)

    if sort_by == "district":
        query = query.outerjoin(District, WorkspaceParty.district_id == District.id)
        order_col = District.name
    elif sort_by == "party_type":
        order_col = WorkspaceParty.party_type
    elif sort_by == "contact":
        order_col = WorkspaceParty.contact
    elif sort_by == "status":
        order_col = WorkspaceParty.is_active
    else:
        order_col = WorkspaceParty.name
    if sort_order == "desc":
        order_col = order_col.desc()
    else:
        order_col = order_col.asc()

    pagination = query.order_by(order_col, WorkspaceParty.id.asc()).paginate(page=page, per_page=per_page, error_out=False)
    return render_template(
        "workspace/parties_list.html",
        rows=pagination.items,
        pagination=pagination,
        per_page=per_page,
        search=search,
        party_type=party_type,
        sort_by=sort_by,
        sort_order=sort_order,
        employee=emp,
    )


def _workspace_normalize_return_path(raw_next):
    """Return safe app-relative path+query for post-create redirects (accepts full or relative URLs)."""
    from urllib.parse import unquote, urlparse

    raw = unquote((raw_next or "").strip())
    if not raw or any(c in raw for c in "\n\r\x00"):
        return ""
    parsed = urlparse(raw)
    if parsed.scheme and parsed.netloc:
        path = parsed.path or ""
        query = parsed.query
    elif raw.startswith("/"):
        path, _, query = raw.partition("?")
    else:
        return ""
    if not path.startswith("/") or path.startswith("//") or len(path) > 500:
        return ""
    if len(query) > 4000:
        query = query[:4000]
    return path + ("?" + query if query else "")


def _append_url_query_params(url, extra_params=None, **query_kwargs):
    """Append query keys; always returns an app-relative redirect path when possible."""
    from urllib.parse import parse_qsl, urlencode

    merged = dict(extra_params or {})
    merged.update(query_kwargs or {})
    safe_path = _workspace_normalize_return_path(url)
    if not safe_path:
        return None
    path, _, query = safe_path.partition("?")
    q = dict(parse_qsl(query, keep_blank_values=True))
    for key, val in merged.items():
        if val is not None and str(val) != "":
            q[key] = str(val)
    new_query = urlencode(list(q.items()))
    out = path + ("?" + new_query if new_query else "")
    return out


def _workspace_party_form_prefill():
    return {
        "name": (request.form.get("name") or "").strip(),
        "party_type": (request.form.get("party_type") or "").strip(),
        "district_id": request.form.get("district_id", type=int),
        "contact": (request.form.get("contact") or "").strip(),
        "phone": (request.form.get("phone") or "").strip(),
        "address": (request.form.get("address") or "").strip(),
        "remarks": (request.form.get("remarks") or "").strip(),
        "is_active": request.form.get("is_active", "1"),
    }


def workspace_party_form(pk=None):
    guard, emp = _workspace_guard("workspace_party_edit" if pk else "workspace_party_add")
    if guard:
        return guard
    row = WorkspaceParty.query.filter_by(employee_id=emp.id, id=pk).first() if pk else None
    if pk and not row:
        flash("Party not found for selected workspace employee.", "danger")
        return redirect(url_for("workspace_parties_list"))

    districts = District.query.order_by(District.name).all()

    next_url = _workspace_normalize_return_path(
        request.args.get("next") or request.form.get("next") or ""
    )
    default_type = (request.args.get("type") or "").strip()

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("Party name is required.", "danger")
            return render_template(
                "workspace/party_form.html",
                row=row,
                employee=emp,
                districts=districts,
                next_url=next_url,
                default_type=default_type,
                party_form_values=_workspace_party_form_prefill(),
                show_similar_ack=False,
            )
        exid = row.id if row else None
        conf = _workspace_party_name_conflicts(emp.id, name, exclude_id=exid)
        if conf.get("exact"):
            ep = conf["exact"]
            flash(
                f'Yeh party pehle se maujood hai: “{ep.name}”. (Same naam — spacing/case alag ho sakta hai). Duplicate nahi bana sakte.',
                "danger",
            )
            return render_template(
                "workspace/party_form.html",
                row=row,
                employee=emp,
                districts=districts,
                next_url=next_url,
                default_type=default_type,
                party_form_values=_workspace_party_form_prefill(),
                show_similar_ack=False,
            )
        if conf.get("similar") and request.form.get("ack_similar") != "1":
            sp = conf["similar"]
            scr = int(round(float(conf.get("similarity") or 0) * 100))
            flash(
                f'Yeh naam maujood party “{sp.name}” se bahut milta-julta hai (~{scr}% match). Agar wohi nayi party nahi, pehle wala edit karein; warna neeche tick karke save karein.',
                "warning",
            )
            return render_template(
                "workspace/party_form.html",
                row=row,
                employee=emp,
                districts=districts,
                next_url=next_url,
                default_type=default_type,
                party_form_values=_workspace_party_form_prefill(),
                show_similar_ack=True,
                similar_party_name=sp.name,
                similar_party_id=sp.id,
                similar_score=conf.get("similarity") or 0.0,
            )
        if not row:
            row = WorkspaceParty(employee_id=emp.id)
            db.session.add(row)
        row.name = name
        row.party_type = (request.form.get("party_type") or "").strip() or None
        row.district_id = request.form.get("district_id", type=int) or None
        row.contact = (request.form.get("contact") or "").strip() or None
        row.phone = (request.form.get("phone") or "").strip() or None
        row.address = (request.form.get("address") or "").strip() or None
        row.remarks = (request.form.get("remarks") or "").strip() or None
        row.is_active = request.form.get("is_active") == "1"
        row.created_by_user_id = session.get("user_id")
        try:
            db.session.flush()
            ensure_workspace_counterparty_account(emp.id, party_id=row.id)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("Duplicate party: is naam ka record pehle se hai (is employee workspace ke liye).", "danger")
            r_after = None
            if pk:
                r_after = WorkspaceParty.query.filter_by(employee_id=emp.id, id=pk).first()
            return render_template(
                "workspace/party_form.html",
                row=r_after,
                employee=emp,
                districts=districts,
                next_url=next_url,
                default_type=default_type,
                party_form_values=_workspace_party_form_prefill(),
                show_similar_ack=False,
            )
        except Exception as e:
            db.session.rollback()
            print(f"workspace_party_form save error: {e}")
            flash("Unable to save workspace party right now. Please try again.", "danger")
            return render_template(
                "workspace/party_form.html",
                row=row,
                employee=emp,
                districts=districts,
                next_url=next_url,
                default_type=default_type,
                party_form_values=_workspace_party_form_prefill(),
                show_similar_ack=False,
            )
        flash("Workspace party saved.", "success")
        if next_url:
            target = _append_url_query_params(next_url, ws_party_created=row.id)
            return redirect(target or next_url)
        return redirect(url_for("workspace_parties_list"))
    return render_template(
        "workspace/party_form.html",
        row=row,
        employee=emp,
        districts=districts,
        next_url=next_url,
        default_type=default_type,
        party_form_values=None,
        show_similar_ack=False,
    )


def workspace_party_delete(pk):
    guard, emp = _workspace_guard("workspace_party_delete")
    if guard:
        return guard
    row = WorkspaceParty.query.filter_by(employee_id=emp.id, id=pk).first_or_404()
    db.session.delete(row)
    db.session.commit()
    flash("Workspace party deleted.", "success")
    return redirect(url_for("workspace_parties_list"))


def workspace_products_list():
    guard, emp = _workspace_guard("workspace_product_list")
    if guard:
        return guard
    search = (request.args.get("search") or "").strip()
    page = max(request.args.get("page", 1, type=int) or 1, 1)
    per_page = request.args.get("per_page", 20, type=int) or 20
    if per_page not in (10, 20, 50, 100):
        per_page = 20
    sort_by = (request.args.get("sort_by") or "name").strip()
    sort_order = (request.args.get("sort_order") or "asc").strip().lower()
    sort_order = "desc" if sort_order == "desc" else "asc"

    query = WorkspaceProduct.query.filter_by(employee_id=emp.id)
    if search:
        flt = _workspace_multi_word_filter(
            search,
            WorkspaceProduct.name,
            WorkspaceProduct.unit,
            WorkspaceProduct.used_in_forms,
            WorkspaceProduct.remarks,
        )
        if flt is not None:
            query = query.filter(flt)

    if sort_by == "used_in_forms":
        order_col = WorkspaceProduct.used_in_forms
    elif sort_by == "unit":
        order_col = WorkspaceProduct.unit
    elif sort_by == "status":
        order_col = WorkspaceProduct.is_active
    else:
        order_col = WorkspaceProduct.name
    if sort_order == "desc":
        order_col = order_col.desc()
    else:
        order_col = order_col.asc()

    pagination = query.order_by(order_col, WorkspaceProduct.id.asc()).paginate(page=page, per_page=per_page, error_out=False)
    return render_template(
        "workspace/products_list.html",
        rows=pagination.items,
        pagination=pagination,
        per_page=per_page,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
        employee=emp,
    )


def workspace_party_export():
    guard, emp = _workspace_guard("workspace_party_list")
    if guard:
        return guard
    search = (request.args.get("search") or "").strip()
    party_type = (request.args.get("type") or "").strip()
    query = WorkspaceParty.query.filter_by(employee_id=emp.id)
    if party_type:
        query = query.filter(WorkspaceParty.party_type == party_type)
    if search:
        flt = _workspace_multi_word_filter(
            search,
            WorkspaceParty.name,
            WorkspaceParty.party_type,
            WorkspaceParty.contact,
            WorkspaceParty.phone,
            WorkspaceParty.address,
            WorkspaceParty.remarks,
        )
        if flt is not None:
            query = query.filter(flt)
    rows = query.order_by(WorkspaceParty.name.asc(), WorkspaceParty.id.asc()).all()
    headers = ["S.No", "Name", "Type", "District", "Contact", "Phone", "Address", "Remarks", "Status"]
    data_rows = []
    for i, p in enumerate(rows, 1):
        data_rows.append([
            i,
            p.name or "",
            p.party_type or "",
            p.district.name if p.district else "",
            p.contact or "",
            p.phone or "",
            p.address or "",
            p.remarks or "",
            "Active" if p.is_active else "Inactive",
        ])
    return generate_excel_template(headers, data_rows, required_columns=[], filename=f"workspace_parties_emp_{emp.id}.xlsx")


def workspace_party_print():
    guard, emp = _workspace_guard("workspace_party_list")
    if guard:
        return guard
    search = (request.args.get("search") or "").strip()
    party_type = (request.args.get("type") or "").strip()
    query = WorkspaceParty.query.filter_by(employee_id=emp.id)
    if party_type:
        query = query.filter(WorkspaceParty.party_type == party_type)
    if search:
        flt = _workspace_multi_word_filter(
            search,
            WorkspaceParty.name,
            WorkspaceParty.party_type,
            WorkspaceParty.contact,
            WorkspaceParty.phone,
            WorkspaceParty.address,
            WorkspaceParty.remarks,
        )
        if flt is not None:
            query = query.filter(flt)
    rows = query.order_by(WorkspaceParty.name.asc(), WorkspaceParty.id.asc()).all()
    return render_template("workspace/parties_print.html", rows=rows, employee=emp, search=search, party_type=party_type)


def workspace_party_import():
    guard, emp = _workspace_guard("workspace_party_add")
    if guard:
        return guard
    import_errors = []
    if request.method == "POST":
        file_obj = request.files.get("file")
        if not file_obj or not (file_obj.filename or "").strip():
            flash("Please select an Excel or CSV file.", "warning")
            return redirect(url_for("workspace_party_import"))
        filename = file_obj.filename or ""
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in ("xlsx", "xls", "csv"):
            flash("Unsupported file type. Use .xlsx, .xls or .csv.", "danger")
            return redirect(url_for("workspace_party_import"))
        try:
            import pandas as pd

            if ext in ("xlsx", "xls"):
                df = pd.read_excel(file_obj)
            else:
                df = pd.read_csv(file_obj)

            required_cols = ["name", "party_type"]
            missing = [c for c in required_cols if c not in df.columns]
            if missing:
                flash(f"Missing required columns: {', '.join(missing)}", "danger")
                return redirect(url_for("workspace_party_import"))

            allowed_types = {"pump": "Pump", "workshop": "Workshop", "spare parts shop": "Spare parts shop"}
            district_map = {d.name.strip().lower(): d.id for d in District.query.order_by(District.name).all() if d.name}
            add_rows = []
            for idx, row in df.iterrows():
                row_no = idx + 2
                name = str(row.get("name", "")).strip() if not pd.isna(row.get("name")) else ""
                ptype_raw = str(row.get("party_type", "")).strip() if not pd.isna(row.get("party_type")) else ""
                ptype = allowed_types.get(ptype_raw.lower(), "")
                issues = []
                if not name:
                    issues.append('"name" is required.')
                if not ptype:
                    issues.append('party_type must be Pump, Workshop or Spare parts shop.')

                district_name = str(row.get("district", "")).strip() if "district" in df.columns and not pd.isna(row.get("district")) else ""
                district_id = None
                if district_name:
                    district_id = district_map.get(district_name.lower())
                    if not district_id:
                        issues.append(f'District "{district_name}" not found.')

                if issues:
                    import_errors.append({"row": row_no, "identifier": name or "-", "message": "; ".join(issues)})
                    continue

                contact = str(row.get("contact", "")).strip() if "contact" in df.columns and not pd.isna(row.get("contact")) else ""
                phone = str(row.get("phone", "")).strip() if "phone" in df.columns and not pd.isna(row.get("phone")) else ""
                address = str(row.get("address", "")).strip() if "address" in df.columns and not pd.isna(row.get("address")) else ""
                remarks = str(row.get("remarks", "")).strip() if "remarks" in df.columns and not pd.isna(row.get("remarks")) else ""

                add_rows.append(WorkspaceParty(
                    employee_id=emp.id,
                    name=name,
                    party_type=ptype,
                    district_id=district_id,
                    contact=contact or None,
                    phone=phone or None,
                    address=address or None,
                    remarks=remarks or None,
                    is_active=True,
                    created_by_user_id=session.get("user_id"),
                ))

            if import_errors:
                return render_template("workspace/party_import.html", employee=emp, import_errors=import_errors)

            for row in add_rows:
                db.session.add(row)
            db.session.commit()
            flash(f"{len(add_rows)} workspace parties imported successfully.", "success")
            return redirect(url_for("workspace_parties_list"))
        except Exception as exc:
            db.session.rollback()
            flash(f"Import failed: {exc}", "danger")
    return render_template("workspace/party_import.html", employee=emp, import_errors=import_errors)


def workspace_party_import_template():
    guard, _emp = _workspace_guard("workspace_party_add")
    if guard:
        return guard
    headers = ["name", "party_type", "district", "contact", "phone", "address", "remarks"]
    rows = [
        ["Shell Pump A", "Pump", "Lahore", "Manager", "03001234567", "Main Road", "Sample party"],
        ["ABC Workshop", "Workshop", "Lahore", "Owner", "03007654321", "Industrial Area", "Sample workshop"],
    ]
    return generate_excel_template(headers, rows, required_columns=["name", "party_type"], filename="workspace_party_import_template.xlsx")


def workspace_product_export():
    guard, emp = _workspace_guard("workspace_product_list")
    if guard:
        return guard
    search = (request.args.get("search") or "").strip()
    query = WorkspaceProduct.query.filter_by(employee_id=emp.id)
    if search:
        flt = _workspace_multi_word_filter(
            search,
            WorkspaceProduct.name,
            WorkspaceProduct.unit,
            WorkspaceProduct.used_in_forms,
            WorkspaceProduct.remarks,
        )
        if flt is not None:
            query = query.filter(flt)
    rows = query.order_by(WorkspaceProduct.name.asc(), WorkspaceProduct.id.asc()).all()
    headers = ["S.No", "Product Name", "Unit", "Used In Forms", "Default Price", "Remarks", "Status"]
    data_rows = []
    for i, p in enumerate(rows, 1):
        data_rows.append([
            i,
            p.name or "",
            p.unit or "",
            p.used_in_forms or "",
            float(p.default_price or 0),
            p.remarks or "",
            "Active" if p.is_active else "Inactive",
        ])
    return generate_excel_template(headers, data_rows, required_columns=[], filename=f"workspace_products_emp_{emp.id}.xlsx")


def workspace_product_print():
    guard, emp = _workspace_guard("workspace_product_list")
    if guard:
        return guard
    search = (request.args.get("search") or "").strip()
    query = WorkspaceProduct.query.filter_by(employee_id=emp.id)
    if search:
        flt = _workspace_multi_word_filter(
            search,
            WorkspaceProduct.name,
            WorkspaceProduct.unit,
            WorkspaceProduct.used_in_forms,
            WorkspaceProduct.remarks,
        )
        if flt is not None:
            query = query.filter(flt)
    rows = query.order_by(WorkspaceProduct.name.asc(), WorkspaceProduct.id.asc()).all()
    return render_template("workspace/products_print.html", rows=rows, employee=emp, search=search)


def workspace_product_import():
    guard, emp = _workspace_guard("workspace_product_add")
    if guard:
        return guard
    import_errors = []
    if request.method == "POST":
        file_obj = request.files.get("file")
        if not file_obj or not (file_obj.filename or "").strip():
            flash("Please select an Excel or CSV file.", "warning")
            return redirect(url_for("workspace_product_import"))
        filename = file_obj.filename or ""
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in ("xlsx", "xls", "csv"):
            flash("Unsupported file type. Use .xlsx, .xls or .csv.", "danger")
            return redirect(url_for("workspace_product_import"))
        try:
            import pandas as pd

            if ext in ("xlsx", "xls"):
                df = pd.read_excel(file_obj)
            else:
                df = pd.read_csv(file_obj)
            if "name" not in df.columns:
                flash("Missing required column: name", "danger")
                return redirect(url_for("workspace_product_import"))

            add_rows = []
            for idx, row in df.iterrows():
                row_no = idx + 2
                name = str(row.get("name", "")).strip() if not pd.isna(row.get("name")) else ""
                if not name:
                    import_errors.append({"row": row_no, "identifier": "-", "message": '"name" is required.'})
                    continue
                unit = str(row.get("unit", "")).strip() if "unit" in df.columns and not pd.isna(row.get("unit")) else ""
                used_in_forms = str(row.get("used_in_forms", "")).strip() if "used_in_forms" in df.columns and not pd.isna(row.get("used_in_forms")) else ""
                remarks = str(row.get("remarks", "")).strip() if "remarks" in df.columns and not pd.isna(row.get("remarks")) else ""
                default_price_raw = str(row.get("default_price", "")).strip() if "default_price" in df.columns and not pd.isna(row.get("default_price")) else "0"
                try:
                    default_price = Decimal(default_price_raw or "0")
                except Exception:
                    import_errors.append({"row": row_no, "identifier": name, "message": "default_price must be numeric."})
                    continue
                add_rows.append(WorkspaceProduct(
                    employee_id=emp.id,
                    name=name,
                    unit=unit or None,
                    used_in_forms=used_in_forms or None,
                    default_price=default_price,
                    remarks=remarks or None,
                    is_active=True,
                    created_by_user_id=session.get("user_id"),
                ))

            if import_errors:
                return render_template("workspace/product_import.html", employee=emp, import_errors=import_errors)

            for row in add_rows:
                db.session.add(row)
            db.session.commit()
            flash(f"{len(add_rows)} workspace products imported successfully.", "success")
            return redirect(url_for("workspace_products_list"))
        except Exception as exc:
            db.session.rollback()
            flash(f"Import failed: {exc}", "danger")
    return render_template("workspace/product_import.html", employee=emp, import_errors=import_errors)


def workspace_product_import_template():
    guard, _emp = _workspace_guard("workspace_product_add")
    if guard:
        return guard
    headers = ["name", "unit", "used_in_forms", "default_price", "remarks"]
    rows = [
        ["Diesel", "Liter", "Fueling", 278, "Fuel product"],
        ["Engine Oil", "Liter", "Oil,Maintenance", 1450, "Used in maintenance too"],
    ]
    return generate_excel_template(headers, rows, required_columns=["name"], filename="workspace_product_import_template.xlsx")


def workspace_product_names_api():
    """JSON: live filter of existing product names + exact/similar flags for the name field."""
    guard, emp = _workspace_guard("workspace_product_list")
    if guard:
        return jsonify({"suggestions": [], "exact_match_id": None, "similar": []}), 403
    qstr = (request.args.get("q") or "").strip()
    exclude_id = request.args.get("exclude_id", type=int) or 0
    base = WorkspaceProduct.query.filter_by(employee_id=emp.id)
    if exclude_id:
        base = base.filter(WorkspaceProduct.id != exclude_id)
    all_p = base.order_by(WorkspaceProduct.name.asc()).all()
    nq = _normalize_ws_product_name(qstr)
    suggestions = []
    for p in all_p:
        pn = _normalize_ws_product_name(p.name)
        if not nq:
            suggestions.append({"id": p.id, "name": p.name, "unit": p.unit or ""})
            if len(suggestions) >= 40:
                break
            continue
        if nq in pn or (len(nq) >= 2 and pn.startswith(nq)):
            suggestions.append({"id": p.id, "name": p.name, "unit": p.unit or ""})
        else:
            tokens = [t for t in nq.split() if len(t) >= 2]
            if tokens and all(t in pn for t in tokens):
                suggestions.append({"id": p.id, "name": p.name, "unit": p.unit or ""})
    suggestions = suggestions[:30]
    exact_id = None
    similar_list = []
    if nq and len(nq) >= 1:
        for p in all_p:
            pn = _normalize_ws_product_name(p.name)
            if pn == nq:
                exact_id = p.id
            r = _ws_product_name_similarity(nq, pn)
            if _WS_PROD_SIMILAR_MIN <= r < 1.0:
                similar_list.append({"id": p.id, "name": p.name, "score": round(r, 3)})
        similar_list.sort(key=lambda x: -x["score"])
        similar_list = similar_list[:8]
    return jsonify(
        {
            "suggestions": suggestions,
            "exact_match_id": exact_id,
            "similar": similar_list,
        }
    )


def workspace_party_names_api():
    """JSON: filter list by optional party_type; exact/similar use all types (name unique per employee)."""
    guard, emp = _workspace_guard("workspace_party_list")
    if guard:
        return jsonify({"suggestions": [], "exact_match_id": None, "similar": []}), 403
    qstr = (request.args.get("q") or "").strip()
    exclude_id = request.args.get("exclude_id", type=int) or 0
    party_type = (request.args.get("party_type") or "").strip()
    base_all = WorkspaceParty.query.filter_by(employee_id=emp.id)
    if exclude_id:
        base_all = base_all.filter(WorkspaceParty.id != exclude_id)
    all_for_dup = base_all.order_by(WorkspaceParty.name.asc()).all()
    base = base_all
    if party_type:
        base = base.filter(WorkspaceParty.party_type == party_type)
    all_p = base.order_by(WorkspaceParty.name.asc()).all()
    nq = _normalize_ws_product_name(qstr)
    suggestions = []
    if not nq:
        return jsonify({"suggestions": [], "exact_match_id": None, "similar": []})
    for p in all_p:
        pn = _normalize_ws_product_name(p.name)
        if nq in pn or (len(nq) >= 2 and pn.startswith(nq)):
            suggestions.append(
                {
                    "id": p.id,
                    "name": p.name,
                    "party_type": p.party_type or "",
                }
            )
        else:
            tokens = [t for t in nq.split() if len(t) >= 2]
            if tokens and all(t in pn for t in tokens):
                suggestions.append(
                    {
                        "id": p.id,
                        "name": p.name,
                        "party_type": p.party_type or "",
                    }
                )
    suggestions = suggestions[:30]
    exact_id = None
    similar_list = []
    if nq and len(nq) >= 1:
        for p in all_for_dup:
            pn = _normalize_ws_product_name(p.name)
            if pn == nq:
                exact_id = p.id
            r = _ws_product_name_similarity(nq, pn)
            if _WS_PROD_SIMILAR_MIN <= r < 1.0:
                similar_list.append({"id": p.id, "name": p.name, "score": round(r, 3)})
        similar_list.sort(key=lambda x: -x["score"])
        similar_list = similar_list[:8]
    return jsonify(
        {
            "suggestions": suggestions,
            "exact_match_id": exact_id,
            "similar": similar_list,
        }
    )


def _workspace_product_form_prefill():
    return {
        "name": (request.form.get("name") or "").strip(),
        "unit": (request.form.get("unit") or "").strip(),
        "default_price": (request.form.get("default_price") or "").strip(),
        "remarks": (request.form.get("remarks") or "").strip(),
        "is_active": request.form.get("is_active", "1"),
        "used_in_forms": request.form.getlist("used_in_forms"),
    }


def workspace_product_form(pk=None):
    guard, emp = _workspace_guard("workspace_product_edit" if pk else "workspace_product_add")
    if guard:
        return guard
    row = WorkspaceProduct.query.filter_by(employee_id=emp.id, id=pk).first() if pk else None
    if pk and not row:
        flash("Product not found for selected workspace employee.", "danger")
        return redirect(url_for("workspace_products_list"))

    next_url = _workspace_normalize_return_path(
        request.args.get("next") or request.form.get("next") or ""
    )
    default_used_in = (request.args.get("default_used_in") or request.form.get("default_used_in") or "").strip()

    default_units = ["Liter", "Piece", "Kg", "Gram", "Ml", "Pack", "Set", "Box", "Pair", "Unit"]
    db_units = [
        (u or "").strip()
        for (u,) in db.session.query(WorkspaceProduct.unit)
        .filter(
            WorkspaceProduct.employee_id == emp.id,
            WorkspaceProduct.unit.isnot(None),
            WorkspaceProduct.unit != "",
        )
        .distinct()
        .order_by(WorkspaceProduct.unit.asc())
        .all()
    ]
    unit_choices = []
    seen = set()
    for u in default_units + db_units:
        key = (u or "").strip()
        if not key:
            continue
        lk = key.lower()
        if lk in seen:
            continue
        seen.add(lk)
        unit_choices.append(key)

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("Product name is required.", "danger")
            return render_template(
                "workspace/product_form.html",
                row=row,
                employee=emp,
                unit_choices=unit_choices,
                next_url=next_url,
                default_used_in=default_used_in,
                product_form_values=_workspace_product_form_prefill(),
            )
        exid = row.id if row else None
        conf = _workspace_product_name_conflicts(emp.id, name, exclude_id=exid)
        if conf.get("exact"):
            ep = conf["exact"]
            flash(
                f'Yeh product pehle se maujood hai: “{ep.name}”. (Same naam — spacing/case alag ho sakta hai). Duplicate nahi bana sakte.',
                "danger",
            )
            return render_template(
                "workspace/product_form.html",
                row=row,
                employee=emp,
                unit_choices=unit_choices,
                next_url=next_url,
                default_used_in=default_used_in,
                product_form_values=_workspace_product_form_prefill(),
            )
        if conf.get("similar") and request.form.get("ack_similar") != "1":
            sp = conf["similar"]
            scr = int(round(float(conf.get("similarity") or 0) * 100))
            flash(
                f'Yeh naam maujood product “{sp.name}” se bahut milta-julta hai (~{scr}% match). Agar wohi naya product nahi, pehle wala edit karein; warna neeche tick karke save karein.',
                "warning",
            )
            return render_template(
                "workspace/product_form.html",
                row=row,
                employee=emp,
                unit_choices=unit_choices,
                next_url=next_url,
                default_used_in=default_used_in,
                product_form_values=_workspace_product_form_prefill(),
                show_similar_ack=True,
                similar_product_name=sp.name,
                similar_product_id=sp.id,
                similar_score=conf.get("similarity") or 0.0,
            )
        if not row:
            row = WorkspaceProduct(employee_id=emp.id)
            db.session.add(row)
        row.name = name
        row.unit = (request.form.get("unit") or "").strip() or None
        used_in = request.form.getlist("used_in_forms")
        row.used_in_forms = ",".join([x.strip() for x in used_in if x.strip()]) if used_in else None
        try:
            row.default_price = Decimal(str((request.form.get("default_price") or "0").strip() or "0"))
        except Exception:
            row.default_price = Decimal("0")
        row.remarks = (request.form.get("remarks") or "").strip() or None
        row.is_active = request.form.get("is_active") == "1"
        row.created_by_user_id = session.get("user_id")
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("Duplicate product: is naam ka record database mein pehle se hai (employee ke liye).", "danger")
            r_after = None
            if pk:
                r_after = WorkspaceProduct.query.filter_by(employee_id=emp.id, id=pk).first()
            return render_template(
                "workspace/product_form.html",
                row=r_after,
                employee=emp,
                unit_choices=unit_choices,
                next_url=next_url,
                default_used_in=default_used_in,
                product_form_values=_workspace_product_form_prefill(),
            )
        flash("Workspace product saved.", "success")
        if next_url:
            target = _append_url_query_params(next_url, ws_product_created=row.id)
            return redirect(target or next_url)
        return redirect(url_for("workspace_products_list"))
    return render_template(
        "workspace/product_form.html",
        row=row,
        employee=emp,
        unit_choices=unit_choices,
        next_url=next_url,
        default_used_in=default_used_in,
        product_form_values=None,
        show_similar_ack=False,
    )


def workspace_product_delete(pk):
    guard, emp = _workspace_guard("workspace_product_delete")
    if guard:
        return guard
    row = WorkspaceProduct.query.filter_by(employee_id=emp.id, id=pk).first_or_404()
    db.session.delete(row)
    db.session.commit()
    flash("Workspace product deleted.", "success")
    return redirect(url_for("workspace_products_list"))


def workspace_accounts_list():
    guard, emp = _workspace_guard("workspace_account_list")
    if guard:
        return guard
    ensure_workspace_base_accounts(emp.id)
    ensure_workspace_opening_expense_accounts(emp.id)
    ensure_workspace_fuel_oil_opening_accounts(emp.id)
    _ensure_workspace_driver_accounts(emp)
    parties = WorkspaceParty.query.filter_by(employee_id=emp.id).all()
    for p in parties:
        try:
            ensure_workspace_counterparty_account(emp.id, party_id=p.id)
        except Exception:
            pass
    db.session.commit()
    page = max(request.args.get("page", 1, type=int) or 1, 1)
    per_page = request.args.get("per_page", 50, type=int) or 50
    if per_page not in (25, 50, 100, 200):
        per_page = 50
    search = (request.args.get("search") or "").strip()

    query = WorkspaceAccount.query.filter_by(employee_id=emp.id)
    if search:
        words = [w.strip() for w in search.split() if w.strip()]
        for w in words:
            like = f"%{w}%"
            query = query.filter(
                or_(
                    WorkspaceAccount.code.ilike(like),
                    WorkspaceAccount.name.ilike(like),
                    WorkspaceAccount.account_type.ilike(like),
                    WorkspaceAccount.description.ilike(like),
                )
            )
    pagination = query.order_by(WorkspaceAccount.code.asc(), WorkspaceAccount.id.asc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    return render_template(
        "workspace/accounts_list.html",
        rows=pagination.items,
        pagination=pagination,
        per_page=per_page,
        search=search,
        employee=emp,
    )


def workspace_account_form(pk=None):
    guard, emp = _workspace_guard("workspace_account_edit" if pk else "workspace_account_add")
    if guard:
        return guard
    ensure_workspace_base_accounts(emp.id)
    _ensure_workspace_driver_accounts(emp)
    row = WorkspaceAccount.query.filter_by(employee_id=emp.id, id=pk).first() if pk else None
    if pk and not row:
        flash("Workspace account not found.", "danger")
        return redirect(url_for("workspace_accounts_list"))

    parents = WorkspaceAccount.query.filter_by(employee_id=emp.id).order_by(WorkspaceAccount.code).all()
    if request.method == "POST":
        code = (request.form.get("code") or "").strip()
        name = (request.form.get("name") or "").strip()
        account_type = (request.form.get("account_type") or "Asset").strip()
        if not code or not name:
            flash("Code and name are required.", "danger")
            return render_template("workspace/account_form.html", row=row, employee=emp, parents=parents)
        if not row:
            row = WorkspaceAccount(employee_id=emp.id, opening_balance=0, current_balance=0)
            db.session.add(row)
        row.code = code
        row.name = name
        row.account_type = account_type
        row.parent_id = request.form.get("parent_id", type=int) or None
        row.description = (request.form.get("description") or "").strip() or None
        row.is_active = request.form.get("is_active") == "1"
        db.session.commit()
        flash("Workspace account saved.", "success")
        return redirect(url_for("workspace_accounts_list"))
    return render_template("workspace/account_form.html", row=row, employee=emp, parents=parents)


def workspace_expenses_list():
    guard, _emp = _workspace_guard("workspace_dashboard")
    if guard:
        return guard
    return redirect(url_for("employee_expense_list"))


def workspace_expense_form(pk=None):
    guard, _emp = _workspace_guard("workspace_dashboard")
    if guard:
        return guard
    return redirect(url_for("employee_expense_form_edit", pk=pk) if pk else url_for("employee_expense_form"))


def workspace_expense_delete(pk):
    guard, _emp = _workspace_guard("workspace_dashboard")
    if guard:
        return guard
    return redirect(url_for("employee_expense_delete", pk=pk))


def _workspace_opening_expense_query(
    employee_id,
    from_date=None,
    to_date=None,
    district_id=0,
    project_id=0,
    search="",
    col_date="",
    col_district="",
    col_project="",
    col_fueling="",
    col_oil="",
    col_maintenance="",
    col_employee="",
    col_total="",
    col_remarks="",
):
    query = (
        WorkspaceOpeningExpense.query
        .filter(WorkspaceOpeningExpense.employee_id == employee_id)
        .outerjoin(District, WorkspaceOpeningExpense.district_id == District.id)
        .outerjoin(Project, WorkspaceOpeningExpense.project_id == Project.id)
    )
    if from_date:
        query = query.filter(WorkspaceOpeningExpense.opening_date >= from_date)
    if to_date:
        query = query.filter(WorkspaceOpeningExpense.opening_date <= to_date)
    if district_id:
        query = query.filter(WorkspaceOpeningExpense.district_id == district_id)
    if project_id:
        query = query.filter(WorkspaceOpeningExpense.project_id == project_id)
    if search:
        flt = _workspace_multi_word_filter(search, WorkspaceOpeningExpense.remarks, District.name, Project.name)
        if flt is not None:
            query = query.filter(flt)
    if col_date:
        parsed = parse_date(col_date)
        if parsed:
            query = query.filter(WorkspaceOpeningExpense.opening_date == parsed)
    if col_district:
        query = query.filter(District.name.ilike(f"%{col_district}%"))
    if col_project:
        query = query.filter(Project.name.ilike(f"%{col_project}%"))
    if col_fueling:
        query = query.filter(cast(WorkspaceOpeningExpense.fueling_expense, String).ilike(f"%{col_fueling}%"))
    if col_oil:
        query = query.filter(cast(WorkspaceOpeningExpense.oil_change_expense, String).ilike(f"%{col_oil}%"))
    if col_maintenance:
        query = query.filter(cast(WorkspaceOpeningExpense.maintenance_expense, String).ilike(f"%{col_maintenance}%"))
    if col_employee:
        query = query.filter(cast(WorkspaceOpeningExpense.employee_expense, String).ilike(f"%{col_employee}%"))
    if col_total:
        query = query.filter(cast(WorkspaceOpeningExpense.total_expense, String).ilike(f"%{col_total}%"))
    if col_remarks:
        query = query.filter(WorkspaceOpeningExpense.remarks.ilike(f"%{col_remarks}%"))
    return query


def _workspace_opening_expense_rows(
    employee_id,
    from_date=None,
    to_date=None,
    district_id=0,
    project_id=0,
    search="",
    col_date="",
    col_district="",
    col_project="",
    col_fueling="",
    col_oil="",
    col_maintenance="",
    col_employee="",
    col_total="",
    col_remarks="",
    sort_by="date",
    sort_order="desc",
):
    sort_map = {
        "date": WorkspaceOpeningExpense.opening_date,
        "district": District.name,
        "project": Project.name,
        "fueling": WorkspaceOpeningExpense.fueling_expense,
        "oil": WorkspaceOpeningExpense.oil_change_expense,
        "maintenance": WorkspaceOpeningExpense.maintenance_expense,
        "employee": WorkspaceOpeningExpense.employee_expense,
        "total": WorkspaceOpeningExpense.total_expense,
        "remarks": WorkspaceOpeningExpense.remarks,
    }
    sort_col = sort_map.get(sort_by, WorkspaceOpeningExpense.opening_date)
    desc_order = (sort_order or "").lower() != "asc"
    ordered = sort_col.desc() if desc_order else sort_col.asc()
    return _workspace_opening_expense_query(
        employee_id=employee_id,
        from_date=from_date,
        to_date=to_date,
        district_id=district_id,
        project_id=project_id,
        search=search,
        col_date=col_date,
        col_district=col_district,
        col_project=col_project,
        col_fueling=col_fueling,
        col_oil=col_oil,
        col_maintenance=col_maintenance,
        col_employee=col_employee,
        col_total=col_total,
        col_remarks=col_remarks,
    ).order_by(ordered, WorkspaceOpeningExpense.id.desc()).all()


def workspace_opening_expenses_list():
    guard, emp = _workspace_guard("workspace_dashboard")
    if guard:
        return guard

    from_date = parse_date(request.args.get("from_date"))
    to_date = parse_date(request.args.get("to_date"))
    district_id = request.args.get("district_id", type=int) or 0
    project_id = request.args.get("project_id", type=int) or 0
    search = (request.args.get("search") or "").strip()
    col_date = (request.args.get("col_date") or "").strip()
    col_district = (request.args.get("col_district") or "").strip()
    col_project = (request.args.get("col_project") or "").strip()
    col_fueling = (request.args.get("col_fueling") or "").strip()
    col_oil = (request.args.get("col_oil") or "").strip()
    col_maintenance = (request.args.get("col_maintenance") or "").strip()
    col_employee = (request.args.get("col_employee") or "").strip()
    col_total = (request.args.get("col_total") or "").strip()
    col_remarks = (request.args.get("col_remarks") or "").strip()
    sort_by = (request.args.get("sort_by") or "date").strip().lower()
    sort_order = (request.args.get("sort_order") or "desc").strip().lower()
    page = max(request.args.get("page", 1, type=int) or 1, 1)
    per_page = request.args.get("per_page", 20, type=int) or 20
    if per_page not in (10, 20, 50, 100):
        per_page = 20

    query = _workspace_opening_expense_query(
        employee_id=emp.id,
        from_date=from_date,
        to_date=to_date,
        district_id=district_id,
        project_id=project_id,
        search=search,
        col_date=col_date,
        col_district=col_district,
        col_project=col_project,
        col_fueling=col_fueling,
        col_oil=col_oil,
        col_maintenance=col_maintenance,
        col_employee=col_employee,
        col_total=col_total,
        col_remarks=col_remarks,
    )
    total_amount = query.with_entities(
        db.func.coalesce(db.func.sum(WorkspaceOpeningExpense.total_expense), 0)
    ).scalar() or 0
    totals_row = query.with_entities(
        db.func.coalesce(db.func.sum(WorkspaceOpeningExpense.fueling_expense), 0),
        db.func.coalesce(db.func.sum(WorkspaceOpeningExpense.oil_change_expense), 0),
        db.func.coalesce(db.func.sum(WorkspaceOpeningExpense.maintenance_expense), 0),
        db.func.coalesce(db.func.sum(WorkspaceOpeningExpense.employee_expense), 0),
        db.func.coalesce(db.func.sum(WorkspaceOpeningExpense.total_expense), 0),
    ).first()
    sort_map = {
        "date": WorkspaceOpeningExpense.opening_date,
        "district": District.name,
        "project": Project.name,
        "fueling": WorkspaceOpeningExpense.fueling_expense,
        "oil": WorkspaceOpeningExpense.oil_change_expense,
        "maintenance": WorkspaceOpeningExpense.maintenance_expense,
        "employee": WorkspaceOpeningExpense.employee_expense,
        "total": WorkspaceOpeningExpense.total_expense,
        "remarks": WorkspaceOpeningExpense.remarks,
    }
    sort_col = sort_map.get(sort_by, WorkspaceOpeningExpense.opening_date)
    desc_order = sort_order != "asc"
    ordered = sort_col.desc() if desc_order else sort_col.asc()
    pagination = query.order_by(ordered, WorkspaceOpeningExpense.id.desc()).paginate(page=page, per_page=per_page, error_out=False)
    page_fueling_subtotal = sum(Decimal(str(r.fueling_expense or 0)) for r in pagination.items)
    page_oil_subtotal = sum(Decimal(str(r.oil_change_expense or 0)) for r in pagination.items)
    page_maintenance_subtotal = sum(Decimal(str(r.maintenance_expense or 0)) for r in pagination.items)
    page_employee_subtotal = sum(Decimal(str(r.employee_expense or 0)) for r in pagination.items)
    page_total_subtotal = sum(Decimal(str(r.total_expense or 0)) for r in pagination.items)
    overall_fueling_total = Decimal(str((totals_row[0] if totals_row else 0) or 0))
    overall_oil_total = Decimal(str((totals_row[1] if totals_row else 0) or 0))
    overall_maintenance_total = Decimal(str((totals_row[2] if totals_row else 0) or 0))
    overall_employee_total = Decimal(str((totals_row[3] if totals_row else 0) or 0))
    overall_total = Decimal(str((totals_row[4] if totals_row else 0) or 0))

    districts = District.query.order_by(District.name).all()
    projects = Project.query.order_by(Project.name).all()
    return render_template(
        "workspace/opening_expense_list.html",
        employee=emp,
        rows=pagination.items,
        pagination=pagination,
        per_page=per_page,
        from_date=from_date,
        to_date=to_date,
        district_id=district_id,
        project_id=project_id,
        search=search,
        total_amount=total_amount,
        page_fueling_subtotal=page_fueling_subtotal,
        page_oil_subtotal=page_oil_subtotal,
        page_maintenance_subtotal=page_maintenance_subtotal,
        page_employee_subtotal=page_employee_subtotal,
        page_total_subtotal=page_total_subtotal,
        overall_fueling_total=overall_fueling_total,
        overall_oil_total=overall_oil_total,
        overall_maintenance_total=overall_maintenance_total,
        overall_employee_total=overall_employee_total,
        overall_total=overall_total,
        col_date=col_date,
        col_district=col_district,
        col_project=col_project,
        col_fueling=col_fueling,
        col_oil=col_oil,
        col_maintenance=col_maintenance,
        col_employee=col_employee,
        col_total=col_total,
        col_remarks=col_remarks,
        sort_by=sort_by,
        sort_order=sort_order,
        districts=districts,
        projects=projects,
    )


def workspace_opening_expense_export():
    guard, emp = _workspace_guard("workspace_dashboard")
    if guard:
        return guard
    from_date = parse_date(request.args.get("from_date"))
    to_date = parse_date(request.args.get("to_date"))
    district_id = request.args.get("district_id", type=int) or 0
    project_id = request.args.get("project_id", type=int) or 0
    search = (request.args.get("search") or "").strip()
    col_date = (request.args.get("col_date") or "").strip()
    col_district = (request.args.get("col_district") or "").strip()
    col_project = (request.args.get("col_project") or "").strip()
    col_fueling = (request.args.get("col_fueling") or "").strip()
    col_oil = (request.args.get("col_oil") or "").strip()
    col_maintenance = (request.args.get("col_maintenance") or "").strip()
    col_employee = (request.args.get("col_employee") or "").strip()
    col_total = (request.args.get("col_total") or "").strip()
    col_remarks = (request.args.get("col_remarks") or "").strip()
    sort_by = (request.args.get("sort_by") or "date").strip().lower()
    sort_order = (request.args.get("sort_order") or "desc").strip().lower()
    rows = _workspace_opening_expense_rows(
        employee_id=emp.id,
        from_date=from_date,
        to_date=to_date,
        district_id=district_id,
        project_id=project_id,
        search=search,
        col_date=col_date,
        col_district=col_district,
        col_project=col_project,
        col_fueling=col_fueling,
        col_oil=col_oil,
        col_maintenance=col_maintenance,
        col_employee=col_employee,
        col_total=col_total,
        col_remarks=col_remarks,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    headers = [
        "S.No", "Date", "District", "Project", "Fueling", "Oil Change",
        "Maintenance", "Employee", "Total", "Remarks",
    ]
    data_rows = []
    for i, r in enumerate(rows, 1):
        data_rows.append([
            i,
            r.opening_date.strftime("%d-%m-%Y") if r.opening_date else "",
            r.district.name if r.district else "",
            r.project.name if r.project else "",
            float(r.fueling_expense or 0),
            float(r.oil_change_expense or 0),
            float(r.maintenance_expense or 0),
            float(r.employee_expense or 0),
            float(r.total_expense or 0),
            r.remarks or "",
        ])
    return generate_excel_template(headers, data_rows, required_columns=[], filename="workspace_opening_expenses.xlsx")


def workspace_opening_expense_print():
    guard, emp = _workspace_guard("workspace_dashboard")
    if guard:
        return guard
    from_date = parse_date(request.args.get("from_date"))
    to_date = parse_date(request.args.get("to_date"))
    district_id = request.args.get("district_id", type=int) or 0
    project_id = request.args.get("project_id", type=int) or 0
    search = (request.args.get("search") or "").strip()
    col_date = (request.args.get("col_date") or "").strip()
    col_district = (request.args.get("col_district") or "").strip()
    col_project = (request.args.get("col_project") or "").strip()
    col_fueling = (request.args.get("col_fueling") or "").strip()
    col_oil = (request.args.get("col_oil") or "").strip()
    col_maintenance = (request.args.get("col_maintenance") or "").strip()
    col_employee = (request.args.get("col_employee") or "").strip()
    col_total = (request.args.get("col_total") or "").strip()
    col_remarks = (request.args.get("col_remarks") or "").strip()
    sort_by = (request.args.get("sort_by") or "date").strip().lower()
    sort_order = (request.args.get("sort_order") or "desc").strip().lower()
    rows = _workspace_opening_expense_rows(
        employee_id=emp.id,
        from_date=from_date,
        to_date=to_date,
        district_id=district_id,
        project_id=project_id,
        search=search,
        col_date=col_date,
        col_district=col_district,
        col_project=col_project,
        col_fueling=col_fueling,
        col_oil=col_oil,
        col_maintenance=col_maintenance,
        col_employee=col_employee,
        col_total=col_total,
        col_remarks=col_remarks,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    total_amount = sum(Decimal(str(r.total_expense or 0)) for r in rows)
    return render_template(
        "workspace/opening_expense_print.html",
        rows=rows,
        from_date=from_date,
        to_date=to_date,
        search=search,
        total_amount=total_amount,
    )


def workspace_opening_expense_import():
    guard, emp = _workspace_guard("workspace_dashboard")
    if guard:
        return guard

    import_errors = []
    if request.method == "POST":
        file_obj = request.files.get("file")
        if not file_obj or not (file_obj.filename or "").strip():
            flash("Please select an Excel or CSV file.", "warning")
            return redirect(url_for("workspace_opening_expense_import"))

        filename = file_obj.filename or ""
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in ("xlsx", "xls", "csv"):
            flash("Unsupported file type. Use .xlsx, .xls or .csv.", "danger")
            return redirect(url_for("workspace_opening_expense_import"))

        try:
            import pandas as pd

            if ext in ("xlsx", "xls"):
                df = pd.read_excel(file_obj)
            else:
                df = pd.read_csv(file_obj)

            required_cols = ["opening_date", "district", "project"]
            missing = [c for c in required_cols if c not in df.columns]
            if missing:
                flash(f"Missing required columns: {', '.join(missing)}", "danger")
                return redirect(url_for("workspace_opening_expense_import"))

            district_map = {d.name.strip().lower(): d.id for d in District.query.order_by(District.name).all() if d.name}
            project_map = {p.name.strip().lower(): p.id for p in Project.query.order_by(Project.name).all() if p.name}
            ensure_workspace_opening_expense_accounts(emp.id)
            add_rows = []

            def _dec(raw):
                if raw is None:
                    return Decimal("0")
                s = str(raw).strip()
                if not s or s.lower() == "nan":
                    return Decimal("0")
                return Decimal(s)

            def _date_from_any(v):
                if v is None:
                    return None
                if hasattr(v, "date"):
                    try:
                        return v.date()
                    except Exception:
                        pass
                s = str(v).strip()
                if not s or s.lower() == "nan":
                    return None
                d1 = parse_date(s)
                if d1:
                    return d1
                try:
                    return pd.to_datetime(s, errors="coerce").date()
                except Exception:
                    return None

            for idx, row in df.iterrows():
                row_no = idx + 2
                issues = []

                opening_date = _date_from_any(row.get("opening_date"))
                if not opening_date:
                    issues.append('"opening_date" is required (dd-mm-yyyy or yyyy-mm-dd).')

                district_name = str(row.get("district", "")).strip() if not pd.isna(row.get("district")) else ""
                district_id = district_map.get(district_name.lower()) if district_name else None
                if not district_id:
                    issues.append(f'District "{district_name or "-"}" not found.')

                project_name = str(row.get("project", "")).strip() if not pd.isna(row.get("project")) else ""
                project_id = project_map.get(project_name.lower()) if project_name else None
                if not project_id:
                    issues.append(f'Project "{project_name or "-"}" not found.')

                try:
                    fueling = _dec(row.get("fueling_expense", 0))
                    oil = _dec(row.get("oil_change_expense", 0))
                    maintenance = _dec(row.get("maintenance_expense", 0))
                    emp_exp = _dec(row.get("employee_expense", 0))
                except Exception:
                    issues.append("Expense fields must be numeric.")
                    fueling = oil = maintenance = emp_exp = Decimal("0")

                if opening_date and _workspace_has_closed_month_for_date(
                    emp.id,
                    opening_date,
                    district_id=district_id,
                    project_id=project_id,
                ):
                    issues.append("Date belongs to a closed month. Reopen month-close first.")

                if issues:
                    import_errors.append({
                        "row": row_no,
                        "identifier": f"{district_name or '-'} / {project_name or '-'}",
                        "message": "; ".join(issues),
                    })
                    continue

                total = fueling + oil + maintenance + emp_exp
                remarks = str(row.get("remarks", "")).strip() if "remarks" in df.columns and not pd.isna(row.get("remarks")) else ""
                add_rows.append({
                    "opening_date": opening_date,
                    "district_id": district_id,
                    "project_id": project_id,
                    "fueling_expense": fueling,
                    "oil_change_expense": oil,
                    "maintenance_expense": maintenance,
                    "employee_expense": emp_exp,
                    "total_expense": total,
                    "remarks": remarks or None,
                })

            if import_errors:
                return render_template("workspace/opening_expense_import.html", employee=emp, import_errors=import_errors)

            for payload in add_rows:
                rec = WorkspaceOpeningExpense(
                    employee_id=emp.id,
                    opening_date=payload["opening_date"],
                    district_id=payload["district_id"],
                    project_id=payload["project_id"],
                    fueling_expense=payload["fueling_expense"],
                    oil_change_expense=payload["oil_change_expense"],
                    maintenance_expense=payload["maintenance_expense"],
                    employee_expense=payload["employee_expense"],
                    total_expense=payload["total_expense"],
                    remarks=payload["remarks"],
                    created_by_user_id=session.get("user_id"),
                )
                db.session.add(rec)
                db.session.flush()
                if rec.total_expense and Decimal(str(rec.total_expense)) > Decimal("0"):
                    je = workspace_post_opening_expense(rec)
                    rec.journal_entry_id = je.id

            db.session.commit()
            flash(f"{len(add_rows)} opening expense rows imported successfully.", "success")
            return redirect(url_for("workspace_opening_expenses_list"))
        except Exception as exc:
            db.session.rollback()
            flash(f"Import failed: {exc}", "danger")

    return render_template("workspace/opening_expense_import.html", employee=emp, import_errors=import_errors)


def workspace_opening_expense_import_template():
    guard, _emp = _workspace_guard("workspace_dashboard")
    if guard:
        return guard

    headers = [
        "opening_date",
        "district",
        "project",
        "fueling_expense",
        "oil_change_expense",
        "maintenance_expense",
        "employee_expense",
        "remarks",
    ]
    rows = [
        ["01-03-2026", "Muzaffargarh", "RAS-1034", 35000, 6000, 9000, 5000, "Date Range: 1-15(Mar-26)"],
        ["16-03-2026", "Muzaffargarh", "RAS-1034", 28000, 5000, 7000, 4500, "Date Range: 16-31(Mar-26)"],
    ]
    return generate_excel_template(
        headers,
        rows,
        required_columns=["opening_date", "district", "project"],
        filename="workspace_opening_expense_import_template.xlsx",
    )


def workspace_opening_expense_form(pk=None):
    guard, emp = _workspace_guard("workspace_dashboard")
    if guard:
        return guard

    row = WorkspaceOpeningExpense.query.filter_by(employee_id=emp.id, id=pk).first() if pk else None
    if pk and not row:
        flash("Opening expense entry not found.", "danger")
        return redirect(url_for("workspace_opening_expenses_list"))

    districts = District.query.order_by(District.name).all()
    projects = Project.query.order_by(Project.name).all()
    ensure_workspace_opening_expense_accounts(emp.id)

    if request.method == "POST":
        opening_date = parse_date(request.form.get("opening_date"))
        if not opening_date:
            flash("Opening date is required.", "danger")
            return render_template("workspace/opening_expense_form.html", row=row, employee=emp, districts=districts, projects=projects)
        district_id = request.form.get("district_id", type=int) or None
        project_id = request.form.get("project_id", type=int) or None
        if _workspace_has_closed_month_for_date(
            emp.id,
            opening_date,
            district_id=district_id,
            project_id=project_id,
        ):
            flash("This date belongs to a closed month. Reopen month-close batch first to make changes.", "danger")
            return render_template("workspace/opening_expense_form.html", row=row, employee=emp, districts=districts, projects=projects)

        def _to_dec(name):
            raw = (request.form.get(name) or "").strip()
            if not raw:
                return Decimal("0")
            return Decimal(str(raw))

        try:
            fueling = _to_dec("fueling_expense")
            oil = _to_dec("oil_change_expense")
            maintenance = _to_dec("maintenance_expense")
            emp_exp = _to_dec("employee_expense")
        except Exception:
            flash("Expense fields must be numeric values.", "danger")
            return render_template("workspace/opening_expense_form.html", row=row, employee=emp, districts=districts, projects=projects)

        if not row:
            row = WorkspaceOpeningExpense(employee_id=emp.id)
            db.session.add(row)
        elif row.journal_entry_id:
            workspace_reverse_journal_entry(row.journal_entry_id)
            row.journal_entry_id = None

        row.opening_date = opening_date
        row.district_id = district_id
        row.project_id = project_id
        row.fueling_expense = fueling
        row.oil_change_expense = oil
        row.maintenance_expense = maintenance
        row.employee_expense = emp_exp
        row.total_expense = fueling + oil + maintenance + emp_exp
        row.remarks = (request.form.get("remarks") or "").strip() or None
        row.created_by_user_id = session.get("user_id")
        db.session.flush()
        if row.total_expense and Decimal(str(row.total_expense)) > Decimal("0"):
            je = workspace_post_opening_expense(row)
            row.journal_entry_id = je.id
        db.session.commit()
        flash("Opening expense saved.", "success")
        return redirect(url_for("workspace_opening_expenses_list"))

    return render_template("workspace/opening_expense_form.html", row=row, employee=emp, districts=districts, projects=projects)


def workspace_opening_expense_delete(pk):
    guard, emp = _workspace_guard("workspace_dashboard")
    if guard:
        return guard
    row = WorkspaceOpeningExpense.query.filter_by(employee_id=emp.id, id=pk).first_or_404()
    if _workspace_has_closed_month_for_date(
        emp.id,
        row.opening_date,
        district_id=row.district_id,
        project_id=row.project_id,
    ):
        flash("Cannot delete opening expense from a closed month. Reopen month-close batch first.", "danger")
        return redirect(url_for("workspace_opening_expenses_list"))
    if row.journal_entry_id:
        workspace_reverse_journal_entry(row.journal_entry_id)
    db.session.delete(row)
    db.session.commit()
    flash("Opening expense deleted.", "success")
    return redirect(url_for("workspace_opening_expenses_list"))


def workspace_fuel_oil_openings_list():
    guard, emp = _workspace_guard("workspace_dashboard")
    if guard:
        return guard

    from_date = parse_date(request.args.get("from_date"))
    to_date = parse_date(request.args.get("to_date"))
    district_id = request.args.get("district_id", type=int) or 0
    project_id = request.args.get("project_id", type=int) or 0
    search = (request.args.get("search") or "").strip()
    page = max(request.args.get("page", 1, type=int) or 1, 1)
    per_page = request.args.get("per_page", 20, type=int) or 20
    if per_page not in (10, 20, 50, 100):
        per_page = 20

    query = _workspace_fuel_oil_opening_query(
        employee_id=emp.id,
        from_date=from_date,
        to_date=to_date,
        district_id=district_id,
        project_id=project_id,
        search=search,
    )

    total_amount = query.with_entities(
        db.func.coalesce(db.func.sum(WorkspaceFuelOilOpeningExpense.total_amount), 0)
    ).scalar() or 0
    totals_row = query.with_entities(
        db.func.coalesce(db.func.sum(WorkspaceFuelOilOpeningExpense.pump_card_fueling), 0),
        db.func.coalesce(db.func.sum(WorkspaceFuelOilOpeningExpense.credit_fueling), 0),
        db.func.coalesce(db.func.sum(WorkspaceFuelOilOpeningExpense.total_fueling), 0),
        db.func.coalesce(db.func.sum(WorkspaceFuelOilOpeningExpense.card_oil_change), 0),
        db.func.coalesce(db.func.sum(WorkspaceFuelOilOpeningExpense.credit_oil_change), 0),
        db.func.coalesce(db.func.sum(WorkspaceFuelOilOpeningExpense.total_oil_change), 0),
        db.func.coalesce(db.func.sum(WorkspaceFuelOilOpeningExpense.total_amount), 0),
    ).first()

    pagination = query.order_by(
        WorkspaceFuelOilOpeningExpense.opening_date.desc(),
        WorkspaceFuelOilOpeningExpense.id.desc(),
    ).paginate(page=page, per_page=per_page, error_out=False)
    page_pump_card_fueling_subtotal = sum(Decimal(str(r.pump_card_fueling or 0)) for r in pagination.items)
    page_credit_fueling_subtotal = sum(Decimal(str(r.credit_fueling or 0)) for r in pagination.items)
    page_total_fueling_subtotal = sum(Decimal(str(r.total_fueling or 0)) for r in pagination.items)
    page_card_oil_change_subtotal = sum(Decimal(str(r.card_oil_change or 0)) for r in pagination.items)
    page_credit_oil_change_subtotal = sum(Decimal(str(r.credit_oil_change or 0)) for r in pagination.items)
    page_total_oil_change_subtotal = sum(Decimal(str(r.total_oil_change or 0)) for r in pagination.items)
    page_grand_total_subtotal = sum(Decimal(str(r.total_amount or 0)) for r in pagination.items)
    overall_pump_card_fueling_total = Decimal(str((totals_row[0] if totals_row else 0) or 0))
    overall_credit_fueling_total = Decimal(str((totals_row[1] if totals_row else 0) or 0))
    overall_total_fueling_total = Decimal(str((totals_row[2] if totals_row else 0) or 0))
    overall_card_oil_change_total = Decimal(str((totals_row[3] if totals_row else 0) or 0))
    overall_credit_oil_change_total = Decimal(str((totals_row[4] if totals_row else 0) or 0))
    overall_total_oil_change_total = Decimal(str((totals_row[5] if totals_row else 0) or 0))
    overall_grand_total = Decimal(str((totals_row[6] if totals_row else 0) or 0))

    districts = District.query.order_by(District.name).all()
    projects = Project.query.order_by(Project.name).all()
    return render_template(
        "workspace/fuel_oil_opening_list.html",
        employee=emp,
        rows=pagination.items,
        pagination=pagination,
        per_page=per_page,
        from_date=from_date,
        to_date=to_date,
        district_id=district_id,
        project_id=project_id,
        search=search,
        total_amount=total_amount,
        page_pump_card_fueling_subtotal=page_pump_card_fueling_subtotal,
        page_credit_fueling_subtotal=page_credit_fueling_subtotal,
        page_total_fueling_subtotal=page_total_fueling_subtotal,
        page_card_oil_change_subtotal=page_card_oil_change_subtotal,
        page_credit_oil_change_subtotal=page_credit_oil_change_subtotal,
        page_total_oil_change_subtotal=page_total_oil_change_subtotal,
        page_grand_total_subtotal=page_grand_total_subtotal,
        overall_pump_card_fueling_total=overall_pump_card_fueling_total,
        overall_credit_fueling_total=overall_credit_fueling_total,
        overall_total_fueling_total=overall_total_fueling_total,
        overall_card_oil_change_total=overall_card_oil_change_total,
        overall_credit_oil_change_total=overall_credit_oil_change_total,
        overall_total_oil_change_total=overall_total_oil_change_total,
        overall_grand_total=overall_grand_total,
        districts=districts,
        projects=projects,
    )


def _workspace_fuel_oil_opening_query(employee_id, from_date=None, to_date=None, district_id=0, project_id=0, search=""):
    query = WorkspaceFuelOilOpeningExpense.query.filter_by(employee_id=employee_id)
    if from_date:
        query = query.filter(WorkspaceFuelOilOpeningExpense.opening_date >= from_date)
    if to_date:
        query = query.filter(WorkspaceFuelOilOpeningExpense.opening_date <= to_date)
    if district_id:
        query = query.filter(WorkspaceFuelOilOpeningExpense.district_id == district_id)
    if project_id:
        query = query.filter(WorkspaceFuelOilOpeningExpense.project_id == project_id)
    if search:
        query = query.outerjoin(District, WorkspaceFuelOilOpeningExpense.district_id == District.id)
        query = query.outerjoin(Project, WorkspaceFuelOilOpeningExpense.project_id == Project.id)
        flt = _workspace_multi_word_filter(
            search,
            WorkspaceFuelOilOpeningExpense.remarks,
            District.name,
            Project.name,
            cast(WorkspaceFuelOilOpeningExpense.opening_date, String),
            cast(WorkspaceFuelOilOpeningExpense.pump_card_fueling, String),
            cast(WorkspaceFuelOilOpeningExpense.credit_fueling, String),
            cast(WorkspaceFuelOilOpeningExpense.total_fueling, String),
            cast(WorkspaceFuelOilOpeningExpense.card_oil_change, String),
            cast(WorkspaceFuelOilOpeningExpense.credit_oil_change, String),
            cast(WorkspaceFuelOilOpeningExpense.total_oil_change, String),
            cast(WorkspaceFuelOilOpeningExpense.total_amount, String),
        )
        if flt is not None:
            query = query.filter(flt)
    return query


def _workspace_fuel_oil_opening_rows(employee_id, from_date=None, to_date=None, district_id=0, project_id=0, search=""):
    return _workspace_fuel_oil_opening_query(
        employee_id=employee_id,
        from_date=from_date,
        to_date=to_date,
        district_id=district_id,
        project_id=project_id,
        search=search,
    ).order_by(
        WorkspaceFuelOilOpeningExpense.opening_date.desc(),
        WorkspaceFuelOilOpeningExpense.id.desc(),
    ).all()


def workspace_fuel_oil_opening_export():
    guard, emp = _workspace_guard("workspace_dashboard")
    if guard:
        return guard

    from_date = parse_date(request.args.get("from_date"))
    to_date = parse_date(request.args.get("to_date"))
    district_id = request.args.get("district_id", type=int) or 0
    project_id = request.args.get("project_id", type=int) or 0
    search = (request.args.get("search") or "").strip()

    rows = _workspace_fuel_oil_opening_rows(
        employee_id=emp.id,
        from_date=from_date,
        to_date=to_date,
        district_id=district_id,
        project_id=project_id,
        search=search,
    )

    headers = [
        "S.No",
        "Date",
        "District",
        "Project",
        "Pump Card Fueling",
        "Credit Fueling",
        "Fueling Total",
        "Card Oil Change",
        "Credit Oil Change",
        "Oil Total",
        "Grand Total",
        "Remarks",
    ]
    data_rows = []
    for i, r in enumerate(rows, 1):
        data_rows.append([
            i,
            r.opening_date.strftime("%d-%m-%Y") if r.opening_date else "",
            r.district.name if r.district else "",
            r.project.name if r.project else "",
            float(r.pump_card_fueling or 0),
            float(r.credit_fueling or 0),
            float(r.total_fueling or 0),
            float(r.card_oil_change or 0),
            float(r.credit_oil_change or 0),
            float(r.total_oil_change or 0),
            float(r.total_amount or 0),
            r.remarks or "",
        ])
    return generate_excel_template(headers, data_rows, required_columns=[], filename="workspace_fuel_oil_opening.xlsx")


def workspace_fuel_oil_opening_print():
    guard, emp = _workspace_guard("workspace_dashboard")
    if guard:
        return guard

    from_date = parse_date(request.args.get("from_date"))
    to_date = parse_date(request.args.get("to_date"))
    district_id = request.args.get("district_id", type=int) or 0
    project_id = request.args.get("project_id", type=int) or 0
    search = (request.args.get("search") or "").strip()

    rows = _workspace_fuel_oil_opening_rows(
        employee_id=emp.id,
        from_date=from_date,
        to_date=to_date,
        district_id=district_id,
        project_id=project_id,
        search=search,
    )
    total_amount = sum(Decimal(str(r.total_amount or 0)) for r in rows)
    return render_template(
        "workspace/fuel_oil_opening_print.html",
        rows=rows,
        from_date=from_date,
        to_date=to_date,
        district_id=district_id,
        project_id=project_id,
        search=search,
        total_amount=total_amount,
    )


def workspace_fuel_oil_opening_form(pk=None):
    guard, emp = _workspace_guard("workspace_dashboard")
    if guard:
        return guard

    row = WorkspaceFuelOilOpeningExpense.query.filter_by(employee_id=emp.id, id=pk).first() if pk else None
    if pk and not row:
        flash("Fuel/Oil opening entry not found.", "danger")
        return redirect(url_for("workspace_fuel_oil_openings_list"))

    districts = District.query.order_by(District.name).all()
    projects = Project.query.order_by(Project.name).all()
    ensure_workspace_fuel_oil_opening_accounts(emp.id)

    if request.method == "POST":
        opening_date = parse_date(request.form.get("opening_date"))
        if not opening_date:
            flash("Date is required.", "danger")
            return render_template("workspace/fuel_oil_opening_form.html", row=row, employee=emp, districts=districts, projects=projects)
        district_id = request.form.get("district_id", type=int) or None
        project_id = request.form.get("project_id", type=int) or None
        if _workspace_has_closed_fuel_oil_month_for_date(
            emp.id,
            opening_date,
            district_id=district_id,
            project_id=project_id,
        ):
            flash("This date belongs to a closed Fuel/Oil close batch. Reopen fuel/oil close first to make changes.", "danger")
            return render_template("workspace/fuel_oil_opening_form.html", row=row, employee=emp, districts=districts, projects=projects)

        def _to_dec(name):
            raw = (request.form.get(name) or "").strip()
            if not raw:
                return Decimal("0")
            return Decimal(str(raw))

        try:
            pump_card_fueling = _to_dec("pump_card_fueling")
            credit_fueling = _to_dec("credit_fueling")
            card_oil_change = _to_dec("card_oil_change")
            credit_oil_change = _to_dec("credit_oil_change")
        except Exception:
            flash("Amount fields must be numeric values.", "danger")
            return render_template("workspace/fuel_oil_opening_form.html", row=row, employee=emp, districts=districts, projects=projects)

        if not row:
            row = WorkspaceFuelOilOpeningExpense(employee_id=emp.id)
            db.session.add(row)
        elif row.journal_entry_id:
            workspace_reverse_journal_entry(row.journal_entry_id)
            row.journal_entry_id = None

        row.opening_date = opening_date
        row.district_id = district_id
        row.project_id = project_id
        row.pump_card_fueling = pump_card_fueling
        row.credit_fueling = credit_fueling
        row.total_fueling = pump_card_fueling + credit_fueling
        row.card_oil_change = card_oil_change
        row.credit_oil_change = credit_oil_change
        row.total_oil_change = card_oil_change + credit_oil_change
        row.total_amount = row.total_fueling + row.total_oil_change
        row.remarks = (request.form.get("remarks") or "").strip() or None
        row.created_by_user_id = session.get("user_id")

        db.session.flush()
        if row.total_amount and Decimal(str(row.total_amount)) > Decimal("0"):
            je = workspace_post_fuel_oil_opening_expense(row)
            row.journal_entry_id = je.id
        db.session.commit()
        flash("Fuel/Oil opening expense saved.", "success")
        return redirect(url_for("workspace_fuel_oil_openings_list"))

    return render_template("workspace/fuel_oil_opening_form.html", row=row, employee=emp, districts=districts, projects=projects)


def workspace_fuel_oil_opening_delete(pk):
    guard, emp = _workspace_guard("workspace_dashboard")
    if guard:
        return guard
    row = WorkspaceFuelOilOpeningExpense.query.filter_by(employee_id=emp.id, id=pk).first_or_404()
    if _workspace_has_closed_fuel_oil_month_for_date(
        emp.id,
        row.opening_date,
        district_id=row.district_id,
        project_id=row.project_id,
    ):
        flash("Cannot delete fuel/oil opening from a closed fuel/oil batch. Reopen fuel/oil close first.", "danger")
        return redirect(url_for("workspace_fuel_oil_openings_list"))
    if row.journal_entry_id:
        workspace_reverse_journal_entry(row.journal_entry_id)
    db.session.delete(row)
    db.session.commit()
    flash("Fuel/Oil opening expense deleted.", "success")
    return redirect(url_for("workspace_fuel_oil_openings_list"))


def workspace_fuel_oil_opening_import():
    guard, emp = _workspace_guard("workspace_dashboard")
    if guard:
        return guard

    import_errors = []
    if request.method == "POST":
        file_obj = request.files.get("file")
        if not file_obj or not (file_obj.filename or "").strip():
            flash("Please select an Excel or CSV file.", "warning")
            return redirect(url_for("workspace_fuel_oil_opening_import"))

        filename = file_obj.filename or ""
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in ("xlsx", "xls", "csv"):
            flash("Unsupported file type. Use .xlsx, .xls or .csv.", "danger")
            return redirect(url_for("workspace_fuel_oil_opening_import"))

        try:
            import pandas as pd

            if ext in ("xlsx", "xls"):
                df = pd.read_excel(file_obj)
            else:
                df = pd.read_csv(file_obj)

            required_cols = ["opening_date", "district", "project"]
            missing = [c for c in required_cols if c not in df.columns]
            if missing:
                flash(f"Missing required columns: {', '.join(missing)}", "danger")
                return redirect(url_for("workspace_fuel_oil_opening_import"))

            district_map = {d.name.strip().lower(): d.id for d in District.query.order_by(District.name).all() if d.name}
            project_map = {p.name.strip().lower(): p.id for p in Project.query.order_by(Project.name).all() if p.name}
            ensure_workspace_fuel_oil_opening_accounts(emp.id)
            add_rows = []

            def _dec(raw):
                if raw is None:
                    return Decimal("0")
                s = str(raw).strip()
                if not s or s.lower() == "nan":
                    return Decimal("0")
                return Decimal(s)

            def _date_from_any(v):
                if v is None:
                    return None
                if hasattr(v, "date"):
                    try:
                        return v.date()
                    except Exception:
                        pass
                s = str(v).strip()
                if not s or s.lower() == "nan":
                    return None
                d1 = parse_date(s)
                if d1:
                    return d1
                try:
                    return pd.to_datetime(s, errors="coerce").date()
                except Exception:
                    return None

            for idx, row in df.iterrows():
                row_no = idx + 2
                issues = []

                opening_date = _date_from_any(row.get("opening_date"))
                if not opening_date:
                    issues.append('"opening_date" is required (dd-mm-yyyy or yyyy-mm-dd).')

                district_name = str(row.get("district", "")).strip() if not pd.isna(row.get("district")) else ""
                district_id = district_map.get(district_name.lower()) if district_name else None
                if not district_id:
                    issues.append(f'District "{district_name or "-"}" not found.')

                project_name = str(row.get("project", "")).strip() if not pd.isna(row.get("project")) else ""
                project_id = project_map.get(project_name.lower()) if project_name else None
                if not project_id:
                    issues.append(f'Project "{project_name or "-"}" not found.')

                try:
                    pump_card_fueling = _dec(row.get("pump_card_fueling", 0))
                    credit_fueling = _dec(row.get("credit_fueling", 0))
                    card_oil_change = _dec(row.get("card_oil_change", 0))
                    credit_oil_change = _dec(row.get("credit_oil_change", 0))
                except Exception:
                    issues.append("Amount fields must be numeric.")
                    pump_card_fueling = credit_fueling = card_oil_change = credit_oil_change = Decimal("0")

                if opening_date and _workspace_has_closed_fuel_oil_month_for_date(
                    emp.id,
                    opening_date,
                    district_id=district_id,
                    project_id=project_id,
                ):
                    issues.append("Date belongs to a closed fuel/oil close batch. Reopen fuel/oil close first.")

                if issues:
                    import_errors.append({
                        "row": row_no,
                        "identifier": f"{district_name or '-'} / {project_name or '-'}",
                        "message": "; ".join(issues),
                    })
                    continue

                total_fueling = pump_card_fueling + credit_fueling
                total_oil_change = card_oil_change + credit_oil_change
                total_amount = total_fueling + total_oil_change
                remarks = str(row.get("remarks", "")).strip() if "remarks" in df.columns and not pd.isna(row.get("remarks")) else ""
                add_rows.append({
                    "opening_date": opening_date,
                    "district_id": district_id,
                    "project_id": project_id,
                    "pump_card_fueling": pump_card_fueling,
                    "credit_fueling": credit_fueling,
                    "total_fueling": total_fueling,
                    "card_oil_change": card_oil_change,
                    "credit_oil_change": credit_oil_change,
                    "total_oil_change": total_oil_change,
                    "total_amount": total_amount,
                    "remarks": remarks or None,
                })

            if import_errors:
                return render_template("workspace/fuel_oil_opening_import.html", employee=emp, import_errors=import_errors)

            for payload in add_rows:
                rec = WorkspaceFuelOilOpeningExpense(
                    employee_id=emp.id,
                    opening_date=payload["opening_date"],
                    district_id=payload["district_id"],
                    project_id=payload["project_id"],
                    pump_card_fueling=payload["pump_card_fueling"],
                    credit_fueling=payload["credit_fueling"],
                    total_fueling=payload["total_fueling"],
                    card_oil_change=payload["card_oil_change"],
                    credit_oil_change=payload["credit_oil_change"],
                    total_oil_change=payload["total_oil_change"],
                    total_amount=payload["total_amount"],
                    remarks=payload["remarks"],
                    created_by_user_id=session.get("user_id"),
                )
                db.session.add(rec)
                db.session.flush()
                if rec.total_amount and Decimal(str(rec.total_amount)) > Decimal("0"):
                    je = workspace_post_fuel_oil_opening_expense(rec)
                    rec.journal_entry_id = je.id

            db.session.commit()
            flash(f"{len(add_rows)} fuel/oil opening rows imported successfully.", "success")
            return redirect(url_for("workspace_fuel_oil_openings_list"))
        except Exception as exc:
            db.session.rollback()
            flash(f"Import failed: {exc}", "danger")

    return render_template("workspace/fuel_oil_opening_import.html", employee=emp, import_errors=import_errors)


def workspace_fuel_oil_opening_import_template():
    guard, _emp = _workspace_guard("workspace_dashboard")
    if guard:
        return guard
    headers = [
        "opening_date",
        "district",
        "project",
        "pump_card_fueling",
        "credit_fueling",
        "card_oil_change",
        "credit_oil_change",
        "remarks",
    ]
    rows = [
        ["01-03-2026", "Muzaffargarh", "RAS-1034", 35000, 22000, 6000, 2500, "Date Range: 1-15(Mar-26)"],
        ["16-03-2026", "Muzaffargarh", "RAS-1034", 32000, 18000, 5400, 2100, "Date Range: 16-31(Mar-26)"],
    ]
    return generate_excel_template(
        headers,
        rows,
        required_columns=["opening_date", "district", "project"],
        filename="workspace_fuel_oil_opening_import_template.xlsx",
    )


def _pending_fuel_oil_close_spells(employee_id):
    bucket = {}

    def _spell_key(dt):
        y, m = dt.year, dt.month
        last = monthrange(y, m)[1]
        if dt.day <= 15:
            return y, m, 1, 15
        return y, m, 16, last

    for row in WorkspaceFuelOilOpeningExpense.query.filter(
        WorkspaceFuelOilOpeningExpense.employee_id == employee_id,
        WorkspaceFuelOilOpeningExpense.fuel_oil_month_close_id.is_(None),
        WorkspaceFuelOilOpeningExpense.total_amount > 0,
    ).all():
        if not row.opening_date or not row.district_id or not row.project_id:
            continue
        y, m, sday, eday = _spell_key(row.opening_date)
        k = (row.district_id, row.project_id, y, m, sday, eday)
        bucket[k] = bucket.get(k, Decimal("0")) + Decimal(str(row.total_amount or 0))

    if not bucket:
        return []

    district_map = {d.id: d.name for d in District.query.all()}
    project_map = {p.id: p.name for p in Project.query.all()}
    out = []
    for (district_id, project_id, y, m, sday, eday), amt in bucket.items():
        if amt <= 0:
            continue
        start_dt = date(y, m, sday)
        end_dt = date(y, m, eday)
        out.append({
            "district_id": district_id,
            "project_id": project_id,
            "district_name": district_map.get(district_id, "-"),
            "project_name": project_map.get(project_id, "-"),
            "period_start": start_dt,
            "period_end": end_dt,
            "spell_label": f"{sday:02d}-{eday:02d}({start_dt.strftime('%m-%y')})",
            "amount": amt,
        })
    out.sort(key=lambda r: (r["period_start"], r["district_name"], r["project_name"]), reverse=True)
    return out


def workspace_fuel_oil_month_close():
    guard, emp = _workspace_guard("workspace_month_close")
    if guard:
        return guard

    can_manage_month_close = _is_master_or_admin_user()
    accounts = Account.query.filter_by(is_active=True).order_by(Account.code).all()
    districts = District.query.order_by(District.name).all()
    projects = Project.query.order_by(Project.name).all()
    rows = WorkspaceFuelOilMonthClose.query.filter_by(employee_id=emp.id).order_by(WorkspaceFuelOilMonthClose.id.desc()).all()
    spell_rows = _pending_fuel_oil_close_spells(emp.id)
    default_company_account_id = emp.wallet_account_id or None

    if request.method == "POST":
        period_start = parse_date(request.form.get("period_start"))
        period_end = parse_date(request.form.get("period_end"))
        company_account_id = request.form.get("company_account_id", type=int) or None
        district = db.session.get(District, request.form.get("district_id", type=int) or 0)
        project = db.session.get(Project, request.form.get("project_id", type=int) or 0)
        notes = (request.form.get("notes") or "").strip()
        if not period_start or not period_end:
            flash("Period start and end are required.", "danger")
        elif period_end < period_start:
            flash("Period end must be on/after period start.", "danger")
        elif not district or not project:
            flash("District and Project are required for fuel/oil close.", "danger")
        else:
            try:
                close_row = workspace_close_fuel_oil_month(
                    employee_id=emp.id,
                    period_start=period_start,
                    period_end=period_end,
                    district_id=district.id,
                    project_id=project.id,
                    district_name=district.name,
                    project_name=project.name,
                    company_account_id=company_account_id,
                    user_id=session.get("user_id"),
                    notes=notes,
                )
                db.session.commit()
                flash(f"Fuel/Oil month close completed. Batch #{close_row.id}", "success")
                return redirect(url_for("workspace_fuel_oil_month_close"))
            except Exception as exc:
                db.session.rollback()
                flash(f"Fuel/Oil month close failed: {exc}", "danger")

    return render_template(
        "workspace/fuel_oil_month_close.html",
        employee=emp,
        rows=rows,
        accounts=accounts,
        districts=districts,
        projects=projects,
        spell_rows=spell_rows,
        default_company_account_id=default_company_account_id,
        can_manage_month_close=can_manage_month_close,
    )


def workspace_fuel_oil_month_close_reverse(pk):
    guard, emp = _workspace_guard("workspace_month_close")
    if guard:
        return guard
    if not _is_master_or_admin_user():
        flash("Only admin/master can reopen a fuel/oil close batch.", "danger")
        return redirect(url_for("workspace_fuel_oil_month_close_list"))

    row = WorkspaceFuelOilMonthClose.query.filter_by(id=pk, employee_id=emp.id).first_or_404()
    try:
        if row.company_journal_entry_id:
            reverse_company_journal_entry(row.company_journal_entry_id)
            row.company_journal_entry_id = None
        WorkspaceFuelOilOpeningExpense.query.filter_by(fuel_oil_month_close_id=row.id).update({"fuel_oil_month_close_id": None}, synchronize_session=False)
        db.session.delete(row)
        db.session.commit()
        flash("Fuel/Oil close batch reopened successfully.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"Fuel/Oil close reopen failed: {exc}", "danger")
    return redirect(url_for("workspace_fuel_oil_month_close_list"))


def workspace_fuel_oil_month_close_list():
    guard, emp = _workspace_guard("workspace_month_close")
    if guard:
        return guard
    can_manage_month_close = _is_master_or_admin_user()
    page = max(request.args.get("page", 1, type=int) or 1, 1)
    per_page = request.args.get("per_page", 25, type=int) or 25
    if per_page not in (25, 50, 100, 200):
        per_page = 25
    search = (request.args.get("search") or "").strip()
    from_date = parse_date(request.args.get("from_date"))
    to_date = parse_date(request.args.get("to_date"))

    query = (
        db.session.query(WorkspaceFuelOilMonthClose)
        .outerjoin(District, WorkspaceFuelOilMonthClose.district_id == District.id)
        .outerjoin(Project, WorkspaceFuelOilMonthClose.project_id == Project.id)
        .outerjoin(JournalEntry, WorkspaceFuelOilMonthClose.company_journal_entry_id == JournalEntry.id)
        .filter(WorkspaceFuelOilMonthClose.employee_id == emp.id)
    )
    if from_date:
        query = query.filter(WorkspaceFuelOilMonthClose.period_start >= from_date)
    if to_date:
        query = query.filter(WorkspaceFuelOilMonthClose.period_end <= to_date)
    if search:
        query = query.filter(
            _workspace_multi_word_filter(
                search,
                cast(WorkspaceFuelOilMonthClose.id, String),
                District.name,
                Project.name,
                WorkspaceFuelOilMonthClose.status,
                WorkspaceFuelOilMonthClose.notes,
                JournalEntry.entry_number,
                cast(WorkspaceFuelOilMonthClose.company_journal_entry_id, String),
            )
        )

    total_amount = (
        query.with_entities(db.func.coalesce(db.func.sum(WorkspaceFuelOilMonthClose.total_amount), 0)).scalar() or 0
    )
    pagination = query.order_by(
        WorkspaceFuelOilMonthClose.period_end.desc(),
        WorkspaceFuelOilMonthClose.id.desc(),
    ).paginate(page=page, per_page=per_page, error_out=False)

    return render_template(
        "workspace/fuel_oil_month_close_list.html",
        employee=emp,
        rows=pagination.items,
        pagination=pagination,
        per_page=per_page,
        search=search,
        from_date=from_date,
        to_date=to_date,
        total_amount=total_amount,
        can_manage_month_close=can_manage_month_close,
    )


def workspace_fund_transfers_list():
    guard, emp = _workspace_guard("workspace_transfer_list")
    if guard:
        return guard
    page = max(request.args.get("page", 1, type=int) or 1, 1)
    raw_per_page = request.args.get("per_page", 25, type=int) or 25
    if raw_per_page in (25, 50, 100, 200):
        per_page = raw_per_page
    elif raw_per_page >= 99999:
        per_page = None  # will be set to query.count() after filters
    else:
        per_page = 25
    search = (request.args.get("search") or "").strip()
    from_date = parse_date(request.args.get("from_date"))
    to_date = parse_date(request.args.get("to_date"))

    from_acct = aliased(WorkspaceAccount)
    to_acct = aliased(WorkspaceAccount)
    query = (
        db.session.query(WorkspaceFundTransfer)
        .options(
            joinedload(WorkspaceFundTransfer.from_account),
            joinedload(WorkspaceFundTransfer.to_account),
        )
        .outerjoin(from_acct, WorkspaceFundTransfer.from_account_id == from_acct.id)
        .outerjoin(to_acct, WorkspaceFundTransfer.to_account_id == to_acct.id)
        .filter(WorkspaceFundTransfer.employee_id == emp.id)
    )

    if from_date:
        query = query.filter(WorkspaceFundTransfer.transfer_date >= from_date)
    if to_date:
        query = query.filter(WorkspaceFundTransfer.transfer_date <= to_date)
    if search:
        query = _workspace_fund_transfer_search_filter(query, search, from_acct, to_acct)

    total_amount = (
        query.with_entities(db.func.coalesce(db.func.sum(WorkspaceFundTransfer.amount), 0)).scalar() or 0
    )
    _wsft_not_ideal = or_(
        WorkspaceFundTransfer.attachment.is_(None),
        WorkspaceFundTransfer.attachment == '',
        and_(
            WorkspaceFundTransfer.attachment.isnot(None),
            WorkspaceFundTransfer.attachment != '',
            not_(or_(WorkspaceFundTransfer.attachment.ilike('http://%'), WorkspaceFundTransfer.attachment.ilike('https://%'))),
        ),
    )
    show_upload_media_columns = query.filter(_wsft_not_ideal).limit(1).first() is not None

    if per_page is None:
        per_page = max(query.count(), 1)

    pagination = query.order_by(
        WorkspaceFundTransfer.transfer_date.desc(),
        WorkspaceFundTransfer.id.desc(),
    ).paginate(page=page, per_page=per_page, error_out=False)

    account_display_map = _build_workspace_account_display_map(emp.id, active_only=False)

    return render_template(
        "workspace/transfers_list.html",
        rows=pagination.items,
        pagination=pagination,
        per_page=per_page,
        search=search,
        from_date=from_date,
        to_date=to_date,
        employee=emp,
        total_amount=total_amount,
        show_upload_media_columns=show_upload_media_columns,
        account_display_map=account_display_map,
    )


def workspace_fund_transfer_form(pk=None):
    guard, emp = _workspace_guard("workspace_transfer_edit" if pk else "workspace_transfer_add")
    if guard:
        return guard
    ensure_workspace_base_accounts(emp.id)
    _ensure_workspace_driver_accounts(emp)
    row = WorkspaceFundTransfer.query.filter_by(employee_id=emp.id, id=pk).first() if pk else None
    if pk and not row:
        flash("Workspace transfer not found.", "danger")
        return redirect(url_for("workspace_fund_transfers_list"))

    # Ensure counterparty accounts exist so To Account shows drivers + parties directly.
    parties = WorkspaceParty.query.filter_by(employee_id=emp.id, is_active=True).order_by(WorkspaceParty.name).all()
    party_ids = [int(p.id) for p in parties if p and p.id]
    existing_party_ids = set()
    if party_ids:
        existing_party_ids = {
            int(r[0]) for r in db.session.query(WorkspaceAccount.entity_id).filter(
                WorkspaceAccount.employee_id == emp.id,
                WorkspaceAccount.entity_type == "party",
                WorkspaceAccount.entity_id.in_(party_ids),
            ).all() if r and r[0]
        }
    for p in parties:
        if int(p.id) in existing_party_ids:
            continue
        try:
            ensure_workspace_counterparty_account(emp.id, party_id=p.id)
        except Exception:
            pass
    db.session.flush()

    accounts = WorkspaceAccount.query.filter_by(employee_id=emp.id, is_active=True).order_by(WorkspaceAccount.code).all()
    categories = FundTransferCategory.query.order_by(FundTransferCategory.name).all()
    account_display_map = _build_workspace_account_display_map(emp.id, active_only=True)

    account_balance_json = {}
    for a in accounts:
        bal = Decimal(str(a.current_balance or 0))
        if a.account_type in ('Asset', 'Expense'):
            side = 'Dr' if bal >= 0 else 'Cr'
        else:
            side = 'Cr' if bal >= 0 else 'Dr'
        account_balance_json[str(a.id)] = {
            'balance': float(bal),
            'balance_str': f"{abs(bal):,.2f} {side}",
            'ledger_url': f'/workspace/ledger?account_id={a.id}',
        }

    last_saved_transfer = None
    if not pk:
        last_saved_transfer = (
            WorkspaceFundTransfer.query.filter_by(employee_id=emp.id)
            .options(joinedload(WorkspaceFundTransfer.from_account), joinedload(WorkspaceFundTransfer.to_account))
            .order_by(WorkspaceFundTransfer.created_at.desc(), WorkspaceFundTransfer.id.desc())
            .first()
        )

    def _transfer_form_ctx(extra=None):
        ctx = dict(
            row=row,
            employee=emp,
            accounts=accounts,
            account_display_map=account_display_map,
            categories=categories,
            existing_attachment=(row.attachment if row else None),
            account_balance_json=account_balance_json,
            last_saved_transfer=last_saved_transfer,
            can_manage_slip_profiles=_can_manage_slip_profiles(),
        )
        if extra:
            ctx.update(extra)
        return ctx

    if request.method == "POST":
        transfer_date_raw = (request.form.get("transfer_date") or "").strip()
        amount_raw = (request.form.get("amount") or "").strip()
        from_account_id = request.form.get("from_account_id", type=int)
        to_account_id = request.form.get("to_account_id", type=int)
        validation_errors = []
        transfer_date = None
        amount = None

        if not transfer_date_raw:
            validation_errors.append("Transfer Date bharna zaroori hai.")
        else:
            try:
                transfer_date = parse_date(transfer_date_raw)
                if not transfer_date:
                    validation_errors.append("Transfer Date sahi format mein likhein (dd-mm-yyyy).")
            except Exception:
                validation_errors.append("Transfer Date sahi format mein likhein (dd-mm-yyyy).")

        if not amount_raw:
            validation_errors.append("Amount bharna zaroori hai.")
        else:
            try:
                amount = Decimal(str(amount_raw))
                if amount <= 0:
                    validation_errors.append("Amount zero se zyada hona chahiye.")
            except (InvalidOperation, ValueError, TypeError):
                validation_errors.append("Amount sahi number mein likhein.")

        if not from_account_id:
            validation_errors.append("From Account select karein.")
        if not to_account_id:
            validation_errors.append("To Account select karein.")
        elif from_account_id and from_account_id == to_account_id:
            validation_errors.append("From aur To Account alag hone chahiye.")

        if validation_errors:
            for msg in validation_errors:
                flash(msg, "danger")
            return render_template("workspace/transfer_form.html", **_transfer_form_ctx())

        attachment_url = _upload_workspace_transfer_attachment(request.files.get("attachment"))

        if not row:
            row = WorkspaceFundTransfer(
                employee_id=emp.id,
                transfer_number=f"WT-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
                created_by_user_id=session.get("user_id"),
            )
            db.session.add(row)
        else:
            workspace_reverse_journal_entry(row.journal_entry_id)
            row.journal_entry_id = None
            if request.form.get("remove_attachment") == "1":
                _delete_workspace_transfer_attachment(row.attachment)
                row.attachment = None
        row.transfer_date = transfer_date or pk_date()
        row.from_account_id = from_account_id
        row.to_account_id = to_account_id
        row.to_workspace_party_id = None
        row.to_driver_id = None
        row.amount = amount
        mode = (request.form.get("payment_mode") or "Cash").strip()
        row.payment_mode = mode if mode in ("Cash", "Bank Transfer", "Cheque", "Online") else "Cash"
        row.reference_no = (request.form.get("reference_no") or "").strip() or None
        row.description = (request.form.get("description") or "").strip() or None
        row.category = (request.form.get("category") or "").strip() or None
        if attachment_url:
            _delete_workspace_transfer_attachment(row.attachment)
            row.attachment = attachment_url
        db.session.flush()
        je = workspace_post_transfer(row)
        row.journal_entry_id = je.id
        db.session.commit()
        flash("Workspace transfer saved.", "success")
        if request.form.get("_save_action") == "save_add":
            return redirect(url_for("workspace_fund_transfer_new"))
        return redirect(url_for("workspace_fund_transfers_list"))
    return render_template("workspace/transfer_form.html", **_transfer_form_ctx())


def workspace_fund_transfer_delete(pk):
    guard, emp = _workspace_guard("workspace_transfer_delete")
    if guard:
        return guard
    row = WorkspaceFundTransfer.query.filter_by(employee_id=emp.id, id=pk).first_or_404()
    workspace_reverse_journal_entry(row.journal_entry_id)
    _delete_workspace_transfer_attachment(row.attachment)
    db.session.delete(row)
    db.session.commit()
    flash("Workspace transfer deleted.", "success")
    return redirect(url_for("workspace_fund_transfers_list"))


def workspace_fund_transfer_view(pk):
    guard, emp = _workspace_guard("workspace_transfer_list")
    if guard:
        return guard
    row = WorkspaceFundTransfer.query.filter_by(employee_id=emp.id, id=pk).first_or_404()
    from routes import _safe_internal_path
    back_default = url_for("workspace_fund_transfers_list")
    back_url = _safe_internal_path(request.args.get("return_to"), back_default)
    return render_template(
        "finance/fund_transfer_detail.html",
        rec=row,
        is_workspace=True,
        title="Workspace fund transfer — " + (row.transfer_number or ""),
        back_url=back_url,
        return_to_path=request.full_path,
    )


def workspace_fund_transfer_media(pk):
    guard, emp = _workspace_guard("workspace_transfer_list")
    if guard:
        return guard
    from routes import _safe_internal_path
    row = WorkspaceFundTransfer.query.filter_by(employee_id=emp.id, id=pk).first_or_404()
    back_default = url_for("workspace_fund_transfers_list")
    back_url = _safe_internal_path(request.args.get("return_to"), back_default)
    media_items = _ws_ft_media_items_for_transfer(row)
    sub = f"Transfer: {row.transfer_number} | {row.transfer_date.strftime('%d-%m-%Y') if row.transfer_date else '—'}"
    tmpl = dict(
        rec=row,
        media_items=media_items,
        media_title="Workspace fund transfer — Media",
        media_header_subline=sub,
        back_url=back_url,
        back_link_label="Back to list",
        download_all_url=url_for("workspace_fund_transfer_media_download_all", pk=row.id),
    )
    if not media_items:
        tmpl["media_empty_hint"] = "No receipt or attachment for this transfer."
        tmpl["show_download_all"] = False
    return render_template("maintenance_expense_media.html", **tmpl)


def workspace_fund_transfer_media_download(pk):
    err, row = _ws_ft_get_transfer_for_media(pk)
    if err:
        return err
    stored_path = (row.attachment or '').strip()
    if not stored_path:
        flash('No attachment available for download.', 'warning')
        return redirect(url_for('workspace_fund_transfer_media', pk=row.id))

    dl_name = _ws_ft_attachment_download_name(stored_path, 'Receipt')
    from routes import _maintenance_attachment_local_full_path
    local_full = _maintenance_attachment_local_full_path(stored_path)
    if local_full:
        return send_file(local_full, as_attachment=True, download_name=dl_name, conditional=True, max_age=0)

    try:
        blob, mime = _ws_ft_read_attachment_bytes(stored_path)
    except Exception as ex:
        current_app.logger.warning('Workspace transfer media download failed (%s): %s', row.id, ex)
        flash('Download failed for this attachment.', 'danger')
        return redirect(url_for('workspace_fund_transfer_media', pk=row.id))
    if not blob:
        flash('Attachment file is empty.', 'warning')
        return redirect(url_for('workspace_fund_transfer_media', pk=row.id))
    return send_file(
        BytesIO(blob),
        as_attachment=True,
        download_name=dl_name,
        mimetype=(mime or 'application/octet-stream'),
        max_age=0,
    )


def workspace_fund_transfer_media_download_all(pk):
    err, row = _ws_ft_get_transfer_for_media(pk)
    if err:
        return err
    stored_path = (row.attachment or '').strip()
    if not stored_path:
        flash('No media files available for download.', 'warning')
        return redirect(url_for('workspace_fund_transfer_media', pk=row.id))

    dl_name = _ws_ft_attachment_download_name(stored_path, 'Receipt')
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
    zip_path = tmp.name
    tmp.close()
    added = 0
    try:
        with zipfile.ZipFile(zip_path, mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
            from routes import _maintenance_attachment_local_full_path
            local_full = _maintenance_attachment_local_full_path(stored_path)
            if local_full:
                try:
                    zf.write(local_full, arcname=dl_name)
                    added += 1
                except Exception:
                    pass
            if added == 0:
                try:
                    blob, _mime = _ws_ft_read_attachment_bytes(stored_path)
                    if blob:
                        zf.writestr(dl_name, blob)
                        added += 1
                except Exception:
                    pass
        if added == 0:
            try:
                os.remove(zip_path)
            except OSError:
                pass
            flash('No files could be packed for download.', 'danger')
            return redirect(url_for('workspace_fund_transfer_media', pk=row.id))
    except Exception as ex:
        try:
            os.remove(zip_path)
        except OSError:
            pass
        current_app.logger.warning('Workspace transfer zip creation failed (%s): %s', row.id, ex)
        flash('Unable to prepare media ZIP right now.', 'danger')
        return redirect(url_for('workspace_fund_transfer_media', pk=row.id))

    @after_this_request
    def _cleanup_ws_transfer_zip(resp):
        try:
            os.remove(zip_path)
        except OSError:
            pass
        return resp

    date_part = row.transfer_date.strftime('%Y%m%d') if row.transfer_date else datetime.utcnow().strftime('%Y%m%d')
    tn = secure_filename(row.transfer_number or f'transfer_{row.id}')
    archive_name = f'workspace_transfer_{tn}_{date_part}.zip'
    return send_file(zip_path, as_attachment=True, download_name=archive_name, mimetype='application/zip', max_age=0)


def workspace_ledger():
    guard, emp = _workspace_guard("workspace_ledger")
    if guard:
        return guard
    accounts = WorkspaceAccount.query.filter_by(employee_id=emp.id).order_by(WorkspaceAccount.code).all()
    driver_ids = sorted({
        int(a.entity_id) for a in accounts
        if (a.entity_type or '').strip().lower() == 'driver' and a.entity_id
    })
    drivers_by_id = {}
    if driver_ids:
        for drv in Driver.query.filter(Driver.id.in_(driver_ids)).all():
            drivers_by_id[int(drv.id)] = drv

    def _driver_vehicle_no(drv):
        if not drv:
            return None
        if getattr(drv, 'vehicle', None) and getattr(drv.vehicle, 'vehicle_no', None):
            return drv.vehicle.vehicle_no
        if getattr(drv, 'vehicle_id', None):
            v = db.session.get(Vehicle, drv.vehicle_id)
            if v and v.vehicle_no:
                return v.vehicle_no
        v = Vehicle.query.filter_by(driver_id=drv.id).order_by(Vehicle.id.desc()).first()
        return v.vehicle_no if v and v.vehicle_no else None

    account_display_map = {}
    for a in accounts:
        label = f"{a.code} - {a.name}"
        if (a.entity_type or '').strip().lower() == 'driver' and a.entity_id:
            drv = drivers_by_id.get(int(a.entity_id))
            if drv:
                v_no = _driver_vehicle_no(drv)
                if v_no:
                    label = f"{label} | Vehicle: {v_no}"
        account_display_map[a.id] = label

    account_id = request.args.get("account_id", type=int) or (accounts[0].id if accounts else None)
    from_date = parse_date(request.args.get("from_date"))
    to_date = parse_date(request.args.get("to_date"))
    category_filter_raw = (request.args.get("category_filter") or "").strip()
    selected_categories = [c.strip() for c in category_filter_raw.split(",") if c.strip()]
    if not selected_categories:
        single_cat = (request.args.get("category") or "").strip()
        if single_cat:
            selected_categories = [single_cat]
    category = selected_categories[0] if len(selected_categories) == 1 else None
    category_param = selected_categories if len(selected_categories) > 1 else category
    ledger = workspace_get_account_ledger(account_id, from_date=from_date, to_date=to_date, category=category_param) if account_id else None
    category_choices = []
    try:
        category_choices = [
            c[0] for c in db.session.query(WorkspaceJournalEntry.category)
            .filter(
                WorkspaceJournalEntry.employee_id == emp.id,
                WorkspaceJournalEntry.category.isnot(None),
                WorkspaceJournalEntry.category != ""
            )
            .distinct()
            .order_by(WorkspaceJournalEntry.category.asc())
            .all()
            if c and c[0]
        ]
    except Exception:
        category_choices = []
    transfer_map = {}
    expense_ref_map = {}
    if ledger and ledger.get("transactions"):
        transfer_ids = [
            int(t.get("reference_id"))
            for t in ledger["transactions"]
            if (t.get("reference_type") or "") == "WorkspaceFundTransfer" and t.get("reference_id")
        ]
        if transfer_ids:
            rows = WorkspaceFundTransfer.query.filter(
                WorkspaceFundTransfer.employee_id == emp.id,
                WorkspaceFundTransfer.id.in_(sorted(set(transfer_ids)))
            ).all()
            transfer_map = {r.id: (r.transfer_number or f"WT-{r.id}") for r in rows if r}
        fuel_ids = [
            int(t.get("reference_id"))
            for t in ledger["transactions"]
            if (t.get("reference_type") or "") == "FuelExpense" and t.get("reference_id")
        ]
        if fuel_ids:
            rows = FuelExpense.query.filter(
                FuelExpense.employee_id == emp.id,
                FuelExpense.id.in_(sorted(set(fuel_ids)))
            ).all()
            for r in rows:
                expense_ref_map[f"FuelExpense:{r.id}"] = f"Fuel Expense #{r.id}"
        oil_ids = [
            int(t.get("reference_id"))
            for t in ledger["transactions"]
            if (t.get("reference_type") or "") == "OilExpense" and t.get("reference_id")
        ]
        if oil_ids:
            rows = OilExpense.query.filter(
                OilExpense.employee_id == emp.id,
                OilExpense.id.in_(sorted(set(oil_ids)))
            ).all()
            for r in rows:
                expense_ref_map[f"OilExpense:{r.id}"] = f"Oil Expense #{r.id}"
        maint_ids = [
            int(t.get("reference_id"))
            for t in ledger["transactions"]
            if (t.get("reference_type") or "") == "MaintenanceExpense" and t.get("reference_id")
        ]
        if maint_ids:
            rows = MaintenanceExpense.query.filter(
                MaintenanceExpense.employee_id == emp.id,
                MaintenanceExpense.id.in_(sorted(set(maint_ids)))
            ).all()
            for r in rows:
                expense_ref_map[f"MaintenanceExpense:{r.id}"] = f"Maintenance Expense #{r.id}"
    return render_template(
        "workspace/ledger.html",
        employee=emp,
        accounts=accounts,
        account_display_map=account_display_map,
        account_id=account_id,
        ledger=ledger,
        transfer_map=transfer_map,
        expense_ref_map=expense_ref_map,
        from_date=from_date,
        to_date=to_date,
        category=category,
        selected_categories=selected_categories,
        category_choices=category_choices,
    )


def _resolve_transfer_account_name(prefix, transfer):
    if not transfer:
        return "-"
    person_id = getattr(transfer, f"{prefix}_employee_id", None)
    if person_id:
        acct = Account.query.filter_by(entity_type="employee", entity_id=person_id).first()
        return f"{acct.code} - {acct.name}" if acct else "Employee Wallet"
    person_id = getattr(transfer, f"{prefix}_driver_id", None)
    if person_id:
        acct = Account.query.filter_by(entity_type="driver", entity_id=person_id).first()
        return f"{acct.code} - {acct.name}" if acct else "Driver Wallet"
    person_id = getattr(transfer, f"{prefix}_party_id", None)
    if person_id:
        acct = Account.query.filter_by(entity_type="party", entity_id=person_id).first()
        return f"{acct.code} - {acct.name}" if acct else "Party Ledger"
    person_id = getattr(transfer, f"{prefix}_company_id", None)
    if person_id:
        acct = Account.query.filter_by(entity_type="company", entity_id=person_id).first()
        return f"{acct.code} - {acct.name}" if acct else "Company Account"
    account_id = getattr(transfer, f"{prefix}_account_id", None)
    if account_id:
        acct = db.session.get(Account, account_id)
        if acct:
            return f"{acct.code} - {acct.name}"
    return "-"


def workspace_ledger_transfer_detail(transfer_id):
    guard, emp = _workspace_guard("workspace_ledger")
    if guard:
        return guard
    transfer = WorkspaceFundTransfer.query.filter_by(id=transfer_id, employee_id=emp.id).first_or_404()

    workspace_rows = WorkspaceJournalEntry.query.filter_by(
        employee_id=emp.id,
        reference_type="WorkspaceFundTransfer",
        reference_id=transfer.id,
    ).order_by(WorkspaceJournalEntry.entry_date.asc(), WorkspaceJournalEntry.id.asc()).all()
    from_account_name = f"{transfer.from_account.code} - {transfer.from_account.name}" if transfer.from_account else "-"
    to_account_name = f"{transfer.to_account.code} - {transfer.to_account.name}" if transfer.to_account else "-"
    return render_template(
        "workspace/ledger_transfer_detail.html",
        employee=emp,
        transfer=transfer,
        from_account_name=from_account_name,
        to_account_name=to_account_name,
        workspace_rows=workspace_rows,
    )


def workspace_ledger_journal_detail(journal_entry_id):
    guard, emp = _workspace_guard("workspace_ledger")
    if guard:
        return guard
    je = WorkspaceJournalEntry.query.filter_by(id=journal_entry_id, employee_id=emp.id).first_or_404()
    expense_url = None
    expense_label = None
    if je.reference_type == 'FuelExpense' and je.reference_id:
        expense_url = url_for('fuel_expense_view', pk=je.reference_id)
        expense_label = f'Fuel Expense #{je.reference_id}'
    elif je.reference_type == 'OilExpense' and je.reference_id:
        expense_url = url_for('oil_expense_view', pk=je.reference_id)
        expense_label = f'Oil Expense #{je.reference_id}'
    elif je.reference_type == 'MaintenanceExpense' and je.reference_id:
        expense_url = url_for('maintenance_expense_view', pk=je.reference_id)
        expense_label = f'Maintenance Expense #{je.reference_id}'
    return render_template(
        "workspace/ledger_journal_detail.html",
        employee=emp,
        je=je,
        expense_url=expense_url,
        expense_label=expense_label,
    )


def workspace_month_close():
    guard, emp = _workspace_guard("workspace_month_close")
    if guard:
        return guard
    can_manage_month_close = _is_master_or_admin_user()
    accounts = Account.query.filter_by(is_active=True).order_by(Account.code).all()
    districts = District.query.order_by(District.name).all()
    projects = Project.query.order_by(Project.name).all()
    rows = WorkspaceMonthClose.query.filter_by(employee_id=emp.id).order_by(WorkspaceMonthClose.id.desc()).all()
    spell_rows = _pending_month_close_spells(emp.id)
    default_company_account_id = emp.wallet_account_id or None

    if request.method == "POST":
        period_start = parse_date(request.form.get("period_start"))
        period_end = parse_date(request.form.get("period_end"))
        district_id = request.form.get("district_id", type=int)
        project_id = request.form.get("project_id", type=int)
        company_account_id = request.form.get("company_account_id", type=int)
        notes = (request.form.get("notes") or "").strip()
        district = db.session.get(District, district_id) if district_id else None
        project = db.session.get(Project, project_id) if project_id else None
        if not (period_start and period_end and district and project):
            flash("Period, district and project are required.", "danger")
            return render_template(
                "workspace/month_close.html",
                employee=emp,
                rows=rows,
                accounts=accounts,
                districts=districts,
                projects=projects,
                spell_rows=spell_rows,
                default_company_account_id=default_company_account_id,
                can_manage_month_close=can_manage_month_close,
            )
        try:
            close_row = workspace_close_month(
                employee_id=emp.id,
                period_start=period_start,
                period_end=period_end,
                district_id=district.id,
                project_id=project.id,
                district_name=district.name,
                project_name=project.name,
                company_account_id=company_account_id,
                user_id=session.get("user_id"),
                notes=notes,
            )
            db.session.commit()
            flash(f"Workspace month closed. Batch #{close_row.id}", "success")
            return redirect(url_for("workspace_month_close"))
        except Exception as exc:
            db.session.rollback()
            flash(f"Month close failed: {exc}", "danger")
    return render_template(
        "workspace/month_close.html",
        employee=emp,
        rows=rows,
        accounts=accounts,
        districts=districts,
        projects=projects,
        spell_rows=spell_rows,
        default_company_account_id=default_company_account_id,
        can_manage_month_close=can_manage_month_close,
    )


def workspace_month_close_reverse(pk):
    guard, emp = _workspace_guard("workspace_month_close")
    if guard:
        return guard
    if not _is_master_or_admin_user():
        flash("Only admin/master can reopen a month close batch.", "danger")
        return redirect(url_for("workspace_month_close_list"))

    row = WorkspaceMonthClose.query.filter_by(id=pk, employee_id=emp.id).first_or_404()
    try:
        # Revert linked company posting first, then reopen all linked expenses.
        if row.company_journal_entry_id:
            reverse_company_journal_entry(row.company_journal_entry_id)
            row.company_journal_entry_id = None
        WorkspaceExpense.query.filter_by(month_close_id=row.id).update({"month_close_id": None}, synchronize_session=False)
        WorkspaceOpeningExpense.query.filter_by(month_close_id=row.id).update({"month_close_id": None}, synchronize_session=False)
        db.session.delete(row)
        db.session.commit()
        flash("Month close batch reopened successfully. You can close this period again.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"Month close reopen failed: {exc}", "danger")
    return redirect(url_for("workspace_month_close_list"))


def workspace_month_close_list():
    guard, emp = _workspace_guard("workspace_month_close")
    if guard:
        return guard
    can_manage_month_close = _is_master_or_admin_user()
    page = max(request.args.get("page", 1, type=int) or 1, 1)
    per_page = request.args.get("per_page", 25, type=int) or 25
    if per_page not in (25, 50, 100, 200):
        per_page = 25
    search = (request.args.get("search") or "").strip()
    from_date = parse_date(request.args.get("from_date"))
    to_date = parse_date(request.args.get("to_date"))

    query = (
        db.session.query(WorkspaceMonthClose)
        .outerjoin(District, WorkspaceMonthClose.district_id == District.id)
        .outerjoin(Project, WorkspaceMonthClose.project_id == Project.id)
        .outerjoin(JournalEntry, WorkspaceMonthClose.company_journal_entry_id == JournalEntry.id)
        .filter(WorkspaceMonthClose.employee_id == emp.id)
    )
    if from_date:
        query = query.filter(WorkspaceMonthClose.period_start >= from_date)
    if to_date:
        query = query.filter(WorkspaceMonthClose.period_end <= to_date)
    if search:
        query = query.filter(
            _workspace_multi_word_filter(
                search,
                cast(WorkspaceMonthClose.id, String),
                District.name,
                Project.name,
                WorkspaceMonthClose.status,
                WorkspaceMonthClose.notes,
                JournalEntry.entry_number,
                cast(WorkspaceMonthClose.company_journal_entry_id, String),
            )
        )

    total_expense = (
        query.with_entities(db.func.coalesce(db.func.sum(WorkspaceMonthClose.total_expense), 0)).scalar() or 0
    )
    pagination = query.order_by(
        WorkspaceMonthClose.period_end.desc(),
        WorkspaceMonthClose.id.desc(),
    ).paginate(page=page, per_page=per_page, error_out=False)

    return render_template(
        "workspace/month_close_list.html",
        employee=emp,
        rows=pagination.items,
        pagination=pagination,
        per_page=per_page,
        search=search,
        from_date=from_date,
        to_date=to_date,
        total_expense=total_expense,
        can_manage_month_close=can_manage_month_close,
    )


def workspace_reports():
    guard, emp = _workspace_guard("workspace_reports")
    if guard:
        return guard
    from_date = parse_date(request.args.get("from_date")) if request.args.get("from_date") else None
    to_date = parse_date(request.args.get("to_date")) if request.args.get("to_date") else None
    district_id = request.args.get("district_id", type=int) or 0
    project_id = request.args.get("project_id", type=int) or 0
    active_tab = (request.args.get("tab") or "w-expense").strip() or "w-expense"
    show_expense_summary = request.args.get("expense_summary", "").strip() in ("1", "true", "yes")
    if from_date and to_date and from_date > to_date:
        from_date, to_date = to_date, from_date

    def _apply_common_filters(query, date_col, district_col, project_col):
        if from_date:
            query = query.filter(date_col >= from_date)
        if to_date:
            query = query.filter(date_col <= to_date)
        if district_id:
            query = query.filter(district_col == district_id)
        if project_id:
            query = query.filter(project_col == project_id)
        return query

    fuel_q = _apply_common_filters(
        FuelExpense.query.filter(FuelExpense.employee_id == emp.id),
        FuelExpense.fueling_date,
        FuelExpense.district_id,
        FuelExpense.project_id,
    )
    oil_q = _apply_common_filters(
        OilExpense.query.filter(OilExpense.employee_id == emp.id),
        OilExpense.expense_date,
        OilExpense.district_id,
        OilExpense.project_id,
    )
    maintenance_q = _apply_common_filters(
        MaintenanceExpense.query.filter(MaintenanceExpense.employee_id == emp.id),
        MaintenanceExpense.expense_date,
        MaintenanceExpense.district_id,
        MaintenanceExpense.project_id,
    )
    employee_q = _apply_common_filters(
        EmployeeExpense.query.filter(EmployeeExpense.employee_id == emp.id),
        EmployeeExpense.expense_date,
        EmployeeExpense.district_id,
        EmployeeExpense.project_id,
    )
    opening_q = _apply_common_filters(
        WorkspaceOpeningExpense.query.filter(WorkspaceOpeningExpense.employee_id == emp.id),
        WorkspaceOpeningExpense.opening_date,
        WorkspaceOpeningExpense.district_id,
        WorkspaceOpeningExpense.project_id,
    )
    fuel_oil_opening_q = _apply_common_filters(
        WorkspaceFuelOilOpeningExpense.query.filter(WorkspaceFuelOilOpeningExpense.employee_id == emp.id),
        WorkspaceFuelOilOpeningExpense.opening_date,
        WorkspaceFuelOilOpeningExpense.district_id,
        WorkspaceFuelOilOpeningExpense.project_id,
    )

    # Source of truth: read each amount directly from its own form table.
    fuel_total = Decimal(str(fuel_q.with_entities(db.func.coalesce(db.func.sum(FuelExpense.amount), 0)).scalar() or 0))
    oil_total = Decimal(str(oil_q.with_entities(db.func.coalesce(db.func.sum(OilExpense.total_bill_amount), 0)).scalar() or 0))
    maintenance_total = Decimal(str(
        maintenance_q.with_entities(db.func.coalesce(db.func.sum(MaintenanceExpense.total_bill_amount), 0)).scalar() or 0
    ))
    employee_total = Decimal(str(employee_q.with_entities(db.func.coalesce(db.func.sum(EmployeeExpense.amount), 0)).scalar() or 0))
    opening_total = Decimal(str(
        opening_q.with_entities(db.func.coalesce(db.func.sum(WorkspaceOpeningExpense.total_expense), 0)).scalar() or 0
    ))
    fuel_oil_opening_total = Decimal(str(
        fuel_oil_opening_q.with_entities(db.func.coalesce(db.func.sum(WorkspaceFuelOilOpeningExpense.total_amount), 0)).scalar() or 0
    ))

    source_totals = {
        "fuel_expense": fuel_total,
        "oil_expense": oil_total,
        "maintenance_expense": maintenance_total,
        "employee_expense": employee_total,
        "opening_expense": opening_total,
        "fuel_oil_opening": fuel_oil_opening_total,
    }
    source_counts = {
        "fuel_expense": fuel_q.count(),
        "oil_expense": oil_q.count(),
        "maintenance_expense": maintenance_q.count(),
        "employee_expense": employee_q.count(),
        "opening_expense": opening_q.count(),
        "fuel_oil_opening": fuel_oil_opening_q.count(),
    }
    source_total_records = sum(source_counts.values())

    tracked_total = sum(source_totals.values(), Decimal("0"))
    transfer_q = WorkspaceFundTransfer.query.filter(WorkspaceFundTransfer.employee_id == emp.id)
    if from_date:
        transfer_q = transfer_q.filter(WorkspaceFundTransfer.transfer_date >= from_date)
    if to_date:
        transfer_q = transfer_q.filter(WorkspaceFundTransfer.transfer_date <= to_date)
    transfer_total = Decimal(str(
        transfer_q.with_entities(db.func.coalesce(db.func.sum(WorkspaceFundTransfer.amount), 0)).scalar() or 0
    ))

    month_close_q = WorkspaceMonthClose.query.filter(WorkspaceMonthClose.employee_id == emp.id)
    if from_date:
        month_close_q = month_close_q.filter(WorkspaceMonthClose.period_start >= from_date)
    if to_date:
        month_close_q = month_close_q.filter(WorkspaceMonthClose.period_end <= to_date)
    if district_id:
        month_close_q = month_close_q.filter(WorkspaceMonthClose.district_id == district_id)
    if project_id:
        month_close_q = month_close_q.filter(WorkspaceMonthClose.project_id == project_id)
    month_closes = month_close_q.order_by(WorkspaceMonthClose.id.desc()).limit(12).all()
    districts = District.query.order_by(District.name.asc()).all()
    projects = Project.query.order_by(Project.name.asc()).all()

    return render_template(
        "workspace/reports.html",
        employee=emp,
        from_date=from_date,
        to_date=to_date,
        district_id=district_id,
        project_id=project_id,
        active_tab=active_tab,
        show_expense_summary=show_expense_summary,
        districts=districts,
        projects=projects,
        source_totals=source_totals,
        source_counts=source_counts,
        source_total_records=source_total_records,
        tracked_total=tracked_total,
        transfer_total=transfer_total,
        month_closes=month_closes,
    )


def workspace_mpg_report():
    guard, emp = _workspace_guard("workspace_reports")
    if guard:
        return guard

    today = pk_date()
    from_date = parse_date(request.values.get("from_date")) or today
    to_date = parse_date(request.values.get("to_date")) or today
    district_id = request.values.get("district_id", type=int) or 0
    project_id = request.values.get("project_id", type=int) or 0
    selected_vehicle_id = request.values.get("vehicle_id", type=int) or 0
    if from_date > to_date:
        from_date, to_date = to_date, from_date

    def _to_dec(value, fallback=Decimal("0")):
        if value is None or value == "":
            return fallback
        try:
            return Decimal(str(value))
        except Exception:
            return fallback

    def _parse_decimal_input(raw_value):
        raw = (raw_value or "").strip()
        if not raw:
            return None, False
        try:
            return Decimal(raw.replace(",", "")), False
        except (InvalidOperation, ValueError):
            return None, True

    fuel_q = FuelExpense.query.filter(
        FuelExpense.employee_id == emp.id,
        FuelExpense.fueling_date >= from_date,
        FuelExpense.fueling_date <= to_date,
    )
    if district_id:
        fuel_q = fuel_q.filter(FuelExpense.district_id == district_id)
    if project_id:
        fuel_q = fuel_q.filter(FuelExpense.project_id == project_id)
    if selected_vehicle_id:
        fuel_q = fuel_q.filter(FuelExpense.vehicle_id == selected_vehicle_id)

    # Keep MPG row sequencing aligned with Fuel Expense resequence logic:
    # date asc, then non-null current_reading first, then current_reading asc.
    fuel_rows = (
        fuel_q
        .order_by(
            FuelExpense.vehicle_id.asc(),
            FuelExpense.fueling_date.asc(),
            db.case((FuelExpense.current_reading.is_(None), 1), else_=0).asc(),
            FuelExpense.current_reading.asc(),
            FuelExpense.id.asc(),
        )
        .all()
    )

    entries_by_vehicle = {}
    for row in fuel_rows:
        entries_by_vehicle.setdefault(int(row.vehicle_id), []).append(row)

    vehicle_ids = sorted(entries_by_vehicle.keys())
    vehicles_by_id = {}
    if vehicle_ids:
        for vehicle in Vehicle.query.filter(Vehicle.id.in_(vehicle_ids)).all():
            vehicles_by_id[int(vehicle.id)] = vehicle

    task_close_reading_map = {}
    if vehicle_ids:
        task_rows = (
            VehicleDailyTask.query
            .filter(
                VehicleDailyTask.vehicle_id.in_(vehicle_ids),
                VehicleDailyTask.task_date <= to_date,
                VehicleDailyTask.close_reading.isnot(None),
            )
            .order_by(
                VehicleDailyTask.vehicle_id.asc(),
                VehicleDailyTask.task_date.desc(),
                VehicleDailyTask.id.desc(),
            )
            .all()
        )
        for task in task_rows:
            v_id = int(task.vehicle_id)
            if v_id in task_close_reading_map:
                continue
            task_close_reading_map[v_id] = _to_dec(task.close_reading, None)

    saved_inputs = {}
    if vehicle_ids:
        for rec in WorkspaceMpgReportInput.query.filter(
            WorkspaceMpgReportInput.employee_id == emp.id,
            WorkspaceMpgReportInput.from_date == from_date,
            WorkspaceMpgReportInput.to_date == to_date,
            WorkspaceMpgReportInput.vehicle_id.in_(vehicle_ids),
        ).all():
            saved_inputs[int(rec.vehicle_id)] = rec

    if request.method == "POST":
        has_invalid = False
        for loop_vehicle_id in vehicle_ids:
            current_meter, current_meter_invalid = _parse_decimal_input(request.form.get(f"current_odoo_meter_{loop_vehicle_id}"))
            today_fuel, today_fuel_invalid = _parse_decimal_input(request.form.get(f"today_fuel_{loop_vehicle_id}"))
            if current_meter_invalid or today_fuel_invalid:
                has_invalid = True
                continue

            existing = saved_inputs.get(loop_vehicle_id)
            if current_meter is None and today_fuel is None:
                if existing:
                    db.session.delete(existing)
                continue

            if not existing:
                existing = WorkspaceMpgReportInput(
                    employee_id=emp.id,
                    vehicle_id=loop_vehicle_id,
                    from_date=from_date,
                    to_date=to_date,
                    created_by_user_id=session.get("user_id"),
                )
                db.session.add(existing)
                saved_inputs[loop_vehicle_id] = existing

            existing.current_odoo_meter_reading = current_meter
            existing.today_fuel = today_fuel

        if has_invalid:
            db.session.rollback()
            flash("Some numeric inputs are invalid. Please enter valid numbers only.", "danger")
        else:
            db.session.commit()
            flash("MPG report inputs saved successfully.", "success")
        return redirect(url_for(
            "workspace_mpg_report",
            from_date=from_date.isoformat(),
            to_date=to_date.isoformat(),
            district_id=district_id or "",
            project_id=project_id or "",
            vehicle_id=selected_vehicle_id or "",
        ))

    report_rows = []
    for idx, row_vehicle_id in enumerate(vehicle_ids, start=1):
        vehicle = vehicles_by_id.get(row_vehicle_id)
        if not vehicle:
            continue
        rows = entries_by_vehicle.get(row_vehicle_id) or []
        if not rows:
            continue

        latest_entry = rows[-1]
        same_start_date_rows = [r for r in rows if r.fueling_date == from_date]
        same_end_date_rows = [r for r in rows if r.fueling_date == to_date]
        first_row_for_prev = same_start_date_rows[0] if same_start_date_rows else rows[0]
        last_row_for_current = same_end_date_rows[-1] if same_end_date_rows else rows[-1]

        previous_reading = _to_dec(first_row_for_prev.previous_reading, None)
        if previous_reading is None:
            # Safety for legacy/imported rows: try earliest non-null previous reading
            # from the same start date bucket, then from full range rows.
            start_prev_values = [_to_dec(r.previous_reading, None) for r in same_start_date_rows]
            start_prev_values = [v for v in start_prev_values if v is not None]
            if start_prev_values:
                previous_reading = min(start_prev_values)
            else:
                all_prev_values = [_to_dec(r.previous_reading, None) for r in rows]
                all_prev_values = [v for v in all_prev_values if v is not None]
                if all_prev_values:
                    previous_reading = min(all_prev_values)
        current_reading = _to_dec(last_row_for_current.current_reading, None)
        km = (current_reading - previous_reading) if (previous_reading is not None and current_reading is not None) else None

        total_ltr = sum((_to_dec(r.liters, Decimal("0")) for r in rows), Decimal("0"))
        total_amount = sum((_to_dec(r.amount, Decimal("0")) for r in rows), Decimal("0"))
        avg_fuel_price = (total_amount / total_ltr) if total_ltr > 0 else None
        mpg = (km / total_ltr) if (km is not None and total_ltr > 0) else None

        target_mpg = _to_dec(vehicle.target_mpg, Decimal("0"))
        tank_capacity = _to_dec(vehicle.fuel_tank_capacity, Decimal("0"))

        fuel_deduction = None
        short_kms = None
        with_full_tank_next_fueling = None
        if target_mpg > 0 and km is not None and avg_fuel_price is not None:
            fuel_deduction = (total_ltr - (km / target_mpg)) * avg_fuel_price
        if target_mpg > 0 and km is not None:
            short_kms = (total_ltr * target_mpg) - km
        if target_mpg > 0 and current_reading is not None and short_kms is not None:
            with_full_tank_next_fueling = current_reading + short_kms + (tank_capacity * target_mpg)

        current_date_reading = task_close_reading_map.get(row_vehicle_id)
        saved = saved_inputs.get(row_vehicle_id)
        current_odoo_meter_reading = _to_dec(saved.current_odoo_meter_reading, None) if saved else None
        today_fuel = _to_dec(saved.today_fuel, None) if saved else None
        meter_base = current_odoo_meter_reading if current_odoo_meter_reading is not None else current_date_reading

        remaining_kms_from_fueling = (
            with_full_tank_next_fueling - meter_base
            if (with_full_tank_next_fueling is not None and meter_base is not None)
            else None
        )
        in_tank_current_ltr = (
            remaining_kms_from_fueling / target_mpg
            if (remaining_kms_from_fueling is not None and target_mpg > 0)
            else None
        )
        fueling_ltr_with_target = (
            tank_capacity - in_tank_current_ltr
            if (in_tank_current_ltr is not None and tank_capacity is not None)
            else None
        )
        fueling_amount = (
            fueling_ltr_with_target * avg_fuel_price
            if (fueling_ltr_with_target is not None and avg_fuel_price is not None)
            else None
        )
        balance_amount = (
            fueling_amount - today_fuel
            if (fueling_amount is not None and today_fuel is not None)
            else fueling_amount
        )

        report_rows.append({
            "sr_no": idx,
            "vehicle": vehicle,
            "entry_date": latest_entry.fueling_date,
            "slip_no": latest_entry.slip_no,
            "previous_reading": previous_reading,
            "current_reading": current_reading,
            "km": km,
            "avg_fuel_price": avg_fuel_price,
            "total_ltr": total_ltr,
            "mpg": mpg,
            "amount": total_amount,
            "fuel_deduction": fuel_deduction,
            "short_kms": short_kms,
            "with_full_tank_next_fueling": with_full_tank_next_fueling,
            "current_date_reading": current_date_reading,
            "current_odoo_meter_reading": current_odoo_meter_reading,
            "remaining_kms_from_fueling": remaining_kms_from_fueling,
            "in_tank_current_ltr": in_tank_current_ltr,
            "fueling_ltr_with_target": fueling_ltr_with_target,
            "fueling_amount": fueling_amount,
            "today_fuel": today_fuel,
            "balance_amount": balance_amount,
            "target_mpg": target_mpg,
            "tank_capacity": tank_capacity,
        })

    districts = District.query.order_by(District.name.asc()).all()
    projects = Project.query.order_by(Project.name.asc()).all()
    from vehicle_sort_utils import vehicle_order_by
    vehicles = Vehicle.query.order_by(*vehicle_order_by()).all()
    district_obj = next((d for d in districts if int(d.id) == int(district_id)), None) if district_id else None
    project_obj = next((p for p in projects if int(p.id) == int(project_id)), None) if project_id else None
    selected_district_name = district_obj.name if district_obj else "All Districts"
    selected_project_name = project_obj.name if project_obj else "All Projects"
    print_report_title = (
        f"{selected_district_name} ({selected_project_name}) "
        f"Fuel MPG SUMMARY(Date: {from_date.strftime('%d-%m-%Y')} To {to_date.strftime('%d-%m-%Y')})"
    )

    return render_template(
        "workspace/mpg_report.html",
        employee=emp,
        from_date=from_date,
        to_date=to_date,
        district_id=district_id,
        project_id=project_id,
        vehicle_id=selected_vehicle_id,
        districts=districts,
        projects=projects,
        vehicles=vehicles,
        rows=report_rows,
        print_report_title=print_report_title,
    )


def workspace_dashboard_financial_report(kind):
    guard, emp = _workspace_guard("workspace_dashboard")
    if guard:
        return guard

    report_kind = (kind or "").strip().lower()
    snapshot = _workspace_dashboard_financial_snapshot(emp.id)
    if report_kind == "bank":
        rows = snapshot["bank_rows"]
        total = snapshot["bank_total"]
        title = "Balance in Bank Details"
        subtitle = "HBL Bank, Easypaisa, JazzCash aur dusre bank/wallet accounts ka current balance."
        icon = "bi-bank"
        accent = "primary"
        total_label = "Net Bank Balance"
        csv_name = "Workspace_Bank_Balance_Details.csv"
    elif report_kind == "receivable":
        rows = snapshot["receivable_rows"]
        total = snapshot["receivable_total"]
        title = "Receivable from Parties & Drivers"
        subtitle = "Jin party/driver se payment leni hai un ka detail breakup."
        icon = "bi-arrow-down-circle"
        accent = "success"
        total_label = "Total Receivable"
        csv_name = "Workspace_Receivable_Details.csv"
    elif report_kind == "payable":
        rows = snapshot["payable_rows"]
        total = snapshot["payable_total"]
        title = "Payable to Parties & Drivers"
        subtitle = "Jin party/driver ko payment deni hai un ka detail breakup."
        icon = "bi-arrow-up-circle"
        accent = "danger"
        total_label = "Total Payable"
        csv_name = "Workspace_Payable_Details.csv"
    else:
        flash("Invalid report type.", "danger")
        return redirect(url_for("workspace_home"))

    return render_template(
        "workspace/dashboard_financial_report.html",
        employee=emp,
        report_kind=report_kind,
        rows=rows,
        total=total,
        title=title,
        subtitle=subtitle,
        icon=icon,
        accent=accent,
        total_label=total_label,
        csv_name=csv_name,
    )


def workspace_balance_sheet():
    guard, emp = _workspace_guard("workspace_reports")
    if guard:
        return guard

    as_of_date = parse_date(request.args.get("as_of_date")) if request.args.get("as_of_date") else pk_date()
    accounts = (
        WorkspaceAccount.query
        .filter_by(employee_id=emp.id, is_active=True)
        .order_by(WorkspaceAccount.account_type.asc(), WorkspaceAccount.code.asc(), WorkspaceAccount.id.asc())
        .all()
    )
    account_ids = [a.id for a in accounts]
    driver_ids = sorted({
        int(a.entity_id) for a in accounts
        if (a.entity_type or "").strip().lower() == "driver" and a.entity_id
    })
    drivers_by_id = {}
    if driver_ids:
        for drv in Driver.query.filter(Driver.id.in_(driver_ids)).all():
            drivers_by_id[int(drv.id)] = drv

    jnl_map = {}
    if account_ids:
        rows = (
            db.session.query(
                WorkspaceJournalEntryLine.account_id,
                db.func.coalesce(db.func.sum(WorkspaceJournalEntryLine.debit), 0),
                db.func.coalesce(db.func.sum(WorkspaceJournalEntryLine.credit), 0),
            )
            .join(WorkspaceJournalEntry, WorkspaceJournalEntry.id == WorkspaceJournalEntryLine.journal_entry_id)
            .filter(
                WorkspaceJournalEntry.employee_id == emp.id,
                WorkspaceJournalEntry.is_posted == True,
                WorkspaceJournalEntry.entry_date <= as_of_date,
                WorkspaceJournalEntryLine.account_id.in_(account_ids),
            )
            .group_by(WorkspaceJournalEntryLine.account_id)
            .all()
        )
        for r in rows:
            jnl_map[int(r[0])] = (Decimal(str(r[1] or 0)), Decimal(str(r[2] or 0)))

    grouped = {
        'Asset': [],
        'Liability': [],
        'Equity': [],
        'Revenue': [],
        'Expense': [],
    }
    totals = {
        'opening': Decimal('0'),
        'debit': Decimal('0'),
        'credit': Decimal('0'),
        'balance': Decimal('0'),
        'by_type': {k: Decimal('0') for k in grouped.keys()},
    }

    def _side(account_type, balance):
        if account_type in ('Asset', 'Expense'):
            return 'Dr' if balance >= 0 else 'Cr'
        return 'Cr' if balance >= 0 else 'Dr'

    def _account_display_name(acc):
        if (acc.entity_type or "").strip().lower() == "driver" and acc.entity_id:
            drv = drivers_by_id.get(int(acc.entity_id))
            if drv and getattr(drv, "vehicle", None) and getattr(drv.vehicle, "vehicle_no", None):
                return f"{acc.name} | Vehicle: {drv.vehicle.vehicle_no}"
        return acc.name

    for acc in accounts:
        opening = Decimal(str(acc.opening_balance or 0))
        debit, credit = jnl_map.get(acc.id, (Decimal('0'), Decimal('0')))
        if acc.account_type in ('Asset', 'Expense'):
            balance = opening + debit - credit
        else:
            balance = opening + credit - debit
        side = _side(acc.account_type, balance)
        is_zero = (
            abs(opening) < Decimal('0.0001')
            and abs(debit) < Decimal('0.0001')
            and abs(credit) < Decimal('0.0001')
            and abs(balance) < Decimal('0.0001')
        )
        row = {
            'account': acc,
            'opening': opening,
            'debit': debit,
            'credit': credit,
            'balance': balance,
            'side': side,
            'is_zero': is_zero,
            'display_name': _account_display_name(acc),
        }
        grouped.setdefault(acc.account_type or 'Asset', []).append(row)
        totals['opening'] += opening
        totals['debit'] += debit
        totals['credit'] += credit
        totals['balance'] += balance
        if acc.account_type in totals['by_type']:
            totals['by_type'][acc.account_type] += balance

    return render_template(
        "workspace/balance_sheet.html",
        employee=emp,
        as_of_date=as_of_date,
        grouped=grouped,
        totals=totals,
    )


def workspace_transfer_description_suggestions_api():
    guard, emp = _workspace_guard("workspace_transfer_add")
    if guard:
        return jsonify([])
    q = (request.args.get("q") or "").strip()
    query = WorkspaceFundTransfer.query.filter(
        WorkspaceFundTransfer.employee_id == emp.id,
        WorkspaceFundTransfer.description.isnot(None),
        WorkspaceFundTransfer.description != "",
    )
    if q:
        words = [w.strip() for w in q.split() if w.strip()]
        for w in words:
            query = query.filter(WorkspaceFundTransfer.description.ilike(f"%{w}%"))
    rows = query.order_by(WorkspaceFundTransfer.id.desc()).limit(200).all()
    out = []
    seen = set()
    for r in rows:
        d = (r.description or "").strip()
        if not d:
            continue
        key = d.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
        if len(out) >= 20:
            break
    return jsonify(out)


def _clean_slip_fingerprint_keywords(keywords, limit=40):
    if not isinstance(keywords, list):
        keywords = []
    clean_keywords = []
    seen_kw = set()
    for kw in keywords:
        s = str(kw or '').strip().upper()
        if len(s) < 3 or s in seen_kw:
            continue
        seen_kw.add(s)
        clean_keywords.append(s)
        if len(clean_keywords) >= limit:
            break
    return clean_keywords


def _sanitize_slip_ocr_recipe(raw):
    if not isinstance(raw, dict):
        return None
    variant = (raw.get('variant') or '').strip()
    if not variant:
        return None
    recipe = {'variant': variant[:80]}
    if raw.get('mode'):
        recipe['mode'] = str(raw.get('mode'))[:40]
    for num_key in ('scale', 'padPct', 'canvasMargin'):
        if raw.get(num_key) is not None:
            try:
                recipe[num_key] = float(raw.get(num_key))
            except (TypeError, ValueError):
                pass
    if raw.get('psm') is not None:
        recipe['psm'] = str(raw.get('psm'))[:4]
    for bool_key in ('noWhitelist', 'digitsOnly'):
        if raw.get(bool_key) is not None:
            recipe[bool_key] = bool(raw.get(bool_key))
    pad_asym = raw.get('padAsym')
    if isinstance(pad_asym, dict):
        cleaned = {}
        for side in ('left', 'right', 'top', 'bottom'):
            if pad_asym.get(side) is not None:
                try:
                    cleaned[side] = float(pad_asym.get(side))
                except (TypeError, ValueError):
                    pass
        if cleaned:
            recipe['padAsym'] = cleaned
    return recipe


def _coerce_slip_profile_field_map(raw_fields, required_all=False):
    allowed_keys = {'date', 'amount', 'reference_no'}
    field_map = {}
    for item in raw_fields or []:
        if not isinstance(item, dict):
            continue
        key = (item.get('field_key') or '').strip().lower()
        if key not in allowed_keys:
            continue
        try:
            entry = {
                'region_x': max(0.0, min(100.0, float(item.get('region_x', 0)))),
                'region_y': max(0.0, min(100.0, float(item.get('region_y', 0)))),
                'region_w': max(1.0, min(100.0, float(item.get('region_w', 1)))),
                'region_h': max(1.0, min(100.0, float(item.get('region_h', 1)))),
            }
            recipe = _sanitize_slip_ocr_recipe(item.get('ocr_recipe'))
            if recipe:
                entry['ocr_recipe'] = recipe
            field_map[key] = entry
        except (TypeError, ValueError):
            continue
    if required_all:
        missing = sorted(allowed_keys - set(field_map.keys()))
        if missing:
            return None, 'Mark all fields on slip: ' + ', '.join(missing)
    return field_map, None


def _active_slip_profiles_query():
    """Company-wide slip designs — shared across all employee workspaces."""
    return WorkspaceSlipProfile.query.filter_by(is_active=True).order_by(
        WorkspaceSlipProfile.id.asc(),
    )


def _get_slip_profile(pk, active_only=True):
    q = WorkspaceSlipProfile.query.filter_by(id=pk)
    if active_only:
        q = q.filter_by(is_active=True)
    return q.first()


def _validated_last_slip_profile_id(employee):
    pid = getattr(employee, 'last_slip_profile_id', None)
    if not pid:
        return None
    profile = _get_slip_profile(pid, active_only=True)
    return profile.id if profile else None


def _serialize_workspace_slip_profile(profile):
    try:
        keywords = json.loads(profile.fingerprint_keywords or '[]')
    except Exception:
        keywords = []
    if not isinstance(keywords, list):
        keywords = []
    fields = []
    for f in profile.fields or []:
        ocr_recipe = None
        if f.ocr_recipe_json:
            try:
                parsed = json.loads(f.ocr_recipe_json)
                if isinstance(parsed, dict):
                    ocr_recipe = _sanitize_slip_ocr_recipe(parsed)
            except Exception:
                ocr_recipe = None
        fields.append({
            'field_key': f.field_key,
            'region_x': float(f.region_x or 0),
            'region_y': float(f.region_y or 0),
            'region_w': float(f.region_w or 0),
            'region_h': float(f.region_h or 0),
            'ocr_recipe': ocr_recipe,
        })
    return {
        'id': profile.id,
        'name': profile.name or '',
        'fingerprint_keywords': keywords,
        'fields': fields,
    }


def _apply_slip_profile_field_rows(profile, field_map):
    for key, region in field_map.items():
        row = WorkspaceSlipProfileField.query.filter_by(profile_id=profile.id, field_key=key).first()
        if not row:
            row = WorkspaceSlipProfileField(profile_id=profile.id, field_key=key)
            db.session.add(row)
        row.region_x = region['region_x']
        row.region_y = region['region_y']
        row.region_w = region['region_w']
        row.region_h = region['region_h']
        recipe = region.get('ocr_recipe')
        row.ocr_recipe_json = json.dumps(recipe, ensure_ascii=False) if recipe else None


def workspace_slip_profiles_api():
    guard, emp = _workspace_guard("workspace_transfer_add")
    if guard:
        return jsonify({'ok': False, 'error': 'Unauthorized'}), 403

    if request.method == 'GET':
        rows = _active_slip_profiles_query().all()
        return jsonify({
            'ok': True,
            'profiles': [_serialize_workspace_slip_profile(p) for p in rows],
            'can_manage': _can_manage_slip_profiles(),
            'last_profile_id': _validated_last_slip_profile_id(emp),
        })

    if not _can_manage_slip_profiles():
        return jsonify({'ok': False, 'error': 'Slip design save ki permission nahi — Admin se Role Management mein permission mangwaein.'}), 403

    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'ok': False, 'error': 'Design name is required.'}), 400

    dup = WorkspaceSlipProfile.query.filter(
        WorkspaceSlipProfile.is_active.is_(True),
        db.func.lower(WorkspaceSlipProfile.name) == name.lower(),
    ).first()
    if dup:
        return jsonify({'ok': False, 'error': 'Is naam ka design pehle se maujood hai.'}), 400

    field_map, field_err = _coerce_slip_profile_field_map(data.get('fields') or [], required_all=True)
    if field_err:
        return jsonify({'ok': False, 'error': field_err}), 400

    clean_keywords = _clean_slip_fingerprint_keywords(data.get('fingerprint_keywords') or [])

    profile = WorkspaceSlipProfile(
        employee_id=None,
        name=name[:120],
        fingerprint_keywords=json.dumps(clean_keywords, ensure_ascii=False),
        is_active=True,
    )
    db.session.add(profile)
    db.session.flush()
    _apply_slip_profile_field_rows(profile, field_map)
    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(exc)}), 500
    return jsonify({'ok': True, 'profile': _serialize_workspace_slip_profile(profile)})


def workspace_slip_profile_update_api(pk):
    """Partial update — used when user corrects OCR-filled fields (region learning)."""
    guard, emp = _workspace_guard("workspace_transfer_add")
    if guard:
        return jsonify({'ok': False, 'error': 'Unauthorized'}), 403
    if not _can_manage_slip_profiles():
        return jsonify({'ok': False, 'error': 'Slip design edit ki permission nahi.'}), 403
    profile = _get_slip_profile(pk, active_only=True)
    if not profile:
        return jsonify({'ok': False, 'error': 'Not found'}), 404

    data = request.get_json(silent=True) or {}
    field_map, field_err = _coerce_slip_profile_field_map(data.get('fields') or [], required_all=False)
    if field_err:
        return jsonify({'ok': False, 'error': field_err}), 400
    if not field_map and not data.get('fingerprint_keywords'):
        return jsonify({'ok': False, 'error': 'Nothing to update.'}), 400

    if data.get('fingerprint_keywords') is not None:
        new_kw = _clean_slip_fingerprint_keywords(data.get('fingerprint_keywords') or [])
        if data.get('merge_fingerprint', True):
            try:
                existing = json.loads(profile.fingerprint_keywords or '[]')
            except Exception:
                existing = []
            if not isinstance(existing, list):
                existing = []
            merged = list(existing)
            seen = {str(k).upper() for k in merged}
            for kw in new_kw:
                if kw not in seen:
                    merged.append(kw)
                    seen.add(kw)
            profile.fingerprint_keywords = json.dumps(merged[:40], ensure_ascii=False)
        else:
            profile.fingerprint_keywords = json.dumps(new_kw, ensure_ascii=False)

    for key, region in field_map.items():
        _apply_slip_profile_field_rows(profile, {key: region})

    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(exc)}), 500
    return jsonify({'ok': True, 'profile': _serialize_workspace_slip_profile(profile)})


def workspace_slip_last_profile_api():
    guard, emp = _workspace_guard("workspace_transfer_add")
    if guard:
        return jsonify({'ok': False, 'error': 'Unauthorized'}), 403

    if request.method == 'GET':
        return jsonify({
            'ok': True,
            'profile_id': _validated_last_slip_profile_id(emp),
        })

    data = request.get_json(silent=True) or {}
    profile_id = data.get('profile_id')
    if profile_id in (None, '', 0, '0'):
        emp.last_slip_profile_id = None
    else:
        try:
            profile_id = int(profile_id)
        except (TypeError, ValueError):
            return jsonify({'ok': False, 'error': 'Invalid profile id.'}), 400
        profile = _get_slip_profile(profile_id, active_only=True)
        if not profile:
            return jsonify({'ok': False, 'error': 'Design not found.'}), 404
        emp.last_slip_profile_id = profile.id
    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(exc)}), 500
    return jsonify({'ok': True, 'profile_id': _validated_last_slip_profile_id(emp)})


def workspace_slip_profile_delete_api(pk):
    guard, emp = _workspace_guard("workspace_transfer_add")
    if guard:
        return jsonify({'ok': False, 'error': 'Unauthorized'}), 403
    if not _can_manage_slip_profiles():
        return jsonify({'ok': False, 'error': 'Slip design delete ki permission nahi.'}), 403
    profile = _get_slip_profile(pk, active_only=False)
    if not profile:
        return jsonify({'ok': False, 'error': 'Not found'}), 404
    profile.is_active = False
    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(exc)}), 500
    return jsonify({'ok': True})


def workspace_transfer_ref_check_api():
    guard, emp = _workspace_guard("workspace_transfer_add")
    if guard:
        guard, emp = _workspace_guard("workspace_transfer_edit")
    if guard:
        return jsonify({'ok': False, 'error': 'Unauthorized'}), 403
    ref = (request.args.get('reference_no') or '').strip()
    if not ref:
        return jsonify({'ok': True, 'exists': False})
    exclude_id = request.args.get('exclude_id', type=int)
    query = WorkspaceFundTransfer.query.filter_by(
        employee_id=emp.id,
        reference_no=ref,
    )
    if exclude_id:
        query = query.filter(WorkspaceFundTransfer.id != exclude_id)
    row = query.order_by(WorkspaceFundTransfer.id.desc()).first()
    if not row:
        return jsonify({'ok': True, 'exists': False})
    return jsonify({
        'ok': True,
        'exists': True,
        'transfer_number': row.transfer_number or str(row.id),
        'transfer_date': row.transfer_date.strftime('%d-%m-%Y') if row.transfer_date else None,
        'amount': float(row.amount or 0),
    })


def workspace_account_balance_api():
    guard, emp = _workspace_guard("workspace_ledger")
    if guard:
        return jsonify({'error': 'Unauthorized'}), 403
    account_id = request.args.get('account_id', type=int)
    party_id = request.args.get('party_id', type=int)
    if account_id:
        acct = WorkspaceAccount.query.filter_by(id=account_id, employee_id=emp.id, is_active=True).first()
        if not acct:
            return jsonify({'error': 'Not found'}), 404
    elif party_id:
        acct = WorkspaceAccount.query.filter_by(employee_id=emp.id, entity_type='party', entity_id=party_id, is_active=True).first()
        if not acct:
            return jsonify({'balance': None, 'balance_str': None, 'ledger_url': None}), 200
    else:
        return jsonify({'error': 'account_id or party_id required'}), 400
    bal = Decimal(str(acct.current_balance or 0))
    if acct.account_type in ('Asset', 'Expense'):
        side = 'Dr' if bal >= 0 else 'Cr'
    else:
        side = 'Cr' if bal >= 0 else 'Dr'
    return jsonify({
        'account_id': acct.id,
        'balance': float(bal),
        'balance_str': f'{abs(bal):,.2f} {side}',
        'ledger_url': f'/workspace/ledger?account_id={acct.id}',
    })


def _is_manual_workspace_journal(je):
    return (
        je.entry_type == 'Journal'
        and je.reference_type == 'Manual'
        and (je.category or '') != 'Fund Transfer Mirror'
    )


def _workspace_journal_lines_payload(je):
    lines = []
    for line in je.lines.order_by(WorkspaceJournalEntryLine.sort_order).all():
        lines.append({
            'account_id': line.account_id,
            'debit': float(line.debit or 0),
            'credit': float(line.credit or 0),
            'description': line.description or '',
        })
    return lines


def _load_journal_voucher_copy(emp, copy_from_id):
    if not copy_from_id:
        return None
    source = WorkspaceJournalEntry.query.filter_by(id=copy_from_id, employee_id=emp.id).first()
    if not source or not _is_manual_workspace_journal(source):
        return None
    return {
        'entry_date': date.today().strftime('%d-%m-%Y'),
        'description': source.description or '',
        'district_id': source.district_id,
        'project_id': source.project_id,
        'lines': _workspace_journal_lines_payload(source),
        'source_entry_number': source.entry_number,
        'source_id': source.id,
    }


def _manual_workspace_journal_filter(query):
    return query.filter(
        WorkspaceJournalEntry.entry_type == 'Journal',
        WorkspaceJournalEntry.reference_type == 'Manual',
        or_(
            WorkspaceJournalEntry.category.is_(None),
            WorkspaceJournalEntry.category != 'Fund Transfer Mirror',
        ),
    )


def workspace_journal_voucher_add():
    """Workspace Journal Voucher - Multi-line journal entry for employee workspace."""
    guard, emp = _workspace_guard("workspace_ledger")
    if guard:
        return guard

    from finance_utils import workspace_create_journal_entry
    from utils import parse_date

    # Get all active workspace accounts for this employee
    accounts = WorkspaceAccount.query.filter_by(
        employee_id=emp.id, is_active=True
    ).order_by(WorkspaceAccount.code).all()

    # Build driver-vehicle mapping for driver accounts
    driver_vehicle_map = {}
    driver_ids = [acc.entity_id for acc in accounts if acc.entity_type == 'driver' and acc.entity_id]
    if driver_ids:
        drivers = Driver.query.filter(Driver.id.in_(driver_ids)).all()
        for d in drivers:
            vehicle_no = d.vehicle.vehicle_no if d.vehicle else None
            driver_vehicle_map[d.id] = vehicle_no

    # Get districts and projects for dropdowns
    districts = District.query.order_by(District.name).all()
    projects = Project.query.order_by(Project.name).all()

    if request.method == "POST":
        try:
            entry_date_str = request.form.get("entry_date", "").strip()
            description = request.form.get("description", "").strip()
            district_id = request.form.get("district_id", "").strip()
            project_id = request.form.get("project_id", "").strip()
            district_id_int = int(district_id) if district_id else None
            project_id_int = int(project_id) if project_id else None

            if not entry_date_str:
                flash("Entry date is required.", "danger")
                return render_template(
                    "workspace/journal_voucher_form.html",
                    title="New Workspace Journal Voucher",
                    accounts=accounts,
                    districts=districts,
                    projects=projects,
                    entry_date=entry_date_str,
                    description=description,
                    district_id=district_id_int,
                    project_id=project_id_int,
                )

            entry_date = parse_date(entry_date_str)
            if not entry_date:
                flash("Invalid entry date format. Use dd-mm-yyyy.", "danger")
                return render_template(
                    "workspace/journal_voucher_form.html",
                    title="New Workspace Journal Voucher",
                    accounts=accounts,
                    districts=districts,
                    projects=projects,
                    entry_date=entry_date_str,
                    description=description,
                    district_id=district_id_int,
                    project_id=project_id_int,
                )

            # Parse journal lines from form (format: lines[0].account_id, lines[0].debit, etc.)
            lines = []
            i = 0
            while True:
                acct_id_key = f"lines[{i}].account_id"
                debit_key = f"lines[{i}].debit"
                credit_key = f"lines[{i}].credit"
                desc_key = f"lines[{i}].description"

                if acct_id_key not in request.form:
                    break

                acct_id_val = request.form.get(acct_id_key, "").strip()
                debit_val = request.form.get(debit_key, "0").strip()
                credit_val = request.form.get(credit_key, "0").strip()
                desc_val = request.form.get(desc_key, "").strip()

                acct_id = int(acct_id_val) if acct_id_val else 0
                debit = Decimal(debit_val or "0")
                credit = Decimal(credit_val or "0")

                if acct_id and (debit or credit):
                    lines.append({
                        "account_id": acct_id,
                        "debit": debit,
                        "credit": credit,
                        "description": desc_val,
                    })
                i += 1

            if not lines:
                flash("Please add at least one journal line.", "danger")
                return render_template(
                    "workspace/journal_voucher_form.html",
                    title="New Workspace Journal Voucher",
                    accounts=accounts,
                    districts=districts,
                    projects=projects,
                    entry_date=entry_date_str,
                    description=description,
                    district_id=district_id_int,
                    project_id=project_id_int,
                )

            # Validate total debits = total credits
            total_debit = sum(l["debit"] for l in lines)
            total_credit = sum(l["credit"] for l in lines)
            if abs(total_debit - total_credit) > Decimal("0.01"):
                flash("Total Debits must equal Total Credits.", "danger")
                return render_template(
                    "workspace/journal_voucher_form.html",
                    title="New Workspace Journal Voucher",
                    accounts=accounts,
                    districts=districts,
                    projects=projects,
                    entry_date=entry_date_str,
                    description=description,
                    district_id=district_id_int,
                    project_id=project_id_int,
                    lines=lines,
                )

            # Create the workspace journal entry
            je = workspace_create_journal_entry(
                employee_id=emp.id,
                entry_type="Journal",
                entry_date=entry_date,
                description=description,
                lines=lines,
                reference_type="Manual",
                created_by_user_id=session.get("user_id"),
                district_id=district_id_int,
                project_id=project_id_int,
            )
            db.session.commit()
            flash(f"Workspace Journal Voucher {je.entry_number} created successfully!", "success")
            return redirect(url_for("workspace_journal_vouchers_list"))

        except ValueError as e:
            db.session.rollback()
            flash(f"Validation error: {e}", "danger")
        except Exception as e:
            db.session.rollback()
            flash(f"Error creating journal voucher: {e}", "danger")

    copy_from = request.args.get('copy_from', type=int)
    copy_data = _load_journal_voucher_copy(emp, copy_from)
    if copy_from and not copy_data:
        flash('Could not duplicate that entry. Only your manual journal vouchers can be copied.', 'warning')

    template_kwargs = {
        'title': 'New Workspace Journal Voucher',
        'accounts': accounts,
        'driver_vehicle_map': driver_vehicle_map,
        'districts': districts,
        'projects': projects,
    }
    if copy_data:
        template_kwargs.update({
            'entry_date': copy_data['entry_date'],
            'description': copy_data['description'],
            'district_id': copy_data['district_id'],
            'project_id': copy_data['project_id'],
            'lines': copy_data['lines'],
            'copy_from_id': copy_data['source_id'],
            'copy_from_number': copy_data['source_entry_number'],
        })
    return render_template('workspace/journal_voucher_form.html', **template_kwargs)


def workspace_journal_voucher_duplicate(pk):
    """Open New JV form pre-filled from an existing manual journal voucher."""
    guard, emp = _workspace_guard("workspace_ledger")
    if guard:
        return guard

    je = WorkspaceJournalEntry.query.filter_by(id=pk, employee_id=emp.id).first_or_404()
    if not _is_manual_workspace_journal(je):
        flash('Only manual journal vouchers created from New JV can be duplicated.', 'warning')
        return redirect(url_for('workspace_journal_voucher_detail', pk=pk))

    flash(f'Duplicating {je.entry_number}. Update the date if needed, then save.', 'info')
    return redirect(url_for('workspace_journal_voucher_add', copy_from=pk))


def workspace_journal_vouchers_list():
    """Workspace Journal Vouchers List with filtering and pagination."""
    guard, emp = _workspace_guard("workspace_ledger")
    if guard:
        return guard

    from_date = None
    to_date = None
    per_page = int(request.args.get("per_page", request.form.get("per_page", 25)))
    page = int(request.args.get("page", 1))
    search = (request.args.get("search") or "").strip()
    entry_type = request.args.get("entry_type", "").strip()
    manual_only = request.args.get("manual_only", "").strip().lower() in ("1", "true", "yes")
    # Multi-select type filter (comma-separated)
    entry_type_filter = request.args.get("entry_type_filter", "").strip()
    selected_types = [t.strip() for t in entry_type_filter.split(",") if t.strip()] if entry_type_filter else []
    # District and Project filters
    district_id = request.args.get("district_id", "").strip()
    project_id = request.args.get("project_id", "").strip()
    district_id_int = int(district_id) if district_id else None
    project_id_int = int(project_id) if project_id else None

    def _parse_date(val):
        if not val:
            return None
        for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
            try:
                return datetime.strptime(val, fmt).date()
            except ValueError:
                continue
        return None

    fd = request.values.get("from_date", "")
    td = request.values.get("to_date", "")
    from_date = _parse_date(fd)
    to_date = _parse_date(td)

    # Default to today's date if no date range provided
    today = date.today()
    if not from_date and not to_date:
        from_date = today
        to_date = today

    # Valid entry types for Workspace Journal Vouchers
    valid_types = ["Journal", "Transfer", "Expense", "Opening", "MonthClose", "FuelOilMonthClose"]

    # Base query - this employee's journal entries
    if manual_only:
        query = WorkspaceJournalEntry.query.filter(
            WorkspaceJournalEntry.employee_id == emp.id,
        )
        query = _manual_workspace_journal_filter(query)
    elif selected_types:
        # Multi-select types from new filter
        # Check if FundTransferMirror is included
        has_mirror = "FundTransferMirror" in selected_types
        regular_types = [t for t in selected_types if t != "FundTransferMirror" and t in valid_types]

        if has_mirror and regular_types:
            # Both FundTransferMirror and regular types
            query = WorkspaceJournalEntry.query.filter(
                WorkspaceJournalEntry.employee_id == emp.id,
                or_(
                    and_(
                        WorkspaceJournalEntry.entry_type == "Journal",
                        WorkspaceJournalEntry.category == "Fund Transfer Mirror"
                    ),
                    WorkspaceJournalEntry.entry_type.in_(regular_types)
                )
            )
        elif has_mirror:
            # Only FundTransferMirror
            query = WorkspaceJournalEntry.query.filter(
                WorkspaceJournalEntry.employee_id == emp.id,
                WorkspaceJournalEntry.entry_type == "Journal",
                WorkspaceJournalEntry.category == "Fund Transfer Mirror"
            )
        elif regular_types:
            # Only regular types
            query = WorkspaceJournalEntry.query.filter(
                WorkspaceJournalEntry.employee_id == emp.id,
                WorkspaceJournalEntry.entry_type.in_(regular_types)
            )
        else:
            # Show all valid types
            query = WorkspaceJournalEntry.query.filter(
                WorkspaceJournalEntry.employee_id == emp.id,
                WorkspaceJournalEntry.entry_type.in_(valid_types)
            )
    elif entry_type == "FundTransferMirror":
        # Legacy single type filter - FundTransferMirror
        query = WorkspaceJournalEntry.query.filter(
            WorkspaceJournalEntry.employee_id == emp.id,
            WorkspaceJournalEntry.entry_type == "Journal",
            WorkspaceJournalEntry.category == "Fund Transfer Mirror"
        )
    elif entry_type and entry_type in valid_types:
        # Legacy single type filter
        query = WorkspaceJournalEntry.query.filter(
            WorkspaceJournalEntry.employee_id == emp.id,
            WorkspaceJournalEntry.entry_type == entry_type
        )
    else:
        # Show all valid types
        query = WorkspaceJournalEntry.query.filter(
            WorkspaceJournalEntry.employee_id == emp.id,
            WorkspaceJournalEntry.entry_type.in_(valid_types)
        )

    if from_date and to_date:
        query = query.filter(WorkspaceJournalEntry.entry_date.between(from_date, to_date))
    elif from_date:
        query = query.filter(WorkspaceJournalEntry.entry_date >= from_date)
    elif to_date:
        query = query.filter(WorkspaceJournalEntry.entry_date <= to_date)

    query = query.order_by(WorkspaceJournalEntry.entry_date.desc(), WorkspaceJournalEntry.id.desc())

    # Apply District filter
    if district_id_int:
        query = query.filter(WorkspaceJournalEntry.district_id == district_id_int)

    # Apply Project filter
    if project_id_int:
        query = query.filter(WorkspaceJournalEntry.project_id == project_id_int)

    if search:
        tokens = [t.lower() for t in search.split() if t]
        for tok in tokens:
            like = f"%{tok}%"
            query = query.filter(
                or_(
                    WorkspaceJournalEntry.entry_number.ilike(like),
                    WorkspaceJournalEntry.description.ilike(like),
                )
            )

    entries = query.paginate(page=page, per_page=per_page, error_out=False)
    items = entries.items
    entry_ids = [e.id for e in items]

    # Get districts and projects for filter dropdowns
    districts = District.query.order_by(District.name).all()
    projects = Project.query.order_by(Project.name).all()

    # Calculate totals per entry
    totals_map = {}
    line_counts = {}
    if entry_ids:
        amount_rows = db.session.query(
            WorkspaceJournalEntryLine.journal_entry_id,
            db.func.coalesce(db.func.sum(WorkspaceJournalEntryLine.debit), 0),
            db.func.count(WorkspaceJournalEntryLine.id),
        ).filter(
            WorkspaceJournalEntryLine.journal_entry_id.in_(entry_ids)
        ).group_by(WorkspaceJournalEntryLine.journal_entry_id).all()
        totals_map = {r[0]: Decimal(str(r[1] or 0)) for r in amount_rows}
        line_counts = {r[0]: r[2] for r in amount_rows}

    return render_template(
        "workspace/journal_vouchers_list.html",
        title="Workspace Journal Vouchers",
        entries=entries,
        from_date=from_date,
        to_date=to_date,
        per_page=per_page,
        search=search,
        entry_type=entry_type,
        selected_types=selected_types,
        district_id=district_id_int,
        project_id=project_id_int,
        districts=districts,
        projects=projects,
        totals_map=totals_map,
        line_counts=line_counts,
        manual_only=manual_only,
    )


def workspace_jv_backfill_district_project():
    """Temporary route to backfill district/project for old journal entries."""
    guard, emp = _workspace_guard("workspace_ledger")
    if guard:
        return guard
    
    updated = 0
    
    # 1. Update Expense entries from related tables
    # Fuel Expense
    entries = db.session.query(
        WorkspaceJournalEntry, FuelExpense
    ).join(
        FuelExpense, WorkspaceJournalEntry.reference_id == FuelExpense.id
    ).filter(
        WorkspaceJournalEntry.reference_type == 'FuelExpense',
        WorkspaceJournalEntry.district_id.is_(None)
    ).all()
    for wje, fe in entries:
        wje.district_id = fe.district_id
        wje.project_id = fe.project_id
        updated += 1
    
    # Oil Expense
    entries = db.session.query(
        WorkspaceJournalEntry, OilExpense
    ).join(
        OilExpense, WorkspaceJournalEntry.reference_id == OilExpense.id
    ).filter(
        WorkspaceJournalEntry.reference_type == 'OilExpense',
        WorkspaceJournalEntry.district_id.is_(None)
    ).all()
    for wje, oe in entries:
        wje.district_id = oe.district_id
        wje.project_id = oe.project_id
        updated += 1
    
    # Maintenance Expense
    entries = db.session.query(
        WorkspaceJournalEntry, MaintenanceExpense
    ).join(
        MaintenanceExpense, WorkspaceJournalEntry.reference_id == MaintenanceExpense.id
    ).filter(
        WorkspaceJournalEntry.reference_type == 'MaintenanceExpense',
        WorkspaceJournalEntry.district_id.is_(None)
    ).all()
    for wje, me in entries:
        wje.district_id = me.district_id
        wje.project_id = me.project_id
        updated += 1
    
    # Employee Expense
    entries = db.session.query(
        WorkspaceJournalEntry, EmployeeExpense
    ).join(
        EmployeeExpense, WorkspaceJournalEntry.reference_id == EmployeeExpense.id
    ).filter(
        WorkspaceJournalEntry.reference_type == 'EmployeeExpense',
        WorkspaceJournalEntry.district_id.is_(None)
    ).all()
    for wje, ee in entries:
        wje.district_id = ee.district_id
        wje.project_id = ee.project_id
        updated += 1
    
    # Opening Expenses
    entries = db.session.query(
        WorkspaceJournalEntry, WorkspaceOpeningExpense
    ).join(
        WorkspaceOpeningExpense, WorkspaceJournalEntry.reference_id == WorkspaceOpeningExpense.id
    ).filter(
        WorkspaceJournalEntry.entry_type == 'Opening',
        WorkspaceJournalEntry.district_id.is_(None)
    ).all()
    for wje, woe in entries:
        wje.district_id = woe.district_id
        wje.project_id = woe.project_id
        updated += 1
    
    # Fuel/Oil Opening
    entries = db.session.query(
        WorkspaceJournalEntry, WorkspaceFuelOilOpeningExpense
    ).join(
        WorkspaceFuelOilOpeningExpense, WorkspaceJournalEntry.reference_id == WorkspaceFuelOilOpeningExpense.id
    ).filter(
        WorkspaceJournalEntry.entry_type == 'Opening',
        WorkspaceJournalEntry.district_id.is_(None)
    ).all()
    for wje, wfooe in entries:
        wje.district_id = wfooe.district_id
        wje.project_id = wfooe.project_id
        updated += 1
    
    db.session.commit()
    flash(f'Backfill complete! Updated {updated} entries with District/Project data.', 'success')
    return redirect(url_for('workspace_journal_vouchers_list'))


def workspace_journal_voucher_detail(pk):
    """Workspace Journal Voucher Detail view."""
    guard, emp = _workspace_guard("workspace_ledger")
    if guard:
        return guard

    je = WorkspaceJournalEntry.query.filter_by(id=pk, employee_id=emp.id).first_or_404()

    # Get all lines with account details
    lines_query = db.session.query(
        WorkspaceJournalEntryLine,
        WorkspaceAccount
    ).join(
        WorkspaceAccount,
        WorkspaceJournalEntryLine.account_id == WorkspaceAccount.id
    ).filter(
        WorkspaceJournalEntryLine.journal_entry_id == je.id
    ).order_by(WorkspaceJournalEntryLine.sort_order).all()

    lines = []
    total_debit = Decimal("0")
    total_credit = Decimal("0")

    for line, account in lines_query:
        lines.append({
            'account_code': account.code,
            'account_name': account.name,
            'description': line.description,
            'debit': line.debit or 0,
            'credit': line.credit or 0,
        })
        total_debit += line.debit or 0
        total_credit += line.credit or 0

    return render_template(
        "workspace/journal_voucher_detail.html",
        title=f"JV {je.entry_number}",
        je=je,
        lines=lines,
        total_debit=total_debit,
        total_credit=total_credit,
    )


def workspace_journal_voucher_edit(pk):
    """Edit a manual Journal entry (only for entry_type='Journal')."""
    guard, emp = _workspace_guard("workspace_ledger")
    if guard:
        return guard

    je = WorkspaceJournalEntry.query.filter_by(id=pk, employee_id=emp.id).first_or_404()

    # Only allow editing manual Journal entries
    if je.entry_type != 'Journal':
        flash("Only manual Journal entries can be edited.", "warning")
        return redirect(url_for('workspace_journal_voucher_detail', pk=pk))

    from finance_utils import workspace_create_journal_entry
    from utils import parse_date

    # Get all active workspace accounts for this employee
    accounts = WorkspaceAccount.query.filter_by(
        employee_id=emp.id, is_active=True
    ).order_by(WorkspaceAccount.code).all()

    # Build driver-vehicle mapping for driver accounts
    driver_vehicle_map = {}
    driver_ids = [acc.entity_id for acc in accounts if acc.entity_type == 'driver' and acc.entity_id]
    if driver_ids:
        drivers = Driver.query.filter(Driver.id.in_(driver_ids)).all()
        for d in drivers:
            vehicle_no = d.vehicle.vehicle_no if d.vehicle else None
            driver_vehicle_map[d.id] = vehicle_no

    # Get districts and projects for dropdowns
    districts = District.query.order_by(District.name).all()
    projects = Project.query.order_by(Project.name).all()

    # Get existing lines
    existing_lines = db.session.query(
        WorkspaceJournalEntryLine,
        WorkspaceAccount
    ).join(
        WorkspaceAccount,
        WorkspaceJournalEntryLine.account_id == WorkspaceAccount.id
    ).filter(
        WorkspaceJournalEntryLine.journal_entry_id == je.id
    ).order_by(WorkspaceJournalEntryLine.sort_order).all()

    lines_data = []
    for line, account in existing_lines:
        lines_data.append({
            'account_id': line.account_id,
            'debit': float(line.debit or 0),
            'credit': float(line.credit or 0),
            'description': line.description or '',
        })

    if request.method == "POST":
        try:
            entry_date_str = request.form.get("entry_date", "").strip()
            description = request.form.get("description", "").strip()
            district_id = request.form.get("district_id", "").strip()
            project_id = request.form.get("project_id", "").strip()

            # Validate required fields
            if not entry_date_str:
                flash("Entry date is required.", "warning")
                return render_template(
                    "workspace/journal_voucher_form.html",
                    title="Edit Workspace Journal Voucher",
                    accounts=accounts,
                    driver_vehicle_map=driver_vehicle_map,
                    districts=districts,
                    projects=projects,
                    entry_date=entry_date_str,
                    description=description,
                    district_id=int(district_id) if district_id else None,
                    project_id=int(project_id) if project_id else None,
                    lines=lines_data,
                    edit_mode=True,
                    je=je,
                )

            # Parse date
            entry_date = parse_date(entry_date_str)
            if not entry_date:
                flash("Invalid entry date format. Use dd-mm-yyyy.", "warning")
                return render_template(
                    "workspace/journal_voucher_form.html",
                    title="Edit Workspace Journal Voucher",
                    accounts=accounts,
                    driver_vehicle_map=driver_vehicle_map,
                    districts=districts,
                    projects=projects,
                    entry_date=entry_date_str,
                    description=description,
                    district_id=int(district_id) if district_id else None,
                    project_id=int(project_id) if project_id else None,
                    lines=lines_data,
                    edit_mode=True,
                    je=je,
                )

            district_id_int = int(district_id) if district_id else None
            project_id_int = int(project_id) if project_id else None

            # Process lines
            lines = []
            line_idx = 0
            while True:
                account_id = request.form.get(f"lines[{line_idx}].account_id", "").strip()
                if not account_id:
                    break
                debit = request.form.get(f"lines[{line_idx}].debit", "0").strip()
                credit = request.form.get(f"lines[{line_idx}].credit", "0").strip()
                line_desc = request.form.get(f"lines[{line_idx}].description", "").strip()
                lines.append({
                    "account_id": int(account_id),
                    "debit": Decimal(debit) if debit else Decimal("0"),
                    "credit": Decimal(credit) if credit else Decimal("0"),
                    "description": line_desc,
                })
                line_idx += 1

            if not lines:
                flash("Please add at least one journal line.", "warning")
                return render_template(
                    "workspace/journal_voucher_form.html",
                    title="Edit Workspace Journal Voucher",
                    accounts=accounts,
                    driver_vehicle_map=driver_vehicle_map,
                    districts=districts,
                    projects=projects,
                    entry_date=entry_date_str,
                    description=description,
                    district_id=district_id_int,
                    project_id=project_id_int,
                    lines=lines,
                    edit_mode=True,
                    je=je,
                )

            # Validate total debits = total credits
            total_debit = sum(l["debit"] for l in lines)
            total_credit = sum(l["credit"] for l in lines)
            if abs(total_debit - total_credit) > Decimal("0.01"):
                flash("Total Debits must equal Total Credits.", "danger")
                return render_template(
                    "workspace/journal_voucher_form.html",
                    title="Edit Workspace Journal Voucher",
                    accounts=accounts,
                    driver_vehicle_map=driver_vehicle_map,
                    districts=districts,
                    projects=projects,
                    entry_date=entry_date_str,
                    description=description,
                    district_id=district_id_int,
                    project_id=project_id_int,
                    lines=lines,
                    edit_mode=True,
                    je=je,
                )

            # Delete old lines
            WorkspaceJournalEntryLine.query.filter_by(journal_entry_id=je.id).delete()

            # Update entry
            je.entry_date = entry_date
            je.description = description
            je.district_id = district_id_int
            je.project_id = project_id_int

            # Create new lines
            for idx, line in enumerate(lines):
                wjl = WorkspaceJournalEntryLine(
                    journal_entry_id=je.id,
                    account_id=line["account_id"],
                    debit=line["debit"],
                    credit=line["credit"],
                    description=line["description"],
                    sort_order=idx,
                )
                db.session.add(wjl)

            db.session.commit()
            flash(f"Journal Voucher {je.entry_number} updated successfully!", "success")
            return redirect(url_for("workspace_journal_voucher_detail", pk=pk))

        except ValueError as e:
            db.session.rollback()
            flash(f"Validation error: {e}", "danger")
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating journal voucher: {e}", "danger")

    return render_template(
        "workspace/journal_voucher_form.html",
        title=f"Edit JV {je.entry_number}",
        accounts=accounts,
        driver_vehicle_map=driver_vehicle_map,
        districts=districts,
        projects=projects,
        entry_date=je.entry_date.strftime('%d-%m-%Y') if je.entry_date else '',
        description=je.description or '',
        district_id=je.district_id,
        project_id=je.project_id,
        lines=lines_data,
        edit_mode=True,
        je=je,
    )


def workspace_journal_voucher_delete(pk):
    """Delete a manual Journal entry (only for entry_type='Journal')."""
    guard, emp = _workspace_guard("workspace_ledger")
    if guard:
        return guard

    je = WorkspaceJournalEntry.query.filter_by(id=pk, employee_id=emp.id).first_or_404()

    # Only allow deleting manual Journal entries
    if je.entry_type != 'Journal':
        flash("Only manual Journal entries can be deleted.", "warning")
        return redirect(url_for('workspace_journal_voucher_detail', pk=pk))

    try:
        entry_number = je.entry_number
        db.session.delete(je)
        db.session.commit()
        flash(f"Journal Voucher {entry_number} deleted successfully!", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting journal voucher: {e}", "danger")

    return redirect(url_for('workspace_journal_vouchers_list'))


def workspace_journal_vouchers_export():
    """Export all Journal Vouchers to CSV (no pagination)."""
    guard, emp = _workspace_guard("workspace_ledger")
    if guard:
        return guard

    # Get filter parameters
    from_date_str = request.args.get("from_date", "").strip()
    to_date_str = request.args.get("to_date", "").strip()
    search = request.args.get("search", "").strip()
    entry_type = request.args.get("entry_type", "").strip()
    manual_only = request.args.get("manual_only", "").strip().lower() in ("1", "true", "yes")
    district_id = request.args.get("district_id", "").strip()
    project_id = request.args.get("project_id", "").strip()

    # Build base query - NO PAGINATION, get all
    query = WorkspaceJournalEntry.query.filter(
        WorkspaceJournalEntry.employee_id == emp.id
    )
    if manual_only:
        query = _manual_workspace_journal_filter(query)

    # Apply filters
    if from_date_str:
        try:
            from_date = datetime.strptime(from_date_str, "%d-%m-%Y").date()
            query = query.filter(WorkspaceJournalEntry.entry_date >= from_date)
        except ValueError:
            pass

    if to_date_str:
        try:
            to_date = datetime.strptime(to_date_str, "%d-%m-%Y").date()
            query = query.filter(WorkspaceJournalEntry.entry_date <= to_date)
        except ValueError:
            pass

    if search:
        search_filter = or_(
            WorkspaceJournalEntry.entry_number.ilike(f"%{search}%"),
            WorkspaceJournalEntry.description.ilike(f"%{search}%"),
        )
        query = query.filter(search_filter)

    if entry_type:
        valid_types = ['Journal', 'Transfer', 'Expense', 'Opening', 'MonthClose', 'FuelOilMonthClose']
        if entry_type in valid_types:
            query = query.filter(WorkspaceJournalEntry.entry_type == entry_type)

    if district_id and district_id.isdigit():
        query = query.filter(WorkspaceJournalEntry.district_id == int(district_id))

    if project_id and project_id.isdigit():
        query = query.filter(WorkspaceJournalEntry.project_id == int(project_id))

    # Get all entries without pagination
    entries = query.order_by(WorkspaceJournalEntry.entry_date.desc(), WorkspaceJournalEntry.id.desc()).all()

    # Calculate totals for each entry
    totals_map = {}
    line_counts = {}
    entry_ids = [e.id for e in entries]

    if entry_ids:
        line_sums = db.session.query(
            WorkspaceJournalEntryLine.journal_entry_id,
            func.sum(WorkspaceJournalEntryLine.debit).label('total_debit'),
            func.count(WorkspaceJournalEntryLine.id).label('line_count')
        ).filter(
            WorkspaceJournalEntryLine.journal_entry_id.in_(entry_ids)
        ).group_by(WorkspaceJournalEntryLine.journal_entry_id).all()

        for je_id, total_debit, count in line_sums:
            totals_map[je_id] = float(total_debit or 0)
            line_counts[je_id] = count

    # Create CSV
    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow(['#', 'Entry Number', 'Date', 'Type', 'District', 'Project', 'Total Amount', 'Lines', 'Description'])

    # Data
    for idx, jv in enumerate(entries, 1):
        writer.writerow([
            idx,
            jv.entry_number,
            jv.entry_date.strftime('%d-%m-%Y') if jv.entry_date else '',
            jv.entry_type or 'Journal',
            jv.district.name if jv.district else '-',
            jv.project.name if jv.project else '-',
            f"{totals_map.get(jv.id, 0):,.2f}",
            line_counts.get(jv.id, 0),
            (jv.description or '')[:50]
        ])

    output.seek(0)

    from flask import Response
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={
            'Content-Disposition': 'attachment; filename=Workspace_Journal_Vouchers_All.csv',
            'Content-Type': 'text/csv; charset=utf-8'
        }
    )
