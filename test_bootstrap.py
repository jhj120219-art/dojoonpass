"""
새로 clone한 저장소에서 **DB를 처음부터 만들 수 있는가** (2026-08-13 Sprint 99 신설).

    python test_bootstrap.py

왜 필요한가
-----------------------------------------------------------------------------
`auction.db`는 `.gitignore` 대상이라 **clone에는 존재하지 않는다.** 새 개발자, 새 배포,
장애 복구는 전부 스키마를 처음부터 만들어야 하는데, 그게 되는지 확인하는 검사가 없었다.

Sprint 99에 실제로 안 된다는 것을 실측했다. 안내대로 `init_db()` -> `run_migrations.py`
순으로 돌리면 **008에서 죽는다**:

    [FAIL] 008_create_search_indexes.sql: no such table: main.auction_item

`auction_item` / `auction_case` / `document_status` / `tenant_rights` / `rights_summary`를
만드는 것은 `storage/migrate_v4_1.py`인데, 그 단계가 어디에도 적혀 있지 않았다.
게다가 001~007은 이미 적용된 뒤라 DB가 **절반만 마이그레이션된 상태**로 남았다.

이 파일은 세 가지를 고정한다:

  1. 올바른 3단계 순서로 돌리면 **전부** 만들어진다 (19개 마이그레이션 / 핵심 테이블 전부)
  2. 선행 스키마 없이 러너를 돌리면 **아무것도 적용하지 않고** 안내와 함께 중단한다
     (예전처럼 절반 적용하고 죽지 않는다)
  3. 만들어진 스키마가 **API가 실제로 읽는 테이블**을 전부 포함한다

주의: 작업본 `auction.db`는 절대 건드리지 않는다. 전부 임시 디렉터리의 새 파일에 대고 돈다.
"""
import os
import sys
import shutil
import sqlite3
import tempfile
import importlib.util

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
failures = []


def check(name, actual, expected):
    if actual == expected:
        print("[PASS] %s: %r (expected %r)" % (name, actual, expected))
    else:
        print("[FAIL] %s: %r (expected %r)" % (name, actual, expected))
        failures.append(name)


def check_true(name, cond, detail=""):
    if cond:
        print("[PASS] %s" % name)
    else:
        print("[FAIL] %s -> %r" % (name, detail))
        failures.append(name)


# API/크롤러가 실제로 읽고 쓰는 테이블. 하나라도 없으면 그 기능이 통째로 죽는다.
CORE_TABLES = [
    "auction", "auction_item", "auction_case", "document_queue", "document_status",
    "document_version_log", "tenant_rights", "rights_summary",
    "favorites", "recent_items", "search_presets",
    "subscriptions", "payments", "payment_logs", "payment_webhooks",
    "registry_requests", "registry_usage", "registry_credits", "registry_credit_logs",
    "audit_logs", "document_collect_failures",
]


