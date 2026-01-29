"""Add hostname column to ips table.

Revision ID: 004
Revises: 003
Create Date: 2026-01-29

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add hostname column
    op.add_column(
        "ips",
        sa.Column("hostname", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ips", "hostname")
