import os
import sys
import time
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from engine import (
    _METADATA_CACHE,
    DownloadOptions,
    DownloadTask,
    EngineManager,
    classify_engine_error,
    extract_media_info,
    format_duration,
    get_cached_metadata,
    parse_timestamp,
    set_cached_metadata,
)


def test_format_duration():
    assert format_duration(None) == "00:00"
    assert format_duration(-5) == "00:00"
    assert format_duration(0) == "00:00"
    assert format_duration(45) == "00:45"
    assert format_duration(65) == "01:05"
    assert format_duration(3600) == "01:00:00"
    assert format_duration(3665) == "01:01:05"


def test_parse_timestamp():
    assert parse_timestamp(None) is None
    assert parse_timestamp("") is None
    assert parse_timestamp("  ") is None
    assert parse_timestamp("45") == 45.0
    assert parse_timestamp("01:30") == 90.0
    assert parse_timestamp("01:02:03") == 3723.0
    assert parse_timestamp("-10") == 0.0
    assert parse_timestamp("invalid") is None


def test_classify_engine_error():
    assert "DRM" in classify_engine_error(Exception("This video is protected content with DRM"))
    assert "not supported" in classify_engine_error(Exception("unsupported url"))
    assert "403" in classify_engine_error(Exception("HTTP Error 403: Forbidden"))
    assert "404" in classify_engine_error(Exception("HTTP Error 404: Not Found"))
    assert "private" in classify_engine_error(Exception("This is a private video. Sign in to view"))
    assert "geographical" in classify_engine_error(
        Exception("Video not available in your country due to geo block")
    )
    assert "timed out" in classify_engine_error(Exception("Connection timed out"))
    assert "Random error" not in classify_engine_error(Exception("Random error"))


def test_metadata_cache():
    url = "https://example.com/cached_test"
    set_cached_metadata(url, {"title": "Cached Video"})
    cached = get_cached_metadata(url)
    assert cached is not None
    assert cached["title"] == "Cached Video"

    # Test expiration
    with patch("engine.time.monotonic", return_value=time.monotonic() + 400):
        assert get_cached_metadata(url) is None


@patch("engine.PublicYoutubeDL")
def test_extract_media_info_single_video(mock_ydl_class):
    mock_instance = mock_ydl_class.return_value.__enter__.return_value
    mock_instance.extract_info.return_value = {
        "id": "vid123",
        "title": "Super Cool Song",
        "uploader": "Artist Name",
        "duration": 215,
        "view_count": 500000,
        "thumbnail": "https://img.youtube.com/vi/vid123/maxresdefault.jpg",
        "formats": [
            {
                "format_id": "18",
                "vcodec": "avc1",
                "acodec": "mp4a",
                "height": 360,
                "url": "https://stream.mp4",
            },
            {
                "format_id": "22",
                "vcodec": "avc1",
                "acodec": "mp4a",
                "height": 720,
                "url": "https://stream720.mp4",
            },
            {"format_id": "137", "vcodec": "avc1", "acodec": "none", "height": 1080},
            {"format_id": "140", "vcodec": "none", "acodec": "mp4a"},
        ],
        "subtitles": {"fr": [{"ext": "vtt"}]},
        "automatic_captions": {"en": [{"ext": "vtt"}]},
    }

    info = extract_media_info("https://example.com/single_test")
    assert info["id"] == "vid123"
    assert info["title"] == "Super Cool Song"
    assert info["uploader"] == "Artist Name"
    assert info["duration_formatted"] == "03:35"
    assert info["is_playlist"] is False
    assert len(info["available_video_resolutions"]) >= 2
    assert any(r["value"] == "1080p" for r in info["available_video_resolutions"])
    assert any(r["value"] == "720p" for r in info["available_video_resolutions"])
    assert len(info["subtitles"]) >= 1


