"""파이썬 회귀 테스트 일괄 실행기 — 2026-08-17 Sprint 146 신설.

## 왜 이게 생겼나

이 저장소에는 `test_*.py` 가 37개 있는데 **한꺼번에 돌리는 수단이 없었다.**
`package.json` 에는 프런트용 `test:frontend` 만 있고, `.bat`/CI 어디에도 파이썬
테스트를 도는 것이 없다(2026-08-17 실측: `.github/workflows` 없음, `.bat`/`.ps1`
에서 `test_*.py` 참조 0건). 그래서 세션마다 셸 반복문을 즉석에서 만들어 썼고,
그 즉석 반복문이 **두 번 연속 결과를 잘못 읽었다.**

    1) `python $f | tail -3` 에 실패 문구가 없으면 통과로 셌다
       -> 마지막 3줄 위에서 죽은 실패를 놓친다.

    2) 파일 개수를 세어 "36 PASS / 1 FAIL" 이라고 보고했다
       -> 그중 4개는 **아무것도 단언하지 않고 0으로 끝나는 파일**이었다.
          `test_db.py` / `test_docs.py` / `test_docs2.py` 는 `ALLOW_LIVE_CRAWL=1`
          없이는 스스로 SKIP 하는 실크롤 스크립트고, `test_filter.py` 는 판정문 자체가
          없는 진단 스크립트다. 넷 다 "통과"로 집계됐다.

즉 문제는 테스트가 아니라 **집계**였다. 이 실행기는 그 집계를 정직하게 만든다.

## 판정 기준 — 종료코드를 1순위로 쓴다

실측으로 확인했다(2026-08-17): 실제 회귀 테스트 33개는 **전부** 실패 시 non-zero 로
끝난다(`sys.exit(1 if FAIL else 0)` 또는 `sys.exit(1)`). 실패를 주입해 본 결과
`test_auth_jwt.py` 도 1을 돌려준다. 그래서 종료코드는 믿을 수 있다.

반면 **출력 문구는 믿을 수 없다.** 이 저장소는 결과 어휘가 세 벌이다:

    [PASS]/[FAIL]        28개 파일
    [OK]/[NG]            일부
    "ALL ... TESTS PASSED" 만 있고 마커가 없는 파일  5개

게다가 `[FAIL]` 이 **테스트 대상의 정상 출력**인 경우가 있다 —
`test_auction_identity.py` 는 검증을 일부러 깨뜨려 `migrate_execute` 가 실패를
보고하는지 확인하므로, 통과할 때도 `[FAIL] document_status 불일치` 를 찍는다.
문구만 grep 하면 **통과한 테스트를 실패로 읽는다.**

    -> 그래서: 합격/불합격은 **종료코드**로, 판정문 유무는 **분류**에만 쓴다.

## 네 가지 상태로 나눈다 (통과와 무판정을 절대 합치지 않는다)

    PASSED      종료코드 0 + 판정문이 있다        진짜 통과
    FAILED      종료코드 != 0                     진짜 실패
    SKIPPED     스스로 건너뛴다고 밝힌 파일       실행 안 됨 (통과 아님)
    NO-VERDICT  0으로 끝났지만 판정문이 없다      검증했다고 말할 수 없음

`SKIPPED` 와 `NO-VERDICT` 를 요약에서 **따로** 찍는 이유는, 이것들이 통과 숫자에
섞여 들어간 것이 애초에 이 파일을 만든 이유이기 때문이다.

## 사용법

    python run_python_tests.py              # 전부
    python run_python_tests.py -k search    # 이름에 search 가 든 것만
    python run_python_tests.py -v           # 실패 파일의 출력도 함께

종료코드: 실패가 하나라도 있으면 1, 아니면 0. (SKIPPED/NO-VERDICT 는 0을 유지한다 —
이것들은 "깨졌다"가 아니라 "실행되지 않았다"이므로 게이트를 붉게 만들지 않는다.
대신 요약에 항상 눈에 띄게 남는다.)

이 파일은 **프로덕션 코드를 건드리지 않는다.** 순수 실행기다.
"""
import argparse
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))

# 파일이 "스스로 건너뛴다"고 밝히는 신호. 실크롤/유료 경로를 막아 둔 스크립트들이다.
SKIP_MARKERS = ("[SKIPPED]", "ALLOW_LIVE_CRAWL")

# "판정을 내렸다"고 인정하는 문구. 어휘가 세 벌이라 전부 받아 준다.
VERDICT_PATTERNS = (
    r"\[PASS\]", r"\[FAIL\]", r"\[OK\]", r"\[NG\]",
    r"ALL .*(TESTS?|PASSED)", r"\bFAILED\s*\(", r"결과:\s*\d+\s*PASS",
)

# 파일 하나당 상한. 통합 테스트(TestClient 부팅, 임시 DB 복사)가 있어 넉넉히 준다.
PER_FILE_TIMEOUT = 900


