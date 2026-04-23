"""Merge activity upload head with security head.

Revision ID: e3f4g5h6i7j8
Revises: security_cleanup_01, d2e3f4a5b6c7
Create Date: 2026-04-23
"""


# revision identifiers, used by Alembic.
revision = 'e3f4g5h6i7j8'
down_revision = ('security_cleanup_01', 'd2e3f4a5b6c7')
branch_labels = None
depends_on = None


def upgrade():
    # Merge-only migration; no schema change.
    pass


def downgrade():
    # Merge-only migration; no schema change.
    pass
