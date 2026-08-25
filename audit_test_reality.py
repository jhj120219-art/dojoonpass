"""검사가 **제품 코드를 실제로 실행하는가**를 전수로 잰다 (2026-08-21 Sprint 242).

## 왜

Sprint 241 에서 `test_worker_capacity.py` 가 상수끼리만 비교하고 제품 코드를 한 줄도
지나지 않는다는 것이 mutation 으로 드러났다. 그 문제를 **저장소 전체로** 확장한다.

## 방법 — 의견이 아니라 측정

각 `test_*.py` 를 `coverage` 로 따로 돌려서, **제품 모듈**(api/, storage/, crawler/,
config/, normalizer/, validator/, search/, filter/, intent/, models/ 및 루트의 제품
스크립트)에서 몇 줄을 실제로 실행했는지 센다.

    실행 줄 0        -> 제품 코드를 전혀 지나지 않는다. 소스 문자열/상수만 보는 검사다.
    실행 줄 매우 적음 -> 대부분 문자열 검사이고 실제 동작 검증은 곁다리일 수 있다.

★ 실행 줄이 적다고 **곧바로 결함은 아니다.** 드리프트 가드(파일명·설정값·문서 동기화)는
  원래 소스만 봐야 한다. 이 스크립트는 **의심 목록**을 만들 뿐이고, 판정은 mutation 으로
  한다. 그래서 출력에 "결함"이라고 쓰지 않는다.
"""
import io, os, re, subprocess, sys, json

# ★ 2026-08-22 수정 — 예전에는 다른 컴퓨터의 사용자 프로필 경로가 하드코딩돼 있었다
# (`C:\Users\jhj12\OneDrive\Desktop\dojoonpass`). 이 저장소가 여러 기기를 오가며
# 개발된 흔적이다. 이 머신에는 그 경로가 **OneDrive가 동기화해 둔 빈 폴더**로
# 우연히 존재해서(`.next/` 하나만 든 빈 껍데기, 실제 코드 0개) `os.chdir()`/
# `os.listdir()`가 예외 없이 조용히 성공하고 `files`가 빈 목록이 되어, 이 도구가
# **"의심 목록 없음"을 계속 출력하면서 실제로는 아무 test_*.py도 한 번도 돌리지
# 않고 있었다** — 이 저장소가 반복 경계하는 바로 그 "CWD/경로 의존성" 결함이
# 정작 그것을 감시해야 할 감사 도구 자신에게 있었다(같은 패턴이 `api/auth.py`
# 등에서 이미 Sprint245/246에 고쳐진 방식 그대로 여기도 고친다).
REPO = os.path.dirname(os.path.abspath(__file__))
os.chdir(REPO)

PRODUCT_DIRS = ("api", "storage", "crawler", "config", "normalizer",
                "validator", "search", "filter", "intent", "models")
PRODUCT_ROOT_FILES = ("doc_worker.py", "collect_documents.py", "migrate_execute.py",
                      "mvp_scraper.py", "api_server.py", "refresh_priority.py",
                      "backfill_doc_raw.py",
                      # ★ 저장소 자체 도구도 "실행 대상"이다 (2026-08-21 실측으로 추가).
                      #   처음엔 빠져 있어서 `test_runner_contract.py` 가 **실행 0줄**로
                      #   나왔다 - 그 파일은 실제로 `run_python_tests.py` 를 import 하고
                      #   subprocess 로 돌리는데도 그랬다. 도구의 분류 목록이 좁아
                      #   멀쩡한 검사를 "공허하다"고 부를 뻔했다.
                      #
                      #   ※ 2026-08-24 복원 — 위 두 파일 이름은 이 파일이 처음 커밋될 때
                      #     (`64e9116`)부터 **빈 자리로 비어 있었다**(git 이력에도 온전한
                      #     판이 없다). 이름 없이 "그 파일"만 남으면 다음 사람이 무엇을
                      #     말하는지 알 수 없어 이 목록을 함부로 줄이게 된다. 지금 소스로
                      #     다시 확인해 채웠다: `test_runner_contract.py:42` 가
                      #     `import run_python_tests as R`, `:143` 이 그것을
                      #     `subprocess.run([sys.executable, "run_python_tests.py", ...])`
                      #     로 돌린다.
                      "run_python_tests.py", "audit_asset_integrity.py",
                      "audit_schedule_health.py", "audit_viewport.py",
                      # 2026-08-24 추가 — 위 두 감사 도구와 같은 부류인데 빠져 있었다
                      # (`test_audit_selftests.py` 가 셋을 함께 돌린다).
                      "audit_auth_health.py",
                      "cleanup_orphans_dryrun.py", "unlock_retry.py")

