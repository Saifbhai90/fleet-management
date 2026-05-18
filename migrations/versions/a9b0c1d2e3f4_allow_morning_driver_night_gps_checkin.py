"""add allow_morning_driver_night_gps_checkin to attendance_time_override

Revision ID: a9b0c1d2e3f4
Revises: h8i9j0k1l2m3
Create Date: 2026-05-17

"""
from alembic import op
import sqlalchemy as sa


revision = 'a9b0c1d2e3f4'
down_revision = 'h8i9j0k1l2m3'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('attendance_time_override', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'allow_morning_driver_night_gps_checkin',
                sa.Boolean(),
                nullable=False,
                server_default='0',
            )
        )


def downgrade():
    with op.batch_alter_table('attendance_time_override', schema=None) as batch_op:
        batch_op.drop_column('allow_morning_driver_night_gps_checkin')
