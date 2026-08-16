# Sprint 133 ― `cleanup_orphans_dryrun.py`가 cp949 콘솔에서 죽는다 + 기존 가드의 사각지대 (2026-08-16)

> 앞 Sprint: `docs/SPRINT132_PAYMENT_LIFECYCLE_ROLLBACK_AUDIT.md`
>
> **별도 파일 이유**: Sprint 100~132와 같다.

Failure Recovery/False Success 감사 중 Document/Filesystem 고아 데이터 점검 도구를
직접 재실행해 실측하다가(`cleanup_orphans_dryrun.py` — Sprint 105가 만든 읽기 전용
진단 스크립트) 실제로 크래시를 재현했다.

## 1. 재현

```
$ python cleanup_orphans_dryrun.py
Traceback (most recent call last):
  File ".../cleanup_orphans_dryrun.py", line 151, in <module>
    sys.exit(main())
  File ".../cleanup_orphans_dryrun.py", line 54, in main
    head("1. document_queue 고아 — 대응 auction_item 이 없는 행")
  File ".../cleanup_orphans_dryrun.py", line 42, in head
    print("\n" + "=" * 74 + "\n" + t + "\n" + "=" * 74)
UnicodeEncodeError: 'cp949' codec can't encode character '—' in position 99: illegal multibyte sequence
```

이 저장소가 이미 여러 번 잡아 온 정확히 그 실패 모양이다 — U+2014 EM DASH가 cp949
콘솔(이 저장소의 기본 실행 환경, `test_console_encoding.py` 참고)에서 죽인다.
`docs/CURRENT_STATE.md`/`docs/BUGS.md`/Sprint 문서를 먼저 확인했다 —
`cleanup_orphans_dryrun.py`는 Sprint 105가 만들었고 여러 Sprint가 그 존재를
언급하지만, **이 크래시 자체는 어디에도 기록된 적이 없다.** 새 발견이 맞다.

## 2. 원인 ― 기존 가드(`test_console_encoding.py`, Sprint 72)가 왜 못 잡았나

이 저장소에는 정확히 이 문제를 막기 위한 전수 스캔 가드가 이미 있다
(`test_console_encoding.py::test_all_output_literals_are_console_encodable`,
2026-08-13 Sprint 72). 그런데 방금 이 파일로 실제 크래시가 재현됐는데 그 가드는
**계속 PASS를 보고하고 있었다.** 원인을 코드에서 찾았다.

`output_literals()`(비-테스트 파일 대상)는 `print(...)`/`logger.*(...)` 호출에
**직접** 박힌 문자열 리터럴만 본다. 그런데 `cleanup_orphans_dryrun.py`는:

```python
def head(t):
    print("\n" + "=" * 74 + "\n" + t + "\n" + "=" * 74)
...
head("1. document_queue 고아 — 대응 auction_item 이 없는 행")
```

