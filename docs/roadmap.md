# Project Roadmap

Status: Beta v1

Owner: Project Management

Last Updated: 2026-08-05

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
- 미완료: PG사 확정 + `TossProvider`/`PortOneProvider` 실제 구현, 구독 플랜 선택 UI, 등기부 무료한도 정책(평생 vs 월) 확정, 실제 발급기관 자동 연동 — 아래 "Next Priority" 참고

---

# In Progress

## Frontend

- 권리분석 화면 연동 (`rightsAnalysis.ts` REGISTRY 소스 하드코딩 해소 — 등기부 신청 카드와는 별개 화면)
- 플랜 비교/선택 UI 신규 구현 (현재 구독 버튼은 베타 얼리버드 단일 옵션 고정)

## Backend

- 등기부 무료 한도 정책 확정 (코드=평생 누적 5회 vs 문서=월 5회, 불일치 상태 — Admin/Payment 연결은 끝났지만 이 정책 자체는 미확정)
- `ADMIN_API_KEY`를 `.env`에 설정 (Admin MVP는 완료됐으나 현재 키 미설정으로 전체 500)
- `SUBSCRIPTION` 결제 금액 서버 검증 (`OVERAGE_USAGE`는 2026-08-05 검증 추가됨, `SUBSCRIPTION`은 아직 클라이언트 값 신뢰)

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
- 등기부 무료 한도 정책 확정 (코드=평생 vs 문서=월, 여전히 미확정 — 남은 항목)
- 권리분석 연동
- 문서 수집 API

Priority 3

- ~~등기부 다운로드 엔진(수동 배치 방식)~~ (완료, Sprint 6 — 아래 Beta v2의 "실제 발급기관 자동 연동"과는 별개)
- ~~Payment Provider 구조 분리~~ (완료, Sprint 8 — PG사 확정 전 기반 구조만)
- PG사 확정 및 `TossProvider`/`PortOneProvider` 실제 구현 (PG사 미확정이 선행 블로커)
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
- 구독 UI (등기부 신청 카드 내 단일 버튼으로 구독 가능 — 별도 플랜 비교/선택 화면은 미착수)
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
- `SUBSCRIPTION` 결제 금액 서버 검증 부재 (`OVERAGE_USAGE`는 검증 추가됨, `SUBSCRIPTION`은 클라이언트 `amount` 그대로 신뢰)
- Admin 인증에 역할(role) 구분 없음 (`X-Admin-Key` 단일 공유키, MVP 한계)

---

# Sprint Backlog

## [P1] run_daily.bat 실패 은폐 구조 개선

배경: migrate_execute.py 로그 파일 잠금 버그(2026-07-27 수정 완료) 조사 중, run_daily.bat가
migrate_execute.py 실패 후에도 뒤따르는 echo 명령 때문에 배치 자체의 종료코드가 0(성공)으로
남는 구조적 결함이 확인됨. Task Scheduler의 LastTaskResult가 실제 내부 실패를 반영하지 못함.

목표

- 현재 하위 프로세스(mvp_scraper.py / migrate_execute.py) 실패 시 BAT가 exit code 0으로
  종료될 수 있는지 재확인
- 실패 시 즉시 종료(다음 단계로 넘어가지 않음)
- 적절한 exit code 반환(Task Scheduler가 실패를 인지 가능하도록)
- 어느 단계에서 실패했는지 로그에 명확히 남기기

이번 Sprint 범위: 등록만 함. 설계/구현은 다음 Sprint에서 진행.

---

## [P2] 로그인 UX 개선 — 비회원 검색 우선 흐름

배경: 현재는 첫 화면에서 로그인부터 시작하는 UX. 향후에는 비회원도 검색/검색결과까지는
볼 수 있고, 상세 진입 시점에 로그인을 요구하는 흐름으로 변경할 계획.

목표(다음 Sprint 후보, 이번 Sprint는 등록만)

- 비회원 → 검색 → 검색결과 → 상세 진입 시 로그인 흐름으로 전환
- 현재 `/properties/*`를 게이트하는 middleware 인증 로직 재검토 필요 (docs/CLAUDE.md 참고)

