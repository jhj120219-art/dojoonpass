# 상태 머신 (Payment / Subscription / Registry)

Status: Active
Last Updated: 2026-08-07 (Sprint 28)
Owner: CTO

정의 위치: `api/constants.py`(상태값) + `api/v1/state_machines.py`(전이 규칙).
**이 문서가 아니라 코드가 기준**이다.

---

## 왜 전이 규칙을 명시하는가

상태를 문자열로만 다루면 "REFUNDED에서 PAID로" 같은 불가능한 전이가 조용히 성립한다.
허용된 전이만 선언하고 나머지를 전부 거부하면, 잘못된 상태 변경이 **코드에 닿기 전에** 막힌다.
`api/v1/admin.py`의 등기부 신청 `ALLOWED_TRANSITIONS`가 이미 쓰던 방식이며, 같은 패턴을
결제·구독으로 넓힌 것이다(새 개념을 도입하지 않았다).

---

## 1. Payment (`api/constants.py:PaymentStatus`)

```
CREATED ──> READY ──> REQUESTED ──> PAID ──> PARTIAL_REFUND ──> REFUNDED
   │          │           │           └──────────────────────> REFUNDED
   │          │           │
   └──> FAILED / CANCELLED / EXPIRED  (종결 — 나가는 전이 없음)
```

| 상태 | 의미 |
|---|---|
| `CREATED` | 결제 레코드만 생성됨(주문 전) |
| `READY` | PG 주문 생성 완료, 결제창 호출 대기 |
| `REQUESTED` | 사용자가 결제창에서 결제 시도(승인 대기) |
| `PAID` | 최종 승인 완료 |
| `SUCCESS` | **레거시** — `PAID`와 동의어 |
| `FAILED` | 승인 실패/거절 |
| `EXPIRED` | 결제 시한 만료(가상계좌 미입금 등) |
| `CANCELLED` | 승인 전 취소 |
| `PARTIAL_REFUND` | 부분 환불(잔액 있음) |
| `REFUNDED` | 전액 환불 |

### ★ `SUCCESS`를 없애지 않은 이유

기존 `payments` 행과 `MockProvider`가 이 값을 쓰고 있다. 제거하면 기존 데이터가 해석
불가가 되고 Mock 결제 흐름이 통째로 깨진다(Breaking Change). `PAID`와 **같은 전이 규칙**을
주고, 성공 판정은 `api.constants.is_paid()`가 두 값을 모두 인정한다. 신규 코드는 `PAID`를 쓴다.

`PARTIAL_REFUND`도 `is_paid()`가 참으로 본다 — 일부 금액은 아직 유효하기 때문이다.

### 현재 흐름과의 관계 (2026-08-11 Sprint 52 갱신)

~~이 상태 머신은 앞으로 상태를 바꾸려는 코드가 통과할 관문이며 지금 흐름에는 개입하지 않는다~~
→ **이제 실제로 개입한다.** Sprint 52에서 상태를 바꾸는 두 경로를 연결했다.

| 경로 | 전이 | 관문 |
|---|---|---|
| `POST /api/v1/admin/payments/{id}/refund` (SUPER_ADMIN) | PAID/SUCCESS → PARTIAL_REFUND / REFUNDED | `assert_payment_transition()` |
| `POST /api/v1/payments/webhook/{provider}` (서명 검증 필수) | PG 노티가 지시하는 상태로 | `assert_payment_transition()` |

두 경로 모두 상태머신이 막는 전이는 **적용하지 않는다**(환불은 400, Webhook은 무시 후 200).
결제 생성 흐름(`MockProvider` → SUCCESS)은 그대로다 — 기존 동작 무변경.

부분 환불의 누적 금액은 `payments`에 컬럼을 추가하지 않고 **`payment_logs`의 CANCEL 이벤트
합계**로 계산한다(원장이 이미 append-only라 두 번째 진실을 만들지 않기 위해서다).

---

## 2. Subscription (`api/constants.py:SubscriptionStatus`)

```
        ┌──────────────< 갱신 결제 성공 ──────────────┐
        ▼                                             │
     ACTIVE ──만료──> GRACE_PERIOD ──유예 종료──> EXPIRED ──재결제──> ACTIVE
        │                   │                          │
        └──> PAUSED <───────┘(불가)                    │
             │                                         │
             └──────────> CANCELLED <──────────────────┘   (최종 — 되돌릴 수 없음)
```

