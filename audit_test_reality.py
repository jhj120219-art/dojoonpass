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
                      #   처음엔 빠져 있어서  가 **실행 0줄**로
                      #   나왔다 - 그 파일은 실제로  를 import 하고
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
            return None
        data = json.loads(raw[i:])
    except Exception as e:
        return {"error": str(e)[:60]}
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


if __name__ == "__main__":
    main()
