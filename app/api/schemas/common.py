"""Common schemas used across the API."""

from datetime import datetime
from typing import Any, Dict, Generic, List, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ErrorDetail(BaseModel):
    """Error detail schema."""

    code: str = Field(..., description="Error code")
    message: str = Field(..., description="Human-readable error message")
    details: Dict[str, Any] = Field(default_factory=dict, description="Additional error details")


class ErrorResponse(BaseModel):
    """Standard error response schema."""

    error: ErrorDetail
    request_id: Optional[str] = Field(None, description="Request ID for tracing")


class PaginationMeta(BaseModel):
    """Pagination metadata."""

    page: int = Field(..., ge=1, description="Current page number")
    per_page: int = Field(..., ge=1, le=100, description="Items per page")
    total_items: int = Field(..., ge=0, description="Total number of items")
    total_pages: int = Field(..., ge=0, description="Total number of pages")
    has_next: bool = Field(..., description="Whether there is a next page")
    has_prev: bool = Field(..., description="Whether there is a previous page")


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response schema."""

    data: Dict[str, Any] = Field(..., description="Response data with items and pagination")


class MessageResponse(BaseModel):
    """Simple message response schema."""

    message: str = Field(..., description="Response message")


class DataResponse(BaseModel, Generic[T]):
    """Generic data response schema."""

    data: Any = Field(..., description="Response data")
    message: Optional[str] = Field(None, description="Optional message")


class HealthCheckComponent(BaseModel):
    """Health check component status."""

    status: str = Field(..., description="Component status: healthy or unhealthy")
    latency_ms: Optional[int] = Field(None, description="Latency in milliseconds")
    error: Optional[str] = Field(None, description="Error message if unhealthy")
    next_run: Optional[datetime] = Field(None, description="Next scheduled run time")


class HealthCheckResponse(BaseModel):
    """Health check response schema."""

    status: str = Field(..., description="Overall status: healthy or unhealthy")
    version: str = Field(..., description="Application version")
    timestamp: datetime = Field(..., description="Current timestamp")
    checks: Dict[str, HealthCheckComponent] = Field(..., description="Component health checks")


class StatsResponse(BaseModel):
    """Statistics response schema."""

    model_config = ConfigDict(from_attributes=True)

    data: Dict[str, Any] = Field(..., description="Statistics data")
