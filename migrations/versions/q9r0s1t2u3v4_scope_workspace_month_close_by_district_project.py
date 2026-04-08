"""Scope workspace month close by district/project.

Revision ID: q9r0s1t2u3v4
Revises: p8q9r0s1t2u3
Create Date: 2026-04-08 16:40:00
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "q9r0s1t2u3v4"
down_revision = "p8q9r0s1t2u3"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("workspace_month_close") as batch_op:
        batch_op.add_column(sa.Column("district_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("project_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_workspace_month_close_district", "district", ["district_id"], ["id"])
        batch_op.create_foreign_key("fk_workspace_month_close_project", "project", ["project_id"], ["id"])
        batch_op.create_index("ix_workspace_month_close_district_id", ["district_id"], unique=False)
        batch_op.create_index("ix_workspace_month_close_project_id", ["project_id"], unique=False)
        try:
            batch_op.drop_constraint("uq_workspace_month_close_period", type_="unique")
        except Exception:
            pass
        batch_op.create_unique_constraint(
            "uq_workspace_month_close_period",
            ["employee_id", "district_id", "project_id", "period_start", "period_end"],
        )


def downgrade():
    with op.batch_alter_table("workspace_month_close") as batch_op:
        try:
            batch_op.drop_constraint("uq_workspace_month_close_period", type_="unique")
        except Exception:
            pass
        batch_op.create_unique_constraint(
            "uq_workspace_month_close_period",
            ["employee_id", "period_start", "period_end"],
        )
        try:
            batch_op.drop_index("ix_workspace_month_close_project_id")
            batch_op.drop_index("ix_workspace_month_close_district_id")
        except Exception:
            pass
        try:
            batch_op.drop_constraint("fk_workspace_month_close_project", type_="foreignkey")
            batch_op.drop_constraint("fk_workspace_month_close_district", type_="foreignkey")
        except Exception:
            pass
        batch_op.drop_column("project_id")
        batch_op.drop_column("district_id")
