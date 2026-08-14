# Sprint 101 — 문서 수집 재시도 고리와 시각 비교 (2026-08-14)

> 앞 Sprint: `docs/SPRINT100_ENV_PERF_AUDIT.md`
>
> **별도 파일 이유**: Sprint 100과 같다 — `docs/BUGS.md` / `docs/CURRENT_STATE.md`는
> 다른 세션의 편집 대상이라 충돌을 피했다.

기준점 `fc22381`, working tree 깨끗한 상태에서 시작했다. **이전 Sprint 보고서를 사실로
가정하지 않고** 실 DB(1,876 물건 / 5,628 문서상태 / 3,498 큐)와 실제 파일 722개를
직접 대조하는 것으로 시작했다.

그 감사에서 **제품 결함 2건**을 찾았다. 둘 다 조용한 결함이다 — 예외도 나지 않고,
로그는 오히려 정상이라고 말하고 있었다.

---

## #101-1 ★ 성공할 수 없는 문서가 4일 주기로 영원히 재시도된다

**심각도** 높음 (사용자 화면 상태가 계속 뒤집힌다 + 매일 헛일)

### 무엇이 잘못됐나

`doc_worker.py`는 큐에서 집은 항목마다 `get_doc_button_id(doc_type, item_no)`를 부르고,
None이면 브라우저를 열지 않는다. None이 되는 조건은 **둘 다 영구적**이다.

```
현황조사서(status) + item_no != '1'   DOM으로 확인된 버튼 id가 없다
알 수 없는 doc_type                    애초에 대응하는 버튼이 없다
```

그런데 이 경로가 `mark_queue_failed()`를 불렀다. **실패는 재시도 대상**이고,
`reset_stale_queue()`는 하루 지난 `failed`를 `pending` + `retry_count=0`으로 되살린다.
성공 가능성이 0인 항목이 그 고리에 들어가면 빠져나올 길이 없다.

### 실측 재현 (selenium 없이, 16일치를 돌렸다)

```
day  1  queue=pending  retry=1   화면 COLLECTING
day  2  queue=pending  retry=2   화면 COLLECTING
day  3  queue=failed   retry=3   화면 FAILED       <- 재시도 소진
day  4  (reset_stale_queue 가 되살린다)
day  5  queue=pending  retry=1   화면 COLLECTING   <- 처음으로 되돌아간다
...
16일 동안 12회 시도. 성공 가능성은 0.
```

나쁜 점이 둘이다.

1. **매일 claim 슬롯을 먹는다.** doc_worker는 02:00~04:00 두 시간만 도는데, 절대
   성공하지 못할 항목이 그 시간을 쓴다.
2. **화면 상태가 4일 주기로 "수집실패" ↔ "수집중"을 오간다.** 사용자는 같은 문서가
   며칠마다 상태를 바꾸는 것을 보지만 실제로 달라진 것은 아무것도 없다.

### 왜 오래 살아남았나

Sprint 75가 이 경로를 정확히 들여다봤고, "큐에서 빼면 `COLLECTING`에 영원히 머무니
빠르게 실패로 남기는 쪽이 더 정직하다"고 판단했다. **그 판단 자체는 옳다.**
놓친 것은 `reset_stale_queue()`와의 상호작용이다 — 한 함수만 보면 보이지 않고,
**여러 날을 돌려 봐야** 드러난다.

### 수정

`SKIPPED_EXPIRED`와 같은 계열의 종결 처리를 만들었다. "실패"가 아니라 "애초에 대상이
아님"이다.

```
storage/database.py   mark_queue_unsupported()  신설
doc_worker.py         `if not btn_id:` 분기가 이 함수를 부른다
```

- 큐 status = `SKIPPED_UNSUPPORTED` — `reset_stale_queue()`가 건드리는 대상
  (`failed`, `in_progress`)이 아니므로 **자동으로 재시도 고리에서 빠진다**.
- `retry_count`를 소모하지 않는다(실패가 아니므로).
- 화면 상태는 `FAILED`로 **한 번만** 쓴다 — Sprint 75의 판단을 그대로 유지한다.
  달라지는 것은 **시점과 안정성**뿐이다: 3일 뒤가 아니라 즉시, 그리고 다시 뒤집히지 않는다.

