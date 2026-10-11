# StreamFab

A Python CLI and self-hosted web interface for downloading and converting media with yt-dlp and FFmpeg. The interface supports light/dark themes, media analysis, audio/video format selection, trimming, playlists, subtitles, and SSE progress.

This is a **single-user application**. Place remote deployments behind authentication and HTTPS. It does not implement separate user accounts or isolated credentials for multiple tenants.

## Quick start

Requirements: Python 3.10+, FFmpeg/ffprobe on PATH. Node.js 24+ is needed only for JavaScript tests.

```bash
git clone https://github.com/Cylae/streamfab.git
cd streamfab
python -m venv .venv
# Linux/macOS:
. .venv/bin/activate
# Windows PowerShell instead:
# .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.lock
python src/downloader.py --web --open-browser
```

Open `http://127.0.0.1:8000`. On Windows, `StreamFab.bat` creates a virtual environment, installs the locked dependencies, and opens the interface after the server starts.

## Processing modes

| Capability | Browser mode | Server mode |
|---|---|---|
| Audio formats | MP3 and WAV, subject to browser decoding support | MP3, M4A, FLAC, WAV, Opus |
| Video | Existing combined MP4 with matching quality; no remuxing | MP4, MKV, WebM with compatible source codecs |
| Trimming | Audio samples | Downloads the media, then trims locally using FFmpeg |
| Metadata | ID3v2.3 Unicode tags and JPEG/PNG cover art for MP3 | FFmpeg metadata and supported cover art |
| Playlists/subtitles | Routes to server mode | Up to 250 selected entries; manual or automatic subtitles |
| Resources | Browser CPU/RAM plus server extraction and bandwidth | Server CPU, RAM, disk and bandwidth |

Unsupported browser operations fall back to the server. Browser stream buffering is limited to 128 MiB; decoded audio can consume considerably more memory. Selecting a high bitrate or converting compressed audio to FLAC does not restore information missing from the source. Maximum resolution and site compatibility depend on the original media and yt-dlp.

The web engine allows only public HTTP/HTTPS destinations on ports 80/443. It checks redirects and resolved addresses at connection time. External network downloaders, FTP and RTSP are disabled in web mode. This may exclude some streams that the locally operated CLI supports. HTTP proxy environment variables are deliberately ignored by web media transports.

## CLI

```bash
python src/downloader.py --help
python src/downloader.py "https://www.youtube.com/watch?v=BaW_jenozKc"
python src/downloader.py --extract-audio --embed-metadata "https://www.youtube.com/watch?v=BaW_jenozKc"
python src/downloader.py -f mp4 -q 1080p --no-playlist "https://www.youtube.com/watch?v=BaW_jenozKc"
python src/downloader.py --trim-start 00:01:30 --trim-end 00:02:45 "https://www.youtube.com/watch?v=BaW_jenozKc"
python src/downloader.py -a urls.txt
python src/downloader.py --cookies /path/to/cookies.txt "https://www.youtube.com/watch?v=BaW_jenozKc"
```

CLI MP3 output uses 192 kbps by default; the web interface defaults to 320 kbps. Batch files are UTF-8, one URL per line; blank lines and `#` comments are ignored. CLI trimming uses yt-dlp download ranges and may use FFmpeg network downloading; run the CLI only with URLs you trust.

## Cookies and credentials

Session cookies grant access to an account. Upload them only to an instance you control. Netscape cookie syntax is validated before atomic replacement; files use private permissions on POSIX systems. The application creates a separate temporary cookie jar for each extraction/download and never serves the cookie contents through the API.

Cookie administration is restricted to loopback clients unless `STREAMFAB_ADMIN_TOKEN` is configured. When configured, use `Authorization: Bearer <token>` even locally. The Cookie Assistant has a token input; the token stays in memory. If a cookie file is installed, remote media analysis/download/proxy requests also require that authorization, so anonymous callers cannot borrow the owner's session. File/progress/cancel URLs use an unguessable task UUID as a capability; keep these URLs private.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `STREAMFAB_HOST` | `127.0.0.1` | CLI web bind address |
| `STREAMFAB_PORT` | `8000` | Web port |
| `STREAMFAB_STORAGE_DIR` | OS temp directory + `/streamfab_downloads` | Isolated task outputs |
| `STREAMFAB_DOWNLOADS_DIR` | unset | Storage fallback alias |
| `STREAMFAB_COOKIES_FILE` | Project `cookies.txt` fallback | Cookie storage path |
| `STREAMFAB_ADMIN_TOKEN` | unset | Cookie/session administration token |
| `STREAMFAB_TRUSTED_HOSTS` | `localhost,127.0.0.1,[::1]` | Comma-separated accepted HTTP hostnames |
| `STREAMFAB_LOG_LEVEL` | `info` | Uvicorn logging level |

Limits: 3 concurrent downloads, 4 metadata extractions, 16 proxy streams, 100 retained tasks, 100 metadata cache entries, and 3 MiB request bodies. Download progress enforces a 2 GiB task disk budget and checks free disk space. These checks are not filesystem quotas; conversion and temporary files can exceed the budget between checks. Use container and filesystem resource limits for remote deployments. Completed/error/cancelled tasks expire after one hour; active workers are retained. Outputs survive process restart only when an atomic completion record exists. Periodic cleanup runs every minute while the server is running.

Run **one Uvicorn worker**. Task state and rate limits are in memory and are not shared between processes.

## API

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/health` | Health and active task count |
| POST | `/api/info` | Metadata and format analysis |
| POST | `/api/stream-urls` | Browser stream resolution |
| GET | `/api/proxy-stream?url=...` | Checked raw media passthrough; single byte-range support |
| POST | `/api/download` | Create task |
| GET | `/api/progress/{task_id}` | SSE progress |
| GET | `/api/file/{task_id}` | Completed file delivery |
| POST | `/api/cancel/{task_id}` | Cooperative cancellation |
| GET/POST/DELETE | `/api/cookies` | Authorized cookie status/upload/removal |

Cancellation interrupts progress hooks and local trimming. A blocking extractor or yt-dlp postprocessor may finish its current operation before cancellation takes effect. Cross-origin API calls are rejected; the frontend is served by the same instance.

## Development and verification

```bash
python -m pip install -r requirements-dev.txt
python -m ruff check src tests
python -m ruff format --check src tests
python -m pytest --cov=src --cov-report=term-missing
npm ci
npm test
python -m pip_audit -r requirements.lock
npm audit
```

Tests isolate storage, cookies, DNS and background downloads. They include guarded transport integration with a synthetic HTTP server, real FFmpeg audio/video fixtures where FFmpeg is available, and DOM regressions for unsafe metadata and cancellation. Tests do not claim every live platform works. See [AUDIT.md](AUDIT.md) for findings, validation evidence and limitations; see [DEPLOYMENT.md](DEPLOYMENT.md) for installation on a server.

Dependencies are pinned. The public-network transport adapter uses internal yt-dlp/httpcore APIs: rerun transport tests before updating them. To refresh the complete runtime lock in a clean virtual environment, install reviewed direct requirements, run `python -m pip freeze > requirements.lock`, audit the result, and rerun the suite. Do not schedule unattended dependency upgrades.

## Third-party software

Browser MP3 encoding uses [lamejs](https://github.com/zhuker/lamejs) and [LAME](https://lame.sourceforge.io/), subject to their LGPL terms. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). yt-dlp, FFmpeg and Python dependencies retain their own licenses. This repository previously advertised an MIT license without including a project license file; that badge has been removed rather than assuming licensing authority.
