import argparse
import math
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any

import yt_dlp
from rich.console import Console
from yt_dlp.utils import download_range_func

from security import validate_timestamp_strict

console = Console()

# How many times to retry a download after a transient (network-ish) failure,
# and how long to wait between attempts (seconds), doubling each retry.
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BACKOFF = 2.0

# Substrings that indicate the failure is almost certainly permanent and
# retrying would just waste time (bad URL, no matching extractor, etc.).
_NON_RETRYABLE_MARKERS = (
    "unsupported url",
    "no video formats found",
    "unable to extract",
    "is not a valid url",
    "404",
    "403",
    "geo-restricted",
    "geo blocked",
)


def classify_error(exc: Exception) -> str:
    """Return a short, human-friendly diagnosis for a download exception."""
    msg = str(exc).lower()
    if (
        "confirm you’re not a bot" in msg
        or "confirm you're not a bot" in msg
        or ("bot" in msg and ("sign in" in msg or "cookies" in msg))
    ):
        return (
            "YouTube anti-bot verification triggered ('Sign in to confirm you’re not a bot'). "
            "YouTube requires session verification. Pass a cookies file with --cookies cookies.txt or switch connection/IP."
        )
    if "unsupported url" in msg:
        return (
            "This site/URL isn't recognized by any yt-dlp extractor "
            "(and the generic fallback couldn't find a playable stream either). "
            "Either yt-dlp needs updating (`pip install -U yt-dlp`), or the site "
            "needs a dedicated extractor."
        )
    if "unable to extract" in msg or "no video formats found" in msg:
        return (
            "The extractor matched the site but couldn't find a playable stream. "
            "The page structure may have changed, or the video may be geo-blocked "
            "or require login."
        )
    if any(code in msg for code in ("403", "forbidden")):
        return "Access denied by the server (403) — may require authentication/cookies."
    if any(code in msg for code in ("404", "not found")):
        return "The page or resource was not found (404) — check the URL is still valid."
    if any(term in msg for term in ("timed out", "timeout", "connection", "network")):
        return "Network-level failure — likely transient, safe to retry."
    return "Unclassified error — see raw message above."


def is_retryable(exc: Exception) -> bool:
    """Heuristic: should we retry this failure, or is it permanent?"""
    msg = str(exc).lower()
    return not any(marker in msg for marker in _NON_RETRYABLE_MARKERS)


