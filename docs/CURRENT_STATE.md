현재 브랜치

master (2026-08-05 기준 재확인. 이전 버전은 "main"으로 기재되어 있었으나 실제 브랜치명과 다름)

현재 작업

Sprint 13(run_daily.bat 실패 은폐 구조 개선) + Sprint 14(구독 플랜 UI, Technical Debt/문서
동기화 리뷰) + Sprint 15(Security/Type/Performance Review) + Sprint 16(Bug Fix — case_no
충돌 발견) + Sprint 17(잔여 Backend/Lint 감사) + Sprint 18(전체 재감사 — Duplicate Code 제거,
mvp_scraper.py 로그 디렉터리 버그 수정) + Sprint 19(크롤러 파이프라인 전 모듈 재감사 — SIDO_MAP
중복 제거, config/settings.py Dead Code 발견·기록) + Sprint 20(`api_server.py` host 바인딩
문서 정정 — 0.0.0.0로 기재돼 있던 문서를 실제 코드값 127.0.0.1로 수정, git 이력으로 근거 확인)
+ Sprint 21(남은 미독파일 전수 감사 — 로그아웃 기능 공백 발견, logs/*.py Dead Code 발견)
+ Sprint 22(CTO 확정사항 3건 기준 저장소 전체 문서 동기화 — PG=KG이니시스, 구독 정책 베이직/프로,
auction_case 복합키) + Sprint 23(Migration 실행 + 구독 정책 구현 + 로그아웃)
+ Sprint 24(승인사항 전수 검증 + 할인 구조 확장 + 정책 회귀 테스트)
+ Sprint 25(전 도메인 회귀 테스트 100+ / Code·Performance·Security Audit)
+ Sprint 26(2026-08-07 — PG 명칭 KG이니시스 기준 정리 / Admin·Release Audit / 정렬 결정성 버그
수정 / Lint 0건화 / 기술부채·보안 하드닝 / API KEY Checklist 신설 / **레거시 auction 키 데이터
소실 결함 발견(#18)** / 회귀 163+33검사)
+ Sprint 27(2026-08-07 — **CTO 승인 6건 반영**: BUG #18 Migration 012/013 / Plan API 서버화 /
ID 체계 전수 Audit / Admin 2단계 권한 / 결제 로그 구조 / registry_credit 원장 / 회귀 227+48검사)
+ Sprint 28(2026-08-07 — **CTO 추가 승인 10건 반영**: FK 런타임 강제 / Payment 상태머신 /
Subscription Lifecycle / registry_credit_logs / audit_logs / Soft Delete 컬럼 / Admin REST 구조 /
Response 표준화 / Error Code / Enum 통합 / **승인 항목 연결 누락 2건 수정**(USAGE 로깅,
Lifecycle↔이용권 게이트) / 회귀 377+48검사, 변이 감사 8/8 검출, 프론트엔드 Audit) 완료
→ 승인 없이 가능한 작업 소진, 다음은 승인 대기

**Release Blocking 현황 (2026-08-07 갱신)**: `auction_case` UNIQUE 충돌은 Migration으로 해소됐고,
확정 구독 정책(플랜명/가격/연결제/등기부 월리셋)과 로그아웃 공백도 해결됐다. 결제는
**KG이니시스 실연동**만 남았으며 사업자 계약·API Key 발급이 선행돼야 해 의도적으로 연기 중이다
(현재 `MockProvider` 유지).

2026-08-07에 발견한 데이터 소실 결함(`docs/BUGS.md` #18 — 레거시 `auction` 키에 법원 누락)은
같은 날 **CTO 승인 하에 Migration 012/013으로 해결**했다. 이제 `auction`은
`UNIQUE(court_code, case_no, item_no)`, `auction_item`은 `UNIQUE(case_id, item_no)`다.

**테스트 커버리지(2026-08-07 기준)**: 회귀 테스트 2종을 상시 실행 가능하다.
- `python test_subscription_policy.py` — 구독 정책/할인 구조/월 리셋/식별키 무결성/credit 원장 (48항목)
- `python test_api_regression.py` — 전 도메인 실제 HTTP 회귀 (**377 검사**, 테스트 데이터 자동 정리).
  Sprint 26에서 Payment Provider 레지스트리 / 정렬 결정성 / 구독 플랜 tie-break /
  검색조건 저장 입력검증 4개 섹션 추가

**품질 게이트(2026-08-07)**: Type Check 통과 / **Lint 0 오류**(기존 2건 해소) / `npm run build` 통과 /
회귀 377검사 + 48항목 전부 통과. 변이 감사(mutation) 8/8 검출로 테스트 유효성 실증.

완료

☑ middleware (Supabase 세션 게이트, `/properties/*`)

☑ Supabase Auth (로그인/회원가입/세션)

☑ Search (`/search`, `api/v1/search.py`, D7 종결물건 기본 필터 포함)

☑ Detail (`/properties/[id]`, `api/v1/item.py`)

☑ Favorites (`/favorites`, `api/v1/favorites.py`)

☑ Recent Items (`/properties/recent`, `api/v1/recent_items.py`)

☑ Payment Mock API (`api/v1/payments.py`, 2026-08-05)

☑ Subscription 자동 생성 (결제 성공 시)

☑ Premium 판정 (`has_active_subscription()`, Registry 신청 게이트로 실사용 중)

☑ Registry 프론트 연동 (`properties/[id]/page.tsx`가 `registry-requests`/`payments` 직접 호출, 기존 Supabase `view_counts` 구현은 삭제)

☑ OVERAGE_USAGE 결제 → `registry_requests.payment_id`/`status` 자동 연결 (트랜잭션, 중복방지, rollback)

☑ Admin MVP (`api/v1/admin.py` — 목록조회/필터/상태전이/completed_at/reason, `X-Admin-Key` 인증)

☑ Registry Download Engine (`GET /registry-requests/{id}/download` 실제 파일 서빙, Admin `doc_url` 연결, 본인확인+경로탐색 방지, `registry_documents/` 신규 디렉터리) — 자동 등기부 수집기는 아님(운영자 수동 배치)

☑ Registry Download UI (`properties/[id]/page.tsx`: `COMPLETED`→다운로드 버튼, `FAILED`→사유 표시. 실제 브라우저에서 다운로드 폴더에 파일 저장까지 Runtime QA 확인)

☑ Payment Provider 구조 분리 (`api/v1/payment_providers.py` — `MockProvider`(사용 중) / `KGInicisProvider`(확정 PG사, 자리) / `TossProvider`·`PortOneProvider`(폐기 예정), `PAYMENT_PROVIDER` 환경변수로 선택, 기본값 mock)

☑ Payment Provider Interface v2 (`create_order`/`confirm_payment`/`cancel_payment`/`verify_payment`/`handle_webhook` 추가, `MockProvider` 전부 구현. `KGInicisProvider`/`TossProvider`/`PortOneProvider`는 자리만 — 호출 시 `NotImplementedError`)

☑ KG이니시스 Provider 자리 신설 (2026-08-07 — `KGInicisProvider` + `PAYMENT_PROVIDER=kginicis` 허용값. 실제 API 호출 구현은 계약/키 발급 필요로 승인 대기)

☑ Payment Flow Migration (`payments.py`가 `create_order`→`confirm_payment`→`verify_payment` 순서로 provider 호출, `SUBSCRIPTION`/`OVERAGE_USAGE` 둘 다 새 Flow로 정상 동작 확인. `cancel_payment`/`handle_webhook`은 여전히 미연결)

☑ `SUBSCRIPTION` 결제 금액 서버 검증 (`PLAN_PRICES`, `OVERAGE_USAGE`와 동일 방식 — 이제 둘 다 완료)

☑ 등기부 무료횟수 레이스 컨디션 수정 (`registry.py`에 `BEGIN IMMEDIATE` 적용, 5/10/20 스레드 동시 요청 테스트로 재검증 — Release Blocking 해소)

☑ run_daily.bat 실패 은폐 구조 개선 (2026-08-06, Sprint 13 — errorlevel 체크 추가, 실패 시 즉시 종료 + 로그 기록)

☑ 구독 플랜 비교/선택 UI (2026-08-06, Sprint 14 — `properties/[id]/page.tsx`, 플랜 비교·선택 후 구독 (현재는 BASIC/PRO + 월/연 토글, Sprint 23에서 갱신))

☑ Admin Key 타이밍 공격 방어 (2026-08-06, Sprint 15 — `api/v1/admin.py:require_admin()`, `hmac.compare_digest()`로 상수 시간 비교)

☑ 로그인 Action 타입 개선 (2026-08-06, Sprint 15 — `login/actions.ts`의 `any` 2건 제거, lint 오류 5→3건)

☑ 즐겨찾기 N+1 쿼리 제거 (2026-08-06, Sprint 15 — `favorites.py:get_favorites()`를 `recent_items.py`와 동일한 단일 JOIN으로 교체)

☑ Lint 정리 (2026-08-06, Sprint 17 — `supabaseServer.ts`의 미사용 catch 변수 제거, Lint 문제 3→2건)

☑ formatPrice 중복 제거 (2026-08-06, Sprint 18 — `src/lib/format.ts` 신규, 동일 구현 3곳 통합)

☑ mvp_scraper.py logs 디렉터리 버그 수정 (2026-08-06, Sprint 18 — `os.makedirs("logs", exist_ok=True)` 추가, fresh clone에서 즉시 크래시하던 문제)

☑ 크롤러 식별키 정상화 (2026-08-07, Sprint 27 — `auction` `UNIQUE(court_code, case_no, item_no)` / `auction_item` `UNIQUE(case_id, item_no)`. Migration 012/013, 데이터 소실 원인 제거)

☑ Plan API 서버화 (2026-08-07, Sprint 27 — `GET /api/v1/plans`가 플랜/가격/할인/한도의 단일 SoT. 프론트 `PLAN_OPTIONS` 하드코딩 제거)

☑ Admin 2단계 권한 (2026-08-07, Sprint 27 — `SUPER_ADMIN`/`ADMIN`. 기존 `ADMIN_API_KEY`는 ADMIN으로 하위호환)

☑ 결제 로그 구조 (2026-08-07, Sprint 27 — `payment_logs`/`payment_webhooks` + 멱등 Webhook + 민감정보 마스킹 + `GET /payments/{id}/logs`. 실연동 없음)

☑ 등기부 무료횟수 관리자 조정 (2026-08-07, Sprint 27 — `registry_credits` 조정 원장, GRANT/DEDUCT/RESET, SUPER_ADMIN 전용)

☑ FK 런타임 강제 (2026-08-07, Sprint 28 — `PRAGMA foreign_keys=ON`. 15개 FK가 선언만 되고 무시되던 상태 해소)

☑ Payment 상태머신 / Subscription Lifecycle (2026-08-07, Sprint 28 — 전이 규칙 검증, 유예기간 3일, 배치 없는 자동 만료. **이용권 게이트(`has_active_subscription`)까지 연결 완료** — 만료 후 3일 이내 사용자는 계속 이용 가능)

☑ audit_logs / registry_credit_logs (2026-08-07, Sprint 28 — Admin 작업·무료횟수 변동 전수 추적)

☑ Error Code / Enum 통합 (2026-08-07, Sprint 28 — `api/constants.py`, `docs/ERROR_CODES.md`. 값 무변경)

☑ Admin REST 구조 (2026-08-07, Sprint 28 — `/admin/users|payments|subscriptions|registry|audit-logs` 신설, 기존 경로 유지)

☑ SIDO_MAP 중복 제거 (2026-08-06, Sprint 19 — `validator/validation_engine.py`가 `normalizer.py`의 `SIDO_PATTERNS` 재사용, 값/동작 무변화)

진행중

☑ ~~**[Release Blocking]** `auction_case.case_no` 전국 UNIQUE 충돌~~ → **2026-08-06 Migration 실행 완료** (`011_auction_case_court_code_unique.sql`, `UNIQUE(court_code, case_no)`. 1,377→1,380건, court mismatch 0건)

☑ ~~**[기능 공백]** 로그아웃 UI 미노출~~ → **2026-08-06 해결** (`properties/page.tsx` 헤더에 `LogoutButton` 연결)

□ `ADMIN_API_KEY`를 `.env`에 설정 (Admin 코드는 완료, 값 미설정으로 현재 500)

☑ ~~**[확정 Spec 미반영]** 구독 정책 코드 반영~~ → **2026-08-06 반영 완료**: `BASIC` 12,900원/월·154,800원/년·월5회, `PRO` 22,900원/월·연 정상가 274,800원→**판매가 198,000원**·월10회. 할인은 `list_price`/`sale_price` 분리 구조로 하드코딩하지 않음

다음

□ ~~PG사 확정~~ → **2026-08-06 KG이니시스로 확정(CTO)**, ~~`KGInicisProvider` 신설~~ → **2026-08-07 완료**(클래스 + `PAYMENT_PROVIDER=kginicis` 허용값, 6개 메서드는 `NotImplementedError` 자리 구현). 남은 작업: Interface v2 6개 메서드의 **실제 KG이니시스 API 호출 구현** (외부 API Key/계약 필요 — 승인 대기). `TossProvider`/`PortOneProvider`는 폐기 예정 표기 + 선택 시 경고 로그

□ 환불(`cancel_payment`)/Webhook(`handle_webhook`) 엔드포인트 신규 구현 — 여전히 미연결

□ **[2026-08-07 발견]** `/properties`(로그인 후 첫 화면)가 Supabase `properties` 테이블을 조회하면서
링크는 `/properties/{id}`(FastAPI `auction_item`)로 보낸다 — id 채번 체계가 달라 엉뚱한 물건이
열리거나 404. 화면 처리 방향이 Spec 결정 사항이라 미착수 (`docs/frontend.md` 알려진 문제점)

□ Admin 화면(UI) 부재 — API만 존재. 신규 화면이라 Spec 결정 필요

□ 전 API Rate Limit 부재 — 미들웨어/패키지 도입 필요(승인 대기)

☑ ~~**[데이터 소실]** 레거시 `auction` 키에 법원 누락~~ → **2026-08-07 해결**
(Migration 012/013, `docs/BUGS.md` #18. id·전 컬럼 100% 보존, 충돌 시 두 법원 공존 확인)

□ **[2026-08-07 발견]** Supabase Site URL / Redirect URLs가 `localhost:3000`이면 운영 사용자가
회원가입을 완료할 수 없다 — 코드가 아니라 대시보드 설정이라 배포 전 육안 확인 필요
(`docs/API_KEY_CHECKLIST.md` 5절)

□ **[2026-08-07 발견]** 구독/초과결제 쿼리가 `user_id`가 아닌 `status` 인덱스를 타고 TEMP B-TREE
정렬 발생 — `(user_id, status)` 복합 인덱스 필요(스키마 변경 승인 대기)

□ **[2026-08-07 발견]** `favorites`/`payments`/`registry-requests` 목록에 LIMIT 없음 —
페이지네이션 도입은 응답 구조 변경(Breaking Change)이라 승인 대기

☑ ~~`PRAGMA foreign_keys = 0`(FK 미강제)~~ → **2026-08-07 해결**(Sprint 28 — `get_connection()`이
기본으로 `ON`, 마이그레이션만 예외. 고아 INSERT 차단 실측 확인)

□ (Beta v2) 등기부등본 실제 발급기관(대법원 인터넷등기소 등) 자동 연동

자세한 근거와 우선순위는 `docs/roadmap.md`("진행률 재계산" 섹션), `docs/backend.md` 참고.
