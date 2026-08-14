# Sprint 115 ― 동기화가 법원을 무시했고, 실패를 성공으로 보고했다 (2026-08-14)

> 앞 Sprint: `docs/SPRINT114_FALSE_VALIDATION_FAIL.md`
>
> **별도 파일 이유**: Sprint 100~114와 같다 ― `docs/BUGS.md` / `docs/CURRENT_STATE.md`는
> 다른 세션의 편집 대상이라 충돌을 피했다.

**제품 결함 2건을 찾아 고쳤다.** 둘 다 `migrate_execute.py` 에 있고,
둘 다 "이미 고쳤다고 기록된 것의 나머지 절반"이다.

---

## 어떻게 찾았나 ― 고아 파일 3개에서 시작했다

문서 상태 양방향 대조(§11 확장, 아래 4절)를 하다가 **어느 물건에도 속하지 않는 문서 파일
3개**를 발견했다. 전부 한 디렉터리였다.

```
documents\고양지원\2024타경2803\1\{spec.pdf, status.html, appraisal.pdf}
```

그런데 `2024타경2803` 은 DB에 있었다 ― **춘천지방법원** 소속으로.
큐를 보니 답이 나왔다.

```
document_queue
  고양지원      2024타경2803 물건1  spec/status/appraisal  done      <- 문서가 여기 있다
  춘천지방법원  2024타경2803 물건1  spec/status/appraisal  pending
```

**같은 사건번호가 두 법원에 존재한다.** 법원마다 사건번호를 독립 채번하므로 당연한 일이고,
실 DB에는 그런 사건번호가 **3개** 있다(2024타경34089 / 2024타경3700 / 2024타경4973).

그래서 물었다 ― **사건번호만으로 조회하는 코드가 남아 있는가?**

## #115-1 ★ `document_status` 조회에 법원이 없다

`migrate_execute.py` 는 스스로 이 위험을 알고 있었다. 주석에 이렇게 적혀 있다.

> 2026-08-07: 위 "Critical TODO"(court_code+case_no+item_no 식별키)의 남은 절반을 해소한다.
> auction_item 조회/갱신은 여전히 `WHERE case_no=? AND item_no=?`로 **법원 구분이 없었다**.
> … 실측 결과 현재 그런 쌍은 0건이지만, 사건번호 충돌 자체는 이미 존재하므로
> **언제든 터질 수 있는 잠재 결함이다.**

그 수정은 `auction_item` UPSERT를 `(case_id, item_no)` 로 바꿨다. 그런데 **60줄 아래**
`document_status` 조회는 옛 형태 그대로였다.

```python
item = conn.execute(
    "SELECT id FROM auction_item WHERE case_no = ? AND item_no = ?",   # 법원이 없다
    (row["case_no"], row["item_no"])
).fetchone()
```

**같은 수정의 나머지 절반이 빠져 있었다.** Sprint 106의 "정적 확인 완료" 주석이
5개 중 2개에서 틀렸던 것과 같은 실패 모양이다.

### 재현 (사본 DB, 실 DB 무변경)

`2024타경3700` 은 부산지방법원(물건1)과 수원지방법원(물건2~15)에 있다.
**부산에 물건2를 만들어** 충돌을 실제로 성립시켰다. 부산 쪽만 문서를 수집한 상태로 뒀다.

```
수정 전
  부산 물건2 (has_spec_pdf=1)  ->  document_status(SPEC) = None   ★ 행이 아예 없다
  수원 물건2 (has_spec_pdf=0)  ->  document_status(SPEC) = COLLECTING
  자체 검증                     ->  [FAIL] document_status 불일치: 5628 != 5631

수정 후
  부산 물건2  ->  READY
  수원 물건2  ->  COLLECTING
  자체 검증   ->  [OK] document_status 건수 일치
```

조회가 둘 중 **아무 행이나** 돌려주고, 두 물건의 상태가 한 `item_id` 로 몰린 뒤
`INSERT OR IGNORE` 가 나중 것을 조용히 버린다. 결과는 **수집해 둔 문서를 사용자가
영원히 못 보는 것**이다 — 상태 행이 없으니 화면에 문서 자체가 나타나지 않는다.

### 수정

조회 형태를 `storage/database.py:_document_status_item_id()` 와 **같게** 맞췄다.

```python
SELECT ai.id FROM auction_item ai
JOIN auction_case ac ON ac.id = ai.case_id
WHERE ac.court_code = ? AND ai.case_no = ? AND ai.item_no = ?
```

같은 것을 찾는 조회가 두 벌이면 한쪽만 고쳐진다 ― 이번이 바로 그 사례다.

## #115-2 ★ 자체 검증이 실패해도 `exit 0`

