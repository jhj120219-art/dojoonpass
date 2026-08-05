# Backend Overview

## 목적
전국 법원경매 데이터 수집·저장·검색·권리분석 API 제공.
의사결정 기준: 투자자가 실제 돈을 내는 기능인지 여부.

---

## 현재 Backend 구조

dojoonpass/
api_server.py
mvp_scraper.py
collect_documents.py
migrate_execute.py
run_daily.bat
.env
api/
auth.py
v1/
search.py
item.py
favorites.py
recent_items.py
search_presets.py
registry.py
documents.py
payments.py
payment_providers.py
admin.py
doc_stats.py
storage/
database.py
migrate_v4_1.py
migrate_doc_collect.py
migrations/
001_create_favorites.sql
002_create_recent_items.sql
003_create_search_presets.sql
004_create_subscriptions.sql
005_create_registry_usage.sql
006_create_payments.sql
007_create_registry_requests.sql
008_create_search_indexes.sql
009_add_default_sort_index.sql
010_add_registry_request_reason.sql
run_migrations.py
crawler/
court_crawler.py
doc_crawler.py
models/
auction_item.py
config/
settings.py
courts.py
logs/
daily_run.log
migrate_execute.log
doc_collect.log
docs/
backend.md


---

## FastAPI 구조

- 진입점: `api_server.py`
- 실행: `python api_server.py`
- 포트: 8000
- host: 0.0.0.0
- Swagger: `http://localhost:8000/docs`
- CORS: 전체 허용 (개발 환경)
- 라우터 prefix: `/api/v1`
- 서비스 레이어: 없음 (라우터에 직접 구현)
- 레포지토리 레이어: 없음 (라우터에서 직접 SQLite 쿼리)

---

## API 구조

### 인증 불필요
| 메서드 | 경로 | 비고 |
|--------|------|------|
| GET | / | 헬스체크 |
| GET | /api/v1/stats | 관리자용, 프론트 연동 없음 |
| GET | /api/v1/document-stats | 관리자용, 프론트 연동 없음 |
| GET | /api/v1/search | 검색 |
| GET | /api/v1/item/{item_id} | JWT 있으면 최근조회 자동 기록. Premium 접근제어 없음(설계만, 미구현) |
| GET/HEAD | /api/v1/item/{item_id}/documents/{doc_type} | 문서 실파일(PDF/HTML) 서빙. 인증/Premium 게이트 없음 |

### 인증 필요 (Supabase JWT)
| 메서드 | 경로 |
|--------|------|
| GET/POST/DELETE | /api/v1/favorites, /api/v1/favorites/{item_id} |
| GET | /api/v1/recent-items |
| GET/POST/DELETE | /api/v1/search-presets, /api/v1/search-presets/{id} |
| POST/GET | /api/v1/registry-requests |
| GET | /api/v1/registry-requests/{id} |
| GET | /api/v1/registry-requests/{id}/download |
| POST/GET | /api/v1/payments |
| GET | /api/v1/payments/{id} |

### Admin 전용 (Supabase JWT 아님 — `X-Admin-Key` 헤더, 2026-08-05 추가)
| 메서드 | 경로 | 비고 |
|--------|------|------|
| GET | /api/v1/admin/registry-requests | 목록 조회. `status`/`user_id`/`item_id`/`case_no`/`page`/`size` 필터 |
| PATCH | /api/v1/admin/registry-requests/{id} | 상태 전이. 허용: PENDING→(PROCESSING,FAILED), PROCESSING→(COMPLETED,FAILED) |

