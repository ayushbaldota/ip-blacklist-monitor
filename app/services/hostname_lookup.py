"""
Hostname Lookup Service.

Performs reverse DNS lookups to resolve IP addresses to their hostnames (PTR records).
Uses asyncio-compatible DNS resolution for high-performance lookups.
"""

import asyncio
import socket
from typing import Optional

from app.utils.logging import get_logger

logger = get_logger(__name__)


class HostnameLookupService:
    """Service to perform reverse DNS lookups for IP addresses."""

    def __init__(self, timeout: float = 3.0):
        """
        Initialize hostname lookup service.

        Args:
            timeout: DNS lookup timeout in seconds (default: 3s)
        """
        self.timeout = timeout

    async def lookup(self, ip_address: str) -> Optional[str]:
        """
        Perform reverse DNS lookup to get hostname for an IP address.

        Args:
            ip_address: The IP address to lookup

        Returns:
            Hostname string if found, None otherwise
        """
        try:
            loop = asyncio.get_event_loop()

            # Run the blocking DNS lookup in a thread executor
            hostname = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: self._resolve_hostname(ip_address)
                ),
                timeout=self.timeout
            )

            if hostname:
                logger.debug("Hostname lookup successful", ip=ip_address, hostname=hostname)
                return hostname

            return None

        except asyncio.TimeoutError:
            logger.debug("Hostname lookup timeout", ip=ip_address)
            return None
        except Exception as e:
            logger.debug("Hostname lookup failed", ip=ip_address, error=str(e))
            return None

    def _resolve_hostname(self, ip_address: str) -> Optional[str]:
        """
        Synchronous hostname resolution using socket.gethostbyaddr.

        Args:
            ip_address: The IP address to resolve

        Returns:
            Hostname if found, None otherwise
        """
        try:
            # gethostbyaddr returns (hostname, aliaslist, ipaddrlist)
            result = socket.gethostbyaddr(ip_address)
            hostname = result[0]

            # Validate hostname is not just the IP address
            if hostname and hostname != ip_address:
                return hostname

            return None
        except socket.herror:
            # Host not found
            return None
        except socket.gaierror:
            # Address-related error
            return None
        except Exception:
            return None


# Singleton instance
_hostname_service: Optional[HostnameLookupService] = None


def get_hostname_service() -> HostnameLookupService:
    """Get or create hostname lookup service instance."""
    global _hostname_service
    if _hostname_service is None:
        _hostname_service = HostnameLookupService()
    return _hostname_service
