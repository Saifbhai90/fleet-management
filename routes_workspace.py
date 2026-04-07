from datetime import datetime
from decimal import Decimal

from flask import flash, redirect, render_template, request, session, url_for

from models import (
    db, Employee, Driver, Party, Account,
    WorkspaceParty, WorkspaceProduct, WorkspaceAccount,
    WorkspaceExpense, WorkspaceFundTransfer, WorkspaceMonthClose,
)
from routes_finance import check_auth
from auth_utils import get_user_context
from finance_utils import (
    ensure_workspace_base_accounts,
    ensure_workspace_counterparty_account,
    workspace_post_expense,
    workspace_post_transfer,
    workspace_reverse_journal_entry,
    workspace_get_account_ledger,
    workspace_close_month,
)
from utils import pk_date, parse_date


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


def _list_employees_for_workspace():
    return Employee.query.filter_by(status="Active").order_by(Employee.name).all()


def workspace_dashboard():
    auth = check_auth("workspace_dashboard")
    if auth:
        return auth
    employees = _list_employees_for_workspace()
    emp = _get_workspace_employee()
    stats = {
        "parties": 0,
        "products": 0,
        "expenses": Decimal("0"),
        "transfers": Decimal("0"),
        "open_closes": 0,
    }
    if emp:
        stats["parties"] = WorkspaceParty.query.filter_by(employee_id=emp.id, is_active=True).count()
        stats["products"] = WorkspaceProduct.query.filter_by(employee_id=emp.id, is_active=True).count()
        stats["expenses"] = sum(
            (x.amount or 0) for x in WorkspaceExpense.query.filter_by(employee_id=emp.id).all()
        )
        stats["transfers"] = sum(
            (x.amount or 0) for x in WorkspaceFundTransfer.query.filter_by(employee_id=emp.id).all()
        )
        stats["open_closes"] = WorkspaceMonthClose.query.filter(
            WorkspaceMonthClose.employee_id == emp.id,
            WorkspaceMonthClose.status != "Closed",
        ).count()
    return render_template("workspace/dashboard.html", employees=employees, selected_employee=emp, stats=stats)


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
    return redirect(url_for("workspace_dashboard"))


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
    rows = WorkspaceParty.query.filter_by(employee_id=emp.id).order_by(WorkspaceParty.name).all()
    return render_template("workspace/parties_list.html", rows=rows, employee=emp)


def workspace_party_form(pk=None):
    guard, emp = _workspace_guard("workspace_party_edit" if pk else "workspace_party_add")
    if guard:
        return guard
    row = WorkspaceParty.query.filter_by(employee_id=emp.id, id=pk).first() if pk else None
    if pk and not row:
        flash("Party not found for selected workspace employee.", "danger")
        return redirect(url_for("workspace_parties_list"))

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("Party name is required.", "danger")
            return render_template("workspace/party_form.html", row=row, employee=emp)
        if not row:
            row = WorkspaceParty(employee_id=emp.id)
            db.session.add(row)
        row.name = name
        row.party_type = (request.form.get("party_type") or "").strip() or None
        row.phone = (request.form.get("phone") or "").strip() or None
        row.address = (request.form.get("address") or "").strip() or None
        row.is_active = request.form.get("is_active") == "1"
        row.created_by_user_id = session.get("user_id")
        db.session.commit()
        flash("Workspace party saved.", "success")
        return redirect(url_for("workspace_parties_list"))
    return render_template("workspace/party_form.html", row=row, employee=emp)


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
    rows = WorkspaceProduct.query.filter_by(employee_id=emp.id).order_by(WorkspaceProduct.name).all()
    return render_template("workspace/products_list.html", rows=rows, employee=emp)


def workspace_product_form(pk=None):
    guard, emp = _workspace_guard("workspace_product_edit" if pk else "workspace_product_add")
    if guard:
        return guard
    row = WorkspaceProduct.query.filter_by(employee_id=emp.id, id=pk).first() if pk else None
    if pk and not row:
        flash("Product not found for selected workspace employee.", "danger")
        return redirect(url_for("workspace_products_list"))

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("Product name is required.", "danger")
            return render_template("workspace/product_form.html", row=row, employee=emp)
        if not row:
            row = WorkspaceProduct(employee_id=emp.id)
            db.session.add(row)
        row.name = name
        row.unit = (request.form.get("unit") or "").strip() or None
        row.used_in_forms = (request.form.get("used_in_forms") or "").strip() or None
        try:
            row.default_price = Decimal(str((request.form.get("default_price") or "0").strip() or "0"))
        except Exception:
            row.default_price = Decimal("0")
        row.is_active = request.form.get("is_active") == "1"
        row.created_by_user_id = session.get("user_id")
        db.session.commit()
        flash("Workspace product saved.", "success")
        return redirect(url_for("workspace_products_list"))
    return render_template("workspace/product_form.html", row=row, employee=emp)


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
    db.session.commit()
    rows = WorkspaceAccount.query.filter_by(employee_id=emp.id).order_by(WorkspaceAccount.code).all()
    return render_template("workspace/accounts_list.html", rows=rows, employee=emp)


