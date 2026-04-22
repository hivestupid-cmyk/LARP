@echo off
title L.A.R.P — Logic AI Robotic Program
cd /d "%~dp0"

:: Check config.json exists
if not exist "config.json" (
    echo.
    echo  [ERROR] config.json not found!
    echo  Please run install.bat first.
    echo.
    pause
    exit /b 1
)

:: Check assets/models folder has a model
set MODEL_FOUND=0
for /r "assets\models" %%f in (*.pt) do set MODEL_FOUND=1
if "%MODEL_FOUND%"=="0" (
    echo.
    echo  [WARNING] No YOLO model (.pt) found in assets\models\
    echo  The bot may fail to start without a model.
    echo.
    echo  Press any key to continue anyway, or close this window to cancel.
    pause
)

echo.
echo  ============================================================
echo   Starting L.A.R.P - Logic AI Robotic Program
echo  ============================================================
echo.

python main.py

:: If python exits with error, keep window open
if errorlevel 1 (
    echo.
    echo  [ERROR] Bot exited with an error. See output above.
    echo.
    pause
)
