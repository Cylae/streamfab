import argparse
import sys
import yt_dlp

def get_parser():
    """Create and return the argument parser."""
    parser = argparse.ArgumentParser(
        description="A versatile command-line video downloader for publicly available platforms."
    )
    parser.add_argument("url", help="The URL of the video to download.")
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
        "-o", "--output",
        default="%(title)s.%(ext)s",
        help="Output filename template."
    )

    return parser

def build_ydl_opts(args):
    """Build yt-dlp options dictionary based on parsed arguments."""
    ydl_opts = {
        'outtmpl': args.output,
        'quiet': False,
        'no_warnings': True,
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
            # For mp4, try to get compatible streams directly to avoid unnecessary transcoding if possible,
            # but preserve the resolution constraint we built earlier.
            if args.format == 'mp4':
                # Re-apply resolution limits but enforce mp4/m4a compatibility where possible
                if args.quality == '1080p':
                    format_str = 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[height<=1080]'
                elif args.quality == '720p':
                    format_str = 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=720]+bestaudio/best[height<=720]'
                elif args.quality == '480p':
                    format_str = 'bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=480]+bestaudio/best[height<=480]'
                elif args.quality == 'worst':
                    format_str = 'worst[ext=mp4]/worst'
                else: # best
                    format_str = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best'
            else:
                # For mkv or other formats, append the extension request to the existing format_str
                format_str += f'[ext={args.format}]'

        ydl_opts['format'] = format_str

    # Subtitles
    if args.subtitles:
        ydl_opts['writesubtitles'] = True
        ydl_opts['subtitleslangs'] = ['en', 'all'] # try english, fallback to all

    return ydl_opts

def download_video(url, ydl_opts):
    """Download video using yt-dlp."""
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        return True
    except Exception as e:
        print(f"Error downloading video: {e}", file=sys.stderr)
        return False

def main():
    parser = get_parser()
    args = parser.parse_args()

    print(f"Preparing to download: {args.url}")
    ydl_opts = build_ydl_opts(args)

    success = download_video(args.url, ydl_opts)
    if success:
        print("Download completed successfully.")
        sys.exit(0)
    else:
        print("Download failed.")
        sys.exit(1)

if __name__ == "__main__":
    main()
