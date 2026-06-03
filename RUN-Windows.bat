@echo off
REM Single-step launcher for Windows. Double-click in Explorer to run.
REM
REM First run: creates a local virtualenv in app\.venv\ and installs the
REM package in editable mode. Subsequent runs reuse the same venv and
REM reinstall only when app\pyproject.toml has changed. The bootstrap
REM logic lives in tools\install.bat so desktop launchers stay aligned.
REM
REM Pass-through args go to the app, e.g.:
REM     RUN-Windows.bat app\inventories\hayes_features.json
REM     RUN-Windows.bat -platform windows

setlocal
set "SCRIPT_DIR=%~dp0"

call "%SCRIPT_DIR%tools\install.bat" "Windows" || exit /b 1

phonology-features %*
exit /b %errorlevel%