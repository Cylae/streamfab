"""Reproduce fragmented-body memory measurements against a reviewed git baseline."""

import asyncio
import json
import statistics
import subprocess
import sys
import time
import tracemalloc
from pathlib import Path

BASELINE = "5308ae4a0d1b3b52807b7ce254f6eb4988185a89"
CHUNKS = 50000


async def measure(middleware):
    remaining = CHUNKS

    async def receive():
        nonlocal remaining
        remaining -= 1
        return {
            "type": "http.request",
            "body": b"" if remaining else b"x",
            "more_body": remaining > 0,
        }

    async def app(scope, receive, send):
        payload = bytearray()
        while True:
            event = await receive()
            payload.extend(event.get("body", b""))
            if not event.get("more_body", False):
                break
        assert payload == b"x"

    async def send(message):
        raise AssertionError("A valid one-byte request must reach the application.")

    tracemalloc.start()
    started = time.perf_counter()
    try:
        await middleware(app)({"type": "http", "method": "POST"}, receive, send)
        seconds = time.perf_counter() - started
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    return seconds, peak


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "src"))
    from security import BodyLimitMiddleware

    # Execute only the project's reviewed baseline, not arbitrary downloaded code.
    source = subprocess.check_output(
        ["git", "show", f"{BASELINE}:src/security.py"], cwd=root, text=True
    )
    baseline = {}
    exec(compile(source, "baseline/security.py", "exec"), baseline)
    results = {"baseline_commit": BASELINE, "chunks": CHUNKS, "payload_bytes": 1}
    for name, middleware in [
        ("baseline", baseline["BodyLimitMiddleware"]),
        ("final", BodyLimitMiddleware),
    ]:
        runs = [asyncio.run(measure(middleware)) for _ in range(3)]
        results[name] = {
            "median_seconds": statistics.median(t for t, _ in runs),
            "peak_bytes": max(p for _, p in runs),
        }
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