`SKIPPED_EXPIRED`와 마찬가지로 이것도 "현재 구조 기준"의 기록이다. 현황조사서의 다른
item_no 버튼 id가 밝혀지면 별도 운영 스크립트로 `pending` 복귀시키면 된다.
**자동 부활은 일부러 하지 않는다 — 그것이 바로 위의 무한 고리였다.**

### 지금 데이터에 실제로 몇 건인가 (가정이 아니라 실측)

```
큐 전체                                3,498
버튼 id 없음(영구)                       109   전부 doc_type='status', item_no>=2
  그중 pending                          103
  그중 SKIPPED_EXPIRED                    6
★ pending + 매각기일이 아직 남은 행         2
```

그 2건이 **지금 기본 검색(D7)에 뜨는 9개 물건 중 2개**다.

```
서울중앙지방법원 2025타경311 물건2  status  기일=2026-08-19   (item id 11856)
서울중앙지방법원 2025타경939 물건2  status  기일=2026-08-19   (item id 11858)
```

가정한 시나리오가 아니라 **사용자가 오늘 열어 볼 수 있는 화면**이다. 고치지 않았다면
이 두 물건의 현황조사서 상태가 매각기일까지 "수집중" ↔ "수집실패"를 오갔을 것이다.
나머지 101건은 기일이 지나 doc_worker의 2차 방어선(`SKIPPED_EXPIRED`)이 먼저 잡는다.

### 새 검사

`test_document_queue.py` §16 — **16일치를 실제로 돌려** 시도가 1회로 끝나는지 본다.
한 번의 호출만 보면 예전 코드도 1일차는 똑같이 동작하므로 이 결함을 잡지 못한다.
§17은 반대 방향을 고정한다 — 버튼 id가 **있는** 항목의 3회 재시도는 그대로여야 한다
(일시적 장애를 한 번에 영구 포기하면 고치려던 것보다 나쁘다).

---

## #101-2 ★ `RETRY_INTERVAL_MINUTES = 30`은 30분이 아니라 9시간 30분이었다

**심각도** 높음 (재시도·회수 방어 장치 둘이 설계대로 동작한 적이 없다)

### 무엇이 잘못됐나

이 저장소는 시각을 **로컬 시각**으로 저장한다 — `datetime.now().isoformat()`.
그런데 SQLite의 `datetime('now')`는 **UTC**다. 둘을 그대로 비교하고 있었다.

```
저장값            2026-08-14T09:53:43   (로컬, 파이썬이 씀)
datetime('now')   2026-08-14 00:53:43   (UTC, SQLite)
```

저장값이 9시간 "미래"로 보이므로 `datetime(last_attempt_at) <= datetime('now','-30 minutes')`는
**실제로 9시간 30분이 지나야** 참이 된다.

| 코드가 말하는 것 | 실제 (한국=UTC+9) |
|---|---|
| `claim_next_queue_item()` 재시도 간격 30분 | **9시간 30분** |
| `reset_stale_queue()` in_progress 회수 10분 | **9시간 10분** |
| `reset_stale_queue()` failed 회수 1일 | **33시간** |

### 왜 이것이 실제 문제인가

doc_worker는 **02:00~04:00 두 시간**만 돈다.

- 재시도 간격이 9시간 반이면 **한 번 실패한 문서는 그날 밤 안에 다시 시도될 수 없다.**
  `MAX_DOC_RETRY = 3`이 90분이 아니라 **3일**에 걸쳐 소진된다.
- in_progress 회수가 9시간 10분이면, Worker가 02:10에 죽어 남긴 행은 **그날 밤 내내
  회수되지 않는다.** "비정상 종료 회수"라는 기능이 자기가 돌아야 할 시간대에 작동하지 않았다.

조용한 결함이다. 예외도 나지 않고 로그는 오히려 `"%d분 후 재시도 가능"`이라고 말한다.

### 수정

저장 형식을 UTC로 바꾸면 이미 쌓인 3,498행 전부와 어긋난다. **비교 쪽을 로컬로 맞췄다.**

