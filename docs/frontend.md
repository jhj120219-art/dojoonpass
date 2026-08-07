# Frontend Overview

## 목적

- 콕찰(Kokchal, 구 도준패스): 법원경매 매물 조회 / 로그인 서비스
- 이 문서는 2026-07-22 실제 코드(`src/`) 재확인을 기준으로 재작성됨. 이전 버전은 현재 저장소에 존재하지 않는 구현(NextAuth, `components/`, `lib/mock`, `lib/api` 등)을 전제로 작성되어 있었음 — "주의사항" 참고

## 현재 화면 구성 (실제 구현됨, 2026-08-05 재확인)

- `/`: 서버 컴포넌트. 로그인 세션 확인 후 `/properties`(로그인 시) 또는 `/login`(비로그인 시)으로 즉시 redirect. 자체 UI 없음
- `/login`: 로그인/회원가입 통합 폼(클라이언트 컴포넌트, `useActionState`로 모드 전환)
- `/properties`: 매물 목록(서버 컴포넌트). Supabase `properties` 테이블 직접 조회 — FastAPI 백엔드 미사용
- `/properties/[id]`: 매물 상세(클라이언트 컴포넌트). FastAPI `GET /api/v1/item/{id}`로 물건 데이터 조회 + `POST/GET /api/v1/registry-requests`, `POST /api/v1/payments`로 등기부등본 신청/구독/초과결제 처리 (2026-08-05 연동, 아래 "API 호출 방식" 참고). Supabase `view_counts` 기반 구현은 제거됨(`properties/[id]/actions.ts` 삭제)
- `/properties/recent`: 최근조회 목록. FastAPI `GET /api/v1/recent-items` 사용 (Release 완료)
- `/search`: 검색 화면. FastAPI `GET /api/v1/search` 사용 (Release 완료)
- `/favorites`: 관심물건 목록. FastAPI `/api/v1/favorites` 사용 (Release 완료)

**중요**: `/properties`(+ `[id]`의 물건 목록 데이터 자체)는 Supabase 직접 조회, `/search`·`/favorites`·`/properties/recent`·`[id]`의 상세 데이터는 FastAPI 경유 — 두 데이터 경로가 화면별로 공존한다. 이전 버전 문서는 후자(Search/Favorite/최근조회)가 전부 미구현이라고 기술했으나 현재는 Release 완료 상태다.

미구현 (2026-08-07 재확인): **마이페이지**, **관리자(Admin) 화면**, 권리분석 화면(상세 페이지 내 `rightsAnalysis.ts`는 REGISTRY 소스를 `available:false`로 하드코딩한 스텁 — 등기부 신청 카드와는 별개)

~~플랜 선택 UI~~ → 2026-08-06 구현됨(`properties/[id]/page.tsx` 등기부 카드 안의 월/연 토글 + BASIC/PRO 비교 카드. 별도 페이지가 아님).
~~검색조건 저장 UI~~ → 구현됨(`src/app/search/SearchPresets.tsx`, `/search` 화면에 노출).

## 페이지 구조

| 경로 | 접근 조건 | 구현 여부 |
|---|---|---|
| `/` | 없음 (redirect 전용) | 구현됨 |
| `/login` | 없음 | 구현됨 |
| `/properties` | 로그인 필요 (middleware + 페이지 내부 이중 체크) | 구현됨 |
| `/properties/[id]` | 로그인 필요 (페이지 내부 체크) | 구현됨 |
| `/properties/recent` | 로그인 필요 | 구현됨 |
| `/search` | 로그인 불필요(비로그인도 조회 가능) | 구현됨 |
| `/favorites` | 로그인 필요 | 구현됨 |

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
- 마이페이지, **Admin 화면**, 권리분석 화면 신규 구현 (전부 미착수)
- ~~등기부 다운로드 UI~~ (2026-08-05 완료)
