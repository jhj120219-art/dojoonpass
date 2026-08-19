# Decision Log

Status: Active

Owner: Project Management

Last Updated: 2026-08-07

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
- Premium은 별도 테이블을 만들지 않는다. `subscriptions`에 이용 가능한 row가 있으면 Premium (2026-08-05 확정, `api/v1/registry.py`의 `has_active_subscription()` 그대로 사용).
  **2026-08-07 갱신**: 판정 기준이 `ACTIVE` 단독에서 `ACTIVE + GRACE_PERIOD`(만료 후 3일 유예)로 넓어졌다 — Lifecycle 승인(3번)에 맞춘 것이며, 그 전까지는 유예 정책이 정의만 되고 게이트에는 반영되지 않았다

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
- **2026-08-07 갱신**: `api/v1/payment_providers.py`에 `KGInicisProvider` 클래스를 신설하고
  `get_payment_provider()`의 `_PROVIDERS` 맵/`PAYMENT_PROVIDER` 허용값에 `kginicis`를 추가했다.
  `TossProvider`/`PortOneProvider`는 **폐기 예정 후보**로 명시하고 선택 시 경고 로그를 남긴다
  (삭제는 승인 필요 작업이라 코드는 유지). 알 수 없는 값은 허용값 목록과 함께 `ValueError`
- 단 `KGInicisProvider`의 6개 메서드는 전부 `NotImplementedError`인 **자리 구현**이다 —
  즉 "PG사 = KG이니시스"는 이제 **구조상 반영 완료 / 실연동 미착수** 상태다. 6개 메서드의
  실제 API 호출 구현은 별도 Sprint(승인 필요 — 외부 API Key/계약 필요)
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
  변경 없이 플랜명 교체 완료**. 기존 `BETA_EARLYBIRD` row의 이관 방침은 여전히 미정이지만,
  **"현재 운영 DB에 해당 row가 있는지"는 2026-08-16(Sprint 142) 확인 완료** —
  `SELECT DISTINCT plan FROM subscriptions`가 빈 결과다(BASIC/PRO를 포함해 어떤
  plan 값의 행도 없음). 즉 지금은 이관 대상 자체가 없다 — 이관 **방침**은 여전히
  제품 결정 필요(승인 영역)이지만, 데이터가 실제로 존재할 때까지는 실행 시급성이
  없다는 것을 실측으로 못박는다

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

---

## CTO 승인 6건 (2026-08-07)

### 1. auction 식별 구조 변경 (BUG #18)

결정
- `auction`의 `UNIQUE(case_no, item_no)`를 **`UNIQUE(court_code, case_no, item_no)`** 로 변경
- `auction_item`은 **`UNIQUE(case_id, item_no)`** — court_code를 복제하지 않고 case_id 기반으로
  간다. `case_id`가 가리키는 `auction_case`가 이미 `(court_code, case_no)` 복합키라 법원이
  특정돼 있으므로 동치이면서 정규화 관점에서도 옳다(기존 `auction_case`와 일관성 유지)

이유
- 법원마다 사건번호를 독립 채번하는데 식별키에 법원이 없어, 매일 크롤링이 다른 법원의 물건을
  덮어써 소실시키고 있었다(사본 DB로 재현). `docs/BUGS.md` #18

영향
- `docs/backend.md`가 `auction`을 "크롤러 원본, 변경 금지"로 표기했으나, 그 취지는 하위호환
  보호이고 컬럼 구성은 그대로 유지(제약만 강화)하므로 CTO 승인 하에 예외 적용
- Migration 012/013. id 100% 보존(자식 테이블 11개가 `auction_item.id` 참조)

### 2. Plan API 서버화

결정
- **Backend가 가격/플랜의 단일 Source of Truth**다. `GET /api/v1/plans`가 플랜명·정상가·할인가·
  연간가격·등기부 한도·할인기간을 내려주고, Frontend는 응답만 사용한다(하드코딩 금지)

이유
- 프론트 `PLAN_OPTIONS`가 서버 `PLAN_CATALOG`를 복사해 갖고 있어, 한쪽만 고치면 사용자가 본
  금액으로 결제를 눌렀을 때 서버가 거절하는 상태가 됐다

### 3. ID 체계 Audit

결정
- 전 도메인 id의 FK/JOIN/중복/혼용을 전수 조사한다

결과 (2026-08-07 실측)
- orphan 0 / 논리 불일치 0 / 식별키 중복 0 / 타입 혼용 0
- **`PRAGMA foreign_keys = 0`** — FK가 선언만 되고 강제되지 않음을 발견(P2 등록)

