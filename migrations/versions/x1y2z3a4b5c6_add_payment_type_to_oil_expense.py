"""Add payment_type to oil_expense.

Revision ID: x1y2z3a4b5c6
Revises: d1e2f3a4b5c6
Create Date: 2026-04-14 15:10:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "x1y2z3a4b5c6"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def _table_exists(bind, table_name):
    return table_name in inspect(bind).get_table_names()


def _column_exists(bind, table_name, column_name):
    if not _table_exists(bind, table_name):
        return False
    cols = inspect(bind).get_columns(table_name)
    return any(c.get("name") == column_name for c in cols)


def upgrade():
    bind = op.get_bind()
    table = "oil_expense"
    if _table_exists(bind, table) and not _column_exists(bind, table, "payment_type"):
        op.add_column(table, sa.Column("payment_type", sa.String(length=20), nullable=True))


def downgrade():
    bind = op.get_bind()
    table = "oil_expense"
    if _table_exists(bind, table) and _column_exists(bind, table, "payment_type"):
        op.drop_column(table, "payment_type")
