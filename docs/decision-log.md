# Decision Log

Status: Active

Owner: Project Management

Last Updated: 2026-08-05

---

# Core Decisions

## Service Name

결정

- 서비스명은 "콕찰" 사용

영향

- Frontend
- Backend
- 문서 전체

---

## Database

결정

- SQLite 유지

이유

- 현재 프로젝트 범위에서 가장 단순하고 안정적

---

## Authentication

결정

- Supabase Auth 사용

이유

- 인증과 경매 데이터를 분리하기 위함

---

## Frontend

결정

- Frontend는 비즈니스 로직을 수행하지 않는다.

이유

- Backend 단일 책임 유지

---

## Search

결정

- 검색은 SQLite 기반

이유

- Beta v1 범위 유지

---

## Routing

결정

- itemId 단일 식별자 사용

이유

- 모든 기능의 기준값 통일

영향

- 검색
- 상세
- 관심물건
- 최근조회
- Registry

---

## API

결정

- 기존 API 응답 구조 유지

이유

- Breaking Change 방지

---

## Mock

결정

- 함수 시그니처 유지

이유

- 실제 API 전환 시 코드 변경 최소화

---

## Premium

결정

- 무료회원은 상세 API 접근 제한 (설계만 완료, `GET /api/v1/item/{id}` 코드에는 미구현 — `docs/search-engine.md` 알려진 문제점 참고)
- Premium은 별도 테이블을 만들지 않는다. `subscriptions`에 ACTIVE + 미만료 row가 있으면 Premium (2026-08-05 확정, `api/v1/registry.py`의 `has_active_subscription()` 그대로 사용)

이유

- 트래픽 절감
- 유료 정책 유지
- 별도 Premium 테이블은 상태 중복을 만들 뿐 이미 subscriptions로 판정 가능

---

## Payment Mock (2026-08-05)

결정

- `POST /api/v1/payments`에 한해 "결제 성공 가정 Mock 로직 백엔드 작성 금지" 결정(`docs/backend.md` 주의사항, 최초 도입 시점)을 예외적으로 대체한다
- 요청 즉시 `payments.status=SUCCESS`로 기록하고, `payment_type=SUBSCRIPTION`이면 `subscriptions` row(ACTIVE, 30일)를 자동 생성한다
- PG(Toss/PortOne 등) 실연동은 포함하지 않는다 — `pg_provider`는 계속 null

이유

- Payment→Subscription→Premium→Registry 체인이 실제로 연결되는지 코드 레벨로 검증하기 위함 (CTO 승인, Sprint 1)
- PG사가 아직 미확정이므로 실연동 없이도 내부 체인만 먼저 완성

영향

- `registry.py`의 `has_active_subscription()`이 실제로 `True`를 반환할 수 있게 됨 (기존에는 subscriptions row가 생성될 방법이 없어 항상 False)
- ~~프론트엔드는 아직 이 API를 호출하지 않음~~ → 2026-08-05 같은 날 후속 Sprint(Registry Frontend 통합)에서 `properties/[id]/page.tsx`가 실제로 호출하도록 연동됨
- PG 실연동 시 `create_mock_payment()`를 PG 콜백 처리로 교체 필요 (구조는 유지 가능)

---

## Admin 인증 (2026-08-05)

결정

- Admin 전용 엔드포인트(`/api/v1/admin/*`)는 Supabase JWT를 쓰지 않고 `X-Admin-Key` 헤더를
  서버 환경변수 `ADMIN_API_KEY`와 단순 비교하는 방식으로 인증한다 (`api/v1/admin.py:require_admin`)
- `registry_requests`에 `reason`(TEXT, nullable) 컬럼을 추가한다(`010_add_registry_request_reason.sql`) —
  FAILED 처리 시 사유를 저장할 곳이 스키마에 없었음

이유

- 프로젝트 전체에 관리자/역할(role) 개념이 전혀 없어(Supabase `auth.users`에도 role 컬럼 없음),
  MVP 단계에서 가장 단순하고 빠르게 구현 가능한 방식을 CTO가 직접 선택함
