# Sprint 240 — 좁은 폭을 **진짜로** 재고, mutation 이 batching 의 빈 가드를 잡았다

**날짜** 2026-08-21. HEAD `9c1f8ed` / branch `master` / 커밋·푸시 없음.
운영 `auction.db` 무변경(읽기만) / `.env` 무변경 / 스케줄러 등록 없음 / 실크롤 없음.

---

## 0. 기준선 — 이전 문서의 숫자를 믿지 않고 다시 쟀다

Sprint 239 문서와 **실제로 달랐다**. 그 사이 migration 020 적용과 `doc_raw` 백필이
이뤄져 있었다(누가 언제 했는지는 이 세션이 알 수 없다). 이번 세션 실측값만 쓴다.

```
                      Sprint 239 문서      2026-08-21 실측
auction_image         "없음"               45행 (물건 9개)
doc_raw               0행                  556행
document_status       READY 555            READY 556 / COLLECTING 5069 / FAILED 3
document_queue        5,062행(대기 4,318)  3,498행 (pending 2,753 / done 559 / SKIPPED_EXPIRED 186)
auction_item          -                    1,876행
crawl_date 최신       2026-08-18           2026-08-12
스케줄러              DOJOONPASS_DAILY 존재 이 저장소를 가리키는 작업 **0개**
```

테스트 기준선(수정 전):

```
python run_python_tests.py   통과 47 | 실패 1 | 건너뜀 3 | 판정없음 1 (단언 7,082, 93.4s)
node --test tests/*.test.mjs 137개 중 133 PASS / 1 FAIL / 3 SKIP
tsc --noEmit                 0
eslint                       0
```

### 그 1건의 실패는 코드 결함이 아니다 — **데이터 신선도**다

python 쪽 실패 `test_pipeline_integrity.py` 와 node 쪽 실패는 **같은 원인 하나**다.

```
auction_item 의 auction_date 최대값 = 2026-08-19,  오늘 = 2026-08-21
-> auction_date >= 오늘 인 물건이 0건 -> 기본 검색이 빈 화면
```

두 가드 모두 정확히 그 사실을 말하고 있었다(가드가 옳다). 이것을 증명하기 위해
**날짜만 +30일 옮긴 fixture DB 사본**(scratchpad, 운영 DB 무변경)으로 같은 코드를 돌렸다:

```
node --test  API_BASE_URL=fixture   ->  137 / 137 PASS, 0 FAIL, 0 SKIP
```

즉 **데이터만 신선하면 프런트 계약은 전부 통과한다.** 크롤 재개는 승인 영역이라
이 결손 자체는 이번 세션이 풀 수 없다(Release Blocker 로 남긴다).

---

## 1. ★ mutation 이 batching 의 **비어 있는 가드**를 잡았다 (이번 세션 최대 발견)

`doc_worker.py` 의 item-level batching 은 코드도 테스트도 완성돼 보였다
(`test_worker_batching.py` 통과). 그래서 **믿지 않고 mutation 을 걸었다.**

```
MUT1  _batch_order 를 상수 0 으로            -> 잡힘 (exit 1)
MUT2  재사용 시 엄격도 검사 제거              -> 잡힘
MUT3  if wait_for_detail(...) -> if True:    -> ★ 살아남았다 (두 스위트 모두 통과)
MUT4  미시도 행 release 제거                  -> 잡힘
MUT5  재시작 후 page.clear() 제거             -> 잡힘
```

### 왜 위험한가

`_ensure_detail_page()` 의 그 한 줄은 **batching 전체가 서 있는 가정을 지키는 유일한
가드**다. 문서 수집기는 새 창을 열고 닫은 뒤 원래 창으로 돌아오는데 그 복구가 전부
`try/except: pass` 다(`crawler/doc_crawler.py` 의 finally 두 곳). 돌아오지 못한 채
다음 종류를 처리하면 **엉뚱한 화면에서 남의 문서를 긁는다** — 이 저장소가 사진에서
겪은(Sprint 230) 것과 같은 계열의, 조용히 틀리는 결함이다.

### 왜 아무도 못 잡았나

