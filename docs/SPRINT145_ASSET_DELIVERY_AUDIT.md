# Sprint 145 — 사용자에게 실제로 도달하는가 (Asset 배달 검증)

Status: 코드 수정 1건 + 관측 1건 완료 / 운영 조치는 SKIP(승인)
Date: 2026-08-17
Scope: Sprint 144가 만든 파이프라인이 **최종 사용자 화면까지** 실제로 도달하는지

---

## 0. 한 줄 요약

Sprint 144는 파이프라인을 만들었고 실제로 잘 동작한다 — 사진 45장은 원천·파일·DB·API가
바이트 단위로 일치하고 상세 API는 7문 고정이다. **그런데 그 파이프라인이 채워 주는
대상이 지금 9건뿐이고, 3일 뒤 0건이 된다.** 이번 스프린트의 실제 성과는 기능 추가가
아니라 이것을 숫자로 드러낸 것과, 그 상태를 **영구화하는 결함 1건을 찾아 고친 것**이다.

---

## 1. ★★ 가장 중요한 사실 — 2026-08-20에 검색 결과가 0건이 된다

```
오늘                       2026-08-17
기본 검색에 뜨는 물건       9건        (auction_item 1,876건 중)
그 9건의 매각기일           전부 2026-08-19
2026-08-20 기준 남는 물건   0건
마지막 crawl_date          2026-08-12  (5일 경과)
logs/daily_run.log         5일 전
예약 작업 등록              0건  ← 실측: 전체 249개 중 이 저장소를 가리키는 것 0개
```

기본 검색은 `include_closed=False`(= `auction_date >= 오늘`)이므로, 수집이 멈추면
남은 물건이 만료되다가 어느 날 0이 된다. **그 날이 3일 뒤다.**

이것은 새 발견이 아니다 — Sprint 112가 2026-08-14에 정확히 예측했고
(`docs/SPRINT112_SCHEDULER_HANDOFF.md`), Sprint 136이 `★★ 수집 파이프라인 스케줄러
등록`을 백로그 최상단에 올려 두었다. **아직 실행되지 않았고 기한이 3일 남았다.**

### 등록 여부를 실제로 확인했다 (이번에 처음)

`Get-ScheduledTask` 249개를 **이름·경로·실행 파일·인자 전부로** 검색했다:

```
DojoonPass-* 로 검색           0건
Actions.Execute  ~ dojoonpass  0건
Actions.Arguments ~ dojoonpass 0건
```

로그가 5일째 없는 이유가 이것이다. **로그 부재만으로는 "배치가 실패했다"와 "배치가
아예 등록되지 않았다"를 구분할 수 없다** — 없는 것은 눈에 띄지 않는다.

### 조치 (SKIP — 사용자 환경 변경)

```powershell
cd C:\Users\jhj12\OneDrive\Desktop\dojoonpass
.\register_scheduler_tasks.ps1           # 계획 확인
.\register_scheduler_tasks.ps1 -Apply    # 등록
```

Sprint 112와 같은 이유로 내가 실행하지 않는다. 대신 **이 사실이 다음부터는 저절로
보이도록** 검사에 넣었다(§5).

---

## 2. 사용자 화면 기준 실제 도달률 (숫자를 다시 셌다)

문서에 적힌 "READY 556건"은 사실이지만 **사용자가 볼 수 있는 물건 기준이 아니다.**
556건의 대부분은 이미 기일이 지나 기본 검색에 뜨지 않는 물건의 문서다.

| 기준 | 사진 | 문서(3종 전부 READY) |
|---|---|---|
| 전체 1,876물건 | 9물건(0.5%) | 197물건(10.5%) |
| **기본 검색에 뜨는 9물건** | **9/9 (100%)** | **2/9 (22%)** |

기본 검색에 뜨는 9건의 실제 상태:

```
item   502  2024타경3528-1     사진5  SPEC READY  STATUS READY  APPRAISAL READY   <- 완전
item   505  2024타경117502-1   사진5  SPEC READY  STATUS READY  APPRAISAL READY   <- 완전
item  1533  2024타경122092-1   사진5  전부 COLLECTING     <- §3의 결함으로 영구 미수집이었다
item 11853  2024타경126346-1   사진5  STATUS READY, 나머지 pending
item 11854  2025타경90-1       사진5  전부 pending
item 11855  2025타경311-1      사진5  전부 pending
item 11856  2025타경311-2      사진5  전부 pending
item 11857  2025타경939-1      사진5  전부 pending
item 11858  2025타경939-2      사진5  전부 pending
```

