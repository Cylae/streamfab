import os
import pytest
from unittest.mock import patch
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from downloader import get_parser, build_ydl_opts

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
    assert opts['quiet'] is False
    assert opts['no_warnings'] is True
    assert opts['format'] == 'bestvideo+bestaudio/best'
    assert 'writesubtitles' not in opts

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

    assert 'bestvideo[height<=1080][ext=mp4]' in opts['format']
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
