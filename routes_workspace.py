from datetime import datetime
from decimal import Decimal

from flask import flash, redirect, render_template, request, session, url_for, make_response, jsonify
from sqlalchemy import and_, or_
from sqlalchemy.orm import aliased

from models import (
    db, Employee, Driver, Party, Account, District, Project,
    EmployeeAssignment, FundTransferCategory,
    WorkspaceParty, WorkspaceProduct, WorkspaceAccount,
    WorkspaceExpense, WorkspaceOpeningExpense, WorkspaceFundTransfer, WorkspaceMonthClose,
)
from routes_finance import check_auth
from auth_utils import get_user_context
from finance_utils import (
    ensure_workspace_base_accounts,
    ensure_workspace_opening_expense_accounts,
    ensure_workspace_counterparty_account,
    reconcile_workspace_opening_expense_postings,
    workspace_post_expense,
    workspace_post_opening_expense,
    workspace_post_transfer,
    workspace_reverse_journal_entry,
    reverse_company_journal_entry,
    workspace_get_account_ledger,
    workspace_close_month,
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


def _workspace_has_closed_month_for_date(employee_id, target_date):
    if not employee_id or not target_date:
        return False
    return db.session.query(WorkspaceMonthClose.id).filter(
        WorkspaceMonthClose.employee_id == employee_id,
        WorkspaceMonthClose.status == "Closed",
        WorkspaceMonthClose.period_start <= target_date,
        WorkspaceMonthClose.period_end >= target_date,
    ).first() is not None


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
    created = 0
    for drv in q.order_by(Driver.name).all():
        exists = WorkspaceAccount.query.filter_by(
            employee_id=employee.id,
            entity_type="driver",
            entity_id=drv.id,
        ).first()
        if exists:
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
    total_expenses = Decimal(str(regular_expenses or 0)) + Decimal(str(opening_expenses or 0))
    total_transfers = sum((x.amount or 0) for x in WorkspaceFundTransfer.query.filter_by(employee_id=emp.id).all())

    # Live ledger position:
    # Employee wallet gets credited at month-close settlement (company-side entry).
    # Add closed batch totals back so dashboard does not double-reduce against Total Expenses.
    wallet_balance = Decimal("0")
    wallet_acct = Account.query.get(emp.wallet_account_id) if emp.wallet_account_id else None
    if wallet_acct:
        wallet_balance = Decimal(str(wallet_acct.current_balance or 0))
    closed_expense_total = Decimal(
        str(
            db.session.query(db.func.coalesce(db.func.sum(WorkspaceMonthClose.total_expense), 0))
            .filter(
                WorkspaceMonthClose.employee_id == emp.id,
                WorkspaceMonthClose.status == "Closed",
            )
            .scalar()
            or 0
        )
    )
    adjusted_ledger_end = wallet_balance + closed_expense_total
    # User convention: Net = Account Ledger End Balance - Total Expenses
    net_balance = adjusted_ledger_end - Decimal(str(total_expenses or 0))
    if net_balance > 0:
        net_balance_status = "Payable to Company"
    elif net_balance < 0:
        net_balance_status = "Receivable from Company"
    else:
        net_balance_status = "Settled"

    stats = {
        "parties": WorkspaceParty.query.filter_by(employee_id=emp.id, is_active=True).count(),
        "products": WorkspaceProduct.query.filter_by(employee_id=emp.id, is_active=True).count(),
        "expenses": total_expenses,
        "opening_expenses": opening_expenses,
        "transfers": total_transfers,
        "ledger_end_balance": adjusted_ledger_end,
        "net_balance": net_balance,
        "net_balance_status": net_balance_status,
        "month_close_adjustment": closed_expense_total,
        "open_closes": WorkspaceMonthClose.query.filter(
            WorkspaceMonthClose.employee_id == emp.id,
            WorkspaceMonthClose.status != "Closed",
        ).count(),
    }
    return render_template("workspace/dashboard.html", employee=emp, stats=stats, scope=scope)


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
    _ensure_workspace_driver_accounts(emp)
    parties = WorkspaceParty.query.filter_by(employee_id=emp.id).all()
    for p in parties:
        try:
            ensure_workspace_counterparty_account(emp.id, party_id=p.id)
        except Exception:
            pass
    try:
        reconcile_workspace_opening_expense_postings(emp.id)
    except Exception as e:
        print(f"Opening expense posting backfill skipped: {e}")
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


def workspace_opening_expenses_list():
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

    query = WorkspaceOpeningExpense.query.filter_by(employee_id=emp.id)
    if from_date:
        query = query.filter(WorkspaceOpeningExpense.opening_date >= from_date)
    if to_date:
        query = query.filter(WorkspaceOpeningExpense.opening_date <= to_date)
    if district_id:
        query = query.filter(WorkspaceOpeningExpense.district_id == district_id)
    if project_id:
        query = query.filter(WorkspaceOpeningExpense.project_id == project_id)
    if search:
        flt = _workspace_multi_word_filter(search, WorkspaceOpeningExpense.remarks)
        if flt is not None:
            query = query.filter(flt)

    total_amount = query.with_entities(
        db.func.coalesce(db.func.sum(WorkspaceOpeningExpense.total_expense), 0)
    ).scalar() or 0

    pagination = query.order_by(
        WorkspaceOpeningExpense.opening_date.desc(),
        WorkspaceOpeningExpense.id.desc(),
    ).paginate(page=page, per_page=per_page, error_out=False)

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
        districts=districts,
        projects=projects,
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
        if _workspace_has_closed_month_for_date(emp.id, opening_date):
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
        row.district_id = request.form.get("district_id", type=int) or None
        row.project_id = request.form.get("project_id", type=int) or None
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
    if _workspace_has_closed_month_for_date(emp.id, row.opening_date):
        flash("Cannot delete opening expense from a closed month. Reopen month-close batch first.", "danger")
        return redirect(url_for("workspace_opening_expenses_list"))
    if row.journal_entry_id:
        workspace_reverse_journal_entry(row.journal_entry_id)
    db.session.delete(row)
    db.session.commit()
    flash("Opening expense deleted.", "success")
    return redirect(url_for("workspace_opening_expenses_list"))


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
    for p in parties:
        try:
            ensure_workspace_counterparty_account(emp.id, party_id=p.id)
        except Exception:
            pass
    db.session.flush()

    accounts = WorkspaceAccount.query.filter_by(employee_id=emp.id, is_active=True).order_by(WorkspaceAccount.code).all()
    categories = FundTransferCategory.query.order_by(FundTransferCategory.name).all()

    if request.method == "POST":
        try:
            transfer_date = parse_date(request.form.get("transfer_date"))
            amount = Decimal(str((request.form.get("amount") or "").strip()))
        except Exception:
            flash("Date and amount are required.", "danger")
            return render_template("workspace/transfer_form.html", row=row, employee=emp, accounts=accounts, categories=categories, existing_attachment=(row.attachment if row else None))
        from_account_id = request.form.get("from_account_id", type=int)
        to_account_id = request.form.get("to_account_id", type=int)
        if not from_account_id:
            flash("From account is required.", "danger")
            return render_template("workspace/transfer_form.html", row=row, employee=emp, accounts=accounts, categories=categories, existing_attachment=(row.attachment if row else None))
        if not to_account_id:
            flash("To account is required.", "danger")
            return render_template("workspace/transfer_form.html", row=row, employee=emp, accounts=accounts, categories=categories, existing_attachment=(row.attachment if row else None))

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
    return render_template("workspace/transfer_form.html", row=row, employee=emp, accounts=accounts, categories=categories, existing_attachment=(row.attachment if row else None))


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
    account_id = request.args.get("account_id", type=int) or (accounts[0].id if accounts else None)
    from_date = parse_date(request.args.get("from_date"))
    to_date = parse_date(request.args.get("to_date"))
    category = (request.args.get("category") or "").strip() or None
    ledger = workspace_get_account_ledger(account_id, from_date=from_date, to_date=to_date, category=category) if account_id else None
    return render_template(
        "workspace/ledger.html",
        employee=emp,
        accounts=accounts,
        account_id=account_id,
        ledger=ledger,
        from_date=from_date,
        to_date=to_date,
        category=category,
    )


def workspace_month_close():
    guard, emp = _workspace_guard("workspace_month_close")
    if guard:
        return guard
    can_manage_month_close = _is_master_or_admin_user()
    accounts = Account.query.filter_by(is_active=True).order_by(Account.code).all()
    rows = WorkspaceMonthClose.query.filter_by(employee_id=emp.id).order_by(WorkspaceMonthClose.id.desc()).all()

    if request.method == "POST":
        period_start = parse_date(request.form.get("period_start"))
        period_end = parse_date(request.form.get("period_end"))
        company_account_id = request.form.get("company_account_id", type=int)
        notes = (request.form.get("notes") or "").strip()
        if not (period_start and period_end):
            flash("Period start/end are required.", "danger")
            return render_template(
                "workspace/month_close.html",
                employee=emp,
                rows=rows,
                accounts=accounts,
                can_manage_month_close=can_manage_month_close,
            )
        try:
            close_row = workspace_close_month(
                employee_id=emp.id,
                period_start=period_start,
                period_end=period_end,
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
        can_manage_month_close=can_manage_month_close,
    )


def workspace_month_close_reverse(pk):
    guard, emp = _workspace_guard("workspace_month_close")
    if guard:
        return guard
    if not _is_master_or_admin_user():
        flash("Only admin/master can reopen a month close batch.", "danger")
        return redirect(url_for("workspace_month_close"))

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
    return redirect(url_for("workspace_month_close"))


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
