"""
Background Job Manager for Check-All Operations.

This module provides background job processing for bulk IP blacklist checks.
It handles:
- Starting/stopping check-all jobs
- Progress tracking and status reporting
- Concurrent IP checking with rate limiting
- Job lifecycle management (pending -> running -> completed/cancelled/failed)

Usage:
    job_manager = CheckJobManager(checker_service)
    result = await job_manager.start_job()  # Returns job_id
    status = await job_manager.get_job_status(job_id)  # Poll for progress
    await job_manager.cancel_job(job_id)  # Cancel if needed
"""

import asyncio
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from app.db.database import AsyncSessionLocal
from app.db.repositories.ip_repository import IPRepository
from app.services.blacklist_checker import BlacklistCheckerService
from app.utils.logging import get_logger

logger = get_logger(__name__)


class JobStatus(str, Enum):
    """Status of a check-all job."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class CheckJobState:
    """State container for a check-all job."""

    def __init__(self, job_id: str, total_ips: int):
        self.job_id = job_id
        self.status = JobStatus.PENDING
        self.total = total_ips
        self.checked = 0
        self.clean = 0
        self.blacklisted = 0
        self.errors = 0
        self.error_messages: List[str] = []
        self.started_at = datetime.now(timezone.utc)
        self.completed_at: Optional[datetime] = None
        self.cancelled = False
        self._lock = asyncio.Lock()

    async def increment(
        self,
        is_blacklisted: bool = False,
        is_error: bool = False,
        error_message: Optional[str] = None,
    ):
        """Thread-safe increment of counters."""
        async with self._lock:
            self.checked += 1
            if is_error:
                self.errors += 1
                if error_message and len(self.error_messages) < 50:
                    self.error_messages.append(error_message)
            elif is_blacklisted:
                self.blacklisted += 1
            else:
                self.clean += 1

    def to_dict(self) -> Dict[str, Any]:
        """Convert job state to dictionary for API response."""
        progress = (self.checked / self.total * 100) if self.total > 0 else 0

        return {
            "job_id": self.job_id,
            "status": self.status.value,
            "progress": round(progress, 1),
            "total": self.total,
            "checked": self.checked,
            "remaining": self.total - self.checked,
            "clean": self.clean,
            "blacklisted": self.blacklisted,
            "errors": self.errors,
            "error_messages": self.error_messages[:10],
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": round(
                ((self.completed_at or datetime.now(timezone.utc)) - self.started_at).total_seconds(),
                1
            ),
        }


class CheckJobManager:
    """Manager for background check-all jobs."""

    def __init__(
        self,
        checker: BlacklistCheckerService,
        max_concurrent_ips: int = 50,
    ):
        """
        Initialize the job manager.

        Args:
            checker: The blacklist checker service
            max_concurrent_ips: Maximum IPs to check concurrently within a job
        """
        self.checker = checker
        self.max_concurrent_ips = max_concurrent_ips
        self._jobs: Dict[str, CheckJobState] = {}
        self._job_tasks: Dict[str, asyncio.Task] = {}
        self._current_job_id: Optional[str] = None
        self._max_jobs = 100

    async def start_job(self) -> Dict[str, Any]:
        """
        Start a new check-all job.

        Returns:
            Job info with job_id, total_ips, started_at
        """
        logger.info("Starting check-all job request received")

        # Check if a job is already running
        if self._current_job_id:
            existing_job = self._jobs.get(self._current_job_id)
            if existing_job and existing_job.status == JobStatus.RUNNING:
                logger.warning("A check-all job is already running", job_id=self._current_job_id)
                raise ValueError(f"A check-all job is already running: {self._current_job_id}")

        # Get all active IPs and reset them to pending
        async with AsyncSessionLocal() as db:
            ip_repo = IPRepository(db)

            # Reset all IPs to pending first
            reset_count = await ip_repo.reset_all_to_pending()
            await db.commit()
            logger.info("Reset all IPs to pending", count=reset_count)

            # Now get the IPs
            active_ips = await ip_repo.get_active_ips()
            total_ips = len(active_ips)
            ip_addresses = [ip.ip_address for ip in active_ips]

        if total_ips == 0:
            logger.warning("No active IPs to check")
            raise ValueError("No active IPs to check")

        # Create job
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        job = CheckJobState(job_id=job_id, total_ips=total_ips)

        # Cleanup old jobs if needed
        await self._cleanup_old_jobs()

        self._jobs[job_id] = job
        self._current_job_id = job_id

        # Start background task
        task = asyncio.create_task(self._run_job(job, ip_addresses))
        self._job_tasks[job_id] = task

        logger.info(
            "Check-all job created and started",
            job_id=job_id,
            total_ips=total_ips,
        )

        return {
            "job_id": job_id,
            "total_ips": total_ips,
            "started_at": job.started_at.isoformat(),
        }

    async def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get the status of a job."""
        job = self._jobs.get(job_id)
        if not job:
            return None
        return job.to_dict()

    def get_current_job(self) -> Optional[Dict[str, Any]]:
        """Get the current running job if any."""
        if self._current_job_id:
            job = self._jobs.get(self._current_job_id)
            if job and job.status == JobStatus.RUNNING:
                return job.to_dict()
        return None

    async def cancel_job(self, job_id: str) -> bool:
        """Cancel a running job."""
        job = self._jobs.get(job_id)
        if not job:
            return False

        if job.status in (JobStatus.COMPLETED, JobStatus.CANCELLED, JobStatus.FAILED):
            return False

        # Mark as cancelled
        job.cancelled = True
        job.status = JobStatus.CANCELLED
        job.completed_at = datetime.now(timezone.utc)

        # Cancel the task if running
        task = self._job_tasks.get(job_id)
        if task and not task.done():
            task.cancel()

        if self._current_job_id == job_id:
            self._current_job_id = None

        logger.info(
            "Check-all job cancelled",
            job_id=job_id,
            checked=job.checked,
            total=job.total,
        )

        return True

    async def _run_job(self, job: CheckJobState, ip_addresses: List[str]) -> None:
        """Run the check-all job in the background."""
        job.status = JobStatus.RUNNING
        logger.info("Job execution started", job_id=job.job_id, total_ips=len(ip_addresses))

        try:
            # Process IPs with semaphore for concurrency control
            semaphore = asyncio.Semaphore(self.max_concurrent_ips)

            async def check_ip(ip_address: str) -> None:
                if job.cancelled:
                    return

                async with semaphore:
                    if job.cancelled:
                        return

                    try:
                        # Check IP against blacklists
                        check_result = await self.checker.check_single_ip(ip_address)
                        is_blacklisted = check_result["is_blacklisted"]
                        new_status = "blacklisted" if is_blacklisted else "clean"

                        # Update database
                        async with AsyncSessionLocal() as db:
                            ip_repo = IPRepository(db)
                            await ip_repo.update_status(
                                ip_address=ip_address,
                                status=new_status,
                                blacklist_sources=check_result["blacklist_sources"],
                                check_duration_ms=check_result["check_duration_ms"],
                                triggered_by="check_all",
                                error_sources=check_result.get("error_sources", []),
                            )
                            await db.commit()

                        # Update job state
                        await job.increment(is_blacklisted=is_blacklisted)

                        if job.checked % 100 == 0:
                            logger.info(
                                "Job progress",
                                job_id=job.job_id,
                                checked=job.checked,
                                total=job.total,
                                progress=f"{job.checked/job.total*100:.1f}%"
                            )

                    except Exception as e:
                        error_msg = f"{ip_address}: {str(e)}"
                        logger.error("Error checking IP in job", ip=ip_address, error=str(e))
                        await job.increment(is_error=True, error_message=error_msg)

            # Run all checks concurrently
            tasks = [check_ip(ip) for ip in ip_addresses]
            await asyncio.gather(*tasks, return_exceptions=True)

            # Mark job as completed
            if not job.cancelled:
                job.status = JobStatus.COMPLETED
                job.completed_at = datetime.now(timezone.utc)

                logger.info(
                    "Check-all job completed successfully",
                    job_id=job.job_id,
                    total=job.total,
                    checked=job.checked,
                    blacklisted=job.blacklisted,
                    clean=job.clean,
                    errors=job.errors,
                    duration_seconds=round((job.completed_at - job.started_at).total_seconds(), 1),
                )

        except asyncio.CancelledError:
            job.status = JobStatus.CANCELLED
            job.completed_at = datetime.now(timezone.utc)
            logger.info("Check-all job was cancelled", job_id=job.job_id)

        except Exception as e:
            job.status = JobStatus.FAILED
            job.completed_at = datetime.now(timezone.utc)
            job.error_messages.append(f"Job failed: {str(e)}")
            logger.error("Check-all job failed", job_id=job.job_id, error=str(e))

        finally:
            if self._current_job_id == job.job_id:
                self._current_job_id = None

    async def _cleanup_old_jobs(self) -> None:
        """Remove old completed jobs to prevent memory leaks."""
        if len(self._jobs) < self._max_jobs:
            return

        completed_jobs = [
            (job_id, job)
            for job_id, job in self._jobs.items()
            if job.status in (JobStatus.COMPLETED, JobStatus.CANCELLED, JobStatus.FAILED)
            and job.completed_at is not None
        ]
        completed_jobs.sort(key=lambda x: x[1].completed_at)

        jobs_to_remove = len(self._jobs) - self._max_jobs + 10
        for job_id, _ in completed_jobs[:jobs_to_remove]:
            del self._jobs[job_id]
            if job_id in self._job_tasks:
                del self._job_tasks[job_id]

        logger.info("Cleaned up old jobs", removed=min(jobs_to_remove, len(completed_jobs)))
