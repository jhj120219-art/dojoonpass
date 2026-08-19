# Sprint 189 — 변경 기반 재수집 (Change-driven Refresh)

2026-08-18. 기준 커밋 `73ac6eb` (master = origin/master, working tree clean).

---

## 한 줄 요약

이 저장소는 **재수집 기계를 다 만들어 놓고 한 번도 돌린 적이 없었다.**
Sprint 189가 그 마지막 한 칸 — **트리거** — 를 채웠다. 그리고 트리거를 켜자마자
도달하게 되는 결함 3건을 함께 막았다.

---

## 1. 왜 지금 이것인가

목표는 "한 번 수집하면 보인다"가 아니라 **"법원이 바꾸면 다음 주기에 따라 간다"**이다.
그 사슬을 실제 코드로 끝까지 따라간 결과, 끊어져 있는 곳은 정확히 한 군데였다.

```
법원 원천 변경
  -> mvp_scraper -> upsert_batch()          ... 동작함 (auction 갱신)
  -> migrate_execute()                       ... 동작함 (auction_item 갱신 + 필드 단위 변경 관측)
  -> ??? 재수집 판단                          ... ★ 없었다
  -> collect_document(overwrite=True)        ... 코드는 완성돼 있으나 **아무도 True를 넘기지 않음**
  -> previous_hash != new_hash               ... 동작함
  -> document_version_log                    ... 동작함 (그래서 0행이었다)
  -> auction_image / doc_raw                 ... 동작함
  -> API -> 상세페이지                        ... 동작함
```

`document_queue`는 한 번 `done`이 되면 **영원히 `done`**이었다. 그래서 법원이 명세서를
다시 올려도 화면은 최초 수집분을 계속 보여 줬다. Sprint 185가 "무엇이 바뀌었는지"를
**세기만** 하고 끝난 것도 같은 이유다 — 관측은 있는데 행동이 없었다.

---

## 2. 무엇을 만들었나

### 2-1. 스키마를 바꾸지 않고 어휘를 늘린다

DB 스키마 변경은 승인 영역이다(`docs/CLAUDE.md`). 그래서 새 컬럼 대신
`document_queue.status`의 **값을 늘렸다**(TEXT + CHECK 제약 없음 -> 값 추가는 DDL이 아니다).

```
pending              한 번도 수집한 적 없다        -> overwrite=False
refresh              이미 있지만 다시 받아야 한다  -> overwrite=True
in_progress          pending 을 집어간 상태
in_progress_refresh  refresh 를 집어간 상태
```

**진행 상태를 두 갈래로 나눈 것이 핵심**이다. 재시도(`mark_queue_failed`)와 stale 회수
(`reset_stale_queue`)가 원래 어느 쪽이었는지 알아야 제자리로 돌려놓을 수 있다.
하나로 합치면 **재수집 의도가 첫 실패에서 조용히 사라진다** — 그다음 시도는
`overwrite=False`라 "이미 존재. 스킵"으로 성공 처리되고, 바뀐 문서는 영원히 옛것으로
남는다. 회귀 §5가 이 자리를 고정한다.

### 2-2. 무엇이 바뀌면 무엇을 다시 받는가

`storage/database.py:REFRESH_DOC_TYPES_BY_FIELD` 하나가 유일한 정의처다.

| 바뀐 필드 | 다시 받는 자산 | 근거 |
|---|---|---|
| `auction_date` | spec, status | 법원은 **기일마다 매각물건명세서를 다시 올린다** |
| `minimum_bid_price` | spec | 저감된 최저가가 명세서에 적혀 있다 |
| `status` | spec, status | 유찰/변경/취하/정지가 두 문서에 반영된다 |
| `appraisal_price` | appraisal, **image** | 감정가 변동 = 재감정 = 감정평가서 + 현장 재촬영 |

**사진을 기일/최저가에 넣지 않는다.** 사진은 감정 시점에 찍힌 것이라 유찰로 값만
내려갈 때는 바뀌지 않는다. 넣으면 매일 수천 장을 이유 없이 다시 받는다.
회귀가 이 결정을 명시적으로 고정한다.

### 2-3. 되돌릴 것과 건드리지 않을 것

```
done                  -> refresh   ★ 단, 매각기일이 아직 지나지 않은 물건만
SKIPPED_EXPIRED       -> pending   ★ 단, 기일이 미래로 다시 잡혔을 때만
pending / refresh     그대로       이미 대기 중
in_progress(_refresh) 그대로       워커가 소유 중 (뺏으면 그 실행이 done 으로 덮는다)
failed                그대로       자기 재시도 경로가 따로 있다
SKIPPED_UNSUPPORTED   그대로       성공할 수 없는 항목의 영구 종결 (무한 재시도 고리 재개 금지)
```

