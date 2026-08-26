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
import io
import re
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
    #
    # `sqlite_` 접두사는 SQLite가 **예약한 내부 이름**이라 스키마가 만들 수 있는 것이
    # 아니다. 이 비교의 목적은 "부트스트랩이 빠뜨린 **우리 테이블**"을 찾는 것이므로
    # 엔진이 알아서 만드는 것은 전부 뺀다.
    #
    #   sqlite_sequence   AUTOINCREMENT가 쓰이면 자동 생성 (원래부터 빼고 있었다)
    #   sqlite_stat1      ★ ANALYZE가 만드는 **통계** 테이블이다 (2026-08-25 추가).
    #                     운영 DB에서 한 번이라도 ANALYZE를 돌리면 생기는데, 부트스트랩은
    #                     통계를 만들 이유가 없으므로 영원히 못 만든다 — 즉 이 검사가
    #                     **고칠 수 없는 이유로 영구히 붉어진다.** 실제로 그렇게 됐다
    #                     (2026-08-25: 운영 DB에 sqlite_stat1 39행). 그 상태를 방치하면
    #                     이 검사가 잡아야 할 **진짜 스키마 누락**이 그 옆에 묻힌다.
    #   sqlite_autoindex_*  UNIQUE 제약이 만드는 자동 인덱스(type='table'로는 안 잡히지만
    #                     같은 예약 접두사이므로 규칙을 하나로 둔다)
    #
    # 접두사 하나로 규칙을 세우면 앞으로 sqlite_stat4 등이 생겨도 따라온다.
    only_live = sorted(t for t in (live_tables - made)
                       if not t.startswith("sqlite_"))
    check("운영에만 있고 부트스트랩으로는 못 만드는 테이블 없음", only_live, [])

    only_new = sorted(made - live_tables - {"sqlite_sequence"})
    if only_new:
        # 실패는 아니다 — 운영 DB가 아직 최신 마이그레이션을 안 받았을 수 있다. 다만 눈에는 띄어야 한다.
        print("   [주의] 부트스트랩에만 있는 테이블(운영 DB가 뒤처졌을 수 있음): %s"
              % ", ".join(only_new))
    print("   운영 %d개 / 부트스트랩 %d개" % (len(live_tables), len(made)))


# ---------------------------------------------------------------------------
# 3-B. 부트스트랩 스키마 == 운영 스키마, **컬럼/인덱스 단위까지** (2026-08-15 Sprint 122)
#
# 위 test_bootstrap_matches_live_schema()는 "같은 테이블 집합인가"만 본다. 실제로는
# **테이블 이름은 같은데 컬럼 제약이나 인덱스가 다른** 경우가 있었다 - 실측(2026-08-15):
#
#     auction_case.court_code       fresh=nullable       live=NOT NULL
#     payment_webhooks.raw_payload  fresh=NOT NULL       live=nullable
#     payment_webhooks.processing_status  fresh=DEFAULT 'RECEIVED'   live=기본값 없음
#     registry_credits.amount / registry_credit_logs.delta  fresh=DEFAULT '0'  live=기본값 없음
#     payment_logs / payment_webhooks / registry_credit_logs / registry_credits
#         인덱스 존재 여부가 서로 다름(양쪽 다 상대에 없는 인덱스가 있다)
#     audit_logs.idx_audit_logs_admin_id            live에만 있음(추적 불가, test_schema_hygiene.py
#         KNOWN_DUPLICATE_INDEXES에도 별도로 기록됨)
#
# 원인: `storage/migrations/014_create_payment_logs.sql`/`011_.../016_...` 같은 파일이
# **이미 운영 DB에 적용된 뒤 내용이 편집됐다.** 마이그레이션 러너는 파일명으로만 "적용됨"을
# 판단해 스킵하므로(001~019 전부 이미 `migration_history`에 있다), 편집된 내용은 운영 DB에
# **다시 반영되지 않는다.** 그 결과 지금 파일을 그대로 실행하는 fresh clone은 운영과 다른
# (이 경우는 더 엄격한) 제약을 갖게 된다 - `payment_webhooks.raw_payload NOT NULL`은 실제로
# `api/v1/payment_logs.py:_dump()`가 `payload is None`이면 `None`을 그대로 반환하는 경로가
# 있어(운영에서는 nullable이라 통과하지만) fresh clone에서는 INSERT가 IntegrityError로
# 죽을 수 있다 - "운영에서는 되는데 새 배포에서만 깨지는" 정확히 그 모양이다.
#
# 여기서는 라이브 DB 스키마를 고치지 않는다(스키마 변경은 승인 영역). 지금 상태를
# **알려진 것으로 못 박고, 새로운 드리프트가 조용히 늘면 잡는다** - 이 저장소가 반복해서
# 쓰는 상한/allowlist 패턴과 같다.
# ---------------------------------------------------------------------------

