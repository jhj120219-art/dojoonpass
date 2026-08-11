# Test Plan

Status: Active
Last Updated: 2026-08-11 (Sprint 53)

이전 버전(16줄짜리 체크리스트)은 "이미지 ☑", "권리분석 ☑"처럼 **존재하지 않는 기능을 완료로
표시**하고 있었고 실제로 상시 실행 중인 회귀 테스트 2종도 전혀 언급하지 않았다.
2026-08-07 코드 기준으로 다시 작성한다.

---

## 1. 자동 회귀 테스트 (상시 실행 가능)

### 1-A. Frontend 계약 테스트 (2026-08-10 Sprint 45 신규, 2026-08-11 Sprint 49~50 확장)

```bash
npm run dev                  # 먼저 서버를 띄운다 (npm run start도 가능)
npm run test:frontend        # tests/**/*.test.mjs — 64 검사 (HTTP 계약 46 + 소스 계약 10 + navContext 8)
```

`docs/FRONTEND_MASTER_SPEC.md`가 "절대 변경 금지"로 못박은 계약을 고정한다: `/` 무redirect,
첫 화면이 로그인 폼이 아님, 비로그인 목록 노출, 검색 실행의 pathname 유지, `/search` 호환,
결과→상세 링크 형태, 비로그인 상세 307 게이트, **redirect의 query string 보존**,
로그인 폼의 redirect 복귀 구조, 공개 라우트 무차단, 정렬/페이지 파라미터 비로그인 처리,
개인화 라우트(`/properties/recent`·`/favorites`) 서버 게이트, **Empty State 안내·복구 동선**,
1320px 컨테이너, 반응형 열 구성, **접근성 기본**(h1 단일/main·nav 랜드마크/select 접근 이름/lang), **Open Redirect 방어**(GET 단계 외부 origin 이탈 없음).

