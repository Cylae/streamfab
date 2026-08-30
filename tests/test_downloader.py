import os
import pytest
from unittest.mock import patch, mock_open, MagicMock
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from downloader import get_parser, build_ydl_opts, download_video, main

# --- Existing Parser and Options Tests ---

def test_parser_defaults():
    parser = get_parser()
    args = parser.parse_args(['http://example.com/video'])

    assert args.url == 'http://example.com/video'
    assert args.format == 'best'
    assert args.quality == 'best'
    assert args.extract_audio is False
    assert args.subtitles is False
    assert args.output == '%(title)s.%(ext)s'

def test_parser_custom_args():
    parser = get_parser()
    args = parser.parse_args([
        'http://example.com/video',
        '-f', 'mp4',
        '-q', '720p',
        '--extract-audio',
        '--subtitles',
        '--no-playlist',
        '--embed-metadata',
        '--embed-thumbnail',
        '-o', 'custom.%(ext)s'
    ])

    assert args.url == 'http://example.com/video'
    assert args.format == 'mp4'
    assert args.quality == '720p'
    assert args.extract_audio is True
    assert args.subtitles is True
    assert args.no_playlist is True
    assert args.embed_metadata is True
    assert args.embed_thumbnail is True
    assert args.output == 'custom.%(ext)s'

def test_parser_batch_file():
    parser = get_parser()
    args = parser.parse_args(['-a', 'urls.txt'])
    assert args.batch_file == 'urls.txt'
    assert args.url is None

def test_build_ydl_opts_defaults():
    parser = get_parser()
    args = parser.parse_args(['http://example.com/video'])

    opts = build_ydl_opts(args)

    assert opts['outtmpl'] == '%(title)s.%(ext)s'
    assert opts['quiet'] is True
    assert opts['no_warnings'] is True
    assert opts['format'] == 'bestvideo+bestaudio/best'
    assert 'writesubtitles' not in opts
    assert 'logger' in opts
    assert 'progress_hooks' in opts

def test_build_ydl_opts_audio():
    parser = get_parser()
    args = parser.parse_args(['http://example.com/video', '--extract-audio'])

    opts = build_ydl_opts(args)

    assert opts['format'] == 'bestaudio/best'
    assert len(opts['postprocessors']) == 1
    assert opts['postprocessors'][0]['key'] == 'FFmpegExtractAudio'
    assert opts['postprocessors'][0]['preferredcodec'] == 'mp3'

def test_build_ydl_opts_format_quality():
    parser = get_parser()
    args = parser.parse_args(['http://example.com/video', '-f', 'mp4', '-q', '1080p'])
    opts = build_ydl_opts(args)
    assert opts['format'] == 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[height<=1080]'
    assert opts['merge_output_format'] == 'mp4'

def test_build_ydl_opts_subtitles():
    parser = get_parser()
    args = parser.parse_args(['http://example.com/video', '--subtitles'])

    opts = build_ydl_opts(args)

    assert opts['writesubtitles'] is True
    assert 'en' in opts['subtitleslangs']

def test_build_ydl_opts_metadata_thumbnail():
    parser = get_parser()
    args = parser.parse_args(['http://example.com/video', '--embed-metadata', '--embed-thumbnail'])

    opts = build_ydl_opts(args)

    assert opts['writethumbnail'] is True
    keys = [p['key'] for p in opts['postprocessors']]
    assert 'FFmpegMetadata' in keys
    assert 'EmbedThumbnail' in keys

def test_build_ydl_opts_no_playlist():
    parser = get_parser()
    args = parser.parse_args(['http://example.com/video', '--no-playlist'])

    opts = build_ydl_opts(args)

    assert opts['noplaylist'] is True


@patch('sys.stdout.write')
@patch('sys.stdout.flush')
def test_progress_hook_downloading(mock_flush, mock_write):
    from downloader import progress_hook
    d = {'status': 'downloading', '_percent_str': '50%', '_speed_str': '1MiB/s', '_eta_str': '00:01'}
    progress_hook(d)
    mock_write.assert_called_once()
    mock_flush.assert_called_once()

@patch('downloader.console.print')
def test_progress_hook_finished(mock_print):
    from downloader import progress_hook
    d = {'status': 'finished'}
    progress_hook(d)
    mock_print.assert_called_once_with("[green]Download finished, processing...[/green]")

def test_rich_logger():
    from downloader import RichLogger
    logger = RichLogger()
    # Check that it has the required methods (can't easily assert on output without mocking console in the same file context, but testing existence is enough)
    assert hasattr(logger, 'debug')
    assert hasattr(logger, 'warning')
    assert hasattr(logger, 'error')
    logger.debug("test") # Should do nothing
    with patch('downloader.console.print') as mock_print:
        logger.warning("test warn")
        mock_print.assert_called_once_with("[yellow]Warning:[/yellow] test warn")
    with patch('downloader.console.print') as mock_print:
        logger.error("test err")
        mock_print.assert_called_once_with("[red]Error:[/red] test err")


# --- New Extended Tests ---

@pytest.mark.parametrize("quality,expected_fmt", [
    ("best", "bestvideo+bestaudio/best"),
    ("1080p", "bestvideo[height<=1080]+bestaudio/best[height<=1080]"),
    ("720p", "bestvideo[height<=720]+bestaudio/best[height<=720]"),
    ("480p", "bestvideo[height<=480]+bestaudio/best[height<=480]"),
    ("worst", "worst"),
])
def test_build_ydl_opts_best_format_all_qualities(quality, expected_fmt):
    parser = get_parser()
    args = parser.parse_args(['http://example.com', '-q', quality])
    opts = build_ydl_opts(args)
    assert opts['format'] == expected_fmt

