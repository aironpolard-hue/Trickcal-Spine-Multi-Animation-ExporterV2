@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "ENV_ROOT=%LOCALAPPDATA%\SpineStudioV2\source-env"
set "PYTHON_EXE=%ENV_ROOT%\Scripts\python.exe"
set "BOOTSTRAP="

if not exist "%PYTHON_EXE%" (
    where py >nul 2>&1
    if not errorlevel 1 (
        set "BOOTSTRAP=py -3"
    ) else (
        where python >nul 2>&1
        if not errorlevel 1 set "BOOTSTRAP=python"
    )

    if not defined BOOTSTRAP (
        echo [ERROR] Python 3 was not found.
        echo Install Python 3.10 or newer, then double-click this file again.
        pause
        exit /b 1
    )

    echo [INFO] Creating the source runtime environment...
    %BOOTSTRAP% -m venv "%ENV_ROOT%"
    if errorlevel 1 (
        echo [ERROR] Could not create the source runtime environment.
        pause
        exit /b 1
    )
)

"%PYTHON_EXE%" -c "import PySide6, numpy, PIL, OpenGL, UnityPy" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installing source runtime dependencies...
    "%PYTHON_EXE%" -m pip install --upgrade pip
    if errorlevel 1 (
        echo [ERROR] Could not update pip.
        pause
        exit /b 1
    )
    "%PYTHON_EXE%" -m pip install -r "%~dp0requirements.txt"
    if errorlevel 1 (
        echo [ERROR] Could not install source runtime dependencies.
        pause
        exit /b 1
    )
)

echo [INFO] Starting Spine Studio from source...
"%PYTHON_EXE%" "%~dp0main.py"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] Spine Studio exited with code %EXIT_CODE%.
    pause
)

exit /b %EXIT_CODE%