# (table, (col_name, col_type, notnull, default)) - fresh clone에만 있고 운영에는 없는 컬럼 정의
# ★ 2026-08-26 migration 023 이 payment_webhooks / registry_credits /
#   registry_credit_logs 의 제약 4건을 **소스(더 엄격한 쪽)에 맞췄다.** 세 테이블 다 0행이라
#   재작성이 무손실이었다(합성 행으로 id 보존·NULL 승격까지 사본에서 검증).
#
#   `auction_case.court_code` 만 남는다 — 여기는 **live 쪽이 옳아서** 일부러 두는 것이다.
#   이 열은 `UNIQUE(court_code, case_no)` 의 앞자리인데 SQLite 는 NULL 을 서로 다른 값으로
#   보므로, 소스처럼 nullable 이면 court_code 가 NULL 인 중복 사건이 제약을 그냥 통과한다.
#   즉 fresh 에 맞추면 **방어가 사라진다.** 방향을 반대로(소스를 NOT NULL 로) 잡아야 하고,
#   그건 1,796행짜리 테이블 재작성이라 별도 마이그레이션으로 다룬다.
# ★ 2026-08-26 migration 024 가 마지막 하나(auction_case.court_code)까지 닫았다.
#   여기는 **소스를 라이브에 맞춘** 유일한 항목이다 — UNIQUE(court_code, case_no) 의
#   앞자리라 nullable 이면 SQLite 가 NULL 을 서로 다른 값으로 봐서 중복 사건이 제약을
#   그냥 통과한다(= 방어가 사라진다). 이제 fresh 와 live 의 스키마가 **완전히 같다.**
KNOWN_FRESH_ONLY_COLUMNS = set()
# 운영에만 있고 fresh clone에는 없는 컬럼 정의(같은 컬럼의 다른 제약 - 위 항목과 쌍을 이룬다)
KNOWN_LIVE_ONLY_COLUMNS = set()
# (table, index_name) - fresh clone에만 있고 운영에는 없는 인덱스(파일 편집 후 운영에 재적용 안 됨)
# ★ 2026-08-26 migration 022 가 이 5개를 **라이브에 채웠다.** 목록을 비운다 —
#   이제 "소스는 선언하는데 라이브에만 없는 인덱스"는 하나도 허용되지 않는다.
#   (컬럼 제약 드리프트 4건은 테이블 재작성이 필요해 아직 남아 있다 — 아래 두 목록 참고.)
KNOWN_FRESH_ONLY_INDEXES = set()
# 운영에만 있고 fresh clone에는 없는 인덱스
KNOWN_LIVE_ONLY_INDEXES = {
    # ("audit_logs", "idx_audit_logs_admin_id") 는 2026-08-26 migration 021 이 **지웠다.**
    #   저장소 어디에서도 만들지 않는(전수 grep 0건) 순수 중복이라 fresh clone 에는 원래
    #   없었고, 이제 라이브에서도 없어져 **격차 자체가 사라졌다.** 목록에서 뺀다.
    ("registry_credit_logs", "idx_registry_credit_logs_user_id"),
}


