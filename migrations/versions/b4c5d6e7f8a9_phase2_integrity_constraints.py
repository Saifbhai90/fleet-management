"""Phase 2: Add missing UNIQUE and composite constraints for data integrity

Revision ID: b4c5d6e7f8a9
Revises: 6a89ca3989e1
Create Date: 2026-03-13

Changes:
- Vehicle.engine_no: UNIQUE (partial, non-null/non-empty)
- Vehicle.chassis_no: UNIQUE (partial, non-null/non-empty)
- Project.name: UNIQUE
- Employee.cnic_no: UNIQUE (partial, non-null)
- Product.name: UNIQUE
- Party(name, party_type): UNIQUE composite
- ParkingStation(name, district): UNIQUE composite
- DriverAttendance(driver_id, attendance_date): UNIQUE composite
"""
from alembic import op
import sqlalchemy as sa


revision = 'b4c5d6e7f8a9'
down_revision = '6a89ca3989e1'
branch_labels = None
depends_on = None


def _table_exists(conn, table_name):
    result = conn.execute(sa.text(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=:t"
    ), {'t': table_name})
    return result.fetchone() is not None


def _index_exists(conn, index_name):
    result = conn.execute(sa.text(
        "SELECT name FROM sqlite_master WHERE type='index' AND name=:n"
    ), {'n': index_name})
    return result.fetchone() is not None


def upgrade():
    conn = op.get_bind()

    # ── Vehicle: UNIQUE engine_no (partial: skip NULL / empty) ───────────
    if _table_exists(conn, 'vehicle') and not _index_exists(conn, 'uq_vehicle_engine_no'):
        conn.execute(sa.text("""
            UPDATE vehicle SET engine_no = NULL
            WHERE engine_no IS NOT NULL AND engine_no != ''
              AND id NOT IN (
                SELECT MIN(id) FROM vehicle
                WHERE engine_no IS NOT NULL AND engine_no != ''
                GROUP BY engine_no
              )
        """))
        conn.execute(sa.text(
            "CREATE UNIQUE INDEX uq_vehicle_engine_no ON vehicle (engine_no) "
            "WHERE engine_no IS NOT NULL AND engine_no != ''"
        ))

    # ── Vehicle: UNIQUE chassis_no (partial) ─────────────────────────────
    if _table_exists(conn, 'vehicle') and not _index_exists(conn, 'uq_vehicle_chassis_no'):
        conn.execute(sa.text("""
            UPDATE vehicle SET chassis_no = NULL
            WHERE chassis_no IS NOT NULL AND chassis_no != ''
              AND id NOT IN (
                SELECT MIN(id) FROM vehicle
                WHERE chassis_no IS NOT NULL AND chassis_no != ''
                GROUP BY chassis_no
              )
        """))
        conn.execute(sa.text(
            "CREATE UNIQUE INDEX uq_vehicle_chassis_no ON vehicle (chassis_no) "
            "WHERE chassis_no IS NOT NULL AND chassis_no != ''"
        ))

    # ── Project: UNIQUE name ──────────────────────────────────────────────
    if _table_exists(conn, 'project') and not _index_exists(conn, 'uq_project_name'):
        conn.execute(sa.text("""
            UPDATE project SET name = name || ' (dup-' || id || ')'
            WHERE id NOT IN (
                SELECT MIN(id) FROM project GROUP BY name
            )
        """))
        conn.execute(sa.text(
            "CREATE UNIQUE INDEX uq_project_name ON project (name)"
        ))

    # ── Employee: UNIQUE cnic_no (partial: skip NULL) ─────────────────────
    if _table_exists(conn, 'employee') and not _index_exists(conn, 'uq_employee_cnic_no'):
        conn.execute(sa.text(
            "UPDATE employee SET cnic_no = NULL WHERE cnic_no = ''"
        ))
        conn.execute(sa.text("""
            UPDATE employee SET cnic_no = NULL
            WHERE cnic_no IS NOT NULL
              AND id NOT IN (
                SELECT MIN(id) FROM employee
                WHERE cnic_no IS NOT NULL
                GROUP BY cnic_no
              )
        """))
        conn.execute(sa.text(
            "CREATE UNIQUE INDEX uq_employee_cnic_no ON employee (cnic_no) "
            "WHERE cnic_no IS NOT NULL"
        ))

    # ── Product: UNIQUE name ──────────────────────────────────────────────
    if _table_exists(conn, 'product') and not _index_exists(conn, 'uq_product_name'):
        conn.execute(sa.text("""
            UPDATE product SET name = name || ' (dup-' || id || ')'
            WHERE id NOT IN (
                SELECT MIN(id) FROM product GROUP BY name
            )
        """))
        conn.execute(sa.text(
            "CREATE UNIQUE INDEX uq_product_name ON product (name)"
        ))

    # ── Party: UNIQUE (name, party_type) ─────────────────────────────────
    if _table_exists(conn, 'party') and not _index_exists(conn, 'uq_party_name_type'):
        conn.execute(sa.text("""
            UPDATE party SET name = name || ' (dup-' || id || ')'
            WHERE id NOT IN (
                SELECT MIN(id) FROM party GROUP BY name, party_type
            )
        """))
        conn.execute(sa.text(
            "CREATE UNIQUE INDEX uq_party_name_type ON party (name, party_type)"
        ))

    # ── ParkingStation: UNIQUE (name, district) ───────────────────────────
    if _table_exists(conn, 'parking_station') and not _index_exists(conn, 'uq_parking_name_district'):
        conn.execute(sa.text("""
            UPDATE parking_station SET name = name || ' (dup-' || id || ')'
            WHERE id NOT IN (
                SELECT MIN(id) FROM parking_station GROUP BY name, district
            )
        """))
        conn.execute(sa.text(
            "CREATE UNIQUE INDEX uq_parking_name_district ON parking_station (name, district)"
        ))

    # ── DriverAttendance: UNIQUE (driver_id, attendance_date) ─────────────
    if _table_exists(conn, 'driver_attendance') and not _index_exists(conn, 'uq_attendance_driver_date'):
        conn.execute(sa.text("""
            DELETE FROM driver_attendance
            WHERE id NOT IN (
                SELECT MAX(id) FROM driver_attendance
                GROUP BY driver_id, attendance_date
            )
        """))
        conn.execute(sa.text(
            "CREATE UNIQUE INDEX uq_attendance_driver_date "
            "ON driver_attendance (driver_id, attendance_date)"
        ))


def downgrade():
    conn = op.get_bind()
    for idx in [
        'uq_vehicle_engine_no', 'uq_vehicle_chassis_no',
        'uq_project_name', 'uq_employee_cnic_no',
        'uq_product_name', 'uq_party_name_type',
        'uq_parking_name_district', 'uq_attendance_driver_date',
    ]:
        if _index_exists(conn, idx):
            conn.execute(sa.text(f"DROP INDEX {idx}"))
