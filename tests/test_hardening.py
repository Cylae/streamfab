"""Regression tests for audit findings, including real local FFmpeg trimming."""

import asyncio
import gzip
import json
import os
import shutil
import socket
import subprocess
import urllib.request
import uuid
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from yt_dlp.networking.exceptions import RequestError

import engine
import networking
import web_server
from engine import DownloadOptions, DownloadTask, EngineManager
from security import (
    RateLimiter,
    SSRFValidationError,
    sanitize_filename,
    validate_and_sanitize_url,
    validate_timestamp_strict,
)


def local_client(**kwargs):
    return TestClient(
        web_server.app, base_url="http://localhost", client=("127.0.0.1", 50000), **kwargs
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com:abc/x",
        "https://example.com:65536/x",
        "http://example.com:0/x",
        "http://example.com:8080/x",
        "http://100.64.0.1/x",
        "http://[::ffff:127.0.0.1]/",
        "http://user:@example.com/",
        "http://example.com/\\secret",
    ],
)
def test_bad_destinations(url):
    with pytest.raises(SSRFValidationError):
        validate_and_sanitize_url(url)


def test_dns_failure_is_closed():
    with patch("socket.getaddrinfo", side_effect=socket.gaierror()):
        with pytest.raises(SSRFValidationError):
            validate_and_sanitize_url("https://unresolvable.example/")


def test_connection_rebinding_blocks_before_socket_creation():
    with (
        patch(
            "socket.getaddrinfo",
            return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))],
        ),
        patch("networking.socket.socket") as sock,
    ):
        with pytest.raises(SSRFValidationError):
            networking.public_connection(("rebind.example", 443))
        sock.assert_not_called()


def test_connection_uses_exact_checked_address():
    with patch("networking.socket.socket") as sock:
        networking.public_connection(("public.example", 443), timeout=5)
        sock.return_value.connect.assert_called_once_with(("93.184.215.14", 443))


def test_mixed_public_private_dns_is_rejected():
    with patch(
        "socket.getaddrinfo",
        return_value=[(2, 1, 6, "", ("93.184.215.14", 443)), (2, 1, 6, "", ("10.0.0.1", 443))],
    ):
        with pytest.raises(SSRFValidationError):
            networking.public_addresses("mixed.example", 443)


def test_async_backend_connects_to_vetted_ip():
    async def check():
        with patch.object(
            networking.AnyIOBackend, "connect_tcp", new_callable=AsyncMock
        ) as connect:
            await networking.PublicAsyncBackend().connect_tcp("public.example", 443)
            assert connect.call_args.args[:2] == ("93.184.215.14", 443)

    asyncio.run(check())


def test_urllib_redirect_to_private_destination_rejected():
    handler = networking.PublicRedirectHandler()
    request = urllib.request.Request("https://public.example/media")
    with pytest.raises(SSRFValidationError):
        handler.redirect_request(request, None, 302, "Found", {}, "http://127.0.0.1/secret")


def test_ytdlp_guard_cannot_use_alternate_handlers():
    with networking.PublicYoutubeDL({"quiet": True, "proxy": ""}) as ydl:
        handlers = list(ydl._request_director.handlers.values())
        assert len(handlers) == 1
        assert isinstance(handlers[0], networking.PublicUrllibRH)
        for url in ("file:///etc/passwd", "ftp://public.example/media", "http://127.0.0.1/"):
            with pytest.raises(SSRFValidationError):
                ydl.urlopen(url)


def test_urllib_factory_preserves_cookie_and_guard_handlers():
    from http.cookiejar import CookieJar

    with networking.PublicUrllibRH(logger=MagicMock()) as handler:
        opener = handler._create_instance({}, CookieJar())
        assert any(isinstance(h, networking.PublicHTTPHandler) for h in opener.handlers)
        assert any(isinstance(h, networking.PublicRedirectHandler) for h in opener.handlers)


@pytest.mark.parametrize("text", ["01:60", "12:60:00", "00:00:60", "86400.001", "nan", "inf", "-1"])
def test_timestamp_limits(text):
    with pytest.raises(ValueError):
        validate_timestamp_strict(text)


def test_long_seconds_and_filename_extension():
    assert validate_timestamp_strict("3600.125") == 3600.125
    assert len(sanitize_filename("a." + "x" * 200, 20)) <= 20
    assert sanitize_filename("CON.mp4").startswith("_")


