# Sprint 138 ― Test Gap 전수 재측정 + `court_crawler.py`의 낮은 심각도 재시작 공백 (2026-08-16)

> 앞 Sprint: `docs/SPRINT137_DOC_WORKER_DRIVER_RESTART_CASCADE.md`
>
> **별도 파일 이유**: Sprint 100~137과 같다.

`/goal`의 1순위(Test Gap Audit)부터 시작했다. 먼저 이 저장소의 `test_*.py` 전체
목록을 다시 세었다 — 32개(`test_db.py`/`test_docs.py`/`test_docs2.py`는 실크롤
가드로 제외). 이전 세션들이 개별적으로 실행은 해 왔지만, 파일명 기준 전체
목록으로 한 번에 확인한 것은 이번이 처음이다 — `test_beta_journey.py`,
`test_auth_jwt.py`, `test_checkpoint_atomicity.py`, `test_doc_storage_atomicity.py`,
`test_false_success.py`는 이 세션이 이름 단위로 개별 언급한 적이 없었다.

## 1. 전체 스위트 기준선 재확인

29개 파일(실크롤 3개 제외) 전부 `coverage run`으로 순서대로 실행 — **전부
PASS**. 특히:

- `test_beta_journey.py`: "BETA JOURNEY GATE PASSED", dev 서버 미기동으로
  프런트 로그인 게이트 1단계만 SKIPPED(명시적으로 보고, 조용히 통과 아님) —
  그 부분은 `tests/source-contract.test.mjs`의 "로그인 성공 후 복귀 계약"
  소스 계약 테스트가 서버 없이도 이미 검증하고 있어 실질적 공백은 아니다
- `test_auth_jwt.py`: 39/39 PASS
- `test_false_success.py`: 0바이트 문서 서빙 차단, 등기부 orphan 가시성 등
  이 세션이 이전에 수동으로 재현/검증했던 것과 같은 항목들을 이미 자동화된
  회귀로 갖고 있었다(예: Sprint 134에서 확인한 0바이트 파일 차단 로직이
  `test_false_success.py::test_zero_byte_document_is_not_served`로 이미
  고정돼 있음)
- `test_checkpoint_atomicity.py`/`test_doc_storage_atomicity.py`: 크래시
  시뮬레이션 원자적 쓰기, 손상 파일, `wait_for_download` 완료 판정 등을
  이미 전수 검증하고 있었다 — Sprint 134에서 수동으로 재확인했던
  `shutil.move()`/`.crdownload` 필터링 안전성이 이미 자동 테스트로 고정돼
  있었다는 뜻(중복 작업은 아니었다 — 그때는 실측 확인이었고 이건 그
  실측이 기존에 이미 회귀로도 잠겨 있었음을 이번에 알게 된 것)

## 2. `api/`, `storage/`, `crawler/`, `models/`, `config/` 전수 커버리지 재측정

```
TOTAL   3008 stmts, 526 miss, 83%
```

`api/`(대부분 96~100%), `storage/database.py`(91%), `models/`, `config/`는
전부 이전 세션 수준을 유지하거나 그 이상이다. 낮은 것은 전부
**Selenium을 직접 조작하는 코드**뿐이다:

```
crawler/court_crawler.py    0%    <- 이번에 처음 개별 확인
crawler/doc_crawler.py     23%
crawler/base_crawler.py    46%
```

이는 결함이 아니라 이 저장소의 기존 설계다 — 순수 로직(파싱/해시/원자적
쓰기/재개 인덱스 계산)은 `crawler/resume.py`, `crawler/doc_paths.py`,
`models/crawl_outcome.py`처럼 selenium 의존성이 없는 모듈로 분리해 100%
테스트하고(이 세션의 grep으로 재확인: 두 파일 다 100%), 실제
`driver.find_element(...)` 호출부는 `ALLOW_LIVE_CRAWL=1` 가드 뒤의
`test_db.py`/`test_docs.py`/`test_docs2.py`만 건드린다. 이 구조 자체를
바꾸는 것은 이 세션 범위 밖(대규모 Selenium 모킹 인프라 신설)이라 하지
않는다.

## 3. `court_crawler.py`의 재시작 공백 ― 발견, 낮은 심각도로 판단해 코드는 건드리지 않음

0% 커버리지 파일을 읽다가 Sprint 137과 **비슷하지만 다른** 모양을 찾았다.

```python
# crawler/court_crawler.py:140-145
try:
    result = crawl_detail(driver, item_info, court)
except Exception as e:
    logger.error("세션 오류 감지: %s. 드라이버 재시작", str(e))
    driver = restart_driver(driver)          # <- 이 호출 자체가 실패하면?
    result = crawl_detail(driver, item_info, court)
```

