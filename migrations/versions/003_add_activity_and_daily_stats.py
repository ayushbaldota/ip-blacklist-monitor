"""Add activity_log and daily_stats tables.

Revision ID: 003
Revises: 002
Create Date: 2026-01-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create activity_log table
    op.create_table(
        "activity_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ip_id", sa.Integer(), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("activity_type", sa.String(length=50), nullable=False),
        sa.Column("old_status", sa.String(length=20), nullable=True),
        sa.Column("new_status", sa.String(length=20), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=True),
        sa.Column("triggered_by", sa.String(length=100), nullable=False, server_default="api"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "activity_type IN ('ip_added', 'ip_deleted', 'ip_updated', 'check_clean', 'check_blacklisted', 'status_change', 'manual_check')",
            name="check_activity_type",
        ),
        sa.ForeignKeyConstraint(["ip_id"], ["ips.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_activity_log_ip_id", "activity_log", ["ip_id"])
    op.create_index("idx_activity_log_activity_type", "activity_log", ["activity_type"])
    op.create_index("idx_activity_log_created_at", "activity_log", ["created_at"])

    # Create daily_stats table
    op.create_table(
        "daily_stats",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_ips", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("clean_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blacklisted_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pending_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("date"),
    )
    op.create_index("idx_daily_stats_date", "daily_stats", ["date"])


def downgrade() -> None:
    op.drop_table("daily_stats")
    op.drop_table("activity_log")
