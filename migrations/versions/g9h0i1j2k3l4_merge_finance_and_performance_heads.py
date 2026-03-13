"""Merge finance and performance migration heads

Revision ID: g9h0i1j2k3l4
Revises: f8a9b0c1d2e3, c1d2e3f4a5b6
Create Date: 2026-03-13

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'g9h0i1j2k3l4'
down_revision = ('f8a9b0c1d2e3', 'c1d2e3f4a5b6')
branch_labels = None
depends_on = None


def upgrade():
    # This is a merge migration - no schema changes needed
    pass


def downgrade():
    # This is a merge migration - no schema changes needed
    pass
