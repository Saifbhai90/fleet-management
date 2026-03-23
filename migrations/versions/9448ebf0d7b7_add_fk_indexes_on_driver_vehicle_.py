"""add_fk_indexes_on_driver_vehicle_attendance

Revision ID: 9448ebf0d7b7
Revises: h1i2j3k4l5m6
Create Date: 2026-03-23 15:18:26.737136

Safe migration: adds missing indexes on high-traffic FK columns.
Uses IF NOT EXISTS / IF EXISTS so it is idempotent on any DB state.
"""
from alembic import op


revision = '9448ebf0d7b7'
down_revision = 'h1i2j3k4l5m6'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE INDEX IF NOT EXISTS ix_driver_project_id      ON driver(project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_driver_vehicle_id      ON driver(vehicle_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_driver_district_id     ON driver(district_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_vehicle_project_id     ON vehicle(project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_vehicle_district_id    ON vehicle(district_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_vehicle_driver_id      ON vehicle(driver_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_da_driver_id           ON driver_attendance(driver_id)")


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_driver_project_id")
    op.execute("DROP INDEX IF EXISTS ix_driver_vehicle_id")
    op.execute("DROP INDEX IF EXISTS ix_driver_district_id")
    op.execute("DROP INDEX IF EXISTS ix_vehicle_project_id")
    op.execute("DROP INDEX IF EXISTS ix_vehicle_district_id")
    op.execute("DROP INDEX IF EXISTS ix_vehicle_driver_id")
    op.execute("DROP INDEX IF EXISTS ix_da_driver_id")
