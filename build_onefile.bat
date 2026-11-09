@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo   Spine Studio - build single EXE
echo ============================================
echo.

set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo [ERROR] .venv\Scripts\python.exe was not found.
    echo This build script needs the development environment in this folder.
    echo The EXE it produces does NOT need any environment.
    echo.
    pause
    exit /b 1
)

if not exist "spine_studio_onefile.spec" (
    echo [ERROR] spine_studio_onefile.spec was not found.
    pause
    exit /b 1
)

tasklist /FI "IMAGENAME eq Spine Studio.exe" 2>nul | findstr /I /C:"Spine Studio.exe" >nul
if not errorlevel 1 (
    echo [WARN] Spine Studio.exe is running.
    echo Close the application before building, otherwise the EXE cannot be replaced.
    pause
    exit /b 1
)

"%PY%" -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo [INFO] PyInstaller is missing, installing it...
    "%PY%" -m pip install pyinstaller
    if errorlevel 1 (
        echo [ERROR] Could not install PyInstaller.
        pause
        exit /b 1
    )
)

echo [INFO] Building one-file package. This can take a few minutes...
echo.
"%PY%" -m PyInstaller --noconfirm --clean --distpath "release" --workpath "build-onefile" spine_studio_onefile.spec
if errorlevel 1 (
    echo.
    echo [ERROR] Build failed. Please read the messages above.
    pause
    exit /b 1
)

if not exist "release\Spine Studio.exe" (
    echo.
    echo [ERROR] The build finished without producing release\Spine Studio.exe.
    pause
    exit /b 1
)

echo.
echo ============================================
echo [OK] Build complete
echo File: %~dp0release\Spine Studio.exe
echo.
echo Copy this single EXE to any Windows PC and double-click it.
echo No Python, Qt, FFmpeg or other runtime is required.
echo ============================================
echo.
pause
