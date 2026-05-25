@echo off
REM Single-step launcher for Windows. Double-click in Explorer to run.
REM
REM First run: creates a local virtualenv in app\.venv\ and installs the
REM package in editable mode. Subsequent runs reuse the same venv.
REM
REM Pass-through args go to the app, e.g.:
REM     RUN-Windows.bat app\inventories\hayes_features.json
REM     RUN-Windows.bat -platform windows

setlocal
cd /d "%~dp0app"

set "VENV_DIR=.venv"
set "STAMP=%VENV_DIR%\.installed"

if not exist "%VENV_DIR%" (
    echo Setting up Phonology Segment ^& Feature Engine ^(first run^)...
    echo Creating virtual environment ...
    where py >nul 2>&1
    if %errorlevel% == 0 (
        py -3 -m venv "%VENV_DIR%" || goto :py_fail
    ) else (
        python -m venv "%VENV_DIR%" || goto :py_fail
    )
)

call "%VENV_DIR%\Scripts\activate.bat"

if not exist "%STAMP%" (
    echo Installing dependencies ...
    python -m pip install --quiet --upgrade pip
    REM Engine first so the app's resolver sees a satisfied
    REM phonology-engine dep instead of going to PyPI for it.
    python -m pip install --quiet -e "..\packages\phonology-engine" || goto :pip_fail
    python -m pip install --quiet -e . || goto :pip_fail
    type nul > "%STAMP%"
)

phonology-features %*
goto :eof

:py_fail
echo.
echo Error: failed to create a virtual environment.
echo Install Python 3.11+ from https://www.python.org/downloads/ and try again.
echo.
pause
exit /b 1

:pip_fail
echo.
echo Error: failed to install dependencies. Check the output above.
echo.
pause
exit /b 1
