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

미구현 (이 저장소의 실제 코드에는 존재하지 않음): 마이페이지, 플랜 선택 UI(구독은 `properties/[id]` 카드 내 단일 버튼으로만 가능, 별도 플랜 비교/결제 화면 없음), 검색조건 저장 UI, 권리분석 화면(상세 페이지 내 `rightsAnalysis.ts`는 REGISTRY 소스를 `available:false`로 하드코딩한 스텁 — 등기부 신청 카드와는 별개)

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

- `components/` 디렉터리가 존재하지 않는다. 모든 UI가 각 `page.tsx`에 인라인으로 작성됨 — 재사용 컴포넌트 없음
- `formatPrice`/`formatDate` 포맷 함수가 `properties/page.tsx`와 `properties/[id]/page.tsx`에 각각 중복 정의되어 있음

## Layout 구조

- `app/layout.tsx`의 메타데이터가 `create-next-app` 기본값(`title: "Create Next App"`) 그대로임 — 리브랜딩 안 됨
- 공통 헤더/네비게이션 없음. 각 페이지가 자체 상단 바를 그림

## Routing 구조

- Next.js App Router, `src/app/` 하위만 유효 라우트
- `src/login/`(`app/` 밖)은 Next.js가 라우팅하지 않는 도달 불가능한 코드. 예전 로그인 페이지의 잔재이며 구 브랜드명 "도준 경매 패스"를 그대로 쓰고 있음 — `docs/decision-log.md`가 명시적으로 금지한 표기

## API 호출 방식

- `src/lib/api.ts`(`fetchJSON`/`postJSON`/`deleteJSON`/`fetchAuthedJSON`/`fetchAuthedRaw`)를 통해 FastAPI 백엔드(`api_server.py`, `/api/v1/*`)를 호출한다 — `search`, `favorites`, `recent-items`, `properties/[id]`의 물건 상세 데이터(`GET /api/v1/item/{id}`), 문서 파일(`GET /api/v1/item/{id}/documents/{doc_type}`), 2026-08-05부터 `payments`/`registry-requests`도 포함
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

## 알려진 문제점

- **데이터 소스 불일치(`/properties`만 해당, 2026-08-05 기준 범위 축소)**: `/properties`(목록)와 `/properties/[id]`의 물건 목록 진입 경로는 여전히 Supabase 테이블 `properties`(컬럼: `title`, `bid_date`, `case_number`, `detail_info`, `status` 등 — `auction_item`과 이름·구조가 다름)를 직접 조회해 크롤러 데이터(`auction_item`)가 노출되지 않는다. 반면 `/search`, `/favorites`, `/properties/recent`와 `/properties/[id]`의 상세 데이터 자체는 FastAPI(`auction_item` 경유)를 사용하므로 이 문제는 `/properties` 목록 화면에 한정된다 — `docs/decision-log.md`의 "검색은 SQLite 기반" 결정과는 `/search`에서는 이미 일치, `/properties`에서는 여전히 어긋남
- ~~등기부 열람 로직 이중 구현~~ → 2026-08-05 해소됨: `properties/[id]/actions.ts`(Supabase `view_counts`) 삭제, `api/v1/registry.py` 하나로 일원화. 단 그 정책 자체(평생 누적 5회)가 맞는지는 여전히 미확정(`docs/decision-log.md` Pending Decisions)
- `src/login/`(도달 불가)이 구 브랜드명을 쓰는 죽은 코드로 남아있음 — 사용 여부가 확실하지 않은 코드는 임의로 삭제하지 않는다는 프로젝트 규칙에 따라 그대로 둠
- `app/layout.tsx` 메타데이터가 `create-next-app` 기본값 그대로 (title/description 미변경)
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
- 마이페이지, 플랜 비교/선택 UI, 검색조건 저장 UI, 권리분석 화면 신규 구현
- ~~등기부 다운로드 UI~~ (2026-08-05 완료)
