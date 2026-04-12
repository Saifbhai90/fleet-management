"""Widen expense attachment file_path for R2 URLs (was VARCHAR 500).

Revision ID: z9a8b7c6d5e4
Revises: r0s1t2u3v4w5
Create Date: 2026-04-12
"""

from alembic import op
import sqlalchemy as sa


revision = "z9a8b7c6d5e4"
down_revision = "r0s1t2u3v4w5"
branch_labels = None
depends_on = None

_TABLES = ("fuel_expense_attachment", "oil_expense_attachment", "maintenance_expense_attachment")


def upgrade():
    bind = op.get_bind()
    dialect = bind.dialect.name
    for table in _TABLES:
        if dialect == "sqlite":
            with op.batch_alter_table(table) as batch_op:
                batch_op.alter_column(
                    "file_path",
                    existing_type=sa.String(length=500),
                    type_=sa.String(length=2048),
                    existing_nullable=False,
                )
        else:
            op.alter_column(
                table,
                "file_path",
                existing_type=sa.String(length=500),
                type_=sa.String(length=2048),
                existing_nullable=False,
            )


def downgrade():
    bind = op.get_bind()
    dialect = bind.dialect.name
    for table in _TABLES:
        if dialect == "sqlite":
            with op.batch_alter_table(table) as batch_op:
                batch_op.alter_column(
                    "file_path",
                    existing_type=sa.String(length=2048),
                    type_=sa.String(length=500),
                    existing_nullable=False,
                )
        else:
            op.alter_column(
                table,
                "file_path",
                existing_type=sa.String(length=2048),
                type_=sa.String(length=500),
                existing_nullable=False,
            )
