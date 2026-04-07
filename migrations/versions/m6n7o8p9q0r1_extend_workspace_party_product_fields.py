"""extend workspace party and product fields

Revision ID: m6n7o8p9q0r1
Revises: l5m6n7o8p9q0
Create Date: 2026-04-06
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "m6n7o8p9q0r1"
down_revision = "l5m6n7o8p9q0"
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

    if _table_exists(bind, "workspace_party"):
        if not _column_exists(bind, "workspace_party", "district_id"):
            op.add_column("workspace_party", sa.Column("district_id", sa.Integer(), nullable=True))
            op.create_foreign_key(
                "fk_workspace_party_district_id",
                "workspace_party",
                "district",
                ["district_id"],
                ["id"],
            )
            op.create_index("ix_workspace_party_district_id", "workspace_party", ["district_id"], unique=False)
        if not _column_exists(bind, "workspace_party", "contact"):
            op.add_column("workspace_party", sa.Column("contact", sa.String(length=100), nullable=True))
        if not _column_exists(bind, "workspace_party", "remarks"):
            op.add_column("workspace_party", sa.Column("remarks", sa.Text(), nullable=True))

    if _table_exists(bind, "workspace_product") and not _column_exists(bind, "workspace_product", "remarks"):
        op.add_column("workspace_product", sa.Column("remarks", sa.Text(), nullable=True))


def downgrade():
    bind = op.get_bind()

    if _table_exists(bind, "workspace_product") and _column_exists(bind, "workspace_product", "remarks"):
        op.drop_column("workspace_product", "remarks")

    if _table_exists(bind, "workspace_party"):
        if _column_exists(bind, "workspace_party", "remarks"):
            op.drop_column("workspace_party", "remarks")
        if _column_exists(bind, "workspace_party", "contact"):
            op.drop_column("workspace_party", "contact")
        if _column_exists(bind, "workspace_party", "district_id"):
            try:
                op.drop_index("ix_workspace_party_district_id", table_name="workspace_party")
            except Exception:
                pass
            try:
                op.drop_constraint("fk_workspace_party_district_id", "workspace_party", type_="foreignkey")
            except Exception:
                pass
            op.drop_column("workspace_party", "district_id")
