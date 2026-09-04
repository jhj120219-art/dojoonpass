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


# ---------------------------------------------------------------------------
# 이스케이프가 **제어문자로 굳은** 자리 (2026-08-20 Sprint 226 신설)
# ---------------------------------------------------------------------------
# 소스에 `\bfoo\b` 라고 쓰려던 것이 파일에 **0x08(백스페이스) 바이트**로 들어가는
# 사고가 있다. 도구를 거쳐 파일을 쓸 때 역슬래시가 한 겹 사라지면 그렇게 된다.
#
# 겉보기로는 알아채기 어렵다 — 에디터가 그 바이트를 거의 보여 주지 않고, 문법 오류도
# 아니다. 그런데 정규식은 "백스페이스 문자"를 찾게 되므로 **영원히 일치하지 않는다.**
#
# 실제 피해(2026-08-20 발견): `tests/source-contract.test.mjs` 의
#
#     assert.ok(!/<BS>formatPrice<BS>/.test(src), '마이페이지가 축약 표기를 씁니다')
#
# 이 단언은 `formatPrice` 가 다시 들어와도 **절대 실패하지 않는** 공허한 검사였다.
# 변이로 확인했다 — 결함을 주입하면 고친 판본은 잡고, 옛 판본은 **놓쳤다.**
#
# 정상적으로 이 바이트가 필요한 소스 파일은 없다. 그래서 0개를 고정한다.
FROZEN_ESCAPES = {
    0x00: r"\0", 0x07: r"\a", 0x08: r"\b", 0x0b: r"\v", 0x0c: r"\f", 0x1b: r"\e",
}

# 콘솔 인코딩과 무관하지만 **같은 사고**라 여기서 함께 본다(이 파일이 이미 소스를
# 바이트로 훑고 있고, 형제 검사와 제외 규칙을 공유하기 때문이다).
FROZEN_SCAN_EXTS = (".py", ".mjs", ".js", ".ts", ".tsx")


def _frozen_scan_files():
    out = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn.endswith(FROZEN_SCAN_EXTS):
                out.append(os.path.join(dirpath, fn))
    return sorted(out)


def test_no_escape_frozen_into_a_control_character():
    print("\n--- 이스케이프가 제어문자로 굳은 자리가 없는가 ---")
    files = _frozen_scan_files()
    # 하한 — 열거가 깨지면 0개를 훑고 조용히 통과한다.
    check("검사 대상 소스를 실제로 찾았다(검사가 공허하지 않다)", len(files) >= 80, True)

    hits = []
    for path in files:
        data = io.open(path, "rb").read()
        for code, shown in sorted(FROZEN_ESCAPES.items()):
            if bytes([code]) in data:
                rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
                hits.append("%s %s x%d" % (rel, shown, data.count(bytes([code]))))
    check("★ 제어문자로 굳은 이스케이프", hits[:5], [])

    # 검출기 자체 검증 — 진짜 바이트가 있으면 반드시 잡아야 하고,
    # 정상적인 두 글자 표기(역슬래시 + b)는 잡으면 안 된다.
    good = ("re.search(r'" + chr(92) + "bfoo" + chr(92) + "b', s)").encode("utf-8")
    bad = ("re.search(r'" + chr(8) + "foo" + chr(8) + "', s)").encode("utf-8")
    check("검출기 자체 검증: 굳은 제어문자를 잡는다",
          any(bytes([c]) in bad for c in FROZEN_ESCAPES), True)
    check("검출기 자체 검증: 정상 표기를 잡지 않는다",
          any(bytes([c]) in good for c in FROZEN_ESCAPES), False)
    print("    훑은 소스 %d개" % len(files))



