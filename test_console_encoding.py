"""
콘솔/로그 출력 인코딩 회귀 테스트 (의존성 없음 — 표준 라이브러리만 쓴다).

배경(2026-08-13 Sprint 72, Test Audit): 전체 회귀를 cp949 콘솔에서 돌렸더니
`test_beta_journey.py`와 `test_pipeline_integrity.py`가 **UnicodeEncodeError로 죽고
종료 코드 1**을 냈다. 테스트가 실패한 것이 아니라 **결과를 출력하다가 죽은 것**이다.

    UnicodeEncodeError: 'cp949' codec can't encode character '\\u2014'

원인은 출력 문자열에 박힌 U+2014 EM DASH다. 이 문자는 cp949에 없다.
그리고 이 저장소의 실행 환경은 cp949가 기본이다:

    PowerShell(Claude Code)   stdout=utf-8   -> 통과
    bash / cmd.exe            stdout=cp949   -> 죽음
    run_daily.bat 의 리다이렉트  `>> logs\\daily_run.log`
                              -> 리다이렉트된 stdout은 locale 인코딩(cp949) -> 죽음

즉 **같은 코드가 어디서 실행되느냐에 따라 통과/실패가 갈렸다.** 회귀 게이트로서는
그 자체가 결함이다. 운영 배치도 같은 조건이라 Sprint 54가 고친 "실패 은폐"와 같은
부류의 사고(크롤이 조용히 멈춤)로 이어질 수 있는 경로였다.

두 가지 서로 다른 고장을 낸다:

    print(...)     예외를 던진다        -> 프로세스가 죽고 종료 코드 1
    logger.xxx(...) 예외를 던지지 않는다 -> 대신 **그 로그 라인이 소실**되고
                                        "--- Logging error ---" 트레이스백으로 대체된다

후자가 더 나쁘다. `api/auth.py`의 JWKS 조회 실패 경고나 `payment_providers.py`의
`PAYMENT_WEBHOOK_SECRET` 미설정 경고처럼 **운영자가 반드시 봐야 하는 메시지**가
조용히 사라지기 때문이다.

수정은 문자 교체다. U+2015 HORIZONTAL BAR(`―`)는 **cp949에 존재하고(0xA1AA)
EM DASH와 시각적으로 같다** — 읽는 사람 입장에서 바뀐 것이 없다.

이 파일이 고정하는 불변식:

    "콘솔로 나가는 문자열 리터럴은 cp949로 인코딩할 수 있어야 한다"

**API 응답 문자열은 대상이 아니다.** JSON 응답은 UTF-8로 직렬화되므로 콘솔 인코딩과
무관하고, `api/v1/payment_logs.py:webhook_reprocess_block_reason()`처럼 응답에만 실리는
문장은 EM DASH를 그대로 쓸 수 있다. 규칙을 실제 고장 경로에만 건다.

    python test_console_encoding.py
"""
import sys
import os
import ast
import io
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.dirname(os.path.abspath(__file__))

# 콘솔 인코딩. 이 저장소의 실행 환경(한국어 Windows)에서 리다이렉트/cmd.exe의 기본값이다.
CONSOLE_ENCODING = "cp949"

EM_DASH = "—"        # 금지 — cp949에 없다
HORIZONTAL_BAR = "―"  # 대체 문자 — cp949 0xA1AA, 시각적으로 동일

# 스캔에서 제외할 디렉터리(우리 소스가 아니거나 수집 산출물).
#
# .gitignore된 로컬 진단 스크립트(`check_*.py` 등)는 **일부러 포함한다.** 실제로
# `check_db_path.py`가 "크롤러와 API가 같은 DB를 보는가"라는 답을 출력하는 바로 그 줄에서
# 죽고 있었다(✅ U+2705). 커밋되지 않는 파일이라도 개발자가 실제로 돌리는 도구다.
# 신규 클론에 그 파일들이 없으면 검사 대상에서 자연히 빠질 뿐 실패하지 않는다.
#
# ★ `.claude` 를 빼야 하는 이유 (2026-08-19 Sprint 223, BUGS #154).
#   이 저장소에는 `.claude/worktrees/sprint95-false-success-audit/` 가 남아 있다 —
#   Sprint 95 시점 커밋(c4f74e6)의 **저장소 통째 사본**이다.
#   제외하기 전 실측: 스캔한 .py 298개 중 **101개(34%)가 그 사본**이었다.
#   아무도 실행하지 않는 얼린 스냅샷에 규칙을 강제했고, 그 안에 위반이
#   하나라도 있었으면 **현재 코드가 멀집한데도 빨간불**이 켜졌을 것이다.
#   형제 검사인 `test_doc_path_safety.py` 는 이미 `.claude` 를 제외하고 있었다 —
#   둘이 같은 범위를 보도록 맞춘다.
SKIP_DIRS = {
    "node_modules", ".next", ".git", "__pycache__", ".claude",
    "venv", ".venv", "htmlcov",
    "documents", "documents_quarantine", "registry_documents", "downloads",
}

