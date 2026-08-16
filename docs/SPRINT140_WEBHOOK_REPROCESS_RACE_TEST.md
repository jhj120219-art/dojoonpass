# Sprint 140 ― Webhook 재처리 레이스: 실제 스레드 테스트 신설 + 자체 잔해 청소 결함 발견 (2026-08-16)

> 앞 Sprint: `docs/SPRINT139_ROADMAP_DRIFT.md`
>
> **별도 파일 이유**: Sprint 100~139와 같다.

`/goal`이 최우선으로 지정한 Transaction/Concurrency Audit — 결제/구독/등기부/
credit/registry_requests의 동시성 경계를 다시 훑었다.

## 1. 발견 ― Webhook 재처리만 "실제 스레드 실행" 검증이 없었다

`test_race_conditions.py`의 기존 테스트 목록을 전부 나열해 대조했다:

```
실제 스레드 레이스 재현              구조 검사(소스 텍스트만 확인)
─────────────────────────────       ─────────────────────────────
registry_free_limit_race            toctou_guard_is_structural
overage_payment_race                refund_guard_is_structural
subscription_race                   webhook_reprocess_guard_is_structural  <- 이것만 짝이 없다
admin_registry_status_race          subscription_status_guard_is_structural
admin_refund_race                   search_preset_cap_guard_is_structural
admin_subscription_status_race
registry_credit_adjust_race
search_preset_cap_race
```

환불/등기부/구독상태/크레딧/검색조건저장은 전부 "실제 스레드로 재현" +
"소스에 가드가 있는지" 두 겹으로 검증되는데, **Webhook 재처리
(`admin_reprocess_webhook` → `reprocess_webhook()`)만 구조 검사 하나뿐**이었다
(전체 파일 `threading` 사용처 grep으로 확인). 구조 검사는 "`BEGIN IMMEDIATE`라는
문자열이 소스에 있다"만 보장하지, 문 위치가 바뀌거나 락 범위가 좁아져도
같은 문자열이 남아 있으면 통과한다 — 실제 동시 실행에서 직렬화가 되는지는
아무도 실행해 본 적이 없었다.

`docs/CURRENT_STATE.md`/`docs/BUGS.md`에서 "webhook reprocess race" 관련
기록을 찾았으나 **이미 고쳐진 결함으로 존재하지는 않았다** — Sprint 39
언저리에 `BEGIN IMMEDIATE`를 다른 상태 전이 경로들과 함께 이 경로에도
적용했다는 기록만 있고, 그 방어를 실제 스레드로 검증한 적은 없었다.
중복이 아니라 순수한 테스트 공백이다.

## 2. 고친 것 ― 실제 스레드 레이스 테스트 신설

`test_race_conditions.py`에 `test_admin_webhook_reprocess_race()` 신설:
PAID 상태 결제 1건에 딸린 Webhook 수신 기록(RECEIVED, `PAYMENT_REFUNDED`
이벤트)을 만들고, 재처리 요청 3개를 `threading.Barrier`로 정확히 동시에
보낸다. 다른 admin race 테스트들과 같은 패턴(같은 asserts 스타일, 같은
super-admin 헤더 확보 방식)을 그대로 따랐다.

## 3. 변이 검증 중 실제로 결함(내 테스트 자신의 정리 공백)을 하나 더 찾았다

`reprocess_webhook()`의 `BEGIN IMMEDIATE`를 제거하는 변이를 걸어 새 테스트가
실제로 잡는지 확인했다. **잡았다** — 그런데 예상과 다른 모양으로 잡혔다.
락이 없어도 `_apply_webhook_event()`의 조건부 UPDATE(`WHERE id=? AND status=?`)가
한 겹 더 있어서 결제 상태 자체가 이중 적용되지는 않았다. 대신 레이스에서 진
두 스레드가 `webhook_reprocess_block_reason()`에서 400으로 미리 걸러지는
대신, `_apply_webhook_event()`까지 들어가 `result="SKIPPED"`로 **200**을
받았다 — 계약 위반(패자는 400을 받아야 하는데 200을 받음)이라 내 assertion이
정확히 이 차이를 검출했다.

