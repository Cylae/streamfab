"""StreamFab Web Server - High-performance REST and SSE API.

Exposes endpoints for instant media analysis, download orchestration,
real-time SSE progress streaming, and direct browser delivery.
"""

from __future__ import annotations

import asyncio
import json
import re
import urllib.parse
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from engine import (
    DownloadOptions,
    DownloadTask,
    DOWNLOADS_DIR,
    engine,
    extract_media_info,
    parse_timestamp,
    resolve_stream_urls,
)
from security import (
    SecurityHeadersMiddleware,
    sanitize_filename,
    validate_and_sanitize_url,
)

app = FastAPI(
    title="StreamFab Web API",
    description="Ultra-fast media conversion and download engine surpassing NoTube.",
    version="2.0.0",
)

# Apply strict security headers & rate limiting
app.add_middleware(SecurityHeadersMiddleware)

# Enable CORS for local and remote web access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)


class InfoRequest(BaseModel):
    url: str = Field(..., description="Target media or playlist URL")

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("URL cannot be empty.")
        if not re.match(r"^https?://[^\s/$.?#].[^\s]*$", clean, re.IGNORECASE):
            # Allow common short forms like 'youtu.be/...'
            if not any(clean.startswith(prefix) for prefix in ("http://", "https://", "www.", "youtu.be", "youtube.com")):
                raise ValueError("Please provide a valid URL (e.g. https://...).")
            if not clean.startswith(("http://", "https://")):
                clean = "https://" + clean
        return clean


class DownloadRequest(BaseModel):
    url: str
    media_type: str = Field(default="audio")  # audio or video
    audio_format: str = Field(default="mp3")
    audio_quality: str = Field(default="320k")
    video_format: str = Field(default="mp4")
    video_quality: str = Field(default="best")
    trim_start: Optional[str] = None
    trim_end: Optional[str] = None
    embed_metadata: bool = True
    embed_thumbnail: bool = True
    subtitle_lang: Optional[str] = None
    playlist_indices: Optional[List[int]] = None

    @field_validator("url")
    @classmethod
    def clean_url(cls, v: str) -> str:
        s = v.strip()
        if not s.startswith(("http://", "https://")):
            return "https://" + s
        return s

    @field_validator("trim_end")
    @classmethod
    def validate_trim(cls, v: Optional[str], info) -> Optional[str]:
        # Validate trim start/end timestamps if provided
        start_raw = info.data.get("trim_start")
        if v and start_raw:
            s_sec = parse_timestamp(start_raw)
            e_sec = parse_timestamp(v)
            if s_sec is not None and e_sec is not None and e_sec <= s_sec:
                raise ValueError("End time must be greater than start time.")
        return v


@app.get("/api/health")
async def health_check() -> Dict[str, Any]:
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "streamfab",
        "version": "2.0.0",
        "active_tasks": len(engine.tasks),
    }


@app.post("/api/info")
async def get_info(req: InfoRequest) -> Dict[str, Any]:
    """Extract metadata, available resolutions, and options for a given URL."""
    loop = asyncio.get_running_loop()
    try:
        # Offload yt-dlp metadata extraction to threadpool to keep async loop fast
        data = await loop.run_in_executor(None, extract_media_info, req.url)
        return {"success": True, "data": data}
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


class StreamUrlsRequest(BaseModel):
    url: str
    media_type: str = Field(default="audio")  # audio or video
    audio_format: str = Field(default="mp3")
    audio_quality: str = Field(default="320k")
    video_format: str = Field(default="mp4")
    video_quality: str = Field(default="best")


@app.post("/api/stream-urls")
async def get_stream_urls(req: StreamUrlsRequest) -> Dict[str, Any]:
    """Resolve direct/proxied stream URLs for zero-server-CPU client-side processing."""
    loop = asyncio.get_running_loop()
    try:
        data = await loop.run_in_executor(
            None,
            resolve_stream_urls,
            req.url,
            req.media_type,
            req.video_quality,
            req.video_format,
            req.audio_format,
        )
        result = dict(data)
        if data.get("audio_stream_url"):
            result["audio_proxy_url"] = f"/api/proxy-stream?url={urllib.parse.quote(data['audio_stream_url'])}"
        if data.get("video_stream_url"):
            result["video_proxy_url"] = f"/api/proxy-stream?url={urllib.parse.quote(data['video_stream_url'])}"
        if data.get("combined_stream_url"):
            result["combined_proxy_url"] = f"/api/proxy-stream?url={urllib.parse.quote(data['combined_stream_url'])}"
        return {"success": True, "data": result}
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@app.get("/api/proxy-stream")
async def proxy_stream(url: str, request: Request) -> StreamingResponse:
    """Zero-CPU asynchronous stream pass-through with Range support for browser clients."""
    try:
        safe_url = validate_and_sanitize_url(url)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid stream URL: {exc}")

    range_header = request.headers.get("range")
    req_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    if range_header:
        req_headers["Range"] = range_header

    client = httpx.AsyncClient(timeout=60.0, follow_redirects=True)
    try:
        upstream_req = client.build_request("GET", safe_url, headers=req_headers)
        upstream_resp = await client.send(upstream_req, stream=True)
    except Exception as exc:
        await client.aclose()
        raise HTTPException(status_code=502, detail=f"Upstream stream error: {exc}")

    resp_headers = {
        "Access-Control-Allow-Origin": "*",
        "Accept-Ranges": "bytes",
        "Cache-Control": "public, max-age=3600",
    }
    for h in ("content-type", "content-length", "content-range"):
        if h in upstream_resp.headers:
            resp_headers[h] = upstream_resp.headers[h]

    async def stream_generator():
        try:
            async for chunk in upstream_resp.aiter_bytes(chunk_size=65536):
                yield chunk
        finally:
            await upstream_resp.aclose()
            await client.aclose()

    return StreamingResponse(
        stream_generator(),
        status_code=upstream_resp.status_code,
        headers=resp_headers,
        media_type=upstream_resp.headers.get("content-type", "application/octet-stream"),
    )


