"""
DB 스키마/커넥션 위생 회귀 테스트 (jose 불필요 — storage.database만 import).

test_api_regression.py를 정적 감사하며 발견한, 실행 전에는 드러나지 않았을 두 결함의 회귀
방어다(2026-08-08 Sprint 31):

    1) get_connection(enforce_foreign_keys=False) 시그니처 — 23번 섹션이 이 키워드 인자를
       호출하는데 예전 storage/database.py:get_connection()은 인자를 받지 않았다.
    2) favorites/search_presets의 deleted_at/deleted_by 컬럼 — 28번 섹션(Soft Delete,
       CTO 승인 10건 #6)이 검증하는데 Migration 010~016 복구 당시에는 코드 참조가 없다는
       이유로 의도적으로 빠뜨렸었다(실제로는 migration **016**에 함께 들어 있다 —
       2026-08-11 Sprint 51 확인. 과거 기록의 "017"은 잘못된 번호였고, 017은 Sprint 51에서
       document_collect_failures 부트스트랩 누락 복구용으로 새로 만들어졌다).

    python test_schema_hygiene.py
"""
import sys
import os
import sqlite3
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import storage.database as dbmod

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


def test_get_connection_fk_parameter():
    print("\n--- 1. get_connection(enforce_foreign_keys=...) ---")
    c1 = dbmod.get_connection()
    check("default (no arg) has FK ON", c1.execute("PRAGMA foreign_keys").fetchone()[0], 1)
    c1.close()

    c2 = dbmod.get_connection(enforce_foreign_keys=True)
    check("explicit True has FK ON", c2.execute("PRAGMA foreign_keys").fetchone()[0], 1)
    c2.close()

    c3 = dbmod.get_connection(enforce_foreign_keys=False)
    check("explicit False has FK OFF", c3.execute("PRAGMA foreign_keys").fetchone()[0], 0)
    c3.close()


def test_soft_delete_columns():
    print("\n--- 2. soft delete columns (favorites/search_presets) ---")
    conn = dbmod.get_connection()
    try:
        for table in ("favorites", "search_presets"):
            cols = [r[1] for r in conn.execute("PRAGMA table_info(%s)" % table)]
            check("%s has deleted_at" % table, "deleted_at" in cols, True)
            check("%s has deleted_by" % table, "deleted_by" in cols, True)
    finally:
        conn.close()


def test_migration_history_complete():
    print("\n--- 3. migration_history completeness (디스크 .sql 전수) ---")
    conn = dbmod.get_connection()
    try:
        applied = {r[0] for r in conn.execute("SELECT filename FROM migration_history")}
        expected_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "storage", "migrations")
        on_disk = {f for f in os.listdir(expected_dir) if f.endswith(".sql")}
        missing = sorted(on_disk - applied)
        check("every .sql file on disk is recorded as applied", missing, [])
    finally:
        conn.close()


