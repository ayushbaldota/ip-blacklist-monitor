"""IP address validation utilities."""

import ipaddress
from typing import Tuple


def validate_ip_address(ip: str) -> Tuple[bool, int, str]:
    """
    Validate an IP address and determine its version.

    Args:
        ip: The IP address string to validate.

    Returns:
        Tuple of (is_valid, ip_version, error_message).
        ip_version is 4 or 6 if valid, 0 if invalid.
    """
    ip = ip.strip()

    if not ip:
        return False, 0, "IP address cannot be empty"

    try:
        ip_obj = ipaddress.ip_address(ip)
        return True, ip_obj.version, ""
    except ValueError as e:
        return False, 0, f"Invalid IP address format: {str(e)}"


def is_valid_ipv4(ip: str) -> bool:
    """Check if the given string is a valid IPv4 address."""
    try:
        ip_obj = ipaddress.ip_address(ip.strip())
        return ip_obj.version == 4
    except ValueError:
        return False


def is_valid_ipv6(ip: str) -> bool:
    """Check if the given string is a valid IPv6 address."""
    try:
        ip_obj = ipaddress.ip_address(ip.strip())
        return ip_obj.version == 6
    except ValueError:
        return False


def reverse_ip_for_dnsbl(ip: str) -> str:
    """
    Reverse an IP address for DNSBL lookup.

    For IPv4: 1.2.3.4 -> 4.3.2.1
    For IPv6: Expand and reverse nibbles.

    Args:
        ip: The IP address to reverse.

    Returns:
        The reversed IP address string for DNSBL query.

    Raises:
        ValueError: If the IP address is invalid.
    """
    ip_obj = ipaddress.ip_address(ip.strip())

    if ip_obj.version == 4:
        # IPv4: reverse octets
        return ".".join(reversed(str(ip_obj).split(".")))
    else:
        # IPv6: expand to full form and reverse nibbles
        expanded = ip_obj.exploded.replace(":", "")
        return ".".join(reversed(expanded))


def normalize_ip(ip: str) -> str:
    """
    Normalize an IP address to its canonical form.

    Args:
        ip: The IP address to normalize.

    Returns:
        The normalized IP address string.

    Raises:
        ValueError: If the IP address is invalid.
    """
    ip_obj = ipaddress.ip_address(ip.strip())
    return str(ip_obj)
