"""
Finance & Accounting Utility Functions
Helper functions for voucher number generation, journal entry creation, and balance updates
"""
from models import (
    db, Account, JournalEntry, JournalEntryLine, PaymentVoucher, ReceiptVoucher, BankEntry, VoucherSequence,
    Employee, Driver, Party, Company,
    WorkspaceParty, WorkspaceAccount, WorkspaceJournalEntry, WorkspaceJournalEntryLine, WorkspaceExpense, WorkspaceOpeningExpense, WorkspaceFuelOilOpeningExpense, WorkspaceMonthClose, WorkspaceFuelOilMonthClose,
    WorkspaceFundTransfer,
)
from utils import pk_now, pk_date
from datetime import datetime, date, timedelta
from decimal import Decimal
from sqlalchemy.exc import IntegrityError


def generate_entry_number(prefix='JE', entry_date=None):
    """
    Generate a unique, collision-free entry number: JE-2026-03-001, PV-2026-03-001, etc.

    Uses a dedicated VoucherSequence table with SELECT FOR UPDATE so that concurrent
    requests increment the counter atomically (B-04 race condition fix).
    A savepoint guards the first-insert path against the concurrent-insert edge case.

    Args:
        prefix: Entry type prefix (JE, PV, RV, BE)
        entry_date: Date for the entry (default: today)

    Returns:
        str: Unique entry number
    """
    if entry_date is None:
        entry_date = pk_date()

    year = entry_date.year
    month = entry_date.month

    # Try to lock an existing sequence row for this prefix+year+month
    seq_row = db.session.query(VoucherSequence).filter_by(
        prefix=prefix, year=year, month=month
    ).with_for_update().first()

    if seq_row is None:
        # No row yet — insert with seq=1 inside a savepoint so that a concurrent
        # insert (IntegrityError on the unique constraint) doesn't abort the outer
        # transaction; we simply fall back to re-reading the now-existing row.
        try:
            with db.session.begin_nested():
                seq_row = VoucherSequence(prefix=prefix, year=year, month=month, last_seq=1)
                db.session.add(seq_row)
                db.session.flush()
            seq = 1
        except IntegrityError:
            # Another concurrent request beat us to the insert; re-read with lock
            seq_row = db.session.query(VoucherSequence).filter_by(
                prefix=prefix, year=year, month=month
            ).with_for_update().first()
            seq_row.last_seq += 1
            seq = seq_row.last_seq
            db.session.flush()
    else:
        seq_row.last_seq += 1
        seq = seq_row.last_seq
        db.session.flush()

    return f"{prefix}-{year:04d}-{month:02d}-{seq:03d}"


def create_journal_entry(entry_type, entry_date, description, lines, district_id=None, project_id=None, 
                         reference_type=None, reference_id=None, created_by_user_id=None, category=None):
    """
    Create a journal entry with lines.
    
    Args:
        entry_type: Type of entry (Payment, Receipt, Bank, Journal, Expense)
        entry_date: Date of transaction
        description: Transaction description
        lines: List of dicts with keys: account_id, debit, credit, description
        district_id: Optional district filter
        project_id: Optional project filter
        reference_type: Source type (FuelExpense, OilExpense, etc.)
        reference_id: Source record ID
        created_by_user_id: User who created the entry
    
    Returns:
        JournalEntry: Created journal entry object
    
    Raises:
        ValueError: If journal entry is not balanced
    """
    # Generate entry number
    entry_number = generate_entry_number('JE', entry_date)
    
    # Create journal entry
    je = JournalEntry(
        entry_number=entry_number,
        entry_date=entry_date,
        entry_type=entry_type,
        description=description,
        reference_type=reference_type,
        reference_id=reference_id,
        created_by_user_id=created_by_user_id,
        district_id=district_id,
        project_id=project_id,
        category=category,
        is_posted=True,
        posted_at=pk_now()
    )
    db.session.add(je)
    db.session.flush()  # Get the ID
    
    # Add lines
    total_debit = Decimal('0')
    total_credit = Decimal('0')
    
    for idx, line_data in enumerate(lines):
        debit = Decimal(str(line_data.get('debit', 0) or 0))
        credit = Decimal(str(line_data.get('credit', 0) or 0))
        
        line = JournalEntryLine(
            journal_entry_id=je.id,
            account_id=line_data['account_id'],
            debit=debit,
            credit=credit,
            description=line_data.get('description', ''),
            sort_order=idx
        )
        db.session.add(line)
        
        total_debit += debit
        total_credit += credit
    
    # Validate balanced entry
    if abs(total_debit - total_credit) > Decimal('0.01'):
        raise ValueError(f"Journal entry not balanced: Debit={total_debit}, Credit={total_credit}")
    
    db.session.flush()
    
    # Update account balances
    update_account_balances(je.id)
    
    return je


def update_account_balances(journal_entry_id):
    """
    Update account balances based on journal entry lines.
    
    For each account in the journal entry:
    - Asset/Expense accounts: increase on debit, decrease on credit
    - Liability/Equity/Revenue accounts: decrease on debit, increase on credit
    
    Args:
        journal_entry_id: ID of the journal entry
    """
    lines = JournalEntryLine.query.filter_by(journal_entry_id=journal_entry_id).all()

    for line in lines:
        # SELECT FOR UPDATE: row-level lock prevents concurrent balance corruption (B-05)
        account = db.session.query(Account).with_for_update().filter_by(id=line.account_id).first()
        if not account:
            continue
        
        debit = Decimal(str(line.debit or 0))
        credit = Decimal(str(line.credit or 0))
        
        # Calculate balance change based on account type
        if account.account_type in ['Asset', 'Expense']:
            # Normal debit balance accounts
            balance_change = debit - credit
        else:
            # Normal credit balance accounts (Liability, Equity, Revenue)
            balance_change = credit - debit
        
        account.current_balance = Decimal(str(account.current_balance or 0)) + balance_change
        db.session.add(account)


def get_account_balance(account_id, as_of_date=None):
    """
    Get account balance as of a specific date.
    
    Args:
        account_id: Account ID
        as_of_date: Date to calculate balance (default: today)
    
    Returns:
        Decimal: Account balance
    """
    account = Account.query.get(account_id)
    if not account:
        return Decimal('0')
    
    if as_of_date is None:
        # Return current balance
        return Decimal(str(account.current_balance or 0))
    
    # Calculate balance from journal entries up to as_of_date
    balance = Decimal(str(account.opening_balance or 0))
    
    lines = db.session.query(JournalEntryLine).join(JournalEntry).filter(
        JournalEntryLine.account_id == account_id,
        JournalEntry.entry_date <= as_of_date,
        JournalEntry.is_posted == True
    ).all()
    
    for line in lines:
        debit = Decimal(str(line.debit or 0))
        credit = Decimal(str(line.credit or 0))
        
        if account.account_type in ['Asset', 'Expense']:
            balance += debit - credit
        else:
            balance += credit - debit
    
    return balance


