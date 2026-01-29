"""APScheduler setup for scheduled blacklist checks."""

import asyncio
from datetime import datetime, timezone
from typing import Optional

from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import text

from app.config import get_settings
from app.db.database import AsyncSessionLocal
from app.db.repositories.activity_repository import StatsRepository
from app.services.blacklist_checker import BlacklistCheckerService
from app.services.slack_notifier import SlackNotifier
from app.utils.logging import get_logger

logger = get_logger(__name__)
settings = get_settings()


class SchedulerService:
    """Manages scheduled blacklist checks."""

    def __init__(
        self,
        checker: BlacklistCheckerService,
        check_interval_hours: int = 3,
        max_execution_time_seconds: int = 300,
    ):
        """
        Initialize scheduler service.

        Args:
            checker: Blacklist checker service instance
            check_interval_hours: Hours between checks
            max_execution_time_seconds: Maximum execution time per check cycle
        """
        self.checker = checker
        self.check_interval_hours = check_interval_hours
        self.max_execution_time = max_execution_time_seconds
        self._scheduler: Optional[AsyncIOScheduler] = None
        self._is_running = False
        self._last_run: Optional[datetime] = None
        self._next_run: Optional[datetime] = None

    def setup(self) -> None:
        """Initialize the scheduler."""
        jobstores = {"default": MemoryJobStore()}

        executors = {"default": AsyncIOExecutor()}

        job_defaults = {
            "coalesce": True,  # Combine missed runs into one
            "max_instances": 1,  # Only one instance at a time
            "misfire_grace_time": 3600,  # 1 hour grace for missed jobs
        }

        self._scheduler = AsyncIOScheduler(
            jobstores=jobstores,
            executors=executors,
            job_defaults=job_defaults,
            timezone="UTC",
        )

    async def start(self) -> None:
        """Start the scheduler and register jobs."""
        if not settings.scheduler_enabled:
            logger.info("Scheduler is disabled in settings")
            return

        if self._scheduler is None:
            self.setup()

        # Register the blacklist check job
        self._scheduler.add_job(
            self._run_check,
            "interval",
            hours=self.check_interval_hours,
            id="blacklist_check",
            name="Scheduled Blacklist Check",
            replace_existing=True,
        )

        self._scheduler.start()
        self._is_running = True

        # Get next run time
        job = self._scheduler.get_job("blacklist_check")
        self._next_run = job.next_run_time if job else None

        logger.info(
            "Scheduler started",
            interval_hours=self.check_interval_hours,
            next_run=self._next_run.isoformat() if self._next_run else None,
        )

    async def _run_check(self) -> None:
        """Run the scheduled blacklist check."""
        logger.info("Starting scheduled blacklist check job")
        self._last_run = datetime.now(timezone.utc)

        try:
            # Create a new database session for this job
            async with AsyncSessionLocal() as db:
                # Try to acquire a simple lock using database
                # This prevents multiple instances from running simultaneously
                try:
                    result = await db.execute(
                        text("SELECT pg_try_advisory_lock(12345)")
                    )
                    lock_acquired = result.scalar()

                    if not lock_acquired:
                        logger.warning(
                            "Could not acquire lock, another instance may be running"
                        )
                        return

                    logger.info("Lock acquired, starting blacklist check")

                    # Run with timeout
                    try:
                        await asyncio.wait_for(
                            self.checker.run_scheduled_check(db),
                            timeout=self.max_execution_time,
                        )

                        # Record daily stats after successful check
                        stats_repo = StatsRepository(db)
                        await stats_repo.record_daily_stats()
                        await db.commit()
                        logger.info("Daily stats recorded")

                    except asyncio.TimeoutError:
                        logger.error(
                            "Check exceeded max execution time",
                            max_seconds=self.max_execution_time,
                        )
                        if self.checker.slack:
                            await self.checker.slack.send_error_notification(
                                "Scheduled check timeout",
                                f"Check exceeded {self.max_execution_time} seconds",
                            )

                finally:
                    # Release lock
                    await db.execute(text("SELECT pg_advisory_unlock(12345)"))
                    logger.info("Lock released")

        except Exception as e:
            logger.exception("Scheduled check failed", error=str(e))
            if self.checker.slack:
                await self.checker.slack.send_error_notification(
                    "Scheduled check failed", str(e)
                )

        # Update next run time
        if self._scheduler:
            job = self._scheduler.get_job("blacklist_check")
            self._next_run = job.next_run_time if job else None

    async def run_now(self) -> None:
        """Trigger an immediate check outside the schedule."""
        logger.info("Triggering immediate blacklist check")
        await self._run_check()

    async def stop(self) -> None:
        """Gracefully stop the scheduler."""
        if self._scheduler and self._is_running:
            self._scheduler.shutdown(wait=True)
            self._is_running = False
            logger.info("Scheduler stopped")

    def get_status(self) -> dict:
        """Get scheduler status information."""
        return {
            "enabled": settings.scheduler_enabled,
            "is_running": self._is_running,
            "interval_hours": self.check_interval_hours,
            "last_run": self._last_run.isoformat() if self._last_run else None,
            "next_run": self._next_run.isoformat() if self._next_run else None,
        }

    @property
    def next_run_time(self) -> Optional[datetime]:
        """Get the next scheduled run time."""
        return self._next_run
