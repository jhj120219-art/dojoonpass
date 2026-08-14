"""크롤 실행의 성패 판정 / 종료 코드 회귀 테스트 (2026-08-11 Sprint 55 신설, BUGS #47).

왜 만들었나 — 2026-08-02 실제 실행 기록:

    [수집 완료 요약]
      총 수집 법원: 60 곳
      기일 없어 스킵: 1 곳
      오류 발생: 59 곳
      총 저장 건수: 0 건
    =====================================
    Finished at 2026-08-02  6:02:49.45      <- 성공으로 끝났다

59곳이 실패하고 한 건도 저장되지 않았는데 배치는 성공을 보고했다.
`mvp_scraper.main()`이 `-> None`이라 종료 코드가 언제나 0이었고, `run_daily.bat`의
`if errorlevel 1` 검사는 **구조적으로 발동할 수 없었다**. Sprint 13이 "실패 은폐 구조"를
없앴다고 기록했지만, 그것은 배치 레벨이었고 그 아래에서 그대로 남아 있었다.

selenium 없이 실행된다 — 판정 로직을 `models/crawl_outcome.py`로 분리한 이유다.

    python test_crawl_exit_code.py
"""
import sys
import os
import re
import io
import ast

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models.crawl_outcome import CrawlOutcome, DocWorkerOutcome

ROOT = os.path.dirname(os.path.abspath(__file__))
failures = []


def check(name, actual, expected):
    ok = actual == expected
    print("[%s] %s: %r (expected %r)" % ("PASS" if ok else "FAIL", name, actual, expected))
    if not ok:
        failures.append(name)


def check_true(name, cond, detail=""):
    print("[%s] %s%s" % ("PASS" if cond else "FAIL", name, ("" if cond else " -- " + str(detail))))
    if not cond:
        failures.append(name)


# ---------------------------------------------------------------------------
def test_the_actual_2026_08_02_run():
    print("\n--- 1. 2026-08-02 실제 실행을 그대로 재현 ---")
    o = CrawlOutcome(courts=60, skipped=["의정부지원"], failed=["법원%d" % i for i in range(59)],
                     collected=0)
    check_true("실패로 판정된다", o.failure_reason() is not None,
               "59/60 실패 + 저장 0건인데 성공으로 판정됨")
    check("종료 코드 1", o.exit_code(), 1)
    # 사유는 **진단**이어야 한다. 수집 자체가 0건인 것과 수집은 됐는데 저장이 0건인 것은
    # 손봐야 할 곳이 완전히 다르다(크롤러 vs 저장 계층). 둘 다 "0건"이라 뭉뚱그리면
    # 로그를 봐도 어디를 봐야 할지 알 수 없다.
    check_true("사유가 '수집' 실패임을 특정한다", "수집 건수 0건" in (o.failure_reason() or ""),
               o.failure_reason())
    check_true("저장 실패로 오진하지 않는다", "저장" not in (o.failure_reason() or ""),
               o.failure_reason())


def test_success_cases():
    print("\n--- 2. 성공으로 둬야 하는 경우 ---")
    o = CrawlOutcome(courts=60, collected=1200, inserted=300, updated=900)
    check("정상 실행은 0", o.exit_code(), 0)
    check("사유 없음", o.failure_reason(), None)

    # 부분 실패는 성공으로 둔다. 임계값을 임의로 정하면 그 자체가 새 정책이 되고,
    # 멀쩡한 실행이 매일 실패로 보고되면 경보가 무시당한다.
    o = CrawlOutcome(courts=60, failed=["법원%d" % i for i in range(30)],
                     collected=500, inserted=100, updated=400)
    check("절반이 실패해도 저장이 있으면 0", o.exit_code(), 0)

    # 갱신만 있고 신규가 없는 날도 정상이다(같은 물건이 계속 조회되는 경우).
    o = CrawlOutcome(courts=60, collected=800, inserted=0, updated=800)
    check("신규 0 / 갱신 800은 정상", o.exit_code(), 0)


