# DojoonPass Project Documents

이 디렉터리는 DojoonPass(콕찰) 프로젝트의 공식 설계 문서를 관리한다.

Claude Code는 프로젝트를 이해할 때 이 문서들을 참고한다.

---

# Documents

## architecture.md

프로젝트 전체 시스템 구조

---

## roadmap.md

현재 개발 상태

향후 개발 계획

우선순위

---

## decision-log.md

프로젝트에서 확정된 주요 설계 결정

---

## frontend.md

Frontend 설계

---

## backend.md

Backend 설계

---

## crawler.md

Crawler 설계

---

## search-engine.md

검색엔진 설계

---

## CURRENT_STATE.md

지금 무엇이 완료/진행중/미착수인지 (가장 자주 갱신되는 현황 문서)

---

## CHANGELOG.md

Sprint별 변경 이력 (사료 — 과거 기록은 정정하지 않고 그대로 둔다)

---

## BUGS.md

알려진 문제점과 해결 내역 (번호로 참조)

---

## BETA_RELEASE_CHECKLIST.md

Beta 출시를 막는 요소를 P0/P1/P2로 분류 (2026-08-07 신설)

---

## API_KEY_CHECKLIST.md

"지금 코드가 실제로 무엇을 읽는가"의 **코드 기준 사실 대장** — 참조 지점(파일:라인)까지 기록.
참조 0건인 카테고리(OAuth/SMTP/Storage/Analytics/Monitoring/SNS/OCR/지도/메일)도 0건이라고 적는다.
env 파일 ↔ 코드 드리프트와, env가 아닌 외부 대시보드 설정도 함께 관리 (2026-08-07 신설)

---

## ERROR_CODES.md

도메인별 Error Code 표준(`AUTH`/`PAY`/`SEARCH`/`REGISTRY`/`ADMIN`/`SUBSCRIPTION` 등).
클라이언트는 메시지 문구가 아니라 이 코드로 분기한다 (2026-08-07 신설)

---

## STATE_MACHINES.md

Payment / Subscription / Registry 상태값과 허용 전이 규칙 (2026-08-07 신설)

---

## ENVIRONMENT_VARIABLES.md

각 환경변수의 **발급 방법·예시 값·설정 절차** + "지금 필요한지 / 론칭 직전인지 / Skip 가능한지".
"무엇을 읽는가"는 `API_KEY_CHECKLIST.md`가 기준이다

---

## TEST_PLAN.md

회귀 테스트 2종의 커버 범위, 품질 게이트, 수동 확인 영역

---

## APPROVAL_POLICY.md

승인이 필요한 작업의 기준과 QA 우선순위

---

## CLAUDE.md / AI_CONTEXT.md

작업 규칙과 프로젝트 컨텍스트 요약

---

# Reading Order

Claude Code가 문서를 읽는 권장 순서

1. CLAUDE.md
2. architecture.md
3. CURRENT_STATE.md
4. roadmap.md
5. decision-log.md
6. frontend.md
7. backend.md
8. crawler.md
9. search-engine.md

출시 판단이 필요하면 BETA_RELEASE_CHECKLIST.md, 버그 이력이 필요하면 BUGS.md,
"어떤 키/ENV가 필요한가"는 API_KEY_CHECKLIST.md, "어떻게 발급·설정하는가"는
ENVIRONMENT_VARIABLES.md를 본다.

---

# Documentation Rules

- 추측을 작성하지 않는다.
- 실제 결정된 내용만 기록한다.
- 설계 변경 시 관련 문서를 함께 수정한다.
- Breaking Change는 decision-log.md에 기록한다.
- 프로젝트 구조 변경 시 architecture.md를 갱신한다.

---

# Single Source of Truth

프로젝트의 공식 정보는 다음 문서를 기준으로 한다.

- CLAUDE.md
- architecture.md
- decision-log.md

코드와 문서가 다를 경우 우선 코드가 기준이며, 문서는 즉시 최신 상태로 갱신한다.