```
storage/database.py   _NOW_LOCAL = "datetime('now', 'localtime')"
                      claim_next_queue_item()  / reset_stale_queue() 3곳
```

`api/` 계층은 이 문제가 없다 — 전부 파이썬 쪽에서 비교하고 SQLite `now`를 쓰지 않는다
(전수 확인). 결함은 `storage/database.py` 4곳에 한정돼 있었다.

### 이 수정이 바꾸는 것 — 정직하게 적는다

시각 비교가 제 값으로 돌아오면서 **두 가지가 실제로 달라진다.**

1. **재시도가 설계대로 30분 간격이 된다.** 기존 3,498행은 `last_attempt_at`이 로컬
   시각이므로 데이터 이관이 필요 없다. 다음 실행부터 더 많은 행이 자기 차례에 잡힌다.
2. **in_progress 회수가 9시간 10분 -> 10분으로 돌아온다.** 이것이 원래 의도한 값이다
   (`reset_stale_queue()`의 주석과 상수 그대로). 다만 **부작용을 알고 있어야 한다**:
   문서 하나를 10분 넘게 붙들고 있는 Worker가 있는데 **두 번째 Worker가 기동하면**
   첫 번째의 작업을 회수해 간다(중복 수집). 지금은 Task Scheduler가 02:00에 하나만
   띄우고 04:00에 끝나므로 겹칠 일이 없다 — **수동으로 두 개를 동시에 띄우지 말 것.**
   고치기 전에는 회수가 사실상 일어나지 않아 이 위험이 없는 대신, 죽은 Worker의 행도
   영원히 회수되지 않았다. 둘 중 의도된 쪽을 택했다.

### 새 검사 — 결과가 아니라 **형태**로 막는다

`test_pipeline_integrity.py` §9. 운영 코드가 `datetime('now')` / `date('now')`를 쓰면서
`localtime`을 빠뜨린 자리를 소스에서 찾는다. DB가 없어도(fresh clone) 돌아간다.

검사를 만드는 과정에서 **검사 자체의 함정 두 개**를 만났고, 둘 다 실제로 겪은 뒤 고쳤다.

1. 소스를 그냥 훑으니 **이 결함을 설명하는 주석**을 결함으로 잡았다.
2. 그래서 AST로 문자열 상수만 골라 봤더니 이번엔 **문자열을 이어 붙여 만든 SQL을
   놓쳤다** — 그런데 원래 결함이 있던 자리가 정확히 그 형태였다(변이 M6가 조용히 통과).

최종 형태는 **주석과 독스트링만 지우고 원문 그대로** 훑는 것이다.

---

## #101-3 `document-stats`의 `total_failures`는 2026-07-15에 멈춰 있다 (결정 대기)

**심각도** 낮음 (운영 지표. 프런트는 이 엔드포인트를 쓰지 않는다 — `src/` 전수 검색 0건)

`GET /api/v1/document-stats`는 값 7개를 돌려주는데 **출처가 두 곳으로 갈라져 있다.**

```
spec_failed / status_failed / appraisal_failed   document_status   (살아있는 경로)
total_failures                                   document_collect_failures
```

그런데 `document_collect_failures`에 INSERT 하는 코드는 `collect_documents.py` 하나뿐이고,
**그 스크립트는 어떤 스케줄러도 실행하지 않는다**(`run_daily.bat` / `run_doc_worker.bat` /
`run_priority_refresh.bat`는 `mvp_scraper` / `migrate_execute` / `doc_worker` /
`refresh_priority` 넷만 부른다 — 실측). 살아있는 수집기 `doc_worker.py`는 실패를
`document_queue.status='failed'`와 `document_status='FAILED'`에만 남긴다.

```
document_collect_failures 최신 행   2026-07-15T22:59:53   (3행, 그 뒤로 멈춤)
document_status 최신 갱신           2026-08-12T14:46:06
```

지금 두 값이 **우연히 똑같이 3이라 어긋남이 보이지 않는다.** doc_worker가 실패를 하나
더 기록하는 순간 `spec/status/appraisal_failed`만 늘고 `total_failures`는 3에 머문다.

