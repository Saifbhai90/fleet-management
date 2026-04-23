"""Merge remaining Alembic heads for single upgrade path.

Revision ID: f4g5h6i7j8k9
Revises: e3f4g5h6i7j8, z1y2x3w4v5u6
Create Date: 2026-04-23
"""


# revision identifiers, used by Alembic.
revision = 'f4g5h6i7j8k9'
down_revision = ('e3f4g5h6i7j8', 'z1y2x3w4v5u6')
branch_labels = None
depends_on = None


def upgrade():
    # Merge-only migration; no schema change.
    pass


def downgrade():
    # Merge-only migration; no schema change.
    pass
