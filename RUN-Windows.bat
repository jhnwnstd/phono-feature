@echo off
REM Single-step launcher for Windows. Double-click in Explorer to run.
REM
REM First run: creates a local virtualenv in desktop\.venv\ and installs
REM the package in editable mode. Subsequent runs reuse the same venv
REM and reinstall only when desktop\pyproject.toml has changed. The
REM bootstrap
REM logic lives in tools\install.bat so desktop launchers stay aligned.
REM
REM Pass-through args go to the app, e.g.:
REM     RUN-Windows.bat desktop\inventories\hayes_features.json
REM     RUN-Windows.bat -platform windows

setlocal
set "SCRIPT_DIR=%~dp0"

call "%SCRIPT_DIR%tools\install.bat" "Windows" || exit /b 1

"%PHONO_BIN%" %*
exit /b %errorlevel%