@pytest.mark.parametrize("quality,expected_fmt", [
    ("best", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"),
    ("1080p", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[height<=1080]"),
    ("720p", "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=720]+bestaudio/best[height<=720]"),
    ("480p", "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=480]+bestaudio/best[height<=480]"),
    ("worst", "worst[ext=mp4]/worst"),
])
def test_build_ydl_opts_mp4_all_qualities(quality, expected_fmt):
    parser = get_parser()
    args = parser.parse_args(['http://example.com', '-f', 'mp4', '-q', quality])
    opts = build_ydl_opts(args)
    assert opts['format'] == expected_fmt

@pytest.mark.parametrize("quality,expected_fmt", [
    ("best", "bestvideo[ext=mkv]+bestaudio/best[ext=mkv]"),
    ("1080p", "bestvideo[height<=1080][ext=mkv]+bestaudio/best[height<=1080][ext=mkv]"),
    ("720p", "bestvideo[height<=720][ext=mkv]+bestaudio/best[height<=720][ext=mkv]"),
    ("480p", "bestvideo[height<=480][ext=mkv]+bestaudio/best[height<=480][ext=mkv]"),
    ("worst", "worst[ext=mkv]/worst"),
])
def test_build_ydl_opts_mkv_all_qualities(quality, expected_fmt):
    parser = get_parser()
    args = parser.parse_args(['http://example.com', '-f', 'mkv', '-q', quality])
    opts = build_ydl_opts(args)
    assert opts['format'] == expected_fmt

@patch('downloader.yt_dlp.YoutubeDL')
def test_download_video_success(mock_ydl):
    instance = mock_ydl.return_value.__enter__.return_value
    instance.download.return_value = 0 # success
    success = download_video(['http://example.com'], {})
    assert success is True
    instance.download.assert_called_once_with(['http://example.com'])

@patch('downloader.yt_dlp.YoutubeDL')
def test_download_video_failure(mock_ydl):
    instance = mock_ydl.return_value.__enter__.return_value
    instance.download.return_value = 1 # failure error code
    success = download_video(['http://example.com'], {})
    assert success is False
    instance.download.assert_called_once_with(['http://example.com'])

@patch('downloader.yt_dlp.YoutubeDL')
def test_download_video_exception(mock_ydl):
    instance = mock_ydl.return_value.__enter__.return_value
    instance.download.side_effect = Exception("Network error")
    success = download_video(['http://example.com'], {})
    assert success is False

@patch('sys.argv', ['downloader.py', 'http://example.com'])
@patch('downloader.download_video')
def test_main_single_url_success(mock_download):
    mock_download.return_value = True
    with pytest.raises(SystemExit) as excinfo:
        main()
    assert excinfo.value.code == 0
    mock_download.assert_called_once()
    assert mock_download.call_args[0][0] == ['http://example.com']

@patch('sys.argv', ['downloader.py', 'http://example.com'])
@patch('downloader.download_video')
def test_main_single_url_failure(mock_download):
    mock_download.return_value = False
    with pytest.raises(SystemExit) as excinfo:
        main()
    assert excinfo.value.code == 1

@patch('sys.argv', ['downloader.py', '-a', 'batch.txt'])
@patch('builtins.open', new_callable=mock_open, read_data="http://url1.com\n#comment\n\nhttp://url2.com\n")
@patch('downloader.download_video')
def test_main_batch_file(mock_download, mock_file):
    mock_download.return_value = True
    with pytest.raises(SystemExit) as excinfo:
        main()
    assert excinfo.value.code == 0
    mock_download.assert_called_once()
    assert mock_download.call_args[0][0] == ['http://url1.com', 'http://url2.com']

@patch('sys.argv', ['downloader.py', '-a', 'nonexistent.txt'])
@patch('builtins.open', side_effect=IOError("File not found"))
def test_main_batch_file_ioerror(mock_file):
    with pytest.raises(SystemExit) as excinfo:
        main()
    assert excinfo.value.code == 1

@patch('sys.argv', ['downloader.py', '--invalid-argument'])
def test_main_invalid_args():
    with pytest.raises(SystemExit) as excinfo:
        main()
    assert excinfo.value.code == 2

@patch('sys.argv', ['downloader.py'])
def test_main_no_urls():
    with pytest.raises(SystemExit) as excinfo:
        main()
    assert excinfo.value.code == 2 # argparse error code

@patch('sys.argv', ['downloader.py', 'http://single.com', '-a', 'batch.txt'])
@patch('builtins.open', new_callable=mock_open, read_data="http://batch1.com\nhttp://batch2.com\n")
@patch('downloader.download_video')
def test_main_url_and_batch_file(mock_download, mock_file):
    mock_download.return_value = True
    with pytest.raises(SystemExit) as excinfo:
        main()
    assert excinfo.value.code == 0
    mock_download.assert_called_once()
    assert mock_download.call_args[0][0] == ['http://single.com', 'http://batch1.com', 'http://batch2.com']

@patch('sys.argv', ['downloader.py', '-a', 'batch.txt'])
@patch('builtins.open', new_callable=mock_open, read_data="\n#only comments\n")
def test_main_batch_file_empty(mock_file):
    with pytest.raises(SystemExit) as excinfo:
        main()
    assert excinfo.value.code == 2 # argparse error code due to missing urls
