"""add vehicle target mpg and fuel tank capacity

Revision ID: d1e2f3a4b5c6
Revises: c7d8e9f0a1b2
Create Date: 2026-04-12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "d1e2f3a4b5c6"
down_revision = "c7d8e9f0a1b2"
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
    if not _table_exists(bind, "vehicle"):
        return
    with op.batch_alter_table("vehicle") as batch_op:
        if not _column_exists(bind, "vehicle", "target_mpg"):
            batch_op.add_column(sa.Column("target_mpg", sa.Numeric(10, 2), nullable=False, server_default="0"))
        if not _column_exists(bind, "vehicle", "fuel_tank_capacity"):
            batch_op.add_column(sa.Column("fuel_tank_capacity", sa.Numeric(10, 2), nullable=False, server_default="0"))


def downgrade():
    bind = op.get_bind()
    if not _table_exists(bind, "vehicle"):
        return
    with op.batch_alter_table("vehicle") as batch_op:
        if _column_exists(bind, "vehicle", "fuel_tank_capacity"):
            batch_op.drop_column("fuel_tank_capacity")
        if _column_exists(bind, "vehicle", "target_mpg"):
            batch_op.drop_column("target_mpg")