| 상태 | 이용 가능 | 의미 |
|---|---|---|
| `ACTIVE` | ✅ | 정상 이용 중 |
| `GRACE_PERIOD` | ✅ | 만료됐지만 유예 기간(기본 **3일**) |
| `PAUSED` | ❌ | 일시정지 — 재개 가능 |
| `EXPIRED` | ❌ | 만료 — 재결제로 되살릴 수 있음 |
| `CANCELLED` | ❌ | 해지 — 최종 상태 |

### 유예 기간을 두는 이유

결제 실패 직후 즉시 차단하면 **카드 갱신 중인 정상 사용자가 끊긴다.** 3일 동안은 서비스를
계속 제공하면서 갱신을 기다린다(`GRACE_PERIOD_DAYS`).

**유예의 기한은 `expires_at`이 아니라 `expires_at + 3일`이다.** 유예는 정의상 만료 시각을
지난 뒤의 상태이므로, `expires_at > now`로 판정하면 유예 정책이 한 번도 작동하지 않는다.
그래서 `is_entitled()`는 만료 시각을 직접 비교하지 않고 `resolve_expected_status()`에
판정을 위임한다 — 규칙이 두 곳에 생기면 반드시 어긋난다.

### 이용권 게이트와의 연결

Premium 판정(`api/v1/registry.py:has_active_subscription()`)은
`get_entitled_subscription()` 하나만 본다. 이 함수는 SQL이 아니라 Python에서
`resolve_expected_status()` + `is_entitled()`로 판정한다:

- 유예 기간 규칙을 SQL 비교식으로 옮기면 규칙이 이중화된다
- `sync_expired_status()`를 부르면 **커밋이 일어나** `create_registry_request()`의
  `BEGIN IMMEDIATE` 트랜잭션이 중간에 끊긴다 — 그래서 DB는 건드리지 않고 계산만 한다

### 자동 만료 — 배치에 의존하지 않는다

이 프로젝트에는 상시 스케줄러가 크롤링 배치뿐이다. 만료 처리를 거기에 얹으면
**"배치가 안 돌아서 만료가 안 됨"이 곧 과금 사고**가 된다.

대신 `resolve_expected_status()`가 "지금 있어야 할 상태"를 순수 함수로 계산하고,
조회 시점에 DB 상태도 함께 맞춘다(`sync_expired_status()` — lazy sync).
배치가 없어도 정확하고, 나중에 배치를 붙여도 결과가 같다.

`PAUSED`/`CANCELLED`는 사용자 의사로 정해진 상태이므로 시간이 지나도 바뀌지 않는다.
`expires_at` 파싱이 실패하면 상태를 **바꾸지 않는다** — 파싱 실패를 '만료'로 해석하면
정상 구독자가 끊기기 때문이다.

### 무료 등기부 초기화

별도 작업이 없다. 한도는 `used_at >= 이번달 1일` 기준으로 계산되므로 월이 바뀌면
자동으로 0부터 다시 센다(`api/v1/registry.py:get_free_count()`).
관리자 조정(`registry_credits`)도 `effective_month`로 묶여 있어 같은 경계에서 초기화된다.

---

## 3. Registry Request (`api/constants.py:RegistryRequestStatus`)

기존 규칙 그대로다(`api/v1/admin.py:ALLOWED_TRANSITIONS`).

```
PAYMENT_REQUIRED ──결제 성공──> PENDING ──> PROCESSING ──> COMPLETED
                                    │            │
                                    └──> FAILED <┘
```

- `PAYMENT_REQUIRED`는 **관리자 전이 대상이 아니다** — 결제 성공으로만 `PENDING`이 된다
- `COMPLETED`/`FAILED`는 종결 상태
- `COMPLETED`에는 `doc_url` 필수, `FAILED`에는 `reason` 필수

---

## API

| 엔드포인트 | 권한 | 비고 |
|---|---|---|
| `PATCH /api/v1/admin/registry-requests/{id}` | ADMIN | 등기부 신청 상태 전이 |
| `PATCH /api/v1/admin/subscriptions/{id}` | **SUPER_ADMIN** | 구독 상태 전이(과금 영향) |

전이 규칙 위반은 **400**, 대상 없음은 **404**로 응답한다.
모든 상태 변경은 `audit_logs`에 before/after와 함께 기록된다.

---

## 회귀 방어

| 테스트 | 검증 내용 |
|---|---|
| `test_api_regression.py` 24 | Payment 허용/금지 전이, 레거시 SUCCESS 호환, 종결 상태 |
| `test_api_regression.py` 25 | Subscription 전이, 자동 만료(정상/유예/만료), 갱신, 해지 불가역 |
| `test_api_regression.py` 27 | Admin 구독 상태 변경 권한·전이 규칙·404 |
| `test_api_regression.py` 11 | 등기부 신청 전이 규칙 전수 |
