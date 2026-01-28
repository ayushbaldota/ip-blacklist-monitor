"""Repository for IP history database operations."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import IP, IPHistory
from app.utils.logging import get_logger

logger = get_logger(__name__)


class HistoryRepository:
    """Repository for IP history database operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_history(
        self,
        ip_address: str,
        page: int = 1,
        per_page: int = 50,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
    ) -> Tuple[List[IPHistory], int]:
        """
        Get paginated history for an IP.

        Returns:
            Tuple of (list of history entries, total count)
        """
        # Default date range: last 7 days
        if from_date is None:
            from_date = datetime.now(timezone.utc) - timedelta(days=7)
        if to_date is None:
            to_date = datetime.now(timezone.utc)

        query = (
            select(IPHistory)
            .where(IPHistory.ip_address == ip_address)
            .where(IPHistory.checked_at >= from_date)
            .where(IPHistory.checked_at <= to_date)
        )

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total = (await self.db.execute(count_query)).scalar() or 0

        # Apply sorting and pagination
        query = query.order_by(IPHistory.checked_at.desc())
        offset = (page - 1) * per_page
        query = query.offset(offset).limit(per_page)

        result = await self.db.execute(query)
        history = list(result.scalars().all())

        return history, total

    async def get_summary(self, ip_address: str) -> Dict[str, Any]:
        """Get summary statistics for an IP's history."""
        # Total checks
        total_result = await self.db.execute(
            select(func.count(IPHistory.id)).where(IPHistory.ip_address == ip_address)
        )
        total_checks = total_result.scalar() or 0

        if total_checks == 0:
            return {
                "total_checks": 0,
                "times_blacklisted": 0,
                "times_clean": 0,
                "first_check": None,
                "blacklist_rate_percent": 0.0,
            }

        # Count by status
        status_result = await self.db.execute(
            select(IPHistory.status, func.count(IPHistory.id))
            .where(IPHistory.ip_address == ip_address)
            .group_by(IPHistory.status)
        )
        status_counts = {row[0]: row[1] for row in status_result.all()}

        # First check
        first_result = await self.db.execute(
            select(func.min(IPHistory.checked_at)).where(IPHistory.ip_address == ip_address)
        )
        first_check = first_result.scalar()

        times_blacklisted = status_counts.get("blacklisted", 0)
        blacklist_rate = (times_blacklisted / total_checks * 100) if total_checks > 0 else 0.0

        return {
            "total_checks": total_checks,
            "times_blacklisted": times_blacklisted,
            "times_clean": status_counts.get("clean", 0),
            "first_check": first_check,
            "blacklist_rate_percent": round(blacklist_rate, 1),
        }

    async def cleanup_old_history(self, retention_days: int = 7) -> int:
        """
        Delete history records older than retention period.

        Returns:
            Number of records deleted.
        """
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)

        result = await self.db.execute(
            delete(IPHistory).where(IPHistory.checked_at < cutoff_date)
        )

        deleted_count = result.rowcount
        await self.db.flush()

        if deleted_count > 0:
            logger.info(
                "Cleaned up old history records",
                deleted_count=deleted_count,
                retention_days=retention_days,
            )

        return deleted_count

    async def get_recent_changes(
        self,
        hours: int = 24,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Get recent status changes."""
        since = datetime.now(timezone.utc) - timedelta(hours=hours)

        # Get history with IP info
        query = (
            select(IPHistory, IP.name)
            .join(IP, IPHistory.ip_address == IP.ip_address)
            .where(IPHistory.checked_at >= since)
            .order_by(IPHistory.checked_at.desc())
            .limit(limit)
        )

        result = await self.db.execute(query)
        rows = result.all()

        changes = []
        for history, ip_name in rows:
            changes.append({
                "ip_address": history.ip_address,
                "name": ip_name,
                "status": history.status,
                "blacklist_sources": history.blacklist_sources,
                "checked_at": history.checked_at,
            })

        return changes

    async def count_today_checks(self) -> int:
        """Count checks performed today."""
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        result = await self.db.execute(
            select(func.count(IPHistory.id)).where(IPHistory.checked_at >= today_start)
        )
        return result.scalar() or 0

    async def count_today_changes(self) -> int:
        """Count status changes detected today (simplified - counts all checks)."""
        # In a real implementation, you'd compare consecutive statuses
        # For now, we count records where status is blacklisted
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        result = await self.db.execute(
            select(func.count(IPHistory.id))
            .where(IPHistory.checked_at >= today_start)
            .where(IPHistory.status == "blacklisted")
        )
        return result.scalar() or 0

    async def get_recent_activity(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent activity for the dashboard."""
        query = (
            select(IPHistory, IP.name)
            .join(IP, IPHistory.ip_address == IP.ip_address)
            .order_by(IPHistory.checked_at.desc())
            .limit(limit)
        )

        result = await self.db.execute(query)
        rows = result.all()

        activities = []
        for history, ip_name in rows:
            activities.append({
                "id": history.id,
                "ip_address": history.ip_address,
                "name": ip_name,
                "status": history.status,
                "blacklist_count": len(history.blacklist_sources) if history.blacklist_sources else 0,
                "checked_at": history.checked_at.isoformat() if history.checked_at else None,
            })

        return activities

    async def get_check_count(self, ip_address: str) -> int:
        """Get total check count for an IP."""
        result = await self.db.execute(
            select(func.count(IPHistory.id)).where(IPHistory.ip_address == ip_address)
        )
        return result.scalar() or 0
