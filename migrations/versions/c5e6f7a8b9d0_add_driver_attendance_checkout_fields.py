"""add check-out geofence fields to driver_attendance

Revision ID: c5e6f7a8b9d0
Revises: b3c4d5e6f7a8
Create Date: 2026-03-06

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = 'c5e6f7a8b9d0'
down_revision = 'c4d5e6f7a8b9'
branch_labels = None
depends_on = None


def _column_exists(conn, table, column):
    if conn.dialect.name == 'sqlite':
        r = conn.execute(text("PRAGMA table_info(" + table + ")"))
        return any(row[1] == column for row in r)
    if conn.dialect.name == 'mysql':
        r = conn.execute(text(
            "SELECT 1 FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = :t AND column_name = :c"
        ), {"t": table, "c": column})
        return r.scalar() is not None
    r = conn.execute(text(
        "SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = :t AND column_name = :c"
    ), {"t": table, "c": column})
    return r.scalar() is not None


def upgrade():
    conn = op.get_bind()
    if not _column_exists(conn, 'driver_attendance', 'check_out_latitude'):
        op.add_column('driver_attendance', sa.Column('check_out_latitude', sa.Numeric(12, 8), nullable=True))
    if not _column_exists(conn, 'driver_attendance', 'check_out_longitude'):
        op.add_column('driver_attendance', sa.Column('check_out_longitude', sa.Numeric(12, 8), nullable=True))
    if not _column_exists(conn, 'driver_attendance', 'check_out_photo_path'):
        op.add_column('driver_attendance', sa.Column('check_out_photo_path', sa.String(500), nullable=True))


def downgrade():
    op.drop_column('driver_attendance', 'check_out_photo_path')
    op.drop_column('driver_attendance', 'check_out_longitude')
    op.drop_column('driver_attendance', 'check_out_latitude')
