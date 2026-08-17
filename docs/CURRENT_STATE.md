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

☑ Payment Flow Migration (`payments.py`가 `create_order`→`confirm_payment`→`verify_payment` 순서로 provider 호출, `SUBSCRIPTION`/`OVERAGE_USAGE` 둘 다 새 Flow로 정상 동작 확인. `cancel_payment`/`handle_webhook`은 이 시점엔 미연결이었으나 **2026-08-11 Sprint 52에서 연결 완료** — 아래 396행 정정 참고)

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

☑ ~~환불(`cancel_payment`)/Webhook(`handle_webhook`) 엔드포인트 신규 구현 — 여전히 미연결~~ →
**2026-08-11 Sprint 52 완료, 2026-08-15 Sprint 131 재확인**: `api/v1/payments.py:refund_payment()`가
`provider.cancel_payment()`를 호출하고(admin 전용 `POST /admin/payments/{id}/refund`에서
진입), `receive_payment_webhook()`(`POST /payments/webhook/{provider_name}`)가
`provider.handle_webhook(payload)`를 호출해 `_apply_webhook_event()`로 이어진다. 둘 다
`test_api_regression.py`(§30 `test_payment_webhook`)/`test_race_conditions.py`(§9)/
Sprint 129가 계속 실측 확인하고 있다 — 이 줄만 Sprint 52 이전 상태로 남아 있었다.

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
SPEC   READY 197 / 파싱됨 116  (나머지 81 = 임차인 없음 — Sprint 62 실측 정정)
STATUS READY 194 / 파싱됨 161  (나머지 33 = 빈 캡처 결함, Sprint 62 복구 — BUGS #61)
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

---

## 2026-08-12 Sprint 61 — 개인화 도메인 IDOR 전수 감사 + 크롤러 복구 경로 회귀

`/goal` 지시(Admin Contract Audit → Favorites/Presets/Recent Audit → Frontend Contract
Audit → Crawler 운영)를 순서대로 수행했다. **이번 Sprint에서 `api/`·`storage/` 제품
소스는 한 줄도 바꾸지 않았다** — 감사 결과 실제 결함이 0건이었기 때문이다. 대신
"동작은 옳은데 검증된 적이 없던" 영역을 회귀로 고정했다.

### 감사 결과 (전부 실측, 정적 판단 아님)

```
Admin 목록 계약 (필터 정확성/페이지네이션/경계/404/malformed)      결함 0
Favorites·Search Presets·Recent Items IDOR·소유권                결함 0
Frontend TS 인터페이스 ↔ 실제 응답 필드                           누락 0
프런트 호출 경로 ↔ 백엔드 라우트                                  누락 0
크롤러 큐 재시도/복구 배선 (reset_stale_queue → doc_worker)        정상 배선
```

확인한 소유권 경계: A가 B의 즐겨찾기/preset을 지우려 하면 거부될 뿐 아니라 **실제로
지워지지 않는다**. 검색 결과의 `is_favorited`는 요청자 기준이며 위조 토큰으로는
개인화가 적용되지 않는다(익명으로 강등). Recent Items도 사용자 간 완전 격리.

### 신규 회귀 (646 → 660검사, `test_document_queue.py` +8)

그동안 **검사가 0건이던 영역**을 메웠다 — Recent Items의 격리·정렬·LIMIT 20,
`reset_stale_queue()`(doc_worker 크래시 복구), 개인화 3갈래 검증.

`reset_stale_queue()` 회귀에서 가장 중요한 것은 회수가 아니라 **회수하지 않는 것**이다:
살아있는 Worker의 `in_progress` 행을 pending으로 되돌리면 같은 문서를 두 프로세스가
동시에 수집한다. 그 5종(최근 in_progress / 최근 failed / SKIPPED_EXPIRED / done / pending)이
그대로 남는지를 함께 단언한다.

변이 11종 전부 검출, 소스는 SHA256 대조로 **byte 단위 원복 확인**(git diff 0).

### 이번에 배운 함정 — "정렬 검사"는 데이터에 의존한다

같은 뿌리의 문제를 두 곳에서 만났다.

1. recent-items 정렬 검사를 HTTP 연속 조회로 짰더니 `ORDER BY DESC`→`ASC` 변이가
   **통과했다**. Windows 시계 분해능(~1~16ms)보다 요청이 빨라 `viewed_at`이 동률이 되고
   정렬이 tie-break(`ri.id`)로 결정된 탓 — 실데이터 동률은 0건이라 테스트 설계 문제였다.
2. 프런트 계약 테스트의 crawl_date 정렬 검사가 실패했는데 **제품은 정상**이었다
   (`docs/BUGS.md` #60). 크롤 중단으로 진행 중 물건이 전부 같은 crawl_date가 된 탓이다.

둘 다 assertion을 약화하지 않고 **검사 대상 데이터를 유효하게** 바꿔 해결했다.

### 실행 환경 — 크롤러 의존성 설치 완료

```
설치   selenium 4.47.0 / webdriver-manager 4.1.2 / pandas 3.0.5 / pdfplumber 0.11.10
확인   크롤러 계열 19개 모듈 import 전수 성공 (mvp_scraper/doc_worker/migrate_execute/
       collect_documents/analyze_docs/load_rights_data/load_spec_data/refresh_priority 포함)
미실행 실제 크롤 1회, 예약 작업 등록 — 외부 사이트 접속/운영 판단이라 하지 않음
```

Sprint 54부터 "크롤 중단의 직접 원인"으로 기록돼 있던 미설치 항목이 해소됐다.
`requirements.txt`의 stale 서술을 정정하고 실측 버전을 고정했다.

### Release Blocking (2건 — 1번은 오늘이 마지막 날)

1. **크롤 파이프라인 중단 (#46) — 2026-08-13부터 검색 결과 0건**
   ```
   auction_item                    1,870건
     auction_date >= 2026-08-12       14건  (전부 오늘이 매각기일)
     crawl_date 최신             2026-08-01
   ```
   Sprint 54가 예측한 시점과 **정확히 일치**한다. 저장소 측 원인은 Sprint 54/55/57과
   이번 Sprint(의존성 설치)로 전부 제거됐다. 남은 것은 운영 조치 2건뿐이다 —
   **예약 작업 등록 + 크롤 1회 실행**. 조치 없이 내일이 되면 서비스가 빈 화면이 된다.
2. **KG이니시스 실연동** — 외부 계약/Secret 필요로 계속 SKIP(변동 없음).

### 승인/정책 결정 대기 (변동 없음)

- Admin 운영 UI — `audit_logs.admin_id`에 사람이 아니라 역할 문자열이 기록되는 문제가 선행
- Search Preset 중복 저장 허용 여부(현재 동일 이름·조건 중복 저장 가능)
- ~~Recent Items 행 보존 정책 — 저장 행이 무제한 누적~~ → **2026-08-12 Sprint 70 실측으로
  철회.** 이 기술부채 항목은 **사실이 아니었다**(아래 Sprint 70 절 참고). `recent_items`에는
  `UNIQUE(user_id, item_id)`가 있어 같은 물건을 몇 번 다시 봐도 행이 늘지 않고
  `viewed_at`만 갱신된다. 상한은 "그 사용자가 본 **서로 다른** 물건 수"(≤ 전체 물건 수)다.
- Admin 목록의 잘못된 enum 필터 처리 불일치(일부 400, 일부 200-빈결과) — 통일은 계약 변경

---

## 2026-08-12 Sprint 62 — 파이프라인 후반(문서 파싱/권리분석) 실제 결함 2건 발견·수정

Sprint 61이 설치한 selenium/pandas/pdfplumber 덕분에 **이 저장소 역사상 처음으로**
파이프라인 후반 스크립트(`load_rights_data.py` / `load_spec_data.py`)를 실제로 실행해
검증할 수 있었다. 그 결과 문서로만 "미파싱"이라고 기록돼 있던 영역에서 **실제 결함 2건**을
발견해 고쳤다.

### 결함 1 — 빈 현황조사서 캡처가 정상 수집으로 저장됨 (BUGS #61)

`collect_status()`의 대기 조건이 "오버레이 텍스트가 비어 있지 않음"이었는데, 골격에
고정 라벨("사건번호"/"조사일시")이 처음부터 있어 **데이터 도착 전에 즉시 참**이 됐다.
그래서 내용이 하나도 없는 페이지가 저장됐고, `doc_exists()`(크기>0)가 이를 완료로 보아
**영구히 재수집에서 제외**됐다(BUGS #22/#50과 같은 부류).

```
status.html 194건 전수 대조
  정상   161건 : 사건번호 161/161 · 그리드 행 1개 이상 · 23,526~351,375 bytes
  빈 캡처 33건 : 사건번호   0/33  · 그리드 행 0개     · 19,253/19,268 bytes   <- 완전 분리
```

- 크롤러 수정: 대기 조건을 "실제 사건 데이터가 채워짐"으로 교체 + **저장 직전 관문** 추가
  (빈 캡처는 저장하지 않고 실패로 두어 큐에 남긴다)
- 판정 함수는 selenium 무의존 순수 함수(`crawler/doc_paths.py:status_overlay_has_data`)로
  분리해 selenium 없이 회귀 검증이 가능하다
- `repair_empty_status_capture.py` 신설 — 기존 33건을 **삭제하지 않고 격리**한 뒤 재수집
  대상으로 복구(dry-run 기본). 정상 파일이 0건이면 중단하는 안전장치 포함

```
복구 결과   격리 66파일 / document_status 33행 COLLECTING / document_queue 33행 pending
STATUS 파싱 갭   194 READY / 161 파싱 / 33 미해결  ->  161 READY / 161 파싱 / 0
```

### 결함 2 — 근거 문서가 사라져도 권리분석 파생 행이 영원히 남음 (BUGS #62)

`load_item()`이 근거 파일 부재 시 `DELETE` 이전에 early return 해서, 한 번 적재된 뒤
문서가 사라져도 파생 행이 영구히 남았다(실측 item_id=540 — 사건 디렉터리 자체가 부재).
화면은 근거를 확인할 수 없는 "현황조사서 임차인 N명"을 계속 보여준다.

두 스크립트(`load_rights_data.py` / `load_spec_data.py`)에 `purge_orphans()` 추가.
**핵심은 안전장치**다 — 근거 파일을 하나도 못 찾으면 아무것도 지우지 않는다(경로 문제로
전체 권리분석 데이터가 날아가는 것을 막는다. 안전장치를 끈 변이에서 실제로 162행/281행이
전부 삭제되는 것을 확인했다).

```
rights_summary  162 -> 161  (= loaded 161과 정확히 일치)
tenant_rights   523 -> 519  (STATUS 281->279 / SPEC 242->240)
SPEC 재파싱 결과  기존과 완전 동일(추가 0 / 변경 0) — 새 pdfplumber로 인한 드리프트 없음
```

### 문서 정정 — "미파싱 81건"은 사실이 아니었다

여러 문서가 SPEC 81건을 "미파싱"으로 기록해 파서가 고장 난 것처럼 보이게 했다. 실제로
파일을 열어 보니 **파싱은 성공**했고 표 내용이 literally `조사된 임차내역없음`이었다 —
즉 **임차인이 없는 물건**이다. `docs/crawler.md` / `docs/roadmap.md` / `docs/CURRENT_STATE.md`
및 테스트 출력 문구를 실측 기준으로 정정했다.

남은 것은 "확인된 임차인 없음"을 "정보 없음"과 구분해 보여줄지의 **표기 결정**뿐이며,
이는 제품 판단이라 Backlog로만 남겼다(데이터 모델에는 `is_vacant`가 이미 있다).

### 품질 게이트

```
Python test_*.py       24개 파일 전부 PASS (신규 test_rights_data_load.py 27검사 포함)
변이 검증               14/14 검출 — 원래 버그 형태를 재현한 변이 포함, 소스 byte 단위 원복
compileall / tsc / eslint(0) / next build   전부 통과
```

---

## 2026-08-12 Sprint 63 — 문서가 만든 운영 함정 제거 + 크롤러 동시성 핵심 회귀

### 1. 배치에 넣으면 안 되는 스크립트가 "배치 편입 후보"로 적혀 있었다

`docs/crawler.md` / `docs/roadmap.md` 16-A가 파이프라인 후반 **4개 스크립트**의 배치 편입을
Backlog로 두고 있었는데, 그중 `analyze_docs.py`는 **애초에 배치 대상이 아니었다**.

```
analyze_docs.py   DB 쓰기 0줄 (get_connection 0회 / SQL 0회)
                  첫 번째 물건을 하드코딩으로 열어 PDF 텍스트를 화면에 출력
                  마지막 줄: input("엔터를 누르면 종료...")   <- 사람 입력 대기
```

Task Scheduler에서 실행되면 stdin이 없어 **매달리거나 즉시 죽고, 같은 배치의 뒷 단계가
통째로 멈춘다.** 문서의 분류만 믿고 배치에 넣는 순간 사고가 나는 자리였다 — 문서 오류가
그대로 운영 사고로 이어지는 형태다.

`test_crawl_exit_code.py`에 구조적 가드를 신설했다(§8, 12검사).
- 배치 후보 9종 전부에 사람 입력 대기가 없는지
- 반대로 `analyze_docs.py`는 **여전히 대화형인지** + DB를 쓰지 않는지(양방향 검사)

양방향으로 둔 이유는, `analyze_docs.py`가 나중에 진짜 파이프라인 단계가 되면 이 검사가
실패해 "목록과 문서를 함께 갱신하라"고 알리게 하기 위해서다.

문서도 정정했다 — 편입 검토 대상은 **넷이 아니라 셋**이다.

### 2. `claim_next_queue_item()` — 크롤러 동시성의 핵심인데 검사가 0건이었다

Worker가 큐에서 일감을 집는 **유일한 경로**이고 `UPDATE ... WHERE status='pending'` +
rowcount로 동시 클레임을 막는 함수인데, 테스트가 하나도 없었다.
`mark_queue_skipped_expired()`도 마찬가지였다.

`test_document_queue.py`에 17검사 신설(§7~9):
- 선택 규칙(우선순위 ASC → 기일 ASC), pending→in_progress 전이, `last_attempt_at` 기록
- 집으면 안 되는 상태(done/failed/SKIPPED_EXPIRED/in_progress) 제외
- 재시도 간격(30분) 준수 + 간격 경과 후 재클레임
- **8스레드 동시 클레임 12건** — 중복 배분 0, 전건 정확히 1회씩
- `SKIPPED_EXPIRED`가 **재시도 횟수를 소모하지 않는지**(실패가 아니라 "대상 아님"이므로)

### 이 저장소에서 처음으로 스레드 재현이 신뢰할 수 있는 검출기였다

Sprint 58/59는 환불·Webhook·구독 경로에서 "스레드 재현이 변이를 놓치고 구조 검사만
잡아냈다"고 기록했다. 원인은 `BEGIN IMMEDIATE`가 구간 전체를 이미 직렬화해 **안쪽 가드까지
창이 벌어지지 않기** 때문이었다.

`claim_next_queue_item()`은 다르다 — 배타 트랜잭션 없이 조건부 UPDATE만 쓰므로 경합 창이
실제로 넓다. 조건부 UPDATE를 제거한 변이에서 **8스레드 재현이 3회 연속 전부 검출**했다
(중복 배분 발생). 같은 프로젝트 안에서도 가드 구조에 따라 스레드 재현의 유효성이 갈린다는
것을 실측으로 확인한 첫 사례다.

### 3. `parsed_document` / `doc_raw` 실사용 전수 확인

```
parsed_document   쓰는 코드 0곳 / 읽는 코드 0곳          <- 완전히 죽은 테이블
doc_raw           쓰는 코드 1곳(스케줄러 미도달) / 읽는 코드 0곳
```

즉 "파싱 단계가 연결만 안 됐다"가 아니라 **그 단계의 구현 자체가 없다.** 실제로 동작하는
파싱은 `load_spec_data.py` / `load_rights_data.py` → `tenant_rights` / `rights_summary`
경로뿐이다. 또 `docs/crawler.md`가 `doc_raw` 적재의 선행 조건으로 적어 둔 "pdfplumber 미설치"는
Sprint 61에 해소됐다(이제 남은 것은 순수한 소유권 결정뿐). 세 서술 모두 정정했다.

### 품질 게이트

```
Python test_*.py       24개 파일 전부 PASS
변이 검증               21/21 검출 (Sprint 61~63 누적), 소스 byte 단위 원복
프런트 계약             93/93 (cancelled 0)
compileall / tsc / eslint(0)   전부 통과
```

---

## 2026-08-12 Sprint 64 — Admin↔사용자 상태 일관성 + 조정·사용 혼합 산술 검증

이번 Sprint는 **제품 결함 0건**이다. 대신 "각자는 검증됐지만 둘이 만난 적이 없는" 경계
두 곳을 찾아 회귀로 고정했다. 조사 중 나온 의심 2건은 실측으로 **오탐임을 확인**하고
버그로 기록하지 않았다.

### 1. Admin 변경이 사용자 상태에 반영되는가 (§31-B, 25검사 신규)

§27(Admin 변경)과 §31(사용자 조회)이 **서로 만난 적이 없었다** — 각자 자기 쪽만 확인했다.
이 둘이 어긋나면 "관리자 화면에서는 해지했는데 사용자는 계속 이용 가능"이라는, 과금에
직접 영향을 주는 모순이 조용히 성립한다.

한 구독을 **세 관점**에서 동시에 본다: 사용자 조회(`/subscriptions/me`) / Admin 목록 /
이용권 게이트(`has_active_subscription`) + DB 실제 값.

```
ACTIVE   -> 세 관점 status·effective_status 일치, 게이트 True
PAUSED   -> 사용자 조회·Admin 목록·DB 전부 PAUSED, 이용 불가, 게이트 차단
재개     -> ACTIVE 복귀, 이용권·게이트 모두 회복 (CS 복구 경로가 실제로 동작)
해지     -> 세 관점 CANCELLED, 게이트 차단,
            등기부 신청이 REGISTRY_SUBSCRIPTION_REQUIRED로 막히고 신청 행도 안 생김
```

마지막 항목이 핵심이다 — 해지했는데 계속 무료로 쓸 수 있으면 그대로 매출 누수다.

### 2. 관리자 조정과 실제 사용이 뒤섞였을 때의 산술 (§20-B, 20검사 신규)

기존 검사는 GRANT/DEDUCT/RESET을 **따로만** 봤다. 실제 등기부 사용과 섞인 적이 없었다.
이 원장은 잔액 컬럼이 아니라 조정 누계이므로 두 항등식이 계속 성립해야 한다.

```
effective_limit = plan_limit + adjustment
remaining       = effective_limit - used
```

특히 **이미 사용한 뒤의 DEDUCT**가 `used`를 건드리면 사용자는 쓰지도 않은 횟수를 잃는다.
실측 결과 산술은 전 구간 정확했다(GRANT +3 → 사용 2건 → DEDUCT -1 각 단계 검증).
사용 로그가 1회당 정확히 -1인 것과, 사용이 조정 원장(history)을 오염시키지 않는 것도 고정했다.

### 오탐으로 확인해 기록하지 않은 것 2건

- **이용권 게이트가 만료 구독에 True를 반환** — 그 사용자가 **다른 ACTIVE 구독을 함께
  갖고 있었기** 때문이었다. 깨끗한 사용자로 재현하니 만료 단독은 False, 유예 기간(만료 1일)은
  True로 **정확히 설계대로** 동작했다.
- **해지 후 등기부 신청이 PAYMENT_REQUIRED가 아님** — 구독이 아예 없으면
  `REGISTRY_SUBSCRIPTION_REQUIRED`가 맞다. `PAYMENT_REQUIRED`는 구독은 있는데 무료 한도를
  초과한 경우다. 내 기대가 틀렸다.

두 건 모두 재현 없이 보고했다면 **없는 버그를 만들어낸** 사례가 됐을 것이다.

### 기록만 하고 고치지 않은 것 — `registry_credit_logs.balance_after`의 이중 의미

한 컬럼이 행 종류에 따라 다른 것을 담는다(실측).

```
GRANT  delta +3  balance_after 3   <- 조정 누계
USAGE  delta -1  balance_after 7   <- 잔여 무료횟수
USAGE  delta -1  balance_after 6   <- 잔여 무료횟수
DEDUCT delta -1  balance_after 2   <- 조정 누계
```

running balance로 읽으면 `3 → 7 → 6 → 2`로 앞뒤가 맞지 않아, 운영자가 원장을 감사할 때
오독할 수 있다. **다만 산술 자체는 전부 정확하고**, 이 필드는
`GET /admin/registry/credit-logs/{user_id}`로 이미 노출된 계약이라 의미를 바꾸는 것은
API 계약 변경 + 표기 제품 결정이다 — 임의로 손대지 않고 Backlog로 남긴다.

### 품질 게이트

```
test_api_regression.py   686 -> 708검사 (Sprint 64에서 +22), 연속 2회 잔여 0
Python test_*.py         24개 파일 전부 PASS
변이 검증                 30/30 검출 (Sprint 61~64 누적)
프런트 계약               93/93 (cancelled 0)
compileall / tsc / eslint(0) / next build  전부 통과
```

이번 Sprint의 **제품 소스 변경은 0건**이며 테스트·문서만 추가했다.

---

## 2026-08-12 Sprint 65 — **크롤 파이프라인 실제 실행 검증 (Release Blocker #1 해소 입증)**

Sprint 54부터 8일간 "Release Blocking"으로 기록돼 온 크롤 중단을, **실제로 크롤러를 돌려**
전 구간 동작을 확인했다. 저장소 역사상 처음이다.

### 선행 조건 실측 (이전 Sprint들이 "미설치/불가"로 기록해 온 것들)

```
Chrome            설치됨 (151.0.7922.109)
ChromeDriver      webdriver-manager로 자동 확보 성공 (5.3s)
헤드리스 기동      성공 (5.7s)
courtauction.go.kr  접속 성공 (200, title='법원경매정보', 64KB)
selenium/pandas/pdfplumber  Sprint 61에 설치 완료
```

**결론: 크롤러를 막고 있던 저장소·환경 측 원인은 하나도 남아 있지 않다.**

### 전 구간 실행 검증 (서울중앙지방법원 1개 법원으로 범위 한정)

정부 사이트 부하와 소요 시간(법원당 약 168초, 60개면 약 2.8시간)을 고려해 **1개 법원**으로
범위를 좁혀 체인 전체를 확인했다.

```
1) crawl_court()          9건 수집 (매각기일 2026-08-19 = 미래 기일)
2) 검증/정규화             ValidationEngine + normalize_batch 통과
3) upsert_batch()          inserted 6 / updated 3 / failed 0, exit_code 0
4) enqueue_documents()     added 18 (신규 6건 x 문서 3종), skipped_expired 0
5) migrate_execute.py      auction_item 1,876건 / document_status 5,628건 — 건수 일치 [OK]
6) 검색 API (실서버)        기본 검색 total 14 -> 23건, 신규 9건이 실제로 조회됨
```

**이것이 Blocker의 핵심이다** — 기일이 남은 물건이 **14건 → 23건**이 됐고, 그중 9건이
2026-08-19이다. 즉 **2026-08-13에 검색 결과가 0건이 되는 상황은 더 이상 발생하지 않는다.**

### 중복 수집 방지 (같은 법원 재실행)

```
inserted 0 / enqueue added 0
auction +0 / auction_item +0 / document_queue +0
```

재실행이 완전히 멱등이며 행이 하나도 늘지 않는다. (재실행 시 수집 건수가 9 → 1로 달랐는데,
이는 사이트의 기일별 목록이 시점에 따라 달라지는 **사이트 측 변동**이지 코드 문제가 아니다.)

### 실행 후 무결성

새로 수집한 실데이터가 들어간 뒤에도 `test_pipeline_integrity.py`(고아 행/단계 간 정합/
권리분석 근거 존재)와 `test_schema_hygiene.py`가 전부 통과했다. Python 회귀 24개 파일도
전부 PASS — **실크롤 데이터가 기존 불변식을 하나도 깨지 않았다.**

작업 전 `auction.db.backup_before_sprint65_crawl_20260812_143616` 백업 생성.

### 남은 것은 순수한 운영 조치 2가지 (SKIP)

1. **전체 60개 법원 1회 실행** — 기술적으로 가능함이 입증됐고, 지금 바로 실행 가능하다.
   다만 약 2.8시간이 걸리고 정부 사이트에 지속적인 부하를 주므로 **실행 시점은 운영 판단**이다.
2. **예약 작업 등록** — 어느 계정으로 몇 시에 돌릴지는 운영 결정이라 등록하지 않았다.
   `run_daily.bat`은 이미 `cd /d %~dp0` 기반이라 경로 하드코딩 없이 동작한다.

**Release Blocking #1의 성격이 바뀌었다** — "고칠 것이 남아 있다"에서 **"운영자가 실행만
하면 된다"**로 내려왔다.

### Sprint 65 이어서 — 문서 수집(doc_worker) 경로도 실사이트로 검증

크롤(목록 수집)에 이어 **문서 수집 경로**까지 실제 사이트로 확인했다. 여기에는 특별한
의미가 있다 — Sprint 62에 고친 `collect_status()`(빈 캡처 저장 결함, BUGS #61)가
**실사이트에서 정상 동작하는지 한 번도 확인된 적이 없었기 때문이다.** 합성 테스트로는
"빈 캡처를 거부한다"만 검증했지 "정상 문서는 제대로 저장한다"를 실증하지 못했다.

```
대상: 2024타경126346-1 status (이번 크롤로 새로 큐에 오른 항목)

1) go_to_case_detail()      진입 성공
2) collect_status()         success=True / partial=False / 파일 2개 저장
3) 저장 결과                24,126 bytes
                           status_overlay_has_data() = True
                           본문 사건번호 = 2024타경126346  (실제 데이터가 들어있다)
4) mark_queue_done()        큐 done / document_status READY / auction.has_status_doc=1
5) 정합 재검사              test_pipeline_integrity.py ALL PASS
```

**Sprint 62 수정이 성공 경로를 막지 않는다는 것이 실증됐다.** 저장된 24,126 bytes는
빈 캡처(19,253)와 명확히 구분되고 정상 파일 범위(23,526~351,375) 안에 든다.

부수 확인 — `collect_status()`만 직접 호출했더니 "파일은 있는데 큐가 pending"인 상태가
잠깐 생겼고, `test_pipeline_integrity.py`가 이를 **즉시 잡아냈다**. 그 불변식 검사가
실제로 작동한다는 증거다(이후 `mark_queue_done()`으로 정상 완결).

체크포인트/검증 로그도 실크롤 후 상태를 확인했다 — `logs/checkpoint.json`은 정상 종료
후 `{}`로 비워졌고(재개 지점 잔여 없음), `logs/validation.jsonl`에는 이번 수집분 PASS
기록이 정상 적재됐다.

---

## 2026-08-12 Sprint 66 — collect_documents 감사(잠재 결함 2건 수정) + 감정평가서 파서 실측 스코핑

### 1. `collect_documents.py` 잠재 결함 2건 (BUGS #64)

배치 편입 Backlog(roadmap 16-A)에 올라 있는 스크립트를 감사했다. **실행되는 순간 발현될**
결함 2건을 찾아 고쳤다(지금까지 한 번도 실행된 적이 없어 현재 피해는 0건).

```
(1) 저장 경로 불일치
    저장   storage/docs/<type>/<원본파일명>
    서빙   documents/<법원>/<사건>/<물건>/spec.pdf
    -> document_status는 READY인데 뷰어는 404 (BUGS #50 재발)

(2) STATUS는 이 경로로 성공 불가
    download_doc()은 .pdf만 받는데 현황조사서는 HTML 오버레이다
    -> 매번 "다운로드 실패"로 FAILED 기록 (실패가 아니라 담당이 다른 것)
```

수정: 경로 규칙을 selenium 무의존 모듈(`crawler/doc_paths.py`)에 두고
`finalize_download()`가 `os.replace()`로 뷰어 경로에 원자적으로 옮긴 뒤 **그 경로를**
기록하게 했다. STATUS는 doc_worker 담당이므로 건너뛴다.

### 2. 감정평가서 파서 — 실측으로 스코핑 (구현은 SKIP)

"감정평가서 파서 미구현"이 Backlog에 오래 있었으나 **왜 못 하는지가 측정된 적이 없었다.**
실제 PDF를 열어 확인했다.

```
appraisal.pdf 보유            198개
표본 30개(앞 5페이지) 텍스트 밀도
  페이지당 추출 문자 중앙값     526자
  200자 이상(텍스트 PDF)      24 / 30   (80%)
  0자 (완전 이미지)            5 / 30
  1~50자 (거의 이미지)          1 / 30
```

**결론: 텍스트 파싱은 약 80%에서 실현 가능하다.** 나머지 20%는 스캔 이미지라 OCR이
필요하며 그것은 별개 과제다. (조사 초기에 표본 몇 개만 보고 "대부분 스캔 이미지"로
판단했다가, 표본을 30개로 늘려 측정하니 정반대였다 — 작은 표본으로 결론 내지 않는다.)

**그럼에도 구현은 SKIP한다** — 막는 것은 파싱 기술이 아니라 **결정**이다.
- 무엇을 추출할지(감정평가액/토지·건물 내역/평가 근거 …) = 제품 결정
- 어디에 저장할지 = 스키마 신설 필요(`parsed_document`는 죽은 테이블이고 `rights_summary`에
  감정평가 관련 컬럼이 없다)
- 화면에 어떻게 보여줄지 = 화면 설계

두 결정이 나오면 곧바로 착수 가능한 상태다(의존성 설치 완료, 파일 198개 확보, 파싱 가능성 실측).

### 3. Dead code 재확인 — 신규 0건

AST로 핵심 7개 패키지의 공개 함수를 전수 대조했다. 참조 0건은 여전히 3개
(`get_active_subscription` / `get_court_by_code` / `_hash_bytes`)뿐이며 전부 기존 기록이다.

`overwrite=True` 호출은 저장소 전체에 **0건**으로 관련 분기가 여전히 죽어 있음을 재확인했다.
다만 Sprint 41이 "미리 준비된 인프라"로 판단해 **유지**하기로 이미 결정한 항목이라,
새 근거 없이 뒤집지 않는다. `parsed_document` 제거는 스키마 변경(부트스트랩 테이블 수 25가
바뀐다)이라 roadmap 16-C 유지.

**이번에 추가한 코드가 죽지 않았는지도 함께 확인했다** — `canonical_doc_path`(8회),
`PDF_DOWNLOADABLE_DOC_TYPES`(7회), `finalize_download`(6회) 전부 실제 참조된다.
이 저장소가 반복해서 지적해 온 "준비만 되고 배선 안 됨" 패턴을 만들지 않았다.

### 품질 게이트

```
Python test_*.py   24개 파일 전부 PASS
변이 검증           36/36 검출 (Sprint 61~66 누적)
프런트 계약         93/93 (cancelled 0)
compileall / tsc / eslint(0)  전부 통과
storage/docs 잔여 파일 0개
```

---

## 2026-08-12 Sprint 67 — doc_raw 소유권 실측 + collect_documents 저장/실패 경로 회귀

### 1. 문서 저장 소유권 매트릭스 (roadmap 16-B 결정 입력)

"누가 무엇을 기록하는가"가 문서로만 서술돼 있고 **표로 정리된 적이 없었다.** 코드 전수
추적으로 확정했다.

```
                        PDF 저장   doc_raw   document_status   document_queue
doc_worker(+doc_crawler)   O         X        O(mark_queue_*)       O
collect_documents.py       O         O        O(직접)               X
```

- **Sprint 66 수정 이후 두 경로가 같은 canonical 경로에 저장**한다(더 이상 갈라지지 않는다).
- 남은 비대칭은 두 칸뿐이다.
- `collect_documents`가 `document_queue`를 갱신하지 않는 것의 실제 영향을 추적했다 —
  파일+READY는 맞는데 큐가 `pending`으로 남아 `test_pipeline_integrity.py`의
  "파일이 있으면 큐도 done" 불변식이 그 시점에 실패한다. **다만 자가 치유된다**:
  다음 `doc_worker` 실행에서 `collect_spec()`이 `doc_exists()` 가드로 즉시
  `success=True`를 반환(재다운로드 없음)하고 `mark_queue_done()`이 큐를 맞춘다.
  데이터 손실·중복 다운로드 없음, 비용은 claim 1회.

**실데이터 교차 검증(전수): READY인데 파일 없음 0 / 파일 있는데 READY 아님 0 /
`doc_raw` 경로 부재 0.**

어느 쪽으로 정리할지는 **소유권 결정**이라 구현하지 않았다(16-B). 결정 없이 한쪽을
구현하면 반대 결정 시 낭비가 되기 때문이다.

### 2. BUGS #65 — 0바이트 다운로드가 READY로 기록됨

Sprint 66은 `collect_documents`의 **경로**를 고쳤지만 **DB 기록 쪽은 검증하지 않았다.**
그 공백을 메우려 회귀를 짜다가 실제 결함을 찾았다.

```
화면(document_status)   READY        사용자에게 "열람 가능"
뷰어                    0바이트 서빙  깨진 문서
재수집 판정(doc_exists) False        미완료로 계속 재시도
```

`doc_exists()`가 이미 "크기>0"을 완료 기준으로 쓰는데 `save_doc_raw()`만 크기를 보지
않았다. **새 정책이 아니라 기존 기준에 맞추는 수정**으로 처리했다(size<=0 → 실패 반환 →
기존 흐름대로 FAILED 기록).

### 3. 신규 `test_collect_documents.py` (26검사)

배치 편입 후보인데 실행된 적이 없어 **저장·실패 경로가 한 번도 검증되지 않았던** 코드다.
selenium 없이 `finalize_download` / `save_doc_raw` / `save_failure`만 직접 호출한다.

| # | 검사 | 왜 중요한가 |
|---|---|---|
| 1 | 정상 저장 | `doc_raw.storage_path`가 **뷰어가 읽는 경로**인지(BUGS #64의 본질) |
| 2 | 저장 실패 | **실패했는데 READY**가 되지 않는지 — 가장 위험한 오동작 |
| 3 | 이동 실패 | 원본 없음/모르는 doc_type → None, 목적지에 파일 미생성 |
| 4 | `save_failure` | 두 테이블(실패 이력 + 상태)에 함께 기록, 다른 문서 종류 무영향 |
| 5 | 재실행 | 버전 1,2로 쌓이되 **뷰어 경로는 파일 하나**로 유지 |
| 6 | 0바이트 | BUGS #65 회귀 — `doc_exists()`와 판정 일치 |

변이 5/5 검출(2종은 수정 전 동작 재현).

### 품질 게이트

```
Python test_*.py   25개 파일 전부 PASS (신규 test_collect_documents.py 포함)
변이 검증           48회 시도 -> 47 검출 / 1 등가 변이 (Sprint 61~67 누적)
compileall / tsc / eslint(0)  전부 통과
```

### Sprint 67 이어서 — 운영 장애 시나리오 / DB 무결성 Audit

**SQLite 동시성 — 추정했던 위험이 실측으로 부정됐다**

일일 크롤이 약 2.8시간 동안 `auction.db`에 쓰는 동안 API 읽기가 막히는지 확인했다.
설정만 보면 위험해 보였다.

```
journal_mode  delete   (WAL 아님)
busy_timeout  5000ms
```

그러나 실제로 쓰기 트랜잭션(`BEGIN IMMEDIATE`)을 3초·7초 보유한 채 읽기를 시도한 결과
**두 경우 모두 0.00초에 성공**했다. rollback-journal 모드에서 `BEGIN IMMEDIATE`는
RESERVED 락만 잡고, 읽기는 원본 DB를 그대로 읽을 수 있기 때문이다(EXCLUSIVE는 커밋 순간
잠깐만 잡힌다). **크롤 중 사용자 조회가 막히는 문제는 없다.**

WAL 전환은 하지 않았다 — 이 `auction.db`는 OneDrive 동기화 폴더 안에 있고, WAL은
네트워크/동기화 파일시스템에서 권장되지 않는다. 게다가 위와 같이 **해결할 문제 자체가
없다.** (인프라 변경이라 승인 영역이기도 하다.)

**DB 무결성 전수**

```
PRAGMA foreign_key_check    위반 0건
PRAGMA integrity_check      ok
document_status             5,628 = auction_item 1,876 x 3  (정확히 일치)
문서 상태 ↔ 파일 교차        READY인데 파일 없음 0 / 파일 있는데 READY 아님 0
doc_raw 경로 부재            0
```

**문서 API 계약 — 상태값과 파일 상태가 일치하는가**

`GET /item/{id}/documents/{type}`를 3개 문서 종류 × 3개 상태(READY/COLLECTING/FAILED)
전 조합으로 실측했다. **9/9 모두 기대와 일치**했다(파일이 있으면 200, 없으면 404).
방어 경로도 정상: 없는 item 404 / 모르는 doc_type 400 / 소문자 doc_type 400.

### Sprint 67 이어서 — self-healing을 코드 읽기가 아니라 **재현**으로 확정 (회귀 고정)

앞서 "collect_documents가 큐를 갱신하지 않아도 다음 doc_worker에서 자가 치유된다"고
**코드 추적으로만** 판단했다. 그 판단을 실제로 재현해 `test_collect_documents.py`에
회귀로 고정했다(§7~8, 23검사 추가 — 총 53검사).

selenium 없이 재현할 수 있는 이유: `collect_spec()`은 `doc_exists()`가 참이면
**driver를 건드리기 전에** `success=True`로 단락한다. 그래서 `driver=None`으로 호출해
실제 함수 그대로 검증했다.

**§7 수렴 시나리오 (실제 재현)**

```
1) collect_documents 경로 수집   document_status READY / 파일 존재
                                 큐는 여전히 pending      <- 불일치 재현됨
2) doc_worker claim              in_progress
3) collect_spec(driver=None)     success=True, files_saved=[]  <- 재다운로드 없음
4) mark_queue_done               큐 done / document_status READY / 파일 유지
                                 doc_raw 1건 유지(중복 없음) / version log 0
```

**불일치는 실재하지만 다음 worker 실행에서 완전히 수렴한다** — 데이터 손실도, 중복
다운로드도 없다. 따라서 이것은 버그가 아니라 roadmap 16-B **소유권 결정** 대상이라는
Sprint 67 초반 결론이 실측으로 확정됐다. 코드는 수정하지 않았다.

**§8 실패 → 재시도 → 성공 수렴**

```
1회 실패      mark_queue_failed  -> pending 복귀, retry_count 1
             document_status는 READY가 아님(COLLECTING 유지)
재시도 간격   30분 전에는 claim되지 않음 -> 간격 경과 후 다시 claim됨
2회차 성공    큐 done / document_status READY / doc_exists True
             retry_count 1은 이력으로 남음
```

**테스트 fixture에서 배운 것 (기록해 둘 가치가 있음)**

처음에는 `auction_item`만 만들고 `auction_case` 연결을 빠뜨렸더니 §8이 실패했다
(큐는 done인데 document_status가 COLLECTING). 원인을 추적하니 제품 결함이 아니라
**fixture가 비현실적**이었다 — `_set_document_status()`는 큐의 (court_code, case_no,
item_no)를 `auction_case` JOIN으로 `auction_item.id`에 매핑하므로 연결이 없으면 갱신
대상을 못 찾는다. 코드는 이 경우를 **조용히 넘기지 않고 경고 로그를 남긴다**
("document_status 갱신 대상 없음"). 운영에서는 `migrate_execute.py`가 항상 연결을
만들고 `test_pipeline_integrity.py`가 그것을 검증한다.

→ **assertion을 낮추지 않고 fixture를 운영과 같게 고쳤다.** 덕분에
`mark_queue_done`의 상태 동기화가 `auction_case` 연결에 의존한다는 사실도 함께 고정됐다.

스키마 준비도 실제 부트스트랩 절차 그대로로 바꿨다(`init_db` → `migrate_v4_1` →
`run_migrations`). 필요한 마이그레이션만 골라 적용하다 011의 `auction_case.court_code`를
빠뜨려 깨진 적이 있어서다.

**변이 검증 3/3** — `mark_queue_done`의 상태 동기화 제거 / 재시도가 pending으로 안 돌아옴 /
`collect_spec`의 단락 제거(이 경우 driver=None을 실제로 쓰려다 크래시 = 단락이 load-bearing
임을 증명). 누적 51회 시도 → 50 검출 / 1 등가.

### Sprint 67 이어서 — Concurrency Audit 완결 (BUGS #66 발견·수정)

후속 Backlog "Registry / Credit 동시성"을 처리하다 **마지막까지 남아 있던 TOCTOU 경로**를
찾았다.

**1. 등기부 무료횟수 조정 — 검증 결과 안전 (수정 없음)**

`adjust_registry_credit`은 **append-only 원장**이다. `add_credit()`은 현재 합계를 읽지 않고
행 하나를 INSERT하며, 상한 검사도 1회 조정량에만 걸린다(누적 아님). 구조상 lost update가
불가능한데 **그 사실이 검증된 적은 없었다.**

12스레드 동시 조정(GRANT 8 × +3 / DEDUCT 4 × -1) 실측:

```
원장 행 수 = 요청 수 12   (유실·중복 0)
원장 합계 = +20           (기대치와 정확히 일치)
API adjustment = +20, effective_limit = plan + 20
```

누군가 나중에 "누적 상한"이나 "잔액 확인 후 조정" 같은 읽기-판단을 넣으면 조용히 경합이
생긴다 — 이제 그때 이 검사가 잡는다.

**2. 검색조건 저장 상한 — 실제 결함 발견·수정 (BUGS #66)**

`create_preset()`이 COUNT로 상한을 확인한 뒤 INSERT하는 전형적인 "확인 후 쓰기"였다.
이 저장소가 다른 경합 지점을 전부 굳혀 온 것과 달리 **여기만 빠져 있었다.**

```
99개 상태에서 12개 동시 요청
  수정 전 : 성공 2건 -> 최종 101개   (상한 초과)
  수정 후 : 성공 1건 -> 최종 100개   (3회 반복 동일)
```

`registry.py`의 무료횟수 COUNT와 같은 패턴(`BEGIN IMMEDIATE` + ROLLBACK/COMMIT)으로 고쳤다.
새 정책이 아니라 **이미 있는 상한을 정확히 집행**하는 수정이며 API 계약은 무변경이다.

**동시성 방어 현황 (이번으로 전 경로 커버)**

| 경로 | 방어 | 회귀 |
|---|---|---|
| 등기부 무료한도 | `BEGIN IMMEDIATE` | §1 |
| 초과결제 | 조건부 UPDATE | §2 |
| 구독 생성 | `BEGIN IMMEDIATE` | §3 |
| Admin 등기부 상태전이 | 조건부 UPDATE | §4 + §6 |
| 환불 | `BEGIN IMMEDIATE` | §5 + §7 |
| Webhook 재처리 | `BEGIN IMMEDIATE` | §8 |
| Admin 구독 상태변경 | `BEGIN IMMEDIATE` | §9 + §10 |
| 등기부 크레딧 조정 | append-only(방어 불필요) | **§11 신규** |
| 검색조건 상한 | **`BEGIN IMMEDIATE` 신규** | **§12 + §13 신규** |
| 큐 claim | 조건부 UPDATE | `test_document_queue.py` §8 |

`test_race_conditions.py` 49 → **58검사**.

**후속 Backlog 1~10 처리 결과**

```
1 문서 API Contract        재검증 완료 (3종x3상태 9/9 + 방어 3종)
2 document-stats DB 대조    재검증 완료 (Sprint 66에 8개 값 전수 대조)
3 crawler retry/resume      재검증 완료 (Sprint 63/67)
4 Registry/Credit 동시성    ★ 이번에 수행 -> §11 신규, BUGS #66 발견
5 Subscription 상태머신     재검증 완료 (Sprint 60/64)
6 Payment 멱등성            재검증 완료 (Sprint 38/58)
7 Search API Contract       재검증 완료 (Sprint 43/51/61)
8 Frontend API Contract     재검증 완료 (93/93)
9 인증/권한                 재검증 완료 (Sprint 61/64)
10 DB integrity             재검증 완료 (FK 0 / integrity_check ok)
```

---

## 2026-08-12 Sprint 68 — Beta 사용자 여정 Release Gate 신설

### 왜 필요했나

기존 회귀는 **도메인별로는 촘촘한데**(검색·상세·즐겨찾기·등기부·구독 …) 실제 사용자가 겪는
**하나의 연속된 흐름**으로 묶여 검증된 적이 없었다. 각 도메인이 전부 통과해도 그 사이를 잇는
**이음매**가 끊기면 사용자는 서비스를 못 쓴다.

- 상세에 들어갔는데 최근조회에 안 남는다
- 관심물건을 눌렀는데 검색 결과 하트가 그대로다
- 로그인하고 돌아왔더니 보던 물건이 아니라 첫 화면이다

이런 것들은 어느 도메인 테스트의 책임도 아니어서 아무도 확인하지 않았다.

### 신규 `test_beta_journey.py` (66검사)

```
/  ->  검색  ->  정렬  ->  페이지 이동  ->  물건 선택
   ->  로그인 게이트 + 복귀 URL 보존  ->  상세  ->  문서 조회
   ->  등기부(구독 전/후)  ->  관심물건  ->  최근조회  ->  검색조건 저장
```

여정 대상은 **문서 3종이 READY이고 기일이 남은 실제 물건**을 DB에서 골라 쓴다
(Sprint 65 크롤로 들어온 `id=502 2024타경3528 서울중앙지방법원`). 고정 id를 박아 두면
데이터가 바뀌는 순간 무의미해지기 때문이다.

각 단계에서 **HTTP status만 보지 않는다** — 응답 본문과 DB 상태를 함께 확인한다.

| 단계 | 이음매로 확인한 것 |
|---|---|
| 1~3 | 검색 응답 계약 / 정렬이 **실제 오름차순**인지 / 두 페이지가 안 겹치는지 |
| 4 | 비로그인 상세 307 + **복귀 URL에 경로와 쿼리(ids/i)가 모두 보존** |
| 5 | 상세 조회가 **DB의 recent_items에 실제로 남고** 목록에 나오는지 |
| 6 | 문서 3종이 READY이고 **실제 바이트가 내려오는지**, 잘못된 종류는 400 |
| 7~8 | 구독 없으면 차단 → 구독 후 무료 PENDING → **재신청이 중복 생성/중복 소모하지 않는지** |
| 9 | 관심물건이 **로그인 검색에는 켜지고 비로그인에는 꺼져 있는지** |
| 10 | 검색조건이 저장되고 **조건이 그대로 복원되는지** |
| 11 | 여정에서 쓰는 8개 엔드포인트가 전부 비로그인 차단인지 |

### dev 서버가 없을 때 조용히 통과하지 않는다

프런트 게이트(4단계)는 dev 서버가 필요하다. 서버가 없으면 그 단계를 **SKIPPED로 명시 출력**하고
요약에도 남긴다 — `docs/TEST_PLAN.md`에 기록된 "cancelled를 fail 0으로 오인하는" 함정을
반복하지 않기 위해서다. 실제로 서버를 내린 채 한 번, 올린 채 한 번 돌려 두 동작을 확인했다.

### 변이 검증 3/3 — 이음매가 실제로 잡힌다

```
상세가 최근조회를 기록하지 않게 함   DETECTED (DB 0건 + 목록 빈 값, 2개 검사 실패)
관심물건이 검색에 반영되지 않게 함    DETECTED (하트 False)
등기부 중복 방지 플래그 제거          DETECTED
```

이 세 가지는 **어느 도메인 테스트도 잡지 못하던 것**이다(각 도메인은 자기 쪽만 보므로).

### 품질 게이트

```
Python test_*.py   26개 파일 전부 PASS (신규 test_beta_journey.py 포함)
  api_regression 727 · race_conditions 69 · journey 66 · collect_documents 53
변이 검증           누적 58회 시도 → 56 검출 / 2 등가
compileall / tsc / eslint(0)  전부 통과
여정 QA 데이터 잔여  0
```

---

## 2026-08-12 Sprint 69 — 감정평가서 파서 기술 검증 + API 장애 시 화면 복원력

### 1. 감정평가서 파서 — 전수 정확도 측정 (제품 결정은 SKIP)

Sprint 66이 "80%가 텍스트 추출 가능"까지 측정했다면, 이번에는 **실제로 값을 뽑아
정답과 대조**했다. 정답은 `auction_item.appraisal_price`(목록 크롤 값)다.

```
전수 197건 (앞 3페이지 파싱)
  match       96  (48.7%)
  mismatch    46  (23.4%)
  no_amount   19  ( 9.6%)
  no_text     36  (18.3%)  <- 스캔 이미지, OCR 필요
```

**핵심은 불일치의 원인이다 — 파서가 틀린 것이 아니었다.** 불일치 건의 원문을 직접 읽었다.

```
item=114  PDF: "감정평가액 일십일억칠천육백일십만육천원정 (\1,176,106,000.-)"   DB: 188,632,000
item=118  PDF: "감정평가액 육억사천사백팔십일만삼천원정 (\644,813,000.-)"       DB: 637,563,000
item=115  PDF: 607,000,000 = 그 사건 물건 2건의 합계와 정확히 일치
```

**감정평가서의 `감정평가액`은 사건 전체 평가액이고 `appraisal_price`는 물건 하나의
평가액이다.** 개념이 달라 일치하지 않는 것이 정상이며, 48.7%의 "일치"는 사건에 물건이
하나뿐인 경우다.

→ **감정평가액은 추출 대상으로서 가치가 낮다.** 화면에 이미 물건별 감정가가 있는데
사건 총액을 나란히 보여주면 사용자가 두 숫자를 혼동한다. 파싱으로 새 가치를 만들 수 있는
후보는 오히려 **토지/건물 내역·면적·구조·제시외건물**처럼 지금 어디에도 없는 항목이다.
어떤 항목을 어디에 저장하고 어떻게 표기할지는 제품·스키마 결정이라 정하지 않았다
(자세한 근거는 `docs/roadmap.md` "감정평가서 파서 — 기술 검증 결과").

**작업 중 스스로 걸러낸 오류** — 처음에는 문자 중복(`감감감감`)을 제거하는 정규식을
넣었는데, 그것이 `2,000,000`의 `000`까지 뭉개 `2,0,0`으로 만들어 "숫자를 못 뽑는다"는
잘못된 결론을 낼 뻔했다. 원문(raw)으로 다시 확인해 정정했다.

### 2. API 장애 시 화면 복원력 (실측)

`SearchScreen`의 `unavailable` 분기는 Sprint 51에 만들어졌지만 **자동 테스트가 없었다**.
실제로 API 서버를 내리고 확인했다.

```
API 정상   결과 카드 렌더
API 중단   HTTP 200 (500/크래시 아님)
           "검색 결과를 불러오지 못했습니다" 안내 표시
           헤더·네비게이션·검색 폼은 그대로 유지 (부분 저하)
API 복구   결과 카드 복원, 에러 문구 사라짐
```

빈 화면이나 스택트레이스가 아니라 **쓸 수 있는 상태로 저하**된다는 것을 확인했다.

### 품질 게이트

```
Python test_*.py   26개 파일 전부 PASS
프런트 계약         93/93 (cancelled 0)
compileall / tsc / eslint(0) / build 경고 0
```

---

## 2026-08-12 Sprint 70 — 미검증 화면 상태 실측 + 기술부채 1건 철회

### 1. 빈 결과 / 페이지 범위 초과 / 잘못된 ID (실제 화면 확인)

여정에서 아직 실제 화면으로 확인하지 않았던 상태들을 dev 서버로 직접 열어 봤다.

```
잘못된 물건 ID   /item/99999999 -> 404   /item/0 -> 404   /item/-1 -> 404   /item/abc -> 422
빈 검색 결과     total=0 / items=[] / 응답 키 계약 유지(5개)
페이지 범위 초과  total=9 / items=[] / total_pages=1  (두 상태가 응답에서 구분된다)
```

화면 문구도 두 상태가 **명확히 갈린다**(BUGS #31이 고친 것이 그대로 유지됨).

```
빈 결과      "검색 결과가 없습니다 / 검색조건을 줄이거나 지역·가격 범위를 넓혀보세요"
             + [조건 없이 전체 물건 보기]  <- 복구 동선
페이지 초과   "조건에 맞는 물건은 총 9건이지만, 요청한 페이지(99)가 마지막 페이지(1)를 넘어섰습니다"
             + [검색조건 유지하고 1페이지로 이동]  <- 조건을 잃지 않는 복구 동선
```

"결과가 없다"와 "페이지를 잘못 요청했다"를 같은 문구로 뭉개지 않는다.

### 2. 기술부채 철회 — "Recent Items 무제한 누적"은 사실이 아니었다

여러 Sprint 보고서에 기술부채로 올라 있던 항목인데, **실측하니 틀린 서술이었다.**

`recent_items`에는 `UNIQUE(user_id, item_id)`가 있고 기록은
`ON CONFLICT DO UPDATE SET viewed_at`이다. 즉 **조회 횟수가 아니라 "서로 다른 물건 수"로
상한이 잡힌다.**

최악의 경우(한 사용자가 전 물건 1,876건을 모두 조회)를 만들어 측정했다.

```
heavy 사용자 행 수                1,876행 (= 전체 물건 수, 그 이상 불가)
같은 물건 100회 재조회 후 증가      0행
최근조회 20건 조회 소요            0.000 ms (50회 평균, 인덱스 seek)
recent_items 3,326행 상태 DB 크기  1.1 MB
```

실행계획도 `idx_recent_items_viewed_at (user_id, viewed_at)` **인덱스 탐색**이라 행이
늘어도 정렬 비용이 생기지 않는다.

→ **보존 정책(pruning)을 도입할 이유가 없다.** 기술부채 목록에서 철회했다.
없는 문제를 목록에 남겨 두면 진짜 문제가 묻힌다.

### 품질 게이트

```
Python test_*.py   26개 파일 전부 PASS
프런트 계약         93/93 (cancelled 0)
Beta Journey Gate   PASSED
compileall / tsc / eslint(0) / build 경고 0
```

---

## 2026-08-12 Sprint 71 — 소프트 삭제 함정 고정 + 기술부채 2건 처리

### 1. `deleted_at`은 어떤 조회도 보지 않는다 — 현재 동작을 회귀로 못 박음

기존 `test_soft_delete_columns`(§28)는 **컬럼이 존재하는지**와 하드 삭제가 동작하는지만
확인했다. **값을 채웠을 때 어떻게 되는지는 검증된 적이 없었다.** 실제로 채워 봤다.

```
favorites / search_presets 에 deleted_at, deleted_by 를 채운 뒤
  즐겨찾기 목록      1건 그대로 조회됨
  검색조건 목록      1건 그대로 조회됨
  검색 결과의 하트   여전히 켜진 채 (True)
```

**지금은 이것이 정상이다** — 소프트 삭제를 쓰는 코드가 0곳이고 하드 삭제가 유일한 경로다.
위험은 나중이다. 누군가 "컬럼이 있으니 값만 채우면 되겠지"라고 판단하면 **행이 사라지지
않는다.** Migration 016 주석이 이미 그 위험을 적어 뒀다("컬럼만 늘리면 모든 조회에
`deleted_at IS NULL`을 붙여야 한다").

§28-B에 **현재 동작을 그대로 고정**했다(8검사). 소프트 삭제를 배선하는 순간 이 검사가
실패하면서 함께 고쳐야 할 조회 지점(`favorites.py` / `search_presets.py` / `search.py`)을
지목한다. 전환 여부 자체는 제품 판단이라 정하지 않았다.

**가드가 실제로 발동하는지 확인** — `favorites.py`의 조회에만 `deleted_at IS NULL`을
붙여 "부분 배선" 상황을 재현하니 즉시 실패했고, 실패 메시지가 그 파일을 지목했다.

```
[FAIL] deleted_at을 채워도 즐겨찾기 조회에서 사라지지 않는다: 0 (expected 1)
[FAIL] favorites.py에 deleted_at 조건이 아직 없다: True (expected False)
```

### 2. `middleware.ts` → `proxy.ts` 잔재 정리 (5곳)

Sprint 50에 파일은 `src/proxy.ts`로 바뀌었는데, **현재 동작을 서술하는 주석 5곳이 여전히
존재하지 않는 `middleware.ts`를 가리키고 있었다.**

```
src/app/login/actions.ts        "middleware.ts가 만드는 /login?redirect=..."
src/app/login/page.tsx          "middleware.ts가 붙이는 ?redirect= 쿼리"
src/app/search/FavoriteButton.tsx "middleware.ts와 동일하게"
src/components/SiteHeader.tsx    "middleware가 모든 요청에서 getUser()로"
src/lib/supabaseServer.ts        "(middleware가 처리)"
```

전부 `src/proxy.ts`로 정정했다. **과거 이력을 서술하는 문장은 그대로 뒀다**
(`properties/[id]/page.tsx`의 "middleware.ts에서 고친 것과", `proxy.ts` 자체의 전환 기록).
없어진 파일명을 현재형으로 가리키는 주석만 고친 것이다.

### 품질 게이트

```
Python test_*.py   26개 파일 전부 PASS   api_regression 727 -> 735검사
compileall / tsc / eslint(0)  전부 통과
```

### Sprint 71 이어서 — 성능 재측정 (현재 데이터 기준, 1,876건)

Sprint 51의 별칭(LIKE) 도입과 Sprint 65의 신규 크롤 이후 핫패스를 다시 쟀다
(각 20회, TestClient 기준).

```
경로                     평균ms  최대ms
기본 검색(D7)              3.2    3.9
전체 포함                  3.1    3.5
물건종류 별칭(LIKE 7종)      3.4    3.9
지역+가격 범위              3.5    4.0
정렬(감정가 desc)           3.4    4.1
깊은 페이지(page=90)        3.3    4.0
지역 목록                  2.4    3.8
상세                      2.7    3.2
문서 통계                  3.5    4.3

50ms 초과 경로: 없음
```

별칭 LIKE의 추가 비용은 측정 한계 안이다(3.1 → 3.4ms). 깊은 페이지도 느려지지 않는다
(offset 페이지네이션이지만 데이터 규모가 작다). **현재 규모에서 성능 조치가 필요한
경로는 없다.**

---

## 2026-08-13 Sprint 72 {BAR} 회귀 게이트 자체의 신뢰성 + 문서/코드 3자 대조

이번 Sprint는 **"게이트가 진실을 말하는가"**를 먼저 물었다. 기준선을 잡으려고 전체 회귀를
돌린 첫 명령에서 곧바로 두 건이 나왔기 때문이다.

### 1. 회귀 게이트가 콘솔에 따라 결과가 달라졌다 (BUGS #67)

`test_*.py` 26개를 bash에서 돌리니 2개가 **실패가 아니라 크래시**했다(종료 코드 1).
원인은 출력 문자열의 U+2014 EM DASH이고, 이 저장소의 기본 콘솔은 cp949다.

```
PowerShell   stdout=utf-8   26/26 통과
bash/cmd     stdout=cp949   24/26 (2개 UnicodeEncodeError로 중단)
```

**이것은 3번째 재발이다.** Sprint 33(test_normalizer), Sprint 53(test_api_regression,
`_safe_out()`, BUGS #43)이 이미 같은 부류를 고쳤지만 **매번 그 파일에서만** 고쳤다.
저장소 전체를 보는 장치가 없어 다른 파일에서 계속 되살아났다.

print와 logger는 실패 방식이 다르고 **후자가 더 나쁘다** {BAR} logger는 예외를 던지지 않는
대신 **로그 라인이 통째로 소실**된다. 소실 목록에 JWKS 조회 실패, `PAYMENT_WEBHOOK_SECRET`
미설정, Webhook 서명 검증 실패처럼 운영자가 반드시 봐야 할 경고가 들어 있었다.

수정은 출력 경로 11곳의 U+2014 -> U+2015(HORIZONTAL BAR). **cp949에 존재하고(0xA1AA)
시각적으로 동일**해 읽는 사람 입장에서 바뀐 것이 없다. API 응답 문자열은 UTF-8 JSON이라
대상에서 제외했다 {BAR} 규칙을 실제 고장 경로에만 건다.

크롤 데이터 경로도 확인했다. `mvp_scraper.py`는 수집한 값을 print하므로 위험이 있을 수
있는데, `auction.db` 전 테이블 TEXT **111,980셀 전수 검사 결과 cp949 밖 문자 0건**이었다.

### 2. 새 스캐너가 스스로 68개 파일을 건너뛰고 있었다

신규 `test_console_encoding.py`를 처음 작성했을 때 소스를 `utf-8`로 읽어 `ast.parse()`에
넘겼다. 그런데 이 저장소에는 **UTF-8 BOM이 붙은 소스가 68개**
(`collect_documents.py` / `migrate_execute.py` / `api/v1/favorites.py` 등 운영 파일 포함)
있어 전부 `SyntaxError`로 조용히 빠지고 있었다.

`utf-8-sig`로 고치자(저장소의 다른 정적 검사가 이미 쓰는 규약) 결과가 즉시 달라졌다.

```
검사 대상 리터럴   6,959 -> 7,778개
숨어 있던 결함     2건 발견
```

```
api/v1/item.py:53      logger.debug 의 EM DASH
check_db_path.py:35    U+2705/U+274C 이모지
```

두 번째는 "크롤러와 API가 같은 DB를 보는가"를 알려주는 진단 스크립트가
**정답을 출력하는 바로 그 줄에서 죽고 있던** 것이다.

이제 이 테스트는 파싱 실패 파일을 삼키지 않고 모아서 **0건임을 단언**한다.
조용히 건너뛴 파일이 있으면 "통과"가 거짓이 되기 때문이다.

### 3. 프런트 게이트가 백엔드 미기동을 기능 결함으로 오진 (BUGS #68)

`docs/TEST_PLAN.md`의 절차를 그대로 따랐더니 검사들이 줄줄이 실패했는데, 문구는
`비로그인 결과 카드에 즐겨찾기 버튼이 없습니다`였다. 즐겨찾기는 멀쩡했고 **백엔드가 안 떠
있어 검색 결과가 0건**이었을 뿐이다(문서의 실행 절차에 백엔드 기동이 빠져 있었다).

`before()` 훅이 이제 두 서버를 각각 확인하고 **띄우는 명령까지** 지목한다. 물건 0건도
따로 구분한다 {BAR} "데이터가 없다"와 "기능이 깨졌다"는 다르다. 건너뛰지 않고 실패시키는
쪽을 택했다. 백엔드 없이 통과한 결과를 게이트 통과로 오해하면 안 되기 때문이다.

### 4. API 라우트 커버리지 {BAR} 39/39 (결함 없음)

39개 라우트를 테스트가 실제로 호출하는지 AST로 대조했다. 1차 스캔은 13개가 미호출로
나왔지만 **전부 오탐**이었다(`%` 포매팅 / 튜플 루프 / f-string을 스캐너가 못 읽었다).
원문 대조 결과 **39개 전부 커버**된다. `test_api_regression.py` §16이 라우트 목록 자체를
집합으로 고정하고 있어 신규 라우트가 테스트 없이 추가되는 것도 이미 막혀 있다.

인가 매트릭스도 함께 뽑았다 {BAR} Admin 16개 전부 `require_admin`/`require_super_admin`이고,
돈·권한이 움직이는 4개(환불/Webhook 재처리/구독 상태변경/크레딧 지급)는 `require_super_admin`이다.
사용자 범위 라우트는 전부 `WHERE ... AND user_id=?`로 소유권을 건다.
`refund_payment(user_id=None)`만 소유권 인자가 선택적인데, 유일한 호출부가 super-admin이라
현재 IDOR는 없다(문서화된 준비 코드).

### 5. ErrorCode 정의/문서/실제 방출 3자 대조

`docs/ERROR_CODES.md`가 "코드가 기준"이라 못박고 40개를 나열한다. 실측했다.

```
정의             40
문서             40   (1:1, 불일치 0)
실제로 방출되는 것 19   payments 9 / search_presets 5 / registry 3 / favorites 2
한 번도 방출 안 됨 21
```

**"정의됐다"와 "응답에 실린다"는 다르다.** 다만 이것은 결함이 아니다 {BAR} 실패 응답이
두 형태(`error_response()` 봉투 / `HTTPException`의 `{"detail":...}`)로 존재하는 것은
`api/auth.py:fail()` 주석과 문서의 "적용 현황" 절이 이미 의도로 적어 둔 상태다.
**실측이 문서를 확증했다.**

대신 그 경계를 `test_schema_hygiene.py` §5로 고정했다. 특히 프런트
(`src/lib/api.ts:ERROR_CODES`)가 **방출되지 않는 코드로 분기하는 것**(죽은 분기)을 잡는다.

### 6. Dead Code 감사 {BAR} 이용권 판정이 두 벌이었다

운영 코드 함수 전수 조사에서 참조 0건 3개를 찾았다(`_hash_bytes`, `get_court_by_code`,
`get_active_subscription`). 앞의 둘은 단순 미사용이지만 **세 번째가 문제였다.**

"이 사용자가 지금 서비스를 쓸 수 있는가"를 판정하는 함수가 두 개다.

```
registry.py:get_entitled_subscription()   DB 미변경, 순수 계산   <- 실사용(등기부 게이트)
subscriptions.py:get_active_subscription() 동기화 후 판정         <- 호출 0곳, 테스트 참조 0곳
```

미배선 자체는 의도된 상태다(후자의 docstring이 전자를 권한다). 문제는 **아무도 부르지 않고
아무도 검증하지 않는 판정 함수가 살아 있다**는 것이다. 나중에 누군가 이것을 쓰는 순간 두
판정이 어긋나면 경로에 따라 유료 게이트의 답이 달라진다.

`test_subscription_policy.py` §9에 9개 상태 조합(만료 전/유예 안/유예 밖/무기한/PAUSED/
CANCELLED/EXPIRED)으로 **두 판정이 같은 답을 내는지** 고정했다. 어느 쪽이 옳은지를 새로
정하지 않았다 {BAR} 지금 같다는 사실만 못박았다.

변이 검증: 동기화 판정에서 GRACE_PERIOD를 빼면 2건 실패(`is_entitled` docstring이 기록한
과거 버그를 그대로 재현), 순수 판정을 상태 그대로 믿게 바꾸면 2건 실패. 양방향 검출된다.

### 품질 게이트

```
Python test_*.py   27개 파일 전부 PASS (cp949 콘솔 기준 {BAR} 이번 Sprint 전에는 25/27)
프런트 계약         93/93 (cancelled 0, 백엔드 기동 상태)
tsc 0 / eslint 0 / next build 경고 0 / compileall 0
```

신규 검사: `test_console_encoding.py` 17 + `test_schema_hygiene.py` §5 9 +
`test_subscription_policy.py` §9 24 = **50검사 추가**. 변이 검출 시험 9종 전부 검출.

---

## 2026-08-13 Sprint 73 ― 문서 파이프라인 실측 감사

Sprint 72가 "게이트가 진실을 말하는가"였다면, 이번에는 **"DB가 말하는 상태가 실제와 같은가"**를
파일시스템과 대조해 물었다.

### 1. `doc_exists()`가 대문자 doc_type에 조용히 틀린 답을 냈다

`document_status` 5,628행을 실제 파일과 대조하다가 "READY인데 파일 없음" 162건이 나왔다.
전부 STATUS였고, **파일은 멀쩡히 있었다**(status.html/json 둘 다).

원인은 `crawler/doc_paths.py`였다.

```python
_PRIMARY_EXT = {"spec": "pdf", "status": "json", "appraisal": "pdf"}   # 소문자 키
ext = _PRIMARY_EXT.get(doc_type, "pdf")                                # 없으면 조용히 pdf
```

이 저장소는 문서 종류를 **대문자**로 다루는 곳이 더 많다(`document_status.doc_type`,
`DOC_TYPE_FILES`, 같은 파일의 `CANONICAL_DOC_FILENAME`). 대문자를 넘기면 사전에 없으니
기본값 `pdf`로 떨어지는데, **그 오답이 종류마다 달랐다.**

```
"SPEC"       -> "SPEC.pdf"      Windows는 대소문자를 구분하지 않아 우연히 정답
"APPRAISAL"  -> 같은 이유로 우연히 정답
"STATUS"     -> "STATUS.pdf"    status의 기준 파일은 json  ->  항상 False (오답)
```

**2/3이 우연히 맞는 것이 가장 나쁘다.** 잘못된 호출이 대부분 정상으로 보이다가 STATUS에서만
조용히 틀린다. 오답 방향도 나쁘다 ― "완료됐는데 미완료로 보임"이라 이미 수집된 문서를
영구히 재수집 대상으로 남긴다. 이 파일이 BUGS #22/#50/#65에서 반복해 경고해 온 함정의
정반대 방향이다.

운영 호출부 3곳은 전부 소문자 리터럴을 넘기고 있어 **현재 피해는 0건**이었다. 하지만 바로
아래 `canonical_doc_path()`는 `.upper()`로 정규화하고 모르는 값에 예외를 던진다 ―
**같은 파일 안에서 규약이 갈려 있었다.**

수정: 대소문자 정규화 + 파일명을 항상 소문자로 생성(대소문자를 구분하는 파일시스템 대비)
+ 모르는 종류는 조용히 pdf로 떨어뜨리지 않고 `ValueError`. 회귀 9검사 추가, 변이로
수정 전 동작(대문자 STATUS=False, 미지값 무예외) 5건 검출.

### 2. 올바른 기준으로 다시 재니 문서 정합은 완전했다

```
document_status 5,628행 대조
  READY인데 파일 미완료   0건
  非READY인데 파일 완료   0건
  auction_item 없는 orphan 0건
PRAGMA integrity_check   ok
PRAGMA foreign_key_check 위반 0
```

### 3. 큐는 자기치유적이다 (결함 없음)

```
중복 큐 행(같은 문서 4-tuple)      0      migration 018의 UNIQUE가 유지된다
pending인데 파일이 이미 완성됨      0      헛일이 없다
retry_count 분포                  0:3249 / 1:189 / 2:60   (MAX_DOC_RETRY=3)
auction_item에 대응 없는 큐 행     15
```

고아 15행(5개 사건 x 3종)은 레거시 `auction` 테이블에도 없다 ― 원본이 사라진 뒤 남은
찌꺼기다. 그런데 **9건의 pending이 전부 매각기일 경과** 상태라 doc_worker의 2차 방어선
(`auction_date < today` -> 브라우저 작업 없이 SKIPPED_EXPIRED)이 처리한다. 크롤 비용 0.

### 4. 그러다 진짜를 찾았다 ― 끝나지 않는 "수집중" (BUGS #69, **결정 대기**)

`mark_queue_skipped_expired()`는 `document_queue`만 바꾸고 **`document_status`는 건드리지
않는다.** 그리고 `enqueue_documents()`는 만료 물건을 애초에 큐에 넣지 않는다. 두 동작이
각각은 옳은데, 이어 놓으면 화면 상태가 **COLLECTING("수집중")으로 영구히 고정**된다.

```
SKIPPED_EXPIRED 큐 행                      186   그중 document_status=COLLECTING  183
document_status=COLLECTING & 물건 만료됨   5,049
document_status=COLLECTING & 물건 진행중      20
auction_item 1,876건 중 만료              1,867  (99.5%)
```

**사용자에게 보인다.** 검색은 D7 기본값으로 만료 물건을 제외하지만 `favorites`/
`recent_items`에는 날짜 필터가 없다. 실측으로 확인했다:

```
GET /api/v1/item/1  (auction_date=2026-07-07, 5주 전 만료)  ->  200
documents: SPEC / STATUS / APPRAISAL 전부 COLLECTING
src/app/properties/[id]/page.tsx:68   COLLECTING -> '수집중'
```

관심물건에 담아 둔 물건이 만료되면 그 상세는 **절대 도착하지 않을 문서를 계속 기다린다.**

고치지 않은 이유는 명확하다 ― **"대상이 아님"을 나타낼 상태가 없다.** DocStatus는
COLLECTING/OCR/PARSING/ANALYZING/READY/FAILED뿐이고 FAILED로 쓰면 시도조차 안 한 것을
실패로 표기하게 된다. 새 상태를 만들지, 화면에서 만료 물건을 다르게 그릴지는 제품 판단이라
`docs/roadmap.md`에 선택지별 기술 영향과 함께 결정 대기로 올렸다.

대신 `test_document_status_sync.py` §6/§7에 **현재 동작과 노출 경로를 그대로 고정**했다.
정책을 배선하는 순간 검사가 실패하며 함께 고쳐야 할 세 지점을 지목한다.
변이 검증: `mark_queue_skipped_expired()`가 `document_status`를 건드리게 하니 즉시 발동했다.

### 품질 게이트

```
Python test_*.py   27개 파일 전부 PASS
프런트 계약         93/93 (cancelled 0)
tsc 0 / eslint 0 / next build 경고 0
```

신규 검사: `test_doc_storage_atomicity.py` §1 확장 9 + `test_document_status_sync.py`
§6/§7 11 = **20검사 추가**. 변이 검출 시험 2종 전부 검출.

---

## 2026-08-13 Sprint 74 ― 재매각 큐 결함 + Admin 필터 계약 + renew 전 상태

### 1. 유찰 후 재매각된 사건이 문서 수집에서 영구히 빠진다 (BUGS #70)

Sprint 73의 #69 체인을 이어 추적하다 **"만료된 물건이 다시 살아나면 어떻게 되는가"**를
물었고, 거기서 나왔다.

`enqueue_documents()`는 `INSERT OR IGNORE`를 쓰고 UNIQUE는
(court_code, case_no, item_no, doc_type)이다. 그래서 **이미 행이 있으면 통째로 무시**되고
큐는 옛 매각기일을 그대로 들고 남는다. 유찰 후 재매각은 한국 경매에서 일상인데도 그렇다.

그 다음이 문제다. `doc_worker`의 2차 방어선은 **큐에 저장된 auction_date**를 본다.

```python
if auction_date and auction_date < today:
    mark_queue_skipped_expired(...)      # 브라우저 작업 없이 종료
```

즉 **기일이 미래로 다시 잡힌 살아 있는 사건이, 남아 있던 옛 날짜 때문에 "기일 경과"로
판정돼 수집 대상에서 빠진다.** `refresh_queue_priority()`도 같은 stale 값으로 우선순위를
계산해 함께 틀린다.

실측 ― 이론이 아니라 **실제로 일어나 있었다.**

```
큐 auction_date != auction_item.auction_date        18행
그중 현재 기일이 미래(재매각으로 살아난 사건)          9행

item=1533  큐 2026-07-15 (pending)  vs 현재 2026-08-19   <- 6일 뒤 매각인데 죽는다
item=502   큐 2026-07-15 (done)     vs 현재 2026-08-19
item=505   큐 2026-07-15 (done)     vs 현재 2026-08-19
```

**수정** ― INSERT가 무시됐을 때 그 행의 `auction_date`/`priority`를 최신 값으로
동기화한다. **status는 건드리지 않는다** ― done/failed/SKIPPED_EXPIRED를 되살려 다시
수집할지는 재수집 정책이라 제품 판단이다(roadmap 결정 대기). 여기서 고친 것은 큐가 자기
필드에 **사실과 다른 값**을 들고 있는 것뿐이고, 그것만으로 pending 행의 오판은 사라진다.
반환값에 `refreshed` 건수를 더해 로그로 추적 가능하게 했다(조용한 동기화를 만들지 않는다).

회귀 `test_document_queue.py` §12/§13 (17검사). 변이 3종 검출 ― 그중 "priority 갱신
누락"은 **처음에 검출되지 않았다.** 시드 priority(3)가 계산값과 우연히 같았기 때문이다.
기일을 +5일로 바꿔(계산값 2) 검사가 실제로 구분력을 갖게 고친 뒤 검출됐다.

### 2. Admin 목록 필터의 잘못된 값이 세 갈래로 처리됐다

Admin 16개 엔드포인트를 경계 상태(무인증/오인증/권한부족/정상/없는대상/잘못된입력)로 전수
스윕했다. 인증·권한·404는 **전부 정확**했다. 필터 검증만 갈려 있었다.

```
registry-requests?status=오타             400  허용값 안내
payments/webhooks?processing_status=오타   400  허용값 안내
payments?status=오타                      200  빈 목록      <- 오타를 "결과 없음"으로 오인
subscriptions?status=오타                 200  빈 목록      <-
audit-logs?target_type=오타               200  빈 목록      <-
```

뒤 세 개에서는 운영자가 필터를 잘못 적어도 "이 상태인 건이 한 건도 없다"로 읽힌다.
**조회 결과가 그대로 운영 판단이 되는 자리**라 조용한 오답이 위험하다(프런트에서 BUGS #31이
"빈 결과"와 "페이지 범위 초과"를 갈라 놓은 것과 같은 부류).

새 정책이 아니라 **이 파일이 이미 쓰던 방식**에 나머지를 맞췄다. 허용값은 전부
`api/constants.py`의 Enum에서 도출한다(손으로 적으면 Enum이 늘 때 조용히 어긋난다).
적용 전 DB의 실제 값이 Enum에 다 있는지 먼저 확인했다(해당 테이블 전부 0행).

회귀 `test_api_regression.py` §31 확장(24검사). 변이 4종 전부 검출 ― 검증 제거,
허용값 안내 문구 제거, 빈 값까지 거부하는 과잉 검증 모두.

### 3. `renew()` ― 호출 0곳인데 검사도 한 갈래뿐이었다

돈을 받고 기간을 늘리는 함수인데 검사는 "GRACE_PERIOD에서 갱신하면 ACTIVE" 하나뿐이었다.
배선되는 순간 어긋나면 **사용자가 산 기간을 잃거나 해지한 구독이 되살아난다.**

전 상태 매트릭스를 `test_subscription_policy.py` §10에 고정했다(18검사).

```
만료 전 ACTIVE      기존 만료 시각에서 이어 붙인다 (잔여 10일 + 30일 = 40일)
이미 만료           지금부터 센다 (과거에서 더하면 갱신하자마자 또 만료)
GRACE/PAUSED/EXPIRED -> ACTIVE 허용
CANCELLED           차단, 그리고 DB도 그대로 (막았는데 값이 바뀌면 의미가 없다)
없는 구독            LookupError
깨진 expires_at     지금부터 세되 **경고를 남긴다**
연속 갱신            누적된다
```

변이 3종 전부 검출(잔여기간 이어붙이기 제거 / 상태전이 관문 제거 / 경고 제거).
제품 정책은 바꾸지 않았다 ― 현재 규칙의 회귀만 막았다.

### 4. Search 핫패스 재측정 (결함 없음)

조건 조합 20종을 각 20회 측정했다.

```
기본/전체/깊은페이지/정렬/지역/별칭/복합    1.2 ~ 4.7 ms (최대 15.3)
감정가·최저가·유찰횟수·최저가율 범위        3.7 ~ 4.7 ms
빈 결과 / 범위 역전 / 상한 초과값          2.4 ~ 3.2 ms, total=0으로 정상 분기
50ms 초과 경로                          없음
```

**측정 중 내 스크립트가 존재하지 않는 파라미터명**(`min_price_from`)을 써서 필터가 무시되는
것처럼 보였다. 실제 이름은 `min_appraisal`/`min_bid_price`였고, 올바른 이름으로 다시 재니
필터는 정확히 동작했다(1,875건 중 1,198건). 프런트도 같은 이름을 쓴다(Sprint 55의 소스
계약이 이미 그것을 고정하고 있다). **제품 결함이 아니라 측정 오류였다.**

### 품질 게이트

```
Python test_*.py   27개 파일 전부 PASS
프런트 계약         93/93 (cancelled 0)
tsc 0 / eslint 0
```

신규 검사: `test_document_queue.py` §12·§13 17 + `test_api_regression.py` 24 +
`test_subscription_policy.py` §10 18 = **59검사 추가**. 변이 10종 전부 검출.

**Sprint 72의 인코딩 가드가 이번 작업에서 두 번 발동했다** ― 내가 새로 쓴 테스트 문자열에
EM DASH를 넣은 것을 `test_document_queue.py:565`, `test_api_regression.py:2248`에서 각각
정확히 지목했다. 가드가 실제 개발 중에 작동함이 확인된 것이다.

---

## 2026-08-13 Sprint 75 ― 검사가 0건이던 경로 채우기 + 감사 로그 원자성

Sprint 74가 결함을 고쳤다면, 이번에는 **"아무도 확인한 적 없는 코드"**를 찾아 들어갔다.
운영 모듈의 공개 함수 82개를 테스트 참조와 대조해 38개가 참조 0건인 것을 확인하고,
그중 Selenium 없이 검증 가능한 것부터 채웠다.

### 1. 크롤 문자열 -> DB 값 변환기가 통째로 미검증이었다

`normalize_price` / `normalize_date` / `normalize_case_no`는 **크롤 원문이 DB 값이 되는
마지막 관문**인데 검사가 0건이었다(`test_normalizer.py`는 주소만 보고 있었다).

중요한 것은 정상 입력이 아니라 **깨진 입력**이다. 실측해서 현재 동작을 그대로 고정했고,
그중 둘은 잠재 위험이라 명시적으로 못박았다.

```
normalize_date("2026-8-19")  -> "2026-8-19"   한 자리 월은 정규화되지 않고 원문 통과
normalize_date("abc")        -> "abc"          날짜가 아니어도 원문 통과
normalize_price("abc")       -> 0              깨진 입력과 "실제 0원"이 구분되지 않는다
normalize_case_no(None)      -> AttributeError price/date와 달리 방어가 없다
```

첫 번째가 특히 위험하다. 이 저장소는 **날짜를 문자열로 비교**한다(D7 필터, 우선순위,
doc_worker의 기일 판정). 정규화되지 않은 값이 섞이면 `'2026-8-19' > '2026-09-01'`이
참이 되어 정렬과 필터가 조용히 어긋난다. 그 위험을 검사로 직접 표현해 두었다.

**실측: 실제 데이터에는 전부 0건이다** ― auction_item/auction/document_queue의
auction_date 형식 위반 0건, case_no 빈 값 0건, 가격 0원 0건. 지금 피해는 없고,
이 검사는 그 전제가 깨지는 순간을 잡기 위한 것이다. (25검사 추가, 총 32 -> 57)

### 2. `get_doc_button_id` ― 모든 문서 수집이 통과하는 한 줄

`doc_worker`는 큐에서 집은 항목마다 이 함수를 부르고 None이면 브라우저를 열지 않고 바로
실패 처리한다. **모든 수집이 여기를 지나는데 검사가 0건**이었다. 35검사로 규약을 고정했다
(물건번호별 버튼 구분, 미지원 None, 공백/생략 처리, 모르는 종류, 대소문자 전용 규약).

측정 중 알게 된 것:

```
이 함수가 None을 주는 큐 행   109 (전체 3,498의 3%)
그중 아직 pending             103   -> 재시도 소진 후 document_status=FAILED가 된다
현재 FAILED 3행 중 1행이 이 경로 (item=14, item_no=7, STATUS)
```

화면에는 "수집실패"로 뜬다. 시도조차 못 한 것과 실패한 것이 같은 문구인데,
**표시 문구를 어떻게 나눌지는 제품 판단**이라 정하지 않았다.

**그리고 "성공할 수 없으니 큐에 넣지 말자"는 방향을 검토했다가 접었다.** 큐에 없으면
document_status가 COLLECTING("수집중")에 영원히 머문다 ― **BUGS #69와 똑같은 상태가
된다.** 지금처럼 빠르게 실패해 FAILED로 남기는 쪽이 더 정직하다. 동작을 바꾸지 않고
그 판단 근거를 테스트 주석에 남겼다.

### 3. 감사 로그의 원자성 ― 계약의 나머지 절반이 미검증이었다

`record_audit()`의 계약은 "commit은 호출부 책임 ― 업무 트랜잭션과 함께 커밋되어야 하므로"다.
지금까지의 검사는 **성공했을 때 로그가 남는가**만 봤다. **실패하면 남지 않는가**는 검증된
적이 없었다.

이 방향이 더 위험하다. 실패한 조작이 로그에만 남으면 **하지도 않은 특권 조작이 기록으로
존재**하게 된다. 감사 로그는 "누가 무엇을 바꿨는가"를 사후에 판단하는 유일한 근거다.

admin.py의 5개 호출부가 전부 `record_audit(...)` -> 같은 커넥션 `conn.commit()` 순서이고
실패 경로는 `rollback()`인 것을 정적으로 확인한 뒤, 실제 응답과 DB로 검증했다.

```
거부된 상태 전이(400)      감사 로그 증가 0
없는 대상 조작(404)        감사 로그 증가 0
권한 부족(403)            감사 로그 증가 0
정상 조작(200)            감사 로그 정확히 +1
```

구조 자체도 고정했다 ― `record_audit` 뒤에 `commit`이 오기 전에 `return`이 끼면
"업무는 커밋됐는데 감사만 빠지는" 상태가 된다. 정적으로만 잡을 수 있는 형태다.
변이 2종 검출(commit 제거 / record_audit 무력화).

### 4. `storage/`가 추적되지 않는다는 문서 서술이 틀렸다

`git status`에 `storage/database.py`가 뜨는 것을 보고 확인했다. `docs/CLAUDE.md`는
"**storage/ is entirely gitignored ... today none of it is tracked**"라고 적고 있었다.

```
git ls-files storage/   ->  23개 파일 (.py 5 / .sql 18)  전부 추적 중
```

2026-08-11 Sprint 51에 `.gitignore`가 정밀화되면서(`storage/*` + `!storage/*.py` +
`!storage/migrations/*.sql`) 이미 해결된 상태였는데 문서 3곳이 옛 서술로 남아 있었다.
**이 서술은 위험하다** ― 그대로 믿으면 `storage/` 변경이 커밋에 안 담긴다고 오판한다.
`docs/CLAUDE.md` 2곳, `docs/search-engine.md` 2곳을 실측값으로 정정했다.

재발 가드도 넣었다(`test_schema_hygiene.py` §6). 검출 원리를 주석에 정확히 적었다 ―
`git ls-files`는 인덱스를 읽으므로 이미 추적 중인 파일은 `.gitignore`를 되돌려도 계속
추적된다. 실제로 잡히는 것은 **(a) 새 파일이 추적되지 않는 경우**(`.gitignore` 되돌린 뒤
019_*.sql 추가 ― 이 시나리오로 검출 확인)와 **(b) `git rm --cached`로 빠지는 경우**다.
둘 다 로컬에서는 멀쩡하고 새로 clone한 환경에서만 터진다.

### 5. 결함 없이 끝난 감사

```
TODO/FIXME/HACK    미처리 0건. SearchForm.tsx의 3건은 전부 TODO(API 미지원)로 표시돼 있고
                   tests/source-contract.test.mjs가 그 표시를 **강제**하고 있다
favorites/recent   DB 레벨 UNIQUE + IntegrityError 처리 - TOCTOU 없음
                   (search_presets는 UNIQUE가 없지만 BEGIN IMMEDIATE로 상한을 지킨다, #66)
Search 핫패스       전 조건 조합 5ms 이하 (Sprint 74 측정)
```

### 품질 게이트

```
Python test_*.py   27개 파일 전부 PASS
tsc 0 / eslint 0 / compileall 0
```

신규 검사: `test_normalizer.py` 25 + `test_document_queue.py` §14 35 +
`test_api_regression.py` 감사 원자성 8 + `test_schema_hygiene.py` §6 6 = **74검사 추가**.
변이 7종 전부 검출.

---

## 2026-08-13 Sprint 76 ― Webhook 서명의 provider별 방어 + 격리 복구 추적

### 1. 유일한 보안 메서드가 provider별로 검증된 적이 없었다

`PaymentProvider`의 생명주기 6개(charge/create_order/confirm_payment/cancel_payment/
verify_payment/handle_webhook)는 KGInicis 자리 구현이 `NotImplementedError`를 던지는지까지
검사돼 있었다. **7번째이자 유일한 보안 메서드인 `verify_webhook_signature`만 빠져 있었다.**

이 메서드의 위치가 특수하다.

```
POST /payments/webhook/{provider_name}     사용자 인증이 없는 공개 경로
  -> URL 이름으로 provider를 고르고
  -> 그 provider의 verify_webhook_signature() 하나로 신뢰 여부를 정한다
```

어느 provider든 이것이 True로 기울면 **누구나 "결제 완료"를 위조**할 수 있다. 기본 구현이
`return False`(fail-closed)로 되어 있고 주석도 그 이유를 적어 뒀지만, **그 기본값이 실제로
유지되는지는 아무도 확인하지 않고 있었다.** KGInicis/toss/portone은 이 메서드를
오버라이드하지 않으므로 전적으로 그 기본값에 의존한다.

14검사를 추가했다.

```
등록된 4개 provider 전부   시크릿 없으면 거절
                          시크릿이 있어도 미구현 provider는 거절(fail-closed 상속)
PaymentProvider 기본 구현  False
mock (유일한 구현)         위조 서명 거절 / 올바른 서명 통과 / 헤더 대소문자 무관
                          서명 헤더 없으면 거절 / 바디 1바이트만 달라도 거절
엔드포인트 수준            POST /payments/webhook/kginicis -> 401
```

변이 검증이 이 검사의 값어치를 보여준다. **기본 구현을 `return True`로 바꾸자 8건이
실패**했다(미구현 provider 3개 x 2 + 기본 구현 + 엔드포인트 401). 서명 비교를 느슨하게
만든 변이는 5건 실패했고, 그중에는 기존 검사인 "미검증 요청은 DB에 저장되지 않는다"도
포함됐다.

**KG이니시스 실연동은 여전히 SKIP이다.** 계약·시크릿·실결제 승인이 필요한 부분은 건드리지
않았고, provider 경계와 webhook 계약처럼 코드·테스트로 준비할 수 있는 것만 했다.

### 2. 격리 복구(Sprint 62)가 어디까지 갔는지 추적

`documents_quarantine/`에 66개 파일이 남아 있는 것을 보고 그 복구가 완결됐는지 확인했다.

```
격리된 (법원,사건,물건)                                      33
  document_status=COLLECTING + 큐 pending 으로 정상 재큐잉    28
  auction_item/큐가 이미 사라진 것                             5
  그 28건의 매각기일이 미래인 것                                0   <- 전부 과거
  실제로 다시 수집돼 파일이 생긴 것                           0 / 33
```

**격리 자체는 설계대로 동작했다** ― 내용이 빈 status 파일을 지우지 않고 옮긴 뒤 재수집
대기로 되돌렸다. 그러나 28건 전부 기일이 지나 **재수집이 구조적으로 불가능**하다.
가치 손실은 아니다(격리 전에도 빈 파일이라 사용자가 얻을 것이 없었다). 다만 결과적으로
"수집중"만 영구히 남는다 ― #69가 지적한 문제의 구체적 사례다.

같은 조사에서 큐 전체의 성격도 드러났다.

```
pending 2,753건 중 매각기일 경과   2,736 (99.4%)
                  아직 미래          17
```

**"pending 2,753"은 실제 남은 일(17)을 크게 부풀린다.** 큐 길이만 보면 크롤이 한참 밀린
것처럼 읽힌다. 두 숫자 모두 `docs/roadmap.md`의 #69 결정 항목에 증거로 넣었다.

### 3. 결함 없이 끝난 감사

```
인증 키/서명 비교   admin.py / payment_providers.py 모두 hmac.compare_digest (타이밍 공격 방어)
                   KGInicisProvider는 조용히 성공하지 않고 NotImplementedError
api/ 비라우트 함수  72개 중 직접 참조 0건은 24개이나 전부 라우트를 통해 간접 검증됨
                   (39/39 라우트 커버리지 - Sprint 72 확인)
crawler/resume.py  test_crawl_resume.py가 사용 중 (죽은 코드 아님)
```

### 품질 게이트

```
Python test_*.py   27개 파일 전부 PASS
프런트 계약         93/93 (cancelled 0)
tsc 0 / eslint 0 / next build 경고 0
```

신규 검사 14개. 변이 2종 전부 검출.

---

## 2026-08-13 Sprint 77 ― 문서 개정 감지: 실행된 적 없는 경로

`document_version_log`가 0행인 것을 보고 배선이 빠진 줄 알았는데, 코드를 읽으니 정상이었다.

```python
if previous_hash and previous_hash != new_hash:
    INSERT INTO document_version_log ...
```

지금까지 수집된 559건이 **전부 최초 수집**이라 비교할 이전 해시가 없었을 뿐이다.

문제는 그 다음이다. **기존 검사는 전부 `previous_hash=""`로만 호출했다.** 즉
"기록하지 않는다"는 쪽만 검증되고 **"기록한다"는 쪽은 한 번도 실행된 적이 없었다.**
그리고 실제 테이블도 정상적으로 0행이라, 이 경로가 깨져 있어도 아무도 눈치챌 수 없다.

왜 중요한가 ― 매각물건명세서는 매각기일 전에 **정정 공고**가 나는 일이 있다. 이 테이블은
"우리가 받아 둔 문서가 그 뒤에 바뀌었다"를 남기는 **유일한 기록**이고, 사용자가 옛 문서를
보고 판단한 것을 나중에 추적할 근거가 여기밖에 없다.

14검사를 추가했다.

```
최초 수집(이전 해시 없음)   기록하지 않는다
내용이 바뀜                기록한다 + 법원/사건/물건/종류/이전해시/새해시/시각이 정확
내용이 같음                재수집해도 기록하지 않는다 (진짜 개정이 묻히면 안 된다)
두 번째 개정               누적된다, 이력이 v1->v2->v3로 이어진다
문서종류가 다름            spec/status가 서로 섞이지 않는다
개정 후 화면 상태          READY 그대로 (개정은 실패가 아니다)
```

변이 2종 검출 ― 기록을 아예 안 하게 하면 4건, 내용이 같아도 기록하게 하면 2건 실패했다.
후자가 중요하다. 재수집마다 로그가 쌓이면 **진짜 개정을 찾을 수 없게 되는데**, 그 형태는
"로그가 남으니 동작한다"고 착각하기 쉽다.

### 품질 게이트

```
Python test_*.py   27개 파일 전부 PASS
프런트 계약         93/93 / tsc 0 / eslint 0 / build 경고 0
```

## 2026-08-13 Sprint 78 ― 형제 함수는 지키는 불변식을 이 함수만 어긴다

Sprint 77이 "실행된 적 없는 경로"를 채운 다음, **"이미 선언된 불변식을 모든 경로가 지키는가"**를
기준으로 훑었다. 결함 3건을 그 방식으로 찾았고, 나머지는 커버리지 측정이 지목한 미검증 경로다.

### 1. `renew()`가 동시 갱신에서 사용자가 산 기간을 잃는다 (BUGS #92)

같은 모듈의 `change_status()`는 2026-08-12에 "조건부 UPDATE + rowcount 확인" 가드를 얻었다.
**돈을 받고 기간을 늘리는 쪽에만 그 가드가 없었다.**

```
기존 만료 2026-06-25에 30일 갱신 2건(= 결제 2건)
  기대 60일   실제 30일   <- 한 주기 소실, 예외도 경고도 없음
journal_mode delete/wal 양쪽 동일 (WAL 전환과 무관하게 이미 열려 있었다)
```

재현은 스레드가 아니라 **결정적 끼워넣기**로 했다(`test_race_conditions.py` §6/§7이 이미
"스레드 경합은 창이 좁아 변이를 항상 잡지 못한다"고 기록해 둔 것을 따랐다). UPDATE 직전에
다른 커넥션의 갱신을 완주시키면 100% 재현된다.

`BEGIN IMMEDIATE`는 쓰지 않았다 ― `renew()`는 호출부가 트랜잭션을 소유하는 계약이라
여기서 새 트랜잭션을 시작하면 기존 호출부가 깨진다. 낙관적 잠금만으로 같은 보호를 얻는다.
`expires_at`은 NULL일 수 있어 `=`가 아니라 `IS`로 비교해야 한다(변이 M4가 이 함정을 잡았다).

거부만 검증하면 절반이다 ― **재시도하면 두 주기가 정확히 누적**되는 것까지 본다. 변이 4종 검출.

### 2. 재시도 복구가 화면 상태를 되돌리지 않았다 (BUGS #73)

`mark_queue_failed()`가 자기 규칙을 적어 두었다 ― "재시도가 소진된 **최종** 실패만 화면에
반영한다". 그런데 `reset_stale_queue()`가 그 행을 `pending`+`retry_count=0`으로 되돌리면서
`document_status`는 FAILED로 남겼다. 재시도 대기 중인 문서가 "수집실패"로 보인다.

`FAILED`인 행만 되돌린다 ― READY를 COLLECTING으로 덮으면 **파일이 실제로 있는 문서를
"수집중"으로 가린다**(정반대 방향의 결함). 그 반대 방향도 회귀에 넣었다.

**수정 중 기존 테스트가 내 변경의 결함을 잡았다**: 처음 구현은 화면 동기화 예외를 그대로
올려 **회수 UPDATE까지 롤백**시켰다(고치려던 것보다 나쁘다). 축소 스키마 임시 DB에서
§6이 즉시 검출했다. `_set_document_status()`의 "경고+False" 판단과 같게 격리했다. 변이 5종 검출.

### 3. Admin webhook `provider` 필터가 오타를 빈 결과로 돌려줬다 (BUGS #93)

Sprint 74가 통일한 규약(잘못된 필터 값은 400)의 **누락 인스턴스**였다. 같은 함수 안에서
바로 위 `processing_status`는 검증되고 `provider`는 그대로 SQL로 들어갔다.
허용값은 `_PROVIDERS` 맵에서 도출하고(webhook 수신 경로가 같은 맵으로 검증한다),
수신 경로와 **같은 정규화**(`.strip().lower()`)를 적용해 `provider=Mock`이 거부되는 비대칭도 없앴다.

Admin 16개 엔드포인트를 코드에서 열거해 차원별(인증/권한/없는 ID/필터/페이지 경계/body)로
전수 프로브했고, 미검증 SQL 등호 필터는 이 하나뿐이었다(`/admin/users`·`/admin/subscriptions`의
`plan`/`status`는 **선언되지 않은 파라미터**라 FastAPI가 무시하는 것 ― 필터가 아니다).

### 4. 커버리지로 찾은 미검증 경로 3건 (BUGS #74/#75/#76) ― 제품 결함은 없었다

전체 스위트를 커버리지로 돌려(71%) 추측이 아니라 측정으로 골랐다.

```
api/auth.py 81%       미커버 55-64, 78-83   JWKS 키 회전/속도제한 전체
api/v1/search.py 82%  미커버 266-305        필터 12개(court_name/status/날짜상한/4개 범위)
storage/database.py 80% 미커버 245-257      upsert_batch 행 단위 격리 + 전체 롤백
```

세 곳 모두 **구현은 옳았고 검사만 없었다**. 각각 12/20/16검사를 추가했다(네트워크·실크롤 없음 ―
`urllib.request.urlopen` 대역, 실제 데이터 중앙값 기준 경계, 스크래치 DB 사본).

### 5. 변이 시험이 **무력한 검사** 2건을 잡았다 (이번 Sprint의 가장 중요한 소득)

- 검색 필터 검사에서 "`court_name`을 `status` 컬럼에 오배선" 변이가 **검출되지 않았다.**
  필터가 엉뚱한 컬럼에 걸리면 결과가 0건이 되고, "돌아온 모든 행이 조건을 만족한다"가
  **공허하게 참**이 된다. 구분력 단언(최소 1건은 나와야 한다)을 먼저 두어 고쳤다.
- 가드 제거 변이가 **크래시**로 끝나 남은 검사가 실행되지 않는 하네스 결함 2곳
  (`upsert_batch`/JWKS 호출). 예외를 FAIL로 바꿔 원인과 범위를 함께 보게 했다.

### 6. 측정 코드 자체의 오판 3건도 기록한다

"내 측정이 맞는가"를 매번 확인했고, 실제로 세 번 틀렸다.

```
쿼리 카운터가 모든 엔드포인트를 0쿼리로 보고    api/v1/*이 import 시점에 이름을 바인딩해
                                              모듈 속성 교체가 닿지 않았다
고아 큐 행이 3,498행 -> 128,469행으로 불어남   court_code만으로 조인해 행이 곱해졌다
upsert_batch 99문장 전체가 미커버로 읽힘        테스트 파일 일부만 실행했다
```

세 번 다 **불가능한 숫자**가 먼저 눈에 걸려 잡았다. 그래서 새로 넣은 고아 측정 검사는
"조인 결과 행 수 == 큐 행 수"를 **먼저** 단언한다.

### 7. 결함이 아니었던 것 (실측으로 반증)

| 확인 대상 | 결과 |
|---|---|
| 다물건 사건의 문서 수집 누락 의심 | **반증** — 살아 있는 물건 9/9(비1번 물건 2건 포함)이 전부 큐에 있다. 비1번 물건 520건이 큐에 없는 것은 전부 **기일이 지난 과거 물건**이고, 만료 물건을 큐에 넣지 않는 1차 방어선의 정상 동작이다 |
| 핫패스 성능 | PASS — item detail 2.2ms(6쿼리) / favorites 2.6ms(2쿼리, N+1 없음) / recent 2.6ms / subscriptions 2.3ms / payments 2.3ms / search 2.6ms / deep page(offset 1000) 2.5ms / doc-stats 3.0ms, 전부 p95 ≤ 3.4ms. 최적화하지 않았다 |
| `logs/*.py` 중복 사본 | 기존 판단 그대로 — git 비추적 + 문서에 stale로 증명돼 있다(새 발견 없음) |
| 고아 큐 행 18행 | 실측 기록 + 측정 경로 고정. 기일이 미래인 고아 pending은 0건이라 실제 낭비는 없다. 운영 DB 행 정리는 범위 밖(#70과 같은 판단) |

### 품질 게이트

```
Python test_*.py   27개 파일 전부 PASS
frontend           93/93 PASS (Next + FastAPI 로컬 기동 후)
tsc 0 / eslint 0 / next build 성공 / compileall 0
```

신규 검사: renew 동시성 9 + 재시도 복구 15 + 고아 측정 4 + provider 필터 6 + JWKS 12 +
검색 필터 20 + upsert 격리 16 = **82검사 추가**. 변이 22종 검출(무력한 검사 2건 수정 포함).

### 8. Release Audit ― "미확인"으로 남아 있던 P0 두 건을 실측으로 확정 (Sprint 78 추가)

비밀값을 **열람하지 않고** 판정할 수 있는 방법으로 확인했다(이름 존재 여부 + 서버 응답 코드).

```
P0-4  SUPABASE_JWT_SECRET  이름 있음 + 값 채워짐 (88자)   -> 이 환경에서는 해소
      JWT_SECRET           없음                          -> 체크리스트가 권한 "이름 변경"이 수행됐다
      SUPABASE_URL         이름은 있고 값은 비어 있음      -> api/auth.py가 NEXT_PUBLIC_SUPABASE_URL로 폴백
                                                            (그 폴백 경로를 §6 회귀로 고정)

P0-2  ADMIN_API_KEY / SUPER_ADMIN_API_KEY   이름 자체가 없다
      PAYMENT_WEBHOOK_SECRET                이름 자체가 없다
      /admin/users, /admin/payments, /admin/subscriptions, /admin/audit-logs  전부 500
      -> "Admin 전체 500"은 여전히 사실. 2026-08-08 기록("이름은 있음")과 달라 정정했다
```

값을 읽지 않고 판정된 근거는 코드 계약이다 — `os.getenv()`는 빈 값을 falsy로 주고
`_require_role()`은 두 키가 모두 없을 때 500을 반환한다. `PAYMENT_WEBHOOK_SECRET` 부재는
결함이 아니라 fail-closed 기본값이지만(Webhook 수신 401), 실연동 시 필요한 값이므로 함께 적었다.

`.env` 수정은 승인 영역이라 손대지 않았다 — **확인과 문서 정정만** 했다.

### 9. 코드가 의존하는 UNIQUE 제약을 구조로 고정 (BUGS #77, Sprint 78 추가)

`add_favorite()`이 중복을 애플리케이션에서 확인하지 않는다는 점에서 출발했다 — TOCTOU를
피하는 옳은 설계이지만, 그렇다면 정확성이 **DB 제약에 걸려 있다**는 뜻이다. 세 경로가
그렇게 동작하는데(favorites / recent_items / payment_webhooks 멱등성) 제약을 강제하는
검사가 없었다. 제약이 사라지면 예외도 로그도 없이 세 방어가 함께 무력화된다.

migration 018이 `document_queue`를 테이블 재생성으로 바꾼 전례가 있으므로 가정이 아니다 —
재생성 SQL에서 UNIQUE 한 줄이 빠지면 데이터는 옮겨지고 제약만 사라진다.

`test_schema_hygiene.py` §7이 DDL 선언 + **실제 데이터 중복 0건**을 함께 본다. 변이 검증은
스크래치 사본에서 018과 같은 방식으로 UNIQUE를 떨어뜨려 수행했다(실제 DB 무변경) → 즉시 검출.
작성 중 `payment_webhooks` DDL의 **주석에 든 "UNIQUE"** 때문에 통과할 수 있는 함정을 발견해
주석 제거 후 판정하도록 고쳤다.

### 10. 편집 도구가 BOM을 떨어뜨려도 아무도 잡지 못했다 (BUGS #78, Sprint 78 추가)

이번 Sprint의 변이 시험 스크립트가 `utf-8-sig` 읽기 + `utf-8` 쓰기로
`normalizer/normalizer.py`의 BOM을 떨어뜨렸다. **테스트 27개 전부 PASS였다** — Python은 두
형태를 모두 실행하고, `test_console_encoding.py`는 `utf-8-sig`로 읽어 BOM 유무에 둔감하다.
발견 경로는 `git diff`를 사람이 본 것 하나뿐이었다.

BOM을 복원해 HEAD와 바이트 단위로 동일함을 확인했고(제품 코드 변경 0),
`test_schema_hygiene.py` §8로 "변경된 소스의 BOM 유무가 HEAD와 같다"를 고정했다.
BOM을 일부러 떨어뜨리면 파일명까지 지목하며 FAIL하고, 그 상태에서
`test_console_encoding.py`는 여전히 PASS다 — 새 검사만이 잡는 결함임이 확인됐다.

작성 중 함정 1건: `BOM = b"..."` 리터럴은 **그 파일 자체의 인코딩에 휘둘린다**
(`SyntaxError: bytes can only contain ASCII literal characters`). `codecs.BOM_UTF8`로 고쳤다 —
인코딩을 검사하는 코드가 인코딩에 의존하면 안 된다.

---

## 2026-08-13 Sprint 78 ― 지역 분류 결함 (BUGS #92)

### 발견 경로 ― validator가 오탐을 낸 것이 아니었다

크롤 파이프라인에서 유일하게 남은 미검증 계층인 **validator**를 보러 갔다.
`ValidationEngine.validate()`는 수집된 모든 물건의 PASS/FAIL을 정하는데 **규칙 자체의
검사가 0건**이었다(기존 2검사는 로그 기록 경로만 본다).

실데이터를 먼저 쟀다. PASS 1,864 / FAIL 12, 그중 `address_mismatch`가 11건.
**이게 오탐인지 진짜인지**를 확인하러 들어갔고, 오탐이 아니었다. validator는 제 일을 했고
그 뒤에 더 큰 결함이 있었다.

### 판정이 문자열 위치가 아니라 **사전 선언 순서**로 정해졌다

```python
for sido, patterns in SIDO_PATTERNS.items():   # 서울, 경기, 인천, ... 세종, ... 제주(마지막)
    for p in patterns:
        if p in text:      # 위치를 보지 않는다
            return sido
```

실측 결과 1,876건 중 **4건이 잘못 분류**돼 있었고 원인이 전부 다르다.

```
경기도 시흥시 서울대학로 59-21                -> 서울 (실제 경기)   도로명
경상남도 양산시 물금읍 부산대학로 150          -> 부산 (실제 경남)   도로명
인천광역시 계양구 ... (효성동, 뉴서울아파트)    -> 서울 (실제 인천)   건물명
제주특별자치도 제주시 ... 주식회사 뉴세종하우징  -> 세종 (실제 제주)   공유자(법인) 이름
```

마지막 건이 성격을 가장 잘 보여준다. **"제주특별자치도"가 0번 위치에 있는데 539번 위치의
"세종"에게 졌다.** 오직 사전에서 세종이 제주보다 위라는 이유였다.

`sido`는 검색의 1차 필터다. 잘못 분류된 물건은 **제 지역에서 검색되지 않고 남의 지역을
오염시킨다.** 그리고 `서울대학로`/`부산대학로`는 실재하는 도로명이라 **반드시 재발한다**.

### 수정 ― 가장 앞선 표기가 이긴다

위치가 같으면 더 긴(구체적인) 표기를 택한다. 지역명이 앞에 오지 않는 입력
(검색어 "강남구 아파트", 감정요항 자유 텍스트)은 기존 동작 그대로다 ― 이 함수는 주소
전용이 아니라 세 용도에 쓰이므로 "접두어만 본다"가 아니라 "가장 앞선 언급"으로 고쳤다.

**전수 재계산: 1,876건 중 정확히 그 4건만 바뀌었다**(나머지 1,872건 무변동).

### 같은 판정을 하는 함수가 두 벌이었다

`validator/validation_engine.py`에 **바이트 단위로 동일한 복사본**이 있었다. 그 파일 주석은
데이터(SIDO_MAP)를 "한쪽만 남기고 재사용한다"고 적어 뒀는데 **해석하는 함수는 합쳐지지
않은 채** 남아 있었다.

복사본을 그대로 뒀다면 **크롤은 제주로 저장하는데 검증은 세종으로 판정**해, 멀쩡한 물건에
address_mismatch가 붙고 화면에 "검증실패"로 떴을 것이다. normalizer의 것을 재노출하도록
바꿔 호출부는 그대로 두고 중복만 없앴다.

### 검증 규칙 자체도 고정했다 (38검사)

필수 필드 4종 x 2형태 / 가격 허용오차 경계(정확히 +1000원은 PASS, +1001원은 FAIL) /
사건번호 형식(병합사건 표기 허용) / 인접 광역시-도 예외 / 한쪽을 못 뽑으면 비교하지 않음 /
사유 누적. **BUGS #92 회귀**(도로명이 오탐을 만들지 않는가)도 여기 넣었다.

변이 3종 전부 검출 ― 허용오차 무시, 인접 예외 제거, 사유를 첫 건만 남기기.

### 남은 데이터

기존 4행은 **매각기일이 전부 지나** 재크롤 대상이 아니라 DB에 잘못된 `sido`가 남는다.
다만 만료 물건이라 검색(D7 기본 제외)에는 나오지 않는다. **운영 데이터를 임의로 고치지
않았다** ― 필요하면 4행 UPDATE로 끝나는 작업이다.

### 품질 게이트

```
Python test_*.py   27개 파일 전부 PASS
tsc 0 / eslint 0 / compileall 0 / next build 0
```

신규 검사: `test_normalizer.py` 13 + `test_validation_log_integrity.py` 38 = **51검사 추가**.
변이 7종 전부 검출.

### 11. 검증 판정 로직이 커버리지 0%였다 (BUGS #79, Sprint 78 추가)

커버리지 재측정에서 `validator/validation_engine.py` 52%, 미커버 구간이 `validate()` 전체.
`validation_status`는 검색 필터와 화면 표시까지 흐르는 값인데 판정 로직이 미검증이었고,
**같은 날 이 파일의 `extract_sido`가 수정됐다**(중복 제거). 검사 0건 상태에서 판정 로직을
건드린 상태였다.

`test_validation_engine.py` 신규(62검사, 28번째 테스트 파일). 필수 필드는 빈 문자열과 `"-"`
두 형태를 모두 확인하고(크롤러가 `"-"`를 기본값으로 넣는다), 선언된 인접 시도 11쌍이 실제
판정과 일치하는지 양방향으로 본다. 가격은 tolerance 정확히/+1원 두 경계를 둬서 경계 이동
변이까지 잡는다. 변이 7종 전부 검출.

이 작업 중 `validator/validation_engine.py`의 BOM을 변이 스크립트가 다시 떨어뜨리지 않도록
읽기/쓰기에서 BOM을 보존했고, §8 검사로 결과를 확인했다(HEAD와 BOM 상태 동일).

---

## 2026-08-13 Sprint 79 ― D7 경계 + 실행 환경 함정 2건

### 1. "오늘이 매각기일인 물건이 보이는가"가 검증된 적이 없었다

기존 D7 검사는 `include_closed=true`면 건수가 **같거나 는다**만 봤다. 그래서 기본 필터가
`auction_date >= today`에서 `> today`로 바뀌어도 **그대로 통과한다.**

그 한 글자가 바뀌면 **매각 당일 아침에 그 물건이 검색에서 사라진다.** 사용자가 가장 절실하게
찾는 시점에 사라지는 셈이다.

실측상 오늘이 기일인 물건이 0건이라 기존 데이터로는 확인할 수 없었다. 어제/오늘/내일
픽스처를 만들어 경계를 데이터로 못박았다(7검사, 픽스처 정리까지 확인).

```
기본            오늘 + 내일          (어제는 빠진다)
include_closed  어제 + 오늘 + 내일
auction_date_from 명시  기본 필터를 대체한다 (기존 계약)
```

변이(`>=` -> `>`)에서 2건이 실패했다.

### 2. 실행 환경 함정 두 가지를 문서에 남겼다

둘 다 **제품 결함이 아닌데 결함처럼 보이는** 것들이라 절차 문서에 적었다.

```
npm run build 가 EPERM ... unlink '.next/static/...' 으로 실패
  -> 저장소가 OneDrive 동기화 폴더 안에 있어 방금 쓴 산출물을 OneDrive가 잡고 있다.
     dev 서버가 떠 있을 때도 같은 증상. `.next` 지우고 다시 빌드하면 통과.

npm run build 직후 npm run dev 를 띄우면 첫 화면이 500
  -> production 산출물과 dev가 같은 `.next`를 공유해 충돌.
     `.next` 지우고 dev를 다시 띄우면 정상.
```

두 번째는 특히 **프런트 계약 테스트를 통째로 무너뜨린다** ― 93검사가 전부 실패하는데
원인은 코드가 아니다. Sprint 72에 고친 "백엔드 미기동 오진"과 같은 부류라 함께 적어 뒀다.

### 3. 세션 중 자체 실수 1건 (기록)

변이 시험 스크립트가 `utf-8-sig`로 파일을 복구해 **BOM이 없던 `api/v1/search.py`에 BOM을
추가**했다. `test_schema_hygiene.py`의 BOM 가드가 즉시 잡아 정정했다. 도구가 작업자를
잡은 사례라 남겨 둔다.

### 품질 게이트

```
Python test_*.py   27개 파일 전부 PASS
프런트 계약         93/93 (cancelled 0, skipped 0)
Beta Journey Gate   PASSED
tsc 0 / eslint 0 / compileall 0 / next build 0
```

### 12. 결제 실패 경로에 사유가 없었다 (BUGS #80, Sprint 78 추가)

커버리지가 지목한 마지막 결제 경로("실연동 전 provider로 환불 시도")를 검증하다 발견했다.
돈 안전 불변식(상태 불변 + 원장 기록)은 지켜졌지만 **사유가 비어 있었다** —
`PaymentProvider`의 6개 메서드가 `raise NotImplementedError`(인자 없음)였고 확정 PG인
`KGInicisProvider`가 그것을 물려받는다. `payment_logs.error_message=''`,
응답은 `"환불 처리에 실패했습니다: "`로 콜론 뒤가 비었다.

`_not_implemented(method)`로 **어느 provider의 어느 단계**인지 담게 고쳤다(6개 메서드 공통).
검사 9건 추가, 변이 2종 검출(사유 제거 / 실패인데 REFUNDED로 전이 — 최악의 결과).

검사를 쓰며 **내 가정 2건이 틀렸다**: (1) Admin 실패는 envelope가 아니라 `detail`이다
(문서화된 기존 결정), (2) Mock 결제의 완료 상태는 레거시 `SUCCESS`이지 `PAID`가 아니다.
후자는 특정 값을 하드코딩하지 않고 **시도 전 상태와 비교**하도록 고쳐 provider와 무관하게
성립하는 검사로 만들었다.

### 13. 데이터 모듈도 무결성 검사 대상이다 (Sprint 78 마무리)

`config/courts.py`는 커버리지 0%인 데이터 모듈이라 "테스트할 것이 없다"고 넘기기 쉽지만,
그 60줄이 곧 **매일 크롤하는 대상 전체**다. 손으로 편집하는 목록이라 깨지는 방식이 정해져 있다.

```
code 중복    -> 같은 법원을 두 번 돌고, 식별키가 (court_code, case_no, item_no)라
                두 번째 크롤이 첫 번째를 UPDATE한다(#18과 같은 계열의 소실)
한 줄 삭제   -> 그 법원 물건이 조용히 사라진다(검색 결과가 줄어드는 것 외 신호 없음)
region 오타  -> get_courts_by_region()이 빈 목록을 주고 지역별 실행이 0건이 된다
```

`test_schema_hygiene.py` §9로 8검사 추가 — 개수 60 / code·name 중복 0 / 빈 값 0 /
`code == name`(이 저장소의 실측된 전제) / region이 SIDO_LIST 안 / **지역별 조회의 합이 전체와
같다**(누락·중복 동시 검출). 법원 추가·제거는 운영 결정이므로 개수를 박아 두어 의도적으로
바꿀 때 이 검사를 함께 갱신하게 했다.

작성 중 **내 문자열이 cp949 불가 문자(U+2014)를 써서** UnicodeEncodeError가 났다 —
이 저장소가 `test_console_encoding.py`로 막고 있는 바로 그 유형이다. U+2015로 고쳤고,
인코딩 가드도 함께 통과함을 확인했다.

---

## 2026-08-13 Sprint 80 ― 부가 기능의 실패가 본 기능을 무너뜨리지 않는가

`api/v1/item.py`는 최근조회 기록을 try/except로 감싸고 실패해도 상세 조회를 계속한다.

```python
try:
    record_view(conn, user_id, item_id)
except Exception:
    logger.warning("최근조회 기록 실패 (item_id=%s)", item_id, exc_info=True)
```

의도는 분명하다 ― **부가 기능(최근조회)의 실패가 본 기능(물건 상세)을 죽이면 안 된다.**
그런데 그 계약은 검증된 적이 없었고, `record_view` 자체도 테스트 참조 0건이었다.
`except`를 지우거나 좁히면 **DB 잠금 한 번에 상세 화면 전체가 500**이 되는데,
기존 검사는 전부 정상 경로만 탄다.

`record_view`에 `sqlite3.OperationalError("database is locked")`를 주입해 확인했다(6검사).

```
상세 응답            200, 본문의 id도 정상
경고 로그            남는다 (조용히 삼키면 원인 추적이 불가능하다)
recent_items 행      생기지 않는다
주입 해제 후          다시 정상 기록된다 (패치가 남지 않았는지 확인)
```

반대쪽(조용히 삼키기만 하고 흔적을 안 남기는 것)도 함께 고정했다.

### 가드가 실패할 때 원인을 말하게 만들었다

처음 만든 검사는 변이(`except Exception` -> `except ZeroDivisionError`)에서
**깔끔한 FAIL이 아니라 스위트 크래시**로 끝났다. TestClient가 서버 예외를 그대로 다시
던지기 때문이다. 그 형태로는 무엇이 잘못됐는지 보이지 않는다.

예외를 붙잡아 FAIL로 바꾸도록 고쳤고, 이제 같은 변이에서 **2건이 정확한 문구로 실패**한다.

```
[FAIL] 기록 실패가 상세 조회 밖으로 새어 나오지 않는다
       -> record_view의 예외가 그대로 전파됐다(try/except가 사라졌는가?)
[FAIL] 기록 실패가 경고 로그로 남는다
```

Sprint 72의 "게이트가 원인과 무관한 문구로 실패하던" 문제와 같은 부류를, 이번에는
**검사를 만드는 단계에서** 발견해 고친 것이다.

### 품질 게이트

```
Python test_*.py   27개 파일 전부 PASS
프런트 계약         93/93 / Beta Journey PASSED
tsc 0 / eslint 0 / compileall 0 / next build 0
```

---

## 2026-08-13 Sprint 81 ― 화면에 찍히는 금액에 동작 테스트가 없었다

`src/lib/format.ts`에는 **소스 계약만** 있었다. `tests/source-contract.test.mjs`가
"formatWon이 한 곳에만 정의되는가", "마이페이지가 formatWon을 쓰는가"를 확인하지만
**그 함수들이 실제로 무엇을 출력하는지는 한 번도 검증된 적이 없었다.**

파일 주석은 이미 위험을 적어 뒀다 ― `formatPrice(12900)`은 **"1만"**이 되어 실제
청구액과 2,900원(22%) 어긋난다. 그래서 청구 금액에는 `formatWon()`을 쓰라고. 그런데
**그 불변식이 코드로 고정돼 있지 않았다.**

`tests/format.test.mjs` 신설(13검사). 경계와 역할 구분을 못박았다.

```
formatPrice   0 -> '-'  (없는 값을 "0원"으로 보이면 안 된다)
              9999 -> '9999' / 10000 -> '1만'          만 단위 경계
              99999999 -> '10000만' / 100000000 -> '1.0억'  억 단위 경계
formatPriceEok 0 -> '0.0억' (formatPrice와 다른 지점) / 1억 이상은 formatPrice와 동일
formatWon     12900 -> '12,900원'  ★ 억/만이 절대 나오지 않는다
              표시 문자열에서 숫자만 남기면 원래 금액과 정확히 일치해야 한다
              확정 구독가 4종(12,900 / 154,800 / 22,900 / 198,000) 전수
```

**표기 기준 자체는 바꾸지 않았다.** `formatPrice`와 `formatPriceEok`가 공존하는 것은
파일 주석이 적어 둔 대로 **미결정 상태**이고, 어느 쪽으로 통일할지는 화면 숫자가 바뀌는
UX 결정이다. 지금 동작을 그대로 고정하기만 했다.

변이 3종 전부 검출 ― formatWon이 축약하도록 / 1억 경계를 한 자리 밀기 /
0을 하이픈으로 안 바꾸기.

### 결함 없이 끝난 확인

```
시군구 단독 검색   sigungu=강남구 -> 3건 (sido+sigungu와 동일). 일반구(일산동구)도 정상
동 단독 검색       dong=역삼동 -> 2건
존재하지 않는 구    total=0 (200)
```

### 품질 게이트

```
Python test_*.py   27개 파일 전부 PASS
프런트 계약         106/106 (93 -> 106, cancelled 0)
tsc 0 / eslint 0
```

---

## 2026-08-13 Sprint 82 ― 회귀 스위트가 무작위로 실패하던 진짜 이유

최종 검증을 돌리다 전체 스위트가 **실행할 때마다 다른 파일에서** 1~3개씩 실패했다.
단독으로 돌리면 전부 통과했다. 코드에서 원인을 찾을 수 없는 형태다.

원인은 **내가 프런트 계약 테스트를 위해 띄워 둔 `uvicorn`**이었다. `test_*.py`의 상당수가
실제 `auction.db`에 쓰고(롤백하더라도 쓰기 잠금은 잡는다), API 서버가 같은 파일을 붙들고
있으면 SQLite 쓰기 잠금이 경합한다.

```
API 서버 켠 채    28개 중 1~3개가 실행마다 다르게 실패
API 서버 내린 뒤  28/28 PASS (2회 연속 확인)
```

이번 세션에서 찾은 **네 번째 "제품 결함이 아닌데 결함처럼 보이는"** 항목이다.

```
Sprint 72  백엔드 미기동 -> "즐겨찾기 버튼이 없습니다"로 오진
Sprint 79  OneDrive 잠금 -> npm run build가 EPERM
Sprint 79  build 후 dev  -> 첫 화면 500
Sprint 82  API 서버 기동 -> Python 회귀가 무작위 실패
```

넷 다 `docs/TEST_PLAN.md`에 증상과 해결을 적어 뒀다. 공통점은 **증상이 원인과 전혀 다른
자리에서 나타난다**는 것이고, 그래서 매번 코드를 의심하며 시간을 쓰게 된다.
권장 순서는 "프런트 계약(서버 필요) -> 서버 종료 -> Python 회귀"다.

### 최종 상태

```
Python test_*.py   28/28 PASS  (서버 종료 상태, 2회 연속)
프런트 계약         106/106 (cancelled 0)
Beta Journey Gate   PASSED
tsc 0 / eslint 0 / compileall 0 / next build 0
```

---

## 2026-08-13 Sprint 83 ― 중복 테스트 정리 + 커버리지 산출물 추적 누락

### 1. 같은 규칙을 두 파일이 각자 검증하고 있었다

작업 중 `test_validation_engine.py`(79검사)가 새로 생겼는데, 같은 세션에 내가
`test_validation_log_integrity.py` §3에 넣은 검증 규칙 검사(38검사)와 **같은 규칙을
각자 검증**하고 있었다.

테스트 중복은 로직 중복보다 덜 위험하지만 같은 문제를 만든다 ― 규칙이 바뀔 때 **한쪽만
고쳐질 수 있고**, 읽는 사람은 어느 쪽이 기준인지 알 수 없다. 이 저장소가 Sprint 78에
`extract_sido` 복사본에서 겪은 것과 같은 구조다.

**커버리지를 잃지 않고** 정리하려면 먼저 대조가 필요했다. 두 파일의 검사 이름을 전부 뽑아
비교했더니 내 쪽에만 있는 것이 4건이었고, 그중 3건은 실제로 의미가 있었다.

```
BUGS #92 도로명 오탐 회귀    "경기도 시흥시 서울대학로"가 가짜 불일치를 만들지 않는가
건물명 오탐 회귀             "(효성동, 뉴서울아파트)"도 같은 부류
병합사건 번호 형식           "2019타경10346 / 2020타경105127" (실데이터에 존재)
```

이 셋을 전용 파일로 옮기고, `test_validation_log_integrity.py`는 **이름이 말하는 책임**
(로그 기록 무결성)으로 되돌렸다. 규칙 검사가 어디 있는지 가리키는 주석만 남겼다.

### 2. 대조하다 진짜 공백을 하나 더 찾았다

가격 비교 가드는 `if appraisal > 0 and minimum > 0:`으로 **양쪽 모두**를 막는다.
그런데 전용 파일은 **최저가 쪽만** 검증하고 있었다(`minimum_bid_price="비공개"`).

감정가 쪽 가드는 미검증이었다. 그것을 지우면 **감정가가 0인 물건이 전부
"최저가 > 감정가(0)"로 잡혀 대량 오탐**이 된다.

검사를 추가하고 변이(`if minimum > 0:`)를 넣으니 **새 검사에서만** 잡혔다 ―
그 가드가 정말로 검증된 적이 없었다는 증거다.

```
정리 전  test_validation_engine 79 + log_integrity §3 38 = 117 (중복 포함)
정리 후  test_validation_engine 84 + log_integrity 11     = 95  (중복 제거 + 신규 5)
```

### 3. `.coverage`가 추적 대상이었다

`.gitignore`에 `/coverage`(JS 도구용 디렉터리)는 있지만 Python `coverage.py`의
`.coverage`는 없었다. 게다가 이 파일은 **확장자 없는 SQLite 파일**이라 `*.db` 규칙에도
걸리지 않는다 ― 42MB짜리 DB 백업이 커밋돼 있던 것(`.gitignore` 51~59행이 기록)과
**정확히 같은 부류의 누락**이다.

`.coverage` / `.coverage.*` / `htmlcov/` / `coverage.xml`을 추가했다. `coverage` 패키지는
requirements.txt에 넣지 않았다 ― 소스가 import하지 않는 개발 도구라, 넣으면
`test_schema_hygiene.py` §4의 "목록에만 있고 안 쓰는 항목" 검사에 걸린다.

### 4. 전체 회귀가 한 번 10분을 넘겼다 (일시적)

`.gitignore` 수정 직후 전체 회귀가 도구 상한(10분)에 걸렸다. 파일별로 계측하니
**전 파일이 3초 이내**였고(가장 느린 `test_beta_journey.py`가 4초), 다시 돌리니
**28개 전체가 17초**에 끝났다. git 인덱스 재계산/OneDrive 스캔과 겹친 일시적 현상이다.
Sprint 82에 적은 것과 같은 부류라 별도 문서화는 하지 않는다.

### 품질 게이트

```
Python test_*.py   28/28 PASS (17초)
tsc 0 / eslint 0 / compileall 0
```

---

## 2026-08-13 Sprint 84 ― 커버리지로 미검증 경로 찾기

지금까지는 "어디가 안 보이는가"를 사람이 추론했다. 이번에는 **커버리지를 실제로 돌려**
전 모듈을 줄 단위로 재게 했다.

```
crawler/base_crawler.py     0%   Selenium 의존 - 구조적으로 불가(브라우저 필요)
crawler/court_crawler.py    0%   같은 이유
crawler/doc_crawler.py     23%   같은 이유
config/courts.py           56%   <- 테스트 가능한데 낮다
storage/database.py        86%
validator/validation_engine 52%  <- Sprint 83에 이미 100%로 올림
api/* 대부분               88~100%
```

### 1. 일일 크롤의 유일한 DB 쓰기 경로에 실패 처리 검사가 없었다

`storage/database.py` 254-257행(전체 롤백)이 미커버였다. 그 함수 `upsert_batch()`는
`mvp_scraper.py:107`이 **매일 부르는 유일한 DB 쓰기 함수**다. 실패 처리가 두 갈래인데
둘 다 한 번도 실행된 적이 없었고, **의미가 정반대**다.

```
행 단위 실패(안쪽 except)  그 행만 건너뛰고 failed++ -> 나머지 행은 그대로 저장
                          법원 한 곳의 값 하나가 깨졌다고 그날 수집분 전체를 잃으면 안 된다
커밋 실패(바깥 except)     전부 rollback + 예외 재전파
                          여기서 삼키면 mvp_scraper가 성공으로 보고한다
```

후자가 특히 위험하다. 조용히 0건 저장하고 성공으로 끝나면 크롤이 멈춘 사실을 아무도
모른 채 며칠이 지난다 ― **2026-08-03~11에 실제로 일어났던 사고**이고 Sprint 54가
없앤 "실패 은폐"가 되살아나는 자리다.

11검사를 넣었다(정상/UPDATE/행 단위 실패 격리/커밋 실패 롤백+전파). 변이 2종 검출.

### 2. 1차 방어선 ― 만료 사건을 애초에 큐에 넣지 않는 분기

`enqueue_documents()`의 `skipped_expired` 분기(364-365행)도 미커버였다. 이것은 코드 주석이
**1차 방어선**이라 부르는 것이고, doc_worker의 2차 방어선과 짝을 이룬다.

```
어제 기일   큐에 안 들어간다 + skipped_expired로 보고된다
오늘 기일   들어간다 (아직 매각 전 - D7 경계와 같은 규칙)
미래 기일   들어간다
기일 없음   거르지 않는다 (모른다고 버리지 않는다)
```

### 3. 가드가 실패할 때 원인을 말하게 (또 한 번)

행 단위 except를 제거하는 변이가 처음엔 **깔끔한 FAIL이 아니라 스위트 크래시**로 끝났다.
Sprint 80과 같은 형태라 같은 방식으로 고쳤다 ― 예외를 붙잡아 FAIL로 바꾸니
`"행 단위 except가 사라졌는가? 한 법원의 값 하나 때문에 그날 수집분을 전부 잃는다"`로
정확히 지목한다.

### 결과

```
config/courts.py              56% -> 100%
validator/validation_engine   52% -> 100%  (Sprint 83)
storage/database.py           86% ->  88%  (롤백 경로 커버)
```

`storage/database.py`에 남은 미커버는 `init_db()` 예외 경로와 **`query()` 함수**다.
후자는 36행짜리 레거시 조회 함수인데 **운영 호출부가 0곳**이다(유일한 호출부인
`test_db.py`는 `ALLOW_LIVE_CRAWL=1` 없이는 즉시 종료하는 실크롤 스크립트).
`renew()` / `get_active_subscription()`과 같은 부류로 기록만 하고 삭제하지 않았다.

### 품질 게이트

```
Python test_*.py   28/28 PASS
tsc 0 / eslint 0 / compileall 0
```

## 2026-08-13 Sprint 85 ― roadmap이 남긴 미검증 경로 4개를 전부 태웠다

Sprint 84가 남긴 "다음 후보" 4개는 모두 **평소에 실행되지 않는 경로**였다. 실행되지 않는
코드는 틀려도 조용하고, 틀렸다는 사실은 그 경로가 처음 필요해지는 날(=사고가 난 날) 드러난다.
이번 Sprint는 그 4개를 픽스처와 결정적 끼워넣기로 실제로 태웠다. **제품 결함은 1건도 없었고,
대신 문서화되지 않은 한계 3개와 내 검사·측정 코드의 결함 3개를 찾았다.**

### 1. 다운로드 완료 판정 (BUGS #84)

`wait_for_download()`는 `crawler/doc_crawler.py`에서 selenium을 타지 않는 마지막 미검증
함수였다. `time.sleep`을 대역으로 바꿔 호출마다 파일을 진행시키면 실제 시간을 쓰지 않고
폴링 루프를 그대로 밟을 수 있다.

핵심은 **"연속 2회 같은 크기"라는 규칙이 정말 필요한가**를 검사가 구별하게 만드는 것이었다.
경로만 비교하면 1회 규칙과 2회 규칙이 같은 파일을 돌려주므로 구별되지 않는다 ― **반환 시점의
크기**를 보고, 크기 대본을 "두 번 쉬었다 다시 자라는" 모양으로 짜야 한다. 한 번만 쉬는
대본에서는 "안정 카운터 리셋 제거" 변이가 살아남았다(실측 후 대본을 고쳤다).

변이 8종 중 7종 검출. 남은 1종(`.crdownload` 제외 줄 제거)은 **효과가 없음이 증명**된다 ―
바로 다음 줄의 `.pdf` 확장자 필터가 같은 것을 걸러내고, 어떤 파일명도 두 조건을 동시에
만족할 수 없다. 지우지 않고 사실만 주석에 남겼다(후보 조건이 확장자를 안 쓰게 바뀌면 그 줄이
유일한 방어가 된다).

### 2. Admin 409 경합 분기 (BUGS #85)

지금까지 근거는 확률적 스레드 재현(2스레드 3/4)과 소스 문자열 검사뿐이었다. 둘 다 "실제로
409를 주고 앞선 결과를 보존하는가"는 보지 못한다. 커넥션을 감싸 **`UPDATE` 직전에 다른
커넥션으로 상태를 확정**하니 확률이 사라졌다 ― sqlite3는 SELECT로 트랜잭션을 열지 않으므로
락 없이 끼어들 수 있고, 그게 TOCTOU 창의 실제 모습이다.

변이 3종 전부 검출. 조건부 WHERE를 지운 변이에서는 **발급된 등기부 URL이 덮이고 진 쪽의
실패 사유가 섞여 들어가는** 것까지 재현됐다 ― 가드가 무엇을 지키는지 검사가 직접 보여준다.
대조군(끼어들기 없으면 같은 요청이 200)을 함께 뒀다. 없으면 409가 끼어들기 때문인지
요청 자체가 잘못돼서인지 구별되지 않는다.

### 3. `init_db()` 옛 스키마 보완 (BUGS #82)

옛 스키마 DB를 픽스처로 만들어 ALTER 분기 4개를 태웠다. 옛 DDL을 복사해 두면 현재 DDL이
바뀔 때 같이 낡으므로, **살아 있는 상수에서 나중에 추가된 칼럼만 걷어내** 파생시켰다.

여기서 문서화되지 않은 한계가 확정됐다: `init_db()`는 **UNIQUE 제약을 고치지 못한다**.
옛 DB를 init_db()만으로 최신화하면 `document_queue`의 UNIQUE에 `item_no`이 빠진 채 남고,
enqueue가 `INSERT OR IGNORE`이므로 **같은 사건의 물건번호 2번이 조용히 버려진다**. migration
018이 반드시 필요하다는 순서를 검사로 고정했다.

### 4. 레거시 문서 플래그의 드리프트 실측 (BUGS #83)

`query()`의 호출 경로를 추적하다가(운영 호출부 0곳 재확인) 레거시 `auction.has_*`와 화면
테이블을 대조했다. 어긋난 행이 35건이고, **35건 전부 디스크 실물과 일치하는 쪽은
`document_status`였다**(플래그만 34건은 파일 없음, READY만 1건은 파일 있음).
`auction`↔`auction_item` 키 집합은 완전히 일치한다(1,876건, 양방향 차집합 0).

사용자 영향은 없다 ― `api/` 어디에서도 그 플래그를 읽지 않는다. 그 상태를 검사로 고정했다.
편의상 다시 읽기 시작하면 #50("파일이 있는데 수집중")이 그대로 되살아난다. 스키마에서 지우는
것은 승인 영역이라 하지 않았다.

### 5. 화면이 걸었다고 보여주는데 걸리지 않는 필터 (BUGS #81)

TODO 전수 탐색에서 시작해 실측으로 확인했다. `min_building_area` 등 5개 파라미터는 프론트가
보내고 백엔드가 조용히 버린다(FastAPI는 선언되지 않은 쿼리 파라미터를 무시한다) ― 결과 목록은
필터가 걸린 것처럼 보이지만 걸러지지 않은 목록이다. **사용자에게 잘못된 결과를 보여주는 유일한
발견**이지만, 구현에는 스키마 변경 + 크롤러 면적 추출 + 정규화 규칙(㎡/평, 전유면적 vs 대지권)이
필요해 승인 영역이다. 결정하지 않고 양방향 드리프트 가드만 설치했다(구현되면 검사가 실패해
프론트 TODO 정리를 강제한다 / 백엔드가 unknown 파라미터를 거부하게 바뀌면 검색이 죽는다는 것도
함께 고정했다).

### 내 검사·측정 코드의 결함 3건 (기록)

제품보다 내 코드에서 결함이 더 나왔다. 세 건 다 "통과가 거짓 안심이 되는" 종류다.

```
1. 변이 스크립트가 파일을 바이너리로 읽고 패턴에 \n을 써서, CRLF 파일(api/v1/admin.py)에서
   0곳 일치 -> 변이가 적용되지 않은 채 "SURVIVED"로 보였다.
   패턴 일치 수가 1이 아니면 즉시 표시하게 해 둔 덕에 드러났다.
2. 없는 칼럼을 sqlite3.Row로 읽어 IndexError로 테스트가 죽었다 -> 결함이 FAIL이 아니라
   크래시가 되어 집계에서 사라진다. 칼럼 부재를 <칼럼 없음>이라는 값으로 다루게 고쳤다.
3. init_db()가 예외로 죽는 변이도 같은 이유로 크래시였다 -> 호출을 감싸 FAIL로 만들었다.
   재실행하니 같은 변이가 8건의 FAIL로 나타난다.
```

### 실행 환경 함정 1건 (기록)

`test_schema_hygiene.py`의 "모든 .py가 파싱된다" 검사가 **한 번** FAIL했고 재현되지 않았다
(직후 3회 연속 PASS, `compileall` 0, 전수 ast 파싱 0건 실패). 저장소가 OneDrive 동기화
폴더 안에 있어, 방금 쓴 파일을 다른 프로세스가 읽는 순간과 겹치면 이런 일시적 읽기가 나온다.
제품 결함이 아니다 ― 다만 **파일을 고치는 명령과 테스트를 같은 블록에서 돌리지 않는다**는
기존 규칙(Sprint 82)이 여기에도 적용된다.

### 품질 게이트

```
Python test_*.py    28개 파일 / 24 PASS / 4 SKIPPED(설계상: 실크롤 3 + Beta Journey)
검사 총합           2,097 PASS / 0 FAIL   (데이터 의존 분기가 있어 회차마다 ±수 건)
compileall          0
변이 테스트         18종 시도 / 16종 검출 / 2종은 "효과 없음"이 증명됨(.crdownload, commit)
```

프론트엔드 소스는 **한 줄도 바꾸지 않았다**(`.ts`/`.tsx` 변경 0건 ― `SearchForm.tsx`는
읽기만 했다). 그래서 tsc / eslint / next build / 프론트 계약 테스트는 Sprint 84에서 확인한
상태 그대로다.

### 6. 커버리지로 다시 훑어 실패·방어 경로 6곳을 태웠다 (Sprint 85 후반)

위 4개를 끝낸 뒤 전체 스위트 커버리지를 다시 재고, 남은 미커버 구간을 우선순위대로 처리했다.
이번에 고른 기준은 "결함일 때 사용자가 무엇을 잃는가"다.

```
api/v1/documents.py     95% -> 100%  경로 탈출 차단 / NULL 경로 404      (BUGS #86)
api/v1/favorites.py     94% -> 100%  중복 아닌 실패를 감추지 않는다       (BUGS #87)
storage/checkpoint.py   91% -> 100%  저장 실패가 크롤을 멈추지 않는다     (BUGS #89)
storage/database.py     89% ->  90%  init_db 실패 / 상태 조회 방어        (BUGS #89)
                                     남은 미커버는 query() 한 함수뿐이다(25문장,
                                     운영 호출부 0곳 - 삭제는 승인 영역)
전체                    78% ->  79%
```

가장 값이 있었던 것은 **경로 탈출 검사에 실제 파일을 둔 것**이다. 파일이 없는 탈출만
검사하면 가드를 지워도 통과한다(둘 다 404다). 절대경로 주입으로 `DOCUMENT_ROOT`를 벗어난
자리에 `%PDF-1.4 QA-SECRET-...`을 두니, 가드를 지운 변이가 **그 내용을 그대로 응답에
실어 보냈다** ― 방어가 무엇을 막고 있는지 검사가 직접 보여준다.

READY의 의미도 함께 좁혔다(BUGS #88): 지금까지 "READY"는 **판정 파일(status.json)**이 있다는
뜻이었고, 사용자가 여는 것은 **status.html**이다. 둘이 갈라지면 "완료인데 뷰어는 404"가 된다.
실측으로 556행 전부 서빙 가능함을 확인하고 0건을 계약으로 고정했다.

### 7. 기존 테스트가 결함을 숨기던 자리 하나를 고쳤다

`test_api_regression.py` §3의 `client.get(...).status_code`는 서버가 예외를 던지면 스위트를
그 자리에서 죽였다. 변이 테스트에서 실제로 그렇게 나왔다 ― **FAIL 0건 + 크래시**, 즉 결함이
집계에서 사라진다. 호출을 감싸 예외를 `None`으로 바꿨다. 단언은 그대로 두었고(약화하지
않았다), `None`은 어떤 기대값과도 맞지 않으므로 검출력은 오히려 올라갔다.

### 8. 내 측정 코드의 네 번째 결함 ― 바이트코드 캐시

같은 파일을 **길이가 같게** 변이하면 `.pyc`가 재사용되어 **앞 변이의 결과가 다음 변이의
증거로 보고된다**(pyc 무효화는 소스의 mtime+크기로 판단한다). `_PRIMARY_EXT` 변이의 FAIL
메시지가 직전 변이의 값을 담고 있는 것을 보고 알아챘다. 변이 실행을 `-B`로 바꿨고, 앞서
SURVIVED로 판정한 2종도 `-B`로 다시 돌려 판정이 유효함을 확인했다(둘은 크기가 달라 캐시
영향이 없었다). 변이 테스트에서 **적용·평가 경로를 의심하지 않으면 통과가 거짓 안심이 된다** ―
이번 세션에서 네 번째로 같은 교훈을 얻었다.

### 최종 품질 게이트 (Sprint 85 종료)

```
Python test_*.py    28개 파일 / 24 PASS / 4 SKIPPED(설계상) / 0 FAIL
검사 총합           2,146 PASS / 0 FAIL      (Sprint 84 시작 시점 2,077 -> +69)
compileall          0
전체 커버리지        79%  (남은 미커버 대부분은 selenium 의존 crawler/*)
변이 테스트          36종 시도 / 34종 검출 / 2종은 "효과 없음"이 증명됨
프론트엔드           .ts/.tsx 변경 0건 ― tsc/eslint/build/계약 테스트는 Sprint 84 상태 유지
```

### 9. 돈 경로의 실패·멱등 분기 (Sprint 85 마무리, BUGS #90)

커버리지가 `api/v1/payments.py`에 남긴 미커버 중 Mock Provider로 도달 가능한 것을 모두
처리했다(92% -> 95%). 이 구간에서 얻은 것은 검사 30개보다 **판단 세 개**다.

**1) 돈 관련 멱등에서 위험한 쪽은 "거절하지 않는 것"이 아니다.** 전액 환불 뒤 같은 요청이
또 오면 이 저장소는 멱등 성공으로 응답한다(등기부·구독과 같은 규약). 처음엔 그것을 결함으로
의심했지만 규약이 먼저 있었다 — 진짜 위험은 **원장을 두 번 계상하는 것**이다. 그래서 응답
형태가 아니라 원장 합계·기록 수·감사 로그 수를 고정했다.

**2) 못 태우는 분기를 억지로 태우는 대신 방향을 바꿨다.** 조건부 UPDATE의 rowcount 검사를
결정적으로 태우려 했지만, `BEGIN IMMEDIATE`가 먼저 쓰기 락을 잡아 **같은 프로세스에서는
끼어들 수 없다**. 그 분기는 락 뒤의 이중 방어다. 그래서 "1차 방어선이 실제로 직렬화하는가"를
검사로 바꿨다 — 끼어든 쓰기가 `database is locked`로 막히는 것이 실행 증거다. `BEGIN
IMMEDIATE`를 지운 변이에서는 끼어들기가 성공하고 **그 다음에 rowcount 검사가 발동해 409**가
된다. 두 방어선이 층으로 쌓여 있다는 사실 자체가 검사로 드러난다.

**3) 통과하는 검사가 무엇을 통과했는지 확인해야 한다.** Webhook 분기 두 개는 통과했지만
**무시된 이유가 달랐다** — 매핑표에 없는 `event_type`을 써서 더 앞의 분기에서 걸렸고, 검사
대상에는 도달조차 못 했다. 커버리지가 그것을 드러냈다(그 줄이 그대로 미커버였다).
실제 `event_type`으로 고쳐 세 분기를 실제로 태웠다.

### 최종 상태 (Sprint 85 종료)

```
Python test_*.py    28개 파일 / 24 PASS / 4 SKIPPED(설계상) / 0 FAIL
검사 총합           2,186 PASS / 0 FAIL      (Sprint 84 종료 시점 2,077 -> +109)
compileall          0
전체 커버리지        81%   (api/v1/payments.py 92% -> 96%)
변이 테스트          43종 시도 / 41종 검출 / 2종은 "효과 없음"이 증명됨
프론트엔드           .ts/.tsx 변경 0건 ― tsc/eslint/build/계약 테스트는 Sprint 84 상태 유지
git                 커밋/푸시 없음(사용자 방침) ― 변경 41개 경로가 작업 트리에만 있다
```

---

## 2026-08-13 Sprint 85 ― parser 계층 (crawler/base_crawler.py 0% -> 30%)

크롤 파이프라인에서 **한 번도 실행된 적 없던 마지막 계층**이다. 이 파일에는 브라우저를
조작하는 코드와 **수집한 DOM을 데이터로 조립하는 코드**가 섞여 있는데, 후자는 브라우저
없이 검증할 수 있는데도 커버리지가 0%였다.

selenium이 설치돼 있어(4.47.0) 모듈 자체는 import된다. 그래서 **리팩터링 없이**
가짜 드라이버로 조립 로직만 검증했다.

### 경계를 흐리지 않았다

가짜 드라이버는 **XPath를 해석하지 않는다.** 미리 정해 둔 결과만 돌려준다.

```
검증한다      DOM에서 값을 꺼낸 뒤의 조립 규칙
              th/td 짝짓기, 중복 라벨, 빈 행 걸러내기, 셀 수 불일치, 예외 내성
검증하지 않는다 XPath가 실제 법원 페이지 DOM과 맞는지 (살아 있는 페이지가 필요)
```

XPath를 해석하는 척하면 "선택자가 맞다"고 착각하게 만드는 검사가 된다. 그래서 일부러
최소한만 흉내 냈다.

### 고정한 규칙 (26검사)

```
clean()              연속 공백/탭/줄바꿈 -> 하나, 앞뒤 제거
                     비단절 공백(NBSP)·전각 공백도 정규화된다
parse_basic_info()   th/td 순서 짝짓기, **중복 라벨은 첫 번째가 이긴다**
                     td가 모자라면 "-", 빈 키/빈 값은 넣지 않는다
                     ★ 중간에 예외가 나도 이미 모은 값은 지킨다
parse_section_table() td 없는 헤더 행 건너뛰기, 모든 셀이 빈 행 버리기
                     일부만 빈 행은 남긴다, 예외 시 앞서 모은 행 보존
parse_gamjung()      clean해서 반환, 못 찾으면 **빈 문자열**(None이 아니라)
```

"중복 라벨은 첫 번째가 이긴다"가 특히 중요하다 ― 법원 상세페이지는 요약표와 상세표에
같은 라벨을 반복해서 쓴다. 뒤가 이기면 요약값이 상세값을 조용히 덮어쓴다.

"예외가 나도 이미 모은 값은 지킨다"도 실제 시나리오다 ― 셀 텍스트를 읽다
StaleElementReference가 나는 일은 흔한데, 여기서 전부 버리면 그 물건은 **필수 필드 누락으로
FAIL** 처리된다.

`parse_gamjung()`이 빈 문자열을 돌려주는 것은 validator와 직접 이어진다. validator는
`if addr_sido and appraisal_sido`로 양쪽이 있을 때만 비교하므로 빈 요약이면 지역 대조를
건너뛴다 ― **모른다고 FAIL을 붙이지 않는 설계**다. 그 연결까지 한 검사로 확인했다.

### 변이 6종 중 5종 검출 ― 살아남은 1종의 정체

```
검출  중복 라벨을 나중 것이 이기게 / 빈 행도 남기게 / clean이 공백만 처리
      gamjung 실패 시 None / td 부족 시 빈 문자열
미검출 `if not cells: continue` 제거
```

미검출을 그냥 두지 않고 원인을 확인했다. `parse_section_table()`에는 행을 거르는 가드가
두 개인데, cells가 비면 texts도 빈 리스트가 되어 `any([])`가 False라 **두 번째 가드가 같은
행을 다시 걸러낸다.** 즉 첫 번째는 **출력에 영향이 없는 순수 중복**이고 리스트
컴프리헨션 한 번을 아끼는 미세 최적화다.

동작으로 구분할 수 없으므로 **억지 검사를 만들지 않았고 코드도 건드리지 않았다**.
대신 그 사실을 테스트 주석에 적어 다음 사람이 같은 변이를 넣고 "테스트가 약하다"고
오판하는 것을 막았다.

### 인코딩 가드가 또 한 번 작동했다

NBSP(U+00A0)를 소스 리터럴로 쓰자 `test_console_encoding.py`가 잡았다. 이번에는 그 문자가
**검사 대상 데이터**라 예외를 만드는 대신 `chr(0xA0)`로 런타임에 조립해 가드의 엄격함을
그대로 뒀다. 이유를 주석에 남겨 되돌리면 왜 실패하는지 알 수 있게 했다.

### 품질 게이트

```
Python test_*.py   29/29 PASS  (신규 test_crawler_parsing.py 포함)
tsc 0 / eslint 0 / compileall 0
crawler/base_crawler.py  0% -> 30%
```

---

## 2026-08-13 Sprint 86 ― 마이그레이션 러너의 실패/재실행 경로 (83% -> 97%)

`docs/CLAUDE.md`가 "safe to re-run"이라 안내하는 부트스트랩이고, **신규 clone에서 스키마를
만드는 유일한 경로**다. 그런데 두 분기가 한 번도 실행된 적이 없었다.

```
if applied: [SKIP] continue    재실행 시 이미 적용된 것을 건너뛴다(멱등성)
except:     [FAIL] raise       실패하면 기록하지 않고 예외를 올린다
```

두 번째가 특히 중요하다. 실패한 마이그레이션이 `migration_history`에 기록되면 재실행이
그것을 건너뛰어 **스키마가 영구히 깨진 채로 남는다.** 현재 구현은 INSERT 전에 raise하므로
기록되지 않는다 ― 그 순서를 11검사로 고정했다.

### 실험으로 확인한 부분 적용 위험

`conn.executescript()`는 실행 전에 **암묵적으로 커밋**한다. 직접 재현했다.

```
CREATE TABLE a (x INTEGER);
CREATE TABLE a (x INTEGER);      <- 두 번째에서 실패

executescript 예외: OperationalError table a already exists
실패 후 남은 테이블: ['a']        <- 앞 문장은 반영된 채 남는다
```

이력에는 기록되지 않으므로 재실행이 처음부터 다시 돌린다. 앞 문장에 `IF NOT EXISTS` 같은
가드가 없으면 **"already exists"로 영원히 완료되지 못한다.**

실제 18개 마이그레이션 중 가드 없는 문장을 포함한 것은 010·011·012·013·016·018이다
(ALTER/DROP/RENAME 패턴이라 SQLite에서 가드를 붙일 수 없는 경우가 섞여 있다).

**지금까지 발현된 적은 없다** ― 18개 전부 정상 적용됐고 `test_schema_hygiene.py` §3이
이력 완전성을 이미 검증한다. 그래서 **코드는 바꾸지 않았다**. 실행 모델을 바꾸는 것
(executescript 대신 문장 분할)은 부트스트랩 전체에 영향을 주고, SQL 안의 세미콜론 처리 때문에
새 결함을 만들 위험이 크다.

대신 그 성질을 **검사로 고정**했다 ― "실패해도 앞 문장은 남아 있다", "가드 없는 문장은
재실행에서도 실패한다". 019를 쓰는 사람이 이 전제를 알고 쓰게 하려는 것이고, 전제가 바뀌면
검사가 먼저 실패한다.

### 변이 2종 검출 ― 두 번째는 가드를 고친 뒤에야 제대로 잡혔다

```
실패를 삼킴        2건 실패 (예외 미전파 + 재실행에서도 실패해야 하는데 통과)
재실행 스킵 제거   처음엔 스위트 크래시 -> 가드 보강 후 5건 실패
```

두 번째가 크래시로 끝난 이유는 스킵이 사라지면 같은 filename을 다시 INSERT하려다
UNIQUE에 걸려 예외가 그대로 올라오기 때문이다. Sprint 80·84와 같은 형태라 같은 방식으로
고쳤다 ― 이제 `"이미 적용된 것을 건너뛰는 분기가 사라졌는가? 같은 filename 재INSERT로
UNIQUE에 걸린다: IntegrityError(...)"`로 정확히 지목한다.

**이 패턴이 이번 세션에서 네 번째다.** 가드를 만들 때 "실패하면 무엇이 보이는가"까지
확인하지 않으면, 정작 결함이 생겼을 때 원인이 아니라 스택트레이스만 남는다.

### 품질 게이트

```
Python test_*.py   29/29 PASS
tsc 0 / eslint 0 / compileall 0
storage/migrations/run_migrations.py  83% -> 97% (남은 1행은 __main__ 가드)
```

---

## 2026-08-13 Sprint 87 ― 감사 로그 직렬화의 두 분기 (88% -> 100%)

커버리지가 지목했다: `api/v1/audit.py:_dump()`가 **None으로도 문자열로도 호출된 적이
없었다.** 지금까지는 dict만 들어와 `json.dumps` 경로만 돌았다. `get_audit_logs`의
`admin_id` 필터도 미검증이었다.

셋 다 **조용히 틀릴 수 있는** 자리다. 감사 로그는 "누가 무엇을 바꿨는가"를 사후에
판단하는 유일한 근거라, 표기 하나가 틀리면 판단이 틀어진다.

```
_dump(None)이 "null" 문자열을 돌려주면   생성 이벤트의 before가 값이 있는 것처럼 보인다
                                        (컬럼 NULL과 문자열 "null"은 다르다)
_dump(str)이 다시 json.dumps하면         이중 인코딩돼 화면에 따옴표가 남는다
admin_id 필터가 빗나가면                 "이 관리자가 무엇을 했는가"를 못 찾는다
```

9검사를 추가했다. 함수 단위뿐 아니라 **DB까지** 확인한다 ― `before=None`으로 기록하면
컬럼이 실제로 NULL인지, `after="문자열"`이 따옴표 없이 그대로 저장되는지.

### 변이 4종 전부 검출 ― 예측한 실패 형태가 그대로 나왔다

```
None도 json.dumps    _dump(None) -> 'null'          / before 컬럼도 'null'
문자열도 재인코딩     '"이미 문자열"'                  / after 컬럼도 따옴표 포함
한글 이스케이프       {"court": "서울"}      (ensure_ascii=False 제거)
admin_id 필터 무시    1건이어야 할 결과가 12건
```

마지막이 특히 위험하다 ― 필터가 무시되면 **다른 관리자의 기록이 섞여 나오는데**
화면에는 정상 응답으로 보인다. 조회 결과를 근거로 책임을 판단하는 자리라 조용한 오답이
그대로 결론이 된다.

### 품질 게이트

```
Python test_*.py   29/29 PASS
tsc 0 / eslint 0
api/v1/audit.py    88% -> 100%
```

---

## 2026-08-13 Sprint 88 ― 인증의 fail-closed 가드와 선택적 인증 폴백

커버리지가 세 곳을 지목했다. 셋 다 **보안이나 화면 가용성에 직결**되는데 한 번도 실행된
적이 없었다.

### 1. 검증 수단이 없을 때 통과시키지 않는가 (auth.py)

```
HS256 토큰인데 SUPABASE_JWT_SECRET이 비어 있음  -> JWTError로 거부
대칭/비대칭 어느 쪽 수단도 없음                  -> HTTPException 500
```

여기서 조용히 통과시키면 **서명 검증 없이 아무 토큰이나 받는 상태**가 된다.
두 번째를 401이 아니라 500으로 두는 것도 의도다 ― 401은 "토큰이 잘못됐다"로 읽혀
서버 설정 문제가 사용자 탓으로 보인다. 시크릿을 되돌리면 같은 토큰이 통과하는 것까지
확인해 **거부가 토큰 탓이 아님**을 못박았다.

`except JOSEError` 분기(134-135)는 남겨 뒀다 ― malformed 토큰이 전부 `JWTError`로
잡혀 **도달할 수 없는 방어 코드**임을 실험으로 확인했다. 억지로 도달시키는 검사를 만들지
않았다.

### 2. 토큰이 잘못돼도 상세는 비로그인으로 보인다 (item.py 92% -> 100%)

상세 조회는 **선택적 인증**이다. 토큰이 있으면 최근조회를 기록하고, 없거나 잘못됐으면
비로그인으로 그냥 보여준다. 이 분기가 없으면 **세션이 만료된 사용자가 물건 상세를 열 때
화면이 깨진다.** 만료는 일상이다.

```
깨진 토큰 / 빈 문자열 / 서명이 틀린 토큰   전부 200, 본문 정상
잘못된 토큰의 응답 == 비로그인 응답        (다른 키 0개)
is_favorited가 켜지지 않는다               개인화가 새지 않는다
최근조회를 남기지 않는다                   검증되지 않은 user_id로 기록하지 않는다
```

마지막이 보안 쪽이다. 검증 실패한 토큰의 `sub`를 그대로 쓰면 **아무 user_id로나 남의
최근조회를 오염**시킬 수 있다. 그 변이를 넣으니 6건이 실패했다.

### 3. 실패 메시지를 두 번 고쳤다

**(a) 거대 dict 출력** ― "잘못된 토큰의 응답이 비로그인과 같다"를 `check()`로 전체 dict
비교하게 했더니, 통과할 때조차 본문 두 개가 통째로 찍혔다. 실패하면 읽을 수 없다.
같은지 여부는 그대로 단언하되 **다른 키만** 보여주도록 바꿨다.

**(b) 크래시 대신 진단** ― `except JWTError`를 제거하는 변이가 또 스위트 크래시로
끝났다(이번 세션 다섯 번째). 붙잡아 FAIL로 바꾸니
`"선택적 인증의 except JWTError가 사라졌는가? 세션 만료만으로 상세 화면이 깨진다"`로
지목한다.

### 품질 게이트

```
Python test_*.py   29/29 PASS
tsc 0 / eslint 0 / compileall 0
api/v1/item.py     92% -> 100%
api/auth.py        96% ->  98%  (남은 2행은 도달 불가 방어 코드)
```

---

## 2026-08-13 Sprint 89 ― 결제 로그 마스킹의 리스트 분기 (90% -> 100%)

KG이니시스 실연동은 SKIP이지만, **결제 로그 무결성과 webhook 계약**은 계속 개발 대상이다.
커버리지가 `api/v1/payment_logs.py`의 7행을 지목했고 그중 하나가 보안 경로였다.

### 1. 리스트 안쪽이 마스킹되는가 (70행)

기존 검사는 **dict 중첩만** 봤다. PG Webhook payload는 배열을 흔히 포함한다
(`{"items":[{...}]}`, 승인 내역 목록). 리스트 재귀가 끊기면 **배열 안의 카드번호가 평문
그대로** `payment_webhooks.raw_payload`에 저장되고, 그 로그는 운영자가 폭넓게 열람한다.

변이로 리스트 분기를 제거하자 실패 메시지에 `4111111111111111`이 그대로 찍혔다.
**dict만 막고 리스트를 놓치면 마스킹이 있다는 사실 자체가 더 위험하다** ― 안전하다고
믿게 되기 때문이다.

함께 고정한 것: 최상위가 리스트인 경우, 중첩 리스트, 키 표기 변형(`card-no` / `CARD_NO`),
스칼라 통과, 그리고 **원본을 변형하지 않는다**(변형하면 PG로 되돌려보내는 payload까지
오염돼 서명이 깨진다).

### 2. 모르는 값을 조용히 받지 않는가 (103·105·194·235·237행)

`log_payment_event` / `mark_webhook_processed`의 enum 검증과,
`webhook_reprocess_block_reason`의 FAILED·미지원 상태 분기가 전부 미커버였다.

마지막이 중요하다 ― 모르는 상태를 **기본 허용**으로 두면 운영자가 재처리해서는 안 되는
Webhook을 재처리하게 된다. 변이로 확인했다.

### 3. 커버리지가 "잘못된 이유로 통과하던 검사"를 드러냈다

`log_payment_event`의 status 가드를 검증하려고 `event_type="PAYMENT_CONFIRMED"`를 썼는데,
**그 값이 VALID_EVENT_TYPES에 없어서 앞선 event_type 가드에서 걸렸다.**
ValueError는 났으니 검사는 통과했지만 **의도한 분기는 한 번도 실행되지 않았다.**

커버리지가 105행을 미커버로 남겨 그 사실이 드러났다. `event_type="CONFIRM"`으로 고치자
100%가 됐고, **그제서야 status 가드 제거 변이가 검출됐다**(그 전에는 통과했을 것이다).

"예외가 났다"만 단언하면 이런 가짜 통과를 구분할 수 없다. 이유를 주석에 남겼다.

### 품질 게이트

```
Python test_*.py   29/29 PASS
tsc 0 / eslint 0
api/v1/payment_logs.py  90% -> 100%
변이 6종 전부 검출(리스트 분기 / enum 가드 3종 / 기본 허용 / 원본 변형)
```

---

## 2026-08-13 Sprint 90 ― address_detail: 검색 파라미터 하나가 통째로 미검증이었다

`address_detail`은 검색 화면의 **주소 상세** 입력이다. `intent.analyzer`가 무엇을 적었는지
해석하고 `build_address_condition()`이 그에 맞는 SQL을 만든다. 그런데 이 파라미터는
**API 레벨 검사가 0건**이었다.

의도별로 조건이 완전히 다르다.

```
"서울"              -> SIDO          sido = ?
"강남구"             -> SIGUNGU       sigungu LIKE ?
"역삼동"             -> DONG          dong LIKE ?
"19"               -> LOT_NUMBER    lot_number = ?      <- 미커버였다
"서울 강남구 역삼동"   -> FULL_ADDRESS  세 조건 AND
"서울 아파트"         -> MIXED         지역어 + 잔여어      <- sido 가지가 미커버였다
```

**200만 보고 통과시키지 않았다.** 조건이 통째로 무시돼도 200은 나오므로, 반환된 행이 실제로
그 조건에 맞는지까지 본다(Sprint 49가 정렬/페이지에서 세운 원칙과 같다). 기대 건수는
단언하지 않고 DB에서 실제 물건을 뽑아 쓰므로 데이터가 바뀌어도 유효하다.

### 변이가 처음엔 살아남았다 ― 검사가 데이터에 의존하고 있었다

지번 조건을 `=`에서 `LIKE`로 바꾸는 변이를 넣었는데 **그대로 통과했다.** 표본으로 고른
지번이 다른 어떤 지번의 부분문자열도 아니어서 결과가 같았기 때문이다.

DB를 뒤져 보니 부분문자열 관계인 지번이 실제로 있었다.

```
'19' ⊂ '342-19' / '589-19' / '19-23' / '14-19' / '194' / '619-2' / '419-130' / '190-15'
```

**상위 문자열이 존재하는 지번을 DB에서 직접 골라 쓰도록** 검사를 고쳤다. 이제 같은 변이가
`[(47, '342-19'), (61, '589-19'), ...]`를 보여주며 실패한다. 지번 검색이 LIKE가 되면
"19"를 찾는 사용자에게 "342-19"가 섞여 나온다.

지번을 바꾸면서 "그 물건이 결과에 있는가"의 기준 id도 함께 바꿔야 했다 ― 처음엔 옛 id를
그대로 두어 정상 실행이 깨졌다.

### 검색의 선택적 인증도 함께 (BUGS #27이 살았던 자리)

`search.py`에도 item.py와 같은 `except JWTError` 폴백이 있고 역시 미커버였다.
여기는 **조용한 오답**의 전례가 있다 ― ES256 전환 후 HS256만 검증하던 시절
로그인 사용자의 하트가 전부 빈 하트로 내려갔다(예외가 아니라 결과만 틀렸다).
그래서 200뿐 아니라 **is_favorited가 켜지지 않는지**까지 본다.

### 품질 게이트

```
Python test_*.py   29/29 PASS
tsc 0 / eslint 0
api/v1/search.py   95% -> 96% (남은 6행은 DB 장애 시 500 핸들러 2곳)
변이 4종 검출: 지번 LIKE화 / SIDO LIKE화 / MIXED sido 무시 / FULL_ADDRESS dong 무시
```

---

## 2026-08-13 Sprint 91 ― Admin 목록 필터가 실제로 걸리는가 (93% -> 96%)

Sprint 74가 **잘못된 필터 값**을 다뤘다면, 이번은 **필터가 실제로 SQL에 붙는가**다.
둘은 다른 문제다 ― 값 검증을 통과해도 조건이 안 붙으면 **전체가 그대로 나온다.**
200이고 목록도 그럴듯해서 운영자는 필터가 먹었다고 믿는다.

커버리지가 지목한 미커버 필터를 전부 채웠다.

```
/admin/payments?user_id= / ?payment_type=
/admin/payments/webhooks?payment_id=
/admin/registry-requests?item_id= / ?case_no=
```

**구분 가능한 픽스처**를 만들어 검증했다 ― 두 사용자 x 두 결제유형. 한 종류만 있으면
필터가 무시돼도 결과가 같아 검사가 구분력을 잃는다. 두 필터를 함께 걸었을 때 교집합이
비는 것까지 확인해, 하나만 먹는 경우도 잡는다.

### 관리자 키 미설정 가드 (104행)

두 키가 모두 없으면 Admin API 자체가 500이다. 여기서 통과시키면 **키 없이 관리자 API가
열린다.** 401/403이 아니라 500인 것도 의도다 ― 키를 안 준 것이 아니라 서버가 설정되지
않은 것이므로, 사용자 탓처럼 보이는 응답을 주면 원인을 못 찾는다.
**500 응답에 키 값이 실리지 않는 것**도 함께 확인했다.

### 변이가 두 번 살아남았고, 두 번째는 진짜 발견이었다

**첫 번째** ― `user_id` 필터 변이가 SKIP됐다. 같은 코드 패턴이 payments와
subscriptions 두 곳에 있어 자동 치환이 대상을 특정하지 못했다. 함수 범위를 지정해 다시
시험하니 4건 실패로 검출됐다.

**두 번째** ― `if req.status not in ("PROCESSING","COMPLETED","FAILED")` 가드를
제거해도 **모든 검사가 통과했다.** 처음엔 "NOT_A_STATUS"만 보냈는데 그 값은 하류의
전이 검사도 어차피 막는다. `PENDING`/`PAYMENT_REQUIRED`로 바꿔도 마찬가지였다 ―
전이표가 `PENDING->{FAILED,PROCESSING}`, `PROCESSING->{COMPLETED,FAILED}`뿐이라
**그 가드가 막는 값은 전부 전이 검사도 막는다.**

그래서 "중복 가드인가?"를 확인했더니 아니었다. 두 검사는 **순서**가 다르다.

```
가드      DB 조회 **이전**
전이 검사  DB 조회 **이후**

없는 신청 + 잘못된 상태값
  가드 있음 -> 400 "허용되지 않는 상태 값입니다: NOT_A_STATUS"
  가드 없음 -> 404 "신청을 찾을 수 없습니다"
```

운영자가 상태값을 오타냈을 때 "신청이 없다"고 답하면 **엉뚱한 곳을 찾게 된다.**
이 순서가 곧 진단 품질이라, 그 지점을 검사로 고정하니 변이가 검출됐다.

Sprint 85의 `parse_section_table` 중복 가드와는 결론이 갈렸다 ― 그때는 정말 출력에
영향이 없어 검사를 만들지 않았고, 이번은 **관찰 가능한 차이가 있어** 고정했다.
"변이가 살아남았다"에서 멈추지 않고 왜인지 확인해야 둘을 구분할 수 있다.

### 품질 게이트

```
Python test_*.py   29/29 PASS
tsc 0 / eslint 0
api/v1/admin.py    93% -> 96%
남은 14행은 전부 `except Exception: rollback; raise` 형태의 방어 핸들러 5곳
변이 6종 검출(키 가드 / user_id / payment_type / webhook payment_id / item_id / case_no / 상태값 순서)
```

---

## 2026-08-13 Sprint 92 ― 남은 방어 경로 정리와 그 경계

`subscriptions.py` / `registry.py` / `search_presets.py`의 미커버 분기를 전수 확인하고,
**테스트할 가치가 있는 것과 없는 것을 갈랐다.**

### 채운 것 ― 등기부 다운로드의 doc_url 방어

`registry.py`의 주석은 "COMPLETED인데 doc_url이 없는 경우는 정상 경로로는 발생하지 않지만
방어적으로 처리한다"고 적어 두었고, 실제로 커버리지 0이었다.

API로는 만들 수 없지만(admin.py가 COMPLETED 전이에 doc_url을 필수로 받는다),
**직접 DB를 만진 복구 작업이나 과거 데이터**로는 생길 수 있다. 그때 500이나 경로 오류가
아니라 읽을 수 있는 실패여야 한다.

변이로 가드를 제거하니 예상대로 `os.path.join(root, None)`이 **TypeError로 터졌다** ―
500조차 아니라 예외가 그대로 새어 나온다. 그것이 이 가드가 막는 사고다.
(여섯 번째로 "크래시 대신 진단" 보강을 했다)

`REGISTRY_NOT_COMPLETED`가 아니라 `REGISTRY_DOCUMENT_NOT_FOUND`로 막혔는지까지 본다 ―
같은 파일의 기존 주석이 남긴 교훈이다. **어느 가드가 막았는지 고정해야 가드 제거가 검출된다.**

### 남긴 것과 그 이유

```
registry.py 246-248      except Exception: rollback; raise      (일반 방어 핸들러)
search_presets.py 58-60  except: ROLLBACK; raise                (동일)
subscriptions.py 83-86   자동 만료 전이가 규칙에 막힘 경고        (도달 불가 - 아래)
subscriptions.py 213-214 ConcurrentStatusChange                 (다른 파일이 이미 검증)
registry.py 288          신청 없음 404                           (소유권 검사로 이미 도달)
```

`subscriptions.py:83-86`은 `resolve_expected_status()`가 만드는 전이(ACTIVE->GRACE_PERIOD->
EXPIRED)가 전부 허용 전이라 **정상 입력으로는 도달할 수 없다.** 억지로 도달시키려면
상태머신 자체를 깨야 하는데, 그러면 검증 대상이 아니라 변이를 검증하는 셈이 된다.

`213-214`는 `test_subscription_policy.py`가 이미 실스레드로 다룬다 ― 중복 검사를
만들지 않았다(Sprint 83에서 정리한 것과 같은 이유).

일반 `except: rollback; raise`는 5곳에 같은 형태로 있고, 각각을 도달시키려면 DB 계층에
장애를 주입해야 한다. **테스트가 검증하는 것이 제품이 아니라 주입 장치가 되는 지점**이라
남겨 두고 이유를 기록했다.

### 품질 게이트

```
Python test_*.py   29/29 PASS
tsc 0 / eslint 0
api/v1/registry.py  96% -> 97%
```

---

## 2026-08-13 Sprint 93 ― 등기부 다운로드 매트릭스 완성 + 상세 조회 응답 계약

Sprint 92에서 시작한 다운로드 방어 매트릭스를 끝까지 채우며 **두 가지 공백**을 찾았다.

### 1. 404만 검증되고 200은 한 번도 실행된 적이 없었다

커버리지가 `get_registry_request()`의 `return success(...)`를 미커버로 지목했다.
`GET /registry-requests/{id}`는 **타인 접근 404만** 검증돼 있었고, **본인 조회 200은
한 번도 실행된 적이 없었다.**

즉 이 엔드포인트가 실제로 무엇을 돌려주는지 아무도 확인하지 않았다. 응답에서 키가 하나
빠지거나 이름이 바뀌어도 검사는 전부 통과한다 ― 프런트가 읽는 값인데도 그렇다.

8개 필드의 존재를 고정하고(늘어나는 것은 허용, 사라지면 실패),
**목록과 상세가 같은 신청에 대해 같은 상태를 말하는지**까지 확인했다.
두 경로가 갈라지면 화면마다 다른 상태가 보인다.

변이 검증: 응답에서 `status`를 빼자 즉시 실패했고, 소유권 조건(`AND rr.user_id=?`)을
제거하자 **타인의 신청이 200으로 열렸다.**

### 2. 다운로드의 인증 경계가 비어 있었다

§8의 보호 라우트 검사는 **기본 경로만** 훑는다(`/api/v1/registry-requests`).
다운로드는 그 하위 경로라 목록에 걸리지 않아, **"토큰 없이 파일을 받을 수 있는가"가
검증된 적이 없었다.** 파일을 내려주는 엔드포인트인데 그랬다.

```
토큰 없음                401
잘못된 토큰               401
Bearer 스킴 없는 헤더      401
없는 신청 + 소유자 토큰     404 (존재 여부를 노출하지 않는다)
음수 request_id           404
```

세 인증 실패가 **같은 401로 수렴**하는 것이 맞다 ― 어느 쪽이든 "인증되지 않았다"이고,
구분해서 알려주면 탐색 단서가 된다. 처음엔 스킴 없는 헤더를 403으로 예상했는데
실제로는 401이었고, **기대값을 실제 동작에 맞췄다**(약화가 아니라 오예측 정정).

변이로 다운로드의 `Depends(get_current_user)`를 제거하자 3건이 실패했다 ―
**인증 없이 파일이 내려가는 상태**를 정확히 잡는다.

### 매트릭스 최종 상태

```
COMPLETED + 정상 doc_url      200 + 본문 일치        (기존)
COMPLETED + doc_url 없음       REGISTRY_DOCUMENT_NOT_FOUND  (Sprint 92)
COMPLETED + traversal 경로     404                   (기존)
파일 없음                      404                   (기존, 강제 다운로드 경로)
상태가 COMPLETED 아님          REGISTRY_NOT_COMPLETED (기존)
다른 사용자                     404                   (기존)
인증 없음 / 잘못된 토큰 / 스킴 없음  401                (Sprint 93)
없는 id / 음수 id              404                   (Sprint 93)
```

### 품질 게이트

```
Python test_*.py   29/29 PASS
tsc 0 / eslint 0
api/v1/registry.py  97% (남은 3행은 except: rollback; raise 방어 핸들러)
변이 3종 전부 검출(소유권 조건 / 응답 필드 / 다운로드 인증)
```

---

## 2026-08-13 Sprint 94 ― 결제: 손상된 payload와 환불 소유권 필터

KG이니시스 실연동은 SKIP이지만 **결제 실패 처리와 권한 검증**은 계속 개발 대상이다.
커버리지가 지목한 두 곳을 채웠다.

### 1. 저장된 payload가 손상됐을 때 (767행)

`raw_payload`는 수신 당시 그대로 저장한 텍스트다. 디스크 문제, 과거 데이터, 수동 복구
과정에서 잘리거나 JSON이 아닌 값이 들어갈 수 있다. 그때 운영자가 재처리 버튼을 누르면
**500이 아니라 읽을 수 있는 400**이어야 한다 ― 500이면 서버 장애로 오해하고 엉뚱한 곳을 본다.

세 형태를 넣어 확인했다.

```
잘린 JSON          '{"event_id": "x", "amo'
JSON이 아님         'not json at all'
객체가 아닌 JSON     '[1, 2, 3]'   -> 셋 다 400 + 사유에 "payload"
```

변이로 `except (TypeError, ValueError)`에서 ValueError를 빼자 **JSONDecodeError가 그대로
새어 나왔다**(3건 실패). 가드가 막는 것이 정확히 그 사고다.

### 2. 환불의 소유권 필터 (497-498행) ― Sprint 72가 기록한 잠재 IDOR 함정

`refund_payment(user_id=None)`은 기본값이 **"소유권을 확인하지 않음"**이고, 지금 유일한
호출부가 super-admin이라 현재 IDOR는 없다. 그래서 **소유권 분기 자체가 한 번도 실행된 적이
없었다.**

위험은 나중이다. 누군가 사용자용 환불 경로를 만들면서 `user_id=`를 빠뜨리면
**아무나 남의 결제를 환불할 수 있다.** 기본값이 안전하지 않은 쪽이라 더 그렇다.

세 갈래를 전부 고정했다.

```
타인 user_id   RefundError(404)  - 권한 오류가 아니라 404(존재를 노출하지 않는다)
               + 상태가 바뀌지 않는다
본인 user_id   정상 환불, 잔여 전액
user_id 없음   정상 환불 (현재 Admin 경로의 동작)
```

변이로 필터를 무시하게 하자 **"남의 결제를 환불할 수 있다"**로 실패했다.
이제 사용자용 환불을 배선하는 사람이 이 분기를 믿고 쓸 수 있다.

### 작업 중 정정

`RefundResult`의 속성명을 `payment`로 잘못 짐작했다(실제 `payment_row`).
테스트가 AttributeError로 죽어 바로 드러났고 정정했다 ― 실제 구조를 확인하지 않고
이름을 추측한 것이 원인이다.

### 품질 게이트

```
Python test_*.py   29/29 PASS
tsc 0 / eslint 0
payments.py: 497-498(환불 소유권) · 767(payload 파싱) 미커버 해소
변이 2종 검출(소유권 필터 무시 / payload 파싱 가드 제거)
```

---

## 2026-08-13 Sprint 95 ― registry lifecycle: DB와 파일이 어긋나는 지점 (BUGS #93)

Sprint 93~94가 다운로드(읽기) 매트릭스를 채웠다. 이번에는 요청받은 대로 **lifecycle 전체를
거슬러 올라가** DB 상태와 실제 파일이 어긋날 수 있는 지점을 찾았다.

```
신청 생성 -> 상태 변경 -> (운영자가 파일 배치) -> COMPLETED + doc_url -> 다운로드
                                                   ↑
                                          여기에 검사가 없었다
```

읽기 쪽은 방어가 촘촘한데(존재 검사·경로 탐색·소유권·상태) **쓰기 쪽에는 파일 검사가
아예 없었다.** `doc_url`이 비어 있지 않기만 하면 COMPLETED가 됐다.

### 재현

```
Admin PATCH status=COMPLETED, doc_url="does-not-exist.pdf"  -> 200 성공
사용자 상세 화면   "발급 완료"
사용자 다운로드    404
```

#50/#65와 같은 부류지만 **더 나쁘다.** 크롤러 경로는 재시도로 스스로 회복하는데
이쪽은 **자가 복구가 없다.** 게다가 등기부는 유료 서비스라, 사용자는 돈을 내고
"발급 완료"를 본 뒤 받지 못한다.

### 수정

COMPLETED 전이 시 실재하는 파일인지 확인한다. 검사 방식을 다운로드 경로와 **똑같이**
맞췄다 ― 두 곳이 다른 기준을 쓰면 같은 불일치가 다시 생긴다.
덤으로 경로 탐색을 **쓰기 시점에도** 막는다(예전에는 읽기 시점에만).

### 기존 테스트가 결함을 정상으로 굳혀 두고 있었다

수정을 넣자 기존 검사가 깨졌다. `doc_url="qa-regression-not-a-real-file.pdf"`로
**전이 성공을 기대**하고 있었고, 바로 아래 줄에는 "COMPLETED이지만 실제 파일이 없으면
거짓 성공을 반환하지 않아야 한다"가 있었다. **파일이 없다는 것을 알면서 읽기 쪽만 막고
쓰기 쪽은 통과를 기대**한 셈이다.

실제 파일을 두고 연결하도록 고치고, "COMPLETED인데 파일 없음"은 **레거시 상태 방어**로
옮겼다(과거 데이터·수동 복구로는 여전히 생길 수 있으므로 읽기 방어는 그대로 필요하다).

### 변이에서 드러난 두 번째 위험

경로 탐색 검사 제거가 **처음엔 검출되지 않았다.** `../../../etc/passwd`가 이 환경에 없는
파일이라 "파일 없음" 검사에도 걸렸기 때문이다.

`registry_documents/`의 부모는 저장소 루트이고 거기에 `auction.db`가 실재한다.
**실재하는** 바깥 파일로 바꾸자 검출됐다 ― 그 검사가 없으면 운영자가 DB 파일을 연결할 수
있고 **사용자가 DB 전체를 내려받는다.**

"파일이 없어서 막힌 것"과 "경로가 밖이라 막힌 것"은 다른 방어인데, 존재하지 않는 경로로는
그 둘을 구분할 수 없다.

### 픽스처 누수도 함께 고침

변이 실행이 중간에 실패하면 `registry_documents/`에 QA 파일이 남았다(실제로 3개 남아 있었다).
남은 픽스처는 다음 실행의 "파일 없음" 전제를 오염시킨다 ― try/finally로 반드시 지우게 했다.

### 품질 게이트

```
Python test_*.py   29/29 PASS
tsc 0 / eslint 0 / compileall 0
변이 3종 전부 검출(파일 존재 / 경로 탐색 / 검증 호출)
registry_documents/ 잔여 픽스처 0개
```

---

## 2026-08-13 Sprint 96 ― 같은 패턴을 크롤 문서 경로에서 찾다 (결과: 상류가 막고 있었다)

Sprint 95의 결함을 **개별 버그가 아니라 패턴**으로 놓고 물었다.

> "DB 상태는 성공인데 실제 리소스는 실패" ― 다른 곳에도 있는가?

크롤 문서 경로가 구조상 가장 닮아 있었다.

```
wait_for_download()   다운로드 폴더에서 완성된 .pdf를 고른다
collect_spec()        그 파일을 문서 보관 경로로 옮긴다 -> result["success"] = True
mark_queue_done()     document_status='READY', auction.has_*_pdf=1
```

`mark_queue_done()`은 **파일이 실재하는지 확인하지 않는다.** #93과 판박이로 보였다.

### 그런데 도달 가능한 결함이 아니었다

상류를 거슬러 올라가니 두 겹이 막고 있었다.

```
collect_spec()        try:/finally: 뿐이고 except가 없다
                      -> shutil.move 실패는 그대로 전파된다
doc_worker            그 예외를 받아 mark_queue_failed()를 호출한다
```

즉 "옮기기가 실패했는데 success=True"가 될 길이 없다. 등기부와 달리 **운영자가 임의의
문자열을 넣는 입구가 없고**, 경로는 언제나 `wait_for_download()`가 실제로 본 파일이다.

**결함을 만들어 내지 않았다.** `mark_queue_done()`에 존재 검사를 덧붙이는 것은 지금
도달할 수 없는 상태를 막는 코드이고, 대신 그것을 지켜 주는 진짜 조건을 검증하는 편이 낫다.

### "테스트 0건"이라고 적었는데, 틀렸다

`mark_queue_done()`이 안전한 이유는 **오로지 `wait_for_download()`가 불완전한 파일을
돌려주지 않기 때문**이다. 그 함수에 검사가 없다고 판단해 `test_crawler_parsing.py`에
9개를 새로 넣었다.

**그 판단이 틀렸다.** `test_doc_storage_atomicity.py`에 §8~§9로 이미 있었다
(Sprint 85 신설). 게다가 기존 것이 더 낫다 ― "잠깐 멈췄다 다시 자라는" 경우에서
경로가 아니라 **반환 시점의 파일 크기**를 보고, 안정 카운터를 리셋하지 않는 변이까지
잡도록 크기 대본을 짜 두었다.

### 그래서 새로 쓴 것을 지우고, 정말 새로운 하나만 옮겼다

두 곳에 같은 검사를 두면 한쪽만 고쳐지고 다른 쪽이 낡는다. 변이로 두 파일의 탐지력을
직접 비교해 무엇이 겹치고 무엇이 새것인지 갈랐다.

```
안정성 1회로 완화     기존 잡음   신규 잡음    -> 중복
crdownload 제외 삭제  기존 놓침   신규 놓침    -> 둘 다 증명된 중복 방어(아래)
타임아웃 제거         기존 정지   신규 잡음    -> 신규만 잡는다
```

`test_crawler_parsing.py`의 §5(9개 검사)를 통째로 지우고, **폴링 상한**만
`test_doc_storage_atomicity.py`로 옮겼다. 이제 `wait_for_download`의 집은 한 곳이다.

### 무한 루프 변이는 실패가 아니라 정지였다

`while elapsed < timeout:`을 `while True:`로 바꾸자 스위트가 **멈췄다**(가짜 sleep은
실제 시간을 쓰지 않으니 루프가 끝날 이유가 없다). 정지는 원인을 가리키지 못하고
스위트 전체를 먹는다.

기존 §8은 `time.sleep` 대역을 일곱 군데에서 따로 갈아 끼우고 있었다. 그것을 **하나로
모으고**(`set_sleep`) 총 폴링 횟수를 세게 했다. 상한은 60 ― 이 검사가 쓰는 가장 긴
timeout이 20이라 정상 사용을 절대 막지 않는다.

```
전:  타임아웃 제거 -> 45초 후 하위 프로세스 강제 종료 (FAIL 0건)
후:  타임아웃 제거 -> [FAIL] wait_for_download의 폴링이 끝난다 -> 폴링 61회
```

**변이 실행기에도 같은 교훈을 적용했다** ― 하위 프로세스에 타임아웃을 주고 원본 복구를
`finally`에 둔다. 이번에 실제로 `doc_crawler.py`가 변이가 걸린 채 남는 일이 있었다.

### 중복 방어 하나를 확인만 하고 두었다

`.crdownload` 제외를 지우는 변이는 **살아남았다.** Chrome의 임시 파일 이름이
`문서.pdf.crdownload`라서 바로 다음 줄의 `.endswith(".pdf")`가 이미 걸러내기 때문이다
(`parse_section_table`의 `if not cells`와 같은 부류).

동작으로 구분할 수 없으므로 억지 검사를 만들지 않았고 코드도 지우지 않았다 ― 의도를
드러내는 무해한 방어다. 검사는 "어느 줄이 거르는가"가 아니라 **"받는 중인 파일은 완료가
아니다"라는 동작**을 고정한다.

### 품질 게이트

```
Python test_*.py   29/29 PASS
tsc 0 / eslint 0 / compileall 0
node --test tests/format.test.mjs  13/13 PASS
변이 4종 검출(타임아웃 제거/100배 · 0바이트 · 안정성 1회) + 증명된 중복 1종
BOM 변동 0 / 픽스처 잔여 0
```

---

## 2026-08-13 Sprint 96 (이어서) ― 같은 패턴을 결제에서 찾다 (BUGS #94, 여기엔 있었다)

크롤 경로에서 헛물을 켠 뒤, 같은 질문을 돈 경로에 던졌다. **여기엔 있었다.**

### 실측 ― 돈은 돌려주고 서비스는 계속 준다

```
BASIC 월 구독 결제     12,900원   payment=SUCCESS   subscription=ACTIVE
SUPER_ADMIN 전액 환불  12,900원   payment=REFUNDED
그 직후                           subscription=ACTIVE  만료일 그대로
                                  GET /subscriptions/me -> "구독 중"
```

`refund_payment()`는 `payments` 행만 바꾸고 `subscriptions`는 건드리지 않는다.
webhook 경로도 마찬가지다. **#93의 거울상이다** ― #93은 "돈 받고 물건 안 준다",
이쪽은 "돈 돌려주고 물건 계속 준다".

### 고치려는 순간 더 근본적인 것이 나왔다

**대상을 특정할 수 없었다.** 결제와 구독을 잇는 열쇠가 아예 없다.

```
registry_requests   payment_id 있음      결제 <-> 등기부 신청이 이어진다
subscriptions       payment_id 없음      여기만 끊겨 있었다
payments.metadata   {"plan": "BASIC"}    플랜만 있고 구독 id는 없다
```

두 행을 맞춰 볼 유일한 방법이 `(user_id, 금액, 생성 시각)` 어림짐작이었다. 그건 식별이 아니다.

### 정책은 정하지 않고, 정책이 딛고 설 바닥만 놓았다

환불 시 구독을 어떻게 할지(즉시 해지 / 주기 만료 / 일할 계산 / 표시만)는
**제품이 정할 문제**라 손대지 않았다. `docs/roadmap.md`에 선택지 4개를 정리했다.

대신 **어떤 선택지를 고르든 먼저 있어야 하는 것**만 만들었다 ― 네 선택지 전부
"이 결제가 산 구독이 무엇인가"에 답할 수 있어야 실행되기 때문이다.

```
019_add_subscription_payment_id.sql   subscriptions.payment_id (NULL 허용, FK)
create_subscription(..., payment_id)  같은 트랜잭션에서 함께 쓴다
```

NULL을 허용한 이유: 칼럼이 생기기 전 구독은 결제를 특정할 수 없다. 가짜 값으로
채우면 **"모르는 것"과 "없는 것"이 구분되지 않는다.**

### 지금 동작을 정상으로 굳히는 검사는 넣지 않았다

Sprint 95에서 바로 그 함정을 겪었다 ― 결함을 정상으로 기대하는 검사가 있으면
고칠 때 그 검사가 먼저 막아선다. 그래서 "환불하면 해지된다"도, "환불해도 남는다"도
검사하지 않는다. 고정한 것은 **식별자가 채워지는가** 하나뿐이고, 변이 2종
(인자 미전달 / NULL로 저장) 전부 검출됐다.

### 칼럼 하나가 세 스위트의 정리 순서를 깨뜨렸다

`subscriptions`가 `payments`의 자식이 되면서, `payments`를 먼저 지우던 정리 코드가
`FOREIGN KEY constraint failed`로 죽었다 ― `test_api_regression` / `test_beta_journey` /
`test_race_conditions` 셋 다. 순서를 자식 -> 부모로 바로잡았다.

**그리고 그 죽음이 흔적을 남겼다.** 정리가 예외로 끊기니 픽스처 140행이 DB에 남았고,
다음 실행에서 `no stray qa-* rows` 가드가 그것을 잡아냈다. 가드가 없었다면 조용히
쌓였을 것이다. 남은 행은 전부 지웠다(잔여 0).

### 번호 충돌도 함께 정리

`docs/BUGS.md`에서 **#71과 #72가 각각 두 결함을 가리키고 있었다.** Sprint 78과 95가
이미 쓰인 번호를 다시 썼다(문서의 최대 번호는 91이었다). 나중 것을 **#92 / #93**으로
바꾸고, 코드 주석·테스트·이 문서의 교차 참조 16곳을 함께 고쳤다.
번호는 코드 주석에서 인용되므로, 가리키는 대상이 둘이면 인용이 무의미해진다.

### 품질 게이트

```
Python test_*.py   29/29 PASS  (test_api_regression 1,035 PASS)
tsc 0 / eslint 0 / compileall 0
node --test tests/format.test.mjs  13/13 PASS
변이 2종 전부 검출 / BOM 변동 0 / 픽스처 잔여 0
마이그레이션 019 적용 완료, git 추적됨(커밋은 하지 않음)
```

---

## 2026-08-13 Sprint 96 (마무리) ― 검색조건: 한 행이 목록 전체를 죽였다 (BUGS #95)

패턴 탐색을 즐겨찾기·최근본·검색조건으로 넓혔다.

```
favorites / recent_items   item_id에 FK가 있다 -> "없는 물건을 담았다"가 DB에서 막힌다
search_presets             conditions가 그냥 TEXT다 -> 여기가 열려 있었다
```

### 실측

```
정상 3건 + conditions가 깨진 행 1건  ->  GET /search-presets = 500
                                         멀쩡한 3건까지 통째로 사라진다
```

### 왜 이것이 같은 패턴인가

"저장은 성공했는데 그 저장물을 쓸 수 없다" ― #93/#94와 같은 어긋남이다.
그런데 여기엔 하나가 더 있었다: **사용자가 스스로 빠져나올 수 없다.**

지우려면 `preset_id`가 필요한데 id를 볼 수 있는 유일한 경로가 죽은 그 목록이다.
운영자가 DB를 열어 주기 전까지 그 사용자의 기능은 영구히 죽어 있다.
(실측에서 삭제가 200이었던 건 **내가 DB에서 id를 직접 읽었기** 때문이다 ―
사용자에게는 없는 수단이다.)

### 저장된 JSON을 읽는 세 곳 중 여기만 빠져 있었다

```
payments.py:646   수신 webhook payload    해석 실패 -> 400
payments.py:784   저장된 payload 재처리    해석 실패 -> 400
search_presets.py 검색조건 목록            방어 없음 -> 500
```

규약은 이미 있었고, 한 곳이 규약 밖에 있었을 뿐이다.

### 두 가지 선택을 일부러 했다

**`None`이 아니라 `{}`** ― 프론트가 `preset.conditions[key]`로 읽는다
(`SearchPresets.tsx:139`). `None`이면 거기서 TypeError가 나 화면이 같은 방식으로 죽는다.
서버만 살리고 화면을 죽이면 고친 게 아니다.

**건너뛰지 않고 보여 준다** ― 숨기면 그 행은 영원히 남으면서 사용자당 상한(100개)만
갉아먹는다. 보여야 지울 수 있다.

### 변이가 크래시로 나오던 것을 진단으로 바꿨다

가드를 무력화하자 TestClient가 예외를 되던져 **테스트가 크래시**했다(FAIL 0건, exit=1).
그 상태로는 무엇이 깨졌는지 알 수 없다. 호출을 감싸 실패 사유를 값으로 만들었고,
이제 같은 변이가 `[FAIL] ... "예외: ValueError(...)" (expected 200)`으로 드러난다.
이 저장소에서 여섯 번 반복된 형태다.

### 품질 게이트

```
Python test_*.py   29/29 PASS  (test_api_regression 1,040 PASS)
tsc 0 / eslint 0 / compileall 0
변이 3종 전부 검출(가드 무력화 / 객체 검사 제거 / 손상 행 숨김)
```

### Sprint 96 전체 결산 ― 패턴 하나로 12개 영역을 훑었다

```
등기부(#93)      Sprint 95에서 해결
크롤 문서 경로    상류가 막고 있었다 -> 결함 없음. 대신 그 안전을 지키는
                 wait_for_download()가 테스트 0건이라 9건 신설
document queue   위와 같은 사슬 (mark_queue_done의 안전은 상류가 보장)
favorites        item_id FK가 막는다
recent_items     item_id FK가 막는다
search_presets   결함 발견 -> #95 해결
payments/구독    결함 발견 -> #94. 연결 열쇠만 만들고 정책은 결정 대기
```

**"현재 결함 없음"이 아니라 "어디를 어떻게 확인했고 무엇이 남았는지"**로 남긴다.
남은 것: 사용자 상태·관리자 작업·파일시스템 영역의 같은 패턴 점검.

---

## 2026-08-13 Sprint 97 ― 관리자 작업: 같은 신청을 두 화면이 다르게 본다 (BUGS #96)

Sprint 96이 남긴 목록에서 **관리자 작업**을 집었다. 물었던 것은 "쓰기가 성공했다고
응답했는데 실제로는 안 바뀐 곳이 있는가"였다.

### 쓰기 쪽은 촘촘했다

`admin.py`의 모든 UPDATE를 훑었다. 등기부 상태 전이는 세 분기 전부
`WHERE id=? AND status=?` + `rowcount==0 -> 409`로 막혀 있다. **여기엔 결함이 없다.**

### 읽기 쪽에서 비대칭이 나왔다

```
사용자 목록   SELECT * FROM registry_requests               JOIN 없음 -> 보인다
관리자 목록   JOIN auction_item ON rr.item_id = ai.id       INNER    -> 사라진다
```

물건 행이 없는 신청은 관리자 목록에서 빠지고 **`total`까지 함께 줄어든다.**
빠졌다는 신호가 없다. 사용자 화면은 "처리 중"인데 관리자는 그런 신청이 있다는
사실조차 모른다 ― 돈을 낸 신청이 영영 처리되지 않는다.

### 실 DB를 건드리지 않고 재현했다

`auction.db`를 임시로 복사해 그 위에서만 확인했다.

```
사용자 목록(JOIN 없음)    1건
관리자 목록(INNER JOIN)   0건
LEFT JOIN이면             1건
```

전이(PATCH) 뒤 상세를 다시 읽는 쿼리도 같은 JOIN이라, 거기서는 빈 결과가 응답 조립으로
들어가 **500**(`TypeError: 'NoneType' object is not subscriptable`)이 된다.

### 잠재 결함이라는 것을 숨기지 않는다

지금 프로덕션에 `auction_item`을 지우는 경로는 **없고**, 실 DB의 고아 신청도 **0건**이다.
다만 011~013처럼 테이블을 재작성하는 마이그레이션은 **FK를 끄고 돈다**
(`run_migrations.py:23`). 그 과정에서 UNIQUE 정리로 빠지는 행이 생기면 이 상태가 된다.

대비 비용은 `JOIN` 한 단어이고, 놓쳤을 때의 대가는 조용한 영구 방치다. 그래서 고쳤고,
**"현재 노출 범위"를 BUGS와 코드 주석에 명시**했다 ― `renew()`(#71) 때와 같은 방식이다.

### 지어내지 않는다

LEFT JOIN이면 사건번호·주소가 `None`으로 나간다. 빈 문자열이나 "정보 없음" 같은 값으로
채우지 않았다 ― 그러면 **모르는 것과 비어 있는 것이 구분되지 않는다**(#94에서
`payment_id`를 NULL 허용으로 둔 것과 같은 이유다).

### 크래시를 읽을 수 있는 실패로

INNER JOIN으로 되돌리는 변이에서 목록이 비자 `got[0]`이 IndexError를 내며 **테스트가
크래시**했고, 그 앞의 FAIL 두 줄까지 묻혔다. 빈 자리를 기대값과 다른 값으로 드러내
5개 검사가 전부 깨끗한 `[FAIL]`로 나오게 했다.

그 과정에서 하나 더 걸렀다: 없을 때 `.get()`이 `None`을 돌려주면 **기대값 None과 우연히
같아져 검사가 통과한다.** 목록이 사라졌는데 검사는 초록인 최악의 형태다 ―
기본값을 `"목록에 행이 없다"`로 두어 막았다.

### 품질 게이트

```
Python test_*.py   29/29 PASS  (test_api_regression 1,047 PASS)
tsc 0 / eslint 0 / compileall 0
node --test tests/format.test.mjs  13/13 PASS
변이 1종에서 검사 5개 검출 / BOM 변동 0 / 픽스처 잔여 0 / 고아 감사로그 0
```

### 남은 영역

```
사용자 상태     즐겨찾기·최근본은 FK가 막는다(96에서 확인). 프로필/설정 저장 경로 미점검
파일시스템      문서 저장 경로의 부분 쓰기 - doc_storage_atomicity가 일부 덮는다
문서 상태       document_status <-> 실제 파일 대조 (mark_queue_done의 상류는 96에서 확인)
```

---

## 2026-08-13 Sprint 98 ― 문서 상태와 디스크를 실제로 대조했다 (대체로 건강, 잔해 하나)

패턴 순회의 마지막 영역: **문서 상태 / 파일시스템**. 추측하지 않고 실 DB와 실 디스크를
전수 대조했다.

### 결과

```
document_status = READY        556건   그중 파일이 없는 것  0건    (전부 일치)
물건 행이 없는 READY                    0건
레거시 auction.has_* = 1        200행   그중 파일이 없는 것 35건
디스크의 완성 문서             565개   그중 READY가 아닌 것 110개
```

### 1. `document_status`는 완전히 일치했다

556건 전부 실제 파일이 있다. Sprint 96에서 "`mark_queue_done()`이 파일을 확인하지 않는데
왜 어긋나지 않는가"를 상류 분석으로 설명했는데, **실 데이터가 그 설명을 뒷받침한다.**
설명이 맞았음을 데이터로 확인한 것이라, 이제 그 주장은 추론이 아니라 실측이다.

### 2. 레거시 플래그 35건은 어긋나 있다 ― 그런데 아무도 읽지 않는다

```
has_status_doc=1인데 status 파일 없음   33건   (spec.pdf/appraisal.pdf만 있다)
has_spec_pdf / has_appraisal_pdf         각 1건
```

이것만 보면 #93과 같은 모양이다. 그래서 **누가 이 플래그를 읽는지** 찾았다.

```
api/     0곳        프런트   0곳
읽는 곳: migrate_dryrun.py / migrate_execute.py / step*.py / repair_document_status.py
```

**사용자 화면에 닿는 경로가 없다.** 그리고 `repair_document_status.py`는 첫 줄부터
"판단 근거는 DB 플래그가 아니라 디스크 실물이다"라고 적어 두었다 ― 이 저장소는
플래그가 못 미덥다는 것을 이미 알고 그렇게 설계해 두었다.

**그래서 고치지 않았다.** 읽는 곳이 없는 값을 맞추는 작업은 위험만 늘린다.
대신 "35건이 어긋나 있고, 그것이 무해한 이유"를 여기 남긴다 ― 다음에 누군가
그 플래그를 읽으려 할 때 필요한 것은 수정이 아니라 **이 사실**이다.

### 3. 디스크에만 있는 110개 = 레거시 세대 104 + QA 잔해 6

```
104개   document_status 행 자체가 없다 (레거시 auction 세대의 문서 ― 알려진 두 세대 분리)
  6개   documents/qa-atomic-*/   테스트 픽스처
```

### QA 잔해는 진짜 문제였다 ― 그리고 정리 코드가 조용히 실패하고 있었다

`test_doc_storage_atomicity.py`의 `cleanup()`은 `finally`에 있는데도 잔해가 남았다.
두 가지가 겹쳤다.

**(a) 밖에서 죽으면 `finally`는 돌지 않는다.** 변이 실행의 타임아웃 kill이 그렇다.
`QA_COURT`가 실행마다 난수라 다음 실행도 남의 잔해를 치우지 않는다 ― 계속 쌓인다.

**(b) 이 저장소는 OneDrive 폴더 안에 있고, OneDrive는 `documents/` 아래 디렉터리에
R(읽기 전용) 속성을 붙인다**(정상 법원 디렉터리도 전부 그렇다). 그 상태에서
`shutil.rmtree`는 `PermissionError [WinError 5]`로 실패하는데,
**`ignore_errors=True`가 그 실패를 삼켜** 지운 줄 알게 만든다.

갓 만든 디렉터리는 아직 속성이 붙기 전이라 성공한다 ― **오래 남은 것만 실패한다.**
그래서 "정리는 늘 성공하는데 잔해는 쌓이는" 모양이 됐다.

고친 것: 이전 실행의 `qa-atomic-*`을 함께 쓸어내고, 읽기 전용 속성을 풀고 지운다.
그리고 정리 결과를 **검사로 확인한다**(삼키지 않는다).

### 품질 게이트

```
Python test_*.py   29/29 PASS
tsc 0 / eslint 0 / compileall 0
변이 4종 전부 깨끗한 FAIL (정지 0건)
documents/ QA 잔해 0 / document_status <-> 디스크 불일치 0
```

---

## 2026-08-13 Sprint 98 (이어서) ― 변이 검증이 거짓말을 했다 (`.pyc` 캐시)

Sprint 98의 마지막 전체 회귀에서 `test_doc_storage_atomicity.py` 하나가 실패했다.
**소스는 멀쩡했다.** `git diff`도 깨끗했고, 파일을 다시 읽어도 정상이었다.
그런데 실행하면 "연속 2회" 검사가 10바이트에서 반환한다고 나왔다.

범인은 바이트코드 캐시였다.

```
crawler/doc_crawler.py                  소스: if stable_count >= 2:   (정상)
crawler/__pycache__/doc_crawler.*.pyc   실행: >= 0                    (변이)
```

`.pyc` 헤더는 소스의 **(mtime, size)** 만 본다. 그런데 이 저장소의 변이는 대부분
`>= 2` -> `>= 0`처럼 **길이가 같은 치환**이고, 변이를 쓰고 복구하는 일이 같은 초 안에
끝나면 mtime까지 같아진다 ― Python이 캐시를 버릴 이유가 없어진다.

### 이것이 위험한 진짜 이유

이번엔 "멀쩡한 코드가 실패"로 나타나 알아챘다. 반대 방향도 똑같이 일어난다.

```
변이가 살아남은 것처럼 보인다   -> 없는 구멍을 "구멍 없음"으로 오인하고 넘어간다
```

그쪽으로 나타났다면 **조용히 틀린 결론이 문서에 남았을 것이다.**

### 그래서 이번 세션의 변이 결론을 전부 다시 돌렸다

캐시 무효화(`__pycache__` 삭제 + `-B` + `PYTHONDONTWRITEBYTECODE=1`)를 넣은 실행기로
재검증했다.

```
wait_for_download   8종 중 7종 검출 (.crdownload 제외는 증명된 중복 ― 결론 유지)
search_presets      3종 전부 검출
admin LEFT JOIN     1종에서 검사 5개 검출
payments 연결       2종 전부 검출
```

**결론은 모두 그대로였다.** 다만 확인하기 전까지는 알 수 없었다는 것이 요점이다.
규율은 `docs/TEST_PLAN.md`에 남겼다 ― `-B`만으로는 부족하다(쓰지 않을 뿐, 있는 것은 쓴다).
**지우는 것과 쓰지 않는 것을 둘 다** 해야 한다.

---

## 2026-08-13 Sprint 99 ― 커버리지가 지목한 두 개 (97% -> 98%)

전체 29개 스위트 합산으로 다시 재고, 남은 미도달 분기 중 **도달 가능하고 의미 있는 것**만
골랐다. 숫자를 올리려고 방어 코드에 주입 장치를 만들지 않는다(Sprint 92의 판단 유지).

### 1. 구독 상태머신: 아는 상태가 아니면 거부한다 (`state_machines.py:129`)

`assert_subscription_transition()`에는 관문이 둘인데 **하나가 한 번도 실행된 적이 없었다.**

```
(A) target이 SubscriptionStatus에 있는 값인가     <- 미도달
(B) current -> target이 허용된 전이인가            <- 기존 검사가 전부 여기서 걸렸다
```

막는 것이 다르다. (B)는 "아는 상태끼리 잘못된 순서", (A)는 **오타나 우리가 모르는
문자열**이다. 지금은 (A)가 없어도 결국 같은 예외가 난다 ― 모르는 값은 전이표 조회에서
조용히 False가 되기 때문이다. 그래도 검사를 둔 이유는 전이표에 와일드카드나 기본 허용이
한 줄 들어오는 순간 **(A)만이 유일한 방어**가 되기 때문이다. 그런 줄은 늘 "모르는 상태를
열어 주는" 형태로 들어온다.

`api/v1/state_machines.py` **100%**.

### 2. 경로 탐색 방어: 비교조차 할 수 없는 경로 (`admin.py:154-156`)

포함 검사는 `commonpath([root, path]) == root`인데, 이 함수는 두 경로가 **다른
드라이브에 있으면 답 대신 ValueError를 던진다.**

```
commonpath(["C:\...\registry_documents", "D:\x.pdf"])  -> ValueError
```

`doc_url`이 절대 경로면 `os.path.join(root, doc_url)`이 root를 통째로 버리므로 그런
경로가 실제로 들어온다(UNC `//server/share/...`도 같다). 잡지 않으면 500이고,
잡되 안쪽으로 처리하면 **드라이브만 바꾸면 뚫리는 우회로**가 된다.
지금은 fail-closed이고, 그 선택을 고정했다.

### 같은 함정에 두 번째로 걸렸다 ― 그리고 이번엔 다르게 풀었다

Sprint 95에서 `../../../etc/passwd`가 **"파일 없음" 검사에도 걸려** 경로 검사의 생사를
가리지 못했다. 이번 경로들도 똑같이 존재하지 않는다. 400만 보고 통과시키면 같은 실수다.

다른 드라이브에 실재하는 파일을 만들면 구분되지만 **그것은 저장소 밖에 파일을 쓰는
일이라 하지 않았다.** 대신 **응답 메시지**로 갈랐다 ― 두 가드는 서로 다른 문장을 돌려준다.

```
경로 검사   "doc_url이 등기부 문서 디렉터리 밖을 가리킵니다"
존재 검사   "해당 문서 파일이 없습니다"
```

변이로 확인: `inside = False`를 `True`로 바꾸면 메시지가 "파일 없음"으로 바뀌며 3개 검사가
실패한다. 상태 코드만 봤다면 **그 변이는 살아남았을 것이다**(실제로 처음엔 살아남았다).

### 남은 미도달 46문장의 정체

```
except Exception: rollback; raise    10문장 (admin 5곳 / registry / search_presets / subscriptions)
                                     -> DB 장애 주입이 필요하다. 그러면 검사 대상이
                                        제품이 아니라 주입 장치가 된다(Sprint 92 판단 유지)
payment_providers.py:117             MockProvider.charge() - 프로덕션 호출부 0곳
                                     (v2 인터페이스 create_order/confirm/verify로 대체됨,
                                      실연동 대비로 남겨 둔 v1 잔재. 삭제하지 않고 기록만 한다)
나머지                               데이터 의존 분기(카탈로그 구성 등)
```

### 품질 게이트

```
Python test_*.py   29/29 PASS  (test_api_regression 1,050+ PASS)
tsc 0 / eslint 0 / compileall 0
api/ 커버리지 97% -> 98%  (state_machines 100%)
변이 2종 전부 검출(fail-closed 뒤집기 / 포함 검사 무력화)
```

---

## 2026-08-17 Sprint 144 — 물건 사진 / 문서 Asset Pipeline 완성

전체 내용은 `docs/SPRINT144_ASSET_PIPELINE.md`. 여기에는 **이 문서의 이전 서술을
정정하는 부분**과 실측 수치만 남긴다.

### 정정 1 — `doc_raw` "쓰는 코드 1곳(스케줄러 미도달)"의 결말

Sprint 78이 위 §3에서 정확히 진단해 뒀던 상태(`doc_raw` 쓰는 코드 1곳 /
읽는 코드 0곳)가 **3개 스프린트 동안 그대로 남아 있었고**, 그 사이 문서는 계속
쌓였다(READY 556건). 2026-08-17 실측:

```
documents/ 실제 파일   722개 / 1,313.8 MB
document_status READY  556행
doc_raw                0행          <- 여전히
parsed_document        0행          <- 여전히
```

**이번에 `doc_raw`만 해소했다.** 운영 경로(`doc_worker.py` → `mark_queue_done()`)가
같은 트랜잭션에서 `doc_raw`를 쓰도록 고치고, 이미 수집된 556건은
`backfill_doc_raw.py --apply`로 채웠다(docs/BUGS.md #97).

```
doc_raw            556행  (APPRAISAL 197 / SPEC 197 / STATUS 162)
page_count 확보    394행  (STATUS 162건은 HTML이라 쪽수 개념이 없어 None이 정상)
```

**`parsed_document`는 여전히 0행이고 쓰는 코드도 0곳이다** — 위 §3의 서술이 그 부분은
그대로 유효하다. 다음 스프린트 후보로 남긴다.

### 정정 2 — 이미지 기능

`docs/TEST_PLAN.md` §4의 "이미지: 물건 사진/이미지 기능이 코드에 존재하지 않는다"는
2026-08-17까지 **정확한 서술이었다.** 전 스키마에 image/photo/thumb 계열 컬럼 0개,
Python 소스에 이미지 처리 0건이었다. 이번 스프린트에 수집→저장→DB→API→화면을
전부 신설했다(docs/BUGS.md #98).

### 상태 정합성 교차검증 (이번 실측 — 여기는 깨끗했다)

```
READY인데 파일이 없다         0건
파일이 있는데 READY가 아니다    0건
0바이트 파일                  0건
document_status.item_id 고아   0건
```

이전 스프린트들이 고쳐 온 "거짓 완료" 계열 결함은 **실제로 해소된 상태**임을 확인했다.
이번에 찾은 것은 그 아래층의 다른 문제(메타데이터 부재 / 계층 부재)다.

### 법원 원천 실측 — 사진은 URL이 아니라 base64로 온다

```
IMG#mf_wfm_mainFrame_gen_pic_<N>_img_reltPic
    alt = "<종류>_<순번>"      전경도 / 위치도 / 관련사진 / 내부구조도
    src = "data:image/png;base64,...."
```

- **다운로드할 URL이 없다** → "URL 획득 → HTTP 다운로드" 단계가 없다(법원 서버 추가 요청 0회)
- **선언 MIME이 틀렸다** → `image/png`라고 선언하고 JPEG/GIF를 준다(표본 45장 중 PNG 0장).
  확장자는 **항상 매직 바이트로 판정**한다

### E2E 검증 (실제 법원 물건)

```
1차 (임의 표본 6건)   성공 6/6, 사진 30/30, 확장자 오판 0건
2차 (DB에 있는 9건)   상세 진입 9/9, 사진 45/45, auction_image 45행
브라우저 확인         GET /api/v1/item/502/images/1 -> 200 image/jpeg 70,100 bytes 정상 렌더
```

이미지 수집 성공률 **100% (45/45)**, 물건 기준 **100% (9/9)**.
표본에 "법원에 사진이 없는 물건"이 없어 `NO_IMAGE` 경로는 합성 테스트로만 검증됐다.

### 성능 실측

```
상세 API SQL 문 수     7문 고정 (사진 5장 / 사진 0장 / 문서 3건 — 전부 동일, N+1 없음)
상세 API 지연          3.0 ms/req  (응답 1.4KB -> 3.5KB, 사진 5장 기준)
사진 서빙              3.3 ms/req, 20.4 MB/s
사진 저장 용량         0.69 MB/물건, 5.0장/물건 -> 전체 추정 약 1.3 GB
문서 저장 용량         1,294 MB (APPRAISAL 1,213 / SPEC 79 / STATUS 2)
인덱스                 SEARCH auction_image USING INDEX idx_auction_image_item_seq
```

**남은 병목 2건** (이번에 고치지 않음, 근거 기록):

1. **대용량 감정평가서** — 최대 130.8 MB / 259쪽이 실재한다(`경주지원/2024타경12602`).
   평균 6.2MB/31.6쪽이지만 꼬리가 길다. 현재 뷰어는 iframe에 통째로 넣으므로 첫 렌더가
   느리다 → 목록·뷰어 양쪽에 "새 탭" 링크를 함께 뒀다. 쪽 단위 렌더링은 별도 과제.
2. **사진 중복 저장** — 같은 사건의 여러 물건이 같은 사진을 갖는 경우가 있어 표본에서
   **사진 바이트만 놓고 보면 11.3%(0.70/6.20 MB)**가 중복이다.
   (2026-08-17 정정 — **전체 자산 기준으로는 0.1%**다: 중복 0.7 MB / 전체 1,320 MB.
    문서가 용량의 99.5%를 차지하고 문서에는 중복이 0건이기 때문이다. 이 두 숫자를
    같은 것으로 읽으면 dedup의 실익을 10배 이상 과대평가하게 된다.)
   `file_hash`를 이미 기록하므로 해시 기반
   dedup이 가능하다(전체 약 150MB 절감 추정). 지금 규모에서는 급하지 않다.

### 위생 — `documents/` 빈 디렉터리 1,674개

`doc_paths.doc_exists()`가 예전에 조회하면서 `os.makedirs()`를 부른 흔적이다. **원인
코드는 2026-08-14에 이미 고쳐졌고 쓰레기만 남아 있다**(파일 0개, 손실 없음).
`empty_doc_dirs_dryrun.py`로 목록과 안전한 삭제 절차를 만들어 뒀다 — `documents/`
하위 파괴적 정리는 승인 영역이라 실행하지 않았다.

### 품질 게이트

```
Python test_*.py    28/29 PASS
                    유일한 실패: test_schema_hygiene.py "추적되지 않는 storage/ 소스"
                    -> 새 migration 020 파일이 아직 미커밋인 것을 검사가 정확히 잡은 것.
                       커밋하면 즉시 GREEN (Commit 금지 지시로 이번에 수행하지 않음)
test_asset_pipeline.py  20그룹 전부 PASS (신설)
tsc 0 / eslint 0 / next build 성공
```

이 스프린트 때문에 깨진 기존 테스트 6개는 전부 고쳤다. 그중 하나
(`test_doc_storage_atomicity.py`)는 **테스트가 옳았다** — 'image'를 넣으면서 사전 조회를
`.get()`으로 바꿨더니 오타 난 doc_type이 조용히 성공 처리되는 상태가 됐다. 고치려던
것보다 나쁜 결함이라 "레거시 컬럼이 없는 것(image)"과 "아예 모르는 종류"를 나누고
후자는 그대로 예외로 죽게 했다.

또 이 스프린트 **이전부터** 깨져 있던 테스트 2건을 함께 고쳤다.

- `test_bootstrap.py`: 드리프트가 **해소됐을 때만** 도달하는 줄에서 `sorted()`가
  `None < str`로 죽었다(상황이 좋아지는 순간 테스트가 죽는 방향)
- `test_pipeline_integrity.py`: 이름·주석은 "상한(ceiling)"인데 비교만 `== 1`이라
  지역 오염이 실제로 0이 되자 실패했다. 같은 파일의 다른 상한 검사는 전부 `<=`다

---

## 2026-08-17 Sprint 144+ — Asset Pipeline 전수 검증 (실측 우선, 문서는 결과 기록)

Sprint 144 직후 같은 날 이어서 수행한 **전수 검증**이다. 출발점으로 받은 세 숫자
(`doc_raw 0` / `722 files` / `READY 556`) 중 앞의 하나는 **이미 Sprint 144에서 해소된
상태**였으므로 다시 고치지 않았고, 나머지를 근거로 더 깊은 계층까지 대조했다.

### 재측정 — Sprint 144 직후 실제 상태

```
doc_raw            0 -> 556행     (Sprint 144에서 해소, BUGS #97)
auction_image      0 ->  45행     (Sprint 144 신설)
documents/       722 -> 767 파일 / 1,320.0 MB  (사진 45장 추가분)
document_status  5,628행 (READY 556 / COLLECTING 5,069 / FAILED 3)  변동 없음
```

### 파일 무결성 — 전수 검사 (표본이 아니라 767개 전부)

```
0바이트 파일                     0
512바이트 미만                   0
잔여 임시파일(.tmp/.crdownload)  0
손상 PDF (396개 전부 열어봄)      0
손상 JSON (163개 전부 파싱)       0
손상 HTML (163개)                0
확장자/매직 불일치 이미지 (45개)   0
```

### DB <-> 파일시스템 정합 — 전수 대조 (경로·크기·SHA-256 전부)

```
doc_raw        556행  path/size/hash 불일치  0
auction_image   45행  path/size/hash 불일치  0
```

### API 전수 스윕 (표본이 아니라 전 행)

```
READY 556행 -> API      {200: 556}     실패 0
auction_image 45행 -> API {200: 45}    실패 0
비-READY 400행 -> API    {404: 400}    잘못된 200 노출 0
```

**모든 계층이 끊긴 곳 없이 이어져 있음을 전수로 확인했다.** "이미지가 안 보인다 /
문서가 안 보인다"는 Sprint 144 이전의 증상이고, 그 원인(계층 부재 + 메타데이터 부재)은
해소됐다.

### ★ 이번 패스에서 새로 찾은 것: 현황조사서 33.5% 영구 수집 불가 (BUGS #100)

파일 개수 히스토그램에서 **문서 세트가 불완전한 물건 41건**이 보였고, 그 패턴을 추적한
결과 원인이 나왔다.

```
have=[APPRAISAL, SPEC] missing=[STATUS] : 36건   <- 압도적 다수
have=[SPEC, STATUS]    missing=[APPRAISAL] : 2건
have=[APPRAISAL]       missing=[SPEC, STATUS] : 2건
have=[STATUS]          missing=[APPRAISAL, SPEC] : 1건
파일/상태 불일치(incoherent) : 0건   <- 부분 수집 자체는 정직하게 기록돼 있었다
```

STATUS만 유독 뒤처지는 이유를 코드에서 찾았다 — `get_doc_button_id("status", item_no)`가
물건번호 2 이상에 None을 돌려주고 있었고, `auction_item`의 **33.5%(629/1,876)**가 거기
해당했다. `document_queue`에서 `status` + `item_no != 1`의 **done이 0건**(단 한 번도 성공한
적이 없다)이라는 것이 그 증거다.

실 브라우저 DOM 실측으로 **버튼이 실제로 존재하고 문서가 사건 단위**임을 확인해 고쳤다
(자세한 근거는 BUGS #100). 결과:

```
수집 가능해진 status 큐 행    109 (그중 pending 103)
현황조사서를 받을 수 있게 된 물건  629 / 1,876 (33.5%)
'수집중'에 갇혀 있던 상태 행     628 -> 정상 대기로 의미가 바뀜
여전히 버튼 id가 없는 큐 행      0
```

### 성능 실측 (STEP 10)

```
상세 API           2.6~3.3 ms (mean), p95 3.8 ms — 자산 수와 무관 (SQL 7문 고정)
사진 서빙          3.2 ms
spec.pdf (383KB)   3.8 ms
appraisal (2.4MB)  9.7 ms
★ 최대 PDF (131MB) 399 ms      <- 실질 병목. 뷰어/목록에 "새 탭" 링크를 둔 이유
documents/ 전체 walk  138 ms   <- 요청당 하면 안 되는 비용. API는 하지 않는다(전수 확인)
PDF page_count 계산   49 ms (131MB 기준) <- doc_raw에 캐시하는 이유
이미지 크기 파싱      0.001 ms  <- Pillow 없이 순수 stdlib, 비용 무시 가능
```

쿼리 계획도 확인했다 — 갤러리와 doc_raw 조회가 전부 인덱스를 탄다
(`idx_auction_image_item_seq`, `sqlite_autoindex_doc_raw_1` COVERING INDEX).

### 규모 위험 (측정만, 최적화하지 않음)

```
측정치       사진 0.69 MB/물건(5.0장) · 문서 6.47 MB/물건
현 corpus 완주   약  13.1 GB   자산행 ~15,008   큐행 ~7,504
1만 물건         약  69.9 GB   자산행 ~80,000   큐행 ~40,000
10만 물건        약 699.2 GB   자산행 ~800,000  큐행 ~400,000
로컬 여유        832.8 GB / 930.6 GB
```

로컬 디스크는 10만 물건 직전까지 버틴다. **진짜 위험은 디스크가 아니라 OneDrive다** —
`documents/`가 동기화 폴더 안이라 13 GB가 그대로 개인 OneDrive로 올라간다.
기존에 문서화된 OneDrive 이슈(빌드 EPERM, BUGS #35)와 **같은 원인의 다른 축**이라
새 항목을 만들지 않고 `docs/BETA_RELEASE_CHECKLIST.md`의 해당 항목을 보강했다.

### 중복 바이트 — 앞선 서술 정정

Sprint 144 기록의 "중복 11.3%"는 **사진만 놓고 본 값**이다. 전수 측정 결과
**전체 자산 기준으로는 0.1%**(0.7 MB / 1,320 MB)다 — 용량의 99.5%가 문서이고 문서
중복은 0건이기 때문이다. 두 숫자를 섞어 읽으면 dedup의 실익을 10배 이상 과대평가한다.

### 고아 자산

```
auction_item이 없는 파일  4개 (고양지원/2024타경2803/1 — Sprint 이전부터 존재)
```

`cleanup_orphans_dryrun.py`의 [C] 항목 그대로이며 삭제는 승인 영역이라 손대지 않았다.

### `document_version_log` 0행의 정확한 이유 (2026-08-17 규명 — 새 결함 아님)

Sprint 144+에서 "왜 0행인가"를 코드로 끝까지 따라간 결과, **아직 재수집이 안 일어나서가
아니라 현재 코드로는 구조적으로 한 행도 생길 수 없다**는 것이 확인됐다.

```
collect_spec/status/appraisal()  파일이 이미 있으면 early-return (success=True)
                                 그 경로는 previous_hash/new_hash를 "" 로 둔다(_empty_result 기본값)
mark_queue_done()                if previous_hash and previous_hash != new_hash:  <- 항상 False
collect_document(..., overwrite) doc_worker는 overwrite를 넘기지 않는다 (기본 False)
```

즉 **한 번 받은 문서는 다시 받지 않고, 따라서 해시 비교도 버전 로그도 실행되지 않는다.**
실측이 이를 뒷받침한다 — `doc_raw` 556행이 **전부 doc_version=1**이다(2 이상 0행).

**이것은 새 결함이 아니라 이미 명시된 미결정 사항의 결과다.**
`storage/database.py:enqueue_documents()`의 주석이 *"done/failed/SKIPPED_EXPIRED를 되살려
다시 수집할 것인지는 재수집 정책이라 제품 판단이다(docs/roadmap.md 결정 대기)"*라고
적어 두었다. 재수집 정책이 정해지기 전까지 `document_version_log`와
`mark_queue_done()`의 해시 비교 분기는 **도달 불가능한 코드**다.

실질적 의미: 법원이 문서를 정정·갱신해도(정정 공고 등) 우리는 **영원히 최초 수집본을
들고 있다.** 감정평가서·매각물건명세서는 정정되는 일이 실제로 있으므로, 재수집 정책은
"있으면 좋은 것"이 아니라 데이터 정확성 항목이다 — 다만 그 결정은 제품 판단이라
여기서 만들지 않는다.

---

# Sprint 145 실측 (2026-08-17) — 사용자 화면 기준으로 다시 세다

앞선 스프린트들이 적어 온 "READY 556건 / doc_raw 556행 / auction_image 45행"은 전부
사실이다. 다만 그것은 **전체 corpus 기준**이고, 사용자가 실제로 볼 수 있는 물건 기준으로
다시 세면 그림이 달라진다.

## 기본 검색에 뜨는 물건은 9건이다

`GET /api/v1/search`의 기본값은 `include_closed=False`(= `auction_date >= 오늘`)다.

```
auction_item                 1,876
  auction_date >= 오늘            9      <- 사용자가 보는 전부
  auction_date <  오늘        1,867
  auction_date 비어 있음          1
```

| 기준 | 사진 | 문서 3종 전부 READY |
|---|---|---|
| 전체 1,876물건 | 9물건 (0.5%) | 197물건 (10.5%) |
| **검색에 뜨는 9물건** | **9/9 (100%)** | **2/9 (22%)** |

**사진은 사용자가 보는 모든 물건에 이미 있다.** 부족한 것은 문서이고, 그 원인은
파이프라인 결함이 아니라 큐를 소진할 배치가 돌지 않는 것이다(아래).

## ★★ 2026-08-20부터 검색 결과가 0건이 된다

```
검색에 뜨는 9건의 매각기일    전부 2026-08-19
2026-08-20 기준 남는 물건     0건
마지막 crawl_date            2026-08-12 (5일 경과)
logs/daily_run.log           5일 전
예약 작업 등록                0건
```

**예약 작업 등록 0건을 이번에 처음 실제로 확인했다** — 전체 249개 예약 작업을
이름·경로·실행 파일·인자 전부로 검색해 이 저장소를 가리키는 것이 하나도 없었다.
로그가 5일째 없는 이유가 이것이다. 로그 부재만으로는 "배치가 실패했다"와 "배치가
아예 등록되지 않았다"를 구분할 수 없었다.

Sprint 112가 2026-08-14에 이 날짜를 예측했고 등록 절차까지 준비해 두었다
(`.\register_scheduler_tasks.ps1 -Apply`). 실행은 사용자 환경 변경이라 SKIP이다.
`test_pipeline_integrity.py` §11이 이제 등록 여부까지 함께 보고한다.

## `document_status`에 IMAGE 행이 아직 없다 (정상)

```
document_status  APPRAISAL/SPEC/STATUS 만 존재, IMAGE 0행
document_queue   appraisal/spec/status 만 존재, image 0행
auction_image    45행
```

모순처럼 보이지만 정상이다. 사진 45장은 **큐를 거치지 않고** Sprint 144의 E2E 검증이
`save_auction_images()`를 직접 호출해 저장한 것이라 상태 행이 없다. `enqueue_documents()`는
이미 `image`를 포함하므로(코드 확인) 다음 06:00 크롤에서 image 큐 행이 처음 생긴다.

API는 이 상태에서도 정확하다 — `_images_status()`가 `auction_image` 행이 있으면
무조건 READY로 답하고(볼 수 있는 사진이 실제로 있으므로), 없을 때만 `document_status`를
본다. 실측: item 502 → `images_status=READY`, item 1 → `COLLECTING`.

## 사진 45장 전수 대조 (파일 ↔ DB)

```
파일 없음 0 / 크기 불일치 0 / SHA-256 불일치 0 / 이미지가 아님 0 / 확장자 오판 0
```

선언 MIME은 45장 전부 `image/png`인데 실제는 JPEG 40 + GIF 5다. Sprint 144의
"선언을 믿지 않고 매직 바이트로 판정한다"가 실데이터에서 그대로 유지되고 있고,
서빙 Content-Type도 실제 바이트와 일치한다(`image/jpeg` x4, `image/gif` x1).

---

## 2026-08-17 Sprint 145 — 사용자 흐름 전 구간 실화면 검증 + 검색 썸네일

Sprint 144/144+가 만든 것을 **실제 브라우저에서 끝까지 써 보는** 것이 목표였다.
그 과정에서 흐름의 첫 칸(검색 결과)에 빠진 것을 찾아 채웠고, 빌드가 못 잡는 결함을
실화면에서 잡았다.

### ★ 처음으로 로그인 상태의 상세페이지를 실제로 확인했다

Sprint 144에서는 계정 자격이 없어 상세페이지 육안 검증을 못 했다고 보고했다.
이번에는 브라우저에 이미 세션이 있어(jab31@naver.com) 전 구간을 실제로 확인했다.

```
검색(/search)        66건, 카드 9장에 실제 법원 사진 썸네일 표시
  -> 상세(/properties/502)
     물건 사진        "5장" 대표 이미지 + 썸네일 5개(전경 3 / 내부 1 / 내부구조도 1)
     관련 문서        매각물건명세서 2쪽 / 현황조사서 / 감정평가서 19쪽  (전부 수집완료)
     PDF 뷰어         감정평가서 실제 렌더 — 2024타경3528, 감정평가액 282,000,000원
     페이지 이동      1/19 -> 2/19 정상 (우리 컨트롤과 내장 뷰어가 동기화)
     확대/축소        100% 표시, -/+ 동작
     HTML 뷰어        현황조사서 실제 렌더(사건번호/조사일시/점유관계 본문)
                     쪽수 개념이 없으므로 페이지 이동 UI가 **자동으로 숨겨진다**(설계대로)
```

### 새로 채운 것 — 검색 결과 대표 사진

흐름의 첫 칸에 사진이 없었다. `api/v1/search.py`는 `SELECT *`만 하고
`ResultList.tsx`에는 `<img>`가 **0개**였다(그 파일의 주석이 "auction_item에 이미지
컬럼이 없어 항상 빈 placeholder만 차지하므로 넣지 않는다"고 이유까지 적어 두었는데,
Sprint 144에 `auction_image`가 생기면서 그 전제가 바뀌었다).

```
api/v1/search.py    대표 사진(MIN(seq))을 **배치 조회 1회**로 가져온다
                    (바로 옆 favorites 배치 조회와 같은 패턴)
ResultList.tsx      thumbnail_url이 있을 때만 80x80 썸네일을 그린다
                    -> 사진 없는 물건은 종전과 완전히 같은 텍스트 전용 레이아웃
```

실측: **페이지 크기 10/50/100 모두 SQL 3문 고정 — N+1 아님.**
기존 응답 키는 하나도 바뀌지 않았고 `thumbnail_url`만 추가됐다(값은 사진 없으면 null).

### ★ 빌드가 통과하는데 화면이 죽는 결함을 실화면에서 잡았다

`ResultList.tsx`는 **서버 컴포넌트**인데 `<img onError={...}>`를 넣었다.

```
tsc        통과
eslint     통과
next build 통과
실제 렌더  Runtime Error: Event handlers cannot be passed to Client Component props
```

세 게이트가 전부 초록인데 페이지 전체가 에러 화면이 됐다. 썸네일만 작은 클라이언트
섬(`ResultThumbnail.tsx`)으로 떼어 고쳤다(같은 카드의 `FavoriteButton`과 같은 방식).

**교훈**: 서버/클라이언트 컴포넌트 경계 위반은 이 저장소의 정적 게이트 3종이 잡지 못한다.
프런트 변경은 실제로 렌더해 봐야 한다.

### 사건 단위 문서 중복 수집 해소 (저장 구조 변경 없이)

BUGS #100으로 현황조사서를 물건번호 2 이상에서도 받게 되면서 **같은 문서를 물건 수만큼
받는** 구조가 됐다. 실측 비용은 용량이 아니라 시간이었다.

```
사건 1,384개 / 물건 1,876개  -> 초과 수집 492회(35.5%)
worker 1건 약 22초           -> 약 3.0시간  (가동 창 02:00~04:00 = 2시간을 넘긴다)
초과 저장 용량                약 13.4 MB    (무의미)
```

같은 사건의 물건 1과 2에 대해 **각각 따로 실제 수집을 돌려 대조**한 결과:

```
status.html   40,596 B  해시 동일
status.json   12,014 B  해시는 다르나 `fields` 115개 키 완전 일치
                        (차이는 우리가 찍는 extracted_at 하나뿐)
```

그래서 형제 물건이 방금 받아 둔 것이 있으면 브라우저를 다시 몰지 않고 복사한다.
**파일은 종전과 같은 경로에 같은 내용으로 놓이므로 저장 구조 변경이 아니다** —
API·뷰어·`doc_exists()` 무영향. 재사용 대상은 6시간 이내 형제로 좁혔고(재수집 정책이
미결정이라 보수적으로), 형제가 빈 캡처면 복사하지 않고 직접 수집한다.

### 개발 환경 함정 2건 (제품 결함 아님, 그러나 QA를 오래 헤매게 만든다)

**(1) uvicorn reloader 자식 프로세스가 부모보다 오래 살아 포트를 붙잡는다.**
`python api_server.py`(reload=True)는 `multiprocessing.spawn` 자식을 만든다. 부모를
`Stop-Process`로 죽여도 **자식이 살아남아 8000 포트의 리스닝 소켓을 계속 들고 있고**,
그 자식이 **옛 코드로 응답한다.** 이번에 그런 고아가 4개까지 쌓였다
(`netstat`은 LISTENING으로 보이는데 `Get-Process`는 `<gone>`).

    증상: 코드를 고치고 서버를 재시작해도 응답이 안 바뀐다
    확인: Get-NetTCPConnection -LocalPort 8000 -State Listen 의 OwningProcess 확인
    함정: 자식의 명령줄은 `multiprocessing.spawn`이라 `*api_server*` 필터에 안 걸린다
    조치: Get-Process python | taskkill /PID <id> /T /F  (트리 종료)

> 이 과정에서 나는 원인을 **"stale .pyc"로 잘못 지목**했다. 근거로 삼은 바이트코드
> 검사가 틀렸다(`co_consts`는 중첩 함수 안으로 들어가지 않고, dict 리터럴의 키는
> 튜플로 저장된다). 같은 코드를 `--reload` 없이 다른 포트로 띄우자 즉시 정상 응답이
> 나와 실제 원인이 드러났다. **재시작만으로 확인했다고 믿지 말고, 응답을 주는 프로세스가
> 정말 방금 띄운 그 프로세스인지 확인해야 한다.**

**(2) `npm run build`의 OneDrive EPERM** — 이미 문서화된 항목(BETA_RELEASE_CHECKLIST)이
이번에도 그대로 재현됐다. dev 서버를 죽이고 `.next`를 지우면 정상 빌드된다.

### 품질 게이트

```
Python test_*.py   30개 중 29 PASS
                   유일한 실패: test_schema_hygiene.py — 새 파일 미커밋 (Commit 금지)
test_asset_pipeline.py  24그룹 PASS (Sprint 145에 4그룹 추가:
                        사건단위 재사용 / 사진 재시도·최종실패 / 재다운로드 없음 / 검색 썸네일)
tsc 0 / eslint 0 / next build 성공 / compileall 0
```

---

## 2026-08-17 Sprint 146 — 공급망 실측 / 큐 소진 속도 정정 / 경로 규칙 단일화

### ★★ 앞선 보고의 오류 정정 — "큐 완주에 8일 이상"은 틀렸다

Sprint 145 보고와 `docs/roadmap.md`의 재수집 정책 절이 **pending 2,753건 전부에 22초를
곱해** "완주 8일 이상, 가동 창 확대나 병렬 worker가 선행돼야 한다"고 적었다. **틀렸다.**
큐 항목의 대다수는 브라우저를 열지 않는다 — 매각기일이 지난 항목은
`mark_queue_skipped_expired()`가 DB 몇 번으로 종결한다.

운영 큐를 그대로 복제해 실측했다:

```
복제한 pending          2,753건
  기일경과로 즉시 종결   2,730건 x 5.1 ms = 13.9초
  실제 수집이 필요한 것     23건 x 22초   = 506초
  ------------------------------------------------
  1회 실행 총 소요                        = 519.9초 (8.7분)
  가동 창(02:00~04:00)                    = 7,200초  -> 창의 7%만 사용
```

**현재 규모에서 가동 창은 병목이 아니다.** 병렬 worker나 창 확대를 선행 조건으로 볼
근거가 없다. 참고로 전 물건(1,876) x 4종을 **전부 실수집**하면 45.9시간이라 그때는
창을 넘긴다 — 재수집 정책을 정할 때 쓸 숫자는 이쪽이다(roadmap 해당 절도 정정했다).

### 검색 9건의 원인 — 단계별 count로 분리 (검색/필터 결함 아님)

```
auction (크롤러 원본)          1,876    auction_item                1,876   차이 0
  validation PASS              1,864      validation PASS           1,864
auction 기일>=오늘                  9    auction_item 기일>=오늘         9   차이 0
마지막 crawl_date          2026-08-12    남은 기일        2026-08-19 뿐
```

**공급망은 전 구간 온전하다.** `migrate_execute.py`도 정상 반영돼 있고 검색 필터도
정상이다(아래 전수 확인). 원인은 오직 **크롤이 2026-08-12 이후 멈춘 것** 하나다.

### 검색 API 전수 (실제 HTTP)

기본/종결포함/시도/시군구/법원/가격/감정가/물건종류/유찰횟수/기일범위/정렬/페이지/size100/
범위밖page/잘못된size/음수page/지역목록 — **17개 경로 전부 정상**(잘못된 입력은 422).
`thumbnail_url` 키는 **모든 응답 항목에 존재**하고 사진이 없으면 null이다.

### 지역 데이터 오염 — 현재 사용자 영향 0건 (정량화)

```
sido 가 틀린 물건     4건  (id=550 인천->서울, 1787 경남->부산, 8160 경기->서울, 9977 제주->세종)
sigungu 옛 형식     207건  (전부 '저장값이 새 값의 접두' — 정보 손실 없이 덮어쓸 수 있음)
'용인시 수지구'로 검색   0건  (반면 '용인시'로는 9건)
'안산시 단원구'로 검색   0건  (반면 '안산시'로는 31건)
```

**★ 그런데 211건 전부가 기일이 지난 물건이다 — 기본 검색에서 이미 제외된다.**
따라서 지금 사용자가 겪는 영향은 **0건**이고, 앞으로 들어올 새 데이터는 현재 규칙으로
정규화되므로 오염되지 않는다. `backfill_region_normalize.py --apply`가 준비돼 있으나
**422행을 덮어쓰는 대량 데이터 변경**이라 승인 영역으로 두고 실행하지 않았다.

### 경로 조각 규칙이 두 벌이었다 — 단일화 (쓰는 곳 vs 읽는 곳)

`sanitize_path_segment()`가 신설되면서 쓰는 쪽은 역슬래시·`..`·빈 값까지 처리하게 됐는데
**읽는 쪽(`api/v1/documents.py`)만 옛 규칙(`/`만 치환)으로 남아 있었다.**

```
case_no = "2024\타경1"
  크롤러가 쓰는 곳   documents/법원/2024_타경1/2/spec.pdf
  API가 찾는 곳      documents/법원/2024\타경1/2/spec.pdf   <- 다른 경로
```

실데이터에 역슬래시는 0건이라 지금 터지는 버그는 아니었지만, **규칙이 두 벌인 상태
자체**가 BUGS #50/#64와 같은 계열의 결함이다. 읽는 쪽도 같은 함수를 쓰게 고쳤고,
회귀는 리터럴이 아니라 **두 구현의 결과를 직접 대조**한다(`test_asset_pipeline.py` §19-B,
`test_pipeline_integrity.py` §0 — 후자의 리터럴 검사도 함께 정정했다. 규칙이 좋아졌는데
테스트가 실패하는 상태였다).

### 프런트 실화면 회귀 — 4가지 자산 조합 전부

```
사진O 문서O (502)    사진 5장 + 문서 3종(2쪽/19쪽) + 뷰어 정상
사진O 문서X (11855)  사진 5장, 문서는 '수집중'으로 비활성 표시
사진X 문서O (111)    '사진 수집 중' 안내, 문서 수집완료
사진X 문서X (58)     '사진 수집 중' 안내, 문서 **클릭 불가**(링크/새 탭 링크 0개)
```

네 경우 모두 런타임 에러 0건. Sprint 144가 고친 "수집 전 문서를 링크처럼 보이게 하지
않는다"가 실제 화면에서 확인됐다.

### 보안 프로빙 (12종)

문서/사진 경로탈출, 음수·거대 seq, 없는 물건, item_id SQLi, sort_by 주입, sido 주입 —
**전부 차단**(404/400/422)이고 응답 본문에 파일시스템 경로·트레이스 누출 0건.
주입 시도 후 DB 행 수도 그대로다.

### TODO/FIXME 분류 (8건)

```
의도된 설계  2건  payment_providers._DEPRECATED_PROVIDERS (폐기 예정 PG 경고 가드)
과거 이력    1건  migrate_execute.py의 해소된 "Critical TODO" 참조 주석
열린 기능 공백 3건  SearchForm.tsx — 면적/특수조건/조합방식은 백엔드 미지원
그 공백을 고정 4건  test_search.py가 위 3건을 소스 대조로 못 박아 둔 검사
```

**관리되지 않는 부채는 0건이다** — 열린 3건은 테스트가 사라짐을 막고 있다.

### 품질 게이트

```
Python test_*.py   31개 중 30 PASS  (실패 1 = 신규 파일 미커밋 검사, Commit 금지)
test_asset_pipeline.py  26그룹 PASS (Sprint 146에 §19-B 경로 규칙 단일화 추가)
tsc 0 / eslint 0 / next build 성공 / compileall 0
```

---

## 2026-08-17 Sprint 146 (계속) — 큐 전수 분류 / 법원 없는 식별키 재발 / 스케일 위험

### 큐는 매우 깨끗하다 (처리 불가 데이터 전수 분류)

```
대응 auction_item 이 없는 큐 행            0
파일이 이미 있는데 pending (헛수집 예정)      0
document_status=READY 인데 pending         0
큐 done 인데 파일 없음                      0   ← 법원까지 넣어 판정한 값
in_progress (worker 없이 남은 것)           0
failed 인데 retry 예산이 남은 것             0
auction_item 은 있는데 큐가 없는 물건        716   (그중 기일이 미래인 것 0 = 문제 아님)
```

### ★ BUGS #103 — "법원 없는 식별키"가 세 번째로 재발했다

`reconcile_queue_auction_date()`(Sprint 145 신설)가 `case_no + item_no`로만 물건을 찾았다.
법원마다 사건번호를 독립 채번하므로 **큐의 (사건,물건)이 다른 법원의 물건과 매칭되는 행이
18행(pending 12행)** 있었고, 그대로 두면 기일을 바로잡으려던 함수가 **엉뚱한 사건의
날짜로 큐를 영구히 덮어쓴다.** `court_code`를 받아 대조하도록 고쳤고, 법원을 못 받으면
정정하지 않는다.

**★ 이 감사에서 내가 쓴 측정 쿼리도 같은 실수를 했다.** 법원 없이 조인해
"done인데 파일 없음 3건"이라는 허위 결과를 냈고, 법원을 넣자 **0건**이었다.
진단 도구도 같은 규칙을 지켜야 한다 — 이 항목을 기록으로 남긴다.

### 검색 스케일 위험 (현재 / 10배 / 100배)

```
현재 auction_item 1,876행
기본 검색 계획   SEARCH ... USING INDEX idx_auction_item_auction_date
                + USE TEMP B-TREE FOR LAST 2 TERMS OF ORDER BY   ← 주목
OFFSET 0     0.20 ms
OFFSET 1000  1.08 ms
OFFSET 10000 1.34 ms
필터 COUNT(*) 0.07 ms
```

**TEMP B-TREE가 기본 정렬에서 발생한다.** 인덱스 `idx_auction_item_default_sort`는
`(auction_date, fail_count)`인데 쿼리는 `auction_date ASC, fail_count DESC, id DESC`로
**방향이 섞여** 인덱스를 끝까지 못 쓴다. 현재는 정렬 대상이 작아(기본 검색은 미래 기일만)
0.2 ms지만, **`include_closed=true`는 전 행이 대상**이라 100배 규모(약 18만 행)에서는
매 요청마다 그만큼을 정렬하게 된다.

지금 고치지 않는다(현재 p95 3.8 ms, 실사용 문제 없음). 고칠 때의 선택지만 기록한다:
(a) 정렬 방향을 인덱스와 맞추거나, (b) `(auction_date DESC, fail_count DESC, id DESC)`
복합 인덱스를 추가하거나, (c) 커서 기반 페이지네이션. 셋 다 **API 응답 계약이나 스키마를
건드리므로** 제품/승인 판단이 필요하다.

### 조건부 캐싱 동작 확인 (외부 추가분 `api/http_cache.py`)

```
GET  /documents/APPRAISAL  200  2,528,908 B
     If-None-Match         304          0 B
     If-Modified-Since     304          0 B
GET  /images/1             200     70,100 B  -> 조건부 요청 시 304 / 0 B
```

가장 큰 자산(2.5MB 감정평가서)이 재열람 시 본문을 다시 보내지 않는다. 신선도 판단은
바뀌지 않았다(클라이언트는 여전히 매번 서버에 물어본다).

### 품질 게이트

```
Python test_*.py   32개 중 31 PASS  (실패 1 = 신규 파일 미커밋 검사, Commit 금지)
test_asset_pipeline.py  28그룹 PASS (Sprint 146에 §12-D, §19-B 추가)
tsc 0 / eslint 0 / next build 성공 / compileall 0
```

---

## 2026-08-17 Sprint 147 — 합성 검증으로 남았던 3건을 **실데이터로** 확정

Sprint 146이 "크롤 재개 후에만 확인 가능"으로 남긴 3건을, 크롤 재개를 기다리지 않고
**임시 DB + 실제 법원 + 운영 코드(`doc_worker.main()`)**로 확정했다.
운영 `auction.db`/`documents/`는 건드리지 않았다.

### (1) `document_status`에 IMAGE 행이 실제로 생긴다 — 확정

실제 worker로 서울중앙 6물건(사진+현황조사서 12큐행)을 처리했다.

```
document_status   IMAGE  READY  6
                  STATUS READY  6
auction_image     30행 (물건당 5장) / path·size 불일치 0
doc_raw           6행
큐                image done 6 / status done 6
소요              222.4초 (12건)
```

### (2) `NO_IMAGE` 실데이터 관측 — 확정

법원 원천에서 **사진이 실제로 없는 물건**을 찾아냈다:
서울중앙 **2025타경103470**(차량, 제네시스). 캐러셀 컨테이너(`ul[id$=gen_pic]`)는 있는데
`img[id*=_img_reltPic]`이 **0개**다.

```
collect_images  success=True  no_asset=True  image_count=0
document_status IMAGE = NO_IMAGE
큐              done            (실패로 기록되지 않는다 = 재시도 고리 없음)
auction_image   0행 / 디스크 파일 0개
```

설계 의도대로 **"실패가 아닌 정상 종결"**로 처리된다. 부동산은 사진이 있고 차량 물건은
없는 경향이 보이지만, 표본 1건이라 일반화하지 않는다.

### (3) ★ 사건 단위 재사용은 발동했지만 **절감의 4%만** 실현하고 있었다 (BUGS #104)

재사용이 실제로 발동하는지 확인하러 갔다가, 발동은 하는데 **비용을 거의 못 아끼고
있었다**는 것을 찾았다.

```
navigation      15.2초   <- doc_worker가 무조건 먼저 한다
overlay 수집     0.6초   <- 재사용이 아끼던 전부
형제 파일 복사   0.002초
```

`doc_worker`가 `go_to_case_detail()`을 **무조건 먼저** 부르고 그 다음에
`collect_document()`(재사용이 들어 있는 곳)를 부르는 구조였다. 물건당 절감 0.6초(4%),
492회 기준 **5분**. 여러 문서가 적어 둔 **"약 3.0시간 절감"은 navigation까지 건너뛴다고
가정한 값**이라 약 26배 과대였다(해당 문서 전부 정정).

**결과가 완전히 같아서 아무 테스트도 잡지 못했다** — 느려지기만 하고 깨지지 않는다.
합성 테스트는 `collect_status()`를 직접 불러 navigation을 거치지 않으므로 구조적으로
볼 수 없었다.

수정: 브라우저를 열기 전에 재사용 가능 여부를 먼저 본다. 실 worker 재측정:

```
수정 전 41.1초  ->  수정 후 23.8초  (2건 기준)
물건당 15.8초 -> 0.002초, 492회 기준 약 130분 절감
정합 유지: status.html 바이트 동일, READY x2, doc_raw 2행, 큐 done x2
```

`test_asset_pipeline.py` §12-E가 **호출 순서**를 고정한다(결과 기반 검사로는 못 잡는다).

### Sprint 146 보고의 오류 정정 — 큐 고아 "0건"은 틀렸다

Sprint 146이 "대응 auction_item 이 없는 큐 행 0건"으로 보고했는데, 그 측정 쿼리가
**법원을 빼고 조인**해서 나온 값이다. 법원을 포함하면 **18행**이다.

```
안산지원 2025타경497 / 고양지원 2024타경2803 / 성남지원 2024타경4973
포항지원 2024타경4705 / 부산동부지원 2023타경5187 / 고양지원 2024타경8092
  (6물건 x 3종류, 상태: pending 12 · done 3 · SKIPPED_EXPIRED 3)
```

`cleanup_orphans_dryrun.py`의 docstring이 이미 **"document_queue 고아 18행"**이라고
적어 두고 있었다 — 기존 문서와 대조했다면 바로 잡혔을 오류다.
전부 기일이 과거라 worker가 `SKIPPED_EXPIRED`로 조용히 종결한다(무해).

### BUGS #103 수정을 운영 DB 실데이터로 회귀검증

```
법원 간 (사건,물건) 중복 조합                     0
큐가 '다른 법원' 물건과 매칭되는 행                18 (pending 12)
  -> 수정 후 자기 법원 물건을 못 찾아 정정 생략     18
  -> 다른 법원 날짜로 덮어쓰는 경우                 0
이미 오염된 흔적                                  0
court_code 없이 호출 시                          정정하지 않음(안전판 동작 확인)
```

### 품질 게이트

```
Python test_*.py   32개 중 31 PASS (실패 1 = 신규 파일 미커밋 검사, Commit 금지)
test_asset_pipeline.py  30그룹 PASS (Sprint 147에 §12-E 추가)
tsc 0 / eslint 0 / next build 성공 / compileall 0
```

---

## 2026-08-17 Sprint 148 — 미착수 Backlog 정리 / 미수행 Audit 영역 순회

Sprint 147이 "다음 Sprint 후보"로 올린 `parsed_document`부터 시작해, 그동안 손대지 않은
감사 영역(Dependency / Failure Recovery / Payment / Documentation Drift)을 순회했다.

### `parsed_document` — **이미 조사·결정이 끝난 항목이었다** (중복 작업 회피)

Sprint 147 보고서가 "다음 Sprint: parsed_document 파이프라인 조사"를 제안했는데,
착수 전에 기존 문서를 대조하니 **이미 끝난 조사**였다:

```
BUGS #49 (2026-08-11 Sprint 55)  parsed_document / rights_analysis_history
                                 각 0행, 읽기 0곳, 쓰기 0곳 = 죽은 테이블
roadmap 16-C                     "죽은 테이블 정리" — 삭제는 승인 영역
roadmap §5 (파싱 착수 준비)        "쓰는·읽는 코드가 0곳인 죽은 테이블이라
                                  그대로 쓸지 새로 만들지도 결정 대상"
```

즉 막고 있는 것은 조사가 아니라 **제품 결정**이다(파싱 파이프라인을 만들 것인가).
2026-08-17에 주장이 아직 사실인지만 재확인했다 — **두 표 모두 0행, 프로덕션
INSERT/UPDATE/SELECT 0곳**으로 여전히 유효하다. 새 Sprint를 만들지 않았다.

### Dependency Audit (이 세션에서 처음 수행)

```
requirements.txt 선언 11개  ->  설치 버전 11/11 일치, 누락 0
프로덕션 코드의 서드파티 import  ->  미선언 0개
```

`uvicorn`/`httpx`/`cryptography`는 직접 import되지 않지만 각각 서버 실행·TestClient·
python-jose가 쓰므로 선언이 옳다(기존 문서의 설명과 일치).

**★ npm 취약점 전제 재검증**: `npm audit`이 `sharp`(libvips CVE 4건)/`postcss`를
계속 보고한다. Sprint 124가 *"이 저장소는 `next/image`를 쓰지 않으므로 sharp 경로에
도달하지 않는다"*로 결론냈는데, **Sprint 144/145가 이미지 기능을 추가했으므로 그 전제가
깨졌을 수 있어** 다시 확인했다:

```
next/image import  0건   (검색 결과는 전부 "쓰지 않는다"는 내 주석과 proxy matcher 문자열)
실제 사용            <img> 4곳 — 전부 순수 HTML 태그
```

전제는 **여전히 유효하다**. 사진 기능을 넣으면서 의도적으로 `next/image`를 피한 결과다.

### Failure Recovery Audit — 커버리지 공백 0

13개 시나리오(브라우저 크래시 / 드라이버 재시작 실패 / 워커 중복 실행 / stale 회수 /
재시도 소진 / 미지원 무한재시도 / 기일경과 종결 / 빈 캡처 거부 / 0바이트 거부 /
이미지 실패 재시도 / 재실행 중복 다운로드 / 원자적 쓰기 / 트랜잭션 롤백)를
테스트 소스와 대조한 결과 **전부 커버돼 있다**.

### Payment / Subscription / Registry — 전부 비어 있음(출시 전 상태)

```
payments 0 · payment_logs 0 · payment_webhooks 0 · subscriptions 0
registry_requests 0 · registry_usage 0 · registry_credits 0 · audit_logs 0
알 수 없는 상태값 0 · 고아 참조 0 · COMPLETED인데 doc_url 없음 0
```

### `recent_items`에 남은 테스트 잔여물 25행 (역사적 잔재)

```
user_id = 'leaked-user'   25행   전부 2026-08-13T14:34:29 (단일 배치)
```

현재 저장소 어디에도 이 값을 만드는 코드가 없다 — 2026-08-13 시점의 옛 테스트가 남긴
것이고, 그 테스트는 이후 무작위 `qa-reg-*` 접두 + 명시적 정리로 바뀌었다.
**현재 테스트는 잔여물을 남기지 않는다**(실측: `test_api_regression.py` 실행 전후
recent_items 34행 그대로, `qa-` 접두 0행, 다른 표도 전부 0 유지).
삭제는 운영 데이터 삭제라 승인 영역 — 기록만 남긴다.

★ 이 감사 중에 **내 E2E 브라우징이 운영 `recent_items`에 4행을 남긴 것**도 확인했다
(2026-08-17, item 502/11855/111/58). 로그인 상태로 실제 상세페이지를 열었으므로
기능상 정상 동작이지만, 검증 작업이 운영 데이터를 건드린다는 사실은 기록해 둔다.

### ★ Documentation Drift — 내 변경이 만든 드리프트 (정정 완료)

```
부트스트랩 테이블 수   문서 25개  vs  실제 26개
```

Sprint 144가 migration 020으로 `auction_image`를 추가하면서 바뀐 값인데, 그때 문서를
갱신하지 않았다. `test_bootstrap.py`가 이 수를 **하드코딩하지 않고 실측해 출력**하는
설계라 테스트가 깨지지 않았고, 그래서 조용히 남아 있었다.
`docs/BUGS.md` #49와 `docs/roadmap.md` 16-C를 정정했다(두 곳 모두 "삭제하면 테이블 수
기록이 바뀐다"는 판단의 근거로 그 숫자를 쓰고 있었다).

그 밖의 핵심 수치는 전부 일치했다:
`auction_item 1,876` / `doc_raw 556` / `auction_image 45` / `document_queue 3,498` /
`documents 767파일` / `CLAUDE.md의 마이그레이션 001~020`.

### 품질 게이트

```
Python test_*.py   32개 중 31 PASS
tsc 0 / eslint 0 / next build 성공 / compileall 0
Dependency  선언-설치 11/11 일치, 미선언 import 0
```

유일한 실패는 `test_schema_hygiene.py`의 **"링크된 storage/ 소스는 git이 추적된다"** 항목이고,
원인은 코드 결함이 아니다:

```
storage/ 소스 25개 중 24개 tracked
미추적 1개 → storage/migrations/020_create_auction_image.sql   (?? untracked)
```

Sprint 144에서 내가 만든 마이그레이션이다. `auction_image` 테이블을 만드는 **실동작
소스**인데 git에 없으므로, 다른 환경에서 부트스트랩하면 001~019만 적용되고 020이 빠져
`auction_image`가 생성되지 않는다(= 이미지 레이어 전체가 죽는다). 테스트는 정확히 이
상황을 잡으라고 만들어진 것이므로 **이 실패는 올바른 동작이다.**

해소 방법은 `git add` 뿐인데 **Commit/add 금지가 상시 제약**이라 SKIP한다.
사용자가 커밋하는 순간 이 테스트는 별도 수정 없이 PASS로 돌아온다.

---

## Sprint 148 Release Audit — 승인 블로커가 1건에서 2건으로 늘었다

이전까지 릴리스 블로커는 스케줄러 미등록 1건이었다. 이번 감사에서 **2번째**가 나왔다.

### 블로커 1 — 스케줄러 미등록 (기존)

249개 작업 중 이 저장소를 참조하는 것이 0개다. 살아있는 물건이 9건뿐이고 전부
2026-08-19 날짜라, **2026-08-20부터 검색 결과가 0건이 된다.**
해소는 `.\register_scheduler_tasks.ps1 -Apply` — 사용자 환경 변경이라 SKIP.

### 블로커 2 — 미추적 파일 14개 (BUGS #105, 이번에 발견)

Sprint 144~146에서 만든 실동작 모듈이 아직 `git add`되지 않았다. Commit 금지가
상시 제약이라 의도된 상태지만, **추적 파일이 미추적 파일을 import한다**는 것이 문제다.

`git ls-files`로 추적 파일 297개만 임시 디렉터리에 복사해 `git commit -a` 직후
상태를 그대로 재현한 뒤 부팅을 시도했다 — 추론이 아니라 실측이다:

```
$ python -c "import api_server"
ModuleNotFoundError: No module named 'api.http_cache'   (api/v1/documents.py:6)
```

라우터 등록 단계에서 죽으므로 **검색/상세/문서/이미지 전 기능이 동시에 정지**한다.
깨지는 간선 4개:

```
api/v1/documents.py:6            -> api/http_cache.py
api_server.py:32                 -> api/v1/images.py
crawler/doc_crawler.py:619       -> crawler/image_crawler.py
src/app/search/ResultList.tsx:5  -> src/app/search/ResultThumbnail.tsx
```

여기에 마이그레이션 020이 빠지면 `auction_image` 테이블이 생성되지 않아 이미지
레이어도 함께 죽는다.

**해소**: `git add -A` 후 커밋. **`git commit -a`나 파일을 골라서 하는 커밋은
쓰면 안 된다.** add/commit 전부 승인 영역이라 SKIP한다.

### 이번에 닫은 것 — 탐지 공백

`test_schema_hygiene.py`에 §6-B(추적 파일→미추적 파일 import 간선 검사)를 신설했다.
기존 §6은 `storage/`만 봐서 14개 중 1개만 잡았다. §6-B는 하드코딩 없이 git에 직접
물어보고, 미추적 소스 10개 대상으로 추적 파일 143개를 훑어 **간선 4개를 전부 재발견**했다
(오탐 0). 실패 출력에 간선 목록과 해소 방법이 그대로 찍힌다.

이 검사는 **의도적으로 현재 FAIL**이다. 커밋하는 순간 테스트 수정 없이 PASS로 돌아온다.

### 게이트 재실행

```
Python test_*.py   32개 중 31 PASS   (실패 1 = 위 §6-B, 승인 영역)
tsc 0 / eslint 0 / next build 성공 / compileall 0
```

파일이 늘지 않았다 — §6-B는 이미 실패 중이던 `test_schema_hygiene.py` 안에 넣어
실패 1건의 **내용을 정확하게** 만든 것이지 실패를 새로 만든 것이 아니다.

### Sprint 148 Frontend Audit — 만료 D-3 화면을 미리 렌더시켜 봤다

블로커 1(스케줄러)은 승인 영역이라 고칠 수 없지만, **그 결과로 나올 화면**은 지금 고칠 수 있다.

```
2026-08-17 실측: 미래 물건 9건, 전부 2026-08-19  ->  08-20부터 기본 검색 0건
```

그 상태의 화면을 실제로 띄워 보니 안내가 틀려 있었다(BUGS #106). 결과 0건의 원인을
항상 사용자 조건으로 단정해서, 재고가 0일 때도 "검색조건을 줄여보세요"라고 말하고
"조건 없이 전체 물건 보기" 링크를 준다 — **이미 조건 없는 화면이라 같은 빈 화면으로
되돌아오는 막다른 길**이다. 사용자가 빠져나갈 동선이 없다.

`SearchScreen`이 조건 유무를 계산해 넘기고 `ResultList`가 두 상태를 가르도록 고쳤다.
`/`와 `/search`가 같은 `SearchScreen`을 쓰므로 한 번의 수정으로 둘 다 해소된다.

검증은 빌드 통과로 끝내지 않았다 — 이 프로젝트엔 이미 "빌드는 통과하는데 화면이 죽는"
사고(서버 컴포넌트 `onError`)가 있었다. `DB_PATH`가 cwd 상대경로이고 API base가
환경변수라, **운영을 건드리지 않고** 만료 상태를 통째로 재현할 수 있었다:

```
auction.db 사본에서만 미래 9건 삭제 -> 사본 cwd로 API를 8010에 기동(total:0)
NEXT_PUBLIC_API_BASE_URL로 dev 서버를 3010에 기동 -> 렌더된 HTML을 직접 확인
```

네 경우 전부 의도대로였다(조건없음+0건 / 정렬만+0건 / 조건있음+0건 / 결과있음).
검증 후 서버 종료·사본 삭제했고 **운영 DB는 무변경**(1,876 / 9 / 556 / 45 그대로).

### Sprint 148 Security Audit — 라우트 전수를 무인증으로 실제 호출해 봤다

정적으로 `dependencies`를 읽는 방식은 **틀렸다**. 이 FastAPI 버전은 include된 라우터를
`_IncludedRouter`로 감싸고 `.routes`를 노출하지 않아, `app.routes`를 재귀로 훑으면
42개 중 2개만 잡힌다(내가 처음에 이렇게 세어 "총 2개"라는 헛수치를 냈다).
**`app.openapi()`가 등록 표면의 authoritative 소스**다 — 42개 오퍼레이션.

GET 29개를 무인증으로 실제 호출했다(GET만 — POST/DELETE를 무인증 호출하면 보호가
없을 경우 운영 데이터가 바뀌므로 정적 확인으로 대체했다):

```
401 요구  10개   favorites / payments(3) / recent-items / registry-requests(3) /
                 search-presets / subscriptions.me
공개      6개    / , /api/v1/search , /api/v1/item/{id} , /api/v1/stats ,
                 /api/v1/plans , /api/v1/document-stats     ← 설계상 비인증 경로
입력거부  3개    400 / 404 / 422 (문서·이미지·regions — 값이 없거나 잘못된 것)
500       10개   /api/v1/admin/*
```

**admin 10개의 500은 취약점이 아니라 fail-closed다.** 이 환경에 `ADMIN_API_KEY`,
`SUPER_ADMIN_API_KEY`가 둘 다 없어서 `_require_role`이 인증 이전에 500으로 끊는다.
데이터는 한 바이트도 나가지 않는다(응답 36B = 에러 봉투).

문제는 그 500이 **인증 로직 자체가 맞는지를 가린다**는 점이다. 그래서 키를 프로세스
환경변수로만 넣고(.env 미수정) 역할 매트릭스를 전수 실행했다:

```
route(admin GET 10개)      키없음  틀린키  ADMIN  SUPER
                            403     403    200    200
/admin/payments/{id}/logs   403     403    404    404   ← 없는 결제건, 누출 아님
```

전 라우트가 의도대로였다. 부수 확인도 통과:

```
hmac.compare_digest 사용     True    (타이밍 사이드채널 차단)
단순 ==/!= 키 비교           False
실패 로그에 키 값 기록        없음 ("미제공"/"불일치"만)
```

회귀도 이미 있다 — `test_api_regression.py`가 틀린 키 403과 ADMIN/SUPER 분리를 고정한다.
**이 영역은 추가 조치 없음.**

### Sprint 148 Data/Pipeline 재측정

```
document_queue  3,498 = pending 2,753 / done 559 / SKIPPED_EXPIRED 186
document_status 5,628 = COLLECTING 5,069 / READY 556 / FAILED 3
auction_item 1,876   auction_case 1,384   doc_raw 556   auction_image 45
documents/ 767파일 / 1.29 GB / 파일있는 디렉터리 210개
```

**COLLECTING 5,069는 멈춘 것이 아니다.** `1,876 물건 x 3 doc_type = 5,628`이고
COLLECTING이 초기값이다(5,069 + 556 + 3 = 5,628, 정확히 일치). "수집중"이 아니라
"아직 수집 안 됨"으로 읽어야 한다.

**pending 2,753의 실체** — 대부분 실작업이 아니다:

```
만료(스킵 대상)  2,736      살아있음(실작업)  17      날짜 없음  3
```

#104 수정 후 물건당 약 24초이므로 실작업 17건은 7분 남짓이고, 만료 2,736건은 건당 5ms
수준으로 빠진다. 큐 자체는 병목이 아니다.

**큐 고아 18건** (= 6사건 x 3문서, 전부 매각기일이 지난 건). 15행은 `auction_case`
자체가 없고, 3행은 사건은 있는데 그 물건번호가 없다(고양지원 2024타경2803, done —
`documents/고양지원/2024타경2803/1`에 파일 4개가 남아 있으나 대응 물건이 없어 API로
도달 불가). pending 12행은 전부 만료라 다음 실행에서 SKIPPED_EXPIRED로 자연 해소된다.
사용자 노출 영향 없음.

**★ 이 감사의 본 소득은 고아가 아니라 그것을 세다가 나온 것이다** — 법원 없는 식별키가
프로덕션 코드에 두 곳 더 남아 있었다(BUGS #107). 같은 계열이 #18/#14/#103으로 세 번
반복됐는데 매번 인스턴스만 고쳤기 때문이다. 이번엔 계열 전체를 막는 회귀를 넣었다
(`test_auction_identity.py`, 추적 .py 77개의 큐 쓰기 13문장 검사, 위반 0).

덫이 실재한다는 증거도 함께 남긴다 — case_no 3개가 두 법원에 걸쳐 있고 물건 22건이
연루된다. 이 감사에서 나 자신도 다시 걸렸다(법원 뺀 조인 15건 vs 넣은 조인 18건).

### Sprint 148 Performance Audit — 성능은 병목이 아니다(그러나 감사 중 버그가 나왔다)

검색 10종 x 5회, 단건 5종 x 5회를 TestClient 인프로세스로 실측했다(중앙값):

```
기본(무필터)      3.2ms      깊은 페이지(50)   4.7ms      지역 필터    3.5ms
가격 범위        4.0ms      정렬 감정가       3.2ms      정렬 최저가   3.2ms
복합(지역+가격+정렬) 3.7ms   size=100        5.4ms      주소 부분검색  4.3ms
상세 item 2.9ms / 이미지 3.1ms / stats 2.5ms / document-stats 3.4ms
```

전부 중앙값 200ms 이내이고 최대값도 20ms를 넘지 않는다. `auction_item`이 1,876행이라
현재 규모에서 인덱스 추가나 쿼리 재작성으로 얻을 것이 없다. **백로그의 TEMP B-TREE
정렬 인덱스 건은 지금 착수할 이유가 없다** — 정렬 쿼리가 3.2ms다. 데이터가 10배 이상
늘어난 뒤 다시 재면 된다.

**★ 이 감사의 소득도 성능이 아니라 버그였다** — 측정 중 READY 물건에 `/documents/status`가
400을 뱉는 것을 발견했다(BUGS #108). `document_status`는 대문자, `document_queue`는
소문자로 같은 개념을 저장하는데 API가 대문자만 받았다. 화면은 대문자 쪽에서 값을 받아
쓰기 때문에 여태 드러나지 않았다. 경계에서 정규화하도록 고쳤다.

### 이번 사이클에 내가 만든 사고 하나 (기록)

`python test_api_regression.py | grep | head -10`으로 실행했다가 `head`가 파이프를 닫아
**SIGPIPE로 테스트가 중간에 죽었고, 픽스처 정리 루틴이 실행되지 않아** 운영 DB에
`qa-*` 행이 남았다(registry_requests 26 / registry_usage 5 / payments 4 / subscriptions 4).
다음 실행의 정리 루틴이 걷어내 지금은 0행이고 전체 스위트도 31/32로 정상이다.

두 가지를 기록해 둔다.

1. **긴 테스트를 `head`로 자르지 말 것.** 파이프가 닫히면 정리 코드가 실행되지 않는다.
   파일로 받아서 검색해야 한다.
2. **`test_api_regression.py`는 운영 `auction.db`에 픽스처를 쓰고 끝에 지운다.** 정상
   종료에서는 문제없지만 중단되면 운영 DB에 잔여물이 남는 구조다. 이 테스트 자신도
   과거 수동 QA가 남긴 `qa-download-001` 같은 행을 감지하는 검사를 갖고 있다(같은 사고가
   전에도 있었다는 뜻이다). 임시 DB로 분리하는 것은 규모가 큰 변경이라 착수하지 않고
   위험만 기록한다.

### Sprint 148 Recovery/Failure Audit

**재시도 정책은 건전하다.** `mark_queue_failed()`는 `retry_count+1 < MAX_DOC_RETRY`면
pending으로 되돌리고, 소진되면 `failed` + 화면 `FAILED`로 종결한다. **중간 재시도는
화면에 노출하지 않는다** — 다음 시도에 성공할 문서가 잠깐 "실패"로 보였다 돌아오는 것을
막는 의도된 설계다. 성공 불가 항목이 `reset_stale_queue()`의 부활 고리에 갇히는 문제도
이미 `SKIPPED_UNSUPPORTED` 계열로 끊어 놨다(큐에 해당 행 0건 = 그 경로가 정리된 상태).

**FAILED 3건의 실체**: 전부 item 14 하나(서울동부지방법원 2022타경55450-7, 기일 2026-07-06)
이고 사유는 `document_collect_failures`에 "상세페이지 진입 실패"로 남아 있다. 이 물건은
큐 행이 아예 없어 되살아날 경로가 없지만, 기일이 지난 물건이라 사용자 영향은 없다.

**전역 정합성 — 모순 쌍 0건**:

```
document_status  <->  document_queue
READY       <-> done              556
COLLECTING  <-> pending          2741
COLLECTING  <-> SKIPPED_EXPIRED   183
(READY<->pending, FAILED<->done 같은 모순 조합 없음)
```

**큐 행이 없는 document_status 2,148건**(COLLECTING 2,145 / FAILED 3)은 화면에서 영원히
"수집중"이 되는 부류다. 그런데 **그중 매각기일이 남은 것은 0건**이다 — 전부 만료 물건이라
사용자에게 보이지 않는다. 숨은 공백은 없다.

**지금 사용자에게 보이는 9건의 문서 상태** (운영상 알아 둘 값):

```
완전 수집   2건   item 502, 505 (SPEC/STATUS/APPRAISAL 전부 READY)
부분 수집   1건   item 11853 (STATUS만 READY)
미수집     6건   item 1533, 11854, 11855, 11856, 11857, 11858
```

7건이 문서 자리에 "수집중"을 보여 준다. 큐에는 pending으로 들어 있으므로 doc_worker가
돌면 채워진다 — 즉 이것도 **블로커 1(스케줄러 미등록)의 증상**이다. 오늘 수동 실행으로
채울 수도 없다: 실행 창이 04:00까지라 14시엔 한 건도 처리하지 않는다.

**★ 이 감사에서 결함 2건이 나왔다 (BUGS #109, 둘 다 수정)**

1. 실행 창 밖에서도 Selenium을 띄운 뒤 루프 첫 조건에서 빠져나왔다. 락 검사에는
   "어차피 못 할 실행에 기동 비용을 쓰지 않는다"는 원칙이 적혀 있는데 시간 검사에는
   적용돼 있지 않았다.
2. **`build_download_driver()`가 락 해제를 보장하는 두 구간 사이에 있었다.** 기동이
   실패하면 락이 남는다 — 재현해서 죽은 PID가 남은 것을 확인했다. `LOCK_STALE_HOURS=5`
   덕에 영구 정지는 아니지만, 하필 곧바로 재시도해야 할 5시간 동안 후속 실행이 전부
   "이미 실행 중"으로 건너뛰어지고 그것이 **종료코드 0(성공)으로 보고**된다.

둘 다 고치고 회귀 2개를 신설했다(`test_doc_worker_recovery.py` 6·7번). 6번은 결함을
일부러 되돌려 FAIL하는 것까지 확인했다.

### Sprint 149 — #109 계열 전수 검색 + TODO 탐색

**TODO/FIXME/HACK 9건** — 실질은 3건이고 전부 `SearchForm.tsx`의 미지원 필터다
(건물면적/토지면적/특수조건). 프론트는 파라미터를 보내는데 백엔드가 읽지 않는다.
이미 `test_search.py`가 "백엔드가 무시한다 + 프론트에 TODO 표시가 남아 있다"를 고정하고
있어 관리되는 공백이다.

**구현 가능성을 실측했다** — 데이터가 있으면 API만 추가하면 되므로 승인이 필요 없다.
결과는 반대였다:

```
auction / auction_item 의 면적 관련 컬럼   없음
크롤러·정규화·검증에 면적/특수조건 처리 코드  없음
```

크롤러 → 스키마 → API 전 계층에 없다. 스키마 변경이 필요하므로 **SKIP**(승인 영역).
사용자에게는 "동작하지 않는 필터"가 보이지만, 컨트롤을 감추거나 비활성화하는 것은
제품 판단이라 임의로 하지 않는다.

**#109 계열 전수 검색 (AST)** — 자원 획득 53곳을 훑었다.

```
1차 규칙(획득 직후가 try가 아니면 의심)      12곳  -> 전부 오탐
   `conn = get_connection()` 다음이 `inserted = 0` 같은 상수 대입이라 예외 불가
2차 규칙(사이 구문 중 예외 가능한 것만)       5곳  -> 전부 오탐
   `conn.row_factory = sqlite3.Row` + 프로세스 종료로 정리되는 일회성 스크립트
```

`storage/database.py`의 커넥션 획득은 전부 제대로 보호돼 있다. **#109는 유일한
실사례였다** — 다만 검사기가 "즉시 반환이니 호출자 책임"으로 건너뛴 곳에 한 겹 더
깊은 같은 계열이 있었다(BUGS #110, 수정 완료): `build_download_driver()`가 크롬을
띄운 뒤 `set_page_load_timeout()`이 실패하면 프로세스가 고아로 남는다. #109 수정으로
락은 풀리지만 좀비 크롬은 그대로여서, 재시도마다 하나씩 쌓인다.

`crawler/doc_crawler.py`는 커버리지 0%지만 이 함수만은 selenium 진입점을 갈아끼워
실브라우저 없이 검증했다(예외 전파 + quit 1회).

### Sprint 150 Architecture/Debt Audit

**AST 전수 검사 결과** (추적 프로덕션 .py 77개):

```
미사용 최상위 import      5건  ->  실질 1건
참조 없는 공개 함수       19건  ->  실질 1건
등록 안 된 APIRouter       0건
```

19건 중 18건은 FastAPI 라우트 핸들러다 — 데코레이터로 등록돼 프레임워크가 부르므로
이름 참조가 없는 것이 정상이다(오탐). import 5건 중 4건은 `crawler/doc_crawler.py`의
`# noqa: F401 (하위 호환 재노출)`로 **의도가 소스에 명시**돼 있다.

실질 2건만 정리했다:

- `storage/database.py:get_auction_images()` **제거**. Sprint 144에 "API 전용 조회"
  헬퍼로 만들었는데 끝내 아무도 부르지 않았다(참조 0건, 테스트 포함). 실제로 사진을
  읽는 곳은 `api/v1/item.py:58`이고 같은 SQL을 인라인으로 갖고 있다. 이 저장소는
  리포지토리 계층 없이 라우터가 직접 조회하는 구조라, 이 헬퍼만 홀로 다른 규칙을
  따르면서 "여기에 조회 계층이 있다"는 잘못된 신호를 주고 있었다.
- `api/v1/payments.py`의 `WEBHOOK_FAILED` **미사용 import 제거**(형제 두 상수는 쓴다).

### ★ 새로 발견: 저장소 안에 1.4 GB 짜리 낡은 worktree

```
git worktree list
  .../dojoonpass                                          21430db [master]
  .../.claude/worktrees/sprint95-false-success-audit       c4f74e6 [worktree-...]

du -sh  ->  1.4 GB
```

`c4f74e6`은 현재 HEAD보다 4커밋 뒤진 옛 상태이고, 저장소 전체 사본(`auction.db` 포함)을
품고 있다. 세 가지가 문제다.

1. **1.4 GB가 OneDrive 동기 대상**이다.
2. **검색을 오염시킨다** — 이번 감사에서도 `grep -r`이 `.claude/worktrees/` 안의 옛
   사본을 함께 물어 왔다(`WEBHOOK_FAILED` 조회에서 실제로 발생). `git ls-files` 기반
   검사는 영향이 없지만, 평범한 grep은 **옛 코드를 현재 코드로 착각하게 만든다.**
   docs/CLAUDE.md가 경고하는 `Desktop\기타\dojun-pass`(옛 auction.db 보유)와 같은 종류의
   함정이 저장소 **안에** 하나 더 있는 셈이다.
3. `git status`에 뜨지 않아 존재를 알아채기 어렵다(별도 worktree이므로).

제거는 `git worktree remove`(파일 삭제)라 **승인 영역이라 SKIP**한다. 대신 위험만
기록한다. 앞으로 이 저장소에서 전수 검색을 할 때는 `git ls-files`를 쓰거나
`.claude/worktrees`를 명시적으로 제외해야 한다.

### Sprint 151 E2E 재검증 — DB / filesystem / API / 실화면 전수 대조

Sprint 148~150에서 documents API(대소문자 정규화)와 `database.py`(죽은 헬퍼 제거)를
건드렸으므로 자산 전달 경로를 실데이터로 다시 훑었다.

```
1. document_status READY 556행
     파일 없음 0 / 0바이트 0 / API != 200  0
2. 비READY 표본 400개 -> 200을 준 것  0        (누출 없음)
3. auction_image 45행
     파일 없음 0 / 크기 불일치 0 / API != 200  0
4. 반대 방향(파일은 있는데 READY 행 없음)      3개
     documents/고양지원/2024타경2803/1/{spec.pdf, appraisal.pdf, status.html}
```

4번 3개는 Sprint 148에서 이미 특정한 큐 고아(사건은 있으나 그 물건번호가
`auction_item`에 없음)와 **같은 건**이다. 새 문제가 아니고, 대응 물건이 없어 API로
도달할 수 없으므로 잘못된 문서가 노출될 위험도 없다. 파일 삭제는 승인 영역이라 SKIP.

### ★ 살아있는 9건은 사진이 전부 있다 (이전 기록 보완)

Sprint 148에서 "9건 중 문서 완전 수집 2건"만 적었는데, **사진 기준으로는 9/9가 READY**다.
경매 사이트에서 가장 먼저 보는 자산이 사진이라는 점에서 체감이 크게 다르다.

```
item  502   사진 5장 READY   문서 SPEC/STATUS/APPRAISAL
item  505   사진 5장 READY   문서 SPEC/STATUS/APPRAISAL
item 11853  사진 5장 READY   문서 STATUS
item 1533 / 11854~11858 (6건)  사진 5장 READY   문서 없음
```

`auction_image` 45행 = 9물건 x 5장으로 정확히 떨어진다.

### 실제 브라우저 확인 (goal 7)

dev 서버를 운영 데이터에 붙여 실제로 렌더시켰다.

- **item 502 상세** — 사진 5장(실물 4 + 도면 1) 갤러리, 권리분석 신뢰도 HIGH
  (정보원 `STATUS ✓ 확보` / `SPEC ✓ 확보`), 임차인 상세, 관련 문서 3종이
  "수집완료 + 새 탭"으로 노출.
- **PDF 뷰어** — 매각물건명세서를 열어 **서울중앙지방법원 2024타경3528 실문서**가
  그대로 렌더되는 것을 확인(1/2쪽 이동, 썸네일). 상세페이지가 보여 준 임차인
  (정진우/피오니, 전입 2020.10.15, 확정 2024.10.02)이 PDF 표 안의 값과 일치했다 —
  크롤러가 저장한 파일과 파싱해 넣은 DB가 같은 물건을 가리킨다는 뜻이다.
- **item 1533(문서 미수집)** — 사진 5장은 정상 노출되고, 관련 문서 3종은 링크 없이
  "수집중"으로만 표시된다. 깨진 링크도 404도 아닌 정직한 축약이다.
- 앱 콘솔 오류 **0건**(경고 2건은 크롬 확장 프로그램에서 나온 것).

법원 원천 -> crawler -> filesystem -> DB -> API -> 화면 -> PDF 뷰어까지 한 줄로 이어지는
것을 눈으로 확인했다. 검증 후 dev/API 서버를 종료했다.

### Sprint 152 Documentation Drift Audit — 실제 드리프트 0건

문서에 박힌 수치를 실측과 대조했다. `★차이`로 뜬 4건은 전부 **오탐 또는 정당한 과거 기록**이었다.

```
BUGS.md / decision-log.md "테이블 11개"
   -> 총 테이블 수가 아니라 "auction_item.id를 참조하는 자식 테이블 11개". 내 정규식이 느슨했다.
CURRENT_STATE.md "부트스트랩(001~017)"
   -> 마이그레이션이 17개이던 시점의 Sprint 기록. 과거형 서술이므로 정정 대상이 아니다.
CURRENT_STATE.md "001~019만 적용되고 020이 빠져"
   -> BUGS #105 본문. 020이 없을 때 무슨 일이 나는지 설명하는 문장이라 맞다.
```

실측 기준값(2026-08-17): `auction_item 1,876` / `auction_case 1,384` / `doc_raw 556` /
`auction_image 45` / `document_queue 3,498` / `READY 556` / 테이블 26 / 법원 60 /
마이그레이션 20(020이 최종) / documents 767파일 1.29GB / 테스트 추적 32·디스크 36.

### Sprint 153 Search Audit — GREEN

필터가 "0건을 준다"가 아니라 **틀린 행을 섞어 주는가**를 봤다(후자가 훨씬 위험하다).

```
필터 10종  최저가/감정가 상하한, sido, 유찰횟수 상하한, 입찰가율, 기일 상하한, 법원
           -> 반환된 행 전부가 조건을 만족  (위반 0)
정렬 4종   최저가 asc/desc, 감정가 desc, 기일 asc  -> 실제 정렬돼 있음
페이지네이션 7페이지 x 50 = 350행, 중복 0 / 고유 350  (누락도 겹침도 없음)
```

`sido`는 처음에 위반 100건으로 나왔는데 **내 단정이 틀린 것**이었다. DB는 `'서울'` 같은
짧은 형태로 일관되게 저장하고(17종, 혼재 없음) API가 `extract_sido()`로 입력을 정규화한
뒤 정확히 일치시킨다. `sort_by=id`가 400이던 것도 허용 목록에 없는 값을 명시적으로
거부하는 의도된 동작이었다(내 테스트의 실수).

`sido`가 빈 문자열인 3행은 지역 필터로 도달할 수 없다(기록만 남긴다).

### Sprint 153 — 저장소 진단 도구 전수 실행

`cleanup_orphans_dryrun` / `detect_stale_region_contamination_dryrun` /
`measure_endless_collecting` / `empty_doc_dirs_dryrun`을 모두 돌렸다. 내 측정과 전부 일치했다
(큐 고아 18건, 지역 오염 0건, 끝나지 않는 '수집중' 2,328건이나 **사용자 노출 0건**).

**★ 그 과정에서 결함 2건이 나왔다 (BUGS #111, #112 — 둘 다 수정)**

1. `empty_doc_dirs_dryrun`이 보고한 숫자가 눈에 걸렸다 — 빈 물건 디렉터리 1,674 + 파일
   있는 202 = **정확히 1,876 = auction_item 행수**. 우연이 아니라 전수 스캔이 만든 것이다.
   범인은 `repair_empty_status_capture.py`로, 읽기 전용 스캔에서 `get_doc_dir()`
   (=`os.makedirs()`를 부른다)을 물건마다 호출하고 있었다. 저장소가 2026-08-14에 이미
   겪고 함수를 둘로 쪼개 `doc_exists()`를 고친 사고인데, **이 호출부에만 적용이 빠져 있었다.**
2. 그 교훈대로 `get_doc_dir` 호출부를 전수로 훑자 `repair_document_status.py`에
   **경로 규칙 세 번째 사본**이 나왔다. docstring은 "동일한 규칙"이라 주장하지만 그 사이
   규칙이 역슬래시·`..` 처리까지 확장돼 실제로는 갈라져 있었다.

두 결함 모두 회귀를 넣었고(`test_doc_path_safety.py` 7번 확장 + 8번 신설), 각각
**결함을 일부러 되돌려 FAIL하는 것까지 확인**했다.

### Sprint 154 — 통계 정확성 + N+1 구조 검증

**`/api/v1/document-stats` 11개 키 전부 DB와 일치**했다(불일치 0). 그리고 이 엔드포인트는
`test_api_regression.py`가 **11개 키를 모두** 이미 고정하고 있다 — success 3, failed 3,
total_failures(자기 출처 테이블로 대조), queue 3, total_items.

즉 Sprint 148 Test Gap 감사가 "테스트 없음"으로 분류한 `api/v1/doc_stats.py`는
**거짓 공백**이었다. `api/http_cache.py`에 이어 두 번째다. 모듈명 grep 방식은 "동작을
엔드포인트로 검증하는" 테스트를 놓친다 — 그 감사의 "8개 미커버"는 실제보다 부풀려진 수치다.

**N+1 계측 (요청 1건이 실행하는 SQL 수)**

```
상세 /api/v1/item/502   결과 1건    SQL 7회   (사진 5 + 문서 3을 실어도 고정)
검색 size=20            결과 20건   SQL 3회
검색 size=100           결과 100건  SQL 3회   <- 건수와 무관하게 동일
```

검색은 썸네일을 `item_id IN (?...)`로 배치 조회한다. **N+1 없음.**

검색 쪽에는 쿼리 수를 세는 가드가 이미 있었다(16-B, size 1/20/100 비교). 그러나
**상세에는 없었다** — 상세는 한 물건에 사진 N장 + 문서 3종을 실으므로 사진마다 따로
물으면 조용히 N+1이 된다. 응답 본문은 완전히 같고 쿼리 수만 늘어 **결과 기반 검사로는
절대 잡히지 않는다**(BUGS #104에서 겪은 함정과 같은 계열).

`test_asset_pipeline.py` 16-C를 신설해 구조를 직접 고정했다 — 사진 1장과 8장으로 각각
상세를 호출해 쿼리 수가 같은지 본다(사진 수가 실제로 다른지도 함께 검사해, 픽스처가
같아져 검사가 무의미해지는 것을 막는다).

```
정상    사진 1장 7회 / 사진 8장 7회        -> PASS
주입    api/v1/item.py에 사진당 1쿼리 삽입 -> 8회 / 15회로 FAIL (가드 유효 증명, 즉시 복원)
```

### Sprint 155 Test Gap 재측정 — 모듈명 grep이 아니라 실제 커버리지로

Sprint 148의 Test Gap 감사는 **테스트 소스에 모듈 이름이 등장하는가**로 판정했다.
그 방식은 "동작을 엔드포인트로 검증하는" 테스트를 통째로 놓친다. `coverage.py`로
33개 테스트를 돌려 실측했다.

```
TOTAL 4,001문장 중 739 미커버  ->  82%
```

**Sprint 148이 "미커버"로 분류한 것들의 실제 값**:

```
api/http_cache.py     98%   (test_http_conditional.py가 엔드포인트로 전수 검증)
api/v1/doc_stats.py  100%   (test_api_regression.py가 11개 키를 전부 대조)
api/v1/images.py     100%   /  api/v1/documents.py 100%  /  api/v1/item.py 100%
```

**즉 그 "8개 미커버"는 실제보다 부풀려진 수치였다.** 이 문서의 해당 대목을 읽을 때는
이 정정을 함께 봐야 한다.

한편 docs/CLAUDE.md의 기록은 **정확히 맞았다** — `filter/filter_engine.py` 80%,
`scoring_engine.py`/`report_generator.py` 0%(둘 다 실측 0%). 테스트를 추가하지 말라는
그 문서의 지시도 그대로 유효하다.

낮은 쪽은 대부분 selenium 의존이라 브라우저 없이 올릴 수 없다
(`court_crawler` 24% / `doc_crawler` 38% / `base_crawler` 45%).

**★ 예외가 하나 있었다 — `crawler/image_assets.py` 72%.**

이 모듈은 **selenium·DB·fastapi 무의존인 순수 규칙 모듈**인데 47문장이 비어 있었고,
그중 **webp 크기 읽기(VP8/VP8L/VP8X)는 통째로 0%**였다. 브라우저 없이 채울 수 있는
공백이므로 채웠다(`test_asset_pipeline.py` 1-B 신설, 36검사).

```
crawler/image_assets.py   72%  ->  86%   (미커버 47 -> 24문장)
```

이 저장소는 법원 페이지가 **선언 MIME으로 거짓말하는** 것을 이미 겪었다(image/png이라
적어 놓고 실제로는 JPEG/GIF). 그래서 형식 판정은 매직 바이트로만 하는데, 그 경계값이
검증되지 않고 있었다.

**검사를 만들면서 배운 것 두 가지**

1. **webp 3형식이 전부 통과했다 — 처음엔 실패했지만 코드가 아니라 내 픽스처가 틀렸다.**
   RIFF 청크 크기 4바이트를 빼먹어 본문 오프셋이 어긋나 있었다. 실패를 보고 곧바로
   프로덕션을 고쳤다면 멀쩡한 코드를 망가뜨렸을 것이다.
2. **진짜 결함도 하나 나왔다.** `decode_image_data_uri("data:image/png;base64,@@@@")`가
   `None`이 아니라 `b""`를 돌려줬다. `base64.b64decode(validate=False)`가 알파벳이 아닌
   글자를 조용히 버리기 때문이다. 바로 위 "payload가 비면 None"과 **같은 상황에 다른
   값**을 주고 있었다. 호출부는 `Optional[bytes]`로 성공/실패를 가르므로 `b""`는
   "성공했는데 내용이 없다"로 읽힌다. 하류의 `MIN_IMAGE_BYTES` 검사가 막아 주고 있어
   실제 사고는 없었지만, 경계에서 지키도록 고쳤다.

### Sprint 156 데이터 공급 사슬 — 배관은 완벽, 입력이 5일째 없다

**`auction`(크롤러 기록) ↔ `auction_item`(API가 서빙) 동기화는 완전하다.**
법원을 포함한 정확한 대조에서 양방향 불일치가 0이다.

```
auction 1,876   auction_item 1,876
auction에만 있음 0 건 (= migrate_execute 미실행분 없음)
auction_item에만 있음 0 건
```

즉 CLAUDE.md가 경고하는 "새 크롤 데이터가 `migrate_execute.py` 미실행 때문에 API에
안 보이는" 상태는 **아니다**. 배관에는 문제가 없다.

**문제는 입력이다.** `crawl_date` 이력이 공급 중단 시점을 정확히 짚어 준다.

```
크롤 실행 기록 20일치   최초 2026-07-06  ~  최종 2026-08-12

07-29 o(68)  07-30 o(58)  07-31 o(20)  08-01 o(278)
08-02 . 08-03 . 08-04 . 08-05 . 08-06 . 08-07 . 08-08 . 08-09 . 08-10 . 08-11 .
08-12 o(9)
08-13 . 08-14 . 08-15 . 08-16 . 08-17 .
```

**2026-08-01까지는 매일 돌았고 그 뒤로 멈췄다.** 08-12의 9건은 단발성으로 보인다
(그 9건이 정확히 지금 살아 있는 물건 9건이다). 오늘까지 5일 연속 0건이다.

이것이 **릴리스 블로커 1(스케줄러 미등록)의 실측 서명**이다. 249개 예약 작업 중 이
저장소를 참조하는 것이 0개라는 사실과 정확히 맞물린다. 해소는 승인 영역이라 SKIP하되,
증상은 이제 날짜 단위로 특정된다:

```
2026-08-01  공급 중단 시작
2026-08-12  단발성 9건 (현재 살아있는 물건 전부)
2026-08-19  그 9건의 매각기일
2026-08-20  기본 검색 결과 0건  <- D-3
```

### Sprint 157 — `storage/database.py` 미커버 구간 정밀 확인

87%였고 빠진 50문장을 실제로 읽어 두 갈래로 나뉘었다.

**(1) `query()` — 프로덕션 호출부 0곳 (28문장)**

`storage/database.py:262`의 `query(sido, court_name, auction_date, ...)`를 부르는
프로덕션 코드가 **하나도 없다.** API는 `api/v1/search.py`가 직접 조회하기 때문이다.
유일한 참조는 `test_db.py:70`인데, 그 파일은 실브라우저를 쓰는 라이브 크롤 테스트라
정규 회귀에서 제외돼 있다(`ALLOW_LIVE_CRAWL=1` 없으면 즉시 SKIP).

Sprint 150에 지운 `get_auction_images()`와 같은 계열이지만 **지우지 않았다** — 그쪽은
참조가 0이었고 이쪽은 테스트가 부르고 있다. 지우려면 `test_db.py`도 함께 손봐야 하는데,
그 파일은 라이브 크롤 전용이라 이 세션에서 실행해 검증할 수 없다. 기록만 남긴다.

**(2) `_record_doc_raw()`의 방어 분기 — 채웠다**

빠진 나머지가 하필 **"거짓 성공"을 막는 분기들**이었다. `doc_raw`는 파일의 실체(크기·
버전·쪽수)를 담는 표라 행이 생기는 것 자체가 "실물이 있다"는 주장이 된다. 실물이 없을
때 0으로 채운 행을 남기면 뒤따르는 어떤 검사도 그것을 실물로 오인한다.

`test_asset_pipeline.py` 12-B를 신설했다(7검사).

```
저장했다는 파일이 실제로 없다   -> doc_raw 행 없음, 그래도 큐는 done(무한 재시도 방지)
0바이트 파일                  -> 행 없음
files_saved가 빈 목록          -> 행 없음
doc_type='image'              -> 행 없음 (0~N장이라 1행 표에 못 담는다)
대조군: 실물이 있다             -> 1행, file_size가 실제 크기와 일치
```

대조군을 함께 넣은 이유는 위 네 검사가 "항상 0"이어도 통과해 버리는 것을 막기 위해서다.

```
storage/database.py   87%  ->  88%
```

남은 47문장은 대부분 `query()`(28문장)와 예외 로깅 경로다.

### Sprint 160 Frontend E2E — 인증 화면 3종 실화면 확인

Sprint 151에서 검색/상세/뷰어를 확인했으나 **로그인이 필요한 화면 3종은 미확인**이었다.
운영 데이터에 붙여 실제로 띄웠다(로그인 상태 jab31@naver.com).

```
/favorites          정상. 빈 목록 안내 "관심물건이 없습니다."
/properties/recent  정상. 카드 10건 렌더 (물건종류 배지 / 감정가 / 최저입찰가 / 법원 / 조회일)
                    오늘 내가 연 물건들이 "2026. 8. 17. 조회"로 반영돼 있다
/mypage             정상. 구독 / 결제 내역 / 등기부 신청 / 내 물건 4개 카드,
                    각각 빈 상태 문구와 이동 버튼
콘솔 오류 0건
```

### 발견: 목록 화면 간 썸네일 비대칭 (기록만, 기능 추가라 착수하지 않음)

검색 결과에는 대표 사진이 나오는데(`thumbnail_url`, Sprint 145) **`/properties/recent`와
`/favorites`에는 사진이 없다.** API가 애초에 그 필드를 주지 않는다 —
`api/v1/recent_items.py`는 `SELECT ai.*`만 하고 `auction_image`를 조인하지 않는다.

최근 본 물건 10건 중 사진이 있는 것이 여럿인데(502, 1533 등 각 5장) 목록에서는
텍스트로만 보인다. 같은 물건이 화면마다 다르게 보이는 셈이다.

다만 이것은 **결함이 아니라 미구현**이다. 고치려면 검색이 쓰는 배치 조회
(`item_id IN (?...)` + `MIN(seq)`)를 두 엔드포인트에 옮기고 프런트 카드에 이미지 슬롯을
추가해야 하는데, 이는 요청 범위 밖의 기능 추가다. 백로그로만 남긴다
(N+1을 만들지 않는 방법은 이미 검색 쪽에 있으므로 착수 시 그대로 따르면 된다).

### Sprint 161~162 — 세션 산출물 정리 + 마지막 커버리지 공백

**저장소 오염 없음 확인.** 이번 세션의 검사가 만든 흔적을 전수 확인했다.

```
QA 프로브 디렉터리       없음 (검사가 스스로 지운다)
워커 락 파일             없음
커버리지 산출물(.coverage) 제거함
documents/               3,338 디렉터리 / 767 파일 / 1.29 GB  ← 감사 시작 시점과 동일
```

(`documents_quarantine/20260812_101659`은 2026-08-12 Sprint 62 복구 실행이 남긴 것으로
이번 세션과 무관하다.)

**BUGS #105의 서술 방식을 바꿨다.** 미추적 파일 수가 세션 중 14 → 15 → 16으로 늘었다
(내가 만들지 않은 테스트 파일 `test_crawl_error_log.py`, `test_item_detail_auth.py`가
추가됐다 — 둘 다 통과한다). 숫자를 쫓아 문서를 세 번 고치게 되자, **목록을 문서에 박지
않고 재현 명령만 남기도록** 고쳐 썼다. 판단에 필요한 사실은 개수가 아니라 **깨지는
import 간선 4개**이고, 그것은 파일이 늘어도 그대로이며 `test_schema_hygiene.py` §6-B가
자동으로 다시 계산한다.

**마지막 커버리지 공백 — 사진 저장 실패 경로** (`test_asset_pipeline.py` 6-B 신설).

`_write_image_atomically()`는 임시 파일에 쓰고 `os.replace()`로 바꾼다. 그 이유가
모듈 주석에 적혀 있다 — 목적지에 직접 쓰면 쓰는 도중 죽었을 때 잘린 파일이 남고 다음
수집이 "이미 있다"고 판정해 **깨진 사진이 영구히 남는다**(BUGS #22/#50/#61).

그런데 **실패 경로(`except OSError`)가 통째로 비어 있었다.** 성공만 검증하면 "실패했을
때 뒷정리가 되는가"는 아무도 보지 않는다. 교체 단계를 강제로 실패시켜 고정했다:
False를 돌려주고, 목적지도 `.tmp`도 남지 않는다(정상 경로 대조군 포함 6검사).

### 최종 게이트 (전 변경 반영 후)

```
Python test_*.py   34개 중 33 PASS   (실패 1 = §6-B 미추적 가드, 승인 영역)
tsc 0 / eslint 0 / next build 성공 / compileall 0
API import OK

E2E 재검증 (모든 코드 변경 이후)
  document_status READY 556  파일없음 0 / 0바이트 0 / API!=200  0
  비READY 표본 400            200을 준 것 0
  auction_image 45           파일없음 0 / 크기불일치 0 / API!=200 0
  디스크에만 있는 문서 3개      = 고양지원 2024타경2803 (기존 큐 고아, 신규 아님)
```

### ★ 정정 — 이 세션의 테스트 집계가 부정확했다

세션 내내 셸 반복문으로 `종료코드 0 = 통과`로 세어 **"33 PASS / 1 FAIL"** 이라고
보고했다. `run_python_tests.py`(일괄 실행기)로 정확히 집계하니 다르다:

```
통과 32 | 실패 1 | 건너뜀 3 | 판정없음 1     (전체 37파일, 단언 4,190건, 36.2초)
```

차이의 원인은 **`test_filter.py`** 다. 판정문(단언)이 하나도 없는 진단 스크립트인데
종료코드가 0이라 내 반복문이 통과로 셌다. "통과"가 아니라 **"검증했다고 말할 수 없음"**
으로 분류하는 것이 정직하다.

`test_db.py` / `test_docs.py` / `test_docs2.py` 3개는 내가 명시적으로 제외했으므로
집계에는 안 들어갔지만, 실행기는 이것도 "건너뜀 — 통과가 아니다"로 따로 세운다.
`ALLOW_LIVE_CRAWL=1` 없이는 스스로 SKIP하는 실크롤 스크립트다.

**교훈**: 종료코드만 보면 "아무것도 검증하지 않고 성공한 것"과 "검증하고 통과한 것"을
구별할 수 없다. 이 저장소가 반복해 잡아 온 **"거짓 성공"이 테스트 집계 자체에도** 있었다.

이 문서의 앞선 Sprint 기록에 나오는 "31~33 PASS" 표기는 전부 이 방식으로 센 값이므로,
**실제 통과 수는 각 시점에서 1 적다**고 읽어야 한다. 실패 1건이 `test_schema_hygiene.py`
(미추적 파일 가드, 승인 영역)라는 사실은 변하지 않는다.

### Sprint 163~164 — 계열 전수 검색 두 건 (rule 8)

**Sprint 163. 프런트가 보내는데 백엔드가 읽지 않는 파라미터 — 전수 대조**

TODO 3건은 소스에 표시라도 돼 있다. 문제는 **표시되지 않은 것이 더 있는가**였다.
`SearchForm.tsx`가 URL에 싣는 키와 백엔드 OpenAPI가 선언한 쿼리 파라미터를 대조했다.

```
프런트가 보내는 키 27개  /  백엔드가 선언한 키 23개
무시되는 키 5개: min·max_building_area, min·max_land_area, special_conditions
   (소스 TODO 표시는 그중 2개에만 붙어 있다)
백엔드가 받지만 프런트가 안 보내는 키: size 1개
```

**미표시 미지원 파라미터는 없었다** — 5개 전부 기존에 알려진 면적/특수조건이다.
실증도 했다: 값을 넣어도 `total`이 1,876으로 불변이고, 400/422로 거부되지도 않는다.

★ 그런데 **기존 가드가 하드코딩 목록**이었다. 프런트가 6번째를 추가하면 통과해 버린다 —
BUGS #112에서 얻은 교훈("목록 기반 검사는 목록에서 빠진 것을 못 본다")과 같은 한계다.
`test_search.py`의 가드를 **동적 계산**으로 바꿨다:

```
(프런트가 싣는 키) - (백엔드 선언 키)  ==  UNSUPPORTED 목록
```

새 미지원 파라미터가 생기면 그 순간 이름을 짚어 실패하고, 반대로 구현돼서 목록에
죽은 항목이 남아도 실패한다. 6번째를 주입해 FAIL하는 것까지 확인 후 복원했다.

**Sprint 164. 중복 SQL / 중복 상수 전수 탐색**

```
서로 다른 파일에 같은 SQL: 8건 — 전부 정당(일회성 스크립트끼리, 또는 id 조회처럼 자명한 것)
중복 정의 상수: 7개
   DB_PATH / DOC_TYPE_FILES / VALID_PAYMENT_TYPES   값 동일
   DOCUMENT_ROOT / DOWNLOAD_DIR / PROJECT_ROOT      ★ 표현식이 다르다
   TARGET_COLUMNS                                    의도적으로 다름(도구별 대상 범위)
```

`PROJECT_ROOT` 계열은 **표현식만 다르고 해석값은 같다** — 파일 깊이가 달라
`dirname()` 횟수가 다를 뿐이다(crawler 2단계 / api/v1 3단계 / 루트 1단계). 실제로
해석해 확인했다: 네 모듈 전부 `<repo>/documents` 한 곳을 가리킨다.

★ 그런데 **그것을 고정하는 검사가 없었다.** `test_doc_path_safety.py` 6번은 크롤러
두 모듈끼리만 비교하고, 정작 **그 파일을 서빙하는 API 쪽 루트는 대조하지 않았다.**
파일이 옮겨지거나 `dirname()` 횟수가 어긋나면 조용히 갈라지고, 그때 나오는 증상이
이 저장소의 단골이다 — 크롤러는 저장했고 `document_status`는 READY인데 서빙만 404다.

표현식이 아니라 **해석된 실제 경로**를 비교하도록 6번을 확장했다(대조군으로 그 경로가
저장소의 `documents/`인지도 함께 본다). 루트 하나를 일부러 어긋나게 해 FAIL하는 것까지
확인 후 복원했다.

### 테스트 집계 (정확한 방식)

```
통과 32 | 실패 1 | 건너뜀 3 | 판정없음 1     (37파일, 단언 4,195건, 36.0초)
실패 1 = test_schema_hygiene.py (미추적 파일 가드, 승인 영역)
```

### Sprint 165~167 — Crawler Audit + ★ 내 감사 도구의 맹점 발견

**Crawler Audit: GREEN**

```
config/courts.py 60개  ==  DB의 auction_case 법원 60개
config에만 있음 0 / DB에만 있음 0     (도달 불가 법원 없음)
code == name  60/60      (docs가 적어 둔 전제와 일치)
사건 수 상위 인천93·서울남부89·부천57 / 하위 거창3·남원2·영덕1
16개 광역 지역 전부 커버
```

**★ 그 과정에서 내 AST 스캐너의 맹점을 발견했다**

스케줄러 전제조건을 확인하다 `migrate_execute.py`가 `ast.parse`에서
`SyntaxError: invalid non-printable character U+FEFF`로 죽는 것을 봤다. 파이썬 자체는
BOM을 처리하므로(py_compile OK) 문제는 **내 읽기 방식**이었다 —
`open(..., encoding="utf-8")`로 읽으면 BOM이 U+FEFF 문자로 남아 `ast.parse`가 거부한다.

그런데 Sprint 149(자원 누수)와 150(죽은 코드/미사용 import) 스캐너가 바로 그 방식이었고,
`except SyntaxError: continue`로 **조용히 건너뛰고 있었다.**

```
추적 프로덕션 .py 77개 중 내 스캐너가 건너뛴 것: 40개 (52%)
   api_server.py / api/v1/item.py / api/v1/registry.py / api/v1/favorites.py /
   normalizer/normalizer.py / validator/validation_engine.py / config/courts.py ...
```

**두 감사가 절반만 수행된 상태였다.** `encoding="utf-8-sig"`로 고쳐 재실행했다.

```
자원 획득 지점   53곳 -> 73곳   (의심 5 -> 10)
미사용 import     5건 -> 9건
미참조 공개 함수  19건 -> 24건
```

**재실행 결과 새로운 자원 누수는 없었다.** 늘어난 의심 10곳은 전부
`conn.isolation_level = None` / `conn.row_factory = ...` 같은 대입(예외 불가)이거나
프로세스 종료로 정리되는 CLI 스크립트다. `api/v1/registry.py`도 확인 결과
`get_connection` 4 : `finally` 4 : `conn.close()` 4로 균형이 맞는다.

**새로 나온 진짜 결함은 하나 — `validator/validation_engine.py`의 미사용 import**

```python
from normalizer.normalizer import SIDO_PATTERNS as SIDO_MAP   # 사용처 0곳
```

시도(sido) 데이터 중복을 없애며 별칭 import로 바꿨는데, 그 뒤 Sprint 78이 `extract_sido`
까지 normalizer 것을 쓰도록 바꾸면서 **그 데이터를 직접 읽던 함수가 사라졌다.** 별칭만
남고 쓰는 곳은 0이 됐다(주석 2곳 외 참조 없음, 다른 모듈의 재수출 사용도 없음).
재노출 의도였다면 같은 파일의 `extract_sido`처럼 `# noqa: F401`이 붙었을 텐데 없었다.

지우면 아래 주석의 "위 SIDO_MAP 주석이" 참조가 끊기므로, **이력을 보존하는 주석으로
대체**하고 참조 문구도 정합화했다. `extract_sido` 재노출은 그대로 동작한다.

**교훈**: 감사 도구가 조용히 실패하면 감사 결과가 조용히 틀린다. `except: continue`는
"이 파일은 검사하지 않았다"를 감춘다. 앞으로 전수 스캐너는 **건너뛴 파일 수를 반드시
출력**해야 한다 — 0이 아닌데 아무도 모르는 상태가 이번에 실제로 있었다.

### Sprint 166 — `test_filter.py`에 성격 명시

판정문(assert/check)이 **0개**인 진단 스크립트인데 이름이 `test_`로 시작해 집계에 섞인다
(이 세션에서 내가 실제로 오집계했다). 대상인 `filter/`는 죽은 코드이고 docs/CLAUDE.md가
테스트 추가를 명시적으로 금지하므로, 판정문을 넣는 대신 **파일 자체에 성격을 명시**했다.
동작은 한 줄도 바꾸지 않았고, 실행기는 여전히 "판정없음"으로 분류한다.

### Sprint 168 — BOM 맹점 계열을 저장소 전체로 전수 검색 (rule 8)

내 스캐너에서 발견한 맹점이 **저장소의 가드에도 있는지** 확인했다. 결과는 깨끗했다.

```
ast.parse를 쓰는 테스트 4곳 — 전부 utf-8-sig로 읽는다
   test_api_regression.py / test_crawl_exit_code.py
   test_doc_storage_atomicity.py / test_pipeline_integrity.py
```

게다가 `test_console_encoding.py`가 **이 함정 자체를 명시적으로 문서화하고 지키고 있다** —
"BOM이 붙은 소스를 utf-8로 읽어 ast.parse()에 넘기면 SyntaxError가 나고, 그것을 조용히
건너뛰면 **검사한 척하면서 68개 파일을 빼먹는다**". 실패한 파일을 삼키지 않고 SKIPPED에
남기는 것까지 구현돼 있다.

즉 저장소는 이 규약을 갖고 있었고, **어긴 것은 내 도구뿐이었다.**

다만 이번 세션에 내가 추가한 `test_auction_identity.py`의 §법원 가드가
`encoding="utf-8"`로 읽고 있었다(같은 파일 290행은 utf-8-sig였다). 정규식 기반이라
지금은 깨지지 않지만 **나중에 AST로 바꾸면 조용히 절반을 빼먹는다.** 규약에 맞춰
`utf-8-sig`로 바꾸고 그 이유를 주석으로 남겼다.

### 최종 상태 (2026-08-17 세션 종료 시점)

```
통과 33 | 실패 1 | 건너뜀 3 | 판정없음 1     (단언 4,235건, 37.6초)
실패 1 = test_schema_hygiene.py §6-B (미추적 파일 import 간선 4개, 승인 영역)

tsc 0 / eslint 0 / next build 성공 / compileall 0
문서 3,338 디렉터리 / 767 파일 / 1.29 GB  (감사 시작 시점과 동일)
워커 락 없음 / 커버리지 산출물 없음 / QA 프로브 흔적 없음
```

### Sprint 169~170 — doc_type 어휘 집합 대조 + 이미지 큐잉 준비 상태

**Sprint 169. 죽은 코드 `storage.database.query()` 정밀 조사**

삭제는 여전히 보류한다(유일한 참조가 `test_db.py`인데 그 파일은 라이브 크롤 전용이라
이 세션에서 실행 검증이 불가능하다). 대신 **결함이 있는지**를 봤다.

```
파라미터 바인딩  정상 (문자열 결합 없음)
try/finally      정상 (커넥션 해제 보장)
식별키           case_no를 쓰지 않는다 -> 법원 누락 계열 아님
```

결함은 없다. 다만 부활시킬 때 주의할 점이 하나 있다 — `sido = ?` **정확 일치**라
`'서울특별시'`를 넣으면 0건이 된다. 현재 API(`api/v1/search.py`)는 `extract_sido()`로
정규화한 뒤 비교한다. 이 함수만 그 단계가 없다.

**Sprint 170. doc_type 어휘를 9개 계층에서 집합 대조** (rule 4의 집합 차이 원칙)

BUGS #108은 "대소문자"라는 한 축만 봤다. 진짜 질문은 **어느 계층에 있는 종류가 다른
계층에 없는가**다.

```
API DOC_TYPE_FILES            APPRAISAL SPEC STATUS
DB document_status / doc_raw  APPRAISAL SPEC STATUS
DB document_queue             appraisal spec status
QUEUE_TO_DOC_STATUS_TYPE      appraisal spec status image  ->  APPRAISAL SPEC STATUS IMAGE
doc_paths.CANONICAL_DOC_FILENAME / _PRIMARY_EXT   3종
doc_paths.CASE_LEVEL_DOC_TYPES                    status only  (설계상 맞다)
```

대소문자 정규화 후 개념은 4개이고, `STATUS`만 전 계층에 있다. `IMAGE`가 여러 계층에
없는 것은 **설계상 의도**다 — 사진은 `api/v1/images.py`가 따로 서빙하고, `doc_raw`는
(item, doc_type)당 1행이라 0~N장을 담을 수 없다(migration 020 주석).

**★ 그런데 실데이터에서 하나가 걸렸다 — `document_queue`에 image 행이 0개다.**

```
enqueue_documents()  393행:  for doc_type in ("spec","status","appraisal","image")
document_queue의 image 행:    0
document_status의 IMAGE 행:   0
auction_image:                45행 (생성 2026-08-17 09:07~09:09)
```

원인은 시점이다. **`image` 큐잉은 오늘(Sprint 144) 추가됐고, 이를 호출하는
`mvp_scraper.py`는 2026-08-12 이후 실행된 적이 없다.** 즉 운영에서 image가 큐에 들어간
적이 한 번도 없고, 사진 45장은 오늘 직접 실행한 수집분이다.

사용자 영향은 지금 **0**이다. 사진 행이 없는 물건 1,867건이 `images_status=COLLECTING`
으로 보이지만 **그중 매각기일이 남은 것은 0건**이다(전부 만료). 살아있는 9건은 전부
사진 5장 READY다.

**Blocker 해결 후 필요한 작업 — 미리 검증했다** (rule 6)

스케줄러가 재개되면 image가 **처음으로** 운영 큐에 들어간다. 그것이 실제로 동작하는지
사본에서 실증했다(운영 DB 무변경: 3,498행 유지, QA 흔적 0):

```
enqueue_documents([row])  ->  {'added': 4}
   appraisal / image / spec / status  전부 pending, prio=3
재적재                     ->  {'added': 0}, 총 4행   (UNIQUE + INSERT OR IGNORE 정상)
worker가 즉시 집을 수 있는 행: 4
get_doc_button_id('image','1') = None 이지만
   doc_worker의 `needs_button = doc_type != "image"` 가 버튼 검사를 건너뛴다 (소스 확인)
```

즉 **스케줄러 등록만 되면 이미지 파이프라인은 첫 실행부터 정상 동작한다.**

### Sprint 171~173 — 필드 계약 / 동시성 / 데이터 신선도

**Sprint 171. 프런트가 읽는 필드 vs API가 보내는 필드 (집합 차이)**

없는 필드를 읽으면 예외가 아니라 `undefined`가 되어 **화면에 조용히 빈 값**이 뜬다.
빌드도 타입체크도 통과하므로 실제 응답과 대조해야 잡힌다.

```
API 실제 응답 키   상세 73개 / 검색 24개 / 합집합 78개
프런트가 읽는 필드 29개 중 응답에 없는 것:  0개
```

**이 방향은 깨끗하다.** 반대 방향("API가 보내는데 프런트가 안 읽는 49개")은
**보고하지 않는다** — 내 정규식이 `property.foo` 형태만 잡아서 구조분해·옵셔널 체이닝을
놓쳤기 때문이다. 표본 6개(`viewer_url`/`image_count`/`representative_image`/
`total_pages`/`risk_level`/`tenant_name`)를 확인하니 **전부 프런트 소스에 존재**했다.
검사기의 한계이지 죽은 필드가 아니다.

**Sprint 172. 동시성 — 공백 없음**

`test_document_queue.py` §8(`test_claim_is_atomic_under_concurrency`)이 threading으로
"여러 Worker가 동시에 집어도 같은 일감을 두 번 주지 않는다"를 이미 고정한다.

**Sprint 173. 데이터 신선도 (stale data)**

지금 사용자에게 보이는 9건은 **전부 2026-08-12 수집분, 5일 경과**다.

```
item 502 / 505 / 1533 / 11853 / 11854 / 11855 / 11856 / 11857 / 11858
   매각기일 2026-08-19  수집일 2026-08-12  경과 5일   유찰 1~8회
```

가격은 유찰 시점에 바뀌므로 매각기일 전인 지금은 대체로 유효하다. 실제 위험은
**08-12 이후 취하·변경·연기된 물건을 계속 보여주는 것**이고, 크롤이 멈춘 상태에서는
그것을 알 방법이 없다.

**다만 앱은 이 사실을 사용자에게 숨기지 않는다** — 상세페이지가 수집일을 그대로 노출한다
(`page.tsx:696`, "최근 수집일 2026-08-12"). 실제 화면에서도 확인했다. 데이터가 낡았을 때
정직하게 낡았다고 말하는 것이 이 블로커에 대한 적절한 fail-safe다.

### Sprint 174~176 — 릴리스 문서 정합 + 문서 주장 전수 검증

**Sprint 174. `BETA_RELEASE_CHECKLIST.md`에 현재 P0 블로커 2건 추가**

그 문서의 역할이 "**지금 출시를 막는 것만** 다룬다"인데, 이번 감사에서 확인된 P0 두 건이
빠져 있었다(둘 다 그 문서가 마지막으로 정리된 시점 이후에 생겼다). 전면 재작성은 여전히
범위 밖이므로 **두 건만 올렸다** — P0-A(데이터 공급 정지, 08-20부터 검색 0건),
P0-B(지금 커밋하면 API 부팅 불가).

**Sprint 175. `CHANGELOG.md`에 Sprint 148~175 항목 추가**

그리고 그 과정에서 **이 CHANGELOG 자신의 과장을 하나 발견해 정정했다.**
Sprint 145 항목의 "상세 API SQL 7문 **고정**"은 사실이 아니었다 — 그 시점에 7문임을
측정했을 뿐, 회귀로 고정하지는 않았다(쿼리 수를 세는 검사는 검색 쪽 16-B 하나뿐이었다).
상세를 실제로 고정한 것은 Sprint 154의 16-C다.

**Sprint 176. 문서가 인용하는 심볼이 실제로 존재하는가 (전수)**

위 과장을 발견한 뒤, **같은 종류가 다른 문서에도 있는지** 전수로 훑었다(rule 3).
`docs/*.md`가 백틱으로 인용하는 `함수()`와 파일명을 저장소 전체 소스와 대조했다.

```
정의를 못 찾은 함수 인용   17개
존재하지 않는 파일 인용    18개
```

**전수 확인 결과 진짜 드리프트는 0건이었다.** 세 부류였다:

1. **내장/라이브러리 함수** — `input()` `sorted()` `dirname()` `flush()` `openapi()`
   `terminate()`. 저장소 함수가 아니다(내 정규식의 한계).
2. **정당한 과거 기록** — `middleware.ts`(→`proxy.ts` 개명), `storage/migrate_doc_collect.py`
   (→Migration 017로 대체), `016_create_audit_logs.sql`/`017_add_soft_delete_columns.sql`
   (Sprint 51 이전 옛 파일명 — CURRENT_STATE가 **그 드리프트를 고친 기록**으로 명시하고
   있다), `get_auction_images()`(Sprint 150에 내가 제거한 것을 기록).
3. **이름만 약간 다른 실존 심볼** — `test_registry_orphan_item_visibility()`는
   `test_false_success.py:68`에 `test_registry_orphan_visibility()`로 존재하고,
   해당 문서가 그 이동·확장을 이미 설명하고 있다.

문서가 과거를 기록하는 것과 현재를 잘못 말하는 것은 다르다. 이 저장소는 전자를 하고 있다.

### Sprint 177 — DB 컬럼 vs API 노출 (rule 4 마지막 적용)

```
auction_item 컬럼 21개  /  API 노출 키(상세+검색) 28개
어떤 API도 내려주지 않는 컬럼: 3개
   case_id      1876/1876 값 있음   내부 FK
   created_at   1876/1876 값 있음   내부 타임스탬프
   updated_at   1876/1876 값 있음   내부 타임스탬프
```

셋 다 **설계상 내부용**이다. 사용자에게 줄 데이터인데 안 주는 컬럼도, 아무도 안 쓰는
죽은 컬럼도 없다. 노출 키 28개 중 10개는 파생/조인값(사진·문서·권리분석)이다.

이로써 집합 차이 검증을 네 영역에 적용했고 전부 깨끗하다:

```
프런트 파라미터 -> API      무표시 미지원 0 (동적 가드로 전환)
doc_type 어휘 9계층         불일치는 전부 설계상 의도
프런트 필드 <- API 응답     읽는데 없는 필드 0
DB 컬럼 -> API 노출         미노출 3개 전부 내부용
```

### Sprint 178 — 감사 범위 자체의 맹점 2번째: 미추적 프로덕션 파일

BOM 맹점(Sprint 167)에 이어 **범위 맹점**이 하나 더 있었다. 내 스캐너들이 전부
`git ls-files`(추적 파일)만 대상으로 했는데, 이 저장소는 지금 **실동작 모듈 6개가
미추적**이고 그중 4개는 프로덕션이 실제로 import한다.

```
api/http_cache.py        <- 3개 파일이 참조
api/v1/images.py         <- 21개 파일이 참조
crawler/image_assets.py  <- 6개
crawler/image_crawler.py <- 4개
backfill_doc_raw.py / empty_doc_dirs_dryrun.py
```

즉 자원 누수·죽은 코드·중복 SQL·법원 식별키 감사가 **라이브 코드 6개를 건너뛰고 있었다.**
범위를 넓혀 재실행했다(추적 77 → 84개).

```
자원 획득 지점  73 -> 75곳,  새 의심 0   (미추적 모듈들은 커넥션을 올바로 다룬다)
중복 SQL        8 -> 9건    (doc_version 조회가 3곳: database / collect_documents / backfill_doc_raw)
법원 식별키     위반 0
```

**★ 저장소 가드 2개에도 같은 맹점이 있었다 (고침)**

- `test_auction_identity.py`의 법원 가드 — `git ls-files`만 썼다. `--others
  --exclude-standard`를 함께 쓰도록 고쳤다(추적 77 → 84개). **미추적 파일에 법원 없는
  큐 UPDATE를 주입해 실제로 잡히는 것까지 확인**했다(확장 전에는 잡을 수 없었다).
- `test_schema_hygiene.py` §13(혼동 컬럼) — 같은 이유로 확장(→125개 파일 검사).

`test_schema_hygiene.py` §6-2(추적됐지만 무시되는 파일)와 §6(storage 추적 검사)은
**추적 전용이 목적에 맞다** — 추적 여부 자체를 보는 검사이므로 그대로 뒀다.

### ★★ 그 확장이 내 결함을 하나 드러냈다

§13 확장 후 `test_schema_hygiene.py`의 위반이 2건에서 **3건**이 됐다. 새로 뜬 것은
`('unlock_retry.py', 'where')` — **Sprint 153에 내가 재작성한 파일**이다. WHERE를
`" AND ".join()`으로 만들었는데 이 저장소는 그 패턴을 허용 목록으로 관리한다.

더 나쁜 것은 **내가 그것을 20 Sprint 동안 못 봤다는 점**이다. 매번
`FAILED: test_schema_hygiene.py` 한 줄만 보고 "미추적 파일 가드겠지"라고 넘겼다.
파일 단위 실패만 보면 **그 안의 다른 위반이 숨는다.**

조각은 전부 상수 리터럴이고 값은 예외 없이 `?`로 바인딩되며, 사용자 입력(argparse)은
조각이 아니라 params로만 간다 — 이미 허용된 `storage/database.py`/`filter_engine.py`의
`where` 항목과 같은 패턴이라 근거를 적어 허용 목록에 추가했다. 지금은 위반이 정확히
2건이고 둘 다 의도된 미추적 파일 가드다.

**교훈**: 실패한 "파일 수"가 아니라 **실패한 "검사 항목"을 세야 한다.**

### Sprint 179~180 — doc_version 중복 판정 + 스케줄러 등록 전제조건 정정

**Sprint 179. `doc_version` 조회 3곳 중복 — 분기 아님**

Sprint 178이 "3곳 중복"으로 기록만 하고 넘어간 것을 실제로 대조했다.

```
storage/database.py     SELECT MAX(doc_version)+1        (라이브 경로)
collect_documents.py    SELECT MAX(doc_version)+1        (스케줄러 미도달 스크립트)
backfill_doc_raw.py     doc_version=1 하드코딩           ★ 다르다
```

세 번째가 달라서 조사했더니 **구조상 정확했다.** `plan()`이
`if key in existing: already += 1; continue` 로 **이미 `doc_raw` 행이 있는
(item_id, doc_type) 조합을 통째로 제외**하므로, 삽입 대상은 정의상 첫 버전뿐이다.

실측이 이를 확인해 준다 — 이미 `--apply`로 556행을 넣은 뒤인데:

```
doc_raw 중복 (item_id, doc_type)  0건
doc_version 분포                  v1: 556행 (다른 버전 없음)
```

**Sprint 180. 스케줄러 등록 스크립트 검증 + 내 기술 정정**

`register_scheduler_tasks.ps1`을 dry-run으로 실제 실행했다(`-Apply` 없음). 작업 3개가
근거와 함께 정의돼 있고 순서도 맞다:

```
01:50 DojoonPass-PriorityRefresh  run_priority_refresh.bat
02:00 DojoonPass-DocWorker        run_doc_worker.bat     (DOC_WORKER_END_TIME 04:00과 정합)
06:00 DojoonPass-DailyCrawl       run_daily.bat
선행 조건: 배치 파일 3개 OK / PATH python 확인됨
```

**★ 그런데 dry-run이 내가 빠뜨린 전제조건을 드러냈다.**

```
머신 PATH 로 해석 가능 : 아니오 -> SYSTEM 계정 등록 금지
실행 방식              : 로그온 상태에서만 (비밀번호 불필요)
```

Python이 사용자 프로필에 설치돼 있어 머신 PATH로 해석되지 않고, 그래서 기본 등록은
`LogonType Interactive`다 — **로그오프 상태에서는 실행되지 않는다.** 01:50~06:00에
기기가 로그인 화면에 있으면 **등록해도 수집은 여전히 0건**이다.

이 사실 자체는 `docs/SPRINT112_SCHEDULER_HANDOFF.md`에 이미 있었다. 문제는 **내가 이
문서와 `BETA_RELEASE_CHECKLIST.md` P0-A에 "조치는 `-Apply` 한 줄"이라고만 적어
전제조건을 누락**한 것이다. 그대로 읽으면 등록만 하고 왜 여전히 0건인지 모르게 된다.

P0-A를 정정했다 — 로그온 유지 / `-RunWhetherLoggedOn`(비밀번호 필요) / Python 머신 전역
설치 중 하나를 **함께 결정해야 한다**는 것과, 어느 쪽을 고를지는 운영 정책이라 임의로
정하지 않는다는 것을 명시했다.

(위 Sprint 148·156 절의 "`-Apply` 한 줄" 표기도 같은 축약이다. 과거 기록은 그대로 두되,
현재 판단은 이 절과 P0-A를 따를 것.)

### Sprint 181~183 — 복구 경로 / 부분 수집 / config 사본 동기화

**Sprint 181. 재시작 후 복구 — GREEN**

`reset_stale_queue()`가 `in_progress` 10분 초과 행을 회수한다. `test_document_queue.py` §6이
**"정지 30분 = 회수 / 진행 1분 = 미회수"** 를 구분해 고정한다(돌고 있는 Worker를 건드리면
같은 문서를 두 프로세스가 받는다). 현재 DB의 in_progress 0건.

**Sprint 182. 부분 수집 — 발생 0건, 설계는 기록만**

`no_asset`(원천에 사진 없음)은 `NO_IMAGE`로 구분하지만 **부분 수집은 `READY`** 다.
그 자체는 정직하다 — `image_count`가 실제 저장된 수를 그대로 반영하므로 화면이
"5장"이라고 거짓말하지 않는다. 다만 부분이라는 사실이 어디에도 기록되지 않고 큐는
done이라 **다시 시도되지 않는다.**

실측상 아직 일어난 적이 없다:

```
로그의 "부분 수집/부분 성공" 경고   0건
물건별 사진 수                      9물건 전부 5장
seq 결번(조용한 손실)               0건  (COUNT == MAX(seq))
```

상태 어휘를 늘리는 것(PARTIAL 신설)은 화면 문구까지 걸리는 제품 결정이라 SKIP한다.

**Sprint 183. config 상수와 그 "사본"이 어긋나지 않는가 (검사 신설)**

`config/settings.py`가 정의만 해 두고 **아무도 import하지 않는** 상수 2개를 찾았다.

```
DOC_TYPE_LIST         사본: storage/database.py:enqueue_documents() 의 for 루프 리터럴
PRIORITY_REFRESH_TIME 사본: register_scheduler_tasks.ps1 의 Time 필드
```

그 파일의 주석 자신이 "둘 중 하나만 고치면 조용히 어긋나므로 함께 맞춰 둔다"고 적고,
통합은 사유와 함께 별도 과제로 미뤄 뒀다. **그렇다면 최소한 그 "함께 맞춰 둔다"를
사람의 기억이 아니라 검사가 지켜야 한다.**

`test_schema_hygiene.py` 14-B를 신설했다(9검사). 어긋나면 증상이 조용하다 — 새 문서
종류를 config에 넣어도 큐에는 안 들어가고, 우선순위 갱신 시각을 바꿔도 스케줄러는 옛
시각으로 등록된다. 현재 두 사본 모두 일치하며, **스케줄러 시각을 일부러 어긋나게 해
FAIL하는 것까지 확인**하고 복원했다.

### ★ 이 세션 후반의 실행 환경 — 저장소가 동시 편집되고 있다

Sprint 176 이후 테스트 실패가 실행마다 **다른 파일로 옮겨 다녔다**(`test_console_encoding`
→ `test_doc_path_safety` → `test_api_regression`). 각각을 단독 실행하면 전부 통과했다.

원인을 특정했다 — **다른 작업이 같은 저장소를 동시에 수정하고 있다.**

```
16:47 backfill_doc_raw.py     17:37 mvp_scraper.py      17:59 collect_documents.py
18:40 migrate_dryrun.py       18:40 reset_failures.py
그 사이 새로 생긴 파일: test_crawl_error_log.py / test_item_detail_auth.py /
                        run_python_tests.py / check_release_build.py / step11_report.py
```

관측된 현상과 판정:

- `check_release_build.py`의 em-dash 위반 → 다음 실행에서 사라짐(외부에서 정정)
- `step11_report.py`의 규칙 사본 위반 → 다음 실행에서 사라짐(`sanitize_path_segment` 사용으로 수정)
- `test_api_regression.py` 배치 실패 → 단독 실행 exit 0, **qa- 잔여 0행**

즉 **코드 결함이 아니라 파일이 검사 도중 바뀐 것**이다. 다만 이것은 Sprint 154에 기록한
위험("`test_api_regression.py`가 운영 DB에 픽스처를 쓰고 끝에 지운다")이 **동시 실행
환경에서 실제로 드러난 것**이기도 하다. 그 구조에서는 동시 작업이 있을 때 결과를
신뢰하려면 단독 실행으로 재확인해야 한다.

**내 수정이 덮이지 않았는지 전수 확인했다 — 11개 항목 전부 온전하다**
(#106~#112 수정, 계열 가드, 14-B, decode 일관성).

동시 편집 중인 파일(gitignore 대상 스크래치 포함)은 **편집하지 않았다** — 진행 중인
작업을 덮어쓸 수 있기 때문이다. 발견 사실만 기록한다.

### Sprint 184 — 데이터 최신화(변경 감지) 사슬 규명

새 목표의 핵심인 **"법원 자료가 바뀌면 따라가는가"** 를 코드 기준으로 끝까지 추적했다.

**변경이 전파되는 구간 — 정상**

```
upsert_batch()      auction 테이블의 매각기일·최저가·상태·감정가를 전부 UPDATE
migrate_execute()   auction_item 에도 같은 필드 + fail_count/bid_rate 재계산해 UPDATE
enqueue_documents() 큐의 auction_date 를 최신 값으로 맞춘다(법원 포함, Sprint 74)
```

즉 **물건 기본정보는 재크롤 시 최신으로 갱신된다.** stale 구조가 아니다.

**변경이 전파되지 않는 구간 — 문서/이미지**

```
collect_spec/status/appraisal (194/345/495행)
    if doc_exists(...) and not overwrite:  -> early return
        ...previous_hash 계산 **이전에** 반환한다
```

파일이 이미 있으면 해시 비교 자체에 도달하지 못한다. 그래서
`mark_queue_done(previous_hash != new_hash)` 분기와 `document_version_log`가
**구조적으로 도달 불가**였다(실측: version log 0행, `doc_raw` 556행 전부 doc_version=1).

**★ 그런데 기계는 이미 완성돼 있었다**

`overwrite` 파라미터가 네 수집기와 디스패처에 **전부 배선돼 있다.** 빠진 것은 호출부
하나뿐이다 — 아무도 `True`를 넘기지 않는다. 그리고 그 경로는 **테스트가 0건**이었다.

그래서 "정책을 정하면 곧바로 쓸 수 있는가"가 미지수인 채로 결정이 미뤄져 있었다.
그 미지수를 없앴다 — `test_asset_pipeline.py` 5-B 신설(11검사):

```
overwrite 기본값   파일 그대로            (중복 다운로드 방지 유지)
overwrite=True     바이트가 실제로 바뀐다  (스킵만 우회하는 게 아니다)
                   순번/장수 계약 유지, 집합 해시도 바뀐다
```

바이트를 그대로 비교하니 실패 메시지에 JPEG 원본이 통째로 찍혀 로그가 34KB로 부풀었다.
해시 비교로 바꿔 읽을 수 있게 했다(검사 자체의 품질도 검사 대상이다).

**결정에 필요한 수치 (roadmap 해당 항목에 상세)**

```
전면 재수집    556건 x 12초 = 1.9시간  vs  실행 창 2.0시간 -> 신규 처리 여지 0
표적 재수집    기일이 미래로 바뀐 done 행 7개 = 약 84초
```

정책(트리거 + 되살릴 상태 범위)은 제품 판단이라 **SKIP**한다. `enqueue_documents()`가
지금 일부러 `status`를 건드리지 않는 그 한 줄이 곧 구현 지점이고, 되살리는 범위에 따라
일일 재수집량이 7행에서 556행까지 달라진다.

### Sprint 185 — 물건 변경 관측 신설 (UPDATE 동작 불변, 순수 가산)

**규명한 사실**

```
auction_item 1,876행 중 updated_at != created_at 인 행: 1,876 (100%, 전부 2026-08-12)
auction_item.updated_at 을 읽는 코드: 0곳
물건 단위 변경 이력 테이블: 없음 (document_version_log/rights_analysis_history는 다른 대상)
```

`migrate_execute`의 UPDATE는 **값이 같아도 매번 실행**된다. 그래서 `updated_at`이 전 행
동일해지고, 아무도 그것을 읽지도 않는다. 결과적으로 **"오늘 어떤 물건의 기일/최저가/
상태가 바뀌었나"를 시스템이 답할 수 없었다.** 법원 자료는 절차 진행에 따라 계속
바뀌므로(유찰 1,480건 = 최소 한 번은 상태가 움직인 물건) 그 답이 곧 제품 가치다.

**조치 — 관측만 추가했다**

스키마도 UPDATE 조건도 건드리지 않았다(순수 가산 +41/-0). 이미 손에 들고 있는
`existing`과 새 값을 비교해 **무엇이 바뀌었는지만** 집계·로그한다. 대상 필드는
`auction_date` / `minimum_bid_price` / `status` / `appraisal_price` — 유찰→재매각 때
함께 움직이는 값들이다.

UPDATE 조건을 바꾸지 않은 이유: 그것은 동작 변경이고, 지금 `updated_at`을 읽는 곳이
없어 얻는 것도 없다. 반면 관측은 **오늘 당장 일일 로그에서 답을 준다.**

**사본에서 실증** (운영 DB 무접촉 — 검증 후 1,876 / 225,600,000 / 유찰 1회 그대로)

```
사본에서 한 물건의 기일·최저가·상태를 바꾸고 migrate_execute 실행
  auction_item 갱신 1,876건   <- 종전과 동일(모든 행을 UPDATE한다)
  실제로 값이 바뀐 항목:
     auction_date       1건    2024타경3528-1  2026-08-19 -> 2026-10-15
     minimum_bid_price  1건                    225600000 -> 112800000
     status             1건                    유찰 1회 -> 유찰 9회
  전파 확인: auction_item 에 그대로 반영, fail_count 도 9로 재계산됨
```

**"갱신 1,876건"과 "실제 변경 1건"을 처음으로 구별해 냈다.**

**회귀** — `test_auction_identity.py` 8번 신설(6검사). 양방향을 고정한다:
변경이 없으면 관측도 0건(거짓 양성 방지), 변경하면 해당 필드만 정확히 1건,
바뀌지 않은 필드는 세지 않음, 그리고 전파까지 확인. 테스트가 읽을 수 있도록
`migrate_execute.LAST_FIELD_CHANGES`를 모듈 수준으로 노출했다(로그만 남기면 자동
검증이 불가능하다).

### Sprint 186 — 이미지 파이프라인 전수 추적 (법원 원천 → 상세페이지)

goal의 15개 확인 항목을 코드 기준으로 훑었다. 결과를 상태별로 나눈다.

**이미 정상인 것**

```
스키마/데이터   auction_image 45행 = 9물건 x 5장, seq 결번 0, 파일/크기/API 전건 일치
중복 방지       기존 파일이 있으면 건너뛴다 (image_crawler.py:162)
재수집 능력     overwrite 가 네 수집기+디스패처에 배선, 동작 검증됨 (Sprint 184 5-B)
원자적 저장     임시파일 + os.replace, 실패 시 .tmp도 남지 않음 (6-B)
상태 구분       NO_IMAGE(법원 미제공) / COLLECTING / READY 를 구분 — "없음"과 "실패"를 뭉개지 않는다
API/화면        상세 API가 auction_image 를 그대로 반환, 브라우저에서 5장 렌더 확인
```

**이번에 고친 결함 2건**

- **BUGS #113 — 이미지는 변경 감지 자체가 불가능했다.** `collect_images()`가
  `previous_hash`를 끝내 계산하지 않아, `mark_queue_done()`의 감지 조건이 이미지에서는
  영원히 거짓이었다. 문서 수집기는 같은 자리에서 이미 계산하고 있었다 — **이미지만
  빠져 있었다.** 수집 전에 디스크 기존 사진으로 같은 공식의 지문을 뜨도록 고쳤다.
- **BUGS #114 — 부분 수집이 사용자가 보던 사진을 지웠다.** `save_auction_images()`가
  "법원이 줄였다"와 "일부만 받아졌다"를 구별하지 못하고 뒷번호 행을 지웠다.
  `complete` 플래그를 받아 **판단할 수 없을 때는 남기는 쪽**으로 바꿨다.

두 결함 모두 **재수집을 켜는 순간 도달하는 경로**다. 지금은 재수집이 없어 드러나지
않았을 뿐이라, 정책이 정해지기 전에 미리 막았다.

**변경 감지 사슬이 이제 이미지에서도 이어진다**

```
디스크 기존 사진 -> previous_hash (_existing_set_hash)
새 수집          -> new_hash (파일별 sha256을 순번 순으로 이어 붙여 sha256)
다르면           -> mark_queue_done -> document_version_log 1행
```

회귀가 이 사슬 전체를 고정한다(5-C, 10검사). 특히 "같은 사진 재수집 시 두 지문이 같다"는
검사가 **디스크 쪽 공식과 수집 쪽 공식의 일치를 구조적으로 보증**한다 — 갈라지면 매 수집이
거짓 개정이 되어 진짜 개정을 찾을 수 없다.

**여전히 남은 것 — 트리거 (승인 영역)**

이미지도 문서와 같다. 기계는 완성됐고 **아무도 `overwrite=True`를 넘기지 않는다.**
재수집 범위는 제품 결정이라 SKIP하며, 판단에 필요한 수치는 roadmap 재수집 정책 항목에
정리돼 있다(전면 1.9시간 vs 표적 84초).

**이미지에는 안정적 원본 식별자가 없다** (goal #2 확인 결과)

법원은 사진을 **base64 data URI로 DOM에 심어** 준다 — URL이 없다. 식별자는 alt 텍스트
(`전경도_1`)에서 뽑은 순번뿐이다. 따라서 "URL이 바뀌었는지"로는 변경을 알 수 없고,
**바이트 지문이 유일한 근거**다. 이번 #113 수정이 그 근거를 실제로 사용 가능하게 만들었다.