`test_worker_batching.py` / `test_doc_worker_recovery.py` 의 **모든 harness 가**
`wait_for_detail` 을 `lambda: True` 상수로 스텁했다. False 분기(화면을 벗어났다 ->
다시 이동한다)를 **한 번도 지나가지 않았다.** 지우면 아무도 울지 않는 가드는
없는 것과 같다.

### 고침

- `_run_worker()` 에 `detail_ok` 훅을 뚫어 상수 스텁을 깼다.
- 검사 13번 신설 `test_reuse_verifies_the_page_before_trusting_it()`:
  단위(A/B) + 워커 전체(C) + 코드 존재(D).
- **재-mutation 으로 확인**: 같은 MUT3 를 다시 걸면 이제 **5개 단언이 동시에 실패**한다.

```
[FAIL] ★ 화면을 벗어나 있으면 재사용하지 않고 다시 이동한다: 1 (expected 2)
[FAIL] ★ 확인 실패가 반복돼도 매번 다시 이동한다: 1 (expected 3)
[FAIL] ★ 재이동이 실패하면 False 를 돌려준다(빈 화면에서 긁지 않는다) -- ok2=True
[FAIL] ★ 실패 후 페이지 기억을 남기지 않는다 -- page.key=(...) 가 남았다
[FAIL] ★ 화면을 벗어나 있으면 행마다 다시 이동한다 -- 이동 3회 != 큐 12행
```

제품 코드는 **바꾸지 않았다** — 옳은 코드였고, 없던 것은 검사였다.

---

## 2. ★ 좁은 폭을 처음으로 **진짜 뷰포트**에서 쟀다 — 결함 3종 발견·수정

### 2.1 측정 수단이 먼저 생겼다

Sprint 219 이래 이 저장소는 좁은 폭을 못 쟀다. 이번에도 다시 확인했다(문서를 믿지 않는다):

```
resize_window(320,720) -> "성공" 응답, 그러나 innerWidth 1905 그대로   (Sprint 223 과 동일)
iframe src=앱          -> X-Frame-Options: DENY                        (Sprint 224 와 동일)
```

**두 가지 새 수단**을 찾았다:

```
(a) iframe + srcdoc + <base>   서버 HTML 을 받아 srcdoc 에 넣으면 X-Frame-Options 가
                              적용되지 않는다. iframe 은 **자기 뷰포트**를 가지므로
                              미디어쿼리가 정상 평가된다(matchMedia md -> false 확인).
                              한계: Suspense 로 스트리밍되는 화면(상세)은 완성되지 않는다.

(b) window.open(url,'',
      'width=320,height=800')  ★ 진짜 320px 창이다. innerWidth 320, 미디어쿼리 정상,
                              클라이언트 렌더/인증 세션까지 전부 살아 있다.
                              -> 이것으로 전 화면을 쟀다.
```

측정기 자체를 **known-good / known-bad 로 검증**했다: 일부러 넣은 넓은 div 는 매번
탐지되고(`selftest: true`), 제거하면 0 이 된다. Tailwind 적용 여부도 매 측정에서 확인한다.

또한 **"스크롤 컨테이너 안에서 넘치는 것"과 "페이지를 밀어내는 것"을 구분**한다.
정렬 칩 5개는 320px 에서 뷰포트를 넘지만 `overflow-x` 컨테이너 안이라 **결함이 아니다**
— 이 구분을 넣기 전에는 그것들이 결함으로 보였다.

### 2.2 발견한 결함 (전부 실측, 전부 수정)

```
(1) 공통 헤더 — 전 화면 영향, **로그인 상태에서만** 나타난다
    우측 묶음(검색·최근 본 물건·관심물건·마이페이지·로그아웃) 276px
    CONTAINER 안쪽 가용 폭 257px, `shrink-0` 이라 줄지도 않는다
    -> 오른쪽 끝 308px vs 뷰포트 289px -> **모든 화면이 가로 스크롤**
    비로그인은 '로그인' 한 줄(219px)이라 들어간다 — 로그아웃 상태로만 보면 멀쩡했다.

(2) 검색조건 저장 줄 (/search)
    `flex-1` input + `shrink-0` 저장 버튼. flex 항목의 min-width 기본값이 `auto` 라
    input 이 자기 고유 폭 아래로 줄지 않는다
    -> 저장 버튼 오른쪽 끝 295px vs 뷰포트 289px

(3) ★ 목록 카드 3화면 공통 (/search, /favorites, /properties/recent)
    grid 항목인 `<Link className="block">` 의 min-width 가 `auto`.
    카드 안 `truncate`(= white-space:nowrap) 문단의 min-content 가 문자열 전체 폭이라
    grid 트랙이 컨테이너보다 넓어진다.
      /search      컨테이너 257px vs 트랙 277.6px  (오른쪽 끝 294)
      /favorites   컨테이너 257px vs 트랙 727.7px  (오른쪽 끝 744)
      /properties/recent  같은 구조 — 같은 결함
```

