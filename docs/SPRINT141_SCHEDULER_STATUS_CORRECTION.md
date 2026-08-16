# Sprint 141 ― "스케줄러 미등록"은 절반만 사실이었다 ― 실제 Task Scheduler 실측 (2026-08-16)

> 앞 Sprint: `docs/SPRINT140_WEBHOOK_REPROCESS_RACE_TEST.md`
>
> **별도 파일 이유**: Sprint 100~140과 같다.

Release Readiness Audit 도중, 이 세션이 Sprint 129부터 지금까지 **모든 Sprint
문서의 "남은 Backlog"란에 그대로 반복해 온** 항목을 처음으로 직접 실측했다:

> ★★ 수집 파이프라인 스케줄러 등록 ― 2026-08-20에 검색 결과 0건이 된다(Sprint 112)

이 문구는 Sprint 112(2026-08-14)가 만들었고, 그 뒤 Sprint 121부터 140까지
**단 한 번도 재검증 없이 그대로 복사**돼 왔다 — `docs/CURRENT_STATE.md`/
`docs/BUGS.md`와 대조하는 이 세션의 원칙을 지키면서도, 정작 "실제 OS 상태"라는
가장 직접적인 증거는 아무도 보지 않았다. 이번에 처음 `Get-ScheduledTask`로
실제 확인했다.

## 실측 결과 ― 절반은 이미 해결돼 있었다

```
PS> Get-ScheduledTask | Where TaskName -match "auction|crawl|dojoon|law"

TaskName         State
--------         -----
DOJOONPASS_DAILY Ready

PS> Get-ScheduledTaskInfo -TaskName "DOJOONPASS_DAILY"

LastRunTime        : 2026-08-16 오전 3:00:01
LastTaskResult     : 0
NextRunTime        : 2026-08-17 오전 3:00:00

Action: cmd.exe /c "...\dojoonpass\run_daily.bat"
Trigger: 매일 03:00 (StartBoundary 2026-08-04)
```

**단순 등록 여부만 본 것이 아니라 실제 성공 여부까지 실측**했다(이 세션이
계속 강조해 온 "exit code 0 ≠ 진짜 성공" 원칙 그대로 적용) —
`logs/daily_run.log` 끝부분을 직접 읽었다:

```
[DB 갱신 결과]
  신규    : 86 건
  업데이트: 216 건
  실패    : 0 건
[DB 저장 현황] 총 저장 건수: 2,242 건
[SUCCESS] Finished at 2026-08-16  4:43:23.85
```

이 86건 신규/216건 업데이트는 이 세션이 이전에 관찰한 "auction_item이 2,156 →
2,242로 늘었다"(Sprint 134→138 사이 실측)의 원인을 그대로 설명한다 — **이
세션 내내 봐 온 데이터 증가가 사실은 이 스케줄러가 실제로 돌고 있다는
증거였는데, 아무도 그 둘을 연결하지 않았다.**

## 정확한 현재 상태 ― "미등록"이 아니라 "3개 중 1개만 등록"

`register_scheduler_tasks.ps1`(Sprint 112가 준비한 등록 스크립트)은 원래
**3개** 작업을 계획했다:

| 계획된 작업 | 배치 | 시각 | 실제 등록 상태 |
|---|---|---|---|
| `DojoonPass-DailyCrawl` | `run_daily.bat`(mvp_scraper+migrate_execute) | 06:00 | **다른 이름(`DOJOONPASS_DAILY`)·다른 시각(03:00)으로 이미 등록·정상 실행 중** |
| `DojoonPass-DocWorker` | `run_doc_worker.bat`(PDF 문서 수집) | 02:00 | **미등록** — `logs/doc_worker*.log` 자체가 존재하지 않음(실행된 적 없음) |
| `DojoonPass-PriorityRefresh` | `run_priority_refresh.bat`(우선순위 재계산) | 01:50 | **미등록** — 같은 이유로 로그 파일 없음 |

