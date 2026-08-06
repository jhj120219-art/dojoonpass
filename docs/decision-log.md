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

## PG사 확정 — KG이니시스 (2026-08-06, CTO 확정)

결정

- 결제대행사(PG)는 **KG이니시스**로 확정한다. Toss Payments/PortOne은 후보에서 제외한다.
- 단, 이번 확정은 **의사결정만** 반영한다 — 실제 API 연동 코드는 이 시점에 작성하지 않는다.

이유

- 장기간 "PG사 미확정" 상태가 Critical Path를 막고 있어 CTO가 직접 확정함

영향 (코드 현황 — 2026-08-06 기준, 의도적으로 미착수)

- CTO 지시에 따라 **실제 API 연동·계약·API Key 입력·Webhook 연결·실결제 테스트는 론칭
  직전까지 연기**한다. 현재는 `MockProvider`를 유지하며 Provider 구조만 KG이니시스 기준으로 둔다.
- `api/v1/payment_providers.py`에는 여전히 `TossProvider`/`PortOneProvider` 자리만 있고
  **`KGInicisProvider` 클래스는 존재하지 않는다**. `get_payment_provider()`의 `_PROVIDERS`
  맵도 `mock`/`toss`/`portone` 3개만 인식한다(`PAYMENT_PROVIDER` 환경변수 허용값 동일)
- 즉 "PG사 = KG이니시스"는 현재 **문서상 확정 / 코드 미반영** 상태다. Provider 클래스 신설과
  Interface v2 6개 메서드의 실제 구현은 별도 Sprint(승인 필요 — 외부 API Key/계약 필요)
- `pg_provider` 컬럼은 실연동 전까지 계속 null(MockProvider 동작 그대로)

---

## 구독 정책 확정 — 베이직/프로 2단계 (2026-08-06, CTO 최종 확정)

결정

| 플랜 | 월 요금 | 연 정상가 | 연 판매가 | 등기부등본 |
|---|---|---|---|---|
| 베이직(BASIC) | 12,900원 | 154,800원 | 154,800원(할인 없음) | **월 5회** |
| 프로(PRO) | 22,900원 | 274,800원 | **198,000원(할인 적용)** | **월 10회** |

- 연 정상가는 월 요금 × 12 (베이직 154,800 / 프로 274,800).
- **프로 연간은 이벤트 할인가 198,000원으로 판매**한다(정상가 대비 76,800원 인하).
- 가격은 하드코딩하지 않고 `list_price`(정상가) / `sale_price`(판매가)를 분리해 저장한다 —
  향후 할인 기간(`discount_start`/`discount_end`)이나 `discount_percent` 같은 필드를 붙일 때
  카탈로그만 확장하면 되고 결제/검증 로직은 손대지 않도록 설계한다.

**구현 상태(2026-08-06 반영 완료)**

- `api/v1/payments.py`: `PLAN_CATALOG`(플랜 → 결제주기 → 가격항목) 도입. 가격항목은
  `list_price`/`sale_price`/`discount_percent`/`discount_start`/`discount_end`를 지원하며,
  가격 해석은 `resolve_plan_price()` 단일 진입점에 모아 호출부가 가격 규칙을 알지 못하게 했다.
  할인 우선순위는 `sale_price` > `discount_percent` > `list_price`이고, 지정한 기간을 벗어나면
  자동으로 정상가로 복귀한다 — 이벤트 시작/종료 시 코드 수정이 필요 없다.
- 결제주기: `BILLING_MONTHLY`(30일) / `BILLING_YEARLY`(365일). 요청의 `billing_cycle`이
  없으면 기존 호출과의 호환을 위해 월 결제로 간주한다.
- 등기부 한도: `PLAN_CATALOG[plan]["registry_monthly_limit"]`(베이직 5 / 프로 10)이 단일 기준.

- 등기부 무료 한도는 **월 단위 리셋**으로 확정한다(기존 "평생 누적" 해석은 폐기).
- 한도는 **플랜별로 다르다**(베이직 5회 / 프로 10회) — 단일 상수 정책이 아니다.
- 연 결제를 새로 도입한다(베이직 154,800원 / 프로 198,000원).
- 기존 표기 `BETA_EARLYBIRD`(베타 얼리버드) / `STANDARD`(스탠다드), "평생 9,900원 유지",
  "평생 누적 5회", 그리고 중간 검토 단계에서 거론됐던 9,900원·19,800원·99,000원 안은
  **전부 폐기**하고 위 표로 통일한다.