#### ★ 내가 한 번 틀렸고, 그것을 기록해 둔다

(3) 을 처음 쟀을 때 `/search` 는 **깨끗하다고 나왔다.** 이유는 그때 측정 URL 이
`/search`(검색 파라미터 없음)라 **결과 카드가 없었기** 때문이다. `/favorites` 에서
같은 결함을 보고 나서야 `?sido=서울` 을 붙여 다시 쟀고, 그제서야 `/search` 도
넘친다는 것이 드러났다. **"넘침 없음"이 아니라 "잴 대상이 없었음"이었다.**

### 2.3 고침 — 색·크기·간격은 하나도 바꾸지 않았다

전부 **줄어들 수 있게 / 접힐 수 있게** 만드는 레이아웃 정정뿐이다(제품 디자인 결정 아님).

```
src/components/SiteHeader.tsx   헤더 줄에 flex-wrap
                                우측 묶음 shrink-0 -> flex-wrap + min-w-0 + justify-end
src/components/PrimaryNav.tsx   nav 에 flex-wrap (글자 확대 대비 포함)
src/app/search/SearchPresets.tsx  inputClass 에 min-w-0
src/app/search/ResultList.tsx     카드 Link 에 min-w-0
src/app/favorites/page.tsx        카드 Link 에 min-w-0
src/app/properties/recent/page.tsx 카드 Link 에 min-w-0
```

### 2.4 재측정 — 전 화면 / 전 폭

```
화면                 320    360    390    430    900     1400
/search              0      0      0      0      0       0     REAL 넘침
/favorites           0                                          (열: 1 / 1 / 1 / 1 / 2 / 3)
/properties/recent   0
/properties/505      0
/mypage              0
페이지 가로 스크롤    없음   없음   없음   없음   없음    없음
grid 트랙(320)       257px = 컨테이너 257px (넘침 해소)
반응형 열            320~430 1열 / 900 2열 / 1400 3열  (그대로 동작)
이미지 디코드 실패    0
```

---

## 3. 이미지 / 문서 무결성 — 파일 존재가 아니라 **브라우저까지**

### 3.1 사진 45장 전수, 바이트 단위

```
DB 45행 -> 디스크 45개 -> API 45개 -> 브라우저 디코드 45개
바이트 완전 일치            45/45
매직바이트 <-> Content-Type  45/45  (jpg 40 image/jpeg, gif 5 image/gif)
매직바이트 <-> 확장자        45/45
ETag -> If-None-Match -> 304  45/45
고아 행 / 크기 불일치 / 경로-물건 불일치   0
```

#### 측정 도구가 두 번 거짓 결함을 냈다 (이 저장소의 함정 목록에 그대로 부합)

```
"JPEG 아님 5건"   -> 실제로는 **정상 GIF**(매직 47494638, 트레일러 3b).
                    내 검사가 JPEG SOI/EOI 만 봤다. 확장자도 .gif 로 맞다.
"ETag 없음"        -> `dict(r.headers)` 가 대소문자를 구분해 소문자 `etag` 를 놓쳤다.
                    curl 로 보면 ETag 도 304 도 정상.
```

둘 다 **코드 결함으로 단정하지 않고 도구부터 확인**해서 걸러냈다.

### 3.2 다른 물건 사진 혼입 — 없음 (그리고 '의심'도 이미 설명돼 있었다)

