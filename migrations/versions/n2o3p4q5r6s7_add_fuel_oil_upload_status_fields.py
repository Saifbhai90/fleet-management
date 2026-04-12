"""Add fuel/oil upload status fields for async media processing.

Revision ID: n2o3p4q5r6s7
Revises: m1n2o3p4q5r6
Create Date: 2026-04-12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "n2o3p4q5r6s7"
down_revision = "m1n2o3p4q5r6"
branch_labels = None
depends_on = None


def _table_exists(bind, table_name):
    return table_name in inspect(bind).get_table_names()


def _column_exists(bind, table_name, column_name):
    if not _table_exists(bind, table_name):
        return False
    cols = inspect(bind).get_columns(table_name)
    return any(c.get("name") == column_name for c in cols)


def _add_upload_columns(bind, table):
    if not _table_exists(bind, table):
        return
    with op.batch_alter_table(table) as batch_op:
        if not _column_exists(bind, table, "upload_status"):
            batch_op.add_column(sa.Column("upload_status", sa.String(length=20), nullable=True))
        if not _column_exists(bind, table, "upload_total"):
            batch_op.add_column(sa.Column("upload_total", sa.Integer(), nullable=False, server_default="0"))
        if not _column_exists(bind, table, "upload_done"):
            batch_op.add_column(sa.Column("upload_done", sa.Integer(), nullable=False, server_default="0"))
        if not _column_exists(bind, table, "upload_failed"):
            batch_op.add_column(sa.Column("upload_failed", sa.Integer(), nullable=False, server_default="0"))
        if not _column_exists(bind, table, "upload_error"):
            batch_op.add_column(sa.Column("upload_error", sa.Text(), nullable=True))
        if not _column_exists(bind, table, "upload_manifest_json"):
            batch_op.add_column(sa.Column("upload_manifest_json", sa.Text(), nullable=True))
        if not _column_exists(bind, table, "upload_started_at"):
            batch_op.add_column(sa.Column("upload_started_at", sa.DateTime(), nullable=True))
        if not _column_exists(bind, table, "upload_finished_at"):
            batch_op.add_column(sa.Column("upload_finished_at", sa.DateTime(), nullable=True))


def _drop_upload_columns(bind, table):
    if not _table_exists(bind, table):
        return
    with op.batch_alter_table(table) as batch_op:
        if _column_exists(bind, table, "upload_finished_at"):
            batch_op.drop_column("upload_finished_at")
        if _column_exists(bind, table, "upload_started_at"):
            batch_op.drop_column("upload_started_at")
        if _column_exists(bind, table, "upload_manifest_json"):
            batch_op.drop_column("upload_manifest_json")
        if _column_exists(bind, table, "upload_error"):
            batch_op.drop_column("upload_error")
        if _column_exists(bind, table, "upload_failed"):
            batch_op.drop_column("upload_failed")
        if _column_exists(bind, table, "upload_done"):
            batch_op.drop_column("upload_done")
        if _column_exists(bind, table, "upload_total"):
            batch_op.drop_column("upload_total")
        if _column_exists(bind, table, "upload_status"):
            batch_op.drop_column("upload_status")


def upgrade():
    bind = op.get_bind()
    for table in ("fuel_expense", "oil_expense"):
        _add_upload_columns(bind, table)
        try:
            op.create_index(f"ix_{table}_upload_status", table, ["upload_status"], unique=False)
        except Exception:
            pass
        op.execute(f"UPDATE {table} SET upload_status = COALESCE(upload_status, 'success')")


def downgrade():
    bind = op.get_bind()
    for table in ("fuel_expense", "oil_expense"):
        try:
            op.drop_index(f"ix_{table}_upload_status", table_name=table)
        except Exception:
            pass
        _drop_upload_columns(bind, table)
