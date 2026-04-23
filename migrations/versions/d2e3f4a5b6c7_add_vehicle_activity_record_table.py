"""Add vehicle activity report table

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-04-23
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = 'd2e3f4a5b6c7'
down_revision = 'c1d2e3f4a5b6'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    table_name = 'vehicle_activity_record'

    if table_name not in inspector.get_table_names():
        op.create_table(
            table_name,
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('task_date', sa.Date(), nullable=False),
            sa.Column('upload_date', sa.Date(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('vehicle_no', sa.String(length=50), nullable=False),
            sa.Column('group_name', sa.String(length=100), nullable=True),
            sa.Column('record_date_time', sa.String(length=50), nullable=True),
            sa.Column('location', sa.Text(), nullable=True),
            sa.Column('speed', sa.Numeric(precision=12, scale=2), nullable=True),
            sa.Column('direction', sa.String(length=20), nullable=True),
            sa.Column('distance', sa.Numeric(precision=12, scale=2), nullable=True),
            sa.Column('travel_time', sa.String(length=30), nullable=True),
            sa.Column('stop_time', sa.String(length=30), nullable=True),
            sa.Column('reason', sa.String(length=100), nullable=True),
            sa.Column('source_file', sa.String(length=255), nullable=True),
            sa.PrimaryKeyConstraint('id'),
        )
        inspector = inspect(bind)

    idx_names = {idx.get('name') for idx in inspector.get_indexes(table_name)} if table_name in inspector.get_table_names() else set()
    if 'ix_vehicle_activity_record_task_date' not in idx_names:
        op.create_index('ix_vehicle_activity_record_task_date', table_name, ['task_date'], unique=False)
    if 'ix_vehicle_activity_record_vehicle_no' not in idx_names:
        op.create_index('ix_vehicle_activity_record_vehicle_no', table_name, ['vehicle_no'], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    table_name = 'vehicle_activity_record'
    if table_name not in inspector.get_table_names():
        return
    idx_names = {idx.get('name') for idx in inspector.get_indexes(table_name)}
    if 'ix_vehicle_activity_record_vehicle_no' in idx_names:
        op.drop_index('ix_vehicle_activity_record_vehicle_no', table_name=table_name)
    if 'ix_vehicle_activity_record_task_date' in idx_names:
        op.drop_index('ix_vehicle_activity_record_task_date', table_name=table_name)
    op.drop_table(table_name)