@patch("engine.PublicYoutubeDL")
def test_extract_media_info_playlist(mock_ydl_class):
    mock_instance = mock_ydl_class.return_value.__enter__.return_value
    mock_instance.extract_info.return_value = {
        "_type": "playlist",
        "id": "pl123",
        "title": "My Awesome Album",
        "uploader": "The Band",
        "entries": [
            {"id": "t1", "title": "Track 1", "duration": 180, "thumbnail": "https://thumb1.jpg"},
            {"id": "t2", "title": "Track 2", "duration": 210, "thumbnail": "https://thumb2.jpg"},
        ],
    }

    info = extract_media_info("https://example.com/playlist_test")
    assert info["is_playlist"] is True
    assert info["playlist_count"] == 2
    assert info["playlist_entries"][0]["title"] == "Track 1"
    assert info["playlist_entries"][1]["duration_formatted"] == "03:30"


def test_download_task_lifecycle():
    opts = DownloadOptions(url="https://example.com/test", media_type="audio", audio_format="mp3")
    task = DownloadTask("6cc83701-6028-4f59-ad33-163c5a137edd", opts)
    assert task.progress.status == "queued"
    assert task.to_dict()["status"] == "queued"

    # Subscriber test
    queue = task.add_subscriber()
    initial_event = queue.get_nowait()
    assert initial_event["task_id"] == "6cc83701-6028-4f59-ad33-163c5a137edd"

    # Cancel test
    task.cancel()
    assert task.progress.status == "cancelled"
    cancel_event = queue.get_nowait()
    assert cancel_event["status"] == "cancelled"
    task.remove_subscriber(queue)


def test_engine_manager():
    mgr = EngineManager()
    opts = DownloadOptions(url="https://example.com/test")
    task = mgr.create_task(opts)
    assert task.task_id in mgr.tasks
    assert mgr.get_task(task.task_id) == task
    assert mgr.get_task("nonexistent") is None


@patch("engine.PublicYoutubeDL")
def test_execute_download_sync_audio_success(mock_ydl_class):
    mgr = EngineManager()
    opts = DownloadOptions(
        url="https://example.com/audio",
        media_type="audio",
        audio_format="mp3",
        audio_quality="320k",
        embed_metadata=True,
    )
    task = mgr.create_task(opts)

    # Mock yt_dlp download and output file creation
    mock_instance = mock_ydl_class.return_value.__enter__.return_value
    mock_instance.download.return_value = 0

    def fake_download(urls):
        # Trigger progress hooks to verify reporting
        opts_passed = mock_ydl_class.call_args[0][0]
        for hook in opts_passed.get("progress_hooks", []):
            hook(
                {
                    "status": "downloading",
                    "_percent_str": "50.0%",
                    "_speed_str": "10MiB/s",
                    "_eta_str": "00:05",
                    "downloaded_bytes": 500,
                    "total_bytes": 1000,
                }
            )
            hook({"status": "finished"})
        # Create output file
        dummy_out = task._output_dir / "Super_Song.mp3"
        dummy_out.write_bytes(b"dummy mp3 data")
        return 0

    mock_instance.download.side_effect = fake_download

    mgr._execute_download_sync(task)
    assert task.progress.status == "completed"
    assert task.progress.percent == 100.0
    assert task.progress.filename == "Super_Song.mp3"
    assert task.progress.file_size == len(b"dummy mp3 data")


@patch("engine.PublicYoutubeDL")
@patch("engine.EngineManager._trim_local_file")
def test_execute_download_sync_video_and_trim(mock_trim, mock_ydl_class):
    mgr = EngineManager()
    opts = DownloadOptions(
        url="https://example.com/video",
        media_type="video",
        video_format="mp4",
        video_quality="1080p",
        trim_start="00:00:10",
        trim_end="00:00:45",
        subtitle_lang="fr",
    )
    task = mgr.create_task(opts)

    mock_instance = mock_ydl_class.return_value.__enter__.return_value

    def fake_download(urls):
        opts_passed = mock_ydl_class.call_args[0][0]
        assert "download_ranges" not in opts_passed
        assert opts_passed["writesubtitles"] is True
        dummy_out = task._output_dir / "Clipped_Video.mp4"
        dummy_out.write_bytes(b"dummy mp4 data")
        return 0

    mock_instance.download.side_effect = fake_download
    mgr._execute_download_sync(task)
    assert task.progress.status == "completed"
    assert task.progress.filename == "Clipped_Video.mp4"


