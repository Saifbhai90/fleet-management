"""
Finance & Accounting Routes
All routes for vouchers, journal entries, ledgers, and financial reports
"""
from flask import render_template, request, redirect, url_for, flash, jsonify, session
from sqlalchemy import or_
from models import (db, Account, JournalEntry, JournalEntryLine, PaymentVoucher, ReceiptVoucher,
                    BankEntry, EmployeeExpense, District, Project, Party, Company, Employee, Driver, User,
                    FundTransfer, BankAccountDirectory)
from forms import (PaymentVoucherForm, ReceiptVoucherForm, BankEntryForm, JournalVoucherForm,
                   EmployeeExpenseForm, AccountLedgerFilterForm, BalanceSheetFilterForm,
                   AccountForm, FundTransferForm, FundTransferFilterForm, WalletDashboardFilterForm)
from finance_utils import (generate_entry_number, create_journal_entry, create_payment_voucher_journal,
                           create_receipt_voucher_journal, create_bank_entry_journal,
                           get_account_ledger, get_dto_wallet_summary, get_account_balance,
                           ensure_wallet_account, create_fund_transfer_journal)
from permissions_config import can_see_page
from utils import pk_now, pk_date
from datetime import datetime, date, timedelta
from decimal import Decimal
import os
from werkzeug.utils import secure_filename


# Helper function for authentication and permission checks
def check_auth(permission_code=None):
    """Check if user is logged in and has permission"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if permission_code:
        perms = session.get('permissions', [])
        if not session.get('is_master') and not can_see_page(perms, permission_code):
            flash('You do not have permission to access this page.', 'danger')
            return redirect(url_for('dashboard'))
    return None


# ════════════════════════════════════════════════════════════════════════════════
# PAYMENT VOUCHER
# ════════════════════════════════════════════════════════════════════════════════

def accounts_quick_payment():
    """Create Payment Voucher"""
    auth_check = check_auth('accounts_quick_payment')
    if auth_check:
        return auth_check
    
    form = PaymentVoucherForm()
    
    # Populate account choices
    accounts = Account.query.filter_by(is_active=True).order_by(Account.code).all()
    form.from_account_id.choices = [(0, '-- Select From Account --')] + [(a.id, f"{a.code} - {a.name}") for a in accounts]
    form.to_account_id.choices = [(0, '-- Select To Account --')] + [(a.id, f"{a.code} - {a.name}") for a in accounts]
    
    # Populate district and project choices
    districts = District.query.order_by(District.name).all()
    projects = Project.query.order_by(Project.name).all()
    form.district_id.choices = [(0, '-- Select District (Optional) --')] + [(d.id, d.name) for d in districts]
    form.project_id.choices = [(0, '-- Select Project (Optional) --')] + [(p.id, p.name) for p in projects]
    
    if form.validate_on_submit():
        try:
            # Generate voucher number
            voucher_number = generate_entry_number('PV', form.payment_date.data)
            
            # Create payment voucher
            pv = PaymentVoucher(
                voucher_number=voucher_number,
                payment_date=form.payment_date.data,
                from_account_id=form.from_account_id.data,
                to_account_id=form.to_account_id.data,
                amount=form.amount.data,
                payment_mode=form.payment_mode.data,
                cheque_number=form.cheque_number.data if form.cheque_number.data else None,
                description=form.description.data,
                district_id=form.district_id.data if form.district_id.data != 0 else None,
                project_id=form.project_id.data if form.project_id.data != 0 else None,
                created_by_user_id=session.get('user_id')
            )
            db.session.add(pv)
            db.session.flush()
            
            # Create journal entry
            je = create_payment_voucher_journal(pv)
            pv.journal_entry_id = je.id
            
            db.session.commit()
            flash(f'Payment Voucher {voucher_number} created successfully!', 'success')
            return redirect(url_for('payment_vouchers_list'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating payment voucher: {str(e)}', 'danger')
    
    return render_template('finance/payment_voucher_form.html', form=form, title='Payment Voucher')


def payment_vouchers_list():
    auth_check = check_auth('accounts_quick_payment')
    if auth_check:
        return auth_check
    """List all Payment Vouchers"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    
    # Filters
    from_date = request.args.get('from_date', '')
    to_date = request.args.get('to_date', '')
    district_id = request.args.get('district_id', 0, type=int)
    project_id = request.args.get('project_id', 0, type=int)
    
    # Build query
    query = PaymentVoucher.query
    
    if from_date:
        for _fmt in ('%d-%m-%Y', '%Y-%m-%d'):
            try:
                fd = datetime.strptime(from_date, _fmt).date()
                query = query.filter(PaymentVoucher.payment_date >= fd)
                break
            except ValueError:
                continue

    if to_date:
        for _fmt in ('%d-%m-%Y', '%Y-%m-%d'):
            try:
                td = datetime.strptime(to_date, _fmt).date()
                query = query.filter(PaymentVoucher.payment_date <= td)
                break
            except ValueError:
                continue
    
    if district_id > 0:
        query = query.filter(PaymentVoucher.district_id == district_id)
    
    if project_id > 0:
        query = query.filter(PaymentVoucher.project_id == project_id)
    
    # Sorting
    sort_by = request.args.get('sort_by', 'payment_date')
    sort_order = request.args.get('sort_order', 'desc')
    
    if sort_by == 'payment_date':
        query = query.order_by(PaymentVoucher.payment_date.desc() if sort_order == 'desc' else PaymentVoucher.payment_date.asc())
    elif sort_by == 'voucher_number':
        query = query.order_by(PaymentVoucher.voucher_number.desc() if sort_order == 'desc' else PaymentVoucher.voucher_number.asc())
    elif sort_by == 'amount':
        query = query.order_by(PaymentVoucher.amount.desc() if sort_order == 'desc' else PaymentVoucher.amount.asc())
    else:
        query = query.order_by(PaymentVoucher.payment_date.desc())
    
    search = (request.args.get('search') or '').strip()
    if search:
        tokens = [t.lower() for t in search.split() if t]
        for tok in tokens:
            like = f'%{tok}%'
            query = query.filter(or_(
                PaymentVoucher.voucher_number.ilike(like),
                PaymentVoucher.description.ilike(like),
                PaymentVoucher.payment_mode.ilike(like),
            ))

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    vouchers = pagination.items

    districts = District.query.order_by(District.name).all()
    projects = Project.query.order_by(Project.name).all()

    return render_template('finance/payment_vouchers_list.html',
                         vouchers=vouchers, pagination=pagination,
                         districts=districts, projects=projects,
                         from_date=from_date, to_date=to_date,
                         district_id=district_id, project_id=project_id,
                         sort_by=sort_by, sort_order=sort_order,
                         page=page, per_page=per_page, search=search)


