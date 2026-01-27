"""Add tags column to ips table.

Revision ID: 002
Revises: 001
Create Date: 2026-01-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add tags column to ips table
    op.add_column(
        "ips",
        sa.Column("tags", postgresql.JSONB(), nullable=False, server_default="[]"),
    )
    # Create GIN index for efficient tag queries
    op.create_index(
        "idx_ips_tags",
        "ips",
        ["tags"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("idx_ips_tags", table_name="ips")
    op.drop_column("ips", "tags")
