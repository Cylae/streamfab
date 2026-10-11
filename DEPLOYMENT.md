# StreamFab deployment

StreamFab is a single-user service with process-local task state. Use one worker, HTTPS, reverse-proxy authentication, and explicit hostnames for any remote installation. A cookie administration token is not a replacement for authenticating the entire web application.

## Docker Compose

```bash
git clone https://github.com/Cylae/streamfab.git
cd streamfab
docker compose up -d --build
curl -f http://127.0.0.1:8000/api/health
```

The port is published on loopback only. Downloads and cookie state have separate named volumes. The image runs as UID 1001 and installs locked runtime dependencies; it does not include tests or credentials from the build context.

For a remote hostname, create a private `.env` file in the project directory:

```dotenv
STREAMFAB_TRUSTED_HOSTS=localhost,127.0.0.1,streamfab.example.com
```

Generate an administration token without embedding it in shell history:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Save its output as `STREAMFAB_ADMIN_TOKEN` in `.env`, restrict permissions (`chmod 600 .env`), and restart Compose. Use the same token in the Cookie Assistant. Keep the application port private; put Nginx or another authenticated HTTPS reverse proxy in front of it.

```bash
docker compose up -d
```

Back up the state volume only if you intend to retain account sessions; handle those backups as credentials. Removing a container does not remove its named volumes.

## Linux with systemd

```bash
sudo useradd --system --home-dir /var/www/streamfab --shell /usr/sbin/nologin streamfab
sudo git clone https://github.com/Cylae/streamfab.git /var/www/streamfab
sudo python3 -m venv /var/www/streamfab/venv
sudo /var/www/streamfab/venv/bin/python -m pip install -r /var/www/streamfab/requirements.lock
sudo cp /var/www/streamfab/deployment/streamfab.service /etc/systemd/system/streamfab.service
sudo systemctl daemon-reload
sudo systemctl enable --now streamfab
sudo systemctl status streamfab
```

The service user is `streamfab`; the repository and virtual environment can remain root-owned and read-only. systemd creates `/var/lib/streamfab` for state and permits writes there. Configuration goes in `/etc/streamfab.env`, readable only by root:

```dotenv
STREAMFAB_TRUSTED_HOSTS=localhost,127.0.0.1,streamfab.example.com
```

Add `STREAMFAB_ADMIN_TOKEN` using a generated secret, then restart the service. `PrivateTmp=true` isolates temporary cookie snapshots. No external cleanup cron is required. Do not delete output directories while downloads run.

## Nginx

The supplied [nginx.conf](deployment/nginx.conf) is an HTTP configuration template; **configure TLS before public exposure**. Replace the example hostname in both Nginx and `STREAMFAB_TRUSTED_HOSTS`. SSE and media proxy buffering are disabled. Static assets have a short cache lifetime because filenames are not content-hashed.

Create the reverse-proxy password file:

```bash
sudo apt-get install apache2-utils
sudo htpasswd -c /etc/nginx/streamfab.htpasswd streamfab
sudo cp deployment/nginx.conf /etc/nginx/conf.d/streamfab.conf
sudo nginx -t
sudo systemctl reload nginx
```

Add certificate paths and a TLS listener using your organization's certificate provisioning workflow. Keep port 8000 closed to external clients. Forwarded client addresses must come only from trusted proxies: Uvicorn's default loopback trust works for a directly local Nginx process. For containerized proxies, configure a specific trusted proxy address with Uvicorn's `--forwarded-allow-ips` and keep the backend private. Never use `*` for proxy trust on an exposed backend.

## Capacity and operational limits

- The application has 3 simultaneous download workers and bounded extraction/proxy admission. Browser encoding still uses server CPU for extraction and stream delivery, plus network bandwidth.
- A 2 GiB task budget is checked during download and after media processing. It is not a hard disk quota; reserve enough disk space and use OS/container quotas where required.
- The supplied Compose configuration sets CPU/memory limits. Add disk quotas and outbound firewall rules suited to the host. Application transport checks complement those controls.
- FFmpeg is a native parser of untrusted media. Keep system packages patched and run it unprivileged. Its web postprocessing inputs disallow network protocols; isolated containers offer additional protection.
- Some extractors, live streams, nonstandard ports and external downloader protocols are intentionally unsupported by the web engine. The CLI has a different network policy and should be used only with trusted inputs.
- File URLs and UUIDs are private capabilities, not multi-user authorization. Do not operate this as a public multi-tenant download service.
- DNS checks at connection time do not control the host's routing/firewall configuration. Egress rules remain an independent layer.

## Updates and troubleshooting

Review dependency upgrades, refresh the lock, run Python/JavaScript tests, and rebuild/restart. The transport adapter relies on internal yt-dlp/httpcore APIs and must be tested after upgrades. Avoid automatic pip-upgrade cron jobs.

```bash
curl -f http://127.0.0.1:8000/api/health
sudo journalctl -u streamfab --since today
# Or:
docker compose logs --tail=100 streamfab
```

HTTP 400 `Invalid host header`: configure the real hostname. HTTP 403 on cookies: supply the token or use loopback if no token is configured. HTTP 503: the bounded admission limit has been reached. SSE delays: check reverse-proxy buffering and connection timeouts. Extraction failures: check platform availability and the reviewed yt-dlp version; session cookies do not guarantee platform acceptance.