같은 사건의 물건 1/2 가 **바이트가 같은** 사진을 쓰는 경우가 2건(2025타경311, 2025타경939)
있었고, 수집 시각(2026-08-17)이 Sprint 230 고침(08-20)보다 **앞선다**. 오염을 의심할
근거가 되는 조합이다. 그러나 `test_asset_pipeline.py` 22번 검사의 docstring 이 이미
그 표본을 실측해 두었다 — *"같은 건물이라 법원이 같은 전경도를 준다"*. **결함이 아니다.**
서로 다른 **사건** 사이에 같은 바이트가 공유되는 경우는 0건이고, `file_hash` 드리프트도 0건이다.

### 3.3 `audit_asset_integrity.py` (운영 DB, 읽기 전용) — 어긋남 27건, 전부 정리 대상

```
[1] auction_image -> 파일        45행 / 없는 파일 0
[2] 디스크 <-> 순번 집합         어긋난 물건 0 / 고아 파일 0 / .tmp 잔재 0
[3] READY -> 필요한 파일         556개 / 모자란 것 0
[4] doc_raw -> 파일              556행 / 없는 파일 0 / READY인데 doc_raw 없음 0
[5] document_queue <-> status    어긋남 없음
[9] API 가 광고한 URL 이 열리는가 물건 206 / 사진 45 / 문서 556 / 열리지 않음 **0**

어긋남 27건 = 고아 큐 행 18(수집 시도 대상 12) + 고아 문서 폴더 1 + 고아 다운로드 8
-> 전부 **고아 데이터 정리 = 승인 영역**. 이번 세션에서 손대지 않았다.
```

---

## 4. 처리량 재측정 — **실제 큐 모양**으로 (추정 아님)

`doc_worker.main()` 을 그대로 돌린다. 브라우저와 수집기만 가짜고 **판단은 전부 제품
코드**가 한다. 큐는 fixture 의 사본(운영 무변경).

```
pending 2,753행 / 서로 다른 물건 944개 (물건당 3행이 903개)
실제 처리 대상 1,732행 (1,207행은 기일 경과로 정상 종결)

Sprint 236 이전 재현   상세페이지 이동 1,732회   이동비용 5.2시간
지금 (batching)        상세페이지 이동   579회   이동비용 1.8시간
                       -> 66.6% 감소, 약 3.5시간 절감
수집 건수              1,732 == 1,732   (batching 이 일을 빠뜨리지 않는다)
큐 최종                done 2,291 + SKIPPED_EXPIRED 1,207, pending 0
```

### ★ 첫 baseline 이 틀렸고, 그것을 고쳤다

처음에는 claim 만 행 단위로 되돌렸는데 **before 와 after 가 똑같이 579** 로 나왔다.
Sprint 236 이 넣은 것은 둘(물건 단위 claim + 페이지 기억)인데 하나만 껐기 때문이다
— claim 이 1행씩이어도 연속된 같은 물건의 행은 페이지 기억이 재사용해 버린다.
`_ensure_detail_page` 도 함께 우회해서야 충실한 1,732 baseline 이 나왔다.
(이동비용 10.9초는 Sprint 235 의 실측 중앙값이다. **실제 벽시계 시간은 실크롤이
필요해 이번에도 못 쟀다** — 추정치를 실측처럼 쓰지 않는다.)

### MAX_ITEMS 상향 — 지금은 **올릴 근거가 없다**

`test_worker_capacity.py` 실측 모델과 위 측정이 일치한다.

```
하루 능력      153건 (batching 전 78건 -> 1.97배)
실측 공급      중앙값 106건 / 최대 278건
MAX_ITEMS=10 x 법원 60 = 이론 최대 공급 600건/일  ->  능력 153건을 447건 초과
능력 안에 드는 MAX_ITEMS 상한 = 2
최대 공급일(278건)을 덮으려면 창 3.6시간 필요 (지금 2.0시간, 02:00~04:00)
```

**결론: 상향하지 않는다.** 지금 값 10 조차 이론 최대로는 능력을 넘는다(중앙값 공급은
감당한다). 상한 변경은 정책 결정이라 승인 영역이기도 하다.

---

## 5. Scheduler — 등록 직전까지 전부 검증

등록과 실크롤은 승인 영역이라 하지 않았다. 그 **앞 단계는 실제로 실행해서** 확인했다.

