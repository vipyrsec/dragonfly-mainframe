"""add scan retry state

Revision ID: 2e7c1a9b4d60
Revises: 8f4c2b1d0a77
Create Date: 2026-07-28 23:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

revision = "2e7c1a9b4d60"
down_revision = "8f4c2b1d0a77"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scans",
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "scans",
        sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "scans",
        sa.Column("assignment_id", sa.UUID(), nullable=True),
    )
    op.execute("UPDATE scans SET attempt_count = 3 WHERE status = 'PENDING'")
    op.create_check_constraint(
        "scans_nonnegative_attempt_count",
        "scans",
        "attempt_count >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "scans_nonnegative_attempt_count",
        "scans",
        type_="check",
    )
    op.drop_column("scans", "assignment_id")
    op.drop_column("scans", "dead_lettered_at")
    op.drop_column("scans", "attempt_count")
