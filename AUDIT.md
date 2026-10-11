# StreamFab audit and remediation

Date: 2026-10-11. Baseline: `b1ca1a2df0e59be838fbdc96db288b9ff4b2806e`, default branch `feat/video-downloader-5573761007156772975`.

## Scope and approach

Reviewed the application's Python modules, browser application and processor, HTML/CSS integration, tests, dependency declarations, launcher, Docker, Compose, Nginx, systemd and documentation. Baseline contained 25 tracked files, including two minified third-party libraries. Retained lamejs was tested with actual synthetic MP3 encoding; its integration and licensing provenance were reviewed. Its complete minified implementation was not formally verified or independently reimplemented. Unused MP4Box was removed.

The audit combines source inspection, reproducible failure cases, targeted regression tests, dependency vulnerability lookups, DOM tests, local synthetic media processing, and a running-server smoke check. This is not a mathematical proof of correctness or a guarantee that every live media platform works.

## Corrected findings

| Severity | Finding in baseline | Remediation and evidence |
|---|---|---|
| High | Playlist titles were interpolated into `innerHTML`, enabling metadata-driven XSS | Dynamic labels, titles and indexes now use DOM properties and `textContent`; malicious playlist/resolution DOM tests; inline handlers removed and script CSP tightened |
| High | Cookie upload/removal was unauthenticated and CORS allowed every origin with credentials | Loopback restriction or explicit constant-time token verification; same-origin checks and trusted hosts; remote/token/spoofed-forwarding regressions |
| High | A global cookie session could be used by anonymous remote media requests | Installed sessions require authorization for remote analysis, resolution, download and proxy requests; isolated per-operation cookie snapshots |
| High | DNS failures were allowed and only initial yt-dlp URLs were screened | Fail-closed DNS validation; public-only ports/addresses; guarded yt-dlp urllib handler validates redirects and connects to the exact checked sockaddr; async proxy backend pins vetted IPs while preserving TLS hostname |
| High | FFmpeg network downloaders could bypass Python transport checks | Web engine rejects external network downloaders; postprocessing input protocols restricted to local file/pipe; web trimming moved to local downloaded files |
| High | Arbitrary upstream HTML could be served by the media proxy under the application origin | Proxy accepts audio/video, safe image types and binary media only; HTML rejection regression |
| High | File fallback could serve unfinished output, and resolving a symlinked task directory weakened containment | Canonical UUIDs, root/task containment checks, sanitized delivery names, and atomic completion records required after restart; unfinished output is not delivered |
| Medium | Worker threads called `asyncio.Queue.put_nowait` directly, causing delayed or unsafe SSE notification | Subscriber event-loop scheduling, coalesced pending notifications, bounded one-event queues; thread wakeup and queue regressions |
| Medium | Cancelling a worker could later report an error; queued cancelled tasks could still start | Queued cancellation skips execution; cancellation remains terminal when the worker raises; completed tasks remain completed |
| Medium | Cleanup used task creation time and could remove an active download | Terminal-state retention with running-worker exclusion; periodic maintenance; only canonical task folders are purged |
| Medium | Cache and pending task/extraction/proxy resources were insufficiently bounded | Hard cache/task caps, extraction/proxy admission limits, body size limit including chunked bodies, browser buffering cap, progress disk/free-space checks |
| Medium | Rate limiter retained expired timestamps and trusted broad forwarded-IP ranges | Store pruned histories, use monotonic time, bound distinct clients and expire a full map; leave proxy trust to Uvicorn |
| Medium | Audio/video formats, playlist indices and some trim ranges accepted unsupported or invalid input | Typed enum/regex/bounded fields, strict integers, nonempty bounded playlists, normalized timestamps and end/start validation before task admission |
| Medium | Browser video could be mislabeled MP4 or silently delivered below selected quality | Client copying requires a matching combined MP4/quality and compatible options; all other cases use server processing |
| Medium | Browser mode could ignore playlists/subtitles, tag disabled metadata, or continue after cancellation | Route playlists/subtitles/WAV metadata to server, respect MP3 metadata toggle, abort fetches and yield during encoding, suppress fallback after cancellation |
| Medium | ID3v2.3 text used the UTF-8 flag defined for another tag version | UTF-16 BOM text frames and JPEG/PNG type detection; Unicode and metadata-disable regressions |
| Medium | CLI trimming only passed arbitrary strings to postprocessors and sometimes performed no trim | Validated yt-dlp download ranges; invalid CLI retry and port parameters rejected; UTF-8 batch reading |
| Medium | Files with repeated titles collided and playlist ZIP creation compressed already-compressed media | Include media IDs and bound title bytes in output names; use ZIP_STORED; reject auxiliary-only outputs |
| Medium | Deployments exposed the backend, used mismatched service users/state paths, and could ship cookies | Loopback Compose publishing, separate private state volume, matching systemd user, writable state-only paths, excluded cookies, locked runtime-only image and reverse-proxy authentication template |
| Low | UI state, object URLs and radio selection could remain stale | Operation IDs, blob revocation, analysis reset, selection synchronization, stale SSE guard, storage-access tolerance and reduced-motion/focus styling |
| Low | Documentation claimed zero CPU, zero-copy streaming, lossless recovery, unsupported MIT licensing and fixed test counts | Rewritten documentation and truthful processing table; third-party notices; removed unsupported guarantees and license badge |
| Low | No repeatable CI or runtime lock | Pinned direct dependencies plus complete runtime lock; Python/Node tests, vulnerability checks and container smoke workflow |

