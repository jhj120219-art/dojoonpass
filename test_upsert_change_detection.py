"""`upsert_batch()` 의 **변경 감지** 회귀 테스트.

운영 DB 는 건드리지 않는다 — `snapshot_live_db()` 로 스키마만 뜬 뒤 비운 스크래치 사본만 쓴다.

배경 (2026-08-27, docs/BUGS.md #249 후속)
---------------------------------------------------------------------------
예전에는 값이 이미 같아도 **매번 18컬럼 UPDATE 를 보내 행을 다시 썼다.** 법원 자료는
대부분 어제와 같으므로 그 대부분이 아무것도 바꾸지 않는 쓰기였다.

지금은 `UPDATE ... WHERE <식별키> AND (col IS NOT ? OR ...)` 로 **DB 가 판정**한다.
문장 수는 예전과 같고(SELECT 1 + UPDATE 1) **실제 쓰기만 사라진다.**

    1,876행 재크롤   38.6ms -> 23.9ms  (1.6배)   쓴 행 1,876 -> 0
   10,000행 재크롤  241.6ms -> 120.4ms (2.0배)   쓴 행 10,000 -> 0

★ 첫 시도는 **더 느렸다.** 15개 컬럼을 함께 SELECT 해 파이썬에서 튜플로 비교했더니
  1,876행에서 41.6ms -> 63.4ms(0.7배)였다. 넓은 SELECT 와 튜플 생성 비용이 절약한
  쓰기보다 컸다. 비교를 SQL 로 옮기고서야 이득이 났다. **측정 없이 "덜 쓰면 빠르다"고
  믿었으면 성능을 되레 깎은 채 끝났을 것이다.**

이 테스트가 지키는 것
---------------------------------------------------------------------------
속도가 아니라 **정확성**이다. "안 쓴다"의 유일한 위험은 써야 할 때 안 쓰는 것이므로,
UPDATE 가 건드리는 필드를 **하나씩 따로** 바꿔 가며 전부 반영되는지 본다.
WHERE 목록에서 필드가 빠지면 이 검사가 바로 잡는다.

    python test_upsert_change_detection.py
"""
import sys
import os
import sqlite3
import shutil
import tempfile
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import storage.database as dbmod

logging.disable(logging.CRITICAL)

failures = []


def check(name, actual, expected):
    ok = actual == expected
    print("[%s] %s: %r (expected %r)" % ("PASS" if ok else "FAIL", name, actual, expected))
    if not ok:
        failures.append(name)


def check_true(name, cond, detail=""):
    ok = bool(cond)
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name, "" if ok else " -> " + str(detail)))
    if not ok:
        failures.append(name)


_TMP = []


# 운영 DB 경로를 **한 번만** 붙잡아 둔다 (2026-08-27, BUGS #257).
#
# ★ 예전에는 `scratch_db()` 가 그때그때의 `dbmod.DB_PATH` 에서 스냅샷을 떴다. 그런데
#   이 함수는 마지막 줄에서 `dbmod.DB_PATH` 를 **방금 만든 스크래치로 바꾼다.** 즉
#   두 번째 호출부터는 실 DB 가 아니라 **직전 스크래치의 사본**을 뜨고 있었다.
#
#   행은 지우므로 데이터는 안 넘어온다 — 그래서 지금까지 아무도 몰랐다. 넘어오는 것은
#   **스키마 객체**다. 6-B 가 유도를 깨뜨리려고 심은 트리거가 6-C/6-D 까지 따라가
#   집계를 흔들었다(실측: 6-D 의 `inserted` 가 1 이 아니라 2 로 나왔다. 그 검사만
#   단독으로 돌리면 1 이다).
#
#   검사끼리 조용히 오염되는 모양이고, 이 세션에 고친 #251(찢어진 DB 사본)과 같은
#   부류다 — **격리한 줄 알았는데 아니었다.**
_LIVE_DB_PATH = dbmod.DB_PATH