def get_account_ledger(account_id, from_date=None, to_date=None, category=None):
    """
    Get account ledger with all transactions and running balance.
    
    Args:
        account_id: Account ID
        from_date: Start date (optional)
        to_date: End date (optional)
        category: Single string or list of category strings (optional)
    
    Returns:
        dict with account, opening_balance, transactions, closing_balance
    """
    account = Account.query.get(account_id)
    if not account:
        return None
    
    if from_date:
        opening_balance = get_account_balance(account_id, from_date - timedelta(days=1))
    else:
        opening_balance = Decimal(str(account.opening_balance or 0))
    
    query = db.session.query(JournalEntryLine, JournalEntry).join(JournalEntry).filter(
        JournalEntryLine.account_id == account_id,
        JournalEntry.is_posted == True
    )
    
    if from_date:
        query = query.filter(JournalEntry.entry_date >= from_date)
    if to_date:
        query = query.filter(JournalEntry.entry_date <= to_date)
    if category:
        if isinstance(category, list):
            if len(category) == 1:
                query = query.filter(JournalEntry.category == category[0])
            else:
                query = query.filter(JournalEntry.category.in_(category))
        else:
            query = query.filter(JournalEntry.category == category)
    
    query = query.order_by(JournalEntry.entry_date, JournalEntry.id, JournalEntryLine.sort_order)
    
    results = query.all()

    je_ids = list({je.id for _, je in results})
    contra_map = {}
    if je_ids:
        contra_lines = db.session.query(
            JournalEntryLine.journal_entry_id,
            Account.code,
            Account.name
        ).join(Account).filter(
            JournalEntryLine.journal_entry_id.in_(je_ids),
            JournalEntryLine.account_id != account_id
        ).all()
        for jeid, code, name in contra_lines:
            if jeid not in contra_map:
                contra_map[jeid] = []
            contra_map[jeid].append(f"{code} - {name}")

    transactions = []
    running_balance = opening_balance
    
    for line, je in results:
        debit = Decimal(str(line.debit or 0))
        credit = Decimal(str(line.credit or 0))
        
        if account.account_type in ['Asset', 'Expense']:
            balance_change = debit - credit
        else:
            balance_change = credit - debit
        
        running_balance += balance_change

        contras = contra_map.get(je.id, [])
        contra_str = ', '.join(sorted(set(contras))) if contras else '-'
        
        transactions.append({
            'date': je.entry_date,
            'entry_number': je.entry_number,
            'entry_type': je.entry_type,
            'description': line.description or je.description,
            'category': je.category or '',
            'contra_account': contra_str,
            'debit': debit,
            'credit': credit,
            'balance': running_balance,
            'journal_entry_id': je.id
        })
    
    return {
        'account': account,
        'opening_balance': opening_balance,
        'transactions': transactions,
        'closing_balance': running_balance
    }


def get_dto_wallet_summary(district_id, project_id, from_date=None, to_date=None):
    """
    Get DTO wallet summary: balance + total payables.
    
    Args:
        district_id: District ID
        project_id: Project ID
        from_date: Start date (optional)
        to_date: End date (optional)
    
    Returns:
        dict: {
            'wallet_account': Account object,
            'wallet_balance': Decimal,
            'payables': List of dicts with party name and amount owed,
            'total_payables': Decimal,
            'available_balance': Decimal (wallet - payables)
        }
    """
    # Find DTO wallet account
    wallet = Account.query.filter_by(
        district_id=district_id,
        project_id=project_id,
        account_type='Asset'
    ).filter(Account.name.like('DTO Wallet%')).first()
    
    if not wallet:
        return None
    
    wallet_balance = get_account_balance(wallet.id, to_date)
    
    # Get all party ledger accounts (liabilities)
    party_accounts = Account.query.filter_by(account_type='Liability').filter(
        Account.name.like('Party Ledger%')
    ).all()
    
    payables = []
    total_payables = Decimal('0')
    
    for party_acc in party_accounts:
        # Check if this party has transactions with this DTO (district/project)
        has_transactions = db.session.query(JournalEntryLine).join(JournalEntry).filter(
            JournalEntryLine.account_id == party_acc.id,
            JournalEntry.district_id == district_id,
            JournalEntry.project_id == project_id,
            JournalEntry.is_posted == True
        ).first()
        
        if has_transactions:
            balance = get_account_balance(party_acc.id, to_date)
            if balance > 0:  # Positive balance = we owe them
                payables.append({
                    'party_name': party_acc.name.replace('Party Ledger - ', ''),
                    'account_id': party_acc.id,
                    'amount': balance
                })
                total_payables += balance
    
    return {
        'wallet_account': wallet,
        'wallet_balance': wallet_balance,
        'payables': payables,
        'total_payables': total_payables,
        'available_balance': wallet_balance - total_payables
    }


def create_payment_voucher_journal(payment_voucher):
    """
    Create journal entry for a payment voucher.
    
    Journal Entry:
        Debit: To Account (destination)
        Credit: From Account (source)
    
    Args:
        payment_voucher: PaymentVoucher object
    
    Returns:
        JournalEntry: Created journal entry
    """
    lines = [
        {
            'account_id': payment_voucher.to_account_id,
            'debit': payment_voucher.amount,
            'credit': 0,
            'description': f"Payment received - {payment_voucher.description or ''}"
        },
        {
            'account_id': payment_voucher.from_account_id,
            'debit': 0,
            'credit': payment_voucher.amount,
            'description': f"Payment made - {payment_voucher.description or ''}"
        }
    ]
    
    je = create_journal_entry(
        entry_type='Payment',
        entry_date=payment_voucher.payment_date,
        description=f"Payment Voucher {payment_voucher.voucher_number}",
        lines=lines,
        district_id=payment_voucher.district_id,
        project_id=payment_voucher.project_id,
        reference_type='PaymentVoucher',
        reference_id=payment_voucher.id,
        created_by_user_id=payment_voucher.created_by_user_id
    )
    
    return je


def create_receipt_voucher_journal(receipt_voucher):
    """
    Create journal entry for a receipt voucher.
    
    Journal Entry:
        Debit: To Account (destination - our account)
        Credit: From Account (source - party/other)
    
    Args:
        receipt_voucher: ReceiptVoucher object
    
    Returns:
        JournalEntry: Created journal entry
    """
    lines = [
        {
            'account_id': receipt_voucher.to_account_id,
            'debit': receipt_voucher.amount,
            'credit': 0,
            'description': f"Receipt received - {receipt_voucher.description or ''}"
        },
        {
            'account_id': receipt_voucher.from_account_id,
            'debit': 0,
            'credit': receipt_voucher.amount,
            'description': f"Receipt from - {receipt_voucher.description or ''}"
        }
    ]
    
    je = create_journal_entry(
        entry_type='Receipt',
        entry_date=receipt_voucher.receipt_date,
        description=f"Receipt Voucher {receipt_voucher.voucher_number}",
        lines=lines,
        reference_type='ReceiptVoucher',
        reference_id=receipt_voucher.id,
        created_by_user_id=receipt_voucher.created_by_user_id
    )
    
    return je


