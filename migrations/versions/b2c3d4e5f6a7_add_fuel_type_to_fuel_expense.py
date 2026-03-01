"""add fuel_type to fuel_expense

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-01

"""
from alembic import op
import sqlalchemy as sa


revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('fuel_expense', schema=None) as batch_op:
        batch_op.add_column(sa.Column('fuel_type', sa.String(length=20), nullable=True))


def downgrade():
    with op.batch_alter_table('fuel_expense', schema=None) as batch_op:
        batch_op.drop_column('fuel_type')