def scratch_db():
    d = tempfile.mkdtemp(prefix="upsert_cd_")
    _TMP.append(d)
    path = os.path.join(d, "scratch.db")
    dbmod.DB_PATH = _LIVE_DB_PATH      # 항상 **실 DB** 에서 뜬다 (직전 스크래치가 아니라)
    dbmod.snapshot_live_db(path)
    c = sqlite3.connect(path)
    try:
        c.execute("PRAGMA foreign_keys=OFF")
        for t in [r[0] for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' AND name<>'migration_history'")]:
            c.execute('DELETE FROM "%s"' % t)
        c.commit()
    finally:
        c.close()
    dbmod.DB_PATH = path
    return path


def row(**over):
    r = {
        "court_code": "B100001", "court_name": "테스트법원",
        "case_no": "2026타경000001", "item_no": "1",
        "property_type": "아파트", "sido": "서울특별시", "sigungu": "강남구",
        "dong": "역삼동", "lot_number": "1-1",
        "full_address": "서울특별시 강남구 역삼동 1-1",
        "appraisal_price": 100000000, "minimum_bid_price": 70000000,
        "auction_date": "2027-03-15", "status": "신건",
        "validation_status": "PASS", "validation_reasons": "",
        "crawl_date": "2026-08-27",
    }
    r.update(over)
    return r


def one(path, sql, args=()):
    c = sqlite3.connect(path)
    try:
        r = c.execute(sql, args).fetchone()
        return r[0] if r else None
    finally:
        c.close()


# ---------------------------------------------------------------------------
# 1. 값이 그대로면 쓰지 않는다 (그러나 "저장 성공"이다)
# ---------------------------------------------------------------------------
def test_unchanged_is_not_written():
    print("\n--- 1. 무변화 재투입 ---")
    path = scratch_db()
    r1 = dbmod.upsert_batch([row()])
    check("최초는 신규", r1, {"inserted": 1, "updated": 0, "unchanged": 0, "failed": 0})
    before_ts = one(path, "SELECT updated_at FROM auction")

    r2 = dbmod.upsert_batch([row()])
    check("재투입은 변화없음", r2,
          {"inserted": 0, "updated": 0, "unchanged": 1, "failed": 0})
    check("행수는 그대로", one(path, "SELECT COUNT(*) FROM auction"), 1)
    # ★ updated_at 이 그대로여야 한다 — 이것이 "쓰지 않았다"의 증거다.
    #   동시에 그 컬럼이 비로소 의미를 갖는다("마지막으로 실제로 변한 시각").
    check("updated_at 이 바뀌지 않았다", one(path, "SELECT updated_at FROM auction"), before_ts)


# ---------------------------------------------------------------------------
# 2. 변이 테스트 — UPDATE 가 건드리는 필드를 **하나씩** 바꿔 전부 반영되는지
#
#    WHERE 의 변경 감지 목록에서 어느 하나가 빠지면 그 필드는 영원히 갱신되지 않는다.
#    "조용히 옛 값을 보여 준다"가 이 최적화의 유일한 실패 모양이다.
# ---------------------------------------------------------------------------
FIELDS = [
    ("court_name", "바뀐법원"),
    ("property_type", "다세대"),
    ("sido", "경기도"),
    ("sigungu", "성남시"),
    ("dong", "정자동"),
    ("lot_number", "999-9"),
    ("full_address", "경기도 성남시 정자동 999-9"),
    ("appraisal_price", 200000000),
    ("minimum_bid_price", 50000000),
    ("auction_date", "2027-09-09"),
    ("status", "유찰 2회"),
    ("validation_status", "FAIL"),
    ("validation_reasons", "가격 이상"),
    ("crawl_date", "2026-09-01"),
]


def test_every_field_change_is_written():
    print("\n--- 2. 필드를 하나씩 바꾸면 전부 반영된다 (변이) ---")
    for field, newval in FIELDS:
        path = scratch_db()
        dbmod.upsert_batch([row()])
        res = dbmod.upsert_batch([row(**{field: newval})])
        check("%s 변경 -> updated 1" % field, res["updated"], 1)
        check("%s 변경 -> unchanged 0" % field, res["unchanged"], 0)
        check("%s 가 DB 에 반영됐다" % field,
              one(path, "SELECT %s FROM auction" % field), newval)


# ---------------------------------------------------------------------------
# 3. NULL 안전성 — `<>` 가 아니라 `IS NOT` 여야 한다
#
#    SQLite 에서 `NULL <> 'x'` 는 참이 아니라 **NULL**(=거짓 취급)이다. 그래서 `<>` 로
#    쓰면 **NULL 이 든 열의 변경을 통째로 놓친다.** 레거시 행에는 NULL 이 실재한다.
# ---------------------------------------------------------------------------
def test_null_columns_are_detected():
    print("\n--- 3. NULL 이 든 열의 변경도 잡는다 (IS NOT) ---")
    path = scratch_db()
    dbmod.upsert_batch([row()])
    # 레거시 행을 흉내 낸다 — 여러 열을 NULL 로 만든다
    c = sqlite3.connect(path)
    c.execute("UPDATE auction SET dong=NULL, full_address=NULL, status=NULL,"
              " validation_reasons=NULL")
    c.commit()
    c.close()
    check("전제: NULL 로 만들었다", one(path, "SELECT dong FROM auction"), None)

    res = dbmod.upsert_batch([row()])
    check("NULL -> 값 변경이 감지된다", res["updated"], 1)
    check("dong 이 채워졌다", one(path, "SELECT dong FROM auction"), "역삼동")
    check("full_address 가 채워졌다",
          one(path, "SELECT full_address FROM auction"), "서울특별시 강남구 역삼동 1-1")
    check("status 가 채워졌다", one(path, "SELECT status FROM auction"), "신건")

    # 이제는 같으므로 다시 조용해야 한다
    res2 = dbmod.upsert_batch([row()])
    check("채운 뒤에는 변화없음", res2["unchanged"], 1)

    # ── ★ 열을 **하나씩만** 비운다 ─────────────────────────────────────────
    #
    #   위처럼 여러 열을 동시에 비우면 서로가 서로를 가려 준다 — 한 열의 비교가
    #   망가져 있어도 **다른 열이 UPDATE 를 유발**해 그 김에 같이 써지기 때문이다.
    #   실제로 `IS NOT` 를 `<>` 로 되돌린 변이가 그렇게 살아남았다(2026-08-27).
    #   NULL 비교가 열마다 제대로 되는지 보려면 한 번에 하나만 비워야 한다.
    for col, want in (("dong", "역삼동"),
                      ("full_address", "서울특별시 강남구 역삼동 1-1"),
                      ("lot_number", "1-1"),
                      ("status", "신건"),
                      ("validation_reasons", ""),
                      ("property_type", "아파트"),
                      ("sigungu", "강남구")):
        path2 = scratch_db()
        dbmod.upsert_batch([row()])
        c2 = sqlite3.connect(path2)
        c2.execute("UPDATE auction SET %s=NULL" % col)
        c2.commit()
        c2.close()
        res3 = dbmod.upsert_batch([row()])
        check("%s 만 NULL 일 때 변경이 감지된다" % col, res3["updated"], 1)
        check("%s 가 실제로 채워졌다" % col,
              one(path2, "SELECT %s FROM auction" % col), want)


# ---------------------------------------------------------------------------
# 4. 섞인 배치 — 신규/갱신/무변화/실패가 한 배치에 같이 와도 정확히 센다
# ---------------------------------------------------------------------------
def test_mixed_batch_counts():
    print("\n--- 4. 섞인 배치의 계수 ---")
    path = scratch_db()
    base = [row(case_no="2026타경00000%d" % i) for i in range(1, 4)]
    dbmod.upsert_batch(base)

    mixed = [
        row(case_no="2026타경000001"),                       # 무변화
        row(case_no="2026타경000002", status="유찰 1회"),     # 갱신
        row(case_no="2026타경000004"),                       # 신규
        row(case_no="2026타경000005", appraisal_price="가격미정"),  # 실패(정수 변환 불가)
    ]
    res = dbmod.upsert_batch(mixed)
    check("신규 1", res["inserted"], 1)
    check("갱신 1", res["updated"], 1)
    check("무변화 1", res["unchanged"], 1)
    check("실패 1", res["failed"], 1)
    check_true("합계가 입력 수와 같다(조용히 사라지는 행이 없다)",
               sum(res.values()) == len(mixed), res)
    check("DB 행수 = 3 + 신규 1", one(path, "SELECT COUNT(*) FROM auction"), 4)


# ---------------------------------------------------------------------------
# 5. persisted 계약 — 전부 무변화인 날도 **성공**이어야 한다
#
#    이 최적화의 진짜 위험은 성능이 아니라 여기다. `CrawlOutcome.persisted` 가
#    `unchanged` 를 빼먹으면 정상적인 날에 크롤이 실패로 끝나고 `migrate_execute.py`
#    가 아예 실행되지 않는다.
# ---------------------------------------------------------------------------
def test_all_unchanged_day_is_success():
    print("\n--- 5. 전부 무변화인 날의 성패 판정 ---")
    from models.crawl_outcome import CrawlOutcome
    path = scratch_db()
    rows = [row(case_no="2026타경00%04d" % i) for i in range(20)]
    dbmod.upsert_batch(rows)
    res = dbmod.upsert_batch(rows)
    check("전부 무변화", res["unchanged"], 20)

    oc = CrawlOutcome(courts=60, collected=20,
                      inserted=res["inserted"], updated=res["updated"],
                      unchanged=res["unchanged"], upsert_failed=res["failed"])
    check("persisted 가 무변화를 포함한다", oc.persisted, 20)
    check("★ 종료 코드 0 (정상적인 날)", oc.exit_code(), 0)
    check("실패 사유 없음", oc.failure_reason(), None)


# ---------------------------------------------------------------------------
# 6. 한 문장 upsert 로 바뀐 뒤 **집계의 전제**가 지켜지는가 (2026-08-27, BUGS #256)
#
# 이제 신규/갱신/무변화를 행마다 묻지 않는다. 배치 앞뒤로 두 번만 세서 유도한다:
#
#     inserted  = 행 수 증가분
#     written   = total_changes 증가분
#     updated   = written - inserted
#     unchanged = 처리한 행 - written
#
# 이 유도는 **한 upsert 가 정확히 0 또는 1행만 바꾼다**는 전제 위에 있다.
# `auction` 에 트리거나 이 테이블을 참조하는 외래키가 생기면 그 전제가 깨진다.
# 아래 검사들은 (a) 전제가 지금 성립하고 (b) 깨졌을 때 **조용하지 않은지**를 본다.
# ---------------------------------------------------------------------------
def test_no_triggers_or_referencing_fks_on_auction():
    print("\n--- 6-A. 집계 유도의 전제 (트리거/참조 외래키 없음) ---")
    path = scratch_db()
    c = sqlite3.connect(path)
    try:
        trig = c.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='auction'"
        ).fetchall()
        check("auction 에 트리거가 없다", [t[0] for t in trig], [])

        refs = []
        for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'"
                              " AND name NOT LIKE 'sqlite_%'").fetchall():
            for fk in c.execute('PRAGMA foreign_key_list("%s")' % t).fetchall():
                if fk[2] == "auction":
                    refs.append("%s -> auction(%s)" % (t, fk[4]))
        check("auction 을 참조하는 외래키가 없다", refs, [])
        if trig or refs:
            print("      -> 생겼다면 upsert_batch 의 집계 유도를 다시 봐야 한다."
                  " total_changes 가 한 행보다 많이 세게 된다.")
    finally:
        c.close()


