"""add driver_response to driver_ratings

Revision ID: 0006_add_rating_driver_response
Revises: 0005_add_driver_ratings
Create Date: 2026-05-03 12:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_add_rating_driver_response"
down_revision: Union[str, None] = "0005_add_driver_ratings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "driver_ratings",
        sa.Column("driver_response", sa.String(2000), nullable=True),
    )
    op.add_column(
        "driver_ratings",
        sa.Column("driver_responded_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("driver_ratings", "driver_responded_at")
    op.drop_column("driver_ratings", "driver_response")
