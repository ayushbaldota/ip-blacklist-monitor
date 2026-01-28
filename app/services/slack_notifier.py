"""Slack notification service."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from app.config import get_settings
from app.utils.logging import get_logger

logger = get_logger(__name__)
settings = get_settings()


class SlackNotifier:
    """Handles all Slack notifications."""

    def __init__(
        self,
        webhook_url: Optional[str] = None,
        enabled: bool = True,
        timeout: int = 10,
        api_base_url: Optional[str] = None,
    ):
        """
        Initialize Slack notifier.

        Args:
            webhook_url: Slack webhook URL
            enabled: Whether notifications are enabled
            timeout: Request timeout in seconds
            api_base_url: Base URL for API links in messages
        """
        self.webhook_url = webhook_url or settings.slack_webhook_url
        self.enabled = enabled and bool(self.webhook_url)
        self.timeout = timeout
        self.api_base_url = api_base_url or settings.external_api_url
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def send_blacklist_alert(
        self,
        ip_address: str,
        blacklist_sources: List[Dict[str, Any]],
        ip_name: Optional[str] = None,
    ) -> bool:
        """Send alert when IP is newly blacklisted (one-time notification)."""
        if not self.enabled:
            logger.debug("Slack notifications disabled, skipping alert")
            return True

        source_details = "\n".join(
            [
                f"• *{s.get('provider', 'Unknown')}*: {s.get('category', 'Listed')}"
                for s in blacklist_sources
            ]
        )

        # Include IP name if available
        ip_display = f"`{ip_address}`"
        if ip_name:
            ip_display = f"`{ip_address}` ({ip_name})"

        payload = {
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "IP Blacklist Alert",
                        "emoji": True,
                    },
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*IP Address:*\n{ip_display}"},
                        {"type": "mrkdwn", "text": f"*Status:*\nBlacklisted ({len(blacklist_sources)} list{'s' if len(blacklist_sources) != 1 else ''})"},
                    ],
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Detected On:*\n{source_details}",
                    },
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"Detected at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC | _This is a one-time alert_",
                        }
                    ],
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "View Details"},
                            "url": f"{self.api_base_url}/api/v1/ips/lookup?ip={ip_address}",
                            "style": "primary",
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Check AbuseIPDB"},
                            "url": f"https://www.abuseipdb.com/check/{ip_address}",
                        },
                    ],
                },
            ]
        }

        return await self._send_message(payload)

    async def send_delisted_notification(
        self,
        ip_address: str,
        ip_name: Optional[str] = None,
    ) -> bool:
        """Send notification when IP is removed from all blacklists."""
        if not self.enabled:
            return True

        # Include IP name if available
        ip_display = f"`{ip_address}`"
        if ip_name:
            ip_display = f"`{ip_address}` ({ip_name})"

        payload = {
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "IP Delisted",
                        "emoji": True,
                    },
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"Good news! {ip_display} is no longer on any monitored blacklists.",
                    },
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"Verified at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC",
                        }
                    ],
                },
            ]
        }

        return await self._send_message(payload)

    async def send_error_notification(self, title: str, error: str) -> bool:
        """Send notification about system errors."""
        if not self.enabled:
            return True

        payload = {
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"System Error: {title}",
                        "emoji": True,
                    },
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"```{error[:2000]}```"},
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"Occurred at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC",
                        }
                    ],
                },
            ]
        }

        return await self._send_message(payload)

    async def send_daily_summary(self, stats: Dict[str, Any]) -> bool:
        """Send daily summary report."""
        if not self.enabled:
            return True

        payload = {
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "Daily Blacklist Summary",
                        "emoji": True,
                    },
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Total IPs Monitored:*\n{stats.get('total_ips', 0)}",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Currently Blacklisted:*\n{stats.get('blacklisted_count', 0)}",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Checks Performed:*\n{stats.get('checks_today', 0)}",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Status Changes:*\n{stats.get('changes_today', 0)}",
                        },
                    ],
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"Report generated at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC",
                        }
                    ],
                },
            ]
        }

        return await self._send_message(payload)

    async def _send_message(self, payload: Dict[str, Any]) -> bool:
        """Send message to Slack webhook."""
        if not self.webhook_url:
            logger.warning("Slack webhook URL not configured")
            return False

        try:
            client = await self._get_client()
            response = await client.post(self.webhook_url, json=payload)

            if response.status_code == 200:
                logger.debug("Slack notification sent successfully")
                return True
            else:
                logger.error(
                    "Slack notification failed",
                    status_code=response.status_code,
                    response=response.text,
                )
                return False

        except Exception as e:
            logger.error("Failed to send Slack notification", error=str(e))
            return False

    async def health_check(self) -> bool:
        """Check if Slack is configured and accessible."""
        return bool(self.webhook_url)

    async def send_test_notification(self) -> Dict[str, Any]:
        """Send a test notification to verify webhook configuration."""
        if not self.webhook_url:
            return {
                "success": False,
                "error": "Slack webhook URL not configured",
            }

        payload = {
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "Test Notification",
                        "emoji": True,
                    },
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "This is a test notification from the IP Blacklist Monitor. If you see this message, your webhook is configured correctly!",
                    },
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"Sent at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC",
                        }
                    ],
                },
            ]
        }

        success = await self._send_message(payload)

        if success:
            return {
                "success": True,
                "message": "Test notification sent successfully",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        else:
            return {
                "success": False,
                "error": "Failed to send test notification",
            }

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
