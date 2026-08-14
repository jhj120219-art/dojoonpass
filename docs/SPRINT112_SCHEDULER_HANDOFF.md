# Sprint 112 ― 스케줄러 등록 한 단계를 준비했다 (2026-08-14)

> 앞 Sprint: `docs/SPRINT111_CLAIM_REMEASUREMENT.md`
>
> **별도 파일 이유**: Sprint 100~111과 같다 ― `docs/BUGS.md` / `docs/CURRENT_STATE.md`는
> 다른 세션의 편집 대상이라 충돌을 피했다.

**★★ 마감이 6일 남았다.** 검색에 남은 진행 중 물건은 9건이고 전부 2026-08-19까지의
기일이라, **2026-08-20부터 검색 결과가 0건**이 된다. 스케줄러 등록은 SKIP 항목이라
내가 하지 않는다 ― 대신 **사용자가 한 줄로 끝낼 수 있게** 준비했다.

---

## 1. 먼저 TODO/FIXME 전수 (새 사실 없음)

운영 코드 전체에서 마커는 **4개**뿐이었고, 3개가 `SearchForm.tsx` 의 `TODO(API 미지원)` 다.
실측으로 재확인했다 ― 면적/특수조건 파라미터는 HTTP 200에 **건수 불변**(1,876 그대로),
즉 필터가 걸린 것처럼 보이지만 전혀 걸러지지 않는다.

**이미 `docs/BUGS.md` #81 이 같은 재현과 보류 사유까지 기록**하고 있고,
`test_search.py` §6 이 대조군을 포함한 12검사로 양방향 드리프트를 막고 있다.
보류 사유(면적 컬럼이 없어 스키마 변경 + 크롤러 추출 + 정규화 규칙이 함께 필요)도 타당하다.
**새 사실 없음.**

## 2. 틀린 가설 하나 (기록해 둔다)

`.bat` 3개에서 이 패턴을 보고 cmd 의 지연확장 버그라고 판단했다.

```bat
if errorlevel 1 (
    echo [FAILED] ... exited with code %errorlevel% >> logs\daily_run.log
```

"괄호 블록 안의 `%errorlevel%` 은 파싱 시점에 전개되므로 항상 0이 찍힌다"고 봤다.
**재현해 보니 42가 정확히 찍혔다.** `if` 블록은 앞 명령이 끝난 **뒤에** 파싱되므로
이 자리에서는 문제가 없다(문제는 명령과 참조가 *같은* 블록 안에 있을 때다).

**결함 아님.** 고칠 뻔한 것을 실측이 막았다.

## 3. ★★ 등록 준비 ― 계정 함정을 먼저 찾았다

재검증 결과 저장소를 가리키는 작업은 **여전히 0개**(전체 248개 중)다.
그리고 등록할 때 걸릴 함정을 하나 실측했다.

```
머신 PATH 에 Python312            : False
사용자 PATH 에 Python312          : True
C:\ProgramData\Anaconda3\python.exe : 없음
```

**`python.exe` 가 사용자 PATH 에만 있다.** 작업을 SYSTEM 계정으로 등록하면
`.bat` 의 3단 폴백이 인터프리터를 찾지 못하고 실패한다.

> 다행히 **조용히 실패하지는 않는다** ― Sprint 54가 넣은 세 번째 분기가
> `[FAILED] Python 인터프리터를 찾을 수 없습니다` 를 로그에 남기고 exit 1 한다.
> 2026-08-03~08-11의 9일 크롤 중단이 바로 이 자리에서 **조용히** 일어났던 일이다.

### `register_scheduler_tasks.ps1` (신설, **dry-run 기본**)

이 저장소의 `--apply` 관례를 따른다. 인자 없이 실행하면 계획만 보여주고 아무것도 바꾸지 않는다.

```
> .\register_scheduler_tasks.ps1

선행 조건
  배치 파일 3개        : OK
  Anaconda python      : 없음 (PATH 폴백)
  PATH python          : ...\Python312\python.exe
  머신 PATH 로 해석 가능 : 아니오 -> SYSTEM 계정 등록 금지

등록할 작업
  DojoonPass-PriorityRefresh   매일 01:50  run_priority_refresh.bat  (신규)
  DojoonPass-DocWorker         매일 02:00  run_doc_worker.bat        (신규)
  DojoonPass-DailyCrawl        매일 06:00  run_daily.bat             (신규)

실행 방식 : 로그온 상태에서만 (비밀번호 불필요)

[DRY-RUN] 아무것도 등록하지 않았다. 실제로 등록하려면 -Apply 를 붙여라.
```

실제 등록은 **사용자가** 한다:

```powershell
.\register_scheduler_tasks.ps1 -Apply
```

설계에서 신경 쓴 것:

