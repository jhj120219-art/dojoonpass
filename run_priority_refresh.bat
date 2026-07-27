@echo off
cd /d %~dp0
C:\ProgramData\Anaconda3\python.exe refresh_priority.py >> logs\doc_run.log 2>&1
