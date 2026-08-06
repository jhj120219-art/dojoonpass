2026-07-22

JWT 적용

Property API 변경

Mock 제거

---

2026-08-05

Payment Domain Infrastructure 구축 (Sprint 1)

- api/v1/payments.py 신규 (Mock 결제, PG 미연동)
- 결제 성공 시 subscriptions 자동 생성
- Premium 판정(has_active_subscription) 연결 확인

문서 동기화 (Roadmap / Backend / Architecture / CURRENT_STATE / decision-log / frontend / search-engine)

---

2026-08-05 (같은 날, 후속 Sprint)

Search: D7 종결물건 기본 필터 (`auction_date >= 오늘`, `include_closed` 옵션)

Registry Frontend 통합: `properties/[id]/actions.ts`(Supabase view_counts) 삭제,
`properties/[id]/page.tsx`가 `registry-requests`/`payments` 직접 호출

Payment → Registry 연결: OVERAGE_USAGE 결제 성공 시 `registry_requests.payment_id`/`status`
자동 갱신(트랜잭션, 중복방지, rollback), `registry.py`에 `OVERAGE_FEE` 상수 추출

Admin MVP: `api/v1/admin.py` 신규(목록조회/필터/상태전이/completed_at/reason),
`registry_requests.reason` 컬럼 추가(`010_add_registry_request_reason.sql`),
`X-Admin-Key` 인증 도입(`ADMIN_API_KEY`는 아직 `.env` 미설정)

문서 동기화 (Roadmap / Backend / CURRENT_STATE / frontend)

---

2026-08-05 (같은 날, Sprint 6 — Registry Download Engine)

Registry 신청 → 문서 다운로드까지 마지막 체인 완성:

- `GET /api/v1/registry-requests/{id}/download`가 더 이상 501이 아님 — 실제 파일 서빙
- `registry_documents/` 신규 디렉터리(`.gitignore`) — Admin이 파일을 배치하고 `doc_url`로 연결
- `PATCH .../admin/registry-requests/{id}`: `status=COMPLETED` 시 `doc_url` 필수화
- 본인 신청만 다운로드 가능(소유권 검사), 경로 탐색 방지(`documents.py`와 동일 패턴)
- 미완료 상태(PENDING/PROCESSING/FAILED)는 실제 상태를 그대로 응답에 포함

**주의**: 자동 등기부 수집 엔진이 아니다. 대법원 인터넷등기소 등 실제 발급기관과의 연동은
없으며, 운영자가 수동으로 발급받아 파일을 배치하는 구조 — `doc_worker`/`crawler`는 손대지
않음(STATUS/SPEC/APPRAISAL 수집과는 별개 경로).

문서 동기화 (Roadmap / Backend / CURRENT_STATE / architecture / decision-log)

---

2026-08-05 (같은 날, Sprint 7 — Registry Download UI)

Registry 신청 → 문서 다운로드까지, 프론트에서도 실제로 파일을 받을 수 있게 완성:

- `properties/[id]/page.tsx`: `COMPLETED`→"📥 등기부 다운로드" 버튼, `FAILED`→`reason` 표시
- `handleDownloadRegistry()`: 응답이 JSON(미완료)인지 실제 파일(COMPLETED)인지 `Content-Type`으로
  분기 → 파일이면 `blob`+`<a download>`로 브라우저 다운로드 실행
- `api/v1/registry.py`의 `GET /registry-requests`·`{id}`에 `reason` 필드 노출 추가
- `src/lib/api.ts`: `fetchAuthedRaw` 신규(JSON/파일 혼합 응답 처리용)
- `api_server.py` CORS에 `expose_headers=["Content-Disposition"]` 추가 — 브라우저가 기본적으로
  숨기는 헤더를 노출해 실제 파일명을 프론트가 읽을 수 있도록 함
- Runtime QA: 실제 Chrome 브라우저에서 버튼 클릭 → Downloads 폴더에 실제 파일 저장 확인

문서 동기화 (Backend / Frontend / Roadmap / CURRENT_STATE)

---

2026-08-05 (같은 날, Sprint 8 — PG Integration Preparation)

PG(Toss/PortOne) 실연동을 위한 기반 구조만 구축(실제 승인 로직은 아직 없음):

- `api/v1/payment_providers.py` 신규: `PaymentProvider`(인터페이스) → `MockProvider`(사용 중,
  기존과 100% 동일 동작) / `TossProvider`·`PortOneProvider`(자리만, 호출 시 `NotImplementedError`)
- `PAYMENT_PROVIDER` 환경변수(mock/toss/portone, 기본값 mock)로 provider 선택 — 미설정 시 기존과
  동일하게 동작(하위호환)
- `payments.py`: `create_mock_payment()` → `create_payment_record()`로 교체, `provider.charge()`
  결과를 그대로 기록. 라우터가 SQLite에 직접 쓰는 기존 구조는 유지(서비스 계층 아님)
- `SUBSCRIPTION` 결제 금액도 서버에서 검증(`PLAN_PRICES`: BETA_EARLYBIRD 9,900원 / STANDARD
  22,900원) — `OVERAGE_USAGE`(`OVERAGE_FEE`)와 동일한 방식. 이제 두 결제 유형 모두 금액 검증됨
- Runtime QA: 리팩터링 전후 Subscription/Overage/Registry/Premium/Download 체인이 100% 동일하게
  동작함을 확인. `PAYMENT_PROVIDER=toss`/`portone` 선택 시 자리만 있고 `NotImplementedError`
  발생함도 확인(의도된 동작)

문서 동기화 (Backend / Architecture / Roadmap / CURRENT_STATE)

---

2026-08-05 (같은 날, Sprint 9 — Payment Final Audit)

PG 실연동 전 마지막 감사. 코드는 수정하지 않고 감사만 수행:

- Payment 상태 전이 감사: `PENDING`/`REFUNDED`는 죽은 상태(코드에서 전혀 안 쓰임), `FAILED`는
  구조상 존재하나 MockProvider가 항상 SUCCESS라 현재 도달하지 않음
- DB 정합성 감사: SQLite FK가 앱에서도 강제되지 않음 확인(DELETE 경로 없어 실제 orphan은 없음).
  `registry.py`는 명시적 rollback이 없지만 `conn.close()`의 암묵적 rollback으로 안전함을 실측 확인
- Provider 구조 감사: 실제 Toss/PortOne 연동에는 웹훅/재검증/멱등성이 빠져 있어 부족함 확인
- Payment 정책 감사: `PLAN_PRICES`/`OVERAGE_FEE`/무료정책/30일정책 모두 코드-문서 100% 일치
- **Security 감사: 등기부 무료횟수 레이스 컨디션을 스레드 동시요청으로 실제 재현 — 5회 제한이
  8회까지 초과 소진됨을 확인 (Release Blocking, 다음 Sprint 최우선 수정 대상)**
- Runtime QA: Subscription/Premium/Registry/Download/Admin/Payment 전부 회귀 통과
- 부수 발견: `docs/backend.md`에 남아있던 stale 서술(`SUPABASE_JWT_SECRET 미입력`,
  `SUBSCRIPTION 금액 미검증`) 정정

문서 동기화 (Backend / Roadmap / CURRENT_STATE)

---

2026-08-05 (같은 날, Sprint 10 — Release Blocking Fix)

