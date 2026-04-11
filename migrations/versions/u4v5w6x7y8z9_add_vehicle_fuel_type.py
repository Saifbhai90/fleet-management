"""Add fuel_type column to vehicle.

Revision ID: u4v5w6x7y8z9
Revises: t3u4v5w6x7y8
Create Date: 2026-04-11 23:40:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "u4v5w6x7y8z9"
down_revision = "t3u4v5w6x7y8"
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
    table = "vehicle"

    if _table_exists(bind, table) and not _column_exists(bind, table, "fuel_type"):
        op.add_column(table, sa.Column("fuel_type", sa.String(length=20), nullable=True, server_default="Petrol"))

    if _table_exists(bind, table):
        op.execute(sa.text("UPDATE vehicle SET fuel_type = 'Petrol' WHERE fuel_type IS NULL OR trim(fuel_type) = ''"))

    if _table_exists(bind, table) and not _index_exists(bind, table, "ix_vehicle_fuel_type"):
        op.create_index("ix_vehicle_fuel_type", table, ["fuel_type"], unique=False)


def downgrade():
    bind = op.get_bind()
    table = "vehicle"

    if _table_exists(bind, table) and _index_exists(bind, table, "ix_vehicle_fuel_type"):
        op.drop_index("ix_vehicle_fuel_type", table_name=table)
    if _table_exists(bind, table) and _column_exists(bind, table, "fuel_type"):
        op.drop_column(table, "fuel_type")
