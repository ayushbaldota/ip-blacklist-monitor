"""Repository for IP-related database operations."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import IPAlreadyExistsError, IPNotFoundError
from app.db.models import IP, IPHistory
from app.utils.logging import get_logger
from app.utils.validators import validate_ip_address

logger = get_logger(__name__)


class IPRepository:
    """Repository for IP database operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        ip_address: str,
        description: Optional[str] = None,
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
            status="pending",
            blacklist_sources=[],
            is_active=True,
        )

        self.db.add(ip)
        await self.db.flush()
        await self.db.refresh(ip)

        logger.info("IP created", ip_id=ip.id, ip_address=ip_address)
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
            search_pattern = f"%{search}%"
            query = query.where(
                (IP.ip_address.ilike(search_pattern))
                | (IP.description.ilike(search_pattern))
            )

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total = (await self.db.execute(count_query)).scalar() or 0

        # Apply sorting
        sort_column = getattr(IP, sort_by, IP.created_at)
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
    ) -> IP:
        """Update IP status after a blacklist check."""
        ip = await self.get_by_id(ip_id)
        if not ip:
            raise IPNotFoundError(ip_id)

        now = datetime.now(timezone.utc)

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