즉 **사진은 사용자가 보는 모든 물건에 이미 있고, 부족한 것은 문서다.** 그리고 문서가
부족한 이유는 파이프라인 결함이 아니라 §1(큐를 소진할 배치가 돌지 않음)이다.

### 사진 전수 검증 (45장)

```
auction_image 45행 vs 실제 파일
  파일 없음        0
  크기 불일치      0
  SHA-256 불일치   0
  이미지가 아님    0   (매직 바이트 판정)
  확장자 오판      0   (45/45가 매직과 일치 — 선언 MIME은 전부 image/png였다)
```

Sprint 144의 "선언 MIME을 믿지 않는다" 판단이 실데이터에서 그대로 유지되고 있다.

---

## 3. ★ 발견·수정한 결함 — 진행 중 물건이 영구히 수집되지 않는다

### 증상

`document_queue.auction_date`는 06:00 적재 시점의 **비정규화 사본**이다. 유찰 후
재매각으로 기일이 미래로 다시 잡혀도 이 사본은 옛 날짜를 들고 있을 수 있다.
`doc_worker`의 2차 방어선은 **그 사본**을 보고 `SKIPPED_EXPIRED`로 종결한다.

```
document_queue.auction_date != auction_item.auction_date        36행
  그중 pending + 큐는 과거 + 실제 기일은 미래                     3행
    -> item 1533 (2024타경122092-1)
       큐 2026-07-15  vs  실제 2026-08-19
       spec / status / appraisal 3종 전부
```

item 1533은 **지금 검색에 뜨는 9건 중 하나다.** 배치가 도는 순간 이 3행은 수집되지
않고 종결되고, `SKIPPED_EXPIRED`는 `reset_stale_queue()`의 부활 대상도 아니므로
**문서가 영원히 오지 않는다.** 사용자에게는 "수집중"이 영구히 유지되는 것으로 보인다.

Sprint 74가 이 위험을 이미 알고 `enqueue_documents()`에 갱신 로직을 넣었지만,
**그 갱신은 06:00 크롤이 돌 때만 일어난다.** 크롤과 크롤 사이에 기일이 바뀌면 구멍이
그대로 남는다 — 그리고 지금은 크롤 자체가 5일째 돌지 않았다(§1).

### 수정

`storage/database.py :: reconcile_queue_auction_date()` 신설, `doc_worker`가 종결
**직전에** 호출한다.

```python
today = ...
if auction_date and auction_date < today:
    auction_date = reconcile_queue_auction_date(item["id"], case_no, item_no, auction_date)
if auction_date and auction_date < today:
    mark_queue_skipped_expired(...)
```

**정책은 바꾸지 않았다** — "기일 지난 사건은 수집하지 않는다"는 그대로다. 바꾼 것은
그 판단이 참조하는 **값의 출처**뿐이다(사본 → `auction_item`). Sprint 74의 주석이 같은
말을 한다: *"여기서 고치는 것은 큐가 자기 필드에 사실과 다른 값을 들고 있는 것뿐이다."*

- 드리프트를 발견하면 큐 행도 함께 정정한다(`refresh_queue_priority()`가 같은 값을
  보므로 우선순위 오판도 함께 사라진다)
- `status`는 건드리지 않는다 — 종결된 행을 되살릴지는 재수집 정책이라 제품 판단이다
- `(case_no, item_no)`가 `auction_item` 1,876행에서 유일함을 실측 확인하고 조인 키로 썼다
- 매칭되는 물건이 없으면 큐 값을 그대로 반환한다(판단을 바꾸지 않는다)

### 회귀 + Mutation

`test_asset_pipeline.py` §15-B / §15-C 신설(7개 단언):

```
권위 있는 값을 돌려준다 / 큐 행도 정정된다 / status는 건드리지 않는다
실제로 지난 기일은 그대로 과거(과잉 구제 방지) / 물건이 없으면 큐 값 유지
worker가 import한다 / 종결 호출보다 먼저 호출된다
```

Mutation: `doc_worker`에서 reconcile 호출을 제거 → §15-C가 `rec=-1`로 실패 확인
→ 복원 후 재검증 PASS.

---

## 4. 사용자 흐름 E2E — 실제 서버·실제 데이터

`uvicorn api_server:app` 기동 후 실제 HTTP로 확인.

