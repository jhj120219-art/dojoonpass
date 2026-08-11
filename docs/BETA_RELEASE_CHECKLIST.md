# Beta Release Readiness

Status: Active
Last Updated: 2026-08-07 (Sprint 28)
Owner: Project Management

이 문서는 **지금 출시를 막는 것만** 다룬다. 이미 해소된 병목은 다시 올리지 않는다
(해소 이력은 `docs/CHANGELOG.md`, `docs/BUGS.md`에 있다).

분류 기준

- **P0** — 이게 남아 있으면 출시할 수 없다(돈을 받을 수 없거나, 핵심 동선이 깨진다)
- **P1** — 출시는 가능하지만 사용자가 즉시 체감하거나 운영이 불가능하다
- **P2** — 출시 후 처리해도 되는 품질/구조 부채

---

## 도메인별 현황 (2026-08-07 코드 기준)

| 도메인 | 상태 | 근거 |
|---|---|---|
| 회원가입 / 로그인 | ✅ | Supabase Auth 실동작, `proxy.ts` 세션 게이트(구 `middleware.ts`), Open Redirect 방어(`sanitizeRedirectPath`) |
| 로그아웃 | ⚠️ | 동작하지만 노출 경로가 `/properties` 한 곳뿐 (P1) |
| 크롤링 데이터 무결성 | ✅ | `auction_case`(#14) · `auction`/`auction_item`(#18) 전부 법원 포함 식별키로 해결. ID 전수 Audit 결과 orphan/중복/불일치 **0건** |
| 검색 | ✅ | 정렬 화이트리스트·페이지네이션·인덱스 확인, 회귀 커버 |
| 검색조건 저장 | ✅ | 서버측 입력 검증 추가(2026-08-07), 소유권 격리, 회귀 커버 |
| 최근조회 | ✅ | 중복 행 없음, 회귀 커버 |
| 즐겨찾기 | ✅ | N+1 제거 완료, 중복/소유권 처리, 회귀 커버 |
| 상세조회 | ✅ | 복합키 Migration 이후 `case.court_code` 일치 회귀로 방어 |
| 등기부 신청 | ✅ | 구독 게이트·월 한도·동시성(`BEGIN IMMEDIATE`)·초과결제 연결까지 회귀 커버 |
| 등기부 발급/전달 | ⚠️ | 다운로드 엔진은 완성. **발급은 운영자 수동**(자동화는 Beta v2) |
| 결제 | ❌ | `MockProvider` — 실제로 돈을 받을 수 없다 (P0). 단 **결제 로그/Webhook 구조는 선구축 완료**(실연동 시 Provider만 채우면 됨) |
| Subscription | ✅ | 플랜/할인/기간/한도 서버 검증, 플랜 tie-break 버그 수정(2026-08-07) |
| 관리자 | ⚠️ | API 완성 + **SUPER_ADMIN/ADMIN 2단계 권한**·등기부 한도 조정 추가. **키 미설정으로 현재 전체 500**, UI 없음 (P0/P1) |
| 문서 | ✅ | 2026-08-07 전수 감사 — 코드와 어긋난 서술 정정 완료 + `API_KEY_CHECKLIST.md` 신설 |
| Runtime | ✅ | Type Check / Lint / Build 전부 통과. **2026-08-08(Sprint 32) 최초로 HTTP 레벨 실제 실행**: `test_api_regression.py` **380검사**(377 + 신규 JWT 적대적 케이스 3건) 전부 PASS, `test_subscription_policy.py` **48항목** 전부 PASS(연속 2회 재실행으로 재현성 확인, 잔여 QA 데이터 0건) |
| 로깅/추적 | ⚠️ | 2026-08-07 API 서버 로깅 설정 신설(그 전엔 `logger.info` 전량 유실). 외부 수집(Sentry 등)은 없음 (P2) |

---

## P0 — 출시 차단

### ~~P0-0. 로컬 `auction.db`/`storage/migrations/`가 문서 기록과 불일치~~ → **2026-08-08 복구 완료**

- 발견(2026-08-08 오전): 이 작업 디렉터리의 `auction.db`/`storage/migrations/`(둘 다 git
  비추적)가 Migration 010~015 이전 상태로 되돌아가 있었다 — `docs/BUGS.md` #18(법원 무시
  UNIQUE 키로 인한 데이터 소실)이 이 DB 파일 기준 미해결이었고, `audit_logs`/`payment_logs`/
  `payment_webhooks`/`registry_credits`/`registry_credit_logs` 5개 테이블도 없었다. 실측
  중 `migrate_execute.py`(정상 코드)가 이 스키마에 대고 실행되면 `INSERT INTO auction_case`에서
  `court_code` 컬럼 부재로 **매일 크롤링 파이프라인이 크래시**하는 것도 함께 확인됨(Runtime Bug)