def test_broken_derivation_is_loud_not_silent():
    """전제가 깨지면 **틀린 숫자를 조용히 내보내지 않는다.**

    트리거를 실제로 심어 유도를 깨뜨린다. 이 검사가 없으면 위 자기 검사는 장식이다.
    """
    print("\n--- 6-B. 전제가 깨지면 시끄럽게 운다 ---")
    path = scratch_db()
    dbmod.upsert_batch([row(case_no="2026타경000001")])

    # auction 이 갱신될 때마다 **다른 행도** 만드는 트리거 - total_changes 가 부풀어
    # 유도가 깨진다. 실제로 이런 트리거를 심어 두는 것이 아니라, "전제가 깨진 상태"를
    # 재현해 경보가 울리는지만 본다.
    c = sqlite3.connect(path)
    try:
        c.execute("CREATE TRIGGER qa_break_derivation AFTER UPDATE ON auction "
                  "BEGIN "
                  "  INSERT INTO auction(court_code, case_no, item_no) "
                  "    VALUES('QA-TRIG', 'QA-'||NEW.id||'-'||NEW.updated_at, '9'); "
                  "END")
        c.commit()
    finally:
        c.close()

    class Grab(logging.Handler):
        def __init__(self):
            logging.Handler.__init__(self)
            self.records = []

        def emit(self, record):
            self.records.append(record)

    logging.disable(logging.NOTSET)          # 이 파일은 위에서 로깅을 꺼 두었다
    grab = Grab()
    lg = logging.getLogger(dbmod.__name__)
    lg.addHandler(grab)
    prev = lg.level
    lg.setLevel(logging.ERROR)
    try:
        res = dbmod.upsert_batch([row(case_no="2026타경000001", status="유찰 1회")])
    finally:
        lg.removeHandler(grab)
        lg.setLevel(prev)
        logging.disable(logging.CRITICAL)

    # 이 검사가 만든 트리거는 이 검사가 치운다 - 위 `scratch_db()` 격리와 두 겹으로 막는다.
    c = sqlite3.connect(path)
    try:
        c.execute("DROP TRIGGER IF EXISTS qa_break_derivation")
        c.commit()
    finally:
        c.close()

    errs = [r.getMessage() for r in grab.records if r.levelno >= logging.ERROR]
    check_true("검사가 공허하지 않다(트리거가 실제로 유도를 깨뜨렸다)",
               min(res["inserted"], res["updated"], res["unchanged"]) < 0,
               "-> %s (깨지지 않았다면 이 검사를 고쳐라)" % res)
    check_true("★ 유도가 깨지면 ERROR 로그가 나간다", len(errs) >= 1,
               "-> 결과=%s / 로그=%s" % (res, errs))
    if errs:
        check_true("로그가 원인을 짚어 준다(트리거/외래키)",
                   "트리거" in errs[0] or "외래키" in errs[0], errs[0][:160])


