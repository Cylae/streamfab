"""Public-network-only transports; validate the addresses actually connected to.

The yt-dlp adapter deliberately uses its urllib handler exclusively. Updating
yt-dlp must include running the transport tests because this adapter uses its
internal handler API. Proxy environment variables are deliberately ignored.
"""

import functools
import http.client
import socket
import urllib.request

import httpcore
import httpx
import yt_dlp
from httpcore._backends.anyio import AnyIOBackend
from yt_dlp.networking._urllib import HTTPHandler, RedirectHandler, UrllibRH

from security import SSRFValidationError, is_ip_private_or_reserved, validate_and_sanitize_url


def public_addresses(host: str, port: int):
    if port not in (80, 443):
        raise SSRFValidationError("Only public HTTP/HTTPS ports are allowed.")
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not addresses or any(is_ip_private_or_reserved(item[4][0]) for item in addresses):
        raise SSRFValidationError("SSRF blocked: local or private IP destination.")
    return addresses


def public_connection(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None):
    """Resolve once, check all answers, then connect to the checked sockaddr."""
    addresses = public_addresses(*address)
    last_error = None
    for family, kind, proto, _, sockaddr in addresses:
        sock = socket.socket(family, kind, proto)
        try:
            if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            sock.connect(sockaddr)
            return sock
        except OSError as exc:
            last_error = exc
            sock.close()
    raise last_error or OSError("No public destination available.")


class PublicHTTPHandler(HTTPHandler):
    def http_request(self, req):
        validate_and_sanitize_url(req.full_url)
        return super().http_request(req)

    https_request = http_request

    def _connection(self, connection_class, *args, **kwargs):
        conn = connection_class(*args, **kwargs)
        conn._create_connection = public_connection
        return conn

    def http_open(self, req):
        return self.do_open(functools.partial(self._connection, http.client.HTTPConnection), req)

    def https_open(self, req):
        return self.do_open(
            functools.partial(self._connection, http.client.HTTPSConnection),
            req,
            context=self._context,
        )


class PublicRedirectHandler(RedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_and_sanitize_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class PublicUrllibRH(UrllibRH):
    def _create_instance(self, proxies, cookiejar, legacy_ssl_support=None):
        original = super()._create_instance({}, cookiejar, legacy_ssl_support)
        opener = urllib.request.OpenerDirector()
        for handler in original.handlers:
            if isinstance(handler, HTTPHandler):
                handler = PublicHTTPHandler(
                    context=self._make_sslcontext(legacy_ssl_support=legacy_ssl_support)
                )
            elif isinstance(handler, RedirectHandler):
                handler = PublicRedirectHandler()
            opener.add_handler(handler)
        opener.addheaders = []
        return opener


class PublicYoutubeDL(yt_dlp.YoutubeDL):
    def urlopen(self, req):
        url = req if isinstance(req, str) else getattr(req, "url", getattr(req, "full_url", ""))
        validate_and_sanitize_url(url)
        return super().urlopen(req)

    @functools.cached_property
    def _request_director(self):
        return self.build_request_director([PublicUrllibRH], [])

    def process_info(self, info_dict):
        # External FFmpeg downloaders have independent network stacks. Never
        # dispatch them from the web engine; trimming runs on local files.
        from yt_dlp.downloader import get_suitable_downloader

        selected = info_dict.get("requested_formats") or [info_dict]
        for info in selected:
            validate_and_sanitize_url(info.get("url", ""))
            downloader = get_suitable_downloader(info, self.params)
            if downloader and downloader.__name__ in ("FFmpegFD", "RtmpFD", "RtspFD"):
                raise SSRFValidationError(
                    "External network downloaders are disabled in the web engine."
                )
        return super().process_info(info_dict)


class PublicAsyncBackend(AnyIOBackend):
    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        import asyncio

        addresses = await asyncio.to_thread(public_addresses, host, port)
        last_error = None
        for item in addresses:
            try:
                # TLS remains keyed to the original hostname by httpcore.
                return await super().connect_tcp(
                    item[4][0], port, timeout, local_address, socket_options
                )
            except (OSError, httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_error = exc
        raise last_error or httpcore.ConnectError("No public destination available.")


def public_async_client() -> httpx.AsyncClient:
    transport = httpx.AsyncHTTPTransport(retries=0, trust_env=False)
    transport._pool = httpcore.AsyncConnectionPool(network_backend=PublicAsyncBackend())
    return httpx.AsyncClient(
        transport=transport, timeout=60, follow_redirects=False, trust_env=False
    )
