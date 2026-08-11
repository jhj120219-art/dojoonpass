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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import storage.database as dbmod

failures = []


def check(name, actual, expected):
    ok = actual == expected
    print("[%s] %s: %r (expected %r)" % ("PASS" if ok else "FAIL", name, actual, expected))
    if not ok:
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

    py_files = []
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
    # httpx는 import 스캔에 안 잡힐 수 있다(테스트 도구/전이 의존성) — 예외로 둔다.
    stale = sorted(listed - used_dists - {"httpx"})
    check("목록에만 있고 소스에서 안 쓰는 항목 없음", stale, [])

    print("   소스에서 발견한 third-party %d개: %s" % (len(imported), ", ".join(sorted(imported))))


def run():
    test_get_connection_fk_parameter()
    test_soft_delete_columns()
    test_migration_history_complete()
    test_requirements_covers_all_imports()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
