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
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# Allowed URL schemes
ALLOWED_SCHEMES: set[str] = {"http", "https"}

# Strict regex for timestamp strings (e.g., "12", "01:30", "01:23:45", "12.345")
TIMESTAMP_REGEX = re.compile(r"^(?:(?:(\d{1,2}):)?(\d{1,2}):)?(\d{1,2})(?:\.(\d{1,3}))?$")

# Max allowable video duration in seconds (24 hours)
MAX_TIMESTAMP_SECONDS = 86400.0

# Banned domain fragments for SSRF
BANNED_HOST_KEYWORDS: tuple[str, ...] = (
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
    "metadata.google.internal",
    "instance-data",
)


# Banned ports for SSRF protection
BANNED_PORTS: set[int] = {21, 22, 23, 25, 53, 110, 143, 6379, 11211, 27017, 9200}


class SSRFValidationError(ValueError):
    """Raised when a URL targets a forbidden destination."""

    pass


def is_ip_private_or_reserved(ip_str: str) -> bool:
    """Check if an IP address belongs to private, loopback, or reserved blocks."""
    try:
        ip = ipaddress.ip_address(ip_str)
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        return not ip.is_global or ip.is_multicast
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
    if len(clean_url) > 8192 or any(c.isspace() for c in clean_url) or "\\" in clean_url:
        raise SSRFValidationError(
            "URL contains whitespace, a backslash, or exceeds the length limit."
        )

    # Parse URL
    try:
        parsed = urlparse(clean_url)
    except Exception as exc:
        raise SSRFValidationError("Invalid URL format.") from exc

    scheme = (parsed.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        raise SSRFValidationError(
            f"Scheme '{scheme}' not allowed. Only HTTP and HTTPS are permitted."
        )

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise SSRFValidationError("URL does not contain a valid hostname.")

    # Check for credentials in URL (user:pass@host)
    if parsed.username or parsed.password:
        raise SSRFValidationError("Credentials in URL are not allowed.")

    # Check port against dangerous service ports
    try:
        port = parsed.port
    except ValueError as exc:
        raise SSRFValidationError("Invalid URL port.") from exc
    if port is not None and port not in (80, 443):
        raise SSRFValidationError(f"Access to port {port} is blocked for security reasons.")

    # Check banned keywords
    for banned in BANNED_HOST_KEYWORDS:
        if hostname == banned or hostname.endswith("." + banned):
            raise SSRFValidationError(f"Access to host '{hostname}' is forbidden.")

    # Check common cloud metadata endpoints
    if hostname == "169.254.169.254" or hostname == "metadata.google.internal":
        raise SSRFValidationError("Attempt to access cloud metadata blocked.")

    # Check numeric or hex IP notation (e.g. 2130706433, 0x7f000001)
    try:
        if hostname.isdigit() or (
            hostname.startswith(("0x", "0X"))
            and all(c in "0123456789abcdefABCDEF" for c in hostname[2:])
        ):
            num = int(hostname, 16 if hostname.startswith("0x") else 10)
            if 0 <= num <= 0xFFFFFFFF:
                raw_ip = ipaddress.IPv4Address(num)
                if is_ip_private_or_reserved(str(raw_ip)):
                    raise SSRFValidationError(
                        f"Access denied: '{hostname}' targets a local or private IP address ({raw_ip})."
                    )
        else:
            raw_ip = ipaddress.ip_address(hostname.strip("[]"))
            if is_ip_private_or_reserved(str(raw_ip)):
                raise SSRFValidationError(
                    f"Access denied: '{hostname}' is a local or private IP address ({raw_ip})."
                )
    except SSRFValidationError:
        raise
    except (ValueError, OverflowError):
        pass

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
        if not addr_info:
            raise SSRFValidationError("Hostname resolved to no addresses.")
    except socket.gaierror as exc:
        raise SSRFValidationError("Unable to resolve the target hostname.") from exc

    return clean_url


def validate_timestamp_strict(raw: str | None) -> float | None:
    """Validate and convert timestamp to float seconds, preventing argument injection."""
    if not raw or not str(raw).strip():
        return None

    cleaned = str(raw).strip()
    if len(cleaned) > 15:
        raise ValueError("Timestamp format too long.")

    match = TIMESTAMP_REGEX.fullmatch(cleaned)
    if not match and not re.fullmatch(r"\d{1,5}(?:\.\d{1,3})?", cleaned):
        raise ValueError(f"Invalid time format: '{cleaned}'. Use HH:MM:SS or MM:SS format.")

    if ":" not in cleaned:
        total = float(cleaned)
        if total > MAX_TIMESTAMP_SECONDS:
            raise ValueError("Time cannot exceed 24 hours.")
        return total

    hours_str, mins_str, secs_str, millis_str = match.groups()
    hours = float(hours_str) if hours_str else 0.0
    mins = float(mins_str) if mins_str else 0.0
    secs = float(secs_str) if secs_str else 0.0
    millis = float(f"0.{millis_str}") if millis_str else 0.0
    if mins >= 60 or secs >= 60:
        raise ValueError("Minutes and seconds must be less than 60.")

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
    if max_length < 1:
        raise ValueError("Filename length must be positive.")
    if name.split(".", 1)[0].upper() in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }:
        name = "_" + name
    if len(name) > max_length:
        parts = name.rsplit(".", 1)
        if len(parts) == 2:
            base, ext = parts
            name = (
                base[: max_length - len(ext) - 1] + "." + ext
                if len(ext) + 1 < max_length
                else name[:max_length]
            )
        else:
            name = name[:max_length]

    return name