SKIP = {"test_db.py", "test_docs.py", "test_docs2.py"}     # 스스로 SKIP 하는 실크롤 스크립트


def is_product(path: str) -> bool:
    p = os.path.relpath(path, REPO).replace("\\", "/")
    if p.startswith("test_") or "/site-packages/" in p or p.startswith(".claude/"):
        return False
    if os.path.basename(p) in PRODUCT_ROOT_FILES:
        return True
    return any(p.startswith(d + "/") for d in PRODUCT_DIRS)


def _why_no_json(cov, out):
    """`coverage json` 이 JSON 을 안 내놓았을 때 그 이유를 한 줄로 만든다.

    두 프로세스의 종료코드와 stderr 꺼리를 붙인다. 순수 함수라
    selftest 가 프로세스 없이도 검증할 수 있다.
    """
    def tail(proc):
        blob = (getattr(proc, "stderr", b"") or b"") + (getattr(proc, "stdout", b"") or b"")
        text = blob.decode("utf-8", "replace").strip().replace(chr(10), " | ")
        return text[-160:]
    bits = ["coverage json 가 JSON 을 내놓지 않았다"]
    if getattr(cov, "returncode", 0):
        bits.append("coverage run exit=%s %s" % (cov.returncode, tail(cov)))
    if getattr(out, "returncode", 0):
        bits.append("coverage json exit=%s %s" % (out.returncode, tail(out)))
    if len(bits) == 1:
        bits.append("두 프로세스 다 exit 0 이다 - 동시 실행으로 수집 파일이 섮였을 수 있다")
    return " / ".join(bits)


def run_one(test_file: str):
    data_file = os.path.join(REPO, ".cov_%s" % test_file.replace(".", "_"))
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["COVERAGE_FILE"] = data_file
    # ★ 실패하면 **왜** 실패했는지 반드시 남긴다 (2026-08-25).
    #   예전에는 JSON 이 안 나오면 그냥 `None` 을 돌려줘서 호출부가
    #   "측정 실패 " 만 찍고 이유를 한 글자도 보여 주지 않았다. 2026-08-25 에
    #   연속 8개가 그렇게 띄었고(원인은 다른 작업과 동시 실행이었다),
    #   그 출력만으로는 "감사가 고장났다"와 "검사가 깨졌다"를 구별할 수 없었다 —
    #   이 저장소가 반복해서 당한 바로 그 모양이다(증거 없는 실패).
    try:
        cov = subprocess.run([sys.executable, "-m", "coverage", "run", "--source", ".",
                              test_file],
                             cwd=REPO, env=env, capture_output=True, timeout=600)
        out = subprocess.run([sys.executable, "-m", "coverage", "json", "-o", "-", "--quiet"],
                             cwd=REPO, env=env, capture_output=True, timeout=300)
        raw = out.stdout.decode("utf-8", "replace")
        i = raw.find("{")
        if i < 0:
            return {"error": _why_no_json(cov, out)}
        data = json.loads(raw[i:])
    except Exception as e:
        return {"error": "%s: %s" % (type(e).__name__, str(e)[:80])}
    finally:
        for suffix in ("", ".lock"):
            try: os.remove(data_file + suffix)
            except OSError: pass

    executed, modules = 0, []
    for fname, info in data.get("files", {}).items():
        full = os.path.join(REPO, fname)
        if not is_product(full):
            continue
        n = info["summary"]["covered_lines"]
        if n:
            executed += n
            modules.append((os.path.relpath(full, REPO).replace("\\", "/"), n))
    modules.sort(key=lambda x: -x[1])
    return {"executed": executed, "top": modules[:4], "nmod": len(modules)}


