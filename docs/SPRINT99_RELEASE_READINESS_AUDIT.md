# Sprint 99 — fresh clone / Release Readiness 감사

> 앞 Sprint: `docs/SPRINT98_FALSE_SUCCESS_AUDIT.md` (false success 패턴)
>
> **왜 별도 파일인가**: `docs/BUGS.md`, `api/v1/admin.py`, `test_api_regression.py`,
> `api/v1/payments.py` 등이 다른 세션에서 편집되고 있어(수정 시각 확인) 충돌을 피했다.
> 내용이 안정되면 `docs/BUGS.md`로 합치면 된다.

Sprint 98에서 `logs/` 없는 새 체크아웃 문제를 고치면서 떠오른 질문 하나를 끝까지 따라갔다:

> **"새로 clone하면 이 저장소가 실제로 돌아가는가?"**

답은 **아니오**였다. 그리고 그 사실을 알려주는 검사도 없었다.

---

## #99-1 ★ fresh clone에서 DB를 만들 수 없다 (Release Blocking, 수정 완료)

**파일** `storage/migrations/run_migrations.py`, `test_bootstrap.py`(신설)
**심각도** **높음 — Release Blocking**

### 증상 (실측 재현)

`auction.db`는 `.gitignore` 대상이라 clone에 없다. 그래서 새 개발자·새 배포·장애 복구는
전부 스키마를 처음부터 만들어야 한다. 그런데 안내되는 순서대로 돌리면 **중간에 죽는다**:

```
1) init_db()                    -> 테이블 3개만 생성 (auction, document_queue, document_version_log)
2) run_migrations.py            -> [FAIL] 008_create_search_indexes.sql:
                                          no such table: main.auction_item
```

`init_db()`는 `auction_item`을 만들지 않는데, 008번 마이그레이션부터는 그 테이블이 있다고
가정한다. 결과적으로 다음 6개 테이블이 **저장소 어디로도 만들어지지 않는 것처럼 보였다**:

`auction_item` · `auction_case` · `document_status` · `tenant_rights` · `rights_summary` · `audit_logs`

`auction_item`은 검색·상세·즐겨찾기·등기부가 전부 JOIN하는 **핵심 테이블**이다.

### 더 나쁜 것 — partial success

실패가 깨끗하지 않았다. **001~007은 이미 적용된 뒤**라 `migration_history`에 7건이 남고,
테이블 8개가 생긴 채로 죽는다. 즉 **절반만 마이그레이션된 DB**가 남는다.
오류 메시지는 `no such table: main.auction_item` 한 줄뿐이라 무엇을 먼저 돌려야 하는지
알 수 없다. 이 저장소가 계속 잡아 온 partial success 패턴이 부트스트랩에도 있었다.

### 원인

빠진 단계는 **`storage/migrate_v4_1.py`**였다. 이 스크립트가 위 5개 테이블을 만든다.
올바른 순서는 3단계인데, 그 사실이 **러너에도 문서에도 적혀 있지 않았다.**

```
1) python -c "from storage.database import init_db; init_db()"
2) python storage/migrate_v4_1.py          <- 빠져 있던 단계
3) python storage/migrations/run_migrations.py
```

이 순서로 돌리면 **마이그레이션 19/19 적용, 테이블 26개, 인덱스 62개**가 만들어지고
운영 DB(26개)와 **정확히 일치**한다 — 실측 확인.

### 수정

**러너가 아무것도 적용하기 전에 선행 스키마를 확인하고, 순서를 알려주며 중단한다.**

필요 여부는 **실제 .sql 내용에서 도출한다** — 목록을 하드코딩하면 두 가지가 어긋난다:
① 앞으로 선행 테이블을 요구하는 마이그레이션이 늘어도 목록이 안 따라온다,
② 테스트가 자기만의 마이그레이션 디렉터리로 러너를 부를 때 무관한 SQL까지 막힌다
(실제로 `test_schema_hygiene.py`의 러너 검사가 그렇게 깨졌고, 그래서 이 방식으로 바꿨다).
`auction_item_new`처럼 **새로 만드는** 테이블에 오탐하지 않도록 경계도 본다.

### 신규 테스트 `test_bootstrap.py`

세 가지를 고정한다 (작업본 DB는 건드리지 않고 임시 파일에만 적용):

1. 선행 스키마 없이 러너를 돌리면 **아무것도 적용하지 않고** 중단하고, 메시지가
   `migrate_v4_1`을 지목한다
