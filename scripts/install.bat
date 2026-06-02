@echo off
setlocal

set "PLATFORM=%~1"
set "SCRIPT_DIR=%~dp0"
set "ROOT_DIR=%SCRIPT_DIR%.."
set "APP_DIR=%ROOT_DIR%\app"
set "ENGINE_DIR=%ROOT_DIR%\packages\phonology-engine"
set "VENV_DIR=%APP_DIR%\.venv"
set "STAMP=%VENV_DIR%\.installed"
set "APP_PYPROJECT=%APP_DIR%\pyproject.toml"

cd /d "%APP_DIR%" || goto :cd_fail

if not exist "%VENV_DIR%" (
    echo Setting up Phonology Segment ^& Feature Engine for %PLATFORM% ^(first run^)...
    echo Creating virtual environment ...

    where py >nul 2>&1
    if %errorlevel% == 0 (
        py -3 -m venv "%VENV_DIR%" || goto :py_fail
    ) else (
        python -m venv "%VENV_DIR%" || goto :py_fail
    )
)

call "%VENV_DIR%\Scripts\activate.bat" || goto :venv_fail

if not exist "%STAMP%" goto :install

for %%F in ("%APP_PYPROJECT%") do set "PYPROJECT_TIME=%%~tF"
for %%F in ("%STAMP%") do set "STAMP_TIME=%%~tF"

if "%APP_PYPROJECT%" newer "%STAMP%" goto :install

exit /b 0

:install
echo Installing dependencies ...
python -m pip install --quiet --upgrade pip || goto :pip_fail
python -m pip install --quiet -e "%ENGINE_DIR%" || goto :pip_fail
python -m pip install --quiet -e "%APP_DIR%" || goto :pip_fail
type nul > "%STAMP%"
exit /b 0

:cd_fail
echo.
echo Error: could not enter the app directory.
echo.
pause
exit /b 1

:py_fail
echo.
echo Error: failed to create a virtual environment.
echo Install Python 3.11+ from https://www.python.org/downloads/ and try again.
echo.
pause
exit /b 1

:venv_fail
echo.
echo Error: failed to activate the virtual environment.
echo.
pause
exit /b 1

:pip_fail
echo.
echo Error: failed to install dependencies. Check the output above.
echo.
pause
exit /b 1