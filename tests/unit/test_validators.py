"""Tests for IP validation utilities."""

import pytest

from app.utils.validators import (
    is_valid_ipv4,
    is_valid_ipv6,
    normalize_ip,
    reverse_ip_for_dnsbl,
    validate_ip_address,
)


class TestValidateIPAddress:
    """Tests for validate_ip_address function."""

    def test_valid_ipv4(self):
        is_valid, version, error = validate_ip_address("192.168.1.1")
        assert is_valid is True
        assert version == 4
        assert error == ""

    def test_valid_ipv4_with_zeros(self):
        is_valid, version, error = validate_ip_address("0.0.0.0")
        assert is_valid is True
        assert version == 4

    def test_valid_ipv6(self):
        is_valid, version, error = validate_ip_address("2001:db8::1")
        assert is_valid is True
        assert version == 6
        assert error == ""

    def test_valid_ipv6_full(self):
        is_valid, version, error = validate_ip_address("2001:0db8:0000:0000:0000:0000:0000:0001")
        assert is_valid is True
        assert version == 6

    def test_invalid_ip_format(self):
        is_valid, version, error = validate_ip_address("not-an-ip")
        assert is_valid is False
        assert version == 0
        assert "Invalid" in error

    def test_invalid_ipv4_out_of_range(self):
        is_valid, version, error = validate_ip_address("256.1.1.1")
        assert is_valid is False
        assert version == 0

    def test_empty_string(self):
        is_valid, version, error = validate_ip_address("")
        assert is_valid is False
        assert version == 0
        assert "empty" in error.lower()

    def test_whitespace_trimming(self):
        is_valid, version, error = validate_ip_address("  192.168.1.1  ")
        assert is_valid is True
        assert version == 4


class TestIsValidIPv4:
    """Tests for is_valid_ipv4 function."""

    def test_valid_ipv4(self):
        assert is_valid_ipv4("192.168.1.1") is True

    def test_ipv6_returns_false(self):
        assert is_valid_ipv4("2001:db8::1") is False

    def test_invalid_returns_false(self):
        assert is_valid_ipv4("invalid") is False


class TestIsValidIPv6:
    """Tests for is_valid_ipv6 function."""

    def test_valid_ipv6(self):
        assert is_valid_ipv6("2001:db8::1") is True

    def test_ipv4_returns_false(self):
        assert is_valid_ipv6("192.168.1.1") is False

    def test_invalid_returns_false(self):
        assert is_valid_ipv6("invalid") is False


class TestReverseIPForDNSBL:
    """Tests for reverse_ip_for_dnsbl function."""

    def test_reverse_ipv4(self):
        result = reverse_ip_for_dnsbl("1.2.3.4")
        assert result == "4.3.2.1"

    def test_reverse_ipv4_with_zeros(self):
        result = reverse_ip_for_dnsbl("192.168.0.1")
        assert result == "1.0.168.192"

    def test_reverse_ipv6(self):
        # IPv6 reverses nibbles
        result = reverse_ip_for_dnsbl("2001:db8::1")
        # Should be expanded and reversed
        assert len(result.split(".")) == 32  # 32 nibbles

    def test_invalid_ip_raises(self):
        with pytest.raises(ValueError):
            reverse_ip_for_dnsbl("invalid")


class TestNormalizeIP:
    """Tests for normalize_ip function."""

    def test_normalize_ipv4(self):
        result = normalize_ip("192.168.001.001")
        assert result == "192.168.1.1"

    def test_normalize_ipv6_compressed(self):
        result = normalize_ip("2001:0db8:0000:0000:0000:0000:0000:0001")
        assert result == "2001:db8::1"

    def test_normalize_with_whitespace(self):
        result = normalize_ip("  192.168.1.1  ")
        assert result == "192.168.1.1"

    def test_invalid_ip_raises(self):
        with pytest.raises(ValueError):
            normalize_ip("invalid")
