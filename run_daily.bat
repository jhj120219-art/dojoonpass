@echo off
cd /d %~dp0

C:\ProgramData\Anaconda3\python.exe mvp_scraper.py >> logs\daily_run.log 2>&1
if errorlevel 1 (
    echo ===================================== >> logs\daily_run.log
    echo [FAILED] mvp_scraper.py exited with code %errorlevel% at %date% %time% >> logs\daily_run.log
    exit /b 1
)

C:\ProgramData\Anaconda3\python.exe migrate_execute.py >> logs\migrate_execute.log 2>&1
if errorlevel 1 (
    echo ===================================== >> logs\daily_run.log
    echo [FAILED] migrate_execute.py exited with code %errorlevel% at %date% %time% >> logs\daily_run.log
    exit /b 1
)

echo ===================================== >> logs\daily_run.log
echo [SUCCESS] Finished at %date% %time% >> logs\daily_run.log
exit /b 0
