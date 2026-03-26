"""add allow_future_checkout to attendance_time_override

Revision ID: j3k4l5m6n7o8
Revises: i2j3k4l5m6n7
Create Date: 2026-03-26

"""
from alembic import op
import sqlalchemy as sa


revision = 'j3k4l5m6n7o8'
down_revision = 'i2j3k4l5m6n7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('attendance_time_override', schema=None) as batch_op:
        batch_op.add_column(sa.Column('allow_future_checkout', sa.Boolean(), nullable=False, server_default='0'))


def downgrade():
    with op.batch_alter_table('attendance_time_override', schema=None) as batch_op:
        batch_op.drop_column('allow_future_checkout')
