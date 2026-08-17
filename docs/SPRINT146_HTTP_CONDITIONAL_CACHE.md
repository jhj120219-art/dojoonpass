# Sprint 146 — 조건부 요청(304) · parsed_document 추적 · 경로 조각 정규화

Status: 코드 수정 2건 완료 / 운영·정책 항목 SKIP
Date: 2026-08-17
Scope: 검색 화면 전송량, `parsed_document` 0행의 진짜 이유, 경로 조각 정규화 통일

> **동시 편집 주의** — 이 스프린트는 다른 세션과 같은 저장소에서 **동시에** 진행됐다.
> 그쪽도 "Sprint 146"으로 작업 중이며 `docs/BUGS.md` · `docs/CURRENT_STATE.md` ·
> `test_asset_pipeline.py` 등을 편집했다. 충돌을 피하려고 이 문서는 **새 파일**로 두고,
> 공유 문서는 건드리지 않았다(§9).

---

## 0. 한 줄 요약

검색 결과가 원본 사진을 썸네일로 쓰면서 **1페이지에 약 2 MB**를 내려주는데, 서버가
조건부 요청을 해석하지 않아 **페이지를 다시 열 때마다 그 2 MB를 통째로 다시 보냈다.**
새 의존성 없이 304를 구현해 **재방문 전송량을 0으로** 만들었다. `parsed_document`는
추적 결과 결함이 아니라 이미 문서화된 상태였다.

---

## 1. ★ 검색 화면 전송량 — 재방문에도 매번 전량 재전송

### 발견 (실측)

Starlette `FileResponse`는 `etag`/`last-modified`를 **붙여 주기만 하고 조건부 요청을
해석하지 않는다.** 설치본(`starlette 1.3.1`) 소스를 직접 확인했다 — `FileResponse`에
`if-none-match`/`304` 처리가 없고 `if-range`만 다룬다.

수정 전 실측:

```
GET /api/v1/item/502/images/1                          200     70,100 B
GET 같은 URL + If-None-Match: <그 etag>                200     70,100 B   <- 304여야 한다
GET /api/v1/item/502/documents/APPRAISAL               200  2,528,908 B
GET 같은 URL + If-None-Match: <그 etag>                200  2,528,908 B
GET 같은 URL + If-Modified-Since: <그 last-modified>   200  2,528,908 B
Cache-Control                                          (없음)
```

