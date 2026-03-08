"""add activity_logs table (device_id, geolocation)

Revision ID: a1b2c3d4e5f7
Revises: c9d0e1f2a3b4
Create Date: 2026-03-06

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = 'a1b2c3d4e5f7'
down_revision = 'c9d0e1f2a3b4'
branch_labels = None
depends_on = None


def _table_exists(conn, name):
    if conn.dialect.name == 'sqlite':
        r = conn.execute(text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:n"), {"n": name})
        return r.scalar() is not None
    if conn.dialect.name == 'mysql':
        r = conn.execute(text(
            "SELECT 1 FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name = :n"
        ), {"n": name})
        return r.scalar() is not None
    # PostgreSQL
    r = conn.execute(text(
        "SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = :n"
    ), {"n": name})
    return r.scalar() is not None


def upgrade():
    conn = op.get_bind()
    if not _table_exists(conn, 'activity_logs'):
        op.create_table('activity_logs',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('device_id', sa.String(80), nullable=True),
            sa.Column('action', sa.String(200), nullable=False),
            sa.Column('latitude', sa.Numeric(12, 8), nullable=True),
            sa.Column('longitude', sa.Numeric(12, 8), nullable=True),
            sa.Column('accuracy', sa.Numeric(10, 2), nullable=True),
            sa.Column('ip_address', sa.String(64), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id')
        )


def downgrade():
    op.drop_table('activity_logs')
