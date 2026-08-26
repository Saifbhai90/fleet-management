"""vehicle_activity_sync_status — last activity/trips sync + fail remarks

Revision ID: act_sync_sts_01
Revises: act_trip_rec_01
Create Date: 2026-08-26
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "act_sync_sts_01"
down_revision = "act_trip_rec_01"
branch_labels = None
depends_on = None


def _table_exists(bind, name):
    return name in inspect(bind).get_table_names()


def upgrade():
    bind = op.get_bind()
    table = "vehicle_activity_sync_status"
    if _table_exists(bind, table):
        return
    op.create_table(
        table,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("portalxs_account.id", ondelete="CASCADE"), nullable=True),
        sa.Column("task_date", sa.Date(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("fetched_count", sa.Integer(), nullable=True),
        sa.Column("error_count", sa.Integer(), nullable=True),
        sa.Column("error_remarks", sa.Text(), nullable=True),
        sa.UniqueConstraint("account_id", "task_date", name="uq_activity_sync_acct_day"),
    )
    op.create_index("ix_vehicle_activity_sync_status_account_id", table, ["account_id"])
    op.create_index("ix_vehicle_activity_sync_status_task_date", table, ["task_date"])
    op.create_index("ix_vehicle_activity_sync_status_last_synced_at", table, ["last_synced_at"])


def downgrade():
    bind = op.get_bind()
    table = "vehicle_activity_sync_status"
    if not _table_exists(bind, table):
        return
    for idx in (
        "ix_vehicle_activity_sync_status_last_synced_at",
        "ix_vehicle_activity_sync_status_task_date",
        "ix_vehicle_activity_sync_status_account_id",
    ):
        try:
            op.drop_index(idx, table_name=table)
        except Exception:
            pass
    op.drop_table(table)
