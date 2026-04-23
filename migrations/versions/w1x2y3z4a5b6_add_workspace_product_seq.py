"""add product_seq to workspace_product

Revision ID: w1x2y3z4a5b6
Revises: f4g5h6i7j8k9
Create Date: 2026-04-24

Kept in repo so PostgreSQL (e.g. Render) whose alembic_version is w1x2y3z4a5b6
can run `flask db upgrade`. Upgrade is idempotent if column already exists.
App code at 515b523 does not use product_seq; extra DB column is harmless.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = "w1x2y3z4a5b6"
down_revision = "f4g5h6i7j8k9"
branch_labels = None
depends_on = None


def _table_exists(bind, name):
    return name in inspect(bind).get_table_names()


def upgrade():
    bind = op.get_bind()
    if not _table_exists(bind, "workspace_product"):
        return
    cols = {c["name"] for c in inspect(bind).get_columns("workspace_product")}
    if "product_seq" in cols:
        return
    op.add_column(
        "workspace_product",
        sa.Column("product_seq", sa.Integer(), nullable=True),
    )
    res = bind.execute(text("SELECT id, employee_id FROM workspace_product ORDER BY employee_id, id"))
    rows = res.fetchall()
    counts = {}
    for rid, eid in rows:
        counts[eid] = counts.get(eid, 0) + 1
        bind.execute(
            text("UPDATE workspace_product SET product_seq = :s WHERE id = :i"),
            {"s": counts[eid], "i": rid},
        )
    op.alter_column(
        "workspace_product",
        "product_seq",
        existing_type=sa.Integer(),
        nullable=False,
        server_default="0",
    )
    try:
        op.create_index("ix_workspace_product_product_seq", "workspace_product", ["product_seq"], unique=False)
    except Exception:
        pass


def downgrade():
    bind = op.get_bind()
    if not _table_exists(bind, "workspace_product"):
        return
    cols = {c["name"] for c in inspect(bind).get_columns("workspace_product")}
    if "product_seq" not in cols:
        return
    try:
        op.drop_index("ix_workspace_product_product_seq", table_name="workspace_product")
    except Exception:
        pass
    op.drop_column("workspace_product", "product_seq")
