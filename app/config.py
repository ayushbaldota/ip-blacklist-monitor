"""
Application Configuration.

This module defines all application settings using Pydantic Settings.
Configuration is loaded from environment variables with fallback defaults.

Key configuration sections:
- Application: app name, environment, debug mode
- API Server: host, port, workers
- Database: PostgreSQL connection settings
- DNSBL Providers: blacklist zones and timeouts
- Slack: notification webhook settings
- Scheduler: check intervals and concurrency

Environment variables can be set in .env file or system environment.
"""

import secrets
from functools import lru_cache
from typing import List, Optional

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# Default insecure secret key - only for development
_INSECURE_DEFAULT_SECRET = "change-this-to-a-secure-random-string"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "ip-blacklist-monitor"
    app_env: str = "development"
    debug: bool = False
    log_level: str = "INFO"
    secret_key: str = _INSECURE_DEFAULT_SECRET

    @model_validator(mode='after')
    def validate_secret_key(self) -> 'Settings':
        """
        Validate that secret_key is secure in production.

        In production, the default insecure secret key will cause startup to fail.
        In development, a warning is logged but the application continues.
        """
        is_production = self.app_env.lower() == "production"
        is_insecure = self.secret_key == _INSECURE_DEFAULT_SECRET

        if is_insecure:
            if is_production:
                raise ValueError(
                    "SECURITY ERROR: The default secret_key is not allowed in production. "
                    "Please set a secure SECRET_KEY environment variable with at least 32 random characters. "
                    "You can generate one with: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
                )
            # In development, generate a random key and warn
            import warnings
            self.secret_key = secrets.token_urlsafe(32)
            warnings.warn(
                "Using auto-generated secret_key for development. "
                "Set SECRET_KEY environment variable for production.",
                UserWarning,
                stacklevel=2,
            )

        # Ensure minimum key length
        if len(self.secret_key) < 32:
            if is_production:
                raise ValueError(
                    "SECURITY ERROR: secret_key must be at least 32 characters long in production."
                )

        return self

    # API Server
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_workers: int = 4

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/ip_blacklist"
    database_pool_size: int = 10
    database_max_overflow: int = 20
    database_pool_timeout: int = 30

    # Rate Limiting
    rate_limit_per_minute: int = 60

    # DNSBL Providers
    dnsbl_enabled: bool = True
    dnsbl_zones: str = "zen.spamhaus.org,dnsbl-1.uceprotect.net,dnsbl-2.uceprotect.net,dnsbl-3.uceprotect.net,dyna.spamrats.com,noptr.spamrats.com,spam.spamrats.com,b.barracudacentral.org,bl.spamcop.net,dnsbl.sorbs.net,psbl.surriel.com,cbl.abuseat.org,bl.blocklist.de,dnsbl.dronebl.org,spamsources.fabel.dk"
    dnsbl_timeout: int = 3  # Timeout in seconds for DNS queries

    # AbuseIPDB (Optional)
    abuseipdb_enabled: bool = False
    abuseipdb_api_key: Optional[str] = None
    abuseipdb_threshold: int = 25

    # Slack Integration
    slack_enabled: bool = True
    slack_webhook_url: Optional[str] = None
    slack_notify_on_blacklist: bool = True
    slack_notify_on_delist: bool = True
    slack_notify_on_error: bool = True

    # Scheduler
    scheduler_enabled: bool = True
    check_interval_hours: int = 3
    check_max_concurrent: int = 200  # Increased from 10 for higher throughput
    check_timeout_seconds: int = 300

    # Check-All Job Settings
    check_all_max_concurrent_ips: int = 50  # Max IPs to check concurrently in check-all job

    # History Management
    history_retention_days: int = 7

    # External URLs
    external_api_url: str = "http://localhost:8000"

    # CORS
    cors_origins: str = ""

    @property
    def cors_origins_list(self) -> List[str]:
        """Parse CORS origins from comma-separated string."""
        if not self.cors_origins:
            return []
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def dnsbl_zones_list(self) -> List[str]:
        """Parse DNSBL zones from comma-separated string."""
        return [zone.strip() for zone in self.dnsbl_zones.split(",") if zone.strip()]

    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.app_env.lower() == "production"

    @property
    def sync_database_url(self) -> str:
        """Get synchronous database URL for Alembic migrations."""
        return self.database_url.replace("+asyncpg", "")


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
