from datetime import date
from decimal import Decimal

from sqlalchemy import and_, or_

from finance_utils import create_journal_entry, generate_entry_number
from models import Account, DtoSettlement, DtoSettlementLine, DtoTxn, db
from utils import pk_now


VALID_COUNTERPARTY_TYPES = ('Driver', 'Party', 'Market', 'Other')
VALID_MODES = ('Cash', 'Credit', 'Bank', 'Wallet')
VALID_NATURES = ('Purchase', 'Borrow', 'Lending', 'Payment', 'Receive', 'Adjustment')
VALID_DIRECTIONS = ('Payable', 'Receivable')
VALID_TXN_STATUS = ('Draft', 'Verified', 'Settled', 'Cancelled')


def validate_dto_txn_payload(payload, require_attachment_for_credit=True):
    errors = []
    counterparty_type = (payload.get('counterparty_type') or '').strip()
    mode = (payload.get('mode') or '').strip()
    txn_nature = (payload.get('txn_nature') or '').strip()
    direction = (payload.get('direction') or '').strip()
    amount = Decimal(str(payload.get('amount') or 0))

    if counterparty_type not in VALID_COUNTERPARTY_TYPES:
        errors.append('Counterparty type is invalid.')
    if mode not in VALID_MODES:
        errors.append('Mode is invalid.')
    if txn_nature not in VALID_NATURES:
        errors.append('Transaction nature is invalid.')
    if direction not in VALID_DIRECTIONS:
        errors.append('Direction is invalid.')
    if amount <= 0:
        errors.append('Amount must be greater than zero.')

    attachment_path = (payload.get('attachment_path') or '').strip()
    if require_attachment_for_credit and mode == 'Credit' and not attachment_path:
        errors.append('Attachment is required for credit transactions.')

    return errors


def generate_dto_txn_number(txn_date):
    return generate_entry_number('DTO', txn_date)


def generate_dto_settlement_number(settlement_date):
    return generate_entry_number('DTS', settlement_date)


def get_working_ledger(dto_profile_id, *, from_date=None, to_date=None, district_id=None, project_id=None,
                       direction=None, status=None, claimable=None, counterparty_type=None):
    query = DtoTxn.query.filter(DtoTxn.dto_profile_id == dto_profile_id)

    if from_date:
        query = query.filter(DtoTxn.txn_date >= from_date)
    if to_date:
        query = query.filter(DtoTxn.txn_date <= to_date)
    if district_id:
        query = query.filter(DtoTxn.district_id == district_id)
    if project_id:
        query = query.filter(DtoTxn.project_id == project_id)
    if direction:
        query = query.filter(DtoTxn.direction == direction)
    if status:
        query = query.filter(DtoTxn.status == status)
    if claimable is not None:
        query = query.filter(DtoTxn.is_company_claimable == bool(claimable))
    if counterparty_type:
        query = query.filter(DtoTxn.counterparty_type == counterparty_type)

    txns = query.order_by(DtoTxn.txn_date.asc(), DtoTxn.id.asc()).all()
    running = Decimal('0')
    rows = []
    for t in txns:
        amt = Decimal(str(t.amount or 0))
        delta = amt if t.direction == 'Receivable' else -amt
        running += delta
        rows.append({
            'txn': t,
            'delta': delta,
            'running_balance': running,
        })

    return {
        'rows': rows,
        'closing_balance': running,
        'count': len(rows),
    }


def get_open_summary(dto_profile_id, *, as_of_date=None):
    as_of_date = as_of_date or date.today()
    q = DtoTxn.query.filter(
        DtoTxn.dto_profile_id == dto_profile_id,
        DtoTxn.status.in_(('Draft', 'Verified')),
        DtoTxn.txn_date <= as_of_date,
    )
    payable = Decimal('0')
    receivable = Decimal('0')
    for t in q.all():
        amt = Decimal(str(t.amount or 0))
        if t.direction == 'Payable':
            payable += amt
        else:
            receivable += amt
    return {
        'payable': payable,
        'receivable': receivable,
        'net': receivable - payable,
    }


def get_aging_buckets(dto_profile_id, *, as_of_date=None, direction=None):
    as_of_date = as_of_date or date.today()
    query = DtoTxn.query.filter(
        DtoTxn.dto_profile_id == dto_profile_id,
        DtoTxn.status.in_(('Draft', 'Verified')),
    )
    if direction:
        query = query.filter(DtoTxn.direction == direction)

    buckets = {
        '0_7': Decimal('0'),
        '8_15': Decimal('0'),
        '16_30': Decimal('0'),
        '31_plus': Decimal('0'),
    }
    for t in query.all():
        base_date = t.due_date or t.txn_date
        if not base_date:
            continue
        age = max((as_of_date - base_date).days, 0)
        amt = Decimal(str(t.amount or 0))
        if age <= 7:
            buckets['0_7'] += amt
        elif age <= 15:
            buckets['8_15'] += amt
        elif age <= 30:
            buckets['16_30'] += amt
        else:
            buckets['31_plus'] += amt
    return buckets


