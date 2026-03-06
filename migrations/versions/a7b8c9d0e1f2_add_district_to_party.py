"""add district_id to party

Revision ID: a7b8c9d0e1f2
Revises: 4b18954691fa
Create Date: 2026-03-05

"""
from alembic import op
import sqlalchemy as sa


revision = 'a7b8c9d0e1f2'
down_revision = '4b18954691fa'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if 'party' not in insp.get_table_names():
        return
    cols = {c['name'] for c in insp.get_columns('party')}
    if 'district_id' in cols:
        return
    with op.batch_alter_table('party', schema=None) as batch_op:
        batch_op.add_column(sa.Column('district_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_party_district_id', 'district', ['district_id'], ['id'])


def downgrade():
    with op.batch_alter_table('party', schema=None) as batch_op:
        batch_op.drop_constraint('fk_party_district_id', type_='foreignkey')
        batch_op.drop_column('district_id')