**그런데 이 SKIPPED 분기가 `payment_id` 없이 `target_type='PAYMENT_WEBHOOK'`으로
감사 로그를 남긴다는 것을 그때 알았다** — 내 테스트의 `cleanup()`은
`target_type='PAYMENT'`(정상 APPLIED 분기)만 정리하도록 짜여 있었다. 변이를
원복한 뒤 `test_api_regression.py`를 재실행하니 `[FAIL] no dangling audit
rows left: 2 (expected 0)`으로 걸렸다 — 변이 실행 중 생긴 감사 로그 2건이
내 정리 로직의 사각지대에 남은 것이다. 실 DB를 직접 조회해 원인을 확정하고
(`target_type='PAYMENT_WEBHOOK', target_id=1218`인 잔해 2건 확인) 즉시 삭제,
그리고 `cleanup()`에 이 분기(`target_type='PAYMENT_WEBHOOK'`)도 정리하도록
보강했다 — 이 분기는 정상 코드에서는 도달하지 않지만(레이스 패자는
`webhook_reprocess_block_reason()`에서 이미 막혀 `record_audit()`까지 가지
않는다), 변이 검증처럼 그 방어를 일부러 깨면 실제로 생기는 모양이라 이 세션
자신의 "테스트 잔해가 다음 실행에 오염을 남기지 않는다"는 원칙에 맞춰
방어적으로 정리 로직을 넓혔다.

## 4. 동일 패턴 전수 검색

다른 "구조 검사만 있는" 항목들(`toctou_guard_is_structural`,
`refund_guard_is_structural`, `subscription_status_guard_is_structural`,
`search_preset_cap_guard_is_structural`)은 전부 **같은 이름의 실제 스레드
테스트가 이미 존재한다**(위 §1의 좌측 목록) — Webhook 재처리만 짝이 없었다.
전수 검색 결과 이 공백은 하나뿐이었다.

## 변이 검증

| | 변이 | 결과 |
|---|---|---|
| M140 | `reprocess_webhook()`의 `conn.execute("BEGIN IMMEDIATE")` 제거 | **검출 O** ― 신설 8개 검사 중 "나머지 2건은 400" 등 2건 실패, 기존 구조 검사도 함께 실패(이중 확인) |

원복 후 `diff`로 원본과 바이트 단위 동일 확인.

## 검증

| 항목 | 결과 |
|---|---|
| `test_race_conditions.py` | 전체 PASS(신설 8검사 포함) |
| `test_api_regression.py`(정리 로직 보강 후 재확인) | 전체 PASS — "no dangling audit rows left" 포함 전부 통과 |
| `python -m compileall` | exit 0 |
| `npx tsc --noEmit` | exit 0 |
| `npm run lint` | 0 issues |
| 변이 잔여 | `api/v1/payments.py` 원본과 diff 0(원복 확인) |
| 실 DB 잔해 | 변이 실행 중 생긴 감사 로그 2건 직접 확인 후 삭제, 이후 재발 방지 코드 반영 |

## 수정 파일

```
test_race_conditions.py   test_admin_webhook_reprocess_race() 신설(§10) +
                           cleanup()에 PAYMENT_WEBHOOK-target 감사 로그 정리 보강
docs/SPRINT140_WEBHOOK_REPROCESS_RACE_TEST.md   신규 (본 문서)
```

**제품 코드 변경 0건.** `api/v1/payments.py`/`api/v1/admin.py`는 변이 검증을
위해 일시적으로만 수정했고 전부 원복했다 — 기존 `BEGIN IMMEDIATE` 방어는
이미 올바르게 동작하고 있었다(회귀 테스트로 고정만 함).

## SKIP

없음.

## 남은 Backlog

- **★★ 수집 파이프라인 스케줄러 등록** ― 2026-08-20에 검색 결과 0건이 된다(Sprint 112, 3일 남음).
- Sprint 105~139 SKIP 표의 나머지 승인 대기 항목들
- 다음 Audit 영역: Release Readiness, TODO/FIXME/HACK 2차, End-to-End Beta
  Journey(추가 각도), Documentation Drift(decision-log.md/TEST_PLAN.md 미확인분) (계속 진행)
