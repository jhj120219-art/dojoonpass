# Sprint 246 — 작업 디렉터리 의존을 끝까지 걷어내고, "설정이 없을 때"의 실패 방식을 고정했다

**날짜** 2026-08-21. HEAD `9c1f8ed` / branch `master` / **커밋·푸시 없음**.
운영 `auction.db` 무변경(읽기 전용) / `.env` **무변경** / 스케줄러 등록 없음 / 실크롤 없음.

---

## 0. 기준선 — 이번 세션 실측 (이전 문서 숫자를 믿지 않고 다시 쟀다)

```
세션 시작 시점              통과 48 | 실패 1 | 건너뜀 3 | 판정없음 1   (단언 7,604건)
세션 종료 시점              통과 48 | 실패 1 | 건너뜀 3 | 판정없음 1   (단언 7,652건, 158.9s)
node  npm run test:frontend  150개 / 146 PASS / 1 FAIL / 3 SKIP  (변동 없음)
tsc --noEmit  0 / eslint  0
```

실패 1건(python `test_pipeline_integrity.py`, node `frontend-contract`)은 **같은 원인**이다 —
크롤이 멈춰 매각기일 남은 물건이 0건. DB 는 1,876건으로 비어 있지 않다. 승인 영역이라 그대로 둔다.

---

## 1. `load_dotenv()` 호출 전수 — 남은 cwd 의존 0건

목표가 요구한 전수 조사를 했다(`grep -rn load_dotenv --include=*.py`).

```
api/auth.py:41   load_dotenv(os.path.join(_REPO_ROOT, ".env"))              <- 파일 기준
api/auth.py:44   load_dotenv(os.path.join(_REPO_ROOT, ".env.local"), ...)   <- 파일 기준
api_server.py:8  load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
```

**제품 코드에 인자 없는 `load_dotenv()` 나 상대경로 `.env` 는 남아 있지 않다.**

`.claude/worktrees/sprint95-false-success-audit/` 아래에 옛 사본이 있고 거기엔 아직
`load_dotenv()` 가 있지만, `.gitignore:129` 가 `.claude/` 를 통째로 무시하며
`git ls-files .claude/worktrees` 는 **0행**이다. 추적되지도, 실행되지도 않는 잔재다.

---

## 2. ★ 두 번째 cwd 의존 — **DB 경로**를 찾아 고쳤다 (P0, 수정 완료)

Sprint 245 는 `.env` 만 봤다. 같은 결함 계열을 전수로 훑다가 더 나쁜 것이 나왔다.

```python
# storage/database.py:9  (수정 전)
DB_PATH = "auction.db"
```

### 왜 `.env` 건보다 나쁜가 — **조용히 성공한 척한다**

`sqlite3.connect()` 는 파일이 없으면 **묻지 않고 새로 만든다.** 그래서 저장소 루트가
아닌 곳에서 서버를 띄우면 예외가 나는 게 아니라 **빈 DB 가 생긴다.**

실측(같은 코드를 별도 프로세스로 cwd 만 바꿔 임포트, 2026-08-21):

```
cwd = 저장소 루트   auction_item 1,876행                       -> 정상
cwd = 다른 폴더     그 폴더에 0바이트 auction.db 가 생성됨
                    모든 조회가 no such table: auction_item
```

환경변수가 비면 500 으로 시끄럽게 실패하지만, 이쪽은 **"데이터가 없습니다"** 로 보인다.
운영자는 크롤이 안 돈 줄 알고 크롤러를 뒤진다. 원인은 작업 디렉터리다.

### 고침 — 파일 위치 기준 절대경로

```python
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, "auction.db")
```

`PROJECT_ROOT` 는 이미 이 파일에 있던 값이다. `DB_PATH` 를 그 아래로 옮겨 재사용했다.
**모듈 변수라는 점은 그대로**라, 테스트/도구가 `db.DB_PATH = ...` 로 갈아끼우는 기존 방식은
아무것도 바뀌지 않는다(실제로 `test_search.py` 등이 그 방식을 쓰고 전부 통과한다).

