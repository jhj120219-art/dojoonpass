# API KEY / Secret Checklist

Status: Active
Last Updated: 2026-08-07 (Sprint 26)
Owner: CTO

## 이 문서의 위치

- **이 문서** = "지금 코드가 실제로 무엇을 읽는가 / 무엇이 없는가"의 **코드 기준 사실 대장**.
  카테고리별로 참조 지점(파일:라인)을 명시하고, 참조가 0건이면 0건이라고 적는다.
- `docs/ENVIRONMENT_VARIABLES.md` = 각 변수의 **발급 방법·예시 값·설정 절차** 상세 가이드.

둘이 어긋나면 **코드가 기준**이다. 실제 키 값은 어느 문서에도 적지 않는다.

**`.env` / `.env.local` 파일은 승인 없이 수정하지 않는다**(프로젝트 규칙). 이 문서는 무엇이
필요한지만 기술하며, 값 입력은 사용자가 직접 한다.

---

## 0. 한 장 요약 (2026-08-07 전수 조사)

코드가 실제로 읽는 환경변수는 **9개뿐**이다. 그 외 카테고리(OAuth / SMTP / Storage /
Analytics / Monitoring / SNS / OCR / 지도 / 메일 / Slack)는 **저장소 전체 참조 0건**이며,
따라서 지금 발급받을 키가 없다.

| # | 변수 | 파일 | 상태 |
|---|---|---|---|
| 1 | `SUPABASE_JWT_SECRET` | `.env` | ✅ 설정됨·동작 중 |
| 2 | `NEXT_PUBLIC_SUPABASE_URL` | `.env.local` | ✅ 설정됨·동작 중 |
| 3 | `NEXT_PUBLIC_SUPABASE_ANON_KEY` | `.env.local` | ✅ 설정됨·동작 중 |
| 4 | `NEXT_PUBLIC_API_BASE_URL` | `.env.local` | ✅ 설정됨·동작 중 |
| 5 | `ADMIN_API_KEY` | `.env` | ❌ **미설정 → Admin API 전체 500** (P0) |
| 6 | `PAYMENT_PROVIDER` | `.env` | ⬜ 미선언(선택). 미설정 시 `mock` — **현재는 이게 정상** |
| 7 | `CORS_ALLOW_ORIGINS` | `.env` | ⬜ 미선언(선택). 미설정 시 `*` — 운영 배포 시 지정 |
| 8 | `LOG_LEVEL` | `.env` | ⬜ 미선언(선택). 미설정 시 `INFO` |
| 9 | `SUPER_ADMIN_API_KEY` | `.env` | ⬜ 미선언(선택, 2026-08-07 신규). 없으면 SUPER_ADMIN 전용 기능 사용 불가 |

### 조사 방법 (재현 가능)

```bash
grep -rn "os.getenv\|os.environ\[" --include="*.py" .      # 백엔드가 읽는 값
grep -rn "process.env" src/                                 # 프론트가 읽는 값
```

---

## 1. 현재 코드가 실제로 읽는 값

### 1-1. `SUPABASE_JWT_SECRET` (`.env`)

| 항목 | 내용 |
|---|---|
| 참조 지점 | `api/auth.py:9` (모듈 로드 시 1회). `api/v1/item.py:6`, `api/v1/search.py:8`이 이 상수를 import |
| 용도 | Supabase가 발급한 JWT의 HS256 서명 검증 |
| 없으면 | 인증 필요 API 전부 `500 "JWT Secret 미설정"` |
| 현재 | ✅ 설정됨 |
| `NEXT_PUBLIC_` | **금지** (서버 전용 비밀값) |

### 1-2. `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY` (`.env.local`)

| 항목 | 내용 |
|---|---|
| 참조 지점 | `src/lib/supabaseClient.ts:10-11`, `src/lib/supabaseServer.ts:13-14`, `src/middleware.ts:14-15` |
| 용도 | 로그인/회원가입/세션 갱신 |
| 없으면 | 인증 전체 불가 (`!` non-null 단언이라 런타임에서 터짐) |
| 현재 | ✅ 설정됨 |
| 비고 | anon key는 브라우저 노출이 정상. 단 **Supabase 쪽 RLS 설정과 함께 관리**해야 한다 |

### 1-3. `NEXT_PUBLIC_API_BASE_URL` (`.env.local`)