Sprint 9(Payment Final Audit)에서 발견한 등기부 무료횟수 레이스 컨디션 수정:

- `registry.py:create_registry_request()`에 `conn.isolation_level = None` + `BEGIN IMMEDIATE`
  적용 — 무료횟수 확인(COUNT)과 등록(INSERT)을 하나의 원자적 트랜잭션으로 묶음
- 기존 API 응답 구조, Frontend, DB 스키마는 전혀 변경하지 않음
- Runtime QA: 5/10/20 스레드 동시 요청 테스트 전부에서 정확히 5건만 무료 처리, 나머지는
  `PAYMENT_REQUIRED`로 정상 처리됨을 실증 확인(수정 전엔 5스레드로도 8건까지 초과됐음).
  DB 실측(`registry_usage`, `registry_requests`)으로도 재검증
- Subscription/Premium/Registry/Payment/Download/Admin/Search/Detail/Favorite 전부 회귀 통과
- **Release Blocking 항목 해소 — 현재 코드 기준 출시를 막는 알려진 버그 없음**

문서 동기화 (Backend / Roadmap / CURRENT_STATE)

---

2026-08-05 (같은 날, Sprint 11 — Payment Provider Interface v2)

실제 PG(Toss/PortOne) 연동을 위해 Provider 인터페이스를 확장(실제 PG API/Webhook 서버는
아직 구현하지 않음):

- `PaymentProvider`에 5개 메서드 추가: `create_order()` / `confirm_payment()` /
  `cancel_payment()` / `verify_payment()` / `handle_webhook()` — 기존 `charge()`는 그대로 유지
- `MockProvider`가 6개 메서드(기존+신규) 전부 구현, 항상 성공 응답
- `TossProvider`/`PortOneProvider`는 여전히 자리만 — 6개 메서드 전부 `NotImplementedError` 확인
- `api/v1/payments.py`는 전혀 수정하지 않음 — 여전히 `charge()`만 호출, 회귀 없음
- Runtime QA: `MockProvider` 직접 호출로 주문 생성→승인→검증→취소→Webhook Mock 전체 흐름 확인
- Subscription/Premium/Registry/Payment/Download/Admin/Search/Detail/Favorite 전부 회귀 통과

문서 동기화 (Backend / Roadmap / CURRENT_STATE)

---

2026-08-05 (같은 날, Sprint 12 — Payment Flow Migration)

`payments.py`를 Interface v2 흐름에 맞게 연결(실제 PG API는 여전히 붙이지 않음):

- `create_payment_record()`가 `provider.charge()` 대신 `create_order()` → `confirm_payment()` →
  `verify_payment()` 순서로 provider를 호출하도록 변경
- `MockProvider`는 수정하지 않음, `TossProvider`/`PortOneProvider` 구현도 하지 않음(범위 밖)
- 반환 시그니처(`payment_id`, `status`) 유지 — 구독 생성/등기부 연결 로직 등 호출부는 무수정
- Runtime QA: `SUBSCRIPTION`/`OVERAGE_USAGE` 둘 다 새 Flow로 정상 동작 확인
- Subscription/Premium/Registry/Payment/Download/Admin/Search/Detail/Favorite 전부 회귀 통과
- `cancel_payment()`/`handle_webhook()`은 이번에도 미연결(환불/Webhook 엔드포인트 자체가 없음)

문서 동기화 (Backend / Roadmap / CURRENT_STATE)

---

2026-08-06 (Sprint 13 — run_daily.bat 실패 은폐 구조 개선)

Sprint Backlog(P1)에 등록만 되어 있던 항목의 설계/구현:

- `run_daily.bat`: `mvp_scraper.py`/`migrate_execute.py` 실행 직후 `if errorlevel 1`으로
  즉시 확인, 실패 시 다음 단계로 넘어가지 않고 `exit /b 1` + 실패 로그(`[FAILED] <script>.py
  exited with code %errorlevel%`) 기록. 성공 시 `[SUCCESS] Finished at ...` 로그
- 이전 구조는 두 파이썬 스크립트 실행 줄 뒤에 조건 없는 `echo` 2줄이 항상 실행돼, 스크립트가
  실패해도 배치 마지막 명령(`echo`, 항상 성공)이 배치 전체 종료코드를 0으로 남기던 구조적
  결함이었음(Task Scheduler `LastTaskResult`가 실패를 인지 못함) — `migrate_execute.py`는
  이미 `sys.exit(0)/sys.exit(1)`을 정확히 반환하고 있었으므로 bat가 이를 확인만 하면 됐음
- Runtime QA: 격리된 스크래치 디렉터리에서 동일 구조의 더미 배치로 실패/성공 시나리오 각각
  실제 cmd.exe 실행 재현(exit code 1/0, 로그 메시지 모두 확인). 실제 크롤러(courtauction.go.kr
  대상)는 이번 QA에서 직접 실행하지 않음
- `run_doc_worker.bat`/`run_priority_refresh.bat`는 마지막 명령이 파이썬 호출이라 이미
  정상 동작 확인 — 수정 대상 아님
- `mvp_scraper.py` 내부 법원별 개별 예외 처리(부분 실패 시 계속 진행)는 기존 설계 유지,
  변경하지 않음(이번 Sprint 범위 밖)

문서 동기화 (Roadmap / crawler)

---

2026-08-06 (Sprint 14 — 구독 플랜 UI + Technical Debt/문서 동기화 리뷰)

Beta v1 Success Criteria는 이미 7/7 완료 상태라, Sprint Backlog 다음으로 roadmap "In Progress"
항목과 Technical Debt/문서 정합성을 점검:

**구독 플랜 비교/선택 UI 구현** (`src/app/properties/[id]/page.tsx`)
- 기존에는 "구독하기(베타 9,900원/월)" 단일 버튼으로 `BETA_EARLYBIRD`만 결제 가능했음
- `PLAN_OPTIONS`(BETA_EARLYBIRD 9,900원 / STANDARD 22,900원, `payments.py`의 `PLAN_PRICES` 미러)
  상수 추가, 두 플랜을 카드로 비교 표시하고 선택 후 구독하는 UI로 교체
- `handleSubscribe()`가 고정 plan 대신 선택된 plan을 받도록 시그니처 변경 — 호출하는
  `/api/v1/payments` 요청 바디 구조·필드명은 그대로 유지(서버가 금액을 다시 검증하므로 회귀 없음)
- Type Check(`tsc --noEmit`)/Build(`next build`) 통과 확인. Lint는 기존에 존재하던 4개 오류(다른
  파일 3곳 + 이 파일의 무관한 기존 줄 1곳)만 그대로 존재함을 수정 전/후 비교로 확인(신규 오류 없음)
- 로컬 Turbopack dev 서버가 이 변경과 무관한 환경 이슈(`0xc0000142` DLL 로드 실패, CSS 처리
  서브프로세스 크래시)로 기동에 실패해 브라우저 클릭 QA는 수행하지 않음 — `docs/APPROVAL_POLICY.md`의
  "코드 분석→로그 확인→서버 확인→API 확인→마지막에 브라우저 QA" 우선순위에 따라 Type Check/Build
  통과와 기존 결제 흐름 재사용(호출 경로 자체는 무변경)으로 검증을 갈음함