def test_requirements_covers_all_imports():
    """requirements.txt가 소스의 실제 third-party import를 전부 덮는가.

    2026-08-11 Sprint 54 신설. 이 저장소에는 8일 동안 의존성 목록이 아예 없었고, 그 사이
    크롤 환경(Anaconda)이 사라지면서 **무엇을 다시 깔아야 하는지조차 알 수 없는 상태**가
    됐다. requirements.txt를 만든 것으로 끝내면 다음 import가 추가되는 순간 똑같이 어긋난다.
    그래서 목록을 사람이 관리하는 대신 **소스에서 매번 다시 도출해 비교**한다.
    """
    import ast

    print("\n--- 4. requirements.txt <-> 소스 import 일치 ---")
    root = os.path.dirname(os.path.abspath(__file__))
    skip_dirs = {".next", "node_modules", ".git", "__pycache__", ".venv", "venv", "logs", "data"}

    # 저장소 내부 모듈(로컬 패키지/스크립트)은 third-party가 아니다.
    local = set()
    for entry in os.listdir(root):
        path = os.path.join(root, entry)
        if os.path.isdir(path) and entry not in skip_dirs:
            local.add(entry)
        elif entry.endswith(".py"):
            local.add(entry[:-3])

    # ★ **저장소에 실제로 들어가는 .py만** 센다 (2026-08-13 Sprint 99).
    #
    #   예전에는 파일시스템을 그냥 훑었다. 그래서 `.gitignore` 대상인 로컬 실험 스크립트까지
    #   "소스"로 셌고, 이 검사는 **다른 환경에는 존재하지도 않는 집합**을 기준으로 통과하고
    #   있었다. 즉 이 검사 자체가 false success였다.
    #
    #   실측(Sprint 99): `.gitignore`의 `step*.py`에 걸리는 파일이 **65개** 있고, 그중
    #   `step8_verify.py`만 `requests`를 import한다. 그 65개를 빼고 돌리면(=fresh clone)
    #
    #       [FAIL] 목록에만 있고 소스에서 안 쓰는 항목 없음: ['requests']
    #
    #   즉 **새로 clone한 환경에서는 이 검사가 깨진다.** 로컬에서만 통과하고 CI에서 깨지는,
    #   가장 알아채기 어려운 종류다.
    #
    #   기준을 `git`에 맡긴다 — `--cached`(추적 중) + `--others --exclude-standard`
    #   (아직 추적 안 되지만 무시 대상도 아닌 새 파일). 무시 대상만 정확히 빠진다.
    #   양방향 모두에 필요하다: 무시된 스크립트가 목록에 없는 걸 import하면 반대로
    #   있지도 않은 누락이 보고된다.
    py_files = []
    try:
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30,
        )
        if out.returncode == 0:
            for rel in out.stdout.splitlines():
                if not rel.endswith(".py"):
                    continue
                if rel.split("/", 1)[0] in skip_dirs:
                    continue
                path = os.path.join(root, rel.replace("/", os.sep))
                if os.path.isfile(path):
                    py_files.append(path)
    except Exception:
        py_files = []

    if not py_files:
        # git이 없거나 저장소가 아니면 예전 방식으로 되돌린다 — 검사를 아예 잃는 것보다는 낫다.
        print("    [주의] git 파일 목록을 쓸 수 없어 파일시스템 전수로 대체한다"
              " (무시된 로컬 스크립트가 섞일 수 있음)")
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in skip_dirs]
            py_files += [os.path.join(dirpath, f) for f in filenames if f.endswith(".py")]

    # import 최상위 이름 -> pip 배포판 이름. 둘이 다른 경우만 적는다.
    DIST_NAME = {
        "dotenv": "python-dotenv",
        "jose": "python-jose",
        "webdriver_manager": "webdriver-manager",
        "yaml": "pyyaml",
        "bs4": "beautifulsoup4",
        "PIL": "pillow",
    }

    imported = {}
    parse_failures = []
    for path in py_files:
        try:
            with open(path, encoding="utf-8-sig", errors="replace") as fh:
                tree = ast.parse(fh.read())
        except SyntaxError as exc:
            parse_failures.append("%s: %s" % (os.path.relpath(path, root), exc.msg))
            continue
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:  # 상대 import는 항상 로컬
                    continue
                if node.module:
                    names = [node.module]
            for name in names:
                top = name.split(".")[0]
                if top in local or top in sys.stdlib_module_names:
                    continue
                imported.setdefault(top, set()).add(os.path.relpath(path, root))

    # .py가 파싱조차 안 되면 그 파일의 import는 조용히 빠진다 -> 검사에 구멍이 생긴다.
    check("모든 .py가 파싱된다(구멍 없는 전수 검사)", parse_failures, [])

    req_path = os.path.join(root, "requirements.txt")
    check("requirements.txt가 존재한다", os.path.exists(req_path), True)
    if not os.path.exists(req_path):
        return

    listed = set()
    with open(req_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            # "python-jose[cryptography]==3.5.0" -> "python-jose"
            for sep in ("==", ">=", "<=", "~=", ">", "<", "!=", "["):
                if sep in line:
                    line = line.split(sep, 1)[0]
            listed.add(line.strip().lower().replace("_", "-"))

    missing = sorted(
        "%s (%s)" % (mod, sorted(files)[0])
        for mod, files in imported.items()
        if DIST_NAME.get(mod, mod).lower().replace("_", "-") not in listed
    )
    check("소스가 import하는 third-party가 전부 목록에 있다", missing, [])

    # 반대 방향: 목록에만 있고 아무도 안 쓰는 항목은 "설치했는데 왜 필요한지 모르는" 상태를 만든다.
    used_dists = {DIST_NAME.get(m, m).lower().replace("_", "-") for m in imported}

    # ── httpx: 예외가 아니라 **강제되는 요구사항**으로 다룬다 (2026-08-14) ──────
    #
    # 예전에는 여기서 `- {"httpx"}`로 조용히 빼기만 했다("import 스캔에 안 잡힐 수 있다").
    # 그러면 검사가 **한 방향만** 본다 — 누가 requirements 에서 httpx 를 지워도
    # `stale`이 비어 통과한다. 실제로 지우기 쉬운 항목이다: 소스 전체에서
    # `import httpx`가 **0건**이라 "안 쓰는 의존성"처럼 보인다(2026-08-14 전수 확인).
    #
    # 그런데 지우면 TestClient 기반 회귀가 통째로 못 돈다. 실측 근거:
    #
    #   from fastapi.testclient import TestClient  -> sys.modules 에 httpx 적재  True
    #   import api_server (운영 경로)               -> httpx 적재                False
    #
    # 즉 **테스트 전용이지만 없어서는 안 되는** 의존성이다. 그래서 빼는 대신
    # "반드시 있어야 한다"를 직접 단언하고, 그 근거(TestClient 사용 테스트가 실재함)도
    # 함께 확인한다. 근거가 사라지면(TestClient 를 아무도 안 쓰게 되면) 그때 다시 판단한다.
    #
    # ★ starlette 이 `httpx` 대신 `httpx2` 를 권고하는 경고를 낸다(deprecated).
    #   전환은 starlette 업그레이드와 함께 해야 하므로 지금 버전만 바꾸지 않는다 —
    #   자세한 근거는 `requirements.txt` 의 httpx 주석 참고.
    tc_users = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            fp = os.path.join(dirpath, fn)
            try:
                with open(fp, encoding="utf-8-sig") as fh:
                    if "TestClient" in fh.read():
                        tc_users.append(os.path.relpath(fp, root))
            except OSError:
                continue

    check_true("httpx 가 requirements 에 있다(TestClient 회귀의 전제)",
               "httpx" in listed,
               "소스가 직접 import 하지 않아 '안 쓰는 의존성'처럼 보이지만, 지우면 "
               "TestClient 기반 테스트가 전부 실행되지 않는다")
    check_true("httpx 가 필요한 근거가 실재한다(TestClient 사용 파일 존재)",
               len(tc_users) > 0, tc_users)
    print("   TestClient 사용 파일 %d개 -> httpx 필수" % len(tc_users))

    stale = sorted(listed - used_dists - {"httpx"})
    check("목록에만 있고 소스에서 안 쓰는 항목 없음", stale, [])

    print("   소스에서 발견한 third-party %d개: %s" % (len(imported), ", ".join(sorted(imported))))


# ---------------------------------------------------------------------------
# 5. ErrorCode: 정의 <-> 문서 <-> 실제 방출 3자 대조 (2026-08-13 Sprint 72 신설)
#
# `docs/ERROR_CODES.md`는 "이 문서가 아니라 코드가 기준"이라고 못박고 40개를 나열한다.
# 그런데 **정의됐다는 것과 실제로 응답에 실린다는 것은 다르다.** 실측하니 40개 중 19개만
# 방출되고 21개는 어디서도 쓰이지 않았다.
#
# 이유는 이 저장소에 실패 응답이 두 가지 형태로 있기 때문이고, 그것 자체는 의도된 상태다:
#
#   error_response(code, msg)  -> HTTP 200 + {success:false, error:"CODE", message:...}
#                                 payments / search_presets / registry / favorites 4개 파일
#   raise HTTPException(...)   -> HTTP 4xx/5xx + {"detail": "..."}  (코드 없음)
#                                 auth / admin / subscriptions / item / search
#
# `api/auth.py:fail()`의 주석이 그 판단을 이미 적어 뒀다 — "코드가 붙지 않은 기존 호출부를
# 억지로 특정 코드로 몰아넣으면 오히려 오해를 부른다". 그래서 이 검사는 **미방출 코드를
# 결함으로 보지 않는다.** 대신 지금의 경계를 그대로 고정해서 다음 두 가지를 잡는다:
#
#   (1) 새 코드를 enum에 넣고 문서에 안 적는 것 / 문서에만 있고 정의가 없는 것
#   (2) 방출되던 코드가 조용히 사라지거나, 문서 없이 새로 방출되기 시작하는 것
#
# 프런트(`src/lib/api.ts:ERROR_CODES`)가 분기에 쓰는 값이라 (2)는 화면 동작에 직결된다.
# ---------------------------------------------------------------------------

# 현재 실제로 응답에 실리는 코드. 늘리거나 줄일 때는 docs/ERROR_CODES.md도 함께 고친다.
EMITTED_ERROR_CODES = {
    # api/v1/payments.py
    "PAY_INVALID_TYPE", "PAY_INVALID_PLAN", "PAY_INVALID_BILLING_CYCLE",
    "PAY_AMOUNT_MISMATCH", "PAY_NO_TARGET_REQUEST", "PAY_ALREADY_PROCESSED",
    "PAY_FAILED", "PAY_NOT_FOUND", "PAY_INVALID_TRANSITION",
    # api/v1/search_presets.py
    "SEARCH_PRESET_NAME_REQUIRED", "SEARCH_PRESET_NAME_TOO_LONG",
    "SEARCH_PRESET_TOO_LARGE", "SEARCH_PRESET_LIMIT_EXCEEDED", "SEARCH_PRESET_NOT_FOUND",
    # api/v1/registry.py
    "REGISTRY_SUBSCRIPTION_REQUIRED", "REGISTRY_NOT_COMPLETED", "REGISTRY_DOCUMENT_NOT_FOUND",
    # api/v1/favorites.py
    "FAVORITE_ALREADY_EXISTS", "FAVORITE_NOT_FOUND",
}


def _error_code_names(root):
    """api/constants.py:ErrorCode에 정의된 이름들."""
    import ast

    path = os.path.join(root, "api", "constants.py")
    with open(path, encoding="utf-8-sig") as fh:
        tree = ast.parse(fh.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "ErrorCode":
            return [st.targets[0].id for st in node.body
                    if isinstance(st, ast.Assign) and isinstance(st.targets[0], ast.Name)]
    return []


def test_error_codes_defined_documented_emitted():
    print("\n--- 5. ErrorCode 정의/문서/방출 대조 ---")
    import re

    root = os.path.dirname(os.path.abspath(__file__))

    defined = _error_code_names(root)
    check("ErrorCode가 정의돼 있다", len(defined) > 0, True)
    check("정의에 중복이 없다", len(defined), len(set(defined)))
    defined_set = set(defined)

    # (1) 문서 대조 — 문서는 표 형식이라 `CODE` 백틱 안에 들어 있다.
    doc_path = os.path.join(root, "docs", "ERROR_CODES.md")
    check("ERROR_CODES.md가 존재한다", os.path.exists(doc_path), True)
    with open(doc_path, encoding="utf-8-sig") as fh:
        doc = fh.read()

    # 코드는 표의 **첫 칸**에만 온다. 둘째 칸(의미)에는 `SUPABASE_JWT_SECRET`,
    # `ADMIN_API_KEY` 같은 환경변수 이름이 들어 있어, 백틱만 보고 긁으면 그것들이
    # "정의되지 않은 유령 코드"로 잡힌다(실제로 잡혔다). 행 구조로 판별한다.
    #
    # 첫 칸이라도 "형식" 절의 접두사 표(`AUTH` / `PAY` / ...)는 코드가 아니다.
    # 문서가 스스로 정한 형식이 `<DOMAIN>_<SNAKE_CASE>`이므로 밑줄 유무로 정확히 갈린다.
    doc_codes = {c for c in re.findall(r"^\|\s*`([A-Z][A-Z0-9_]{3,})`\s*\|", doc, re.M)
                 if "_" in c}

    check("정의된 코드가 전부 문서에 있다", sorted(defined_set - doc_codes), [])
    check("문서의 코드가 전부 정의돼 있다", sorted(doc_codes - defined_set), [])

    # (2) 방출 대조 — api/ 안에서 ErrorCode.X 로 참조되는 것이 실제 방출이다.
    emitted = set()
    for dirpath, dirnames, filenames in os.walk(os.path.join(root, "api")):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fn in filenames:
            if not fn.endswith(".py") or fn == "constants.py":
                continue
            with open(os.path.join(dirpath, fn), encoding="utf-8-sig") as fh:
                emitted |= set(re.findall(r"ErrorCode\.([A-Z0-9_]+)", fh.read()))

    check("방출되는 코드가 전부 정의돼 있다", sorted(emitted - defined_set), [])
    check("방출 집합이 고정된 목록과 같다(신규 방출)", sorted(emitted - EMITTED_ERROR_CODES), [])
    check("방출 집합이 고정된 목록과 같다(사라진 방출)", sorted(EMITTED_ERROR_CODES - emitted), [])

    # 프런트가 분기에 쓰는 코드는 반드시 실제로 방출돼야 한다 — 아니면 죽은 분기다.
    api_ts = os.path.join(root, "src", "lib", "api.ts")
    if os.path.exists(api_ts):
        with open(api_ts, encoding="utf-8-sig") as fh:
            ts = fh.read()
        block = re.search(r"ERROR_CODES\s*=\s*\{(.*?)\}", ts, re.S)
        front_codes = set(re.findall(r"([A-Z][A-Z0-9_]{3,})\s*:", block.group(1))) if block else set()
        check("프런트가 분기하는 코드가 실제로 방출된다",
              sorted(front_codes - emitted), [])
        print("   프런트 분기 코드 %d개" % len(front_codes))

    print("   정의 %d / 문서 %d / 실제 방출 %d (미방출 %d ― 의도된 상태, 위 주석 참고)"
          % (len(defined_set), len(defined_set & doc_codes), len(emitted),
             len(defined_set - emitted)))


# ---------------------------------------------------------------------------
# 6. storage/의 실동작 소스가 실제로 git에 추적되는가 (2026-08-13 Sprint 75 신설)
#
# 예전에는 `.gitignore`에 `storage/` 한 줄이 있었다. 의도는 크롤 데이터 산출물 제외였지만,
# 같은 디렉터리에 있는 **실동작 소스까지 통째로 빠졌다**:
#
#     storage/database.py          모든 API 라우트가 쓰는 DB 커넥션/큐 로직
#     storage/migrate_v4_1.py      v4.1 스키마 생성
#     storage/migrations/*.sql     001~018 마이그레이션 전부
#
# 이 사고의 성질이 나쁘다 - **파일은 디스크에 그대로 있으므로 아무도 눈치채지 못한다.**
# 로컬에서는 전부 정상 동작하고, 새로 clone한 환경에서만 스키마가 통째로 사라진다.
# 실제로 `docs/search-engine.md`와 `docs/crawler.md`는 그 상태를 보고
# "storage/database.py가 저장소에 없다"고 서술했고, 그 서술이 오래 남아 있었다.
#
# 2026-08-11 Sprint 51에 규칙이 정밀화됐다(`storage/*` + `!storage/*.py` +
# `!storage/migrations/*.sql`). 이 검사는 그 정밀화가 되돌아가는 것을 막는다.
#
# 검출 원리를 정확히 적어 둔다(그래야 이 검사를 과신하지 않는다).
# `git ls-files`는 **인덱스**를 읽으므로, 이미 추적 중인 파일은 `.gitignore`를 되돌려도
# 계속 추적된다. 따라서 이 검사가 실제로 잡는 것은 아래 두 가지다.
#
#   (a) 새 파일이 추적되지 않는 경우 - `.gitignore`를 `storage/`로 되돌린 뒤 새 마이그레이션
#       (019_*.sql)을 추가하면 그 파일만 조용히 빠진다. **가장 현실적인 재발 경로다**
#       (실제로 이 시나리오로 검출을 확인했다).
#   (b) 기존 파일이 추적에서 빠지는 경우 - `git rm --cached -r storage/`.
#       원래 사고가 일어난 방식이다.
#
# 둘 다 "로컬에서는 멀쩡히 동작하고 새로 clone한 환경에서만 터지는" 형태라
# 사람 눈으로는 거의 잡히지 않는다.
#
# (2026-08-13 Sprint 75에 문서 3곳의 stale 서술도 함께 정정했다.)
# ---------------------------------------------------------------------------
def test_storage_sources_are_tracked():
    print("\n--- 6. storage/ 실동작 소스가 git에 추적되는가 ---")
    import subprocess

    root = os.path.dirname(os.path.abspath(__file__))
    try:
        out = subprocess.run(["git", "ls-files", "storage/"], cwd=root,
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        print("[SKIP] git을 실행할 수 없다 (%s) - 추적 검사 생략" % type(exc).__name__)
        return
    if out.returncode != 0:
        print("[SKIP] git 저장소가 아니다 - 추적 검사 생략")
        return

    tracked = {line.strip().replace("\\", "/") for line in out.stdout.splitlines() if line.strip()}

    # 디스크에 있는 실동작 소스가 전부 추적되고 있는가.
    on_disk = set()
    for dirpath, dirnames, filenames in os.walk(os.path.join(root, "storage")):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fn in filenames:
            if fn.endswith(".py") or fn.endswith(".sql"):
                rel = os.path.relpath(os.path.join(dirpath, fn), root).replace("\\", "/")
                on_disk.add(rel)

    check_true("storage/에 소스가 존재한다", len(on_disk) > 0, on_disk)
    missing = sorted(on_disk - tracked)
    check("디스크의 storage/ 소스가 전부 추적된다", missing, [])

    # 핵심 파일은 이름으로 직접 확인한다 - 위 검사가 통째로 비어도 여기서 잡힌다.
    for must in ("storage/database.py", "storage/migrate_v4_1.py"):
        check_true("%s 가 추적된다" % must, must in tracked,
                   "추적 목록에 없다 - .gitignore가 되돌아갔는지 확인하라")

    sql_tracked = sorted(t for t in tracked if t.endswith(".sql"))
    check_true("마이그레이션 .sql이 추적된다(%d개)" % len(sql_tracked),
               len(sql_tracked) >= 18,
               "새로 clone하면 스키마를 만들 수 없다: %s" % sql_tracked)

    # 반대 방향: 데이터 산출물은 여전히 무시돼야 한다(규칙을 반대로 풀어 버리는 실수 방지).
    docs_dir = os.path.join(root, "storage", "docs")
    if os.path.isdir(docs_dir):
        leaked = sorted(t for t in tracked if t.startswith("storage/docs/"))
        check("storage/docs/(수집 산출물)는 추적되지 않는다", leaked, [])

    print("   추적 중인 storage/ 파일 %d개 (.py %d / .sql %d)"
          % (len(tracked),
             len([t for t in tracked if t.endswith(".py")]),
             len(sql_tracked)))


# ---------------------------------------------------------------------------
# 6-2. `.gitignore`가 무시한다고 적어 둔 파일이 **이미 추적되고 있는가** (2026-08-13 Sprint 99)
#
# git의 ignore 규칙은 **추적을 시작한 뒤에는 적용되지 않는다.** 그래서 규칙을 나중에 추가하면
# "무시하기로 했는데 계속 따라다니는" 파일이 남고, `.gitignore`만 읽으면 정리된 것처럼 보인다.
# 의도(.gitignore)와 실제(index)가 갈라진 상태다.
#
# 실측(Sprint 99): 추적 파일 238개 중 **10개가 무시 대상**이었다.
#
#     auction.db.backup_* 9개   36.9 MB   [.gitignore:73:*.db.backup*]
#     CEO/00 CEO.txt            0.0 MB    [.gitignore:120:*.txt]
#
# **개인정보는 없다** — 9개 백업 전부를 열어 확인했고, user_id가 들어 있는 두 개도
# 전부 `qa-*` 테스트 계정이었다(실 Supabase UUID 0건). 즉 보안 문제가 아니라 저장소 위생 문제다.
# 다만 clone마다 37MB를 따라다니게 하고, "왜 여기 있는지" 아무 데도 적혀 있지 않다.
#
# **왜 지우지 않았나** — 인덱스에서 빼려면 `git rm --cached` + commit이 필요한데
# 이 세션은 commit이 금지돼 있다. 그래서 **늘어나는 것만 막는다**(이 저장소가
# `test_pipeline_integrity.py`에서 쓰는 "상한을 두고 증가만 차단" 방식과 같다).
# 새로 추가되면 즉시 실패하고, 나중에 정리해서 줄어들면 그대로 통과한다.
# ---------------------------------------------------------------------------
KNOWN_TRACKED_BUT_IGNORED = {
    "CEO/00 CEO.txt",
    "auction.db.backup_20260728_103355",
    "auction.db.backup_20260728_121249",
    "auction.db.backup_20260728_123213",
    "auction.db.backup_20260730_221737",
    "auction.db.backup_20260730_221737.local",
    "auction.db.backup_before_auction_unique_20260807_095423",
    "auction.db.backup_before_court_code_20260806_173734",
    "auction.db.backup_before_migration_recovery_20260808_153510",
    "auction.db.backup_before_soft_delete_20260808_160908",
}


# ---------------------------------------------------------------------------
# 6-3. 완전히 겹치는 인덱스가 늘고 있는가 (2026-08-13 Sprint 100)
#
# 같은 컬럼 조합에 인덱스가 둘 이상이면 **읽기 이득은 0이고** 쓰기 비용과 파일 크기만 는다.
# 이 저장소에서는 이름 규칙이 다른 두 계통이 같은 인덱스를 각각 만들면서 생겼다
# (`idx_ai_*` vs `idx_auction_item_*`) - `migrate_v4_1.py`와 마이그레이션 008/009가
# 서로를 모르고 각자 만든 결과다. "같은 것을 두 곳에서 정의한다"는 이 저장소가 계속 잡아 온 패턴.
#
# 실측(Sprint 100): **완전 중복 4쌍**, 접두 포함 7쌍.
#
#   idx_ai_auction_date               == idx_auction_item_auction_date        (auction_date)
#   idx_ai_case_no                    == idx_auction_item_case_no             (case_no)
#   idx_auction_item_minimum_bid_price== idx_minimum_bid_price                (minimum_bid_price)
#   idx_rights_summary_item_id        == idx_rs_item_id                       (item_id)
#
# **왜 지금 지우지 않나** - 현재 규모(auction_item 1,876행 / DB 5.0MB)에서 측정한 API
# p95가 전부 3.1ms 이하다. 병목이 없다. 쓰기도 하루 1회 배치라 비용이 무시할 수준이고,
# 인덱스 DROP은 스키마 변경이라 이득 없이 위험만 만든다. 측정값을 남기고 **증가만 막는다**.
#
# 접두 포함(prefix)은 대상에서 뺀다 - SQLite가 더 작은 인덱스를 고르는 편이 유리한 경우가
# 있어 의도적일 수 있다. **완전 중복은 어떤 경우에도 의도일 수 없다.**
# ---------------------------------------------------------------------------
KNOWN_DUPLICATE_INDEXES = {
    ("auction_item", ("auction_date",)),
    ("auction_item", ("case_no",)),
    ("auction_item", ("minimum_bid_price",)),
    ("rights_summary", ("item_id",)),
}


def test_no_new_duplicate_indexes():
    print("\n--- 6-3. 완전히 겹치는 인덱스 ---")
    conn = dbmod.get_connection()
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]

        found = set()
        detail = []
        for t in sorted(tables):
            by_cols = {}
            for r in conn.execute("PRAGMA index_list(%s)" % t):
                name = r[1]
                if name.startswith("sqlite_autoindex"):
                    continue
                cols = tuple(c[2] for c in conn.execute("PRAGMA index_info(%s)" % name))
                by_cols.setdefault(cols, []).append(name)
            for cols, names in by_cols.items():
                if len(names) > 1:
                    found.add((t, cols))
                    detail.append("%s(%s): %s" % (t, ",".join(cols), " == ".join(sorted(names))))
    finally:
        conn.close()

    check_true("인덱스를 읽을 대상 테이블이 있다", len(tables) > 0, len(tables))

    new = sorted("%s(%s)" % (t, ",".join(c)) for t, c in (found - KNOWN_DUPLICATE_INDEXES))
    check("새로 생긴 완전 중복 인덱스 없음", new, [])

    gone = sorted("%s(%s)" % (t, ",".join(c)) for t, c in (KNOWN_DUPLICATE_INDEXES - found))
    if gone:
        print("   정리된 중복 %d건 - KNOWN_DUPLICATE_INDEXES에서 빼십시오: %s"
              % (len(gone), ", ".join(gone)))

    print("   완전 중복 %d건 (전부 알려진 항목)" % len(found))
    for d in sorted(detail):
        print("     %s" % d)


def test_no_new_tracked_but_ignored_files():
    print("\n--- 6-2. .gitignore 의도와 git index가 갈라진 파일 ---")
    root = os.path.dirname(os.path.abspath(__file__))

    try:
        ls = subprocess.run(["git", "ls-files", "-z"], cwd=root,
                            capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        print("[SKIP] git을 실행할 수 없다 (%s)" % type(exc).__name__)
        return
    if ls.returncode != 0:
        print("[SKIP] git 저장소가 아니다")
        return

    tracked = [p.decode("utf-8", "replace") for p in ls.stdout.split(b"\x00") if p]
    check_true("추적 파일 목록을 얻었다", len(tracked) > 0, len(tracked))

    # `--no-index`: 추적 여부와 무관하게 "규칙만으로는 무시 대상인가"를 판정한다.
    # 경로에 공백/한글이 있어 NUL 구분자로 주고받는다(줄 단위로 하면 깨진다).
    chk = subprocess.run(["git", "check-ignore", "--no-index", "--stdin", "-z", "-v"],
                         cwd=root,
                         input=b"\x00".join(p.encode("utf-8") for p in tracked),
                         capture_output=True, timeout=60)

    fields = chk.stdout.split(b"\x00")
    offenders = set()
    for i in range(0, len(fields) - 3, 4):
        pattern = fields[i + 2].decode("utf-8", "replace")
        path = fields[i + 3].decode("utf-8", "replace")
        if not path:
            continue
        # 마지막 매칭이 부정(!) 규칙이면 무시 대상이 아니다(예: !storage/migrations/*.sql).
        if pattern.startswith("!"):
            continue
        offenders.add(path)

    new = sorted(offenders - KNOWN_TRACKED_BUT_IGNORED)
    check("새로 생긴 '무시 대상인데 추적 중'인 파일 없음", new, [])

    # 정리되면 목록에서 빼라고 알려 준다(방치되면 이 상수 자체가 낡은 정보가 된다).
    gone = sorted(KNOWN_TRACKED_BUT_IGNORED - offenders)
    if gone:
        # 콘솔 출력 문자열에는 EM DASH(U+2014)를 쓰지 않는다 - Windows cp949에서
        # UnicodeEncodeError가 난다(test_console_encoding.py가 이 규칙을 강제한다).
        print("   정리된 항목 %d개 - KNOWN_TRACKED_BUT_IGNORED에서 빼십시오: %s"
              % (len(gone), ", ".join(gone)))

    total = 0
    for p in offenders:
        full = os.path.join(root, p.replace("/", os.sep))
        if os.path.isfile(full):
            total += os.path.getsize(full)
    print("   무시 대상인데 추적 중: %d개 / %.1f MB (전부 알려진 항목)"
          % (len(offenders), total / 1048576))


# ---------------------------------------------------------------------------
# 7. 코드가 **정확성을 위해 의존하는** UNIQUE 제약 (2026-08-13 Sprint 85 신설)
#
# 세 코드 경로가 DB의 UNIQUE 제약을 "중복 방지 장치"로 직접 사용한다 — 애플리케이션에서
# 먼저 조회해 확인하지 않고, **제약 위반 예외를 받아 분기**한다(TOCTOU를 피하는 올바른 방식).
#
#     api/v1/favorites.py:add_favorite()      IntegrityError -> FAVORITE_ALREADY_EXISTS
#     api/v1/recent_items.py                  같은 (user_id,item_id)를 여러 행으로 만들지 않는다
#     api/v1/payment_logs.py:record_webhook()  event_id UNIQUE -> is_duplicate (멱등성)
#
# 즉 **제약이 사라지면 이 세 방어가 조용히 전부 무력화된다.** 중복 즐겨찾기가 쌓이고,
# 같은 PG 노티가 두 번 적용된다(결제 상태 이중 반영). 예외가 나지 않으므로 로그도 없다.
#
# 이 저장소는 그런 일이 실제로 일어날 수 있는 구조다 — migration 018이 `document_queue`를
# **테이블 재생성** 방식으로 바꿨듯이(CREATE new -> copy -> rename), 재생성 SQL에서 UNIQUE
# 한 줄을 빠뜨리면 데이터는 그대로 옮겨지고 제약만 사라진다. `test_auction_identity.py` §1이
# auction 계열 3개 테이블에 대해 같은 검사를 이미 하고 있는데, 위 세 테이블은 빠져 있었다.
# ---------------------------------------------------------------------------
def test_code_dependent_unique_constraints():
    print("\n--- 7. 코드가 의존하는 UNIQUE 제약 (Sprint 78) ---")
    import re

    # (테이블, 제약이 덮어야 하는 컬럼들, 그 제약에 의존하는 코드 경로)
    REQUIRED = [
        ("favorites", ("user_id", "item_id"),
         "api/v1/favorites.py:add_favorite() IntegrityError -> FAVORITE_ALREADY_EXISTS"),
        ("recent_items", ("user_id", "item_id"),
         "api/v1/recent_items.py 중복 행 방지"),
        ("payment_webhooks", ("event_id",),
         "api/v1/payment_logs.py:record_webhook() is_duplicate (Webhook 멱등성)"),
    ]

    conn = dbmod.get_connection()
    try:
        for table, cols, why in REQUIRED:
            row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if not row:
                check_true("%s 테이블이 존재한다" % table, False, "테이블 자체가 없다")
                continue

            ddl = row[0]
            # 주석(-- ...)을 지운 뒤 본다 — payment_webhooks의 UNIQUE 설명 주석에 'UNIQUE'라는
            # 단어가 들어 있어, 주석을 지우지 않으면 **주석만 보고 통과**할 수 있다(실측).
            ddl_no_comment = re.sub(r"--[^\n]*", " ", ddl)
            flat = " ".join(ddl_no_comment.split())

            # 테이블 레벨 UNIQUE(...) 절 + 컬럼 레벨 `col ... UNIQUE` 둘 다 인정한다.
            table_level = [m for m in re.findall(r"UNIQUE\s*\(([^)]*)\)", flat, re.IGNORECASE)]
            covered = any(
                all(c in [x.strip() for x in group.split(",")] for c in cols)
                for group in table_level
            )
            if not covered and len(cols) == 1:
                covered = re.search(
                    r"\b%s\b[^,)]*\bUNIQUE\b" % re.escape(cols[0]), flat, re.IGNORECASE
                ) is not None
            # 별도 UNIQUE INDEX로 걸어도 동등하다.
            if not covered:
                for (idx_sql,) in conn.execute(
                    "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=?"
                    " AND sql LIKE '%UNIQUE%'", (table,)
                ).fetchall():
                    group = re.findall(r"\(([^)]*)\)", idx_sql or "")
                    if group and all(c in [x.strip() for x in group[0].split(",")] for c in cols):
                        covered = True
                        break

            check_true("%s: UNIQUE(%s)이 존재한다" % (table, ", ".join(cols)), covered,
                       "이 제약이 사라지면 조용히 무력화되는 방어: %s" % why)

        # ★ 제약이 **실제로 동작하는가**까지 본다. DDL 문자열만 보면 "선언은 있는데
        #   데이터에는 이미 중복이 있다"(과거에 제약 없이 쌓인 행)를 놓친다.
        for table, cols, _ in REQUIRED:
            group = ", ".join(cols)
            dup = conn.execute(
                "SELECT COUNT(*) FROM (SELECT %s FROM %s GROUP BY %s HAVING COUNT(*)>1)"
                % (group, table, group)
            ).fetchone()[0]
            check("%s: 실제 데이터에 중복 없음 (%s)" % (table, group), dup, 0)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 8. 추적 중인 소스의 BOM 상태가 HEAD와 같은가 (2026-08-13 Sprint 85 신설)
#
# 이 저장소의 소스 상당수(68개)에 UTF-8 BOM이 있고, 그것은 **의도된 현재 상태**다 —
# `test_console_encoding.py`가 그래서 읽기를 `utf-8-sig`로 고정했다.
#
# 문제는 도구가 BOM을 조용히 떨어뜨린다는 것이다. `utf-8-sig`로 읽고 `utf-8`로 다시 쓰면
# BOM이 사라진다(가장 흔한 편집 스크립트 패턴). 실제로 Sprint 78 작업 중 변이 시험 스크립트가
# `normalizer/normalizer.py`의 BOM을 떨어뜨렸고, **어떤 테스트도 그것을 잡지 못했다**
# (Python은 두 형태 모두 정상 실행하므로 회귀가 나지 않는다). 발견 경로는 `git diff`를
# 사람이 눈으로 본 것뿐이었다.
#
# 왜 문제인가 — 조용한 전량 변경은 진짜 변경을 가린다. BOM만 달라진 파일도 diff에 뜨므로,
# 리뷰에서 실제 코드 변경을 찾기 어려워지고 "이 파일을 왜 건드렸지?"가 반복된다.
# 값싼 구조로 막는다: **추적 중인 파일의 BOM 유무가 HEAD와 같아야 한다.**
#
# git이 없는 환경(배포된 tarball 등)에서는 조용히 건너뛴다 — 검사 자체가 실패 원인이 되면 안 된다.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 한글이 든 .ps1 은 **반드시** UTF-8 BOM 으로 저장돼야 한다 (2026-08-14 신설)
#
# 아래 §8은 "HEAD와 같은가"를 본다. 이건 다른 종류의 규칙이다 ― **절대 요건**이고,
# 신규 파일에도 적용되며(§8은 HEAD가 없는 새 파일을 건너뛴다), `.ps1` 은 §8의 대상 확장자도
# 아니다.
#
# 왜 절대 요건인가 ― Windows PowerShell 5.1(이 PC의 기본 `powershell.exe`)은 BOM이 없는
# `.ps1` 을 **시스템 ANSI 코드페이지(cp949)** 로 읽는다. UTF-8로 저장된 한글은 깨지고,
# 깨진 바이트가 따옴표·괄호를 삼켜 **파싱 자체가 실패한다.**
#
# 2026-08-14에 실제로 겪었다. `register_scheduler_tasks.ps1` 을 BOM 없이 저장했더니:
#
#     Unexpected token '?섏쭛' in expression or statement.
#     The string is missing the terminator: ".
#     Missing closing '}' in statement block or type definition.
#
# 스크립트가 한 줄도 실행되지 않았다. BOM 3바이트를 붙이자 그대로 정상 동작했다.
#
# 이 트랩이 특히 나쁜 이유: 편집기에서는 멀쩡해 보이고, 파일을 "고친" 사람은
# BOM을 떨어뜨렸다는 사실을 모른다(실제로 이 세션에서 `favorites.py` 의 BOM을
# 같은 방식으로 떨어뜨린 적이 있다 ― §8이 그때 잡았다).
# ---------------------------------------------------------------------------
def test_powershell_scripts_have_bom():
    print("\n--- 한글이 든 .ps1 의 UTF-8 BOM ---")
    import codecs

    root = os.path.dirname(os.path.abspath(__file__))
    BOM = codecs.BOM_UTF8

    scripts = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in ("node_modules", ".git", "__pycache__", ".next", ".claude")]
        scripts += [os.path.join(dirpath, f) for f in filenames if f.endswith(".ps1")]

    missing, checked = [], 0
    for path in sorted(scripts):
        with open(path, "rb") as fh:
            data = fh.read()
        try:
            data.decode("ascii")
            continue          # 순수 ASCII 는 코드페이지와 무관하다 ― 요건 아님
        except UnicodeDecodeError:
            pass
        checked += 1
        if not data.startswith(BOM):
            missing.append(os.path.relpath(path, root).replace("\\", "/"))

    print("    .ps1 %d개 중 비ASCII 포함 %d개" % (len(scripts), checked))
    check("BOM 없는 비ASCII .ps1", missing, [])
    if missing:
        print("      PowerShell 5.1 이 cp949 로 읽어 파싱이 깨진다 ― BOM 3바이트를 붙일 것")


def test_source_bom_matches_head():
    print("\n--- 8. 소스 BOM 상태가 HEAD와 동일한가 (Sprint 78) ---")
    import codecs
    import subprocess

    root = os.path.dirname(os.path.abspath(__file__))
    BOM = codecs.BOM_UTF8   # b"\xef\xbb\xbf" — 리터럴로 적으면 이 파일 자체의 인코딩에 휘둘린다

    def git(*args):
        return subprocess.run(["git"] + list(args), cwd=root, capture_output=True)

    probe = git("rev-parse", "--git-dir")
    if probe.returncode != 0:
        print("[SKIP] git 저장소가 아니다(배포본) - BOM 대조 생략")
        return

    changed = git("diff", "--name-only").stdout.decode("utf-8", "replace").split()
    # 검사 대상은 **텍스트 소스**만. 바이너리/데이터는 대상이 아니다.
    exts = (".py", ".md", ".sql", ".mjs", ".ts", ".tsx", ".json", ".txt", ".css")
    targets = [f for f in changed if f.endswith(exts)]

    mismatched = []
    for rel in targets:
        head = git("show", "HEAD:" + rel)
        if head.returncode != 0:
            continue  # 새 파일 — 비교할 HEAD가 없다
        path = os.path.join(root, rel.replace("/", os.sep))
        try:
            with open(path, "rb") as fh:
                current = fh.read(3)
        except OSError:
            continue
        if (head.stdout[:3] == BOM) != (current == BOM):
            mismatched.append(rel)

    check("작업 중 BOM이 조용히 바뀐 파일 없음", mismatched, [])
    print("   대조한 변경 소스: %d개" % len(targets))


# ---------------------------------------------------------------------------
# 9. 법원 목록(ALL_COURTS)의 무결성 (2026-08-13 Sprint 85 신설)
#
# `config/courts.py`는 커버리지 0%인 **데이터 모듈**이다. 로직이 없으니 테스트할 것도 없어
# 보이지만, 이 60줄이 곧 **매일 크롤하는 대상 전체**다. 손으로 편집하는 목록이라 값이 깨지는
# 방식이 정해져 있다.
#
#     code 중복      -> 그 법원을 두 번 돌고, DB 식별키가 (court_code, case_no, item_no)라
#                       두 번째 크롤이 첫 번째를 UPDATE한다(BUGS #18과 같은 계열의 소실)
#     한 줄 삭제     -> 그 법원 물건이 조용히 사라진다. 검색 결과가 줄어드는 것 말고 신호가 없다
#     region 오타    -> `get_courts_by_region()`이 빈 목록을 돌려주고, 지역별 실행이 0건이 된다
#
# 이 저장소는 `code == name`(둘 다 한글 법원명)이라는 실측된 전제 위에 서 있다
# (`api/v1/documents.py` 주석, `document_queue.court_code`에 한글이 들어가는 이유).
# 그 전제까지 함께 고정한다 — 코드 체계를 바꾸려면 이 검사가 먼저 실패해야 한다.
#
# 개수(60)를 박아 두는 이유: 법원을 추가/제거하는 것은 **운영 결정**이라 조용히 일어나면
# 안 된다. 의도적으로 바꿀 때 이 숫자를 함께 고치게 만든다(문서 6곳이 "60개 법원"을 말한다).
# ---------------------------------------------------------------------------
def test_court_list_integrity():
    print("\n--- 9. ALL_COURTS 무결성 (Sprint 78) ---")
    from config.courts import ALL_COURTS, get_courts_by_region
    from config.settings import SIDO_LIST

    codes = [c.code for c in ALL_COURTS]
    names = [c.name for c in ALL_COURTS]

    check("법원 수가 60개다(변경은 운영 결정 ― 함께 갱신할 것)", len(ALL_COURTS), 60)
    check("code 중복 없음", len(codes) - len(set(codes)), 0)
    check("name 중복 없음", len(names) - len(set(names)), 0)
    check("빈 값 없음", [c for c in ALL_COURTS if not (c.code and c.name and c.region)], [])
    # 이 저장소의 실측된 전제 — DB의 court_code 컬럼에 한글 법원명이 들어가는 이유다.
    check("code == name (한글 법원명 체계)", [c.code for c in ALL_COURTS if c.code != c.name], [])
    check("region이 전부 SIDO_LIST 안에 있다",
          sorted({c.region for c in ALL_COURTS if c.region not in SIDO_LIST}), [])

    # 조회 함수가 목록과 어긋나지 않는가 — 지역별 실행 경로가 이것에 의존한다.
    grouped = sum(len(get_courts_by_region(r)) for r in sorted({c.region for c in ALL_COURTS}))
    check("지역별 조회의 합이 전체와 같다(누락/중복 없음)", grouped, len(ALL_COURTS))
    check("없는 지역은 빈 목록", get_courts_by_region("없는지역"), [])


def _old_schema_ddl():
    """현재 DDL에서 **나중에 추가된 것들을 빼서** 옛 스키마를 만든다.

    옛 DDL을 이 파일에 복사해 두면 현재 DDL이 바뀔 때 같이 낡아버린다(그러면 검사는
    통과하지만 실제 마이그레이션 경로와는 무관한 것을 검사하게 된다). 그래서 살아 있는
    상수에서 파생시킨다 ― init_db()가 보완하려는 차이만 정확히 되돌린다.
    """
    auction = dbmod.CREATE_TABLE_SQL
    for col in ("has_spec_pdf", "has_status_doc", "has_appraisal_pdf"):
        auction = "\n".join(l for l in auction.split("\n") if col not in l)
    # Step 9 이전 이름. 이 칼럼에 담긴 값이 RENAME으로 보존되는지가 이 검사의 핵심이다.
    auction = auction.replace(
        "    created_at TEXT,", "    has_status_pdf INTEGER DEFAULT 0,\n    created_at TEXT,")

    queue = dbmod.CREATE_QUEUE_TABLE_SQL
    queue = "\n".join(l for l in queue.split("\n") if "item_no TEXT NOT NULL" not in l)
    queue = queue.replace("UNIQUE(court_code, case_no, item_no, doc_type)",
                          "UNIQUE(court_code, case_no, doc_type)")

    vlog = "\n".join(l for l in dbmod.CREATE_VERSION_LOG_TABLE_SQL.split("\n")
                     if "item_no TEXT" not in l)
    return auction, queue, vlog


def test_init_db_upgrades_old_schema():
    """init_db()의 옛 스키마 보완 분기 (2026-08-13 Sprint 85 신설).

    init_db()에는 "과거 실행분 DB"를 위한 분기가 네 개 있다 ― has_status_pdf ->
    has_status_doc RENAME, has_* 칼럼 추가, document_queue.item_no 추가,
    document_version_log.item_no 추가. 운영 DB는 이미 전부 반영된 상태라 이 분기들은
    **평소에 한 줄도 실행되지 않는다**(검사 0건이었다). 여기서 옛 스키마 DB를 픽스처로
    만들어 실제로 밟는다.

    틀렸을 때의 결과: RENAME 대신 ADD COLUMN을 하면 이미 수집한 문서 표시가 전부 0으로
    돌아가 같은 문서를 다시 받는다(크롤 부하 + 큐 소진). NOT NULL DEFAULT 없이 item_no을
    추가하면 기존 큐 행의 item_no이 NULL이 되어 (court,case,item_no) 조회에서 사라진다.

    함께 못 박는 사실 하나: init_db()는 **UNIQUE 제약을 고치지 못한다**(SQLite는 제약만
    바꾸는 ALTER가 없다). 그래서 옛 DB는 init_db() 하나로 최신 상태가 되지 않고
    migration 018이 반드시 필요하다. 이 순서를 코드로 고정해 둔다.

    변이 테스트로 확인된 것(2026-08-13): 분기 5개를 각각 없앤 변이는 모두 잡힌다. 다만
    `conn.commit()`을 지운 변이는 **잡히지 않으며, 실제로 아무 차이도 없다** ― init_db()
    본문은 전부 DDL이고 sqlite3 모듈은 DDL에 트랜잭션을 열지 않으므로 이미 확정돼 있다.
    검사를 늘려도 잡을 수 없는 종류이므로(=결함이 아니다) 그대로 둔다. 나중에 이 함수에
    DML이 들어오면 그때는 commit이 실제 의미를 갖게 되고, 그 값을 보는 검사가 필요해진다.
    """
    import shutil
    import sqlite3
    import tempfile

    print("\n--- 10. init_db() 옛 스키마 보완 분기 (Sprint 85) ---")
    auction_ddl, queue_ddl, vlog_ddl = _old_schema_ddl()
    tmpdir = tempfile.mkdtemp(prefix="qa_oldschema_")
    old_db = os.path.join(tmpdir, "old_auction.db")
    saved_path = dbmod.DB_PATH
    try:
        conn = sqlite3.connect(old_db)
        conn.execute(auction_ddl)
        conn.execute(queue_ddl)
        conn.execute(vlog_ddl)
        # 옛 DB에 이미 있던 데이터. 마이그레이션이 이걸 지키는지가 관심사다.
        conn.execute(
            "INSERT INTO auction (court_code, case_no, item_no, has_status_pdf, created_at)"
            " VALUES ('999','2026TEST9999','1',1,'2026-01-01')")
        conn.execute(
            "INSERT INTO document_queue (court_code, case_no, doc_type, status, enqueued_at)"
            " VALUES ('999','2026TEST9999','spec','pending','2026-01-01')")
        conn.execute(
            "INSERT INTO document_version_log (court_code, case_no, doc_type, new_hash)"
            " VALUES ('999','2026TEST9999','spec','abc')")
        conn.commit()
        conn.close()

        dbmod.DB_PATH = old_db
        # init_db()가 예외로 죽으면 그건 **결함**이지 테스트 오류가 아니다. 그대로 터지게
        # 두면 크래시가 되어 FAIL 집계에서 사라진다(변이 테스트에서 실제로 그렇게 나왔다:
        # RENAME 후 칼럼 목록을 갱신하지 않는 변이가 "duplicate column name"으로 죽었다).
        def try_init(label):
            try:
                dbmod.init_db()
                return True
            except Exception as exc:
                check_true("init_db()가 예외 없이 끝난다 (%s)" % label, False, repr(exc))
                return False

        upgraded = try_init("옛 스키마")

        conn = sqlite3.connect(old_db)
        conn.row_factory = sqlite3.Row
        cols = [r[1] for r in conn.execute("PRAGMA table_info(auction)").fetchall()]
        check_true("has_status_doc로 개명됐다", "has_status_doc" in cols, cols)
        check_true("옛 이름 has_status_pdf는 남지 않는다", "has_status_pdf" not in cols, cols)
        for col in ("has_spec_pdf", "has_appraisal_pdf"):
            check_true("%s 칼럼이 추가됐다" % col, col in cols, cols)

        # 없는 칼럼을 sqlite3.Row로 읽으면 IndexError로 **테스트가 죽는다** ― 그러면 결함이
        # FAIL이 아니라 크래시로 나타나 집계에서 사라진다(변이 테스트로 확인한 하네스 결함
        # 유형이다). 칼럼 부재를 값처럼 다뤄 항상 FAIL로 보이게 한다.
        def val(row, name):
            return row[name] if name in row.keys() else "<칼럼 없음>"

        row = conn.execute(
            "SELECT * FROM auction WHERE case_no='2026TEST9999'").fetchone()
        check("이미 수집된 표시(1)가 RENAME으로 보존된다", val(row, "has_status_doc"), 1)
        check("새로 추가된 칼럼은 0으로 채워진다",
              (val(row, "has_spec_pdf"), val(row, "has_appraisal_pdf")), (0, 0))

        qrow = conn.execute("SELECT * FROM document_queue").fetchone()
        check("큐의 기존 행에 item_no이 '1'로 채워진다(NULL이 아니다)", val(qrow, "item_no"), "1")
        vcols = [r[1] for r in conn.execute("PRAGMA table_info(document_version_log)").fetchall()]
        check_true("이력 로그에 item_no이 추가됐다", "item_no" in vcols, vcols)
        vrow = conn.execute("SELECT * FROM document_version_log").fetchone()
        check("이력 로그의 item_no은 NULL 허용이다", val(vrow, "item_no"), None)

        # UNIQUE 제약은 그대로다 ― 이것이 migration 018이 따로 있는 이유다.
        # enqueue는 INSERT OR IGNORE를 쓰므로, 이 상태의 DB에서는 같은 사건의 물건번호 2번이
        # **조용히 버려진다**(에러도 안 난다). init_db()만으로 끝났다고 믿으면 안 된다.
        queue_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='document_queue'"
        ).fetchone()["sql"]
        check_true("init_db()는 UNIQUE 제약을 고치지 못한다(측정된 한계)",
                   "UNIQUE(court_code, case_no, doc_type)" in queue_sql, queue_sql)
        mig = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "storage", "migrations", "018_document_queue_item_no_unique.sql")
        check_true("그 한계를 메우는 migration 018이 존재한다", os.path.exists(mig), mig)
        conn.close()

        # 두 번 실행해도 안전한가 ― 부트스트랩은 매 실행 호출된다.
        try_init("두 번째 실행")
        conn = sqlite3.connect(old_db)
        conn.row_factory = sqlite3.Row
        check("두 번째 init_db() 후에도 칼럼 수가 같다",
              len([r[1] for r in conn.execute("PRAGMA table_info(auction)").fetchall()]),
              len(cols))
        row = conn.execute("SELECT * FROM auction WHERE case_no='2026TEST9999'").fetchone()
        check("두 번째 init_db()가 값을 되돌리지 않는다", row["has_status_doc"], 1)
        conn.close()

        # 신규 DB(옛 칼럼이 아예 없는 경우)에서는 처음부터 올바른 제약으로 만들어진다.
        fresh = os.path.join(tmpdir, "fresh.db")
        dbmod.DB_PATH = fresh
        check_true("옛 스키마 보완이 예외 없이 끝났다", upgraded, "위 FAIL 참고")
        try_init("신규 DB")
        conn = sqlite3.connect(fresh)
        fresh_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='document_queue'"
        ).fetchone()[0]
        check_true("신규 DB의 큐 UNIQUE에는 item_no이 들어 있다",
                   "UNIQUE(court_code, case_no, item_no, doc_type)" in fresh_sql, fresh_sql)
        fresh_cols = [r[1] for r in conn.execute("PRAGMA table_info(auction)").fetchall()]
        check_true("신규 DB에도 has_status_doc이 있다", "has_status_doc" in fresh_cols, fresh_cols)
        check_true("신규 DB에 옛 이름은 없다", "has_status_pdf" not in fresh_cols, fresh_cols)
        conn.close()
    finally:
        dbmod.DB_PATH = saved_path
        shutil.rmtree(tmpdir, ignore_errors=True)
    check("운영 DB 경로가 원래대로 복원됐다", dbmod.DB_PATH, saved_path)