def create_bank_entry_journal(bank_entry):
    """
    Create journal entry for a bank entry (transfer).
    
    Journal Entry:
        Debit: To Account (destination)
        Credit: From Account (source)
    
    Args:
        bank_entry: BankEntry object
    
    Returns:
        JournalEntry: Created journal entry
    """
    lines = [
        {
            'account_id': bank_entry.to_account_id,
            'debit': bank_entry.amount,
            'credit': 0,
            'description': f"Transfer received - {bank_entry.description or ''}"
        },
        {
            'account_id': bank_entry.from_account_id,
            'debit': 0,
            'credit': bank_entry.amount,
            'description': f"Transfer sent - {bank_entry.description or ''}"
        }
    ]
    
    je = create_journal_entry(
        entry_type='Bank',
        entry_date=bank_entry.entry_date,
        description=f"Bank Entry {bank_entry.entry_number}",
        lines=lines,
        reference_type='BankEntry',
        reference_id=bank_entry.id,
        created_by_user_id=bank_entry.created_by_user_id
    )
    
    return je


def create_expense_journal(expense_type, expense_obj, expense_account_code, party_account_id):
    """
    Create journal entry for an expense (Fuel, Oil, Maintenance, Employee).
    
    Journal Entry:
        Debit: Expense Account (5110, 5120, 5130, etc.)
        Credit: Party Ledger (2110+) or Cash
    
    Args:
        expense_type: Type of expense (FuelExpense, OilExpense, etc.)
        expense_obj: Expense object with amount, date, etc.
        expense_account_code: Account code for expense (e.g., '5110' for Fuel)
        party_account_id: Party ledger account ID (or cash account)
    
    Returns:
        JournalEntry: Created journal entry
    """
    # Find expense account
    expense_account = Account.query.filter_by(code=expense_account_code).first()
    if not expense_account:
        raise ValueError(f"Expense account {expense_account_code} not found")
    
    # Get amount based on expense type
    if hasattr(expense_obj, 'amount'):
        amount = expense_obj.amount
    elif hasattr(expense_obj, 'total_amount'):
        amount = expense_obj.total_amount
    else:
        raise ValueError("Expense object has no amount field")
    
    # Get date
    if hasattr(expense_obj, 'expense_date'):
        expense_date = expense_obj.expense_date
    elif hasattr(expense_obj, 'fueling_date'):
        expense_date = expense_obj.fueling_date
    else:
        expense_date = pk_date()
    
    lines = [
        {
            'account_id': expense_account.id,
            'debit': amount,
            'credit': 0,
            'description': f"{expense_type} expense"
        },
        {
            'account_id': party_account_id,
            'debit': 0,
            'credit': amount,
            'description': f"Payable for {expense_type}"
        }
    ]
    
    je = create_journal_entry(
        entry_type='Expense',
        entry_date=expense_date,
        description=f"{expense_type} - {getattr(expense_obj, 'description', '')}",
        lines=lines,
        district_id=getattr(expense_obj, 'district_id', None),
        project_id=getattr(expense_obj, 'project_id', None),
        reference_type=expense_type,
        reference_id=expense_obj.id,
        created_by_user_id=getattr(expense_obj, 'created_by_user_id', None)
    )
    
    return je


def ensure_wallet_account(person_type, person_id):
    """
    Ensure the entity (employee/driver/party/company) has a wallet Account.
    If not, auto-create one under the appropriate CoA parent head.
    Supported person_types: 'employee'/'emp', 'driver'/'drv', 'party'/'pty', 'company'/'com', 'acct'.
    """
    if person_type == 'acct':
        acct = Account.query.get(person_id)
        if not acct:
            raise ValueError(f"Account {person_id} not found")
        return acct

    _type_map = {'emp': 'employee', 'drv': 'driver', 'pty': 'party', 'com': 'company'}
    ptype = _type_map.get(person_type, person_type)

    if ptype == 'employee':
        person = Employee.query.get(person_id)
        if not person:
            raise ValueError(f"Employee {person_id} not found")
        if person.wallet_account_id:
            acct = Account.query.get(person.wallet_account_id)
            if acct:
                return acct
    elif ptype == 'driver':
        person = Driver.query.get(person_id)
        if not person:
            raise ValueError(f"Driver {person_id} not found")
        if person.wallet_account_id:
            acct = Account.query.get(person.wallet_account_id)
            if acct:
                return acct
    elif ptype == 'party':
        person = Party.query.get(person_id)
        if not person:
            raise ValueError(f"Party {person_id} not found")
        existing = Account.query.filter_by(entity_type='party', entity_id=person_id).first()
        if existing:
            return existing
    elif ptype == 'company':
        person = Company.query.get(person_id)
        if not person:
            raise ValueError(f"Company {person_id} not found")
        existing = Account.query.filter_by(entity_type='company', entity_id=person_id).first()
        if existing:
            return existing
    else:
        raise ValueError(f"Unknown person_type: {person_type}")

    _parent_codes = {
        'driver': '6000', 'employee': '6500',
        'party': '7000', 'company': '8000',
    }
    _labels = {
        'driver': 'DRV', 'employee': 'EMP',
        'party': 'PTY', 'company': 'COM',
    }
    parent_code = _parent_codes[ptype]
    parent = Account.query.filter_by(code=parent_code).first()
    parent_id = parent.id if parent else None
    code_prefix = parent_code
    code_end = str(int(parent_code) + 999)
    max_code_row = db.session.query(db.func.max(Account.code)).filter(
        Account.code.between(code_prefix, code_end)
    ).scalar()
    next_code = str(int(max_code_row) + 1) if max_code_row and max_code_row >= code_prefix else str(int(code_prefix) + 1)

    label = _labels[ptype]
    wallet = Account(
        code=next_code,
        name=f"{person.name} ({label}-{person.id})",
        account_type=parent.account_type if parent else 'Asset',
        parent_id=parent_id,
        is_active=True,
        opening_balance=0,
        current_balance=0,
        description=f"Auto-created wallet for {person.name}",
        entity_type=ptype,
        entity_id=person_id,
    )
    db.session.add(wallet)
    db.session.flush()

    if ptype in ('employee', 'driver') and hasattr(person, 'wallet_account_id'):
        person.wallet_account_id = wallet.id
        db.session.flush()
    return wallet


def _ensure_salary_expense_account(transfer_obj):
    """Return the correct salary expense account based on receiver type.
    Driver → 5401 (Driver Salaries), Employee → 5402 (Employee Salaries)."""
    if transfer_obj.to_driver_id:
        code, name, parent_code = '5401', 'Driver Salaries', '5400'
    else:
        code, name, parent_code = '5402', 'Employee Salaries', '5400'

    acct = Account.query.filter_by(code=code).first()
    if acct:
        return acct

    parent = Account.query.filter_by(code=parent_code).first()
    if not parent:
        parent = Account.query.filter_by(code='5000').first()
    acct = Account(
        code=code, name=name, account_type='Expense',
        parent_id=parent.id if parent else None,
        is_active=True, opening_balance=0, current_balance=0,
        description=f'{name} – auto-created')
    db.session.add(acct)
    db.session.flush()
    return acct


