# Frontend Overview

## 목적

- 콕찰(Kokchal, 구 도준패스): 법원경매 검색 / 상세조회 / 등기부 신청 서비스
- Beta v1 기준 (MVP 아님)
- 금지: 투자점수, AI추천, 수익률 계산, 권리분석 엔진 자체 개발(프론트는 백엔드 rights_summary 결과만 표시)

## 현재 화면 구성

- 상세페이지 카드 순서(고정): 기본정보 → 문서목록 → PDF뷰어 → 등기부등본 → 권리분석
- 검색 페이지: 저장된 검색조건 목록 + 검색폼
- 검색결과 페이지: 카드 리스트 + 정렬 + 페이지네이션
- 회원가입 / 로그인
- 관심물건 목록
- 최근조회 목록 (LRU, 최대 20개)
- /subscribe: 요금제 안내 + 구독 버튼(Mock)
- 미구현: 마이페이지 본체, 결제 UI, Success/Fail 페이지, 관리자 화면, 홈(`/`)

## 페이지 구조

| 경로 | 접근 조건 |
|---|---|
| `/search` | 제한 없음 |
| `/search/results` | 제한 없음 |
| `/auction/[itemId]` | 프리미엄 회원만. 아니면 `PremiumRequiredNotice`만 렌더링, 상세 API 미호출 |
| `/auth/signup` | 제한 없음 |
| `/auth/login` | 제한 없음 |
| `/mypage/favorites` | 로그인 필요, 미로그인 시 `/auth/login` 서버 리다이렉트 |
| `/mypage/recent` | 로그인 필요, 미로그인 시 `/auth/login` 서버 리다이렉트 |
| `/subscribe` | 제한 없음(구독 실행 시 로그인 필요) |

## Component 구조

```
components/auction/
  AuctionDetailView.tsx      카드 오케스트레이션(client), activeDoc/로딩 상태
  BasicInfoCard.tsx
  DocumentListCard.tsx
  PdfViewerCard.tsx
  RightsAnalysisCard.tsx     4섹션: 위험도/점유현황/임차인현황/분석근거
  DocumentStageBadges.tsx
  StatusBadge.tsx
  CaseStamp.tsx

components/registry/
  RegistryCard.tsx           신청/상태조회(폴링)/다운로드

components/favorites/
  FavoriteButton.tsx         등록/해제 + Toast (ResultCard, 상세페이지 공용)
  FavoritesList.tsx

components/search/
  SearchForm.tsx
  SavedSearchList.tsx
  SearchPageContent.tsx

components/results/
  ResultCard.tsx
  SortSelect.tsx
  Pagination.tsx

components/auth/
  AuthLayout.tsx, SignupForm.tsx, LoginForm.tsx, GoogleAuthButton.tsx

components/premium/
  PremiumRequiredNotice.tsx
  SubscribeButton.tsx        구독 버튼(Mock)

components/common/
  EmptyState.tsx, Toast.tsx

components/providers/
  AuthSessionProvider.tsx    NextAuth SessionProvider 래퍼
```

## Layout 구조

- `app/layout.tsx`: `AuthSessionProvider`로 전체 래핑, `metadata.title = "콕찰"`
- 공통 헤더/네비게이션: 아직 결정되지 않음
- 상세페이지 헤더(사건번호 스탬프 + 관심물건 버튼 + 타이틀)는 페이지 내부 자체 구성
- 반응형 브레이크포인트 상세 규칙: 아직 결정되지 않음

## Routing 구조

- Next.js App Router
- 단일 식별자 `itemId` 기준 통일: 목록/상세/관심물건/최근조회/검색조건저장/등기부 전부 동일 `itemId` 사용
- `caseNo`+`itemNo` 조합 사용 금지 (과거 `/auction/[caseNo]/[itemNo]` → `/auction/[itemId]`로 변경 완료)
- 인증 라우트: `app/api/auth/[...nextauth]/route.ts` (NextAuth 표준, 구글 콜백 자동 생성)

## API 호출 방식

- `lib/mock/*.ts`: 미연동 기능. 실제 API와 동일한 함수 시그니처 고정, 내부만 교체 가능
- `lib/api/*.ts`: 연동 완료 기능. `lib/api/client.ts`의 `apiFetch()` 공용 래퍼 사용 (base URL: `NEXT_PUBLIC_API_BASE_URL`, JSON 파싱/에러 처리, `Authorization: Bearer {token}` 지원)

연동 완료:
- `GET /api/v1/search` → `lib/api/fetchAuctionSummaries.ts`
- `GET /api/v1/item/{item_id}` → `lib/api/fetchAuctionDetail.ts` (문서 목록은 별도 API 없어 Mock 유지)

엔드포인트 확정, Mock 유지(JWT 활성화 대기, PM 승인 사항):
- `GET/POST/DELETE /api/v1/favorites`
- `GET /api/v1/recent-items`
- `GET/POST/DELETE /api/v1/search-presets`

인증: `Authorization: Bearer {Supabase JWT}`, `SUPABASE_JWT_SECRET` 설정 후 활성화 예정.
미해결: NextAuth 세션에 Supabase JWT 없음 — 발급/전달 방식 아직 결정되지 않음. `lib/api/authToken.ts`는 현재 `null` 고정 반환.

Mock 유지 도메인(엔드포인트 자체 미확정 또는 회신 대기):
- 권리분석: `GET /api/v1/rights/{item_id}`
- 문서 수집(매각물건명세서/감정평가서/현황조사서)
- 등기부 신청/상태조회/다운로드
- 결제(Toss)

## 상태관리 방식

