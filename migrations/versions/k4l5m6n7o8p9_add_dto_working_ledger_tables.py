"""add dto working ledger tables

Revision ID: k4l5m6n7o8p9
Revises: security_cleanup_01
Create Date: 2026-04-06

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = 'k4l5m6n7o8p9'
down_revision = 'security_cleanup_01'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'dto_profile' not in existing_tables:
        op.create_table(
            'dto_profile',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('employee_id', sa.Integer(), nullable=False),
            sa.Column('district_id', sa.Integer(), nullable=False),
            sa.Column('project_id', sa.Integer(), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('created_by_user_id', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['created_by_user_id'], ['user.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['district_id'], ['district.id']),
            sa.ForeignKeyConstraint(['employee_id'], ['employee.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['project_id'], ['project.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('employee_id', name='uq_dto_profile_employee'),
        )
        existing_tables.add('dto_profile')
    op.execute('CREATE INDEX IF NOT EXISTS ix_dto_profile_employee_id ON dto_profile (employee_id)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_dto_profile_district_id ON dto_profile (district_id)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_dto_profile_project_id ON dto_profile (project_id)')

    if 'dto_counterparty' not in existing_tables:
        op.create_table(
            'dto_counterparty',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('dto_profile_id', sa.Integer(), nullable=False),
            sa.Column('counterparty_type', sa.String(length=20), nullable=False),
            sa.Column('name', sa.String(length=150), nullable=False),
            sa.Column('driver_id', sa.Integer(), nullable=True),
            sa.Column('party_id', sa.Integer(), nullable=True),
            sa.Column('phone', sa.String(length=30), nullable=True),
            sa.Column('account_ref', sa.String(length=80), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['driver_id'], ['driver.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['dto_profile_id'], ['dto_profile.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['party_id'], ['party.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('dto_profile_id', 'counterparty_type', 'name', name='uq_dto_counterparty_scope'),
        )
        existing_tables.add('dto_counterparty')
    op.execute('CREATE INDEX IF NOT EXISTS ix_dto_counterparty_dto_profile_id ON dto_counterparty (dto_profile_id)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_dto_counterparty_counterparty_type ON dto_counterparty (counterparty_type)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_dto_counterparty_name ON dto_counterparty (name)')

    if 'dto_settlement' not in existing_tables:
        op.create_table(
            'dto_settlement',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('settlement_number', sa.String(length=40), nullable=False),
            sa.Column('settlement_date', sa.Date(), nullable=False),
            sa.Column('dto_profile_id', sa.Integer(), nullable=False),
            sa.Column('district_id', sa.Integer(), nullable=False),
            sa.Column('project_id', sa.Integer(), nullable=True),
            sa.Column('status', sa.String(length=20), nullable=False, server_default='Draft'),
            sa.Column('posting_mode', sa.String(length=20), nullable=False, server_default='Journal'),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('journal_entry_id', sa.Integer(), nullable=True),
            sa.Column('created_by_user_id', sa.Integer(), nullable=True),
            sa.Column('posted_by_user_id', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('posted_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['created_by_user_id'], ['user.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['district_id'], ['district.id']),
            sa.ForeignKeyConstraint(['dto_profile_id'], ['dto_profile.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['journal_entry_id'], ['journal_entry.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['posted_by_user_id'], ['user.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['project_id'], ['project.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('settlement_number'),
        )
        existing_tables.add('dto_settlement')
    op.execute('CREATE UNIQUE INDEX IF NOT EXISTS ix_dto_settlement_settlement_number ON dto_settlement (settlement_number)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_dto_settlement_settlement_date ON dto_settlement (settlement_date)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_dto_settlement_dto_profile_id ON dto_settlement (dto_profile_id)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_dto_settlement_district_id ON dto_settlement (district_id)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_dto_settlement_project_id ON dto_settlement (project_id)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_dto_settlement_status ON dto_settlement (status)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_dto_settlement_journal_entry_id ON dto_settlement (journal_entry_id)')

    if 'dto_txn' not in existing_tables:
        op.create_table(
            'dto_txn',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('txn_number', sa.String(length=40), nullable=False),
            sa.Column('txn_date', sa.Date(), nullable=False),
            sa.Column('district_id', sa.Integer(), nullable=False),
            sa.Column('project_id', sa.Integer(), nullable=True),
            sa.Column('dto_profile_id', sa.Integer(), nullable=False),
            sa.Column('counterparty_id', sa.Integer(), nullable=True),
            sa.Column('counterparty_type', sa.String(length=20), nullable=False),
            sa.Column('counterparty_name', sa.String(length=150), nullable=False),
            sa.Column('mode', sa.String(length=20), nullable=False),
            sa.Column('txn_nature', sa.String(length=30), nullable=False),
            sa.Column('direction', sa.String(length=20), nullable=False),
            sa.Column('amount', sa.Numeric(precision=15, scale=2), nullable=False),
            sa.Column('due_date', sa.Date(), nullable=True),
            sa.Column('is_company_claimable', sa.Boolean(), nullable=False, server_default='0'),
            sa.Column('claim_status', sa.String(length=20), nullable=False, server_default='Unclaimed'),
            sa.Column('status', sa.String(length=20), nullable=False, server_default='Draft'),
            sa.Column('reference_no', sa.String(length=80), nullable=True),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('attachment_path', sa.String(length=500), nullable=True),
            sa.Column('settlement_id', sa.Integer(), nullable=True),
            sa.Column('created_by_user_id', sa.Integer(), nullable=True),
            sa.Column('verified_by_user_id', sa.Integer(), nullable=True),
            sa.Column('settled_by_user_id', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('verified_at', sa.DateTime(), nullable=True),
            sa.Column('settled_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['counterparty_id'], ['dto_counterparty.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['created_by_user_id'], ['user.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['district_id'], ['district.id']),
            sa.ForeignKeyConstraint(['dto_profile_id'], ['dto_profile.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['project_id'], ['project.id']),
            sa.ForeignKeyConstraint(['settled_by_user_id'], ['user.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['settlement_id'], ['dto_settlement.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['verified_by_user_id'], ['user.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('txn_number'),
        )
        existing_tables.add('dto_txn')
    op.execute('CREATE UNIQUE INDEX IF NOT EXISTS ix_dto_txn_txn_number ON dto_txn (txn_number)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_dto_txn_txn_date ON dto_txn (txn_date)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_dto_txn_district_id ON dto_txn (district_id)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_dto_txn_project_id ON dto_txn (project_id)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_dto_txn_dto_profile_id ON dto_txn (dto_profile_id)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_dto_txn_counterparty_id ON dto_txn (counterparty_id)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_dto_txn_counterparty_type ON dto_txn (counterparty_type)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_dto_txn_counterparty_name ON dto_txn (counterparty_name)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_dto_txn_direction ON dto_txn (direction)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_dto_txn_due_date ON dto_txn (due_date)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_dto_txn_is_company_claimable ON dto_txn (is_company_claimable)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_dto_txn_claim_status ON dto_txn (claim_status)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_dto_txn_status ON dto_txn (status)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_dto_txn_settlement_id ON dto_txn (settlement_id)')

    if 'dto_settlement_line' not in existing_tables:
        op.create_table(
            'dto_settlement_line',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('settlement_id', sa.Integer(), nullable=False),
            sa.Column('dto_txn_id', sa.Integer(), nullable=False),
            sa.Column('amount', sa.Numeric(precision=15, scale=2), nullable=False),
            sa.Column('direction', sa.String(length=20), nullable=False),
            sa.Column('note', sa.String(length=255), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['dto_txn_id'], ['dto_txn.id'], ondelete='RESTRICT'),
            sa.ForeignKeyConstraint(['settlement_id'], ['dto_settlement.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('settlement_id', 'dto_txn_id', name='uq_dto_settlement_line_unique'),
        )
        existing_tables.add('dto_settlement_line')
    op.execute('CREATE INDEX IF NOT EXISTS ix_dto_settlement_line_settlement_id ON dto_settlement_line (settlement_id)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_dto_settlement_line_dto_txn_id ON dto_settlement_line (dto_txn_id)')

    if 'dto_attachment' not in existing_tables:
        op.create_table(
            'dto_attachment',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('dto_txn_id', sa.Integer(), nullable=True),
            sa.Column('dto_settlement_id', sa.Integer(), nullable=True),
            sa.Column('file_path', sa.String(length=500), nullable=False),
            sa.Column('file_type', sa.String(length=20), nullable=True),
            sa.Column('original_name', sa.String(length=255), nullable=True),
            sa.Column('uploaded_by_user_id', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['dto_settlement_id'], ['dto_settlement.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['dto_txn_id'], ['dto_txn.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['uploaded_by_user_id'], ['user.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
        )
    op.execute('CREATE INDEX IF NOT EXISTS ix_dto_attachment_dto_txn_id ON dto_attachment (dto_txn_id)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_dto_attachment_dto_settlement_id ON dto_attachment (dto_settlement_id)')


def downgrade():
    op.execute('DROP TABLE IF EXISTS dto_attachment CASCADE')
    op.execute('DROP TABLE IF EXISTS dto_settlement_line CASCADE')
    op.execute('DROP TABLE IF EXISTS dto_txn CASCADE')
    op.execute('DROP TABLE IF EXISTS dto_settlement CASCADE')
    op.execute('DROP TABLE IF EXISTS dto_counterparty CASCADE')
    op.execute('DROP TABLE IF EXISTS dto_profile CASCADE')