| 항목 | 내용 |
|---|---|
| 참조 지점 | `src/lib/api.ts:5` |
| 용도 | FastAPI 백엔드 주소 |
| 없으면 | `http://localhost:8000`으로 폴백 — 개발은 되지만 **운영 배포 시 반드시 지정** |
| 현재 | ✅ 설정됨 |

### 1-4. `ADMIN_API_KEY` (`.env`) — ❌ 미설정, P0

| 항목 | 내용 |
|---|---|
| 참조 지점 | `api/v1/admin.py:27` (`require_admin`) |
| 용도 | `/api/v1/admin/*`의 `X-Admin-Key` 헤더 검증 (`hmac.compare_digest` 상수시간 비교) |
| 없으면 | Admin API 전체 `500 "관리자 키 미설정"` → **등기부 신청 상태를 아무도 못 바꾼다** |
| 발급 | 외부 발급 없음. 직접 생성: `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| 승인 | `.env` 수정 승인 필요 → **현재 Skip 상태** |
| 한계 | 역할(role) 구분 없음. 키를 아는 사람 = 전체 관리자. 유출 시 즉시 교체 |

### 1-4-1. `SUPER_ADMIN_API_KEY` (`.env`, 선택, 2026-08-07 신규)

| 항목 | 내용 |
|---|---|
| 참조 지점 | `api/v1/admin.py:resolve_admin_role()` |
| 용도 | Admin 권한 2단계 중 **SUPER_ADMIN** 등급 판정. 과금에 직접 영향을 주는 조작(등기부 무료횟수 조정) 전용 |
| 없으면 | `POST /api/v1/admin/registry-credits`가 403. ADMIN 등급 기능(신청 목록·상태 전이)은 정상 동작 |
| 발급 | 외부 발급 없음. 직접 생성하되 **`ADMIN_API_KEY`와 다른 값**이어야 등급 분리가 의미를 갖는다 |
| 비고 | 두 키가 같으면 더 높은 등급(SUPER_ADMIN)이 부여된다. `NEXT_PUBLIC_` 금지 |
| 예시 | `SUPER_ADMIN_API_KEY=<secrets.token_urlsafe(32) 결과>` |

### 1-5. `PAYMENT_PROVIDER` (`.env`, 선택)

| 항목 | 내용 |
|---|---|
| 참조 지점 | `api/v1/payment_providers.py:163` (`get_payment_provider`) |
| 허용값 | `mock`(기본) / `kginicis`(확정 PG사, **자리 구현**) / `toss`·`portone`(**폐기 예정**, 선택 시 경고 로그) |
| 그 외 값 | 허용값 목록을 포함한 `ValueError`로 즉시 실패 |
| 현재 | 미선언 = `mock`. **실연동 완료 전까지 이 상태가 정상** |
| 주의 | `kginicis`로 바꾸면 6개 메서드가 전부 `NotImplementedError`라 **모든 결제가 즉시 실패**한다 |

### 1-6. `CORS_ALLOW_ORIGINS` (`.env`, 선택, 2026-08-07 신규)

| 항목 | 내용 |
|---|---|
| 참조 지점 | `api_server.py:30` |
| 형식 | 콤마 구분 Origin 목록 (`https://a.com,https://b.com`) |
| 현재 | 미선언 = `*` 전체 허용 (기존 동작 유지) |
| 권장 | 운영 배포 시 프론트 도메인만 지정 |
| 비고 | 인증이 쿠키가 아닌 `Authorization: Bearer`라 CSRF 위험은 없지만, 전 도메인 개방을 유지할 이유도 없다 |

### 1-7. `LOG_LEVEL` (`.env`, 선택, 2026-08-07 신규)

| 항목 | 내용 |
|---|---|
| 참조 지점 | `api_server.py` (`logging.basicConfig`) |
| 값 | `DEBUG` / `INFO`(기본) / `WARNING` / `ERROR`. 알 수 없는 값이면 `INFO`로 폴백 |
| 배경 | 크롤러 계열은 전부 `basicConfig`를 호출하는데 **API 서버만 빠져 있어** root logger에 핸들러가 없고 기본 레벨이 WARNING이었다 → `logger.info`(Admin 상태 전이 감사 로그)가 통째로 버려지고 있었다 |
| 비고 | 비밀값이 아니다. `httpx`/`httpcore`/`urllib3`는 요청마다 INFO를 뱉으므로 WARNING으로 낮춰둔다 |

---

## 2. 론칭 시 필요 — KG이니시스 (전부 코드 참조 0건)

