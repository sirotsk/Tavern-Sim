@echo off
setlocal

:: Enable UTF-8 output for colored text
chcp 65001 > nul

:: Change to the directory where this batch file lives
cd /d "%~dp0"

:: Find Python
where python >nul 2>nul
if %errorlevel%==0 (
    set PYTHON=python
    goto :run
)

where python3 >nul 2>nul
if %errorlevel%==0 (
    set PYTHON=python3
    goto :run
)

where py >nul 2>nul
if %errorlevel%==0 (
    set PYTHON=py -3
    goto :run
)

echo.
echo Python not found. Download from https://www.python.org/downloads/
echo Make sure to check "Add Python to PATH" during installation.
echo.
goto :done

:run
%PYTHON% run.py

:done
echo.
pause
endlocal