```
검색            GET /api/v1/search              200, 9건
상세            GET /api/v1/item/502            200, image_count=5, images_status=READY
                                                representative_image=/api/v1/item/502/images/1
                                                SPEC 2쪽 / STATUS(html) / APPRAISAL 19쪽
사진 5장        /item/502/images/1..5           200 image/jpeg x4 + image/gif x1
                                                매직 바이트가 Content-Type과 일치
없는 사진       /item/502/images/6              404      (200 위장 없음)
문서 3종        /item/502/documents/{SPEC,STATUS,APPRAISAL}
                                                200 application/pdf / text/html / application/pdf
알 수 없는 종류  /item/502/documents/UNKNOWN     400
미수집 문서      /item/11855/documents/*         404      (수집 전을 200으로 위장하지 않는다)
HEAD            사진·문서 both                   200      (뷰어의 사전 확인 경로)
```

### 상세페이지(브라우저) — 인증 벽에서 멈춤 (SKIP)

`GET /properties/502` → **307 → `/login?redirect=...`**. `src/proxy.ts`의
`PROTECTED_PREFIXES = ['/properties', '/favorites', '/mypage']`가 Supabase 세션 쿠키를
요구한다. 세션 발급은 외부 서비스 자격증명이 필요해 **SKIP**(§13 승인 영역).

그래서 화면 렌더 자체는 확인하지 못했다. 대신 그 아래층을 전부 고정해 두었다 —
API 계약(위), 프런트/백엔드 필드 계약(`test_asset_pipeline.py` §20이 두 소스를 대조),
`tsc`/`eslint`/`next build` 통과. **"상세페이지가 사진을 보여준다"를 직접 관측한
것은 아니라는 점을 분명히 적어 둔다.**

---

## 5. 관측 개선 — 스케줄러 미등록이 보이게 했다

`test_pipeline_integrity.py` §11(데이터 신선도)은 이미 잘 만들어져 있었다: 검색 0건일
때만 실패하고, 남은 기간이 7일 이하면 크게 경고한다. 지금 출력이 이렇다:

```
마지막 crawl_date : 2026-08-12
기본 검색에 뜨는 물건: 9건
마지막 매각기일   : 2026-08-19
★ 수집이 멈춘 채로 두면 2026-08-20 부터 검색 결과 0건 (3일 남음)
!! 경고: 수집이 멈춰 있다. 3일 뒤 검색 결과가 0건이 된다.
!! 확인 순서: 스케줄러 등록 여부 -> logs/daily_run.log -> run_daily.bat
```

**그런데 "스케줄러 등록 여부"를 확인하라고 안내하면서 정작 확인해 주지는 않았다.**
그 한 줄을 채웠다(`_report_scheduler_registration()`):

```
예약 작업          ★ 등록 0건. run_daily.bat / run_doc_worker.bat가
                   자동 실행되지 않는다. 이것이 로그가 없는 이유다.
                   조치: .\register_scheduler_tasks.ps1 -Apply
                   (사용자 환경 변경이라 자동으로 하지 않는다: Sprint 112)
```

**실패시키지 않는다** — 등록은 코드로 고칠 수 있는 것이 아니고, 이 블록의 설계 원칙이
"제품이 실제로 망가진 상태만 실패"이기 때문이다(로그 파일 보고와 같은 취급).
`schtasks`가 없는 환경(비-Windows)에서는 "확인 불가"로 조용히 넘어간다.

---

## 6. 재수집 정책 — `document_version_log`는 구조적으로 도달 불가 (SKIP)

Sprint 144가 남긴 backlog를 확정했다. **추측이 아니라 호출 경로로 증명된다.**

```
doc_worker.py:168   collect_document(driver, court, case, item, doc_type, btn_id)
                    ^ overwrite 인자를 넘기지 않는다 -> 기본값 False

crawler/doc_crawler.py:177/328/477
                    if doc_exists(...) and not overwrite:
                        result["success"] = True
                        return result          <- previous_hash를 계산하기 전에 반환

storage/database.py:1163
                    if previous_hash and previous_hash != new_hash:
                        INSERT INTO document_version_log ...
```

운영 경로에서 `overwrite=True`가 되는 곳이 **0곳**이므로, 파일이 존재하는 한
재다운로드가 없고 `previous_hash`는 항상 빈 문자열이다. → `document_version_log`에
행이 생길 수 없다. 실측 **0행**이 이것과 일치한다.

### 데이터 손실 가능성

법원이 문서를 정정 게시해도(매각물건명세서 정정은 실무에서 흔하다) 시스템은 **옛
사본을 영구히 보관**하고, 사용자에게 낡은 내용을 보여준다. 변경 사실을 알 방법도 없다.

### 정책 선택지 (제품 판단 — 임의 결정하지 않는다)