def create_fund_transfer_journal(transfer_obj, from_wallet, to_wallet):
    """Create journal entry for a fund transfer: Debit receiver wallet, Credit sender wallet.
    If is_salary is True, add neutralizing lines so receiver balance stays zero
    and the salary expense (5401/5402) is recorded."""
    user_desc = (transfer_obj.description or '').strip()
    recv_desc = user_desc or f"Fund received from {transfer_obj.from_name}"
    send_desc = user_desc or f"Fund sent to {transfer_obj.to_name}"

    lines = [
        {'account_id': to_wallet.id, 'debit': transfer_obj.amount, 'credit': 0,
         'description': recv_desc},
        {'account_id': from_wallet.id, 'debit': 0, 'credit': transfer_obj.amount,
         'description': send_desc},
    ]

    if getattr(transfer_obj, 'is_salary', False):
        salary_expense = _ensure_salary_expense_account(transfer_obj)
        sal_desc = user_desc or f"Salary paid to {transfer_obj.to_name}"

        lines.extend([
            {'account_id': to_wallet.id, 'debit': 0, 'credit': transfer_obj.amount,
             'description': sal_desc},
            {'account_id': salary_expense.id, 'debit': transfer_obj.amount, 'credit': 0,
             'description': sal_desc},
        ])

    desc = f"Fund Transfer {transfer_obj.transfer_number}"
    if getattr(transfer_obj, 'is_salary', False):
        desc = f"Salary Transfer {transfer_obj.transfer_number}"

    return create_journal_entry(
        entry_type='Journal',
        entry_date=transfer_obj.transfer_date,
        description=desc,
        lines=lines,
        district_id=transfer_obj.district_id,
        project_id=transfer_obj.project_id,
        reference_type='FundTransfer',
        reference_id=transfer_obj.id,
        created_by_user_id=transfer_obj.created_by_user_id,
        category=getattr(transfer_obj, 'category', None),
    )


# ════════════════════════════════════════════════════════════════════════════════
# EMPLOYEE FINANCIAL WORKSPACE (isolated ledger)
# ════════════════════════════════════════════════════════════════════════════════
def workspace_generate_entry_number(prefix, entry_date, employee_id):
    base = generate_entry_number(prefix, entry_date)
    return f"{base}-E{employee_id}"


def ensure_workspace_base_accounts(employee_id):
    employee = Employee.query.get(employee_id)
    if not employee:
        raise ValueError("Selected employee not found")

    required = [
        ("1000", "Workspace Assets", "Asset", None, "asset_root"),
        ("1100", "Workspace Cash", "Asset", "1000", "cash"),
        ("1110", "HBL Bank", "Asset", "1000", "bank_hbl"),
        ("1120", "Easypaisa", "Asset", "1000", "bank_easypaisa"),
        ("1130", "JazzCash", "Asset", "1000", "bank_jazzcash"),
        ("2000", "Workspace Liabilities", "Liability", None, "liability_root"),
        ("2300", "Company Funding", "Liability", "2000", "company_funding"),
        ("2310", "Transfer Clearing", "Liability", "2000", "transfer_clearing"),
        ("5000", "Workspace Expenses", "Expense", None, "expense_root"),
        ("5100", "General Expense", "Expense", "5000", "general_expense"),
        ("5400", "Salary Expense", "Expense", "5000", "salary_expense"),
    ]

    existing = {
        a.code: a for a in WorkspaceAccount.query.filter_by(employee_id=employee_id).all()
    }
    for code, name, acc_type, parent_code, entity_type in required:
        if code in existing:
            continue
        parent_id = existing[parent_code].id if parent_code and parent_code in existing else None
        row = WorkspaceAccount(
            employee_id=employee_id,
            code=code,
            name=name,
            account_type=acc_type,
            parent_id=parent_id,
            is_active=True,
            opening_balance=0,
            current_balance=0,
            entity_type=entity_type,
            description=f"Default workspace account for {employee.name}",
        )
        db.session.add(row)
        db.session.flush()
        existing[code] = row
    return existing


def ensure_workspace_opening_expense_accounts(employee_id):
    """Create dedicated opening-expense heads under 5100 if missing."""
    existing = ensure_workspace_base_accounts(employee_id)
    mapping = {
        'opening_fueling': ('5111', 'Opening Fueling Expense'),
        'opening_oil': ('5112', 'Opening Oil Change Expense'),
        'opening_maintenance': ('5113', 'Opening Maintenance Expense'),
        'opening_employee': ('5114', 'Opening Employee Expense'),
    }
    parent = existing.get('5100')
    for _key, (code, name) in mapping.items():
        if code in existing:
            continue
        row = WorkspaceAccount(
            employee_id=employee_id,
            code=code,
            name=name,
            account_type='Expense',
            parent_id=parent.id if parent else None,
            is_active=True,
            opening_balance=0,
            current_balance=0,
            entity_type='opening_expense_head',
            description='Dedicated opening expense head',
        )
        db.session.add(row)
        db.session.flush()
        existing[code] = row
    return {
        'fueling': existing.get('5111'),
        'oil': existing.get('5112'),
        'maintenance': existing.get('5113'),
        'employee': existing.get('5114'),
        'company_funding': existing.get('2300'),
    }


def ensure_workspace_fuel_oil_opening_accounts(employee_id):
    """Create dedicated fuel/oil opening heads under 5100 if missing."""
    existing = ensure_workspace_base_accounts(employee_id)
    mapping = {
        'pump_fuel': ('5115', 'Opening Pump Card Fueling'),
        'credit_fuel': ('5116', 'Opening Credit Fueling'),
        'card_oil': ('5117', 'Opening Card Oil Change'),
        'credit_oil': ('5118', 'Opening Credit Oil Change'),
    }
    parent = existing.get('5100')
    for _key, (code, name) in mapping.items():
        if code in existing:
            continue
        row = WorkspaceAccount(
            employee_id=employee_id,
            code=code,
            name=name,
            account_type='Expense',
            parent_id=parent.id if parent else None,
            is_active=True,
            opening_balance=0,
            current_balance=0,
            entity_type='fuel_oil_opening_head',
            description='Dedicated opening fuel/oil expense head',
        )
        db.session.add(row)
        db.session.flush()
        existing[code] = row
    return {
        'pump_fuel': existing.get('5115'),
        'credit_fuel': existing.get('5116'),
        'card_oil': existing.get('5117'),
        'credit_oil': existing.get('5118'),
        'company_funding': existing.get('2300'),
    }


