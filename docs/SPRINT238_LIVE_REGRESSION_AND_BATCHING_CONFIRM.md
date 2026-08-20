# Sprint 238 — item-level batching 재확인, 그리고 **검색 API가 지금 100% 500이다**

**날짜** 2026-08-20. 운영 DB / `.env` / 스케줄러 등록 **무변경**. 이 세션은 앞선 어떤 세션의
숫자도 재측정 없이 믿지 않았다 — 아래는 전부 이번 세션에서 직접 돌리거나 curl/브라우저로
확인한 값이다.

---

## 0. 세션 시작 시 다시 잰 기준선

```
git HEAD  e41575c / branch master / origin/master 와 동일 / working tree clean
python run_python_tests.py   통과 36 | 실패 12 | 건너뜀 3 | 판정없음 1  (단언 5,674건, 78.0s)
```

Sprint 237 이 적어 둔 "통과 46 | 실패 2"를 그대로 믿지 않고 다시 돌렸다 — **일치하지 않았다.**
실패가 2건에서 12건으로 늘었다. 원인을 하나씩 추적했다.

---

## 1. ★ 실패 12건 중 8건이 **같은 원인 하나**다 — `auction_image` 테이블 부재

이 로컬 `auction.db`(git 비추적, 환경마다 별도 사본)에 `020_create_auction_image.sql`이
적용돼 있지 않다. `docs/BETA_RELEASE_CHECKLIST.md`의 P0-C가 2026-08-17 09:03 적용을
확인하고 "해결"로 내렸던 바로 그 문제가 **이 환경에서 다시 벌어져 있다.**

```
migration_history         020_create_auction_image.sql  기록 없음(19개까지만)
sqlite_master              auction_image 테이블 자체가 없음(테이블 26개)
```

### 실제 서버로 재현 — 이번엔 test harness가 아니라 **진짜 프로세스**

```
python api_server.py 로 기동, curl 로 직접 호출

GET /api/v1/search?limit=3   -> 500  {"detail":"검색 처리 중 오류가 발생했습니다"}
GET /api/v1/item/1           -> 500  Internal Server Error
   traceback: api/v1/item.py:56  sqlite3.OperationalError: no such table: auction_image
```

**검색과 상세, 둘 다 100% 500이다.** 데이터가 있고 없고의 문제가 아니라 — 어떤 조건으로
호출해도 죽는다. Sprint 224~229가 걱정했던 "매각기일이 남은 물건이 0건이라 검색 결과가
빈 화면"보다 **더 나쁜 상태다** — 그때는 화면이 정상 렌더링되며 빈 결과였고, 지금은
API 자체가 죽는다.

### 이 하나의 원인이 설명하는 실패 목록

```
python                      test_http_conditional.py     (썸네일 조회가 auction_image 를 짚는다)
                             test_id_bounds_sweep.py      (thumbnails.py 동일 쿼리)
                             test_api_cache_headers.py    (§4 이미지 304 검증이 auction_image 를 직접 SELECT)
                             test_search.py                (search 500 -> KeyError 'address_detail' 대신)
                             test_admin_secret_contract.py (부수 확인 중 /search 호출)
                             test_api_regression.py        (test_search() 에서 KeyError 'size')
                             test_auth_jwks_robustness.py  (10개 x /search, /item/1 대상)
                             test_auth_jwt.py               (3건, 전부 "-> 200 -> 500")
                             test_beta_journey.py           (1단계 익명 검색에서 KeyError 'total')
node --test tests/*.test.mjs                                (frontend-contract 다수, 백엔드 500 그대로 전파)
```

**서로 다른 9개 파일의 실패가 아니라 같은 결함의 9개 증상이다.** 이 구분이 중요하다 —
"실패 12건"으로 보고하면 문제의 크기를 잘못 전달한다.

### test_bootstrap.py 도 같은 사실을 다른 각도에서 확인해준다

이 테스트는 자체 임시 DB에서 **부트스트랩 전 과정**(init_db → migrate_v4_1 → run_migrations)을
새로 돌린다. 그 fresh DB는 `020_create_auction_image.sql`까지 정상 적용된다. 그리고
**그 fresh 스키마와 지금 이 저장소의 `auction.db`를 대조해서 컬럼/인덱스 드리프트를 잡는다** —
정확히 이 결손을 가리키며 FAIL 한다("새로운 컬럼/인덱스 드리프트 감지(fresh에는 있는 것)").
`test_schema_hygiene.py` §3("모든 .sql 파일이 적용 기록에 있는지")도 같은 파일 하나를 지목한다.
**세 개의 독립된 가드(라이브 서버 curl, bootstrap 드리프트, migration_history 완전성)가 전부
같은 결론에 도달했다** — 측정 오류가 아니다.

