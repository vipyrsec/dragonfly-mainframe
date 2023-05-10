"""empty message

Revision ID: b5ec215f4679
Revises: 5264b2894e56
Create Date: 2023-05-10 18:09:00.725313

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b5ec215f4679'
down_revision = '5264b2894e56'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('packages', sa.Column('version', sa.String(), nullable=False))
    op.add_column('packages', sa.Column('queued_at', sa.DateTime(), nullable=False))
    op.add_column('packages', sa.Column('pending_at', sa.DateTime(), nullable=True))
    op.add_column('packages', sa.Column('finished_at', sa.DateTime(), nullable=True))
    op.add_column('packages', sa.Column('client_id', sa.String(), nullable=False))
    op.add_column('packages', sa.Column('reported', sa.Boolean(), nullable=False))
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('packages', 'reported')
    op.drop_column('packages', 'client_id')
    op.drop_column('packages', 'finished_at')
    op.drop_column('packages', 'pending_at')
    op.drop_column('packages', 'queued_at')
    op.drop_column('packages', 'version')
    # ### end Alembic commands ###
