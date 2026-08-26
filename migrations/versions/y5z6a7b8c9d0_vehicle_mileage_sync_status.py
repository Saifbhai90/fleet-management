"""vehicle_mileage_sync_status — last PortalXS fetch per account/day

Revision ID: y5z6a7b8c9d0
Revises: x4y5z6a7b8c9
Create Date: 2026-08-26
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "y5z6a7b8c9d0"
down_revision = "x4y5z6a7b8c9"
branch_labels = None
depends_on = None


def _table_exists(bind, name):
    return name in inspect(bind).get_table_names()


def upgrade():
    bind = op.get_bind()
    if _table_exists(bind, "vehicle_mileage_sync_status"):
        return
    op.create_table(
        "vehicle_mileage_sync_status",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("task_date", sa.Date(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("fetched_count", sa.Integer(), nullable=True),
        sa.Column("error_count", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["portalxs_account.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "task_date", name="uq_mileage_sync_acct_day"),
    )
    op.create_index("ix_vehicle_mileage_sync_status_account_id", "vehicle_mileage_sync_status", ["account_id"])
    op.create_index("ix_vehicle_mileage_sync_status_task_date", "vehicle_mileage_sync_status", ["task_date"])
    op.create_index("ix_vehicle_mileage_sync_status_last_synced_at", "vehicle_mileage_sync_status", ["last_synced_at"])


def downgrade():
    bind = op.get_bind()
    if not _table_exists(bind, "vehicle_mileage_sync_status"):
        return
    op.drop_index("ix_vehicle_mileage_sync_status_last_synced_at", table_name="vehicle_mileage_sync_status")
    op.drop_index("ix_vehicle_mileage_sync_status_task_date", table_name="vehicle_mileage_sync_status")
    op.drop_index("ix_vehicle_mileage_sync_status_account_id", table_name="vehicle_mileage_sync_status")
    op.drop_table("vehicle_mileage_sync_status")
