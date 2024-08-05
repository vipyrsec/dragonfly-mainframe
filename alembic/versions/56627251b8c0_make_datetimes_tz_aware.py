"""make datetimes tz aware

Revision ID: 56627251b8c0
Revises: 6991bcb18f89
Create Date: 2024-07-04 14:23:08.370773

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "56627251b8c0"
down_revision = "6991bcb18f89"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""\
ALTER TABLE scans
ALTER COLUMN queued_at TYPE TIMESTAMP WITH TIME ZONE USING queued_at AT TIME ZONE 'UTC',
ALTER COLUMN pending_at TYPE TIMESTAMP WITH TIME ZONE USING pending_at AT TIME ZONE 'UTC',
ALTER COLUMN finished_at TYPE TIMESTAMP WITH TIME ZONE USING finished_at AT TIME ZONE 'UTC',
ALTER COLUMN reported_at TYPE TIMESTAMP WITH TIME ZONE USING reported_at AT TIME ZONE 'UTC';
""")

    op.execute("ANALYZE scans;")


def downgrade() -> None:
    op.execute("""\
ALTER TABLE scans
ALTER COLUMN reported_at TYPE TIMESTAMP WITHOUT TIME ZONE,
ALTER COLUMN finished_at TYPE TIMESTAMP WITHOUT TIME ZONE,
ALTER COLUMN pending_at TYPE TIMESTAMP WITHOUT TIME ZONE,
ALTER COLUMN queued_at TYPE TIMESTAMP WITHOUT TIME ZONE;
""")

    op.execute("ANALYZE scans;")
