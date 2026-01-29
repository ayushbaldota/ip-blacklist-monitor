"""SQLAlchemy database models."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class IP(Base):
    """IP address tracking model.

    Uses ip_address as the primary key instead of an auto-increment ID.
    """

    __tablename__ = "ips"

    # IP address is the primary key
    ip_address: Mapped[str] = mapped_column(String(45), primary_key=True)
    ip_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    isp: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    org: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    country_code: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    hostname: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    tags: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", index=True
    )
    last_checked: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    blacklist_sources: Mapped[List[Dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    error_sources: Mapped[List[Dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Notification muting - prevents repeated alerts for same blacklist event
    notifications_muted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_notified_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    last_notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    history: Mapped[List["IPHistory"]] = relationship(
        "IPHistory", back_populates="ip", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("ip_version IN (4, 6)", name="check_ip_version"),
        CheckConstraint("status IN ('pending', 'clean', 'blacklisted')", name="check_status"),
        Index("idx_ips_is_active", "is_active", postgresql_where=(is_active == True)),
        Index("idx_ips_status", "status"),
        Index("idx_ips_created_at", "created_at"),
        Index("idx_ips_updated_at", "updated_at"),
    )

    def __repr__(self) -> str:
        return f"<IP(ip_address={self.ip_address}, name={self.name}, status={self.status})>"


class IPHistory(Base):
    """IP check history model."""

    __tablename__ = "ip_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ip_address: Mapped[str] = mapped_column(
        String(45), ForeignKey("ips.ip_address", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    blacklist_sources: Mapped[List[Dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    check_duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    ip: Mapped["IP"] = relationship("IP", back_populates="history")

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'clean', 'blacklisted')", name="check_history_status"
        ),
        Index("idx_ip_history_ip_date", "ip_address", "checked_at"),
    )

    def __repr__(self) -> str:
        return f"<IPHistory(id={self.id}, ip_address={self.ip_address}, status={self.status})>"


class APIKey(Base):
    """API key model for authentication."""

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    permissions: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_api_keys_is_active", "is_active", postgresql_where=(is_active == True)),
    )

    def __repr__(self) -> str:
        return f"<APIKey(id={self.id}, name={self.name}, is_active={self.is_active})>"

    def has_permission(self, permission: str) -> bool:
        """Check if API key has a specific permission."""
        return permission in self.permissions


class ActivityLog(Base):
    """Activity log model for tracking system events."""

    __tablename__ = "activity_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True, index=True)
    activity_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    old_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    new_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    details: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    triggered_by: Mapped[str] = mapped_column(String(100), nullable=False, default="api")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    __table_args__ = (
        CheckConstraint(
            "activity_type IN ('ip_added', 'ip_deleted', 'ip_updated', 'check_clean', 'check_blacklisted', 'status_change', 'manual_check')",
            name="check_activity_type",
        ),
        Index("idx_activity_log_created_at_desc", created_at.desc()),
    )

    def __repr__(self) -> str:
        return f"<ActivityLog(id={self.id}, type={self.activity_type}, ip={self.ip_address})>"


class DailyStats(Base):
    """Daily statistics snapshot model."""

    __tablename__ = "daily_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), unique=True, nullable=False, index=True
    )
    total_ips: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    clean_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blacklisted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pending_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<DailyStats(id={self.id}, date={self.date}, total={self.total_ips})>"
