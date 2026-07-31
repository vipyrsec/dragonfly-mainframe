"""gate OpenGrep shadow work on alerts

Revision ID: 71e3c2a9f804
Revises: 5a2f3be77d31
Create Date: 2026-07-31 02:10:00.000000

"""

import sqlalchemy as sa

from alembic import op

revision = "71e3c2a9f804"
down_revision = "5a2f3be77d31"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "opengrep_scans",
        sa.Column("alerted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.drop_index("ix_opengrep_scans_status", table_name="opengrep_scans")
    op.create_index(
        "ix_opengrep_scans_status",
        "opengrep_scans",
        ["status"],
        unique=False,
        postgresql_where=sa.text("alerted_at IS NOT NULL AND (status = 'QUEUED' OR status = 'PENDING')"),
    )


def downgrade() -> None:
    op.drop_index("ix_opengrep_scans_status", table_name="opengrep_scans")
    op.create_index(
        "ix_opengrep_scans_status",
        "opengrep_scans",
        ["status"],
        unique=False,
        postgresql_where=sa.text("status = 'QUEUED' OR status = 'PENDING'"),
    )
    op.drop_column("opengrep_scans", "alerted_at")
