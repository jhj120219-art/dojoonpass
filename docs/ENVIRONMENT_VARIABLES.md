# 환경변수 가이드 (Environment Variables)

Status: Active
Last Updated: 2026-08-07
Owner: CTO

---

## 이 문서의 목적

> **함께 보는 문서**: `docs/API_KEY_CHECKLIST.md`(2026-08-07 신설)는 "지금 코드가 실제로 무엇을
> 읽는가"를 참조 지점(파일:라인)까지 적은 **코드 기준 사실 대장**이다. 이 문서는 각 변수의
> **발급 방법·예시 값·설정 절차**를 다룬다. 둘이 어긋나면 코드가 기준이다.

이 저장소를 실행/배포할 때 필요한 모든 환경변수를 한 곳에 정리한다.
**Claude Code가 그대로 참고할 수 있는 개발 문서**를 목표로 하며, 각 항목마다
"지금 필요한지 / 론칭 직전에 필요한지 / 지금은 Skip해도 되는지"를 명시한다.

## 읽는 법 / 중요 규칙

- **`.env` 파일은 승인 없이 수정하지 않는다** (프로젝트 규칙). 이 문서는 "무엇이 필요한가"를
  기술할 뿐이며, 실제 값 입력은 사용자가 직접 수행한다.
- **실제 키 값을 이 문서에 적지 않는다.** 예시는 전부 형식만 보여주는 더미다.
- 현재 저장소의 `.env` / `.env.local` 두 파일이 사용된다:
  - `.env` — 백엔드(FastAPI, `api_server.py`가 `load_dotenv()`로 로드)
  - `.env.local` — 프론트엔드(Next.js, `NEXT_PUBLIC_*` 포함)
- **Next.js에서 `NEXT_PUBLIC_` 접두사가 붙은 값은 브라우저에 그대로 노출된다.**
  비밀키에는 절대 이 접두사를 붙이지 않는다.

## 현재 상태 요약 (2026-08-07 코드 기준)

| 상태 | 항목 |
|---|---|
| ✅ 설정 완료·동작 중 | `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `ADMIN_API_KEY`, `SUPER_ADMIN_API_KEY`(2026-08-11 Sprint 57 재확인 — 둘 다 실제 요청으로 정상 동작 확인, 이전 "미설정" 기록은 stale) |
| ⚪ 값 없이도 정상 동작 | `SUPABASE_JWT_SECRET`(2026-08-10 Sprint 46부터 JWKS/ES256이 주 경로라 없어도 실사용자 인증이 막히지 않는다. HS256 레거시 검증에만 쓰이므로 없으면 그 경로만 비활성) |
| 🕓 론칭 직전 필요 | KG이니시스 4종, Mail, SMS, GA4, Sentry, Slack |
| 💤 지금 Skip 가능 | 코드에 참조 지점이 아직 없는 항목 전부(아래 "코드 참조 여부" 열 확인) |

## 시점별 분류 (한눈에 보기)

### A. 지금 당장 필요 — 없으면 기능이 막힌다

| 변수 | 상태 | 없을 때 증상 |
|---|---|---|
| `SUPABASE_JWT_SECRET` | ❌ 미설정(2026-08-11 재확인) | HS256 레거시 검증 경로만 비활성 — 실사용자 토큰은 ES256/JWKS로 검증되어 영향 없음(`docs/BUGS.md` #27) |
| `NEXT_PUBLIC_SUPABASE_URL` | ✅ 설정됨 | 로그인/회원가입 불가 |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | ✅ 설정됨 | 로그인/회원가입 불가 |
| `ADMIN_API_KEY` | ✅ 설정됨(2026-08-11 Sprint 57 실제 요청으로 재확인 — 이전 "미설정" 기록은 stale) | — |
| `SUPER_ADMIN_API_KEY` | ✅ 설정됨(2026-08-11 Sprint 57 재확인, `ADMIN_API_KEY`와 다른 값이라 등급 분리 정상 동작) | — |

### B. 론칭 직전 필요 — 결제/모니터링 개시 시점

| 변수 | 선행 조건 |
|---|---|
| `KG_MID` / `KG_API_KEY` / `KG_SECRET_KEY` | KG이니시스 사업자 계약·심사 완료 |
| `KG_WEBHOOK_SECRET` | Webhook 수신 엔드포인트 구현 후 |
| `PAYMENT_PROVIDER=kginicis` | `KGInicisProvider` **실구현** 완료 후 (클래스 자리는 2026-08-07 신설 완료. 현재 값 없으면 안전하게 `mock`) |
| `SENTRY_DSN` | 실사용자 트래픽 전 예외 수집 시작 |
| `GA4_MEASUREMENT_ID` | 개인정보처리방침에 분석도구 고지 후 |

### C. 운영 중 필요 — 서비스 성장에 따라 추가

| 변수 | 도입 시점 |
|---|---|
| `SLACK_WEBHOOK_URL` | 크롤링 실패/결제 실패를 즉시 인지해야 할 때(현재는 로그 수동 확인) |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` | 등기부 발급 완료·영수증·구독 만료 안내 메일을 자체 발송할 때 |
| `SMS_API_KEY` / `SMS_SECRET` | 매각기일 임박 등 실시간 알림을 붙일 때 |
| `SUPABASE_SERVICE_ROLE_KEY` | 서버가 RLS를 우회해 Supabase 데이터를 직접 조작해야 할 때 |
| `CORS_ALLOW_ORIGINS` | 운영 배포 시 API를 프론트 도메인으로만 제한할 때(미설정 = 기존 `*`) |
| `LOG_LEVEL` | API 서버 로그 레벨 조절이 필요할 때(미설정 = `INFO`) |

