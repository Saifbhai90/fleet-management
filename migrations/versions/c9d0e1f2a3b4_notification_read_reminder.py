"""notification_read, reminder, notification.created_by_user_id

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-03-06

"""
from alembic import op
import sqlalchemy as sa


revision = 'c9d0e1f2a3b4'
down_revision = 'b8c9d0e1f2a3'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('notification', sa.Column('created_by_user_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_notification_created_by_user', 'notification', 'user', ['created_by_user_id'], ['id'], ondelete='SET NULL')

    op.create_table('notification_read',
        sa.Column('notification_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('read_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['notification_id'], ['notification.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('notification_id', 'user_id')
    )

    op.create_table('reminder',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('reminder_date', sa.Date(), nullable=False),
        sa.Column('reminder_time', sa.Time(), nullable=True),
        sa.Column('is_completed', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('reminder')
    op.drop_table('notification_read')
    op.drop_constraint('fk_notification_created_by_user', 'notification', type_='foreignkey')
    op.drop_column('notification', 'created_by_user_id')