영향이 가장 큰 곳은 **검색 목록**이다. 검색 카드 썸네일이 원본 사진을 그대로 쓴다
(서버 측 썸네일 생성은 Pillow 미선언으로 Sprint 144 SKIP #2):

```
검색 노출 9건        0.91 MB   평균 104 KB / 최대 236 KB / 원본 522~700 px
표시 크기            80x80 CSS px (w-20 h-20)
기본 page size 20 환산   약 2.03 MB / 페이지
```

즉 **80×80으로 그릴 그림을 원본 그대로 받고, 그것을 매 방문마다 반복**했다.

### 수정

`api/http_cache.py` 신설 — `not_modified(request, response)`가 이미 만들어진
`FileResponse`의 검증자를 보고 304를 줄지 판단한다. `images.py`/`documents.py` 둘 다 사용.

**RFC 9110을 따른다** — `If-None-Match`가 있으면 그것만 보고(§13.1.3 우선순위),
없을 때만 `If-Modified-Since`를 본다. `If-None-Match`는 약한 비교(§13.1.2)라 `W/`
접두사를 떼고 비교하며, `*`와 콤마 목록도 처리한다. 304에는 검증자를 다시 실어 준다(§15.4.5).

#### ★ 조용히 실패했던 자리 — `stat_result`

1차 구현은 **아무 효과가 없었다.** 원인은 Starlette가 `stat_result`를 받지 않으면
**응답을 보낼 때에야** 파일을 stat해 검증자를 만든다는 것이다(`FileResponse.__call__`).
그래서 생성 직후에는 `response.headers`에 `etag`가 없고, 내 검사가 아무것도 못 봤다.

```python
FileResponse(path, ..., stat_result=os.stat(path))   # <- 이것이 없으면 항상 200
```

**응답 코드만 보면 정상이라 눈치채기 어렵다.** 그래서 회귀 테스트에 §7(소스 대조)을
따로 뒀다 — 동작 검사(§2)가 실패했을 때 원인을 바로 짚어 주기 위해서다.

### 수정 후 실측

```
                     최초        If-None-Match   If-Modified-Since   틀린 etag      *
image 70KB           200 70,100  304  0 B        304  0 B            200 70,100    304
APPRAISAL 2.5MB      200 2.5MB   304  0 B        304  0 B            200 2.5MB     304
SPEC 392KB           200 392KB   304  0 B        304  0 B            200 392KB     304
STATUS html          200 29,914  304  0 B        304  0 B            200 29,914    304
HEAD                 200         200 (의도된 예외 — 아낄 본문이 없다)

검색 1페이지 재방문   0.91 MB  ->  0.00 MB   (절감 100%)
```

**HEAD에는 일부러 304를 주지 않는다.** HEAD 응답에는 본문이 없어 304로 아낄 바이트가
**0**인데, 프런트는 문서 존재 확인을 `fetch(HEAD).then(res => res.ok ? 'ok' : 'notfound')`
로 한다(`src/app/properties/[id]/page.tsx`). `res.ok`는 200~299에서만 참이다. 브라우저는
`cache: "default"`에서 재검증 304를 JS에 노출하지 않으므로 정상 경로에서는 문제가 없지만,
**이득이 0인 자리에 그 의존을 남길 이유가 없어** HEAD는 항상 200/404로 둔다.

`page size 20` 환산으로 **약 2.03 MB → 0 B**.

### 무엇을 하지 않았나

**`Cache-Control: max-age=...`를 임의로 정하지 않았다.** 그것은 "사용자가 며칠 지난
사진을 봐도 되는가"라는 제품 판단이고, 재수집 정책이 아직 미정이다
(`document_version_log`가 구조적으로 도달 불가 — Sprint 145 §6). 지금 구현은
**바이트만 아끼고 신선도 판단은 바꾸지 않는다** — 클라이언트는 여전히 매번 서버에
물어보므로 "오래된 문서가 보인다" 같은 부작용이 원리적으로 없다. 정책이 정해지면
`api/http_cache.py`에 한 줄로 붙는다.

**서버 측 썸네일 생성도 하지 않았다** — Pillow가 `requirements.txt`에 없어 새 의존성
도입이고(Sprint 144 SKIP #2), API의 `thumbnail_url` 필드는 이미 있으므로 승인만 나면
프런트 계약 변경 없이 붙는다. 그때는 전송량이 재방문뿐 아니라 **최초 방문에서도** 준다.

---

## 2. `parsed_document` 0행 — 결함이 아니라 이미 문서화된 상태

지시대로 원본→다운로드→`doc_raw`→parser→`parsed_document`→API→Frontend를 추적했다.

```
parsed_document          0행   INSERT 0곳   SELECT 0곳   (migrate_v4_1.py의 CREATE만)
rights_analysis_history  0행   참조 자체가 0곳
```

`doc_raw`(556행)는 "실행되지 않는 스크립트에 쓰는 코드가 1곳" 이었던 것과 달리,
`parsed_document`는 **쓰는 코드가 아예 없다.** 이미 **BUGS #49**(2026-08-11 Sprint 55)로
기록돼 있고 *"삭제하면 부트스트랩 테이블 수가 바뀌고 여러 문서의 실측 기록과 어긋나므로
사실만 기록한다"* 로 **의도적으로 보류**된 상태다. 스키마 삭제는 승인 영역 → SKIP.

### 실제 파싱 경로는 다른 표로 간다

```
load_rights_data.py  ->  rights_summary(161행) + tenant_rights
load_spec_data.py    ->  tenant_rights (SPEC 240 / STATUS 279, 합 519행)
```

### ★ 그 파서들이 배치에 없다 (이미 문서화된 SKIP)

스케줄 배치 3종이 실제로 실행하는 파이썬을 전부 확인했다:

```
run_priority_refresh.bat  refresh_priority.py
run_doc_worker.bat        doc_worker.py
run_daily.bat             mvp_scraper.py, migrate_execute.py
```

`load_rights_data.py` / `load_spec_data.py` / `collect_documents.py` / `analyze_docs.py`는
**어느 배치에도 없다.** 이는 `docs/CURRENT_STATE.md`가 이미 적어 둔 그대로이고,
*"배치에 넣는 것은 운영 스케줄 결정이라 SKIP했다"* 로 결론까지 나 있다.

내 측정이 그 문서의 숫자와 맞는지 대조했다:

```
문서가 적은 값   권리분석 커버리지 8.7%
내 측정          rights_summary 161 / auction_item 1,876 = 8.6%      <- 일치
READY 기준       SPEC 116/197 = 58.9%,  STATUS 161/162 = 99.4%
                 (즉 SPEC READY 197건 중 81건은 파싱된 적이 없다)
```

**결론: 코드 결함 없음.** 수집은 자동인데 파싱이 수동이라는 구조적 사실이고,
그 해소는 운영 스케줄 결정이라 이번에도 SKIP한다.

---

## 3. 경로 조각 정규화 통일 + 탈출 차단

`_doc_dir_path()` 주석이 *"규칙은 여기 한 곳에만"* 이라고 못박아 둔 치환이 실제로는
세 곳에 각자 있었고, `/`만 치환하고 있었다. Windows에서는 역슬래시도 구분자라 재현됨:

```
case_no = "..\..\evil"   ->  <repo>/evil/1      <- documents/ 탈출
case_no = "../../evil"   ->  documents/.._.._evil  (이쪽은 이미 안전)
```

- **서빙은 안전했다** — `documents.py`/`images.py`가 `realpath`+`commonpath`로 차단
- **쓰기가 위험했다** — `get_doc_dir()`가 `os.makedirs()`를 부른다. 이 저장소는 이미
  `doc_paths` 때문에 빈 디렉터리 1,674개가 생긴 사고를 겪었다
- **실데이터는 깨끗** — 역슬래시 0건, `..` 0건 (터지던 버그가 아니라 자리를 막은 것)

`crawler/doc_paths.py :: sanitize_path_segment()`로 모으고 `/`·`\` 둘 다 치환,
조각이 `""`/`"."`/`".."`면 `_`로 대체(`os.path.join`에 빈 조각을 주면 그 단계가 사라져
상위를 가리킨다). **실데이터 회귀 없음** — `doc_raw` 556행 + `auction_image` 45행이
새 규칙으로 계산한 경로에서 그대로 발견된다(복수 사건번호 101행 포함).

> 이 항목은 다른 세션이 이어받아 `api/v1/documents.py`(읽는 쪽)까지 같은 함수를 쓰도록
> 맞췄다. 결과적으로 소비자 4곳이 한 규칙을 공유한다.

---

## 4. 회귀 테스트 (신규 2개 파일)

### `test_http_conditional.py`

정상(검증자 존재) → **304 동작** → 거짓 304 방지(틀린 etag/빈 값/깨진 날짜/과거 시각) →
etag 매칭 규칙(`*`, `W/`, 콤마 목록) → **If-None-Match 우선순위** → **HEAD는 304를 주지 않음** → `stat_result` 소스 대조.

대상 id를 하드코딩하지 않고 **실 DB에서 고른다** — 수집이 진행되면 id가 바뀌고,
그때 "기능이 깨졌다"가 아니라 "데이터가 없다"로 실패하면 신호가 흐려지기 때문이다.

### `test_doc_path_safety.py`

정상 → 실데이터 형태(복수 사건번호) → 경계값(`""`/`.`/`..`) → 구분자 →
**어떤 입력으로도 root 탈출 없음** → **세 소비자 경로 일치** → **규칙 사본 재발 금지**.

---

## 5. Mutation Test (5회 전부 검출)

| 되돌린 것 | 결과 |
|---|---|
| `stat_result` 인자 제거 | §2가 4건 실패 (304여야 할 자리에 200 70,100 B) |
| `If-None-Match` 우선순위 제거 | §5가 실패 (etag 불일치인데 304를 줬다) |
| 역슬래시 치환 제거 | 5건 실패 + 실제 탈출 경로 `<repo>\evil\1` 출력 |
| 인라인 사본 재도입(case_no) | 탈출 검출 |
| 인라인 사본 재도입(item_no) | `image_assets.py:271`을 정확히 지목 |

전부 복구 후 재검증 PASS.

---

## 6. 전체 검증

```
Python 테스트   35개 파일 -> 34 PASS / 1 FAIL
                FAIL = test_schema_hygiene.py (미추적 파일 감지) — Commit 금지라 SKIP
tsc --noEmit    exit 0
eslint src      exit 0 (--max-warnings=0)
compileall      exit 0 (경고 0)
E2E             검색 200(9건) -> 썸네일 9/9 200 -> 상세 200 -> 사진 5/5 200 -> 문서 3/3 200
성능            search 2.2ms / detail 2.2ms / image 2.3ms / APPRAISAL 2.5MB 8.5ms
                조건부 재요청 304는 본문 0 B
```

---

## 7. 변경 파일

```
신규   api/http_cache.py              조건부 요청 판정 (RFC 9110)
       test_http_conditional.py       304 회귀 (7개 그룹)
       test_doc_path_safety.py        경로 조각 회귀 (7개 그룹)
       docs/SPRINT146_...md           이 문서

수정   api/v1/images.py               Request 주입 + stat_result + not_modified
       api/v1/documents.py            같음
       crawler/doc_paths.py           sanitize_path_segment() 신설 + 2곳 사용
       crawler/image_assets.py        공용 함수 사용
```

운영 `auction.db` / `documents/` 변경 **0행** (감사는 전부 읽기 전용 쿼리).

---

## 8. SKIP (승인 필요)

| 항목 | 사유 |
|---|---|
| `Cache-Control: max-age` | 신선도 = 제품 판단. 재수집 정책 미정과 얽힘 |
| 서버 측 썸네일 생성 | Pillow 새 의존성(Sprint 144 SKIP #2). 붙으면 **최초 방문**도 줄어든다 |
| `load_rights_data`/`load_spec_data` 배치 편입 | 운영 스케줄 결정(CURRENT_STATE에 기존 SKIP) |
| `parsed_document`/`rights_analysis_history` 삭제 | 스키마 변경(BUGS #49 보류 결정) |
| **★★ 스케줄러 등록** | 사용자 환경 변경. **기한 2026-08-20** |
| Commit / Push | 지시 |

---

## 9. 동시 편집 — 공유 문서를 건드리지 않은 이유

다른 세션이 같은 저장소를 병행 편집 중이고, 관측된 마지막 활동이 `docs/BUGS.md` ·
`docs/CURRENT_STATE.md` · `doc_worker.py` · `storage/database.py` · `test_asset_pipeline.py`였다.
전체 파일 쓰기는 그쪽의 진행 중 편집을 덮어쓸 수 있으므로 **공유 문서에 쓰지 않았다.**

내 Sprint 145 변경(`reconcile_queue_auction_date`)과 이번 변경이 그쪽 편집 후에도
그대로 살아 있는지 확인했고(전부 intact), 내 테스트 3종도 전부 통과한다.

**남은 일**: 동시 편집이 끝난 뒤 이 문서의 내용을 `BUGS.md`/`CHANGELOG.md`/
`CURRENT_STATE.md`/`TEST_PLAN.md`에 반영해야 한다.

---

## 10. 다음 스프린트

1. **★★ 스케줄러 등록**(기한 2026-08-20) — 등록 후 큐 소진 관측
2. 서버 측 썸네일(승인 시) — 최초 방문 전송량까지 감소
3. `Cache-Control` 정책 결정(재수집 정책과 함께)
4. 공유 문서 동기화

---

# 부록 A — 검색 엔드포인트의 인증 없는 500 (같은 날 이어서)

조건부 요청 검증이 끝난 뒤 **모든 공개 GET 경로에 극단 입력을 넣는 스윕**을 돌렸다
(`/openapi.json`으로 30개 GET 경로를 열거해 대상 선정). 거기서 새 결함이 나왔다.

## 발견 — 7개 파라미터가 토큰 없이 500을 만든다

```
/api/v1/search?min_appraisal=9999999999999999999999999   500
              ?max_appraisal=                            500
              ?min_bid_price=                            500
              ?max_bid_price=                            500
              ?min_fail_count=                           500
              ?max_fail_count=                           500
              ?page=                                     500
              ?size=                                     422   <- 이것만 무사
```

원인은 Sprint 144가 `item_id`에서 고친 것과 **같은 계열**이다 — 파이썬 int는 무한
정밀도인데 SQLite INTEGER는 64비트라, 상한 없는 값을 그대로 바인딩하면
`OverflowError: Python int too large to convert to SQLite INTEGER`다.
`size`만 무사했던 이유는 `Query(20, ge=1, le=100)`이 이미 상한을 갖고 있었기 때문이다.

경계로 원인을 확정했다:

```
?min_appraisal=2**63-1   -> 200      (SQLite 범위 안)
?min_appraisal=2**63     -> 500      (넘는 순간 터진다)
```

### `page`는 값이 아니라 곱한 결과가 넘친다

```
?page=2**63-1  -> 500     <- page 자체는 SQLite 범위 안인데도 터진다
```

OFFSET이 `(page - 1) * size`이기 때문이다. **값만 검사했으면 이 케이스를 놓쳤을 것**이라
계산된 offset을 검사한다.

## 수정

`api/constants.py`의 기존 `is_sqlite_int()`를 **그대로 재사용**한다(새 헬퍼를 만들지
않는다). 상태 코드만 Sprint 144와 다르다 — 거기서는 "존재할 수 없는 id"라 404가 맞았지만
여기서는 **검색 조건 값**이므로, 이 엔드포인트가 `sort_by`/`property_type`에 이미 쓰고
있는 **400 + 사유**와 같은 규약으로 거절한다.

```
수정 후
  7개 파라미터 전부           400 (사유 포함)
  ?min_appraisal=2**63-1     200   <- 과잉 차단 없음
  ?page=1, ?page=2           200   <- 정상 페이지네이션 보존
  정상 범위 필터              200
```

## 회귀 + Mutation

`test_search.py`에 11개 단언 추가(그 파일의 기존 `check()` 스타일 그대로).
정상 차단 7건 + **과잉 차단 방지 4건**(경계값·정상 페이지·정상 필터)을 함께 고정한다 —
차단만 검사하면 "전부 400"으로 고쳐도 통과하기 때문이다.

Mutation: 가드 블록을 통째로 제거 → **8건 실패**(6개 필터 + page 초대형 + page=2^63-1).
복구 후 70/70 통과.

## 전체 재스윕

52개 극단 입력을 다시 던졌다.

```
응답 분포   404:10  422:10  400:11  401:6  200:15
500 / 예외  NONE
```

---

# 부록 B — 조건부 요청 공격 (추가 검증)

§1의 기본 동작 위에, 실패 시나리오를 직접 만들어 던졌다.

## 파일 변경/삭제 후 캐시 검증 (가장 중요)

캐시가 실패하는 방식은 보통 "안 준다"가 아니라 **"낡은 것을 준다"**다. 운영
`documents/`를 건드리지 않고 `test_asset_pipeline.Env`(임시 DB + 임시 문서 루트)로
실제 엔드포인트를 통해 확인했다:

```
1) 최초 GET                     200  5,003 B
2) 같은 etag                    304      0 B
3) ★ 파일 내용/크기 변경 후 옛 etag  200  9,003 B   <- 낡은 304를 주지 않는다
   etag가 실제로 바뀌었다        True
