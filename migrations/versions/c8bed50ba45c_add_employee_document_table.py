"""add employee_document table

Revision ID: c8bed50ba45c
Revises: e7f8a9b0c1d2
Create Date: 2026-03-09 00:07:39.588429

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = 'c8bed50ba45c'
down_revision = 'e7f8a9b0c1d2'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = inspect(conn)
    if 'employee_document' not in inspector.get_table_names():
        op.create_table('employee_document',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('employee_id', sa.Integer(), nullable=False),
            sa.Column('title', sa.String(length=120), nullable=True),
            sa.Column('file_path', sa.String(length=500), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['employee_id'], ['employee.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id')
        )


def downgrade():
    conn = op.get_bind()
    inspector = inspect(conn)
    if 'employee_document' in inspector.get_table_names():
        op.drop_table('employee_document')
