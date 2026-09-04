"""회귀 **실행기 자신**의 계약 (2026-08-19 Sprint 217 신설).

## 왜 이 파일이 있나

`run_python_tests.py` 는 이 저장소의 모든 파이썬 회귀 결과를 **집계**한다.
그런데 그 집계 로직에는 검사가 하나도 없었다 — 44개 파일을 검사하는 도구가
정작 자기는 아무도 검사하지 않는 상태였다.

그 자리가 위험한 이유는 **고장 나는 방향**이다. 판정이 망가지면 결과는
빨간색이 아니라 **초록색**으로 기운다:

    종료코드 검사가 사라진다      -> 실패한 파일이 PASSED 로 집계된다
    판정문 정규식이 넓어진다      -> 단언 없는 스크립트가 PASSED 가 된다
    SKIP 판정이 넓어진다          -> 실행되지 않은 것이 통과로 보인다
    discover() 가 좁아진다        -> 새 테스트가 조용히 실행되지 않는다

전부 "44 통과 / 0 실패"라는 **정상과 똑같은 화면**으로 나온다. 이 실행기가
애초에 만들어진 이유가 그 착각(즉석 셸 반복문이 결과를 두 번 잘못 읽음)이고,
그 착각을 실행기 자신이 되풀이하지 않는지 여기서 본다.

## 무엇을 고정하나

    1. 종료코드가 1순위다 — 출력이 아무리 "통과"라고 말해도 non-zero 면 FAILED
    2. 종료코드 0 이어도 판정문이 없으면 PASSED 가 아니다(NO-VERDICT)
    3. SKIPPED / NO-VERDICT 는 통과가 아니다(요약에서 따로 세고 이름을 남긴다)
    4. discover() 는 새로 생긴 루트 test_*.py 를 실제로 찾는다
    5. 하위 디렉터리에 test_*.py 가 생기면 **못 찾는다**는 사실을 기록한다
       (현재 0개다. 사실을 고정해 두면 생기는 날 이 검사가 먼저 말한다)

    python test_runner_contract.py
"""
import io
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.dirname(os.path.abspath(__file__))

import run_python_tests as R

failures = []


def emit(line):
    """콘솔 코드페이지가 cp949 여도 죽지 않게 찍는다.

    `run_python_tests.emit()` 과 같은 이유다 — 여기서 죽으면 **실패한 이유를
    보여 주지 못한다.** 실제로 이 파일을 처음 돌렸을 때 그렇게 죽었다:
    실행기 출력에 섞인 대체문자(U+FFFD)를 그대로 찍으려다 UnicodeEncodeError 가 났고,
    정작 어떤 단언이 깨졌는지는 화면에 나오지 않았다.
    """
    try:
        print(line)
    except UnicodeEncodeError:
        enc = sys.stdout.encoding or "utf-8"
        print(line.encode(enc, "replace").decode(enc, "replace"))


def check(name, actual, expected):
    ok = actual == expected
    emit("[%s] %s: %r (expected %r)" % ("PASS" if ok else "FAIL", name, actual, expected))
    if not ok:
        failures.append(name)


def check_true(name, cond, detail=""):
    emit("[%s] %s%s" % ("PASS" if cond else "FAIL", name,
                        "" if cond else " -- " + str(detail)))
    if not cond:
        failures.append(name)