이유

- 요금제/한도가 문서마다 달라(9,900 vs 12,900 vs 22,900, 평생 vs 월) 정합성이 깨져 있었고,
  Beta 출시 전 과금 기준을 하나로 확정할 필요가 있어 CTO가 직접 결정함

영향 (2026-08-06 코드 반영 완료)

- `api/v1/payments.py`: `VALID_PLANS = ("BASIC", "PRO")`, `PLAN_CATALOG`가 플랜×결제주기별
  `list_price`/`sale_price`를 보유. 서버가 `resolve_plan_price()`로 계산한 금액과 요청 `amount`가
  다르면 결제를 거부한다(기존 검증 방식 유지, 기준값만 카탈로그 기반으로 교체)
- `api/v1/registry.py`: `get_free_count()`가 이번 달 사용분만 COUNT(`used_at >= 이번달 1일`),
  `get_user_free_limit()`이 활성 구독의 plan으로 한도를 조회 — 월 리셋 + 플랜별 차등 동작
- `src/app/properties/[id]/page.tsx`: 월/연 토글 + 플랜 카드(정상가 취소선 + 판매가) UI로 교체,
  `billing_cycle`을 함께 전송
- `storage/migrations/004_create_subscriptions.sql`: `plan`은 CHECK 제약 없는 TEXT라 **스키마
  변경 없이 플랜명 교체 완료**. 다만 기존 `BETA_EARLYBIRD` row의 이관 방침은 여전히 미정
  (현재 운영 DB에 해당 row가 있는지는 별도 확인 필요 — Pending Decisions 참고)

---

## auction_case UNIQUE 키 — (court_code, case_no) 복합키로 확정 (2026-08-06, CTO 확정)

결정

- `auction_case`의 `case_no` 단독 UNIQUE 제약을 **`(court_code, case_no)` 복합 UNIQUE**로
  변경한다(`docs/BUGS.md` #14 Release Blocking의 해결 방향).
- **2026-08-06 Migration 실행 완료** (CTO 승인). `storage/migrations/011_auction_case_court_code_unique.sql`

이유

- 법원마다 사건번호를 독립 채번하므로 전국 단일 UNIQUE는 구조적으로 충돌한다(실측 3건 확인).
  식별자로는 법원 + 사건번호 조합이 유일하게 안전하다.

실행 내역 / 결과 (2026-08-06)

- `auction_case`에 `court_code` 컬럼이 없었으므로 신규 추가했다. SQLite는 기존 테이블의
  UNIQUE 제약을 ALTER로 바꿀 수 없어, 새 테이블 생성 → 데이터 이관 → 교체(표준 재작성 패턴)로 처리
- `court_code` 정본은 크롤러 원본 `auction.court_code`를 그대로 사용. 이 컬럼에는
  `config/courts.py:ALL_COURTS`의 `code`(= 법원명 문자열)가 들어있고 NULL이 0건임을 실측 확인했다
  (`config/settings.py:COURTS`의 `B000210` 형식과 다르지만, 실제 데이터의 정본은 전자다)
- `migrate_execute.py`의 dedup 키와 조회 키도 `(court_code, case_no)`로 함께 변경 — 안 하면
  매일 크롤링이 `court_code=NULL` row를 만들어 재오염된다
- **검증 결과**: 사본 DB 리허설 후 실제 적용. `auction_case` 1,377 → 1,380건(충돌 3건이 법원별로
  정확히 분리), `auction_item` 1,870건 불변, orphan `case_id` 0건,
  **잘못된 법원 연결(court mismatch) 0건 — 원래 버그가 해소됨**. 실행 전 타임스탬프 백업 생성
- 안전장치: `auction.db.backup_before_court_code_20260806_173734`

---

# Pending Decisions

아직 결정되지 않음

- ~~PG사~~ → 2026-08-06 KG이니시스로 확정(위 참고)
- ~~등기부 무료 한도 정책(평생 vs 월)~~ → 2026-08-06 월 단위 + 플랜별 차등으로 확정(위 참고)
- 구독 플랜 변경/해지·환불 정책 (연 결제 도입으로 중도 해지 시 정산 기준 필요)
- 기존 `BETA_EARLYBIRD` 구독 row의 신규 플랜 체계 이관 방침
- 검색 인덱스
- 문서 수집 구조
- 권리분석 고도화
- 운영 배포 구조