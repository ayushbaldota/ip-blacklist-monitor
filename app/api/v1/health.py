"""Health check and statistics endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.common import (
    DataResponse,
    HealthCheckComponent,
    HealthCheckResponse,
    StatsResponse,
)
from app.config import get_settings
from app.core.security import require_read_permission
from app.db.database import get_db
from app.db.models import APIKey
from app.db.repositories.history_repository import HistoryRepository
from app.db.repositories.ip_repository import IPRepository
from app.utils.logging import get_logger

logger = get_logger(__name__)
settings = get_settings()

router = APIRouter(tags=["Health & Stats"])

# These will be set by the main app
_scheduler_service = None
_checker_service = None


def set_services(scheduler, checker):
    """Set service references for health checks."""
    global _scheduler_service, _checker_service
    _scheduler_service = scheduler
    _checker_service = checker


@router.get("/health", response_model=HealthCheckResponse)
async def health_check(db: AsyncSession = Depends(get_db)):
    """
    Check health of all system components.

    This endpoint does not require authentication.
    """
    checks = {}
    overall_healthy = True

    # Check database
    try:
        start = datetime.now(timezone.utc)
        await db.execute(text("SELECT 1"))
        latency = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
        checks["database"] = HealthCheckComponent(status="healthy", latency_ms=latency)
    except Exception as e:
        checks["database"] = HealthCheckComponent(status="unhealthy", error=str(e))
        overall_healthy = False

    # Check scheduler
    if _scheduler_service:
        status = _scheduler_service.get_status()
        if status["is_running"]:
            checks["scheduler"] = HealthCheckComponent(
                status="healthy",
                next_run=datetime.fromisoformat(status["next_run"])
                if status["next_run"]
                else None,
            )
        else:
            checks["scheduler"] = HealthCheckComponent(
                status="disabled" if not settings.scheduler_enabled else "unhealthy"
            )
    else:
        checks["scheduler"] = HealthCheckComponent(status="not_initialized")

    # Check Slack (just verify it's configured)
    if settings.slack_enabled and settings.slack_webhook_url:
        checks["slack"] = HealthCheckComponent(status="healthy")
    else:
        checks["slack"] = HealthCheckComponent(status="disabled")

    return HealthCheckResponse(
        status="healthy" if overall_healthy else "unhealthy",
        version="1.0.0",
        timestamp=datetime.now(timezone.utc),
        checks=checks,
    )


@router.get("/stats", response_model=StatsResponse)
async def get_stats(
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(require_read_permission),
):
    """Get system statistics."""
    ip_repo = IPRepository(db)
    history_repo = HistoryRepository(db)

    # Get IP stats
    ip_stats = await ip_repo.get_stats()

    # Get check stats
    checks_today = await history_repo.count_today_checks()
    changes_today = await history_repo.count_today_changes()

    # Get scheduler info
    scheduler_info = {}
    if _scheduler_service:
        status = _scheduler_service.get_status()
        scheduler_info = {
            "last_run": status["last_run"],
            "next_run": status["next_run"],
        }

    return StatsResponse(
        data={
            "ips": ip_stats,
            "checks": {
                "last_run": scheduler_info.get("last_run"),
                "next_run": scheduler_info.get("next_run"),
                "checks_today": checks_today,
                "status_changes_today": changes_today,
            },
            "providers": {
                "total": len(settings.dnsbl_zones_list),
                "zones": settings.dnsbl_zones_list,
            },
        }
    )
