@echo off
title StreamFab PRO - Windows Desktop Launcher
setlocal

echo =======================================================
echo          StreamFab PRO - High Performance Engine
echo   Ultra-Fast Video & Audio Downloader & Converter
echo =======================================================
echo.

:: Check Python installation
where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python is not found in PATH!
    echo Please install Python 3.10 or higher from https://python.org
    echo Make sure to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

:: Check FFmpeg installation
where ffmpeg >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [WARNING] FFmpeg was not detected in your PATH.
    echo High-resolution merging, audio conversion, and trimming require FFmpeg.
    echo You can install it using: winget install Gyan.FFmpeg
    echo.
)

echo Starting StreamFab Web UI and opening your default browser...
echo Local Server: http://127.0.0.1:8000
echo Press Ctrl+C in this window to stop the server anytime.
echo.

python src/downloader.py --web --open-browser --port 8000

if %ERRORLEVEL% neq 0 (
    echo.
    echo [INFO] StreamFab stopped.
    pause
)