def test_init_db_failure_is_loud():
    """init_db()가 실패할 때 **조용히 넘어가지 않는가** (2026-08-13 Sprint 85 신설).

    `init_db()`의 `except Exception` 절(로그 + 재전파)이 유일하게 남은 미커버 구간이었다.
    이 절이 하는 일은 하나뿐이지만 그 하나가 중요하다 ― 부트스트랩 실패를 삼키면 이후 모든
    작업이 "테이블이 없다"는 엉뚱한 오류로 실패하고, 진짜 원인(디스크/권한/파일 손상)은
    어디에도 남지 않는다. 이 저장소가 반복해 지킨 원칙("조용히 넘기면 추적할 수 없다")이
    부트스트랩에도 적용되는지 확인한다.

    재현 방법: DB 파일 자리에 **DB가 아닌 파일**을 둔다. sqlite3는 연결 자체는 성공하고
    (지연 열기) 첫 DDL에서 `DatabaseError: file is not a database`로 실패한다 ― 디스크 손상과
    같은 계열의 실패를 파일 하나로 만들 수 있다.
    """
    import logging
    import shutil
    import tempfile

    print("\n--- 12. init_db() 실패는 조용하지 않다 (Sprint 85) ---")
    tmpdir = tempfile.mkdtemp(prefix="qa_initfail_")
    broken = os.path.join(tmpdir, "not_a_database.db")
    with open(broken, "wb") as fh:
        fh.write("이건 SQLite 파일이 아니다".encode("utf-8") * 8)
    before = open(broken, "rb").read()

    records = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = _Capture(level=logging.ERROR)
    logger = logging.getLogger(dbmod.__name__)
    logger.addHandler(handler)
    saved_path = dbmod.DB_PATH
    try:
        dbmod.DB_PATH = broken
        raised = None
        try:
            dbmod.init_db()
        except Exception as exc:  # noqa: BLE001 - 어떤 예외든 전파돼야 한다
            raised = exc
        check_true("실패를 삼키지 않고 예외를 전파한다", raised is not None,
                   "init_db()가 조용히 끝났다")
        check_true("sqlite 계열 오류로 전파된다", isinstance(raised, sqlite3.Error), repr(raised))
        errors = [r for r in records if r.levelno >= logging.ERROR]
        check_true("ERROR 로그를 남긴다", len(errors) >= 1, records)
        if errors:
            msg = errors[0].getMessage()
            check_true("로그에 원인이 담긴다(빈 메시지가 아니다)",
                       "DB 초기화 실패" in msg and len(msg) > len("DB 초기화 실패: "), msg)
    finally:
        dbmod.DB_PATH = saved_path
        logger.removeHandler(handler)

    # 실패했다면 그 파일을 망가뜨리지 않고 그대로 두었는가 ― 남의 파일을 덮어쓰면
    # 원인 조사조차 불가능해진다.
    # 내용을 그대로 비교하면 실패 메시지가 파일 전체를 토해낸다 ― 요약값으로 본다.
    import hashlib
    check("실패한 대상 파일을 변형하지 않는다",
          hashlib.sha256(open(broken, "rb").read()).hexdigest()[:16],
          hashlib.sha256(before).hexdigest()[:16])
    shutil.rmtree(tmpdir, ignore_errors=True)
    check("운영 DB 경로가 복원됐다", dbmod.DB_PATH, saved_path)