- 인증 방식이 다른 모든 API와 다르다: Supabase JWT를 쓰지 않고 `X-Admin-Key` 헤더를 서버 환경변수 `ADMIN_API_KEY`와 단순 비교한다(`api/v1/admin.py:require_admin`). 역할(role) 개념이 프로젝트 어디에도 없어 MVP로 도입한 임시 인증이며, 사용자별 권한 구분은 없다(키를 아는 사람은 전체 관리자 권한).
- `ADMIN_API_KEY`가 `.env`에 설정되어 있지 않으면 요청 자체가 `500 "관리자 키 미설정"`으로 막힌다 — 아직 `.env`에 값이 없다(운영 전 사용자가 직접 설정 필요, DB/env 변경 승인 정책상 임의로 넣지 않음).
- `COMPLETED` 전이 시 `completed_at` 자동 기록, `FAILED` 전이 시 `reason`(필수) 저장 — `registry_requests.reason` 컬럼은 `010_add_registry_request_reason.sql`로 신규 추가됨.
- `PAYMENT_REQUIRED`는 관리자가 직접 전이시킬 수 없다 — `POST /api/v1/payments`(OVERAGE_USAGE)가 성공할 때만 `PENDING`으로 자동 전환된다.

### GET /api/v1/search 파라미터
sido, sigungu, property_type, court_name,
auction_date_from, auction_date_to,
min_appraisal, max_appraisal,
min_bid_rate, max_bid_rate,
min_fail_count, max_fail_count,
page(기본 1), size(기본 20, 최대 100)

자유텍스트 주소 검색 미지원.

### 공통 응답 형식 (인증 필요 API 전용)
```json
{"success": true, "data": {...}, "message": null}
{"success": false, "data": null, "message": "오류 내용"}
```

인증 불필요 API(search, item)는 공통 형식 미적용.

---

## Business Logic

### auction → auction_item 동기화
- 설계 이유: mvp_scraper.py는 auction에만 저장. 검색 API는 auction_item 사용. 동기화 누락 방지를 위해 run_daily.bat에 migrate_execute.py 추가.
- 방식: SELECT * FROM auction 전체 대상, INSERT OR IGNORE
- 실행 시간: 0.17초

### 유찰횟수 추출
auction.status 문자열 정규식 추출. "유찰 11회" → fail_count=11

### 최저가율
bid_rate = minimum_bid_price / appraisal_price

### 최근조회 자동 기록
GET /api/v1/item/{item_id} 호출 시 JWT가 있으면 recent_items 자동 기록.
동일 물건 재조회 시 viewed_at 갱신.
JWT 없으면 기록 안 함 (에러 없음).

### 등기부 무료 횟수
평생 누적 5회 무료(월 단위 리셋 로직 없음, 코드 기준 `api/v1/registry.py:get_free_count`). 초과 시 건당 1,000원.
차감 시점: 신청 시점.
판단 기준: registry_usage WHERE user_id=? AND is_free=1 COUNT (기간 조건 없음).
`FREE_LIMIT`(=5) 초과 시 `registry_requests`에 `PAYMENT_REQUIRED` row 생성. 2026-08-05부터 `POST /api/v1/payments`(OVERAGE_USAGE)가 성공하면 가장 오래된 미결제 `PAYMENT_REQUIRED` 건을 찾아 `payment_id` 연결 + `status=PENDING`으로 자동 전환됨(아래 "결제(Payment)..." 참고) — 더 이상 미구현 아님.
무료횟수 COUNT와 등록은 원자적 트랜잭션(`BEGIN IMMEDIATE`)으로 묶여 있어 동시 요청에도 5회를 초과할 수 없다(2026-08-05 Release Blocking 수정, 아래 "알려진 문제점" 참고).

### 구독 정책
- 베타 얼리버드: 9,900원/월
- 정가: 22,900원/월
- 얼리버드 가입자 평생 9,900원 유지 (정책 확정)
- 위 금액은 정책 문서 기준이며, `POST /api/v1/payments`는 서버에서 플랜별 가격을 검증하지 않고 클라이언트가 보낸 `amount`를 그대로 저장함 (알려진 문제점 참고)
- 구독 기간(`expires_at`)은 `SUBSCRIPTION_PERIOD_DAYS=30`(코드 상수, `api/v1/payments.py`)로 임시 고정. 플랜별 차등 기간 정책 미확정