**PG사는 KG이니시스로 확정**(2026-08-06 CTO). 2026-08-07 기준 `KGInicisProvider` **클래스와
`PAYMENT_PROVIDER=kginicis` 경로는 코드에 반영 완료**됐으나, 6개 메서드는 전부
`NotImplementedError`인 자리 구현이다. **따라서 아래 4개 변수를 읽는 코드는 아직 없다.**

| 변수 | 용도 | 발급 위치 | 코드 참조 | 선행 조건 |
|---|---|---|---|---|
| `KG_MID` | 상점 아이디(Merchant ID) | 이니시스 가맹점 관리자 → 상점정보 | **0건** | 사업자 계약·심사 |
| `KG_API_KEY` | 승인/취소/조회 API 인증 | 가맹점 관리자 → API 키 관리 | **0건** | 위와 동일 |
| `KG_SECRET_KEY` | 요청 서명(해시) 생성 | 가맹점 관리자 (`signKey`/`iniapiKey` 계열) | **0건** | 위와 동일 |
| `KG_WEBHOOK_SECRET` | Webhook(입금통보/결제결과) 서명 검증 | 가맹점 관리자 → 노티(Noti) 설정 | **0건** | Webhook 수신 엔드포인트 구현 후 |

전부 서버 전용 — `NEXT_PUBLIC_` **금지**. `KG_SECRET_KEY`가 유출되면 결제 요청 위조가 가능하다.

### Redirect / Callback / Webhook URL (env가 아니라 **PG 관리자 콘솔 설정**)

실연동 시 이니시스 콘솔에 아래 URL을 등록해야 한다. **현재 이 URL을 처리하는 엔드포인트가
저장소에 하나도 없다** — 신규 구현 대상이다.

| 종류 | 필요한 것 | 현재 상태 |
|---|---|---|
| 결제 리턴 URL | 결제창에서 돌아올 프론트 경로 | 없음 (현재는 `create_order`→`confirm_payment`를 서버가 곧바로 이어 호출) |
| 서버 승인 콜백 | `confirm_payment`를 호출할 백엔드 엔드포인트 | 없음 |
| Webhook(노티) 수신 | `handle_webhook`을 호출할 백엔드 엔드포인트 | 없음 (`handle_webhook`은 인터페이스에만 존재, 호출부 0건) |
| 환불 | `cancel_payment` 호출부 | 없음 |

---

## 3. 코드 참조 0건 — 지금 발급받을 것이 없는 카테고리

아래는 요청받은 점검 카테고리를 **전부 코드에서 검색한 결과**다. 기능 자체가 없으므로
지금 키를 발급받아도 쓸 곳이 없다. 해당 기능을 신규 구현할 때 이 표를 갱신한다.

| 카테고리 | 필요해질 변수(예상) | 코드 참조 | 확인 방법 |
|---|---|---|---|
| **OAuth**(소셜 로그인) | `*_CLIENT_ID` / `*_CLIENT_SECRET` / Redirect URL | **0건** | `signInWithOAuth` 0건 — 로그인은 `signInWithPassword`(이메일+비밀번호) 단일 방식 |
| **SMTP / 메일** | `SMTP_HOST` `SMTP_PORT` `SMTP_USER` `SMTP_PASSWORD` | **0건** | `smtp`/`nodemailer`/`sendgrid`/`send_mail` 전부 0건 |
| **Storage** | `SUPABASE_SERVICE_ROLE_KEY`, 버킷명 | **0건** | `supabase.storage`/`createBucket` 0건. 파일은 로컬 디스크(`registry_documents/`, `documents/`)에서 서빙 |
| **Analytics** | `GA4_MEASUREMENT_ID` | **0건** | `gtag`/`googletagmanager` 0건 |
| **Monitoring** | `SENTRY_DSN` | **0건** | `sentry` 0건. 현재는 `logging` + `logs/*.log` 수동 확인 |
| **SNS 알림** | `SLACK_WEBHOOK_URL`, `SMS_API_KEY`/`SMS_SECRET` | **0건** | `slack` 0건, SMS 발송 코드 0건 |
| **OCR** | OCR 서비스 키 | **0건** | `tesseract`/`vision` 0건. `document_status`의 `OCR` 문자열은 **상태값 이름일 뿐** 실제 OCR 코드 아님 |
| **지도** | 카카오/네이버/구글 지도 키 | **0건** | 지도 SDK·geocoding 0건. 주소는 문자열로만 다룬다(`auction_item`에 위경도 컬럼 없음) |
| **크롤러** | — | **0건** | `crawler/`·`config/`에 계정/토큰 0건. courtauction.go.kr은 로그인 없이 스크래핑 |

