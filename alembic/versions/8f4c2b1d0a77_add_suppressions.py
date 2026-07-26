"""add suppressions

Revision ID: 8f4c2b1d0a77
Revises: f6c1e85d4a29
Create Date: 2026-07-26 00:00:00.000000

"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "8f4c2b1d0a77"
down_revision = "f6c1e85d4a29"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "suppressions",
        sa.Column("suppression_id", sa.UUID(), nullable=False),
        sa.Column("package_name", sa.String(), nullable=False),
        sa.Column("package_version", sa.String(), nullable=False),
        sa.Column("rules", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(), nullable=False),
        sa.CheckConstraint(
            "package_name <> ''",
            name="suppressions_package_name_nonempty",
        ),
        sa.CheckConstraint(
            "package_version <> ''",
            name="suppressions_package_version_nonempty",
        ),
        sa.PrimaryKeyConstraint("suppression_id"),
    )
    op.create_index(
        "ix_suppressions_package_name_version",
        "suppressions",
        ["package_name", "package_version"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_suppressions_package_name_version",
        table_name="suppressions",
    )
    op.drop_table("suppressions")