`SKIPPED_EXPIRED`만 `refresh`가 아니라 `pending`인 이유: **한 번도 받아 본 적이 없다.**
overwrite로 갈 이유가 없고, 그렇게 두면 형제 물건 복사 같은 값싼 경로를 잃는다.

"기일이 지난 물건은 되돌리지 않는다"는 조건은 **실제 DB 사본으로 돌려 보다가** 추가했다.
되돌리면 워커가 집어가서 2차 방어선(`auction_date < today`)에 걸려 곧바로
`SKIPPED_EXPIRED`로 종결한다 — **아무것도 다시 받지 못한 채 성공 기록(done)만 잃는다.**

### 2-4. 상한은 조용하지 않다

`REFRESH_MAX_ITEMS_PER_RUN = 300`. 법원이 하루에 수천 건을 갱신한 날
(실측: 2026-08-01 하루 278건) 재수집이 워커의 실행 창(02:00~04:00)을 통째로 차지하면
**한 번도 수집된 적 없는 물건이 밀린다.** 아직 아무것도 못 본 사용자가 먼저다.
초과분은 큐에 그대로 남아 다음 실행의 후보가 되고, **잘린 건수는 반드시 로그와
반환값에 남는다**(조용한 절단 금지).

### 2-5. 정렬은 바꾸지 않았다

재수집을 앞세우고 싶어지지만, `priority`는 매각기일 임박도에서 계산된 값이라
이미 제품이 정한 중요도다. 재수집을 앞세우면 **한 번도 수집된 적 없는 임박 물건**이
뒤로 밀린다. 총량은 위 상한으로 따로 제한한다.

### 2-6. 끌 수 있다

`DOJOONPASS_REFRESH_ON_CHANGE=0` 이면 관측만 하고 예약하지 않는다.
기본은 **켬**이다 — 이 기능이 없는 상태가 곧 제품 결함이기 때문이다.
사고 시 코드 수정 없이 배치 한 줄로 되돌릴 수 있어야 해서 환경변수로 뒀다.

---

## 3. 트리거를 켜자 드러난 결함 3건

| # | 결함 | 성격 |
|---|---|---|
| #120 | 사진 형식이 바뀌면 옛 파일이 고아로 남고 **지문 공식이 갈라진다** | 기존 결함, 재수집이 도달시킨다 |
| #121 | 기존 PDF를 덮어쓸 때만 저장이 **비원자적**이 된다 | 기존 결함, 재수집이 도달시킨다 |
| #122 | 재수집 최종 실패가 **이미 보여 주던 문서를 "수집실패"로 뒤집는다** | 이번 Sprint가 도입할 뻔한 것 |

세 건 모두 `docs/BUGS.md`에 재현 절차·실측값과 함께 기록했다.

#120의 파급이 가장 크다 — Sprint 186이 `_existing_set_hash()` docstring에 적어 둔 경고
("공식이 갈라지면 매 수집이 거짓 개정이 되어 진짜 개정을 찾을 수 없다")가 **형식 변경
한 번으로 영구히 현실이 된다.**

#121은 "같은 계약, 한쪽만 실제로 구현" 계열(#113/#115)의 네 번째다 —
`collect_documents.py`와 `image_crawler.py`는 이미 `os.replace()`를 쓰고 있었고
**두 수집기만 빠져 있었다.** 그래서 인스턴스만 고치지 않고 `crawler/`·`storage/`·
`collect_documents.py` 전체를 **AST로 훑는 전수 가드**를 함께 넣었다.

---

## 4. 실측 — 실제 `auction.db` 사본으로 끝까지

운영 DB는 읽기만 했다(`shutil.copy2` 후 사본에만 쓰기).

```
대상 물건: 서울중앙지방법원 / 2024타경126346-1  (기일 2026-08-19, 유찰 4회)
법원 원천: 최저가 134,144,000 -> 146,489,678 / 기일 2026-08-19 -> 2026-09-30
           (유찰 -> 재매각. 한국 경매의 일상적 변경)

migrate_execute 결과      True
관측된 필드 변경          {'auction_date': 1, 'minimum_bid_price': 1}
재수집 예약 결과          {'items': 1, 'refreshed': 1, 'revived_expired': 0, 'skipped_over_cap': 0}

변경 후 auction_item 최저가   146,489,678   (기대값과 일치)
변경 전 큐   [('appraisal','pending'), ('spec','pending'), ('status','done')]
변경 후 큐   [('appraisal','pending'), ('spec','pending'), ('status','refresh')]
전체 큐 분포  SKIPPED_EXPIRED 186 / done 558 / pending 2,753 / refresh 1
```

**바뀐 그 물건의, 실제로 수집이 끝나 있던 그 문서 한 줄만** 되돌아갔다.
나머지 3,497행은 그대로다.

