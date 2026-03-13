"""Add finance and accounting tables: Account, JournalEntry, Vouchers, EmployeeExpense

Revision ID: f8a9b0c1d2e3
Revises: f7a8b9c0d1e2
Create Date: 2026-03-13

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = 'f8a9b0c1d2e3'
down_revision = 'f7a8b9c0d1e2'
branch_labels = None
depends_on = None


def _table_exists(conn, name):
    if conn.dialect.name == 'sqlite':
        r = conn.execute(text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:n"), {"n": name})
    else:
        r = conn.execute(text(
            "SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = :n"
        ), {"n": name})
    return r.scalar() is not None


def upgrade():
    conn = op.get_bind()
    
    # 1. Account (Chart of Accounts)
    if not _table_exists(conn, 'account'):
        op.create_table('account',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('code', sa.String(length=20), nullable=False),
            sa.Column('name', sa.String(length=200), nullable=False),
            sa.Column('account_type', sa.String(length=20), nullable=False),
            sa.Column('parent_id', sa.Integer(), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
            sa.Column('opening_balance', sa.Numeric(precision=15, scale=2), nullable=False, server_default='0'),
            sa.Column('current_balance', sa.Numeric(precision=15, scale=2), nullable=False, server_default='0'),
            sa.Column('district_id', sa.Integer(), nullable=True),
            sa.Column('project_id', sa.Integer(), nullable=True),
            sa.Column('party_id', sa.Integer(), nullable=True),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['district_id'], ['district.id'], ),
            sa.ForeignKeyConstraint(['parent_id'], ['account.id'], ),
            sa.ForeignKeyConstraint(['party_id'], ['party.id'], ),
            sa.ForeignKeyConstraint(['project_id'], ['project.id'], ),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('code')
        )
        op.create_index(op.f('ix_account_code'), 'account', ['code'], unique=True)
    
    # 2. Journal Entry
    if not _table_exists(conn, 'journal_entry'):
        op.create_table('journal_entry',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('entry_number', sa.String(length=50), nullable=False),
            sa.Column('entry_date', sa.Date(), nullable=False),
            sa.Column('entry_type', sa.String(length=20), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('reference_type', sa.String(length=50), nullable=True),
            sa.Column('reference_id', sa.Integer(), nullable=True),
            sa.Column('created_by_user_id', sa.Integer(), nullable=True),
            sa.Column('district_id', sa.Integer(), nullable=True),
            sa.Column('project_id', sa.Integer(), nullable=True),
            sa.Column('is_posted', sa.Boolean(), nullable=False, server_default='1'),
            sa.Column('posted_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['created_by_user_id'], ['user.id'], ),
            sa.ForeignKeyConstraint(['district_id'], ['district.id'], ),
            sa.ForeignKeyConstraint(['project_id'], ['project.id'], ),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('entry_number')
        )
        op.create_index(op.f('ix_journal_entry_entry_date'), 'journal_entry', ['entry_date'], unique=False)
        op.create_index(op.f('ix_journal_entry_entry_number'), 'journal_entry', ['entry_number'], unique=True)
    
    # 3. Journal Entry Line
    if not _table_exists(conn, 'journal_entry_line'):
        op.create_table('journal_entry_line',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('journal_entry_id', sa.Integer(), nullable=False),
            sa.Column('account_id', sa.Integer(), nullable=False),
            sa.Column('debit', sa.Numeric(precision=15, scale=2), nullable=False, server_default='0'),
            sa.Column('credit', sa.Numeric(precision=15, scale=2), nullable=False, server_default='0'),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
            sa.ForeignKeyConstraint(['account_id'], ['account.id'], ),
            sa.ForeignKeyConstraint(['journal_entry_id'], ['journal_entry.id'], ),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_journal_entry_line_account_id'), 'journal_entry_line', ['account_id'], unique=False)
        op.create_index(op.f('ix_journal_entry_line_journal_entry_id'), 'journal_entry_line', ['journal_entry_id'], unique=False)
    
    # 4. Payment Voucher
    if not _table_exists(conn, 'payment_voucher'):
        op.create_table('payment_voucher',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('voucher_number', sa.String(length=50), nullable=False),
            sa.Column('payment_date', sa.Date(), nullable=False),
            sa.Column('from_account_id', sa.Integer(), nullable=False),
            sa.Column('to_account_id', sa.Integer(), nullable=False),
            sa.Column('amount', sa.Numeric(precision=15, scale=2), nullable=False),
            sa.Column('payment_mode', sa.String(length=20), nullable=False, server_default='Cash'),
            sa.Column('cheque_number', sa.String(length=50), nullable=True),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('journal_entry_id', sa.Integer(), nullable=True),
            sa.Column('created_by_user_id', sa.Integer(), nullable=True),
            sa.Column('district_id', sa.Integer(), nullable=True),
            sa.Column('project_id', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['created_by_user_id'], ['user.id'], ),
            sa.ForeignKeyConstraint(['district_id'], ['district.id'], ),
            sa.ForeignKeyConstraint(['from_account_id'], ['account.id'], ),
            sa.ForeignKeyConstraint(['journal_entry_id'], ['journal_entry.id'], ),
            sa.ForeignKeyConstraint(['project_id'], ['project.id'], ),
            sa.ForeignKeyConstraint(['to_account_id'], ['account.id'], ),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('voucher_number')
        )
        op.create_index(op.f('ix_payment_voucher_payment_date'), 'payment_voucher', ['payment_date'], unique=False)
        op.create_index(op.f('ix_payment_voucher_voucher_number'), 'payment_voucher', ['voucher_number'], unique=True)
    
    # 5. Receipt Voucher
    if not _table_exists(conn, 'receipt_voucher'):
        op.create_table('receipt_voucher',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('voucher_number', sa.String(length=50), nullable=False),
            sa.Column('receipt_date', sa.Date(), nullable=False),
            sa.Column('from_account_id', sa.Integer(), nullable=False),
            sa.Column('to_account_id', sa.Integer(), nullable=False),
            sa.Column('amount', sa.Numeric(precision=15, scale=2), nullable=False),
            sa.Column('receipt_mode', sa.String(length=20), nullable=False, server_default='Cash'),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('journal_entry_id', sa.Integer(), nullable=True),
            sa.Column('created_by_user_id', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['created_by_user_id'], ['user.id'], ),
            sa.ForeignKeyConstraint(['from_account_id'], ['account.id'], ),
            sa.ForeignKeyConstraint(['journal_entry_id'], ['journal_entry.id'], ),
            sa.ForeignKeyConstraint(['to_account_id'], ['account.id'], ),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('voucher_number')
        )
        op.create_index(op.f('ix_receipt_voucher_receipt_date'), 'receipt_voucher', ['receipt_date'], unique=False)
        op.create_index(op.f('ix_receipt_voucher_voucher_number'), 'receipt_voucher', ['voucher_number'], unique=True)
    
    # 6. Bank Entry
    if not _table_exists(conn, 'bank_entry'):
        op.create_table('bank_entry',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('entry_number', sa.String(length=50), nullable=False),
            sa.Column('entry_date', sa.Date(), nullable=False),
            sa.Column('from_account_id', sa.Integer(), nullable=False),
            sa.Column('to_account_id', sa.Integer(), nullable=False),
            sa.Column('amount', sa.Numeric(precision=15, scale=2), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('journal_entry_id', sa.Integer(), nullable=True),
            sa.Column('created_by_user_id', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['created_by_user_id'], ['user.id'], ),
            sa.ForeignKeyConstraint(['from_account_id'], ['account.id'], ),
            sa.ForeignKeyConstraint(['journal_entry_id'], ['journal_entry.id'], ),
            sa.ForeignKeyConstraint(['to_account_id'], ['account.id'], ),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('entry_number')
        )
        op.create_index(op.f('ix_bank_entry_entry_date'), 'bank_entry', ['entry_date'], unique=False)
        op.create_index(op.f('ix_bank_entry_entry_number'), 'bank_entry', ['entry_number'], unique=True)
    
    # 7. Employee Expense
    if not _table_exists(conn, 'employee_expense'):
        op.create_table('employee_expense',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('expense_date', sa.Date(), nullable=False),
            sa.Column('employee_id', sa.Integer(), nullable=True),
            sa.Column('user_id', sa.Integer(), nullable=True),
            sa.Column('district_id', sa.Integer(), nullable=True),
            sa.Column('project_id', sa.Integer(), nullable=True),
            sa.Column('expense_category', sa.String(length=50), nullable=False),
            sa.Column('description', sa.Text(), nullable=False),
            sa.Column('amount', sa.Numeric(precision=15, scale=2), nullable=False),
            sa.Column('payment_mode', sa.String(length=20), nullable=False, server_default='Cash'),
            sa.Column('receipt_path', sa.String(length=500), nullable=True),
            sa.Column('journal_entry_id', sa.Integer(), nullable=True),
            sa.Column('created_by_user_id', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['created_by_user_id'], ['user.id'], ),
            sa.ForeignKeyConstraint(['district_id'], ['district.id'], ),
            sa.ForeignKeyConstraint(['employee_id'], ['employee.id'], ),
            sa.ForeignKeyConstraint(['journal_entry_id'], ['journal_entry.id'], ),
            sa.ForeignKeyConstraint(['project_id'], ['project.id'], ),
            sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_employee_expense_expense_date'), 'employee_expense', ['expense_date'], unique=False)


def downgrade():
    conn = op.get_bind()
    
    if _table_exists(conn, 'employee_expense'):
        op.drop_index(op.f('ix_employee_expense_expense_date'), table_name='employee_expense')
        op.drop_table('employee_expense')
    
    if _table_exists(conn, 'bank_entry'):
        op.drop_index(op.f('ix_bank_entry_entry_number'), table_name='bank_entry')
        op.drop_index(op.f('ix_bank_entry_entry_date'), table_name='bank_entry')
        op.drop_table('bank_entry')
    
    if _table_exists(conn, 'receipt_voucher'):
        op.drop_index(op.f('ix_receipt_voucher_voucher_number'), table_name='receipt_voucher')
        op.drop_index(op.f('ix_receipt_voucher_receipt_date'), table_name='receipt_voucher')
        op.drop_table('receipt_voucher')
    
    if _table_exists(conn, 'payment_voucher'):
        op.drop_index(op.f('ix_payment_voucher_voucher_number'), table_name='payment_voucher')
        op.drop_index(op.f('ix_payment_voucher_payment_date'), table_name='payment_voucher')
        op.drop_table('payment_voucher')
    
    if _table_exists(conn, 'journal_entry_line'):
        op.drop_index(op.f('ix_journal_entry_line_journal_entry_id'), table_name='journal_entry_line')
        op.drop_index(op.f('ix_journal_entry_line_account_id'), table_name='journal_entry_line')
        op.drop_table('journal_entry_line')
    
    if _table_exists(conn, 'journal_entry'):
        op.drop_index(op.f('ix_journal_entry_entry_number'), table_name='journal_entry')
        op.drop_index(op.f('ix_journal_entry_entry_date'), table_name='journal_entry')
        op.drop_table('journal_entry')
    
    if _table_exists(conn, 'account'):
        op.drop_index(op.f('ix_account_code'), table_name='account')
        op.drop_table('account')