---

# 1. Supabase (인증)

인증은 Supabase Auth를 쓰고, 경매 데이터는 SQLite에 있다(`docs/decision-log.md` 참고).

## SUPABASE_URL

| 항목 | 내용 |
|---|---|
| 구분 | Supabase |
| 설명 | Supabase 프로젝트 API 엔드포인트 URL |
| 필수 여부 | **필수** |
| 언제 필요한지 | 로그인/회원가입 등 인증 기능 전체 |
| 현재 필요한가 | **예 (이미 설정되어 동작 중)** |
| 발급 위치 | Supabase 대시보드 → Project Settings → API → Project URL |
| 코드 참조 여부 | 프론트는 `NEXT_PUBLIC_SUPABASE_URL`로 참조(`src/lib/supabaseClient.ts`, `src/lib/supabaseServer.ts`, `src/proxy.ts`(구 `middleware.ts`)) |
| 비고 | 프론트에서 쓰려면 반드시 `NEXT_PUBLIC_` 접두사 버전이 `.env.local`에 있어야 한다. 비밀값이 아니므로 노출되어도 무방 |
| 예시 | `NEXT_PUBLIC_SUPABASE_URL=https://abcdefghijklm.supabase.co` |

## SUPABASE_ANON_KEY

| 항목 | 내용 |
|---|---|
| 구분 | Supabase |
| 설명 | 익명(공개) 클라이언트 키. RLS 정책 적용을 전제로 브라우저에 노출되는 것이 정상 |
| 필수 여부 | **필수** |
| 언제 필요한지 | 로그인/회원가입/세션 갱신 |
| 현재 필요한가 | **예 (이미 설정되어 동작 중)** |
| 발급 위치 | Supabase 대시보드 → Project Settings → API → Project API keys → `anon` `public` |
| 코드 참조 여부 | `NEXT_PUBLIC_SUPABASE_ANON_KEY` (`supabaseClient.ts`/`supabaseServer.ts`/`proxy.ts`) |
| 비고 | 공개 키지만 RLS가 없으면 데이터가 열린다 — Supabase 쪽 RLS 설정과 함께 관리할 것 |
| 예시 | `NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.<...>` |

### 2026-08-08 확인 — Supabase의 legacy anon/service_role → publishable/secret key 전환과의 관계