| 안 | 내용 | 비용 |
|---|---|---|
| A | 기일 임박(D-7 등) 문서만 강제 재수집 | 큐에 재적재 규칙 + `overwrite=True` 경로. 크롤 부하 소폭 |
| B | 해시만 비교(HEAD/짧은 재다운로드 후 폐기) | 대용량 PDF(최대 131MB)에 비용이 크다 |
| C | 현행 유지(1회 수집 후 불변) | 비용 0, 정정 반영 불가 — **현재 상태** |

### 구현 범위 / 테스트 방법 (정해지면)

- `collect_document(..., overwrite=True)` 경로를 doc_worker가 조건부로 태운다
- `mark_queue_done`은 이미 `previous_hash != new_hash`를 처리하므로 **변경 불필요**
- 테스트: 같은 (물건, 종류)를 두 번 수집하되 두 번째에 다른 바이트를 주고
  ① 파일이 교체되는가 ② `document_version_log`에 1행이 생기는가
  ③ `doc_raw.file_hash`가 갱신되는가 ④ 바이트가 같으면 로그가 **안** 생기는가

---

## 7. 사건 단위 문서 중복 — 측정 결과 개선 대상 아님 (SKIP)

현황조사서는 사건 단위 문서다(Sprint 144가 DOM·내용 양쪽으로 확정). 물건마다 따로
저장하면 중복이 생긴다. **실제로 얼마인지 셌다.**

```
현재 중복        0건        <- STATUS/SPEC/APPRAISAL 전부 동일 해시 0쌍
```

중복이 0인 이유는 구조가 좋아서가 아니라, 예전에는 `item_no != '1'`이 "미지원"으로
종결돼 **사건당 한 물건만 현황조사서를 가졌기 때문**이다. Sprint 144가 그 제약을
풀었으므로 **앞으로는 중복이 생긴다.**

```
다중물건 사건            193건 (물건 688개)
그중 이미 STATUS 보유     17물건
전 물건이 수집될 경우 중복 495부
STATUS 평균 크기         14.3 KB
-> 추가 용량 약 6.7 MB   = documents/ 전체 1,294 MB의 0.52%
```

**0.52%다.** 저장 구조 변경(공유 저장소/하드링크)은 이 이득에 비해 위험이 크다.
`crawler/doc_crawler.py`에 이미 `find_sibling_case_document()`(6시간 내 형제 물건 재사용)가
있어 **크롤 횟수**는 이미 줄고 있고, 남는 것은 디스크뿐이다. 개선하지 않는다.

---

## 8. 성능 (실측, 재측정)

```
search (9건)                mean 3.4 ms   p95  2.8 ms      5,536 B
detail 사진5+문서3          mean 2.3 ms   p95  2.5 ms      3,546 B
detail 자산 없음            mean 2.0 ms   p95  2.2 ms      1,395 B
detail 다중물건(311-2)      mean 2.2 ms   p95  2.4 ms      2,371 B
사진 서빙 70KB              mean 2.9 ms   p95  3.1 ms     70,100 B
문서 SPEC 392KB             mean 3.6 ms   p95  4.0 ms    392,074 B
문서 APPRAISAL 2.5MB        mean 8.4 ms   p95  9.3 ms  2,528,908 B
문서 STATUS html            mean 2.3 ms   p95  2.6 ms     29,914 B
```

### N+1 없음 (SQL 문 수를 직접 셌다)

`sqlite3.set_trace_callback`으로 상세 요청 1건의 실제 SQL을 세었다:

```
item   502 (사진5 + 문서3)   7문
item     1 (자산 0)          7문
item 11856 (다중물건)        7문
```

자산 수와 무관하게 **7문 고정** — Sprint 144 측정과 동일하다. 이번 변경은 상세 경로를
건드리지 않았다(`reconcile_...`은 worker 전용이고, 큐 날짜가 과거일 때만 SELECT 1회 추가).

대용량 PDF(최대 131MB/259쪽)는 Sprint 144 측정 그대로 병목이며, 지금 규모에서
쪽 단위 렌더링은 도입하지 않는다(뷰어에 "새 탭" 링크를 둔 이유).

---

## 9. 검증 결과

```
Python 테스트    33개 파일 중 32 PASS / 1 FAIL
                 FAIL = test_schema_hygiene.py (storage/migrations/020_*.sql 미추적)
                 -> Sprint 144 SKIP #1 그대로. 검사가 제 일을 하는 중이고 커밋하면 해소.
                    Commit 금지 지시라 이번에도 SKIP.
tsc --noEmit     exit 0
eslint src       exit 0 (--max-warnings=0)
next build       exit 0  (첫 시도는 OneDrive 파일 잠금으로 EPERM -> .next 정리 후 통과.
                          BETA_RELEASE_CHECKLIST에 문서화된 알려진 환경 이슈)
compileall       exit 0
사진 전수 대조    45/45 파일·크기·해시·매직 일치
API 스윕         READY 문서 200 / 미수집 404 / 잘못된 종류 400 / 범위 밖 seq 404
```

