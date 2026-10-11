"""Second-pass failure regressions: independent outputs and injected failures."""

import asyncio
import json
import os
import random
import shutil
import subprocess
import threading
import tracemalloc
import uuid
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yt_dlp
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

import engine
import web_server
from downloader import build_ydl_opts, get_parser
from engine import DownloadOptions, DownloadTask, EngineManager
from security import (
    BodyLimitMiddleware,
    SSRFValidationError,
    validate_and_sanitize_url,
    validate_timestamp_strict,
)


def task(**options):
    return DownloadTask(str(uuid.uuid4()), DownloadOptions(url="https://public.example", **options))


def test_explicit_cookie_path_never_borrows_or_deletes_legacy_cookies(monkeypatch, tmp_path):
    legacy = engine.COOKIES_FILE_PATH
    legacy.write_text("legacy account credentials")
    monkeypatch.setenv("STREAMFAB_COOKIES_FILE", str(tmp_path / "configured.txt"))
    assert engine.get_cookiefile_opt() is None
    assert not engine.delete_cookies_file()
    assert legacy.read_text() == "legacy account credentials"


def test_cookie_removal_cannot_repopulate_old_session_metadata():
    valid = "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tabc\n"
    engine.save_cookies_text(valid)

    @contextmanager
    def extraction(_, **kwargs):
        ydl = MagicMock()

        def extract(*args, **kwargs):
            engine.delete_cookies_file()
            return {"title": "Private account title", "formats": []}

        ydl.extract_info.side_effect = extract
        yield ydl

    with patch("engine.web_ydl", extraction):
        engine.extract_media_info("https://public.example/private")
    assert engine.get_cached_metadata("https://public.example/private") is None


def test_cancellation_wins_over_a_progress_hook_already_in_flight():
    download = task()

    @contextmanager
    def downloading(options, **kwargs):
        ydl = MagicMock()

        def run(_):
            hook = options["progress_hooks"][0]
            original = engine.shutil.disk_usage

            def cancel_during_check(path):
                download.cancel()
                return original(path)

            with patch("engine.shutil.disk_usage", side_effect=cancel_during_check):
                hook({"status": "downloading", "_percent_str": "20%"})
            assert download.to_dict()["status"] == "cancelled"
            return 0

        ydl.download.side_effect = run
        yield ydl

    with patch("engine.web_ydl", downloading):
        EngineManager()._execute_download_sync(download)
    assert download.progress.status == "cancelled"


def test_cancelled_proxy_open_releases_capacity_and_client():
    async def check():
        entered = asyncio.Event()
        client = MagicMock()
        client.aclose = AsyncMock()

        async def send(*args, **kwargs):
            entered.set()
            await asyncio.Event().wait()

        client.send = send
        request = Request({"type": "http", "headers": []})
        before = web_server._proxy_active
        with patch("web_server.public_async_client", return_value=client):
            opening = asyncio.create_task(
                web_server.proxy_stream("https://public.example", request)
            )
            await entered.wait()
            opening.cancel()
            with pytest.raises(asyncio.CancelledError):
                await opening
        assert web_server._proxy_active == before
        client.aclose.assert_awaited_once()

    asyncio.run(check())


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg tools not installed"
)
def test_mp3_trim_preserves_selected_bitrate_and_metadata():
    download = task(audio_quality="320k")
    media = download._output_dir / "tone.mp3"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=duration=2",
            "-b:a",
            "320k",
            "-metadata",
            "title=Bitrate fixture",
            str(media),
        ],
        check=True,
    )
    EngineManager()._trim_local_file(download, media, 0.25, 1.25)
    probe = json.loads(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=bit_rate:format_tags=title",
                "-of",
                "json",
                str(media),
            ]
        )
    )
    assert int(probe["streams"][0]["bit_rate"]) == 320000
    assert probe["format"]["tags"]["title"] == "Bitrate fixture"


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg tools not installed"
)
def test_trim_outside_duration_cannot_replace_the_original_with_empty_media():
    download = task(audio_format="wav")
    media = download._output_dir / "tone.wav"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=duration=0.5", str(media)],
        check=True,
    )
    original = media.read_bytes()
    with pytest.raises(ValueError, match="duration"):
        EngineManager()._trim_local_file(download, media, 1, 2)
    assert media.read_bytes() == original


def test_sse_subscribers_are_bounded_and_released():
    download = task()
    subscribers = [download.add_subscriber() for _ in range(32)]
    with pytest.raises(RuntimeError, match="capacity"):
        download.add_subscriber()
    download.remove_subscriber(subscribers[0])
    download.add_subscriber()
    assert len(download.subscribers) == 32


def test_anonymous_queued_task_cannot_acquire_later_installed_cookies():
    with TestClient(
        web_server.app, base_url="http://localhost", client=("10.0.0.2", 50000)
    ) as client:
        response = client.post("/api/download", json={"url": "https://public.example"})
    assert response.status_code == 200
    download = engine.engine.get_task(response.json()["task_id"])
    assert download.options.use_cookies is False
    engine.save_cookies_text(
        "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tabc\n"
    )
    with engine.web_ydl({"quiet": True}, use_cookies=download.options.use_cookies) as ydl:
        assert "cookiefile" not in ydl.params


def test_metadata_cache_keeps_anonymous_and_account_results_separate():
    engine.set_cached_metadata("https://public.example", {"title": "Private title"}, True)
    assert engine.get_cached_metadata("https://public.example", False) is None
    engine.set_cached_metadata("https://public.example", {"title": "Public title"}, False)
    assert engine.get_cached_metadata("https://public.example", True)["title"] == "Private title"
    assert engine.get_cached_metadata("https://public.example", False)["title"] == "Public title"


