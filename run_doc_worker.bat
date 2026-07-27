@echo off
cd /d %~dp0
C:\ProgramData\Anaconda3\python.exe doc_worker.py >> logs\doc_run.log 2>&1
