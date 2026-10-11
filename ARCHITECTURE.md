# StreamFab architecture and maintenance

## Purpose and requirements

StreamFab is a single-user CLI and web application that extracts media with yt-dlp, converts it with FFmpeg, and delivers audio, video or playlist archives. It consumes public media URLs, options and optional owner-supplied account cookies. Its outputs are metadata, progress events and completed media files. Live-site availability and DRM circumvention are not guarantees.

The web interface must preserve the requested format, MP3 bitrate, trim range, selected playlist entries, metadata setting and subtitles when supported. Failure must not appear as success. Cancellation is terminal. Shared cookies must never become anonymous credentials. Web network connections must remain public HTTP/HTTPS, including redirects and DNS changes. Active outputs must not be removed by retention cleanup. Only completed outputs may be served after restart.

Compatibility: Python 3.10+, Windows/Linux, one Uvicorn process/worker, local FFmpeg/ffprobe. Node 24 is development tooling, not a production runtime. Browser decoding support varies; operations the browser cannot honor use the server. The locally operated CLI deliberately permits a broader set of yt-dlp protocols than the web engine.

## Technology decision

Decision: **retain Python and vanilla JavaScript, refactor the defective boundaries, and replace unsafe credential/progress/body-buffering behavior**.

| Alternative | Assessment | Decision basis |
|---|---|---|
| Python + yt-dlp + FFmpeg | Direct supported extraction/postprocessor integration; async API with bounded worker offload; native FFmpeg handles conversion | Retain. Actual integration and regression fixtures provide evidence. Python CPU performance is not claimed to dominate conversion |
| Rust or Go backend | Could provide stronger compile-time constraints or simpler process isolation; would still invoke yt-dlp/FFmpeg or require replacing extraction | No rewrite. No measured Python bottleneck justifies migration and platform-compatibility risk |
| Node/TypeScript backend | Could share frontend types; would still need Python extraction or a maintained equivalent | No replacement. Adds a second production runtime without solving the confirmed defects |
| SPA framework or frontend TypeScript migration | May help a larger application; current UI is one screen and tests run against actual DOM bindings | Keep the current frontend. Fix operation lifetimes and escaping directly; revisit if UI complexity materially grows |

These are code-review assessments, not comparative performance benchmarks. Switching languages would not itself fix credentials, DNS rebinding, cancellation, invalid trim ranges or deployment exposure.

## Components and data flow

| Component | Responsibility | Important boundary |
|---|---|---|
| `src/downloader.py` | CLI entrypoint, option selection, retry policy, Uvicorn startup | CLI accepts trusted-owner URLs; web startup is loopback by default |
| `src/web_server.py` | HTTP validation/authentication, admission, SSE, checked proxy, file delivery | Capture cookie permission before offloading or queueing |
| `src/security.py` | URL/IP/timestamp/filename rules, request body limits, rate limits, origin/CSP headers | Reject malformed input before media processing |
| `src/networking.py` | yt-dlp urllib and HTTPX/httpcore network adapters | Resolve and validate actual destinations; connect to checked IPs; preserve original TLS hostname |
| `src/engine.py` | Cookie snapshots, metadata cache, tasks, concurrency, conversion and retention | Worker threads publish through guarded state transitions; complete records are atomic |
| `src/static/js/app.js` | DOM state, request dispatch, processing choice, SSE and downloads | Older asynchronous operations cannot reset a newer operation |
| `src/static/js/client-processor.js` | Bounded stream buffering, Web Audio, MP3/WAV encoding, ID3, MP4 copying | Each call owns its AbortController; compatible output only; bounded cover art |

Analysis: request validation/authentication → bounded extractor thread → per-operation optional cookie snapshot → public-only yt-dlp transport → credential-separated metadata cache → response.

Server download: validated request and captured credential permission → UUID task directory → concurrency semaphore → worker extraction/download/postprocessing → optional local FFmpeg trim → optional ZIP_STORED archive → atomic completion record → completed SSE event → file delivery.

