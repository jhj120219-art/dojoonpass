# Sprint 142 ― doc_worker.py 동시 실행 시 다운로드 폴더 교차 오염 위험 방지 (2026-08-16)

> 앞 Sprint: `docs/SPRINT141_SCHEDULER_STATUS_CORRECTION.md`
>
> **별도 파일 이유**: Sprint 100~141과 같다.

`/goal`이 지정한 "Scheduler/Worker Audit — worker 운영 안정성"을 Sprint 141의
발견(document_queue 적체, doc_worker.py 스케줄 미등록)에 이어서 진행했다.

## 조사 ― 스케줄 등록 후 실제로 안전하게 돌 것인가

Sprint 141은 "스케줄이 없다"까지만 확인했다. 이번엔 "스케줄을 등록하면
안전하게 돌아가는가"를 코드로 검증했다. 먼저 환경 자체가 준비됐는지
읽기 전용으로 확인했다 — `ChromeDriverManager().install()`이 성공해
ChromeDriver가 정상 확보됨을 확인(브라우저는 열지 않음, 실크롤 아님).

## 발견 ― 다운로드 폴더가 프로세스 간 공유된다

`crawler/doc_paths.py:DOWNLOAD_DIR`는 모듈 전역 상수로, **모든 doc_worker.py
실행이 같은 디렉터리(`downloads/`)를 공유**한다. `wait_for_download()`는
"다운로드 전 파일 목록"과 "다운로드 후 파일 목록"의 차집합으로 방금 받은
파일을 찾는다(`crawler/doc_crawler.py`, Sprint 40이 만든 로직). 이 방식은
**같은 시각에 doc_worker.py 프로세스가 두 개 이상 떠 있으면 깨진다** — 한
프로세스가 받은 파일을 다른 프로세스가 "내가 방금 받은 파일"로 착각해
전혀 다른 물건의 문서로 저장할 수 있다(교차 오염).

`register_scheduler_tasks.ps1`이 준비하는 예약 작업은 `MultipleInstances`를
명시하지 않아 Windows 기본값(`IgnoreNew`)을 쓴다 — **같은 예약 작업**끼리는
겹치지 않는다. 하지만 이것으로 막히지 않는 경로가 있다: 운영자가 수동으로
`python doc_worker.py`를 터미널에서 실행하는 동안 예약된 실행이 겹치는
경우(오탐/디버깅 중 흔히 생기는 실수), 또는 예약 작업이 `ExecutionTimeLimit`을
넘겨 강제 종료된 직후 다음 트리거가 겹치는 경우다.

`docs/CURRENT_STATE.md`/`docs/BUGS.md`에서 "다운로드 폴더 공유"/"동시 실행"
관련 기록을 찾았으나 없었다 ― 새 발견이다.

## 고친 것 ― 순수 파이썬 파일 잠금(새 의존성 없음)

`doc_worker.py`에 `_acquire_lock()`/`_release_lock()` 신설:

- `logs/doc_worker.lock`에 PID+시각을 기록해 락으로 쓴다.
- 락이 있고 **5시간 이내**면 다른 인스턴스가 실행 중으로 보고 즉시
  종료 코드 0으로 종료(큐/브라우저 전혀 건드리지 않음 — Selenium 기동
  비용도 쓰지 않도록 락 확인을 `build_download_driver()`보다 먼저 둠).
- 락이 있지만 **5시간 이상 지났으면** 죽은 실행(프로세스 kill 등)으로
  보고 회수한다 — `reset_stale_queue()`의 10분 in_progress 회수와 같은
  "시간 기반 죽은 소유자 판정" 원칙. PID 생존 확인(예: `psutil`)은 새
  의존성이 필요해 쓰지 않았다 — 시간 기반 판정으로 충분하고, 예약
  작업의 `ExecutionTimeLimit`(4시간)보다 여유 있게 5시간으로 잡았다.
- 정상 종료(성공/실패 무관)면 `finally`에서 락을 반드시 해제한다.

**제품 정책 변경 없음.** 재시도 횟수/간격/문서 판정 기준 어느 것도 바꾸지
않았고, `crawler/doc_crawler.py`(0% 커버리지, 실 브라우저 없이 안전하게
검증 불가)의 다운로드 귀속 로직 자체는 건드리지 않았다 — 그 대신 **동시
실행 자체를 막아** 그 로직이 절대 두 프로세스에서 동시에 도는 상황에
놓이지 않게 했다. 위험이 큰 코드를 고치는 대신, 위험한 상황 자체를
사전 차단하는 더 안전한 접근이다.

