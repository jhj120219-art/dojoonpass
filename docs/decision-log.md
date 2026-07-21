# Decision Log

Status: Active

Owner: Project Management

Last Updated: 2026-07-22

---

# Core Decisions

## Service Name

결정

- 서비스명은 "콕찰" 사용

영향

- Frontend
- Backend
- 문서 전체

---

## Database

결정

- SQLite 유지

이유

- 현재 프로젝트 범위에서 가장 단순하고 안정적

---

## Authentication

결정

- Supabase Auth 사용

이유

- 인증과 경매 데이터를 분리하기 위함

---

## Frontend

결정

- Frontend는 비즈니스 로직을 수행하지 않는다.

이유

- Backend 단일 책임 유지

---

## Search

결정

- 검색은 SQLite 기반

이유

- Beta v1 범위 유지

---

## Routing

결정

- itemId 단일 식별자 사용

이유

- 모든 기능의 기준값 통일

영향

- 검색
- 상세
- 관심물건
- 최근조회
- Registry

---

## API

결정

- 기존 API 응답 구조 유지

이유

- Breaking Change 방지

---

## Mock

결정

- 함수 시그니처 유지

이유

- 실제 API 전환 시 코드 변경 최소화

---

## Premium

결정

- 무료회원은 상세 API 접근 제한

이유

- 트래픽 절감
- 유료 정책 유지

---

## Search Engine

결정

- Offset Pagination 유지

이유

- 현재 구현 유지

---

## Project Scope

결정

다음 기능은 개발하지 않는다.

- 투자점수
- AI 추천
- 수익률 계산
- 자동 투자판단

---

# Development Rules

- Breaking Change 금지
- SQLite 유지
- itemId 유지
- Mock 시그니처 유지
- 기존 API 유지

---

# Pending Decisions

아직 결정되지 않음

- PG사
- 검색 인덱스
- 문서 수집 구조
- 권리분석 고도화
- 운영 배포 구조