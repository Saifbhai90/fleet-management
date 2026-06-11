"""slip ocr recipe and employee last slip profile

Revision ID: u1v2w3x4y5z6
Revises: t0u1v2w3x4y5
Create Date: 2026-06-11
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "u1v2w3x4y5z6"
down_revision = "t0u1v2w3x4y5"
branch_labels = None
depends_on = None


def _column_exists(bind, table_name, column_name):
    if table_name not in inspect(bind).get_table_names():
        return False
    return column_name in {c["name"] for c in inspect(bind).get_columns(table_name)}


def upgrade():
    bind = op.get_bind()
    if not _column_exists(bind, "workspace_slip_profile_field", "ocr_recipe_json"):
        op.add_column("workspace_slip_profile_field", sa.Column("ocr_recipe_json", sa.Text(), nullable=True))
    if not _column_exists(bind, "employee", "last_slip_profile_id"):
        op.add_column("employee", sa.Column("last_slip_profile_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            "fk_employee_last_slip_profile_id",
            "employee",
            "workspace_slip_profile",
            ["last_slip_profile_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index("ix_employee_last_slip_profile_id", "employee", ["last_slip_profile_id"])


def downgrade():
    bind = op.get_bind()
    if _column_exists(bind, "employee", "last_slip_profile_id"):
        op.drop_index("ix_employee_last_slip_profile_id", table_name="employee")
        op.drop_constraint("fk_employee_last_slip_profile_id", "employee", type_="foreignkey")
        op.drop_column("employee", "last_slip_profile_id")
    if _column_exists(bind, "workspace_slip_profile_field", "ocr_recipe_json"):
        op.drop_column("workspace_slip_profile_field", "ocr_recipe_json")
