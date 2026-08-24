# Sprint 251 — 문서가 적어 둔 상태와 **이 저장소의 실제 상태**가 갈라져 있었다

**날짜** 2026-08-24. HEAD `ebb5816` / branch `master` / **커밋·푸시 없음**.
운영 `auction.db` 무변경(행수·`PRAGMA integrity_check` 전후 대조) / `.env` **무변경** /
스케줄러 등록 없음 / 실크롤 없음 / 의존성 설치 없음.

---

## 0. 기준선 — 이번 세션 실측 (이전 Sprint 숫자를 믿지 않고 다시 쟀다)

```
세션 시작   python  통과 48 | 실패 1 | 건너뜀 3 | 판정없음 1   (단언 7,719건, 148.2s / 53파일)
세션 종료   python  통과 49 | 실패 1 | 건너뜀 3 | 판정없음 1   (단언 7,759건, 119.6s / 54파일)
            node    175개 / 171 PASS / 1 FAIL / 3 SKIP   (5.9s, dev+api 기동 상태에서 측정)
            tsc 0 / eslint 0 / next build 성공(10 페이지)

※ 단언 수가 실행마다 몇 건 흔들리는 것은 정상이다 — 일부 검사가 **실 데이터 건수만큼**
  단언한다(예: 자산 URL 확인). 판정(통과/실패 파일)은 모든 실행에서 동일했다.

운영 DB (작업 전후 동일, integrity_check ok)
  auction 1,876 / auction_item 1,876 / auction_case 1,384
  document_queue 3,498 (pending 2,753 / done 559 / SKIPPED_EXPIRED 186 / refresh 0)
  doc_raw 556 / document_status 5,628 / auction_image 45
  favorites 0 / recent_items 36 / payments 0 / subscriptions 0
  foreign_key_check 위반 0 / 논리적 고아(6개 테이블) 0
```

실패 1건(python·node 각 1)은 **같은 원인**이다 — 기일 남은 물건 0건. 아래 §1 의
Release Blocker 그 자체이고 승인 영역이라 그대로 둔다.

---

## 1. ★★ 이번 세션의 핵심 발견 — 문서가 **다른 환경의 측정값**을 이 저장소의 상태로 적고 있다

직전 커밋 `ebb5816`("chore: update beta release audit and fixes", 2026-08-24 06:52)이
Sprint 251~267 의 결과를 문서에 담았다. 그 안의 **환경 의존 측정값이 이 저장소에서
하나도 재현되지 않는다.** 어느 쪽이 옳은지 단정하지 않고, 잰 것만 적는다.

| 항목 | 문서 기록 (Sprint 267, 2026-08-23) | 2026-08-24 실측 |
|---|---|---|
| `auction_item` | 2,360 | **1,876** |
| 기일 미도래 물건 | 275건 | **0건** (최종 기일 2026-08-19) |
| `GET /api/v1/search` | total 275 | **total 0** (HTTP 200) |
| `…?include_closed=true` | total 2,360 | **total 1,876** |
| `…?sido=서울` | total 49 | **total 0** |
| `DOJOONPASS_DAILY` | Ready / 08-22·08-23 03:00 / 결과 0 | **존재하지 않음** |
| 저장소를 가리키는 예약 작업 | 1개 | **0개** (전체 249개 전수 스캔) |
| `logs/daily_run.log` | `[SUCCESS] Finished 2026-08-23 04:35:15` | mtime **2026-08-11 17:05** / 마지막 완료줄 `Finished at 2026-08-02` |
| `document_queue` | pending 4,883 / done 549 / SKIPPED 178 / refresh 9 | **pending 2,753 / done 559 / SKIPPED 186 / refresh 0** |
| item 173 (`2024타경2981`) 기일 | 2026-09-02 | **2026-08-05** |
| `auction_image` 테이블 | "테이블 자체가 없다"(P0-C) | **있다, 45행** (migration 020 applied 2026-08-17) |
| `ADMIN_API_KEY` / `SUPER_ADMIN_API_KEY` | 둘 다 있다(75/74자) | **둘 다 미설정** → admin 5종 전부 500 `관리자 키 미설정` |

### 측정 방법 (전부 읽기 전용)

- DB 경로를 추측하지 않고 **제품 코드가 쓰는 값**을 그대로 물었다 —
  `storage.database.DB_PATH` → `…\dojoonpass\auction.db` (5,246,976 bytes).
  저장소 안의 다른 `.db` 는 0바이트 `auction_data.db` 뿐이다.
- **이 세션이 열기 전 그 파일의 mtime 은 2026-08-21 19:19** 이었다. 08-22/08-23 의
  크롤 결과를 담고 있을 수 없다. (`auction.db` 는 `.gitignore:64` `*.db` 라 git 이력으로
  확인할 수 없다.)
- 예약 작업은 **세 가지 독립 경로**로 확인 — `Get-ScheduledTask` 전수(249개)의
  Action 문자열 매칭 / 이름 정규식 `(?i)dojoon` / 별도 도구 `audit_schedule_health.py`
  (schtasks 기반). 셋 다 0개.
- API 는 로컬에서 실제로 띄워 HTTP 로 호출했다(`api_server.py`, 127.0.0.1:8000).

### 반대로, **git 안에 있는 사실은 그대로 옳았다**

