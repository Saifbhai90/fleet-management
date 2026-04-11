"""Add payment_type, workspace_party_id, total_bill_amount to maintenance_expense.

Revision ID: v5w6x7y8z9a0
Revises: u4v5w6x7y8z9
Create Date: 2026-04-12 00:30:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "v5w6x7y8z9a0"
down_revision = "u4v5w6x7y8z9"
branch_labels = None
depends_on = None


def _table_exists(bind, table_name):
    return table_name in inspect(bind).get_table_names()


def _column_exists(bind, table_name, column_name):
    if not _table_exists(bind, table_name):
        return False
    cols = inspect(bind).get_columns(table_name)
    return any(c.get("name") == column_name for c in cols)


def _index_exists(bind, table_name, index_name):
    if not _table_exists(bind, table_name):
        return False
    idxs = inspect(bind).get_indexes(table_name)
    return any(i.get("name") == index_name for i in idxs)


def _fk_exists(bind, table_name, fk_name):
    if not _table_exists(bind, table_name):
        return False
    fks = inspect(bind).get_foreign_keys(table_name)
    return any((fk.get("name") or "") == fk_name for fk in fks)


def upgrade():
    bind = op.get_bind()
    table = "maintenance_expense"

    if _table_exists(bind, table) and not _column_exists(bind, table, "payment_type"):
        op.add_column(table, sa.Column("payment_type", sa.String(length=20), nullable=True))
    if _table_exists(bind, table) and not _column_exists(bind, table, "workspace_party_id"):
        op.add_column(table, sa.Column("workspace_party_id", sa.Integer(), nullable=True))
    if _table_exists(bind, table) and not _column_exists(bind, table, "total_bill_amount"):
        op.add_column(table, sa.Column("total_bill_amount", sa.Numeric(15, 2), nullable=True))

    if _table_exists(bind, table) and not _index_exists(bind, table, "ix_maintenance_expense_workspace_party_id"):
        op.create_index("ix_maintenance_expense_workspace_party_id", table, ["workspace_party_id"], unique=False)

    if (
        _table_exists(bind, table)
        and _table_exists(bind, "workspace_party")
        and _column_exists(bind, table, "workspace_party_id")
        and not _fk_exists(bind, table, "fk_maintenance_expense_workspace_party_id")
    ):
        op.create_foreign_key(
            "fk_maintenance_expense_workspace_party_id",
            "maintenance_expense",
            "workspace_party",
            ["workspace_party_id"],
            ["id"],
        )


def downgrade():
    bind = op.get_bind()
    table = "maintenance_expense"

    if _table_exists(bind, table) and _fk_exists(bind, table, "fk_maintenance_expense_workspace_party_id"):
        op.drop_constraint("fk_maintenance_expense_workspace_party_id", table, type_="foreignkey")
    if _table_exists(bind, table) and _index_exists(bind, table, "ix_maintenance_expense_workspace_party_id"):
        op.drop_index("ix_maintenance_expense_workspace_party_id", table_name=table)
    if _table_exists(bind, table) and _column_exists(bind, table, "total_bill_amount"):
        op.drop_column(table, "total_bill_amount")
    if _table_exists(bind, table) and _column_exists(bind, table, "workspace_party_id"):
        op.drop_column(table, "workspace_party_id")
    if _table_exists(bind, table) and _column_exists(bind, table, "payment_type"):
        op.drop_column(table, "payment_type")