def ensure_workspace_counterparty_account(employee_id, *, party_id=None, driver_id=None):
    ensure_workspace_base_accounts(employee_id)
    if party_id:
        code = f"210{party_id}"
        existing = WorkspaceAccount.query.filter_by(employee_id=employee_id, entity_type='party', entity_id=party_id).first()
        party = WorkspaceParty.query.filter_by(employee_id=employee_id, id=party_id).first()
        if not party:
            # Backward-compatible fallback for old callers that pass master Party id.
            party = Party.query.get(party_id)
        if not party:
            raise ValueError("Party not found")
        parent = WorkspaceAccount.query.filter_by(employee_id=employee_id, code='1000').first()
        if existing:
            existing.name = f"Party - {party.name}"
            existing.is_active = bool(getattr(party, 'is_active', True))
            if parent and not existing.parent_id:
                existing.parent_id = parent.id
            db.session.flush()
            return existing
        candidate_code = code
        seq = 1
        while WorkspaceAccount.query.filter_by(employee_id=employee_id, code=candidate_code).first():
            candidate_code = f"{code}{seq}"
            seq += 1
        row = WorkspaceAccount(
            employee_id=employee_id,
            code=candidate_code,
            name=f"Party - {party.name}",
            account_type='Asset',
            parent_id=parent.id if parent else None,
            is_active=bool(getattr(party, 'is_active', True)),
            opening_balance=0,
            current_balance=0,
            entity_type='party',
            entity_id=party_id,
            description='Workspace counterparty account',
        )
        db.session.add(row)
        db.session.flush()
        return row
    if driver_id:
        code = f"220{driver_id}"
        existing = WorkspaceAccount.query.filter_by(employee_id=employee_id, entity_type='driver', entity_id=driver_id).first()
        if existing:
            return existing
        driver = Driver.query.get(driver_id)
        if not driver:
            raise ValueError("Driver not found")
        row = WorkspaceAccount(
            employee_id=employee_id,
            code=code,
            name=f"Driver - {driver.name}",
            account_type='Asset',
            parent_id=WorkspaceAccount.query.filter_by(employee_id=employee_id, code='1000').first().id,
            is_active=True,
            opening_balance=0,
            current_balance=0,
            entity_type='driver',
            entity_id=driver_id,
            description='Workspace counterparty account',
        )
        db.session.add(row)
        db.session.flush()
        return row
    raise ValueError("party_id or driver_id is required")


def workspace_create_journal_entry(employee_id, entry_type, entry_date, description, lines,
                                   reference_type=None, reference_id=None, created_by_user_id=None, category=None):
    entry_number = workspace_generate_entry_number('WJ', entry_date, employee_id)
    je = WorkspaceJournalEntry(
        employee_id=employee_id,
        entry_number=entry_number,
        entry_date=entry_date,
        entry_type=entry_type,
        description=description,
        reference_type=reference_type,
        reference_id=reference_id,
        category=category,
        is_posted=True,
        posted_at=pk_now(),
        created_by_user_id=created_by_user_id,
    )
    db.session.add(je)
    db.session.flush()

    total_debit = Decimal("0")
    total_credit = Decimal("0")
    for idx, line_data in enumerate(lines):
        debit = Decimal(str(line_data.get('debit', 0) or 0))
        credit = Decimal(str(line_data.get('credit', 0) or 0))
        db.session.add(WorkspaceJournalEntryLine(
            journal_entry_id=je.id,
            account_id=line_data['account_id'],
            debit=debit,
            credit=credit,
            description=line_data.get('description') or '',
            sort_order=idx,
        ))
        total_debit += debit
        total_credit += credit

    if abs(total_debit - total_credit) > Decimal('0.01'):
        raise ValueError("Workspace journal entry not balanced")

    db.session.flush()
    workspace_update_account_balances(je.id)
    return je


def workspace_update_account_balances(journal_entry_id):
    lines = WorkspaceJournalEntryLine.query.filter_by(journal_entry_id=journal_entry_id).all()
    for line in lines:
        account = db.session.query(WorkspaceAccount).with_for_update().filter_by(id=line.account_id).first()
        if not account:
            continue
        debit = Decimal(str(line.debit or 0))
        credit = Decimal(str(line.credit or 0))
        if account.account_type in ['Asset', 'Expense']:
            delta = debit - credit
        else:
            delta = credit - debit
        account.current_balance = Decimal(str(account.current_balance or 0)) + delta
        db.session.add(account)


def workspace_reverse_journal_entry(journal_entry_id):
    if not journal_entry_id:
        return
    lines = WorkspaceJournalEntryLine.query.filter_by(journal_entry_id=journal_entry_id).all()
    for line in lines:
        account = db.session.query(WorkspaceAccount).with_for_update().filter_by(id=line.account_id).first()
        if not account:
            continue
        debit = Decimal(str(line.debit or 0))
        credit = Decimal(str(line.credit or 0))
        if account.account_type in ['Asset', 'Expense']:
            delta = debit - credit
        else:
            delta = credit - debit
        account.current_balance = Decimal(str(account.current_balance or 0)) - delta
        db.session.add(account)
    WorkspaceExpense.query.filter_by(journal_entry_id=journal_entry_id).update(
        {'journal_entry_id': None}, synchronize_session='fetch'
    )
    WorkspaceOpeningExpense.query.filter_by(journal_entry_id=journal_entry_id).update(
        {'journal_entry_id': None}, synchronize_session='fetch'
    )
    WorkspaceFuelOilOpeningExpense.query.filter_by(journal_entry_id=journal_entry_id).update(
        {'journal_entry_id': None}, synchronize_session='fetch'
    )
    WorkspaceMonthClose.query.filter_by(workspace_journal_entry_id=journal_entry_id).update(
        {'workspace_journal_entry_id': None}, synchronize_session='fetch'
    )
    WorkspaceFundTransfer.query.filter_by(journal_entry_id=journal_entry_id).update(
        {'journal_entry_id': None}, synchronize_session='fetch'
    )
    je = WorkspaceJournalEntry.query.get(journal_entry_id)
    if je:
        db.session.delete(je)


def reverse_company_journal_entry(journal_entry_id):
    """Reverse account balances and delete a posted company journal entry."""
    if not journal_entry_id:
        return
    lines = JournalEntryLine.query.filter_by(journal_entry_id=journal_entry_id).all()
    for line in lines:
        account = db.session.query(Account).with_for_update().filter_by(id=line.account_id).first()
        if not account:
            continue
        debit = Decimal(str(line.debit or 0))
        credit = Decimal(str(line.credit or 0))
        if account.account_type in ['Asset', 'Expense']:
            delta = debit - credit
        else:
            delta = credit - debit
        account.current_balance = Decimal(str(account.current_balance or 0)) - delta
        db.session.add(account)
    je = JournalEntry.query.get(journal_entry_id)
    if je:
        db.session.delete(je)