- 해결(같은 날, CTO 승인): `storage/migrations/010~016.sql` 재작성(코드의 실제 INSERT/SELECT
  문에서 컬럼 추출) → 백업 → 사본 리허설(FK ON/OFF 양쪽) → 실제 `auction.db` 적용 → 30개
  무결성 검증 항목 전부 통과 → `storage/database.py`(`upsert_batch()` court_code 안전화,
  `PRAGMA foreign_keys=ON`, `CREATE_TABLE_SQL` 정정) / `storage/migrate_v4_1.py`(fresh clone도
  같은 제약) 함께 수정 → fresh-clone 전체 부트스트랩(`init_db`→`migrate_v4_1`→`run_migrations`)
  재현 검증까지 완료. 상세는 `docs/CHANGELOG.md` 2026-08-08(Sprint 30) 항목,
  회귀는 `test_auction_identity.py`(신규, 26검사 전부 PASS) 참고
- **`.env`의 `SUPABASE_JWT_SECRET` 부재는 별개 사안으로 여전히 남아 있다** — `.env` 수정은
  승인 목록에 없어 이번에도 Skip. 아래 P0-3 참고

### P0-1. KG이니시스 실연동 미완료 (결제 불가)

- `KGInicisProvider`의 6개 메서드가 전부 `NotImplementedError`(2026-08-07 클래스 자리만 신설).
  현재 `PAYMENT_PROVIDER` 미설정 = `MockProvider` = **결제가 항상 성공으로 기록되지만 실제 입금은 없다.**
- 선행 조건: KG이니시스 사업자 계약·심사 → `KG_MID`/`KG_API_KEY`/`KG_SECRET_KEY` 발급
- 함께 필요: 환불(`cancel_payment`) / Webhook 수신(`handle_webhook`) 엔드포인트 신규 구현 —
  두 메서드는 인터페이스에만 있고 호출부가 없다
- **승인/외부 절차 필요 → 코드로 해결 불가**

### P0-2. `ADMIN_API_KEY` / `SUPER_ADMIN_API_KEY` — 변수명은 존재, 값 유효성 미확인

- **2026-08-08 재확인**: `.env`에 `ADMIN_API_KEY=`/`SUPER_ADMIN_API_KEY=` **변수명 자체는
  존재한다**(이전 문서가 "미설정"으로 기록했던 것과 달리 이름은 있음). 다만 이 세션은
  Secret 값을 열람/출력하지 않는 원칙이라 **실제로 유효한 값이 채워져 있는지는 확인하지
  않았다** — 값이 비어 있거나 형식이 잘못됐다면 여전히 `/api/v1/admin/*` 전체가
  `500 "관리자 키 미설정"`이 된다. 사용자가 직접 `.env`를 열어 값이 채워져 있는지
  확인 필요
- 값이 비어 있다면 생성: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
- **`.env` 수정은 승인 필요 → 이 세션에서는 확인만 가능, 수정 불가**

### P0-3. Supabase Site URL / Redirect URLs 미확인 (회원가입 완료 불가 위험)

- `signUpAction`은 "이메일을 확인하여 가입을 완료해주세요"를 반환한다 — 가입 확인 메일의 링크는
  Supabase 대시보드의 **Authentication → URL Configuration** 설정을 따라간다.
- 이 값이 `localhost:3000`인 채로 배포되면 **운영 사용자가 회원가입을 끝낼 수 없다.**
  코드로는 확인할 수 없는 외부 대시보드 설정이라 배포 전 반드시 눈으로 확인해야 한다.
- 2026-08-07 신규 등록 (`docs/API_KEY_CHECKLIST.md` 5절)

### P0-4. **[2026-08-08 신규]** `.env`에 `SUPABASE_JWT_SECRET` 변수명 자체가 없음 (인증 전체 불가)

