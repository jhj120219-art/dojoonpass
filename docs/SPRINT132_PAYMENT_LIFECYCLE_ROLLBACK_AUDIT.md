# Sprint 132 ― 결제 Lifecycle 전수 감사: "Provider 성공 + DB 실패" 회귀 테스트 신설 (2026-08-16)

> 앞 Sprint: `docs/SPRINT131_DOC_DRIFT_PAYMENT_FLOW.md`
>
> **별도 파일 이유**: Sprint 100~131과 같다.

`/goal`이 최우선으로 지정한 "SUBSCRIPTION vs OVERAGE_USAGE의 Lock/Provider 호출 순서
차이"부터 먼저 현재 코드와 대조했다.

## 1. 최우선 지시 사항 재확인 ― 이미 Sprint 129에서 해소됨(중복 아님, 재검증만)

```
api/v1/payments.py:381   conn.execute("BEGIN IMMEDIATE")  <- SUBSCRIPTION/OVERAGE_USAGE
                                                               분기 이전, 무조건 실행
```

`docs/SPRINT129_OVERAGE_PAYMENT_LOCK_ORDER.md`가 바로 이 문제(OVERAGE_USAGE가 락보다
먼저 provider를 호출하던 것)를 이미 찾아 고쳤고, `test_race_conditions.py::
test_overage_payment_race`를 "payments 행 ≥1" → "정확히 1"로 강화해 뒀다. 지금
코드를 다시 읽고 테스트를 재실행해 여전히 유효함을 재확인했다(아래 검증 표) ―
**새 Sprint로 다시 만들지 않는다.** 대신 `/goal`이 요구한 "결제 Lifecycle 전체
전수 감사"의 나머지(REFUND/CANCEL/WEBHOOK/RETRY, 그리고 "Provider 성공 + DB 실패"
같은 아직 테스트되지 않은 개별 실패 모드)로 이어서 진행한다.

## 2. 전수 감사에서 실제로 비어 있던 지점 ― "Provider 성공 + 그 이후 DB 실패"

