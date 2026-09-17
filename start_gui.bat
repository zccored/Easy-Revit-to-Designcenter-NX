@echo off
rem ===========================================================================
rem  Revit -> NX integrated importer : GUI launcher
rem
rem  This file is intentionally ASCII-only.
rem  cmd.exe parses .bat using the system ANSI codepage (936/GBK on Chinese
rem  Windows), NOT UTF-8. Non-ASCII bytes here would corrupt parsing.
rem
rem  The GUI runs OUTSIDE NX (system Python + tkinter).
rem  The actual import is executed by NX's run_journal in a separate batch
rem  session, because NXOpen.pyd can only be loaded inside an NX process.
rem ===========================================================================
setlocal

set "HERE=%~dp0"
set "PY="

rem ---- locate a usable Python -------------------------------------------
where py >nul 2>nul && set "PY=py"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY (
    if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
        set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    )
)

if not defined PY (
    echo [ERROR] Python not found.
    echo         Install Python 3.9+ from https://www.python.org/downloads/
    echo         During setup, tick "Add python.exe to PATH".
    echo.
    pause
    exit /b 1
)

if not exist "%HERE%Revit2NX.py" (
    echo [ERROR] Revit2NX.py not found next to this launcher.
    echo         Expected: %HERE%Revit2NX.py
    echo.
    pause
    exit /b 1
)

echo Using Python : %PY%
echo Starting GUI : %HERE%Revit2NX.py
echo.

"%PY%" "%HERE%Revit2NX.py"
set RC=%ERRORLEVEL%

if %RC% NEQ 0 (
    echo.
    echo [FAILED] GUI exited with code %RC%
    pause
)
exit /b %RC%
