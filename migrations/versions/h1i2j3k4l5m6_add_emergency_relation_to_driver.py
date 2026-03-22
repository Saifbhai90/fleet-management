"""add emergency_relation to driver

Revision ID: h1i2j3k4l5m6
Revises: 3498c269d73b
Create Date: 2026-03-22

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'h1i2j3k4l5m6'
down_revision = '3498c269d73b'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('driver', schema=None) as batch_op:
        batch_op.add_column(sa.Column('emergency_relation', sa.String(length=100), nullable=True))


def downgrade():
    with op.batch_alter_table('driver', schema=None) as batch_op:
        batch_op.drop_column('emergency_relation')
