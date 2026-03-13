"""Phase 3: Add performance indexes on high-traffic columns

Revision ID: c1d2e3f4a5b6
Revises: b4c5d6e7f8a9
Create Date: 2026-06-01

Indexes added:
- driver.cnic_no       (search/unique lookup)
- driver.license_no    (search/duplicate check)
- driver.status        (Active/Inactive filter)
- driver_attendance.attendance_date  (daily filter)
- driver_attendance.driver_id        (per-driver lookup)
- fuel_expense.fueling_date          (date range filter)
- fuel_expense.vehicle_id            (per-vehicle filter)
- fuel_expense.project_id            (per-project filter)
- fuel_expense.district_id           (per-district filter)
"""
from alembic import op
import sqlalchemy as sa


revision = 'c1d2e3f4a5b6'
down_revision = 'b4c5d6e7f8a9'
branch_labels = None
depends_on = None


def _index_exists(conn, index_name):
    dialect = conn.dialect.name
    if dialect == 'sqlite':
        result = conn.execute(
            sa.text("SELECT name FROM sqlite_master WHERE type='index' AND name=:n"),
            {'n': index_name}
        )
        return result.fetchone() is not None
    else:
        result = conn.execute(
            sa.text("SELECT 1 FROM pg_indexes WHERE indexname=:n"),
            {'n': index_name}
        )
        return result.fetchone() is not None


def upgrade():
    conn = op.get_bind()
    indexes = [
        ('ix_driver_cnic_no',              'driver',           'cnic_no'),
        ('ix_driver_license_no',           'driver',           'license_no'),
        ('ix_driver_status',               'driver',           'status'),
        ('ix_driver_attendance_date',      'driver_attendance','attendance_date'),
        ('ix_driver_attendance_driver_id', 'driver_attendance','driver_id'),
        ('ix_fuel_expense_fueling_date',   'fuel_expense',     'fueling_date'),
        ('ix_fuel_expense_vehicle_id',     'fuel_expense',     'vehicle_id'),
        ('ix_fuel_expense_project_id',     'fuel_expense',     'project_id'),
        ('ix_fuel_expense_district_id',    'fuel_expense',     'district_id'),
    ]
    for idx_name, table, col in indexes:
        if not _index_exists(conn, idx_name):
            op.create_index(idx_name, table, [col], unique=False)


def downgrade():
    indexes = [
        ('ix_fuel_expense_district_id',    'fuel_expense'),
        ('ix_fuel_expense_project_id',     'fuel_expense'),
        ('ix_fuel_expense_vehicle_id',     'fuel_expense'),
        ('ix_fuel_expense_fueling_date',   'fuel_expense'),
        ('ix_driver_attendance_driver_id', 'driver_attendance'),
        ('ix_driver_attendance_date',      'driver_attendance'),
        ('ix_driver_status',               'driver'),
        ('ix_driver_license_no',           'driver'),
        ('ix_driver_cnic_no',              'driver'),
    ]
    conn = op.get_bind()
    for idx_name, table in indexes:
        if _index_exists(conn, idx_name):
            op.drop_index(idx_name, table_name=table)