4) 새 etag                      304      0 B
5) ★ 파일 삭제 후                404             <- 캐시가 삭제를 가리지 않는다
6) 삭제 + `*`                    404
```

검증자 자체도 따로 확인했다 — 내용 변경·크기 변경·**같은 크기 다른 내용**(mtime이
구해 준다) 모두에서 `etag`와 `last-modified`가 바뀐다.

## 대용량 파일 — 실질 병목이 사라졌다

```
130.8 MB / 259쪽 감정평가서 (item 480)
  최초 GET        200  130.8 MB  328 ms
  If-None-Match   304       0 B    3 ms
  If-Modified-Since 304     0 B    2 ms
```

Sprint 144가 "실질 병목"으로 기록한 131MB PDF가 **재검증에서는 3 ms / 0 B**가 된다.

## Range + 조건부 혼용

```
Range만                206  1,000 B   (Content-Range: bytes 0-999/137137806)
Range + 맞는 etag      304      0 B   <- RFC 9110 §13.1.2: If-None-Match가 Range보다 먼저
Range + 틀린 etag      206  1,000 B
```

## malformed 조건부 헤더 (8종) — 500 0건

빈 문자열 / 콤마만 / 따옴표 없음 / `W/`만 / 8KB 길이 / `%00` / `*, *` / 제어문자 —
전부 200 또는 304로 정상 처리. `If-Modified-Since`에 숫자·음수·5KB 문자열·미래 날짜를
넣어도 500 없음(미래 날짜는 304가 맞다 — 그 시각 이후 수정되지 않았다).

## 동시 요청

```
200 경로 40개 동시   전부 (200, 70100)   56 ms   합계 2.67 MB
304 경로 40개 동시   전부 (304, 0)       38 ms   합계 0.00 MB
혼합 60개(200/304/404)   정확히 20/20/20 — 교차 오염 없음
```

## Failure Injection — DB는 정상인데 파일이 병든 경우 (8종)

```
0바이트 파일                     404
MIN_IMAGE_BYTES 미만(13B)        404
storage_path가 documents/ 밖      404  (+ 경고 로그)
storage_path에 ../ 탈출           404  (+ 경고 로그)
storage_path 빈 문자열            404
파일 자리에 디렉터리               404
DB엔 있는데 파일 없음              404
이미지가 아닌 바이트(크기 충분)     200  <- 아래 참고
```

**500은 하나도 없었다.** 마지막 항목만 200인데, 쓰기 경로가 매직 판정으로 이미
막고 있고(`sniff_image_ext`가 판정 실패 시 저장하지 않는다) 확장자도 그 판정에서
나오므로 Content-Type이 어긋날 수 없다. 실데이터 45장 전부 매직 일치라 **실제 발생
0건**이다 — 확인된 문제가 아니므로 코드를 바꾸지 않고 기록만 한다.

---

# 부록 C — 필드 단위 Data Flow 대조

API 응답과 프런트가 실제로 읽는 필드를 소스에서 뽑아 맞췄다.

```
검색   API 19 필드  vs  src/app/search/types.ts 19 필드
       TS에만 있음 0 / API에만 있음 0            <- 완전 일치

