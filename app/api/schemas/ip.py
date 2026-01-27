"""IP-related request and response schemas."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.utils.validators import validate_ip_address


class IPCreate(BaseModel):
    """Schema for creating a new IP."""

    ip_address: str = Field(..., description="IPv4 or IPv6 address", examples=["192.168.1.1"])
    description: Optional[str] = Field(
        None, max_length=255, description="Optional description", examples=["Mail server"]
    )

    @field_validator("ip_address")
    @classmethod
    def validate_ip(cls, v: str) -> str:
        is_valid, _, error = validate_ip_address(v)
        if not is_valid:
            raise ValueError(error)
        return v.strip()


class IPBulkCreate(BaseModel):
    """Schema for bulk creating IPs."""

    ips: List[IPCreate] = Field(
        ..., min_length=1, max_length=100, description="List of IPs to add (max 100)"
    )


class IPBulkResult(BaseModel):
    """Result for a single IP in bulk operation."""

    ip_address: str
    status: str = Field(..., description="added, skipped, or error")
    id: Optional[int] = None
    reason: Optional[str] = None


class IPBulkResponse(BaseModel):
    """Response for bulk IP operation."""

    added: int
    skipped: int
    results: List[IPBulkResult]


class BlacklistSource(BaseModel):
    """Schema for a blacklist source entry."""

    provider: str = Field(..., description="Provider name")
    confidence_score: Optional[int] = Field(None, ge=0, le=100, description="Confidence score")
    category: Optional[str] = Field(None, description="Listing category")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional details")
    checked_at: Optional[datetime] = Field(None, description="When the check was performed")


class IPResponse(BaseModel):
    """Schema for IP response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    ip_address: str
    ip_version: int
    description: Optional[str] = None
    status: str
    last_checked: Optional[datetime] = None
    blacklist_sources: List[Any] = Field(default_factory=list)
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None


class IPListResponse(BaseModel):
    """Schema for paginated IP list response."""

    items: List[IPResponse]
    pagination: Dict[str, Any]


class IPDeleteResponse(BaseModel):
    """Schema for IP deletion response."""

    id: int
    ip_address: str
    deleted_at: datetime


class IPHistoryEntry(BaseModel):
    """Schema for a single history entry."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    blacklist_sources: List[Any] = Field(default_factory=list)
    check_duration_ms: Optional[int] = None
    checked_at: datetime


class IPHistorySummary(BaseModel):
    """Summary statistics for IP history."""

    total_checks: int
    times_blacklisted: int
    times_clean: int
    first_check: Optional[datetime] = None
    blacklist_rate_percent: float


class IPHistoryResponse(BaseModel):
    """Schema for IP history response."""

    ip_id: int
    ip_address: str
    current_status: str
    history: List[IPHistoryEntry]
    pagination: Dict[str, Any]
    summary: IPHistorySummary


class IPCheckResponse(BaseModel):
    """Schema for manual IP check response."""

    id: int
    ip_address: str
    check_id: str
    status: str = "queued"


class IPCheckResult(BaseModel):
    """Schema for IP check result."""

    ip_address: str
    is_blacklisted: bool
    blacklist_sources: List[BlacklistSource]
    providers_checked: int
    check_duration_ms: int
    checked_at: datetime