즉 "검색 결과 0건이 되는 것"(경매 목록 자체가 사라지는 위험)은 **이미
해소돼 있었다** — `DOJOONPASS_DAILY`가 매일 새 경매 목록을 계속 채워 넣고
있어 Sprint 112가 걱정한 "2026-08-20 검색 결과 0건" 시나리오는 일어나지
않는다. 대신 **다른, 지금까지 이 세션이 전혀 주목하지 않은 문제**가 실제로
존재한다:

### 새로 확인된 진짜 문제 ― `document_queue`가 계속 쌓이기만 한다

```
document_queue WHERE status='pending'  ->  3,996건
```

`mvp_scraper.py`는 새 물건을 등록할 때마다 `document_queue`에 문서 수집
작업을 넣는다(`docs/CLAUDE.md`의 파이프라인 설명 그대로). 그런데 그걸 실제로
소진하는 `doc_worker.py`가 스케줄에 없으니 **매일 늘어나기만 하고 줄어들지
않는다.** 이 세션이 Sprint 133/137에서 `doc_worker.py`를 직접 감사·수정까지
했으면서도(cp949 크래시 수정, 드라이버 재시작 캐스케이드 수정), 정작 "지금
이 파일이 스케줄에 아예 없어서 그 수정들이 실전에서 한 번도 발동한 적이
없다"는 사실은 놓치고 있었다.

### 실제 사용자 영향 정량화 ― "덜 급함"이 아니라 심각하다

처음엔 이 결과를 문서화하고 우선순위를 낮게 매기려 했으나, **현재 매각기일이
남아 사용자가 실제로 볼 수 있는 313개 물건**만 좁혀서 다시 재보니 그렇지
않았다:

```sql
SELECT ds.doc_type, ds.status, COUNT(*)
FROM document_status ds JOIN auction_item ai ON ai.id = ds.item_id
WHERE ai.auction_date >= '오늘'
GROUP BY ds.doc_type, ds.status
```

```
APPRAISAL(감정평가서)   COLLECTING 257  /  READY  56   (READY 18%)
SPEC(매각물건명세서)    COLLECTING 255  /  READY  58   (READY 19%)
STATUS(현황조사서)      COLLECTING 266  /  READY  47   (READY 15%)
```

**지금 사용자가 검색해서 볼 수 있는 물건 313건 중 약 82~85%가 문서 3종
전부 "수집중"으로 멈춰 있고, 이 스케줄러가 등록되지 않는 한 영원히 그
상태로 남는다.** 등기부/문서 확인은 이 서비스의 핵심 기능 중 하나라
(`docs/roadmap.md` "Beta v1 Scope"), 이건 "성능 최적화가 지연되는" 수준이
아니라 **핵심 기능이 사실상 동작하지 않는 상태에 가깝다.** 위 SKIP 표의
`DojoonPass-DocWorker` 등록을 "덜 급함"이 아니라 **가장 먼저 처리해야 할
사용자 조치**로 재분류한다.

## 왜 이 오류가 12개 Sprint 동안 이어졌나

이 세션의 "과거 기록을 실측과 대조한다"는 원칙은 **문서끼리의** 대조에는
철저했지만, "문서가 주장하는 것"과 "실제 OS 상태"의 대조는 이번이 처음이다.
Task Scheduler는 `docs/`에 없는 정보라 grep으로 찾을 수 없고, 이 세션 전체가
Python 테스트/DB 쿼리/API 호출로만 실측해 왔다 — 운영체제 수준 상태(스케줄된
작업, 서비스 등)를 직접 조회한 것은 이번이 처음이다. **DB에 새 데이터가
계속 늘고 있다는 것 자체가 단서였는데도, "누가 크롤러를 실행했는가"를
스케줄러 조회로 확인하기 전까지는 아무도 그 단서를 좇지 않았다.**

## 이번 세션이 하는 것 / 하지 않는 것

- 실제 OS 상태 조회(`Get-ScheduledTask`, `Get-ScheduledTaskInfo`)와 로그 실측 —
  **읽기 전용**, 수행함