# ---------------------------------------------------------------------------
# 목록 조회 GET 은 "HTTP 200 = 성공"이어야 한다 (2026-08-14 신설)
#
# 이 API 에는 실패 응답이 **두 형태**로 있고, 그것 자체는 의도된 상태다(§5 참고).
#
#     error_response(code,msg)  -> HTTP 200 + {success:false, error:"CODE", ...}
#     raise HTTPException(...)  -> HTTP 4xx  + {"detail": "..."}
#
# 문제는 프런트가 목록을 받는 방식이다. 아래 네 화면은 전부 이렇게 쓴다.
#
#     const result = await fetchAuthedJSON<T[]>(path, token)
#     setItems(result.data ?? [])          // <- success 를 보지 않는다
#
# 지금은 **안전하다**. 네 엔드포인트 모두 `error_response` 를 한 번도 쓰지 않아
# HTTP 200 이면 반드시 성공이기 때문이다(2026-08-14 전수 확인). 즉 `success` 확인이
# 생략된 것이 아니라 **생략해도 되는 상태**다.
#
# 그런데 그 전제는 깨지기 쉽다. 누가 이 GET 중 하나에 `error_response(...)` 를 하나만
# 추가하면 — 예컨대 "구독이 필요합니다" — 프런트는 그 응답을 **빈 목록**으로 그린다.
# 사용자는 오류 대신 "관심물건이 없습니다"를 본다. 실패가 정상 화면으로 둔갑한다.
#
# 그래서 전제를 검사로 고정한다. 이 GET 들에 `error_response` 를 넣으려면 프런트의
# 호출부도 함께 고쳐야 하고, 이 검사가 그 사실을 먼저 알려 준다.
# ---------------------------------------------------------------------------
# (파일, GET 경로) — 프런트가 success 를 보지 않고 data 만 쓰는 목록 엔드포인트
DATA_ONLY_LIST_GETS = [
    ("favorites.py", "/favorites"),
    ("recent_items.py", "/recent-items"),
    ("search_presets.py", "/search-presets"),
    ("registry.py", "/registry-requests"),
]


