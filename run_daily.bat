@echo off
cd /d %~dp0

REM ---------------------------------------------------------------------------
REM logs 디렉터리 확보 (2026-08-13 Sprint 99) - 아래 어떤 리다이렉트보다 먼저 와야 한다.
REM
REM `logs\`는 .gitignore 대상이라 **새로 받은 저장소/새 배포에는 없다.** 그 상태에서
REM `>> logs\daily_run.log`는 실패하는데, cmd는 **errorlevel을 0으로 둔다.** 그래서:
REM
REM   1. 리다이렉트가 실패해 파이썬 스크립트가 **아예 실행되지 않는다**
REM   2. errorlevel이 0이라 아래 `if errorlevel 1` 실패 분기가 **타지 않는다**
REM   3. 마지막 [SUCCESS] 마커까지 지나 **exit /b 0으로 끝난다**
REM
REM 즉 아무것도 하지 않고 "성공"으로 보고한다. 실측 재현했다(스크립트 미실행 + exit 0).
REM 이 배치가 막으려던 바로 그 "실패 은폐"(2026-08-03~08-11 9일간 크롤 중단)가
REM 로그 디렉터리 부재라는 다른 입구로 그대로 재발하는 자리였다.
REM
REM mkdir 한 줄이면 없어진다. 이미 있으면 아무 일도 하지 않는다.
REM ---------------------------------------------------------------------------
if not exist "logs" mkdir "logs"

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

REM ---------------------------------------------------------------------------
REM Schema migrations (added 2026-08-26).
REM
REM This batch never called storage.migrations.run_migrations before. init_db()
REM inside mvp_scraper.py only creates the 3 legacy tables; it does not apply the
REM numbered migrations. So 001-025 got applied only because a human ran the
REM runner by hand, and a new migration would NOT reach a fresh deployment.
REM Risk: the first crawl after a new migration writes into the old schema.
REM
REM The runner is safe to re-run (migration_history blocks double-apply).
REM On failure we stop here - not writing crawl data beats writing it into a
REM wrong schema. See docs/BUGS.md for the full reasoning.
REM
REM NOTE: comments in this file are ASCII on purpose. The .bat is UTF-8 but cmd
REM reads it in the system codepage (cp949 here), and multi-byte text can shift
REM byte alignment so that following ASCII is swallowed and a fragment runs as a
REM command. That already happens with the older Korean comments in this file.
REM ---------------------------------------------------------------------------
"%PY%" -m storage.migrations.run_migrations >> logs\migrate_execute.log 2>&1
if errorlevel 1 (
    echo ===================================== >> logs\daily_run.log
    echo [FAILED] run_migrations exited with code %errorlevel% at %date% %time% >> logs\daily_run.log
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
