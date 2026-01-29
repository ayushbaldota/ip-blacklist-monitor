"""Repository for IP-related database operations."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import IPAlreadyExistsError, IPNotFoundError
from app.db.models import IP, IPHistory, ActivityLog
from app.services.hostname_lookup import get_hostname_service
from app.services.isp_lookup import get_isp_service
from app.utils.logging import get_logger
from app.utils.validators import validate_ip_address

logger = get_logger(__name__)

# Whitelist of allowed sort columns to prevent SQL injection via attribute injection
ALLOWED_SORT_COLUMNS = frozenset({
    'ip_address',
    'name',
    'status',
    'created_at',
    'updated_at',
    'last_checked',
    'description',
    'ip_version',
})

# Maximum search string length to prevent ReDoS attacks
MAX_SEARCH_LENGTH = 100


class IPRepository:
    """Repository for IP database operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        ip_address: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> IP:
        """Create a new IP record."""
        # Validate and get IP version
        is_valid, ip_version, error = validate_ip_address(ip_address)
        if not is_valid:
            raise ValueError(error)

        # Normalize IP address
        normalized_ip = ip_address.strip()

        # Check if IP already exists
        existing = await self.get_by_address(normalized_ip)
        if existing:
            raise IPAlreadyExistsError(normalized_ip)

        # Lookup ISP information
        isp_info = {}
        try:
            isp_service = get_isp_service()
            isp_info = await isp_service.lookup(normalized_ip)
        except Exception as e:
            logger.warning("Failed to lookup ISP info", ip=normalized_ip, error=str(e))

        # Lookup hostname (reverse DNS)
        hostname = None
        try:
            hostname_service = get_hostname_service()
            hostname = await hostname_service.lookup(normalized_ip)
        except Exception as e:
            logger.warning("Failed to lookup hostname", ip=normalized_ip, error=str(e))

        ip = IP(
            ip_address=normalized_ip,
            ip_version=ip_version,
            name=name,
            description=description,
            tags=tags or [],
            status="pending",
            blacklist_sources=[],
            is_active=True,
            isp=isp_info.get("isp"),
            org=isp_info.get("org"),
            country=isp_info.get("country"),
            country_code=isp_info.get("country_code"),
            hostname=hostname,
        )

        self.db.add(ip)
        await self.db.flush()
        await self.db.refresh(ip)

        # Log activity
        activity = ActivityLog(
            ip_address=ip.ip_address,
            activity_type="ip_added",
            new_status="pending",
            triggered_by="api",
        )
        self.db.add(activity)

        logger.info("IP created", ip_address=ip_address)
        return ip

    async def update(
        self,
        ip_address: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
        is_active: Optional[bool] = None,
    ) -> IP:
        """Update an IP record."""
        ip = await self.get_by_address(ip_address)
        if not ip:
            raise IPNotFoundError(ip_address)

        update_data = {"updated_at": datetime.now(timezone.utc)}

        if name is not None:
            update_data["name"] = name
        if description is not None:
            update_data["description"] = description
        if tags is not None:
            update_data["tags"] = tags
        if is_active is not None:
            update_data["is_active"] = is_active

        await self.db.execute(
            update(IP).where(IP.ip_address == ip_address).values(**update_data)
        )

        # Log activity
        activity = ActivityLog(
            ip_address=ip.ip_address,
            activity_type="ip_updated",
            details={"updated_fields": list(update_data.keys())},
            triggered_by="api",
        )
        self.db.add(activity)

        await self.db.flush()
        await self.db.refresh(ip)

        logger.info("IP updated", ip_address=ip_address, fields=list(update_data.keys()))
        return ip

    async def get_by_address(self, ip_address: str) -> Optional[IP]:
        """Get IP by address (primary key lookup)."""
        result = await self.db.execute(
            select(IP).where(IP.ip_address == ip_address.strip())
        )
        return result.scalar_one_or_none()

    async def get_all(
        self,
        page: int = 1,
        per_page: int = 20,
        status: Optional[str] = None,
        is_active: Optional[bool] = True,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        search: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> Tuple[List[IP], int]:
        """
        Get paginated list of IPs.

        Returns:
            Tuple of (list of IPs, total count)
        """
        query = select(IP)

        # Apply filters
        if status:
            query = query.where(IP.status == status)
        if is_active is not None:
            query = query.where(IP.is_active == is_active)
        if search:
            # Limit search string length to prevent ReDoS attacks
            sanitized_search = search[:MAX_SEARCH_LENGTH] if len(search) > MAX_SEARCH_LENGTH else search
            search_pattern = f"%{sanitized_search}%"
            query = query.where(
                (IP.ip_address.ilike(search_pattern))
                | (IP.name.ilike(search_pattern))
                | (IP.description.ilike(search_pattern))
            )
        if tag:
            # Filter by tag using JSONB contains operator
            query = query.where(IP.tags.contains([tag]))

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total = (await self.db.execute(count_query)).scalar() or 0

        # Apply sorting with whitelist validation to prevent SQL injection
        if sort_by not in ALLOWED_SORT_COLUMNS:
            logger.warning(
                "Invalid sort column requested, using default",
                requested=sort_by,
                allowed=list(ALLOWED_SORT_COLUMNS),
            )
            sort_by = "created_at"

        sort_column = getattr(IP, sort_by)
        if sort_order.lower() == "desc":
            query = query.order_by(sort_column.desc())
        else:
            query = query.order_by(sort_column.asc())

        # Apply pagination
        offset = (page - 1) * per_page
        query = query.offset(offset).limit(per_page)

        result = await self.db.execute(query)
        ips = list(result.scalars().all())

        return ips, total

    async def get_active_ips(self) -> List[IP]:
        """Get all active IPs for blacklist checking."""
        result = await self.db.execute(
            select(IP).where(IP.is_active == True).order_by(IP.ip_address)
        )
        return list(result.scalars().all())

    async def reset_all_to_pending(self) -> int:
        """
        Reset all active IPs to pending status.
        Used before a full check-all operation.

        Returns:
            Number of IPs reset
        """
        now = datetime.now(timezone.utc)

        # Update all active IPs to pending - clear all old data
        result = await self.db.execute(
            update(IP)
            .where(IP.is_active == True)
            .values(
                status="pending",
                blacklist_sources=[],
                error_sources=[],
                updated_at=now,
            )
        )

        await self.db.flush()

        count = result.rowcount
        logger.info("Reset all IPs to pending", count=count)
        return count

    async def update_status(
        self,
        ip_address: str,
        status: str,
        blacklist_sources: List[Dict[str, Any]],
        check_duration_ms: Optional[int] = None,
        triggered_by: str = "scheduler",
        error_sources: Optional[List[Dict[str, Any]]] = None,
    ) -> IP:
        """Update IP status after a blacklist check."""
        ip = await self.get_by_address(ip_address)
        if not ip:
            raise IPNotFoundError(ip_address)

        now = datetime.now(timezone.utc)
        old_status = ip.status

        # Update IP record
        await self.db.execute(
            update(IP)
            .where(IP.ip_address == ip_address)
            .values(
                status=status,
                blacklist_sources=blacklist_sources,
                error_sources=error_sources or [],
                last_checked=now,
                updated_at=now,
            )
        )

        # Create history record
        history = IPHistory(
            ip_address=ip_address,
            status=status,
            blacklist_sources=blacklist_sources,
            check_duration_ms=check_duration_ms,
            checked_at=now,
        )
        self.db.add(history)

        # Log activity based on status
        activity_type = "check_clean" if status == "clean" else "check_blacklisted"
        if old_status != status and old_status != "pending":
            activity_type = "status_change"

        activity = ActivityLog(
            ip_address=ip_address,
            activity_type=activity_type,
            old_status=old_status,
            new_status=status,
            details={
                "blacklist_count": len(blacklist_sources),
                "check_duration_ms": check_duration_ms,
            },
            triggered_by=triggered_by,
        )
        self.db.add(activity)

        await self.db.flush()
        await self.db.refresh(ip)

        logger.info(
            "IP status updated",
            ip_address=ip_address,
            status=status,
            sources_count=len(blacklist_sources),
        )

        return ip

    async def delete(self, ip_address: str) -> IP:
        """Delete an IP record."""
        ip = await self.get_by_address(ip_address)
        if not ip:
            raise IPNotFoundError(ip_address)

        old_status = ip.status

        # Log activity before deleting
        activity = ActivityLog(
            ip_address=ip_address,
            activity_type="ip_deleted",
            old_status=old_status,
            triggered_by="api",
        )
        self.db.add(activity)

        await self.db.execute(delete(IP).where(IP.ip_address == ip_address))
        await self.db.flush()

        logger.info("IP deleted", ip_address=ip_address)
        return ip

    async def deactivate(self, ip_address: str) -> IP:
        """Soft delete by deactivating an IP."""
        ip = await self.get_by_address(ip_address)
        if not ip:
            raise IPNotFoundError(ip_address)

        await self.db.execute(
            update(IP)
            .where(IP.ip_address == ip_address)
            .values(is_active=False, updated_at=datetime.now(timezone.utc))
        )

        await self.db.flush()
        await self.db.refresh(ip)

        logger.info("IP deactivated", ip_address=ip_address)
        return ip

    async def mute_notifications(self, ip_address: str, muted: bool = True) -> IP:
        """Mute or unmute notifications for an IP."""
        ip = await self.get_by_address(ip_address)
        if not ip:
            raise IPNotFoundError(ip_address)

        await self.db.execute(
            update(IP)
            .where(IP.ip_address == ip_address)
            .values(
                notifications_muted=muted,
                updated_at=datetime.now(timezone.utc)
            )
        )

        await self.db.flush()
        await self.db.refresh(ip)

        logger.info("IP notifications muted" if muted else "IP notifications unmuted", ip_address=ip_address)
        return ip

    async def update_notification_status(
        self,
        ip_address: str,
        notified_status: str,
    ) -> None:
        """Update the last notified status for an IP (called after sending notification)."""
        await self.db.execute(
            update(IP)
            .where(IP.ip_address == ip_address)
            .values(
                last_notified_status=notified_status,
                last_notified_at=datetime.now(timezone.utc),
            )
        )
        await self.db.flush()

    async def get_stats(self) -> Dict[str, Any]:
        """Get IP statistics."""
        # Total and active counts
        total_result = await self.db.execute(select(func.count(IP.ip_address)))
        total = total_result.scalar() or 0

        active_result = await self.db.execute(
            select(func.count(IP.ip_address)).where(IP.is_active == True)
        )
        active = active_result.scalar() or 0

        # Count by status
        status_result = await self.db.execute(
            select(IP.status, func.count(IP.ip_address))
            .where(IP.is_active == True)
            .group_by(IP.status)
        )
        by_status = {row[0]: row[1] for row in status_result.all()}

        # Count by IP version
        version_result = await self.db.execute(
            select(IP.ip_version, func.count(IP.ip_address))
            .where(IP.is_active == True)
            .group_by(IP.ip_version)
        )
        by_version = {f"ipv{row[0]}": row[1] for row in version_result.all()}

        return {
            "total": total,
            "active": active,
            "by_status": {
                "pending": by_status.get("pending", 0),
                "clean": by_status.get("clean", 0),
                "blacklisted": by_status.get("blacklisted", 0),
            },
            "by_version": {
                "ipv4": by_version.get("ipv4", 0),
                "ipv6": by_version.get("ipv6", 0),
            },
        }
