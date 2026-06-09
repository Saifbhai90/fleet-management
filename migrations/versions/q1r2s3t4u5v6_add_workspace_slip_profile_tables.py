"""add workspace slip profile tables

Revision ID: q1r2s3t4u5v6
Revises: p8q9r0s1t2u3
Create Date: 2026-06-05
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "q1r2s3t4u5v6"
down_revision = "p8q9r0s1t2u3"
branch_labels = None
depends_on = None


def _table_exists(bind, table_name):
    return table_name in inspect(bind).get_table_names()


def upgrade():
    bind = op.get_bind()
    if not _table_exists(bind, "workspace_slip_profile"):
        op.create_table(
            "workspace_slip_profile",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("employee_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("fingerprint_keywords", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["employee_id"], ["employee.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_workspace_slip_profile_employee_id", "workspace_slip_profile", ["employee_id"])

    if not _table_exists(bind, "workspace_slip_profile_field"):
        op.create_table(
            "workspace_slip_profile_field",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("profile_id", sa.Integer(), nullable=False),
            sa.Column("field_key", sa.String(length=30), nullable=False),
            sa.Column("region_x", sa.Numeric(precision=6, scale=2), nullable=False, server_default="0"),
            sa.Column("region_y", sa.Numeric(precision=6, scale=2), nullable=False, server_default="0"),
            sa.Column("region_w", sa.Numeric(precision=6, scale=2), nullable=False, server_default="100"),
            sa.Column("region_h", sa.Numeric(precision=6, scale=2), nullable=False, server_default="100"),
            sa.ForeignKeyConstraint(["profile_id"], ["workspace_slip_profile.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("profile_id", "field_key", name="uq_ws_slip_profile_field"),
        )
        op.create_index("ix_workspace_slip_profile_field_profile_id", "workspace_slip_profile_field", ["profile_id"])


def downgrade():
    bind = op.get_bind()
    if _table_exists(bind, "workspace_slip_profile_field"):
        op.drop_table("workspace_slip_profile_field")
    if _table_exists(bind, "workspace_slip_profile"):
        op.drop_table("workspace_slip_profile")
