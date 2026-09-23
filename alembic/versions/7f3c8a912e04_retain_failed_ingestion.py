"""Retain packages when upstream metadata is temporarily unavailable.

Revision ID: 7f3c8a912e04
Revises: 6e2b9a140fd3
"""

import sqlalchemy as sa

from alembic import op

revision = "7f3c8a912e04"
down_revision = "6e2b9a140fd3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '2s'")
    op.create_table(
        "ingestion_retries",
        sa.Column("name", sa.String(), primary_key=True),
        sa.Column("version", sa.String(), primary_key=True),
        sa.Column("queued_by", sa.String(), nullable=False),
        sa.Column("retry_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_ingestion_retries_retry_at", "ingestion_retries", ["retry_at"])


def downgrade() -> None:
    op.drop_table("ingestion_retries")
