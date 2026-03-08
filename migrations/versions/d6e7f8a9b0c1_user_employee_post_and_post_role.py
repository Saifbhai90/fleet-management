"""add employee_post_id to user and role_id to driver_post for Post from Employee Posts

Revision ID: d6e7f8a9b0c1
Revises: c5e6f7a8b9d0
Create Date: 2026-03-06

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = 'd6e7f8a9b0c1'
down_revision = 'c5e6f7a8b9d0'
branch_labels = None
depends_on = None


def _column_exists(conn, table, column):
    if conn.dialect.name == 'sqlite':
        r = conn.execute(text(
            "SELECT 1 FROM pragma_table_info(:t) WHERE name = :c"
        ), {"t": table, "c": column})
    else:
        r = conn.execute(text(
            "SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = :t AND column_name = :c"
        ), {"t": table, "c": column})
    return r.scalar() is not None


def upgrade():
    conn = op.get_bind()
    if not _column_exists(conn, 'driver_post', 'role_id'):
        if conn.dialect.name == 'sqlite':
            with op.batch_alter_table('driver_post', schema=None) as batch_op:
                batch_op.add_column(sa.Column('role_id', sa.Integer(), nullable=True))
                batch_op.create_foreign_key('fk_driver_post_role_id', 'role', ['role_id'], ['id'], ondelete='SET NULL')
        else:
            op.add_column('driver_post', sa.Column('role_id', sa.Integer(), nullable=True))
            op.create_foreign_key('fk_driver_post_role_id', 'driver_post', 'role', ['role_id'], ['id'], ondelete='SET NULL')
    if not _column_exists(conn, 'user', 'employee_post_id'):
        if conn.dialect.name == 'sqlite':
            with op.batch_alter_table('user', schema=None) as batch_op:
                batch_op.add_column(sa.Column('employee_post_id', sa.Integer(), nullable=True))
                batch_op.create_foreign_key('fk_user_employee_post_id', 'driver_post', ['employee_post_id'], ['id'], ondelete='SET NULL')
        else:
            op.add_column('user', sa.Column('employee_post_id', sa.Integer(), nullable=True))
            op.create_foreign_key('fk_user_employee_post_id', 'user', 'driver_post', ['employee_post_id'], ['id'], ondelete='SET NULL')


def downgrade():
    conn = op.get_bind()
    if _column_exists(conn, 'user', 'employee_post_id'):
        if conn.dialect.name == 'sqlite':
            with op.batch_alter_table('user', schema=None) as batch_op:
                batch_op.drop_constraint('fk_user_employee_post_id', type_='foreignkey')
                batch_op.drop_column('employee_post_id')
        else:
            op.drop_constraint('fk_user_employee_post_id', 'user', type_='foreignkey')
            op.drop_column('user', 'employee_post_id')
    if _column_exists(conn, 'driver_post', 'role_id'):
        if conn.dialect.name == 'sqlite':
            with op.batch_alter_table('driver_post', schema=None) as batch_op:
                batch_op.drop_constraint('fk_driver_post_role_id', type_='foreignkey')
                batch_op.drop_column('role_id')
        else:
            op.drop_constraint('fk_driver_post_role_id', 'driver_post', type_='foreignkey')
            op.drop_column('driver_post', 'role_id')
