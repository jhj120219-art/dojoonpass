# Test Plan

Status: Active
Last Updated: 2026-08-09

이전 버전(16줄짜리 체크리스트)은 "이미지 ☑", "권리분석 ☑"처럼 **존재하지 않는 기능을 완료로
표시**하고 있었고 실제로 상시 실행 중인 회귀 테스트 2종도 전혀 언급하지 않았다.
2026-08-07 코드 기준으로 다시 작성한다.

---

## 1. 자동 회귀 테스트 (상시 실행 가능)

별도 러너(pytest 등) 설정은 없다. 두 스크립트를 직접 실행한다.

```bash
python test_api_regression.py       # 전 도메인 실제 HTTP 회귀 (434 검사, 2026-08-09 HEAD 프로브 + Admin 결제로그 조회 + 등기부/문서 실다운로드·경로탐색 + 등기부 중복신청 방지 + 구독 중복결제 방지 + 결제 실패 후 재시도 + 2026-08-10 Sprint 43 sort_by 화이트리스트 8개 전수(정렬 결과 body까지) 검증 추가, `docs/BUGS.md` #24)
python test_subscription_policy.py  # 구독 정책/할인/월 리셋/식별키 무결성/credit 원장 (48 항목)
python test_state_machines.py       # Payment/Subscription 상태 전이·유예기간 순수 로직 (2026-08-08 신규, 82 검사)
python test_registry_credits.py     # 등기부 credit 원장 순수 로직 (2026-08-08 신규, 20 검사)
python test_auction_identity.py     # auction 식별키 무결성 + upsert_batch 법원 교차 안전성 (2026-08-08 신규, 26 검사)
python test_schema_hygiene.py       # get_connection(enforce_foreign_keys=) + soft delete 컬럼 + migration_history 완전성 (2026-08-08 신규, 8 검사)
python test_race_conditions.py      # 등기부 무료한도 + 초과결제 + 구독 + Admin 상태전이 동시 요청 방어 (2026-08-09 신규, 실스레드 22 검사, 구독 시나리오는 Sprint 38, Admin 상태전이 시나리오는 Sprint 39에서 각각 결함 수정 후 추가)
python test_intent_analyzer.py      # intent.analyzer 순수 함수 (기존, DB/API 무의존, 16 검사)
python test_normalizer.py           # normalizer.normalize_address 순수 함수 (기존, DB/API 무의존, 29 검사, 2026-08-09 cp949 크래시 수정)
python test_search.py               # /api/v1/search 주소 Intent 회귀 (기존, 17 검사, 2026-08-09 D7 필터 드리프트 재동기화)
python test_doc_storage_atomicity.py # crawler/doc_crawler.py 문서 저장 + storage/database.py 큐 완료 처리 순수 로직(Selenium 무의존) — get_doc_dir/doc_exists/원자적 쓰기(os.replace)/mark_queue_done() 부분실패 rollback (2026-08-09 Sprint 40 신규 12검사, 2026-08-10 Sprint 41 mark_queue_done rollback 검증 3검사 추가 → 15 검사, `docs/BUGS.md` #22)
python test_checkpoint_atomicity.py # storage/checkpoint.py(크롤러 재시작 이어받기) 순수 로직(Selenium 무의존) — 여러 법원 공유 파일 격리, 원자적 쓰기(os.replace), 손상 파일에도 크래시하지 않는 폴백 (2026-08-10 Sprint 42 신규, 15 검사, `docs/BUGS.md` #23)
python test_validation_log_integrity.py # validator/validation_engine.py의 logs/validation.jsonl append 순수 로직(Selenium 무의존) — 로그-결과 일치, 마지막 줄 손상이 이전 줄에 영향 없음 (2026-08-10 Sprint 42 신규, 9 검사)
python test_crawl_resume.py         # crawler/court_crawler.py:resume_start_idx() 체크포인트 재개 순수 로직(Selenium 무의존) — 정상 매칭/묶인 사건번호/체크포인트가 오늘 목록에 없을 때의 안전한 0-폴백 (2026-08-10 Sprint 43 신규, 10 검사, crawl_court() 인라인 로직을 순수 함수로 추출)
```

