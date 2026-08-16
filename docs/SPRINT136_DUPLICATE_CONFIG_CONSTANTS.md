# Sprint 136 ― `config/settings.py`가 5개 상수를 다른 모듈과 독립적으로 중복 선언하고 있었다 (2026-08-16)

> 앞 Sprint: `docs/SPRINT135_BETA_CHECKLIST_STALE_P0.md`
>
> **별도 파일 이유**: Sprint 100~135와 같다.

Architecture Audit(`/goal` §4 — 책임 중복/누락 전수 확인)을 진행하며 재시도 정책의
소유권(retry 책임)이 어디 있는지 추적하다가 발견했다.

## 발견

`storage/database.py:10-11`에 `MAX_DOC_RETRY = 3` / `RETRY_INTERVAL_MINUTES = 30`이
있는데, `config/settings.py:66-67`에도 **같은 이름, 같은 값**이 독립적으로 또
있었다. grep으로 실제 사용처를 추적한 결과 `storage/database.py`가 쓰는 것은
**자기 자신의 모듈 전역 변수**뿐이었고(`mark_queue_failed()`/
`claim_next_queue_item()`이 그 값을 직접 참조), `config/settings.py` 쪽 사본은
**저장소 어디에서도 import되지 않는 죽은 코드**였다.

"동일 패턴 전수 검색"으로 `config/settings.py`의 나머지 상수도 대조한 결과, 같은
모양이 2건 더 있었다: `PAGE_LOAD_TIMEOUT` / `ELEMENT_TIMEOUT` / `AJAX_TIMEOUT`이
`crawler/base_crawler.py`에도 독립적으로 재선언돼 있었다(값도 동일: 30/20/30).
`crawler/base_crawler.py`는 이미 같은 파일(`config/settings.py`)에서
`random_delay`/`CourtInfo`/`MAX_ITEMS`를 정상적으로 import하고 있어서, 타임아웃
세 값만 유독 복사돼 있는 것이 더 눈에 띄었다 — import를 안 하기로 한 결정이
아니라 그냥 두 번 선언된 흔적으로 보인다.

**왜 위험한가**: 지금은 두 사본의 값이 우연히 같아 겉으로 드러나지 않는다.
하지만 실제로 동작을 바꾸는 쪽(`storage/database.py`/`crawler/base_crawler.py`
자신의 사본)과 "설정 파일"이라는 이름표를 단 `config/settings.py`의 사본이
따로 논다 — 누군가 `config/settings.py`의 값만 바꾸고 "설정을 바꿨다"고
믿으면, 실제 동작은 전혀 바뀌지 않는다. 이 저장소가 이미 여러 번 겪은
"두 번째 진실(second source of truth)" 문제의 작은 버전이다.

## 동일 패턴 2차 확인 — 삭제하지 않고 남긴 것

같은 방식으로 `config/settings.py`의 나머지 상수(`COURTS`, `SIDO_LIST`,
`DOC_TYPE_LIST`, `PRIORITY_REFRESH_TIME`)도 확인했다. `COURTS`는 Sprint 43이
이미 "죽은 목록, 삭제는 안 함(P3)"으로 처리해 둔 것을 재확인했을 뿐 새 발견이
아니다. `SIDO_LIST`/`DOC_TYPE_LIST`/`PRIORITY_REFRESH_TIME`은 코드에서 어디서도
안 쓰이지만(`PRIORITY_REFRESH_TIME`은 `refresh_priority.py`가 실제로 참조하지
않음을 직접 확인 — 01:50 스케줄은 Windows Task Scheduler 설정에만 있고 이
파이썬 상수와 연결돼 있지 않다), **이들은 "다른 파일의 사본"이 아니라 그 자체로
유일한 값이라 지워도 정보가 사라질 뿐 정합성 문제를 해소하지 않는다** — 위
5개(진짜 중복)와는 다른 범주라 판단해 삭제하지 않았다(Sprint 43의 같은 판단
기준을 그대로 적용).

## 고친 것

`config/settings.py`에서 죽은 사본 5개를 지웠다(값이 바뀐 것이 아니라 사본을
없앤 것 — 실제 정책 값은 `storage/database.py`/`crawler/base_crawler.py`에
그대로 남아 동작 변화 없음):

```
MAX_DOC_RETRY            (storage/database.py에 원본 있음)
RETRY_INTERVAL_MINUTES   (storage/database.py에 원본 있음)
PAGE_LOAD_TIMEOUT        (crawler/base_crawler.py에 원본 있음)
ELEMENT_TIMEOUT          (crawler/base_crawler.py에 원본 있음)
AJAX_TIMEOUT             (crawler/base_crawler.py에 원본 있음)
```

