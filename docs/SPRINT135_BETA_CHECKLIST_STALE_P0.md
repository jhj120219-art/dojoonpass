# Sprint 135 ― `BETA_RELEASE_CHECKLIST.md`의 P0 항목이 108개 Sprint만큼 뒤처져 있었다 (2026-08-16)

> 앞 Sprint: `docs/SPRINT134_PERFORMANCE_SCALE_MEASUREMENT.md`
>
> **별도 파일 이유**: Sprint 100~134와 같다.

Documentation Drift Audit(`/goal` 체크리스트에 명시된 문서 목록 중 이 세션이
아직 안 본 `docs/BETA_RELEASE_CHECKLIST.md`)를 확인했다.

## 발견

`Last Updated: 2026-08-07 (Sprint 28)` ― CURRENT_STATE.md는 Sprint 99(2026-08-13)까지,
Sprint 100 이후는 개별 `docs/SPRINT1XX_*.md`로 계속 갱신돼 왔는데 이 파일만
Sprint 28 이후 손대지 않은 채 방치돼 있었다. 이 문서 자신이 "이미 해소된
병목은 다시 올리지 않는다"를 원칙으로 명시하는데, 정작 자신은 그 원칙을 어기고
있었다.

가장 심각한 것: **P0-2("`ADMIN_API_KEY`/`SUPER_ADMIN_API_KEY` 미설정 확정",
2026-08-13 Sprint 78 실측 기준)가 더 이상 사실이 아니었다.**

### 재검증(비밀값 열람 없이, Sprint 78과 같은 방법)

```
os.getenv() truthy 여부   ADMIN_API_KEY        True   (2026-08-13엔 이름 자체가 없었다)
                          SUPER_ADMIN_API_KEY  True
                          PAYMENT_WEBHOOK_SECRET False (이것만 여전히 비어 있다)

실서버 응답(키 없이 호출)  /admin/users /admin/payments /admin/subscriptions /admin/audit-logs
                          전부 403 "권한이 없습니다"
                          (2026-08-13엔 전부 500 "관리자 키 미설정"이었다)
```

`.env`가 Sprint 78과 지금 사이 어딘가에서 채워졌다 — 이 세션이 채운 것은
아니다(`.env` 수정은 승인 영역이라 이 세션은 손대지 않았다, git diff에도 없음).
언제/누가 채웠는지는 이 세션 범위 밖이지만, **문서가 그 변화를 반영하지 못해
"Admin API 전체 사용 불가"라는, 지금은 틀린 P0 차단 사유를 계속 보여주고
있었다.** 실제로 남은 문제는 "Admin 화면(UI)이 없다"는 P1뿐이다.

`PAYMENT_WEBHOOK_SECRET`은 여전히 비어 있어 Webhook 수신은 계속 fail-closed(401)
— 이 부분은 Sprint 78 기록이 지금도 정확하므로 그대로 유지했다.

## 왜 이게 중요한가

이 문서는 "지금 출시를 막는 것"을 보여주는 것이 유일한 목적이다. 실제로는
해소된 P0 항목이 계속 P0로 남아 있으면, 이 문서를 근거로 판단하는 사람(사람이든
다음 세션이든)이 "Admin 기능이 아직 못 쓴다"고 오판해 이미 끝난 작업을 다시
하려 들거나, 반대로 실제로 남은 문제(Webhook Secret, KG이니시스, Admin UI)의
우선순위를 놓칠 수 있다 — Sprint 133/134가 이미 다뤄 온 "오래된 기록이 잘못된
확신을 준다"는 것과 같은 종류의 위험이 이번엔 릴리즈 판단 문서에서 나타났다.

## 고친 것

`docs/BETA_RELEASE_CHECKLIST.md`:

1. 문서 최상단에 2026-08-16 정정 안내 신설 — 이 파일이 Sprint 28 이후 갱신되지
   않았음을 명시하고, 현재 상태를 보려면 `CURRENT_STATE.md` + 
   `SPRINT99_RELEASE_READINESS_AUDIT.md` + `SPRINT100~134` 개별 파일을 먼저
   보라고 안내(전면 재작성은 이 세션 범위를 넘어 하지 않음 — P0/P1/P2 전 항목을
   하나하나 재검증해야 하는 별도 규모의 작업이라 섣불리 손대지 않았다)
2. P0-2 제목에 취소선 + "2026-08-16 재실측: 지금은 둘 다 설정돼 있다" 추가,
   위 재검증 내용을 그대로 삽입. **기존 Sprint 78 기록은 지우지 않고
   `<details>`로 접어서 보존**(이 저장소의 "문장을 지우지 않고 정정만 덧붙인다"
   관례를 유지하되, 정정된 옛 기록이 눈에 계속 띄어 다시 헷갈리지 않도록 접어 둠
   — 기존 취소선 관례와 같은 목적, 표현만 이 경우에 맞게 골랐다)
3. "도메인별 현황" 요약 표의 "관리자" 행도 같은 내용으로 정정(P0/P1 → P1만)

## 검증

| 항목 | 결과 |
|---|---|
| `os.getenv()` truthy 확인 | ADMIN_API_KEY=True, SUPER_ADMIN_API_KEY=True, PAYMENT_WEBHOOK_SECRET=False (비밀값 자체는 열람하지 않음) |
| 실서버 응답(키 없이) | 4개 Admin 엔드포인트 전부 403(이전 500에서 전환 확인) |
| `test_api_regression.py` | 전체 PASS(문서 전용 변경이라 영향 없음, 재확인 완료) |
| `.env` 수정 여부 | 0건(이 세션은 읽기만 함, `git status`에도 `.env` 변경 없음) |
| 코드 변경 | 0건 |

## 수정 파일

```
docs/BETA_RELEASE_CHECKLIST.md   최상단 정정 안내 + P0-2 재실측 정정(취소선/details) + 도메인 현황 표 정정
docs/SPRINT135_BETA_CHECKLIST_STALE_P0.md   신규 (본 문서)
```

## SKIP

| 항목 | 이유 |
|---|---|
| `BETA_RELEASE_CHECKLIST.md` 전면 재작성(P0/P1/P2 전 항목 재검증) | 이 세션 범위를 넘는 별도 규모 작업 — 이번엔 실제로 틀린 것으로 확인된 P0-2 하나만 정정 |
| `PAYMENT_WEBHOOK_SECRET` 값 채우기 | `.env` 수정은 승인 영역 |
| KG이니시스 실연동(P0-1) | 외부 계약 필요, 승인 영역(변동 없음) |

## 남은 Backlog

- **★★ 수집 파이프라인 스케줄러 등록** ― 2026-08-20에 검색 결과 0건이 된다(Sprint 112, 4일 남음).
- `BETA_RELEASE_CHECKLIST.md`의 나머지 P1/P2 항목들도 이번처럼 하나씩 재검증할
  가치가 있음(이번엔 가장 심각한 P0 하나만 처리) — 다음 Documentation Drift
  회차 후보
- Sprint 105~134 SKIP 표의 나머지 승인 대기 항목들
- 다음 Audit 영역: Architecture, Failure Recovery(프로세스/Worker/Browser
  crash 실제 주입), Test Gap, TODO/FIXME/HACK 2차, Dead Code, Security,
  Release Audit (계속 진행)