### 4. Admin 권한 2단계

결정
- **SUPER_ADMIN / ADMIN** 2단계. Operator 등급은 두지 않는다
- 등급은 제시된 키로 판정한다(`ADMIN_API_KEY` / `SUPER_ADMIN_API_KEY`)
- 과금에 직접 영향을 주는 조작(등기부 한도 조정)은 SUPER_ADMIN 전용

영향
- 기존 `ADMIN_API_KEY`는 그대로 ADMIN 등급으로 동작 — 하위호환 유지
- 여전히 키 기반이라 **개별 운영자를 특정할 수는 없다**(감사 로그에 등급만 남는다).
  사용자 단위 식별이 필요해지면 Supabase custom claim 기반으로 교체해야 한다

### 5. 결제 로그 구조 선구축

결정
- KG이니시스 실연동은 론칭 직전까지 연기하되 `payment_logs` / `payment_webhooks`의
  Table/Model/Repository/Interface/Mock/테스트/문서는 미리 만든다. **실제 API Key 연결은 안 한다**

영향
- Webhook은 `event_id` UNIQUE로 멱등 처리(PG는 같은 노티를 재전송한다)
- 민감정보는 저장 전 마스킹(`mask_sensitive`)
- ~~수신 엔드포인트는 여전히 없다 — 구조만 준비된 상태~~ → **2026-08-11 Sprint 52
  완료**: `POST /api/v1/payments/webhook/{provider_name}`(`receive_payment_webhook()`)
  로 실제 연결됨. 서명 검증(fail-closed) + `event_id` UNIQUE 멱등 처리 전부 동작 확인,
  `test_api_regression.py` §30이 지속 검증

### 6. registry_credit 구조

결정
- 관리자가 등기부 무료 횟수를 추가/차감/초기화할 수 있게 한다. Admin UI는 없어도 된다
- **잔액 컬럼을 두지 않고 조정 원장으로 관리한다**: 유효 한도 = 플랜 월 한도 + 이번 달 조정 합계

이유
- 잔액 컬럼은 `registry_usage` 기반 사용량 계산과 상태가 이중화되어 반드시 어긋난다.
  Premium 판정에서 별도 테이블을 거부한 것과 같은 근거(위 "Premium" 항목 참고)
- 원장은 조정 이력이 그대로 감사 기록이 되고, 월 리셋 정책과 경계가 자동으로 일치한다

### 보류 (진행하지 않음)

Sentry / Rate Limit / ~~Selenium~~ / Monitoring / Analytics / OCR / 지도 API / SNS API /
Storage 확장 / 외부 서비스 연동 / 패키지 설치

**2026-08-16 정정(Sprint 142, Documentation Drift Audit)**: Selenium은 이 목록에
있던 2026-08-07 이후 **2026-08-12 Sprint 61에 실제로 설치·승인됐다**
(`requirements.txt`, `pip install -r requirements.txt`로 selenium/webdriver-manager/
pandas/pdfplumber 확보 — 크롤러/문서수집 파이프라인의 핵심 의존성이라 대상에서
빠질 수 없었다). 나머지(Sentry/Rate Limit/Monitoring 등)는 여전히 보류 상태
유지(재확인 완료, `docs/roadmap.md` "기술부채" 절과 일치).


---

## CTO 추가 승인 10건 (2026-08-07, Sprint 28)

### 1. SQLite FK 런타임 강제
- 모든 DB 커넥션에 `PRAGMA foreign_keys = ON`. 마이그레이션만 예외(테이블 재작성 패턴이
  중간에 자식 행을 고아로 만들기 때문)
- 이유: `REFERENCES` 15개를 선언해 두고도 SQLite 기본값(OFF) 때문에 전부 무시되고 있었다

### 2. Payment State Machine
- `CREATED/READY/REQUESTED/PAID/FAILED/EXPIRED/CANCELLED/PARTIAL_REFUND/REFUNDED`
- **레거시 `SUCCESS`는 제거하지 않는다** — 기존 `payments` 행과 `MockProvider`가 쓰고 있어
  없애면 데이터 해석이 불가해진다. `PAID`와 동의어로 두고 `is_paid()`가 둘 다 인정한다
- 허용 전이만 선언하고 나머지는 거부. 기존 흐름(Mock 즉시 SUCCESS)에는 개입하지 않는다

