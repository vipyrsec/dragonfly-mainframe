"""add rules primary key

Revision ID: 6991bcb18f89
Revises: 94f1cd79b7d4
Create Date: 2024-07-04 14:31:47.752321

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "6991bcb18f89"
down_revision = "94f1cd79b7d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE rules RENAME CONSTRAINT rules_pkey TO rules_name_key")

    op.execute("ALTER TABLE package_rules DROP CONSTRAINT package_rules_rule_id_fkey")
    op.execute("ALTER TABLE rules DROP CONSTRAINT rules_id_key")

    op.execute("ALTER TABLE rules ADD CONSTRAINT rules_pkey PRIMARY KEY (id)")
    op.execute(
        "ALTER TABLE package_rules ADD CONSTRAINT package_rules_rule_id_fkey FOREIGN KEY (rule_id) REFERENCES rules(id)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE package_rules DROP CONSTRAINT package_rules_rule_id_fkey")
    op.execute("ALTER TABLE rules DROP CONSTRAINT rules_pkey")

    op.execute("ALTER TABLE rules ADD CONSTRAINT rules_id_key UNIQUE (id)")
    op.execute(
        "ALTER TABLE package_rules ADD CONSTRAINT package_rules_rule_id_fkey FOREIGN KEY (rule_id) REFERENCES rules(id)"
    )

    op.execute("ALTER TABLE rules RENAME CONSTRAINT rules_name_key TO rules_pkey")
