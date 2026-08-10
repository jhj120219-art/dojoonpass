# Project Roadmap

Status: Beta v1

Owner: Project Management

Last Updated: 2026-08-07

---

# Project Vision

콕찰(Kokchal)은 대한민국 법원경매 정보를 수집하고 검색·상세조회·권리분석·등기부 신청 서비스를 제공하는 플랫폼이다.

Beta v1에서는 안정적인 검색 서비스 구축을 목표로 하며,
AI 투자추천이나 자동 투자판단 기능은 범위에 포함하지 않는다.

---

# Current Status

Project Stage

Beta v1 Development

---

# Completed

## Infrastructure

- Next.js 기반 Frontend 구축
- FastAPI Backend 구축
- SQLite 기반 데이터 저장 구조 구축
- 크롤링 파이프라인 구축
- Search API 구축

---

## Search / Detail / Favorite (Release 완료 — 2026-08-05 코드 기준 재확인, 이 영역은 수정 대상 아님)

- 검색 API 구현 + 프론트 `/search` 연동 (`api/v1/search.py`, `src/app/search/*`)
- 상세조회 API 구현 + 프론트 `/properties/[id]` 연동 (`api/v1/item.py`)
- 관심물건 API + 프론트 `/favorites` 연동 (`api/v1/favorites.py`)
- 페이지네이션 구현 (offset 방식 유지)
- (참고) 최근조회 `/properties/recent`, 검색조건 저장 `search_presets.py`도 코드 상 구현·연동되어 있으나 Release 대상 목록에는 별도 명시되지 않음

---

## Authentication (Release 완료)

- Supabase Auth 실제 동작 (로그인/회원가입, `src/app/login/actions.ts`)
- JWT 검증 실제 동작 (`api/auth.py`, `SUPABASE_JWT_SECRET` 필요)
- `middleware.ts`로 `/properties/*` 세션 게이트

---

## Payment / Subscription / Premium / Registry / Admin / Download / PG Prep (Sprint 1~8 완료 — 2026-08-05, PG·실제 등기부 발급기관 연동 제외)

- `POST /api/v1/payments` Mock 결제 API (`api/v1/payments.py`), 결제 성공 시 `subscriptions` row 자동 생성(Sprint 1)
- Premium = `subscriptions` ACTIVE row 존재 여부로 판정 (`registry.py`의 `has_active_subscription()`, 신규 테이블 없음)
- 등기부 신청 프론트 연동 완료: `properties/[id]/page.tsx`가 `registry-requests`/`payments`를 직접 호출, 무료/초과 판단은 백엔드 응답 그대로 반영(프론트 자체 계산 없음). 기존 Supabase `view_counts` 구현(`properties/[id]/actions.ts`)은 삭제(Sprint 3)
- `OVERAGE_USAGE` 결제 성공 시 `registry_requests.payment_id`/`status`(PAYMENT_REQUIRED→PENDING) 자동 연결, 트랜잭션 처리(부분 성공 시 rollback), 중복 결제/레이스 가드 포함(Sprint 4)
- Admin MVP 완료: `api/v1/admin.py` — `registry_requests` 목록 조회(상태/user_id/item_id/case_no 필터) + 상태 전이(PENDING→PROCESSING/FAILED, PROCESSING→COMPLETED/FAILED), `completed_at`/`reason` 기록. 인증은 `X-Admin-Key`(Supabase JWT 아님) — `ADMIN_API_KEY`는 아직 `.env`에 미설정(Sprint 5)
- **등기부 다운로드 엔진 완료(Sprint 6)**: `GET /registry-requests/{id}/download`가 실제 파일을 서빙한다. Admin이 `COMPLETED` 전이 시 `doc_url`(필수)을 지정하면 `registry_documents/`(신규, `.gitignore`)에서 파일을 찾아 반환. 본인 신청만 다운로드 가능(소유권 검사), 경로 탐색 방지(`documents.py`와 동일 패턴). **자동 등기부 수집 엔진이 아니다** — 대법원 인터넷등기소 등 실제 발급기관과의 연동은 없고, 운영자가 수동으로 발급받아 파일을 배치하는 구조
- **등기부 다운로드 UI 완료(Sprint 7)**: `properties/[id]/page.tsx`에 상태별 UI 완성 — `PAYMENT_REQUIRED`→결제 버튼, `PENDING`/`PROCESSING`→상태 표시, `FAILED`→`reason` 표시, `COMPLETED`→"📥 등기부 다운로드" 버튼(클릭 시 실제 파일이 브라우저로 저장됨, `fetch`+`blob`+`<a download>`). `GET /registry-requests`·`{id}` 응답에 `reason` 필드 추가, CORS에 `expose_headers=["Content-Disposition"]` 추가(파일명 노출용) — 실제 브라우저로 다운로드 완료까지 Runtime QA 확인
- **PG Integration Preparation 완료(Sprint 8)**: `api/v1/payment_providers.py` 신규(`PaymentProvider`→`MockProvider`/`TossProvider`/`PortOneProvider`), `PAYMENT_PROVIDER` 환경변수로 선택. `SUBSCRIPTION` 플랜별 가격도 `PLAN_PRICES`로 서버 검증(`OVERAGE_FEE`와 동일 방식). 리팩터링 전후 Registry 체인 100% 동일 동작 Runtime QA 확인
- 미완료(2026-08-06 갱신): KG이니시스 실연동만 남음(계약·API Key 필요). 구독 플랜 UI/등기부 무료한도 정책은 확정 및 코드 반영 완료, 실제 발급기관 자동 연동은 Beta v2 범위

---

# In Progress

## Frontend

- 권리분석 화면 연동 (`rightsAnalysis.ts` REGISTRY 소스 하드코딩 해소) — 2026-08-06 조사 결과 **승인
  필요(DB 스키마 변경)로 확인되어 보류**. `tenant_rights`/`rights_summary`는 STATUS/SPEC 문서
  파싱 결과만 담는 테이블이고, 등기부(REGISTRY) 파싱 데이터를 저장할 테이블 자체가 없음(`docs/backend.md`
  Phase 2의 `registry_rights` 테이블이 아직 미착수) — 등기부 PDF는 크롤러가 수집하지 않고 운영자가
  수동 배치한 원본 파일일 뿐이라 파싱 로직도 없음. 새 테이블 추가(스키마 변경) + OCR/파싱 파이프라인
  신규 구축이 선행되어야 하는 별도 규모의 작업이라 "하드코딩 해소" 한 줄로 될 수 없음 — 사용자 승인 후 별도 Sprint로 재계획 필요
- ~~플랜 비교/선택 UI 신규 구현~~ (2026-08-06 완료 — `properties/[id]/page.tsx`, BASIC/PRO 비교 카드 + 월/연 토글 + 할인가 표시)

## Backend

- ~~등기부 무료 한도 정책 확정~~ → **2026-08-06 확정 + 코드 반영 완료**(플랜별 월 단위: 베이직 5회 / 프로 10회, 월 자동 리셋)
- ~~확정 구독 정책 코드 반영~~ → **2026-08-06 완료**: `BASIC` 12,900원/월·154,800원/년, `PRO` 22,900원/월·연 정상가 274,800원→판매가 198,000원. 할인은 `list_price`/`sale_price` 분리 구조
- `ADMIN_API_KEY`/`SUPER_ADMIN_API_KEY`를 `.env`에 설정 — **2026-08-08/09 재확인**: 변수명
  자체는 이제 `.env`에 존재한다(값 유효성은 Secret 열람 금지 원칙상 이 세션에서 미확인).
  `docs/BETA_RELEASE_CHECKLIST.md` P0-2 참고