## Validation results

Locally executed on Linux, Python 3.12.14 and Node.js 24.19.0:

| Check | Result |
|---|---|
| Baseline Python suite | 130 passed, 1 failed: proxy constructor consumed an environment SOCKS proxy without the optional dependency; some tests performed actual extraction and touched project cookie storage |
| Final Python suite | **192 passed**; includes 61 added audit regressions |
| Python statement coverage | **89.70%** (1,315 covered of 1,466 statements); coverage is a measurement, not a correctness guarantee |
| `ruff check src tests` | Passed |
| `ruff format --check src tests` | Passed |
| `git diff --check` | Passed |
| Node processor suite | Passed; actual lamejs synthetic MP3, WAV, Unicode tags, metadata toggles, timestamp/range and video-container checks |
| Node DOM suite | Passed; event bindings, malicious metadata, theme, cookie modal, playlist routing, cancellation and blob cleanup |
| FFmpeg fixtures | Real audio trim and video trim with retained title; duration checked with ffprobe |
| Guarded transport fixture | Real synthetic HTTP exchange through the restricted yt-dlp handler; private redirect rejected |
| Running Uvicorn smoke | Passed: health, SPA and scripts, CSP, invalid request rejection, private proxy/download rejection and cross-origin cookie rejection |
| `pip-audit -r requirements.lock` | No known vulnerabilities reported at audit time |
| `npm audit --audit-level=low` | No known vulnerabilities reported at audit time |
| `pip check` | Passed |

One upstream Starlette test-client deprecation warning remains: its HTTPX compatibility path is deprecated in favor of HTTPX2. Runtime proxy traffic uses HTTPX 0.28.1 and the tested transport adapter; no warning was hidden.

Published validation: [GitHub Actions run 38175919984](https://github.com/Cylae/streamfab/actions/runs/38175919984) completed successfully for application commit `06b794ad4d8cf11395d20b7bc3f78ccc8e5bd574`. All seven jobs passed: Python on Ubuntu and Windows with Python 3.10 and 3.12, JavaScript tests and npm audit, locked Python dependency audit, and Compose configuration/container build/startup health check. This subsequent documentation-only commit records those results without changing the validated application code.

## Verification limits and operating constraints

- Headless Chromium download failed in this environment with an invalid/truncated browser archive. DOM interaction tests passed, but pixel layout, actual Web Audio decoding and browser codec compatibility were not verified in a rendered browser.
- Docker/Nginx executables and a Windows host were unavailable locally. Published CI verified the Windows/Linux Python matrix and container build/startup as recorded above. Nginx, systemd and TLS provisioning were reviewed, not deployed here.
- Live YouTube/TikTok/etc. downloads were not used as final acceptance tests. Availability, authentication, DRM restrictions, platform changes and signed CDN URLs are external behavior; the web engine deliberately rejects some downloader protocols.
- yt-dlp and httpcore internal APIs are used to enforce connection policy. Their versions are pinned; transport tests are required before dependency updates.
- The system remains single-user and single-worker. Remote operation requires HTTPS and full reverse-proxy authentication. Shared cookies are not multi-tenant credentials; task UUIDs are private capabilities.
- Cancellation is cooperative for yt-dlp extraction/postprocessing. The local trim process can be terminated, but blocking upstream operations may finish before cancellation takes effect.
- Disk checks and 2 GiB progress budgeting are not hard filesystem quotas. Temporary conversion output can exceed them between checks. Native FFmpeg parsing also requires patched system packages, unprivileged execution and host/container isolation.
- Browser audio decoding can expand compressed input substantially. The 128 MiB byte-stream cap limits compressed buffering, not all browser memory allocations.
- No project license was invented. The owner must explicitly supply a license for original application code if one is desired.
