"""StreamFab Web Server - High-performance REST and SSE API.

Exposes endpoints for instant media analysis, download orchestration,
real-time SSE progress streaming, and direct browser delivery.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import os
import re
import urllib.parse
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from starlette.background import BackgroundTask
from starlette.middleware.trustedhost import TrustedHostMiddleware

from engine import (
    DOWNLOADS_DIR,
    DownloadOptions,
    classify_engine_error,
    delete_cookies_file,
    engine,
    extract_media_info,
    get_cookiefile_opt,
    get_cookies_status,
    parse_timestamp,
    resolve_stream_urls,
    save_cookies_text,
)
from networking import public_async_client
from security import (
    BodyLimitMiddleware,
    SecurityHeadersMiddleware,
    sanitize_filename,
    validate_and_sanitize_url,
    validate_timestamp_strict,
)

_background_tasks = set()
_extraction_active = 0
_proxy_active = 0


@asynccontextmanager
async def lifespan(app):
    async def maintenance():
        while True:
            await asyncio.sleep(60)
            engine.cleanup_old_tasks()

    cleanup = asyncio.create_task(maintenance())
    try:
        yield
    finally:
        cleanup.cancel()
        for task in engine.tasks.values():
            task.cancel()
        await asyncio.gather(cleanup, *_background_tasks, return_exceptions=True)


async def extract_bounded(function, *args):
    global _extraction_active
    if _extraction_active >= 4:
        raise HTTPException(
            status_code=503, detail="Media analysis capacity reached. Please try again later."
        )
    _extraction_active += 1
    future = asyncio.get_running_loop().run_in_executor(None, function, *args)

    def release(_):
        global _extraction_active
        _extraction_active -= 1

    future.add_done_callback(release)
    return await asyncio.shield(future)


async def require_cookie_admin(request: Request):
    token = os.getenv("STREAMFAB_ADMIN_TOKEN")
    if token:
        provided = request.headers.get("authorization", "").removeprefix("Bearer ")
        if not hmac.compare_digest(provided.encode(), token.encode()):
            raise HTTPException(
                status_code=403, detail="Cookie administration requires the configured admin token."
            )
    elif not request.client or request.client.host not in ("127.0.0.1", "::1"):
        raise HTTPException(
            status_code=403, detail="Cookie administration is restricted to localhost."
        )


async def require_media_user(request: Request):
    # A shared cookie jar must never lend the owner's session to anonymous users.
    if get_cookiefile_opt():
        await require_cookie_admin(request)


app = FastAPI(
    lifespan=lifespan,
    title="StreamFab Web API",
    description="Ultra-fast media conversion and download engine surpassing NoTube.",
    version="2.0.0",
)

# Apply strict security headers & rate limiting
app.add_middleware(BodyLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=[
        h.strip()
        for h in os.getenv("STREAMFAB_TRUSTED_HOSTS", "localhost,127.0.0.1,[::1]").split(",")
        if h.strip()
    ],
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)


class InfoRequest(BaseModel):
    url: str = Field(..., max_length=8192, description="Target media or playlist URL")

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("URL cannot be empty.")
        if not clean.startswith(("http://", "https://")):
            clean = "https://" + clean
        try:
            parsed = urllib.parse.urlparse(clean)
            if (
                parsed.scheme not in ("http", "https")
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
            ):
                raise ValueError("Please provide an HTTP/HTTPS URL without credentials.")
            if any(c.isspace() for c in clean) or "\\" in clean or len(clean) > 8192:
                raise ValueError("Invalid URL characters or length.")
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("Please provide a valid HTTP/HTTPS URL.") from exc
        return clean


class DownloadRequest(InfoRequest):
    media_type: Literal["audio", "video"] = "audio"  # audio or video
    audio_format: Literal["mp3", "m4a", "flac", "wav", "opus"] = "mp3"
    audio_quality: Literal["320k", "256k", "192k", "128k", "best"] = "320k"
    video_format: Literal["mp4", "mkv", "webm"] = "mp4"
    video_quality: str = Field(default="best", pattern=r"^(best|worst|4k|2k|[1-9][0-9]{1,3}p)$")
    trim_start: str | None = None
    trim_end: str | None = None
    embed_metadata: bool = True
    embed_thumbnail: bool = True
    subtitle_lang: str | None = Field(
        default=None, max_length=30, pattern=r"^[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]{2,8})*$"
    )
    playlist_indices: list[Annotated[int, Field(strict=True, ge=1, le=1000)]] | None = Field(
        default=None, min_length=1, max_length=250
    )

    @field_validator("trim_start", "trim_end")
    @classmethod
    def validate_timestamp_format(cls, v: str | None) -> str | None:
        if not v or not str(v).strip():
            return None
        try:
            validate_timestamp_strict(v)
        except Exception as e:
            raise ValueError(f"Invalid timestamp format: {e}")
        return v.strip()

    @field_validator("trim_end")
    @classmethod
    def validate_trim(cls, v: str | None, info) -> str | None:
        # Validate trim start/end timestamps if provided
        start_raw = info.data.get("trim_start")
        if v:
            s_sec = parse_timestamp(start_raw) or 0
            e_sec = parse_timestamp(v)
            if s_sec is not None and e_sec is not None and e_sec <= s_sec:
                raise ValueError("End time must be greater than start time.")
        return v


@app.get("/api/health")
async def health_check() -> dict[str, Any]:
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "streamfab",
        "version": "2.0.0",
        "active_tasks": sum(
            t.progress.status in ("queued", "downloading", "converting")
            for t in engine.tasks.values()
        ),
    }


@app.post("/api/info", dependencies=[Depends(require_media_user)])
async def get_info(req: InfoRequest) -> dict[str, Any]:
    """Extract metadata, available resolutions, and options for a given URL."""
    try:
        # Offload yt-dlp metadata extraction to threadpool to keep async loop fast
        data = await extract_bounded(extract_media_info, req.url)
        return {"success": True, "data": data}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=classify_engine_error(exc),
        ) from exc


class StreamUrlsRequest(DownloadRequest):
    pass


@app.post("/api/stream-urls", dependencies=[Depends(require_media_user)])
async def get_stream_urls(req: StreamUrlsRequest) -> dict[str, Any]:
    """Resolve direct/proxied stream URLs for zero-server-CPU client-side processing."""
    try:
        data = await extract_bounded(
            resolve_stream_urls,
            req.url,
            req.media_type,
            req.video_quality,
            req.video_format,
            req.audio_format,
        )
        result = dict(data)
        if data.get("audio_stream_url"):
            result["audio_proxy_url"] = (
                f"/api/proxy-stream?url={urllib.parse.quote(data['audio_stream_url'])}"
            )
        if data.get("video_stream_url"):
            result["video_proxy_url"] = (
                f"/api/proxy-stream?url={urllib.parse.quote(data['video_stream_url'])}"
            )
        if data.get("combined_stream_url"):
            result["combined_proxy_url"] = (
                f"/api/proxy-stream?url={urllib.parse.quote(data['combined_stream_url'])}"
            )
        return {"success": True, "data": result}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=classify_engine_error(exc),
        ) from exc


@app.get("/api/proxy-stream", dependencies=[Depends(require_media_user)])
async def proxy_stream(url: str, request: Request) -> StreamingResponse:
    """Zero-CPU asynchronous stream pass-through with Range support for browser clients."""
    try:
        current_url = await asyncio.to_thread(validate_and_sanitize_url, url)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid stream URL: {exc}")

    range_header = request.headers.get("range")
    req_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    if range_header:
        if len(range_header) > 100 or not re.fullmatch(
            r"bytes=(?:[0-9]+-[0-9]*|-[0-9]+)", range_header
        ):
            raise HTTPException(status_code=400, detail="Only one byte range is supported.")
        req_headers["Range"] = range_header
    req_headers["Accept-Encoding"] = "identity"

    # Do not auto-follow redirects blindly to prevent SSRF bypass via 302 redirects
    global _proxy_active
    if _proxy_active >= 16:
        raise HTTPException(status_code=503, detail="Stream capacity reached. Try again later.")
    _proxy_active += 1
    client = public_async_client()
    upstream_resp = None
    try:
        for _ in range(5):
            upstream_req = client.build_request("GET", current_url, headers=req_headers)
            resp = await client.send(upstream_req, stream=True)
            if resp.is_redirect and "location" in resp.headers:
                raw_loc = resp.headers["location"]
                await resp.aclose()
                next_url = urllib.parse.urljoin(current_url, raw_loc)
                current_url = await asyncio.to_thread(validate_and_sanitize_url, next_url)
                continue
            upstream_resp = resp
            break

        if upstream_resp is None:
            raise HTTPException(status_code=502, detail="Too many redirects from upstream stream.")
    except HTTPException:
        _proxy_active -= 1
        await client.aclose()
        raise
    except Exception:
        _proxy_active -= 1
        if upstream_resp:
            await upstream_resp.aclose()
        await client.aclose()
        raise HTTPException(status_code=502, detail="Upstream stream request failed.")

    content_type = (
        upstream_resp.headers.get("content-type", "application/octet-stream")
        .split(";", 1)[0]
        .strip()
        .lower()
    )
    if not (
        content_type.startswith(("audio/", "video/"))
        or content_type
        in ("image/jpeg", "image/png", "image/webp", "application/octet-stream", "application/mp4")
    ):
        _proxy_active -= 1
        await upstream_resp.aclose()
        await client.aclose()
        raise HTTPException(status_code=502, detail="Upstream response is not supported media.")
    resp_headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, no-store",
    }
    for h in ("content-type", "content-length", "content-range", "content-encoding"):
        if h in upstream_resp.headers:
            resp_headers[h] = upstream_resp.headers[h]

    closed = False

    async def close_stream():
        nonlocal closed
        global _proxy_active
        if not closed:
            closed = True
            _proxy_active -= 1
            await upstream_resp.aclose()
            await client.aclose()

    async def stream_generator():
        total = 0
        try:
            async for chunk in upstream_resp.aiter_raw(chunk_size=65536):
                total += len(chunk)
                if total > 2 * 1024**3:
                    break
                yield chunk
        finally:
            await close_stream()

    return StreamingResponse(
        stream_generator(),
        background=BackgroundTask(close_stream),
        status_code=upstream_resp.status_code,
        headers=resp_headers,
        media_type=upstream_resp.headers.get("content-type", "application/octet-stream"),
    )


@app.post("/api/download", dependencies=[Depends(require_media_user)])
async def start_download(req: DownloadRequest) -> dict[str, Any]:
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
    try:
        await asyncio.to_thread(validate_and_sanitize_url, options.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid or forbidden media URL.") from exc
    try:
        task = engine.create_task(options)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    background = asyncio.create_task(engine.run_task(task))
    _background_tasks.add(background)
    background.add_done_callback(_background_tasks.discard)
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
        if str(uuid.UUID(task_id)) != task_id:
            raise ValueError("Non-canonical task ID")
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
        if str(uuid.UUID(task_id)) != task_id:
            raise ValueError("Non-canonical task ID")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID.")

    task = engine.get_task(task_id)
    file_path: Path | None = None
    filename: str | None = None

    expected_dir = (DOWNLOADS_DIR / task_id).resolve()
    if not expected_dir.is_relative_to(DOWNLOADS_DIR.resolve()):
        raise HTTPException(status_code=403, detail="Unauthorized access.")
    if task:
        if task.progress.status == "completed" and task.progress.file_path:
            file_path = Path(task.progress.file_path).resolve()
            filename = sanitize_filename(task.progress.filename or file_path.name)
    else:
        marker = expected_dir / "completed.json"
        if marker.is_file() and not marker.is_symlink():
            try:
                record = json.loads(marker.read_text(encoding="utf-8"))
                name = record["filename"]
                if isinstance(name, str) and Path(name).name == name:
                    file_path = (expected_dir / name).resolve()
                    filename = sanitize_filename(name)
            except (OSError, ValueError, KeyError, TypeError):
                pass

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
        ".zip": "application/zip",
    }
    content_type = media_types.get(ext, "application/octet-stream")

    return FileResponse(
        path=str(file_path),
        filename=filename or file_path.name,
        media_type=content_type,
        content_disposition_type="attachment",
    )


@app.post("/api/cancel/{task_id}")
async def cancel_download(task_id: str) -> dict[str, Any]:
    """Cancel an ongoing download task."""
    try:
        if str(uuid.UUID(task_id)) != task_id:
            raise ValueError("Non-canonical task ID")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID.")

    task = engine.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")

    task.cancel()
    return {"success": True, "message": "Download cancelled."}


class CookiePayload(BaseModel):
    content: str


@app.get("/api/cookies")
async def get_cookies(_=Depends(require_cookie_admin)) -> dict[str, Any]:
    """Get status of installed cookies.txt file."""
    status_data = get_cookies_status()
    return {"success": True, "data": status_data}


@app.post("/api/cookies")
async def upload_cookies(payload: CookiePayload, _=Depends(require_cookie_admin)) -> dict[str, Any]:
    """Upload or paste Netscape format cookies.txt to bypass YouTube bot challenges."""
    try:
        updated = save_cookies_text(payload.content)
        return {"success": True, "data": updated, "message": "Cookies saved successfully."}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/cookies")
async def remove_cookies(_=Depends(require_cookie_admin)) -> dict[str, Any]:
    """Remove installed cookies.txt."""
    deleted = delete_cookies_file()
    return {"success": True, "deleted": deleted}


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