def workspace_account_form(pk=None):
    guard, emp = _workspace_guard("workspace_account_edit" if pk else "workspace_account_add")
    if guard:
        return guard
    ensure_workspace_base_accounts(emp.id)
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


def workspace_fund_transfers_list():
    guard, emp = _workspace_guard("workspace_transfer_list")
    if guard:
        return guard
    rows = WorkspaceFundTransfer.query.filter_by(employee_id=emp.id).order_by(
        WorkspaceFundTransfer.transfer_date.desc(), WorkspaceFundTransfer.id.desc()
    ).all()
    total_amount = sum((r.amount or 0) for r in rows)
    return render_template("workspace/transfers_list.html", rows=rows, employee=emp, total_amount=total_amount)


def workspace_fund_transfer_form(pk=None):
    guard, emp = _workspace_guard("workspace_transfer_edit" if pk else "workspace_transfer_add")
    if guard:
        return guard
    ensure_workspace_base_accounts(emp.id)
    row = WorkspaceFundTransfer.query.filter_by(employee_id=emp.id, id=pk).first() if pk else None
    if pk and not row:
        flash("Workspace transfer not found.", "danger")
        return redirect(url_for("workspace_fund_transfers_list"))

    accounts = WorkspaceAccount.query.filter_by(employee_id=emp.id, is_active=True).order_by(WorkspaceAccount.code).all()
    parties = WorkspaceParty.query.filter_by(employee_id=emp.id, is_active=True).order_by(WorkspaceParty.name).all()
    drivers = Driver.query.filter_by(status="Active").order_by(Driver.name).all()

    if request.method == "POST":
        try:
            transfer_date = parse_date(request.form.get("transfer_date"))
            amount = Decimal(str((request.form.get("amount") or "").strip()))
        except Exception:
            flash("Date and amount are required.", "danger")
            return render_template("workspace/transfer_form.html", row=row, employee=emp, accounts=accounts, parties=parties, drivers=drivers)
        from_account_id = request.form.get("from_account_id", type=int)
        to_account_id = request.form.get("to_account_id", type=int)
        if not from_account_id:
            flash("From account is required.", "danger")
            return render_template("workspace/transfer_form.html", row=row, employee=emp, accounts=accounts, parties=parties, drivers=drivers)
        to_party_id = request.form.get("to_workspace_party_id", type=int) or None
        to_driver_id = request.form.get("to_driver_id", type=int) or None
        if not to_account_id:
            if to_party_id:
                to_account_id = ensure_workspace_counterparty_account(emp.id, party_id=to_party_id).id
            elif to_driver_id:
                to_account_id = ensure_workspace_counterparty_account(emp.id, driver_id=to_driver_id).id
        if not to_account_id:
            flash("Select target account or target party/driver.", "danger")
            return render_template("workspace/transfer_form.html", row=row, employee=emp, accounts=accounts, parties=parties, drivers=drivers)

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
        row.transfer_date = transfer_date or pk_date()
        row.from_account_id = from_account_id
        row.to_account_id = to_account_id
        row.to_workspace_party_id = to_party_id
        row.to_driver_id = to_driver_id
        row.amount = amount
        row.payment_mode = (request.form.get("payment_mode") or "Cash").strip()
        row.reference_no = (request.form.get("reference_no") or "").strip() or None
        row.description = (request.form.get("description") or "").strip() or None
        row.category = (request.form.get("category") or "").strip() or None
        db.session.flush()
        je = workspace_post_transfer(row)
        row.journal_entry_id = je.id
        db.session.commit()
        flash("Workspace transfer saved.", "success")
        return redirect(url_for("workspace_fund_transfers_list"))
    return render_template("workspace/transfer_form.html", row=row, employee=emp, accounts=accounts, parties=parties, drivers=drivers)


def workspace_fund_transfer_delete(pk):
    guard, emp = _workspace_guard("workspace_transfer_delete")
    if guard:
        return guard
    row = WorkspaceFundTransfer.query.filter_by(employee_id=emp.id, id=pk).first_or_404()
    workspace_reverse_journal_entry(row.journal_entry_id)
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
    accounts = Account.query.filter_by(is_active=True).order_by(Account.code).all()
    rows = WorkspaceMonthClose.query.filter_by(employee_id=emp.id).order_by(WorkspaceMonthClose.id.desc()).all()

    if request.method == "POST":
        period_start = parse_date(request.form.get("period_start"))
        period_end = parse_date(request.form.get("period_end"))
        company_account_id = request.form.get("company_account_id", type=int)
        notes = (request.form.get("notes") or "").strip()
        if not (period_start and period_end and company_account_id):
            flash("Period and company account are required.", "danger")
            return render_template("workspace/month_close.html", employee=emp, rows=rows, accounts=accounts)
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
    return render_template("workspace/month_close.html", employee=emp, rows=rows, accounts=accounts)


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