상세   API 27 필드  vs  page.tsx가 읽는 21 필드
       프런트가 읽는데 API에 없음: 0             <- undefined를 읽는 자리 없음
       API가 주는데 안 읽음: dong, sido, sigungu, is_favorited,
                            image_count, representative_image
```

`images[].thumbnail_url`은 현재 `url`과 **같은 값**이다. 이는 결함이 아니라
`api/v1/item.py`에 적힌 의도된 설계다 — 서버 썸네일이 생겨도 프런트 계약이 바뀌지
않도록 필드를 미리 만들어 둔 것이고, 주석이 그 이유를 명시하고 있다.

---

# 부록 D — 이 구간의 변경 파일

```
수정   api/v1/search.py     숫자 파라미터 SQLite 범위 검사(400) + OFFSET 곱셈 검사
       test_search.py       회귀 11단언 추가 (차단 7 + 과잉차단 방지 4)
       test_http_conditional.py  §8 파일 변경/삭제 후 캐시 검증 추가
```

운영 `auction.db` / `documents/` 변경 **0행**.

---

# 부록 E — 이어서 수행한 감사 (2026-08-17 14:00 전후)

이 구간은 **새 결함을 찾지 못했다.** 검사한 영역이 전부 "이미 담겨 있거나 영향 0"으로
확인됐고, 그 사실 자체가 결과다. 아래는 그 근거다.

## E-1. ★ 내가 만든 결함이 다른 세션에 잡혔다 (BUGS #103)

Sprint 145에 신설한 `reconcile_queue_auction_date()`가 물건을
**`case_no + item_no`로만** 찾고 있었다. 내가 근거로 적은 것은
*"(case_no, item_no)가 auction_item 1,876행에서 유일함을 실측 확인"* 이었다.

**그 확인은 방향이 틀렸다.** `auction_item` 안에서 유일한 것과, **큐 행이 자기 법원의
물건과 맺어지는가**는 다른 명제다. 조인 상대는 `document_queue`이고 큐에는 자기
`court_code`가 따로 있다. 실측하니 **큐의 (사건,물건)이 다른 법원의 물건과 매칭되는
행이 18행(pending 12행)** 있었다 — 법원마다 사건번호를 독립 채번하기 때문이다.

이 저장소가 BUGS #18·#14로 이미 두 번 잡은 "법원 없는 식별키" 함정이고,
**내가 세 번째로 다시 넣었다.**

다른 세션이 `court_code`를 요구하도록 고쳤다. 그 수정이 옳은지 직접 검증했다:

```
item 1533 (원래 내가 고치려던 대상)
  spec/status/appraisal 3종 전부  큐 2026-07-15 -> 정정 2026-08-19  RESCUED
  => 원래 목적(진행 중 물건 구제)은 그대로 보존된다

교차 법원 오염 시도 (성남지원 큐 vs 통영지원 물건, 같은 사건번호)
  큐기일 2026-07-20 / 타법원기일 2026-08-10 -> 결과 2026-07-20   오염 없음
  => 법원이 다르면 정정하지 않는다
```

**교훈**: "유일성을 확인했다"고 적을 때 **무엇과 무엇 사이의 유일성인지**를 명시해야
한다. 조인의 반대편을 보지 않은 확인은 확인이 아니다.

## E-2. 정규화 드리프트 — 숫자는 크지만 사용자 영향 0

`test_pipeline_integrity.py` §12가 상한으로 관리하던 값을 직접 재계산했다
(`normalize_address`를 실 주소 1,876건에 다시 돌림).

```
sido       불일치   4행
sigungu    불일치 207행
dong          0행
lot_number    0행
```

**그중 기본 검색에 노출되는 물건: 0건** (전부 기일 경과).

### 원인 — 옛 정규화기가 도로명·건물명 안의 시도명을 잡았다

```
id=8160  '경기도 시흥시 서울대학로 59-21'      -> 저장 sido='서울'   (도로명 오매칭)
id=1787  '경상남도 양산시 물금읍 부산대학로'    -> 저장 sido='부산'   (도로명 오매칭)
id=550   '인천광역시 계양구 ... 뉴서울아파트'   -> 저장 sido='서울'   (건물명 오매칭)
```

`sigungu` 207건은 전부 **한 가지 패턴**이다 — 저장값이 더 짧다(구 누락:
`안양시` vs `안양시 만안구`). "완전히 다른 지역" 0건.

### 지금 코드는 고쳐져 있다 (쓰기 경로 확인)

```
mvp_scraper.py -> normalize_batch() -> normalize_item() -> normalize_address()
```

즉 내가 재계산에 쓴 함수가 **크롤러가 실제로 쓰는 바로 그 함수**다. 재계산이 옳은
값을 내므로 앞으로 들어올 데이터는 정상이다. 남은 207+4행은 **옛 규칙의 잔재**이고,
백필은 운영 데이터 변경이라 SKIP이며 **지금 얻을 이익도 0이다**(노출 0건).
기존 상한 검사(§12 "늘지 않았다")가 올바른 처치다.

## E-3. validation_status FAIL 12건 — 역시 노출 0

```
PASS 1,864 / FAIL 12   |  FAIL 중 검색 노출 0건
```

FAIL 목록에 E-2의 sido 오류 물건(id=550, 9977)이 실제로 들어 있다 —
**검증 엔진이 드리프트를 제 손으로 잡아내고 있다.** 오작동이 아니다.

## E-4. ★ 2026-08-20 마감 de-risking — 배치가 실제로 뜨는가

가장 급한 항목은 스케줄러 등록(승인 영역, SKIP)이다. 등록 자체는 못 하지만
**등록했을 때 실제로 도는지**는 확인할 수 있고, 그것이 이 마감의 실질 위험이다.
(과거에 Anaconda 제거로 배치가 전부 죽고 8일간 아무도 몰랐던 전례가 있다.)

```
1) 인터프리터 해석 (배치 로직 그대로 재현)
   C:\ProgramData\Anaconda3\python.exe   없음  <- 과거 장애의 원인
   PATH 폴백                              성공
   -> C:\Users\jhj12\AppData\Local\Programs\Python\Python312\python.exe (3.12.10)
   => Sprint 99가 넣은 폴백이 이 머신에서 실제로 동작한다

