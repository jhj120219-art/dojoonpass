@echo off
cd /d %~dp0

REM ---------------------------------------------------------------------------
REM Python 인터프리터 해석 (2026-08-11 Sprint 54)
REM
REM 예전에는 Anaconda 경로(C:\ProgramData\Anaconda3\python.exe)를 하드코딩했다.
REM 그 Anaconda가 제거되면서 **모든 배치가 즉시 실패**했고, 실패가 로그에도 남지 않아
REM 2026-08-03 ~ 08-11 동안 크롤이 멈춘 사실을 아무도 몰랐다. 그 사이 진행 중 물건이
REM 41건까지 줄었다(전부 2026-08-12 만료 -> 그 다음날부터 검색 결과 0건).
REM
REM 이제 (1) 기존 Anaconda 경로가 남아 있으면 그대로 쓰고(기존 환경 무변경)
REM      (2) 없으면 PATH의 python으로 폴백하며
REM      (3) 둘 다 없으면 로그에 남기고 즉시 실패한다.
REM (3)이 핵심이다 — Sprint 13이 없앤 "실패 은폐"가 인터프리터 단계에서 재발했었다.
REM ---------------------------------------------------------------------------
set "PY="
if exist "C:\ProgramData\Anaconda3\python.exe" set "PY=C:\ProgramData\Anaconda3\python.exe"
if not defined PY for /f "delims=" %%i in ('where python 2^>nul') do if not defined PY set "PY=%%i"
if not defined PY (
    echo ===================================== >> logs\daily_run.log
    echo [FAILED] Python 인터프리터를 찾을 수 없습니다 ^(run_daily.bat^) at %date% %time% >> logs\daily_run.log
    exit /b 1
)

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
