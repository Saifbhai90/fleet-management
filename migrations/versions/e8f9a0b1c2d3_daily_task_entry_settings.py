"""Add New Task Entry settings columns to attendance_settings

Revision ID: e8f9a0b1c2d3
Revises: d2e3f4a5b6c7
Create Date: 2026-05-14
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = 'e8f9a0b1c2d3'
down_revision = 'd2e3f4a5b6c7'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = inspect(bind)
    cols = {c['name'] for c in insp.get_columns('attendance_settings')}
    if 'daily_task_entry_max_kms_driven' not in cols:
        op.add_column(
            'attendance_settings',
            sa.Column('daily_task_entry_max_kms_driven', sa.Integer(), nullable=True),
        )
    if 'daily_task_odometer_photo_required' not in cols:
        op.add_column(
            'attendance_settings',
            sa.Column(
                'daily_task_odometer_photo_required',
                sa.Boolean(),
                nullable=False,
                server_default=sa.text('false'),
            ),
        )


def downgrade():
    bind = op.get_bind()
    insp = inspect(bind)
    cols = {c['name'] for c in insp.get_columns('attendance_settings')}
    if 'daily_task_odometer_photo_required' in cols:
        op.drop_column('attendance_settings', 'daily_task_odometer_photo_required')
    if 'daily_task_entry_max_kms_driven' in cols:
        op.drop_column('attendance_settings', 'daily_task_entry_max_kms_driven')