- `api/auth.py:9`가 `os.getenv("SUPABASE_JWT_SECRET")`을 읽는데, 현재 `.env`에는 이 이름이
  없다(`JWT_SECRET`이라는 **다른 이름**만 존재 — `docs/ENVIRONMENT_VARIABLES.md`가 이미
  경고해온 바로 그 이름 실수). 값이 아니라 **변수명 자체가 코드와 불일치**하므로, 어떤 값을
  넣어도 `JWT_SECRET`이라는 이름으로는 작동하지 않는다
- 영향: `get_current_user()`가 `500 "JWT Secret 미설정"`을 반환 — 인증이 필요한 API
  (favorites/recent-items/search-presets/registry-requests/payments) **전체가 막힌다**.
- **2026-08-08 갱신**: `python-jose`는 승인 하에 설치 완료(P1-x 아래 갱신 참고). 회귀 스크립트
  (`test_api_regression.py`)는 `.env`에 이 이름이 없을 때만 **이 프로세스 안에서만 유효한
  합성 값**을 주입하도록 수정해(`ADMIN_API_KEY`와 동일한 기존 패턴) 380검사(377+신규 3건) 전부
  실제 HTTP 레벨로 통과했다 — **이것은 인가·서명 검증 로직 자체가 옳다는 증거**이지, 실제
  운영 `.env`가 고쳐졌다는 뜻이 아니다. 운영 배포에는 여전히 `.env`에 정확한 이름으로 진짜
  Supabase JWT Secret을 넣어야 한다 — 이 항목은 **여전히 P0**
- **2026-08-09 분류 확정**(사용자 요청, `JWT_SECRET`/`SUPABASE_JWT_SECRET`/`NEXTAUTH_SECRET`
  3개 변수명 코드 전체 재검색, 값은 열람하지 않음):
  - `SUPABASE_JWT_SECRET` — **실제로 별도 필요함**(분류 1). `api/auth.py`(모듈 최상단 로드 +
    `get_current_user()`), `api/v1/item.py`/`api/v1/search.py`(선택적 인증 경로),
    `test_api_regression.py`(테스트 토큰 서명)까지 전부 이 이름 하나로 통일되어 있다.
    다른 이름으로 대체하도록 설계된 적이 없다(분류 2 해당 없음)
  - `JWT_SECRET`(현재 `.env`에 있는 이름) — 코드 참조 **0건**. **분류 3(잘못된 변수명으로
    남은 값)**. Supabase의 실제 JWT Signing Secret일 가능성이 높지만 이름이 코드와 달라
    인식되지 않는다
  - `NEXTAUTH_SECRET`/`NEXTAUTH_URL` — 코드 참조 0건, `next-auth` 패키지 자체도 참조 0건.
    **분류 3(완전히 무관한 잔재)** — 이 프로젝트는 NextAuth.js를 쓰지 않는다(Auth는
    Supabase Auth로 확정, `docs/decision-log.md` "Authentication"). 옮겨 담을 대상이
    아니라 그냥 미사용 항목
- 조치: `.env`에서 `JWT_SECRET`의 **값**을 `SUPABASE_JWT_SECRET`이라는 **이름**으로 옮기거나
  (기존 `JWT_SECRET` 항목은 그대로 둬도 무해 — 코드가 안 읽으므로), 같은 값을
  `SUPABASE_JWT_SECRET`이라는 이름으로 추가 입력하면 해결된다 — Supabase 대시보드
  → Project Settings → API → JWT Settings에서 같은 값을 다시 확인 가능. `NEXTAUTH_SECRET`은
  건드릴 필요 없음(무관)
- **`.env` 수정은 승인 필요 → 이 세션에서는 확인만 가능, 수정 불가**. 사용자가 `.env`에서
  `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`/`SUPABASE_SERVICE_ROLE_KEY`를 이미 입력해 둔 것으로
  보아(2026-08-08, `docs/API_KEY_CHECKLIST.md` 8절) Supabase 키 자체는 준비돼 있을 가능성이
  높다 — `SUPABASE_JWT_SECRET`이라는 정확한 이름으로 옮겨 담는 작업만 남았을 수 있다

---

## P1 — 출시는 가능하나 즉시 체감/운영 부담

### ~~P1-0. 레거시 `auction` 키에 법원이 빠져 물건이 소실됨~~ → **2026-08-07 해결**