def test_rate_limiter_keeps_every_request_after_pruning():
    limiter = RateLimiter(2, 60)
    with patch("security.time.monotonic", side_effect=[0, 1, 2]):
        assert limiter.is_allowed("a")
        assert limiter.is_allowed("a")
        assert not limiter.is_allowed("a")


def test_cache_is_hard_bounded_and_returns_copies():
    for i in range(150):
        engine.set_cached_metadata(str(i), {"title": [i]})
    assert len(engine._METADATA_CACHE) == 100
    value = engine.get_cached_metadata("149")
    value["title"].append("mutated")
    assert engine.get_cached_metadata("149") == {"title": [149]}


def test_active_task_is_never_deleted():
    manager = EngineManager()
    task = manager.create_task(DownloadOptions(url="https://public.example"))
    task.created_at -= timedelta(hours=3)
    task.progress.status = "downloading"
    manager.cleanup_old_tasks()
    assert task._output_dir.exists()
    assert manager.get_task(task.task_id) is task


def test_cleanup_preserves_unrelated_folders():
    unrelated = engine.DOWNLOADS_DIR / "important-files"
    unrelated.mkdir()
    os.utime(unrelated, (0, 0))
    EngineManager().cleanup_old_tasks()
    assert unrelated.exists()


def test_task_directory_rejects_traversal():
    with pytest.raises(ValueError):
        DownloadTask("../outside", DownloadOptions(url="https://public.example"))


def test_worker_notifications_wake_sse_without_keepalive_delay():
    async def check():
        task = DownloadTask(str(uuid.uuid4()), DownloadOptions(url="https://public.example"))
        queue = task.add_subscriber()
        await queue.get()
        waiter = asyncio.create_task(queue.get())
        await asyncio.sleep(0)

        def update():
            task.progress.status = "completed"
            task.notify_subscribers()

        await asyncio.to_thread(update)
        assert (await asyncio.wait_for(waiter, 1))["status"] == "completed"
        task.remove_subscriber(queue)

    asyncio.run(check())


def test_subscriber_queue_coalesces_and_cancel_is_terminal():
    task = DownloadTask(str(uuid.uuid4()), DownloadOptions(url="https://public.example"))
    q = task.add_subscriber()
    for i in range(1000):
        task.progress.percent = i % 100
        task.notify_subscribers()
    assert q.qsize() == 1
    task.progress.status = "completed"
    task.cancel()
    assert task.progress.status == "completed"


@pytest.mark.parametrize(
    "payload",
    [
        {"media_type": "anything"},
        {"audio_format": "--exec"},
        {"video_format": "../../x"},
        {"playlist_indices": []},
        {"playlist_indices": [0]},
        {"playlist_indices": [True]},
        {"playlist_indices": ["1"]},
        {"playlist_indices": list(range(1, 252))},
        {"trim_end": "0"},
        {"url": ""},
    ],
)
def test_invalid_download_input_is_rejected_before_queue(payload):
    with local_client() as client:
        response = client.post(
            "/api/download", json={"url": "https://public.example/media", **payload}
        )
    assert response.status_code == 422
    assert not engine.engine.tasks


def test_private_url_rejected_before_creating_task():
    with local_client() as client:
        response = client.post("/api/download", json={"url": "http://127.0.0.1/secret"})
    assert response.status_code == 400
    assert not engine.engine.tasks


def test_cross_origin_and_host_rebinding_blocked():
    with local_client() as client:
        assert (
            client.post(
                "/api/cookies", headers={"Origin": "https://evil.example"}, json={"content": "x"}
            ).status_code
            == 403
        )
        assert client.get("/", headers={"Host": "evil.example"}).status_code == 400
        assert (
            "'unsafe-inline'"
            not in client.get("/")
            .headers["content-security-policy"]
            .split("script-src", 1)[1]
            .split(";", 1)[0]
        )


def test_cookie_auth_and_proxy_spoofing(monkeypatch):
    with TestClient(
        web_server.app, base_url="http://localhost", client=("10.0.0.2", 50000)
    ) as client:
        assert (
            client.get("/api/cookies", headers={"X-Forwarded-For": "127.0.0.1"}).status_code == 403
        )
        monkeypatch.setenv("STREAMFAB_ADMIN_TOKEN", "secret-token")
        assert client.get("/api/cookies").status_code == 403
        assert (
            client.get("/api/cookies", headers={"Authorization": "Bearer secret-token"}).status_code
            == 200
        )


