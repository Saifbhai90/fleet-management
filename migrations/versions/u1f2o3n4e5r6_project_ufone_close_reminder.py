"""add ufone_close_reminder_minutes to project

Revision ID: u1f2o3n4e5r6
Revises: y2z3a4b5c6d7
Create Date: 2026-07-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = 'u1f2o3n4e5r6'
down_revision = 'y2z3a4b5c6d7'
branch_labels = None
depends_on = None


def _column_exists(bind, table_name, column_name):
    if table_name not in inspect(bind).get_table_names():
        return False
    return column_name in {c['name'] for c in inspect(bind).get_columns(table_name)}


def upgrade():
    bind = op.get_bind()
    if not _column_exists(bind, 'project', 'ufone_close_reminder_minutes'):
        op.add_column(
            'project',
            sa.Column('ufone_close_reminder_minutes', sa.Integer(), nullable=True, server_default='0'),
        )


def downgrade():
    bind = op.get_bind()
    if _column_exists(bind, 'project', 'ufone_close_reminder_minutes'):
        op.drop_column('project', 'ufone_close_reminder_minutes')
