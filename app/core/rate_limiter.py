"""Rate limiting configuration using SlowAPI."""

import hashlib
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import get_settings

settings = get_settings()


def _hash_key_for_rate_limit(api_key: str) -> str:
    """
    Generate a non-reversible hash of the API key for rate limiting.

    This prevents API key enumeration attacks while still allowing
    per-key rate limiting.
    """
    # Use SHA-256 hash truncated to 16 chars for rate limit identifier
    # This is sufficient for rate limiting uniqueness without exposing key info
    return hashlib.sha256(api_key.encode()).hexdigest()[:16]


def get_api_key_or_ip(request) -> str:
    """
    Get rate limit key from API key hash or IP address.

    Uses a hash of the API key if present (to prevent enumeration attacks),
    otherwise falls back to client IP.
    """
    try:
        api_key = request.headers.get("X-API-Key")
        if api_key:
            # Use hash of API key to prevent enumeration attacks
            return f"key:{_hash_key_for_rate_limit(api_key)}"
        return get_remote_address(request)
    except Exception:
        # Fallback to IP address if any error occurs
        return get_remote_address(request)


# Create limiter instance
limiter = Limiter(
    key_func=get_api_key_or_ip,
    default_limits=[f"{settings.rate_limit_per_minute}/minute"],
)