def test_list_gets_never_return_success_false():
    print("\n--- 12. 목록 GET 은 HTTP 200 = 성공이어야 한다 ---")
    import re

    root = os.path.dirname(os.path.abspath(__file__))
    offenders, checked = [], 0
    for fname, route in DATA_ONLY_LIST_GETS:
        path = os.path.join(root, "api", "v1", fname)
        if not os.path.exists(path):
            check_true("%s 가 존재한다" % fname, False, path)
            continue
        src = open(path, encoding="utf-8-sig").read()
        # 해당 라우트의 GET 핸들러 본문만 잘라 본다(다음 @router 데코레이터까지).
        m = re.search(r'@router\.get\(\s*["\']%s["\']' % re.escape(route), src)
        check_true("%s 의 GET %s 핸들러를 찾았다" % (fname, route), m is not None, route)
        if not m:
            continue
        start = m.end()
        nxt = src.find("@router.", start)
        body = src[start:nxt if nxt > 0 else len(src)]
        code = "\n".join(l.split("#")[0] for l in body.splitlines())
        checked += 1
        if "error_response(" in code:
            offenders.append("%s %s" % (fname, route))

    check_true("검사 대상 GET 을 실제로 찾았다", checked == len(DATA_ONLY_LIST_GETS), checked)
    check("목록 GET 이 success=false 를 돌려주지 않는다", offenders, [])
    if offenders:
        print("      프런트(favorites/recent/search-presets/mypage)는 `result.data ?? []` 만"
              " 쓰므로, 이 응답은 화면에서 **빈 목록**이 된다.")