재측정:

```
A. 저장소 루트   auction_item 1,876행
B. 다른 디렉터리 auction_item 1,876행 / 그 폴더에 auction.db 가 생겼는가: False
C. 다른 디렉터리에서 API 기동
     GET /api/v1/search   -> 200
     GET /api/v1/item/505 -> 200 (사진 5장)
     GET /api/v1/favorites-> 401 (정상. 500 아님)
```

---

## 3. 회귀 검사 — 목표가 요구한 7개 항목 전부

`test_bootstrap.py` + `test_auth_jwt.py` 에 신설. **별도 프로세스를 다른 cwd 에서 띄운다** —
같은 프로세스 안에서는 이미 임포트된 모듈 변수와 `os.environ` 이 남아 재현되지 않는다
(그러면 검사가 공허해진다).

```
요구 항목                                    검사 위치                   결과
--------------------------------------------------------------------------------
정상 cwd 에서 성공                            test_auth_jwt / bootstrap   PASS
다른 cwd 에서도 성공                          test_auth_jwt / bootstrap   PASS
잘못된/없는 env -> 안전한 실패                 test_auth_jwt §설정         PASS (6건)
JWT_SECRET 정상 -> 인증 정상                  test_auth_jwt §4            PASS
Secret 없음 -> 의도된 인증 실패                test_auth_jwt §설정         PASS
공개 API 가 Secret 문제로 500 이 되지 않음     test_auth_jwt §설정         PASS
상대경로로 되돌리는 mutation 을 잡는가          아래 §5                    잡힘
```

공개 API 는 6개 경로를 전수로 본다(`/`, 검색, 지역, 통계, 요금제, 상세). 시크릿을 통째로
비운 상태에서 **하나도 500 이 되지 않는다.** 보호 API 3개는 전부 거부한다.
실패 응답에 **시크릿 문자열도 스택트레이스도 들어가지 않는 것**까지 확인한다.

검사는 시크릿 값을 절대 출력하지 않는다 — **존재 여부와 길이만** 본다.

---

## 4. ★ 그 과정에서 찾은 진짜 구멍 — **빈 시크릿 = 인증 우회**

mutation 을 돌리다가 하나가 살아남았다.

```
MUT-F1  api/auth.py 의  if not SUPABASE_JWT_SECRET: raise JWTError(...)  삭제
        -> 전체 테스트 통과 (★생존★)
```

**동등 변이인지 먼저 의심했다.** 아니었다. 실측:

```python
tok = jwt.encode({"sub": "attacker"}, "", algorithm="HS256")
jwt.decode(tok, "", algorithms=["HS256"])   # -> ★통과★  sub=attacker
```

HMAC-SHA256 은 **빈 키도 정상 키다.** 즉 시크릿이 비면
"아무도 로그인 못 한다"가 아니라 **"누구나 아무 사용자로 로그인된다."**

`get_current_user` 의 `if not SECRET and not URL: 500` 가드는 **이걸 막지 못한다** —
`SUPABASE_URL` 이 살아 있으면 통과하기 때문이다. 그리고 그게 **지금 이 저장소의 실제
상태다**(Sprint 245 실측: `.env` 의 `SUPABASE_URL` 은 비었지만 `.env.local` 폴백으로 40자).

**제품 코드는 옳다** — 그 한 줄이 정확히 이걸 막고 있다. 문제는 **아무도 그걸 검사하지
않았다는 것**이다. 지우면 조용히 통과하는 상태였다. 검사를 넣었다.

```
[PASS] ★ 시크릿이 비었을 때 빈 키로 서명한 위조 토큰을 거부한다
[PASS] ★ 검증 함수 자체가 빈 시크릿으로 HS256 을 검증하지 않는다
```

---

---

## 4-B. 세 번째 cwd 의존 - **중복 실행 방지 락이 무력화돼 있었다** (P1, 수정 완료)

`.env` 와 `DB_PATH` 를 고치고 같은 계열을 전수로 훑다가 **가장 나쁜 것**이 나왔다.

