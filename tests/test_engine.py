import os
import sys
import time
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from engine import (
    format_duration,
    parse_timestamp,
    classify_engine_error,
    get_cached_metadata,
    set_cached_metadata,
    extract_media_info,
    DownloadOptions,
    DownloadTask,
    EngineManager,
    _METADATA_CACHE,
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
    assert "geographical" in classify_engine_error(Exception("Video not available in your country due to geo block"))
    assert "timed out" in classify_engine_error(Exception("Connection timed out"))
    assert "Random error" in classify_engine_error(Exception("Random error"))


def test_metadata_cache():
    url = "https://example.com/cached_test"
    set_cached_metadata(url, {"title": "Cached Video"})
    cached = get_cached_metadata(url)
    assert cached is not None
    assert cached["title"] == "Cached Video"

    # Test expiration
    _METADATA_CACHE[url] = (time.time() - 400, {"title": "Expired Video"})
    assert get_cached_metadata(url) is None


@patch('engine.yt_dlp.YoutubeDL')
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
            {"format_id": "18", "vcodec": "avc1", "acodec": "mp4a", "height": 360, "url": "https://stream.mp4"},
            {"format_id": "22", "vcodec": "avc1", "acodec": "mp4a", "height": 720, "url": "https://stream720.mp4"},
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


@patch('engine.yt_dlp.YoutubeDL')
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
    task = DownloadTask("task-uuid-123", opts)
    assert task.progress.status == "queued"
    assert task.to_dict()["status"] == "queued"

    # Subscriber test
    queue = task.add_subscriber()
    initial_event = queue.get_nowait()
    assert initial_event["task_id"] == "task-uuid-123"

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


@patch('engine.yt_dlp.YoutubeDL')
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
            hook({"status": "downloading", "_percent_str": "50.0%", "_speed_str": "10MiB/s", "_eta_str": "00:05", "downloaded_bytes": 500, "total_bytes": 1000})
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


@patch('engine.yt_dlp.YoutubeDL')
def test_execute_download_sync_video_and_trim(mock_ydl_class):
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
        assert "postprocessor_args" in opts_passed
        assert opts_passed["postprocessor_args"]["ffmpeg"] == ["-ss", "10.0", "-to", "45.0"]
        assert opts_passed["writesubtitles"] is True
        dummy_out = task._output_dir / "Clipped_Video.mp4"
        dummy_out.write_bytes(b"dummy mp4 data")
        return 0

    mock_instance.download.side_effect = fake_download
    mgr._execute_download_sync(task)
    assert task.progress.status == "completed"
    assert task.progress.filename == "Clipped_Video.mp4"


@patch('engine.yt_dlp.YoutubeDL')
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


@patch('engine.yt_dlp.YoutubeDL')
def test_execute_download_sync_failure_code(mock_ydl_class):
    mgr = EngineManager()
    opts = DownloadOptions(url="https://example.com/video")
    task = mgr.create_task(opts)

    mock_instance = mock_ydl_class.return_value.__enter__.return_value
    mock_instance.download.return_value = 1  # failure code

    with pytest.raises(RuntimeError, match="yt-dlp exit code: 1"):
        mgr._execute_download_sync(task)

