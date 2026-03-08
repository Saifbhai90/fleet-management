"""add force_password_change to user for first-time login with 123

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-03-06

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = 'e7f8a9b0c1d2'
down_revision = 'd6e7f8a9b0c1'
branch_labels = None
depends_on = None


def _column_exists(conn, table, column):
    if conn.dialect.name == 'sqlite':
        r = conn.execute(text("SELECT 1 FROM pragma_table_info(:t) WHERE name = :c"), {"t": table, "c": column})
    else:
        r = conn.execute(text(
            "SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = :t AND column_name = :c"
        ), {"t": table, "c": column})
    return r.scalar() is not None


def upgrade():
    conn = op.get_bind()
    if not _column_exists(conn, 'user', 'force_password_change'):
        op.add_column('user', sa.Column('force_password_change', sa.Boolean(), nullable=True))


def downgrade():
    conn = op.get_bind()
    if _column_exists(conn, 'user', 'force_password_change'):
        op.drop_column('user', 'force_password_change')