# ---------------------------------------------------------------------------
# 1. 종료코드가 1순위다
# ---------------------------------------------------------------------------
def test_exit_code_beats_wording():
    """출력이 무엇이라고 말하든 **종료코드가 이긴다.**

    이 저장소는 결과 어휘가 세 벌이고(`[PASS]`/`[OK]`/문장만), 게다가
    `test_auction_identity.py` 는 **통과할 때도 `[FAIL]` 을 찍는다**
    (검증을 일부러 깨뜨려 대상이 실패를 보고하는지 확인하므로).
    그래서 문구로 판정하면 통과한 테스트를 실패로 읽는다 — 그 반대도 마찬가지다.
    """
    print("\n--- 1. 종료코드가 판정의 1순위인가 ---")

    loud_pass = "[PASS] 전부 좋음\nALL TESTS PASSED\n"
    st, n = R.classify(1, loud_pass)
    check("★ 출력이 '전부 통과'여도 종료코드 1이면 FAILED", st, "FAILED")
    check("그래도 단언 수는 센다", n, 1)

    st, _ = R.classify(0, loud_pass)
    check("종료코드 0 + 판정문 -> PASSED", st, "PASSED")

    st, _ = R.classify(None, loud_pass)
    check("종료코드 None(시간초과) -> TIMEOUT", st, "TIMEOUT")

    # 통과하면서 [FAIL] 을 찍는 실제 파일의 모양
    mixed = "[FAIL] document_status 불일치 (의도된 출력)\n[PASS] 검증기가 실패를 보고한다\n"
    st, n = R.classify(0, mixed)
    check("[FAIL] 문구가 있어도 종료코드 0이면 PASSED", st, "PASSED")
    check("단언 수는 PASS+FAIL 을 합친다", n, 2)


# ---------------------------------------------------------------------------
# 2. 판정문이 없으면 통과가 아니다
# ---------------------------------------------------------------------------
def test_no_verdict_is_not_a_pass():
    print("\n--- 2. 판정문 없음 / 건너뜀은 통과가 아니다 ---")

    silent = "filter_auctions() 결과:\n  물건 3건\n"
    st, n = R.classify(0, silent)
    check("★ 단언이 하나도 없으면 NO-VERDICT", st, "NO-VERDICT")
    check("단언 수 0", n, 0)

    skipped = "[SKIPPED] ALLOW_LIVE_CRAWL=1 이 없어 실크롤을 건너뜁니다\n"
    st, n = R.classify(0, skipped)
    check("★ 스스로 건너뛴 파일은 SKIPPED", st, "SKIPPED")

    # 건너뜀 표시가 있어도 **단언이 있으면** 건너뛴 것이 아니다.
    both = "[SKIPPED] 일부 단계 생략\n[PASS] 나머지는 검증했다\n"
    st, n = R.classify(0, both)
    check("일부만 건너뛴 파일은 SKIPPED 가 아니다(단언이 있다)", st, "PASSED")
    check("그 파일의 단언도 집계된다", n, 1)


# ---------------------------------------------------------------------------
# 3. 요약 집계에서 통과와 비통과가 섞이지 않는다 (실제 실행)
# ---------------------------------------------------------------------------
def _run_runner(pattern):
    """실행기를 하위 프로세스로 돌리고 (종료코드, 출력) 을 돌려준다.

    ★ `PYTHONIOENCODING=utf-8` 을 **반드시 준다.** 파이프로 받으면 파이썬이
      로캘 인코딩(이 환경에서는 cp949)으로 인코딩하는데, 그것을 utf-8 로 읽으면
      한글이 전부 깨진다. 그 상태에서 요약 문구를 찾으면 **항상 못 찾는다** —
      실제로 이 검사를 처음 돌렸을 때 그렇게 실패했고, 원인은 실행기가 아니라
      이 검사의 디코딩이었다. 인코딩을 못 박으면 콘솔 코드페이지와 무관해진다.
    """
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run([sys.executable, "run_python_tests.py", "-k", pattern],
                       cwd=ROOT, capture_output=True, timeout=300, env=env)
    return p.returncode, (p.stdout + p.stderr).decode("utf-8", "replace")


