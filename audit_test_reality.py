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
import io, os, re, shutil, subprocess, sys, time, json

# ★ 저장소 경로는 **이 파일 기준**이다 (2026-08-27, BUGS #252).
#
#   예전에는 다른 컴퓨터의 사용자 프로필 절대경로가 그대로 박혀 있었다.
#   그 계정이 아닌 곳에서는 `os.chdir()` 이 곧바로 죽어 **감사가 한 줄도 돌지 않는다**
#   — 있는데 안 도는 감사다. `test_schema_hygiene.py` 의 하드코딩 경로 검사가
#   실제로 이것을 붉게 잡고 있었다.
#
#   저장소의 다른 곳(`storage/database.py` 의 DB_PATH, `mvp_scraper.py` 의 _HERE)이
#   이미 쓰는 규칙과 같게 맞춘다.
REPO = os.path.dirname(os.path.abspath(__file__))
os.chdir(REPO)

PRODUCT_DIRS = ("api", "storage", "crawler", "config", "normalizer",
                "validator", "search", "filter", "intent", "models")
PRODUCT_ROOT_FILES = ("doc_worker.py", "collect_documents.py", "migrate_execute.py",
                      "mvp_scraper.py", "api_server.py", "refresh_priority.py",
                      "backfill_doc_raw.py",
                      # ★ 저장소 자체 도구도 "실행 대상"이다 (2026-08-21 실측으로 추가).
                      #   처음엔 빠져 있어서 `test_runner_contract.py` 가
                      #   **실행 0줄**로 나왔다 - 그 파일은 실제로
                      #   `run_python_tests` 를 import 하고
                      #   subprocess 로 돌리는데도 그랬다. 도구의 분류 목록이 좁아
                      #   멀쩡한 검사를 "공허하다"고 부를 뻔했다.
                      "run_python_tests.py", "audit_asset_integrity.py",
                      "audit_schedule_health.py", "audit_viewport.py",
                      "cleanup_orphans_dryrun.py", "unlock_retry.py")

SKIP = {"test_db.py", "test_docs.py", "test_docs2.py"}     # 스스로 SKIP 하는 실크롤 스크립트


def is_product(path: str) -> bool:
    p = os.path.relpath(path, REPO).replace("\\", "/")
    if p.startswith("test_") or "/site-packages/" in p or p.startswith(".claude/"):
        return False
    if os.path.basename(p) in PRODUCT_ROOT_FILES:
        return True
    return any(p.startswith(d + "/") for d in PRODUCT_DIRS)