재현 중에 더 나쁜 것이 보였다. 위 로그에서 `[FAIL] document_status 불일치` 가 찍혔는데
**프로세스 종료코드는 0이었다.**

```python
if ds == orig * 3:
    print("  [OK] ...")
else:
    print(f"  [FAIL] document_status 불일치: ...")   # 출력만 하고 끝

...
if __name__ == "__main__":
    execute()
    sys.exit(0)          # 항상 0
```

`run_daily.bat` 은 `if errorlevel 1` 로 실패를 판정한다. 그래서
**자기 검증이 실패했다고 적혀 있는 그 로그 파일에 `[SUCCESS]` 마커가 함께 찍힌다.**

이 저장소가 Sprint 13/54/99에서 `.bat` 계층에 대해 없앤 "실패 은폐"와 같은 모양이고,
이번에는 파이썬 쪽에 남아 있었다. **스케줄러를 켜기 직전에 발견한 것이 다행이다** ―
등록 후 이 상태였다면 문서 상태가 유실돼도 매일 "성공"으로 보고됐을 것이다.

### 수정

건수 검증 결과를 모아 `execute()` 가 성공 여부를 돌려주고, `__main__` 이 그것을 종료코드로 쓴다.

```
정상       -> execute() True  / exit 0
검증 실패   -> execute() False / exit 1  -> run_daily.bat 이 [FAILED] 를 남긴다
```

판정 대상은 **결정적인 건수 검증 두 개뿐**으로 좁게 유지했다.
예전에 이모지 인코딩 때문에 데이터는 정상인데 exit 1로 끝나 **매일 실패로 보고된 일**이
있었기 때문이다(그 사고 기록이 같은 함수 주석에 남아 있다). 거짓 실패를 다시 만들지 않는다.

## 회귀 검사 ― `test_auction_identity.py` §5 / §6 신설

이 파일 §2는 **크롤러 쓰기 경로**(`upsert_batch`)의 법원 교차 안전성을 이미 검사한다.
빠진 것은 **동기화 경로**였다. 데이터가 화면에 닿으려면 `migrate_execute` 를 한 번 더 지난다.

```
--- 5. cross-court migrate_execute safety (scratch copy only) ---
[PASS] 전제: 두 법원 행이 만들어졌다: 2
[PASS] 전제: 한쪽만 수집 완료: [1, 0]
[PASS] migrate_execute 가 검증을 통과한다
[PASS] 수집한 법원은 READY
[PASS] 수집하지 않은 법원은 COLLECTING
[PASS] 두 법원 모두 document_status 행을 갖는다(유실 없음)

--- 6. migrate_execute 종료코드 계약 ---
[PASS] 정상 상태에서는 True(성공)를 돌려준다
[PASS] 검증이 깨지면 False(실패)를 돌려준다
[PASS] __main__ 이 execute() 의 반환값을 종료코드로 쓴다
```

마지막 검사가 필요한 이유: 반환값을 만들어 놓고 `__main__` 이 무시하면 계약이 무의미하다.

> **전제 검사가 내 실수를 잡았다.** 처음에 `upsert_batch()` 입력에 `has_spec_pdf=1` 을
> 넣었는데 그 함수는 그 필드를 받지 않는다(수집 결과라 doc_worker 가 따로 쓴다).
> `[FAIL] 전제: 한쪽만 수집 완료: [0, 0] (expected [1, 0])` 이 떠서 바로 알았다.
> 전제 없이 만들었다면 **아무것도 검사하지 않는 초록불**이 됐을 것이다.

## #115-3 같은 결함의 세 번째 자리 ― 미리보기가 다른 숫자를 말한다

두 결함을 고친 뒤 **이 부류를 전수로 훑었다** ― 파이썬 수준에서 사건번호만으로 키를 잡는 곳.

```
migrate_execute.py:45   key = (row["court_code"], row["case_no"])     OK
migrate_dryrun.py:29    case_map[case_no] = {...}                     ★ 법원이 없다
check_*.py / step*.py                                                 (gitignore된 일회성)
api/v1/*, storage/*     LIKE 검색 필터거나 court 를 별도 인자로 받는다   OK
```

`migrate_dryrun.py` 는 **git 추적 대상**이고 `docs/CURRENT_STATE.md` 에도 실려 있다.
`migrate_execute.py` 를 돌리기 전에 무엇이 만들어질지 보여주는 미리보기다.

```
2026-08-14 실측
  dryrun  (case_no 만)      1,381건
  execute (court+case_no)   1,384건   <- 실제 auction_case 행 수
```

**미리보기가 실행 결과보다 3건 적게 예고한다.** 데이터가 깨지지는 않지만,
실행 뒤 그 차이를 보고 "execute 가 뭔가 잘못했다"고 오판하게 된다 ―
**거짓말하는 측정 도구**다. 키를 `(court_code, case_no)` 로 맞췄다.