def test_failure_cases():
    print("\n--- 3. 실패로 잡아야 하는 경우 ---")
    o = CrawlOutcome(courts=60, failed=["법원%d" % i for i in range(60)], collected=0)
    check("전 법원 실패", o.exit_code(), 1)
    check_true("사유가 전 법원 실패임을 밝힌다", "전 법원" in o.failure_reason(), o.failure_reason())

    # 수집은 됐는데 DB에 한 건도 안 남은 경우 — 저장 계층이 통째로 깨진 상황.
    o = CrawlOutcome(courts=60, collected=1200, inserted=0, updated=0, upsert_failed=1200)
    check("수집 1200 / 저장 0", o.exit_code(), 1)
    check_true("사유가 저장 실패임을 밝힌다", "저장" in o.failure_reason(), o.failure_reason())

    # 오류가 하나도 없는데 수집이 0건인 경우도 실패다.
    # (사이트 구조가 바뀌어 파싱이 조용히 빈 목록을 돌려주는 상황 — 예외가 안 난다)
    o = CrawlOutcome(courts=60, skipped=["법원%d" % i for i in range(60)], collected=0)
    check("예외 없이 전부 스킵돼 0건이어도 실패", o.exit_code(), 1)


def test_persisted_arithmetic():
    print("\n--- 4. persisted 계산 ---")
    check("신규+갱신", CrawlOutcome(inserted=7, updated=5).persisted, 12)
    check("둘 다 0", CrawlOutcome().persisted, 0)


def test_doc_worker_outcome():
    print("\n--- 4-B. PDF 수집 Worker 성패 판정 ---")
    # 큐가 비어 할 일이 없던 날. 매일 도는 워커이므로 흔하고, 실패가 아니다.
    check("큐가 비면 성공(0)", DocWorkerOutcome(processed=0, succeeded=0).exit_code(), 0)
    check("아무것도 안 했으면 사유 없음", DocWorkerOutcome().failure_reason(), None)

    # 시도했는데 전건 실패 — 드라이버/사이트/선택자가 통째로 깨진 신호.
    o = DocWorkerOutcome(processed=120, succeeded=0)
    check("120건 시도 / 성공 0 -> 실패(1)", o.exit_code(), 1)
    check_true("사유에 시도 건수가 남는다", "120" in (o.failure_reason() or ""), o.failure_reason())

    # 한 건이라도 성공하면 부분 실패로 보고 넘어간다(크롤 쪽과 같은 원칙).
    check("1건이라도 성공하면 0", DocWorkerOutcome(processed=120, succeeded=1).exit_code(), 0)


# ---------------------------------------------------------------------------
def test_entrypoints_propagate_exit_code():
    """진입점이 종료 코드를 실제로 전달하는가 (소스 계약).

    selenium 미설치로 import할 수 없으므로 소스를 읽어 확인한다. 약한 검사처럼 보이지만,
    이 결함의 본질이 정확히 "`main()`의 반환값이 프로세스 종료 코드로 이어지지 않는 것"이라
    바로 그 연결을 고정하는 것이 맞다.
    """
    print("\n--- 5. 진입점이 종료 코드를 전달하는가 ---")
    for name in ("mvp_scraper.py", "doc_worker.py"):
        src = io.open(os.path.join(ROOT, name), encoding="utf-8-sig").read()
        check_true("%s: sys.exit(main()) 형태" % name,
                   re.search(r"sys\.exit\(\s*main\(\)\s*\)", src) is not None,
                   "main()의 반환값이 종료 코드로 이어지지 않습니다")
        check_true("%s: main()이 int를 돌려준다" % name,
                   re.search(r"def main\(\)\s*->\s*int", src) is not None,
                   "main()이 -> None이면 실패를 표현할 방법이 없습니다")
        # 배선이 형태만 맞고 값이 상수면 아무 소용이 없다 — `return 0`으로 굳어 있으면
        # sys.exit(main())가 있어도 실패를 절대 알리지 못한다.
        check_true("%s: 판정 결과를 반환한다(상수 반환 아님)" % name,
                   "exit_code()" in src,
                   "main()이 Outcome의 판정을 쓰지 않고 상수를 돌려줍니다")


def _is_main_guard(node) -> bool:
    """`if __name__ == "__main__":` 인가."""
    test = node.test
    return (isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name) and test.left.id == "__name__"
            and len(test.comparators) == 1
            and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value == "__main__")


