# Sprint 244 — 체크리스트의 P0 3건이 이미 해소돼 있었고, "선언된 필터가 거르지 않는" 구멍을 막았다

**날짜** 2026-08-21. HEAD `9c1f8ed` / branch `master` / **커밋·푸시 없음**.
운영 `auction.db` 무변경(읽기 전용) / `.env` 무변경 / 스케줄러 등록 없음 / 실크롤 없음.

---

## 0. 기준선 — 이번 세션 실측

```
auction_item 1,876 / 기일 미래 **0건** / crawl_date 최신 2026-08-12
auction_image 45 / doc_raw 556
document_status  COLLECTING 5,069 / READY 556 / FAILED 3   (doc_type = SPEC·STATUS·APPRAISAL 각 1,876, IMAGE 0)
document_queue   pending 2,753 / done 559 / SKIPPED_EXPIRED 186  (doc_type = spec·status·appraisal 각 1,166, image 0)
favorites 0 / recent_items 36
스케줄러 이 저장소를 가리키는 등록 작업 **0개**

python  통과 48 | 실패 1 | 건너뜀 3 | 판정없음 1  (단언 7,566)
node    150개 중 146 PASS / 1 FAIL / 3 SKIP
tsc 0 / eslint 0
```

---

## 1. ★ Release Checklist P0 전수 재검증 — **3건이 이미 해소돼 있었다**

체크리스트를 문서로 읽지 않고 **하나씩 실행해서** 확인했다.

| 항목 | 문서 | 실측 결과 | 판정 |
|---|---|---|---|
| P0-A 데이터 공급 정지 | P0 | 등록 작업 0개 / 기일 남은 물건 0건 | **P0 유지** |
| P0-B 커밋 시 API 부팅 불가 | P0 | `import api_server` 성공, OpenAPI 엔드포인트 42개 | **해소** |
| P0-C migration 020 누락 → 500 | P0 | `auction_image` 존재(45행), `migration_history` 에 020 기록 | **해소** |
| P0-2 ADMIN 키 없음 | P0 | 키 2개 모두 없음, admin 5종 호출 전부 **500 `관리자 키 미설정`** | **유지**(등급 재분류 제안) |
| P0-3 Supabase Redirect URL | P0 | 외부 콘솔 = 승인 영역 | **보류** |
| P0-4 `SUPABASE_JWT_SECRET` 없음 | P0 | **설정돼 있다**(88자) | **해소** |

세 건이 P0로 남아 있으면 "무엇이 출시를 막는가"를 이 문서로 판단할 수 없다.
`docs/BETA_RELEASE_CHECKLIST.md` 머리에 실측 표를 넣어 정정했다(기존 본문은 건드리지 않았다).

### 곁가지 실측 — `.env` 의 두 값이 **비어 있다** (동작은 정상)

```
SUPABASE_URL        = (빈 값)
SUPABASE_ANON_KEY   = (빈 값)
SUPABASE_JWT_SECRET = 88자
```

그런데 인증은 멀쩡하다. `api/auth.py` 가 `SUPABASE_URL` 이 비면 `.env.local` 의
`NEXT_PUBLIC_SUPABASE_URL` 로 폴백하도록 이미 만들어져 있고, **런타임에서 실제로 그 값이
해석되는 것**을 확인했다(JWKS URL 생성 가능 = ES256 검증 경로 살아 있음).
빈 두 줄은 오해를 부르지만 동작을 깨뜨리지 않는다. `.env` 수정은 승인 영역이라 두었다.

### P0-2 등급 재분류 제안(확정하지 않음)

admin 500 은 사실이다. 다만 베타의 핵심 동선은 검색→목록→상세→사진/문서→관심물건/최근본→
마이리스트이고, admin 16개 라우트는 **웹 UI 자체가 없는 운영자 도구**다(§2 연결 감사).
따라서 "출시 차단(P0)"보다 "출시 후 운영 불가(P1)"가 정확하다. 등급 확정은 제품 판단이라
근거만 남겼다.