# ---------------------------------------------------------------------------
# 뜻이 비슷한 컬럼 중 **잘못된 쪽**을 고르지 않는가 (2026-08-14 신설)
#
# `registry_credits` / `registry_credit_logs` 에는 이름이 비슷한 컬럼이 **둘** 있다.
#
#     reason_type   GRANT / DEDUCT / RESET / USAGE / EVENT / REFUND / OTHER   <- enum
#     reason        "등기부 신청 (item_id=123)"                                <- 자유 텍스트
#
# 이런 자리는 **반드시 한 번은 잘못 고른다.** 실제로 2026-08-14에 새 검사를 쓰면서
# `WHERE reason = 'REFUND'` 라고 썼다. 자유 텍스트에 그 값이 들어갈 일이 없으니
# **보상이 실제로 있어도 영원히 0으로 세는** 검사가 될 뻔했다(사본 검증에서 잡았다).
#
# 조용히 틀리는 종류라 더 나쁘다 — 예외도 안 나고 결과가 0이라 "문제 없음"처럼 보인다.
#
# 운영 코드는 지금 전부 `reason_type` 을 쓴다(전수 확인). 그 상태를 고정한다.
# 같은 이유로 `status` 에 검증 결과(PASS/FAIL)를 비교하는 것도 막는다 —
# `auction_item` 에는 `status`("유찰 2회")와 `validation_status`("PASS"/"FAIL")가 함께 있다.
# ---------------------------------------------------------------------------
CREDIT_REASON_ENUM = ("GRANT", "DEDUCT", "RESET", "USAGE", "EVENT", "REFUND", "OTHER")


def test_no_confusable_column_misuse():
    print("\n--- 13. 뜻이 비슷한 컬럼을 잘못 고르지 않는가 ---")
    import re
    import subprocess

    root = os.path.dirname(os.path.abspath(__file__))
    p = subprocess.run(["git", "ls-files", "*.py"], cwd=root,
                       capture_output=True, text=True)
    files = [f for f in p.stdout.split() if f]
    check_true("검사할 파일을 찾았다", len(files) > 10, len(files))

    # ★ 범위를 정확히 좁힌다. 처음에는 `status = "PASS"` 를 전부 잡았는데,
    #   테스트들이 **출력 라벨용 지역 변수**로 그 이름을 쓴다
    #   (`status = "PASS" if ok else "FAIL"` — DB 컬럼과 무관하다).
    #   그런 오탐을 남기면 검사가 곧 무시당한다. 그래서 두 형태만 본다:
    #     (a) SQL 문자열 안의 컬럼 비교  ... WHERE status='PASS'
    #     (b) 행에서 꺼낸 값의 비교      row["status"] == "PASS" / .status == "PASS"
    enum_alt = "|".join(CREDIT_REASON_ENUM)
    SQL_HINT = re.compile(r"\b(SELECT|WHERE|UPDATE|DELETE|AND|OR)\b", re.I)

    sql_reason = re.compile(r"(?<![\w_])reason\s*(?:=|==|!=)\s*['\"](?:%s)['\"]" % enum_alt)
    row_reason = re.compile(
        r"""(?:\[\s*['"]reason['"]\s*\]|\.reason)\s*(?:==|!=)\s*['"](?:%s)['"]""" % enum_alt)
    sql_status = re.compile(r"(?<![\w_])status\s*(?:=|==|!=)\s*['\"](?:PASS|FAIL)['\"]")
    row_status = re.compile(
        r"""(?:\[\s*['"]status['"]\s*\]|\.status)\s*(?:==|!=)\s*['"](?:PASS|FAIL)['"]""")

    hits_reason, hits_status = [], []
    for rel in files:
        path = os.path.join(root, rel)
        try:
            src = open(path, encoding="utf-8-sig").read()
        except OSError:
            continue
        for i, line in enumerate(src.splitlines(), 1):
            code = line.split("#")[0]
            in_sql = bool(SQL_HINT.search(code))
            if row_reason.search(code) or (in_sql and sql_reason.search(code)):
                hits_reason.append("%s:%d" % (rel, i))
            if row_status.search(code) or (in_sql and sql_status.search(code)):
                hits_status.append("%s:%d" % (rel, i))

    check("크레딧 enum 을 자유 텍스트 reason 과 비교하지 않는다", hits_reason, [])
    check("검증 결과(PASS/FAIL)를 status 와 비교하지 않는다", hits_status, [])
    print("    %d개 파일에서 reason/reason_type · status/validation_status 사용을 대조" % len(files))


LEGACY_DOC_FLAGS = ("has_spec_pdf", "has_status_doc", "has_appraisal_pdf")


def test_api_never_reads_legacy_doc_flags():
    """화면 경로는 `auction.has_*` 플래그를 읽지 않는다 (2026-08-13 Sprint 85 신설).

    2026-08-13 실측 ― 레거시 플래그와 화면 테이블(`document_status`)이 어긋난 행이 35건이고,
    **어긋난 35건 모두 디스크 실물과 일치하는 쪽은 document_status였다**:

        SPEC        플래그=1인데 READY 아님 1건 (파일 없음)  / READY인데 플래그=0 1건 (파일 있음)
        APPRAISAL   같은 물건에서 같은 모양 1건 / 1건
        STATUS      플래그=1인데 READY 아님 33건 (전부 파일 없음)

    즉 플래그는 과거에 잘못 세워진 채 남아 있다(2026-08-11 Sprint 55, docs/BUGS.md #50에서
    화면 테이블을 디스크 기준으로 1회 보정하고, 이후 수집은 `mark_queue_done()`이 두 곳을
    한 트랜잭션에서 함께 갱신하도록 고쳤다). 지금은 `api/` 어디에서도 이 플래그를 읽지
    않는다 ― 그래서 사용자에게는 문제가 보이지 않는다.

    이 검사는 그 상태를 고정한다. 누군가 편의상 `auction.has_spec_pdf`를 다시 읽으면
    "파일이 있는데 수집중으로 보이거나, 없는데 있다고 보이는" #50이 그대로 되살아난다.
    플래그를 지우는 것(스키마 변경)은 승인 사항이라 여기서 하지 않는다 ― 대신 읽히지
    않는다는 사실만 회귀로 지킨다.
    """
    print("\n--- 11. 화면 경로는 레거시 문서 플래그를 읽지 않는다 (Sprint 85) ---")
    root = os.path.dirname(os.path.abspath(__file__))
    api_dir = os.path.join(root, "api")
    hits = []
    scanned = 0
    for dirpath, _dirs, files in os.walk(api_dir):
        if "__pycache__" in dirpath:
            continue
        for fn in files:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dirpath, fn)
            scanned += 1
            with open(path, encoding="utf-8-sig") as fh:
                for lineno, line in enumerate(fh, 1):
                    stripped = line.strip()
                    if stripped.startswith("#"):
                        continue  # 주석에서 언급하는 것은 막을 이유가 없다
                    for flag in LEGACY_DOC_FLAGS:
                        if flag in line:
                            hits.append("%s:%d %s" % (os.path.relpath(path, root), lineno, stripped[:60]))
    check_true("api/ 소스를 실제로 읽었다(검사가 공허하지 않다)", scanned >= 5, scanned)
    check("api/ 어디서도 레거시 문서 플래그를 참조하지 않는다", hits, [])

    # 반대쪽도 확인 ― 플래그는 여전히 수집 경로에서 **쓰이고** 있다. 이게 없으면 위 검사는
    # "플래그가 아예 사라졌다"와 구별되지 않는다(그때는 이 검사 자체가 무의미해진다).
    with open(os.path.join(root, "storage", "database.py"), encoding="utf-8-sig") as fh:
        db_src = fh.read()
    for flag in LEGACY_DOC_FLAGS:
        check_true("%s는 수집 경로에 아직 존재한다" % flag, flag in db_src)


