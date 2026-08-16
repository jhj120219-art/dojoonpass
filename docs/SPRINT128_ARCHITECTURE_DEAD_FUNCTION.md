# Sprint 128 ― 정정: "새로 찾은" 죽은 함수는 Sprint 72가 이미 찾아 처리해 둔 것이었다 (2026-08-15)

> 앞 Sprint: `docs/SPRINT127_SECURITY_HEADERS_APPLIED.md`
>
> **별도 파일 이유**: Sprint 100~127과 같다.

Sprint 127에서 "commit 제어 패턴이 다른 곳에도 일관되게 적용됐는가"를 확인하다가
`api/v1/subscriptions.py:get_active_subscription()`이 프로덕션 호출부 0곳(테스트만
참조)이라는 것을 찾고 처음엔 "새 발견"으로 문서를 썼다. **`docs/CURRENT_STATE.md`를
확인하지 않고 썼다** ― 다시 읽어 보니 Sprint 72(2026-08-13)가 이미 정확히 같은
것을 찾아 처리까지 끝내 둔 사안이었다. 초안을 그대로 남기지 않고 정정한다.

---

## 무엇을 잘못했나

이 세션 내내 "이전 Sprint 보고서를 그대로 믿지 않는다"는 원칙을 지키려 애썼는데,
정반대 방향의 실수를 했다 ― **아예 확인하지 않았다.** `docs/CURRENT_STATE.md`는
`git grep`으로 3초면 걸리는 파일인데, 코드에서 직접 재현되는 사실(호출부 0건)만
확인하고 "이미 알려진 사실인가"는 확인하지 않은 채 새 Sprint 문서를 만들었다.

## Sprint 72가 실제로 이미 한 것 (`docs/CURRENT_STATE.md` §6 "Dead Code 감사")

```
registry.py:get_entitled_subscription()    DB 미변경, 순수 계산   <- 실사용(등기부 게이트)
subscriptions.py:get_active_subscription() 동기화 후 판정         <- 호출 0곳(발견 당시)
```

발견에서 끝내지 않았다 ― **두 판정 함수가 같은 답을 내는지** `test_subscription_policy.py`
§9(`test_entitlement_judgments_agree`, 2026-08-13 신설)에 9개 상태 조합(만료 전/유예
안/유예 밖/무기한/PAUSED/CANCELLED/EXPIRED)으로 고정했고, 변이 검증까지 마쳤다
(동기화 판정에서 GRACE_PERIOD를 빼거나 순수 판정을 상태 그대로 믿게 바꾸면 각각
검출됨, 양방향 확인). **내가 방금 `grep`으로 찾은 "테스트 참조 2곳"이 바로 이
Sprint 72의 결과물이다** ― CURRENT_STATE.md의 "테스트 참조 0곳"은 그 정리가
있기 **전** 시점의 서술이고, 바로 다음 문단에서 그 정리 내용을 설명한다. 문서가
틀린 게 아니라 내가 앞부분만 읽고 뒷부분을 안 읽은 것이다.

## 지금 다시 확인한 것 (재검증, 새로 안 것은 없음)

- `get_active_subscription()` 프로덕션 호출부: 여전히 0건(Sprint 72 이후 새로
  생기지 않았다)
- `test_subscription_policy.py::test_entitlement_judgments_agree`: 이 세션의 전체
  스위트 실행(여러 차례)에서 계속 PASS ― Sprint 72의 정리가 지금도 유효하다
- 삭제 여부는 Sprint 72 때와 같은 이유로 여전히 승인 영역(`docs/CLAUDE.md`)

## 교훈 ― 이 문서에만 남긴다

"과거 Sprint 보고서를 맹신하지 않는다"는 "과거 Sprint 보고서를 안 본다"가 아니다.
**직접 재현한 사실**(호출부 0건)과 **이미 알려진 사실인지 여부**는 서로 다른
질문이고, 후자를 건너뛰면 이미 끝난 작업을 새 작업으로 착각해 문서만 늘린다.
다음부터 Architecture/Dead Code류 발견은 `docs/CURRENT_STATE.md` 전문(또는 최소
관련 키워드 grep)을 먼저 확인한 뒤에만 새 Sprint 문서를 쓴다.

## 검증

| 항목 | 결과 |
|---|---|
| `get_active_subscription` 프로덕션 호출부 재확인 | 0건 (Sprint 72와 동일) |
| `docs/CURRENT_STATE.md` 관련 서술 재확인 | §6에 이미 발견·처리 완료 기록 있음(2026-08-13 Sprint 72) |
| `test_entitlement_judgments_agree` 현재 통과 여부 | PASS (이 세션 전체 스위트 실행에서 지속 확인) |
| 코드 변경 | 없음 |

## 수정 파일

```
docs/SPRINT128_ARCHITECTURE_DEAD_FUNCTION.md   신규 (본 문서 ― 정정 기록. 최초 오해를 지우지 않고 그대로 남기고 정정 내용을 이어 붙였다)
```

## SKIP

없음(Sprint 72가 이미 처리 완료, 남은 승인 대기 항목도 Sprint 72 시점 그대로 ―
`get_active_subscription()` 삭제만 여전히 승인 영역).

## 남은 Backlog

- Sprint 105~127의 SKIP 표 항목들 (전부 승인/외부 조치 대기, 미해소)