# 출력 경로로 보는 호출.
PRINT_FUNCS = {"print"}
LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical", "log"}

# 이 파일만 예외다. 금지 문자(U+2014)를 **일부러** 들고 있어야 검사를 할 수 있기 때문이다.
# 예외를 파일 하나로 좁혀 두면 "예외 목록이 늘어나며 규칙이 무력해지는" 흔한 실패를 막는다.
SELF = os.path.basename(__file__)

failures = []

# 파싱하지 못해 검사에서 빠진 파일. 비어 있어야 한다 — 조용히 건너뛴 파일이 있으면
# 이 가드는 "통과"를 보고하면서 실제로는 그 파일을 보지 않은 것이 된다.
SKIPPED = []


def check(name, actual, expected):
    ok = actual == expected
    print("[%s] %s: %r (expected %r)" % ("PASS" if ok else "FAIL", name, actual, expected))
    if not ok:
        failures.append(name)


def encodable(s):
    try:
        s.encode(CONSOLE_ENCODING)
        return True
    except UnicodeEncodeError:
        return False


def python_files():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn.endswith(".py"):
                yield os.path.join(dirpath, fn)


def _docstring_ids(tree):
    """docstring 노드 id 집합. docstring은 출력되지 않으므로 검사 대상이 아니다."""
    ids = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if body and isinstance(body[0], ast.Expr) and \
                isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
            ids.add(id(body[0].value))
    return ids


def _wrapper_print_functions(tree):
    """print()/logger.*()에 자신의 매개변수를 그대로 실어 보내는 "투명 출력 래퍼"
    함수 이름 -> {그 문자열이 실리는 매개변수 위치} 딕셔너리.

    2026-08-16 Sprint 133 신설(BUGS류). `cleanup_orphans_dryrun.py`가

        def head(t):
            print("\\n" + "=" * 74 + "\\n" + t + "\\n" + "=" * 74)
        ...
        head("... — ...")

    형태로 U+2014 EM DASH를 실제로 출력하다가 cp949 콘솔에서 죽었는데(재현 확인),
    아래 `output_literals()`는 원래 `print`/`logger.*` 호출에 **직접** 박힌 리터럴만
    봐서 `head("...")`처럼 한 단계 감싼 호출은 놓쳤다 — 이 스캔이 "통과"를 보고하는
    동안 실제로는 그 파일의 진짜 출력 경로를 보지 않고 있었다는 뜻이다(§0의 "SKIPPED
    없어야 한다"는 원칙과 같은 종류의 함정). 매개변수 이름이 print/logger 호출의
    인자(직접 또는 BinOp/JoinedStr 안)로 그대로 쓰이는 모듈 최상위 함수를 찾아 그
    함수도 "출력 경로"로 취급한다.
    """
    wrappers = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        param_names = [a.arg for a in node.args.args]
        if not param_names:
            continue
        printed_positions = set()
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue
            fn = sub.func
            is_print = isinstance(fn, ast.Name) and fn.id in PRINT_FUNCS
            is_log = isinstance(fn, ast.Attribute) and fn.attr in LOG_METHODS
            if not (is_print or is_log):
                continue
            for arg in sub.args:
                for name_node in ast.walk(arg):
                    if isinstance(name_node, ast.Name) and name_node.id in param_names:
                        printed_positions.add(param_names.index(name_node.id))
        if printed_positions:
            wrappers[node.name] = printed_positions
    return wrappers