def test_created_at_and_doc_flags_survive_update():
    """갱신이 `created_at` 과 `has_*` 를 덮지 않는다 (SET 목록에 없어야 한다).

    한 문장 upsert 로 옮기면서 SET 목록을 새로 조립했다. 거기에 이 컬럼들이 끼면
    **문서 수집 결과가 매일 크롤에 지워진다** - 조용하고 되돌리기 어려운 손실이다.
    """
    print("\n--- 6-C. 갱신이 created_at / has_* 를 보존한다 ---")
    path = scratch_db()
    dbmod.upsert_batch([row(case_no="2026타경000001")])
    c = sqlite3.connect(path)
    try:
        c.execute("UPDATE auction SET created_at='2020-01-01T00:00:00',"
                  " has_spec_pdf=1, has_status_doc=1, has_appraisal_pdf=1")
        c.commit()
    finally:
        c.close()

    res = dbmod.upsert_batch([row(case_no="2026타경000001", status="유찰 1회")])
    check("실제로 갱신됐다(검사가 공허하지 않다)", res["updated"], 1)
    check("created_at 이 보존된다", one(path, "SELECT created_at FROM auction"),
          "2020-01-01T00:00:00")
    check("has_spec_pdf 가 보존된다", one(path, "SELECT has_spec_pdf FROM auction"), 1)
    check("has_status_doc 가 보존된다", one(path, "SELECT has_status_doc FROM auction"), 1)
    check("has_appraisal_pdf 가 보존된다",
          one(path, "SELECT has_appraisal_pdf FROM auction"), 1)
    check_true("updated_at 은 갱신된다",
               one(path, "SELECT updated_at FROM auction") != "2020-01-01T00:00:00")