2. 3단계로 돌리면 마이그레이션이 **전부**(19/19) 적용되고 핵심 테이블 21개가 다 생긴다
   (인덱스 생성까지 확인 — 테이블만 있고 인덱스가 없으면 기능은 되지만 검색이 조용히 느려진다)
3. 부트스트랩 스키마 == **운영 스키마** (운영에만 있는 테이블이 0개여야 한다)

**변이 검증**: 선행 확인 블록을 지우면 3개 단언이 실패하며 **원래 버그가 그대로 재현**된다 —
적용된 마이그레이션 7개, 테이블 8개 증가, 메시지 `no such table: main.auction_item`.

---

## #99-2 fresh clone에서 `test_schema_hygiene.py`가 깨진다 (수정 완료)

**파일** `test_schema_hygiene.py`, `requirements.txt`

### 증상

`requirements.txt`의 `requests`를 쓰는 저장소 소스가 **하나도 없다.** 그런데 로컬에서는
검사가 통과한다 — `.gitignore`가 무시하는 `step8_verify.py`가 그걸 import하기 때문이다.

`test_schema_hygiene.py`의 import 스캔이 `os.walk`로 **파일시스템을 그냥 훑고 있어서**,
clone에는 존재하지 않는 로컬 실험 스크립트까지 "소스"로 세고 있었다.
**즉 이 검사 자체가 false success였다** — 다른 환경에는 없는 집합을 기준으로 통과했다.

### 실측

`.gitignore`의 `step*.py`에 걸리는 파일이 **65개**. 그 65개를 치우고 돌리면:

```
[FAIL] 목록에만 있고 소스에서 안 쓰는 항목 없음: ['requests'] (expected [])
```

로컬에서만 통과하고 **CI/새 환경에서는 깨지는**, 가장 알아채기 어려운 형태다.

### 수정

1. import 스캔 기준을 **git**으로 바꿨다 — `git ls-files --cached --others --exclude-standard`
   (추적 중 + 아직 추적 안 되지만 무시 대상도 아닌 새 파일). 무시 대상만 정확히 빠진다.
   git이 없으면 예전 방식으로 되돌리고 **경고를 출력한다**(검사를 아예 잃는 것보다 낫다).
2. `requirements.txt`에서 `requests`를 뺐다. `webdriver-manager`가 의존하므로
   **전이 의존성으로 그대로 설치된다**(실측 확인) — 설치 결과는 달라지지 않는다.

이 목록 자체가 같은 원인으로 오염돼 있었다는 점도 기록해 둔다 — `requirements.txt` 머리말이
"소스 153개 .py의 import를 전수 파싱해서 뽑았다"고 적고 있는데, 그 파싱이 바로 이 스캔이었다.

**변이 검증**: 추적 중인 파일(`api/v1/doc_stats.py`)에 `import requests`를 넣으면
`['requests (api\v1\doc_stats.py)']`로 잡힌다 → git 기준 스캔이 추적 파일을 정상적으로 본다.
반대 방향(미사용 항목)은 위 `requests` 발견 자체가 증거다. fresh clone 시뮬레이션도 통과로 전환.

---

## #99-3 `.gitignore` 의도와 git index가 갈라져 있다 (계측 + 증가 차단, 제거는 SKIP)

**파일** `.gitignore`, `test_schema_hygiene.py`

git의 ignore 규칙은 **추적 시작 이후에는 적용되지 않는다.** 그래서 규칙을 나중에 추가하면
"무시하기로 했는데 계속 따라다니는" 파일이 남고, `.gitignore`만 읽으면 정리된 것처럼 보인다.

### 실측 — 추적 파일 238개 중 10개가 무시 대상 (36.9 MB)

| 파일 | 크기 | 걸리는 규칙 |
|---|---|---|
| `auction.db.backup_*` 9개 | **36.9 MB** | `.gitignore:73:*.db.backup*` |
| `CEO/00 CEO.txt` | 0.0 MB | `.gitignore:120:*.txt` |

### 개인정보 여부 — **없음 (전수 확인)**

9개 백업을 **전부** 열어 확인했다. 사용자 테이블이 비어 있지 않은 것은 2개뿐이고
(`recent_items` 각 10행), 그 `user_id`는 **전부 `qa-*` 테스트 계정**이었다 —
실제 Supabase UUID 형태 **0건**. 즉 **보안 문제가 아니라 저장소 위생 문제**다.
다만 clone마다 37MB를 따라다니게 하고, 왜 있는지 아무 데도 적혀 있지 않다.

