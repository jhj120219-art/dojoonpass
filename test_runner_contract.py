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


if __name__ == "__main__":
    test_exit_code_beats_wording()
    test_no_verdict_is_not_a_pass()
    test_summary_separates_pass_from_not_run()
    test_discover_finds_new_files_and_admits_its_blind_spot()
    test_verdict_vocabulary_matches_reality()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        sys.exit(1)
    print("ALL RUNNER CONTRACT TESTS PASSED")