def workspace_get_account_ledger(account_id, from_date=None, to_date=None, category=None):
    account = WorkspaceAccount.query.get(account_id)
    if not account:
        return None
    opening_balance = Decimal(str(account.opening_balance or 0))
    q = db.session.query(WorkspaceJournalEntryLine, WorkspaceJournalEntry).join(WorkspaceJournalEntry).filter(
        WorkspaceJournalEntryLine.account_id == account_id,
        WorkspaceJournalEntry.is_posted == True,
    )
    if from_date:
        q = q.filter(WorkspaceJournalEntry.entry_date >= from_date)
    if to_date:
        q = q.filter(WorkspaceJournalEntry.entry_date <= to_date)
    if category:
        q = q.filter(WorkspaceJournalEntry.category == category)
    q = q.order_by(WorkspaceJournalEntry.entry_date.asc(), WorkspaceJournalEntry.id.asc(), WorkspaceJournalEntryLine.sort_order.asc())

    tx = []
    running = opening_balance
    for line, je in q.all():
        debit = Decimal(str(line.debit or 0))
        credit = Decimal(str(line.credit or 0))
        running += (debit - credit) if account.account_type in ['Asset', 'Expense'] else (credit - debit)
        tx.append({
            'journal_entry_id': je.id,
            'date': je.entry_date,
            'entry_number': je.entry_number,
            'entry_type': je.entry_type,
            'description': line.description or je.description,
            'category': je.category or '',
            'reference_type': je.reference_type or '',
            'reference_id': je.reference_id,
            'debit': debit,
            'credit': credit,
            'balance': running,
        })

    return {
        'account': account,
        'opening_balance': opening_balance,
        'transactions': tx,
        'closing_balance': running,
    }


def workspace_post_expense(expense_obj, cash_account_id, expense_account_id):
    lines = [
        {
            'account_id': expense_account_id,
            'debit': expense_obj.amount,
            'credit': 0,
            'description': f"{expense_obj.expense_type} expense",
        },
        {
            'account_id': cash_account_id,
            'debit': 0,
            'credit': expense_obj.amount,
            'description': "Cash out",
        },
    ]
    return workspace_create_journal_entry(
        employee_id=expense_obj.employee_id,
        entry_type='Expense',
        entry_date=expense_obj.expense_date,
        description=expense_obj.description,
        lines=lines,
        reference_type='WorkspaceExpense',
        reference_id=expense_obj.id,
        created_by_user_id=expense_obj.created_by_user_id,
        category=expense_obj.category,
    )


def workspace_post_transfer(transfer_obj):
    lines = [
        {
            'account_id': transfer_obj.to_account_id,
            'debit': transfer_obj.amount,
            'credit': 0,
            'description': f"Transfer received - {transfer_obj.description or ''}",
        },
        {
            'account_id': transfer_obj.from_account_id,
            'debit': 0,
            'credit': transfer_obj.amount,
            'description': f"Transfer paid - {transfer_obj.description or ''}",
        },
    ]
    return workspace_create_journal_entry(
        employee_id=transfer_obj.employee_id,
        entry_type='Transfer',
        entry_date=transfer_obj.transfer_date,
        description=transfer_obj.description or f"Workspace Transfer {transfer_obj.transfer_number}",
        lines=lines,
        reference_type='WorkspaceFundTransfer',
        reference_id=transfer_obj.id,
        created_by_user_id=transfer_obj.created_by_user_id,
        category=transfer_obj.category,
    )


def workspace_post_opening_expense(opening_obj):
    """Post opening breakup to dedicated workspace expense heads."""
    heads = ensure_workspace_opening_expense_accounts(opening_obj.employee_id)
    if not heads.get('company_funding'):
        raise ValueError("Workspace Company Funding account not found")

    fueling = Decimal(str(opening_obj.fueling_expense or 0))
    oil = Decimal(str(opening_obj.oil_change_expense or 0))
    maintenance = Decimal(str(opening_obj.maintenance_expense or 0))
    emp_exp = Decimal(str(opening_obj.employee_expense or 0))
    total = fueling + oil + maintenance + emp_exp
    if total <= Decimal("0"):
        raise ValueError("Opening total must be greater than zero")

    lines = []
    if fueling > 0 and heads.get('fueling'):
        lines.append({'account_id': heads['fueling'].id, 'debit': fueling, 'credit': 0, 'description': 'Opening Fueling Expense'})
    if oil > 0 and heads.get('oil'):
        lines.append({'account_id': heads['oil'].id, 'debit': oil, 'credit': 0, 'description': 'Opening Oil Change Expense'})
    if maintenance > 0 and heads.get('maintenance'):
        lines.append({'account_id': heads['maintenance'].id, 'debit': maintenance, 'credit': 0, 'description': 'Opening Maintenance Expense'})
    if emp_exp > 0 and heads.get('employee'):
        lines.append({'account_id': heads['employee'].id, 'debit': emp_exp, 'credit': 0, 'description': 'Opening Employee Expense'})
    lines.append({'account_id': heads['company_funding'].id, 'debit': 0, 'credit': total, 'description': 'Opening Expense funded by company'})

    return workspace_create_journal_entry(
        employee_id=opening_obj.employee_id,
        entry_type='Expense',
        entry_date=opening_obj.opening_date,
        description=opening_obj.remarks or f"Opening Expense {opening_obj.opening_date:%d-%m-%Y}",
        lines=lines,
        reference_type='WorkspaceOpeningExpense',
        reference_id=opening_obj.id,
        created_by_user_id=opening_obj.created_by_user_id,
        category='Opening',
    )


def workspace_post_fuel_oil_opening_expense(opening_obj):
    """Post fuel/oil opening breakup to dedicated workspace expense heads."""
    heads = ensure_workspace_fuel_oil_opening_accounts(opening_obj.employee_id)
    if not heads.get('company_funding'):
        raise ValueError("Workspace Company Funding account not found")

    pump_fuel = Decimal(str(opening_obj.pump_card_fueling or 0))
    credit_fuel = Decimal(str(opening_obj.credit_fueling or 0))
    card_oil = Decimal(str(opening_obj.card_oil_change or 0))
    credit_oil = Decimal(str(opening_obj.credit_oil_change or 0))
    total = pump_fuel + credit_fuel + card_oil + credit_oil
    if total <= Decimal("0"):
        raise ValueError("Opening total must be greater than zero")

    lines = []
    if pump_fuel > 0 and heads.get('pump_fuel'):
        lines.append({'account_id': heads['pump_fuel'].id, 'debit': pump_fuel, 'credit': 0, 'description': 'Opening Pump Card Fueling'})
    if credit_fuel > 0 and heads.get('credit_fuel'):
        lines.append({'account_id': heads['credit_fuel'].id, 'debit': credit_fuel, 'credit': 0, 'description': 'Opening Credit Fueling'})
    if card_oil > 0 and heads.get('card_oil'):
        lines.append({'account_id': heads['card_oil'].id, 'debit': card_oil, 'credit': 0, 'description': 'Opening Card Oil Change'})
    if credit_oil > 0 and heads.get('credit_oil'):
        lines.append({'account_id': heads['credit_oil'].id, 'debit': credit_oil, 'credit': 0, 'description': 'Opening Credit Oil Change'})
    lines.append({'account_id': heads['company_funding'].id, 'debit': 0, 'credit': total, 'description': 'Opening Fuel/Oil funded by company'})

    return workspace_create_journal_entry(
        employee_id=opening_obj.employee_id,
        entry_type='Expense',
        entry_date=opening_obj.opening_date,
        description=opening_obj.remarks or f"Fuel/Oil Opening {opening_obj.opening_date:%d-%m-%Y}",
        lines=lines,
        reference_type='WorkspaceFuelOilOpeningExpense',
        reference_id=opening_obj.id,
        created_by_user_id=opening_obj.created_by_user_id,
        category='Opening',
    )


