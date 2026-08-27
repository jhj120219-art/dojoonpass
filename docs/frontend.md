# Frontend Overview

## 목적

- 콕찰(Kokchal, 구 도준패스): 법원경매 매물 조회 / 로그인 서비스
- 이 문서는 2026-07-22 실제 코드(`src/`) 재확인을 기준으로 재작성됨. 이전 버전은 현재 저장소에 존재하지 않는 구현(NextAuth, `components/`, `lib/mock`, `lib/api` 등)을 전제로 작성되어 있었음 — "주의사항" 참고

## 현재 화면 구성 (실제 구현됨, 2026-08-11 Sprint 50 재확인)

- `/`: 서버 컴포넌트. **검색 화면 자체**다 — `SearchScreen`(`src/app/search/SearchScreen.tsx`)을 렌더하며 **어떤 경로로도 redirect하지 않는다**.
  (2026-08-11 Sprint 50 정정: 이 줄은 오랫동안 "로그인 시 `/properties`, 비로그인 시 `/login`으로 즉시 redirect. 자체 UI 없음"으로 남아 있었다 —
  Sprint 44에서 redirect를 제거했는데 이 절만 갱신되지 않아, 같은 문서의 아래 "페이지 구조" 표와 서로 모순되던 stale 기록이다.)
- `/login`: 로그인/회원가입 통합 폼(클라이언트 컴포넌트, `useActionState`로 모드 전환)
- `/properties`: 매물 목록(서버 컴포넌트). Supabase `properties` 테이블 직접 조회 — FastAPI 백엔드 미사용
- `/properties/[id]`: 매물 상세(클라이언트 컴포넌트). FastAPI `GET /api/v1/item/{id}`로 물건 데이터 조회 + `POST/GET /api/v1/registry-requests`, `POST /api/v1/payments`로 등기부등본 신청/구독/초과결제 처리 (2026-08-05 연동, 아래 "API 호출 방식" 참고). Supabase `view_counts` 기반 구현은 제거됨(`properties/[id]/actions.ts` 삭제).
  **2026-08-17 Sprint 144 추가** — 물건 사진 갤러리(대표 이미지 + 썸네일 줄 + 라이트박스)와
  개선된 문서 뷰어(쪽 이동 / 확대·축소 / 로딩·실패 상태 / 새 탭)를 넣었다.
  사진 바이트는 `GET /api/v1/item/{id}/images/{seq}`로 받고, 목록·순서·크기는
  상세 응답의 `images[]`가 준다(`next/image`는 쓰지 않는다 — docs/SPRINT124 참고).
  **빈 상태를 상태별로 구분한다**: `images_status`가 `COLLECTING`이면 "사진 수집 중",
  `NO_IMAGE`면 "법원이 사진을 제공하지 않습니다", `FAILED`면 "가져오지 못했습니다" —
  기다리면 되는 것과 기다려도 소용없는 것을 사용자가 구분할 수 있어야 하기 때문이다
- `/properties/recent`: 최근조회 목록. FastAPI `GET /api/v1/recent-items` 사용 (Release 완료)

  **2026-08-19 Sprint 218 — 검색목록 썸네일은 상세와 같은 사진이어야 한다.**
  목록 카드의 대표 사진은 `src/components/ResultThumbnail.tsx`(작은 클라이언트 섬)가
  그린다. 서버 컴포넌트인 `ResultList.tsx` 안에서는 `onError` 를 쓸 수 없기 때문이다
  (그 오류는 `tsc`/`eslint`/`build` 셋 다 못 잡고 화면만 죽는다 — 그 파일 주석 참고).

  **2026-08-20 Sprint 224 — 사진을 그리는 화면이 셋이 됐다.**
  검색목록 · 관심물건(`/favorites`) · 최근 본 물건(`/properties/recent`) 이 **같은
  컴포넌트**를 쓴다. 그래서 파일이 `src/app/search/` 에서 `src/components/` 로 옮겨졌다 —
  화면마다 따로 만들면 한쪽만 `onError` 를 빠뜨려 그 화면에서만 깨진 아이콘이 남는다.

  대표 사진을 고르는 규칙은 이제 **한 곳에만** 있다(Sprint 224 이전에는 둘로 갈라져
  있었고, 화면이 늘면 넷이 될 참이었다):

  ```
  api/v1/thumbnails.py   IMAGE_URL_TEMPLATE / image_url() / fetch_thumbnail_seqs()
    <- api/v1/search.py         검색목록      (배치 1회)
    <- api/v1/favorites.py      관심물건      (배치 1회)
    <- api/v1/recent_items.py   최근 본 물건  (배치 1회)
    <- api/v1/item.py           상세 images[] (같은 URL 규칙)
  ```

  갈라지면 **"목록에는 나오는데 열면 404"** 또는 **"클릭했더니 다른 집이 나온다"** 가
  된다. 둘 다 화면은 정상으로 보이고 로그도 조용하다.
  `test_asset_pipeline.py` 12-N 이 두 응답을 나란히 놓고 **같은 URL·같은 바이트**인지
  대조한다. 12-O 는 사진이 교체됐을 때 목록도 새 사진을 받는지(ETag)까지 본다.
  16-B2(Sprint 224)는 **네 화면이 글자 그대로 같은 URL** 을 주는지, 그 URL 이 실제로
  200 으로 열리는지, 그리고 건수가 늘어도 쿼리 수가 늘지 않는지(N+1)를 함께 본다.

  **빈 상태**: 사진이 없으면 `thumbnail_url` 이 `null` 이고 `<img>` 를 아예 만들지
  않는다(깨진 아이콘도, 빈 자리도 남기지 않는다). 서빙이 404 를 내면
  `ResultThumbnail` 이 `onError` 로 스스로 사라진다 — **목록 전체는 200 그대로**다.

  ★ 한계(2026-08-19 실측): 검색 결과 항목의 이미지 관련 키는 `thumbnail_url` **하나뿐**
  이라, 목록은 "한 번도 안 해 봄 / 법원에 없음 / 수집 실패"를 **구분하지 못한다**
  (상세는 `images_status` 로 구분한다). 목록에 상태 배지를 넣을지는 제품 결정이다.

  ★ 비용(2026-08-19 실측): 썸네일 한 장이 평균 **약 101 KB** 다 — 80x80 으로 그리는데
  **원본을 그대로** 내려 준다. 1페이지(9장) 첫 방문 **0.91 MB**, 재방문은 전부 304 로
  **0 바이트**. 서버 측 썸네일 생성은 Pillow 의존성이라 승인 영역이다.
