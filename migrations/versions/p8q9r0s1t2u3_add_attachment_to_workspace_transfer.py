"""add attachment to workspace transfer

Revision ID: p8q9r0s1t2u3
Revises: n7o8p9q0r1s2
Create Date: 2026-04-06
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "p8q9r0s1t2u3"
down_revision = "n7o8p9q0r1s2"
branch_labels = None
depends_on = None


def _table_exists(bind, table_name):
    return table_name in inspect(bind).get_table_names()


def _column_exists(bind, table_name, column_name):
    if not _table_exists(bind, table_name):
        return False
    cols = inspect(bind).get_columns(table_name)
    return any(c.get("name") == column_name for c in cols)


def upgrade():
    bind = op.get_bind()
    if _table_exists(bind, "workspace_fund_transfer") and not _column_exists(bind, "workspace_fund_transfer", "attachment"):
        op.add_column("workspace_fund_transfer", sa.Column("attachment", sa.String(length=500), nullable=True))


def downgrade():
    bind = op.get_bind()
    if _table_exists(bind, "workspace_fund_transfer") and _column_exists(bind, "workspace_fund_transfer", "attachment"):
        op.drop_column("workspace_fund_transfer", "attachment")