- `register_scheduler_tasks.ps1`을 **dry-run(인자 없이)** 재실행해 스크립트
  자체가 지금도 유효한지 확인 — 수행함(아래 결과)
- 실제 `-Apply` 실행(작업 등록) — **여전히 SKIP**(운영 환경 변경, 승인 영역).
  다만 이제는 정확히 **2개**(DocWorker, PriorityRefresh)만 등록하면 된다는
  것을 알게 됐다는 점이 다르다

### dry-run 재확인 결과 ― 스크립트는 여전히 유효하나, 그대로 `-Apply`하면 중복이 생긴다

```
등록할 작업
  DojoonPass-PriorityRefresh   매일 01:50  (신규)
  DojoonPass-DocWorker         매일 02:00  (신규)
  DojoonPass-DailyCrawl        매일 06:00  (신규)   <- 이미 DOJOONPASS_DAILY(03:00)가 같은 일을 하고 있다!
```

스크립트는 작업 이름으로만 기존 여부를 판단하므로(`Get-ScheduledTask
-TaskName $t.Name`), 이름이 다른 `DOJOONPASS_DAILY`를 인식하지 못해 **셋
다 "신규"로 표시한다.** 지금 그대로 `-Apply`하면 `run_daily.bat`를 하루에
두 번(03:00, 06:00) 실행하는 **중복 작업**이 생긴다 — 해롭지는 않지만
(멱등적 upsert라 두 번 돌아도 데이터가 깨지지 않는다, `migrate_execute.py`의
UPSERT 설계 확인됨) 불필요하다. 사용자가 나중에 이 스크립트를 실행할 때는
`DojoonPass-DailyCrawl` 줄을 빼거나 기존 `DOJOONPASS_DAILY`를 정리하는 판단이
필요하다 — 이것도 운영 판단(어느 시각을 쓸지, 기존 작업을 유지할지)이라
SKIP, 다음 사용자 조치 항목에 정확히 남긴다.

## 후속 조치 ― `document-stats` API에 큐 적체 가시성 추가

이 문제(document_queue 3,996건 적체, 5주 이상 미발견)의 근본 원인 중 하나는
**이 값을 볼 수 있는 API/Admin 경로가 아예 없었다**는 것이다(`document_queue`를
실제로 조회하는 API 코드는 저장소 전체에 0곳, 이 파일 자신의 주석 한 줄뿐이었다).
운영 환경(스케줄러 등록)은 승인 영역이라 손대지 않지만, **다음에 같은 문제가
생겼을 때 DB를 직접 열어 보지 않아도 API로 바로 알 수 있게 만드는 것**은
순수 추가 기능(기존 필드/구조 무변경)이라 승인 없이 가능한 개선으로 판단해
바로 처리했다.

`api/v1/doc_stats.py:document_stats()`(`GET /api/v1/document-stats`)에 3개
필드 추가: `queue_pending`, `queue_in_progress`, `queue_failed`
(`document_queue.status` 그룹별 집계). 실 응답으로 확인:

```json
{"total_items": 2242, ..., "queue_pending": 3996, "queue_in_progress": 0, "queue_failed": 0}
```

`test_api_regression.py`에 3개 값을 각자의 출처(`document_queue.status`
GROUP BY)와 직접 대조하는 검사 3건 추가(기존 `total_failures` 검사와 같은
패턴 — "우연히 값이 맞아 보이는" 변이를 놓치지 않기 위해 자기 출처와
대조한다). **변이 검증**: `queue_pending`/`queue_in_progress` 필드를 서로
바꿔치기하는 변이를 걸어 새 검사 2건이 정확히 실패하는 것을 확인, 원복 후
`diff`로 원본과 바이트 단위 동일 확인.

## 검증