class RichLogger:
    def debug(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        console.print(f"[yellow]Warning:[/yellow] {msg}")

    def error(self, msg: str) -> None:
        console.print(f"[red]Error:[/red] {msg}")


def get_parser() -> argparse.ArgumentParser:
    """Create and return the argument parser."""
    parser = argparse.ArgumentParser(
        description="A versatile command-line and web video downloader for publicly available platforms."
    )
    parser.add_argument(
        "url",
        nargs="?",
        help="The URL of the video to download. Optional if --batch-file or --web is used.",
    )
    parser.add_argument(
        "-a", "--batch-file", help="File containing URLs to download, one per line."
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=["mp4", "mkv", "best"],
        default="best",
        help="Specify the desired video format. Default is 'best'.",
    )
    parser.add_argument(
        "-q",
        "--quality",
        choices=["best", "1080p", "720p", "480p", "worst"],
        default="best",
        help="Specify the desired video quality.",
    )
    parser.add_argument(
        "--extract-audio", action="store_true", help="Extract audio only (saves as MP3)."
    )
    parser.add_argument("--subtitles", action="store_true", help="Download subtitles if available.")
    parser.add_argument(
        "--no-playlist",
        action="store_true",
        help="Download only the video, if the URL refers to a video and a playlist.",
    )
    parser.add_argument(
        "--embed-metadata",
        action="store_true",
        help="Embed video metadata (title, artist, etc.) in the output file.",
    )
    parser.add_argument(
        "--embed-thumbnail", action="store_true", help="Embed video thumbnail as cover art."
    )
    parser.add_argument(
        "-o", "--output", default="%(title)s.%(ext)s", help="Output filename template."
    )
    parser.add_argument(
        "--list-formats",
        action="store_true",
        help="List available formats for the URL(s) and exit, without downloading.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=DEFAULT_MAX_RETRIES,
        help=f"Number of retry attempts on transient failure (default: {DEFAULT_MAX_RETRIES}).",
    )
    parser.add_argument(
        "--retry-backoff",
        type=float,
        default=DEFAULT_RETRY_BACKOFF,
        help=f"Base seconds to wait between retries, doubles each attempt (default: {DEFAULT_RETRY_BACKOFF}).",
    )
    parser.add_argument("--trim-start", help="Start timestamp for trimming (e.g. 00:01:30).")
    parser.add_argument("--trim-end", help="End timestamp for trimming (e.g. 00:02:45).")
    parser.add_argument(
        "--cookies", help="Path to cookies file (e.g. cookies.txt) to bypass anti-bot verification."
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="Launch the modern StreamFab Web interface (NoTube alternative).",
    )
    parser.add_argument(
        "--host",
        default=os.getenv("STREAMFAB_HOST", "127.0.0.1"),
        help="Web server host address (default: 127.0.0.1 or $STREAMFAB_HOST).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=os.getenv("STREAMFAB_PORT", "8000"),
        help="Web server port (default: 8000 or $STREAMFAB_PORT).",
    )
    parser.add_argument(
        "--open-browser",
        action="store_true",
        help="Automatically open the default web browser when starting the web server.",
    )

    return parser


def build_ydl_opts(args: argparse.Namespace) -> dict[str, Any]:
    """Build yt-dlp options dictionary based on parsed arguments."""
    ydl_opts: dict[str, Any] = {
        "outtmpl": args.output,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": getattr(args, "no_playlist", False),
        "logger": RichLogger(),
        "progress_hooks": [progress_hook],
    }

    # Cookies support
    cookies_path = getattr(args, "cookies", None)
    if cookies_path:
        ydl_opts["cookiefile"] = cookies_path

    # Format and quality selection
    if args.extract_audio:
        ydl_opts["format"] = "bestaudio/best"
        ydl_opts["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ]
    else:
        # Determine format string based on quality
        format_str = "bestvideo+bestaudio/best"
        if args.quality == "1080p":
            format_str = "bestvideo[height<=1080]+bestaudio/best[height<=1080]"
        elif args.quality == "720p":
            format_str = "bestvideo[height<=720]+bestaudio/best[height<=720]"
        elif args.quality == "480p":
            format_str = "bestvideo[height<=480]+bestaudio/best[height<=480]"
        elif args.quality == "worst":
            format_str = "worst"

        # Determine merge format if specific extension is requested
        if args.format in ["mp4", "mkv"]:
            ydl_opts["merge_output_format"] = args.format

            def get_fmt(res_limit: str = "") -> str:
                if args.format == "mp4":
                    return f"bestvideo{res_limit}[ext=mp4]+bestaudio[ext=m4a]/bestvideo{res_limit}+bestaudio/best{res_limit}"
                else:
                    return f"bestvideo{res_limit}+bestaudio/best{res_limit}"

            if args.quality == "1080p":
                format_str = get_fmt("[height<=1080]")
            elif args.quality == "720p":
                format_str = get_fmt("[height<=720]")
            elif args.quality == "480p":
                format_str = get_fmt("[height<=480]")
            elif args.quality == "worst":
                format_str = "worst" if args.format == "mkv" else f"worst[ext={args.format}]/worst"
            else:  # best
                format_str = get_fmt("")

        ydl_opts["format"] = format_str

    # Subtitles
    if getattr(args, "subtitles", False):
        ydl_opts["writesubtitles"] = True
        ydl_opts["subtitleslangs"] = ["en", "all"]

    # Metadata and Post-processing
    postprocessors = ydl_opts.get("postprocessors", [])
    if getattr(args, "embed_metadata", False):
        postprocessors.append({"key": "FFmpegMetadata"})
    if getattr(args, "embed_thumbnail", False):
        ydl_opts["writethumbnail"] = True
        postprocessors.append({"key": "EmbedThumbnail"})

    if postprocessors:
        ydl_opts["postprocessors"] = postprocessors

    # Validated segment ranges are applied to downloads, not arbitrary postprocessors.
    trim_start = getattr(args, "trim_start", None)
    trim_end = getattr(args, "trim_end", None)
    start = validate_timestamp_strict(trim_start)
    end = validate_timestamp_strict(trim_end)
    if end is not None and end <= (start or 0):
        raise ValueError("End time must be greater than start time.")
    if start is not None or end is not None:
        ydl_opts["download_ranges"] = download_range_func(
            None, [(start or 0, end if end is not None else float("inf"))]
        )

    return ydl_opts


def progress_hook(d: dict) -> None:
    if d["status"] == "downloading":
        percent = d.get("_percent_str", "N/A")
        speed = d.get("_speed_str", "N/A")
        eta = d.get("_eta_str", "N/A")
        sys.stdout.write(f"\r\033[K\033[36mDownloading...\033[0m {percent} at {speed} ETA {eta}")
        sys.stdout.flush()
    elif d["status"] == "finished":
        print()
        console.print("[green]Download finished, processing...[/green]")


def download_video(
    urls: list[str],
    ydl_opts: dict[str, Any],
    max_retries: int = DEFAULT_MAX_RETRIES,
    retry_backoff: float = DEFAULT_RETRY_BACKOFF,
    sleep_fn=time.sleep,
) -> bool:
    """Download videos using yt-dlp, retrying transient failures."""
    if max_retries < 0 or not math.isfinite(retry_backoff) or retry_backoff < 0:
        raise ValueError("Retry count and backoff must be finite and non-negative.")
    last_exc: Exception | None = None
    attempt = 0

    while attempt <= max_retries:
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                error_code = ydl.download(urls)
                return error_code == 0
        except Exception as e:
            last_exc = e
            diagnosis = classify_error(e)

            if not is_retryable(e) or attempt == max_retries:
                console.print(f"[bold red]Critical error during download:[/bold red] {e}")
                console.print(f"[yellow]Diagnosis:[/yellow] {diagnosis}")
                return False

            attempt += 1
            wait = retry_backoff * (2 ** (attempt - 1))
            console.print(
                f"[yellow]Attempt {attempt}/{max_retries} failed ({e}). "
                f"Retrying in {wait:.1f}s...[/yellow]"
            )
            sleep_fn(wait)

    if last_exc is not None:
        console.print(f"[bold red]Critical error during download:[/bold red] {last_exc}")
    return False


def list_formats(urls: list[str], ydl_opts: dict[str, Any]) -> bool:
    """Print available formats for each URL without downloading."""
    list_opts = dict(ydl_opts)
    list_opts["listformats"] = True
    list_opts["quiet"] = False
    list_opts["no_warnings"] = False

    try:
        with yt_dlp.YoutubeDL(list_opts) as ydl:
            for url in urls:
                console.print(f"[bold blue]Formats for {url}:[/bold blue]")
                ydl.extract_info(url, download=False)
        return True
    except Exception as e:
        console.print(f"[bold red]Error listing formats:[/bold red] {e}")
        console.print(f"[yellow]Diagnosis:[/yellow] {classify_error(e)}")
        return False


def run_web_server(host: str = "127.0.0.1", port: int = 8000, open_browser: bool = False) -> None:
    """Launch the FastAPI web server with Uvicorn."""
    import uvicorn

    src_dir = Path(__file__).resolve().parent
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))
    log_level = os.getenv("STREAMFAB_LOG_LEVEL", "info").lower()
    console.print(
        f"[bold green]🚀 StreamFab Web UI running at:[/bold green] [bold cyan]http://{host}:{port}[/bold cyan]"
    )
    console.print("[dim]Press Ctrl+C to stop the server.[/dim]")
    if open_browser:
        browser_host = (
            "127.0.0.1" if host == "0.0.0.0" else "[::1]" if host in ("::", "::1") else host
        )

        def open_when_ready():
            import socket

            for _ in range(50):
                try:
                    with socket.create_connection(
                        ("::1" if browser_host == "[::1]" else browser_host, port), timeout=0.1
                    ):
                        webbrowser.open(f"http://{browser_host}:{port}")
                        return
                except OSError:
                    time.sleep(0.1)

        threading.Thread(target=open_when_ready, daemon=True).start()
    uvicorn.run("web_server:app", host=host, port=port, log_level=log_level, app_dir=str(src_dir))