---

## 4. env 파일 ↔ 코드 드리프트 (2026-08-07 실측)

```
.env / .env.local에 선언됨 :  SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_JWT_SECRET,
                              NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_ANON_KEY,
                              NEXT_PUBLIC_API_BASE_URL
코드가 읽지만 미선언       :  ADMIN_API_KEY, SUPER_ADMIN_API_KEY, PAYMENT_PROVIDER,
                              CORS_ALLOW_ORIGINS, LOG_LEVEL
선언됐지만 코드가 안 읽음  :  SUPABASE_URL, SUPABASE_ANON_KEY
```

### 해석

- **`ADMIN_API_KEY` 미선언 = P0.** 값이 없어 Admin API 전체가 500이다.
- `SUPER_ADMIN_API_KEY` 미선언은 P1이다 — 등기부 무료횟수 조정(CS 대응)이 불가능하다.
- `PAYMENT_PROVIDER` / `CORS_ALLOW_ORIGINS` / `LOG_LEVEL` 미선언은 **정상**이다. 셋 다 안전한
  기본값(`mock` / `*` / `INFO`)으로 폴백하도록 설계했다.
- **`SUPABASE_URL` / `SUPABASE_ANON_KEY`(`.env`)는 어떤 Python 코드도 읽지 않는다.**
  백엔드는 Supabase에 직접 접속하지 않고 JWT 서명만 검증하기 때문이다(`docs/decision-log.md`
  "Authentication" — 인증과 경매 데이터 분리). 프론트는 `NEXT_PUBLIC_` 버전을 따로 쓴다.
  → 지금은 **무해한 잔재**다. 삭제는 `.env` 수정이라 승인 필요 → Skip. 향후 백엔드가
  Supabase Admin API를 쓰게 되면 그때 실제로 필요해질 수 있으니 남겨두는 것도 합리적이다.

---

## 5. env가 아닌데 론칭 전 반드시 필요한 외부 설정

키 발급이 아니라 **대시보드 설정**이라 놓치기 쉬운 항목.

| 항목 | 어디서 | 왜 필요한가 |
|---|---|---|
| Supabase **Site URL / Redirect URLs** | Supabase 대시보드 → Authentication → URL Configuration | `signUpAction`이 "이메일을 확인하여 가입을 완료해주세요"를 반환한다 — 가입 확인 메일의 링크가 이 설정을 따라간다. `localhost:3000`인 채로 배포하면 **운영 사용자가 회원가입을 완료할 수 없다** |
| Supabase **RLS 정책** | 대시보드 → Table Editor → RLS | anon key는 브라우저에 노출된다. `/properties`가 조회하는 `properties` 테이블에 RLS가 없으면 누구나 읽을 수 있다 |
| KG이니시스 **콘솔 URL 등록** | 이니시스 가맹점 관리자 | 위 2절 표 참고 (리턴/콜백/노티 URL) |

---

## 6. 갱신 규칙

새 외부 연동을 붙일 때마다 **코드를 먼저 확인하고** 이 문서를 갱신한다.

1. `grep -rn "os.getenv" --include="*.py" .` / `grep -rn "process.env" src/` 로 참조 지점 확인
2. 1절(실제 읽는 값) 또는 3절(참조 0건) 중 맞는 표에 등록 — **참조 지점(파일:라인)을 반드시 적는다**
3. 4절 드리프트 목록을 다시 실측해 갱신
4. `docs/ENVIRONMENT_VARIABLES.md`에 발급 절차·예시 값을 추가
5. 실제 키 값은 어느 문서에도 적지 않는다


---

## 7. 2026-08-07 (Sprint 28) 갱신 — 신규 참조 없음

FK 강제 / 상태 머신 / 감사 로그 / Error Code / Enum 통합은 전부 **내부 구조 작업**이며
새로 읽는 환경변수가 없다. 1절의 9개 목록은 그대로 유효하다.

`api/constants.py`·`api/v1/state_machines.py`·`api/v1/audit.py`·`api/v1/subscriptions.py`는
외부 서비스를 호출하지 않는다(`grep "os.getenv" `로 재확인 — 신규 0건).
