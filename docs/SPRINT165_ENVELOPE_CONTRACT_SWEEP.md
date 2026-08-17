# Sprint 165 — API 응답 계약 검사가 5개만 보고 있었다 (실제 대상 14개)

작성 2026-08-17. 모든 수치는 실행 결과다. **프로덕션 코드 변경 0.**

---

## 1. Architecture 감사: 응답 형태를 전수로 재 봤다

인증 필요 라우트는 `{success, data, error, meta, message}` 5키 envelope 를 쓴다는 것이
`docs/backend.md:569` 의 계약이다. 실제로 지켜지는지 **전 GET 엔드포인트를 두드려** 봤다.

```
envelope 형식 14개
   admin 7개(audit-logs / payments / payments-webhooks / registry-requests /
             registry/requests / subscriptions / users)
   favorites · recent-items · search-presets · registry-requests · payments
   plans · subscriptions/me

raw 형식 5개
   /                        레거시 3키 {success, data, message}
   /api/v1/stats            레거시 3키
   /api/v1/search           소스 근거 있음 — "인증 불필요 라우트라 envelope 를 쓰지 않는다"
   /api/v1/search/regions   같은 모듈·같은 근거 (search.py:436)
   /api/v1/document-stats   순수 dict, 소스에 명시적 근거 주석 없음(확인함)
```

raw 5개는 프런트가 **하나도 소비하지 않는다**(`src/` 전수 grep 0건). 운영/진단용이라
사용자 영향이 없고, 응답 형태를 바꾸는 것은 알 수 없는 소비자(운영 스크립트·모니터링)를
깨뜨릴 수 있는 API 계약 변경이라 **바꾸지 않았다.**

## 2. 진짜 문제는 검사 쪽이었다

`test_api_regression.py:test_response_envelope()` 는 **손으로 적은 5개 경로**만 본다.

```python
for path in ("/api/v1/favorites", "/api/v1/recent-items", "/api/v1/search-presets",
             "/api/v1/registry-requests", "/api/v1/payments"):
```

즉 envelope 를 쓰는 14개 중 **9개가 검사 밖**이었다 — admin 7개 전부와
`/api/v1/plans`, `/api/v1/subscriptions/me`. 새 엔드포인트가 다른 형태를 돌려줘도
아무도 모른다.

**Sprint 161 에서 고친 것과 똑같은 실패 모양이다.** 거기서는 경로 정규화 규칙 검사가
목록 기반이라 사본을 **세 번 연속** 놓쳤다. 여기도 같은 구조다.

## 3. 수정 — 목록을 예외 목록으로 뒤집었다

OpenAPI 에서 GET 라우트를 뽑아 전부 두드리고, raw 로 둘 것만 **이유와 함께** 예외에 적는다.

```python
RAW_BY_DESIGN = {
    "/api/v1/search":         "인증 불필요 라우트(소스에 근거 주석 있음)",
    "/api/v1/search/regions": "위와 같은 모듈·같은 근거",
    "/":                      "레거시 3키 헬스체크 응답",
    "/api/v1/stats":          "레거시 3키 운영 통계 응답",
    "/api/v1/document-stats": "운영 진단용 raw dict(소스에 근거 주석 없음)",
}
```

> **포함 목록과 예외 목록은 다르다.** 포함 목록은 새 엔드포인트를 조용히 무시한다(fail-open).
> 예외 목록은 새 엔드포인트를 기본으로 검사하고, 빼려면 이유를 적게 만든다(fail-safe).

4xx 응답은 건너뛴다 — 이 검사의 관심사는 **성공 응답의 형태**이고, 권한·검증 실패는
다른 검사들이 본다.

## 4. Mutation — 옛 검사로는 못 잡던 것을 잡는다

`/api/v1/subscriptions/me` 가 envelope 대신 raw dict 를 돌려주게 만들었다.
**이 엔드포인트는 옛 5개 목록에 없었다.**

```
exit=1 잡힘=True
   [FAIL] ★ 모든 GET 엔드포인트가 envelope 계약을 지킨다 -> ["/api/v1/subscriptions/me: ['plan']"]
원본 복원 확인 OK
```

옛 검사였다면 통과했을 변경이다. 이것이 이번 수정의 값어치다.

검사가 비어 있지 않다는 것도 함께 단언한다(`checked >= 10`) — 라우트 수집이 실패해
0개를 훑고 통과하는 상태를 막는다.

## 5. 검증 결과

```
파이썬 전체   통과 37 | 실패 1 | 건너뜀 3 | 판정없음 1   (단언 4,506건, 48.2s)
              실패 1건은 test_schema_hygiene.py — 미추적 파일 문제(`git add` 로만 풀린다)
프런트엔드    113 tests / 113 pass / 0 fail
tsc 0   eslint 0   compileall 0
```

## 6. 변경 파일

```
수정   test_api_regression.py   §17 에 전수 검사 + RAW_BY_DESIGN 예외 목록 추가
신규   docs/SPRINT165_ENVELOPE_CONTRACT_SWEEP.md
```

**프로덕션 코드 변경 0** — 계약 위반이 실제로는 하나도 없었다. 바꾼 것은 검사 범위뿐이다.

## 7. 기록만 하고 넘어간 것

- `/` 와 `/api/v1/stats` 는 5키가 아니라 **레거시 3키**(`error`/`meta` 없음)다.
  프런트 소비처가 0이라 지금 문제는 없지만 형태가 세 갈래인 것은 사실이다.
  통일은 API 계약 변경이라 승인 영역으로 남긴다.
- `/api/v1/document-stats` 는 raw 인 이유가 **소스 어디에도 적혀 있지 않다.**
  추측해서 쓰지 않고 "근거 주석 없음"이라고 예외 목록에 그대로 적었다.