### 3. Subscription Lifecycle
- `ACTIVE/GRACE_PERIOD/PAUSED/EXPIRED/CANCELLED`, 유예 기간 3일
- **자동 만료를 배치에 의존하지 않는다** — 상시 스케줄러가 크롤링 배치뿐이라 거기 얹으면
  "배치가 안 돌아서 만료가 안 됨"이 곧 과금 사고가 된다. 조회 시점 lazy sync로 처리
- 무료 등기부 초기화는 별도 작업 불요(월 경계 계산이 이미 그 역할을 한다)

### 4. registry_credit_logs
- `registry_credits`(한도 계산 반영분)와 **별도**로 무료 횟수가 움직인 모든 사건을 추적
- 사용(USAGE)은 로그에만 남기고 한도 계산에는 넣지 않는다 — `registry_usage`가 이미
  세고 있어 넣으면 이중 차감

### 5. audit_logs
- `admin_id/action/target_type/target_id/before/after/created_at`
- `before`/`after`는 **바뀐 필드만** 담는다. 업무 트랜잭션과 같은 커밋에 넣는다

### 6. Soft Delete
- **실제 DELETE가 있는 테이블에만** 적용: `favorites`, `search_presets`
- 이번 범위는 컬럼 추가까지. 전환은 `UNIQUE(user_id,item_id)` 재등록 문제를 먼저 풀어야 한다

### 7. Admin REST 구조
- `/admin/users|payments|subscriptions|registry|audit-logs` 신설
- **기존 경로는 유지**한다(`/admin/registry-requests`, `/admin/registry-credits`) —
  운영 문서·테스트가 참조 중이라 폐기는 Breaking Change
- `/admin/users`는 users 테이블이 없으므로(인증은 Supabase) 활동 있는 user_id 집계로 제공

### 8. API Response 표준화
- `{success, data, error, meta, message}` — `error`/`meta` **추가**
- **`message`는 유지**(프론트가 읽고 있음). Admin의 `HTTPException` 기반 실패는
  클라이언트가 `status_code`로 분기 중이라 **Skip**(Spec 결정 사항)

### 9. Error Code 표준화
- 9개 도메인 40개 코드, `docs/ERROR_CODES.md`
- 클라이언트는 문구가 아니라 코드로 분기한다. 코드 값은 배포 후 바꾸지 않는다

### 10. Enum / Constant 통합
- `api/constants.py`에 13개 Enum. `str, Enum` 상속이라 문자열처럼 동작한다
- **문자열 값은 지금 DB에 있는 값 그대로** — 정의 위치만 모았고 값은 바꾸지 않았다

### 보류 (진행하지 않음)
KG이니시스 실연동 / API Key 입력 / Webhook 실서버 / Sentry / Analytics / OCR / Monitoring /
Rate Limit / 외부 서비스 / 패키지 설치 / Docker / OS 변경 / GitHub 설정 변경

---

## 큐의 매각기일 사본을 신뢰하지 않는다 (2026-08-17, Sprint 145)

결정

- `doc_worker`의 2차 방어선(기일 경과 종결)은 `document_queue.auction_date`(사본)가
  아니라 **`auction_item.auction_date`(권위 있는 값)**를 기준으로 판단한다.
- 사본과 원본이 어긋나면 큐 행의 `auction_date`/`priority`를 함께 정정한다.
- 다만 이미 종결된 행(`done`/`failed`/`SKIPPED_EXPIRED`)의 `status`는 **되살리지 않는다.**

이유

- 사본은 06:00 적재 시점의 값이라, 유찰 후 재매각으로 기일이 미래로 다시 잡히면
  옛 날짜가 남는다. 그 상태로 종결하면 **살아 있는 사건의 문서가 영구히 수집되지 않는다**
  (`SKIPPED_EXPIRED`는 `reset_stale_queue()`의 부활 대상이 아니다).
- 실측 2026-08-17: 드리프트 36행, 그중 해로운 것 3행 — item 1533은 **당시 기본 검색에
  뜨는 9건 중 하나**였다. 즉 사용자가 보는 물건의 문서가 무기한 "수집중"으로 남는다.
- Sprint 74가 `enqueue_documents()`에 같은 취지의 갱신을 넣었지만 **06:00 크롤이 돌 때만**
  동작한다. 크롤과 크롤 사이의 구멍은 worker 쪽에서 막아야 한다.

바꾸지 않은 것

- **수집 정책 자체는 그대로다** — "기일 지난 사건은 수집하지 않는다"는 유지하고,
  그 판단이 참조하는 값의 출처만 바꿨다. Sprint 74의 표현을 그대로 따른다:
  *"여기서 고치는 것은 큐가 자기 필드에 사실과 다른 값을 들고 있는 것뿐이다."*