def test_every_scheduled_script_propagates_failure():
    """배치가 실행하는 **모든** 스크립트가 실패를 종료 코드로 알리는가 (2026-08-14 신설).

    위 §5는 `mvp_scraper.py` / `doc_worker.py` **두 개를 손으로 적어** 검사한다.
    그런데 배치가 실행하는 스크립트는 넷이고, 빠져 있던 `migrate_execute.py` 에서
    실제로 결함이 나왔다 — `[FAIL] document_status 불일치` 를 찍고도 `sys.exit(0)` 이라
    `run_daily.bat` 이 같은 로그 파일에 `[SUCCESS]` 를 남겼다(2026-08-14 Sprint 115).

    손으로 적은 목록은 파이프라인이 늘면 어긋난다. 그래서 **배치에서 목록을 읽는다** —
    새 스크립트가 파이프라인에 들어오면 자동으로 검사 대상이 된다.

    허용되는 형태는 둘이다.

        (a) `sys.exit(...)` 로 판정을 종료 코드에 싣는다
        (b) `main() -> None` 이고 실패는 예외로 나간다
            -> 파이썬이 스스로 exit 1 한다. `refresh_priority.py` 가 이 형태다.

    (b)를 허용하되 **의도한 것만** 허용한다 — 목록을 고정해 두고, 새 스크립트가
    말없이 (b)로 들어오면 실패시킨다. 실패를 표현할 방법이 있는데 안 쓰는 것과
    애초에 없는 것은 다르다.
    """
    print("\n--- 5-B. 배치가 실행하는 모든 스크립트의 실패 전달 ---")
    scripts = set()
    for name in ("run_daily.bat", "run_doc_worker.bat", "run_priority_refresh.bat"):
        src = io.open(os.path.join(ROOT, name), encoding="utf-8-sig").read()
        for ln in src.splitlines():
            if ln.strip().upper().startswith("REM"):
                continue
            m = re.match(r'^\s*"%PY%"\s+(\S+\.py)', ln)
            if m:
                scripts.add(m.group(1))

    # 파이프라인 구성이 바뀌면 알린다 — 새 스크립트의 종료 코드 계약을 사람이 한 번 보게 한다.
    EXPECTED = {"mvp_scraper.py", "migrate_execute.py", "doc_worker.py", "refresh_priority.py"}
    check("배치가 실행하는 스크립트 목록", sorted(scripts), sorted(EXPECTED))

    # 실패를 예외로만 알리는 것이 의도된 스크립트(위 (b)).
    RAISES_ONLY = {"refresh_priority.py"}

    for name in sorted(scripts):
        path = os.path.join(ROOT, name)
        if not os.path.exists(path):
            check_true("%s: 파일이 존재한다" % name, False, path)
            continue
        src = io.open(path, encoding="utf-8-sig").read()
        idx = src.find('if __name__ == "__main__":')
        check_true("%s: __main__ 진입점이 있다" % name, idx >= 0)
        if idx < 0:
            continue
        main_block = src[idx:]
        has_exit = "sys.exit(" in main_block
        if name in RAISES_ONLY:
            # 형태가 바뀌어 판정을 갖게 되면 그때는 종료 코드에 실어야 한다.
            check_true("%s: main()이 여전히 -> None 이다(실패는 예외로만)" % name,
                       re.search(r"def main\(\)\s*->\s*None", src) is not None,
                       "판정을 돌려주기 시작했다면 sys.exit()로 실어야 한다")
        else:
            check_true("%s: __main__ 이 sys.exit(...) 로 결과를 싣는다" % name,
                       has_exit,
                       "판정이 종료 코드로 이어지지 않으면 배치가 [SUCCESS]를 남긴다")
            # ★ 문자열로 보면 뚫린다. 예외 분기의 `sys.exit(1)` 하나만 있어도
            #   "상수만 있지는 않다"가 참이 되기 때문이다 — 처음 만든 검사가 정확히
            #   그렇게 통과했고, `execute(); sys.exit(0)` 변이를 놓쳤다.
            #
            #   판정 기준은 **정상 경로의 인자가 런타임 값인가** 다. AST로 본다.
            #   `sys.exit(main())` / `sys.exit(0 if execute() else 1)` 는 통과하고,
            #   `sys.exit(0)` 과 `sys.exit(1)` 뿐이면 실패한다.
            exits = []
            for node in ast.walk(ast.parse(src)):
                if not (isinstance(node, ast.If) and _is_main_guard(node)):
                    continue
                for sub in ast.walk(node):
                    if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                            and sub.func.attr == "exit" and sub.args):
                        exits.append(sub.args[0])
            check_true("%s: 종료 코드에 런타임 판정이 실린다(상수만 있지 않다)" % name,
                       any(not isinstance(a, ast.Constant) for a in exits),
                       "sys.exit 인자가 전부 상수다: %s"
                       % [ast.unparse(a) for a in exits])


