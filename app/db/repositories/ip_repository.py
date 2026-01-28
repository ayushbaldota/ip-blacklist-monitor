"""Repository for IP-related database operations."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import IPAlreadyExistsError, IPNotFoundError
from app.db.models import IP, IPHistory, ActivityLog
from app.utils.logging import get_logger
from app.utils.validators import validate_ip_address

logger = get_logger(__name__)

# Whitelist of allowed sort columns to prevent SQL injection via attribute injection
ALLOWED_SORT_COLUMNS = frozenset({
    'id',
    'ip_address',
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
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> IP:
        """Create a new IP record."""
        # Validate and get IP version
        is_valid, ip_version, error = validate_ip_address(ip_address)
        if not is_valid:
            raise ValueError(error)

        # Check if IP already exists
        existing = await self.get_by_address(ip_address)
        if existing:
            raise IPAlreadyExistsError(ip_address)

        ip = IP(
            ip_address=ip_address.strip(),
            ip_version=ip_version,
            description=description,
            tags=tags or [],
            status="pending",
            blacklist_sources=[],
            is_active=True,
        )

        self.db.add(ip)
        await self.db.flush()
        await self.db.refresh(ip)

        # Log activity
        activity = ActivityLog(
            ip_id=ip.id,
            ip_address=ip.ip_address,
            activity_type="ip_added",
            new_status="pending",
            triggered_by="api",
        )
        self.db.add(activity)

        logger.info("IP created", ip_id=ip.id, ip_address=ip_address)
        return ip

    async def update(
        self,
        ip_id: int,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
        is_active: Optional[bool] = None,
    ) -> IP:
        """Update an IP record."""
        ip = await self.get_by_id(ip_id)
        if not ip:
            raise IPNotFoundError(ip_id)

        update_data = {"updated_at": datetime.now(timezone.utc)}

        if description is not None:
            update_data["description"] = description
        if tags is not None:
            update_data["tags"] = tags
        if is_active is not None:
            update_data["is_active"] = is_active

        await self.db.execute(
            update(IP).where(IP.id == ip_id).values(**update_data)
        )

        # Log activity
        activity = ActivityLog(
            ip_id=ip_id,
            ip_address=ip.ip_address,
            activity_type="ip_updated",
            details={"updated_fields": list(update_data.keys())},
            triggered_by="api",
        )
        self.db.add(activity)

        await self.db.flush()
        await self.db.refresh(ip)

        logger.info("IP updated", ip_id=ip_id, fields=list(update_data.keys()))
        return ip

    async def get_by_id(self, ip_id: int) -> Optional[IP]:
        """Get IP by ID."""
        result = await self.db.execute(select(IP).where(IP.id == ip_id))
        return result.scalar_one_or_none()

    async def get_by_address(self, ip_address: str) -> Optional[IP]:
        """Get IP by address."""
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
            select(IP).where(IP.is_active == True).order_by(IP.id)
        )
        return list(result.scalars().all())

    async def update_status(
        self,
        ip_id: int,
        status: str,
        blacklist_sources: List[Dict[str, Any]],
        check_duration_ms: Optional[int] = None,
        triggered_by: str = "scheduler",
    ) -> IP:
        """Update IP status after a blacklist check."""
        ip = await self.get_by_id(ip_id)
        if not ip:
            raise IPNotFoundError(ip_id)

        now = datetime.now(timezone.utc)
        old_status = ip.status

        # Update IP record
        await self.db.execute(
            update(IP)
            .where(IP.id == ip_id)
            .values(
                status=status,
                blacklist_sources=blacklist_sources,
                last_checked=now,
                updated_at=now,
            )
        )

        # Create history record
        history = IPHistory(
            ip_id=ip_id,
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
            ip_id=ip_id,
            ip_address=ip.ip_address,
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
            ip_id=ip_id,
            status=status,
            sources_count=len(blacklist_sources),
        )

        return ip

    async def delete(self, ip_id: int) -> IP:
        """Delete an IP record."""
        ip = await self.get_by_id(ip_id)
        if not ip:
            raise IPNotFoundError(ip_id)

        ip_address = ip.ip_address
        old_status = ip.status

        # Log activity before deleting (with ip_id set to NULL since we're deleting)
        activity = ActivityLog(
            ip_id=None,  # Will be NULL since we're deleting the IP
            ip_address=ip_address,
            activity_type="ip_deleted",
            old_status=old_status,
            triggered_by="api",
        )
        self.db.add(activity)

        await self.db.execute(delete(IP).where(IP.id == ip_id))
        await self.db.flush()

        logger.info("IP deleted", ip_id=ip_id, ip_address=ip_address)
        return ip

    async def deactivate(self, ip_id: int) -> IP:
        """Soft delete by deactivating an IP."""
        ip = await self.get_by_id(ip_id)
        if not ip:
            raise IPNotFoundError(ip_id)

        await self.db.execute(
            update(IP)
            .where(IP.id == ip_id)
            .values(is_active=False, updated_at=datetime.now(timezone.utc))
        )

        await self.db.flush()
        await self.db.refresh(ip)

        logger.info("IP deactivated", ip_id=ip_id)
        return ip

    async def get_stats(self) -> Dict[str, Any]:
        """Get IP statistics."""
        # Total and active counts
        total_result = await self.db.execute(select(func.count(IP.id)))
        total = total_result.scalar() or 0

        active_result = await self.db.execute(
            select(func.count(IP.id)).where(IP.is_active == True)
        )
        active = active_result.scalar() or 0

        # Count by status
        status_result = await self.db.execute(
            select(IP.status, func.count(IP.id))
            .where(IP.is_active == True)
            .group_by(IP.status)
        )
        by_status = {row[0]: row[1] for row in status_result.all()}

        # Count by IP version
        version_result = await self.db.execute(
            select(IP.ip_version, func.count(IP.id))
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
