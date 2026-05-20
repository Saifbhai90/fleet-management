"""notifications v2: per-user target_user_id

Revision ID: x0y1z2a3b4c5
Revises: d2e3f4g5h6i7
Create Date: 2026-05-20
"""

from alembic import op
import sqlalchemy as sa


revision = 'x0y1z2a3b4c5'
down_revision = 'd2e3f4g5h6i7'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = [c['name'] for c in insp.get_columns('notification')] if insp.has_table('notification') else []
    if 'target_user_id' not in cols:
        op.add_column('notification', sa.Column('target_user_id', sa.Integer(), nullable=True))
        op.create_foreign_key(
            'fk_notification_target_user_id',
            'notification',
            'user',
            ['target_user_id'],
            ['id'],
            ondelete='CASCADE',
        )
        op.create_index('ix_notification_target_user_id', 'notification', ['target_user_id'], unique=False)
    op.execute('DELETE FROM notification_read')
    op.execute('DELETE FROM notification')


def downgrade():
    op.drop_index('ix_notification_target_user_id', table_name='notification')
    op.drop_constraint('fk_notification_target_user_id', 'notification', type_='foreignkey')
    op.drop_column('notification', 'target_user_id')
