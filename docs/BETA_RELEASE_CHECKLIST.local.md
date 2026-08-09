# Beta Release Checklist

Status: Active
Last Updated: 2026-08-06 (Sprint 26)
Owner: CTO

---

## 이 문서의 목적

"실제로 베타를 공개해도 되는가"를 판단하는 단일 체크리스트. 기능 구현 여부(`docs/roadmap.md`
Success Criteria)와 운영 준비 상태(환경변수/키/방화벽 등)를 하나로 합쳤다. 각 항목은 근거
문서를 함께 표기한다.

---

## 1. 기능 (Success Criteria) — 전부 완료

- [x] 검색 (`docs/roadmap.md` Success Criteria)
- [x] 상세조회
- [x] 로그인/회원가입 (Supabase Auth)
- [x] 로그아웃 (Sprint 23에서 기능 공백 해소)
- [x] 관심물건
- [x] 최근조회
- [x] 검색조건 저장
- [x] 구독 UI (베이직/프로, 월/연 토글)
- [x] Registry(등기부) 신청 → 결제 연결 → Admin 상태 관리 → 다운로드 전체 체인

## 2. 알려진 버그 — Release Blocking 없음

- [x] `auction_case.case_no` 전국 UNIQUE 충돌 → **Migration 완료**(`docs/BUGS.md` #14)
- [x] 등기부 무료횟수 레이스 컨디션 → **`BEGIN IMMEDIATE`로 수정 완료**
- [x] 로그아웃 기능 공백 → **해소**
- [ ] (Non-blocking) SQLite FK 미강제, `auction.db` 백업 체계 없음 — 아래 "기술부채" 참고

## 3. 실행 환경 — ⚠️ 확인 필요

- [ ] **`python-jose` 설치 확인** — 2026-08-06(Sprint 26) 발견: 이 세션 로컬 환경에는 없어서
  `api_server.py`를 포함한 백엔드 전체가 import 단계에서 죽는다. 운영 배포 서버에도
  설치돼 있는지 별도 확인 필요(`pip install python-jose[cryptography]`)
- [ ] `requirements.txt` 부재 — 의존성이 import 추적으로만 알려져 있음(`docs/CLAUDE.md` 참고).
  배포 전 고정된 의존성 목록 작성 권장(신규 패키지 설치이므로 승인 필요)
- [ ] 방화벽 설정 — `api_server.py`는 `127.0.0.1` 바인딩(로컬 전용). 실제 운영 서버 구성(리버스
  프록시 등)은 이 저장소 코드 범위 밖(`docs/backend.md` "알려진 문제점" 참고)
- [ ] `CORS allow_origins=["*"]` — 현재 "개발 환경"으로 문서화됨. 운영 도메인 확정 시 제한 권장
  (`allow_credentials` 미설정이라 쿠키 전송은 안 되지만, 운영 전 도메인 제한이 안전함)

## 4. 환경변수/API Key — `docs/API_KEY_CHECKLIST.md` 상세 참고

- [ ] `ADMIN_API_KEY` — **지금 바로 설정 가능**(외부 발급 불필요, Admin API가 이 값만 없으면 500)
- [ ] KG이니시스 계약 + `KG_MID`/`KG_API_KEY`/`KG_SECRET_KEY`/`KG_WEBHOOK_SECRET` — 결제 실연동 시작 전 필수
- [ ] `SENTRY_DSN` — 실사용자 트래픽 전 권장
- [ ] `SLACK_WEBHOOK_URL` — 운영 알림, 선택
- [ ] `GA4_MEASUREMENT_ID` — 분석 시작 시점(개인정보처리방침 고지 선행 필요)

## 5. 결제(Payment) — Mock 유지 중, 의도적

- [x] Mock 결제 체인 100% 동작(Subscription/Registry 연결 포함)
- [x] 금액 서버 검증(구독+초과분 둘 다)
- [x] Provider 인터페이스 v2 + Flow Migration 완료
- [ ] `KGInicisProvider` 실제 API 연동 — **계약/API Key 필요, 승인 대기**(스켈레톤만 존재)
- [ ] 환불(`cancel_payment`)/Webhook(`handle_webhook`) 수신 엔드포인트 — 미착수

## 6. 테스트/검증

- [x] `test_subscription_policy.py`(28항목) / `test_api_regression.py`(100+ 검사, Admin 3건 추가)
  작성 완료
- [ ] **위 두 테스트를 실제로 실행해 통과 확인** — 이번 세션 환경에서는 `python-jose` 누락으로
  실행 불가했음(위 3번 참고). 배포 전 반드시 재실행 필요
- [x] Type Check(`tsc --noEmit`) / Build(`npm run build`) / Lint(`npm run lint`) — 전부 통과
  (Lint 기존 2건은 알려진 항목, 신규 0)
- [x] Python 전체 `compileall` 통과

## 7. 운영 준비

- [ ] `auction.db` 백업 체계 (현재 수동 타임스탬프 백업만 존재, 자동화 없음)
- [ ] Admin 역할(role) 구분 (현재 단일 공유키, MVP 한계로 알려진 채 유지 중)
- [ ] `run_daily.bat`/`run_doc_worker.bat`/`run_priority_refresh.bat` Task Scheduler 정상 동작 확인
  (경로 통합은 2026-07-26 완료, 최근 재확인 권장)
- [ ] 개인정보처리방침 — 로그인(Supabase), 결제(KG이니시스), 분석(GA4 도입 시) 관련 고지 필요

---

## 종합 판단

**기능/버그 관점에서는 베타 공개 가능한 상태다.** 남은 항목은 대부분 "외부 절차"(KG이니시스
계약) 또는 "값 입력"(ADMIN_API_KEY 등, 승인 필요)이지 코드 결함이 아니다. 유일하게 코드
작업이 남은 것은 PG 실연동(계약 후)과 환불/Webhook 엔드포인트뿐이며, 둘 다 Mock 결제로
베타를 운영하는 동안은 없어도 서비스가 정상 동작한다.

**단, 배포 전 "3. 실행 환경"의 `python-jose` 확인은 반드시 선행해야 한다** — 이 패키지가
없으면 백엔드 자체가 뜨지 않는다(로컬 개발 환경에서만 이번에 우연히 발견됨, 운영 서버 상태는
별도 확인 필요).

---

## 관련 문서

- `docs/roadmap.md` — Success Criteria, Critical Path
- `docs/API_KEY_CHECKLIST.md` — 키 발급 실행 목록
- `docs/ENVIRONMENT_VARIABLES.md` — 환경변수 상세
- `docs/BUGS.md` — 알려진 이슈 이력
- `docs/CHANGELOG.md` — Sprint별 변경 이력
