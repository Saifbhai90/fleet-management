"""add user role permission tables for login and RBAC

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-03-05

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = 'b8c9d0e1f2a3'
down_revision = 'a7b8c9d0e1f2'
branch_labels = None
depends_on = None


def _table_exists(conn, name):
    if conn.dialect.name == 'sqlite':
        r = conn.execute(text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:n"), {"n": name})
    else:
        r = conn.execute(text(
            "SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = :n"
        ), {"n": name})
    return r.scalar() is not None


def upgrade():
    conn = op.get_bind()
    if not _table_exists(conn, 'permission'):
        op.create_table('permission',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('code', sa.String(80), nullable=False),
            sa.Column('name', sa.String(120), nullable=False),
            sa.Column('category', sa.String(80), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('code')
        )
    if not _table_exists(conn, 'role'):
        op.create_table('role',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(80), nullable=False),
            sa.Column('description', sa.String(255), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('name')
        )
    if not _table_exists(conn, 'role_permissions'):
        op.create_table('role_permissions',
            sa.Column('role_id', sa.Integer(), nullable=False),
            sa.Column('permission_id', sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(['permission_id'], ['permission.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['role_id'], ['role.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('role_id', 'permission_id')
        )
    if not _table_exists(conn, 'user'):
        op.create_table('user',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('username', sa.String(80), nullable=False),
            sa.Column('password_hash', sa.String(255), nullable=False),
            sa.Column('full_name', sa.String(120), nullable=True),
            sa.Column('role_id', sa.Integer(), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['role_id'], ['role.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('username')
        )


def downgrade():
    op.drop_table('user')
    op.drop_table('role_permissions')
    op.drop_table('role')
    op.drop_table('permission')
