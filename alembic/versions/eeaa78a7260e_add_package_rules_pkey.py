"""add package rules pkey

Revision ID: eeaa78a7260e
Revises: 6761c4a3421c
Create Date: 2024-03-23 17:06:28.438393

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'eeaa78a7260e'
down_revision = '6761c4a3421c'
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
