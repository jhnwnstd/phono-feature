@echo off
REM Intentionally NOT using ``setlocal``. The caller (RUN-Windows.bat)
REM invokes this script via ``call`` and then runs ``phonology-features``,
REM which lives at ``<venv>\Scripts\phonology-features.exe`` and is only
REM reachable when the venv's ``activate.bat`` has prepended that
REM directory to PATH. ``setlocal`` would scope the activation's env
REM changes to this script and revert them on exit, leaving PATH
REM without the Scripts dir and the caller's ``phonology-features``
REM call failing with "not recognized as an internal or external
REM command" (exit code 9009). This mirrors the bash launchers, which
REM ``source`` install.sh so its env changes are visible to the caller.

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

REM No reliable "is newer than" operator in cmd.exe: ``IF`` only
REM supports ``EXIST`` / ``==`` / ``LSS|GTR|EQU|LEQ|GEQ|NEQ``.
REM Workarounds (xcopy /D, forfiles, powershell) are either locale-
REM dependent or pull in a slow second process. The bash launchers'
REM ``-nt`` test has no clean cmd equivalent, so the Windows
REM launcher only triggers a reinstall when the stamp is missing.
REM Manual override: ``del app\.venv\.installed`` to force the next
REM run to reinstall.

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