def _spawn_hint(test_file: str):
    """이 검사가 **자식 파이썬 프로세스로 무엇을 돌리는지**를 소스에서 읽어 돌려준다.

    돌려주는 것은 그 대상 파일명(여럿이면 콤마로). 자식 프로세스를 안 쓰면 빈 문자열.

    왜 소스를 읽나 — coverage 로는 알 수 없기 때문이다. 자식 프로세스에서 실행된 줄은
    부모의 커버리지 데이터에 아예 들어오지 않는다. 그래서 "실행 0줄"이 두 가지 전혀 다른
    상태를 뜻하게 된다: (a) 진짜로 제품 코드를 안 지난다 (b) 자식이 다 실행했는데 안 보인다.
    (b)를 (a)로 읽으면 멀쩡한 검사를 지운다.
    """
    path = os.path.join(REPO, test_file)
    try:
        src = io.open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return ""
    if "subprocess" not in src:
        return ""
    targets = []
    # `subprocess.run([sys.executable, ..., "<something>.py", ...])` 안의 .py 이름
    for m in re.finditer(r"subprocess\.run\(\s*\[([^\]]{0,400})\]", src, re.S):
        chunk = m.group(1)
        if "sys.executable" not in chunk:
            continue
        for name in re.findall(r"[\"']([A-Za-z0-9_./\\-]+\.py)[\"']", chunk):
            base = os.path.basename(name)
            if base != test_file and base not in targets:
                targets.append(base)
    # 리스트를 변수로 만들어 넘기는 모양(예: TOOLS 목록)도 잡는다.
    if not targets:
        for name in re.findall(r"[\"']([A-Za-z0-9_-]+\.py)[\"']", src):
            if name != test_file and is_product(os.path.join(REPO, name)) and name not in targets:
                targets.append(name)
        if targets and "sys.executable" not in src:
            targets = []
    return ", ".join(targets[:3])


def main():
    files = sorted(f for f in os.listdir(REPO)
                   if f.startswith("test_") and f.endswith(".py") and f not in SKIP)
    only = [a for a in sys.argv[1:] if not a.startswith("-")]
    if only:
        files = [f for f in files if any(o in f for o in only)]
    print("=" * 78)
    print(" 검사별 제품 코드 실행 줄 수 (2026-08-21 실측)")
    print("=" * 78)
    rows = []
    for i, f in enumerate(files, 1):
        r = run_one(f)
        if r is None or "error" in r:
            print("  [%2d/%d] %-38s 측정 실패 %s" % (i, len(files), f, (r or {}).get("error", "")))
            continue
        rows.append((r["executed"], f, r))
        print("  [%2d/%d] %-38s 제품 %5d줄 / 모듈 %2d  %s"
              % (i, len(files), f, r["executed"], r["nmod"],
                 ", ".join("%s:%d" % (m, n) for m, n in r["top"][:2])))
    rows.sort()
    print()
    print("=" * 78)
    print(" 의심 목록 - 제품 코드를 거의/전혀 실행하지 않는 검사")
    print("=" * 78)
    subproc = 0
    for ex, f, r in rows:
        if ex >= 60:
            continue
        # ★ 2026-08-24 — coverage 는 **자식 프로세스를 따라가지 못한다.**
        #   제품 코드를 `subprocess.run([sys.executable, ...])` 로 돌리는 검사는
        #   실제로 그 코드를 전부 실행하고도 여기서 "실행 0줄"로 나온다. 그 둘을
        #   같은 문장으로 찍으면, 멀쩡한 검사를 공허하다고 읽고 지우게 된다 —
        #   이 도구가 막으려던 오독을 이 도구가 만드는 셈이다.
        #   (`test_audit_selftests.py` 가 정확히 이 모양이다: 감사 도구 3종의
        #    `--selftest` 를 자식 프로세스로 돌리고 종료 코드로 판정한다.)
        hint = _spawn_hint(f)
        if hint:
            subproc += 1
            label = "<- 자식 프로세스로 실행한다(coverage 가 못 본다): %s" % hint
        elif ex == 0:
            label = "<- 소스 문자열/상수만 본다"
        else:
            label = "<- 대부분 문자열 검사일 수 있다"
        print("  [실행 %3d줄] %-36s %s" % (ex, f, label))
    print()
    print("  ※ 실행 줄이 적다고 결함이 아니다. 드리프트 가드는 원래 소스만 본다.")
    print("     판정은 mutation 으로 한다.")
    if subproc:
        print("  ※ '자식 프로세스로 실행한다'로 표시된 %d개는 **측정의 한계**이지"
              " 검사의 결함이 아니다." % subproc)