def test_bootstrap_matches_live_schema_columns_and_indexes():
    """부트스트랩 스키마가 운영과 **컬럼 제약/인덱스 단위**까지 같은가.

    test_bootstrap_matches_live_schema()가 놓치는 사각지대를 메운다 - 테이블 집합이
    같아도 그 안의 컬럼 제약이나 인덱스가 다르면 "부트스트랩은 성공했는데 동작이 다른"
    상태가 된다(정확히 이 저장소가 반복해서 잡아 온 패턴).
    """
    print("\n--- 3-B. 부트스트랩 스키마 == 운영 스키마 (컬럼/인덱스) ---")
    import storage.database as dbmod
    import storage.migrate_v4_1 as v41

    live_path = os.path.join(REPO_ROOT, "auction.db")
    if not os.path.isfile(live_path):
        print("[SKIP] 운영 DB가 없다 - 비교 생략")
        return

    def _schema(db_path, readonly):
        conn = (sqlite3.connect("file:%s?mode=ro" % db_path.replace("\\", "/"), uri=True)
                if readonly else sqlite3.connect(db_path))
        try:
            tables = sorted(r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))
            cols, idxs = set(), set()
            for t in tables:
                for c in conn.execute("PRAGMA table_info(%s)" % t).fetchall():
                    cols.add((t, (c[1], c[2], c[3], c[4])))
                for r in conn.execute("PRAGMA index_list(%s)" % t).fetchall():
                    if not r[1].startswith("sqlite_autoindex"):
                        idxs.add((t, r[1]))
            return cols, idxs
        finally:
            conn.close()

    live_cols, live_idxs = _schema(live_path, readonly=True)

    tmp = tempfile.mkdtemp(prefix="qa_boot_cols_")
    db = os.path.join(tmp, "fresh.db")
    saved = dbmod.DB_PATH
    dbmod.DB_PATH = db
    try:
        dbmod.init_db()
        v41.migrate()
        _load_runner().run()
        fresh_cols, fresh_idxs = _schema(db, readonly=False)
    finally:
        dbmod.DB_PATH = saved
        shutil.rmtree(tmp, ignore_errors=True)

    fresh_only_cols = fresh_cols - live_cols
    live_only_cols = live_cols - fresh_cols
    new_fresh_only_cols = sorted(fresh_only_cols - KNOWN_FRESH_ONLY_COLUMNS)
    new_live_only_cols = sorted(live_only_cols - KNOWN_LIVE_ONLY_COLUMNS)
    check("새로운 컬럼 제약 드리프트 없음(fresh에만 있는 것)", new_fresh_only_cols, [])
    check("새로운 컬럼 제약 드리프트 없음(운영에만 있는 것)", new_live_only_cols, [])

    fresh_only_idxs = fresh_idxs - live_idxs
    live_only_idxs = live_idxs - fresh_idxs
    new_fresh_only_idxs = sorted(fresh_only_idxs - KNOWN_FRESH_ONLY_INDEXES)
    new_live_only_idxs = sorted(live_only_idxs - KNOWN_LIVE_ONLY_INDEXES)
    check("새로운 인덱스 드리프트 없음(fresh에만 있는 것)", new_fresh_only_idxs, [])
    check("새로운 인덱스 드리프트 없음(운영에만 있는 것)", new_live_only_idxs, [])

    # 2026-08-17 Sprint 144: `sorted()`를 그냥 부르면 여기서 **테스트가 TypeError로 죽었다.**
    #   컬럼 항목은 (table, (name, type, notnull, default)) 모양이고 `default`는 값이
    #   없으면 None, 있으면 문자열이다("'RECEIVED'"). 두 항목의 앞 세 요소가 같으면
    #   정렬 비교가 네 번째로 내려가 None < str 을 시도하고 그 순간 죽는다.
    #   실제로 KNOWN_LIVE_ONLY_COLUMNS의 payment_webhooks.processing_status(default=None)와
    #   KNOWN_FRESH_ONLY_COLUMNS의 같은 컬럼(default="'RECEIVED'")이 정확히 그 쌍이다.
    #   드리프트가 **해소됐을 때만** 이 줄에 도달하므로, 상황이 좋아진 순간에 테스트가
    #   죽는 최악의 방향이었다(위 check() 4개는 이미 전부 통과한 뒤다).
    #   값 자체를 비교하지 않고 문자열로 찍어 정렬한다 - 여기서 필요한 것은 사람이 읽을
    #   목록의 안정적인 순서뿐이다.
    resolved_cols = sorted((KNOWN_FRESH_ONLY_COLUMNS - fresh_only_cols)
                            | (KNOWN_LIVE_ONLY_COLUMNS - live_only_cols), key=repr)
    resolved_idxs = sorted((KNOWN_FRESH_ONLY_INDEXES - fresh_only_idxs)
                            | (KNOWN_LIVE_ONLY_INDEXES - live_only_idxs), key=repr)
    if resolved_cols or resolved_idxs:
        print("   [정리됨] 더 이상 드리프트가 아닌 알려진 항목 - 위 KNOWN_* 상수에서 빼십시오:")
        for c in resolved_cols:
            print("      컬럼", c)
        for i in resolved_idxs:
            print("      인덱스", i)
    print("   알려진 컬럼 드리프트 %d건 / 알려진 인덱스 드리프트 %d건 (전부 알려진 항목)"
          % (len(KNOWN_FRESH_ONLY_COLUMNS) + len(KNOWN_LIVE_ONLY_COLUMNS),
             len(KNOWN_FRESH_ONLY_INDEXES) + len(KNOWN_LIVE_ONLY_INDEXES)))


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

        # ── 배치가 부르는 스크립트가 실재하는가 (2026-08-14 추가) ────────────
        #
        # `test_crawl_exit_code.py` §8은 **알려진 후보 목록**의 파일 존재와 input() 부재를
        # 본다. 그러나 배치가 **무엇을 부르는지**는 보지 않는다. 그래서 배치를 고쳐
        # 존재하지 않는 스크립트를 부르게 만들면 아무 검사도 걸리지 않는다 —
        # 그 경우 Task Scheduler는 매일 조용히 실패한다(파일이 없으면 cmd는 계속 진행한다).
        #
        # 이 검사도 REM을 건너뛴 본문만 본다(위와 같은 이유 — 주석에 예시가 들어 있다).
        body = "\n".join(l for l in lines
                         if not (l.strip().upper().startswith("REM") or l.strip().startswith("::")))
        called = sorted(set(re.findall(r"([A-Za-z_][A-Za-z0-9_]*\.py)", body)))
        check_true("%s: 부르는 파이썬 스크립트를 찾았다" % name, len(called) > 0, called)
        missing = [s for s in called if not os.path.exists(os.path.join(REPO_ROOT, s))]
        check("%s: 부르는 스크립트가 모두 실재한다" % name, missing, [])
        print("      %s -> %s" % (name, ", ".join(called)))