def run_one(test_file: str):
    data_file = os.path.join(REPO, ".cov_%s" % test_file.replace(".", "_"))
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["COVERAGE_FILE"] = data_file
    try:
        subprocess.run([sys.executable, "-m", "coverage", "run", "--source", ".",
                        test_file],
                       cwd=REPO, env=env, capture_output=True, timeout=600)
        out = subprocess.run([sys.executable, "-m", "coverage", "json", "-o", "-", "--quiet"],
                             cwd=REPO, env=env, capture_output=True, timeout=300)
        raw = out.stdout.decode("utf-8", "replace")
        i = raw.find("{")
        if i < 0:
            # ★ 예전에는 여기서 `None` 을 돌려줬다 (2026-08-27, BUGS #258).
            #   호출부는 `(r or {}).get("error", "")` 로 읽으므로 화면에는
            #   **"측정 실패" 뒤에 빈칸**만 남는다 - 왜 실패했는지 한 글자도 없다.
            #   이 도구는 "검사가 공허하지 않은가"를 재는 도구인데, 정작 자기
            #   실패를 조용히 삼키고 있었다. 이유를 반드시 들려 보낸다.
            err = (out.stderr or b"").decode("utf-8", "replace").strip()
            return {"error": ("coverage json 출력에 JSON 이 없다: %s"
                              % (err or raw.strip() or "(출력 없음)"))[:200]}
        data = json.loads(raw[i:])
    except Exception as e:
        return {"error": str(e)[:60]}
    finally:
        # ★ 지우지 못하면 **조용히 넘어가지 않는다** (2026-08-27, docs/BUGS.md #264).
        #
        #   예전에는 `except OSError: pass` 하나였다. Windows 에서 coverage 가 파일을
        #   아직 쥐고 있으면 그 한 줄이 삼키고, `.cov_<파일명>` 이 저장소 루트에 남는다.
        #   그렇게 남은 것이 실제로 커밋된 적이 있다
        #   (`.cov_test_audit_selftests-DESKTOP-DVRJEGP_py`, BUGS #253 이 잡은 그 파일).
        #
        #   `.gitignore` 에 `.cov_*` 를 넣어 커밋은 막았지만, 그것만으로는 **작업 트리에
        #   쓰레기가 쌓이는 것**을 막지 못한다. 잠깐 기다렸다 다시 시도하고,
        #   그래도 안 되면 경고로 남긴다 — 남았다는 사실을 사람이 알아야 한다.
        for suffix in ("", ".lock"):
            target = data_file + suffix
            for attempt in range(3):
                if not os.path.exists(target):
                    break
                try:
                    os.remove(target)
                    break
                except OSError:
                    time.sleep(0.2)
            else:
                if os.path.exists(target):
                    print("  [WARN] 커버리지 산출물을 지우지 못했다: %s"
                          % os.path.basename(target))

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
    for ex, f, r in rows:
        if ex == 0:
            print("  [실행 0줄] %-38s <- 소스 문자열/상수만 본다" % f)
        elif ex < 60:
            print("  [실행 %3d줄] %-36s <- 대부분 문자열 검사일 수 있다" % (ex, f))
    print()
    print("  ※ 실행 줄이 적다고 결함이 아니다. 드리프트 가드는 원래 소스만 본다.")
    print("     판정은 mutation 으로 한다.")


# ---------------------------------------------------------------------------
# selftest — **이 도구 자신이 옳게 재는가** (2026-08-27, docs/BUGS.md #258)
#
# 이 도구는 "다른 검사가 공허하지 않은가"를 재면서 정작 자기 자신은 아무도 재지 않았다.
# 그런데 이 도구가 틀렸을 때 나오는 것은 **오류가 아니라 그럴듯한 숫자**다 —
# `is_product()` 의 판정이 어긋나면 "제품 0줄"(= 의심 목록에 오른다)이나
# "제품 5,000줄"(= 안심하고 넘어간다)이 조용히 나온다.
#
# 전체 스윕(69개 파일 x coverage)은 몇 분이 걸리므로 selftest 로 쓸 수 없다.
# 그래서 **판정 로직과 측정 경로만** 태운다:
#
#   [1] is_product()  분류가 양쪽으로 옳은가 (제품을 제품이라 하고, 검사를 검사라 한다)
#   [2] run_one()     제품 코드를 지나는 파일에서 **0보다 큰 줄 수**가 나오는가
#   [3] run_one()     제품 코드를 전혀 안 지나는 파일에서 **정확히 0** 이 나오는가
#   [4] 측정이 실패하면 **이유를 남기는가** (조용히 None 으로 사라지지 않는가)
#
# [2]와 [3]이 짝이다 — 한쪽만 있으면 "항상 0" 이나 "항상 큰 수" 인 고장을 못 잡는다.
# ---------------------------------------------------------------------------
_SELFTEST_FAILURES = []


def _st_check(name, cond, detail=""):
    ok = bool(cond)
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name,
                         "" if ok else " -> " + str(detail)))
    if not ok:
        _SELFTEST_FAILURES.append(name)


