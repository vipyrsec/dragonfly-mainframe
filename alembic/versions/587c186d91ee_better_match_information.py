"""better-match-information

Revision ID: 587c186d91ee
Revises: 6991bcb18f89
Create Date: 2024-07-27 19:51:33.408128

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "587c186d91ee"
down_revision = "6991bcb18f89"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column("scans", sa.Column("files", postgresql.JSONB(), nullable=True))
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column("scans", "files")
    # ### end Alembic commands ###