---

## 10. 변경 파일

### 코드 (2)
```
storage/database.py        reconcile_queue_auction_date() 신설
doc_worker.py              import + 종결 직전 호출 (2차 방어선)
```

### 테스트 (2)
```
test_asset_pipeline.py     §15-B/§15-C 신설(7단언) + 실행 목록 등록
test_pipeline_integrity.py _report_scheduler_registration() — 신선도 검사에 등록 여부 보고
```

### 문서 (7)
```
docs/SPRINT145_ASSET_DELIVERY_AUDIT.md (이 문서, 신규)
docs/BUGS.md              #101 추가
docs/CHANGELOG.md         2026-08-17 항목
docs/CURRENT_STATE.md     "사용자 화면 기준으로 다시 세다" 절
docs/TEST_PLAN.md         Sprint 145 추가(§15-B/§15-C, §11 등록 보고)
docs/crawler.md           2차 방어선 규약
docs/roadmap.md           Sprint 145 + ★★ 기한 항목
docs/decision-log.md      "큐의 매각기일 사본을 신뢰하지 않는다"
```

### 데이터 변경
```
없음. 운영 auction.db / documents/ 를 이번 스프린트는 한 행도 바꾸지 않았다.
(측정은 전부 읽기 전용 쿼리. §3 수정의 실데이터 검증도 auction.db를 임시 복사해
 그 사본에서 수행하고 삭제했다 — 검증 후 운영 DB의 item 1533 큐 3행이 여전히
 2026-07-15임을 재확인했다.)
```

### ★ 동시 작업 관측 (내 변경이 아님)

세션 중반부터 내가 건드리지 않은 파일이 작업 트리에 나타났다. 파일 시각으로 보면
내 편집과 **교대로** 일어났다:

```
11:00 storage/database.py      (나)
11:02 doc_worker.py            (나)
11:03 api/v1/search.py         <- 내가 아님
11:04 src/app/search/types.ts  <- 내가 아님
11:05 test_asset_pipeline.py   (나)
11:14 src/app/search/ResultThumbnail.tsx  <- 내가 아님 (신규 파일)
11:14 src/app/search/ResultList.tsx       <- 내가 아님
11:15 docs/SPRINT145_...md     (나)
```

다른 세션이 같은 저장소에서 **검색 결과 썸네일** 작업을 병행 중인 것으로 보인다.
그쪽 파일은 읽지도 되돌리지도 않았다. 다만 최종 검증(전체 테스트 / `tsc` / `eslint`)은
**그 변경이 섞인 상태에서 돌았고 전부 통과했다** — 즉 아래 결과는 내 변경만의 결과가
아니라 현재 작업 트리 전체의 결과다. 이 사실을 밝혀 둔다.

---

## 11. SKIP (승인 필요)

| # | 항목 | 사유 | 조치 |
|---|---|---|---|
| 1 | **★★ 스케줄러 등록** | 사용자 환경 변경 | `.\register_scheduler_tasks.ps1 -Apply` — **기한 2026-08-20(3일)** |
| 2 | 새 파일 커밋 | Commit 금지 | `test_schema_hygiene` 1건은 커밋 즉시 해소 |
| 3 | 재수집 정책(§6) | 제품 판단 | A/B/C 선택지와 구현 범위·테스트 방법을 §6에 적어 둠 |
| 4 | 사진 dedup / 사건 단위 공유(§7) | 저장 구조 변경 | 이득 0.52%로 측정됨 — 권장하지 않음 |
| 5 | 상세페이지 브라우저 E2E | Supabase 자격증명(외부 서비스) | API·계약·빌드까지는 검증 완료(§4) |
| 6 | 대용량 PDF 쪽 단위 렌더링 | 설계 변경 규모 | 현행 "새 탭" 우회 유지 |
| 7 | `config/settings.py:DOC_TYPE_LIST` 삭제 | **Sprint 136이 이미 "정보 손실 동반, 별도 승인" 으로 보류 결정** | 그 결정을 존중해 이번에도 손대지 않음(미사용 확인만 재확인: import 0곳) |
| 8 | `documents/` 빈 디렉터리 1,674개 / 고아 4파일 | 파괴적 정리 | Sprint 144 SKIP 그대로 |
| 9 | OneDrive 동기화 제외 | OS 설정 | 빌드 EPERM·13GB 동기화의 근본 원인 |