Supabase는 2026년 기준 대시보드에서 legacy `anon`/`service_role` 키와 신규
`publishable`(`sb_publishable_...`)/`secret`(`sb_secret_...`) 키를 함께 제공한다(같은 프로젝트,
같은 권한 등급, 형식만 다른 값). **코드가 실제로 요구하는 것은 변수명 `NEXT_PUBLIC_SUPABASE_ANON_KEY`
뿐이다** — `createBrowserClient()`/`createServerClient()`(`@supabase/ssr`)의 두 번째 인자는 legacy
anon 키 값이든 신규 publishable 키 값이든 그대로 받아들인다(SDK는 값의 형식을 구분하지 않음).
즉 **`.env.local`의 `NEXT_PUBLIC_SUPABASE_ANON_KEY`에 신규 publishable 키 값을 넣어도 코드 변경
없이 동작한다** — 변수명만 기존 그대로 유지하면 된다.

**주의**: `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`라는 이름으로 값을 넣으면 코드가 그 이름을
읽지 않으므로 **아무 효과가 없다**(조용히 무시됨). 반드시 `NEXT_PUBLIC_SUPABASE_ANON_KEY`라는
기존 변수명을 그대로 써야 한다. 또한 `NEXT_PUBLIC_`로 시작하는 프론트엔드 값은 `.env.local`에
있어야 하며, `.env`(백엔드 전용, `api_server.py`가 `load_dotenv()`로 읽는 파일)에 넣으면 프론트가
전혀 읽지 못한다 — Next.js가 빌드 타임에 `.env.local`만 읽어 클라이언트 번들에 주입하기 때문이다.

## SUPABASE_SERVICE_ROLE_KEY

| 항목 | 내용 |
|---|---|
| 구분 | Supabase |
| 설명 | RLS를 우회하는 **관리자 권한 키**. 서버에서만 사용 |
| 필수 여부 | 선택 (현재 미사용) |
| 언제 필요한지 | 서버가 사용자 대신 Supabase 데이터를 직접 조작해야 할 때(예: 관리자 배치, 사용자 강제 탈퇴) |
| 현재 필요한가 | **아니오 — 지금 Skip 가능.** 현재 코드에 참조 지점이 전혀 없다 |
| 발급 위치 | Supabase 대시보드 → Project Settings → API → `service_role` `secret` |
| 코드 참조 여부 | **없음** (저장소 전체 grep 결과 0건) |
| 비고 | **절대 `NEXT_PUBLIC_` 접두사를 붙이지 말 것.** 유출 시 전체 데이터 조작 가능 |
| 예시 | `SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.<...>` |

---

# 2. JWT (백엔드 토큰 검증)

## JWT_SECRET

> **주의 — 실제 코드가 쓰는 이름은 `SUPABASE_JWT_SECRET`이다.**
> 이 문서의 요청 항목명은 `JWT_SECRET`이지만, `api/auth.py`는
> `os.getenv("SUPABASE_JWT_SECRET")`을 읽는다. 이름을 바꾸려면 코드 수정이 필요하므로
> **현재는 `SUPABASE_JWT_SECRET`으로 설정해야 동작한다.**
>
> **2026-08-09 분류 확정**(`docs/BETA_RELEASE_CHECKLIST.md` P0-4 상세 근거): `JWT_SECRET`/
> `SUPABASE_JWT_SECRET`/`NEXTAUTH_SECRET` 3개 변수명을 코드 전체에서 재검색한 결과 —
> `SUPABASE_JWT_SECRET`만 실제로 별도 필요(코드 참조 다수), `JWT_SECRET`은 코드 참조
> **0건**(이 환경의 `.env`에 그 이름으로 값이 들어있지만 어떤 코드도 읽지 않음),
> `NEXTAUTH_SECRET`은 이 프로젝트가 NextAuth.js를 쓰지 않아 **완전히 무관**(코드 참조 0건).
> 셋 중 대체 가능하거나 재활용할 이름은 없다 — `SUPABASE_JWT_SECRET`이라는 정확한 이름으로
> 값을 넣는 것 외에는 방법이 없다.

