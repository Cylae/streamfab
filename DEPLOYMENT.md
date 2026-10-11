# StreamFab Production Deployment Guide

This guide provides end-to-end instructions for deploying **StreamFab** in production environments, covering Docker containerization, Bare-Metal Linux VPS with Systemd, Reverse Proxies (Nginx & Caddy), Cloud Platforms (Railway, Render, Fly.io, AWS, DigitalOcean), and security hardening.

---

## 📋 Table of Contents

1. [Architecture & Resource Sizing](#1-architecture--resource-sizing)
2. [Prerequisites & FFmpeg Verification](#2-prerequisites--ffmpeg-verification)
3. [Method 1: Docker & Docker Compose (Recommended)](#3-method-1-docker--docker-compose-recommended)
4. [Method 2: Bare-Metal Linux VPS (Systemd)](#4-method-2-bare-metal-linux-vps-systemd)
5. [Reverse Proxy Setup (Nginx & Caddy)](#5-reverse-proxy-setup-nginx--caddy)
6. [Cloud Platform Deployments](#6-cloud-platform-deployments)
   - [Railway](#railway)
   - [Render](#render)
   - [Fly.io](#flyio)
   - [DigitalOcean / AWS EC2](#digitalocean--aws-ec2)
7. [Environment Variables & Configuration](#7-environment-variables--configuration)
8. [Automated Maintenance & yt-dlp Updates](#8-automated-maintenance--yt-dlp-updates)
9. [Production Security Checklist](#9-production-security-checklist)
10. [Health Checks & Troubleshooting](#10-health-checks--troubleshooting)

---

## 1. Architecture & Resource Sizing

StreamFab supports two compute modes that dramatically dictate your server hardware requirements:

| Operational Mode | Processing Location | Server CPU Usage | Server Disk Usage | Recommended VPS Specs |
|---|---|---|---|---|
| **⚡ In-Browser Client Mode (Default)** | User's Browser (Web Audio, lamejs, mp4box) | **~0.0% (Zero Load)** | **0 Bytes** | **1 vCPU, 512 MB RAM** ($4-5/mo) |
| **Cloud Server Mode (Fallback)** | Host Server (FFmpeg multi-thread) | 50% - 100% during encode | Disk space = video size | **2 - 4 vCPUs, 2 - 4 GB RAM** |

> [!TIP]
> Because StreamFab defaults to **Client-Side In-Browser Computing**, a minimal $4/month VPS (1 vCPU / 1GB RAM) can easily serve **thousands of concurrent users** without CPU bottlenecks or disk saturation.

---

## 2. Prerequisites & FFmpeg Verification

StreamFab requires:
- **Python**: 3.10, 3.11, or 3.12
- **FFmpeg**: Compiled with `libmp3lame`, `libx264`, and `libvpx`

### Installing FFmpeg on Linux

```bash
# Ubuntu / Debian
sudo apt update && sudo apt install -y ffmpeg ca-certificates curl

# RHEL / Rocky / Fedora
sudo dnf install -y ffmpeg ca-certificates curl

# Verify FFmpeg installation and codecs
ffmpeg -version
ffmpeg -encoders | grep -E "libmp3lame|libx264"
```

---

## 3. Method 1: Docker & Docker Compose (Recommended)

The easiest and most isolated way to run StreamFab in production is with Docker.

### 3.1 Using Docker Compose

1. Clone repository on your server:
   ```bash
   git clone https://github.com/Cylae/streamfab.git /opt/streamfab
   cd /opt/streamfab
   ```

2. Launch container with Docker Compose:
   ```bash
   docker compose up -d --build
   ```

3. Verify running state:
   ```bash
   docker compose ps
   docker compose logs -f streamfab
   ```

4. Check health endpoint:
   ```bash
   curl -i http://localhost:8000/api/health
   ```

### 3.2 Standalone Docker Run

```bash
# Build production image
docker build -t streamfab:latest .

# Run with resource limits and auto-restart
docker run -d \
  --name streamfab \
  --restart unless-stopped \
  -p 8000:8000 \
  -v streamfab_downloads:/app/downloads \
  --memory="2g" \
  --cpus="2.0" \
  streamfab:latest
```

---

## 4. Method 2: Bare-Metal Linux VPS (Systemd)

For direct host execution without containers (e.g. Ubuntu 22.04 / 24.04 LTS, Debian 12):

### 4.1 Setup Application User & Directory

```bash
# Create dedicated system user
sudo useradd -r -s /bin/false -d /var/www/streamfab streamfab

# Clone repository into /var/www/streamfab
sudo git clone https://github.com/Cylae/streamfab.git /var/www/streamfab
cd /var/www/streamfab

# Create virtual environment
sudo python3 -m venv venv
sudo ./venv/bin/pip install --upgrade pip
sudo ./venv/bin/pip install -r requirements.txt

# Create downloads folder and assign ownership
sudo mkdir -p /var/www/streamfab/downloads
sudo chown -R streamfab:streamfab /var/www/streamfab
```

### 4.2 Configure Systemd Service

1. Copy the provided service file:
   ```bash
   sudo cp /var/www/streamfab/deployment/streamfab.service /etc/systemd/system/streamfab.service
   ```

2. Reload daemon, enable and start StreamFab:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable streamfab
   sudo systemctl start streamfab
   ```

3. Check service status:
   ```bash
   sudo systemctl status streamfab
   ```

---

## 5. Reverse Proxy Setup (Nginx & Caddy)

StreamFab serves real-time **Server-Sent Events (SSE)** for download progress and **HTTP Range byte streams** for zero-copy client playback. The reverse proxy must be configured to disable response buffering on these endpoints.

### 5.1 Nginx (Recommended)

1. Copy the optimized configuration template:
   ```bash
   sudo cp /var/www/streamfab/deployment/nginx.conf /etc/nginx/sites-available/streamfab.conf
   ```

2. Edit your domain name in `/etc/nginx/sites-available/streamfab.conf`:
   ```nginx
   server_name streamfab.yourdomain.com;
   ```

3. Enable the site and test configuration:
   ```bash
   sudo ln -s /etc/nginx/sites-available/streamfab.conf /etc/nginx/sites-enabled/
   sudo nginx -t
   sudo systemctl reload nginx
   ```

4. Secure with free SSL certificate using Certbot:
   ```bash
   sudo apt install -y certbot python3-certbot-nginx
   sudo certbot --nginx -d streamfab.yourdomain.com
   ```

#### Key Nginx Configuration Highlights
- `proxy_buffering off;` on `/api/progress/` ensures SSE events reach browser immediately without buffering delays.
- `proxy_buffering off;` and `Range` headers on `/api/proxy-stream` ensure smooth audio decoding without storing entire files in proxy buffers.
- `limit_req_zone` protects against API spam and DDoS attacks.

### 5.2 Caddy Alternative (Automatic HTTPS)

If using Caddy, create `/etc/caddy/Caddyfile`:

```caddy
streamfab.yourdomain.com {
    encode gzip zstd

    # Disable buffering for SSE stream
    @sse path /api/progress/*
    reverse_proxy @sse 127.0.0.1:8000 {
        flush_interval -1
    }

    # Zero-copy stream proxy
    @proxy_stream path /api/proxy-stream*
    reverse_proxy @proxy_stream 127.0.0.1:8000 {
        flush_interval -1
    }

    # All other routes
    reverse_proxy 127.0.0.1:8000
}
```

Reload Caddy:
```bash
sudo systemctl reload caddy
```

---

## 6. Cloud Platform Deployments

### Railway

1. Push your repository to GitHub.
2. In Railway, click **New Project** &rarr; **Deploy from GitHub repo**.
3. Railway automatically detects the `Dockerfile` and provisions the container.
4. Set **Port** to `8000` in Service Settings &rarr; Networking.
5. Generate a public Railway domain.

### Render

1. Create a new **Web Service** on [Render.com](https://render.com).
2. Connect your GitHub repository.
3. Select **Docker** environment (Render uses the included `Dockerfile`).
4. Set **Port** to `8000`.
5. Deploy service.

### Fly.io

1. Install Fly CLI:
   ```bash
   curl -L https://fly.io/install.sh | sh
   ```
2. Authenticate and launch:
   ```bash
   fly auth login
   fly launch --no-deploy
   ```
3. Set internal port to 8000 in `fly.toml`:
   ```toml
   [[services]]
     internal_port = 8000
     protocol = "tcp"
   ```
4. Deploy:
   ```bash
   fly deploy
   ```

### DigitalOcean / AWS EC2

1. Provision an **Ubuntu 24.04 LTS** Droplet / t3.small EC2 instance.
2. Allow inbound ports `80` (HTTP), `443` (HTTPS), and `22` (SSH) in Security Groups / Cloud Firewall.
3. Follow [Method 1 (Docker Compose)](#3-method-1-docker--docker-compose-recommended) or [Method 2 (Systemd)](#4-method-2-bare-metal-linux-vps-systemd).

---

## 7. Environment Variables & Configuration

StreamFab accepts the following environment variables or command-line arguments:

| Variable | CLI Flag | Default | Description |
|---|---|---|---|
| `STREAMFAB_HOST` | `--host` | `127.0.0.1` (`0.0.0.0` in Docker) | Network bind interface |
| `STREAMFAB_PORT` | `--port` | `8000` | Port for the HTTP/REST server |
| `STREAMFAB_DOWNLOADS_DIR` | N/A | `./downloads` | Root path for temporary task isolation |
| `STREAMFAB_LOG_LEVEL` | N/A | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

---

## 8. Automated Maintenance & yt-dlp Updates

Media platforms (YouTube, TikTok, Instagram) frequently update their video delivery mechanisms. Keeping `yt-dlp` updated is essential for continuous 100% download reliability.

### 8.1 Automated Weekly yt-dlp Update Cron

Add a weekly cron job to update `yt-dlp`:

**For Bare-Metal / Systemd:**
```bash
# Edit root crontab
sudo crontab -e

# Add line to update yt-dlp every Sunday at 3:00 AM
0 3 * * 0 /var/www/streamfab/venv/bin/pip install --upgrade yt-dlp && systemctl restart streamfab
```

**For Docker:**
Set up a CI/CD pipeline (e.g. GitHub Actions) or a Watchtower container to rebuild the image weekly:
```yaml
# In docker-compose.yml
services:
  watchtower:
    image: containrrr/watchtower
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    command: --interval 86400 streamfab_app
```

### 8.2 Automated Temp Downloads Cleanup Cron

If users trigger downloads using Cloud Server mode, temporary files are cleaned upon download, but orphaned tasks can be pruned daily:

```bash
# Clean tasks older than 24 hours in downloads directory
0 4 * * * find /var/www/streamfab/downloads -mindepth 1 -maxdepth 1 -type d -mtime +1 -exec rm -rf {} +
```

---

## 9. Production Security Checklist

- [x] **Anti-SSRF Protection**: Built-in IP address resolution blocking private RFC1918, loopback (127.0.0.1), and link-local (169.254.169.254) networks.
- [x] **Path Traversal Defenses**: Strictly verified UUIDv4 paths prevent `../` attacks on file delivery.
- [x] **Content-Security-Policy (CSP)**: `default-src 'self'`, `worker-src 'self' blob:`, and strict framing defenses (`X-Frame-Options: SAMEORIGIN`).
- [x] **Unprivileged User**: Container and systemd execute under unprivileged user (`streamfab` / `www-data`), never as `root`.
- [x] **Rate Limiting**: Built-in 60 req/min token bucket per IP, plus upstream Nginx burst limiting.
- [x] **Cloudflare / CDN Note**: If using Cloudflare proxy (orange cloud), navigate to **Rules** &rarr; **Page Rules** and disable **Buffering** for `*streamfab.yourdomain.com/api/*` so SSE streams are delivered in real time.

---

## 10. Health Checks & Troubleshooting

### Health Check Endpoint
```bash
curl -f http://127.0.0.1:8000/api/health
```
Response:
```json
{
  "status": "healthy",
  "service": "streamfab",
  "version": "2.0.0",
  "active_tasks": 0
}
```

### Common Issues & Solutions

1. **SSE progress bar does not update until 100%:**
   - *Cause:* Nginx or Cloudflare is buffering the response stream.
   - *Fix:* Ensure `proxy_buffering off;` is active on `/api/progress/` in Nginx, and disable proxy buffering in Cloudflare.

2. **FFmpeg missing error:**
   - *Cause:* FFmpeg is not installed or not in system PATH.
   - *Fix:* Run `sudo apt install ffmpeg` or check `which ffmpeg`.

3. **Port 8000 already bound:**
   - *Cause:* Another instance is running.
   - *Fix:* Check with `lsof -i :8000` or `netstat -tlpn | grep 8000` and stop the conflicting process.

4. **Stream extraction fails for specific platform:**
   - *Cause:* The platform updated its API tokens.
   - *Fix:* Update yt-dlp to latest version with `pip install --upgrade yt-dlp`.
