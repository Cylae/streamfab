import os
import sys
import uuid
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from web_server import app
from engine import DownloadOptions, DownloadTask, engine, DOWNLOADS_DIR

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "streamfab"
    assert "version" in data


def test_root_index():
    response = client.get("/")
    assert response.status_code == 200
    assert "StreamFab" in response.text


@patch('web_server.extract_media_info')
def test_info_endpoint_success(mock_extract):
    mock_extract.return_value = {
        "id": "123",
        "title": "Test Title",
        "uploader": "Tester",
        "duration": 120,
        "duration_formatted": "02:00",
        "thumbnail": "https://example.com/thumb.jpg",
        "is_playlist": False,
        "available_video_resolutions": [{"height": 1080, "label": "1080p", "value": "1080p"}],
        "subtitles": [],
    }

    response = client.post("/api/info", json={"url": "https://youtube.com/watch?v=123"})
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["success"] is True
    assert res_data["data"]["title"] == "Test Title"


def test_info_endpoint_empty_url():
    response = client.post("/api/info", json={"url": "   "})
    assert response.status_code == 422


@patch('engine.EngineManager.run_task')
def test_download_endpoint_success(mock_run):
    payload = {
        "url": "https://youtube.com/watch?v=123",
        "media_type": "audio",
        "audio_format": "mp3",
        "audio_quality": "320k",
        "embed_metadata": True,
        "embed_thumbnail": True,
    }
    response = client.post("/api/download", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "task_id" in data
    assert uuid.UUID(data["task_id"])


def test_download_endpoint_invalid_trim_validation():
    payload = {
        "url": "https://youtube.com/watch?v=123",
        "trim_start": "03:00",
        "trim_end": "01:00",  # End is before start
    }
    response = client.post("/api/download", json=payload)
    assert response.status_code == 422
    assert "greater" in response.text


def test_file_download_invalid_uuid():
    response = client.get("/api/file/non-existent-uuid-string")
    assert response.status_code == 400


def test_file_download_success(tmp_path):
    # Setup completed task with real temp file
    task_id = str(uuid.uuid4())
    opts = DownloadOptions(url="https://example.com/test")
    task = DownloadTask(task_id, opts)

    # Create dummy media file inside the task's directory
    sample_file = task._output_dir / "test_audio.mp3"
    sample_file.write_bytes(b"ID3\x03\x00\x00\x00\x00\x00\x00fake audio content")

    task.progress.status = "completed"
    task.progress.filename = "test_audio.mp3"
    task.progress.file_path = str(sample_file)
    task.progress.file_size = sample_file.stat().st_size

    engine.tasks[task_id] = task

    response = client.get(f"/api/file/{task_id}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/mpeg")
    assert 'attachment; filename="test_audio.mp3"' in response.headers["content-disposition"]
    assert response.content == b"ID3\x03\x00\x00\x00\x00\x00\x00fake audio content"


def test_file_download_path_traversal_blocked():
    # Attempt path traversal: file path outside task directory
    task_id = str(uuid.uuid4())
    opts = DownloadOptions(url="https://example.com/test")
    task = DownloadTask(task_id, opts)

    # Point file_path to /etc/hosts or arbitrary parent directory file
    task.progress.status = "completed"
    task.progress.filename = "malicious.txt"
    task.progress.file_path = str(DOWNLOADS_DIR.parent / "escape.txt")

    engine.tasks[task_id] = task

    response = client.get(f"/api/file/{task_id}")
    assert response.status_code in (403, 404)


def test_cancel_endpoint():
    task_id = str(uuid.uuid4())
    opts = DownloadOptions(url="https://example.com/test")
    task = DownloadTask(task_id, opts)
    engine.tasks[task_id] = task

    response = client.post(f"/api/cancel/{task_id}")
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert task.progress.status == "cancelled"


def test_progress_sse_invalid_uuid():
    response = client.get("/api/progress/not-a-valid-uuid")
    assert response.status_code == 400


def test_progress_sse_not_found():
    random_uuid = str(uuid.uuid4())
    response = client.get(f"/api/progress/{random_uuid}")
    assert response.status_code == 404


def test_progress_sse_stream():
    task_id = str(uuid.uuid4())
    opts = DownloadOptions(url="https://example.com/test")
    task = DownloadTask(task_id, opts)
    task.progress.status = "completed"
    engine.tasks[task_id] = task

    with client.stream("GET", f"/api/progress/{task_id}") as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        line = next(response.iter_lines())
        assert line.startswith("data: ")
        assert "completed" in line


def test_video_resolution_request():
    payload = {
        "url": "https://youtube.com/watch?v=vid1080",
        "media_type": "video",
        "video_format": "mp4",
        "video_quality": "1080p",
    }
    response = client.post("/api/download", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    task = engine.get_task(data["task_id"])
    assert task is not None
    assert task.options.video_quality == "1080p"
    assert task.options.video_format == "mp4"


def test_cancel_english_message():
    task_id = str(uuid.uuid4())
    opts = DownloadOptions(url="https://example.com/test")
    task = DownloadTask(task_id, opts)
    engine.tasks[task_id] = task

    response = client.post(f"/api/cancel/{task_id}")
    assert response.status_code == 200
    assert response.json()["message"] == "Download cancelled."


def test_static_index_html_english():
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert "Download &amp; Convert" in html or "Download & Convert" in html
    assert "Features" in html
    assert "Built-in Audio/Video Trimmer" in html
    assert "Why StreamFab Outclasses NoTube" in html
    # Ensure no French strings in UI
    assert "Téléchargez" not in html
    assert "Découpeur Audio/Vidéo" not in html
    assert "Avantages" not in html