### 왜 고치지 않았나 — 추측하지 않기로 했다

`total_failures`를 무엇으로 정의할지가 갈린다.

| | 뜻 | 근거 |
|---|---|---|
| A | 누적 **실패 사건** 로그 | 테이블 이름과 append-only 구조. `test_api_regression.py:155`가 이 계약을 명시적으로 고정하고 있다 |
| B | 현재 **FAILED 상태** 개수 | 이름이 `total_failures`고 나머지 6개 값과 같은 출처가 된다 |

A로 가려면 `doc_worker`가 이 테이블에도 INSERT 해야 하고(item_id 해석 필요 — 큐에는
있는데 `auction_item`이 없는 행 18개가 실재한다), B로 가려면 기존 테스트가 고정한
계약을 바꿔야 한다. **어느 쪽도 코드만 보고 정할 수 없다.** 사용자 영향이 없으므로
(프런트 미사용) 사실만 남기고 결정을 기다린다.

---

## #101-4 법원 식별자 규약에 가드를 세웠다 (지금은 정상 — 조용히 깨질 수 있는 자리)

`doc_worker`가 문서를 받으려면 큐의 `court_code`로 법원을 찾아야 한다.

```python
# crawler/base_crawler.py:go_to_case_detail()
court = next((c for c in ALL_COURTS if c.code == court_code), None)
if not court:
    logger.error("법원 코드 매칭 실패: %s", court_code)
    return False        # <- 그 법원의 문서는 하나도 수집되지 않는다
```

**예외가 아니라 로그 한 줄**이다. 규약이 어긋나면 조용히 멈춘다.

이 저장소의 규약은 "법원 식별자 = 한글 법원명"이다. 실측으로 확인했다.

```
config/courts.py ALL_COURTS   60개, code == name 인 항목 60개
DB 6개 컬럼(document_queue.court_code / auction_item.court_name /
            auction.court_code · court_name / auction_case.court_code · court_name)
                              값 60종, ALL_COURTS 에 없는 값 0
```

**지금은 완전히 일치한다.** 문제는 `config/settings.py:COURTS`에 **다른 규약**의 목록이
남아 있다는 것이다 — `code="B000210"` 같은 WebSquare 코드 5개, `code == name`인 항목 **0개**.

```
git grep '\bCOURTS\b' -- '*.py'   ->  정의된 한 줄뿐. import 하는 코드 0곳.
```

지금은 아무도 쓰지 않아 무해하지만, 누가 그쪽 규약이 옳다고 보고 "정리"하면
**60개 법원의 문서 수집이 전부 조용히 멈춘다.** 죽은 코드를 지우는 것은 승인 영역이라
건드리지 않고, 대신 `test_pipeline_integrity.py` §10으로 **코드와 데이터를 대조해** 규약을
못 박았다. 변이 검증: `ALL_COURTS[0]`을 `B000210`으로 바꾸면 검출(M9), 법원 하나를
목록에서 지워도 검출(M10).

> 부수 확인: 큐는 있는데 `done`이 0인 법원이 5곳(밀양·장흥·남원·공주·영동) 있어 법원별
> 실패를 의심했지만, **전부 매각기일이 지난 pending**이었다(미래 기일 0건). 전체가
> 559/3,498만 done인 것과 같은 배경이고 법원 고유의 문제가 아니다.

---

## 픽스처가 결함에 기대고 있었다 (테스트 3곳)

`_NOW_LOCAL` 수정 후 기존 검사 8건이 실패했다. **단언은 전부 옳았고 픽스처가 틀렸다.**

```
test_document_queue.py  §6 §7   datetime('now', '-1 minutes')  <- UTC 기준
```

"1분 전"이라고 적어 둔 행이 실제로는 "9시간 1분 전"이었다. 그래서 `live_in_progress`
("살아있는 Worker의 행은 건드리면 안 된다")가 회수 대상이 되어 버렸다.
**단언을 약화하지 않고 픽스처에 `localtime`을 넣어** 의도한 상황을 실제로 만들게 고쳤다.