def test_summary_separates_pass_from_not_run():
    """실행기를 **실제로 돌려** 세 상태가 섞이지 않는지 본다.

    가짜 테스트 파일 3개를 루트에 잠깐 만든다 — 루트여야 `discover()` 가 찾는다.
    이름에 공통 접두어를 두어 `-k` 로 이 셋만 돌린다(전체 스위트를 다시 돌리지 않는다).
    """
    print("\n--- 3. 실행기를 실제로 돌린 집계 (가짜 테스트 3개) ---")

    files = {
        "test_zzprobe_pass.py": "print('[PASS] 가짜 통과')\n",
        "test_zzprobe_fail.py": "print('[PASS] 하나는 통과')\nimport sys; sys.exit(1)\n",
        "test_zzprobe_quiet.py": "print('아무것도 판정하지 않는다')\n",
    }
    made = []
    try:
        for name, body in files.items():
            path = os.path.join(ROOT, name)
            with io.open(path, "w", encoding="utf-8") as fh:
                fh.write(body)
            made.append(path)

        rc, out = _run_runner("zzprobe")

        check("★ 하나라도 실패하면 실행기 종료코드는 1", rc, 1)
        check_true("통과 1 / 실패 1 / 판정없음 1 로 집계된다",
                   "통과 1 | 실패 1" in out and "판정없음 1" in out, out[-400:])
        check_true("실패한 파일 이름을 남긴다", "test_zzprobe_fail.py" in out, out[-400:])
        check_true("판정없음 파일 이름을 남긴다", "test_zzprobe_quiet.py" in out, out[-400:])
        # 실패는 -v 없이도 증거를 남긴다 (Sprint 203 규칙)
        check_true("실패한 파일의 마지막 줄을 그 자리에서 보여 준다",
                   "종료코드 1" in out, out[-600:])
    finally:
        for path in made:
            try:
                os.remove(path)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# 4. discover() 가 새 파일을 실제로 찾는가 / 어디를 못 보는가
# ---------------------------------------------------------------------------
def test_discover_finds_new_files_and_admits_its_blind_spot():
    print("\n--- 4. discover() 의 범위 ---")

    base = set(R.discover())
    check_true("현재 루트 test_*.py 를 실제로 찾는다(검사가 공허하지 않다)",
               len(base) >= 30, len(base))

    probe = os.path.join(ROOT, "test_zzdiscover_probe.py")
    with io.open(probe, "w", encoding="utf-8") as fh:
        fh.write("print('[PASS] probe')\n")
    try:
        found = set(R.discover())
        check("★ 새로 생긴 루트 test_*.py 를 곧바로 찾는다",
              sorted(found - base), ["test_zzdiscover_probe.py"])
        check("-k 필터가 이름으로 좁힌다",
              R.discover("zzdiscover"), ["test_zzdiscover_probe.py"])
    finally:
        try:
            os.remove(probe)
        except OSError:
            pass

    # ★ 못 보는 곳을 **사실로 고정한다.**
    #   `discover()` 는 루트만 훑는다(`os.listdir(ROOT)`). 하위 디렉터리에
    #   test_*.py 가 생기면 조용히 실행되지 않는다 — 지금은 0개라 문제가 아니지만,
    #   생기는 날 "왜 안 돌았는지"를 아무도 모르는 상태가 되면 안 된다.
    nested = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames
                       if d not in ("node_modules", ".git", ".next", "__pycache__",
                                    ".claude", "documents", "logs")]
        if os.path.abspath(dirpath) == os.path.abspath(ROOT):
            continue
        for fn in filenames:
            if fn.startswith("test_") and fn.endswith(".py"):
                nested.append(os.path.relpath(os.path.join(dirpath, fn), ROOT))
    check("하위 디렉터리의 test_*.py (실행기가 못 보는 자리)", sorted(nested), [])


