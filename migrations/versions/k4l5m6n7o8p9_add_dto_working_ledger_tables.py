"""compatibility stub for removed dto working ledger migration

Revision ID: k4l5m6n7o8p9
Revises: security_cleanup_01
Create Date: 2026-04-07
"""

# NOTE:
# This project previously had a DTO migration with this revision id.
# The feature was reverted, but some deployed databases still have this
# revision recorded in alembic_version. Keeping this no-op revision lets
# Alembic resolve the historical chain during `flask db upgrade`.

revision = "k4l5m6n7o8p9"
down_revision = "security_cleanup_01"
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