### 조치 — 승인 필요, 이 세션은 실행하지 않았다

```
python -m storage.migrations.run_migrations
python test_schema_hygiene.py   # §3 통과 확인
```

`docs/CLAUDE.md`의 "DB 스키마 변경은 반드시 사용자 승인 후 진행한다" 원칙과, 이 저장소가
Sprint 187/189에서 **같은 명령을 실행하지 않고 승인을 기다린** 전례를 그대로 따랐다.
이 로컬 DB는 gitignore 대상이라 원격 서버나 다른 세션의 사본에는 이미 적용돼 있을 수
있다 — **배포/운영 환경에서 별도로 확인할 것.**

---

## 2. ★ 스케줄러 — 처음으로 "등록은 있는데 실행이 실패한다"를 확인했다

이전 세션들은 전부 "등록 0개"를 확인했다. 이번엔 달랐다.

```
Get-ScheduledTask (254개 전수) 중 이 저장소를 가리키는 것    DOJOONPASS_DAILY 1개 (Ready)
                                                            DocWorker / PriorityRefresh 관련   0개 (변동 없음)

DOJOONPASS_DAILY 정의   Trigger: 매일 03:00 (StartBoundary 2026-08-04)
                        Action:  cmd /c "...\dojoonpass\run_daily.bat"

LastRunTime             2026-08-20 22:01:17   (오늘, 그런데 03:00이 아니다)
LastTaskResult          0x800710E0  ->  net helpmsg 4320: "관리자 또는 운영자가 요청을 거부했습니다"
NumberOfMissedRuns      0
```

즉 작업 자체는 **살아서 등록돼 있다**(과거 세션들이 걱정한 "0개"가 아니다). 그런데
가장 최근 실행이 **권한 거부로 즉시 실패**했다. `docs/SPRINT112_SCHEDULER_HANDOFF.md`가
이미 경고한 것과 같은 계열의 실패다 — 기본 등록은 `LogonType Interactive`라 로그온 상태가
아니면 돌지 않는다.

### 그런데 데이터는 08-18까지는 실제로 들어왔다 — 모순처럼 보이지만 아니다

```
auction_item.crawl_date 최신값      2026-08-18
logs/daily_run.log 마지막 완료      "Finished at 2026-08-18  4:46:08" (310건, PASS 100%)
                                     그 이후(08-19, 08-20 새벽) 기록 없음
auction_item.auction_date 최신값    2026-08-31   (미래 기일 129건 존재 — 검색 자체는 살아있었다면 빈 화면이 아니었을 것)
```

**해석**: 08-18 새벽까지는(로그온 상태였거나 수동 실행으로) 정상 수집됐고, 그 이후
로그온 세션이 끊긴 시점부터 스케줄 실행이 4320으로 실패하기 시작한 것으로 보인다.
지금 이 세션 도중의 22:01 실행도 같은 코드로 실패했다 — **지금 이 순간도 크롤이 멈춰
있다.** 이틀치(08-19, 08-20) 신규 수집 공백이 실제로 발생 중이다.

★ 이전 세션들의 교훈("`LastTaskResult 0`은 데이터가 쌓였다는 뜻이 아니다")을 뒤집어
적용했다: 이번엔 **`LastTaskResult`가 실패인데 과거엔 데이터가 쌓였다** — 그 둘을
같은 날의 것으로 섞지 않는 것이 핵심이다. 등록 시점부터 지금까지 동일한 조건이
아니었을 수 있다(로그온 상태 변화).

### 조치 — 승인 필요 (`docs/BETA_RELEASE_CHECKLIST.md` P0-A 계열, 3가지 중 택1)

```
1. 01:50~06:00 시간대에 로그온 상태 유지
2. -RunWhetherLoggedOn 으로 재등록 (계정 비밀번호 입력 필요)
3. Python 을 머신 전역에 설치 후 SYSTEM 계정으로 등록
```

DocWorker/PriorityRefresh 작업은 여전히 등록 자체가 없다 — 이 부분은 이전 세션들의
결론과 변동 없다.

---

## 3. Admin API 키 / JWT — 이번 세션의 값 (열람하지 않고 이름·길이만)

