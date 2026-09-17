"""Quarantine individual cached files without revoking unrelated results.

Revision ID: 6e2b9a140fd3
Revises: 4d6a1c8f902b
"""

import sqlalchemy as sa

from alembic import op

revision = "6e2b9a140fd3"
down_revision = "4d6a1c8f902b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '2s'")
    op.add_column(
        "scan_cache_entries", sa.Column("quarantined", sa.Boolean(), nullable=False, server_default=sa.false())
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '2s'")
    # The older schema cannot represent per-file quarantine. Preserve safety.
    op.execute(
        "UPDATE scan_cache_namespaces SET revoked = true WHERE namespace IN "
        "(SELECT namespace FROM scan_cache_entries WHERE quarantined)"
    )
    op.drop_column("scan_cache_entries", "quarantined")
