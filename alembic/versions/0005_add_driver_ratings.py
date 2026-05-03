"""add driver_ratings table

Revision ID: 0005_add_driver_ratings
Revises: 0004_add_chat
Create Date: 2026-05-03 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_add_driver_ratings"
down_revision: Union[str, None] = "0004_add_chat"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "driver_ratings",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "order_id",
            sa.BigInteger,
            sa.ForeignKey("orders.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "driver_id",
            sa.BigInteger,
            sa.ForeignKey("drivers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "customer_id",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("score", sa.Integer, nullable=False),
        sa.Column("comment", sa.String(1000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("score >= 1 AND score <= 5", name="ck_driver_ratings_score"),
    )
    op.create_index("ix_driver_ratings_order_id", "driver_ratings", ["order_id"])
    op.create_index("ix_driver_ratings_driver_id", "driver_ratings", ["driver_id"])
    op.create_index("ix_driver_ratings_customer_id", "driver_ratings", ["customer_id"])


def downgrade() -> None:
    op.drop_index("ix_driver_ratings_customer_id", table_name="driver_ratings")
    op.drop_index("ix_driver_ratings_driver_id", table_name="driver_ratings")
    op.drop_index("ix_driver_ratings_order_id", table_name="driver_ratings")
    op.drop_table("driver_ratings")
