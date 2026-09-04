"""migration chain 전체 호환성 회귀 (2026-09-04 신설).

## 왜 이 파일이 따로 있나 — 기존 검사가 못 보는 자리

마이그레이션을 보는 검사가 이미 셋 있는데, 셋 다 **지금 문제가 되는 질문에는
답하지 않는다**:

    test_bootstrap.py            빈 DB 에서 부트스트랩이 되는가 + fresh vs 운영 **현재**
                                 스키마 드리프트. 운영 DB 가 뒤처져 있으면 그 드리프트가
                                 **당연히** 나므로, 그 실패가 "코드 결함"인지
                                 "아직 안 돌렸을 뿐"인지 구별해 주지 못한다.
    test_migration_atomicity.py  .sql 이 문장 단위로 깨끗이 쪼개지는가 (파싱 문제)
    test_schema_hygiene.py       디스크 .sql 과 `migration_history` 의 양방향 대조

빠진 질문은 이것이다:

> **아직 안 돌린 마이그레이션을 지금 운영 스키마에 돌리면 실제로 되는가?**

이 저장소는 마이그레이션 적용이 승인 영역이라 **운영과 저장소가 늘 몇 칸 벌어져
있다**(2026-09-04 기준 020 vs 031). 그 간격이 벌어질수록 "돌리면 되는지"를 아무도
모르는 채 쌓이고, 승인이 떨어진 날 처음 알게 된다 — 가장 나쁜 시점이다.

## 무엇을 하나

두 경로를 **둘 다** 만들어 비교한다. 운영 DB 는 **읽기만** 한다(온라인 백업 사본).

    (A) 빈 DB   -> init_db -> migrate_v4_1 -> 전체 마이그레이션
    (B) 운영 사본 -> 남은 마이그레이션 전부

그리고 확인한다: 무결성 · FK · 데이터 보존 · **실제 질의가 도는가**(기존 API /
FIELD / T2D) · 두 경로의 스키마가 같은가.

## 기대값을 손으로 적지 않는다

"31개"처럼 숫자를 박으면 032 가 들어온 날 이 파일도 고쳐야 한다. 그래서 기대값은
**디스크의 .sql 목록에서 유도한다** — 새 마이그레이션이 들어오면 이 검사가
자동으로 그것까지 검증한다.

    python test_migration_chain.py
"""
import contextlib
import importlib
import io
import os
import re
import shutil
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import storage.database as dbmod                      # noqa: E402
import storage.migrate_v4_1 as migv41                 # noqa: E402
import storage.migrations.run_migrations as runner    # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))
MIG_DIR = os.path.join(ROOT, "storage", "migrations")
LIVE_DB = dbmod.DB_PATH
_TMP = []
failures = []


def _out(text):
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    return str(text).encode(enc, errors="replace").decode(enc, errors="replace")


def check(name, actual, expected):
    ok = actual == expected
    print(_out("[%s] %s: %r%s" % ("PASS" if ok else "FAIL", name, actual,
                                  "" if ok else " (expected %r)" % (expected,))))
    if not ok:
        failures.append(name)


def check_true(name, cond, detail=""):
    ok = bool(cond)
    print(_out("[%s] %s%s" % ("PASS" if ok else "FAIL", name,
                              "" if ok else " -> %r" % (detail,))))
    if not ok:
        failures.append(name)


def migration_files():
    """디스크의 마이그레이션 파일 이름(정렬). **기대값의 유일한 출처다.**"""
    return sorted(f for f in os.listdir(MIG_DIR)
                  if re.match(r"^\d{3}_.*\.sql$", f))


def scratch(name):
    d = tempfile.mkdtemp(prefix="migchain-")
    _TMP.append(d)
    return os.path.join(d, name)


def build_fresh(path):
    """빈 DB -> 부트스트랩 3단계 (docs/CLAUDE.md 가 안내하는 순서 그대로)."""
    dbmod.DB_PATH = path
    with contextlib.redirect_stdout(io.StringIO()):
        dbmod.init_db()
        migv41.migrate()
        importlib.reload(runner)
        runner.run()


def build_from_live(path):
    """운영 **사본** -> 남은 마이그레이션 전부. 운영 DB 는 읽기만 한다."""
    dbmod.DB_PATH = LIVE_DB
    dbmod.snapshot_live_db(path)
    dbmod.DB_PATH = path
    with contextlib.redirect_stdout(io.StringIO()):
        importlib.reload(runner)
        runner.run()