def _load_runner():
    """러너를 파일 경로로 로드한다(패키지 import 부작용을 피한다)."""
    path = os.path.join(REPO_ROOT, "storage", "migrations", "run_migrations.py")
    spec = importlib.util.spec_from_file_location("qa_run_migrations", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tables(db_path):
    c = sqlite3.connect(db_path)
    try:
        return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        c.close()


def _applied(db_path):
    c = sqlite3.connect(db_path)
    try:
        return [r[0] for r in c.execute(
            "SELECT filename FROM migration_history ORDER BY filename")]
    except sqlite3.OperationalError:
        return []
    finally:
        c.close()


def test_runner_refuses_without_prerequisites():
    """선행 스키마가 없으면 **아무것도 적용하지 않고** 중단해야 한다.

    예전에는 001~007을 적용한 뒤 008에서 죽어 DB를 절반만 마이그레이션된 상태로 남겼다.
    "실패했는데 일부는 반영됨"은 이 저장소가 계속 잡아 온 partial success 패턴이다.
    """
    print("\n--- 1. 선행 스키마 없이 러너를 돌리면 ---")
    import storage.database as dbmod

    tmp = tempfile.mkdtemp(prefix="qa_boot_no_prereq_")
    db = os.path.join(tmp, "empty.db")
    saved = dbmod.DB_PATH
    dbmod.DB_PATH = db
    try:
        dbmod.init_db()  # auction / document_queue / document_version_log 만 생긴다
        before = _tables(db)
        check_true("init_db()만으로는 auction_item이 없다", "auction_item" not in before, sorted(before))

        runner = _load_runner()
        stopped = None
        try:
            runner.run()
        except SystemExit as exc:
            stopped = str(exc)
        except Exception as exc:  # noqa: BLE001
            stopped = "%s: %s" % (type(exc).__name__, exc)

        check_true("선행 스키마가 없으면 중단한다", stopped is not None, stopped)
        # 무엇을 해야 하는지 알려줘야 한다 — 예전 메시지("no such table")로는 알 수 없었다.
        check_true("중단 메시지가 migrate_v4_1을 지목한다",
                   bool(stopped) and "migrate_v4_1" in stopped, stopped)

        # ★ 핵심: 아무 마이그레이션도 적용되지 않아야 한다.
        check("중단했으므로 적용된 마이그레이션이 없다", len(_applied(db)), 0)
        after = _tables(db)
        check("중단했으므로 테이블도 늘지 않았다", sorted(after - before), [])
    finally:
        dbmod.DB_PATH = saved
        shutil.rmtree(tmp, ignore_errors=True)


def test_full_bootstrap_from_scratch():
    """올바른 3단계로 돌리면 스키마가 **전부** 만들어진다."""
    print("\n--- 2. 3단계 부트스트랩 (init_db -> migrate_v4_1 -> run_migrations) ---")
    import storage.database as dbmod
    import storage.migrate_v4_1 as v41

    tmp = tempfile.mkdtemp(prefix="qa_boot_full_")
    db = os.path.join(tmp, "fresh.db")
    saved = dbmod.DB_PATH
    dbmod.DB_PATH = db
    try:
        dbmod.init_db()
        v41.migrate()
        _load_runner().run()

        made = _tables(db)
        applied = _applied(db)

        # 마이그레이션 파일 수와 적용 수가 같아야 한다 — 하나라도 조용히 건너뛰면 스키마가 어긋난다.
        sql_count = len([f for f in os.listdir(
            os.path.join(REPO_ROOT, "storage", "migrations")) if f.endswith(".sql")])
        check("마이그레이션이 전부 적용된다", len(applied), sql_count)

        missing = [t for t in CORE_TABLES if t not in made]
        check("핵심 테이블이 전부 만들어진다", missing, [])

        # 인덱스까지 생겼는지 — 008/009는 검색 성능의 근거다(테이블만 있고 인덱스가 없으면
        # 기능은 되지만 검색이 느려지고, 그건 조용히 넘어간다).
        c = sqlite3.connect(db)
        try:
            idx = {r[0] for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'")}
        finally:
            c.close()
        check_true("검색 인덱스가 만들어진다(008/009)", len(idx) > 0, len(idx))
        print("   테이블 %d개 / 인덱스 %d개 / 마이그레이션 %d개"
              % (len(made), len(idx), len(applied)))
    finally:
        dbmod.DB_PATH = saved
        shutil.rmtree(tmp, ignore_errors=True)


def test_bootstrap_matches_live_schema():
    """새로 만든 스키마가 **운영 DB와 같은 테이블 집합**인가.

    부트스트랩이 "돌긴 하는데 운영과 다른 스키마"를 만들면, 새 배포는 조용히 다른 DB를 갖게 된다.
    운영 DB는 읽기 전용으로만 연다.
    """
    print("\n--- 3. 부트스트랩 스키마 == 운영 스키마 ---")
    import storage.database as dbmod
    import storage.migrate_v4_1 as v41

    live_path = os.path.join(REPO_ROOT, "auction.db")
    if not os.path.isfile(live_path):
        print("[SKIP] 운영 DB가 없다 - 비교 생략")
        return

    live = sqlite3.connect("file:%s?mode=ro" % live_path.replace("\\", "/"), uri=True)
    try:
        live_tables = {r[0] for r in live.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        live.close()

    tmp = tempfile.mkdtemp(prefix="qa_boot_cmp_")
    db = os.path.join(tmp, "fresh.db")
    saved = dbmod.DB_PATH
    dbmod.DB_PATH = db
    try:
        dbmod.init_db()
        v41.migrate()
        _load_runner().run()
        made = _tables(db)
    finally:
        dbmod.DB_PATH = saved
        shutil.rmtree(tmp, ignore_errors=True)

    # 운영에만 있는 테이블 = 부트스트랩이 못 만드는 것. 이게 있으면 새 배포가 깨진다.
    # (`sqlite_sequence`는 AUTOINCREMENT가 쓰이면 자동 생성되므로 비교에서 뺀다.)
    only_live = sorted(live_tables - made - {"sqlite_sequence"})
    check("운영에만 있고 부트스트랩으로는 못 만드는 테이블 없음", only_live, [])

    only_new = sorted(made - live_tables - {"sqlite_sequence"})
    if only_new:
        # 실패는 아니다 — 운영 DB가 아직 최신 마이그레이션을 안 받았을 수 있다. 다만 눈에는 띄어야 한다.
        print("   [주의] 부트스트랩에만 있는 테이블(운영 DB가 뒤처졌을 수 있음): %s"
              % ", ".join(only_new))
    print("   운영 %d개 / 부트스트랩 %d개" % (len(live_tables), len(made)))


def test_batch_scripts_create_logs_before_redirecting():
    """예약 배치가 `logs\\`가 없는 새 배포에서 **조용히 성공으로 끝나지 않는가**.

    2026-08-13 Sprint 99 신설.

    `logs/`는 .gitignore 대상이라 새 배포에는 없다. 그 상태에서 `>> logs\\daily_run.log`는
    실패하는데 **cmd는 errorlevel을 0으로 둔다.** 그래서 실측하면 이렇게 된다:

        1. 리다이렉트가 실패해 파이썬 스크립트가 **아예 실행되지 않는다**
        2. errorlevel이 0이라 `if errorlevel 1` 실패 분기가 **타지 않는다**
        3. 마지막 [SUCCESS] 마커까지 지나 **exit /b 0**으로 끝난다

    아무것도 하지 않고 "성공"으로 보고한다. 이 배치들이 막으려고 만들어진 바로 그
    "실패 은폐"(2026-08-03~08-11 9일간 크롤 중단, 그 사이 진행 중 물건 41건까지 감소)가
    로그 디렉터리 부재라는 다른 입구로 재발하는 자리였다.

    cmd를 실제로 띄우지 않고 **소스에서** 고정한다 - 리다이렉트보다 mkdir이 먼저 오는지만
    보면 되고, 그게 이 결함의 정확한 조건이다.
    """
    print("\n--- 4. 예약 배치가 logs/를 먼저 만드는가 ---")
    import glob
    import re

    bats = sorted(glob.glob(os.path.join(REPO_ROOT, "run_*.bat")))
    check_true("검사할 배치 파일이 있다", len(bats) > 0, bats)

    for path in bats:
        name = os.path.basename(path)
        # 배치는 cp949로 저장돼 있을 수 있다 - 인코딩 때문에 검사를 잃지 않도록 관대하게 읽는다.
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.read().split("\n")

        mkdir_at = None
        redirect_at = None
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.upper().startswith("REM"):
                continue  # 주석 안의 예시 문구에 걸리지 않게 한다
            if mkdir_at is None and re.search(r"mkdir\s+\"?logs\"?", stripped, re.I):
                mkdir_at = i
            if redirect_at is None and re.search(r">>?\s*logs[\\/]", stripped):
                redirect_at = i

        check_true("%s: logs로 리다이렉트하는 줄이 있다" % name, redirect_at is not None, redirect_at)
        check_true("%s: logs 디렉터리를 만든다" % name, mkdir_at is not None,
                   "`if not exist \"logs\" mkdir \"logs\"`가 없다")
        if mkdir_at is not None and redirect_at is not None:
            # 순서가 핵심이다. 뒤에 있으면 첫 리다이렉트가 이미 실패한 뒤다.
            check_true("%s: mkdir이 첫 리다이렉트보다 먼저다" % name,
                       mkdir_at < redirect_at,
                       "mkdir=%d줄, 첫 리다이렉트=%d줄" % (mkdir_at + 1, redirect_at + 1))


def run():
    print("=" * 60)
    print("fresh clone 부트스트랩 검증 (Sprint 99)")
    print("=" * 60)

    test_runner_refuses_without_prerequisites()
    test_full_bootstrap_from_scratch()
    test_bootstrap_matches_live_schema()
    test_batch_scripts_create_logs_before_redirecting()

    print("\n" + "=" * 60)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL BOOTSTRAP TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