| 항목 | 내용 |
|---|---|
| 구분 | JWT |
| 실제 변수명 | **`SUPABASE_JWT_SECRET`** |
| 설명 | FastAPI가 Supabase 발급 JWT의 서명을 검증하는 비밀키(HS256) |
| 필수 여부 | **필수** |
| 언제 필요한지 | 인증이 필요한 모든 API(favorites/recent-items/search-presets/registry-requests/payments) |
| 현재 필요한가 | **아니오(2026-08-11 재확인)** — 이름이 여전히 `.env`에 없지만, 2026-08-10 Sprint 46부터 실사용자 토큰은 JWKS 기반 ES256으로 검증되어 이 값과 무관하게 동작한다. 없으면 HS256 레거시 검증 경로(테스트 토큰 등)만 비활성 |
| 발급 위치 | Supabase 대시보드 → Project Settings → API → JWT Settings → JWT Secret |
| 코드 참조 여부 | `api/auth.py:9`, `api/v1/item.py`, `api/v1/search.py`(선택적 검증), `test_api_regression.py`(테스트 토큰 서명) |
| 비고 | 미설정 시 인증 필요 API가 전부 `500 "JWT Secret 미설정"`으로 막힌다. `NEXT_PUBLIC_` 금지 |
| 예시 | `SUPABASE_JWT_SECRET=super-long-random-secret-from-supabase` |

---

# 3. Admin (운영자 전용 API)

## ADMIN_API_KEY

| 항목 | 내용 |
|---|---|
| 구분 | Admin |
| 설명 | `/api/v1/admin/*` 접근용 공유 키. `X-Admin-Key` 헤더 값과 상수시간 비교(`hmac.compare_digest`) |
| 필수 여부 | **필수 (운영 전)** |
| 언제 필요한지 | 등기부 신청 상태 관리(목록 조회, PENDING→PROCESSING→COMPLETED 전이, `doc_url` 등록) |
| 현재 필요한가 | **아니오 — 2026-08-11 Sprint 57 재확인, 설정되어 정상 동작 중**(실제 요청으로 200/403 응답 확인) |
| 발급 위치 | 외부 발급 없음. **직접 생성**(예: `python -c "import secrets; print(secrets.token_urlsafe(32))"`) |
| 코드 참조 여부 | `api/v1/admin.py:resolve_admin_role()` / `require_admin()` |
| 비고 | 2026-08-07부터 이 키는 **ADMIN 등급**이다(SUPER_ADMIN은 아래 별도 키). 같은 등급 안에서는 사용자 구분이 없어 키를 아는 사람이 동일 권한을 갖는다. 유출 시 즉시 교체 |
| 예시 | `ADMIN_API_KEY=Xy9-3fQz...랜덤32바이트...` |

## SUPER_ADMIN_API_KEY (2026-08-07 신규)

