"""add client_diagnostic_log table for per-device errors and slow loads

Revision ID: y2z3a4b5c6d7
Revises: u1v2w3x4y5z6
Create Date: 2026-06-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "y2z3a4b5c6d7"
down_revision = "u1v2w3x4y5z6"
branch_labels = None
depends_on = None


def _table_exists(bind, name):
    return name in inspect(bind).get_table_names()


def upgrade():
    bind = op.get_bind()
    if _table_exists(bind, "client_diagnostic_log"):
        return
    op.create_table(
        "client_diagnostic_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("login_log_id", sa.Integer(), nullable=True),
        sa.Column("device_id", sa.String(length=80), nullable=True),
        sa.Column("user_agent", sa.String(length=500), nullable=True),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("page_path", sa.String(length=500), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("device_model", sa.String(length=120), nullable=True),
        sa.Column("os_version", sa.String(length=80), nullable=True),
        sa.Column("network_type", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["login_log_id"], ["login_log.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_client_diagnostic_log_user_id", "client_diagnostic_log", ["user_id"])
    op.create_index("ix_client_diagnostic_log_device_id", "client_diagnostic_log", ["device_id"])
    op.create_index("ix_client_diagnostic_log_event_type", "client_diagnostic_log", ["event_type"])
    op.create_index("ix_client_diagnostic_log_created_at", "client_diagnostic_log", ["created_at"])


def downgrade():
    bind = op.get_bind()
    if not _table_exists(bind, "client_diagnostic_log"):
        return
    op.drop_index("ix_client_diagnostic_log_created_at", table_name="client_diagnostic_log")
    op.drop_index("ix_client_diagnostic_log_event_type", table_name="client_diagnostic_log")
    op.drop_index("ix_client_diagnostic_log_device_id", table_name="client_diagnostic_log")
    op.drop_index("ix_client_diagnostic_log_user_id", table_name="client_diagnostic_log")
    op.drop_table("client_diagnostic_log")
