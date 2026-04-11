"""Add maintenance job category fields.

Revision ID: s2t3u4v5w6x7
Revises: q9r0s1t2u3v4
Create Date: 2026-04-11 17:05:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "s2t3u4v5w6x7"
down_revision = "q9r0s1t2u3v4"
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


def upgrade():
    bind = op.get_bind()
    table = "maintenance_expense"

    if _table_exists(bind, table) and not _column_exists(bind, table, "job_category"):
        op.add_column(table, sa.Column("job_category", sa.String(length=120), nullable=True))
    if _table_exists(bind, table) and not _column_exists(bind, table, "job_interval_mode"):
        op.add_column(table, sa.Column("job_interval_mode", sa.String(length=20), nullable=True))
    if _table_exists(bind, table) and not _index_exists(bind, table, "ix_maintenance_expense_job_category"):
        op.create_index("ix_maintenance_expense_job_category", table, ["job_category"], unique=False)


def downgrade():
    bind = op.get_bind()
    table = "maintenance_expense"

    if _table_exists(bind, table) and _index_exists(bind, table, "ix_maintenance_expense_job_category"):
        op.drop_index("ix_maintenance_expense_job_category", table_name=table)
    if _table_exists(bind, table) and _column_exists(bind, table, "job_interval_mode"):
        op.drop_column(table, "job_interval_mode")
    if _table_exists(bind, table) and _column_exists(bind, table, "job_category"):
        op.drop_column(table, "job_category")