### 왜 제거하지 않았나 (SKIP)

인덱스에서 빼려면 `git rm --cached` + **commit**이 필요한데 이 세션은 commit 금지다.
그래서 **늘어나는 것만 막았다** — 이 저장소가 `test_pipeline_integrity.py`에서 쓰는
"상한을 두고 증가만 차단" 방식과 같다. 알려진 10개는 상수로 고정하고, 새로 생기면 즉시 실패한다.
나중에 정리해서 줄어들면 그대로 통과하고, 줄어든 항목은 "상수에서 빼라"고 안내한다.

**변이 검증**: 상수에서 항목 하나를 빼면 그 파일이 "새로 생긴 항목"으로 잡힌다.

### 함께 고친 것 — `.claude/`가 무시되지 않고 있었다

`.claude/worktrees/` 안에는 저장소 **전체 사본**이 들어간다(실측 **1.4GB**, `auction.db` 사본 포함).
`.gitignore`에 항목이 없어 `git status`에는 `?? .claude/` 한 줄로만 보이다가
**`git add .` 한 번에 통째로 스테이징된다.** `.gitignore`에 `.claude/`를 추가했다.

---

## #99-4 ★ 예약 배치가 아무것도 안 하고 "성공"으로 끝난다 (Release Blocking, 수정 완료)

**파일** `run_daily.bat`, `run_doc_worker.bat`, `run_priority_refresh.bat`, `test_bootstrap.py`
**심각도** **높음 - Release Blocking** (과거 9일 무중단 장애와 동일한 실패 모드)

### 증상 (실측 재현)

세 배치 모두 첫 동작이 `>> logs\...log` 리다이렉트다. `logs/`는 .gitignore 대상이라
**새 배포에는 없다.** 그 상태에서 cmd는:

```
"%PY%" mvp_scraper.py >> logs\daily_run.log 2>&1     <- 리다이렉트 실패, 스크립트 미실행
if errorlevel 1 ( ... exit /b 1 )                    <- errorlevel은 0! 분기 안 탐
echo [SUCCESS] Finished >> logs\daily_run.log        <- 이것도 실패(무시됨)
exit /b 0                                            <- 성공으로 종료
```

**cmd는 리다이렉트 실패에 errorlevel을 세우지 않는다.** 그래서 파이썬 스크립트는 실행조차
되지 않았는데 배치는 exit 0으로 끝난다. 실측 재현 결과:

```
REPORTED_SUCCESS
exit code: 0
로그 파일 없음 / 스크립트 실행 흔적 없음 ("SCRIPT ACTUALLY RAN" 미출력)
```

### 왜 심각한가

이 배치들의 주석이 스스로 적어 둔 사고가 **정확히 이 모양**이었다:

> Anaconda가 제거되면서 모든 배치가 즉시 실패했고, **실패가 로그에도 남지 않아**
> 2026-08-03 ~ 08-11 동안 크롤이 멈춘 사실을 아무도 몰랐다. 그 사이 진행 중 물건이
> 41건까지 줄었다(전부 2026-08-12 만료 -> 그 다음날부터 검색 결과 0건).

그 사고를 막으려고 넣은 것이 "(3) 둘 다 없으면 **로그에 남기고** 즉시 실패한다"인데,
그 로그 경로 자체가 없으면 그 방어가 통째로 무력화된다. **새 배포에서 그대로 재발한다.**
스케줄러에는 성공으로 기록되므로 아무도 눈치채지 못한다.

### 수정

세 파일 모두 `cd /d %~dp0` 직후, **어떤 리다이렉트보다 먼저**:

```bat
if not exist "logs" mkdir "logs"
```

**검증**: 수정 전후를 실제 cmd로 돌려 확인했다.
- 수정 전: `REPORTED_SUCCESS` / exit 0 / 스크립트 미실행
- 수정 후: 로그에 `SCRIPT ACTUALLY RAN` 기록 / exit 0 (진짜 성공)
- 실패 경로도 함께 확인: 스크립트가 exit 3이면 `REPORTED_FAILURE` / exit 1
  (성공이 무조건 나오게 만든 것이 아님을 확인)

### 신규 테스트