2) 배치가 부르는 4개 스크립트
   mvp_scraper / migrate_execute / doc_worker / refresh_priority
   컴파일  4/4 OK      (migrate_execute.py의 UTF-8 BOM 포함)
   import  4/4 OK      (미추적 모듈까지 작업트리에서 정상 해석)
```

**결론: 등록만 하면 도는 상태다.** 등록 전에 코드 쪽에서 막을 것은 없다.

> 단, BUGS #105 주의 — `git commit -a`로 커밋하면 미추적 모듈이 빠져 API가 부팅되지
> 않는다. 반드시 `git add -A`.

## E-5. 다른 세션 변경 반영 후 재검증

Sprint 146~148에서 `doc_worker.py`·`storage/database.py`·`crawler/doc_crawler.py`·
`crawler/doc_paths.py`·`ResultList.tsx`가 바뀌었으므로 내 이전 측정을 다시 돌렸다.

```
E2E     search 200(9건) -> 썸네일 9/9 200 -> 상세 200(사진5·문서3)
        -> 사진 5/5 200 -> 문서 3/3 200 -> 조건부 304 여전히 동작
성능    search 2.11ms / detail 2.05ms / image 200 2.24ms / image 304 1.69ms
전체    34 PASS / 1 FAIL(test_schema_hygiene — 미추적 파일 감지, Commit 금지라 SKIP)
```

내 변경(`sanitize_path_segment` / `not_modified` / `stat_result` / `is_sqlite_int` 가드)
전부 intact.

## E-6. 이미 처리돼 있어 손대지 않은 것

- **추적 파일이 미추적 모듈을 import** — 내가 3건(.py)을 찾았는데,
  다른 세션이 이미 `test_schema_hygiene.py` §6-B로 검사를 넣어 뒀고
  **내 것보다 넓다**(`ResultList.tsx -> ResultThumbnail.tsx`까지 4건 검출).
  중복 구현하지 않았다.
- `parsed_document` / `rights_analysis_history` — BUGS #49 보류 결정 유지.

## E-7. 이 구간의 변경 파일

```
없음 (코드 변경 0). 이 부록만 추가했다.
운영 auction.db / documents/ 변경 0행 — 측정은 전부 읽기 전용 또는 임시 복사본.
```

---

# 부록 F — 내 검증에 있던 구멍 두 개를 메웠다

## F-1. ★ 프런트엔드 테스트를 한 번도 돌리지 않고 있었다

지금까지 "전체 테스트 통과"라고 적어 온 것은 **파이썬 스위트만**이었다.
`package.json`에 `test:frontend`가 있고 `tests/*.test.mjs` 5개 파일이 있다.

```
npm run test:frontend
  -> Next 서버(localhost:3000)에 연결할 수 없습니다  (통합 테스트다)
```

API(8000) + `next build` + `next start`(3000)를 띄우고 다시 돌렸다:

```
tests 111 / suites 42 / pass 111 / fail 0
```

**111개가 전부 통과한다.** 다만 이 사실을 이번에 처음 확인했다 —
파이썬만 돌리고 "전체 통과"라고 적은 것은 과장이었다.

## F-2. ★ 실제 렌더된 화면을 처음으로 확인했다

이전 스프린트들에서 상세페이지(`/properties/{id}`)가 Supabase 세션을 요구해
**"화면 렌더는 확인 못 했다"** 고 여러 번 적었다. 그런데 `src/proxy.ts`의
`PROTECTED_PREFIXES`는 `/properties`·`/favorites`·`/mypage`뿐이고 **`/search`는
게이트 대상이 아니다.** 즉 검색 화면은 처음부터 확인할 수 있었다.

`GET http://localhost:3000/search`의 실제 HTML(59,969자)을 받아 파싱했다:

```
썸네일 <img> 태그        9개  (전부 loading="lazy")
  src 예) http://localhost:8000/api/v1/item/505/images/1
상세 링크 물건 id        502, 505, 1533, 11853~11858  (검색 노출 9건 전부)
실데이터 렌더            타경 18회 · 법원 23회 · 감정가 20회 · 최저가 18회
```

그리고 **그 HTML에 박힌 URL을 그대로 요청**했다:

```
최초 방문   9/9 200,  0.91 MB
재방문      9/9 304,  0.00 MB      <- Sprint 146의 조건부 요청이 실화면 경로에서 동작
```

즉 **원천 → DB → 파일 → API → Frontend → 실제 렌더된 화면**까지 전 구간이
실제 바이트로 이어지는 것을 처음으로 끝까지 확인했다.

> 남은 미확인: `/properties/{id}` 상세 화면(갤러리·라이트박스·문서 뷰어)은 여전히
> Supabase 세션이 필요해 확인하지 못했다. **검색 화면은 확인됨, 상세 화면은 미확인**으로
> 구분해 적는다.

## F-3. 인증 감사 — 독립 공격 33종, 결함 0

`api/auth.py`를 읽고 끝내지 않고 위조 토큰을 직접 만들어 던졌다.

```
엔드포인트 레벨 24종 (12개 위조 토큰 x 필수인증/선택인증 두 경로)
  alg:none · alg:NONE · alg 없음 · HS256 임의서명 · HS256 빈 시크릿 서명
  ES256 kid 없음 · 미지 kid · RS256 kid 없음 · HS512 · JWT 아님 · "..." · 빈 문자열
  -> 필수 인증(/favorites)  전부 401
  -> 선택 인증(/search)     전부 200 + 비로그인 강등(is_favorited 미설정)
  -> 500  0건

decode 함수 직접 9종 (합성 시크릿으로 HS256 경로까지 실제 실행)
  정상 통과(대조군) / 서명 변조 / payload role 상승 / 다른 시크릿 /
  alg:none 헤더 교체 / 만료 / HS384 / HS512 / ES256헤더+HMAC서명
  -> 9/9 기대대로
```

`algorithms=[alg]`가 코드에 보여 처음엔 위험해 보였지만, **`alg`가 화이트리스트를
통과한 뒤에만** 그 줄에 도달하므로 안전하다 — 공격으로 확인했다.

**이미 `test_auth_jwt.py`가 39개 단언으로 같은 영역을 덮고 있다**(키 회전·JWKS
속도제한·빈 JWKS 복원력까지). 내 공격은 그 테스트들이 **거짓 안심을 주고 있지 않다는
독립 확인**이고, 중복 테스트를 추가하지 않았다.

## F-4. 이 구간 변경 파일

```
코드 변경 0. 이 부록만 추가.
운영 auction.db / documents/ 변경 0행.
```

---

# 부록 G — 커버리지 실측으로 테스트 공백 찾기

"어디를 더 테스트해야 하나"를 감으로 고르지 않고 **`coverage`로 실측**했다
(35개 파이썬 테스트 파일을 전부 커버리지 아래에서 실행 후 합산).

## G-1. 0% 모듈 3개 — 성격이 서로 다르다

```
crawler/court_crawler.py     91문장  0%
filter/scoring_engine.py     68문장  0%
filter/report_generator.py   54문장  0%
```

**같은 0%인데 조치가 정반대다.** import 관계를 추적해 갈랐다:

| 모듈 | import 하는 곳 | 판정 |
|---|---|---|
| `court_crawler.py` | **`mvp_scraper.py`(06:00 운영 배치)** + `test_db.py` | **살아 있는 코드**, 미검증 |
| `report_generator.py` | **없음** | 죽은 코드 |
| `scoring_engine.py` | `report_generator.py`(그 자체가 죽음)뿐 | 전이적으로 죽은 코드 |

`filter/` 두 개는 **이미 Sprint 78(2026-08-13)이 같은 결론을 냈고**
`docs/CLAUDE.md:120`이 *"deleting them is approval-gated; **do not add tests for them
either** — testing code nobody runs buys nothing"* 라고 못박아 두었다. 내 실측이 그
기록을 재확인했을 뿐이라 **테스트를 붙이지 않았다.**

## G-2. `court_crawler.py`는 왜 0%였나 — 이미 옳게 설계돼 있었다

모듈 안의 함수는 셋뿐이고, 그중 둘은 selenium 드라이버를 받는다:

```
log_error(case_no, step, error, retry)      <- 순수
crawl_detail(driver, item_info, court)      selenium
crawl_court(court)                          selenium
```

그리고 소스에 이렇게 적혀 있다:

```python
# 순수 계산 로직이라 selenium 없이도 쓸 수 있어야 해서 crawler/resume.py로 분리했다
from crawler.resume import resume_start_idx
```

즉 Sprint 47이 **테스트 가능한 로직을 이미 밖으로 빼 뒀다.** 실제로 그 결과가 커버리지에
그대로 나온다:

```
crawler/resume.py        100%
storage/checkpoint.py    100%
models/auction_item.py   100%
models/crawl_outcome.py  100%
```

**0%는 설계 실패가 아니라 브라우저가 필요한 코드가 남은 것**이다. 남은 순수 함수는
`log_error` 하나뿐이었다.

## G-3. 그 하나가 하필 "조용한 실패"를 지키고 있었다

```python
try:
    os.makedirs("logs", exist_ok=True)   # <- Sprint 98이 넣은 한 줄
    with open("logs/errors.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
except Exception:
    pass                                  # <- 모든 예외를 삼킨다
```

`logs/`는 `.gitignore` 대상이라 **새 체크아웃/배포에는 없다.** `makedirs`가 빠지면
`open()`이 실패하고 `except`가 삼켜 **크롤 오류 기록이 통째로 증발한다** — 정작 가장
필요한 순간에. Sprint 98이 고쳤지만 **검사가 없어서 지우면 아무도 모른다.**

### `test_crawl_error_log.py` 신설 (5개 그룹)

정상 기록 → **logs/ 부재 시 자동 생성** → append(덮어쓰지 않음) →
경계값(300자 절단·정확히 300자·한글 보존) → 실패 주입(쓸 수 없어도 예외를 던지지 않음).

운영 `logs/`를 오염시키지 않는다 — 임시 디렉터리로 `chdir` 후 실행하고 되돌린다.

**Mutation**: Sprint 98의 `os.makedirs` 한 줄을 제거 →
`[FAIL] 파일이 생겼다` / `[FAIL] 한 줄이다: 0 (expected 1)` 로 정확히 검출 → 복원 후 PASS.

**커버리지: `court_crawler.py` 0% → 24%** (남은 76%는 selenium 경로).

## G-4. 찾았지만 **고치지 않은 것** — 근거를 남긴다

`entry` dict가 `try` **밖**에서 만들어지고 거기에 `str(error)[:300]`이 있다. `__str__`이
예외를 던지는 별난 예외면 `log_error` 자신이 예외를 던져 "크롤을 멈추지 않는다"는 계약이
깨진다. 처음엔 결함으로 보였다.

**그런데 도달 불가능하다.** 프로덕션 호출부가 하나뿐이고 바로 윗줄이 이미 `str(e)`를 부른다:

```
crawler/court_crawler.py
  81      logger.warning("[%s] attempt %d/%d failed: %s",
  82          case_no, attempt, MAX_RETRY, str(e))     <- 여기서 먼저 터진다
  83      log_error(case_no, "detail", e, attempt)
```

고쳐도 관측 가능한 동작이 바뀌지 않으므로 **오류 처리 경로를 건드리지 않았다.**
대신 그 판단의 전제("호출부는 하나")를 §5-B 검사로 고정했다 — 두 번째 호출부가 생기면
그때는 실제 위험이 되므로 테스트가 먼저 알린다.

## G-5. 이 구간 변경 파일

```
신규   test_crawl_error_log.py    (5개 그룹 + 전제 고정 1)
수정   없음 (프로덕션 코드 0)
```

전체 테스트 **35 PASS / 1 FAIL (36 파일)** — 실패는 `test_schema_hygiene.py`이고
사유 3건 전부 미추적/동시세션 작업 관련이다(`020_*.sql` 미추적, 추적파일→미추적모듈
import 4건, 다른 세션이 편집 중인 `unlock_retry.py`의 SQL 연결 허용목록). **내 변경으로
생긴 실패는 없다.**

---

# 부록 H — 커버리지가 가리킨 두 번째 공백: 상세 API의 로그인 경로

부록 G가 `court_crawler.py`를 다뤘다면, 모듈별로 다시 실측했을 때 **살아 있는 코드 중
가장 큰 공백**은 다른 곳이었다.

## H-1. `api/v1/item.py` 80% — 빠진 13줄이 한 덩어리였다

```
api/v1/item.py   64문장  13 미커버  80%   (76-98행)
```

흩어진 13줄이 아니라 **연속된 한 블록**이고, 그 블록이 전부 **로그인 사용자 경로**다:

```python
if credentials:
    payload = decode_supabase_jwt(...)          # 토큰 해석
    user_id = payload.get("sub")
    if user_id:
        try:
            record_view(conn, user_id, item_id)  # 최근조회 자동 기록
        except Exception:
            logger.warning(...)                  # <- 실패해도 상세는 계속돼야 한다
is_favorited = ... SELECT 1 FROM favorites ...   # 하트 채움 여부
```

즉 **비로그인 상세 조회만 검증되고 있었다.** 로그인 사용자에게만 일어나는 일
(최근조회 기록, 즐겨찾기 표시)과, 그 부수 기능이 실패해도 상세가 떠야 한다는 계약이
한 번도 실행된 적이 없었다.

`test_auth_jwt.py`가 `is_favorited`를 검증하긴 하지만 그것은 **검색** 응답이다
(`ES256 로그인 시 결과에 is_favorited 필드가 채워진다`). 상세는 코드가 따로다.

## H-2. 왜 이 계약이 중요한가

`record_view()`는 `INSERT ... ON CONFLICT DO UPDATE` + `commit()`이다. 쓰기가 실패할
수 있는 경로(락·디스크·제약)가 실재하는데, 그때 **상세 페이지 전체가 500이 되면 안
된다.** 코드는 이미 `try/except`로 방어하고 있었지만 **검사가 없어서 누가 걷어내도
아무도 모르는 상태**였다. 이 저장소가 반복해 겪은 "조용한 실패"의 반대편 —
**부수 기능 실패가 주 기능을 죽이는** 실패다.

## H-3. `test_item_detail_auth.py` 신설 (6개 그룹)

```
1. 비로그인(대조군)      200 · is_favorited False · recent_items 0행
2. 로그인                recent_items 1행 · user_id == 토큰 sub
                         재조회해도 행이 늘지 않는다(ON CONFLICT DO UPDATE)
3. 즐겨찾기              찜 전 False -> 찜 후 True -> **다른 사용자에겐 False**(사용자 격리)
4. 위조 토큰 3종         전부 200 + 비로그인 강등, 최근조회 기록 0행
5. ★ record_view 폭발    상세는 여전히 200, 본문 정상, is_favorited 계산은 계속
6. 소스 배선 고정        record_view 호출이 try/except 안에 있다
```

운영 데이터를 건드리지 않는다 — `test_asset_pipeline.Env`(임시 DB + 실제 부트스트랩
스키마)를 재사용하고, 토큰은 `test_auth_jwt.py`와 같은 방식의 **합성 시크릿**으로 만든다.
실제 credential은 쓰지도 출력하지도 않는다.

## H-4. Mutation — 한 번은 "잡았지만 잘 못 알렸다"

| 되돌린 것 | 결과 |
|---|---|
| `is_favorited = fav is not None` -> 항상 False | `[FAIL] 찜 후에는 True` 즉시 검출 |
| `record_view`의 `try/except` 제거 | **처음엔 트레이스백으로 죽었다** |

두 번째가 문제였다. `TestClient`는 서버 예외를 **그대로 다시 던지므로**(기본
`raise_server_exceptions=True`) 보호가 사라지면 테스트가 트레이스백으로 중단되고,
`[FAIL]` 한 줄로 원인이 보이지 않았다. **검출은 됐지만 신호가 나빴다.**

그래서 §5가 요청을 `try`로 감싸 예외를 **실패로 보고**하도록 고쳤다. 이제:

```
[FAIL] ★ record_view 예외가 상세 조회로 새어 나오지 않는다 -- RuntimeError: 의도적 실패: DB 잠김 등
[FAIL] ★ 호출 앞에 try가 있다
[FAIL] ★ 뒤에 except가 있다
```

**커버리지 `api/v1/item.py` 80% -> 100%.**

## H-5. 이 구간 변경 파일

```
신규   test_item_detail_auth.py   (6개 그룹)
수정   프로덕션 코드 0
```

전체 **36 PASS / 1 FAIL (37 파일)** — 실패는 `test_schema_hygiene.py`(미추적 파일 및
다른 세션이 편집 중인 `unlock_retry.py` 관련)뿐이고 **내 변경으로 생긴 실패는 없다.**
운영 `auction.db` / `documents/` 변경 **0행**.

---

# 부록 I — 검증 도구 자체를 검증했다

## I-1. 프런트엔드 스위트의 요약 줄은 믿으면 안 된다 (실측)

부록 F에서 `npm run test:frontend`를 처음 돌렸을 때 111/111이었다. 그런데 나중에 다시
돌렸더니 이렇게 나왔다:

```
✖ `/`는 redirect되지 않는다 (비로그인)
✖ `/`에 검색 Form이 있다
...
ℹ tests 111
ℹ pass 63
ℹ fail 0        <- ✖가 잔뜩인데 fail이 0이다
```

원인은 코드가 아니라 **Next 서버(3000)가 죽어 있었던 것**이다(셸 리셋으로 종료됨).
이 스위트는 통합 테스트라 서버가 필요하다.

문제는 `fail 0`이라는 요약이다. **요약 줄만 grep하면 통과로 읽힌다** — 실제로 내가
직전 보고에서 "111 tests / 63 pass / 0 fail"을 그대로 옮겨 적을 뻔했다.
`node:test`가 suite 레벨 `✖`를 `fail` 집계에 넣지 않는 표시 방식 때문이다.

### 그래서 exit code를 직접 쟀다

```
서버 있음   npm run test:frontend  -> exit 0   (tests 111 / pass 111 / fail 0)
서버 없음   npm run test:frontend  -> exit 1   ← CI는 정상적으로 잡는다
```

**CI 위험은 없다.** 다만 사람이 요약 줄만 보면 속는다.
→ 앞으로 이 스위트의 결과는 **`fail` 숫자가 아니라 exit code로 판단한다.**

(대조 실험으로 `before` 훅이 실패하는 최소 재현을 만들어 보니 그때는 `fail 2` + exit 1로
정상 집계됐다. 즉 집계 누락은 훅 실패 방식에 따라 갈리는 표시 문제이고, exit code는
어느 경우에도 정직했다.)

## I-2. 내 테스트가 운영 DB를 건드리지 않았는지 확인했다

`test_item_detail_auth.py`는 로그인 사용자 경로를 검증하므로 `recent_items`/`favorites`에
**쓰기가 일어난다.** 임시 DB(`test_asset_pipeline.Env`)를 쓰도록 만들었지만, 격리가
실제로 됐는지 운영 DB에서 직접 확인했다:

```
recent_items 에서 user_id='user-under-test'   0행
             에서 user_id='other-user'        0행
favorites    에서 user_id='user-under-test'   0행
```

**격리 성공.** 다만 그 과정에서 운영 `recent_items`가 32 -> 35로 는 것을 발견해
출처를 끝까지 추적했다 — 내 것이 아니었다:

```
leaked-user            25행  마지막 2026-08-13   <- 옛 테스트 잔재(이미 문서화됨)
126e425c-91e8-...      10행  마지막 2026-08-17   <- 다른 세션의 로그인 E2E 브라우징
qa-reg-*                0행                     <- 현재 테스트는 정리하고 끝낸다(확인)
```

둘 다 `docs/CURRENT_STATE.md`가 이미 기록해 둔 것이고(다른 세션이 자기 E2E가 4행을
남긴 사실까지 적어 두었다), 삭제는 운영 데이터라 승인 영역이다.

> 표현 정정: 앞선 보고에서 "운영 DB 0행 변경"이라고 적었는데, 정확히는
> **"내 변경·내 테스트가 남긴 행이 0"** 이다. 저장소의 기존 테스트(`test_api_regression.py`)는
> 운영 DB에 `qa-reg-*` 사용자로 쓰고 **정리하고 끝낸다**(실측 잔존 0행).

## I-3. 이 구간 변경 파일

```
코드 변경 0. 이 부록만 추가.
```

---

# 부록 J — 내가 보고해 온 "36 PASS" 는 틀린 숫자였다

## J-1. 커버리지를 파다가 집계 오류를 발견했다

`storage/database.py` 가 88% 라 미커버 줄을 함수로 매핑했더니 가장 큰 덩어리가
`query()` (270~297, 28줄) 였다. 호출부를 찾으니 **`test_db.py:70` 하나뿐**이었다.
그런데 커버리지에는 0줄로 잡힌다 — 모순이다. 직접 돌려 봤다:

```
$ python -m coverage run --source=storage.database test_db.py
CoverageWarning: Module storage.database was never imported.
[SKIPPED] test_db.py 는 실제 크롤 사이트를 호출하는 실행 스크립트입니다 (회귀 대상 아님).
          실행하려면 명시적으로 허용하십시오:  ALLOW_LIVE_CRAWL=1 python test_db.py
exit=0
```

**스스로 SKIP 하고 0으로 끝난다.** 그리고 내 집계 반복문은 이것을 **PASS 로 셌다.**

전 파일을 다시 재니 같은 파일이 4개였다:

| 파일 | 정체 | 내 옛 집계 |
|---|---|---|
| `test_db.py` | `ALLOW_LIVE_CRAWL` 게이트 실크롤 스크립트 | PASS(오) |
| `test_docs.py` | 〃 | PASS(오) |
| `test_docs2.py` | 〃 | PASS(오) |
| `test_filter.py` | 판정문이 아예 없는 진단 스크립트 | PASS(오) |

> **정정:** 앞서 여러 번 보고한 `PASS=36 FAIL=1 (of 37)` 에서, 실제로 무언가를
> **검증하는** 파일은 **32개**다. 4개는 단언 0건으로 0을 돌려줄 뿐이다.
> 실패 1건(`test_schema_hygiene.py`)은 그대로다.

## J-2. 왜 문구 grep 으로는 못 고치나 (한 번 더 틀릴 뻔했다)

`[FAIL]` 을 grep 하도록 바꿔 봤더니 이번엔 **통과한 테스트가 실패로 잡혔다.**
`test_auction_identity.py` 가 이렇게 찍는다:

```
[FAIL] document_status 불일치: 5629 != 5628      <- 그런데 끝은 ALL TESTS PASSED, exit 0
```

조사해 보니 **정상이다.** `test_migrate_exit_code_contract()` 가 임시 DB 사본에
stray 행을 일부러 넣고 `migrate_execute.execute()` 가 False 를 돌려주는지 확인한다
(5628 + 주입 1행 = 5629). 즉 저 `[FAIL]` 은 **검사 대상의 정상 출력**이다.
문구만 보면 의도된 음성 테스트를 버그로 신고하게 된다.

게다가 결과 어휘가 세 벌이다 — `[PASS]/[FAIL]` 28개, `[OK]/[NG]` 일부,
마커 없이 `ALL ... TESTS PASSED` 만 찍는 파일 5개(`test_api_regression.py`,
`test_asset_pipeline.py`, `test_document_queue.py`, `test_document_status_sync.py`,
`test_pipeline_integrity.py`). 이것들도 내가 "단언 0건"으로 잘못 분류했었다.

## J-3. 그래서 종료코드가 믿을 만한지 **주입해서** 확인했다

정적으로 훑으니 5개 파일에 `sys.exit(1)` 이 없어 보였다. 그중 하필
`test_auth_jwt.py`(JWT 보안, 39단언) 가 있어 실패를 주입해 봤다:

```
주입 후 종료코드 : 1        <- 정직하다
```

`if __name__` 블록 없이 **모듈 끝에서** `sys.exit(1 if FAIL else 0)` 을 한다.
내 정적 검사가 `__main__` 꼬리만 봐서 놓친 것이다(내 검사가 틀렸다, 코드는 멀쩡).

**결론: 실제 회귀 테스트 33개는 전부 실패 시 non-zero 로 끝난다. 종료코드는 믿을 수 있고,
출력 문구는 믿을 수 없다.**

## J-4. `run_python_tests.py` 를 만들었다 (신규)

일괄 실행 수단이 **없었다** — `.github/workflows` 없음, `.bat`/`.ps1` 에서
`test_*.py` 참조 0건, `package.json` 은 프런트용 `test:frontend` 뿐. 그래서 세션마다
즉석 반복문을 만들었고 그 즉석 반복문이 위처럼 두 번 틀렸다.

합격 판정은 **종료코드**로만 하고, 출력 문구는 **분류**에만 쓴다. 그리고
통과와 무판정을 절대 합치지 않는다:

```
PASSED      종료코드 0 + 판정문 있음      진짜 통과
FAILED      종료코드 != 0                 진짜 실패
SKIPPED     스스로 건너뛴다고 밝힘        실행 안 됨 (통과 아님)
NO-VERDICT  0인데 판정문 없음             검증했다고 말할 수 없음
```

실측 결과:

```
$ python run_python_tests.py
 통과 32 | 실패 1 | 건너뜀 3 | 판정없음 1 | 시간초과 0   (단언 4,160건, 46.9s)

실패 (1):                                   - test_schema_hygiene.py
건너뜀(실행되지 않음 — 통과가 아니다) (3):  - test_db.py / test_docs.py / test_docs2.py
판정문 없음(검증했다고 말할 수 없다) (1):   - test_filter.py
exit=1
```

`SKIPPED`/`NO-VERDICT` 는 종료코드를 붉게 만들지 않는다("깨졌다"가 아니라 "안 돌았다").
대신 요약에 **항상 이름이 남아** 숫자만 보고 넘어갈 수 없게 했다.
`emit()` 은 cp949 콘솔에서도 죽지 않는다(`test_console_encoding.py` 가 지키는 그 문제).

## J-5. 곁가지로 확인한 것 — `auction` vs `auction_item` 은 어긋나지 않았다

`query()` 가 읽는 `auction` 은 API 가 쓰는 `auction_item` 과 **별개 테이블**이라
표류(drift)를 의심해 실측했다:

```
auction        1,876행 (23컬럼)        auction_item   1,876행 (21컬럼)
키(court|case|item) 공통 1,876 · auction 단독 0 · auction_item 단독 0
같은 키인데 auction_date 불일치 :  0건
```

**동기 상태다. 버그 아님.** (`auction` 전용: court_code, has_*_pdf, validation_reasons /
`auction_item` 전용: bid_rate, case_id, fail_count)

`query()` 자체는 **프로덕션 호출부가 0개**다(유일 호출부가 게이트된 `test_db.py`).
사용자 규칙대로 Dead 성격 코드는 삭제 판단을 하지 않고 호출 경로만 기록한다 —
삭제는 Architecture 결정이라 SKIP.

## J-6. 이 구간 변경 파일

```
신규   run_python_tests.py          (실행기, 프로덕션 코드 무변경)
추가   docs/SPRINT146_...md         이 부록
```

프로덕션 코드 변경 **0**.
