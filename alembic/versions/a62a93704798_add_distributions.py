"""add distributions

Revision ID: a62a93704798
Revises: 587c186d91ee
Create Date: 2024-08-11 08:12:42.354151

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "a62a93704798"
down_revision = "587c186d91ee"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("scans", "files", new_column_name="distributions")


def downgrade() -> None:
    op.alter_column("scans", "distributions", new_column_name="files")