# ---------------------------------------------------------------------------
# SQL 텍스트에 새 보간이 생기면 알린다 (2026-08-14 신설)
#
# 이 API 는 WHERE 절을 **문자열로 조립한다.**
#
#     conditions.append("sigungu LIKE ?")      # 조각은 전부 상수 + ? 바인딩
#     where = " AND ".join(conditions)
#     conn.execute(f"SELECT * FROM auction_item WHERE {where}", params)
#
# 2026-08-14 실측 결과 **지금은 인젝션이 없다.** 정적/동적 양쪽으로 확인했다.
#
#   - 정적: SQL 텍스트를 만드는 보간 지점 22곳을 AST 로 전수. 요청으로 도달 가능한 7곳
#           (search 3 / admin 2 / audit 2)의 조각이 전부 **상수**이거나 상수의 반복이다.
#           유일한 f-string 조각 `f"({or_clause})"` 도 `["property_type LIKE ?"] * len(...)`
#           이라 **길이만** 가변이다. 값은 전부 `?` 로 바인딩된다.
#   - 동적: `' OR '1'='1` / `'; DROP TABLE auction_item; --` / UNION 등 6개 페이로드를
#           sido·sigungu·dong·case_no·court_name·status·address_detail·property_type 에
#           넣어 실제 요청. 전부 리터럴로 취급됐고(결과 0건), 테이블 26개와 1,876행이
#           그대로였다. 정렬 파라미터는 화이트리스트 밖이면 **HTTP 400**이다.
#
# 그러니 이 검사는 "안전함을 증명"하지 않는다 — 그건 위 실측이 이미 했다.
# 이 검사가 하는 일은 하나다: **SQL 텍스트에 새로운 보간이 들어오면 실패한다.**
#
# 지켜야 할 것이 그 지점이기 때문이다. 지금 구조에서 인젝션이 생기는 유일한 방법은
# 누가 조각 하나를 상수가 아니게 쓰는 것이다.
#
#     conditions.append(f"sido = '{sido}'")    # <- 이 한 줄이면 뚫린다
#
# 페이로드 검사는 **내가 생각해 낸 공격만** 잡지만, 이 검사는 위 한 줄을 잡는다.
# 새 보간이 정당하면 아래 목록에 추가하면 된다 — 그때 사람이 한 번 보게 하는 것이 목적이다.
# ---------------------------------------------------------------------------
# (파일, 보간되는 표현식) — SQL **텍스트**에 들어가는 것만. `f"%{x}%"` 같은
# 바인딩 **값**은 애초에 대상이 아니다(리터럴 부분에 SQL 키워드가 없다).
ALLOWED_SQL_TEXT_INTERPOLATIONS = {
    ("api/v1/search.py", "where"),          # " AND ".join(상수 조각들)
    ("api/v1/search.py", "order_clause"),   # SORT_COLUMNS 화이트리스트 + ASC/DESC
    ("api/v1/search.py", "placeholders"),   # "?,?,?" (id 개수)
    ("api/v1/admin.py", "where"),           # " AND ".join(상수 조각들)
    # 부트스트랩 스크립트의 결과 출력. 테이블명을 `sqlite_master` 가 돌려준 그대로 쓴다 —
    # DB 자신이 만든 이름이고 요청으로 도달하는 경로가 아니다.
    ("storage/migrate_v4_1.py", "t[0]"),
    # 백필 스크립트(CLI). `table` 은 호출부에서 `"auction"` / `"auction_item"` 리터럴로만
    # 넘어온다(2026-08-14 확인). 요청으로 도달하는 경로가 아니다.
    ("backfill_dong_normalize.py", "table"),
    ("backfill_dong_fix_mismatch.py", "table"),
}
# ★ 문자열 `+` 연결도 SQL 텍스트를 만든다 (2026-08-14 추가).
#
#   처음 이 검사를 만들 때 f-string 과 %-포맷만 봤다. **세 번째 형태를 통째로 놓쳤다** —
#   `storage/database.py:get_auctions()` 와 `api/v1/admin.py` 의 목록 3개가 그 형태다.
#
#       "SELECT * FROM payments WHERE " + where + " ORDER BY ..."
#       "SELECT * FROM auction " + where + " ORDER BY auction_date DESC LIMIT ?"
#       "UPDATE auction SET " + col + "=1 WHERE ..."
#
#   즉 인벤토리가 22곳이라고 적어 뒀는데 실제로는 그보다 많았다. 다시 세어 전부 확인했다:
#   조각은 여전히 전부 상수이고 값은 `?` 로 바인딩되며, `col` 은 3개 리터럴 dict 조회
#   (모르는 키는 `KeyError` 로 막힌다)라 **인젝션은 없다**. 빠졌던 것은 검사 범위다.
ALLOWED_SQL_CONCAT_OPERANDS = {
    ("api/v1/admin.py", "where"),                    # " AND ".join(상수 조각들)
    ("api/v1/admin.py", "base"),                     # 상수 SELECT 문
    ("storage/database.py", "where"),                # " AND ".join(상수 조각들)
    ("storage/database.py", "' AND '.join(conditions)"),
    ("storage/database.py", "col"),                  # 3개 리터럴 dict 조회 (KeyError 로 fail-closed)
    ("storage/database.py", "_NOW_LOCAL"),           # 모듈 상수 "datetime('now','localtime')"
    ("storage/database.py", "str(RETRY_INTERVAL_MINUTES)"),   # 모듈 상수 int
    # `filter/` 는 어디에도 배선되지 않은 죽은 코드지만(docs/CLAUDE.md), 조각은 상수다.
    ("filter/filter_engine.py", "where"),
    ("filter/filter_engine.py", "' AND '.join(conditions)"),
    # SQL 이 아니다 — 진단 출력 문자열이 "[select ..." 라 키워드 매칭에 걸린다.
    ("verify_courts.py", "sel_id"),
    ("verify_courts.py", "sel_name"),
    ("verify_courts.py", "str(s_idx)"),
}
# %-포맷으로 만드는 SQL 은 좌변 템플릿 자체를 고정한다(우변은 상수 조각/`?` 반복뿐).
ALLOWED_SQL_PERCENT_TEMPLATES = {
    ("api/v1/audit.py", "SELECT COUNT(*) FROM audit_logs WHERE %s"),
    ("api/v1/audit.py",
     "SELECT * FROM audit_logs WHERE %s ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?"),
    ("api/v1/payments.py", "UPDATE payment_logs SET payment_id=? WHERE id IN (%s)"),
    ("storage/database.py", "PRAGMA foreign_keys = %s"),
    # 아래는 전부 CLI 운영 스크립트다(요청으로 도달하지 않는다). 2026-08-14 확인:
    #   `%s` 자리에 들어가는 것은 호출부의 테이블 리터럴이거나 `?` 반복뿐이고,
    #   값은 예외 없이 바인딩된다. `TARGET_COLUMNS` 도 모듈 상수 튜플이다.
    ("backfill_region_normalize.py", "SELECT id, full_address, sido, sigungu FROM %s"),
    ("backfill_region_normalize.py", "UPDATE %s SET %s = ? WHERE id = ?"),
    ("load_rights_data.py", "DELETE FROM rights_summary WHERE item_id IN (%s)"),
    ("load_rights_data.py",
     "DELETE FROM tenant_rights WHERE source='STATUS' AND item_id IN (%s)"),
    ("load_spec_data.py",
     "DELETE FROM tenant_rights WHERE source='SPEC' AND item_id IN (%s)"),
    ("reset_failures.py",
     "SELECT COUNT(*) FROM document_status WHERE status='FAILED' AND id IN (%s)"),
    ("reset_failures.py",
     "UPDATE document_status SET status='COLLECTING', updated_at=? "
     "WHERE status='FAILED' AND id NOT IN (%s)"),
}
_SQL_KEYWORDS = ("SELECT ", "INSERT ", "UPDATE ", "DELETE ", "WHERE ", "ORDER BY",
                 " FROM ", "VALUES", "SET ", "JOIN ", "GROUP BY", "PRAGMA ", "CREATE ")


def _sql_text_interpolations(root):
    """(경로, f-string 보간식) / (경로, %-템플릿) / (경로, + 연결 피연산자) 세 집합."""
    import ast

    fstr, pct, cat = set(), set(), set()
    targets = []
    # `filter/` 와 루트 스크립트도 본다 — `api`/`storage` 만 보면 SQL 을 만드는 곳을 놓친다
    # (2026-08-14: 실제로 `filter/filter_engine.py` 와 루트 스크립트가 빠져 있었다).
    for base in ("api", "storage", "crawler", "validator", "normalizer", "filter"):
        d = os.path.join(root, base)
        if not os.path.isdir(d):
            continue
        for dp, dn, fn in os.walk(d):
            dn[:] = [x for x in dn if x != "__pycache__"]
            targets += [os.path.join(dp, f) for f in fn if f.endswith(".py")]
    targets += [os.path.join(root, f) for f in os.listdir(root)
                if f.endswith(".py")
                and not f.startswith(("test_", "step", "check_", "patch_"))]

    def _flatten_add(node, out):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            _flatten_add(node.left, out)
            _flatten_add(node.right, out)
        else:
            out.append(node)

    for path in sorted(set(targets)):
        rel = os.path.relpath(path, root).replace("\\", "/")
        with open(path, "rb") as f:
            tree = ast.parse(f.read().decode("utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                lit = "".join(v.value for v in node.values
                              if isinstance(v, ast.Constant) and isinstance(v.value, str))
                if any(k in lit.upper() for k in _SQL_KEYWORDS):
                    for v in node.values:
                        if isinstance(v, ast.FormattedValue):
                            fstr.add((rel, ast.unparse(v.value)))
            elif (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod)
                  and isinstance(node.left, ast.Constant)
                  and isinstance(node.left.value, str)
                  and any(k in node.left.value.upper() for k in _SQL_KEYWORDS)):
                pct.add((rel, " ".join(node.left.value.split())))
            elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
                parts = []
                _flatten_add(node, parts)
                consts = [p for p in parts
                          if isinstance(p, ast.Constant) and isinstance(p.value, str)]
                if any(any(k in p.value.upper() for k in _SQL_KEYWORDS) for p in consts):
                    for p in parts:
                        if not (isinstance(p, ast.Constant) and isinstance(p.value, str)):
                            cat.add((rel, ast.unparse(p)[:52]))
    return fstr, pct, cat


