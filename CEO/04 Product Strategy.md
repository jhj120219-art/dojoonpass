# Product Strategy

Version 2.0 (2026-09-04 개정)

> **정본은 `docs/PRODUCT_STRATEGY.md` 다.** 고객 / 문제 / 가치 / Workflow / KPI 의
> 정의가 이 문서와 다르면 그쪽을 기준으로 한다. 이 문서는 회사 관점의 요약이다.

---

# Purpose

콕찰 제품의 개발 방향을 정의한다.

---

# Customer

**본업이 있는 투자자.**

직장인 · 사업자 · 전문직 · 경매를 전업으로 하지 않는 개인 투자자.

이 고객의 결정적 제약은 지식도 자본도 아니라 **시간**이다.

> 사용 빈도(월 몇 건)는 **내부 행동 세그먼트**로만 쓴다. 제품 정의에 쓰지 않는다 —
> 빈도로 정의하면 "더 자주 쓰게 만들기"가 목표가 되는데, 우리 목표는 반대다.

---

# Product Vision

콕찰은

**경매 의사결정에 드는 시간이 가장 짧은 서비스**를 만든다.

"AI 기반 경매 플랫폼"이 목표가 아니다 — AI 는 수단이고,
고객이 사는 것은 **줄어든 시간**이다.

---
# Product Scope
우리가 하는 것

AI 검색

AI 권리분석

경매 데이터

추천

자동화

---

우리가 하지 않는 것

중개

투자 권유

부동산 매매

경매 교육 판매

---

# Product Goal

사용자가

DISCOVER (물건 발견)

↓

REVIEW (핵심정보 검토 — 권리 · 임차인 · 문서)

↓

FIELD (임장)

↓

DECIDE (입찰 판단)

까지

**한 플랫폼 안에서, 밖으로 나가지 않고** 수행할 수 있도록 한다.

단계와 단계 **사이가 끊긴 자리**에서 사용자는 콕찰 밖으로 나가고,
나가는 순간 시간이 늘어난다. 그래서 연결이 곧 제품이다.

---

# Product Principles

## Product First

제품 품질이 최우선이다.

---

## Simplicity

복잡한 기능보다

쉽게 사용할 수 있는 기능을 만든다.

---

## Accuracy

정확하지 않은 AI는

기능으로 제공하지 않는다.

---

## Data Driven

모든 기능은

데이터 기반이다.

---

## MVP First

큰 기능보다

작게 만들어

검증한다.

---

# Feature Priority

Priority 1

사용자가 반드시 필요한 기능

Priority 2

사용성을 높이는 기능

Priority 3

자동화 기능

Priority 4

부가 기능

---

# Development Process

Problem

↓

Research

↓

Spec

↓

MVP

↓

Test

↓

Improve

↓

Release

---

# AI Integration

AI는

검색

추천

분석

자동화

콘텐츠

에 활용한다.

---

# Success Metrics

**핵심 KPI — Time to Decision (T2D)**

    물건을 처음 발견한 시점  ->  입찰 여부를 판단한 시점

측정 도구는 `audit_time_to_decision.py`(읽기 전용)다.
측정 가능 범위와 한계는 `docs/PRODUCT_STRATEGY.md` §7 에 적혀 있다.

**표본이 없는 상태에서 "몇 % 단축" 같은 숫자를 만들지 않는다.**

보조 지표 (T2D 를 대신하지 않고 보완한다)

검토 완료율 (상세를 열고 판단까지 간 비율)

임장 완료율

재방문율

유료 전환율