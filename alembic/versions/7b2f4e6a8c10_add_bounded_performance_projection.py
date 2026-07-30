"""add bounded performance projection

Revision ID: 7b2f4e6a8c10
Revises: 2e7c1a9b4d60
Create Date: 2026-07-29 23:15:00.000000

"""

import sqlalchemy as sa

from alembic import op

revision = "7b2f4e6a8c10"
down_revision = "2e7c1a9b4d60"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scans",
        sa.Column("analytics_outcome_processed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "scans",
        sa.Column("analytics_report_processed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "performance_rollup",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("packages_scanned", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("packages_failed", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("packages_dead_lettered", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("packages_reported", sa.BigInteger(), server_default="0", nullable=False),
        sa.CheckConstraint("id = 1", name="performance_rollup_singleton"),
        sa.CheckConstraint(
            "packages_scanned >= 0 AND packages_failed >= 0 AND packages_dead_lettered >= 0 AND packages_reported >= 0",
            name="performance_rollup_nonnegative",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "performance_projection_state",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("initial_backfill_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("id = 1", name="performance_projection_state_singleton"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "rule_hit_rollup",
        sa.Column("rule_id", sa.UUID(), nullable=False),
        sa.Column("hits", sa.BigInteger(), server_default="0", nullable=False),
        sa.CheckConstraint("hits >= 0", name="rule_hit_rollup_nonnegative"),
        sa.ForeignKeyConstraint(["rule_id"], ["rules.id"]),
        sa.PrimaryKeyConstraint("rule_id"),
    )
    op.create_table(
        "score_rollup",
        sa.Column("score", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("scans", sa.BigInteger(), server_default="0", nullable=False),
        sa.CheckConstraint("scans >= 0", name="score_rollup_nonnegative"),
        sa.PrimaryKeyConstraint("score"),
    )

    # These partial indexes are the only reads of the historical scans table.
    # Build them without blocking package ingestion or result submission.
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_scans_analytics_outcome_pending",
            "scans",
            ["scan_id"],
            unique=False,
            postgresql_where=sa.text("analytics_outcome_processed_at IS NULL AND status IN ('FINISHED', 'FAILED')"),
            postgresql_concurrently=True,
        )
        op.create_index(
            "ix_scans_analytics_report_pending",
            "scans",
            ["scan_id"],
            unique=False,
            postgresql_where=sa.text("analytics_report_processed_at IS NULL AND reported_at IS NOT NULL"),
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_scans_analytics_report_pending",
            table_name="scans",
            postgresql_concurrently=True,
        )
        op.drop_index(
            "ix_scans_analytics_outcome_pending",
            table_name="scans",
            postgresql_concurrently=True,
        )
    op.drop_table("score_rollup")
    op.drop_table("rule_hit_rollup")
    op.drop_table("performance_projection_state")
    op.drop_table("performance_rollup")
    op.drop_column("scans", "analytics_report_processed_at")
    op.drop_column("scans", "analytics_outcome_processed_at")