- 전역 상태관리 라이브러리 없음
- 서버 컴포넌트 fetch → props 전달이 기본
- 클라이언트 상태는 필요한 컴포넌트에만 `"use client"` + `useState`
- 세션: `useSession()`(client) / `getServerSession()`(server)
- 검색조건/정렬/페이지: URL 쿼리스트링(`useSearchParams`, `router.push`)
- Mock 데이터: 각 모듈 내부 인메모리 Map/Set/배열

## UI/UX 원칙

- 무료회원은 상세페이지 진입 불가. 진입 시 `PremiumRequiredNotice`만 렌더링, `fetchAuctionDetail()`/`fetchRightsSummary()` 호출하지 않음 (이유: 불필요한 트래픽/보안 문제 방지)
- `risk_level`/명도난이도 등은 등급 라벨만 표시. 점수·순위·추천 문구 금지
- 관심물건 등록/해제 시 Toast 표시
- 반응형 필수

## 디자인 규칙

- 색상/타이포는 `styles/auction-theme.css`의 CSS 변수 토큰만 사용, 컴포넌트 내 하드코딩 금지
- 폰트: 헤딩 `Noto Serif KR`, 본문 `Pretendard`, 데이터값(사건번호/금액) `IBM Plex Mono`
- 문서 수집 상태 뱃지 색상 고정: 수집완료=녹, 수집중=황, 미수집=적
- `risk_level` 색상은 `RISK_LEVEL_COLOR` 매핑 테이블에서만 조회, 컴포넌트 내 if/else 하드코딩 금지
- 백엔드 ENUM 코드값(risk_level, review_status, tenant_rights.source 등)은 코드값으로만 송수신. 한글 라벨은 `lib/mock/labels.ts`에서만 매핑, 서버에 라벨 문자열 저장 금지

## 공통 컴포넌트

- `components/common/EmptyState.tsx`
- `components/common/Toast.tsx`
- `components/results/Pagination.tsx`
- `components/results/SortSelect.tsx`
- `components/favorites/FavoriteButton.tsx` (ResultCard, 상세페이지 공용)
- `components/auction/StatusBadge.tsx`
- `components/auction/DocumentStageBadges.tsx`

## 향후 개발 예정

- 마이페이지 본체
- 결제 UI(Toss 위젯), Success/Fail 페이지
- 관심물건/최근조회/검색조건저장 실 API 연동(JWT 활성화 이후)
- Supabase JWT 획득 방법 확정 → `lib/api/authToken.ts` 구현
- 권리분석(rights_summary) 실제 연동
- 문서 수집 파이프라인 API 연동
- 등기부 신청/상태조회/다운로드 실 API 연동
- 관리자 화면(가입자수/검색횟수/등기부 신청건수) — 후순위
- 검색/상세 API 응답 필드 전체 확정에 따른 타입/매핑 보정

## 절대 변경하면 안 되는 것

- **itemId 단일 식별자 체계.** 이유: 목록/상세/관심물건/최근조회/검색조건저장/등기부가 모두 연결되어야 하며, 백엔드가 목록↔상세 동일 itemId 반환을 검증함
- **위험도/명도난이도 등급 라벨만 노출.** 이유: 투자점수/AI추천/수익률 계산 금지 규칙
- **무료회원 상세 API 미호출 구조.** 이유: 불필요한 트래픽/보안 문제 방지
- **서비스명 "콕찰" 통일.** "도준패스" 명칭 사용 금지
- **Mock 함수 시그니처 고정.** 파라미터/반환 타입은 실 API 전환 후에도 동일하게 유지(교체만 가능한 구조)
- **등기부 신청 정책.** 결제되지 않은 registry_request는 생성하지 않음
- **결제 상품 범위.** 상품 A(월 구독, 콕찰 프리미엄, 9,900원) + 상품 B(추가 등기부, 1,000원) 2종만. 그 외 결제수단은 Beta v1 범위 아님

## 알려진 문제점

- `lib/mock/*.ts`의 인메모리 상태는 서버(Node)와 클라이언트(브라우저)에서 별도 인스턴스로 동작 — SSR 시점과 클라이언트 조작 시점 상태 불일치 가능
- `GET /api/v1/search`, `GET /api/v1/item/{item_id}` 응답은 `id`/`case_no`만 실제 예시로 확인됨. 나머지 필드명은 프론트 추정 매핑
- 검색 쿼리 파라미터 `sido`가 프론트의 "주소 자유 텍스트 검색"과 의미가 같은지 확인되지 않음
- `favorites`/`recent-items`/`search-presets` 응답이 id 목록만 주는지, 물건 요약정보까지 결합해서 주는지 확인되지 않음
- itemId가 백엔드 내부 PK(INTEGER) 그대로 노출, 순번 예측 가능 — 백엔드는 Beta v1 허용 범위로 판단, 프론트가 보안 재검토 요청했으나 결론 아직 안 남
- 상세페이지 문서 목록(`GENERIC_DOCUMENTS`)은 모든 물건에 동일하게 붙는 placeholder, 실제 물건별 데이터 아님

## 주의사항

- 코드 수정 시 수정 파일명 / 수정 함수명 / 변경 코드만 우선 제시, 전체 파일 통째 출력 지양
- 문제 발생 시 원인 → 확인 방법 → 수정 방법 순서로 설명
- 의사결정 기준: 투자자가 실제 돈을 내는 기능인지
- TypeScript strict 유지, 수정 후 타입체크 통과 확인
- 새 Mock 함수도 실 API 연동을 전제로 시그니처 설계
- 백엔드 확인이 필요한 사항은 추측 금지, 확인될 때까지 Mock 유지
