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

## Initial audit validation (PR #1)

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

## Second-pass audit under the engineering directive

Baseline: merged application commit `5308ae4a0d1b3b52807b7ce254f6eb4988185a89` (PR #1). The complete supplied directive was reviewed. The existing 192 tests still passed, but failure injection and independent ffprobe outputs exposed additional defects. Seven initial new regressions were run before remediation and **all seven failed**; their failure output confirmed each root cause below. Subsequent tests cover the broader defect classes rather than treating a green initial suite as completion.

Architecture/technology decision: retain Python/yt-dlp/FFmpeg and vanilla JavaScript; replace the defective credential, state-transition and body-buffering boundaries. No comparative measurement justified a language/framework rewrite. [ARCHITECTURE.md](ARCHITECTURE.md) records the project model, invariants, alternatives, design decisions, trust boundaries, recovery, debugging and requirement traceability. This was a fresh failure/adversarial review of the previous implementation, not a claim of review by a separate team.

| ID / severity | Confirmed cause and remediation | Verification / status |
|---|---|---|
| F01 / High | An absent configured cookie path searched legacy jars; removal could delete an unrelated jar. Configuration is now authoritative and working-directory/src searches are removed | Missing-configured-file and original-byte preservation regression; VERIFIED |
| F02 / High | Request-time authentication did not constrain a worker's later credential lookup. Admission now captures account permission and anonymous work cannot acquire later-installed cookies | Remote queued task, install-after-admission and actual cookie-less yt-dlp context; VERIFIED |
| F03 / High | An extraction could repopulate cleared metadata after cookie removal; one cache namespace mixed account/public data. Locked mutation advances a generation, refuses stale writes and separates namespaces | Remove-during-extraction injection plus namespace isolation; VERIFIED |
| F04 / Medium | Progress checked cancellation before later work and could overwrite the terminal state. Worker updates, snapshots and subscriber lifecycle now share the cancellation lock | Cancel-during-disk-check injection; 30 barrier-driven contention rounds; VERIFIED |
| F05 / Medium | Cancelled proxy setup escaped exception cleanup; client construction was outside the protected block. Shielded, idempotent cleanup releases capacity and closes owned clients | Cancel while send is pending; constructor failure; raw streaming/redirect regressions; VERIFIED |
| F06 / Medium | SSE had bounded queues but unlimited subscribers. Admission is capped at 32 subscribers per task and detached loop/subscriber state is released | Capacity/release regression, worker-to-loop notification tests; VERIFIED |
| F07 / Medium | FFmpeg trim used its default MP3 bitrate. The real 320 kbps mono fixture became **64 kbps**. Trim now explicitly preserves the selected bitrate, title and cover stream | Independent ffprobe reports 320,000 bit/s and retained title; VERIFIED |
| F08 / Medium | A trim starting after media duration replaced the original with an empty WAV without reporting failure. ffprobe duration is now validated before conversion; disk budget is rechecked after trimming | Real half-second WAV, invalid range, expected error and unchanged original bytes; VERIFIED |
| F09 / Medium | CLI container choice configured the merger only, so combined streams could bypass it. Explicit remuxing now applies MP4/MKV choices to combined media | Real combined MPEG-4/AAC fixtures remuxed by the configured yt-dlp postprocessor; independent ffprobe container check; VERIFIED |
| F10 / Medium | A late cancellation response reset a newer DOM task; a new singleton controller revived an older browser decode. Cancellation ownership is now per operation and old responses cannot reset new state | Deferred old decode released after starting a new request; deferred server cancel response with a new active task; VERIFIED |
| F11 / Medium | Request memory grew with the number of ASGI messages, including empty fragments. The limit now accumulates a bounded byte buffer instead of message dictionaries | 50,000-fragment tracemalloc stress test and reproducible before/after benchmark; VERIFIED |
| F12 / Medium | Oversized proxy bodies could end as apparently successful truncated responses; cover fetches bypassed the browser buffer cap. Declared proxy oversize is rejected, streamed overruns fail, cover art is capped at 8 MiB and cancelled on excess | Declared malformed/5,000-digit/oversized lengths; browser declared/streamed buffer-cancellation tests; VERIFIED |
| F13 / Low | Empty URL credentials disagreed between entry points; malformed Origin raised a server error | Consistent userinfo rejection and explicit HTTP 403 Origin test; VERIFIED |
| F14 / Medium | Default POSIX output directories could be read/enumerated by other OS users. Storage/task directories now use owner-only modes | POSIX task permission assertion and clean server startup; Windows ACL limitation remains documented; VERIFIED for POSIX |

### Measured before/after

`python scripts/benchmark_body_limit.py` compares the reviewed first-audit baseline with the final buffer, runs each case three times, checks the identical delivered payload, and reports traced Python allocation peaks and median time. Linux, Python 3.12.14; 50,000 synthetic empty/tiny ASGI fragments delivering one byte:

| Measurement/behavior | Merged first audit | Second pass | Evidence |
|---|---:|---:|---|
| Traced peak allocations for body fixture | 9,634,840 bytes | 1,484 bytes | Reproducible benchmark script; not process RSS or an overall memory guarantee |
| Median fixture processing time | 0.5193 seconds | 0.0640 seconds | Three measured runs under tracemalloc; machine-dependent synthetic workload |
| Trimmed 320 kbps MP3 fixture | 64,000 bit/s | 320,000 bit/s | Real FFmpeg processing and independent ffprobe |
| Initial second-pass regression failures | 7 | 0 | Same seven behaviors reproduced before and after corrections |

### Final evidence and maintainability gate

The final source snapshot was copied into an empty directory, a new virtual environment was created, and runtime/development dependencies were installed from the repository declarations. Node dependencies were installed by `npm ci --ignore-scripts` without the project's existing node_modules. No browser/vendor or upstream warning was suppressed. One earlier clean-copy formatting check correctly rejected a stale, pre-format script snapshot; it was recopied from the final formatted source and the checks were rerun.

| Area | Verification | Result / evidence strength |
|---|---|---|
| Requirements/maintainability | Component ownership, alternatives, invariants, contracts, debugging, rollback and traceability | Documented in ARCHITECTURE; supported by source review, not an actual third-party developer onboarding study |
| Formatting/lint | `python -m ruff check src tests scripts`; `python -m ruff format --check src tests scripts` | PASS; clean environment |
| Python behavior | Full offline/regression/media suite in a new venv | 216 tests passed on Linux Python 3.12; 24 second-pass cases; proven for tested inputs |
| Statement coverage | `pytest --cov=src --cov-report=json` | 89.95% (1,369 / 1,522); no correctness guarantee |
| JavaScript | Shipped processor, synthetic actual MP3, jsdom UI, overlapping operation and byte-budget regressions | PASS from fresh npm install; rendered browser remains NOT VERIFIED |
| Media integration | Actual MP3/WAV/video trimming and requested MP4/MKV remux fixtures | PASS; independent duration/bitrate/title/container oracles |
| Resource/failure behavior | Fragment stress, cancellation contention, proxy setup cancellation/failure, bounded subscribers and cache | PASS for these scenarios; quotas and cooperative-cancellation limitations still apply |
| Dependencies | Fresh `pip check`, `pip-audit -r requirements.lock`, `npm audit --audit-level=low` | PASS; no known vulnerabilities at execution time |
| Clean runtime | Real subprocess Uvicorn smoke from new venv | PASS: startup, SPA/CSP, hostile origin/host, private URL rejection, 422/413, cookie lifecycle and completion-record delivery after restart |
| Windows/Docker | GitHub Actions Python matrix and container build/startup | Publication CI is the authoritative evidence; inspect the linked PR checks for this second-pass commit |
| Live media platforms, rendered-browser audio/layout, production provisioning | Not exercised as final acceptance tests | NOT VERIFIED; limitations above remain applicable |

Final source review examined credential capabilities, cache invalidation order, all production progress mutations, cancellation cleanup, storage bounds, FFmpeg arguments, API contracts and documentation against the regressions. No additional material actionable defect was confirmed in that final review. This is an evidence-based stopping decision, not a proof of absolute correctness. Dev-tool resolver metadata and the environment's npm proxy setting produced compatibility warnings; the upstream Starlette TestClient deprecation remains documented and visible.