@patch("engine.PublicYoutubeDL")
def test_execute_download_sync_cancellation(mock_ydl_class):
    mgr = EngineManager()
    opts = DownloadOptions(url="https://example.com/video")
    task = mgr.create_task(opts)

    mock_instance = mock_ydl_class.return_value.__enter__.return_value

    def fake_download(urls):
        opts_passed = mock_ydl_class.call_args[0][0]
        # Simulate cancellation triggered from outside
        task._cancel_requested = True
        for hook in opts_passed.get("progress_hooks", []):
            hook({"status": "downloading"})
        return 0

    mock_instance.download.side_effect = fake_download
    with pytest.raises(Exception, match="Download cancelled"):
        mgr._execute_download_sync(task)


@patch("engine.PublicYoutubeDL")
def test_execute_download_sync_failure_code(mock_ydl_class):
    mgr = EngineManager()
    opts = DownloadOptions(url="https://example.com/video")
    task = mgr.create_task(opts)

    mock_instance = mock_ydl_class.return_value.__enter__.return_value
    mock_instance.download.return_value = 1  # failure code

    with pytest.raises(RuntimeError, match="yt-dlp exit code: 1"):
        mgr._execute_download_sync(task)


@patch("engine.PublicYoutubeDL")
def test_windows_options_in_ydl_opts(mock_ydl_class):
    mgr = EngineManager()
    opts = DownloadOptions(url="https://example.com/video")
    task = mgr.create_task(opts)

    mock_instance = mock_ydl_class.return_value.__enter__.return_value

    def fake_download(urls):
        opts_passed = mock_ydl_class.call_args[0][0]
        assert opts_passed.get("windowsfilenames") is True
        assert opts_passed.get("paths", {}).get("home") == str(task._output_dir)
        assert "[%(id)s]" in str(opts_passed.get("outtmpl"))
        dummy_out = task._output_dir / "Video.mp4"
        dummy_out.write_bytes(b"content")
        return 0

    mock_instance.download.side_effect = fake_download
    mgr._execute_download_sync(task)
    assert task.progress.status == "completed"


def test_sanitize_filename_windows_illegal_characters():
    from security import sanitize_filename

    # Colons, quotes, question marks, pipes, trailing dots and spaces
    bad_name = 'My: Cool "Video"? | Awesome.. '
    cleaned = sanitize_filename(bad_name)
    assert ":" not in cleaned
    assert '"' not in cleaned
    assert "?" not in cleaned
    assert "|" not in cleaned
    assert not cleaned.endswith(".")
    assert not cleaned.endswith(" ")


def test_cleanup_old_tasks():
    from datetime import datetime, timedelta, timezone

    mgr = EngineManager()
    opts = DownloadOptions(url="https://example.com/test")
    task = mgr.create_task(opts)
    # Manually backdate created_at to 2 hours ago
    task.created_at = datetime.now(timezone.utc) - timedelta(hours=2)
    assert task.task_id in mgr.tasks
    assert task._output_dir.exists()

    task.progress.status = "completed"
    mgr.cleanup_old_tasks()
    assert task.task_id not in mgr.tasks
    assert not task._output_dir.exists()


def test_multiple_subscribers():
    opts = DownloadOptions(url="https://example.com/test")
    task = DownloadTask("a2b67097-2a7c-4f2a-a3c5-fde2885f7cb3", opts)
    q1 = task.add_subscriber()
    q2 = task.add_subscriber()

    assert len(task.subscribers) == 2
    # Both received initial dict
    assert not q1.empty()
    assert not q2.empty()

    task.remove_subscriber(q1)
    assert len(task.subscribers) == 1
    assert q1 not in task.subscribers
    assert q2 in task.subscribers


@patch("engine.shutil.disk_usage")
def test_disk_usage_insufficient_space(mock_disk):
    mock_disk.return_value.free = 50 * 1024 * 1024  # 50 MB
    mgr = EngineManager()
    opts = DownloadOptions(url="https://example.com/test")
    task = mgr.create_task(opts)

    with pytest.raises(RuntimeError, match="Insufficient disk space"):
        mgr._execute_download_sync(task)


