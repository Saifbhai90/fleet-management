"""shared workspace slip profiles (company-wide, all employee workspaces)

Revision ID: r7s8t9u0v1w2
Revises: q1r2s3t4u5v6
Create Date: 2026-06-08
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "r7s8t9u0v1w2"
down_revision = "q1r2s3t4u5v6"
branch_labels = None
depends_on = None


def _table_exists(bind, table_name):
    return table_name in inspect(bind).get_table_names()


def upgrade():
    bind = op.get_bind()
    if not _table_exists(bind, "workspace_slip_profile"):
        return
    with op.batch_alter_table("workspace_slip_profile", schema=None) as batch_op:
        batch_op.alter_column(
            "employee_id",
            existing_type=sa.Integer(),
            nullable=True,
        )
    op.execute(sa.text("UPDATE workspace_slip_profile SET employee_id = NULL"))


def downgrade():
    bind = op.get_bind()
    if not _table_exists(bind, "workspace_slip_profile"):
        return
    with op.batch_alter_table("workspace_slip_profile", schema=None) as batch_op:
        batch_op.alter_column(
            "employee_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
