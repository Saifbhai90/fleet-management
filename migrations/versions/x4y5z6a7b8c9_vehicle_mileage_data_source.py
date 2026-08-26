"""Add data_source to vehicle_mileage_record (excel vs portalxs)

Revision ID: x4y5z6a7b8c9
Revises: w3x4y5z6a7b8
Create Date: 2026-08-26
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "x4y5z6a7b8c9"
down_revision = "w3x4y5z6a7b8"
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
    if not _table_exists(bind, "vehicle_mileage_record"):
        return
    if not _column_exists(bind, "vehicle_mileage_record", "data_source"):
        op.add_column(
            "vehicle_mileage_record",
            sa.Column("data_source", sa.String(length=20), nullable=True),
        )
    if not _index_exists(bind, "vehicle_mileage_record", "ix_vehicle_mileage_record_data_source"):
        op.create_index(
            "ix_vehicle_mileage_record_data_source",
            "vehicle_mileage_record",
            ["data_source"],
        )
    # Existing rows came from Excel uploads — protect them from PortalXS overwrite
    op.execute(
        sa.text(
            "UPDATE vehicle_mileage_record SET data_source = 'excel' "
            "WHERE data_source IS NULL"
        )
    )


def downgrade():
    bind = op.get_bind()
    if not _table_exists(bind, "vehicle_mileage_record"):
        return
    if _index_exists(bind, "vehicle_mileage_record", "ix_vehicle_mileage_record_data_source"):
        op.drop_index("ix_vehicle_mileage_record_data_source", table_name="vehicle_mileage_record")
    if _column_exists(bind, "vehicle_mileage_record", "data_source"):
        op.drop_column("vehicle_mileage_record", "data_source")
