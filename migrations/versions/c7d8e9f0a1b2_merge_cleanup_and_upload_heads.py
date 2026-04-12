"""merge cleanup and upload migration heads

Revision ID: c7d8e9f0a1b2
Revises: b1c2d3e4f5g6, n2o3p4q5r6s7
Create Date: 2026-04-12
"""

from alembic import op  # noqa: F401


revision = "c7d8e9f0a1b2"
down_revision = ("b1c2d3e4f5g6", "n2o3p4q5r6s7")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
