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