def selftest():
    import tempfile

    print("=" * 60)
    print(" audit_test_reality.py --selftest")
    print("=" * 60)

    # [1] 분류 -------------------------------------------------------------
    print("\n--- 1. is_product() 분류 ---")
    for rel, expect in (
        ("storage/database.py", True),
        ("api/v1/admin.py", True),
        ("crawler/court_crawler.py", True),
        ("mvp_scraper.py", True),
        ("doc_worker.py", True),
        ("test_document_queue.py", False),
        # ★ 저장소 자체 도구도 "실행 대상"이다 - 위 PRODUCT_ROOT_FILES 의
        #   주석 참고. 여기서 False 를 기대하면 그 결정을 되돌리게 된다.
        ("run_python_tests.py", True),
        ("test_schema_hygiene.py", False),
        (".claude/whatever.py", False),
    ):
        got = is_product(os.path.join(REPO, rel.replace("/", os.sep)))
        _st_check("is_product(%s) == %s" % (rel, expect), got == expect, got)

    _st_check("제품 목록이 비어 있지 않다(검사가 공허하지 않다)",
              len(PRODUCT_DIRS) > 0 and len(PRODUCT_ROOT_FILES) > 0)

    # [2][3] 측정 ---------------------------------------------------------
    print("\n--- 2. run_one() 이 실제로 제품 줄을 센다 ---")
    d = tempfile.mkdtemp(prefix="atr_selftest_")
    touching = os.path.join(REPO, "_atr_selftest_touching.py")
    inert = os.path.join(REPO, "_atr_selftest_inert.py")
    try:
        # 제품 코드를 확실히 지나는 파일 - `calc_priority()` 는 DB 를 열지 않는다.
        io.open(touching, "w", encoding="utf-8").write(
            "import sys, os\n"
            "sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))\n"
            "import storage.database as d\n"
            "for x in ('2099-01-01', '', 'bad', '2026-01-01'):\n"
            "    d.calc_priority(x)\n"
            "print('[PASS] probe')\n")
        # 제품 코드를 한 줄도 안 지나는 파일.
        io.open(inert, "w", encoding="utf-8").write(
            "print('[PASS] inert probe')\n")

        r_touch = run_one("_atr_selftest_touching.py")
        r_inert = run_one("_atr_selftest_inert.py")

        _st_check("제품을 지나는 파일에서 측정이 성공한다",
                  isinstance(r_touch, dict) and "error" not in r_touch, r_touch)
        if isinstance(r_touch, dict) and "error" not in r_touch:
            _st_check("★ 제품을 지나는 파일은 0줄이 아니다",
                      r_touch["executed"] > 0, r_touch)
            _st_check("어느 모듈을 지났는지도 남는다",
                      any(m.endswith("storage/database.py") for m, _ in r_touch["top"]),
                      r_touch["top"])

        _st_check("제품을 안 지나는 파일에서 측정이 성공한다",
                  isinstance(r_inert, dict) and "error" not in r_inert, r_inert)
        if isinstance(r_inert, dict) and "error" not in r_inert:
            _st_check("★ 제품을 안 지나는 파일은 정확히 0줄이다",
                      r_inert["executed"] == 0, r_inert)

        # [4] 실패해도 이유를 남긴다 --------------------------------------
        print("\n--- 3. 측정 실패는 조용하지 않다 ---")
        missing = run_one("_atr_selftest_does_not_exist.py")
        _st_check("없는 파일도 dict 로 돌아온다(None 으로 사라지지 않는다)",
                  isinstance(missing, dict), missing)
        if isinstance(missing, dict):
            _st_check("★ 실패 이유가 비어 있지 않다",
                      bool(missing.get("error")) or missing.get("executed") == 0,
                      missing)
    finally:
        for f in (touching, inert):
            try:
                os.remove(f)
            except OSError:
                pass
        # coverage 산출물이 저장소에 남지 않게 한다(추적되면 감사가 잡는다).
        for name in os.listdir(REPO):
            if name.startswith(".cov__atr_selftest"):
                try:
                    os.remove(os.path.join(REPO, name))
                except OSError:
                    pass
        shutil.rmtree(d, ignore_errors=True)

    print()
    if _SELFTEST_FAILURES:
        print("FAILED (%d): %s" % (len(_SELFTEST_FAILURES),
                                   ", ".join(_SELFTEST_FAILURES)))
        return 1
    print("ALL SELFTEST CHECKS PASSED")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    main()