def schema_of(path):
    conn = sqlite3.connect(path)
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
            " AND name NOT LIKE 'sqlite_%'")}
        cols = {t: {(r[1], r[2], r[3], r[4])
                    for r in conn.execute("PRAGMA table_info(%s)" % t)}
                for t in tables}
        idx = {(r[0], r[1]) for r in conn.execute(
            "SELECT tbl_name, name FROM sqlite_master WHERE type='index'"
            " AND name NOT LIKE 'sqlite_%'")}
        applied = [r[0] for r in conn.execute(
            "SELECT filename FROM migration_history ORDER BY 1")]
        return tables, cols, idx, applied
    finally:
        conn.close()


# 이 스키마 위에서 **실제로 도는지** 확인할 질의들.
#
# ★ 스키마가 "있다"와 "쓸 수 있다"는 다르다. 컬럼이 생겼어도 제품 질의가 참조하는
#   이름/조인이 어긋나면 런타임에야 안다. 그래서 제품이 실제로 쓰는 모양을 그대로 태운다.
#   (행이 0개여도 좋다 — 여기서 보는 것은 결과가 아니라 **실행 가능성**이다.)
PROBE_QUERIES = (
    ("기존 API: 검색 조인",
     "SELECT ai.*, ac.court_code FROM auction_item ai"
     " JOIN auction_case ac ON ac.id = ai.case_id LIMIT 1"),
    ("기존 API: 문서 상태",
     "SELECT * FROM document_status LIMIT 1"),
    ("기존 API: 관심물건 조인",
     "SELECT ai.*, f.created_at FROM favorites f"
     " LEFT JOIN auction_item ai ON f.item_id = ai.id LIMIT 1"),
    ("기존 API: 메모/태그 (026)",
     "SELECT memo, tags, source FROM favorite_notes LIMIT 1"),
    ("기존 파이프라인: 면적 (025)",
     "SELECT building_area, land_area FROM auction_item LIMIT 1"),
    ("기존 파이프라인: 접수일 (028)",
     "SELECT filed_date FROM auction LIMIT 1"),
    ("FIELD: 임장 조회 (030)",
     "SELECT status, completed_at, decision, decided_at FROM field_visits"
     " WHERE user_id = 'probe' AND item_id = 1"),
    ("FIELD: 체크 조인 (030)",
     "SELECT COUNT(*) FROM field_visit_checks c"
     " JOIN field_visits v ON v.id = c.visit_id WHERE v.user_id = 'probe'"),
    ("T2D: 처음 발견 -> 판단 (030+031)",
     "SELECT ri.first_viewed_at, fv.decided_at FROM field_visits fv"
     " JOIN recent_items ri ON ri.user_id = fv.user_id AND ri.item_id = fv.item_id"
     " WHERE fv.decided_at IS NOT NULL"),
    ("T2D: 최근본 정리(임장 보존) (030+031)",
     "SELECT id FROM recent_items WHERE user_id = 'probe'"
     "   AND item_id NOT IN (SELECT item_id FROM field_visits WHERE user_id = 'probe')"),
)


def verify(path, label, expected_files):
    tables, cols, idx, applied = schema_of(path)

    # 기대값은 **디스크에서 유도한다** - 숫자를 손으로 적지 않는다.
    check("%s: 적용된 마이그레이션이 디스크와 같다" % label, applied, expected_files)
    check("%s: 같은 마이그레이션이 두 번 적용되지 않았다" % label,
          len(applied), len(set(applied)))

    conn = sqlite3.connect(path)
    try:
        check("%s: integrity_check" % label,
              conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        check("%s: foreign_key_check 위반" % label,
              len(conn.execute("PRAGMA foreign_key_check").fetchall()), 0)
        broken = []
        for name, sql in PROBE_QUERIES:
            try:
                conn.execute(sql).fetchall()
            except sqlite3.Error as exc:
                broken.append("%s (%s)" % (name, exc))
        check("%s: 제품 질의 %d개가 전부 실행된다" % (label, len(PROBE_QUERIES)),
              broken, [])
    finally:
        conn.close()
    return tables, cols, idx, applied


def test_fresh_and_live_paths_converge():
    """빈 DB 경로와 운영 사본 경로가 **같은 스키마**에 도착하는가."""
    print("\n--- 1. fresh / 운영사본 두 경로 전체 적용 ---")
    expected = migration_files()
    check_true("마이그레이션 파일을 찾았다 (%d개)" % len(expected), len(expected) >= 20)
    # 번호가 비어 있으면 "전부 적용"이라는 말 자체가 성립하지 않는다.
    nums = [int(f[:3]) for f in expected]
    check("번호에 빠진 구간이 없다",
          sorted(set(range(nums[0], nums[-1] + 1)) - set(nums)), [])

    fresh = scratch("fresh.db")
    build_fresh(fresh)
    ft, fc, fi, fa = verify(fresh, "fresh", expected)

    live_copy = scratch("live.db")
    conn = sqlite3.connect(LIVE_DB)
    try:
        before = {t: conn.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
                  for t in ("auction_item", "recent_items", "document_queue")}
    finally:
        conn.close()
    build_from_live(live_copy)
    lt, lc, li, la = verify(live_copy, "운영사본", expected)

    # ★ 데이터가 그대로인가 - 마이그레이션이 행을 잃으면 승인 전에 알아야 한다.
    conn = sqlite3.connect(live_copy)
    try:
        for t, n in before.items():
            check("운영사본: %s 행 보존" % t,
                  conn.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0], n)
        # 031 은 기존 행을 메우지 않는다 - "모름"을 0 이나 지금 시각으로 채우면
        # T2D 가 거짓 숫자를 내놓는다.
        check("운영사본: 031 이 기존 행을 메우지 않는다(NULL 유지)",
              conn.execute("SELECT COUNT(*) FROM recent_items"
                           " WHERE first_viewed_at IS NULL").fetchone()[0],
              before["recent_items"])
    finally:
        conn.close()

    print("\n--- 2. 두 경로의 스키마가 같은가 ---")
    check("테이블 집합이 같다", sorted(ft ^ lt), [])
    check("컬럼 정의가 같다",
          sorted(t for t in (ft & lt) if fc[t] != lc[t]), [])
    check("인덱스가 같다", sorted(fi ^ li), [])
    check("적용 이력이 같다", fa, la)


