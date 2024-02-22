"""Add subscriptions models

Revision ID: 0286cedeefc7
Revises: 8ee6f22d775a
Create Date: 2024-02-16 22:09:09.808981

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0286cedeefc7"
down_revision = "94f1cd79b7d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "packages",
        sa.Column("name", sa.String(), nullable=False, primary_key=True),
    )

    op.execute("INSERT INTO packages (name) SELECT DISTINCT name FROM scans")

    op.create_table(
        "people",
        sa.Column("id", sa.UUID(), nullable=False, primary_key=True),
        sa.Column("discord_id", sa.BigInteger(), nullable=True),
        sa.Column("email_address", sa.String(), nullable=True),
    )

    op.create_table(
        "subscriptions",
        sa.Column("package_name", sa.String(), nullable=False),
        sa.Column("person_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["package_name"],
            ["packages.name"],
        ),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["people.id"],
        ),
        sa.PrimaryKeyConstraint("package_name", "person_id"),
    )

    op.create_foreign_key("scans_packages_fkey", "scans", "packages", ["name"], ["name"])


def downgrade() -> None:
    op.drop_constraint("scans_packages_fkey", "scans", type_="foreignkey")
    op.drop_table("subscriptions")
    op.drop_table("people")
    op.drop_table("packages")
