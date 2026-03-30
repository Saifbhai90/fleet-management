"""Add device_unique_id to device_fcm_token, update unique constraint

Revision ID: fcm_bank_style_01
Revises: 20edd49322dd
Create Date: 2026-03-30

"""
from alembic import op
import sqlalchemy as sa


revision = 'fcm_bank_style_01'
down_revision = '20edd49322dd'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    col_check = conn.execute(sa.text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='device_fcm_token' AND column_name='device_unique_id'"
    ))
    if not col_check.fetchone():
        op.add_column('device_fcm_token',
            sa.Column('device_unique_id', sa.String(length=255), nullable=True))
        op.create_index('ix_device_fcm_token_device_unique_id',
                        'device_fcm_token', ['device_unique_id'], unique=False)

    try:
        op.drop_constraint('uq_user_fcm_token', 'device_fcm_token', type_='unique')
    except Exception:
        pass

    uq_check = conn.execute(sa.text(
        "SELECT 1 FROM pg_constraint WHERE conname='uq_user_device'"
    ))
    if not uq_check.fetchone():
        op.create_unique_constraint('uq_user_device', 'device_fcm_token',
                                    ['user_id', 'device_unique_id'])


def downgrade():
    try:
        op.drop_constraint('uq_user_device', 'device_fcm_token', type_='unique')
    except Exception:
        pass
    op.drop_index('ix_device_fcm_token_device_unique_id', table_name='device_fcm_token')
    op.drop_column('device_fcm_token', 'device_unique_id')
    op.create_unique_constraint('uq_user_fcm_token', 'device_fcm_token',
                                ['user_id', 'fcm_token'])