| 항목 | 내용 |
|---|---|
| 구분 | Admin |
| 설명 | Admin 권한 2단계 중 **SUPER_ADMIN**. 과금에 직접 영향을 주는 조작 전용 |
| 필수 여부 | 선택(없으면 SUPER_ADMIN 전용 기능만 막힌다) |
| 언제 필요한지 | 등기부 무료횟수 추가/차감/초기화(CS 보상 등) |
| 현재 필요한가 | 운영 개시와 함께 필요 — CS 대응 수단이다 |
| 발급 위치 | 외부 발급 없음. `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| 코드 참조 여부 | `api/v1/admin.py:resolve_admin_role()` |
| 비고 | **`ADMIN_API_KEY`와 반드시 다른 값**으로 설정해야 등급 분리가 의미를 갖는다. 같으면 SUPER_ADMIN으로 승격된다 |
| 예시 | `SUPER_ADMIN_API_KEY=Qz1-8wKp...랜덤32바이트...` |

---

# 4. Payment — KG이니시스

**PG사는 KG이니시스로 확정**(2026-08-06, `docs/decision-log.md`).
단 실제 API 연동·계약·키 입력·Webhook 연결·실결제 테스트는 **론칭 직전까지 연기**한다.
현재는 `MockProvider`로 동작하며, 아래 4개 변수는 **지금 전부 Skip 가능**하다.

> 현재 코드 상태(2026-08-07 갱신): `api/v1/payment_providers.py`에 `KGInicisProvider` **클래스가
> 신설**됐고 `get_payment_provider()`는 `PAYMENT_PROVIDER`(mock/kginicis/toss/portone)를 인식한다
> (기본값 `mock`). 단 `KGInicisProvider`의 6개 메서드는 전부 `NotImplementedError`인 **자리
> 구현**이므로, `PAYMENT_PROVIDER=kginicis`로 바꾸면 모든 결제가 즉시 실패한다 — 실제 API 호출
> 구현(승인 필요)이 끝나기 전까지는 값을 설정하지 않고 `mock`을 유지해야 한다.

## PAYMENT_PROVIDER (기존 변수, 참고)

| 항목 | 내용 |
|---|---|
| 구분 | Payment |
| 설명 | 사용할 결제 Provider 선택 |
| 필수 여부 | 선택 (미설정 시 `mock`) |
| 현재 필요한가 | **아니오 — 미설정 상태 유지 권장**(설정하지 않으면 Mock으로 안전하게 동작) |
| 코드 참조 여부 | `api/v1/payment_providers.py:get_payment_provider()` |
| 허용값 | `mock`(기본) / `kginicis`(확정 PG사, 자리 구현) / `toss`·`portone`(**폐기 예정**, 선택 시 경고 로그). 그 외 값은 허용값 목록을 포함한 `ValueError`로 즉시 실패 |
| 비고 | `_PROVIDERS` 맵 등록은 2026-08-07 완료. 실제 값 설정은 `KGInicisProvider` 실구현 완료 후 |
| 예시 | `PAYMENT_PROVIDER=mock` |

## KG_MID

| 항목 | 내용 |
|---|---|
| 구분 | Payment (KG이니시스) |
| 설명 | 상점 아이디(Merchant ID). 가맹점 식별자 |
| 필수 여부 | 론칭 시 **필수** |
| 언제 필요한지 | 결제창 호출, 승인 API 요청 |
| 현재 필요한가 | **아니오 — 지금 Skip 가능** (사업자 계약 완료 후) |
| 발급 위치 | KG이니시스 가맹점 관리자(https://iniweb.inicis.com) → 상점정보. 테스트용 MID는 이니시스 개발 가이드에서 제공 |
| 코드 참조 여부 | **없음** (Provider 미구현) |
| 비고 | 테스트 MID와 운영 MID가 다르다. 운영 MID는 사업자 계약·심사 완료 후 발급 |
| 예시 | `KG_MID=INIpayTest` |

## KG_API_KEY

| 항목 | 내용 |
|---|---|
| 구분 | Payment (KG이니시스) |
| 설명 | 결제 API 인증 키(상점 인증용) |
| 필수 여부 | 론칭 시 **필수** |
| 언제 필요한지 | 승인/취소/조회 API 호출 시 인증 |
| 현재 필요한가 | **아니오 — 지금 Skip 가능** |
| 발급 위치 | KG이니시스 가맹점 관리자 → 상점정보 → API 키 관리 |
| 코드 참조 여부 | **없음** (Provider 미구현) |
| 비고 | 서버 전용. `NEXT_PUBLIC_` 금지 |
| 예시 | `KG_API_KEY=ItEQKi3rY7uvDS8l` |

## KG_SECRET_KEY

| 항목 | 내용 |
|---|---|
| 구분 | Payment (KG이니시스) |
| 설명 | 요청 서명(해시) 생성용 비밀키 |
| 필수 여부 | 론칭 시 **필수** |
| 언제 필요한지 | 결제 요청 위·변조 방지 서명 생성/검증 |
| 현재 필요한가 | **아니오 — 지금 Skip 가능** |
| 발급 위치 | KG이니시스 가맹점 관리자 → 상점정보 (`signKey`/`iniapiKey` 계열) |
| 코드 참조 여부 | **없음** (Provider 미구현) |
| 비고 | 유출 시 결제 요청 위조가 가능하므로 최우선 보호 대상 |
| 예시 | `KG_SECRET_KEY=SU5JTElURV9UUklQTEVERVNfS0VZU1RS` |

## KG_WEBHOOK_SECRET

| 항목 | 내용 |
|---|---|
| 구분 | Payment (KG이니시스) |
| 설명 | Webhook(입금통보/결제결과 노티) 요청이 실제 KG이니시스에서 왔는지 검증하는 키 |
| 필수 여부 | 론칭 시 **필수** |
| 언제 필요한지 | 가상계좌 입금통보, 비동기 결제결과 수신 |
| 현재 필요한가 | **아니오 — KG 실연동 시점에 필요** (수신 엔드포인트는 2026-08-11 Sprint 52에 생겼으나, KG용 서명 검증은 `KGInicisProvider` 구현과 함께 붙는다) |
| 발급 위치 | KG이니시스 가맹점 관리자 → 노티(Noti) 설정 |
| 코드 참조 여부 | **아직 없음.** 수신 엔드포인트(`POST /api/v1/payments/webhook/{provider}`)와 `verify_webhook_signature()` 인터페이스는 준비됐고, `KGInicisProvider`가 이 값을 읽도록 구현하면 된다 |
| 비고 | 서명 검증 없이 Webhook을 신뢰하면 결제 위조가 가능하다 — 구현 시 반드시 검증 먼저 |
| 예시 | `KG_WEBHOOK_SECRET=whsec_<랜덤문자열>` |

## PAYMENT_WEBHOOK_SECRET (2026-08-11 Sprint 52 신규)

| 항목 | 내용 |
|---|---|
| 구분 | Payment (Webhook 수신) |
| 설명 | `POST /api/v1/payments/webhook/{provider}`로 들어오는 요청의 **HMAC-SHA256 서명**을 검증하는 공유 시크릿 |
| 필수 여부 | Webhook을 실제로 받기 시작하는 시점에 **필수** |
| 언제 필요한지 | 지금은 불필요 — `MockProvider` 기준 구현이고, 값이 없으면 **모든 Webhook이 401로 거부**된다(fail-closed) |
| 현재 필요한가 | **아니오 — Skip 가능.** 미설정 상태가 곧 "Webhook으로 결제 상태를 바꿀 수 없음"이라 안전한 기본값이다 |
| 발급 위치 | **운영자가 직접 생성**하는 랜덤 문자열(외부 발급 아님). 이 저장소의 코드나 문서가 값을 만들지 않는다 |
| 코드 참조 여부 | `api/v1/payment_providers.py:MockProvider.verify_webhook_signature()` |
| 검증 방식 | 요청 **원문 바디**에 대한 HMAC-SHA256 hex를 `X-Webhook-Signature` 헤더와 `hmac.compare_digest()`로 상수시간 비교 |
| 비고 | KG 실연동 시에는 KG가 정한 서명 규격을 `KGInicisProvider`가 따로 구현한다 — 이 값은 Mock/자체 노티용이다 |
| 예시 | `PAYMENT_WEBHOOK_SECRET=<운영자가 생성한 랜덤 문자열>` |

---

# 4-1. CORS (API 서버)

## CORS_ALLOW_ORIGINS

| 항목 | 내용 |
|---|---|
| 구분 | API 서버 |
| 설명 | FastAPI가 허용할 Origin 목록(콤마 구분). 미설정 시 기존과 동일하게 `*`(전체 허용) |
| 필수 여부 | 선택 (개발 중에는 불필요) |
| 언제 필요한지 | **운영 배포 시** — 프론트 도메인만 남기고 나머지를 닫을 때 |
| 현재 필요한가 | **아니오 — 지금 Skip 가능**(미설정 = 기존 동작 `*`) |
| 코드 참조 여부 | `api_server.py` (2026-08-07 신규) |
| 비고 | 인증이 쿠키가 아니라 `Authorization: Bearer`라 CSRF 위험은 없지만, 운영에서 전 도메인에 API를 열어둘 이유도 없다. 값을 넣으면 그 목록만 허용된다 |
| 예시 | `CORS_ALLOW_ORIGINS=https://kokchal.com,https://www.kokchal.com` |