`restart_driver()`(`crawler/base_crawler.py:35`)가 실패하면(Sprint 137이 고친
`restart_download_driver()`와 정확히 같은 실패 모드 — ChromeDriver 실행
실패 등) 예외가 이 지점에 방어막 없이 그대로 위로 전파된다. `crawl_court()`의
`for idx in range(start_idx, total):` 루프 밖으로 빠져나가 그 법원의 나머지
항목은 이번 실행에서 전부 건너뛰게 된다.

### Sprint 137과 다른 점 ― 왜 같은 방식으로 고치지 않았나

Sprint 137의 doc_worker.py는 **유한한 재시도 예산**(`document_queue.retry_count`,
`MAX_DOC_RETRY=3`)을 가진 큐를 처리한다 — 재시작 실패가 무관한 항목의
예산을 갉아먹으면 그 항목이 **영구적으로** failed가 될 수 있었다.

`mvp_scraper.py`/`crawl_court()`는 다르다. 경매 목록은 **매일 법원
웹사이트에서 새로 긁는 것**이라 재시도 예산 개념이 없다 — 오늘 법원 X의
6번째 물건에서 재시작이 실패해 7~20번째 물건을 못 가져와도, **내일 같은
법원을 다시 통째로 크롤링하면 그 물건들이 다시 목록에 잡힌다**(체크포인트는
5번째까지 저장했으므로 오히려 다음 실행이 5번째부터 재개해 효율적이다).
게다가 `mvp_scraper.py:67-78`의 법원 단위 `try/except`가 이미 이 실패를
그 법원 하나로 격리한다(다른 법원 진행에 영향 없음, grep으로 재확인).
**즉 데이터 유실이 아니라 "오늘 못 가져온 몇 건이 내일로 미뤄지는 것"** —
Sprint 137이 고친 "영구적으로 잘못 실패 처리됨"과는 실제 피해 크기가
다르다.

### 판단 ― 지금은 코드를 고치지 않는다

낮은 심각도(자가 치유됨, 24시간 안에 저절로 복구)와 이 파일의 커버리지가
0%(실제 Selenium 없이 안전하게 검증할 방법이 제한적 — `restart_driver` 자체를
몽키패치하는 것은 가능하지만 `crawl_court()` 전체를 구동하려면
`build_driver`/`go_to_schedule`/`collect_list_items`/`CheckpointManager`까지
전부 가짜로 바꿔야 해서 Sprint 137보다 훨씬 큰 몽키패치 표면이 필요하다)를
함께 고려해, "실제 결함이지만 즉시 고칠 만큼 가치가 크지 않다"로 판단했다
(`/goal`의 "단순 가능성만 있으면... 과잉수정하지 않는다"는 원칙 — 여기서는
가능성이 아니라 실제 재현 가능한 코드 경로지만, 피해가 자가 치유되는
낮은 심각도라 지금 투입 대비 가치가 낮다). 문서로 남겨 다음 세션이 중복
조사하지 않게 한다.

## 검증

| 항목 | 결과 |
|---|---|
| 전체 테스트 스위트(29개, 실크롤 3개 제외) | 전부 PASS |
| `api`/`storage`/`crawler`/`models`/`config` 커버리지 | 83% (Selenium 직접조작부만 낮음, 설계상 정상) |
| `test_bootstrap.py` §3-B 드리프트 재확인 | Sprint 122 발견 그대로 유지(변동 없음, "[정리됨]" 출력 없음 — 예상대로) |
| 코드 변경 | 0건(발견만, 판단에 따라 보류) |

## 수정 파일

```
docs/SPRINT138_TEST_GAP_AND_COURT_CRAWLER_RESTART.md   신규 (본 문서)
```

## SKIP

없음(승인 필요 항목 아님 — 위험 대비 낮은 가치로 자체 판단해 보류한 것).

## 남은 Backlog

- **★★ 수집 파이프라인 스케줄러 등록** ― 2026-08-20에 검색 결과 0건이 된다(Sprint 112, 4일 남음).
- `court_crawler.py`의 `restart_driver()` 실패 공백 ― 낮은 심각도로 보류(위 §3),
  Selenium 모킹 인프라가 이 저장소에 생기면 그때 함께 처리할 후보
- Sprint 105~137 SKIP 표의 나머지 승인 대기 항목들
- 다음 Audit 영역: Architecture(계속), Transaction/Concurrency 나머지, API
  Contract, DB Schema Drift 재확인, Frontend Contract, Release Readiness,
  E2E Beta Journey(dev 서버 기동 시도 포함 검토) (계속 진행)
