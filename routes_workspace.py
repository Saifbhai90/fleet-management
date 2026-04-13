from datetime import datetime, date, timedelta
from calendar import monthrange
from decimal import Decimal, InvalidOperation

from flask import flash, redirect, render_template, request, session, url_for, make_response, jsonify
from sqlalchemy import and_, or_, cast, String
from sqlalchemy.orm import aliased

from models import (
    db, Employee, Driver, Party, Account, District, Project, Vehicle,
    VehicleDailyTask,
    JournalEntry, JournalEntryLine,
    EmployeeAssignment, FundTransfer, FundTransferCategory,
    WorkspaceParty, WorkspaceProduct, WorkspaceAccount,
    WorkspaceExpense, WorkspaceOpeningExpense, WorkspaceFuelOilOpeningExpense, WorkspaceFundTransfer, WorkspaceJournalEntry, WorkspaceJournalEntryLine, WorkspaceMonthClose, WorkspaceFuelOilMonthClose,
    WorkspaceMpgReportInput,
    FuelExpense, OilExpense, MaintenanceExpense,
)
from routes_finance import check_auth
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


def _workspace_multi_word_filter(search_text, *columns):
    words = [w.strip() for w in (search_text or "").split() if w.strip()]
    if not words:
        return None
    and_parts = []
    for word in words:
        pattern = f"%{word}%"
        and_parts.append(or_(*[col.ilike(pattern) for col in columns]))
    return and_(*and_parts)


def _get_workspace_employee():
    emp_id = session.get("workspace_employee_id")
    if not emp_id:
        return None
    return Employee.query.get(emp_id)


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


def _is_master_or_admin_user():
    user_id = session.get("user_id")
    if not user_id:
        return False
    ctx = get_user_context(user_id)
    return bool(ctx.get("is_master_or_admin"))


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

    # Opening expenses (always scoped by district/project).
    for row in WorkspaceOpeningExpense.query.filter(
        WorkspaceOpeningExpense.employee_id == employee_id,
        WorkspaceOpeningExpense.month_close_id.is_(None),
        WorkspaceOpeningExpense.total_expense > 0,
    ).all():
        if not row.opening_date or not row.district_id or not row.project_id:
            continue
        y, m, sday, eday = _spell_key(row.opening_date)
        k = (row.district_id, row.project_id, y, m, sday, eday)
        bucket[k] = bucket.get(k, Decimal("0")) + Decimal(str(row.total_expense or 0))

    # Regular workspace expenses (if scoped columns exist in model).
    has_dist = hasattr(WorkspaceExpense, "district_id")
    has_proj = hasattr(WorkspaceExpense, "project_id")
    if has_dist and has_proj:
        for row in WorkspaceExpense.query.filter(
            WorkspaceExpense.employee_id == employee_id,
            WorkspaceExpense.month_close_id.is_(None),
            WorkspaceExpense.amount > 0,
        ).all():
            district_id = getattr(row, "district_id", None)
            project_id = getattr(row, "project_id", None)
            exp_date = getattr(row, "expense_date", None)
            if not exp_date or not district_id or not project_id:
                continue
            y, m, sday, eday = _spell_key(exp_date)
            k = (district_id, project_id, y, m, sday, eday)
            bucket[k] = bucket.get(k, Decimal("0")) + Decimal(str(row.amount or 0))

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
    regular_expenses = sum((x.amount or 0) for x in WorkspaceExpense.query.filter_by(employee_id=emp.id).all())
    opening_expenses = sum((x.total_expense or 0) for x in WorkspaceOpeningExpense.query.filter_by(employee_id=emp.id).all())
    fuel_oil_openings = sum((x.total_amount or 0) for x in WorkspaceFuelOilOpeningExpense.query.filter_by(employee_id=emp.id).all())
    total_expenses = Decimal(str(regular_expenses or 0)) + Decimal(str(opening_expenses or 0)) + Decimal(str(fuel_oil_openings or 0))
    total_transfers = sum((x.amount or 0) for x in WorkspaceFundTransfer.query.filter_by(employee_id=emp.id).all())

    # Live ledger position:
    # User convention for dashboard card:
    # last ledger balance + total credit posted under close categories.
    wallet_balance = Decimal("0")
    close_credit_total = Decimal("0")
    wallet_acct = Account.query.get(emp.wallet_account_id) if emp.wallet_account_id else None
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
    emp = Employee.query.get(emp_id) if emp_id else None
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


def workspace_party_form(pk=None):
    guard, emp = _workspace_guard("workspace_party_edit" if pk else "workspace_party_add")
    if guard:
        return guard
    row = WorkspaceParty.query.filter_by(employee_id=emp.id, id=pk).first() if pk else None
    if pk and not row:
        flash("Party not found for selected workspace employee.", "danger")
        return redirect(url_for("workspace_parties_list"))

    districts = District.query.order_by(District.name).all()

    next_url = (request.args.get("next") or request.form.get("next") or "").strip()
    default_type = (request.args.get("type") or "").strip()

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("Party name is required.", "danger")
            return render_template("workspace/party_form.html", row=row, employee=emp, districts=districts, next_url=next_url, default_type=default_type)
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
        except Exception as e:
            db.session.rollback()
            print(f"workspace_party_form save error: {e}")
            flash("Unable to save workspace party right now. Please try again.", "danger")
            return render_template("workspace/party_form.html", row=row, employee=emp, districts=districts, next_url=next_url, default_type=default_type)
        flash("Workspace party saved.", "success")
        if next_url:
            return redirect(next_url)
        return redirect(url_for("workspace_parties_list"))
    return render_template("workspace/party_form.html", row=row, employee=emp, districts=districts, next_url=next_url, default_type=default_type)


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