CTO 승인 하에 Migration 012/013 실행. `auction` → `UNIQUE(court_code, case_no, item_no)`,
`auction_item` → `UNIQUE(case_id, item_no)`. id·전 컬럼 100% 보존, 충돌 시 두 법원 공존 확인.
회귀 방어: `test_api_regression.py` 22번, `test_subscription_policy.py` 7번.

### P1-1. `/properties` 첫 화면의 id 체계 불일치 (`docs/BUGS.md` #17)

- `/`가 로그인 사용자를 `/properties`로 보내는데, 그 화면은 Supabase `properties` 테이블을
  조회하면서 링크는 FastAPI `auction_item` id 기준인 `/properties/{id}`로 건다 —
  **로그인 직후 첫 화면에서 물건을 클릭하면 엉뚱한 물건이 열리거나 404.**
- 우회 동선은 있다(`PrimaryNav`의 "검색" → `/search`는 정상).
- 처리 방향(FastAPI 전환 vs 화면 폐지 후 `/`를 `/search`로)이 **Spec 결정 사항**.

### P1-2. 로그아웃 노출 경로가 1곳뿐 (`docs/BUGS.md` #15)

- `/search`, `/favorites`, `/properties/recent`에서는 로그아웃 불가(`PrimaryNav`에 없음).
- 하필 유일한 경로가 P1-1의 문제 화면이다.
- 배치 위치가 **Spec 결정 사항**.

### P1-3. Admin 화면(UI) 부재

- 운영자가 curl / Swagger UI로만 등기부 상태를 관리해야 한다.
- 신규 화면이라 **Spec 결정 필요**.

### P1-4. Admin 인증이 여전히 키 기반 — 개별 운영자를 특정할 수 없다

- 2026-08-07 **SUPER_ADMIN / ADMIN 2단계 권한을 도입**해 과금 영향 조작(등기부 한도 조정)은
  분리했다. 감사 로그에도 수행 등급이 남는다.
- 그러나 등급 안에서는 여전히 공유키라 **"어느 사람이" 했는지는 알 수 없다.**
  키 유출 시 그 등급 권한 전체가 노출되는 것도 그대로다.
- 사용자 단위 식별이 필요하면 Supabase custom claim 기반 인증으로 교체해야 한다 — **승인 필요**.

### P1-5. Rate Limit 전무

- Admin 키 무차별 대입, 검색/결제 API 남용을 막는 장치가 없다.
- 미들웨어/패키지 도입 필요 — **패키지 설치 승인 필요**.

---

## P2 — 출시 후 처리

- `src/login/`이 라우팅되지 않는 죽은 코드로 남아 있고, 금지된 옛 브랜드명
  "도준 경매 패스"를 사용 중 — **삭제 승인 필요**
- `properties/page.tsx`의 지역 `formatPrice`가 공용 구현과 다르게 동작(`0` → `"0.0억"`).
  P1-1과 같은 화면이라 함께 처리하는 것이 맞다
- `LIKE` 필터의 `%`/`_` 이스케이프 미처리 — 보안 문제는 아니고 와일드카드 의미론.
  `search.py` 전체 검색 동작이 바뀌므로 PM 확인 후
- Admin 목록의 `JOIN auction_item`이 INNER — 물건이 사라진 신청이 목록에서 통째로 빠진다
  (현재 DELETE 경로가 없어 실제 발생은 안 함)
- **[2026-08-07 신규]** 활성 구독 조회·초과결제 대상 선택 쿼리가 `user_id` 인덱스가 아니라
  `status` 인덱스를 타고 TEMP B-TREE 정렬을 만든다(실행계획 실측). `(user_id, status)` 복합
  인덱스가 적합하나 **스키마 변경 승인 필요**
- **[2026-08-07 신규]** `favorites` / `payments` / `registry-requests` 목록에 **LIMIT이 없다.**
  현재 사용자당 최대 보유 행이 0건이라 실제 문제는 없지만 구조적으로 무제한이다.
  페이지네이션 도입은 응답 구조 변경(Breaking Change)이라 승인 필요
- **[2026-08-07 신규]** 외부 로그/예외 수집(Sentry 등) 없음 — 서버 로깅 설정은 2026-08-07
  신설했으나 stdout 스트림뿐이라 운영에서 과거 로그를 되짚기 어렵다 (**CTO 보류 지정**)