```python
# doc_worker.py:47 / mvp_scraper.py:45  (수정 전)
LOCK_PATH = os.path.join("logs", "doc_worker.lock")
```

락 파일 경로가 상대경로다. 즉 **작업 디렉터리가 다르면 서로 다른 락 파일을 본다.**
실측(별도 프로세스 3개, 2026-08-21):

```
A (저장소 루트)에서 획득   -> True
B (같은 cwd)에서 획득      -> False    <- 정상적으로 막힌다
C (다른 cwd)에서 획득      -> **True**  <- 막히지 않는다
                              ABS = ...qa_lock_xxxx/logs/doc_worker.lock
```

### 왜 이게 가장 나쁜가 - 아무 흔적도 안 남는다

`DOWNLOAD_DIR` 은 모든 `doc_worker` 실행이 **공유한다**(Sprint 142 가 락을 넣은 이유가
바로 이것이다 - 한쪽이 받은 파일을 다른 쪽이 자기 것으로 착각하는 교차 오염).
락이 갈라지면 워커 두 개가 같은 큐를 이중 claim 하고 같은 폴더에 동시에 내려받는다.

그런데 **양쪽 로그 모두 "락 획득 성공"** 이다. 앞의 두 결함은 최소한 500 이나
"no such table" 로 티라도 났지만, 이건 **정상 동작처럼 기록된다.**

기존 검사 `test_lock_prevents_concurrent_run` 은 이걸 못 잡는다 - **같은 프로세스,
같은 cwd** 에서만 확인하기 때문이다. cwd 가 갈리는 순간이 정확히 사각지대였다.

### 고침 + 재측정

`_HERE = os.path.dirname(os.path.abspath(__file__))` 기준으로 바꿨다.
`logs/` 생성과 로그 파일 경로도 같이 정리했다(`mvp_scraper.py`, `collect_documents.py`,
`refresh_priority.py`).

```
A (저장소 루트) -> True
B (같은 cwd)    -> False
C (다른 cwd)    -> **False**   ABS = dojoonpass/logs/doc_worker.lock  (같은 파일)
다른 폴더에 logs/ 가 생겼는가: False
```

---

## 4-C. 네 번째 - 크롤 오류 기록이 흩어지고 있었다

`crawler/court_crawler.py:log_error` 가 `open("logs/errors.jsonl")` 였다.
다른 cwd 에서 크롤하면 오류 기록이 그 폴더로 흩어지고, `except Exception: pass` 가
있어 **아무도 모른다.** Sprint 98 이 막으려던 "조용한 실패"와 같은 계열이다
(원인만 다르다 - 디렉터리 부재가 아니라 경로 자체가 다른 곳).

경로를 모듈 상수 `ERROR_LOG_PATH` 로 올리고 저장소 루트 기준으로 바꿨다.

**여기서 기존 테스트가 하나 깨졌고, 그게 옳았다.** `test_crawl_error_log.py` 는
임시 디렉터리로 `chdir` 해서 격리했는데 - 그 격리는 **경로가 cwd 에 의존한다는
제품 결함에 얹혀 있었다.** 결함을 고치자 당연히 못 쓰게 됐다.

그래서 제품에 제대로 된 seam 을 만들었다. `doc_worker.LOCK_PATH` 가 이미 쓰는 규칙
(모듈 변수를 **호출 시점에** 읽어 테스트가 갈아끼울 수 있게 한다)을 그대로 따랐다.
테스트는 `chdir` 대신 `court_crawler.ERROR_LOG_PATH` 를 임시 경로로 바꾼다.
검사 강도는 그대로이고, cwd 비의존 검사 5건이 **추가**됐다.

---

## 4-D. 운영 도구 8개 - 같은 결함, 낮은 심각도

git 이 추적하는 운영/점검 스크립트 8개가 전부 `DB_PATH = "auction.db"` 였다.
다른 cwd 에서 실행해 **실측**했다(임시 폴더라 운영 DB 는 닿지 않는다):

