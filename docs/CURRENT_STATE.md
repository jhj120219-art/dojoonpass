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
`deleted_by`, CTO 승인 10건 #6) 누락 → Migration 신설·적용(2026-08-11 Sprint 51 정정:
실제 파일 번호는 **016**이다. 이 기록의 "017"은 잘못된 번호였고, 017은 Sprint 51에서
별도 용도로 신설됐다). 신규 회귀
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

### 2026-08-11 (Sprint 49) 실제 사용자 흐름 완성 + 실행 검증

API 서버 + `npm run dev`를 띄우고 **실제 브라우저**로 전 동선을 확인했다(코드 정적 확인만이
아니라 실동작). 이 과정에서 결함 4건을 재현·수정하고 1건을 측정해 기록했다.

**수정 (`docs/BUGS.md` #29~#32)**
- 정렬 화살표가 데이터와 반대(#29) — `SortBar`의 `sort_order` 기본값을 백엔드와 같은 `desc`로
- 정렬을 바꿔도 페이지 유지(#30) — "감정가 ↓"인데 가장 싼 물건이 보이던 문제. `page=1`로 초기화
- 페이지 범위 초과를 "결과 없음"으로 오인 안내(#31) — 두 상태 구분 + 검색조건 유지 복구 동선
- 목록 컨텍스트 없는 상세의 죽은 "이전/다음" 바(#32) — `navContext.ts` 순수 함수로 분리·수정

**미해결 / 결정 필요 (`docs/BUGS.md` #33) — Release 전 판단 항목**
- 검색 UI 물건종류 **69개 중 60개가 항상 0건**. UI 어휘(Tank Auction 전수 복사)와 크롤러가
  저장하는 값(18종, 복합값 포함)이 다르다. `다세대`(246) `근린시설`(164)
  `상가,오피스텔,근린시설`(202) `오피스텔`(102) 등 **이름으로 도달 불가한 행 745/1,870 ≈ 40%**.
  해결책 3안(UI 어휘 교체 / 백엔드 동의어 매핑 / 크롤러 정규화)이 모두 기존 확정 결정을
  뒤집으므로 임의 수정하지 않고 측정치와 함께 기록만 했다.

**테스트** — 프론트 계약 테스트 29 → **50 검사**(`tests/nav-context.test.mjs` 신규 8 포함).
"200이면 통과"를 넘어 정렬 순서·페이지 내용·결과 주소 등 **실제 응답 데이터**를 단언한다.

**품질 게이트** — Python 회귀 15/15, 프론트 50/50, Type Check / Lint 0 / Build 전부 통과.
QA 데이터 잔여 0건.

### 2026-08-11 (Sprint 50) Release Readiness + 잔여 Backlog

**완료**
- **Next.js 16 `middleware` → `proxy` 규약 전환**: `src/middleware.ts` → `src/proxy.ts`.
  인증 로직은 함수명을 빼면 **문자 단위로 동일**(정규화 비교로 확인). 유일한 실질 변화는
  Next가 강제하는 런타임(Edge → Node.js)이며 `@supabase/ssr`은 양쪽 모두 지원한다.
  빌드 경고 소멸, 게이트/redirect 동작 9항목 브라우저 실측 통과, 계약 테스트 +3검사(50→53)
- **문서 stale 정정**: `FRONTEND_MASTER_SPEC.md` §5.1이 "공통 Header 없음"으로 남아
  §11.2("중복 컴포넌트 금지")와 충돌하던 위험한 기록을 AS-IS로 명시하고 현재 상태를 추가.
  컴포넌트 인벤토리(5→6), `docs/frontend.md`의 "`/`가 redirect한다"(자기 모순) 정정,
  `middleware.ts` → `proxy.ts` 참조 정리(과거 기록은 보존)

**측정만 하고 SKIP (승인/결정 필요)**
- **BUGS #33 물건종류 어휘**: 기본 검색 화면에서 **69개 중 62개(90%)가 항상 0건**,
  이름으로 도달 불가한 행 **진행 중 26/41(63.4%)**. 고쳐야 할 이름은 **6개뿐**이고
  남은 쟁점은 복합값 `상가,오피스텔,근린시설`(202행) 처리 하나. 해결안 3안 비교표 작성.
  **Release Blocking 아님 / 출시 전 결정 필요**
- **BUGS #34 레거시 `/properties`**(신규 기록): 404가 아니라 **항상 엉뚱한 물건이 열린다**를
  실측 확정(강남구 카드 → 관악구 물건). inbound 링크 0건이라 사용자 도달 경로 없음

**Audit 결과** — dead code 0건, 프론트↔서버 API 계약 누락 0건, 아키텍처 불변식 유지,
신규 TODO 0건, 성능 회귀 없음(`proxy.ts` 구간 5~12ms)

**품질 게이트** — Python 회귀 15/15, 프론트 53/53, Type Check / Lint 0 / Build(경고 0) 통과

### 2026-08-11 (Sprint 51) 검색 데이터 품질 + 레거시 정리 + 부트스트랩 복구

사용자 확정 정책: **KG이니시스 실연동만 SKIP**, 나머지는 가능한 범위에서 전부 진행.

**해결**
- **BUG #33 물건종류 검색** — 전수 조사 결과 데이터는 완전히 깨끗했고(토큰 15개, 공백/NULL 0건),
  원인은 **LIKE 방향**이었다(`'%다세대주택%'`이 DB값 `'다세대'`보다 길어 매치 불가).
  `api/v1/search.py`에 어휘 별칭 7개를 **순수 가산**으로 추가 —
  **도달 불가 745행 → 0행**, 기존 9개 항목 건수 전부 불변, UI 어휘·API 계약 무변경
- **BUG #34 레거시 `/properties`** — `/`로 영구 이동. `SearchFilters.tsx`도 함께 제거
- **`src/login/` 제거** — 도달 불가 증명 + §3.4 계약 위반(무방어 redirect) 구현
- **Migration 017 신설** — fresh clone 부트스트랩에서 `document_collect_failures`가
  생성되지 않던 것을 복구. **fresh clone이 운영 스키마를 25/25 완전 재현**
- **`storage/` gitignore 정밀화** — load-bearing 소스 22개가 미추적이던 BUG #28의
  구조적 원인 제거(소스만 추적, 데이터는 계속 무시)
- **잘못된 검색 파라미터 UX** — 400/422를 서버 장애 문구로 오귀인하던 것을 원인별 분기 +
  복구 동선으로 수정(검색/상세 양쪽). API 서버를 실제로 내려 재현 검증
- **BUG #36 신규·해결** — `property_type` 2,000개 입력 시 500 → 상한 100 + 400

**Audit** — 약한 테스트 결함 0건(기존 2건은 이미 강화돼 있음 확인), 별칭 성능 비용 +0.3ms,
크롤러 원자적 쓰기 방어 전 계층 유지

**테스트** — Python 회귀 469 → **494검사**, 프론트 53 → **59검사**, 변이 5종 검출 확인.
테스트 자체의 자기참조 결함 1건 발견·수정

**품질 게이트** — Python 15/15, 프론트 59/59, Type Check / Lint 0 / Build(경고 0) 통과

### 2026-08-11 (Sprint 52) 결제 도메인 내부 완성 + 기술부채 정리

확정 정책: **KG이니시스 실연동만 SKIP**.

**결제 도메인 (`docs/BUGS.md` #38)** — 준비만 되고 호출부가 0건이던 경로를 전부 연결했다.
- `POST /api/v1/admin/payments/{id}/refund` (SUPER_ADMIN) — 전액/부분/반복 환불.
  누적 환불액은 스키마 변경 없이 `payment_logs` CANCEL 합계로 계산. 상태머신 관문 통과 필수,
  멱등, 동시 환불 방어, 감사 로그 기록. provider 미구현이면 상태를 바꾸지 않는다
- `POST /api/v1/payments/webhook/{provider}` — 인증 없는 경로라 서명 검증이 유일한 방어선.
  `verify_webhook_signature()` 신설(**기본 False = fail-closed**), `PAYMENT_WEBHOOK_SECRET`
  미설정이면 전부 401, `event_id` 멱등, 검증 실패도 감사 기록
- `MockProvider.handle_webhook()`이 event_type과 무관하게 항상 SUCCESS를 주던 결함도 수정
- **사업 정책은 만들지 않았다** — 환불 조건/비율, 셀프 환불, 환불 시 구독 해지 여부 SKIP

**`GET /api/v1/subscriptions/me` 신설** — 결제한 사용자가 자기 구독(플랜/만료/유예/이용가능)을
볼 방법이 아예 없던 공백. 마이페이지 화면 스펙은 미정이라 API만 완성했다.

**Frontend 기술부채 3건** — 카드 "조회수 -"(항상 빈 죽은 UI) 제거 / `crawl_date` 정렬 UI 노출
(도달 불가 정렬이었음) / 비로그인 검색조건 저장 시 입력하던 **이름** 보존

**`audit_logs` QA 잔여 792행 정리 (#39)** — cleanup이 `user_id` 없는 테이블을 못 지우던 공백.
검증 체크가 공허하게 참이던 허점도 수정. 이제 회귀 후 감사/Webhook/결제로그 전부 0행

**테스트** — Python 494 → **569검사**, 프론트 59 → **64검사**, 변이 5종 검출

**품질 게이트** — Python 15/15, 프론트 64/64, Type Check / Lint 0 / Build 통과

**신규 환경변수** — `PAYMENT_WEBHOOK_SECRET`(선택, 미설정이 안전한 기본값. 값은 운영자 생성)

### 2026-08-11 (Sprint 53) Webhook 운영 도구 + 인증 경계 전수 + 기술부채 정리

**신설** — Webhook 운영 엔드포인트 3개(`docs/BUGS.md` #41)
- `GET /admin/payments/webhooks` (ADMIN) — 필터·페이지네이션 + `reprocessable`/차단 사유
- `GET /admin/payments/webhooks/{id}` (ADMIN) — 원문 payload·실패 사유
- `POST /admin/payments/webhooks/{id}/reprocess` (**SUPER_ADMIN**) — 수신 경로와 같은
  `_apply_webhook_event()`를 타므로 상태머신 우회 없음, 성공 시 PROCESSED로 중복 재처리 자동 차단

**보안 결함 2건 수정 (#42)**
- **저장소 증폭**: 인증 없는 Webhook이 익명 요청마다 DB 행 생성(5회→5행) → 검증 전 저장 금지.
  실측 재검증 **익명 20회 → 0행**
- **event_id oracle**: 중복 검사가 서명 검사보다 앞이라 서명 없이 존재 여부 탐지 가능 → 구조적 제거

**테스트 강화**
- **인증 경계 전수(§33)** — OpenAPI 전 엔드포인트 열거. 분류 안 된 신규 엔드포인트는 실패.
  결과: 공개 8 / 사용자 16 / 관리자 16 / 서명보호 1, **익명 도달 가능 0건**
- **하네스 결함 수정(#43)** — 실패 출력의 제품 문자열이 cp949에서 크래시해 회귀가
  "FAIL"이 아니라 "중단"으로 보이던 문제. 출력 함수 한 곳에서 차단

**기술부채 해소**
- 계약 테스트 `before()` 서버 의존 → `tests/source-contract.test.mjs` 분리(서버 없이 10/10)
- `.env` BOM 제거(#35 해결, 본문 SHA256 동일 — 값 무변경)
- `storage/migrate_doc_collect.py` 제거(017로 대체, 부트스트랩 25/25 재현 재확인)
- `AuditTargetType.PAYMENT_WEBHOOK` 신설, cleanup 순서 버그 수정

**검토 후 유지 결정** — `TossProvider`/`PortOneProvider`(제거 시 운영자 진단이 나빠짐),
개별 차종·면적·특수조건 검색(대응 컬럼 0개, 크롤러+스키마 선행 필요)

**테스트** — Python 569 → **616검사**, 프론트 64검사, 변이 8종 검출, 3회 연속 잔여 0

**품질 게이트** — Python 15/15, 프론트 64/64, Type Check / Lint 0 / Build(경고 0) 통과

---

## 2026-08-11 Sprint 54 기준 실측

### Release Blocking (2건)

1. **KG이니시스 실연동 미완** — 기존 항목. 결제 도메인은 Mock으로 end-to-end 동작하지만
   실제 PG 호출은 없다. 외부 계약/Secret 발급이 필요해 Sprint 지침상 계속 SKIP.
2. **크롤 파이프라인 8일 중단 (BUGS #46)** — 신규. 저장소 안의 원인 3개는 이번에 고쳤고
   운영 조치 3개가 남았다. 조치 없이는 **2026-08-13부터 검색 결과가 0건**이 된다.

### 데이터 실측 (2026-08-11)

```
auction_item                 1,870건
  auction_date >= 오늘          41건   (08-11에 27, 08-12에 14)
  crawl_date 최신          2026-08-01   (10일 경과)

rights_summary                 162건 / 1,870  (8.7%)
  진행 중 물건 중                  1건 / 41
  19개 분석 컬럼 중 14개가 100% NULL
  (risk_level / risk_reason / analysis_explanation / estimated_inheritance /
   foreclosure_note / priority_right / total_deposit / lien_exists 등)
tenant_rights                  523행  (SPEC 242 / STATUS 281)

document_status    COLLECTING 5,593 / READY 14 / FAILED 3
document_queue     pending 2,703 / done 591
doc_raw                          0행
parsed_document                  0행
```

권리분석 화면은 **거의 모든 항목이 "정보 없음"**으로 뜬다. 화면 결함이 아니라
문서 수집·파싱이 멈춰 있어서다(#46과 같은 뿌리).

### 실행 환경

```
인터프리터   C:\Users\jhj12\AppData\Local\Programs\Python\Python312\python.exe  (3.12.10)
             (배치가 가리키던 C:\ProgramData\Anaconda3\python.exe 는 존재하지 않음)
설치됨       fastapi 0.141.1 / uvicorn 0.52.1 / pydantic 2.13.4 / python-jose 3.5.0 /
             cryptography 50.0.0 / python-dotenv 1.2.2 / requests 2.34.2 / httpx 0.28.1
미설치       selenium / pandas / pdfplumber / webdriver-manager
             -> test_db.py / test_docs.py / test_docs2.py 실행 불가, 크롤러 기동 불가
예약 작업    등록된 248개 중 이 저장소를 가리키는 것 0개
디스크       859.2 GB 여유 (2026-08-02의 "No space left on device"는 해소됨)
```

### 테스트 현황

```
Python  test_api_regression.py       616검사 PASS
        나머지 18개 파일             15 PASS / 3 실행 불가(selenium)
프런트  node --test tests/**          86검사 PASS  (35 suites)
변이    rightsAnalysis 5/5 + requirements 4/4  전부 검출
정적    tsc --noEmit 0 / eslint 0 / next build 성공 (/mypage 포함 10 페이지)
```

### 승인 대기로 막혀 있는 것

- **Admin 운영 UI** — 인증이 공유 `X-Admin-Key` 하나뿐이고, `audit_logs.admin_id`에
  사람이 아니라 역할 문자열(`admin_role`)이 기록된다. 환불(실제 금전)이 누구 소행인지
  남지 않는다. 브라우저 UI는 그 키 보유자만 늘리므로 **운영자별 신원 체계가 선행**돼야 한다.
- **권리분석 "정보원" 표기 (BUGS #45)** — 원본 문서 확보 여부와 파싱 데이터 존재 여부가
  한 이름으로 표시돼 서로 모순된다. 표기 방식은 화면 설계 결정.

---

## 2026-08-11 Sprint 55 기준 실측

### 파이프라인 연결 상태 (가장 중요한 발견)

배치가 실행하는 것과 데이터를 채우는 것이 **끊겨 있다**.

```
스케줄러 도달 가능    mvp_scraper / migrate_execute / doc_worker / refresh_priority
스케줄러 도달 불가    collect_documents.py  analyze_docs.py
                     load_rights_data.py   load_spec_data.py
```

아래 네 스크립트가 `document_status`(Sprint 55 전) / `doc_raw` / `parsed_document` /
`tenant_rights` / `rights_summary`를 쓰는 **유일한 코드**다. 배치 3종의 import를 재귀로
따라가도 도달하지 않는다. 권리분석 커버리지 8.7%의 근본 원인이며, 배치에 넣는 것은
운영 스케줄 결정이라 SKIP했다.

### 데이터 실측

```
auction_item        1,870      document_queue      3,480 (pending 2,703 / done 591 / SKIPPED_EXPIRED 186)
rights_summary        162      document_status     5,610 (READY 588 / COLLECTING 5,019 / FAILED 3)
tenant_rights         523      doc_raw                 0
                              parsed_document          0

document_status READY   14 -> 588   (Sprint 55에서 574행 보정, 디스크 실물 기준)
자기 item_no로 큐에 없는 물건  716 -> 구조 수정 완료, 기일 남은 대상 10건은 다음 수집 때 채워짐
```

### 데이터 무결성 (전수)

```
고아 행 (7개 참조 경로 전수)                    0
필수 필드 결측  auction_date 1건 / sido 3건 / 그 외 0
가격 이상 (최저가>감정가, bid_rate 범위 밖)      0
큐에 있으나 auction_item에 없는 (사건,물건)      0
property_type과 실제 내용 불일치                 2건 (id=317, id=11804)
면적 10만㎡ 초과                                8건 (지분 매각이라 표기 면적이 전체 필지)
```

### 검색 Backlog 재조사 (면적 / 차종 / 특수조건)

| 항목 | 데이터 존재 | 결론 |
|---|---|---|
| 면적 | **이미 수집됨** — `full_address`의 99.0%에 면적 수치(㎡ 1,952 / 평 14) | 크롤러 변경 불필요. 다만 2.4%가 층별 다중 면적이고 지분 매각은 표기가 전체 필지라, **어느 값을 색인할지가 제품 결정** |
| 차종 | 텍스트로는 존재(`[카니발 리무진 2020년식 승용차]`) | 대상이 13건뿐이고 자유 텍스트라 신뢰도 낮음. 구조화 수집 선행 필요 |
| 특수조건 | 없음 | 대응 컬럼·수집 항목 모두 없음 |

로드맵의 "셋 다 크롤러 수집 항목 추가가 선행돼야 한다"는 서술은 **면적에 한해 부정확**했다.

### 성능 (실측, 최적화 불필요)

```
document_status by item_id   0.028ms   index
tenant_rights by item_id     0.034ms   index
rights_summary by item_id    0.029ms   index
Sprint 55 신규 JOIN 조회      0.027ms   index (COVERING)
worker claim 쿼리            idx_queue_status + TEMP B-TREE (pending 2,703건 규모에선 무영향)
```

### Release Blocking (2건, 변동 없음)

1. **KG이니시스 실연동** — 계속 SKIP
2. **크롤 파이프라인 중단** — 저장소 측 원인은 Sprint 54·55에서 전부 제거했다.
   남은 것은 운영 조치 3건(`pip install`, 예약 작업 등록, 크롤 1회 실행)뿐이다.
   조치 없이는 **2026-08-13부터 검색 결과 0건**.

### 승인 대기로 막혀 있는 것

- **Admin 운영자 신원 체계** — 16개 라우트 전부 권한 가드가 있고 변경 6개 전부 감사 로그를
  남긴다(전수 확인). 그러나 `record_audit(admin_id=admin_role)` — 사람이 아니라 역할
  문자열이 기록된다. 환불이 누구 소행인지 남지 않으므로 브라우저 UI는 여전히 선행 조건 미충족.
- **파이프라인 후반 4개 스크립트의 스케줄 편입** — 운영 스케줄 결정
- **면적 색인 기준** — 다중 면적/지분 매각을 어떻게 다룰지는 제품 결정

---

## 2026-08-11 Sprint 56 기준 실측

### 파이프라인 정합 (Sprint 55 수정 이후 재측정)

```
done 591건  -> 파일 없음 0 / document_status 없음 0 / READY 아님 0 / 대응 물건 없음 3
파일 588개  -> 큐가 done 아님 0
큐 상태     -> in_progress 정체 0 / retry 불일치 0 / 기일 남은 SKIPPED_EXPIRED 0
고아 행     -> 5개 참조 경로 전부 0
```

단계 간 불일치가 **0**이고, `test_pipeline_integrity.py`(30검사)가 이를 불변식으로 고정한다.

남은 공백은 파싱 단계 하나다.

```
SPEC   READY 197 / 파싱됨 116  (미파싱 81)
STATUS READY 194 / 파싱됨 161  (미파싱 33)
APPRAISAL           파싱 대상 테이블 없음
진행 중 물건 41건 중 큐에 있는 것 31건 (나머지 10건은 다음 수집 때 충전)
```

### 동시성 방어 (BUGS #53 — 검증이 무의미했던 것을 정상화)

| 가드 | 변이 검출 (수정 전 → 후) |
|---|---|
| 등기부 무료한도 `BEGIN IMMEDIATE` | 2/3 → **4/4** |
| 관리자 전이 조건부 UPDATE | 0/4 → **4/4** (결정적 구조 검사) |
| 결제 주문 `BEGIN IMMEDIATE` | 원래부터 검출됨 |
| 환불 `BEGIN IMMEDIATE` | 원래부터 검출됨 |

### 결제 도메인 감사 결과

- Admin 16개 라우트: 권한 가드 16/16, 변경 6/6 감사 로그 (Sprint 55 확인 유지)
- 미결제 → 완료 전이 **차단됨**(`ALLOWED_TRANSITIONS`에 `PAYMENT_REQUIRED` 키 없음) + 회귀 추가
- 다운로드 게이트: 소유권 + `COMPLETED` + 경로 탈출 검사 3중
- 무료/유료 판정, 멱등 처리, 원장 기록 전부 `BEGIN IMMEDIATE` 안에서 수행
- 변이 5종 전부 검출

### 테스트 현황

```
Python  test_api_regression.py       627검사
        그 외 21개 파일              19 PASS / 3 설계상 건너뜀
프런트  node --test tests/**          93검사 (37 suites)
변이    파이프라인 9/9 · 결제 5/5 · TOCTOU 4/4 · 무료한도 4/4
정적    tsc 0 / eslint 0 / build 성공
```

### 알아 둘 함정

프런트엔드 테스트는 dev 서버가 없으면 `frontend-contract.test.mjs` 전체가 **cancelled**가 되고,
출력이 `pass 45 / fail 0`으로 보인다(종료 코드는 정상적으로 1). `fail 0`만 읽으면 초록으로
오인한다 — **`cancelled`와 종료 코드를 함께 봐야 한다.**

---

## 2026-08-11 Sprint 57 기준 실측 — `auction.db` 되돌아감 재발견·복구

`/goal` 자동 루프 지시에 따라 과거 Sprint 보고서를 신뢰하지 않고 코드/DB 실측부터
다시 시작했다. 그 결과 Sprint 51/52/55가 "완료"로 기록한 작업 3건이 이 저장소의
`auction.db`에서 **사라져 있었음**을 발견하고 복구했다(`docs/BUGS.md` #57).

**발견 → 복구**

1. `migration_history`가 Sprint 51 이전 옛 파일명(`016_create_audit_logs.sql`,
   `017_add_soft_delete_columns.sql`)만 기록하고 있었고, 현재 추적 파일(`016_create_audit_and_credit_logs.sql`,
   `017_create_document_collect_failures.sql`, `018_document_queue_item_no_unique.sql`)은
   한 번도 적용되지 않았다 — `run_migrations.py`를 그대로 돌리면 `duplicate column name`으로
   **전체 마이그레이션이 중단**됨을 사본으로 재현 확인. 이미 존재하는 부분은 건너뛰고 누락된
   인덱스 9개만 실제로 생성한 뒤 `migration_history`를 정합화
2. Migration 018(`document_queue` UNIQUE에 `item_no` 포함, BUGS #48)이 **실제로는 반영되지
   않고 있었다** — 자기 item_no로 큐에 없는 물건이 751/2,012건(37.3%)으로, Sprint 55가
   처음 발견했을 때 규모(38%)와 사실상 동일하게 재발. 실제로 적용 후 `enqueue_documents()`를
   현재 데이터 전량으로 재호출 — 매각기일이 남은 물건은 **전부** 자기 item_no로 큐에 등록됨
3. `audit_logs` dangling 698행 재발(Sprint 52 #39가 "0행"으로 기록) — 삭제
4. `document_status` COLLECTING↔READY 574행이 Sprint 55(#50) 수정 이전 상태로 재역행 —
   `repair_document_status.py --apply` 재실행으로 재보정(디스크 실물 기준, 동일 스크립트)
5. 드리프트를 유발한 미추적 중복 파일 3개 삭제(`storage/migrations/016_create_audit_logs.sql`,
   `017_add_soft_delete_columns.sql`, `storage/migrate_doc_collect.py` — 셋 다 이전 Sprint가
   "제거/대체 완료"로 기록했던 것들이 디스크에 남아 있었다)

작업 전 `auction.db.backup_before_migration_reconcile_20260811_233247` 백업 생성.
네 증상 모두 새 정책 결정이 아니라 **이미 승인·완료된 작업의 재적용**이라 승인 없이 즉시 처리했다.

**품질 게이트** — Python 회귀 15개 파일 전부 PASS(`test_db.py`는 설계상 SKIP),
`test_schema_hygiene.py`/`test_pipeline_integrity.py`(이번에 새로 드러난 실패 포함)
전부 PASS로 전환, 프런트 계약 93/93 PASS(API+dev 서버 동시 기동, `cancelled: 0` 확인),
Type Check / Lint(0) / Build(경고 0) 전부 통과.

**남은 것**: `auction.db`가 왜 되돌아갔는지(OneDrive 동기화, 수동 백업 복원 등)는 특정하지
못했다. `auction.db`는 애초에 git 비추적이라 같은 일이 다시 벌어져도 git으로는 막을 수
없다 — `test_schema_hygiene.py`/`test_pipeline_integrity.py`/`test_api_regression.py`의
실측 기반 무결성 검사가 유일한 방어선이며, 이번에 그 검사들이 실제로 문제를 잡아냈다.
**모든 Sprint 실행 시작 시 이 세 파일부터 돌려 DB 상태를 재확인하는 것을 권장한다** —
문서의 "완료" 기록을 그대로 믿지 않는다는 이 프로젝트의 원칙이 정확히 이 사고에 적용됐다.

### Release Blocking (변동 없음)

1. KG이니시스 실연동 — 계속 SKIP(외부 계약 필요)
2. 크롤 파이프라인 운영 조치(selenium 설치, 예약 작업 등록) — 여전히 미착수, 저장소 측
   원인은 Sprint 54/55에서 이미 제거됨. 이번 Sprint의 document_queue 복구로, 크롤러가
   다시 돌기 시작하면 이전보다 더 많은 물건이 정확하게 큐에 오른다(item_no 결손 해소)

---

## 2026-08-12 Sprint 58 — Admin 키 상태 재확인 + 환불/Webhook 재처리 동시성 커버리지

`/goal` 지시에 따라 Backend API Contract Audit을 계속하던 중 두 가지를 확인·보완했다.

**1. `ADMIN_API_KEY`/`SUPER_ADMIN_API_KEY`가 실제로는 이미 설정되어 정상 동작 중임을 확인**

문서 여러 곳(`docs/ENVIRONMENT_VARIABLES.md`, `docs/roadmap.md` 등)이 "미설정 → Admin API
전체 500"으로 기록하고 있었으나, 실제 요청으로 재확인한 결과 두 키 모두 설정되어 있고
정상 동작한다(`ADMIN_API_KEY`로 일반 Admin 라우트 200, 잘못된/누락 키 403, `SUPER_ADMIN_API_KEY`
전용 라우트에 일반 `ADMIN_API_KEY`를 쓰면 403 — 등급 분리도 정상). 두 값을 운영자가 이미
설정한 것으로 보이며, `docs/ENVIRONMENT_VARIABLES.md`를 실측 기준으로 정정했다. `SUPABASE_JWT_SECRET`은
여전히 이름 자체가 없지만, 2026-08-10 Sprint 46부터 JWKS/ES256이 주 경로라 실사용자 인증에는
영향이 없음을 코드(`api/auth.py`)로 재확인해 문서의 "예 — 필요" 서술도 정정했다.

**2. 환불/Webhook 재처리 동시성 회귀 신설**

Admin 41개 엔드포인트를 API Contract Audit으로 훑다가, 환불(Sprint 52 신설)과 Webhook 재처리
(Sprint 53 신설) 둘 다 소스에는 `BEGIN IMMEDIATE` + 조건부 UPDATE 가드가 있는데 `test_race_conditions.py`에는
두 경로 모두 동시 요청 회귀가 없었음을 발견했다(순차 재현만 `test_api_regression.py`에 있었다).
Sprint 38의 교훈("순차 재현만으로는 동시성 결함을 검출 못한다")이 아직 이 두 경로에는
적용되지 않은 상태였다 — **버그는 아니지만 검증 공백**이었다.

신규 3개 시나리오 추가(22 → 41검사):
- 환불 3스레드 동시 요청(결제액의 절반보다 큰 부분환불을 동시에 3번 — 총 환불액이 결제액을
  넘지 않는지)
- 환불 가드 결정적 구조 검사(`BEGIN IMMEDIATE`/조건부 UPDATE/rowcount/rollback/409)
- Webhook 재처리 가드 결정적 구조 검사(`reprocess_webhook`과 `_apply_webhook_event`가 실시간
  수신 경로와 같은 가드를 공유하는지)

**변이 검증**: `BEGIN IMMEDIATE` 제거와 UPDATE의 `WHERE status=?` 제거 두 변이를 각각 넣어
확인한 결과, **3스레드 재현은 둘 다 놓쳤다**(Sprint 56이 Admin TOCTOU에서 겪은 것과 동일한
"좁은 창" 한계 — `BEGIN IMMEDIATE`가 전체 구간을 이미 직렬화해 안쪽 가드까지 창을 벌리지
못한다). 구조 검사는 두 변이 모두 결정적으로 검출했다. 수정 후 원복해 정상 통과를 재확인했다
(git diff 0 — 실제 소스 변경 없음, 테스트만 추가).

**품질 게이트**: `test_race_conditions.py` 41/41, `test_api_regression.py` 627검사,
`test_schema_hygiene.py`/`test_pipeline_integrity.py` 전부 PASS(Sprint 57 상태 유지 확인),
`python -m compileall` 클린, TypeCheck/Lint 통과.

**문서**: `docs/ENVIRONMENT_VARIABLES.md`(Admin 키 상태 정정), `docs/TEST_PLAN.md`(Sprint 57
누락분 + Sprint 58 신규 시나리오).

---

## 2026-08-12 Sprint 59 — Admin 구독 상태 변경 동시성 결함 발견·수정

Backend API Contract Audit을 계속하던 중 **실제 기능 결함**을 발견해 즉시 수정했다
(`docs/BUGS.md` #58).

`PATCH /admin/subscriptions/{id}`(구독 상태 변경, 과금에 직접 영향을 주는 SUPER_ADMIN 전용
엔드포인트)의 유일한 구현부 `api/v1/subscriptions.py:change_status()`에 동시성 방어가
전혀 없었다. 등기부 신청 상태전이(#21)/결제 환불/Webhook 재처리는 전부 `BEGIN IMMEDIATE`
+ 조건부 UPDATE + rowcount 확인으로 방어돼 있는데 이 경로만 예외였다.

실측 재현(5회) 결과 서로 다른 목표 상태로 동시 PATCH를 보내면 **매번 둘 다 200 성공**을
응답했다 — 진 쪽 요청도 자신이 요청한 상태가 반영됐다고 믿게 되는, 조용한 데이터 손실보다
나쁜 "거짓 성공" 패턴이었다.

등기부(#21)와 동일한 패턴(`BEGIN IMMEDIATE` + `WHERE id=? AND status=?` + rowcount → 409)으로
수정. 수정 후 5/5 재현 전부 정확히 1건만 200, 최종 DB 상태가 성공 응답과 항상 일치함을 확인.

`test_race_conditions.py`에 실스레드 재현 + 결정적 구조 검사 2개 시나리오 추가(41 → 49검사).
두 변이(락 제거/조건부 WHERE 제거) 모두 구조 검사가 결정적으로 검출, 스레드 재현은 이번에도
좁은 창 때문에 놓쳤다(refund/webhook 재처리 감사에서 이미 확인한 것과 같은 한계 — 그래서
두 검사를 함께 둔다).

**품질 게이트**: `test_race_conditions.py` 49/49, `test_api_regression.py` 627검사 무변동,
`test_schema_hygiene.py`/`test_pipeline_integrity.py`/`test_state_machines.py` 전부 PASS,
`compileall`/TypeCheck/Lint(0)/Build(경고 0) 전부 통과.

**문서**: `docs/BUGS.md` #58, `docs/TEST_PLAN.md`/`docs/CHANGELOG.md` 갱신.

---

## 2026-08-12 Sprint 60 — 만료 구독 재활성화가 항상 조용히 실패하던 결함 발견·수정

Sprint 59(#58)를 고치며 `change_status()`를 정독하다 이어서 발견했다(`docs/BUGS.md` #59).

함수 자신의 docstring이 "ACTIVE: 만료된 구독을 되살리는 경우라면 호출부가 새 expires_at을
함께 넘긴다"고 명시하는데, 정작 함수 시그니처에 그 값을 받을 매개변수가 없었다. 만료 시각을
올바르게 연장하는 `renew()` 함수도 저장소 전체에서 호출하는 곳이 0곳 — 준비만 되고 배선이
안 된, 이 저장소에 반복되는 패턴(KG이니시스 스텁과 같은 부류)이었다.

**재현**: 만료된 구독(5일 전 만료)에 Admin이 `{"status": "ACTIVE"}`만 보내면 **200이
오지만 같은 응답 안의 `effective_status`가 이미 "EXPIRED"** — 응답 자체가 자기모순이고,
다음 조회에서 DB도 다시 EXPIRED로 돌아와 있었다. CS가 고객 지원 차원에서 구독을 되살려
주려 해도 이 엔드포인트는 **항상, 아무 신호 없이** 실패했다.

**수정**: `change_status()`에 `new_expires_at` 매개변수를 추가하고, 만료된 구독을 ACTIVE로
되돌리는데 이 값이 없으면 신규 예외(`ReactivationRequiresNewExpiry`)로 명확히 거부(400)하도록
했다. 며칠을 연장할지는 요금 정산 정책이라(`subscriptions`에 `billing_cycle`도 없어 원래
결제 주기 역산도 불가능) 서버가 추측하지 않고 Admin이 `expires_at`을 명시하게 했다 —
`refund` 금액을 Admin이 직접 지정하는 것과 같은 원칙. PAUSED→ACTIVE(재개, 만료 전)는
기존과 동일하게 `expires_at` 없이도 정상 동작(회귀 없음, 실측 확인).

**품질 게이트**: `test_api_regression.py` 627 → **638검사**(§27에 11개 신규 — 거부/성공/
재개 3갈래 전부), `test_race_conditions.py` 49/49(§10 구조 검사를 4개 UPDATE 분기 전수로
갱신), `test_schema_hygiene.py`/`test_pipeline_integrity.py`/`test_state_machines.py`/
`test_subscription_policy.py` 전부 PASS. `compileall`/TypeCheck/Lint(0)/Build(경고 0)
전부 통과.

**문서**: `docs/BUGS.md` #59.

---

## 2026-08-12 Sprint 60 마무리 — Release 준비 최종 검증

Sprint 59~60(#58/#59)을 커밋 전 최종 점검했다. 사용자가 지정한 11개 회귀 체크리스트를
하나씩 대조하다 **ACTIVE → CANCELLED / ACTIVE → EXPIRED가 실제 Admin 엔드포인트를 통해
검증된 적이 없음**을 발견했다(내부 상태머신 순수 로직 테스트는 있었지만, `change_status()`의
CANCELLED/EXPIRED 종결 분기를 실제 HTTP 경로로 왕복 확인한 테스트는 없었다) — `test_api_regression.py`
§27에 각각 4개씩(성공 200/응답 status/DB 반영/만료 시각이 과거로 당겨짐) 8개 신규
(638 → **646검사**).

**마무리 검증 결과**:
- 회귀 체크리스트 11개 전항목 실제 통과 확인(ACTIVE→CANCELLED/EXPIRED/PAUSED→ACTIVE/
  EXPIRED→ACTIVE 거부·성공/형식 오류/404/무효 전이/동시 요청/구조 검사 2종)
- `BEGIN IMMEDIATE` 제거, `WHERE id=? AND status=?` 제거 두 변이 각각 최종 재검증 —
  §10 구조 검사가 결정적으로 검출, 수정 후 정확히 원복(git diff 0)
- 저장소 전체에 mutation-test 임시 코드/디버그 print/scratch 파일 잔여 0건 확인
- `api/v1/subscriptions.py`/`api/v1/admin.py` diff 전문 재검토 — 중복 UPDATE·중복 import·
  구식 코드 잔존 없음
- Python 전체 회귀(15개 실행 가능 파일) + `compileall` + TypeScript + Lint(0) + Build(경고 0) +
  프런트 계약 93/93(API+dev 서버 동시 기동, `cancelled: 0` 확인) 전부 최종 재통과

**품질 게이트(최종)**: `test_api_regression.py` **646검사**, `test_race_conditions.py`
**49검사**, 나머지 Python 회귀 전부 PASS, 프런트 계약 93/93, TypeCheck/Lint(0)/Build(경고 0)
전부 통과. 이번 세션의 코드 변경 범위는 `api/v1/admin.py`/`api/v1/subscriptions.py`
(BUGS #58/#59) + 회귀 테스트(`test_api_regression.py`/`test_race_conditions.py`) +
문서뿐이며, 이와 무관한 파일은 손대지 않았다.