class RateLimiter:
    """Token-bucket / Sliding-window in-memory rate limiter per client IP."""

    def __init__(self, max_requests: int = 60, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests: dict[str, list[float]] = {}

    def is_allowed(self, client_ip: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window_seconds

        # Clean old timestamps for this client
        history = [t for t in self.requests.get(client_ip, []) if t > cutoff]
        if history:
            self.requests[client_ip] = history
        else:
            self.requests.pop(client_ip, None)
            history = []

        # Periodic memory prune if tracking large number of distinct IPs
        if len(self.requests) >= 1000:
            stale_ips = [
                ip
                for ip, timestamps in self.requests.items()
                if not any(t > cutoff for t in timestamps)
            ]
            for ip in stale_ips:
                self.requests.pop(ip, None)

        if (client_ip not in self.requests and len(self.requests) >= 1000) or len(
            history
        ) >= self.max_requests:
            return False

        self.requests[client_ip] = history + [now]
        return True

    def reset(self) -> None:
        """Reset all tracked rate limits."""
        self.requests.clear()


# Global rate limiters
api_rate_limiter = RateLimiter(max_requests=45, window_seconds=60)
download_rate_limiter = RateLimiter(max_requests=10, window_seconds=60)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Enforces strict HTTP Security Headers on all responses."""

    async def dispatch(self, request: Request, call_next) -> Response:
        # IP Extraction with reverse proxy support (e.g. Nginx, Docker)
        client_ip = request.client.host if request.client else "127.0.0.1"
        # Uvicorn performs proxy address handling only for explicitly trusted peers.

        # Apply Rate Limiting on API endpoints
        path = request.url.path
        if path.startswith("/api/") and request.headers.get("origin"):
            origin = urlparse(request.headers["origin"])
            if origin.netloc != request.headers.get("host") or origin.scheme != request.url.scheme:
                return JSONResponse(
                    status_code=403, content={"detail": "Cross-origin API access is forbidden."}
                )
        if path == "/api/download":
            if not download_rate_limiter.is_allowed(client_ip):
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many download requests. Please wait a minute."},
                )
        elif path.startswith("/api/") and path != "/api/health":
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
            "script-src 'self'; "
            "worker-src 'self' blob:; "
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


class BodyLimitMiddleware:
    """Bound JSON bodies before parsing, including chunked requests."""

    def __init__(self, app, max_bytes=3 * 1024 * 1024):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in ("POST", "PUT", "PATCH", "DELETE"):
            return await self.app(scope, receive, send)
        messages = []
        total = 0
        while True:
            message = await receive()
            messages.append(message)
            total += len(message.get("body", b""))
            if total > self.max_bytes:
                return await JSONResponse(
                    status_code=413, content={"detail": "Request body exceeds the size limit."}
                )(scope, receive, send)
            if not message.get("more_body", False):
                break

        async def replay():
            if messages:
                return messages.pop(0)
            return await receive()

        await self.app(scope, replay, send)
