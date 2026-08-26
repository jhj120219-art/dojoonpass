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
REM     logs\ is gitignored, so a fresh clone/deploy does not have it. Without
REM     it the ">> logs\..." redirect fails, cmd leaves errorlevel at 0, the
REM     python script never runs, and the batch still reports [SUCCESS].
if not exist "logs" mkdir "logs"

REM --- 2. Resolve the Python interpreter (docs/BATCH_SCRIPTS.md sec.2) --------
REM     Keep an existing Anaconda install if present, else fall back to PATH,
REM     else fail loudly. The third branch is the point: a hardcoded Anaconda
REM     path once disappeared and stopped the crawl for 9 days unnoticed.
set "PY="
if exist "C:\ProgramData\Anaconda3\python.exe" set "PY=C:\ProgramData\Anaconda3\python.exe"
if not defined PY for /f "delims=" %%i in ('where python 2^>nul') do if not defined PY set "PY=%%i"
if not defined PY (
    echo ===================================== >> logs\daily_run.log
    echo [FAILED] Python interpreter not found ^(run_daily.bat^) at %date% %time% >> logs\daily_run.log
    exit /b 1
)

REM --- 3. Schema migrations (docs/BATCH_SCRIPTS.md sec.3) --------------------
REM     init_db() inside mvp_scraper.py only creates the 3 legacy tables; it
REM     does not apply the numbered migrations. Without this line a new
REM     migration never reaches a deployment and the first crawl after it
REM     writes into the old schema. The runner is safe to re-run. On failure we
REM     stop - not writing crawl data beats writing it into a wrong schema.
"%PY%" -m storage.migrations.run_migrations >> logs\migrate_execute.log 2>&1
if errorlevel 1 (
    echo ===================================== >> logs\daily_run.log
    echo [FAILED] run_migrations exited with code %errorlevel% at %date% %time% >> logs\daily_run.log
    exit /b 1
)

REM --- 4. Pipeline. Every script gets an errorlevel check right after it, and
REM     each failing branch writes its own [FAILED] marker
REM     (docs/BATCH_SCRIPTS.md sec.4, pinned by test_crawl_exit_code.py).
"%PY%" mvp_scraper.py >> logs\daily_run.log 2>&1
if errorlevel 1 (
    echo ===================================== >> logs\daily_run.log
    echo [FAILED] mvp_scraper.py exited with code %errorlevel% at %date% %time% >> logs\daily_run.log
    exit /b 1
)

"%PY%" migrate_execute.py >> logs\migrate_execute.log 2>&1
if errorlevel 1 (
    echo ===================================== >> logs\daily_run.log
    echo [FAILED] migrate_execute.py exited with code %errorlevel% at %date% %time% >> logs\daily_run.log
    exit /b 1
)

echo ===================================== >> logs\daily_run.log
echo [SUCCESS] Finished at %date% %time% >> logs\daily_run.log
exit /b 0