@app.post("/api/download")
async def start_download(req: DownloadRequest) -> Dict[str, Any]:
    """Initiate a download task with high performance settings."""
    options = DownloadOptions(
        url=req.url,
        media_type=req.media_type,
        audio_format=req.audio_format,
        audio_quality=req.audio_quality,
        video_format=req.video_format,
        video_quality=req.video_quality,
        trim_start=req.trim_start,
        trim_end=req.trim_end,
        embed_metadata=req.embed_metadata,
        embed_thumbnail=req.embed_thumbnail,
        subtitle_lang=req.subtitle_lang,
        playlist_indices=req.playlist_indices,
    )
    task = engine.create_task(options)
    # Launch in asyncio background task
    asyncio.create_task(engine.run_task(task))
    return {
        "success": True,
        "task_id": task.task_id,
        "status": task.progress.status,
    }


@app.get("/api/progress/{task_id}")
async def stream_progress(task_id: str) -> StreamingResponse:
    """Stream real-time download and conversion progress via Server-Sent Events (SSE)."""
    # Validate UUID to prevent injection
    try:
        uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID.")

    task = engine.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")

    async def event_generator() -> AsyncGenerator[str, None]:
        queue = task.add_subscriber()
        try:
            while True:
                try:
                    # Wait up to 15 seconds for an event, then send keep-alive ping
                    data = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {json.dumps(data)}\n\n"
                    if data.get("status") in ("completed", "error", "cancelled"):
                        break
                except asyncio.TimeoutError:
                    # Keep-alive comment
                    yield ": ping\n\n"
        finally:
            task.remove_subscriber(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/file/{task_id}")
async def download_file(task_id: str) -> FileResponse:
    """Serve the final converted file safely with proper Content-Disposition."""
    try:
        uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID.")

    task = engine.get_task(task_id)
    file_path: Optional[Path] = None
    filename: Optional[str] = None

    if task and task.progress.status == "completed" and task.progress.file_path:
        file_path = Path(task.progress.file_path).resolve()
        filename = task.progress.filename or file_path.name
    else:
        # Fallback check on disk in case server restarted or task evicted
        expected_dir = (DOWNLOADS_DIR / task_id).resolve()
        if expected_dir.is_dir():
            files = [f for f in expected_dir.iterdir() if f.is_file() and not f.name.endswith((".part", ".ytdl"))]
            if files:
                file_path = max(files, key=lambda f: f.stat().st_size).resolve()
                filename = sanitize_filename(file_path.name)

    if not file_path or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not ready or task does not exist.")

    # Path traversal check: verify the file is strictly inside the task's directory
    expected_dir = (DOWNLOADS_DIR / task_id).resolve()
    if not file_path.is_relative_to(expected_dir):
        raise HTTPException(status_code=403, detail="Unauthorized access.")

    # Determine safe media type
    ext = file_path.suffix.lower()
    media_types = {
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".flac": "audio/flac",
        ".wav": "audio/wav",
        ".opus": "audio/opus",
        ".mp4": "video/mp4",
        ".mkv": "video/x-matroska",
        ".webm": "video/webm",
    }
    content_type = media_types.get(ext, "application/octet-stream")

    return FileResponse(
        path=str(file_path),
        filename=filename or file_path.name,
        media_type=content_type,
        content_disposition_type="attachment",
    )


@app.post("/api/cancel/{task_id}")
async def cancel_download(task_id: str) -> Dict[str, Any]:
    """Cancel an ongoing download task."""
    try:
        uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID.")

    task = engine.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")

    task.cancel()
    return {"success": True, "message": "Download cancelled."}


# Serve SPA frontend
@app.get("/favicon.ico")
async def favicon():
    return Response(content=b"", media_type="image/x-icon", status_code=204)


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>StreamFab Web Server Ready. Frontend initializing...</h1>")



# Mount static assets (css, js, assets)
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