---

## 2. API ↔ UI 연결 감사 — 깨진 연결 0건

```
백엔드 엔드포인트                 42개 (경로 38종)
프런트가 참조하는 경로             16종
★ 프런트가 부르는데 백엔드에 없는 것   0건
★ 핸들러 없는 <button>              0건
★ 빈 핸들러 `() => {}`              0건
백엔드에만 있고 프런트 미사용        admin 16 + 운영/서버간 5
   (`/`, `/api/v1/stats`, `/api/v1/document-stats`,
    `/api/v1/payments/webhook/{provider}`, `/api/v1/payments/{id}/logs`)
```

즉 **"UI 는 있는데 백엔드가 없다" / "버튼이 아무 동작도 안 한다" 유형은 0건**이다.

### ★ 감사 도구가 두 번 거짓 결함을 냈다

```
(1) 템플릿 리터럴 `${id}` 정규화에서 `$` 가 남아 `/api/v1/item` 이 "백엔드에 없음"으로 나왔다
    -> 실제로는 `/api/v1/item/{item_id}` 와 같은 것이다.
(2) `<button([^>]*)>` 정규식이 속성 안의 `>=`(`currentPage >= totalPages`)에서 끊겨
    Pagination 의 버튼이 "onClick 없음"으로 나왔다 -> 실제로는 둘 다 onClick 이 있다.
```

둘 다 코드 결함으로 단정하기 전에 도구를 확인해서 걸렀다.

---

## 3. ★ "선언된 필터가 실제로 거르는가" — 새 검사로 구멍을 막았다

### 발견

프런트는 면적(건물/토지)과 특수조건 필터 UI 를 갖고 있고 값을 **실제로 보낸다.**
백엔드는 그것을 받지 않는다. 2026-08-21 실측(fixture 830건):

```
기준(필터 없음)                    total=830
min_building_area=1000            total=830   ** 무시됨 **
max_building_area=1               total=830   ** 무시됨 **
min_land_area=99999               total=830   ** 무시됨 **
special_conditions=X              total=830   ** 무시됨 **
min_appraisal=1e15 (지원되는 필터)  total=0     정상 동작
```

즉 사용자가 "건물면적 1000㎡ 이상"을 걸어도 19㎡ 빌라가 그대로 나온다.
**화면은 필터가 걸린 것처럼 보인다.**

### 구현은 못 한다(승인·범위 밖) — 그러나 **검사의 구멍**은 막을 수 있었다

`auction_item` 에 면적 컬럼이 없어 백엔드 구현은 새 스키마/파싱이 필요하고,
UI 를 숨기거나 안내를 넣는 것은 문구·디자인 결정이다. 둘 다 이번 범위 밖이다.

대신 **검사가 이 상태를 놓칠 수 있는 구멍**을 mutation 으로 찾아 막았다.

```
mutation 1단계  `min_building_area: float = Query(None)` 을 **선언만** 추가(WHERE 절 없음)
                -> source-contract 가 "미지원 목록에 있는데 백엔드가 지원한다"고 실패 (잡힘)
mutation 2단계  개발자가 자연스럽게 source-contract 의 KNOWN_UNSUPPORTED 에서 그 이름을 뺀다
                -> **소스 검사 36건 전부 통과.** 그런데 실제 동작은 830 -> 830, 아무것도 안 거른다.
```

즉 "선언했다"와 "거른다"는 다른 사실인데 소스 검사는 앞의 것만 본다.

### 신설: `test_search.py:check_declared_filters_actually_filter()`

`Query(...)` 로 선언된 필터를 전부 뽑아 **극단값을 실제로 보내고 결과 수가 달라지는지** 센다.

```
선언된 필터 18개 (표시 설정 sort_by/sort_order/page/size 제외)
극단값에도 결과가 그대로인 것: 0개   <- 전부 실제로 거른다
프런트가 보내는데 백엔드가 안 받는 것: 5개 (면적 4 + 특수조건 1) — 이 사실을 고정한다
```