---

## 12. 남은 Backlog / 다음 스프린트

1. **★★ 스케줄러 등록 후 재검증** — 등록되면 큐 2,753 pending이 소진되기 시작한다.
   그때 확인할 것: ① item 1533이 §3 수정 덕분에 실제로 수집되는가
   ② `document_status`에 `IMAGE` 행이 처음 생기는가(현재 0행 — 사진 45장은 큐가 아니라
   Sprint 144의 직접 호출로 저장된 것이라 상태 행이 없다) ③ `NO_IMAGE` 실데이터가
   처음 관측되는가(지금까지 합성 테스트로만 검증됨)
2. **`parsed_document` 0행** — `doc_raw`와 같은 계열. 채우는 코드가 운영 경로에 있는지
   §6과 같은 방식(호출 경로 추적)으로 확인
3. **`SKIPPED_EXPIRED` 문서의 화면 표시** — 큐는 종결됐는데 `document_status`는
   COLLECTING("수집중")으로 남는다. 2,328건 규모이고 상태 enum 확장이 필요해 제품 판단
   (`mark_queue_skipped_expired` 주석 + `test_document_status_sync.py` §6이 현재 동작을 고정 중)
4. **문서 3종의 구독 게이트** — Sprint 112 SKIP 표에 남아 있는 항목

---

# 부록 — Sprint 145 후속 감사 (2026-08-17 12:00 전후, 같은 날 이어서)

Sprint 145 본문이 남긴 backlog를 실측으로 처리하고, Data Flow / DB / Security /
Dead Code 감사를 이어서 돌렸다. **이 구간은 다른 세션이 같은 저장소를 동시에
편집하는 상태에서 진행됐다**(§F).

## A. backlog #2 `parsed_document` — 이미 알려진 BUGS #49였다

Sprint 145 §12가 "다음 스프린트 후보 1번"으로 올렸던 항목이다. 호출 경로를 추적한
결과 **쓰는 코드가 아예 0곳**이다(`doc_raw`는 "실행되지 않는 스크립트에 1곳"이었던
것과 다르다).

전 저장소 `.py`/`.ts(x)`/`.sql`을 훑은 결과:

```
parsed_document          0행   INSERT 0곳  SELECT 0곳   (migrate_v4_1.py의 CREATE만)
rights_analysis_history  0행   참조 자체가 0곳
실제로 파싱 결과가 들어가는 곳:  tenant_rights 519행 / rights_summary 161행
                                 (load_rights_data.py / load_spec_data.py)
```

**새 발견이 아니라 BUGS #49**(2026-08-11 Sprint 55 기록)를 6스프린트 뒤에 재확인한
것이다. #49는 "삭제하면 부트스트랩 테이블 수(25개)가 바뀌고 여러 문서의 실측 기록과
어긋나므로 사실만 기록한다"로 **의도적으로 보류**된 상태이고, 스키마 삭제는 승인
영역이라 이번에도 손대지 않는다.

> 기록해 두는 이유: 이 표가 스프린트마다 "0행이네?"로 다시 조사되고 있다(55 → 144 →
> 145). **이미 조사됐고 의도적으로 남겨 둔 것**이라는 사실이 backlog에 남아 있지 않아
> 반복된다.

### 죽은 스키마 전수 스캔 (26개 테이블)

writer/reader를 소스에서 세어 봤다. 마이그레이션 파일을 제외한 탓에 초기 결과에
오탐이 3건 있었고(`migration_history`는 `run_migrations.py`가, `auction_case`는
`migrate_execute.py`가 쓴다, `auction_item`은 자명), 개별 확인으로 걸러냈다.

**진짜 죽은 표는 위 2개뿐이다.** 나머지 24개는 writer 또는 reader가 실재한다.

## B. 데이터 무결성 전수 감사 — 실측 결과 깨끗하다

```
FK/고아          document_status/doc_raw/auction_image/tenant_rights/rights_summary
                 -> auction_item 전부 0,  auction_item -> auction_case 0
doc_raw <-> 디스크  556행: 파일 없음 0 / 크기 불일치 0 / SHA-256 불일치 0
auction_image     45행: 파일 없음 0 / 이미지 아님 0 / 확장자-매직 불일치 0
중복             doc_raw(item,type) 0 / auction_image(item,seq) 0 /
                 document_status(item,type) 0 / auction_item(case_no,item_no) 0
값 이상          0바이트 0 / auction_date 형식 위반 0 / 최저가>감정가 0 /
                 bid_rate 범위 밖 0 / case_no 빈 값 0
queue<->status   done인데 status가 READY/NO_IMAGE 아님 3건(= FAILED 3건과 일치)
```