`test_bootstrap.py`에 소스 레벨 검사를 넣었다 - 모든 `run_*.bat`이 (1) logs로
리다이렉트하고 (2) logs를 만들며 (3) **mkdir이 첫 리다이렉트보다 먼저** 오는지 확인한다.
순서가 핵심이라 순서까지 본다. 주석(`REM`) 줄은 제외해 예시 문구에 걸리지 않게 했다.

**변이 검증**: `run_daily.bat`에서 mkdir 줄을 지우면 즉시 `[FAIL]`.

### 함께 확인한 것 - 인터프리터 선택 (수정하지 않음)

세 배치는 `C:\ProgramData\Anaconda3\python.exe`가 있으면 **그것을 우선**하는데,
크롤러 의존성(selenium/pandas/pdfplumber/webdriver-manager)은 Sprint 61에 **PATH의
Python312**에 설치됐다(실측: Anaconda 부재, PATH python이 4개 패키지 전부 보유).

즉 Anaconda가 다시 설치되면 의존성이 없는 인터프리터가 선택된다. 다만 그 경우는
**조용하지 않다** - ImportError로 파이썬이 exit 1을 내고, 이제 logs도 확보돼 있어
traceback이 로그에 남고 errorlevel 분기가 정상적으로 탄다. 그리고 우선순위 자체는
"기존 환경 무변경"이라는 의도적 선택이라(주석에 명시) 배포 정책에 해당한다. **손대지 않았다.**

---

## 확인했으나 결함이 **아닌** 것

| 대상 | 판단 |
|---|---|
| 마이그레이션 011~013의 `*_new` 테이블 | **정상.** SQLite에서 UNIQUE 제약을 바꾸는 표준 패턴(새 테이블→이관→DROP→RENAME). 러너가 FK를 끄고 도는 이유도 여기에 있고 주석에 이미 설명돼 있다. |
| `storage/migrations/*`가 `.gitignore`에 있는 것 | **정상.** 바로 아래 `!storage/migrations/*.sql` / `*.py` 부정 규칙이 다시 포함시킨다. `check-ignore`로 확인했고, 실제로 19개 .sql이 전부 추적 중이다. |
| 커밋된 DB 백업의 개인정보 | **없음.** 9개 전수 확인, `qa-*` 테스트 계정만 존재. |

---

## 검증

| 항목 | 결과 |
|---|---|
| 파이썬 테스트 | **31개 파일 전부 통과** (`test_bootstrap.py` 신설 포함) |
| 프런트 테스트 (서버 불필요분) | 59/59 통과 |
| TypeCheck (`npx tsc --noEmit`) | exit 0 |
| Lint (`npm run lint`) | exit 0 |
| Build (`npm run build`) | exit 0 |

### 이번에 스스로 만든 회귀 2건 (즉시 수정)

정직하게 남긴다 — 둘 다 기존 검사가 잡아 줬다:

1. 선행 스키마 확인을 **무조건** 걸어서 `test_schema_hygiene.py`의 러너 검사(자체 마이그레이션
   디렉터리 사용)를 깨뜨렸다 → 요구사항을 **.sql 내용에서 도출**하도록 바꿔 해결.
2. 새 주석에 EM DASH(U+2014)를 써서 `test_console_encoding.py`가 실패했다(Windows cp949).
   → 하이픈으로 교체. 이 저장소가 이 규칙을 검사로 강제하고 있다는 게 그대로 증명됐다.

---

## 남은 Backlog / SKIP

| 항목 | 상태 | 이유 |
|---|---|---|
| 배치의 Anaconda 우선순위 | **SKIP** | 배포 정책(의도적 "기존 환경 무변경"). 실패해도 이제는 조용하지 않다(#99-4 참고). |
| 커밋된 DB 백업 9개(36.9MB) 인덱스에서 제거 | **SKIP** | `git rm --cached` + commit 필요. 증가 차단만 적용. |
| 부트스트랩 3단계를 `README`/`docs`에 반영 | **미완** | 러너가 이제 직접 안내하지만, 문서에도 적는 편이 좋다. 다른 세션이 docs를 편집 중이라 보류. |
| `mypage` 등기부 다운로드 버튼 (#98-1 후속) | **SKIP** | UX/제품 결정 필요. |
| `init_db()`와 `migrate_v4_1.py`를 하나의 부트스트랩 진입점으로 통합 | **제안** | 지금은 세 단계를 사람이 순서대로 불러야 한다. 합치면 순서 실수가 원천적으로 불가능해진다. 다만 기존 운영 절차를 바꾸는 일이라 승인 대상으로 본다. |
