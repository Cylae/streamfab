"""StreamFab Engine - High-performance Media Extraction and Conversion Engine.

Provides blazing-fast metadata extraction, concurrent fragment downloads,
FFmpeg-accelerated conversion, time-based trimming, subtitle handling,
and real-time event-driven progress tracking.
Hardened against SSRF, command injection, path traversal, and resource exhaustion.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
import zipfile
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from http.cookiejar import MozillaCookieJar
from itertools import islice
from pathlib import Path
from typing import Any

from networking import PublicYoutubeDL
from security import (
    sanitize_filename,
    validate_and_sanitize_url,
    validate_timestamp_strict,
)

# Output directory for processed files
storage_env = os.getenv("STREAMFAB_STORAGE_DIR") or os.getenv("STREAMFAB_DOWNLOADS_DIR")
if storage_env:
    DOWNLOADS_DIR = Path(storage_env).resolve()
else:
    DOWNLOADS_DIR = Path(tempfile.gettempdir()) / "streamfab_downloads"
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
if os.name != "nt":
    DOWNLOADS_DIR.chmod(0o700)

# Credential-separated metadata cache, using monotonic TTLs and jar generations.
_METADATA_CACHE: dict[tuple[str, bool], tuple[float, dict[str, Any]]] = {}
_CACHE_GENERATION = 0
CACHE_TTL_SECONDS = 300  # 5 minutes
TASK_RETENTION_SECONDS = 3600  # 1 hour auto-cleanup
MAX_TASKS = 100
_CACHE_LOCK = threading.Lock()
_COOKIE_LOCK = threading.RLock()
MAX_CONCURRENT_DOWNLOADS = 3  # Protect server resources against DoS


def format_duration(seconds: float | int | None) -> str:
    """Format seconds into HH:MM:SS or MM:SS."""
    if seconds is None or seconds < 0:
        return "00:00"
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def parse_timestamp(timestamp_str: str | None) -> float | None:
    """Parse string timestamp safely using strict regex validation."""
    if timestamp_str is None:
        return None
    s = str(timestamp_str).strip()
    if not s:
        return None
    if s.startswith("-"):
        return 0.0
    try:
        return validate_timestamp_strict(s)
    except Exception:
        return None


COOKIES_FILE_PATH = (Path(__file__).resolve().parent.parent / "cookies.txt").resolve()


def get_cookiefile_opt() -> str | None:
    """An explicit configuration is authoritative, even when its file is absent."""
    with _COOKIE_LOCK:
        candidate = cookie_write_path()
        return str(candidate.resolve()) if candidate.is_file() else None


def get_cookies_status() -> dict[str, Any]:
    """Return status of installed YouTube cookies."""
    cookie_path = get_cookiefile_opt()
    if not cookie_path or not os.path.isfile(cookie_path):
        return {
            "has_cookies": False,
            "filename": None,
            "count": 0,
            "has_youtube_cookies": False,
            "youtube_count": 0,
            "updated_at": None,
        }
    try:
        jar = MozillaCookieJar(cookie_path)
        jar.load(ignore_discard=True, ignore_expires=True)
        cookies = list(jar)
        yt_count = sum(
            1
            for c in cookies
            if c.domain.lstrip(".") in ("youtube.com", "google.com")
            or c.domain.endswith((".youtube.com", ".google.com"))
        )
        return {
            "has_cookies": True,
            "filename": Path(cookie_path).name,
            "count": len(cookies),
            "has_youtube_cookies": yt_count > 0,
            "youtube_count": yt_count,
            "updated_at": datetime.fromtimestamp(
                Path(cookie_path).stat().st_mtime, timezone.utc
            ).isoformat(),
        }
    except (OSError, ValueError):
        return {
            "has_cookies": False,
            "filename": None,
            "count": 0,
            "has_youtube_cookies": False,
            "youtube_count": 0,
            "updated_at": None,
        }


def cookie_write_path() -> Path:
    return Path(os.getenv("STREAMFAB_COOKIES_FILE") or COOKIES_FILE_PATH)


def save_cookies_text(content: str) -> dict[str, Any]:
    """Validate Netscape cookies before atomic replacement with private permissions."""
    clean = content.strip()
    if not clean:
        raise ValueError("Cookie content cannot be empty.")
    if len(clean.encode("utf-8")) > 2 * 1024 * 1024:
        raise ValueError("Cookie file size exceeds maximum limit of 2MB.")
    destination = cookie_write_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".cookies-", dir=destination.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(clean + "\n")
        jar = MozillaCookieJar(temp_name)
        try:
            jar.load(ignore_discard=True, ignore_expires=True)
        except (OSError, ValueError) as exc:
            raise ValueError("Invalid Netscape cookie file.") from exc
        if not list(jar):
            raise ValueError("Cookie file contains no cookies.")
        with _COOKIE_LOCK:
            os.replace(temp_name, destination)
            invalidate_metadata_cache()
    finally:
        Path(temp_name).unlink(missing_ok=True)
    return get_cookies_status()


def delete_cookies_file() -> bool:
    """Delete exactly the configured jar and invalidate in-flight cache writes."""
    with _COOKIE_LOCK:
        destination = cookie_write_path()
        existed = destination.is_file()
        destination.unlink(missing_ok=True)
        invalidate_metadata_cache()
        return existed


def invalidate_metadata_cache() -> None:
    global _CACHE_GENERATION
    with _CACHE_LOCK:
        _CACHE_GENERATION += 1
        _METADATA_CACHE.clear()


@contextmanager
def web_ydl(options, *, use_cookies=True):
    """Isolate each cookie jar so parallel downloads never overwrite credentials."""
    opts = dict(options, proxy="", hls_prefer_native=True)
    temporary = None
    try:
        with _COOKIE_LOCK:
            cookie_path = get_cookiefile_opt() if use_cookies else None
            if cookie_path:
                fd, temporary = tempfile.mkstemp(prefix="streamfab-cookie-")
                with os.fdopen(fd, "wb") as f:
                    f.write(Path(cookie_path).read_bytes())
        if temporary:
            opts["cookiefile"] = temporary
        else:
            opts.pop("cookiefile", None)
        with PublicYoutubeDL(opts) as ydl:
            yield ydl
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)


def classify_engine_error(exc: Exception) -> str:
    """Provide clean, human-friendly error diagnosis in English without leaking system internals."""
    msg = str(exc).lower()
    if "ssrf" in msg or "local or private" in msg or ("forbidden" in msg and "ip" in msg):
        return "Security check blocked request: unauthorized destination."
    if (
        "confirm you’re not a bot" in msg
        or "confirm you're not a bot" in msg
        or ("bot" in msg and ("sign in" in msg or "cookies" in msg))
    ):
        return (
            "YOUTUBE_BOT_CHECK: YouTube requires human verification for this network ('Sign in to confirm you’re not a bot'). "
            "Please use the 1-Click Cookie Assistant below to unlock this video."
        )
    if "drm" in msg or "protected content" in msg:
        return "This media is protected by DRM and cannot be downloaded."
    if "unsupported url" in msg or "is not a valid url" in msg:
        return "The provided URL is not recognized or not supported."
    if "403" in msg or "forbidden" in msg:
        return "Access denied by server (403) — content may require authentication or cookies."
    if "404" in msg or "not found" in msg:
        return "Content not found (404) — check if the link is still valid."
    if "private" in msg or "members-only" in msg or "login" in msg or "sign in" in msg:
        return "This video is private, members-only, or requires a login."
    if "geo" in msg or "country" in msg:
        return "This video is not available in your geographical country/region."
    if "timed out" in msg or "timeout" in msg or "connection" in msg:
        return "Connection timed out. Please try again."
    if "disk" in msg:
        return "Insufficient disk space on the server."
    return "Media processing failed. Check the server logs for details."


def get_cached_metadata(url: str, use_cookies: bool = True) -> dict[str, Any] | None:
    """Return cached metadata if still valid."""
    with _CACHE_LOCK:
        entry = _METADATA_CACHE.get((url, use_cookies))
        if entry:
            cached_time, data = entry
            if time.monotonic() - cached_time < CACHE_TTL_SECONDS:
                return deepcopy(data)
            _METADATA_CACHE.pop((url, use_cookies), None)
    return None


def set_cached_metadata(
    url: str, data: dict[str, Any], use_cookies: bool = True, generation: int | None = None
) -> None:
    """Hard-bound the cache, including when all entries are still fresh."""
    now = time.monotonic()
    key = (url, use_cookies)
    with _CACHE_LOCK:
        if generation is not None and generation != _CACHE_GENERATION:
            return
        expired = [k for k, (t, _) in _METADATA_CACHE.items() if now - t >= CACHE_TTL_SECONDS]
        for expired_key in expired:
            _METADATA_CACHE.pop(expired_key, None)
        if key not in _METADATA_CACHE and len(_METADATA_CACHE) >= 100:
            _METADATA_CACHE.pop(next(iter(_METADATA_CACHE)))
        _METADATA_CACHE[key] = (now, deepcopy(data))


def extract_media_info(
    url: str, fast_mode: bool = True, use_cookies: bool = True
) -> dict[str, Any]:
    """Extract metadata, formats, preview streams, and subtitle tracks safely."""
    # Enforce strict URL validation & anti-SSRF checks
    safe_url = validate_and_sanitize_url(url)

    with _CACHE_LOCK:
        generation = _CACHE_GENERATION
    cached = get_cached_metadata(safe_url, use_cookies)
    if cached:
        return cached

    ydl_opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist" if fast_mode else False,
        "ignoreconfig": True,
        "no_exec": True,
        "socket_timeout": 15,
    }

    try:
        with web_ydl(ydl_opts, use_cookies=use_cookies) as ydl:
            info = ydl.extract_info(safe_url, download=False)
    except Exception as e:
        raise ValueError(classify_engine_error(e)) from e

    if not info:
        raise ValueError("Unable to extract media information.")

    is_playlist = info.get("_type") == "playlist" or "entries" in info

    # Find highest quality thumbnail
    thumbnails = info.get("thumbnails") or []
    best_thumb = info.get("thumbnail")
    if thumbnails:
        valid_thumbs = [
            t
            for t in thumbnails
            if t.get("url") and t.get("url", "").startswith(("http://", "https://"))
        ]
        if valid_thumbs:
            best_thumb = valid_thumbs[-1]["url"]

    # Direct preview stream URL if accessible
    preview_url = None
    formats = info.get("formats") or []
    for fmt in reversed(formats):
        if fmt.get("url") and fmt.get("url", "").startswith(("http://", "https://")):
            if (
                fmt.get("vcodec") not in (None, "none")
                and fmt.get("acodec") not in (None, "none")
                and (fmt.get("height") or 0) <= 720
            ):
                preview_url = fmt["url"]
                break
            elif not preview_url and fmt.get("acodec") not in (None, "none"):
                preview_url = fmt["url"]

    result: dict[str, Any] = {
        "url": safe_url,
        "is_playlist": is_playlist,
        "id": info.get("id", ""),
        "title": info.get("title", "Untitled Media"),
        "uploader": info.get("uploader")
        or info.get("channel")
        or info.get("uploader_id")
        or "Unknown Creator",
        "uploader_url": info.get("uploader_url") or info.get("channel_url"),
        "thumbnail": best_thumb,
        "duration": info.get("duration"),
        "duration_formatted": format_duration(info.get("duration")),
        "view_count": info.get("view_count"),
        "description": (info.get("description") or "")[:350],
        "webpage_url": info.get("webpage_url") or safe_url,
        "preview_url": preview_url,
    }

    if is_playlist:
        entries = []
        raw_entries = info.get("entries") or []
        for idx, entry in enumerate(
            islice(raw_entries, 250)
        ):  # Cap at 250 entries to prevent memory exhaustion
            if not entry:
                continue
            entry_thumbs = entry.get("thumbnails") or []
            entry_thumb = entry.get("thumbnail") or (
                entry_thumbs[-1].get("url") if entry_thumbs else result["thumbnail"]
            )
            entry_url = entry.get("webpage_url") or entry.get("url")
            if not entry_url or not str(entry_url).startswith(("http://", "https://")):
                entry_id = entry.get("id")
                if entry_id and re.match(r"^[a-zA-Z0-9_-]{8,15}$", str(entry_id)):
                    entry_url = f"https://www.youtube.com/watch?v={entry_id}"
                else:
                    entry_url = f"{safe_url}#{idx + 1}"
            entries.append(
                {
                    "index": idx + 1,
                    "id": entry.get("id"),
                    "title": entry.get("title", f"Track {idx + 1}"),
                    "uploader": entry.get("uploader") or entry.get("channel") or result["uploader"],
                    "duration": entry.get("duration"),
                    "duration_formatted": format_duration(entry.get("duration")),
                    "thumbnail": entry_thumb,
                    "url": entry_url,
                }
            )
        result["playlist_entries"] = entries
        result["playlist_count"] = len(entries)
        result["available_video_resolutions"] = [
            {"height": 1080, "label": "1080p Full HD", "value": "1080p"},
            {"height": 720, "label": "720p HD", "value": "720p"},
            {"height": 480, "label": "480p SD", "value": "480p"},
            {"height": 360, "label": "360p Low", "value": "360p"},
        ]
        result["subtitles"] = []
    else:
        # Build clean resolution matrix
        resolutions_set: set[int] = set()
        has_audio = False
        for fmt in formats:
            if fmt.get("vcodec") not in (None, "none") and fmt.get("height"):
                resolutions_set.add(fmt["height"])
            if fmt.get("acodec") not in (None, "none"):
                has_audio = True

        standard_res = [2160, 1440, 1080, 720, 480, 360]
        available_res = []
        for r in standard_res:
            if any(h >= r for h in resolutions_set):
                if r == 2160:
                    label = "2160p 4K Ultra HD"
                elif r == 1440:
                    label = "1440p 2K QHD"
                elif r == 1080:
                    label = "1080p Full HD"
                elif r == 720:
                    label = "720p HD"
                elif r == 480:
                    label = "480p Standard"
                else:
                    label = "360p Low"
                available_res.append({"height": r, "label": label, "value": f"{r}p"})

        if not available_res and resolutions_set:
            max_h = max(resolutions_set)
            available_res.append(
                {"height": max_h, "label": f"{max_h}p (Maximum)", "value": f"{max_h}p"}
            )

        result["available_video_resolutions"] = available_res or [
            {"height": 1080, "label": "1080p HD (Optimal)", "value": "1080p"}
        ]
        result["has_audio"] = has_audio

        # Inspect subtitles
        subtitles_list = []
        subs = info.get("subtitles") or {}
        auto_subs = info.get("automatic_captions") or {}
        all_sub_keys = set(list(subs.keys()) + list(auto_subs.keys()))
        common_langs = ["fr", "en", "es", "de", "it", "pt", "ru", "ja", "ko", "zh"]
        for lang in sorted(all_sub_keys):
            if lang in common_langs or len(subtitles_list) < 15:
                subtitles_list.append(
                    {
                        "code": lang,
                        "name": lang.upper(),
                        "is_auto": lang in auto_subs and lang not in subs,
                    }
                )
        result["subtitles"] = subtitles_list

    set_cached_metadata(safe_url, result, use_cookies, generation)
    return result


@dataclass
class DownloadOptions:
    url: str
    use_cookies: bool = True  # Captured authorization; never upgraded while queued.
    media_type: str = "audio"  # 'audio' or 'video'
    audio_format: str = "mp3"  # mp3, m4a, flac, wav, opus
    audio_quality: str = "320k"  # 320k, 256k, 192k, 128k, best
    video_format: str = "mp4"  # mp4, mkv, webm
    video_quality: str = "best"  # best, 2160p, 1440p, 1080p, 720p, 480p, 360p
    trim_start: str | None = None  # e.g. "00:01:15"
    trim_end: str | None = None  # e.g. "00:02:45"
    embed_metadata: bool = True
    embed_thumbnail: bool = True
    subtitle_lang: str | None = None  # e.g. "fr", "en"
    playlist_indices: list[int] | None = None  # indices to download if playlist


@dataclass
class TaskProgress:
    status: str = "queued"  # queued, downloading, converting, completed, error, cancelled
    percent: float = 0.0
    speed: str = "0 KiB/s"
    eta: str = "00:00"
    downloaded_bytes: int = 0
    total_bytes: int = 0
    filename: str | None = None
    file_path: str | None = None
    file_size: int | None = None
    download_url: str | None = None
    error_message: str | None = None
    detail: str = "Waiting to start..."


class DownloadTask:
    def __init__(self, task_id: str, options: DownloadOptions):
        if str(uuid.UUID(task_id)) != task_id:
            raise ValueError("Task ID must be a canonical UUID.")
        self.task_id = task_id
        self.options = options
        self.progress = TaskProgress()
        self.created_at = datetime.now(timezone.utc)
        self.subscribers: list[asyncio.Queue] = []
        self._subscriber_loops = {}
        self._notification_lock = threading.RLock()
        self._pending_notifications = set()
        self._latest_notifications = {}
        self.finished_at = None
        self._running = False
        self._cancel_requested = False
        self._output_dir = (DOWNLOADS_DIR / task_id).resolve()
        self._output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

    def cancel(self) -> None:
        with self._notification_lock:
            if self.progress.status in ("completed", "error", "cancelled"):
                return
            self._cancel_requested = True
            self.progress.status = "cancelled"
            self.progress.detail = "Download cancelled."
            self.notify_subscribers()

    def add_subscriber(self) -> asyncio.Queue:
        with self._notification_lock:
            if len(self.subscribers) >= 32:
                raise RuntimeError("Progress subscriber capacity reached.")
            q: asyncio.Queue = asyncio.Queue(maxsize=1)
            try:
                self._subscriber_loops[q] = asyncio.get_running_loop()
            except RuntimeError:
                self._subscriber_loops[q] = None
            self.subscribers.append(q)
            q.put_nowait(self.to_dict())
            return q

    def remove_subscriber(self, q: asyncio.Queue) -> None:
        with self._notification_lock:
            if q in self.subscribers:
                self.subscribers.remove(q)
            self._subscriber_loops.pop(q, None)
            self._latest_notifications.pop(q, None)
            self._pending_notifications.discard(q)

    def update_progress(self, **fields) -> bool:
        """Make terminal transitions and worker updates atomic with cancellation."""
        with self._notification_lock:
            if self.progress.status in ("completed", "error", "cancelled"):
                return False
            for name, value in fields.items():
                setattr(self.progress, name, value)
            self.notify_subscribers()
            return True

    def notify_subscribers(self) -> None:
        with self._notification_lock:
            self._notify_subscribers_locked()

    def _notify_subscribers_locked(self) -> None:
        if self.progress.status in ("completed", "error", "cancelled") and self.finished_at is None:
            self.finished_at = datetime.now(timezone.utc)
        data = self.to_dict()

        def deliver(q):
            with self._notification_lock:
                self._pending_notifications.discard(q)
                if q not in self.subscribers:
                    return
                latest = self._latest_notifications.pop(q, data)
                if q.full():
                    q.get_nowait()
                q.put_nowait(latest)

        with self._notification_lock:
            for q in list(self.subscribers):
                loop = self._subscriber_loops.get(q)
                if loop is not None:
                    if not loop.is_closed():
                        self._latest_notifications[q] = data
                        if q not in self._pending_notifications:
                            self._pending_notifications.add(q)
                            try:
                                loop.call_soon_threadsafe(deliver, q)
                            except RuntimeError:
                                self.remove_subscriber(q)
                    else:
                        self.remove_subscriber(q)
                else:
                    deliver(q)

    def to_dict(self) -> dict[str, Any]:
        with self._notification_lock:
            return self._to_dict_locked()

    def _to_dict_locked(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.progress.status,
            "percent": round(self.progress.percent, 1),
            "speed": self.progress.speed,
            "eta": self.progress.eta,
            "detail": self.progress.detail,
            "filename": self.progress.filename,
            "file_size": self.progress.file_size,
            "download_url": f"/api/file/{self.task_id}"
            if self.progress.status == "completed"
            else None,
            "error_message": self.progress.error_message,
        }


class EngineManager:
    """Manages download tasks, throttles concurrency, and cleans up resources."""

    def __init__(self):
        self.tasks: dict[str, DownloadTask] = {}
        self._concurrency_semaphore: asyncio.Semaphore | None = None

    def _get_semaphore(self) -> asyncio.Semaphore:
        if self._concurrency_semaphore is None:
            self._concurrency_semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
        return self._concurrency_semaphore

    def cleanup_old_tasks(self) -> None:
        """Remove directories and task data older than TASK_RETENTION_SECONDS."""
        now = datetime.now(timezone.utc)
        to_delete = []
        for tid, task in list(self.tasks.items()):
            age = (now - (task.finished_at or task.created_at)).total_seconds()
            if (
                not task._running
                and task.progress.status in ("completed", "error", "cancelled")
                and age > TASK_RETENTION_SECONDS
            ):
                to_delete.append(tid)

        for tid in to_delete:
            task = self.tasks.pop(tid, None)
            if task and task._output_dir.exists():
                shutil.rmtree(task._output_dir, ignore_errors=True)

        # Also purge orphaned task directories on disk from previous runs
        if DOWNLOADS_DIR.exists():
            for folder in DOWNLOADS_DIR.iterdir():
                try:
                    canonical = str(uuid.UUID(folder.name)) == folder.name
                except ValueError:
                    canonical = False
                if (
                    canonical
                    and not folder.is_symlink()
                    and folder.is_dir()
                    and folder.name not in self.tasks
                ):
                    try:
                        mtime = folder.stat().st_mtime
                        if (time.time() - mtime) > TASK_RETENTION_SECONDS:
                            shutil.rmtree(folder, ignore_errors=True)
                    except OSError:
                        logging.getLogger(__name__).warning(
                            "Could not clean an expired task directory"
                        )

    def create_task(self, options: DownloadOptions) -> DownloadTask:
        self.cleanup_old_tasks()
        if len(self.tasks) >= MAX_TASKS:
            raise RuntimeError("Task capacity reached. Please try again later.")
        task_id = str(uuid.uuid4())
        task = DownloadTask(task_id, options)
        self.tasks[task_id] = task
        return task

    def get_task(self, task_id: str) -> DownloadTask | None:
        return self.tasks.get(task_id)

    async def run_task(self, task: DownloadTask) -> None:
        sem = self._get_semaphore()
        async with sem:
            if task._cancel_requested:
                return
            task._running = True
            loop = asyncio.get_running_loop()
            try:
                await loop.run_in_executor(None, self._execute_download_sync, task)
            except Exception as exc:
                if task._cancel_requested:
                    return
                logging.getLogger(__name__).exception("Download task failed")
                diagnosis = classify_engine_error(exc)
                task.update_progress(
                    status="error", error_message=diagnosis, detail=f"Error: {diagnosis}"
                )
            finally:
                task._running = False

    def _execute_download_sync(self, task: DownloadTask) -> None:
        if task._cancel_requested:
            return
        opts = task.options
        out_dir = task._output_dir

        if shutil.disk_usage(out_dir).free < 200 * 1024 * 1024:
            raise RuntimeError("Insufficient disk space on the server.")

        # Enforce strict URL validation & anti-SSRF checks
        safe_url = validate_and_sanitize_url(opts.url)
        opts.url = safe_url
        if task._cancel_requested:
            return

        if not task.update_progress(status="downloading", detail="Initializing media download..."):
            return

        ydl_opts: dict[str, Any] = {
            "paths": {"home": str(out_dir)},
            "outtmpl": {"default": "%(title).120B [%(id)s].%(ext)s"},
            "windowsfilenames": True,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": not bool(opts.playlist_indices),
            "concurrent_fragment_downloads": 8,  # Turbo multi-threaded downloads
            "retries": 3,
            "fragment_retries": 5,
            "ignoreconfig": True,  # Prevent malicious config file overrides
            "no_exec": True,  # Prevent command injection
            "socket_timeout": 20,
            "postprocessor_args": {"ffmpeg_i": ["-protocol_whitelist", "file,pipe"]},
            "max_filesize": 2 * 1024 * 1024 * 1024,  # 2 GB limit per download
        }

        # Validate timestamps strictly & configure ultra-efficient segment trimming
        trim_start_sec = validate_timestamp_strict(opts.trim_start) if opts.trim_start else None
        trim_end_sec = validate_timestamp_strict(opts.trim_end) if opts.trim_end else None
        if trim_end_sec is not None:
            if trim_end_sec <= (trim_start_sec or 0):
                raise ValueError("End time must be greater than start time.")

        target_codec = "mp3"
        # Audio conversion
        if opts.media_type == "audio":
            ydl_opts["format"] = "bestaudio/best"
            target_codec = opts.audio_format.lower()
            if target_codec not in ("mp3", "m4a", "flac", "wav", "opus"):
                target_codec = "mp3"

            pp_dict: dict[str, Any] = {
                "key": "FFmpegExtractAudio",
                "preferredcodec": target_codec,
            }
            if target_codec == "mp3":
                bitrate = (
                    opts.audio_quality.replace("k", "").strip() if opts.audio_quality else "320"
                )
                pp_dict["preferredquality"] = (
                    bitrate if bitrate in ("128", "192", "256", "320") else "320"
                )

            ydl_opts["postprocessors"] = [pp_dict]
        else:
            # Video quality options
            quality_target = opts.video_quality.lower()
            if quality_target == "worst":
                format_str = "worstvideo+worstaudio/worst"
            else:
                quality_target = {"4k": "2160p", "2k": "1440p"}.get(quality_target, quality_target)
                match = re.fullmatch(r"([1-9][0-9]{1,3})p", quality_target)
                limit = f"[height<={match[1]}]" if match else ""
                format_str = f"bestvideo{limit}+bestaudio/best{limit}"

            ydl_opts["format"] = format_str
            target_container = (
                opts.video_format if opts.video_format in ("mp4", "mkv", "webm") else "mp4"
            )
            ydl_opts["merge_output_format"] = target_container
            ydl_opts.setdefault("postprocessors", []).append(
                {"key": "FFmpegVideoRemuxer", "preferedformat": target_container}
            )
            if target_container == "webm":
                ydl_opts["format"] = (
                    format_str.replace("bestvideo", "bestvideo[ext=webm]")
                    .replace("bestaudio", "bestaudio[ext=webm]")
                    .replace("/best", "/best[ext=webm]")
                )

        # Metadata embedding
        if opts.embed_metadata:
            ydl_opts.setdefault("postprocessors", []).append({"key": "FFmpegMetadata"})
        # WAV format does not support embedding cover art via EmbedThumbnail
        if opts.embed_thumbnail and opts.media_type == "audio" and target_codec != "wav":
            ydl_opts["writethumbnail"] = True
            ydl_opts.setdefault("postprocessors", []).extend(
                [
                    {"key": "FFmpegThumbnailsConvertor", "format": "jpg"},
                    {"key": "EmbedThumbnail"},
                ]
            )

        # Subtitles (validate lang code)
        if opts.subtitle_lang and re.fullmatch(
            r"[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]{2,8})*", opts.subtitle_lang
        ):
            ydl_opts["writesubtitles"] = True
            ydl_opts["subtitleslangs"] = [opts.subtitle_lang]
            ydl_opts["writeautomaticsub"] = True
            ydl_opts.setdefault("postprocessors", []).append({"key": "FFmpegEmbedSubtitle"})

        # Playlist items
        if opts.playlist_indices:
            # Clean and bound playlist items
            safe_indices = [int(i) for i in opts.playlist_indices if 1 <= int(i) <= 1000][:250]
            if safe_indices:
                ydl_opts["playlist_items"] = ",".join(str(idx) for idx in safe_indices)

        last_size_check = 0.0

        def progress_hook(d: dict[str, Any]) -> None:
            if task._cancel_requested:
                raise RuntimeError("Download cancelled by user.")

            nonlocal last_size_check
            now = time.monotonic()
            if now - last_size_check >= 1:
                last_size_check = now
                total_on_disk = sum(f.stat().st_size for f in out_dir.iterdir() if f.is_file())
                if total_on_disk > 2 * 1024**3 or shutil.disk_usage(out_dir).free < 200 * 1024**2:
                    raise RuntimeError("Download exceeded disk storage limits.")
            status = d.get("status")
            if status == "downloading":
                raw_percent = d.get("_percent_str", "0%").replace("%", "").strip()
                try:
                    percent = max(0.0, min(100.0, float(raw_percent)))
                except ValueError:
                    percent = 0.0
                speed = d.get("_speed_str", "Calculating...")
                eta = d.get("_eta_str", "00:00")
                task.update_progress(
                    status="downloading",
                    percent=percent,
                    speed=speed,
                    eta=eta,
                    downloaded_bytes=d.get("downloaded_bytes", 0),
                    total_bytes=d.get("total_bytes") or d.get("total_bytes_estimate") or 0,
                    detail=f"Downloading: {percent:.1f}% ({speed}) - ETA: {eta}",
                )
            elif status == "finished":
                task.update_progress(
                    status="converting", percent=99.0, detail="Conversion via FFmpeg..."
                )

        ydl_opts["progress_hooks"] = [progress_hook]

        # Execute download with yt_dlp
        with web_ydl(ydl_opts, use_cookies=opts.use_cookies) as ydl:
            retcode = ydl.download([opts.url])

        if task._cancel_requested:
            return

        if retcode != 0:
            raise RuntimeError(f"yt-dlp exit code: {retcode}")

        generated_files = [
            f for f in out_dir.iterdir() if f.is_file() and not f.name.endswith((".part", ".ytdl"))
        ]
        if not generated_files:
            raise FileNotFoundError("No converted file was found.")

        # Filter media files vs auxiliary files (like stray thumbnail images)
        media_extensions = {".mp3", ".m4a", ".flac", ".wav", ".opus", ".mp4", ".mkv", ".webm"}
        media_files = [f for f in generated_files if f.suffix.lower() in media_extensions]
        if not media_files:
            raise FileNotFoundError("No converted media file was found.")
        if sum(f.stat().st_size for f in media_files) > 2 * 1024**3:
            raise RuntimeError("Processed output exceeded disk storage limits.")
        files_to_serve = media_files
        if trim_start_sec is not None or trim_end_sec is not None:
            for media_file in files_to_serve:
                self._trim_local_file(task, media_file, trim_start_sec or 0, trim_end_sec)
        if sum(f.stat().st_size for f in files_to_serve) > 2 * 1024**3:
            raise RuntimeError("Processed output exceeded disk storage limits.")

        # If multiple media files were downloaded (e.g. playlist batch), bundle into a zip
        if len(files_to_serve) > 1:
            zip_name = "StreamFab_Playlist.zip"
            zip_path = out_dir / zip_name
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as zf:
                for f in files_to_serve:
                    zf.write(f, arcname=f.name)
            target_file = zip_path
        else:
            target_file = files_to_serve[0]

        with task._notification_lock:
            if task._cancel_requested:
                return
            # A persistent completion record avoids exposing partial outputs after restart.
            marker = out_dir / "completed.json"
            temporary_marker = out_dir / "completed.json.tmp"
            temporary_marker.write_text(
                json.dumps({"filename": target_file.name}), encoding="utf-8"
            )
            os.replace(temporary_marker, marker)
            safe_name = sanitize_filename(target_file.name)
            task.progress.status = "completed"
            task.progress.percent = 100.0
            task.progress.filename = safe_name
            task.progress.file_path = str(target_file)
            task.progress.file_size = target_file.stat().st_size
            mb_size = task.progress.file_size / (1024 * 1024)
            task.progress.detail = f"Completed! File ready ({mb_size:.2f} MB)."
            task.notify_subscribers()

    def _trim_local_file(self, task, media_file, start, end):
        """Trim downloaded media locally, never sending an untrusted URL to FFmpeg."""
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-protocol_whitelist",
                "file,pipe",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(media_file),
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        try:
            duration = float(json.loads(probe.stdout)["format"]["duration"])
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError("Cannot determine media duration for trimming.") from exc
        if not math.isfinite(duration) or start >= duration:
            raise ValueError("Trim range is outside the media duration.")
        output = media_file.with_name("trimmed-" + media_file.name)
        args = [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-protocol_whitelist",
            "file,pipe",
            "-ss",
            str(start),
            "-i",
            str(media_file),
        ]
        if end is not None:
            args += ["-t", str(end - start)]
        args += ["-map", "0", "-map_metadata", "0", "-c:s", "copy"]
        if media_file.suffix.lower() == ".mp3":
            bitrate = task.options.audio_quality
            args += [
                "-c:a",
                "libmp3lame",
                "-b:a",
                bitrate if bitrate != "best" else "320k",
                "-c:v",
                "copy",
            ]
        args += [str(output)]
        try:
            with tempfile.TemporaryFile() as errors:
                with subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=errors) as proc:
                    deadline = time.monotonic() + 600
                    while proc.poll() is None:
                        if task._cancel_requested or time.monotonic() > deadline:
                            proc.kill()
                            proc.wait()
                            raise RuntimeError("Media trimming cancelled or timed out.")
                        time.sleep(0.1)
                    if proc.returncode:
                        raise RuntimeError("FFmpeg could not trim the downloaded media.")
            os.replace(output, media_file)
        finally:
            output.unlink(missing_ok=True)


def resolve_stream_urls(
    url: str,
    media_type: str = "audio",
    video_quality: str = "best",
    video_format: str = "mp4",
    audio_format: str = "mp3",
    use_cookies: bool = True,
) -> dict[str, Any]:
    """Resolve direct CDN stream URLs for zero-server-CPU client-side processing."""
    safe_url = validate_and_sanitize_url(url)
    ydl_opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "ignoreconfig": True,
        "no_exec": True,
        "socket_timeout": 15,
    }

    with web_ydl(ydl_opts, use_cookies=use_cookies) as ydl:
        info = ydl.extract_info(safe_url, download=False)

    if not info:
        raise ValueError("Could not extract stream URLs.")

    title = info.get("title", "Media")
    uploader = info.get("uploader") or info.get("channel") or ""
    duration = info.get("duration", 0)
    thumbnail = info.get("thumbnail")
    formats = info.get("formats") or []

    # 1. Best audio-only stream
    audio_formats = [
        f
        for f in formats
        if f.get("url") and f.get("acodec") not in (None, "none") and f.get("vcodec") == "none"
    ]
    best_audio = None
    if audio_formats:
        best_audio = max(audio_formats, key=lambda f: f.get("abr") or f.get("tbr") or 0)
    else:
        # Fallback to any format with audio
        for f in reversed(formats):
            if f.get("url") and f.get("acodec") not in (None, "none"):
                best_audio = f
                break

    # 2. Video streams
    target_height = 1080
    if video_quality in ("2160p", "4k"):
        target_height = 2160
    elif video_quality in ("1440p", "2k"):
        target_height = 1440
    elif video_quality == "1080p":
        target_height = 1080
    elif video_quality == "720p":
        target_height = 720
    elif video_quality == "480p":
        target_height = 480
    elif video_quality == "360p":
        target_height = 360
    elif video_quality == "worst":
        target_height = 144
    elif video_quality == "best":
        target_height = 4320

    quality_match = re.fullmatch(r"([1-9][0-9]{1,3})p", video_quality)
    if quality_match:
        target_height = int(quality_match[1])
    best_video = None
    combined_stream = None

    for f in formats:
        if f.get("url") and f.get("vcodec") not in (None, "none"):
            h = f.get("height") or 0
            if video_quality == "worst" or video_quality == "best" or h <= target_height:
                if not best_video or (
                    h < (best_video.get("height") or 0)
                    if video_quality == "worst"
                    else h > (best_video.get("height") or 0)
                ):
                    best_video = f
            if f.get("acodec") not in (None, "none") and (
                video_quality in ("best", "worst") or h <= target_height
            ):
                if not combined_stream or (
                    h < (combined_stream.get("height") or 0)
                    if video_quality == "worst"
                    else h > (combined_stream.get("height") or 0)
                ):
                    combined_stream = f

    return {
        "title": title,
        "uploader": uploader,
        "duration": duration,
        "duration_formatted": format_duration(duration),
        "thumbnail": thumbnail,
        "media_type": media_type,
        "audio_stream_url": best_audio.get("url") if best_audio else None,
        "audio_codec": best_audio.get("acodec") if best_audio else "unknown",
        "audio_ext": best_audio.get("ext") if best_audio else "m4a",
        "video_stream_url": best_video.get("url") if best_video else None,
        "video_codec": best_video.get("vcodec") if best_video else "unknown",
        "video_ext": best_video.get("ext") if best_video else "mp4",
        "video_height": best_video.get("height") if best_video else target_height,
        "combined_ext": combined_stream.get("ext") if combined_stream else None,
        "combined_height": combined_stream.get("height") if combined_stream else None,
        "combined_stream_url": combined_stream.get("url") if combined_stream else None,
        "has_combined_stream": combined_stream is not None,
    }


engine = EngineManager()