### Payment Provider 구조 (2026-08-05, PG 실연동 준비)
- `api/v1/payment_providers.py`(신규): `PaymentProvider`(인터페이스) → `MockProvider`(현재 사용, 항상 SUCCESS) / `TossProvider`·`PortOneProvider`(자리만 있음, `charge()` 호출 시 `NotImplementedError` — PG사 미확정이라 실제 승인 로직 없음)
- `get_payment_provider()`가 환경변수 `PAYMENT_PROVIDER`(mock/toss/portone, 기본값 `mock`)로 어떤 Provider를 쓸지 결정. `.env`에 값이 없어도 기존과 동일하게 `mock`으로 동작(하위호환)
- `payments.py`의 `create_payment_record()`가 `provider`의 결과(`status`/`pg_provider`/`pg_transaction_id`)를 그대로 `payments` row에 기록만 함 — router는 여전히 SQLite에 직접 쓰고, provider는 "결제 승인 여부"만 결정하는 좁은 역할(서비스/레포지토리 계층 아님). 2026-08-05부터 `charge()` 단일 호출 대신 `create_order()`→`confirm_payment()`→`verify_payment()` 순서로 호출(아래 "Payment Flow Migration" 참고)
- `status != "SUCCESS"`(현재는 도달하지 않음, PG 실연동 시 사용)면 결제 실패로 기록하고 구독/등기부 연결 같은 후속 효과는 만들지 않음
- ~~[2026-08-05 Payment Final Audit] 현재 인터페이스는 실제 Toss/PortOne 연동에 부족함~~ → **2026-08-05 Provider Interface v2로 확장 완료**. `PaymentProvider`에 5개 메서드 추가: `create_order()`(주문 생성) / `confirm_payment()`(결제 승인) / `cancel_payment()`(취소·환불) / `verify_payment()`(서버가 PG API로 재확인) / `handle_webhook()`(PG Webhook payload 정규화). `MockProvider`는 6개 메서드(기존 `charge()` 포함) 전부 구현, `TossProvider`/`PortOneProvider`는 여전히 자리만(base class의 `NotImplementedError` 상속)
- ~~이번 v2는 인터페이스 확장만 — payments.py는 아직 charge()만 호출~~ → **2026-08-05 Payment Flow Migration으로 연결 완료**(바로 아래 항목)

### Payment Flow Migration (2026-08-05)
- `payments.py:create_payment_record()`가 이제 `provider.charge()` 대신 `provider.create_order()` → `provider.confirm_payment()` → `provider.verify_payment()` 순서로 호출한다 — 실제 PG 흐름(주문 생성→결제창→승인→서버 재검증)과 동일한 단계 구성
- `MockProvider`는 사용자가 결제창에서 결제를 마치고 돌아오는 중간 단계가 없으므로 `confirm_payment()`를 `create_order()` 직후 곧바로 이어서 호출한다 — 실제 PG 연동 시 이 호출 지점만 클라이언트 콜백/리다이렉트 처리 뒤로 옮기면 되고, 반환값 형태(`ChargeResult`)는 그대로라 이후 로직(저장/구독/등기부 연결)은 안 바뀐다
- `cancel_payment()`/`handle_webhook()` 2개는 여전히 `payments.py` 어디에서도 호출되지 않음(환불 엔드포인트, Webhook 엔드포인트가 아직 없음 — 이번 Sprint 범위 아님)
- `create_payment_record()`의 반환 시그니처(`payment_id`, `status`)는 그대로라 호출부(`create_payment()` 라우터 핸들러의 구독 생성/등기부 연결 로직)는 전혀 수정하지 않음 — 회귀 없음

