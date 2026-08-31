# Sprint 273 — 표시 계약(로케일·시간대·면적)과 **공허한 보증** 정리 (2026-08-31)

> 앞 Sprint: `docs/SPRINT270_MYLIST_IMPORT.md`(가져오기), Sprint 271/272(`docs/CURRENT_STATE.md`)
>
> **별도 파일 이유**: Sprint 100~255 와 같다 — `docs/BUGS.md` / `docs/CURRENT_STATE.md` 는
> 다른 세션의 편집 대상이라 충돌을 피했다.

이 세션은 기능을 만들지 않았다. **정책은 이미 있는데 코드가 그 정책을 다르게 구현하거나,
지킨다고 적어 두고 지키지 않던 자리**만 찾아 닫았다. 새 정책을 만든 곳은 없다.

---

## 요약

| # | 무엇 | 종류 | 사용자 영향 |
|---|---|---|---|
| 1 | 금액·건수 표기가 **보는 사람의 브라우저 로케일**을 따랐다 | 결함 | de-DE 브라우저에서 `12,900원` -> `12.900원` |
| 2 | 청구 금액 표기가 **두 곳에 따로** 구현돼 있었다 | Frankenstein | 로케일 고정이 한쪽에만 들어갈 뻔했다 |
| 3 | D-day 의 "오늘"이 **브라우저 시계** 기준이었다 | 결함 | 비 KST 브라우저에서 하루 어긋남 |
| 4 | 카드 면적이 **필터가 쓰는 값과 다른 경로**로 계산됐다 | Frankenstein | '평' 표기 7건: 걸러 놓고 카드는 빈 칸 |
| 5 | 가장 최근 화면이 **구 브랜드명**을 노출 | 정책 위반 | "도준패스" 2곳 |
| 6 | `property_type` 을 존재한 적 없는 ENUM 으로 서술 | 거짓 문서 | 그 문장대로 짜면 조회 0건 |
| 7 | `types.ts` 가 **이미 구현된 필터**를 미지원이라고 서술 | 문서 드리프트 | 믿으면 실동작 필터를 지운다 |
| 8 | 주석이 **존재하지 않는 검사 파일**을 가리켰다 (2곳) | 공허한 보증 | 지키는 것이 없는데 지킨다고 읽힌다 |
| 9 | `/properties` 관련 서술이 3개 문서에서 stale | 문서 드리프트 | 없는 화면을 있다고 읽는다 |
| 10 | 최저가율 퍼센트 계산이 **두 곳에 따로**, 한쪽엔 값없음 가드가 없었다 | Frankenstein | 값이 없으면 상세가 `0.0%` 를 지어낸다 |
| 11 | `document_queue.status` 여덟 값 중 **둘만 상수가 없었다** | 어휘 분열 | SQL 오타가 예외가 아니라 0행 매치 |
| 12 | 화면 간 사진 일관성 서술이 stale(이미 해소됨) | 문서 드리프트 | 있는 기능을 다시 만들게 된다 |
| 13 | **응답에는 있는데 프런트 타입에 없는 키** 7개 | API 계약 드리프트 | "없는 데이터"로 읽혀 같은 것을 다시 만든다 |
| 14 | `document_status` 열거형에 **NO_IMAGE 가 없었다** | 상태 체계 누락 | DB·수집기·API·화면이 아는 값을 정의만 몰랐다 |
| 15 | BUGS #268 이 **없는 검사 두 벌**을 근거로 "해결" | 공허한 보증 | DB 쓰기 장애 거동이 실제로는 미검증 |
| 16 | 결제·등기부·문서 상태값이 **SQL 문자열에 박혀** 있었다 (3곳) | 어휘 분열 | 오타가 예외 아닌 0행 매치 |
| 17 | 문서가 **없는 함수/상수**를 이관 지시·완료 근거로 인용 (2건) | 공허한 보증 | 그 지시를 따르면 없는 것을 찾게 된다 |
| 18 | 출시 차단 문서가 **이미 있는 엔드포인트**를 "신규 구현 필요"로 적었다 | 문서 드리프트 | 남은 일의 크기를 과대평가 |
| 19 | 인증 필요 응답의 `note_source` 가 프런트 타입에 없었다 | API 계약 드리프트 | "응답에 없다"로 읽힌다 |
| 20 | 검사 실효성 도구와 실행기가 **충돌 사본을 다르게 취급** | 도구 간 불일치 | 멀쩡한 검사를 의심 목록에 올린다 |
| 21 | 마이페이지 3종 응답의 미선언 키 9개가 **아무 검사에도 안 걸림** | 계약 공백 | 조용히 늘어난다 |
| 22 | `audit_contrast.py` 가 **없는 속성**(`AV.DriverUnavailable`)을 참조 — 실패 사유가 가려진다 | 도구 파손 | 브라우저 못 띄우면 트레이스백 |

전부 **오류도 로그도 남기지 않는** 부류다. 실행해서는 드러나지 않아 소스/데이터 대조로만 잡힌다.

---

## 1. 표시 로케일 — `toLocaleString()` 에 로케일이 없었다

### 실측

```
(12900).toLocaleString('de-DE')  ->  "12.900"      한국식으로 읽으면 12.9
(12900).toLocaleString('ko-KR')  ->  "12,900"
(12900).toLocaleString()         ->  환경이 정한다
```

인자 없는 호출이 `src/` 에 **10곳**이었고 그중 **5곳이 실제 청구 금액**이었다
(구독 카드 정상가/판매가, 구독하기 버튼, 초과결제 안내/버튼).

이 저장소는 **날짜에서는 이미 로케일을 고정하고 있었다** —
`favorites/page.tsx` · `properties/recent/page.tsx` · `mypage/page.tsx` 세 곳 모두
`toLocaleDateString('ko-KR')`. 숫자만 빠져 **같은 관심사에 규칙이 둘**이었다.

### 고친 것

`src/lib/format.ts` 에 `DISPLAY_LOCALE = 'ko-KR'` 과 `formatNumber()` 를 두고,
`formatWon()` 이 그 위에서 만들어지게 했다. 호출부 10곳을 전부 옮겼다.

**ko-KR / en-US 사용자가 보는 문자열은 한 글자도 바뀌지 않는다**(둘 다 쉼표 3자리).

새 정책이 아니다 — 이미 있던 규칙(ko-KR 고정)을 숫자에도 적용했다.
제품은 한국어 전용이다(`src/app/layout.tsx` 의 `lang="ko"`).

---

## 2. 청구 금액 표기의 중복 구현

`src/lib/format.ts` 의 주석이 이렇게 적고 있었다.

> 구독 카드가 이미 `price.toLocaleString() + '원'` 으로 정확히 표시하고 있어서 …

**그 문장이 곧 중복이었다.** Sprint 54 가 상세 페이지의 지역 `formatWon` 을 지우고 공용으로
옮겼을 때, 구독/초과결제 **5곳**은 함께 옮겨지지 않고 손으로 `+ '원'` 을 다시 적고 있었다.
`tests/source-contract.test.mjs` 가 "상세에 `function formatWon` 지역 사본이 없다"만
보고 있어 **함수를 다시 만들지 않고 인라인으로 적는 것**은 잡히지 않았다.

호출부를 `formatWon()` 으로 모으고, 소스 계약을 인라인 형태까지 잡도록 넓혔다.

---

## 3. D-day 의 "오늘" — 두 곳에서 따로 계산되고 있었다

```
백엔드  api/v1/search.py   auction_date >= date.today()    서버 로컬 시각
프런트  formatDday()       new Date() 로 로컬 자정          보는 사람의 시계
```

이 저장소가 선언한 시각 기준은 **한국 로컬 시각**이다
(`storage/database.py` 의 `_NOW_LOCAL` 주석 — "한국(UTC+9)에서 실측한 결과가 이렇다").
서버는 한국에서 도는데 브라우저는 아무 데서나 돈다. 자정 부근에서
UTC-05:00 브라우저는 목록에 남아 있는 물건을 "1일 경과"로, UTC+13:00 은 하루 일찍 D-Day 로 보였다.

### 고친 것

`formatDday()` 를 `src/app/search/ResultList.tsx`(JSX) 에서 `src/lib/format.ts` 로 옮기고
`DISPLAY_TIME_ZONE = 'Asia/Seoul'` 기준으로 계산하게 했다. `parseArea` 를 옮겼을 때와 같은 이유다 —

1. `.tsx` 는 Node 타입 스트리핑으로 import 할 수 없어 **동작 테스트를 붙일 수 없었다**
   (카드와 상세 배지에 매번 찍히는 값인데 계약이 하나도 고정돼 있지 않았다)
