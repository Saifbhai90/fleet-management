"""
Finance & Accounting Utility Functions
Helper functions for voucher number generation, journal entry creation, and balance updates
"""
from models import db, Account, JournalEntry, JournalEntryLine, PaymentVoucher, ReceiptVoucher, BankEntry
from datetime import datetime, date
from decimal import Decimal


def generate_entry_number(prefix='JE', entry_date=None):
    """
    Generate unique entry number: JE-2026-03-001, PV-2026-03-001, etc.
    
    Args:
        prefix: Entry type prefix (JE, PV, RV, BE)
        entry_date: Date for the entry (default: today)
    
    Returns:
        str: Unique entry number
    """
    if entry_date is None:
        entry_date = date.today()
    
    year = entry_date.year
    month = entry_date.month
    
    # Find last entry number for this prefix, year, and month
    pattern = f"{prefix}-{year:04d}-{month:02d}-%"
    
    if prefix == 'JE':
        last = JournalEntry.query.filter(JournalEntry.entry_number.like(pattern)).order_by(JournalEntry.entry_number.desc()).first()
    elif prefix == 'PV':
        last = PaymentVoucher.query.filter(PaymentVoucher.voucher_number.like(pattern)).order_by(PaymentVoucher.voucher_number.desc()).first()
    elif prefix == 'RV':
        last = ReceiptVoucher.query.filter(ReceiptVoucher.voucher_number.like(pattern)).order_by(ReceiptVoucher.voucher_number.desc()).first()
    elif prefix == 'BE':
        last = BankEntry.query.filter(BankEntry.entry_number.like(pattern)).order_by(BankEntry.entry_number.desc()).first()
    else:
        last = None
    
    if last:
        # Extract sequence number from last entry
        if prefix == 'JE':
            last_num = last.entry_number
        elif prefix in ['PV', 'RV']:
            last_num = last.voucher_number
        else:
            last_num = last.entry_number
        
        parts = last_num.split('-')
        if len(parts) == 4:
            seq = int(parts[3]) + 1
        else:
            seq = 1
    else:
        seq = 1
    
    return f"{prefix}-{year:04d}-{month:02d}-{seq:03d}"


def create_journal_entry(entry_type, entry_date, description, lines, district_id=None, project_id=None, 
                         reference_type=None, reference_id=None, created_by_user_id=None):
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
        is_posted=True,
        posted_at=datetime.utcnow()
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
        account = Account.query.get(line.account_id)
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


def get_account_ledger(account_id, from_date=None, to_date=None):
    """
    Get account ledger with all transactions and running balance.
    
    Args:
        account_id: Account ID
        from_date: Start date (optional)
        to_date: End date (optional)
    
    Returns:
        dict: {
            'account': Account object,
            'opening_balance': Decimal,
            'transactions': List of dicts with transaction details,
            'closing_balance': Decimal
        }
    """
    account = Account.query.get(account_id)
    if not account:
        return None
    
    # Calculate opening balance
    if from_date:
        opening_balance = get_account_balance(account_id, from_date - datetime.timedelta(days=1))
    else:
        opening_balance = Decimal(str(account.opening_balance or 0))
    
    # Get transactions
    query = db.session.query(JournalEntryLine, JournalEntry).join(JournalEntry).filter(
        JournalEntryLine.account_id == account_id,
        JournalEntry.is_posted == True
    )
    
    if from_date:
        query = query.filter(JournalEntry.entry_date >= from_date)
    if to_date:
        query = query.filter(JournalEntry.entry_date <= to_date)
    
    query = query.order_by(JournalEntry.entry_date, JournalEntry.id, JournalEntryLine.sort_order)
    
    results = query.all()
    
    transactions = []
    running_balance = opening_balance
    
    for line, je in results:
        debit = Decimal(str(line.debit or 0))
        credit = Decimal(str(line.credit or 0))
        
        # Calculate balance change
        if account.account_type in ['Asset', 'Expense']:
            balance_change = debit - credit
        else:
            balance_change = credit - debit
        
        running_balance += balance_change
        
        transactions.append({
            'date': je.entry_date,
            'entry_number': je.entry_number,
            'entry_type': je.entry_type,
            'description': line.description or je.description,
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
        expense_date = date.today()
    
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
