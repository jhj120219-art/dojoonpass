"""
API 라우터의 "예상치 못한 예외 -> HTTPException 500" 경로가 원인을 로그에 남기는지
회귀로 고정한다 (2026-08-18 Sprint 188, `docs/BUGS.md` #117 실측 과정에서 발견).

배경
----
`api/v1/search.py`의 `search()`/`get_regions()`는 `except Exception as e:` 에서 곧바로
`raise HTTPException(status_code=500, ...) from e`로 바꿔 던지고 있었다. FastAPI는
`HTTPException`을 "의도된 응답"으로 취급해 트레이스백을 찍지 않는다 — 그래서 실제 원인
(예: 테이블 누락 같은 서버측 결함)이 서버 로그 어디에도 남지 않고, 사용자에게 보이는
일반 오류 문구("검색 처리 중 오류가 발생했습니다")만 남았다. `api/v1/payments.py`의
웹훅 처리는 같은 자리에서 `logger.exception(...)`을 먼저 부르고 있어, 같은 저장소
안에서도 라우터마다 방식이 갈려 있었다.

이 결함 자체는 사용자에게 보이지 않는다(응답 내용은 그대로다) — 그래서 API 회귀
테스트(`test_api_regression.py`)의 상태코드/본문 검사로는 절대 잡히지 않는다.
로그 출력을 직접 캡처해야만 보인다.

이 파일이 하는 것 두 가지
------------------------
1. **실제 호출 경로로 재현** — `get_connection()`을 예외를 던지는 가짜로 바꿔치기하고
   `TestClient`로 실제 HTTP 요청을 보내, 응답은 그대로(500 + 같은 문구)인데 로그에
   근본 원인이 남는지/안 남는지를 직접 확인한다(수정 전에는 이 검사가 FAIL했을 것 —
   `git stash`로 되돌려 재현 가능).
2. **같은 계열 전수 검색(AST)** — 목록으로 대상을 정해 두면 새 라우터가 같은 실수를
   반복해도 못 잡는다. 그래서 `api/**/*.py` 전체를 AST로 훑어, `except Exception`
   (좁혀지지 않은 catch-all)이 `HTTPException`을 새로 던지면서 그 사이에 `logger.*` 호출이
   하나도 없는 지점을 **동적으로** 찾는다. `except HTTPException: raise`처럼 이미 잡은
   HTTPException을 그대로 다시 던지는 경우, 또는 좁은 예외 타입(`except ValueError as e:`
   등, 예상된 도메인 오류라 로그 소음일 뿐인 경우)은 대상이 아니다.

실행: python test_error_logging.py
"""
import ast
import io
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

failures = []


def check(name, actual, expected):
    ok = actual == expected
    print("[%s] %s: %r (expected %r)" % ("PASS" if ok else "FAIL", name, actual, expected))
    if not ok:
        failures.append(name)


def check_true(name, cond, detail=""):
    ok = bool(cond)
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name, ("" if ok else " -> " + str(detail))))
    if not ok:
        failures.append(name)


# ---------------------------------------------------------------------------
# 1. 실제 호출 경로 — TestClient를 통해 진짜 HTTP 요청으로 재현한다
# ---------------------------------------------------------------------------

class _RaisingConn:
    """`conn.execute(...)`가 항상 이 문자열을 담은 예외를 던진다.
    로그에 이 문자열이 있으면 근본 원인이 실제로 남은 것이고, 없으면 소실된 것이다."""
    MARKER = "qa-error-logging-marker-3f9a1c"

    def execute(self, *a, **k):
        raise RuntimeError(_RaisingConn.MARKER)

    def close(self):
        pass


def _run_with_captured_logs(module, endpoint_fn_name, request_fn):
    """`module.get_connection`을 `_RaisingConn`으로 바꿔치고, `module.logger`에 임시
    핸들러를 달아 `request_fn()`이 만드는 HTTP 응답과 그 사이 로그를 함께 돌려준다.
    끝나면 반드시 원상복구한다(다른 검사에 영향을 주지 않기 위해)."""
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setLevel(logging.ERROR)
    module.logger.addHandler(handler)
    prev_level = module.logger.level
    module.logger.setLevel(logging.ERROR)

    orig_get_connection = module.get_connection
    module.get_connection = lambda: _RaisingConn()
    try:
        response = request_fn()
    finally:
        module.get_connection = orig_get_connection
        module.logger.removeHandler(handler)
        module.logger.setLevel(prev_level)

    return response, buf.getvalue()


def test_search_endpoint_logs_root_cause():
    print("\n--- 1. /api/v1/search: 원인이 로그에 남는다 ---")
    import api.v1.search as search_mod
    from fastapi.testclient import TestClient
    import api_server

    client = TestClient(api_server.app)
    response, log_output = _run_with_captured_logs(
        search_mod, "search", lambda: client.get("/api/v1/search")
    )

    check("응답 상태코드는 그대로 500", response.status_code, 500)
    check("사용자에게 보이는 문구는 안 바뀐다",
          response.json().get("detail"), "검색 처리 중 오류가 발생했습니다")
    check_true("근본 원인이 로그에 남는다", _RaisingConn.MARKER in log_output,
               "로그에서 마커를 찾지 못함 (첫 300자: %r)" % log_output[:300])


def test_search_regions_endpoint_logs_root_cause():
    print("\n--- 2. /api/v1/search/regions: 원인이 로그에 남는다 ---")
    import api.v1.search as search_mod
    from fastapi.testclient import TestClient
    import api_server

    client = TestClient(api_server.app)
    response, log_output = _run_with_captured_logs(
        search_mod, "get_regions",
        lambda: client.get("/api/v1/search/regions", params={"sido": "서울"}),
    )

    check("응답 상태코드는 그대로 500", response.status_code, 500)
    check("사용자에게 보이는 문구는 안 바뀐다",
          response.json().get("detail"), "지역 목록 조회 중 오류가 발생했습니다")
    check_true("근본 원인이 로그에 남는다", _RaisingConn.MARKER in log_output,
               "로그에서 마커를 찾지 못함 (첫 300자: %r)" % log_output[:300])


