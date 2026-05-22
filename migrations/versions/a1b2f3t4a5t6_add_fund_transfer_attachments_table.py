"""Add fund transfer attachments table (multiple images/PDFs).

Revision ID: a1b2f3t4a5t6
Revises: x0y1z2a3b4c5
Create Date: 2026-05-22
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "a1b2f3t4a5t6"
down_revision = "x0y1z2a3b4c5"
branch_labels = None
depends_on = None


def _table_exists(bind, table_name):
    return table_name in inspect(bind).get_table_names()


def _index_exists(bind, table_name, index_name):
    if not _table_exists(bind, table_name):
        return False
    idxs = inspect(bind).get_indexes(table_name)
    return any(i.get("name") == index_name for i in idxs)


def upgrade():
    bind = op.get_bind()
    table = "fund_transfer_attachment"
    if not _table_exists(bind, table):
        op.create_table(
            table,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("fund_transfer_id", sa.Integer(), sa.ForeignKey("fund_transfer.id", ondelete="CASCADE"), nullable=False),
            sa.Column("file_path", sa.String(length=2048), nullable=False),
            sa.Column("file_type", sa.String(length=20), nullable=True),
            sa.Column("original_name", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
    if _table_exists(bind, table) and not _index_exists(bind, table, "ix_fund_transfer_attachment_fund_transfer_id"):
        op.create_index("ix_fund_transfer_attachment_fund_transfer_id", table, ["fund_transfer_id"], unique=False)


def downgrade():
    bind = op.get_bind()
    table = "fund_transfer_attachment"
    if _table_exists(bind, table) and _index_exists(bind, table, "ix_fund_transfer_attachment_fund_transfer_id"):
        op.drop_index("ix_fund_transfer_attachment_fund_transfer_id", table_name=table)
    if _table_exists(bind, table):
        op.drop_table(table)
