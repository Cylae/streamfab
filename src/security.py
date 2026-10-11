"""StreamFab Security Module.

Provides comprehensive defenses against:
- SSRF (Server-Side Request Forgery) and local/private network probing
- Path traversal and arbitrary file read/write
- Command injection and argument injection
- HTTP Response Splitting and Header Injection
- Denial of Service (DoS) via rate limiting and concurrency throttling
- Information disclosure
"""

from __future__ import annotations

import ipaddress
import re
import socket
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


# Allowed URL schemes
ALLOWED_SCHEMES: Set[str] = {"http", "https"}

# Strict regex for timestamp strings (e.g., "12", "01:30", "01:23:45", "12.345")
TIMESTAMP_REGEX = re.compile(r"^(?:(?:(\d{1,2}):)?(\d{1,2}):)?(\d{1,2})(?:\.(\d{1,3}))?$")

# Max allowable video duration in seconds (24 hours)
MAX_TIMESTAMP_SECONDS = 86400.0

# Banned domain fragments for SSRF
BANNED_HOST_KEYWORDS: Tuple[str, ...] = (
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
    "metadata.google.internal",
    "instance-data",
)


class SSRFValidationError(ValueError):
    """Raised when a URL targets a forbidden destination."""
    pass


def is_ip_private_or_reserved(ip_str: str) -> bool:
    """Check if an IP address belongs to private, loopback, or reserved blocks."""
    try:
        ip = ipaddress.ip_address(ip_str)
        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        )
    except ValueError:
        return True


def validate_and_sanitize_url(url: str) -> str:
    """Validate that a URL is safe to fetch and does not target internal assets.

    Guards against SSRF, cloud metadata exfiltration, loopback, and local network scans.
    """
    clean_url = url.strip()
    if not clean_url:
        raise SSRFValidationError("URL cannot be empty.")

    # Prevent control characters or null bytes
    if any(ord(c) < 32 or ord(c) == 127 for c in clean_url):
        raise SSRFValidationError("URL contains invalid control characters.")

    # Parse URL
    try:
        parsed = urlparse(clean_url)
    except Exception as exc:
        raise SSRFValidationError("Invalid URL format.") from exc

    scheme = (parsed.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        raise SSRFValidationError(f"Scheme '{scheme}' not allowed. Only HTTP and HTTPS are permitted.")

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise SSRFValidationError("URL does not contain a valid hostname.")

    # Check for credentials in URL (user:pass@host)
    if parsed.username or parsed.password:
        raise SSRFValidationError("Credentials in URL are not allowed.")

    # Check banned keywords
    for banned in BANNED_HOST_KEYWORDS:
        if hostname == banned or hostname.endswith("." + banned):
            raise SSRFValidationError(f"Access to host '{hostname}' is forbidden.")

    # Check common cloud metadata endpoints
    if hostname == "169.254.169.254" or hostname == "metadata.google.internal":
        raise SSRFValidationError("Attempt to access cloud metadata blocked.")

    # Resolve domain to check target IP addresses
    try:
        # Resolve IPv4 / IPv6 addresses
        addr_info = socket.getaddrinfo(hostname, None)
        for _, _, _, _, sockaddr in addr_info:
            ip_addr = sockaddr[0]
            if is_ip_private_or_reserved(ip_addr):
                raise SSRFValidationError(
                    f"Access denied: '{hostname}' resolves to a local or private IP address ({ip_addr})."
                )
    except socket.gaierror:
        # DNS resolution failure will be handled by the downloader, but domain itself is not private IP
        pass

    return clean_url


def validate_timestamp_strict(raw: Optional[str]) -> Optional[float]:
    """Validate and convert timestamp to float seconds, preventing argument injection."""
    if not raw or not str(raw).strip():
        return None

    cleaned = str(raw).strip()
    if len(cleaned) > 15:
        raise ValueError("Timestamp format too long.")

    match = TIMESTAMP_REGEX.match(cleaned)
    if not match:
        raise ValueError(f"Invalid time format: '{cleaned}'. Use HH:MM:SS or MM:SS format.")

    hours_str, mins_str, secs_str, millis_str = match.groups()
    hours = float(hours_str) if hours_str else 0.0
    mins = float(mins_str) if mins_str else 0.0
    secs = float(secs_str) if secs_str else 0.0
    millis = float(f"0.{millis_str}") if millis_str else 0.0

    total_seconds = hours * 3600.0 + mins * 60.0 + secs + millis
    if total_seconds < 0:
        raise ValueError("Time cannot be negative.")
    if total_seconds > MAX_TIMESTAMP_SECONDS:
        raise ValueError("Time cannot exceed 24 hours.")

    return round(total_seconds, 3)


def sanitize_filename(filename: str, max_length: int = 120) -> str:
    """Sanitize filename to prevent HTTP Header Injection, path traversal, and special char abuse."""
    if not filename:
        return "download.bin"

    # Remove path traversal tokens and directory separators
    name = re.sub(r"[/\\]+", "", filename)

    # Strip HTTP header injection characters (CR, LF, null)
    name = re.sub(r"[\r\n\x00-\x1f\x7f]", "", name)

    # Replace unsafe characters for filenames and Content-Disposition
    name = re.sub(r'["\';*?<>|:]', "_", name)

    # Strip leading/trailing dots or spaces
    name = name.strip(". ")

    if not name:
        name = "media_download"

    # Limit length preserving extension
    if len(name) > max_length:
        parts = name.rsplit(".", 1)
        if len(parts) == 2:
            base, ext = parts
            name = base[: max_length - len(ext) - 1] + "." + ext
        else:
            name = name[:max_length]

    return name


class RateLimiter:
    """Token-bucket / Sliding-window in-memory rate limiter per client IP."""

    def __init__(self, max_requests: int = 60, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests: Dict[str, List[float]] = defaultdict(list)

    def is_allowed(self, client_ip: str) -> bool:
        now = time.time()
        cutoff = now - self.window_seconds

        # Clean old timestamps
        history = [t for t in self.requests[client_ip] if t > cutoff]
        self.requests[client_ip] = history

        if len(history) >= self.max_requests:
            return False

        self.requests[client_ip].append(now)
        return True


# Global rate limiters
api_rate_limiter = RateLimiter(max_requests=45, window_seconds=60)
download_rate_limiter = RateLimiter(max_requests=10, window_seconds=60)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Enforces strict HTTP Security Headers on all responses."""

    async def dispatch(self, request: Request, call_next) -> Response:
        # IP Extraction
        client_ip = request.client.host if request.client else "127.0.0.1"

        # Apply Rate Limiting on API endpoints
        path = request.url.path
        if path.startswith("/api/download"):
            if not download_rate_limiter.is_allowed(client_ip):
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many download requests. Please wait a minute."},
                )
        elif path.startswith("/api/"):
            if not api_rate_limiter.is_allowed(client_ip):
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded. Please slow down."},
                )

        response = await call_next(request)

        # Security Headers
        headers = response.headers
        headers["X-Content-Type-Options"] = "nosniff"
        headers["X-Frame-Options"] = "DENY"
        headers["X-XSS-Protection"] = "1; mode=block"
        headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
        headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https: http:; "
            "media-src 'self' data: https: http: blob:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "object-src 'none'; "
            "base-uri 'self';"
        )

        return response