# ---------------------------------------------------------------------------
# 2. 같은 계열 전수 검색 (AST) — 목록에 의존하지 않고 api/ 전체를 훑는다
# ---------------------------------------------------------------------------

def _iter_api_source_files():
    """`api/`와 `api/v1/` 아래 모든 `.py`. 서브디렉터리가 새로 생겨도 그대로 잡히도록
    `os.walk`로 재귀한다 — 목록을 하드코딩하지 않는다."""
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "api")
    for dirpath, _dirnames, filenames in os.walk(root):
        if "__pycache__" in dirpath:
            continue
        for fn in filenames:
            if fn.endswith(".py"):
                yield os.path.join(dirpath, fn)


def _is_bare_broad_except(handler: ast.ExceptHandler) -> bool:
    """`except Exception` / `except Exception as e` 만 대상으로 한다.
    `except HTTPException`, `except ValueError as e` 처럼 좁혀진 타입은 "예상된 도메인
    오류"일 가능성이 높아 로그가 없어도 결함이 아니다 — 실제로 `subscriptions.py` 등이
    그런 경우에 의도적으로 `logger.warning` 없이 처리한다."""
    if handler.type is None:
        return False  # bare `except:` — 이 저장소에는 없지만 있다면 별개 사안
    return isinstance(handler.type, ast.Name) and handler.type.id == "Exception"


def _raises_http_exception(node) -> bool:
    """핸들러 본문 안에 `raise HTTPException(...)` (그대로든 `from e`든)가 있는가."""
    for child in ast.walk(node):
        if isinstance(child, ast.Raise) and child.exc is not None:
            call = child.exc
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) \
                    and call.func.id == "HTTPException":
                return True
    return False


def _has_logger_call(node) -> bool:
    """핸들러 본문 안에 `logger.<무엇이든>(...)` 호출이 하나라도 있는가.
    `logger.exception` / `logger.error` / `logger.warning` 등 메서드 이름을 가리지 않는다
    — "로그를 남겼는가" 자체가 관심사이지 어떤 레벨을 썼는지는 별개 판단이다."""
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
            value = child.func.value
            if isinstance(value, ast.Name) and value.id == "logger":
                return True
    return False


def test_no_silent_broad_except_raises_http_exception():
    """`except Exception` 이 `HTTPException`을 새로 던지면서 로그를 안 남기는 지점이
    저장소 어디에도 없어야 한다 — 목록이 아니라 `api/` 전체를 AST로 훑는다.

    이 검사가 통과하려면 지금 `api/v1/search.py`에 있는 것과 **같은 모양의 결함이
    새로 생기면 즉시 FAIL해야** 한다 — 그래서 아래에서 실제로 그런 코드를 파싱시켜
    이 검사 자체가 결함을 잡아내는지부터 확인한다(공허한 검사 방지).
    """
    print("\n--- 3. except Exception -> HTTPException 인데 로그가 없는 지점 전수 검색 (AST) ---")

    # 3-a. 검사 로직 자체가 살아있는지 먼저 확인 — 결함이 있는 가짜 코드는 잡아야 하고,
    #      로그를 남기는 정상 코드는 잡지 않아야 한다.
    bad_sample = ast.parse(
        "try:\n"
        "    do_something()\n"
        "except Exception as e:\n"
        "    raise HTTPException(status_code=500, detail='x') from e\n"
    )
    good_sample = ast.parse(
        "try:\n"
        "    do_something()\n"
        "except Exception as e:\n"
        "    logger.exception('boom')\n"
        "    raise HTTPException(status_code=500, detail='x') from e\n"
    )
    bad_handler = bad_sample.body[0].handlers[0]
    good_handler = good_sample.body[0].handlers[0]
    check_true("검사 로직: 결함 있는 샘플을 실제로 잡는다",
               _is_bare_broad_except(bad_handler) and _raises_http_exception(bad_handler)
               and not _has_logger_call(bad_handler))
    check_true("검사 로직: 로그를 남기는 정상 샘플은 통과시킨다",
               _is_bare_broad_except(good_handler) and _raises_http_exception(good_handler)
               and _has_logger_call(good_handler))

    # 3-b. 실제 소스 전수 검사.
    offenders = []
    scanned = 0
    for path in _iter_api_source_files():
        with open(path, encoding="utf-8-sig") as f:
            src = f.read()
        try:
            tree = ast.parse(src, filename=path)
        except SyntaxError:
            continue
        scanned += 1
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if not _is_bare_broad_except(node):
                continue
            if _raises_http_exception(node) and not _has_logger_call(node):
                rel = os.path.relpath(path, os.path.dirname(os.path.abspath(__file__)))
                offenders.append("%s:%d" % (rel, node.lineno))

    check_true("api/ 아래 .py 파일을 실제로 훑었다(검사가 공허하지 않다)", scanned > 5,
               "-> %d개 파일만 스캔함" % scanned)
    check("로그 없이 HTTPException을 던지는 지점", offenders, [])


if __name__ == "__main__":
    test_search_endpoint_logs_root_cause()
    test_search_regions_endpoint_logs_root_cause()
    test_no_silent_broad_except_raises_http_exception()

    print()
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        sys.exit(1)
    print("ALL ERROR-LOGGING TESTS PASSED")
    sys.exit(0)
