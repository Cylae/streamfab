"""Isolated, offline unit tests: never download real media or touch user cookies."""

import ipaddress
import socket
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path):
    import engine
    import security

    monkeypatch.setattr(engine, "DOWNLOADS_DIR", tmp_path / "downloads")
    engine.DOWNLOADS_DIR.mkdir()
    monkeypatch.setattr(engine, "COOKIES_FILE_PATH", tmp_path / "cookies.txt")
    monkeypatch.delenv("STREAMFAB_COOKIES_FILE", raising=False)
    monkeypatch.delenv("STREAMFAB_ADMIN_TOKEN", raising=False)
    original_run_task = engine.EngineManager.run_task
    monkeypatch.setattr(engine.EngineManager, "run_task", AsyncMock())
    import web_server

    monkeypatch.setattr(web_server, "DOWNLOADS_DIR", engine.DOWNLOADS_DIR)
    engine.engine.tasks.clear()
    engine._METADATA_CACHE.clear()
    security.api_rate_limiter.reset()
    security.download_rate_limiter.reset()

    def public_dns(host, port=None, *args, **kwargs):
        try:
            address = str(ipaddress.ip_address(host))
        except ValueError:
            address = "93.184.215.14"
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        return [(family, socket.SOCK_STREAM, 6, "", (address, port or 443))]

    monkeypatch.setattr(socket, "getaddrinfo", public_dns)
    yield original_run_task
    engine.engine.tasks.clear()
    engine._METADATA_CACHE.clear()