def _ddl_ledger():
    """마이그레이션 .sql 을 **순서대로 재생**해 최종 객체 집합을 계산한다.

    ## 왜 파일 이름을 믿지 않나 (2026-09-04, 이 검사 자신의 거짓 양성)

    처음에는 `030_create_field_visits.sql` -> `field_visits` 처럼 **파일 이름에서
    표 이름을 유추**했다. 곧바로 정확한 파일 둘을 결함으로 지목했다:

        008_create_search_indexes.sql        표가 아니라 **인덱스**를 만든다
        016_create_audit_and_credit_logs.sql 표를 **둘**(audit_logs, credit_logs) 만든다

    이름은 사람이 읽으라고 붙인 요약이지 계약이 아니다. 요약을 계약으로 오해하면
    가드가 **맞는 코드를 고치라고 압박**한다 - 이 저장소가 피하려는 바로 그 방향이다.

    그래서 이름 대신 **DDL 본문을 읽는다.** 각 파일의 CREATE/DROP/RENAME 을 순서대로
    적용해 "이 체인이 끝나면 무엇이 있어야 하는가"를 유도한다. 새 마이그레이션은
    이름을 어떻게 짓든 자동으로 검증된다.

    반환: (있어야 하는 표, 있어야 하는 인덱스, 없어야 하는 객체)
    """
    tables, indexes, killed = set(), {}, set()

    def kill(name):
        killed.add(name)

    for fname in migration_files():
        sql = io.open(os.path.join(MIG_DIR, fname), encoding="utf-8-sig").read()
        # 주석은 지운다 - 주석 속 예시 DDL 을 실제 문장으로 세지 않기 위해.
        sql = re.sub(r"--[^\n]*", " ", sql)
        for m in re.finditer(
                r"\b(create\s+table(?:\s+if\s+not\s+exists)?|"
                r"create\s+(?:unique\s+)?index(?:\s+if\s+not\s+exists)?|"
                r"drop\s+table(?:\s+if\s+exists)?|"
                r"drop\s+index(?:\s+if\s+exists)?|"
                r"alter\s+table)\s+[\"`\[]?(\w+)[\"`\]]?"
                r"(?:\s+on\s+[\"`\[]?(\w+)[\"`\]]?|"
                r"\s+rename\s+to\s+[\"`\[]?(\w+)[\"`\]]?)?",
                sql, re.I):
            verb = re.sub(r"\s+", " ", m.group(1).lower())
            name, on_tbl, rename_to = m.group(2), m.group(3), m.group(4)
            if verb.startswith("create table"):
                tables.add(name)
                killed.discard(name)
            elif verb.startswith("drop table"):
                tables.discard(name)
                kill(name)
                # 표가 사라지면 그 표의 인덱스도 함께 사라진다.
                for i in [i for i, t in indexes.items() if t == name]:
                    del indexes[i]
                    kill(i)
            elif verb.startswith("create") and "index" in verb:
                indexes[name] = on_tbl
                killed.discard(name)
            elif verb.startswith("drop index"):
                indexes.pop(name, None)
                kill(name)
            elif verb.startswith("alter table") and rename_to:
                # 재작성 관용구: X_new 를 만들어 복사한 뒤 X 를 지우고 이름을 바꾼다.
                # SQLite 에서 인덱스는 표를 따라간다.
                tables.discard(name)
                tables.add(rename_to)
                kill(name)
                killed.discard(rename_to)
                for i, t in list(indexes.items()):
                    if t == name:
                        indexes[i] = rename_to
    return tables, indexes, killed


