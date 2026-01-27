"""Base class for blacklist providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class BlacklistResult:
    """Result from a blacklist provider check."""

    provider_name: str
    is_listed: bool
    confidence_score: Optional[int] = None  # 0-100
    category: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    checked_at: datetime = field(default_factory=datetime.utcnow)
    response_time_ms: int = 0
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "provider": self.provider_name,
            "is_listed": self.is_listed,
            "checked_at": self.checked_at.isoformat() if self.checked_at else None,
            "response_time_ms": self.response_time_ms,
        }

        if self.confidence_score is not None:
            result["confidence_score"] = self.confidence_score
        if self.category:
            result["category"] = self.category
        if self.details:
            result["details"] = self.details
        if self.error:
            result["error"] = self.error

        return result


class BlacklistProvider(ABC):
    """Abstract base class for all blacklist providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique provider name."""
        pass

    @property
    @abstractmethod
    def provider_type(self) -> str:
        """Provider type: 'dnsbl' or 'rest_api'."""
        pass

    @abstractmethod
    async def check_ip(self, ip_address: str) -> BlacklistResult:
        """
        Check if IP is blacklisted.

        This method should NOT raise exceptions - return error in result instead.
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Verify provider is accessible."""
        pass

    async def close(self) -> None:
        """Cleanup resources. Override if needed."""
        pass
