"""add cargo_image_url to orders

Revision ID: 0003_add_cargo_image_url
Revises: 0002_add_google_id
Create Date: 2026-04-30 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_add_cargo_image_url"
down_revision: Union[str, None] = "0002_add_google_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("cargo_image_url", sa.String(1024), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "cargo_image_url")