def workspace_product_form(pk=None):
    guard, emp = _workspace_guard("workspace_product_edit" if pk else "workspace_product_add")
    if guard:
        return guard
    row = WorkspaceProduct.query.filter_by(employee_id=emp.id, id=pk).first() if pk else None
    if pk and not row:
        flash("Product not found for selected workspace employee.", "danger")
        return redirect(url_for("workspace_products_list"))

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
            return render_template("workspace/product_form.html", row=row, employee=emp, unit_choices=unit_choices)
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
        db.session.commit()
        flash("Workspace product saved.", "success")
        return redirect(url_for("workspace_products_list"))
    return render_template("workspace/product_form.html", row=row, employee=emp, unit_choices=unit_choices)


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
        district = District.query.get(request.form.get("district_id", type=int) or 0)
        project = Project.query.get(request.form.get("project_id", type=int) or 0)
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
    per_page = request.args.get("per_page", 25, type=int) or 25
    if per_page not in (25, 50, 100, 200):
        per_page = 25
    search = (request.args.get("search") or "").strip()
    from_date = parse_date(request.args.get("from_date"))
    to_date = parse_date(request.args.get("to_date"))

    from_acct = aliased(WorkspaceAccount)
    to_acct = aliased(WorkspaceAccount)
    query = (
        db.session.query(WorkspaceFundTransfer)
        .outerjoin(from_acct, WorkspaceFundTransfer.from_account_id == from_acct.id)
        .outerjoin(to_acct, WorkspaceFundTransfer.to_account_id == to_acct.id)
        .filter(WorkspaceFundTransfer.employee_id == emp.id)
    )

    if from_date:
        query = query.filter(WorkspaceFundTransfer.transfer_date >= from_date)
    if to_date:
        query = query.filter(WorkspaceFundTransfer.transfer_date <= to_date)
    if search:
        words = [w.strip() for w in search.split() if w.strip()]
        for w in words:
            like = f"%{w}%"
            query = query.filter(
                or_(
                    WorkspaceFundTransfer.transfer_number.ilike(like),
                    WorkspaceFundTransfer.category.ilike(like),
                    WorkspaceFundTransfer.payment_mode.ilike(like),
                    WorkspaceFundTransfer.reference_no.ilike(like),
                    WorkspaceFundTransfer.description.ilike(like),
                    from_acct.code.ilike(like),
                    from_acct.name.ilike(like),
                    to_acct.code.ilike(like),
                    to_acct.name.ilike(like),
                )
            )

    total_amount = (
        query.with_entities(db.func.coalesce(db.func.sum(WorkspaceFundTransfer.amount), 0)).scalar() or 0
    )
    pagination = query.order_by(
        WorkspaceFundTransfer.transfer_date.desc(),
        WorkspaceFundTransfer.id.desc(),
    ).paginate(page=page, per_page=per_page, error_out=False)

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
            v = Vehicle.query.get(drv.vehicle_id)
            if v and v.vehicle_no:
                return v.vehicle_no
        v = Vehicle.query.filter_by(driver_id=drv.id).order_by(Vehicle.id.desc()).first()
        return v.vehicle_no if v and v.vehicle_no else None

    account_display_map = {}
    for a in accounts:
        base = f"{a.code} - {a.name}"
        if (a.entity_type or '').strip().lower() == 'driver' and a.entity_id:
            drv = drivers_by_id.get(int(a.entity_id))
            if drv:
                v_no = _driver_vehicle_no(drv)
                if v_no:
                    base = f"{base} | Vehicle: {v_no}"
        account_display_map[a.id] = base

    if request.method == "POST":
        try:
            transfer_date = parse_date(request.form.get("transfer_date"))
            amount = Decimal(str((request.form.get("amount") or "").strip()))
        except Exception:
            flash("Date and amount are required.", "danger")
            return render_template("workspace/transfer_form.html", row=row, employee=emp, accounts=accounts, account_display_map=account_display_map, categories=categories, existing_attachment=(row.attachment if row else None))
        from_account_id = request.form.get("from_account_id", type=int)
        to_account_id = request.form.get("to_account_id", type=int)
        if not from_account_id:
            flash("From account is required.", "danger")
            return render_template("workspace/transfer_form.html", row=row, employee=emp, accounts=accounts, account_display_map=account_display_map, categories=categories, existing_attachment=(row.attachment if row else None))
        if not to_account_id:
            flash("To account is required.", "danger")
            return render_template("workspace/transfer_form.html", row=row, employee=emp, accounts=accounts, account_display_map=account_display_map, categories=categories, existing_attachment=(row.attachment if row else None))

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
        return redirect(url_for("workspace_fund_transfers_list"))
    return render_template("workspace/transfer_form.html", row=row, employee=emp, accounts=accounts, account_display_map=account_display_map, categories=categories, existing_attachment=(row.attachment if row else None))


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
            v = Vehicle.query.get(drv.vehicle_id)
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
        acct = Account.query.get(account_id)
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
        district = District.query.get(district_id) if district_id else None
        project = Project.query.get(project_id) if project_id else None
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
    expenses_by_type = {}
    for r in WorkspaceExpense.query.filter_by(employee_id=emp.id).all():
        key = r.expense_type or "Other"
        expenses_by_type[key] = expenses_by_type.get(key, Decimal("0")) + Decimal(str(r.amount or 0))
    transfer_total = sum((Decimal(str(r.amount or 0)) for r in WorkspaceFundTransfer.query.filter_by(employee_id=emp.id).all()), Decimal("0"))
    month_closes = WorkspaceMonthClose.query.filter_by(employee_id=emp.id).order_by(WorkspaceMonthClose.id.desc()).limit(12).all()
    return render_template(
        "workspace/reports.html",
        employee=emp,
        expenses_by_type=expenses_by_type,
        transfer_total=transfer_total,
        month_closes=month_closes,
    )


