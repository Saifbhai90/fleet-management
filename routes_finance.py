"""
Finance & Accounting Routes
All routes for vouchers, journal entries, ledgers, and financial reports
"""
from flask import render_template, request, redirect, url_for, flash, jsonify, session
from models import (db, Account, JournalEntry, JournalEntryLine, PaymentVoucher, ReceiptVoucher, 
                    BankEntry, EmployeeExpense, District, Project, Party, Employee, User)
from forms import (PaymentVoucherForm, ReceiptVoucherForm, BankEntryForm, JournalVoucherForm,
                   EmployeeExpenseForm, AccountLedgerFilterForm, BalanceSheetFilterForm)
from finance_utils import (generate_entry_number, create_journal_entry, create_payment_voucher_journal,
                           create_receipt_voucher_journal, create_bank_entry_journal, 
                           get_account_ledger, get_dto_wallet_summary, get_account_balance)
from auth_utils import login_required, permission_required
from datetime import datetime, date, timedelta
from decimal import Decimal
import os
from werkzeug.utils import secure_filename


# ════════════════════════════════════════════════════════════════════════════════
# PAYMENT VOUCHER
# ════════════════════════════════════════════════════════════════════════════════

@login_required
@permission_required('accounts_quick_payment')
def accounts_quick_payment():
    """Create Payment Voucher"""
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


@login_required
@permission_required('accounts_quick_payment')
def payment_vouchers_list():
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
        try:
            fd = datetime.strptime(from_date, '%Y-%m-%d').date()
            query = query.filter(PaymentVoucher.payment_date >= fd)
        except:
            pass
    
    if to_date:
        try:
            td = datetime.strptime(to_date, '%Y-%m-%d').date()
            query = query.filter(PaymentVoucher.payment_date <= td)
        except:
            pass
    
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
    
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    vouchers = pagination.items
    
    # Get districts and projects for filter
    districts = District.query.order_by(District.name).all()
    projects = Project.query.order_by(Project.name).all()
    
    return render_template('finance/payment_vouchers_list.html', 
                         vouchers=vouchers, pagination=pagination,
                         districts=districts, projects=projects,
                         from_date=from_date, to_date=to_date,
                         district_id=district_id, project_id=project_id,
                         sort_by=sort_by, sort_order=sort_order,
                         page=page, per_page=per_page)


@login_required
@permission_required('accounts_quick_payment')
def payment_voucher_edit(pk):
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


@login_required
@permission_required('accounts_quick_payment')
def payment_voucher_delete(pk):
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

@login_required
@permission_required('accounts_quick_receipt')
def accounts_quick_receipt():
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


