"""add oil expense and product balance tables

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-03-01

"""
from alembic import op
import sqlalchemy as sa


revision = 'e6f7a8b9c0d1'
down_revision = 'd5e6f7a8b9c0'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'product_balance',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('balance_qty', sa.Numeric(12, 2), nullable=False, server_default='0'),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['product_id'], ['product.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('product_id')
    )
    op.create_table(
        'oil_expense',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('district_id', sa.Integer(), nullable=True),
        sa.Column('project_id', sa.Integer(), nullable=True),
        sa.Column('vehicle_id', sa.Integer(), nullable=False),
        sa.Column('expense_date', sa.Date(), nullable=False),
        sa.Column('card_swipe_date', sa.Date(), nullable=True),
        sa.Column('previous_reading', sa.Numeric(12, 2), nullable=True),
        sa.Column('current_reading', sa.Numeric(12, 2), nullable=True),
        sa.Column('km', sa.Numeric(12, 2), nullable=True),
        sa.Column('remarks', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['district_id'], ['district.id'], ),
        sa.ForeignKeyConstraint(['project_id'], ['project.id'], ),
        sa.ForeignKeyConstraint(['vehicle_id'], ['vehicle.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table(
        'oil_expense_item',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('oil_expense_id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('payment_type', sa.String(30), nullable=True),
        sa.Column('qty', sa.Numeric(12, 2), nullable=False, server_default='0'),
        sa.Column('price', sa.Numeric(12, 2), nullable=True, server_default='0'),
        sa.Column('amount', sa.Numeric(12, 2), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['oil_expense_id'], ['oil_expense.id'], ),
        sa.ForeignKeyConstraint(['product_id'], ['product.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table(
        'oil_expense_attachment',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('oil_expense_id', sa.Integer(), nullable=False),
        sa.Column('file_path', sa.String(500), nullable=False),
        sa.Column('file_type', sa.String(20), nullable=True),
        sa.Column('original_name', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['oil_expense_id'], ['oil_expense.id'], ),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('oil_expense_attachment')
    op.drop_table('oil_expense_item')
    op.drop_table('oil_expense')
    op.drop_table('product_balance')
