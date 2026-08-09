"""
DB 스키마/커넥션 위생 회귀 테스트 (jose 불필요 — storage.database만 import).

test_api_regression.py를 정적 감사하며 발견한, 실행 전에는 드러나지 않았을 두 결함의 회귀
방어다(2026-08-08 Sprint 31):

    1) get_connection(enforce_foreign_keys=False) 시그니처 — 23번 섹션이 이 키워드 인자를
       호출하는데 예전 storage/database.py:get_connection()은 인자를 받지 않았다.
    2) favorites/search_presets의 deleted_at/deleted_by 컬럼 — 28번 섹션(Soft Delete,
       CTO 승인 10건 #6)이 검증하는데 Migration 010~016 복구 당시에는 코드 참조가 없다는
       이유로 의도적으로 빠뜨렸었다(migration 017로 추가).

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
    print("\n--- 3. migration_history completeness (001~017) ---")
    conn = dbmod.get_connection()
    try:
        applied = {r[0] for r in conn.execute("SELECT filename FROM migration_history")}
        expected_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "storage", "migrations")
        on_disk = {f for f in os.listdir(expected_dir) if f.endswith(".sql")}
        missing = sorted(on_disk - applied)
        check("every .sql file on disk is recorded as applied", missing, [])
    finally:
        conn.close()


def run():
    test_get_connection_fk_parameter()
    test_soft_delete_columns()
    test_migration_history_complete()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
