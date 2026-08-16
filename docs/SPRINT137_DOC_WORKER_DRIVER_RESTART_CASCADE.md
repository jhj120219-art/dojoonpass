# Sprint 137 ― 브라우저 드라이버 재시작이 실패하면 무관한 항목들의 재시도 예산이 연쇄로 소모된다 (2026-08-16)

> 앞 Sprint: `docs/SPRINT136_DUPLICATE_CONFIG_CONSTANTS.md`
>
> **별도 파일 이유**: Sprint 100~136과 같다.

Failure Recovery Audit(`/goal`의 명시적 체크리스트 — "Worker crash", "Browser
crash")을 진행하며 `doc_worker.py`의 예외 처리 경로를 코드로 추적하다가 발견했다.

## 발견

`doc_worker.py:main()`의 메인 루프에서, 항목 처리 중 예외(브라우저 크래시,
사이트 오류 등)가 나면 `mark_queue_failed()`를 부르고 `restart_download_driver()`로
드라이버를 새로 만든다:

```python
except Exception as e:
    ...
    mark_queue_failed(item["id"], item["retry_count"])
    try:
        driver = restart_download_driver(driver)
    except Exception:
        pass          # <- 재시작 자체가 실패해도 그냥 넘어간다
```

`restart_download_driver()`가 **자기 자신도 실패하면**(ChromeDriver 실행 실패,
리소스 고갈 등 환경 문제), 예외가 `except Exception: pass`에 조용히 삼켜지고
`driver` 변수는 재할당되지 않은 채(죽은 이전 driver를 그대로 들고) 루프가
계속된다. 그러면:

1. 다음 큐 항목도 죽은 driver로 처리를 시도 → 즉시 실패
2. 그 항목도 `mark_queue_failed()` 호출 → **그 항목과 전혀 무관한 이유로**
   `retry_count`가 1 소모됨
3. 다시 `restart_download_driver()` 시도 → 같은 환경 문제로 다시 실패 → 반복
4. `is_time_up()`(04:00)까지 이 패턴이 큐가 빌 때까지 계속됨

## 왜 심각한가 ― 재시도 예산이 "죄 없는" 항목들에서 소모된다

`MAX_DOC_RETRY = 3`이고 `reset_stale_queue()`는 `failed`를 하루 지나면
`pending`으로 되살린다(4일 주기 재시도, `docs/CURRENT_STATE.md`/`docs/BUGS.md`
기존 기록). 그런데 이 재시도 카운터는 "이 항목 자체의 문제"를 세기 위한
것인데, 드라이버 환경 문제가 발생한 날에는 **그날 처리 순번이었을 뿐인 모든
항목**이 동시에 1회씩 재시도를 잃는다. 이런 환경 문제가 3번(꼭 연속일 필요도
없다) 겹치면, 실제로는 완전히 정상인 문서도 `retry_count >= MAX_DOC_RETRY`로
영구 `failed` 처리된다 — 사람이 보기엔 "이 문서만 계속 실패한다"로 보이지만
실제 원인은 그 문서와 무관한 인프라 문제였다는 뜻이다.

`DocWorkerOutcome.failure_reason()`(BUGS #47, Sprint 55)이 이미 "시도했는데
전부 실패"를 잡아 그 **실행 자체**는 정직하게 실패로 보고되지만, **그 실행이
갉아먹은 개별 항목들의 재시도 예산**까지는 보호하지 못했다 — 다른 층위의
문제라 별개로 고쳐야 했다.

## 재현 여부 확인

`docs/CURRENT_STATE.md`/`docs/BUGS.md`/기존 Sprint 문서에서
`restart_download_driver`/"재시작"/"연쇄" 관련 기록을 찾았으나 이 패턴은
기록된 적이 없다 — 새 발견이다. 코드에서 `restart_download_driver`를
참조하는 테스트도 0건이었다(전혀 검증된 적 없는 경로).

## 고친 것

`doc_worker.py`의 예외 처리에서, 드라이버 재시작 자체가 실패하면 **이번 실행을
즉시 중단**하도록 바꿨다(`break`). 큐 항목은 손대지 않은 채(claim되지 않은
채) 그대로 남으므로 데이터 유실이 아니라 "이번 실행만 조기 종료"다 — 다음
실행(다음날 02:00)에서 정상적으로 다시 시도된다. 재시작이 **성공**하면 기존과
동일하게 계속 처리한다(과잉 수정 아님 — 아래 테스트 2가 이를 확인한다).

## 회귀 테스트 신설

`doc_worker.py`는 selenium을 import하므로 실제 브라우저 없이 테스트하려면
모든 브라우저 호출부를 몽키패치해야 한다(`models/crawl_outcome.py`가
BUGS #47 때 판정 로직을 분리한 것과 같은 이유). 새 파일
`test_doc_worker_recovery.py`를 만들어 `doc_worker.main()`을 직접 구동한다:

- **시나리오 1**: 3개 항목이 큐에 있고, 매 항목마다 `go_to_case_detail`이 예외를
  던지며, `restart_download_driver`도 항상 실패한다. **기대**: 첫 항목만
  claim/실패 처리되고, 나머지 2건은 큐에 그대로 남는다(claim 자체가 안 됨).
- **시나리오 2**: 2개 항목, 첫 항목만 크래시하고 재시작은 성공한다. **기대**:
  두 항목 다 정상 처리된다(첫 항목 실패 + 둘째 항목 성공) — 시나리오 1의
  수정이 "항상 멈춘다"로 과잉 수정되지 않았음을 확인한다.

## 동일 패턴 전수 검색

`except Exception: pass` 뒤에 재시도/재접속 로직이 있고 그 실패가 무시되는
패턴이 다른 곳에도 있는지 crawler/storage 전체를 검색했다. `mvp_scraper.py`/
`court_crawler.py`/`refresh_priority.py`에는 이런 "재시작 실패를 삼키고 계속
진행" 구조가 없었다(각자 예외를 그대로 상위로 전파하거나 해당 법원만
`failed` 목록에 남기고 다음 법원으로 넘어가는 구조 — 이건 "법원 A의 문제가
법원 B에 영향 주지 않는다"는 올바른 격리라 같은 결함이 아니다). 이 패턴은
`doc_worker.py`의 드라이버 재시작 지점 하나뿐이었다.

## 사이드 이펙트 ― 이 세션 자신의 cp949 함정에 다시 걸림

새 코드/테스트 작성 중 `— `(EM DASH)를 두 번 다시 썼다가 `test_console_encoding.py`
(Sprint 133이 이미 고친 그 검사)가 아니라 **직접 실행해서** `UnicodeEncodeError`로
잡았다 — `test_doc_worker_recovery.py`는 `test_` 접두사 파일이라
`output_literals()`가 **모든** 리터럴을 검사 대상으로 보는데(§0 참고), 마침
설계상 이 검사를 먼저 돌리기 전에 새 테스트 자체를 실행하다 걸렸다. 즉시
하이픈으로 교체하고 `test_console_encoding.py`를 재실행해 이 파일도 깨끗하게
통과함을 확인했다(추가 수정 불필요 — Sprint 133의 검사 확장이 새 파일에도
자동으로 적용된다는 뜻이기도 하다).

## 변이 검증

| | 변이 | 결과 |
|---|---|---|
| M137 | `except Exception as restart_exc: ... break`를 `except Exception: pass`(원래 버그)로 되돌림 | **검출 O** ― 시나리오 1의 4개 assertion이 전부 실패(`claimed=[100,101,102]` vs 기대 `[100]`, `queue 남은 개수=0` vs 기대 `2` 등) — 시나리오 2는 영향받지 않고 그대로 PASS(격리 확인) |

원복 후 `diff`로 원본과 바이트 단위 동일 확인, 전체 스위트 재통과.

## 검증

| 항목 | 결과 |
|---|---|
| `test_doc_worker_recovery.py`(신설) | 전체 PASS(2 시나리오, 9검사) |
| `test_document_queue.py`/`test_document_status_sync.py`/`test_pipeline_integrity.py`/`test_collect_documents.py`/`test_crawl_resume.py`/`test_crawl_exit_code.py` | 전체 PASS(회귀 없음) |
| `test_schema_hygiene.py`/`test_bootstrap.py`/`test_auction_identity.py`/`test_api_regression.py`/`test_race_conditions.py`/`test_console_encoding.py` | 전체 PASS |
| `python -m compileall` | exit 0 |
| `npx tsc --noEmit` | exit 0 |
| `npm run lint` | 0 issues |
| 변이 잔여 | `doc_worker.py` 원본과 diff 0(원복 확인) |
| 실 DB | 무변경(신설 테스트는 큐/claim을 전부 몽키패치, 실제 큐 테이블에 쓰기 없음) |

## 수정 파일

```
doc_worker.py                     드라이버 재시작 실패 시 break(이번 실행 조기 종료)
test_doc_worker_recovery.py       신규 — 재시작 실패/성공 두 시나리오 회귀 테스트
docs/SPRINT137_DOC_WORKER_DRIVER_RESTART_CASCADE.md   신규 (본 문서)
```

**제품 정책 변경 0건.** 재시도 횟수·간격·문서 판정 기준 어느 것도 바꾸지
않았다 — "이번 실행에서 더 진행할 수 없는 상태(드라이버 자체가 안 뜬다)"를
"각 항목이 재시도 예산을 하나씩 잃어야 하는 상태"와 구분했을 뿐이다.

## SKIP

없음(제품 정책 변경 없는 순수 버그 수정).

## 남은 Backlog

- **★★ 수집 파이프라인 스케줄러 등록** ― 2026-08-20에 검색 결과 0건이 된다(Sprint 112, 4일 남음).
- Sprint 105~136 SKIP 표의 나머지 승인 대기 항목들
- 다음 Audit 영역: Test Gap 나머지, TODO/FIXME/HACK 2차, Dead Code, Security,
  Release Journey (계속 진행)