```
audit_schedule_health.py     이 저장소를 가리키는 작업 0개 (정의 3개 모두 미등록)
register_scheduler_tasks.ps1 (dry-run)  배치 3개 OK / PATH python 해석 OK
                             머신 PATH 불가 -> SYSTEM 등록 금지(그대로 유지)
```

### BAT -> Python 진입점을 **실제로 돌렸다**

지금 시각이 실행 창(02:00~04:00) 밖이라 브라우저를 띄우지 않고 끝나는 안전 경로다.

```
cmd /c .\run_doc_worker.bat
  exit code                0
  로그 마커                [SUCCESS] doc_worker.py finished at 2026-08-21 8:59:06
  창 가드                  "실행 창(04:00)이 이미 지났다 - 브라우저를 띄우지 않고 종료"
  lock                     생성 -> 정상 해제 (잔여 없음)
  DB                       접근 없음 (창 가드가 init_db 앞에 있다)
```

`logs/doc_run.log` 는 **정상 UTF-8** 이다(cp949 로는 디코드 실패). PowerShell 이
cp949 로 읽어 깨져 보였을 뿐 — 또 하나의 측정 도구 함정.

Queue/Retry/Recovery/Idempotency/Starvation 은 기존 스위트가 실제로 덮고 있다
(`test_doc_worker_recovery.py`, `test_race_conditions.py`, `test_refresh_trigger.py` 547단언,
`test_scheduler_longrun.py` 121단언, `test_worker_capacity.py` 22단언 — 전부 통과).

---

## 6. 마이리스트 내보내기 — **실제 API 응답**으로 검증

관심물건 3건을 브라우저에서 실제로 담고(운영 DB 아님, fixture 사본에만 기록됨 — 확인함),
제품의 진짜 `buildCsv`/`buildTsv` 에 그 응답을 그대로 통과시켰다. 다운로드는
일으키지 않았다.

```
헤더: 법원 | 사건번호 | 물건번호 | 물건종류 | 소재지 | 감정가 | 최저입찰가 | 매각기일 | 상태 | 유찰횟수

[PASS] 사건번호/법원/주소/기일/최저입찰가/감정가 6개 필드가 **원본 API 값과 정확히 일치** (불일치 0)
[PASS] 값 안의 쉼표(주소·물건종류 3행)가 파싱 후에도 한 칸으로 복원된다
[PASS] CRLF 줄바꿈 / UTF-8 BOM (한국어 Windows 엑셀 대비)
[PASS] TSV 전 행의 열 수가 헤더와 같다 (탭/개행 누출 없음)
[PASS] 복사 결과를 role="status" 로 알린다 ("3건을 복사했습니다")
       파일명 관심물건_2026-08-21.csv
전 16개 검사 통과
```

지지옥션/탱크옥션 전용 포맷은 **여전히 만들지 않는다** — 실제 입력 형식 확인이
승인 영역이고, 추측 구현은 "붙여넣었는데 안 들어간다"가 되며 그 실패는 우리 쪽에
보이지 않는다. `ExportButtons.tsx` 가 이미 그 판단을 문서화해 두었다.

---

## 7. API <-> Type <-> JSX 계약 — 실제 응답과 대조

정적 대조가 아니라 **살아 있는 API 응답**의 키 집합을 화면의 TS 선언과 맞췄다.

```
SearchResultItem      API 19 / TS 19   필수 누락 0 / 미선언 0
FavoriteItem          API 16 / TS 16   필수 누락 0 / 미선언 0
RecentItem            API 16 / TS 16   필수 누락 0 / 미선언 0
AuctionItemDetail     API 27 / TS 24   필수 누락 0 / 미선언 3 (dong, sido, sigungu)
AuctionImage          API  7 / TS  7   필수 누락 0 / 미선언 0
DocumentStatusItem    API  8 / TS  8   필수 누락 0 / 미선언 0
```

`dong/sido/sigungu` 는 상세가 `full_address` 를 쓰므로 **중복 필드**다(결함 아님, 기록만).

---

## 8. 접근성 — 실제 렌더/실제 키보드