**2026-08-09 갱신**: 저장소 루트의 `test_*.py` 전체를 재탐색해 이번 세션 이전에는 실행되지
않았던 3개(`test_intent_analyzer.py`/`test_normalizer.py`/`test_search.py`)를 발견·실행했다.
`test_normalizer.py`는 cp949 콘솔에서 인코딩 불가능한 em-dash(—) 문자 때문에 마지막 출력에서
크래시하던 것을 ASCII로 정리해 해결(검사 자체는 이미 19/19 통과 중이었음, 출력 버그만 수정).
`test_search.py`는 11개 검사가 실패했는데, 원인은 검색 로직이 아니라 이 테스트가 하드코딩한
기대값이 D7 기본 필터(`auction_date >= 오늘`) 도입 이전 스냅숏이었기 때문 —
`include_closed`/필터 유무로 대조해 검증한 뒤 `include_closed=True`를 헬퍼에 추가하고
드리프트가 확인된 두 지역(서울/빛가람동)의 기대값만 오늘 실측치로 갱신했다(나머지는 원래
값과 정확히 일치함을 확인). 신규 `test_race_conditions.py`는 등기부 무료한도(10스레드)와
초과결제 중복방지(8스레드)를 실제 스레드로 검증한다 — 두 방어 모두 과거 문서에 "N스레드
동시 요청으로 실측 검증"이라고 기록돼 있었지만 자동화된 회귀로는 한 번도 남지 않았던 공백이다.
`test_filter.py`(dead code `filter/filter_engine.py` 대상)와 `test_db.py`/`test_docs.py`/
`test_docs2.py`(실제 courtauction.go.kr 크롤링)는 PASS/FAIL 어서션이 없거나 외부 네트워크를
쓰므로 회귀 스위트에 포함하지 않는다(전자는 수동 확인용 데모, 후자는 기존 원칙대로 자동 실행 제외).

**2026-08-08(Sprint 32) 갱신**: 승인 하에 `python-jose`를 설치해 `test_api_regression.py`/
`test_subscription_policy.py`가 **이 세션에서 처음으로 실제 HTTP 레벨로 실행**됐다 —
연속 2회 실행 전부 통과(재현성 확인), 잔여 QA 데이터 0건. `.env`에는 여전히
`SUPABASE_JWT_SECRET`이라는 이름이 없어(`JWT_SECRET`만 존재, `docs/BETA_RELEASE_CHECKLIST.md`
P0-4), `test_api_regression.py`는 `ADMIN_API_KEY`와 같은 기존 패턴으로 **이 프로세스에서만
유효한 합성 값**을 주입하도록 수정됐다(`.env` 무수정, 실제 운영 비밀값과 무관) — 이는
인가·서명 검증 **로직**을 검증하는 것이지 실제 운영 `.env`가 고쳐졌다는 뜻은 아니다.
`test_state_machines.py`/`test_registry_credits.py`/`test_auction_identity.py`/
`test_schema_hygiene.py`(jose 불필요, Sprint 29~31 신설)는 계속 유효하며, jose 확보 여부와
무관하게 더 빠르게 순수 로직만 검증하고 싶을 때 계속 쓸 수 있다.

두 HTTP 회귀 스크립트 모두 **실제 `auction.db`를 사용하되 실사용자 데이터는 건드리지 않는다.**

- `test_api_regression.py`: FastAPI `TestClient`로 `api_server.app`을 직접 호출한다(라우팅/
  의존성/인증/직렬화까지 실제 요청과 같은 경로). 테스트 데이터는 `qa-reg-<uuid>` 전용
  user_id로만 만들고 종료 시 그 행만 삭제한다. `ADMIN_API_KEY`는 프로세스 환경에만 주입한다
  (`.env` 무수정).
- `test_subscription_policy.py`: 정책 계산 함수를 직접 검증하고, DB를 건드리는 검사는
  트랜잭션 롤백 안에서 수행한다.

### `test_api_regression.py` 커버 범위

