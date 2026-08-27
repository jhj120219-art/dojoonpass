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
constants.py          (2026-08-07 Sprint 28 신설 — 도메인 상태값/Error Code 단일 정의)
v1/
search.py
item.py
favorites.py
recent_items.py
search_presets.py
registry.py
registry_credits.py   (2026-08-07 Sprint 27 신설 — 등기부 무료횟수 조정 원장)
documents.py
payments.py
payment_providers.py
payment_logs.py        (2026-08-07 Sprint 27 신설 — 결제 로그/Webhook 구조)
subscriptions.py       (2026-08-07 Sprint 28 신설 — Subscription Lifecycle, get_active_subscription/
                          sync_expired_status/change_status/renew. Admin REST가 사용, 자체 라우터 없음)
state_machines.py      (2026-08-07 Sprint 28 신설 — Payment/Subscription 상태 전이 규칙)
audit.py               (2026-08-07 Sprint 28 신설 — Admin 작업 감사 로그)
admin.py
doc_stats.py
storage/
database.py
migrate_v4_1.py
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
011_auction_case_court_code_unique.sql   (2026-08-08 Migration 정합성 복구로 재작성)
012_auction_court_code_unique.sql        (〃)
013_auction_item_case_id_unique.sql      (〃)
014_create_payment_logs.sql              (〃)
015_create_registry_credits.sql          (〃)
016_create_audit_and_credit_logs.sql     (2026-08-11 Sprint 51 — audit_logs/registry_credit_logs/soft delete 통합.
                                           옛 016_create_audit_logs.sql·017_add_soft_delete_columns.sql은
                                           이 파일로 대체되어 Sprint 57에서 삭제됨)