# ---------------------------------------------------------------------------
# 배치/PowerShell 스크립트의 파일 인코딩 계약 (2026-08-26, `docs/BUGS.md` #221)
# ---------------------------------------------------------------------------
#
# 이 파일의 나머지 검사는 **파이썬이 콘솔에 쓰는 글자**를 본다. 이 검사는 한 칸 위
# — **셸이 스크립트 파일 자체를 읽는 순간**을 본다. 둘은 다른 사고다.
#
#   `.bat`  cmd 는 시스템 OEM 코드페이지(여기서는 cp949)로 읽는다. UTF-8 한글
#           바이트를 cp949 로 읽으면 2바이트 조합이 **뒤따르는 ASCII 를 트레일
#           바이트로 삼켜** 토큰 경계가 밀린다. 그러면 주석 한가운데에서 파싱이
#           재개되고 남은 조각이 **명령으로 실행된다.**
#           BOM 은 해법이 아니라 악화다(`'癤?echo'` 가 명령이 된다, BUGS #219).
#           cp949 저장도 불가하다(em-dash 를 인코딩하지 못한다).
#           => 남는 규칙은 하나, **ASCII 로 쓴다.**
#
#   `.ps1`  Windows PowerShell 5.1 은 **BOM 이 없으면 ANSI 로 읽는다.**
#           그래서 여기서는 반대로 **BOM 이 있어야** 한글이 안전하다.
#
# 2026-08-26 실측 (작업 사본 + 스텁, `chcp 949`, 끝까지 실행):
#
#     HEAD  run_daily.bat             exit=255, cmd stderr 7줄, daily_run.log **없음**
#           run_doc_worker.bat        exit=0,   cmd stderr 7줄
#           run_priority_refresh.bat  exit=0,   cmd stderr 5줄
#     수정후 셋 다                     exit=0,   cmd stderr **0줄**, 마커 정상
#
# `run_daily.bat` 의 255 가 특히 나쁘다 — **성공 경로에서** 종료 코드가 실패가 되고
# `[SUCCESS]`/`[FAILED]` 어느 마커도 남지 않는다. 이 저장소가 오래 싸워 온
# "실패 은폐"(BUGS #47)의 정확한 거울상이다.
SHELL_SCRIPT_DIRS_SKIPPED = (".claude", "node_modules", ".next", ".git")


def _shell_scripts(suffix):
    """저장소가 **실제로 쓰는** 셸 스크립트만 훑는다.

    `.claude/worktrees/` 아래에는 옛 worktree 의 사본이 남아 있다. 그것까지 세면
    고칠 수 없는 과거 파일 때문에 이 검사가 영구 red 가 된다 - 그러면 사람이
    검사를 끄게 되고, 그게 가드를 죽이는 흔한 경로다.
    """
    found = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SHELL_SCRIPT_DIRS_SKIPPED]
        for fn in filenames:
            if fn.lower().endswith(suffix):
                found.append(os.path.join(dirpath, fn))
    return sorted(found)


def test_batch_files_are_ascii():
    """`.bat` 는 ASCII 만, `.ps1` 는 비ASCII 를 쓰려면 BOM 을 가진다."""
    print("\n--- 8. 셸 스크립트 파일 인코딩 계약 (BUGS #221) ---")

    bats = _shell_scripts(".bat")
    # 검사가 공허하지 않다는 것부터 — 파일을 못 찾았는데 통과하면 아무 뜻이 없다.
    check("훑을 .bat 를 찾았다(검사가 공허하지 않다)", len(bats) >= 3, True)

    for path in bats:
        rel = os.path.relpath(path, ROOT)
        raw = io.open(path, "rb").read()
        check("%s: BOM 이 없다" % rel, raw.startswith(b"\xef\xbb\xbf"), False)
        try:
            raw.decode("ascii")
            ok, detail = True, ""
        except UnicodeDecodeError as e:
            # 어느 줄인지까지 알려 준다 - "어딘가 한글이 있다"는 고치기 어렵다.
            head = raw[:e.start]
            ok = False
            detail = "L%d 부근: %r" % (head.count(b"\n") + 1, raw[e.start:e.start + 20])
        check("%s: ASCII 로만 이루어져 있다%s" % (rel, (" (%s)" % detail) if detail else ""),
              ok, True)

        # ★ 왜 ASCII 여야 하는지를 **직접** 확인한다. 규칙만 적어 두면 다음 사람이
        #   "주석인데 뭐 어때" 로 되돌린다 - cmd 가 보는 바이트가 우리가 쓴 것과
        #   같은지를 그 자리에서 재는 편이 낫다.
        as_cmd_sees_it = raw.decode("cp949", errors="replace")
        as_written = raw.decode("utf-8", errors="replace")
        check("%s: cmd 가 읽는 내용이 우리가 쓴 내용과 같다(cp949 == utf-8)" % rel,
              as_cmd_sees_it == as_written, True)

    for path in _shell_scripts(".ps1"):
        rel = os.path.relpath(path, ROOT)
        raw = io.open(path, "rb").read()
        try:
            raw.decode("ascii")
            continue                      # ASCII 면 BOM 유무와 무관하게 안전하다
        except UnicodeDecodeError:
            pass
        # Windows PowerShell 5.1 은 BOM 이 없으면 ANSI 로 읽는다.
        check("%s: 비ASCII 를 쓰므로 UTF-8 BOM 이 있어야 한다" % rel,
              raw.startswith(b"\xef\xbb\xbf"), True)

    # ★ 검출기 자체 검증 - known-bad 를 정말 잡는가, known-good 을 잘못 잡지 않는가.
    #   (이 저장소가 반복해 겪은 "가드가 자기 자신만 검사한다"를 여기서도 막는다)
    bad = "REM 한글 주석\r\necho ok\r\n".encode("utf-8")
    good = "REM ascii comment\r\necho ok\r\n".encode("utf-8")
    def _is_ascii(b):
        try:
            b.decode("ascii"); return True
        except UnicodeDecodeError:
            return False
    check("검출기 자체 검증: 한글 주석이 든 .bat 를 잡는다", _is_ascii(bad), False)
    check("검출기 자체 검증: ASCII 주석은 잡지 않는다", _is_ascii(good), True)
    check("검출기 자체 검증: cp949 대조가 known-bad 에서 어긋난다",
          bad.decode("cp949", errors="replace") == bad.decode("utf-8", errors="replace"),
          False)
    print("    훑은 .bat %d개" % len(bats))