**BUGS.md 정리**
- #12(Chrome Extension 권한 반복): 코드 버그가 아니라 QA 절차 문제였음을 확인 — `docs/APPROVAL_POLICY.md`에
  이미 명시된 "브라우저 QA는 마지막 수단" 원칙을 재확인하고 해결로 정정
- #13(Mock API): Search/Detail/Favorite/Recent Items/Auth는 이미 실 API 연동 완료, Payment만
  PG사 미확정이라는 의사결정 대기 상태(의도된 정책, 버그 아님)로 정정

**Technical Debt Review**
- `registry.py:create_registry_request()`의 "명시적 rollback 없음" 서술이 stale함을 코드로 확인
  — Sprint 10(`BEGIN IMMEDIATE`)에서 이미 `try/except Exception: conn.rollback(); raise`가
  함께 추가되어 있었음. `docs/backend.md` 정정(수정 불필요, 문서만 동기화)
- SQLite `PRAGMA foreign_keys=ON` 부재, `payments.status`의 죽은 상태(PENDING/REFUNDED),
  Admin role 미구분, `SUBSCRIPTION_PERIOD_DAYS` 하드코딩은 재확인 결과 여전히 유효한 기술부채이며
  전부 스키마 변경/정책 결정/큰 설계 변경이 필요해 이번 Sprint에서는 수정하지 않음(기존 문서 그대로 유지)

**검색 문서 대규모 동기화** (`docs/search-engine.md`, `docs/backend.md`)
- `api/v1/search.py` 코드를 처음부터 다시 읽어 문서와 대조한 결과, 실제로는 이미 구현되어 있는데
  문서에 "미구현"으로 잘못 기재된 항목을 다수 발견:
  - `status` 필터 — 구현되어 있었음(문서만 "없음"으로 기재)
  - `sort_by`/`sort_order` 파라미터 — 구현되어 있었음(화이트리스트 `SORT_COLUMNS`, 미허용 값은 400)
  - **자유텍스트 주소 검색** — `address_detail` 파라미터로 이미 구현되어 있었음(`intent/analyzer.py`
    기반 SIDO/SIGUNGU/DONG 구조화 시도 → 실패 시 `full_address LIKE` 폴백), 프론트(`SearchForm.tsx`)
    까지 연동 완료 — `docs/backend.md`/`docs/roadmap.md`가 "미지원"으로 기재하고 있던 알려진 문제점이었음
  - 검색 인덱스 — "아직 결정되지 않음"으로 기재되어 있었으나 `storage/migrations/008_create_search_indexes.sql`
    /`009_add_default_sort_index.sql`에 `auction_item`의 주요 필터/정렬 컬럼 전부 인덱스 적용 완료 확인
  - `storage/database.py` — "저장소에 없음(미확인)"으로 기재되어 있었으나 `.gitignore`로 git 이력에서만
    빠져 있을 뿐 작업 디렉터리에는 실재하며 읽을 수 있음(`docs/CLAUDE.md`의 기존 정정 사항과 동일한
    내용이 `search-engine.md`에는 반영되지 않고 있었음)
  - 검색 API 인증 — "인증 로직 없음"으로 기재되어 있었으나 실제로는 선택적 JWT 검증(`HTTPBearer(auto_error=False)`)이
    있어 로그인 시 `is_favorited`를 채움. 검색 자체가 인증을 요구하지 않는다는 원래 취지는 그대로 유효
- 코드 변경 없음 — 전부 문서만 코드에 맞춰 재동기화(`docs/search-engine.md`/`docs/backend.md`,
  이 CHANGELOG 항목 자체가 근거)

---

2026-08-06 (Sprint 15 — Security/Type/Performance Review)

Beta Release 품질 향상 목표로 처음 전용 Security Review 수행. Critical Path(PG사 확정)는 여전히
의사결정 대기, Sprint Backlog(P2 로그인 UX)는 화면 스펙 미확정으로 Skip하고 Security Review 진행:

- `api/v1/*.py` 전체 SQL 조립 지점 재확인 — 전부 파라미터 바인딩 사용, Injection 여지 없음(수정 불필요)
- **발견 및 수정**: `api/v1/admin.py:require_admin()`의 관리자 키 비교가 단순 `!=` 문자열
  비교였음(타이밍 사이드채널 이론상 존재) → `hmac.compare_digest()`로 상수 시간 비교 교체
- JWT 알고리즘 하드코딩(`HS256`), 문서 다운로드 경로 탐색 방지, favorites/search-presets/recent-items
  소유권 검사(`WHERE user_id=?`) 전부 재확인 결과 안전함(수정 불필요)
- Runtime QA: `require_admin()` 직접 호출로 정상 키/틀린 키/키 누락/`ADMIN_API_KEY` 미설정 4개
  시나리오가 수정 전과 동일한 결과(403/403/403/500)임을 확인 — 비교 방식만 교체, 로직 무변경
- Compile/Import 확인: `py_compile` 통과, `api_server.py` 전체 import 및 라우트 16개 정상 등록 확인
- Admin 인증의 구조적 한계(단일 공유키, role 미구분)는 이번 범위 밖 — 타이밍 공격 방어만 추가,
  키 자체 유출 시에는 여전히 무방비(`docs/decision-log.md` 기존 결정 유지)

**Type 개선**: `src/app/login/actions.ts`의 `loginAction`/`signUpAction`이 `prevState: any`를
쓰고 있었음(lint `@typescript-eslint/no-explicit-any` 오류 2건, Sprint 14 lint 비교에서 이미
식별된 기존 오류) — 호출부(`login/page.tsx`의 `useActionState(loginAction, null)`)의 실제 상태
모양에 맞춰 `{ error: string } | null` / `{ error: string } | { message: string } | null`로 타입
명시. 함수 내부에서 `prevState`를 참조하지 않아 런타임 동작 변화 없음. Type Check/Build 통과,
Lint 오류 5→3건으로 감소(남은 2건+경고 1건은 무관한 기존 이슈, `SearchForm.tsx`/`page.tsx`/
`supabaseServer.ts`)

**Performance Review**: `api/v1/favorites.py:get_favorites()`가 즐겨찾기 목록을 조회한 뒤
각 항목마다 `get_item_summary()`를 개별 호출하는 N+1 쿼리 구조였음(`recent_items.py:get_recent_items()`는
이미 단일 JOIN으로 구현되어 있어 같은 문제가 없었음 — 두 엔드포인트 간 패턴 불일치 확인). 동일한
JOIN 패턴으로 교체해 단일 쿼리로 통합. 응답 JSON의 필드/순서/값은 완전히 동일(정렬 기준도
`created_at DESC` 그대로). Runtime QA: 실제 `auction_item`의 실존 id 2개로 롤백 트랜잭션
안에서 기존 로직과 신규 로직의 출력을 직접 비교해 완전히 일치함을 확인(`MATCH: True`), 트랜잭션은
커밋하지 않고 rollback해 DB에 영구 변경 없음. `python -m py_compile`/`api_server.py` 전체
import(라우트 16개) 재확인

문서 동기화 (roadmap / backend)

---

2026-08-06 (Sprint 16 — Bug Fix 발견: auction_case.case_no 전국 UNIQUE 충돌)