def _ensure_company_expense_head(code, name, parent_code='5000'):
    row = Account.query.filter_by(code=code).first()
    if row:
        return row
    parent = Account.query.filter_by(code=parent_code).first()
    row = Account(
        code=code,
        name=name,
        account_type='Expense',
        parent_id=parent.id if parent else None,
        is_active=True,
        opening_balance=0,
        current_balance=0,
        description=f'Auto-created expense head ({name})',
    )
    db.session.add(row)
    db.session.flush()
    return row


def _company_expense_account_for_category(category_key, fallback_account_id=None):
    key = (category_key or '').strip().lower()
    if key == 'fuel':
        return _ensure_company_expense_head('5100', 'Fuel Expenses')
    if key == 'oil':
        return _ensure_company_expense_head('5200', 'Oil Expenses')
    if key == 'maintenance':
        return _ensure_company_expense_head('5300', 'Maintenance Expenses')
    if key == 'employee':
        # Keep employee month-close postings under operational group (5500).
        return _ensure_company_expense_head('5510', 'Employee Expenses', parent_code='5500')
    if fallback_account_id:
        return Account.query.get(fallback_account_id)
    return _ensure_company_expense_head('5500', 'Operational Expenses')


def _map_workspace_expense_category(exp_obj):
    txt = ((exp_obj.category or '') + ' ' + (exp_obj.expense_type or '')).lower()
    if 'fuel' in txt:
        return 'fuel'
    if 'oil' in txt:
        return 'oil'
    if 'maint' in txt:
        return 'maintenance'
    if 'employee' in txt or 'salary' in txt:
        return 'employee'
    return 'other'


def reconcile_workspace_opening_expense_postings(employee_id):
    """
    Keep opening postings consistent with latest policy:
    - backfill missing journals
    - migrate legacy cash-credit journals to Company Funding credit
    """
    ensure_workspace_base_accounts(employee_id)
    accounts = WorkspaceAccount.query.filter_by(employee_id=employee_id).all()
    by_code = {a.code: a for a in accounts}
    cash_id = by_code.get('1100').id if by_code.get('1100') else None
    company_funding = by_code.get('2300')

    rows = WorkspaceOpeningExpense.query.filter(
        WorkspaceOpeningExpense.employee_id == employee_id,
        WorkspaceOpeningExpense.journal_entry_id.is_(None),
        WorkspaceOpeningExpense.total_expense > 0,
    ).all()
    created = 0
    for row in rows:
        je = workspace_post_opening_expense(row)
        row.journal_entry_id = je.id
        created += 1

    migrated = 0
    if company_funding and cash_id:
        posted_rows = WorkspaceOpeningExpense.query.filter(
            WorkspaceOpeningExpense.employee_id == employee_id,
            WorkspaceOpeningExpense.journal_entry_id.isnot(None),
            WorkspaceOpeningExpense.total_expense > 0,
        ).all()
        for row in posted_rows:
            je = WorkspaceJournalEntry.query.get(row.journal_entry_id)
            if not je:
                continue
            has_cash_credit = WorkspaceJournalEntryLine.query.filter_by(
                journal_entry_id=je.id,
                account_id=cash_id,
            ).filter(WorkspaceJournalEntryLine.credit > 0).first() is not None
            if not has_cash_credit:
                continue
            workspace_reverse_journal_entry(je.id)
            row.journal_entry_id = None
            rebuilt = workspace_post_opening_expense(row)
            row.journal_entry_id = rebuilt.id
            migrated += 1

        fuel_oil_rows = WorkspaceFuelOilOpeningExpense.query.filter(
            WorkspaceFuelOilOpeningExpense.employee_id == employee_id,
            WorkspaceFuelOilOpeningExpense.journal_entry_id.isnot(None),
            WorkspaceFuelOilOpeningExpense.total_amount > 0,
        ).all()
        for row in fuel_oil_rows:
            je = WorkspaceJournalEntry.query.get(row.journal_entry_id)
            if not je:
                continue
            has_cash_credit = WorkspaceJournalEntryLine.query.filter_by(
                journal_entry_id=je.id,
                account_id=cash_id,
            ).filter(WorkspaceJournalEntryLine.credit > 0).first() is not None
            if not has_cash_credit:
                continue
            workspace_reverse_journal_entry(je.id)
            row.journal_entry_id = None
            rebuilt = workspace_post_fuel_oil_opening_expense(row)
            row.journal_entry_id = rebuilt.id
            migrated += 1
    return created + migrated