# ---------------------------------------------------------------------------
# 5. 판정문 어휘가 실제 파일들과 맞는가
# ---------------------------------------------------------------------------
def test_verdict_vocabulary_matches_reality():
    """실행기가 아는 판정 어휘가 **실제 테스트 파일의 출력**을 덮는가.

    어휘가 좁아지면 멀쩡한 테스트가 NO-VERDICT 로 떨어지고, 넓어지면
    단언 없는 스크립트가 PASSED 로 올라온다. 둘 다 조용하다.
    """
    print("\n--- 5. 판정 어휘가 실제 출력과 맞는가 ---")

    samples = {
        "[PASS] x": "PASSED",
        "[OK] x": "PASSED",
        "ALL TESTS PASSED": "PASSED",
        "ALL ASSET PIPELINE TESTS PASSED": "PASSED",
        "결과: 12 PASS": "PASSED",
        "FAILED (1): 무언가": "PASSED",   # 종료코드 0 이면 판정은 했다는 뜻
    }
    for out, want in samples.items():
        st, _ = R.classify(0, out + "\n")
        check("어휘 %r" % out[:28], st, want)

    # SKIP 마커는 두 가지뿐이고, 그 둘이 실제 파일에 있는가
    live = [f for f in R.discover() if f in ("test_db.py", "test_docs.py", "test_docs2.py")]
    check_true("실크롤 스크립트 3개가 여전히 존재한다", len(live) == 3, live)
    for f in live:
        with io.open(os.path.join(ROOT, f), encoding="utf-8-sig") as fh:
            body = fh.read()
        check_true("%s 에 SKIP 신호가 있다" % f,
                   any(m in body for m in R.SKIP_MARKERS), f)