def test_duplicate_key_inside_one_batch():
    """같은 배치에 같은 키가 두 번 와도 행이 두 벌 생기지 않고 계수도 맞는다."""
    print("\n--- 6-D. 한 배치 안의 중복 키 ---")
    path = scratch_db()
    r = row(case_no="2026타경000001")
    res = dbmod.upsert_batch([r, dict(r)])
    check("행은 하나만 생긴다", one(path, "SELECT COUNT(*) FROM auction"), 1)
    check("신규 1", res["inserted"], 1)
    check("둘째는 무변화", res["unchanged"], 1)
    check_true("합계가 입력 수와 같다", sum(res.values()) == 2, res)

    # 같은 배치 안에서 **값이 다른** 중복 - 뒤엣것이 이기고 갱신으로 센다.
    res2 = dbmod.upsert_batch([row(case_no="2026타경000002"),
                               row(case_no="2026타경000002", status="유찰 1회")])
    check("값이 다른 중복: 신규 1 + 갱신 1", (res2["inserted"], res2["updated"]), (1, 1))
    check("마지막 값이 남는다",
          one(path, "SELECT status FROM auction WHERE case_no='2026타경000002'"), "유찰 1회")
    check("행은 여전히 하나", one(
        path, "SELECT COUNT(*) FROM auction WHERE case_no='2026타경000002'"), 1)


