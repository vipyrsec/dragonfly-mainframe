"""add package rules pkey

Revision ID: 49f38c26141c
Revises: 94f1cd79b7d4
Create Date: 2024-07-04 15:01:48.599379

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "49f38c26141c"
down_revision = "94f1cd79b7d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""\
        WITH cte AS (
            SELECT
                pr.*,
                ROW_NUMBER() OVER (PARTITION BY scan_id, rule_id) AS rn
            FROM package_rules AS pr
        )
        DELETE FROM package_rules
        WHERE (scan_id, rule_id) IN (SELECT scan_id, rule_id FROM cte WHERE rn > 1)
    """)

    op.execute("ALTER TABLE package_rules ADD CONSTRAINT package_rules_pkey PRIMARY KEY (scan_id, rule_id)")


def downgrade() -> None:
    op.execute("ALTER TABLE package_rules DROP CONSTRAINT package_rules_pkey")