`storage/database.py` 쪽을 `from config.settings import ...`로 바꿔 합치는
방향은 **일부러 택하지 않았다** — `test_pipeline_integrity.py`가
`MAX_DOC_RETRY\s*=\s*(\d+)`로 `storage/database.py`의 소스 텍스트에서 리터럴
할당을 직접 읽어 "테스트가 값을 따로 복제하지 않는다"는 목적을 지키고 있는데,
import 문으로 바꾸면 그 형태가 깨져 이 검사가 실패한다. 더 안전한 쪽(실제로
안 쓰이는 사본 삭제)을 택했다.

## 회귀 테스트 신설

`test_schema_hygiene.py`에 §9(`test_no_duplicate_config_constants`) 신설 —
`config/settings.py`와 `storage/database.py`/`crawler/base_crawler.py`가 AST로
읽은 최상위 UPPER_SNAKE 상수 이름 집합을 서로 대조해, 같은 이름이 양쪽에
독립적으로 존재하면 실패한다. 이번에 발견한 5개 사례를 다시 만들지 않는 것이
목적이지, 지금 상태를 그대로 봉인하는 스냅샷 검사가 아니다(이름이 겹치는 것
자체가 항상 나쁜 것은 아니지만, 지금까지 이 저장소에서 겹친 사례가 전부
의도치 않은 중복이었으므로 새로 생기면 사람이 한 번 보게 하는 것이 목적).

## 변이 검증

| | 변이 | 결과 |
|---|---|---|
| M136 | `config/settings.py`에 `MAX_DOC_RETRY: int = 3`를 다시 추가(중복 재도입) | **검출 O** ― §9가 `["storage/database.py <-> config/settings.py: ['MAX_DOC_RETRY']"]`로 즉시 실패 |

원복 후 `diff`로 원본과 바이트 단위 동일 확인, 전체 스위트 재통과.

## 검증

| 항목 | 결과 |
|---|---|
| `test_document_queue.py` / `test_document_status_sync.py` / `test_pipeline_integrity.py` / `test_collect_documents.py` / `test_crawl_resume.py` / `test_crawl_exit_code.py` | 전체 PASS(회귀 없음 — 큐 재시도 정책 관련 테스트 전부) |
| `test_schema_hygiene.py` | 전체 PASS(신설 §9 포함) |
| `test_bootstrap.py` / `test_auction_identity.py` / `test_api_regression.py` / `test_race_conditions.py` / `test_console_encoding.py` | 전체 PASS |
| `python -m compileall` | exit 0 |
| `npx tsc --noEmit` | exit 0 |
| `npm run lint` | 0 issues |
| 변이 잔여 | `config/settings.py` 원본과 diff 0(원복 확인) |
| 실 DB | 무변경(코드/테스트 파일만 수정) |

## 수정 파일

```
config/settings.py       중복 상수 5개 삭제(값 변경 없음, 원본은 각 실제 사용처에 그대로 존재)
test_schema_hygiene.py   §9 test_no_duplicate_config_constants() 신설
docs/SPRINT136_DUPLICATE_CONFIG_CONSTANTS.md   신규 (본 문서)
```

**런타임 동작 변경 0건.** 크롤러/큐의 재시도 횟수(3회)·재시도 간격(30분)·
페이지로드/AJAX/Element 타임아웃(30/30/20초) 전부 기존과 동일 — 안 쓰이던
사본만 지웠다.

## SKIP

없음(제품 정책 변경 없는 순수 코드 정리).

## 남은 Backlog

- **★★ 수집 파이프라인 스케줄러 등록** ― 2026-08-20에 검색 결과 0건이 된다(Sprint 112, 4일 남음).
- `SIDO_LIST`/`DOC_TYPE_LIST`/`PRIORITY_REFRESH_TIME`(진짜 중복은 아니지만 미사용) —
  삭제 여부는 정보 손실을 동반하므로 이번엔 보류, 필요시 별도 승인 검토 대상
- Sprint 105~135 SKIP 표의 나머지 승인 대기 항목들
- 다음 Audit 영역: Failure Recovery(Provider/Worker/Browser crash 실제 주입 테스트),
  Test Gap, TODO/FIXME/HACK 2차, Dead Code, Security, Release Journey (계속 진행)
