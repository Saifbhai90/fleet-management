"""Add fleet_backup_job tables for multi-instance backup polling

Revision ID: h8i9j0k1l2m3
Revises: m9n0o1p2q3r4
Create Date: 2026-05-15

"""
from alembic import op
import sqlalchemy as sa


revision = 'h8i9j0k1l2m3'
down_revision = 'm9n0o1p2q3r4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'fleet_backup_job',
        sa.Column('id', sa.String(length=40), nullable=False),
        sa.Column('body', sa.JSON(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'fleet_backup_job_lock',
        sa.Column('job_id', sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(['job_id'], ['fleet_backup_job.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('job_id'),
    )


def downgrade():
    op.drop_table('fleet_backup_job_lock')
    op.drop_table('fleet_backup_job')
