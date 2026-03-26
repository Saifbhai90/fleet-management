"""add check_out_date to driver_attendance

Revision ID: i2j3k4l5m6n7
Revises: 9448ebf0d7b7
Create Date: 2026-03-26

"""
from alembic import op
import sqlalchemy as sa


revision = 'i2j3k4l5m6n7'
down_revision = '9448ebf0d7b7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('driver_attendance', schema=None) as batch_op:
        batch_op.add_column(sa.Column('check_out_date', sa.Date(), nullable=True))


def downgrade():
    with op.batch_alter_table('driver_attendance', schema=None) as batch_op:
        batch_op.drop_column('check_out_date')