- `/search`: `/`와 **동일한 `SearchScreen`을 공유**하는 검색 화면(복제 없음). 기존 링크/북마크 호환용으로 유지. FastAPI `GET /api/v1/search` 사용 (Release 완료)
- `/favorites`: 관심물건 목록. FastAPI `/api/v1/favorites` 사용 (Release 완료)

**중요**: `/properties`(+ `[id]`의 물건 목록 데이터 자체)는 Supabase 직접 조회, `/search`·`/favorites`·`/properties/recent`·`[id]`의 상세 데이터는 FastAPI 경유 — 두 데이터 경로가 화면별로 공존한다. 이전 버전 문서는 후자(Search/Favorite/최근조회)가 전부 미구현이라고 기술했으나 현재는 Release 완료 상태다.

~~마이페이지~~ → **2026-08-11 Sprint 54 구현 완료** (`/mypage`). 기존 API 3종(`/subscriptions/me`, `/payments`, `/registry-requests`)을 조합한 읽기 전용 화면으로,신규 엔드포인트를 만들지 않았다. 구독 해지 같은 정책 미결정 액션은 넣지 않았다.

미구현 (2026-08-11 재확인): **관리자(Admin) 화면** — 인증이 공유 `X-Admin-Key` 하나뿐이고 `audit_logs.admin_id`에 사람이 아니라 역할 문자열이 기록된다. 환불이 누구 소행인지 남지 않으므로 **운영자별 신원 체계가 선행**돼야 한다. 권리분석 전용 화면 — 상세 페이지 안의 권리분석/신뢰도 섹션은 동작하지만(`rightsAnalysis.ts`, 신뢰도 규칙은 FRONTEND_MASTER_SPEC §9.5), REGISTRY 소스는 여전히 `available:false` 고정이고 표시할 데이터 자체가 거의 없다(`rights_summary` 162/1,870건, 분석 컬럼 19개 중 14개가 100% NULL — BUGS #46).

~~플랜 선택 UI~~ → 2026-08-06 구현됨(`properties/[id]/page.tsx` 등기부 카드 안의 월/연 토글 + BASIC/PRO 비교 카드. 별도 페이지가 아님).
~~검색조건 저장 UI~~ → 구현됨(`src/app/search/SearchPresets.tsx`, `/search` 화면에 노출).

## 페이지 구조

아래 표는 **현재(as-is) 코드 기준**이다. 2026-08-10 확정된 목표(to-be) 정책은
`search/00_SEARCH_MVP.md` §1~§2가 Single Source of Truth이며, 아래 "첫 진입 화면 정책(2026-08-10 확정)"
절에 차이를 정리했다.

| 경로 | 접근 조건 (as-is) | 구현 여부 |
|---|---|---|
| `/` | 없음 — **검색 화면**(2026-08-10 Sprint 44에서 redirect 제거 완료) | 구현됨 |
| `/login` | 없음 | 구현됨 |
| `/properties` | 로그인 필요 (`proxy.ts` + 페이지 내부 이중 체크) | 구현됨(레거시·고아 라우트) |
| `/properties/[id]` | 로그인 필요 (`proxy.ts`의 `/properties/*` 게이트 + 페이지 내부 체크) | 구현됨 |
| `/properties/recent` | 로그인 필요 (`proxy.ts` + 페이지 내부 체크) | 구현됨 |
| `/search` | 로그인 불필요(비로그인도 조회 가능) | 구현됨(`/`와 `SearchScreen` 공유) |
| `/favorites` | 로그인 필요 (**Sprint 45부터 `proxy.ts` 서버 게이트 + 페이지 내부 이중 체크**) | 구현됨 |

## 첫 진입 화면 정책 (2026-08-10 확정 → **같은 날 Sprint 44에서 구현 완료**)

> 아래 "현재 코드와의 불일치" 표는 **Sprint 44 이전 상태**의 기록이다. 5개 항목 전부
> 해소됐다(`docs/CHANGELOG.md` 2026-08-10 항목 참고). 신규 파일:
> `src/app/search/SearchScreen.tsx`(`/`·`/search` 공유 화면), `src/components/SiteHeader.tsx`(공통 헤더),
> `src/lib/layout.ts`(`CONTAINER` = `max-w-[1320px] mx-auto`, 컨테이너 단일 정의).
>
> **Sprint 45 추가**: `SiteHeader`가 `/properties/[id]`(상세)에도 적용돼 전 주요 화면이
> 공통 Header를 공유한다(상세 전용 바는 유지, 위에 얹는 방식).
> 프론트엔드 계약 테스트가 생겼다 — `tests/frontend-contract.test.mjs`,
> `npm run test:frontend`. 이후 확장되어 **2026-08-11 Sprint 50 기준 53검사**
> (계약 45 + `tests/nav-context.test.mjs` 8, Node 내장 러너, 새 의존성 없음). `docs/TEST_PLAN.md` §1-A 참고.


확정 정책은 `search/00_SEARCH_MVP.md` v0.2 §1~§3에 있다. 요약:

- `/`는 **검색 화면 자체**이며 어떤 경로로도 redirect하지 않는다(로그인 여부 무관)
- 비로그인도 첫 화면에서 검색조건 입력 → 검색 → 결과 탐색까지 가능
- 검색 결과는 별도 화면이 아니라 **같은 페이지 하단**에 이어짐
- 로그인은 즐겨찾기 / 최근조회 / 검색조건 저장 / 구독·결제 / 등기부 **액션 시점**에만 요구
- 모든 화면(헤더 포함)은 `max-w-[1320px] mx-auto` 중앙 컨테이너 기준으로 정렬

현재 코드와의 불일치(= 구현 대상):

| 항목 | 현재 코드 | 확정 정책 |
|---|---|---|
| `/` 동작 | `src/app/page.tsx`가 무조건 redirect (`user` → `/properties`, 비로그인 → `/login`) | 검색 화면 렌더 |
| 검색 실행 경로 | `SearchForm.handleSearch()` / `SearchPresets.applyPreset()`이 `/search`로 하드코딩 push | 현재 pathname으로 push |
| 컨테이너 | `/search`만 `max-w-[1320px]`, `/properties`·`/login`·`/favorites`·`/properties/recent`는 풀블리드(`px-4`/`px-5`/`px-6`) | 전 화면 동일 컨테이너 |
| 데스크톱 밀도 | 모바일 1열 레이아웃이 1320px 폭으로 그대로 늘어남(입력 필드가 화면을 가로지름) | `md` 2열 / `xl` 3열 |
| 공용 헤더 | 없음(각 page.tsx가 상단 바를 개별 작성, `PrimaryNav`만 공유) | 공용 헤더에서 컨테이너 정렬 + 로그인/로그아웃 노출 |

`/properties/[id]`(상세) 게이트는 **2026-08-10 확정됐다: 로그인 필수** — 더 이상 PM 결정 대기
항목이 아니다. 비로그인은 목록까지만 보고, 물건을 클릭하는 순간 로그인으로 이동한다.
`proxy.ts`(당시 `middleware.ts`)의 `/properties/*` 게이트가 이미 이 정책과 일치하므로 게이트 로직은 그대로 두되,
로그인 redirect가 **쿼리스트링을 버리는 결함**은 수정 대상이다(당시 `middleware.ts:42`가 `pathname`만
넘겨 상세의 `?ids=&i=` 이전/다음 물건 컨텍스트가 소실됨. `login/actions.ts`의 기본 복귀 경로도
레거시 `/properties`라 `/`로 바뀌어야 함).

**Frontend 전체의 최상위 기준은 `docs/FRONTEND_MASTER_SPEC.md`다**(2026-08-10 신규).
라우팅/인증 경계/공통 Layout/Navigation 정책은 그 문서를 따르고, 검색 화면 세부는
`search/00_SEARCH_MVP.md`, 현재 코드 현황은 이 문서를 본다.

## Component 구조

- **(2026-08-07 정정)** `src/components/` 디렉터리는 **존재한다** — `PrimaryNav`, `PriceRangeSelect`,
  `RangeSelect`, `PropertyTypeTree`, `SearchAccordionSection` 5개의 공용 컴포넌트가 있고 전부
  실제로 import되어 쓰인다(미사용 컴포넌트 0건, 2026-08-07 전수 확인). 이전 버전의 "components/
  디렉터리가 존재하지 않는다 / 재사용 컴포넌트 없음"은 stale이었다. 그 외 화면별 UI는 여전히
  각 `page.tsx`에 인라인으로 작성되어 있다
- 라우트별 지역 컴포넌트: `src/app/search/*`(SearchForm/ResultList/Pagination/SortBar/
  SearchPresets/FavoriteButton), `src/app/properties/*`(SearchFilters/LogoutButton) — 전부 사용 중
- `formatPrice`/`formatDate` 포맷 함수 중복 정의 — 2026-08-06(Sprint 18) 재확인 결과, 서로 다른
  5곳 중 `search/ResultList.tsx`/`favorites/page.tsx`/`properties/recent/page.tsx` 3곳은
  완전히 동일한 구현이라 `src/lib/format.ts`(신규)의 공용 `formatPrice()`로 통합함(동작 무변경,
  Runtime QA로 확인). `properties/page.tsx`와 `properties/[id]/page.tsx`는 서로 다른 구현(단순
  "억" 고정 표기 vs "만/억" 단계 표기)이라 통합하지 않고 그대로 둠 — 통합하려면 어느 표기를
  기준으로 할지 UX 결정이 먼저 필요함(Spec 필요, 이번 Sprint 범위 밖)

## Layout 구조

- ~~`app/layout.tsx`의 메타데이터가 `create-next-app` 기본값 그대로임~~ → **2026-08-07 수정 완료**:
  `title: "콕찰 — 법원경매 검색"`, description도 서비스 설명으로 교체. `<html lang>`도 `en` → `ko`
- 공통 헤더/레이아웃은 없지만, 화면 간 이동은 `src/components/PrimaryNav.tsx`(검색/최근 본 물건/
  관심물건 3개 링크)를 각 페이지 상단 바가 공유한다

## Routing 구조

- Next.js App Router, `src/app/` 하위만 유효 라우트
- `src/login/`(`app/` 밖)은 Next.js가 라우팅하지 않는 도달 불가능한 코드. 예전 로그인 페이지의 잔재이며 구 브랜드명 "도준 경매 패스"를 그대로 쓰고 있음 — `docs/decision-log.md`가 명시적으로 금지한 표기

## API 호출 방식

- `src/lib/api.ts`(`fetchJSON`/`postJSON`/`deleteJSON`/`fetchAuthedJSON`/`fetchAuthedRaw`)를 통해 FastAPI 백엔드(`api_server.py`, `/api/v1/*`)를 호출한다 — `search`, `favorites`, `recent-items`, `properties/[id]`의 물건 상세 데이터(`GET /api/v1/item/{id}`), 문서 파일(`GET /api/v1/item/{id}/documents/{doc_type}`), 2026-08-05부터 `payments`/`registry-requests`도 포함
- **가격/플랜은 서버가 내려준다(2026-08-07)**: `GET /api/v1/plans`. 예전에 있던 `PLAN_OPTIONS`
  하드코딩 상수와 `REGISTRY_OVERAGE_FEE`는 제거했다 — 프론트/서버 이중 관리로 금액이 어긋나면
  사용자가 본 가격으로 결제를 눌렀을 때 서버가 거절하는 상태가 됐기 때문이다.
  카탈로그 도착 전에는 구독 버튼이 비활성화된다
- `properties/[id]/page.tsx`가 `POST /api/v1/registry-requests`(등기부 신청), `POST /api/v1/payments`(구독·초과분 결제)를 직접 호출한다 — 무료/초과 판단은 프론트에서 계산하지 않고 응답(`status`/`is_free`/`free_remaining`/`charged_amount`)을 그대로 반영만 함
- `fetchAuthedRaw`(2026-08-05 신규, `api.ts`): 다른 래퍼와 달리 `!res.ok`에서 던지지 않는다 — `GET /registry-requests/{id}/download`가 상황에 따라 JSON envelope(미완료 상태) 또는 실제 파일(COMPLETED)을 돌려주므로, 호출부(`handleDownloadRegistry`)가 `Content-Type`을 보고 직접 분기한다. 응답의 `Content-Disposition`으로 파일명을 읽기 위해 `api_server.py`의 CORS에 `expose_headers=["Content-Disposition"]`을 추가함(기본적으로 브라우저가 이 헤더를 cross-origin JS에 노출하지 않기 때문)
- `properties/page.tsx`는 여전히 Supabase 테이블 `properties`를 서버 컴포넌트에서 직접 `select`한다 (FastAPI `auction_item` 미사용)
- `properties/[id]/actions.ts`(Supabase `view_counts` 기반 등기부 카운터)는 2026-08-05 삭제됨 — 더 이상 존재하지 않음
- `lib/mock/*` 디렉터리는 존재하지 않는다. `lib/api.ts`는 존재한다(위 참고)

## 상태관리 방식

- 전역 상태관리 라이브러리 없음
- 클라이언트 컴포넌트 로컬 `useState`/`useActionState`만 사용
- 세션 확인: 서버는 `createServerSupabaseClient().auth.getUser()`, 클라이언트는 `createClient()` 직접 호출 — `useSession()` 같은 훅 없음

## 절대 변경하면 안 되는 것

(실제 코드에서 확인되는 것만 기록 — 원 문서의 itemId 체계/Mock 시그니처 관련 정책은 해당 구현 자체가 없어 현재 코드 기준으로는 검증 불가)

- 서비스명 "콕찰" 표기 유지, "도준패스"/"도준 경매 패스" 사용 금지 (`docs/decision-log.md`)

## 2026-08-07 Audit 결과 (Sprint 28)

프론트엔드는 그동안 lint만 돌리고 코드 감사를 한 적이 없어 이번에 전수로 봤다.

**수정한 것**
- 즐겨찾기 토글이 서버 실패에도 상태를 뒤집어, **하트는 바뀌는데 그 아래 실패 메시지가
  함께 뜨는** 모순된 화면이 됐다(`search/FavoriteButton.tsx`, `properties/[id]/page.tsx`).
  상태는 서버 기준으로만 바꾸되, 중복 등록/이미 삭제됨은 "의도가 이미 이뤄진 것"으로 보고
  상태만 맞추고 에러는 띄우지 않는다 — 도메인 Error Code(`FAVORITE_ALREADY_EXISTS` /
  `FAVORITE_NOT_FOUND`)로 구분한다
- `src/lib/api.ts`: `ApiEnvelope`에 `error`/`meta` 추가, `ERROR_CODES` 상수 신설.
  **분기는 `message` 문구가 아니라 `error` 코드로 한다**

**이상 없음 확인**
- `localStorage`/`sessionStorage` 사용 0건 — 토큰을 브라우저 저장소에 두지 않는다
- `dangerouslySetInnerHTML` 0건, 사용자 입력이 직접 `href`로 들어가는 지점 0건
- 모든 `fetch` 호출에 에러 처리 존재, `.map()` 36곳 전부 `key` 지정
- Open Redirect 방어(`sanitizeRedirectPath`) 유지

---

## 알려진 문제점

### 2026-08-11 (Sprint 49) 실제 브라우저 검증에서 발견

- ~~정렬 화살표가 실제 데이터 순서와 반대로 표시되고, 정렬 버튼을 눌러도 결과가 바뀌지 않음~~
  → **해결** (`docs/BUGS.md` #29 — `SortBar`의 `sort_order` 기본값을 백엔드와 같은 `desc`로)
- ~~정렬을 바꿔도 페이지 번호가 유지되어 "감정가 높은 순"인데 가장 싼 물건이 보임~~
  → **해결** (#30 — 정렬 변경 시 `page=1`)
- ~~페이지 번호가 범위를 벗어나면 "검색 결과가 없습니다"로 오인 안내 + 복구 링크가 검색조건을 버림~~
  → **해결** (#31 — 두 상태 구분 + 검색조건 유지 1페이지 복귀 링크)
- ~~`/favorites`·`/properties/recent`에서 상세로 들어가면 "이전/다음 물건" 바가 "1 / 1"로 죽은 채 노출~~
  → **해결** (#32 — `navContext.ts` 순수 함수로 분리 + 빈 세그먼트/`i` 부재 처리)
- ~~결과 0건일 때 원인을 항상 사용자 조건으로 단정 — 재고가 0이면 "조건 없이 전체 물건 보기"가
  같은 빈 화면으로 되돌아오는 **막다른 링크**가 됨~~
  → **해결** (#106 — `SearchScreen`이 `hasFilters`를 계산해 넘기고 `ResultList`가 두 상태를 가름.
  `page`/`size`/`sort_by`/`sort_order`는 조건으로 세지 않는다. 조건 없이 0건이면 문구를
  "현재 공개된 경매 물건이 없습니다"로 바꾸고 막다른 링크를 제거한다.
  기본 필터가 `auction_date >= 오늘`이라 크롤이 멈추면 도달하는 **예정된 상태**다)
- **[미해결 · 결정 필요] 검색 물건종류 69개 중 60개가 항상 0건** (`docs/BUGS.md` #33).
  `PropertyTypeTree`의 어휘는 Tank Auction HTML 전수 복사인데 DB는 크롤러 수집 원문 18종이고
  백엔드는 `LIKE %값%` 매칭이라, `다세대`(246) `근린시설`(164) `상가,오피스텔,근린시설`(202)
  `오피스텔`(102) 등이 **이름으로 아예 선택되지 않는다**(도달 불가 745/1,870 ≈ 40%).
  어휘를 어느 쪽으로 통일할지가 제품 판단이라 임의 수정하지 않고 측정치만 기록했다
- **[저심각도]** `?size=abc`·`?page=0`처럼 백엔드 검증(422)에 걸리는 파라미터가 URL로 들어오면
  화면 전체가 "검색 결과를 불러오지 못했습니다" 한 줄이 된다(검색 Form은 남아 있어 복구는 가능).
  UI 조작으로는 만들 수 없고 URL 직접 입력에서만 발생 — 별도 안내 문구는 미도입
- **[저심각도]** 비로그인 상태에서 검색조건 이름을 입력하고 "저장"을 누르면 로그인으로 유도되는데,
  복귀 후 **입력했던 이름은 남지 않는다**(검색조건 자체는 URL로 보존됨)


- **데이터 소스 불일치(`/properties`만 해당, 2026-08-05 기준 범위 축소)**: `/properties`(목록)와 `/properties/[id]`의 물건 목록 진입 경로는 여전히 Supabase 테이블 `properties`(컬럼: `title`, `bid_date`, `case_number`, `detail_info`, `status` 등 — `auction_item`과 이름·구조가 다름)를 직접 조회해 크롤러 데이터(`auction_item`)가 노출되지 않는다. 반면 `/search`, `/favorites`, `/properties/recent`와 `/properties/[id]`의 상세 데이터 자체는 FastAPI(`auction_item` 경유)를 사용하므로 이 문제는 `/properties` 목록 화면에 한정된다 — `docs/decision-log.md`의 "검색은 SQLite 기반" 결정과는 `/search`에서는 이미 일치, `/properties`에서는 여전히 어긋남
- ~~등기부 열람 로직 이중 구현~~ → 2026-08-05 해소됨: `properties/[id]/actions.ts`(Supabase `view_counts`) 삭제, `api/v1/registry.py` 하나로 일원화. 정책도 2026-08-06 확정 + **코드 반영 완료**(플랜별 월 단위: 베이직 5회/프로 10회, `registry.py:get_user_free_limit()`/`get_free_count()`). 이전 문서의 "코드는 아직 평생 누적 5회"는 2026-08-07 기준 stale
- ~~`PLAN_OPTIONS` 확정 Spec 미반영~~ → **2026-08-06 완료**: `properties/[id]/page.tsx`가 월/연 결제주기 토글 + 플랜 카드(베이직 12,900원·월5회 / 프로 22,900원·월10회)를 표시하고, 연 결제 시 프로는 정상가 274,800원 취소선 + 판매가 198,000원을 함께 노출한다. 결제 요청에 `billing_cycle`을 함께 보내며 금액은 서버(`PLAN_CATALOG`)가 재검증한다. 할인은 `listPrice`/`price` 분리 구조라 이벤트 적용 시 값만 교체하면 된다
- `src/login/`(도달 불가)이 구 브랜드명을 쓰는 죽은 코드로 남아있음 — 사용 여부가 확실하지 않은 코드는 임의로 삭제하지 않는다는 프로젝트 규칙에 따라 그대로 둠
- ~~**[2026-08-06 Sprint 21 발견] 로그아웃 기능이 화면에 전혀 노출되지 않음**~~ → **2026-08-06 Sprint 23 해결**: `src/app/properties/page.tsx` 헤더에 `LogoutButton`을 연결했다(`docs/BUGS.md` #15).
  단 **2026-08-07 추가 확인**: 로그아웃 버튼이 붙은 `/properties`는 아래 "데이터 소스 불일치" 항목의
  Supabase 직접 조회 화면이다 — 로그아웃 자체는 동작하지만, 유일한 로그아웃 경로가 그 화면에만
  있어 `/search`·`/favorites`·`/properties/recent`에서는 여전히 로그아웃할 수 없다(`PrimaryNav`에는
  로그아웃이 없음). 어느 화면에 추가로 노출할지는 화면 스펙 결정 사항이라 임의로 배치하지 않음
- **[2026-08-07 발견] `/properties` 목록의 링크 대상 id가 다른 시스템의 id다**: 목록은 Supabase
  `properties` 테이블 행을 그리면서 `href={/properties/${property.id}}`로 이동시키는데, 상세
  화면 `/properties/[id]`는 그 id로 FastAPI `GET /api/v1/item/{id}`(SQLite `auction_item`)를
  조회한다. 두 id는 서로 다른 채번 체계라 **엉뚱한 물건이 열리거나 404가 난다**. 데이터 소스
  불일치(아래 항목)의 직접적인 사용자 영향이며, `/properties` 목록의 처리 방향(FastAPI 전환 vs
  화면 폐지)이 정해져야 고칠 수 있어 이번에는 기록만 함
- **[2026-08-07 발견] `properties/page.tsx`의 지역 `formatPrice`가 공용 구현과 다르게 동작**:
  `src/lib/format.ts`의 공용 `formatPrice()`는 0을 `'-'`로, 1만~1억 미만을 `'N만'`으로 표시하지만,
  `properties/page.tsx` 안의 동명 지역 함수는 항상 1억으로 나눠 `0` → `"0.0억"`, `500만` →
  `"0.1억"`으로 표시한다. Sprint 18의 중복 제거에서 이 화면만 "표기 기준 UX 결정 필요"로 제외됐던
  잔여분이며, 위 id 불일치와 같은 화면이라 함께 처리하는 것이 맞다
- `src/app/properties/SearchFilters.tsx`는 `properties/page.tsx`에서 실제로 사용 중이나, 자체 `SIDO_LIST`(정식 명칭 표기, 17개)·`SIGUNGU_MAP`(서울/부산/경기 3개 시도만 하드코딩)·`PRICE_OPTIONS`(10단계)를 갖고 있어 `/search` 화면의 `SearchForm.tsx`(축약 표기 시도, `GET /api/v1/search/regions` 실시간 조회, `PriceRangeSelect`의 60단계 프리셋)와 완전히 다른 데이터·정밀도를 쓴다. `/properties`가 Supabase 직접 조회라는 기존 데이터 소스 불일치(위 항목)와 같은 뿌리이며, `/properties` 목록의 향후 처리 방향이 정해지기 전에는 통합 대상이 아님(미결정, PM 확인 필요)
- ~~`app/layout.tsx` 메타데이터가 `create-next-app` 기본값 그대로~~ → 2026-08-07 해결(`콕찰 — 법원경매 검색` + `lang="ko"`)
- 색상/스타일이 각 페이지에 Tailwind 유틸리티 클래스로 하드코딩되어 있음 (`bg-blue-500`, `text-gray-400` 등). 별도 디자인 토큰 파일(`styles/auction-theme.css` 등)은 존재하지 않음 — `globals.css`는 `create-next-app` 기본값(배경/전경색 변수, 폰트)만 정의
- ~~등기부 실제 발급(다운로드)은 여전히 없음~~ → 2026-08-05 완전히 해결됨: `status=COMPLETED`이면 "📥 등기부 다운로드" 버튼이 나타나고, 클릭 시 `GET /registry-requests/{id}/download`를 호출해 실제 파일을 브라우저 다운로드로 저장한다(`handleDownloadRegistry`, `fetch`+`blob`+`<a download>`). `FAILED`는 `reason`(백엔드가 노출)을 그대로 보여준다
- OVERAGE_USAGE 결제가 성공해도 프론트는 백엔드가 응답으로 돌려주는 `registry_request`(연결 후 상태)를 그대로 반영하므로, 결제 후 화면에는 실제 `PENDING` 상태가 뜬다 — 단 이 상태가 "발급 완료"를 뜻하진 않음(위 항목 참고)

## 주의사항

- 이 문서는 2026-07-22 코드 재확인을 기준으로 재작성됨. 이전 버전이 전제한 NextAuth/`components/`/`lib/mock`/`lib/api` 기반 구현은 이 저장소의 `src/`에 존재하지 않았다 — 다른 브랜치, 다른 저장소, 계획 단계 문서 중 무엇이었는지는 확인되지 않음
- 코드 수정 시 수정 파일명 / 수정 함수명 / 변경 코드만 우선 제시, 전체 파일 통째 출력 지양
- 문제 발생 시 원인 → 확인 방법 → 수정 방법 순서로 설명
- 백엔드 확인이 필요한 사항은 추측하지 않는다

## 향후 개발 예정

(2026-08-05 기준 재확인 — 우선순위는 `docs/roadmap.md` 기준)

- ~~검색 페이지~~ / ~~관심물건~~ / ~~최근조회~~ (Release 완료, FastAPI 연동됨)
- `/properties` 목록을 FastAPI(`auction_item`) 기반으로 전환할지, Supabase `properties`를 유지할지 결정 — PM 확인 필요 (미결정)
- ~~등기부 열람 로직 일원화~~ (2026-08-05 완료, 위 참고)
- ~~플랜 비교/선택 UI~~ (2026-08-06 완료), ~~검색조건 저장 UI~~ (완료 — `SearchPresets.tsx`)
- ~~마이페이지~~ (2026-08-11 Sprint 54 완료 — `/mypage`)
- **Admin 화면** — 운영자별 신원 체계 선행 필요 (위 참고)
- 권리분석 전용 화면 — 데이터 커버리지 회복(BUGS #46)이 선행돼야 의미가 있다
- ~~등기부 다운로드 UI~~ (2026-08-05 완료)

---

## 접근성 / 큰글씨 — 2026-08-19 Sprint 219 실측

**화면은 바꾸지 않았다.** 처음으로 쟀고, 나빠지지 않게 잠갔다
(`test_frontend_accessibility.py`, 상세는 `docs/SPRINT219_ACCESSIBILITY_AUDIT.md`).

```
검사한 텍스트 199개 / WCAG AA 대비(4.5:1) 미달 81개 (41%)
text-gray-400 on white = 2.6:1        기준의 58%
탭 타깃 53개 중 44px 미만 44개 (83%)   그중 24px 미만 5개 (★ 2026-08-20 Sprint 225 정정: 위반 아님 — 간격 예외로 적합)
물건 주소 12px / "최저입찰가"·"감정가 3.8억" 11px
소스: text-xs 111 / text-gray-400 106 (상세페이지가 각 55 로 가장 심하다)
```

**확인한 것**: 뷰포트 메타가 올바르다(`width=device-width, initial-scale=1`),
확대 차단(`user-scalable=no` 등)이 **없다**, 썸네일이 `alt=""`+`aria-hidden`+`onError`
규약을 지킨다, `alt` 없는 `<img>` 가 **0개**다.

**2026-08-19 Sprint 223에 채운 것** (전부 픽셀 무변경):

```
모달 포커스 트랩     첫 진입 포커스 / Tab 순환 / 닫을 때 여는 버튼으로 복귀
                     src/lib/useFocusTrap.ts, 두 모달에 배선 (BUGS #151)
상태 메시지 알림     동적 안내 13곳에 role=alert|status
                     검색 결과는 **항상 존재하는 sr-only 한 줄**(role=status) (BUGS #152)
오류-컨트롤 연결     시/군/구 로드 실패를 aria-describedby 로 그 select 에
main 랜드마크        화면 6개 전부 보유(로딩·실패 분기 포함) (BUGS #153)
폼 컨트롤 이름       93/93 (Sprint 222)
키보드               양수 tabindex 0 / 클릭 전용 div 0 / 이름 없는 대화형 요소 0
aria 상태값          aria-expanded 가 실제로 토글된다(클릭해서 확인) / aria-current / aria-pressed
disabled             네이티브 disabled 만 사용(aria-disabled 단독 0)
heading              /search·/properties 둘 다 건너뜀 0
```

**확인하지 못한 것**: **모바일 뷰포트(390~412px) 레이아웃.**
브라우저 자동화의 창 리사이즈가 페이지 뷰포트에 반영되지 않았고
(`innerWidth` 가 1920 에서 안 바뀐다), 앱이 `X-Frame-Options: DENY` 라
iframe 으로 좁은 폭을 만드는 우회도 막혔다(그 헤더 자체는 올바른 보안 설정이다).
2026-08-19 Sprint 223에 `resize_window(390x844)` 로 **재확인했다** — 창은 줄지만
`innerWidth` 는 여전히 1920 이라 미디어 쿼리가 전환되지 않는다. 여전히 **확인 불가**다.
**"모바일에서 깨지지 않는다"는 아직 주장할 수 없다** — 사람이 실기기나
DevTools 디바이스 모드로 한 번 봐야 한다.

**큰글씨 모드의 전제** (2026-08-19 Sprint 220 정정): 처음엔 "대부분 px 고정이라
루트 글꼴을 키워도 안 커진다"고 적었으나 **빌드 CSS 를 열어 보니 사실이 아니다.**
Tailwind v4 의 이름 있는 크기는 rem 기반이다(`--text-xs: .75rem`).
`text-xs`(111곳)는 루트 글꼴을 따라 커진다. 닿지 않는 것은 **대괄호 임의값 8곳**뿐
(`text-[11px]` 6 + `text-[10px]` 2). **선행 작업은 그 8곳 교체**이고 전면 전환이 아니다.

**(2026-08-19 Sprint 223 — 그 8곳을 교체해 `0곳`이 됐다.)**
`text-[11px]` -> `text-[0.6875rem]`, `text-[10px]` -> `text-[0.625rem]`.
16px 기준 **정확히 같은 크기**라 픽셀은 하나도 바뀌지 않고, 이제 루트 글꼴을 따라 커진다.

```
루트 16px    11px  (수정 전과 동일)
루트 32px    11px -> **22px**  (전에는 11px 고정)
2배 확대에서도 가로 오버플로 0
```

큰글씨의 **기술 기반은 끝났다.** 남은 것은 색·크기·간격을 얼마로 할지라는 제품 결정뿐이다.

---

## 로컬 개발 접속 정보 (2026-08-19 Sprint 221 실측)

```
WEB   http://localhost:3000/     메인이 곧 검색 화면(SearchScreen). 리다이렉트 없음
API   http://127.0.0.1:8000      Swagger UI: /docs
실행  python -m uvicorn api_server:app --host 127.0.0.1 --port 8000
      npm run dev
설정  .env.local 의 NEXT_PUBLIC_API_BASE_URL 이 프런트가 부를 API 주소를 정한다
```

로그인 게이트(`src/proxy.ts`)가 막는 것은 `/properties`, `/favorites`, `/mypage` 뿐이다.
**검색은 비로그인으로 볼 수 있다.**

★ 긴 개발 세션에서 `node` 프로세스가 누적되면 Turbopack 이 `0xc0000142` 로 죽어
dev 서버가 **500** 을 낸다(코드 결함 아님). 남은 node 프로세스를 모두 종료하면 정상화된다.

## 화면 간 사진 일관성 — 검색목록에만 썸네일이 있다 (2026-08-19)

`thumbnail_url` 을 주는 API 는 `api/v1/search.py` 하나뿐이다.
**관심물건·최근 본 물건 화면에는 `<img>` 가 없다.** 사용자는 검색목록에서 사진을 보고
담았는데 관심물건에서는 사진이 사라진다.

의도된 제외라는 기록이 없어 **미문서화 공백**으로 판단했고, 고치는 것은 제품 결정이라
`docs/roadmap.md` 에 Backlog 로 등록했다. 그동안 `test_search.py` 가 규칙을 건다 —
**그리기 시작하면 API 도 주어야 한다.**

## 폼 접근성 — 이름은 `aria-label` 로 준다 (2026-08-19 Sprint 222, BUGS #150)

이 저장소의 검색 폼은 보이는 레이블을 `<span className={labelClass}>` 로 그린다.
**그것은 컨트롤과 프로그래밍적으로 연결되지 않는다** — 스크린리더는 "콤보박스"라고만
읽고, 최소/최대가 나란히 둘이라 어느 쪽인지도 알 수 없다.

그래서 **감싸는 `<label>` 로 이름을 줄 수 없는 부류**는 전부 `aria-label` 을 쓴다.

```
<select>                 `${label} 최소` / `${label} 최대`  (RangeSelect / PriceRangeSelect)
<input type="date">      "매각기일 시작" / "매각기일 종료"
placeholder 만 있는 input  placeholder 와 같은 문구를 aria-label 로도 준다
```

`placeholder` 는 **입력을 시작하면 사라지므로 이름이 아니다**(WCAG 3.3.2).
체크박스 77개는 `<label>` 로 감싸는 패턴이라 그대로 둔다.

실측(2026-08-19, 아코디언 전부 펼침): **폼 컨트롤 93개 전부 이름 있음**(수정 전 77개).
`test_frontend_accessibility.py` 10 이 이 규칙을 잠근다.

★ 측정할 때 **아코디언을 펼쳐야 한다.** 접힌 상태만 보면 컨트롤이 5개로 보인다.

## 모달 — `role="dialog"` + `aria-modal` (2026-08-19 Sprint 221, BUGS #149)

상세페이지의 전체 화면 오버레이 둘(문서 뷰어 / 사진 라이트박스)은
`role="dialog" aria-modal="true" aria-labelledby=<제목 id>` 를 갖는다.
없으면 스크린리더가 모달임을 알리지 못하고 **뒤의 검색 결과·가격이 계속 읽힌다.**

Escape 닫기와 좌우 화살표 이동은 이미 있었고 함께 회귀로 고정했다.

~~**포커스 트랩은 아직 없다** — Tab 이 배경으로 빠져나간다(별도 작업).~~
→ **구현됐다** (2026-08-27 코드 대조로 정정). `src/lib/useFocusTrap.ts` 가 있고,
상세 화면의 모달 **둘 다** 쓰고 있다 —
`properties/[id]/page.tsx:285`(문서 뷰어) / `:286`(사진 뷰어).
