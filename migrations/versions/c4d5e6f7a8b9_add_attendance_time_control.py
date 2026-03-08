"""add attendance_time_control table for form controls

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-03-06

"""
from alembic import op
import sqlalchemy as sa


revision = 'c4d5e6f7a8b9'
down_revision = 'b3c4d5e6f7a8'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'attendance_time_control',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('morning_start', sa.Time(), nullable=True),
        sa.Column('morning_end', sa.Time(), nullable=True),
        sa.Column('night_start', sa.Time(), nullable=True),
        sa.Column('night_end', sa.Time(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('attendance_time_control')