def output_literals(path):
    """콘솔로 나갈 수 있는 문자열 리터럴을 (lineno, 값)으로 돌려준다.

    범위를 파일 종류에 따라 다르게 잡는다. 규칙을 실제 고장 경로에만 걸기 위해서다.

      test_*.py       **모든** 리터럴(docstring 제외).
                      이 저장소의 테스트는 `check(name, actual, expected)` 헬퍼가
                      이름과 값을 %s/%r로 전부 찍는다. 즉 print() 안에 없는 리터럴도
                      거의 전부 stdout으로 나간다 — print만 보면 그 대부분을 놓친다.

      그 외 소스       print()/logger.*() 호출에 직접 박힌 리터럴만.
                      API 응답 문자열(JSON, UTF-8 직렬화)까지 묶으면 콘솔과 무관한
                      문장에 제약을 거는 셈이 된다.

    f-string(JoinedStr)의 고정 부분도 ast.Constant로 잡혀 함께 검사된다.
    변수를 거쳐 들어오는 문자열은 정적으로 알 수 없다 — 그래서 §3/§4에 **실제로
    출력해 보는** 동작 검사를 따로 둔다.

    읽기는 반드시 `utf-8-sig`다. 이 저장소의 소스 68개에 UTF-8 BOM이 있고
    (`collect_documents.py` / `migrate_execute.py` / `api/v1/favorites.py` 등 운영 파일 포함),
    BOM이 붙은 소스를 `utf-8`로 읽어 `ast.parse()`에 넘기면
    `SyntaxError: invalid non-printable character U+FEFF`가 난다. 그것을 조용히
    건너뛰면 **검사한 척하면서 68개 파일을 빼먹는다.** 저장소의 다른 정적 검사
    (`test_schema_hygiene.py` / `test_crawl_exit_code.py` 등)가 이미 `utf-8-sig`를
    쓰고 있어 규약을 따른 것이다. 실패한 파일은 삼키지 않고 SKIPPED에 남긴다.
    """
    try:
        with io.open(path, encoding="utf-8-sig") as f:
            tree = ast.parse(f.read())
    except (SyntaxError, UnicodeDecodeError, OSError) as exc:
        SKIPPED.append("%s (%s: %s)" % (
            os.path.relpath(path, ROOT).replace("\\", "/"), type(exc).__name__, exc))
        return []

    docs = _docstring_ids(tree)
    is_test = os.path.basename(path).startswith("test_")

    found = []
    if is_test:
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                    and id(node) not in docs:
                found.append((node.lineno, node.value))
        return found

    wrapper_funcs = _wrapper_print_functions(tree)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        is_print = isinstance(fn, ast.Name) and fn.id in PRINT_FUNCS
        is_log = isinstance(fn, ast.Attribute) and fn.attr in LOG_METHODS
        is_wrapper = isinstance(fn, ast.Name) and fn.id in wrapper_funcs
        if is_wrapper:
            # 래퍼 호출은 문자열이 실리는 그 위치의 인자만 본다(다른 인자는 출력과
            # 무관할 수 있다 — head(t)처럼 매개변수가 하나뿐이면 사실상 전부지만,
            # 매개변수가 여럿인 래퍼에서 과탐하지 않도록 위치를 좁힌다).
            for pos in wrapper_funcs[fn.id]:
                if pos < len(node.args):
                    arg = node.args[pos]
                    for sub in ast.walk(arg):
                        if isinstance(sub, ast.Constant) and isinstance(sub.value, str) \
                                and id(sub) not in docs:
                            found.append((sub.lineno, sub.value))
            continue
        if not (is_print or is_log):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str) \
                    and id(sub) not in docs:
                found.append((sub.lineno, sub.value))
    return found


