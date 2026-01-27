"""API v1 router that combines all endpoints."""

from fastapi import APIRouter

from app.api.v1 import health, ips

router = APIRouter(prefix="/api/v1")

# Include all sub-routers
router.include_router(ips.router)
router.include_router(health.router)