`migrate_execute.py`의 기존 주석("court_code+case_no+item_no 식별키 문제는 Critical TODO로
별도 기록")을 따라가 실제 영향을 조사:

- `storage/migrate_v4_1.py`의 `auction_case`가 `case_no TEXT UNIQUE NOT NULL`(전국 단일
  UNIQUE, 법원 구분 없음)로 선언되어 있음을 확인
- `config/courts.py:ALL_COURTS`(60개 법원)를 매일 전부 크롤링하는 구조이므로 법원마다 독립
  채번되는 사건번호가 우연히 같을 가능성이 항상 존재
- 실제 DB(`auction` 테이블)를 조회해 서로 다른 법원 간 사건번호 충돌 **3건을 실측 확인**(읽기
  전용 조회만 수행, 데이터 변경 없음)
- `auction_case` 총 row 수(1,377)가 `auction`의 distinct `case_no` 수(1,377)와 정확히 일치함을
  확인 — 충돌한 3쌍이 이미 `auction_case`에서 병합되어 있다는 방증
- 영향 범위 분석: `auction_item.court_name`(검색/상세 목록에 실제 노출)은 법원별로 개별 저장돼
  현재는 눈에 보이는 오류 없음. `auction_case` 경유 필드(`case_type`/`filed_date`/`demand_deadline`)는
  `migrate_execute.py`가 전부 `NULL`로 채우고 있어 지금 당장은 미노출이지만, 이 필드들을 채우는
  기능이 추가되면 즉시 데이터 오염이 사용자에게 노출됨
- 수정에는 UNIQUE 키를 `(court_name, case_no)` 복합키로 바꾸는 **Schema 변경** + 기존 데이터
  재처리(**Migration**)가 필요 — 이번 세션 원칙(승인 필요 항목 즉시 Skip)에 따라 코드는 전혀
  수정하지 않고 **Release Blocking**으로 기록만 함(`docs/BUGS.md` #14, `docs/crawler.md` 알려진
  문제점 6번)
- 부수 확인: 과거 문서에 있던 "`auction` 1,010 / `auction_item` 710, 차이 300건" 서술이 stale함을
  발견 — 현재는 `auction`/`auction_item` 둘 다 1,870건으로 차이 0건(정상 동기화 중), `docs/crawler.md` 정정

코드 변경 없음(조사·문서화만). 문서 동기화 (BUGS / crawler / roadmap / CURRENT_STATE)

---

2026-08-06 (Sprint 17 — 잔여 Backend/Lint 감사, Type/Lint 마무리)

`api/v1/payments.py`, `api/v1/payment_providers.py`, `storage/database.py`(크롤러/문서큐 관련
전체)를 처음부터 다시 읽어 SQL Injection/트랜잭션/rollback/동시성 관점에서 재검토 — 전부
파라미터 바인딩, 명시적 rollback, 원자적 UPDATE(WHERE 조건부) 사용 확인, 추가 이슈 없음(수정 불필요).
`favorites/page.tsx`/`properties/recent/page.tsx`도 재확인 — Sprint 15의 `favorites.py` JOIN
응답 필드가 프론트 `FavoriteItem` 인터페이스와 정확히 일치함을 교차 검증.

- **Lint 정리**: `src/lib/supabaseServer.ts`의 `catch (error) { /* 미사용 */ }`를 `catch { }`로
  단순화 — `@typescript-eslint/no-unused-vars` 경고 제거(동작 무변화, 옵셔널 catch binding은
  프로젝트 TS 설정에서 이미 지원). Lint 문제 3→2건(경고 0건). 남은 2건(`page.tsx`/`SearchForm.tsx`의
  `react-hooks/set-state-in-effect`)은 표준적인 "리셋 후 fetch" idiom이라 수정 시 결제/등기부/검색
  핵심 로직을 건드리는 회귀 위험이 더 크다고 판단해 그대로 유지(의도적 Skip, 버그 아님)
- Type Check(`tsc --noEmit`) 통과
- **일시적 Build 환경 이슈(코드 결함 아님, 해소됨)**: `npm run build` 중 `.next\static\...` 캐시
  파일에서 `EPERM: operation not permitted, unlink`가 3회 연속 발생. 진단 결과 OneDrive 동기화
  프로세스(이 저장소가 `OneDrive\Desktop\dojoonpass` 경로에 위치)의 일시적 파일 잠금으로 확인됨
  — 삭제 시도 등 강제 조치 없이 대기 후 재시도했더니 4번째 시도에서 정상적으로 Build 성공
  (Route 9개 전부 정상 생성). 코드 변경과는 무관한 로컬 환경 이슈였음

문서 동기화 (CHANGELOG만 — 코드 동작 변화가 없어 다른 문서는 갱신 대상 없음)

---

2026-08-06 (Sprint 18 — 전체 재감사: Duplicate Code, Bug Fix)

지시에 따라 Backend→Frontend→DB Layer→API Contract→TODO→Dead Code→Duplicate Code 순으로
저장소 전체를 처음부터 다시 훑음(`api/v1/*.py` 전 라우터, `storage/database.py`,
`payment_providers.py`, `migrate_execute.py`/`mvp_scraper.py`/`doc_worker.py`/`refresh_priority.py`,
`middleware.ts`, `lib/api.ts`/`supabaseClient.ts`/`supabaseServer.ts`, `favorites`/`recent`/
`search` 화면, `components/*` 참조 여부):

- **Duplicate Code 제거**: `formatPrice()`가 5개 파일에 각각 정의돼 있었는데, 그중
  `search/ResultList.tsx`/`favorites/page.tsx`/`properties/recent/page.tsx` 3곳은 완전히
  동일한 구현이었음(`!price`/`>=1억`/`>=1만` 3단계 분기). `src/lib/format.ts`(신규) 공용 함수로
  통합하고 3개 파일에서 로컬 정의 삭제 + import로 교체. `properties/page.tsx`/`properties/[id]/page.tsx`의
  2곳은 서로 다른 구현(항상 "억" 고정 표기)이라 건드리지 않음 — 통합하려면 표기 방식 자체를
  하나로 정할지 UX 결정이 필요해(Spec) 이번 Sprint 범위 밖으로 Skip
- **Bug Fix**: `mvp_scraper.py`가 모듈 로드 시점에 `logging.FileHandler("logs/scraper.log")`를
  즉시 생성하는데, `logs/`는 `.gitignore` 대상이라 없는 환경(fresh clone 등)에서는
  `FileNotFoundError`로 스크립트가 단 한 줄도 못 실행하고 죽는 구조였음. `doc_worker.py`/
  `refresh_priority.py`는 이미 `os.makedirs("logs", exist_ok=True)`로 이 문제를 막고 있었음 —
  동일 패턴을 `mvp_scraper.py`에도 적용(1줄 추가). 이 저장소는 `logs/`가 이미 있어 완전히
  no-op(동작 무변화), fresh clone/CI 환경에서만 실질적 효과
- TODO 5건(`SearchForm.tsx`/`ResultList.tsx`) 전수 재확인 — 전부 `building_area`/`land_area`/
  `special_conditions`/조회수 등 `auction_item`에 없는 컬럼을 요구해 Schema 변경 없이는 구현
  불가함을 재확인(기존에 이미 정확히 문서화돼 있었음, 추가 조치 없음)
- Dead Code 탐색: `filter/` 모듈(기존에 이미 dead code로 문서화됨, 변동 없음), `src/components/*`
  5개 컴포넌트 전부 다른 파일에서 참조됨을 확인(dead 컴포넌트 없음)
- API Contract 재검토: `payments.py`/`admin.py`의 요청/응답 스키마가 프론트 호출부와 정확히
  일치함을 재확인(수정 불필요)
- Architecture Audit: `next.config.ts`(`reactCompiler: true` — 남은 2개 lint 오류의 근거),
  `tsconfig.json`(strict 모드) 확인, 문제 없음
- Runtime QA/Regression: `formatPrice` 통합은 3개 파일 모두 동일 출력이므로 순수 이동(함수 바디
  1바이트도 변경하지 않음)이라 별도 비교 없이 Type Check/Build로 충분히 검증됨. `mvp_scraper.py`는
  `pandas` 등 크롤러 전용 의존성이 이 세션의 Python 환경에 없어 전체 import 실행은 불가했으나
  `py_compile`로 문법 확인, 추가한 코드가 이미 검증된 자매 스크립트와 동일한 표준 라이브러리
  호출(`os.makedirs`)이라 위험 없음
- Build: 최초 3회 `EPERM`(OneDrive 잠금, 코드와 무관) 후 원인이 이전 시도에서 남은 좀비 `node`
  프로세스(내가 실행한 이전 build의 잔류물)로 확인돼 해당 프로세스만 종료 후 재시도해 정상 성공
  (Route 9개 전부 생성)
- Type Check/Lint: 통과(Lint 2건은 Sprint 17에서 이미 의도적 Skip 처리한 항목 그대로)
- 부수 발견: 이 CHANGELOG 파일 자체에 이전 Sprint 편집 과정에서 남은 헤더 없는 고아 줄
  ("문서 동기화 (search-engine / backend / BUGS)")이 있어 정리함(문서 자체의 오탈자/구조
  수정, 코드 변경 아님)

문서 동기화 (frontend / crawler / CHANGELOG 자체 정리)

---

2026-08-06 (Sprint 19 — 크롤러 파이프라인 전 모듈 재감사)

이전 Sprint들이 주로 `api/v1/*.py`와 프론트에 집중했던 것과 달리, 이번엔 아직 전체를 읽지
않았던 크롤러 파이프라인 하위 모듈(`intent/analyzer.py`, `normalizer/normalizer.py`,
`models/auction_item.py`, `crawler/court_crawler.py`, `crawler/base_crawler.py`,
`crawler/doc_crawler.py`, `storage/checkpoint.py`, `validator/validation_engine.py`,
`config/settings.py`)을 처음부터 끝까지 재감사:

- **Duplicate Code 제거**: `validator/validation_engine.py`의 `SIDO_MAP`이
  `normalizer/normalizer.py`의 `SIDO_PATTERNS`와 완전히 동일한 내용(17개 시도, 동일 variant
  목록)의 별도 정의였음. `extract_sido()` 함수도 로직이 사실상 동일. `validation_engine.py`가
  `from normalizer.normalizer import SIDO_PATTERNS as SIDO_MAP`으로 재사용하도록 교체, 로컬
  중복 딕셔너리(18줄) 삭제. 함수 로직/시그니처는 그대로 유지(값·동작 무변화)
- **Dead Code 발견(삭제 없이 기록)**: `config/settings.py`의 `COURTS`(서울 5개 법원, 진짜
  법원코드 사용)와 `PAGE_LOAD_TIMEOUT`/`ELEMENT_TIMEOUT`/`AJAX_TIMEOUT`/`SIDO_LIST`가
  저장소 전체에서 한 곳도 import되지 않음을 grep으로 확인 — 60개 법원 확장 이전 초기 개발
  단계의 잔재로 보이며, 실제로는 `config/courts.py:ALL_COURTS`(60개 법원)와
  `crawler/base_crawler.py`의 자체 하드코딩 타임아웃이 각각 대체해 쓰이고 있음(이름·값이
  우연히 같을 뿐 서로 연결되어 있지 않아 한쪽만 바뀌면 조용히 어긋날 수 있는 구조). 삭제는
  이번 세션 원칙상 수행하지 않고 `docs/crawler.md`에 근거와 함께 기록만 함
- 부수 확인: `mvp_scraper.py`의 `logs/` 생성 수정(Sprint 18)이 `storage/checkpoint.py`
  (`logs/checkpoint.json`)·`crawler/court_crawler.py`의 `log_error()`(`logs/errors.jsonl`)·
  `ValidationEngine`(`logs/validation.jsonl`)까지 전부 함께 보호하고 있음을 코드 추적으로 확인
  (해당 세 곳 모두 `logs/` 하위 파일을 열되 디렉터리 생성은 스스로 하지 않으므로, `mvp_scraper.py`
  모듈 로드 시점의 `os.makedirs`에 의존)
- Runtime QA: `SIDO_MAP`/`SIDO_PATTERNS`가 동일 객체(`is` 비교로 확인)임을 직접 확인,
  `ValidationEngine.validate()`를 실제 `AuctionItem` 2건(일치/서울-제주 불일치)으로 end-to-end
  실행해 `PASS`/`FAIL`(`address_mismatch`) 결과가 기존과 동일함을 확인. 기존 `test_normalizer.py`
  실행 결과 전부 `[PASS]`(테스트 스크립트 자체의 무관한 콘솔 인코딩 이슈로 마지막에 크래시했으나
  `normalizer.py` 로직 자체와는 무관 — 이 세션에서 `normalizer.py`는 수정하지 않았음)
- Compile/Type Check/Build/Lint 전부 통과(Lint는 기존 2건 그대로, 신규 이슈 없음)

문서 동기화 (crawler)

---

2026-08-06 (Sprint 20 — 미독파일 재감사: 보안 문서 정정 발견)

이전 Sprint에서 아직 읽지 않았던 파일(`api_server.py` 전체, `api/v1/doc_stats.py`,
`storage/migrate_v4_1.py`, `src/app/search/SearchForm.tsx` 전체(655줄), `src/app/login/page.tsx`)
을 처음으로 완전히 읽고 감사:

- **문서 정정(코드 변경 없음, Evidence 기반)**: `docs/backend.md`/`docs/CLAUDE.md`가 "host:
  0.0.0.0"·"외부 봇/스캐너 접근 중"이라고 계속 기재하고 있었으나, `api_server.py`를 직접 읽은
  결과 `uvicorn.run(..., host="127.0.0.1", ...)`로 이미 localhost 전용으로 바인딩되어 있음을
  확인. `git log -p -- api_server.py`로 추적한 결과 커밋 `bfefbf7`("feat: add backend
  authentication and registry APIs")에서 `0.0.0.0` → `127.0.0.1`로 이미 변경된 이력을 확인 —
  인증 도입 시점에 보안 강화 목적으로 바뀐 것으로 보이나 문서는 그 이후 한 번도 갱신되지 않았음.
  "외부 봇/스캐너 접근" 서술을 stale로 정정하되, 실제 운영 배포가 이 코드를 그대로(CLI
  `--host` 오버라이드 없이) 쓰는지는 코드로 검증 불가라는 한계도 함께 명시(Non-blocking, 운영
  확인 필요)
- `api/v1/doc_stats.py`, `storage/migrate_v4_1.py` 재확인 — 기존 문서와 100% 일치, 추가 이슈 없음
- `SearchForm.tsx` 전체 재확인 — `COURT_LIST`가 `config/courts.py:ALL_COURTS`를 프론트에
  그대로 복사한 것임을 코드 자체가 이미 주석으로 명시하고 있고("같은 목록을 두 곳에서
  관리하므로... 함께 갱신해야 한다"), 실제 60개 항목을 1:1 대조한 결과 현재는 드리프트 없음
  (이미 자체적으로 문서화된 트레이드오프라 새로운 발견 아님, 수정하지 않음). "면적 조건"/
  "특수조건" 아코디언은 UI 자체가 "준비 중입니다"로 명시돼 있어, 관련 `SearchFormState` 필드
  (`buildingArea*`/`landArea*`/`specialConditions`)가 실제로는 어떤 입력 요소에도 바인딩되지
  않는 것도 확인했으나 이미 UI/문서 양쪽에서 일관되게 미완성으로 표시돼 있어 별도 조치 없음
- `src/app/login/page.tsx` 재확인 — Sprint 15에서 `any` 제거 시 부여한
  `{error}|{message}|null` 유니온 타입이 `'message' in currentState` 타입 가드와 정확히
  맞물려 동작함을 확인(회귀 없음 재검증)

문서 동기화 (CLAUDE.md / backend)

---

2026-08-06 (Sprint 21 — 남은 미독파일 전수 감사: 기능 공백 1건 + Dead Code 1건 발견)

Sprint 20 보고에서 "다음 라운드 시작점"으로 지목했던 `src/components/*`(5개) 전체와, 아직 읽지
않았던 `src/app/properties/SearchFilters.tsx`·`LogoutButton.tsx`·`search/SearchPresets.tsx`를
읽고, 저장소의 전체 파일 목록을 다시 나열해 미감사 영역이 남아있는지 교차 확인:

- **[기능 공백 발견, 구현하지 않음]** `src/app/properties/LogoutButton.tsx`가 완성된 채로
  존재하지만 저장소 전체에서 import하는 곳이 **0곳**임을 확인(`grep -rn "LogoutButton" src/`
  결과가 자기 자신의 `export default` 1줄뿐). `signOut()` 호출도 이 죽은 파일 내부가 유일
  (`grep -rn "signOut" src/`) — 즉 **로그인한 사용자가 앱 안에서 로그아웃할 수 있는 경로가
  전혀 없다**. 컴포넌트 자체는 이미 동작 가능한 상태라 코드 작업은 사실상 "어디에 붙일지"만
  남았는데, 그 배치가 화면 스펙 결정 사항이라 임의로 연결하지 않고 `docs/BUGS.md` #15로 기록
  (결제/등기부 등 개인정보가 걸린 서비스 특성상 우선순위가 낮지 않다고 판단해 Bug로 등록)
- **[Dead Code 발견, 삭제하지 않음]** `logs/` 안에 `mvp_scraper.py`/`doc_worker.py`/
  `refresh_priority.py` 3개가 루트 동명 스크립트의 오래된 복사본으로 남아있음을 발견. 어떤
  코드/배치도 이 경로를 참조하지 않으며, **stale임이 코드로 증명됨** — `logs/doc_worker.py`가
  import하는 `crawl_single_document`는 현재 저장소에 존재하지 않는 이름(현재는
  `collect_document`)이라 실행 시 즉시 ImportError. `mark_queue_skipped_expired`·부분 성공
  로깅 등 이후 추가 기능도 전부 빠져 있음. `docs/crawler.md` 알려진 문제점 9번으로 기록
- `src/components/*` 5개 전체 정독 — `PriceRangeSelect`/`RangeSelect`가 "레이블+최소/최대
  select" 구조를 공유하지만, 값 체계(0-sentinel 프리셋 vs 빈문자열-sentinel 범용)와 disabled
  조건이 서로 달라 통합 대상이 아님을 확인(코드 주석에도 이미 의도가 명시돼 있음). 나머지
  3개(`PrimaryNav`/`PropertyTypeTree`/`SearchAccordionSection`)도 이슈 없음
- `SearchFilters.tsx`가 `/search`의 `SearchForm.tsx`와 완전히 다른 시도/시군구/가격 데이터를
  쓰는 것을 확인 — 다만 이는 `/properties`가 Supabase를 직접 조회한다는 기존 데이터 소스
  불일치와 같은 뿌리이고 `/properties`의 향후 방향이 미결정이라 통합하지 않고 `docs/frontend.md`에 기록
- 전체 파일 목록 재나열로 미감사 영역 교차 확인 — 남은 미독 `.py`는 전부 `.gitignore` 대상
  일회성 조사 스크립트(`step*.py`/`check_*.py`/`patch_*.py`, `docs/CLAUDE.md`가 "현재 코드로
  간주하지 말 것"이라고 이미 명시)와 `filter/*`(기존에 dead code로 문서화됨)뿐임을 확인
- Type Check/Compile/Build/Lint 전부 통과(Lint 기존 2건 그대로, 신규 이슈 없음). 이번 Sprint는
  코드 변경이 없어(발견·문서화만) Runtime QA/Regression 재실행 불필요

문서 동기화 (BUGS #15 신규 / crawler #9 신규 / frontend)

---

2026-08-06 (Sprint 22 — CTO 확정사항 기준 저장소 전체 문서 동기화)

CTO가 3건을 확정함에 따라 저장소 전체 문서를 확정 Spec 기준으로 통일. **코드는 변경하지 않음**
(확정 지시가 "문서만 정합성을 맞춘다"였고, 실제 과금/한도 동작 변경은 승인 필요 작업):

**[확정 1] PG사 = KG이니시스**
- `decision-log.md`에 확정 결정 신규 등록(Pending Decisions에서 제거)
- `BUGS.md` #13, `CURRENT_STATE.md`, `roadmap.md`(Next Priority/Beta 남은 작업/Critical Path/
  Risks), `backend.md`, `architecture.md`의 "PG사 미확정" 서술을 전부 확정 기준으로 수정
- Critical Path 다이어그램 갱신: `[PG사 확정] ✅ 완료` → `[KG이니시스 계약 + API Key 발급] ← 현재 여기`
- **코드 현황 명시**: `KGInicisProvider`는 저장소에 존재하지 않으며 `_PROVIDERS` 맵도
  `mock`/`toss`/`portone` 3개만 인식 — "문서상 확정 / 코드 미반영" 상태임을 각 문서에 기록.
  `TossProvider`/`PortOneProvider`는 폐기 예정으로 표기(삭제는 승인 필요라 코드 유지)

**[확정 2] 구독 정책 — 베이직/프로 2단계**
- 베이직 9,900원/월·99,000원/년·등기부 월 5회 / 프로 19,800원/월·198,000원/년·등기부 월 10회
- 기존 충돌 표기(`BETA_EARLYBIRD`/`STANDARD`, 12,900·22,900, "얼리버드 평생 9,900원 유지",
  "평생 누적 5회")를 전부 폐기로 통일
- 등기부 무료 한도의 오랜 미결 쟁점("평생 vs 월")이 **월 단위 + 플랜별 차등**으로 확정됨
- **코드↔Spec 불일치를 실측 확인 후 명시적으로 기록**(`backend.md`에 "확정 Spec 미반영 항목"
  절 신설): 실제 코드값이 `VALID_PLANS=('BETA_EARLYBIRD','STANDARD')`,
  `PLAN_PRICES={9900, 22900}`, `SUBSCRIPTION_PERIOD_DAYS=30`, `FREE_LIMIT=5`(기간 조건 없는
  전체 COUNT)임을 파이썬으로 직접 import해 검증. 반영에는 플랜명/가격/연결제/월리셋 4가지
  동시 수정이 필요하며 승인 후 별도 Sprint로 분류
- `roadmap.md` Risks에 신규 항목 추가: **확정 Spec과 코드 불일치 장기화 시, 안내한 요금·한도와
  실제 과금/차감이 달라지는 위험** — 출시 전 코드 반영 선행 필요
- 스키마 영향 확인: `subscriptions.plan`은 CHECK 제약 없는 TEXT라 플랜명 교체에 스키마 변경
  불필요(기존 `BETA_EARLYBIRD` row 이관 방침만 미정 — Pending Decisions에 추가)

**[확정 3] auction_case UNIQUE → (court_code, case_no) 복합키**
- `decision-log.md`/`BUGS.md` #14를 확정 방향으로 통일, Migration은 승인 필요로 유지
- **구현 시 선행 확인 사항을 코드 조사로 보강**: `auction_case`에 `court_code` 컬럼이 아예 없고
  (`court_name`만 존재), `config/courts.py:ALL_COURTS`의 `code`에는 실제 법원코드가 아니라
  법원명 문자열이 들어가 있어(`config/settings.py:COURTS`의 `B000210` 형식과 불일치) 어느 값을
  `court_code` 정본으로 삼을지 확정이 선행돼야 함을 기록

**부수 수정(자체 오류 복구)**: 이번 세션 편집 중 `backend.md`에 "Payment Provider 구조" 섹션이
중복 생성된 것을 자체 검증에서 발견해 옛 블록 제거(git 원본 1개 → 현재 1개 복구 확인). 전체
문서 헤더 중복 검사도 함께 수행해 0건 확인.

검증: Type Check/Compile/Build/Lint 전부 통과(Lint 기존 2건 그대로). 코드 무변경이라 Runtime
QA/Regression 재실행 불요 — 대신 문서에 기재한 코드값이 실제와 일치하는지 직접 import로 교차 검증함.

문서 동기화 (decision-log / backend / CURRENT_STATE / roadmap / BUGS / architecture / frontend)
※ CHANGELOG·roadmap의 "[완료] Sprint N" 블록은 과거 시점의 사실 기록이라 소급 수정하지 않음
---

2026-08-06 (Sprint 23 — CTO 최종 확정사항 반영: Migration 실행 + 구독 정책 구현 + 로그아웃)

이전 Sprint(22)가 문서 동기화만 했던 것과 달리, CTO가 Migration 실행·로그아웃 수정·구독 정책
코드 반영을 명시적으로 승인해 **실제 코드/DB 변경**을 수행했다.

**[Release Blocking 해소] auction_case UNIQUE(court_code, case_no) Migration 실행**
- `storage/migrations/011_auction_case_court_code_unique.sql` 신규. SQLite는 UNIQUE 제약을
  ALTER로 못 바꿔 새 테이블 생성 → 이관 → 교체(표준 재작성 패턴)로 처리
- `auction_case`에 없던 `court_code` 컬럼 신규 추가. 정본은 크롤러 원본 `auction.court_code`
  (법원명 문자열, NULL 0건 실측 확인)
- `migrate_execute.py`의 dedup 키·조회 키도 `(court_code, case_no)`로 변경 — 안 했으면 매일
  크롤링이 `court_code=NULL` row를 만들어 재오염됐을 지점
- **안전 절차**: 실행 전 타임스탬프 백업 생성 → 사본 DB에서 리허설로 결과 검증 → 실제 적용
- **검증**: `auction_case` 1,377→1,380(충돌 3건이 법원별로 정확히 분리), `auction_item` 1,870
  불변, orphan `case_id` 0건, **court mismatch 0건(원래 버그 해소)**, `migrate_execute.py`
  재실행 시 신규 0/갱신 1,870으로 멱등 확인

**[신규 버그 발견·수정] migrate_execute.py가 매일 배치 실패를 유발하던 문제**
- Migration 검증 중 발견: 커밋 성공 후 결과 출력의 `✅`/`❌` 이모지가 cp949로 인코딩되지 않아
  `UnicodeEncodeError` → `sys.exit(1)`. **운영 로그에 11회 실제 발생**(최근 2026-08-01)
- 데이터는 정상 커밋되지만 종료코드가 1이라, Sprint 13에서 배치 exit code를 정직하게 만든 이후
  **매일 Task Scheduler에 실패로 보고되는 상태**였음
- 이모지를 `[OK]`/`[FAIL]` ASCII로 교체. 실제 배치와 동일 조건(stdout 리다이렉트)에서
  재현 테스트 → **exit code 0** 확인

**[구독 정책 최종 확정 반영] 할인 구조를 하드코딩하지 않는 설계**
- BASIC 12,900원/월·154,800원/년·월5회, PRO 22,900원/월·연 정상가 274,800원→**판매가 198,000원**·월10회
- `PLAN_CATALOG`: 플랜 → 결제주기 → `{list_price, sale_price}`. `sale_price=None`이면 정상가 판매
- `resolve_plan_price()`를 가격 해석의 **단일 진입점**으로 두어, 향후 `discount_start`/
  `discount_end`/`discount_percent`를 붙일 때 결제 라우터를 수정하지 않아도 되게 함
- 결제주기 도입: `BILLING_MONTHLY`(30일)/`BILLING_YEARLY`(365일). `billing_cycle` 미지정 시
  월 결제로 간주해 기존 호출과 호환
- 등기부 한도: `get_free_count()`가 이번 달 사용분만 COUNT(월 자동 리셋, 별도 배치 불요),
  `get_user_free_limit()`이 활성 구독 plan으로 한도 조회(베이직 5/프로 10)
- 프론트: 월/연 토글 + 플랜 카드(정상가 취소선 + 판매가) UI, `billing_cycle` 전송
- **Runtime QA**: 가격 4종 카탈로그 대조 전부 일치, 실제 DB 롤백 트랜잭션에서 지난달 3건 +
  이번달 2건 → 이번달 카운트 2로 계산됨을 실증(옛 로직이면 5로 오판), PRO 10/BASIC 5 확인

**[기능 공백 해소] 로그아웃**
- `properties/page.tsx`(로그인 후 랜딩) 헤더에 `LogoutButton` 연결. `PrimaryNav`는 비로그인
  접근이 가능한 `/search`에도 쓰이므로 그쪽에는 넣지 않음

**[신규 문서] docs/ENVIRONMENT_VARIABLES.md**
- Supabase/JWT/Admin/KG이니시스/Mail/SMS/GA4/Sentry/Slack 전 항목을 구분·설명·필수여부·
  발급위치·비고·예시로 정리. 각 항목마다 "지금 필요 / 론칭 직전 필요 / 지금 Skip 가능"과
  **실제 코드 참조 여부**(grep 근거)를 명시
- 중요 정정 기록: 요청 항목명은 `JWT_SECRET`이나 실제 코드가 읽는 변수는 `SUPABASE_JWT_SECRET`

검증: Type Check/Build/Compile/Lint 전부 통과(Lint 기존 2건 그대로). 문서 7종 동기화.

문서 동기화 (decision-log / backend / CURRENT_STATE / roadmap / BUGS / frontend / ENVIRONMENT_VARIABLES 신규)

---

2026-08-06 (Sprint 24 — 승인사항 전수 검증 + 할인 구조 확장 + 회귀 테스트 작성)

Sprint 23에서 반영한 CTO 승인 3건을 지시대로 **전수 실증 검증**하고, 남은 우선순위 작업을 진행:

**[검증] Migration 영향 범위 (CTO 지시 항목 전부)**
- `court_code` 데이터 존재 확인: `auction.court_code` NULL 0건(법원명 문자열이 정본)
- Migration 결과: `UNIQUE(court_code, case_no)` 적용, `auction_case` 1,380건, `auction_item`
  1,870건 불변, `court_code` NULL 0건, orphan 0건, court mismatch 0건, `migration_history` 기록 확인
- **충돌 3건이 법원별로 정확히 분리됐고 각 물건이 올바른 법원에 연결됨을 개별 확인**
  (예: `2024타경3700` → 창원지방법원 10건 / 부산지방법원 1건으로 분리)
- **검색 API**: 정상 동작(total 56건, 목록 반환 확인)
- **상세 API**: 충돌 사건 6건에 대해 `item.court_name == case.court_code` 전부 일치 —
  Migration 전이라면 실패했을 검증이며, 원래 버그가 실제로 해소됐음을 API 레벨에서 확인

**[확장] 할인 구조 — CTO 예시 필드 전부 지원**
- Sprint 23은 `list_price`/`sale_price`만 지원했으나, CTO가 예시한 `discount_start`/
  `discount_end`/`discount_percent`까지 실제 동작하도록 확장
- 할인 우선순위: `sale_price` > `discount_percent` > `list_price`
- **기간을 벗어나면 자동으로 정상가 복귀** — 이벤트 종료 시 코드 수정 불필요
- `resolve_plan_price(plan, cycle, at=None)`에 시점 파라미터 추가(테스트/미래 시점 계산용)
- Runtime QA: 기간 중/전/후/종료일 당일, 정률 20%, 우선순위 충돌까지 전부 실증

**[신규] test_subscription_policy.py — 회귀 테스트 28항목**
- 프로젝트 관례(pytest 미설정, `test_*.py` 단독 실행 스크립트)를 그대로 따름
- 커버리지: 확정 가격 4종 + list_price, 플랜별 등기부 한도, 잘못된 조합 거부,
  할인 구조 6종(기간/정률/우선순위/복구), 월 리셋 + 플랜별 한도(실제 DB, 롤백),
  `auction_case` 복합키 무결성 4종(Release Blocking 회귀 방지)
- DB 검사는 전부 롤백 트랜잭션 — 실행해도 데이터가 남지 않음. 출력은 ASCII만 사용(cp949 안전)
- **전체 통과(ALL TESTS PASSED, exit 0)**

검증: Compile/Type Check/Build/Lint 전부 통과(Lint 기존 2건 그대로, 신규 0).

문서 동기화 (backend / decision-log / CHANGELOG)

---

2026-08-06 (Sprint 25 — 전 도메인 회귀 테스트 + Code/Performance/Security Audit)

Release Blocking 해소 이후 Beta 품질 향상·운영 안정화를 목표로 진행:

**[신규] test_api_regression.py — 전 도메인 실제 HTTP 회귀 테스트 (100+ 검사)**
- FastAPI `TestClient`로 `api_server.app`을 직접 호출 — 라우팅/의존성/인증/직렬화까지
  실제 요청과 동일한 경로를 검증한다(함수 직접 호출이 아님)
- `SUPABASE_JWT_SECRET`으로 실제 형식의 테스트 JWT를 발급해 인증 경로까지 관통
- 커버 도메인: Health/Stats, Search(필터·정렬 화이트리스트·페이지네이션 경계·인젝션),
  Detail/Documents, Authentication, Favorite, Recent, SearchPreset, Payment/Subscription,
  Registry, 무료한도 초과→결제 연결, Admin(상태 전이 규칙 전수)
- **핵심 회귀 방어**: 상세 API가 반환하는 `case.court_code`가 물건의 `court_name`과 일치하는지
  검사 — Migration 이전이라면 실패했을 항목이라 Release Blocking 재발을 HTTP 레벨에서 막는다
- 소유권 격리 검증: 다른 user_id로 favorites/presets/payments/registry 접근 시 전부 차단됨을 확인
- 금액 위조(100원), 폐기된 옛 플랜명(`BETA_EARLYBIRD`), 잘못된 결제주기, 할인 미적용 정상가
  결제 시도가 전부 서버에서 거부됨을 확인
- 테스트 데이터는 `qa-reg-<uuid>` 전용 user_id로만 생성하고 종료 시 그 행만 정리한다
  (실데이터 무관 확인: `auction_case` 1,380 / `auction_item` 1,870 불변, 잔여 0건)
- `ADMIN_API_KEY`는 프로세스 환경에만 주입(`.env` 무수정)

**[Code Audit] 미사용 import 4건 제거**
- AST 기반 전수 조사(40개 모듈) → `search_presets.py`(HTTPException),
  `base_crawler.py`(Select), `auction_item.py`(Optional), `mvp_scraper.py`(get_courts_by_region)
- 파일의 UTF-8 BOM을 보존하며 수정(26개 파일이 BOM 포함 — 파이썬 실행에는 무해)
- 재조사 결과 **잔여 0건**

**[Performance Review] 이상 없음 확인**
- 루프 내 `execute` 호출(N+1) **0건** (Sprint 15의 favorites JOIN 전환 이후 재발 없음)
- 신규 월별 무료횟수 쿼리 실행계획: `idx_registry_usage_user_id` 사용 확인
- 검색 기본 정렬: `idx_auction_item_default_sort` 사용 — 정렬용 임시 B-tree 없이 처리됨
- 사용자 테이블 전체(favorites/recent_items/registry_*/payments/subscriptions) 인덱스 커버 확인

**[Security Review] 이상 없음 확인**
- SQL Injection: `sido=' OR 1=1--` 등 실제 요청으로 무해 처리(0건 반환) 확인
- 하드코딩된 비밀값 0건, 토큰/키를 로그로 출력하는 지점 0건
- JWT: 무토큰 401 / 위조 401 / `sub` 없는 토큰 401 전부 확인
- Admin: 키 없음·오답 403, 상수시간 비교 유지
- 잔존 위험(변경하지 않음): `allow_origins=["*"]` — `allow_credentials`가 없어 쿠키는 전송되지
  않으나 운영 전 도메인 제한 권장(기존 문서에 "개발 환경"으로 이미 명시됨)

**[Type] TS `any` 0건 유지**, Type Check/Build/Lint 전부 통과(Lint 기존 2건, 신규 0)

**[발견] 이전 Sprint QA 잔재 데이터**
- `recent_items`에 2026-08-05 Sprint들의 QA user_id 10건(`qa-admin-mvp-001`,
  `qa-download-001` 등)이 남아있음. 이번 테스트가 만든 것이 아니며(이번 것은 전부 정리 완료),
  삭제는 이번 세션 원칙상 수행하지 않고 기록만 함

문서 동기화 (ENVIRONMENT_VARIABLES 시점별 분류 A/B/C 추가 / CHANGELOG)