@patch("engine.PublicYoutubeDL")
def test_resolve_stream_urls(mock_ydl_class):
    mock_instance = mock_ydl_class.return_value.__enter__.return_value
    mock_instance.extract_info.return_value = {
        "title": "Stream Video",
        "uploader": "StreamUploader",
        "duration": 180,
        "thumbnail": "https://example.com/thumb.png",
        "formats": [
            {
                "format_id": "140",
                "url": "https://cdn.com/audio.m4a",
                "vcodec": "none",
                "acodec": "mp4a",
                "abr": 128,
                "ext": "m4a",
            },
            {
                "format_id": "137",
                "url": "https://cdn.com/v1080.mp4",
                "vcodec": "avc1",
                "acodec": "none",
                "height": 1080,
                "ext": "mp4",
            },
            {
                "format_id": "18",
                "url": "https://cdn.com/v360_combined.mp4",
                "vcodec": "avc1",
                "acodec": "mp4a",
                "height": 360,
                "ext": "mp4",
            },
        ],
    }
    from engine import resolve_stream_urls

    res = resolve_stream_urls(
        "https://example.com/watch", media_type="video", video_quality="1080p"
    )
    assert res["title"] == "Stream Video"
    assert res["audio_stream_url"] == "https://cdn.com/audio.m4a"
    assert res["video_stream_url"] == "https://cdn.com/v1080.mp4"
    assert res["has_combined_stream"] is True
    assert res["combined_stream_url"] == "https://cdn.com/v360_combined.mp4"


def test_classify_engine_error_extended():
    assert "Security check blocked request" in classify_engine_error(
        Exception("SSRF blocked: local or private IP")
    )
    assert "Insufficient disk space" in classify_engine_error(
        Exception("No disk space left on device")
    )


def test_metadata_cache_pruning():
    _METADATA_CACHE.clear()
    for i in range(100):
        set_cached_metadata(f"https://example.com/old_{i}", {"title": f"Old {i}"})
    assert len(_METADATA_CACHE) == 100
    # Adding one more triggers pruning of expired entries
    with patch("engine.time.monotonic", return_value=time.monotonic() + 400):
        set_cached_metadata("https://example.com/new_item", {"title": "New Item"})
        assert get_cached_metadata("https://example.com/new_item") == {"title": "New Item"}
    assert len(_METADATA_CACHE) == 1


@patch("engine.PublicYoutubeDL")
def test_extract_media_info_cached_hit(mock_ydl):
    mock_instance = mock_ydl.return_value.__enter__.return_value
    mock_instance.extract_info.return_value = {
        "id": "cache123",
        "title": "Cached Title",
        "uploader": "Uploader",
        "duration": 60,
        "formats": [],
    }
    url = "https://example.com/cache_hit_test"
    info1 = extract_media_info(url)
    assert info1["title"] == "Cached Title"
    # Call a second time - should hit cache
    info2 = extract_media_info(url)
    assert info2["title"] == "Cached Title"
    assert mock_instance.extract_info.call_count == 1


@patch("engine.PublicYoutubeDL")
def test_extract_media_info_4k_and_2k(mock_ydl):
    mock_instance = mock_ydl.return_value.__enter__.return_value
    mock_instance.extract_info.return_value = {
        "id": "4k_vid",
        "title": "4K Video",
        "duration": 120,
        "formats": [
            {
                "format_id": "313",
                "vcodec": "vp9",
                "acodec": "none",
                "height": 2160,
                "url": "https://cdn/4k.webm",
            },
            {
                "format_id": "271",
                "vcodec": "vp9",
                "acodec": "none",
                "height": 1440,
                "url": "https://cdn/2k.webm",
            },
            {
                "format_id": "140",
                "vcodec": "none",
                "acodec": "mp4a",
                "url": "https://cdn/audio.m4a",
            },
        ],
    }
    info = extract_media_info("https://example.com/4k_test")
    res_values = [r["value"] for r in info["available_video_resolutions"]]
    assert "2160p" in res_values
    assert "1440p" in res_values


