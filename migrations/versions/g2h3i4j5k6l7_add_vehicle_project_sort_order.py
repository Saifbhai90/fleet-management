"""add project_sort_order to vehicle

Revision ID: g2h3i4j5k6l7
Revises: f1e2d3c4b5a6
Create Date: 2026-05-28

"""
from alembic import op
import sqlalchemy as sa


revision = 'g2h3i4j5k6l7'
down_revision = 'f1e2d3c4b5a6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('vehicle', schema=None) as batch_op:
        batch_op.add_column(sa.Column('project_sort_order', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('vehicle', schema=None) as batch_op:
        batch_op.drop_column('project_sort_order')
