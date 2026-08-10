# DOJOONPASS Frontend Master Spec

Version: 1.2
Status: 확정 — **P0/P1 구현 완료(Sprint 44~45) + 인증 체인 복구(Sprint 46)**
Last Updated: 2026-08-10
Scope: DOJOONPASS(서비스명 **콕찰**) Frontend 전체

---

## 0. 이 문서의 위치

이 문서는 **DOJOONPASS Frontend 전체 구현의 최상위 기준(Single Source of Truth)**이다.
전체 구조 · 라우팅 · 인증 경계 · 공통 Layout · 공통 UX 원칙을 담당한다.

### 문서 간 역할 분담

| 문서 | 담당 범위 | 이 문서와의 관계 |
|---|---|---|
| **`docs/FRONTEND_MASTER_SPEC.md`** (본 문서) | Frontend 전체 구조 · 라우팅 · 인증 경계 · 공통 Layout · 공통 UX | 최상위 |
| `search/00_SEARCH_MVP.md` v0.2 | **검색 화면 상세 요구사항**(검색조건 필드, 결과 표시 항목, 정렬, 페이지네이션, 검색 화면 내부 구조) | **하위 상세 기준. 본 문서가 대체하지 않는다** |
| `docs/frontend.md` | 현재 코드의 **as-is 기록**(구현 현황 · 알려진 문제점) | 현황 기록용. 정책 결정은 본 문서 |
| `docs/search-engine.md` | 검색 **백엔드/API** 사양 | API 계약의 근거 |
| `docs/roadmap.md` | Sprint 우선순위 | 실행 계획 |
| `docs/CLAUDE.md` | 프로젝트 공통 규칙(Breaking Change 금지 등) | 상위 규칙. 본 문서보다 우선 |

**충돌 시 우선순위**: `docs/CLAUDE.md` > 본 문서 > `search/00_SEARCH_MVP.md` > `docs/frontend.md`
단, **검색 화면의 세부 요구사항은 `00_SEARCH_MVP.md`가 우선**이다(본 문서는 검색 세부를 재정의하지 않는다).

### 조사 기준

본 문서는 2026-08-10 아래를 **실제 코드로 전수 대조**해 작성했다.
`src/app/**`, `src/components/**`, `src/lib/api.ts`, `src/middleware.ts`, `api_server.py`, `api/v1/*.py`,
`search/00_SEARCH_MVP.md`, `docs/frontend.md`, `docs/search-engine.md`, `docs/roadmap.md`, `docs/CLAUDE.md`

---

## 1. Frontend 목표

1. **첫 화면부터 경매 검색이 가능하다.**
2. **로그인보다 경매 물건 탐색을 우선한다.** 로그인은 진입 장벽이 아니라 개인화 기능의 조건이다.
3. **검색 → 목록 → 상세 조회**의 사용자 흐름이 끊기지 않고 명확하다.
4. **검색은 비로그인 사용자에게 공개한다.**
5. **상세 조회는 로그인 사용자에게만 공개한다.**

---

## 2. 전체 페이지 구조

### 2.1 실제 존재하는 route (2026-08-10 코드 확인)

`src/app/` 하위만 Next.js App Router의 유효 라우트다.

| 경로 | 파일 | 역할 | 접근 정책 (확정) |
|---|---|---|---|
| `/` | `src/app/page.tsx` | **첫 진입 화면 = 경매 검색 화면**. 검색 Form + 결과 목록 | **공개** |
| `/search` | `src/app/search/page.tsx` | `/`와 동일한 검색 화면. 기존 링크/북마크 호환 유지 | **공개** |
| `/login` | `src/app/login/page.tsx` + `actions.ts` | 로그인 / 회원가입 통합 폼 | **공개** |
| `/properties/[id]` | `src/app/properties/[id]/page.tsx` | 물건 상세 | **로그인 필수** |
| `/favorites` | `src/app/favorites/page.tsx` | 관심물건 목록 | **로그인 필수** (Sprint 45부터 middleware 서버 게이트) |
| `/properties/recent` | `src/app/properties/recent/page.tsx` | 최근 본 물건 목록 | **로그인 필수** |
| `/properties` | `src/app/properties/page.tsx` | **레거시 목록 화면**(Supabase `properties` 직접 조회) | 로그인 필수 (현행 유지) |

### 2.2 라우트가 아닌 코드

- `src/login/`(`page.tsx`, `action.ts`) — `src/app/` 밖이라 **Next.js가 라우팅하지 않는 도달 불가 코드**.
  구 브랜드명 "도준 경매 패스"를 사용하고 있어 `docs/decision-log.md`의 서비스명 규칙에 어긋난다.
  **프로젝트 규칙상 "사용 여부가 확실하지 않은 코드는 임의 삭제하지 않는다" → 이번 범위에서 삭제하지 않는다.**

### 2.3 `/properties`(레거시)에 대한 기록

`/properties`는 다음 문제를 이미 가지고 있다(`docs/frontend.md` 기록, 2026-08-10 코드 재확인).