### 상세페이지까지 (API 서버 + Next dev 서버 실제 기동)

```
GET /api/v1/search?limit=3                 200   total 9
GET /api/v1/item/505                       200   images 5장 READY / SPEC·STATUS·APPRAISAL READY
GET /api/v1/item/505/images/1              200   image/jpeg 235,194B
GET /api/v1/item/505/images/9              404   (없는 것은 정직하게 404)
GET /api/v1/item/505/documents/APPRAISAL   200   application/pdf 3,416,671B
If-None-Match: <etag>                      304
Cache-Control                              (없음 -> 브라우저가 항상 재검증)

http://localhost:3000/search               200   실데이터 렌더 확인(이미지 URL 18개, 기일 2026-08-19)
http://localhost:3000/properties/505       307 -> /login  (로그인 필요, 설계대로)
```

**캐시가 최신화를 막지 않는다**는 것을 실측으로 확인했다. `src/lib/api.ts`는 전 경로
`cache: 'no-store'`이고, 파일 서빙은 `Cache-Control`을 두지 않아 브라우저가 항상
재검증한다. 파일이 바뀌면 ETag가 바뀌어 옛 검증자는 200을 받는다
(`test_http_conditional.py`가 이미 고정하고 있다).

---

## 5. 이미지 6가지 상황 — 전부 검사가 있다

| | 상황 | 동작 | 고정하는 검사 |
|---|---|---|---|
| A | 이미지가 동일 | `overwrite=False`면 재다운로드 없음. `True`여도 지문이 같아 **거짓 개정이 안 생긴다** | 5-C |
| B | 기존 이미지가 변경 | 새 바이트 저장 + 지문이 달라져 개정 기록 | 5-C |
| B' | **형식까지 변경** | 옛 확장자 파일 정리, 두 공식 일치 유지 | **5-D (신규)** |
| C | 이미지가 추가 | 새 순번이 그대로 붙고 **지울 것이 없다** | **7-B (5) (신규)** |
| D | 법원이 실제로 삭제 | `complete=True`일 때만 옛 행 정리 | 7-B (3) |
| E | 일부 다운로드 실패 | `complete=False` -> **지우지 않는다** | 7-B (2) |
| F | 전체 실패 | 저장 0장 -> 삭제도 0 | 7-B (4) |

C는 가장 흔한 변경인데 **어느 검사도 이름을 붙여 두지 않았다** — 이번에 명시했다.

---

## 6. 테스트

```
신규   test_refresh_trigger.py        12개 절 / 74검사
증분   test_asset_pipeline.py         5-D(8) 5-E(2) 7-B(5)(3)  = +13검사
       test_doc_storage_atomicity.py  7d(6) 7e(2)              = +8검사
수정   test_doc_worker_recovery.py    대역이 실물보다 좁아 TypeError -> 키워드 수용으로 정정
       test_schema_hygiene.py         `?` 반복 상수 1건 허용목록 추가(값은 전부 바인딩)

전체   40 PASSED / 0 FAILED / 3 SKIPPED / 1 NO-VERDICT   (단언 4,649 -> 5,038, +389)
프런트 113/113 PASS, tsc 0, eslint 0
```

SKIP 3개(`test_db.py`/`test_docs.py`/`test_docs2.py`)는 `ALLOW_LIVE_CRAWL=1` 없이는
스스로 건너뛰는 실크롤 스크립트다. NO-VERDICT 1개(`test_filter.py`)는 판정문이 없는
진단 스크립트다 — 둘 다 **통과가 아니다**(`run_python_tests.py`가 일부러 분리해 센다).

### 가드가 헛돌지 않는지 확인했다

`test_doc_storage_atomicity.py` 7e(비원자적 이동 전수 검색)에 변이를 주입해
(`move_into_place` -> `shutil.move`로 되돌림) **즉시 FAIL하는 것을 확인**한 뒤 복원했다.
"항상 통과하는 검사"와 "결함이 없어서 통과하는 검사"를 구분하기 위해서다.

---

## 7. 승인 필요로 SKIP한 것

### SKIP-1. 예약 작업 등록 (Release Blocker, BUGS #123)

**이 저장소를 가리키는 예약 작업이 0개다.** 전체 249개 중 하나도 없다.

```
logs/daily_run.log 마지막 기록      2026-08-11 17:05
auction.crawl_date 최신             2026-08-12 (9건) — 이후 6일간 0건
기일이 남은 물건                    1,876건 중 9건 (전부 2026-08-19까지)
```

즉 **2026-08-20부터 검색 결과가 0건이 된다.**

준비된 것: `register_scheduler_tasks.ps1`(dry-run으로 선행 조건 확인 완료 —
배치 3개 OK, PATH python OK, 머신 PATH로는 불가 -> SYSTEM 계정 등록 금지를
스크립트가 이미 지킨다). 승인 후 필요한 최소 작업은 한 줄이다:

```powershell
.\register_scheduler_tasks.ps1 -Apply
```

릴리스 영향: **이것 없이는 Sprint 189가 만든 것을 포함해 아무것도 자동으로 돌지 않는다.**

### SKIP-2. 운영 DB 대량 변경

없음. 이번 Sprint는 스키마를 바꾸지 않았고, 실측은 전부 스크래치 사본에서 했다.
실제 `auction.db`는 읽기만 했다.

---

## 8. 다음 백로그

1. **(승인 후 즉시)** 예약 작업 등록 -> 첫 실행 로그로 재수집이 실제로 도는지 확인.
   `document_version_log`에 첫 행이 남는 순간이 이 Sprint의 진짜 완료 시점이다.
2. `REFRESH_MAX_ITEMS_PER_RUN = 300`은 **아직 실측 근거가 없는 값**이다. 재수집이
   실제로 돌기 시작하면 물건당 소요를 재서 실행 창(02:00~04:00) 기준으로 다시 정한다.
3. `documents/` 빈 디렉터리 1,674개(기존 SKIP 항목) — 파일 삭제라 승인 영역.
4. `mark_queue_skipped_expired()`가 `document_status`를 COLLECTING에 남겨 두는 문제
   (Sprint 73부터 보류 중, 제품 판단). 재수집 어휘가 생긴 지금은 "대상 아님" 상태를
   추가하기 더 쉬워졌다.


---

## 9. 후반부 — "정확히 개정만 기록하고, 안 바뀐 것은 건드리지 않는가"

트리거가 붙은 뒤 그 다음 질문을 따라갔더니 **두 가지가 더 틀려 있었다.**
둘 다 재수집을 켜기 전에는 도달하지 않아 드러날 수 없었다.

### BUGS #124 — 지문이 우리 메타데이터에 오염돼 있었다

`status.json`에는 `extracted_at`(수집 시각)이 들어 있는데 지문을 **파일 전체**에서 떴다.
법원 자료가 그대로여도 두 지문이 항상 다르다 → `document_version_log`가 거짓 개정으로
가득 차고 `doc_raw.doc_version`이 매일 오른다(`api/v1/item.py`가 사용자에게 그대로 싣는다).

이 저장소는 원인을 **이미 알고 있었다** — Sprint 145의 형제 재사용 주석이
*"차이는 우리가 찍는 extracted_at 하나뿐"*이라고 실측해 적어 두었다. 그 관찰이
변경 감지 쪽으로 연결되지 않았을 뿐이다. **알고 있던 사실이 다른 문맥에서 결함이 된다.**

### BUGS #125 — 안 바뀐 것을 다시 쓰면 캐시가 통째로 죽는다

같은 바이트를 다시 써도 mtime이 바뀌고, ETag는 (mtime, size)다. 즉 재수집이
`api/http_cache.py`의 절감을 매번 되돌린다. 목표 문서의 상황 A가 정확히 이것이다.
세 저장 경로 전부 "바이트 지문이 같으면 쓰지 않는다"로 바꿨다.

### BUGS #126 — 테스트 정리가 스스로를 막고 있었다

`documents/`는 OneDrive 동기 대상이라 디렉터리에 R 속성이 붙는다. 그 방어
(`_force_rmtree`)는 Sprint 96에 이미 만들어져 있었는데 **두 호출 지점 중 하나만**
쓰고 있었다. 한 번 실패하면 잔해가 남아 **이후 모든 실행이 같은 자리에서 죽는다** —
작업 중 실제로 겪었고 6벌이 쌓여 있었다. 호출 지점을 하나로 합쳤다.

이 실패는 판정문에 `[FAIL]`이 **하나도 없이** 종료 코드만 1이 된다.
`run_python_tests.py`가 종료 코드를 1순위 근거로 쓰는 이유가 여기서 다시 증명됐다.

### 검사 설계에서 배운 것

```
"안 썼다"  -> mtime 으로 단언할 수 있다 (쓰지 않았으면 절대 안 바뀐다)
"썼다"     -> mtime 으로 단언할 수 **없다** — 두 쓰기가 파일시스템의 타임스탬프
              갱신 간격보다 가까우면 같은 값이 나온다. 내용으로 확인한다.
```

작성 중 실제로 이 플레이크를 겪었다. 방향에 따라 근거를 다르게 쓴다.

### 최종 테스트

```
전체   40 PASSED / 0 FAILED / 3 SKIPPED / 1 NO-VERDICT
단언   4,649 (Sprint 189 시작) -> 5,084 (+435)
연속   2회 동일, documents/ 잔해 0
프런트 113/113 PASS, tsc 0, eslint 0
```
