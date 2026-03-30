"""Add AppRelease table for in-app update management

Revision ID: app_release_001
Revises: fcm_bank_style_01
"""
from alembic import op
import sqlalchemy as sa

revision = 'app_release_001'
down_revision = 'fcm_bank_style_01'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'app_release' not in inspector.get_table_names():
        op.create_table('app_release',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('version', sa.String(length=20), nullable=False),
            sa.Column('apk_filename', sa.String(length=255), nullable=False),
            sa.Column('force_update', sa.Boolean(), nullable=False, server_default='false'),
            sa.Column('is_latest', sa.Boolean(), nullable=False, server_default='false'),
            sa.Column('release_notes', sa.Text(), nullable=True),
            sa.Column('file_size_bytes', sa.BigInteger(), nullable=True),
            sa.Column('uploaded_by', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('version'),
            sa.ForeignKeyConstraint(['uploaded_by'], ['user.id'], ondelete='SET NULL'),
        )


def downgrade():
    op.drop_table('app_release')
