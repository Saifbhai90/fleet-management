"""Add maintenance work order master and expense linkage.

Revision ID: z1y2x3w4v5u6
Revises: y7z8a9b0c1d2
Create Date: 2026-04-16 12:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "z1y2x3w4v5u6"
down_revision = "y7z8a9b0c1d2"
branch_labels = None
depends_on = None


def _table_exists(bind, table_name):
    return table_name in inspect(bind).get_table_names()


def _column_exists(bind, table_name, column_name):
    if not _table_exists(bind, table_name):
        return False
    cols = inspect(bind).get_columns(table_name)
    return any(c.get("name") == column_name for c in cols)


def _index_exists(bind, table_name, index_name):
    if not _table_exists(bind, table_name):
        return False
    idxs = inspect(bind).get_indexes(table_name)
    return any(i.get("name") == index_name for i in idxs)


def _fk_exists(bind, table_name, fk_name):
    if not _table_exists(bind, table_name):
        return False
    fks = inspect(bind).get_foreign_keys(table_name)
    return any((fk.get("name") or "") == fk_name for fk in fks)


def upgrade():
    bind = op.get_bind()

    if not _table_exists(bind, "maintenance_work_order"):
        op.create_table(
            "maintenance_work_order",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("work_order_no", sa.String(length=40), nullable=False),
            sa.Column("district_id", sa.Integer(), nullable=True),
            sa.Column("project_id", sa.Integer(), nullable=True),
            sa.Column("employee_id", sa.Integer(), nullable=True),
            sa.Column("vehicle_id", sa.Integer(), nullable=False),
            sa.Column("opened_on", sa.Date(), nullable=False),
            sa.Column("closed_on", sa.Date(), nullable=True),
            sa.Column("work_type", sa.String(length=120), nullable=True),
            sa.Column("title", sa.String(length=180), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
            sa.Column("remarks", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["district_id"], ["district.id"], name="fk_maintenance_work_order_district_id"),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], name="fk_maintenance_work_order_project_id"),
            sa.ForeignKeyConstraint(["employee_id"], ["employee.id"], name="fk_maintenance_work_order_employee_id"),
            sa.ForeignKeyConstraint(["vehicle_id"], ["vehicle.id"], name="fk_maintenance_work_order_vehicle_id"),
        )

    if _table_exists(bind, "maintenance_work_order") and not _index_exists(bind, "maintenance_work_order", "ix_maintenance_work_order_work_order_no"):
        op.create_index("ix_maintenance_work_order_work_order_no", "maintenance_work_order", ["work_order_no"], unique=True)
    if _table_exists(bind, "maintenance_work_order") and not _index_exists(bind, "maintenance_work_order", "ix_maintenance_work_order_status"):
        op.create_index("ix_maintenance_work_order_status", "maintenance_work_order", ["status"], unique=False)
    if _table_exists(bind, "maintenance_work_order") and not _index_exists(bind, "maintenance_work_order", "ix_maintenance_work_order_vehicle_id"):
        op.create_index("ix_maintenance_work_order_vehicle_id", "maintenance_work_order", ["vehicle_id"], unique=False)
    if _table_exists(bind, "maintenance_work_order") and not _index_exists(bind, "maintenance_work_order", "ix_maintenance_work_order_opened_on"):
        op.create_index("ix_maintenance_work_order_opened_on", "maintenance_work_order", ["opened_on"], unique=False)
    if _table_exists(bind, "maintenance_work_order") and not _index_exists(bind, "maintenance_work_order", "ix_maintenance_work_order_district_id"):
        op.create_index("ix_maintenance_work_order_district_id", "maintenance_work_order", ["district_id"], unique=False)
    if _table_exists(bind, "maintenance_work_order") and not _index_exists(bind, "maintenance_work_order", "ix_maintenance_work_order_project_id"):
        op.create_index("ix_maintenance_work_order_project_id", "maintenance_work_order", ["project_id"], unique=False)
    if _table_exists(bind, "maintenance_work_order") and not _index_exists(bind, "maintenance_work_order", "ix_maintenance_work_order_employee_id"):
        op.create_index("ix_maintenance_work_order_employee_id", "maintenance_work_order", ["employee_id"], unique=False)
    if _table_exists(bind, "maintenance_work_order") and not _index_exists(bind, "maintenance_work_order", "ix_maintenance_work_order_work_type"):
        op.create_index("ix_maintenance_work_order_work_type", "maintenance_work_order", ["work_type"], unique=False)

    if _table_exists(bind, "maintenance_expense") and not _column_exists(bind, "maintenance_expense", "work_order_id"):
        op.add_column("maintenance_expense", sa.Column("work_order_id", sa.Integer(), nullable=True))
    if _table_exists(bind, "maintenance_expense") and _column_exists(bind, "maintenance_expense", "work_order_id") and not _index_exists(bind, "maintenance_expense", "ix_maintenance_expense_work_order_id"):
        op.create_index("ix_maintenance_expense_work_order_id", "maintenance_expense", ["work_order_id"], unique=False)
    if (
        _table_exists(bind, "maintenance_expense")
        and _table_exists(bind, "maintenance_work_order")
        and _column_exists(bind, "maintenance_expense", "work_order_id")
        and not _fk_exists(bind, "maintenance_expense", "fk_maintenance_expense_work_order_id")
    ):
        op.create_foreign_key(
            "fk_maintenance_expense_work_order_id",
            "maintenance_expense",
            "maintenance_work_order",
            ["work_order_id"],
            ["id"],
        )


def downgrade():
    bind = op.get_bind()

    if _table_exists(bind, "maintenance_expense") and _fk_exists(bind, "maintenance_expense", "fk_maintenance_expense_work_order_id"):
        op.drop_constraint("fk_maintenance_expense_work_order_id", "maintenance_expense", type_="foreignkey")
    if _table_exists(bind, "maintenance_expense") and _index_exists(bind, "maintenance_expense", "ix_maintenance_expense_work_order_id"):
        op.drop_index("ix_maintenance_expense_work_order_id", table_name="maintenance_expense")
    if _table_exists(bind, "maintenance_expense") and _column_exists(bind, "maintenance_expense", "work_order_id"):
        op.drop_column("maintenance_expense", "work_order_id")

    if _table_exists(bind, "maintenance_work_order"):
        for idx_name in [
            "ix_maintenance_work_order_work_type",
            "ix_maintenance_work_order_employee_id",
            "ix_maintenance_work_order_project_id",
            "ix_maintenance_work_order_district_id",
            "ix_maintenance_work_order_opened_on",
            "ix_maintenance_work_order_vehicle_id",
            "ix_maintenance_work_order_status",
            "ix_maintenance_work_order_work_order_no",
        ]:
            if _index_exists(bind, "maintenance_work_order", idx_name):
                op.drop_index(idx_name, table_name="maintenance_work_order")
        op.drop_table("maintenance_work_order")
