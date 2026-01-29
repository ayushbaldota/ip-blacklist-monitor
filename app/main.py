"""
FastAPI Application Entry Point.

This module initializes and configures the FastAPI application for the IP Blacklist Monitor.
It handles:
- Application lifecycle (startup/shutdown)
- Service initialization (DNSBL providers, Slack notifier, scheduler)
- Middleware configuration (CORS, request logging, rate limiting)
- Exception handlers for API errors
- API router registration

The application monitors IP addresses against DNS-based blacklists (DNSBLs)
and provides real-time notifications via Slack when IPs are blacklisted.
"""

import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.v1 import health, ips
from app.api.v1.router import router as api_router
from app.config import get_settings
from app.core.exceptions import AppException
from app.core.rate_limiter import limiter
from app.db.database import close_db, init_db
from app.services.blacklist_checker import BlacklistCheckerService
from app.services.check_job_manager import CheckJobManager
from app.services.providers.dnsbl import create_dnsbl_providers
from app.services.slack_notifier import SlackNotifier
from app.tasks.scheduler import SchedulerService
from app.utils.logging import get_logger, setup_logging

# Initialize logging
setup_logging()
logger = get_logger(__name__)
settings = get_settings()

# Global service instances
checker_service: BlacklistCheckerService = None
scheduler_service: SchedulerService = None
slack_notifier: SlackNotifier = None
job_manager: CheckJobManager = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup and shutdown."""
    global checker_service, scheduler_service, slack_notifier, job_manager

    logger.info("Starting application", app_name=settings.app_name, env=settings.app_env)

    # Initialize database
    await init_db()
    logger.info("Database initialized")

    # Initialize Slack notifier
    slack_notifier = SlackNotifier(
        webhook_url=settings.slack_webhook_url,
        enabled=settings.slack_enabled,
        api_base_url=settings.external_api_url,
    )

    # Initialize DNSBL providers
    providers = create_dnsbl_providers(
        zones=settings.dnsbl_zones_list,
        timeout=settings.dnsbl_timeout,
    )
    logger.info("DNSBL providers initialized", count=len(providers))

    # Initialize blacklist checker service
    checker_service = BlacklistCheckerService(
        providers=providers,
        slack_notifier=slack_notifier,
        max_concurrent_checks=settings.check_max_concurrent,
    )

    # Initialize check-all job manager
    job_manager = CheckJobManager(
        checker=checker_service,
        max_concurrent_ips=settings.check_all_max_concurrent_ips,
    )
    logger.info("Check-all job manager initialized")

    # Initialize and start scheduler
    scheduler_service = SchedulerService(
        checker=checker_service,
        check_interval_hours=settings.check_interval_hours,
        max_execution_time_seconds=settings.check_timeout_seconds,
    )

    # Set services for health endpoint
    health.set_services(scheduler_service, checker_service)

    # Set checker service and job manager for IPs endpoint
    ips.set_checker_service(checker_service)
    ips.set_job_manager(job_manager)

    # Start scheduler
    await scheduler_service.start()

    logger.info("Application started successfully")

    yield  # Application is running

    # Shutdown
    logger.info("Shutting down application")

    await scheduler_service.stop()
    await checker_service.close()
    await slack_notifier.close()
    await close_db()

    logger.info("Application shutdown complete")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="IP Blacklist Monitor",
        description="Microservice for monitoring IP addresses against DNS-based blacklists",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # Add rate limiter
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # Add CORS middleware
    cors_origins = ["*"] if settings.debug else settings.cors_origins_list
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Add request logging middleware with correlation IDs
    @app.middleware("http")
    async def request_logging_middleware(request: Request, call_next):
        """Add request ID and log request/response details."""
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id

        start_time = time.time()
        response = await call_next(request)
        duration_ms = round((time.time() - start_time) * 1000)

        # Log request details (skip health checks to reduce noise)
        if not request.url.path.endswith("/health"):
            logger.info(
                "request_completed",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=duration_ms,
            )

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time"] = f"{duration_ms}ms"
        return response

    # Register exception handlers
    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
        """Handle application-specific exceptions."""
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                },
                "request_id": request.headers.get("X-Request-ID"),
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Handle Pydantic validation errors."""
        errors = []
        for error in exc.errors():
            errors.append({
                "field": ".".join(str(loc) for loc in error["loc"]),
                "message": error["msg"],
                "type": error["type"],
            })

        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Request validation failed",
                    "details": {"errors": errors},
                },
                "request_id": request.headers.get("X-Request-ID"),
            },
        )

    # Include API router
    app.include_router(api_router)

    # Root endpoint
    @app.get("/", include_in_schema=False)
    async def root() -> Dict[str, Any]:
        return {
            "name": "IP Blacklist Monitor",
            "version": "1.0.0",
            "docs": "/docs",
            "health": "/api/v1/health",
        }

    return app


# Create application instance
app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
    )