def workspace_close_month(employee_id, period_start, period_end, company_account_id, user_id, notes='',
                         district_id=None, project_id=None, district_name=None, project_name=None):
    ensure_workspace_base_accounts(employee_id)
    expenses_q = WorkspaceExpense.query.filter(
        WorkspaceExpense.employee_id == employee_id,
        WorkspaceExpense.month_close_id.is_(None),
        WorkspaceExpense.expense_date >= period_start,
        WorkspaceExpense.expense_date <= period_end,
    )
    # WorkspaceExpense legacy model may not carry district/project columns.
    # Guard these filters to avoid runtime attribute errors on older schemas/models.
    has_exp_dist = hasattr(WorkspaceExpense, "district_id")
    has_exp_proj = hasattr(WorkspaceExpense, "project_id")
    if district_id and has_exp_dist:
        expenses_q = expenses_q.filter(getattr(WorkspaceExpense, "district_id") == district_id)
    if project_id and has_exp_proj:
        expenses_q = expenses_q.filter(getattr(WorkspaceExpense, "project_id") == project_id)
    # If scope is selected but legacy rows are not scopeable, exclude them from scoped close.
    if (district_id or project_id) and not (has_exp_dist and has_exp_proj):
        expenses = []
    else:
        expenses = expenses_q.all()

    opening_q = WorkspaceOpeningExpense.query.filter(
        WorkspaceOpeningExpense.employee_id == employee_id,
        WorkspaceOpeningExpense.month_close_id.is_(None),
        WorkspaceOpeningExpense.opening_date >= period_start,
        WorkspaceOpeningExpense.opening_date <= period_end,
    )
    if district_id:
        opening_q = opening_q.filter(WorkspaceOpeningExpense.district_id == district_id)
    if project_id:
        opening_q = opening_q.filter(WorkspaceOpeningExpense.project_id == project_id)
    opening_expenses = opening_q.all()
    total_regular = sum(Decimal(str(e.amount or 0)) for e in expenses)
    total_opening = sum(Decimal(str(e.total_expense or 0)) for e in opening_expenses)
    total = total_regular + total_opening
    if total <= Decimal("0"):
        raise ValueError("No unclosed workspace/opening expense found in selected period")

    employee = Employee.query.get(employee_id)
    if not employee:
        raise ValueError("Employee not found")
    if not employee.wallet_account_id:
        raise ValueError("Employee company wallet account is not configured")
    company_wallet = Account.query.get(employee.wallet_account_id)
    expense_head = WorkspaceAccount.query.filter_by(employee_id=employee_id, code='5100').first()
    if not expense_head:
        raise ValueError("Workspace base accounts are missing")

    close_row = WorkspaceMonthClose(
        employee_id=employee_id,
        district_id=district_id,
        project_id=project_id,
        period_start=period_start,
        period_end=period_end,
        status='Closed',
        total_expense=total,
        workspace_expense_account_id=expense_head.id,
        company_account_id=company_account_id,
        closed_by_user_id=user_id,
        closed_at=pk_now(),
        notes=notes or None,
    )
    db.session.add(close_row)
    db.session.flush()

    debit_bucket = {}
    for exp in expenses:
        amt = Decimal(str(exp.amount or 0))
        if amt <= 0:
            continue
        cat = _map_workspace_expense_category(exp)
        acct = _company_expense_account_for_category(cat, fallback_account_id=company_account_id)
        if acct:
            debit_bucket[acct.id] = debit_bucket.get(acct.id, Decimal('0')) + amt

    for opn in opening_expenses:
        mapping = [
            ('fuel', Decimal(str(opn.fueling_expense or 0))),
            ('oil', Decimal(str(opn.oil_change_expense or 0))),
            ('maintenance', Decimal(str(opn.maintenance_expense or 0))),
            ('employee', Decimal(str(opn.employee_expense or 0))),
        ]
        for cat, amt in mapping:
            if amt <= 0:
                continue
            acct = _company_expense_account_for_category(cat, fallback_account_id=company_account_id)
            if acct:
                debit_bucket[acct.id] = debit_bucket.get(acct.id, Decimal('0')) + amt
    period_label = f"{period_start.day}-{period_end.day}({period_end.strftime('%b-%y')})"
    scope_label = f"District: {district_name or '-'} | Project: {project_name or '-'}"
    company_lines = []
    for acct_id, amt in debit_bucket.items():
        company_lines.append({
            'account_id': acct_id,
            'debit': amt,
            'credit': 0,
            'description': f'Workspace month close expense - {employee.name} | Period: {period_label} | {scope_label}',
        })
    company_lines.append({
        'account_id': company_wallet.id,
        'debit': 0,
        'credit': total,
        'description': f'Workspace settlement against employee wallet - {employee.name} | Period: {period_label} | {scope_label}',
    })
    company_je = create_journal_entry(
        entry_type='Journal',
        entry_date=period_end,
        description=f"Workspace month close {employee.name} ({period_start:%m/%Y}) [{scope_label}]",
        lines=company_lines,
        district_id=district_id,
        project_id=project_id,
        reference_type='WorkspaceMonthClose',
        reference_id=close_row.id,
        created_by_user_id=user_id,
        category='Workspace Close',
    )
    close_row.company_journal_entry_id = company_je.id

    for exp in expenses:
        exp.month_close_id = close_row.id
    for opn in opening_expenses:
        opn.month_close_id = close_row.id

    return close_row


def workspace_close_fuel_oil_month(employee_id, period_start, period_end, company_account_id, user_id, notes='',
                                   district_id=None, project_id=None, district_name=None, project_name=None):
    rows_q = WorkspaceFuelOilOpeningExpense.query.filter(
        WorkspaceFuelOilOpeningExpense.employee_id == employee_id,
        WorkspaceFuelOilOpeningExpense.fuel_oil_month_close_id.is_(None),
        WorkspaceFuelOilOpeningExpense.opening_date >= period_start,
        WorkspaceFuelOilOpeningExpense.opening_date <= period_end,
    )
    if district_id:
        rows_q = rows_q.filter(WorkspaceFuelOilOpeningExpense.district_id == district_id)
    if project_id:
        rows_q = rows_q.filter(WorkspaceFuelOilOpeningExpense.project_id == project_id)
    rows = rows_q.all()

    total = sum(Decimal(str(r.total_amount or 0)) for r in rows)
    if total <= Decimal("0"):
        raise ValueError("No unclosed fuel/oil opening found in selected period")

    employee = Employee.query.get(employee_id)
    if not employee:
        raise ValueError("Employee not found")
    if not employee.wallet_account_id:
        raise ValueError("Employee company wallet account is not configured")
    company_wallet = Account.query.get(employee.wallet_account_id)

    close_row = WorkspaceFuelOilMonthClose(
        employee_id=employee_id,
        district_id=district_id,
        project_id=project_id,
        period_start=period_start,
        period_end=period_end,
        status='Closed',
        total_amount=total,
        company_account_id=company_account_id,
        closed_by_user_id=user_id,
        closed_at=pk_now(),
        notes=notes or None,
    )
    db.session.add(close_row)
    db.session.flush()

    debit_bucket = {}
    for row in rows:
        mapping = [
            ('fuel', Decimal(str(row.total_fueling or 0))),
            ('oil', Decimal(str(row.total_oil_change or 0))),
        ]
        for cat, amt in mapping:
            if amt <= 0:
                continue
            acct = _company_expense_account_for_category(cat, fallback_account_id=company_account_id)
            if acct:
                debit_bucket[acct.id] = debit_bucket.get(acct.id, Decimal('0')) + amt

    period_label = f"{period_start.day}-{period_end.day}({period_end.strftime('%b-%y')})"
    scope_label = f"District: {district_name or '-'} | Project: {project_name or '-'}"
    company_lines = []
    for acct_id, amt in debit_bucket.items():
        company_lines.append({
            'account_id': acct_id,
            'debit': amt,
            'credit': 0,
            'description': f'Workspace fuel/oil close expense - {employee.name} | Period: {period_label} | {scope_label}',
        })
    company_lines.append({
        'account_id': company_wallet.id,
        'debit': 0,
        'credit': total,
        'description': f'Workspace fuel/oil settlement against employee wallet - {employee.name} | Period: {period_label} | {scope_label}',
    })
    company_je = create_journal_entry(
        entry_type='Journal',
        entry_date=period_end,
        description=f"Workspace fuel/oil close {employee.name} ({period_start:%m/%Y}) [{scope_label}]",
        lines=company_lines,
        district_id=district_id,
        project_id=project_id,
        reference_type='WorkspaceFuelOilMonthClose',
        reference_id=close_row.id,
        created_by_user_id=user_id,
        category='Workspace Fuel/Oil Close',
    )
    close_row.company_journal_entry_id = company_je.id

    for row in rows:
        row.fuel_oil_month_close_id = close_row.id

    return close_row