### ★ 내 검사 하나가 오탐이었다 (기록해 둔다)

"READY인데 파일 없음 **101건**"이 처음 나왔다. 보고하기 전에 확인하니 **내 경로
조립이 틀린 것**이었다:

1. 복수 사건번호는 `case_no`에 `/`가 들어 있다(`"2024타경1451 / 2024타경32745"`).
   실제 코드는 `/`를 `_`로 치환하는데 내 검사는 `os.path.join`에 그대로 넣어
   존재할 수 없는 경로를 만들었다.
2. `STATUS`는 `status.html`만이 아니라 `status.json`으로 저장된 경우가 있다.

권위 있는 `doc_raw.storage_path`로 대조하면 **556행 전부 존재하고 해시도 일치**한다
(위 표). 실패 0건이다. — *검사 코드가 틀려서 나온 숫자를 결함으로 보고하지 않았다.*

## C. ★ 경로 조각 정규화 — 취약점 1건 수정 + 규칙 3중복 해소

### 발견

`_doc_dir_path()`의 주석은 예전부터 *"규칙은 여기 한 곳에만 두고 ... 규칙이 두 벌이
되면 쓰는 곳과 읽는 곳이 다른 경로를 보는 이 저장소의 단골 결함이 된다"* 고 적고
있었다. 실측하니 같은 치환이 **세 곳**에 각자 적혀 있었다:

```
crawler/doc_paths.py    _doc_dir_path()                (원본)
crawler/doc_paths.py    find_sibling_case_document()   (같은 날 추가된 두 번째 소비자)
crawler/image_assets.py image_path()                   (Sprint 144)
```

그리고 `/`만 치환하고 있었다. **Windows에서는 역슬래시도 경로 구분자다** — 재현:

```
case_no = "..\..\evil"  ->  <repo>/evil/1        <- documents/ 를 벗어난다
case_no = "../../evil"  ->  documents/.._.._evil <- 이쪽은 이미 막혀 있었다
```

영향 범위를 확인했다:

- **서빙은 안전하다** — `api/v1/documents.py`·`api/v1/images.py`가 `realpath` +
  `commonpath`로 `documents/` 밖을 거부한다(파일이 새지 않는다).
- **쓰기가 위험하다** — `get_doc_dir()`가 `os.makedirs()`를 부르므로 저장소 밖에
  디렉터리를 만들 수 있다. 이 저장소는 이미 `doc_paths` 때문에 **빈 디렉터리
  1,674개**가 생긴 사고를 겪었다.
- **실데이터는 깨끗하다** — `case_no`/`item_no`에 역슬래시 0건, `..` 0건,
  `storage_path`가 `documents/` 밖 0건. 즉 **터지던 버그가 아니라 자리를 막은 것**이다.

### 수정