```
backfill_* 3개 / detect_stale_* / repair_*    rc=1  0바이트 auction.db 생성 + no such table
cleanup_orphans_dryrun / measure_endless_*    rc=1  mode=ro 라 찌꺼기 없이 "unable to open"
unlock_retry                                  rc=2  인자 검사에서 먼저 멈춤
```

**8개 모두 조용히 성공하지는 않는다** - 여기서 정직해야 한다. API 처럼 "200 인데 0건"
으로 거짓말하지는 않고, 전부 0 아닌 종료 코드로 죽는다. 심각도는 **P2** 다.
다만 5개는 찌꺼기 0바이트 DB 를 남기고(나중에 그 폴더에서 크롤을 돌리면 그 빈 DB 에
쓴다), 오류 문구가 진짜 원인(작업 디렉터리)을 가린다. 한 줄씩 고쳤다.

수정 후 재측정: 세 dry-run 도구 모두 다른 cwd 에서 `rc=0`, 찌꺼기 DB 없음.

---

## 4-E. 재발 방지 - 저장소 전체 소스 가드

같은 결함이 한 세션에 **네 계열**로 나왔다. 개별 회귀 검사만으로는 다음 것을 못 막는다.
`test_schema_hygiene.py` 에 저장소 전체를 훑는 검사를 넣었다.

문자열 grep 이 아니라 **AST** 로 본다. `git ls-files` 로 추적되는 제품 `.py` 85개에서:

```
(A) 모듈 최상위 상수 할당   DB_PATH = "auction.db"
(B) 경로 인자를 받는 호출    open("logs/x.jsonl") / os.path.join("logs", ...) / makedirs("logs")
```

### 이 검사는 자기 자신을 먼저 검사한다

"0건 통과"가 **결함이 없다**는 뜻인지 **검사가 눈멀었다**는 뜻인지 구분해야 한다.
그래서 알려진 결함 3종과 고쳐진 모양을 검사 안에 박아 두고 매번 확인한다.

**이 자기 검증이 즉시 값을 했다.** 초판은 `os.path.join("logs", ...)` 를 못 잡았다 -
`"logs"` 는 확장자도 구분자도 없어서 경로로 안 보였기 때문이다. 하필 그게 4-B 의
LOCK_PATH 결함 모양이다. 자기 검증이 그것을 잡아내 범위를 넓혔고, 넓히자 이번엔
`cols.remove("has_status_pdf")` 를 경로로 오해했다(리스트 메서드와 이름이 겹친다).
그래서 맨 디렉터리 이름까지 잡는 것은 **디렉터리를 확실히 받는 호출**
(`makedirs`/`mkdir`/`join`)로 제한했다.

측정이 이상하면 제품보다 도구를 먼저 의심하라는 원칙 그대로다 - 두 번 다 도구가 문제였다.

---

## 4-F. 후속 조사 - "격리가 결함에 얹혀 있는" 검사가 더 있는가 (결론: 없다)

4-C 에서 `test_crawl_error_log.py` 의 `chdir` 격리가 제품 결함 위에 서 있었다는 것을
확인했다. 같은 패턴이 더 있는지 전수로 봤다.

`os.chdir` 를 쓰는 테스트는 7개이고, 전부 **저장소 루트로** 옮긴다
(`os.chdir(os.path.dirname(os.path.abspath(__file__)))`). 이것들이 제품의 cwd 의존을
가려 온 것인지 확인하려고, **chdir 를 빼고 다른 폴더에서** 하나씩 돌려 봤다.

```
test_admin_secret_contract.py     통과      <- chdir 없어도 된다(제품이 cwd 비의존이 됐다)
test_api_cache_headers.py         통과
test_error_logging.py             통과
test_search.py                    통과
test_max_items_contract.py        실패      <- 원인: **테스트가** 'crawler/base_crawler.py' 를
                                              상대경로로 읽는다
test_worker_capacity.py           실패      <- 원인: **테스트가** doc_worker.py 소스를 읽는다
test_image_queue_transition.py    실패      <- 원인: **테스트가** auction.db 를 상대경로로 찾는다
```

