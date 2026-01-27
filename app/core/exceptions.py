"""Custom exceptions for the application."""

from typing import Any, Dict, Optional


class AppException(Exception):
    """Base exception for all application exceptions."""

    def __init__(
        self,
        message: str,
        code: str = "APP_ERROR",
        status_code: int = 500,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)


class ValidationError(AppException):
    """Raised when input validation fails."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="VALIDATION_ERROR",
            status_code=400,
            details=details,
        )


class InvalidIPFormatError(ValidationError):
    """Raised when IP address format is invalid."""

    def __init__(self, ip_address: str, details: Optional[str] = None):
        super().__init__(
            message=f"Invalid IP address format: {ip_address}",
            details={"ip_address": ip_address, "reason": details or "Must be valid IPv4 or IPv6"},
        )


class IPAlreadyExistsError(AppException):
    """Raised when trying to add an IP that already exists."""

    def __init__(self, ip_address: str):
        super().__init__(
            message=f"IP address {ip_address} already exists",
            code="IP_ALREADY_EXISTS",
            status_code=409,
            details={"ip_address": ip_address},
        )


class IPNotFoundError(AppException):
    """Raised when an IP is not found."""

    def __init__(self, identifier: Any):
        super().__init__(
            message=f"IP not found: {identifier}",
            code="IP_NOT_FOUND",
            status_code=404,
            details={"identifier": str(identifier)},
        )


class UnauthorizedError(AppException):
    """Raised when authentication fails."""

    def __init__(self, message: str = "Authentication required"):
        super().__init__(
            message=message,
            code="UNAUTHORIZED",
            status_code=401,
        )


class ForbiddenError(AppException):
    """Raised when user lacks permission."""

    def __init__(self, message: str = "Permission denied"):
        super().__init__(
            message=message,
            code="FORBIDDEN",
            status_code=403,
        )


class RateLimitExceededError(AppException):
    """Raised when rate limit is exceeded."""

    def __init__(self, message: str = "Too many requests"):
        super().__init__(
            message=message,
            code="RATE_LIMITED",
            status_code=429,
        )


class ProviderError(AppException):
    """Raised when a blacklist provider fails."""

    def __init__(self, provider: str, message: str):
        super().__init__(
            message=f"Provider {provider} error: {message}",
            code="PROVIDER_ERROR",
            status_code=502,
            details={"provider": provider},
        )


class DatabaseError(AppException):
    """Raised when a database operation fails."""

    def __init__(self, message: str = "Database operation failed"):
        super().__init__(
            message=message,
            code="DATABASE_ERROR",
            status_code=500,
        )
