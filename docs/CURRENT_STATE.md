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
+ Sprint 29(2026-08-08 — Beta Release 전수 감사: 신설 백엔드 모듈(constants/state_machines/
subscriptions/registry_credits/payment_logs/audit) 재검증 중 `get_active_subscription()`의
유예 기간 필터링 결함 발견·수정(미사용 함수라 실사용 영향 없음). **더 중요한 발견**: 이 작업
디렉터리의 `.env`/`auction.db`/`storage/migrations/`(전부 git 비추적)가 Migration 010~015
이전 시점 상태로 되돌아가 있어 `docs/BUGS.md` #18이 이 DB 기준 미해결이고 `SUPABASE_JWT_SECRET`
미설정으로 인증도 막혀 있음을 실측(`docs/BETA_RELEASE_CHECKLIST.md` P0-0, `docs/CHANGELOG.md`
Sprint 29 항목 상세). `python-jose` 미설치(Sprint 26부터 알려진 항목)로 백엔드 기동·회귀
테스트는 이번에도 실행 불가. Type Check/Build/Lint는 전부 통과) 완료
+ Sprint 29 이어서(같은 날 재확인 요청 — §13 재실측, 변동 없음 확인 후 계속 진행:
`properties/[id]/page.tsx`가 등기부 "구독 필요" UI를 `registryMessage === '구독이 필요합니다'`
문자열 비교로 분기하던 결함 발견·수정(FavoriteButton.tsx에서 이미 고친 것과 동일 축의
안티패턴, `error` 코드 기반으로 교체) / jose 의존성 없는 순수 로직 회귀 2종 신설
(`test_state_machines.py` 82검사, `test_registry_credits.py` 20검사, 전부 PASS) /
`docs/TEST_PLAN.md`의 "selenium 미설치" 서술이 stale임을 실측 정정(selenium은 실제로
설치돼 있고 크롤러 계열을 막는 것은 python-jose임을 확인)) 완료
+ Sprint 30(2026-08-08 — **CTO "Migration 정합성 복구" 승인**: 없어진 `storage/migrations/
010~016.sql`을 코드의 실제 INSERT/SELECT 문 기준으로 재작성(`auction_case` court_code +
복합 UNIQUE, `auction`/`auction_item` 법원 인식 UNIQUE, `payment_logs`/`payment_webhooks`/
`registry_credits`/`registry_credit_logs`/`audit_logs` 5개 테이블, `registry_requests.reason`).
백업 → 사본 리허설(2회, `PRAGMA foreign_keys` ON/OFF 양쪽 검증) → 실제 `auction.db` 적용 →
사후 무결성 30개 항목 전부 통과 → 기능 스모크 테스트(payment_logs/registry_credits/audit
실제 함수 호출) 전부 통과. `storage/database.py`(`upsert_batch()` 조회·갱신 키에 court_code
추가로 교차 법원 덮어쓰기 **구조적으로 차단**, `PRAGMA foreign_keys=ON`, `CREATE_TABLE_SQL`
정정) / `storage/migrate_v4_1.py`(fresh clone도 같은 제약)까지 함께 수정하고
`init_db→migrate_v4_1→run_migrations` 전체 부트스트랩을 빈 DB에 재현해 검증 완료.
회귀 `test_auction_identity.py` 신설(26검사 전부 PASS, 실제 DB는 읽기 전용/스크래치 사본만
쓰기). 진행 중 발견: `migrate_execute.py`(정상 코드)가 이 스키마 없이는 `INSERT INTO
auction_case`에서 `no such column: court_code`로 **매일 크롤링이 크래시**하고 있었을
Runtime Bug — 이번 복구로 해소. Supabase 키 명명 확인(사용자 요청): `NEXT_PUBLIC_
SUPABASE_ANON_KEY`가 유일한 코드 요구 이름이며 legacy anon/신규 publishable 값 모두 그
이름으로 동작, `SUPABASE_JWT_SECRET`은 여전히 `.env`에 이름 자체가 없음(별개 사안,
`docs/BETA_RELEASE_CHECKLIST.md` P0-4 신규 등록). Type Check/Lint 전부 통과) 완료
→ 승인 없이 가능한 작업 계속 진행 중 (Auth/Payment/Registry 회귀 강화 등 승인 11~26번 대기)
+ Sprint 31(2026-08-08 — Auth Blocker 재확인(변동 없음, `SUPABASE_JWT_SECRET` 여전히 이름
부재) 후 `test_api_regression.py`/`test_subscription_policy.py`(jose로 실행 불가) 전체를
정적 대조해 Sprint 30이 놓친 결함 2건 발견·수정: (1) `get_connection(enforce_foreign_keys=)`
매개변수 부재 → 추가, (2) Soft Delete 컬럼(`favorites`/`search_presets`의 `deleted_at`/
`deleted_by`, CTO 승인 10건 #6) 누락 → Migration 017 신설·적용. 신규 회귀
`test_schema_hygiene.py`(8검사). jose-free 테스트 4종 전부 재통과(136검사), fresh-clone
부트스트랩(001~017) 재현 검증. HTTP 레벨 Auth/Admin/IDOR 등은 여전히 jose 부재로 Skip,
정적 감사는 이전 Sprint 완료분 유효(중복 안 함)) 완료
→ jose/SUPABASE_JWT_SECRET 확보 전까지 코드/테스트/문서 준비 작업 사실상 소진
+ Sprint 32(2026-08-08 — **python-jose 설치 승인**. 저장소 역사상 처음으로 `test_api_
regression.py`(380검사, ADMIN_API_KEY와 동일 패턴으로 SUPABASE_JWT_SECRET 프로세스 전용
주입 추가)/`test_subscription_policy.py`(48항목) 실제 HTTP 레벨 전체 실행 — 연속 2회 전부
PASS, Sprint 30/31의 Migration·Soft Delete·get_connection 수정이 전부 실서버 응답으로
재확인됨. 신규: JWT 만료/서명위조/alg=none 적대적 테스트 3건 추가(전부 방어 확인).
Type/Build/Lint 전부 통과) 완료
→ `.env`의 `SUPABASE_JWT_SECRET` 이름 부재만 남음(운영 배포 시에만 필요, 테스트는 우회
가능해짐) — 승인 없이 가능한 코드/테스트 작업 사실상 완전 소진
+ Sprint 33(2026-08-09 — 저장소 루트 `test_*.py` 전수 재탐색으로 미실행 3종 발견:
`test_intent_analyzer.py`(16검사 PASS, 결함 없음), `test_normalizer.py`(cp949 콘솔
크래시 버그 발견·수정, 29검사 PASS), `test_search.py`(D7 필터 도입 이전 스냅숏이라
11/17 FAIL — 원인 격리 후 `include_closed=True` 적용 + 드리프트 2건만 재동기화, 17검사
PASS). 신규 `test_race_conditions.py`(15검사, 실스레드로 등기부 무료한도·초과결제 동시성
방어 검증 — 문서에 "N스레드 검증"으로만 기록되고 자동화 안 됐던 공백을 메움, 설계 중
발견한 테스트 자체 결함(시나리오 간 데이터 오염, cleanup FK 순서) 수정 후 연속 2회 PASS).
QA 데이터 잔여 30건(레이스 테스트 초기 버그가 남긴 것) 식별·정리, 전 테이블 재확인 완료.
Mass Assignment 점검(신규 결함 없음), 핫패스 쿼리 7종 EXPLAIN QUERY PLAN 실측(전부 인덱스
적중). 자동 회귀 스위트 **10개 파일 전부 PASS**. Type/Lint/Build 전부 통과) 완료
→ 알려진 모든 test_*.py 실행·검증 완료, 승인 없이 가능한 작업 재소진
+ Sprint 34(2026-08-09 — TODO/FIXME 재탐색(신규 0건). API 엔드포인트 31개 전수 목록화 후
테스트 커버리지 대조(단순 재실행이 아니라 "애초에 검사 대상인가" 확인) — `HEAD /item/{id}/
documents/{type}`(프론트가 실제 사용하는 문서 존재 확인 프로브)와 `GET /admin/payments/{id}/
logs`(Admin 전용 결제 로그 조회) 2개 엔드포인트가 테스트 0건이었음을 발견, 회귀 추가(377→387
검사, 연속 2회 PASS). `docs/backend.md`/`docs/roadmap.md`의 stale 서술 정정(FK 미강제·
ADMIN_API_KEY 미설정·REFUNDED 죽은 상태 — 전부 이미 해결됐는데 문서 미반영이었음), 디렉터리
구조 목록에 신규 마이그레이션/모듈 6개 보강. Type/Lint 전부 통과) 완료
→ 알려진 backend 엔드포인트 전수 커버리지 확보, 문서 drift 재정리 완료
+ Sprint 35(2026-08-09 — Beta 사용자 여정을 코드 기준으로 재추적해 "테스트가 있어도 진짜
성공 경로까지 검증하는가"를 감사. §8~10(Payment/Subscription/Registry)이 TEST_USER 하나를
공유하며 이어지는 구조라 이미 사실상 연속 사용자 여정 테스트였음을 확인(신규 아님). 마지막
한 단계(등기부 다운로드)에서 공백 발견: 기존 검사는 "COMPLETED인데 파일 없음" 방어 경로만
있었고 실제 성공 다운로드(200+파일 바이트 일치)는 테스트 0건, 경로 탐색 방어(`commonpath`)도
테스트 0건이었음 — 둘 다 회귀 추가(391검사, 연속 3회 PASS, 임시 파일 잔여 없음 확인).
Type 변경 없음(테스트 파일만 수정)) 완료
→ Beta 사용자 여정 전 단계(회원가입/로그인 제외, Supabase Auth 영역이라 수동 확인 대상)가
HTTP 레벨 회귀로 커버됨
+ Sprint 36(2026-08-09 — Sprint 35의 "방어 경로만 테스트, 성공 경로 미검증" 패턴을
`api/v1/documents.py`(크롤러 수집 SPEC/STATUS/APPRAISAL)에도 동일 적용해 확인. 기존 검사가
200/404 둘 다 통과로 처리해 실제 성공 시 내용이 맞는지 검증한 적이 없었음을 확인·해결
(실존 파일이면 내용 확인, 없으면 임시로 만들어 왕복 후 정확히 그 파일만 삭제 —
`get_doc_dir()` 상용 함수를 그대로 재사용). 391→394검사. `FileResponse` 사용처는
`documents.py`/`registry.py` 2곳뿐임을 grep으로 확정해 같은 패턴의 추가 공백은 없음을
확인. `documents/` 잔여 테스트 콘텐츠 0건, `auction.db` QA 데이터 0건 재확인) 완료
→ 파일 서빙 엔드포인트 전수(2곳)가 성공/방어 경로 둘 다 커버됨
+ Sprint 37(2026-08-09 — **실제 기능 결함 발견·수정**: `create_registry_request()`가 동일
사용자·동일 물건에 대한 중복 신청을 전혀 막지 않아, 반복 호출마다 별도 신청 행이 생기고
매번 무료 등기부 횟수가 추가 소모됨(재현: 같은 item_id 3회 연속 POST → 3행 생성, 무료 3회
소모). `docs/BUGS.md` #19 신규 등록. 승인 없이 수정 가능한 버그로 판단해 즉시 수정 — 진행
중(PENDING/PAYMENT_REQUIRED/PROCESSING) 신청이 있으면 새로 만들지 않고 기존 신청을 그대로
반환(`already_requested` 플래그 추가, 기존 필드 무변경이라 Breaking Change 아님).
COMPLETED/FAILED는 재신청 허용(정당한 재시도 흐름 보존). 회귀 8건 추가(394→402검사, 연속
3회 PASS), 하위 흐름(초과결제)이 의존하는 무료소모 카운트 전제가 깨지지 않도록 서브테스트
부수효과를 FK 안전 순서로 정밀 원복. Type/Lint/Build 전부 통과) 완료
→ Registry 도메인의 핵심 무결성 결함(무료한도 중복 소모) 해소, 승인 없이 가능한 신규 발견
계속 진행 중
+ Sprint 38(2026-08-09 — Sprint 37의 "중복 요청/멱등성 부재" 패턴을 Payment/Subscription/
Registry Credit 도메인으로 확장 감사. **실제 기능 결함 발견·수정**: `create_payment()`가
`payment_type=SUBSCRIPTION` 요청 시 기존 유효 구독(ACTIVE/GRACE_PERIOD) 여부를 전혀 확인하지
않아, 같은 사용자가 반복 구독을 요청할 때마다 새 subscriptions/payments 행이 생겨 중복 결제됨
(실측: PRO 연 구독 2회 연속 요청 → 198,000원 결제 2건, 두 번째는 기간 연장 없는 순수 중복
청구). 프론트(`properties/[id]/page.tsx`)의 구독 UI가 "유효한 구독 없음" 상태에서만
렌더링되고 성공 즉시 스스로 사라져 "이미 구독 중이면 재구독 불가"가 이미 전제된 불변식이었음을
확인 후, 승인 없이 수정 가능한 버그로 판단해 즉시 수정 — 이미 유효한 구독이 있으면 새로
만들지 않고 기존 구독을 그대로 반환(`already_subscribed` 플래그 추가, `payment: null`, 기존
필드 무변경이라 Breaking Change 아님). CANCELLED/EXPIRED 이후 재구독은 정상 허용. `docs/BUGS.md`
#20 신규 등록. OVERAGE_USAGE 결제 경로(조건부 UPDATE로 이미 보호됨), Registry Credit 관리자
조정 경로(의도적 개별 원장 기록이라 중복 방지 불필요), Webhook 수신(HTTP 미노출로 위험 없음),
Subscription 소유권(사용자용 엔드포인트 자체가 없어 IDOR 표면 없음)은 감사 결과 이상 없음
확인. 별도로 FAILED 처리된 등기부 신청의 무료횟수가 환불되지 않는 문제(`RegistryCreditReason.
REFUND`가 정의만 되고 미호출)를 발견했으나 정책 결정이 필요해 Backlog로만 기록, 임의 구현하지
않음. 회귀 재구성 + 신규 6건(402→410검사, 연속 3회 PASS), 연쇄 영향으로 21번(Payment Logs)
테스트를 전용 사용자로 분리. Type/Lint/Build 전부 통과) 완료
→ Payment/Subscription 도메인의 핵심 무결성 결함(구독 중복 결제) 해소, Registry Credit 환불
정책 공백을 Backlog로 확정, 승인 없이 가능한 신규 발견 계속 진행 중
+ Sprint 38 재개(2026-08-09 — Claude Code Auto-update failed로 세션이 끊겼으나 git status/
diff/docs 4종 재확인 결과 이전 작업은 손상·부분 적용 없이 그대로였음(compileall + 회귀
재실행으로 실측 확인), 처음부터 반복하지 않고 더 깊은 감사로 이어감. **실제 기능 결함 추가
발견·수정**: 직전 구독 중복 결제 수정(#20)이 순차 요청만 막고 **동시 요청(Race Condition)은
막지 못함**을 재현 확인 — 같은 사용자가 동시에 10개 스레드로 PRO 연 구독을 요청하면
subscriptions/payments가 각 10행씩 생성(락 없는 SELECT->판단->INSERT 패턴). `registry.py`
(#19)와 동일하게 BEGIN IMMEDIATE로 확인+생성을 원자화해 해결, 동시 10/20스레드 재현 각 3회
반복으로 검증, `test_race_conditions.py`에 3번째 시나리오로 상시 회귀화(15→16검사). 추가로
"결제 실패 후 재시도"가 실제로는 테스트된 적이 없었음을 확인(MockProvider가 항상 SUCCESS라
자연 재현 불가) — provider를 일시적으로 실패하도록 교체해 SUBSCRIPTION/OVERAGE_USAGE 둘 다
검증(실패 시 entitlement 미생성, 재시도는 정상 생성), `test_api_regression.py`에 9검사 추가
(410→419검사). "이미 COMPLETED된 결제 재처리"는 재처리 엔드포인트 자체가 없어 대상 없음,
Subscription IDOR도 사용자용 엔드포인트가 없어 표면 없음(재확인). `get_entitled_subscription()`
쿼리는 EXPLAIN QUERY PLAN으로 인덱스 seek 확인, 락 보유 시간 짧아 성능 우려 없음. 연속 3회
PASS, `auction.db` QA 데이터 잔여 0건, Type/Lint/Build 전부 통과) 완료
→ Payment/Subscription 도메인의 동시성 결함까지 포함해 중복 결제 경로 완전 차단, "순차 재현만
으로는 동시성 결함을 검출 못한다"는 교훈을 `docs/BUGS.md`에 기록, 승인 없이 가능한 신규 발견
계속 진행 중
+ Sprint 39(2026-08-09 — Sprint 38이 남긴 Backlog 3건(Registry Credit FAILED 환불 정책,
Frontend Duplicate-Action Audit, storage/database.py TOCTOU 전수 스캔)을 순서대로 처리.
(1) Registry Credit REFUND는 `add_credit()`의 `VALID_REASON_TYPES`가 애초에 GRANT/DEDUCT/
RESET만 받도록 설계돼 있음을 확인(`docs/backend.md`가 이미 그렇게 문서화) — 버그가 아니라
여전히 정책 미결정 상태라 SKIP 유지. (2) Frontend Duplicate-Action Audit에서 **실제 결함
발견·수정**: `properties/[id]/page.tsx`의 등기부/구독/결제 4개 핸들러가 `FavoriteButton.tsx`가
이미 쓰던 "busy 플래그를 await 이전에 동기적으로 세운다" 패턴을 따르지 않아 빠른 연속 클릭
시 가드가 늦게 걸리는 창이 있었음(백엔드는 이미 안전, 불필요한 중복 요청 자체를 프론트에서
막도록 통일). Search Preset 저장은 중복 방지가 전혀 없음을 재현 확인했으나 프론트에 "중복
불가" 전제가 없어(Registry/Subscription과 다름) 정책 결정 없이 임의로 막지 않고 Backlog
유지(저심각도). (3) storage/database.py TOCTOU 전수 스캔에서 **실제 결함 추가 발견·수정**:
`api/v1/admin.py:update_registry_request_status()`가 SELECT→판단→UPDATE에 현재 status
재확인 조건이 없어, 같은 신청에 서로 다른 목표 상태로 동시 PATCH가 오면 나중에 커밋되는
쪽이 앞선 결과를 조용히 덮어쓸 수 있었음(실측 재현). `payments.py`의 OVERAGE_USAGE와 동일한
조건부 UPDATE+rowcount 패턴으로 수정, 실패 시 409. `upsert_batch`/`claim_next_queue_item`/
`enqueue_documents` 등 나머지는 이미 안전하거나(조건부 UPDATE/UNIQUE) 단일 스케줄 크롤러
프로세스라 실질적 동시 호출 경로가 없어 수정 불필요(문서화만). `test_race_conditions.py`에
4번째 시나리오 신규(15→22검사) — 첫 버전은 승자 판정 코드를 409로만 단정했다가 스레드
스케줄링에 따라 400도 정상 차단 결과일 수 있음을 flaky 실패로 발견해 즉시 보정, 이후 연속
5회 PASS. `test_api_regression.py` 419검사 무변동 PASS. Type/Lint/Build 전부 통과) 완료
→ Admin 상태전이까지 포함해 이 저장소의 모든 "확인 후 쓰기" 다중 사용자 경합 지점을
`BEGIN IMMEDIATE`/조건부 UPDATE 패턴으로 통일, Search Preset 중복 저장은 정책 미결정으로
Backlog 유지, 승인 없이 가능한 신규 발견 계속 진행 중
+ Sprint 40(2026-08-09 — API Response Contract / Frontend State Consistency / 크롤러
TOCTOU 확장 스캔을 순서대로 처리. (1) `api/constants.py:ErrorCode` 40개 전량과
`docs/ERROR_CODES.md`를 1:1 대조 — 불일치 0건(문서 타임스탬프만 stale이라 정정). Admin의
HTTPException 관례도 문서와 일치, Sprint 39의 409 응답도 그 관례를 그대로 따름을 재확인.
(2) Frontend State Consistency Audit — `src/app/search/page.tsx`가 Next.js 서버 컴포넌트로
`searchParams`마다 서버에서 새로 fetch하는 구조라 클라이언트 stale-fetch 레이스가 구조적으로
불가능함을 확인, Favorites/Search Presets도 "서버 응답 확인 후에만 상태 변경"이라 롤백이
불필요한 안전한 구조임을 재확인 — 새 결함 없음. (3) 크롤러(`mvp_scraper.py`/`doc_worker.py`/
`crawler/doc_crawler.py`) TOCTOU 확장 스캔에서 **실제 결함 발견·수정**: `collect_status()`
(현황조사서 html+json)가 최종 경로에 직접 `open().write()`해, 쓰기 도중 프로세스가 강제
종료되면(전원차단/OOM kill) 손상된 파일이 남고 `doc_exists()`(크기>0만 확인)가 이를 "완료"로
오인해 영구히 재수집에서 제외될 수 있었음. `collect_spec`/`collect_appraisal`(PDF)이 이미
쓰던 "다운로드 안정화 확인 + `shutil.move()`(원자적 rename)" 불변식을 status만 못 지키던
구현 공백이라 승인 없이 수정 — html/json 둘 다 임시파일(`.tmp`) 쓰기 후 `os.replace()`로
원자적 교체하도록 변경. `mvp_scraper.py`/`doc_worker.py`/`claim_next_queue_item` 기반 워커
루프는 이미 안전함을 재확인(수정 불필요). 신규 `test_doc_storage_atomicity.py`(Selenium
무의존, 12검사) — 강제종료 시뮬레이션으로 목적지 파일이 손상되지 않음을 검증, 연속 3회 PASS.
`test_api_regression.py` 419검사 무변동 PASS. Type/Lint/Build 전부 통과) 완료
→ 크롤러의 파일 저장 계층까지 포함해 이 저장소의 "확인 후 쓰기"/"쓰기 도중 손상" 방어가
API/DB/파일시스템 전 계층에서 일관됨을 확인, 승인 없이 가능한 신규 발견 계속 진행 중
+ Sprint 41(2026-08-10 — Sprint 40의 크롤러 File/DB Consistency 감사를 10개 구체 시나리오로
심화 검증: collect_document 흐름/저장 성공-실패와 DB 순서/저장 중 예외 시 DB 상태/파일 저장·
DB 실패 조합/DB 완료·파일 없음 조합/재수집/워커 재시작/부분·0바이트 파일/임시파일·overwrite/
재시도 중복처리. 핵심 신규 검증: `mark_queue_done()`의 3단계 쓰기(큐 done/auction 플래그/
버전로그)가 중간에 실패해도 암묵적 rollback으로 부분 반영이 남지 않음을 **실제로 강제
예외를 유발해 재현**해 확인(이론이 아니라 실측), 이어지는 재시도가 완전히 성공함도 확인 —
`test_doc_storage_atomicity.py`에 회귀 테스트로 고정(12→15검사). "DB 완료·파일 없음"은
코드 경로상 도달 불가임을 확인, "동일 문서 재수집"은 `doc_exists()` 가드로 이미 방지되고
`overwrite=True` 호출 경로가 저장소 전체에 0건임도 재확인. 기술부채 1건 발견(수정 안 함):
`document_version_log` INSERT 로직이 `overwrite` 미사용으로 인해 현재 운영 흐름에서
도달 불가능한 죽은 분기임을 확인 — KG이니시스 스텁과 같은 성격의 "미리 준비된 인프라"로
판단해 임의로 제거하지 않고 Backlog(P2)로만 기록. Recent Items 페이지는 읽기 전용이라
중복 액션 위험 없음 재확인. 신규 버그는 없어 `docs/BUGS.md` 갱신 없음(기존 #19~#22가
이번 재검증 대상을 이미 커버). `test_api_regression.py` 419검사, `test_race_conditions.py`
22검사 전부 무변동 PASS, Type/Lint/Build 전부 통과) 완료
→ 크롤러 파이프라인의 실패/재시작/부분쓰기 복원력을 실측으로 확정, 승인 없이 가능한 신규
발견 계속 진행 중
+ Sprint 42(2026-08-10 — Sprint 41 Backlog 4건(court_crawler/base_crawler TOCTOU, API
Response Body 실측 감사, validation.jsonl 동시성, document_version_log dead branch)을
순서대로 처리. (1) `base_crawler.py`는 전부 Selenium DOM 파싱 순수 함수라 TOCTOU 대상 아님
확인. `court_crawler.py:crawl_court()`가 쓰는 `storage/checkpoint.py:CheckpointManager`
에서 **실제 결함 발견·수정**: `save()`/`clear()`가 `logs/checkpoint.json`에 직접
`open(path,"w")`해서, 저장 도중 강제종료되면 파일 전체(=이미 저장된 다른 모든 법원의
체크포인트까지)가 손상될 수 있었음(#22와 동일 부류) — 임시파일+`os.replace()` 원자적 교체로
수정, `docs/BUGS.md` #23. 동시 다중 프로세스 접근은 단일 프로세스 순차 호출이라 실제 경로
없음 확인, 수정 안 함. (2) API Response Contract를 ErrorCode 이름 대조(Sprint 40)를 넘어
실제 HTTP 응답 body까지 확인 — 빈 결과 4종(Favorites/Recent Items/Search Presets/Payments)
전부 envelope 완전 일관, 404/401도 문서화된 FastAPI 표준 형태와 일치, 불일치 0건. (3)
`logs/validation.jsonl`은 `ValidationEngine` 호출부 3곳(mvp_scraper.py 단일 프로세스,
test_db.py 회귀 대상 아님, revalidate.py는 별도 파일 사용) 전수 확인 결과 실제 동시 쓰기
경로가 없어 코드는 변경하지 않고, append-only JSONL의 "마지막 줄만 손상, 이전 줄은 안전"
특성을 실측 검증(신규 테스트). 부수 발견: `revalidate.py`가 하드코딩된 옛 날짜 CSV를
참조하는 죽은 유틸리티임을 확인(P3 기술부채, 삭제 안 함). (4) `document_version_log`/
`overwrite=True` dead branch는 Sprint 41 결론 재확인(변동 없음, P2 유지). 신규
`test_checkpoint_atomicity.py`(15검사)/`test_validation_log_integrity.py`(9검사) 추가,
둘 다 연속 3회 PASS. `test_api_regression.py` 419검사/`test_race_conditions.py` 22검사/
`test_doc_storage_atomicity.py` 15검사 전부 무변동 PASS. Type/Lint/Build 전부 통과) 완료
→ 크롤러 재시작 복원력이 파일 저장(#22)에 이어 체크포인트(#23)까지 전 계층에서 원자적임을
확정, API/Validation Log 계약도 실측으로 재확인, 승인 없이 가능한 신규 발견 계속 진행 중
+ Sprint 43(2026-08-10 — models/auction_item.py, normalizer/normalizer.py, config/settings.py,
config/courts.py 전수 조사 + Frontend↔API Response Contract 실측 대조. **실제 결함 발견·
수정**: `api/v1/search.py:SORT_COLUMNS`(8개) vs `src/app/search/types.ts`의 `sort_by`
유니온 타입(7개) 대조 결과 `crawl_date` 누락 확인 — 타입 파일 자체가 "백엔드 파라미터명과
동일하게 맞춘다"를 명시하는데 그 목적에 어긋났고, `SortBar.tsx` UI도 같은 7개만 노출해
"수집일" 정렬 선택 경로가 아예 없었으며, 회귀 테스트도 `auction_date` 하나만 검증하는 약한
테스트였다. 타입만 정정(`crawl_date` 추가, UI 노출은 별도 제품 판단이라 손대지 않음),
회귀 테스트를 8개 화이트리스트 전수(200 여부+실제 오름차순 정렬 여부까지)로 강화(16검사
신규, 419→434검사), `docs/BUGS.md` #24. 감사 결과 실제 버그는 아니지만 기술부채 발견:
`models/auction_item.py:has_status_pdf`가 DB 컬럼 리네임(`has_status_doc`) 이후에도 옛
이름 그대로이며, `upsert_batch()`가 이 필드들을 항상 0으로 하드코딩해 normalizer.py의
계산 자체가 죽은 코드임을 확인(P3). `config/settings.py:COURTS`(5개, 다른 코드 체계)가
저장소 전체에서 import 0건으로 완전히 죽은 목록임을 확인 — `config/courts.py:ALL_COURTS`
(60개, code=법원명)만 실제로 쓰이고 크롤러/DB/doc_worker 전 구간이 일관됨을 추적 확인(기능
결함 없음), `get_court_by_code()`도 호출부 0건(P3, 둘 다 삭제는 안 함). `ALL_COURTS` 60개
전수 검사로 중복/불일치 0건 확인. Error Handling Audit(API 레이어 전체 `except Exception:`
7곳)도 전부 올바른 rollback-and-reraise 또는 의도적 log-and-continue 패턴임을 확인(수정
불필요). "200/404 둘 다 PASS" 스타일 잔여 패턴 재탐색 결과 1건(`document known type`)
발견했으나 Sprint 35/36에서 이미 실제 파일 내용까지 검증하는 2단계 설계로 강화돼 있던
것으로 확인(추가 조치 불필요). `test_api_regression.py` 434검사 연속 3회 PASS, Type/Lint/
Build 전부 통과) 완료
→ Frontend↔Backend 계약 불일치를 실측으로 찾아내 수정한 첫 사례(그동안은 백엔드 내부
일관성 위주였음), 크롤러/설정/모델 레이어에 남은 죽은 코드를 P2/P3로 전부 정리, 승인 없이
가능한 신규 발견 계속 진행 중
+ Sprint 43 계속(2026-08-10 — Stop Hook 조건에 따라 남은 미검증 영역을 마저 확인. 체크포인트가
저장은 원자적(#23, Sprint 42)이어도 "실제로 올바른 위치부터 재개하는가"는 검증된 적이
없었음을 발견 — `crawl_court()` 인라인 재개 로직을 `resume_start_idx()` 순수 함수로 추출
(동작 변경 없음)해 `test_crawl_resume.py`(10검사) 신규 작성, 정상 매칭/묶인 사건번호 매칭/
체크포인트 사건이 오늘 목록에 없을 때 0으로 안전하게 폴백하는지(데이터 누락 아닌 재크롤링
비효율로만 귀결) 확인 — 실제 버그는 없었고 검증 공백만 해소. `src/` 전체 TODO/dead code
재탐색은 신규 발견 없음(기존 기록과 일치). Admin PATCH 상태전이(§11)와 다운로드 성공(§9)
테스트가 분리돼 있는 게 통합 부족이 아니라 두 관심사(상태전이 규칙 vs 파일 서빙)가 실제로
독립적이라 의도된 설계임을 코드 추적으로 확인 — 추가 테스트 불필요. 연속 3회 PASS, 기존
회귀 전부 무변동 PASS, Type/Lint/Build 전부 통과) 완료
→ 크롤러 재시작 복원력이 "저장(#22/#23) + 재개 위치 계산(신규 검증)"까지 전 계층에서 실측
확정, 승인 없이 가능한 검증 가능한 영역을 모두 소진 — 남은 작업은 전부 정책 결정(Registry
Credit 환불/Search Preset 중복/crawl_date UI 노출) 또는 외부 승인(SUPABASE_JWT_SECRET/
KG이니시스) 대기로 수렴

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

---

## 2026-08-10 (Sprint 44~46) Frontend 재정의 + 인증 체인 복구

**Frontend UX 재정의(Sprint 44~45)**
- `/`가 첫 화면이자 **검색 화면**이다. redirect 없음, 비로그인으로 검색/정렬/페이지 이동 가능
- `/search`는 호환 유지(같은 `SearchScreen` 공유, 복제 없음)
- 상세 `/properties/[id]`, `/favorites`, `/properties/recent`는 **로그인 필수**(middleware 서버 게이트)
- 로그인 redirect가 **query string까지 보존**한다(`docs/BUGS.md` #25)
- 공통 `SiteHeader` + 1320px 중앙 컨테이너, 반응형 1/2/3열
- 프론트 계약 테스트 신설: `npm run test:frontend` (24검사, Node 내장 러너, 새 의존성 없음)

**인증 체인 복구(Sprint 46) — Release Blocker 해소**
- Supabase가 ES256(비대칭)으로 전환된 것을 백엔드가 따라가지 못해 로그인 사용자의 모든 인증
  API가 401이었다(`docs/BUGS.md` #27). `api/auth.py`에 JWKS 기반 ES256 검증을 도입하고
  HS256(레거시)을 함께 지원하도록 고쳤다. `item.py`/`search.py`의 중복 검증도 공용 함수로 통합
- 실제 Supabase 토큰으로 구/신 코드를 비교해 401 → **200** 전환을 확인했다
- **API 서버를 완전히 재기동해야 적용된다**(`--reload`만으로는 반영되지 않는 경우가 있었다)

**현재 릴리스 상태**: 비로그인 검색 경로와 로그인 인증 경로 모두 코드 레벨 검증 완료.
남은 미결정은 `/properties` 레거시 화면 처리와 표기/디자인 관련 UX 결정들이다.

### 2026-08-10 (Sprint 47) 운영 검증 + 테스트 복구

- API 서버를 최신 코드로 재기동하고 **실제 Supabase ES256 토큰으로 인증 API 전부 200** 확인.
  브라우저에서 상세 진입 → 최근조회 기록 → 목록 표시까지 전 스택 실동작 확인
- selenium 의존성 분리(`crawler/doc_paths.py`, `crawler/resume.py`)로 실행 불가였던
  회귀 테스트 2건 복구
- `test_search.py`를 고정 건수 비의존으로 재설계(25검사, mutation 검증)
- `storage/checkpoint.py` 원자적 쓰기 복구(BUGS #28 — #23 수정분이 유실돼 있었음)
- **Python 회귀 15/15 전부 PASS**, 프론트 계약 24/24, Type/Lint/Build 통과

운영 주의: API 서버는 `--reload`만으로 변경이 반영되지 않는 경우가 있으므로 **완전 재기동**한다.

### 2026-08-10 (Sprint 48) 잔여 Backlog 조사 + 안전한 정리

- `/properties`(레거시)·`src/login/`: 도달 경로 **0건** 확정. 삭제/redirect는 정책 결정이라 SKIP
- table view·마이페이지·Admin·권리분석 화면: 구현 0건(미착수) 확정
- CORS: `CORS_ALLOW_ORIGINS` 환경변수로 **이미 제한 가능**. 문서의 "전체 허용 고정" 기록 정정
- `formatPrice`: 동일했던 두 지역 구현을 `formatPriceEok()`로 통합(표시 숫자 무변경).
  표기 기준 통일 자체는 여전히 UX 결정 대기
- `court_code`/`court_name`: 값이 전부 한글 법원명으로 동일 — 경로 불일치 없음(버그 아님).
  DB 컬럼명이 `court_code`라 내부 rename은 하지 않고 주석으로 근거 기록
- Open Redirect 방어 회귀 테스트 추가(계약 테스트 29검사)
- `storage/` git 미추적 소스 **22개** 전수 특정(BUGS #28의 구조적 원인)