## LOG_LEVEL

| 항목 | 내용 |
|---|---|
| 구분 | API 서버 |
| 설명 | FastAPI 서버의 로그 레벨. `logging.basicConfig(level=...)`에 그대로 들어간다 |
| 필수 여부 | 선택 (미설정 시 `INFO`) |
| 언제 필요한지 | 운영에서 로그량을 줄이고 싶을 때(`WARNING`), 문제 추적 시 늘리고 싶을 때(`DEBUG`) |
| 현재 필요한가 | **아니오 — 지금 Skip 가능**(미설정 = `INFO`가 적정) |
| 코드 참조 여부 | `api_server.py` (2026-08-07 신규) |
| 비고 | 비밀값 아님. 알 수 없는 값이면 `INFO`로 폴백. **2026-08-07 이전에는 API 서버에 로깅 설정 자체가 없어 `logger.info`가 전부 버려졌다**(Admin 감사 로그 포함) |
| 예시 | `LOG_LEVEL=INFO` |

---

# 5. Mail (SMTP)

현재 저장소에 메일 발송 코드가 **전혀 없다**(회원가입 인증메일은 Supabase가 자체 발송).
아래 4개는 자체 메일 발송 기능을 만들 때 필요하며, **지금은 전부 Skip 가능**하다.