### 결제(Payment) → 구독(Subscription) → Premium → Registry (2026-08-05 완성, PG 미연동)
- `POST /api/v1/payments`: PG 미연동 상태의 Mock 결제(`MockProvider`). 요청 즉시 `payments.status="SUCCESS"`로 기록(`pg_provider=null`, `pg_transaction_id="MOCK-<uuid>"`)
- `payment_type="SUBSCRIPTION"`이면 같은 요청 안에서 `subscriptions` row를 함께 생성(`status="ACTIVE"`, `started_at=now`, `expires_at=now+30일`). 플랜별 가격(`amount`)은 2026-08-05부터 `PLAN_PRICES`(`BETA_EARLYBIRD`=9,900원, `STANDARD`=22,900원) 기준으로 서버에서 검증한다(`OVERAGE_FEE`와 동일한 방식)
- Premium 여부는 별도 테이블/플래그 없이 `registry.py`의 `has_active_subscription()`(status=ACTIVE AND expires_at > now)으로만 판정 — `subscriptions` row 존재가 곧 Premium
- `payment_type="OVERAGE_USAGE"`(등기부 초과 건별 결제): `req.amount`가 `registry.py`의 `OVERAGE_FEE`(=1000) 상수와 다르면 결제 자체를 거부. 결제 성공 시 해당 유저의 가장 오래된 미결제 `PAYMENT_REQUIRED` 건을 찾아 `payment_id` 연결 + `status="PENDING"`으로 전환(같은 트랜잭션, 부분 성공 시 rollback). 결제할 대상이 없으면(이미 결제됨/애초에 없음) `payments` row 자체를 만들지 않고 즉시 거부
- 프론트엔드는 `/api/v1/payments`, `/api/v1/registry-requests`를 실제로 호출한다(`src/app/properties/[id]/page.tsx`, 2026-08-05 연동) — 더 이상 "미호출" 아님

### Admin — Registry 운영 (2026-08-05 MVP)
- `api/v1/admin.py`: `registry_requests` 상태를 운영자가 직접 관리. 인증은 Supabase JWT가 아니라 `X-Admin-Key` 헤더(위 API 표 참고)
- 허용 전이: `PENDING→PROCESSING`, `PENDING→FAILED`, `PROCESSING→COMPLETED`, `PROCESSING→FAILED`. 그 외(예: `COMPLETED`에서 다른 상태로, `PENDING→COMPLETED` 직행 등)는 전부 `400`
- `PAYMENT_REQUIRED`는 관리자 전이 대상이 아님 — 결제 성공으로만 `PENDING`이 됨(위 문단)
- `COMPLETED`는 `completed_at` 자동 기록 + `doc_url`(2026-08-05부터 필수) 저장, `FAILED`는 `reason`(필수) 저장
- **등기부 문서 전달 (2026-08-05 구현, 같은 날 프론트 연동까지 완료)**: `GET /registry-requests/{id}/download`가 더 이상 `501`이 아니다. `registry_documents/`(신규 디렉터리, `.gitignore` 처리)에 파일을 두고 `doc_url`(상대경로)을 지정하면 실제 파일을 서빙한다. 단 **자동 수집 엔진이 아니다** — 등기부등본은 이 크롤러(courtauction.go.kr 대상)가 수집하는 문서가 아니라 별도 경로(대법원 인터넷등기소 등, 실연동 없음)로 발급받아 운영자가 파일을 직접 배치하고 Admin(`PATCH .../admin/registry-requests/{id}`, `doc_url` 포함)으로 연결하는 구조. 경로 탐색 방지는 `api/v1/documents.py`와 동일한 `commonpath` 검사 방식 재사용
- `GET /registry-requests`, `GET /registry-requests/{id}`가 `reason` 필드를 함께 반환하도록 변경(프론트의 FAILED 사유 표시용, 기존 필드는 그대로 유지 — 추가만 했으므로 Breaking Change 아님)
- CORS에 `expose_headers=["Content-Disposition"]` 추가 — 브라우저가 cross-origin 응답의 이 헤더를 기본적으로 JS에 노출하지 않아, 프론트가 다운로드 파일명을 읽으려면 명시적으로 노출해야 함 (`api_server.py`)
- 본인 신청만 다운로드 가능(`WHERE id=? AND user_id=?`, 기존 `registry.py` 다른 엔드포인트와 동일한 소유권 검사 패턴)