## 회귀 테스트 신설 (3건)

`test_doc_worker_recovery.py`에 추가:

1. `test_lock_prevents_concurrent_run` — 신선한 락이 있으면 `init_db()`조차
   불리지 않고 즉시 종료 코드 0을 반환하는지 확인(호출되면 즉시
   `AssertionError`를 던지는 가짜로 모든 큐 관련 함수를 바꿔 강하게 검증).
2. `test_stale_lock_is_taken_over` — 5시간보다 오래된 락은 회수해 새로 잡을
   수 있는지 확인.
3. `test_lock_released_after_normal_run` — 정상 실행 후 락 파일이 남지
   않는지 확인(다음 날 실행이 영원히 막히지 않아야 함).

## 사후 발견 ― 이 세션 자신이 또 cp949 함정에 걸렸다(즉시 수정)

새 코드 작성 중 `logger.warning()`/`logger.info()` 실제 출력 문자열에
EM DASH(`—`)를 두 곳 다시 썼고, 새 테스트의 `AssertionError` 메시지에도
한 곳 썼다. `test_console_encoding.py`(Sprint 72 신설, Sprint 133이 "출력
래퍼 함수" 탐지로 확장)가 **즉시 잡았다** — 회귀 스위트를 전체로 돌리는
습관이 실제로 작동한 사례로 그대로 남긴다. 세 곳 다 하이픈으로 교체,
재검사 통과 확인.

## 변이 검증

| | 변이 | 결과 |
|---|---|---|
| M142 | `main()`의 `if not _acquire_lock(): ... return 0` 블록 제거(락 확인 자체를 없앰) | **검출 O** ― `test_lock_prevents_concurrent_run`이 `init_db()` 호출 시점에 `AssertionError`로 즉시 실패("claim_next_queue_item이 불렸다 - 락이 큐 접근을 막지 못했다") |

원복 후 `diff`로 원본과 바이트 단위 동일 확인, 잔여 락 파일 없음 확인.

## 검증

| 항목 | 결과 |
|---|---|
| `test_doc_worker_recovery.py`(신규 3검사 포함, 총 8시나리오) | 전체 PASS |
| `test_console_encoding.py` | 최초 FAIL(3곳 EM DASH) → 수정 후 PASS |
| `test_api_regression.py`/`test_race_conditions.py`/`test_schema_hygiene.py`/`test_bootstrap.py`/`test_pipeline_integrity.py`/`test_document_queue.py`/`test_document_status_sync.py`/`test_collect_documents.py`/`test_crawl_resume.py`/`test_crawl_exit_code.py` | 전체 PASS(회귀 없음) |
| `python -m compileall` / `npx tsc --noEmit` / `npm run lint` | 전부 통과 |
| 변이 잔여 | `doc_worker.py` 원본과 diff 0(원복 확인) |
| ChromeDriver 실측 | 정상 확보(실크롤 아님, 브라우저 미기동) |
| 실 DB/운영 환경 변경 | 0건 |

## 수정 파일

```
doc_worker.py                     _acquire_lock()/_release_lock() 신설, main() 진입부에 배선
test_doc_worker_recovery.py       락 시나리오 3건 신설 + 자체 cp949 수정
docs/SPRINT142_DOC_WORKER_CONCURRENT_INSTANCE_LOCK.md   신규 (본 문서)
```

## SKIP

없음(제품 정책 변경 없는 순수 안정성 개선 — 새 의존성 없음, 스키마 변경 없음).

## 남은 Backlog

- **★★★ 최우선**: `DojoonPass-DocWorker`/`DojoonPass-PriorityRefresh` 스케줄 등록
  (Sprint 141) — 현재 매각기일 물건의 82~85%가 문서 미수집 상태
- `DOJOONPASS_DAILY`/`DojoonPass-DailyCrawl` 중복 방지 판단(Sprint 141)
- `crawler/doc_crawler.py`의 다운로드 귀속 로직 자체를 프로세스별로 격리하는
  더 근본적인 리팩터링 — 지금은 락으로 상황 자체를 막았으니 급하지 않음,
  Selenium 모킹 인프라가 갖춰지면 재검토 후보
- Sprint 105~141 SKIP 표의 나머지 승인 대기 항목들
- 다음 Audit 영역: TODO/FIXME/HACK 2차, Dead Code 2차, Documentation Drift
  나머지, Release Readiness 종합 (계속 진행)