017_create_document_collect_failures.sql (2026-08-11 Sprint 51 — 부트스트랩 누락 복구)
018_document_queue_item_no_unique.sql    (2026-08-11 Sprint 55 — document_queue UNIQUE에 item_no 포함, BUGS #48)
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
- host: 127.0.0.1(localhost 전용) — 2026-08-06 코드 재확인·정정. `api_server.py` 하단
  `uvicorn.run(..., host="127.0.0.1", ...)` 하드코딩 확인(`git log -p`로 커밋 `bfefbf7`(인증
  도입 시점)에서 `0.0.0.0` → `127.0.0.1`로 이미 변경된 이력 확인). 이전 버전 문서의 "0.0.0.0"은 stale
- Swagger: `http://localhost:8000/docs`
- CORS: `CORS_ALLOW_ORIGINS` 환경변수로 제한 가능(콤마 구분 다중 오리진). 미설정 시 전체 허용(`*`)으로
  폴백 — 2026-08-10 Sprint 48 재확인, "전체 허용 고정"이던 이전 서술은 stale이었다
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
| GET/HEAD | /api/v1/item/{item_id}/images/{seq} | 물건 사진 실파일 서빙(2026-08-17 Sprint 144). 문서 뷰어와 같은 판단으로 공개 — 상세 화면이 공개인데 그 화면의 사진만 인증을 요구하면 화면이 깨진다. 경로는 `auction_image.storage_path`에서 읽고, **DB가 가리키는 파일이 실제로 있는지 반드시 다시 확인**한다(없으면 404) |

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
| GET | /api/v1/subscriptions/me | 2026-08-11 Sprint 52 신설. 내 구독 목록(최신순). 파생 필드 `effective_status`/`is_entitled`/`grace_period_end` 포함, 조회 시 lazy sync |
| POST | /api/v1/payments/webhook/{provider} | 2026-08-11 Sprint 52 신설. **사용자 인증 없음**(PG가 호출) — 서명 검증이 유일한 방어선. 검증 실패 401, `event_id` 멱등 |

### Admin 전용 (Supabase JWT 아님 — `X-Admin-Key` 헤더, 2026-08-05 추가)
| 메서드 | 경로 | 비고 |
|--------|------|------|
| GET | /api/v1/admin/registry-requests | 목록 조회. `status`/`user_id`/`item_id`/`case_no`/`page`/`size` 필터 |
| PATCH | /api/v1/admin/registry-requests/{id} | 상태 전이. 허용: PENDING→(PROCESSING,FAILED), PROCESSING→(COMPLETED,FAILED) |
| GET | /api/v1/admin/payments/webhooks | 2026-08-11 Sprint 53 신설. Webhook 수신 목록. `processing_status`/`provider`/`payment_id`/`signature_verified`/`reprocessable_only` 필터. 각 행에 `reprocessable`·차단 사유 포함 |
| GET | /api/v1/admin/payments/webhooks/{id} | 2026-08-11 Sprint 53 신설. 원문 payload + 실패 사유 |
| POST | /api/v1/admin/payments/webhooks/{id}/reprocess | 2026-08-11 Sprint 53 신설. **SUPER_ADMIN 전용**(결제 상태 변경 가능). 수신 경로와 같은 `_apply_webhook_event()`를 타므로 상태머신 우회 없음. 서명 미검증/이미 처리됨/FAILED는 거부 |
| POST | /api/v1/admin/payments/{id}/refund | 2026-08-11 Sprint 52 신설. **SUPER_ADMIN 전용**(과금 직접 영향). 전액/부분/반복 환불, 상태머신 관문 통과 필수, 멱등, 감사 로그 기록. 실제 PG 호출 없음(MockProvider) |

- 인증 방식이 다른 모든 API와 다르다: Supabase JWT를 쓰지 않고 `X-Admin-Key` 헤더를 서버 환경변수 `ADMIN_API_KEY`와 비교한다(`api/v1/admin.py:require_admin`). 2026-08-06(Sprint 15)부터 `hmac.compare_digest()`로 상수 시간 비교(타이밍 공격 방어) — 이전에는 단순 `!=` 비교였음. 역할(role) 개념이 프로젝트 어디에도 없어 MVP로 도입한 임시 인증이며, 사용자별 권한 구분은 없다(키를 아는 사람은 전체 관리자 권한, 이 부분은 이번 수정 범위 밖).
- `ADMIN_API_KEY`가 `.env`에 설정되어 있지 않으면 요청 자체가 `500 "관리자 키 미설정"`으로 막힌다 — 아직 `.env`에 값이 없다(운영 전 사용자가 직접 설정 필요, DB/env 변경 승인 정책상 임의로 넣지 않음).
- `COMPLETED` 전이 시 `completed_at` 자동 기록, `FAILED` 전이 시 `reason`(필수) 저장 — `registry_requests.reason` 컬럼은 `010_add_registry_request_reason.sql`로 신규 추가됨.
- `PAYMENT_REQUIRED`는 관리자가 직접 전이시킬 수 없다 — `POST /api/v1/payments`(OVERAGE_USAGE)가 성공할 때만 `PENDING`으로 자동 전환된다.

### GET /api/v1/search 파라미터
case_no, sido, sigungu, dong, address_detail(자유텍스트, 아래 참고),
property_type(콤마 다중선택), court_name, status,
auction_date_from, auction_date_to,
min_appraisal, max_appraisal,
min_bid_price, max_bid_price,
min_bid_rate, max_bid_rate,
min_fail_count, max_fail_count,
sort_by, sort_order(asc/desc),
page(기본 1), size(기본 20, 최대 100),
include_closed(기본 false)

전체 파라미터/필터 구조/정렬/인덱스의 상세 근거는 `docs/search-engine.md` 참고(2026-08-06 코드 기준 재동기화됨).

### 대표 사진 URL 규칙 (2026-08-20 Sprint 224)

목록 성격의 응답에 실리는 `thumbnail_url` 의 출처는 `api/v1/thumbnails.py` **하나뿐**이다.

```
IMAGE_URL_TEMPLATE = "/api/v1/item/%d/images/%d"     실제 라우트(api/v1/images.py)와 같아야 한다
fetch_thumbnail_seqs(conn, ids)  -> {item_id: MIN(seq)}   쿼리 **1회** (물건 수와 무관)
thumbnail_url(id, seqs)          -> URL 또는 None
```

- 대표 = 순번(`seq`)이 가장 앞선 사진. 상세가 `images[0]` 을 대표로 쓰는 것과 같은 규칙이다.
- 사진이 없는 물건은 **키는 있고 값이 `null`** 이다(프런트 분기를 단순하게 유지한다).
- 이 규칙을 화면마다 따로 적으면 어긋났을 때 **"목록에는 나오는데 열면 404"** 가 된다.
  화면은 정상으로 보이고 로그도 조용해 눈으로 찾기 어렵다.
- 주는 엔드포인트: `GET /api/v1/search`, `GET /api/v1/favorites`, `GET /api/v1/recent-items`.

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

**확정 정책(2026-08-06 CTO 확정, `docs/decision-log.md` 참고)**: 플랜별 **월 단위** 무료 제공 —
베이직 월 5회 / 프로 월 10회. 매월 리셋된다. 초과 시 건당 1,000원(`OVERAGE_FEE`).

**구현 완료(2026-08-06)**
- `get_free_count()`가 `used_at >= 이번 달 1일` 조건으로 **이번 달 사용분만** COUNT한다.
  `used_at`이 ISO 8601 문자열이라 사전순 = 시간순이므로 문자열 비교로 월 경계를 나눌 수 있고,
  월이 바뀌면 자동으로 0부터 다시 센다 — **별도 리셋 배치가 필요 없다**
- `get_user_free_limit()`이 활성 구독의 `plan`을 조회해 `PLAN_CATALOG`의
  `registry_monthly_limit`(베이직 5 / 프로 10)을 적용한다. 플랜을 해석할 수 없으면
  보수적으로 `DEFAULT_FREE_LIMIT`(=5)을 쓴다
- `payments.py` ↔ `registry.py` 순환 import를 피하려 `get_registry_monthly_limit`는
  함수 내부에서 import한다(기존 `OVERAGE_FEE`가 반대 방향으로 이미 import되고 있기 때문)

공통(정책 변경과 무관하게 유지되는 동작):
- 차감 시점: 신청 시점
- 한도 초과 시 `registry_requests`에 `PAYMENT_REQUIRED` row 생성. `POST /api/v1/payments`(OVERAGE_USAGE)가 성공하면 가장 오래된 미결제 `PAYMENT_REQUIRED` 건을 찾아 `payment_id` 연결 + `status=PENDING`으로 자동 전환(아래 "결제(Payment)..." 참고)
- 무료횟수 COUNT와 등록은 원자적 트랜잭션(`BEGIN IMMEDIATE`)으로 묶여 있어 동시 요청에도 한도를 초과할 수 없다(2026-08-05 Release Blocking 수정)

### 구독 정책

**확정 정책(2026-08-06 CTO 최종 확정, `docs/decision-log.md` 참고)**

| 플랜 | 월 요금 | 연 정상가 | 연 판매가 | 등기부등본 |
|---|---|---|---|---|
| 베이직(BASIC) | 12,900원 | 154,800원 | 154,800원 | 월 5회 |
| 프로(PRO) | 22,900원 | 274,800원 | **198,000원(할인)** | 월 10회 |

기존 표기(`BETA_EARLYBIRD`/`STANDARD`, "얼리버드 평생 9,900원 유지", "평생 누적 5회")는 전부 폐기됨.

**구현 완료(2026-08-06) — 할인 정책을 하드코딩하지 않는 구조**

- `PLAN_CATALOG`가 플랜 → 결제주기 → 가격 항목 구조를 갖는다. 가격 항목이 지원하는 필드:

  | 필드 | 필수 | 의미 |
  |---|---|---|
  | `list_price` | 필수 | 정상가 |
  | `sale_price` | 선택 | 고정 할인가. 지정되면 이 값이 청구액 |
  | `discount_percent` | 선택 | 정률 할인(%). `sale_price`가 없을 때만 적용 |
  | `discount_start` | 선택 | 할인 시작일 `YYYY-MM-DD` (생략 시 제한 없음) |
  | `discount_end` | 선택 | 할인 종료일 `YYYY-MM-DD` (그날까지 포함) |

  현재 값이 채워진 것은 프로 연간뿐이다(`list_price=274800`, `sale_price=198000`, 기간 무제한).
- `resolve_plan_price(plan, billing_cycle, at=None)`이 가격 해석의 **단일 진입점**이다 —
  호출부(결제 라우터)는 가격 규칙을 전혀 모른다. 할인 우선순위는
  `sale_price` > `discount_percent` > `list_price`이고, **기간을 벗어나면 자동으로 정상가로
  복귀**하므로 이벤트 종료 시 코드를 고칠 필요가 없다(카탈로그 값만 넣고 빼면 된다)
- 결제주기: `BILLING_MONTHLY`(30일) / `BILLING_YEARLY`(365일). `BILLING_PERIOD_DAYS`로 관리하며
  요청에 `billing_cycle`이 없으면 월 결제로 간주한다(기존 호출 호환)
- 금액 검증은 기존 방식 유지 — 서버가 계산한 금액과 요청 `amount`가 다르면 거부

### 확정 Spec 미반영 항목 (2026-08-06 기준)

1. ~~플랜 체계 교체~~ → **완료**(`BASIC`/`PRO`, 12,900/22,900원)
2. ~~연 결제 도입~~ → **완료**(154,800/198,000원, 365일)
3. ~~등기부 한도 월 리셋 + 플랜별 차등~~ → **완료**
4. 기존 `BETA_EARLYBIRD` 구독 row 이관 방침 — **미정**(스키마 변경은 불필요. 운영 DB에 해당
   row가 존재하는지 확인 후 처리 방침 결정 필요)
5. ~~`KGInicisProvider` 신설~~ → **2026-08-07 완료**(클래스 + `PAYMENT_PROVIDER=kginicis` 경로).
   남은 것은 6개 메서드의 **실제 KG이니시스 API 호출 구현**뿐 — 외부 API Key/계약 필요로 승인 대기

### Payment Provider 구조 (2026-08-05, PG 실연동 준비 / 2026-08-06 PG사 확정 반영)
- **PG사는 KG이니시스로 확정됨(2026-08-06 CTO 확정)**. **2026-08-07 기준 `KGInicisProvider` 클래스와 `PAYMENT_PROVIDER=kginicis` 경로는 코드에 반영 완료**됐다 — 다만 6개 메서드 전부 `NotImplementedError`인 자리 구현이며, 실제 API 호출 코드는 외부 API Key/계약이 필요해 승인 대기 상태다
- `api/v1/payment_providers.py`: `PaymentProvider`(인터페이스) → `MockProvider`(현재 사용, 항상 SUCCESS) / `KGInicisProvider`(확정 PG사, 자리만) / `TossProvider`·`PortOneProvider`(**폐기 예정 후보**, 호출 시 `NotImplementedError` — 삭제는 승인 필요 작업이라 코드에 그대로 남아있음)
- `get_payment_provider()`가 환경변수 `PAYMENT_PROVIDER`(mock/kginicis/toss/portone, 기본값 `mock`)로 어떤 Provider를 쓸지 결정. `.env`에 값이 없어도 기존과 동일하게 `mock`으로 동작(하위호환). 폐기 예정값(`toss`/`portone`) 선택 시 경고 로그를 남기고, 알 수 없는 값이면 허용값 목록을 포함한 `ValueError`로 즉시 실패한다
- `payments.py`의 `create_payment_record()`가 `provider`의 결과(`status`/`pg_provider`/`pg_transaction_id`)를 그대로 `payments` row에 기록만 함 — router는 여전히 SQLite에 직접 쓰고, provider는 "결제 승인 여부"만 결정하는 좁은 역할(서비스/레포지토리 계층 아님). 2026-08-05부터 `charge()` 단일 호출 대신 `create_order()`→`confirm_payment()`→`verify_payment()` 순서로 호출(아래 "Payment Flow Migration" 참고)
- `status != "SUCCESS"`(현재는 도달하지 않음, PG 실연동 시 사용)면 결제 실패로 기록하고 구독/등기부 연결 같은 후속 효과는 만들지 않음
- ~~[2026-08-05 Payment Final Audit] 현재 인터페이스는 실제 PG 연동에 부족함~~ → **2026-08-05 Provider Interface v2로 확장 완료**. `PaymentProvider`에 5개 메서드 추가: `create_order()`(주문 생성) / `confirm_payment()`(결제 승인) / `cancel_payment()`(취소·환불) / `verify_payment()`(서버가 PG API로 재확인) / `handle_webhook()`(PG Webhook payload 정규화). `MockProvider`는 6개 메서드(기존 `charge()` 포함) 전부 구현 — 이 인터페이스는 KG이니시스 연동에도 그대로 재사용 가능
- ~~이번 v2는 인터페이스 확장만 — payments.py는 아직 charge()만 호출~~ → **2026-08-05 Payment Flow Migration으로 연결 완료**(바로 아래 항목)

### Payment Flow Migration (2026-08-05)
- `payments.py:create_payment_record()`가 이제 `provider.charge()` 대신 `provider.create_order()` → `provider.confirm_payment()` → `provider.verify_payment()` 순서로 호출한다 — 실제 PG 흐름(주문 생성→결제창→승인→서버 재검증)과 동일한 단계 구성
- `MockProvider`는 사용자가 결제창에서 결제를 마치고 돌아오는 중간 단계가 없으므로 `confirm_payment()`를 `create_order()` 직후 곧바로 이어서 호출한다 — 실제 PG 연동 시 이 호출 지점만 클라이언트 콜백/리다이렉트 처리 뒤로 옮기면 되고, 반환값 형태(`ChargeResult`)는 그대로라 이후 로직(저장/구독/등기부 연결)은 안 바뀐다
- ~~`cancel_payment()`/`handle_webhook()` 2개는 여전히 `payments.py` 어디에서도 호출되지 않음(환불 엔드포인트, Webhook 엔드포인트가 아직 없음 — 이번 Sprint 범위 아님)~~
  → **둘 다 호출된다** (2026-08-27 코드 대조로 정정). 환불은 `payments.py:621 refund_payment()` 가 `provider.cancel_payment()` 를 부르고(:678), 관리자 라우트 `POST /api/v1/admin/payments/{id}/refund`(`admin.py:975`) 가 그것을 연다. Webhook 수신은 `POST /api/v1/payments/webhook/{provider_name}`(`payments.py:735`) 이고, 재처리용 `POST /api/v1/admin/payments/webhooks/{id}/reprocess`(`admin.py:913`) 도 있다. 남은 것은 **KGInicis 판 구현체**뿐이다.
- `create_payment_record()`의 반환 시그니처(`payment_id`, `status`)는 그대로라 호출부(`create_payment()` 라우터 핸들러의 구독 생성/등기부 연결 로직)는 전혀 수정하지 않음 — 회귀 없음

### 결제(Payment) → 구독(Subscription) → Premium → Registry (2026-08-05 완성, PG 미연동)
- `POST /api/v1/payments`: PG 미연동 상태의 Mock 결제(`MockProvider`). 요청 즉시 `payments.status="SUCCESS"`로 기록(`pg_provider=null`, `pg_transaction_id="MOCK-<uuid>"`)
- `payment_type="SUBSCRIPTION"`이면 같은 요청 안에서 `subscriptions` row를 함께 생성(`status="ACTIVE"`, `started_at=now`, `expires_at=now + 결제주기별 기간`(월 30일 / 연 365일)). 금액(`amount`)은 서버가 `PLAN_CATALOG`로 계산한 값(`resolve_plan_price()`, 할인 적용 후)과 대조해 검증한다(`OVERAGE_FEE`와 동일한 방식) — 클라이언트가 보낸 금액을 신뢰하지 않는다
- Premium 여부는 별도 테이블/플래그 없이 `registry.py`의 `has_active_subscription()`으로만 판정. **2026-08-07부터 판정 기준이 Lifecycle과 일치한다** — `get_entitled_subscription()`이 `ACTIVE` + `GRACE_PERIOD`(만료 후 3일)를 이용 가능으로 보고, `PAUSED`/`CANCELLED`/유예 초과는 차단한다(`docs/STATE_MACHINES.md`)
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
- 파일: 저장소 루트의 `auction.db` (2026-08-07 정정 — `storage/database.py:DB_PATH = "auction.db"`는 **상대경로**라 프로세스의 작업 디렉터리 기준으로 열린다. 이전 문서의 `C:\Users\Administrator\Desktop\...` 절대경로는 이 PC에 존재하지 않는 옛 프로필 경로로 stale이었다. 현재 실제 위치는 `C:\Users\jhj12\OneDrive\Desktop\dojoonpass\auction.db`)
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
PAYMENT_PROVIDER= (2026-08-05 신규, 선택: mock/kginicis/toss/portone. 미설정 시 mock — 아직 `.env`에 값 없음, 없어도 기존과 동일하게 동작. `kginicis`는 확정 PG사지만 아직 자리 구현이라 선택 시 결제가 전부 실패한다 — 실연동 완료 전까지 `mock` 유지)
ADMIN_API_KEY= (Admin MVP용, 여전히 `.env`에 값 없음 — 설정 전까지 `/api/v1/admin/*` 전체 500). 2026-08-07부터 **ADMIN 등급**
SUPER_ADMIN_API_KEY= (2026-08-07 신규, 선택. 설정 시 그 키가 **SUPER_ADMIN 등급** — 등기부 한도 조정 등 과금 영향 조작 전용)
CORS_ALLOW_ORIGINS= (2026-08-07 신규, 선택: 콤마 구분 Origin 목록. 미설정 시 기존과 동일하게 `*` 전체 허용. 운영 배포 시 프론트 도메인만 지정 권장)

### 개발용 임시 헤더 — 존재하지 않음 (2026-08-07 정정)

이전 문서는 "JWT 미설정 시 `X-Test-User-Id: {user_id}` 헤더로 우회 가능"이라고 기술했으나,
**저장소 전체에 해당 헤더를 읽는 코드가 없다**(`api/auth.py`는 `HTTPBearer` + JWT 검증만 한다).
인증을 우회할 방법은 없으며, 테스트는 `test_api_regression.py`처럼 실제 서명된 HS256 토큰을
만들어 사용해야 한다.


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
- `favorites`: UNIQUE(user_id, item_id) + `deleted_at`/`deleted_by`(2026-08-07 추가, 아직 미사용)
- `recent_items`: UNIQUE(user_id, item_id), viewed_at 갱신
- `search_presets`: conditions JSON + `deleted_at`/`deleted_by`(2026-08-07 추가, 아직 미사용)

### 결제/등기부 테이블 (Phase 1)
- `subscriptions`: plan(BASIC/PRO — 2026-08-06 확정. 컬럼은 CHECK 제약 없는 TEXT라 스키마 변경 없이 교체됨. 과거 BETA_EARLYBIRD/STANDARD row가 남아있을 수 있음),
  status(**ACTIVE / GRACE_PERIOD / PAUSED / EXPIRED / CANCELLED** — 2026-08-07 Lifecycle 확장, `docs/STATE_MACHINES.md`)
- `registry_usage`: is_free, charged_amount
- `payments`: payment_type(SUBSCRIPTION/OVERAGE_USAGE), pg_provider(미연동, null),
  status(**CREATED/READY/REQUESTED/PAID/FAILED/EXPIRED/CANCELLED/PARTIAL_REFUND/REFUNDED** +
  레거시 `SUCCESS` — 2026-08-07 상태머신 확장)
- `registry_requests`: status(PENDING/PAYMENT_REQUIRED/PROCESSING/COMPLETED/FAILED)

### 감사·이력 테이블 (2026-08-07 신규, Sprint 27~28)
- `payment_logs`: 결제 생명주기 단계별 append-only 기록. `payment_id`는 nullable(주문 생성
  실패도 남겨야 하므로). 민감정보는 저장 전 마스킹
- `payment_webhooks`: PG 노티 원문. `event_id` UNIQUE로 멱등, `signature_verified` 별도 관리.
  ~~**수신 엔드포인트는 아직 없다**(구조만 준비)~~ → **있다** (2026-08-27 정정): `POST /api/v1/payments/webhook/{provider_name}`(`payments.py:735`).
- `registry_credits`: 무료 횟수 **조정 원장**(GRANT/DEDUCT/RESET). 잔액 컬럼 없음 —
  유효 한도 = 플랜 월 한도 + 이번 달 조정 합계
- `registry_credit_logs`: 무료 횟수가 움직인 **모든 사건**(지급/사용/회수/이벤트/환불).
  사용(USAGE)은 여기에만 남고 한도 계산에는 안 들어간다(`registry_usage`와 이중 차감 방지)
- `audit_logs`: Admin 작업 이력(admin_id/action/target_type/target_id/before/after/created_at)

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
- PG사 실연동 — **PG사는 KG이니시스로 확정(2026-08-06)**, `KGInicisProvider` **클래스는 2026-08-07 신설 완료**. Interface v2 6개 메서드의 실제 API 호출 구현만 남음(외부 API Key/계약 필요, 승인 대기)
- 확정된 구독 정책(베이직/프로, 연 결제, 등기부 월 리셋) 코드 반영 — 위 "확정 Spec 미반영 항목" 참고
- registry_rights 테이블

### Phase 3
- LLM 기반 권리분석
- 임차인 배당 시뮬레이션

---

## 절대 변경하면 안 되는 것

- `auction.db` 경로: 저장소 루트의 상대경로 `auction.db` (`storage/database.py:DB_PATH`). 절대경로로 바꾸지 않는다 — 크롤러와 API 서버가 같은 작업 디렉터리에서 실행되는 것을 전제로 한다
- `auction` 테이블 **컬럼 구성** (크롤러 원본). 단 UNIQUE 제약은 2026-08-07 CTO 승인 하에
  `(case_no, item_no)` → **`(court_code, case_no, item_no)`** 로 강화했다(Migration 012,
  `docs/BUGS.md` #18 — 법원 구분이 없어 다른 법원 물건이 소실되고 있었음). 컬럼은 그대로다
- `auction_item.id` (프론트 라우팅 /auction/{itemId} 기준 PK, 정수형)
- GET /api/v1/search 응답 필드명 (프론트 연동 완료)
- GET /api/v1/item/{item_id} 응답 필드명 (프론트 연동 완료).
  2026-08-17 Sprint 144에 키를 **추가만** 했다 — `images` / `image_count` /
  `representative_image` / `images_status`, 그리고 `documents[]` 항목에
  `available` / `page_count` / `file_size` / `doc_version` / `viewer_url` / `download_url`.
  **기존 키(`doc_type`/`status` 포함)는 하나도 바뀌거나 사라지지 않았고**, 회귀 테스트가
  그것을 고정한다(`test_asset_pipeline.py` §16의 "기존 키 유지" 검사)
- 공통 응답 형식 `{"success", "data", "message"}`
- 인증 방식: Supabase JWT (NEXTAUTH_SECRET 사용 금지). 단 `/api/v1/admin/*`만 예외로 `X-Admin-Key` 사용(위 참고)
- `python -m storage.migrations.run_migrations` 실행 방식

---

## 알려진 문제점

- ~~외부 봇/스캐너 접근 중 (0.0.0.0:8000, 방화벽 미설정)~~ → 2026-08-06 코드/git 이력 재확인 결과
  stale. `api_server.py`가 이미 `host="127.0.0.1"`(localhost 전용)로 바인딩되고 있어(커밋
  `bfefbf7`에서 `0.0.0.0`→`127.0.0.1`로 변경됨), 이 코드 경로로 실행하는 한 외부에서 직접
  접근할 수 없다. 다만 실제 운영 서버가 이 저장소의 `api_server.py`를 그대로(코드 수정/CLI
  `--host` 오버라이드 없이) 실행 중인지는 이번 정정의 범위 밖 — 배포 방식 자체는 코드로
  검증되지 않음(운영 환경 확인 필요, Non-blocking)
- sido="" 데이터 1건 존재
- ~~자유텍스트 주소 검색 미지원~~ → 2026-08-06 코드 재확인 결과 stale했음. `GET /api/v1/search`의 `address_detail` 파라미터로 이미 지원됨(`intent/analyzer.py` 기반 SIDO/SIGUNGU/DONG 구조화 시도 후, 구조화 불가능한 입력은 `full_address LIKE`로 폴백), 프론트(`SearchForm.tsx`)까지 연동 완료. 자세한 내용은 `docs/search-engine.md` "자유텍스트 주소 검색" 절 참고
- ~~등기부 다운로드 501~~ → 2026-08-05 파일 전달 구조로 해결. 단 실제 등기부등본을 자동으로 수집/발급받는 기능은 없음 — 운영자가 대법원 인터넷등기소 등에서 수동으로 발급받아 `registry_documents/`에 넣어야 함(자동화 아님, 운영 부담 존재)
- ~~SUPABASE_JWT_SECRET 미입력~~ → 2026-08-05 재확인 결과 값이 설정되어 있음(이 문서의 오래된 서술이었음)
- auction.db 백업 없음
- ~~`POST /api/v1/payments`가 `SUBSCRIPTION` 플랜별 가격을 서버에서 검증하지 않음~~ → 2026-08-05 해결. `OVERAGE_USAGE`(`OVERAGE_FEE`)와 `SUBSCRIPTION`(`PLAN_PRICES`) 둘 다 서버에서 금액을 검증한다
- ~~구독 기간 30일 고정~~ → 2026-08-06 해결(`BILLING_PERIOD_DAYS`, 월 30일 / 연 365일)
- ~~등기부 무료 한도 평생 누적~~ → 2026-08-06 해결(월 리셋 + 플랜별 차등)
- ~~플랜명/가격 불일치~~ → 2026-08-06 해결(`BASIC` 12,900 / `PRO` 22,900, 연 결제 포함)
- 기존 `BETA_EARLYBIRD`/`STANDARD` 플랜으로 생성된 `subscriptions` row가 있다면 새 플랜 체계로 해석되지 않는다 — `get_user_free_limit()`이 `DEFAULT_FREE_LIMIT`(5)로 폴백하므로 동작은 안전하나, 이관 방침은 미정
- ~~`ADMIN_API_KEY`가 `.env`에 아직 설정되어 있지 않음~~ → 2026-08-08/09 재확인 결과 stale.
  `.env`에 `ADMIN_API_KEY`/`SUPER_ADMIN_API_KEY` **변수명 자체는 이제 존재**한다(값 유효성은
  이 세션에서 확인 안 함 — Secret 값 열람 금지 원칙). `docs/BETA_RELEASE_CHECKLIST.md` P0-2 참고
- Admin 인증에 SUPER_ADMIN/ADMIN 2단계는 있으나 등급 안에서는 여전히 공유키 — 키를 아는 사람은
  그 등급의 전체 권한(MVP 한계, 사용자 확인 하에 채택). 아래 "2026-08-07 추가" 절 참고
- ~~[Release Blocking] 등기부 무료횟수 레이스 컨디션~~ → **2026-08-05 수정 완료**. `registry.py:create_registry_request()`에서 `conn.isolation_level = None` + `BEGIN IMMEDIATE`로 무료횟수 확인(`get_free_count()`)과 INSERT를 하나의 원자적 트랜잭션으로 묶었다 — SQLite가 이 커넥션에 즉시 쓰기 락을 선점시켜, 동시 요청 중 하나가 커밋을 마칠 때까지 다른 요청은 자신의 COUNT를 다시 셀 수 없다. `payments.py`의 `OVERAGE_USAGE`(조건부 UPDATE+rowcount)와 목적은 같지만, 이쪽은 COUNT 집계값을 다루므로 row 단위 조건부 UPDATE로는 막을 수 없어 트랜잭션 자체를 직접 제어하는 방식을 썼다. 5/10/20 스레드 동시 요청 테스트 전부에서 정확히 5건만 무료 처리되고 나머지는 `PAYMENT_REQUIRED`로 정상 처리됨을 실증 확인(이전엔 5스레드만으로도 8건까지 초과됐었음)
- ~~SQLite FK(`REFERENCES`)가 `PRAGMA foreign_keys=ON`이 없어 DB 레벨에서 전혀 강제되지 않음~~ →
  **2026-08-08 해결**(Migration 정합성 복구, CTO 승인). `storage/database.py:get_connection()`이
  기본으로 `PRAGMA foreign_keys=ON`을 켠다(`enforce_foreign_keys=False`로 명시 호출하면
  끌 수 있고, 테이블 재작성 패턴을 쓰는 마이그레이션만 이 값을 쓴다). 고아 INSERT가 실제로
  `sqlite3.IntegrityError`로 차단됨을 `test_schema_hygiene.py`/`test_api_regression.py`
  23번(FK 런타임 강제)에서 실측 확인
- ~~`registry.py:create_registry_request()`는 다중 INSERT 앞뒤로 명시적 `try/except/rollback`이 없음~~ → 2026-08-06 코드 재확인 결과 stale한 서술이었음. Sprint 10(`BEGIN IMMEDIATE` 도입) 시점에 `except Exception: conn.rollback(); raise`가 이미 함께 추가되어 있어 `payments.py`/`admin.py`와 동일한 패턴을 따르고 있음(코드 확인 완료, 수정 불필요)
- `payments.status`의 컬럼 DEFAULT인 `PENDING`은 모든 INSERT가 status를 명시적으로 지정해
  실제로는 절대 자연 발생하지 않는다(Non-blocking). ~~`REFUNDED`는 죽은 상태~~는 2026-08-07
  Sprint 28(Payment State Machine, `api/constants.py:PaymentStatus`)로 stale — `REFUNDED`/
  `PARTIAL_REFUND`는 이제 정식 상태값이고 `PAID`/`SUCCESS` → 그 상태로의 전이 규칙까지
  `api/v1/state_machines.py`에 정의·테스트(`test_api_regression.py` 24번)되어 있다. 다만
  실제로 이 상태에 도달시키는 **엔드포인트**(`cancel_payment` 호출부)는 여전히 없다 — "상태는
  모델링됨, 도달 경로만 없음"이 정확한 표현이다

---

## 주의사항

- 투자점수 / AI추천 / 수익률 계산 개발 금지
- 방화벽 설정: 베타 공개 직전 별도 작업
- PG 연동 코드 작성 금지 — 2026-08-06 PG사는 KG이니시스로 확정됐으나, **실제 연동 코드 작성은 여전히 금지**(외부 API Key/계약이 필요한 승인 대상). `pg_provider`는 계속 null, `MockProvider` 동작 유지
- ~~결제 성공 가정 Mock 로직 백엔드 작성 금지~~ → **2026-08-05 Sprint 1에서 예외적으로 구현됨** (`api/v1/payments.py`, CTO 승인). 기존 결정(`docs/decision-log.md`)을 이 범위에 한해 대체함. Payment↔Subscription↔Premium 내부 체인 검증 목적이며 PG 실연동과는 무관
- ~~`registry_requests`의 PAYMENT_REQUIRED(등기부 초과분) 상태는 결제와 연결되지 않는다~~ → 2026-08-05 자동 연결 구현 완료(위 "결제(Payment)..." 참고)
- property_type 코드: APARTMENT/OFFICETEL/LAND/FACTORY/COMMERCIAL/MULTI_FAMILY
- payments.pg_provider: 현재 null (Mock 결제이므로)
- Admin MVP(`api/v1/admin.py`) 도입: `X-Admin-Key` 인증, `registry_requests.reason` 컬럼 추가(`010_add_registry_request_reason.sql`) — 스키마 변경 사용자 승인 완료


---

## 2026-08-07 추가 (CTO 승인 6건)

### Plan API — 가격/플랜의 단일 Source of Truth
- `GET /api/v1/plans` (인증 불필요, envelope 사용): 플랜명·label·등기부 월 한도 +
  결제주기별 `list_price`/`price`(실청구액)/`discounted`/`discount_amount`/`discount_start`/
  `discount_end`/`period_days`, 그리고 `billing_cycles`·`overage_fee`
- `price`는 항상 `resolve_plan_price()` 결과다 — **표시 금액과 검증 금액이 같은 함수에서 나오므로
  구조적으로 어긋날 수 없다**. 프론트는 값을 갖지 않고 응답을 그대로 표시·전송만 한다

### Admin 권한 2단계 (Operator 없음)
| 등급 | 키 | 가능한 것 |
|---|---|---|
| `ADMIN` | `ADMIN_API_KEY` | 등기부 신청 목록 조회·상태 전이, credit **조회** |
| `SUPER_ADMIN` | `SUPER_ADMIN_API_KEY` | ADMIN 전부 + 등기부 무료횟수 **조정** |

- `resolve_admin_role()`이 제시된 키로 등급을 판정(둘 다 `hmac.compare_digest` 상수시간 비교)
- 두 키 모두 미설정이면 기존과 동일하게 `500 "관리자 키 미설정"`
- **기존 `ADMIN_API_KEY`만 설정된 환경도 그대로 동작한다**(ADMIN 등급, 하위호환)
- 한계: 여전히 키 기반이라 **개별 운영자를 특정할 수 없다** — 감사 로그에는 등급만 남는다

### 결제 로그 (`payment_logs` / `payment_webhooks`)
- `payments`는 최종 상태 한 줄뿐이라 결제 분쟁 시 궤적 재구성이 불가능했다
- `payment_logs`: `CREATE_ORDER`/`CONFIRM`/`VERIFY`/`CANCEL`/`WEBHOOK` 단계를 append-only 기록.
  `create_payment_record()`가 앞 3단계를 실제로 남기고, `payments` row 생성 후 `payment_id`를 연결
- `payment_webhooks`: PG 노티 원문 보관. `event_id` UNIQUE로 **멱등** 처리
  (PG는 응답이 늦으면 같은 노티를 재전송한다), `signature_verified`로 서명 검증 여부 관리
- `mask_sensitive()`가 카드번호/CVC/생년월일/토큰 등을 저장 전에 재귀 마스킹
- `GET /api/v1/payments/{id}/logs` — 본인 결제만 조회(타인은 404)
- **실제 PG API 호출·API Key 연결은 없다**(승인 범위대로 론칭 직전까지 연기)

### 등기부 무료횟수 조정 (`registry_credits`)
- **잔액 컬럼 없음.** 조정 원장만 쌓고 `유효 한도 = 플랜 월 한도 + 이번 달 조정 합계`로 계산한다.
  잔액 컬럼은 `registry_usage` 기반 사용량과 상태가 이중화되어 반드시 어긋난다
- `GRANT`(+) / `DEDUCT`(−) / `RESET`(그 달 이전 조정 무효화). 부호는 서버가 정한다.
  1회 조정 상한 100(오타 방어). 차감이 과해도 유효 한도는 **0에서 멈춘다**
- `GET /api/v1/admin/registry-credits/{user_id}` (ADMIN) — 플랜 한도/조정/유효 한도/사용량/이력
- `POST /api/v1/admin/registry-credits` (**SUPER_ADMIN 전용**)
- 월이 바뀌면 조정도 자연히 초기화된다(기존 월 리셋 정책과 같은 경계)


---

## 2026-08-07 추가 (CTO 추가 승인 10건, Sprint 28)

### FK 런타임 강제
- `storage/database.py:get_connection()`이 커넥션마다 `PRAGMA foreign_keys = ON`.
  SQLite는 `REFERENCES`를 선언해도 이걸 켜지 않으면 **아무 검사도 하지 않는다**(기본 OFF).
  이 저장소는 15개 FK를 선언해 두고 전부 무시되던 상태였다
- 마이그레이션만 `get_connection(enforce_foreign_keys=False)` — 테이블 재작성 패턴이
  중간에 자식 행을 잠시 고아로 만들기 때문(`storage/migrations/run_migrations.py`)

### 상태 머신
`api/constants.py`(상태값) + `api/v1/state_machines.py`(전이 규칙).
자세한 다이어그램과 근거는 **`docs/STATE_MACHINES.md`** 참고.

- Payment: `CREATED/READY/REQUESTED/PAID/FAILED/EXPIRED/CANCELLED/PARTIAL_REFUND/REFUNDED`.
  레거시 `SUCCESS`는 `PAID`와 동의어로 유지(기존 데이터 호환) — `is_paid()`가 둘 다 인정
- Subscription: `ACTIVE/GRACE_PERIOD/PAUSED/EXPIRED/CANCELLED`, 유예 3일.
  자동 만료는 **배치가 아니라 조회 시점 lazy sync**(`api/v1/subscriptions.py`)

### 감사·이력 테이블
- `audit_logs` — Admin 작업(admin_id/action/target_type/target_id/before/after/created_at).
  업무 트랜잭션과 같은 커밋에 넣는다
- `registry_credit_logs` — 무료 횟수가 움직인 **모든 사건**. `registry_credits`(한도 계산에
  반영되는 관리자 조정)와 역할이 다르다. 사용(USAGE)은 로그에만 남긴다 —
  계산에 넣으면 `registry_usage`와 이중 차감
- `payment_logs` / `payment_webhooks` — Sprint 27 참고

### Soft Delete
- `favorites`/`search_presets`에 `deleted_at`/`deleted_by` 컬럼 추가(**실제 DELETE가 있는 곳만**)
- 이번 범위는 컬럼 추가까지. 전환하려면 `UNIQUE(user_id,item_id)` 때문에 재등록이 막히는
  문제를 먼저 풀어야 한다 — 기존 DELETE 동작은 그대로다

### 공통 응답 형식
```
{ "success": bool, "data": any, "error": str|null, "meta": dict|null, "message": str|null }
```
- `error`(도메인 코드, `docs/ERROR_CODES.md`)와 `meta`(페이지네이션)는 **추가** 필드
- **`message`는 유지한다** — 프론트가 `result.message`를 읽고 있어 제거하면 Breaking Change
- Admin의 `HTTPException` 기반 실패(`{"detail": ...}`)는 그대로 뒀다(Spec 결정 사항이라 Skip)

### Admin 엔드포인트 (2026-08-07 기준 전체)
| 경로 | 메서드 | 권한 |
|---|---|---|
| `/admin/registry-requests` | GET, PATCH | ADMIN |
| `/admin/registry/requests` | GET | ADMIN (위와 동일 동작, 새 구조 경로) |
| `/admin/registry-credits/{user_id}` | GET | ADMIN |
| `/admin/registry-credits` | POST | **SUPER_ADMIN** |
| `/admin/registry/credit-logs/{user_id}` | GET | ADMIN |
| `/admin/users` | GET | ADMIN |
| `/admin/payments` | GET | ADMIN |
| `/admin/payments/{id}/logs` | GET | ADMIN |
| `/admin/subscriptions` | GET | ADMIN |
| `/admin/subscriptions/{id}` | PATCH | **SUPER_ADMIN** |
| `/admin/audit-logs` | GET | ADMIN |

### `GET /api/v1/doc-stats` 응답 필드 (2026-08-18 Sprint 189 갱신)

큐 적체 규모 필드가 하나 늘었다. **기존 필드는 이름도 의미도 그대로다**(순수 추가).

| 필드 | 뜻 |
|---|---|
| `queue_pending` | 한 번도 수집한 적 없어 대기 중 |
| `queue_refresh` | **(신규)** 이미 받았지만 법원 변경으로 다시 받아야 해서 대기 중 |
| `queue_in_progress` | 지금 작업 중 — `in_progress` + `in_progress_refresh`의 **합** |
| `queue_failed` | 재시도 소진으로 최종 실패 |

상태 문자열을 이 파일에 하드코딩하지 않는다. 어휘의 단일 소스는
`storage/database.py`의 `QUEUE_STATUS_*` / `QUEUE_IN_PROGRESS_STATUSES`이고,
`api/v1/doc_stats.py`가 그것을 import한다 — 하드코딩 목록은 **새 값이 생겨도 조용히
어느 칸에도 안 잡히는** 문제를 만든다(BUGS #119가 정확히 그 부류였다).
`test_refresh_trigger.py` §11이 하드코딩이 다시 들어오는 것을 막는다.


### `document_queue` claim 의 `None` 은 한 가지 뜻이다 (2026-08-18 Sprint 191, BUGS #130)

`claim_next_queue_item()` 이 `None` 을 돌려주는 것은 **"지금 가져갈 행이 없다"** 하나뿐이다.
(2026-08-20 Sprint 236: 워커는 이제 이 함수를 감싼 `claim_next_item_rows()` 를 부르고,
그쪽은 같은 뜻을 **빈 목록**으로 돌려준다. 첫 행 선택과 경쟁 처리는 여전히 이 함수가 한다.)

예전에는 두 가지가 같은 `None` 이었다:

```
(a) 조회 결과가 없다                     -> 진짜로 비었다
(b) 조회는 됐는데 UPDATE 에서 밀렸다      -> 경쟁에서 졌을 뿐, 큐는 안 비었다
```

`doc_worker.main()` 은 `None` 을 (a)로 읽고 **그 실행 전체를 끝낸다.** 즉 claim 충돌
한 번이 그날 남은 큐를 통째로 다음 날로 미뤘고, 로그에는 사실이 아닌
`대기열 비어있음` 이 남았다.

지금은 (b)면 **다른 행으로 다시 시도**한다(`CLAIM_RACE_MAX_ATTEMPTS = 5`).
상한에 걸리면 `None` 을 주되 **경고를 남긴다** — 그래야 "비었다"와 구별된다.

실측(스레드 12 / 대기 행 4): 중복 claim 은 **원래 0건**이었다(원자적 클레임 정상).
수정 전 claim 성공 3건 -> 수정 후 4건.
