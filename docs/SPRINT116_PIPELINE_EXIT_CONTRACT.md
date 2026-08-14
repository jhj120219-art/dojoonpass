# Sprint 116 ― 파이프라인 전체의 실패 전달을 고정했다 (2026-08-14)

> 앞 Sprint: `docs/SPRINT115_MIGRATE_COURT_KEY.md`
>
> **별도 파일 이유**: Sprint 100~115와 같다 ― `docs/BUGS.md` / `docs/CURRENT_STATE.md`는
> 다른 세션의 편집 대상이라 충돌을 피했다.

Sprint 115에서 `migrate_execute.py` 가 **검증 실패를 성공으로 보고**하는 것을 고쳤다.
그러면 물어야 할 것이 하나 남는다 ― **나머지 진입점은?**

---

## 1. 네 진입점을 전부 봤다

```
mvp_scraper.py       sys.exit(main())            main() -> int    OK
doc_worker.py        sys.exit(main())            main() -> int    OK
migrate_execute.py   sys.exit(0 if execute() else 1)              OK (Sprint 115에서 고침)
refresh_priority.py  main()                      main() -> None   OK ― 아래 참고
```

`refresh_priority.py` 만 `sys.exit()` 없이 `main()` 을 부른다. 처음엔 결함으로 보였는데
**아니었다** ― `main() -> None` 이라 돌려줄 판정 자체가 없고, 실패는 예외로 나가
파이썬이 스스로 exit 1 한다. `run_priority_refresh.bat` 의 `if errorlevel 1` 이 그것을 받는다.

**결함 0건.** 파이프라인의 실패 전달은 Sprint 115의 수정으로 완결돼 있었다.

## 2. ★ 그런데 그것을 지키는 검사가 두 개만 덮고 있었다

`test_crawl_exit_code.py` §5는 진입점을 **손으로 적어** 검사한다.

```python
for name in ("mvp_scraper.py", "doc_worker.py"):
```