Browser download: checked stream resolution → checked same-origin media proxy → bounded compressed buffer → browser decode/trim/encode or compatible MP4 copying → downloadable Blob. Unsupported operations use the server; cancellation does not trigger fallback.

## Security model

Assets: account cookies, admin token, task outputs, local/private network services, server resources and browser memory. Actors: instance owner, anonymous network callers, a malicious media server, malicious page metadata and other local OS users.

The browser/API boundary validates origin, hostname and request size. Account access is captured separately from public media access. An anonymous operation admitted without cookies remains anonymous even if the owner installs a jar later. The two cache namespaces cannot exchange account-derived titles or results. Cookie mutation and snapshots use a lock; replacing/deleting a jar advances a cache generation so older extraction results cannot repopulate a cleared cache.

The network boundary validates every resolved address and redirect and connects only to vetted public addresses. External web network downloaders are rejected. FFmpeg/ffprobe trimming takes local filenames and restricts protocols to file/pipe. This does not make native media parsing a sandbox: keep FFmpeg patched and run unprivileged with container/filesystem limits.

The filesystem boundary uses canonical UUID task IDs, root/task containment, owner-only POSIX directories, sanitized attachment names and completed-state records. Task UUIDs are bearer capabilities, not user accounts. Do not expose the storage directory through Nginx or share UUIDs with untrusted people. Windows installations need appropriate OS ACLs.

Remote deployments still require HTTPS and full reverse-proxy authentication. The admin token protects shared-session operations; it is not a replacement for complete deployment access control. Same-user local filesystem compromise is outside the isolation boundary.

## Non-obvious design decisions

| Context | Decision and alternatives | Consequence |
|---|---|---|
| yt-dlp supports multiple network backends and FFmpeg can fetch URLs independently | Use one guarded urllib handler in web mode and reject external network downloaders. Alternative: allow them and trust initial URL validation | Some streams are deliberately unsupported; pinned internal APIs require regression checks before upgrades |
| Stateful downloads and SSE run in one process | Keep bounded in-memory state and a semaphore. Alternative: database/job broker and multiple workers | Simpler for a single-user application; multi-worker/multi-tenant operation requires a designed replacement, not a changed launch flag |
| Authentication and cookie installation can change while work is queued | Capture a boolean account-access capability at admission; isolate jars and cache generations. Alternative: check whichever cookie file exists when a worker starts | Anonymous work cannot acquire later-installed credentials; already authorized snapshots may finish after cookie removal |
| Cancellation races worker progress and client decoding | Atomic terminal server state; per-call browser controller; operation IDs in DOM handling | Cancellation is terminal at the state boundary, but blocking external/native operations remain cooperative |
| HTTP chunk count can far exceed body byte count | Accumulate bytes into one bounded buffer, not a list of ASGI messages | Memory depends on byte budget; repeated empty/tiny fragments do not accumulate message objects |
| CLI combined streams bypass yt-dlp's merger | Add explicit remuxing for requested MP4/MKV containers | Unsupported codec/container combinations fail rather than falsely claim a requested format |

## Persistence and recovery

`STREAMFAB_STORAGE_DIR` (or its legacy alias) contains task UUID directories. `STREAMFAB_COOKIES_FILE` is authoritative; otherwise project-root `cookies.txt` is the only default. Working-directory and `src` cookie searches were removed deliberately. See README for all environment variables and limits.

`completed.json` stores the actual output basename and is replaced atomically before the in-memory task becomes completed. After restart, only contained outputs with this marker can be delivered. Progress, cancellation controls and active task state are not recovered. Interrupted outputs remain unavailable and expire as orphan directories. Retention is one hour after terminal state while running; after restart it uses orphan directory modification time.

There is no database migration. Rollback through git is possible, but reverting security fixes restores their exposure. A rollback should stop the server first, retain private cookie storage, verify the completion-record format and run the suite before restarting. Do not overwrite a live task directory during an upgrade.