같은 커밋의 코드/마이그레이션 관련 서술은 재실측에서 전부 맞았다:
`migration_history` 에 `019_add_subscription_payment_id.sql`(2026-08-13 적용),
`subscriptions.payment_id INTEGER REFERENCES payments(id)` 실재,
`api/v1/payments.py:440` 이 같은 트랜잭션 안에서 그 값을 실제로 채운다(BUGS #94 해소 확인).
README 의 `src/middleware.ts` → `src/proxy.ts` 정정도 맞다.

**패턴이 일관된다** — git 이 옮기는 것(코드·마이그레이션 파일)은 따라왔고,
git 이 옮기지 않는 것(`auction.db`, `.env`, 작업 스케줄러)은 따라오지 않았다.

### 무엇을 고쳤나 — 산문이 아니라 **기계가 읽는 판정**을 심었다

문구를 고쳐도 다음에 또 갈라진다. 그래서 문서에 토큰 한 줄을 두고 실측과 대조한다.

```
docs/BETA_RELEASE_CHECKLIST.md   <!-- P0A-VERDICT: OPEN -->
test_pipeline_integrity.py       test_checklist_p0a_verdict_matches_reality()
```

**양방향**으로 잠근다 — 깨졌는데 `RESOLVED` 여도, 정상인데 `OPEN` 이어도 실패한다.
그래서 크롤이 되살아나 실제로 해소되는 날에도 문서를 반드시 갱신하게 된다.

```
mutation 1  토큰을 RESOLVED 로 바꿈 (실측 0건)      -> FAIL   검출 O
mutation 2  스크래치 DB 사본에 미래 기일 1건 주입    -> FAIL   검출 O
            (운영 DB 무변경, 임시 파일 사용 후 삭제)
```

---

## 2. ★ 조치 **순서**를 바로잡았다 — DocWorker 부터 등록하면 아무 일도 안 일어난다

Sprint 267 은 "활성 물건의 89%가 문서/사진이 비어 있다 → DocWorker 등록이 P0"이라고
적었다. 이 저장소 상태에서는 그 처방이 **아무것도 바꾸지 못한다.**

```
document_queue pending          2,753행
  그중 기일이 이미 지난 행      2,753행  (100%)
  그중 기일이 남은 행               0행
  auction_date 가 비어 있는 행      0행
큐의 auction_date 최댓값        2026-08-19   (오늘 2026-08-24)
```

`doc_worker.py` 의 2차 방어선(`auction_date < today`)이 **브라우저를 열기 전에**
`mark_queue_skipped_expired()` 로 종결한다. 지금 DocWorker 를 돌리면 2,753행을 전부
`SKIPPED_EXPIRED` 로 닫고 문서는 한 건도 수집하지 않는다.

**뿌리는 하나다 — 크롤이 멈춰 있다.** 새 물건이 들어와야 DocWorker 가 할 일이 생긴다.

---

## 3. `register_scheduler_tasks.ps1` — 결함 2건 수정 + 거짓 실측 주장 1건 정정

이 스크립트의 "다른 이름의 기존 작업 탐지" 블록은 **중복 등록 사고를 막으려고** 있다.
그 블록이 두 가지로 눈이 멀어 있었다.

### 3-A. `Execute` 에 .bat 을 직접 넣은 작업을 통째로 놓친다 (수정)

```
필터가 Arguments 만 볼 때
  cmd.exe /c "…\run_daily.bat"          -> 탐지 O
  Execute="…\run_daily.bat", Arguments 빔 -> 탐지 X   ★ 놓침
Execute+Arguments+WorkingDirectory 를 볼 때
  둘 다 탐지 O
```

뒤쪽은 `schtasks /create /TR "C:\…\run_daily.bat"` 가 만드는 아주 흔한 모양이다.
놓치면 **경고가 아예 뜨지 않은 채** `-Apply` 가 중복 작업을 등록한다 — 이 블록이
존재하는 이유 자체가 무력화된다.

### 3-B. 루트(`\`) 밖 폴더의 작업은 실행 이력을 못 읽는다 (수정)

```
Get-ScheduledTaskInfo -TaskName '…GoogleUpdaterTaskSystem…'            -> 실패
  "The system cannot find the file specified."
Get-ScheduledTaskInfo -TaskName '…' -TaskPath '\GoogleSystem\GoogleUpdater\' -> result=0
```

`-ErrorAction SilentlyContinue` 라 조용히 `$null` 이 되고, 출력이
`(마지막 실행 , 결과 )` 로 비어 사람이 판단할 근거가 사라진다.
`-TaskPath` 를 함께 넘기고, `$null` 이면 "확인 안 됨"으로 **명시적으로** 찍는다.

### 3-C. `.PARAMETER SkipCoveredByLegacy` 의 거짓 실측 주장 (정정)

원문: *"실측(2026-08-22)으로 `DOJOONPASS_DAILY` 가 `run_daily.bat` 을 매일 03:00에
정상 실행 중임을 확인했다."* → 위 §1 의 실측과 정면으로 어긋난다.
이 문장을 믿으면 "DailyCrawl 은 이미 커버되니 `-SkipCoveredByLegacy` 로 나머지만
등록하면 된다"고 판단하게 되는데, 그러면 **크롤은 계속 안 돈다.**

### 회귀 방어 — 문구가 아니라 **식 자체를 떼어 내 실행한다**

`test_schema_hygiene.py::test_scheduler_script_detects_legacy_tasks()` 가
`.ps1` 에서 `$LegacyBatPattern` ~ `$legacyCandidates` 식을 그대로 잘라 내
목 데이터에 대해 PowerShell 로 돌린다.

```
목 데이터                                          기대 탐지
  LEGACY_CMDC   cmd.exe /c "…run_daily.bat"        O
  LEGACY_DIRECT Execute="…run_daily.bat"           O   <- 3-A 가 놓치던 것
  UNRELATED     notepad.exe                        X
  DojoonPass-DailyCrawl (자기가 등록할 이름)        X

mutation: 필터를 `$_.Arguments` 만 보게 되돌림
  -> 정적 검사 FAIL + 동작 검사 FAIL (['LEGACY_CMDC'] != 기대)   검출 O
```

---

## 4. `audit_asset_integrity.py` [7] — 감사기가 **비용을 부풀려** 보고하고 있었다

```
(수정 전)  고아 큐 행 18개 (그중 워커가 실제로 수집을 시도할 대기 행 12개)
           docstring: "pending 이면 워커가 실제로 브라우저를 몰아 수집한다(물건당 약 22초)"
(실측)     pending 12행은 **전부 기일 경과**(가장 늦은 것 2026-07-30) -> 실제 시도 0행
(수정 후)  대기(pending/refresh) 12개 = 기일 남음 0개 + 기일 경과 12개
           -> 지금 낭비되는 수집 비용은 0이다. 정리는 급하지 않다
```

**왜 중요한가**: 이 숫자는 사람이 "고아 정리를 지금 해야 하나"를 판단하는 근거다.
부풀려진 비용은 **승인 영역의 파괴적 삭제를 서두르게** 만든다. 게다가 같은 저장소의
`test_pipeline_integrity.py` 고아 상한 주석은 이미 "낭비 비용은 지금은 0"이라고
적고 있었다 — **두 도구가 서로 다른 말을 하고 있었다.**

분류를 순수 함수 `classify_queue_orphans()` 로 떼어 내고 selftest 에 넣었다
(운영 데이터에는 "기일 남은 고아 행"이 0개라 실데이터만으로는 검증이 공허하다).

```
mutation: live_n = waiting_n (기일 방어선 무시, 옛 동작)
  -> selftest 2건 FAIL (기일 남음 6 != 기대 3, 기일 경과 0 != 기대 3)   검출 O
```

---

## 5. 감사 도구의 `--selftest` 를 **아무것도 돌리고 있지 않았다** (신규 `test_audit_selftests.py`)

```
run_python_tests.py   test_*.py 만 찾는다 -> audit_*.py 는 대상 아님
.bat / .ps1           `--selftest` 참조 0건 (2026-08-24 실측)
package.json          프런트 전용
```

즉 감사기가 조용히 눈이 멀어도 아무도 모른다 — 감사기가 막으려던 상태 그 자체다.

`audit_asset_integrity.py` 는 selftest 를 자기 파일 안에 둔 이유를 이렇게 적어 두었다:
*"이 파일은 아직 미추적 파일이고 … 파일이 추적되면 그때 회귀 스위트로 옮기는 것이 맞다."*
**2026-08-24 실측: 세 파일 다 이미 추적된다**(`git ls-files`). 조건이 스스로 말한 대로
충족됐으므로, 검사 **내용**은 각 도구에 두고 **실행**만 회귀 스위트로 끌어왔다
(import 가 아니라 서브프로세스 + 종료코드 계약 — 모듈 수준 부작용을 떠안지 않는다).

```
mutation: audit_schedule_health.py 의 CSV 헤더 키를 __MUTANT__ 로 바꿈
  -> test_audit_selftests.py FAIL   검출 O
```

`--selftest` 가 **아닌** 실행은 하지 않는다 — 그쪽은 운영 DB 를 훑고,
`audit_auth_health.py` 는 외부 네트워크 요청까지 보낸다.

---

## 6. `audit_test_reality.py` — "실행 0줄"이 두 가지 전혀 다른 상태를 뜻하고 있었다

coverage 는 **자식 프로세스를 따라가지 못한다.** 제품 코드를 `subprocess.run` 으로
돌리는 검사는 실제로 다 실행하고도 "실행 0줄"로 나온다. 그것을 "소스 문자열/상수만
본다"와 같은 문장으로 찍으면 멀쩡한 검사를 지우게 된다.

```
(수정 후)
  [실행   0줄] test_audit_selftests.py   <- 자식 프로세스로 실행한다(coverage 가 못 본다):
                                            audit_asset_integrity.py, audit_schedule_health.py, audit_auth_health.py
  [실행  33줄] test_runner_contract.py   <- 자식 프로세스로 실행한다(coverage 가 못 본다): run_python_tests.py
```

같은 파일에서 **처음 커밋(`64e9116`)부터 이름이 비어 있던 주석**도 복원했다
("처음엔 빠져 있어서  가 실행 0줄로 나왔다 - 그 파일은 실제로  를 import 하고" —
git 이력에도 온전한 판이 없어, 소스를 다시 읽어 `test_runner_contract.py:42/143`,
`run_python_tests.py` 로 채웠다).

### 의심 목록 4건을 **mutation 으로 판정**했다 — 전부 진짜다

```
test_crawl_resume.py       (제품 10줄)   3/3 검출
  부분문자열 비교로 되돌림 / idx+1 -> idx / resume_from 무시하고 항상 0
test_crawl_exit_code.py    (제품 34줄)   5/5 검출
  collected==0 / persisted==0 / 전법원실패 / 워커 0성공 / persisted 합산
test_frontend_accessibility.py (0줄)     2/2 검출
  role+aria-modal 제거 / aria-labelledby 를 없는 id 로
test_console_encoding.py       (0줄)     이번 세션에 **실제 회귀 2건**을 잡았다
  (내가 넣은 U+2014 EM DASH 출력 리터럴 — 아래 §9)
```

---

## 7. `docs/CLAUDE.md` — 색인 문서가 **없는 폴더를 있다고** 적고 있었다

```
"Note `src/login/` is a stale duplicate of the real `src/app/login/`."
실측: src/ 아래는 app/ components/ lib/ proxy.ts **네 개뿐**. src/login/ 없음.
      docs/BETA_RELEASE_CHECKLIST.md 는 2026-08-22 에 이미 "해결 확인"으로 적었다.
```

`CLAUDE.md` 는 세션마다 컨텍스트로 들어간다 — 여기 틀린 것은 **이후 모든 판단에 전파된다.**
없는 폴더를 "정리 대상 죽은 코드"로 알면, 다음 세션은 있지도 않은 것을 찾거나 다른
폴더를 그것으로 착각한다.

### 회귀 방어와 **그 방어가 한 번 눈이 멀었던 기록**

`test_claude_md_paths_exist()` — 백틱 토큰 중 `/` 가 들어 있어 경로가 분명한 것만 보고,
없어졌다고 밝힌 것(제거/개명 표시가 붙은 것)은 면제한다.

처음 판은 **토큰 앞뒤 120자**를 훑었다. mutation 으로 눈이 먼 것을 확인했다 —
같은 줄에 있던 정상적인 개명 서술(`renamed from \`src/middleware.ts\``)이 120자 안에
들어와 **옆에 심은 가짜 경로까지 함께 면제**했다. 한 줄에 표시가 하나만 있어도 그 줄의
모든 경로가 통과하는 셈이라 검사가 있으나 마나였다.

그래서 표시를 찾는 범위를 (1) 앞뒤 백틱 토큰 사이, (2) 다시 **절 구분자**
(`— ― , ; : ( ) .`)에서 잘라 좁혔다. 그 두 번째 조임을 자기 검증이 잠근다:

```
"(`src/lib/supabaseServer.ts`, `src/qa_ghost/` gates stuff ― renamed from `src/middleware.ts`…)"
  -> ['src/qa_ghost/'] 을 잡아야 한다   (좁히기 전에는 [] 였다)

mutation: 실제 CLAUDE.md 의 `src/proxy.ts` -> `src/ghost_dir/`
  -> FAIL ['src/ghost_dir/']   검출 O
```

---

## 8. `api/auth.py` / `test_auth_jwt.py` / `audit_auth_health.py` — 실측 주장 3건 정정

세 곳이 같은 문장을 공유하고 있었다: *"실측: **이 환경의** `.env` 에
`NEXT_PUBLIC_SUPABASE_URL=https://<ref>.supabase.co/rest/v1/` 가 들어 있었다."*

```
2026-08-24 실측
  .env         키 3개 = SUPABASE_URL(빈 값) / SUPABASE_ANON_KEY(빈 값) / SUPABASE_JWT_SECRET(88자)
               -> NEXT_PUBLIC_SUPABASE_URL 키 자체가 없다
  .env.local   NEXT_PUBLIC_SUPABASE_URL 40자, urlsplit().path == ''  (경로 없음)
  해석 결과    api.auth.SUPABASE_URL 40자 / path '' -> JWKS 경로 '/auth/v1/.well-known/jwks.json' 정상
```

**코드는 그대로 둔다** — `_project_origin()` 정규화는 좋은 방어이고, `.env` 는
gitignore 대상이라 기기마다 값이 다르다. 고친 것은 **사실 주장뿐**이다.
값은 길이/경로 유무만 확인했고 어디에도 출력하지 않았다.

---

## 9. 이번 세션이 스스로 만든 회귀 2건 — 저장소의 가드가 둘 다 잡았다

정직하게 남긴다. 둘 다 `test_console_encoding.py` 가 잡았다 — 내가 만든 회귀를
저장소의 기존 가드가 잡아낸 것이고, 그 가드가 공허하지 않다는 실증이기도 하다.

```
회귀 1  test_schema_hygiene.py:3087  print 문자열에 U+2014 EM DASH
회귀 2  test_schema_hygiene.py:3168  CLAUSE_SEPARATORS 상수의 U+2014 리터럴
```

Windows PowerShell 5.1 은 cp949 로 출력하므로 U+2014 는 `UnicodeEncodeError` 를 낸다.
1번은 U+2015(HORIZONTAL BAR, cp949 `\xa1\xaa`)로 바꿨고, 2번은 **출력이 아니라 찾을 대상
데이터**라 `chr(0x2014)` 로 만들어 리터럴을 없앴다(검사기는 `test_*.py` 의 모든 문자열
상수를 보므로 둘을 구별할 수 없다).

---

## 9-b. ★ 주소 오분류 4행 — "검색에 안 나온다"가 **절반만 맞았다**

`validation_status='FAIL'` 12행을 확인하다가 저장된 `sido` 가 주소와 어긋난 행을 다시 쟀다.

```
id=550  '서울' -> '인천'   인천 계양구 …(효성동, 뉴서울아파트) [카니발 2017년식 승용차]
id=1787 '부산' -> '경남'   경남 양산시 물금읍 부산대학로 150
id=8160 '서울' -> '경기'   경기 시흥시 서울대학로 59-21
id=9977 '세종' -> '제주'   제주 제주시 구좌읍 세화리 산29 (공유자에 "뉴세종하우징")
```

원인은 BUGS #78 이 이미 고쳤다(`extract_sido()` 를 "사전 선언 순서" → "가장 앞선 표기").
남은 것은 **그때 일부러 남긴 데이터 4행**이다. 그런데 그 문단의 마무리가 이렇게 적혀 있었다:

> *"만료 물건이라 검색(D7 기본 제외)에는 나오지 않는다"*

**절반만 맞다.** `src/app/search/SearchForm.tsx:643` 에 **"종결물건 포함" 체크박스**가 있다.

```
실측  GET /api/v1/search?include_closed=true&sido=서울  -> 시흥시(경기) 물건 id=8160 포함
```

방향도 둘이다 — 서울을 고른 사용자에게 **남의 지역이 섞이고**, 인천/경남/경기/제주를 고른
사용자에게는 **제 지역 물건이 빠진다.** 등급은 그대로 두되(만료 4행), "안 보이니 나중에"가
성립하지 않는다는 것만 바로잡았다. 정리는 4행 UPDATE = **승인 영역**
(`backfill_region_normalize.py` dry-run: sido 4행 + sigungu 207행 = 422건 예정, 실행 안 함).

### 같은 자리에서 상한 하나를 조였다

`test_pipeline_integrity.py` §12 의 `sido` 상한이 **5** 였다. 그 5는 Sprint 121이
id=11903 때문에 올린 값인데 **그 행은 지금 이 DB 에 없다**(실측 4행). 상한이 실측보다
하나 헐거우면 새 오분류 하나가 조용히 통과한다 — 5 → **4** 로 내렸다.

```
mutation: 상한을 3으로 낮춤 -> [FAIL] 현재 4행, 상한 3    (검사가 공허하지 않음을 확인)
```

### 상한(ratchet) 전수 점검 — **여유의 종류를 구분해야 한다**

이 저장소는 "고칠 수 없으면 늘어나는 것만 막는다"는 상한 방식을 여러 곳에 쓴다.
전부 다시 재서 실측과 상한을 대조했다. 여유가 있는 곳이 넷이었고, **원인이 두 종류였다.**

| 상한 | 실측 | 여유의 원인 | 조치 |
|---|---|---|---|
| 차량 역방향 오분류 5 | 3 | **근거 없는 패딩** — BUGS #56 이 처음부터 3건으로 적었다 | **5 → 3** |
| `sido` 드리프트 5 | 4 | 5를 만든 id=11903 이 지금 이 DB 에 없다 | **5 → 4** |
| 고아 큐 행 21 | 18 | 21은 더 큰 DB 에서 실제로 잰 값, 3행이 지금 없다 | **그대로 21** |
| `SYNC_MISMATCH_CEILING sigungu` 1 | 0 | 그 1건(대전 2024타경11191-1)이 지금 이 DB 에 없다 | **그대로 1** |

앞의 둘은 조였다 — 상한이 실측보다 헐거우면 그만큼 새 결함이 조용히 통과한다.
뒤의 둘은 두지 않았다 — **0이 된 이유가 "고쳐져서"가 아니라 "그 행이 지금 없어서"**라,
데이터가 원래 크기로 돌아오면 붉어지는 것이 회귀가 아니라 오탐이 된다.

특히 §13-B 는 지금 **"[정리됨] 상한을 0으로 낮출 수 있다"고 스스로 권한다.** 그 제안을
그대로 따르면 안 된다는 것을 코드 옆에 적어 두었다 — 자동 제안은 "줄어든 이유"를 모른다.

```
비공허 확인 (조인 두 상한)
  역방향 상한을 2로 낮춤 -> [FAIL] 현재 3건   (실제로 세고 있다)
  sido 상한을 3으로 낮춤 -> [FAIL] 현재 4행   (실제로 세고 있다)
```

### 같은 4행이 만드는 **또 하나의** 사용자 영향

`test_pipeline_integrity.py` 의 "지금 규칙으로는 통과할 FAIL" 검사가 이렇게 찍는다:

```
FAIL 12행 중 address_mismatch 11행
오탐: 2025타경513824-1 (서울->인천 vs 인천)     <- id=550
오탐: 2016타경3104-1  (세종->제주 vs 제주)     <- id=9977
```

즉 잘못된 `sido` 때문에 검증기가 주소 불일치로 판정해 **화면에 "검증실패"로 뜬다.**
같은 4행이 (1) 남의 지역 검색에 섞이고 (2) 제 지역 검색에서 빠지고
(3) 검증실패로 표시된다 — 세 갈래다.

### 정직하게 남기는 것 — 중복 검사를 하나 만들었다가 지웠다

처음에는 "저장된 sido vs 주소" 검사(11-c)를 **새로 만들었다.** 만들고 나서 mutation 으로
확인하니 `extract_sido()` 퇴행을 **못 잡았다** — 퇴행하면 새로 계산한 값이 저장된 옛 값과
같아져 드리프트가 오히려 **줄기** 때문이다. 그래서 단언 문구("BUGS #78 정규화 퇴행 감지")가
사실이 아니었고, 게다가 §12 가 이미 같은 것을 같은 규칙으로 재고 있었다.

**지웠다.** 이 저장소가 BUGS #78 에서 얻은 교훈이 그대로 적용된다 —
*"같은 판정을 하는 함수가 두 벌이면 한쪽만 고쳐질 수 있다."*
퇴행 축은 `test_normalizer.py` 가 맡는다(mutation 확인: 규칙을 되돌리면 그쪽이 실패한다).
남긴 것은 **새로 안 사실**(체크박스로 노출된다 / 상한이 하나 헐거웠다)뿐이다.

---

## 9-c. 추적된 SQLite 파일 — 기존 가드가 **한 종류를 못 본다**

추적 파일 401개를 매직 바이트(`SQLite format 3\0`)로 훑었더니 **9개가 데이터베이스**였다
(36.9MB). 그 9개 자체는 이미 알려진 항목이다 — 6-2(`test_no_new_tracked_but_ignored_files`)가
`.gitignore:73 *.db.backup*` 로 잡고 있고, 그 주석이 "개인정보 없음(`user_id` 전부 `qa-*`)",
"commit 금지라 늘어나는 것만 막는다"까지 이미 적어 두었다. **거기까지는 새 발견이 없다.**

새 발견은 그 가드의 **사각**이다.

```
git check-ignore  auction.db.backup_20260728_103355   -> .gitignore:73 *.db.backup*   6-2가 잡는다
git check-ignore  qa_snapshot_2026 / db_dump_for_debug -> **무시 안 됨**              6-2가 못 잡는다
```

6-2 는 "무시하겠다고 해 놓고 추적 중인 파일"만 본다. 어떤 무시 규칙에도 안 걸리는 이름
(`fixtures/sample`, `snapshot_before_x`, 확장자 없는 이름)으로 DB 가 커밋되면 아무 말도 없다.
그래서 **이름이 아니라 내용**으로 보는 검사를 하나 더 두었다(401개 전수 0.05초).
allowlist 는 6-2 의 목록을 **그대로 재사용**한다 — 같은 9개를 두 곳에 적으면 한쪽만
갱신되는 날이 온다.

```
mutation (인덱스에만 올리고 커밋하지 않음, 끝나고 되돌림)
  qa_snapshot_2026 (진짜 SQLite, favorites 테이블 포함)을 git add -f
    6-2                  -> [PASS]   (무시 규칙에 안 걸리니 보이지 않는다)
    새 검사               -> [FAIL] ['qa_snapshot_2026']
  정리 후 git status 깨끗함 확인
```

지금 9개가 안전한 이유(합성 `qa-*` 계정)는 **지금** 그렇다는 뜻일 뿐이다. 실사용자가 생긴
뒤 뜬 스냅숏 하나가 같은 습관으로 들어오면 `favorites`/`payments`/`recent_items` 에 진짜
`user_id` 가 담기고, git 이력에서 지우는 비용은 비교가 안 된다.

---

## 9-d. 이 세션이 낸 사고 하나 — `git checkout` 오타로 파일 하나를 되돌렸다

정직하게 남긴다. mutation 정리 명령을 `... && python ...; git checkout -- test_schema_hygiene.py`
로 썼다. 앞 명령이 실패해도 `;` 뒤는 실행되므로, **그 세션에서 그 파일에 넣은 변경이 전부
날아갔다**(커밋 전이라 git 에도 없었다).

복구했다 — 잃은 것은 그 파일 하나뿐이었고, 내용이 전부 이 세션의 기록 안에 있었다.
복구 후 **세 가드 전부 mutation 으로 다시 검증**했다(위 §3 / §7 / §9-c 의 재현 결과가
그 재검증분이다). 남은 차이가 없음을 전체 스위트로 확인했다.

교훈은 두 개다. (1) 정리(cleanup)는 `;` 가 아니라 `&&`/`trap` 으로 앞 단계 성공에 묶어야
한다. (2) mutation 되돌리기에 `git checkout` 을 쓰면 **추적 중인 다른 변경까지** 함께
날아간다 — 이 세션의 나머지 mutation 은 전부 파일 사본(`cp`)으로 되돌렸고, 그쪽은 안전했다.

---

## 10. 결함이 **나오지 않은** 영역 — 잰 것만 적는다

### 보안 (전부 실측)

```
인가       보호 라우트 6종 x (토큰 없음 / 쓰레기 / a.b.c / alg=none 위조) = 18회 -> 전부 401
           admin 라우트 5종 -> 키 없음·틀린 키 모두 500 `관리자 키 미설정` (fail-closed)
           공개 라우트는 잘못된 토큰에도 500 없이 200 (우아한 degradation)
프런트 게이트  /properties, /properties/{id}, /favorites, /mypage -> 307 /login?redirect=… (쿼리 보존)
SQL 주입   sort_by/sort_order 화이트리스트 -> 400, LIKE/UNION 시도 -> 200 total 0, DB 무변경(테이블 27개 유지)
경로 순회  documents/images 에 ..%2f, %2e%2e%2f, 절대경로 -> 404 / 성공 경로는 200(PDF 402KB, JPEG 70KB)
조건부 캐시 If-None-Match -> 304 0B (402KB 절약)
헤더       프런트 4종(X-Content-Type-Options / X-Frame-Options / Referrer-Policy / Permissions-Policy)
           백엔드 2종 — X-Frame-Options 는 **의도적 제외**(이 API 가 문서 뷰어 iframe 대상)
CORS       allow_origins 기본 "*", allow_credentials 미설정(=False), 인증은 Bearer 헤더 -> CSRF 축 아님
퍼징       공개 엔드포인트 467회(쿼리 399 + 경로 68) -> **500 0건**
```

### 데이터 무결성

```
PRAGMA foreign_key_check          위반 0
논리적 고아 6쌍                    전부 0 (doc_raw/document_status/auction_image/favorites/recent_items/auction_case)
auction <-> auction_item 매칭      불일치 0
API vs 직접 SQL 차분 12종          불일치 0 (sido/sigungu/court/가격/유찰/기일/상태/전체)
페이지네이션 전수(19페이지)         수집 1,876 / 중복 0 / 누락 0
자산 무결성 감사                   [1][2][2-b][3][4][4-b][5][9] 어긋남 0
                                   남은 것: 디스크 고아 디렉터리 1개(파일 4개) / 다운로드 고아 8개 14.0MB
                                   / 고아 큐 행 18개 — 셋 다 정리가 승인 영역
```

### 성능 — SPRINT134 기준선과 대조했다 (회귀 없음)

DB 계층을 같은 방식(인 프로세스, 200회)으로 재서 SPRINT134 의 기준(p95 ≤ 3.4ms)과 비교했다.

```
쿼리                 p50(ms)  p95(ms)      쿼리                 p50(ms)  p95(ms)
COUNT 기본             0.045    0.087      정렬(가격) 깊은 페이지    0.140    0.200
PAGE 1                0.138    0.207      sido+sigungu          0.066    0.095
PAGE 94(가장 깊은)      1.410    1.525      주소 LIKE(전체 스캔)     0.481    0.557
```

전부 기준선 안이다. 깊은 페이지만 10배(0.14 -> 1.41ms)인데, 이는 SPRINT134 가
**성능 결함이 아니라 스케일 리스크로** 기록해 둔 기본 정렬 tie-break 의 TEMP B-TREE
비용이다 — 현재 규모에서는 여전히 무시할 수준이고, 그 기록과 일치한다.

HTTP 계층은 같은 요청이 p50 4~17ms / p95 ~30ms 였다. **이 숫자를 위 표와 비교하면 안 된다** —
`uvicorn --reload`(파일 감시자가 붙은 개발 모드)로 잰 값이라 측정 도구가 다르다.
프레임워크 오버헤드이지 쿼리 비용이 아니다.

### 파이프라인 기동 가능성 — 등록만 하면 도는가 (승인 전 de-risking)

등록은 승인 영역이지만, **등록했을 때 곧바로 실패할 이유가 있는지**는 지금 확인할 수 있다.

```
.bat 3개    cd /d %~dp0 있음 / python 3단 폴백(Anaconda -> PATH -> 실패시 [FAILED]+exit 1)
            errorlevel 검사 + [SUCCESS]/[FAILED] 마커 + exit code  -- 셋 다 갖춤
진입점 import  mvp_scraper / doc_worker / migrate_execute / refresh_priority /
            collect_documents / api_server  -> **6/6 import 성공**
            (부팅 시 ADMIN_API_KEY 미설정 경고가 정상 동작하는 것도 함께 확인)
migrate 드라이런  auction 1,876 -> auction_case 1,384 / auction_item 1,876 /
                document_status 5,628  — 실제 DB 현황과 정확히 일치
```

즉 **막고 있는 것은 등록 그 자체뿐**이고, 그 뒤 단계에 알려진 장애물은 없다.

### 의존성

```
npm audit   moderate 1 / high 6 / 합계 7  — 패키지 7개·설치본 전부 스냅샷과 일치(드리프트 0)
pip         requirements.txt 10개 전부 `==` 고정, 설치본 10/10 정확히 일치, 미설치 0
```

---

## 11. ★ 의존성 권고의 **우선순위 근거**를 바로잡았다

문서와 가드는 오랫동안 `next` 권고를 **CVE-2026-64641(Server Actions 미인증 DoS)**
하나로만 불렀다. 같은 묶음에 이 앱 구조에 훨씬 직접적인 것이 있다.

```
GHSA-6gpp-xcg3-4w24
  Middleware / Proxy bypass in App Router applications using Turbopack and single locale
  high / CWE-285(인가 우회) / 해당 범위 >=16.0.0 <16.2.11   -> 설치본 16.2.9 는 **해당됨**
```

전제 조건과 이 앱의 구성이 일치한다 — 라우트 단위 인증 게이트가 `src/proxy.ts`
**하나뿐**이고(`PROTECTED_PREFIXES = /properties, /favorites, /mypage`),
`next dev` 배너가 "Next.js 16.2.9 (Turbopack)", i18n 설정 없음(단일 로케일).

**다만 데이터가 새는 것은 아니다 — 이것도 쟀다.** 개인 데이터는 전부 파이썬 API 가 내고
(`src/lib/api.ts` 가 Supabase access_token 을 Bearer 로 실어 보낸다), 그 API 는
무효 토큰 18회 모두 401 이다. 게이트가 뚫려도 얻는 것은 **빈 화면 껍데기**다.
그래도 등급은 낮추지 않는다 — 인가 경계가 설계대로 동작하지 않는 상태이고, 화면이
데이터를 직접 읽는 경로가 하나만 생겨도 그 순간 실피해가 된다.

`KNOWN_SAFE_MIN_NEXT_VERSION` 도 재실측에 맞춰 `16.3.1` → **`16.3.2`** 로 올렸다
(npm `fixAvailable`, `isSemVerMajor: false`). **업그레이드는 승인 영역이라 하지 않았다.**

---

## 12. 승인이 필요해 SKIP 한 것

| 항목 | 왜 승인 영역인가 |
|---|---|
| 예약 작업 3개 등록 (`register_scheduler_tasks.ps1 -Apply`) | 사용자 환경 변경. **지금 상태에서는 `-SkipCoveredByLegacy` 를 붙이지 말 것** — 커버 중인 기존 작업이 0개다 |
| `.env` 에 `ADMIN_API_KEY` / `SUPER_ADMIN_API_KEY` 설정 | 시크릿 값 결정·주입 |
| `npm install next@16.3.2` | 빌드/런타임 동작 변경 |
| 고아 큐 행 18개 / 고아 문서 디렉터리 1개 / 다운로드 고아 8개(14.0MB) 정리 | 운영 데이터 파괴적 변경 (지금 낭비 비용은 §4 대로 0) |
| 명암비 44곳 AA 미달(브랜드 파랑·회색 텍스트) | 전 화면 인상을 바꾸는 디자인 결정 |
| `document_status` 에 "대상 아님" 상태 신설(COLLECTING 잔존 2,145행) | 상태머신·화면 문구 = 제품 판단 |
| 전액 환불 시 구독 처리 정책 | 정책 결정 (식별자 인프라는 이미 완료 — BUGS #94) |
| `filter/` 죽은 모듈 3개 삭제 | 죽은 코드 제거 승인 |

---

## 12-b. 승인 항목을 실행할 사람을 위한 순서 (이 세션이 확인한 것만)

```
1) 현재 상태를 직접 잰다        python audit_schedule_health.py          (읽기 전용)
2) 무엇이 등록될지 본다          .\register_scheduler_tasks.ps1           (dry-run, 무변경)
   -> 오늘 실행하면 3개 전부 "(신규)" 로 뜬다. -SkipCoveredByLegacy 는 붙이지 말 것.
3) 등록한다                     .\register_scheduler_tasks.ps1 -Apply
   -> 스크립트가 등록 후 **다시 조회해서** NextRunTime 을 확인한다("등록했다"가 아니라 "등록됐다")
4) 첫 실행 뒤 로그로 확인       logs\daily_run.log  /  logs\doc_run.log   (끝에 [SUCCESS]/[FAILED])
5) 결과를 다시 잰다             python audit_schedule_health.py
                                python test_pipeline_integrity.py
   -> 기일 남은 물건이 0을 넘으면 `docs/BETA_RELEASE_CHECKLIST.md` 의
      `<!-- P0A-VERDICT: OPEN -->` 를 `RESOLVED` 로 바꿔야 한다(안 바꾸면 §1의 가드가 실패한다).
```

**SYSTEM 계정으로 등록하지 말 것** — `python.exe` 가 사용자 PATH 에만 있다
(이 세션 실측: 머신 PATH 로 해석 불가). 스크립트가 기본으로 현재 사용자 계정을 쓴다.

---

## 13. 남은 Backlog (승인 없이 가능한 것)

- `docs/CURRENT_STATE.md` / `docs/CHANGELOG.md` 의 Sprint 251~267 기록에도 §1 과 같은
  환경 의존 수치가 남아 있을 수 있다. 이번 세션은 **판단에 직접 쓰이는 세 문서**
  (`BETA_RELEASE_CHECKLIST.md` / `BUGS.md` / `CLAUDE.md`)와 등록 스크립트만 정정했다.
- `logs/errors.jsonl` 끝 2줄이 테스트 잔재다(`2024타경1234` / `"boom"`,
  2026-08-21 16:03·16:04). 지금은 테스트가 임시 디렉터리를 쓴다(연속 실행으로 확인:
  44줄 불변). 잔재 삭제는 운영 로그 변경이라 손대지 않았다.
- `auction_item` 에 완전 중복 인덱스가 남아 있다(`case_no` x2, `auction_date` x2,
  `minimum_bid_price` x2, `sido` 는 복합 인덱스의 접두). `KNOWN_DUPLICATE_INDEXES`
  로 추적 중이고, 제거는 마이그레이션 = 승인 영역.
- 추적 중인 DB 백업 9개(36.9MB)는 `git rm --cached` + commit 이 필요해 손대지 않았다.
  6-2 와 새 SQLite 검사가 **늘어나는 것만** 막고 있다.

---

## 14. 왜 여기서 멈추는가

승인 없이 수행 가능한 축을 전부 훑었고, 남은 발견은 전부 위 §12 의 승인 영역이다.

```
코드      제품 코드에서 새 결함 0건 (퍼징 467회 500 0건, 차분 12종 불일치 0)
          - 이번에 고친 것은 전부 **진단 도구·가드·문서**다. 제품 동작은 한 줄도 안 바꿨다.
데이터    무결성 위반 0, 고아 0(FK/논리 6쌍), 세션 전후 행수·integrity_check 동일
          (auction/auction_item 1,876 / auction_case 1,384 / document_queue 3,498 /
           auction_image 45 / doc_raw 556 / document_status 5,628 / favorites 0 /
           recent_items 36 — 시작·종료 동일, WAL/SHM 잔재 없음)
테스트    python 49 PASS / 1 FAIL(승인 영역) / 단언 7,763,  node 171 PASS / 1 FAIL(같은 원인)
          mutation 11개 대상 21건 — 20건 검출.
          검출 못 한 1건(§7 의 120자 창)은 **가드의 사각을 드러낸 것**이고,
          그 자리에서 좁혀 고친 뒤 같은 변이로 재확인해 검출됨
빌드      tsc 0 / eslint 0 / next build 성공
문서      판단에 쓰이는 3문서 + 등록 스크립트 정정, 기계 판독 가드 3종 신설
```

남은 P0 은 **하나이고 그 하나가 승인 영역**이다 — 크롤이 2026-08-11 이후 돌지 않아
기일 남은 물건이 0건이고, 그래서 기본 검색이 빈 화면이다. 이 세션이 할 수 있는 것은
그 사실을 정확히 재고, 문서가 반대말을 하지 못하게 잠그고, 사람이 등록을 실행할 때
밟을 함정(중복 등록 탐지 2건, 잘못된 `-SkipCoveredByLegacy` 안내)을 없애는 것까지였다.
전부 했다.
