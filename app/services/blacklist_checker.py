"""Blacklist checker service that orchestrates checks across all providers."""

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.ip_repository import IPRepository
from app.services.providers.base import BlacklistProvider, BlacklistResult
from app.services.slack_notifier import SlackNotifier
from app.utils.logging import get_logger

logger = get_logger(__name__)


class BlacklistCheckerService:
    """Orchestrates blacklist checks across all providers."""

    def __init__(
        self,
        providers: List[BlacklistProvider],
        slack_notifier: Optional[SlackNotifier] = None,
        max_concurrent_checks: int = 200,
    ):
        """
        Initialize the blacklist checker service.

        Args:
            providers: List of blacklist providers to check against
            slack_notifier: Optional Slack notifier for alerts
            max_concurrent_checks: Maximum concurrent provider checks (default: 200 for high throughput)
        """
        self.providers = providers
        self.slack = slack_notifier
        self.semaphore = asyncio.Semaphore(max_concurrent_checks)

    async def check_single_ip(self, ip_address: str) -> Dict[str, Any]:
        """
        Check a single IP against all providers concurrently.

        Args:
            ip_address: The IP address to check

        Returns:
            Dictionary with check results
        """
        start_time = datetime.now(timezone.utc)

        async def check_with_provider(provider: BlacklistProvider) -> BlacklistResult:
            async with self.semaphore:
                return await provider.check_ip(ip_address)

        # Run all provider checks concurrently
        results = await asyncio.gather(
            *[check_with_provider(p) for p in self.providers],
            return_exceptions=True,
        )

        # Process results
        blacklist_sources = []
        errors = []

        for result in results:
            if isinstance(result, Exception):
                errors.append(str(result))
                continue

            if isinstance(result, BlacklistResult):
                if result.is_listed:
                    blacklist_sources.append(result.to_dict())
                if result.error:
                    errors.append(f"{result.provider_name}: {result.error}")

        check_duration = int(
            (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
        )

        return {
            "ip_address": ip_address,
            "is_blacklisted": len(blacklist_sources) > 0,
            "blacklist_sources": blacklist_sources,
            "providers_checked": len(self.providers),
            "providers_with_errors": len(errors),
            "errors": errors if errors else None,
            "check_duration_ms": check_duration,
            "checked_at": datetime.now(timezone.utc),
        }

    async def run_scheduled_check(self, db: AsyncSession) -> Dict[str, Any]:
        """
        Run the full scheduled check for all active IPs.

        Args:
            db: Database session

        Returns:
            Dictionary with check summary
        """
        logger.info("Starting scheduled blacklist check")
        start_time = datetime.now(timezone.utc)

        ip_repo = IPRepository(db)

        # Get all active IPs
        active_ips = await ip_repo.get_active_ips()
        logger.info("Checking active IPs", count=len(active_ips))

        results = {
            "total_checked": 0,
            "newly_blacklisted": [],
            "newly_clean": [],
            "still_blacklisted": [],
            "still_clean": [],
            "errors": [],
        }

        for ip_record in active_ips:
            try:
                check_result = await self.check_single_ip(ip_record.ip_address)
                previous_status = ip_record.status
                new_status = "blacklisted" if check_result["is_blacklisted"] else "clean"

                # Update database
                await ip_repo.update_status(
                    ip_address=ip_record.ip_address,
                    status=new_status,
                    blacklist_sources=check_result["blacklist_sources"],
                    check_duration_ms=check_result["check_duration_ms"],
                )

                # Track status changes and handle notifications
                # Notification logic: Only notify ONCE per blacklist event, not every check
                should_notify = (
                    self.slack
                    and not ip_record.notifications_muted
                )

                if previous_status != new_status:
                    if new_status == "blacklisted":
                        results["newly_blacklisted"].append(
                            {
                                "ip": ip_record.ip_address,
                                "sources": check_result["blacklist_sources"],
                            }
                        )
                        # Send ONE notification for newly blacklisted IP
                        # Only if: not muted AND we haven't already notified for this blacklist
                        if should_notify and ip_record.last_notified_status != "blacklisted":
                            await self.slack.send_blacklist_alert(
                                ip_record.ip_address,
                                check_result["blacklist_sources"],
                                ip_name=ip_record.name,
                            )
                            # Mark as notified to prevent duplicate notifications
                            await ip_repo.update_notification_status(
                                ip_record.ip_address,
                                notified_status="blacklisted",
                            )
                    else:
                        results["newly_clean"].append(ip_record.ip_address)
                        # Notify when IP is delisted (status changed from blacklisted to clean)
                        if should_notify and previous_status == "blacklisted":
                            await self.slack.send_delisted_notification(
                                ip_record.ip_address,
                                ip_name=ip_record.name,
                            )
                            # Clear notification status so future blacklist events trigger alerts
                            await ip_repo.update_notification_status(
                                ip_record.ip_address,
                                notified_status="clean",
                            )
                else:
                    if new_status == "blacklisted":
                        results["still_blacklisted"].append(ip_record.ip_address)
                        # Don't send repeat notifications for still-blacklisted IPs
                    else:
                        results["still_clean"].append(ip_record.ip_address)

                results["total_checked"] += 1

            except Exception as e:
                logger.error(
                    "Error checking IP",
                    ip=ip_record.ip_address,
                    error=str(e),
                )
                results["errors"].append(
                    {
                        "ip": ip_record.ip_address,
                        "error": str(e),
                    }
                )

        # Commit all changes
        await db.commit()

        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        logger.info(
            "Scheduled check completed",
            duration_seconds=round(duration, 2),
            total_checked=results["total_checked"],
            newly_blacklisted=len(results["newly_blacklisted"]),
            newly_clean=len(results["newly_clean"]),
            errors=len(results["errors"]),
        )

        return results

    async def health_check(self) -> Dict[str, Any]:
        """Check health of all providers."""
        results = {}

        for provider in self.providers:
            try:
                is_healthy = await provider.health_check()
                results[provider.name] = {
                    "status": "healthy" if is_healthy else "unhealthy",
                    "zone": getattr(provider, "zone", None),
                }
            except Exception as e:
                results[provider.name] = {
                    "status": "unhealthy",
                    "error": str(e),
                }

        healthy_count = sum(1 for r in results.values() if r["status"] == "healthy")

        return {
            "total_providers": len(self.providers),
            "healthy_providers": healthy_count,
            "providers": results,
        }

    async def close(self) -> None:
        """Cleanup all provider resources."""
        for provider in self.providers:
            await provider.close()