## Failure, debugging and extension

| Symptom | Where to investigate | Required invariant |
|---|---|---|
| HTTP 400/422 | URL/options/timestamps, yt-dlp support, server exception chain | Invalid input must not create a successful task |
| HTTP 403 | Trusted hosts/origin, admin token, cookie access, path containment | Never relax transport or credential checks to fix authentication |
| HTTP 429/503 | Rate limits and task/extractor/proxy/subscriber capacity | Reject overload before unbounded work starts |
| HTTP 502 from proxy | Upstream connection, redirect, media MIME or declared size | Failed/disconnected streams release their slot and client |
| Task error during trim | FFmpeg/ffprobe availability, duration, codecs, storage, server logs | Original media is retained when the trim range is invalid |
| Browser fallback | Unsupported codec/container/options or browser buffer/decode limit | The server must honor the same requested options |
| File unavailable after restart | Completion marker, output basename and containment | Never expose a partial file as completed |

Server worker errors are logged with their traceback; public errors are classified and omit implementation details. UUIDs correlate tasks and file/progress routes. Do not log uploaded cookies or bearer tokens. A health response reports service readiness and active states; it does not prove upstream sites or FFmpeg codecs work.

To add a format or option, update API validation, engine option mapping, client support/fallback rules, UI controls and README capability tables. Add a real output fixture when the change affects media fidelity. Do not replace file extensions to simulate container conversion. To update yt-dlp/httpcore, verify request-director selection, public-IP socket connection, redirects, TLS hostname behavior and proxy cancellation first.

## Verification and traceability

Install/run/test commands are in README; deployment commands are in DEPLOYMENT. `tests/conftest.py` isolates DNS, cookies and storage for every test. Real transport fixtures map only a vetted synthetic public address to a local test socket; this exception exists only in tests. FFmpeg fixtures verify actual media duration, bitrate and metadata. JavaScript tests execute the shipped processor and UI in Node/jsdom; they do not establish rendered-browser/Web Audio compatibility.

| Requirement/invariant | Implementation | Verification/evidence |
|---|---|---|
| Public-only web connections across DNS/redirects | `networking.py`, URL validation | Guarded socket, mixed DNS, rebinding, redirect and real HTTP fixtures in `test_hardening.py` |
| No anonymous use of owner cookies | Admission capability, snapshots, cache namespaces/generations | Queued-cookie and invalidation regressions in `test_final_validation.py`; auth tests in `test_hardening.py` |
| Cancellation stays terminal | Locked task updates, isolated browser operation, DOM operation IDs | In-flight hook injection, 30 contention rounds, overlapping browser decode and delayed cancel response |
| Requested MP3 trim bitrate and title retained | FFmpeg arguments, independent ffprobe oracle | Real 320 kbps MP3 fixture in `test_final_validation.py` |
| Invalid out-of-duration trim preserves input | Pre-trim ffprobe validation | Original-byte comparison and expected error in `test_final_validation.py` |
| Requested CLI container applied to combined source | Explicit yt-dlp remux postprocessor | MP4/MKV CLI option regression; local FFmpeg integration fixtures |
| Bounded bodies and resources | Byte buffer, admission limits, queues/subscriber cap | 50,000-chunk memory stress, proxy cancellation/failure/size tests, capacity regressions |
| Complete files only, active files retained | Completion record, containment, terminal retention | Restart, partial-output, traversal and active-cleanup tests |
| No metadata XSS or stale cancelled UI | DOM text properties and asynchronous ownership | `test_app.js` and strict-CSP checks |
| Portable/reproducible build | Runtime/npm locks, CI matrix and Docker | Fresh venv/npm install plus published Ubuntu/Windows/container CI; see AUDIT for exact evidence |

Unverified critical external behaviors: live platform extraction, rendered-browser codec/audio decoding and actual production TLS/Nginx/systemd provisioning. These are documented constraints, not passing gates. No audit or test count proves zero defects.