| 변수명 | 설명 | 필수 | 현재 필요 | 발급 위치 | 예시 |
|---|---|---|---|---|---|
| `SMTP_HOST` | 메일 서버 주소 | 론칭 시 선택 | ❌ Skip | 메일 제공사(Gmail/AWS SES/Naver Works 등) | `smtp.gmail.com` |
| `SMTP_PORT` | 메일 서버 포트 | 론칭 시 선택 | ❌ Skip | 위와 동일 | `587` (TLS) / `465` (SSL) |
| `SMTP_USER` | SMTP 인증 계정 | 론칭 시 선택 | ❌ Skip | 위와 동일 | `no-reply@kokchal.com` |
| `SMTP_PASSWORD` | SMTP 인증 비밀번호 | 론칭 시 선택 | ❌ Skip | 위와 동일 (Gmail은 앱 비밀번호 발급 필요) | `abcd efgh ijkl mnop` |

- **언제 필요한지**: 등기부 발급 완료 알림, 결제 영수증, 구독 만료 예정 안내 등 **알림 기능을 새로 만들 때**
- **코드 참조 여부**: 없음(저장소 전체 grep 0건)
- **비고**: Supabase Auth 메일(가입 확인/비밀번호 재설정)은 이 설정과 무관하게 Supabase 쪽에서 처리된다

---

# 6. SMS

현재 저장소에 SMS 발송 코드가 **전혀 없다**. **지금은 전부 Skip 가능**하다.

| 변수명 | 설명 | 필수 | 현재 필요 | 발급 위치 | 예시 |
|---|---|---|---|---|---|
| `SMS_API_KEY` | SMS 발송 API 키 | 론칭 시 선택 | ❌ Skip | SMS 제공사(NHN Toast/Solapi/알리고 등) 콘솔 | `NCSKEY-xxxxxxxx` |
| `SMS_SECRET` | SMS API 서명용 비밀키 | 론칭 시 선택 | ❌ Skip | 위와 동일 | `s3cr3t-xxxxxxxx` |

- **언제 필요한지**: 매각기일 임박 알림, 등기부 발급 완료 알림 등 **실시간성이 중요한 알림**을 붙일 때
- **코드 참조 여부**: 없음
- **비고**: 광고성 문자를 보내려면 수신동의 및 야간 발송 제한 등 정보통신망법 준수가 선행돼야 한다

---

# 7. Google Analytics

## GA4_MEASUREMENT_ID

| 항목 | 내용 |
|---|---|
| 구분 | Analytics |
| 설명 | GA4 측정 ID. 페이지뷰/전환 추적용 |
| 필수 여부 | 선택 |
| 언제 필요한지 | 베타 오픈 후 사용자 유입/전환(구독 결제) 분석 시작 시점 |
| 현재 필요한가 | **아니오 — 지금 Skip 가능** (분석 스크립트 미삽입) |
| 발급 위치 | Google Analytics → 관리 → 데이터 스트림 → 웹 스트림 세부정보 |
| 코드 참조 여부 | **없음** |
| 비고 | 프론트에서 쓰므로 `NEXT_PUBLIC_GA4_MEASUREMENT_ID` 형태가 되어야 하며, 공개되어도 무방한 값이다. 개인정보처리방침에 분석도구 사용 고지 필요 |
| 예시 | `NEXT_PUBLIC_GA4_MEASUREMENT_ID=G-XXXXXXXXXX` |