**실패 3건은 전부 테스트 자신의 소스 읽기다. 제품이 아니다.** 즉 다섯 번째 제품 결함은
없다. 이 7개의 `chdir` 는 제품을 가리는 장치가 아니라 **테스트가 소스 파일을 읽기 위한
편의**이고, 목적지가 `__file__` 기준 저장소 루트라 결정적이다.

프로세스 오염 가능성도 확인했다 - `os.chdir` 는 프로세스 전역이라 한 테스트가 다른
테스트에 샐 수 있다. `run_python_tests.py` 는 **테스트마다 별도 프로세스**로 돌리고
`cwd=ROOT` 로 못 박는다(`subprocess.run([sys.executable, name], cwd=ROOT, ...)`).
샐 경로가 없다.

TS/JS 쪽도 봤다 - `process.cwd()` 기준 경로나 상대경로 파일 읽기는 **0건**이다.

---

## 4-G. Backlog D 판정 - "실행 줄 수가 적은" 검사 3개는 **공허하지 않다**

`audit_test_reality.py` 가 의심 목록에 올린 3개를 mutation 으로 판정했다.
그 도구의 휴리스틱은 "제품 코드를 몇 줄 실행했는가"를 센다. **순수 함수는 본체가
짧아서 몇 줄밖에 안 나온다** - 그게 곧 검증하지 않는다는 뜻은 아니다. 믿을 수 있는
판정은 하나뿐이다: **결함을 심으면 우는가.**

```
ID  대상 검사                    판정     심은 결함
--------------------------------------------------------------------------------
R1  test_crawl_resume.py        [잡힘]   정확 일치 -> 부분 문자열 일치(실 DB 오탐 버그)
R2  test_crawl_resume.py        [잡힘]   재개 지점 off-by-one -> 끝낸 물건 재크롤
R3  test_crawl_resume.py        ★생존★   빈 문자열 체크포인트를 유효한 값으로 취급
C1  test_crawl_exit_code.py     [잡힘]   크롤 실패해도 종료코드 0 -> 스케줄러가 성공으로 봄
C2  test_crawl_exit_code.py     [잡힘]   수집했는데 저장 0건인 상황을 정상 판정
N1  test_runner_contract.py     [잡힘]   종료코드 != 0 인데 PASSED -> 실패가 통과로 보고됨
N2  test_runner_contract.py     [잡힘]   판정문 없는 스크립트를 통과로 셈
```

**7건 중 6건이 잡혔다. 세 검사 모두 실질적이다** - 의심 목록은 오탐이었다.

### R3 생존 - 동등 변이가 아니라 진짜 구멍이었다

`if not resume_from:` 를 `if resume_from is None:` 로 바꿔도 기존 검사가 통과했다.
동등 변이인지 먼저 의심하고 **실측**했다:

```
정상 목록 + resume_from=''              -> 두 구현 모두 0   (구분 불가)
빈 조각이 섞인 목록 + resume_from=''    -> 현행 0 / 변이 1  (갈린다)
```

기존 검사가 못 구분한 이유는, 정상 목록에서 빈 문자열이 어느 항목과도 일치하지 않아
루프가 끝까지 돌고 **결국 같은 0 을 다른 경로로** 내기 때문이다.

크롤 목록의 `case_no` 는 `" / "` 로 이어 붙는다. 뒤가 잘려 `"2026타경1005 / "` 가 되면
split 결과에 **빈 문자열 조각이 생긴다**. 그러면 빈 체크포인트가 그 항목과 "일치"해
`idx + 1` 을 돌려주고 - **첫 물건을 통째로 건너뛴다.** 오류는 나지 않는다. 조용한 누락이다.

빈 조각 목록을 쓰는 검사 3건을 추가했고, R3 은 이제 [잡힘] 이다. **생존 0건.**

---

## 4-H. Backlog F - ADMIN 키 미설정을 **부팅 시점에** 알린다 (수정 완료)

이 세션의 주제와 같은 계열이라 함께 처리했다: **조용한 실패를 시끄럽게 만든다.**