- **현재 사용자 계정**으로 등록한다(위 함정 회피). 비밀번호가 필요 없는 방식이 기본이고,
  로그오프 상태에서도 돌려야 하면 `-RunWhetherLoggedOn` 을 준다.
- 시각 순서를 지킨다 ― 01:50 우선순위 → 02:00 문서 수집 → 06:00 사건 수집.
  우선순위가 먼저 갱신돼야 기일 임박 물건의 문서가 앞으로 온다.
- 노트북/절전 대비 ― `-StartWhenAvailable`(놓친 실행 따라잡기),
  `-DontStopIfGoingOnBatteries`, 실행 시간 제한 4시간.
- 등록 후 **다시 조회해서** 확인한다. "등록했다"가 아니라 "등록됐다"로 판정하고,
  다음 실행 시각을 함께 출력한다.
- 선행 조건이 안 맞으면 **등록 전에** 멈춘다(배치 파일 누락 / python 없음).

**나는 dry-run 만 실행했다.** 실행 후 `DojoonPass-*` 작업 수가 **0개**임을 재조회로 확인했다.

## 4. 만들면서 밟은 함정 ― BOM 없는 `.ps1`

처음 저장한 `.ps1` 은 **한 줄도 실행되지 않았다.**

```
Unexpected token '?섏쭛' in expression or statement.
The string is missing the terminator: ".
Missing closing '}' in statement block or type definition.
```

Windows PowerShell 5.1은 BOM이 없는 `.ps1` 을 **시스템 ANSI 코드페이지(cp949)** 로 읽는다.
UTF-8로 저장한 한글이 깨지고, 깨진 바이트가 따옴표·괄호를 삼켜 파싱이 무너진다.
BOM 3바이트를 붙이자 그대로 정상 동작했다.

### 그래서 검사를 넣었다 ― `test_schema_hygiene.py`

기존 §8은 **"HEAD와 같은가"** 를 본다. 이건 다른 종류의 규칙이다:

- **절대 요건**이다(HEAD와의 비교가 아니라 그 자체로 깨진다)
- **신규 파일**에도 적용된다(§8은 HEAD가 없는 새 파일을 건너뛴다)
- `.ps1` 은 §8의 대상 확장자에 **없다**

```
--- 한글이 든 .ps1 의 UTF-8 BOM ---
    .ps1 1개 중 비ASCII 포함 1개
[PASS] BOM 없는 비ASCII .ps1: []
```

순수 ASCII 인 `.ps1` 은 코드페이지와 무관하므로 대상에서 뺀다(불필요한 규칙을 만들지 않는다).

## 변이 검증

| | 변이 | 결과 |
|---|---|---|
| M79 | `register_scheduler_tasks.ps1` 의 BOM 제거 | **검출 O** ― 그리고 **실제로 PowerShell 파싱 실패** |

두 번째가 중요하다. 가드가 스타일 규칙이 아니라 **진짜 고장**을 막는다는 확인이다.
원복 후 첫 3바이트가 `239,187,191`(EF BB BF)임을 확인했다.

## 검증

| 항목 | 결과 |
|---|---|
| 파이썬 테스트 | **28/28 파일 통과** (실크롤 3개 제외) |
| `python -m compileall` | **exit 0** |
| 프런트 | 무변경 (Sprint 107에서 107/107, TSC/LINT/BUILD exit 0) |
| 실 DB | **한 줄도 쓰지 않았다** |
| 스케줄러 | **등록 0건** ― dry-run 만 실행하고 재조회로 확인 |

## 수정 파일

```
register_scheduler_tasks.ps1   신설 (dry-run 기본, 사용자가 -Apply 로 등록)
test_schema_hygiene.py         한글 .ps1 의 UTF-8 BOM 검사 신설
```

**제품 코드 변경 0건.**

## ★★ 사용자가 할 일 (마감 2026-08-20)

```powershell
cd C:\Users\jhj12\OneDrive\Desktop\dojoonpass
.\register_scheduler_tasks.ps1           # 먼저 계획 확인
.\register_scheduler_tasks.ps1 -Apply    # 등록
```

첫 실행 뒤 `logs\daily_run.log` / `logs\doc_run.log` 끝의 `[SUCCESS]` / `[FAILED]` 마커로
결과를 확인하면 된다.

## SKIP (변동 없음)

Sprint 110~111의 SKIP 표 그대로 ― 스케줄러 **실행**(위 `-Apply`)은 사용자 환경 변경이라
내가 하지 않는다. 그 외 각종 `--apply`, 죽은 스키마 삭제, worktree 삭제,
`total_failures` 정의, 환불 시 구독 처리, httpx2 전환, 현황조사서 버튼 id,
문서 3종의 구독 게이트, 소프트 삭제 전환, '수집 대상 아님'의 화면 표시(2,328건).