이것이 이번 결함이 오래 숨어 있던 방식이기도 하다 — 검사와 운영 코드가 **같은 잘못된
전제**를 공유하면 검사는 영원히 통과한다.

---

## 변이 검증 (방어를 일부러 깨뜨려 검사가 실패하는지 확인)

| | 변이 | 검출 |
|---|---|---|
| M1 | doc_worker가 다시 `mark_queue_failed`를 부른다 | O |
| M2 | `SKIPPED_UNSUPPORTED` 대신 `failed`로 기록 | O |
| M3 | claim의 시각 비교를 UTC로 되돌림 | O |
| M4 | in_progress 회수 비교를 UTC로 되돌림 | O |
| M5 | 미지원 항목의 화면 상태를 쓰지 않음 | O |
| M6 | claim에서 `localtime`만 제거 | O (§9 스캐너 수정 후) |
| M7 | `-1 day` 비교에서 `localtime` 제거 | O |
| M8 | 새 파일이 `date('now')` 사용 | O |
| M9 | `ALL_COURTS`를 WebSquare 코드 규약으로 변경 | O |
| M10 | `ALL_COURTS`에서 법원 하나 삭제 | O |

M1은 §16의 재현이 **호출부를 흉내낸 것**이라 그것만으로는 잡히지 않았다.
`doc_worker.py`의 해당 분기를 소스로 고정하는 검사를 함께 넣어 막았다.

---

## 데이터 감사 결과 (결함 아님 — 측정값만 남긴다)

실 DB + 실제 파일 722개 교차 대조. **"DB는 성공인데 실물이 없다"는 0건이었다.**

| 항목 | 결과 |
|---|---|
| 성공상태(READY) + 파일 정상 | 556 |
| 성공상태 + 파일 없음 | **0** |
| 성공상태 + 0바이트 | **0** |
| 0바이트 파일 전수 | **0** |
| 실패/대기 상태인데 파일 존재 | **0** |
| 고아 검사 8종(document_status/favorites/recent_items/rights_summary/…) | **전부 0** |
| `document_status` (item_id, doc_type) 중복 | 0 |
| queue `done` ↔ `document_status` READY 불일치 | 0 |

남은 것 두 가지는 **전부 만료된 과거 데이터**라 사용자 영향이 없다. 기록만 남긴다.

```
큐 행이 없는 물건 716건        전부 Migration 018 이전에 만들어진 것(created_at <= 2026-08-01).
                              그중 520건이 item_no != '1' — 018이 고친 바로 그 결함의 잔여물.
                              매각기일이 미래인 것은 **0건**이라 화면 영향이 없다.
고아 파일 3개 / 고아 큐 18행   (고양지원 2024타경2803) 대응 auction_item이 없다.
                              전부 만료. 정리는 운영 데이터 삭제라 SKIP.
```

### 베타 사용자 여정 실측 (기본 검색에 뜨는 9개 물건을 끝까지 따라갔다)

`GET /api/v1/search` → `GET /item/{id}` → `document_status` → 실제 파일 → 문서 서빙 HTTP.
9개 물건 × 문서 3종 = **27경로 전부 일치, 모순 0건.**

```
READY   -> 파일 있음(수십 KB~3.4MB) -> HTTP 200
COLLECTING -> 파일 없음            -> HTTP 404
```

"READY인데 파일 없음"도, "미완료인데 200"도 없었다. 화면이 말하는 것과 실제가 같다.

> 감사 도중 **case_no 단독 조인이 법원 간 동명 사건을 가린다**는 것을 확인했다
> (2개 이상 법원에 같은 case_no가 존재하는 사건 3건). 정합성 조회는 반드시
> `(court, case_no, item_no)` 3자로 해야 한다 — 앞으로 이 감사를 다시 할 때의 전제다.

---

## 결함이 아니었던 것 — 확인하고 넘어간 영역

보고서를 믿지 않고 직접 확인한 결과 **정상이었던** 것들이다. 결과가 음성이어도 측정은
남긴다(다음에 같은 곳을 다시 파지 않기 위해서다).

### 인가 / IDOR — 유출 0건

OpenAPI로 41개 라우트를 전수 열거해 익명·타인·관리자 키로 **실제 호출**했다.

