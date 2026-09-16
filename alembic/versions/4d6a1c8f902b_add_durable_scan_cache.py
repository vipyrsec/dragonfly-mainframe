"""Add isolated, disposable durable scanner cache tables.

Revision ID: 4d6a1c8f902b
Revises: a71dc40e9b82
"""

import sqlalchemy as sa

from alembic import op

revision = "4d6a1c8f902b"
down_revision = "a71dc40e9b82"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scan_cache_namespaces",
        sa.Column("namespace", sa.LargeBinary(32), primary_key=True),
        sa.Column("scanner", sa.String(), nullable=False),
        sa.Column("rules_commit", sa.String(), nullable=False),
        sa.Column("rules_digest", sa.LargeBinary(32), nullable=False),
        sa.Column("engine_digest", sa.LargeBinary(32), nullable=False),
        sa.CheckConstraint("octet_length(namespace) = 32", name="cache_namespace_digest_length"),
        sa.CheckConstraint("entry_count >= 0 AND payload_bytes >= 0", name="cache_nonnegative_counts"),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.Column("entry_count", sa.Integer(), nullable=False),
        sa.Column("payload_bytes", sa.BigInteger(), nullable=False),
    )
    op.create_table(
        "scan_cache_entries",
        sa.Column("namespace", sa.LargeBinary(32), sa.ForeignKey("scan_cache_namespaces.namespace"), primary_key=True),
        sa.Column("file_digest", sa.LargeBinary(32), primary_key=True),
        sa.Column("language", sa.String(), primary_key=True),
        sa.Column("result", sa.String(), nullable=False),
        sa.CheckConstraint("octet_length(file_digest) = 32", name="cache_file_digest_length"),
        sa.CheckConstraint("octet_length(result) <= 16384", name="cache_result_size"),
        sa.CheckConstraint("char_length(language) <= 32", name="cache_language_size"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_scan_cache_entries_expires_at", "scan_cache_entries", ["expires_at"])
    op.execute(
        "ALTER TABLE scan_cache_entries SET (autovacuum_vacuum_scale_factor = 0.02, "
        "autovacuum_vacuum_threshold = 1000, autovacuum_analyze_scale_factor = 0.05)"
    )
    op.execute("ALTER TABLE scan_cache_namespaces SET (fillfactor = 80)")


def downgrade() -> None:
    op.drop_table("scan_cache_entries")
    op.drop_table("scan_cache_namespaces")
