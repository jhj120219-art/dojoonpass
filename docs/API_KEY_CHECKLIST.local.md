# API Key 체크리스트 (Beta 출시용)

Status: Active
Last Updated: 2026-08-06
Owner: CTO

---

## 이 문서의 목적

`docs/ENVIRONMENT_VARIABLES.md`가 "각 환경변수가 무엇인지"를 설명하는 참고 문서라면,
이 문서는 **"지금 무엇을 발급받아야 하는가"를 순서대로 체크할 수 있는 실행 목록**이다.
비개발자(창업자)가 그대로 따라가며 체크할 수 있도록 발급 주체·소요 시간·선행 조건 위주로 정리했다.

**실제 키 값은 이 문서에 절대 적지 않는다.** 발급받은 값은 `.env`(백엔드) /
`.env.local`(프론트엔드)에 직접 입력한다 — 두 파일 모두 `.gitignore` 대상이라 git에 올라가지 않는다.

---

## 지금 당장 (5분, 외부 발급 불필요)

- [ ] **`ADMIN_API_KEY` 생성 + `.env`에 입력**
  - 외부 발급 없음. 아래 명령을 터미널에서 실행해 나온 값을 그대로 사용
    ```
    python -c "import secrets; print(secrets.token_urlsafe(32))"
    ```
  - `.env`에 `ADMIN_API_KEY=<생성된 값>` 한 줄 추가
  - **효과**: 지금 이 값이 없어서 `/api/v1/admin/*`(등기부 신청 상태 관리) 전체가 500 에러로 막혀 있다.
    설정 즉시 정상 동작한다 — 코드는 이미 완성되어 있다(`api/v1/admin.py`).
  - 참고: `docs/ENVIRONMENT_VARIABLES.md` 3번 섹션

---

## 론칭 직전 (결제를 실제로 받기 시작하기 전 — 순서대로)

### 1. KG이니시스 (PG사, 결제 처리) — 가장 오래 걸림, 가장 먼저 시작할 것

- [ ] **사업자등록증 등 가맹점 심사 서류 준비**
- [ ] **KG이니시스 가맹점 계약 신청** (https://iniweb.inicis.com)
  - 심사 기간은 영업일 기준 며칠 소요될 수 있음 — 다른 항목보다 먼저 시작 권장
- [ ] 계약 완료 후 가맹점 관리자에서 발급:
  - [ ] `KG_MID` (상점 아이디)
  - [ ] `KG_API_KEY` (결제 API 인증 키)
  - [ ] `KG_SECRET_KEY` (요청 서명용 비밀키)
  - [ ] `KG_WEBHOOK_SECRET` (노티/Webhook 검증용, Webhook 설정 메뉴에서 별도 발급)
- [ ] **(개발 작업, 계약 후 별도 승인 필요)** `KGInicisProvider` 실제 API 연동 코드 작성
  - 현재 상태: Provider 뼈대(스켈레톤)만 코드에 존재(`api/v1/payment_providers.py`), 실제 API 호출은
    미구현 — 계약 전에는 작성 금지가 프로젝트 원칙(`docs/backend.md` "주의사항" 참고)
  - [ ] 환불(`cancel_payment` 호출부), Webhook 수신 엔드포인트(`handle_webhook` 호출부) 신규 구현도 이 시점에 함께 진행
- [ ] `.env`에 4개 값 입력 후 `PAYMENT_PROVIDER=kginicis`로 전환 (그 전까지는 절대 이 값으로 바꾸지 말 것 — `NotImplementedError`로 결제가 즉시 실패한다)
- [ ] 테스트 MID로 실결제 테스트 → 운영 MID로 전환
- 참고: `docs/ENVIRONMENT_VARIABLES.md` 4번 섹션, `docs/decision-log.md`("PG사 확정" 항목)

### 2. Sentry (에러 모니터링) — 실사용자 트래픽 시작 전 권장

- [ ] Sentry 프로젝트 생성 (https://sentry.io)
- [ ] 백엔드용 DSN 1개 + 프론트엔드용 DSN 1개 발급 (각각 별도 프로젝트 권장)
- [ ] `SENTRY_DSN` `.env`에 입력
- [ ] (개발 작업) 코드에 Sentry SDK 연동 — 현재 저장소에 연동 코드 없음
- 참고: `docs/ENVIRONMENT_VARIABLES.md` 8번 섹션

### 3. Slack (운영 알림) — 크롤링/결제 실패를 즉시 알고 싶을 때

- [ ] Slack 워크스페이스에서 Incoming Webhook 앱 추가
- [ ] `SLACK_WEBHOOK_URL` 발급
- [ ] `.env`에 입력
- [ ] (개발 작업) `run_daily.bat` 실패 시 알림 발송 코드 추가 — 현재 없음
- 참고: `docs/ENVIRONMENT_VARIABLES.md` 9번 섹션

### 4. GA4 (분석) — 사용자 유입/전환 분석 시작 시점

- [ ] Google Analytics 계정/속성 생성
- [ ] `GA4_MEASUREMENT_ID` 발급
- [ ] **개인정보처리방침에 분석 도구 사용 고지 문구 추가** (법적 요구사항, 키 발급보다 먼저 확인)
- [ ] `.env.local`에 `NEXT_PUBLIC_GA4_MEASUREMENT_ID`로 입력
- 참고: `docs/ENVIRONMENT_VARIABLES.md` 7번 섹션

---

## 운영 중 필요 (서비스 성장에 따라 — 지금은 발급 불필요)

- [ ] SMTP (`SMTP_HOST`/`PORT`/`USER`/`PASSWORD`) — 등기부 발급 완료/영수증/구독 만료 메일을 자체 발송할 때
- [ ] SMS (`SMS_API_KEY`/`SMS_SECRET`) — 매각기일 임박 등 실시간 알림을 붙일 때
  - 광고성 문자는 정보통신망법상 수신동의·야간 발송 제한 준수 필요
- [ ] `SUPABASE_SERVICE_ROLE_KEY` — 서버가 Supabase 데이터를 RLS 우회해 직접 조작해야 할 때(현재 필요 없음)

---

## 발급 순서 요약 (의존 관계)

```
[지금] ADMIN_API_KEY 생성 (5분, 외부 발급 없음)
   │
   ▼
[가장 먼저 시작] KG이니시스 가맹점 계약 신청 ← 심사 기간이 있어 병목이 되기 쉬움
   │
   ▼
계약 완료 → KG_MID/KG_API_KEY/KG_SECRET_KEY/KG_WEBHOOK_SECRET 발급
   │
   ▼
KGInicisProvider 실제 구현 (개발 작업, 계약 후 승인)
   │
   ▼
테스트 결제 → 운영 전환
```

Sentry/Slack/GA4는 KG이니시스 계약과 무관하게 병렬로 준비 가능하다.

---

## 관련 문서

- `docs/ENVIRONMENT_VARIABLES.md` — 각 변수의 상세 설명, 코드 참조 여부, 예시 값 형식
- `docs/decision-log.md` — PG사(KG이니시스) 확정 경위
- `docs/backend.md` — "주의사항" 절, PG 연동 코드 작성 금지 원칙
- `docs/BUGS.md` #13 — Mock 결제 상태와 남은 구현 범위