`.env`가 세션마다 바뀌어 온 이 저장소의 패턴이 이번에도 반복됐다. `python-dotenv`로
실제 로더와 같은 방식으로 확인했다(비밀값은 출력하지 않음, 존재 여부와 길이만):

```
ADMIN_API_KEY           PRESENT (75자)   <- Sprint 233(08-20 이전 세션)엔 없었다. 지금은 있다
SUPER_ADMIN_API_KEY     PRESENT (74자)   <- 동일
PAYMENT_WEBHOOK_SECRET  없음              <- 계속 없음 (여러 세션째 동일)
SUPABASE_JWT_SECRET     없음              <- ★ Sprint 78/134가 "있다"고 적었던 것과 다르다
SUPABASE_URL            없음 (다만 NEXT_PUBLIC_SUPABASE_URL 로 폴백됨, 정상 설계)
```

`api/auth.py`를 코드로 추적한 결과, `SUPABASE_JWT_SECRET` 부재의 실제 영향은 제한적이다:

```
SUPABASE_URL 폴백(NEXT_PUBLIC_SUPABASE_URL) 정상 동작 -> JWKS 기반(RS256/ES256) 토큰 검증은 그대로 산다
HS256 토큰만 "SUPABASE_JWT_SECRET이 설정되지 않았습니다" 로 거부된다(auth.py:107-108)
```

Supabase 프로젝트가 기본값대로 비대칭키(JWKS)로 서명한다면 로그인/세션은 영향받지
않는다. 레거시 HS256 서명을 쓰는 프로젝트라면 인증 전체가 막힌다 — **어느 쪽인지는
이 세션에서 확인할 수 없다**(Supabase 대시보드 설정, 외부 확인 필요).

Admin API는 이번 세션 기준 **키가 존재하므로 500(설정오류)이 아니라 정상적으로 403/200을
반환할 수 있는 상태다.** 다만 이것도 다음 세션에 다시 바뀌어 있을 수 있다 — `.env`는
세션 간 영속성이 보장되지 않는 값으로 취급해야 한다(이 저장소가 반복 확인한 패턴).

---

## 4. item-level document batching — 회귀 검증 (P0 최우선 요청)

Sprint 236이 구현하고 Sprint 236/237이 검증한 batching을, **이번 세션이 다시 돌려서
재현되는지만** 확인했다(새로 측정하지 않았다 — 크롤이 막혀 있어 실거래 로그가 없다,
아래 §4.3).

### 4.1 회귀 스위트 재실행 — 그대로 통과한다

```
test_worker_batching.py   PASSED  단언 268건 (0.0s 아님, 3.6s)
test_worker_capacity.py   PASSED  단언 22건
```

두 파일 모두 이번 세션 초입의 전체 스위트 실행(§0)에서 **다른 10개 실패와 섞이지 않고
독립적으로 통과했다** — `auction_image` 결손의 영향을 받지 않는다(둘 다 자체 fixture
DB를 쓰고 실제 HTTP 서버를 거치지 않는다).

### 4.2 구현을 코드 레벨로 직접 대조했다 (grep이 아니라 읽었다)

`storage/database.py`의 `claim_next_item_rows()` / `release_queue_rows()`를 전문 읽었다.
Sprint 236 문서가 서술한 것과 실제 코드가 일치한다:

```
claim_next_item_rows()   첫 행은 claim_next_queue_item() 그대로 재사용(판단 복제 없음)
                          형제 행은 (court_code, case_no, item_no) 로 묶어 CAS UPDATE
                          claim 경쟁에서 진 형제는 continue(전체 실패로 취급하지 않음)  <- Sprint 191 결함 재발 방지 유지
                          재시도 간격(last_attempt_at)을 형제에도 동일 적용
release_queue_rows()     retry_count/last_attempt_at 을 건드리지 않음(문서 서술과 일치)
                          동적 SQL 없이 반복 UPDATE(문서가 적은 SQL 가드 회피 이유와 일치)
```

**서술과 코드가 어긋나는 지점을 찾지 못했다.** 이번 세션은 여기서 결함을 추가하지 않았다.

### 4.3 ★ 처리량/능력 숫자는 재측정하지 않았다 — 정직하게 그 이유를 남긴다