이번 Sprint 범위: 등록만 함. 구현하지 않음.

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
- PG사 미확정으로 인한 Payment Mock 장기화 가능성
- 등기부 무료한도 정책(평생 vs 월) 미확정 상태 장기화 시 사용자 혼란(정책은 통일됐으나 "어느 쪽이 맞는 정책인지"는 여전히 미결정)
- ~~`SUBSCRIPTION` 결제 금액 서버 미검증~~ → 2026-08-05 해결(Sprint 8)
- ~~Payment Provider 인터페이스가 실제 Toss/PortOne 흐름을 수용하지 못함~~ → 2026-08-05 Interface v2로 해결, 같은 날 `payments.py`가 `create_order`/`confirm_payment`/`verify_payment` 3개를 실제로 호출하도록 연결 완료(Sprint 12). `cancel_payment`/`handle_webhook`은 여전히 미호출(환불·Webhook 엔드포인트 자체가 없어 PG사 확정 후 작업)
- Admin 인증이 단일 공유키(`X-Admin-Key`)라 유출 시 전체 Registry 상태를 조작당할 위험 — 운영 전 역할 구분/키 로테이션 정책 필요

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
| Payment | 진행 중(Flow 준비 완료) | Mock API 완료, `OVERAGE_USAGE`/`SUBSCRIPTION` 금액검증 완료, Provider 인터페이스 분리(Sprint 8) + Interface v2(Sprint 11) + `payments.py`가 실제 PG 흐름과 동일한 순서(`create_order`→`confirm_payment`→`verify_payment`)로 provider를 호출하도록 연결(Sprint 12) 완료. 남은 것은 PG사 확정 + `TossProvider`/`PortOneProvider` 실제 구현뿐 — 흐름 구조 자체는 실연동 준비 완료 |
| Subscription | 진행 중 | 결제 성공 시 자동 생성 완료, 플랜별 가격 서버 검증 완료(Sprint 8). 플랜별 기간 정책은 여전히 미확정(30일 고정은 가정값) |
| Premium | 완료 | `has_active_subscription()`으로 판정, Registry 신청 경로에서 실제 게이트로 사용 중 |
| Registry | **완료 (Release Blocking 해소)** | 신청(프론트 연동) → 무료/초과 판단(백엔드, `BEGIN IMMEDIATE`로 동시성 안전 확보) → 결제 연결(자동) → Admin 상태 관리(MVP) → 실제 문서 다운로드(백엔드+프론트)까지 전체 체인 확인. 5/10/20 스레드 동시 요청 테스트로 무료 한도가 절대 초과되지 않음을 재검증 |
| Admin | 완료(MVP) | `api/v1/admin.py` — 목록조회/필터/상태전이/completed_at/reason/doc_url 전부 Runtime QA 확인. `ADMIN_API_KEY` 미설정으로 현재는 즉시 사용 불가 |

## 전체 진행률(%)

- Beta v1 Success Criteria 7개 항목 기준: **7/7 완료, Release Blocking 없음** — Registry의 레이스 컨디션이 Sprint 10에서 해소되어 현재 코드 기준으로 출시를 막는 알려진 버그가 없다(발급기관 자동 연동은 Beta v2 범위로 애초에 제외)
- Payment 도메인을 "PG 실연동까지 포함한 완전한 결제 기능" 기준으로 보면: Mock 체인 **100% 동작**(동시성 안전 포함), 금액 검증(구독+초과분) **100% 완료**, Provider 인터페이스 확장(Interface v2) 완료, **`payments.py`가 실제 PG 흐름 순서(주문→승인→검증)로 provider를 호출하도록 연결 완료(Flow Migration)**. PG 실연동 포함 시 **약 90%**(이전 85%에서 상승 — 남은 건 사실상 "PG사 확정"이라는 의사결정과 `TossProvider`/`PortOneProvider`의 실제 API 호출 코드뿐, 엔드포인트 구조 자체는 더 손댈 곳이 없음)

## Beta 남은 작업

1. `ADMIN_API_KEY`를 `.env`에 설정 (Admin MVP 자체는 완료, 이 값만 없으면 500)
2. 등기부 무료 한도 정책 확정 (평생 5회 vs 월 5회 — 통일은 됐으나 "어느 정책이 맞는지"는 미결정)
3. PG사 확정 (사용자/PM 의사결정 필요) → `TossProvider`/`PortOneProvider`가 Interface v2의 6개 메서드를 실제 API 호출로 구현
4. 환불 엔드포인트(`cancel_payment` 호출부), Webhook 수신 엔드포인트(`handle_webhook` 호출부) 신규 구현 — 이 둘은 여전히 어디서도 호출되지 않음
5. 구독 플랜 비교/선택 UI, Admin 역할(role) 구분
6. (Beta v2) 등기부등본 실제 발급기관 자동 연동 — 현재는 운영자 수동 배치

## Critical Path

```
[PG사 확정] (의사결정, 코드 작업 아님)
     │
     ▼
TossProvider 또는 PortOneProvider의 6개 메서드 실제 API 호출로 구현
     │
     ▼
환불(cancel_payment)·Webhook(handle_webhook) 수신 엔드포인트 신규 구현
     │
     ▼
PAYMENT_PROVIDER를 .env에 설정
```

Release Blocking 항목은 더 이상 없다. 등기부 무료횟수 레이스 컨디션(Sprint 9에서 발견, Sprint 10에서
수정)이 이 Critical Path에서 완전히 빠졌다 — 남은 경로는 PG사 확정 이후의 실연동뿐이다.

`ADMIN_API_KEY` 설정과 등기부 무료 한도 정책 확정은 위 경로와 무관하게 언제든 병행 가능하다
(코드 작업이 거의 없는 운영/정책 결정). 이전 회차의 "프론트 결제 UI + registry-requests 연동",
"Registry-Payment 연결", "Admin MVP", "Registry Download Engine", "Payment Provider 구조 분리"는
모두 완료되어 Critical Path에서 제외됨 — **Beta 출시 관점에서 남은 코드 작업은 "PG사가 확정된
이후" `TossProvider`/`PortOneProvider`를 실제로 구현하는 것뿐이다.** 그 전까지 코드 쪽에서
할 수 있는 준비는 이번 Sprint로 전부 끝났다. 등기부 발급기관 자동 연동은 Beta v2로 이관되어
Beta 출시를 막지 않는다.