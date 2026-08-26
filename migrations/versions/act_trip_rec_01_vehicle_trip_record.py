"""Add vehicle_trip_record for PortalXS trips synced with GPS activity

Revision ID: act_trip_rec_01
Revises: z6a7b8c9d0e1
Create Date: 2026-08-26
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "act_trip_rec_01"
down_revision = "z6a7b8c9d0e1"
branch_labels = None
depends_on = None


def _table_exists(bind, name):
    return name in inspect(bind).get_table_names()


def upgrade():
    bind = op.get_bind()
    table = "vehicle_trip_record"
    if _table_exists(bind, table):
        return
    op.create_table(
        table,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_date", sa.Date(), nullable=False),
        sa.Column("upload_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("vehicle_no", sa.String(length=50), nullable=False),
        sa.Column("igon_rdt", sa.String(length=50), nullable=True),
        sa.Column("igon_lat", sa.Numeric(10, 6), nullable=True),
        sa.Column("igon_lon", sa.Numeric(10, 6), nullable=True),
        sa.Column("igon_landmark", sa.Text(), nullable=True),
        sa.Column("igoff_rdt", sa.String(length=50), nullable=True),
        sa.Column("igoff_lat", sa.Numeric(10, 6), nullable=True),
        sa.Column("igoff_lon", sa.Numeric(10, 6), nullable=True),
        sa.Column("igoff_landmark", sa.Text(), nullable=True),
        sa.Column("mileage", sa.Numeric(12, 2), nullable=True),
        sa.Column("travel_time_s", sa.String(length=30), nullable=True),
        sa.Column("max_speed", sa.Numeric(12, 2), nullable=True),
        sa.Column("avg_speed", sa.Numeric(12, 2), nullable=True),
        sa.Column("trip_status", sa.String(length=50), nullable=True),
        sa.Column("data_source", sa.String(length=20), nullable=True),
    )
    op.create_index("ix_vehicle_trip_record_task_date", table, ["task_date"])
    op.create_index("ix_vehicle_trip_record_vehicle_no", table, ["vehicle_no"])
    op.create_index("ix_vehicle_trip_record_data_source", table, ["data_source"])
    op.create_index(
        "ix_vehicle_trip_record_task_date_vehicle_no",
        table,
        ["task_date", "vehicle_no"],
    )


def downgrade():
    bind = op.get_bind()
    table = "vehicle_trip_record"
    if not _table_exists(bind, table):
        return
    for idx in (
        "ix_vehicle_trip_record_task_date_vehicle_no",
        "ix_vehicle_trip_record_data_source",
        "ix_vehicle_trip_record_vehicle_no",
        "ix_vehicle_trip_record_task_date",
    ):
        try:
            op.drop_index(idx, table_name=table)
        except Exception:
            pass
    op.drop_table(table)
