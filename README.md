# Versatile Video Downloader

A powerful and versatile command-line video downloader written in Python. It supports downloading publicly available, non-DRM protected content from numerous platforms.

## Features

*   **Download Videos:** Download from any platform supported by `yt-dlp`.
*   **Format Selection:** Choose between `mp4`, `mkv`, or let the tool pick the `best` format.
*   **Quality Selection:** Specify video quality (`best`, `1080p`, `720p`, `480p`, `worst`).
*   **Audio Extraction:** Extract audio only and save it as an MP3 file.
*   **Subtitles:** Automatically download subtitles when available.
*   **Batch Downloading:** Read multiple URLs from a text file to download in bulk.
*   **Playlist Control:** Choose whether to download an entire playlist or just a single video.
*   **Metadata Embedding:** Embed video metadata (title, author) and thumbnails directly into the downloaded file.
*   **Custom Output Naming:** Customize the output file name template.

## Requirements

*   Python 3.6 or higher
*   `yt-dlp`
*   `pytest` (for running tests)
*   `ffmpeg` (highly recommended for format conversion and audio extraction)

## Installation

1.  Clone this repository or download the source files.
2.  Install the required Python packages:

```bash
pip install -r requirements.txt
```

3.  Ensure `ffmpeg` is installed on your system.
    *   **Ubuntu/Debian:** `sudo apt install ffmpeg`
    *   **macOS:** `brew install ffmpeg`
    *   **Windows:** Download from the official site and add it to your PATH.

## Usage

Run the `downloader.py` script from the `src` directory:

```bash
python3 src/downloader.py [options] [URL]
```

### Options

*   `URL`: The URL of the video to download (Optional if `--batch-file` is provided).
*   `-a`, `--batch-file`: File containing URLs to download, one per line.
*   `-f`, `--format`: Specify the desired video format (`mp4`, `mkv`, `best`). Default is `best`.
*   `-q`, `--quality`: Specify the desired video quality (`best`, `1080p`, `720p`, `480p`, `worst`). Default is `best`.
*   `--extract-audio`: Extract audio only (saves as MP3).
*   `--subtitles`: Download subtitles if available.
*   `--no-playlist`: Download only the single video, ignoring the rest of the playlist if the URL is part of one.
*   `--embed-metadata`: Embed video metadata (title, artist, etc.) in the output file.
*   `--embed-thumbnail`: Embed the video's thumbnail as cover art.
*   `-o`, `--output`: Output filename template (e.g., `%(title)s.%(ext)s`).

### Examples

**Download a video with default settings (best quality):**
```bash
python3 src/downloader.py "https://www.youtube.com/watch?v=BaW_jenozKc"
```

**Download a video in 720p MP4 format:**
```bash
python3 src/downloader.py -f mp4 -q 720p "https://www.youtube.com/watch?v=BaW_jenozKc"
```

**Extract only the audio as an MP3:**
```bash
python3 src/downloader.py --extract-audio "https://www.youtube.com/watch?v=BaW_jenozKc"
```

**Download a video with subtitles and save to a specific directory:**
```bash
python3 src/downloader.py --subtitles -o "~/Downloads/%(title)s.%(ext)s" "https://www.youtube.com/watch?v=BaW_jenozKc"
```

**Download a video with embedded metadata and thumbnail:**
```bash
python3 src/downloader.py --embed-metadata --embed-thumbnail "https://www.youtube.com/watch?v=BaW_jenozKc"
```

**Download multiple videos from a text file (e.g., `urls.txt`):**
```bash
python3 src/downloader.py -a urls.txt
```

## Testing

To run the automated tests, execute `pytest` from the root directory:

```bash
pytest tests/
```

## Disclaimer

This tool is intended solely for downloading unprotected, publicly available content. It does not bypass Digital Rights Management (DRM) or download protected content from commercial streaming platforms. Users are responsible for ensuring they have the legal right to download and use the content they access with this tool.
