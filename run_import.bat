@echo off
rem ===========================================================================
rem  Easy Revit to Designcenter NX : command line importer
rem
rem  NOTE: this file is intentionally ASCII-only.
rem  cmd.exe parses .bat using the system ANSI codepage (936/GBK on Chinese
rem  Windows), NOT UTF-8. Non-ASCII bytes here would corrupt parsing.
rem
rem  Most users should just run start_gui.bat instead.
rem
rem  Why run_journal is required:
rem    NXOpen.pyd (<NX_HOME>\NXBIN\python\NXOpen.pyd) can only be loaded inside
rem    an NX process. Running the .py with an external Python fails at
rem    "import NXOpen".
rem
rem  Official usage (from run_journal.exe -help):
rem    run_journal [ -nx ] <journal-file> [ -args .... ]
rem    -nx        run the journal in NX
rem    -args ...  pass the rest of the command line as a string array to Main()
rem  Do not reorder these switches.
rem
rem  Usage:
rem    run_import.bat --rvt "D:\bim\model.rvt" --output-dir "D:\out\model1"
rem    run_import.bat --help
rem ===========================================================================
setlocal

set "HERE=%~dp0"
set "SCRIPT=%HERE%src\import_revit.py"

rem ---- locate NX -----------------------------------------------------------
rem  1) use UGII_BASE_DIR when already set
rem  2) otherwise probe a few common install locations
if not "%UGII_BASE_DIR%"=="" goto :have_nx

for %%D in (C D E F G) do (
    if not defined UGII_BASE_DIR (
        for %%P in (
            "%%D:\Program Files\Siemens\NX"
            "%%D:\Siemens\NX"
            "%%D:\NX"
        ) do (
            if not defined UGII_BASE_DIR (
                if exist "%%~P\NXBIN\run_journal.exe" set "UGII_BASE_DIR=%%~P"
            )
        )
    )
)

if "%UGII_BASE_DIR%"=="" (
    echo [ERROR] NX installation not found.
    echo         Set UGII_BASE_DIR to your NX root folder, e.g.
    echo             set "UGII_BASE_DIR=C:\Program Files\Siemens\NX2406"
    echo         It must contain NXBIN\run_journal.exe
    echo.
    echo         Tip: start_gui.bat detects NX automatically.
    echo.
    pause
    exit /b 1
)

:have_nx
set "RUN_JOURNAL=%UGII_BASE_DIR%\NXBIN\run_journal.exe"

if not exist "%RUN_JOURNAL%" (
    echo [ERROR] run_journal.exe not found: %RUN_JOURNAL%
    echo         UGII_BASE_DIR must point at the NX root folder,
    echo         not at NXBIN itself.
    exit /b 1
)

if not exist "%SCRIPT%" (
    echo [ERROR] import script not found: %SCRIPT%
    exit /b 1
)

echo NX base      : %UGII_BASE_DIR%
echo Journal      : %SCRIPT%
echo Extra args   : %*
echo.

"%RUN_JOURNAL%" -nx "%SCRIPT%" -args %*
set RC=%ERRORLEVEL%

echo.
if %RC% NEQ 0 (
    echo [FAILED] run_journal exit code = %RC%
    echo          See output above and src\nx_revit_import.log
) else (
    echo [DONE] exit code = 0
    echo        Verify with:  python verify_output.py "<output dir>"
)

exit /b %RC%
