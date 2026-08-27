"""마이그레이션 러너(`storage/migrations/run_migrations.py`)의 **원자성** 회귀 테스트.

운영 DB 는 전혀 건드리지 않는다 — 시스템 임시 디렉터리에 만든 스크래치 DB 와
스크래치 마이그레이션 폴더에서만 돈다(`test_checkpoint_atomicity.py` 와 같은 관례:
OneDrive 동기화 폴더 밖으로 나가 무관한 flaky 요인을 없앤다).

배경 (2026-08-27, 크롤->DB 경로 감사에서 실측)
---------------------------------------------------------------------------
러너는 마이그레이션 한 파일을 `conn.executescript(sql)` 로 통째로 실행했다.
`executescript()` 는 **먼저 열린 트랜잭션을 커밋하고, 스크립트를 트랜잭션 밖에서
실행한다.** 파일 안에 BEGIN/COMMIT 이 없으면(이 저장소의 25개 파일 전부가 그렇다)
각 DDL 이 **문장 단위로 즉시 확정**된다. 그래서 파일 중간에서 실패하면:

    1. 앞선 문장들은 **이미 DB 에 남는다** (rollback 해도 되돌아오지 않는다 - 실측)
    2. `migration_history` 에는 아무것도 안 들어간다 (INSERT 가 뒤에 있다)
    3. 다음 실행에서 러너는 그 파일을 **처음부터 다시** 적용한다
    4. `ALTER TABLE ... ADD COLUMN` 이 `duplicate column name` 으로 죽는다
       (SQLite 에는 ADD COLUMN 용 IF NOT EXISTS 가 없다 - 025 주석이 이미 인정한다)
    5. 러너가 raise -> `run_daily.bat` 3단계가 exit 1 -> **mvp_scraper.py 가 아예 실행되지 않는다**

즉 한 번의 중간 실패가 **매일 06:00 크롤을 영구히 정지**시킨다. 사람이 손으로
DB 를 고치기 전에는 회복 경로가 없다.

더 나쁜 형태가 023/024 다. 이 파일들은 SQLite 의 제약 변경을 위해
`CREATE ..._new` -> `INSERT SELECT` -> `DROP TABLE 원본` -> `RENAME` 을 돈다.
DROP 과 RENAME **사이**에서 죽으면 원본 테이블이 **사라진 채로 확정**된다(결제 테이블이다).

무엇을 고정하는가
---------------------------------------------------------------------------
SQLite 는 (MySQL/Oracle 과 달리) **DDL 도 트랜잭션에 참여한다.** 그래서 파일 하나 +
history INSERT 를 **한 트랜잭션**으로 묶으면 위 5단계가 전부 사라진다:
실패하면 그 파일은 통째로 없던 일이 되고, 재실행이 그냥 성공한다.

    python test_migration_atomicity.py
"""
import sys
import os
import shutil
import sqlite3
import tempfile
import importlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

failures = []


def check_true(name, cond, detail=""):
    ok = bool(cond)
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name, ("" if ok else " -> " + str(detail))))
    if not ok:
        failures.append(name)


def _fresh_runner(mig_dir, db_path):
    """스크래치 폴더/스크래치 DB 를 보도록 러너를 갈아끼운 모듈 객체."""
    import storage.database as dbmod
    dbmod.DB_PATH = db_path
    import storage.migrations.run_migrations as runner
    importlib.reload(runner)
    runner.MIGRATIONS_DIR = mig_dir
    return runner


def _base_db(path):
    """러너의 선행 스키마 검사를 통과할 최소 DB."""
    c = sqlite3.connect(path)
    c.executescript(
        "CREATE TABLE auction (id INTEGER PRIMARY KEY, case_no TEXT);"
        "CREATE TABLE auction_case (id INTEGER PRIMARY KEY, case_no TEXT);"
        "CREATE TABLE auction_item (id INTEGER PRIMARY KEY, case_no TEXT);"
        "CREATE TABLE payment_webhooks (id INTEGER PRIMARY KEY, payload TEXT);"
        "INSERT INTO payment_webhooks (id, payload) VALUES (1, 'keep-me'), (2, 'keep-me-too');"
    )
    c.commit()
    c.close()