```
익명으로 2xx인 라우트    6개  (/, /stats, /document-stats, /search, /item/{id}, /plans) — 전부 의도된 공개
사용자 라우트            전부 401
관리자 라우트            전부 403 (키 없이)
500이 난 라우트          0개
```

A가 만든 자원을 B가 건드릴 수 있는지도 자원별로 실제 시도했다 — **검색조건 / 즐겨찾기 /
최근조회 / 등기부 신청 / 등기부 문서 다운로드 / 결제 / 결제로그 / 구독, 유출 0건.**
위조 서명·빈 키·형식 파손 토큰도 전부 401.

> `test_api_regression.py` §33이 이미 같은 전수 검사를 하고 있었다. 이번 감사는 그것이
> **실제로 작동함을 독립적으로 확인**한 것이다. 같은 검사를 하나 더 만들지는 않았다 —
> 중복 검사는 유지 비용만 늘린다.

### `bid_rate` 백분율/비율 혼선 — 없음

DB는 비율(0.0023~1.0)로 저장한다. `min_bid_rate=50`을 넣으면 0건이 나와 처음엔 결함으로
보였다. 확인해 보니 **호출 규약이 비율**이고(`search/00_SEARCH_MVP.md:215` "%÷100"),
프런트가 `SearchForm.tsx:359`에서 100으로 나눠 보내며, 표시할 때 `ResultList.tsx:8`이
다시 100을 곱한다. **양끝이 일치한다.** 내가 규약을 어긴 호출을 했던 것이다.

### 검색 파라미터가 조용히 무시되는 것 — 없음

`GET /search`가 선언한 파라미터 19개를 SQL 조건과 1:1로 대조했다. **전부 실제 조건절로
연결된다.** (`SearchForm.tsx`의 `TODO(API 미지원)` 3건은 애초에 전송하지 않는다 —
보내 놓고 무시하는 것과 다르다.)

### `auction` → `auction_item` 동기화 — 불일치 0건

크롤러가 쓰는 레거시 `auction`과 API가 읽는 `auction_item`이 갈라지면 **"크롤은 됐는데
화면은 옛 값"**이 된다. 1,876행 × 12개 필드를 전수 대조했다.

```
키(법원,사건,물건) 대조   auction 에만 0행 / auction_item 에만 0행
값 대조                  1,876행 × 12필드 → 불일치 0건
```

`property_type / sido / sigungu / dong / lot_number / full_address / appraisal_price /
minimum_bid_price / auction_date / status / validation_status / crawl_date` 전부 같다.
`migrate_execute.py`의 단방향 동기화는 충실하게 동작하고 있다.

> `updated_at`이 auction 쪽이 더 최신인 행이 1건 있었지만(2025타경939 물건2,
> 14:41 vs 14:39) **값은 완전히 동일**하다. 같은 배치 안에서 migrate가 먼저 돈 순서
> 효과일 뿐 내용 지연이 아니다.

### 레거시 `has_*` 플래그 드리프트 35건 — 이미 알려진 것과 같음