| 항목 | 결과 |
|---|---|
| `Get-ScheduledTask` 실측 | `DOJOONPASS_DAILY` 1건 등록, 나머지 2건 미등록 확인 |
| `logs/daily_run.log` 실측 | 오늘 86 신규/216 갱신/0 실패, `[SUCCESS]` 마커 확인 |
| `document_queue` pending 실측 | 3,996건(계속 누적 중) |
| `logs/doc_worker*.log`/`logs/priority*.log` 존재 여부 | 없음(한 번도 실행된 적 없음 확인) |
| `register_scheduler_tasks.ps1` dry-run 재실행 | 정상 동작, 선행조건 전부 OK, 그대로 두면 DailyCrawl 중복 생성 위험 확인 |
| `document-stats` API 신규 필드 실응답 확인 | `queue_pending=3996` 등 실제 DB 값과 일치 |
| `test_api_regression.py`(신규 검사 3건 포함) | 전체 PASS |
| `test_race_conditions.py` | 전체 PASS(회귀 없음) |
| `python -m compileall` / `npx tsc --noEmit` / `npm run lint` | 전부 통과 |
| 변이 검증 | `queue_pending`/`queue_in_progress` 뒤바꿈 → 신규 검사 2건 정확히 실패 → 원복 후 diff 0 |
| 운영 환경 변경 | 0건(Task Scheduler 조회만, 등록/수정/삭제 없음) |

## 수정 파일

```
api/v1/doc_stats.py                             document-stats에 queue_pending/queue_in_progress/queue_failed 3개 필드 추가
test_api_regression.py                          위 3개 필드를 자기 출처와 대조하는 검사 3건 추가
docs/SPRINT141_SCHEDULER_STATUS_CORRECTION.md   신규 (본 문서)
```

이 문서가 지금부터 "스케줄러 등록" 백로그의 최신 근거다 — 이후 Sprint의
"남은 Backlog"란은 Sprint 112가 아니라 이 문서를 인용해야 한다.

## SKIP (사용자 결정 필요)

| 항목 | 이유 |
|---|---|
| `DojoonPass-DocWorker`(02:00)/`DojoonPass-PriorityRefresh`(01:50) 등록 | 운영 환경(Task Scheduler) 변경 — 승인 영역. `register_scheduler_tasks.ps1 -Apply`로 실행 가능(사용자가 직접) |
| `DOJOONPASS_DAILY`(03:00)와 신규 `DojoonPass-DailyCrawl`(06:00) 중복 여부 정리 | 어느 시각을 쓸지는 운영 판단 — 기존 작업 유지 시 스크립트의 DailyCrawl 줄만 빼고 등록하거나, 기존 작업을 대체하는 두 가지 선택지를 문서로만 남김 |

## 남은 Backlog (갱신됨 ― 이전 표현 대체)

- ~~★★ 수집 파이프라인 스케줄러 등록 (2026-08-20 검색 결과 0건 위험)~~ →
  **부분 해소 확인(본 문서)**: 경매 목록 수집(`DOJOONPASS_DAILY`)은 이미
  정상 작동 중, 검색 결과 0건 위험은 없다
- **★★★ 신규, 최우선**: `document_queue` pending 3,996건이 매일 증가만 하고
  소진되지 않는다 — 실제 사용자가 보는 현재 매각기일 물건 313건 중
  82~85%가 문서 3종 전부 "수집중"에 멈춰 있다(위 정량화 참고). `run_doc_worker.bat`
  스케줄 등록 필요(위 SKIP 표), 사용자 조치 대기 — Sprint 112의 "검색결과
  0건" 위험보다 지금 당장은 더 심각하다
- `run_priority_refresh.bat` 스케줄 등록 필요(위 SKIP 표), 덜 급함(우선순위
  재계산 누락은 기능 손실이 아니라 정렬 최적화 지연)
- `DOJOONPASS_DAILY`/`DojoonPass-DailyCrawl` 중복 방지 판단(위 SKIP 표)
- Sprint 105~140 SKIP 표의 나머지 승인 대기 항목들
- 다음 Audit 영역: TODO/FIXME/HACK 2차, E2E Beta Journey(document_queue 적체가
  실제 사용자 화면에 미치는 영향 확인), Dead Code 2차 (계속 진행)