@patch("engine.shutil.disk_usage")
def test_execute_download_sync_trim_end_less_than_start(mock_disk):
    mock_disk.return_value.free = 10 * 1024 * 1024 * 1024
    mgr = EngineManager()
    opts = DownloadOptions(
        url="https://example.com/test",
        trim_start="00:02:00",
        trim_end="00:01:00",
    )
    task = mgr.create_task(opts)
    with pytest.raises(ValueError, match="End time must be greater than start time"):
        mgr._execute_download_sync(task)


@patch("engine.PublicYoutubeDL")
def test_resolve_stream_urls_fallback_and_qualities(mock_ydl):
    mock_instance = mock_ydl.return_value.__enter__.return_value
    mock_instance.extract_info.return_value = {
        "title": "Fallback Video",
        "uploader": "Uploader",
        "duration": 50,
        "formats": [
            # Combined format with audio, no audio-only format
            {
                "format_id": "18",
                "url": "https://cdn/combined360.mp4",
                "vcodec": "avc1",
                "acodec": "mp4a",
                "height": 360,
                "ext": "mp4",
            },
            {
                "format_id": "22",
                "url": "https://cdn/combined720.mp4",
                "vcodec": "avc1",
                "acodec": "mp4a",
                "height": 720,
                "ext": "mp4",
            },
            {
                "format_id": "313",
                "url": "https://cdn/v4k.mp4",
                "vcodec": "vp9",
                "acodec": "none",
                "height": 2160,
                "ext": "mp4",
            },
        ],
    }
    from engine import resolve_stream_urls

    res = resolve_stream_urls("https://example.com/qualities", video_quality="720p")
    assert res["audio_stream_url"] == "https://cdn/combined720.mp4"
    assert res["video_stream_url"] == "https://cdn/combined720.mp4"

    res_4k = resolve_stream_urls("https://example.com/qualities", video_quality="4k")
    assert res_4k["video_height"] == 2160
    assert res_4k["video_stream_url"] == "https://cdn/v4k.mp4"


@patch("engine.PublicYoutubeDL")
def test_execute_download_sync_playlist_multiple_files_zipped(mock_ydl_class):
    import zipfile

    mgr = EngineManager()
    opts = DownloadOptions(
        url="https://example.com/playlist",
        playlist_indices=[1, 2],
    )
    task = mgr.create_task(opts)
    mock_instance = mock_ydl_class.return_value.__enter__.return_value

    def fake_download(urls):
        f1 = task._output_dir / "track1.mp3"
        f1.write_bytes(b"track 1 mp3")
        f2 = task._output_dir / "track2.mp3"
        f2.write_bytes(b"track 2 mp3")
        return 0

    mock_instance.download.side_effect = fake_download
    mgr._execute_download_sync(task)
    assert task.progress.status == "completed"
    assert task.progress.filename == "StreamFab_Playlist.zip"
    assert task.progress.file_path.endswith(".zip")
    with zipfile.ZipFile(task.progress.file_path, "r") as zf:
        names = zf.namelist()
        assert "track1.mp3" in names
        assert "track2.mp3" in names


@patch("engine.PublicYoutubeDL")
def test_execute_download_sync_wav_skips_embed_thumbnail(mock_ydl_class):
    mgr = EngineManager()
    opts = DownloadOptions(
        url="https://example.com/audio",
        media_type="audio",
        audio_format="wav",
        embed_thumbnail=True,
    )
    task = mgr.create_task(opts)
    mock_instance = mock_ydl_class.return_value.__enter__.return_value

    def fake_download(urls):
        opts_passed = mock_ydl_class.call_args[0][0]
        pp_keys = [p.get("key") for p in opts_passed.get("postprocessors", [])]
        assert "EmbedThumbnail" not in pp_keys
        out_f = task._output_dir / "audio.wav"
        out_f.write_bytes(b"wav bytes")
        return 0

    mock_instance.download.side_effect = fake_download
    mgr._execute_download_sync(task)
    assert task.progress.status == "completed"