def run():
    test_scan_scope_excludes_snapshots()
    test_all_output_literals_are_console_encodable()
    test_replacement_character_is_valid()
    test_print_actually_survives_cp949_stream()
    test_logger_record_is_not_lost_on_cp949()
    test_known_operator_warnings_are_safe()
    test_no_escape_frozen_into_a_control_character()
    test_batch_files_are_ascii()
    test_stdout_is_not_replaced_at_import_time()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL TESTS PASSED")
    return 0


# ---------------------------------------------------------------------------
# import 부작용으로 `sys.stdout` 을 갈아치우지 않는가 (2026-09-04 신설)
# ---------------------------------------------------------------------------
def test_stdout_is_not_replaced_at_import_time():
    """콘솔 인코딩 고정은 **`__main__` 안에서만** 한다.

    ## 무슨 일이 있었나 (2026-09-04 실측)

    세 스크립트가 모듈 최상단에서 이렇게 하고 있었다:

        if hasattr(sys.stdout, "buffer"):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", ...)

    의도는 맞다(cp949 콘솔에서 죽지 않게). 문제는 **자리**다. 최상단에 두면
    **그 모듈을 import 하는 것만으로 `sys.stdout` 이 교체되고**, 교체되는 순간
    옛 스트림의 버퍼에 쌓여 있던 출력은 아무도 flush 하지 않으므로 사라진다.

    `test_doc_path_safety.py` 가 경로 생성기 대조에 `backfill_doc_raw` 를 넣자
    그 앞 §1~§6 의 출력이 화면에서 통째로 사라졌다. 검사는 전부 돌고 통과했는데
    **보고만 없어져** 회귀 실행기의 단언 집계가 175 -> 122 로 떨어졌다.
    실패가 아니라 **검사 결과가 조용히 줄어드는 것**이라 더 나쁘다 — 이 파일이
    막으려는 "로그 라인이 조용히 소실되는" 사고와 같은 계열이다.

    이 저장소는 로그 핸들러에 대해 이미 같은 규칙을 세워 두었다(BUGS #192):
    *"운영 파일 로그는 `if __name__ == '__main__':` 안에서만 붙인다."*
    `sys.stdout` 도 같은 종류의 전역 자원이다.

    ## 무엇을 보나

    `sys.stdout = ...` 대입이 **최상위 문(statement)** 으로 있으면 위반이다.
    함수 안(`def _force_utf8_stdout(): ...`)에 있는 것은 정상이다 — 부르는 쪽이
    `__main__` 인지 정하기 때문이다.
    """
    import ast
    import subprocess as _sp

    print("\n--- import 만으로 sys.stdout 을 바꾸지 않는가 ---")
    root = os.path.dirname(os.path.abspath(__file__))
    try:
        out = _sp.run(["git", "ls-files", "--exclude-standard", "*.py"], cwd=root,
                      capture_output=True, text=True, timeout=30)
        files = ([f for f in out.stdout.split()
                  if f.endswith(".py") and "-DESKTOP-" not in f]
                 if out.returncode == 0 else [])
    except (OSError, _sp.SubprocessError):
        files = []
    if len(files) < 20:
        files = sorted(n for n in os.listdir(root)
                       if n.endswith(".py") and "-DESKTOP-" not in n)
    check("훑을 파일을 실제로 찾았다 (%d개)" % len(files), len(files) >= 20, True)

    def toplevel_stdout_assign(tree):
        """최상위(모듈/if/try 블록 포함, 함수 밖)에서 sys.stdout 에 대입하는 줄."""
        hits = []

        def walk(body):
            for node in body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                     ast.ClassDef)):
                    continue                      # 함수 안은 정상이다
                if isinstance(node, ast.Assign):
                    for t in node.targets:
                        if (isinstance(t, ast.Attribute) and t.attr == "stdout"
                                and isinstance(t.value, ast.Name)
                                and t.value.id == "sys"):
                            hits.append(node.lineno)
                for field in ("body", "orelse", "finalbody"):
                    inner = getattr(node, field, None)
                    if isinstance(inner, list):
                        walk(inner)
        walk(tree.body)
        return hits

    offenders = []
    scanned = 0
    for rel in files:
        path = os.path.join(root, rel.replace("/", os.sep))
        try:
            tree = ast.parse(io.open(path, encoding="utf-8-sig").read())
        except (OSError, SyntaxError):
            continue
        scanned += 1
        # `if __name__ == "__main__":` 안의 대입은 정상이다 - 그 블록만 걷어낸다.
        tree.body = [n for n in tree.body if not _is_main_guard(n)]
        for lineno in toplevel_stdout_assign(tree):
            offenders.append("%s:%d" % (rel, lineno))

    check("실제로 훑었다 (%d개)" % scanned, scanned >= 20, True)
    if offenders:
        print("   ★ import 만으로 sys.stdout 을 교체하는 곳:")
        for o in sorted(set(offenders)):
            print("      %s" % o)
        print("   함수로 감싸고 `if __name__ == \"__main__\":` 에서 부르십시오"
              " (예: backfill_doc_raw._force_utf8_stdout)")
    check("최상위에서 sys.stdout 을 갈아치우는 곳이 없다", sorted(set(offenders)), [])

    # 탐지기 자기 증명 - 합성 입력에서는 반드시 잡히고, 정상 형태는 잡히지 않는다.
    bad_src = ('import sys, io\n'
               'if hasattr(sys.stdout, "buffer"):\n'
               '    sys.stdout = io.TextIOWrapper(sys.stdout.buffer)\n')
    good_src = ('import sys, io\n'
                'def fix():\n'
                '    sys.stdout = io.TextIOWrapper(sys.stdout.buffer)\n')
    check("탐지기가 최상위 교체를 잡는다",
          bool(toplevel_stdout_assign(ast.parse(bad_src))), True)
    check("함수 안의 교체는 잡지 않는다(오탐 없음)",
          bool(toplevel_stdout_assign(ast.parse(good_src))), False)
    main_src = ('import sys, io\n'
                'if __name__ == "__main__":\n'
                '    sys.stdout = io.TextIOWrapper(sys.stdout.buffer)\n')
    _t = ast.parse(main_src)
    _t.body = [n for n in _t.body if not _is_main_guard(n)]
    check("`__main__` 안의 교체는 잡지 않는다(오탐 없음)",
          bool(toplevel_stdout_assign(_t)), False)


def _is_main_guard(node):
    """`if __name__ == "__main__":` 노드인가."""
    import ast
    if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
        return False
    left = node.test.left
    if not (isinstance(left, ast.Name) and left.id == "__name__"):
        return False
    return any(isinstance(c, ast.Constant) and c.value == "__main__"
               for c in node.test.comparators)


if __name__ == "__main__":
    sys.exit(run())
