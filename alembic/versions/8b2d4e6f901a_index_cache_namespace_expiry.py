"""Bound cache expiration scans to a single namespace.

Revision ID: 8b2d4e6f901a
Revises: 7f3c8a912e04
"""

from alembic import op

revision = "8b2d4e6f901a"
down_revision = "7f3c8a912e04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_scan_cache_entries_namespace_expires_at", "scan_cache_entries", ["namespace", "expires_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_scan_cache_entries_namespace_expires_at", table_name="scan_cache_entries")
