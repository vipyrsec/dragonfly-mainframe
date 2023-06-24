"""Rename package to scan

Revision ID: 883af2539440
Revises: 5e46ee8ec64f
Create Date: 2023-06-21 12:37:16.744892

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "883af2539440"
down_revision = "5e46ee8ec64f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.rename_table("packages", "scans")
    op.alter_column("scans", "package_id", new_column_name="scan_id")

    op.alter_column("download_urls", "package_id", new_column_name="scan_id")
    op.drop_constraint("download_urls_package_id_fkey", "download_urls", type_="foreignkey")
    op.create_foreign_key("download_urls_scan_id_fkey", "download_urls", "scans", ["scan_id"], ["scan_id"])

    op.alter_column("package_rules", "package_id", new_column_name="scan_id")
    op.drop_constraint("package_rules_package_id_fkey", "package_rules", type_="foreignkey")
    op.create_foreign_key("package_rules_scan_id_fkey", "package_rules", "scans", ["scan_id"], ["scan_id"])


def downgrade() -> None:
    op.rename_table("scans", "packages")
    op.alter_column("packages", "scan_id", new_column_name="package_id")

    op.alter_column("download_urls", "scan_id", new_column_name="package_id")
    op.drop_constraint("download_urls_scan_id_fkey", "download_urls", type_="foreignkey")
    op.create_foreign_key("download_urls_package_id_fkey", "download_urls", "packages", ["package_id"], ["package_id"])

    op.alter_column("package_rules", "scan_id", new_column_name="package_id")
    op.drop_constraint("package_rules_scan_id_fkey", "package_rules", type_="foreignkey")
    op.create_foreign_key("package_rules_package_id_fkey", "package_rules", "packages", ["package_id"], ["package_id"])