def workspace_mpg_report():
    guard, emp = _workspace_guard("workspace_reports")
    if guard:
        return guard

    today = pk_date()
    default_from_date = today - timedelta(days=30)
    from_date = parse_date(request.values.get("from_date")) or default_from_date
    to_date = parse_date(request.values.get("to_date")) or today
    district_id = request.values.get("district_id", type=int) or 0
    project_id = request.values.get("project_id", type=int) or 0
    vehicle_id = request.values.get("vehicle_id", type=int) or 0
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
    if vehicle_id:
        fuel_q = fuel_q.filter(FuelExpense.vehicle_id == vehicle_id)

    fuel_rows = (
        fuel_q
        .order_by(FuelExpense.vehicle_id.asc(), FuelExpense.fueling_date.asc(), FuelExpense.id.asc())
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
        for vehicle_id in vehicle_ids:
            current_meter, current_meter_invalid = _parse_decimal_input(request.form.get(f"current_odoo_meter_{vehicle_id}"))
            today_fuel, today_fuel_invalid = _parse_decimal_input(request.form.get(f"today_fuel_{vehicle_id}"))
            if current_meter_invalid or today_fuel_invalid:
                has_invalid = True
                continue

            existing = saved_inputs.get(vehicle_id)
            if current_meter is None and today_fuel is None:
                if existing:
                    db.session.delete(existing)
                continue

            if not existing:
                existing = WorkspaceMpgReportInput(
                    employee_id=emp.id,
                    vehicle_id=vehicle_id,
                    from_date=from_date,
                    to_date=to_date,
                    created_by_user_id=session.get("user_id"),
                )
                db.session.add(existing)
                saved_inputs[vehicle_id] = existing

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
            vehicle_id=vehicle_id or "",
        ))

    report_rows = []
    for idx, vehicle_id in enumerate(vehicle_ids, start=1):
        vehicle = vehicles_by_id.get(vehicle_id)
        if not vehicle:
            continue
        rows = entries_by_vehicle.get(vehicle_id) or []
        if not rows:
            continue

        latest_entry = rows[-1]
        same_start_date_rows = [r for r in rows if r.fueling_date == from_date]
        same_end_date_rows = [r for r in rows if r.fueling_date == to_date]
        first_row_for_prev = same_start_date_rows[0] if same_start_date_rows else rows[0]
        last_row_for_current = same_end_date_rows[-1] if same_end_date_rows else rows[-1]

        previous_reading = _to_dec(first_row_for_prev.previous_reading, None)
        current_reading = _to_dec(last_row_for_current.current_reading, None)
        km = (current_reading - previous_reading) if (previous_reading is not None and current_reading is not None) else None

        price_values = [_to_dec(r.fuel_price, None) for r in rows if r.fuel_price is not None]
        avg_fuel_price = (sum(price_values, Decimal("0")) / Decimal(len(price_values))) if price_values else None
        total_ltr = sum((_to_dec(r.liters, Decimal("0")) for r in rows), Decimal("0"))
        total_amount = sum((_to_dec(r.amount, Decimal("0")) for r in rows), Decimal("0"))
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

        current_date_reading = task_close_reading_map.get(vehicle_id)
        saved = saved_inputs.get(vehicle_id)
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

    return render_template(
        "workspace/mpg_report.html",
        employee=emp,
        from_date=from_date,
        to_date=to_date,
        district_id=district_id,
        project_id=project_id,
        vehicle_id=vehicle_id,
        districts=District.query.order_by(District.name.asc()).all(),
        projects=Project.query.order_by(Project.name.asc()).all(),
        vehicles=Vehicle.query.order_by(Vehicle.vehicle_no.asc()).all(),
        rows=report_rows,
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
