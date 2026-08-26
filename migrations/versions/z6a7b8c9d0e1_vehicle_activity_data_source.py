"""Add data_source to vehicle_activity_record (excel vs portalxs)

Revision ID: z6a7b8c9d0e1
Revises: y5z6a7b8c9d0
Create Date: 2026-08-26
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "z6a7b8c9d0e1"
down_revision = "y5z6a7b8c9d0"
branch_labels = None
depends_on = None


def _table_exists(bind, name):
    return name in inspect(bind).get_table_names()


def _column_exists(bind, table, column):
    try:
        return any(c["name"] == column for c in inspect(bind).get_columns(table))
    except Exception:
        return False


def _index_exists(bind, table_name, index_name):
    try:
        return any(ix["name"] == index_name for ix in inspect(bind).get_indexes(table_name))
    except Exception:
        return False


def upgrade():
    bind = op.get_bind()
    table = "vehicle_activity_record"
    if not _table_exists(bind, table):
        return
    if not _column_exists(bind, table, "data_source"):
        op.add_column(table, sa.Column("data_source", sa.String(length=20), nullable=True))
    # No backfill and no index here on purpose: this table holds millions of GPS
    # points, so an UPDATE or CREATE INDEX over it outlasts the boot window and
    # fails the deploy. Legacy rows keep data_source NULL, which the activity
    # service already treats as an Excel upload (never overwritten by PortalXS).


def downgrade():
    bind = op.get_bind()
    table = "vehicle_activity_record"
    if not _table_exists(bind, table):
        return
    idx = "ix_vehicle_activity_record_data_source"
    if _index_exists(bind, table, idx):
        op.drop_index(idx, table_name=table)
    if _column_exists(bind, table, "data_source"):
        op.drop_column(table, "data_source")
