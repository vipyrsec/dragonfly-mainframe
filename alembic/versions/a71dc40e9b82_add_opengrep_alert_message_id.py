"""add OpenGrep alert message ID

Revision ID: a71dc40e9b82
Revises: 71e3c2a9f804
Create Date: 2026-07-31 12:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

revision = "a71dc40e9b82"
down_revision = "71e3c2a9f804"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Store the optional Discord alert used as an OpenGrep thread root."""
    op.add_column(
        "opengrep_scans",
        sa.Column("discord_alert_message_id", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    """Remove only the experimental Discord alert routing metadata."""
    op.drop_column("opengrep_scans", "discord_alert_message_id")