# ---------------------------------------------------------------------------
# 6. "safe to re-run"이 **실제 부트스트랩에서** 사실인가 (2026-08-14 신설)
#
# `docs/CLAUDE.md`는 부트스트랩이 "safe to re-run"이라고 안내한다. 그런데 그 주장을
# 검증하는 것은 `test_schema_hygiene.py` §7뿐이고, 거기서 쓰는 것은 **합성 마이그레이션**
# (`CREATE TABLE IF NOT EXISTS qa_a ...`)이다. 즉 러너의 skip 분기는 검증됐지만
# **실제 19개 파일로 두 번 돌렸을 때 안전한가는 확인된 적이 없었다.**
#
# 이게 공허한 걱정이 아닌 이유: 마이그레이션 019는 이렇게 생겼다.
#
#     ALTER TABLE subscriptions ADD COLUMN payment_id INTEGER REFERENCES payments(id);
#
# `ALTER TABLE ADD COLUMN`은 **그 자체로는 멱등이 아니다** — 두 번 실행하면
# "duplicate column name"으로 죽는다. 안전한 이유는 오직 `migration_history` 기반
# skip 하나뿐이다. 그 방어가 실제 파일에서 동작하는지 여기서 직접 확인한다.
#
# 스키마 비교는 테이블 이름만 보지 않는다 — **컬럼 목록과 인덱스까지** 본다.
# 이름만 같고 컬럼이 늘어나는 종류의 비멱등성이 정확히 019 같은 경우다.
# ---------------------------------------------------------------------------
def _full_schema(db_path):
    """테이블/인덱스 이름 + 테이블별 컬럼 목록. 재실행 전후를 비교할 지문."""
    c = sqlite3.connect(db_path)
    try:
        tables = sorted(r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))
        indexes = sorted(r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"))
        cols = {t: [r[1] for r in c.execute("PRAGMA table_info(%s)" % t)] for t in tables}
        return {"tables": tables, "indexes": indexes, "columns": cols}
    finally:
        c.close()


def test_bootstrap_is_idempotent():
    print("\n--- 6. 부트스트랩을 두 번 돌려도 안전한가 (CLAUDE.md 'safe to re-run') ---")
    import storage.database as dbmod
    import storage.migrate_v4_1 as v41

    tmp = tempfile.mkdtemp(prefix="qa_boot_idem_")
    db = os.path.join(tmp, "fresh.db")
    saved = dbmod.DB_PATH
    dbmod.DB_PATH = db
    try:
        # 1회차
        dbmod.init_db()
        v41.migrate()
        _load_runner().run()
        first_schema = _full_schema(db)
        first_applied = _applied(db)

        # 2회차 — 같은 3단계를 그대로 다시 돌린다
        crashed = None
        try:
            dbmod.init_db()
            v41.migrate()
            _load_runner().run()
        except SystemExit as exc:
            crashed = "SystemExit: %s" % exc
        except Exception as exc:  # noqa: BLE001
            crashed = "%s: %s" % (type(exc).__name__, exc)

        check_true("두 번째 실행이 예외 없이 끝난다", crashed is None, crashed)
        if crashed:
            return

        second_schema = _full_schema(db)
        second_applied = _applied(db)

        # 목록을 통째로 찍으면 로그가 수십 줄로 불어나 진짜 실패가 묻힌다 —
        # **차이만** 보고한다(같으면 빈 목록이라 한 줄로 끝난다).
        def diff(label, a, b):
            check("재실행 후 %s에 사라진 것" % label, sorted(set(a) - set(b)), [])
            check("재실행 후 %s에 새로 생긴 것" % label, sorted(set(b) - set(a)), [])

        check("재실행이 마이그레이션을 중복 기록하지 않는다",
              len(second_applied), len(first_applied))
        diff("마이그레이션 기록", first_applied, second_applied)
        diff("테이블", first_schema["tables"], second_schema["tables"])
        diff("인덱스", first_schema["indexes"], second_schema["indexes"])

        # ★ 019 같은 ADD COLUMN이 두 번 먹으면 여기서 잡힌다.
        drifted = {t: (first_schema["columns"][t], second_schema["columns"][t])
                   for t in first_schema["columns"]
                   if first_schema["columns"][t] != second_schema["columns"].get(t)}
        check("재실행 후 컬럼 구성이 같다(ADD COLUMN 중복 없음)", drifted, {})
        # 출력 리터럴에는 U+2014(—) 대신 U+2015(―)를 쓴다 — cp949 콘솔에서 깨진다
        # (`test_console_encoding.py`가 강제한다).
        print("   테이블 %d개 / 인덱스 %d개 / 마이그레이션 %d개 ― 2회 실행 후 동일"
              % (len(second_schema["tables"]), len(second_schema["indexes"]),
                 len(second_applied)))
    finally:
        dbmod.DB_PATH = saved
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# 5. `docs/CLAUDE.md`가 부트스트랩에 대해 말하는 것이 사실인가 (2026-08-14 신설)
#
# CLAUDE.md는 새 개발자와 새 세션이 **가장 먼저 읽는 색인**이다. 여기가 틀리면 그
# 아래 모든 판단이 틀어진다. 그런데 이 문서는 이미 여러 번 낡았고, 그때마다 본문에
# "정정" 문단이 덧붙는 방식으로만 고쳐졌다 — 즉 **드리프트를 잡아 주는 장치가 없다.**
#
# 2026-08-14에 실제로 두 건이 낡아 있었다.
#
#   "No `requirements.txt` exists"        -> 2026-08-11 Sprint 54에 신설돼 추적 중이었다
#   "applies numbered SQL files 001~018"  -> 019가 이미 있고 적용까지 돼 있었다
#
# 둘 다 사람이 눈으로 봐야만 발견된다. 그래서 **문서가 주장하는 사실을 코드로 대조한다.**
# 문장 표현이 아니라 "숫자/파일 존재" 같은 확인 가능한 주장만 검사한다 —
# 산문까지 고정하면 문서를 손볼 때마다 검사가 깨져서 오히려 신뢰를 잃는다.
# ---------------------------------------------------------------------------
def test_claude_md_bootstrap_claims_are_true():
    print("\n--- 5. docs/CLAUDE.md의 부트스트랩 서술이 사실인가 ---")
    import re

    doc_path = os.path.join(REPO_ROOT, "docs", "CLAUDE.md")
    if not os.path.exists(doc_path):
        print("[SKIP] docs/CLAUDE.md 없음")
        return
    doc = open(doc_path, encoding="utf-8-sig").read()

    mig_dir = os.path.join(REPO_ROOT, "storage", "migrations")
    numbers = sorted(int(m.group(1)) for f in os.listdir(mig_dir)
                     for m in [re.match(r"^(\d{3})_.*\.sql$", f)] if m)
    check_true("마이그레이션 파일을 찾았다", bool(numbers), numbers)

    # (1) "001~NNN" 범위 주장이 실제 파일 번호와 맞는가
    ranges = re.findall(r"(\d{3})\s*~\s*(\d{3})", doc)
    check_true("CLAUDE.md에 마이그레이션 범위 서술이 있다", bool(ranges), ranges)
    for lo, hi in ranges:
        check("CLAUDE.md가 말하는 마이그레이션 시작 번호", int(lo), numbers[0])
        check("CLAUDE.md가 말하는 마이그레이션 끝 번호", int(hi), numbers[-1])

    # (2) 번호가 비어 있지 않은가 (문서 범위가 맞아도 중간이 빠지면 안내가 거짓이 된다)
    check("마이그레이션 번호에 빠진 구간 없음",
          sorted(set(range(numbers[0], numbers[-1] + 1)) - set(numbers)), [])

    # (3) 존재/부재를 단정하는 서술이 실제와 맞는가
    #     ("No `requirements.txt` exists"가 정확히 이 부류로 틀려 있었다)
    #
    # ★ 함정: 이 문서의 관례는 낡은 문장을 지우는 대신 **그대로 인용하고 "정정"을 붙이는**
    #   것이다. 그래서 단순 문자열 검색은 *고쳐 놓은 문서*를 위반으로 잡는다 —
    #   이 검사를 처음 붙였을 때 실제로 그렇게 실패했다(같은 날 만든
    #   `test_pipeline_integrity.py` §9 스캐너가 자기 설명 주석을 잡은 것과 같은 부류다).
    #   그래서 **주변에 정정 표시가 있으면 살아 있는 주장이 아니라 인용으로 본다.**
    req = os.path.join(REPO_ROOT, "requirements.txt")
    if os.path.exists(req):
        CORRECTION = ("정정", "stale", "이전 버전", "예전", "더 이상")
        live_claims = []
        for m in re.finditer(r"No\s+`?requirements\.txt`?\s+exists", doc, re.I):
            around = doc[max(0, m.start() - 300):m.end() + 300]
            if not any(k in around for k in CORRECTION):
                live_claims.append(doc[max(0, m.start() - 60):m.end() + 60])
        check("requirements.txt가 있는데 '없다'고 단정한 자리 없음", live_claims, [])

    # (4) 부트스트랩 명령이 가리키는 파일이 실제로 있는가
    for rel in ("storage/migrate_v4_1.py", "storage/migrations/run_migrations.py",
                "storage/database.py", "api_server.py", "doc_worker.py",
                "mvp_scraper.py", "migrate_execute.py", "refresh_priority.py"):
        if rel in doc or rel.replace("/", "\\") in doc:
            check_true("CLAUDE.md가 언급한 %s 가 실재한다" % rel,
                       os.path.exists(os.path.join(REPO_ROOT, *rel.split("/"))), rel)




def test_db_path_does_not_depend_on_cwd():
    """DB 경로가 **작업 디렉터리에 의존하지 않는가** (2026-08-21 Sprint 246 신설).

    ## 왜 생겼나

    `storage/database.py` 는 예전에 `DB_PATH = "auction.db"` 였다. 상대경로라 **cwd 기준**
    으로 열린다. 그런데 `sqlite3.connect()` 는 파일이 없으면 **조용히 새로 만든다.**
    그래서 저장소 루트가 아닌 곳에서 서버를 띄우면:

        그 폴더에 0바이트 `auction.db` 가 생기고
        모든 조회가 `no such table: auction_item` 으로 실패한다

    실측(2026-08-21, 같은 코드를 별도 프로세스로 cwd 만 바꿔 임포트):

        cwd = 저장소 루트  -> auction_item 1,876행
        cwd = 다른 폴더    -> 그 폴더에 0바이트 auction.db 생성 / no such table

    같은 세션에 고친 `.env` cwd 의존(Sprint 245)과 같은 계열이고 **더 나쁘다** —
    환경변수는 비면 500 으로 시끄럽게 실패하지만, 이쪽은 빈 DB 를 만들어 놓고
    "데이터가 없다"처럼 보이게 한다. 운영자가 크롤이 안 돈 줄로 오해한다.

    ## 검사 방법

    **별도 프로세스를 다른 cwd 에서 띄운다.** 같은 프로세스 안에서는 이미 임포트된
    모듈의 `DB_PATH` 가 남아 있어 재현되지 않는다 - 그러면 검사가 공허해진다.
    """
    print("\n--- DB 경로가 작업 디렉터리에 의존하지 않는가 (Sprint 246) ---")
    import subprocess
    import tempfile
    import shutil

    repo = os.path.dirname(os.path.abspath(__file__))
    probe = (
        "import os, storage.database as db;"
        "c=db.get_connection();"
        "n=list(c.execute('select count(*) from auction_item'))[0][0];"
        "c.close();"
        "print('ROWS=%d STRAY=%d' % (n, 1 if os.path.exists('auction.db') else 0))"
    )

    def run_in(cwd):
        env = dict(os.environ)
        env["PYTHONPATH"] = repo
        env["PYTHONIOENCODING"] = "utf-8"
        r = subprocess.run([sys.executable, "-c", probe], cwd=cwd, env=env,
                           capture_output=True, timeout=180)
        out = (r.stdout or b"").decode("utf-8", "replace").strip()
        err = (r.stderr or b"").decode("utf-8", "replace").strip()
        m = re.search(r"ROWS=(\d+) STRAY=(\d)", out)
        return (int(m.group(1)), int(m.group(2))) if m else (None, (out + err)[:160])

    root_rows, root_stray = run_in(repo)
    check_true("저장소 루트에서 DB 를 연다(검사가 공허하지 않다)",
               isinstance(root_rows, int) and root_rows > 0,
               "-> %r" % (root_stray,))
    if not isinstance(root_rows, int) or root_rows <= 0:
        return

    tmp = tempfile.mkdtemp(prefix="qa_dbcwd_")
    try:
        other_rows, other_stray = run_in(tmp)
        check_true("다른 디렉터리에서도 임포트/조회가 성공한다",
                   isinstance(other_rows, int), "-> %r" % (other_stray,))
        if isinstance(other_rows, int):
            check("★ 다른 디렉터리에서도 **같은 DB** 를 읽는다(cwd 비의존)",
                  other_rows, root_rows)
            check("★ 다른 디렉터리에 빈 auction.db 를 만들지 않는다",
                  other_stray, 0)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # 소스 수준 가드 - 편집 시점에 되돌리는 것을 잡는다(주석 제외)
    src = io.open(os.path.join(repo, "storage", "database.py"),
                  encoding="utf-8-sig").read()
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    check_true("★ DB_PATH 가 상대경로 리터럴이 아니다",
               not re.search(r'^DB_PATH\s*=\s*["\'][^"\']*["\']\s*$', code, re.M),
               "-> DB_PATH = \"auction.db\" 는 cwd 기준이다. PROJECT_ROOT 기준 절대경로를 써라")
    check_true("★ DB_PATH 가 PROJECT_ROOT 기준으로 만들어진다",
               re.search(r"DB_PATH\s*=\s*os\.path\.join\(\s*PROJECT_ROOT", code) is not None,
               "-> 파일 위치 기준 절대경로여야 한다")


# ---------------------------------------------------------------------------
# 15. 제품이 **실제로 읽는** 환경변수가 전부 문서에 있는가
#     (2026-08-26, `docs/BUGS.md` #232)
#
# 왜 — `docs/ENVIRONMENT_VARIABLES.md` 는 운영자가 "무엇을 설정해야 하는가"를 보는
# 유일한 자리다. 코드가 새 변수를 읽기 시작했는데 문서에 없으면, 운영자는 그것을
# 설정하지 않고 배포한다. 그리고 대부분의 환경변수는 **없어도 조용히 폴백**하므로
# 배포 시점에는 아무 일도 안 일어난다(#206 이 정확히 그 모양이다).
#
# ★ 반대 방향(문서에는 있는데 코드가 안 읽는 것)은 **검사하지 않는다.**
#   `KG_*` / `SMTP_*` / `SENTRY_DSN` 등은 **아직 도입하지 않은 연동의 계획 항목**이고,
#   문서가 §B/§C 로 그렇게 분류하고 있다. 그것까지 실패로 만들면 계획을 적을 수 없다.
#
# ★ 이 검사는 **머신과 무관하다.** `.env` 의 값이 무엇인지는 보지 않는다 —
#   그것은 머신마다 다르고(BUGS #222), git 이 추적하지도 않는다.
#   보는 것은 "코드가 이 이름을 읽는가" 와 "문서가 이 이름을 아는가" 뿐이다.
# ---------------------------------------------------------------------------
def test_every_env_var_the_code_reads_is_documented():
    print("\n--- 15. 코드가 읽는 환경변수가 전부 문서에 있는가 (BUGS #232) ---")
    import glob
    import io as _io
    import re as _re

    root = os.path.dirname(os.path.abspath(__file__))
    targets = []
    for pattern in ("api/**/*.py", "storage/**/*.py", "crawler/**/*.py",
                    "config/*.py", "normalizer/*.py"):
        targets += glob.glob(os.path.join(root, pattern), recursive=True)
    targets += [os.path.join(root, f) for f in
                ("api_server.py", "doc_worker.py", "collect_documents.py",
                 "mvp_scraper.py", "migrate_execute.py", "refresh_priority.py")]

    # ★ 직접 호출(`os.getenv("X")`)과 **간접 호출**(`_env_flag("X", ...)`) 을 모두 잡는다.
    #   처음에 직접 호출만 정규식으로 찾았다가 `RATE_LIMIT_ENABLED` /
    #   `RATE_LIMIT_TRUST_FORWARDED` 를 놓쳤다 — 그 둘은 이름을 **인자로 넘겨** 읽는다.
    #   런타임 추적으로 확인하고 규칙을 넓혔다.
    DIRECT = _re.compile(r'os\.(?:getenv|environ\.get)\(\s*["\']([A-Z][A-Z0-9_]{2,})["\']')
    BRACKET = _re.compile(r'os\.environ\[\s*["\']([A-Z][A-Z0-9_]{2,})["\']')
    HELPER = _re.compile(r'_env_flag\(\s*["\']([A-Z][A-Z0-9_]{2,})["\']')

    read = {}
    for path in sorted(set(targets)):
        if not os.path.isfile(path):
            continue
        try:
            src = _io.open(path, encoding="utf-8-sig").read()
        except OSError:
            continue
        rel = os.path.relpath(path, root).replace("\\", "/")
        for rx in (DIRECT, BRACKET, HELPER):
            for name in rx.findall(src):
                read.setdefault(name, set()).add(rel)

    check_true("제품이 읽는 환경변수를 실제로 찾았다(검사가 공허하지 않다)",
               len(read) >= 8, sorted(read))

    doc_path = os.path.join(root, "docs", "ENVIRONMENT_VARIABLES.md")
    doc = _io.open(doc_path, encoding="utf-8-sig").read() if os.path.exists(doc_path) else ""
    check_true("ENVIRONMENT_VARIABLES.md 를 읽었다", bool(doc), doc_path)

    # ★ 부분 문자열이 아니라 **단어 경계**로 찾는다.
    #   `k in doc` 로 썼다가 변이 M3(문서의 `RATE_LIMIT_TRUST_FORWARDED` 를
    #   `..._FORWARDEDX` 로 바꾼다)을 **놓쳤다** — 지운 이름이 새 이름의 부분 문자열이라
    #   여전히 "문서에 있다"로 읽혔다. 이름이 바뀌거나 지워지는 것이 정확히 이 검사가
    #   잡아야 할 드리프트다.
    def _documented(name):
        return _re.search(r"(?<![A-Z0-9_])%s(?![A-Z0-9_])" % _re.escape(name), doc) is not None

    missing = sorted("%s (%s)" % (k, ", ".join(sorted(v))) for k, v in read.items()
                     if not _documented(k))
    check("★ 코드가 읽는 환경변수가 전부 문서에 있다", missing, [])
    if missing:
        print("      문서에 없으면 운영자가 설정하지 않고 배포한다:")
        for m in missing:
            print("        " + m)
    print("    코드가 읽는 환경변수 %d개" % len(read))

    # ★ 검출기 자체 검증 — 규칙이 직접/간접 호출을 모두 잡는지, 아무 대문자나 잡지는 않는지.
    sample = ('x = os.getenv("QA_DIRECT_ONE")\n'
              'y = os.environ["QA_BRACKET_TWO"]\n'
              'z = _env_flag("QA_HELPER_THREE", True)\n'
              'w = SOME_CONSTANT + "NOT_AN_ENV_VAR_JUST_TEXT"\n')
    got = set()
    for rx in (DIRECT, BRACKET, HELPER):
        got |= set(rx.findall(sample))
    check("검출기 자체 검증: 직접 호출을 잡는다", "QA_DIRECT_ONE" in got, True)
    check("검출기 자체 검증: 대괄호 접근을 잡는다", "QA_BRACKET_TWO" in got, True)
    check("검출기 자체 검증: 간접(_env_flag) 호출을 잡는다", "QA_HELPER_THREE" in got, True)
    check("검출기 자체 검증: 그냥 상수/문자열은 잡지 않는다",
          ("SOME_CONSTANT" in got or "NOT_AN_ENV_VAR_JUST_TEXT" in got), False)

    # ★ 문서 대조가 **부분 문자열로 속지 않는지**도 못박는다(변이 M3 가 그렇게 빠져나갔다).
    _sample_doc = "`RATE_LIMIT_TRUST_FORWARDEDX` 는 다른 이름이다"
    def _documented_in(name, text):
        return _re.search(r"(?<![A-Z0-9_])%s(?![A-Z0-9_])" % _re.escape(name), text) is not None
    check("검출기 자체 검증: 더 긴 이름에 묻힌 것을 '문서에 있다'로 읽지 않는다",
          _documented_in("RATE_LIMIT_TRUST_FORWARDED", _sample_doc), False)
    check("검출기 자체 검증: 정확히 같은 이름은 찾는다",
          _documented_in("RATE_LIMIT_TRUST_FORWARDED",
                         "`RATE_LIMIT_TRUST_FORWARDED` 설명"), True)


def run():
    print("=" * 60)
    print("fresh clone 부트스트랩 검증 (Sprint 99)")
    print("=" * 60)

    test_runner_refuses_without_prerequisites()
    test_full_bootstrap_from_scratch()
    test_bootstrap_matches_live_schema()
    test_bootstrap_matches_live_schema_columns_and_indexes()
    test_batch_scripts_create_logs_before_redirecting()
    test_claude_md_bootstrap_claims_are_true()
    test_bootstrap_is_idempotent()
    test_db_path_does_not_depend_on_cwd()
    test_every_env_var_the_code_reads_is_documented()

    print("\n" + "=" * 60)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL BOOTSTRAP TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