배치가 실행하는 스크립트는 **넷**이다. 빠져 있던 `migrate_execute.py` 에서
실제로 결함이 나왔다(Sprint 115 #115-2). 손목록이 짧아 그 결함이 통과했다 ―
Sprint 109의 소프트 삭제 체크리스트와 **같은 실패 모양**이다.

### `test_crawl_exit_code.py` §5-B 신설 ― 목록을 배치에서 읽는다

```
[PASS] 배치가 실행하는 스크립트 목록: ['doc_worker.py', 'migrate_execute.py',
                                      'mvp_scraper.py', 'refresh_priority.py']
[PASS] doc_worker.py:       종료 코드에 런타임 판정이 실린다(상수만 있지 않다)
[PASS] migrate_execute.py:  종료 코드에 런타임 판정이 실린다(상수만 있지 않다)
[PASS] mvp_scraper.py:      종료 코드에 런타임 판정이 실린다(상수만 있지 않다)
[PASS] refresh_priority.py: main()이 여전히 -> None 이다(실패는 예외로만)
```

- 목록은 `.bat` 세 개에서 `"%PY%" X.py` 를 뽑아 만든다 ― 파이프라인이 늘면 자동으로 대상이 된다.
- 그 목록 자체도 고정한다. 새 스크립트가 들어오면 실패해서 **종료 코드 계약을 한 번 보게** 한다.
- `refresh_priority.py` 는 "실패는 예외로만" 형태를 **의도된 예외**로 허용하되,
  `main()` 이 판정을 돌려주기 시작하면 실패하도록 `-> None` 을 함께 고정했다.
  판정을 표현할 방법이 있는데 안 쓰는 것과, 애초에 없는 것은 다르다.

## 3. ★ 처음 만든 검사가 변이를 놓쳤다 (문자열 → AST)

첫 구현은 문자열로 봤다.

```python
check_true("sys.exit(0) 만 있지는 않다",
           not re.search(r"sys\.exit\(\s*0\s*\)", main_block)
           or re.search(r"sys\.exit\(\s*[^0\s)]", main_block) is not None)
```

변이 M91(`migrate_execute` 를 `execute(); sys.exit(0)` 로 되돌림)을 걸었더니
**통과했다.** 이유는 이렇다 ― 예외 분기에 `sys.exit(1)` 이 있어서
"상수만 있지는 않다"가 참이 됐다. 정상 경로는 언제나 0인데도.

**이번엔 내 도구 문제가 아니라 가드의 진짜 구멍이었다.** AST로 바꿨다.

```
[FAIL] migrate_execute.py: 종료 코드에 런타임 판정이 실린다(상수만 있지 않다)
       -- sys.exit 인자가 전부 상수다: ['0', '1']
```

`sys.exit(main())` / `sys.exit(0 if execute() else 1)` 는 통과하고,
`sys.exit(0)` 과 `sys.exit(1)` 뿐이면 실패한다. 판정 기준이
"어딘가에 0이 아닌 게 있는가"에서 **"인자가 런타임 값인가"**로 정확해졌다.

> 변이 검증이 없었다면 이 검사는 **초록불인 채로 아무것도 막지 못했을 것이다.**
> 그리고 Sprint 115에서 고친 바로 그 결함이 되돌아와도 몰랐을 것이다.

## 변이 검증

| | 변이 | 결과 |
|---|---|---|
| M91 | `migrate_execute` 를 `execute(); sys.exit(0)` 로 되돌림 | 문자열 검사 **놓침** → AST 검사 **검출 O** |
| M92 | 배치에 새 스크립트를 추가 | **검출 O** ― 목록에 `some_new_step.py` 가 뜬다 |

두 변이 모두 원복했고(`git status` 에 `.bat` 없음), 스위트는 다시 통과한다.

## 함께 확인한 것 (결함 0건)

- **결제/구독의 이용권 판정**: `get_entitled_subscription()` 과 `get_active_subscription()` 이
  같은 답을 내는지 `test_subscription_policy.py` §9가 **이미** 검사하고 있다(Sprint 72).
  전자는 쓰기 없이 `resolve_expected_status()` 로 만료를 계산한다 ― 설계가 타당하다.
  (결제 3개 테이블은 실 DB에 0행 ― 베타 실결제 없음.)
- **쿼리 계획**: 검색 8종의 실행 계획을 봤다. 전부 인덱스를 탄다.
  유일한 `SCAN` 은 `ORDER BY minimum_bid_price` 의 인덱스 워크로 **정상**이다
  (LIMIT 20에서 조기 종료). 최장 0.81ms.
- **중복 인덱스**: 완전 중복 4건이 있는데 `test_schema_hygiene.py` §6-3이
  "새로 생긴 중복 없음"으로 **이미 고정**하고 있다.

## 검증

| 항목 | 결과 |
|---|---|
| 파이썬 테스트 | **28/28 파일 통과** (실크롤 3개 제외) |
| `python -m compileall` | **exit 0** |
| 프런트 | 무변경 (Sprint 107에서 107/107, TSC/LINT/BUILD exit 0) |
| 실 DB | **한 줄도 쓰지 않았다** |
| 변이 잔여 | `.bat` 3개 무변경, `migrate_execute.py` 원복 확인 |

## 수정 파일

```
test_crawl_exit_code.py    §5-B 신설 (배치에서 유도한 목록 + AST 기반 종료 코드 계약)
```

**제품 코드 변경 0건.**

## 남은 Backlog

- **★★ 수집 파이프라인 스케줄러 등록** ― 2026-08-20에 검색 결과 0건이 된다.
  `register_scheduler_tasks.ps1 -Apply` 한 줄이면 된다(Sprint 112).
- Sprint 105~115의 SKIP 표 항목들 (전부 승인/외부 조치 대기)
