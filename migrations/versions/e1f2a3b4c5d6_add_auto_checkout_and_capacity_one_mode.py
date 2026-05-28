"""add gps auto-checkout and capacity-1 mode settings

Revision ID: e1f2a3b4c5d6
Revises: d2e3f4g5h6i7
Create Date: 2026-05-28
"""

from alembic import op
import sqlalchemy as sa


revision = 'e1f2a3b4c5d6'
down_revision = 'd2e3f4g5h6i7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('attendance_time_override', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'auto_gps_checkout_on_window_end',
                sa.Boolean(),
                nullable=False,
                server_default='0',
            )
        )
        batch_op.add_column(
            sa.Column(
                'capacity_one_checkin_mode',
                sa.String(length=16),
                nullable=False,
                server_default='both',
            )
        )


def downgrade():
    with op.batch_alter_table('attendance_time_override', schema=None) as batch_op:
        batch_op.drop_column('capacity_one_checkin_mode')
        batch_op.drop_column('auto_gps_checkout_on_window_end')