- 데이터 소스가 Supabase `properties` 테이블 직접 조회 — 크롤러 데이터(`auction_item`)가 아니다
- 목록 카드의 링크 id와 상세(`/properties/[id]` → FastAPI `auction_item`)의 id **채번 체계가 다르다**
  → 엉뚱한 물건이 열리거나 404가 난다
- 자체 `formatPrice`가 공용 `src/lib/format.ts` 구현과 다르게 동작한다
- 자체 `SearchFilters.tsx`가 `/search`의 `SearchForm`과 완전히 다른 지역/가격 데이터를 쓴다

**본 문서는 `/properties`의 처리 방향(FastAPI 전환 vs 화면 폐지)을 결정하지 않는다** — 기존부터
미결정 상태인 항목이며, 임의 결정 금지 규칙에 따라 §16 SKIP 항목으로 남긴다.
다만 **`/`가 더 이상 `/properties`로 redirect하지 않게 되므로**, 이 화면은 사용자 동선에서
사실상 분리된다(직접 URL 입력 외 진입 경로 없음).

---

## 3. 확정 인증 정책

**이 절은 확정 정책이다. 임의로 변경하지 않는다.**

### 3.1 공개 (비로그인 사용자도 가능)

- 첫 화면(`/`) 접속
- 검색조건 입력
- 검색 실행
- 검색 결과 조회
- 경매 물건 목록 탐색
- 정렬
- 페이지 이동 / 페이지 크기 변경

공개 화면에서 사용하는 API도 비인증으로 동작해야 한다:
`GET /api/v1/search`, `GET /api/v1/search/regions`.
두 API는 이미 **선택적 인증**(`HTTPBearer(auto_error=False)`) 구조다 —
토큰이 있으면 결과의 `is_favorited`를 채우고, 없거나 검증에 실패해도 검색은 그대로 진행된다.
**이 구조를 필수 인증으로 바꾸지 않는다.**

### 3.2 로그인 필요

| 액션 | 요구 시점 |
|---|---|
| **물건 상세 조회 (`/properties/[id]`)** | **화면 진입 시** |
| 관심물건 등록/해제 | 버튼 클릭 시 |
| 관심물건 조회 (`/favorites`) | 화면 진입 시 |
| 최근 조회 (`/properties/recent`) 등 개인화 | 화면 진입 시 |
| 검색조건 저장 / 불러오기 / 삭제 | 저장·삭제 클릭 시 |
| 구독 | 액션 시 |
| 결제 | 액션 시 |
| 등기부 신청 / 다운로드 | 액션 시 |

### 3.3 상세 조회 게이트 (확정)

**검색 결과에서 물건의 상세 조회를 클릭하는 순간 로그인으로 이동한다.**

- 비로그인 사용자가 **목록까지 보는 것은 허용**한다.
- 비로그인 사용자에게 **`/properties/[id]` 상세 조회는 허용하지 않는다.**
- 이 정책은 **확정 사항이다.** PM 결정 대기 항목으로 기록하지 않는다.
  (이전 문서들이 "PM 결정 대기"로 기록하고 있던 상태는 2026-08-10 본 결정으로 종료됐다.)
- 게이트 위치: `src/middleware.ts`의 `/properties/*` 서버사이드 게이트를 **그대로 사용**한다.
  이미 구현되어 있으므로 새 게이트 로직을 추가하지 않는다.

### 3.4 로그인 Redirect 계약 (확정)

로그인으로 보낼 때 **원래 이동하려던 URL 전체를 유지**해야 한다.

1. 게이트/액션은 `/login?redirect=<원래 URL>`로 이동시킨다.
2. `<원래 URL>`은 **pathname + query string 전체**다.
   - 검색 화면에서의 액션 → 검색조건(쿼리스트링)이 보존되어야 한다.
   - 상세 진입 차단 → `?ids=...&i=...`(목록 내 이전/다음 물건 이동 컨텍스트)까지 보존되어야 한다.
3. 로그인 성공 후 **`redirect` 대상 URL로 복귀**한다.
4. Open Redirect 방어(`sanitizeRedirectPath`)는 **그대로 유지**한다 — `/`로 시작하는 내부 상대경로만
   허용하고 `//evil.com` · `/\evil.com`는 거부한다.
5. `redirect`가 없거나 거부된 경우의 기본 복귀 경로는 **`/`(검색 화면)**다.

