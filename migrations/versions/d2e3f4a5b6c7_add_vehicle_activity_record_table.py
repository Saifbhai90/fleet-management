"""Add vehicle activity report table

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-04-23
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd2e3f4a5b6c7'
down_revision = 'c1d2e3f4a5b6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'vehicle_activity_record',
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
    op.create_index('ix_vehicle_activity_record_task_date', 'vehicle_activity_record', ['task_date'], unique=False)
    op.create_index('ix_vehicle_activity_record_vehicle_no', 'vehicle_activity_record', ['vehicle_no'], unique=False)


def downgrade():
    op.drop_index('ix_vehicle_activity_record_vehicle_no', table_name='vehicle_activity_record')
    op.drop_index('ix_vehicle_activity_record_task_date', table_name='vehicle_activity_record')
    op.drop_table('vehicle_activity_record')