두 관리자 키가 모두 없으면 Admin API 16개가 전부 500 이다(의도된 동작이고
`test_no_keys_is_500_not_403` 이 이미 고정하고 있다). 문제는 **알게 되는 시점**이었다 -
운영자가 Admin 화면을 열어 500 을 볼 때까지 서버는 아무 말도 하지 않았다.

`api/v1/admin.py` 에 `warn_if_admin_keys_missing()` 를 넣고 `api_server.py` 부팅에서 부른다.
호출 위치는 `load_dotenv` 와 `logging.basicConfig` **다음**이다 - 더 위로 올리면
`.env` 를 읽기 전이라 멀쩡한 설정에도 거짓 경고가 나간다.

```
2026-08-21 [WARNING] api.v1.admin: ADMIN_API_KEY / SUPER_ADMIN_API_KEY 가 모두 미설정이다
  - Admin API 16개 라우트가 전부 500(관리자 키 미설정)으로 응답한다. .env 설정을 확인하라.
```

라우트 개수는 `len(router.routes)` 로 **실측해서** 찍는다(문서와 코드가 어긋나지 않는다).
키 값은 남기지 않는다. `.env` 는 건드리지 않았다(승인 영역).

### 여기서도 내가 쓴 검사 하나가 공허했다

"경고에 키 값이 들어가지 않는다"를 런타임으로 확인하려 했다. 그런데 이 함수는
**두 키가 모두 빌 때만** 경고한다 - 경고가 나가는 순간에는 **흘릴 값 자체가 없다.**
무엇을 넣어도 통과하는 검사였다.

동작으로 검사할 수 없는 성질이라 소스를 **AST** 로 본다. 문자열 검색으로는 안 된다 -
경고 문구가 `"ADMIN_API_KEY"` 라는 **이름**을 정당하게 포함하기 때문이다. 이름이 아니라
**값을 읽어 오는 호출**(`os.getenv`/`os.environ`)이 경고 인자 안에 있는지를 본다.

그 판정도 mutation 으로 확인했다:

```
MUT-A5  값을 인자로 덧붙임(형식 문자열은 그대로)  -> [잡힘] 이지만 **TypeError 로**. 가드가 아니다.
MUT-A6  형식 문자열까지 맞춰 값을 제대로 끼워 넣음 -> [잡힘] "★ 경고 인자에서 키 값을 읽지 않는다"
```

A6 가 진짜 유출 모양이고, 그것을 잡는 것이 이 가드다.

---

## 5. Mutation 판정

```
MUT-D1  DB_PATH 를 "auction.db" 상대경로로 되돌림              -> test_bootstrap  [잡힘] 3건
MUT-D2  DB_PATH 를 os.getcwd() 기준으로 바꿈                   -> test_bootstrap  [잡힘] 2건
MUT-F1  빈 시크릿 가드 삭제                                    -> test_auth_jwt   [잡힘] 2건 ※
MUT-F3  "검증 수단 없음 -> 500" 가드 삭제                       -> test_auth_jwt   [잡힘] 1건
MUT-F4  빈 시크릿 가드를 if False 로 무력화                     -> test_auth_jwt   [잡힘] 2건
MUT-F5  모든 alg 를 대칭키 경로로 흘림                          -> test_auth_jwt   [잡힘]
MUT-E1~E3 (Sprint 245) .env 경로를 상대경로로 되돌림            -> test_auth_jwt   [잡힘]

MUT-L1  doc_worker LOCK_PATH 를 상대경로로 되돌림               -> test_doc_worker  [잡힘] 4건
MUT-L2  mvp_scraper LOCK_PATH 를 상대경로로 되돌림              -> test_doc_worker  [잡힘] 1건
MUT-L3  logs/ 생성을 상대경로로 되돌림                          -> test_doc_worker  [잡힘] 1건

저장소 전체 소스 가드(test_schema_hygiene) - 네 결함 모양을 전부 짚어낸다
MUT-G1  storage/database.py  DB_PATH        -> [잡힘] storage/database.py:38  할당:DB_PATH
MUT-G2  doc_worker.py        LOCK_PATH      -> [잡힘] doc_worker.py:54  join -> 'logs'
MUT-G3  court_crawler.py     errors.jsonl   -> [잡힘] crawler/court_crawler.py:39  open
MUT-G4  unlock_retry.py      DB_PATH        -> [잡힘] unlock_retry.py:37  할당:DB_PATH
MUT-G5  mvp_scraper.py       makedirs       -> [잡힘] mvp_scraper.py:27  makedirs -> 'logs'
MUT-G6  court_crawler.py     ERROR_LOG_PATH -> [잡힘] test_crawl_error_log + test_schema_hygiene
MUT-G7  makedirs 를 상대경로로 되돌림                            -> test_crawl_error_log [잡힘]

MUT-A1  두 키 검사를 무력화(항상 False 반환)                    -> test_admin_secret  [잡힘]
MUT-A2  경고는 하되 반환값만 False 로                           -> test_admin_secret  [잡힘]
MUT-A3  api_server.py 의 부팅 호출 삭제                         -> test_admin_secret  [잡힘]
MUT-A4  경고 문구에서 환경변수 이름을 지움                       -> test_admin_secret  [잡힘]
MUT-A6  경고에 키 **값**을 끼워 넣음(형식까지 맞춤)              -> test_admin_secret  [잡힘]

R1~R3 / C1~C2 / N1~N2 (4-G, 짧은 검사 3개 판정)                  -> 7건 중 7건 [잡힘]
```

