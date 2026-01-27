"""IP management API endpoints."""

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.common import DataResponse, ErrorResponse
from app.api.schemas.ip import (
    IPBulkCreate,
    IPBulkResponse,
    IPBulkResult,
    IPCheckResponse,
    IPCreate,
    IPDeleteResponse,
    IPHistoryEntry,
    IPHistoryResponse,
    IPHistorySummary,
    IPListResponse,
    IPResponse,
)
from app.core.exceptions import IPAlreadyExistsError, IPNotFoundError, ValidationError
from app.core.rate_limiter import limiter
from app.core.security import require_read_permission, require_write_permission
from app.db.database import get_db
from app.db.models import APIKey
from app.db.repositories.history_repository import HistoryRepository
from app.db.repositories.ip_repository import IPRepository
from app.utils.logging import get_logger
from app.utils.validators import validate_ip_address

logger = get_logger(__name__)

router = APIRouter(prefix="/ips", tags=["IPs"])


@router.post(
    "",
    response_model=DataResponse,
    status_code=201,
    responses={400: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
@limiter.limit("30/minute")
async def create_ip(
    request: Request,  # Required for rate limiter
    ip_data: IPCreate,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(require_write_permission),
):
    """Add a new IP address to monitor."""
    repo = IPRepository(db)

    try:
        ip = await repo.create(
            ip_address=ip_data.ip_address,
            description=ip_data.description,
        )
        await db.commit()

        logger.info("IP created via API", ip_id=ip.id, ip_address=ip.ip_address)

        return DataResponse(
            data=IPResponse.model_validate(ip).model_dump(),
            message="IP address added successfully",
        )

    except IPAlreadyExistsError:
        raise
    except ValueError as e:
        raise ValidationError(str(e))


@router.post(
    "/bulk",
    response_model=DataResponse,
    status_code=201,
    responses={400: {"model": ErrorResponse}},
)
@limiter.limit("10/minute")
async def create_ips_bulk(
    request: Request,
    bulk_data: IPBulkCreate,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(require_write_permission),
):
    """Add multiple IP addresses in bulk (max 100)."""
    repo = IPRepository(db)
    results = []
    added = 0
    skipped = 0

    for ip_item in bulk_data.ips:
        try:
            ip = await repo.create(
                ip_address=ip_item.ip_address,
                description=ip_item.description,
            )
            results.append(
                IPBulkResult(ip_address=ip_item.ip_address, status="added", id=ip.id)
            )
            added += 1
        except IPAlreadyExistsError:
            results.append(
                IPBulkResult(
                    ip_address=ip_item.ip_address,
                    status="skipped",
                    reason="already_exists",
                )
            )
            skipped += 1
        except Exception as e:
            results.append(
                IPBulkResult(
                    ip_address=ip_item.ip_address,
                    status="error",
                    reason=str(e),
                )
            )
            skipped += 1

    await db.commit()

    logger.info("Bulk IP creation", added=added, skipped=skipped, total=len(bulk_data.ips))

    return DataResponse(
        data=IPBulkResponse(added=added, skipped=skipped, results=results).model_dump(),
        message="Bulk operation completed",
    )


@router.get(
    "",
    response_model=DataResponse,
    responses={400: {"model": ErrorResponse}},
)
@limiter.limit("60/minute")
async def list_ips(
    request: Request,
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page"),
    status: Optional[str] = Query(None, description="Filter by status"),
    is_active: bool = Query(True, description="Filter by active status"),
    sort_by: str = Query("created_at", description="Sort field"),
    sort_order: str = Query("desc", description="Sort order"),
    search: Optional[str] = Query(None, description="Search in IP or description"),
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(require_read_permission),
):
    """Get paginated list of monitored IPs."""
    repo = IPRepository(db)

    ips, total = await repo.get_all(
        page=page,
        per_page=per_page,
        status=status,
        is_active=is_active,
        sort_by=sort_by,
        sort_order=sort_order,
        search=search,
    )

    total_pages = (total + per_page - 1) // per_page

    return DataResponse(
        data=IPListResponse(
            items=[IPResponse.model_validate(ip) for ip in ips],
            pagination={
                "page": page,
                "per_page": per_page,
                "total_items": total,
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_prev": page > 1,
            },
        ).model_dump()
    )


@router.get(
    "/lookup",
    response_model=DataResponse,
    responses={404: {"model": ErrorResponse}},
)
@limiter.limit("60/minute")
async def lookup_ip(
    request: Request,
    ip: str = Query(..., description="IP address to look up"),
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(require_read_permission),
):
    """Look up an IP address by its value."""
    # Validate IP format
    is_valid, _, error = validate_ip_address(ip)
    if not is_valid:
        raise ValidationError(error)

    repo = IPRepository(db)
    ip_record = await repo.get_by_address(ip)

    if not ip_record:
        raise IPNotFoundError(ip)

    return DataResponse(data=IPResponse.model_validate(ip_record).model_dump())


@router.get(
    "/{ip_id}",
    response_model=DataResponse,
    responses={404: {"model": ErrorResponse}},
)
@limiter.limit("60/minute")
async def get_ip(
    request: Request,
    ip_id: int,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(require_read_permission),
):
    """Get a specific IP by ID."""
    repo = IPRepository(db)
    ip = await repo.get_by_id(ip_id)

    if not ip:
        raise IPNotFoundError(ip_id)

    return DataResponse(data=IPResponse.model_validate(ip).model_dump())


@router.delete(
    "/{ip_id}",
    response_model=DataResponse,
    responses={404: {"model": ErrorResponse}},
)
@limiter.limit("30/minute")
async def delete_ip(
    request: Request,
    ip_id: int,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(require_write_permission),
):
    """Delete an IP address."""
    repo = IPRepository(db)
    ip = await repo.delete(ip_id)
    await db.commit()

    logger.info("IP deleted via API", ip_id=ip_id, ip_address=ip.ip_address)

    return DataResponse(
        data=IPDeleteResponse(
            id=ip_id,
            ip_address=ip.ip_address,
            deleted_at=datetime.now(timezone.utc),
        ).model_dump(),
        message="IP address removed successfully",
    )


@router.get(
    "/{ip_id}/history",
    response_model=DataResponse,
    responses={404: {"model": ErrorResponse}},
)
@limiter.limit("60/minute")
async def get_ip_history(
    request: Request,
    ip_id: int,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(require_read_permission),
):
    """Get check history for an IP."""
    ip_repo = IPRepository(db)
    history_repo = HistoryRepository(db)

    # Get IP record
    ip = await ip_repo.get_by_id(ip_id)
    if not ip:
        raise IPNotFoundError(ip_id)

    # Get history
    history, total = await history_repo.get_history(
        ip_id=ip_id,
        page=page,
        per_page=per_page,
        from_date=from_date,
        to_date=to_date,
    )

    # Get summary
    summary = await history_repo.get_summary(ip_id)

    total_pages = (total + per_page - 1) // per_page

    return DataResponse(
        data=IPHistoryResponse(
            ip_id=ip_id,
            ip_address=ip.ip_address,
            current_status=ip.status,
            history=[IPHistoryEntry.model_validate(h) for h in history],
            pagination={
                "page": page,
                "per_page": per_page,
                "total_items": total,
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_prev": page > 1,
            },
            summary=IPHistorySummary(**summary),
        ).model_dump()
    )


@router.post(
    "/{ip_id}/check",
    response_model=DataResponse,
    status_code=202,
    responses={404: {"model": ErrorResponse}},
)
@limiter.limit("10/minute")
async def trigger_check(
    request: Request,
    ip_id: int,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(require_write_permission),
):
    """Trigger an immediate blacklist check for an IP."""
    repo = IPRepository(db)
    ip = await repo.get_by_id(ip_id)

    if not ip:
        raise IPNotFoundError(ip_id)

    # Generate a check ID for tracking
    check_id = f"chk_{uuid.uuid4().hex[:12]}"

    logger.info("Manual check triggered", ip_id=ip_id, check_id=check_id)

    # Note: In a full implementation, this would queue a background task
    # For now, we return immediately with queued status

    return DataResponse(
        data=IPCheckResponse(
            id=ip_id,
            ip_address=ip.ip_address,
            check_id=check_id,
            status="queued",
        ).model_dump(),
        message="Blacklist check queued",
    )
