"""Add required_permission column to notification table

Revision ID: notif_perm_01
Revises: fcm_bank_style_01
Create Date: 2026-03-31

"""
from alembic import op
import sqlalchemy as sa


revision = 'notif_perm_01'
down_revision = 'fcm_bank_style_01'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    col_check = conn.execute(sa.text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='notification' AND column_name='required_permission'"
    ))
    if not col_check.fetchone():
        op.add_column('notification',
            sa.Column('required_permission', sa.String(length=500), nullable=True))


def downgrade():
    op.drop_column('notification', 'required_permission')
