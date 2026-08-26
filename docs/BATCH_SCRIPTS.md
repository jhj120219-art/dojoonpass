# 배치 스크립트 3종 — 왜 지금 모양인가

`run_daily.bat` / `run_doc_worker.bat` / `run_priority_refresh.bat` 의 각 구간이
**어떤 사고를 겪고 생겼는지**를 모아 둔 문서다.

2026-08-26(BUGS #220 후속)에 배치 파일의 주석을 **ASCII 로 옮기면서** 그 안에 있던
한글 설명을 여기로 뺐다. 설명이 사라진 것이 아니라 **자리를 옮긴 것**이다.
배치에는 이 문서를 가리키는 최소 주석만 남겼다.

---

## 0. 왜 배치 파일에 한글을 쓰지 않는가 (BUGS #219, #221)

세 파일 모두 **UTF-8(BOM 없음)** 인데 `cmd.exe` 는 이 시스템의 **OEM 코드페이지(cp949)**
로 읽는다. 한글 UTF-8 바이트를 cp949 로 읽으면 2바이트 조합이 **뒤따르는 ASCII 를
트레일 바이트로 삼켜** 토큰 경계가 밀린다. 그러면 주석 한가운데에서 파싱이 재개되고
남은 조각이 **명령으로 실행된다.**

2026-08-26 실측(작업 사본을 `chcp 949` 로 실행):

```
run_daily.bat            stderr 0줄   <- 다만 아래 ★ 참고
run_doc_worker.bat       stderr 7줄   조각 3개가 명령으로 실행 + 리다이렉트 구문 오류 1건
run_priority_refresh.bat stderr 5줄   조각 2개가 명령으로 실행 + 리다이렉트 구문 오류 1건
```

★ `run_daily.bat` 가 0줄인 것은 **깨끗해서가 아니다.** 그 사본에는 파이썬 스크립트가
없어 첫 단계(`run_migrations`)에서 `exit /b 1` 로 끝났고, cmd 는 줄 단위로 읽으며
실행하므로 **뒤쪽 한글 주석까지 가지 못했다.** 측정이 그 구간을 덮지 못한 것이다.

**★ 처음 잰 값은 틀렸다.** 같은 사본을 이 세션의 셸에서 그냥 돌렸을 때는 세 파일 모두
stderr 0줄이었다. 그 셸의 cmd 가 **코드페이지 65001(UTF-8)** 을 물려받았기 때문이다.
작업 스케줄러는 시스템 OEM 코드페이지(949)로 띄운다 — 즉 그 측정은 **실제 실행 조건이
아니었다.** 코드페이지를 949 로 맞추고 다시 재서 위 표를 얻었다.
*측정값이 뜻밖이면 코드보다 도구를 먼저 의심한다.*

### 왜 다른 방법으로는 못 고치나 (BUGS #219 실측)

```
cp949 로 저장     실패 — 기존 주석의 em-dash(U+2014)를 cp949 가 인코딩하지 못한다
chcp 65001 추가   효과 없음 — cmd 는 그 줄에 닿기 전에 이미 앞을 파싱한다
UTF-8 BOM 추가    더 나빠진다 — '癤?echo' 가 명령이 된다
```

그래서 남은 방법은 **배치 안의 문자를 ASCII 로 유지하는 것**뿐이다.
`test_console_encoding.py` 의 배치 ASCII 검사가 이 규칙을 지킨다.

---

## 1. `logs\` 디렉터리를 먼저 만든다 (Sprint 99)

```bat
if not exist "logs" mkdir "logs"
```

`logs\` 는 `.gitignore` 대상이라 **새로 받은 저장소/새 배포에는 없다.** 그 상태에서
`>> logs\daily_run.log` 리다이렉트는 실패하는데 **cmd 는 errorlevel 을 0 으로 둔다.**

1. 리다이렉트가 실패해 파이썬 스크립트가 **아예 실행되지 않는다**
2. errorlevel 이 0 이라 `if errorlevel 1` 실패 분기가 **타지 않는다**
3. 마지막 `[SUCCESS]` 마커까지 지나 **`exit /b 0` 으로 끝난다**

즉 아무것도 하지 않고 "성공"으로 보고한다(실측 재현). 이 배치가 막으려던 바로 그
**실패 은폐**(2026-08-03~08-11 9일간 크롤 중단)가 로그 디렉터리 부재라는 다른 입구로
그대로 재발하는 자리였다. `mkdir` 한 줄이면 없어지고, 이미 있으면 아무 일도 하지 않는다.

**이 줄은 어떤 리다이렉트보다 먼저 와야 한다.**

---

## 2. Python 인터프리터 해석 (Sprint 54)

```bat
set "PY="
if exist "C:\ProgramData\Anaconda3\python.exe" set "PY=C:\ProgramData\Anaconda3\python.exe"
if not defined PY for /f "delims=" %%i in ('where python 2^>nul') do if not defined PY set "PY=%%i"
if not defined PY ( ... [FAILED] ... exit /b 1 )
```

예전에는 Anaconda 경로를 하드코딩했다. 그 Anaconda 가 제거되면서 **모든 배치가 즉시
실패**했고, 실패가 로그에도 남지 않아 2026-08-03 ~ 08-11 동안 크롤이 멈춘 사실을 아무도
몰랐다. 그 사이 진행 중 물건이 41건까지 줄었다(전부 2026-08-12 만료 → 그 다음날부터
검색 결과 0건).

지금은 (1) 기존 Anaconda 경로가 남아 있으면 그대로 쓰고(기존 환경 무변경)
(2) 없으면 PATH 의 python 으로 폴백하며 (3) 둘 다 없으면 로그에 남기고 즉시 실패한다.

**(3)이 핵심이다** — Sprint 13 이 없앤 "실패 은폐"가 인터프리터 단계에서 재발했었다.

---

## 3. 스키마 마이그레이션 (`run_daily.bat`, 2026-08-26, BUGS #219)

```bat
"%PY%" -m storage.migrations.run_migrations >> logs\migrate_execute.log 2>&1
if errorlevel 1 ( ... exit /b 1 )
```

이 배치는 예전에 `run_migrations` 를 **부르지 않았다.** `mvp_scraper.py` 안의
`init_db()` 는 레거시 3테이블만 만들고 번호 마이그레이션은 건드리지 않는다. 즉
001~025 가 적용된 것은 **사람이 수동으로 러너를 돌렸기 때문**이고, 새 마이그레이션이
생겨도 새 배포에는 닿지 않았다.

**위험한 순간은 새 배포/새 마이그레이션 뒤 첫 크롤이다 — 옛 스키마에 쓴다.**
러너는 재실행에 안전하다(`migration_history` 가 중복 적용을 막는다). 실패하면 거기서
멈춘다 — **틀린 스키마에 크롤 데이터를 쓰는 것보다 안 쓰는 것이 낫다.**

관련: 같은 드리프트가 **읽기 쪽**에 낸 상처가 BUGS #220(면적 필터 500)이다.

---

## 4. 실행 결과 기록 / errorlevel 검사 (Sprint 13, Sprint 55, BUGS #47)

파이썬 스크립트를 부르는 줄마다 **바로 뒤에** `if errorlevel 1` 블록이 붙고, 그 블록
안에서 `[FAILED]` 를 남긴 뒤 `exit /b 1` 한다. 마지막에만 `[SUCCESS]` 를 남긴다.

원래 이 구조는 `run_daily.bat` 에만 있었다. 나머지 둘은 스크립트를 실행하고 그냥 끝나서
로그만 봐서는 **"돌아서 할 일이 없었다"와 "아예 실행되지 않았다"를 구분할 수 없었다.**
실제로 2026-08-02 에 `refresh_priority.py` 가 traceback 으로 죽었지만, 그 사실이
`doc_run.log` 안쪽 줄에만 남고 스케줄러 결과에는 드러나지 않았다.

이 구조는 `test_crawl_exit_code.py` 가 고정한다.

- 배치가 실행하는 스크립트 목록이 바뀌면 알린다(사람이 종료 코드 계약을 한 번 본다)
- 각 스크립트 뒤에 errorlevel 검사가 **붙어 있는지**
- 각 실패 분기가 **자기 블록 안에서** `[FAILED]` 를 남기는지
  (파일 어딘가에 한 번이라도 있으면 통과시키면 분기 하나가 비어도 안 잡힌다)
- 파이썬 쪽 `sys.exit()` 인자가 **런타임 판정**인지(상수뿐이면 실패)

---

## 5. 스케줄러 등록

`register_scheduler_tasks.ps1` 이 세 작업을 정의한다
(`DojoonPass-PriorityRefresh` 01:50 / `DojoonPass-DocWorker` 02:00 /
`DojoonPass-DailyCrawl` 06:00). 상태는 `python audit_schedule_health.py` 로 잰다
(읽기 전용). **등록·변경은 승인 영역**이라 에이전트가 임의로 하지 않는다.
