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
    table = "workspace_month_close"
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns(table)}

    if "district_id" not in cols:
        op.add_column(table, sa.Column("district_id", sa.Integer(), nullable=True))
    if "project_id" not in cols:
        op.add_column(table, sa.Column("project_id", sa.Integer(), nullable=True))

    # Refresh metadata after possible column additions.
    insp = sa.inspect(bind)
    idx_names = {i.get("name") for i in insp.get_indexes(table)}
    fk_names = {f.get("name") for f in insp.get_foreign_keys(table) if f.get("name")}
    uq_names = {u.get("name") for u in insp.get_unique_constraints(table) if u.get("name")}

    if "ix_workspace_month_close_district_id" not in idx_names:
        try:
            op.create_index("ix_workspace_month_close_district_id", table, ["district_id"], unique=False)
        except Exception:
            pass
    if "ix_workspace_month_close_project_id" not in idx_names:
        try:
            op.create_index("ix_workspace_month_close_project_id", table, ["project_id"], unique=False)
        except Exception:
            pass

    if "fk_workspace_month_close_district" not in fk_names:
        try:
            op.create_foreign_key("fk_workspace_month_close_district", table, "district", ["district_id"], ["id"])
        except Exception:
            pass
    if "fk_workspace_month_close_project" not in fk_names:
        try:
            op.create_foreign_key("fk_workspace_month_close_project", table, "project", ["project_id"], ["id"])
        except Exception:
            pass

    if "uq_workspace_month_close_period" in uq_names:
        try:
            op.drop_constraint("uq_workspace_month_close_period", table_name=table, type_="unique")
        except Exception:
            pass
    try:
        op.create_unique_constraint(
            "uq_workspace_month_close_period",
            table,
            ["employee_id", "district_id", "project_id", "period_start", "period_end"],
        )
    except Exception:
        pass


def downgrade():
    table = "workspace_month_close"
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns(table)}
    idx_names = {i.get("name") for i in insp.get_indexes(table)}
    fk_names = {f.get("name") for f in insp.get_foreign_keys(table) if f.get("name")}
    uq_names = {u.get("name") for u in insp.get_unique_constraints(table) if u.get("name")}

    if "uq_workspace_month_close_period" in uq_names:
        try:
            op.drop_constraint("uq_workspace_month_close_period", table_name=table, type_="unique")
        except Exception:
            pass
    try:
        op.create_unique_constraint(
            "uq_workspace_month_close_period",
            table,
            ["employee_id", "period_start", "period_end"],
        )
    except Exception:
        pass

    if "ix_workspace_month_close_project_id" in idx_names:
        try:
            op.drop_index("ix_workspace_month_close_project_id", table_name=table)
        except Exception:
            pass
    if "ix_workspace_month_close_district_id" in idx_names:
        try:
            op.drop_index("ix_workspace_month_close_district_id", table_name=table)
        except Exception:
            pass

    if "fk_workspace_month_close_project" in fk_names:
        try:
            op.drop_constraint("fk_workspace_month_close_project", table_name=table, type_="foreignkey")
        except Exception:
            pass
    if "fk_workspace_month_close_district" in fk_names:
        try:
            op.drop_constraint("fk_workspace_month_close_district", table_name=table, type_="foreignkey")
        except Exception:
            pass

    if "project_id" in cols:
        try:
            op.drop_column(table, "project_id")
        except Exception:
            pass
    if "district_id" in cols:
        try:
            op.drop_column(table, "district_id")
        except Exception:
            pass
