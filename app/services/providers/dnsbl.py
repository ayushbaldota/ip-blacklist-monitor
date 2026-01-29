"""
DNSBL (DNS-based Blacklist) Provider Implementation.

This module provides the core DNSBL checking functionality. It queries DNS-based
blacklists to determine if an IP address has been flagged for spam, abuse, or
other malicious activity.

How DNSBL works:
1. Reverse the IP address octets (1.2.3.4 -> 4.3.2.1)
2. Append the DNSBL zone (4.3.2.1.zen.spamhaus.org)
3. Perform DNS A record lookup
4. If response received (127.0.0.x), IP is listed
5. If NXDOMAIN, IP is clean

Supported providers (15 total):
- Spamhaus ZEN (comprehensive)
- UCEProtect L1/L2/L3 (escalating severity)
- SpamRATS (dynamic IPs, no PTR, spam)
- Barracuda, SpamCop, SORBS, PSBL, CBL
- Blocklist.de, DroneBL, Fabel Spamsources
"""

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import dns.resolver

from app.services.providers.base import BlacklistProvider, BlacklistResult
from app.utils.logging import get_logger
from app.utils.validators import reverse_ip_for_dnsbl

logger = get_logger(__name__)


# All 14 DNSBL zones from the original Apps Script
DNSBL_ZONES: Dict[str, Dict[str, Any]] = {
    # Spamhaus ZEN - comprehensive list combining SBL, XBL, PBL
    "zen.spamhaus.org": {
        "name": "Spamhaus ZEN",
        "description": "Combined Spamhaus blocklist (SBL+XBL+PBL)",
        "return_codes": {
            "127.0.0.2": "SBL (Spamhaus Block List)",
            "127.0.0.3": "SBL CSS (Spamhaus CSS)",
            "127.0.0.4": "XBL (Exploits Block List via CBL)",
            "127.0.0.9": "SBL DROP/EDROP",
            "127.0.0.10": "PBL ISP Maintained",
            "127.0.0.11": "PBL Spamhaus Maintained",
        },
    },
    # UCEProtect - 3 levels of blocking
    "dnsbl-1.uceprotect.net": {
        "name": "UCEProtect L1",
        "description": "Single IP listings",
        "return_codes": {"127.0.0.2": "Listed"},
    },
    "dnsbl-2.uceprotect.net": {
        "name": "UCEProtect L2",
        "description": "Network range listings",
        "return_codes": {"127.0.0.2": "Listed"},
    },
    "dnsbl-3.uceprotect.net": {
        "name": "UCEProtect L3",
        "description": "ASN-level listings",
        "return_codes": {"127.0.0.2": "Listed"},
    },
    # SpamRATS - 3 specialized lists
    "dyna.spamrats.com": {
        "name": "SpamRATS Dyna",
        "description": "Dynamic/residential IP addresses",
        "return_codes": {"127.0.0.36": "Dynamic IP"},
    },
    "noptr.spamrats.com": {
        "name": "SpamRATS NoPtr",
        "description": "IPs without proper reverse DNS",
        "return_codes": {"127.0.0.37": "No PTR Record"},
    },
    "spam.spamrats.com": {
        "name": "SpamRATS Spam",
        "description": "IPs caught sending spam",
        "return_codes": {"127.0.0.38": "Spam Source"},
    },
    # Barracuda
    "b.barracudacentral.org": {
        "name": "Barracuda",
        "description": "Barracuda Reputation Block List",
        "return_codes": {"127.0.0.2": "Listed"},
    },
    # SpamCop
    "bl.spamcop.net": {
        "name": "SpamCop",
        "description": "SpamCop Blocking List",
        "return_codes": {"127.0.0.2": "Listed"},
    },
    # SORBS
    "dnsbl.sorbs.net": {
        "name": "SORBS DNSBL",
        "description": "Spam and Open Relay Blocking System",
        "return_codes": {
            "127.0.0.2": "HTTP Proxy",
            "127.0.0.3": "SOCKS Proxy",
            "127.0.0.4": "Misc Proxy",
            "127.0.0.5": "SMTP Open Relay",
            "127.0.0.6": "Spam Source",
            "127.0.0.7": "Web Server Vulnerability",
            "127.0.0.8": "Block (On Demand)",
            "127.0.0.9": "Zombie/Hijacked",
            "127.0.0.10": "Dynamic IP",
            "127.0.0.11": "Bad Config",
            "127.0.0.12": "No Mail Server",
        },
    },
    # PSBL - Passive Spam Block List
    "psbl.surriel.com": {
        "name": "PSBL",
        "description": "Passive Spam Block List",
        "return_codes": {"127.0.0.2": "Listed"},
    },
    # CBL - Composite Blocking List
    "cbl.abuseat.org": {
        "name": "CBL",
        "description": "Composite Blocking List (botnet/malware)",
        "return_codes": {"127.0.0.2": "Listed"},
    },
    # Blocklist.de
    "bl.blocklist.de": {
        "name": "Blocklist.de",
        "description": "Fail2ban-based blocklist",
        "return_codes": {"127.0.0.2": "Listed"},
    },
    # DroneBL
    "dnsbl.dronebl.org": {
        "name": "DroneBL",
        "description": "Drone/botnet IP blocklist",
        "return_codes": {
            "127.0.0.2": "Sample",
            "127.0.0.3": "IRC Drone",
            "127.0.0.5": "Bottler",
            "127.0.0.6": "Unknown Spambot",
            "127.0.0.7": "DDNS Host",
            "127.0.0.8": "SOCKS Proxy",
            "127.0.0.9": "HTTP Proxy",
            "127.0.0.10": "ProxyChain",
            "127.0.0.11": "Web Page Proxy",
            "127.0.0.12": "Open DNS Resolver",
            "127.0.0.13": "Brute Force Attacker",
            "127.0.0.14": "Open Wingate Proxy",
            "127.0.0.15": "Compromised Router/Gateway",
            "127.0.0.16": "Autorooting Worm",
            "127.0.0.17": "Auto Botnet",
            "127.0.0.18": "DNS/MX",
            "127.0.0.19": "Abused VPN",
        },
    },
    # Fabel.dk spam sources
    "spamsources.fabel.dk": {
        "name": "Fabel Spamsources",
        "description": "Fabel.dk Spam Sources List",
        "return_codes": {"127.0.0.2": "Listed"},
    },
}


