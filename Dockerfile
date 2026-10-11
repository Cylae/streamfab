# ==============================================================================
# StreamFab - Production Dockerfile
# Unprivileged container with FFmpeg & Python 3.12
# ==============================================================================

FROM python:3.12-slim-bookworm AS base

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    STREAMFAB_STORAGE_DIR=/app/downloads \
    STREAMFAB_COOKIES_FILE=/app/state/cookies.txt

# Install system dependencies: FFmpeg, curl (for healthcheck), ca-certificates
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create unprivileged system user for sandboxed execution
RUN groupadd -r streamfab && useradd -r -g streamfab -u 1001 -m -d /home/streamfab streamfab

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.lock .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.lock

# Copy application source code
COPY --chown=streamfab:streamfab src /app/src

# Create downloads directory with unprivileged ownership
RUN mkdir -p /app/downloads /app/state && chown -R streamfab:streamfab /app

# Switch to unprivileged user
USER streamfab

# Expose StreamFab API & Web UI port
EXPOSE 8000

# Container healthcheck querying /api/health
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://127.0.0.1:8000/api/health || exit 1

# Launch StreamFab Web Server
CMD ["python", "src/downloader.py", "--web", "--host", "0.0.0.0", "--port", "8000"]
