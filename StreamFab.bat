@echo off
setlocal
title StreamFab
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
    if errorlevel 1 (
        echo [ERROR] Install Python 3.10 or newer and add it to PATH.
        pause
        exit /b 1
    )
    python -m venv .venv
    if errorlevel 1 exit /b 1
)

".venv\Scripts\python.exe" -m pip install -r requirements.lock
if errorlevel 1 (
    echo [ERROR] Dependency installation failed.
    pause
    exit /b 1
)
where ffmpeg >nul 2>nul
if errorlevel 1 echo [WARNING] Server conversion requires FFmpeg. Install with winget install Gyan.FFmpeg
".venv\Scripts\python.exe" src/downloader.py --web --open-browser --port 8000
if errorlevel 1 pause
