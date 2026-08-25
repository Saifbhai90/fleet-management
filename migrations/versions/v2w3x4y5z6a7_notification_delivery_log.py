"""notification_delivery_log — FCM push delivery audit

Revision ID: v2w3x4y5z6a7
Revises: u1f2o3n4e5r6
Create Date: 2026-08-26
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "v2w3x4y5z6a7"
down_revision = "u1f2o3n4e5r6"
branch_labels = None
depends_on = None


def _table_exists(bind, name):
    return name in inspect(bind).get_table_names()


def _index_exists(bind, table_name, index_name):
    try:
        return any(ix["name"] == index_name for ix in inspect(bind).get_indexes(table_name))
    except Exception:
        return False


def upgrade():
    bind = op.get_bind()
    if _table_exists(bind, "notification_delivery_log"):
        return
    op.create_table(
        "notification_delivery_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("notification_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("device_fcm_token_id", sa.Integer(), nullable=True),
        sa.Column("device_unique_id", sa.String(length=255), nullable=True),
        sa.Column("fcm_token_prefix", sa.String(length=32), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("body_preview", sa.String(length=200), nullable=True),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_code", sa.String(length=40), nullable=True),
        sa.Column("remarks", sa.String(length=500), nullable=True),
        sa.Column("fcm_message_id", sa.String(length=200), nullable=True),
        sa.Column("opened_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["notification_id"], ["notification.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notification_delivery_log_created_at", "notification_delivery_log", ["created_at"])
    op.create_index("ix_notification_delivery_log_user_id", "notification_delivery_log", ["user_id"])
    op.create_index("ix_notification_delivery_log_notification_id", "notification_delivery_log", ["notification_id"])
    op.create_index("ix_ndl_user_created", "notification_delivery_log", ["user_id", "created_at"])
    op.create_index("ix_ndl_status_created", "notification_delivery_log", ["status", "created_at"])


def downgrade():
    bind = op.get_bind()
    if not _table_exists(bind, "notification_delivery_log"):
        return
    for ix in (
        "ix_ndl_status_created",
        "ix_ndl_user_created",
        "ix_notification_delivery_log_notification_id",
        "ix_notification_delivery_log_user_id",
        "ix_notification_delivery_log_created_at",
    ):
        if _index_exists(bind, "notification_delivery_log", ix):
            op.drop_index(ix, table_name="notification_delivery_log")
    op.drop_table("notification_delivery_log")
