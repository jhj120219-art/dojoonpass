@echo off
cd /d %~dp0

REM ---------------------------------------------------------------------------
REM logs 디렉터리 확보 (2026-08-13 Sprint 99) - 아래 어떤 리다이렉트보다 먼저 와야 한다.
REM 이유는 run_daily.bat의 같은 자리 주석 참고: `logs\`가 없으면 리다이렉트가 실패하는데
REM cmd가 errorlevel을 0으로 둬서, 스크립트를 실행조차 못 한 채 [SUCCESS]로 끝난다(실측).
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
    echo ===================================== >> logs\doc_run.log
    echo [FAILED] Python 인터프리터를 찾을 수 없습니다 ^(run_doc_worker.bat^) at %date% %time% >> logs\doc_run.log
    exit /b 1
)

REM ---------------------------------------------------------------------------
REM 실행 결과 기록 (2026-08-11 Sprint 55, BUGS #47)
REM
REM 이 배치에는 errorlevel 검사도, 성공/실패 마커도 **없었다**. Sprint 13이
REM run_daily.bat에만 넣었기 때문이다. 그래서 doc_run.log만 봐서는
REM "돌아서 할 일이 없었다"와 "아예 실행되지 않았다"를 구분할 수 없었다.
REM ---------------------------------------------------------------------------
"%PY%" doc_worker.py >> logs\doc_run.log 2>&1
if errorlevel 1 (
    echo ===================================== >> logs\doc_run.log
    echo [FAILED] doc_worker.py exited with code %errorlevel% at %date% %time% >> logs\doc_run.log
    exit /b 1
)

echo ===================================== >> logs\doc_run.log
echo [SUCCESS] doc_worker.py finished at %date% %time% >> logs\doc_run.log
exit /b 0
