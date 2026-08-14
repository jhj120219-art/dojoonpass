# Sprint 102 — 같은 패턴의 전파 차단, 문서 드리프트, 부트스트랩 멱등성 (2026-08-14)

> 앞 Sprint: `docs/SPRINT101_RETRY_LOOP_AND_TIMEZONE.md`
>
> **별도 파일 이유**: Sprint 100/101과 같다 — `docs/BUGS.md` / `docs/CURRENT_STATE.md`는
> 다른 세션의 편집 대상이라 충돌을 피했다.

Sprint 101을 끝낸 뒤 **내 작업 자체에 후속 점검을 적용해서** 나온 결과다.
"방금 고친 패턴이 다른 파일에도 있는가", "관련 호출부가 있는가", "문서와 코드가
어긋나는가" — 세 질문 전부 YES였다.

---

## #102-1 ★ 같은 시간대 결함이 **테스트 5곳**에 그대로 남아 있었다

Sprint 101은 운영 코드 4곳을 고쳤다. 그런데 같은 패턴을 다시 훑어보니
**테스트 4개 파일 5개 자리**가 여전히 UTC로 시각을 다루고 있었다.

```
test_pipeline_integrity.py   2곳   불변식 검사가 UTC 기준으로 판정
test_document_status_sync.py 3곳   픽스처 + 측정 쿼리
test_collect_documents.py    1곳   재시도 간격 경계 픽스처
test_false_success.py        2곳   INSERT 하는 타임스탬프
```

### 왜 운영 코드보다 이쪽이 더 위험한가

픽스처가 `-1 hours`라고 적어 두고 실제로는 **한국 기준 10시간 전**을 만들면,
검사는 통과하면서 **의도한 상황을 한 번도 만들지 못한다.**

이번 결함이 오래 숨어 있던 방식이 정확히 그것이다 —
**운영 코드와 검사가 같은 잘못된 전제를 공유하면 검사는 영원히 통과한다.**

특히 나빴던 두 자리:

| 위치 | 적힌 뜻 | 실제 (KST) |
|---|---|---|
| `test_pipeline_integrity.py` "하루 넘게 in_progress" 불변식 | 24시간 | **33시간** (느슨) |
| `test_pipeline_integrity.py` "기일이 남았는데 SKIPPED_EXPIRED" | 오늘 기준 | 02:00 배치 시각에 **날짜가 하루 어긋남** |

두 번째는 `doc_worker`가 만료를 판정할 때 쓰는 "오늘"
(`datetime.now().strftime("%Y-%m-%d")`, 로컬)과 검사의 "오늘"이 **서로 다른 날**이 된다는
뜻이다. 배치가 도는 02:00 KST가 정확히 그 구간(UTC로는 전날)이다.

### 조치

5곳 전부 `localtime`으로 맞췄다. **단언은 하나도 약화하지 않았고**, 픽스처가
자기가 적어 둔 시간을 실제로 만들도록 고쳤다.

---

## #102-2 §9 가드가 테스트를 안 보고 있었다 (그래서 위를 놓쳤다)

Sprint 101에서 만든 `test_pipeline_integrity.py` §9(형태 검사)는 **운영 코드만** 훑고
있었다. 그래서 #102-1을 스스로 잡지 못했다.

검사 범위를 저장소의 **모든 추적 대상 `.py`**로 넓혔다 — `api/ crawler/ storage/
validator/ normalizer/ filter/` + 루트 운영 스크립트 + `test_*.py` 전부.

**예외 목록을 두지 않았다.** 예외는 곧 "여기만 UTC여도 된다"는 두 번째 규약이 되고,
서로 다른 두 규약이 공존하는 것이 이 결함의 뿌리이기 때문이다.

범위를 넓히자마자 **내가 미처 못 찾은 5번째 자리를 즉시 잡아냈다**
(`test_document_status_sync.py:665`, 고아 큐 낭비 판정의 `date('now')`).
가드가 사람보다 먼저 찾은 첫 사례다.

