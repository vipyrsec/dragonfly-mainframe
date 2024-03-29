"""Add composite unique constraint to name and version

Revision ID: 9d70bac89aa5
Revises: 095a3873bec8
Create Date: 2023-06-27 16:21:50.089192

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "9d70bac89aa5"
down_revision = "095a3873bec8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_unique_constraint("name_version_unique", "scans", ["name", "version"])
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint("name_version_unique", "scans", type_="unique")
    # ### end Alembic commands ###