**구현 상태(2026-08-10 Sprint 44 완료)**: `src/middleware.ts`는 `pathname + search` 전체를
넘기고, `login/actions.ts`의 기본 복귀 경로는 `/`다. 상세 화면의 세션 만료 후 액션 3곳도
`loginRedirectUrl()`로 통일했다(`docs/BUGS.md` #25). 이 계약은 `tests/frontend-contract.test.mjs`가
회귀 테스트로 고정하고 있다(mutation 테스트로 검출력 확인 완료).

---

## 4. 첫 화면

`/`는 로그인 화면이 아니다. **`/` 자체가 경매 검색 화면이다.**

```
Header
  ↓
검색 Form
  ↓
정렬 / 결과 건수
  ↓
경매 물건 목록
  ↓
페이지네이션
```

- `/`는 **어떤 경로로도 자동 redirect하지 않는다**(로그인 여부 무관).
- 검색 결과를 보기 위해 **별도의 검색 페이지로 이동시키지 않는다.** 검색 실행은 현재 URL의
  쿼리스트링만 갱신하고, 결과는 같은 페이지 하단에 이어서 렌더한다.
- 쿼리 파라미터가 없는 최초 진입에서도 목록은 비어 있지 않다 — 파라미터 없는
  `GET /api/v1/search` 호출이 백엔드 기본 동작(`include_closed=false` → `auction_date >= 오늘`,
  기본 정렬 `auction_date DESC, fail_count DESC`)으로 진행 중인 물건을 반환한다.
  **"추천/인기 물건" 같은 새 개념을 만들지 않는다.**
- 검색 화면 내부 구조의 상세는 `search/00_SEARCH_MVP.md` §1·§3~§7을 따른다.

---

## 5. 공통 Layout

### 5.1 현재 코드에 존재하는 것 (조사 결과)

| 요소 | 현황 |
|---|---|
| `src/app/layout.tsx` | RootLayout. metadata(`콕찰 — 법원경매 검색`) + `lang="ko"` + `body` flex column만 정의. **공통 Header 없음** |
| 공통 Header 컴포넌트 | **존재하지 않는다.** 각 page.tsx가 상단 바를 개별 작성 |
| `src/components/PrimaryNav.tsx` | 검색 / 최근 본 물건 / 관심물건 3개 링크. `/search`·`/properties`·`/favorites`·`/properties/recent` 상단 바가 공유 |
| `src/app/properties/LogoutButton.tsx` | 로그아웃 버튼. **`/properties` 헤더에만 연결되어 있다** |
| `src/app/globals.css` | `create-next-app` 기본값(배경/전경 변수, 폰트)만. 디자인 토큰 파일 없음 |

**결과**: 로그아웃은 레거시 `/properties`에서만 가능하고, 컨테이너 규칙은 화면마다 제각각이다.

### 5.2 확정 원칙

- 모든 주요 페이지는 **동일한 중앙 컨테이너 체계**를 사용한다.
- 최대 폭은 **1320px** — 현재 `/search`에서 확정된 값을 그대로 표준으로 채택한다.
  **새로운 max-width 값을 임의로 만들지 않는다.**
- 컨테이너 규칙: `max-w-[1320px] mx-auto` + 좌우 패딩(모바일 16px / 데스크톱 32px)
- **화면 전체**: 배경 영역(풀블리드 배경색/보더 허용)
- **내부 콘텐츠**: 중앙 정렬
- **좌우 과도한 여백 금지**
- **데스크톱에서 콘텐츠가 화면 전체로 늘어나지 않게 한다** — 특히 입력 필드 하나가
  1320px를 가로지르지 않아야 한다.

### 5.3 공통 Header

- 공통 Header를 **하나** 두고 모든 주요 페이지가 공유한다.
- Header 배경은 화면 폭 전체, **Header 내부 콘텐츠는 본문과 같은 1320px 컨테이너**에 정렬한다.
  (헤더 좌측 끝과 본문 좌측 끝이 한 줄로 맞아야 한다.)
- Header 구성: 서비스명 / `PrimaryNav` / 인증 상태 영역
  - 비로그인: 로그인 링크
  - 로그인: 사용자 이메일 + 로그아웃
- **`PrimaryNav`와 `LogoutButton`은 기존 컴포넌트를 그대로 재사용한다.** 같은 기능을 새로 만들지 않는다.
- 로그아웃 후 이동 경로는 **`/`(검색 화면)**다.

---

## 6. 반응형

Tailwind 기본 breakpoint를 그대로 사용한다(`md` 768px / `lg` 1024px / `xl` 1280px).
새 breakpoint를 만들지 않는다.

| 폭 | 검색 Form | 결과 목록 |
|---|---|---|
| 모바일 (< 768px) | 1열 | 1열 |
| 태블릿 (768~1279px) | 2열 | 2열 |
| 데스크톱 (≥ 1280px) | 3열 | 3열 |

- 검색 Form과 결과 목록 **모두** 화면 폭에 맞게 밀도를 조정한다.
- 열 배치는 **레이아웃(컨테이너 클래스) 변경만**이다. 각 섹션의 필드 구성 · 컴포넌트 state ·
  `buildSearchQuery()` 결과는 변경하지 않는다.
- 상세(`/properties/[id]`)와 목록형 화면(`/favorites`, `/properties/recent`)도 동일한 컨테이너
  체계를 적용한다. 상세의 카드 배치 세부는 P1 이후 범위다(§14).

---

## 7. Navigation

### 7.1 현재 코드 기준 흐름

`PrimaryNav`(`src/components/PrimaryNav.tsx`)가 제공하는 링크는 3개다.

| 항목 | 링크 | 접근 |
|---|---|---|
| 검색 | `/search` | 공개 |
| 최근 본 물건 | `/properties/recent` | 로그인 필요 |
| 관심물건 | `/favorites` | 로그인 필요 |

로그인/로그아웃은 `PrimaryNav`에 없다. 로그아웃은 `/properties` 헤더에만 있다.

### 7.2 확정 원칙

- Navigation 구성: **검색 / 최근 본 물건 / 관심물건 / 로그인·로그아웃**
- **검색은 공개 기능이다.** 비로그인 상태에서도 Navigation에 노출하고 이동 가능하다.
- **개인화 기능(최근 본 물건 / 관심물건)은 로그인 필요**다.
  - 비로그인 상태에서도 **메뉴는 노출한다**(숨기지 않는다).
  - 클릭하면 §3.4 계약에 따라 로그인으로 유도한다.
- 로그인/로그아웃은 공통 Header의 인증 상태 영역에서 처리한다(§5.3).
- 검색 메뉴의 링크 대상은 `/`로 한다(첫 화면 = 검색 화면). `/search`도 계속 동작한다.

---

## 8. Search

**검색 화면의 상세 기준은 `search/00_SEARCH_MVP.md` v0.2다.** 본 문서는 그것을 대체하지 않는다.

### 8.1 재사용 대상 (전부 이미 구현됨 — 재구현 금지)

| 컴포넌트 | 경로 | 역할 |
|---|---|---|
| `SearchForm` | `src/app/search/SearchForm.tsx` | 검색조건 입력 전체(주소/법원 토글, 물건정보, 가격, 일정·유찰, 면적·특수) + URL↔폼 양방향 복원 |
| `SearchPresets` | `src/app/search/SearchPresets.tsx` | 검색조건 저장/불러오기/삭제 (인증 필요 액션) |
| `SortBar` | `src/app/search/SortBar.tsx` | 정렬 7종 + ASC/DESC 토글 |
| `ResultList` | `src/app/search/ResultList.tsx` | 결과 카드 목록, 총 건수, 면적 파싱, D-day, 상세 이동 링크 |
| `Pagination` | `src/app/search/Pagination.tsx` | 페이지 이동 + size(20/30/50/100) |
| `FavoriteButton` | `src/app/search/FavoriteButton.tsx` | 즐겨찾기 토글 (인증 필요 액션) |
| `PriceRangeSelect` | `src/components/PriceRangeSelect.tsx` | 가격 프리셋 select 쌍 |
| `RangeSelect` | `src/components/RangeSelect.tsx` | 범용 최소/최대 select 쌍 |
| `PropertyTypeTree` | `src/components/PropertyTypeTree.tsx` | 물건종류 체크박스 트리(5그룹 69항목) |
| `SearchAccordionSection` | `src/components/SearchAccordionSection.tsx` | 검색조건 접기/펼치기 섹션 |
| `formatPrice` | `src/lib/format.ts` | 공용 가격 표기 |
| `SearchQueryParams` / `SearchResponse` | `src/app/search/types.ts` | 검색 DTO |

### 8.2 확정 원칙

- **검색 API 계약은 변경하지 않는다.**
- **검색 화면 재구성을 이유로 새로운 검색 API를 만들지 않는다.**
- 검색 실행은 **현재 URL(pathname)을 유지**한 채 쿼리스트링만 갱신한다.
  `/`에서 검색하면 `/`에 머물고, `/search`에서 검색하면 `/search`에 머문다.
- 비로그인 상태에서도 즐겨찾기 버튼과 검색조건 저장 UI는 **보인다**(숨기지 않는다).
  누르는 시점에만 로그인으로 유도한다.

---

## 9. Property 상세 (`/properties/[id]`)

### 9.1 확정 정책

**로그인 필수.**

- 비로그인 사용자가 검색 결과에서 물건을 클릭하면 **로그인으로 이동**한다.
- 로그인 후 **해당 상세 URL로 복귀**한다(§3.4 — 쿼리스트링 포함).
- 게이트는 `src/middleware.ts`의 기존 `/properties/*` 서버사이드 검사를 사용한다.

### 9.2 현재 상세페이지의 실제 정보 구성 (코드 조사 결과)

`src/app/properties/[id]/page.tsx`(클라이언트 컴포넌트)가 `GET /api/v1/item/{id}` 응답으로 렌더한다.

| 영역 | 내용 |
|---|---|
| 상단 바 | 뒤로가기 · "매물 상세" · 즐겨찾기 토글 · 등기열람 무료 잔여 횟수 |
| 이전/다음 물건 | 검색 결과에서 넘어온 경우에만 노출(`?ids=`,`?i=` 컨텍스트). 없으면 버튼 자체를 숨김 |
| 기본 정보 | 물건종류, D-day 배지, 소재지, 사건번호(+물건번호), 지번, 최근 수집일 |
| 가격·일정 | 감정가, 최저입찰가, 입찰기일, 담당법원, 사건번호, 진행상태, 입찰가율, 유찰횟수, 검증상태 |
| 권리분석 | 점유관계, 공실여부, 임대차 인원수, 명도난이도, 위험도, 인수금액, 특이사항 (`rights_summary` 있을 때만) |
| 권리분석 신뢰도 | confidence, 정보원(REGISTRY 제외), 충돌, 경고 (`rightsAnalysis.ts`) |
| 사건 정보 | 사건종류, 접수일, 배당요구종기일 |
| 임차인 상세 | SPEC(매각물건명세서) 기준 임차인 목록 |
| 현황조사서 임차인 | STATUS 기준 임차인 목록 |
| 관련 문서 | SPEC / APPRAISAL / STATUS 상태 + 클릭 시 iframe 뷰어(HEAD로 존재 확인) |
| 등기부등본 | 신청 / 구독(플랜·결제주기 선택) / 초과분 결제 / 상태 표시 / 다운로드 |

### 9.3 확정 원칙

- 위 정보 구성과 등기부/구독/결제 흐름은 **변경 대상이 아니다.** 본 문서의 범위는
  **접근 정책 + 컨테이너/반응형 적용**이다.
- 상세 진입 시 최근조회 기록은 백엔드가 처리한다 — `GET /api/v1/item/{id}`가 유효 토큰을 받으면
  `record_view()`를 호출한다. **프론트가 별도로 최근조회 기록 API를 호출하지 않는다**
  (해당 용도의 POST 엔드포인트는 존재하지 않는다).
- 금액/플랜은 서버(`GET /api/v1/plans`)가 단일 Source of Truth다. 프론트에 가격 상수를 두지 않는다.
- 즐겨찾기 성공/실패 분기는 **도메인 Error Code**(`ERROR_CODES`)로만 한다. 메시지 문구로 분기하지 않는다.

---

## 10. API 계약

**아래 path / parameter / response / 인증 방식을 임의로 변경하지 않는다.**
호출은 `src/lib/api.ts`의 기존 래퍼만 사용한다.

### 10.1 현재 Frontend가 사용하는 API

| Endpoint | 인증 | 사용 화면 | 응답 형태 |
|---|---|---|---|
| `GET /api/v1/search` | 선택적 Bearer | `/`(예정), `/search` | `{ total, page, size, total_pages, items[] }` — **envelope 아님** |
| `GET /api/v1/search/regions?sido=` | 불필요 | `SearchForm` | `{ sido, sigungu[] }` |
| `GET /api/v1/item/{id}` | 선택적 Bearer | `/properties/[id]` | 물건 상세 객체 — **envelope 아님**. 토큰 있으면 `is_favorited` 채움 + `record_view()` |
| `GET /api/v1/item/{id}/documents/{doc_type}` | 불필요 | 상세 문서 뷰어(iframe/HEAD) | 파일 |
| `POST /api/v1/favorites` | 필수 | `FavoriteButton`, 상세 | envelope |
| `DELETE /api/v1/favorites/{item_id}` | 필수 | `FavoriteButton`, 상세 | envelope |
| `GET /api/v1/favorites` | 필수 | `/favorites` | envelope |
| `GET /api/v1/recent-items` | 필수 | `/properties/recent` | envelope |
| `GET /api/v1/search-presets` | 필수 | `SearchPresets` | envelope |
| `POST /api/v1/search-presets` | 필수 | `SearchPresets` | envelope |
| `DELETE /api/v1/search-presets/{id}` | 필수 | `SearchPresets` | envelope |
| `GET /api/v1/plans` | 불필요 | 상세(구독 카드) | envelope |
| `POST /api/v1/payments` | 필수 | 상세(구독/초과결제) | envelope |
| `POST /api/v1/registry-requests` | 필수 | 상세(등기부 신청) | envelope |
| `GET /api/v1/registry-requests` | 필수 | 상세(기존 신청 조회) | envelope |
| `GET /api/v1/registry-requests/{id}/download` | 필수 | 상세(다운로드) | **파일 또는 JSON** — `fetchAuthedRaw`로 Content-Type 분기 |

Frontend가 사용하지 않는 백엔드 라우터: `admin`, `doc_stats`, `payments` 조회 계열 일부.
(Admin 화면은 미구현 — §16)

### 10.2 클라이언트 래퍼 (`src/lib/api.ts`)

| 함수 | 용도 |
|---|---|
| `fetchJSON<T>(path, token?)` | 비-envelope GET(검색/상세). 토큰 optional |
| `fetchAuthedJSON<T>(path, token)` | envelope GET(인증 필요) |
| `postJSON<T>` / `deleteJSON<T>` | envelope POST/DELETE(인증 필요) |
| `fetchAuthedRaw(path, token)` | 파일 또는 JSON일 수 있는 응답 전용. `!res.ok`에서 던지지 않음 |
| `ApiError` / `ApiEnvelope` / `ERROR_CODES` | 오류·분기 규약. **분기는 `error` 코드로, `message` 문구로 하지 않는다** |

### 10.3 변경 금지 사항

- offset 페이지네이션(`page` / `size`) 방식
- `GET /api/v1/search` · `GET /api/v1/item/{id}`의 응답 구조와 필드명
- `auction_item` 컬럼명
- `search` / `item` / `search/regions`의 **선택적 인증 구조**(필수 인증으로 승격 금지)
- envelope 사용 여부(검색/상세는 envelope 아님 — 통일하려 하지 않는다)

---

## 11. 공통 컴포넌트

### 11.1 현재 실제 존재하는 컴포넌트 (2026-08-10 전수 확인)

**`src/components/`** — 5개, 전부 사용 중

| 컴포넌트 | 사용처 |
|---|---|
| `PrimaryNav` | `/search`, `/properties`, `/favorites`, `/properties/recent` |
| `PriceRangeSelect` (+ `PRICE_OPTIONS`) | `SearchForm` |
| `RangeSelect` | `SearchForm`(최저가율, 유찰횟수) |
| `PropertyTypeTree` (+ `PROPERTY_CATEGORY_GROUPS`) | `SearchForm` |
| `SearchAccordionSection` | `SearchForm` |

**라우트 지역 컴포넌트**

| 컴포넌트 | 위치 |
|---|---|
| `SearchForm` / `SearchPresets` / `SortBar` / `ResultList` / `Pagination` / `FavoriteButton` | `src/app/search/` |
| `SearchFilters` / `LogoutButton` | `src/app/properties/` |
| `rightsAnalysis.ts`(`mapSpecView` / `assembleRightsAnalysis`) | `src/app/properties/[id]/` |

**공용 유틸** — `src/lib/format.ts`(`formatPrice`), `src/lib/api.ts`,
`src/lib/supabaseClient.ts`(클라이언트 세션), `src/lib/supabaseServer.ts`(서버 세션)

### 11.2 확정 원칙

- **동일 기능의 중복 컴포넌트를 새로 만들지 않는다.** 기존 컴포넌트 재사용을 우선한다.
- 공통 Header는 새로 만들되(현재 존재하지 않음), **내부는 기존 `PrimaryNav` + `LogoutButton`을
  조합**한다. 네비게이션/로그아웃을 다시 구현하지 않는다.
- 검색 화면을 `/`와 `/search`가 공유할 때 **화면 컴포넌트를 복제하지 않는다** — 하나를 두고 둘이 함께 쓴다.
- `formatPrice` 중복: `properties/page.tsx`와 `properties/[id]/page.tsx`에 공용 구현과 다르게 동작하는
  지역 함수가 남아 있다. **표기 기준 통일은 UX 결정이 선행되어야 하므로 이번 범위에서 통일하지 않는다**(§16).
- `SearchFilters.tsx`(레거시 `/properties` 전용)는 `SearchForm`과 통합하지 않는다 —
  `/properties`의 처리 방향이 미결정이기 때문이다(§2.3).

---

## 12. 디자인 원칙

사용자가 제공한 **Tank Auction 종합검색 화면을 benchmark로 사용**한다.

### 12.1 참고 대상

- 정보 밀도
- 검색조건 배치
- 검색 → 결과 흐름
- 중앙 정렬
- 데스크톱 화면 활용
- 물건 목록 노출 방식

### 12.2 복제 금지

**Tank Auction의 브랜드/디자인을 그대로 복제하지 않는다.** 색상 · 타이포 · 로고 · 브랜드 요소는
콕찰의 것을 사용한다. 참고 대상은 **정보 구조와 화면 밀도/정렬**에 한정한다.
(원본 HTML: `search/reference/01_SEARCH_FORM.html`, `02_SEARCH_RESULT.html`)

### 12.3 핵심 원칙

- 첫 화면에서 바로 검색
- 검색 결과를 같은 화면에서 탐색
- 과도한 좌우 여백 제거
- 콘텐츠 중앙 정렬
- 데스크톱 정보 밀도 확보
- 모바일 1열 대응
- 기존 기능/API 계약 유지

### 12.4 목록 표현 방식

- **1단계(현행 범위)**: 기존 `ResultList` 카드를 재사용하고 데스크톱에서 열 수만 늘려 밀도를 확보한다.
  카드 내부 정보 구성은 변경하지 않는다.
- **2단계(범위 밖)**: 탱크옥션식 표(table) 뷰. 카드/표 이중 구현이 되므로 별도 결정 후 진행한다.
  이번 범위에서 만들지 않는다.

---

## 13. AS-IS / TO-BE

아래 AS-IS는 **2026-08-10 Sprint 44 이전**의 코드 기준 조사 결과이며, TO-BE는 같은 날
전부 구현됐다(`docs/CHANGELOG.md` 2026-08-10). 표는 "무엇을 왜 바꿨는가"의 근거로 보존한다.
#10(레거시 `/properties`)만 여전히 미결정으로 남아 있다.

| # | 항목 | AS-IS (근거 파일) | TO-BE | 우선순위 |
|---|---|---|---|---|
| 1 | **첫 화면** | `src/app/page.tsx`가 UI 없이 무조건 redirect (로그인 → `/properties`, 비로그인 → `/login`) | `/`가 검색 화면을 렌더. redirect 없음 | P0 |
| 2 | **로그인 redirect** | ① `middleware.ts:42`가 `pathname`만 넘겨 **쿼리스트링을 버림** → 상세의 `?ids=&i=` 컨텍스트 소실 ② `login/actions.ts:6` 기본 복귀 경로가 레거시 `/properties` | ① pathname+search 전체 보존 ② 기본 복귀 `/` | P0 |
| 3 | **검색 진입** | 검색이 별도 화면(`/search`)으로 분리. `SearchForm.handleSearch()`·`SearchPresets.applyPreset()`이 `/search` **하드코딩 push** | `/`가 검색 화면. push는 **현재 pathname 기준** | P0 |
| 4 | **검색 결과** | `/search` 하단에는 이미 이어져 있음(구조 자체는 정상) | `/`에서도 동일하게 이어짐. 결과 0건/오류에도 검색 Form 유지 | P1 |
| 5 | **상세 조회 인증** | `middleware.ts`가 `/properties/*` 게이트 — **정책상 이미 올바름** | 유지. 단 redirect URL 보존(#2)이 함께 고쳐져야 완성 | P0 |
| 6 | **Header** | 공통 Header 없음. 각 page.tsx가 상단 바 개별 작성. **로그아웃이 레거시 `/properties`에만 존재** | 공통 Header 1개. `PrimaryNav`+`LogoutButton` 재사용. 비로그인엔 로그인 링크 | P0 |
| 7 | **중앙 컨테이너** | `/search`만 `max-w-[1320px] mx-auto`. `/login`(`px-6`)·`/properties`(`px-5`)·`/properties/[id]`(`px-4`)·`/favorites`·`/properties/recent`는 풀블리드 | 전 화면 `max-w-[1320px] mx-auto` 통일. Header도 동일 기준 정렬 | P0 |
| 8 | **반응형** | 모바일 1열 레이아웃이 데스크톱 폭으로 그대로 늘어남 — 입력 필드 하나가 1320px를 가로지름 | 모바일 1열 / 태블릿 2열 / 데스크톱 3열 (Form·목록 모두) | P1 |
| 9 | **Navigation** | `PrimaryNav` 3개 링크(검색/최근/관심). 로그인·로그아웃 없음. 검색 링크가 `/search` | 검색/최근/관심 + 로그인·로그아웃. 검색 링크 `/` | P1 |
| 10 | **레거시 `/properties`** | Supabase 직접 조회 + id 채번 불일치로 상세 404 가능 | **미결정 — 이번 범위 밖**(§16). `/`가 더 이상 여기로 보내지 않으므로 동선에서 분리됨 | — |

---

## 14. 구현 우선순위

> **진행 상태(2026-08-10 Sprint 44)**: P0 완료 · P1 완료 · P2는 인증 경계/레이아웃까지 적용됐고
> 기능 자체는 기존 구현 그대로다. 단 **P2의 실제 동작은 아래 §16의 JWT 401 환경 이슈로 막혀 있다**
> (코드가 아니라 Secret 설정 문제).

### P0 — 진입/구조 정상화 ✅ 완료

- 첫 진입 화면(`/` = 검색 화면, redirect 제거)
- 공통 Layout(1320px 중앙 컨테이너 체계)
- Header(공통 Header + 로그인/로그아웃 노출)
- 검색 화면(`/`·`/search` 공유, 검색 실행이 현재 URL 유지)
- 상세 조회 로그인 게이트(기존 게이트 유지 + **redirect URL 전체 보존**)

### P1 — 탐색 품질 ✅ 완료

- 검색 결과(같은 화면 연결, 0건/오류 시 Form 유지)
- 정렬
- 페이지네이션
- 반응형(1/2/3열)
- Navigation

### P2 — 개인화

- 최근조회
- 관심물건
- 검색조건 저장
- 기타 개인화 기능

> 실제 코드/문서와 충돌하는 경우 **근거를 기록하고 임의 결정하지 않는다.**
> 본 문서 작성 중 발견된 충돌은 §13과 §16에 근거와 함께 기록했다.

---

## 15. 완료 기준

### 비로그인 사용자

```
/
 ↓ 검색조건 입력
 ↓ 검색
 ↓ 검색 결과 확인
 ↓ 정렬 / 페이지 이동
 ↓ 물건 선택
로그인 화면
 ↓ 로그인
선택했던 물건 상세페이지로 복귀
```

### 로그인 사용자

```
/
 ↓ 검색
 ↓ 결과
 ↓ 물건 선택
상세 조회
```

### 체크리스트

□ `localhost:3000` 접속 시 로그인으로 redirect되지 않는다
□ 첫 화면이 경매 물건 검색 화면이다
□ 비로그인 상태에서 검색조건 입력 → 검색 실행이 가능하다
□ 검색 결과가 같은 페이지 하단에 이어서 표시된다
□ 첫 로드(조건 없음)에서도 물건 목록이 보인다
□ 비로그인 상태에서 정렬 / 페이지 이동이 동작한다
□ 비로그인 상태에서 물건을 클릭하면 로그인 화면으로 이동한다
□ 로그인 후 **선택했던 물건 상세 URL로 복귀**한다(쿼리스트링 포함)
□ 로그인 상태에서는 물건 클릭 시 바로 상세로 진입한다
□ 비로그인 상태에서 즐겨찾기/검색조건 저장을 누르면 로그인으로 유도되고, 로그인 후 **검색조건이 유지된 채** 복귀한다
□ 헤더와 본문이 같은 중앙 컨테이너(1320px) 기준으로 정렬된다
□ 데스크톱에서 좌우 여백이 과도하지 않고 입력 필드가 화면을 가로지르지 않는다
□ 모바일 / 태블릿 / 데스크톱에서 레이아웃이 깨지지 않는다
□ 모든 주요 화면에서 로그인/로그아웃이 가능하다
□ 기존 검색 / 상세 / 즐겨찾기 / 최근조회 / 등기부 기능의 계약이 그대로 동작한다

---

## 16. 이번 범위에서 결정하지 않은 것 (SKIP)

임의 결정 금지 규칙에 따라 아래는 **결정하지 않고 기록만** 한다.

| 항목 | 상태 | 사유 |
|---|---|---|
| 레거시 `/properties` 처리 (FastAPI 전환 vs 화면 폐지) | 기존부터 미결정 | 2026-08-10 Sprint 48 재조사: 도달 가능한 inbound 링크 **0건** 확정(고아 라우트). 삭제/redirect는 정책 결정이라 SKIP |
| `src/login/`(도달 불가 중복 코드) 삭제 | SKIP | "사용 여부가 확실하지 않은 코드는 임의 삭제하지 않는다"(`docs/CLAUDE.md`) |
| `formatPrice` 표기 기준 통일 | SKIP(표기 결정) | 2026-08-10 Sprint 48: 두 화면에 **글자 단위로 동일**하던 구현은 `formatPriceEok()`로 **중복 제거 완료**(표시 숫자 무변경). 남은 것은 공용 `formatPrice()`와 표기 기준을 통일할지의 UX 결정뿐 |
| 결과 목록 table 뷰 도입 | SKIP | 카드/표 이중 구현. 별도 결정 필요(§12.4) |
| 마이페이지 / Admin 화면 / 권리분석 전용 화면 | 미착수 | 신규 화면 스펙 미정 |
| `SortBar`에 `crawl_date` 정렬 노출 | SKIP | 백엔드는 지원하나 UI 노출은 제품 판단 필요(`types.ts` 주석 기록) |
| 검색 Form 면적조건 / 특수조건 활성화 | 불가 | 백엔드 미지원(`auction_item`에 대응 컬럼 없음). "준비 중" 표기 유지 |
| 상세 페이지 정보 구성 변경 | 범위 밖 | 본 문서 범위는 접근 정책 + 레이아웃 |
| 디자인 토큰 파일 도입 | SKIP | 현재 Tailwind 유틸리티 하드코딩. 도입은 별도 결정 |
| ~~로그인 사용자의 JWT를 FastAPI가 401로 거부~~ | **✅ 2026-08-10 Sprint 46 해결** | 2026-08-10 발견·확정(`docs/BUGS.md` #27). Supabase 프로젝트가 **ES256(비대칭 서명)** 으로 전환됐는데(JWKS 200, `kty=EC`) 백엔드는 `algorithms=["HS256"]` + 공유 시크릿으로만 검증한다(`api/auth.py:20-23`, `item.py:47-48`, `search.py:145-146`). **Secret 교체로는 해결되지 않고 검증 코드를 고쳐야 한다.** Sprint 46에서 `api/auth.py`에 JWKS 기반 ES256 검증을 도입해 해결(HS256 병행 유지). 실제 Supabase 토큰으로 401 → 200 확인. **API 서버 완전 재기동 필요** |
| ~~공통 Header를 `/properties/[id]`에도 적용~~ | **✅ 2026-08-10 Sprint 45 완료** | 상세에서 검색/관심물건/최근 본 물건으로 갈 방법이 뒤로가기뿐이고 로그아웃 경로도 없는 **네비게이션 막다른 길**이었다. 기존 상세 전용 바(뒤로가기·즐겨찾기·무료잔여)는 그대로 두고 `SiteHeader`를 위에 얹는 **가산 방식**으로 해결(로딩/실패 상태 포함) |
| ~~middleware가 모든 공개 요청에도 `getUser()` 호출~~ | **✅ 2026-08-10 Sprint 45 측정 결과 문제 아님** | 실측: 비로그인 `/` 요청 20회에서 미들웨어 구간 **2~3ms**(전체 응답 median 84ms). 세션 쿠키가 없으면 `getUser()`가 Supabase 왕복 없이 즉시 `null`을 반환하기 때문이다. Sprint 44에서 제기한 우려는 **과장이었고**, 공개 첫 화면 성능에 영향이 없다. 인증 요청의 토큰 갱신 비용은 별개이며 정상 동작 |
| 디자인 토큰 도입 | **불필요(현 시점)** — 2026-08-10 Sprint 45 조사 | 색상 유틸리티 고유 35종이지만 gray 스케일 + blue 단일 primary + 의미색(red/green/orange)으로 **이미 일관된 단일 팔레트**다. 경쟁하는 중복 팔레트(예: blue와 indigo가 동시에 primary)가 없어, 지금 토큰 레이어를 넣으면 전 파일 기계적 치환 비용만 발생하고 얻는 것이 없다. 브랜드 컬러 변경이나 다크모드 도입이 실제로 결정될 때 재검토 |

---

END