# ---------------------------------------------------------------------------
# 테스트 **대역**이 실물 시그니처를 따라가는가 (2026-09-04 신설)
# ---------------------------------------------------------------------------
def test_doubles_accept_what_the_real_function_accepts():
    """`_patch_all({...})` 로 갈아끼우는 대역이 실물만큼 인자를 받는가.

    ## 왜 필요한가 — 규칙은 이미 적혀 있는데 지키는 것이 없었다

    `test_doc_worker_recovery.py` 가 그 규칙을 문장으로 적어 두고 있다:

        `claim_token` 은 2026-08-24 Sprint 254(BUGS #181)에 붙었다. 대역도 실물과 같은
        모양이어야 한다 — 고정 인자 2개로 두면 워커가 토큰을 넘기기 시작한 날 대역만
        터져서, **제품 결함이 아닌 것을 결함처럼 보이게** 만든다.

    적어 두기만 했지 **아무도 확인하지 않았다.** 실제로 두 번 어긋났다:

        2026-09-04  `release_queue_rows()` 에 `claim_tokens` 를 더하자 대역 6개가
                    `lambda ids: 0` 이라 전부 TypeError — 제품은 멀쩡한데 스위트가 붉었다.
        2026-09-04  `claim_next_item_rows(max_rows=8)` 의 대역 5개가 `lambda: []` 였다.
                    지금은 호출부가 인자를 안 넘겨 우연히 통과할 뿐이다.

    ## 방향이 중요하다 — "실물만큼 받는가"만 본다

    대역이 실물보다 **더 받는 것**은 막지 않는다(해가 없다). 막는 것은 **덜 받는
    것**뿐이다 — 그것이 위 두 사고의 모양이다. `*args` 대역도 통과시킨다.

    ★ 이 검사가 잡는 것은 제품 결함이 아니라 **검사 도구의 결함**이다. 그래서
      실행기 계약을 다루는 이 파일에 둔다(`run_python_tests.py` 자신을 검사하는 것과
      같은 취지 — 도구가 조용히 거짓말하는 자리를 막는다).
    """
    import ast
    import inspect
    import subprocess as _sp

    print("\n--- 테스트 대역이 실물 시그니처를 따라가는가 ---")
    root = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, root)
    import storage.database as db

    real = {}
    for name, fn in vars(db).items():
        if (callable(fn) and getattr(fn, "__module__", "") == "storage.database"
                and not name.startswith("_")):
            try:
                real[name] = inspect.signature(fn)
            except (ValueError, TypeError):
                continue
    check_true("실물 함수를 실제로 모았다 (%d개)" % len(real), len(real) >= 15)

    def max_positional(sig):
        """받을 수 있는 위치 인자 최대 개수. `*args` 면 None(무제한)."""
        hi = 0
        for p in sig.parameters.values():
            if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD):
                hi += 1
            elif p.kind == p.VAR_POSITIONAL:
                return None
        return hi

    try:
        out = _sp.run(["git", "ls-files", "test_*.py"], cwd=root,
                      capture_output=True, text=True, timeout=30)
        files = ([f for f in out.stdout.split()
                  if f.endswith(".py") and "-DESKTOP-" not in f]
                 if out.returncode == 0 else [])
    except (OSError, _sp.SubprocessError):
        files = []
    # ★ git 이 없으면 **조용히 돌아가지 않는다** (2026-09-04 변이 M19).
    #
    #   처음에는 여기서 `print("[SKIP]"); return` 했다. 그런데 그러면 파일 열거가
    #   어떤 이유로든 비는 순간 이 검사는 **아무 말 없이 초록**이 된다 - 이 파일이
    #   막으려는 바로 그 모양이다("판정이 망가지면 결과는 빨간색이 아니라 초록색으로
    #   기운다"). 변이 검증에서 실제로 살아남았다.
    #
    #   그래서 디렉터리 열거로 되돌아간다. 저장소 안에서는 어느 쪽이든 비지 않고,
    #   정말로 비면 아래 하한이 붉게 잡는다.
    if len(files) < 20:
        files = sorted(n for n in os.listdir(root)
                       if n.startswith("test_") and n.endswith(".py")
                       and "-DESKTOP-" not in n)
    check_true("훑을 검사 파일을 실제로 찾았다 (%d개)" % len(files), len(files) >= 20)

    offenders = []
    checked = 0
    for rel in files:
        path = os.path.join(root, rel.replace("/", os.sep))
        try:
            tree = ast.parse(io.open(path, encoding="utf-8-sig").read())
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for key, val in zip(node.keys, node.values):
                if not (isinstance(key, ast.Constant)
                        and isinstance(key.value, str)):
                    continue
                if key.value not in real or not isinstance(val, ast.Lambda):
                    continue
                checked += 1
                if val.args.vararg:
                    continue                      # `*a` 대역은 무엇이든 받는다
                double_max = len(val.args.args)
                need = max_positional(real[key.value])
                if need is not None and double_max < need:
                    offenders.append(
                        "%s:%d  %s  대역 %d개 < 실물 %d개  %s"
                        % (rel, val.lineno, key.value, double_max, need,
                           real[key.value]))

    # 하한 - dict 대역을 한 개도 못 찾았으면 이 검사는 공허하다.
    check_true("대역을 실제로 찾았다 (%d개)" % checked, checked >= 20)
    if offenders:
        print("   ★ 실물보다 인자를 적게 받는 대역:")
        for o in sorted(set(offenders)):
            print("      %s" % o)
        print("   제품이 그 인자를 넘기기 시작하면 대역만 터진다 - 실물과 같은 모양으로 두라")
    check("실물보다 좁은 대역이 없다", sorted(set(offenders)), [])

    # 탐지기 자기 증명 - 합성 입력에서 반드시 잡혀야 한다.
    probe = ast.parse("d = {'release_queue_rows': lambda ids: 0}")
    found = []
    for node in ast.walk(probe):
        if isinstance(node, ast.Dict):
            for key, val in zip(node.keys, node.values):
                if (isinstance(key, ast.Constant) and key.value in real
                        and isinstance(val, ast.Lambda) and not val.args.vararg):
                    need = max_positional(real[key.value])
                    if need is not None and len(val.args.args) < need:
                        found.append(key.value)
    check_true("탐지기가 좁은 대역을 실제로 잡는다(자기 증명)",
               found == ["release_queue_rows"])


if __name__ == "__main__":
    test_exit_code_beats_wording()
    test_no_verdict_is_not_a_pass()
    test_summary_separates_pass_from_not_run()
    test_discover_finds_new_files_and_admits_its_blind_spot()
    test_verdict_vocabulary_matches_reality()
    test_doubles_accept_what_the_real_function_accepts()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        sys.exit(1)
    print("ALL RUNNER CONTRACT TESTS PASSED")
