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
    echo [FAILED] Python interpreter not found ^(run_doc_worker.bat^) at %date% %time% >> logs\doc_run.log
    exit /b 1
)

REM --- 3. Record the outcome (docs/BATCH_SCRIPTS.md sec.4, BUGS #47) ---------
REM     This batch used to run the script and just end, so the log could not
REM     tell "ran and had nothing to do" from "never ran at all".
"%PY%" doc_worker.py >> logs\doc_run.log 2>&1
if errorlevel 1 (
    echo ===================================== >> logs\doc_run.log
    echo [FAILED] doc_worker.py exited with code %errorlevel% at %date% %time% >> logs\doc_run.log
    exit /b 1
)

REM --- 4. Turn the collected documents into rights analysis (BUGS #245) -----
REM     doc_worker.py only *collects* status.html / spec.pdf. Until these two
REM     scripts run, document_status says READY while rights_summary stays
REM     empty - the detail page shows a property whose documents exist but
REM     whose rights analysis is blank. That gap grew every night because
REM     neither script was in any .bat or scheduled task (2026-09-01: 9
REM     documents collected, 0 parsed).
REM
REM     Wiring was deferred before because both scripts contain a DELETE path
REM     (purge_orphans). That path now asks storage.database.guard_mass_purge()
REM     first and refuses - with exit code 1 - when a single run would remove
REM     more than 20% of existing derived rows, which is the signature of a
REM     half-synced documents/ tree rather than real data change.
"%PY%" load_rights_data.py >> logs\doc_run.log 2>&1
if errorlevel 1 (
    echo ===================================== >> logs\doc_run.log
    echo [FAILED] load_rights_data.py exited with code %errorlevel% at %date% %time% >> logs\doc_run.log
    exit /b 1
)

"%PY%" load_spec_data.py >> logs\doc_run.log 2>&1
if errorlevel 1 (
    echo ===================================== >> logs\doc_run.log
    echo [FAILED] load_spec_data.py exited with code %errorlevel% at %date% %time% >> logs\doc_run.log
    exit /b 1
)

echo ===================================== >> logs\doc_run.log
echo [SUCCESS] doc_worker.py finished at %date% %time% >> logs\doc_run.log
exit /b 0
