"""IP-related request and response schemas."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.utils.validators import validate_ip_address


class IPCreate(BaseModel):
    """Schema for creating a new IP."""

    ip_address: str = Field(..., description="IPv4 or IPv6 address", examples=["192.168.1.1"])
    name: Optional[str] = Field(
        None, max_length=100, description="Friendly name for the IP", examples=["Production Web Server"]
    )
    description: Optional[str] = Field(
        None, max_length=255, description="Optional description", examples=["Mail server"]
    )
    tags: List[str] = Field(
        default_factory=list, max_length=20, description="Tags for organization", examples=[["production", "web"]]
    )

    @field_validator("ip_address")
    @classmethod
    def validate_ip(cls, v: str) -> str:
        is_valid, _, error = validate_ip_address(v)
        if not is_valid:
            raise ValueError(error)
        return v.strip()

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: List[str]) -> List[str]:
        """Normalize tags to lowercase and remove duplicates."""
        return list(set(tag.lower().strip() for tag in v if tag.strip()))


class IPUpdate(BaseModel):
    """Schema for updating an IP."""

    name: Optional[str] = Field(
        None, max_length=100, description="Friendly name for the IP"
    )
    description: Optional[str] = Field(
        None, max_length=255, description="Optional description"
    )
    tags: Optional[List[str]] = Field(
        None, max_length=20, description="Tags for organization"
    )
    is_active: Optional[bool] = Field(None, description="Whether IP is active")

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        """Normalize tags to lowercase and remove duplicates."""
        if v is None:
            return None
        return list(set(tag.lower().strip() for tag in v if tag.strip()))


class IPBulkItem(BaseModel):
    """Schema for a single IP in bulk create."""

    ip_address: str = Field(..., description="IPv4 or IPv6 address")
    name: Optional[str] = Field(None, max_length=100, description="Friendly name for the IP")
    description: Optional[str] = Field(None, max_length=255, description="Optional description")
    tags: List[str] = Field(default_factory=list, description="Tags for this IP")

    @field_validator("ip_address")
    @classmethod
    def validate_ip(cls, v: str) -> str:
        is_valid, _, error = validate_ip_address(v)
        if not is_valid:
            raise ValueError(error)
        return v.strip()

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: List[str]) -> List[str]:
        """Normalize tags to lowercase and remove duplicates."""
        return list(set(tag.lower().strip() for tag in v if tag.strip()))


class IPBulkCreate(BaseModel):
    """Schema for bulk creating IPs."""

    ips: List[IPBulkItem] = Field(
        ..., min_length=1, max_length=100, description="List of IPs to add (max 100)"
    )
    tags: List[str] = Field(
        default_factory=list, description="Tags to apply to all IPs"
    )

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: List[str]) -> List[str]:
        """Normalize tags to lowercase and remove duplicates."""
        return list(set(tag.lower().strip() for tag in v if tag.strip()))


class IPBulkResult(BaseModel):
    """Result for a single IP in bulk operation."""

    ip_address: str
    status: str = Field(..., description="added, skipped, or error")
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

    ip_address: str
    ip_version: int
    name: Optional[str] = None
    description: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    status: str
    last_checked: Optional[datetime] = None
    blacklist_sources: List[Any] = Field(default_factory=list)
    blacklists: List[Any] = Field(default_factory=list)
    blacklist_count: int = 0
    listings: int = 0
    check_count: int = 0
    is_active: bool
    # Notification muting fields
    notifications_muted: bool = False
    last_notified_status: Optional[str] = None
    last_notified_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    @model_validator(mode="after")
    def compute_blacklist_count(self):
        """Compute blacklist_count, listings, and blacklists from blacklist_sources."""
        if self.blacklist_sources:
            self.blacklist_count = len(self.blacklist_sources)
            self.listings = len(self.blacklist_sources)
            self.blacklists = self.blacklist_sources
        return self


class IPListResponse(BaseModel):
    """Schema for paginated IP list response."""

    items: List[IPResponse]
    pagination: Dict[str, Any]


class IPDeleteResponse(BaseModel):
    """Schema for IP deletion response."""

    ip_address: str
    deleted_at: datetime


class IPHistoryEntry(BaseModel):
    """Schema for a single history entry."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    blacklist_sources: List[Any] = Field(default_factory=list)
    blacklists: List[Any] = Field(default_factory=list)
    blacklist_count: int = 0
    check_duration_ms: Optional[int] = None
    checked_at: datetime

    @model_validator(mode="after")
    def compute_blacklists(self):
        """Add blacklists alias and count for frontend compatibility."""
        if self.blacklist_sources:
            self.blacklists = self.blacklist_sources
            self.blacklist_count = len(self.blacklist_sources)
        return self


class IPHistorySummary(BaseModel):
    """Summary statistics for IP history."""

    total_checks: int
    times_blacklisted: int
    times_clean: int
    first_check: Optional[datetime] = None
    blacklist_rate_percent: float


class IPHistoryResponse(BaseModel):
    """Schema for IP history response."""

    ip_address: str
    current_status: str
    history: List[IPHistoryEntry]
    pagination: Dict[str, Any]
    summary: IPHistorySummary


class IPCheckResponse(BaseModel):
    """Schema for manual IP check response."""

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
