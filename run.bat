@echo off
setlocal enabledelayedexpansion
title L.A.R.P — Logic AI Robotic Program
cd /d "%~dp0"

:: Clear screen
cls

:: Check config.json exists
if not exist "config.json" (
    echo.
    echo  [ERROR] config.json not found!
    echo  Please run install.bat first or rename config.example.json to config.json.
    echo.
    pause
    exit /b 1
)

:: Check assets/models folder has a model
set MODEL_FOUND=0
if exist "assets\models" (
    for /f %%f in ('dir /b /s "assets\models\*.pt" 2^>nul') do set MODEL_FOUND=1
)

if "%MODEL_FOUND%"=="0" (
    echo.
    echo  [WARNING] No YOLO model (.pt) found in assets\models\
    echo  The bot will try to download it automatically on first launch.
    echo.
)

echo.
echo  ============================================================
echo   Starting L.A.R.P - Logic AI Robotic Program
echo  ============================================================
echo.

:: Try to run with 'python', if fails try 'py'
python --version >nul 2>&1
if %errorlevel% equ 0 (
    python main.py
) else (
    py --version >nul 2>&1
    if %errorlevel% equ 0 (
        py main.py
    ) else (
        echo [ERROR] Python is not installed or not in PATH!
        echo Please follow the FAQ in README.md to add Python to your environment variables.
        pause
        exit /b 1
    )
)

:: Keep window open if it crashes or finishes
if %errorlevel% neq 0 (
    echo.
    echo  [ERROR] Bot exited with code %errorlevel%.
    echo.
    pause
) else (
    echo.
    echo  [INFO] Bot session ended normally.
    echo.
    pause
)
