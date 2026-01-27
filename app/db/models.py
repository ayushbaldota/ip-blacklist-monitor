"""SQLAlchemy database models."""

from datetime import datetime
from typing import List, Optional

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
    """IP address tracking model."""

    __tablename__ = "ips"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ip_address: Mapped[str] = mapped_column(String(45), unique=True, nullable=False, index=True)
    ip_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", index=True
    )
    last_checked: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    blacklist_sources: Mapped[dict] = mapped_column(JSONB, default=list, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
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
    )

    def __repr__(self) -> str:
        return f"<IP(id={self.id}, ip_address={self.ip_address}, status={self.status})>"


class IPHistory(Base):
    """IP check history model."""

    __tablename__ = "ip_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ip_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ips.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    blacklist_sources: Mapped[dict] = mapped_column(JSONB, default=list, nullable=False)
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
        Index("idx_ip_history_ip_date", "ip_id", "checked_at"),
    )

    def __repr__(self) -> str:
        return f"<IPHistory(id={self.id}, ip_id={self.ip_id}, status={self.status})>"


class APIKey(Base):
    """API key model for authentication."""

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    permissions: Mapped[dict] = mapped_column(JSONB, default=["read"], nullable=False)
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