- 종결된 행의 부활(재수집)은 **제품 판단**이라 이 결정에 포함하지 않는다.

---

## 종결된 큐 행을 되살린다 — 단, 법원이 실제로 바꿨을 때만 (2026-08-18, Sprint 189)

결정

- Sprint 145가 "제품 판단"으로 미뤄 둔 **종결 행의 부활(재수집)** 을 도입한다.
  기준은 **법원 원천이 실제로 바뀌었는가** 하나다 — 주기적 전면 재수집이 아니다.
- 새 컬럼을 만들지 않는다. `document_queue.status`의 **값**을 늘린다
  (`refresh` / `in_progress_refresh`). TEXT + CHECK 제약이 없으므로 값 추가는
  스키마 변경이 아니고, 따라서 승인 영역이 아니다.
- 무엇이 바뀌면 무엇을 다시 받는지는 `REFRESH_DOC_TYPES_BY_FIELD` **하나**가 정한다.

이유

- "한 번 수집하면 끝"은 경매 데이터에서 곧 오답이다. 유찰 -> 재매각은 일상이고,
  그때 기일·최저가와 함께 **매각물건명세서가 새로 게시된다.** 최초 수집분을 계속
  보여 주는 것은 화면이 사실과 다른 것을 말하는 것이다.
- 전면 재수집은 실측 약 1.9시간, 표적 재수집은 84초다(roadmap 재수집 정책).
  "바뀐 물건의, 그 변경이 실제로 영향을 주는 자산만"이 유일하게 매일 감당 가능한 범위다.
- 기계는 이미 다 있었다 — 수집기의 `overwrite`, 해시 비교, `document_version_log`,
  부분수집 보호. **트리거만 없었다.**

명시적으로 정한 경계

- **사진은 기일/최저가 변동으로 다시 받지 않는다.** 사진은 감정 시점의 것이라
  유찰로 값만 내려갈 때는 바뀌지 않는다. 넣으면 매일 수천 장을 이유 없이 다시 받는다.
  감정가가 바뀌었을 때(=재감정)만 사진을 함께 받는다.
- **기일이 이미 지난 물건은 되돌리지 않는다.** 되돌려도 워커의 2차 방어선에 걸려
  곧바로 `SKIPPED_EXPIRED`가 되므로, 아무것도 못 받은 채 **성공 기록만 잃는다.**
- **`SKIPPED_UNSUPPORTED`는 절대 되살리지 않는다.** `mark_queue_unsupported()`가 끊은
  "성공할 수 없는 항목의 무한 재시도" 고리를 다시 이으면 안 된다.
- **`in_progress` 계열은 건드리지 않는다.** 워커가 소유 중인 행을 뺏으면 그 실행이
  끝나며 `done`으로 덮어써 재수집 의도가 사라진다.
- **정렬 순서는 바꾸지 않는다.** `priority`는 기일 임박도에서 나온 제품의 중요도다.
  재수집을 앞세우면 **한 번도 수집된 적 없는 임박 물건**이 뒤로 밀린다.
  총량은 `REFRESH_MAX_ITEMS_PER_RUN`으로 따로 제한한다.