def test_no_new_sql_text_interpolation():
    print("\n--- SQL 텍스트 보간 지점 고정 ---")
    root = os.path.dirname(os.path.abspath(__file__))
    fstr, pct, cat = _sql_text_interpolations(root)

    new_c = sorted(cat - ALLOWED_SQL_CONCAT_OPERANDS)
    check_true("+ 연결 SQL 에 새 피연산자 없음", not new_c,
               "허용 목록에 없다(정당하면 ALLOWED_SQL_CONCAT_OPERANDS 에 추가): %s" % new_c)

    new_f = sorted(fstr - ALLOWED_SQL_TEXT_INTERPOLATIONS)
    check_true("f-string SQL 에 새 보간 없음", not new_f,
               "허용 목록에 없다(정당하면 ALLOWED_SQL_TEXT_INTERPOLATIONS 에 추가): %s" % new_f)
    new_p = sorted(pct - ALLOWED_SQL_PERCENT_TEMPLATES)
    check_true("%-포맷 SQL 에 새 템플릿 없음", not new_p,
               "허용 목록에 없다: %s" % new_p)

    # 목록이 실제 코드보다 앞서 나가지 않게 한다 — 지워진 지점이 남아 있으면 검사가 헐거워진다.
    gone = sorted((ALLOWED_SQL_TEXT_INTERPOLATIONS | ALLOWED_SQL_PERCENT_TEMPLATES
                   | ALLOWED_SQL_CONCAT_OPERANDS) - (fstr | pct | cat))
    check_true("허용 목록에 죽은 항목 없음", not gone, "코드에서 사라진 항목: %s" % gone)

    # 조각이 상수인지 — WHERE 조각을 모으는 리스트에 상수 아닌 것이 들어가면 알린다.
    # (`f"({or_clause})"` 는 상수의 반복이라 예외로 둔다. 위 주석의 실측 근거 참고.)
    import ast
    # ★ 대상 파일을 손으로 적지 않는다 (2026-08-14 정정).
    #   처음에는 3개를 박아 뒀는데 `conditions.append` 를 쓰는 파일은 **5개**였다
    #   (`storage/database.py` / `filter/filter_engine.py` 가 빠져 있었다).
    #   Sprint 109·116·118 에서 반복해 고친 것과 같은 모양이라 여기서도 코드에서 유도한다.
    cond_files = []
    for base in ("api", "storage", "filter"):
        d = os.path.join(root, base)
        for dp, dn, fn in os.walk(d):
            dn[:] = [x for x in dn if x != "__pycache__"]
            for f_ in fn:
                if not f_.endswith(".py"):
                    continue
                p = os.path.join(dp, f_)
                with open(p, "rb") as fh:
                    if b"conditions.append" in fh.read():
                        cond_files.append(os.path.relpath(p, root).replace("\\", "/"))
    cond_files = sorted(set(cond_files))
    print("    conditions.append 사용 파일 %d개: %s" % (len(cond_files), ", ".join(cond_files)))
    check_true("WHERE 조각을 모으는 파일을 실제로 찾았다", len(cond_files) >= 4, cond_files)

    bad = []
    for rel in cond_files:
        with open(os.path.join(root, rel), "rb") as f:
            tree = ast.parse(f.read().decode("utf-8-sig"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "append"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "conditions"):
                continue
            arg = node.args[0] if node.args else None
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                continue
            if isinstance(arg, ast.Name) and arg.id in ("addr_sql",):
                continue          # _address_condition() 이 돌려주는 상수 조각
            # `f"({or_clause})"` 만 예외. 따옴표 종류에 흔들리지 않게 **구조로** 본다.
            # (`or_clause` 는 `["property_type LIKE ?"] * len(...)` ― 길이만 가변이다.)
            if isinstance(arg, ast.JoinedStr):
                names = [ast.unparse(v.value) for v in arg.values
                         if isinstance(v, ast.FormattedValue)]
                lits = "".join(v.value for v in arg.values
                               if isinstance(v, ast.Constant) and isinstance(v.value, str))
                if names == ["or_clause"] and lits == "()":
                    continue
            bad.append("%s:%d %s" % (rel, node.lineno, ast.unparse(arg) if arg else "?"))
    check_true("WHERE 조각이 전부 상수", not bad,
               "상수가 아닌 조각은 값이 SQL 텍스트가 된다: %s" % bad)


# ---------------------------------------------------------------------------
# 7. 마이그레이션 러너의 실패/재실행 경로 (2026-08-13 Sprint 86 신설)
#
# 커버리지가 지목했다: `storage/migrations/run_migrations.py`의 두 분기가 미커버였다.
#
#     if applied: [SKIP] continue      재실행 시 이미 적용된 것을 건너뛴다(멱등성)
#     except: [FAIL] raise             실패하면 기록하지 않고 예외를 올린다
#
# 이 파일은 `docs/CLAUDE.md`가 "safe to re-run"이라 안내하는 부트스트랩이고, 신규 clone에서
# 스키마를 만드는 유일한 경로다. 두 분기 모두 **한 번도 실행된 적이 없었다.**
#
# 두 번째가 특히 중요하다. 실패한 마이그레이션이 `migration_history`에 기록되면 재실행이
# 그것을 건너뛰어 **스키마가 영구히 깨진 채로 남는다.** 현재 구현은 INSERT 전에 raise하므로
# 기록되지 않는다 - 그 순서를 고정한다.
# ---------------------------------------------------------------------------
def test_migration_runner_skip_and_failure():
    print("\n--- 7. 마이그레이션 러너: 재실행/실패 경로 ---")
    import shutil
    import sqlite3
    import tempfile
    import storage.database as dbmod
    import storage.migrations.run_migrations as runmig

    d = tempfile.mkdtemp(prefix="qa_mig_")
    real_db, real_dir = dbmod.DB_PATH, runmig.MIGRATIONS_DIR
    try:
        mig_dir = os.path.join(d, "migrations")
        os.makedirs(mig_dir)
        dbmod.DB_PATH = os.path.join(d, "t.db")
        runmig.MIGRATIONS_DIR = mig_dir

        def write(name, sql):
            with open(os.path.join(mig_dir, name), "w", encoding="utf-8") as fh:
                fh.write(sql)

        def history():
            c = sqlite3.connect(dbmod.DB_PATH)
            try:
                return [r[0] for r in c.execute(
                    "SELECT filename FROM migration_history ORDER BY id")]
            finally:
                c.close()

        def tables():
            c = sqlite3.connect(dbmod.DB_PATH)
            try:
                return sorted(r[0] for r in c.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"))
            finally:
                c.close()

        # --- 정상 적용 ---
        write("001_a.sql", "CREATE TABLE IF NOT EXISTS qa_a (x INTEGER);")
        write("002_b.sql", "CREATE TABLE IF NOT EXISTS qa_b (y INTEGER);")
        runmig.run()
        check("두 마이그레이션이 기록된다", history(), ["001_a.sql", "002_b.sql"])
        check_true("테이블이 실제로 생겼다", {"qa_a", "qa_b"} <= set(tables()), tables())

        # --- ★ 재실행은 멱등이다 ---
        #
        # 스킵 분기가 사라지면 같은 filename을 다시 INSERT하려다 UNIQUE 제약에 걸려
        # **예외가 그대로 올라온다**(스위트 크래시). 그 형태로 끝나면 원인이 안 보이므로
        # 붙잡아 깔끔한 FAIL로 바꾼다.
        rerun_error = None
        try:
            runmig.run()
        except Exception as exc:
            rerun_error = exc
        check_true("재실행이 예외 없이 끝난다", rerun_error is None,
                   "이미 적용된 것을 건너뛰는 분기가 사라졌는가? "
                   "같은 filename 재INSERT로 UNIQUE에 걸린다: %r" % (rerun_error,))
        check("재실행해도 이력이 늘지 않는다", history(), ["001_a.sql", "002_b.sql"])

        # 새 파일만 추가로 적용된다(앞의 둘은 건너뛴다).
        write("003_c.sql", "CREATE TABLE IF NOT EXISTS qa_c (z INTEGER);")
        try:
            runmig.run()
        except Exception as exc:
            check_true("새 파일 추가 실행이 예외 없이 끝난다", False, repr(exc))
        check("새 파일만 추가된다", history(), ["001_a.sql", "002_b.sql", "003_c.sql"])

        # --- ★ 실패한 마이그레이션은 기록되지 않는다 ---
        write("004_bad.sql", "CREATE TABLE qa_d (w INTEGER);\nTHIS IS NOT SQL;")
        raised = False
        try:
            runmig.run()
        except Exception:
            raised = True
        check("실패는 예외로 올라온다(삼키지 않는다)", raised, True)
        check_true("실패한 파일은 이력에 없다", "004_bad.sql" not in history(), history())
        check("앞선 이력은 그대로", history(), ["001_a.sql", "002_b.sql", "003_c.sql"])

        # --- 부분 적용 위험을 사실로 고정한다 ---
        #
        # `conn.executescript()`는 실행 전에 **암묵적으로 커밋**한다. 그래서 여러 문장짜리
        # 마이그레이션이 중간에 실패하면 **앞 문장은 이미 반영된 채 남는다.**
        # 그런데 이력에는 기록되지 않으므로 재실행이 처음부터 다시 돌린다 - 앞 문장이
        # `IF NOT EXISTS` 같은 가드 없이 쓰였다면 "already exists"로 **영원히 완료되지 못한다.**
        #
        # 이것은 지금까지 발현된 적이 없다(18개 전부 정상 적용됨). 그러나 019를 쓰는 사람이
        # 알아야 하는 성질이라 검사로 남긴다 - 코드는 바꾸지 않았다(실행 모델 변경은
        # 부트스트랩 전체에 영향을 준다).
        check_true("실패해도 앞 문장은 남아 있다(부분 적용)",
                   "qa_d" in tables(),
                   "이 전제가 바뀌었다면 위 주석과 019 작성 지침을 갱신해야 한다: %s" % tables())

        # 재실행하면 같은 지점에서 다시 실패한다(가드 없는 문장의 결과).
        raised_again = False
        try:
            runmig.run()
        except Exception:
            raised_again = True
        check("가드 없는 문장은 재실행에서도 실패한다", raised_again, True)
        check_true("여전히 이력에 없다", "004_bad.sql" not in history(), history())
    finally:
        dbmod.DB_PATH, runmig.MIGRATIONS_DIR = real_db, real_dir
        shutil.rmtree(d, ignore_errors=True)


def run():
    test_get_connection_fk_parameter()
    test_soft_delete_columns()
    test_migration_history_complete()
    test_requirements_covers_all_imports()
    test_error_codes_defined_documented_emitted()
    test_storage_sources_are_tracked()
    test_no_new_duplicate_indexes()
    test_no_new_tracked_but_ignored_files()
    test_migration_runner_skip_and_failure()
    test_code_dependent_unique_constraints()
    test_powershell_scripts_have_bom()
    test_source_bom_matches_head()
    test_court_list_integrity()
    test_init_db_upgrades_old_schema()
    test_api_never_reads_legacy_doc_flags()
    test_list_gets_never_return_success_false()
    test_no_confusable_column_misuse()
    test_no_new_sql_text_interpolation()
    test_init_db_failure_is_loud()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
