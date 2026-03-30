"""Add login_attempt and system_setting tables

Revision ID: security_cleanup_01
Revises: notif_perm_01
Create Date: 2026-03-31

"""
from alembic import op
import sqlalchemy as sa


revision = 'security_cleanup_01'
down_revision = 'notif_perm_01'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    tbl_check = conn.execute(sa.text(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_name='login_attempt'"
    ))
    if not tbl_check.fetchone():
        op.create_table('login_attempt',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('username', sa.String(length=200), nullable=False),
            sa.Column('ip_address', sa.String(length=64), nullable=True),
            sa.Column('user_agent', sa.String(length=500), nullable=True),
            sa.Column('success', sa.Boolean(), nullable=False, server_default=sa.text('false')),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_login_attempt_username', 'login_attempt', ['username'])
        op.create_index('ix_login_attempt_created_at', 'login_attempt', ['created_at'])

    tbl_check2 = conn.execute(sa.text(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_name='system_setting'"
    ))
    if not tbl_check2.fetchone():
        op.create_table('system_setting',
            sa.Column('key', sa.String(length=100), nullable=False),
            sa.Column('value', sa.Text(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('key'),
        )


def downgrade():
    op.drop_table('system_setting')
    op.drop_table('login_attempt')
