"""link workspace expenses to employee scope

Revision ID: n7o8p9q0r1s2
Revises: m6n7o8p9q0r1
Create Date: 2026-04-06
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "n7o8p9q0r1s2"
down_revision = "m6n7o8p9q0r1"
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

    if _table_exists(bind, "fuel_expense"):
        if not _column_exists(bind, "fuel_expense", "employee_id"):
            op.add_column("fuel_expense", sa.Column("employee_id", sa.Integer(), nullable=True))
            op.create_foreign_key("fk_fuel_expense_employee_id", "fuel_expense", "employee", ["employee_id"], ["id"])
            op.create_index("ix_fuel_expense_employee_id", "fuel_expense", ["employee_id"], unique=False)
        if not _column_exists(bind, "fuel_expense", "workspace_pump_id"):
            op.add_column("fuel_expense", sa.Column("workspace_pump_id", sa.Integer(), nullable=True))
            op.create_foreign_key("fk_fuel_expense_workspace_pump_id", "fuel_expense", "workspace_party", ["workspace_pump_id"], ["id"])
            op.create_index("ix_fuel_expense_workspace_pump_id", "fuel_expense", ["workspace_pump_id"], unique=False)

    if _table_exists(bind, "oil_expense") and not _column_exists(bind, "oil_expense", "employee_id"):
        op.add_column("oil_expense", sa.Column("employee_id", sa.Integer(), nullable=True))
        op.create_foreign_key("fk_oil_expense_employee_id", "oil_expense", "employee", ["employee_id"], ["id"])
        op.create_index("ix_oil_expense_employee_id", "oil_expense", ["employee_id"], unique=False)

    if _table_exists(bind, "maintenance_expense") and not _column_exists(bind, "maintenance_expense", "employee_id"):
        op.add_column("maintenance_expense", sa.Column("employee_id", sa.Integer(), nullable=True))
        op.create_foreign_key("fk_maintenance_expense_employee_id", "maintenance_expense", "employee", ["employee_id"], ["id"])
        op.create_index("ix_maintenance_expense_employee_id", "maintenance_expense", ["employee_id"], unique=False)


def downgrade():
    bind = op.get_bind()

    if _table_exists(bind, "maintenance_expense") and _column_exists(bind, "maintenance_expense", "employee_id"):
        try:
            op.drop_index("ix_maintenance_expense_employee_id", table_name="maintenance_expense")
        except Exception:
            pass
        try:
            op.drop_constraint("fk_maintenance_expense_employee_id", "maintenance_expense", type_="foreignkey")
        except Exception:
            pass
        op.drop_column("maintenance_expense", "employee_id")

    if _table_exists(bind, "oil_expense") and _column_exists(bind, "oil_expense", "employee_id"):
        try:
            op.drop_index("ix_oil_expense_employee_id", table_name="oil_expense")
        except Exception:
            pass
        try:
            op.drop_constraint("fk_oil_expense_employee_id", "oil_expense", type_="foreignkey")
        except Exception:
            pass
        op.drop_column("oil_expense", "employee_id")

    if _table_exists(bind, "fuel_expense"):
        if _column_exists(bind, "fuel_expense", "workspace_pump_id"):
            try:
                op.drop_index("ix_fuel_expense_workspace_pump_id", table_name="fuel_expense")
            except Exception:
                pass
            try:
                op.drop_constraint("fk_fuel_expense_workspace_pump_id", "fuel_expense", type_="foreignkey")
            except Exception:
                pass
            op.drop_column("fuel_expense", "workspace_pump_id")
        if _column_exists(bind, "fuel_expense", "employee_id"):
            try:
                op.drop_index("ix_fuel_expense_employee_id", table_name="fuel_expense")
            except Exception:
                pass
            try:
                op.drop_constraint("fk_fuel_expense_employee_id", "fuel_expense", type_="foreignkey")
            except Exception:
                pass
            op.drop_column("fuel_expense", "employee_id")
