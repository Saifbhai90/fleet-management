"""add workspace mpg report input table

Revision ID: e4f5a6b7c8d9
Revises: d1e2f3a4b5c6
Create Date: 2026-04-12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "e4f5a6b7c8d9"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def _table_exists(bind, table_name):
    return table_name in inspect(bind).get_table_names()


def _index_exists(bind, table_name, index_name):
    if not _table_exists(bind, table_name):
        return False
    indexes = inspect(bind).get_indexes(table_name)
    return any(i.get("name") == index_name for i in indexes)


def upgrade():
    bind = op.get_bind()
    if not _table_exists(bind, "workspace_mpg_report_input"):
        op.create_table(
            "workspace_mpg_report_input",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("employee_id", sa.Integer(), nullable=False),
            sa.Column("vehicle_id", sa.Integer(), nullable=False),
            sa.Column("from_date", sa.Date(), nullable=False),
            sa.Column("to_date", sa.Date(), nullable=False),
            sa.Column("current_odoo_meter_reading", sa.Numeric(12, 2), nullable=True),
            sa.Column("today_fuel", sa.Numeric(12, 2), nullable=True),
            sa.Column("created_by_user_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["created_by_user_id"], ["user.id"]),
            sa.ForeignKeyConstraint(["employee_id"], ["employee.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["vehicle_id"], ["vehicle.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "employee_id",
                "vehicle_id",
                "from_date",
                "to_date",
                name="uq_workspace_mpg_input_scope",
            ),
        )

    if not _index_exists(bind, "workspace_mpg_report_input", "ix_workspace_mpg_report_input_employee_id"):
        op.create_index(
            "ix_workspace_mpg_report_input_employee_id",
            "workspace_mpg_report_input",
            ["employee_id"],
            unique=False,
        )
    if not _index_exists(bind, "workspace_mpg_report_input", "ix_workspace_mpg_report_input_vehicle_id"):
        op.create_index(
            "ix_workspace_mpg_report_input_vehicle_id",
            "workspace_mpg_report_input",
            ["vehicle_id"],
            unique=False,
        )
    if not _index_exists(bind, "workspace_mpg_report_input", "ix_workspace_mpg_report_input_from_date"):
        op.create_index(
            "ix_workspace_mpg_report_input_from_date",
            "workspace_mpg_report_input",
            ["from_date"],
            unique=False,
        )
    if not _index_exists(bind, "workspace_mpg_report_input", "ix_workspace_mpg_report_input_to_date"):
        op.create_index(
            "ix_workspace_mpg_report_input_to_date",
            "workspace_mpg_report_input",
            ["to_date"],
            unique=False,
        )


def downgrade():
    bind = op.get_bind()
    if not _table_exists(bind, "workspace_mpg_report_input"):
        return

    for idx_name in (
        "ix_workspace_mpg_report_input_to_date",
        "ix_workspace_mpg_report_input_from_date",
        "ix_workspace_mpg_report_input_vehicle_id",
        "ix_workspace_mpg_report_input_employee_id",
    ):
        if _index_exists(bind, "workspace_mpg_report_input", idx_name):
            op.drop_index(idx_name, table_name="workspace_mpg_report_input")
    op.drop_table("workspace_mpg_report_input")