- **이미 가진 것을 실패로 덮지 않는다.** 재수집이 최종 실패해도 화면 상태가
  `READY`/`NO_IMAGE`면 유지한다. 아니면 "화면은 수집실패인데 파일은 200"이 된다
  (BUGS #122). 큐 행은 `failed`로 남아 실패 사실 자체는 유실되지 않는다.

되돌리는 법

- `DOJOONPASS_REFRESH_ON_CHANGE=0` — 관측은 계속하고 예약만 멈춘다. 코드 수정 불필요.

---

## 2026-08-19 (Sprint 217) — 스킵 경로도 실체를 기록한다 / 잃는 이력 한 행은 그냥 잃는다

### 정한 것 1 — `"이미 존재. 스킵"` 이 `files_saved` 를 채운다

**무엇이 바뀌나**: 수집기가 "이미 있다"로 건너뛸 때, 결과에 **이미 갖고 있는 파일 경로**를
담는다. 파일은 여전히 다시 쓰지 않는다.

**왜**: 빈 목록이 `_record_doc_raw()` 를 맨 앞에서 반환시켜, 파일은 있는데 `doc_raw` 가
없는 상태가 **영구로** 굳었다(BUGS #144). 다음 수집도 같은 분기를 타므로 스스로 회복되는
길이 없었다. 사진 쪽은 같은 자리를 처음부터 복구하고 있었다(`_describe_existing()`).

**바꾸지 않은 것**: 재다운로드 여부, 부분 성공 계약, 개정 판정. `previous_hash`/`new_hash`
는 그대로 비워 두므로 `document_version_log` 에 거짓 개정이 생기지 않는다.

### 정한 것 2 — `document_version_log` 한 행의 유실은 고치지 않는다

**상황**: 큐 성공기록이 실패한 뒤 재시도하면, 디스크가 이미 새 바이트라 수집기가 재는
`previous_hash` 가 `new_hash` 와 같아져 개정 이력이 남지 않는다(실측 확인).

**정한 것**: **고치지 않는다.** 근거 셋 —
1. 바뀌었다는 사실 자체는 `doc_raw` 가 v1->v2 로 지킨다(실측).
2. `document_version_log` 는 이 저장소에 **제품 독자가 없다**(쓰는 곳 1, 읽는 곳은
   일회성 리포트뿐).
3. 되살리려면 **수집 전에** 지문을 큐에 적어야 한다 — 사용자 영향 0인 이력 한 행을
   위해 큐 구조를 바꾸는 것은 값이 맞지 않는다.

**대신**: `test_asset_pipeline.py` 12-K 가 이 상태를 **명시적으로 고정**한다.
그 테이블에 독자가 생기는 날 이 단언이 먼저 깨지고, 그때 다시 결정하게 된다.

### 정한 것 3 — 잠금은 커널에 맡긴다 (BUGS #145)

`RunLock` 이 `exists()` 로 보고 `open("w")` 로 쓰는 구조라 **동시 시작을 하나도 막지
못했다**(8스레드 x 200라운드 전부 8개 성공). `O_CREAT|O_EXCL` 로 바꾸고, 오래된 락
회수는 **배타 토큰으로 한 번에 하나만** 들어가게 했다.

중간 시도 둘(`os.remove` 재확인 추가 / `os.rename` 중재)이 측정에서 실패한 기록을
`docs/BUGS.md` #145 에 그대로 남긴다 — "나아졌겠지"가 그대로 틀렸던 사례라
지우면 다음 사람이 같은 길을 간다.



## 2026-08-19 (Sprint 223)

### 정한 것 1 — 픽셀을 바꾸지 않는 접근성 결함은 제품 결정이 아니다

색·크기·간격은 디자인이라 손대지 않는다. 그러나 **포커스가 어디로 가는가**,
**바뀐 화면이 읽히는가**, **본문으로 건너뛸 수 있는가**는 디자인이 아니라 **동작**이다.
렌더 결과가 한 픽셀도 달라지지 않는지 실측으로 확인한 뒤 고쳤다(BUGS #151·#152·#153).

같은 기준으로, 고정 px 글자 8곳을 **16px 기준 정확히 같은 크기의 rem** 으로 바꾼 것도
제품 결정이 아니라고 판단했다 — 기본 설정에서 픽셀이 동일하고, 달라지는 것은
**사용자가 글꼴을 키웠을 때뿐**이다. 그 경우 커지는 쪽이 의도된 동작이다.

### 정한 것 2 — 트랩은 Tab 만 막지 않는다

포커스 트랩을 Tab 가로채기만으로 만들면 마우스로 배경 컨트롤을 눌러 새는 경로가 남는다.
`focusin` 감시를 함께 둔다. 대신 **복귀보다 먼저 해제**해야 한다 —
순서가 바뀌면 자기 감시기가 복귀 포커스를 다시 모달 안으로 끌고 들어온다(가드가 잠근다).

### 정한 것 3 — 검색 결과 알림은 "항상 존재하는 한 줄"로 한다

결과 목록 자체에 `aria-live` 를 다는 쪽이 자연스러워 보이지만, **0건일 때 그 문단이
통째로 사라져** 정작 알려야 할 순간에 아무것도 알리지 못한다.
`sr-only` 한 줄을 **무조건 렌더**하고 글자만 바꾼다. 소프트 전환 후에도 같은 DOM 노드가
유지되는 것을 실측으로 확인한 뒤 채택했다.

### 정한 것 4 — 스테일 worktree 는 지우지 않고 검사 범위에서만 뺀다

`.claude/worktrees/sprint95-...` 는 옛 커밋의 저장소 통째 사본이고,
검사 도구가 그것까지 훑고 있었다(스캔의 34%). **삭제는 승인 영역**이라 하지 않고,
검사 범위에서만 제외했다. 지우는 판단은 그 worktree 의 쓸모를 아는 사람이 해야 한다.
