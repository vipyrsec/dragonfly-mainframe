"""Cache download URL

Revision ID: 7c8806e19b45
Revises: 6e1ee71402d0
Create Date: 2023-05-23 21:46:44.692584

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "7c8806e19b45"
down_revision = "6e1ee71402d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "download_urls",
        sa.Column("id", sa.UUID(), server_default=sa.FetchedValue(), nullable=False),
        sa.Column("package_id", sa.UUID(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["package_id"],
            ["packages.package_id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.alter_column("package_rules", "package_id", existing_type=sa.UUID(), nullable=False)
    op.alter_column("package_rules", "rule_name", existing_type=sa.VARCHAR(), nullable=False)
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column("package_rules", "rule_name", existing_type=sa.VARCHAR(), nullable=True)
    op.alter_column("package_rules", "package_id", existing_type=sa.UUID(), nullable=True)
    op.drop_table("download_urls")
    # ### end Alembic commands ###