- `doc_url` 컬럼 재사용(스키마 변경 없음) 대안도 검토했으나, 상태별로 컬럼 의미가 달라지는
  것보다 전용 컬럼을 추가하는 쪽을 CTO가 선택함(스키마 변경 승인)

영향

- Admin 키를 아는 사람은 전원 동일한 전체 권한을 가짐 — 사용자별 권한 구분, 감사 로그 없음
- `ADMIN_API_KEY`가 `.env`에 설정되지 않으면 전체 Admin API가 `500`으로 막힘(운영 전 필수 설정)
- 추후 역할 기반 인증(Supabase custom claim 등)으로 교체 시 `require_admin()` 함수만 교체하면 됨(라우터 핸들러 변경 불필요)

---

## Registry Download Engine (2026-08-05)

결정

- `GET /api/v1/registry-requests/{id}/download`는 자동 등기부 수집 엔진을 만들지 않는다.
  대신 운영자가 실제 등기부등본을 별도 경로(대법원 인터넷등기소 등)로 직접 발급받아
  `registry_documents/`(신규 디렉터리, `.gitignore`)에 파일을 두고, Admin API(`PATCH
  .../admin/registry-requests/{id}`, `status=COMPLETED` + `doc_url` 필수)로 연결하면
  다운로드 엔드포인트가 그 파일을 서빙하는 구조로 구현한다

이유

- 코드 분석 결과(`doc_worker.py`, `crawler/doc_crawler.py`, `document_status`/`document_queue`)
  기존 크롤러 파이프라인은 courtauction.go.kr이 공개하는 STATUS/SPEC/APPRAISAL만 대상으로
  하며, 등기부등본을 수집하는 코드/설정이 전혀 없음 — `doc_crawler.py:collect_document()`는
  `spec`/`status`/`appraisal` 외 타입을 아예 인식하지 못함
- 등기부등본 자동 발급은 대법원 인터넷등기소 등 별도 유료 기관 API와의 실계약/연동이
  필요한 완전히 다른 프로젝트 규모이며, "최소 diff·기존 아키텍처 유지" 원칙과 "추측 금지"
  원칙상 실제 연동 방식을 확인 없이 임의로 만들 수 없음
- `registry_requests` 상태 모델(PENDING/PAYMENT_REQUIRED/PROCESSING/COMPLETED/FAILED)과
  Admin MVP는 이미 운영자가 수동으로 상태를 관리하는 구조로 설계되어 있어, 문서 배치도
  동일하게 운영자 수동 개입으로 자연스럽게 확장됨

영향

- Beta 단계에서 실제 등기부 신청이 들어오면 운영자가 별도로 등기부를 발급받아 파일을
  `registry_documents/`에 넣고 Admin API를 호출해야 함(자동화 아님, 운영 부담 존재)
- 추후 발급기관 API 연동 시 `registry.py`의 download 로직(파일 존재 확인 + FileResponse)은
  그대로 두고, "누가 `doc_url`을 채우는가"만 Admin 수동 입력 → 자동 콜백으로 교체하면 됨

---

## Search Engine

결정

- Offset Pagination 유지

이유

- 현재 구현 유지

---

## Project Scope

결정

다음 기능은 개발하지 않는다.

- 투자점수
- AI 추천
- 수익률 계산
- 자동 투자판단

---

# Development Rules

- Breaking Change 금지
- SQLite 유지
- itemId 유지
- Mock 시그니처 유지
- 기존 API 유지

---

# Pending Decisions

아직 결정되지 않음

- PG사 (Mock 결제로 내부 체인은 검증됨, 2026-08-05 — 실연동 PG사 선정은 여전히 미정)
- 등기부 무료 한도 정책: 코드는 평생 누적 5회, 문서(구독 정책)는 "월 5회"로 표기 — 어느 쪽이 맞는지 미확정
- 검색 인덱스
- 문서 수집 구조
- 권리분석 고도화
- 운영 배포 구조