def create_settlement(dto_profile_id, settlement_date, txn_ids, created_by_user_id, description=''):
    txns = DtoTxn.query.filter(
        DtoTxn.dto_profile_id == dto_profile_id,
        DtoTxn.id.in_(txn_ids),
    ).all()
    if not txns:
        raise ValueError('No transactions selected for settlement.')

    for t in txns:
        if t.status not in ('Verified', 'Draft'):
            raise ValueError(f'Transaction {t.txn_number} cannot be settled in current status.')

    settlement = DtoSettlement(
        settlement_number=generate_dto_settlement_number(settlement_date),
        settlement_date=settlement_date,
        dto_profile_id=dto_profile_id,
        district_id=txns[0].district_id,
        project_id=txns[0].project_id,
        status='Draft',
        description=description or None,
        created_by_user_id=created_by_user_id,
    )
    db.session.add(settlement)
    db.session.flush()

    for t in txns:
        line = DtoSettlementLine(
            settlement_id=settlement.id,
            dto_txn_id=t.id,
            amount=t.amount,
            direction=t.direction,
            note=t.reference_no or None,
        )
        db.session.add(line)
        t.settlement_id = settlement.id
        if t.is_company_claimable:
            t.claim_status = 'Claimed'
        db.session.add(t)
    db.session.flush()
    return settlement


def _pick_account(code, fallback_code=None):
    acct = Account.query.filter_by(code=code).first()
    if acct:
        return acct
    if fallback_code:
        return Account.query.filter_by(code=fallback_code).first()
    return None


def post_settlement_to_books(settlement, user_id):
    if settlement.status == 'Posted' and settlement.journal_entry_id:
        return settlement.journal_entry

    claimable_txns = DtoTxn.query.filter(
        DtoTxn.settlement_id == settlement.id,
        DtoTxn.is_company_claimable == True,
        DtoTxn.status.in_(('Draft', 'Verified')),
    ).all()
    if not claimable_txns:
        raise ValueError('No claimable transactions available for posting.')

    total_payable = Decimal('0')
    total_receivable = Decimal('0')
    for t in claimable_txns:
        amt = Decimal(str(t.amount or 0))
        if t.direction == 'Payable':
            total_payable += amt
        else:
            total_receivable += amt

    # Clearing accounts (existing COA heads)
    expense_acct = _pick_account('5600', '5500')
    income_acct = _pick_account('4200', '4100')
    dto_clearing_acct = _pick_account('2200', '1101')
    if not expense_acct or not income_acct or not dto_clearing_acct:
        raise ValueError('Required chart accounts are missing for settlement posting.')

    lines = []
    if total_payable > 0:
        lines.append({
            'account_id': expense_acct.id,
            'debit': total_payable,
            'credit': 0,
            'description': f'DTO settlement expense {settlement.settlement_number}',
        })
    if total_receivable > 0:
        lines.append({
            'account_id': income_acct.id,
            'debit': 0,
            'credit': total_receivable,
            'description': f'DTO settlement recovery {settlement.settlement_number}',
        })

    net_to_company = total_payable - total_receivable
    if net_to_company > 0:
        lines.append({
            'account_id': dto_clearing_acct.id,
            'debit': 0,
            'credit': net_to_company,
            'description': f'DTO claim payable {settlement.settlement_number}',
        })
    elif net_to_company < 0:
        lines.append({
            'account_id': dto_clearing_acct.id,
            'debit': abs(net_to_company),
            'credit': 0,
            'description': f'DTO recovery receivable {settlement.settlement_number}',
        })

    if len(lines) < 2:
        raise ValueError('Settlement posting requires at least two balanced lines.')

    je = create_journal_entry(
        entry_type='Journal',
        entry_date=settlement.settlement_date,
        description=f'DTO Settlement {settlement.settlement_number}',
        lines=lines,
        district_id=settlement.district_id,
        project_id=settlement.project_id,
        reference_type='DtoSettlement',
        reference_id=settlement.id,
        created_by_user_id=user_id,
    )

    settlement.journal_entry_id = je.id
    settlement.status = 'Posted'
    settlement.posted_by_user_id = user_id
    settlement.posted_at = pk_now()
    db.session.add(settlement)

    for t in claimable_txns:
        t.status = 'Settled'
        t.claim_status = 'Settled'
        t.settled_by_user_id = user_id
        t.settled_at = pk_now()
        db.session.add(t)

    db.session.flush()
    return je


def cancel_settlement(settlement, user_id):
    if settlement.status == 'Posted':
        raise ValueError('Posted settlement cannot be cancelled directly.')
    settlement.status = 'Cancelled'
    settlement.updated_at = pk_now()
    db.session.add(settlement)
    for t in settlement.transactions:
        if t.status != 'Settled':
            t.settlement_id = None
            if t.is_company_claimable:
                t.claim_status = 'Unclaimed'
            db.session.add(t)
    db.session.flush()
    return settlement
