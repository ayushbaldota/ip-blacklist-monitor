"""IP management API endpoints."""

import uuid
from datetime import datetime, timezone
from typing import List, Optional

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
    IPUpdate,
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

# Reference to checker service (set by main app)
_checker_service = None
_job_manager = None


def set_checker_service(checker):
    """Set checker service reference for manual checks."""
    global _checker_service
    _checker_service = checker


def set_job_manager(job_manager):
    """Set job manager reference for check-all operations."""
    global _job_manager
    _job_manager = job_manager


@router.post(
    "",
    response_model=DataResponse,
    status_code=201,
    responses={400: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
@limiter.limit("1200/minute")
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
            name=ip_data.name,
            description=ip_data.description,
            tags=ip_data.tags,
        )
        await db.commit()

        logger.info("IP created via API", ip_address=ip.ip_address)

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
@limiter.limit("1200/minute")
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

    # Merge bulk tags with individual item tags
    bulk_tags = bulk_data.tags

    for ip_item in bulk_data.ips:
        # Combine bulk tags with individual tags
        combined_tags = list(set(bulk_tags + ip_item.tags))
        try:
            ip = await repo.create(
                ip_address=ip_item.ip_address,
                name=ip_item.name,
                description=ip_item.description,
                tags=combined_tags,
            )
            results.append(
                IPBulkResult(ip_address=ip_item.ip_address, status="added")
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
@limiter.limit("1200/minute")
async def list_ips(
    request: Request,
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page"),
    status: Optional[str] = Query(None, description="Filter by status"),
    is_active: bool = Query(True, description="Filter by active status"),
    sort_by: str = Query("created_at", description="Sort field"),
    sort_order: str = Query("desc", description="Sort order"),
    search: Optional[str] = Query(None, description="Search in IP, name, or description"),
    tag: Optional[str] = Query(None, description="Filter by tag"),
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
        tag=tag,
    )

    total_pages = (total + per_page - 1) // per_page

    # Build response with total at root level for frontend compatibility
    response_data = {
        "items": [IPResponse.model_validate(ip).model_dump() for ip in ips],
        "total": total,
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total_items": total,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
        },
    }

    return DataResponse(data=response_data)


@router.get(
    "/lookup",
    response_model=DataResponse,
    responses={404: {"model": ErrorResponse}},
)
@limiter.limit("1200/minute")
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
    "/{ip_address}",
    response_model=DataResponse,
    responses={404: {"model": ErrorResponse}},
)
@limiter.limit("1200/minute")
async def get_ip(
    request: Request,
    ip_address: str,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(require_read_permission),
):
    """Get a specific IP by its address."""
    # Validate IP format
    is_valid, _, error = validate_ip_address(ip_address)
    if not is_valid:
        raise ValidationError(error)

    repo = IPRepository(db)
    history_repo = HistoryRepository(db)
    ip = await repo.get_by_address(ip_address)

    if not ip:
        raise IPNotFoundError(ip_address)

    # Get check count
    check_count = await history_repo.get_check_count(ip_address)

    # Build response with check_count
    response = IPResponse.model_validate(ip)
    response.check_count = check_count

    return DataResponse(data=response.model_dump())


@router.patch(
    "/{ip_address}",
    response_model=DataResponse,
    responses={404: {"model": ErrorResponse}},
)
@limiter.limit("1200/minute")
async def update_ip(
    request: Request,
    ip_address: str,
    ip_data: IPUpdate,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(require_write_permission),
):
    """Update an IP address metadata."""
    # Validate IP format
    is_valid, _, error = validate_ip_address(ip_address)
    if not is_valid:
        raise ValidationError(error)

    repo = IPRepository(db)

    ip = await repo.update(
        ip_address=ip_address,
        name=ip_data.name,
        description=ip_data.description,
        tags=ip_data.tags,
        is_active=ip_data.is_active,
    )
    await db.commit()

    logger.info("IP updated via API", ip_address=ip_address)

    return DataResponse(
        data=IPResponse.model_validate(ip).model_dump(),
        message="IP address updated successfully",
    )