Sprint 237이 이미 "이 상수(행 23.2초/이동 15.2초)는 batching 이전, 2026-08-02 이전 로그의
것"이라고 인정했다. 이번 세션도 **그 상수를 갱신할 수 없었다** — §2에서 확인했듯 doc_worker
스케줄 자체가 여전히 등록되지 않았고, 08-18 이후 크롤도 권한 오류로 막혀 있어 이 기간의
`logs/doc_run.log`/`logs/doc_collect.log`에 batching 코드가 실제로 만든 새 로그 행이 없다
(`doc_collect.log`의 최신 갱신은 이번 세션이 회귀 테스트를 돌리며 생긴 것 — 즉 **테스트
fixture의 흔적이지 실거래 흔적이 아니다**, 파일을 열어 직접 확인함).

따라서 Sprint 236/237의 "153건/일" · "277건/일" 숫자를 **이번 세션이 재확인했다고
말하지 않는다.** 확인한 것은:

```
회귀 스위트(mutation 8/8 + 5/5, 구조 단언)가 이번 세션에도 그대로 통과한다 -> 구현이 살아있다
실거래 처리시간/이동횟수는 doc_worker 가 한 번도 자동 실행되지 않아 잴 자료가 없다
```

★ 이 항목이 P0 최우선인데 재측정이 불가능했던 이유는 batching 코드 문제가 아니라
**§1(검색 API 500)·§2(스케줄러 권한 실패)가 doc_worker 를 돌 기회 자체를 막고 있기
때문이다.** 순서가 확정된다: 두 블로커가 먼저 풀려야 batching 의 실거래 숫자를 잴 수 있다.

---

## 5. 이번 세션에 고친 것 — 승인 없이 가능한 범위

### `test_doc_path_safety.py` 가드 위반 1건 수정

```
[FAIL] ★ 인라인 '/'->'_' 치환 사본이 없다(sanitize_path_segment()를 쓸 것)
       -> step11_report.py:45, step7_report.py:28
```

두 파일 모두 `.gitignore`가 무시하는 1회성 조사 스크립트(`docs/CLAUDE.md`가 이미
"로드베어링 코드가 아니다"로 분류)이고, 읽기 전용으로 파일 존재 여부만 확인하는
용도라 실제 경로 주입 위험은 없었다(쓰기 경로가 아니다). 그래도 저장소가 이미
`sanitize_path_segment()`로 통일해 둔 규칙과 벗어나 있었으므로, 두 곳 다 그 함수를
import해서 쓰도록 고쳤다(동작 변경 없음 — 두 스크립트가 다루는 사건번호 표본에
역슬래시나 상위 경로 탈출 문자가 없어 치환 결과는 이전과 동일하다).

```
python test_doc_path_safety.py   -> ALL DOC PATH SAFETY TESTS PASSED (이전: FAILED 1)
```

DB/`.env`/스케줄러/git 관련 항목은 전부 승인 영역이라 **이 세션은 코드를 그 외에는
건드리지 않았다.**

---

## 6. 이번 세션 종료 시 재실행한 전체 스위트

```
python run_python_tests.py   통과 37 | 실패 11 | 건너뜀 3 | 판정없음 1  (test_doc_path_safety.py 회복)
```

남은 실패 11건은 전부 §1 의 `auction_image` 결손 하나로 설명된다(§1 목록의 9개 파일 +
`test_bootstrap.py`/`test_schema_hygiene.py`의 드리프트 감지 2건 = 11. 크롤 계열 3건은
이미 알려진 것과 무관하며 SKIPPED로 별도 집계). node 스위트도 같은 원인으로 다수 실패
(수치는 §1 표 참고, `frontend-contract.test.mjs`가 백엔드 500 을 그대로 전파).

tsc / eslint: 0 / 0 (변동 없음, 클린).

---

## 7. 다음 (전부 승인 필요, 이 세션은 SKIP했다)

```
1. migration 020 적용            검색/상세 API 를 살리는 유일한 방법. 가장 값싸고 가장 급하다
                                 (python -m storage.migrations.run_migrations)
2. DOJOONPASS_DAILY 실행 계정    4320 오류 해소 — 로그온 유지 / RunWhetherLoggedOn / 전역 Python 중 택1
3. DocWorker/PriorityRefresh 등록  여전히 0개. 1·2가 풀려도 이 등록이 없으면 batching 실거래 재측정 불가
4. SUPABASE_JWT_SECRET 값 확인    Supabase 프로젝트가 HS256 서명을 쓰는지 대시보드에서 확인 필요
5. batching 실거래 재측정        1~3 이 풀린 뒤에만 가능(§4.3)
```
