"""add attendance_time_control table for form controls

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-03-06

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = 'c4d5e6f7a8b9'
down_revision = 'b3c4d5e6f7a8'
branch_labels = None
depends_on = None


def _table_exists(conn, table_name):
    if conn.dialect.name == 'sqlite':
        r = conn.execute(text(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=:t"
        ), {"t": table_name})
    else:
        r = conn.execute(text(
            "SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = :t"
        ), {"t": table_name})
    return r.scalar() is not None


def upgrade():
    conn = op.get_bind()
    if _table_exists(conn, 'attendance_time_control'):
        return
    op.create_table(
        'attendance_time_control',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('morning_start', sa.Time(), nullable=True),
        sa.Column('morning_end', sa.Time(), nullable=True),
        sa.Column('night_start', sa.Time(), nullable=True),
        sa.Column('night_end', sa.Time(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('attendance_time_control')