@router.delete(
    "/{ip_address}",
    response_model=DataResponse,
    responses={404: {"model": ErrorResponse}},
)
@limiter.limit("1200/minute")
async def delete_ip(
    request: Request,
    ip_address: str,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(require_write_permission),
):
    """Delete an IP address."""
    # Validate IP format
    is_valid, _, error = validate_ip_address(ip_address)
    if not is_valid:
        raise ValidationError(error)

    repo = IPRepository(db)
    ip = await repo.delete(ip_address)
    await db.commit()

    logger.info("IP deleted via API", ip_address=ip_address)

    return DataResponse(
        data=IPDeleteResponse(
            ip_address=ip_address,
            deleted_at=datetime.now(timezone.utc),
        ).model_dump(),
        message="IP address removed successfully",
    )


@router.post(
    "/{ip_address}/mute",
    response_model=DataResponse,
    responses={404: {"model": ErrorResponse}},
)
@limiter.limit("1200/minute")
async def mute_ip_notifications(
    request: Request,
    ip_address: str,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(require_write_permission),
):
    """Mute notifications for an IP address.

    When muted, no Slack notifications will be sent for this IP,
    even if it becomes blacklisted.
    """
    # Validate IP format
    is_valid, _, error = validate_ip_address(ip_address)
    if not is_valid:
        raise ValidationError(error)

    repo = IPRepository(db)
    ip = await repo.mute_notifications(ip_address, muted=True)
    await db.commit()

    logger.info("IP notifications muted", ip_address=ip_address)

    return DataResponse(
        data=IPResponse.model_validate(ip).model_dump(),
        message="Notifications muted for this IP",
    )


@router.post(
    "/{ip_address}/unmute",
    response_model=DataResponse,
    responses={404: {"model": ErrorResponse}},
)
@limiter.limit("1200/minute")
async def unmute_ip_notifications(
    request: Request,
    ip_address: str,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(require_write_permission),
):
    """Unmute notifications for an IP address.

    Re-enables Slack notifications for this IP. A new notification
    will be sent if the IP is currently blacklisted.
    """
    # Validate IP format
    is_valid, _, error = validate_ip_address(ip_address)
    if not is_valid:
        raise ValidationError(error)

    repo = IPRepository(db)
    ip = await repo.mute_notifications(ip_address, muted=False)
    # Also clear last_notified_status so they get a fresh notification if currently blacklisted
    if ip.status == "blacklisted":
        await repo.update_notification_status(ip_address, notified_status=None)
    await db.commit()

    logger.info("IP notifications unmuted", ip_address=ip_address)

    return DataResponse(
        data=IPResponse.model_validate(ip).model_dump(),
        message="Notifications enabled for this IP",
    )


