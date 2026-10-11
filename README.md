# StreamFab &mdash; Modern Media Downloader &amp; Converter (NoTube Alternative)

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688.svg)](https://fastapi.tiangolo.com/)
[![yt--dlp](https://img.shields.io/badge/yt--dlp-2024%2B-red.svg)](https://github.com/yt-dlp/yt-dlp)
[![Tests](https://img.shields.io/badge/Tests-91%20passed-brightgreen.svg)]()
[![License](https://img.shields.io/badge/License-MIT-green.svg)]()

> A high-performance, ad-free, privacy-friendly video & audio converter and downloader. Designed to completely outclass legacy web converters like **NoTube** with client-side in-browser computing (0% server CPU load), turbo multi-fragment downloads, lossless audio (FLAC/MP3 320k), 4K 60fps video, interactive trimming, playlist batching, and real-time SSE progress tracking. Available both as a modern Web App and a versatile CLI.

---

## ⚡ StreamFab vs NoTube Comparison

| Evaluation Metric | NoTube & Legacy Converters | StreamFab PRO (Our Engine) |
|---|---|---|
| **Server CPU Load** | 🚨 100% CPU bottleneck (converts on server) | ⚡ **0% Server CPU (In-Browser Client Compute)** |
| **Ads & Popups** | 🚨 Intrusive, deceptive redirects, malware risks | 🛡️ **0 Ads, 0 Trackers, 100% Clean** |
| **Max Video Resolution** | 🔒 Often capped at 720p or compressed 1080p | 💎 **True 4K 60fps & 2K QHD Lossless** |
| **Audio Quality** | ⚠️ Standard compressed MP3 (128-192 kbps) | 🎧 **MP3 320 kbps HD, Lossless FLAC, Studio WAV** |
| **Built-in Trimmer (Trim & Cut)** | ❌ Missing (forces full video download) | ✂️ **Precise down-to-the-second trimming** |
| **Playlists & Batch Downloads** | ❌ 1-by-1 manual or paywalled | 📋 **Full playlists with individual video selection** |
| **Processing Speed** | 🐢 Overcrowded, slow server queues | ⚡ **Client GPU/AudioContext Hardware Acceleration** |
| **In-App Media Player** | ❌ No preview available before conversion | 🎬 **Built-in audio/video player in the Web App** |
| **Subtitles & Metadata** | ❌ Not supported | 📝 **Multi-language subtitles & ID3 tags + HD cover art** |

---

## 🌐 In-Browser Client Compute (Zero Server CPU Load)

Unlike NoTube and legacy converters where thousands of users cause heavy server CPU spikes from video transcoding and audio encoding, StreamFab offloads **100% of compute-heavy tasks directly to the client's browser**:

- **Web Audio API**: Hardware-accelerated in-browser audio decoding into Float32 PCM sample buffers.
- **Sample-Accurate Trimming**: Sub-millisecond slice precision directly in browser memory without FFmpeg container overhead.
- **In-Browser MP3 Encoder (`lamejs`)**: Multi-bitrate encoding (128k to 320k) performed entirely by client threads.
- **Pure JavaScript ID3v2.3 Tagger**: Injects ID3 metadata and embedded high-resolution JPEG cover art in browser memory.
- **Zero-Copy Streaming Proxy (`/api/proxy-stream`)**: Asynchronous, zero-copy byte stream pass-through with HTTP Range support (`206 Partial Content`) that prevents browser CORS issues while maintaining 0% server CPU utilization and 0 bytes server disk usage.

---

## 🚀 Quick Start

### 1. Requirements

- Python 3.10 or higher
- `ffmpeg` installed and available in PATH (Ubuntu: `sudo apt install ffmpeg`, macOS: `brew install ffmpeg`, Windows: `winget install Gyan.FFmpeg` or official binary)

### 2. Installation

```bash
git clone https://github.com/Cylae/streamfab.git
cd streamfab
pip install -r requirements.txt
```

### 3. Launch the Web Interface (NoTube Alternative)

```bash
# Launch on http://127.0.0.1:8000
python src/downloader.py --web

# Or with custom port and auto-opening browser:
python src/downloader.py --web --port 8080 --open-browser

# On Windows (Desktop 1-click launcher):
StreamFab.bat
```

Then open your browser at **http://127.0.0.1:8000/**.

---

## 💻 CLI Usage

StreamFab can also be operated as a powerful command-line tool with zero configuration:

```bash
python src/downloader.py [options] [URL]
```

### CLI Examples

**Download a video in Best Quality (up to 4K):**
```bash
python src/downloader.py "https://www.youtube.com/watch?v=BaW_jenozKc"
```

**Extract Ultra HD Audio (MP3 320kbps):**
```bash
python src/downloader.py --extract-audio "https://www.youtube.com/watch?v=BaW_jenozKc"
```

**Download only a specific clip (Trimming):**
```bash
python src/downloader.py --trim-start "00:01:30" --trim-end "00:02:45" "https://www.youtube.com/watch?v=BaW_jenozKc"
```

**Download with embedded subtitles and metadata:**
```bash
python src/downloader.py --subtitles --embed-metadata --embed-thumbnail "https://www.youtube.com/watch?v=BaW_jenozKc"
```

**Download batch URLs from a file:**
```bash
python src/downloader.py -a urls.txt
```

### Complete CLI Options

| Argument | Description | Default |
|---|---|---|
| `url` | URL of the media or playlist to download | None |
| `-a`, `--batch-file` | File containing multiple URLs (one per line) | None |
| `-f`, `--format` | Output container format (`mp4`, `mkv`, `best`) | `best` |
| `-q`, `--quality` | Video quality target (`best`, `1080p`, `720p`, `480p`, `worst`) | `best` |
| `--extract-audio` | Extract audio only and convert to MP3 | False |
| `--trim-start` | Start timestamp for trimming (e.g. `00:01:30`) | None |
| `--trim-end` | End timestamp for trimming (e.g. `00:02:45`) | None |
| `--subtitles` | Download and embed available subtitles | False |
| `--no-playlist` | Download single video if part of playlist | False |
| `--embed-metadata` | Embed ID3 tags, title, artist, uploader | False |
| `--embed-thumbnail` | Embed high-resolution cover art | False |
| `--list-formats` | List all available stream formats without downloading | False |
| `--max-retries` | Number of retries on transient network errors | 3 |
| `--web` | Launch the modern StreamFab Web App | False |
| `--port` | Port for the web server | 8000 |
| `--host` | Host address for the web server | 127.0.0.1 |
| `--open-browser` | Open web browser automatically | False |

---

## 🌐 REST & SSE API Reference

StreamFab includes an asynchronous FastAPI backend:

| Endpoint | Method | Description |
|---|---|---|
| `/` | `GET` | Serves the responsive SPA web frontend |
| `/api/health` | `GET` | Health check endpoint returning service status |
| `/api/info` | `POST` | Instant media analysis (title, uploader, thumbnail, formats, subtitles, playlist items) |
| `/api/stream-urls` | `POST` | Resolves direct CDN stream URLs for zero-server-CPU client-side processing |
| `/api/proxy-stream` | `GET` | Zero-CPU asynchronous stream pass-through with Range support for browser clients |
| `/api/download` | `POST` | Dispatches background conversion task with turbo multi-fragment engine |
| `/api/progress/{task_id}` | `GET` | Server-Sent Events (SSE) streaming real-time progress (% %, speed, ETA, status) |
| `/api/file/{task_id}` | `GET` | Downloads the converted file with resume support and safe path validation |
| `/api/cancel/{task_id}` | `POST` | Cancels an ongoing task cleanly |

### API Example: Start Conversion

```bash
curl -X POST "http://127.0.0.1:8000/api/download" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.youtube.com/watch?v=BaW_jenozKc",
    "media_type": "audio",
    "audio_format": "mp3",
    "audio_quality": "320k",
    "trim_start": "00:00:30",
    "trim_end": "00:01:30"
  }'
```

Response:
```json
{
  "success": true,
  "task_id": "7f8b9d3e-4b6a-4d92-91ea-0d7281f62b11",
  "status": "downloading"
}
```

---

## 🚀 Production Deployment

StreamFab is production-ready for single-instance VPS, Docker clusters, and cloud container platforms. For comprehensive step-by-step instructions, see the complete [Deployment Guide (DEPLOYMENT.md)](DEPLOYMENT.md).

### Quick Deployment via Docker Compose

```bash
# 1. Clone repository
git clone https://github.com/Cylae/streamfab.git
cd streamfab

# 2. Start container in background
docker compose up -d --build

# 3. Check health status
curl -i http://localhost:8000/api/health
```

### Production Linux VPS (Systemd + Nginx)

1. **Systemd Service**: Deploy the pre-configured [streamfab.service](deployment/streamfab.service) into `/etc/systemd/system/`.
2. **Reverse Proxy**: Use the battle-tested [nginx.conf](deployment/nginx.conf) with unbuffered SSE and byte-range streaming proxy configurations.
3. **SSL/TLS**: Enable automated HTTPS with Let's Encrypt Certbot (`certbot --nginx -d yourdomain.com`).

Detailed deployment instructions for **Docker**, **Ubuntu/Debian Systemd**, **Nginx/Caddy**, **Railway**, **Render**, **Fly.io**, **AWS EC2**, and **DigitalOcean** are available in [DEPLOYMENT.md](DEPLOYMENT.md).

---

## 🧪 Testing

Execute the test suite with `pytest`:

```bash
pytest
```

Run test suite with coverage report:

```bash
pytest --cov=src --cov-report=term-missing
```

The test suite covers:
- CLI argument parsing, defaults, batch files, errors, format listing, retry backoff heuristics
- Engine metadata caching, duration formatting, timestamp parsing, error classification
- Concurrent fragment options, FFmpeg trimming postprocessor arguments, cancellation safety
- Web API endpoints (`/api/health`, `/api/info`, `/api/download`, `/api/file`, `/api/progress`, path traversal defenses)

---

## 🏛️ Architecture & Design Decisions (ADRs)

1. **ADR-001: Server-Sent Events (SSE) over WebSockets**
   - *Context:* Need real-time progress streaming for progress bars, download speed, and ETA.
   - *Decision:* Use SSE (`text/event-stream` via FastAPI `StreamingResponse`) instead of WebSockets.
   - *Reason:* SSE is native in all modern browsers (`EventSource`), firewall and proxy-friendly, auto-reconnecting, HTTP/2 multiplexed, and requires no external WebSocket state or handshakes.

2. **ADR-002: In-Memory Metadata Caching with TTL**
   - *Context:* Users frequently toggle between audio and video or adjust trimming timestamps for the same URL.
   - *Decision:* Implement bounded in-memory caching with a 5-minute TTL.
   - *Reason:* Eliminates redundant network queries to YouTube/TikTok APIs, providing instantaneous format updates and trimming changes.

3. **ADR-003: UUID-Isolated Task Storage & Path Traversal Immunity**
   - *Context:* Web applications downloading files to disk must be immune to directory traversal.
   - *Decision:* Every task is strictly keyed by a standard UUIDv4 and isolated in `DOWNLOADS_DIR / <uuid>`.
   - *Reason:* User input can never control storage directories or file paths. `/api/file/{task_id}` enforces `is_relative_to(expected_dir)`.

4. **ADR-004: Dual-Engine Architecture (CLI & Web Share Same Core)**
   - *Context:* Both the command-line interface and the web interface need high-performance downloading and conversion.
   - *Decision:* Centralize download logic, options building, and error diagnosis in `engine.py`, leaving `downloader.py` and `web_server.py` as clean client adapters.
   - *Reason:* Zero duplicated logic, unified error classification, and 100% backward compatibility with existing workflows.

---

## ⚖️ Legal Disclaimer

This software is intended solely for downloading publicly available, non-DRM protected content for personal, archival, or educational use. It does not circumvent Digital Rights Management (DRM) or technical protection measures. Users are responsible for complying with the Terms of Service of content platforms and local copyright regulations.
