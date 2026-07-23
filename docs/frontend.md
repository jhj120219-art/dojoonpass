# Frontend Overview

## 목적

- 콕찰(Kokchal, 구 도준패스): 법원경매 매물 조회 / 로그인 서비스
- 이 문서는 2026-07-22 실제 코드(`src/`) 재확인을 기준으로 재작성됨. 이전 버전은 현재 저장소에 존재하지 않는 구현(NextAuth, `components/`, `lib/mock`, `lib/api` 등)을 전제로 작성되어 있었음 — "주의사항" 참고

## 현재 화면 구성 (실제 구현됨)

- `/`: 서버 컴포넌트. 로그인 세션 확인 후 `/properties`(로그인 시) 또는 `/login`(비로그인 시)으로 즉시 redirect. 자체 UI 없음
- `/login`: 로그인/회원가입 통합 폼(클라이언트 컴포넌트, `useActionState`로 모드 전환)
- `/properties`: 매물 목록(서버 컴포넌트). Supabase `properties` 테이블 직접 조회
- `/properties/[id]`: 매물 상세(클라이언트 컴포넌트). 등기부등본 열람(월 5회 차감) UI 포함

미구현 (이 저장소의 실제 코드에는 존재하지 않음): 검색 페이지, 마이페이지, 구독/결제 UI, 관심물건, 최근조회, 검색조건 저장, 권리분석 화면

## 페이지 구조

| 경로 | 접근 조건 | 구현 여부 |
|---|---|---|
| `/` | 없음 (redirect 전용) | 구현됨 |
| `/login` | 없음 | 구현됨 |
| `/properties` | 로그인 필요 (middleware + 페이지 내부 이중 체크) | 구현됨 |
| `/properties/[id]` | 로그인 필요 (페이지 내부 체크) | 구현됨 |

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

- FastAPI 백엔드(`api_server.py`, `/api/v1/*`)를 전혀 호출하지 않는다
- Supabase(Postgres)를 인증뿐 아니라 데이터 조회에도 직접 사용한다: `properties/page.tsx`, `properties/[id]/page.tsx`가 Supabase 테이블 `properties`를 서버/클라이언트 컴포넌트에서 직접 `select`
- `properties/[id]/actions.ts`의 서버 액션(`decreaseViewCount`, `getViewCount`)이 Supabase 테이블 `view_counts`를 직접 읽고 써서 등기부 열람 횟수를 관리한다 (월 5회, `remaining_views`/`total_used` 컬럼)
- `lib/mock/*`, `lib/api/*` 디렉터리는 존재하지 않는다

## 상태관리 방식

- 전역 상태관리 라이브러리 없음
- 클라이언트 컴포넌트 로컬 `useState`/`useActionState`만 사용
- 세션 확인: 서버는 `createServerSupabaseClient().auth.getUser()`, 클라이언트는 `createClient()` 직접 호출 — `useSession()` 같은 훅 없음

## 절대 변경하면 안 되는 것

(실제 코드에서 확인되는 것만 기록 — 원 문서의 itemId 체계/Mock 시그니처 관련 정책은 해당 구현 자체가 없어 현재 코드 기준으로는 검증 불가)

- 서비스명 "콕찰" 표기 유지, "도준패스"/"도준 경매 패스" 사용 금지 (`docs/decision-log.md`)

## 알려진 문제점

- **데이터 소스 불일치(중요)**: 이 프론트엔드는 크롤러가 채우는 SQLite(`auction_item`, FastAPI `/api/v1/search`·`/api/v1/item/{id}` 경유)를 전혀 쓰지 않는다. 대신 Supabase 테이블 `properties`(컬럼: `title`, `bid_date`, `case_number`, `detail_info`, `status` 등 — `auction_item`과 이름·구조가 다름)를 직접 조회한다. 실제로 수집된 경매 데이터가 현재 이 화면에 전혀 노출되지 않는다. `docs/decision-log.md`의 "검색은 SQLite 기반" 결정, `docs/architecture.md`의 "Frontend ↓ Backend API만 호출 가능" 의존성 규칙과 실제 코드가 어긋나 있음
- **등기부 열람 로직 이중 구현**: `properties/[id]/actions.ts`가 Supabase `view_counts`로 월 5회 무료 열람을 자체 관리한다. 백엔드에도 별도로 `api/v1/registry.py`(`registry_usage`/`registry_requests`, SQLite, 평생 5회 무료)가 이미 구현되어 있으나 프론트엔드는 이를 호출하지 않는다 — 서로 다른 정책(월별 vs 평생)의 구현이 동시에 존재
- `src/login/`(도달 불가)이 구 브랜드명을 쓰는 죽은 코드로 남아있음 — 사용 여부가 확실하지 않은 코드는 임의로 삭제하지 않는다는 프로젝트 규칙에 따라 그대로 둠
- `app/layout.tsx` 메타데이터가 `create-next-app` 기본값 그대로 (title/description 미변경)
- 색상/스타일이 각 페이지에 Tailwind 유틸리티 클래스로 하드코딩되어 있음 (`bg-blue-500`, `text-gray-400` 등). 별도 디자인 토큰 파일(`styles/auction-theme.css` 등)은 존재하지 않음 — `globals.css`는 `create-next-app` 기본값(배경/전경색 변수, 폰트)만 정의
- 등기부 다운로드는 프론트·백엔드 모두 실제 파일 발급 기능이 없음 (`api/v1/registry.py`는 `501`, 프론트는 텍스트(`detail_info`)만 표시)

## 주의사항

- 이 문서는 2026-07-22 코드 재확인을 기준으로 재작성됨. 이전 버전이 전제한 NextAuth/`components/`/`lib/mock`/`lib/api` 기반 구현은 이 저장소의 `src/`에 존재하지 않았다 — 다른 브랜치, 다른 저장소, 계획 단계 문서 중 무엇이었는지는 확인되지 않음
- 코드 수정 시 수정 파일명 / 수정 함수명 / 변경 코드만 우선 제시, 전체 파일 통째 출력 지양
- 문제 발생 시 원인 → 확인 방법 → 수정 방법 순서로 설명
- 백엔드 확인이 필요한 사항은 추측하지 않는다

## 향후 개발 예정

(원 문서의 항목 대부분이 미착수로 확인됨 — 우선순위는 `docs/roadmap.md` 기준)

- 실제 백엔드(FastAPI/SQLite) 연동 여부 결정: 현재의 Supabase `properties` 직접 조회를 대체할지 병행할지 미결정 — PM 확인 필요
- 검색 페이지, 마이페이지, 구독/결제 UI, 관심물건, 최근조회, 검색조건 저장, 권리분석 화면 신규 구현
- 등기부 열람 로직 일원화 (프론트 자체 구현 vs 백엔드 `registry.py` 중 하나로 통합)