def test_cookies_validate_atomically_and_count_httponly():
    valid = "# Netscape HTTP Cookie File\n#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tabc\n"
    assert engine.save_cookies_text(valid)["youtube_count"] == 1
    before = engine.cookie_write_path().read_bytes()
    with pytest.raises(ValueError):
        engine.save_cookies_text("not a cookie file")
    assert engine.cookie_write_path().read_bytes() == before
    if os.name != "nt":
        assert engine.cookie_write_path().stat().st_mode & 0o077 == 0


def test_remote_users_cannot_borrow_cookie_session():
    engine.save_cookies_text(
        "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tabc\n"
    )
    with TestClient(
        web_server.app, base_url="http://localhost", client=("10.0.0.2", 50000)
    ) as client:
        response = client.post("/api/info", json={"url": "https://public.example"})
    assert response.status_code == 403


def test_unfinished_files_are_not_served_and_restart_requires_marker():
    task_id = str(uuid.uuid4())
    task = DownloadTask(task_id, DownloadOptions(url="https://public.example"))
    media = task._output_dir / "partial.mp3"
    media.write_bytes(b"partial")
    task.progress.status = "converting"
    engine.engine.tasks[task_id] = task
    with local_client() as client:
        assert client.get(f"/api/file/{task_id}").status_code == 404
        engine.engine.tasks.pop(task_id)
        assert client.get(f"/api/file/{task_id}").status_code == 404
        (task._output_dir / "completed.json").write_text(json.dumps({"filename": media.name}))
        assert client.get(f"/api/file/{task_id}").content == b"partial"


def test_proxy_raw_encoded_bytes_and_cleanup():
    compressed = gzip.compress(b"raw")
    upstream = MagicMock(status_code=206, is_redirect=False)
    upstream.headers = {
        "content-type": "audio/mpeg",
        "content-encoding": "gzip",
        "content-length": str(len(compressed)),
        "content-range": "bytes 0-2/3",
    }

    async def raw(chunk_size=65536):
        yield compressed

    upstream.aiter_raw = raw
    upstream.aclose = AsyncMock()
    with patch("httpx.AsyncClient.send", return_value=upstream):
        with local_client() as client:
            response = client.get(
                "/api/proxy-stream",
                params={"url": "https://public.example/audio"},
                headers={"Range": "bytes=0-2"},
            )
    assert response.status_code == 206
    assert response.headers["content-length"] == str(len(compressed))
    assert response.content == b"raw"
    upstream.aclose.assert_awaited_once()
    assert web_server._proxy_active == 0


def test_proxy_html_cannot_execute_under_app_origin():
    upstream = MagicMock(status_code=200, is_redirect=False)
    upstream.headers = {"content-type": "text/html"}
    upstream.aclose = AsyncMock()
    with patch("httpx.AsyncClient.send", return_value=upstream):
        with local_client() as client:
            assert (
                client.get(
                    "/api/proxy-stream", params={"url": "https://public.example/xss"}
                ).status_code
                == 502
            )
    assert web_server._proxy_active == 0


def test_proxy_redirect_to_metadata_is_blocked():
    upstream = MagicMock(is_redirect=True)
    upstream.headers = {"location": "http://169.254.169.254/secret"}
    upstream.aclose = AsyncMock()
    with patch("httpx.AsyncClient.send", return_value=upstream) as send:
        with local_client() as client:
            assert (
                client.get(
                    "/api/proxy-stream", params={"url": "https://public.example/media"}
                ).status_code
                == 502
            )
        assert send.call_count == 1
    assert web_server._proxy_active == 0


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg tools not installed"
)
def test_actual_local_media_trim(tmp_path):
    task = DownloadTask(str(uuid.uuid4()), DownloadOptions(url="https://public.example"))
    media = task._output_dir / "tone.wav"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", str(media)],
        check=True,
    )
    EngineManager()._trim_local_file(task, media, 0.5, 1.25)
    result = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(media)]
    )
    assert float(json.loads(result)["format"]["duration"]) == pytest.approx(0.75, abs=0.03)