2. 상세 페이지가 **다른 라우트의 컴포넌트 파일에서** 유틸을 가져오는 계층 우회가 있었다

**백엔드는 그대로 둔다.** `date.today()`(서버 로컬)는 이 저장소의 명시적 규약이고,
서버가 어느 시간대에서 도는가는 배포 결정(승인 영역)이다. 여기서 맞춘 것은
**클라이언트가 서버와 같은 날짜를 보게 하는 것**뿐이다.

회귀: 자정 경계(±1초), 윤년/월말, UTC-05:00 / UTC+13:00 대조. 변이 4/4 검출.

---

## 4. 카드 면적이 필터와 다른 경로로 계산됐다

면적 규칙이 두 곳에 있다.

```
백엔드  normalizer.extract_areas()  ->  auction_item.building_area / land_area
        = 검색 **필터**가 쓰는 값 (migration 025, api/v1/search.py 의 WHERE)
프런트  parseArea(full_address)     ->  검색 카드에 **표시**하는 값
```

둘 다 같은 원문에서 읽지만 구현이 다르다. 이 저장소는 이미 한 번 데였다 —
천단위 쉼표를 백엔드는 읽고 프런트는 못 읽어 3,005.35㎡ 가 카드에 5.35㎡ 로 찍혔다(BUGS #240).

### 실측 (auction.db 1,876행 전수, 두 구현을 나란히 실행)

```
라벨 불일치      0건
값 불일치        0건
프런트만 값      0건
백엔드만 값      7건   <- 단위가 '평'인 주소. 백엔드는 ㎡ 로 환산하고 프런트는 못 읽는다
```

```
[토지 전 1048평]   백엔드 land_area 3464.46㎡   프런트 표시 없음
```

즉 **면적 조건으로 걸러 놓고 그 카드에는 면적이 비어 있었다.** 필터와 표시가 다른 사실을 말한다.

### 고친 것

`displayArea()` 가 **서버 값을 먼저** 쓰고, 없으면 `parseArea()` 로 폴백한다.
`SearchResultItem` 타입에 `building_area` / `land_area` 를 추가했다 —
**응답에는 2026-08-26 부터 실려 있었는데 타입에만 없었다.**

폴백을 남긴 이유: migration 025 이전 스키마에서는 서버가 null 을 준다(이 개발 머신이 그렇다).
그때 카드가 갑자기 비면 오히려 퇴행이다.

**한계를 정직하게 적는다** — 폴백이 남아 있는 한 두 구현은 계속 공존한다. 그것을 없애려면
"면적 컬럼이 항상 채워져 있다"를 전제해야 하고, 그 전제는 운영 DB 마이그레이션 상태에
달려 있어(승인 영역) 여기서 세우지 않았다.

---

## 5. 가장 최근 화면이 구 브랜드명을 노출하고 있었다

```
docs/decision-log.md "Service Name"      서비스명은 "콕찰"
docs/frontend.md "절대 변경하면 안 되는 것"  "도준패스"/"도준 경매 패스" 사용 금지
```

2026-08-28 Sprint 270 에 추가된 마이리스트 가져오기 화면이 사용자에게 **"도준패스"를 두 번**
보여주고 있었다(`src/app/favorites/import/page.tsx:245,421`). 나머지 화면은 전부 "콕찰"이다.

즉 정책이 없어서가 아니라 **정책을 확인하지 않고 새 화면을 만들어서** 갈라졌다.
문구를 고치고, 문서에만 있던 규칙을 소스 계약으로 옮겼다(주석은 제외하고 **화면 문구만** 본다).

---

## 6. `property_type` — 존재한 적 없는 ENUM

```
storage/migrate_v4_1.py:13   "APARTMENT / OFFICETEL / LAND / FACTORY / COMMERCIAL / MULTI_FAMILY"
docs/backend.md 주의사항       같은 문장
```

**그 값을 쓰는 행은 0건**이고 저장소 어느 소스도 그 문자열을 만들지 않는다.
실제로는 법원 표기 그대로의 한국어 자유 문자열이며 콤마 복합값이 있다(2026-08-31 실측 18종).

이 문장을 믿고 `property_type='APARTMENT'` 로 필터를 짜면 **오류 없이 그냥 0건**이 나온다.
BUGS #33 이 발견까지 오래 걸렸던 실패 모양 그대로다.

### 검사를 어떻게 걸었나 — 산문을 읽지 않고 **표를 DB 와 대조한다**

처음에는 "정정 표시가 근처에 있는가"로 판정하려 했는데 **변이 2건이 그대로 통과했다**
(정정문 안에 있는 단어를 escape hatch 로 쓰면 어떤 규칙도 우회된다).
그래서 두 파일에 기계가 읽는 표(`[VOCAB-TABLE]`)를 두고 **거기 적힌 어휘가 실제 DB 에
존재하는지**를 본다. 지어낸 어휘를 적으면 잡히고, 표를 지우면 커버리지 단언이 잡는다.

**한계**: 표를 정확히 둔 채 다른 문단에서 ENUM 을 다시 주장하는 것까지는 기계가 판별하지
못한다. 그 경우를 위해 옛 문장을 **그대로** 되붙이는 것만 따로 막는다(취소선으로 감싼
사료는 통과 — 취소선은 산문이 아니라 표기라 기계가 가를 수 있다).

변이 5/5 검출.

---

## 7. `types.ts` 가 이미 구현된 필터를 "미지원"이라고 적고 있었다

2026-08-26 에 면적 4종이 구현되면서 `SearchForm.tsx` 와
`tests/_search_param_contract.mjs`(미지원 정본)는 갱신됐는데
`src/app/search/types.ts` 만 **"아래 4개 필드는 백엔드가 읽지 않는다"**를 유지하고 있었다.

타입도 맞고 검색도 잘 돌기 때문에 실행으로는 드러나지 않는다. 드러나는 순간은 누군가
그 주석을 믿고 **"죽은 파라미터니 지우자"**로 갈 때이고, 그때 실동작 필터가 사라진다.

주석을 정정하고, "백엔드가 지원하는 파라미터를 미지원으로 서술하지 않는다"를 소스 계약으로
고정했다. 여기서도 **인용/취소선 표기**로 사료와 살아 있는 주장을 갈랐다.

---

## 8. 주석이 **존재하지 않는 검사 파일**을 가리켰다

저장소 전체(추적 파일 `.py/.ts/.tsx/.mjs`)에서 검사 파일 인용 **286건**을 훑었다.
살아 있지 않은 대상은 6종이고, 그중 4종은 `test_runner_contract.py` 가 **실행 중에 만드는**
임시 파일 이름(`test_zz*`)이라 정상이다. 남은 2건이 진짜였다.

| 인용한 곳 | 가리킨 파일 | 실제 |
|---|---|---|
| `normalizer/mylist_import.py:91` | tests/ 아래 `.mjs` 계약 파일 | 존재한 적 없음. **보증은 처음부터 `test_favorite_import.py` §13 이 하고 있었다** |
| `crawler/doc_crawler.py:57` | `test_doc_pdf_iframe.py` | 존재한 적 없음. **그 함수는 한 줄도 실행된 적이 없었다** |

### 8-1. 인용을 고치고, 대신 **원래 검사를 강화**했다

`test_favorite_import.py` §13 은 열 이름이 **있는지**만 봤다. `"법원": "case_no"` 처럼
잘못 매핑돼도 이름은 그대로 있어서 통과하면서 되붙이기만 조용히 틀린다.
의도한 필드까지 못박고, 되붙이기에서 법원·소재지가 실제로 살아 오는지 확인하고,
"이 모듈의 주석이 가리키는 검사 파일이 실재하는가"를 같은 자리에 넣었다.

**새 `.mjs` 계약 파일을 만들었다가 지웠다** — 같은 짝을 두 벌 검사하게 되고, 그것이
이 저장소가 `_search_param_contract.mjs` 로 경계해 온 바로 그 모양이기 때문이다.

### 8-2. `_pdf_iframe_src()` 에 회귀를 붙였다 (`test_doc_pdf_iframe.py` 신설)

docstring 이 "브라우저 없이 검증할 수 있게 하려고 함수로 뺐다"고 적어 두고 검증은 없었다.
이 함수의 계약은 두 겹이고 둘 다 깨져도 증상은 "문서를 못 받는다"뿐이다.

```
1. 아직 준비되지 않았으면 반드시 None   (""/False 를 주면 WebDriverWait 폴링 계약이 깨진다)
2. 폴링 중 DOM 교체(stale element)·드라이버 예외에 죽지 않는다
```

가짜 드라이버로 늦게 채워지는 src(BUGS #267 이 고친 그 상황), 대문자 확장자,
쿼리스트링(현재 계약상 잡지 못한다 — 알려진 한계를 그대로 못박음), 예외 격리를 검증한다.
변이 4/4 검출.

---

## 9. `/properties` 관련 stale 서술 정정

`/properties` 는 2026-08-11 Sprint 51 에 `redirect('/')` 한 줄이 됐고 `SearchFilters.tsx` 는
삭제됐다. `docs/BETA_RELEASE_CHECKLIST.md` 는 2026-08-22 에 이미 해소로 적었는데
`docs/frontend.md`(5건) · `docs/architecture.md`(2건) 는 갱신되지 않아, 지금도
**Supabase 직접 조회 화면이 남아 있는 것처럼** 읽혔다.

2026-08-31 실측: `src/app/properties/` 아래는 `page.tsx`(redirect) / `LogoutButton.tsx` /
`[id]/` / `recent/` 뿐이고, 화면에서 Supabase 데이터 테이블을 조회하는 곳은 **0건**이다
(`tests/supabase-boundary.test.mjs` 가 이미 회귀로 고정하고 있다).
사료는 지우지 않고 취소선 + 정정으로 남겼다.

---

## 검증

```
npx tsc --noEmit                exit 0
npx eslint .                    exit 0
npm run test:frontend           280 tests / 276 pass / 0 fail / 4 skip   (dev 서버 + API 서버 기동 상태)
                                (서버 없이 돌리면 218 pass / 0 fail / 57 cancelled — 종전과 같은 구조)
python run_python_tests.py      통과 62 | 실패 4 | 건너뜀 3 | 판정없음 1   (단언 10,483 -> 10,740)
                                (통과 60 -> 62: test_doc_pdf_iframe.py / test_db_write_failure_modes.py 신설분)
```

프런트 서버 없이 도는 순수 계약/단위 검사: **167 -> 218건**.

### 실제 화면으로 확인 (dev 서버 + API 서버 기동)

```
GET /api/v1/search           200, total 1,876, 응답에 building_area/land_area 키 존재
GET /  (검색 첫 화면)          200
  총 건수     "총 1,876건"                    formatNumber
  D-day       "입찰 12일 경과"                 KST 기준
  면적         "건물 29.95㎡ (9.06평)"          서버 값 null -> 주소 폴백 (이 DB 는 025 미적용)
```

### 파이썬 실패 4건은 **이 머신의 환경**이다 (코드 결함 아님)

```
migration_history 최신   020_create_auction_image  (2026-08-17)
미적용                   021 ~ 026
auction_item             building_area / land_area 컬럼 없음
```

`test_auction_identity` / `test_bootstrap` / `test_pipeline_integrity` / `test_schema_hygiene`
넷이 이 때문에 멈춘다. **이 세션 전후로 실패 목록이 같다**(60/4/3/1 -> 60/4/3/1).
마이그레이션 적용은 승인 영역이라 하지 않았다.

### 변이 검증 (전부 원복 확인)

| 영역 | 변이 | 검출 |
|---|---|---|
| 로케일 | 인자 없는 `toLocaleString` 복귀 / 로케일 제거 / `formatWon` 우회 / 인라인 원 표기 복귀 | 4/4 |
| D-day | 로컬 자정 복귀 / UTC 로 변경 / 잘못된 형식을 D-Day 로 / 계층 우회 복귀 | 4/4 |
| 면적 | 카드가 주소 파서만 사용 / 우선순위 뒤집기 / 0 을 면적으로 / 라벨 뒤집기 / 타입·응답 키 제거 | 6/6 |
| 브랜드 | 구 브랜드명 복귀 / 헤더에서 서비스명 제거 | 2/2 |
| 어휘 | 옛 ENUM 선언 복귀 / 취소선 제거 / 없는 어휘 삽입 / 표 삭제 / 표식 삭제 | 5/5 |
| types | 옛 미지원 서술 복귀 / 두 번째 목록 생성 / 정본 참조 제거 | 3/3 |
| 가져오기 | 별칭 오매핑 / 내보내기 열 이름 변경 / 없는 검사 파일 인용 | 3/3 |
| PDF iframe | 준비 전 `""` 반환 / stale 예외 전파 / 드라이버 예외 전파 / 대소문자 구분 | 4/4 |
| 최저가율 | 인라인 계산 복귀 / 값없음 가드 제거 / 0 을 하이픈으로 / 라벨 교체 / 자릿수 변경 | 5/5 |
| 큐 어휘 | 상수 오타 2종 / SQL 리터럴 되박기 / 어휘 집합에서 값 제거 | 4/4 |
| API 계약 | 타입에서 키 제거 2종 / 없는 키를 필수 선언 / 죽은 예외 추가 | 4/4 |
| 인증 계약 | note_source 제거 / 미선언 키 추가 / 유령 필수 키 / 화면 전용 필드 변경 | 4/4 |
| 마이페이지 계약 | 새 키 추가 / 예외 대상 키 제거 / 유령 필수 키 | 3/3 |
| 문서 상태 | 열거형에서 NO_IMAGE 제거 / 실패 쪽으로 이동 / 라벨 제거 / 워커가 선언 밖 값 | 4/4 |
| DB 쓰기 장애 | 행마다 커밋 / 커밋 실패 삼키기 / claim CAS 상태 조건 제거 | 3/3 |
| 상태 리터럴 | payments 되돌리기 / doc_stats IN 되돌리기 / registry 에 새 리터럴 | 3/3 |

**합계 61/61 검출, 생존 0.**
(중간에 생존 6건이 나왔고 — 산문 기반 판정 2건, 소스 계약 누락 2건, 자기참조 검사 1건,
인용 범위 1건 — 전부 검사 쪽을 고쳐 닫았다.)

---

## 하지 않은 것 (SKIP — 전부 승인·제품 결정 영역)

| 항목 | 사유 |
|---|---|
| 마이그레이션 021~026 적용 | 승인 영역. 이 머신의 파이썬 실패 4건의 유일한 원인이다 |
| `formatPrice` / `formatPriceEok` 표기 통일 | 화면 숫자가 바뀌는 UX 결정(미결정으로 이미 기록돼 있다) |
| 빈 값 표기 어휘 통일(`-` / `정보 없음` / `주소 미확인` / `일자 미상`) | 화면 문구 결정 |
| `formatPrice(0)` 이 `'-'` 인 것(0 과 NULL 을 같게 보여준다) | 표기 결정. 실데이터에 0 은 0건이라 지금은 잠재 결함이다 |
| 임차인 실명 마스킹(BUGS #254) | 제품·법무 판단 |
| 상세 API 인가 정책 | 제품 결정 |
| 백엔드 `date.today()` 를 KST 로 고정 | 배포/서버 시간대 결정 |
| 내보내기에 메모/태그 열 추가 | 개인 메모를 파일로 내보내는 것은 개인정보 판단이 따라온다 |
| 상세 화면에 면적 표시 | 정보 구성 변경은 `FRONTEND_MASTER_SPEC` §9.3 범위 밖 |
| `_pdf_iframe_src` 가 쿼리스트링 src 를 잡게 넓히기 | 실 사이트 확인 필요(docstring 이 이미 그렇게 적어 둔 자리) |

---

## 10. 최저가율 퍼센트 계산이 두 곳에 있었고, 한쪽은 없는 값을 0 으로 지어냈다

```
src/app/search/ResultList.tsx     (r*100).toFixed(1) + '%'   + null/undefined 가드 -> '-'
properties/[id]/page.tsx:772      (r*100).toFixed(1) + '%'   가드 없음
```

가드가 없는 쪽은 `(null*100).toFixed(1)` = **"0.0%"** 를 찍는다. 없는 것을 0 으로
지어내는 것이고, 이 저장소가 반복해 금지해 온 모양이다(`exportList.ts` 의
"값이 없음과 값이 0 은 다른 사실이다", `parseArea`/`formatDday` 가 모르면 null 을
돌려주는 것과 같은 규칙). **가드가 있는 쪽으로** 모아 `src/lib/format.ts:formatBidRate`
한 곳으로 옮겼다.

지금 DB 에 `bid_rate` NULL 은 0건이고 컬럼 DEFAULT 도 0 이라 **화면 문자열은 바뀌지 않는다.**
막는 것은 앞으로 생길 "0.0%" 다.

★ **라벨이 화면마다 다른 것은 고치지 않았다** — 둘 다 문서가 그렇게 정하고 있다.

```
검색 결과 카드   "최저가율"   search/00_SEARCH_MVP.md §5.2 표시 항목
물건 상세        "입찰가율"   docs/FRONTEND_MASTER_SPEC.md §9.2 가격·일정
백엔드 정의      "최저가율"   docs/backend.md (bid_rate = 최저가 / 감정가)
```

한 낱말로 통일할지는 화면 문구 결정이라 SKIP 했고, 대신 **문서와 어긋나지 않는지**를
소스 계약으로 고정했다. 변이 5/5 검출.

---

## 11. `document_queue.status` — 여덟 값 중 둘만 상수가 없었다

이 컬럼의 값은 전부 `WHERE status='...'` 로 **비교**된다. 오타는 예외가 아니라
**0행 매치**다. `mark_queue_done()` 이 아무 행도 바꾸지 못하면 그 행은 `in_progress` 로
남아 stale 회수까지 붙잡혀 있고, 화면에는 수집이 끝난 것으로 보인다. 로그에도 남지 않는다.

`storage/database.py` 는 여섯 값을 상수로 두고 그 이유까지 적어 두었다 —
"되살리는 쪽과 되살리지 않는 쪽을 문자열로 구별하면 언젠가 어긋난다".
그런데 **종결 둘(`done`/`failed`)만 상수가 없었고**, 상수가 있는 값조차 SQL 텍스트에
리터럴로 박힌 자리가 있었다(`AND status='SKIPPED_EXPIRED'`). 같은 파일 안에서 규칙이
반쯤만 지켜지고 있었다.

```
신설   QUEUE_STATUS_DONE / QUEUE_STATUS_FAILED
       QUEUE_STATUSES (이 컬럼이 가질 수 있는 값 전부)
정리   SQL 안의 상태 리터럴 8곳 -> 바인딩 (값은 그대로, SQL 텍스트에 값을 넣지 않는다)
       api/v1/doc_stats.py 의 `queue_counts.get("failed", 0)` 도 상수로
```

`api/constants.py` 가 상태값을 모을 때 세운 규칙과 같다 — **리터럴을 모으되 값은 새로
정하지 않는다.** DB 에 든 값은 한 글자도 바뀌지 않았다.

### 검사를 어떻게 걸었나 — 자기참조를 피한다

처음 만든 "파생 목록이 어휘를 벗어나지 않는다" 검사는 **양쪽이 같은 상수에서 파생**돼
상수 값 자체의 오타를 잡지 못했다(변이에서 실제로 생존). 그래서 **제품 코드가 DB 에
실제로 쓴 값**을 읽어, 검사 파일에 손으로 적은 기대 문자열과 맞춘다 — 두 출처가 독립이라
`"in_progres"` 같은 오타가 드러난다.

```
(a) 상수/어휘 집합이 실재한다            (b) 파생 목록이 어휘 안에 있다
(c) 제품 SQL 에 상태 리터럴이 없다        (구문 트리로 docstring 만 제외 — 줄 단위로 훑으면
                                          설명문의 'SKIPPED_EXPIRED' 까지 결함으로 잡힌다)
(d) 실제 DB 의 상태가 전부 선언된 어휘다   (e) claim/mark_done 이 DB 에 쓴 값 == 기대 문자열
```

`test_queue_safety_invariants.py` 에 넣었다(큐 불변식의 기존 자리). 변이 4/4 검출.

---

## 12. 화면 간 사진 일관성 — 이미 해소된 것을 미해결로 적고 있었다

`docs/frontend.md` 가 "`thumbnail_url` 을 주는 API 는 `search.py` 하나뿐이고 관심물건·
최근 본 물건에는 `<img>` 가 없다"를 유지하고 있었다. Sprint 224 가 닫은 항목이고
`docs/roadmap.md` 는 해결로 적고 있었는데 이 문서만 갱신되지 않았다. 2026-08-31 실측:

```
API    thumbnail_url 을 주는 라우터 4개   search / item / favorites / recent_items
화면   ResultThumbnail 을 쓰는 화면 3개   ResultList / favorites / properties/recent
```

**있는 기능을 다시 만들게 되는** 종류의 드리프트라 정정했다.

---

## 13. 응답에는 있는데 프런트 타입에 없는 키 — 반대 방향 계약이 비어 있었다

이 저장소의 계약 검사는 **파라미터 방향**(프런트가 보내는 것 ↔ 백엔드가 받는 것)만
보고 있었다. 반대 방향 — **백엔드가 주는 것 ↔ 프런트가 선언한 것** — 은 아무것도
보지 않았고, 실제로 드리프트가 쌓여 있었다. 실행 중인 서버에 붙어 전수 대조한 결과:

```
GET /api/v1/search  items[]   building_area / land_area                2026-08-26 부터 응답에 있었다
GET /api/v1/item/{id}         sido / sigungu / dong                    처음부터 있었다
                              building_area / land_area
```

타입에 없는 키는 런타임에 아무 문제도 일으키지 않는다. 그래서 **드러나지 않는다.**
드러나는 순간은 누군가 "그 데이터는 응답에 없다"고 읽고 **이미 있는 것을 다시 만들 때**다 —
§4 의 검색 카드가 서버 면적을 두고 주소를 다시 파싱하고 있던 것이 정확히 그 결과다.

일곱 개를 전부 선언했다(표시 여부는 바꾸지 않았다 — 정보 구성 변경은
`docs/FRONTEND_MASTER_SPEC.md` §9.3 범위 밖이라 SKIP). 주소 3조각에는
"표시는 `full_address` 하나로 한다"를 함께 적어, 같은 주소의 두 번째 계산 경로가
생기지 않게 했다.

### 검사를 `tests/frontend-contract.test.mjs` 에 넣었다 (살아 있는 서버 대조)

```
1  응답의 모든 키가 타입에 선언돼 있다
2  타입에만 있는 키는 optional 이다        (없는 것을 있다고 적지 않는다)
3  예외 목록이 코드보다 앞서 나가지 않는다   (죽은 예외 금지)
```

예외는 하나다 — `tenants[]` 의 `id`/`item_id`/`created_at`. `tenant_rights` 는 12컬럼인데
프런트는 9개만 쓰고, 좁히는 것은 **API 계약 축소**라 소비자를 먼저 옮겨야 한다
(`docs/BUGS.md` #254 가 같은 이유로 화이트리스트를 지금 나가는 그대로 두었다).
3번 검사가 이 예외가 죽지 않았는지 매번 확인한다.

대조 결과: **6개 계약 중 드리프트 0** (수정 후). 변이 4/4 검출.

---

---

## 14. `document_status` 열거형에 `NO_IMAGE` 가 없었다

`api/constants.py:DocumentStatus` 가 여섯 값만 선언하는데 제품은 일곱 번째를 쓰고 있었다.

```
doc_worker.py            done_status = "NO_IMAGE" if result.get("no_asset") else "READY"
api/v1/item.py           `_images_status()` 가 그대로 내보낸다
storage/database.py      DOC_STATUS_HAS_ARTIFACT = ("READY", "NO_IMAGE")
audit_asset_integrity.py 정합성 판정이 정상으로 센다
properties/[id]/page.tsx '사진 없음' 라벨
```

**DB·수집기·API·화면·감사기가 전부 아는 값을 상태값 정의만 몰랐다.** 상태값이 문자열이라
열거형을 거치지 않고도 잘 돌기 때문에 실행으로는 드러나지 않는다. 드러나는 순간은
누군가 열거형만 보고 분기를 짤 때다 — `NO_IMAGE` 를 `FAILED` 로 뭉뚱그리면 사용자는
**기다리면 사진이 생길 것으로** 오해한다(법원이 제공하지 않는다는 것은 확인된 답이다).

`storage/migrate_v4_1.py` 주석 2곳과 `docs/backend.md` 도 같은 여섯 값만 적고 있어 함께 정정했다.
`DOCUMENT_STATUSES_IN_USE` 도 두었다 — `OCR`/`PARSING`/`ANALYZING` 은 **선언만 있고
쓰는 코드 0곳·DB 행 0건**이라(자리만 잡아 둔 값) "DB 에 이 값이 있어야 정상"을 판정할 때는
사용 집합을 쓴다. 지우는 것은 상태 체계 축소라 제품 결정이므로 SKIP 했다.

회귀는 큐 어휘 검사 옆(`test_queue_safety_invariants.py`)에 뒀다 — 같은 파이프라인의
이웃 컬럼이고, 목록이 두 벌이면 갈라진다. 변이 4/4 검출.

---

## 15. BUGS #268 이 **없는 검사 두 벌**을 근거로 "해결"이라고 적고 있었다

```
docs/BUGS.md #268 (2026-08-28)
  "해결. 검사 두 벌 신설 — test_db_write_failure_modes.py(6절/단언 30) ·
   test_queue_multiprocess_claim.py(3절/단언 14). 둘 다 변이로 검출 확인."
```

2026-08-31 실측: **두 파일 다 저장소에 없다.** 작업 디렉터리에도 `git log --all` 에도 없고,
그 이름을 언급하는 곳은 그 문단뿐이었다. 실제로 고정돼 있던 것은 행 단위 격리 하나뿐
(`test_auction_identity.py` §3 — 그것은 실재한다).

`upsert_batch()` 의 계수는 `CrawlOutcome.persisted` 를 거쳐 크롤의 **종료 코드**가 된다.
틀린 숫자는 곧 `run_daily.bat` 의 잘못된 판정이고 "실패했는데 성공으로 끝났다"가 된다.
그 자리가 미검증인 채 "해결"로 적혀 있었다.

### 실제로 만들었다 — `test_db_write_failure_modes.py` (6절 / 단언 29)

BUGS 의 서술을 베끼지 않고 **스크래치 DB 에서 각 거동을 먼저 재고** 잰 값으로 단언했다.

```
1 트랜잭션 모양   commit 1 / rollback 0 / 행당 쓰기 1 / 배치당 SELECT 2   (n=50 실측)
2 커밋 실패      OperationalError 가 올라오고 그 배치는 한 행도 남지 않는다
3 DB 잠김        `database is locked` 로 드러난다(조용한 0건 성공이 아니다) + 해제 후 정상
4 프로세스 사망   커밋 직전 os._exit(9) - 500행이 남지 않고 integrity_check=ok, 이후 쓰기 정상
5 실패 후 재실행  앞선 실패가 남기지 않고, 두 번째 실행은 전부 unchanged(멱등)
6 claim 배타성   **진짜 프로세스 2개**(스레드 아님)로 40행 경합 - 중복 claim 0, 잔여 0
```

파일을 두 벌로 나누지 않았다 — 큐 claim 배타성도 같은 "DB 쓰기 장애 거동"이고,
목록이 두 벌이면 갈라진다(#204). 행 단위 격리는 다시 만들지 않았다(중복).

★ **첫 실행에서 6절이 공허했다.** 한 프로세스가 40행을 통째로 비우고 다른 하나가 빈 큐를
봤다(40:0) — 동시성을 재려던 검사가 순차 실행을 재고 있었고 "중복 0" 은 그 상태에서도
통과한다. 비공허성 단언이 그것을 잡아서 파일 신호로 둘을 함께 출발시키게 고쳤다.

변이 3/3 검출(행마다 커밋 / 커밋 실패 삼키기 / claim CAS 의 상태 조건 제거).
※ 처음 시도한 변이 2건은 앵커가 빗나가 생존했는데, **검사가 약한 것이 아니라 변이가
   엉뚱한 곳에 붙은 것**이었다(행 단위 except / 두 곳 중 한 곳만). 정확히 겨누니 둘 다 잡혔다.

---

## 16. 결제·등기부·문서 상태값이 SQL 문자열에 박혀 있었다

§11 에서 큐 어휘를 정리한 뒤 **같은 방식으로 나머지 상태 컬럼을 훑었다**(열거형에서
어휘를 파생시켜 `api/v1/*.py` 전수 스캔). 세 자리가 남아 있었다.

```
api/v1/payments.py   SELECT ... WHERE user_id=? AND status='PAYMENT_REQUIRED'
api/v1/payments.py   UPDATE ... SET status='PENDING' WHERE ... status='PAYMENT_REQUIRED'
api/v1/doc_stats.py  WHERE doc_type IN ('SPEC',...) AND status IN ('READY','FAILED')
```

같은 파일들이 **다른 자리에서는 이미 상수를 쓰고 있었다**(`PaymentStatus` /
`QUEUE_STATUS_*`) — 한 파일 안에서 규칙이 둘이었다. 결제 경로에서 오타가 나면
0행 매치가 되어 "초과결제 대상 신청이 없다" 또는 "이미 처리됨"으로 조용히 오판한다.

값은 한 글자도 바뀌지 않는다 — 리터럴을 `api/constants.py` 의 열거형으로 옮기고
바인딩했다. `doc_stats.py` 의 `IN (...)` 은 `?` 반복만 만들고 값은 모듈 상수 튜플에서
바인딩한다(`QUEUE_CLAIMABLE_PLACEHOLDERS` 와 같은 패턴).

### 저장소의 자체 감사가 이 변경을 세 번 잡았다

새 `IN (...)`/`%`-포맷 SQL 은 **등록 없이는 통과하지 못한다.**

```
[FAIL] 작업 중 BOM이 조용히 바뀐 파일 없음      api/v1/payments.py     -> 되돌림
[FAIL] %-포맷 SQL 에 새 템플릿 없음             허용 목록 미등록        -> 근거와 함께 등록
[FAIL] 새 `IN (...)` 지점이 인벤토리에 등록됐다  입력 크기 근거 필요     -> 모듈 상수 3/2 개로 등록
```

감사 자체가 설계대로 동작한 사례라 그대로 적어 둔다.

회귀는 `test_state_machines.py` 에 뒀다 — DB 가 필요 없는 순수 소스 검사이고,
그 파일이 이미 이 열거형들의 전이 규칙을 담당한다. 어휘는 **열거형에서 파생**시켜
목록이 두 벌이 되지 않게 했다. 변이 3/3 검출.

### 함께 확인한 것 — 문서가 인용하는 **테스트 함수**가 실재하는가

파일 이름 인용은 §8 에서 확인했고, 이번에는 **함수 이름**을 봤다.
정의된 `test_*` 함수 617개 / 인용 682건 대조 결과 정의되지 않은 이름은 1종
(`test_registry_orphan_item_visibility`)뿐이고, 그것은 worktree 시절 이름을 설명하는
**사료**였다 — 같은 검사가 `test_false_success.py:test_registry_orphan_visibility()` 로
실재한다(0바이트 문서 검사 2종도 함께 확인). **문제 없음.**

---

## 17. 문서가 인용하는 **식별자**가 실제로 있는가 — 전수 대조

§8 은 파일 이름을, §16 은 함수 이름을 봤다. 이번에는 정책·현황 문서 11개가 backtick 으로
인용하는 **상수 / 함수 / 경로**를 코드 259개 파일(3.9MB)과 통째로 대조했다.

```
상수·Enum 인용   246종 -> 코드에 없는 것 3종
함수 인용        202종 -> 코드에 없는 것 4종
경로 인용        479종 -> 실재하지 않는 것 12종 (basename 해석 후)
```

대부분은 **취소선이나 "제거했다/정정" 표기가 붙은 사료**였다(`REGISTRY_OVERAGE_FEE`,
`SIGUNGU_MAP`, `src/middleware.ts`, `storage/migrate_doc_collect.py`, `action.ts` 등).
살아 있는 주장으로 남아 있던 것은 둘이다.

### (a) `create_mock_payment()` — 없는 함수를 이관 지시가 가리켰다

```
docs/decision-log.md "Payment Mock (2026-08-05)"
  - PG 실연동 시 `create_mock_payment()`를 PG 콜백 처리로 교체 필요
```

저장소 전수 검색 결과 그 이름은 **어디에도 정의돼 있지 않다.** 이 지시를 따르려던 사람은
없는 함수를 찾게 된다. 지금의 교체 지점은 함수가 아니라 **Provider** 다 —
`create_payment_record()`(`api/v1/payments.py:344`)가 `get_payment_provider()`(:352)로
얻은 Provider 의 `create_order()`/`confirm_payment()` 를 부르고, PG 실연동은
`KGInicisProvider` 의 그 메서드를 구현하는 일이다. `docs/architecture.md` 가 이미 그 경계를
그려 두고 있어 **새 정책을 만들 필요 없이** 그쪽을 가리키도록 고쳤다.

### (b) `PLAN_PRICES` — 이름이 바뀐 상수를 완료 근거로 들었다

`docs/CURRENT_STATE.md` 의 ☑ 항목이 `PLAN_PRICES` 를 서버 검증의 근거로 든다.
Sprint 28 의 Plan API 서버화로 `PLAN_CATALOG` + `resolve_plan_price()` 가 됐고,
그 이름은 지금 없다. 완료 사실은 그대로 두고 **현재 이름을 가리키도록** 정정했다.

---

## 18. 출시 차단 문서가 이미 있는 엔드포인트를 "신규 구현 필요"로 적고 있었다

`docs/BETA_RELEASE_CHECKLIST.md` P0-1(KG이니시스 실연동)이 이렇게 적고 있었다.

```
- 함께 필요: 환불(`cancel_payment`) / Webhook 수신(`handle_webhook`) 엔드포인트 신규 구현 —
  두 메서드는 인터페이스에만 있고 호출부가 없다
```

**호출부는 있다.** 코드 대조 + 살아 있는 서버의 OpenAPI(전체 41경로)로 확인했다.

```
POST /api/v1/admin/payments/{payment_id}/refund   admin.py:975 -> refund_payment() -> provider.cancel_payment() (payments.py:679)
POST /api/v1/payments/webhook/{provider_name}     payments.py:736 -> verify_webhook_signature(:759) -> handle_webhook(:792,:912)
GET/POST /api/v1/admin/payments/webhooks[...]     수신 원문 조회·재처리 3경로
```

비어 있는 것은 **`KGInicisProvider` 쪽 구현**뿐이다(그 클래스의 6개 메서드가
전부 `NotImplementedError`). `docs/decision-log.md` CTO 승인 5번은 2026-08-11 Sprint 52 에
수신 경로가 연결됐다고 이미 적고 있었고, `docs/STATE_MACHINES.md` §1 도 환불 경로에
상태머신 관문이 붙어 있다고 적는다 — **세 문서 중 이 하나만 옛 상태였다.**

출시를 막는 항목이라 남은 일의 크기를 과대평가하게 만든다. 사료는 취소선으로 남기고
실측 근거와 함께 정정했다. **정책은 바꾸지 않았다** — P0-1 은 여전히 승인·외부 절차 대기다.

---

## 19. 인증 필요 응답 ↔ 프런트 타입 — 소스로 대조했다

공개 API 는 §13 에서 살아 있는 서버로 대조했다. 인증이 필요한 목록은 같은 방법을 쓰려면
JWT 가 필요하고 **그 시크릿을 읽는 것은 승인 영역**이라(`docs/CLAUDE.md` Secret 열람 금지),
같은 질문에 **소스로** 답했다 — 라우터가 만드는 dict 의 키 ↔ TS 인터페이스의 키.

```
GET /api/v1/favorites      API 19키 / TS 18키   -> note_source 미선언 (드리프트)
GET /api/v1/recent-items   API 16키 / TS 16키   -> 일치
```

`note_source` 는 `favorite_notes.source` 로, 마이리스트 가져오기가 "어디서 옮겨 왔는지"를
적어 두는 값이다. 검색·상세에서 고친 것과 같은 모양이라 **타입에 선언만** 했다
(화면 표시 여부는 정보 구성 결정이라 SKIP).

검사는 `tests/source-contract.test.mjs` 에 뒀다. 두 목록 화면이 **같은 카드 필드**를 받는지도
함께 고정한다 — 화면 전용 필드(`favorited_at`/`memo`/`tags`/`note_source` vs `viewed_at`)만
달라야 한다. 변이 4/4 검출.

## 감사 도구가 작업 트리를 바꾸는가 (2026-08-31 실측)

도구를 돌리기 전후로 `git status --porcelain` 과 `git ls-files -s` 를 비교했다.

```
도구                         exit   작업 트리 변화   index 변화
audit_schedule_health.py      0        없음           없음
audit_auth_health.py          0        없음           없음
audit_asset_integrity.py      1        없음           없음      (어긋남 27건은 데이터)
audit_test_reality.py (필터)  0        없음           없음
audit_contrast.py --selftest  1        없음           없음      <- §24 의 파손
audit_viewport.py --selftest  2        없음           없음      (--selftest 자체가 없다)
```

★ 단, `audit_test_reality.py` 를 **전수**로 돌리면 추적 파일
`.cov_test_audit_selftests-DESKTOP-DVRJEGP_py` 를 지운다(자기 산출물 정리 경로).
`.gitignore` 에 `.cov_*` 가 있는데 그 파일 하나는 규칙보다 먼저 커밋돼 추적 중이라 생긴 일이다.
이 세션에서 두 번 발생했고 **두 번 다 HEAD 블롭으로 바이트 동일 복원**했다.
근본 해결(추적 해제)은 git index 변경이라 승인 영역이다.

## 운영 감사 도구 점검 (읽기 전용 실행)

문서가 아니라 **도구 자체**가 없는 것을 가리키는지도 봤다.

```
audit_asset_integrity.py   exit 1  어긋남 27건 (전부 데이터 - 고아 큐 18 / 다운로드 고아 8 / 고아 디렉터리 1)
audit_schedule_health.py   exit 0
audit_auth_health.py       exit 0
audit_test_reality.py      exit 0  전수 71개 측정 완료 - 의심 목록 7건, 전부 설계·측정 한계로 설명됨(§20)
경로·테이블 참조            존재하지 않는 것 0건
```

어긋남 27건은 **코드 결함이 아니라 이 개발 DB 의 상태**이고, 정리는 승인 영역이라 SKIP 했다
(도구 스스로도 "지금 낭비되는 수집 비용은 0" 이라고 판정한다).

### 새 검사들이 공허하지 않다는 독립 증거

`audit_test_reality.py` 로 이번 회차의 검사들이 **제품 코드를 몇 줄 실행하는지** 쟀다.

```
test_queue_safety_invariants.py   제품 467줄 / 모듈 6
test_property_type_vocabulary.py  제품 348줄 / 모듈 8
test_db_write_failure_modes.py    제품 232줄 / 모듈 3
test_doc_pdf_iframe.py            제품  80줄 / 모듈 3
의심 목록(제품 코드를 거의/전혀 실행하지 않는 검사)  -> 해당 없음
```

변이 검증과 별개의 축으로도 "소스 문자열만 보는 검사"가 아님이 확인된다.

---

## 20. 검사 71개의 실효성을 전수로 쟀다 — 그리고 도구 두 개가 다른 말을 하고 있었다

`audit_test_reality.py` 를 **전수 실행**했다(파일 하나씩 coverage 로 돌려 제품 코드
실행 줄을 센다). 71개 측정, 의심 목록 7건.

```
[실행 0줄] test_audit_selftests.py          <- subprocess 로 감사 도구를 돌린다 (측정 한계)
[실행 0줄] test_console_encoding.py         <- 소스를 훑는 드리프트 가드 (설계대로)
[실행 0줄] test_frontend_accessibility.py   <- 프런트를 본다 (파이썬 제품 코드 무관)
[실행 0줄] test_audit_selftests-DESKTOP-DVRJEGP.py   <- ★ OneDrive 충돌 사본
[실행 14/37/45줄] test_crawl_resume / test_crawl_exit_code / test_runner_contract
```

**공허한 검사는 없었다.** 0줄 셋은 전부 설계상 소스/서브프로세스를 보는 것이고,
낮은 셋도 subprocess 로 실행기를 돌려 과소 계상된다.

### 그런데 네 번째 줄이 문제였다 — 도구 두 개가 다른 말을 한다

`run_python_tests.py` 는 OneDrive 충돌 사본(`*-DESKTOP-XXXX.py`)을 **제품 검사가 아니라고**
판정해 실행 대상에서 빼고 요약에 따로 센다(그 파일 주석 + `docs/BUGS.md` #253/#258 —
그중 하나는 605초가 걸려 스위트를 2분에서 12분으로 만든다). 그런데 이 감사기는 빼지 않아
**그 사본을 재서 의심 목록에 올렸다.**

규칙을 베끼지 않고 **실행기의 판정 함수를 그대로 import** 했다
(`run_python_tests.is_conflict_copy`). 목록이 두 벌이면 갈라진다 — 이 저장소가
`_search_param_contract.mjs` 로 이미 세운 원칙이다. 숨기지도 않는다:

```
OneDrive 충돌 사본 1개는 재지 않았다(제품 검사가 아니다, BUGS #253/#258): test_audit_selftests-DESKTOP-DVRJEGP.py
```

### 측정 한계도 출력에 적었다

`subprocess` 로 도는 검사가 0줄로 나오는 것은 coverage 가 부모 프로세스만 세기 때문이다.
이 사실이 적혀 있지 않으면 **멀쩡한 검사를 "공허하다"고 오독한다**(2026-08-21 에 도구의
분류 목록이 좁아 `test_runner_contract.py` 가 0줄로 나왔던 것과 같은 종류의 오독이다).
의심 목록 각주에 그 문장을 넣었다.

---

## 21. 마이페이지 3종 — 미선언 키를 "타입에 다 적기"로 풀지 않았다

`/mypage` 는 기존 API 3개를 조합한 읽기 전용 화면이다. 소스 대조 결과 응답에는 있는데
타입에 없는 키가 **9개** 있었다.

```
GET /api/v1/subscriptions/me   user_id / created_at / updated_at
GET /api/v1/payments           user_id / updated_at / pg_provider / pg_transaction_id / metadata
GET /api/v1/registry-requests  completed_at
```

**검색·상세와 같은 처방(타입에 추가)을 쓰지 않았다.** 성격이 다르기 때문이다 —
앞의 여덟은 화면이 쓸 일이 없는 내부 필드(결제 내부 식별자·타임스탬프)이고,
`completed_at` 하나만 사용자에게 의미가 있다. **어느 것을 타입에 올리고 어느 것을
응답에서 뺄지는 정보 구성·계약 축소 결정**이라 여기서 정하지 않았다
(`docs/BUGS.md` #254 가 `tenants[]` 3키를 같은 이유로 남겨 둔 것과 같은 취급).

대신 **지금 상태를 명시적으로 적어 고정**했다.

```
1  목록에 없는 새 키가 응답에 생기면 실패한다   (조용히 늘지 않는다)
2  목록에 있는데 응답에서 사라지면 실패한다     (죽은 예외 금지)
3  타입이 필수라고 적은 키가 응답에 실제로 있다
```

변이 3/3 검출(새 키 추가 / 예외 대상 키 제거 / 유령 필수 키).

### 함께 확인하고 **고치지 않은** 것

`row_to_subscription()` 이 `payments.py` 와 `subscriptions.py` 에 **두 벌** 있다.
기본 9필드가 손으로 복제돼 있어 전형적인 Frankenstein 후보로 보였는데,
`test_subscription_policy.py:test_row_to_subscription_shapes_agree()` 가 **이미 두 함수를
나란히 태워 기본 필드 집합이 같은지 고정하고 있었다**(2026-08-14 신설).
`crawler/resume.py` ↔ `normalizer/mylist_import.py` 의 사건번호 규칙과 같은 처리 방식이다.
**중복이지만 교차 검사가 실재하므로 손대지 않았다** — 새 코드를 만들기 전에 기존 검사를
찾으라는 규칙이 실제로 한 건을 막았다.

---

## 22. 내가 만든 변경을 다시 감사했다 (Self-Consistency)

이 문서의 §1~§21 은 전부 이 세션들이 만든 변경이다. 그 변경 자체가 새로운 Frankenstein 을
만들지 않았는지 **같은 검사기로** 되짚었다.

```
내가 추가한 상수 8종        정의 위치 각 1곳 (DISPLAY_LOCALE / DISPLAY_TIME_ZONE /
                            QUEUE_STATUS_DONE / QUEUE_STATUS_FAILED / QUEUE_STATUSES /
                            DOCUMENT_STATUSES_IN_USE / _STAT_DOC_TYPES / _STAT_STATUSES)
내가 추가/이관한 함수 6종    정의 위치 각 1곳 (formatNumber / formatBidRate / serverArea /
                            displayArea / todayInDisplayZone / formatDday)
새 SQL 상태 리터럴          0건  (test_state_machines / test_queue_safety_invariants 통과)
새 bare toLocale*           0건  (source-contract 통과)
새 timezone 계산 경로       0건  (todayInDisplayZone 하나)
새 fallback                 1건  (displayArea — 의도적이고 §4 에 근거를 적어 두었다)
이 문서의 경로 인용 52종     실재하지 않는 4종은 전부 **사료를 인용한 자리**(취소선/인용문/
                            "존재하지 않는다"를 설명하는 문장) — 살아 있는 잘못된 인용 0건
```

새 검사들이 제품 코드를 실제로 도는지는 §20 의 전수 측정이 별도로 답한다.

---

## 23. `docs/roadmap.md` 식별자 인용 검증

라이브 계획 문서라 따로 훑었다.

```
테스트 파일 12종 -> 없는 것 0
함수        34종 -> 없는 것 1  (create_mock_payment — Sprint 8 에 교체됐다는 **이력 서술**)
상수        36종 -> 없는 것 2  (PLAN_PRICES — 같은 이력 / SKIPPED_NO_ITEM — "만들지 여부는
                                 제품 판단" 이라고 명시된 **후보 어휘**)
경로        40종 -> 없는 것 2  (src/middleware.ts, storage/migrate_doc_collect.py — 개명·대체 이력)
```

**전부 이력이거나 후보로 정확히 표시돼 있다.** 살아 있는 잘못된 인용 0건 — 정정하지 않았다
(스프린트 이력을 고쳐 쓰는 것은 사료를 지우는 일이다).

---

## 24. `audit_contrast.py` 가 존재하지 않는 속성을 참조한다 (미해결 — 승인 영역)

§20 의 **감사 도구 자체 감사**를 하다 찾았다. 도구 6개를 돌려 작업 트리 변화를 재던 중
`audit_contrast.py --selftest` 만 exit 1 이었다.

```
File "audit_contrast.py", line 351, in selftest
    except AV.DriverUnavailable as exc:
AttributeError: module 'audit_viewport' has no attribute 'DriverUnavailable'
```

### 실측 — 무엇이 어긋나 있나

```
audit_viewport.build_driver 시그니처   (headed, width, height)        <- factories 없음
audit_viewport.DriverUnavailable       없음
audit_contrast.py:349                  AV.build_driver(..., factories=[...])   <- 없는 인자
audit_contrast.py:351, :388            except AV.DriverUnavailable            <- 없는 속성
```

### 왜 심각한가 — 실패 사유가 **가려진다**

388행은 selftest 가 아니라 **본 측정 경로**다. 재현했다.

```
try:    raise RuntimeError('드라이버 기동 실패')
except AV.DriverUnavailable: ...          -> AttributeError 가 대신 올라온다
except Exception: ...                     -> 이 절에는 **도달하지 못한다**
```

즉 브라우저를 못 띄우면 바로 아래에 적힌 "예전에는 여기서 40줄짜리 트레이스백이 그대로
나왔다(BUGS #193)" 라는 **고쳤다는 그 증상이 그대로 재현된다.** 주석이 약속한 것을
코드가 못 한다.

### 원인 — OneDrive 충돌 사본이 갈라 놓았다

```
audit_viewport.py                  2026-08-21  DriverUnavailable 없음   (HEAD == 작업본)
audit_viewport-DESKTOP-DVRJEGP.py  2026-08-27  DriverUnavailable 있음 + factories + --selftest
audit_contrast.py                  2026-08-27  **충돌 사본 쪽 인터페이스**를 기대한다
```

새 구현이 **충돌 사본에만** 들어왔고 살아 있는 파일은 2026-08-21 판에 멈춰 있다.
`run_python_tests.py` 가 경고한 충돌 사본 문제가 테스트가 아니라 **운영 도구를 깨뜨린** 사례다.

### 고치지 않은 이유 (SKIP)

세 가지 길이 있는데 전부 승인 영역이거나 위험하다.

```
(a) 충돌 사본을 살아 있는 파일로 승격        <- 어느 쪽이 최신인지 고르는 일 = 사람의 판단
                                              (`run_python_tests.py` 가 명시)
(b) audit_viewport 를 crawler.base_crawler.resolve_chrome_driver 에 바인딩
    (BUGS #196 의 단일 소스. DriverUnavailable 도 거기 있다)
    -> 본 측정 경로는 고쳐지지만 selftest 가 기대하는 factories 계약
       ((h,w,ht) 서명)은 base_crawler((opts) 서명)와 다르다. 반쪽만 맞는다
(c) audit_contrast 쪽만 except 를 좁힌다     <- 증상은 가리고 인터페이스 불일치는 남는다
```

(b)/(c) 를 지금 넣으면 (a) 를 할 때 **세 번째 변종**이 생긴다 — 이 문서가 막으려는 그것이다.
그래서 **증거만 남기고 손대지 않았다.**

### 덧붙여 확인한 것 — `audit_viewport.build_driver` 는 단일 소스를 우회한다

BUGS #196 은 드라이버 해석을 `crawler.base_crawler.resolve_chrome_driver()` 한 곳으로 모았다
(Selenium Manager 먼저, 실패하면 webdriver_manager). 그런데 `audit_viewport.py`(2026-08-21)는
그보다 나흘 먼저라 **`ChromeDriverManager().install()` 를 직접 부른다** — 즉 #196 이 고친
"Are you offline?" 오진 경로가 이 도구에만 남아 있다. (a) 를 할 때 함께 정리할 자리다.

---

## 25. DB Contract — 마이그레이션 정본 스키마와 대조했다

로컬 `auction.db` 는 021~026 이 밀려 있어(승인 영역) 기준이 될 수 없다. 그래서 임시
디렉터리에 **부트스트랩 3단계**(`init_db` → `migrate_v4_1` → `run_migrations`)로 정본
스키마를 만들어 비교했다. 운영/개발 DB 는 건드리지 않았다.

```
정본 스키마        테이블 28개 / 마이그레이션 26개 (최신 026_create_favorite_notes.sql)
로컬 auction.db    마이그레이션 20개 -> 미적용 6개
                   정본에만 있는 테이블  favorite_notes
                   정본에만 있는 컬럼    auction_item.building_area / land_area
```

**이 6개가 파이썬 실패 4건의 전부이자 유일한 원인**이라는 것이 숫자로 확정된다.
(면적 폴백이 아직 필요한 이유도 같다 — §4.)

### API 응답 화이트리스트 ↔ 정본 스키마

`api/v1/item.py` 가 공개 응답에 싣는 세 테이블의 화이트리스트를 정본 스키마와 대조했다
(BUGS #254 가 `dict(row)` 덤프를 막으려고 만든 목록이다).

```
_TENANT_FIELDS  (tenant_rights)   12 / 12   불일치 0
_CASE_FIELDS    (auction_case)     9 /  9   불일치 0
_RIGHTS_FIELDS  (rights_summary)  21 / 21   불일치 0
```

**스키마에 없는 필드 0 / 응답에서 빠진 컬럼 0.** 즉 화이트리스트는 정본 스키마와
정확히 일치하고, `test_public_endpoint_exposure.py` 가 그것을 계속 붙잡는다.

---

## 26. BUGS.md 의 "해결" 주장 전수 대조

`docs/README.md` 가 BUGS.md 를 "알려진 문제점과 해결 내역"으로 규정하므로 **이력 문서**다.
그래도 "해결" 이라고 적힌 항목이 **근거로 든 대상이 실재하는지**는 별개 문제라 전수로 봤다.

```
항목            268건
해결/완료 표기   200건
실재하지 않는 대상을 인용   9건
   test_reality.py x4        -> `audit_test_reality.py` 의 부분 문자열 (검사기 오탐)
   src/middleware.ts (#25)   -> proxy.ts 로 개명(Sprint 50). 당시 파일명은 정확
   SearchFilters.tsx (#35)   -> 삭제(Sprint 51). 당시 파일명은 정확
   migrate_doc_collect.py / 016_create_audit_logs.sql (#57) -> 대체·개명
   storage/runlock.py (#132) -> "처음엔 만들었는데" 라는 경위 서술
   test_queue_multiprocess_claim.py (#268) -> **이번 세션에 이미 정정한 것**
```

**근거 없는 "해결" 은 0건이다.** 오탐 4건을 빼면 남는 5건은 전부 "그때 그 파일을 고쳤다"는
정확한 이력이고, 유일한 진짜 문제였던 #268 은 §15 에서 이미 닫았다.
이력 문서를 현재 이름으로 고쳐 쓰지 않았다 — 그것은 사료를 지우는 일이다.

같은 방법으로 두 문서를 더 봤다.

```
docs/CURRENT_STATE.md   테스트 파일 인용 53종 -> 실재하지 않는 것 0
docs/CHANGELOG.md       테스트 파일 인용 46종 -> 실재하지 않는 것 0
```

## 성능 실측 (2026-08-31, 실서버 · auction_item 1,876행 · 12회 중앙값)

```
기본 검색(20건)              5.4 ms      최대 페이지(100건)      8.4 ms
시도 필터                    6.2 ms      자유텍스트 주소          6.4 ms
물건종류 다중                5.6 ms      정렬                    6.1 ms
깊은 페이지(offset 1,780)    7.4 ms      상세                    4.6 ms
플랜                         3.4 ms      문서 통계                5.3 ms
지역 목록                    3.9 ms
```

**이번 변경으로 느려진 곳이 없다.** 이 세션은 쿼리를 하나도 바꾸지 않았고
(`document_queue` 의 상태 리터럴을 바인딩으로 옮긴 것은 실행 계획이 같다),
프런트 변경도 전부 순수 함수다. 더 큰 N 의 프로파일은
`docs/SPRINT134_PERFORMANCE_SCALE_MEASUREMENT.md` 를 그대로 둔다.

## 작업하다 걸린 함정 하나 — 개행

이 저장소에는 **HEAD 가 CRLF 로 커밋된 파일**이 섞여 있다(`docs/CLAUDE.md` 346줄,
`docs/architecture.md` 121줄, `tests/source-contract.test.mjs` 등). 파이썬으로
`open(...).read()` -> `open(..., newline='').write()` 하면 CRLF 가 조용히 LF 로 바뀌고,
`git diff` 는 autocrlf 때문에 **아무 변화도 보여 주지 않는다**(`git status` 만 M 으로 뜬다).

`test_schema_hygiene.py` 의 `CRLF 로 커밋된 파일을 LF 로 다시 쓴 것 없음` 검사가
이것을 정확히 잡아 준다 — 이 세션도 그 검사 덕분에 두 파일을 되돌렸다.
파일을 프로그램으로 고칠 때는 **읽은 바이트의 개행을 그대로 되쓴다.**

**BOM 도 같다.** 파이썬으로 `encoding='utf-8-sig'` 로 쓰면 원래 없던 BOM 이 붙는다.
`test_schema_hygiene.py` 의 `작업 중 BOM이 조용히 바뀐 파일 없음` 검사가 이것도 잡아 준다 —
이 세션에서 `test_queue_safety_invariants.py` 에 BOM 을 붙였다가 그 검사로 되돌렸다.
이 저장소는 BOM 이 **있는 파일과 없는 파일이 섞여 있다**(`storage/database.py` 는 있고
`test_queue_safety_invariants.py` 는 없다). 읽은 그대로 되쓰는 것 외에 규칙은 없다.

## 남은 위험

- **면적의 두 구현은 아직 공존한다**(폴백). 운영 DB 에 025 가 적용되고 컬럼이 채워져야
  프런트 파서를 뺄 수 있다. 그때까지는 `displayArea()` 한 함수가 경계다.
- 이 세션의 검사들은 **소스 대조**다. 런타임에만 갈라지는 문제(예: 서버가 실제로 어떤
  로케일/시간대에서 도는가)는 여전히 배포 환경 확인이 필요하다.

## 수정 파일

```
src/lib/format.ts                   DISPLAY_LOCALE/formatNumber, DISPLAY_TIME_ZONE/formatDday, serverArea/displayArea
src/app/search/ResultList.tsx       formatDday 이관, 면적 출처 변경, formatNumber
src/app/search/SearchScreen.tsx     formatNumber
src/app/search/SearchForm.tsx       formatNumber
src/app/search/types.ts             면적 키 선언 + 미지원 서술 정정
src/app/properties/[id]/page.tsx    formatWon 5곳, formatDday import 경로
src/app/favorites/import/page.tsx   서비스명 2곳
storage/migrate_v4_1.py             property_type 어휘 정정 + [VOCAB-TABLE]
normalizer/mylist_import.py         죽은 검사 인용 정정
docs/backend.md                     property_type 어휘 정정 + [VOCAB-TABLE]
docs/frontend.md                    /properties·src/login stale 6건 정정
docs/architecture.md                Supabase 경로 stale 2건 정정
tests/format.test.mjs               로케일 / D-day / 면적 회귀 (+24건)
tests/source-contract.test.mjs      로케일 / D-day / types / 브랜드 / 면적 소스 계약 (+19건)
test_property_type_vocabulary.py    어휘 표 ↔ DB 대조 검사 신설
test_favorite_import.py             §13 강화(매핑·되붙이기·죽은 인용)
test_doc_pdf_iframe.py              신설
storage/database.py                 QUEUE_STATUS_DONE/FAILED + QUEUE_STATUSES, SQL 리터럴 8곳 -> 바인딩
api/v1/doc_stats.py                 queue_failed 를 상수로
test_queue_safety_invariants.py     큐 상태 어휘 계약 검사 신설
tests/frontend-contract.test.mjs    응답 ↔ 타입 대조 검사 신설(살아 있는 서버)
api/constants.py                    DocumentStatus.NO_IMAGE + DOCUMENT_STATUSES_IN_USE
test_db_write_failure_modes.py      신설 (DB 쓰기 장애 거동 6절)
docs/BUGS.md                        #268 의 없는 검사 인용 정정
api/v1/payments.py                  registry_requests 상태 리터럴 2곳 -> 바인딩
api/v1/doc_stats.py                 문서 종류/상태 리터럴 -> 상수 + 바인딩
test_state_machines.py              상태 리터럴 소스 계약 신설
test_schema_hygiene.py              새 SQL 지점 2건 인벤토리 등록
```

**제품 동작 변경은 셋뿐이고 전부 정책을 따라간 것이다** —
비 ko-KR 브라우저의 구분자, 비 KST 브라우저의 D-day, '평' 표기 물건의 카드 면적.
한국에서 보는 사용자의 화면은 바뀌지 않는다.
