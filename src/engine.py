"""StreamFab Engine - High-performance Media Extraction and Conversion Engine.

Provides blazing-fast metadata extraction, concurrent fragment downloads,
FFmpeg-accelerated conversion, time-based trimming, subtitle handling,
and real-time event-driven progress tracking.
Hardened against SSRF, command injection, path traversal, and resource exhaustion.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import yt_dlp
from yt_dlp.utils import download_range_func
from security import (
    sanitize_filename,
    validate_and_sanitize_url,
    validate_timestamp_strict,
)

# Output directory for processed files
DOWNLOADS_DIR = Path(os.getenv("STREAMFAB_STORAGE_DIR", tempfile.gettempdir())) / "streamfab_downloads"
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

# In-memory metadata cache (URL -> (timestamp, info_dict))
_METADATA_CACHE: Dict[str, tuple[float, Dict[str, Any]]] = {}
CACHE_TTL_SECONDS = 300  # 5 minutes
TASK_RETENTION_SECONDS = 3600  # 1 hour auto-cleanup
MAX_CONCURRENT_DOWNLOADS = 3  # Protect server resources against DoS


def format_duration(seconds: Optional[float | int]) -> str:
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


def parse_timestamp(timestamp_str: Optional[str]) -> Optional[float]:
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


def get_cookiefile_opt() -> Optional[str]:
    """Return path to cookie file if configured or present in project root."""
    custom_cookie = os.getenv("STREAMFAB_COOKIES_FILE")
    if custom_cookie and Path(custom_cookie).is_file():
        return str(Path(custom_cookie).resolve())
    for candidate in [
        Path.cwd() / "cookies.txt",
        Path(__file__).resolve().parent.parent / "cookies.txt",
        Path(__file__).resolve().parent / "cookies.txt",
    ]:
        if candidate.is_file():
            return str(candidate.resolve())
    return None


def classify_engine_error(exc: Exception) -> str:
    """Provide clean, human-friendly error diagnosis in English without leaking system internals."""
    msg = str(exc).lower()
    if "ssrf" in msg or "local or private" in msg or ("forbidden" in msg and "ip" in msg):
        return "Security check blocked request: unauthorized destination."
    if "confirm you’re not a bot" in msg or "confirm you're not a bot" in msg or ("bot" in msg and ("sign in" in msg or "cookies" in msg)):
        return (
            "YouTube anti-bot verification triggered ('Sign in to confirm you’re not a bot'). "
            "YouTube requires session verification for this connection. Place a cookies.txt file in the project folder to authenticate."
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
    return f"An error occurred during extraction or download: {str(exc)}"


def get_cached_metadata(url: str) -> Optional[Dict[str, Any]]:
    """Return cached metadata if still valid."""
    entry = _METADATA_CACHE.get(url)
    if entry:
        cached_time, data = entry
        if time.time() - cached_time < CACHE_TTL_SECONDS:
            return data
    return None


def set_cached_metadata(url: str, data: Dict[str, Any]) -> None:
    """Cache metadata for the given URL, bounding cache size."""
    now = time.time()
    if len(_METADATA_CACHE) > 100:
        expired = [k for k, (t, _) in _METADATA_CACHE.items() if now - t >= CACHE_TTL_SECONDS]
        for k in expired:
            _METADATA_CACHE.pop(k, None)
    _METADATA_CACHE[url] = (now, data)


def extract_media_info(url: str, fast_mode: bool = True) -> Dict[str, Any]:
    """Extract metadata, formats, preview streams, and subtitle tracks safely."""
    # Enforce strict URL validation & anti-SSRF checks
    safe_url = validate_and_sanitize_url(url)

    cached = get_cached_metadata(safe_url)
    if cached:
        return cached

    ydl_opts: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist" if fast_mode else False,
        "ignoreconfig": True,
        "no_exec": True,
        "socket_timeout": 15,
    }
    cookie_file = get_cookiefile_opt()
    if cookie_file:
        ydl_opts["cookiefile"] = cookie_file

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
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
        valid_thumbs = [t for t in thumbnails if t.get("url") and t.get("url", "").startswith(("http://", "https://"))]
        if valid_thumbs:
            best_thumb = valid_thumbs[-1]["url"]

    # Direct preview stream URL if accessible
    preview_url = None
    formats = info.get("formats") or []
    for fmt in reversed(formats):
        if fmt.get("url") and fmt.get("url", "").startswith(("http://", "https://")):
            if fmt.get("vcodec") != "none" and fmt.get("acodec") != "none" and fmt.get("height", 0) <= 720:
                preview_url = fmt["url"]
                break
            elif not preview_url and fmt.get("acodec") != "none":
                preview_url = fmt["url"]

    result: Dict[str, Any] = {
        "url": safe_url,
        "is_playlist": is_playlist,
        "id": info.get("id", ""),
        "title": info.get("title", "Untitled Media"),
        "uploader": info.get("uploader") or info.get("channel") or info.get("uploader_id") or "Unknown Creator",
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
        for idx, entry in enumerate(raw_entries[:250]):  # Cap at 250 entries to prevent memory exhaustion
            if not entry:
                continue
            entry_thumbs = entry.get("thumbnails") or []
            entry_thumb = entry.get("thumbnail") or (entry_thumbs[-1]["url"] if entry_thumbs else result["thumbnail"])
            entries.append({
                "index": idx + 1,
                "id": entry.get("id"),
                "title": entry.get("title", f"Track {idx + 1}"),
                "uploader": entry.get("uploader") or entry.get("channel") or result["uploader"],
                "duration": entry.get("duration"),
                "duration_formatted": format_duration(entry.get("duration")),
                "thumbnail": entry_thumb,
                "url": entry.get("url") or entry.get("webpage_url") or f"{safe_url}#{idx+1}",
            })
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
        resolutions_set: Set[int] = set()
        has_audio = False
        for fmt in formats:
            if fmt.get("vcodec") != "none" and fmt.get("height"):
                resolutions_set.add(fmt["height"])
            if fmt.get("acodec") != "none":
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
            available_res.append({"height": max_h, "label": f"{max_h}p (Maximum)", "value": f"{max_h}p"})

        result["available_video_resolutions"] = available_res or [{"height": 1080, "label": "1080p HD (Optimal)", "value": "1080p"}]
        result["has_audio"] = has_audio

        # Inspect subtitles
        subtitles_list = []
        subs = info.get("subtitles") or {}
        auto_subs = info.get("automatic_captions") or {}
        all_sub_keys = set(list(subs.keys()) + list(auto_subs.keys()))
        common_langs = ["fr", "en", "es", "de", "it", "pt", "ru", "ja", "ko", "zh"]
        for lang in sorted(all_sub_keys):
            if lang in common_langs or len(subtitles_list) < 15:
                subtitles_list.append({
                    "code": lang,
                    "name": lang.upper(),
                    "is_auto": lang in auto_subs and lang not in subs
                })
        result["subtitles"] = subtitles_list

    set_cached_metadata(safe_url, result)
    return result


@dataclass
class DownloadOptions:
    url: str
    media_type: str = "audio"  # 'audio' or 'video'
    audio_format: str = "mp3"  # mp3, m4a, flac, wav, opus
    audio_quality: str = "320k"  # 320k, 256k, 192k, 128k, best
    video_format: str = "mp4"  # mp4, mkv, webm
    video_quality: str = "best"  # best, 2160p, 1440p, 1080p, 720p, 480p, 360p
    trim_start: Optional[str] = None  # e.g. "00:01:15"
    trim_end: Optional[str] = None  # e.g. "00:02:45"
    embed_metadata: bool = True
    embed_thumbnail: bool = True
    subtitle_lang: Optional[str] = None  # e.g. "fr", "en"
    playlist_indices: Optional[List[int]] = None  # indices to download if playlist


@dataclass
class TaskProgress:
    status: str = "queued"  # queued, downloading, converting, completed, error, cancelled
    percent: float = 0.0
    speed: str = "0 KiB/s"
    eta: str = "00:00"
    downloaded_bytes: int = 0
    total_bytes: int = 0
    filename: Optional[str] = None
    file_path: Optional[str] = None
    file_size: Optional[int] = None
    download_url: Optional[str] = None
    error_message: Optional[str] = None
    detail: str = "Waiting to start..."


class DownloadTask:
    def __init__(self, task_id: str, options: DownloadOptions):
        self.task_id = task_id
        self.options = options
        self.progress = TaskProgress()
        self.created_at = datetime.now(timezone.utc)
        self.subscribers: List[asyncio.Queue] = []
        self._cancel_requested = False
        self._output_dir = (DOWNLOADS_DIR / task_id).resolve()
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def cancel(self) -> None:
        self._cancel_requested = True
        self.progress.status = "cancelled"
        self.progress.detail = "Download cancelled."
        self.notify_subscribers()

    def add_subscriber(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self.subscribers.append(q)
        q.put_nowait(self.to_dict())
        return q

    def remove_subscriber(self, q: asyncio.Queue) -> None:
        if q in self.subscribers:
            self.subscribers.remove(q)

    def notify_subscribers(self) -> None:
        data = self.to_dict()
        for q in list(self.subscribers):
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                pass

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.progress.status,
            "percent": round(self.progress.percent, 1),
            "speed": self.progress.speed,
            "eta": self.progress.eta,
            "detail": self.progress.detail,
            "filename": self.progress.filename,
            "file_size": self.progress.file_size,
            "download_url": f"/api/file/{self.task_id}" if self.progress.status == "completed" else None,
            "error_message": self.progress.error_message,
        }


class EngineManager:
    """Manages download tasks, throttles concurrency, and cleans up resources."""

    def __init__(self):
        self.tasks: Dict[str, DownloadTask] = {}
        self._concurrency_semaphore: Optional[asyncio.Semaphore] = None

    def _get_semaphore(self) -> asyncio.Semaphore:
        if self._concurrency_semaphore is None:
            self._concurrency_semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
        return self._concurrency_semaphore

    def cleanup_old_tasks(self) -> None:
        """Remove directories and task data older than TASK_RETENTION_SECONDS."""
        now = datetime.now(timezone.utc)
        to_delete = []
        for tid, task in list(self.tasks.items()):
            age = (now - task.created_at).total_seconds()
            if age > TASK_RETENTION_SECONDS:
                to_delete.append(tid)

        for tid in to_delete:
            task = self.tasks.pop(tid, None)
            if task and task._output_dir.exists():
                try:
                    shutil.rmtree(task._output_dir, ignore_errors=True)
                except Exception:
                    pass

    def create_task(self, options: DownloadOptions) -> DownloadTask:
        self.cleanup_old_tasks()
        task_id = str(uuid.uuid4())
        task = DownloadTask(task_id, options)
        self.tasks[task_id] = task
        return task

    def get_task(self, task_id: str) -> Optional[DownloadTask]:
        return self.tasks.get(task_id)

    async def run_task(self, task: DownloadTask) -> None:
        sem = self._get_semaphore()
        async with sem:
            loop = asyncio.get_running_loop()
            try:
                await loop.run_in_executor(None, self._execute_download_sync, task)
            except Exception as exc:
                task.progress.status = "error"
                diagnosis = classify_engine_error(exc)
                task.progress.error_message = diagnosis
                task.progress.detail = f"Error: {diagnosis}"
                task.notify_subscribers()

    def _execute_download_sync(self, task: DownloadTask) -> None:
        opts = task.options
        out_dir = task._output_dir

        # Check available disk space (at least 200MB free) using drive root for Windows safety
        try:
            drive_or_dir = Path(out_dir).anchor or out_dir
            free_space = shutil.disk_usage(drive_or_dir).free
            if free_space < 200 * 1024 * 1024:
                raise RuntimeError("Insufficient disk space on the server.")
        except Exception as e:
            if "insufficient disk space" in str(e).lower():
                raise

        # Enforce strict URL validation & anti-SSRF checks
        safe_url = validate_and_sanitize_url(opts.url)
        opts.url = safe_url

        task.progress.status = "downloading"
        task.progress.detail = "Initializing ultra-fast stream..."
        task.notify_subscribers()

        ydl_opts: Dict[str, Any] = {
            "paths": {"home": str(out_dir)},
            "outtmpl": {"default": "%(title)s.%(ext)s"},
            "windowsfilenames": True,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True if not opts.playlist_indices else False,
            "concurrent_fragment_downloads": 8,  # Turbo multi-threaded downloads
            "retries": 3,
            "fragment_retries": 5,
            "ignoreconfig": True,  # Prevent malicious config file overrides
            "no_exec": True,       # Prevent command injection
            "socket_timeout": 20,
            "max_filesize": 2 * 1024 * 1024 * 1024,  # 2 GB limit per download
        }
        cookie_file = get_cookiefile_opt()
        if cookie_file:
            ydl_opts["cookiefile"] = cookie_file

        # Validate timestamps strictly & configure ultra-efficient segment trimming
        trim_start_sec = validate_timestamp_strict(opts.trim_start) if opts.trim_start else None
        trim_end_sec = validate_timestamp_strict(opts.trim_end) if opts.trim_end else None
        if trim_end_sec is not None:
            if trim_start_sec is not None and trim_end_sec <= trim_start_sec:
                raise ValueError("End time must be greater than start time.")

        if trim_start_sec is not None or trim_end_sec is not None:
            start_val = trim_start_sec if trim_start_sec is not None else 0.0
            end_val = trim_end_sec if trim_end_sec is not None else float("inf")
            ydl_opts["download_ranges"] = download_range_func(None, [(start_val, end_val)])

        # Audio conversion
        if opts.media_type == "audio":
            ydl_opts["format"] = "bestaudio/best"
            target_codec = opts.audio_format.lower()
            if target_codec not in ("mp3", "m4a", "flac", "wav", "opus"):
                target_codec = "mp3"

            pp_dict: Dict[str, Any] = {
                "key": "FFmpegExtractAudio",
                "preferredcodec": target_codec,
            }
            if target_codec == "mp3":
                bitrate = opts.audio_quality.replace("k", "").strip() if opts.audio_quality else "320"
                pp_dict["preferredquality"] = bitrate if bitrate in ("128", "192", "256", "320") else "320"

            ydl_opts["postprocessors"] = [pp_dict]
        else:
            # Video quality options
            quality_target = opts.video_quality.lower()
            if quality_target in ("2160p", "4k"):
                format_str = "bestvideo[height<=2160]+bestaudio/best[height<=2160]"
            elif quality_target in ("1440p", "2k"):
                format_str = "bestvideo[height<=1440]+bestaudio/best[height<=1440]"
            elif quality_target == "1080p":
                format_str = "bestvideo[height<=1080]+bestaudio/best[height<=1080]"
            elif quality_target == "720p":
                format_str = "bestvideo[height<=720]+bestaudio/best[height<=720]"
            elif quality_target == "480p":
                format_str = "bestvideo[height<=480]+bestaudio/best[height<=480]"
            elif quality_target == "360p":
                format_str = "bestvideo[height<=360]+bestaudio/best[height<=360]"
            else:
                format_str = "bestvideo+bestaudio/best"

            ydl_opts["format"] = format_str
            ydl_opts["merge_output_format"] = opts.video_format if opts.video_format in ("mp4", "mkv", "webm") else "mp4"

        # Metadata embedding
        if opts.embed_metadata:
            ydl_opts.setdefault("postprocessors", []).append({"key": "FFmpegMetadata"})
        if opts.embed_thumbnail and opts.media_type == "audio":
            ydl_opts["writethumbnail"] = True
            ydl_opts.setdefault("postprocessors", []).extend([
                {"key": "FFmpegThumbnailsConvertor", "format": "jpg"},
                {"key": "EmbedThumbnail"},
            ])

        # Subtitles (validate lang code)
        if opts.subtitle_lang and re.match(r"^[a-zA-Z]{2,3}(-[a-zA-Z]{2})?$", opts.subtitle_lang):
            ydl_opts["writesubtitles"] = True
            ydl_opts["subtitleslangs"] = [opts.subtitle_lang, "en"]
            ydl_opts.setdefault("postprocessors", []).append({"key": "FFmpegEmbedSubtitle"})

        # Playlist items
        if opts.playlist_indices:
            # Clean and bound playlist items
            safe_indices = [int(i) for i in opts.playlist_indices if 1 <= int(i) <= 1000][:100]
            if safe_indices:
                ydl_opts["playlist_items"] = ",".join(str(idx) for idx in safe_indices)

        def progress_hook(d: Dict[str, Any]) -> None:
            if task._cancel_requested:
                raise Exception("Download cancelled by user.")

            status = d.get("status")
            if status == "downloading":
                task.progress.status = "downloading"
                raw_percent = d.get("_percent_str", "0%").replace("%", "").strip()
                try:
                    task.progress.percent = float(raw_percent)
                except ValueError:
                    task.progress.percent = 0.0

                task.progress.speed = d.get("_speed_str", "Calculating...")
                task.progress.eta = d.get("_eta_str", "00:00")
                task.progress.downloaded_bytes = d.get("downloaded_bytes", 0)
                task.progress.total_bytes = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                task.progress.detail = f"Downloading: {task.progress.percent:.1f}% ({task.progress.speed}) - ETA: {task.progress.eta}"
                task.notify_subscribers()
            elif status == "finished":
                task.progress.status = "converting"
                task.progress.percent = 99.0
                task.progress.detail = "High-quality conversion & finalization via FFmpeg..."
                task.notify_subscribers()

        ydl_opts["progress_hooks"] = [progress_hook]

        # Execute download with yt_dlp
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            retcode = ydl.download([opts.url])

        if task._cancel_requested:
            task.progress.status = "cancelled"
            task.progress.detail = "Download cancelled by user."
            task.notify_subscribers()
            return

        if retcode != 0:
            raise RuntimeError(f"yt-dlp exit code: {retcode}")

        generated_files = [
            f for f in out_dir.iterdir()
            if f.is_file() and not f.name.endswith((".part", ".ytdl"))
        ]
        if not generated_files:
            raise FileNotFoundError("No converted file was found.")

        target_file = max(generated_files, key=lambda f: f.stat().st_size)
        safe_name = sanitize_filename(target_file.name)
        task.progress.status = "completed"
        task.progress.percent = 100.0
        task.progress.filename = safe_name
        task.progress.file_path = str(target_file)
        task.progress.file_size = target_file.stat().st_size
        mb_size = task.progress.file_size / (1024 * 1024)
        task.progress.detail = f"Completed! File ready ({mb_size:.2f} MB)."
        task.notify_subscribers()



def resolve_stream_urls(
    url: str,
    media_type: str = "audio",
    video_quality: str = "best",
    video_format: str = "mp4",
    audio_format: str = "mp3",
) -> Dict[str, Any]:
    """Resolve direct CDN stream URLs for zero-server-CPU client-side processing."""
    safe_url = validate_and_sanitize_url(url)
    ydl_opts: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "ignoreconfig": True,
        "no_exec": True,
        "socket_timeout": 15,
    }
    cookie_file = get_cookiefile_opt()
    if cookie_file:
        ydl_opts["cookiefile"] = cookie_file

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
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
        f for f in formats
        if f.get("url") and f.get("acodec") != "none" and f.get("vcodec") == "none"
    ]
    best_audio = None
    if audio_formats:
        best_audio = max(audio_formats, key=lambda f: f.get("abr") or f.get("tbr") or 0)
    else:
        # Fallback to any format with audio
        for f in reversed(formats):
            if f.get("url") and f.get("acodec") != "none":
                best_audio = f
                break

    # 2. Video streams
    target_height = 1080
    if video_quality == "2160p":
        target_height = 2160
    elif video_quality == "1440p":
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

    best_video = None
    combined_stream = None

    for f in formats:
        if f.get("url") and f.get("vcodec") != "none":
            h = f.get("height") or 0
            if video_quality == "best" or h <= target_height:
                if not best_video or h > (best_video.get("height") or 0):
                    best_video = f
            if f.get("acodec") != "none" and (video_quality == "best" or h <= target_height):
                if not combined_stream or h > (combined_stream.get("height") or 0):
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
        "combined_stream_url": combined_stream.get("url") if combined_stream else None,
        "has_combined_stream": combined_stream is not None,
    }


engine = EngineManager()