미지원 목록은 **여기서 새로 적지 않는다** — `tests/source-contract.test.mjs` 의
`KNOWN_UNSUPPORTED` 를 읽어 온다. 두 벌로 두면 한쪽만 갱신되는 날 두 검사가 서로를
눈감아 준다(이 저장소가 BUGS #107/#112/#136/#161 에서 반복해 겪은 모양).

### ★ 내 검사가 정말 값어치가 있는지 따로 확인했다

처음 mutation 에서 신설 검사가 잡히길래 "구멍을 막았다"고 볼 뻔했는데,
**원본 `test_search.py` 도 같은 mutation 을 이미 잡고 있었다**(exit 1).
그래서 기존 검사가 못 잡는 시나리오를 따로 만들어 다시 쟀다 —
**새 필터를 백엔드에 선언하고 프런트도 보내는데 WHERE 절만 없는** 경우:

```
source-contract      -> 1 (잡음)
원본 test_search     -> **0 (놓침)**
신설 test_search     -> 1 (잡음)
   "EXTREME 에 없다 - 새 파라미터가 생겼으면 여기에 추가하라"
```

즉 신설 검사는 **새로 추가된 미배선 필터**를 잡는다. 기존 검사가 덮는 범위와 겹치는
부분이 있다는 사실도 함께 기록한다(중복을 숨기지 않는다).

---

## 4. COLLECTING 잔존 — 기존 판단이 여전히 옳다는 것을 독립 측정으로 확인

```
document_status COLLECTING           5,069행
  큐에 대응 행이 있는 것              2,924행 (정상, 처리 대기)
  ★ 큐에 대응 행이 **없는** 것        2,145행 (715 물건)
       그중 기일 경과                2,145행 (100%)
```

화면에서 영원히 "수집중"으로 남는다. **새 결함이 아니다** —
`storage/database.py:mark_queue_skipped_expired()` 의 주석이 이 수치(2,145)와 두 원인
((a) 큐가 SKIPPED_EXPIRED 로 종결 183건, (b) 애초에 큐에 안 들어감 2,145건)을 이미
기록해 두었고, "`document_status` 에 '대상 아님' 상태가 없어 새 상태를 만드는 것은
상태머신·화면 문구 결정 = 제품 판단"이라 **의도적으로 보류**한 항목이다.
이번 독립 측정이 그 숫자와 정확히 일치했다(문서가 최신임을 확인).

그 보류가 조용히 풀리지 않는지도 mutation 으로 확인했다 —
`mark_queue_skipped_expired()` 가 `document_status` 를 건드리도록 배선하면
`test_document_status_sync.py` 와 `test_pipeline_integrity.py` 가 **둘 다 실패한다.**

### 같은 계열 — 사진 쪽은 지금 **1,867 물건**이 "사진 수집 중"이다

```
document_status 의 IMAGE 행: 0개
사진을 가진 물건: 9 / 전체 1,876
_images_status([], 0) 실제 호출 결과 -> "COLLECTING"
=> 사진 없는 1,867 물건 전부가 화면에 "사진 수집 중입니다"
   그런데 image 큐 행도 0개라 아무도 수집하지 않는다
```

문서 쪽과 같은 구조이며, **크롤이 재개되면 image 큐가 적재되어 자연히 해소**된다
(Sprint 243 에서 전환 경로를 검증했다). 상태 문구를 새로 만드는 것은 같은 제품 판단이라
이번에도 손대지 않았다.

---

## 5. 성능 감사 — 현재 규모에서 문제 없음

`TestClient` 기준(네트워크 제외 = 서버 처리시간), fixture DB(기일 미래 830건):

```
GET /api/v1/search?size=20                p50 3.2ms   p90 3.3ms   total=830
GET /api/v1/search?size=100               p50 5.3ms   p90 5.4ms
GET /api/v1/search?sido=서울&size=20        p50 3.4ms   p90 3.6ms   total=139
GET /api/v1/search?page=20                p50 3.8ms   p90 4.0ms
GET /api/v1/search?sort=감정가             p50 3.3ms   p90 3.4ms
GET /api/v1/item/505 (사진 5장)            p50 2.8ms   p90 2.9ms
GET /api/v1/item/505/images/1             p50 3.6ms   p90 4.0ms
```

N+1 없음(상세는 물건당 고정 쿼리 수 — `test_asset_pipeline.py` 가 별도로 잠근다),
페이지 깊이에 따른 열화 없음. **현재 데이터 규모에서 성능은 Release 관심사가 아니다.**

---

## 6. 최종 상태

```
python run_python_tests.py   통과 48 | 실패 1 | 건너뜀 3 | 판정없음 1  (단언 7,566 -> **7,596**)
                             실패 1 = test_pipeline_integrity.py (기일 남은 물건 0건 가드)
node --test                  150개 / 146 PASS / 1 FAIL / 3 SKIP
tsc 0 / eslint 0
```

### ★ node 결과를 한 번 잘못 읽을 뻔했다

서버를 내린 상태로 돌렸더니 `pass 99 / fail 0` 이 나왔다. 합이 150 이 아니다 —
**51건이 cancelled** 였다(frontend-contract 의 `before()` 가 서버 없음을 감지해 그 파일을
통째로 취소한다). "실패 0"만 보고 통과로 셀 뻔했다. 서버를 올리고 다시 재서 146/1/3 을 얻었다.

---

## 7. 승인으로 SKIP

```
1. 실크롤 재개 / 스케줄러 등록      <- 유일한 실질 P0(P0-A)의 해소 수단
2. `.env` 수정 (ADMIN_API_KEY / SUPER_ADMIN_API_KEY, 빈 SUPABASE_URL 정리)
3. 운영 DB 변경 (COLLECTING 2,145행 정리 등)
4. `document_status` 에 "대상 아님" 상태 신설 (상태머신·화면 문구 = 제품 판단)
5. 면적/특수조건 필터 UI 처리 (숨김/안내/비활성 = 디자인·문구 결정)
6. 면적 필터 백엔드 구현 (스키마 추가 필요)
7. 결제 실연동(P0-1) / Supabase Redirect URL 확인(P0-3)
8. MAX_ITEMS 정책 변경 / 실행시간 변경
9. git add / commit / push
```

## 8. Release Blocker

```
[P0] 크롤 정지 -> 기일 남은 물건 0건 -> 기본 검색이 빈 화면   (P0-A, 승인 영역)
```

문서가 P0 로 올려 둔 나머지 3건(P0-B/P0-C/P0-4)은 **이번 실측으로 해소 확인**했고,
P0-2(admin 키)는 운영자 도구 범위라 베타 사용자 동선을 막지 않는다.

## 9. 남은 Backlog / 다음 Sprint

```
A. 면적/특수조건 필터 — 셋 중 하나를 제품이 골라야 한다
   (1) 백엔드 구현(스키마 추가) (2) UI 에서 숨김 (3) "미지원" 안내
   지금은 사용자가 필터를 걸어도 아무 일도 일어나지 않는다(§3).
B. `document_status` 의 "대상 아님" 상태 — 문서 2,145행 + 사진 1,867물건이 걸려 있다(§4).
   크롤 재개 시 사진 쪽은 자연 해소되지만 기일 경과 문서는 남는다.
C. `audit_viewport.py --cookie` 로 로그인 화면 24칸 실측(Sprint 242 미완).
D. `audit_test_reality.py` 의 "60줄 미만" 3개 검사를 mutation 으로 마저 판정(Sprint 242 미완).
E. 크롤 재개 후 image 4종 체제의 실벽시계 처리량 재측정(Sprint 243 §2 산술의 검증).
```
