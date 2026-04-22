@echo off
setlocal EnableDelayedExpansion
title L.A.R.P — Installer

echo.
echo  ============================================================
echo   L.A.R.P - Logic AI Robotic Program
echo   Installer v1.0
echo  ============================================================
echo.

:: ── Step 1: Check Python ──────────────────────────────────────────────────────
echo  [1/5] Checking Python installation...
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [ERROR] Python not found!
    echo.
    echo  Please install Python 3.10 or newer from:
    echo  https://www.python.org/downloads/
    echo.
    echo  IMPORTANT: Check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo  [OK] Python %PY_VER% found.

:: Check version is 3.10+
for /f "tokens=1,2 delims=." %%a in ("%PY_VER%") do (
    set MAJOR=%%a
    set MINOR=%%b
)
if %MAJOR% LSS 3 (
    echo  [ERROR] Python 3.10 or newer is required. Found: %PY_VER%
    pause & exit /b 1
)
if %MAJOR% EQU 3 if %MINOR% LSS 10 (
    echo  [ERROR] Python 3.10 or newer is required. Found: %PY_VER%
    pause & exit /b 1
)

echo.

:: ── Step 2: Install PyTorch ───────────────────────────────────────────────────
echo  [2/5] PyTorch Installation
echo.
echo  Does this PC have an NVIDIA GPU?
echo  [Y] Yes - Install PyTorch with CUDA support (recommended for AI)
echo  [N] No  - Install PyTorch CPU-only (bot will run slower)
echo.
set /p GPU_CHOICE= Enter Y or N: 

if /i "%GPU_CHOICE%"=="Y" (
    echo.
    echo  Installing PyTorch with CUDA 12.1 support...
    pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
) else (
    echo.
    echo  Installing PyTorch CPU version...
    pip install torch torchvision
)

if errorlevel 1 (
    echo.
    echo  [ERROR] PyTorch installation failed. Check your internet connection.
    pause & exit /b 1
)
echo  [OK] PyTorch installed.
echo.

:: ── Step 3: Install remaining dependencies ────────────────────────────────────
echo  [3/5] Installing remaining dependencies...
pip install -r requirements.txt --no-deps-for torch torchvision 2>nul
pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo  [WARNING] Some packages may have failed. Check output above.
    echo  You can retry by running: pip install -r requirements.txt
    echo.
)
echo  [OK] Dependencies installed.
echo.

:: ── Step 4: Setup config ─────────────────────────────────────────────────────
echo  [4/5] Setting up configuration...
if not exist "config.json" (
    copy "config.example.json" "config.json" >nul
    echo  [OK] config.json created from template.
    echo.
    echo  *** Please open config.json and fill in your settings:
    echo      - Discord bot token (optional)
    echo      - Webhook URLs (optional)
    echo      - Screen resolution (default: 1920x1080)
) else (
    echo  [OK] config.json already exists, skipping.
)
echo.

:: ── Step 5: Create required directories ───────────────────────────────────────
echo  [5/5] Creating required directories...
if not exist "assets\models" mkdir "assets\models"
if not exist "logs" mkdir "logs"
echo  [OK] Directories ready.
echo.

:: ── Done ──────────────────────────────────────────────────────────────────────
echo  ============================================================
echo   Installation Complete!
echo  ============================================================
echo.
echo  Next steps:
echo   1. Place your YOLO model (best.pt) in:
echo      assets\models\
echo.
echo   2. Edit config.json with your settings
echo      (screen resolution, Discord token, etc.)
echo.
echo   3. Run the bot by double-clicking run.bat
echo.
echo  ============================================================
echo.
pause