@login_required
@permission_required('accounts_quick_receipt')
def receipt_vouchers_list():
    """List all Receipt Vouchers"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    
    from_date = request.args.get('from_date', '')
    to_date = request.args.get('to_date', '')
    
    query = ReceiptVoucher.query
    
    if from_date:
        try:
            fd = datetime.strptime(from_date, '%Y-%m-%d').date()
            query = query.filter(ReceiptVoucher.receipt_date >= fd)
        except:
            pass
    
    if to_date:
        try:
            td = datetime.strptime(to_date, '%Y-%m-%d').date()
            query = query.filter(ReceiptVoucher.receipt_date <= td)
        except:
            pass
    
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
    
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    vouchers = pagination.items
    
    return render_template('finance/receipt_vouchers_list.html',
                         vouchers=vouchers, pagination=pagination,
                         from_date=from_date, to_date=to_date,
                         sort_by=sort_by, sort_order=sort_order,
                         page=page, per_page=per_page)


# ════════════════════════════════════════════════════════════════════════════════
# BANK ENTRY
# ════════════════════════════════════════════════════════════════════════════════

@login_required
@permission_required('accounts_bank_entry')
def accounts_bank_entry():
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


@login_required
@permission_required('accounts_bank_entry')
def bank_entries_list():
    """List all Bank Entries"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    
    from_date = request.args.get('from_date', '')
    to_date = request.args.get('to_date', '')
    
    query = BankEntry.query
    
    if from_date:
        try:
            fd = datetime.strptime(from_date, '%Y-%m-%d').date()
            query = query.filter(BankEntry.entry_date >= fd)
        except:
            pass
    
    if to_date:
        try:
            td = datetime.strptime(to_date, '%Y-%m-%d').date()
            query = query.filter(BankEntry.entry_date <= td)
        except:
            pass
    
    query = query.order_by(BankEntry.entry_date.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    entries = pagination.items
    
    return render_template('finance/bank_entries_list.html',
                         entries=entries, pagination=pagination,
                         from_date=from_date, to_date=to_date,
                         page=page, per_page=per_page)


# ════════════════════════════════════════════════════════════════════════════════
# ACCOUNT LEDGER (KEY VIEW FOR DTOs)
# ════════════════════════════════════════════════════════════════════════════════

@login_required
@permission_required('accounts_account_ledger')
def accounts_account_ledger():
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
    
    if request.method == 'POST' and form.validate_on_submit():
        account_id = form.account_id.data
        from_date = form.from_date.data
        to_date = form.to_date.data
        district_id = form.district_id.data if form.district_id.data != 0 else None
        project_id = form.project_id.data if form.project_id.data != 0 else None
        
        if account_id > 0:
            ledger_data = get_account_ledger(account_id, from_date, to_date)
            
            # If this is a DTO wallet account, also get summary
            if ledger_data and ledger_data['account'].name.startswith('DTO Wallet'):
                if district_id and project_id:
                    dto_summary = get_dto_wallet_summary(district_id, project_id, from_date, to_date)
    
    return render_template('finance/account_ledger.html',
                         form=form, ledger_data=ledger_data, dto_summary=dto_summary,
                         title='Account Ledger')


# ════════════════════════════════════════════════════════════════════════════════
# BALANCE SHEET
# ════════════════════════════════════════════════════════════════════════════════

@login_required
@permission_required('accounts_balance_sheet')
def accounts_balance_sheet():
    """Balance Sheet Report"""
    form = BalanceSheetFilterForm()
    
    as_of_date = None
    balance_sheet_data = None
    
    if request.method == 'POST' and form.validate_on_submit():
        as_of_date = form.as_of_date.data or date.today()
        
        # Get all accounts grouped by type
        assets = Account.query.filter_by(account_type='Asset', is_active=True).order_by(Account.code).all()
        liabilities = Account.query.filter_by(account_type='Liability', is_active=True).order_by(Account.code).all()
        equity = Account.query.filter_by(account_type='Equity', is_active=True).order_by(Account.code).all()
        
        # Calculate balances
        total_assets = sum(get_account_balance(a.id, as_of_date) for a in assets)
        total_liabilities = sum(get_account_balance(a.id, as_of_date) for a in liabilities)
        total_equity = sum(get_account_balance(a.id, as_of_date) for a in equity)
        
        balance_sheet_data = {
            'assets': [(a, get_account_balance(a.id, as_of_date)) for a in assets],
            'liabilities': [(a, get_account_balance(a.id, as_of_date)) for a in liabilities],
            'equity': [(a, get_account_balance(a.id, as_of_date)) for a in equity],
            'total_assets': total_assets,
            'total_liabilities': total_liabilities,
            'total_equity': total_equity,
            'balanced': abs(total_assets - (total_liabilities + total_equity)) < Decimal('0.01')
        }
    
    return render_template('finance/balance_sheet.html',
                         form=form, as_of_date=as_of_date,
                         balance_sheet_data=balance_sheet_data,
                         title='Balance Sheet')


# ════════════════════════════════════════════════════════════════════════════════
# EMPLOYEE EXPENSE
# ════════════════════════════════════════════════════════════════════════════════

@login_required
@permission_required('employee_expense_form')
def employee_expense_form(pk=None):
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
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
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


@login_required
@permission_required('employee_expense_list')
def employee_expense_list():
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
        try:
            fd = datetime.strptime(from_date, '%Y-%m-%d').date()
            query = query.filter(EmployeeExpense.expense_date >= fd)
        except:
            pass
    
    if to_date:
        try:
            td = datetime.strptime(to_date, '%Y-%m-%d').date()
            query = query.filter(EmployeeExpense.expense_date <= td)
        except:
            pass
    
    if district_id > 0:
        query = query.filter(EmployeeExpense.district_id == district_id)
    
    if project_id > 0:
        query = query.filter(EmployeeExpense.project_id == project_id)
    
    if category:
        query = query.filter(EmployeeExpense.expense_category == category)
    
    query = query.order_by(EmployeeExpense.expense_date.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    expenses = pagination.items
    
    # Get filter options
    districts = District.query.order_by(District.name).all()
    projects = Project.query.order_by(Project.name).all()
    
    # Calculate totals
    total_amount = sum(e.amount for e in expenses)
    
    return render_template('finance/employee_expenses_list.html',
                         expenses=expenses, pagination=pagination,
                         districts=districts, projects=projects,
                         from_date=from_date, to_date=to_date,
                         district_id=district_id, project_id=project_id,
                         category=category, total_amount=total_amount,
                         page=page, per_page=per_page)


@login_required
@permission_required('employee_expense_form')
def employee_expense_delete(pk):
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