# ---------------------------------------------------------------------------
# 1. 저장소 전수 스캔 — 출력 문자열이 콘솔 인코딩으로 나갈 수 있는가
# ---------------------------------------------------------------------------
def test_all_output_literals_are_console_encodable():
    print("\n--- 1. 출력 문자열 리터럴 전수 스캔 (%s) ---" % CONSOLE_ENCODING)

    scanned_files = 0
    scanned_literals = 0
    offenders = []

    for path in python_files():
        if os.path.basename(path) == SELF:
            continue
        scanned_files += 1
        for lineno, value in output_literals(path):
            scanned_literals += 1
            if not encodable(value):
                bad = sorted({c for c in value if not encodable(c)})
                offenders.append("%s:%d %s" % (
                    os.path.relpath(path, ROOT).replace("\\", "/"),
                    lineno,
                    " ".join("U+%04X" % ord(c) for c in bad),
                ))

    # 스캐너가 실제로 무언가를 보고 있는지 먼저 확인한다. 0건이면 "전부 통과"가 아니라
    # 스캔이 망가진 것이다(경로 규칙 변경 등).
    check("스캔한 .py 파일이 있다", scanned_files > 0, True)
    check("스캔한 출력 리터럴이 있다", scanned_literals > 100, True)
    # 파싱 실패로 빠진 파일이 하나라도 있으면 아래 결과는 신뢰할 수 없다.
    check("파싱 실패로 건너뛴 파일 없음", SKIPPED, [])
    check("cp949로 못 내보내는 출력 리터럴 없음", offenders, [])

    print("   파일 %d개 / 출력 리터럴 %d개 검사" % (scanned_files, scanned_literals))
    if offenders:
        for o in offenders:
            print("     %s" % o)


# ---------------------------------------------------------------------------
# 2. 대체 문자 자체의 성질 — EM DASH는 불가, HORIZONTAL BAR는 가능
# ---------------------------------------------------------------------------
def test_replacement_character_is_valid():
    print("\n--- 2. 대체 문자(U+2015)가 실제로 안전한가 ---")

    check("U+2014 EM DASH는 cp949 불가", encodable(EM_DASH), False)
    check("U+2015 HORIZONTAL BAR는 cp949 가능", encodable(HORIZONTAL_BAR), True)
    check("U+2015의 cp949 바이트", HORIZONTAL_BAR.encode(CONSOLE_ENCODING), b"\xa1\xaa")

    # 한글은 cp949에 있다 — 이 테스트가 "한글을 쓰지 말라"는 뜻이 아님을 못박는다.
    check("한글은 cp949 가능", encodable("서울중앙지방법원 감정평가서"), True)


# ---------------------------------------------------------------------------
# 3. 실제 동작 — cp949 스트림에 정말 출력되는가 (정적 스캔이 놓치는 경로)
# ---------------------------------------------------------------------------
def _cp949_stream():
    return io.TextIOWrapper(io.BytesIO(), encoding=CONSOLE_ENCODING, newline="")


def test_print_actually_survives_cp949_stream():
    print("\n--- 3. cp949 스트림 실출력 동작 ---")

    # 수정 전 동작 재현: EM DASH는 실제로 예외를 던진다.
    raised = False
    stream = _cp949_stream()
    try:
        print("JWKS 조회 실패" + EM_DASH + "캐시로 검증", file=stream)
    except UnicodeEncodeError:
        raised = True
    check("EM DASH를 print하면 UnicodeEncodeError", raised, True)

    # 수정 후 동작: HORIZONTAL BAR는 통과하고 내용도 보존된다.
    raised = False
    stream = _cp949_stream()
    try:
        print("JWKS 조회 실패 " + HORIZONTAL_BAR + " 캐시로 검증", file=stream)
    except UnicodeEncodeError:
        raised = True
    check("HORIZONTAL BAR를 print하면 예외 없음", raised, False)

    stream.flush()
    stream.buffer.seek(0)
    written = stream.buffer.read().decode(CONSOLE_ENCODING)
    check("출력 내용이 보존된다", written.strip(), "JWKS 조회 실패 " + HORIZONTAL_BAR + " 캐시로 검증")


