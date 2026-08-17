"""크롤 오류 기록(`crawler/court_crawler.py:log_error`) 회귀 — 2026-08-17 Sprint 146 신설.

## 왜 이 파일이 생겼나

커버리지를 실측하니 `crawler/court_crawler.py`가 **91문장 0%**였다. 모듈 전체를
테스트하는 것은 의미가 없다 — 3개 함수 중 `crawl_detail`/`crawl_court`는 selenium
드라이버를 받아 실제 브라우저를 모는 코드이고, 순수 계산 로직은 이미 Sprint 47이
`crawler/resume.py`로 분리해 **100%** 덮여 있다(`storage/checkpoint.py`,
`models/*`도 100%).

0%로 남은 것 중 **selenium 없이 돌릴 수 있는 함수는 `log_error` 하나**이고,
이것이 지키는 것이 하필 이 저장소가 반복해 겪은 **"조용한 실패"** 다:

```python
try:
    os.makedirs("logs", exist_ok=True)      # <- Sprint 98이 추가한 한 줄
    with open("logs/errors.jsonl", "a", ...) as f:
        f.write(...)
except Exception:
    pass                                     # <- 모든 예외를 삼킨다
```

`logs/`는 `.gitignore` 대상이라 **새 체크아웃/새 배포에는 없다.** `makedirs` 한 줄이
빠지면 `open()`이 실패하고 `except`가 그것을 삼켜 **크롤 오류 기록이 통째로 사라진다**
— 정작 가장 필요한 순간에. Sprint 98이 그 한 줄을 넣어 고쳤지만 **검사는 없었다.**
지우면 아무도 모르게 되돌아간다.

## 운영 로그를 건드리지 않는다

`log_error`는 `logs/errors.jsonl`에 **상대 경로로** 쓴다. 그래서 이 테스트는 임시
디렉터리로 `chdir`한 뒤 실행하고 끝나면 되돌린다 — 저장소의 `logs/`는 손대지 않는다.

    python test_crawl_error_log.py
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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


class TempCwd:
    """임시 디렉터리에서 실행한다 — 저장소의 logs/를 오염시키지 않기 위해서다."""

    def __enter__(self):
        self.old = os.getcwd()
        self.dir = tempfile.mkdtemp(prefix="qa_errlog_")
        os.chdir(self.dir)
        return self.dir

    def __exit__(self, *a):
        os.chdir(self.old)
        shutil.rmtree(self.dir, ignore_errors=True)


def _read_lines():
    path = os.path.join("logs", "errors.jsonl")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return [ln for ln in f.read().splitlines() if ln.strip()]


# ---------------------------------------------------------------------------
# 1. 정상 — 기록이 실제로 남는다
# ---------------------------------------------------------------------------
def test_writes_entry():
    print("\n--- 1. 정상 기록 ---")
    from crawler.court_crawler import log_error
    with TempCwd():
        log_error("2024타경1234", "detail", ValueError("boom"), 1)
        lines = _read_lines()
        check_true("파일이 생겼다", lines is not None)
        check("한 줄이다", len(lines or []), 1)
        entry = json.loads(lines[0])
        check("case_no", entry["case_no"], "2024타경1234")
        check("step", entry["step"], "detail")
        check("error는 예외 **클래스명**", entry["error"], "ValueError")
        check("message", entry["message"], "boom")
        check("retry", entry["retry"], 1)
        check_true("timestamp가 있다", bool(entry.get("timestamp")), entry)


# ---------------------------------------------------------------------------
# 2. ★ logs/ 가 없어도 기록된다 (Sprint 98이 고친 그 지점)
#
# `.gitignore` 대상이라 새 체크아웃에는 logs/가 없다. `os.makedirs`가 빠지면
# `open()`이 실패하고 `except Exception: pass`가 삼켜 **오류가 조용히 증발한다.**
# ---------------------------------------------------------------------------
def test_creates_logs_dir_when_missing():
    print("\n--- 2. logs/ 부재 시 자동 생성 (조용한 실패 방지) ---")
    from crawler.court_crawler import log_error
    with TempCwd() as d:
        check_true("사전 조건: logs/가 없다", not os.path.exists(os.path.join(d, "logs")))
        log_error("2024타경1", "list", RuntimeError("x"), 0)
        check_true("★ logs/가 생성됐다", os.path.isdir(os.path.join(d, "logs")))
        check("★ 기록이 남았다(증발하지 않았다)", len(_read_lines() or []), 1)


# ---------------------------------------------------------------------------
# 3. 누적 — 덮어쓰지 않고 append
# ---------------------------------------------------------------------------
def test_appends_not_overwrites():
    print("\n--- 3. append (앞선 기록을 지우지 않는다) ---")
    from crawler.court_crawler import log_error
    with TempCwd():
        for i in range(3):
            log_error("2024타경%d" % i, "detail", OSError("e%d" % i), i)
        lines = _read_lines() or []
        check("3줄이 쌓인다", len(lines), 3)
        check("첫 줄이 보존된다", json.loads(lines[0])["case_no"], "2024타경0")
        check_true("각 줄이 독립 JSON이다(JSONL)",
                   all(isinstance(json.loads(ln), dict) for ln in lines))


# ---------------------------------------------------------------------------
# 4. 경계값 — 메시지 300자 절단 / 비ASCII 보존
# ---------------------------------------------------------------------------
def test_message_truncation_and_unicode():
    print("\n--- 4. 경계값: 300자 절단 · 한글 보존 ---")
    from crawler.court_crawler import log_error
    with TempCwd():
        log_error("2024타경2", "detail", ValueError("가" * 1000), 2)
        entry = json.loads((_read_lines() or ["{}"])[0])
        check("메시지가 300자로 잘린다", len(entry["message"]), 300)
        check_true("한글이 이스케이프되지 않고 보존된다",
                   entry["message"].startswith("가가"), entry["message"][:12])
        # 정확히 300자인 메시지는 잘리지 않아야 한다(경계 off-by-one 방지).
        log_error("2024타경3", "detail", ValueError("나" * 300), 0)
        e2 = json.loads((_read_lines() or [])[1])
        check("정확히 300자는 그대로", len(e2["message"]), 300)


# ---------------------------------------------------------------------------
# 5. 실패 주입 — 쓸 수 없어도 크롤을 멈추지 않는다
#
# `except Exception: pass`는 **의도된 설계**다. 오류 기록이 실패했다고 크롤 전체를
# 죽이면 안 되기 때문이다. 그 계약이 유지되는지 확인한다(예외가 새면 크롤이 멈춘다).
# ---------------------------------------------------------------------------
def test_never_raises():
    print("\n--- 5. 기록에 실패해도 예외를 던지지 않는다 ---")
    from crawler.court_crawler import log_error
    with TempCwd() as d:
        # logs를 **파일**로 만들어 두면 makedirs/open이 실패한다.
        with open(os.path.join(d, "logs"), "w") as f:
            f.write("not a directory")
        try:
            log_error("2024타경4", "detail", ValueError("x"), 0)
            raised = None
        except Exception as exc:  # noqa: BLE001 - 계약 검증이 목적
            raised = type(exc).__name__
        check("예외를 던지지 않는다", raised, None)
        check_true("실패해도 파일을 남기지 않는다(부분 기록 없음)",
                   not os.path.isdir(os.path.join(d, "logs")))


# ---------------------------------------------------------------------------
# 5-B. 확인했지만 **고치지 않은 것** — `str(error)`가 터지는 예외
#
# `entry` dict는 `try` **밖**에서 만들어지고 거기에 `str(error)[:300]`이 있다. 따라서
# `__str__`이 예외를 던지는 별난 예외를 넘기면 `log_error` 자신이 예외를 던진다 —
# "크롤을 멈추지 않는다"는 이 함수의 계약과 어긋나 보인다.
#
# **그런데 그 경로는 실제로 도달할 수 없다.** 프로덕션 호출부가 하나뿐이고,
# 그 바로 윗줄이 이미 `str(e)`를 평가한다:
#
#     crawler/court_crawler.py
#       81      logger.warning("[%s] attempt %d/%d failed: %s",
#       82          case_no, attempt, MAX_RETRY, str(e))     <- 여기서 먼저 터진다
#       83      log_error(case_no, "detail", e, attempt)
#
# 즉 `str()`이 터지는 예외는 82행에서 이미 전파되어 `log_error`에 닿지 못한다.
# 고쳐도 관측 가능한 동작이 바뀌지 않으므로 **프로덕션 코드를 건드리지 않았다**
# (확인되지 않은 이익을 위해 오류 처리 경로를 손대는 것이 더 위험하다).
#
# 이 주석을 남기는 이유: 다음에 같은 것을 발견한 사람이 **다시 조사하지 않도록** 하기
# 위해서다. 만약 `log_error`에 두 번째 호출부가 생기면 그때는 실제 위험이 되므로,
# 아래 검사가 "호출부는 하나"라는 전제를 고정한다.
# ---------------------------------------------------------------------------
def test_single_caller_assumption_holds():
    print("\n--- 5-B. 호출부가 하나라는 전제 (위 주석의 근거) ---")
    root = os.path.dirname(os.path.abspath(__file__))
    callers = []
    for name in os.listdir(root):
        if not name.endswith(".py") or name.startswith("test_"):
            continue
        path = os.path.join(root, name)
        if os.path.isfile(path):
            src = open(path, encoding="utf-8-sig", errors="ignore").read()
            if "log_error(" in src.replace("def log_error(", ""):
                callers.append(name)
    for sub in ("crawler", "storage", "api"):
        d = os.path.join(root, sub)
        if not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            if not name.endswith(".py"):
                continue
            src = open(os.path.join(d, name), encoding="utf-8-sig", errors="ignore").read()
            if "log_error(" in src.replace("def log_error(", ""):
                callers.append("%s/%s" % (sub, name))
    check("프로덕션 호출부는 court_crawler.py 하나뿐이다",
          sorted(callers), ["crawler/court_crawler.py"])


if __name__ == "__main__":
    test_writes_entry()
    test_creates_logs_dir_when_missing()
    test_appends_not_overwrites()
    test_message_truncation_and_unicode()
    test_never_raises()
    test_single_caller_assumption_holds()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        sys.exit(1)
    print("ALL CRAWL ERROR LOG TESTS PASSED")