- ~~`SUBSCRIPTION` 결제 금액 서버 검증~~ (2026-08-05 완료, 2026-08-06 `PLAN_CATALOG` 기준으로 교체 완료)

## Crawler

- 문서수집 안정화
- 자동 실행 안정화

## Search

- 검색 최적화
- 필터 개선

---

# Next Priority

Priority 1 (완료, 2026-08-05)

- ~~JWT 인증 완료~~ (Release)
- ~~Mock 제거~~ (search/item 등 완료. 단, Payment는 의도적으로 Mock 유지 — PG 미확정)
- ~~실제 API 연결~~ (search/favorites/recent-items/payments Release·Sprint 1 완료)

Priority 2 (대부분 완료, 2026-08-05)

- ~~프론트엔드 결제 UI + `registry-requests` 연동~~ (완료 — `properties/[id]/page.tsx`)
- ~~OVERAGE_USAGE 결제 → registry_requests 자동 연결~~ (완료)
- ~~관리자 페이지(등기부 신청 상태 관리)~~ (MVP 완료, `ADMIN_API_KEY` 설정만 남음)
- ~~등기부 무료 한도 정책 확정~~ → 2026-08-06 확정 + 코드 반영 완료(플랜별 월 단위)
- 권리분석 연동 — 2026-08-06 조사 결과 신규 DB 테이블(`registry_rights`) + OCR/파싱 파이프라인이
  선행돼야 하는 스키마 변경 승인 대기 상태로 확인됨(위 "In Progress > Frontend" 참고)
- 문서 수집 API

Priority 3

- ~~등기부 다운로드 엔진(수동 배치 방식)~~ (완료, Sprint 6 — 아래 Beta v2의 "실제 발급기관 자동 연동"과는 별개)
- ~~Payment Provider 구조 분리~~ (완료, Sprint 8 — PG사 확정 전 기반 구조만)
- ~~PG사 확정~~ → **2026-08-06 KG이니시스로 확정(CTO)**, ~~`KGInicisProvider` 신설~~ → **2026-08-07 완료**. 남은 작업: Interface v2 6개 메서드의 실제 API 호출 구현(외부 API Key/계약 필요 — 승인 대기). `TossProvider`/`PortOneProvider`는 폐기 예정 표기 완료
- `ADMIN_API_KEY` 운영 값 설정 + 역할(role) 구분 도입 여부 결정(현재 단일 공유키)
- 성능 최적화

---

# Beta v1 Scope

포함

- 검색
- 상세조회
- 관심물건
- 최근조회
- 검색조건 저장
- 회원가입
- 로그인
- 구독 UI (등기부 신청 카드 내에서 BASIC/PRO 두 플랜 + 월/연 결제주기를 비교·선택해 구독 가능, 2026-08-06 갱신 — 별도 페이지가 아니라 기존 카드 내 UI로 구현됨)
- 등기부 신청 구조 (백엔드+프론트+Admin MVP+다운로드 엔진까지 완료 — 아래 Success Criteria 참고. 발급기관 자동 연동만 남음)

제외

- AI 추천
- 투자점수
- 수익률 계산
- 자동 투자판단

---

# Future Roadmap

## Beta v2

- 문서 자동 수집
- 권리분석 고도화
- 등기부등본 실제 발급기관(대법원 인터넷등기소 등) 자동 연동 — 현재는 운영자가 수동으로 발급받아 배치(Sprint 6 완료 범위는 "전달" 엔진까지)

---

## Release

- PG 연동
- 결제 완료
- 관리자 기능
- 운영환경 배포
- 성능 최적화

---

# Technical Debt

- ~~Mock API 제거 필요~~ (search/item 등은 완료. Payment의 Mock 결제는 PG 미확정으로 인한 의도적 유지 — 제거 대상 아님)
- ~~JWT 연동 필요~~ (Release 완료)
- ~~등기부 열람 로직 이원화~~ (2026-08-05 해소 — 프론트 `view_counts` 삭제, `registry_usage`로 일원화)
- 문서 수집 안정화
- 검색 최적화
- DB 백업 체계 구축
- ~~`SUBSCRIPTION` 결제 금액 서버 검증 부재~~ → 2026-08-05 해결, 2026-08-06 `PLAN_CATALOG` 기반으로 갱신(할인가 포함 서버 재계산)
- Admin 인증에 역할(role) 구분 없음 (`X-Admin-Key` 단일 공유키, MVP 한계). 2026-08-07 상태 전이
  **감사 로그**는 추가했으나 단일 키라 개별 운영자를 특정할 수는 없다
- ~~bare `except:` / 과잉 `except Exception` / 미사용 import / 함수 내부 import~~ → 2026-08-07 정리 완료
  (AST 전수 재조사 결과 미사용 import 잔여 **0건**)
- ~~API 서버 로깅 설정 부재~~ → 2026-08-07 해소(`logging.basicConfig` + `LOG_LEVEL`)
- ~~프론트/서버 정렬 비결정성~~ → 2026-08-07 전 도메인 `id` tie-break 적용
- **`PLAN_OPTIONS`(프론트) ↔ `PLAN_CATALOG`(서버) 이중 관리** — 드리프트는 회귀 15번이 감지하지만
  구조적으로는 서버가 카탈로그를 내려주는 편이 맞다
- **목록 엔드포인트 LIMIT 부재**(`favorites`/`payments`/`registry-requests`) — 응답 구조 변경 필요
- **`(user_id, status)` 복합 인덱스 부재** — 구독/초과결제 조회가 `status` 인덱스를 타고
  TEMP B-TREE 정렬을 만든다(2026-08-07 실행계획 실측)
- **외부 예외/로그 수집 없음**(Sentry 등) — 운영에서 과거 로그 추적 불가
- **selenium 미설치** — 크롤러 **실동작** 테스트(`test_docs.py` 등)는 여전히 실행 불가.
  다만 순수 로직 테스트 2건(`test_doc_storage_atomicity.py`/`test_crawl_resume.py`)은
  2026-08-10 Sprint 47에 의존성 분리(`crawler/doc_paths.py`/`crawler/resume.py`)로 복구됨
