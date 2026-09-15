"""Unique (vehicle_id, task_date) on vehicle_daily_task.

Revision ID: vdt_uq_vehicle_date_01
Revises: attend_idempotency_open_guard
Create Date: 2026-09-15
"""
from alembic import op
import sqlalchemy as sa


revision = 'vdt_uq_vehicle_date_01'
down_revision = 'attend_idempotency_open_guard'
branch_labels = None
depends_on = None


def _table_exists(conn, table_name):
    inspector = sa.inspect(conn)
    return table_name in inspector.get_table_names()


def _constraint_exists(conn, table_name, constraint_name):
    inspector = sa.inspect(conn)
    names = {c['name'] for c in inspector.get_unique_constraints(table_name)}
    names.update({ix['name'] for ix in inspector.get_indexes(table_name) if ix.get('unique')})
    return constraint_name in names


def upgrade():
    conn = op.get_bind()
    if not _table_exists(conn, 'vehicle_daily_task'):
        return
    if _constraint_exists(conn, 'vehicle_daily_task', 'uq_vehicle_daily_task_vehicle_date'):
        return

    dialect = conn.dialect.name
    if dialect == 'postgresql':
        op.execute(
            sa.text(
                """
                DELETE FROM vehicle_daily_task a
                USING vehicle_daily_task b
                WHERE a.vehicle_id = b.vehicle_id
                  AND a.task_date = b.task_date
                  AND a.id < b.id
                """
            )
        )
    else:
        op.execute(
            sa.text(
                """
                DELETE FROM vehicle_daily_task
                WHERE id IN (
                    SELECT id FROM (
                        SELECT id,
                               ROW_NUMBER() OVER (
                                   PARTITION BY vehicle_id, task_date
                                   ORDER BY id DESC
                               ) AS rn
                        FROM vehicle_daily_task
                    ) ranked
                    WHERE rn > 1
                )
                """
            )
        )

    op.create_unique_constraint(
        'uq_vehicle_daily_task_vehicle_date',
        'vehicle_daily_task',
        ['vehicle_id', 'task_date'],
    )


def downgrade():
    conn = op.get_bind()
    if not _table_exists(conn, 'vehicle_daily_task'):
        return
    if not _constraint_exists(conn, 'vehicle_daily_task', 'uq_vehicle_daily_task_vehicle_date'):
        return
    op.drop_constraint('uq_vehicle_daily_task_vehicle_date', 'vehicle_daily_task', type_='unique')
