"""add scans finished at index

Revision ID: 94f1cd79b7d4
Revises: 9ac5b6c4a36b
Create Date: 2023-09-27 15:37:05.455517

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "94f1cd79b7d4"
down_revision = "9ac5b6c4a36b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(op.f("ix_scans_finished_at"), "scans", ["finished_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_scans_finished_at"), table_name="scans")