**생존 0건.**

※ MUT-F1 은 **처음엔 생존**했다. §4 가 그 결과다.

---

## 6. 내가 만든 검사에서 잡은 내 실수 2건 (제품 결함 아님)

측정이 이상하면 제품보다 도구를 먼저 의심한다는 원칙대로 확인했다.

**(1) 스스로를 무력화하는 검사.** "시크릿이 틀리면 정상 토큰도 거부한다"가 FAIL 로 떴다.
제품 결함처럼 보였지만 아니었다 — 헬퍼 `hs256()` 이 **호출 시점의 모듈 값**으로 서명한다.
시크릿을 바꾼 **뒤에** 토큰을 만들었으니 틀린 키로 서명하고 틀린 키로 검증해 **항상 통과**한다.
토큰을 바꾸기 **전에** 미리 만들도록 고쳤다. 그러자 정상 통과.

**(2) 공허한 검사.** "위조 토큰을 로그인으로 취급하지 않는다"를 `is_favorited is False` 로
판정하려 했는데, 이 테스트 사용자는 **관심물건이 애초에 없다** — 로그인이든 아니든 False 다.
아무것도 구분하지 못한다. 검증 함수가 실제로 예외를 던지는지 보도록 바꿨다.

두 경우 다 **주석에 남겼다** — 다음 사람이 같은 함정을 밟는다.

---

## 7. 최소 변경 / 인코딩 보존 확인

목표가 요구한 "전체 파일 재작성이 아닌지" 확인:

```
                          추가   삭제        |                          추가   삭제
api/auth.py               +25    -2 (S245)   | doc_worker.py             +9     -2
api_server.py             +4     -1 (S245)   | mvp_scraper.py            +11    -4
storage/database.py       +25    -2          | collect_documents.py      +9     -2
crawler/court_crawler.py  +16    -2          | refresh_priority.py       +8     -1
운영 도구 8개              +5~6   -1 each     | test_crawl_error_log.py   +80    -7
test_auth_jwt.py          +263   -0          | test_doc_worker_recovery  +121   -0
test_bootstrap.py         +87    -0          | test_schema_hygiene.py    +169   -0
```

**제품 코드 삭제가 전부 한 자릿수다.** 재작성이 아니다.
(`test_crawl_error_log.py` 의 -7 은 4-C 의 `chdir` 격리를 seam 방식으로 바꾼 것이다.)

인코딩도 HEAD 와 대조했다:

