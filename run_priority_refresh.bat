@echo off
cd /d %~dp0

REM ---------------------------------------------------------------------------
REM NOTE: keep this file ASCII-only. The .bat is UTF-8 (no BOM) but cmd reads it
REM in the system OEM codepage (cp949 here). Multi-byte text shifts the byte
REM alignment so that following ASCII gets swallowed and a leftover fragment is
REM run as a command - measured, see docs/BUGS.md #219 / #221.
REM Rationale for every block below lives in docs/BATCH_SCRIPTS.md.
REM ---------------------------------------------------------------------------

REM --- 1. logs\ must exist before ANY redirect (docs/BATCH_SCRIPTS.md sec.1) ---
REM     Without it the redirect fails, cmd leaves errorlevel at 0, the script
REM     never runs, and the batch still reports [SUCCESS].
if not exist "logs" mkdir "logs"

REM --- 2. Resolve the Python interpreter (docs/BATCH_SCRIPTS.md sec.2) --------
REM     Anaconda if present, else PATH, else fail loudly. The third branch is
REM     the point - a vanished hardcoded path once stopped the pipeline for 9
REM     days without leaving a trace in the logs.
set "PY="
if exist "C:\ProgramData\Anaconda3\python.exe" set "PY=C:\ProgramData\Anaconda3\python.exe"
if not defined PY for /f "delims=" %%i in ('where python 2^>nul') do if not defined PY set "PY=%%i"
if not defined PY (
    echo ===================================== >> logs\doc_run.log
    echo [FAILED] Python interpreter not found ^(run_priority_refresh.bat^) at %date% %time% >> logs\doc_run.log
    exit /b 1
)

REM --- 3. Record the outcome (docs/BATCH_SCRIPTS.md sec.4, BUGS #47) ---------
REM     This batch used to run the script and just end, so the log could not
REM     tell "ran and had nothing to do" from "never ran at all".
"%PY%" refresh_priority.py >> logs\doc_run.log 2>&1
if errorlevel 1 (
    echo ===================================== >> logs\doc_run.log
    echo [FAILED] refresh_priority.py exited with code %errorlevel% at %date% %time% >> logs\doc_run.log
    exit /b 1
)

echo ===================================== >> logs\doc_run.log
echo [SUCCESS] refresh_priority.py finished at %date% %time% >> logs\doc_run.log
exit /b 0