문자열이 `print()`에 직접 있지 않고 **한 단계 감싼 래퍼 함수(`head`)의 인자로
전달**된다. 스캐너는 `head(...)` 호출을 `print`/`logger.*` 이름 목록에 없다는
이유로 통째로 지나친다 — **"통과"를 보고하면서 실제로는 그 파일의 진짜 출력
경로를 보지 않고 있었다.** 이 스캐너 자신의 §0 원칙("조용히 건너뛴 파일이 있으면
이 가드는 통과를 보고하면서 실제로는 보지 않은 것이 된다")과 같은 종류의 함정이
파일 단위가 아니라 **함수 호출 단위**로 재발한 셈이다.

## 3. 고친 것

### 3-1. `cleanup_orphans_dryrun.py` — em-dash 4곳 제거

`head()`로 넘어가는 4개 문자열의 U+2014를 일반 하이픈(`-`)으로 바꿨다(모듈
docstring 안의 2곳은 출력되지 않으므로 그대로 둔다 — 이 검사 자체가 docstring은
제외 대상으로 이미 설계돼 있다). 크래시 없이 끝까지 실행됨을 확인했고, 그 결과
현재 DB 상태도 실측했다: 고아 큐 21행, 빈 고아 디렉터리 1개, 파일이 든 고아
디렉터리 1개(`고양동부/2024타경2803`, 4개 파일 12.5MB — Sprint 105가 처음 찾은
바로 그 사례가 아직 정리되지 않은 채 남아 있다. 삭제는 이 스크립트의 설계대로
여전히 사람 판단 영역).

### 3-2. `test_console_encoding.py` — "투명 출력 래퍼" 탐지 추가

`_wrapper_print_functions(tree)` 신설: 모듈 최상위 함수 중 자신의 매개변수를
그대로 `print()`/`logger.*()` 호출의 인자로 넘기는 함수를 찾아 이름과 "문자열이
실리는 매개변수 위치" 집합을 돌려준다. `output_literals()`의 비-테스트 파일 분기가
`print`/`logger.*` 호출뿐 아니라 이렇게 찾은 래퍼 함수 호출도 같은 방식으로
스캔하도록 확장했다. **동일 패턴 전수 검색**: 저장소 전체에서 `head`류 출력
래퍼 함수가 다른 곳에도 있는지 찾아봤으나(`grep`으로 `def head(` 검색)
`cleanup_orphans_dryrun.py`가 유일했다 — 지금 당장 추가로 걸리는 파일은 없지만,
가드 자체의 사각지대를 없앤 것이라 앞으로 같은 모양의 래퍼가 생겨도 잡힌다.

## 변이 검증

| | 변이 | 결과 |
|---|---|---|
| M133 | 고친 4곳 중 1곳(`head("1. ... - ...")`)의 하이픈을 다시 EM DASH로 되돌림(재현) | **검출 O** ― `test_console_encoding.py`가 `cleanup_orphans_dryrun.py:54 U+2014`를 즉시 보고(전에는 이 변이가 있어도 스캐너가 못 봤다는 뜻 — 확장 전 코드로 같은 변이를 재현하면 조용히 통과했을 것이다) |

원복 후 `diff`로 원본과 바이트 단위 동일 확인.

## 검증

| 항목 | 결과 |
|---|---|
| `cleanup_orphans_dryrun.py` 실행 | 크래시 없이 완주, exit 0, stderr 없음 |
| `test_console_encoding.py` | 전체 PASS(신설 래퍼 탐지 포함), 저장소 전체 재스캔에서 새 오탐 0건 |
| `test_api_regression.py`/`test_race_conditions.py`/`test_schema_hygiene.py`/`test_bootstrap.py`/`test_pipeline_integrity.py`/`test_auction_identity.py` | 전체 PASS(회귀 없음) |
| `python -m compileall` | exit 0 |
| `npx tsc --noEmit` | exit 0 |
| `npm run lint` | 0 issues |
| 변이 잔여 | `cleanup_orphans_dryrun.py` 원본과 diff 0(원복 확인) |
| 실 DB | 읽기 전용 연결만 사용(`file:...?mode=ro`), 쓰기 없음 |

## 수정 파일

```
cleanup_orphans_dryrun.py    head()로 전달되는 문자열 4곳의 U+2014 -> 일반 하이픈
test_console_encoding.py     _wrapper_print_functions() 신설 + output_literals()가
                              투명 출력 래퍼 호출도 스캔하도록 확장
docs/SPRINT133_CONSOLE_ENCODING_WRAPPER_GAP.md   신규 (본 문서)
```

## SKIP

| 항목 | 이유 |
|---|---|
| 고아 큐 21행 / 고아 디렉터리 삭제(`고양동부/2024타경2803` 포함) | 파괴적 운영 데이터 삭제 — 이 스크립트 자신의 설계 원칙("삭제는 운영 판단")대로 SKIP |

## 남은 Backlog

- **★★ 수집 파이프라인 스케줄러 등록** ― 2026-08-20에 검색 결과 0건이 된다(Sprint 112, 4일 남음).
- 위 SKIP 항목(고아 데이터 정리, 사람 판단 필요)
- Sprint 105~132 SKIP 표의 나머지 승인 대기 항목들
- 다음 Audit 영역: Frontend/Beta Journey, Performance/N+1 나머지, Technical Debt,
  Release Audit (계속 진행)