class DNSBLProvider(BlacklistProvider):
    """DNS-based blacklist provider."""

    def __init__(self, zone: str, timeout: float = 2.0):
        """
        Initialize DNSBL provider.

        Args:
            zone: The DNSBL zone to query (e.g., 'zen.spamhaus.org')
            timeout: DNS query timeout in seconds (default: 2s for high throughput)
        """
        self.zone = zone
        self.zone_config = DNSBL_ZONES.get(
            zone,
            {
                "name": zone,
                "description": "Custom DNSBL zone",
                "return_codes": {"127.0.0.2": "Listed"},
            },
        )
        self.timeout = timeout
        self._resolver = dns.resolver.Resolver()
        self._resolver.timeout = timeout
        self._resolver.lifetime = timeout

    @property
    def name(self) -> str:
        return self.zone_config["name"]

    @property
    def provider_type(self) -> str:
        return "dnsbl"

    async def check_ip(self, ip_address: str) -> BlacklistResult:
        """Check if IP is listed in this DNSBL."""
        start_time = datetime.now(timezone.utc)

        try:
            reversed_ip = reverse_ip_for_dnsbl(ip_address)
            query = f"{reversed_ip}.{self.zone}"

            # Run DNS query in executor to avoid blocking
            loop = asyncio.get_event_loop()

            try:
                answers = await loop.run_in_executor(
                    None, lambda: self._resolver.resolve(query, "A")
                )

                response_time = int(
                    (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
                )

                # IP is listed if we get a response
                return_code = str(answers[0])
                category = self.zone_config["return_codes"].get(
                    return_code, f"Listed ({return_code})"
                )

                logger.debug(
                    "IP listed in DNSBL",
                    ip=ip_address,
                    provider=self.name,
                    category=category,
                )

                return BlacklistResult(
                    provider_name=self.name,
                    is_listed=True,
                    category=category,
                    details={
                        "zone": self.zone,
                        "return_code": return_code,
                        "query": query,
                    },
                    checked_at=datetime.now(timezone.utc),
                    response_time_ms=response_time,
                )

            except dns.resolver.NXDOMAIN:
                # NXDOMAIN means IP is NOT listed (this is the expected "clean" response)
                response_time = int(
                    (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
                )
                return BlacklistResult(
                    provider_name=self.name,
                    is_listed=False,
                    checked_at=datetime.now(timezone.utc),
                    response_time_ms=response_time,
                )

            except dns.resolver.NoAnswer:
                # No A record means not listed
                response_time = int(
                    (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
                )
                return BlacklistResult(
                    provider_name=self.name,
                    is_listed=False,
                    checked_at=datetime.now(timezone.utc),
                    response_time_ms=response_time,
                )

            except dns.resolver.Timeout:
                response_time = int(
                    (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
                )
                logger.warning(
                    "DNSBL query timeout",
                    provider=self.name,
                    ip=ip_address,
                    timeout=self.timeout,
                )
                return BlacklistResult(
                    provider_name=self.name,
                    is_listed=False,
                    error="Query timeout",
                    checked_at=datetime.now(timezone.utc),
                    response_time_ms=response_time,
                )

        except Exception as e:
            response_time = int(
                (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
            )
            logger.error(
                "DNSBL check failed",
                provider=self.name,
                ip=ip_address,
                error=str(e),
            )
            return BlacklistResult(
                provider_name=self.name,
                is_listed=False,
                error=str(e),
                checked_at=datetime.now(timezone.utc),
                response_time_ms=response_time,
            )

    async def health_check(self) -> bool:
        """
        Check if DNSBL is responsive.

        Uses 127.0.0.2 which should always be listed in test mode for most DNSBLs.
        """
        try:
            result = await self.check_ip("127.0.0.2")
            # Most DNSBLs list 127.0.0.2 as a test IP
            # If we get any response (listed or not) without error, consider it healthy
            return result.error is None
        except Exception:
            return False


def create_dnsbl_providers(
    zones: list[str], timeout: float = 2.0
) -> list[DNSBLProvider]:
    """
    Create DNSBL provider instances for the given zones.

    Args:
        zones: List of DNSBL zone names
        timeout: DNS query timeout

    Returns:
        List of DNSBLProvider instances
    """
    providers = []
    for zone in zones:
        try:
            provider = DNSBLProvider(zone=zone, timeout=timeout)
            providers.append(provider)
            logger.info("DNSBL provider created", provider=provider.name, zone=zone)
        except Exception as e:
            logger.error("Failed to create DNSBL provider", zone=zone, error=str(e))

    return providers