---

## Database 연동 방식

- 종류: SQLite
- 파일: `C:\Users\Administrator\Desktop\dojoonpass\auction.db`
- 연결: `storage/database.py` → `get_connection()`
- DB_PATH: `"auction.db"` (상대경로)
- 크롤러(mvp_scraper.py)와 API 서버(api_server.py) 동일 DB 파일 사용 확인됨
- row_factory: sqlite3.Row
- 중복 처리: INSERT OR IGNORE
- 트랜잭션: commit() / rollback() 수동 관리
- 백업: 없음

---

## 인증 방식

- 방식: Supabase Auth JWT
- 헤더: `Authorization: Bearer {supabase_jwt}`
- 검증 키: `SUPABASE_JWT_SECRET` (환경변수)
- 사용자 식별자: JWT payload.sub = auth.users.id
- users 테이블 없음 (Supabase auth.users 직접 사용)
- NEXTAUTH_SECRET 사용 안 함

### 환경변수 (.env)

SUPABASE_URL=
SUPABASE_ANON_KEY=
SUPABASE_JWT_SECRET= (값 설정됨, 2026-08-05 재확인 — 이전 버전 문서의 "미입력 상태"는 stale했음)
PAYMENT_PROVIDER= (2026-08-05 신규, 선택: mock/toss/portone. 미설정 시 mock — 아직 `.env`에 값 없음, 없어도 기존과 동일하게 동작)
ADMIN_API_KEY= (Admin MVP용, 여전히 `.env`에 값 없음 — 설정 전까지 `/api/v1/admin/*` 전체 500)

### 개발용 임시 헤더
JWT 미설정 시에만 동작:

X-Test-User-Id: {user_id}


---

## 자동 수집 파이프라인

Task Scheduler (매일 06:00)
→ run_daily.bat
→ mvp_scraper.py >> logs/daily_run.log
→ migrate_execute.py >> logs/migrate_execute.log


---

## DB 스키마 (v4.1 확정)

### 원본 테이블
- `auction`: 크롤러 원본. 하위호환 유지. 변경 금지.

### 서비스 테이블
- `auction_case`: 사건 단위
- `auction_item`: 물건 단위. 검색/상세 API 기준 테이블.
- `document_status`: COLLECTING/OCR/PARSING/ANALYZING/READY/FAILED
- `doc_raw`: 원본 파일 보관
- `parsed_document`: parsed_json, parser_version (raw_text 없음)
- `tenant_rights`: 임차인 원본 데이터. 분석 결과 없음.
- `rights_summary`: occupancy_difficulty(EASY/NORMAL/HARD), risk_level(LOW/MID/HIGH), risk_reason(JSON)
- `rights_analysis_history`: 분석 이력
- `document_collect_failures`: 수집 실패 로그

### 사용자 테이블 (Phase 1)
- `favorites`: UNIQUE(user_id, item_id)
- `recent_items`: UNIQUE(user_id, item_id), viewed_at 갱신
- `search_presets`: conditions JSON

### 결제/등기부 테이블 (Phase 1)
- `subscriptions`: plan(BETA_EARLYBIRD/STANDARD), status(ACTIVE/CANCELLED/EXPIRED)
- `registry_usage`: is_free, charged_amount
- `payments`: payment_type(SUBSCRIPTION/OVERAGE_USAGE), pg_provider(미연동, null)
- `registry_requests`: status(PENDING/PAYMENT_REQUIRED/PROCESSING/COMPLETED/FAILED)

### 마이그레이션 관리
`migration_history` 테이블로 적용 이력 관리.
`python -m storage.migrations.run_migrations` 으로 실행.
각 SQL 파일은 독립 실행 가능.

---

## Validation 규칙

- validation_status: PASS / FAIL
- FAIL 조건: address_mismatch (addr 시도 ≠ appraisal 시도)
- FAIL 건도 DB 저장 (제외 안 함)

---

## Error 처리 방식