- ~~`PRAGMA foreign_keys = 0`~~ → **2026-08-07 해결**(Sprint 28)
- **[2026-08-07 신규, 환경 문제] 저장소가 OneDrive 동기화 폴더 안에 있어 빌드가 간헐적으로
  실패한다.** `npm run build`가 이전 빌드ID 디렉터리(`.next/static/<buildId>/`, 매니페스트 3개)를
  정리하려 할 때 OneDrive가 잠그고 있으면 `EPERM ... unlink`가 난다. 이번 세션에서 두 번 발생했고
  둘 다 그 디렉터리를 **삭제하지 않고 옮겨서** 해결했다.
  근본 해결은 (a) 저장소를 OneDrive 밖으로 옮기거나 (b) `.next`를 OneDrive 동기화 제외로 설정하는
  것이다 — 둘 다 OS/외부 설정이라 **승인 필요**. 코드 문제가 아니며 Type Check·Lint는 항상 정상이다
- **[2026-08-07 신규]** Admin 실패 응답이 `{"detail": ...}`(HTTPException)이라 envelope·Error Code를
  쓰지 않는다. 통일하려면 클라이언트가 `status_code`로 분기하는 방식을 바꿔야 해 **Spec 결정 필요**
- **[2026-08-07 신규]** Soft Delete가 컬럼 추가까지만 적용됐다. 실제 전환은
  `UNIQUE(user_id,item_id)` 때문에 재등록이 막히는 문제를 먼저 풀어야 한다
- DB 백업 체계 없음(수동 타임스탬프 백업만), SQLite 단일 파일 운영
- 크롤러 계열 스크립트(`test_db.py` 등)는 이 환경에서 실행되지 않는다 — 이유가 두 겹이다:
  (1) selenium 미설치, (2) **2026-08-11부터 `ALLOW_LIVE_CRAWL=1` 없이는 실행 자체가 막힌다**
  (BUGS #51 — 이름은 test_*.py지만 assert가 0개이고 실제 법원 사이트에 접속한다).
  회귀 스윕은 이 셋을 '실패'가 아니라 '설계상 건너뜀'으로 분류해야 한다
  (패키지 설치 승인 필요)
- 권리분석 화면이 스텁 — `registry_rights` 테이블 + OCR/파싱 파이프라인 신규 구축 필요(Beta v2)
- 등기부 발급기관 자동 연동(Beta v2 범위, Beta v1 출시를 막지 않음)

---

## 이번 회차에 새로 등록된 것만

- **P0-3** Supabase Site URL / Redirect URLs 미확인 — 2026-08-07 신규 발견
- **P1-1** `/properties` id 불일치 — 2026-08-07 신규 발견
- **P2** `formatPrice` 지역 구현 차이 — 2026-08-07 신규 발견
- **P2** `LIKE` 이스케이프 / Admin INNER JOIN — 2026-08-07 신규 발견
- **P2** `.next` 잔여 아티팩트로 build 실패 / Admin 응답 형식 미통일 / Soft Delete 미전환 — 2026-08-07 신규
- **P2** 구독/초과결제 쿼리의 인덱스 선택 · 목록 LIMIT 부재 · 외부 로그 수집 부재 — 2026-08-07 신규 발견

그 외 P0/P1 항목은 이전 회차에서 이미 등록된 것으로, 상태만 갱신했다.

**Sprint 28에서 해소되어 목록에서 내려간 항목**: FK 미강제(P2), 결제/구독 상태 전이 검증 부재,
Admin 작업 이력 추적 불가, 무료횟수 변동 추적 불가, Error Code·Enum 산재.

**Sprint 27에서 해소되어 목록에서 내려간 항목**: P1-0(레거시 `auction` 키 물건 소실, #18),
프론트/서버 가격 이중 관리(`PLAN_OPTIONS` 제거 + Plan API), Admin 단일 등급(2단계 도입),
결제 궤적 추적 불가(payment_logs), 등기부 한도 CS 대응 수단 부재(registry_credits).

Sprint 26에서 해소되어 **목록에서 내려간 항목**: Lint 오류 2건, 구독 플랜 tie-break 버그,
Admin 목록 페이지네이션 비결정성, `layout.tsx` 기본 메타데이터, 문서-코드 불일치 다수,
**API 서버 로깅 설정 부재**(감사 로그가 전량 유실되던 문제), **OpenAPI Duplicate Operation ID**,
미사용 import 2건.