@router.get(
    "/{ip_address}/history",
    response_model=DataResponse,
    responses={404: {"model": ErrorResponse}},
)
@limiter.limit("1200/minute")
async def get_ip_history(
    request: Request,
    ip_address: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(require_read_permission),
):
    """Get check history for an IP."""
    # Validate IP format
    is_valid, _, error = validate_ip_address(ip_address)
    if not is_valid:
        raise ValidationError(error)

    ip_repo = IPRepository(db)
    history_repo = HistoryRepository(db)

    # Get IP record
    ip = await ip_repo.get_by_address(ip_address)
    if not ip:
        raise IPNotFoundError(ip_address)

    # Get history
    history, total = await history_repo.get_history(
        ip_address=ip_address,
        page=page,
        per_page=per_page,
        from_date=from_date,
        to_date=to_date,
    )

    # Get summary
    summary = await history_repo.get_summary(ip_address)

    total_pages = (total + per_page - 1) // per_page

    return DataResponse(
        data=IPHistoryResponse(
            ip_address=ip_address,
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
    "/bulk-check",
    response_model=DataResponse,
    status_code=200,
)
@limiter.limit("1200/minute")
async def bulk_check(
    request: Request,
    ip_addresses: List[str] = Query(..., description="List of IP addresses to check"),
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(require_write_permission),
):
    """Trigger immediate blacklist check for multiple IPs."""
    import asyncio

    repo = IPRepository(db)
    results = []

    async def check_single(ip_addr: str):
        try:
            ip = await repo.get_by_address(ip_addr)
            if not ip:
                return {"ip_address": ip_addr, "status": "error", "error": "IP not found"}

            if _checker_service:
                check_result = await _checker_service.check_single_ip(ip.ip_address)
                new_status = "blacklisted" if check_result["is_blacklisted"] else "clean"

                await repo.update_status(
                    ip_address=ip_addr,
                    status=new_status,
                    blacklist_sources=check_result["blacklist_sources"],
                    check_duration_ms=check_result["check_duration_ms"],
                    triggered_by="manual",
                )

                return {
                    "ip_address": ip_addr,
                    "status": "completed",
                    "new_status": new_status,
                    "is_blacklisted": check_result["is_blacklisted"],
                    "check_duration_ms": check_result["check_duration_ms"],
                }
            return {"ip_address": ip_addr, "status": "error", "error": "Checker not available"}
        except Exception as e:
            return {"ip_address": ip_addr, "status": "error", "error": str(e)}

    # Run all checks concurrently (limit to 50)
    results = await asyncio.gather(*[check_single(ip_addr) for ip_addr in ip_addresses[:50]])
    await db.commit()

    completed = sum(1 for r in results if r.get("status") == "completed")
    errors = sum(1 for r in results if r.get("status") == "error")

    logger.info("Bulk check completed", total=len(ip_addresses), completed=completed, errors=errors)

    return DataResponse(
        data={
            "total": len(results),
            "completed": completed,
            "errors": errors,
            "results": results,
        },
        message=f"Checked {completed} IPs",
    )


@router.post(
    "/{ip_address}/check",
    response_model=DataResponse,
    status_code=200,
    responses={404: {"model": ErrorResponse}},
)
@limiter.limit("1200/minute")
async def trigger_check(
    request: Request,
    ip_address: str,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(require_write_permission),
):
    """Trigger an immediate blacklist check for an IP."""
    # Validate IP format
    is_valid, _, error = validate_ip_address(ip_address)
    if not is_valid:
        raise ValidationError(error)

    repo = IPRepository(db)
    ip = await repo.get_by_address(ip_address)

    if not ip:
        raise IPNotFoundError(ip_address)

    # Generate a check ID for tracking
    check_id = f"chk_{uuid.uuid4().hex[:12]}"

    logger.info("Manual check triggered", ip_address=ip_address, check_id=check_id)

    # Perform synchronous check if checker service is available
    if _checker_service:
        try:
            check_result = await _checker_service.check_single_ip(ip.ip_address)

            new_status = "blacklisted" if check_result["is_blacklisted"] else "clean"

            # Update IP status in database
            await repo.update_status(
                ip_address=ip_address,
                status=new_status,
                blacklist_sources=check_result["blacklist_sources"],
                check_duration_ms=check_result["check_duration_ms"],
                triggered_by="manual",
            )
            await db.commit()

            # Refresh to get updated data
            ip = await repo.get_by_address(ip_address)

            return DataResponse(
                data={
                    "ip_address": ip_address,
                    "check_id": check_id,
                    "status": "completed",
                    "result": {
                        "is_blacklisted": check_result["is_blacklisted"],
                        "blacklist_sources": check_result["blacklist_sources"],
                        "blacklists": check_result["blacklist_sources"],
                        "providers_checked": check_result["providers_checked"],
                        "check_duration_ms": check_result["check_duration_ms"],
                    },
                    "new_status": new_status,
                },
                message="Blacklist check completed",
            )
        except Exception as e:
            logger.error("Manual check failed", ip_address=ip_address, error=str(e))
            return DataResponse(
                data=IPCheckResponse(
                    ip_address=ip_address,
                    check_id=check_id,
                    status="error",
                ).model_dump(),
                message=f"Check failed: {str(e)}",
            )

    # Fallback if checker service not available
    return DataResponse(
        data=IPCheckResponse(
            ip_address=ip_address,
            check_id=check_id,
            status="queued",
        ).model_dump(),
        message="Blacklist check queued",
    )


# ============================================================
# Check-All Endpoints (Background Job-based)
# ============================================================


@router.get(
    "/check-all/current",
    response_model=DataResponse,
)
@limiter.limit("600/minute")
async def get_current_check_job(
    request: Request,
    api_key: APIKey = Depends(require_read_permission),
):
    """
    Get the currently running check-all job, if any.

    Returns null if no job is running.
    """
    if not _job_manager:
        return DataResponse(data=None, message="No job running")

    current_job = _job_manager.get_current_job()
    return DataResponse(
        data=current_job,
        message="Current job retrieved" if current_job else "No job running",
    )


@router.post(
    "/check-all",
    response_model=DataResponse,
    status_code=202,
    responses={400: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
@limiter.limit("10/minute")
async def start_check_all_job(
    request: Request,
    api_key: APIKey = Depends(require_write_permission),
):
    """
    Start a background job to check all active IPs against blacklists.

    This will:
    1. Reset all IPs to 'pending' status
    2. Start checking all IPs in the background
    3. Return immediately with a job_id for polling

    Returns immediately with a job_id that can be used to poll for progress.
    This endpoint is rate-limited to prevent abuse.
    """
    if not _job_manager:
        from app.core.exceptions import AppException
        raise AppException(
            status_code=503,
            code="SERVICE_UNAVAILABLE",
            message="Job manager not available",
        )

    try:
        job_info = await _job_manager.start_job()

        logger.info(
            "Check-all job started via API",
            job_id=job_info["job_id"],
            total_ips=job_info["total_ips"],
        )

        return DataResponse(
            data=job_info,
            message="Check-all job started. All IPs reset to pending and checking started.",
        )

    except ValueError as e:
        from app.core.exceptions import ValidationError
        raise ValidationError(str(e))
    except Exception as e:
        logger.error("Failed to start check-all job", error=str(e))
        from app.core.exceptions import AppException
        raise AppException(
            status_code=500,
            code="JOB_START_FAILED",
            message=f"Failed to start check-all job: {str(e)}",
        )


@router.get(
    "/check-all/{job_id}/status",
    response_model=DataResponse,
    responses={404: {"model": ErrorResponse}},
)
@limiter.limit("600/minute")
async def get_check_job_status(
    request: Request,
    job_id: str,
    api_key: APIKey = Depends(require_read_permission),
):
    """
    Get the status of a check-all job.

    Returns progress information including:
    - status: pending, running, completed, cancelled, failed
    - progress: percentage complete (0-100)
    - checked: number of IPs checked
    - total: total number of IPs
    - clean: number of clean IPs
    - blacklisted: number of blacklisted IPs
    - errors: number of check errors
    """
    if not _job_manager:
        from app.core.exceptions import AppException
        raise AppException(
            status_code=503,
            code="SERVICE_UNAVAILABLE",
            message="Job manager not available",
        )

    status = await _job_manager.get_job_status(job_id)

    if not status:
        from app.core.exceptions import AppException
        raise AppException(
            status_code=404,
            code="JOB_NOT_FOUND",
            message=f"Job {job_id} not found",
        )

    return DataResponse(data=status)


@router.post(
    "/check-all/{job_id}/cancel",
    response_model=DataResponse,
    responses={404: {"model": ErrorResponse}},
)
@limiter.limit("30/minute")
async def cancel_check_job(
    request: Request,
    job_id: str,
    api_key: APIKey = Depends(require_write_permission),
):
    """
    Cancel a running check-all job.

    Returns success if the job was cancelled, or an error if the job
    was not found or already completed.
    """
    if not _job_manager:
        from app.core.exceptions import AppException
        raise AppException(
            status_code=503,
            code="SERVICE_UNAVAILABLE",
            message="Job manager not available",
        )

    cancelled = await _job_manager.cancel_job(job_id)

    if not cancelled:
        # Check if job exists
        status = await _job_manager.get_job_status(job_id)
        if not status:
            from app.core.exceptions import AppException
            raise AppException(
                status_code=404,
                code="JOB_NOT_FOUND",
                message=f"Job {job_id} not found",
            )
        else:
            from app.core.exceptions import AppException
            raise AppException(
                status_code=400,
                code="JOB_NOT_CANCELLABLE",
                message=f"Job {job_id} is already {status['status']} and cannot be cancelled",
            )

    logger.info("Check-all job cancelled via API", job_id=job_id)

    return DataResponse(
        data={"job_id": job_id, "cancelled": True},
        message="Job cancelled successfully",
    )