def test_logger_record_is_not_lost_on_cp949():
    """logger는 예외를 던지지 않는다 — 대신 **로그가 통째로 사라진다.** 그쪽을 검증한다."""
    print("\n--- 4. logger 경로: 로그 소실 여부 ---")

    def emit(message):
        stream = _cp949_stream()
        handler = logging.StreamHandler(stream)
        logger = logging.getLogger("test_console_encoding.%d" % id(message))
        logger.handlers = [handler]
        logger.propagate = False
        logger.setLevel(logging.INFO)
        # logging은 인코딩 실패를 삼키고 stderr로 트레이스백을 뱉는다. 그 소음을 죽인다.
        prev = logging.raiseExceptions
        logging.raiseExceptions = False
        try:
            logger.warning(message)
        finally:
            logging.raiseExceptions = prev
            handler.flush()
        stream.flush()
        stream.buffer.seek(0)
        return stream.buffer.read().decode(CONSOLE_ENCODING, errors="replace")

    lost = emit("PAYMENT_WEBHOOK_SECRET 미설정 " + EM_DASH + " 서명 검증 실패 처리")
    check("EM DASH 로그는 예외 없이 소실된다", lost, "")

    kept = emit("PAYMENT_WEBHOOK_SECRET 미설정 " + HORIZONTAL_BAR + " 서명 검증 실패 처리")
    check("HORIZONTAL BAR 로그는 남는다", HORIZONTAL_BAR in kept, True)
    check("로그 본문이 온전하다", "PAYMENT_WEBHOOK_SECRET 미설정" in kept, True)


# ---------------------------------------------------------------------------
# 5. 운영자가 봐야 하는 경고가 실제로 안전해졌는지 — 고쳤던 지점을 직접 지목
# ---------------------------------------------------------------------------
def test_known_operator_warnings_are_safe():
    print("\n--- 5. 수정 대상이었던 운영 경고 지점 ---")

    # Sprint 72에서 고친 파일들. 이 목록이 비면 검사가 무의미해지므로 존재도 확인한다.
    targets = [
        "api/auth.py",
        "api/v1/payment_logs.py",
        "api/v1/payment_providers.py",
        "api/v1/payments.py",
        "api/v1/search.py",
        "api/v1/state_machines.py",
        "api/v1/subscriptions.py",
        "test_beta_journey.py",
        "test_document_queue.py",
        "test_pipeline_integrity.py",
    ]

    missing = [t for t in targets if not os.path.exists(os.path.join(ROOT, t))]
    check("수정 대상 파일이 전부 존재한다", missing, [])

    still_bad = []
    for rel in targets:
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            continue
        for lineno, value in output_literals(path):
            if not encodable(value):
                still_bad.append("%s:%d" % (rel, lineno))
    check("해당 파일들의 출력 경로가 전부 안전하다", still_bad, [])

    # 이 저장소가 EM DASH를 **완전히 금지한 것은 아니다.** 주석·문서·API 응답은 그대로다.
    # 규칙의 범위를 잘못 넓히지 않았는지 확인한다(넓히면 불필요한 대량 수정을 부른다).
    with io.open(os.path.join(ROOT, "api/v1/payment_logs.py"), encoding="utf-8-sig") as f:
        payment_logs_src = f.read()
    check("API 응답 문자열의 EM DASH는 그대로 허용된다",
          EM_DASH in payment_logs_src, True)


def test_scan_scope_excludes_snapshots():
    """스캔 범위가 **지금 돌아가는 코드**만 담고 있는가 (BUGS #154).

    이 검사가 없으면 SKIP_DIRS 가 조용히 있으나 마나 한다 —
    범위가 넓어져도(사본을 검사) 좁아져도(0개를 검사) 둘 다 초록으로 보인다.
    """
    print(chr(10) + "--- 스캔 범위 ---")
    files = [os.path.relpath(p, ROOT).replace(os.sep, "/") for p in python_files()]
    leaked = sorted(f for f in files if f.startswith(".claude/") or "/.claude/" in f)
    check("★ 저장소 사본(.claude/worktrees)을 검사하지 않는다", leaked[:5], [])
    # 하한 — 제외가 과해서 0개를 훑고 조용히 통과하는 것을 막는다.
    check("검사 대상 .py 를 실제로 찾았다(검사가 공허하지 않다)", len(files) >= 120, True)
    print("    검사 대상 .py %d개" % len(files))


def run():
    test_scan_scope_excludes_snapshots()
    test_all_output_literals_are_console_encodable()
    test_replacement_character_is_valid()
    test_print_actually_survives_cp949_stream()
    test_logger_record_is_not_lost_on_cp949()
    test_known_operator_warnings_are_safe()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
