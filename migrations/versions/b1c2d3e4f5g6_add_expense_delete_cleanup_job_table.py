"""add expense delete cleanup job table

Revision ID: b1c2d3e4f5g6
Revises: z9a8b7c6d5e4
Create Date: 2026-04-12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "b1c2d3e4f5g6"
down_revision = "z9a8b7c6d5e4"
branch_labels = None
depends_on = None


def _table_exists(bind, table_name):
    return table_name in inspect(bind).get_table_names()


def upgrade():
    bind = op.get_bind()
    if _table_exists(bind, "expense_delete_cleanup_job"):
        return
    op.create_table(
        "expense_delete_cleanup_job",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employee.id", ondelete="CASCADE"), nullable=False),
        sa.Column("expense_kind", sa.String(length=20), nullable=False),
        sa.Column("expense_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="processing"),
        sa.Column("total_files", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deleted_files", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_files", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pending_paths_json", sa.Text(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("initiated_by_user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_expense_delete_cleanup_job_employee_id", "expense_delete_cleanup_job", ["employee_id"], unique=False)
    op.create_index("ix_expense_delete_cleanup_job_expense_kind", "expense_delete_cleanup_job", ["expense_kind"], unique=False)
    op.create_index("ix_expense_delete_cleanup_job_expense_id", "expense_delete_cleanup_job", ["expense_id"], unique=False)
    op.create_index("ix_expense_delete_cleanup_job_status", "expense_delete_cleanup_job", ["status"], unique=False)


def downgrade():
    bind = op.get_bind()
    if not _table_exists(bind, "expense_delete_cleanup_job"):
        return
    try:
        op.drop_index("ix_expense_delete_cleanup_job_status", table_name="expense_delete_cleanup_job")
        op.drop_index("ix_expense_delete_cleanup_job_expense_id", table_name="expense_delete_cleanup_job")
        op.drop_index("ix_expense_delete_cleanup_job_expense_kind", table_name="expense_delete_cleanup_job")
        op.drop_index("ix_expense_delete_cleanup_job_employee_id", table_name="expense_delete_cleanup_job")
    except Exception:
        pass
    op.drop_table("expense_delete_cleanup_job")
"""add expense delete cleanup job table

Revision ID: b1c2d3e4f5g6
Revises: z9a8b7c6d5e4
Create Date: 2026-04-12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "b1c2d3e4f5g6"
down_revision = "z9a8b7c6d5e4"
branch_labels = None
depends_on = None


def _table_exists(bind, table_name):
    return table_name in inspect(bind).get_table_names()


def upgrade():
    bind = op.get_bind()
    if _table_exists(bind, "expense_delete_cleanup_job"):
        return
    op.create_table(
        "expense_delete_cleanup_job",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employee.id", ondelete="CASCADE"), nullable=False),
        sa.Column("expense_kind", sa.String(length=20), nullable=False),
        sa.Column("expense_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="processing"),
        sa.Column("total_files", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deleted_files", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_files", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pending_paths_json", sa.Text(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("initiated_by_user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_expense_delete_cleanup_job_employee_id", "expense_delete_cleanup_job", ["employee_id"], unique=False)
    op.create_index("ix_expense_delete_cleanup_job_expense_kind", "expense_delete_cleanup_job", ["expense_kind"], unique=False)
    op.create_index("ix_expense_delete_cleanup_job_expense_id", "expense_delete_cleanup_job", ["expense_id"], unique=False)
    op.create_index("ix_expense_delete_cleanup_job_status", "expense_delete_cleanup_job", ["status"], unique=False)


def downgrade():
    bind = op.get_bind()
    if not _table_exists(bind, "expense_delete_cleanup_job"):
        return
    try:
        op.drop_index("ix_expense_delete_cleanup_job_status", table_name="expense_delete_cleanup_job")
        op.drop_index("ix_expense_delete_cleanup_job_expense_id", table_name="expense_delete_cleanup_job")
        op.drop_index("ix_expense_delete_cleanup_job_expense_kind", table_name="expense_delete_cleanup_job")
        op.drop_index("ix_expense_delete_cleanup_job_employee_id", table_name="expense_delete_cleanup_job")
    except Exception:
        pass
    op.drop_table("expense_delete_cleanup_job")
