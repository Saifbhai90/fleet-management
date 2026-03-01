"""add party table and fuel_pump_id to fuel_expense

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-03-01

"""
from alembic import op
import sqlalchemy as sa


revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    # Party table may already exist from db.create_all(); create if not
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if 'party' not in insp.get_table_names():
        op.create_table(
            'party',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(length=150), nullable=False),
            sa.Column('party_type', sa.String(length=30), nullable=False),
            sa.Column('contact', sa.String(length=100), nullable=True),
            sa.Column('address', sa.String(length=255), nullable=True),
            sa.Column('remarks', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id')
        )
    with op.batch_alter_table('fuel_expense', schema=None) as batch_op:
        batch_op.add_column(sa.Column('fuel_pump_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_fuel_expense_fuel_pump_id', 'party', ['fuel_pump_id'], ['id'])


def downgrade():
    with op.batch_alter_table('fuel_expense', schema=None) as batch_op:
        batch_op.drop_constraint('fk_fuel_expense_fuel_pump_id', type_='foreignkey')
        batch_op.drop_column('fuel_pump_id')
    op.drop_table('party')
