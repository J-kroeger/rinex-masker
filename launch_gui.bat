@echo off
echo Starting RINEX-Masker...

REM Check if running from dist (exe mode) or source (python mode)
if exist "%~dp0RINEX-Masker.exe" (
    start "" "%~dp0RINEX-Masker.exe"
    exit /b
)

REM Fallback: run from Python source
if exist "%~dp0main_gui.py" (
    python "%~dp0main_gui.py"
    if errorlevel 1 (
        echo.
        echo ERROR: Failed to start. Make sure Python 3.8+ is installed.
        echo Install dependencies: pip install -r requirements.txt
        pause
    )
) else (
    echo ERROR: Neither RINEX-Masker.exe nor main_gui.py found.
    echo Please run this from the RINEX-Masker directory.
    pause
)
