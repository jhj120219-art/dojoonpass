# Sprint 129 ― OVERAGE_USAGE 결제가 락보다 먼저 provider를 호출했다 (2026-08-15)

> 앞 Sprint: `docs/SPRINT128_ARCHITECTURE_DEAD_FUNCTION.md`
>
> **별도 파일 이유**: Sprint 100~128과 같다.

`/goal`이 지정한 우선순위(`payments.py overage-payment transaction path`)를 감사했다.
먼저 `docs/BUGS.md`/`docs/CURRENT_STATE.md`에서 OVERAGE_USAGE 관련 기록(#19,#20,#21)을
읽고 "조건부 UPDATE+rowcount로 이미 보호됨"이 최종 DB 정합성 얘기임을 확인한 뒤,
그 보호가 **provider 호출 시점**까지 커버하는지를 코드로 직접 대조했다.

## 발견

`api/v1/payments.py:create_payment()`에서 `payment_type=SUBSCRIPTION`은 Sprint 38(BUGS #20)
수정으로 `BEGIN IMMEDIATE`를 **provider 호출(`create_payment_record`) 이전**에 잡는다.
그런데 같은 함수의 `OVERAGE_USAGE` 분기는 그 원칙이 적용되지 않고 있었다:

```
[수정 전]
1. target_request SELECT           <- 락 없음
2. (SUBSCRIPTION만 여기서 BEGIN IMMEDIATE)
3. create_payment_record()         <- provider.create_order/confirm/verify 실행
4. registry_requests UPDATE ... WHERE payment_id IS NULL AND status='PAYMENT_REQUIRED'
   rowcount==0 이면 rollback + PAY_ALREADY_PROCESSED   <- 레이스는 여기서만 걸림
```

`test_race_conditions.py::test_overage_payment_race`가 이미 이 경로를 8스레드로
재현하고 있었고, 결과는 "등기부 신청에 실제 연결된 결제는 항상 1건"으로 **최종 DB
정합성은 지켜졌다.** 하지만 그 테스트 자신이 남긴 주석이 문제를 그대로 진술하고
있었다: "payments 행 자체는... n개 전부 생성될 수 있다" ― 즉 **레이스에서 진 요청도
provider 호출(`create_order`/`confirm_payment`/`verify_payment`)까지는 도달**하고,
그 결과(성공한 `payments` 행 + `payment_logs` 3건)가 4번 단계의 `conn.rollback()`으로
**우리 DB 기록만** 통째로 사라진다.

## 왜 문제인가 ― 지금은 무해하지만 실연동 시 그대로 청구 위험이 된다

지금은 `MockProvider`뿐이라 `create_order`/`confirm_payment`가 실제 부작용이 없다.
하지만 이 경로는 "실제 PG 연동 시 그대로 쓰인다"고 도처에 주석돼 있는 코드다
(`create_payment_record` 자체 docstring 포함). 실제 PG가 붙으면:

- 동시에 도착한 N개의 OVERAGE_USAGE 결제 요청 중 승자 1명을 제외한 나머지도
  전부 PG에 결제 승인(카드 청구)을 요청하게 된다.
- `conn.rollback()`은 SQLite 쪽 기록만 지운다 ― PG 쪽에서 이미 승인된 청구는
  취소되지 않는다. `refund_payment()`/`provider.cancel_payment()` 인프라는 있지만
  이 롤백 경로에서 **호출되지 않는다.**
- 게다가 `payment_logs`(분쟁 재구성용 원장, 2026-08-07 CTO 승인 5번)까지 같은
  트랜잭션 안에서 롤백되므로, 사고가 나도 "무슨 일이 있었는지" 재구성할 근거 자체가
  사라진다 ― 이 원장을 만든 목적과 정확히 반대되는 결과다.

`SUBSCRIPTION`은 이미 이 문제가 없다(락이 provider보다 먼저라 패자가 provider까지
가지 않는다). OVERAGE_USAGE만 비대칭이었다.

## 고친 것

`api/v1/payments.py:create_payment()` — `BEGIN IMMEDIATE`를 함수 진입 직후, 두
결제 유형(target_request 조회 / 기존 구독 확인) 어느 쪽보다도 먼저 무조건 잡도록
옮겼다. `VALID_PAYMENT_TYPES`는 SUBSCRIPTION/OVERAGE_USAGE 둘뿐이라(`api/constants.py`
`PaymentType`) 조건 분기 없이 걸어도 된다. 이제:

```
[수정 후]
1. BEGIN IMMEDIATE                 <- 무조건, provider 호출보다 먼저
2. target_request 재확인(OVERAGE_USAGE) / 기존 구독 확인(SUBSCRIPTION)
3. create_payment_record()         <- 락을 쥔 요청만 도달
4. registry_requests UPDATE (여전히 조건부 - 방어선 이중화, 제거하지 않음)
```

레이스에서 진 요청은 2번 단계에서 target_request가 이미 다른 트랜잭션에 의해
`PENDING`으로 바뀐 것을 보고 `PAY_NO_TARGET_REQUEST`로 즉시 거부된다 ― provider를
아예 호출하지 않는다. 4번의 조건부 UPDATE는 그대로 남겨뒀다(락이 이미 순차적
직렬화를 보장하지만, "락 획득 시점과 실제 쓰기 시점 사이 다른 결함으로 상태가
바뀌는" 방어선 이중화는 이 저장소의 기존 관례 — 예: registry.py도 락 이후 조건부
검사를 유지).

**실제 PG 연동 시 패자의 provider 호출 자체를 막는 것**이 이번 수정이다. "락을 쥔
뒤에도 실제로 PG에 청구가 나갔는데 우리 쪽만 롤백되는" 상황에 대한 자동 보상
(cancel_payment 자동 호출)은 다른 문제다 — MockProvider만 있는 지금은 그 실패
모드 자체가 재현·검증 불가능해 SKIP(아래 표).

## 동일 패턴 전수 검색

`get_payment_provider()`/`provider.create_order|confirm_payment|verify_payment|cancel_payment`
전체 호출부를 grep했다. 프로덕션 호출부는 2곳뿐:

| 호출부 | 락 순서 | 결과 |
|---|---|---|
| `create_payment_record()` (← `create_payment()`) | 이번 수정으로 provider보다 락이 먼저 | 수정 완료 |
| `refund_payment()`의 `provider.cancel_payment()` | 함수 최상단에서 이미 `BEGIN IMMEDIATE` 먼저 확보(510행) | 기존부터 정상 — 추가 수정 불필요 |

다른 provider 호출부 없음. 이 패턴은 이 두 곳이 전부였다.

## 회귀 테스트 강화

`test_race_conditions.py::test_overage_payment_race` — 기존에는
`"at least one payment row recorded", paid_payments >= 1` (약한 검사, 레이스 패자도
provider에 도달할 수 있다는 것을 그대로 용인하던 assertion)이었다. 이번 수정으로
패자가 provider에 도달하지 않으므로
`"exactly 1 payment row recorded (provider never reached by losers)", paid_payments, 1`
로 강화했다 — 완화가 아니라 강화다(이 세션의 "assertion을 약화해 PASS시키지 않는다"
원칙에 부합).

## 변이 검증

| | 변이 | 결과 |
|---|---|---|
| M129 | `create_payment()`의 `conn.execute("BEGIN IMMEDIATE")`를 주석 처리(락 제거, 레이스 재현) | **검출 O** ― `test_overage_payment_race`가 `paid_payments=3`으로 즉시 실패, 동시에 기존 `test_subscription_race`의 4개 assertion도 함께 실패(락이 SUBSCRIPTION도 같이 지키고 있었다는 뜻 — 두 결제 유형이 같은 락 지점을 공유하므로 당연한 결과) |

원복 후 `diff`로 원본과 바이트 단위 동일 확인, 전체 `test_race_conditions.py` 재통과.

## 검증

| 항목 | 결과 |
|---|---|
| `test_race_conditions.py` | 전체 PASS (강화된 overage 검사 포함) |
| `test_api_regression.py` | 전체 PASS |
| `test_subscription_policy.py` / `test_pipeline_integrity.py` / `test_schema_hygiene.py` / `test_bootstrap.py` | 전체 PASS |
| `python -m compileall` | exit 0 |
| 변이 잔여 | `api/v1/payments.py` 원본과 diff 0 (원복 확인) |
| 실 DB | QA 테스트 유저 데이터만 생성 후 각 스위트 cleanup에서 회수(잔여 0 확인) |

## 수정 파일

```
api/v1/payments.py          create_payment(): BEGIN IMMEDIATE를 provider 호출보다 먼저로 이동
test_race_conditions.py     test_overage_payment_race: 약한 assertion(>=1)을 강한 assertion(==1)으로 강화
docs/SPRINT129_OVERAGE_PAYMENT_LOCK_ORDER.md   신규 (본 문서)
```

**제품 정책 변경 0건.** 결제 금액/한도/환불 정책 어느 것도 바꾸지 않았다 — 기존
SUBSCRIPTION 수정(BUGS #20)과 동일한 패턴을 OVERAGE_USAGE에도 적용했을 뿐이다.

## SKIP (사용자/제품 결정 필요)

| 항목 | 이유 |
|---|---|
| 실제 PG 청구 후 우리 쪽만 롤백되는 경우의 자동 `cancel_payment()` 보상 호출 | 실제 PG 연동이 없는 지금은 재현·검증 불가능한 실패 모드 — 실연동 시점 작업 |
| `payment_logs`가 롤백과 함께 사라지는 것을 막기 위해 "실패/폐기된 시도도 별도 보존" | 원장 설계 변경(무엇을 영구 보존할지는 감사/컴플라이언스 정책 판단 필요) |
| Sprint 105~128의 SKIP 표 항목들 | 전부 승인/외부 조치 대기, 미해소 |

## 남은 Backlog

- **★★ 수집 파이프라인 스케줄러 등록** ― 2026-08-20에 검색 결과 0건이 된다(Sprint 112).
- 위 SKIP 표의 승인 대기 항목들
- 다음 Audit 영역: State Machine 전수, Transaction/Atomicity(payments.py 외 나머지),
  Server Action idempotency, Performance/N+1 (계속 진행)