---

# 8. Sentry (에러 모니터링)

## SENTRY_DSN

| 항목 | 내용 |
|---|---|
| 구분 | Monitoring |
| 설명 | Sentry 프로젝트 DSN. 런타임 예외 자동 수집 |
| 필수 여부 | 선택 (운영 안정성 관점에서는 권장) |
| 언제 필요한지 | **론칭 직전** — 실사용자 트래픽에서 발생하는 예외를 놓치지 않으려면 오픈 전 설정이 바람직 |
| 현재 필요한가 | **아니오 — 지금 Skip 가능** |
| 발급 위치 | Sentry → Projects → 프로젝트 선택 → Settings → Client Keys (DSN) |
| 코드 참조 여부 | **없음** |
| 비고 | 프론트/백엔드 각각 별도 DSN을 두는 것이 일반적. 백엔드 DSN에는 `NEXT_PUBLIC_` 금지. 크롤러(`mvp_scraper.py`/`doc_worker.py`) 실패 추적에도 유용 |
| 예시 | `SENTRY_DSN=https://<key>@o0.ingest.sentry.io/0` |

---

# 9. Slack (운영 알림)

## SLACK_WEBHOOK_URL

| 항목 | 내용 |
|---|---|
| 구분 | Ops Notification |
| 설명 | Slack Incoming Webhook URL. 운영 이벤트를 채널로 전송 |
| 필수 여부 | 선택 |
| 언제 필요한지 | 크롤링 실패, 등기부 신청 접수, 결제 실패 등 **운영자가 즉시 알아야 하는 이벤트** 알림 |
| 현재 필요한가 | **아니오 — 지금 Skip 가능** |
| 발급 위치 | Slack API → Your Apps → Incoming Webhooks → Add New Webhook to Workspace |
| 코드 참조 여부 | **없음** |
| 비고 | URL 자체가 인증 수단이라 유출 시 누구나 채널에 메시지를 보낼 수 있다. `run_daily.bat`이 실패(exit 1)할 때 알림을 보내면 크롤링 중단을 조기에 발견할 수 있다(현재는 로그를 직접 봐야 함) |
| 예시 | `SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T000/B000/XXXX` |

---

# 부록 A. 지금 당장 해야 할 일

1. **`ADMIN_API_KEY` 설정** — 유일하게 "코드는 완성됐는데 값이 없어서 막혀 있는" 항목이다.
   설정 즉시 Admin API(등기부 신청 상태 관리)가 동작한다.

그 외 항목은 전부 현재 동작에 영향이 없다.

# 부록 B. 론칭 직전 체크리스트

- [ ] KG이니시스 사업자 계약 완료 → `KG_MID` / `KG_API_KEY` / `KG_SECRET_KEY` 발급
- [ ] `KGInicisProvider` 구현 + `_PROVIDERS` 등록 → `PAYMENT_PROVIDER=kginicis`
- [ ] Webhook 수신 엔드포인트 구현 + `KG_WEBHOOK_SECRET` 서명 검증
- [ ] 테스트 MID로 실결제 테스트 → 운영 MID 전환
- [ ] `SENTRY_DSN` 설정(예외 수집)
- [ ] `SLACK_WEBHOOK_URL` 설정(크롤링/결제 실패 알림)
- [ ] `GA4_MEASUREMENT_ID` 설정 + 개인정보처리방침에 고지
- [ ] 방화벽 설정 검토 (`docs/backend.md` 주의사항)

# 부록 C. 관련 문서

- `docs/decision-log.md` — PG사/구독 정책 확정 내역
- `docs/backend.md` — 인증 방식, API 목록, 확정 Spec 미반영 항목
- `docs/BUGS.md` — 알려진 이슈
