"""make datetimes tz aware

Revision ID: 56627251b8c0
Revises: 6991bcb18f89
Create Date: 2024-07-04 14:23:08.370773

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "56627251b8c0"
down_revision = "6991bcb18f89"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "scans",
        "queued_at",
        existing_type=postgresql.TIMESTAMP(),
        type_=sa.DateTime(timezone=True),
        existing_nullable=True,
        postgresql_using="queued_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "scans",
        "pending_at",
        existing_type=postgresql.TIMESTAMP(),
        type_=sa.DateTime(timezone=True),
        existing_nullable=True,
        postgresql_using="pending_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "scans",
        "finished_at",
        existing_type=postgresql.TIMESTAMP(),
        type_=sa.DateTime(timezone=True),
        existing_nullable=True,
        postgresql_using="finished_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "scans",
        "reported_at",
        existing_type=postgresql.TIMESTAMP(),
        type_=sa.DateTime(timezone=True),
        existing_nullable=True,
        postgresql_using="reported_at AT TIME ZONE 'UTC'",
    )


def downgrade() -> None:
    op.alter_column(
        "scans",
        "reported_at",
        existing_type=sa.DateTime(timezone=True),
        type_=postgresql.TIMESTAMP(),
        existing_nullable=True,
    )
    op.alter_column(
        "scans",
        "finished_at",
        existing_type=sa.DateTime(timezone=True),
        type_=postgresql.TIMESTAMP(),
        existing_nullable=True,
    )
    op.alter_column(
        "scans",
        "pending_at",
        existing_type=sa.DateTime(timezone=True),
        type_=postgresql.TIMESTAMP(),
        existing_nullable=True,
    )
    op.alter_column(
        "scans",
        "queued_at",
        existing_type=sa.DateTime(timezone=True),
        type_=postgresql.TIMESTAMP(),
        existing_nullable=True,
    )