def test_statement_count_is_one_per_row():
    """★ 행마다 **한 문장**인가 (#256 의 본론).

    숫자를 고정하는 것이 목적이 아니라, 예전의 `SELECT + INSERT/UPDATE` 두 문장이
    다시 돌아오는 것을 막는 것이 목적이다.
    """
    print("\n--- 6-E. 행마다 한 문장 ---")
    scratch_db()
    seen = []
    real_connect = sqlite3.connect

    def traced(*a, **kw):
        c = real_connect(*a, **kw)
        c.set_trace_callback(
            lambda s: seen.append((s.strip().split(None, 1) or ["?"])[0].upper()))
        return c

    sqlite3.connect = traced
    try:
        n = 50
        dbmod.upsert_batch([row(case_no="2026타경%06d" % i) for i in range(n)])
    finally:
        sqlite3.connect = real_connect

    body = [s for s in seen if s in ("SELECT", "INSERT", "UPDATE")]
    check_true("검사가 공허하지 않다(문장을 실제로 관찰했다)", len(body) > 0, seen[:5])
    check("행마다 INSERT(upsert) 한 문장", body.count("INSERT"), n)
    check("행마다 SELECT 를 보내지 않는다(배치당 2번뿐)", body.count("SELECT"), 2)
    check("별도 UPDATE 문장은 없다", body.count("UPDATE"), 0)
    check_true("총 문장 수가 행 수 + 상수다(2N 이 아니다)",
               len(body) <= n + 4, "-> %d문장 / %d행" % (len(body), n))


if __name__ == "__main__":
    try:
        test_unchanged_is_not_written()
        test_every_field_change_is_written()
        test_null_columns_are_detected()
        test_mixed_batch_counts()
        test_all_unchanged_day_is_success()
        test_no_triggers_or_referencing_fks_on_auction()
        test_broken_derivation_is_loud_not_silent()
        test_created_at_and_doc_flags_survive_update()
        test_duplicate_key_inside_one_batch()
        test_statement_count_is_one_per_row()
    finally:
        for d in _TMP:
            shutil.rmtree(d, ignore_errors=True)
    print("")
    if failures:
        print("FAILED %d: %s" % (len(failures), ", ".join(failures)))
        sys.exit(1)
    print("ALL PASS")
    sys.exit(0)
