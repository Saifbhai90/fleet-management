"""add allow_night_driver_morning_gps_checkin to attendance_time_override

Revision ID: b0c1d2e3f4a5
Revises: a9b0c1d2e3f4
Create Date: 2026-05-17

"""
from alembic import op
import sqlalchemy as sa


revision = 'b0c1d2e3f4a5'
down_revision = 'a9b0c1d2e3f4'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('attendance_time_override', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'allow_night_driver_morning_gps_checkin',
                sa.Boolean(),
                nullable=False,
                server_default='0',
            )
        )


def downgrade():
    with op.batch_alter_table('attendance_time_override', schema=None) as batch_op:
        batch_op.drop_column('allow_night_driver_morning_gps_checkin')
