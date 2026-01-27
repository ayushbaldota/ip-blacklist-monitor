"""Rate limiting configuration using SlowAPI."""

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import get_settings

settings = get_settings()


def get_api_key_or_ip(request) -> str:
    """
    Get rate limit key from API key or IP address.

    Uses API key if present, otherwise falls back to client IP.
    """
    api_key = request.headers.get("X-API-Key")
    if api_key:
        # Use first 16 chars of API key as identifier
        return f"key:{api_key[:16]}"
    return get_remote_address(request)


# Create limiter instance
limiter = Limiter(
    key_func=get_api_key_or_ip,
    default_limits=[f"{settings.rate_limit_per_minute}/minute"],
)
