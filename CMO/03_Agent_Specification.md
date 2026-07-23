# 03_Agent_Specification.md

# Agent Specification

Version: 1.0

---

# Mission

모든 AI Agent의 역할, 입력(Input), 출력(Output), 책임(Responsibility)을 정의한다.

모든 Agent는 하나의 역할만 수행한다.

Agent 간 직접 의사결정을 하지 않는다.

모든 작업은 Playbook을 따른다.

---

# Workflow

Crawler Agent
↓
Trend Hunter
↓
Topic Scorer
↓
Content Director
↓
Content Blueprint
↓
Story Agent
↓
SEO Agent
↓
Distribution Agent
↓
Publisher
↓
Analytics Agent
↓
Learning Agent

---

# Agent List

---

## 1. Crawler Agent

### Mission

외부 데이터를 수집한다.

### Input

Source Registry

### Output

Raw Data

### Responsibility

- 법원경매
- 온비드
- 뉴스
- SNS
- 커뮤니티
- Google Trends
- 네이버 데이터랩

---

## 2. Trend Hunter

### Mission

콘텐츠가 될 만한 이슈를 찾는다.

### Input

Raw Data

### Output

Content Candidate

### Responsibility

- 트렌드 탐색
- 신규 이슈 탐색
- 지역별 인기 분석
- 급상승 키워드 탐색

---

## 3. Topic Scorer

### Mission

후보 콘텐츠의 우선순위를 계산한다.

### Input

Content Candidate

### Output

Scored Candidate

### Score

- Search Volume
- CTR Prediction
- Share Prediction
- Brand Fit
- Data Quality

---

## 4. Content Director

### Mission

오늘 제작할 콘텐츠를 선정한다.

### Input

Top 50 Candidate

### Output

Today's Top 10

### Responsibility

- Candidate 선택
- Recipe 선택
- Priority 결정

---

## 5. Story Agent

### Mission

Master Content 작성

### Input

Blueprint

### Output

Master Content

### Responsibility

- Hook 작성
- 스토리 작성
- 데이터 해석
- AI 분석
- CTA 생성

---

## 6. SEO Agent

### Mission

검색 최적화

### Input

Master Content

### Output

SEO Optimized Content

### Responsibility

- Title
- Description
- Keyword
- Internal Link
- Slug

---

## 7. Distribution Agent

### Mission

플랫폼별 변환

### Input

Master Content

### Output

- Blog
- Threads
- X
- Shorts
- Newsletter

---

## 8. Publisher

### Mission

예약 발행

### Responsibility

- 예약
- 플랫폼 업로드
- 실패 재시도

---

## 9. Analytics Agent

### Mission

성과 측정

### Input

Published Content

### Output

Performance Report

### Metrics

- Views
- CTR
- Read Time
- Share
- Save
- Signup
- Bounce Rate

---

## 10. Learning Agent

### Mission

AI 품질 개선

### Input

Performance Report

### Output

Weekly Recipe Report

### Responsibility

- Recipe 평가
- 실패 원인 분석
- Prompt 개선
- 신규 Recipe 제안
- Experiment 제안

---

# Agent Rules

모든 Agent는

- 자신의 역할만 수행한다.
- 추측하지 않는다.
- 근거 없는 데이터를 생성하지 않는다.
- Source Registry 외 데이터는 사용하지 않는다.
- 실패 시 Error Report를 반환한다.

---

# Output Rule

모든 Agent는 JSON 또는 Markdown만 출력한다.

자연어 설명은 최소화한다.

---

# End