회귀는 `test_auction_identity.py` §7로 고정했다. 소스를 대조하지 않고 **출력을 읽어**
`(court, case)` 고유 건수 및 실제 `auction_case` 행 수와 **셋이 같은지** 본다
(형태만 같고 동작이 다르면 소스 대조는 통과한다).

```
    예고 1384 / (court,case) 고유 1384 / 실제 auction_case 1384
```

## 4. 함께 넣은 것 ― 문서 상태 양방향 대조

이 조사의 출발점이었다. `test_document_status_sync.py` §11은
"READY -> 파일이 있는가" 한 방향만 봤다. 반대쪽도 결함이다 ―
**파일은 있는데 READY가 아니면** 받아 둔 문서를 사용자가 못 본다.

```
[PASS] READY인데 뷰어가 서빙할 수 없는 행: 0
    READY 아님 5072행 대조
[PASS] 파일은 있는데 화면 상태가 READY가 아닌 행: 0
```

실측: 서빙 가능한 파일 **556개** = READY **556행**, 양방향 모두 0건.
정상 경로에서는 생길 수 없다(`mark_queue_done()` 이 한 트랜잭션에서 처리).
0이 아니게 되는 경우는 **경로 밖에서 파일이 들어온 것**이다 — Sprint 111의 빈 캡처와 같은 입구.

## 변이 검증

| | 변이 | 결과 |
|---|---|---|
| M86 | COLLECTING 물건 경로에 파일을 심는다 | **검출 O** ― 경로까지 지목 |
| M87 | #115-1을 수정 전으로 되돌림 | **검출 O** ― `{'QA법원A': 'READY', 'QA법원B': None}` |
| M88 | `execute()` 가 항상 True를 돌려주게 | **검출 O** |
| M89 | `__main__` 이 반환값을 무시하게 | **검출 O** |
| M90 | dryrun 키를 `case_no` 단독으로 되돌림 | **검출 O** ― `1381 (expected 1384)` |

M87의 출력이 결함을 그대로 보여준다 ― 한 법원의 상태 행이 **통째로 사라진다.**

> M90은 처음에 "검출 X"로 나왔다. **가드의 구멍이 아니라 내 변이 도구의 문제**였다 ―
> 자식 프로세스가 cp949로 출력하는데 utf-8로 읽어 한글이 깨져 매칭에 실패했다.
> `PYTHONIOENCODING=utf-8` 을 넘겨 다시 돌리니 정상 검출됐다.
> **변이가 안 잡혔다고 곧바로 "가드에 구멍"이라고 적지 않는다** ― 먼저 도구를 의심한다.

## 검증

| 항목 | 결과 |
|---|---|
| 파이썬 테스트 | **28/28 파일 통과** (실크롤 3개 제외) |
| `python -m compileall` | **exit 0** |
| 프런트 | 무변경 (Sprint 107에서 107/107, TSC/LINT/BUILD exit 0) |
| 실 DB | **한 줄도 쓰지 않았다** ― `auction` 1,876 / `auction_item` 1,876 / `document_status` 5,628 그대로 |
| 재현·변이 | 전부 임시 사본 DB. `documents/` 는 심은 파일만 삭제하고 기존 디렉터리는 보존 |

## 수정 파일

```
migrate_execute.py            ★ document_status 조회에 법원 추가 + 검증 실패를 종료코드에 반영
migrate_dryrun.py             ★ auction_case 중복 제거 키에 법원 추가 (예고 1381 -> 1384)
test_auction_identity.py      §5/§6/§7 신설 (동기화 경로의 법원 구분 / 종료코드 / 예고 일치)
test_document_status_sync.py  §11에 반대 방향(파일 있는데 READY 아님) 추가
```

**제품 동작 변경은 `migrate_execute.py` 두 곳**이고, 정상 경로의 결과는 그대로다
(기존 테스트 전부 무변경 통과). 달라지는 것은 **법원이 충돌할 때**와
**검증이 실패했을 때** 뿐이다.

## SKIP (변동 없음)

Sprint 114의 SKIP 표 그대로.

## 남은 Backlog

- **★★ 수집 파이프라인 스케줄러 등록** ― 2026-08-20에 검색 결과 0건이 된다.
  `register_scheduler_tasks.ps1 -Apply` 한 줄이면 된다(Sprint 112).
  **이번 수정 두 건이 그 등록 전에 들어간 것이 중요하다** ―
  #115-2가 남아 있었다면 문서 상태 유실이 매일 "성공"으로 보고됐을 것이다.
- Sprint 105~114의 SKIP 표 항목들 (전부 승인/외부 조치 대기)
