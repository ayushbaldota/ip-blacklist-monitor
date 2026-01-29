"""
Hostname Update Service.

This service performs scheduled updates of PTR (hostname) records for all monitored IPs.
It runs as a background task every N hours (configurable) to keep hostname data fresh.

Features:
- Batch processing to avoid DNS overload
- Concurrent lookups with semaphore rate limiting
- Progress logging for monitoring
- Graceful error handling per IP
"""

import asyncio
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from app.config import get_settings
from app.db.database import AsyncSessionLocal
from app.db.repositories.ip_repository import IPRepository
from app.services.hostname_lookup import get_hostname_service
from app.utils.logging import get_logger

logger = get_logger(__name__)
settings = get_settings()


class HostnameUpdateService:
    """Service to update PTR records for all monitored IPs."""

    def __init__(
        self,
        batch_size: int = 50,
        lookup_timeout: float = 3.0,
    ):
        """
        Initialize the hostname update service.

        Args:
            batch_size: Number of concurrent DNS lookups
            lookup_timeout: Timeout for each DNS lookup in seconds
        """
        self.batch_size = batch_size
        self.lookup_timeout = lookup_timeout
        self.hostname_service = get_hostname_service()

    async def run_update(self) -> Dict[str, Any]:
        """
        Run a full hostname update for all active IPs.

        Returns:
            Dictionary with update statistics
        """
        start_time = datetime.now(timezone.utc)
        logger.info("Starting scheduled hostname (PTR) update")

        stats = {
            "total": 0,
            "updated": 0,
            "no_ptr": 0,
            "errors": 0,
            "unchanged": 0,
        }

        try:
            async with AsyncSessionLocal() as db:
                ip_repo = IPRepository(db)

                # Get all active IP addresses
                ip_addresses = await ip_repo.get_all_active_ip_addresses()
                stats["total"] = len(ip_addresses)

                if not ip_addresses:
                    logger.info("No active IPs to update")
                    return stats

                logger.info("Updating hostnames for IPs", count=len(ip_addresses))

                # Process in batches with semaphore for rate limiting
                semaphore = asyncio.Semaphore(self.batch_size)

                async def update_single_ip(ip_address: str) -> Optional[str]:
                    """Update hostname for a single IP."""
                    async with semaphore:
                        try:
                            hostname = await self.hostname_service.lookup(ip_address)
                            return hostname
                        except Exception as e:
                            logger.debug(
                                "Hostname lookup failed",
                                ip=ip_address,
                                error=str(e)
                            )
                            return None

                # Run all lookups concurrently
                tasks = [update_single_ip(ip) for ip in ip_addresses]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Update database with results
                for ip_address, result in zip(ip_addresses, results):
                    try:
                        if isinstance(result, Exception):
                            stats["errors"] += 1
                            continue

                        hostname = result
                        await ip_repo.update_hostname(ip_address, hostname)

                        if hostname:
                            stats["updated"] += 1
                        else:
                            stats["no_ptr"] += 1

                    except Exception as e:
                        logger.error(
                            "Failed to update hostname in database",
                            ip=ip_address,
                            error=str(e)
                        )
                        stats["errors"] += 1

                # Commit all updates
                await db.commit()

        except Exception as e:
            logger.error("Hostname update failed", error=str(e))
            raise

        duration = (datetime.now(timezone.utc) - start_time).total_seconds()

        logger.info(
            "Hostname update completed",
            duration_seconds=round(duration, 1),
            total=stats["total"],
            updated=stats["updated"],
            no_ptr=stats["no_ptr"],
            errors=stats["errors"],
        )

        return stats


# Singleton instance
_hostname_update_service: Optional[HostnameUpdateService] = None


def get_hostname_update_service() -> HostnameUpdateService:
    """Get or create hostname update service instance."""
    global _hostname_update_service
    if _hostname_update_service is None:
        _hostname_update_service = HostnameUpdateService(
            batch_size=settings.ptr_update_batch_size,
            lookup_timeout=settings.ptr_update_timeout,
        )
    return _hostname_update_service
