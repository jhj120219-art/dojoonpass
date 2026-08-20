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

---

2026-08-07 (Sprint 26 — PG 명칭 정리 / Admin·Release Audit / 기술부채·회귀 확대)

**[PG] KG이니시스 기준으로 Provider 구조 정리 (실연동은 여전히 Skip)**
- `api/v1/payment_providers.py`에 `KGInicisProvider` 신설 — Interface v2 6개 메서드
  (`charge`/`create_order`/`confirm_payment`/`cancel_payment`/`verify_payment`/`handle_webhook`)
  전부 `NotImplementedError`인 자리 구현. 실제 API 호출은 계약/키 발급 필요로 미착수(승인 대기)
- `_PROVIDERS`/`PAYMENT_PROVIDER` 허용값에 `kginicis` 추가. `toss`/`portone`은 **폐기 예정**으로
  명시하고 선택 시 경고 로그를 남긴다(삭제는 승인 필요라 클래스는 유지, 하위호환 보존)
- 알 수 없는 `PAYMENT_PROVIDER` 값이면 허용값 목록을 포함한 `ValueError`로 즉시 실패
- 모듈 주석·`docs/architecture.md`·`backend.md`·`BUGS.md`·`CURRENT_STATE.md`·`decision-log.md`·
  `roadmap.md`·`ENVIRONMENT_VARIABLES.md`의 Toss 기준 서술을 KG이니시스 기준으로 갱신
  (CHANGELOG/roadmap의 과거 Sprint 기록은 사료라 그대로 둠)

**[Bug] 플랜 업그레이드 직후 등기부 무료한도가 옛 플랜으로 계산될 수 있었음**
- `registry.py:get_user_free_limit()`의 `ORDER BY started_at DESC`가 전순서가 아니었다.
  `started_at`은 `datetime.now().isoformat()`인데 Windows 시계 분해능(~15.6ms)상 짧은 간격의
  두 결제가 **완전히 같은 문자열**을 가질 수 있어, 베이직→프로 업그레이드 후에도 베이직(5회)
  한도가 적용될 수 있었다. 회귀 테스트가 실제로 이 조합에서 한 번 실패해 발견됨
- `ORDER BY started_at DESC, id DESC`로 tie-break 추가 — 나중에 INSERT된 구독이 항상 이긴다
- 같은 뿌리의 정렬 비결정성을 전 도메인에 일괄 수정: `payments`(목록/초과결제 대상 선택),
  `favorites`, `recent_items`, `registry_requests`(사용자/Admin), `search_presets`.
  특히 **Admin 목록은 offset 페이지네이션이라** 동률 행이 두 페이지에 나오거나 빠질 수 있었다

**[Lint] react-hooks/set-state-in-effect 2건 해소 — Lint 오류 2 → 0**
- `properties/[id]/page.tsx`: 문서 존재확인 결과를 `물건id:문서종류` 키 맵으로 보관하고
  `'checking'`은 렌더 중 파생. 이전 문서의 늦은 응답이 현재 문서 상태를 덮어쓰던 경쟁 상태도 함께 해소
- `search/SearchForm.tsx`: `sigunguOptions`/`Loading`/`Error` 3개 상태를 "어떤 조회의 결과인지"를
  담은 단일 상태로 합치고 나머지는 렌더 중 파생. 로딩 중 이전 시/도의 시/군/구가 잠깐 보이던 문제도 사라짐

**[기술부채]**
- bare `except:` 2건 제거(`item.py`/`search.py`) — `JWTError`만 잡고 debug 로그를 남긴다
  (기존에는 `KeyboardInterrupt`/`SystemExit`까지 삼키고 원인도 남지 않았음)
- `item.py`: 최근조회 기록 실패가 상세 조회를 막지 않도록 분리 + 실패 시 warning 로그
- `favorites.py`: `except Exception` → `sqlite3.IntegrityError`. DB 잠금/디스크 오류까지
  "이미 관심물건으로 등록되어 있습니다"로 잘못 안내하던 문제 해소, rollback 추가
- `registry.py`: 미사용 지역변수 `charged_amount`를 실제 단일 기준값으로 사용(하드코딩 0/OVERAGE_FEE 제거)
- `search_presets.py`: 함수 내부 `import json` 2건을 모듈 최상단으로
- `item.py`/`search.py`: 요청마다 반복되던 함수 내부 `from ... import`를 모듈 최상단으로

**[Performance]**
- `doc_stats.py`: `document_status`를 (doc_type,status) 조합마다 6번 스캔하던 COUNT 쿼리를
  단일 `GROUP BY` 1회로 교체(응답 필드/값 동일)

**[Security]**
- `api_server.py`: CORS 허용 Origin을 `CORS_ALLOW_ORIGINS` 환경변수로 제한 가능하게 함.
  **미설정 시 기존과 동일하게 `*`** — 하위호환 유지, 운영 배포 시에만 값 지정
- `search_presets.py`: 서버측 입력 검증 신설 — 이름 공백/100자 초과 거부, 조건 JSON 4000자
  초과 거부, 사용자당 100개 상한. 프론트의 `maxLength=50`에만 의존하던 상태 해소
- `admin.py`: 인증 실패 시 warning 로그(키 값은 절대 기록하지 않음), 상태 전이 성공 시
  `id / 이전상태 → 새상태 / reason / doc_url` info 로그 — 스키마 변경 없이 사후 추적 가능하게 함
- `documents.py`: `court_name`/`case_no`가 NULL이면 `os.path.join` TypeError로 500이 나던 것을 404로

**[UX/Release] `app/layout.tsx` 메타데이터가 `create-next-app` 기본값이던 문제 해결**
- `title: "Create Next App"` → `"콕찰 — 법원경매 검색"`, description도 교체, `<html lang>` `en` → `ko`

**[Test] 회귀 테스트 확대 — 118 → 163 검사**
- 12. Payment Provider 레지스트리: `kginicis` 선택 확인 + 6개 메서드가 **조용히 성공하지 않고**
  전부 `NotImplementedError`임을 확인(실연동 전 결제가 성공한 것처럼 보이는 사고 방지),
  폐기 후보 2종·알 수 없는 값·미설정 기본값까지
- 13. 정렬 결정성: 완전히 같은 타임스탬프 행 3개를 직접 넣고 목록 순서가 호출마다 동일한지,
  동률 구간이 `id` 내림차순 전순서인지 확인
- 14. 구독 플랜 tie-break: 같은 `started_at`의 BASIC→PRO 업그레이드에서 한도 10이 나오는지 확인
- 7. 검색조건 저장: 공백/초과 길이 이름, 초과 크기 조건, 서버측 trim, 개수 상한 검증 추가

**[문서 정합성 — 코드와 어긋난 서술 정정]**
- `docs/CLAUDE.md`: "`docs/architecture.md`가 저장소에 없다"는 안내는 stale — 파일은 존재함
- `docs/backend.md`: `auction.db` 경로가 존재하지 않는 `C:\Users\Administrator\...`로 기재돼
  있던 것을 실제 값(상대경로 `auction.db`)으로 정정. **"개발용 임시 헤더 `X-Test-User-Id`"는
  코드에 존재하지 않음**을 명시(저장소 전체 grep 0건 — 인증 우회 수단은 없다)
- `docs/crawler.md`: Task Scheduler/DB 절대경로를 실제 경로로 정정
- `docs/frontend.md`: "`components/` 디렉터리가 존재하지 않는다 / 재사용 컴포넌트 없음"은 stale —
  5개 공용 컴포넌트가 실제로 사용 중임을 반영. "플랜 선택 UI·검색조건 저장 UI 미구현", "등기부
  한도가 아직 평생 누적 5회", "로그아웃 미노출"도 전부 해결 완료 상태로 정정

**[발견 — 이번에 고치지 않고 기록만]**
- `/properties`(로그인 후 첫 화면)가 Supabase `properties` 테이블을 직접 조회하면서 링크는
  `/properties/{id}`(FastAPI `auction_item`)로 보낸다 — **두 id 채번 체계가 달라 엉뚱한 물건이
  열리거나 404**. 화면 처리 방향(FastAPI 전환 vs 폐지)이 Spec 결정 사항이라 미착수
- 같은 파일의 지역 `formatPrice`가 공용 구현과 다르게 동작(0 → `"0.0억"`)
- 유일한 로그아웃 경로가 그 `/properties` 화면에만 있음(`PrimaryNav`에는 없음)
- `src/login/`(라우팅되지 않는 죽은 코드)이 금지된 옛 브랜드명 "도준 경매 패스"를 사용 중 —
  삭제는 승인 필요
- Admin은 API만 있고 화면이 없음, 단일 공유키라 역할 구분·감사 주체 식별 불가
- 전 API에 Rate Limit 없음(패키지 설치 필요로 미착수)

문서 동기화 (architecture / backend / frontend / crawler / CLAUDE / BUGS / CURRENT_STATE /
decision-log / roadmap / ENVIRONMENT_VARIABLES / CHANGELOG)

---

2026-08-07 (같은 날, Sprint 26 후반 — API KEY Checklist / Architecture·Performance Audit)

**[신규 문서] docs/API_KEY_CHECKLIST.md — 코드 기준 키/시크릿 사실 대장**
- 요청받은 카테고리(API KEY / ENV / Secret / Client ID / Webhook Secret / Redirect URL /
  Callback URL / OAuth / SMTP / Storage / Analytics / Monitoring / SNS / OCR / 지도 / 메일)를
  **전부 코드에서 검색**해 참조 지점(파일:라인)까지 기록. 참조가 0건이면 0건이라고 적는다
- 결론: 코드가 실제로 읽는 환경변수는 **8개뿐**. OAuth/SMTP/Storage/Analytics/Monitoring/
  SNS/OCR/지도/메일은 전부 **참조 0건** — 지금 발급받을 키가 없다
- `document_status`의 `OCR` 문자열은 **상태값 이름일 뿐** 실제 OCR 코드가 아님을 명시(오독 방지)
- **env 드리프트 실측**: `.env`의 `SUPABASE_URL`/`SUPABASE_ANON_KEY`는 **어떤 Python 코드도 읽지
  않는다**(백엔드는 Supabase에 접속하지 않고 JWT 서명만 검증). 무해한 잔재이며 삭제는 승인 필요
- env가 아니라 **대시보드 설정**이라 놓치기 쉬운 항목을 별도 절로 분리 — 특히 Supabase
  **Site URL / Redirect URLs**가 `localhost:3000`인 채로 배포되면 **운영 사용자가 회원가입을
  완료할 수 없다**(가입 확인 메일 링크가 이 설정을 따라감)

**[Bug] API 서버에 로깅 설정이 아예 없어 감사 로그가 버려지고 있었음**
- 크롤러 계열(`mvp_scraper`/`doc_worker`/`migrate_execute`/`collect_documents`)은 전부
  `logging.basicConfig`를 호출하는데 **`api_server.py`만 빠져 있었다** → root logger에 핸들러가
  없고 기본 레벨이 WARNING이라, 같은 날 추가한 **Admin 상태 전이 감사 로그(`logger.info`)가
  통째로 버려지고** 인증 실패 warning조차 timestamp·모듈명 없이 lastResort로만 찍혔다
- 크롤러와 같은 포맷으로 `basicConfig` 추가(+`%(name)s`), 레벨은 `LOG_LEVEL`로 조절(기본 INFO)
- `httpx`/`httpcore`/`urllib3`는 요청마다 INFO를 뱉으므로 WARNING으로 낮춤
- 확인: 수정 전 `logger.info` 미출력 → 수정 후 `2026-08-07 ... [INFO] api.v1.admin: Admin 상태
  전이: registry_request id=... PENDING -> PROCESSING` 정상 출력

**[Bug] OpenAPI Duplicate Operation ID 경고**
- `documents.py`가 `api_route(methods=["GET","HEAD"])` 하나로 두 메서드를 처리해 FastAPI가
  **같은 operationId를 두 번** 생성 → `/openapi.json`을 그릴 때마다 `UserWarning: Duplicate
  Operation ID ...`가 나고 OpenAPI 클라이언트 생성이 깨졌다
- GET/HEAD를 별도 라우트로 분리하고 HEAD는 `include_in_schema=False` — 동작은 동일
  (Starlette가 HEAD 응답 본문을 자동으로 버린다). 스키마 엔드포인트 24 → 23

**[Architecture Audit]**
- AST 기반 미사용 import 전수 재조사(47개 모듈) → **2건 발견·제거**:
  `storage/database.py`의 `os`, `filter/filter_engine.py`의 `Optional`. 재조사 결과 잔여 0건
- 미사용 Component/Type **0건** 재확인(프론트 5개 공용 컴포넌트 + 라우트별 컴포넌트 전부 사용 중,
  `search/types.ts`의 3개 타입 전부 import됨)
- 미사용 API: 프론트가 호출하지 않는 엔드포인트는 `/`(health), `/api/v1/stats`,
  `/api/v1/document-stats`, `GET /payments/{id}`, `GET /registry-requests/{id}`, Admin 2종.
  전부 **운영/테스트/향후 Admin UI용으로 의도된 것**이라 제거 대상 아님(회귀 16번이 집합을 고정)

**[Performance Audit] 실행계획 실측**
- N+1 **0건**(AST 스캔의 `doc_stats.py` 2건은 단일 `GROUP BY` 결과를 순회하는 dict 컴프리헨션 —
  오탐으로 확인)
- 인덱스 적중 확인: 검색 기본 정렬 → `idx_auction_item_default_sort`,
  최근조회 → `idx_recent_items_viewed_at`, 월 무료횟수 → `idx_registry_usage_user_id`
- **개선 여지(스키마 변경 필요라 미착수)**: 활성 구독 조회와 초과결제 대상 선택이
  `user_id` 인덱스가 아니라 `status` 인덱스를 타고 TEMP B-TREE 정렬을 만든다 —
  `(user_id, status)` 복합 인덱스가 적합하나 승인 필요
- **응답 크기 상한 없음**: `favorites`/`payments`/`registry-requests` 목록에 LIMIT이 없다
  (현재 최대 보유 행 0건이라 실제 문제는 없음). 페이지네이션 도입은 응답 구조 변경이라 승인 필요

**[Test] 회귀 145 → 163 검사**
- 16. **API 표면 고정** — 엔드포인트 23개 집합을 명시 선언해 사라짐/추가를 둘 다 검출,
  OpenAPI 생성 경고 0건 확인, HEAD 프로브가 GET과 동일 상태코드인지 확인
- 17. **응답 envelope 계약** — 인증 라우트 5종이 `{success,data,message}`를 유지하는지,
  공개 라우트(search)는 flat 형태를 유지하는지(`docs/backend.md` "절대 변경하면 안 되는 것")
- 18. **CORS 설정** — 미설정 시 `*`, 환경변수 지정 시 그 목록만 파싱

**[문서]** ENVIRONMENT_VARIABLES에 `LOG_LEVEL` 추가 + API_KEY_CHECKLIST 상호 참조,
TEST_PLAN에 16~18번 및 "selenium 미설치로 실행 불가한 테스트" 명시, docs/README 색인 갱신

문서 동기화 (API_KEY_CHECKLIST(신규) / ENVIRONMENT_VARIABLES / TEST_PLAN / CHANGELOG /
CURRENT_STATE / roadmap / BETA_RELEASE_CHECKLIST / README)

---

2026-08-07 (같은 날, Sprint 26 마무리 — TODO 탐색 / 크롤러 데이터 무결성)

**[Critical 발견] 레거시 `auction` 테이블이 매일 물건을 소실시키고 있음 (docs/BUGS.md #18)**

`migrate_execute.py`의 "Critical TODO로 별도 기록"이라는 주석을 추적하다 발견했다.

- `auction` 테이블 제약이 `UNIQUE(case_no, item_no)`로 **법원(court_code)이 빠져 있다.**
  `storage/database.py:upsert_batch()`가 이 키로 기존 행을 찾아 `court_code`/`court_name`/주소/
  가격을 전부 UPDATE하므로, 서로 다른 법원이 같은 사건번호+물건번호를 쓰면 **병합이 아니라
  앞선 법원의 물건이 통째로 교체되어 사라진다**
- **실측**: 법원 간 사건번호 공유 3건. 세 건 모두 한쪽이 `item_no=1`을 차지하고 다른 쪽 목록에서
  정확히 `item_no=1`만 결번 — 이미 소실이 일어났을 가능성이 높다(제약 특성상 사후 확인 불가)
- **재현**: `auction.db` 사본에서 부산지방법원 `2024타경3700 item_no=1`에 수원지방법원 같은 키를
  upsert → `updated=1`, 조회 시 부산 물건이 수원 것으로 대체됨을 확인(**실제 DB 무변경**)

승인 없이 가능한 완화 3가지를 적용했다(근본 수정인 스키마 변경은 승인 대기):

1. `storage/database.py:upsert_batch()` — 덮어쓰기 직전 기존 행의 `court_code`가 다르면
   **WARNING 로그**. 막지는 못하지만 조용한 소실이 로그로 드러난다
2. `migrate_execute.py` — `auction_item` 조회/갱신 식별키를 `(case_no, item_no)` →
   **`(case_id, item_no)`** 로 변경. `case_id`는 `(court_code, case_no)`로 구한 값이라 이미
   법원이 특정되어 있어, 스키마 변경 없이 하위 단계의 동일 결함을 차단한다.
   기존 주석의 "Critical TODO" 남은 절반을 해소한 것
   **검증**: 사본 DB 2개에 구/신 로직을 각각 적용 → `auction_item` 1,870행 전 컬럼 비교
   **차이 0건**(현재 데이터에서 동작 동일, 잠재 결함만 제거)
3. `test_subscription_policy.py` 7번 신설 — 법원 간 공유 `case_no` 개수를 계속 출력·감시하고,
   `auction_item`에 실제 중복이 생기면 실패. 스키마가 복합키로 바뀌면 이 검사가 실패하므로
   그때 #18을 해결 처리하면 된다

**[TODO 탐색] 코드 전체 TODO/FIXME/HACK 스윕**
- 실제 남은 TODO는 프론트 4건뿐이며 전부 **백엔드 미지원 컬럼**에 대한 정직한 표기로 확인:
  건물/토지 면적(`auction_item`에 컬럼 없음), `special_conditions`, `specialSearchType`,
  조회수. FastAPI가 알 수 없는 쿼리 파라미터를 무시하므로 동작상 무해하다 —
  컬럼 추가는 스키마 변경이라 미착수
- `SearchForm.tsx:244`의 "단일 선택시에만 API 연동" TODO는 **stale** — 백엔드 `search.py`가
  이미 콤마 구분 다중 `property_type`을 OR 조건으로 처리한다

**[Test] 회귀 163 + 28 → 163 + 33 검사**

문서 동기화 (BUGS #18 / BETA_RELEASE_CHECKLIST P1-0 / CURRENT_STATE / CHANGELOG)

---

2026-08-07 (Sprint 27 — CTO 승인 6건 반영)

CTO가 승인한 6개 항목을 전부 구현했다. 보류 지정 항목(Sentry / Rate Limit / Selenium /
Monitoring / Analytics / OCR / 지도 / SNS / Storage 확장 / 외부 연동 / 패키지 설치)은 착수하지 않았다.

**[승인 1] BUG #18 — auction 식별 구조 해결 (Migration 012/013)**
- `auction` : `UNIQUE(case_no, item_no)` → **`UNIQUE(court_code, case_no, item_no)`**
- `auction_item` : `UNIQUE(case_no, item_no)` → **`UNIQUE(case_id, item_no)`**
  (CTO 지시대로 **case_id 기반**. `case_id`가 가리키는 `auction_case`는 이미
  `UNIQUE(court_code, case_no)`라 법원이 특정돼 있어, court_code를 또 복제하지 않고도
  "법원+사건번호+물건번호"와 동치가 된다 — `auction_case`와 일관성 유지)
- **id 보존이 필수였다**: `auction_item.id`를 favorites/recent_items/registry_requests/
  registry_usage/document_status/doc_raw/parsed_document/tenant_rights/rights_summary/
  rights_analysis_history/document_collect_failures **11개 테이블**이 참조한다
- 검증: 사본 리허설 → 실제 적용. 1,870/1,870행 **id·전 컬럼 값 100% 보존**, 인덱스 43개 재생성,
  orphan 0건, 충돌 주입 시 두 법원 행 공존 확인. 백업
  `auction.db.backup_before_auction_unique_20260807_095423`
- 함께 수정: `upsert_batch()`(조회·갱신 키), `init_db()`/`migrate_v4_1.py`의 CREATE TABLE
  (fresh clone도 같은 제약), `migrate_execute.py`

**[승인 2] Plan API 서버화 — `GET /api/v1/plans`**
- 서버가 플랜명/정상가/할인가/연간가격/등기부 한도/할인기간/결제주기/초과요금을 전부 내려준다.
  `price`는 항상 `resolve_plan_price()` 결과라 **표시 금액과 검증 금액이 같은 함수에서 나온다**
- 프론트 `properties/[id]/page.tsx`의 `PLAN_OPTIONS` 상수와 `REGISTRY_OVERAGE_FEE`를 **제거**하고
  서버 응답만 사용하도록 교체. 카탈로그 도착 전에는 구독 버튼을 비활성화한다(금액을 모른 채
  결제를 보내면 서버가 거절하므로)
- 회귀 15번을 "프론트 미러 파싱"에서 **"서버 계약 검증 + 프론트에 가격 하드코딩이 되살아나지
  않았는지 확인"** 으로 교체

**[승인 3] ID 체계 전수 Audit**
- 선언 FK 15개, 암묵 참조 10종, 논리 일관성 5종, 식별키 중복 5종, 타입 혼용 전수 조사
- 결과: **orphan 0 / 중복 0 / 불일치 0**. `payments.pg_transaction_id`가 TEXT인 것은
  PG 발급 문자열이라 의도된 것(오탐)
- **발견**: `PRAGMA foreign_keys = 0` — FK가 선언만 되고 런타임에 강제되지 않는다.
  현재 orphan이 0이라 실피해는 없으나 구조적 공백이므로 P2로 등록(활성화 시 마이그레이션의
  DROP TABLE 동작에 영향이 있어 별도 검증이 필요하다)

**[승인 4] Admin 권한 2단계 — SUPER_ADMIN / ADMIN**
- `resolve_admin_role()`이 제시된 키로 등급을 판정한다. 두 키 비교 모두 `hmac.compare_digest`
- `require_admin`(ADMIN 이상) / `require_super_admin`(SUPER_ADMIN 전용) 의존성 분리.
  **기존 `ADMIN_API_KEY`는 그대로 ADMIN 등급으로 동작해 하위호환이 깨지지 않는다**
- 과금에 직접 영향을 주는 조작(등기부 한도 조정)만 SUPER_ADMIN 전용. Operator 등급은 두지 않음
- 상태 전이 감사 로그에 수행 등급(`by=ADMIN`)을 함께 기록

**[승인 5] 결제 로그 구조 (Table/Model/Repository/Interface/Mock/테스트/문서)**
- `payment_logs` : 결제 생명주기(CREATE_ORDER/CONFIRM/VERIFY/CANCEL/WEBHOOK)를 append-only 기록.
  `payments`는 최종 상태 한 줄뿐이라 분쟁 시 궤적을 재구성할 수 없던 문제를 해소
- `payment_webhooks` : PG 노티 원문 보관. `event_id` UNIQUE로 **멱등성** 보장(PG는 응답이 늦으면
  같은 노티를 여러 번 보낸다), 서명 검증 여부를 별도 컬럼으로 관리
- `mask_sensitive()` : 카드번호/CVC/생년월일/토큰 등을 저장 전에 재귀 마스킹.
  로그는 폭넓게 열람되는 데이터라 민감정보가 남으면 안 된다
- `payments.py`가 실제로 3단계를 기록하도록 연결 + `GET /payments/{id}/logs`(본인 것만) 신설
- **실제 API Key 연결·PG 호출은 하지 않았다**(승인 범위대로)

**[승인 6] registry_credit — 관리자 등기부 무료횟수 조정**
- **잔액 컬럼을 두지 않고 조정 원장(ledger)** 으로 설계했다.
  `유효 한도 = 플랜 월 한도 + 이번 달 조정 합계`
  잔액 컬럼을 만들면 `registry_usage` 기반 사용량 계산과 상태가 이중화되어 반드시 어긋난다
  (decision-log의 Premium 판정이 별도 테이블을 거부한 것과 같은 이유). 원장은 (1) 누가/언제/왜
  바꿨는지 남고 (2) 월이 바뀌면 자연히 초기화되며 (3) 동기화 버그가 원천적으로 불가능하다
- `GRANT`(추가) / `DEDUCT`(차감) / `RESET`(그 달 이전 조정 무효화). 부호는 서버가 정하므로
  호출부가 음수를 넘겨 GRANT가 차감이 되는 사고가 없다. 1회 조정 상한 100(오타 방어)
- `GET /admin/registry-credits/{user_id}`(ADMIN 조회) / `POST /admin/registry-credits`(SUPER_ADMIN)
- `registry.py`의 한도 계산에 연결. 차감이 과해도 한도는 0에서 멈춘다(음수 한도는 의미 없음)

**[Test] 회귀 163+33 → 227+48 = 275 검사**
- 신규: Plan API 계약(15) / Admin 권한 2단계(19) / registry_credit 원장(20) /
  결제 로그·Webhook 멱등성·마스킹(21) / 크롤러 식별키(22) / credit ledger 정책(policy 8)
- 어제 넣어둔 "#18 위험 감시" 테스트가 예정대로 실패 → **해결 상태 고정 테스트로 전환**

**[문서]** BUGS #18 해결 처리, CHANGELOG/CURRENT_STATE/roadmap/backend/frontend/architecture/
decision-log/BETA_RELEASE_CHECKLIST/API_KEY_CHECKLIST/ENVIRONMENT_VARIABLES/TEST_PLAN 동기화

---

2026-08-07 (Sprint 28 — CTO 추가 승인 10건 반영)

보류 지정(KG 실연동 / API Key / Webhook 실서버 / Sentry / Analytics / OCR / Monitoring /
Rate Limit / 외부 서비스 / 패키지 / Docker / OS / GitHub 설정)은 착수하지 않았다.

**[승인 1] SQLite FK 런타임 강제**
- `get_connection()`이 커넥션마다 `PRAGMA foreign_keys = ON`을 건다. SQLite는 `REFERENCES`를
  선언해도 이걸 켜지 않으면 **아무 검사도 하지 않는다**(기본 OFF) — 15개 FK가 전부 무시되고
  있었다. 존재하지 않는 `item_id`로 즐겨찾기를 넣어도 DB가 막지 않던 상태
- 마이그레이션만 `get_connection(enforce_foreign_keys=False)`를 쓴다. UNIQUE 제약을 바꾸는
  "새 테이블 → 이관 → DROP → RENAME" 패턴은 중간에 자식 행이 잠시 고아가 되므로 FK를 켜면
  마이그레이션 자체가 실패한다
- 실측: 고아 INSERT가 `IntegrityError`로 차단됨을 확인. 기존 데이터의 orphan은 0건이라
  켜도 아무것도 깨지지 않았다(회귀 340검사 통과)

**[승인 2] Payment State Machine 확장**
- `CREATED / READY / REQUESTED / PAID / FAILED / EXPIRED / CANCELLED / PARTIAL_REFUND / REFUNDED`
- `api/v1/state_machines.py`에 허용 전이만 선언하고 나머지는 전부 거부.
  건너뛰기(`CREATED→PAID`), 되돌리기(`REFUNDED→PAID`), 종결 상태에서의 이동 전부 차단
- **레거시 `SUCCESS`는 제거하지 않았다** — 기존 `payments` 행과 `MockProvider`가 쓰고 있어
  없애면 데이터 해석이 불가해진다. `PAID`와 동일한 전이 규칙을 주고 `is_paid()`가 둘 다 인정한다
- 지금 흐름에는 개입하지 않는다(Mock은 여전히 즉시 SUCCESS). 앞으로 상태를 바꾸려는
  코드가 반드시 통과해야 할 관문이다

**[승인 3] Subscription Lifecycle**
- `ACTIVE / GRACE_PERIOD / PAUSED / EXPIRED / CANCELLED`
- **자동 만료를 배치에 의존하지 않는다.** 상시 스케줄러가 크롤링 배치뿐이라 만료를 거기
  얹으면 "배치가 안 돌아서 만료가 안 됨"이 곧 과금 사고가 된다. `resolve_expected_status()`가
  순수 함수로 계산하고 조회 시점에 DB도 맞춘다(lazy sync)
- 유예 기간 3일 — 결제 실패 즉시 차단하면 카드 갱신 중인 정상 사용자가 끊긴다
- `PAUSED`/`CANCELLED`는 시간과 무관하게 유지, `expires_at` 파싱 실패 시 상태를 바꾸지 않는다
  (파싱 실패를 만료로 해석하면 정상 구독자가 끊긴다)
- 갱신은 만료 전이면 기존 만료시각에서 이어 붙이고, 지났으면 지금부터 센다
- 무료 등기부 초기화는 별도 작업 불요 — 월 경계 계산이 이미 그 역할을 한다

**[승인 4] registry_credit_logs**
- `registry_credits`(한도 계산에 반영되는 관리자 조정)와 **별도**로, 무료 횟수가 움직인
  **모든 사건**(지급/사용/회수/이벤트/환불/기타)을 추적한다
- 사용(USAGE)을 한도 계산에 넣으면 `registry_usage`가 이미 세는 사용량과 이중 차감이 된다 —
  로그에만 남기고 계산에서는 뺀다(`ADJUSTMENT_REASONS`)
- `balance_after` 스냅샷으로 "그 시점에 얼마였는지"를 재계산 없이 조회 가능
- `GET /admin/registry/credit-logs/{user_id}`

**[승인 5] audit_logs**
- `admin_id / action / target_type / target_id / before / after / created_at`
- 등기부 상태 전이, 등기부 한도 조정, 구독 상태 변경이 전부 기록된다.
  `before`/`after`는 **바뀐 필드만** 담는다(전체 행을 넣으면 무엇이 바뀌었는지 오히려 안 보인다)
- 업무 트랜잭션과 같은 커밋에 넣어 "업무만 되고 감사는 빠지는" 상황이 없게 했다
- `GET /admin/audit-logs` (target_type/target_id/admin_id/action 필터)

**[승인 6] Soft Delete**
- **실제로 DELETE가 일어나는 테이블에만** 적용: `favorites`, `search_presets`에
  `deleted_at`/`deleted_by` 컬럼 추가
- `payments`/`subscriptions`/`registry_*`는 삭제 경로가 애초에 없어 제외했다 — 컬럼만 늘리면
  모든 조회에 `deleted_at IS NULL`을 붙여야 해 실익 없이 회귀 위험만 커진다
- 이번 범위는 **컬럼 추가까지**다. 실제 soft delete 전환은 `UNIQUE(user_id,item_id)` 때문에
  재등록이 막히는 문제를 먼저 풀어야 해 별도 판단으로 남겼다(기존 DELETE 동작 무변경)

**[승인 7] Admin REST 구조 개선**
- 신규: `/admin/users`, `/admin/payments`, `/admin/payments/{id}/logs`,
  `/admin/subscriptions`(+PATCH), `/admin/registry/requests`,
  `/admin/registry/credit-logs/{user_id}`, `/admin/audit-logs`
- **기존 경로(`/admin/registry-requests`, `/admin/registry-credits`)는 그대로 유지**한다 —
  운영 문서·테스트가 참조하고 있어 없애면 Breaking Change다. 새 구조는 추가로 제공한다
- `/admin/users`: 이 저장소에 users 테이블이 없어(인증은 Supabase `auth.users`)
  **서비스 활동이 있는 user_id를 집계**해 보여준다. 개인정보는 노출하지 않는다
- 구독 상태 변경만 쓰기이고 나머지는 전부 읽기 전용

**[승인 8] API Response 표준화**
- `{success, data, error, meta, message}` — `error`(도메인 코드)와 `meta`(페이지네이션)를 **추가**
- **`message`는 제거하지 않았다.** 프론트가 `result.message`를 읽고 있어 없애면 Breaking Change다
- Admin의 `HTTPException` 기반 실패는 그대로 뒀다 — 클라이언트가 `status_code`로 분기하고
  있어 envelope로 바꾸는 것은 Spec 결정 사항이라 **Skip**

**[승인 9] Error Code 표준화 — `docs/ERROR_CODES.md` 신설**
- `AUTH/PAY/SEARCH/REGISTRY/ADMIN/SUBSCRIPTION/FAVORITE/ITEM/INTERNAL` 9개 도메인, 40개 코드
- `payments`/`registry`/`favorites`/`search_presets`의 실패 응답에 실제로 연결
- 클라이언트는 문구가 아니라 코드로 분기해야 한다(한국어 메시지는 언제든 바뀐다)

**[승인 10] Enum / Constant 통합 — `api/constants.py` 신설**
- `PaymentStatus`/`SubscriptionStatus`/`RegistryRequestStatus`/`PaymentType`/`BillingCycle`/
  `PlanCode`/`DocumentStatus`/`DocumentType`/`AdminRole`/`AuditAction`/`AuditTargetType`/
  `RegistryCreditReason`/`ErrorCode`
- `str, Enum` 상속이라 SQLite 바인딩·JSON 직렬화에서 문자열처럼 동작한다 —
  기존 코드가 문자열을 그대로 써도 깨지지 않는다
- **문자열 값은 지금 DB에 있는 값 그대로다.** 정의 위치만 모았고 값은 하나도 바꾸지 않았다

**[Test] 회귀 227+48 → 340+48 = 388 검사**
- 23 FK 강제 / 24 Payment 상태머신 / 25 Subscription lifecycle /
  26 audit·credit 로그 / 27 Admin REST 구조 / 28 Soft Delete 컬럼
- envelope 계약 테스트를 새 표준(error/meta 추가, message 유지)으로 갱신

**[문서]** `ERROR_CODES.md`·`STATE_MACHINES.md` 신설, decision-log/backend/CURRENT_STATE/
roadmap/BETA_RELEASE_CHECKLIST/API_KEY_CHECKLIST/TEST_PLAN/README 동기화

---

2026-08-07 (Sprint 28 후속 — 승인 항목 연결 누락 2건 수정)

승인 내용을 구현한 뒤 **실제 사용 경로에 연결됐는지**를 자체 감사하다 두 건을 발견했다.
둘 다 "구조는 만들었는데 아무도 쓰지 않는" 형태라 테스트만으로는 드러나지 않았다.

**[누락 1] 무료 횟수 "사용(USAGE)"이 추적 로그에 남지 않았음**
- 승인 4번의 기록 대상은 `관리자 지급 / 사용 / 회수 / 이벤트 지급 / 환불 / 기타`인데,
  실제로는 `add_credit()`을 거치는 **관리자 조정만** 기록되고 있었다.
  사용자가 무료 횟수를 소진하는 경로(`registry.py`)에는 로깅이 없었다
- `create_registry_request()`의 무료 사용 지점에 `log_credit_event(USAGE, -1)` 연결.
  `related_usage_id`로 `registry_usage` 행과 이어지고, `balance_after`에 잔여 횟수를 남긴다
- **한도 계산에는 반영하지 않는다** — `registry_usage`가 이미 세고 있어 넣으면 이중 차감
- 회귀: 사용 후 로그 1건 생성 / delta -1 / actor USER / 조정 합계·유효 한도 불변 / 사용량 +1

**[누락 2] Subscription Lifecycle이 이용권 게이트에 연결되지 않았음**
- 승인 3번으로 `GRACE_PERIOD`(유예 3일)를 정의했지만, 정작 Premium 판정
  `has_active_subscription()`은 여전히 `status='ACTIVE'`만 봤다 —
  **승인된 유예 정책이 코드에서 한 번도 작동하지 않는 상태**였다
- 게다가 `is_entitled()` 자체에도 결함이 있었다: `GRACE_PERIOD`인데도 `expires_at > now`를
  요구했는데, 유예는 **정의상 만료 시각을 지난 뒤**의 상태다. 즉 이 함수는 GRACE_PERIOD를
  절대 통과시킬 수 없었다. 유예의 기한은 `expires_at + GRACE_PERIOD_DAYS`다
- `is_entitled()`가 만료 시각을 직접 비교하지 않고 `resolve_expected_status()`에 판정을
  위임하도록 변경(규칙이 두 곳에 있으면 반드시 어긋난다)
- `registry.py`에 `get_entitled_subscription()` 신설 — Premium 판정과 플랜 한도 조회가
  이 함수 하나만 본다. **SQL이 아니라 Python에서 판정**하는데, `sync_expired_status()`를
  부르면 커밋이 일어나 `create_registry_request()`의 `BEGIN IMMEDIATE`가 끊기기 때문이다
- 실효 변화: 만료 후 3일 이내 사용자가 서비스를 계속 이용할 수 있게 됐다(승인된 정책대로).
  `PAUSED`/`CANCELLED`/유예 초과는 그대로 차단
- 회귀: 게이트 6종(active/grace/expired/paused/cancelled/none) + 유예 중 플랜 한도 유지

**[빌드]** `npm run build`를 막던 `.next/static` 잔여 아티팩트(이전 빌드 매니페스트 3개)를
**삭제하지 않고** 스크래치패드로 이동해 빌드 통과 확인.

**[Test] 340 → 361 검사**

---

2026-08-07 (Sprint 28 후속 2 — 커밋 경계 정리 / 테스트 Audit)

**[P2 해소] `sync_expired_status()`의 커밋 경계**
- 이 함수는 UPDATE를 하는데 커밋 시점이 호출 맥락에 따라 정반대다: 읽기 경로에서는 여기서
  커밋해야 변경이 남고, 쓰기 트랜잭션 안에서는 커밋하면 **호출부 트랜잭션이 끊긴다**
  (`create_registry_request()`의 `BEGIN IMMEDIATE`가 대표적 — 무료횟수 확인과 INSERT의
  원자성이 깨져 동시성 버그가 되살아난다)
- `commit`을 **키워드 전용 + 기본값 없음**으로 바꿔 호출부가 반드시 명시하게 했다.
  어느 쪽을 기본으로 삼아도 반대 맥락에서 조용히 틀리고, 그 실패는 테스트로 잡기 어렵다
- 회귀: 기본값 호출이 `TypeError`로 막히는지 검증

**[테스트 Audit] 변이(mutation) 검증 — "통과"가 아니라 "잡아내는가"를 확인**
회귀 테스트가 실제로 결함을 막고 있는지 확인하려고, 코드를 일부러 8가지로 망가뜨려
테스트가 실패하는지 측정했다(각 변이는 적용 후 즉시 원복).

| 변이 | 결과 |
|---|---|
| 유예 판정을 만료시각 비교로 되돌림 | 검출(5건 실패) |
| 이용권 게이트를 ACTIVE 단독으로 되돌림 | **최초에는 미검출 → 테스트 보강 후 검출** |
| 결제 상태 전이 검증 무력화 | 검출(6건) |
| 구독 정렬 tie-break 제거 | 검출(3건) |
| USAGE 로깅 제거 | 검출(1건) |
| 감사 로그 기록 제거 | 검출(1건) |
| FK 강제 해제 | 검출(2건) |
| 응답 envelope에서 `error` 제거 | 검출(예외 중단) |

**발견된 테스트 공백 1건**: 이용권 게이트 테스트가 전부 `status='ACTIVE'` + 과거 만료시각
행만 썼다. 그래서 조회 조건에서 `GRACE_PERIOD`를 빼먹어도 Python 판정이 커버해 테스트가
통과했다. **DB에 `GRACE_PERIOD`로 저장된 행**(lazy sync가 이미 돈 뒤의 실제 상태)을 쓰는
케이스를 추가해 공백을 막았다. 재측정 결과 **8/8 전부 검출**.

**[Test] 361 → 365 검사**

---

2026-08-07 (Sprint 28 후속 3 — 프론트엔드 Audit / 성능)

이번 회차는 그동안 lint만 돌리고 코드 감사를 한 적이 없던 **프론트엔드**를 봤다.

**[Bug] 즐겨찾기 토글이 서버 실패에도 상태를 뒤집었음**
- `search/FavoriteButton.tsx`와 `properties/[id]/page.tsx` 둘 다
  `setFavorited(...)`를 응답 성공 여부와 무관하게 실행하고, 그 뒤에 실패 메시지를 띄웠다 —
  **하트는 빨갛게 변하는데 그 아래 "등록에 실패했습니다"가 함께 뜨는** 모순된 화면
- 상태는 "서버 기준으로 그렇게 됐을 때만" 바꾸도록 수정. 다만 중복 등록/이미 삭제됨은
  실패가 아니라 **의도가 이미 이뤄진 것**이므로 상태만 맞추고 에러는 띄우지 않는다
- 이 구분이 가능한 이유가 어제 도입한 도메인 Error Code다
  (`FAVORITE_ALREADY_EXISTS` / `FAVORITE_NOT_FOUND`). 메시지 문구로 분기했다면 문구가
  바뀌는 순간 깨졌을 것이다 — Error Code의 첫 실사용 사례
- `src/lib/api.ts`의 `ApiEnvelope`에 `error`/`meta` 추가, `ERROR_CODES` 상수 신설
- 회귀: 중복 등록·재삭제 시 응답의 `error` 코드를 고정

**[Performance] `/admin/users`의 집계가 전체 사용자에 대해 실행되던 문제**
- 집계 서브쿼리를 바깥에 둬서 SQLite가 **전체 사용자**에 4개 서브쿼리를 실행한 뒤에야
  ORDER BY/LIMIT를 적용했다 — 사용자 N명이면 페이지 크기와 무관하게 4N번 인덱스 탐색
- 페이지를 먼저 자르고 그 결과에만 집계를 걸도록 변경(4×size). 정렬 기준과 반환 행은 동일
- 회귀: 집계값 정확성 + 페이지를 잘라도 집계가 흐트러지지 않는지

**[Audit 결과 — 이상 없음 확인]**
- `localStorage`/`sessionStorage` 사용 0건(토큰을 브라우저 저장소에 두지 않는다)
- `dangerouslySetInnerHTML` 0건, 사용자 입력이 직접 `href`로 들어가는 지점 0건
- 모든 `fetch` 호출에 에러 처리 존재, `.map()` 36곳 전부 `key` 지정
- Open Redirect 방어(`sanitizeRedirectPath`) 유지 확인

**[Test] 365 → 377 검사**

---

2026-08-08 (Sprint 29 — Beta Release 감사, 환경 정합성 점검)

`docs/CLAUDE.md`/`CURRENT_STATE.md`/`roadmap.md`/`BUGS.md`/`decision-log.md`/
`BETA_RELEASE_CHECKLIST.md`/`API_KEY_CHECKLIST.md`/`ENVIRONMENT_VARIABLES.md`/
`ERROR_CODES.md`/`STATE_MACHINES.md`를 실제 코드·DB·환경과 전수 대조했다. 승인 없이 가능한
코드 결함 1건을 수정했고, **승인 필요 범위의 심각한 환경 불일치 1건을 발견**했다(아래).
패키지 설치 승인이 없어 `python-jose` 부재로 백엔드 기동·회귀 테스트(`test_api_regression.py`,
`test_subscription_policy.py`)는 이번에도 실행 불가했다(Sprint 26부터 알려진 항목, 계속 유효).

**[Bug 수정] `api/v1/subscriptions.py:get_active_subscription()`의 유예 기간 필터링 결함**
- `sync_expired_status()`로 방금 `GRACE_PERIOD`로 동기화한 행을 바로 다음 SELECT의
  `AND (expires_at IS NULL OR expires_at > ?)` 조건이 스스로 걸러내 `None`을 반환하는
  구조였다 — `GRACE_PERIOD`는 정의상 `expires_at`이 이미 지난 상태이므로 이 조건과
  본질적으로 양립할 수 없다(`docs/STATE_MACHINES.md`의 유예 기간 정의 참고)
- 현재 이 함수를 호출하는 곳은 저장소 전체에 없어(정의만 되고 미사용) 사용자 영향은
  없었지만, 함수 docstring이 "유효한 구독 행"을 정확히 반환한다고 명시하고 있어 향후
  이 함수를 신뢰하고 호출하는 코드(예: 사용자용 "내 구독" 조회 엔드포인트)가 추가되면
  그대로 재현됐을 잠재 결함이다. `sync_expired_status()`가 이미 상태를 맞춰준 뒤이므로
  `status IN (ACTIVE, GRACE_PERIOD)` 조건만으로 충분해 `expires_at` 필터를 제거했다
- 실제 이용권 게이트(`api/v1/registry.py:get_entitled_subscription()`,
  `has_active_subscription()`)는 애초에 이 SQL 필터를 쓰지 않는 별도 구현이라
  이번 결함의 영향을 받지 않았다(Registry 신청 게이트는 정상 동작)

**[Release Blocking, 신규 발견] 로컬 작업 디렉터리의 `.env` / `auction.db` / `storage/migrations/`가
문서가 기록한 완료 상태와 일치하지 않음**

문서(`docs/BUGS.md` #18, `decision-log.md`, `CURRENT_STATE.md`, `roadmap.md`)는 2026-08-06~07에
Migration 010~015(등기부 사유 컬럼, `auction_case`/`auction`/`auction_item` 복합키,
`payment_logs`/`payment_webhooks`, `registry_credits`/`registry_credit_logs`)가 전부 실행·검증
완료됐다고 기록하고 있다. 이번 회차에 **현재 이 작업 디렉터리의 실제 파일을 직접 열어 대조한
결과**, 아래가 실측 확인됐다(값은 열람하지 않고 구조·스키마·파일명만 확인):

1. `storage/migrations/`에 `009_add_default_sort_index.sql`까지만 존재한다.
   `010_add_registry_request_reason.sql`부터 `015_create_registry_credits.sql`까지
   6개 파일이 전부 없다(`storage/`는 `.gitignore` 대상이라 git 이력으로 복구 불가)
2. 루트 `auction.db`의 `migration_history` 테이블도 `009`까지만 기록돼 있고,
   `auction_case`에 `court_code` 컬럼이 없으며, `auction`/`auction_item`의 UNIQUE 제약이
   각각 여전히 `(case_no, item_no)`다 — **`docs/BUGS.md` #18(다른 법원 물건이 매일 크롤링에서
   덮어써지는 데이터 소실 결함)이 이 DB 파일 기준으로는 미해결 상태**. `audit_logs`,
   `payment_logs`, `payment_webhooks`, `registry_credits`, `registry_credit_logs` 5개
   테이블도 존재하지 않는다
3. `storage/database.py`(git 비추적)의 `CREATE_TABLE_SQL`도 `UNIQUE(case_no, item_no)`
   그대로다 — fresh clone 시 적용되는 스키마 정의 자체가 pre-#18-fix 상태
4. `.env`(git 비추적)의 변수 구성이 `docs/API_KEY_CHECKLIST.md`가 기록한 "코드가 실제로
   읽는 9개"와 겹치지 않는다. 특히 `api/auth.py`가 요구하는 `SUPABASE_JWT_SECRET`이
   없고(`JWT_SECRET`이라는 다른 이름만 있음 — `ENVIRONMENT_VARIABLES.md`가 이미 경고해온
   바로 그 이름 실수), 이 프로젝트 코드가 참조하지 않는 변수(`YOUTUBE_API_KEY`/
   `REDDIT_CLIENT_ID`/`NAVER_DATALAB_*`/`BROWSERBASE_API_KEY`/`FIRECRAWL_API_KEY`/
   `JINA_API_KEY`/`NEXTAUTH_SECRET` 등)가 다수 존재한다. `.env.local`(프론트)은 문서와
   일치해 정상이다
5. `migrate_execute.py`(git 추적, 커밋 `00cef09`에 포함)는 `(court_code, case_no)`/
   `(case_id, item_no)` 기반 로직을 이미 담고 있어 **코드 자체는 #18 수정판이 맞다** —
   즉 코드 수정은 실재했고, 위 3개 파일(`.env`/`auction.db`/`storage/`)만 그 수정 이전
   시점의 상태로 되돌아가 있다. 관련 파일들의 mtime도 전부 이번 세션 시작 직전인
   오늘(2026-08-08) 오전으로 한 시점에 몰려 있어(`auction.db.backup_before_auction_unique_
   20260807_095423`조차 파일명과 다르게 mtime이 08-08), git이 추적하지 않는 로컬 파일
   묶음(`.env`/`auction.db`/`storage/`)이 이 시점에 통째로 교체된 것으로 보인다

**결론 및 처리**: 이 3가지(`.env` 내용, `auction.db` 스키마, `storage/migrations/` 파일 목록)는
전부 이 세션의 원칙상 임의로 되돌리거나 재작성할 수 없는 영역이다(`.env` 수정 금지,
대규모 DB Schema 변경은 승인 필요, 존재하지 않는 마이그레이션 SQL을 문서 서술만으로
추정 재작성하는 것은 위험). **코드는 수정하지 않았고 DB에도 쓰기 작업을 하지 않았다** —
사실 확인과 문서 기록만 하고 Skip했다. 사용자가 올바른 최신 `auction.db`/`storage/`/`.env`
스냅샷을 이 작업 디렉터리에 복원해야 Migration 010~015가 실제로 적용된 상태로 돌아온다
(또는 승인 후 010~015를 문서 기술 내용대로 재작성해 재실행). 이 발견을 반영해
`docs/BUGS.md` #18과 `docs/BETA_RELEASE_CHECKLIST.md`의 P0 목록을 갱신했다.

**[확인 — 이상 없음]** `npm run build` / `npx tsc --noEmit` / `npm run lint`(0건) /
`python -m compileall`(전체 통과). Next.js가 `middleware` 파일 컨벤션이 Next 16에서
deprecated(→ `proxy`)라는 경고를 새로 출력하기 시작했다 — 아직 동작은 하나(현재 빌드 통과),
프레임워크 쪽 명명 변경이라 다음 Sprint에서 `src/middleware.ts` → `proxy` 전환 검토 필요
(동작 변경이 아니라 파일 리네임 수준이라 승인 없이도 가능할 가능성이 높지만, 이번 회차는
감사 범위 안에서 발견만 기록)

**[TODO 재탐색]** 프론트 4건 그대로(전부 백엔드 미지원 컬럼에 대한 정직한 표기, stale 없음),
백엔드 TODO 0건(Sprint 26과 동일)

**[코드 감사 — 이상 없음 확인]** Sprint 27~28에서 신설된 `api/constants.py`,
`api/v1/state_machines.py`, `api/v1/subscriptions.py`, `api/v1/registry_credits.py`,
`api/v1/payment_logs.py`, `api/v1/audit.py`, `api/v1/admin.py`(REST 확장분),
`api/v1/payments.py`(Plan API), `api/v1/registry.py`를 전량 재독해 상태 전이·트랜잭션
경계·소유권 검사·감사 로그 커밋 시점을 검증했다 — 위 1건을 제외하면 결함 없음

---

2026-08-08 (Sprint 29 이어서 — 프론트엔드 Error Code 감사 / jose-free 테스트 신설)

같은 날 재확인 요청에 따라 §13(로컬 `.env`/`auction.db`/`storage/migrations/` 불일치)을
다시 실측했다 — **변동 없음**(migration_history `009`까지, `SUPABASE_JWT_SECRET` 여전히
부재, `python-jose` 여전히 미설치). 이 상태에서 계속 가능한 코드/테스트/문서 작업을 진행했다.

**[Bug 수정] `properties/[id]/page.tsx` — 등기부 구독 필요 UI가 한국어 메시지 문자열 비교로 분기하고 있었음**
- `registryMessage === '구독이 필요합니다'`로 백엔드 `error_response()`의 **문구**를 직접
  비교해 "구독 플랜 선택" UI 노출 여부를 결정하고 있었다 — Sprint 26에서
  `search/FavoriteButton.tsx`에 대해 이미 명시적으로 고친(`docs/CHANGELOG.md` 2026-08-07
  Sprint 28 후속 3 항목) 것과 **동일한 축의 안티패턴**이 등기부 구독 전환 퍼널에 남아 있었다
- 이 문구는 `api/v1/registry.py:145`(`ErrorCode.REGISTRY_SUBSCRIPTION_REQUIRED`)가 만드는
  값이며, 백엔드가 문구를 다듬는 순간(예: 안내를 더 길게 바꾸는 등) 이 화면은 구독 UI를
  영영 보여주지 않게 되어 **결제 전환 자체가 막히는** 실질적 위험이 있었다
- `src/lib/api.ts:ERROR_CODES`에 `REGISTRY_SUBSCRIPTION_REQUIRED` 추가, `page.tsx`에
  `registryErrorCode` state 신설 — `handleRegistryRequest()` 실패 시 `result.error`를
  저장하고, 렌더링은 이 코드로만 분기한다. 구독 필요 상태의 중복 안내 문구는 UI 섹션
  자체가 이미 설명하므로 `registryMessage`를 아예 설정하지 않는 방식으로 억제(그 외 실패
  — 결제 거절, 네트워크 오류 등 —는 `registryMessage`가 항상 그대로 표시된다)
- Type Check / Lint / Build 재확인 — 전부 통과. 프론트엔드 전역 grep으로 동일 패턴
  (`message === '...'`) 잔여 여부 재확인 — 이 1건 외 추가 발견 없음

**[Test, 신규] jose 의존성 없이 실행되는 순수 로직 회귀 2종**
- `python-jose` 부재로 `test_api_regression.py`/`test_subscription_policy.py`가 이 환경에서
  계속 막혀 있는 동안의 최소 방어선으로, `api.auth`를 타지 않는 두 모듈을 대상으로 신설했다
  (패키지 설치 없이, DB는 손대지 않고 in-memory/고정 시각으로 실행)
- `test_state_machines.py`(82검사): Payment 12종 허용 전이 + 9종 금지 전이 + 미지 상태 거부,
  `is_terminal_payment`/`is_paid`(레거시 SUCCESS 호환), Subscription 12종 허용 + 6종 금지 전이,
  **유예 기간(GRACE_PERIOD) 경계값 검증** — 만료 직전/직후/정확히 3일/3일 초과/`expires_at==now`/
  malformed 값(파싱 실패 시 상태 유지) 전부. `docs/BUGS.md` #16과 같은 축의 "만료 시각 처리
  실수"가 재발하면 이 테스트가 즉시 잡아낸다
- `test_registry_credits.py`(20검사): GRANT/DEDUCT 부호 정규화, **RESET 이후 조정만 합산**
  (RESET 반복 처리 포함), 월별 합산 격리, 입력 검증(0/음수/한도초과/미지 사유 거부, 정확히
  한도값은 통과), `registry_credit_logs`가 원장과 함께 기록되는지 + USAGE 로그가 원장 합계를
  건드리지 않는지(이중 차감 방지 확인)
- 두 파일 모두 실행해 **전부 PASS** 확인. 콘솔 인코딩(cp949) 문제로 섹션 헤더에서 한글을
  걷어내고 ASCII로 재작성(기존 `test_subscription_policy.py` 관례와 통일)

**[문서 정정] `docs/TEST_PLAN.md`의 "selenium 미설치" 서술이 stale임을 실측 확인**
- `python -c "import selenium"`/`webdriver_manager`/`pandas` 및 `crawler`/`config`/
  `validator`/`normalizer`/`storage.database` 전체 import가 이 환경에서 **전부 성공**한다 —
  실제로 크롤러 계열 스크립트를 막고 있던 것은 selenium이 아니라 **jose**(크롤러는 애초에
  `api.auth`를 참조하지 않는다)였다. `test_db.py`는 import 확인까지만 하고 실제 실행은
  하지 않았다(courtauction.go.kr에 실제 크롤링 요청을 보내는 스크립트라 회귀에서 자동
  실행하지 않는다는 기존 원칙 유지)
- 위 신규 테스트 2종을 1절에 등록하고 "실행할 수 없는 테스트" 절을 이 실측 결과로 갱신

**[재확인 — 이상 없음]** `api/v1/item.py`/`search.py`/`favorites.py`/`recent_items.py`/
`search_presets.py`/`documents.py`/`doc_stats.py`/`api_server.py`/`src/middleware.ts`/
`src/lib/api.ts`를 전량 재독해 인증·소유권·SQL 파라미터 바인딩·CORS·로깅 설정을 재검증 —
위 프론트엔드 1건을 제외하면 결함 없음. `src/app/properties/[id]/page.tsx` 951줄 전체를
읽고 렌더 분기·비동기 race condition 가드(idRef)·서버 권위 가격 표시를 검증 — 위 1건 외
이상 없음

---

2026-08-08 (Sprint 30 — CTO 승인 하에 Migration 정합성 복구)

Sprint 29(같은 날)에서 발견한 §13/§11 병목(로컬 `auction.db`/`storage/migrations/`가 Migration
010~015 이전 상태로 되돌아가 있음)에 대해, CTO가 "Migration 정합성 복구"(승인 항목 1~4)를
명시적으로 승인했다. 원래 마이그레이션 SQL 파일은 git 비추적(`storage/`)이라 복구할 수 없었으나,
git 추적 코드(`api/v1/payment_logs.py`·`registry_credits.py`·`audit.py`의 실제 INSERT/SELECT문,
`migrate_execute.py`의 실제 쿼리)가 요구하는 정확한 컬럼·제약을 역산할 수 있었다.

**[사전 조사]** 실제 `auction.db`를 직접 조회해 재구성 범위를 확정했다.
- `auction`/`auction_item` 2,012행, `auction_case` 1,467행(당시 문서가 기록한 1,870/1,377과
  다른 규모 — 이 DB가 문서화된 마이그레이션 이후에도 계속 크롤링을 받았거나, 다른 크롤 시점의
  스냅숏임을 시사. 어느 쪽이든 스키마가 pre-fix 상태라는 결론은 동일)
- 법원 간 case_no 충돌 **정확히 3건** 실측(`2024타경34089`/`2024타경3700`/`2024타경4973` —
  2026-08-06 당시 문서가 기록한 것과 **동일한 사건번호들**). `(court_code, case_no, item_no)`
  기준 실제 데이터 충돌 0건(아직 실제 덮어쓰기 소실은 발생하지 않은 상태) — 마이그레이션
  리스크가 낮음을 사전에 확인
- `auction_case.case_no`가 `auction`의 distinct case_no와 100% 일치(고아 0), `auction_item`의
  `(court_name, case_no)`가 전부 `auction`에서 매칭 가능함을 확인 — 재작성 시 데이터 유실 없이
  100% 재연결 가능하다는 확신을 얻은 뒤 실행

**[Migration 010~016 신설]** (`storage/migrations/`)
- `010_add_registry_request_reason.sql` — `registry_requests.reason TEXT` 추가
- `011_auction_case_court_code_unique.sql` — `auction_case`에 `court_code NOT NULL` 추가,
  `UNIQUE(court_code, case_no)`로 재작성(표준 재작성 패턴). id 보존 대신
  `auction_item.case_id`를 `(court_name=court_code)` 매칭으로 명시 재연결(충돌 3건만
  실제로 재배선, 나머지는 무변화) — 이 편이 "충돌 case_no만 골라 분리"보다 항상 정확함
- `012_auction_court_code_unique.sql` — `auction`을 `UNIQUE(court_code, case_no, item_no)`로
  재작성(id는 어디서도 FK로 참조되지 않아 보존 불요, 컬럼 값 무변경)
- `013_auction_item_case_id_unique.sql` — `auction_item`을 `UNIQUE(case_id, item_no)`로
  재작성. id는 **10개 하위 테이블**(favorites/recent_items/registry_usage/registry_requests/
  document_status/doc_raw/parsed_document/tenant_rights/rights_summary/
  rights_analysis_history)이 FK로 참조해 반드시 보존 — 명시적 컬럼 복사로 처리
- `014_create_payment_logs.sql` — `payment_logs`/`payment_webhooks`(event_id UNIQUE 멱등)
- `015_create_registry_credits.sql` — `registry_credits`/`registry_credit_logs`
- `016_create_audit_logs.sql` — `audit_logs`
- **[안전장치, 사전 실측으로 발견]** 011/013은 `PRAGMA foreign_keys=ON` 상태에서 실행하면
  `DROP TABLE`이 하위 테이블의 FK 참조 때문에 즉시 실패함을 리허설에서 실측 확인 —
  두 파일 모두 `BEGIN` 앞에 `PRAGMA foreign_keys=OFF`, `COMMIT` 뒤에 `ON` 복귀를 추가해
  FK 강제 커넥션에서도 안전하게 실행되도록 함(fresh-clone 시나리오 대비)

**[실행 절차]** 백업(`auction.db.backup_before_migration_recovery_20260808_153510`) → 사본
리허설(1차: 실제 DB와 동일 조건, 2차: FK 강제 켠 상태로 처음부터 재현) → 실제 `auction.db`
적용 → 사후 무결성 30개 항목(row count/orphan/dup/NULL/court mismatch/DDL 제약/FK) 전부 통과 →
`payment_logs`/`registry_credits`/`audit_logs`의 실제 함수(log_payment_event/record_webhook/
add_credit/record_audit) 호출 스모크 테스트 통과, QA 데이터는 스크래치 사본에서만 만들고
전부 정리 확인. 실제 `auction.db`에 남은 잔여 QA 행 0건 재확인.

**[Bug 발견 — 이번 복구로 해소]** 실제 auction.db가 pre-fix 스키마였던 동안,
`migrate_execute.py`(정상 코드, git 추적)가 `INSERT INTO auction_case (..., court_code, ...)`를
실행하면 그 컬럼이 없어 **`sqlite3.OperationalError`로 매일 크롤링 파이프라인 2단계가
크래시했을 것**이다(`logs/daily_run.log` 확인 결과 최근 3회 실행은 더 이른 단계 —
`mvp_scraper.py`의 pandas DLL 오류/경로 오류/그 외 실패로 이 단계 도달 전 중단됐음을
별도 확인 — 실제 크래시 사례는 로그에 없지만, 다음에 1단계가 성공하는 즉시 재현됐을 결함).

**[storage/database.py 수정]**
- `upsert_batch()` — 조회/갱신 키를 `(case_no, item_no)`에서 `(court_code, case_no, item_no)`로
  변경. `docs/BUGS.md` #18 완화(2026-08-07 기록)이 "WARNING 로그만 남기고 막지는 못한다"였던
  것과 달리, 이번엔 **쿼리 자체가 다른 법원 행을 찾지 못하게 해 교차 덮어쓰기가 구조적으로
  불가능**해졌다(런타임 경고가 아니라 원천 차단). 스모크 테스트로 실증: 법원 A가 먼저
  upsert한 case_no+item_no를 법원 B가 같은 값으로 upsert해도 별도 행으로 공존(과거엔 A가
  사라졌음), 법원 A가 같은 키로 재upsert하면 정상적으로 제자리 UPDATE
- `CREATE_TABLE_SQL`(fresh clone용) — `UNIQUE(case_no, item_no)` → `UNIQUE(court_code, case_no,
  item_no)`로 정정(마이그레이션 012와 동일한 최종 상태)
- `get_connection()` — `PRAGMA foreign_keys = ON` 추가(CTO 승인 항목 5). 15개 이상의
  REFERENCES가 선언만 되고 무시되던 상태 해소. 마이그레이션 스크립트(011/013)만 예외적으로
  이 안에서 일시 OFF

**[storage/migrate_v4_1.py 수정]** `auction_case`/`auction_item`의 CREATE TABLE을 마이그레이션
011/013과 동일한 최종 제약으로 정정 — fresh clone이 처음부터 올바른 스키마로 시작하도록
(마이그레이션 010~016을 거칠 필요 자체가 없어짐). **검증**: 완전히 빈 스크래치 DB에
`init_db()` → `migrate_v4_1.migrate()` → `run_migrations.run()`(001~016 전부) 순서로 실행해
최종 스키마가 실제 DB와 동일함을 확인(`PRAGMA foreign_keys=ON` 상태로 전 과정 실행,
011/013의 `PRAGMA OFF/ON` 안전장치가 정확히 이 시나리오를 위한 것이었음이 실증됨).

**[신규 회귀] `test_auction_identity.py`** (26검사, 전부 PASS) — docs/BUGS.md #14/#18 재발 방지
전용. (1) 실제 `auction.db`에 대한 읽기 전용 무결성 불변식(dup/orphan/NULL/DDL 제약 검사),
(2) `upsert_batch()`의 법원 교차 덮어쓰기 방지 회귀(스크래치 사본에서만 쓰기, 법원 A→B upsert
후 두 행 공존 + 법원 A 재upsert 시 제자리 UPDATE 확인). 실제 DB는 어떤 테스트 함수에서도
쓰기 대상이 아니다(항상 임시 파일로 복사 후 그 사본에만 씀).

**[사용자 요청 — Supabase 키 명명 확인, `docs/API_KEY_CHECKLIST.md` 8절]** `.env`에
`NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`/`SUPABASE_SERVICE_ROLE_KEY`가 입력되어 있다는 사용자
확인에 따라 5개 변수명(`NEXT_PUBLIC_SUPABASE_URL`/`_PUBLISHABLE_KEY`/`_ANON_KEY`/
`SUPABASE_SERVICE_ROLE_KEY`/`SUPABASE_SECRET_KEY`) 전수 검색. 코드가 실제로 읽는 것은
`NEXT_PUBLIC_SUPABASE_URL`/`NEXT_PUBLIC_SUPABASE_ANON_KEY` 둘뿐(`middleware.ts`/
`supabaseClient.ts`/`supabaseServer.ts`) — `@supabase/ssr`의 클라이언트 생성 함수는 legacy
anon 키 값이든 신규 publishable 키 값이든 그대로 받아들이므로, **변수명은 그대로 두고 그 안에
신규 값을 넣으면 코드 변경 없이 동작**한다고 판단(코드 변경 없음, 문서만 갱신). `.env`
자체 값은 열람하지 않았다. `docs/ENVIRONMENT_VARIABLES.md`/`docs/API_KEY_CHECKLIST.md`에
근거와 판단 기록.

**[확인 — 이상 없음]** `python -m compileall`(전체), `test_state_machines.py`(82검사),
`test_registry_credits.py`(20검사) 재실행 — 마이그레이션 이후에도 전부 PASS(원래 DB에
의존하지 않는 순수 로직이라 예상대로 무영향). `npx tsc --noEmit`/`npm run lint` 통과
(이번 회차는 프론트 코드 변경 없음).

**[남은 것]** `.env`의 `SUPABASE_JWT_SECRET`(변수명 자체 부재, `JWT_SECRET`이라는 다른 이름만
존재)과 `python-jose` 미설치는 이번 범위 밖(`.env` 수정·패키지 설치는 승인 목록에 없음) —
`docs/BETA_RELEASE_CHECKLIST.md` P0-4 신규 등록. 이 둘이 해결되면 `test_api_regression.py`
377검사 + `test_subscription_policy.py` 48항목을 실제로 재실행해 이번 마이그레이션을
HTTP 레벨에서 재검증할 수 있다.

---

2026-08-08 (Sprint 31 — Auth Blocker 재확인 / 테스트 코드 정적 감사 / Soft Delete 복구)

Sprint 30에서 해소한 DB/Migration 병목은 재확인 결과 변동 없음(migration_history/스키마/`.env`
변수 구성 전부 동일) — 동일 Audit을 반복하지 않고 다음 단계로 이동했다.

**[Auth Blocker 재확인, 변동 없음]** `SUPABASE_JWT_SECRET`/`JWT_SECRET`/`NEXT_PUBLIC_SUPABASE_
ANON_KEY`/`NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`/`SUPABASE_SERVICE_ROLE_KEY`/`SUPABASE_SECRET_KEY`
6개 변수명을 코드 전체에서 재검색 — 결과는 Sprint 30과 동일. 코드가 요구하는 것은
`SUPABASE_JWT_SECRET`(백엔드, `api/auth.py`)과 `NEXT_PUBLIC_SUPABASE_ANON_KEY`(프론트 3곳)
둘뿐이며, `.env`에는 여전히 `SUPABASE_JWT_SECRET`이라는 이름이 없다(`JWT_SECRET`만 존재).
`python-jose`도 여전히 미설치. `docs/BETA_RELEASE_CHECKLIST.md` P0-4 그대로 유효.

**[신규 — jose 없이 가능한 테스트 코드 정적 감사]** `python-jose` 부재로 `test_api_regression.py`
(1538줄, 28개 섹션)와 `test_subscription_policy.py`(281줄, 8개 섹션)를 실행할 수 없는 대신
**전체를 정독**해 Sprint 30에서 재구성한 스키마와 실제로 일치하는지 대조했다. 두 파일 모두
Migration 010~016이 만든 스키마(court_code 복합키, payment_logs/registry_credits/audit_logs
등)와는 완전히 일치했으나, **다음 2건은 Sprint 30이 놓쳤던 실제 결함**이었다(실행했다면
바로 발견됐을 것 — jose가 없어 실행으로는 못 잡고 정적 대조로 잡았다):

1. **`test_api_regression.py` 23번(FK 런타임 강제)**이 `get_connection(enforce_foreign_keys=False)`를
   호출하는데, Sprint 30이 만든 `get_connection()`은 인자를 받지 않았다(마이그레이션 스크립트가
   `PRAGMA foreign_keys=OFF/ON`을 SQL 안에 직접 내장하는 방식으로 우회했었음). 원래 설계는
   커넥션 팩토리 자체가 이 스위치를 갖는 것이었다 — `storage/database.py:get_connection()`에
   `enforce_foreign_keys: bool = True` 매개변수를 추가(기본값 True라 기존 무인자 호출은 전부
   무변화). 기존 마이그레이션 SQL의 자체 `PRAGMA` 구문은 그대로 유지(중복이지만 무해)
2. **`test_api_regression.py` 28번(Soft Delete)**이 `favorites`/`search_presets`에
   `deleted_at`/`deleted_by` 컬럼을 기대하는데, Sprint 30은 "코드 참조 0건"이라는 이유로
   의도적으로 생략했었다. 그러나 이는 **CTO 승인 10건 #6(Soft Delete, 컬럼 추가까지가 이번
   범위)의 명시적 승인 사항**이자 테스트가 이미 이를 전제로 작성돼 있어, 생략이 아니라 추가가
   맞는 판단이었다 — `storage/migrations/017_add_soft_delete_columns.sql` 신설
   (`favorites`/`search_presets` 각각 2컬럼, 둘 다 현재 0행이라 무위험). 절차 동일 준수:
   백업(`auction.db.backup_before_soft_delete_20260808_160908`) → 사본 리허설 → 실제 `auction.db`
   적용 → 컬럼 존재 검증 → fresh-clone 부트스트랩(001~017 전체) 재현 검증까지 완료

**[신규 회귀 2종]**
- `test_schema_hygiene.py`(8검사) — 위 두 결함의 회귀 방어: `get_connection()`의 3가지 호출
  형태(무인자/True/False) FK pragma 값 검증, soft delete 컬럼 존재, `migration_history`가
  디스크의 `storage/migrations/*.sql` 전체를 빠짐없이 기록하고 있는지(017 누락 등 재발 방지)
- 기존 `test_state_machines.py`/`test_registry_credits.py`/`test_auction_identity.py` 마이그레이션
  후 재실행 — 전부 PASS(무영향 확인)

**[테스트 코드 감사 결과 — 그 외 이상 없음]** `test_subscription_policy.py`는 Sprint 30
스키마와 완전히 일치(추가 결함 0건). `test_api_regression.py`의 나머지 26개 섹션은
`payment_logs`/`registry_credits`/`audit_logs`/`registry_requests.reason` 등 Sprint 30이 만든
구조와 컬럼명까지 정확히 일치함을 코드 대조로 확인(§21 payment_logs, §20 registry_credits는
Sprint 30 스모크 테스트로 이미 기능 검증 완료).

**[jose 확보 시 즉시 실행 순서]** `python-jose` 설치 + `.env`에 `SUPABASE_JWT_SECRET` 이름으로
값 입력(현재 `JWT_SECRET`의 값을 이름만 바꿔 추가) 후:
```
python test_api_regression.py       # 377+ 검사, 이번 Sprint 수정 2건 포함 28개 섹션 전부
python test_subscription_policy.py  # 48항목
```
두 스크립트 모두 이번 Sprint의 스키마 변경(017 포함)과 완전히 정합됨을 정적 감사로 이미
확인했으므로, 이 시점에는 새로운 실패가 나오면 그 자체가 신규 회귀로 간주할 수 있다.

**[확인 — 이상 없음]** `python -m compileall`(전체) / 4개 jose-free 테스트 전부 PASS(136검사) /
fresh-clone 부트스트랩(001~017) 재현 성공 / 실제 `auction.db` QA 데이터 잔여 0건.
이번 회차는 프론트 코드 변경이 없어 Type Check/Lint 재실행 생략(직전 확인 유효).

**[Auth/Authorization/Ownership/Admin/IDOR/권한상승/금액위조 등 HTTP 레벨 검증]** jose 부재로
계속 Skip. 해당 영역의 **정적 코드 감사**(파라미터 바인딩, 소유권 WHERE 절, 상수시간 비교,
서버측 금액 재계산)는 이전 Sprint들에서 이미 완료돼 있고 이번 회차에 코드 변경이 없어
재감사하지 않았다(중복 방지 원칙).

---

2026-08-08 (Sprint 32 — python-jose 설치, HTTP 레벨 회귀 최초 전체 실행)

CTO 승인 하에 `python-jose`를 설치했다(`from jose import jwt` 정상 확인). 이 저장소 역사상
**처음으로** `test_api_regression.py`/`test_subscription_policy.py`를 실제 HTTP 레벨로 전체
실행했다 — 두 파일 모두 Sprint 27~31에 걸쳐 여러 차례 대상 코드/스키마가 바뀌었지만 jose
부재로 한 번도 실행 확인이 안 된 상태였다.

**[Blocker 확인]** `.env`는 여전히 `SUPABASE_JWT_SECRET`이라는 이름이 없다(`JWT_SECRET`만
존재, 변동 없음). `test_api_regression.py`가 `from api.auth import SUPABASE_JWT_SECRET`을
import하면 빈 문자열을 받게 되므로, 그대로는 모든 인증 라우트가 `500`이 되어 회귀가 무의미해질
상황이었다.

**[수정] `test_api_regression.py` — SUPABASE_JWT_SECRET 프로세스 전용 주입**
- `ADMIN_API_KEY`/`SUPER_ADMIN_API_KEY`가 이미 쓰던 것과 동일한 패턴(`.env` 무수정, 프로세스
  환경에만 합성 값 주입)을 `SUPABASE_JWT_SECRET`에도 적용 — `.env`에 이미 값이 있으면 그 값을
  그대로 쓰고, 없을 때만(이 환경처럼) `secrets.token_hex`로 만든 무작위 값으로 대체한다.
  이 테스트가 검증하는 것은 "서명·인가 로직이 옳은가"이지 "실제 운영 Supabase 비밀값이
  맞는가"가 아니므로, 값 자체는 프로세스 안에서 서명·검증에 같은 값이 쓰이기만 하면 된다
- **결과**: `python test_api_regression.py` **380검사** 전부 PASS(연속 2회 실행, 재현성 확인),
  `python test_subscription_policy.py` **48항목** 전부 PASS. 두 실행 모두 잔여 QA 데이터 0건
  (`cleanup()`이 매번 192건을 정확히 정리)

**[신규 — JWT 적대적 케이스 3건]** 정적 대조 중 §4(Authentication)이 "토큰 없음/구조가 깨진
토큰/sub 없는 토큰"만 다루고 사용자가 명시적으로 요청한 "만료/잘못된 JWT"의 더 현실적인
공격면(만료 시각, 잘못된 서명, 알고리즘 혼동)을 다루지 않음을 확인해 추가했다:
- **만료 토큰**(`exp`가 1시간 전) → `401` 확인. python-jose가 `exp` 클레임을 기본적으로
  검증함을 실측
- **잘못된 서명 토큰**(구조는 정상 HS256 JWT, 비밀키만 다름 — "not-a-real-token" 같은 구조
  자체가 깨진 문자열과는 다른, 더 현실적인 위조 시도) → `401` 확인
- **alg=none 토큰**(서명 검증 자체를 우회하려는 고전적 공격) → jose 라이브러리가 인코딩
  단계에서부터 거부함을 확인(그 자체로 공격면이 성립하지 않음), 별도로 서버가
  `algorithms=["HS256"]`을 명시 고정해두었다는 사실도 재확인(코드 감사는 이전 Sprint 완료분)
- 이 과정에서 나온 `datetime.utcnow()` deprecation을 `datetime.now(timezone.utc)`로 정리(Code Quality)

**[테스트 결과 요약]**
- `test_api_regression.py`: 28개 섹션(Health/Search/Detail/Auth/Favorite/Recent/Preset/
  Payment/Subscription/Registry/Admin/Provider/정렬결정성/Plan API/API표면/envelope/CORS/
  Admin권한/registry_credit/payment_logs/auction식별키/FK강제/Payment상태머신/Subscription
  Lifecycle/audit·credit로그/Admin REST/Soft Delete) **전부 실제 HTTP 요청으로 통과** —
  Sprint 30(Migration 010~016)·31(017 Soft Delete, `get_connection` 매개변수)에서 구축한
  모든 것이 이제 코드 리뷰나 직접 SQL 검증이 아니라 **실제 서버 응답 레벨**로 재확인됨
- `test_subscription_policy.py`: 8개 섹션(가격/한도/할인구조/월리셋/auction_case무결성/
  auction식별키/credit원장) 전부 통과 — Sprint 30 마이그레이션이 정책 계산 함수 레벨에서도
  완전히 정합됨을 재확인

**[Compile/Type/Build/Lint]** `python -m compileall`(전체, 신규 테스트 파일 포함) /
`npx tsc --noEmit` / `npm run lint`(0건) / `npm run build` 전부 통과.

**[Security — 재확인 및 신규]** IDOR(타인 favorites/payments/registry-requests/payment_logs
접근 차단), Admin 권한 게이트(무키/오답 403, ADMIN이 SUPER_ADMIN 작업 시도 403), 금액 위조
거부(PAY_AMOUNT_MISMATCH), 소유권 격리 — 전부 실제 HTTP 응답으로 재확인(이전엔 코드 정독으로만
확인했던 것). 신규: JWT 만료/서명위조/alg혼동 방어 실증(위 참고).

**[jose 확보 후 즉시 실행 계획 — 완료]** Sprint 31이 예고한 "jose 확보 시 즉시 실행 순서"를
그대로 따라 실행했고, 예고한 대로 **새로운 실패 없이** 통과했다 — Sprint 30/31의 정적 대조가
정확했음을 실행으로 확정.

**[남은 것]** `.env`의 `SUPABASE_JWT_SECRET` 이름 자체는 여전히 없다 — 이번 회차는 테스트
프로세스 안에서만 우회했을 뿐, **실제 운영 배포 시에는 여전히 `.env` 수정이 필요하다**
(`docs/BETA_RELEASE_CHECKLIST.md` P0-4, 여전히 P0 유지). KG이니시스 실연동은 계속 별개 사안.

---

2026-08-09 (Sprint 33 — 전체 test_*.py 인벤토리 재탐색 / Race Condition 회귀 신설 / 미실행 테스트 수리)

Sprint 32까지 확인된 5종 외에 저장소 루트의 `test_*.py`를 전수 재탐색해 이번 세션에서 한 번도
고려되지 않았던 파일이 남아있는지 점검했다(`ls test_*.py` 13개 전체 대조).

**[발견] 지금까지 한 번도 실행되지 않았던 안전한 테스트 3개**
- `test_intent_analyzer.py`(순수 함수, DB/API 무의존) — 실행 결과 16/16 PASS, 결함 없음
- `test_normalizer.py`(순수 함수) — 검사 자체는 19/19 PASS였지만 **마지막 요약 출력에서
  크래시**했다. 원인: 테스트 케이스 설명 문자열에 em-dash(—, U+2014)가 섞여 있어 Windows
  cp949 콘솔 인코딩이 실패(`UnicodeEncodeError`) — 다른 테스트 파일들이 이미 채택한
  "출력은 ASCII만" 컨벤션(`test_subscription_policy.py` 등)을 이 파일만 놓치고 있었다.
  해당 문자만 ASCII 하이픈으로 교체해 해결(검사 로직 자체는 원래도 정상이었음) — 29/29 PASS
- `test_search.py`(`/api/v1/search` 주소 Intent 회귀) — **11/17 FAIL**. 근본 원인 조사:
  이 파일의 하드코딩된 기대값("서울 221건" 등)은 Sprint 4 백필 시점 스냅숏 실측치인데,
  (1) `/api/v1/search`에 나중에 추가된 D7 기본 필터(`auction_date >= 오늘`, `include_closed`
  미지정 시 적용)가 이 테스트 작성 당시엔 존재하지 않았고, (2) 크롤링이 계속되며 데이터 자체도
  늘었다. `include_closed` 유무로 같은 검색어를 대조해 원인을 정확히 격리: 13개 케이스 중
  11개는 `include_closed=True`로 원래 기댓값과 **정확히 일치**(검색 로직 자체는 무결함을
  실증), 서울(221→284)·빛가람동(7→12) 두 곳만 실제 데이터 증가로 드리프트. 조치:
  `search_total()` 헬퍼가 항상 `include_closed=True`로 호출하도록 수정(이 파일은 매각기일
  필터가 아니라 주소 파싱 자체를 검증하는 것이 원래 목적이므로), 드리프트가 확인된 두 값만
  오늘 실측치로 갱신 — 17/17 PASS

**[신규] `test_race_conditions.py` — 등기부 무료한도 / 초과결제 동시성 방어 (15검사)**
- 배경: `docs/BUGS.md`/`docs/decision-log.md`는 두 방어(등기부 무료한도 `BEGIN IMMEDIATE`,
  초과결제 조건부 UPDATE)를 "5/10/20 스레드 동시 요청으로 실측 검증"이라고 여러 차례
  기록하고 있었지만, 전체 `test_*.py`에 `Thread`/`concurrent` 사용이 **0건**이었다 — 그
  검증이 자동화된 회귀로 한 번도 남지 않았다는 뜻이다. 이번에 그 공백을 메웠다
- 시나리오 1: BASIC(월 5회 무료) 사용자가 서로 다른 물건 10개를 실제 스레드 10개로 동시
  신청 → 정확히 5건만 무료(PENDING), 5건은 PAYMENT_REQUIRED, `registry_usage` 원장도
  정확히 5건(6건 이상이면 레이스 재발)
- 시나리오 2: PAYMENT_REQUIRED 신청 1건에 결제 8건을 동시 전송 → 정확히 1건만 성공,
  나머지 7건은 `PAY_ALREADY_PROCESSED`, 등기부 신청에 실제로 연결된 것도 정확히 1건
- **테스트 설계 과정에서 발견한 자체 결함(코드 결함 아님)**: 처음엔 두 시나리오가 같은
  `user_id`를 공유했는데, 시나리오 1이 남긴 5건의 미결제 `PAYMENT_REQUIRED` 신청이 시나리오
  2의 "타깃 1건짜리 경쟁" 전제를 깨뜨려 2건이 동시 성공하는 것처럼 보였다 — 실제 원인은
  결제 레이스 방어 결함이 아니라 테스트 시나리오 간 데이터 오염이었음을 확인하고, 두 시나리오를
  별도 user_id로 분리해 해결. 초기 `cleanup()`도 FK 참조 순서 누락(`registry_credit_logs`/
  `payment_logs`를 부모 테이블보다 먼저 지우지 않음)으로 `FOREIGN KEY constraint failed`가
  발생해 첫 실행이 중간에 멈췄었다 — `test_api_regression.py`의 기존 cleanup 순서를 그대로
  따르도록 수정
- 연속 2회 실행 전부 PASS(재현성 확인)

**[QA 데이터 잔여 정리]** 위 `test_race_conditions.py`의 첫(버그가 있던) 실행이 cleanup 크래시로
`qa-race-f9f8590a6889` 사용자의 행 30건(payments/subscriptions/registry_requests/
registry_usage/payment_logs/registry_credit_logs)을 실제 `auction.db`에 남겼다. `qa-` 접두사로
식별 가능한 테스트 전용 데이터임을 확인한 뒤 FK 안전 순서로 수동 정리 — 정리 후 전 테이블
`user_id LIKE 'qa-%'` 잔여 0건 재확인(실사용자 데이터는 조회·삭제 대상에 없었음).

**[신규 확인 — Security]** 전 Pydantic 모델(`FavoriteRequest`/`PaymentCreateRequest`/
`RegistryRequest`/`SearchPresetRequest`/`StatusUpdateRequest`/`RegistryCreditRequest`/
`SubscriptionStatusRequest`) 재확인 — Mass Assignment 취약점 없음. 사용자 액션은 전부
`user_id`를 요청 바디가 아니라 `Depends(get_current_user)`(JWT)에서만 받는다. `user_id`를
바디에 직접 받는 유일한 모델(`RegistryCreditRequest`)은 SUPER_ADMIN이 타인 계정을 조정하는
의도된 기능이라 문제 없음(기존 감사와 일치, 신규 결함 아님).

**[신규 확인 — Performance]** 크롤러/API 핫패스 쿼리 7종에 `EXPLAIN QUERY PLAN` 실측 — 전부
인덱스 사용 확인, 풀스캔 0건(`auction_case`/`auction`/`auction_item`의 UNIQUE 자동 인덱스,
`registry_credits`/`payment_logs`/`payment_webhooks`/`audit_logs`의 신설 인덱스 전부 적중).
Migration 010~017이 만든 인덱스가 실제로 쓰이고 있음을 최초로 실측 확인.

**[문서]** `docs/TEST_PLAN.md`에 신규/수리된 파일 5종 등록 및 근거 기록.
`docs/CLAUDE.md`의 "Tests" 절이 `python test_db.py`를 실행 예시로 들고 있어(실제로는 실제
크롤링을 유발하는 파일이라 부적절한 예시) `test_api_regression.py`로 정정하고 예외 목록 명시.

**[확인 — 이상 없음]** `python -m compileall`(전체) / `npx tsc --noEmit` / `npm run lint`(0건) /
`npm run build` 전부 통과. **자동 회귀 스위트 10개 파일, 전부 PASS**(실행 불가/의도적 제외:
`test_db.py`/`test_docs.py`/`test_docs2.py` — 실제 courtauction.go.kr 크롤링, `test_filter.py`
— dead code 대상 비어서션 데모).

---

2026-08-09 (Sprint 34 — 엔드포인트 커버리지 공백 발견, 문서 Drift 정정)

Sprint 29~33에서 다루지 않은 새 영역을 찾아 진행했다: TODO/FIXME 전수 재탐색, 문서-코드
대조, API 엔드포인트별 테스트 커버리지 감사.

**[TODO/FIXME/HACK/XXX/NotImplementedError 전수 재탐색]** 백엔드(`api`/`storage`/`crawler`/
`filter`/`config`/`normalizer`/`validator`/`intent`/`models`) + 프론트(`src`) 전체 재확인 —
신규 발견 0건. `payment_providers.py`의 `NotImplementedError` 6개는 전부 의도된 자리 구현
(KG이니시스 실연동 대기), 프론트 TODO 4건은 기존과 동일(백엔드 미지원 컬럼에 대한 정직한 표기).

**[엔드포인트별 테스트 커버리지 감사 — 신규 방법론]** `api/v1/*.py`의 `@router.*` 데코레이터
31개를 전수 목록화하고, `test_api_regression.py`가 실제로 호출하는 경로와 대조했다(단순
"통과했는가"가 아니라 "애초에 검사 대상인가"를 확인하는 방식 — 사용자 요청 6번 Test Quality
Audit의 "중요한 endpoint에 테스트가 없는가"에 해당). **2개 엔드포인트가 테스트 0건**으로
확인됨:
- `HEAD /api/v1/item/{id}/documents/{doc_type}` — `properties/[id]/page.tsx`가 문서 뷰어를
  열기 전에 실제로 호출하는 프로브 엔드포인트(`docCheckKey`). GET/HEAD를 별도 라우트로 나눈
  이유(OpenAPI Duplicate Operation ID 회피, Sprint 26)가 유지되는지 지금까지 한 번도
  자동 검증되지 않았다
- `GET /api/v1/admin/payments/{id}/logs` — 사용자용 `GET /payments/{id}/logs`(§21, 이미
  검증됨)와 별개 라우트로, 소유권 검사 없이 관리자가 임의 payment_id를 조회하는 결제 분쟁
  대응용 엔드포인트인데 지금까지 테스트가 없었다

두 곳 모두 `test_api_regression.py`에 회귀 추가(§3, §21) — HEAD가 GET과 상태코드 일치하는지,
잘못된 문서타입/존재하지 않는 물건에도 정확히 응답하는지 / Admin이 임의 결제 로그를 볼 수
있는지, 키 없이는 403, 존재하지 않는 payment_id는 404인지. **377 → 387검사**로 확대, 연속
2회 전부 PASS, 잔여 QA 데이터 0건 재확인.

**[문서 Drift 정정]** `docs/backend.md`/`docs/roadmap.md`에서 이미 해결된 사안을 여전히
미해결로 서술하던 지점을 코드 대조 후 정정:
- `docs/backend.md` "알려진 문제점": ~~`PRAGMA foreign_keys=ON`이 없어 FK 미강제~~ →
  2026-08-08 Migration 정합성 복구로 해결됨(그때는 이 파일에 반영 안 됨). ~~`ADMIN_API_KEY`
  `.env` 미설정~~ → 변수명은 이제 존재(값 미확인). ~~`REFUNDED`는 죽은 상태~~ → Sprint 28
  Payment State Machine으로 정식 상태값이 됨(도달 엔드포인트만 아직 없음)
- `docs/backend.md` 디렉터리 구조 목록에 Migration 011~017과 신규 모듈(`constants.py`/
  `registry_credits.py`/`payment_logs.py`/`subscriptions.py`/`state_machines.py`/`audit.py`)
  6개가 누락돼 있었음 — 추가
- `docs/roadmap.md`의 "In Progress > Backend" 절도 동일하게 `ADMIN_API_KEY` 서술 정정
- `docs/architecture.md`/`docs/frontend.md`/`docs/decision-log.md`/`docs/ERROR_CODES.md`/
  `docs/STATE_MACHINES.md`는 관련 키워드(FK/jose/selenium/ADMIN_API_KEY/LogoutButton 등)
  재검색 결과 이미 정확했음(신규 수정 없음)

**[확인 — 이상 없음]** `python -m compileall`(전체) / `npx tsc --noEmit` / `npm run lint`(0건)
전부 통과. Mass Assignment는 Sprint 33에서 이미 전수 확인해 이번엔 반복하지 않음.

---

2026-08-09 (Sprint 35 — Beta 사용자 여정 마지막 단계 커버리지 공백 발견·해결: 등기부 실다운로드)

Sprint 34가 "엔드포인트가 애초에 테스트 대상인가"를 감사했다면, 이번엔 "테스트가 있는
엔드포인트라도 진짜 성공 경로까지 검증하는가"를 감사했다(사용자 요청 4번 테스트 원칙
"테스트가 실제 요구사항을 검증하고 있는가").

**[감사 방법]** `docs/CLAUDE.md`가 정의한 Beta 사용자 여정(검색→...→Registry 신청→무료한도
사용→초과결제→다운로드)을 그대로 따라가며, 각 단계마다 test_api_regression.py의 어떤 검사가
그 단계를 커버하는지 역추적했다. 대부분은 §8~10(Payment/Subscription/Registry)이 TEST_USER
하나를 공유하며 이어지는 구조라 이미 사실상의 "한 사용자 연속 여정" 테스트였음을 확인(BASIC
월구독 → PRO 연구독 → 등기부 10건 신청으로 한도 소진 → 11번째 초과결제, 전부 같은
`TEST_USER`) — 새로 발견한 것은 마지막 한 단계뿐이었다.

**[발견] 등기부 "실제 성공 다운로드" 경로가 테스트 0건**
- 기존 §9의 유일한 다운로드 검사는 `doc_url`을 항상 존재하지 않는 더미 파일명
  (`qa-regression-not-a-real-file.pdf`)으로 설정해 "COMPLETED인데 파일이 없으면 거짓 성공을
  반환하지 않는다"는 **방어 경로**만 검증했다 — 베타 사용자 여정의 마지막 단계, 즉
  "실제로 파일이 정상적으로 내려오는" **성공 경로**는 이 저장소 전체에서 한 번도 자동
  검증된 적이 없었다
- 같은 이유로 `registry.py:download_registry()`의 경로 탐색 방어(`commonpath` 검사)도
  테스트 0건이었다(전체 `test_*.py`에 `traversal`/`../` 검색 결과 무), `documents.py`의
  동일 패턴 방어도 마찬가지지만 이번엔 등기부 쪽만 추가(Registry가 사용자 결제와 직결된
  더 민감한 경로이므로 우선)

**[수정] `test_api_regression.py` §9에 2건 추가**
- 실제 임시 파일(`registry_documents/qa-regression-real-file.pdf`, PDF 매직바이트로 시작하는
  더미 바이트열)을 만들고 `doc_url`을 그 파일명으로 UPDATE → `GET .../download` 호출 →
  상태코드 200, 응답 바디가 원본 바이트와 정확히 일치, `Content-Disposition`에 파일명이
  노출되는지 확인
- 같은 신청의 `doc_url`을 `../../../../etc/passwd`로 바꿔 경로 탐색을 시도 → 404로
  차단되는지 확인(DB 값이라 사용자가 직접 조작할 순 없지만, 방어 로직 자체의 무음 회귀를
  잡기 위해 별도로 확인할 가치가 있다고 판단)
- `finally` 블록에서 임시 파일 삭제 + 해당 `registry_requests` 행을 원래 상태(PENDING,
  doc_url/completed_at NULL)로 복구 — 이후 이어지는 §10/§11 검사가 이 행의 상태에 의존하지
  않지만, 부작용을 남기지 않는 것을 원칙으로 했다

**[검증]** 377 → **391검사**, 연속 3회 실행 전부 PASS. `registry_documents/`에 임시 파일이
남지 않음을 매 실행 후 확인, `auction.db`에 QA 잔여 데이터 0건 재확인.

**[확인 — 이상 없음]** `python -m compileall` 통과(신규 코드 변경은 테스트 파일뿐).

---

2026-08-09 (Sprint 36 — documents.py에도 같은 "성공 경로 미검증" 패턴 확인·해결)

Sprint 35에서 등기부(`registry.py`) 다운로드에 적용한 감사("방어 경로만 테스트되고 진짜
성공 경로는 검증된 적 없음")를 크롤러 수집 문서 엔드포인트(`api/v1/documents.py`,
SPEC/STATUS/APPRAISAL)에도 동일하게 적용했다.

**[발견]** 기존 §3(Detail/Documents)의 문서 검사는
`check_true("document known type", get_status in (200, 404))` — **200과 404를 둘 다
통과로 처리**하고 있었다. 즉 이 검사는 "400을 내지 않는다"만 확인할 뿐, 실제로 파일이
있어서 200이 나오는 정상 경로도, 없어서 404가 나오는 정상 경로도 **어느 쪽이 맞는지,
200일 때 진짜 올바른 내용이 오는지**는 한 번도 검증하지 않았다 — Sprint 35에서 등기부
다운로드에 대해 지적한 것과 정확히 같은 축의 결함.

**[수정]** `test_api_regression.py` §3에 추가:
- 선택한 물건의 SPEC 문서가 **이미 실제로 존재하면**(크롤러가 수집해 둔 진짜 파일) 그
  파일이 비어있지 않은지 확인
- **존재하지 않으면** `get_doc_dir()`(문서 경로 계산 로직, 상용 코드와 완전히 동일한
  함수를 그대로 import)로 실제 경로를 계산해 임시 파일을 만들고, `GET`/`HEAD` 왕복으로
  진짜 200 + 올바른 바이트가 오는지 확인한 뒤 **자신이 만든 파일만** 정확히 삭제
- 디렉터리 정리는 `os.rmdir()`을 시도해 실패하면(그 안에 실제 크롤러 파일이 남아있어
  비어있지 않음) 즉시 멈추는 방식으로 안전하게 처리 — 실측 확인: 선택된 물건은 이미
  `appraisal.pdf`/`status.html`/`status.json`이 실존했고 `spec.pdf`만 없었다. 임시
  `spec.pdf`만 만들고 지운 뒤 나머지 3개 파일과 디렉터리 구조는 그대로 남아있음을
  `find`/`grep -rl qa-regression`으로 재확인(잔여 0건)

**[검증]** 391 → **394검사**, 연속 실행 확인, `documents/`에 테스트 콘텐츠(`qa-regression`
문자열) 잔여 0건, `auction.db` QA 데이터 잔여 0건.

**[결론]** 등기부(Sprint 35)와 문서(Sprint 36) 두 다운로드 엔드포인트 모두 이제 "방어
경로"와 "성공 경로"를 둘 다 실제로 검증한다. 같은 패턴을 가진 다른 파일 서빙 엔드포인트는
이 저장소에 더 없음(전수 확인: `FileResponse` 사용처는 `documents.py`/`registry.py`
2곳뿐, grep으로 재확인).

**[확인 — 이상 없음]** `python -m compileall` / `npx tsc --noEmit` / `npm run lint`(0건) 전부 통과.

---

2026-08-09 (Sprint 37 — 등기부 중복 신청 방지 결함 발견·수정, `docs/BUGS.md` #19)

Sprint 35~36에서 "방어 경로만 있고 성공 경로 미검증"을 찾았다면, 이번엔 "State/Data
Consistency Audit" 관점에서 저장소 전체 코드를 다시 훑어 실제 기능 결함을 찾았다.

**[감사 방법]** 사용자 요청 3번(State/Data Consistency Audit)의 "중복 요청" 항목을 Registry
도메인에 적용 — `create_registry_request()`가 신규 신청 생성 전에 "같은 사용자·같은 물건에
이미 진행 중인 신청이 있는가"를 확인하는지 코드를 재확인했다.

**[발견] 등기부 신청 중복 방지 완전 부재**
- `api/v1/registry.py:create_registry_request()`는 물건 존재·구독 여부·이번 달 무료 한도만
  확인하고, **동일 (user_id, item_id)에 대한 기존 신청 여부는 전혀 확인하지 않았다**
- 실측 재현: 테스트 스크립트로 같은 `item_id`에 3회 연속 `POST`했더니 `registry_requests`
  3행이 각각 생성되고 **무료횟수가 3회 소모**됨(is_free=True 3건)
- 화면상 "신청 완료 후 신청하기 버튼이 사라지는" UI 흐름 때문에 정상적인 클릭 한 번짜리
  사용에서는 드러나지 않지만, 중복 클릭·새로고침 후 재제출·직접 API 호출(스크립트/재시도
  로직)로 같은 물건에 대해 월 무료 한도를 반복 소모하거나 `PAYMENT_REQUIRED` 신청이
  중복 생성될 수 있는 실질적 결함이었다

**[판단]** 새 UX/Spec 도입이 아니라 "사용자당 물건당 진행 중인 신청은 1건"이라는 기존
직관적 불변식을 채우는 것이므로, PM 결정이 필요한 Spec 변경이 아니라 **승인 없이 수정
가능한 버그**로 분류해 즉시 고쳤다.

**[수정] `api/v1/registry.py`**
- `BEGIN IMMEDIATE` 트랜잭션 내부, 무료 한도 확인 이전에 `status IN (PENDING,
  PAYMENT_REQUIRED, PROCESSING)`인 기존 신청을 조회한다
- 있으면 새로 만들지 않고 **그 기존 신청을 그대로 반환**한다(응답에 `already_requested: true`
  플래그만 추가 — 기존 필드는 전혀 바뀌지 않아 Breaking Change 아님, `free_remaining`은
  현재 실제 잔여값으로 최신화해서 돌려준다)
- `COMPLETED`/`FAILED`(종결 상태)는 이 검사 대상에서 제외 — 발급 실패 후 재시도, 재발급
  요청 같은 정당한 흐름을 막지 않기 위함

**[회귀 검증]** `test_api_regression.py` 9번(Registry)에 8개 검사 추가:
- 같은 물건 재신청 → 동일 `id` 반환, `already_requested` 플래그, `free_remaining` 불변
- DB 레벨 확인 → `registry_requests`/`registry_usage` 각 정확히 1행만 존재
- `FAILED` 처리 후 재신청 → 새 `id`로 정상 생성(차단되지 않음), 플래그 없음
- 하위 검사(§10 초과결제 흐름)가 의존하는 "정확히 1건 무료 소모" 전제가 깨지지 않도록,
  FAILED 재시도 서브테스트가 만든 부수 상태를 FK 안전 순서(`registry_requests` →
  `registry_credit_logs` → `registry_usage`)로 정밀 원복 — 원복 후 무료 소모 건수가
  정확히 1로 돌아오는지까지 확인

**[검증]** 394 → **402검사**, 연속 3회 실행 전부 PASS, `auction.db` QA 데이터 잔여 0건.
`test_race_conditions.py`(서로 다른 물건 10개 동시 신청)는 이번 변경과 무관해 재확인만
하고 영향 없음을 확인. `python -m compileall`/`npx tsc --noEmit`/`npm run lint`(0건)/
`npm run build` 전부 통과.

**[문서]** `docs/BUGS.md` #19 신규 등록(발견·해결 전 과정 기록), `docs/TEST_PLAN.md` 9번
섹션·검사 총계 갱신.

---

2026-08-09 (Sprint 38 — 구독 중복 결제 방지 결함 발견·수정, `docs/BUGS.md` #20)

Sprint 37에서 발견한 "중복 요청/멱등성 부재" 패턴(Registry, #19)을 Payment/Subscription/
Registry Credit 도메인 전체로 확장해 같은 결함이 숨어 있는지 감사했다.

**[감사 범위]** `POST /api/v1/payments`(SUBSCRIPTION/OVERAGE_USAGE 둘 다), Registry Credit
원장의 쓰기 경로(무료 소진/관리자 조정), Webhook 수신 경로(HTTP 노출 여부), Subscription
소유권(IDOR) 노출 범위를 순서대로 훑었다.

**[발견 1] 구독(SUBSCRIPTION) 결제 중복 방지 완전 부재 — 실제 결함, 즉시 수정**
- `create_payment()`가 SUBSCRIPTION 요청 시 기존 유효 구독 여부를 전혀 확인하지 않아, 같은
  사용자가 연이어 구독을 요청하면 매번 새 `subscriptions`+`payments` 행이 생겨 중복 결제됨
  (실측: PRO 연 구독 2회 연속 요청 → 198,000원 결제 2건, 둘 다 ACTIVE 구독 행, 두 번째는
  기간 연장 없이 순수 중복 청구)
- 반면 OVERAGE_USAGE는 이미 안전함을 확인 — 결제 대상(`target_request`)을 `payment_id IS
  NULL AND status='PAYMENT_REQUIRED'`로 매번 재조회하므로 순차 재요청은 대상 없음 오류로
  막히고, 동시 레이스는 조건부 UPDATE + rowcount 검사로 `test_race_conditions.py`가 이미 검증함
- 프론트(`properties/[id]/page.tsx`)의 구독 UI는 "유효한 구독 없음" 응답에서만 렌더링되고
  성공 즉시 스스로 사라지므로, "이미 구독 중이면 재구독 불가"는 이미 전제된 불변식이었다 —
  #19와 동일하게 승인 없이 수정 가능한 버그로 판단해 즉시 고쳤다. 상세 내용은 `docs/BUGS.md`
  #20 참고

**[발견 2] Registry Credit 원장 — 관리자 조정 경로는 정상(수정 불필요), FAILED 환불 누락은
정책 결정 필요(Backlog)**
- `POST /admin/registry-credits`(GRANT/DEDUCT/RESET)는 SUPER_ADMIN이 매번 의도적으로 남기는
  개별 원장 기록이라 중복 방지가 오히려 부적절함 — 정상 설계로 판단, 수정하지 않음
- 무료 소진 시의 `log_credit_event(USAGE, ...)`는 이미 #19의 `BEGIN IMMEDIATE` 트랜잭션·중복
  방지 검사 안에 있어 별도 결함 없음
- 다만 무료로 소진된 `registry_requests`가 이후 관리자에 의해 FAILED 처리돼도 소진된
  `registry_usage`(=무료횟수)가 전혀 환불되지 않음을 발견. `RegistryCreditReason.REFUND`가
  정의만 되어 있고 어디서도 호출되지 않는 죽은 사유 타입이었다. "모든 FAILED가 환불 대상인지,
  사유별로 다른지"는 새 정책이 필요해 임의로 구현하지 않고 Backlog로만 기록했다

**[발견 3] Webhook 수신 경로 — 현재 HTTP로 노출되지 않음(위험 없음)**
- `api/v1/payment_logs.py:record_webhook()`은 순수 함수이고 이를 호출하는 `APIRouter`가
  어디에도 없다 — KG이니시스 미연동 상태와 일관되게, 현재는 Webhook 위조/재전송 공격 표면
  자체가 없음을 확인

**[발견 4] Subscription 소유권(IDOR) — 노출 표면 자체가 없음**
- `api/v1/subscriptions.py`에는 사용자용 HTTP 엔드포인트가 하나도 없다(구독 생성은
  `POST /api/v1/payments`로만, 조회/취소는 아직 없음) — 타인 구독 열람/취소를 시도할 경로
  자체가 없어 확인할 대상이 없음

**[회귀 검증]** `test_api_regression.py` 8번(Payment/Subscription) 재구성 + 신규 검사 6개,
연쇄 영향으로 21번(Payment Logs)의 구독 생성 부분을 전용 사용자로 분리. 402 → **410검사**,
연속 3회 실행 전부 PASS, `auction.db` QA 데이터 잔여 0건. `test_subscription_policy.py`는
이번 변경과 무관(DB 직접 조작 방식)함을 재확인. `python -m compileall`/`npx tsc --noEmit`/
`npm run lint`(0건)/`npm run build` 전부 통과.

**[문서]** `docs/BUGS.md` #20 신규 등록, `docs/TEST_PLAN.md` 8번 섹션·검사 총계 갱신.

---

2026-08-09 (Sprint 38 재개 — 구독 결제 동시요청 레이스 발견·수정, 결제 실패 재시도 회귀 강화)

Claude Code Auto-update failed로 세션이 한 번 끊겼으나, `git status`/`git diff`/`docs/BUGS.md`/
`docs/CHANGELOG.md`/`docs/CURRENT_STATE.md`/`docs/TEST_PLAN.md` 전수 재확인 결과 이전 Sprint 38
작업(구독 순차 중복 방지 수정, 410검사)은 코드 손상이나 부분 적용 없이 그대로 남아 있었다
(`python -m compileall` + `test_api_regression.py` 재실행으로 실측 확인). 처음부터 반복하지
않고 중단 지점부터 이어서 더 깊은 감사(동시성/실패-재시도)를 진행했다.

**[발견] 구독 결제 중복 방지의 순차 수정만으로는 동시 요청(Race Condition)을 막지 못함**
- 이전 수정(`get_entitled_subscription()`으로 확인 후 생성)은 잠금 없는 SELECT -> 판단 ->
  INSERT라, 실측 재현 결과 같은 사용자가 동시에 10개 스레드로 PRO 연 구독을 요청하면
  `subscriptions`/`payments`가 각 10행씩 생성됨(순차 재현 테스트는 통과했지만 동시 재현에서만
  드러난 결함)
- `registry.py:create_registry_request()`(#19)와 동일하게 `BEGIN IMMEDIATE`로 확인+생성을
  원자화해 해결. 동시 10/20개 스레드 재현을 각 3회 반복해 정확히 1행만 생성됨을 확인,
  `test_race_conditions.py`에 3번째 시나리오로 상시 회귀화

**[발견] 결제 실패 후 재시도 경로가 실제로는 테스트된 적이 없었음**
- `MockProvider`가 항상 SUCCESS를 반환해 결제 실패를 자연 재현할 수 없었다 — provider를
  일시적으로 실패하도록 교체하는 방식으로 SUBSCRIPTION/OVERAGE_USAGE 둘 다 검증: 실패 시
  entitlement가 생기지 않고(subscription 미생성 / registry_request 미연결), 이어지는 재시도가
  정상 provider로 새 결제를 만들 수 있음을 확인. `test_api_regression.py`에 9검사 추가

**[검증]** `test_api_regression.py` 410 → **419검사**, `test_race_conditions.py` 15 →
**16검사**, 연속 3회 실행 전부 PASS, `auction.db` QA 데이터 잔여 0건. 기존 등기부/초과결제
레이스 시나리오 2종은 이번 변경과 무관해 영향 없음 재확인. `python -m compileall`/
`npx tsc --noEmit`/`npm run lint`(0건)/`npm run build` 전부 통과.

**[감사 범위 확장 — 이상 없음 확인]** "이미 COMPLETED된 결제 재처리"는 재처리 엔드포인트 자체가
없어 확인할 대상이 없음. Subscription IDOR은 사용자용 HTTP 엔드포인트가 없어 노출 표면 없음
(§9번 재확인). `get_entitled_subscription()` 쿼리는 `EXPLAIN QUERY PLAN`으로 인덱스 seek임을
재확인(`idx_subscriptions_user_id`) — 락 보유 시간이 짧아 신규 성능 우려 없음.

**[문서]** `docs/BUGS.md` #20 추가 발견 항목 등록, `docs/TEST_PLAN.md` 8/10번 섹션·검사 총계
갱신.

---

2026-08-09 (Sprint 39 — Registry Credit/Frontend/TOCTOU Backlog 처리, Admin 상태전이 레이스 발견·수정)

Sprint 38이 남긴 Backlog 3건(Registry Credit FAILED 환불 정책, Frontend Duplicate-Action Audit,
storage/database.py TOCTOU 전수 스캔)을 순서대로 처리했다.

**[1. Registry Credit FAILED/REFUND 감사 — 결론 불변, SKIP 유지]**
- `RegistryCreditReason.REFUND`는 여전히 정의만 되어 있고 호출부가 없다. 추가로
  `registry_credits.py:add_credit()`의 `VALID_REASON_TYPES`가 애초에 GRANT/DEDUCT/RESET
  3종만 받고 REFUND는 거부함을 확인 — `docs/backend.md`가 이미 "registry_credits: 조정
  원장(GRANT/DEDUCT/RESET)"로 문서화하고 있어 이는 설계상 의도(REFUND/EVENT는 자동 트리거가
  아직 없는 향후 확장 자리)이지 버그가 아니다. "어떤 FAILED가 환불 대상인가"는 여전히 코드/
  문서 어디에도 정의되지 않은 정책 결정이라 이번에도 임의 구현하지 않고 SKIP 유지
- Registry Credit 동시성(무료 소진 확인->차감)은 #19의 `BEGIN IMMEDIATE`로 이미 보호되고
  `test_race_conditions.py` 시나리오 1(10스레드)로 이미 검증되어 있음을 재확인, 새 결함 없음.
  Admin GRANT/DEDUCT/RESET 경로는 매번 새 원장을 남기는 의도적 설계라 중복 방지가 오히려
  부적절함을 재확인(수정 안 함)

**[2. Frontend Duplicate-Action Audit — 실제 결함 발견·수정]**
- `properties/[id]/page.tsx`의 4개 핸들러(`handleRegistryRequest`/`handleSubscribe`/
  `handlePayOverage`/`handleDownloadRegistry`)가 같은 파일의 `handleToggleFavorite`나
  `FavoriteButton.tsx`가 이미 쓰던 "busy 플래그를 await 이전에 동기적으로 세운다" 패턴을
  따르지 않아, 빠른 연속 클릭 시 재진입 가드가 실제로는 늦게 걸리는 창이 있었다. 4개 핸들러
  전부 동일 패턴으로 통일(상세는 `docs/BUGS.md` #21 참고). 백엔드는 #19/#20으로 이미
  안전하지만(중복 제출돼도 데이터가 깨지지 않음) 불필요한 중복 HTTP 요청 자체를 프론트에서
  막는 게 맞다고 판단해 수정
- Favorite/Search Preset 저장·삭제/Recent Item은 감사 결과 이미 안전: Favorite은 DB UNIQUE +
  IntegrityError 처리, Recent Item은 `ON CONFLICT DO UPDATE` UPSERT — 둘 다 프론트 가드
  없이도 백엔드가 원천 차단. Search Preset 저장은 중복 방지 장치가 전혀 없음을 실측
  재현(동시 5회 요청 -> 5행 생성)했으나, Registry/Subscription과 달리 "중복 저장 불가"가
  프론트 어디에도 전제돼 있지 않아(여러 개의 동일 이름 프리셋을 두는 것과 실수로 중복
  제출한 것을 구분할 근거가 없음) 새 정책 없이 임의로 막지 않고 Backlog로 남김(저심각도 —
  금전/이용권 영향 없음)

**[3. storage/database.py + 인접 도메인 TOCTOU 전수 스캔 — 실제 결함 1건 발견·수정]**
- `storage/database.py` 전체(`upsert_batch`/`claim_next_queue_item`/`enqueue_documents`/
  `mark_queue_*`/`reset_stale_queue`/`init_db`)를 처음부터 끝까지 재검토. `claim_next_queue_item`
  은 이미 조건부 UPDATE+rowcount로 안전, `enqueue_documents`는 UNIQUE+`INSERT OR IGNORE`로
  안전. `upsert_batch`는 SELECT-후-쓰기 패턴이지만 단일 스케줄 크롤러 프로세스(`mvp_scraper.py`,
  Task Scheduler 1일 1회)에서만 호출되어 실질적인 동시 호출 경로가 없음 — 수정하지 않고
  문서화만 함
- **`api/v1/admin.py:update_registry_request_status()`에서 같은 부류의 실제 결함 발견**:
  "현재 status SELECT -> 전이 허용 판단 -> `UPDATE WHERE id=?`"에 현재 status 재확인 조건이
  없어, 같은 신청에 서로 다른 목표 상태로 동시 PATCH가 오면 나중에 커밋되는 쪽이 앞선 결과
  (doc_url/reason)를 조용히 덮어쓸 수 있었다(실측 재현으로 확인). `payments.py`의
  OVERAGE_USAGE와 동일한 조건부 UPDATE+rowcount 패턴으로 수정, rowcount=0이면 409 반환.
  상세는 `docs/BUGS.md` #21

**[검증]** `test_race_conditions.py`에 4번째 시나리오(Admin 상태전이 레이스, 5검사) 신규 —
15 → **22검사**, 연속 5회 실행 전부 PASS(첫 버전은 승자 판정 코드를 409로만 단정했다가 5회
중 1회 flaky 실패 — 진 쪽이 스케줄링에 따라 400으로도 정상 차단될 수 있음을 확인하고 즉시
보정, 이후 5회 연속 PASS). `test_api_regression.py` 419검사 무변동 PASS. `python -m compileall`/
`npx tsc --noEmit`/`npm run lint`(0건)/`npm run build` 전부 통과.

**[문서]** `docs/BUGS.md` #21 신규 등록, `docs/TEST_PLAN.md` 검사 총계 갱신.

---

2026-08-09 (Sprint 40 — 크롤러 File/DB Consistency 감사, API Contract 재확인, Frontend 상태 재확인)

Sprint 39가 남긴 Backlog 3건 중 API Response Contract Audit / Frontend State Consistency
Audit / storage/database.py+크롤러 TOCTOU 확장 스캔을 순서대로 처리했다.

**[1. API Response Contract Audit — 불일치 0건, 문서 신뢰도 확인]**
- `api/constants.py:ErrorCode`(40개) 전량과 `docs/ERROR_CODES.md`를 1:1 대조 — 코드에만
  있고 문서에 없는 값, 문서에만 있고 코드에 없는 값 둘 다 0건. Admin/HTTPException 경로가
  envelope를 쓰지 않는다는 문서의 서술(126~128행)도 실제 코드와 일치 — Sprint 39에서 추가한
  Admin 409 응답도 이 관례를 그대로 따름(별도 수정 불필요)
- 문서 상단 "Last Updated: 2026-08-07 (Sprint 28)"이 실제로는 그 이후에도 계속 갱신되고
  있었음(내용은 최신, 타임스탬프만 stale)을 확인해 정정

**[2. Frontend State Consistency Audit — 새 결함 없음, 아키텍처 확인]**
- `src/app/search/page.tsx`가 Next.js 서버 컴포넌트로 `searchParams`마다 서버에서 새로
  `fetchJSON`하는 구조임을 확인 — 클라이언트 useEffect+fetch 방식이 아니라 페이지 이동마다
  Next.js 라우터가 새 서버 렌더를 트리거하므로, "이전 요청의 응답이 늦게 도착해 최신 상태를
  덮어쓰는" 전형적인 stale-fetch 레이스가 구조적으로 발생할 수 없음
- Favorites(`FavoriteButton.tsx`)/Search Presets(`SearchPresets.tsx`)의 성공/실패 후 상태
  반영은 전부 "서버 응답 확인 후에만 상태 변경"(비관적 갱신, optimistic update 아님) 방식이라
  실패 시 롤백이 필요 없는 구조임을 재확인(Sprint 39에서 이미 확인한 busy-가드와 별개로,
  상태 커밋 시점 자체도 안전)

**[3. storage/database.py + 크롤러 TOCTOU 확장 스캔 — 실제 결함 1건 발견·수정]**
- `mvp_scraper.py`(`upsert_batch`/`enqueue_documents`)와 `doc_worker.py`(단일 워커 루프,
  `claim_next_queue_item` 기반)는 Sprint 39~40 재검토 결과 이미 안전함을 재확인(수정 불필요)
- **`crawler/doc_crawler.py:collect_status()`에서 실제 결함 발견**: `status.html`/
  `status.json`을 최종 경로에 직접 `open().write()`하고 있어, 쓰기 도중 프로세스가 강제
  종료되면(전원 차단/OOM kill 등) 잘려나간 파일이 남을 수 있었다. `doc_exists()`는
  `status.json`의 존재+0바이트 초과만으로 완료를 판정하므로, 손상된 파일이 하나라도 생기면
  그 물건은 영구히 재수집 대상에서 빠졌다. `collect_spec`/`collect_appraisal`(PDF)은
  `wait_for_download()`의 안정화 확인 + `shutil.move()`(같은 파일시스템 내 원자적 rename)
  덕분에 이미 안전했던 것과 대비된다. 임시 파일(`.tmp`) 쓰기 후 `os.replace()`로 원자적
  교체하도록 두 파일 모두 수정 — 상세는 `docs/BUGS.md` #22

**[검증]** 신규 `test_doc_storage_atomicity.py`(Selenium 불필요, 순수 파일시스템 로직만
검증, 12검사) — `get_doc_dir()`/`doc_exists()`(크기 가드, status의 json 우선 판정)와
"tmp 쓰기 후 replace 호출 전에 강제종료" 시뮬레이션으로 목적지가 손상되지 않음을 확인,
연속 3회 PASS. `test_api_regression.py` 419검사 무변동 PASS. `python -m compileall`/
`npx tsc --noEmit`/`npm run lint`(0건)/`npm run build` 전부 통과.

**[문서]** `docs/BUGS.md` #22 신규 등록, `docs/ERROR_CODES.md` 타임스탬프 정정,
`docs/TEST_PLAN.md` 신규 테스트 파일 등록.

---

2026-08-10 (Sprint 41 — 크롤러 TOCTOU 감사 심화 검증: 파일 저장 실패/DB 부분쓰기/워커 재시작
전 경로 실측 재현)

Sprint 40의 크롤러 File/DB Consistency 감사(`collect_status()` 원자적 쓰기 수정)를 더 깊이
이어받아, 10개 구체 시나리오(collect_document 흐름 / 저장 성공-실패와 DB 변경 순서 / 저장 중
예외 시 DB 상태 / 파일 저장·DB 실패 조합 / DB 완료·파일 없음 조합 / 재수집 / 워커 재시작 /
부분·0바이트 파일 / 임시파일·overwrite / 재시도 중복처리)을 하나씩 실측으로 추적했다.

**[검증 1] 파일 저장 성공/실패와 DB 상태 변경 순서**
- `doc_worker.py`는 `collect_document()`가 `result["success"]=True`를 반환했을 때만
  `mark_queue_done()`을 호출한다. `collect_spec`/`collect_appraisal`은 `wait_for_download()`
  로 다운로드 완전 종료를 확인한 뒤 `shutil.move()`(원자적)로 옮긴 다음에야 success=True,
  `collect_status()`는 Sprint 40에서 임시파일+`os.replace()`로 이미 원자화됨 — 파일이
  완전히, 손상 없이 저장된 뒤에만 DB가 "완료"로 갱신되는 순서가 코드 전체에서 일관됨을
  재확인(신규 결함 없음)

**[검증 2] 파일 저장 중 예외 발생 시 DB 상태 — 실측 확인**
- `collect_status()`의 `try/except Exception`(343행)이 저장 중 오류(예: DOM 추출 실패)를
  잡아 `result["success"]=False`(또는 html만 저장됐다면 partial 성공)로 반환하므로,
  `mark_queue_done()`은 절대 호출되지 않고 `mark_queue_failed()`로만 이어짐을 코드로 재확인

**[검증 3] 파일은 저장됐지만 DB가 실패하는 경우 — 실제 재현으로 검증(신규)**
- `mark_queue_done()`은 `document_queue.status='done'` -> `auction.has_*_pdf=1` -> (조건부)
  `document_version_log` INSERT 3단계를 한 트랜잭션으로 묶고 마지막에만 commit한다. 중간
  단계에서 예외가 나면 어떻게 되는지 이론이 아니라 **직접 재현**했다: 존재하지 않는 doc_type을
  넘겨 강제로 `KeyError`를 유발한 결과, `document_queue.status`는 `in_progress`로 그대로
  남고(먼저 실행된 UPDATE까지 전부 rollback됨 — Python sqlite3 모듈이 커밋 안 된 채
  `close()`하면 암묵적으로 rollback하는 동작 덕분), 이어서 정상 doc_type으로 재시도하면
  완전히 성공함을 확인 — "큐는 done인데 auction 플래그는 그대로"인 부분 반영 상태가
  발생하지 않음을 실증했다. `test_doc_storage_atomicity.py`에 회귀 테스트로 고정(3검사)

**[검증 4] DB는 완료됐지만 파일이 없는 경우 — 코드 경로상 도달 불가 확인**
- `mark_queue_done()`은 `result["success"]=True`일 때만 호출되고, 그 값은 파일이 실제로
  완전히 저장된 뒤에만 True가 되므로, "DB는 done인데 파일이 없는" 상태를 만드는 코드 경로
  자체가 없음(외부에서 수동으로 파일을 지우는 경우는 이 감사 범위 밖)

**[검증 5] 동일 문서 재수집/재처리 + 재시도 시 중복 처리**
- 모든 `collect_*()` 함수가 시작 시 `doc_exists()`(존재+0바이트초과)를 확인해 이미 있으면
  즉시 success=True로 스킵 — 재시도가 파일을 다시 다운로드하거나 덮어쓰지 않음. 저장소 전체를
  grep해 `overwrite=True`로 `collect_document()`를 호출하는 곳이 **단 한 곳도 없음**을
  확인 — 실제 운영 경로에서 재수집/덮어쓰기 자체가 발생하지 않는다(아래 기술부채 참고)

**[검증 6] worker 재시작**
- `reset_stale_queue()`(02:00 워커 시작 시 호출)가 `failed`(1일 경과) -> `pending`,
  `in_progress`(10분 경과, 비정상 종료 추정) -> `pending`으로 회수 — Sprint 39~40에서 이미
  확인한 내용을 재확인, 변동 없음

**[검증 7] 부분/0바이트 파일 + 임시 파일/overwrite**
- `doc_exists()`의 `os.path.getsize(path) > 0` 가드로 0바이트 파일은 "미완료"로 정확히
  판정됨을 `test_doc_storage_atomicity.py`로 실측(신규 아님, Sprint 40 확인분 재검증).
  `.tmp` 임시파일은 매 저장 시도마다 같은 이름으로 덮어써지므로 고아 파일이 누적되지 않음

**[기술부채 발견, 수정 안 함]** `mark_queue_done()`의 `document_version_log` INSERT는
`previous_hash != new_hash`일 때만 실행되도록 설계돼 있는데, `previous_hash`는 각
`collect_*()` 함수에서 `doc_exists()`가 이미 True(=이미 존재)일 때만 값을 갖고, 그 경우는
바로 그 앞 줄에서 `overwrite`가 아닌 이상 early return하므로 실제로는 절대 이 지점에
도달하지 못한다 — `overwrite=True` 호출 경로가 없는 한 `document_version_log`는 현재 운영
흐름에서 채워질 수 없는 구조다(버그는 아님 — 향후 "변경 감지 재수집" 기능을 위해 미리
만들어둔 인프라로 보임, KG이니시스 스텁과 같은 성격). P2로 분류, Backlog 기록만 하고 임의로
제거하거나 손대지 않음(사용 여부가 불확실한 코드는 임의 삭제하지 않는다는 원칙).

**[검증]** `test_doc_storage_atomicity.py` 12 → **15검사**(mark_queue_done 부분실패
rollback 시나리오 추가), 연속 3회 PASS. `test_api_regression.py` 419검사, `test_race_
conditions.py` 22검사 전부 무변동 PASS. `python -m compileall`/`npx tsc --noEmit`/
`npm run lint`(0건)/`npm run build` 전부 통과.

**[Frontend 재확인 — 새 결함 없음]** `src/app/properties/recent/page.tsx`(Recent Items
목록)는 순수 읽기 전용 페이지(삭제/추가 액션 없음)라 중복 액션 위험 자체가 없음을 확인.

**[문서]** `docs/TEST_PLAN.md` 검사 총계 갱신. 신규 버그 발견은 없어 `docs/BUGS.md`는
갱신하지 않음(기존 #19~#22가 이번 재검증 대상 전부를 이미 커버).

---

2026-08-10 (Sprint 42 — 크롤러 재시작 체크포인트 원자성 결함 발견·수정, API/Validation Log
감사 완료)

Sprint 41이 남긴 Backlog 4건을 순서대로 처리했다.

**[1. crawler/court_crawler.py + crawler/base_crawler.py TOCTOU — 실제 결함 1건 발견·수정]**
- `base_crawler.py`는 전부 Selenium DOM 파싱 함수(파일/DB 쓰기 없음)라 TOCTOU 대상에서
  제외(순수 함수 확인)
- `court_crawler.py:crawl_court()`가 쓰는 `storage/checkpoint.py:CheckpointManager`에서
  실제 결함 발견: `save()`/`clear()`가 `logs/checkpoint.json`에 직접 `open(path,"w")`로
  써서, 사건 하나 처리할 때마다 반복 호출되는 저장 도중 프로세스가 강제 종료되면 파일 전체가
  손상돼 **이미 저장돼 있던 다른 모든 법원**의 체크포인트까지 함께 사라졌다(재시작 이어받기
  불가). `#22`(collect_status)와 동일한 부류라 같은 원자적 교체(임시파일+`os.replace()`)
  패턴으로 수정. 상세는 `docs/BUGS.md` #23
- `CheckpointManager`의 동시 다중 프로세스 접근(load-modify-write TOCTOU)은 `mvp_scraper.py`
  단일 프로세스·법원 순차 루프 안에서만 호출돼 실제 경로가 없음을 확인, 수정하지 않음(근거만
  기록). `court_crawler.py:log_error()`(`logs/errors.jsonl`)는 append 전용이라 손상돼도
  마지막 한 줄만 영향받고 이전 줄은 안전 — 수정 불필요

**[2. API Response Contract Deep Audit — 실제 응답 body 확인, 불일치 0건]**
- ErrorCode 이름 대조(Sprint 40)를 넘어, 실제 HTTP 호출로 빈 결과 응답 4종(Favorites/
  Recent Items/Search Presets/Payments 목록)의 body를 직접 확인 — 전부
  `{success:true, data:[], error:null, meta:null, message:null}`로 완전히 일관됨
- 404(`GET /item/{없는id}`), 401(인증 없이 등기부 다운로드) 응답도 문서화된 대로
  FastAPI 표준 `{"detail": "..."}` 형태로 일관됨(Admin과 동일 관례). 새 불일치 없음

**[3. Validation Log Concurrency Audit — 실제 동시 쓰기 경로 없음 확인, 코드 변경 없음]**
- `ValidationEngine`을 참조하는 곳을 저장소 전체에서 확인 — `mvp_scraper.py`(단일 프로세스
  순차 호출), `test_db.py`(회귀 대상 아님), `revalidate.py`(**별도 파일**
  `logs/revalidation.jsonl`을 씀, 겹치지 않음) 3곳뿐이라 `logs/validation.jsonl`에 대한
  실제 다중 프로세스 동시 쓰기 경로 자체가 없음을 확인 — 코드는 변경하지 않음(이론적
  가능성만 있는 경우 불필요한 수정을 하지 않는다는 원칙)
- 대신 append-only JSONL 형식이 갖는 안전 특성(쓰기 도중 죽어도 최대 마지막 한 줄만 손상되고
  이전 줄은 전부 안전)을 실측으로 검증 — `test_validation_log_integrity.py` 신규(9검사):
  로그 항목이 실제 validation 결과와 정확히 일치하는지, 마지막 줄이 잘려도 이전 줄이 바이트
  단위로 그대로 남는지 확인
- 부수 발견: `revalidate.py`가 하드코딩된 옛 날짜 CSV(`auction_20260703.csv`)를 참조하는
  1회성 스크립트로, 사실상 오늘 실행하면 파일이 없어 즉시 실패하는 죽은 유틸리티임을 확인
  (git 추적은 되고 있으나 자동 파이프라인에서 호출되지 않음) — P3 기술부채로 기록, 삭제는
  하지 않음(사용 여부가 불확실한 코드는 임의 삭제하지 않는다는 원칙)

**[4. document_version_log / overwrite=True dead branch — 결론 불변]**
- Sprint 41에서 이미 확인한 내용 재확인: `overwrite=True`로 `collect_document()`를 호출하는
  곳이 저장소 전체에 0건이라 `document_version_log` INSERT 로직이 현재 운영 흐름에서
  도달 불가능함을 재확인. P2 기술부채로 계속 기록, 임의 제거하지 않음

**[검증]** `test_checkpoint_atomicity.py` 신규(15검사), `test_validation_log_integrity.py`
신규(9검사) — 둘 다 연속 3회 PASS. `test_api_regression.py` 419검사, `test_race_
conditions.py` 22검사, `test_doc_storage_atomicity.py` 15검사 전부 무변동 PASS.
`python -m compileall`/`npx tsc --noEmit`/`npm run lint`(0건)/`npm run build` 전부 통과.
`logs/` 디렉터리 QA 임시 파일 잔여 0건.

**[문서]** `docs/BUGS.md` #23 신규 등록, `docs/TEST_PLAN.md` 신규 테스트 파일 2종 등록.

---

2026-08-10 (Sprint 43 — Frontend↔API 정렬 계약 불일치 발견·수정, 설정/모델 파일 감사)

`models/auction_item.py`/`normalizer/normalizer.py`/`config/settings.py`/`config/courts.py`
전수 조사와 Frontend ↔ API Response Contract 실측 대조를 진행했다.

**[발견·수정] search 정렬(sort_by) — crawl_date가 프론트 타입/UI/테스트 3곳 모두 누락**
- `api/v1/search.py:SORT_COLUMNS`(8개) vs `src/app/search/types.ts`의 `sort_by` 유니온
  타입(7개) 대조 결과 `crawl_date` 누락 확인 — 타입 파일 자체가 "백엔드 파라미터명과 동일하게
  맞춘다"를 명시하고 있어 그 목적에 어긋나는 불일치였다. `SortBar.tsx` UI도 같은 7개만
  노출해 사용자가 "수집일" 정렬을 선택할 경로가 없었고, 회귀 테스트도 `auction_date` 하나만
  검증하는 약한 테스트였다. 타입 정확성만 정정(`crawl_date` 추가) — UI에 새 정렬 버튼을
  노출할지는 별도 제품 판단이라 손대지 않음. 상세는 `docs/BUGS.md` #24
- `test_api_regression.py`를 8개 화이트리스트 값 전수 검사(200 여부 + 실제 오름차순 정렬
  여부까지)로 강화(16검사 신규, 419→434검사)

**[감사 — 실제 버그 없음, 기술부채만 발견]**
- `models/auction_item.py:has_status_pdf`가 DB 컬럼 리네임(`has_status_doc`, 이전 Sprint에서
  이미 완료) 이후에도 옛 이름 그대로임을 확인. 다만 `storage/database.py:upsert_batch()`의
  INSERT문이 `has_spec_pdf/has_status_doc/has_appraisal_pdf`를 항상 `0,0,0`으로 하드코딩해
  `normalizer.py`가 계산하는 이 3개 필드 자체가 애초에 전혀 읽히지 않음(순수 계산 낭비,
  기능 영향 없음) — 이름 불일치와 죽은 계산 둘 다 P3 기술부채로 기록, 실질 버그 아니라 수정
  안 함
- `config/settings.py:COURTS`(5개 법원, `code="B000210"` 형식) — 저장소 전체에서 import하는
  곳이 0건임을 grep으로 확인, `config/courts.py:ALL_COURTS`(60개, `code`가 법원명과 동일한
  문자열)만 실제로 쓰인다. `select_court()`가 `court.code`를 그대로 `<select>` 값으로 넣는
  경로를 끝까지 추적한 결과 크롤러/DB/doc_worker 전 구간이 일관되게 `ALL_COURTS`식 코드를
  쓰고 있어(실제 운영 중인 `auction.db`가 이를 뒷받침) 기능 결함 없음, `settings.COURTS`는
  단순 죽은 목록(P3). `config/courts.py:get_court_by_code()`도 호출부 0건(P3, 둘 다 삭제는
  안 함 — 사용 여부가 불확실한 코드는 임의 삭제하지 않는다는 원칙)
- `ALL_COURTS` 60개 항목의 code/name 중복·불일치 여부를 스크립트로 전수 확인 — 중복 0건,
  `code != name`인 항목 0건, 법원 지역이 `SIDO_LIST`에서 빠진 것도 0건
- `normalizer/normalizer.py`는 이미 `test_normalizer.py`(29검사)로 충분히 커버되어 있고
  이번 재검토에서 새 결함 없음

**[Frontend↔API 나머지 도메인 확인 — 이상 없음]** `properties/[id]/page.tsx:AuctionItemDetail`
타입이 백엔드 `GET /item/{id}` 응답의 `sido`/`sigungu`/`dong` 3개 필드를 선언하지 않지만
페이지 어디서도 참조하지 않아(grep 확인) 안전한 방향의 불일치(타입 ⊂ 실제 응답) — 런타임
위험 없어 수정 안 함. Registry/Subscription 결제 응답은 `postJSON<unknown>`으로 애초에
타입을 강제하지 않아 안전.

**[검증]** `test_api_regression.py` 434검사, 연속 3회 PASS. `python -m compileall`/
`npx tsc --noEmit`/`npm run lint`(0건)/`npm run build` 전부 통과.

**[문서]** `docs/BUGS.md` #24 신규 등록.

---

2026-08-10 (Sprint 43 계속 — 체크포인트 재개 로직 실측 검증, 잔여 Frontend/Dead Code 재탐색)

Sprint 43 1차 보고 이후 Stop Hook 조건에 따라 계속 진행 — 남은 미검증 영역(체크포인트가
실제로 올바른 위치부터 재개하는지)과 아직 훑지 않은 TypeScript/TSX 죽은 코드를 마저 확인했다.

**[검증 공백 발견·해소] crawler/court_crawler.py의 체크포인트 재개 위치 계산이 실측
검증된 적이 없었음**
- Sprint 42에서 `storage/checkpoint.py`의 원자적 저장(#23)은 검증했지만, "저장된 체크포인트
  값을 가지고 실제로 올바른 인덱스부터 재개하는가"는 별도로 확인한 적이 없었다
- `crawl_court()` 안에 인라인으로만 있던 재개 인덱스 계산 로직을 `resume_start_idx(list_items,
  resume_from)` 순수 함수로 추출(동작은 그대로 유지, Selenium 없이 회귀 테스트 가능해짐).
  신규 `test_crawl_resume.py`(10검사)로 검증: 정상 매칭 시 정확히 "그 다음 항목"부터
  재개하는지, 한 물건에 사건번호가 여럿 묶여 있을 때 어느 번호로 매칭돼도 같은 결과를
  내는지, **체크포인트의 사건이 오늘 목록에 더 이상 없을 때(취하/기각/기일변경) 조용히
  일부를 건너뛰지 않고 0으로 안전하게 폴백하는지**(데이터 누락이 아니라 재크롤링 비효율로만
  귀결됨을 확인)
- 실제 버그는 없었음(기존 로직이 정확했음) — 검증 공백을 메우고 테스트 가능하게 리팩터한 것

**[재탐색 — 새 발견 없음]** `src/` 전체에서 TODO/FIXME/HACK/XXX/@deprecated를 재검색 —
기존에 이미 문서화된 4건(백엔드 미지원 컬럼 표기)뿐, 신규 없음. `src/login/`(App Router
바깥이라 라우팅 자체가 안 되는 stale 중복, `docs/CLAUDE.md`에 이미 기록됨)이 여전히
어디서도 import되지 않음을 재확인 — 기존 기록과 일치, 변동 없음

**[Release Audit — Admin↔Download 체인 설계 재확인]** Admin PATCH 상태전이 테스트(§11)는
항상 존재하지 않는 더미 `doc_url`을 쓰고, 다운로드 성공 테스트(§9)는 항상 DB를 직접 조작해
COMPLETED를 만든다 — 이 둘을 하나로 합친 통합 테스트가 없는 게 아니라, 두 관심사(상태전이
규칙의 정확성 / 파일 서빙의 정확성)가 서로 독립적이라 의도적으로 분리 검증하고 있음을
코드 추적으로 확인(다운로드 로직은 상태가 어떻게 COMPLETED가 됐는지 신경 쓰지 않고,
Admin PATCH는 파일 존재 여부에 관여하지 않음) — 통합 부족이 아니라 정확한 관심사 분리이므로
추가 테스트 불필요

**[검증]** `test_crawl_resume.py` 신규(10검사), 연속 3회 PASS. `test_api_regression.py`
434검사/`test_race_conditions.py` 22검사/`test_doc_storage_atomicity.py` 15검사/
`test_checkpoint_atomicity.py` 15검사/`test_validation_log_integrity.py` 9검사 전부
무변동 PASS. `python -m compileall`/`npx tsc --noEmit`/`npm run lint`(0건)/`npm run build`
전부 통과.

**[문서]** `docs/TEST_PLAN.md` 신규 테스트 파일 등록. 실제 결함이 아니라 검증 공백 해소라
`docs/BUGS.md`는 갱신하지 않음.

---

2026-08-10 (Frontend Sprint 44 — 첫 화면 재정의 / 공통 Layout / 로그인 Redirect)

기준 문서: `docs/FRONTEND_MASTER_SPEC.md`(신규 최상위 기준) + `search/00_SEARCH_MVP.md` v0.2

**[P0 첫 진입 화면]** `src/app/page.tsx`의 무조건 redirect(로그인→`/properties`,
비로그인→`/login`)를 제거하고 `/` 자체를 경매 검색 화면으로 만들었다. 화면 구성은
`src/app/search/SearchScreen.tsx`(신규)로 추출해 `/`와 `/search`가 **복제 없이 공유**한다.
첫 화면 로그인 강제가 사라졌고, 비로그인 상태에서 검색/결과/정렬/페이지 이동이 모두 가능하다.

**[P0 검색 URL]** `SearchForm.handleSearch()` / `SearchPresets.applyPreset()`·`redirectToLogin()`에
하드코딩돼 있던 `/search`를 `usePathname()` 기준으로 바꿨다 — `/`에서 검색하면 `/`에 머문다.
`/search`는 그대로 동작(호환 유지).

**[P0 로그인 Redirect 결함 수정]** `middleware.ts`가 `redirect`에 `pathname`만 실어
쿼리스트링을 버리고 있었다 → 검색 결과에서 물건을 클릭해 로그인하면 목록 내 이전/다음 물건
컨텍스트(`?ids=...&i=...`)가 사라졌다. `pathname + search` 전체를 보존하도록 수정.
같은 결함이 `properties/[id]/page.tsx`의 세션 만료 후 액션 경로 3곳에도 있어
`loginRedirectUrl()`로 통일. Open Redirect 방어(`sanitizeRedirectPath`)는 그대로 유지.
`login/actions.ts`의 기본 복귀 경로를 레거시 `/properties` → `/`로 정정.

**[P0 공통 Layout / Header]** `src/lib/layout.ts`(신규)에 `CONTAINER`(=`max-w-[1320px] mx-auto`)를
단일 정의하고 `/`·`/search`·`/favorites`·`/properties/recent`·`/properties/[id]`에 적용.
`src/components/SiteHeader.tsx`(신규)는 기존 `PrimaryNav`+`LogoutButton`을 재사용하며
배경은 풀블리드, 내용은 본문과 동일 컨테이너 정렬. 비로그인엔 로그인 링크, 로그인엔
이메일+로그아웃을 노출해 `/properties`에만 있던 로그아웃 경로 문제를 해소했다.
`PrimaryNav`의 검색 링크를 `/search` → `/`로 통일. 로그아웃 후 이동도 `/login` → `/`.

**[P1 반응형]** 검색 Form(주소 블록 + 아코디언 묶음)과 결과 목록, `/favorites`,
`/properties/recent`를 모바일 1열 / 태블릿(md 768px) 2열 / 데스크톱(xl 1280px) 3열로 적용.
상세는 xl 2열. 레이아웃 클래스만 변경했고 필드 구성·state·`buildSearchQuery()` 결과는 무변경.
`/login` 폼은 화면 전체 폭으로 늘어나던 것을 `max-w-md` 가독 폭으로 제한.

**[부수 결함 수정]** `SearchPresets`의 목록 조회가 401/403을 "불러오기 실패"(빨간 에러)로
표시하고 있었다 — 만료 토큰으로 `getSession()`이 세션을 돌려주는 경우 비로그인 사용자에게
고칠 수 없는 실패가 보인다. 저장/삭제 경로와 동일하게 비로그인 상태로 되돌리도록 통일.

**[검증]** `npx tsc --noEmit` / `npm run lint`(0건) / `npm run build` 전부 통과.
실제 브라우저(localhost:3000)에서 첫 화면 렌더·검색 실행 시 `/` 유지·정렬·상세 진입·
비로그인 307 게이트(쿼리스트링 보존)·로그인 페이지 hidden input 값까지 확인.

**[미해결/SKIP]** 로그인 사용자의 Supabase JWT를 FastAPI가 401로 거부하는 환경 문제
(`SUPABASE_JWT_SECRET` 불일치 추정) — 즐겨찾기/최근조회/검색조건 저장이 로그인 상태에서도
동작하지 않는다. Secret 변경은 승인 필요라 SKIP, 보고서에만 기록.

---

2026-08-10 (Frontend Sprint 45 — 계약 테스트 도입 / Backlog 조사·정리)

**[Frontend 자동 테스트 신규]** `tests/frontend-contract.test.mjs` + `npm run test:frontend`.
프로젝트에 프론트엔드 자동 테스트가 **0건**이던 공백을 메웠다(Sprint 44 최대 리스크 항목).

- 러너는 **Node 내장 `node:test`** — 새 라이브러리 설치 없음(`docs/CLAUDE.md` 승인 규칙 준수).
  기존 Python 스크립트 방식과 중복되는 러너를 만들지 않으려 npm script 하나만 추가.
- **HTTP 블랙박스** 20검사: `/` 무redirect / 첫 화면이 로그인 폼 아님 / 비로그인 목록 노출 /
  검색 실행의 pathname 유지 / `/search` 호환 / 결과→상세 링크 형태 / 비로그인 상세 307 게이트 /
  **redirect query string 보존** / 로그인 폼 복귀 구조 / 공개 라우트 무차단 / 정렬·페이지
  파라미터 비로그인 처리 / `/favorites` 서버 응답에 개인 데이터 미노출 / 1320px 컨테이너 / 반응형
- **DB 건수에 의존하지 않게** 설계 — `test_search.py`가 기대 건수 노후화로 3건 실패하는 것과
  같은 함정을 반복하지 않도록 구조만 단언한다
- **회귀 검출력 검증**: `middleware.ts`를 결함 상태(pathname만 전달)로 되돌리는 mutation
  테스트를 실행해 해당 검사가 정확한 메시지로 실패하는 것을 확인한 뒤 원복

**[상세 화면 네비게이션 막다른 길 해소]** `/properties/[id]`에는 공통 Header가 없어
검색/관심물건/최근 본 물건으로 이동할 방법이 뒤로가기뿐이었고 로그아웃 경로도 없었다.
기존 상세 전용 바(뒤로가기·즐겨찾기·무료잔여)는 그대로 두고 `SiteHeader`를 위에 얹는
가산 방식으로 해결. 로딩/실패 상태에서도 Header를 유지해 "빠져나갈 길이 없는 화면"을 없앴다.

**[Backlog 조사 — 코드 근거로 결론]**
- `middleware`의 공개 요청 `getUser()`: 실측 **2~3ms**(비로그인 `/` 20회, 전체 median 84ms).
  세션 쿠키가 없으면 Supabase 왕복 없이 즉시 반환된다 — **Sprint 44의 성능 우려는 과장이었음**을
  측정으로 정정
- 디자인 토큰: 색상 고유 35종이나 gray+blue 단일 primary+의미색의 **일관된 단일 팔레트**라
  현 시점 도입 불필요(경쟁 팔레트 없음). 브랜드 변경/다크모드 결정 시 재검토
- `/properties` 레거시: 코드상 **inbound 링크 0건**(Sprint 44에서 `/` redirect와 PrimaryNav
  링크가 사라져 완전 고아 상태). 삭제는 정책 결정이라 SKIP, 상태만 확정 기록
- `src/login/`: 참조 **0건** 재확인. 삭제는 프로젝트 규칙상 SKIP
- `formatPrice`: 정의 3곳(`lib/format.ts` 공용 + `properties/page.tsx` + `properties/[id]`).
  통일은 "억 고정 vs 만/억 단계" 표기 기준 UX 결정이 선행돼야 해 SKIP 유지

**[JWT 401 원인 확정 — Sprint 44 추정 → 확정]** `docs/BUGS.md` #27 신규.
`{SUPABASE_URL}/auth/v1/.well-known/jwks.json`이 **200 + `kty=EC`/`alg=ES256`** 을 반환한다 —
Supabase 프로젝트가 비대칭 서명으로 전환됐는데 백엔드 검증 3곳(`api/auth.py:20-23`,
`api/v1/item.py:47-48`, `api/v1/search.py:145-146`)은 `algorithms=["HS256"]` + 공유 시크릿
고정이다. ES256 토큰은 원리상 검증 불가 → 인증 필수 라우트 401, 선택적 인증 라우트는 예외를
삼켜 `is_favorited`가 항상 false(검색 결과 하트가 전부 빈 하트로 보이던 증상의 정체).
**Secret 교체로 해결되지 않으며 검증 코드를 고쳐야 한다**(`python-jose`가 ES256/JWK 지원,
신규 라이브러리 불필요). 함정: `NEXT_PUBLIC_SUPABASE_ANON_KEY`는 여전히 `alg=HS256`이라
anon 키만 보면 오진하기 쉽다. 백엔드 수정은 이번 Sprint 범위 밖이라 원인 확정까지만 수행.

**[검증]** `npx tsc --noEmit` / `npm run lint`(0건) / `npm run build` / `npm run test:frontend`
(20/20) 전부 통과. 브라우저에서 상세 화면 공통 Header 노출 확인.

**[문서]** `docs/TEST_PLAN.md`에 Frontend 계약 테스트 절 신설(1-A/1-B 분리),
`docs/FRONTEND_MASTER_SPEC.md` §16 갱신, `docs/BUGS.md` #27.

2026-08-10 (Sprint 45 후속 — Empty State / 인증 경계 통일)

**[Empty State 개선]** 검색 결과 0건일 때 회색 한 줄("검색 결과가 없습니다")만 덩그러니
떠 있어, 조건을 잘못 넣은 사용자가 무엇을 해야 하는지도 어떻게 되돌리는지도 알 수 없었다.
원인 안내("검색조건을 줄이거나 지역·가격 범위를 넓혀보세요")와 복구 동선
("조건 없이 전체 물건 보기")을 추가했다. 복구 링크는 **현재 화면의 경로**를 가리킨다 —
`/`에서는 `/`로, `/search`에서는 `/search`로(§8.2의 pathname 유지 규칙과 동일). 이를 위해
`SearchScreen`/`ResultList`에 `basePath` prop을 추가했고, `/`와 `/search`가 각자 자기 경로를 넘긴다.

**[0건일 때 페이지네이션 숨김]** 결과가 0건인데도 페이지 크기(20/30/50/100)와 이전/다음
컨트롤이 남아 Empty State 안내를 가리고 있었다. `data.total > 0`일 때만 렌더한다.

**[인증 경계 통일]** `/properties/recent`는 middleware가 서버에서 307로 막는데
`/favorites`는 middleware 대상이 아니라 200을 준 뒤 클라이언트에서 튕겼다 — 같은 개인화
화면인데 게이트 방식이 갈려 있었고, 빈 화면이 잠깐 그려졌다가 이동하는 깜빡임도 있었다.
`middleware.ts`의 보호 경로를 `PROTECTED_PREFIXES = ['/properties', '/favorites']`로 통일해
둘 다 서버 게이트로 맞췄다(각 페이지의 클라이언트 체크는 토큰 만료 대응용 이중 방어로 유지).

**[테스트]** 계약 테스트 20 → **24검사**(Empty State 4건 추가, 개인화 라우트 검사를
서버 게이트 기준으로 강화). `npx tsc --noEmit`/`npm run lint`(0건)/`npm run build`/
`npm run test:frontend`(24/24) 전부 통과. 브라우저에서 Empty State와 `/favorites` 307 확인.

---

2026-08-10 (Sprint 46 — JWT 인증 체인 복구 / Release Blocker 해소)

**[Release Blocker 해소] ES256(JWKS) 검증 도입** — `docs/BUGS.md` #27.
Supabase가 비대칭 서명(ES256)으로 전환됐는데 백엔드 3곳이 `algorithms=["HS256"]` +
공유 시크릿 고정이라, 로그인 사용자의 즐겨찾기/최근조회/검색조건 저장/등기부/결제가 전부
401이었고 검색 결과의 `is_favorited`도 항상 false였다.

- `api/auth.py`에 `decode_supabase_jwt()` 신설: 헤더 `alg`에 따라 ES256(JWKS 공개키) /
  HS256(레거시) 경로 선택, **알고리즘 화이트리스트 고정**(`alg:"none"` 위조 차단),
  **kid 기반 키 선택 + JWKS 캐시**(TTL 600초, 미상 kid 시 재조회로 키 회전 대응,
  최소 재조회 간격 30초), JWKS 실패 시 기존 캐시 보존
- `api/v1/item.py`/`api/v1/search.py`의 중복 `jwt.decode` 3중 구현을 공용 함수로 통합
- **예외 정규화**: jose가 `JWTError`의 형제 예외(`JWSError` 등)를 던지는 경로가 있어,
  선택적 인증 라우트(검색/상세)가 이상한 토큰 하나로 500이 될 수 있었다 — 테스트 작성 중
  발견해 `JWTError`로 정규화
- 실패 사유 로깅 추가(토큰/시크릿은 로그에 남기지 않음)
- **Secret은 발급/변경/조회하지 않았고 `.env`도 수정하지 않았다.** JWKS URL은 `.env.local`의
  `NEXT_PUBLIC_SUPABASE_URL`을 읽기만 한다

**[테스트 신규] `test_auth_jwt.py` (23검사)** — Supabase 개인키 없이 실제 코드 경로를 검증하기
위해, 테스트가 자체 EC P-256 키쌍을 만들어 공개키를 JWKS 캐시에 주입하고 개인키로 서명한다
(네트워크 무의존). ES256 성공/만료/위조서명/미상 kid/kid 누락, `alg:"none"`·알고리즘 혼동
(공개키를 HMAC 키로 사용)·미상 alg 거부, HS256 레거시 성공/실패, 엔드포인트 레벨 인증 필수
200/401 및 선택적 인증 200 유지까지 포함.

**[결정적 검증]** 실제 Supabase ES256 토큰으로 구/신 코드 서버를 동시 비교:
구 코드 401/401/401 → 신 코드 **200/200/200**(search-presets/recent-items/favorites).

**[정정]** 진행 중 `SiteHeader`를 `getSession()` → `getUser()`로 바꿨다가 되돌렸다.
"헤더는 로그인인데 미들웨어는 로그아웃"이라고 판단했으나, 로그 재확인 결과 미들웨어는 200으로
통과했고 리다이렉트는 API 401을 받은 클라이언트가 한 것이었다 — 그 결함은 존재하지 않았다.
middleware가 매 요청 `getUser()`로 쿠키를 갱신한 뒤 렌더되므로 `getSession()`으로 충분하며,
헤더에서 다시 `getUser()`를 부르면 로그인 사용자의 매 페이지 로드에 왕복만 늘어난다.

**[검증]** `test_auth_jwt.py` 23/23, `test_api_regression.py` 434검사 ALL PASSED,
`test_state_machines.py`/`test_race_conditions.py`/`test_subscription_policy.py`/
`test_registry_credits.py`/`test_schema_hygiene.py` 전부 PASS,
`npm run test:frontend` 24/24, `npx tsc --noEmit`/`npm run lint`(0건)/`npm run build` 통과.

**[운영 주의]** `--reload`가 걸린 기존 프로세스가 변경을 확실히 반영하지 못할 수 있다.
**API 서버를 완전히 재기동해야** 적용된다(이번에도 낡은 프로세스 때문에 브라우저에서
401이 계속 보였다).

---

2026-08-10 (Sprint 47 — 운영 검증 / 테스트 복구 / 잔여 부채)

**[운영 검증] API 서버 재기동 후 인증 체인 실동작 확인**
Sprint 46에서 고친 코드가 낡은 프로세스 때문에 브라우저에 반영되지 않던 상태를 해소했다.
netstat이 가리키던 PID는 이미 사라진 reloader 부모였고 실제 소켓은 워커가 쥐고 있었다.
워커를 종료하고 최신 코드로 재기동한 뒤, 실제 Supabase ES256 토큰으로
`search-presets`/`recent-items`/`favorites` 전부 **200**을 확인했다.
브라우저에서도 상세 진입 → `record_view()` 기록 → 최근 본 물건 목록 표시까지
**전 스택 인증 체인이 실동작**함을 확인했다(브라우저 → Next.js → FastAPI → JWT 검증 → DB).

**[테스트 복구] selenium 의존성 분리로 회귀 테스트 2건 되살림**
`crawler/doc_crawler.py`와 `crawler/court_crawler.py`는 최상단에서 selenium을 import하는데,
순수 계산 함수만 쓰는 테스트까지 selenium 설치를 강요받아 실행조차 못 하고 있었다.
- `crawler/doc_paths.py` 신규 — 문서 저장 경로 규칙(`get_doc_dir`/`doc_exists`/`DOCUMENT_ROOT`)
- `crawler/resume.py` 신규 — 체크포인트 재개 위치 계산(`resume_start_idx`)
- 원본 모듈은 두 이름을 **재노출**하므로 `doc_worker.py` 등 기존 호출부는 무변경
- **우회가 아니라 불필요한 의존성을 실제로 끊은 것** — 검증 대상은 동일한 그 함수다
- `test_doc_storage_atomicity.py`(15검사), `test_crawl_resume.py`(10검사) 실행 복구

**[테스트 재설계] `test_search.py` — 고정 row count 제거**
`address_detail="서울" -> total == 284` 같은 절대 건수는 크롤링으로 매일 드리프트해,
두 번 연속 "실패 3건"이 났지만 **전부 기대값 노후화였고 실제 회귀는 하나도 없었다**.
건수 대신 아래를 검증하도록 재설계(13건 -> **25검사**):
- 행 단위 검증: 반환된 모든 행이 그 의도에 맞는 컬럼 값을 갖는가
- **컬럼 매핑 고정**: `address_detail="오금동"` 결과 == `dong="오금동"` 결과 (0건이어도 성립)
- 표기 동치("서울"=="서울시"=="서울특별시"), 분해 동치, 포함 관계, 응답 계약/필수 필드
- **mutation 테스트로 검출력 확인**: DONG 의도를 `sigungu` 컬럼에 걸도록 바꾸자 정확히
  "컬럼 매핑 고정" 검사가 실패했다. (1차 재설계안은 0건일 때 조용히 통과해 mutation을
  놓쳤고, 그래서 컬럼 매핑 동치 검사를 추가했다)
- 부수 수정: 출력 문자열의 em-dash가 cp949 콘솔에서 UnicodeEncodeError를 일으켜
  테스트가 중간에 죽던 문제(과거 `test_normalizer.py`와 동일한 함정)를 ASCII로 교체

**[결함 수정] `storage/checkpoint.py` 원자적 쓰기 복구 — `docs/BUGS.md` #28**
`save()`/`clear()`가 목적지에 직접 쓰고 있었다. `docs/BUGS.md` #23(Sprint 42)이 고쳤다고
기록한 수정이 **코드에서 사라진 상태**였고, `storage/`가 통째로 gitignore라 이력 추적도
불가능했다. `_write_atomic()`(tmp -> fsync -> `os.replace`)으로 복구.
체크포인트 저장 중 크래시 시 크롤러가 전체 진행 상황을 잃는 실질적 결함이었다.

**[검증]** Python 회귀 **15/15 전부 PASS**(이번 세션 최초):
auth_jwt(23) / api_regression(434) / search(25) / doc_storage_atomicity(15) /
state_machines / race_conditions / subscription_policy / registry_credits /
auction_identity / schema_hygiene / intent_analyzer / normalizer /
checkpoint_atomicity(15) / validation_log_integrity / crawl_resume(10).
`npm run test:frontend` 24/24, `npx tsc --noEmit`/`npm run lint`(0건)/`npm run build` 통과.

**[조사 결과 — 버그 아님]** `crawler`의 `get_doc_dir(court_code, ...)`와
`api/v1/documents.py`의 `get_doc_dir(court_name, ...)`가 서로 다른 인자명을 쓰지만,
DB 실측 결과 `document_queue.court_code`/`auction_case.court_code`/`auction_item.court_name`이
**전부 한글 법원명**을 담고 있어 경로가 일치한다. 인자 이름만 오해를 부르는 상태이며
문서 서빙에는 문제가 없다.

**[접근성 감사 — Sprint 47 추가]** 실제 DOM 검사로 4건 발견·수정.
- **`<h1>` 부재** — Sprint 44에서 공통 Header를 만들며 각 페이지의 `<h1>`을 헤더로 옮기다가
  `<span>`으로 바꿔버려 문서에 h1이 하나도 없었다(내가 만든 회귀). 시각적 크기는 그대로 두고
  시맨틱만 복구
- **`<main>` / `<nav>` 랜드마크 0개** — `SearchScreen` 본문을 `<main>`으로,
  `PrimaryNav`를 `<nav aria-label="주요 메뉴">`로 변경
- **라벨 없는 select 2개** — 시/도·시/군/구(+법원)에 `aria-label` 추가. 첫 option의
  placeholder 텍스트는 접근 가능한 이름이 아니라 스크린리더가 아무것도 읽지 못했다
- 계약 테스트에 접근성 4검사 추가(24 -> **28검사**)해 같은 회귀를 고정

**[최종 게이트]** Python 회귀 **15/15 PASS**, 프론트 계약 **28/28 PASS**,
`npx tsc --noEmit` / `npm run lint`(0건) / `npm run build` 전부 통과.
(빌드가 한 번 `EPERM: unlink .next/static/...`으로 실패했으나 재실행 시 정상 —
dev 서버/OneDrive의 일시적 파일 잠금이며 코드 문제가 아니다.)

---

2026-08-10 (Sprint 48 — 잔여 Backlog 조사 / 안전한 정리)

**[조사 확정 — 코드 변경 없음]**
- **`/properties` 레거시**: 도달 가능한 inbound 링크 **0건** 확정(주석 2건, 죽은 코드
  `src/login/action.ts` 1건, middleware의 보호 prefix 1건이 전부 — 전부 진입 경로가 아님).
  직접 URL 입력 외에는 도달 불가. 삭제/redirect는 정책 결정이라 SKIP
- **`src/login/`**: import/route/link/dynamic reference **0건** 재확인(파일 2개).
  삭제는 프로젝트 규칙상 SKIP
- **table view**: 관련 구현/TODO **0건**. 미착수 확정
- **마이페이지/Admin/권리분석**: `src/app/`에 해당 라우트 없음. `rightsAnalysis.ts`는
  `REGISTRY: available:false` 하드코딩 스텁 상태 그대로(등기부 파싱 테이블 자체가 없음)

**[문서 정정] CORS 기록이 stale이었다** — `docs/search-engine.md`가
"전체 허용(`allow_origins=["*"]`)"으로만 적고 있었으나, 실제 `api_server.py`는
**`CORS_ALLOW_ORIGINS` 환경변수를 콤마 구분으로 읽어 그 목록만 허용**하고 미설정일 때만
하위호환으로 `["*"]`가 된다. 즉 "코드가 전체 허용으로 고정"이 아니라 "운영 값 미설정"이다.
`.env` 설정은 승인 사항이라 값 자체는 건드리지 않고 기록만 정정했다.

**[중복 제거 — 동작 무변경] `formatPrice`**
`properties/page.tsx`(레거시)와 `properties/[id]/page.tsx`(상세)에 **글자 단위로 동일한**
`(price/1e8).toFixed(1) + '억'` 구현이 각각 복사돼 있었다. `src/lib/format.ts`에
`formatPriceEok()`로 추출하고 두 화면이 이를 쓰도록 통합했다 — **표시되는 숫자는 하나도
바뀌지 않는다**. 공용 `formatPrice()`(0 -> '-', 만/억 단계)와 표기 기준이 다른 것은 그대로
남으며, 어느 쪽으로 통일할지는 화면 숫자가 바뀌는 UX 결정이라 SKIP(함수 주석에 명시).

**[조사 확정 — rename SKIP] `court_code` / `court_name`**
DB 실측 결과 `ALL_COURTS[].code == ALL_COURTS[].name`이고
`document_queue.court_code`/`auction_case.court_code`/`auction_item.court_name`이 **전부 한글
법원명**을 담는다. 따라서 크롤러(`documents/<법원명>/`)와 API(`documents/<법원명>/`) 경로는
일치하며 문서 서빙에 불일치가 없다(버그 아님). 인자명 rename은 **하지 않았다** — DB 컬럼명이
`court_code`인 이상 내부 인자만 바꾸면 호출부(`item["court_code"]`)와 어긋나 혼란이 옮겨갈
뿐이고, 컬럼명 변경은 스키마 변경이라 승인이 필요하다. 대신 양쪽 함수에 근거를 주석으로 남겼다.

**[결함 수정] 로그인 redirect 주석 stale**
`login/actions.ts`가 "기본값(`/properties`)으로 되돌린다"고 적고 있었으나 실제
`DEFAULT_REDIRECT`는 Sprint 44에 `/`로 바뀌었다(내가 만든 불일치). 주석 정정.

**[테스트 추가] Open Redirect 방어 회귀**
자격증명 없이 검증 가능한 지점을 찾아 계약 테스트에 추가했다 — `//evil.example.com`,
`/\evil.example.com`, `https://evil.example.com`을 `redirect`로 넘겨도 로그인 페이지가
200이며 **외부 origin으로 튕기지 않는지** 확인한다(28 -> **29검사**).
제출 시점의 `sanitizeRedirectPath()` 동작 자체는 비밀번호 입력이 필요해 여전히 범위 밖.

**[기록] `storage/` git 미추적 소스 전수 특정**
`git ls-files storage/` 결과 **0건**. 실제로는 load-bearing 소스 **22개**가 있다
(`database.py`/`checkpoint.py`/`migrate_v4_1.py`/`migrate_doc_collect.py`/`__init__.py` +
migrations `.sql` 16개 + `run_migrations.py`). Sprint 47의 checkpoint 원자성 유실(BUGS #28)이
바로 이 구조 때문에 이력 없이 발생했다. 추적 정책 변경은 승인 사항이라 SKIP하고 범위만 확정 기록.

---

2026-08-11 (Sprint 49) — 실제 사용자 흐름 완성 + 실행 검증

**목표**: 문서가 아니라 실제 동작으로 `/ → 검색 → 결과 → 정렬/페이지 → 물건 클릭 → 로그인 →
원래 상세 복귀 → 상세 → 즐겨찾기/최근조회/검색조건 저장 → 로그아웃`이 끝까지 되는지 증명.
API 서버 + `npm run dev`를 띄우고 실제 브라우저와 코드 양쪽으로 확인했다.

**발견·수정한 결함 4건** (전부 실제 브라우저에서 재현 후 수정, `docs/BUGS.md` #29~#32)

1. **#29 정렬 화살표가 데이터와 반대** — `SortBar`의 `sort_order` 기본값이 `'asc'`인데
   백엔드 기본값은 `'desc'`다. 첫 화면이 ↑라고 표시하면서 실제로는 내림차순이었고,
   "매각기일"을 눌러도 이미 적용 중인 정렬과 같은 값이 나가 **아무 변화가 없었다**.
   → 기본값을 `'desc'`로 통일.
2. **#30 정렬 변경 시 페이지가 유지됨** — 3페이지에서 "감정가 ↓"를 누르면 감정가가 가장 높은
   물건이 아니라 **가장 낮은 물건 1건**(3/3페이지)이 나왔다. `Pagination.changeSize()`와
   `SearchForm.handleSearch()`는 이미 1페이지로 되돌리고 있었고 SortBar만 예외였다.
   → 정렬 변경 시 `page=1`.
3. **#31 페이지 범위 초과를 "결과 없음"으로 안내** — 조건에 맞는 물건이 6건 있는데
   `?page=9`에서 "검색조건을 줄이세요"라는 정반대 처방을 하고, 유일한 복구 링크는
   검색조건까지 버렸다(북마크·공유 URL에서 실제로 도달 — 기본 필터가 `auction_date >= 오늘`이라
   결과가 매일 줄어든다). → `ResultList`가 두 상태를 구분하고, `SearchScreen`이 page만 제거한
   `firstPageHref`로 **검색조건 유지 1페이지 복귀** 동선을 제공.
4. **#32 목록 컨텍스트 없는 상세에 죽은 이전/다음 바** — `/favorites`·`/properties/recent`의
   카드는 `/properties/{id}`로만 링크하는데, `''.split(',')`가 `['']`를 주고 `Number('')`가 0이라
   `ids` 없이도 "1 / 1" 바가 양쪽 비활성으로 떠 있었다(Master Spec §9.2 위반).
   → 계산을 순수 함수 `navContext.ts:resolveNavContext()`로 분리(동작 무변경)하고 빈 세그먼트
   필터 + `i` 부재 명시 구분.

**발견했으나 고치지 않은 결함 1건 — 승인/결정 필요 (`docs/BUGS.md` #33)**

검색 UI의 물건종류 **69개 중 60개가 항상 0건**이다. UI 트리는 Tank Auction HTML을 전수 복사한
어휘이고 DB는 크롤러가 수집한 원문 18종이라 어휘가 다르다. 가장 흔한 `다세대`(246건),
`근린시설`(164건), `상가,오피스텔,근린시설`(202건), `오피스텔`(102건)은 **이름으로 아예 선택할
수 없다**(이름으로 도달 불가한 행 745/1,870 ≈ 40%). 해결책 3가지(UI 어휘 교체 / 백엔드 동의어
매핑 / 크롤러 정규화)가 전부 확정된 결정을 뒤집고, 복합값(`상가,오피스텔,근린시설`)은 1:1
매핑으로 풀리지 않아 제품 판단이 필요하다 → 측정치와 함께 기록만 하고 임의 수정하지 않음.

**정정한 stale 주석 1건** — `SearchForm.tsx`의 "물건종류는 단일 선택시에만 API 연동"은 stale.
실측으로 다중 선택 OR 검색이 정상 동작함을 확인(임야 8 + 다세대 11 → "임야,다세대" 19).

**테스트 강화** — 프론트 계약 테스트 **29 → 50 검사**
(`tests/frontend-contract.test.mjs` 42 + `tests/nav-context.test.mjs` 8 신규).
정렬이 실제 순서를 바꾸는지 / 페이지가 실제로 다른 물건을 주는지 / 지역 조건이 결과 카드의
실제 주소에 반영되는지까지 **응답 body를 검증**한다. `navContext`는 변이 테스트로 검출력 확인.

**브라우저 실측 결과** — 검색조건 입력→결과(6건, 주소 전부 일치) / 정렬(최저입찰가 ↓ 실제
내림차순) / 페이지 이동(3/3페이지) / 물건 클릭→상세(`?ids=&i=` 컨텍스트 유지, 1/6) /
이전·다음 물건 이동(2/6) / 즐겨찾기 토글(서버 반영 후 `/favorites`·검색 결과 하트에 반영) /
최근조회 자동 기록(`/properties/recent` 최상단) / 검색조건 저장·불러오기·삭제(조건 복원 확인) /
비로그인 상세 요청 → `/login`으로 이동하며 `?ids=&i=`까지 보존(쿠키 없는 실제 브라우저 요청).

**품질 게이트** — Python 회귀 15/15 전부 PASS, 프론트 50/50, Type Check / Lint 0 / Build 통과.
QA 데이터 잔여 0건(테스트로 만든 즐겨찾기 1건·검색조건 1건 모두 UI 경로로 원복).

---

2026-08-11 (Sprint 50) — Release Readiness + 남은 Frontend/Architecture Backlog

**1. Next.js 16 `middleware` → `proxy` 규약 전환 (완료)**

Sprint 49가 기술부채로 남긴 빌드 경고
(`The "middleware" file convention is deprecated. Please use "proxy" instead.`)를 해소했다.

- `src/middleware.ts` → **`src/proxy.ts`**, `export async function middleware` →
  `export async function proxy` (Next 엔트리 템플릿이 proxy 파일에서는 `mod.proxy`를 먼저 찾는다)
- **인증 로직은 한 줄도 바뀌지 않았다** — `git show HEAD:src/middleware.ts`와 주석/공백을
  정규화해 비교한 결과 함수명을 제외하고 **문자 단위로 동일**함을 확인했다
- `export const config = { matcher }`는 그대로 동작한다(Next의 `isMiddlewareFile()`이 두 규약을
  동일 취급). 정적 자산 제외 동작도 실측 확인
- 유일한 실질 변화는 Next가 강제하는 **런타임(Edge → Node.js)**이다. `@supabase/ssr`의
  `createServerClient`·`NextResponse`·`request.cookies`는 양쪽에서 동일하게 동작하고,
  Node는 Edge의 상위 집합이라 기능이 줄어드는 방향이 아니다
- 두 파일이 동시에 있으면 Next가 빌드를 실패시키므로 `src/middleware.ts`는 삭제했다

**검증**: 빌드 경고 소멸(`grep -i deprecat` 0건). 쿠키 미전송 실제 브라우저 요청으로
비로그인 상세 게이트·`?ids=&i=` 보존·개인화 라우트 차단·공개 라우트 무차단 9항목 전부 통과.
로그인 세션 유지 확인. 계약 테스트에 규약 회귀 3검사 추가(50 → 53). 변이 테스트로 검출력 확인
(`pathname + search` → `pathname`으로 되돌리면 2검사 실패).

**2. BUGS #33(물건종류 어휘) 재검증 — 임의 수정 없이 측정·해결안 정리만**

상태 변동 없음. **사용자가 실제로 보는 화면 기준으로는 더 나쁘다**는 것을 새로 확인했다.

- 기본 검색 화면(진행 중 41행)에서 **69개 중 62개(90%)가 항상 0건**
- 이름으로 도달 불가한 행: 전체 745/1,870(39.8%), **진행 중 26/41(63.4%)**
- **고쳐야 할 이름은 6개뿐**임을 특정(다세대주택/근린생활시설/오피스텔(주거)/오피스텔(상업)/
  근린상가/자동차관련). 남은 진짜 쟁점은 복합값 `상가,오피스텔,근린시설`(202행)을 어느 항목에
  노출할지 하나뿐이다
- 해결안 3가지의 변경 지점·비용·리스크·되돌리기 난이도를 표로 정리(②백엔드 동의어 매핑이
  가장 국소적). **Release Blocking 아님 / 출시 전 결정 필요** 등급으로 판정
- 승인 규칙(제품 결정 + 기존 API 계약 변경)에 해당해 **SKIP**

**3. 레거시 `/properties` 실패 모드 확정 (BUGS #34 신규)**

기존 문서는 "엉뚱한 물건이 열리거나 404가 난다"로 애매하게 적혀 있었다. 실측 결과
**404는 나지 않고 항상 엉뚱한 물건이 열린다**(조용한 오답). Supabase 시드 5행의 id 1~5가
FastAPI `auction_item`에서 전부 200이라, 예를 들어 "강남구 역삼동 아파트"를 클릭하면
"관악구 난곡로 2층202호"가 열린다. inbound 링크 0건(고아 라우트)이라 사용자 도달 경로는
없어 **Release Blocking은 아니며**, 화면 처리 방향이 미결정이라 수정하지 않았다.

**4. 문서 stale 정정 (실제 코드와 불일치)**

- `FRONTEND_MASTER_SPEC.md` §5.1이 "공통 Header 컴포넌트: **존재하지 않는다**"로 남아 있었다 —
  Sprint 44에 `SiteHeader.tsx`를 만들었는데 이 절만 갱신되지 않았고, **§11.2의 "중복 컴포넌트를
  만들지 않는다"와 정면으로 충돌하는 위험한 기록**이었다. AS-IS 스냅숏임을 명시하고 현재 상태
  표를 덧붙였다. §11.2의 "공통 Header는 새로 만들되(현재 존재하지 않음)"도 정정
- §11.1 컴포넌트 인벤토리: `src/components/` 5개 → **6개**(`SiteHeader` 누락), 라우트 지역
  컴포넌트에 `SearchScreen`·`navContext.ts` 추가, 공용 유틸에 `src/lib/layout.ts` 추가
- `docs/frontend.md` "현재 화면 구성"의 첫 줄이 `/`가 여전히 redirect한다고 기술 —
  같은 문서 아래 "페이지 구조" 표와 **서로 모순**이었다. 정정
- 계약 테스트 검사 수 표기(20 → 53), `middleware.ts` → `proxy.ts` 참조 정리
  (`CLAUDE.md`/`API_KEY_CHECKLIST.md`/`ENVIRONMENT_VARIABLES.md`/`BETA_RELEASE_CHECKLIST.md`/
  `FRONTEND_MASTER_SPEC.md`/`roadmap.md`/`frontend.md`). CHANGELOG·BUGS의 **과거 기록은 그대로 보존**

**5. Audit 결과 (새 결함 0건)**

- **Dead code**: `src/` 34개 파일 export 전수 스캔 — 참조 0건인 함수/상수 **0건**
  (`mapStatusView`는 같은 파일의 `assembleRightsAnalysis`가 사용 중이라 dead 아님)
- **API 계약**: 프론트가 호출하는 14개 엔드포인트를 서버 OpenAPI(31개)와 대조 — 누락 0건
- **아키텍처 불변식**: `/`·`/search`의 `SearchScreen` 단일 공유 / `SiteHeader` 단일 Header /
  `CONTAINER` 단일 정의 / 서버 게이트 단일 위치(`proxy.ts`) 전부 유지.
  API 호출은 `src/lib/api.ts` 래퍼 경유(예외 1건 — 상세의 문서 존재확인 HEAD 프로브, 문서화됨)
- **TODO**: 신규 0건(기존 4건 전부 "백엔드 미지원" 기록)
- **성능**: dev 로그 기준 `proxy.ts` 구간 **5~12ms**(비로그인), `/` 서버 총 178~227ms.
  전환에 따른 회귀 없음

**품질 게이트** — Python 회귀 **15/15 PASS**, 프론트 **53/53**, Type Check / Lint 0 / Build 통과
(빌드 경고 0건).

---

2026-08-11 (Sprint 51) — 검색 데이터 품질 정상화 + 레거시 정리 + 부트스트랩 복구

사용자 확정 정책(**KG이니시스 실연동만 SKIP**)에 따라, 이전 Sprint들이 "승인 대기"로
남겨둔 항목을 실제 코드/데이터/브라우저로 검증하며 처리했다.

**1. BUG #33 물건종류 검색 — 해결 (도달 불가 745행 → 0행)**

먼저 전수 조사부터 했다. `auction_item.property_type` 1,870행은 고유값 18종, 콤마 분해 시
**고유 토큰 15개**이고 **NULL·빈값·앞뒤 공백·내부 공백이 전부 0건**이었다. 레거시 `auction`
테이블과 분포가 완전히 동일해 `migrate_execute.py`가 값을 변형하지 않음도 확인했다.
크롤러(`court_crawler.py:59`)는 법원의 "물건종류"를 **원문 그대로** 저장한다 —
정규화 실패도 표기 흔들림도 아니었다.

정확한 실패 메커니즘은 **LIKE 방향**이었다. `property_type LIKE '%<입력>%'`인데 UI 값이
DB 토큰보다 길다: `'%다세대주택%'`은 DB값 `'다세대'`보다 길어 **절대 매치될 수 없다**.
반대로 UI 값이 토큰과 같거나(아파트/연립주택/임야…) 짧으면(전·답 → `전답`) 지금도 동작했다 —
69개 중 정확히 9개만 살아 있던 이유다.

`api/v1/search.py`에 **어휘 별칭 7개**를 순수 가산 방식으로 추가했다(다세대주택→다세대,
근린생활시설→근린시설, 오피스텔(주거)/(상업)→오피스텔, 근린상가→상가, 자동차관련→자동차,
기타중기→중기). 원본 패턴을 항상 먼저 넣고 별칭을 OR로 덧붙이므로 **기존에 매치되던 행은
하나도 빠지지 않는다** — 응답 구조·파라미터명 무변경이라 기존 API 계약을 지킨다.
**UI 어휘(Tank Auction 전수 복사)는 손대지 않았다**(§12.2 무위반).

임의 확장은 하지 않았다. 개별 차종(승용차/화물차 등)은 DB에 차종 구분이 없어 매핑하면
"승용차"에 화물차가 나오므로 **의도적으로 제외**했고, DB에 대응 토큰이 없는 53개 항목은
0건을 유지한다(버그가 아니라 "그 물건이 아직 없다"는 사실).

실측: 다세대주택 0→**376건**, 근린생활시설 0→**366건**, 오피스텔 0→**304건**,
근린상가 0→**220건**. 기존 9개 항목 건수 **전부 불변**, 다중 선택 합집합 유지,
전체 건수 1,870 불변. 브라우저에서 체크박스 복원까지 확인.

**2. 레거시 정리 (BUG #34 해결)**

- **`/properties` → `/` 영구 이동**. 404가 아니라 **항상 엉뚱한 물건이 열리던** 화면이고
  (강남구 카드 → 관악구 물건), `docs/CLAUDE.md`의 "경매 데이터는 Python API 경유" 규칙을
  어기는 유일한 화면이었으며, Supabase 5행은 프로토타입 시드였다.
  하위 경로(`[id]`/`recent`)와 로그인 게이트는 영향 없음을 실측 확인
- **`src/login/` 제거** — `src/app/` 밖이라 라우팅 불가 + import 0건으로 **도달 불가 증명**.
  구 브랜드명 사용, 로그인 후 레거시 `/properties`로 보내고 `sanitizeRedirectPath` 방어가
  전혀 없는 **§3.4 계약 위반 구현**이었다
- **`SearchFilters.tsx` 제거** — 위 페이지가 유일한 사용처였던 중복 검색 UI

**3. 부트스트랩 재현성 복구 (Migration 017 신설)**

빈 DB로 fresh clone 부트스트랩을 실제로 재현해 운영 DB와 대조한 결과
**`document_collect_failures` 테이블 하나가 생성되지 않음**을 발견했다(운영 25 vs fresh 24).
이 테이블은 `collect_documents.py`가 쓰고 `api/v1/doc_stats.py`가 읽는데, 생성 코드가
번호 없는 별도 스크립트(`storage/migrate_doc_collect.py`)에만 있어 문서화된 부트스트랩
순서에서 빠져 있었다 → 신규 설치 시 `doc_stats`가 "no such table"로 실패하는 상태.

`017_create_document_collect_failures.sql` 신설(정의는 기존 스크립트에서 글자 그대로 이관,
`IF NOT EXISTS`라 운영 DB에서는 완전한 no-op). 백업 후 적용 — 기존 3행 무손실,
integrity/FK ok. **재검증: fresh clone이 운영 스키마를 25/25 테이블, 컬럼 불일치 0으로 완전 재현.**

부수 확인: 과거 문서가 "Migration 017(soft delete)"로 적어 온 것은 **잘못된 번호**였고
실제 내용은 016에 들어 있다. 관련 stale 기록을 정정했다.

**4. `storage/` gitignore 정밀화 (BUG #28의 구조적 원인 제거)**

`.gitignore`의 `storage/` 한 줄이 **load-bearing 소스 22개**(database.py / checkpoint.py /
migrate_v4_1.py / migrations/*.sql …)를 버전관리 밖으로 밀어내고 있었다. #28(체크포인트
원자적 쓰기 수정이 소리 없이 사라진 사건)에서 **언제·왜 되돌아갔는지 추적할 방법이 아예
없었던** 직접 원인이다. 소스(.py/.sql)만 추적하고 데이터는 계속 무시하도록 바꿨다
(`storage/` → `storage/*` + 재포함 규칙 — git은 부모 디렉터리가 제외되면 재포함이 불가하다).
추적 전 비밀값·개인정보·절대경로 스캔 0건 확인, 데이터/캐시가 여전히 무시되는지 실측 확인.

**5. 잘못된 검색 파라미터 UX (Sprint 50 기술부채 #8 해결)**

`?size=500`·`?size=abc`·`?page=0`·`?sort_by=DROP` 등 백엔드가 400/422로 거부하는 입력에서
"검색 결과를 불러오지 못했습니다"(=서버 장애처럼 보이는 문구)만 뜨고 되돌아갈 동선이 전혀
없었다. `SearchScreen`이 `ApiError.status`로 **bad_request / unavailable을 구분**해
전자에는 원인 안내 + "검색조건 초기화"(basePath 유지) 링크를 준다. 6개 케이스 실측 확인.

상세 화면에도 같은 기준을 적용했다 — API 장애 시 "매물을 찾을 수 없습니다"(없는 물건으로 오해)
대신 "물건 정보를 불러오지 못했습니다 / 일시적 오류"를 보여주고, 404는 기존 문구를 유지한다.
양쪽 다 "검색 화면으로" 탈출 동선 추가. **실제로 API 서버를 내려 재현 검증**했다.

**6. BUG #36 신규 — `property_type` 대량 입력 500 (해결)**

DoS 내성 점검 중 발견: 콤마로 2,000개 토큰을 보내면 SQLite 표현식 한계로 **500**이 났다
(별칭 도입과 무관한 기존 결함). `MAX_PROPERTY_TYPES = 100` 상한 + 400 응답으로 수정.
UI 최대가 69개라 정상 사용에 여유가 있다. 69/100 → 200, 101/2,000/10,000 → 400.

**Audit 결과**

- **약한 테스트 재탐색**: `in (200,404)` 형태 2건 발견했으나 둘 다 이미 강화돼 있음을 확인
  (문서 조회는 실제 파일 내용 검증이 뒤따르고 HEAD/GET 교차 확인, 레이스 테스트는
  "정확히 1건만 200" + DB 필드 일관성 검증이 함께 있음). `check_true(..., True)` 패턴도
  전부 except 블록의 정상 사용이었다 — **약한 테스트 결함 0건**
- **성능**: 별칭 확장 비용 +0.3ms(1.9→2.2ms), 69개 전체 선택 최악 케이스도 2.6ms.
  쿼리 플랜은 여전히 `idx_auction_item_default_sort` 인덱스 seek
- **크롤러**: 원자적 쓰기 방어(#22/#23/#28) 전 계층 유지 확인, 관련 테스트 30검사 PASS

**테스트** — Python 회귀 **469 → 494검사**(§2-B 물건종류 별칭 신설), 프론트 **53 → 59검사**.
변이 테스트 5종 전부 검출 확인. 작성 중 **테스트 자체 결함 1건 발견·수정**: 별칭 테스트가
기대값을 `PROPERTY_TYPE_ALIASES`에서 끌어와, 표를 비우면 루프가 0회 돌아 전부 통과하는
자기참조 결함이 있었다(기대 목록을 테스트가 직접 들도록 수정).

**품질 게이트** — Python 회귀 15/15 PASS, 프론트 59/59, Type Check / Lint 0 / Build 통과(경고 0).

---

2026-08-11 (Sprint 52) — 결제 도메인 내부 완성 + 사용자 구독 조회 + 기술부채 정리

확정 정책(**KG이니시스 실연동만 SKIP**)에 따라, PG 없이 만들 수 있는 결제 내부 로직을
전부 연결했다. **실제 PG 호출은 하지 않는다**(MockProvider).

**1. 결제 도메인 — 준비만 되고 실행된 적 없던 경로 연결 (`docs/BUGS.md` #38)**

전수 확인 결과 결제 도메인의 절반이 "코드는 있는데 도달할 수 없는" 상태였다:
`PAYMENT_TRANSITIONS`의 환불 전이 / `cancel_payment()` / `handle_webhook()` /
`payment_webhooks` 테이블 / `EVENT_CANCEL`·`EVENT_WEBHOOK` / `PAY_NOT_FOUND`·
`PAY_INVALID_TRANSITION` — **전부 호출부 0건**이었다.

- **`POST /api/v1/admin/payments/{id}/refund` (SUPER_ADMIN)** — 전액/부분/반복 환불.
  누적 환불액은 **스키마 변경 없이** `payment_logs`의 CANCEL 이벤트 합계로 계산한다.
  상태머신 관문 통과 필수, 잔여 초과·0원·음수 거부, 이미 전액 환불이면 멱등,
  `BEGIN IMMEDIATE` + 조건부 UPDATE로 동시 환불 방어, `audit_logs` 기록.
  provider가 미구현(kginicis)이면 **상태를 바꾸지 않고** 실패만 남긴다.
- **`POST /api/v1/payments/webhook/{provider}`** — 사용자 인증이 없는 경로라
  **서명 검증이 유일한 방어선**이다. `verify_webhook_signature()`를 provider 인터페이스에
  신설하고 **기본 구현을 항상 False(fail-closed)** 로 뒀다. MockProvider는
  `PAYMENT_WEBHOOK_SECRET` HMAC-SHA256 + 상수시간 비교이며 **시크릿 미설정이면 전부 401**.
  서명은 payload 파싱보다 먼저 검증하고, `event_id` UNIQUE로 멱등 처리하며,
  검증 실패도 감사용으로 기록한다.

**함께 고친 결함**: `MockProvider.handle_webhook()`이 event_type과 무관하게 **항상 SUCCESS**를
반환하고 있었다 — 그대로 엔드포인트를 붙였다면 `PAYMENT_FAILED` 노티에 결제를 성공으로
바꿨을 것이다. event_type을 실제로 해석하도록 수정.

**임의로 정하지 않은 것(사업 정책)**: 환불 조건·기간·비율(예: 구독 잔여기간 일할 계산),
사용자 셀프 환불 개방, 환불 시 구독 자동 해지 여부 — 전부 SKIP하고 응답에
`subscription_untouched`로 명시했다.

**2. 사용자용 구독 조회 신설 — `GET /api/v1/subscriptions/me`**

**결제한 사용자가 자기 구독을 볼 방법이 아예 없었다.** 프론트는 등기부 신청 실패 시 돌아오는
error code로 "구독이 없구나"를 간접 추론하는 것이 유일한 수단이었고, 플랜·만료일·유예기간을
확인할 경로는 없었다. 기존 `api/v1/subscriptions.py`(파생 필드 + lazy sync)를 그대로
재사용하고 응답 형태도 기존 리스트 엔드포인트와 동일하게 맞췄다(새 관례 없음).
마이페이지 **화면**은 스펙 미정이라 만들지 않았다 — 어떤 스펙이 나오든 필요한 조회 계약만 완성.

**3. `audit_logs` QA 잔여 792행 정리 (`docs/BUGS.md` #39)**

`cleanup()`이 `user_id` 기반이라 `user_id` 컬럼이 없는 `audit_logs`/`payment_webhooks`를
한 번도 정리하지 못했다. 부모 행을 지우기 전에 대상 id를 캡처해 정확히 그 감사 행만 지우도록
고치고, **검증 체크가 공허하게 참이 되던 허점**도 함께 수정했다(부모를 지운 뒤에 되물어
항상 0이었다). 기존 792행은 dangling만 선별해 백업 후 1회 정리.
이제 회귀 실행 후 `audit_logs`/`payment_webhooks`/`payment_logs` 전부 0행이다.

**4. Frontend 기술부채 3건**

- **카드 "조회수 -" 제거** — `auction_item`에 컬럼이 없어 **구조적으로 항상 "-"** 인 죽은 UI였다
- **`crawl_date`(수집일) 정렬 UI 노출** — 백엔드·타입은 지원하는데 UI만 빠져 있어
  URL을 직접 편집해야만 쓸 수 있는 도달 불가 정렬이었다. 계약 테스트로
  "타입에 있는 정렬은 UI에도 있어야 한다"를 고정
- **비로그인 검색조건 저장 시 입력하던 이름 보존** — 조건(쿼리스트링)은 이미 보존됐지만
  이름은 사라져 다시 타이핑해야 했다. 복귀 URL에 실어 되살린다
  (`preset_name`은 FILTER_PARAM_KEYS 밖이라 검색조건·저장 conditions로 새지 않음 — 테스트로 고정)

**5. Audit**

- **Git/저장소**: Sprint 51 상태 유지 확인 — 추적 백업 9개 증가 없음, 신규 백업 2개는
  `.gitignore`로 정상 제외, 추적 백업의 개인 테이블 행 20개는 전부 `qa-*` 합성.
  기존 9개 untrack은 **Commit이 필요해 SKIP**
- **성능**: 별칭·신규 경로 모두 영향 없음(검색 2~10ms 유지)
- **약한 테스트**: `no test audit rows left`가 공허하게 참이던 것을 발견·수정(위 3번)

**테스트** — Python 회귀 **494 → 569검사**(§29 환불 / §30 Webhook / §31 구독 조회 신설),
프론트 **59 → 64검사**. 변이 5종 전부 검출(서명 검증 무력화 / 상태머신 관문 제거 /
멱등성 제거 / 권한 완화 / 환불 상한 제거).

**신규 환경변수** — `PAYMENT_WEBHOOK_SECRET`(선택, 미설정이 안전한 기본값).
**값은 운영자가 생성하며 이 저장소가 만들지 않는다.**

**품질 게이트** — Python 회귀 15/15 PASS, 프론트 64/64, Type Check / Lint 0 / Build 통과.

---

2026-08-11 (Sprint 53) — Webhook 운영 도구 + 인증 경계 전수 + 기술부채 정리

**1. Webhook 운영 도구 신설 (`docs/BUGS.md` #41)**

Sprint 52의 수신 경로에는 **운영자가 볼 방법도 되살릴 방법도 없었다**. 엔드포인트 3개를 추가했다
(조회/상세/재처리, 실제 PG 호출 없음). 재처리 가능 판정은 목록과 재처리가 **같은 함수**를 써서
"목록엔 가능한데 누르면 거부"가 구조적으로 불가능하고, 상태 변경은 수신 경로와 **같은**
`_apply_webhook_event()`가 하므로 재처리 전용 우회로가 없다. 성공하면 PROCESSED가 되어
두 번째 재처리는 자동 차단된다.

**2. 보안 결함 2건 발견·수정 (#42) — 성능 감사와 변이 테스트에서 나왔다**

- **저장소 증폭(DoS)**: 인증 없는 Webhook 경로가 **서명 없는 익명 요청마다 DB 행을 생성**했다
  (실측: 5회 요청 → 5행). 서명 검증을 파싱·DB 쓰기보다 **먼저** 수행하고, 검증 실패는
  저장하지 않고 경고 로그만 남긴다 — 로그는 회전되지만 DB는 계속 쌓이기 때문이다.
  실측 재검증: 익명 20회 → **증가 0행**
- **event_id oracle**: 중복 검사가 서명 검사보다 앞에 있어, 서명 없이도 **존재하는 event_id**만
  맞히면 200을 받았다(존재 200 / 없음 401). 검증을 앞으로 옮기면서 구조적으로 사라졌다

**3. 인증 경계 전수 검사 신설 (§33)**

기존 §4는 **하드코딩된 5개 경로**만 봤다. Sprint 52~53에 6개가 늘었지만 목록은 그대로였다.
이제 **OpenAPI에서 모든 엔드포인트를 열거**해 익명 접근을 검사하고, 분류되지 않은 신규
엔드포인트가 나타나면 실패한다(EXPECTED_ENDPOINTS와 같은 규율).
전수 결과: 공개 8 / 사용자 16 / 관리자 16 / 서명보호 1 — **익명 도달 가능한 보호 엔드포인트 0건**.
인증이 body 검증보다 먼저 동작하는 것(스키마 정보 미유출), 사용자 간 결제 격리(404)도 함께 고정.

**4. 테스트 하네스 결함 수정 (#43)**

변이 테스트가 `FAIL 0건 + 크래시`로 나타나는 것을 추적하니, 실패 출력에 제품 코드의 em-dash가
실려 cp949 콘솔에서 `UnicodeEncodeError`가 났다. 출력 함수 한 곳(`_safe_out()`)에서 막아
**어떤 제품 문자열이 들어와도** 재발하지 않게 했다. 같은 변이가 이제 크래시 없이 6건 FAIL로 검출된다.

**5. 기술부채 정리**

- **계약 테스트 `before()` 서버 의존 해소** — 소스만 읽는 검사 10건을
  `tests/source-contract.test.mjs`로 분리했다. 서버가 꺼져 있으면 예전엔 **소스 검사까지 전부
  취소**됐다(실측: 46건 전부 cancelled). 이제 서버 없이도 소스 계약 10/10이 정상 보고된다
- **`.env` UTF-8 BOM 제거 (#35 해결)** — 145 → 142바이트, **본문 SHA256 동일**(값 무변경).
  `os.getenv("SUPABASE_URL")`이 이제 정상적으로 읽힌다(예전엔 키가 `\ufeffSUPABASE_URL`이라 영원히 None)
- **`storage/migrate_doc_collect.py` 제거** — Migration 017로 대체됐고 코드 참조 0건(문서만).
  제거 후 fresh clone 부트스트랩이 여전히 운영 스키마를 **25/25 완전 재현**함을 확인
- **`AuditTargetType.PAYMENT_WEBHOOK` 신설** — 결제에 연결되지 못한 노티의 감사 대상을 분리.
  PAYMENT에 욱여넣었더니 dangling 감사 행으로 검출됐다
- **cleanup 순서 버그 수정** — 테스트가 webhook 행을 먼저 지워 감사 행 id를 캡처할 수 없었다

**6. 검토 후 유지하기로 한 것 (근거 기록)**

- **`TossProvider`/`PortOneProvider`** — 제거해도 이득이 없다고 판단해 유지한다.
  현재는 `.env`에 옛 값이 남아 있으면 "폐기된 PG 후보입니다"라는 **구체적 경고**가 나오는데,
  제거하면 "알 수 없는 값"이라는 일반 오류로 바뀌어 운영자 진단이 오히려 나빠진다.
  15줄이고 호출 시 즉시 `NotImplementedError`라 오용 위험도 없다. **열린 backlog → 결정 완료**로 전환
- **개별 차종(승용차/화물차) / 면적 / 특수조건 검색** — `auction_item`에 대응 컬럼이
  **하나도 없음**을 컬럼 전수로 재확인(21개 컬럼 중 area/special/vehicle 관련 0개).
  크롤러 수집 항목 추가 + 스키마 변경이 선행돼야 하므로 코드로 해결 불가

**7. 성능 감사(실측)**

신규 엔드포인트 전부 1~5ms. Webhook 목록은 `idx_payment_webhooks_received_at`,
환불 누적액은 `idx_payment_logs_payment_id` 인덱스 seek. `/subscriptions/me`는 TEMP B-TREE가
뜨지만 사용자당 구독이 1~2건이라 **측정상 영향이 없어 최적화하지 않았다**.

**테스트** — Python 회귀 **569 → 616검사**(§32 Webhook 운영 / §33 인증 경계 전수),
프론트 64검사(파일 2개로 분리, 총계 동일). 변이 8종 전부 검출. 3회 연속 실행 잔여 0.

**품질 게이트** — Python 15/15 PASS, 프론트 64/64, Type Check / Lint 0 / Build(경고 0) 통과.

---

2026-08-11 (Sprint 54)

권리분석 신뢰도 결함 수정 (BUGS #44)

- `rightsAnalysis.ts` — 정보원이 하나뿐이면 대조가 불가능한데 "충돌 없음"과 뭉개져
  **HIGH**가 나오고 있었다(실측 180건 중 81건, 45%). 대조 가능 여부를 등급 계산에 포함.
- 판정 조건을 `canCrossCheck()` 한 함수로 추출 — `detectConflicts()`의 가드와
  `computeConfidence()`의 입력이 갈라지지 않게 고정
- `tests/rights-analysis.test.mjs` 신설(15건). 이 모듈은 그때까지 테스트가 0건이었다.

크롤 파이프라인 중단 대응 (BUGS #46, **Release Blocking**)

- `run_daily.bat` / `run_doc_worker.bat` / `run_priority_refresh.bat` — 사라진
  Anaconda 경로 하드코딩을 제거. 기존 경로 우선 → `where python` 폴백 →
  **둘 다 없으면 로그 기록 후 exit 1**(실패 은폐 차단)
- `requirements.txt` 신설 — 소스 153개 `.py`의 import를 전수 파싱해 도출.
  실측 가능한 버전만 고정, 사라진 환경의 버전은 추측하지 않음
- `test_schema_hygiene.py`에 "requirements.txt ↔ 소스 import 일치" 검사 추가(§4)

기록만 한 항목

- BUGS #45 — "정보원 SPEC 미확보"가 명세서 임차인 표 위에 표시됨. 어느 사실을 "정보원"으로
  부를지가 화면 설계 결정이라 이번 Sprint 지침에 따라 수정하지 않고 기록
- Admin 운영 UI — 인증이 공유 `X-Admin-Key` 하나뿐이고 감사 로그의 `admin_id`에
  역할 문자열("SUPER_ADMIN")이 들어간다. 환불 같은 조작이 **사람 단위로 추적되지 않는다**.
  브라우저 UI를 만들면 그 키를 가진 사람만 늘어나므로 운영자별 신원 체계가 먼저 필요

테스트: Python 616검사 + 파일 19개 중 16개 PASS(3개는 selenium 미설치로 실행 불가),
프런트엔드 86검사, 변이 9/9 검출. TypeCheck/Lint/Build 전부 통과.

---

---

2026-08-11 (Sprint 55)

크롤/파이프라인 실패 은폐 구조 제거 (BUGS #47)

- `mvp_scraper.main()` / `doc_worker.main()`이 `-> None`이라 **무엇이 얼마나 실패하든
  종료 코드가 0**이었다. 배치의 `if errorlevel 1`은 구조적으로 발동 불가였다.
  2026-08-02 실행(59/60 법원 실패, 저장 0건)이 "성공"으로 끝난 이유다.
- `models/crawl_outcome.py` 신설 — 판정을 selenium 없이 테스트 가능한 곳으로 분리
- `run_doc_worker.bat` / `run_priority_refresh.bat`에 errorlevel 검사 + `[SUCCESS]`/`[FAILED]` 마커
  (Sprint 13은 `run_daily.bat`만 고쳤었다. 전체 로그에 이 마커가 **0회** 기록돼 있었다)

document_queue 적재 누락 (BUGS #48) — Migration 018

- UNIQUE에 `item_no`가 빠져 한 사건의 두 번째 물건부터 `INSERT OR IGNORE`에 삼켜졌다.
  실측: 물건 1,870개 중 **716개(38%)**가 자기 item_no로 큐에 없었다.
- 코드 주석은 `item_no`가 포함된 키를 전제하고 있었다 — 주석과 스키마가 갈라져 있었다.
- 행 삭제 없이 id까지 보존해 이관(3,480행 / 최대 id 17637 불변).
- `run_migrations.py`의 `sys.path` 계산이 한 단계 부족해 직접 실행이 불가했던 것도 함께 수정.

문서 상태가 화면에 도달하지 않던 문제 (BUGS #50, #45 해결)

- 파이프라인이 두 동강 나 있었다. `document_status`/`doc_raw`/`tenant_rights`/`rights_summary`를
  쓰는 스크립트 4개가 **어떤 배치에서도 도달 불가**였고, 화면은 그중 `document_status`를 읽는다.
- `mark_queue_done()`이 같은 트랜잭션에서 `document_status`를 갱신하도록 수정.
  최종 실패만 FAILED로 반영(중간 재시도는 화면을 흔들지 않는다).
- 과거 어긋남 574행을 `repair_document_status.py`로 1회 보정 — 판단 근거는 DB 플래그가
  아니라 **디스크 실물**, 경로 규칙은 API 서빙과 동일(경로 탈출 검사 포함).
- 브라우저 실측: 물건 111이 "SPEC 미확보 / 수집중" → **"SPEC ✓ 확보 / 수집완료"**

실제 접속 스크립트의 실행 가드 (BUGS #51)

- `test_db.py`/`test_docs.py`/`test_docs2.py`는 assert가 0개이고 실제 법원 사이트에 접속한다.
  "회귀 대상 아님"이 문서 6곳에 있었지만 아무것도 막지 못했고, 이번 감사에서 실제로
  전수 실행 스윕이 두 번 돌았다(selenium 부재로 우연히 접속만 면했다).
- `ALLOW_LIVE_CRAWL=1` 없이는 즉시 `[SKIPPED]` 종료. 스윕 분류가 "환경부재"에서
  "설계상 건너뜀"으로 바뀌어 실패와 구분된다.

기록만 한 항목

- BUGS #49 — `parsed_document` / `rights_analysis_history`: 읽기·쓰기 코드가 하나도 없는 죽은 테이블
- 파이프라인 후반 스크립트 4개의 스케줄러 미연결 — 배치/스케줄 변경은 운영 결정이라 SKIP
- 면적 검색: 데이터는 이미 수집돼 있다(`full_address`의 99.0%에 면적 수치). 로드맵의
  "크롤러 수집 항목 추가 선행" 서술은 면적에 한해 **부정확**했다. 다만 2.4%가 층별 다중 면적이라
  어느 값을 색인할지는 제품 결정이다.

테스트: Python 616검사 + 파일 21개(18 PASS / 3 설계상 건너뜀), 프런트 86검사,
변이 25종 전부 검출(14 + 7 + 4). TypeCheck/Lint/Build 통과.

---

2026-08-11 (Sprint 56)

동시성 가드 검증 정상화 (BUGS #53)

- `test_race_conditions.py`가 **레이스를 재현하지 못하는 레이스 테스트**였다.
  가드를 제거하는 변이를 넣어 보니 4개 중 2개가 통과했다.
- 무료한도 레이스: `threading.Barrier` + 경합 폭 10→24 → 변이 검출 2/3 → **4/4**
- 관리자 TOCTOU: 스레드로는 안정 재현 불가(6스레드에서 오히려 1/5로 악화)로 판단,
  **결정적 구조 검사**(조건부 WHERE / rowcount / 409 / 롤백) 추가 → **4/4 결정적 검출**

구독 만료 파싱 실패의 조용한 폴백 제거 (BUGS #52)

- `state_machines._parse()` / `subscriptions.renew()`가 로그 없이 폴백했다.
  깨진 `expires_at`을 가진 구독은 **무기한 유효**해지는데 알 방법이 없었다.
- 두 곳 모두 경고 로그 추가. 부재(`None`/`''`)와 날짜만 있는 값에는
  **경고를 남기지 않는 것**까지 테스트로 고정(과잉 경고는 진짜 경고를 묻는다).

금전 가드 회귀 추가 (BUGS #54)

- 미결제(PAYMENT_REQUIRED) 신청을 관리자가 COMPLETED로 옮길 수 없다는 가드에 회귀가 없었다.
- 기존 "미완료 다운로드" 단언이 `success=False`만 봐서 상태 검사 제거 변이를 놓쳤다 —
  `error` 코드까지 고정하도록 강화. 변이 5/5 검출.

파이프라인 정합 불변식화 (신규 `test_pipeline_integrity.py`, 30검사)

- Sprint 55 수정 이후 단계 간 불일치가 0이 된 상태를 불변식으로 못 박았다.
- 변이 9종(상태 되돌림 / retry 불일치 / 고아 행 / doc_type 오염 / 미지 상태값 등) **9/9 검출**

기록만 한 항목

- BUGS #55 — `doc_raw`도 라이브 경로가 쓰지 않는다(`parsed_document`와 같은 부류).
  적재 소유권 결정이 선행돼야 함
- BUGS #56 — `property_type` 모순 5건(양방향). 원인은 실제 페이지 재확인 필요(SKIP),
  대신 상한을 둔 검사로 증가만 차단

테스트: Python 627검사 + 파일 22개(19 PASS / 3 설계상 건너뜀), 프런트 93검사,
변이 22종 전부 검출(9 + 5 + 4 + 4). TypeCheck/Lint/Build 통과.

---

2026-08-11 (Sprint 57)

`auction.db`가 되돌아가 있던 것을 재발견·복구 (BUGS #57)

- migration_history가 Sprint 51 이전 옛 파일명만 기록, 현재 추적 파일(016/017/018)
  3개가 실제로는 한 번도 적용되지 않은 상태였음을 `test_schema_hygiene.py`로 발견
- Migration 018(document_queue UNIQUE에 item_no 포함, BUGS #48) 미반영으로
  자기 item_no로 큐에 없는 물건이 37.3%(751/2,012)까지 재발해 있었음 — 실제 적용 후
  enqueue_documents() 재호출로 매각기일 남은 물건 전량 큐 등록 확인
- audit_logs dangling 698행(Sprint 52 #39 재발), document_status 574행(Sprint 55 #50
  재역행) 둘 다 재보정
- 드리프트를 유발한 미추적 중복 파일 3개 삭제(storage/migrations/016_create_audit_logs.sql,
  017_add_soft_delete_columns.sql, storage/migrate_doc_collect.py)
- docs/backend.md의 stale 마이그레이션 목록(016_create_audit_logs.sql/
  017_add_soft_delete_columns.sql로 남아 있던 것)을 실제 추적 파일 기준으로 정정

새 정책 결정이 아니라 이미 승인·완료된 작업의 재적용이라 승인 없이 즉시 처리.
작업 전 `auction.db.backup_before_migration_reconcile_20260811_233247` 백업.

테스트: Python 15개 파일 전부 PASS(test_db.py 설계상 SKIP, test_schema_hygiene.py/
test_pipeline_integrity.py 신규 FAIL 발견분 포함 전부 PASS로 전환), 프런트 93/93 PASS
(API+dev 서버 동시 기동, cancelled 0 확인). TypeCheck/Lint(0)/Build(경고 0) 통과.

---

2026-08-12 (Sprint 58)

Admin 키 상태 재확인 + 환불/Webhook 재처리 동시성 커버리지 신설

- ADMIN_API_KEY/SUPER_ADMIN_API_KEY가 실제로 이미 설정되어 정상 동작 중임을 실제 요청으로
  재확인(이전 문서의 "미설정 500" 기록은 stale). SUPABASE_JWT_SECRET은 여전히 이름이 없지만
  JWKS/ES256이 주 경로라 실사용자 인증에 영향 없음을 재확인. docs/ENVIRONMENT_VARIABLES.md 정정
- 환불(Sprint 52)/Webhook 재처리(Sprint 53) 둘 다 소스에는 BEGIN IMMEDIATE + 조건부 UPDATE
  가드가 있는데 동시 요청 회귀가 없던 공백을 발견 — test_race_conditions.py에 3개 시나리오
  신규(22 -> 41검사): 환불 3스레드 동시요청, 환불 가드 구조검사, Webhook 재처리 가드 구조검사
- 변이 검증: BEGIN IMMEDIATE 제거/조건부 UPDATE 제거 두 변이 모두 3스레드 재현으로는 미검출
  (Sprint 56 Admin TOCTOU와 동일한 "좁은 창" 한계), 구조 검사는 둘 다 결정적으로 검출.
  검증 후 소스는 정확히 원복(git diff 0, 테스트 파일만 순증)

새 버그는 발견하지 않음 — 기존 코드의 동시성 방어는 이미 올바르게 구현돼 있었고, 이번
Sprint는 그 사실을 검증 가능한 회귀로 고정한 것.

테스트: test_race_conditions.py 22 -> 41검사, 나머지 전부 무변동 PASS. TypeCheck/Lint/
compileall 통과.

---

2026-08-12 (Sprint 59)

Admin 구독 상태 변경 동시성 결함 발견·수정 (BUGS #58)

- api/v1/subscriptions.py:change_status()(PATCH /admin/subscriptions/{id}의 유일한 구현부)에
  동시성 방어가 전혀 없어, 서로 다른 목표 상태로 동시 PATCH 시 둘 다 200 성공 응답(진 쪽도
  거짓 성공)했음을 실측 재현(5/5)으로 발견. 등기부 #21과 동일한 BEGIN IMMEDIATE + 조건부
  UPDATE(WHERE id=? AND status=?) + rowcount 확인 패턴으로 수정, 신규 ConcurrentStatusChange
  예외 -> admin.py에서 409로 변환
- 수정 후 5/5 재현 전부 정확히 1건만 200으로 확인
- test_race_conditions.py 신규 2개 시나리오(실스레드 재현 + 결정적 구조 검사, 41 -> 49검사).
  변이 검증: 두 가지(BEGIN IMMEDIATE 제거/WHERE status=? 제거) 모두 구조 검사만 결정적으로
  검출(스레드 재현은 refund/webhook 재처리와 동일한 좁은 창 한계로 놓침)

테스트: test_race_conditions.py 49/49, test_api_regression.py 627검사 무변동, 나머지 회귀
전부 PASS. TypeCheck/Lint(0)/Build(경고 0)/compileall 전부 통과.

---

2026-08-12 (Sprint 60)

만료 구독 재활성화가 항상 조용히 실패하던 결함 발견·수정 (BUGS #59)

- change_status()의 docstring이 이미 명시한 설계("ACTIVE 재활성화 시 호출부가 새 expires_at을
  넘긴다")가 실제로는 배선되지 않았음을 발견. 만료 구독을 Admin이 ACTIVE로 되돌려도
  expires_at을 갱신하지 않아 200 응답 직후(같은 응답 안에서도 effective_status가 이미
  EXPIRED) 조용히 원상복구됐다
- change_status()에 new_expires_at 매개변수 추가, 없으면 ReactivationRequiresNewExpiry(400)
  로 명확히 거부. 값은 Admin이 명시(요금 정산 정책은 서버가 추측하지 않음, refund 금액과
  동일 원칙). PAUSED->ACTIVE 재개는 영향 없음(실측 확인)
- test_api_regression.py §27에 11개 검사 신규(627 -> 638), test_race_conditions.py §10
  구조 검사를 4개 UPDATE 분기 전수로 갱신(49검사 무변동)

테스트: 전체 회귀 PASS. TypeCheck/Lint(0)/Build(경고 0)/compileall 전부 통과.

---

2026-08-12 (Sprint 60 마무리 — Release 준비)

- 사용자 지정 11개 회귀 체크리스트 대조 중 ACTIVE→CANCELLED/ACTIVE→EXPIRED가 실제 Admin
  엔드포인트로는 검증된 적이 없었음을 발견 — test_api_regression.py §27에 8개 신규
  (638 -> 646), 실제 PATCH 왕복으로 200/status/DB 반영/만료 시각 확인
- BEGIN IMMEDIATE 제거·조건부 UPDATE 제거 두 변이 최종 재검증(§10이 결정적으로 검출),
  수정 후 정확히 원복(git diff 0)
- mutation-test 임시 코드/디버그 print/scratch 파일 저장소 잔여 0건 확인
- api/v1/subscriptions.py·api/v1/admin.py diff 전문 재검토 — 중복 UPDATE/import/구식
  코드 없음

테스트(최종): test_api_regression.py 646검사, test_race_conditions.py 49검사, Python
회귀 15개 파일 전부 PASS, 프런트 계약 93/93(cancelled 0). TypeCheck/Lint(0)/Build(경고 0)
전부 통과.

---

2026-08-12 (Sprint 61)

개인화 도메인 IDOR 전수 감사 + 크롤러 복구 경로 회귀 + 크롤러 의존성 설치

**감사 결과 — 제품 결함 0건**
- Admin 41개 엔드포인트 중 목록/필터 계약을 실측 검증(필터 정확성 / 페이지네이션 무중복·무누락 /
  page·size 경계 / 404 / 잘못된 path param) — 결함 0건
- Favorites / Search Presets / Recent Items의 IDOR·소유권 경계 실측 — 결함 0건
  (A가 B의 데이터를 조회·수정·삭제할 수 있는 경로 없음, 위조 토큰도 개인화 미적용)
- Frontend↔API 계약: 프런트 TS 인터페이스가 선언한 필드가 실제 응답에 전부 존재(누락 0건),
  프런트가 호출하는 경로가 전부 백엔드에 존재

**신규 회귀 (646 → 660검사, `test_document_queue.py` +8검사)**
- 남의 즐겨찾기/preset 삭제 시도가 거부될 뿐 아니라 **실제로 지워지지 않는지**까지 단언
- 검색 개인화 3갈래(소유자 true / 다른 사용자 false / 비로그인 false)
- Recent Items 격리·정렬·LIMIT 20 — 그동안 검사 0건이던 영역
- `reset_stale_queue()` 직접 회귀 — `doc_worker.py` 크래시 복구 경로. **살아있는 Worker의
  in_progress를 건드리지 않는지**(중복 수집 방지)를 핵심으로 검증
- 변이 11종 전부 검출, 소스는 SHA256 대조로 byte 단위 원복 확인

**테스트 결함 수정 (`docs/BUGS.md` #60)**
- 프런트 계약 테스트의 crawl_date 정렬 검사가 실패했으나 **제품은 정상**이었다 —
  크롤 중단(#46)으로 진행 중 물건이 14건까지 줄고 전부 같은 crawl_date가 되어, 정렬 키가
  상수인 집합에서 asc/desc가 같은 순서를 내는 올바른 동작이 실패로 보인 것.
  검사 대상을 crawl_date가 실제로 여러 값인 집합으로 교체(assertion 무약화)
- recent-items 정렬 검사도 같은 축의 함정(시계 분해능으로 viewed_at 동률 → tie-break로
  통과)을 변이 테스트로 발견해 결정적 설계로 교체

**실행 환경**
- `selenium==4.47.0` / `webdriver-manager==4.1.2` / `pandas==3.0.5` / `pdfplumber==0.11.10`
  설치(Sprint 54부터 크롤 중단의 직접 원인으로 기록돼 있던 항목). 크롤러 계열 19개 모듈
  import 전수 확인. `requirements.txt` stale 서술 정정 + 실측 버전 고정
- 실제 크롤 실행·예약 작업 등록은 하지 않았다(외부 사이트 접속/운영 판단)

**Release Blocking 실측 (긴급)**
- 2026-08-12 기준 매각기일이 남은 물건 **14건, 전부 오늘(08-12)이 기일**.
  → **2026-08-13부터 기본 검색 결과가 0건**이 된다(Sprint 54 예측 시점과 정확히 일치)

품질 게이트 — Python 20 PASS / 3 설계상 SKIP, 프런트 93/93(cancelled 0),
compileall / tsc / eslint(0) / next build 전부 통과. 코드 변경은 테스트·문서뿐이며
`api/`·`storage/` 제품 소스는 이번 Sprint에서 **변경하지 않았다**.

---

2026-08-12 (Sprint 62)

파이프라인 후반(문서 파싱 / 권리분석) 실제 결함 2건 수정 — Sprint 61의 의존성 설치로
비로소 실행 검증이 가능해진 영역이다.

**BUGS #61 — 빈 현황조사서 캡처가 정상 수집으로 저장됨 (33건)**
- `collect_status()`의 대기 조건("텍스트가 비어 있지 않음")이 고정 라벨 때문에 데이터
  도착 전 즉시 참이 되어, 내용 없는 페이지가 저장되고 `doc_exists()`가 이를 완료로 판정해
  **영구히 재수집에서 제외**됐다
- 대기 조건을 "실제 사건 데이터가 채워짐"으로 교체 + **저장 직전 관문** 추가
- `crawler/doc_paths.py:status_overlay_has_data()` 신설(selenium 무의존 순수 함수)
- `repair_empty_status_capture.py` 신설 — 기존 33건을 격리 후 재수집 대상으로 복구
- 결과: STATUS 파싱 갭 33 → **0** (161 READY / 161 파싱)

**BUGS #62 — 근거 문서가 사라져도 권리분석 파생 행이 영원히 남음**
- `load_rights_data.py` / `load_spec_data.py`에 `purge_orphans()` 추가
- **안전장치**: 근거 파일을 하나도 못 찾으면 아무것도 지우지 않는다(경로 문제로 전체
  권리분석 데이터가 삭제되는 것을 방지 — 안전장치를 끈 변이에서 실제로 재현 확인)
- 파일은 있는데 추출 결과가 빈 경우는 지우지 않는다(파서 회귀와 구분 불가하므로 보수적)
- `rights_summary` 162 → 161, `tenant_rights` 523 → 519

**문서 정정 — "미파싱 81건"은 사실이 아니었다**
- SPEC 81건은 파싱 성공이며 표 내용이 `조사된 임차내역없음`, 즉 **임차인 없는 물건**이다.
  정상 동작을 결함처럼 기록해 온 서술을 `docs/crawler.md`/`docs/roadmap.md`/
  `docs/CURRENT_STATE.md` 및 테스트 출력에서 실측 기준으로 정정
- 남은 것은 "확인된 임차인 없음"의 표기 방식(제품 결정) 하나뿐이며 Backlog로 남겼다

**신규 테스트**
- `test_rights_data_load.py`(27검사) — 정상 적재 / 공실 / 고아 정리 / **안전장치** /
  보수적 미삭제 / 멱등성 / SPEC 정리 / SPEC 안전장치
- `test_doc_storage_atomicity.py` +8검사 — 빈 캡처 판별 + 크롤러 배선(관문 위치) 확인
- `test_pipeline_integrity.py` — "파생 데이터에는 근거 문서가 존재한다" 불변식 +
  `tenant_rights.source` 표기 검사

**품질 게이트** — Python 24개 파일 전부 PASS, 변이 14/14 검출(원래 버그 형태 재현 변이 포함),
compileall / tsc / eslint(0) / next build 전부 통과. 소스는 변이 후 SHA256 대조로 byte 단위 원복.

---

2026-08-12 (Sprint 63)

문서가 만든 운영 함정 제거 + 크롤러 동시성 핵심 경로 회귀 신설

**운영 함정 (문서 오류가 사고로 이어지는 형태)**
- `docs/roadmap.md` 16-A / `docs/crawler.md`가 파이프라인 후반 **4개 스크립트**의 배치
  편입을 Backlog로 두고 있었으나, 그중 `analyze_docs.py`는 DB에 아무것도 쓰지 않고
  마지막이 `input()`인 **1회성 조사 스크립트**다. 배치에 넣으면 stdin이 없어 매달리거나
  죽고 뒷 단계까지 멈춘다. 편입 대상은 **넷이 아니라 셋**으로 정정
- `test_crawl_exit_code.py` §8 신설 — 배치 후보 9종에 입력 대기가 없는지 + `analyze_docs.py`가
  여전히 대화형/비DB인지 **양방향** 검사(나중에 진짜 단계가 되면 실패해 갱신을 요구한다)

**동시성 핵심 경로 회귀 (`test_document_queue.py` §7~9, 17검사)**
- `claim_next_queue_item()`은 Worker가 일감을 집는 유일한 경로인데 검사가 **0건**이었다
- 선택 규칙 / 상태 필터 / 재시도 간격(30분) / `last_attempt_at` 기록 /
  **8스레드 동시 클레임 12건 중복 0** 검증
- `mark_queue_skipped_expired()`도 검사 0건이었다 — 특히 **재시도 횟수를 소모하지 않는지**
  (실패가 아니라 "대상 아님"이므로) 확인
- **이 저장소에서 처음으로 스레드 재현이 신뢰할 수 있는 검출기**였다. 조건부 UPDATE 제거
  변이를 8스레드 재현이 3회 연속 전부 검출 — `BEGIN IMMEDIATE`로 직렬화된 결제 경로(Sprint 58)와
  달리 이 함수는 배타 트랜잭션이 없어 경합 창이 실제로 넓기 때문이다

**문서 정정 (실측 기반)**
- `parsed_document`: 쓰는 코드 0곳 / 읽는 코드 0곳 — "연결만 안 된 단계"가 아니라
  **구현 자체가 없음**. `doc_raw`도 읽는 코드 0곳
- `docs/crawler.md`의 "`doc_raw` 적재에 pdfplumber 필요(미설치)"는 Sprint 61에 해소됨

**품질 게이트** — Python 24개 파일 전부 PASS, 프런트 93/93(cancelled 0),
변이 21/21 검출(Sprint 61~63 누적), compileall / tsc / eslint(0) 전부 통과.
이번 Sprint의 제품 소스 변경은 **0건**이며 테스트·문서만 추가/정정했다.

**BUGS #63 (같은 Sprint 63)** — `refresh_queue_priority()`가 검토 행 수를 "변경 건수"로
보고해 매일 밤 배치 로그가 "재계산 완료: 2,736건"을 남기던 문제. `cur.rowcount`로 실제
변경만 세도록 수정하고 검토/변경을 나눠 로그에 남긴다. 실제 배치 실행으로 137건 변경 확인
(크롤 중단으로 기일이 지나 p2 22 + p3 115 → p1 승격). `calc_priority` /
`refresh_queue_priority`는 매일 도는 배치 로직인데 검사가 0건이었다 — 17검사 신설.

---

2026-08-12 (Sprint 64)

Admin↔사용자 경계 및 조정·사용 혼합 산술 회귀 신설 (제품 결함 0건 / 제품 소스 변경 0건)

**§31-B — Admin 변경이 사용자 상태에 반영되는가 (25검사)**
- §27(Admin 변경)과 §31(사용자 조회)이 서로 만난 적이 없어, "관리자는 해지했는데 사용자는
  계속 이용 가능"이라는 과금 직결 모순이 검증되지 않고 있었다
- 한 구독을 **세 관점**(사용자 조회 / Admin 목록 / 이용권 게이트) + DB 값으로 동시에 확인
- PAUSED / 재개 / 해지 각 단계에서 status·effective_status·is_entitled·게이트가 모두 일치
- 해지 후 등기부 신청이 `REGISTRY_SUBSCRIPTION_REQUIRED`로 막히고 **신청 행도 생기지 않음**

**§20-B — 관리자 조정과 실제 사용의 혼합 산술 (20검사)**
- 기존 검사는 GRANT/DEDUCT/RESET을 따로만 봤고 실제 사용과 섞인 적이 없었다
- `effective_limit = plan_limit + adjustment` / `remaining = effective_limit - used`
  두 항등식을 GRANT → 사용 2건 → DEDUCT 각 단계에서 검증
- **사용 후 DEDUCT가 `used`를 건드리지 않음**(건드리면 쓰지도 않은 횟수를 잃는다),
  사용 로그 delta가 1회당 정확히 -1, 사용이 조정 원장을 오염시키지 않음

**오탐 2건을 재현으로 걸러냄** — "만료 구독인데 게이트가 True"(그 사용자가 다른 ACTIVE
구독을 갖고 있었음), "해지 후 PAYMENT_REQUIRED가 아님"(구독이 없으면
SUBSCRIPTION_REQUIRED가 맞다). 재현 없이 보고했다면 없는 버그를 만들어낸 사례가 됐을 것이다.

**기록만 하고 미수정** — `registry_credit_logs.balance_after`가 행 종류에 따라 "조정 누계"와
"잔여 무료횟수"를 번갈아 담아 running balance로 읽으면 `3 → 7 → 6 → 2`로 앞뒤가 안 맞는다.
산술 자체는 정확하고, 이미 노출된 API 계약이라 의미 변경은 계약 변경 + 표기 제품 결정이다.

**품질 게이트** — `test_api_regression.py` 686 → **708검사**(연속 2회 잔여 0),
Python 24개 파일 전부 PASS, 프런트 93/93(cancelled 0), 변이 30/30 검출(Sprint 61~64 누적),
compileall / tsc / eslint(0) / next build 전부 통과.

---

2026-08-12 (Sprint 65)

**크롤 파이프라인 실제 실행 검증 — Release Blocker #1 해소 입증**

Sprint 54부터 8일간 Release Blocking으로 기록돼 온 크롤 중단을, 실제로 크롤러를 돌려
전 구간 동작을 확인했다(저장소 역사상 처음).

**선행 조건** — Chrome 151 설치됨 / ChromeDriver 자동 확보 성공 / 헤드리스 기동 성공 /
courtauction.go.kr 접속 200. 크롤러를 막던 저장소·환경 측 원인은 **0건**.

**전 구간 실행**(서울중앙지방법원 1개로 범위 한정, 법원당 약 168초)
- 수집 9건(기일 2026-08-19) → 검증/정규화 통과 → upsert(신규 6/갱신 3/실패 0, exit 0)
- `enqueue_documents` added 18 → `migrate_execute` 건수 일치 [OK]
- **검색 API 실조회: 기일 남은 물건 14 → 23건**, 신규 9건이 실제로 노출됨
- → **2026-08-13에 검색 결과 0건이 되는 상황은 더 이상 발생하지 않는다**

**중복 수집 방지** — 같은 법원 재실행 시 inserted 0 / enqueue added 0 /
auction·auction_item·document_queue 증가 0으로 완전 멱등

**실행 후 무결성** — 실크롤 데이터 반영 후에도 `test_pipeline_integrity.py`,
`test_schema_hygiene.py`, Python 회귀 24개 파일 전부 PASS(불변식 무손상)

**SKIP(운영 판단)** — 전체 60개 법원 1회 실행(약 2.8시간, 정부 사이트 부하),
예약 작업 등록(실행 계정·시각 결정 필요). 둘 다 기술적 장애물은 없다.

백업: `auction.db.backup_before_sprint65_crawl_20260812_143616`

---

2026-08-12 (Sprint 66)

`collect_documents.py` 잠재 결함 2건 수정 (BUGS #64) + 감정평가서 파서 실측 스코핑

**BUGS #64 — 배치 편입 시 즉시 발현될 결함 2건** (현재 피해 0건: 아직 실행된 적 없음)
- 저장 경로가 뷰어 서빙 경로와 완전히 달랐다(`storage/docs/<type>/` vs
  `documents/<법원>/<사건>/<물건>/`). `save_doc_raw()`가 READY로 바꾸므로 배치에 넣는 순간
  "화면은 열람 가능, 뷰어는 404"가 된다 — BUGS #50 재발
- STATUS는 `download_doc()`이 `.pdf`만 받아 **구조적으로 성공 불가**인데 매번 FAILED로 기록됐다
- 수정: `crawler/doc_paths.py`에 `canonical_doc_path()`/`PDF_DOWNLOADABLE_DOC_TYPES` 신설,
  `finalize_download()`가 `os.replace()`로 뷰어 경로에 원자적 이동 후 그 경로를 기록,
  STATUS는 건너뜀(doc_worker 담당)
- `test_doc_storage_atomicity.py` +14검사, 변이 5/5 검출(2종은 수정 전 동작 재현)

**감정평가서 파서 — 실측 스코핑 후 SKIP**
- 198개 PDF 표본 30개 측정: 페이지당 문자 중앙값 526자, **80%가 텍스트 추출 가능**,
  20%는 스캔 이미지(OCR 별개 과제)
- 막는 것은 기술이 아니라 결정이다 — 추출 항목(제품)·저장 스키마(신설 필요)·화면 표기
- 초기에 소표본으로 "대부분 이미지"라 판단했다가 표본을 늘려 정정함

**Dead code 재확인** — 참조 0건 함수는 여전히 3개(전부 기존 기록), `overwrite=True` 호출 0건
재확인(Sprint 41의 유지 결정 존중). 이번 추가분은 전부 실제 배선됨(6~8회 참조).

**품질 게이트** — Python 24개 파일 PASS, 프런트 93/93, 변이 36/36 누적,
compileall/tsc/eslint(0) 통과.

---

2026-08-12 (Sprint 67)

doc_raw 소유권 실측 + `collect_documents.py` 저장/실패 경로 회귀 신설 (BUGS #65)

**doc_raw 소유권 매트릭스 확정 (roadmap 16-B 결정 입력)**
- 코드 전수 추적으로 "누가 무엇을 기록하는가"를 표로 확정. Sprint 66 수정 이후
  **두 경로가 같은 canonical 경로에 저장**하며, 남은 비대칭은 두 칸뿐이다
  (`doc_worker`는 `doc_raw` 미기록 / `collect_documents`는 `document_queue` 미갱신)
- `document_queue` 미갱신의 영향을 추적: 파일+READY인데 큐가 pending으로 남아 불변식이
  일시 실패하지만 **자가 치유**된다(다음 doc_worker가 `doc_exists()` 가드로 즉시 성공
  반환 → `mark_queue_done`). 데이터 손실·중복 다운로드 없음
- 실데이터 전수 교차 검증: READY인데 파일 없음 0 / 파일 있는데 READY 아님 0 /
  `doc_raw` 경로 부재 0
- **소유권 결정 자체는 SKIP** — 결정 없이 한쪽을 구현하면 반대 결정 시 낭비

**BUGS #65 — 0바이트 다운로드가 READY로 기록됨 (수정)**
- `save_doc_raw()`가 크기를 보지 않아 화면(READY)·뷰어(0바이트 서빙)·재수집 판정
  (`doc_exists()`=False) 세 곳이 어긋났다. BUGS #50/#61과 같은 부류
- `doc_exists()`가 이미 쓰는 "크기>0" 기준에 맞춰 `size<=0`이면 실패 반환하도록 수정
  (새 정책이 아니라 기존 기준과의 정합)

**신규 `test_collect_documents.py` (26검사)** — 배치 편입 후보인데 저장·실패 경로가 한 번도
검증되지 않았던 코드. 정상 저장 / 실패가 READY를 만들지 않음 / 이동 실패 / `save_failure`
이중 기록 / 재실행 버전 이력 / 0바이트. selenium 불필요.

**품질 게이트** — Python 25개 파일 전부 PASS, 프런트 93/93(cancelled 0),
변이 누적 48회 시도 → 47 검출 / 1 등가, compileall / tsc / eslint(0) 통과.

**Sprint 67 이어서** — self-healing 수렴을 코드 추적이 아니라 **실제 재현**으로 확정하고
`test_collect_documents.py` §7~8로 고정(30 → 53검사).
`collect_documents` 수집 직후 큐가 pending으로 남는 불일치가 실재함을 재현하고,
다음 `doc_worker` 실행에서 **재다운로드 없이** 큐 done + document_status READY로 완전히
수렴함을 확인했다(데이터 손실·중복 없음). 실패 → 재시도 간격(30분) → 성공 경로도 함께 고정.
따라서 이 차이는 버그가 아니라 roadmap 16-B **소유권 결정** 대상이라는 결론이 실측으로
확정됐고, 코드는 수정하지 않았다. 변이 3/3 검출. 누적 51회 시도 → 50 검출 / 1 등가.

**Sprint 67 이어서 (BUGS #66)** — Concurrency Audit에서 마지막 TOCTOU 경로 발견·수정.
`create_preset()`이 COUNT 확인 후 INSERT하는 구조라 상한이 동시 요청에서 뚫렸다
(99개 상태 + 12 동시 요청 → 최종 101개 재현). `registry.py`와 같은 `BEGIN IMMEDIATE`
패턴으로 수정(3회 반복 전부 정확히 100). 새 정책이 아니라 기존 상한의 정확한 집행이며
API 계약 무변경. 함께 `adjust_registry_credit`의 append-only 안전성도 12스레드로 검증
(원장 합계 정확, 유실·중복 0) — 이쪽은 결함이 없어 수정하지 않았다.
`test_race_conditions.py` 49 → 58검사, 변이 4종 전부 검출(2종은 수정 전 동작 재현).

---

2026-08-12 (Sprint 68)

**Beta 사용자 여정 Release Gate 신설** — `test_beta_journey.py` (66검사)

도메인별 회귀는 촘촘했지만 **도메인 사이의 이음매**는 어느 테스트의 책임도 아니어서
검증되지 않고 있었다(상세→최근조회, 관심물건→검색 반영, 로그인→복귀 URL).
검색부터 검색조건 저장까지 11단계를 하나의 흐름으로 묶어 고정했다.

- 여정 대상을 **DB에서 조건으로 선택**한다(문서 3종 READY + 기일 남음). 고정 id를 박지 않는다
- 각 단계에서 HTTP status가 아니라 **응답 본문 + DB 상태**를 확인
- 프런트 게이트는 dev 서버가 없으면 **SKIPPED로 명시 출력**(조용히 통과 금지 —
  "cancelled를 fail 0으로 오인"하는 기존 함정을 반복하지 않는다). 서버 유/무 양쪽 실행 확인
- 변이 3/3 검출 — 상세가 최근조회를 기록하지 않게 하거나, 관심물건이 검색에 반영되지 않게
  하면 즉시 실패한다. **어느 도메인 테스트도 잡지 못하던 결함 형태**다

**품질 게이트** — Python 26개 파일 전부 PASS, 변이 누적 58회 시도 → 56 검출 / 2 등가,
compileall / tsc / eslint(0) 통과.

---

2026-08-12 (Sprint 69)

**감정평가서 파서 기술 검증(전수) + API 장애 복원력 실측** — 제품 소스 변경 0건

- 감정평가액 추출을 **197건 전수** 측정: match 48.7% / mismatch 23.4% / 텍스트 없음 18.3%
- **불일치 원인이 파서가 아님을 원문 대조로 확정** — PDF의 감정평가액은 **사건 전체 총액**,
  `appraisal_price`는 **물건별** 값이라 개념이 다르다(물건 2건 사건에서 합계와 정확히 일치)
- → 감정평가액은 추출 가치가 낮고(화면에 이미 물건별 감정가 존재, 혼동 위험),
  가치 있는 후보는 토지/건물 내역·면적·구조 등 현재 없는 항목. **표기·스키마는 제품 결정이라 SKIP**
- 작업 중 자체 오류를 걸러냄 — 문자 중복 제거 정규식이 `2,000,000`을 `2,0,0`으로 뭉개
  잘못된 결론을 낼 뻔했고, 원문 재확인으로 정정
- `SearchScreen`의 `unavailable` 분기를 **실제로 API를 내려** 검증: HTTP 200 유지,
  안내 문구 표시, 헤더·검색 폼 유지(부분 저하), API 복구 시 정상 복원

---

2026-08-12 (Sprint 70)

미검증 화면 상태 실측 + **기술부채 1건 철회** (제품 소스 변경 0건)

- 잘못된 물건 ID(99999999/0/-1/abc), 빈 검색 결과, 페이지 범위 초과를 API·화면 양쪽에서 확인.
  빈 결과와 페이지 초과가 **서로 다른 문구 + 각각의 복구 동선**으로 갈리는 것을 재확인
  (BUGS #31 유지)
- **"Recent Items 무제한 누적" 기술부채를 실측으로 철회.** `UNIQUE(user_id, item_id)` +
  `ON CONFLICT DO UPDATE` 구조라 같은 물건을 100번 다시 봐도 행이 0개 늘어난다.
  상한은 "본 서로 다른 물건 수"(≤ 전체 물건 수)이며, 최악의 경우(1,876행)에서도
  최근조회 조회는 0.000ms(인덱스 seek), DB 1.1MB. **pruning 도입 이유 없음**

---

2026-08-12 (Sprint 71)

소프트 삭제 함정 회귀 고정 + `middleware.ts` 잔재 정리

- **`deleted_at`이 어떤 조회에도 반영되지 않는다는 현재 동작을 §28-B(8검사)로 못 박았다.**
  기존 검사는 컬럼 존재 여부만 봤고, 값을 채웠을 때 어떻게 되는지는 미검증이었다.
  실제로 채우니 즐겨찾기·검색조건 목록에 그대로 남고 검색 하트도 켜진 채였다
  (지금은 하드 삭제만 쓰므로 정상). 소프트 삭제를 배선하는 순간 이 검사가 실패하며
  함께 고쳐야 할 조회 3곳(`favorites.py`/`search_presets.py`/`search.py`)을 지목한다.
  부분 배선을 재현해 가드가 실제로 발동하는 것까지 확인했다. **전환 여부는 제품 판단이라 SKIP**
- Sprint 50의 `middleware.ts` → `src/proxy.ts` 전환 후에도 **현재 동작을 서술하며 없어진
  파일명을 가리키던 주석 5곳**을 정정. 과거 이력 서술은 보존
- `test_api_regression.py` 727 → **735검사**

---

2026-08-17

Sprint 145 — Asset 배달 검증 (docs/SPRINT145_ASSET_DELIVERY_AUDIT.md)

- **[결함 수정] BUGS #101** 진행 중 물건이 큐의 옛 매각기일 때문에 영구 미수집으로
  종결되는 문제. `storage/database.py::reconcile_queue_auction_date()` 신설,
  `doc_worker`가 `mark_queue_skipped_expired()` **직전에** 호출해 권위 있는 값
  (`auction_item.auction_date`)과 대조한다. 정책이 아니라 값의 출처만 바꿨다.
  실측: 드리프트 36행 / 그중 해로운 것 3행(item 1533 = 당시 검색 노출 9건 중 1건).
- **[관측] `test_pipeline_integrity.py` §11**에 예약 작업 등록 여부 보고 추가.
  "확인 순서: 스케줄러 등록 여부 -> ..."라고 안내하면서 정작 확인해 주지 않던 한 줄을
  채웠다. 실측 결과 **등록 0건**(전체 249개 중 이 저장소를 가리키는 것 0개)이고,
  이것이 로그가 5일째 없는 이유다. 실패시키지는 않는다(코드로 고칠 수 없는 환경 사안).
- **[회귀] `test_asset_pipeline.py` §15-B/§15-C** 7단언 신설 + Mutation 검증.
- **[측정]** 기본 검색에 뜨는 물건 9건 / 사진 9-9(100%) / 문서 3종 완비 2-9.
  `auction_image` 45행 전수 대조(파일·크기·SHA-256·매직) 불일치 0.
  상세 API SQL 7문 고정(자산 수 무관, N+1 없음).
- **[SKIP]** 스케줄러 등록(기한 2026-08-20) / 재수집 정책 / 사진 dedup(이득 0.52% 측정) /
  상세페이지 브라우저 E2E(Supabase 자격증명).
- 운영 `auction.db` / `documents/` 변경 0건 (측정은 전부 읽기 전용).

---

2026-08-17

Sprint 148~175 — 자율 감사 사이클 (docs/CURRENT_STATE.md 해당 절)

- **[결함 수정] BUGS #106** 재고가 0일 때 빈 화면 안내가 틀렸고 복구 링크가 막다른 길이었다.
  `SearchScreen`이 `hasFilters`를 계산해 넘기고 `ResultList`가 두 상태를 가른다
  (`page`/`size`/`sort_*`는 조건으로 세지 않는다). `/`와 `/search`가 같은 컴포넌트를
  쓰므로 한 번의 수정으로 둘 다 해소된다. 운영을 건드리지 않고 만료 상태를 재현해
  (사본 DB + 별도 포트) 렌더된 HTML로 4가지 경우를 전부 확인했다.
- **[결함 수정] BUGS #107** 법원 없는 식별키가 `repair_empty_status_capture.py`와
  `unlock_retry.py`에 남아 있었다(#18/#14/#103에 이은 **네 번째**). 개별 수정으로 끝내지
  않고 `test_auction_identity.py`에 **계열 전체를 막는 검사**를 신설했다 — 추적 프로덕션
  `.py`의 `UPDATE/DELETE document_queue` 문장 전수를 훑는다. 근거: case_no 3개가 두 법원에
  걸쳐 있고 물건 22건이 연루된다.
- **[결함 수정] BUGS #108** 문서 엔드포인트가 대소문자를 가려서, 같은 저장소의 다른 어휘
  (`document_queue`는 소문자)로 URL을 만들면 400이 났고 그 400이 오타와 구별되지 않았다.
  경계에서 정규화한다(받는 입력만 넓히므로 기존 동작 불변).
- **[결함 수정] BUGS #109** `doc_worker`가 실행 창 밖에서도 Selenium을 띄웠고,
  드라이버 기동 실패 시 락이 남았다(`LOCK_STALE_HOURS=5` 동안 후속 실행이 전부 건너뛰어지고
  그것이 종료코드 0으로 보고된다). 시간 검사를 락 검사 옆으로 올리고, 드라이버 생성을
  락 해제 보장 블록 안으로 옮겼다.
- **[결함 수정] BUGS #110** `build_download_driver()`가 크롬을 띄운 뒤 설정이 실패하면
  프로세스가 고아로 남았다(호출자는 `driver` 참조조차 못 받는다). #109 계열 전수 검색의 소득.
- **[결함 수정] BUGS #111** 읽기 전용 dry-run(`repair_empty_status_capture.py`)이
  `get_doc_dir()`(=`os.makedirs()`)를 물건 전수에 호출해 **디렉터리를 만들고 있었다.**
  근거가 된 숫자: 빈 물건 디렉터리 1,674 + 파일 있는 202 = 정확히 1,876 = `auction_item` 행수.
- **[결함 수정] BUGS #112** 경로 규칙 **세 번째 사본**(`repair_document_status.py`).
  docstring은 "동일한 규칙"이라 주장했지만 그 사이 규칙이 역슬래시·`..` 처리까지 확장돼
  실제로는 갈라져 있었다. #111의 호출부 전수 검색에서 나왔다.
- **[미해결 · 승인 영역] BUGS #105** 지금 상태로 `git commit -a` 하면
  `ModuleNotFoundError`로 **API가 부팅되지 않는다**(추적 파일 297개만 복사해 재현).
  탐지 가드는 신설했다(`test_schema_hygiene.py` §6-B, import 간선 4개를 자동 재계산).
  반드시 `git add -A` 후 커밋할 것.

- **[정정] 이 CHANGELOG의 Sprint 145 항목 중 "상세 API SQL 7문 고정"은 과장이었다.**
  그 시점에 7문임을 **측정**했지만 회귀로 **고정**하지는 않았다(쿼리 수를 세는 검사는
  검색 쪽 16-B 하나뿐이었다). 상세를 실제로 고정한 것은 Sprint 154에 신설한
  `test_asset_pipeline.py` 16-C다(사진 1장/8장으로 쿼리 수가 같은지 본다). 결과 본문은
  동일하고 쿼리 수만 늘어나므로 결과 기반 검사로는 잡히지 않는다.

- **[회귀 신설]** 계열 가드 위주로 추가했고 **전부 "결함을 되돌리면 FAIL하는지"까지 확인**했다:
  `test_auction_identity.py`(법원 식별키 전수) / `test_doc_path_safety.py` 7 확장·8 신설
  (규칙 사본 대상 확대, 읽기 전용 조회의 디스크 부작용, DOCUMENT_ROOT 4개 모듈 합치) /
  `test_doc_worker_recovery.py` 6·7·8(락·실행창·드라이버 고아) /
  `test_asset_pipeline.py` 1-B(형식 판정 36검사)·6-B(저장 실패 정리)·12-B(doc_raw 거짓 성공)·
  16-C(상세 N+1) / `test_search.py`(미지원 파라미터를 **동적 집합 차이**로 판정) /
  `test_api_regression.py` §16(doc_type 대소문자).

- **[측정]** 커버리지 실측 82%(`coverage.py` 33개 테스트). `crawler/image_assets.py`
  72%→86%, `storage/database.py` 87%→88%. 검색 3.2~5.4ms / 상세 2.9ms.
  E2E 정합성: READY 556 전건 파일 존재·API 200, `auction_image` 45 전건 일치, 비READY 누출 0.
  실브라우저로 검색→상세→사진→PDF 뷰어(실제 법원 문서)→인증 3화면 확인, 앱 콘솔 오류 0.

- **[자기 정정]** (1) 테스트 집계를 `종료코드 0 = 통과`로 세어 오보고했다 —
  `test_filter.py`는 판정문이 0개인 진단 스크립트다. (2) 내 AST 스캐너가 BOM 파일을
  조용히 건너뛰어 **프로덕션 77개 중 40개(52%)를 검사하지 않았다**(Sprint 149·150이
  절반만 수행된 상태였다). 고쳐 재실행했고, 저장소의 테스트들은 이미 `utf-8-sig` 규약을
  지키고 있었다. (3) Test Gap을 모듈명 grep으로 판정해 `http_cache.py`(실제 98%)와
  `doc_stats.py`(실제 100%)를 "미커버"로 분류했다.

- **[SKIP]** 스케줄러 등록(기한 2026-08-20) / commit·add / `.claude/worktrees` 1.4GB
  낡은 worktree / 빈 디렉터리 1,674개 / 면적·특수조건 필터(스키마 변경) /
  recent·favorites 썸네일(기능 추가) / `storage.database.query()` 죽은 코드(테스트가 참조).
- 운영 `auction.db` / `documents/` 변경 0건 (3,338 디렉터리 / 767 파일 / 1.29GB 그대로).

---

2026-08-17

Sprint 186 — 이미지 파이프라인 전수 추적 (docs/CURRENT_STATE.md 해당 절)

- **[결함 수정] BUGS #113** `collect_images()`가 `previous_hash`를 끝내 계산하지 않아
  이미지의 변경 감지가 구조적으로 불가능했다(`mark_queue_done`의 감지 조건이 이미지에서는
  영원히 거짓). 문서 수집기는 같은 자리를 이미 계산하고 있었다 — 이미지만 빠져 있었다.
  수집 전 디스크 기존 사진으로 `new_hash`와 같은 공식의 지문을 뜨도록 고쳤다.
- **[결함 수정] BUGS #114** 부분 수집(법원이 줄인 것 vs 일부만 받아진 것)을 구별하지
  못해 `save_auction_images()`가 사용자가 보던 사진을 지울 수 있었다. `complete` 플래그를
  추가해 판단할 수 없을 때는 남기는 쪽으로 바꿨다.
- **[회귀]** `test_asset_pipeline.py` 5-C(10검사)/7-B(10검사) 신설.
- **[SKIP]** 재수집 트리거(`overwrite=True`를 아무도 넘기지 않음, 제품 정책 대기).

---

2026-08-17

Sprint 187 — 문서 파이프라인 전수 추적 + 매일 갱신 체인 감사 (docs/CURRENT_STATE.md 해당 절)

- **[결함 수정] BUGS #115** `doc_raw.doc_version`이 내용 변경 여부와 무관하게 재수집마다
  증가했다 — `document_version_log`는 `previous_hash != new_hash`로 이미 구분하는데,
  같은 트랜잭션의 `doc_raw` 삽입엔 그 판단이 없었다(BUGS #113과 같은 계열, 이번엔 한
  함수 안의 두 기록 대상 사이). `api/v1/item.py`가 그대로 응답에 싣는 값이라 재수집을
  켜는 순간 사용자에게 드러났을 결함이다.
- **[결함 수정] BUGS #116** spec/appraisal PDF가 내용 검증 없이 저장됐다(`wait_for_download()`는
  크기만 본다). 이미지의 매직 바이트 판정과 같은 수준으로 `_looks_like_pdf()` 신설 + 배선.
- **[미해결 · 승인 영역, Release Blocker] BUGS #117** 이 환경의 `auction.db`에 마이그레이션
  020(`auction_image`)이 적용되지 않아 **검색/상세 API가 전면 500**(`curl`로 직접 확인).
  DB 스키마 변경이라 여기서 실행하지 않음 — `python -m storage.migrations.run_migrations` 승인 대기.
- **[운영 실측]** Windows 작업 스케줄러 확인 결과 `run_daily.bat`(물건 기본정보)만 매일
  도는 중(`DOJOONPASS_DAILY`, 수동 등록으로 보임, 오늘도 성공). `run_doc_worker.bat`/
  `run_priority_refresh.bat`은 **한 번도 등록된 적이 없다** — 사진/문서 자동 수집이
  구조적으로 일어나지 않는 근본 원인. `register_scheduler_tasks.ps1`을 그대로 `-Apply`하면
  `run_daily.bat`이 하루 두 번(기존 03:00 + 신규 06:00) 도는 중복이 생기는 것도 발견해
  스크립트에 기존 작업 자동 탐지+경고를 추가(자동 삭제는 하지 않음).
- **[회귀]** `test_asset_pipeline.py` +1검사, `test_doc_storage_atomicity.py` +2검사.
  관련 스위트 전체 재실행 — 전체 PASS(회귀 없음).
- **[SKIP]** 마이그레이션 020 적용 / DocWorker·PriorityRefresh 작업 등록 (둘 다 승인 영역,
  코드 준비는 완료 — 실행만 남았다).
- 운영 `auction.db` 변경 0건(스키마 변경은 승인 전이라 미적용, 조회는 전부 읽기 전용).

문서 동기화 (BUGS / CURRENT_STATE / roadmap / TEST_PLAN / SPRINT187_DOCUMENT_PIPELINE_AUDIT 신설)

---

2026-08-18

Sprint 188 — Failure Recovery 감사: 검색 API 오류가 로그에 원인을 안 남기던 결함

- **[결함 수정] BUGS #118** BUGS #117을 서버 로그로 재확인하려다 발견 — `api/v1/search.py`의
  `search()`/`get_regions()`가 `except Exception as e: raise HTTPException(...) from e`로
  곧바로 바꿔 던져, FastAPI가 트레이스백을 안 찍는 바람에 진짜 원인이 로그 어디에도
  안 남았다. `api/v1/payments.py`는 같은 자리에서 이미 `logger.exception()`을 쓰고
  있어 라우터마다 관례가 갈려 있었다. 두 핸들러에 `logger.exception(...)` 추가(응답은
  불변).
- **[회귀]** 신규 `test_error_logging.py` — 실제 HTTP 요청으로 재현(응답 불변 + 로그에
  원인 노출 확인, `git stash`로 결함 재현해 검사가 실제로 FAIL하는 것도 확인) +
  `api/` 전체를 AST로 훑어 같은 패턴(로그 없이 `except Exception` -> `HTTPException`)이
  다른 곳에 없는지 전수 검색(목록 의존 없음 — 새 라우터가 같은 실수를 해도 잡힌다).
- **[전수 검색 결과]** `api/` 전체에서 이 패턴은 2곳(둘 다 `search.py`)뿐이었다 —
  `admin.py`/`favorites.py`/`registry.py`/`search_presets.py` 등의 `except Exception:`은
  전부 `raise`(원본 예외를 그대로 다시 던짐, FastAPI 기본 핸들러가 로그를 남김)라 대상이
  아니었다.
- TODO/FIXME/HACK 전수 검색 — 신규 결함 없음(기존에 이미 roadmap/BETA_RELEASE_CHECKLIST에
  등록된 2건뿐: 검색 면적/특수조건 필터 API 미지원, 둘 다 스키마 변경이라 승인 영역).
- 부수적으로: `crawler/doc_crawler.py`의 기존 PDF 파일 396개를 매직바이트로 전수
  재검사(BUGS #116 회귀와 별개로 디스크 실측) — 손상/오탐 0건, 소급 정리 불필요.
- **[결함 수정] BUGS #119** 위 회귀를 재실행하다 `test_document_queue.py`/
  `test_pipeline_integrity.py`가 **전날엔 PASS였는데 새로 FAIL**했다 — 제품 결함이
  아니라 실 `auction.db`가 하루 사이 바뀐 것(매일 도는 `enqueue_documents()`가 쌓아
  온 `document_queue.doc_type='image'`가 처음 이 두 검사의 **하드코딩 목록**과
  부딪힘). `test_pipeline_integrity.py`는 `storage.database.QUEUE_TO_DOC_STATUS_TYPE`
  (단일 소스)을 참조하도록, `test_document_queue.py`는 버튼이 구조적으로 없는
  `image`를 이유와 함께 명시적으로 제외하도록 고쳤다 — 정상 상태를 결함으로
  오판하던 것을 바로잡았을 뿐, 제품 코드는 변경하지 않았다.
- 운영 `auction.db`/스케줄러 변경 0건 (`enqueue_documents()`가 매일 03:00에 넣는
  `image` 큐 행은 이 세션이 만든 게 아니라 Sprint 144부터 있던 정상 동작이다).

문서 동기화 (BUGS / TEST_PLAN)

---

2026-08-18 (Sprint 189) — 변경 기반 재수집 (Change-driven Refresh)

**기능**
- `storage/database.py`: 큐 상태 어휘 확장(`refresh` / `in_progress_refresh`)과
  `requeue_changed_documents()` / `doc_types_for_changed_fields()` 신설.
  스키마 변경 없음(TEXT + CHECK 없는 컬럼의 값 추가).
- `migrate_execute.py`: Sprint 185의 필드 단위 변경 **관측**을 **행동**으로 연결 —
  바뀐 물건을 커밋 뒤 `requeue_changed_documents()`에 넘긴다.
  `DOJOONPASS_REFRESH_ON_CHANGE=0`으로 끌 수 있다(기본 켬).
  재수집 예약 실패가 이미 성공한 매일 크롤링을 exit 1로 만들지 않도록 격리.
- `doc_worker.py`: `claim_next_queue_item()`이 계산한 `overwrite`를
  `collect_document(..., overwrite=)`로 전달. 재수집일 때는 **형제 물건 복사 지름길을
  쓰지 않는다**(형제 사본도 같은 옛 수집분이라 재수집의 의미가 없어진다).
- `claim_next_queue_item()` / `mark_queue_failed()` / `reset_stale_queue()` /
  `refresh_queue_priority()`가 새 어휘를 일관되게 다룬다 — 특히 재시도와 stale 회수가
  재수집 의도를 **각자 제자리로** 되돌린다.
- `api/v1/doc_stats.py`: `queue_refresh` 필드 추가, 큐 상태 문자열 하드코딩 제거
  (단일 소스 참조). `queue_in_progress`는 두 진행 상태의 합.
- `measure_endless_collecting.py`: 하드코딩 집합(존재하지 않는 `"processing"`을 세고
  새 어휘를 못 세던 것)을 `QUEUE_ACTIVE_STATUSES` 참조로 교체.

**버그 수정**
- BUGS #120 — 사진 형식 변경 시 옛 확장자 파일이 고아로 남고 지문 공식이 갈라져
  **이후 매 수집이 거짓 개정**이 되던 결함. `_remove_other_ext_for_seq()` 신설 +
  `_existing_set_hash()`가 중복 순번에서 비교를 포기하도록 이중 방어.
- BUGS #121 — 기존 PDF 덮어쓰기가 Windows에서 `shutil.move()`의 조용한 copy2 폴백으로
  **비원자적**이 되던 결함. `crawler/doc_crawler.py:move_into_place()` 신설.
- BUGS #122 — 재수집 최종 실패가 이미 READY인 문서를 FAILED로 뒤집던 결함
  (이번 Sprint가 도입할 뻔한 것). `DOC_STATUS_HAS_ARTIFACT` 판정으로 차단.

**문서**
- BUGS #117 해결로 정정(마이그레이션 020은 2026-08-17T09:03:19에 적용됨, API 200 실측).
- BUGS #123 신규 — **이 저장소를 가리키는 예약 작업이 0개다**(Release Blocker,
  승인 필요). Sprint 187의 "DOJOONPASS_DAILY 정상 동작 중" 기록을 실측으로 정정.

**테스트**
- 신규 `test_refresh_trigger.py` (12절 74검사).
- `test_asset_pipeline.py` +13검사(5-D 형식 교체 / 5-E 중복 순번 / 7-B(5) 사진 추가).
- `test_doc_storage_atomicity.py` +8검사(7d 원자적 덮어쓰기 / 7e AST 전수 가드).
- `test_doc_worker_recovery.py` 대역 시그니처 정정(실물보다 좁아 TypeError를 냈다).
- 전체 40 PASSED / 0 FAILED (단언 4,649 -> 5,038). 프런트 113/113, tsc 0, eslint 0.


---

2026-08-18 (Sprint 189 이어서) — 재수집 정확도/비용 하드닝

**버그 수정**
- BUGS #124 — `status.json` 전체를 해싱해 **수집 시각(`extracted_at`)이 지문을 매번
  바꾸던** 결함. 재수집을 켜면 `document_version_log`가 거짓 개정으로 차고
  `doc_raw.doc_version`이 매일 올랐을 것이다. `_fields_hash()` /
  `status_content_hash()` 신설로 **내용**만 해싱하고, 디스크 쪽·수집 쪽·형제 재사용
  경로가 전부 같은 공식을 쓴다.
- BUGS #125 — 내용 무변경 재수집이 파일을 다시 써 **mtime -> ETag -> 브라우저 캐시**를
  통째로 무효화하던 결함. 사진/status/PDF 세 경로 모두 "바이트 지문이 같으면 쓰지
  않는다"로 바꿨다(`_same_bytes_on_disk`, `_write_text_if_changed`, PDF 조기 반환).
- BUGS #126 — `test_doc_storage_atomicity.py`의 cleanup이 자기 디렉터리에는
  `_force_rmtree()`를 안 써서, 한 번 실패하면 잔해가 남아 **이후 모든 실행이 실패**하던
  테스트 위생 결함(실측 6벌 누적). 두 호출 지점을 하나로 합쳤다.

**테스트**
- `test_asset_pipeline.py` 5-F(재수집 캐시 보존, 대조군 포함).
- `test_doc_storage_atomicity.py` 7f(지문이 수집 시각에 안 흔들린다) /
  7g(텍스트 무변경 미기록) / 7h(같은 PDF는 목적지 무변경, 대조군 포함).
- `test_doc_storage_atomicity.py`의 소스 순서 검사가 구현 세부(`html_tmp = html_path`)를
  찾고 있어 리팩터링에 부러졌다 — 함수 이름 기준으로 바꿔 불변식만 남겼다.
- 전체 40 PASSED / 0 FAILED, 단언 5,084개. 연속 2회 동일.


---

2026-08-18 (Sprint 190) — 매일 갱신 체인 실측 감사

**실측**
- 라이브 크롤 프로브(한 법원, DB 미기록): 9건 수집 / 검증 100% PASS / 핵심 필드 전부
  채워짐 — **크롤러가 아직 법원 원천을 읽는다**. 데이터 공급 중단의 원인이 오직
  예약 작업 미등록(BUGS #123)임을 확정.
- 전체 크롤 소요 추정 3.1시간(1곳 186초 x 60곳). 법원 변경 -> 문서 반영 지연 약 17시간.
- `claim_next_queue_item()`: 어휘 확장(`=` -> `IN 2값`) 전후 **0.30 ms 동일**, 계획 동일.
- `requeue_changed_documents()`: 최악(300물건 x 4종 = UPDATE 2,400회) **0.005초**.

**수정**
- `docs/BETA_RELEASE_CHECKLIST.md` 43행의 셸 이스케이프 파손 복구
  (`` `.<개행>egister_scheduler_tasks.ps1` `` -> 정상). 추적 파일 315개 전수 검색, 잔여 0건.
- 문서 드리프트 정정 4건(스케줄러 상태 2건, BUGS #117 해결, 체크리스트 P0-C 해결).

**신규 문서**
- `docs/SPRINT190_REFRESH_CHAIN_AUDIT.md`


**Sprint 190 추가** — `test_schema_hygiene.py`에 이스케이프 파손 전수 가드 신설(2검사,
추적 텍스트 315개). 변이 주입으로 헛돌지 않음을 확인한 뒤 복원.
전체 40 PASSED / 0 FAILED, 단언 **5,086개**.


**Sprint 190 추가 2** — 실제 브라우저로 재수집 1건 완주(스크래치 DB + 스크래치 문서 루트):
큐 refresh -> done, 내용 무변경 판정, `document_version_log` 0->0, `doc_raw` 556->556,
파일 미기록. 실 데이터 무변경 확인. 회귀 2절 추가(`enqueue` 가 refresh 를 안 덮는다 /
doc-stats 집계 실호출) + `test_api_regression.py` 의 큐 집계 검사를 단일 소스로 정정
(새 어휘를 조용히 흘리던 잠재 오통과). 전체 40 PASSED / 0 FAILED, 단언 **5,145개**.


**Sprint 190 추가 3** — 사진 재수집을 실제 브라우저로 완주(스크래치 격리):
5장 무변경 -> 파일 미기록·mtime 보존, `version_log` 0->0, `auction_image` 5->5.
그 실행에서 **완료 로그가 거짓**(한 장도 안 썼는데 "5장 저장 완료")임을 발견해 정정하고,
`written`/`unchanged` 를 반환값에 담아 로그 파싱 없이 검증되게 했다.
전체 40 PASSED / 0 FAILED, 단언 **5,148개**.


---

2026-08-18 (Sprint 191) — 자산 3근거 불변식 + 큐 경쟁 정직성

**버그 수정**
- BUGS #127 — 법원이 사진 수를 줄여도 **파일이 안 지워져** 지문 공식이 영구히 갈라지던
  결함(#120과 같은 실패 방식). `_remove_files_not_in()` 신설(부분 수집 보호 포함) +
  `save_auction_images()`의 행 삭제를 `seq > max_seq` -> **집합 차집합**으로
  (가운데 순번이 빠지는 경우를 `>` 비교가 못 잡았다).
- BUGS #128 — 법원이 사진을 **전부** 내려도 옛 사진이 영원히 노출되던 결함.
  `clear_images_if_absence_confirmed()` 신설, **두 번 연속 확인** 후에만 정리
  (새 컬럼 없이 `document_status`가 1회차를 기억).
  `crawler/image_assets.py:remove_stored_image_files()` 신설(DB -> 파일 순서 보장).
- BUGS #129 — 문서 **완료 기준(json)과 서빙 대상(html)이 서로 다른 파일**이던 결함.
  `DOC_REQUIRED_FILES` 신설, `doc_exists()`가 필요한 파일 전부를 본다.
- BUGS #130 — 큐 경쟁에서 진 것을 "큐 비었음"으로 오해해 워커 실행이 조기 종료되던 결함.
  `CLAIM_RACE_MAX_ATTEMPTS = 5`, `None`은 진짜로 가져갈 것이 없을 때만.

**테스트**
- `test_asset_pipeline.py` 5-G(12) / 5-H(13) / **5-I 세 근거 불변식**(시나리오 8종, 25)
- `test_doc_storage_atomicity.py` 7i 완료기준==서빙대상 구조적 가드(9)
- `test_refresh_trigger.py` §15 동시 claim 정직성(스레드 12개, 8)
- `test_asset_pipeline.py` §11 — 옛 semantics를 굳히던 검사를 정정
- 전체 40 PASSED / 0 FAILED, 단언 **5,359개**. 신규 가드 2종 전부 변이 확인.


---

2026-08-18 (Sprint 192) — 삭제 경로 봉쇄 + 변경 감지 커버리지 증명

**버그 수정**
- BUGS #131 — `remove_stored_image_files()` 가 DB 값(`storage_path`)으로 파일을 지우면서
  경로 탈출 봉쇄가 없던 결함. 서빙 쪽에는 이미 있던 방어가 **삭제 쪽에만** 빠져 있었다.
  `crawler/image_assets.py:is_inside_document_root()` 신설.

**테스트**
- `test_asset_pipeline.py` 18-B — 봉쇄 판정 + 실제 삭제 동작 + **삭제 지점 AST 전수**(12검사).
  변이 확인 완료(봉쇄 무력화 시 바깥 파일이 실제로 지워지며 3건 FAIL).
- `test_refresh_trigger.py` §16 — 사용자에게 보이는 **변동 필드가 전부 관측되거나
  파생**임을 구조적으로 증명(16검사). 유찰횟수/낙찰가율이 관측 목록에 없는 이유를
  코드로 고정한다.
- 전체 40 PASSED / 0 FAILED, 단언 **5,387개**.


**Sprint 192 추가** — `audit_asset_integrity.py` 신설(읽기 전용 자산 무결성 감사,
종료 코드 0/1/2, `--selftest` 포함). 실 DB 전수 감사 결과 **5개 항목 전부 GREEN**
(사진 45행·문서 556건·doc_raw 556행·큐↔상태 모두 일치).
BUGS #129 로 엄격해진 STATUS 완료 기준(html+json)에서도 기존 READY 556건이 전부 통과.
`git add audit_asset_integrity.py` 는 승인 영역이라 SKIP — 그때까지 회귀 스위트는
이 파일을 참조하지 않는다(미추적 import 금지 규칙, BUGS #105).


---

2026-08-18 (Sprint 193) — 운영 데이터 무결성 감사

**신규**
- `audit_asset_integrity.py` 를 일곱 검사로 완성(양방향: DB->파일, 파일->DB, 큐->물건).
  읽기 전용, 종료 코드 0/1/2, `--selftest` 로 감사기 자체를 검증.
- `docs/SPRINT193_ASSET_INTEGRITY_AUDIT.md`

**실측**
- [1]~[5] GREEN. BUGS #129 로 좁힌 STATUS 완료 기준에서도 기존 READY 556건 전부 통과.
- [6] 대응 물건 없는 문서 디렉터리 1개 / [7] 고아 큐 18행 — 같은 사건번호가 두 법원에
  존재하던 잔재(BUGS #14/#18/#103/#107 계열). 새로 생기지 않으며 사용자 피해 없음.
  정리는 `cleanup_orphans_dryrun.py`(승인 영역).

**감사기 자체의 결함 3건을 만들고 즉시 잡았다**
- 추적 파일 -> 미추적 파일 import (`test_schema_hygiene.py` 가 검출, 의존 제거로 해결)
- `DB_PATH` 스냅숏 복사 (자체 검사가 실 DB 를 읽고 있었다)
- 경로 정규화 누락으로 거짓 경보 36건 (37 -> 1)


---

2026-08-18 (Sprint 194) — 매일 크롤 동시 실행 방지

**버그 수정**
- BUGS #132 — `mvp_scraper.py` 에 동시 실행 방지가 없던 결함(`logs/checkpoint.json`
  덮어쓰기 + 법원 서버 이중 크롤). `storage/checkpoint.py` 에 `RunLock` 을 두고
  `doc_worker.py` 의 인라인 구현을 그것으로 교체(동작 불변, 기존 회귀가 보증) 후
  `mvp_scraper.py` 에 적용.

**테스트**
- `test_doc_worker_recovery.py` §9 `RunLock` 원시 계약(7) / §10 두 배치가 같은 구현을
  쓰는지 구조적 확인(10) / §11 `mvp_scraper.main()` 락 흐름 실동작(8).
- 전체 40 PASSED / 0 FAILED, 단언 **5,404개**.


---

2026-08-18 (Sprint 195/196) — 가드 사각지대 + 재수집 처리량 근거

**버그 수정**
- BUGS #133 — AST 전수 가드 2개가 `encoding="utf-8"` + `except SyntaxError: continue` 로
  **BOM 파일 16개를 조용히 건너뛰던** 결함. `utf-8-sig` 로 고치고, 못 판 파일이 있으면
  단언으로 드러나게 했다. 삭제 지점 집계 8곳 -> **12곳**으로 정정.
- BUGS #134 — `REFRESH_MAX_ITEMS_PER_RUN` 300 -> **60**(실측 근거).
  `config/settings.py` 에 `DOC_WORKER_START_TIME` / `DOC_COLLECT_SECONDS_PER_ROW` 신설.

**실측**
- 재수집 상한: 창 7,200초 / 옛 값 최악 28,800초(400%) / 새 값 최악 5,760초(80%).
- 이미지 트리거: CSV 25개 diff, 공통 4,455건에서 감시 필드 변경 **0건**.
  원인은 `MAX_ITEMS=10` 로 인한 슬라이스 교체(이탈 163 / 신규 158).

**테스트**
- `test_refresh_trigger.py` §17 상한 산술 불변식(6검사).
- `test_asset_pipeline.py` 18-B / `test_doc_storage_atomicity.py` 7e 에
  "스캔 범위를 전부 읽고 팠다" 단언 추가.
- 전체 40 PASSED / 0 FAILED, 단언 **5,419**. 변이 검증 3건 전부 FAIL 확인 후 복원.


**Sprint 197 실측** — doc_worker 이동 비용 63%(물건 단위 묶기 시 47% 절감 여지, 미착수) /
`image` 큐 행 0개는 마지막 enqueue(08-12)가 image 추가(08-17)보다 앞선 시간 순서 문제이며
코드 결함 아님 / 문서의 "원래 없음"은 신뢰할 positive signal 이 없어 **새 상태를 만들지 않음**.


---

2026-08-18 (Sprint 198/199) — 관측 설계 정정 + 묶기 실증

**정정**
- Sprint 196 의 "변경 사실상 없음" 결론을 **실측으로 정정**. 연속 스냅숏 0건은
  **관측 공백**이었고, 물건별 처음<->마지막으로 재니 **44물건 132건 변경**
  (저감률 0.7/0.8 = 한국 경매 법정 저감률과 일치). 문서 재수집은 실제로 발동하며
  하루 약 3행(창의 1%). 사진 재수집만 발동하지 않는다(감정가 0/1,228).
- 관련 문서(`SPRINT195...md`, `CURRENT_STATE.md`)에 정정 표시 삽입(원문 보존).

**실증**
- 물건 단위 묶기 **가능**을 호출 그래프 + 실브라우저로 확인(이동 1회 뒤 두 번째 종류
  정상 수집, 창/URL 보존). 사진 수집 비용은 **0.0초** — 전부 이동 비용이다.
- 실브라우저 실행에서 **실재하는 spec 이 타임아웃 실패** — "수집 실패 != 원래 없음"의
  직접 증거이자 BUGS #122 방어의 필요성 실증.

**신규 문서**
- `docs/SPRINT198_TRIGGER_OBSERVABILITY_CORRECTION.md`
- `docs/SPRINT199_BATCHING_FEASIBILITY.md`


**Sprint 200** — `test_refresh_trigger.py` §18 배선 가드 신설(능력 19개가 실제로
정의·호출되는지 AST 확인, 진입점은 `run_*.bat` 에서 유도). 작성 중 스캔 범위가 좁아
`refresh_queue_priority` 를 거짓 경보로 잡은 것을 발견해 진입점 유도 방식으로 정정.
변이 검증: `overwrite=overwrite` 제거 시 3건 FAIL. 단언 5,419 -> **5,426**.


---

2026-08-18 (Sprint 201) — 받아 놓고 버린 문서

**버그 수정**
- BUGS #135 — `collect_appraisal()` 이 새 탭을 성공 조건으로 삼아, **실제로 내려온 PDF 를
  확인조차 하지 않고 버리던** 결함. `plugins.always_open_pdf_externally` 때문에
  다운로드가 성공할수록 탭이 안 생기는 구조였다. 탭이 없으면 다운로드 도착 여부로
  판단하도록 고쳤다(더하기만 하는 변경). **실환경에서 success=False -> True 확인.**

**탐지 추가**
- BUGS #136 — 명세서 다운로드 고아(원인 미확정). `audit_asset_integrity.py` [8] 신설.
  실측 고아 8개 / 14.0MB (감정평가서 3 + 명세서 5).

**테스트**
- `test_doc_storage_atomicity.py` 7j — 탭을 만들지 않는 가짜 드라이버로 3경우 고정(9검사).
  대역이 실물보다 좁아 한 번 막힌 것(`default_content`/iframe `src`)도 함께 넓혔다.
- 전체 40 PASSED / 0 FAILED, 단언 **5,463**.

**실측**
- 묶기 4종 확장: 절감 **44%**(19.1 + 53.5 = 72.6초 vs 129.7초). 미착수 유지.


---

2026-08-18 (Sprint 202) — #135 계열 전수검색

**버그 수정**
- BUGS #136 — `collect_spec()` 도 탭을 성공 조건으로 삼아 도착한 PDF 를 버리던 결함
  (#135 와 동일 모양). 탭이 없으면 다운로드 도착을 확인하고, 왔으면 뷰어 단계를
  건너뛰고 저장한다. 뷰어 경로는 대조군으로 회귀에 고정.
- BUGS #137 — `wait_for_download` 호출부 가드가 `else:`/`finally:` 를 안 보던 결함.
  `body` 만 훑던 것을 `body`/`orelse`/`finalbody` 전부로 확장.

**테스트**
- `test_doc_storage_atomicity.py` 7k(8검사) + §9 가드 확장.
- `test_schema_hygiene.py` 27 신설 - CRLF 로 커밋된 파일을 LF 로 다시 쓰지 않는지.
- 전체 40 PASSED / 0 FAILED, 단언 **5,473**. Frontend 113/113, tsc 0, eslint 0.


---

2026-08-18 (Sprint 203) - 검색 필터 dependency 감사

**감사 (구현 없음)**
- 면적 필터: 데이터는 `full_address` 대괄호에 **이미 있다**(1,852/1,876 = 98.7%).
  막고 있는 것은 의미 정의(제품 결정). 파싱 함정 5종 실측.
- 특수조건 필터: 소스는 법원 목록 **셀5**. `collect_list_items()` 가 읽지 않는다.
  재크롤 3.1시간 + 분류 사전(제품 결정)이 필요하다.
- `crawl_detail()` 의 `property_list`/`schedule`/`nearby_cases` 는 수집만 하고
  **아무도 읽지 않는다**(`normalize_item()` 이 21필드만 통과).

**가드 추가**
- `test_normalizer.py` - 주소 끝 대괄호 보존(면적의 유일한 소재지). 사례 4 x 검사 3.
  변이 2종 확인(대괄호 제거 8 FAIL / 지번 오염 3 FAIL).

**테스트**
- 전체 40 PASSED / 0 FAILED, 단언 **5,485**.

**러너**
- `run_python_tests.py` - 실패/시간초과 파일의 마지막 12줄을 `-v` 없이도 즉시 출력.
  간헐 실패의 증거를 놓치지 않기 위해서다(BUGS #139).


---

2026-08-18 (Sprint 204) - 예약 실행 등록 후 검증

**신설**
- `audit_schedule_health.py` (읽기 전용) - 등록/마지막 실행/저장소 흔적 세 축을 대조해
  **어긋나는 지점을 지목**한다. `--selftest` 9검사 포함. 미추적(= git add 승인 필요).

**가드 추가**
- `test_schema_hygiene.py` 14-B - DOC_WORKER_START_TIME vs 등록 스크립트 시각,
  우선순위/문서수집 실행 순서, ExecutionTimeLimit vs worker 실행 창. 전부 변이 검증.

**문서 정정**
- `docs/BETA_RELEASE_CHECKLIST.md` - Sprint 187의 "DOJOONPASS_DAILY 정상 동작 중"
  문단에 재정정 표시(원문 보존). 오늘 세 축 실측이 전부 반대다.

**자기 결함**
- 새 감사기가 첫 실행에서 249개를 0개로 읽었다(`schtasks /v` 헤더 위치 오독).
  파싱을 분리해 픽스처로 고정하고, 못 뽑으면 0개가 아니라 조회 실패로 돌려준다.


---

2026-08-18 (Sprint 205) - 공허한 가드 전수 감사

**가드 보강**
- `test_auction_identity.py` 법원 스코프 SQL 스캔 - 하한 추가(파일 40개 / 쓰기문 8개).
  실측 86개 / 15개. 변이(열거를 2개로 자름) -> FAIL 2건.
- `test_schema_hygiene.py` .ps1 BOM 스캔 - 하한 추가(비ASCII .ps1 1개 이상).
  변이(열거를 비움) -> FAIL 1건.

**감사 결과**
- 테스트 44개에서 "비었음" 단언 115개 -> 스캔 기반만 4개 -> 실제 결함 2개.
  나머지 2개는 오탐 1(이미 `bool()` 하한 있음) / 하한 불가 1(작업트리가 깨끗하면 0이 정답).
- 탐지기 자신이 `check_true(..., bool(X), ...)` 형태를 하한으로 못 알아봤다(기록함).

**확인만 한 것**
- `migrate_execute.refresh_on_change_enabled()` 기본값 ON(미설정 = 켬)이고,
  사용자/머신 환경변수 어디에도 `DOJOONPASS_REFRESH_ON_CHANGE` 가 설정돼 있지 않다.
  즉 스케줄러 등록만 되면 변경 기반 재수집은 **별도 설정 없이 발동한다**.


---

2026-08-18 (Sprint 206) - 낡은 미구현 주장 감사

**정정**
- `src/app/search/types.ts` - "DB에 대응 컬럼/데이터가 없어"는 절반만 사실.
  데이터는 `full_address` 대괄호에 98.7% 있다(Sprint 203 실측). 실제 장애물은 의미 정의.

**확인만 한 것 (전부 여전히 참)**
- 프로덕션 소스 196개 중 미완/미지원 표시 22건 - 살아 있는 거짓 주장은 위 1건뿐.
- `api/v1/item.py` 썸네일 미구현(Pillow 부재 확인), `payment_providers.py` PG 미연동,
  `SearchForm.tsx` TODO 3건 + "준비 중" 2건.
- `storage/migrations/014_*.sql` 의 낡은 주장은 **적용된 마이그레이션이라 고치지 않는다**
  (살아 있는 코드에 이미 정정이 있다).


---

2026-08-18 (Sprint 207) - 의존성 권고 재실측

**정정**
- `KNOWN_SAFE_MIN_NEXT_VERSION` 16.2.11 -> **16.3.1**. 취약 범위가
  `16.3.0-preview.10` 까지 넓어져 옛 안전선으로 올리면 8건이 남는다(npm audit 실측).

**가드 추가**
- `test_schema_hygiene.py` 8-B - 권고가 걸린 패키지 7개의 설치본이 스냅샷보다
  낮아지면 실패(오프라인, package-lock.json 기준). 변이 2종 확인.

**문서**
- `docs/BETA_RELEASE_CHECKLIST.md` P1 신설 - 권고 7건 표(등급/설치본/내용)와
  `next@16.3.1` 이 메이저가 아니며 postcss/sharp 도 함께 정리된다는 사실.

**SKIP(승인)**: `npm install next@16.3.1` 등 의존성 업그레이드.


---

2026-08-18 (Sprint 208) - 이미지 체인 관통 조사

**버그 수정**
- BUGS #140 - `doc_worker` 가 사진을 적기 전에 성공을 먼저 기록하던 순서 결함.
  실체(`auction_image`)를 먼저, 성공(`mark_queue_done`)을 나중에.
- BUGS #141 - `_images_status()` 가 "READY인데 0장"을 그대로 전달하던 결함.
  READY 만 COLLECTING 으로 낮춘다(NO_IMAGE/FAILED 는 유지).

**테스트**
- `test_asset_pipeline.py` 12-F 신설 + 17 확장. 변이 2종 확인.

**실측**
- `appraisal_price` 변경 **0/1,228 (0.0%)** - image 재수집 트리거의 실제 발동 가능 횟수.
  나머지 3필드는 각 44건(3.6%).
- 사본 실증: `enqueue_documents(rows)` -> image 10행 생성. 큐 0행은 시점 문제다.


---

2026-08-18 (Sprint 209) - 문서 증거 정합성 감사

**정정**
- "전체 크롤 3.1시간"의 증거 등급을 **실측 -> 파생**으로 고침(4곳).
  원 측정은 서울중앙 1곳 9건 186.2초이고, `MAX_ITEMS=10` 전제 위에서만 곱셈이 성립한다.
- `docs/SPRINT190_*` 에 파생 전제를 명시(확인된 것 / 확인 안 된 것 구분).
- `docs/SPRINT203_*` - "재크롤 3.1시간"은 틀렸다. 기일이 지난 1,867건은
  **소급 불가**이고 1회 실행 상한은 600건이다. 정정 마커로 원문 보존.
- `docs/SPRINT199_*` - 4종 주장은 그 시점에 **외삽**이었음을 표시하고
  Sprint 201 의 4종 실측으로 전방 참조.

**방법 기록**
- 강한 단정 정규식은 245건(대부분 규칙 문장)을 내 쓸모가 없었다.
  "결정에 쓰이는 수치 주장"으로 좁혀야 실제 결함 3건이 드러났다.


---

2026-08-18 (Sprint 210) - 재수집 의도 보존

**버그 수정**
- BUGS #142 - 재시도 소진 뒤 `reset_stale_queue()` 가 무조건 `pending` 으로 되돌려
  재수집 의도가 사라지던 결함. 실체(READY)가 있는 행은 `refresh` 로 되돌린다.
  상태 어휘는 늘리지 않았다.

**계약 변경**
- `test_document_status_sync.py` 9-(2) 기대값 `pending` -> `refresh`.
  회귀가 아니라 의도된 변경이며 사유를 그 자리에 기록했다.

**테스트**
- `test_refresh_trigger.py` 20 신설(4검사). 변이 -> FAIL 2건.
- 전체 40 PASSED / 0 FAILED, 단언 **5,553**.


---

2026-08-18 (Sprint 211) - 낡은 "도달 불가" 주장 정정

**정정 (4곳)**
- `api/http_cache.py` / `docs/SPRINT145_*` / `docs/SPRINT146_*` / `docs/roadmap.md`
  — `document_version_log` 는 Sprint 189 이후 **도달 가능**하다. 0행인 이유는
  "경로 없음"이 아니라 "아직 안 돌았음"(예약 작업 0개).

**가드 추가**
- `test_schema_hygiene.py` 28 — 정정 없이 살아 있는 "도달 불가" 주장 검출.
  취소선 이력은 인정, 스캐너 자기 파일은 제외, 하한/대조군 포함.
- ★ 이 가드가 처음에 **공허했다**("정정"이라는 흔한 단어를 인정 조건에 넣어
  마커를 지워도 통과). 조건을 좁히자 낡은 주장 2건이 더 드러났다. 변이 2종 재검증.


---

2026-08-18 (Sprint 212) - 문서 계열 확인 + 감사기 출력 구분

**확인만 한 것 (결함 없음)**
- 문서에는 사진의 순서 결함이 없다 — `_record_doc_raw()` 가 `mark_queue_done()`
  트랜잭션 안이라 원자적. 실측 READY 556 / doc_raw 없음 0 / 파일 없음 0.
- 그래서 `_document_entry()` 에 두 번째 방어선을 넣지 않았다(어긋나는 행 0).

**도구 수정**
- `audit_asset_integrity.py` — `--selftest` 가 심은 결함의 감사 출력에
  `[selftest 가짜DB]` 접두사. 실제 감사 출력과 구분되지 않아
  **selftest 결과를 운영 실측으로 오독한 사고**가 실제로 있었다.


---

2026-08-18 (Sprint 213) - 죽은 코드 전수 조사

**감사 (구현 없음)**
- 진입점 유도(`run_*.bat` + `api_server.py` + 회귀 실행기 + 추적 테스트) -> import 그래프.
  프로덕션 82개 중 도달하지 않는 것 22개. **새 죽은 코드 0건** —
  20개는 의도된 수동 스크립트, 2개는 이미 기록된 `filter/` 잔재(삭제는 승인).
- 도구 자기 결함: `__init__.py` 를 도달 불가로 오판(31 -> 22로 정정).

**문서 정밀화**
- `docs/CLAUDE.md` — `filter_engine.py` "80% 커버리지"는 실행률이며,
  `test_filter.py` 에 단언이 없어(NO-VERDICT) 세 모듈 모두 미검증임을 명시.


---

2026-08-18 (Sprint 214) - 성공판정 A~F 관통

**버그 수정**
- BUGS #143 - 기록이 0장/0행이어도 큐가 done 으로 끝나던 결함.
  사진은 `saved>0`, 문서는 `files_saved` 실재를 성공 판정에 쓴다.
  범위는 좁게(스킵 경로/부분 성공 계약은 건드리지 않는다).

**테스트**
- `test_asset_pipeline.py` 12-G(A~F x 기존asset 2벌) / 12-H(문서 3경우).
- 변이 3종 전부 FAIL 확인. 전체 40 PASSED / 0 FAILED, 단언 **5,883**.


---

2026-08-18 (Sprint 215) - 이미지 전 구간 관통 fixture

**테스트**
- `test_refresh_trigger.py` 21 신설 - 원천 변경부터 API 응답까지 8단계를 실함수로 잇는다
  (대역은 브라우저 한 곳). `document_version_log` 1행까지 확인.
- 전체 40 PASSED / 0 FAILED, 단언 **5,918**.


---

2026-08-18 (Sprint 216) - Cache/성능 확인 + 트리거 매핑 고정

**확인만 한 것**
- Cache: `not_modified()` 가 문서/사진 두 라우트에서 실제 호출됨(HEAD 는 GET 위임).
- 성능: `reset_stale_queue()` 2,753행 회수에 **0.034초**(사본 측정, 원본 무변경).

**가드 추가**
- `test_refresh_trigger.py` 1 — "사진으로 가는 길은 감정가 하나뿐"(실측 0.0%)을 단언.
  매핑 확대는 제품 결정이므로 조용히 바뀌지 않게 한다. 변이 -> FAIL 3건.


---

2026-08-19 (Sprint 217) - 스킵 경로의 실체 기록 (BUGS #144)

**버그 수정**
- BUGS #144 - `"이미 존재. 스킵"` 이 `files_saved=[]` 로 돌아와 `_record_doc_raw()` 가
  실체 기록을 통째로 건너뛰던 결함. 파일은 있는데 `doc_raw` 0행 / 큐 done / 화면 READY 가
  되고, **다음 수집도 같은 분기라 스스로 회복되지 않았다**(API 의 쪽수·크기·버전 영구 null).
- `crawler/doc_paths.existing_doc_files()` 신설 — `doc_exists()` 와 같은 목록·같은 기준.
  spec/status/appraisal 세 분기가 이미 가진 파일을 결과에 담는다. 파일은 다시 쓰지 않고
  (mtime 무변경), 개정 이력도 남기지 않는다.
- 사진 쪽은 같은 자리를 처음부터 복구하고 있었다(`_describe_existing()`). 문서만 없던 칸이다.

**테스트 자체의 결함 2건 수정**
- `test_asset_pipeline.py` / `test_collect_documents.py` 가 "다시 쓰지 않는다"의 증거로
  `files_saved == []` 를 썼다 — **결함을 오히려 고정하고 있었다.** 의도는 그대로 두고
  증거를 파일 mtime/크기 무변경으로 바꿨다.

**테스트/가드 추가**
- `test_asset_pipeline.py` 12-I — 스킵 경로가 실체를 기록한다(3종 문서 x 2회 실행 + API).
- `test_asset_pipeline.py` 12-J — 큐 성공기록 실패 -> 재시도 간격 -> 재시도 성공.
  (실체 보존 / 거짓 READY 없음 / 중복 행 없음 / 고아 파일 없음 / 거짓 개정 없음)
- `test_false_success.py` 5 — **구조 검사**: 수집기가 `success=True` 를 쓰는 10곳 전부가
  같은 분기에서 `files_saved`/`images`/`no_asset` 중 하나를 함께 알리는가.
- 변이 6종 전부 검출(21 / 7 / 2 / 16 / 7건 FAIL + UNIQUE 위반 종료코드 1).
- 전체 40 PASSED / 0 FAILED / 3 SKIPPED / 1 NO-VERDICT, 단언 **6,075**.

**감사기 보강** (`audit_asset_integrity.py`, 읽기 전용)
- `[4-b]` READY 인데 `doc_raw` 행이 없다 — BUGS #144 의 모양. 기존 [3]/[4] 는 둘 다
  통과시킨다. 실 DB 실측 **0건**.
- `[2-b]` 사진 폴더의 이름 규칙 밖 파일(`.tmp` 잔재). `list_stored_images()` 가 조용히
  건너뛰므로 [1]/[2] 어디에도 안 보였다 — "없다"가 아니라 **"못 봤다"** 였다. 실측 **0건**.
- 둘 다 자체 검사(selftest)에 결함을 심어 잡히는 것을 확인.

**실측 (전부 사본/읽기 전용, 원본 무변경 확인)**
- `claim_next_queue_item()` p50 **3.02ms** / p95 3.38ms (큐 3,498행 · pending 2,753행)
- `save_auction_images()` 5장 p50 **2.52ms**
- `GET /api/v1/item/{id}` p50 **2.8ms** (사진 5 + 문서 3) — 자산이 없는 물건과 차이 없음
- 물건당 수집 비용은 브라우저 navigation 이 지배한다(약 22초). DB 비용은 그 0.03% 수준.
- 예약 작업 **0개**(249개 중), 기일이 내일 이후인 물건 **0건** — 2026-08-20부터 기본
  검색 0건이라는 예고가 유효하다. 등록은 승인 영역이라 하지 않았다.

**추가 (같은 스프린트, 실서버 확인 포함)**
- `collect_documents.py` 의 bare `except:` **4곳** 제거 — `BaseException` 까지 잡아
  Ctrl-C/SystemExit 를 삼켰다(그중 하나는 30초 대기 안이라 창이 넓었다).
  `api/v1/item.py` 가 같은 이유로 이미 고친 자리인데 규칙이 `api/` 밖으로 퍼지지 않았다.
- `test_error_logging.py` 4 신설 — 파이프라인 58개 파일 전수로 bare `except:` 를 막는다.
  파싱 실패도 `continue` 로 넘기지 않고 **결함으로 보고**한다. 하한(>=40파일) 포함.
  변이 2종(결함 재주입 / 열거 비우기) 전부 FAIL 확인.
- `test_error_logging.py` 의 "bare except 는 이 저장소에 없다"는 주석 정정 — **사실이
  아니었다.** 그 검사가 `api/` 만 훑어서 안 보였을 뿐이다.
- `audit_asset_integrity.py` `[9]` 신설 — **API 가 광고한 자산 URL 을 그대로 다시
  요청한다**(전수). 실측: 물건 206개 / 사진 URL 45개 / 문서 URL 556개 **전부 200**,
  `image_count`·`images_status` 불일치 0건. 서버가 없으면 "이상 없음"이 아니라
  **"확인하지 못함"** 으로 보고한다(가짜 서버로 두 경로를 따로 자체 검사).
- 실서버 조건부 캐시 실측 — 사진(70KB)/문서(406KB) 둘 다 `If-None-Match`,
  `If-Modified-Since` 에 **304 / 0바이트**. `Cache-Control` 부재는 의도된 결정
  (`api/http_cache.py`: 갱신 주기 근거가 없어 `max-age` 를 임의로 정하지 않는다).
- 프런트 계약 테스트를 **서버를 띄우고** 돌렸다 — 113/113 PASS, cancelled 0
  (서버 없이 돌리면 50개가 cancelled 로 빠진다. `pass 63` 을 통과로 읽으면 안 된다).
- `.bat` 의 `%errorlevel%` 확장이 블록 안에서 옳게 동작하는지 실제로 돌려 확인(7 출력).

**BUGS #145 — 동시 실행 잠금이 동시 실행을 막지 못했다**
- `RunLock.acquire()` 가 `exists()` 로 보고 `open("w")` 로 썼다. 실측: **스레드 8 x
  200라운드 전부에서 8개가 동시에 성공** — "몇 초 차이"만 막고 "같은 순간"은 하나도
  막지 못했다(하필 이 락이 막으려던 것이 후자다). `O_CREAT|O_EXCL` 로 바꿨다.
- 오래된 락 회수도 두 단계라 같은 문제가 있었다. **세 가지를 차례로 측정**했고
  중간 시도 둘이 실패한 기록을 그대로 남겼다:
  `os.remove` 4/1,000 -> mtime 재확인 추가해도 4/1,000 -> `os.rename` 중재 2/40 ->
  **회수 구역을 배타 토큰으로 감싸 1,000라운드 전부 정확히 하나.**
- `test_doc_worker_recovery.py` 11 신설 — 두 경우 각각 8스레드 x 40라운드,
  성공 수가 **정확히 1**(0도 결함이다). 토큰 잔재 0건도 함께 본다.
  변이 3종 전부 검출. 기존 §9 는 순서대로만 시험해 이 방향을 못 봤다.

**문서 정정**
- `docs/CLAUDE.md` "No test runner is configured" — `run_python_tests.py`(Sprint 146)가
  생긴 뒤에도 그대로였다. 실행법과 4상태 집계(SKIPPED/NO-VERDICT는 통과가 아니다)를 적었다.
- `doc_worker.py` / `test_doc_worker_recovery.py` 의 `storage/runlock.py` 언급 3곳 정정 —
  **그런 파일은 없다**(가드에 걸려 `storage/checkpoint.py` 로 옮긴 경위가 BUGS #132에 있다).

**감사 도구 자체 감사 (BUGS #146/#147)**
- #146 `test_schema_hygiene.py` 6-B 가 `utf-8` 로 읽어 **BOM 파일 31개의 1행 import 를
  못 봤다**(추적 .py 44개가 BOM). 커밋 시 API 부팅을 막는 P0-B 가드다. `utf-8-sig` 로
  고치고 스캐너를 분리해 탐침 파일로 직접 검증. 못 읽은 파일도 "미확인"으로 보고.
- #147 `run_python_tests.py` 에 자기 검사가 없었다. `test_runner_contract.py` 신설(33단언):
  종료코드 1순위 / NO-VERDICT / SKIPPED 구분 / 실제 실행 집계 / discover 범위와 그 맹점.
  변이 4종 전부 검출.
- `test_error_logging.py` — `except SyntaxError: continue` 제거(파싱 실패를 결함으로 보고),
  하드코딩 진입점 목록을 git 목록으로 교체(58 -> **86파일**, 28개가 검사 밖이었다).
  그 결과 드러난 bare `except:` 4곳(analyze_docs/analyze_hyunhwang/manual_test) 제거.
- `audit_schedule_health.py` — 칸 수가 어긋난 CSV 행을 조용히 버리던 것을 **보고**하도록.
  selftest 에 결함 주입 검사 추가.
- `test_asset_pipeline.py` Env — 문서 서빙 모듈의 `DOCUMENT_ROOT` 를 안 바꿔 뷰어가
  항상 404 였다. 루트를 들고 있는 모듈 4곳이 같은 값을 보는지 가드로 고정.
- 문서 부분 수집 계약 12-L 신설(큐 done + doc_exists False 라는 "스스로 끝나지 않는 상태").
- 실브라우저: `/search` 총 9건 / 대표 이미지 9장 전부 렌더링, 깨짐 0, 콘솔 오류 0.
  상세페이지는 `record_view()` 운영 쓰기 때문에 열지 않았다.
- 전체 **41 PASSED / 0 FAILED / 3 SKIPPED / 1 NO-VERDICT, 단언 6,205**.

**추가 (같은 스프린트, 2차)**
- `test_asset_pipeline.py` 12-M 신설 — 법원이 사진을 전부 내린 경우를 **doc_worker 로
  관통**(3회 실행). 5-H 는 저장소 함수만 직접 불렀고 호출부의 **순서**는 코드를 읽어서만
  알 수 있었다. 변이 2종: 정리 호출 제거 -> FAIL 6건, **순서를 뒤집으면 1회차에 사진을
  전부 지운다** -> FAIL 4건(가장 파괴적인 동작을 실제로 재현해 확인).
- `test_asset_pipeline.py` 19-B 보강 — `DOCUMENT_ROOT` 4곳 + `PROJECT_ROOT` **6곳**이
  같은 곳을 가리키는지. 식이 아니라 결과를 대조한다(모듈 깊이가 달라 식은 원래 다르다).
- `test_doc_worker_recovery.py` — 락 검사가 운영 `logs/` 에 흔적을 남기지 않도록
  `finally` + 안전망. 중단을 주입해 확인(종료코드 1 로 죽어도 락 없음).
  회수 토큰(`.reclaim`)도 함께 정리한다.
- 스위트 전체 실행 전후 파일 대조: **새 파일 0 / 사라진 파일 0**(로그 1개만 증가).
- 잠금 수정의 비용 실측(개선 전/후): "이미 잡힘" 경로 0.006 -> 0.093ms.
  **상대 15배지만 실행당 1회 호출이라 22초 대비 0.0000004%** — 숨기지 않고 기록.
- 전체 **41 PASSED / 0 FAILED / 3 SKIPPED / 1 NO-VERDICT, 단언 6,241**.


---

2026-08-19 (Sprint 218) - 검색목록 썸네일까지 하나의 기능으로 (BUGS #148)

**버그 수정**
- BUGS #148 — `save_auction_images()` 가 `size <= 0` 만 거절해 **서빙 계층이 404 로
  거절할 크기의 사진을 기록**했다. 241바이트로 재현: DB 1행 / API `image_count=1`,
  `images_status=READY` / 검색목록 썸네일 URL 제공 / **그 URL 은 404**.
  `MIN_IMAGE_BYTES` 를 같은 상수로 참조하도록 수정. 운영 영향 실측 **0건**
  (45행 최소 크기 35,746바이트).

**★ 픽스처가 결함을 가리고 있었다**
- 이 수정으로 기존 검사 **10건이 깨졌다.** 픽스처가 100~600바이트 사진으로
  "READY / 2행" 을 단언하고 있었는데 **그 크기는 한 장도 서빙될 수 없다.**
  `MIN_FIXTURE_PAD` 로 일괄 상향(3파일).

**테스트/가드 추가**
- 12-N 목록 썸네일 == 상세 대표 사진 — 두 화면이 **서로 다른 코드**로 대표를 고른다
  (`MIN(seq)` vs `images[0]`). 순번을 어긋나게 한 두 물건으로 ID 혼선·바이트 일치·
  파일 소실 시 목록 견고성까지 본다.
- 12-O 사진 교체가 목록에 반영되는가 — **크기가 같은 다른 사진**으로 교체해
  ETag 변경/200/새 바이트를 확인(크기만 보는 구현을 걸러낸다).
- 12-P 기록된 사진은 반드시 서빙될 수 있어야 한다(하한 미만/이상 대조군 + API + 목록).
- 12-Q 판정처 3곳이 **같은 상수**를 보는가 — AST 로 숫자 상수 대입과 단일 소스
  import 여부를 본다. ★ 문자열 포함만 보던 첫 버전은 변이를 놓쳤다.
- 변이 4종 전부 검출(11 / 2 / 6 / 4건 FAIL).

**실측**
- 검색목록 썸네일: 첫 방문 **0.91 MB**(장당 p50 4.1ms), 재방문 전부 **304 / 0바이트**
  — 조건부 캐시가 바이트를 **100%** 아낀다.
- 썸네일 한 장 평균 **약 101 KB** — 80x80 으로 그리는데 원본을 그대로 내려 준다.
  서버 측 썸네일 생성은 Pillow 의존성이라 승인 영역.

**확인했지만 고치지 않음**
- 검색목록은 "사진 없음"과 "수집 실패"를 구분하지 못한다(이미지 관련 키가
  `thumbnail_url` 하나뿐). 목록 상태 배지는 제품 결정.

- 전체 **41 PASSED / 0 FAILED / 3 SKIPPED / 1 NO-VERDICT, 단언 6,365**.


---

2026-08-19 (Sprint 219) - 큰글씨/접근성 감사 (실측, 화면 변경 없음)

**감사만 한다** — 글자 크기·색·간격 변경은 제품 디자인 결정이고, roadmap 이
"웹 핵심 기능 안정화 후"로 잡은 항목이다. 재고, 기록하고, 나빠지지 않게 잠갔다.

**실측 (실브라우저 Chrome, `/search`)**
```
검사한 텍스트 199개 / WCAG AA 대비(4.5:1) 미달 81개(41%)
text-gray-400 on white 실제 대비 2.6:1        <- 기준의 58%
탭 타깃 53개 중 44px 미만 44개(83%), 그중 24px 미만 5개  <- (★ 2026-08-20 Sprint 225 정정: 위반 아님 — 간격 예외로 적합)
14px 미만 텍스트 111개
```
가장 나쁜 것은 **무엇이** 작고 흐린가다 — 물건 주소 12px/2.6:1,
"최저입찰가" 라벨과 "감정가 3.8억" **11px**/2.6:1. 판단에 쓰는 정보가 가장 안 보인다.
헤더 내비 5개는 높이 **16px**(Apple HIG 44px 의 36%). (★ 2026-08-20 Sprint 225 정정: 위반 아님 — 간격 예외로 적합)

**소스 분포** (`src/app/**/*.tsx` 18파일): `text-xs` 111 / `text-gray-400` 106 /
`text-[11px]` 6 / `text-gray-300` 6 / `text-[10px]` 2.
가장 심한 화면은 **상세페이지**(text-xs 55 + gray-400 55) — 실제 판단이 일어나는 곳이다.

**★ 측정 도구가 틀렸다(다섯 번째)** — Tailwind v4 는 `oklch()` 로 색을 내는데
숫자만 뽑아 RGB 로 읽어 **대비 1.06 같은 불가능한 값**이 나왔다. canvas 로 변환을
브라우저에 맡기고 **알려진 값(흑백 21.0 / #9ca3af 2.54)으로 도구부터 검증**한 뒤 다시 쟀다.

**★ 재지 못한 것도 적는다** — 모바일 뷰포트(390~412px) 레이아웃은 **확인하지 못했다.**
자동화의 창 리사이즈가 페이지 뷰포트에 반영되지 않고(`innerWidth` 1920 고정),
앱이 `X-Frame-Options: DENY` 라 iframe 우회도 막혔다(그 헤더는 올바른 설정이다).
확인한 것은 뷰포트 메타가 올바르고 확대 차단이 없다는 것까지다.

**가드 추가** — `test_frontend_accessibility.py` 신설(21단언, ratchet 방식)
- 작은 글자/낮은 대비 클래스 사용 횟수를 현재값으로 **상한 고정**(줄면 통과, 늘면 실패)
- 확대 차단(`user-scalable=no` 등) 부재 고정
- 썸네일 `alt=""`/`aria-hidden`/`onError` 규약 + **alt 없는 `<img>` 0개**
- 실측 수치가 Sprint 문서에 남아 있는지(문서가 사라지면 검사가 먼저 운다)
- 변이 4종 전부 검출(클래스 추가 2 / 확대 차단 2 / alt 없는 img 1 / 열거 비우기 2)

★ 이 가드도 처음엔 오탐을 냈다 — **주석 속 `<img`** 를 실제 요소로 세어
`ResultThumbnail.tsx` 를 결함으로 보고했다(그 주석은 Next.js 오류 메시지 인용이다).
주석을 걷어내되 **줄 번호는 보존**하도록 고쳤다.

- 전체 **42 PASSED / 0 FAILED / 3 SKIPPED / 1 NO-VERDICT, 단언 6,386**.


---

2026-08-19 (Sprint 220) - 모바일 구조 감사 / 검색목록 계약 / 큰글씨 전제 정정

**모바일 — 재지 못한 것은 재지 못했다고 적는다**
- 브라우저 자동화의 창 리사이즈가 페이지 뷰포트에 반영되지 않고(`innerWidth` 1920 고정),
  `X-Frame-Options: DENY` 라 iframe 우회도 막힌다(그 헤더는 올바른 설정이라 낮추지 않았다).
  **"모바일 정상"이라고 판정하지 않았다.**
- 대신 가로 넘침의 **구조적 원인**을 전수 확인: 고정 `w-[NNNpx]` / `min-w-[NNNpx]` /
  `w-screen` / `100vw` / `min-w-max` / 인라인 `width` / `<table>` / 반응형 없는 3열 그리드
  **전부 0곳**. 컨테이너는 `max-w-[1320px] px-4 md:px-8`(고정 폭이 아니라 상한).
  `overflow-x-auto` 2곳은 컨테이너 **내부**의 의도된 가로 스크롤.

**검색목록 계약 (신규 가드)**
- `api/v1/search.py` 19키 / `types.ts` 19필드 / `ResultList.tsx` 17필드 — 어긋남 0.
  세 파일이 각자 적혀 있는데 대조하는 검사가 없었다. `item.foo` 가 `undefined` 면
  React 는 **오류 없이 빈칸**을 그린다. 변이 3종 검출(특히 **API 키 이름 변경**).

**데이터 신선도 (신규 가드)**
- 검색/상세 라우터에 캐시 헤더 **0곳**, `src/lib/api.ts` fetch **5곳 전부 no-store**.
  stale 이 생길 자리가 없다는 것을 잠갔다. 변이 2종 검출.

**★ 직전 Sprint 의 기록을 정정했다**
- Sprint 219 의 *"대부분 px 고정이라 루트 글꼴을 키워도 안 커진다"* 는 **틀렸다.**
  빌드 CSS 확인: `--text-xs: .75rem` — Tailwind v4 의 이름 있는 크기는 **rem 기반**이다.
  닿지 않는 것은 임의값 **8곳**(`text-[11px]` 6 + `text-[10px]` 2)뿐.
  **선행 작업은 전면 rem 전환이 아니라 그 8곳 교체.**
  정정을 `SPRINT219` / `roadmap` / `frontend.md` 세 곳에 원문과 함께 남겼다.

**가드 자신도 두 번 틀렸다**
- `max-w-[1320px]` 안의 `w-[1` 을 고정 폭으로 오인(토큰 경계) → 수정.
- 출력 리터럴에 **EM DASH** 를 넣어 `test_console_encoding.py` 에 걸렸다
  (goal 이 경고한 함정을 그대로 밟았고, 저장소의 기존 가드가 잡았다).

- 전체 **42 PASSED / 0 FAILED / 3 SKIPPED / 1 NO-VERDICT, 단언 6,412**.


---

2026-08-19 (Sprint 221) - 접속 정보 확인 / 접근성 구조 / 화면 전체 데이터 계약

**개발 사이트 접속 정보 (실측)**
```
WEB   http://localhost:3000/        (메인 = 검색 화면, 총 9건 + 썸네일 렌더링 확인)
API   http://127.0.0.1:8000         (Swagger /docs 200)
로그인 검색/로그인 화면은 비로그인 가능, /properties·/favorites·/mypage 는 로그인 필요
실행  python -m uvicorn api_server:app --host 127.0.0.1 --port 8000  +  npm run dev
```
운영/외부 배포 없음. ★ 긴 세션에서 node 프로세스가 누적되면 Turbopack 이 `0xc0000142`
로 죽어 dev 서버가 500 을 낸다(코드 결함 아님) — 남은 node 종료로 정상화.

**접근성 구조 (색·크기·간격은 건드리지 않음)**
- 실측: 랜드마크 main/nav/header/h1 각 1 이상, **접근 가능한 이름 없는 요소 0**,
  **키보드로 갈 수 없는 클릭 요소 0**.
- 포커스 표시: 전역 리셋 **없음**(빌드 CSS 확인). `outline-none` 5곳은 **전부 대체
  표시(ring/border)를 함께** 갖는다. 그 규칙을 가드로 잠갔다.
- ★ 판정에 두 번 실패했다 — 계산된 스타일의 `outline-style: none` 은 **비포커스
  기본값**이고, `el.focus()` 는 Chrome 에서 `:focus-visible` 을 켜지 않는다.
  **CSS 규칙 자체**를 읽어야 답이 나왔다.

**화면 전체 데이터 계약 (신규 가드)**
- 검색목록 19/19/17 · 상세 27/20 · 관심물건 22/12 · 최근본물건 22/12 — **어긋남 0**.
  관심물건·최근본물건은 `SELECT ai.*` 라 계약이 스키마에 묶여 있어
  `auction_item` 실제 컬럼을 읽어 대조한다.
- ★ **발견**: `thumbnail_url` 을 주는 API 는 `search.py` 뿐이고 **관심물건·최근 본
  물건 화면에는 사진이 아예 없다.** 기존 문서에 언급이 없어 **미문서화 공백**으로 보인다.
  고치지 않았다(API 필드 + 레이아웃 = 제품 결정). 대신 규칙을 걸었다 —
  *어느 화면이든 `thumbnail_url` 을 그리면 그 화면 API 도 주어야 한다.*

**가드 자신도 두 번 틀렸다**
- `REPLACE` 패턴에 `outline-` 를 넣어 **`focus:outline-none` 이 자기 대체로** 잡혔다
  (무엇을 지워도 통과) → 제거.
- CSS 정규식이 `@supports` 를 선택자로 오인해 **변이 없이도 항상 실패** →
  검출기를 **넣기 전에 검증**하는 방식으로 교체(실제 0 / 주입 1 / 유틸리티 0).

- 전체 **42 PASSED / 0 FAILED / 3 SKIPPED / 1 NO-VERDICT, 단언 6,429**.

**BUGS #149 — 전체 화면 모달이 스크린리더에 모달이라고 말하지 않았다 (수정함)**
- 문서 뷰어 / 사진 라이트박스 둘 다 `role="dialog"`·`aria-modal` 이 **없었다**
  (저장소 전체 0건). 스크린리더가 모달임을 알리지 못하고 **뒤의 검색 결과·가격이
  계속 읽힌다.** `role`/`aria-modal`/`aria-labelledby` 는 **픽셀을 바꾸지 않으므로**
  제품 디자인 결정이 아니라 그대로 고쳤다(제목 h2 에 id 부여).
- 이미 있던 것도 회귀로 고정: Escape 닫기 / 좌우 화살표 / 닫기 버튼 `aria-label` /
  고정 height 없음(큰글씨에도 안 깨진다).
- **포커스 트랩은 여전히 없다**(Tab 이 배경으로 빠져나간다) — 동작 변경 폭이 커서 별도 작업.
- `test_frontend_accessibility.py` 9 신설, 변이 2종 검출.
- 전체 **42 PASSED / 0 FAILED, 단언 6,429** (서버 미기동 기준. 기동 시 6,433 —
  `test_beta_journey` 의 프런트 게이트 4단언이 추가로 실행된다).


---

2026-08-19 (Sprint 222) - 폼 접근성 이름 / 모달 시맨틱 후속

**BUGS #150 — 폼 컨트롤 16개에 접근 가능한 이름이 없었다 (수정함)**
- `/search` 아코디언을 **전부 펼쳐** 실측: 폼 컨트롤 93개 중 **16개 무명**
  (select 9 / date 2 / placeholder 만 있는 input 5).
  보이는 레이블이 `<span>` 이라 컨트롤과 연결돼 있지 않고, 최소/최대가 나란히 둘이라
  **어느 쪽인지도 알 수 없다.** `placeholder` 는 입력 시작과 함께 사라지므로 이름이 아니다.
- `aria-label` 은 **픽셀을 바꾸지 않고**, 저장소가 이미 그 패턴을 쓰고 있었다
  (`시/도`·`시/군/구`·`법원`). 빠진 자리에 같은 방식 적용.
  공용 컴포넌트 2개(`RangeSelect`/`PriceRangeSelect`) 수정으로 select 8개가 한 번에 해결.
- 재측정 **93/93 이름 있음**(수정 전 77/93).
- `test_frontend_accessibility.py` 10 신설 — 감싸는 `<label>` 로 이름을 줄 수 없는
  부류(select / date / placeholder input)만 검사. 변이 3종 전부 검출.

**★ 이 검사의 앞선 판본이 거짓 결과를 냈다**
- `<select[^>]*>` 가 **`onChange={(e) => f(e)}` 의 `>` 에서 잘려** "select 7개 전부
  이름 없음"이라고 보고했다(브라우저로는 전부 이름이 있었다).
  중괄호 깊이를 추적하는 추출기로 교체하고, **추출기 자체를 자기 검증**하도록 했다.

**측정 방법 교정**
- 접힌 아코디언만 보면 폼 컨트롤이 5개로 보인다. **펼친 뒤 재측정**해야 93개가 나온다
  — 화면 상태에 따라 달라지는 것은 그 상태를 만들어 놓고 재야 한다.

- 전체 **42 PASSED / 0 FAILED / 3 SKIPPED / 1 NO-VERDICT, 단언 6,440**.


---

2026-08-19 (Sprint 223) — 모달 포커스 트랩 · 상태 메시지 알림 · main 랜드마크 · 큰글씨 rem 전환

**BUGS #151 — 모달이 키보드 포커스를 가두지 않았다** (수정)
- Sprint 221의 `role="dialog"`/`aria-modal`은 **스크린리더에게만** 하는 말이었다.
  실측(실브라우저 `/properties/505`, 진짜 마우스 클릭·진짜 Tab): 모달을 연 직후 포커스가
  **모달 뒤 버튼**에 있고, Tab 한 번에 **오버레이에 완전히 가려진 버튼**(top 415, left 346)으로
  갔으며, Escape 로 닫아도 여는 버튼으로 돌아오지 않았다. 모달 안 포커스 요소는 3개인데
  화면 전체는 24개 — 21개가 오버레이 뒤에 그대로 살아 있었다.
- `src/lib/useFocusTrap.ts` 신설: 첫 진입 포커스 / Tab·Shift+Tab 순환 /
  Tab 이 아닌 경로는 `focusin` 으로 되돌림 / 닫을 때 원래 자리로 복귀. **픽셀 무변경.**
- 수정 후 실측: 열기 -> '닫기', Tab x3 순환, Shift+Tab 역순환,
  Escape -> **여는 버튼 바로 그 노드**로 복귀(`===`), 밖으로 강제 포커스 -> 되돌아옴.

**★ 없는 결함을 만들 뻔했다** — 문서 뷰어의 첫 열기만 실패한다는 결과가 반복됐고
"PDF iframe 이 포커스를 뺏는다"는 설명까지 세웠지만 **틀렸다.** 탭이 보이지 않는 상태
(`visibilityState: hidden`)에서 `element.focus()` 를 부르면 activeElement 는 바뀌지만
**focus/focusin 이벤트가 전혀 발생하지 않는다**(직접 단 리스너 0회 호출). 탭을 보이게 하고
진짜 마우스 클릭으로 재니 첫 열기부터 정상이었다.

**BUGS #152 — 나중에 나타나는 안내가 아무것도 읽히지 않았다** (수정, WCAG 4.1.3)
- 실측 `/search`: `aria-live`/`role=alert`/`role=status` 요소 **0개**.
  로그인은 **제출해도 반응이 없는 화면**이었다.
- 개별 상태 메시지 13곳에 `role="alert"`/`role="status"`(조건이 감싸는 **여는 태그**에).
- 검색 결과는 `SearchScreen` 의 **항상 존재하는 `sr-only` 한 줄**로 알린다 —
  결과 목록에 달면 0건일 때 문단이 사라져 아무것도 못 알린다.
  실측: 소프트 전환 후에도 **같은 DOM 노드 유지, 글자만 변경**(정렬 변경/실제 0건 검색 둘 다).
- 시/군/구 로드 실패는 `aria-describedby` 로 그 select 에 연결.

**BUGS #153 — 화면 4개에 `main` 랜드마크가 없었다** (수정, WCAG 2.4.1)
- 기존 가드가 **저장소 전체 합산**으로 `>=1` 만 봐서 못 잡았다.
  실측: `/properties/{id}`·`/favorites`·`/properties/recent`·`/login` 이 전부 0.
- 감싸는 `<div>` 의 **태그만** `<main>` 으로 교체(className 동일 = 픽셀 무변경).
  로딩·실패 분기에도 넣었다. 실측 확인: 상세 grid `622px 622px` / 컨테이너 1320px / 오버플로 0.
- 가드도 **화면 루트(min-h-screen) 개수만큼 main** 으로 조였다 — 파일 단위 검사는
  분기 하나가 빠져도 통과했다(변이로 확인).

**BUGS #154 — 검사 도구가 저장소 사본을 검사하고 있었다** (수정)
- `test_console_encoding.py` 가 `.claude/worktrees/sprint95-...`(Sprint 95 커밋의 저장소
  통째 사본)까지 훑었다. **스캔 298개 중 101개(34%)가 그 사본.**
- `.claude` 등 제외 -> 197개. 범위 자체를 잠그는 검사도 넣었다(하한 포함).

**큰글씨 — 고정 px 글자 8곳을 같은 크기의 rem 으로** (BACKLOG 4)
- `text-[11px]` -> `text-[0.6875rem]`, `text-[10px]` -> `text-[0.625rem]`.
- 실측: 루트 16px 에서 **11px 그대로**(픽셀 무변경), 루트 32px 에서 11px -> **22px**
  (전에는 11px 고정), 2배 확대에서도 가로 오버플로 0.
- 큰글씨가 닿지 않는 자리 **8곳 -> 0곳**. 래칫도 0으로 조였다.

**성능 — 검색 API 의 SQL 횟수를 처음으로 쟀다**
- `set_trace_callback` 실측: size 1/3/9 전부 **SQL 3회**(COUNT + 페이지 + 썸네일 배치).
  상세 1건은 7회, 전부 단건. **N+1 아님**을 계측으로 확인하고 회귀로 잠갔다.

**관통 감사**
- 검색목록 썸네일 체인 9/9: DB MIN(seq) == URL seq, 목록 == 상세 images[0], HTTP 재요청 전부 성공.
- 관심물건/최근 본 물건 썸네일은 **SKIP** — 제품 결정이고, 최근 본 34개 중 사진이 있는 것은 **4개**뿐이다.
- API↔UI 대조: 유령 호출 0건. ★ 조사 도구가 먼저 거짓말했다(`app.routes` 만 읽어 "라우트 2개"
  — 이 FastAPI 는 include_router 를 `_IncludedRouter` 로 지연 보관한다). OpenAPI 로 바꿔 42개.
  ★ `GET /item/{id}/images/{seq}` 는 소스에 문자열이 없지만 **실제로 쓰인다**(thumbnail_url 경유).
- 모바일 실뷰포트는 **여전히 확인하지 못했다** — `resize_window(390x844)` 후에도
  페이지 `innerWidth` 는 1920 그대로다(재확인).

**테스트**
- 변이 14종 전부 검출(주입 -> FAIL -> 원복 -> PASS). ★ 두 번은 첫 판본이 놓쳐 조였다.
- Frontend 113/113, tsc 0, eslint 0.
- Python **41 PASSED / 1 FAILED / 3 SKIPPED / 1 NO-VERDICT**.
  유일한 FAILED 는 `test_schema_hygiene.py` 의 P0-B 가드가 **옳게** 보고하는 것이다 —
  새 파일 `src/lib/useFocusTrap.ts` 가 아직 **미추적**인데 추적 파일이 import 한다.
  해소는 `git add` 뿐이고 그것은 **승인 영역이라 하지 않았다**(커밋 시 함께 add 하면 초록).

---

2026-08-20

Sprint 224 — 목록 화면 대표 사진 + 검사 관측 공백 해소

**BUGS #155 — N+1 감시 가드가 공허하게 통과하고 있었다** (수정)
- `test_search.py` 의 SQL 횟수 가드만 `include_closed` 를 빠뜨려, 크롤이 멈춘 채
  날짜가 지나자 결과 0건에서 `2 == 2` 로 통과. 진짜 N+1 을 주입해도 통과함을 확인했다.
- 실측 복구: 검색 1회 = SQL 3회(COUNT + 페이지 행 + 썸네일 배치), size 1/9 동일.
- 변이 2/2 검출.

**BUGS #156 — 관심물건/최근 본 물건에 대표 사진 추가** (구현)
- `api/v1/thumbnails.py` 신설 — 사진 URL 규칙과 배치 조회의 **유일한 출처**.
  `search.py` / `item.py` 도 이 모듈을 쓰게 바꿔 중복 2곳을 제거했다.
- `GET /api/v1/favorites`, `GET /api/v1/recent-items` 응답에 `thumbnail_url` **추가**
  (기존 키는 하나도 바뀌지 않았다 — 추가만 했다). 사진이 없으면 `null`.
- `ResultThumbnail.tsx` 를 `src/app/search/` -> `src/components/` 로 이동, 세 화면 공유.
- 실브라우저 실측: 두 화면 모두 사진이 실제로 디코딩되어 80x80 렌더, 가로 오버플로 0,
  사진 없는 카드는 종전과 같은 텍스트 전용 레이아웃(빈 칸 없음).
- 회귀 `test_asset_pipeline.py` 16-B2 신설, 변이 5/5 검출.

**BUGS #157 — 프런트 계약 스위트의 관측 공백** (수정)
- 데이터 전제 하나가 `before()` 에 있어 50개 검사 전부를 가리고 있었다(93건 실패).
  전용 검사 하나로 분리하고 나머지는 실제로 실행하게 했다.
- 0건 skip 분기가 헤더 링크 때문에 **한 번도 동작하지 않던** 결함도 함께 수정.
- `pass 21/fail 93` -> `pass 110/fail 1/skip 3`. 데이터가 있으면 `114/0/0` (사본으로 증명).

가드 갱신(약화 아님)
- `test_search.py` 목록 화면 계약을 **가정이 아니라 AST 로 소스에서** 읽게 바꿨다.
  앞 판본은 제공 필드를 `auction_item 컬럼 + {favorited_at}` 으로 가정해, 계산된 키
  (`thumbnail_url`)를 표현하지 못하고 **없는 결함을 보고했다.** 스키마 결합은 따로 본다.
- `test_frontend_accessibility.py` 의 `ResultThumbnail.tsx` 경로 갱신.
- `test_schema_hygiene.py` SQL 보간 허용 목록에 `api/v1/thumbnails.py:placeholders` 추가
  (`search.py` 에서 이미 허용돼 있던 것을 모듈로 옮긴 것).

테스트
- `python run_python_tests.py` 통과 40 / 실패 2 / 건너뜀 3 / 판정없음 1 (단언 6,540건 — 6,456에서 증가)
- `npx tsc --noEmit` 0 / `npm run lint` 0
- `npm run test:frontend` pass 110 / fail 1 / skip 3
- `python audit_asset_integrity.py --selftest` 통과, 본 감사 어긋남 27건(기존 고아 데이터)

남은 실패 2건은 둘 다 가드가 옳게 말하는 것이다
- `test_pipeline_integrity.py` — 크롤이 2026-08-12 이후 멈춰 기본 검색에 뜰 물건 0건.
  DB 가 빈 것이 아니다(1,876건 보유, 매각기일이 전부 지났다). 해소 = 실제 크롤(승인 영역).
- `test_schema_hygiene.py` — 새 파일 2개 + 이동 1건이 미추적. 해소 = `git add`(승인 영역).

확인하지 못한 것
- 모바일 실뷰포트. iframe(390px) 측정을 시도했으나 앱 자신의 `X-Frame-Options: DENY`
  (Sprint 127)에 막혔다 — 앱이 옳게 동작한 것이고 측정 경로가 닫힌 것이다.

---

2026-08-20

Sprint 225 — 접근성 주장 정정 + ratchet 가드 사각지대 (**화면 픽셀 무변경**)

**BUGS #158 — "WCAG 2.5.8 위반" 단정 철회** (정정)
- 실브라우저 기하 계산: 세 화면 전부 **위반 0건**. 간격(Spacing) 예외로 적합
  (24px 미만 타깃들의 가장 가까운 중심 간 거리 54px, 임계 24px).
- roadmap 접근성 1순위의 근거(*"위반이라 논쟁 여지가 적다"*)가 사라져 철회했다.
  진짜 규격 위반은 **대비(SC 1.4.3)** 쪽에만 있다.
- 같은 서술이 퍼져 있던 **6곳** 전수 정정. 문서 근거 검사에 정정 토큰을 추가해 잠갔다.

**BUGS #159 — ratchet 가드가 `src/components/` 를 안 봤다** (수정)
- `SiteHeader.tsx`/`PrimaryNav.tsx` 의 `text-xs` 7개 + `text-gray-400` 4개가 미집계였다.
  공용 컴포넌트로 옮기면 검사에서 사라지는 구조 = 리팩터링이 검사 회피가 된다.
- 상한 재기준: text-xs 111 -> **118**, text-gray-400 106 -> **110**, text-red-400 **2** 신규.
- 추적 밖 저대비 클래스 탐지 추가(상한만으로는 더 나쁜 색으로 갈아타는 것을 못 막는다).

**BUGS #160 — 고정 폭 검출기가 `max-w-` 를 오인** (수정)
- #159 로 범위를 넓힌 첫 실행에서 드러났다. **범위가 좁으면 검사기 버그도 함께 숨는다.**
- 부정 lookbehind 추가 + 검출기 자체를 known-good/known-bad 로 선검증.

색 대비 실측(캔버스 래스터화 — oklch/lab 을 브라우저가 변환하게 했다)
```
text-gray-300 1.47  text-gray-400 2.60  text-red-400 2.89  text-blue-500 3.76   <- 전부 AA 미달
text-gray-500 4.84  text-blue-600 5.25  text-gray-600 7.56  text-gray-700 10.30 <- AA 통과
흰 글씨 on bg-blue-500  3.76   <- 주 CTA(검색/저장/정렬칩)가 미달
/search 36개 중 20개 실패 · /properties/505 100개 중 49개 실패(14px 미만 38개)
```
- 새로 드러난 것: **주 CTA 버튼**(흰 글씨 on blue-500)과 **오류 문구**(red-400)가
  Sprint 219 표에 없었다. 오류 문구는 가장 읽혀야 하는 글자인데 본문 회색과 비슷하다.
- ★ 측정 도구가 또 거짓값을 낼 뻔했다 — Tailwind v4 는 **쓰인 클래스만** CSS 로 만들어서,
  없는 클래스를 붙이면 상속색이 읽힌다(`text-blue-700` -> `--foreground` 17.93). 그래서
  "클래스가 실제로 적용됐는가"를 먼저 확인하고, 아니면 **측정 불가**라고 말하게 했다.
- 최소 교체안(같은 색조에서 한 단계)을 문서에 남겼다. **적용은 제품 결정이라 하지 않았다.**

변이 4/4 검출. ★ 넷째는 처음에 놓침으로 나왔는데 원인이 **변이 시험 쪽**이었다
(토큰이 3번 나오는데 1번만 바꿨다) — 가드를 의심하기 전에 변이가 진짜 결함을 만들었는지 먼저 본다.

곁다리: 새 문구에 넣은 em dash 를 `test_console_encoding.py` 가 잡았다(cp949 출력 불가). 가드가 제 일을 했다.

테스트: 통과 40 / 실패 2 / 건너뜀 3 / 판정없음 1 (단언 **6,546건**, 6,540에서 증가), tsc 0, lint 0.

확인하지 못한 것: **모바일 폭**. 이번 2.5.8 판정은 데스크톱 1920px 기하다. 좁은 폭에서
헤더 항목이 가까워지면 간격 예외가 깨져 **진짜 위반**이 될 수 있다.
`resize_window` 는 innerWidth 를 못 바꾸고 iframe 은 `X-Frame-Options: DENY` 에 막힌다.

---

2026-08-20

Sprint 226 - 제어문자로 굳은 이스케이프 / 공허한 가드 (제품 코드 변경 없음)

**BUGS #161 - 절대 실패할 수 없던 단언** (수정)
- `tests/source-contract.test.mjs` 의 `formatPrice` 금지 단언이 정규식 이스케이프가
  **백스페이스 문자(0x08)로 굳어** 한 번도 동작한 적이 없었다. 커밋된 상태 그대로다.
- 지키려던 것: 축약 표기가 12,900원을 "1만"(-22%)으로 만들어
  **같은 결제가 화면마다 다른 금액으로 보이는** 결함.
- 변이로 확인: 결함을 주입하면 수정 후 판본은 **검출**, 수정 전 판본은 **놓침**.
- `String.raw` + `RegExp` 로 바꾸고, 같은 자리에서 합성 입력으로 공허하지 않음을 증명하게 했다.

**BUGS #162 - 같은 계열 전수 탐색 + 상시 가드 신설** (수정)
- 390개 파일 전수 탐색 -> 발견 1곳(#161 그것뿐).
- `test_console_encoding.py` 에 상시 검사 신설(대상 242개, 고정 0개, 하한 80, 자체 검증 포함).
- 변이 3/3 검출(.mjs/.py/.tsx).

테스트: 통과 40 / 실패 2 / 건너뜀 3 / 판정없음 1 (단언 **6,550건**, 6,546에서 증가),
`node --test tests/source-contract.test.mjs` 23/23, tsc 0, 프런트 110/1/3.

---

2026-08-20

Sprint 227 - 마이리스트 내보내기(형식 중립 CSV / 클립보드)

**기능** (`docs/SPRINT219B` 가 "안전"으로 분류한 범위만)
- `src/lib/exportList.ts` 신설 - 열 정의(헤더+추출기 결합) / RFC 4180 이스케이프 /
  CSV·TSV 생성 / 엑셀용 UTF-8 BOM 상수 / 파일명.
- `src/app/favorites/ExportButtons.tsx` - "CSV 내려받기" + "복사". 0건이어도 감추지 않고
  비활성으로 둔다(사라지는 UI 는 "기능이 없다"로 읽힌다).
- **상대 서비스 전용 포맷은 만들지 않았다** - 실제 입력 형식 미확인(사람의 확인 필요).

**데이터를 왜곡하지 않는다**
- 병합 사건(실측 22.7%)을 쪼개지 않고 원본 문자열 그대로 낸다.
- 가격은 숫자 원본(축약하면 12,900원이 "1만"이 되어 -22%).
- 없는 값은 빈 칸. 유찰 0회는 "0"(`!v` 판정이면 "없음"이 "모름"이 된다).

**회귀** `tests/export-list.test.mjs` **23검사** 신설.
- ★ 이 저장소에서 처음으로 **TypeScript 를 실행해** 검증한다. Node 24 가 타입 스트리핑을
  기본 지원(`process.features.typescript === 'strip'`)해 새 라이브러리 없이 `.ts` 를 직접
  import 한다 - "새 라이브러리 설치는 승인 필요"를 지키면서 진짜 실행 검증을 얻었다.
- 검사용 CSV 파서 자체를 known-good 표본 6가지로 먼저 검증한다(우리 코드로 만든 것을
  우리 코드로 파싱하면 같은 실수를 두 번 해도 통과한다).

**바깥 소비자로 확인** 픽스처 API 응답으로 만든 CSV 를 **파이썬 csv 모듈**로 읽었다 -
BOM / 헤더 10열 / 모든 행 칸 수 일치 / 쉼표 든 값('상가,오피스텔,근린시설') 한 칸 유지 /
가격 원본 / 한글 온전. cp949 로 읽으면 UnicodeDecodeError -> **BOM 이 필요한 근거**.

**실브라우저** 복사 7줄x10칸, 내려받기 관심물건_2026-08-20.csv 1,505B, 선행 바이트 EF BB BF.
★ 처음에 `blob.text()` 로 BOM 을 확인하려다 "없음"이 나왔다 - `Blob.text()` 는 디코딩에서
**선행 BOM 을 제거한다.** `arrayBuffer()` 로 바이트를 보니 있었다. 도구를 먼저 의심한다.

**가드가 새 코드를 두 번 잡았고 둘 다 옳았다**
- `text-xs` 상한 초과 -> 상한을 올리지 않고 `text-sm`(14px)으로 바꿨다(접근성으로도 낫다).
  상태 메시지 색은 `text-gray-600`(7.56:1, Sprint 225 실측표)을 골랐다.
- 상태 메시지를 sr-only + 보이는 줄 둘로 나눈 것 -> **한 줄로 합쳤다.**
  가드의 예외 정규식이 속성 순서에 의존했지만 **순서를 바꿔 피하지 않고** 구조를 고쳤다.

**BUGS #163 - 상한 계수기가 주석을 코드로 세고 있었다** (수정, 위 과정에서 발견)
- 계수기만 `_strip_comments()` 를 안 썼다. 상한을 코드 기준으로 재기준(text-xs 118 -> 117).
- 변이 2/2 기대대로.

테스트: 통과 40 / 실패 2 / 건너뜀 3 / 판정없음 1 (단언 6,550건),
프런트 **tests 137 / pass 133 / fail 1 / skip 3** (114 -> 137), tsc 0, lint 0.

확인하지 못한 것: 운영 데이터. 이 계정의 관심물건이 0건이라 **사본**으로 검증했다.

---

2026-08-20

Sprint 228 - 남의 사건 파일 저장 방지 + 묶기 착수 조건 재측정

**BUGS #164 - 내려받은 파일의 사건을 아무도 확인하지 않았다** (수정)
- `wait_for_download()` 가 "새로 생긴 PDF" 를 사건과 무관하게 집는다. 앞선 수집이
  타임아웃으로 포기한 뒤 그 다운로드가 완료되면 **남의 문서가 이 사건으로 저장**된다.
- 저장물은 진짜 PDF 라 무결성 감사 전부를 통과한다 - 결과 검사로는 절대 안 잡힌다.
- 파일명의 사건번호로 대조하되 **확실할 때만 거부**한다(사건번호가 없는 감정평가서는 통과).
- 병합 사건은 기존 `case_no_matches_list_entry()` 재사용. 거부해도 파일은 지우지 않는다.
- 회귀 14검사 신설(배선 여부까지 센다), 변이 4/4 검출.

**doc_worker 물건 단위 묶기 - 다시 재고 구현하지 않았다**
- Backlog 지시대로 병목 조건을 먼저 확인했다. 문서의 숫자를 믿지 않고 재측정:

```
pending 2,753 / done 559 / SKIPPED_EXPIRED 186
대기 + 기일이 남은 물건   **0개**   (Sprint 199 당시 2개)
묶어서 아낄 이동 횟수      0회  ->  절감 0초
```

- 착수 조건이 더 나빠졌다(크롤이 2026-08-12 이후 멈춰 대기 행 2,753개가 전부 만료).
  이득 0인데 claim/retry 전제를 흔드는 것은 순서가 나쁘다 - Sprint 199 결론 그대로 유효.
- 곁다리: "만료 행이 실제 작업을 굶기는가"를 의심해 **사본에서 실제 함수로 쟀다** ->
  2,753개 전부 훑기 **16.1초**(문서 1건 이동 18.2초보다 싸다). **내 의심이 틀렸다.**
  고칠 것이 없으므로 고치지 않는다.

**이미지/문서 파이프라인 전수 확인**(서버를 띄운 상태)
- [1]~[5] 전부 어긋남 0. **[9] API 가 광고한 URL 601개(사진 45 + 문서 556) 전부 열림.**
  ★ [9] 는 서버가 없으면 "확인하지 못함"이 된다 - 그것을 "이상 없음"으로 읽으면 안 된다.
- 남은 어긋남 27건은 전부 기존 고아 데이터(디렉터리 1 + 큐 18 + 다운로드 8). 삭제는 승인 영역.

테스트: 통과 40 / 실패 2 / 건너뜀 3 / 판정없음 1 (단언 **6,564건**, 6,550에서 증가).

---

2026-08-20

Sprint 229 - 변경 감지 감사 ("없음" / "실패" / "관측 공백"의 구분). 운영 DB 무변경.

**BUGS #165 - `COUNT(*) >= 0` 공허한 단언** (수정)
- 깨질 수 있는 불변식(만료+진행중+고아 == 전체)으로 교체. 고아 `document_status` 행을
  처음으로 세게 됐다(현재 0개). 변이: 사본에 고아 1행 주입 -> 지금 판본 FAIL / 옛 판본 통과.

**★ "변경 0건"은 변경이 없다는 뜻이 아니었다**
```
doc_raw 556행, doc_version 전부 1 (2 이상 0건)
큐의 refresh 행 0개 / 마지막 문서 수집 시도 2026-07-12 (39일 전)
```
- 재수집이 39일간 한 번도 돌지 않았다 -> **관측 공백**이지 "변경 없음"이 아니다.
  변경 감지 로직 자체는 합성 픽스처 회귀로 계속 검증되고 있다. 없는 것은 운영 관측뿐이다.

**상태 어휘는 구분되어 있고 모순도 없다**
- READY / NO_IMAGE(없음) / FAILED(실패) / COLLECTING(모름)이 코드에서 분리돼 있다.
- "사진 없음인데 사진 행 있음" 0개, "READY인데 사진 행 없음" 0개, 해시 없는 행 0개.

**보류된 제품 결정의 비용이 16배로 자랐다** (수치 갱신, 코드 변경 없음)
```
                                 Sprint 73(08-14)   지금(08-20)
COLLECTING 총합                        5,069          5,069
  그중 물건 진행중                          20              0
  큐에 살아 있는 행이 없어 영원히 안 끝남    183          2,921
  (별개) 큐 행이 아예 없는 물건 715 x 3종                2,145
```
- 원인은 상태머신이 아니라 **크롤 정지**로 큐가 전부 만료된 것 = 데이터 공백의 그림자다.
  "수집이 정상 가동 중에도 남는가"는 재개 후에 다시 재야 판정할 수 있다.
- **지금 사용자 노출은 0** (기본 검색에 뜨면서 COLLECTING 인 물건 0개).
- `document_status` 에 "대상 아님" 상태를 만들지는 여전히 **제품 결정**이라 하지 않았다.

테스트: 통과 40 / 실패 2 / 건너뜀 3 / 판정없음 1 (단언 6,564건).

---

2026-08-20

Sprint 230 - 무인 운전 시뮬레이션 / 스케줄 산술 / 다른 물건 사진 차단

**BUGS #166 - 다른 물건의 사진이 저장될 수 있었다** (수정)
- `go_to_case_detail()` 이 물건번호를 못 찾으면 경고만 남기고 첫 행으로 진행했다.
  저장물은 진짜 사진이라 무결성 감사 [1]~[9] 를 전부 통과한다 - 결과 검사로는 안 잡힌다.
- `require_exact_item` 추가, `doc_worker` 가 **사진일 때만** True. 모호할 때만 거부한다.
- 회귀 9검사(실제 함수 + 가짜 드라이버), 변이 4/4.
- 곁다리: `test_doc_worker_recovery.py` 스텁이 시그니처 변경을 즉시 잡았다.
  `**kwargs` 로 뭉개지 않고 새 인자를 이름으로 받게 고쳤다.

**BUGS #167 - 스케줄 산술의 사건 크롤 다리** (가드 신설)
- `DOC_WORKER_END_TIME <= DailyCrawl 시작` 을 잠갔다(겹치면 Chrome 두 개가 동시 크롤).
- 하드코딩한 배치 목록 ↔ PS1 작업 목록 대조 + PS1 -> .bat -> .py 존재 확인.
- 변이 4/4.

**`test_scheduler_longrun.py` 신설 (121단언)** - 장시간 무인 운전 시뮬레이션
- 실제 함수만 부른다(enqueue/claim/mark/reset/refresh + migrate_execute). 운영 DB 무접근.
- 7일 연속: 일별 증가폭 [16]x6 로 **일정**, 불변식 위반 0, auction_item 28 / status 106.
- 크래시 회수(refresh 의도 보존) / 재시도 예산 / 재실행 멱등 / 만료 200행 starvation 없음.
- ★ 첫 판본이 **공허하게 통과**했다 - `upsert_batch` 는 `auction` 에 쓰고 `auction_item` 은
  `migrate_execute` 가 채우는데 그 단계를 빼먹어 조인 불변식 2개가 항상 빈 결과였다.
  동기화를 넣고 "실제로 채워졌다"를 명시적으로 잠갔다.
- 변이 3/4 검출. 나머지 하나는 **변이가 결함을 못 만든 것**(UNIQUE 가 막는다)이었고,
  UNIQUE 를 건드리자 검출됐다.

**이미지 체인 실브라우저 관통**
```
자산 감사 [9]  사진 45 + 문서 556 URL / **열리지 않음 0**
최근 본 물건   사진 4장 전부 디코딩, ★ 화면 URL == 검색 API == 상세 API
검색목록       총 1,876건 / 썸네일 9개, 뷰포트 안 6개 전부 디코딩, alt/aria 준수
상세 /505      사진 5장, 대표 사진 렌더
```
- ★ 하마터면 없는 결함을 보고할 뻔했다. 첫 측정에서 `naturalWidth: 0` 이었는데
  원인은 앱이 아니라 **탭이 hidden 이라 Chrome 이 `loading="lazy"` 로드를 미룬 것**이었다
  (서버는 200/정상 JPEG, 새 Image() 는 성공, `currentSrc` 는 비어 있었다).
  Sprint 223 의 포커스 함정과 같은 계열 - **보이지 않는 탭에서 잰 lazy 이미지 상태는
  근거로 쓰지 않는다.** 렌더를 강제한 뒤 재측정한다.

테스트: 통과 **41** / 실패 2 / 건너뜀 3 / 판정없음 1 (단언 **6,701건**, 6,564에서 증가).

---

2026-08-20

Sprint 231 - 좁은 폭 레이아웃을 처음으로 실측 (코드 변경 없음)

**측정 경로를 다시 확인했다** (문서를 믿지 않는다)
- `resize_window(390x844)` 는 "성공"을 반환하지만 `innerWidth` 는 1568 그대로,
  `matchMedia('(min-width: 768px)')` 도 여전히 true. **뷰포트는 못 줄인다** - 결론 변동 없음.

**대신 서브트리를 고정 폭 컨테이너에 복제해 진짜 레이아웃을 계산시켰다**
- `clone.scrollWidth - w > 0` 이면 그 폭에서 넘친다. 가짜 산술이 아니라 브라우저가
  실제로 줄바꿈/축소/min-content 를 계산한 값이다.
- ★ 한계: 복제본도 **실제 뷰포트**로 미디어쿼리를 평가한다. `md:`/`xl:` 로 열 수가
  바뀌는 컨테이너에는 쓸 수 없다. 실제로 결과 그리드가 "288px 에서 157px 초과"로
  나왔는데 그것은 결함이 아니라 **기법의 한계**였다(3열을 그리려 한 것).

**실측 결과 - 넘치는 곳이 없다**
```
검색목록 결과 카드 20개    320 / 360 / 390px 전부 초과 0
상세페이지 카드 10개       320 / 360 / 390px 전부 초과 0
                           (Sprint 219 가 "목록보다 나쁘다"고 지목한 화면)
마이리스트 내보내기 줄     320 / 360 / 390px 전부 초과 0
                           가장 긴 실패 문구로 재도 상태 문구가 축소·줄바꿈된다
```
- ★ 내보내기 줄은 **넘칠 것으로 의심했는데 틀렸다.** 산술로 추정했으면 없는 결함을
  보고했을 것이다.

**이제 말할 수 있는 것 / 없는 것**
- 말할 수 있다: 결과 카드/상세 카드/내보내기 줄은 **320px 에서도 가로로 넘치지 않는다.**
- 여전히 말할 수 없다: `md:`/`xl:` 열 전환 지점의 동작, 실기기 렌더링/터치.
- 기존 소스 가드(넘칠 **원인**이 없다)와 보완 관계다 - 이번 실측이 그것을 처음으로 뒷받침한다.

---

2026-08-20

Sprint 232~233 - 불필요한 드라이버 재시작 제거 / Admin 키 회귀 / 전면 Audit

**BUGS #168 - '사건 미발견'이 드라이버를 재시작했다** (수정)
- `go_to_case_detail()` 의 False 는 브라우저 고장이 아닌데 일반 예외로 올려 재시작했다.
  Sprint 230 의 **의도적 거부**(사진 물건 모호)도 같은 경로를 타서 옳은 판단이 재시작을 불렀다.
- 실측(로그 11일치): 매칭 실패 255회 x 평균 5.9초 = 25.1분(하루 2.3분, 창의 약 2%).
  **시간보다 연쇄가 문제** - 재시작이 실패하면 Sprint 137 방어가 하루치 실행을 중단한다.
- 전용 예외 `CaseNotReachable` 로 분리해 재시작 없이 다음 항목으로. 재시도 예산은 불변.
- 회귀 2종(대조군 포함), 변이 3/3.
- 함께 조사한 `MAX_ITEMS=10` 가설은 **반증**(62개 중 10건 초과는 2개뿐). 폐기.

**BUGS #169 - Admin 키가 다시 사라졌다** (문서 정정, P1 -> **P0**)
- `.env` 에 ADMIN_API_KEY / SUPER_ADMIN_API_KEY / PAYMENT_WEBHOOK_SECRET **이름 자체가 없다**.
- OpenAPI 전 라우트 38개를 토큰 없이 호출 -> `/admin/*` 13개 전부 500 "관리자 키 미설정".
- 운영자가 할 수 있는 일이 하나도 없다. `.env` 수정은 승인 영역이라 보고만 했다.

**전면 Audit (전부 이번 세션 실측)**
```
라우트 인증 경계  38개: 보호 16 / 공개 8 / 422 1 / 500 13(admin) / SKIP 4
                  공개 8개에 개인정보·관리 기능 없음
Cache            사진 235KB·문서 396KB 모두 ETag+Last-Modified, If-None-Match -> 304/0B
                  틀린 ETag -> 200(공허하지 않음). JSON API 는 캐시 헤더 없음
성능             search20 14.8ms / search100 20.6ms / item 4.3ms / image 5.5ms / stats 4.1ms
                  size 1->100 에서 3.8->29ms (데이터 100배, 시간 8배 = 선형 폭증 아님)
접근성           컨트롤 167개 전부 이름 있음 / alt 누락 0 / h1 1 / heading 건너뜀 없음
                  focus-visible 위반 **0건** / 마이리스트 disabled 의미론 정상
죽은 코드        production 59파일 304함수 중 미참조 **0개**
```

**★ 도구 오류 4건을 걸러냈다** (코드보다 도구를 먼저 의심)
```
1. MAX_ITEMS 가 원인이다              -> 60:2 로 반증
2. 자산에 ETag 가 없다                 -> dict(headers) 대소문자. 실제로는 있다
3. 폼 컨트롤 7개 포커스 표시 없음       -> focusin 핸들러 안에서 읽은 타이밍 문제
4. element.focus() 로 focus-visible    -> 키보드 포커스가 아니면 켜지지 않는다
```

테스트: 통과 41 / 실패 2 / 건너뜀 3 / 판정없음 1 (단언 **6,709건**, 6,701에서 증가).

---

2026-08-20

Sprint 234 - Admin Secret 계약 / MAX_ITEMS 실측 / 큰글씨·모바일 재확인

**BUGS #170 - Admin Secret 계약 회귀 신설** (`test_admin_secret_contract.py`, 30검사)
- 비어 있던 중간 상태를 잠갔다: 틀린 키 -> **403**(500 아님) / 등급 분리(ADMIN 키로 SUPER 라우트 403,
  SUPER 미설정이어도 열리지 않음) / **Secret 부재가 일반 사용자 API 에 영향 없음**.
- Admin 라우트는 OpenAPI 에서 **16개 전수 추출**(하드코딩 목록 안 씀), 키 없이 500 아닌 것 0개.
- 키는 프로세스 환경에만 주입 — `.env` 무접근, 운영 Secret 생성 없음.
- 변이 **4/4**(등급 검사 끄기 / 미설정 가드 끄기 / 틀린 키 허용 / 헤더 없으면 최고 등급).

**BUGS #171 - `DOC_WORKER_TEST_MODE` 문서 공백** (문서 보강)
- 실행 창 검사를 무력화하는 플래그인데 문서에 없었다. 용도/위험/운영값을 기록.
- 함께: `SUPABASE_ANON_KEY` 는 `.env` 에 있으나 **읽는 코드 0곳**(프런트는 NEXT_PUBLIC_ 쪽 사용).

**설정 로딩 경로 전수 Audit** (값 미열람)
```
SUPABASE_JWT_SECRET 88자 / SUPABASE_URL 40자        <- 설정됨
ADMIN_API_KEY / SUPER_ADMIN_API_KEY / PAYMENT_WEBHOOK_SECRET  <- 이름 없음
startup validation **없음** — 필수 Secret 이 비어도 서버는 정상 기동한다
```
- ★ 측정 도구가 두 번 틀렸다. `load_dotenv()` 없이 / 스크래치에서 인자 없이 호출
  (find_dotenv 는 **호출 파일 디렉터리**부터 훑는다) -> "JWT 시크릿 없음"이라는 거짓 결과.
  경로 명시 후 88자 확인. 2차에서 멈췄다면 **없는 P0**(인증 전체 장애)를 보고했을 것이다.

**MAX_ITEMS = 10 실측** (정책은 바꾸지 않았다 — 운영 판단)
```
상한 도달   "목록 수집 완료" 104회 중 10건 12회 (11.5%)
DB 기준     (법원,기일) 조합 316개 중 10건 초과 14개(4.4%) / 상한 밖 물건 31건(1.7%)
비용        물건 1건당 중앙값 3.5초, 법원 60개
            20 -> +0.6h / 30 -> +1.2h / 50 -> +2.3h (전 법원이 상한만큼 있다는 최악 가정)
제약        일일 크롤은 종료 시각이 없고 ExecutionTimeLimit 4시간이 상한
            ★ 그러나 물건 1건 = 문서 큐 4행 -> 02:00~04:00(120분) 창이 진짜 병목
```

**큰글씨 기술 장애물 재측정** — `text-[NNpx]` **0** / `leading-[NNpx]` **0** /
인라인 fontSize px **0**. 유일한 `max-h-[420px]` 는 **`<img>`** 라 글자와 무관.
**진짜 장애물 0개** — 남은 것은 토글 여부와 배율뿐이고 그것은 제품 결정.

**모바일 4개 폭 전부** — 검색목록 카드 20 / 버튼 줄 42 / 상세 카드 10,
**320·360·390·430px 전부 가로 넘침 0**. (긴 주소 포함 요소 11개, 최장 103자 — 공허하지 않음)

테스트: 통과 **42** / 실패 2 / 건너뜀 3 / 판정없음 1 (단언 **6,736건**, 6,709에서 증가).

---

2026-08-20

Sprint 235 - 문서 워커 처리 능력 (정책 변경 없음)

**BUGS #172 - 처리 능력 검사 부재** (회귀 신설 `test_worker_capacity.py`, 15단언)
- 실측: navigate 1회 **10.9초**(904구간 중앙값), 물건당 이동 = doc_type 수.
- 능력 **165건/일**(4종 x 10.9초 / 창 120분) vs 공급 중앙값 106 / 최대 278 / 이론 600.
  -> 평상시는 감당, **최대일은 113건 밀림**, MAX_ITEMS 상향 시 434건 초과.
- ★ 큐에 `image` 0행 — 새 적재부터 4종이 되어 이동이 는다(사진 수집 자체는 0.0초인데
  그것을 위한 이동만 10.9초).
- 래칫 추가(기준선 165건). 변이 **3/3** — doc_type 추가는 **래칫만** 잡았다.
- batching 이득 **4.0배**(661건/일, 이론 최대까지 덮는다). 구조 변경이라 SKIP, 근거만 기록.
- **MAX_ITEMS 상향은 batching 다음**이라는 순서를 계산으로 확정.

**7일 시뮬레이션을 다시 믿지 않고 검증**
- stub/monkeypatch **없음** / 부르는 이름 9개 전부 실제 함수 / 런타임 추적으로
  claim 402회·skipped 200회·done 88회·failed 73회 등 **실제 호출 확인**.

**곁다리** - 새 검사의 출력 문자열에 넣은 em dash 를 `test_console_encoding.py` 가 즉시 잡았다
(cp949 UnicodeEncodeError 자리). 지목된 4줄만 수정.

테스트: 통과 **43** / 실패 2 / 건너뜀 3 / 판정없음 1 (단언 **6,751건**, 6,736에서 증가).

---

2026-08-20

Sprint 236 - 물건 단위 batching (정책 무변경)

**BUGS #173 - 물건 하나에 상세페이지 4회 진입** (회귀 신설 `test_worker_batching.py`, 43검사)
- `claim_next_item_rows()` / `release_queue_rows()` 신설. **claim 단위만** 행 -> 물건.
  재시도 예산 / 성공·실패 / refresh 의도 / 부분 실패는 전부 **행 단위 그대로**.
- 상세페이지 이동 **48회 -> 12회**(진짜 `doc_worker.main()` 실측, 물건 12 x 4종).
- 처리량 **78 -> 153건/일 (1.97배)**. 실측 공급 중앙값 106건을 이제 감당한다
  (예전 78건으로는 **평상시에도 못 따라갔다**).
- ★ 재사용 전 `wait_for_detail()` 로 화면 확인 - 창 복구 실패 시 남의 문서를 긁는 것을 막는다.
- ★ 사진을 먼저 처리해 **엄격한 이동 한 번**을 나머지가 재사용한다(Sprint 230 정확일치 유지).

**★ Sprint 235 측정 정정**
- 'navigate 10.9초'는 이동 비용이 아니라 **한 행의 전체 주기**였다(수집+sleep 포함).
  실측: 행 1개당 23.2초 / 이동 1회 15.2초 / 능력 165 -> **78건/일**.
- 'batching 4.0배'는 처리량이 아니라 **이동 감소 배수**였다. 처리량 이득은 **1.97배**.

**★ 공허했던 가드 수리** - Sprint 235 의 '모델 근거' 검사가 `doc_worker.py:266`의
**주석**에 걸려 batching 을 놓쳤다. 주석·독스트링 제거 후 검사 + **실제 호출** 확인으로 교체.
`test_asset_pipeline.py` 의 정확일치 배선 검사도 grep -> 실제 호출로 교체(5규칙).

**실행 창 / MAX_ITEMS 재평가 (계산만, 변경 없음)**
- 최대 공급일(278건)을 덮으려면 창 **3.6시간** 필요 -> 02:00~**05:38**, 06:00 크롤과
  겹치지 않는다. 가장 값싼 다음 수.
- `MAX_ITEMS` 상향은 여전히 아니다(이론 최대 600 vs 능력 153).

테스트: 통과 **44** / 실패 2 / 건너뜀 3 / 판정없음 1 (단언 **7,007건**, 6,751에서 +256).
frontend 137 중 133 PASS / 1 FAIL(크롤 정지) / 3 SKIP. tsc 0 / eslint 0.

---

2026-08-20

Sprint 237 - 실행 창 / MAX_ITEMS / 캐시 (정책·운영 전부 무변경)

**BUGS #175 - 실행 창 가드가 "종료 == 크롤 시작"을 통과시켰다**
- 워커는 종료 시각에 딱 멈추지 않는다 - 처리 중이던 **행 하나**는 지나서도 끝난다
  (실측 최대 42.2초, 이론 약 50초). END=06:00 이면 크롤과 실제로 겹친다.
- 여유 **5분**을 요구하도록 강화. 창이 음수일 때 공허하게 통과하던 검사도 수리.
- ★ config 를 잠깐 바꿔 **실제 가드에 태워** 판정: **05:38 통과 / 안전 상한 05:55 /
  05:56·06:00 막힘**. 되돌린 뒤 바이트 동일 확인.
- 초과분이 행 하나로 제한되는지 행동으로 잠갔다(is_time_up 호출 14회).

**BUGS #174 - MAX_ITEMS 가 공급 상한이면서 조회 반경이다** (신규 `test_max_items_contract.py`, 18검사)
- 진짜 함수로 절단 재현(19건 페이지 -> 10건, 19번째는 못 찾음).
- 크롤 로그 1,698회 중 **12.1%가 상한에 걸린다**(분포가 10에서 튄다).
- ★ 자료가 오른쪽으로 잘려 있어 "올리면 공급이 얼마"는 알 수 없다 -> **역산**:
  능력 153건/일 vs 공급 106건 = 여유 1.44배. 창 05:38 이면 277건/일 = 2.61배.
  **창 확대가 MAX_ITEMS 보다 먼저**라는 순서를 계산으로 확정.

**BUGS #176 - 사용자별 JSON 에 캐시 정책 없음** (신규 `test_api_cache_headers.py`, 12검사)
- 인증 요청 + 검증자 없는 응답에만 `Cache-Control: no-store`.
- ★ 파일 응답은 제외 - 덮으면 실측 **630KB** 의 304 절약이 사라진다.

**★ 내 가설이 틀렸다는 것을 데이터가 말해 줬다**
- 로그의 "상세페이지 미도달 28.1%" 를 MAX_ITEMS 절단으로 의심했으나, 실행 시점 기준
  재판정 결과 **81%가 이미 지난 기일**이었고 MAX_ITEMS 로 설명되는 것은 2건뿐이었다.
- 게다가 그 로그는 **2026-08-02 까지**로, 형제 재사용 0회·정확 일치 0회 -
  기일 경과 방어(Sprint 145/146)가 들어오기 **전**이다. 현재 결함으로 보고하지 않는다.
- 같은 이유로 시간 상수(행 23.2초/이동 15.2초)도 batching 이후 실측이 아니다. 크롤 재개 후 재측정 필요.

**관심물건/최근본** - favorites 0건이라 최근본 실데이터로 카드 경로를 태웠다
(카드 12 / 이미지 4장 전부 디코딩). 썸네일 계약은 사진 보유 4건에 정확히 4개 -
첫 표본이 사진 없는 사용자여서 거짓 결함으로 볼 뻔했다.

**모바일 측정 개선** - `truncate` 요소를 min-content 로 재면 **과대보고**한다(잘릴 뿐 안 넘친다).
클리핑 요소 제외 + 실제 320/360/390/430 상자 측정으로 교체 -> 카드 31개 전부 넘침 0.
iframe 으로 진짜 viewport 를 만들려 했으나 앱의 `X-Frame-Options: DENY` 에 막혔다 -
**측정 편의로 보안 헤더를 약화하지 않는다.**

테스트: 통과 **46** / 실패 2 / 건너뜀 3 / 판정없음 1 (단언 **7,064건**, 7,007에서 +57).
변이 **9/9**.

---

## Sprint 238 (2026-08-20)

**재측정 결과 실패가 2건 -> 12건으로 늘어 있었다** - 전부 로컬 `auction.db`에
`020_create_auction_image.sql` 재미적용 하나로 설명됨(진짜 서버 curl로 재현:
`/search`/`/item` 100% 500). `docs/BETA_RELEASE_CHECKLIST.md` P0-C 재오픈.

**스케줄러 - 처음으로 "등록은 있는데 실행이 실패한다"를 확인** - `DOJOONPASS_DAILY`
1개 등록됨(과거 "0개"와 다름), 그러나 `LastTaskResult 0x800710E0`(권한 거부)로
최근 실행 실패. DocWorker/PriorityRefresh는 여전히 등록 0개.

**`test_doc_path_safety.py` 가드 수정** - `step11_report.py`/`step7_report.py`의
인라인 `/`->`_` 치환을 `sanitize_path_segment()` 호출로 교체(동작 무변경).

테스트: 통과 37 / 실패 11 / 건너뜀 3 / 판정없음 1. 상세는 `docs/SPRINT238_LIVE_REGRESSION_AND_BATCHING_CONFIRM.md`.

---

## Sprint 239 (2026-08-21)

**BUGS #177 - `auction_image` 결손이 검색/상세/사진 API 전체를 500으로 끌고 갔다** -
migration 020 미적용은 그대로지만, 원인 3곳(`fetch_thumbnail_seqs()` / `item.py` 사진
목록 / `images.py` 서빙)에서 `sqlite3.OperationalError`를 narrow하게(정확히
`"no such table: auction_image"` 메시지만) 흡수해 "사진 없음"과 같은 모양으로
되돌리도록 고쳤다. 다른 종류의 `OperationalError`는 그대로 재던진다.

```
GET /api/v1/search?limit=3   500 -> 200  total 124
GET /api/v1/item/1           500 -> 200  images: []
GET /api/v1/item/53                200  documents[].available: true (실파일 다운로드 200 확인)
```

python `run_python_tests.py` 37 -> **45**, node `--test` **137/137 PASS**(이전 96 실패
전부 이 결손의 파급이었다). 신규 회귀 `test_asset_pipeline.py::test_missing_auction_image_table_degrades_not_crashes` -
3개 수정 파일 각각 try/except를 mutation으로 제거해 재현(FAIL 확인) -> 원복(PASS 확인)
까지 이번 세션에서 직접 수행. narrow-catch도 실제 함수를 그대로 불러 별도 검증(처음에
함수 자체를 몽키패치해 공허하게 통과하던 것을 mutation으로 잡아 직접 고쳤다).

**doc_raw 백필 공백 재확인 (미해결, DB 쓰기라 승인 영역)** - `document_status` READY
555행인데 `doc_raw` 0행(Sprint 144 때와 같은 증상 재발). 기존 `backfill_doc_raw.py`
dry-run: 기록 예정 555 / 문제 0. 영향은 제한적 - 문서 열람(`available`/`viewer_url`)은
정상, `page_count`/`file_size`/`doc_version`만 계속 null이라 문서 뷰어 페이지네비만 저하.

**스케줄러 재확인** - `DOJOONPASS_DAILY`는 여전히 `LastTaskResult 0x800710E0`으로
실패 상태(변동 없음). `register_scheduler_tasks.ps1`을 dry-run으로 재실행해 3개 작업
전부 미등록·선행조건 OK·계정 함정(SYSTEM 등록 금지)을 도구로 재확인.

테스트: 통과 **45** / 실패 3(의도된 드리프트 가드) / 건너뜀 3 / 판정없음 1
(단언 **7,029건**). node **137/137 PASS**(0 FAIL, 종전 최고 133/137 대비 개선).