`crawler/doc_paths.py`에 `sanitize_path_segment()`를 신설하고 세 곳이 함께 쓰게 했다.
`/`와 `\` 둘 다 `_`로 바꾸고, 조각이 `""`/`"."`/`".."`가 되면 `_`로 대체한다
(`os.path.join`에 빈 조각을 주면 그 단계가 통째로 사라져 상위를 가리킨다).

**실데이터 회귀 없음**을 먼저 확인했다 — `doc_raw` 556행, `auction_image` 45행 전부
새 규칙으로 계산한 경로에서 파일이 그대로 발견된다(복수 사건번호 101행 포함).

### 회귀 테스트 — `test_doc_path_safety.py` (신규)

정상 → 실데이터 형태(복수 사건번호) → 경계값(`""`/`.`/`..`) → 잘못된 입력(구분자) →
**어떤 입력으로도 `documents/`를 벗어나지 않음** → **세 소비자가 같은 디렉터리를
가리킴** → **규칙 사본이 다시 생기지 않음(소스 대조)** 순으로 검사한다.

Mutation 3회 전부 검출 확인:

| 되돌린 것 | 결과 |
|---|---|
| 역슬래시 처리 제거 | 5건 실패, 실제 탈출 경로(`<repo>\evil\1`)까지 출력 |
| `image_path`에 인라인 사본 재도입(case_no) | 탈출 검출 |
| `image_path`에 인라인 사본 재도입(item_no) | §7이 `image_assets.py:271`을 정확히 지목 |

### 정정 — "문서 경로 슬래시 처리가 미검증"은 내 오판이었다

처음에 "문서 쪽 슬래시 처리는 테스트가 없다"고 판단했는데 **틀렸다.**
`test_pipeline_integrity.py` §0이 소스 텍스트 대조로 이미 고정하고 있었고, 내 grep이
리터럴 문자열만 찾아 놓친 것이다. 내 리팩터가 그 리터럴을 없애자 §0이 **정확히
실패했다** — 검사가 제 일을 한 것이다. (그 뒤 다른 세션이 §0을 "리터럴 비교"에서
"두 구현의 결과 직접 대조"로 바꿔 더 강한 검사가 됐다.)

## D. 검색 썸네일 — 실측 2.03 MB/페이지 (측정만, 수정 없음)

다른 세션이 추가한 검색 결과 썸네일이 실제로 동작한다(9/9가 200 + 실 JPEG 바이트).
다만 **원본을 그대로 내려준다**:

```
표시 크기   80x80 CSS px (w-20 h-20)
실제 전송   평균 104 KB, 최대 236 KB, 원본 522~700 px
9건 합계    0.91 MB
기본 페이지(size=20) 환산   약 2.03 MB / 페이지
```

컴포넌트는 잘 만들어져 있다(`loading="lazy"`, `onError` 폴백) — 지연 로딩이 화면
아래쪽은 덜어 주지만 **보이는 행은 원본을 그대로 받는다.**

근본 해결은 서버 측 썸네일 생성이고, 그것은 Sprint 144 SKIP #2다
(`Pillow`가 `requirements.txt`에 선언돼 있지 않아 새 의존성 도입 = 승인 영역).
API의 `thumbnail_url` 필드는 이미 있으므로 **프런트 계약은 바뀌지 않는다.**

## E. 재검증 (전 항목 실행 결과)

```
Python 테스트   34개 파일 -> 33 PASS / 1 FAIL
                FAIL = test_schema_hygiene.py (미추적 파일 감지) — Commit 금지라 SKIP
tsc --noEmit    exit 0
eslint src      exit 0 (--max-warnings=0)
next build      exit 0 (이번엔 1차 시도에 통과)
compileall      exit 0 — 내 새 파일의 SyntaxWarning 1건을 발견해 함께 고쳤다
                (docstring 안 `\.` 이스케이프)
E2E             검색 200(9건) -> 썸네일 9/9 200 -> 상세 200 -> 사진 5/5 200
                (jpeg x4 + gif x1, Content-Type이 매직과 일치) -> 문서 3/3 200
성능            search 2.2ms / detail 2.2ms / image 2.3ms / APPRAISAL 2.5MB 8.5ms
                경로 리팩터로 인한 회귀 없음
```

## F. ★ 동시 편집 — 공유 문서를 갱신하지 않은 이유

이 구간 내내 **다른 세션이 같은 저장소를 초 단위로 편집했다.** 관측된 시각:

```
11:59:25  api/v1/documents.py          (다른 세션)
12:00:10  test_doc_path_safety.py      (나)
12:00:40  crawler/doc_paths.py, image_assets.py   (나)
12:01:31  test_pipeline_integrity.py   (다른 세션)
12:04:02  docs/CURRENT_STATE.md        (다른 세션)
12:04:23  docs/BUGS.md                 (다른 세션)
```

그쪽은 "Sprint 146"으로 작업 중이고, 내가 만든 `sanitize_path_segment()`를
`api/v1/documents.py`가 쓰도록 **가져다 붙였다** — 결과적으로 서빙 쪽까지 규칙이
하나로 모였다(소비자 4곳).

**그래서 이번 후속 구간의 내용을 `BUGS.md`/`CHANGELOG.md`/`CURRENT_STATE.md`에
쓰지 않았다.** 전체 파일 쓰기는 그쪽의 진행 중 편집을 덮어쓸 수 있고, 지시가
"다른 세션의 변경사항은 절대 되돌리지 않는다"이기 때문이다. 내용은 전부 이 문서
(내가 만든 파일)에 남긴다. **공유 문서 반영은 동시 편집이 끝난 뒤에 해야 하는
남은 일이다.**

## G. 이 구간에서 바꾼 파일

```
crawler/doc_paths.py       sanitize_path_segment() 신설 + 2곳이 사용
crawler/image_assets.py    image_path()가 공용 함수 사용
test_doc_path_safety.py    신규 (7개 그룹)
docs/SPRINT145_...md       이 부록
```

운영 `auction.db` / `documents/` 변경 **0행**(감사는 전부 읽기 전용 쿼리).
