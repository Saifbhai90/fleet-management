"""add fuel_expense table

Revision ID: a1b2c3d4e5f6
Revises: 77d916675066
Create Date: 2026-03-01

"""
from alembic import op
import sqlalchemy as sa


revision = 'a1b2c3d4e5f6'
down_revision = '77d916675066'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'fuel_expense',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('district_id', sa.Integer(), nullable=True),
        sa.Column('project_id', sa.Integer(), nullable=True),
        sa.Column('vehicle_id', sa.Integer(), nullable=False),
        sa.Column('fueling_date', sa.Date(), nullable=False),
        sa.Column('card_swipe_date', sa.Date(), nullable=True),
        sa.Column('payment_type', sa.String(length=20), nullable=True),
        sa.Column('slip_no', sa.String(length=50), nullable=True),
        sa.Column('previous_reading', sa.Numeric(12, 2), nullable=True),
        sa.Column('current_reading', sa.Numeric(12, 2), nullable=False),
        sa.Column('km', sa.Numeric(12, 2), nullable=True),
        sa.Column('fuel_price', sa.Numeric(12, 2), nullable=True),
        sa.Column('liters', sa.Numeric(12, 2), nullable=True),
        sa.Column('mpg', sa.Numeric(12, 2), nullable=True),
        sa.Column('amount', sa.Numeric(12, 2), nullable=True),
        sa.Column('km_out_task', sa.Numeric(12, 2), nullable=True),
        sa.Column('km_in_task', sa.Numeric(12, 2), nullable=True),
        sa.Column('meter_reading_matched', sa.String(length=10), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['district_id'], ['district.id'], ),
        sa.ForeignKeyConstraint(['project_id'], ['project.id'], ),
        sa.ForeignKeyConstraint(['vehicle_id'], ['vehicle.id'], ),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('fuel_expense')
