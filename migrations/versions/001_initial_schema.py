"""Initial schema with IPs, history, and API keys.

Revision ID: 001
Revises:
Create Date: 2026-01-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create IPs table
    op.create_table(
        "ips",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=False),
        sa.Column("ip_version", sa.SmallInteger(), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("last_checked", sa.DateTime(timezone=True), nullable=True),
        sa.Column("blacklist_sources", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("ip_version IN (4, 6)", name="check_ip_version"),
        sa.CheckConstraint("status IN ('pending', 'clean', 'blacklisted')", name="check_status"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ip_address"),
    )
    op.create_index("idx_ips_ip_address", "ips", ["ip_address"])
    op.create_index("idx_ips_status", "ips", ["status"])
    op.create_index("idx_ips_last_checked", "ips", ["last_checked"])
    op.create_index(
        "idx_ips_is_active",
        "ips",
        ["is_active"],
        postgresql_where=sa.text("is_active = true"),
    )
    op.create_index(
        "idx_ips_blacklist_sources",
        "ips",
        ["blacklist_sources"],
        postgresql_using="gin",
    )

    # Create IP history table
    op.create_table(
        "ip_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ip_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("blacklist_sources", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("check_duration_ms", sa.Integer(), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'clean', 'blacklisted')", name="check_history_status"
        ),
        sa.ForeignKeyConstraint(["ip_id"], ["ips.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_ip_history_ip_id", "ip_history", ["ip_id"])
    op.create_index("idx_ip_history_checked_at", "ip_history", ["checked_at"])
    op.create_index("idx_ip_history_ip_date", "ip_history", ["ip_id", "checked_at"])

    # Create API keys table
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("permissions", postgresql.JSONB(), nullable=False, server_default='["read"]'),
        sa.Column("rate_limit_per_minute", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_hash"),
    )
    op.create_index("idx_api_keys_key_hash", "api_keys", ["key_hash"])
    op.create_index(
        "idx_api_keys_is_active",
        "api_keys",
        ["is_active"],
        postgresql_where=sa.text("is_active = true"),
    )


def downgrade() -> None:
    op.drop_table("api_keys")
    op.drop_table("ip_history")
    op.drop_table("ips")