`has_status_doc=1`인데 화면은 미READY인 행 33 + spec/appraisal 각 1 = **35건**.
`docs/roadmap.md`(BUGS #83)가 기록한 수치와 일치한다. **이 플래그는 `api/`가 읽지
않으며 그것을 강제하는 가드가 이미 있다** — 화면에 영향이 없다. 새 사실 없음.

### 크롤러 목록 파싱을 픽스처로 검증할 수 있는가 — 없다 (문서가 맞았다)

> **★ 2026-08-14 Sprint 103에서 이 항목을 정정한다. 아래 결론은 범위를 잘못 잡았다.**
>
> "저장된 HTML 덤프가 목록 페이지가 아니다"는 사실은 맞다(재확인). 그러나 그것으로
> **"크롤러 파싱은 검증할 수 없다"고 넓힌 것이 틀렸다.** 실제 HTML 없이도
> **가짜 드라이버**로 조립 로직을 검증할 수 있고, 이 저장소는 이미 그렇게 하고 있었다 —
> `test_crawler_parsing.py`(Sprint 85 신설)가 `parse_basic_info` / `parse_section_table` /
> `parse_gamjung` / `clean`을 그 방식으로 검사한다. 나는 그 파일을 확인하지 않고
> `roadmap.md`의 오래된 서술만 확인한 뒤 "문서가 맞았다"고 결론지었다.
>
> 남아 있던 진짜 공백은 **`collect_list_items()` 하나**였고, Sprint 103에서 같은 방식으로
> 채웠다(변이 6종 전부 검출). 자세한 내용은 `docs/SPRINT103_NORMALIZER_DRIFT.md` 참고.

`docs/roadmap.md`는 "HTML 픽스처가 저장소에 없어 SKIP"이라고 적고 있다. 저장소에 있는
`page_dump.html` / `debug_page.html`을 실제로 열어 확인했다 — **`타경`도 `moveDtlPage`도
0건**이라 목록 페이지가 아니다.

**여기까지가 확인된 사실이고**, "따라서 검증 불가"라는 추론이 틀렸다.
XPath가 실제 법원 DOM과 맞는지는 여전히 검증할 수 없다(실크롤 필요). 그러나
**DOM에서 값을 꺼낸 뒤의 조립 규칙은 검증할 수 있다.** 두 가지는 다른 문제였다.

---

## 실 DB 복사본으로 "다음 실행"을 재생했다

단위 검사만으로는 **실제 데이터에서 어떻게 갈리는지** 알 수 없다. `auction.db`를 임시
디렉터리로 복사하고 `DB_PATH`를 그쪽으로 돌린 뒤, doc_worker의 결정 경로 세 갈래
(claim → 기일 방어선 → 버튼 id 방어선)만 브라우저 없이 재생했다. **원본은 건드리지 않았다.**

```
실행 전   queue = {pending 2753, done 559, SKIPPED_EXPIRED 186}

다음 실행에서 일어나는 일
  기일 경과로 즉시 종료(SKIPPED_EXPIRED)   2,733
  버튼 id 없어 종료(SKIPPED_UNSUPPORTED)       2      <- #101-1 이 잡는 바로 그 2건
  실제로 브라우저를 여는 항목                  18

실행 후   queue = {SKIPPED_EXPIRED 2919, SKIPPED_UNSUPPORTED 2, done 559, (시뮬 18)}
          document_status  FAILED 3 -> 5   (늘어난 2건이 그 미지원 문서다)

하루 뒤 두 번째 실행 (reset_stale_queue 포함)
  SKIPPED_UNSUPPORTED 2  ->  2      ★ 되살아나지 않는다
```

검증 항목도 함께 확인했다.

```
버튼 id가 있는데 UNSUPPORTED 로 끝난 행     0
UNSUPPORTED 행의 retry_count 최대           0   (실패가 아니므로 소모하지 않는다)
UNSUPPORTED 에 대응하는 document_status     전부 FAILED
```

**고치기 전이라면 저 2건이 4일 주기로 영원히 되살아났을 자리다.** 실제 데이터에서 고리가
끊긴 것을 확인했다.

> 부수 확인: 기일이 빈 문자열인 행 1건(상주지원, 사건번호 5개짜리)은 기일 방어선을
> 통과해 수집 대상이 된다. `if auction_date and auction_date < today`라 **날짜를 모를 때는
> 건너뛰지 않는다** — 모르는 것을 만료로 단정하지 않는 쪽이 안전하므로 의도된 방향이다.

> 이 시뮬레이션도 처음엔 **내 하네스가 틀렸다.** 클레임한 행을 `pending`으로 되돌려 놓아
> 같은 행을 5,000번 다시 집었다(가드에 걸려 멈춤). 제품이 아니라 재생 코드의 문제였고,
> 되돌리지 않도록 고쳐 다시 돌렸다.

---

## 검증

| 항목 | 결과 |
|---|---|
| 파이썬 테스트 | **31/31 파일 통과** (서버 2개 기동 상태에서 재확인) |
| 프런트 테스트 | **107/107 통과** (tests 107 / pass 107 / fail 0 / cancelled 0 / skipped 0) |
| `test_beta_journey.py` 프런트 게이트 | SKIP이 아니라 **실제 PASS** (307 확인) |
| TypeCheck (`npx tsc --noEmit`) | **exit 0** |
| Lint (`npm run lint`) | **exit 0** |
| Build (`npm run build`) | **exit 0** (파이프 없이 재측정) |
| 서버 정리 | 3000 / 8000 모두 해제 확인 |

---

## 이번 Sprint에서 **내가 만든** 사고와 교훈

정직하게 남긴다. Sprint 100이 같은 자리에서 넘어졌고, 이번에도 넘어졌다.

### 1. 변이 검증 도구가 BOM을 지웠다

변이 스크립트가 `utf-8-sig`로 읽고 `utf-8`로 되썼다. 그래서 `api/v1/favorites.py`의
**BOM이 조용히 사라졌다.** 손댈 생각조차 없던 파일이다.

`test_schema_hygiene.py` §8("작업 중 BOM이 조용히 바뀐 파일 없음")이 **정확히 이것을
잡아냈다.** HEAD에서 복구했다. 검사가 제 일을 했다.

교훈: **소스를 되쓰는 도구는 바이트 그대로 다뤄야 한다**(`rb`/`wb`). 인코딩을 해석하는
순간 원본을 바꾼다.

이후 변이 도구를 `rb`/`wb`로 고쳐 다시 돌렸고, 복구 후 `git status config/courts.py`가
**빈 문자열**(바이트까지 동일)임을 확인했다.

### 2. 서버 정리 — 이번엔 파이썬 쪽이었다

Sprint 100은 `npm run start`의 자식 node가 살아남는 것을 기록했다. 이번엔 **파이썬
서버가 같은 일을 했다.** `api_server.py:104`가 `uvicorn.run(..., reload=True)`라
multiprocessing 자식을 띄우고, **그 자식이 소켓을 쥔다.**

```
Stop-Process <부모 PID>   -> 포트 여전히 LISTENING, curl 200
taskkill /T /F <부모>     -> "프로세스를 찾을 수 없습니다" (부모는 이미 죽음)
실제 소켓 보유자          -> multiprocessing-fork 자식
```

교훈: 포트로 찾은 PID가 죽었는데 포트가 살아 있으면 **자식을 찾아야 한다**
(`Win32_Process`의 `ParentProcessId`). 종료 확인은 "프로세스를 죽였다"가 아니라
**"포트가 풀렸다"**로 해야 한다.

---

## SKIP 및 이유

| 항목 | 이유 |
|---|---|
| 고아 파일 3개 / 고아 큐 18행 정리 | 운영 데이터 삭제 — 승인 영역 |
| 큐 없는 716건 재적재 | 전부 만료. 재수집 정책은 결정 대기 |
| 현황조사서 item_no != 1 버튼 id 확보 | 실제 courtauction.go.kr DOM 분석 필요 |
| `api_server.py`의 `reload=True` | 개발 편의. 운영 기동 방식은 배포 정책 |
| 중복 인덱스 4쌍 (Sprint 100) | 변동 없음 — 병목 없음 |

## 남은 Backlog

**이번에 새로 올라온 것**

- `document-stats`의 `total_failures` 정의 결정 (#101-3 — A/B 선택 후 구현)
- 현황조사서 item_no != 1 의 버튼 id 확보 (실제 DOM 분석 필요). 확보되면
  `SKIPPED_UNSUPPORTED` 109행을 pending 으로 되돌리는 운영 스크립트가 함께 필요하다
- 고아 파일 3개 / 고아 큐 18행 정리 (운영 데이터 삭제 — 승인 영역)

**Sprint 100에서 이월 (변동 없음)**

- 커밋된 DB 백업 9개(36.9MB) 인덱스에서 제거 — commit 필요
- 부트스트랩 3단계를 README/docs에 반영
- `mypage` 등기부 다운로드 버튼 — UX 결정
- 스키마 생성 경로 일원화(`init_db` + `migrate_v4_1`) — 운영 절차 변경
- 구독 결제 환불 시 구독 처리(A/B/C/D) — 제품 결정 (열쇠인 `payment_id`는 Migration 019로 이미 있다)