`/goal`의 결제 Lifecycle 체크리스트 18개 항목을 하나씩 기존 테스트와 대조했다.
대부분(중복 결제, 동시 결제, 금액 불일치, 중복 webhook, 이미 완료된 상태 재요청
등)은 이미 `test_api_regression.py`/`test_race_conditions.py`가 검사하고 있었다.
**#7 "Provider 성공 + DB 실패"만 어느 테스트에도 없었다** — 기존 "결제 실패 재시도"
테스트(BUGS #20 강화분)는 **provider가 거절하는** 경우만 재현했지, "provider는
승인했는데 그 뒤 우리 코드가 죽는" 반대 방향은 다룬 적이 없었다.

### 재현

`api/v1/payments.py:create_payment()`에서 `create_subscription()`을 강제로
`RuntimeError`를 던지도록 몽키패치해(MockProvider는 실패를 만들지 않으므로 이
방법이 유일한 재현 경로) 확인했다. 같은 트랜잭션(`BEGIN IMMEDIATE` ~
`except Exception: conn.rollback(); raise`) 안에 있으므로:

- 예외가 조용히 삼켜지지 않고 그대로 전파된다(요청이 거짓 성공을 보고하지 않는다)
- `subscriptions`/`payments`/`payment_logs` 전부 고아 행 0건(전부 롤백됨 —
  provider가 승인한 흔적까지 함께 사라진다는 뜻이지만, 지금은 MockProvider라
  실제 청구가 없어 무해하다. 실제 청구가 있었다면 Sprint 129가 이미 이 위험을
  SKIP 항목으로 남겨 뒀다: `docs/SPRINT129_OVERAGE_PAYMENT_LOCK_ORDER.md`
  "SKIP" 표 첫 줄)
- 이어지는 재시도는 정상 성공한다(예외가 커넥션/트랜잭션 상태를 오염시키지 않는다)

**결론: 결함 없음.** 기존 `except Exception: conn.rollback(); raise` 패턴이
정확히 이 실패 모드를 이미 막고 있었다 — 검증되지 않았을 뿐 결함은 아니었다.
이번에 한 일은 그 사실을 **회귀 테스트로 고정**한 것이다.

### 회귀 테스트

`test_api_regression.py` §8(SUBSCRIPTION 결제) — 기존 "결제 실패 재시도" 검사
바로 뒤에 6개 검사 신설: 예외 전파 확인 1건 + 고아 행 0건 확인 3건(subscriptions/
payments/payment_logs) + 재시도 성공 확인 2건.

## 3. 동일 패턴 전수 검색 ― REFUND / WEBHOOK RETRY 경로도 같은 보호를 받는가

`/goal`이 명시한 "한 곳 고치면 동일 패턴을 전수 검색한다"에 따라, 같은
"provider 성공 + DB 실패" 위험이 있는 다른 결제 경로를 코드로 추적했다.

| 경로 | Provider 호출 | 그 뒤 실패 시 처리 | 결론 |
|---|---|---|---|
| `create_payment()`(SUBSCRIPTION/OVERAGE_USAGE) | `create_payment_record()` | 함수 자체가 `except Exception: conn.rollback(); raise` | 보호됨(위 §2가 실측 확인) |
| `refund_payment()`(→ `provider.cancel_payment()`) | `admin.py:admin_refund_payment()`가 `except Exception: conn.rollback(); raise`로 감쌈(871~873행) — `refund_payment()` 자신은 래핑하지 않지만 유일한 호출부가 감싼다 | 보호됨(코드 추적으로 확인, `refund_payment()`의 유일한 프로덕션 호출부가 `admin_refund_payment()` 하나뿐임을 Sprint 129에서 이미 grep 확인) |
| `receive_payment_webhook()`(→ `provider.handle_webhook()`) | 함수 자체가 `except Exception: conn.rollback(); raise HTTPException(500)` | 보호됨 — 단, **미검증 예외가 나면 웹훅 수신 기록(`payment_webhooks` 행) 자체가 롤백으로 사라진다**(아래 §4) |
| `admin_reprocess_webhook()`(재처리, 새 provider 호출 없음 — 서명 재검증도 안 함) | 없음(`reprocess_webhook()`이 저장된 payload만 재해석) | `admin.py` 801/804/825행에서 `BEGIN IMMEDIATE` + `except: conn.rollback()` 패턴 확인 | 보호됨(provider 재호출이 없어 이 문제 자체가 해당 없음) |

**결론: 4개 경로 전부 같은 방어 패턴(`except Exception: conn.rollback(); raise`
+ 단일 트랜잭션)을 쓰고 있고, 전부 안전하다.** 새로 고칠 것은 없었다.

## 4. 파생 관찰 ― 웹훅 처리 중 미검증 예외는 수신 기록 자체를 지운다(Sprint 129와 같은 근본 원인, 새 SKIP 아님)

§3에서 `receive_payment_webhook()`을 추적하며 확인한 것: `record_webhook()`
(INSERT)과 `_apply_webhook_event()`(상태 반영)이 **같은 트랜잭션**에 있다.
**예상된** 비적용 사유(알 수 없는 event_type, 대응 결제 없음, 상태머신이 막는
전이, 이미 같은 상태)는 전부 `skip()` → `mark_webhook_processed(..., IGNORED)`로
**커밋**되어 `admin_reprocess_webhook()`이 나중에 재처리할 수 있다 — 이건
의도된 설계고 문제가 아니다.

문제가 될 수 있는 건 **예상 밖의** 예외(코드 버그, `provider.handle_webhook()`
자체가 던지는 예외 등)뿐이다 — 이때는 바깥쪽 `except Exception`이 잡아 **웹훅
수신 기록까지 통째로 롤백**한다. `event_id` UNIQUE 중복 검사도 커밋된 행 기준이라,
PG가 같은 이벤트를 재전송하면 "새 이벤트"로 다시 시도된다(일시적 장애라면 오히려
바람직한 자동 재시도). 하지만 **원인이 지속적인 버그라면** DB에는 아무 흔적도
남지 않고 로그(회전됨)만 남는다 — `docs/SPRINT129_OVERAGE_PAYMENT_LOCK_ORDER.md`의
SKIP 표가 이미 "결제 레이스에서 패자의 `payment_logs`가 롤백과 함께 사라지는"
문제로 지적한 것과 **정확히 같은 근본 원인**(같은 트랜잭션에 "저장"과 "처리 성공
판정"을 묶어 두면, 처리 실패가 저장 자체를 지운다)이 웹훅 경로에도 그대로
적용된다는 것을 확인했을 뿐, 새로운 결함은 아니다. 별도 SKIP 항목을 추가하지
않고 기존 SKIP 항목이 이 범위까지 포함한다고 이 문서에 남긴다.

## 변이 검증

| | 변이 | 결과 |
|---|---|---|
| M132a | `create_payment()`의 바깥쪽 `except Exception: conn.rollback(); raise`에서 `conn.rollback()` 제거 | **검출 안 됨(그러나 다른 기존 검사가 검출)** ― 새 6개 검사는 전부 그대로 PASS했다(SQLite가 커밋되지 않은 트랜잭션을 `conn.close()` 시점에 자동 폐기하므로 관측 가능한 차이가 없었다). 대신 이미 존재하던 별도의 Mock 기반 유닛 검사("실패 시 롤백한다")가 이 제거를 즉시 잡아냈다(`rollback이 호출되지 않았다`) — 새 검사가 이 특정 변이에는 둔감하다는 것을 정직하게 기록한다. |
| M132b | `create_payment_record()` 직후에 **조기 `conn.commit()`**을 삽입(부분 커밋 재현 — 더 현실적인 결함 모양) | **검출 O** ― 새로 추가한 "고아 행 0건" 3개 검사가 즉시 실패(`payment=1`, `payment_logs=3`, 기존 무관 검사 2개도 연쇄로 실패) — 새 검사가 **실제로 재현 가능한 결함 모양**(부분 커밋)에는 정확히 반응함을 확인했다. |

두 변이 모두 원복 후 `diff`로 원본과 바이트 단위 동일 확인, 전체 스위트 재통과.

M132a의 "검출 안 됨"을 숨기지 않고 그대로 남기는 이유: 이 세션의 "테스트를
약화하거나 assertion을 삭제해서 PASS시키지 않는다"는 원칙은 "변이 검증 결과를
유리하게만 보고하지 않는다"까지 포함한다고 판단했다. `conn.rollback()` 명시적
호출 자체는 SQLite의 close-시 자동폐기 안전망과 중복 방어라 관측 가능한 차이가
없는 것이 오히려 **더 견고하다는 증거**이기도 하다 — 하지만 정직하게 "이 검사가
못 잡는 변이도 있다"고 남겨야 다음 세션이 잘못된 확신을 갖지 않는다.

## 검증

| 항목 | 결과 |
|---|---|
| `test_api_regression.py` | 전체 PASS(신규 6검사 포함) |
| `test_race_conditions.py` | 전체 PASS(Sprint 129 검사 재확인) |
| `python -m compileall` | exit 0 |
| 변이 잔여 | `api/v1/payments.py` 원본과 diff 0(양쪽 다 원복 확인) |
| 실 DB | QA 테스트 유저만 생성, 각 스위트 cleanup에서 회수 |

## 수정 파일

```
test_api_regression.py   §8에 "Provider 성공 + DB 실패" 시나리오 6검사 신설
docs/SPRINT132_PAYMENT_LIFECYCLE_ROLLBACK_AUDIT.md   신규 (본 문서)
```

**제품 코드 변경 0건.** 기존 방어(`except Exception: conn.rollback(); raise`)가
이미 올바르게 동작하고 있음을 확인 + 회귀 테스트로 고정했을 뿐이다.

## SKIP

없음(신규 SKIP 없음 — §4는 기존 Sprint 129 SKIP 항목의 적용 범위를 넓혀 확인한
것으로, 별도 항목이 아니다).

## 남은 Backlog

- **★★ 수집 파이프라인 스케줄러 등록** ― 2026-08-20에 검색 결과 0건이 된다(Sprint 112, 4일 남음).
- Sprint 105~131 SKIP 표의 승인 대기 항목들
- 다음 Audit 영역: Failure Recovery(프로세스 크래시/재시작 복구), Webhook 재시도
  경계값, Frontend Idempotency, Performance/N+1 나머지 (계속 진행)
