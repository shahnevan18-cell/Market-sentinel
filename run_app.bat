@echo off
rem Market Sentinel launcher for Windows. Double-click this file to start the app.
rem First run: creates a private Python environment and installs the packages (internet needed).
setlocal
title Market Sentinel
cd /d "%~dp0"

if not exist "app.py" goto not_extracted

set "PYTHON="
py -3 -c "import sys; raise SystemExit(sys.version_info < (3, 11))" >nul 2>&1 && set "PYTHON=py -3"
if not defined PYTHON python -c "import sys; raise SystemExit(sys.version_info < (3, 11))" >nul 2>&1 && set "PYTHON=python"
if not defined PYTHON goto no_python

%PYTHON% launch.py
if errorlevel 1 goto failed
exit /b 0

:not_extracted
echo This launcher has to run from the extracted project folder.
echo Right-click the zip file, choose Extract All, open the new folder and double-click run_app.bat there.
echo.
pause
exit /b 1

:no_python
echo Python 3.11 or newer was not found on this computer.
echo.
echo   1. Download Python from https://www.python.org/downloads/
echo   2. In the installer, tick "Add python.exe to PATH", then click Install Now.
echo   3. Double-click run_app.bat again.
echo.
pause
exit /b 1

:failed
echo.
echo Market Sentinel stopped because of the problem shown above.
pause
exit /b 1