def test_batches_check_errorlevel():
    """배치 3종이 errorlevel을 검사하고 성공/실패를 기록하는가.

    `run_daily.bat`에만 있던 구조다. 나머지 둘은 스크립트를 실행하고 그냥 끝나서,
    로그만 봐서는 "할 일이 없었다"와 "아예 실행되지 않았다"를 구분할 수 없었다.
    """
    print("\n--- 6. 배치가 실패를 감지하고 기록하는가 ---")
    for name in ("run_daily.bat", "run_doc_worker.bat", "run_priority_refresh.bat"):
        src = io.open(os.path.join(ROOT, name), encoding="utf-8-sig").read()
        body = "\n".join(ln for ln in src.splitlines() if not ln.strip().upper().startswith("REM"))

        lines = body.splitlines()

        # 실행되는 python 스크립트마다 errorlevel 검사가 붙어 있어야 한다.
        runs = [i for i, ln in enumerate(lines) if re.match(r'^\s*"%PY%"\s+\S+\.py', ln)]
        check_true("%s: 실행되는 스크립트가 있다" % name, len(runs) > 0, body[:200])
        for i in runs:
            script = lines[i].split()[1]
            nxt = next((lines[j] for j in range(i + 1, len(lines)) if lines[j].strip()), "")
            check_true("%s: %s 뒤에 errorlevel 검사" % (name, script),
                       nxt.strip().startswith("if errorlevel 1"),
                       "실패해도 성공으로 끝납니다 -> %r" % nxt.strip()[:60])

        # 각 실패 분기가 **자기 블록 안에서** [FAILED]를 남기는가.
        # 파일 어딘가에 [FAILED]가 한 번이라도 있으면 통과시키면, 분기 하나에서
        # 마커가 사라져도 검출되지 않는다(실제로 그렇게 빠져나간 변이가 있었다).
        depth = 0
        block_start = None
        for idx, ln in enumerate(lines):
            stripped = ln.strip()
            if depth == 0 and re.match(r"^if\s+(errorlevel\s+1|not defined PY)\s*\($", stripped):
                depth, block_start = 1, idx
                has_failed = False
                continue
            if depth:
                if "[FAILED]" in ln:
                    has_failed = True
                depth += ln.count("(") - ln.count(")")
                if depth <= 0:
                    label = lines[block_start].strip()[:34]
                    check_true("%s: 실패 분기 '%s' 가 [FAILED]를 남긴다" % (name, label),
                               has_failed, "이 분기는 조용히 exit합니다")
                    depth, block_start = 0, None

        check_true("%s: [SUCCESS] 기록" % name,
                   "[SUCCESS]" in body,
                   "성공 마커가 없으면 '실행되지 않음'과 '정상 종료'를 구분할 수 없습니다")
        # 인터프리터 해석 실패도 반드시 기록돼야 한다(Sprint 54).
        check_true("%s: 인터프리터 미탐색 시 exit 1" % name,
                   "if not defined PY" in body and "exit /b 1" in body,
                   "인터프리터가 없으면 조용히 끝납니다")


def test_live_crawl_scripts_are_guarded():
    """실제 사이트에 접속하는 스크립트가 회귀 스윕에서 그냥 실행되지 않는가.

    2026-08-11 Sprint 55 (BUGS #51). `test_db.py` / `test_docs.py` / `test_docs2.py`는
    이름이 test_*.py지만 assert가 하나도 없고 실제 `courtauction.go.kr`에 접속한다.
    "회귀 대상 아님"이라고 문서 6곳에 적혀 있었지만 **아무것도 막지 못했다** —
    실제로 이 저장소에서 `test_*.py` 전수 실행이 두 번 돌았고, selenium이 없어서
    우연히 접속이 일어나지 않았을 뿐이다. 규약이 아니라 구조로 막혀야 한다.
    """
    print("\n--- 7. 실제 접속 스크립트가 구조적으로 막혀 있는가 ---")
    for name in ("test_db.py", "test_docs.py", "test_docs2.py"):
        path = os.path.join(ROOT, name)
        if not os.path.exists(path):
            check_true("%s 존재" % name, False, "가드 대상 파일이 사라졌습니다")
            continue
        src = io.open(path, encoding="utf-8-sig").read()
        check_true("%s: 명시 허용 없이는 실행되지 않는다" % name,
                   "ALLOW_LIVE_CRAWL" in src,
                   "회귀 스윕이 실제 법원 사이트를 크롤합니다")

        # 가드가 무거운 import보다 **앞**에 있어야 selenium 없이도 깔끔히 끝난다.
        gi = src.find("ALLOW_LIVE_CRAWL")
        si = src.find("from selenium")
        check_true("%s: 가드가 selenium import보다 앞" % name,
                   si == -1 or gi < si,
                   "import 단계에서 먼저 죽어 가드가 무의미해집니다")

        # 진짜 회귀 테스트에는 이 가드가 있으면 안 된다(있으면 조용히 안 돌게 된다).
    for name in ("test_api_regression.py", "test_crawl_exit_code.py", "test_document_queue.py"):
        src = io.open(os.path.join(ROOT, name), encoding="utf-8-sig").read()
        check_true("%s: 회귀 테스트에는 가드가 없다" % name,
                   "ALLOW_LIVE_CRAWL" not in src or name == "test_crawl_exit_code.py",
                   "회귀가 조용히 건너뛰어집니다")