```
손댄 36개 파일 전수 대조 -> **BOM 이 바뀐 파일 0개**

storage/database.py       BOM True  (HEAD True )  LF   (HEAD LF )   <- 보존
crawler/court_crawler.py  BOM True  (HEAD True )  LF   (HEAD LF )   <- 보존
doc_worker.py             BOM True  (HEAD True )  CRLF (HEAD CRLF)  <- 보존
collect_documents.py      BOM True  (HEAD True )  CRLF (HEAD CRLF)  <- 보존
api_server.py             BOM True  (HEAD True )  CRLF (HEAD CRLF)  <- 보존
```

(작업 사본이 CRLF 인데 HEAD 가 LF 인 파일들은 `core.autocrlf` 정상 동작이다 —
git 이 저장소에는 LF 로 담는다. `git diff` 에 잡히지 않는다.)

---

## 8. 승인으로 SKIP

```
1. 실크롤 재개 / 스케줄러 등록   <- 유일한 실질 P0 의 해소 수단
2. `.env` 수정 (ADMIN 키 추가, 빈 SUPABASE_URL/ANON_KEY 정리)
3. 운영 DB 변경 (COLLECTING 2,145행 등)
4. `filter/` 3개 dead 모듈 삭제
5. 면적/특수조건 필터 처리 / `document_status` "대상 아님" 상태 신설
6. 결제 실연동 / Supabase Redirect URL 확인
7. `.claude/worktrees/sprint95-*` 잔재 정리 (추적되지 않지만 디스크에 남아 있다)
8. git add / commit / push
```

## 9. Release Blocker

```
[P0] 크롤 정지 -> 기일 남은 물건 0건 -> 기본 검색이 빈 화면 (승인 영역)
```

이번에 고친 cwd 의존 **네 계열**은 배포 방식에 따라 각각 인증 전체(1절), 데이터 전체(2절),
**중복 실행 방지(4-B)**, 오류 추적(4-C)을 죽일 수 있던 문제였고 전부 해소됐다.
4-B 는 유일하게 **로그에 흔적조차 남지 않던** 것이라 가장 위험했다.

## 10. 남은 Backlog / 다음 Sprint

```
A. 면적·특수조건 필터 — 백엔드 구현 / UI 숨김 / 안내 중 제품 선택 필요
B. `document_status` "대상 아님" 상태 — 문서 2,145행 + 사진 1,867물건
C. `audit_viewport.py --cookie` 로 로그인 화면 24칸 실측
   -> **막혔다.** 도구는 `--cookie` 를 이미 지원하지만, 실제 로그인 세션 쿠키가 필요하고
      그건 자격증명 입력이라 대신 할 수 없다. 사용자가 로그인한 탭의 `document.cookie` 를
      건네주면 그 자리에서 24칸을 잰다.
D. ~~`audit_test_reality.py` 의 "60줄 미만" 3개 검사 mutation 판정~~
   -> **이번에 완료**(4-G). 셋 다 실질적이었고, 그 과정에서 진짜 구멍 1건을 찾아 막았다.
E. 크롤 재개 후 image 4종 실벽시계 처리량 재측정
F. ~~ADMIN 키 미설정 시 부팅 경고~~ -> **이번에 완료**(4-H).
G. ~~cwd 의존 결함 계열 전수 조사~~ -> **이번에 완료**. 네 계열을 찾아 고쳤고
   `test_schema_hygiene.py` 의 소스 가드가 재발을 막는다(제품 .py 85개, 현재 0건).
H. ~~"격리가 결함에 얹혀 있는" 패턴 전수 조사~~ -> **이번에 완료**(4-F).
   chdir 를 쓰는 테스트 7개 전수 확인. 제품 결함을 가리던 것은 4-C 하나뿐이었다.
I. ~~TS/JS 쪽 같은 계열~~ -> **이번에 완료**. `process.cwd()` 기준 경로 0건.
J. ★ 신규 - `test_max_items_contract` / `test_worker_capacity` /
   `test_image_queue_transition` 이 소스·DB 를 **상대경로로** 읽는다(4-F).
   지금은 `chdir` 덕에 동작하지만, `__file__` 기준으로 바꾸면 그 `chdir` 를 지울 수 있다.
   제품 결함은 아니라 이번엔 손대지 않았다(최소 변경).
```
