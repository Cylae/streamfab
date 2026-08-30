import argparse
import sys
import time
from typing import List, Dict, Any, Optional
import yt_dlp
from rich.console import Console

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
    "geo",
)


def classify_error(exc: Exception) -> str:
    """Return a short, human-friendly diagnosis for a download exception."""
    msg = str(exc).lower()
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
        description="A versatile command-line video downloader for publicly available platforms."
    )
    parser.add_argument(
        "url",
        nargs="?",
        help="The URL of the video to download. Optional if --batch-file is used."
    )
    parser.add_argument(
        "-a", "--batch-file",
        help="File containing URLs to download, one per line."
    )
    parser.add_argument(
        "-f", "--format",
        choices=["mp4", "mkv", "best"],
        default="best",
        help="Specify the desired video format. Default is 'best'."
    )
    parser.add_argument(
        "-q", "--quality",
        choices=["best", "1080p", "720p", "480p", "worst"],
        default="best",
        help="Specify the desired video quality."
    )
    parser.add_argument(
        "--extract-audio",
        action="store_true",
        help="Extract audio only (saves as MP3)."
    )
    parser.add_argument(
        "--subtitles",
        action="store_true",
        help="Download subtitles if available."
    )
    parser.add_argument(
        "--no-playlist",
        action="store_true",
        help="Download only the video, if the URL refers to a video and a playlist."
    )
    parser.add_argument(
        "--embed-metadata",
        action="store_true",
        help="Embed video metadata (title, artist, etc.) in the output file."
    )
    parser.add_argument(
        "--embed-thumbnail",
        action="store_true",
        help="Embed video thumbnail as cover art."
    )
    parser.add_argument(
        "-o", "--output",
        default="%(title)s.%(ext)s",
        help="Output filename template."
    )
    parser.add_argument(
        "--list-formats",
        action="store_true",
        help="List available formats for the URL(s) and exit, without downloading."
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=DEFAULT_MAX_RETRIES,
        help=f"Number of retry attempts on transient failure (default: {DEFAULT_MAX_RETRIES})."
    )
    parser.add_argument(
        "--retry-backoff",
        type=float,
        default=DEFAULT_RETRY_BACKOFF,
        help=f"Base seconds to wait between retries, doubles each attempt (default: {DEFAULT_RETRY_BACKOFF})."
    )

    return parser

def build_ydl_opts(args: argparse.Namespace) -> Dict[str, Any]:
    """Build yt-dlp options dictionary based on parsed arguments."""
    ydl_opts: Dict[str, Any] = {
        'outtmpl': args.output,
        'quiet': True,
        'no_warnings': True,
        'noplaylist': args.no_playlist,
        'logger': RichLogger(),
        'progress_hooks': [progress_hook],
    }

    # Format and quality selection
    if args.extract_audio:
        ydl_opts['format'] = 'bestaudio/best'
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]
    else:
        # Determine format string based on quality
        format_str = 'bestvideo+bestaudio/best'
        if args.quality == '1080p':
            format_str = 'bestvideo[height<=1080]+bestaudio/best[height<=1080]'
        elif args.quality == '720p':
            format_str = 'bestvideo[height<=720]+bestaudio/best[height<=720]'
        elif args.quality == '480p':
            format_str = 'bestvideo[height<=480]+bestaudio/best[height<=480]'
        elif args.quality == 'worst':
            format_str = 'worst'

        # Determine merge format if specific extension is requested
        if args.format in ['mp4', 'mkv']:
            ydl_opts['merge_output_format'] = args.format

            # Helper to generate format string with constraints
            def get_fmt(res_limit: str = "") -> str:
                if args.format == 'mp4':
                    return f'bestvideo{res_limit}[ext=mp4]+bestaudio[ext=m4a]/bestvideo{res_limit}+bestaudio/best{res_limit}'
                else:
                    # For MKV, do not enforce the extension on the downloaded streams,
                    # because platforms rarely host native MKV streams. Let yt-dlp
                    # download the best available and merge them into MKV later.
                    return f'bestvideo{res_limit}+bestaudio/best{res_limit}'

            if args.quality == '1080p':
                format_str = get_fmt("[height<=1080]")
            elif args.quality == '720p':
                format_str = get_fmt("[height<=720]")
            elif args.quality == '480p':
                format_str = get_fmt("[height<=480]")
            elif args.quality == 'worst':
                format_str = f'worst' if args.format == 'mkv' else f'worst[ext={args.format}]/worst'
            else: # best
                format_str = get_fmt("")

        ydl_opts['format'] = format_str

    # Subtitles
    if args.subtitles:
        ydl_opts['writesubtitles'] = True
        ydl_opts['subtitleslangs'] = ['en', 'all'] # try english, fallback to all

    # Metadata and Post-processing
    postprocessors = ydl_opts.get('postprocessors', [])
    if args.embed_metadata:
        postprocessors.append({'key': 'FFmpegMetadata'})
    if args.embed_thumbnail:
        ydl_opts['writethumbnail'] = True
        postprocessors.append({'key': 'EmbedThumbnail'})

    if postprocessors:
        ydl_opts['postprocessors'] = postprocessors

    return ydl_opts

def progress_hook(d: dict) -> None:
    if d['status'] == 'downloading':
        percent = d.get('_percent_str', 'N/A')
        speed = d.get('_speed_str', 'N/A')
        eta = d.get('_eta_str', 'N/A')
        filename = d.get('filename', 'video')
        # Only print a clean line that overrides the previous one
        # Using ANSI escape codes instead of rich tags since we use sys.stdout directly for \r magic
        sys.stdout.write(f"\r\033[K\033[36mDownloading...\033[0m {percent} at {speed} ETA {eta}")
        sys.stdout.flush()
    elif d['status'] == 'finished':
        print() # New line after the progress bar finishes
        console.print("[green]Download finished, processing...[/green]")

def download_video(
    urls: List[str],
    ydl_opts: Dict[str, Any],
    max_retries: int = DEFAULT_MAX_RETRIES,
    retry_backoff: float = DEFAULT_RETRY_BACKOFF,
    sleep_fn=time.sleep,
) -> bool:
    """Download videos using yt-dlp, retrying transient failures.

    Returns True if all downloads succeeded.
    """
    last_exc: Optional[Exception] = None
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

    # Unreachable in practice, but keeps type checkers happy.
    if last_exc is not None:
        console.print(f"[bold red]Critical error during download:[/bold red] {last_exc}")
    return False


def list_formats(urls: List[str], ydl_opts: Dict[str, Any]) -> bool:
    """Print available formats for each URL without downloading. Returns True on success."""
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

def main() -> None:
    parser = get_parser()
    args = parser.parse_args()

    urls: List[str] = []
    if args.url:
        urls.append(args.url)

    if args.batch_file:
        try:
            with open(args.batch_file, 'r') as f:
                for line in f:
                    stripped_line = line.strip()
                    if stripped_line and not stripped_line.startswith('#'):
                        urls.append(stripped_line)
        except IOError as e:
            console.print(f"[bold red]Error reading batch file {args.batch_file}:[/bold red] {e}")
            sys.exit(1)

    if not urls:
        parser.error("You must provide a URL or a batch file containing URLs.")

    ydl_opts = build_ydl_opts(args)

    if args.list_formats:
        console.print(f"[bold blue]Listing formats for {len(urls)} item(s)...[/bold blue]")
        success = list_formats(urls, ydl_opts)
        sys.exit(0 if success else 1)

    console.print(f"[bold blue]Preparing to download {len(urls)} item(s)...[/bold blue]")

    success = download_video(
        urls, ydl_opts,
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