| 코드 | 의미 |
|------|------|
| 401 | 토큰 없음 / 검증 실패 |
| 403 | 권한 없음 |
| 404 | 리소스 없음 |
| 402 | 결제 필요 |
| 500 | JWT Secret 미설정 / 서버 오류 |
| 501 | (해당 없음 — 등기부 다운로드는 2026-08-05부터 실제 파일 서빙으로 대체) |

---

## 향후 개발 예정

### Phase 2
- ~~payments/subscriptions API~~ (2026-08-05 Mock으로 구현 완료)
- ~~프론트엔드 ↔ payments/registry-requests API 연동~~ (2026-08-05 완료)
- ~~OVERAGE_USAGE 결제 → registry_requests 자동 연결~~ (2026-08-05 완료)
- ~~관리자 페이지(등기부 신청 상태 관리)~~ (2026-08-05 MVP 완료, `api/v1/admin.py`)
- ~~등기부 문서 전달 구조~~ (2026-08-05 완료 — 운영자가 파일을 `registry_documents/`에 배치 + Admin이 `doc_url` 연결하는 수동 방식. 대법원 인터넷등기소 등 실제 발급기관과의 자동 연동은 여전히 없음 — 아래 알려진 문제점 참고)
- PG사 실연동 (Toss/PortOne 등, 여전히 미확정)
- registry_rights 테이블

### Phase 3
- LLM 기반 권리분석
- 임차인 배당 시뮬레이션

---

## 절대 변경하면 안 되는 것

- `auction.db` 경로: `C:\Users\Administrator\Desktop\dojoonpass\auction.db`
- `auction` 테이블 구조 (크롤러 원본)
- `auction_item.id` (프론트 라우팅 /auction/{itemId} 기준 PK, 정수형)
- GET /api/v1/search 응답 필드명 (프론트 연동 완료)
- GET /api/v1/item/{item_id} 응답 필드명 (프론트 연동 완료)
- 공통 응답 형식 `{"success", "data", "message"}`
- 인증 방식: Supabase JWT (NEXTAUTH_SECRET 사용 금지). 단 `/api/v1/admin/*`만 예외로 `X-Admin-Key` 사용(위 참고)
- `python -m storage.migrations.run_migrations` 실행 방식

---

## 알려진 문제점

