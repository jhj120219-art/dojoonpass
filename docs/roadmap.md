# Project Roadmap

Status: Beta v1

Owner: Project Management

Last Updated: 2026-07-22

---

# Project Vision

콕찰(Kokchal)은 대한민국 법원경매 정보를 수집하고 검색·상세조회·권리분석·등기부 신청 서비스를 제공하는 플랫폼이다.

Beta v1에서는 안정적인 검색 서비스 구축을 목표로 하며,
AI 투자추천이나 자동 투자판단 기능은 범위에 포함하지 않는다.

---

# Current Status

Project Stage

Beta v1 Development

---

# Completed

## Infrastructure

- Next.js 기반 Frontend 구축
- FastAPI Backend 구축
- SQLite 기반 데이터 저장 구조 구축
- 크롤링 파이프라인 구축
- Search API 구축

---

## Search

- 검색 API 구현
- 검색 결과 조회
- 상세조회 API 구현
- 페이지네이션 구현

---

## Authentication

- Supabase Auth 구조 설계
- JWT 인증 구조 설계

---

## User Features

- 관심물건 구조 설계
- 최근조회 구조 설계
- 검색조건 저장 구조 설계

---

# In Progress

## Frontend

- 실제 API 연동
- JWT 연동
- 권리분석 화면 연동

## Backend

- JWT 인증 활성화
- Registry API 보완

## Crawler

- 문서수집 안정화
- 자동 실행 안정화

## Search

- 검색 최적화
- 필터 개선

---

# Next Priority

Priority 1

- JWT 인증 완료
- Mock 제거
- 실제 API 연결

Priority 2

- 권리분석 연동
- 등기부 신청 API
- 문서 수집 API

Priority 3

- 결제 연동
- 관리자 페이지
- 성능 최적화

---

# Beta v1 Scope

포함

- 검색
- 상세조회
- 관심물건
- 최근조회
- 검색조건 저장
- 회원가입
- 로그인
- 구독 UI
- 등기부 신청 구조

제외

- AI 추천
- 투자점수
- 수익률 계산
- 자동 투자판단

---

# Future Roadmap

## Beta v2

- 문서 자동 수집
- 권리분석 고도화
- Registry 다운로드

---

## Release

- PG 연동
- 결제 완료
- 관리자 기능
- 운영환경 배포
- 성능 최적화

---

# Technical Debt

- Mock API 제거 필요
- JWT 연동 필요
- 문서 수집 안정화
- 검색 최적화
- DB 백업 체계 구축

---

# Sprint Backlog

## [P1] run_daily.bat 실패 은폐 구조 개선

배경: migrate_execute.py 로그 파일 잠금 버그(2026-07-27 수정 완료) 조사 중, run_daily.bat가
migrate_execute.py 실패 후에도 뒤따르는 echo 명령 때문에 배치 자체의 종료코드가 0(성공)으로
남는 구조적 결함이 확인됨. Task Scheduler의 LastTaskResult가 실제 내부 실패를 반영하지 못함.

목표

- 현재 하위 프로세스(mvp_scraper.py / migrate_execute.py) 실패 시 BAT가 exit code 0으로
  종료될 수 있는지 재확인
- 실패 시 즉시 종료(다음 단계로 넘어가지 않음)
- 적절한 exit code 반환(Task Scheduler가 실패를 인지 가능하도록)
- 어느 단계에서 실패했는지 로그에 명확히 남기기

이번 Sprint 범위: 등록만 함. 설계/구현은 다음 Sprint에서 진행.

---

## [P2] 로그인 UX 개선 — 비회원 검색 우선 흐름

배경: 현재는 첫 화면에서 로그인부터 시작하는 UX. 향후에는 비회원도 검색/검색결과까지는
볼 수 있고, 상세 진입 시점에 로그인을 요구하는 흐름으로 변경할 계획.

목표(다음 Sprint 후보, 이번 Sprint는 등록만)

- 비회원 → 검색 → 검색결과 → 상세 진입 시 로그인 흐름으로 전환
- 현재 `/properties/*`를 게이트하는 middleware 인증 로직 재검토 필요 (docs/CLAUDE.md 참고)

이번 Sprint 범위: 등록만 함. 구현하지 않음.

---

# Risks

- SQLite 단일 DB 운영
- 문서 수집 실패 가능성
- JWT 미설정 상태
- 실제 API와 Mock 차이

---

# Success Criteria

Beta v1 출시 기준

- 검색 가능
- 상세조회 가능
- 로그인 가능
- 관심물건 가능
- 최근조회 가능
- 검색조건 저장 가능
- Registry 신청 가능

---

# Out of Scope

다음 기능은 Beta v1 범위가 아니다.

- 투자점수
- AI 추천
- 수익률 계산
- 자동 권리분석 생성
- 자동 투자 의사결정