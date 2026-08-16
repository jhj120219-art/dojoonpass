# Sprint 143 ― `docs/decision-log.md`의 오래된 항목 3건 정정 (2026-08-16)

> 앞 Sprint: `docs/SPRINT142_DOC_WORKER_CONCURRENT_INSTANCE_LOCK.md`
>
> **별도 파일 이유**: Sprint 100~142와 같다.

Documentation Drift Audit — 이 세션이 아직 대조하지 않았던
`docs/decision-log.md`(2026-08-07 시점 기록 다수 포함)를 실제 코드/DB와 대조했다.

## 발견 및 정정 (3건)

1. **"보류(진행하지 않음)" 목록의 Selenium** ― 2026-08-07 시점엔 정확했으나
   2026-08-12 Sprint 61에 실제로 설치·승인됐다(이 세션도 Sprint 137/142에서
   `import selenium` 성공을 직접 확인했다). 목록에서 취소선 처리하고 정정
   추가, 나머지 항목(Sentry/Rate Limit/Monitoring 등)은 재확인 결과 여전히
   보류 상태 유지(스테일 아님).
2. **"결제 로그 구조 선구축" 항목의 "수신 엔드포인트는 여전히 없다"** ―
   2026-08-11 Sprint 52에 `receive_payment_webhook()`으로 실제 연결됐다
   (이 세션이 Sprint 129/132/140에서 이 엔드포인트를 직접 감사·테스트했다).
3. **`BETA_EARLYBIRD` 플랜 이관 관련 "현재 운영 DB에 해당 row가 있는지는
   별도 확인 필요"** ― 실제로 확인해 봤다: `SELECT DISTINCT plan FROM
   subscriptions`가 빈 결과(현재 어떤 plan 값의 구독 행도 없음). 이관
   **방침**(정책 결정)은 여전히 미정이지만, "확인이 필요하다"던 것 자체는
   이제 확인 완료 — 지금 당장 이관할 데이터가 없다는 사실을 실측으로 남겼다.

## 왜 이게 중요한가

Sprint 131/135/139와 같은 종류의 위험이다 — 이미 끝난 일이 "아직 안 한 일"로
문서에 남아 있으면, 다음 세션이 이미 있는 기능(Webhook 수신, Selenium 설치)을
없는 것으로 오판해 중복 작업을 시도할 수 있다. 특히 결제 로그 구조 문서는
바로 이 세션이 Sprint 129/132/140에서 Webhook 관련 깊은 감사를 3차례나
수행한 영역이라, 만약 이 문서만 먼저 읽고 코드를 확인하지 않았다면 "수신
엔드포인트가 없다"는 틀린 전제로 작업을 시작했을 수도 있었다.

## 검증

| 항목 | 결과 |
|---|---|
| 코드 변경 | 0건(문서만) |
| `subscriptions.plan` 실측 | `SELECT DISTINCT plan` 빈 결과 확인 |
| `docs/decision-log.md` 편집 | 3곳, 전부 취소선/보존 + 정정 내용 추가(기존 서술 보존) |
| `test_api_regression.py` | 전체 PASS(문서 전용 변경이라 영향 없음, 재확인 완료) |

## 수정 파일

```
docs/decision-log.md              3개 항목 정정(Selenium/webhook 엔드포인트/BETA_EARLYBIRD 확인)
docs/SPRINT143_DECISION_LOG_DRIFT.md   신규 (본 문서)
```

## SKIP

없음.

## 남은 Backlog

- **★★★ 최우선**: `DojoonPass-DocWorker`/`DojoonPass-PriorityRefresh` 스케줄 등록
  (Sprint 141/142)
- `BETA_EARLYBIRD` 플랜 이관 **방침** 자체는 여전히 제품 결정 필요(승인 영역,
  단 지금 데이터는 없음)
- Sprint 105~142 SKIP 표의 나머지 승인 대기 항목들
- 다음 Audit 영역: TODO/FIXME/HACK 2차 종합, Dead Code 2차 종합, Release
  Readiness 종합, Transaction/Concurrency 추가 심층(등기부/크레딧 경계) (계속 진행)
