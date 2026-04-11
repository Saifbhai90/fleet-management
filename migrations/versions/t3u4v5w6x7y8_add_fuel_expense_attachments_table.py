"""Add fuel expense attachments table.

Revision ID: t3u4v5w6x7y8
Revises: s2t3u4v5w6x7
Create Date: 2026-04-11 19:40:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "t3u4v5w6x7y8"
down_revision = "s2t3u4v5w6x7"
branch_labels = None
depends_on = None


def _table_exists(bind, table_name):
    return table_name in inspect(bind).get_table_names()


def _index_exists(bind, table_name, index_name):
    if not _table_exists(bind, table_name):
        return False
    idxs = inspect(bind).get_indexes(table_name)
    return any(i.get("name") == index_name for i in idxs)


def upgrade():
    bind = op.get_bind()
    table = "fuel_expense_attachment"
    if not _table_exists(bind, table):
        op.create_table(
            table,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("fuel_expense_id", sa.Integer(), sa.ForeignKey("fuel_expense.id"), nullable=False),
            sa.Column("file_path", sa.String(length=500), nullable=False),
            sa.Column("file_type", sa.String(length=20), nullable=True),
            sa.Column("original_name", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
    if _table_exists(bind, table) and not _index_exists(bind, table, "ix_fuel_expense_attachment_fuel_expense_id"):
        op.create_index("ix_fuel_expense_attachment_fuel_expense_id", table, ["fuel_expense_id"], unique=False)


def downgrade():
    bind = op.get_bind()
    table = "fuel_expense_attachment"
    if _table_exists(bind, table) and _index_exists(bind, table, "ix_fuel_expense_attachment_fuel_expense_id"):
        op.drop_index("ix_fuel_expense_attachment_fuel_expense_id", table_name=table)
    if _table_exists(bind, table):
        op.drop_table(table)