def _cols(path, table):
    c = sqlite3.connect(path)
    try:
        return [r[1] for r in c.execute("PRAGMA table_info(%s)" % table)]
    finally:
        c.close()


def _tables(path):
    c = sqlite3.connect(path)
    try:
        return set(r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"))
    finally:
        c.close()


def _history(path):
    c = sqlite3.connect(path)
    try:
        return [r[0] for r in c.execute(
            "SELECT filename FROM migration_history ORDER BY id")]
    except sqlite3.OperationalError:
        return []
    finally:
        c.close()


def _write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


# ---------------------------------------------------------------------------
# 1. 파일 중간 실패 -> 그 파일은 통째로 없던 일이 되어야 한다
#
#    025 와 **완전히 같은 모양**을 쓴다(ADD COLUMN 두 개 + CREATE INDEX). 마지막
#    문장만 없는 컬럼을 참조해 실패한다 - 운영에서는 오타/락/디스크/전원으로 같은 자리에
#    도달한다. 중요한 것은 실패 원인이 아니라 **실패 이후의 DB 상태**다.
# ---------------------------------------------------------------------------
def test_partial_failure_leaves_no_residue():
    print("\n--- 1. 중간 실패한 마이그레이션은 흔적을 남기지 않는다 ---")
    root = tempfile.mkdtemp(prefix="mig_atomic_")
    try:
        mig = os.path.join(root, "migrations")
        os.makedirs(mig)
        dbp = os.path.join(root, "scratch.db")
        _base_db(dbp)

        _write(os.path.join(mig, "900_boom.sql"),
               "ALTER TABLE auction_item ADD COLUMN bench_a REAL;\n"
               "ALTER TABLE auction_item ADD COLUMN bench_b REAL;\n"
               "CREATE INDEX idx_boom ON auction_item(no_such_column);\n")

        runner = _fresh_runner(mig, dbp)
        raised = None
        try:
            runner.run()
        except Exception as e:      # noqa: BLE001 - 실패는 예상된 것이다
            raised = e

        check_true("실패는 조용히 넘어가지 않는다(raise)", raised is not None, raised)

        cols = _cols(dbp, "auction_item")
        check_true("첫 ALTER 가 남지 않는다(bench_a)", "bench_a" not in cols, cols)
        check_true("둘째 ALTER 가 남지 않는다(bench_b)", "bench_b" not in cols, cols)
        check_true("실패한 파일은 history 에 없다",
                   "900_boom.sql" not in _history(dbp), _history(dbp))

        # 핵심: 파일을 고친 뒤 **그냥 다시 돌리면** 성공해야 한다.
        # 예전 러너에서는 여기서 duplicate column name 으로 영구히 막혔다.
        _write(os.path.join(mig, "900_boom.sql"),
               "ALTER TABLE auction_item ADD COLUMN bench_a REAL;\n"
               "ALTER TABLE auction_item ADD COLUMN bench_b REAL;\n"
               "CREATE INDEX idx_boom ON auction_item(bench_a);\n")
        rerun_error = None
        try:
            runner.run()
        except Exception as e:      # noqa: BLE001
            rerun_error = e
        check_true("고친 뒤 재실행이 그냥 성공한다", rerun_error is None, rerun_error)
        check_true("재실행 후 컬럼이 생긴다",
                   set(("bench_a", "bench_b")) <= set(_cols(dbp, "auction_item")),
                   _cols(dbp, "auction_item"))
        check_true("재실행 후 history 에 기록된다",
                   "900_boom.sql" in _history(dbp), _history(dbp))
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------------------
# 2. DROP -> RENAME 재작성 중간 실패에서 **원본 테이블이 사라지지 않는다**
#
#    023/024 가 쓰는 바로 그 모양이다. 여기서 원본이 날아가면 결제 데이터가 사라진다.
# ---------------------------------------------------------------------------
def test_table_rewrite_failure_keeps_original():
    print("\n--- 2. 테이블 재작성이 중간에 죽어도 원본이 남는다 ---")
    root = tempfile.mkdtemp(prefix="mig_rewrite_")
    try:
        mig = os.path.join(root, "migrations")
        os.makedirs(mig)
        dbp = os.path.join(root, "scratch.db")
        _base_db(dbp)

        # ★ 실패 지점은 **DROP 과 RENAME 사이**여야 한다. 여기가 진짜 위험 구간이다.
        #
        #   RENAME 이후에 죽게 하면 옛 러너에서도 이 검사가 통과한다 - INSERT SELECT 가
        #   이미 데이터를 옮겼고 RENAME 도 끝나서 결과만 보면 멀쩡하기 때문이다.
        #   그건 방어가 아니라 **실패 지점을 안전한 곳으로 골라 준 것**이다(2026-08-27에
        #   이 테스트를 그렇게 썼다가 실측으로 잡았다).
        #
        #   DROP 과 RENAME 사이에서 죽으면 옛 러너는 이렇게 된다:
        #     - `payment_webhooks` 는 **사라진 채 확정**된다
        #     - 데이터는 `payment_webhooks_new` 라는 엉뚱한 이름 밑에 남는다
        #     - 재실행은 `INSERT ... SELECT FROM payment_webhooks` 에서
        #       `no such table` 로 죽는다 -> **영구 정지**
        _write(os.path.join(mig, "901_rewrite.sql"),
               "CREATE TABLE IF NOT EXISTS payment_webhooks_new "
               "(id INTEGER PRIMARY KEY, payload TEXT NOT NULL);\n"
               "INSERT INTO payment_webhooks_new (id, payload) "
               "SELECT id, payload FROM payment_webhooks;\n"
               "DROP TABLE payment_webhooks;\n"
               "SELECT no_such_column;\n"
               "ALTER TABLE payment_webhooks_new RENAME TO payment_webhooks;\n")

        runner = _fresh_runner(mig, dbp)
        try:
            runner.run()
        except Exception:
            pass

        tables = _tables(dbp)
        check_true("원본 payment_webhooks 가 살아 있다",
                   "payment_webhooks" in tables, sorted(tables))
        check_true("중간 산출물 _new 가 남지 않는다",
                   "payment_webhooks_new" not in tables, sorted(tables))

        c = sqlite3.connect(dbp)
        try:
            rows = c.execute("SELECT payload FROM payment_webhooks ORDER BY id").fetchall()
        except sqlite3.OperationalError as e:
            rows = [("<%s>" % e,)]
        finally:
            c.close()
        check_true("데이터가 보존된다(2행)",
                   [r[0] for r in rows] == ["keep-me", "keep-me-too"], rows)

        # 그리고 **재실행으로 회복 가능해야 한다** - 원자적이면 이 파일은 아직
        # 적용 전 상태이므로, 고친 뒤 다시 돌리면 그냥 성공한다.
        _write(os.path.join(mig, "901_rewrite.sql"),
               "CREATE TABLE IF NOT EXISTS payment_webhooks_new "
               "(id INTEGER PRIMARY KEY, payload TEXT NOT NULL);\n"
               "INSERT INTO payment_webhooks_new (id, payload) "
               "SELECT id, payload FROM payment_webhooks;\n"
               "DROP TABLE payment_webhooks;\n"
               "ALTER TABLE payment_webhooks_new RENAME TO payment_webhooks;\n")
        rerun_error = None
        try:
            runner.run()
        except Exception as e:      # noqa: BLE001
            rerun_error = e
        check_true("재작성 마이그레이션은 고친 뒤 재실행으로 회복된다",
                   rerun_error is None, rerun_error)
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------------------
# 3. 정상 경로 회귀 - 여러 문장짜리 파일이 **전부** 적용된다
#
#    원자성을 얻으려고 문장을 직접 쪼개므로, 쪼개기가 주석/문자열/여러 줄 문장을
#    망가뜨리지 않는지 함께 고정한다. 이 저장소의 실제 마이그레이션이 쓰는 형태만 담았다.
# ---------------------------------------------------------------------------
def test_multi_statement_file_fully_applied():
    print("\n--- 3. 여러 문장짜리 파일이 전부 적용된다 ---")
    root = tempfile.mkdtemp(prefix="mig_multi_")
    try:
        mig = os.path.join(root, "migrations")
        os.makedirs(mig)
        dbp = os.path.join(root, "scratch.db")
        _base_db(dbp)

        _write(os.path.join(mig, "902_multi.sql"),
               "-- 주석 줄. 세미콜론이 들어 있어도 문장 경계가 아니다;\n"
               "-- 한글 주석과 괄호(`foo()` 참고)도 그대로 지나가야 한다\n"
               "CREATE TABLE IF NOT EXISTS multi_a (\n"
               "    id INTEGER PRIMARY KEY,\n"
               "    label TEXT DEFAULT 'a;b'   -- 문자열 안의 세미콜론\n"
               ");\n"
               "\n"
               "CREATE INDEX IF NOT EXISTS idx_multi_a_label ON multi_a(label);\n"
               "INSERT INTO multi_a (id, label) VALUES (1, 'x;y');\n"
               "ALTER TABLE auction_item ADD COLUMN multi_col TEXT;\n"
               "-- 파일 끝의 주석만 있는 꼬리\n")

        runner = _fresh_runner(mig, dbp)
        err = None
        try:
            runner.run()
        except Exception as e:      # noqa: BLE001
            err = e
        check_true("정상 파일은 예외 없이 적용된다", err is None, err)
        check_true("CREATE TABLE 적용", "multi_a" in _tables(dbp), sorted(_tables(dbp)))
        check_true("ALTER 적용", "multi_col" in _cols(dbp, "auction_item"),
                   _cols(dbp, "auction_item"))

        c = sqlite3.connect(dbp)
        try:
            row = c.execute("SELECT label FROM multi_a WHERE id=1").fetchone()
            idx = [r[0] for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='multi_a'")]
        except sqlite3.OperationalError:
            row, idx = None, []
        finally:
            c.close()
        check_true("문자열 안 세미콜론이 잘리지 않는다", row is not None and row[0] == "x;y", row)
        check_true("CREATE INDEX 적용", "idx_multi_a_label" in idx, idx)
        check_true("history 기록", "902_multi.sql" in _history(dbp), _history(dbp))

        # 재실행은 SKIP 되어야 한다(멱등)
        err2 = None
        try:
            runner.run()
        except Exception as e:      # noqa: BLE001
            err2 = e
        check_true("적용 완료된 파일 재실행은 무해하다", err2 is None, err2)
        check_true("history 가 중복되지 않는다",
                   _history(dbp).count("902_multi.sql") == 1, _history(dbp))
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------------------
# 4. 실 마이그레이션 25개가 **실제로** 쪼개기를 통과하는지
#
#    합성 파일만 검사하면 쪼개기의 진짜 입력을 검증하지 못한다. 저장소의 .sql 을
#    그대로 읽어 각 조각이 SQLite 가 인정하는 완전한 문장인지 본다.
# ---------------------------------------------------------------------------
def test_real_migration_files_split_cleanly():
    print("\n--- 4. 저장소의 실제 .sql 이 깨끗하게 쪼개진다 ---")
    import storage.migrations.run_migrations as runner
    mig_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "storage", "migrations")
    files = sorted(f for f in os.listdir(mig_dir) if f.endswith(".sql"))
    check_true("마이그레이션 파일이 발견된다", len(files) >= 25, len(files))

    split = getattr(runner, "split_sql_statements", None)
    check_true("러너가 문장 분해기를 노출한다", callable(split), split)
    if not callable(split):
        return

    total = 0
    for fn in files:
        sql = open(os.path.join(mig_dir, fn), encoding="utf-8").read()
        stmts = list(split(sql))
        total += len(stmts)
        bad = [s for s in stmts if not sqlite3.complete_statement(s)]
        check_true("%s: 모든 조각이 완전한 문장" % fn, not bad, bad[:1])
        # 주석뿐인 조각은 나오지 않아야 한다(실행하면 예외가 된다)
        empty = [s for s in stmts
                 if not "".join(l for l in s.splitlines()
                                if not l.strip().startswith("--")).strip(" \t\r\n;")]
        check_true("%s: 주석뿐인 조각이 없다" % fn, not empty, empty[:1])
    print("     (실제 문장 총 %d개)" % total)


if __name__ == "__main__":
    test_partial_failure_leaves_no_residue()
    test_table_rewrite_failure_keeps_original()
    test_multi_statement_file_fully_applied()
    test_real_migration_files_split_cleanly()
    print("")
    if failures:
        print("FAILED %d: %s" % (len(failures), ", ".join(failures)))
        sys.exit(1)
    print("ALL PASS")
    sys.exit(0)
