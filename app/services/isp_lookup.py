"""ISP lookup service using ip-api.com (free, no API key required)."""

from typing import Any, Dict, Optional

import httpx

from app.utils.logging import get_logger

logger = get_logger(__name__)

# ip-api.com free tier: 45 requests per minute
ISP_API_URL = "http://ip-api.com/json/{ip}?fields=status,message,country,countryCode,isp,org"


class ISPLookupService:
    """Service to lookup ISP information for IP addresses."""

    def __init__(self, timeout: int = 5):
        """Initialize ISP lookup service."""
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def lookup(self, ip_address: str) -> Dict[str, Any]:
        """
        Lookup ISP information for an IP address.

        Args:
            ip_address: The IP address to lookup

        Returns:
            Dictionary with ISP info: {isp, org, country, country_code}
        """
        try:
            client = await self._get_client()
            response = await client.get(ISP_API_URL.format(ip=ip_address))

            if response.status_code != 200:
                logger.warning(
                    "ISP lookup failed",
                    ip=ip_address,
                    status_code=response.status_code,
                )
                return {}

            data = response.json()

            if data.get("status") != "success":
                logger.warning(
                    "ISP lookup returned error",
                    ip=ip_address,
                    message=data.get("message"),
                )
                return {}

            result = {
                "isp": data.get("isp", ""),
                "org": data.get("org", ""),
                "country": data.get("country", ""),
                "country_code": data.get("countryCode", ""),
            }

            logger.debug("ISP lookup successful", ip=ip_address, isp=result.get("isp"))
            return result

        except httpx.TimeoutException:
            logger.warning("ISP lookup timeout", ip=ip_address)
            return {}
        except Exception as e:
            logger.error("ISP lookup error", ip=ip_address, error=str(e))
            return {}

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None


# Singleton instance
_isp_service: Optional[ISPLookupService] = None


def get_isp_service() -> ISPLookupService:
    """Get or create ISP lookup service instance."""
    global _isp_service
    if _isp_service is None:
        _isp_service = ISPLookupService()
    return _isp_service
