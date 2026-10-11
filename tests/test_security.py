import os
import sys
import time
import pytest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from security import (
    SSRFValidationError,
    is_ip_private_or_reserved,
    validate_and_sanitize_url,
    validate_timestamp_strict,
    sanitize_filename,
    RateLimiter,
)


class TestURLValidationAndSSRF:
    def test_empty_url(self):
        with pytest.raises(SSRFValidationError, match="cannot be empty"):
            validate_and_sanitize_url("")
        with pytest.raises(SSRFValidationError, match="cannot be empty"):
            validate_and_sanitize_url("   ")

    def test_control_characters(self):
        with pytest.raises(SSRFValidationError, match="control characters"):
            validate_and_sanitize_url("https://example.com/test\x00path")
        with pytest.raises(SSRFValidationError, match="control characters"):
            validate_and_sanitize_url("https://example.com/\r\ntest")

    def test_forbidden_schemes(self):
        for bad_url in [
            "ftp://files.example.com",
            "file:///etc/passwd",
            "gopher://example.com",
            "javascript:alert(1)",
            "data:text/html,test",
        ]:
            with pytest.raises(SSRFValidationError, match="Scheme .* not allowed"):
                validate_and_sanitize_url(bad_url)

    def test_missing_hostname(self):
        with pytest.raises(SSRFValidationError, match="valid hostname"):
            validate_and_sanitize_url("http://")
        with pytest.raises(SSRFValidationError, match="valid hostname"):
            validate_and_sanitize_url("https:///path")

    def test_credentials_in_url(self):
        with pytest.raises(SSRFValidationError, match="Credentials in URL"):
            validate_and_sanitize_url("https://admin:secret@example.com/video")

    def test_banned_hostnames_and_metadata(self):
        for banned_url in [
            "http://localhost:8080/secret",
            "http://sub.localhost/api",
            "http://127.0.0.1:8000/info",
            "http://0.0.0.0/path",
            "http://[::1]/test",
            "http://169.254.169.254/latest/meta-data/",
            "http://metadata.google.internal/computeMetadata/v1/",
            "http://instance-data/latest/",
        ]:
            with pytest.raises(SSRFValidationError):
                validate_and_sanitize_url(banned_url)

    @patch("socket.getaddrinfo")
    def test_private_ip_resolution(self, mock_addrinfo):
        mock_addrinfo.return_value = [
            (2, 1, 6, "", ("192.168.1.100", 80)),
        ]
        with pytest.raises(SSRFValidationError, match="local or private IP"):
            validate_and_sanitize_url("https://internal-service.local/media")

    @patch("socket.getaddrinfo")
    def test_loopback_ip_resolution(self, mock_addrinfo):
        mock_addrinfo.return_value = [
            (2, 1, 6, "", ("127.0.0.5", 80)),
        ]
        with pytest.raises(SSRFValidationError, match="local or private IP"):
            validate_and_sanitize_url("https://sneaky-domain.com/video")

    def test_valid_public_urls(self):
        valid = [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ",
            "https://www.tiktok.com/@user/video/123456789",
            "http://example.com/media.mp4",
        ]
        for u in valid:
            assert validate_and_sanitize_url(u) == u


class TestTimestampValidation:
    def test_none_or_empty(self):
        assert validate_timestamp_strict(None) is None
        assert validate_timestamp_strict("") is None
        assert validate_timestamp_strict("   ") is None

    def test_too_long(self):
        with pytest.raises(ValueError, match="too long"):
            validate_timestamp_strict("00:00:00:00:00:00:00:00")

    def test_invalid_syntax(self):
        for bad in ["abc", "12:34:56:78", "00:-1:20", "12:60:00a"]:
            with pytest.raises(ValueError, match="Invalid time format"):
                validate_timestamp_strict(bad)

    def test_exceeding_max_duration(self):
        # > 24 hours (86400s)
        with pytest.raises(ValueError, match="cannot exceed 24 hours"):
            validate_timestamp_strict("25:00:00")

    def test_valid_timestamps(self):
        assert validate_timestamp_strict("45") == 45.0
        assert validate_timestamp_strict("01:30") == 90.0
        assert validate_timestamp_strict("01:02:03") == 3723.0
        assert validate_timestamp_strict("12.5") == 12.5


class TestFilenameSanitization:
    def test_empty_or_none(self):
        assert sanitize_filename("") == "download.bin"
        assert sanitize_filename(None) == "download.bin"

    def test_path_traversal_removal(self):
        res = sanitize_filename("../../../etc/passwd")
        assert "/" not in res
        assert "\\" not in res
        assert res == "etcpasswd"

    def test_header_injection_stripping(self):
        res = sanitize_filename("video\r\nSet-Cookie:evil=1.mp4")
        assert "\r" not in res
        assert "\n" not in res
        assert res == "videoSet-Cookie_evil=1.mp4"

    def test_special_characters_replaced(self):
        res = sanitize_filename('Song "Title": The Best?.mp3')
        assert '"' not in res
        assert ':' not in res
        assert '?' not in res
        assert res == "Song _Title__ The Best_.mp3"

    def test_overly_long_filename_truncation(self):
        long_base = "a" * 200
        res = sanitize_filename(f"{long_base}.mp4", max_length=50)
        assert len(res) <= 50
        assert res.endswith(".mp4")


class TestRateLimiter:
    def test_sliding_window_rate_limiter(self):
        limiter = RateLimiter(max_requests=3, window_seconds=1)
        ip = "192.0.2.1"

        assert limiter.is_allowed(ip) is True
        assert limiter.is_allowed(ip) is True
        assert limiter.is_allowed(ip) is True
        # 4th request within 1 second window should be denied
        assert limiter.is_allowed(ip) is False

        # After window expires, requests should be allowed again
        time.sleep(1.1)
        assert limiter.is_allowed(ip) is True