def discover(pattern=None):
    names = sorted(
        f for f in os.listdir(ROOT)
        if f.startswith("test_") and f.endswith(".py")
        and os.path.isfile(os.path.join(ROOT, f))
    )
    if pattern:
        names = [f for f in names if pattern.lower() in f.lower()]
    return names


def classify(returncode, out):
    """(상태, 단언수) 를 돌려준다. 상태 판단의 1순위는 종료코드다."""
    n_pass = len(re.findall(r"\[PASS\]|\[OK\]", out))
    n_fail = len(re.findall(r"\[FAIL\]|\[NG\]", out))
    asserts = n_pass + n_fail

    if returncode is None:
        return "TIMEOUT", asserts
    if returncode != 0:
        return "FAILED", asserts
    # 여기부터는 종료코드 0 — 그래도 "통과"라고 부르려면 판정문이 있어야 한다.
    if any(m in out for m in SKIP_MARKERS) and asserts == 0:
        return "SKIPPED", asserts
    if any(re.search(p, out) for p in VERDICT_PATTERNS):
        return "PASSED", asserts
    return "NO-VERDICT", asserts


def run_one(name):
    started = time.time()
    try:
        p = subprocess.run(
            [sys.executable, name], cwd=ROOT,
            capture_output=True, timeout=PER_FILE_TIMEOUT,
        )
        rc = p.returncode
        out = (p.stdout + p.stderr).decode("utf-8", "replace")
    except subprocess.TimeoutExpired as exc:
        rc = None
        got = (exc.stdout or b"") + (exc.stderr or b"")
        out = got.decode("utf-8", "replace")
    status, asserts = classify(rc, out)
    return status, asserts, out, rc, time.time() - started


def emit(line):
    """콘솔 코드페이지가 cp949 여도 죽지 않게 찍는다.

    이 저장소는 한글 출력이 기본이고 Windows 기본 콘솔은 cp949 다.
    `test_console_encoding.py` 가 지키는 것과 같은 문제로, 여기서 죽으면
    실행기 자체가 결과를 못 보여 준다.
    """
    try:
        print(line)
    except UnicodeEncodeError:
        enc = sys.stdout.encoding or "utf-8"
        print(line.encode(enc, "replace").decode(enc, "replace"))


def main():
    ap = argparse.ArgumentParser(description="파이썬 회귀 테스트 일괄 실행")
    ap.add_argument("-k", "--filter", dest="pattern", default=None,
                    help="파일명 부분 일치 필터")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="실패한 파일의 출력을 함께 보여 준다")
    args = ap.parse_args()

    files = discover(args.pattern)
    if not files:
        emit("대상 파일이 없습니다.")
        return 0

    emit("=" * 72)
    emit(" 파이썬 회귀 테스트 %d개 실행" % len(files))
    emit("=" * 72)

    buckets = {"PASSED": [], "FAILED": [], "SKIPPED": [], "NO-VERDICT": [], "TIMEOUT": []}
    outputs = {}
    total_asserts = 0
    t0 = time.time()

    for i, name in enumerate(files, 1):
        status, asserts, out, rc, secs = run_one(name)
        buckets[status].append(name)
        outputs[name] = out
        total_asserts += asserts
        emit("[%2d/%2d] %-11s %-38s 단언%-5d %5.1fs" %
             (i, len(files), status, name, asserts, secs))

    emit("=" * 72)
    emit(" 통과 %d | 실패 %d | 건너뜀 %d | 판정없음 %d | 시간초과 %d   (단언 %d건, %.1fs)"
         % (len(buckets["PASSED"]), len(buckets["FAILED"]), len(buckets["SKIPPED"]),
            len(buckets["NO-VERDICT"]), len(buckets["TIMEOUT"]),
            total_asserts, time.time() - t0))
    emit("=" * 72)

    # 통과가 아닌 것은 전부 이름을 남긴다 — 요약 숫자만 보고 넘어가지 못하게 한다.
    for label, key in (("실패", "FAILED"), ("시간초과", "TIMEOUT"),
                       ("건너뜀(실행되지 않음 — 통과가 아니다)", "SKIPPED"),
                       ("판정문 없음(검증했다고 말할 수 없다)", "NO-VERDICT")):
        if buckets[key]:
            emit("\n%s (%d):" % (label, len(buckets[key])))
            for n in buckets[key]:
                emit("   - %s" % n)

    if args.verbose:
        for n in buckets["FAILED"] + buckets["TIMEOUT"]:
            emit("\n" + "-" * 72)
            emit("### %s 출력" % n)
            emit("-" * 72)
            emit(outputs[n][-4000:])

    return 1 if (buckets["FAILED"] or buckets["TIMEOUT"]) else 0


if __name__ == "__main__":
    sys.exit(main())
