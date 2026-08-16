# Sprint 131 ― Test Gap 감사 결과 + CURRENT_STATE.md의 오래된 TODO 정정 (2026-08-15)

> 앞 Sprint: `docs/SPRINT130_MIGRATE_EXECUTE_N_PLUS_1.md`
>
> **별도 파일 이유**: Sprint 100~130과 같다. 이번엔 `docs/CURRENT_STATE.md` 본문을
> 직접 고쳤다(아래 "왜 이번엔 CURRENT_STATE.md를 직접 고쳤는가" 참고) — 새 Sprint
> 파일은 그 변경을 기록하는 용도로만 쓴다.

## 1. Test Gap 감사 ― 실측 커버리지

`/goal`의 Test Gap Audit 우선순위를 따라 `coverage.py`로 `api/`, `storage/`를
전수 측정했다(`test_db.py`/`test_docs.py`/`test_docs2.py`는 기존 관례대로 제외 —
`ALLOW_LIVE_CRAWL=1` 없이는 스스로 SKIP하는 실크롤 테스트).

```
TOTAL   2257 stmts, 78 miss, 97% coverage
```

가장 낮은 파일 3개(`storage/migrate_v4_1.py` 90%, `storage/database.py` 91%,
`storage/migrations/run_migrations.py` 94%)의 미달성 라인을 직접 읽었다 — 전부
`except Exception:` 방어 분기 또는 `if __name__ == "__main__":` CLI 진입점이었다.
실제 비즈니스 로직 공백은 없었다.

**후보 하나를 잘못 짚을 뻔했다**: `storage/database.py:query()`가 0% 커버리지로
보여 죽은 코드로 의심했으나, `docs/BUGS.md` #83(2026-08-13)을 먼저 확인하니 이미
"유일한 호출자는 `ALLOW_LIVE_CRAWL` 가드로 회귀에서 제외된 `test_db.py`"라고
기록돼 있었다 — 내가 커버리지 측정에서 그 파일을 **의도적으로 제외**했기 때문에
0%로 보인 것뿐이다. 새 발견으로 쓰지 않았다(이번 세션의 "먼저 과거 기록과
대조한다" 원칙이 정확히 막아 준 오탐 사례).

**결론: Test Gap 없음.** 97% 커버리지, 남은 3%는 방어 분기/CLI 진입점.

## 2. Documentation Drift ― `docs/CURRENT_STATE.md`의 미완료 TODO가 실제로는 끝나 있었다

같은 감사 중 `docs/CURRENT_STATE.md`를 훑다가 두 곳에서 같은 오래된 서술을 발견했다:

- **338행**(이미 ☑ 처리된 "Payment Flow Migration" 항목 안): "`cancel_payment`/
  `handle_webhook`은 여전히 미연결"
- **396행**(다음 할 일 목록, □ 미완료 표시): "환불(`cancel_payment`)/Webhook
  (`handle_webhook`) 엔드포인트 신규 구현 — 여전히 미연결"

두 문장 모두 이 문서 초기(2026-08-06/07 무렵, 주변 항목 날짜로 추정) 시점 서술이다.
그런데 이 세션이 Sprint 129에서 직접 코드를 읽으며 이미 확인한 사실과 어긋난다:

```
api/v1/payments.py:557   refund_payment() 안에서 provider.cancel_payment() 호출
api/v1/payments.py:693   receive_payment_webhook() 안에서 provider.handle_webhook() 호출
```

두 경로 다 `docs/BUGS.md`/Sprint 문서로 추적된다 — **2026-08-11 Sprint 52**가
`receive_payment_webhook()`(Webhook 수신)와 환불 경로를 실제로 연결했다(Sprint 52
자신의 코드 주석: "인프라는 Sprint 28~27에 전부 준비돼 있었는데 호출부가 없어
한 번도 실행되지 않았다... 여기서 연결한다"). 396행의 TODO는 그 작업이 끝난
뒤로도 계속 미완료(□)로 남아 있었다.

### 왜 이게 문제인가

이 세션 초반에 실제로 같은 함정에 거의 빠질 뻔했다(Sprint 128의
`get_active_subscription` 중복 발견, Sprint 122 vs Sprint 57 대조). 이번 것은 그
반대 방향이다 — **이미 끝난 일이 "할 일"로 남아 있으면**, 다음 세션(또는 이
세션이라도 이 문서만 보고 판단했다면)이 "아, cancel_payment가 아직 연결 안
됐구나"라고 믿고 **이미 있는 기능을 처음부터 다시 구현**하려 들 수 있다. 실제로
이번 세션이 Sprint 129에서 결제 트랜잭션 경로를 감사하며 코드를 직접 읽지 않았다면
이 오탐을 그대로 믿었을 것이다.

### 고친 것

`docs/CURRENT_STATE.md` 396행을 이 문서의 기존 관례(취소선 + "→ **날짜 완료**:
설명")로 완료 처리하고, 338행의 괄호 안 서술도 "이 시점엔 미연결이었으나
Sprint 52에서 연결 완료"로 정정했다(문장을 지우지 않고 이어 붙이는 이 저장소
관례 그대로).

### 왜 이번엔 CURRENT_STATE.md를 직접 고쳤는가

이전 Sprint 문서들은 "`docs/BUGS.md`/`docs/CURRENT_STATE.md`는 다른 세션의 편집
대상이라 충돌을 피했다"고 명시하며 새 Sprint 파일로만 기록해 왔다. 그런데 그
문서 자체를 다시 읽어 보면, 386/390/394/406행처럼 **완료된 TODO를 취소선 +
"→ 날짜 완료"로 그 자리에서 직접 고치는 것이 이 문서의 원래 관례**다(여러 세션에
걸쳐 수십 건 그렇게 고쳐져 있다). "충돌을 피한다"는 원칙은 **같은 세션 안에서
새 Sprint 문서를 그 파일과 별도로 만드는 이유**였지, 완료 표시를 절대 하지
말라는 뜻이 아니었다 — 오히려 완료된 TODO를 그대로 방치하면 이번 항목처럼
다음 세션이 오탐(중복 구현 시도)을 일으킬 위험이 더 크다고 판단했다. 이 판단
자체를 이 문서에 남긴다.

## 검증

| 항목 | 결과 |
|---|---|
| 코드 변경 | 0건 (문서만) |
| `docs/CURRENT_STATE.md` 편집 | 338/396행, 취소선+완료 표기 방식으로 기존 서술을 지우지 않고 정정 |
| Test Gap 재확인 | 97% 커버리지, 실제 로직 공백 없음(위 §1) |
| 회귀 스위트 | 문서 전용 변경이라 재실행 불필요 — Sprint 130 종료 시점 전체 PASS 상태 유지(직전 커밋 없음) |

## 수정 파일

```
docs/CURRENT_STATE.md   338/396행 정정(취소선+완료 표기, 서술 보존)
docs/SPRINT131_DOC_DRIFT_PAYMENT_FLOW.md   신규 (본 문서)
```

## SKIP

없음.

## 남은 Backlog

- **★★ 수집 파이프라인 스케줄러 등록** ― 2026-08-20에 검색 결과 0건이 된다(Sprint 112).
- Sprint 105~130 SKIP 표의 승인 대기 항목들
- 다음 Audit 영역: Architecture, Technical Debt, TODO/FIXME/HACK/Dead Code 2차 전수,
  Release Audit (계속 진행)
