"""Add cnic_front_back and license_front_back paths to driver

Revision ID: 3498c269d73b
Revises: g9h0i1j2k3l4
Create Date: 2026-03-18 19:48:18.083811

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3498c269d73b'
down_revision = 'g9h0i1j2k3l4'
branch_labels = None
depends_on = None


def _column_exists(table, column):
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = [c['name'] for c in insp.get_columns(table)]
    return column in cols


def upgrade():
    if not _column_exists('driver', 'cnic_front_path'):
        op.add_column('driver', sa.Column('cnic_front_path', sa.String(length=500), nullable=True))
    if not _column_exists('driver', 'cnic_back_path'):
        op.add_column('driver', sa.Column('cnic_back_path', sa.String(length=500), nullable=True))
    if not _column_exists('driver', 'license_front_path'):
        op.add_column('driver', sa.Column('license_front_path', sa.String(length=500), nullable=True))
    if not _column_exists('driver', 'license_back_path'):
        op.add_column('driver', sa.Column('license_back_path', sa.String(length=500), nullable=True))


def downgrade():
    op.drop_column('driver', 'license_back_path')
    op.drop_column('driver', 'license_front_path')
    op.drop_column('driver', 'cnic_back_path')
    op.drop_column('driver', 'cnic_front_path')
