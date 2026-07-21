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

# Reading Order

Claude Code가 문서를 읽는 권장 순서

1. CLAUDE.md
2. architecture.md
3. roadmap.md
4. decision-log.md
5. frontend.md
6. backend.md
7. crawler.md
8. search-engine.md

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