"""add report summary and reported at index

Revision ID: 3f42e287fc2f
Revises: 6991bcb18f89
Create Date: 2026-04-01 09:30:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "3f42e287fc2f"
down_revision = "6991bcb18f89"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("scans", sa.Column("report_summary", sa.String(), nullable=True))
    op.create_index(op.f("ix_scans_reported_at"), "scans", ["reported_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_scans_reported_at"), table_name="scans")
    op.drop_column("scans", "report_summary")