---

## #102-3 `reset_failures.py`가 되살려서는 안 되는 것을 되살린다

Sprint 101의 변경으로 새로 생긴 상호작용이다. **호출부를 따라간 덕에 찾았다.**

`reset_failures.py`는 "다시 시도할 수 있게 실패를 푼다"는 뜻의 수동 운영 스크립트로,
`document_status`의 **모든** `FAILED`를 `COLLECTING`으로 되돌린다. 그런데 큐에는
**다시 시도해도 성공할 수 없는** 종결 상태가 둘 있다.

```
SKIPPED_EXPIRED       매각기일이 지나 법원 사이트에서 조회 자체가 안 된다
SKIPPED_UNSUPPORTED   수집 버튼 id가 없다 (#101-1에서 신설)
```

그 행까지 `COLLECTING`으로 되돌리면 **큐는 종결인데 화면은 영원히 "수집중"**인,
앞뒤가 안 맞는 상태가 된다(`docs/BUGS.md` #69와 같은 모양).

Sprint 101 이전에는 이런 행이 다음 날 되살아나 다시 실패하며 `FAILED`로 돌아왔다 —
즉 **무한 재시도 고리가 이 결함을 가리고 있었다.** 고리를 끊자 드러났다.

### 조치 (실 DB 복사본으로 검증)

- 종결(`SKIPPED_*`) 대응 행은 `FAILED` 그대로 둔다 — 사용자에게 "수집실패"가 사실이다
- **`--apply` 없이는 아무것도 바꾸지 않는다**(dry-run 기본). 이 스크립트는 원래
  실행 즉시 `document_collect_failures`를 통째로 DELETE 했다. 같은 저장소의
  `repair_document_status.py`가 이미 쓰는 관례를 따랐다

검증(저장소·DB를 통째로 복사해 그 위에서 실행):

```
[PASS] 종결(SKIPPED_UNSUPPORTED) 행은 FAILED 로 남는다
[PASS] 평범한 FAILED 는 COLLECTING 으로 되살아난다   (4건)
[PASS] 실패 로그는 비워진다
[PASS] DRY-RUN 은 아무것도 바꾸지 않았다
```

---

## #102-4 `docs/CLAUDE.md`가 두 군데 낡아 있었다 + 드리프트 가드 신설

CLAUDE.md는 새 개발자와 새 세션이 **가장 먼저 읽는 색인**이다. 여기가 틀리면
그 아래 모든 판단이 틀어진다.

| 문서가 말하던 것 | 실제 |
|---|---|
| "No `requirements.txt` exists — dependencies are inferred from imports" | **2026-08-11 Sprint 54에 신설돼 git이 추적 중.** 11개 전부 `==` 고정 |
| "applies numbered SQL files 001~018" | **019가 이미 있고 적용까지 돼 있다** |

첫 번째가 특히 나쁘다 — 그 서술을 믿으면 **이미 있는 핀 목록을 무시하고 import에서
의존성을 역추론**하게 된다. Sprint 54가 "Anaconda가 사라져 크롤이 멈췄는데 무엇이
설치돼 있었는지 아무 데도 없었다"는 사고 끝에 만든 파일인데, 색인은 그것이 없다고
말하고 있었다.

### 가드 (`test_bootstrap.py` §5)

문서가 **주장하는 사실을 코드로 대조**한다. 산문이 아니라 확인 가능한 주장만 본다 —
표현까지 고정하면 문서를 손볼 때마다 깨져서 오히려 신뢰를 잃는다.

```
마이그레이션 범위 "001~NNN"  <-> 실제 파일 번호의 최소/최대
번호 중간에 빠진 구간 없음
"requirements.txt 없다" 단정  <-> 파일 실재 여부
문서가 언급한 부트스트랩 파일 8개가 실재하는가
```

**함정 하나를 실제로 밟고 고쳤다**: 이 문서의 관례는 낡은 문장을 지우는 대신
**그대로 인용하고 "정정"을 붙이는** 것이다. 그래서 단순 문자열 검색은
*고쳐 놓은 문서*를 위반으로 잡았다(붙이자마자 그렇게 실패했다). 주변에 정정 표시
(`정정`/`stale`/`이전 버전`…)가 있으면 **살아 있는 주장이 아니라 인용으로** 보도록 고쳤다.
Sprint 101의 §9 스캐너가 자기 설명 주석을 잡은 것과 같은 부류다 —
**형태 검사는 대상 범위가 정확해야 "고쳐야 할 것"과 "적어 둔 것"을 구분한다.**

---

## #102-5 "safe to re-run"이 실제 부트스트랩에서 검증된 적이 없었다

CLAUDE.md는 부트스트랩이 "safe to re-run"이라고 안내한다. 그 주장을 검증하는 것은
`test_schema_hygiene.py` §7뿐인데, 거기서 쓰는 것은 **합성 마이그레이션**
(`CREATE TABLE IF NOT EXISTS qa_a ...`)이다. 즉 러너의 skip 분기는 검증됐지만
**실제 19개 파일로 두 번 돌렸을 때 안전한가는 확인된 적이 없었다.**

공허한 걱정이 아니다. 마이그레이션 019는 이렇게 생겼다.

```sql
ALTER TABLE subscriptions ADD COLUMN payment_id INTEGER REFERENCES payments(id);
```

`ALTER TABLE ADD COLUMN`은 **그 자체로는 멱등이 아니다** — 두 번 실행하면
`duplicate column name`으로 죽는다. 안전한 이유는 오직 `migration_history` 기반
skip 하나뿐이다.

### 가드 (`test_bootstrap.py` §6)

3단계 부트스트랩을 **두 번** 돌리고 테이블/인덱스/**테이블별 컬럼 목록**까지 비교한다
(이름만 같고 컬럼이 느는 종류의 비멱등성이 정확히 019 같은 경우다).

```
[PASS] 두 번째 실행이 예외 없이 끝난다
[PASS] 재실행이 마이그레이션을 중복 기록하지 않는다: 19
[PASS] 테이블 / 인덱스 / 컬럼 구성 — 사라진 것도 새로 생긴 것도 없음
   테이블 25개 / 인덱스 62개 / 마이그레이션 19개 — 2회 실행 후 동일
```

**변이 M20으로 러너의 skip 분기를 죽이자 즉시 잡혔다**:
`IntegrityError: UNIQUE constraint failed: migration_history.filename`.
그 skip이 **유일한 방어선**임이 실증됐다.

---

## #102-6 ★★ 수집이 멈춰 있다 — **2026-08-20부터 검색 결과 0건** (운영 조치 필요)

**심각도 최상** (제품이 빈 화면이 된다). 코드 결함이 아니라 **환경/운영** 문제라
이 세션에서 조치하지 않았다. 대신 **정확한 사실과 날짜**를 남긴다.

### 실측

```
마지막 crawl_date              2026-08-12   (오늘 2026-08-14 — 2일 전)
기본 검색(D7)에 뜨는 물건        9건  — 전부 매각기일 2026-08-19, 전부 서울중앙지방법원
★ 검색 결과가 0이 되는 날        2026-08-20   (6일 뒤)

logs/daily_run.log 마지막 기록  2026-08-11 17:05  (3일 전)
logs/doc_run.log   마지막 기록  2026-08-11 17:05
```

### 원인 — 스케줄러에 아무것도 등록돼 있지 않다

`docs/CLAUDE.md`는 Task Scheduler 작업 `LawAuctionDailyCrawl` / `PDF우선순위갱신`이
매일 돈다고 설명한다. **이 PC에는 그 작업이 존재하지 않는다.**

```
Get-ScheduledTask  ->  전체 248개 중 이 저장소 경로를 참조하는 작업 0개
LawAuctionDailyCrawl : 없음
PDF우선순위갱신      : 없음
```

`logs/daily_run.log`가 08-11에 멈춘 것과 일치한다 — **배치가 08-11 이후 한 번도 돌지
않았다.** 08-12에 데이터가 들어온 것은 배치가 아니라 **수동 실행**이었다
(배치가 돌았다면 `daily_run.log`에 기록이 남는다).

그 수동 실행도 **부분 수집**이었다. 평소 하루 100~278건이 들어오는데 08-12에는 9건,
그것도 60개 법원 중 서울중앙지방법원 하나뿐이다.

```
crawl_date별 신규 수집:  08-12 → 9건 / 08-01 → 278건 / 07-28 → 142건 / 07-27 → 108건
```

### 이것은 **재발**이다

`run_daily.bat`의 주석이 같은 사고를 이미 기록해 두었다.

> Anaconda가 제거되면서 모든 배치가 즉시 실패했고, 실패가 로그에도 남지 않아
> 2026-08-03 ~ 08-11 동안 크롤이 멈춘 사실을 아무도 몰랐다. 그 사이 진행 중 물건이
> 41건까지 줄었다(전부 2026-08-12 만료 → 그 다음날부터 검색 결과 0건).

그때는 **인터프리터**가 원인이었고 배치를 고쳐 해결했다. 이번에는 **스케줄러 등록 자체가
없다.** 원인은 다르지만 사용자가 겪는 결과는 완전히 같다.

### 배치 자체는 정상이다 (확인함)

부르기만 하면 도는 상태다. 실행하지는 않고 해석 로직만 재현해 확인했다.

```
Anaconda 경로 존재?         False        → PATH 폴백으로 간다(설계대로)
배치가 고를 인터프리터       C:\Users\jhj12\AppData\Local\Programs\Python\Python312\python.exe
그 인터프리터의 의존성       selenium / pandas / pdfplumber / webdriver_manager / fastapi 전부 OK
```

즉 **고쳐야 할 코드가 없다. 스케줄러 등록만 남았다.**

### 왜 내가 등록하지 않았나

스케줄 작업 등록은 **사용자 PC의 시스템 상태를 바꾸는 조치**이고, 등록하면 매일 새벽
실제 정부 사이트(courtauction.go.kr)에 Selenium이 접속한다. 이 저장소가 실제 크롤을
`ALLOW_LIVE_CRAWL=1`로 따로 막아 둔 것과 같은 이유로, **사용자 결정 없이 할 일이 아니다.**
게다가 이 PC가 운영 머신이 맞는지도 코드로는 알 수 없다.

### 사용자가 할 일 (택 1)

```
A. 즉시 1회 수집으로 급한 불 끄기
     cd <저장소>
     run_daily.bat            (mvp_scraper → migrate_execute 까지 한 번에)

B. 매일 자동화 복구 — Task Scheduler에 등록 (관리자 권한 필요)
     06:00  run_daily.bat            작업명 예: LawAuctionDailyCrawl
     01:50  run_priority_refresh.bat
     02:00  run_doc_worker.bat
   ※ Execute 필드는 OS 제약상 절대경로여야 한다(배치 내부는 이미 %~dp0 기준이라 무관).
```

### 앞으로 조용히 재발하지 않게 (이번에 넣은 것)

`test_pipeline_integrity.py` §11 신설. **결과 쪽에서** 본다 — 배치가 안 돌면 로그도
안 생기므로 로그로는 알 수 없다(없는 것은 눈에 띄지 않는다).

```
--- 11. 데이터 신선도 (검색 결과가 0이 되기까지) ---
    마지막 crawl_date : 2026-08-12
    기본 검색에 뜨는 물건: 9건
    ★ 수집이 멈춘 채로 두면 2026-08-20 부터 검색 결과 0건 (6일 남음)
    !! 경고: 수집이 멈춰 있다. 6일 뒤 검색 결과가 0건이 된다.
    !! 확인 순서: 스케줄러 등록 여부 -> logs/daily_run.log -> run_daily.bat
```

**실패로 만드는 조건은 "검색 0건" 하나뿐이다.** "오늘 크롤이 안 돌았다"로 실패시키면
주말·개발 중에도 스위트가 빨개지고, 그건 코드를 고쳐 풀 수 있는 실패가 아니라
금방 무시하게 된다. 남은 기간은 크게 출력하되 실패시키지 않는다.
변이 검증(M22): 남은 9건을 과거로 옮겨 "검색 0건"을 만들면 즉시 FAIL로 잡힌다.

---

## Dependency Audit — 문제 0건 (측정값만 남긴다)

| 항목 | 결과 |
|---|---|
| 선언 11개가 설치돼 있고 **버전까지 일치** | **11/11** |
| 선언한 것이 실제로 import 된다 | **11/11** |
| 소스가 쓰는데 선언 안 된 서드파티 | **0** |
| 선언했지만 아무도 안 쓰는 것 | 1건 (`httpx` — 아래) |

`httpx`는 **어떤 소스도 직접 import하지 않아** 안 쓰는 의존성으로 보이고, 실제로 이번
감사에서 그렇게 잡혔다. **지우면 안 된다** — `fastapi.testclient.TestClient`가 감싸는
`starlette.testclient`가 내부에서 쓴다(`inspect.getsource`로 `import httpx` 확인).
없으면 TestClient 기반 회귀(`test_api_regression` / `test_auth_jwt` /
`test_beta_journey` …)가 통째로 실행되지 않는다.

**★ 발견한 예고된 드리프트**: 현재 starlette이 이렇게 경고한다.

```
StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is
deprecated; install `httpx2` instead.
```

지금은 버전을 고정해 두어 동작에 문제가 없다. **starlette을 올릴 때 httpx -> httpx2
전환이 함께 필요하다.** 사유와 함께 `requirements.txt` 주석에 남겼다 —
다음에 누가 "안 쓰는 의존성"이라고 지우지 못하도록.

---

## 변이 검증 (이번 Sprint 신설분)

| | 변이 | 검출 |
|---|---|---|
| M11 | 테스트 픽스처를 UTC로 되돌림 (status_sync) | O |
| M12 | 테스트 픽스처를 UTC로 되돌림 (collect_documents) | O |
| M13 | `normalizer/`에 새 UTC 비교 주입 | O |
| M14 | `validator/`에 새 UTC 비교 주입 | O |
| M15 | `filter/`에 새 UTC 비교 주입 | O |
| M16 | 문서가 옛 범위(001~018)로 회귀 | O |
| M17 | 마이그레이션 020 추가, 문서는 그대로 | O |
| M18 | 문서가 정정 표시 없이 "requirements.txt 없다" 단정 | O |
| M19 | 마이그레이션 번호 중간 누락(017 제거) | O |
| M20 | **러너의 skip 분기 무력화** | O — `UNIQUE constraint failed: migration_history.filename` |
| M21 | 멱등이 아닌 020 추가 | O |

M13은 처음에 문법적으로 깨진 코드를 주입해 "검출 X"로 나왔다. **주입 자체가 유효한지
먼저 확인**하도록 도구를 고친 뒤 재측정해 정상 검출을 확인했다 — 변이 검증은
"테스트가 실패했다"가 아니라 **"의도한 이유로 실패했다"**를 봐야 한다.

모든 변이 후 원본은 **바이트 단위로 복구**했다(`rb`/`wb`). Sprint 101에서 BOM을 날린
사고의 재발 방지책을 이번 내내 적용했고, 복구 후 `git status`가 비는 것으로 매번 확인했다.

---

## 저장소의 가드가 **또** 내 작업을 잡았다 (기록)

Sprint 101에서는 `test_schema_hygiene.py`가 내 변이 도구의 BOM 삭제를 잡았다.
이번에는 `test_console_encoding.py`가 잡았다.

```
[FAIL] cp949로 못 내보내는 출력 리터럴 없음: ['test_bootstrap.py:366 U+2014']
```

내가 새로 쓴 **출력 문자열**에 em dash(U+2014 `—`)를 썼는데, 이 저장소는 Windows
cp949 콘솔에서 깨지지 않도록 U+2015(`―`)를 쓰기로 정해 두었고 그것을 검사로 강제한다.
주석은 무방하고 **print되는 리터럴만** 대상이다 — 검사가 그 구분을 정확히 하고 있었다.

두 번 다 **내 코드가 아니라 내 작업 습관**이 문제였고, 두 번 다 저장소가 먼저 잡았다.
이것이 이 저장소의 검사들이 실제로 값을 하고 있다는 가장 좋은 증거다.

---

## 검증

| 항목 | 결과 |
|---|---|
| 파이썬 테스트 | **31/31 파일 통과** |
| 프런트 테스트 | **107/107** (fail 0 / cancelled 0 / skipped 0) |
| TypeCheck / Lint / Build | **전부 exit 0** (파이프 없이 측정) |
| 신설 검사 | `test_bootstrap.py` §5·§6, `test_pipeline_integrity.py` §9 범위 확장 |
| 실 DB | **읽기 전용 + 복사본**으로만 검증. 원본 무변경 |

---

## ★ 다른 세션의 미커밋 작업이 남아 있다 (건드리지 않았다)

작업 중 git worktree가 하나 살아 있는 것을 발견했다. **손대지 않았다** —
동시 세션 보호 원칙 그대로다. 사용자가 알아야 할 사실만 남긴다.

```
경로        .claude/worktrees/sprint95-false-success-audit
브랜치      worktree-sprint95-false-success-audit
기준 커밋   c4f74e6   ← master(fc22381)보다 2커밋 뒤처져 있다
미커밋 변경 48개 파일
마지막 수정 2026-08-13 17:37
디스크      1,359.5 MB
```

### 내 작업과 겹치는 파일 5개

지금은 **디렉터리가 달라 충돌하지 않는다**(그쪽은 자기 체크아웃, 나는 메인 작업 트리).
다만 언젠가 합칠 때 이 5개는 반드시 손으로 병합해야 한다.

```
docs/CLAUDE.md
storage/database.py
test_document_queue.py
test_document_status_sync.py
test_pipeline_integrity.py
```

`storage/database.py`가 특히 주의 대상이다 — 그쪽 기준 커밋이 2커밋 뒤라
**Sprint 100의 변경조차 들어 있지 않다.** 그대로 덮어쓰면 Sprint 100~102가 함께 사라진다.

## SKIP 및 이유

| 항목 | 이유 |
|---|---|
| `config/settings.py:COURTS` 죽은 코드 삭제 | 구조 변경(승인 영역). #101-4 가드로 대체 |
| `document-stats`의 `total_failures` 정의 | 제품 결정 (#101-3) |
| starlette 업그레이드 + httpx2 전환 | 의존성 major 변경 — 계획된 작업으로 남긴다 |
| 고아 파일/큐 정리 | 운영 데이터 삭제 |

## 남은 Backlog

- **★★ 최우선: 수집 파이프라인 스케줄러 등록** (#102-6 — 2026-08-20에 검색 0건)
- 다른 세션의 worktree 48개 파일 병합 결정 (겹치는 5개는 손 병합 필요)
- **starlette 업그레이드 시 httpx -> httpx2 전환** (신규, 예고된 드리프트)
- `document-stats`의 `total_failures` 정의 결정 (#101-3)
- 현황조사서 item_no != 1 버튼 id 확보 + `SKIPPED_UNSUPPORTED` 복귀 스크립트
- 고아 파일 3개 / 고아 큐 18행 정리
- 커밋된 DB 백업 9개(36.9MB) 인덱스에서 제거
- `mypage` 등기부 다운로드 버튼 (UX 결정)
- 스키마 생성 경로 일원화(`init_db` + `migrate_v4_1`)
- 구독 결제 환불 시 구독 처리(A/B/C/D) — `payment_id` 열쇠는 Migration 019로 이미 있다