# ---------------------------------------------------------------------------
# selftest (2026-08-25 신설)
#
# 이 도구는 다른 검사들이 "공허하지 않은가"를 재는 도구다. 그런데 자기 자신은
# 아무도 재지 않았다 — `test_audit_selftests.py` 의 표에도 없었다. 감사기가 조용히
# 눈이 머는 것이 바로 이 저장소가 반복해서 당한 일이라, 최소한 **실패를 설명하는
# 경로**만큼은 고정해 둔다(그 경로가 실제로 비어 있었다 - 아래 참고).
#
# 아무것도 실행하지 않는다 — 순수 함수 `_why_no_json()` / `is_product()` 만 본다.
# (본 실행은 테스트 55개를 coverage 로 전부 돌려서 수 분이 걸리므로 회귀에 못 넣는다.)
# ---------------------------------------------------------------------------
def selftest():
    fails = []

    def check(name, cond, detail=""):
        print("  [%s] %s%s" % ("PASS" if cond else "FAIL", name,
                               "" if cond else " -- %s" % detail))
        if not cond:
            fails.append(name)

    class _P:
        def __init__(self, rc, err=b"", out=b""):
            self.returncode, self.stderr, self.stdout = rc, err, out

    print("--- selftest: 측정 실패의 이유가 실제로 남는가 ---")
    #
    # 왜 이것부터인가 — 2026-08-25 에 이 도구가 연속 8개에 대해 "측정 실패 " 만 찍고
    # 이유를 한 글자도 남기지 않았다. 그 출력만으로는 "감사기가 고장났다"와 "검사가
    # 깨졌다"를 구별할 수 없다. 증거 없는 실패는 이 저장소가 반복해서 당한 함정이다.
    #
    m = _why_no_json(_P(1, b"No source for code: 'x.py'"), _P(0))
    check("coverage run 실패를 이유에 담는다",
          "coverage run exit=1" in m and "No source" in m, m)

    m = _why_no_json(_P(0), _P(2, b"No data to report."))
    check("coverage json 실패를 이유에 담는다",
          "coverage json exit=2" in m and "No data" in m, m)

    m = _why_no_json(_P(0), _P(0))
    check("둘 다 exit 0 이면 그 사실 자체를 말한다(빈 문자열로 끝나지 않는다)",
          "동시 실행" in m, m)

    m = _why_no_json(_P(1, b"x" * 500), _P(0))
    check("긴 stderr 를 잘라 한 줄로 만든다", len(m) < 400 and chr(10) not in m, len(m))

    m = _why_no_json(_P(1, b"a\nb\nc"), _P(0))
    check("여러 줄 stderr 를 한 줄로 접는다", "|" in m and chr(10) not in m, m)

    m = _why_no_json(None, None)
    check("프로세스 객체가 없어도 죽지 않는다", isinstance(m, str) and m, m)

    check("★ 이유가 절대 빈 문자열이 아니다",
          all(_why_no_json(a, b) for a, b in
              [(_P(0), _P(0)), (_P(1), _P(0)), (_P(0), _P(1)), (None, None)]), "")

    print("--- selftest: 제품/검사 파일 구분 ---")
    check("테스트 파일은 제품이 아니다",
          not is_product(os.path.join(REPO, "test_search.py")), "")
    check("감사기 자신도 제품이 아니다",
          not is_product(os.path.join(REPO, "audit_test_reality.py")), "")
    check("api 라우터는 제품이다",
          is_product(os.path.join(REPO, "api", "v1", "search.py")), "")

    print()
    if fails:
        print("selftest 실패 %d건: %s" % (len(fails), fails))
        return 1
    print("selftest 전체 통과")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    main()
