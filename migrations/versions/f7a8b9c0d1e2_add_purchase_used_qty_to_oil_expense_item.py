"""add purchase_qty and used_qty to oil_expense_item

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-03-01

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = 'f7a8b9c0d1e2'
down_revision = 'e6f7a8b9c0d1'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if 'oil_expense_item' not in insp.get_table_names():
        return
    cols = [c['name'] for c in insp.get_columns('oil_expense_item')]
    if 'purchase_qty' not in cols:
        op.add_column('oil_expense_item', sa.Column('purchase_qty', sa.Numeric(12, 2), nullable=True))
    if 'used_qty' not in cols:
        op.add_column('oil_expense_item', sa.Column('used_qty', sa.Numeric(12, 2), nullable=True))
    try:
        op.execute(text("UPDATE oil_expense_item SET purchase_qty = qty WHERE purchase_qty IS NULL AND qty IS NOT NULL"))
        op.execute(text("UPDATE oil_expense_item SET used_qty = 0 WHERE used_qty IS NULL"))
    except Exception:
        pass


def downgrade():
    with op.batch_alter_table('oil_expense_item') as batch:
        batch.drop_column('used_qty')
        batch.drop_column('purchase_qty')
