"""add driver_attendance table

Revision ID: ee5823f584c4
Revises:
Create Date: 2026-03-01 18:04:54.533444

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ee5823f584c4'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Sirf naya table add karte hain - purani tables/data touch nahi
    op.create_table(
        'driver_attendance',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('driver_id', sa.Integer(), nullable=False),
        sa.Column('attendance_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('check_in', sa.Time(), nullable=True),
        sa.Column('check_out', sa.Time(), nullable=True),
        sa.Column('remarks', sa.Text(), nullable=True),
        sa.Column('project_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['driver_id'], ['driver.id'], ),
        sa.ForeignKeyConstraint(['project_id'], ['project.id'], ),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('driver_attendance')
