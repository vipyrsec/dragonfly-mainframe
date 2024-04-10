"""make client_id nullable

Revision ID: 1bced040ba5a
Revises: b5ec215f4679
Create Date: 2023-05-10 20:59:43.955108

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "1bced040ba5a"
down_revision = "b5ec215f4679"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column("packages", "client_id", existing_type=sa.VARCHAR(), nullable=True)
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column("packages", "client_id", existing_type=sa.VARCHAR(), nullable=False)
    # ### end Alembic commands ###