- **`storage/`가 통째로 gitignore** — 그 안의 수정이 이력 없이 사라질 수 있다.
  실제로 Sprint 47에 `checkpoint.py`의 원자적 쓰기(BUGS #23)가 유실된 것을 발견해
  복구했다(BUGS #28). 회귀 테스트가 유일한 안전장치다

---

# Sprint Backlog

## [완료] PG 명칭 정리 / Admin·Release Audit / 기술부채·회귀 확대 (Sprint 26, 2026-08-07)

배경: KG이니시스 확정(2026-08-06) 이후 코드/문서에 남아있던 Toss 기준 서술을 정리하고,
Beta 출시 기준으로 Admin·전 도메인·성능·보안·문서를 전수 감사한다. 승인이 필요한 작업
(실연동, `.env` 수정, 스키마 변경, 패키지 설치, 파일 삭제)은 전부 Skip하고 기록만 한다.

완료

- **PG**: `KGInicisProvider` 신설(6개 메서드 자리 구현), `PAYMENT_PROVIDER=kginicis` 허용값 추가,
  `toss`/`portone`은 폐기 예정 표기 + 선택 시 경고 로그, 알 수 없는 값은 허용값 목록과 함께 즉시 실패.
  문서 7종의 Toss 기준 서술을 KG이니시스 기준으로 갱신
- **Bug(신규 발견·수정)**: 정렬 비결정성 — `get_user_free_limit()`의 `ORDER BY started_at DESC`가
  전순서가 아니라 플랜 업그레이드 직후 옛 플랜 한도가 적용될 수 있었다(`docs/BUGS.md` #16).
  전 도메인 6개 쿼리에 `id` tie-break 일괄 적용. **Admin 목록은 offset 페이지네이션이라
  동률 행 중복/누락까지 가능했던 지점**
- **Lint 2 → 0**: `react-hooks/set-state-in-effect` 2건을 파생 상태 방식으로 해소.
  부수적으로 문서 뷰어의 늦은 응답 경쟁 상태, 시/군/구 로딩 중 이전 값 잔상도 함께 사라짐
- **기술부채**: bare `except:` 2건 제거, `favorites.py`의 과잉 `except Exception`(DB 오류를
  "이미 등록됨"으로 오안내) 수정, 미사용 지역변수 제거, 함수 내부 import 4건을 모듈 최상단으로
- **Performance**: `doc_stats.py`의 6회 COUNT 스캔 → 단일 `GROUP BY` 1회
- **Security**: CORS 허용 Origin을 `CORS_ALLOW_ORIGINS`로 제한 가능(미설정 시 기존 `*` 유지),
  검색조건 저장 서버측 입력 검증(이름/크기/개수 상한), Admin 인증 실패·상태 전이 감사 로그,
  `documents.py`의 NULL 컬럼 500 → 404
- **UX/Release**: `layout.tsx` 메타데이터가 `create-next-app` 기본값이던 문제 해결(`콕찰`, `lang="ko"`)
- **Test**: 회귀 118 → **163 검사**(Provider 레지스트리 / 정렬 결정성 / 플랜 tie-break / 입력 검증
  / **API 표면 고정** / **응답 envelope 계약** / CORS 설정)
- **문서**: `docs/API_KEY_CHECKLIST.md` 신설 — 요청 카테고리 16종을 전부 코드에서 검색해
  참조 지점까지 기록. 실제로 읽는 env는 8개뿐이고 OAuth/SMTP/Storage/Analytics/Monitoring/
  SNS/OCR/지도/메일은 참조 0건임을 확정. env 드리프트 실측(`.env`의 `SUPABASE_URL`/
  `SUPABASE_ANON_KEY`는 코드가 읽지 않음)
- **Bug(추가 발견·수정) 2건**:
  (1) **API 서버에 로깅 설정 자체가 없어** 같은 날 추가한 Admin 감사 로그(`logger.info`)가
  전량 유실되고 있었다 — 크롤러와 같은 포맷으로 `basicConfig` 추가, `LOG_LEVEL` 도입
  (2) `documents.py`의 GET/HEAD 겸용 라우트가 **같은 operationId를 생성**해 `/openapi.json`
  생성 시마다 경고가 나고 클라이언트 생성이 깨졌다 — 라우트 분리로 해소
- **Architecture**: AST 미사용 import 재조사(47모듈) → 2건 제거 후 잔여 0건.
  미사용 Component/Type 0건 재확인. 프론트 미호출 엔드포인트는 전부 운영/테스트/Admin UI용으로
  의도된 것임을 확인하고 회귀 16번으로 집합을 고정
- **Performance**: 실행계획 실측 — 검색/최근조회/무료횟수는 인덱스 적중. 구독·초과결제 쿼리가
  `status` 인덱스를 타는 문제와 목록 LIMIT 부재는 **스키마/응답 구조 변경이라 미착수·기록**
- **문서 정합성**: CLAUDE(architecture.md 위치), backend(DB 절대경로, **존재하지 않는
  `X-Test-User-Id` 헤더 안내 삭제**), crawler(절대경로), frontend(`components/` 부재·플랜 UI·
  검색조건 저장 UI·평생 누적 한도·로그아웃 미노출 — 전부 stale이었음) 정정

- **Critical 발견**: 레거시 `auction` 테이블의 `UNIQUE(case_no, item_no)`에 법원이 빠져 있어
  다른 법원 물건이 매일 크롤링에서 **소실**된다(`docs/BUGS.md` #18, 사본 DB로 재현).
  승인 없이 가능한 완화 3종 적용(덮어쓰기 WARNING 로그 / `migrate_execute.py` 식별키를
  `(case_id, item_no)`로 차단 / 위험 규모 감시 테스트). 근본 수정인 스키마 변경은 승인 대기
- **TODO 탐색**: 코드 전체 스윕 결과 실제 TODO는 프론트 4건뿐이며 전부 백엔드 미지원 컬럼에
  대한 정직한 표기. `SearchForm.tsx`의 "단일 선택시에만 API 연동" TODO는 stale로 확인(정정)

Skip (승인 필요 — 기록만)

- **`auction` 테이블 `UNIQUE(court_code, case_no, item_no)` 스키마 변경 (#18)** — 데이터 소실 중
- KG이니시스 실연동 6개 메서드 구현 (계약·API Key·Webhook)
- `ADMIN_API_KEY` `.env` 설정
- `src/login/` 죽은 디렉터리 삭제(금지된 옛 브랜드명 사용 중)
- Rate Limit 도입(패키지 설치 필요)
- `registry_requests` 감사 컬럼 추가(스키마 변경)
- `/properties` 화면 처리 방향(Spec), Admin UI 신설(Spec)

---

## [다음 Sprint 후보] Beta 출시 직전 정리 (Sprint 27)

승인 없이 착수 가능한 것부터. 위 Skip 항목의 결정이 나면 그쪽이 우선한다.
**단 `docs/BUGS.md` #18(레거시 `auction` 키로 인한 물건 소실)은 매일 재발하고 되돌릴 수 없으므로
승인만 나면 아래 어느 항목보다 먼저 처리한다.**

1. ~~`properties/[id]/page.tsx`의 stale 주석 정리~~ → **Sprint 26에서 함께 처리**
   (다운로드 501 서술, 존재하지 않는 `registry.py:9 FREE_LIMIT` 참조 정정)
2. ~~`PLAN_OPTIONS` ↔ `PLAN_CATALOG` 정합성 회귀 테스트~~ → **Sprint 26에서 함께 처리**
   (`test_api_regression.py` 15번 — 한도/정상가/청구액 6항목 × 2플랜)
3. ~~`TEST_PLAN.md` / `README.md` 정합성~~ → **Sprint 26에서 함께 처리**.
   `search-engine.md`/`AI_CONTEXT.md`는 감사 결과 코드와 일치해 수정 없음
4. `admin.py`/`search.py`의 `LIKE` 필터에서 사용자 입력의 `%`/`_` 이스케이프 처리 —
   **Sprint 26에서 의도적으로 보류**. 보안 취약점은 아니고(파라미터 바인딩이라 인젝션 불가)
   와일드카드 의미론만 바뀌는 문제인데, `search.py`의 8개 조건 전체를 바꾸면 사용자가 체감하는
   검색 동작이 달라진다 — "Spec 변경 금지" 원칙상 PM 확인 후 착수
5. Admin 목록의 `JOIN auction_item`이 INNER라 물건이 사라진 신청이 목록에서 통째로 빠지는 문제
   (LEFT JOIN 전환 검토 — 현재 DELETE 경로가 없어 실제 발생은 안 하지만 구조적 사각지대)
6. `PLAN_OPTIONS` 미러 자체를 없애는 방향 검토 — 서버가 카탈로그를 반환하는 엔드포인트를 두면
   프론트/서버 이중 관리가 사라진다(현재는 회귀 15번으로 드리프트만 감지)
7. **(승인 필요)** `(user_id, status)` 복합 인덱스 추가 — 활성 구독 조회와 초과결제 대상 선택이
   `status` 인덱스를 타고 TEMP B-TREE 정렬을 만드는 것을 실행계획으로 실측함. 사용자·구독 수가
   늘수록 나빠지는 구조라 Beta 트래픽이 붙기 전에 결정하는 편이 좋다(스키마 변경)
8. **(승인 필요)** `favorites`/`payments`/`registry-requests` 목록 페이지네이션 —
   현재 LIMIT이 없다. 응답 구조가 배열이라 `{total, items}`로 바꾸면 Breaking Change라
   프론트 동시 수정이 필요하다
9. **(승인 필요)** 외부 예외/로그 수집(Sentry 등) 도입 — 2026-08-07에 서버 로깅 설정을 신설했지만
   stdout 스트림뿐이라 운영에서 과거 로그를 되짚을 수 없다. 패키지 설치 필요
10. **(승인 필요)** selenium 설치 — 크롤러 계열 테스트(`test_db.py` 등)가 이 환경에서
   `ModuleNotFoundError`로 실행 불가하다. 크롤러 회귀를 전혀 돌리지 못하는 상태

---

## [완료] Security/Type/Performance Review (Sprint 15, 2026-08-06)

배경: Beta Release 품질 향상을 위해 처음으로 전용 Security Review를 수행. Sprint Backlog(P2)는
UX/Spec 결정이 선행돼야 해 Skip(위 참고), Critical Path는 PG사 확정 대기라 Security Review로 진행.

완료

- `api/v1/*.py` 전체에서 f-string 기반 SQL 조립 지점을 재확인 — `search.py`/`admin.py`/`payments.py`
  모두 컬럼명/연산자만 하드코딩 리터럴이고 실제 값은 전부 `?` 파라미터 바인딩(`params` 리스트)이라
  SQL Injection 여지 없음을 재확인(수정 불필요)
- **발견 및 수정**: `api/v1/admin.py:require_admin()`이 관리자 키를 `x_admin_key != admin_key`
  단순 문자열 비교로 검증하고 있었음 — Python의 문자열 `!=`는 앞에서부터 다른 문자가 나오는
  즉시 반환되어, 비교에 걸리는 시간이 일치하는 접두 길이에 비례하는 타이밍 사이드채널이 이론상
  존재함. `hmac.compare_digest()`로 상수 시간 비교하도록 교체
- `api/auth.py`의 JWT 검증(`algorithms=["HS256"]` 하드코딩)은 알고리즘 혼동 공격 여지 없음을 확인(수정 불필요)
- `api/v1/documents.py`/`api/v1/registry.py`의 경로 탐색 방지(`commonpath` 검사)는 파일명이
  DB 조회 결과의 화이트리스트 값으로만 결정되어 안전함을 재확인(수정 불필요)
- `favorites.py`/`search_presets.py`/`recent_items.py`는 전부 `WHERE user_id=?` 소유권 검사+
  파라미터 바인딩 확인(수정 불필요)
- Runtime QA: `require_admin()`을 직접 호출해 (1) 올바른 키 → 통과, (2) 틀린 키 → 403,
  (3) 키 미제공 → 403, (4) `ADMIN_API_KEY` 미설정 → 500, 4가지 시나리오 모두 수정 전과 동일한
  결과임을 확인(로직 변화 없음, 비교 방식만 상수 시간으로 교체)
- Compile/Import 확인: `python -m py_compile api/v1/admin.py` 통과, `api_server.py` 전체
  import 및 라우트 등록(16개) 정상 확인
- Admin 인증이 여전히 단일 공유키(role 구분 없음)라는 구조적 한계는 이번 Sprint 범위 밖(기존
  MVP 결정 유지, `docs/decision-log.md` 참고) — 타이밍 공격 방어만 추가한 것으로, 키 자체가
  유출되면 여전히 무방비임에 유의

**같은 Sprint, Type 개선**: `src/app/login/actions.ts`의 `loginAction`/`signUpAction`이 쓰던
`prevState: any` 2건을 `login/page.tsx`의 실제 `useActionState` 상태 모양에 맞춰 명시적 타입으로
교체(런타임 동작 무변경, lint 오류 5→3건).

**같은 Sprint, Performance Review**: `api/v1/favorites.py:get_favorites()`가 즐겨찾기 개수만큼
`get_item_summary()`를 반복 호출하던 N+1 쿼리를 `recent_items.py`와 동일한 단일 JOIN 패턴으로
교체. 롤백 트랜잭션 안에서 기존/신규 로직 출력이 완전히 일치함을 확인(Runtime QA), DB 영구
변경 없음.

---

## [완료] run_daily.bat 실패 은폐 구조 개선 (Sprint 13, 2026-08-06)

배경: migrate_execute.py 로그 파일 잠금 버그(2026-07-27 수정 완료) 조사 중, run_daily.bat가
migrate_execute.py 실패 후에도 뒤따르는 echo 명령 때문에 배치 자체의 종료코드가 0(성공)으로
남는 구조적 결함이 확인됨. Task Scheduler의 LastTaskResult가 실제 내부 실패를 반영하지 못함.

완료

- 재확인: `run_daily.bat`는 `mvp_scraper.py`/`migrate_execute.py` 실행 줄 뒤에 조건 없는
  `echo` 2줄이 항상 실행되는 구조라, 두 스크립트가 0이 아닌 exit code로 끝나도 배치의
  마지막 명령(`echo`, 항상 성공)이 배치 전체 종료코드를 결정해 항상 0으로 남는 것을 확인함.
  `migrate_execute.py`는 이미 `sys.exit(0)/sys.exit(1)`을 정확히 반환하고 있어 이 값을
  bat가 그냥 확인만 안 하고 있었음
- `mvp_scraper.py` 실행 직후 / `migrate_execute.py` 실행 직후 각각 `if errorlevel 1`으로
  즉시 확인 → 실패 시 다음 단계로 진행하지 않고 `exit /b 1`로 즉시 종료
- 실패한 스크립트명과 종료코드를 `logs\daily_run.log`에 `[FAILED] <script>.py exited with
  code %errorlevel% at <timestamp>`로 명시 기록. 성공 시에도 `[SUCCESS] Finished at
  <timestamp>`로 구분 기록
- Runtime QA: 격리된 스크래치 디렉터리에서 동일 구조의 더미 배치 파일로 (1) 1단계 실패 → 2단계
  건너뜀 + 배치 exit code 1 + 실패 로그 기록, (2) 전체 성공 → 배치 exit code 0 + 성공 로그
  기록, 두 시나리오 모두 실제 cmd.exe 실행으로 재현·확인함(실제 크롤러는 courtauction.go.kr에
  대한 실제 크롤링을 유발하므로 이번 QA에서 직접 실행하지 않음)
- `run_doc_worker.bat`/`run_priority_refresh.bat`는 각각 파이썬 호출이 마지막 명령이라 이미
  자신의 exit code가 배치 exit code로 정상 전파됨을 확인 — 수정 대상 아님
- `mvp_scraper.py` 내부의 법원(court)별 개별 try/except(부분 실패 시에도 계속 진행)는 기존
  설계 그대로 유지 — 이번 Sprint는 bat 구조 개선만 범위, 크롤러 내부 예외 처리 정책 변경은
  범위 밖(변경 시 별도 Sprint 필요)

---

## [P2] 로그인 UX 개선 — 비회원 검색 우선 흐름

배경: 현재는 첫 화면에서 로그인부터 시작하는 UX. 향후에는 비회원도 검색/검색결과까지는
볼 수 있고, 상세 진입 시점에 로그인을 요구하는 흐름으로 변경할 계획.

목표(다음 Sprint 후보, 이번 Sprint는 등록만)

- 비회원 → 검색 → 검색결과 → 상세 진입 시 로그인 흐름으로 전환
- 현재 `/properties/*`를 게이트하는 middleware 인증 로직 재검토 필요 (docs/CLAUDE.md 참고)

이번 Sprint 범위: 등록만 함. 구현하지 않음.

2026-08-10 업데이트: **이 항목은 스펙이 전부 확정됐다** — `docs/FRONTEND_MASTER_SPEC.md`(신규,
Frontend 최상위 기준) + `search/00_SEARCH_MVP.md` v0.2(검색 화면 상세).

- 첫 화면: `/`의 무조건 redirect(`src/app/page.tsx`)를 제거하고 `/` 자체를 검색 화면으로 만든다
- 공개 범위: 검색 / 결과 / 목록 탐색 / 정렬 / 페이지 이동까지 비로그인 허용
- **상세(`/properties/[id]`)는 로그인 필수로 확정** — "무엇을 보여줄지"는 더 이상 미결정이 아니다.
  비로그인은 목록까지 보고, 물건 클릭 시 로그인으로 이동한 뒤 원래 상세 URL로 복귀한다.
  `middleware.ts`의 `/properties/*` 게이트는 이 정책과 일치하므로 유지하고, redirect가
  쿼리스트링을 버리는 결함만 수정한다
- 검색 API 변경 없음

**2026-08-10 Sprint 44에서 P0·P1 구현 완료** — 첫 화면 redirect 제거(`/`=검색 화면),
`/`·`/search` 화면 공유(`SearchScreen`), 검색 실행의 pathname 유지, 공통 Header(`SiteHeader`),
1320px 컨테이너 단일화(`src/lib/layout.ts`), 반응형 1/2/3열, 로그인 redirect의 쿼리스트링 보존
(middleware + 상세 액션 3곳), 로그인 기본 복귀 경로 `/`. 자세한 내용은 `docs/CHANGELOG.md`.

**2026-08-10 Sprint 45**: 프론트엔드 자동 테스트 신규(`npm run test:frontend`, 20검사,
Node 내장 러너 — 새 의존성 없음), 상세 화면 공통 Header 적용(네비게이션 막다른 길 해소),
Backlog 6건 코드 근거로 조사 완료(`docs/CHANGELOG.md`).

남은 것: `/properties` 레거시 화면 처리(미결정 — 코드상 inbound 링크 0건인 고아 상태로 확정)와
아래 환경 이슈.

**[해결됨 · 2026-08-10 Sprint 46]** 로그인 사용자의 Supabase JWT를 FastAPI가
401로 거부한다(`docs/BUGS.md` #27). Supabase 프로젝트가 **ES256 비대칭 서명으로 전환**됐음을
JWKS 엔드포인트(200, `kty=EC`/`alg=ES256`)로 확인했는데, 백엔드 검증 3곳
(`api/auth.py:20-23`, `api/v1/item.py:47-48`, `api/v1/search.py:145-146`)이 여전히
`algorithms=["HS256"]` + 공유 시크릿 고정이다. ES256 토큰은 이 방식으로 원리상 검증되지 않는다.

**Secret 교체로는 해결되지 않는다 — 검증 코드를 JWKS 기반 ES256으로 바꿔야 한다**
(`python-jose`가 이미 지원하므로 신규 라이브러리 불필요, `kid` 기반 키 선택 + 캐시 필요,
전환기에는 HS256 병행 허용 권장). Sprint 46에서 JWKS 기반 ES256 검증을 도입해 **해결**했다(HS256 병행 유지, `docs/BUGS.md` #27).
실제 Supabase 토큰으로 401 → 200 전환을 확인했다. **API 서버 완전 재기동 필요.**

2026-08-06(Sprint 15) 재확인: `/search`는 이미 비로그인 접근 가능(기존 구현, `middleware.ts`가
`/properties/*`만 게이트). 남은 범위는 "상세(`/properties/[id]`) 진입 시 무엇을 보여줄지"인데
— 전체 정보를 다 보여줄지, 일부만 보여주고 로그인 유도 배너를 띄울지, 로그인 모달로 막을지 등
UX/정책이 확정되지 않은 상태. 이건 코드 구현 문제가 아니라 화면 스펙(Spec) 결정이 선행돼야
하는 항목이라(이번 세션 원칙상 "Spec 변경 금지"), 임의로 범위를 정해 구현하지 않고 Skip함.
PM이 "상세 페이지에서 비회원에게 무엇을 보여줄지" 결정하면 바로 착수 가능.

---

## [완료] Payment Sprint 2~4 — 프론트 연동 / 결제-Registry 연결 / Admin MVP

배경: Sprint 1(2026-08-05)에서 `payments`/`subscriptions`/Premium 판정까지 백엔드 체인은
Runtime QA로 검증 완료. 이후 3개 Sprint에 걸쳐 아래를 완료함(계획했던 "Sprint 2" 범위 중
무료한도 정책 확정만 남고 나머지는 완료):

- ~~`registry_requests`/`payments` 프론트 연동~~ (완료 — `properties/[id]/page.tsx`, Supabase `view_counts` 삭제)
- ~~`registry.py`의 PAYMENT_REQUIRED 분기와 `payments`(OVERAGE_USAGE) 실제 연결~~ (완료 — 트랜잭션/중복방지/rollback 포함)
- ~~관리자 페이지(MVP)~~ (완료 — `api/v1/admin.py`, 목록조회+상태전이+completed_at/reason)
- 미완료: 등기부 무료 한도 정책 확정(평생 vs 월), 구독 플랜 비교/선택 UI, `ADMIN_API_KEY` 운영 설정

---

## [완료] PG Integration Preparation Sprint (Sprint 8, 2026-08-05)

배경: PG사(Toss/PortOne 등)가 아직 미확정이라 실제 승인 연동은 만들 수 없지만, 그 전에
결제 로직을 Provider 구조로 분리해두면 PG사 확정 후 교체 범위를 최소화할 수 있음.

완료

- `api/v1/payment_providers.py` 신규: `PaymentProvider`(인터페이스) → `MockProvider`(사용 중)
  / `TossProvider`·`PortOneProvider`(자리만, `NotImplementedError`)
- `payments.py`의 `create_mock_payment()` → `create_payment_record()`로 교체, `provider.charge()`
  결과를 그대로 기록 — 라우터가 SQLite에 직접 쓰는 기존 구조는 그대로 유지(서비스 계층 아님)
- 환경변수 `PAYMENT_PROVIDER`(mock/toss/portone, 기본값 mock) 도입 — 미설정 시 기존과 100% 동일 동작
- ~~`SUBSCRIPTION` 플랜별 가격 서버 검증~~ 완료: `PLAN_PRICES`(`BETA_EARLYBIRD`=9,900원, `STANDARD`=22,900원) 도입, `OVERAGE_FEE`와 동일한 방식
- Runtime QA로 Subscription/Overage/Registry/Premium/Download 체인이 리팩터링 전후 100% 동일하게 동작함을 확인

남음 (PG사 확정 후)

- PG사 확정 (사용자/PM 의사결정 필요, 코드로 판단 불가)
- `TossProvider`/`PortOneProvider` 실제 구현(결제창 연동, 승인 API 호출)
- 결제 승인 콜백/웹훅 → `payments.status` 갱신, 실패/취소 처리
- `PAYMENT_PROVIDER`를 `.env`에 실제 값으로 설정

---

## [완료] Payment Final Audit Sprint (Sprint 9, 2026-08-05)

배경: PG 실연동 전 마지막 감사. 새 기능이 아니라 남아있는 Risk 제거가 목적이며, 이번
Sprint에서는 코드 수정 없이 감사만 수행함(다음 Sprint에서 수정 예정).

완료 (감사 항목)

- Payment 상태 전이: `SUCCESS`(실사용), `FAILED`(구조상 존재하나 MockProvider가 항상 SUCCESS라
  현재 도달 안 함), `PENDING`(컬럼 DEFAULT로만 존재, 실제로 쓰인 적 없음), `REFUNDED`(코드
  0건, 환불 기능 자체 없음) — 죽은 상태 2개 확인
- DB 정합성: SQLite FK가 앱에서도 강제되지 않음(`PRAGMA foreign_keys` 없음) 확인. 단 DELETE
  경로가 없어 실제 orphan은 없음. Rollback은 `payments.py`/`admin.py`는 명시적, `registry.py`는
  암묵적(`conn.close()`의 자동 rollback, 실측 확인)이라 안전하지만 일관성 문제로 기록
- Provider 구조: 실제 Toss/PortOne 연동에는 부족함 확인 — 웹훅/재검증/멱등성 개념이 빠짐
- Payment 정책: `PLAN_PRICES`/`OVERAGE_FEE`/무료정책/30일정책 모두 코드-문서 100% 일치 확인(수정 불필요)
- **Security: 등기부 무료횟수 레이스 컨디션을 스레드 동시 요청으로 실제 재현 — 5회 제한이 8회까지
  뚫림을 확인 (Release Blocking)**
- Runtime QA: Subscription/Premium/Registry/Download/Admin/Payment/Search/Detail/Favorite 전부 회귀 통과

다음 Sprint(수정 필요)

- ~~등기부 무료횟수 레이스 컨디션 수정~~ → **Sprint 10에서 완료**(아래 참고)

---

## [완료] Release Blocking Fix — Registry Free Limit Race Condition (Sprint 10, 2026-08-05)

배경: Sprint 9(Payment Final Audit)에서 실증한 Release Blocking 버그를 수정. 다른 기능은
건드리지 않음.

완료

- `registry.py:create_registry_request()`에 `conn.isolation_level = None` + `BEGIN IMMEDIATE`
  적용 — 무료횟수 확인(`get_free_count()`)과 INSERT를 하나의 원자적 트랜잭션으로 묶음
- `payments.py`의 `OVERAGE_USAGE`(조건부 UPDATE+rowcount)와 목적은 같지만, 이쪽은 COUNT
  집계값을 다루므로 row 단위 조건부 UPDATE로는 막을 수 없어 트랜잭션 자체를 직접 제어
- 기존 API 응답 구조, Frontend, DB 스키마는 전혀 변경하지 않음(요청대로)
- Runtime QA: 5/10/20 스레드 동시 요청 테스트 전부에서 정확히 5건만 무료 처리, 나머지는
  `PAYMENT_REQUIRED`로 정상 처리됨을 실증 확인(수정 전엔 5스레드로도 8건까지 초과됐음)
- Subscription/Premium/Registry/Payment/Download/Admin/Search/Detail/Favorite 전부 회귀 통과

---

## [완료] Payment Provider Interface v2 (Sprint 11, 2026-08-05)

배경: 실제 PG(Toss/PortOne) 연동을 위해 Provider 인터페이스를 확장. 실제 PG API 호출,
Webhook 서버, Frontend, DB 스키마는 이번 Sprint 범위에서 제외.

완료

- `PaymentProvider`에 5개 메서드 추가: `create_order()`(주문 생성) / `confirm_payment()`(결제
  승인) / `cancel_payment()`(취소·환불) / `verify_payment()`(서버가 PG API로 재확인) /
  `handle_webhook()`(Webhook payload 정규화) — 기존 `charge()`는 그대로 유지
- `MockProvider`가 6개 메서드(기존 `charge()` + 신규 5개) 전부 구현, 항상 성공 응답
- `TossProvider`/`PortOneProvider`는 여전히 자리만 — base class의 `NotImplementedError`를
  그대로 상속해 6개 메서드 모두 호출 시 명확히 실패함을 확인
- **`api/v1/payments.py`는 전혀 수정하지 않음** — 여전히 `charge()`만 호출, 신규 5개 메서드는
  아직 어떤 엔드포인트에서도 호출되지 않음(다음 Sprint에서 PG사 확정 후 연결 예정)
- Runtime QA: `MockProvider`로 주문 생성→결제 승인→검증→취소→Webhook Mock 전체 흐름 직접 호출
  검증. `TossProvider` 선택 시 6개 메서드 전부 `NotImplementedError` 확인
- Subscription/Premium/Registry/Payment/Download/Admin/Search/Detail/Favorite 전부 회귀 통과(무변경 확인)

---

## [완료] Payment Flow Migration (Sprint 12, 2026-08-05)

배경: Sprint 11에서 Interface v2를 만들었지만 `payments.py`는 여전히 `charge()`만 호출했다.
이번 Sprint에서 실제 PG 흐름과 동일한 순서로 연결한다. 실제 PG API/Webhook 서버는 여전히 금지.

완료

- `payments.py:create_payment_record()`가 `provider.charge()` 대신 `create_order()` →
  `confirm_payment()` → `verify_payment()` 순서로 provider를 호출하도록 변경
- `MockProvider`는 그대로 사용(수정 없음), `TossProvider`/`PortOneProvider`는 여전히 구현 금지
- 반환 시그니처(`payment_id`, `status`)는 그대로 유지 — 호출부(구독 생성/등기부 연결 로직)는
  전혀 수정하지 않음
- Runtime QA: `SUBSCRIPTION`/`OVERAGE_USAGE` 둘 다 새 Flow로 정상 동작(결제 SUCCESS, 구독
  생성, 등기부 `payment_id` 연결까지 확인)
- Subscription/Premium/Registry/Payment/Download/Admin/Search/Detail/Favorite 전부 회귀 통과
- `cancel_payment()`/`handle_webhook()`은 이번에도 연결하지 않음(환불·Webhook 엔드포인트 자체가
  없어 범위 밖)

---

## [완료] Registry Download Engine Sprint (Sprint 6, 2026-08-05)

배경: Admin MVP(상태 관리)는 완료됐으나 `GET /registry-requests/{id}/download`가 여전히
`501`이었음. `documents.py`/`document_queue`/`doc_worker`를 분석한 결과, 기존 크롤러
파이프라인은 STATUS/SPEC/APPRAISAL(법원 공개 서류)만 다루고 등기부등본(대법원 인터넷등기소
발급)은 애초에 수집 대상이 아니었음(`doc_crawler.py:collect_document`에 registry 타입 자체가
없음) — 자동 수집 엔진을 새로 만드는 것은 실제 발급기관 연동이 필요한 별도 프로젝트 규모라
이번 Sprint 범위 밖으로 판단.

완료

- `registry_documents/`(신규, `.gitignore`) + Admin `doc_url`(COMPLETED 시 필수) → 실제 파일 서빙
- 본인 신청만 다운로드 가능, 경로 탐색 방지(`documents.py`와 동일 패턴)
- 상태별 정확한 메시지 반환(PENDING/PROCESSING/FAILED 등, 거짓 UI 없음)

남음(Beta v2 범위로 이관)

- 대법원 인터넷등기소 등 실제 발급기관과의 자동 연동(현재는 운영자가 수동으로 발급받아 배치)

---

## [완료] Registry Download UI Sprint (Sprint 7, 2026-08-05)

배경: Sprint 6에서 백엔드 다운로드 엔진은 완성했으나, 프론트(`properties/[id]/page.tsx`)에는
`COMPLETED` 상태여도 실제로 파일을 내려받는 버튼이 없었음(직전 Sprint 보고에서 발견된 gap).

완료

- 상태별 UI 완성: `PAYMENT_REQUIRED`→결제 버튼(기존), `PENDING`/`PROCESSING`→상태 표시(기존),
  `FAILED`→`reason` 표시(신규), `COMPLETED`→"📥 등기부 다운로드" 버튼(신규)
- `handleDownloadRegistry()`: `GET /registry-requests/{id}/download` 호출 → 응답이 JSON(미완료)인지
  실제 파일(COMPLETED)인지 `Content-Type`으로 판별 → 파일이면 `blob`+`<a download>`로 브라우저 다운로드 실행
- `registry.py`의 `GET /registry-requests`·`{id}`에 `reason` 필드 노출 추가(기존 필드 유지, 추가만)
- `api_server.py` CORS에 `expose_headers=["Content-Disposition"]` 추가 — 브라우저가 기본적으로
  숨기는 헤더를 노출해 실제 파일명(`19.pdf` 등)을 프론트가 읽을 수 있도록 함
- Runtime QA: 실제 브라우저(Chrome)에서 버튼 클릭 → `Downloads` 폴더에 실제 파일 저장 확인
  (Supabase 실로그인 세션이 없는 환경이라, 코드와 동일한 fetch+blob+anchor 로직을 실제 백엔드에
  대해 실행하는 최소 테스트 페이지로 검증 — 아래 Runtime QA 절 참고)

---

# Risks

- ~~[Release Blocking] 등기부 무료횟수 레이스 컨디션~~ → 2026-08-05 Sprint 10에서 수정 완료(`BEGIN IMMEDIATE`, 5/10/20 스레드 테스트로 재검증)
- `registry-requests` POST가 이제 DB 전체 쓰기 락을 잠깐 선점한다(`BEGIN IMMEDIATE`) — 현재 트래픽 규모에선 문제 없으나, 등기부 신청이 폭증하면 다른 쓰기 요청과의 대기 시간 증가 가능성 있음(모니터링 필요, Non-blocking)
- SQLite 단일 DB 운영
- 문서 수집 실패 가능성
- ~~PG사 미확정으로 인한 Payment Mock 장기화~~ → 2026-08-06 KG이니시스 확정으로 의사결정 병목은 해소. 다만 계약/API Key 발급이라는 **외부 절차**가 새 병목이며, 그동안 Mock 상태는 계속 유지됨
- ~~등기부 무료한도 정책(평생 vs 월) 미확정~~ → 2026-08-06 확정(플랜별 월 단위)
- ~~확정 Spec과 코드의 불일치~~ → 2026-08-06 해소(구독 정책 코드 반영 완료). 다만 기존 `BETA_EARLYBIRD` 구독 row가 운영 DB에 있다면 새 플랜으로 해석되지 않아 `DEFAULT_FREE_LIMIT`(5)로 폴백한다 — 이관 방침 미정(동작은 안전)
- ~~`SUBSCRIPTION` 결제 금액 서버 미검증~~ → 2026-08-05 해결(Sprint 8)
- ~~Payment Provider 인터페이스가 실제 Toss/PortOne 흐름을 수용하지 못함~~ → 2026-08-05 Interface v2로 해결, 같은 날 `payments.py`가 `create_order`/`confirm_payment`/`verify_payment` 3개를 실제로 호출하도록 연결 완료(Sprint 12). `cancel_payment`/`handle_webhook`은 여전히 미호출(환불·Webhook 엔드포인트 자체가 없어 PG사 확정 후 작업)
- Admin 인증이 단일 공유키(`X-Admin-Key`)라 유출 시 전체 Registry 상태를 조작당할 위험 — 운영 전 역할 구분/키 로테이션 정책 필요. 2026-08-06(Sprint 15) 키 비교 자체를 `hmac.compare_digest`로 타이밍 공격에는 방어했으나, 키가 유출되면 여전히 무방비(role 구분 없음 — 위험 자체는 그대로, 공격 벡터 하나만 줄어듦)
- **[Release Blocking, 2026-08-06 Sprint 16 발견]** `auction_case.case_no` 전국 단일 UNIQUE 제약으로 서로 다른 법원의 동일 사건번호가 병합됨(실측 3건 충돌 확인). Schema 변경(UNIQUE 복합키) + Migration 필요 — 승인 대기, 자세한 내용은 `docs/BUGS.md` #14 · `docs/crawler.md` 알려진 문제점 6번 참고

---

# Success Criteria

Beta v1 출시 기준

- 검색 가능 (완료)
- 상세조회 가능 (완료)
- 로그인 가능 (완료)
- 관심물건 가능 (완료)
- 최근조회 가능 (완료)
- 검색조건 저장 가능 (완료)
- Registry 신청 가능 — **완료** (백엔드+프론트+Admin MVP, 2026-08-05). 단 실제 문서 발급 자동화는 별도(Beta v2 범위)

---

# Out of Scope

다음 기능은 Beta v1 범위가 아니다.

- 투자점수
- AI 추천
- 수익률 계산
- 자동 권리분석 생성
- 자동 투자 의사결정

---

# 진행률 재계산 (2026-08-05, Payment Flow Migration 반영, 코드 기준)

## 도메인별 상태

| 도메인 | 상태 | 근거 |
|---|---|---|
| Search | 완료 | `api/v1/search.py` + `src/app/search/*`, D7 종결물건 기본 필터 포함 |
| Detail | 완료 | `api/v1/item.py` + `src/app/properties/[id]/page.tsx` |
| Favorite | 완료 | `api/v1/favorites.py` + `src/app/favorites/page.tsx` |
| Authentication | 완료 | Supabase Auth + `api/auth.py` JWT 검증 |
| Payment | 진행 중(Flow 준비 완료) | Mock API 완료, `OVERAGE_USAGE`/`SUBSCRIPTION` 금액검증 완료, Provider 인터페이스 분리(Sprint 8) + Interface v2(Sprint 11) + `payments.py`가 실제 PG 흐름과 동일한 순서(`create_order`→`confirm_payment`→`verify_payment`)로 provider를 호출하도록 연결(Sprint 12) 완료. PG사 확정(KG이니시스) + `KGInicisProvider` 클래스 신설(2026-08-07)까지 끝나, 남은 것은 그 6개 메서드의 실제 API 호출 구현뿐 — 흐름 구조 자체는 실연동 준비 완료 |
| Subscription | 진행 중 | 결제 성공 시 자동 생성 완료, 플랜별 가격 서버 검증 완료(Sprint 8). 플랜별 기간 정책은 여전히 미확정(30일 고정은 가정값) |
| Premium | 완료 | `has_active_subscription()`으로 판정, Registry 신청 경로에서 실제 게이트로 사용 중 |
| Registry | **완료 (Release Blocking 해소)** | 신청(프론트 연동) → 무료/초과 판단(백엔드, `BEGIN IMMEDIATE`로 동시성 안전 확보) → 결제 연결(자동) → Admin 상태 관리(MVP) → 실제 문서 다운로드(백엔드+프론트)까지 전체 체인 확인. 5/10/20 스레드 동시 요청 테스트로 무료 한도가 절대 초과되지 않음을 재검증 |
| Admin | 완료(MVP) | `api/v1/admin.py` — 목록조회/필터/상태전이/completed_at/reason/doc_url 전부 Runtime QA 확인. `ADMIN_API_KEY` 미설정으로 현재는 즉시 사용 불가 |

## 전체 진행률(%)

- Beta v1 Success Criteria 7개 항목 기준: **7/7 완료**였으나, 2026-08-06 Sprint 16에서 새 Release Blocking 항목 발견(`auction_case.case_no` 전국 UNIQUE 충돌, 위 Risks/`docs/BUGS.md` #14 참고) — Search/Detail 화면 자체는 지금 당장 안전하지만(잠재적 데이터 오염이 아직 사용자에게 노출되는 필드에 닿지 않음), DB Schema 변경 승인이 있어야 코드로 해결 가능한 상태라 "완전히 알려진 버그 없음"이라고는 더 이상 말할 수 없음(발급기관 자동 연동은 Beta v2 범위로 애초에 제외, 이 항목과는 무관)
- Payment 도메인을 "PG 실연동까지 포함한 완전한 결제 기능" 기준으로 보면: Mock 체인 **100% 동작**(동시성 안전 포함), 금액 검증(구독+초과분) **100% 완료**, Provider 인터페이스 확장(Interface v2) 완료, **`payments.py`가 실제 PG 흐름 순서(주문→승인→검증)로 provider를 호출하도록 연결 완료(Flow Migration)**. PG 실연동 포함 시 **약 92%**(2026-08-07 `KGInicisProvider` 신설로 상승 — 남은 건 그 6개 메서드의 실제 KG이니시스 API 호출 코드 + 환불/Webhook 엔드포인트뿐, 나머지 엔드포인트 구조는 더 손댈 곳이 없음)

## Beta 남은 작업

1. `ADMIN_API_KEY`를 `.env`에 설정 (Admin MVP 자체는 완료, 이 값만 없으면 500)
2. ~~등기부 무료 한도 정책 확정~~ → **2026-08-06 확정**(플랜별 월 단위: 베이직 5회/프로 10회). 남은 것은 **코드 반영**(현재 `FREE_LIMIT=5` 평생 누적)
3. ~~확정 구독 정책 코드 반영~~ → **2026-08-06 완료**(플랜명/가격/연 결제/등기부 월 리셋 전부 반영)
4. ~~PG사 확정~~ → **2026-08-06 KG이니시스 확정**, ~~`KGInicisProvider` 신설~~ → **2026-08-07 완료**. 남은 것은 6개 메서드의 실제 API 호출 구현(외부 API Key/계약 필요, 승인 대기)
5. 환불 엔드포인트(`cancel_payment` 호출부), Webhook 수신 엔드포인트(`handle_webhook` 호출부) 신규 구현 — 이 둘은 여전히 어디서도 호출되지 않음
5. ~~구독 플랜 비교/선택 UI~~ (2026-08-06 완료, Sprint 14), Admin 역할(role) 구분(여전히 미착수)
6. (Beta v2) 등기부등본 실제 발급기관 자동 연동 — 현재는 운영자 수동 배치

## Critical Path

```
[PG사 확정] ✅ 2026-08-06 KG이니시스로 확정 완료 (CTO)
     │
     ▼
[KGInicisProvider 클래스 신설 + PAYMENT_PROVIDER=kginicis 허용값] ✅ 2026-08-07 완료
(6개 메서드는 NotImplementedError 자리 구현. TossProvider/PortOneProvider는 폐기 예정 표기)
     │
     ▼
[KG이니시스 계약 + API Key 발급]  ← 현재 여기 (승인/외부 절차 필요)
     │
     ▼
KGInicisProvider의 Interface v2 6개 메서드를 실제 API 호출로 구현
     │
     ▼
환불(cancel_payment)·Webhook(handle_webhook) 수신 엔드포인트 신규 구현
     │
     ▼
PAYMENT_PROVIDER를 .env에 설정(kginicis)
```

병렬 진행 가능(코드 작업, PG 계약과 무관): **확정 구독 정책 코드 반영** — 플랜명/가격/연 결제/
등기부 월 리셋. 승인만 나면 외부 의존성 없이 즉시 착수 가능해 실질적으로 가장 먼저 처리 가능한 항목.

등기부 무료횟수 레이스 컨디션(Sprint 9에서 발견, Sprint 10에서 수정)이 이 Payment Critical Path에서는
완전히 빠졌다 — Payment 경로만 놓고 보면 남은 것은 PG사 확정 이후의 실연동뿐이다. 단, 2026-08-06
Sprint 16에서 **별개의 새로운 Release Blocking 항목**이 발견됨(위 Risks 참고): `auction_case.case_no`
전국 UNIQUE 충돌 — Search/Detail 자체는 지금 당장 안전하지만(`auction_item.court_name`은 정상),
DB 스키마 변경 승인이 있어야 코드로 고칠 수 있는 상태라 이번 세션에서는 구현하지 않고 발견만 기록함.

`ADMIN_API_KEY` 설정과 등기부 무료 한도 정책 확정은 위 경로와 무관하게 언제든 병행 가능하다
(코드 작업이 거의 없는 운영/정책 결정). 이전 회차의 "프론트 결제 UI + registry-requests 연동",
"Registry-Payment 연결", "Admin MVP", "Registry Download Engine", "Payment Provider 구조 분리"는
모두 완료되어 Critical Path에서 제외됨 — **Beta 출시 관점에서 남은 코드 작업은 "PG사가 확정된
이후" `KGInicisProvider`의 6개 메서드를 실제 API 호출로 구현하는 것뿐이다.** 그 전까지 코드 쪽에서
할 수 있는 준비는 이번 Sprint로 전부 끝났다. 등기부 발급기관 자동 연동은 Beta v2로 이관되어
Beta 출시를 막지 않는다.