def test_batch_candidates_are_non_interactive():
    """배치가 부를 수 있는 스크립트에 사람 입력 대기가 없는가 (2026-08-12 Sprint 63 신설).

    `docs/crawler.md` / `docs/roadmap.md`가 "어떤 배치도 실행하지 않는 것"으로 네 스크립트를
    묶어 놓고 배치 편입을 Backlog로 두고 있었는데, 그중 `analyze_docs.py`는 **애초에 배치에
    넣으면 안 되는 스크립트**다 — DB에 아무것도 쓰지 않고(관련 코드 0줄), 마지막에
    `input("엔터를 누르면 종료...")`로 사람 입력을 기다린다.

    Task Scheduler에서 이것이 실행되면 stdin이 없어 **영원히 매달리거나 즉시 죽고**,
    같은 배치의 뒷 단계가 통째로 멈춘다. 문서의 분류만 믿고 배치에 넣는 순간 사고가 난다.
    규약이 아니라 구조로 막는다.
    """
    print("\n--- 8. 배치 후보 스크립트에 입력 대기가 없는가 ---")
    import re as _re

    # 실제로 배치가 부르거나, 문서가 배치 편입 후보로 거론하는 스크립트 전부.
    candidates = (
        "mvp_scraper.py", "doc_worker.py", "migrate_execute.py", "refresh_priority.py",
        "collect_documents.py", "load_rights_data.py", "load_spec_data.py",
        "repair_document_status.py", "repair_empty_status_capture.py",
    )
    # 주석/문자열 안의 input( 은 세지 않도록 줄 단위로 코드만 본다.
    call = _re.compile(r"(?<![\w.])input\s*\(")
    for name in candidates:
        path = os.path.join(ROOT, name)
        if not os.path.exists(path):
            check_true("%s 존재" % name, False, "배치 후보 파일이 사라졌습니다")
            continue
        hits = [i + 1 for i, line in enumerate(io.open(path, encoding="utf-8-sig"))
                if call.search(line.split("#")[0])]
        check("%s: 사람 입력 대기 없음" % name, hits, [])

    # 반대로 `analyze_docs.py`는 **대화형 조사 스크립트**임이 분명해야 한다.
    # 여기가 조용히 바뀌면(=input이 사라지면) 위 목록에 넣어야 한다는 신호다.
    ad = os.path.join(ROOT, "analyze_docs.py")
    if os.path.exists(ad):
        src = io.open(ad, encoding="utf-8-sig").read()
        check_true("analyze_docs.py는 대화형이라 배치 후보가 아니다",
                   bool(call.search(src)),
                   "입력 대기가 사라졌다면 배치 후보 목록과 문서를 함께 갱신하십시오")
        # DB에 아무것도 쓰지 않는다 = 파이프라인 단계가 아니다(문서가 그렇게 적고 있었다).
        # 주의: 단순히 "INSERT" 문자열을 찾으면 `sys.path.insert(...)`가 걸린다 —
        # 실제로 이 검사를 처음 썼을 때 그렇게 오검출됐다. SQL 형태로만 판정한다.
        sql_write = _re.search(r"\b(INSERT\s+(OR\s+\w+\s+)?INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM)\b",
                               src, _re.IGNORECASE)
        check_true("analyze_docs.py는 DB를 쓰지 않는다(파이프라인 단계 아님)",
                   "get_connection" not in src and sql_write is None,
                   "DB를 쓰기 시작했다면 파이프라인 문서를 갱신하십시오")


def run():
    test_the_actual_2026_08_02_run()
    test_success_cases()
    test_failure_cases()
    test_persisted_arithmetic()
    test_doc_worker_outcome()
    test_entrypoints_propagate_exit_code()
    test_every_scheduled_script_propagates_failure()
    test_batches_check_errorlevel()
    test_live_crawl_scripts_are_guarded()
    test_batch_candidates_are_non_interactive()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