```
/properties/505   h1 1개 / 랜드마크 header·nav·main / 이미지 6장 전부 alt / 접근이름 누락 0 (21개)
/search           포커스 가능 요소 74개, **접근이름 누락 0**
                  tabindex 양수 0개 (탭 순서 조작 없음)
                  전역 `outline: none` 0건
실제 Tab 키 3회   activeElement=BUTTON "로그아웃"
                  matches(':focus-visible') = true
                  outline: auto 1px rgb(153,161,175)  (브라우저 기본이 살아 있다)
```

색·크기·간격, 큰글씨 UI 최종 디자인은 **승인 영역이라 확정하지 않았다.**

---

## 9. 최종 상태

```
python run_python_tests.py   통과 47 | 실패 1 | 건너뜀 3 | 판정없음 1  (단언 7,133, 105.7s)
                             실패 1 = test_pipeline_integrity.py (§0 데이터 신선도 가드, 옳다)

node --test tests/**/*.test.mjs
  운영 데이터(API :8000, 기일 전부 경과)   143개 중 139 PASS / 1 FAIL / 3 SKIP
      FAIL 1건 = "기본 검색에 판정 가능한 물건이 있다 (다른 검사의 전제)"  <- §0 그 하나
      SKIP 3건 = 그 전제에 매달린 검사들
  fixture 데이터(날짜 +30일, 같은 코드)     같은 스위트가 **전부 통과**
      -> FAIL/SKIP 4건이 코드가 아니라 **데이터 신선도** 때문임을 이 대비가 증명한다

기준선(수정 전) 137개 중 133 PASS -> 지금 143개 중 139 PASS (신설 6개 전부 통과)

tsc --noEmit                 0
eslint                       0
git diff --stat              8 files changed, 355 insertions(+), 9 deletions(-)
                             + docs/SPRINT240_*.md (신규, 미추적)
```

### 이번 세션이 새로 넣은 검사 (전부 mutation 으로 검증)

```
test_worker_batching.py                  13번 신설 (+51 단언). MUT3 를 5개 단언이 잡는다.
tests/source-contract.test.mjs  Sprint 240 좁은 폭 3검사 + 카드 min-w-0 3검사
                                6개 mutation(고침을 되돌리는 편집) 전부 잡힘 확인
```

---

## 10. 승인으로 SKIP 한 것

```
1. 실제 법원 크롤 재개            <- Release Blocker 의 원인, 이것만이 §0 을 푼다
2. 스케줄러 실제 등록 (3작업)
3. 고아 데이터 정리 (큐 18행 / 문서 폴더 1 / 다운로드 8건 = 어긋남 27)
4. 운영 DB 변경 / 데이터 삭제
5. .env / Secret 변경
6. 지지옥션·탱크옥션 실제 입력 포맷 확인
7. 제품 디자인 확정 / 큰글씨 UI 최종 디자인
8. 모바일 실기기 검증
9. git add / commit / push
```

## 11. Release Blocker

```
[P0] 크롤 정지 -> 앞으로 기일이 남은 물건 0건 -> 기본 검색이 빈 화면
     (코드는 정상. 데이터 신선도만의 문제이며 fixture 로 137/137 PASS 로 증명했다)
```

그 외 P0 없음. 이번 세션이 고친 좁은 폭 3종은 베타 모바일 사용성 관점의 실사용 결함이었다.

## 12. 남은 Backlog / 다음 Sprint 후보

```
A. 다른 상수 스텁도 mutation 으로 훑기
   `wait_for_detail` 처럼 harness 가 True 로 박아 둔 것이 더 있는지.
   이번에 그 방식으로 실제 공백을 하나 찾았으므로 값어치가 증명됐다.
B. window.open 320px 측정을 스크립트로 고정
   이번에 얻은 측정 수단(§2.1 b)을 재사용 가능한 형태로 남기면 좁은 폭이
   매번 수동 작업이 되지 않는다. (CI 에는 브라우저가 없으므로 소스 계약과 병행)
C. 고아 큐 18행이 워커 시간을 먹는다 (승인 후 cleanup_orphans_dryrun.py --apply)
D. 큐에 image 종류가 0행 — 기존 2,753행은 image 추가 **전에** 적재됐다.
   새로 적재되는 물건부터 4종이 되어 물건당 이동/비용이 늘어난다(능력 모델은 이미 4종 기준).
E. 상세 응답의 중복 필드 dong/sido/sigungu 정리 여부 판단
```
