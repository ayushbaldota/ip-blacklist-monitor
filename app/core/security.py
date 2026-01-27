"""API key authentication and security utilities."""

import hashlib
import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, Request
from fastapi.security import APIKeyHeader
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.db.database import get_db
from app.db.models import APIKey
from app.utils.logging import get_logger

logger = get_logger(__name__)

# API Key header
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def hash_api_key(key: str) -> str:
    """Hash an API key using SHA-256."""
    return hashlib.sha256(key.encode()).hexdigest()


def generate_api_key() -> str:
    """Generate a new secure API key."""
    return secrets.token_urlsafe(32)


async def get_api_key(
    request: Request,
    api_key: Optional[str] = Depends(api_key_header),
    db: AsyncSession = Depends(get_db),
) -> Optional[APIKey]:
    """
    Validate API key from request header.

    Returns None if no API key is provided (for public endpoints).
    Raises UnauthorizedError if key is invalid.
    """
    if not api_key:
        return None

    key_hash = hash_api_key(api_key)

    result = await db.execute(
        select(APIKey).where(
            APIKey.key_hash == key_hash,
            APIKey.is_active == True,
        )
    )
    api_key_obj = result.scalar_one_or_none()

    if not api_key_obj:
        logger.warning("Invalid API key attempted", key_prefix=api_key[:8])
        raise UnauthorizedError("Invalid or inactive API key")

    # Check expiration
    if api_key_obj.expires_at and api_key_obj.expires_at < datetime.now(timezone.utc):
        logger.warning("Expired API key used", key_id=api_key_obj.id)
        raise UnauthorizedError("API key has expired")

    # Update last used timestamp
    await db.execute(
        update(APIKey)
        .where(APIKey.id == api_key_obj.id)
        .values(last_used_at=datetime.now(timezone.utc))
    )

    return api_key_obj


async def require_api_key(
    api_key: Optional[APIKey] = Depends(get_api_key),
) -> APIKey:
    """Require a valid API key for the endpoint."""
    if not api_key:
        raise UnauthorizedError("API key required")
    return api_key


async def require_read_permission(
    api_key: APIKey = Depends(require_api_key),
) -> APIKey:
    """Require read permission."""
    if not api_key.has_permission("read"):
        raise ForbiddenError("Read permission required")
    return api_key


async def require_write_permission(
    api_key: APIKey = Depends(require_api_key),
) -> APIKey:
    """Require write permission."""
    if not api_key.has_permission("write"):
        raise ForbiddenError("Write permission required")
    return api_key


async def create_api_key(
    db: AsyncSession,
    name: str,
    permissions: list[str] = ["read"],
    rate_limit: int = 60,
    expires_at: Optional[datetime] = None,
) -> tuple[str, APIKey]:
    """
    Create a new API key.

    Returns:
        Tuple of (raw_key, APIKey object).
        The raw key should be shown to user once and never stored.
    """
    raw_key = generate_api_key()
    key_hash = hash_api_key(raw_key)

    api_key = APIKey(
        key_hash=key_hash,
        name=name,
        permissions=permissions,
        rate_limit_per_minute=rate_limit,
        expires_at=expires_at,
    )

    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    logger.info("API key created", key_id=api_key.id, name=name, permissions=permissions)

    return raw_key, api_key
