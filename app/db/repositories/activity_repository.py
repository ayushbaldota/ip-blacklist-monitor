"""Repository for activity log database operations."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ActivityLog, DailyStats, IP
from app.utils.logging import get_logger

logger = get_logger(__name__)


class ActivityRepository:
    """Repository for activity log database operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def log_activity(
        self,
        activity_type: str,
        ip_id: Optional[int] = None,
        ip_address: Optional[str] = None,
        old_status: Optional[str] = None,
        new_status: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        triggered_by: str = "api",
    ) -> ActivityLog:
        """Log an activity event."""
        activity = ActivityLog(
            ip_id=ip_id,
            ip_address=ip_address,
            activity_type=activity_type,
            old_status=old_status,
            new_status=new_status,
            details=details,
            triggered_by=triggered_by,
        )
        self.db.add(activity)
        await self.db.flush()

        logger.debug(
            "Activity logged",
            activity_type=activity_type,
            ip_address=ip_address,
        )
        return activity

    async def get_recent_activity(
        self,
        limit: int = 10,
        activity_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get recent activity entries."""
        query = select(ActivityLog).order_by(ActivityLog.created_at.desc())

        if activity_type:
            query = query.where(ActivityLog.activity_type == activity_type)

        query = query.limit(limit)

        result = await self.db.execute(query)
        activities = result.scalars().all()

        return [
            {
                "id": a.id,
                "type": a.activity_type,
                "activity_type": a.activity_type,
                "ip": a.ip_address,
                "ip_address": a.ip_address,
                "ip_id": a.ip_id,
                "old_status": a.old_status,
                "new_status": a.new_status,
                "details": a.details,
                "triggered_by": a.triggered_by,
                "created_at": a.created_at.isoformat() if a.created_at else None,
                "timestamp": a.created_at.isoformat() if a.created_at else None,
            }
            for a in activities
        ]

    async def cleanup_old_activity(self, retention_days: int = 30) -> int:
        """Delete activity records older than retention period."""
        from sqlalchemy import delete

        cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)

        result = await self.db.execute(
            delete(ActivityLog).where(ActivityLog.created_at < cutoff_date)
        )

        deleted_count = result.rowcount
        await self.db.flush()

        if deleted_count > 0:
            logger.info(
                "Cleaned up old activity records",
                deleted_count=deleted_count,
                retention_days=retention_days,
            )

        return deleted_count


class StatsRepository:
    """Repository for statistics database operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def record_daily_stats(self) -> DailyStats:
        """Record or update daily stats snapshot."""
        today = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        # Get current IP counts
        total_result = await self.db.execute(
            select(func.count(IP.id)).where(IP.is_active == True)
        )
        total = total_result.scalar() or 0

        status_result = await self.db.execute(
            select(IP.status, func.count(IP.id))
            .where(IP.is_active == True)
            .group_by(IP.status)
        )
        status_counts = {row[0]: row[1] for row in status_result.all()}

        # Check if we have a record for today
        existing = await self.db.execute(
            select(DailyStats).where(DailyStats.date == today)
        )
        daily_stat = existing.scalar_one_or_none()

        if daily_stat:
            daily_stat.total_ips = total
            daily_stat.clean_count = status_counts.get("clean", 0)
            daily_stat.blacklisted_count = status_counts.get("blacklisted", 0)
            daily_stat.pending_count = status_counts.get("pending", 0)
        else:
            daily_stat = DailyStats(
                date=today,
                total_ips=total,
                clean_count=status_counts.get("clean", 0),
                blacklisted_count=status_counts.get("blacklisted", 0),
                pending_count=status_counts.get("pending", 0),
            )
            self.db.add(daily_stat)

        await self.db.flush()
        return daily_stat

    async def get_history(self, days: int = 30) -> List[Dict[str, Any]]:
        """Get daily stats history for the specified number of days."""
        cutoff_date = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ) - timedelta(days=days)

        result = await self.db.execute(
            select(DailyStats)
            .where(DailyStats.date >= cutoff_date)
            .order_by(DailyStats.date.asc())
        )
        stats = result.scalars().all()

        return [
            {
                "date": s.date.strftime("%Y-%m-%d"),
                "total": s.total_ips,
                "clean": s.clean_count,
                "blacklisted": s.blacklisted_count,
                "pending": s.pending_count,
            }
            for s in stats
        ]

    async def get_provider_stats(self) -> List[Dict[str, Any]]:
        """Get blacklist counts per provider from current IP data."""
        # Get all blacklisted IPs with their sources
        result = await self.db.execute(
            select(IP.blacklist_sources)
            .where(IP.is_active == True)
            .where(IP.status == "blacklisted")
        )
        rows = result.all()

        # Count listings per provider
        provider_counts: Dict[str, int] = {}
        for (sources,) in rows:
            if sources:
                for source in sources:
                    provider = source.get("provider") or source.get("zone") or str(source)
                    provider_counts[provider] = provider_counts.get(provider, 0) + 1

        # Convert to list of dicts sorted by count
        return sorted(
            [{"name": name, "count": count} for name, count in provider_counts.items()],
            key=lambda x: x["count"],
            reverse=True,
        )

    async def cleanup_old_stats(self, retention_days: int = 90) -> int:
        """Delete daily stats older than retention period."""
        from sqlalchemy import delete

        cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)

        result = await self.db.execute(
            delete(DailyStats).where(DailyStats.date < cutoff_date)
        )

        deleted_count = result.rowcount
        await self.db.flush()

        if deleted_count > 0:
            logger.info(
                "Cleaned up old daily stats",
                deleted_count=deleted_count,
                retention_days=retention_days,
            )

        return deleted_count