def payment_voucher_edit(pk):
    auth_check = check_auth('accounts_quick_payment')
    if auth_check:
        return auth_check
    """Edit Payment Voucher"""
    pv = PaymentVoucher.query.get_or_404(pk)
    form = PaymentVoucherForm(obj=pv)
    
    # Populate choices
    accounts = Account.query.filter_by(is_active=True).order_by(Account.code).all()
    form.from_account_id.choices = [(a.id, f"{a.code} - {a.name}") for a in accounts]
    form.to_account_id.choices = [(a.id, f"{a.code} - {a.name}") for a in accounts]
    
    districts = District.query.order_by(District.name).all()
    projects = Project.query.order_by(Project.name).all()
    form.district_id.choices = [(0, '-- Select District (Optional) --')] + [(d.id, d.name) for d in districts]
    form.project_id.choices = [(0, '-- Select Project (Optional) --')] + [(p.id, p.name) for p in projects]
    
    if form.validate_on_submit():
        try:
            # Update payment voucher
            pv.payment_date = form.payment_date.data
            pv.from_account_id = form.from_account_id.data
            pv.to_account_id = form.to_account_id.data
            pv.amount = form.amount.data
            pv.payment_mode = form.payment_mode.data
            pv.cheque_number = form.cheque_number.data if form.cheque_number.data else None
            pv.description = form.description.data
            pv.district_id = form.district_id.data if form.district_id.data != 0 else None
            pv.project_id = form.project_id.data if form.project_id.data != 0 else None
            
            # Delete old journal entry and create new one
            if pv.journal_entry_id:
                old_je = JournalEntry.query.get(pv.journal_entry_id)
                if old_je:
                    db.session.delete(old_je)
            
            je = create_payment_voucher_journal(pv)
            pv.journal_entry_id = je.id
            
            db.session.commit()
            flash(f'Payment Voucher {pv.voucher_number} updated successfully!', 'success')
            return redirect(url_for('payment_vouchers_list'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating payment voucher: {str(e)}', 'danger')
    
    return render_template('finance/payment_voucher_form.html', form=form, title='Edit Payment Voucher', pv=pv)


def payment_voucher_delete(pk):
    auth_check = check_auth('accounts_quick_payment')
    if auth_check:
        return auth_check
    """Delete Payment Voucher"""
    pv = PaymentVoucher.query.get_or_404(pk)
    
    try:
        # Delete associated journal entry (will cascade delete lines and update balances)
        if pv.journal_entry_id:
            je = JournalEntry.query.get(pv.journal_entry_id)
            if je:
                db.session.delete(je)
        
        db.session.delete(pv)
        db.session.commit()
        flash(f'Payment Voucher {pv.voucher_number} deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting payment voucher: {str(e)}', 'danger')
    
    return redirect(url_for('payment_vouchers_list'))


# ════════════════════════════════════════════════════════════════════════════════
# RECEIPT VOUCHER
# ════════════════════════════════════════════════════════════════════════════════

def accounts_quick_receipt():
    auth_check = check_auth('accounts_quick_receipt')
    if auth_check:
        return auth_check
    """Create Receipt Voucher"""
    form = ReceiptVoucherForm()
    
    # Populate account choices
    accounts = Account.query.filter_by(is_active=True).order_by(Account.code).all()
    form.from_account_id.choices = [(0, '-- Select From Account --')] + [(a.id, f"{a.code} - {a.name}") for a in accounts]
    form.to_account_id.choices = [(0, '-- Select To Account --')] + [(a.id, f"{a.code} - {a.name}") for a in accounts]
    
    if form.validate_on_submit():
        try:
            voucher_number = generate_entry_number('RV', form.receipt_date.data)
            
            rv = ReceiptVoucher(
                voucher_number=voucher_number,
                receipt_date=form.receipt_date.data,
                from_account_id=form.from_account_id.data,
                to_account_id=form.to_account_id.data,
                amount=form.amount.data,
                receipt_mode=form.receipt_mode.data,
                description=form.description.data,
                created_by_user_id=session.get('user_id')
            )
            db.session.add(rv)
            db.session.flush()
            
            je = create_receipt_voucher_journal(rv)
            rv.journal_entry_id = je.id
            
            db.session.commit()
            flash(f'Receipt Voucher {voucher_number} created successfully!', 'success')
            return redirect(url_for('receipt_vouchers_list'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating receipt voucher: {str(e)}', 'danger')
    
    return render_template('finance/receipt_voucher_form.html', form=form, title='Receipt Voucher')


def receipt_vouchers_list():
    auth_check = check_auth('accounts_quick_receipt')
    if auth_check:
        return auth_check
    """List all Receipt Vouchers"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    
    from_date = request.args.get('from_date', '')
    to_date = request.args.get('to_date', '')
    
    query = ReceiptVoucher.query
    
    if from_date:
        for _fmt in ('%d-%m-%Y', '%Y-%m-%d'):
            try:
                fd = datetime.strptime(from_date, _fmt).date()
                query = query.filter(ReceiptVoucher.receipt_date >= fd)
                break
            except ValueError:
                continue

    if to_date:
        for _fmt in ('%d-%m-%Y', '%Y-%m-%d'):
            try:
                td = datetime.strptime(to_date, _fmt).date()
                query = query.filter(ReceiptVoucher.receipt_date <= td)
                break
            except ValueError:
                continue
    
    sort_by = request.args.get('sort_by', 'receipt_date')
    sort_order = request.args.get('sort_order', 'desc')
    
    if sort_by == 'receipt_date':
        query = query.order_by(ReceiptVoucher.receipt_date.desc() if sort_order == 'desc' else ReceiptVoucher.receipt_date.asc())
    elif sort_by == 'voucher_number':
        query = query.order_by(ReceiptVoucher.voucher_number.desc() if sort_order == 'desc' else ReceiptVoucher.voucher_number.asc())
    elif sort_by == 'amount':
        query = query.order_by(ReceiptVoucher.amount.desc() if sort_order == 'desc' else ReceiptVoucher.amount.asc())
    else:
        query = query.order_by(ReceiptVoucher.receipt_date.desc())
    
    search = (request.args.get('search') or '').strip()
    if search:
        tokens = [t.lower() for t in search.split() if t]
        for tok in tokens:
            like = f'%{tok}%'
            query = query.filter(or_(
                ReceiptVoucher.voucher_number.ilike(like),
                ReceiptVoucher.description.ilike(like),
                ReceiptVoucher.receipt_mode.ilike(like),
            ))

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    vouchers = pagination.items

    return render_template('finance/receipt_vouchers_list.html',
                         vouchers=vouchers, pagination=pagination,
                         from_date=from_date, to_date=to_date,
                         sort_by=sort_by, sort_order=sort_order,
                         page=page, per_page=per_page, search=search)


# ════════════════════════════════════════════════════════════════════════════════
# BANK ENTRY
# ════════════════════════════════════════════════════════════════════════════════

def accounts_bank_entry():
    auth_check = check_auth('accounts_bank_entry')
    if auth_check:
        return auth_check
    """Create Bank Entry"""
    form = BankEntryForm()
    
    # Only show Asset accounts (bank/cash accounts)
    accounts = Account.query.filter_by(is_active=True, account_type='Asset').order_by(Account.code).all()
    form.from_account_id.choices = [(0, '-- Select From Account --')] + [(a.id, f"{a.code} - {a.name}") for a in accounts]
    form.to_account_id.choices = [(0, '-- Select To Account --')] + [(a.id, f"{a.code} - {a.name}") for a in accounts]
    
    if form.validate_on_submit():
        try:
            entry_number = generate_entry_number('BE', form.entry_date.data)
            
            be = BankEntry(
                entry_number=entry_number,
                entry_date=form.entry_date.data,
                from_account_id=form.from_account_id.data,
                to_account_id=form.to_account_id.data,
                amount=form.amount.data,
                description=form.description.data,
                created_by_user_id=session.get('user_id')
            )
            db.session.add(be)
            db.session.flush()
            
            je = create_bank_entry_journal(be)
            be.journal_entry_id = je.id
            
            db.session.commit()
            flash(f'Bank Entry {entry_number} created successfully!', 'success')
            return redirect(url_for('bank_entries_list'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating bank entry: {str(e)}', 'danger')
    
    return render_template('finance/bank_entry_form.html', form=form, title='Bank Entry')


def bank_entries_list():
    auth_check = check_auth('accounts_bank_entry')
    if auth_check:
        return auth_check
    """List all Bank Entries"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    
    from_date = request.args.get('from_date', '')
    to_date = request.args.get('to_date', '')
    
    query = BankEntry.query
    
    if from_date:
        for _fmt in ('%d-%m-%Y', '%Y-%m-%d'):
            try:
                fd = datetime.strptime(from_date, _fmt).date()
                query = query.filter(BankEntry.entry_date >= fd)
                break
            except ValueError:
                continue

    if to_date:
        for _fmt in ('%d-%m-%Y', '%Y-%m-%d'):
            try:
                td = datetime.strptime(to_date, _fmt).date()
                query = query.filter(BankEntry.entry_date <= td)
                break
            except ValueError:
                continue
    
    search = (request.args.get('search') or '').strip()
    if search:
        tokens = [t.lower() for t in search.split() if t]
        for tok in tokens:
            like = f'%{tok}%'
            query = query.filter(or_(
                BankEntry.entry_number.ilike(like),
                BankEntry.description.ilike(like),
            ))

    query = query.order_by(BankEntry.entry_date.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    entries = pagination.items

    return render_template('finance/bank_entries_list.html',
                         entries=entries, pagination=pagination,
                         from_date=from_date, to_date=to_date,
                         page=page, per_page=per_page, search=search)


# ════════════════════════════════════════════════════════════════════════════════
# ACCOUNT LEDGER (KEY VIEW FOR DTOs)
# ════════════════════════════════════════════════════════════════════════════════

def accounts_account_ledger():
    auth_check = check_auth('accounts_account_ledger')
    if auth_check:
        return auth_check
    """Account Ledger View - Shows transactions and running balance"""
    form = AccountLedgerFilterForm()
    
    # Populate choices
    accounts = Account.query.filter_by(is_active=True).order_by(Account.code).all()
    form.account_id.choices = [(0, '-- Select Account --')] + [(a.id, f"{a.code} - {a.name}") for a in accounts]
    
    districts = District.query.order_by(District.name).all()
    projects = Project.query.order_by(Project.name).all()
    form.district_id.choices = [(0, '-- All Districts --')] + [(d.id, d.name) for d in districts]
    form.project_id.choices = [(0, '-- All Projects --')] + [(p.id, p.name) for p in projects]
    
    ledger_data = None
    dto_summary = None
    
    account_id_param = request.args.get('account_id', 0, type=int)
    if account_id_param > 0 and request.method == 'GET':
        form.account_id.data = account_id_param

    if request.method == 'POST' and form.validate_on_submit():
        account_id = form.account_id.data
        from_date_val = form.from_date.data
        to_date_val = form.to_date.data
        district_id = form.district_id.data if form.district_id.data and form.district_id.data != 0 else None
        project_id = form.project_id.data if form.project_id.data and form.project_id.data != 0 else None

        if account_id and account_id > 0:
            ledger_data = get_account_ledger(account_id, from_date_val, to_date_val)
            if ledger_data and ledger_data['account'].name.startswith('DTO Wallet'):
                if district_id and project_id:
                    dto_summary = get_dto_wallet_summary(district_id, project_id, from_date_val, to_date_val)
        else:
            flash('Please select an Account to view the ledger.', 'warning')
    elif account_id_param > 0:
        ledger_data = get_account_ledger(account_id_param, None, None)

    return render_template('finance/account_ledger.html',
                         form=form, ledger_data=ledger_data, dto_summary=dto_summary,
                         title='Account Ledger')


# ════════════════════════════════════════════════════════════════════════════════
# BALANCE SHEET
# ════════════════════════════════════════════════════════════════════════════════

def accounts_balance_sheet():
    auth_check = check_auth('accounts_balance_sheet')
    if auth_check:
        return auth_check
    """Balance Sheet Report"""
    form = BalanceSheetFilterForm()

    as_of_date = None
    balance_sheet_data = None

    if request.method == 'POST' and form.validate_on_submit():
        as_of_date = form.as_of_date.data or pk_date()
    elif request.method == 'GET' and request.args.get('as_of_date'):
        try:
            as_of_date = datetime.strptime(request.args['as_of_date'], '%d-%m-%Y').date()
        except ValueError:
            as_of_date = pk_date()
    if as_of_date:
        
        # Get all accounts grouped by type
        assets      = Account.query.filter_by(account_type='Asset',     is_active=True).order_by(Account.code).all()
        liabilities = Account.query.filter_by(account_type='Liability', is_active=True).order_by(Account.code).all()
        equity      = Account.query.filter_by(account_type='Equity',    is_active=True).order_by(Account.code).all()

        # B-09: Replace N+1 get_account_balance() calls with ONE bulk aggregate query
        from sqlalchemy import func as _func
        all_ids = [a.id for a in assets + liabilities + equity]
        _bal_rows = db.session.query(
            JournalEntryLine.account_id,
            _func.sum(JournalEntryLine.debit).label('td'),
            _func.sum(JournalEntryLine.credit).label('tc'),
        ).join(JournalEntry).filter(
            JournalEntryLine.account_id.in_(all_ids),
            JournalEntry.entry_date <= as_of_date,
            JournalEntry.is_posted == True,
        ).group_by(JournalEntryLine.account_id).all()

        _jnl = {r.account_id: (Decimal(str(r.td or 0)), Decimal(str(r.tc or 0))) for r in _bal_rows}

        def _bal(account):
            opening = Decimal(str(account.opening_balance or 0))
            debit, credit = _jnl.get(account.id, (Decimal('0'), Decimal('0')))
            if account.account_type in ('Asset', 'Expense'):
                return opening + debit - credit
            return opening + credit - debit

        total_assets      = sum(_bal(a) for a in assets)
        total_liabilities = sum(_bal(a) for a in liabilities)
        total_equity      = sum(_bal(a) for a in equity)

        balance_sheet_data = {
            'assets':      [(a, _bal(a)) for a in assets],
            'liabilities': [(a, _bal(a)) for a in liabilities],
            'equity':      [(a, _bal(a)) for a in equity],
            'total_assets': total_assets,
            'total_liabilities': total_liabilities,
            'total_equity': total_equity,
            'balanced': abs(total_assets - (total_liabilities + total_equity)) < Decimal('0.01'),
        }
    
    return render_template('finance/balance_sheet.html',
                         form=form, as_of_date=as_of_date,
                         balance_sheet_data=balance_sheet_data,
                         title='Balance Sheet')


# ════════════════════════════════════════════════════════════════════════════════
# EMPLOYEE EXPENSE
# ════════════════════════════════════════════════════════════════════════════════

def employee_expense_form(pk=None):
    auth_check = check_auth('employee_expense_add' if not pk else 'employee_expense_edit')
    if auth_check:
        return auth_check
    """Add/Edit Employee Expense"""
    expense = None
    if pk:
        expense = EmployeeExpense.query.get_or_404(pk)
        form = EmployeeExpenseForm(obj=expense)
    else:
        form = EmployeeExpenseForm()
    
    # Populate choices
    employees = Employee.query.filter_by(status='Active').order_by(Employee.name).all()
    form.employee_id.choices = [(0, '-- Select Employee (Optional) --')] + [(e.id, e.name) for e in employees]
    
    districts = District.query.order_by(District.name).all()
    projects = Project.query.order_by(Project.name).all()
    form.district_id.choices = [(0, '-- Select District (Optional) --')] + [(d.id, d.name) for d in districts]
    form.project_id.choices = [(0, '-- Select Project (Optional) --')] + [(p.id, p.name) for p in projects]
    
    if form.validate_on_submit():
        try:
            if not expense:
                expense = EmployeeExpense()
            
            expense.expense_date = form.expense_date.data
            expense.employee_id = form.employee_id.data if form.employee_id.data != 0 else None
            expense.user_id = session.get('user_id')
            expense.district_id = form.district_id.data if form.district_id.data != 0 else None
            expense.project_id = form.project_id.data if form.project_id.data != 0 else None
            expense.expense_category = form.expense_category.data
            expense.description = form.description.data
            expense.amount = form.amount.data
            expense.payment_mode = form.payment_mode.data
            expense.created_by_user_id = session.get('user_id')
            
            # Handle receipt upload
            if form.receipt.data:
                file = form.receipt.data
                filename = secure_filename(file.filename)
                timestamp = pk_now().strftime('%Y%m%d_%H%M%S')
                filename = f"receipt_{timestamp}_{filename}"
                upload_folder = os.path.join('static', 'uploads', 'receipts')
                os.makedirs(upload_folder, exist_ok=True)
                file_path = os.path.join(upload_folder, filename)
                file.save(file_path)
                expense.receipt_path = f"uploads/receipts/{filename}"
            
            if not pk:
                db.session.add(expense)
            
            db.session.flush()
            
            # Create journal entry (Debit: Expense, Credit: Cash or Employee Advance)
            # Find appropriate expense account based on category
            expense_account_map = {
                'Travel': '5210',
                'Office': '5220',
                'Communication': '5230',
                'Other': '5240'
            }
            expense_account_code = expense_account_map.get(expense.expense_category, '5240')
            expense_account = Account.query.filter_by(code=expense_account_code).first()
            
            # Use Cash account as credit
            cash_account = Account.query.filter_by(code='1110').first()
            
            if expense_account and cash_account:
                from finance_utils import create_expense_journal
                je = create_expense_journal('EmployeeExpense', expense, expense_account_code, cash_account.id)
                expense.journal_entry_id = je.id
            
            db.session.commit()
            flash(f'Employee Expense saved successfully!', 'success')
            return redirect(url_for('employee_expense_list'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error saving employee expense: {str(e)}', 'danger')
    
    return render_template('finance/employee_expense_form.html', form=form, expense=expense,
                         title='Add Employee Expense' if not pk else 'Edit Employee Expense')


def employee_expense_list():
    auth_check = check_auth('employee_expense_list')
    if auth_check:
        return auth_check
    """List all Employee Expenses"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    
    from_date = request.args.get('from_date', '')
    to_date = request.args.get('to_date', '')
    district_id = request.args.get('district_id', 0, type=int)
    project_id = request.args.get('project_id', 0, type=int)
    category = request.args.get('category', '')
    
    query = EmployeeExpense.query
    
    if from_date:
        for _fmt in ('%d-%m-%Y', '%Y-%m-%d'):
            try:
                fd = datetime.strptime(from_date, _fmt).date()
                query = query.filter(EmployeeExpense.expense_date >= fd)
                break
            except ValueError:
                continue

    if to_date:
        for _fmt in ('%d-%m-%Y', '%Y-%m-%d'):
            try:
                td = datetime.strptime(to_date, _fmt).date()
                query = query.filter(EmployeeExpense.expense_date <= td)
                break
            except ValueError:
                continue
    
    if district_id > 0:
        query = query.filter(EmployeeExpense.district_id == district_id)
    
    if project_id > 0:
        query = query.filter(EmployeeExpense.project_id == project_id)
    
    if category:
        query = query.filter(EmployeeExpense.expense_category == category)

    search = (request.args.get('search') or '').strip()
    if search:
        tokens = [t.lower() for t in search.split() if t]
        for tok in tokens:
            like = f'%{tok}%'
            query = query.filter(or_(
                EmployeeExpense.description.ilike(like),
                EmployeeExpense.expense_category.ilike(like),
                EmployeeExpense.payment_mode.ilike(like),
            ))

    query = query.order_by(EmployeeExpense.expense_date.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    expenses = pagination.items

    districts = District.query.order_by(District.name).all()
    projects = Project.query.order_by(Project.name).all()

    total_amount = sum(e.amount for e in expenses)

    return render_template('finance/employee_expenses_list.html',
                         expenses=expenses, pagination=pagination,
                         districts=districts, projects=projects,
                         from_date=from_date, to_date=to_date,
                         district_id=district_id, project_id=project_id,
                         category=category, total_amount=total_amount,
                         page=page, per_page=per_page, search=search)


def employee_expense_delete(pk):
    auth_check = check_auth('employee_expense_delete')
    if auth_check:
        return auth_check
    """Delete Employee Expense"""
    expense = EmployeeExpense.query.get_or_404(pk)
    
    try:
        # Delete journal entry
        if expense.journal_entry_id:
            je = JournalEntry.query.get(expense.journal_entry_id)
            if je:
                db.session.delete(je)
        
        # Delete receipt file if exists
        if expense.receipt_path:
            file_path = os.path.join('static', expense.receipt_path)
            if os.path.exists(file_path):
                os.remove(file_path)
        
        db.session.delete(expense)
        db.session.commit()
        flash('Employee Expense deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting expense: {str(e)}', 'danger')
    
    return redirect(url_for('employee_expense_list'))


# ════════════════════════════════════════════════════════════════════════════════
# CHART OF ACCOUNTS
# ════════════════════════════════════════════════════════════════════════════════

def chart_of_accounts_list():
    auth_check = check_auth('chart_of_accounts')
    if auth_check:
        return auth_check
    per_page = int(request.args.get('per_page', 50))
    page = int(request.args.get('page', 1))
    search = (request.args.get('search') or '').strip()

    query = Account.query.order_by(Account.code)
    if search:
        tokens = [t.lower() for t in search.split() if t]
        for tok in tokens:
            like = f'%{tok}%'
            query = query.filter(or_(
                Account.code.ilike(like),
                Account.name.ilike(like),
                Account.account_type.ilike(like),
            ))
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    return render_template('finance/chart_of_accounts.html',
                           title='Chart of Accounts', accounts=pagination.items,
                           pagination=pagination, per_page=per_page, search=search)


def chart_of_accounts_add():
    auth_check = check_auth('chart_of_accounts')
    if auth_check:
        return auth_check

    form = AccountForm()
    _populate_account_form(form)

    if form.validate_on_submit():
        try:
            acct = Account(
                code=form.code.data.strip(),
                name=form.name.data.strip(),
                account_type=form.account_type.data,
                parent_id=form.parent_id.data or None,
                opening_balance=form.opening_balance.data or 0,
                current_balance=form.opening_balance.data or 0,
                district_id=form.district_id.data or None,
                project_id=form.project_id.data or None,
                description=form.description.data,
                is_active=(form.is_active.data == '1'),
            )
            db.session.add(acct)
            db.session.commit()
            flash('Account created successfully!', 'success')
            return redirect(url_for('chart_of_accounts_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {e}', 'danger')

    return render_template('finance/account_form.html', form=form, title='Add Account')


def chart_of_accounts_edit(pk):
    auth_check = check_auth('chart_of_accounts')
    if auth_check:
        return auth_check

    acct = Account.query.get_or_404(pk)
    form = AccountForm(obj=acct)
    _populate_account_form(form)
    if request.method == 'GET':
        form.is_active.data = '1' if acct.is_active else '0'

    if form.validate_on_submit():
        try:
            acct.code = form.code.data.strip()
            acct.name = form.name.data.strip()
            acct.account_type = form.account_type.data
            acct.parent_id = form.parent_id.data or None
            acct.opening_balance = form.opening_balance.data or 0
            acct.district_id = form.district_id.data or None
            acct.project_id = form.project_id.data or None
            acct.description = form.description.data
            acct.is_active = (form.is_active.data == '1')
            db.session.commit()
            flash('Account updated successfully!', 'success')
            return redirect(url_for('chart_of_accounts_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {e}', 'danger')

    return render_template('finance/account_form.html', form=form, title='Edit Account')


def chart_of_accounts_toggle(pk):
    auth_check = check_auth('chart_of_accounts')
    if auth_check:
        return auth_check
    acct = Account.query.get_or_404(pk)
    acct.is_active = not acct.is_active
    db.session.commit()
    flash(f'Account {"activated" if acct.is_active else "deactivated"}.', 'success')
    return redirect(url_for('chart_of_accounts_list'))


def _populate_account_form(form):
    all_accounts = Account.query.filter_by(is_active=True).order_by(Account.code).all()
    form.parent_id.choices = [(0, '-- No Parent --')] + [(a.id, f"{a.code} - {a.name}") for a in all_accounts]
    districts = District.query.order_by(District.name).all()
    form.district_id.choices = [(0, '-- None --')] + [(d.id, d.name) for d in districts]
    projects = Project.query.order_by(Project.name).all()
    form.project_id.choices = [(0, '-- None --')] + [(p.id, p.name) for p in projects]


# ════════════════════════════════════════════════════════════════════════════════
# CHART OF ACCOUNTS — SEED & AUTO-CREATE HELPERS
# ════════════════════════════════════════════════════════════════════════════════

_COA_SEED = [
    # (code, name, type, parent_code, description)
    # ── ASSETS ──
    ('1000', 'Assets',                       'Asset',     None,   'All asset accounts'),
    ('1100', 'Cash & Bank',                  'Asset',     '1000', 'Cash in hand, bank accounts'),
    ('1101', 'Cash in Hand',                 'Asset',     '1100', 'Physical cash held by the company'),
    ('1102', 'Bank Account - HBL',           'Asset',     '1100', 'Example: Habib Bank Limited account'),
    ('1200', 'Wallets / Receivables',        'Asset',     '1000', 'Employee, Driver, DTO wallets (advances given)'),
    ('1300', 'Advance to Parties',           'Asset',     '1000', 'Advances paid to fuel pumps, workshops, vendors'),

    # ── LIABILITIES ──
    ('2000', 'Liabilities',                  'Liability', None,   'All liability accounts'),
    ('2100', 'Payables',                     'Liability', '2000', 'Amounts owed to suppliers / parties'),
    ('2101', 'Salary Payable',               'Liability', '2100', 'Example: Unpaid employee salaries'),
    ('2200', 'Company Funds Received',       'Liability', '2000', 'Funds received from companies (to be accounted)'),

    # ── EQUITY ──
    ('3000', 'Equity',                       'Equity',    None,   'Owner equity and retained earnings'),
    ('3100', 'Owner Capital',                'Equity',    '3000', 'Capital invested by owner'),
    ('3200', 'Retained Earnings',            'Equity',    '3000', 'Accumulated profits/losses'),

    # ── REVENUE ──
    ('4000', 'Revenue',                      'Revenue',   None,   'All income accounts'),
    ('4100', 'Service Income',               'Revenue',   '4000', 'Income from ambulance/transport services'),
    ('4200', 'Penalty / Fine Income',        'Revenue',   '4000', 'Fines collected from drivers'),

    # ── EXPENSES ──
    ('5000', 'Expenses',                     'Expense',   None,   'All expense accounts'),
    ('5100', 'Fuel Expenses',                'Expense',   '5000', 'Diesel, petrol, CNG purchases'),
    ('5101', 'Diesel',                       'Expense',   '5100', 'Example: Diesel fuel expense'),
    ('5102', 'Petrol',                       'Expense',   '5100', 'Example: Petrol fuel expense'),
    ('5200', 'Oil Expenses',                 'Expense',   '5000', 'Engine oil, gear oil, brake oil'),
    ('5201', 'Engine Oil',                   'Expense',   '5200', 'Example: Engine oil purchase'),
    ('5300', 'Maintenance Expenses',         'Expense',   '5000', 'Vehicle repairs, spare parts, servicing'),
    ('5301', 'Spare Parts',                  'Expense',   '5300', 'Example: Spare parts purchase'),
    ('5302', 'Labour / Workshop Charges',    'Expense',   '5300', 'Example: Mechanic/workshop fees'),
    ('5400', 'Salary & Wages',              'Expense',   '5000', 'Driver salaries, employee wages'),
    ('5401', 'Driver Salaries',              'Expense',   '5400', 'Example: Monthly driver salary payments'),
    ('5402', 'Employee Salaries',            'Expense',   '5400', 'Example: Monthly employee salary payments'),
    ('5500', 'Operational Expenses',         'Expense',   '5000', 'Day-to-day office/operational costs'),
    ('5501', 'TCS / Tax Charges',            'Expense',   '5500', 'Example: Tax collected at source'),
    ('5502', 'Travel Expense',               'Expense',   '5500', 'Example: Travel fare, bus tickets'),
    ('5503', 'Photocopy / Printing',         'Expense',   '5500', 'Example: Printing, photocopy, stationery'),
    ('5504', 'Mobile / Phone Recharge',      'Expense',   '5500', 'Example: Phone credit, SIM recharge'),
    ('5505', 'Courier / Postage',            'Expense',   '5500', 'Example: TCS, Leopards, postal charges'),
    ('5506', 'Office Supplies / Stationery', 'Expense',   '5500', 'Example: Pens, papers, files'),
    ('5507', 'Food / Refreshment',           'Expense',   '5500', 'Example: Tea, lunch during duty'),
    ('5600', 'Miscellaneous Expenses',       'Expense',   '5000', 'Other/uncategorized expenses'),

    # ── PARENT HEADS FOR AUTO-CREATED ACCOUNTS ──
    ('6000', 'Drivers',                      'Asset',     '1200', 'Auto-created: one sub-account per driver'),
    ('6500', 'Employees',                    'Asset',     '1200', 'Auto-created: one sub-account per employee'),
    ('7000', 'Parties / Vendors',            'Liability', '2100', 'Auto-created: one sub-account per party'),
    ('8000', 'Companies',                    'Liability', '2200', 'Auto-created: one sub-account per company'),
]

def seed_chart_of_accounts():
    """Seed default head accounts if not present. Safe to call multiple times."""
    from models import Company as CompanyModel
    code_map = {a.code: a for a in Account.query.all()}
    created = 0
    for code, name, atype, parent_code, desc in _COA_SEED:
        if code in code_map:
            continue
        parent_id = code_map[parent_code].id if parent_code and parent_code in code_map else None
        acct = Account(code=code, name=name, account_type=atype,
                       parent_id=parent_id, is_active=True,
                       opening_balance=0, current_balance=0, description=desc)
        db.session.add(acct)
        db.session.flush()
        code_map[code] = acct
        created += 1

    # Auto-create accounts for ALL existing drivers
    parent_drv = code_map.get('6000')
    if parent_drv:
        existing_drv = {a.entity_id for a in Account.query.filter_by(entity_type='driver').all()}
        for drv in Driver.query.order_by(Driver.id).all():
            if drv.id not in existing_drv:
                _auto_create_coa_account('driver', drv.id, drv.name,
                                         extra_label=drv.driver_id, parent_head=parent_drv,
                                         _code_map=code_map)
                created += 1

    # Auto-create accounts for ALL existing employees
    parent_emp = code_map.get('6500')
    if parent_emp:
        existing_emp = {a.entity_id for a in Account.query.filter_by(entity_type='employee').all()}
        for emp in Employee.query.order_by(Employee.id).all():
            if emp.id not in existing_emp:
                _auto_create_coa_account('employee', emp.id, emp.name,
                                         extra_label=emp.code, parent_head=parent_emp,
                                         _code_map=code_map)
                created += 1

    # Auto-create accounts for ALL existing parties
    parent_pty = code_map.get('7000')
    if parent_pty:
        existing_pty = {a.entity_id for a in Account.query.filter_by(entity_type='party').all()}
        for pty in Party.query.order_by(Party.id).all():
            if pty.id not in existing_pty:
                _auto_create_coa_account('party', pty.id, pty.name,
                                         extra_label=pty.party_type, parent_head=parent_pty,
                                         _code_map=code_map)
                created += 1

    # Auto-create accounts for ALL existing companies
    parent_co = code_map.get('8000')
    if parent_co:
        existing_co = {a.entity_id for a in Account.query.filter_by(entity_type='company').all()}
        for co in CompanyModel.query.order_by(CompanyModel.id).all():
            if co.id not in existing_co:
                _auto_create_coa_account('company', co.id, co.name,
                                         parent_head=parent_co, _code_map=code_map)
                created += 1

    if created:
        db.session.commit()
    return created


def _auto_create_coa_account(entity_type, entity_id, entity_name,
                              extra_label=None, parent_head=None, _code_map=None):
    """Create an Account sub-entry under the appropriate parent head."""
    existing = Account.query.filter_by(entity_type=entity_type, entity_id=entity_id).first()
    if existing:
        return existing

    parent_codes = {
        'driver': '6000', 'employee': '6500', 'party': '7000', 'company': '8000',
    }
    if not parent_head:
        parent_head = Account.query.filter_by(code=parent_codes.get(entity_type, '5600')).first()
    if not parent_head:
        return None

    prefix = parent_head.code
    max_sub = db.session.query(db.func.max(Account.code)).filter(
        Account.entity_type == entity_type
    ).scalar()
    if max_sub:
        try:
            next_num = int(max_sub) + 1
        except ValueError:
            next_num = int(prefix) * 10 + 1
    else:
        next_num = int(prefix) * 10 + 1
    new_code = str(next_num)

    lbl = f" ({extra_label})" if extra_label else ''
    type_labels = {'driver': 'Driver', 'employee': 'Employee',
                   'party': 'Vendor', 'company': 'Company'}
    acct = Account(
        code=new_code,
        name=f"{entity_name}{lbl}",
        account_type=parent_head.account_type,
        parent_id=parent_head.id,
        is_active=True,
        opening_balance=0,
        current_balance=0,
        entity_type=entity_type,
        entity_id=entity_id,
        description=f"Auto-created for {type_labels.get(entity_type, entity_type)}: {entity_name}",
    )
    db.session.add(acct)
    db.session.flush()

    if _code_map is not None:
        _code_map[new_code] = acct

    if entity_type == 'driver':
        drv = Driver.query.get(entity_id)
        if drv and not drv.wallet_account_id:
            drv.wallet_account_id = acct.id
    elif entity_type == 'employee':
        emp = Employee.query.get(entity_id)
        if emp and not emp.wallet_account_id:
            emp.wallet_account_id = acct.id

    return acct


# ════════════════════════════════════════════════════════════════════════════════
# FUND TRANSFER (Bank-like wallet system)
# ════════════════════════════════════════════════════════════════════════════════

def _person_choices():
    choices = [('', '-- Select Person / Account --')]

    _seen_acct_ids = set()

    for c in Company.query.order_by(Company.name).all():
        choices.append((f'com-{c.id}', f"{c.name} (Company)"))
        acct = Account.query.filter_by(entity_type='company', entity_id=c.id).first()
        if acct:
            _seen_acct_ids.add(acct.id)

    for e in Employee.query.filter_by(status='Active').order_by(Employee.name).all():
        post_label = e.post.full_name if e.post else 'Staff'
        choices.append((f'emp-{e.id}', f"{e.name} ({post_label})"))
        acct = Account.query.filter_by(entity_type='employee', entity_id=e.id).first()
        if acct:
            _seen_acct_ids.add(acct.id)

    for d in Driver.query.filter_by(status='Active').order_by(Driver.name).all():
        veh = f" – {d.vehicle.vehicle_no}" if d.vehicle else ""
        choices.append((f'drv-{d.id}', f"{d.name}{veh} (Driver)"))
        acct = Account.query.filter_by(entity_type='driver', entity_id=d.id).first()
        if acct:
            _seen_acct_ids.add(acct.id)

    for p in Party.query.order_by(Party.name).all():
        choices.append((f'pty-{p.id}', f"{p.name} ({p.party_type})"))
        acct = Account.query.filter_by(entity_type='party', entity_id=p.id).first()
        if acct:
            _seen_acct_ids.add(acct.id)

    _parent_codes = {'6000', '6500', '7000', '8000'}
    parent_ids = {a.id for a in Account.query.filter(Account.code.in_(_parent_codes)).all()}
    if parent_ids:
        extra = Account.query.filter(
            Account.parent_id.in_(parent_ids),
            Account.is_active == True,
            ~Account.id.in_(_seen_acct_ids) if _seen_acct_ids else True,
        ).order_by(Account.name).all()
        for a in extra:
            choices.append((f'acct-{a.id}', f"{a.name} (Account {a.code})"))

    return choices


def _parse_person(val):
    if not val:
        return None, None
    parts = val.split('-', 1)
    if len(parts) == 2 and parts[1].isdigit():
        return parts[0], int(parts[1])
    return None, None


def _upload_ft_attachment(file_storage):
    """Upload fund-transfer attachment image to R2, return public URL or None."""
    if not file_storage or not getattr(file_storage, 'filename', None):
        return None
    try:
        from r2_storage import upload_image_file as _r2_up, R2_PUBLIC_URL, R2_ACCESS_KEY_ID, R2_ENDPOINT_URL, R2_BUCKET_NAME
        if not all([R2_PUBLIC_URL, R2_ACCESS_KEY_ID, R2_ENDPOINT_URL, R2_BUCKET_NAME]):
            return None
        file_storage.seek(0)
        return _r2_up(file_storage, folder='fund_transfers')
    except Exception:
        return None


def _delete_ft_attachment(url):
    """Delete old attachment from R2 if it exists."""
    if not url:
        return
    try:
        from r2_storage import delete_file_by_url
        delete_file_by_url(url)
    except Exception:
        pass


def fund_transfer_add():
    auth_check = check_auth('fund_transfer')
    if auth_check:
        return auth_check

    form = FundTransferForm()
    choices = _person_choices()
    form.from_person.choices = choices
    form.to_person.choices = choices
    _populate_transfer_filters(form)

    if form.validate_on_submit():
        try:
            from_type, from_id = _parse_person(form.from_person.data)
            to_type, to_id = _parse_person(form.to_person.data)
            if not from_type or not to_type:
                flash('Please select both sender and receiver.', 'danger')
                return render_template('finance/fund_transfer_form.html', form=form, title='New Fund Transfer',
                           existing_attachment=None)

            from_wallet = ensure_wallet_account(from_type, from_id)
            to_wallet = ensure_wallet_account(to_type, to_id)

            attachment_url = _upload_ft_attachment(request.files.get('attachment'))

            transfer = FundTransfer(
                transfer_number=generate_entry_number('FT', form.transfer_date.data),
                transfer_date=form.transfer_date.data,
                from_employee_id=from_id if from_type == 'emp' else None,
                from_driver_id=from_id if from_type == 'drv' else None,
                from_party_id=from_id if from_type == 'pty' else None,
                from_company_id=from_id if from_type == 'com' else None,
                from_account_id=from_id if from_type == 'acct' else None,
                to_employee_id=to_id if to_type == 'emp' else None,
                to_driver_id=to_id if to_type == 'drv' else None,
                to_party_id=to_id if to_type == 'pty' else None,
                to_company_id=to_id if to_type == 'com' else None,
                to_account_id=to_id if to_type == 'acct' else None,
                amount=form.amount.data,
                payment_mode=form.payment_mode.data,
                reference_no=form.reference_no.data,
                description=form.description.data,
                attachment=attachment_url,
                is_salary=form.is_salary.data or False,
                district_id=form.district_id.data or None,
                project_id=form.project_id.data or None,
                created_by_user_id=session.get('user_id'),
            )
            db.session.add(transfer)
            db.session.flush()

            je = create_fund_transfer_journal(transfer, from_wallet, to_wallet)
            transfer.journal_entry_id = je.id
            db.session.commit()
            flash('Fund Transfer created successfully!', 'success')
            return redirect(url_for('fund_transfers_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {e}', 'danger')

    return render_template('finance/fund_transfer_form.html', form=form, title='New Fund Transfer',
                           existing_attachment=None)


def fund_transfer_edit(pk):
    auth_check = check_auth('fund_transfer')
    if auth_check:
        return auth_check

    transfer = FundTransfer.query.get_or_404(pk)
    form = FundTransferForm()
    choices = _person_choices()
    form.from_person.choices = choices
    form.to_person.choices = choices
    _populate_transfer_filters(form)

    if request.method == 'GET':
        form.transfer_date.data = transfer.transfer_date
        form.amount.data = transfer.amount
        form.payment_mode.data = transfer.payment_mode
        form.reference_no.data = transfer.reference_no
        form.description.data = transfer.description
        form.district_id.data = transfer.district_id or 0
        form.project_id.data = transfer.project_id or 0
        form.is_salary.data = transfer.is_salary
        if transfer.from_employee_id:
            form.from_person.data = f'emp-{transfer.from_employee_id}'
        elif transfer.from_driver_id:
            form.from_person.data = f'drv-{transfer.from_driver_id}'
        elif transfer.from_party_id:
            form.from_person.data = f'pty-{transfer.from_party_id}'
        elif transfer.from_company_id:
            form.from_person.data = f'com-{transfer.from_company_id}'
        elif transfer.from_account_id:
            form.from_person.data = f'acct-{transfer.from_account_id}'
        if transfer.to_employee_id:
            form.to_person.data = f'emp-{transfer.to_employee_id}'
        elif transfer.to_driver_id:
            form.to_person.data = f'drv-{transfer.to_driver_id}'
        elif transfer.to_party_id:
            form.to_person.data = f'pty-{transfer.to_party_id}'
        elif transfer.to_company_id:
            form.to_person.data = f'com-{transfer.to_company_id}'
        elif transfer.to_account_id:
            form.to_person.data = f'acct-{transfer.to_account_id}'

    if form.validate_on_submit():
        try:
            if transfer.journal_entry_id:
                old_je = JournalEntry.query.get(transfer.journal_entry_id)
                if old_je:
                    for line in old_je.lines:
                        db.session.delete(line)
                    db.session.delete(old_je)
                    db.session.flush()

            from_type, from_id = _parse_person(form.from_person.data)
            to_type, to_id = _parse_person(form.to_person.data)
            from_wallet = ensure_wallet_account(from_type, from_id)
            to_wallet = ensure_wallet_account(to_type, to_id)

            transfer.transfer_date = form.transfer_date.data
            transfer.from_employee_id = from_id if from_type == 'emp' else None
            transfer.from_driver_id = from_id if from_type == 'drv' else None
            transfer.from_party_id = from_id if from_type == 'pty' else None
            transfer.from_company_id = from_id if from_type == 'com' else None
            transfer.from_account_id = from_id if from_type == 'acct' else None
            transfer.to_employee_id = to_id if to_type == 'emp' else None
            transfer.to_driver_id = to_id if to_type == 'drv' else None
            transfer.to_party_id = to_id if to_type == 'pty' else None
            transfer.to_company_id = to_id if to_type == 'com' else None
            transfer.to_account_id = to_id if to_type == 'acct' else None
            transfer.amount = form.amount.data
            transfer.payment_mode = form.payment_mode.data
            transfer.reference_no = form.reference_no.data
            transfer.description = form.description.data
            transfer.district_id = form.district_id.data or None
            transfer.project_id = form.project_id.data or None
            transfer.is_salary = form.is_salary.data or False

            if request.form.get('remove_attachment') == '1':
                _delete_ft_attachment(transfer.attachment)
                transfer.attachment = None
            new_att = _upload_ft_attachment(request.files.get('attachment'))
            if new_att:
                _delete_ft_attachment(transfer.attachment)
                transfer.attachment = new_att

            db.session.flush()

            je = create_fund_transfer_journal(transfer, from_wallet, to_wallet)
            transfer.journal_entry_id = je.id
            db.session.commit()
            flash('Fund Transfer updated!', 'success')
            return redirect(url_for('fund_transfers_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {e}', 'danger')

    return render_template('finance/fund_transfer_form.html', form=form, title='Edit Fund Transfer',
                           existing_attachment=transfer.attachment)


def fund_transfer_delete(pk):
    auth_check = check_auth('fund_transfer')
    if auth_check:
        return auth_check
    transfer = FundTransfer.query.get_or_404(pk)
    try:
        if transfer.journal_entry_id:
            je = JournalEntry.query.get(transfer.journal_entry_id)
            if je:
                for line in je.lines:
                    db.session.delete(line)
                db.session.delete(je)
        db.session.delete(transfer)
        db.session.commit()
        flash('Fund Transfer deleted.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error: {e}', 'danger')
    return redirect(url_for('fund_transfers_list'))


def fund_transfers_list():
    auth_check = check_auth('fund_transfer')
    if auth_check:
        return auth_check

    form = FundTransferFilterForm()
    choices = [('0', '-- All Persons --')] + _person_choices()[1:]
    form.person.choices = choices
    _populate_transfer_filters(form)

    from_date = None
    to_date = None
    per_page = int(request.args.get('per_page', 25))
    page = int(request.args.get('page', 1))

    try:
        if request.args.get('from_date'):
            from_date = datetime.strptime(request.args['from_date'], '%d-%m-%Y').date()
        if request.args.get('to_date'):
            to_date = datetime.strptime(request.args['to_date'], '%d-%m-%Y').date()
    except ValueError:
        pass

    person_val = request.args.get('person', '0')
    district_val = int(request.args.get('district_id', 0) or 0)
    project_val = int(request.args.get('project_id', 0) or 0)

    form.from_date.data = from_date
    form.to_date.data = to_date
    form.person.data = person_val
    form.district_id.data = district_val
    form.project_id.data = project_val

    query = FundTransfer.query
    if from_date and to_date:
        query = query.filter(FundTransfer.transfer_date.between(from_date, to_date))
    elif from_date:
        query = query.filter(FundTransfer.transfer_date >= from_date)
    elif to_date:
        query = query.filter(FundTransfer.transfer_date <= to_date)

    if person_val and person_val != '0':
        p_type, p_id = _parse_person(person_val)
        if p_type and p_id:
            if p_type == 'emp':
                query = query.filter(or_(
                    FundTransfer.from_employee_id == p_id,
                    FundTransfer.to_employee_id == p_id))
            elif p_type == 'drv':
                query = query.filter(or_(
                    FundTransfer.from_driver_id == p_id,
                    FundTransfer.to_driver_id == p_id))
            elif p_type == 'pty':
                query = query.filter(or_(
                    FundTransfer.from_party_id == p_id,
                    FundTransfer.to_party_id == p_id))
            elif p_type == 'com':
                query = query.filter(or_(
                    FundTransfer.from_company_id == p_id,
                    FundTransfer.to_company_id == p_id))
            elif p_type == 'acct':
                query = query.filter(or_(
                    FundTransfer.from_account_id == p_id,
                    FundTransfer.to_account_id == p_id))

    if district_val and district_val > 0:
        query = query.filter_by(district_id=district_val)
    if project_val and project_val > 0:
        query = query.filter_by(project_id=project_val)

    search = (request.args.get('search') or '').strip()
    if search:
        tokens = [t.lower() for t in search.split() if t]
        for tok in tokens:
            like = f'%{tok}%'
            query = query.filter(or_(
                FundTransfer.transfer_number.ilike(like),
                FundTransfer.description.ilike(like),
                FundTransfer.payment_mode.ilike(like),
                FundTransfer.reference_no.ilike(like),
            ))

    query = query.order_by(FundTransfer.transfer_date.desc(), FundTransfer.id.desc())
    transfers = query.paginate(page=page, per_page=per_page, error_out=False)
    return render_template('finance/fund_transfers_list.html',
                           form=form, transfers=transfers,
                           from_date=from_date, to_date=to_date, per_page=per_page, search=search)


def _populate_transfer_filters(form):
    districts = District.query.order_by(District.name).all()
    form.district_id.choices = [(0, '-- All --')] + [(d.id, d.name) for d in districts]
    projects = Project.query.order_by(Project.name).all()
    form.project_id.choices = [(0, '-- All --')] + [(p.id, p.name) for p in projects]


# ════════════════════════════════════════════════════════════════════════════════
# WALLET DASHBOARD
# ════════════════════════════════════════════════════════════════════════════════

def wallet_dashboard():
    auth_check = check_auth('wallet_dashboard')
    if auth_check:
        return auth_check

    form = WalletDashboardFilterForm()
    districts = District.query.order_by(District.name).all()
    form.district_id.choices = [(0, '-- All --')] + [(d.id, d.name) for d in districts]
    projects = Project.query.order_by(Project.name).all()
    form.project_id.choices = [(0, '-- All --')] + [(p.id, p.name) for p in projects]

    filter_district = request.args.get('district_id', 0, type=int)
    filter_project = request.args.get('project_id', 0, type=int)
    form.district_id.data = filter_district
    form.project_id.data = filter_project

    wallets = []
    total_funds = Decimal('0')
    total_expenses = Decimal('0')

    emp_recv = dict(db.session.query(
        FundTransfer.to_employee_id,
        db.func.coalesce(db.func.sum(FundTransfer.amount), 0)
    ).filter(FundTransfer.to_employee_id.isnot(None)).group_by(FundTransfer.to_employee_id).all())
    drv_recv = dict(db.session.query(
        FundTransfer.to_driver_id,
        db.func.coalesce(db.func.sum(FundTransfer.amount), 0)
    ).filter(FundTransfer.to_driver_id.isnot(None)).group_by(FundTransfer.to_driver_id).all())
    wallet_spent = dict(db.session.query(
        JournalEntryLine.account_id,
        db.func.coalesce(db.func.sum(JournalEntryLine.credit), 0)
    ).join(JournalEntry).filter(
        JournalEntry.entry_type == 'Expense',
        JournalEntry.is_posted == True,
    ).group_by(JournalEntryLine.account_id).all())

    all_acct_ids = set()
    employees = Employee.query.filter(Employee.wallet_account_id.isnot(None)).all()
    drv_query = Driver.query.filter(Driver.wallet_account_id.isnot(None))
    if filter_district:
        drv_query = drv_query.filter(Driver.district_id == filter_district)
    if filter_project:
        drv_query = drv_query.filter(Driver.project_id == filter_project)
    drivers = drv_query.all()
    for emp in employees:
        all_acct_ids.add(emp.wallet_account_id)
    for drv in drivers:
        all_acct_ids.add(drv.wallet_account_id)
    acct_map = {a.id: a for a in Account.query.filter(Account.id.in_(all_acct_ids)).all()} if all_acct_ids else {}

    proj_ids = {drv.project_id for drv in drivers if drv.project_id}
    proj_map = {p.id: p.name for p in Project.query.filter(Project.id.in_(proj_ids)).all()} if proj_ids else {}

    for emp in employees:
        acct = acct_map.get(emp.wallet_account_id)
        if not acct:
            continue
        emp_districts = [d.name for d in emp.districts]
        emp_projects = [p.name for p in emp.projects]
        emp_district_ids = [d.id for d in emp.districts]
        emp_project_ids = [p.id for p in emp.projects]
        if filter_district and filter_district not in emp_district_ids:
            continue
        if filter_project and filter_project not in emp_project_ids:
            continue
        bal = acct.current_balance or Decimal('0')
        received = Decimal(str(emp_recv.get(emp.id, 0)))
        spent = Decimal(str(wallet_spent.get(acct.id, 0)))
        wallets.append({
            'person_name': emp.name,
            'person_type': 'Employee',
            'post': emp.post.full_name if emp.post else '—',
            'district_name': ', '.join(emp_districts) or '—',
            'project_name': ', '.join(emp_projects) or '—',
            'balance': bal,
            'total_received': received,
            'total_spent': spent,
            'account_id': acct.id,
        })
        if bal > 0:
            total_funds += bal
        else:
            total_expenses += abs(bal)

    for drv in drivers:
        acct = acct_map.get(drv.wallet_account_id)
        if not acct:
            continue
        bal = acct.current_balance or Decimal('0')
        received = Decimal(str(drv_recv.get(drv.id, 0)))
        spent = Decimal(str(wallet_spent.get(acct.id, 0)))
        wallets.append({
            'person_name': drv.name,
            'person_type': 'Driver',
            'post': 'Driver',
            'district_name': drv.district.name if drv.district else '—',
            'project_name': proj_map.get(drv.project_id, '—'),
            'balance': bal,
            'total_received': received,
            'total_spent': spent,
            'account_id': acct.id,
        })
        if bal > 0:
            total_funds += bal
        else:
            total_expenses += abs(bal)

    search = request.args.get('search', '').strip()
    if search:
        tokens = search.lower().split()
        def _match_wallet(w):
            blob = ' '.join([
                w.get('person_name', ''), w.get('person_type', ''),
                w.get('post', ''), w.get('district_name', ''),
                w.get('project_name', ''),
            ]).lower()
            return all(t in blob for t in tokens)
        wallets = [w for w in wallets if _match_wallet(w)]

    summary = {
        'total_wallets': len(wallets),
        'total_funds': total_funds,
        'total_expenses': total_expenses,
        'net_outstanding': total_funds - total_expenses,
    }

    return render_template('finance/wallet_dashboard.html',
                           form=form, wallets=wallets, summary=summary,
                           search=search)


def _sum_transfers_received(person_type, person_id):
    if person_type == 'emp':
        total = db.session.query(db.func.coalesce(db.func.sum(FundTransfer.amount), 0)).filter(
            FundTransfer.to_employee_id == person_id).scalar()
    else:
        total = db.session.query(db.func.coalesce(db.func.sum(FundTransfer.amount), 0)).filter(
            FundTransfer.to_driver_id == person_id).scalar()
    return Decimal(str(total))


def _sum_expenses_from_wallet(wallet_account_id):
    total = db.session.query(
        db.func.coalesce(db.func.sum(JournalEntryLine.credit), 0)
    ).join(JournalEntry).filter(
        JournalEntryLine.account_id == wallet_account_id,
        JournalEntry.entry_type == 'Expense',
        JournalEntry.is_posted == True,
    ).scalar()
    return Decimal(str(total))


# ════════════════════════════════════════════════════════════════════════════════
# JOURNAL VOUCHER (replace placeholder)
# ════════════════════════════════════════════════════════════════════════════════

def journal_voucher_add():
    auth_check = check_auth('accounts_jv')
    if auth_check:
        return auth_check

    form = JournalVoucherForm()
    districts = District.query.order_by(District.name).all()
    form.district_id.choices = [(0, '-- None --')] + [(d.id, d.name) for d in districts]
    projects = Project.query.order_by(Project.name).all()
    form.project_id.choices = [(0, '-- None --')] + [(p.id, p.name) for p in projects]
    accounts = [(a.id, f"{a.code} - {a.name}") for a in
                Account.query.filter_by(is_active=True).order_by(Account.code).all()]

    if request.method == 'POST' and form.validate():
        try:
            line_accounts = request.form.getlist('line_account_id')
            line_debits = request.form.getlist('line_debit')
            line_credits = request.form.getlist('line_credit')
            line_descs = request.form.getlist('line_description')

            lines = []
            for i in range(len(line_accounts)):
                acct_id = int(line_accounts[i]) if line_accounts[i] else 0
                debit = Decimal(line_debits[i] or '0')
                credit = Decimal(line_credits[i] or '0')
                if acct_id and (debit or credit):
                    lines.append({
                        'account_id': acct_id,
                        'debit': debit,
                        'credit': credit,
                        'description': line_descs[i] if i < len(line_descs) else '',
                    })

            if not lines:
                flash('Please add at least one journal line.', 'danger')
            else:
                je = create_journal_entry(
                    entry_type='Journal',
                    entry_date=form.entry_date.data,
                    description=form.description.data,
                    lines=lines,
                    district_id=form.district_id.data or None,
                    project_id=form.project_id.data or None,
                    reference_type='Manual',
                    created_by_user_id=session.get('user_id'),
                )
                db.session.commit()
                flash(f'Journal Voucher {je.entry_number} created!', 'success')
                return redirect(url_for('journal_vouchers_list'))
        except ValueError as e:
            db.session.rollback()
            flash(f'Validation error: {e}', 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {e}', 'danger')

    return render_template('finance/journal_voucher_form.html',
                           form=form, title='New Journal Voucher', accounts=accounts)


def journal_vouchers_list():
    auth_check = check_auth('accounts_jv')
    if auth_check:
        return auth_check

    from_date = None
    to_date = None
    per_page = int(request.args.get('per_page', request.form.get('per_page', 20)))
    page = int(request.args.get('page', 1))

    def _parse_date(val):
        if not val:
            return None
        for fmt in ('%Y-%m-%d', '%d-%m-%Y'):
            try:
                return datetime.strptime(val, fmt).date()
            except ValueError:
                continue
        return None

    fd = request.values.get('from_date', '')
    td = request.values.get('to_date', '')
    from_date = _parse_date(fd)
    to_date = _parse_date(td)

    query = JournalEntry.query
    if from_date and to_date:
        query = query.filter(JournalEntry.entry_date.between(from_date, to_date))
    elif from_date:
        query = query.filter(JournalEntry.entry_date >= from_date)
    elif to_date:
        query = query.filter(JournalEntry.entry_date <= to_date)
    query = query.order_by(JournalEntry.entry_date.desc(), JournalEntry.id.desc())

    search = (request.args.get('search') or '').strip()
    if search:
        tokens = [t.lower() for t in search.split() if t]
        for tok in tokens:
            like = f'%{tok}%'
            query = query.filter(or_(
                JournalEntry.entry_number.ilike(like),
                JournalEntry.description.ilike(like),
                JournalEntry.entry_type.ilike(like),
            ))

    entries = query.paginate(page=page, per_page=per_page, error_out=False)

    return render_template('finance/journal_vouchers_list.html',
                           entries=entries, from_date=from_date, to_date=to_date, per_page=per_page, search=search)


# ──────────────────────────────────────────────────────
# Bank Account Directory – JSON API (for Fund Transfer panel)
# ──────────────────────────────────────────────────────

def bank_directory_list_api():
    """Return all entries, optionally filtered by search query."""
    q = (request.args.get('q') or '').strip()
    query = BankAccountDirectory.query
    if q:
        tokens = [t.lower() for t in q.split() if t]
        for tok in tokens:
            like = f'%{tok}%'
            query = query.filter(or_(
                BankAccountDirectory.bank_name.ilike(like),
                BankAccountDirectory.account_no.ilike(like),
                BankAccountDirectory.account_title.ilike(like),
            ))
    items = query.order_by(BankAccountDirectory.id.desc()).limit(200).all()
    return jsonify([i.to_dict() for i in items])


def bank_directory_add_api():
    """Add a new bank account entry."""
    data = request.get_json(silent=True) or {}
    bank_name = (data.get('bank_name') or '').strip()
    account_no = (data.get('account_no') or '').strip()
    account_title = (data.get('account_title') or '').strip()
    if not bank_name and not account_no and not account_title:
        return jsonify({'error': 'At least one field is required.'}), 400
    entry = BankAccountDirectory(
        bank_name=bank_name or None,
        account_no=account_no or None,
        account_title=account_title or None,
        created_by_user_id=session.get('user_id'),
    )
    db.session.add(entry)
    db.session.commit()
    return jsonify(entry.to_dict()), 201


def bank_directory_delete_api(pk):
    """Delete a bank account entry."""
    entry = BankAccountDirectory.query.get_or_404(pk)
    db.session.delete(entry)
    db.session.commit()
    return jsonify({'ok': True})


def ft_description_suggestions_api():
    """Return unique past Fund Transfer descriptions for autocomplete."""
    q = (request.args.get('q') or '').strip().lower()
    query = db.session.query(FundTransfer.description).filter(
        FundTransfer.description.isnot(None),
        FundTransfer.description != '',
    ).distinct().order_by(FundTransfer.description)
    if q:
        query = query.filter(FundTransfer.description.ilike(f'%{q}%'))
    results = query.limit(30).all()
    return jsonify([r[0] for r in results if r[0]])
