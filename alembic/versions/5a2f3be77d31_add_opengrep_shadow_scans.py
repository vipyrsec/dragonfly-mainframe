"""add OpenGrep shadow scans

Revision ID: 5a2f3be77d31
Revises: 2e7c1a9b4d60
Create Date: 2026-07-30 23:15:00.000000

"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "5a2f3be77d31"
down_revision = "2e7c1a9b4d60"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "opengrep_scans",
        sa.Column("scan_id", sa.UUID(), nullable=False),
        sa.Column(  # pyright: ignore[reportUnknownArgumentType]
            "status",
            postgresql.ENUM(name="status", create_type=False),
            nullable=False,
        ),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("queued_by", sa.String(), nullable=False),
        sa.Column("pending_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pending_by", sa.String(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("assignment_id", sa.UUID(), nullable=True),
        sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_by", sa.String(), nullable=True),
        sa.Column("fail_reason", sa.String(), nullable=True),
        sa.Column("commit_hash", sa.String(), nullable=True),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("findings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="opengrep_scans_nonnegative_attempt_count",
        ),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="opengrep_scans_nonnegative_duration",
        ),
        sa.ForeignKeyConstraint(
            ["scan_id"],
            ["scans.scan_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("scan_id"),
    )
    op.create_index(
        "ix_opengrep_scans_finished_at",
        "opengrep_scans",
        ["finished_at"],
        unique=False,
    )
    op.create_index(
        "ix_opengrep_scans_published_at",
        "opengrep_scans",
        ["published_at"],
        unique=False,
    )
    op.create_index(
        "ix_opengrep_scans_status",
        "opengrep_scans",
        ["status"],
        unique=False,
        postgresql_where=sa.text("status = 'QUEUED' OR status = 'PENDING'"),
    )


def downgrade() -> None:
    op.drop_index("ix_opengrep_scans_status", table_name="opengrep_scans")
    op.drop_index("ix_opengrep_scans_published_at", table_name="opengrep_scans")
    op.drop_index("ix_opengrep_scans_finished_at", table_name="opengrep_scans")
    op.drop_table("opengrep_scans")
