"""add alerting configuration

Revision ID: f6c1e85d4a29
Revises: 3f42e287fc2f
Create Date: 2026-07-25 00:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

revision = "f6c1e85d4a29"
down_revision = "3f42e287fc2f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alerting_configuration",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("production_score_threshold", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(), nullable=False),
        sa.CheckConstraint(
            "production_score_threshold >= 0",
            name="alerting_configuration_nonnegative_threshold",
        ),
        sa.CheckConstraint("id = 1", name="alerting_configuration_singleton"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        sa.text(
            """
            INSERT INTO alerting_configuration (
                id,
                production_score_threshold,
                updated_at,
                updated_by
            )
            VALUES (1, 8, CURRENT_TIMESTAMP, 'database-migration')
            """
        )
    )


def downgrade() -> None:
    op.drop_table("alerting_configuration")