def test_progress_updates_and_cancellation_are_terminal_under_contention():
    for _ in range(30):
        download = task()
        start = threading.Barrier(3)

        def updates():
            start.wait()
            for percent in range(100):
                download.update_progress(status="downloading", percent=percent)

        def cancel():
            start.wait()
            download.cancel()

        worker = threading.Thread(target=updates)
        cancellation = threading.Thread(target=cancel)
        worker.start()
        cancellation.start()
        start.wait()
        worker.join(timeout=5)
        cancellation.join(timeout=5)
        assert not worker.is_alive() and not cancellation.is_alive()
        assert download.to_dict()["status"] == "cancelled"
        assert not download.update_progress(status="completed")


def test_proxy_constructor_failure_releases_capacity():
    async def check():
        before = web_server._proxy_active
        with patch("web_server.public_async_client", side_effect=RuntimeError("fixture failure")):
            with pytest.raises(HTTPException) as error:
                await web_server.proxy_stream(
                    "https://public.example", Request({"type": "http", "headers": []})
                )
        assert error.value.status_code == 502
        assert web_server._proxy_active == before

    asyncio.run(check())


@pytest.mark.parametrize("length", [str(2 * 1024**3 + 1), "9" * 5000, "-1", "not-a-size"])
def test_oversized_proxy_response_is_rejected_and_closed_before_streaming(length):
    async def check():
        before = web_server._proxy_active
        upstream = MagicMock(is_redirect=False)
        upstream.headers = {"content-type": "video/mp4", "content-length": length}
        upstream.aclose = AsyncMock()
        client = MagicMock()
        client.send = AsyncMock(return_value=upstream)
        client.aclose = AsyncMock()
        with patch("web_server.public_async_client", return_value=client):
            with pytest.raises(HTTPException) as error:
                await web_server.proxy_stream(
                    "https://public.example", Request({"type": "http", "headers": []})
                )
        assert error.value.status_code == 502
        assert web_server._proxy_active == before
        upstream.aclose.assert_awaited_once()
        client.aclose.assert_awaited_once()

    asyncio.run(check())


@pytest.mark.parametrize("container", ["mp4", "mkv"])
def test_cli_requested_container_applies_to_combined_streams(container):
    args = get_parser().parse_args(["https://public.example", "-f", container])
    options = build_ydl_opts(args)
    assert {"key": "FFmpegVideoRemuxer", "preferedformat": container} in options["postprocessors"]


def test_fragmented_request_body_memory_is_bounded_by_bytes_not_chunk_count():
    async def check():
        remaining = 50000

        async def receive():
            nonlocal remaining
            remaining -= 1
            return {
                "type": "http.request",
                "body": b"" if remaining else b"x",
                "more_body": remaining > 0,
            }

        async def app(scope, receive, send):
            body = bytearray()
            while True:
                received = await receive()
                body.extend(received.get("body", b""))
                if not received.get("more_body", False):
                    break
            assert body == b"x"

        tracemalloc.start()
        try:
            await BodyLimitMiddleware(app)({"type": "http", "method": "POST"}, receive, AsyncMock())
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        assert peak < 2 * 1024**2

    asyncio.run(check())


def test_timestamp_roundtrip_generated_against_independent_integer_arithmetic():
    rng = random.Random(78231)
    for _ in range(500):
        millis = rng.randrange(86400000)
        seconds, fraction = divmod(millis, 1000)
        minutes, second = divmod(seconds, 60)
        hour, minute = divmod(minutes, 60)
        timestamp = f"{hour:02}:{minute:02}:{second:02}.{fraction:03}"
        assert validate_timestamp_strict(timestamp) == millis / 1000


def test_empty_url_credentials_are_rejected_consistently():
    with pytest.raises(SSRFValidationError):
        validate_and_sanitize_url("https://@public.example/media")


def test_malformed_origin_is_rejected_without_server_error():
    with TestClient(
        web_server.app, base_url="http://localhost", client=("127.0.0.1", 50000)
    ) as client:
        assert client.get("/api/health", headers={"Origin": "https://["}).status_code == 403


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory mode contract")
def test_task_output_directory_is_private_to_the_owner():
    assert task()._output_dir.stat().st_mode & 0o077 == 0


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg tools not installed"
)
@pytest.mark.parametrize(
    "target,source_ext,format_name", [("mp4", "mkv", "mp4"), ("mkv", "mp4", "matroska")]
)
def test_cli_remux_produces_requested_container_with_real_combined_media(
    tmp_path, target, source_ext, format_name
):
    source = tmp_path / f"combined.{source_ext}"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=s=160x90:d=0.5",
            "-f",
            "lavfi",
            "-i",
            "sine=duration=0.5",
            "-c:v",
            "mpeg4",
            "-c:a",
            "aac",
            "-shortest",
            str(source),
        ],
        check=True,
    )
    options = build_ydl_opts(get_parser().parse_args(["https://public.example", "-f", target]))
    with yt_dlp.YoutubeDL(options) as ydl:
        processor = ydl._pps["post_process"][0]
        _, converted = processor.run({"filepath": str(source), "ext": source_ext})
    probe = json.loads(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=format_name",
                "-of",
                "json",
                converted["filepath"],
            ]
        )
    )
    assert format_name in probe["format"]["format_name"].split(",")
    assert converted["filepath"].endswith("." + target)
