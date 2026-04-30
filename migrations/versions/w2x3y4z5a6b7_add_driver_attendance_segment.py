"""Add attendance_segment to driver_attendance for capacity-2 double shifts.

Revision ID: w2x3y4z5a6b7
Revises: w1x2y3z4a5b6
Create Date: 2026-04-30

"""
from alembic import op
import sqlalchemy as sa


revision = 'w2x3y4z5a6b7'
down_revision = 'w1x2y3z4a5b6'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    dialect = conn.dialect.name
    with op.batch_alter_table('driver_attendance', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('attendance_segment', sa.Integer(), nullable=False, server_default='1')
        )
    # Drop old unique index on (driver_id, attendance_date)
    if dialect == 'postgresql':
        op.execute(sa.text('DROP INDEX IF EXISTS uq_attendance_driver_date'))
    else:
        try:
            op.drop_index('uq_attendance_driver_date', table_name='driver_attendance')
        except Exception:
            try:
                op.execute(sa.text('DROP INDEX IF EXISTS uq_attendance_driver_date'))
            except Exception:
                pass
    op.create_index(
        'uq_attendance_driver_date_seg',
        'driver_attendance',
        ['driver_id', 'attendance_date', 'attendance_segment'],
        unique=True,
    )


def downgrade():
    conn = op.get_bind()
    dialect = conn.dialect.name
    op.drop_index('uq_attendance_driver_date_seg', table_name='driver_attendance')
    if dialect == 'postgresql':
        op.execute(
            sa.text(
                'CREATE UNIQUE INDEX IF NOT EXISTS uq_attendance_driver_date '
                'ON driver_attendance (driver_id, attendance_date)'
            )
        )
    else:
        op.create_index(
            'uq_attendance_driver_date',
            'driver_attendance',
            ['driver_id', 'attendance_date'],
            unique=True,
        )
    with op.batch_alter_table('driver_attendance', schema=None) as batch_op:
        batch_op.drop_column('attendance_segment')
