"""add task_entry_yesterday_default_until to project

Revision ID: d2e3f4g5h6i7
Revises: b0c1d2e3f4a5
Create Date: 2026-05-19

"""
from alembic import op
import sqlalchemy as sa


revision = 'd2e3f4g5h6i7'
down_revision = 'b0c1d2e3f4a5'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('project', schema=None) as batch_op:
        batch_op.add_column(sa.Column('task_entry_yesterday_default_until', sa.Time(), nullable=True))


def downgrade():
    with op.batch_alter_table('project', schema=None) as batch_op:
        batch_op.drop_column('task_entry_yesterday_default_until')