- 외부 봇/스캐너 접근 중 (0.0.0.0:8000, 방화벽 미설정)
- sido="" 데이터 1건 존재
- 자유텍스트 주소 검색 미지원
- ~~등기부 다운로드 501~~ → 2026-08-05 파일 전달 구조로 해결. 단 실제 등기부등본을 자동으로 수집/발급받는 기능은 없음 — 운영자가 대법원 인터넷등기소 등에서 수동으로 발급받아 `registry_documents/`에 넣어야 함(자동화 아님, 운영 부담 존재)
- ~~SUPABASE_JWT_SECRET 미입력~~ → 2026-08-05 재확인 결과 값이 설정되어 있음(이 문서의 오래된 서술이었음)
- auction.db 백업 없음
- ~~`POST /api/v1/payments`가 `SUBSCRIPTION` 플랜별 가격을 서버에서 검증하지 않음~~ → 2026-08-05 해결. `OVERAGE_USAGE`(`OVERAGE_FEE`)와 `SUBSCRIPTION`(`PLAN_PRICES`) 둘 다 서버에서 금액을 검증한다
- 구독 기간 30일 고정값은 정책 확정 전 임시 가정
- 등기부 무료 한도가 코드(평생 누적 5회)와 구독 정책 문서(월 5회)로 여전히 불일치(`docs/decision-log.md` Pending Decisions 참고) — Admin/Payment 연결은 완성됐지만 이 정책 자체는 미확정
- `ADMIN_API_KEY`가 `.env`에 아직 설정되어 있지 않음 — 설정 전까지 모든 `/api/v1/admin/*` 요청은 `500`
- Admin 인증에 역할(role) 구분이 없음 — 키를 아는 사람은 누구나 전체 관리자 권한(MVP 한계, 사용자 확인 하에 채택)
- ~~[Release Blocking] 등기부 무료횟수 레이스 컨디션~~ → **2026-08-05 수정 완료**. `registry.py:create_registry_request()`에서 `conn.isolation_level = None` + `BEGIN IMMEDIATE`로 무료횟수 확인(`get_free_count()`)과 INSERT를 하나의 원자적 트랜잭션으로 묶었다 — SQLite가 이 커넥션에 즉시 쓰기 락을 선점시켜, 동시 요청 중 하나가 커밋을 마칠 때까지 다른 요청은 자신의 COUNT를 다시 셀 수 없다. `payments.py`의 `OVERAGE_USAGE`(조건부 UPDATE+rowcount)와 목적은 같지만, 이쪽은 COUNT 집계값을 다루므로 row 단위 조건부 UPDATE로는 막을 수 없어 트랜잭션 자체를 직접 제어하는 방식을 썼다. 5/10/20 스레드 동시 요청 테스트 전부에서 정확히 5건만 무료 처리되고 나머지는 `PAYMENT_REQUIRED`로 정상 처리됨을 실증 확인(이전엔 5스레드만으로도 8건까지 초과됐었음)
- SQLite FK(`REFERENCES`)가 `storage/database.py`에 `PRAGMA foreign_keys=ON`이 없어 DB 레벨에서 전혀 강제되지 않음(확인됨, 스키마 선언은 문서용). 현재는 어떤 테이블에도 DELETE 경로가 없어 실제 orphan row는 발생하지 않지만, 구조적으로는 무방비 상태(Non-blocking, 향후 삭제 기능 추가 시 재검토 필요)
- `registry.py:create_registry_request()`는 다중 INSERT 앞뒤로 명시적 `try/except/rollback`이 없음(반면 `payments.py`/`admin.py`는 있음) — 실측 결과 `conn.commit()` 없이 `conn.close()`하면 SQLite가 자동으로 rollback하므로 현재는 안전하지만, 코드 일관성 문제로 남아있음(Non-blocking)
- `payments.status`의 스키마 선언값(PENDING/SUCCESS/FAILED/REFUNDED) 중 `PENDING`은 컬럼 DEFAULT로만 존재(모든 INSERT가 status를 명시적으로 지정해 실제로는 절대 쓰이지 않음), `REFUNDED`는 이 값을 쓰는 코드가 전체 저장소에 0건(환불 기능 자체가 없음) — 둘 다 죽은 상태(Non-blocking, PG/환불 기능 설계 시 정리 필요)

---

## 주의사항

- 투자점수 / AI추천 / 수익률 계산 개발 금지
- 방화벽 설정: 베타 공개 직전 별도 작업
- PG 연동 코드 작성 금지 (PG사 미확정) — 여전히 유효, `pg_provider`는 계속 null
- ~~결제 성공 가정 Mock 로직 백엔드 작성 금지~~ → **2026-08-05 Sprint 1에서 예외적으로 구현됨** (`api/v1/payments.py`, CTO 승인). 기존 결정(`docs/decision-log.md`)을 이 범위에 한해 대체함. Payment↔Subscription↔Premium 내부 체인 검증 목적이며 PG 실연동과는 무관
- ~~`registry_requests`의 PAYMENT_REQUIRED(등기부 초과분) 상태는 결제와 연결되지 않는다~~ → 2026-08-05 자동 연결 구현 완료(위 "결제(Payment)..." 참고)
- property_type 코드: APARTMENT/OFFICETEL/LAND/FACTORY/COMMERCIAL/MULTI_FAMILY
- payments.pg_provider: 현재 null (Mock 결제이므로)
- Admin MVP(`api/v1/admin.py`) 도입: `X-Admin-Key` 인증, `registry_requests.reason` 컬럼 추가(`010_add_registry_request_reason.sql`) — 스키마 변경 사용자 승인 완료
