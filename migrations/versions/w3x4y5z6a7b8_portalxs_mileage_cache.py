"""portalxs_mileage_cache — persist mileage report rows per date range

Revision ID: w3x4y5z6a7b8
Revises: v2w3x4y5z6a7
Create Date: 2026-08-26
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "w3x4y5z6a7b8"
down_revision = "v2w3x4y5z6a7"
branch_labels = None
depends_on = None


def _table_exists(bind, name):
    return name in inspect(bind).get_table_names()


def upgrade():
    bind = op.get_bind()
    if _table_exists(bind, "portalxs_mileage_cache"):
        return
    op.create_table(
        "portalxs_mileage_cache",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("query_from", sa.Date(), nullable=False),
        sa.Column("query_to", sa.Date(), nullable=False),
        sa.Column("regno", sa.String(length=50), nullable=False),
        sa.Column("vehicle_no", sa.String(length=80), nullable=True),
        sa.Column("date_from", sa.String(length=40), nullable=True),
        sa.Column("time_from", sa.String(length=20), nullable=True),
        sa.Column("date_to", sa.String(length=40), nullable=True),
        sa.Column("time_to", sa.String(length=20), nullable=True),
        sa.Column("mileage", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("ptop", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["portalxs_account.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "query_from", "query_to", "regno", name="uq_portalxs_mileage_range_regno"),
    )
    op.create_index("ix_portalxs_mileage_cache_account_id", "portalxs_mileage_cache", ["account_id"])
    op.create_index("ix_portalxs_mileage_cache_regno", "portalxs_mileage_cache", ["regno"])
    op.create_index("ix_portalxs_mileage_range", "portalxs_mileage_cache", ["account_id", "query_from", "query_to"])


def downgrade():
    bind = op.get_bind()
    if not _table_exists(bind, "portalxs_mileage_cache"):
        return
    op.drop_index("ix_portalxs_mileage_range", table_name="portalxs_mileage_cache")
    op.drop_index("ix_portalxs_mileage_cache_regno", table_name="portalxs_mileage_cache")
    op.drop_index("ix_portalxs_mileage_cache_account_id", table_name="portalxs_mileage_cache")
    op.drop_table("portalxs_mileage_cache")