def main() -> None:
    parser = get_parser()
    args = parser.parse_args()

    if getattr(args, "web", False):
        if not 1 <= args.port <= 65535:
            parser.error("Web port must be between 1 and 65535.")
        run_web_server(host=args.host, port=args.port, open_browser=args.open_browser)
        sys.exit(0)

    urls: list[str] = []
    if args.url:
        urls.append(args.url)

    if args.batch_file:
        try:
            with open(args.batch_file, encoding="utf-8-sig") as f:
                for line in f:
                    stripped_line = line.strip()
                    if stripped_line and not stripped_line.startswith("#"):
                        urls.append(stripped_line)
        except OSError as e:
            console.print(f"[bold red]Error reading batch file {args.batch_file}:[/bold red] {e}")
            sys.exit(1)

    if not urls:
        parser.error("You must provide a URL or a batch file containing URLs.")

    if args.max_retries < 0 or not math.isfinite(args.retry_backoff) or args.retry_backoff < 0:
        parser.error("Retry count and backoff must be finite and non-negative.")
    try:
        ydl_opts = build_ydl_opts(args)
    except ValueError as exc:
        parser.error(str(exc))

    if args.list_formats:
        console.print(f"[bold blue]Listing formats for {len(urls)} item(s)...[/bold blue]")
        success = list_formats(urls, ydl_opts)
        sys.exit(0 if success else 1)

    console.print(f"[bold blue]Preparing to download {len(urls)} item(s)...[/bold blue]")

    success = download_video(
        urls,
        ydl_opts,
        max_retries=args.max_retries,
        retry_backoff=args.retry_backoff,
    )
    if success:
        console.print("[bold green]✔ All download(s) completed successfully.[/bold green]")
        sys.exit(0)
    else:
        console.print("[bold red]✖ Some download(s) failed.[/bold red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
