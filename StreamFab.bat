@echo off
title StreamFab PRO - Windows Desktop Launcher
setlocal

:: Navigate to script directory
cd /d "%~dp0"

echo =======================================================
echo          StreamFab PRO - High Performance Engine
echo   Ultra-Fast Video & Audio Downloader & Converter
echo =======================================================
echo.

:: Detect Python executable (virtualenv or system Python)
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

:: Check Python installation
where %PYTHON_EXE% >nul 2>nul
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

:: Check and install dependencies if missing
"%PYTHON_EXE%" -c "import fastapi, yt_dlp, uvicorn" >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [INFO] Missing Python dependencies detected. Installing requirements.txt...
    "%PYTHON_EXE%" -m pip install -r requirements.txt
    if %ERRORLEVEL% neq 0 (
        echo [ERROR] Failed to install required packages.
        pause
        exit /b 1
    )
    echo [SUCCESS] Dependencies installed successfully.
    echo.
)

echo Starting StreamFab Web UI and opening your default browser...
echo Local Server: http://127.0.0.1:8000
echo Press Ctrl+C in this window to stop the server anytime.
echo.

"%PYTHON_EXE%" src/downloader.py --web --open-browser --port 8000

if %ERRORLEVEL% neq 0 (
    echo.
    echo [INFO] StreamFab stopped.
    pause
)