**Sprint 49 확장 (29 → 50 검사)** — "200이면 통과"를 넘어 실제 결과 데이터까지 본다.
기존 29검사는 정렬/페이지 파라미터를 붙여도 200인지까지만 봤기 때문에, **정렬 버튼을 눌러도
결과 순서가 그대로**인 결함(`docs/BUGS.md` #29/#30)이 전부 통과한 채로 남아 있었다.

- 정렬: asc/desc의 **렌더된 물건 id 순서가 실제로 다른가**, 화살표 표시가 백엔드 기본 정렬
  (`sort_order` 기본 `desc`)과 일치하는가, 정렬 변경 시 `page=1`로 초기화하는가
- 페이지: 1페이지와 2페이지의 물건이 **겹치지 않는가**, size 변경이 실제 건수에 반영되는가
- 페이지 범위 초과(#31): "결과 없음"으로 오인시키지 않고, 복구 링크가 **검색조건을 유지**하는가
- 검색조건: 지역 조건이 **결과 카드의 실제 주소**에 반영되는가(200만 보고 통과시키지 않음)
- 비로그인 개인화 액션 노출 정책(§8.2), 로그인 성공 후 복귀·로그아웃 복귀 경로

**Sprint 50 확장 (50 → 53 검사) — 서버 인증 게이트의 위치와 규약**

Next.js 16이 `middleware` 파일 규약을 deprecate해 `src/middleware.ts` → `src/proxy.ts`로
이전했다(로직 무변경). 게이트가 **어디에 있고 무엇을 보장하는가**를 소스 레벨로 고정한다.

- `src/proxy.ts`가 존재하고 `src/middleware.ts`가 **동시에 존재하지 않는다**
  (둘 다 있으면 Next가 빌드를 실패시킨다 — 실수로 되살아나는 것을 테스트가 막는다)
- proxy 파일이 Next 규약(`proxy` 이름의 export 또는 default) + `config.matcher`를 지킨다
- 보호 경로 목록(`['/properties','/favorites']`)과
  **`pathname + search` 전체 보존**, `supabase.auth.getUser()` 서버 검증이 그대로다

변이 테스트로 검출력 확인: `pathname + search` → `pathname`으로 되돌리면 **2검사 실패**
(기존 HTTP 검사 + 신규 소스 검사). 두 규약 파일을 동시에 두거나 export 이름을 바꾸면
Next가 앱 전체를 500으로 만들어 스위트 전체가 실패한다.

**Sprint 51 확장 (53 → 59 검사)**

- **잘못된 검색 파라미터**(`?size=500`/`?size=abc`/`?page=0`/`?sort_by=DROP` 등 6종):
  원인을 특정해 안내하는가, 서버 장애 문구를 쓰지 않는가, 복구 링크가 basePath를 유지하는가
- **레거시 라우트 정리**: `/properties`가 자체 화면을 렌더하지 않는가,
  하위 경로(`[id]`/`recent`)가 여전히 게이트되고 redirect 경로를 잃지 않는가,
  도달 불가 중복 코드 `src/login/`이 되살아나지 않았는가

**Backend `test_api_regression.py` §2-B (Sprint 51 신규, 469 → 494 검사)** — 물건종류 어휘
별칭(`docs/BUGS.md` #33)과 토큰 개수 상한(#36). 고정 건수를 단언하지 않고 **관계**로만 단언한다
(별칭 건수 >= 원본 토큰 건수 / 다중 선택은 합집합 / 과확장 없음 / 상한 초과는 400).
변이 5종 검출 확인: 별칭 표 비우기(28실패), 별칭 1개 제거(4실패), 가산성 파괴(7실패),
과확장(2실패), 상한 무력화(스위트 중단).

> **작성 교훈**: 처음에는 기대값을 `PROPERTY_TYPE_ALIASES`에서 끌어와 루프를 돌렸는데,
> **표를 비우면 루프가 0회 실행돼 아무것도 단언하지 않고 전부 통과**했다(검증 대상을
> 기대값의 출처로 삼은 자기참조 결함). 기대 목록은 테스트가 직접 들고, 구현 표는
> "그 목록을 덮는가"로만 검사하도록 바꿨다.

**Sprint 52 확장 (59 → 64 검사, 프론트)** — 기술부채 정리분 고정.
카드에 채워질 수 없는 "조회수" 자리가 없는가 / `crawl_date` 정렬이 UI에 노출되고 **실제로
순서를 바꾸는가** / **타입에 선언된 정렬을 UI가 전부 덮는가**(한쪽만 늘어나는 재발 방지) /
비로그인 저장 시 입력하던 이름이 복귀 URL에 실리는가 / `preset_name`이 검색 결과를 바꾸지 않는가.

**Backend §29~§31 (Sprint 52 신규, 494 → 569 검사)**

- **§29 환불** — 권한 경계(무인증/ADMIN 거부, SUPER_ADMIN만 허용) / 전액·부분·반복 환불 /
  멱등(`already_refunded`) / 잔여 초과·0원·음수 거부 / 상태머신 관문(FAILED 결제 환불 불가) /
  `payment_logs` CANCEL 궤적 / `audit_logs` 전후 상태·금액 기록
- **§30 Webhook** — **보안이 첫 관심사다**: 시크릿 미설정 401(fail-closed), 서명 없음/오류 401,
  본문 변조 401, 위조 시도도 감사 기록, 위조가 결제 상태를 못 바꿈. 그 다음이 정상 동작 —
  적용/멱등(재전송 시 행·로그 중복 없음)/상태머신이 막는 전이 무시/모르는 거래 무시/깨진 payload 400
- **§31 사용자 구독 조회** — 인증 필수, **소유권 격리**(B가 A의 구독을 볼 수 없음),
  파생 필드(`effective_status`/`is_entitled`/`grace_period_end`), lazy sync가 DB 상태까지 맞추는지

변이 5종 전부 검출: 서명 검증 무력화(5실패) / 상태머신 관문 제거(1) / 멱등성 제거(1) /
권한 SUPER_ADMIN→ADMIN 완화(1) / 환불 상한 제거(1).

> **작성 교훈 2**: `no test audit rows left` 검사가 **부모 행을 이미 지운 뒤에** "지금 존재하는
> qa 결제의 감사 행이 있는가"를 물어 **항상 0(공허하게 참)** 이었다. 삭제 전에 캡처한 id로
> 확인하도록 바꾸고 "dangling 감사 행 0건"을 추가했다. Sprint 51의 자기참조 결함과 같은 부류다.

**`tests/source-contract.test.mjs` (Sprint 53 신규 — frontend-contract.test.mjs에서 분리, 10 검사)**

**서버가 필요 없다.** `frontend-contract.test.mjs`의 `before()`가 dev 서버를 확인하는데,
Node 러너는 `before()` 실패 시 **그 파일의 모든 테스트를 취소**한다 — 서버가 잠깐 죽으면
서버와 무관한 소스 검사까지 사라졌다(실측: 46건 전부 cancelled). 소스만 읽는 검사 10건을
분리해, 서버가 꺼져 있어도 정상적으로 통과/실패를 보고한다.

**Backend §32~§33 (Sprint 53 신규, 569 → 616 검사)**

- **§32 Webhook 운영** — 권한 경계(ADMIN 조회 / SUPER_ADMIN 재처리) / "노티가 결제보다 먼저
  도착" 시나리오의 실제 재처리 성공 / 중복 재처리 자동 차단 / **서명 미검증은 상태와 무관하게
  재처리 불가**(가드 격리 검증) / 목록 필터 / 감사 로그
- **§33 인증 경계 전수** — OpenAPI에서 **모든 엔드포인트를 열거**해 익명 접근을 검사한다.
  분류되지 않은 신규 엔드포인트가 나타나면 실패하므로, 추가 시 공개/사용자/관리자 중 무엇인지
  **반드시 의식적으로 선언**하게 된다. 인증이 body 검증보다 먼저인지, 사용자 간 결제 격리(404)도 확인

변이 8종 전부 검출(서명 가드 / PROCESSED 재처리 / 권한 완화 / 상태머신 우회 /
oracle 재도입 / 인증 의존성 제거 2종 / 저장소 증폭).

> **작성 교훈 3**: 변이 테스트가 `FAIL 0건 + 크래시`로 나왔다 — 실패 출력에 **제품 코드의
> em-dash**가 실려 cp949 콘솔에서 죽은 것이다(`docs/BUGS.md` #43). 회귀가 "FAIL"이 아니라
> "중단"으로 보이면 성격을 오판하기 쉽다. 출력 함수 한 곳에서 인코딩을 방어하도록 고쳤다.

**`tests/nav-context.test.mjs` (Sprint 49 신규, 8 검사)** — 상세의 "이전/다음 물건" 컨텍스트
(`docs/BUGS.md` #32). 상세 화면은 로그인 필수 + 클라이언트 렌더라 HTTP 블랙박스로 관찰할 수
없어, 계산을 순수 함수(`src/app/properties/[id]/navContext.ts`)로 분리해 직접 호출한다.
Node 24의 내장 TypeScript type stripping을 쓰므로 새 의존성·빌드 단계가 없다.
변이 테스트로 검출력 확인(빈 세그먼트 필터 제거 → 2검사 실패, `i` 부재를 0으로 폴백 → 1검사 실패).

- **러너는 Node 내장 `node:test`** — 새 라이브러리를 설치하지 않았다(`docs/CLAUDE.md` 규칙).
  기존 Python 스크립트 방식과 중복되는 러너를 만들지 않기 위해 `npm run test:frontend` 하나만 추가.
- **HTTP 블랙박스**로만 검증해 번들러/트랜스파일 설정이 필요 없다.
- **DB 건수에 의존하지 않는다** — `test_search.py`가 기대 건수 노후화로 실패하는 함정을
  반복하지 않도록 구조(상태코드/링크 형태/파라미터 보존)만 단언한다.
- **자격증명을 다루지 않는다** — 비밀번호 제출과 실제 세션 파기는 범위 밖. 그래서
  `sanitizeRedirectPath()`의 Open Redirect 방어는 이 계층에서 검증되지 않는다(의도적 공백).
- 회귀 검출력 확인: `middleware.ts`를 `pathname`만 넘기도록 되돌리는 mutation 테스트로
  "redirect 파라미터가 query string 전체를 보존한다" 검사가 실제로 실패하는 것을 확인했다.

### 1-B. Backend / Crawler 회귀 테스트

별도 러너(pytest 등) 설정은 없다. 아래 스크립트를 직접 실행한다.

```bash
python test_api_regression.py       # 전 도메인 실제 HTTP 회귀 (616 검사, 2026-08-11 Sprint 53 §32 Webhook 운영 + §33 인증 경계 전수 추가, 2026-08-11 Sprint 52 §29 환불 + §30 Webhook + §31 사용자 구독 조회 추가, 2026-08-11 Sprint 51 §2-B 물건종류 어휘 별칭(#33)+토큰 상한(#36) 추가, 2026-08-09 HEAD 프로브 + Admin 결제로그 조회 + 등기부/문서 실다운로드·경로탐색 + 등기부 중복신청 방지 + 구독 중복결제 방지 + 결제 실패 후 재시도 + 2026-08-10 Sprint 43 sort_by 화이트리스트 8개 전수(정렬 결과 body까지) 검증 추가, `docs/BUGS.md` #24)
python test_subscription_policy.py  # 구독 정책/할인/월 리셋/식별키 무결성/credit 원장 (48 항목)
python test_state_machines.py       # Payment/Subscription 상태 전이·유예기간 순수 로직 (2026-08-08 신규, 82 검사)
python test_registry_credits.py     # 등기부 credit 원장 순수 로직 (2026-08-08 신규, 20 검사)
python test_auction_identity.py     # auction 식별키 무결성 + upsert_batch 법원 교차 안전성 (2026-08-08 신규, 26 검사)
python test_schema_hygiene.py       # get_connection(enforce_foreign_keys=) + soft delete 컬럼 + migration_history 완전성 (2026-08-08 신규, 8 검사)
python test_race_conditions.py      # 등기부 무료한도 + 초과결제 + 구독 + Admin 상태전이 동시 요청 방어 (2026-08-09 신규, 실스레드 22 검사, 구독 시나리오는 Sprint 38, Admin 상태전이 시나리오는 Sprint 39에서 각각 결함 수정 후 추가)
python test_intent_analyzer.py      # intent.analyzer 순수 함수 (기존, DB/API 무의존, 16 검사)
python test_normalizer.py           # normalizer.normalize_address 순수 함수 (기존, DB/API 무의존, 29 검사, 2026-08-09 cp949 크래시 수정)
python test_auth_jwt.py             # JWT 인증 체인 — ES256(JWKS, kid 선택/캐시/키회전) + HS256 레거시 + 알고리즘 화이트리스트(alg:none·알고리즘 혼동 거부) + 엔드포인트 레벨 인증필수/선택적인증 (2026-08-10 Sprint 46 신규, 23 검사, `docs/BUGS.md` #27). 자체 EC 키쌍을 JWKS 캐시에 주입해 네트워크 무의존
python test_search.py               # /api/v1/search 주소 Intent 회귀 (2026-08-10 Sprint 47 재설계, 25 검사) — 고정 row count 단언을 전부 제거하고 행 단위 검증 + 컬럼 매핑 동치 + 표기/분해 동치 + 포함 관계로 대체. 데이터가 늘어도 유효하며 mutation 테스트로 검출력 확인
python test_doc_storage_atomicity.py # crawler/doc_paths.py(Sprint 47 분리) 문서 저장 + storage/database.py 큐 완료 처리 순수 로직(Selenium 무의존) — get_doc_dir/doc_exists/원자적 쓰기(os.replace)/mark_queue_done() 부분실패 rollback (2026-08-09 Sprint 40 신규 12검사, 2026-08-10 Sprint 41 mark_queue_done rollback 검증 3검사 추가 → 15 검사, `docs/BUGS.md` #22)
python test_checkpoint_atomicity.py # storage/checkpoint.py(크롤러 재시작 이어받기) 순수 로직(Selenium 무의존) — 여러 법원 공유 파일 격리, 원자적 쓰기(os.replace), 손상 파일에도 크래시하지 않는 폴백 (2026-08-10 Sprint 42 신규, 15 검사, `docs/BUGS.md` #23)
python test_validation_log_integrity.py # validator/validation_engine.py의 logs/validation.jsonl append 순수 로직(Selenium 무의존) — 로그-결과 일치, 마지막 줄 손상이 이전 줄에 영향 없음 (2026-08-10 Sprint 42 신규, 9 검사)
python test_crawl_resume.py         # crawler/resume.py:resume_start_idx()(Sprint 47 분리) 체크포인트 재개 순수 로직(Selenium 무의존) — 정상 매칭/묶인 사건번호/체크포인트가 오늘 목록에 없을 때의 안전한 0-폴백 (2026-08-10 Sprint 43 신규, 10 검사, crawl_court() 인라인 로직을 순수 함수로 추출)
```

**2026-08-10(Sprint 45) 주의 — `test_search.py`의 3건 실패는 회귀가 아니다**:
`address_detail='서울'`/`'서울시'`/`'서울특별시'` 3개 검사가 `total=269`인데 기대값이 `284`로
하드코딩돼 있어 실패한다. 크롤러가 매일 데이터를 갱신하므로 **기대 건수가 노후화된 것**이며
(2026-08-09에도 같은 이유로 한 번 재동기화한 이력이 있다), 검색 로직 변경 때문이 아니다.
같은 파일의 응답 스키마 불변 검사와 `sido` 정규화 회귀 검사는 PASS 상태다.
근본 해결은 "절대 건수" 대신 관계(예: 시도 합계 = 하위 시군구 합계)로 단언하도록 바꾸는 것이며,
테스트 검증력을 낮추지 않는 재설계가 필요해 별도 작업으로 남긴다. Sprint 45에서 신설한
Frontend 계약 테스트(§1-A)는 이 함정을 피하려 처음부터 건수를 단언하지 않는다.

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

---

## 6. 알려진 테스트 환경 이슈 (2026-08-10 Sprint 46)

- ~~`test_doc_storage_atomicity.py`는 selenium 없이 실행되지 않는다~~ →
  **2026-08-10 Sprint 47 해결**. 같은 문제가 `test_crawl_resume.py`에도 있었다
  (`court_crawler` -> `base_crawler` -> selenium).
  순수 함수를 selenium을 import하지 않는 모듈로 분리해 해결했다(위 (a) 방향):
  `crawler/doc_paths.py`(경로 규칙), `crawler/resume.py`(재개 위치 계산).
  원본 모듈이 이름을 재노출하므로 `doc_worker.py` 등 기존 호출부는 무변경이고,
  테스트가 검증하는 함수는 **동일한 그 함수**라 검증력이 약해지지 않았다.
  selenium 설치는 여전히 하지 않았다(승인 사항).

- **`storage/`가 통째로 gitignore라 그 안의 수정은 조용히 사라질 수 있다.**
  2026-08-10 Sprint 47에 `storage/checkpoint.py`의 원자적 쓰기(BUGS #23 수정분)가
  코드에서 사라진 것을 `test_checkpoint_atomicity.py`가 잡아냈다(BUGS #28).
  git 이력이 없으므로 **이 디렉터리의 회귀 테스트가 유일한 안전장치**다.

---

## Sprint 54 추가 (2026-08-11)

### tests/rights-analysis.test.mjs (신규, 15검사)

`src/app/properties/[id]/rightsAnalysis.ts`는 순수 로직인데도 **테스트가 0건**이었다.
그 사이 신뢰도 등급이 뒤집혀 있었고(BUGS #44) HTTP 블랙박스로는 관찰되지 않았다
(`/properties/[id]`는 로그인 필수 + 클라이언트 렌더).

`nav-context.test.mjs`와 같은 방식 — 순수 함수를 직접 호출한다
(Node 24 내장 TypeScript type stripping, 새 의존성 없음).

고정한 계약:

| 상황 | 기대 등급 | 근거 |
|---|---|---|
| 현황조사서만 | MEDIUM | 대조 상대가 없다 |
| 명세서만 | MEDIUM | 대조 상대가 없다 |
| 정보원 없음 | MEDIUM | 확인된 것이 없다 |
| 둘 다 있고 인원수 일치 | HIGH | 교차 검증됨 |
| 둘 다 있고 인원수 다름 | MEDIUM | AGGREGATION_DIFFERENCE |
| 현황 0명 vs 명세서 N명 | LOW | DIRECT_CONFLICT |
| 둘 다 있으나 비교값 NULL | HIGH 금지 | 비교한 적이 없다 |

핵심 계약 한 줄: **"신뢰도 HIGH와 정보원 누락 경고는 동시에 나올 수 없다."**
화면에 실제로 함께 떠 있던 모순이라 이것 자체를 테스트로 못 박았다.

변이 감사 5종 전부 검출(5/5):
대조불가→HIGH 복귀 / `canCrossCheck` 항상 true / NULL 비교값 무시 /
SPEC 필터 제거 / DIRECT_CONFLICT 등급 하향.

### test_schema_hygiene.py §4 — requirements.txt ↔ 소스 import 일치 (신규 4검사)

의존성 목록을 사람이 관리하면 다음 import가 추가되는 순간 어긋난다. 그래서 **매번 소스에서
재도출해 비교**한다.

- 저장소의 모든 `.py`를 AST 파싱해 third-party 최상위 import를 수집
  (표준 라이브러리·로컬 모듈 제외, import 이름 → pip 배포판 이름 매핑 포함)
- **파싱 실패 파일이 하나라도 있으면 실패** — 파싱 안 된 파일의 import는 조용히 빠져
  검사에 구멍이 생기기 때문
- 양방향 검사: 목록에 빠진 것 / 목록에만 있고 아무도 안 쓰는 것

변이 감사 4종 전부 검출(4/4):
selenium 제거 / pdfplumber 제거 / 미사용 항목 추가 / `python-jose`를 `jose`로 오표기.

### 실행 불가 테스트 (3건) — 회귀 실패 아님

`test_db.py` / `test_docs.py` / `test_docs2.py`는 `selenium`을 직접 import한다.
현재 인터프리터에 selenium이 없어 `ModuleNotFoundError`로 즉시 종료된다(BUGS #46).
`pip install -r requirements.txt` 후 재실행해야 한다. **테스트가 깨진 것이 아니라
환경이 빠진 것**이므로 회귀 실패로 집계하지 않는다.

---

## Sprint 55 추가 (2026-08-11)

| 파일 | 검사 | 대상 |
|---|---|---|
| `test_crawl_exit_code.py` | 44 | 크롤/워커 성패 판정, 진입점 종료코드 전달, 배치 errorlevel·마커, 실접속 스크립트 가드 |
| `test_document_queue.py` | 16 | 큐 UNIQUE 4축 독립성, 다물건 사건 적재, 018 마이그레이션 무손실 |
| `test_document_status_sync.py` | 25 | 수집 결과가 화면 테이블까지 도달, 최종 실패만 FAILED, 경로 탈출 차단 |

세 파일 모두 **selenium 없이** 실행된다. 판정 로직을 `models/crawl_outcome.py`로 분리하고,
DB가 필요한 검사는 임시 DB(`tempfile.mkdtemp`)에 최소 스키마를 만들어 실제 함수를 호출한다.

### 테스트를 약하게 만들지 않기 위해 지킨 것

- **스키마를 테스트에 베껴 쓰지 않는다.** `test_document_queue.py`는 018 마이그레이션
  파일에서 `CREATE TABLE`을 읽어 쓴다. 손으로 베낀 스키마는 진짜 스키마가 바뀌어도
  계속 통과하고, 그것이 바로 BUGS #48이 오래 살아남은 방식이다(주석은 `item_no`가
  있다고 했고 테이블에는 없었다).
- **사유 문자열까지 고정한다.** "수집 0건"과 "저장 0건"은 손봐야 할 곳이 다르다
  (크롤러 vs 저장 계층). 둘 다 "0건"으로 뭉개면 로그를 봐도 어디를 볼지 알 수 없다.
  변이 M1이 이 느슨함을 뚫고 살아남아 단언을 강화했다.
- **배치는 블록 단위로 검사한다.** "파일 어딘가에 `[FAILED]`가 있으면 통과"는 실제로
  변이를 놓쳤다(인터프리터 분기의 마커가 다른 분기의 결손을 가렸다). 지금은 각
  실패 분기 안에서 마커를 찾는다.

### 실행 가드 (BUGS #51)

`test_db.py` / `test_docs.py` / `test_docs2.py`는 이름과 달리 테스트가 아니다 —
assert가 0개이고 실제 `courtauction.go.kr`에 접속한다. 이제 `ALLOW_LIVE_CRAWL=1` 없이는
`[SKIPPED]`를 남기고 즉시 종료한다.

회귀 스윕은 이 셋을 **"설계상 건너뜀"**으로 분류해야 한다(실패도, 환경부재도 아니다).

```
python test_api_regression.py          616검사
그 외 test_*.py 20개                   18 PASS / 3 설계상 건너뜀
npm run test:frontend                   86검사
```

### Sprint 55 프런트엔드 추가

| 파일 | 추가 | 내용 |
|---|---|---|
| `tests/source-contract.test.mjs` | 3 | 검색 파라미터 계약 — 프런트가 만드는 쿼리 키가 백엔드 파라미터를 벗어나지 않는가 |
| `tests/rights-analysis.test.mjs` | 4 | `MISSING_SPEC` vs `SPEC_NOT_PARSED` 구분, 문서 확보가 신뢰도를 바꾸지 않음 |

**검색 파라미터 계약이 왜 필요했나** — `SearchForm.buildSearchQuery()`가 백엔드에 없는
파라미터 5개(면적 4 + 특수조건 1)를 만들고 있었다. FastAPI는 모르는 쿼리 파라미터를
**조용히 무시**하므로, 값이 실리는 순간 "조건을 걸었는데 전체 결과가 나오는" 상태가 된다.
현재는 해당 UI가 "준비 중입니다" 자리표시자라 값이 실릴 수 없어 무해하지만, 그 사실이
주석에만 있었다. 미지원 목록을 테스트에 고정해 **늘어나면 실패하고, 구현되면 목록에서
빼도록** 강제한다. 변이 4종 전부 검출.

프런트엔드 합계: **93검사** (Sprint 54 기준 86 → 93)

---

## Sprint 56 추가 (2026-08-11)

| 파일 | 검사 | 대상 |
|---|---|---|
| `test_pipeline_integrity.py` (신규) | 30 | 파이프라인 단계 간 정합을 **불변식으로 고정** |
| `test_state_machines.py` §8 | 14 | 깨진 만료 시각이 안전하게, 그러나 **조용하지 않게** 처리되는가 |
| `test_race_conditions.py` §5 | 5 | TOCTOU 가드 결정적 구조 검사 |
| `test_api_regression.py` §10 | 10 | 미결제 신청의 관리자 전이/다운로드 차단 |

### 레이스 테스트는 가드를 제거해 보기 전까지 의미가 없다 (BUGS #53)

`test_race_conditions.py`는 4가지 동시성 방어를 검증한다고 돼 있었지만, 실제로 가드를
제거해 보니 **절반이 통과했다.** 스레드를 순서대로 `start()`만 해서 요청이 겹치지 않았다.

```
                                   수정 전   수정 후
BEGIN IMMEDIATE 제거 (무료한도)      2/3      4/4    Barrier + 경합 폭 10->24
조건부 UPDATE 제거 (관리자 TOCTOU)   0/4      4/4    결정적 구조 검사로 대체
```

관리자 TOCTOU는 스레드 수를 6으로 늘리자 검출률이 **오히려 1/5로 나빠졌다** —
Barrier 해제가 계단식이라 첫 스레드가 커밋을 마친 뒤에야 나머지가 SELECT에 도달한다.
창이 수 마이크로초라 실제 스레드로는 안정 재현이 불가능하다고 판단하고,
확률적 테스트(2스레드)와 **결정적 구조 검사**를 함께 두는 방식으로 바꿨다.

### "어느 가드가 막았는지"까지 봐야 한다 (BUGS #54)

기존 "미완료 다운로드" 검사는 `success == False`만 봤다. 다운로드의 COMPLETED 검사를
통째로 없애는 변이를 넣었더니 `doc_url`이 NULL이라 다른 오류로 떨어져 **그대로 통과했다.**
지금은 `error` 코드와 메시지가 실제 상태를 밝히는지까지 고정한다.

### 프런트엔드 결과는 `fail 0`만 보고 판단하지 말 것

dev 서버가 내려가 있으면 `frontend-contract.test.mjs`의 `before()`가 실패해 그 파일 전체가
**cancelled**가 된다. 그때 출력은 이렇게 보인다.

```
tests 93 / pass 45 / fail 0 / cancelled 48      exit code = 1
```

`fail 0`만 읽으면 초록으로 오인한다. **`cancelled`와 종료 코드를 함께** 봐야 한다
(2026-08-11 이 저장소에서 실제로 겪음). 하네스 자체는 정상적으로 exit 1을 낸다.

### 현재 게이트

```
python test_api_regression.py            627검사
그 외 test_*.py 21개                     19 PASS / 3 설계상 건너뜀
npm run test:frontend                     93검사 (dev 서버 필요 — cancelled 확인 필수)
```

---

## Sprint 57 (2026-08-11) — `auction.db` 되돌아감 복구, 신규 테스트는 없음

`docs/BUGS.md` #57. `test_schema_hygiene.py`/`test_pipeline_integrity.py`가 이미 갖고 있던
검사(migration_history 완전성, done↔READY 정합)가 실제로 드리프트를 잡아냈다 — 신규 테스트
작성 없이 기존 회귀가 문제를 검출한 사례. `audit_logs` dangling 698행/`document_status`
574행은 데이터 보정이며 테스트 로직 변경은 없었다.

## Sprint 58 (2026-08-12) — 환불/Webhook 재처리 동시성 커버리지 공백 해소

`docs/roadmap.md` Sprint 57 이후 배경: Admin 키가 실제로 설정된 것을 확인(§ENVIRONMENT_VARIABLES.md
갱신)한 뒤 Admin 엔드포인트 41개를 API Contract Audit으로 재점검하다, 환불(`POST
/admin/payments/{id}/refund`, Sprint 52 신설)과 Webhook 재처리(`POST
/admin/payments/webhooks/{id}/reprocess`, Sprint 53 신설) 둘 다 소스에 `BEGIN IMMEDIATE` +
조건부 UPDATE 가드가 있는데도 **동시 요청 회귀가 없었다** — 순차 재현(`test_api_regression.py`
§29/§32)만 있고 `test_race_conditions.py`에는 두 경로 모두 없었다. Sprint 38의 교훈
("순차 재현만으로는 동시성 결함을 검출 못한다")이 두 신규 경로에는 아직 적용 안 된 상태였다.

| 파일 | 검사 | 대상 |
|---|---|---|
| `test_race_conditions.py` §5 (신규) | 6 | 결제 환불 동시 요청 — 3스레드, 결제액의 절반보다 큰 부분환불을 동시에 3번 보내 총 환불액이 결제액을 넘지 않는지 |
| `test_race_conditions.py` §7 (신규) | 5 | 환불 가드 결정적 구조 검사(`BEGIN IMMEDIATE`/`WHERE id=? AND status=?`/rowcount/rollback/409) |
| `test_race_conditions.py` §8 (신규) | 3 | Webhook 재처리 가드 결정적 구조 검사(`reprocess_webhook`/`_apply_webhook_event` 공유 가드) |

### 스레드 재현은 이번에도 신뢰할 수 없었다 — 구조 검사가 실제로 잡아낸 것은 구조 검사뿐

환불 레이스(§5)에 대해 두 가지 변이를 직접 넣어 검증했다.

```
                                        §5(스레드) 검출   §7(구조) 검출
BEGIN IMMEDIATE 제거                    실패(미검출)      성공
UPDATE의 "AND status=?" 제거            실패(미검출)      성공
```

3스레드 재현은 두 변이 모두 놓쳤다(BEGIN IMMEDIATE 제거는 실행할 때마다 결과가 달라지는
진짜 flaky였고, WHERE 조건 제거는 매번 조용히 통과했다 — `BEGIN IMMEDIATE`가 전체
읽기-판단-쓰기 구간을 이미 완전히 직렬화해 그 안쪽 가드까지 창을 벌리지 못했기 때문으로
추정). Sprint 56이 Admin TOCTOU에서 이미 겪은 것과 같은 결론 — **좁은 창은 스레드 수를
늘려도 안정 재현되지 않는다** — 이 세 번째 사례로 재확인됐다. §7 구조 검사가 두 변이를
전부 결정적으로 잡아냈다(수정 후 원복해 정상 통과 확인).

### 현재 게이트

```
python test_api_regression.py            627검사 (무변동)
test_race_conditions.py                  41검사 (22 -> 41, 신규 3시나리오)
그 외 test_*.py 21개                     19 PASS / 3 설계상 건너뜀(test_db.py/test_docs.py/test_docs2.py, ALLOW_LIVE_CRAWL 가드)
npm run test:frontend                     93검사 (dev 서버 필요 — cancelled 확인 필수)
```

---

## Sprint 59 (2026-08-12) — Admin 구독 상태 변경 동시성 결함(BUGS #58) + 회귀 신설

`test_race_conditions.py`에 2개 시나리오 추가.

| 파일 | 검사 | 대상 |
|---|---|---|
| `test_race_conditions.py` §9 (신규) | 4 | Admin 구독 상태 변경 동시 요청 — 2스레드, 같은 목표(CANCELLED)로 동시 PATCH 시 정확히 1건만 성공 |
| `test_race_conditions.py` §10 (신규) | 4 | 구독 상태 변경 가드 결정적 구조 검사(`BEGIN IMMEDIATE`/`WHERE id=? AND status=?`/rowcount/rollback) |

Sprint 58의 refund/webhook 재처리 감사와 같은 방식(변이 주입 → 스레드/구조 검사 각각의
검출력 비교)으로 검증했다. 결과도 동일했다 — 스레드 재현(§9)은 두 변이(락 제거/조건부
WHERE 제거) 모두 놓쳤고, 구조 검사(§10)만 결정적으로 잡아냈다.

### 현재 게이트

```
python test_api_regression.py            627검사 (무변동)
test_race_conditions.py                  49검사 (41 -> 49, 신규 2시나리오)
그 외 test_*.py 21개                     19 PASS / 3 설계상 건너뜀
npm run test:frontend                     93검사 (dev 서버 필요 — cancelled 확인 필수)
```

---

## Sprint 60 (2026-08-12) — 만료 구독 재활성화 결함(BUGS #59) + 회귀 신설

`test_api_regression.py` §27(admin rest structure)에 11개 검사 추가: expires_at 없이
재활성화 거부(400 + DB 불변) / 형식 오류 거부(400) / expires_at과 함께면 성공(200 +
effective_status/is_entitled 일치 + DB 반영) / PAUSED→ACTIVE 재개는 영향 없음(회귀 방지).

`test_race_conditions.py` §10(구독 상태 변경 구조 검사)을 change_status()의 UPDATE 분기가
2개에서 4개로 늘어난 것에 맞춰 갱신(개수 검사만 정합화, 새 시나리오 아님).

### Sprint 60 마무리 — Release 준비 최종 검증

Commit 전 사용자 지정 11개 회귀 체크리스트를 하나씩 대조하다 ACTIVE→CANCELLED/
ACTIVE→EXPIRED가 실제 Admin 엔드포인트로는 한 번도 검증되지 않았음을 발견(내부 상태머신
순수 로직 테스트만 있었다) — `test_api_regression.py` §27에 8개 신규(638 → 646검사).
`BEGIN IMMEDIATE`/조건부 UPDATE 제거 변이를 최종 재검증(§10이 결정적으로 검출), 저장소
전체에 mutation-test 임시 코드·scratch 파일 잔여 0건 확인.

### 현재 게이트 (최종, Sprint 60 Release 시점)

```
python test_api_regression.py            646검사 (627 -> 638 -> 646)
test_race_conditions.py                  49검사 (무변동, 구조 검사 갱신만)
그 외 test_*.py 21개                     19 PASS / 3 설계상 건너뜀
npm run test:frontend                     93검사 (dev 서버 필요 — cancelled 확인 필수)
```
