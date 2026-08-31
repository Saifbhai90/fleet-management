"""Protect GPS attendance submits from duplicate requests and open races.

Revision ID: attend_idempotency_open_guard
Revises: act_sync_sts_01
Create Date: 2026-08-31

"""
from alembic import op
import sqlalchemy as sa


revision = 'attend_idempotency_open_guard'
down_revision = 'act_sync_sts_01'
branch_labels = None
depends_on = None


def _table_exists(conn, table_name):
    inspector = sa.inspect(conn)
    return table_name in inspector.get_table_names()


def _index_exists(conn, index_name):
    inspector = sa.inspect(conn)
    return index_name in {
        index['name']
        for index in inspector.get_indexes('driver_attendance')
    }


def upgrade():
    conn = op.get_bind()
    if not _table_exists(conn, 'driver_attendance'):
        return

    existing_columns = {
        column['name']
        for column in sa.inspect(conn).get_columns('driver_attendance')
    }
    if 'check_in_request_id' not in existing_columns:
        op.add_column(
            'driver_attendance',
            sa.Column('check_in_request_id', sa.String(length=100), nullable=True),
        )
    if 'check_out_request_id' not in existing_columns:
        op.add_column(
            'driver_attendance',
            sa.Column('check_out_request_id', sa.String(length=100), nullable=True),
        )

    # Existing databases may contain duplicate open rows from rapid retries.
    # Keep the most complete row and remove only the extra open rows; completed
    # historical sessions and sequential capacity segments are untouched.
    duplicate_groups = conn.execute(sa.text("""
        SELECT driver_id, attendance_date
        FROM driver_attendance
        WHERE check_in IS NOT NULL AND check_out IS NULL
        GROUP BY driver_id, attendance_date
        HAVING COUNT(*) > 1
    """)).fetchall()
    for driver_id, attendance_date in duplicate_groups:
        rows = conn.execute(sa.text("""
            SELECT id
            FROM driver_attendance
            WHERE driver_id = :driver_id
              AND attendance_date = :attendance_date
              AND check_in IS NOT NULL
              AND check_out IS NULL
            ORDER BY
              CASE WHEN check_in_photo_path IS NOT NULL THEN 0 ELSE 1 END,
              id ASC
        """), {
            'driver_id': driver_id,
            'attendance_date': attendance_date,
        }).fetchall()
        for (duplicate_id,) in rows[1:]:
            conn.execute(
                sa.text('DELETE FROM driver_attendance WHERE id = :id'),
                {'id': duplicate_id},
            )

    if not _index_exists(conn, 'uq_attendance_open_driver_date'):
        conn.execute(sa.text("""
            CREATE UNIQUE INDEX uq_attendance_open_driver_date
            ON driver_attendance (driver_id, attendance_date)
            WHERE check_in IS NOT NULL AND check_out IS NULL
        """))
    if not _index_exists(conn, 'uq_attendance_checkin_request_id'):
        conn.execute(sa.text("""
            CREATE UNIQUE INDEX uq_attendance_checkin_request_id
            ON driver_attendance (check_in_request_id)
            WHERE check_in_request_id IS NOT NULL
        """))
    if not _index_exists(conn, 'uq_attendance_checkout_request_id'):
        conn.execute(sa.text("""
            CREATE UNIQUE INDEX uq_attendance_checkout_request_id
            ON driver_attendance (check_out_request_id)
            WHERE check_out_request_id IS NOT NULL
        """))


def downgrade():
    conn = op.get_bind()
    if not _table_exists(conn, 'driver_attendance'):
        return
    for index_name in (
        'uq_attendance_open_driver_date',
        'uq_attendance_checkin_request_id',
        'uq_attendance_checkout_request_id',
    ):
        if _index_exists(conn, index_name):
            op.drop_index(index_name, table_name='driver_attendance')
    existing_columns = {
        column['name']
        for column in sa.inspect(conn).get_columns('driver_attendance')
    }
    with op.batch_alter_table('driver_attendance', schema=None) as batch_op:
        for column_name in ('check_out_request_id', 'check_in_request_id'):
            if column_name in existing_columns:
                batch_op.drop_column(column_name)
