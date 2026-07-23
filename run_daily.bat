@echo off
cd /d C:\Users\Administrator\Desktop\dojoonpass
C:\ProgramData\Anaconda3\python.exe mvp_scraper.py >> logs\daily_run.log 2>&1
C:\ProgramData\Anaconda3\python.exe migrate_execute.py >> logs\migrate_execute.log 2>&1
echo ===================================== >> logs\daily_run.log
echo Finished at %date% %time% >> logs\daily_run.log
