@echo off
setlocal
cd /d "%~dp0"
title FOODiE - Starting server

echo ========================================
echo          FOODiE WEB APPLICATION
echo ========================================
echo.

REM Find a usable Python 3 installation.
where py >nul 2>nul
if not errorlevel 1 (
    py -3 --version
    if not errorlevel 1 set "PYTHON=py -3"
)
if not defined PYTHON (
    where python >nul 2>nul
    if not errorlevel 1 (
        python --version
        if not errorlevel 1 set "PYTHON=python"
    )
)
if not defined PYTHON (
    echo ERROR: Python 3 was not found.
    echo Install Python 3.10 or newer from https://www.python.org/downloads/windows/
    echo During installation, enable "Add python.exe to PATH".
    echo Then close this window, reopen FOODiE, and run this file again.
    echo.
    pause
    exit /b 1
)

echo.
echo [1/3] Checking virtual environment...
if not exist ".venv\Scripts\python.exe" (
    %PYTHON% -m venv .venv
    if errorlevel 1 goto :error_venv
)

 echo.
echo [2/3] Installing required packages (internet connection required)...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error_pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error_pip

echo.
echo [3/3] Starting FOODiE...
echo Keep this window open while using the application.
echo Open http://127.0.0.1:5000 in your browser.
echo Press CTRL+C to stop the server.
echo.
".venv\Scripts\python.exe" -c "from waitress import serve; from app import app; serve(app, host='0.0.0.0', port=5000)"
if errorlevel 1 goto :error_server
exit /b 0

:error_venv
echo.
echo ERROR: Could not create the Python virtual environment.
echo Check that Python 3.10+ is installed correctly.
goto :show_error

:error_pip
echo.
echo ERROR: Dependency installation failed.
echo Check your internet connection, then run this file again.
goto :show_error

:error_server
echo.
echo ERROR: FOODiE could not start. Read the error message above.
echo If port 5000 is already in use, close the other application using it.
goto :show_error

:show_error
echo.
pause
exit /b 1