| # | 섹션 | 주요 검사 |
|---|---|---|
| 1 | Health / Stats | 루트·`/stats`·`/document-stats` 응답 형태 |
| 2 | Search | 비로그인 접근, 필터, **정렬 화이트리스트(미허용 값 400)**, 페이지네이션 경계, 인젝션 문자열 무해 처리 |
| 3 | Detail / Documents | 상세 필드, 문서 서빙, **`case.court_code`와 물건 `court_name` 일치**(복합키 Migration 회귀 방어), **HEAD 프로브**(GET과 상태코드 일치), **실제 문서 성공 다운로드**(파일이 있으면 내용 검증, 없으면 임시로 만들어 왕복 후 정확히 그 파일만 삭제 — 2026-08-09 신규, 이전까지 "200 또는 404 둘 다 통과"로만 검증해 실제 성공 시 내용이 맞는지 확인한 적이 없었음) |
| 4 | Authentication | 무토큰 401 / 위조 토큰 401 / `sub` 없는 토큰 401 / 정상 토큰 200 |
| 5 | Favorite | 등록·중복 거부·목록·삭제, 검색 결과의 `is_favorited` 반영, 소유권 격리 |
| 6 | Recent items | 상세 조회 시 자동 기록, 재조회 시 중복 행 없음 |
| 7 | Search presets | 저장·목록·조건 round-trip·삭제, 소유권 격리, **서버측 입력 검증**(공백/길이/크기/개수 상한, 이름 trim) |
| 8 | Payment / Subscription | 금액 위조 거부, 폐기 플랜명 거부, 잘못된 결제주기 거부, 월/연 기간, 할인가 적용, 소유권 격리, **구독 중복결제 방지**(순차 재요청 — 이미 유효한 구독이 있으면 다른 플랜을 보내도 새 subscriptions/payments 행 생성 없이 기존 구독 반환, `already_subscribed` 플래그 — 2026-08-09 Sprint 38, `docs/BUGS.md` #20), **결제 실패 후 재시도**(provider를 일시 교체해 FAILED 강제 — 실패 시 subscription 미생성, 이어지는 재시도는 정상 생성 — 2026-08-09 Sprint 38 추가) |
| 9 | Registry | 구독 게이트, 무료 한도, 소유권 격리, 미완료 다운로드가 파일이 아님, **실제 성공 다운로드**(200, 파일 바이트 일치, Content-Disposition), **경로 탐색 방어**, **중복 신청 방지**(같은 물건 재신청 시 동일 id 반환·무료횟수 불변·행 수 불변, FAILED 이후 재시도는 허용 — 2026-08-09 Sprint 37 신규, `docs/BUGS.md` #19) |
| 10 | Registry overage | 한도 초과 → `PAYMENT_REQUIRED` → 결제 → `payment_id` 연결, **결제 실패 후 재시도**(provider 일시 교체로 FAILED 강제 — 실패 시 대상 신청이 미연결 상태로 남아 재시도 가능함을 확인 — 2026-08-09 Sprint 38 추가) |
| 11 | Admin | 키 없음/오답 403, 필터, **상태 전이 규칙 전수**, `completed_at`, 없는 파일에 거짓 성공 없음, **동시 상태전이 레이스 방지**(`test_race_conditions.py` — 같은 신청에 다른 목표 상태로 동시 PATCH 시 정확히 1건만 성공, 진 쪽 필드가 섞이지 않음 — 2026-08-09 Sprint 39, `docs/BUGS.md` #21) |
| 12 | Payment Provider | `kginicis` 선택, **6개 메서드가 전부 `NotImplementedError`**(실연동 전 결제가 성공한 것처럼 보이는 사고 방지), 폐기 후보 2종, 알 수 없는 값, 미설정 기본값 |
| 13 | 정렬 결정성 | 동일 타임스탬프 행에서도 목록 순서가 호출마다 동일하고 `id` 내림차순 전순서인지 |
| 14 | 구독 플랜 tie-break | 같은 `started_at`의 BASIC→PRO 업그레이드에서 한도 10이 나오는지 (`docs/BUGS.md` #16) |
| 15 | 가격 미러 정합성 | 프론트 `PLAN_OPTIONS`와 서버 `PLAN_CATALOG`의 한도·정상가·청구액이 일치하는지 |
| 16 | API 표면 고정 | 엔드포인트 23개 집합이 그대로인지(사라짐/추가 둘 다 검출), **OpenAPI 생성 시 경고 0건**, HEAD 프로브가 GET과 같은 상태코드를 주는지 |
| 17 | 응답 envelope | 인증 라우트 5종이 `{success, data, message}` 계약을 유지하는지 / 공개 라우트(search)는 flat 형태 유지 |
| 15 | Plan API | `GET /api/v1/plans`가 `PLAN_CATALOG`와 일치하는지, 응답 금액 그대로 결제가 통과하는지, **프론트에 가격 하드코딩이 되살아나지 않았는지** |
| 18 | CORS 설정 | 미설정 시 `*`, `CORS_ALLOW_ORIGINS` 지정 시 그 목록만 파싱되는지 |
| 19 | Admin 권한 2단계 | 키별 등급 판정, ADMIN은 조정 불가(403)·SUPER_ADMIN은 가능, 기존 ADMIN 운영 하위호환 |
| 20 | registry_credit | GRANT/DEDUCT/RESET 원장 계산, RESET 이후만 유효, 입력 검증, 한도 0 하한, 이력·수행자 기록 |
| 21 | 결제 로그/Webhook | 3단계 기록·순서·연결, 소유권 격리, 민감정보 마스킹, `event_id` 멱등성, **Admin 전용 조회**(`GET /admin/payments/{id}/logs`, 2026-08-09 신규 — 이전까지 테스트 0건이던 라우트) |
| 22 | 크롤러 식별키 | `auction`/`auction_item` 제약 고정, 두 법원 공존(롤백 검증) |
| 23 | FK 런타임 강제 | 기본 커넥션 `ON`, 고아 INSERT 차단, 마이그레이션 커넥션은 `OFF` |
| 24 | Payment 상태머신 | 허용/금지 전이, 레거시 `SUCCESS` 환불 가능, 종결 상태, 알 수 없는 상태 거부 |
| 25 | Subscription Lifecycle | 전이 규칙, 자동 만료(정상/유예/만료), **이용권 게이트 6종**(active/grace/expired/paused/cancelled/none), 유예 중 플랜 한도 유지, 갱신, 해지 불가역 |
| 26 | audit / credit 로그 | 감사 로그 기록·필터·before/after, credit 변동 로그·balance_after·actor, **사용(USAGE) 로깅 + 한도 이중차감 없음** |
| 27 | Admin REST 구조 | 기존 경로 유지 + 새 경로 동일 결과, meta.total, 권한 게이트, 구독 전이 400/404 |
| 28 | Soft Delete 컬럼 | `deleted_at`/`deleted_by` 존재, 기존 DELETE 동작 무변경 |

---

## 1-1. 테스트 Audit — "통과"가 아니라 "잡아내는가"

테스트가 전부 통과했다는 사실만으로는 그 테스트가 무언가를 지키고 있다는 증거가 되지 않는다.
일부러 코드를 망가뜨렸을 때 실패해야 비로소 의미가 있다.

2026-08-07 변이(mutation) 검증: 8가지 결함을 주입 → **8/8 전부 검출**.
그 과정에서 실제 테스트 공백 1건을 발견해 보강했다(이용권 게이트가 DB에 `GRACE_PERIOD`로
저장된 행을 한 번도 쓰지 않아, 조회 조건에서 그 상태를 빼먹어도 통과했다).

새 회귀 테스트를 추가할 때는 **그 테스트가 실패하는 것을 한 번 확인**하고 커밋한다
(해당 코드를 잠깐 망가뜨려 보는 것으로 충분하다).

---

## 2. 품질 게이트 (변경 시 매번)

```bash
npx tsc --noEmit    # Type Check — 통과해야 함
npx eslint .        # Lint — 2026-08-07 기준 0 오류
npm run build       # Next.js 빌드 — 통과해야 함
```

---

## 3. 수동 확인이 필요한 영역 (자동화 미적용)

자동 테스트로 덮이지 않는 부분. 회귀 위험이 있는 변경에서만 수행한다
(`docs/APPROVAL_POLICY.md`: 코드 분석 → 로그 → 서버 → API → **마지막에** 브라우저 QA).

- 회원가입 / 로그인 / 로그아웃 — Supabase Auth 실계정이 필요해 자동화하지 않는다.
  로그아웃 버튼은 현재 `/properties` 화면에만 있다(`docs/BUGS.md` #15)
- 등기부 다운로드 — 실제 파일을 `registry_documents/`에 두고 Admin으로 `doc_url`을 연결한 뒤
  브라우저에서 저장되는지 확인(백엔드 응답까지는 9~11번이 검증)
- 크롤링 파이프라인(`mvp_scraper.py` → `migrate_execute.py`) — courtauction.go.kr에 실제
  요청을 보내므로 회귀 테스트에서 실행하지 않는다

### 실행할 수 없는 테스트 (환경 제약)

- `selenium`/`webdriver-manager`/`pandas`/`python-jose` **전부 이 환경에 설치되어 있다**
  (2026-08-08 재확인). 이전 버전 문서의 "selenium 미설치"/"python-jose 미설치"는 둘 다 stale —
  jose는 2026-08-08(Sprint 32) 승인 하에 설치 완료됐고, `test_api_regression.py`/
  `test_subscription_policy.py`가 이제 실제로 실행된다(위 1절 참고).
- 그럼에도 `test_db.py` 등 크롤러 계열 스크립트는 여전히 회귀에서 **자동 실행하지 않는다** —
  import 실패가 아니라 **실제로 courtauction.go.kr에 크롤링 요청을 보내는 스크립트**이기
  때문이다(위 "수동 확인이 필요한 영역"과 동일한 이유). 코드/의존성 문제는 이제 없다.

---

## 4. 테스트하지 않는 것 (기능 자체가 없음)

이전 버전 문서가 "완료"로 표시했던 항목의 실제 상태다.

- **이미지**: 물건 사진/이미지 기능이 코드에 존재하지 않는다
- **권리분석**: `src/app/properties/[id]/rightsAnalysis.ts`는 REGISTRY 소스를
  `available:false`로 하드코딩한 스텁이다. 등기부 파싱 테이블/파이프라인 자체가 없다
  (`docs/roadmap.md` "In Progress > Frontend" 참고)
- **Admin 화면**: Admin은 API만 있고 UI가 없다