def test_chunked_request_body_is_bounded():
    with local_client() as client:
        response = client.post(
            "/api/cookies",
            content=iter([b"a" * (2 * 1024**2), b"b" * (2 * 1024**2)]),
            headers={"Content-Type": "application/json"},
        )
    assert response.status_code == 413


def test_real_guarded_transport_and_redirect():
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "http://127.0.0.1/secret")
                self.end_headers()
            else:
                self.send_response(200)
                self.send_header("Content-Length", "3")
                self.end_headers()
                self.wfile.write(b"abc")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # The test-only connector maps a vetted public endpoint to the synthetic
        # fixture server. Production public_addresses rejects loopback addresses.
        address = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", server.server_port))]
        with patch("networking.public_addresses", return_value=address):
            with networking.PublicYoutubeDL({"quiet": True, "proxy": ""}) as ydl:
                with ydl.urlopen("http://public.example/media") as response:
                    assert response.read() == b"abc"
                with pytest.raises((SSRFValidationError, RequestError)):
                    ydl.urlopen("http://public.example/redirect")
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_worker_keeps_cancellation_terminal(isolated_environment):
    manager = EngineManager()
    task = manager.create_task(DownloadOptions(url="https://public.example"))

    def fail_after_cancel(task):
        task.cancel()
        raise RuntimeError("cancelled in downloader")

    with patch.object(manager, "_execute_download_sync", side_effect=fail_after_cancel):
        asyncio.run(isolated_environment(manager, task))
    assert task.progress.status == "cancelled"
    assert task.progress.error_message is None
    assert not task._running


def test_worker_reports_sanitized_errors(isolated_environment):
    manager = EngineManager()
    task = manager.create_task(DownloadOptions(url="https://public.example"))
    with patch.object(
        manager, "_execute_download_sync", side_effect=RuntimeError("SECRET /etc/server/config")
    ):
        asyncio.run(isolated_environment(manager, task))
    assert task.progress.status == "error"
    assert "SECRET" not in task.progress.error_message
    assert not task._running


def test_queued_cancel_never_downloads(isolated_environment):
    manager = EngineManager()
    task = manager.create_task(DownloadOptions(url="https://public.example"))
    task.cancel()
    with patch.object(manager, "_execute_download_sync") as download:
        asyncio.run(isolated_environment(manager, task))
        download.assert_not_called()


def test_download_admission_is_bounded(monkeypatch):
    monkeypatch.setattr(engine, "MAX_TASKS", 1)
    manager = EngineManager()
    manager.create_task(DownloadOptions(url="https://public.example"))
    with pytest.raises(RuntimeError, match="capacity"):
        manager.create_task(DownloadOptions(url="https://public.example"))


def test_extraction_capacity_returns_503(monkeypatch):
    monkeypatch.setattr(web_server, "_extraction_active", 4)
    with local_client() as client:
        assert client.post("/api/info", json={"url": "https://public.example"}).status_code == 503


def test_rate_limiter_full_map_expires():
    limiter = RateLimiter()
    limiter.requests = {str(i): [0] for i in range(1000)}
    with patch("security.time.monotonic", return_value=61):
        assert limiter.is_allowed("new")
    assert len(limiter.requests) == 1


def test_cookie_snapshot_never_updates_the_original():
    valid = "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tabc\n"
    engine.save_cookies_text(valid)
    original = engine.cookie_write_path().read_bytes()
    with engine.web_ydl({"quiet": True}) as ydl:
        snapshot = Path(ydl.params["cookiefile"])
        assert snapshot != engine.cookie_write_path()
        assert snapshot.is_file()
    assert not snapshot.exists()
    assert engine.cookie_write_path().read_bytes() == original


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg tools not installed"
)
def test_actual_local_video_trim():
    task = DownloadTask(str(uuid.uuid4()), DownloadOptions(url="https://public.example"))
    media = task._output_dir / "synthetic.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=160x90:r=25:d=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-c:v",
            "mpeg4",
            "-c:a",
            "aac",
            "-metadata",
            "title=Synthetic",
            "-shortest",
            str(media),
        ],
        check=True,
    )
    EngineManager()._trim_local_file(task, media, 0.5, 1.25)
    result = json.loads(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration:format_tags=title",
                "-of",
                "json",
                str(media),
            ]
        )
    )
    assert float(result["format"]["duration"]) == pytest.approx(0.75, abs=0.08)
    assert result["format"]["tags"]["title"] == "Synthetic"