def test_migrations_actually_change_the_schema():
    """마이그레이션이 **실제로 무언가를 만들고 지웠는가**.

    ## 왜 따로 보나

    앞의 검사는 "두 경로가 같다"를 본다. 그런데 마지막 마이그레이션이 아무 일도 하지
    않아도 두 경로는 여전히 같다 - **빈 파일을 추가해도 통과한다.** 실제로 스키마가
    바뀌었는지는 따로 물어야 한다.
    """
    print("\n--- 3. 마이그레이션이 실제로 스키마를 바꿨는가 ---")
    want_tables, want_idx, killed = _ddl_ledger()

    # 공허하지 않은가 - 파싱이 빗나가 아무것도 못 읽으면 이 검사는 전부 통과한다.
    check_true("DDL 을 읽었다 - 표 %d개 / 인덱스 %d개 / 제거 %d개"
               % (len(want_tables), len(want_idx), len(killed)),
               len(want_tables) >= 10 and len(want_idx) >= 10 and len(killed) >= 5,
               (sorted(want_tables), sorted(want_idx), sorted(killed)))

    # ★ 파일 하나하나가 **무언가를 선언하는가**.
    #
    #   위의 원장은 저장소 전체를 합쳐서 본다. 그래서 빈 파일 하나가 섞여 들어와도
    #   합계는 그대로여서 조용히 통과한다. 실제로 그런 파일은 두 가지 중 하나다 -
    #   붙여넣다 만 파일이거나, 다른 곳에서 이미 한 일을 적어만 둔 파일. 둘 다
    #   "적용됨"으로 이력에 남아 다음 사람을 속인다.
    #
    #   DDL 이 아닌 문장(UPDATE 백필 등)만 있는 파일도 정상이므로, 세는 대상은
    #   "주석을 뺀 실행 문장이 하나라도 있는가"다.
    empty = []
    for fname in migration_files():
        body = io.open(os.path.join(MIG_DIR, fname), encoding="utf-8-sig").read()
        body = re.sub(r"--[^\n]*", " ", body)
        body = re.sub(r"/\*.*?\*/", " ", body, flags=re.S)
        if not re.search(r"\b(create|drop|alter|insert|update|delete|pragma)\b",
                         body, re.I):
            empty.append(fname)
    check("★ 아무 것도 선언하지 않는 마이그레이션 파일이 없다", empty, [])

    fresh = scratch("fresh2.db")
    build_fresh(fresh)
    tables, cols, idx, _ = schema_of(fresh)
    have_idx = {name for _tbl, name in idx}

    check("★ 마이그레이션이 만든 표가 전부 존재한다",
          sorted(want_tables - tables), [])
    check("★ 마이그레이션이 만든 인덱스가 전부 존재한다",
          sorted(set(want_idx) - have_idx), [])
    # 지운 것이 남아 있으면 재작성이 중간에 멎었다는 뜻이다(_new 잔재 등).
    check("★ 마이그레이션이 지운 객체가 남아 있지 않다",
          sorted(killed & (tables | have_idx)), [])

    # 이번에 들어온 둘은 이름으로도 직접 확인한다 - 파싱이 빗나가도 잡히도록
    # **독립적인 두 번째 근거**를 둔다.
    check_true("030 이 field_visits / field_visit_checks 를 만들었다",
               {"field_visits", "field_visit_checks"} <= tables,
               sorted(t for t in tables if "field" in t))
    check_true("031 이 recent_items.first_viewed_at 을 만들었다",
               any(c[0] == "first_viewed_at" for c in cols["recent_items"]),
               sorted(c[0] for c in cols["recent_items"]))


if __name__ == "__main__":
    try:
        test_fresh_and_live_paths_converge()
        test_migrations_actually_change_the_schema()
    finally:
        dbmod.DB_PATH = LIVE_DB
        for d in _TMP:
            shutil.rmtree(d, ignore_errors=True)
    print("")
    if failures:
        print(_out("FAILED (%d): %s" % (len(failures), ", ".join(failures))))
        sys.exit(1)
    print("ALL MIGRATION CHAIN TESTS PASSED")
    sys.exit(0)
