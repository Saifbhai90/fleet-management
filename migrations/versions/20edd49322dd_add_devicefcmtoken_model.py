"""add DeviceFCMToken model

Revision ID: 20edd49322dd
Revises: j3k4l5m6n7o8
Create Date: 2026-03-30 18:02:24.847129

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20edd49322dd'
down_revision = 'j3k4l5m6n7o8'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='device_fcm_token')"
    ))
    exists = result.scalar()
    if not exists:
        op.create_table('device_fcm_token',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('fcm_token', sa.String(length=500), nullable=False),
            sa.Column('device_info', sa.String(length=255), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('user_id', 'fcm_token', name='uq_user_fcm_token'),
        )
        op.create_index('ix_device_fcm_token_user_id', 'device_fcm_token', ['user_id'], unique=False)


def downgrade():
    op.drop_table('device_fcm_token')
