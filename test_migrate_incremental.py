"""`migrate_execute.execute()` 의 **증분 적용** 회귀 테스트.

운영 DB 는 건드리지 않는다 — `storage.database.snapshot_live_db()` 로 스키마만 뜬 뒤
데이터를 비운 스크래치 사본에서만 돈다.

배경 (2026-08-27, 크롤->DB 경로 감사)
---------------------------------------------------------------------------
이 스크립트는 매일 `SELECT * FROM auction` 으로 **누적 전체**를 읽어 전부 다시 쓴다.
하루에 새로 들어오는 것은 1,900건 안팎인데 비용은 누적 행수를 따라간다. 실측:

    누적       migrate(수정 전)   문장 수
     5,000          484ms          33,493
    10,000        3,510ms          63,493
    25,000        9,882ms         153,495
    50,000       17,250ms         303,499

cProfile 로 보면 `sqlite3.Connection.execute` 가 전체의 52%(254,892회)였다 —
병목은 쿼리 하나의 무게가 아니라 **문장 개수 그 자체**였다. 그래서 세 자리에서
"안 바뀐 것에는 문장을 보내지 않는다"로 바꿨다:

    1. auction_item UPDATE      쓰려는 값이 기존과 전부 같으면 건너뛴다
    2. auction_case INSERT      먼저 있는 것을 읽고 없는 것만 executemany
    3. document_status INSERT   먼저 있는 (item_id, doc_type) 집합을 읽고 없는 것만

결과(같은 데이터, 같은 조건):

    누적       전 -> 후            문장 수 전 -> 후
     5,000     484ms ->   207ms    33,493 ->  9,893   (2.3배)
    50,000  17,250ms -> 3,178ms   303,499 -> 54,896   (5.4배)

이 테스트가 지키는 것
---------------------------------------------------------------------------
속도가 아니라 **정확성**이다. "안 보낸다"는 최적화의 위험은 하나뿐이다 —
보내야 할 때 안 보내는 것. 그래서 auction_item 이 쓰는 필드를 **하나씩 따로**
바꿔 가며(변이 테스트) 전부 반영되는지 본다. 필드를 UPDATE 목록에는 넣고
비교 목록에서 빠뜨리면 이 검사가 바로 잡는다.

    python test_migrate_incremental.py
"""
import sys
import os
import sqlite3
import shutil
import tempfile
import logging
import importlib
import contextlib
import io

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
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name, ("" if ok else " -> " + str(detail))))
    if not ok:
        failures.append(name)


# ---------------------------------------------------------------------------
# 스크래치 환경
# ---------------------------------------------------------------------------
_TMP = []


# 운영 DB 경로를 **한 번만** 붙잡아 둔다 (2026-08-27, BUGS #257).
#
# ★ `scratch_db()` 는 마지막에 `dbmod.DB_PATH` 를 스크래치로 갈아끼운다. 그래서
#   그때그때의 `dbmod.DB_PATH` 에서 스냅샷을 뜨면, 두 번째 호출부터는 실 DB 가 아니라
#   **직전 스크래치의 사본**을 뜬다. 행은 지우므로 데이터는 안 넘어오지만 **스키마
#   객체(트리거/인덱스/뷰)는 넘어간다** — 검사끼리 조용히 오염된다.
#   `test_upsert_change_detection.py` 에서 실제로 트리거가 새어 나가 집계를 흔들었다.
_LIVE_DB_PATH = dbmod.DB_PATH


def scratch_db():
    """운영 DB 의 **스키마 그대로**인 빈 DB. 마이그레이션도 끝까지 적용한다."""
    d = tempfile.mkdtemp(prefix="mig_incr_")
    _TMP.append(d)
    path = os.path.join(d, "scratch.db")
    dbmod.DB_PATH = _LIVE_DB_PATH   # 항상 **실 DB** 에서 뜬다
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
    import storage.migrations.run_migrations as runner
    importlib.reload(runner)
    with contextlib.redirect_stdout(io.StringIO()):
        runner.run()
    dbmod.DB_PATH = path
    return path


def fresh_migrate():
    import migrate_execute
    importlib.reload(migrate_execute)
    migrate_execute.get_connection = dbmod.get_connection
    return migrate_execute


def row(i, **over):
    r = {
        "court_code": "B10000%d" % (i % 3),
        "court_name": "테스트법원%d" % (i % 3),
        "case_no": "2026타경%06d" % i,
        "item_no": "1",
        "property_type": "아파트",
        "sido": "서울특별시",
        "sigungu": "강남구",
        "dong": "역삼동",
        "lot_number": "%d-1" % i,
        # ★ 주소는 **운영 실데이터의 모양**을 그대로 쓴다. `extract_areas()` 는
        #   대괄호 안의 `[집합건물 ... 17.08㎡]` 꼴에서만 면적을 읽는다 —
        #   괄호 없는 합성 주소를 쓰면 면적이 항상 None 이라 이 검사가 **공허해진다**
        #   (2026-08-27 실제로 그렇게 썼다가 실측으로 잡았다).
        "full_address": "서울특별시 강남구 역삼동 %d-1 제2층202호 [집합건물 철근콘크리트조 84.5㎡]" % i,
        "appraisal_price": 100000000 + i,
        "minimum_bid_price": 70000000 + i,
        "auction_date": "2027-03-15",
        "status": "신건",
        "validation_status": "PASS",
        "validation_reasons": "",
        "crawl_date": "2026-08-27",
        "has_spec_pdf": 0,
        "has_status_pdf": 0,
        "has_appraisal_pdf": 0,
    }
    r.update(over)
    return r


def count_statements(fn):
    """실행 중 실제로 나간 SQL 문장 수."""
    box = {"n": 0}
    orig = dbmod.get_connection

    def patched(*a, **kw):
        conn = orig(*a, **kw)
        conn.set_trace_callback(lambda s: box.__setitem__("n", box["n"] + 1))
        return conn

    dbmod.get_connection = patched
    try:
        me = fresh_migrate()
        with contextlib.redirect_stdout(io.StringIO()):
            me.execute()
    finally:
        dbmod.get_connection = orig
    return box["n"]


def item_fields(path):
    """auction_item 전체를 (case_no, item_no) -> 값 튜플로. updated_at 은 뺀다."""
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    try:
        out = {}
        for r in c.execute("SELECT * FROM auction_item"):
            d = dict(r)
            d.pop("updated_at", None)
            d.pop("id", None)
            out[(d["case_no"], d["item_no"])] = d
        return out
    finally:
        c.close()


def one(path, sql, args=()):
    c = sqlite3.connect(path)
    try:
        r = c.execute(sql, args).fetchone()
        return r[0] if r else None
    finally:
        c.close()


# ---------------------------------------------------------------------------
# 1. 아무것도 바뀌지 않은 재실행 — 데이터가 그대로이고 문장이 급감한다
# ---------------------------------------------------------------------------
def test_noop_rerun_is_cheap_and_identical():
    print("\n--- 1. 변화 없는 재실행 ---")
    path = scratch_db()
    rows = [row(i) for i in range(300)]
    dbmod.upsert_batch(rows)

    me = fresh_migrate()
    with contextlib.redirect_stdout(io.StringIO()):
        first = me.execute()
    check_true("최초 마이그레이션이 성공한다", first, first)

    before = item_fields(path)
    ds_before = one(path, "SELECT COUNT(*) FROM document_status")
    n = count_statements(None)
    after = item_fields(path)

    check_true("데이터가 한 글자도 바뀌지 않는다", before == after,
               [k for k in before if before[k] != after.get(k)][:3])
    check("document_status 건수 그대로", one(path, "SELECT COUNT(*) FROM document_status"), ds_before)
    check("auction_item 건수 그대로", one(path, "SELECT COUNT(*) FROM auction_item"), 300)

    # 300행이면 예전에는 최소 300(SELECT) + 300(UPDATE) + 300(case) + 900(ds) = 1,800문장이었다.
    # 이제는 행 단위 SELECT 300개 + 상수 몇 개만 남아야 한다.
    check_true("문장 수가 900개 미만으로 떨어진다 (실제 %d)" % n, n < 900, n)


# ---------------------------------------------------------------------------
# 2. 변이 테스트 — auction_item 이 쓰는 필드를 **하나씩** 바꿔 전부 반영되는지
#
#    이 최적화의 유일한 위험은 "보내야 할 때 안 보내는 것"이다. UPDATE 목록에는
#    있는데 비교 목록에서 빠진 필드가 생기면 그 필드는 영원히 갱신되지 않는다.
#    파생 필드(fail_count/bid_rate/building_area/land_area)도 함께 확인한다.
# ---------------------------------------------------------------------------
MUTATIONS = [
    # (auction 쪽 필드, 새 값, auction_item 에서 확인할 (컬럼, 기대값))
    ("court_name",        "바뀐법원",      [("court_name", "바뀐법원")]),
    ("property_type",     "다세대",        [("property_type", "다세대")]),
    ("sido",              "경기도",        [("sido", "경기도")]),
    ("sigungu",           "성남시",        [("sigungu", "성남시")]),
    ("dong",              "정자동",        [("dong", "정자동")]),
    ("lot_number",        "999-9",         [("lot_number", "999-9")]),
    ("auction_date",      "2027-09-09",    [("auction_date", "2027-09-09")]),
    ("validation_status", "FAIL",          [("validation_status", "FAIL")]),
    ("crawl_date",        "2026-09-01",    [("crawl_date", "2026-09-01")]),
    # 파생: status -> fail_count 도 함께 바뀐다.
    # ★ 값은 **운영 실데이터의 모양**이다 — `SELECT status, COUNT(*) FROM auction` 상위가
    #   '유찰 2회'(324건) / '유찰 3회'(292건) 꼴이다. 괄호를 넣은 '유찰(3회)' 로 쓰면
    #   `extract_fail_count()` 의 정규식(`유찰\s*(\d+)회`)에 안 걸려 항상 1이 나오고,
    #   그러면 이 검사는 제품이 아니라 **가짜 입력**을 재고 있게 된다.
    ("status",            "유찰 3회",      [("status", "유찰 3회"), ("fail_count", 3)]),
    # 파생: 가격 -> bid_rate 도 함께 바뀐다
    ("appraisal_price",   200000000,       [("appraisal_price", 200000000)]),
    ("minimum_bid_price", 50000000,        [("minimum_bid_price", 50000000)]),
    # 파생: 주소 -> building_area / land_area 도 함께 바뀐다 (대괄호 표기가 정본이다)
    ("full_address",      "서울특별시 강남구 역삼동 5-5 제3층303호 "
                          "[집합건물 철근콘크리트조 120.75㎡] [토지 대 55.5㎡]",
     [("building_area", 120.75), ("land_area", 55.5)]),
]


def test_every_written_field_still_updates():
    print("\n--- 2. 변이 테스트: 필드를 하나씩 바꾸면 전부 반영된다 ---")
    for field, newval, expectations in MUTATIONS:
        path = scratch_db()
        dbmod.upsert_batch([row(1)])
        me = fresh_migrate()
        with contextlib.redirect_stdout(io.StringIO()):
            me.execute()

        dbmod.upsert_batch([row(1, **{field: newval})])
        me = fresh_migrate()
        with contextlib.redirect_stdout(io.StringIO()):
            me.execute()

        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        try:
            got = dict(c.execute("SELECT * FROM auction_item").fetchone())
        finally:
            c.close()

        for col, want in expectations:
            check("%s 변경 -> auction_item.%s" % (field, col), got[col], want)


def test_fields_that_can_change_alone():
    """**혼자서만** 바뀔 수 있는 필드들.

    왜 따로 필요한가 (2026-08-27 변이 테스트로 발견):
    위 변이 목록은 필드를 하나씩 바꾸지만, 파생 필드가 **같이** 움직이는 경우가 있다.
    그러면 파생 쪽 비교가 먼저 불일치를 만들어 UPDATE 가 나가고, 정작 그 필드의
    비교가 망가져 있어도 검사가 통과한다. 실제로 두 결함이 그렇게 살아남았다:

        appraisal_price 를 자기 자신과 비교   -> 안 잡힘 (bid_rate 가 같이 바뀌어 가려짐)
        full_address    를 자기 자신과 비교   -> 안 잡힘 (면적이 같이 바뀌어 가려짐)

    그래서 그 필드가 **혼자** 바뀌는 입력을 따로 만든다.
    """
    print("\n--- 2-d. 혼자 바뀌는 필드 (파생값이 가려 주지 않는 입력) ---")

    # (1) 최저가가 0(파싱 실패)인 물건의 감정가만 바뀐다.
    #     bid_rate = round(0/감정가, 4) = 0.0 이라 감정가가 변해도 **파생값이 그대로**다.
    #     실데이터에 가격 0("가격미정")은 실제로 존재한다.
    path = scratch_db()
    dbmod.upsert_batch([row(1, appraisal_price=100000000, minimum_bid_price=0)])
    me = fresh_migrate()
    with contextlib.redirect_stdout(io.StringIO()):
        me.execute()
    check("최초 감정가", one(path, "SELECT appraisal_price FROM auction_item"), 100000000)
    check("최초 bid_rate(최저가 0)", one(path, "SELECT bid_rate FROM auction_item"), 0.0)

    dbmod.upsert_batch([row(1, appraisal_price=200000000, minimum_bid_price=0)])
    me = fresh_migrate()
    with contextlib.redirect_stdout(io.StringIO()):
        me.execute()
    check("감정가만 바뀌어도 반영된다",
          one(path, "SELECT appraisal_price FROM auction_item"), 200000000)

    # (2) 대괄호 안 면적은 그대로 두고 **주소 앞부분만** 정정한다.
    #     주소 정정은 운영에서 흔하고, 그때 면적은 움직이지 않는다.
    path = scratch_db()
    addr_old = "서울특별시 강남구 역삼동 1-1 제2층202호 [집합건물 철근콘크리트조 84.5㎡]"
    addr_new = "서울특별시 강남구 역삼동 1-2 제2층203호 [집합건물 철근콘크리트조 84.5㎡]"
    dbmod.upsert_batch([row(1, full_address=addr_old)])
    me = fresh_migrate()
    with contextlib.redirect_stdout(io.StringIO()):
        me.execute()
    check("최초 주소", one(path, "SELECT full_address FROM auction_item"), addr_old)

    dbmod.upsert_batch([row(1, full_address=addr_new)])
    me = fresh_migrate()
    with contextlib.redirect_stdout(io.StringIO()):
        me.execute()
    check("면적이 같아도 주소 정정이 반영된다",
          one(path, "SELECT full_address FROM auction_item"), addr_new)
    check("면적은 그대로", one(path, "SELECT building_area FROM auction_item"), 84.5)


def test_derived_columns_repaired():
    """파생 컬럼이 DB 에서 틀어져 있으면 **다시 계산해 고쳐야** 한다.

    `fail_count` / `bid_rate` / `building_area` / `land_area` 는 전부 원본 필드의
    순수 함수다. 그래서 "원본이 안 바뀌면 파생도 안 바뀐다"가 보통은 맞고,
    변이 테스트에서 `fail_count` 를 자기 자신과 비교하게 만들어도 안 잡혔다.

    그러나 **계산 규칙이 바뀌면** 원본이 그대로여도 파생값이 달라져야 한다.
    이 저장소에서 실제로 있었던 일이다:

      - `025_add_auction_item_area_columns.sql` 로 면적 컬럼을 갓 추가한 직후(전부 NULL)
      - `extract_areas()` 파싱이 좋아져 예전에 못 읽던 주소를 읽게 됐을 때
        (`backfill_area.py` 가 존재하는 이유)
      - `extract_fail_count()` 의 정규식이 새 표기를 지원하게 됐을 때

    비교 목록에서 파생 컬럼이 빠져 있으면 그 값들은 **영원히 옛 값으로 남는다.**
    """
    print("\n--- 2-e. 틀어진 파생 컬럼은 다시 계산되어 고쳐진다 ---")
    path = scratch_db()
    dbmod.upsert_batch([row(1, status="유찰 4회")])
    me = fresh_migrate()
    with contextlib.redirect_stdout(io.StringIO()):
        me.execute()
    check("최초 fail_count", one(path, "SELECT fail_count FROM auction_item"), 4)

    # ★ 파생 컬럼을 **한 번에 하나씩** 틀어 놓는다.
    #   셋을 동시에 틀면 서로가 서로를 가려 준다 — 예를 들어 bid_rate 도 함께 틀어 두면
    #   bid_rate 비교가 불일치를 만들어 UPDATE 가 나가고, 그 김에 fail_count 도 올바르게
    #   써진다. 그러면 "fail_count 를 자기 자신과 비교한다"는 결함이 통과한다
    #   (2026-08-27 실제로 그렇게 썼다가 변이 테스트로 잡았다).
    def corrupt_and_check(sql, label, verify_sql, expected):
        c = sqlite3.connect(path)
        c.execute(sql)
        c.commit()
        c.close()
        me2 = fresh_migrate()
        with contextlib.redirect_stdout(io.StringIO()):
            me2.execute()
        check(label, one(path, verify_sql), expected)

    corrupt_and_check("UPDATE auction_item SET fail_count=0",
                      "fail_count 만 틀어도 다시 계산된다",
                      "SELECT fail_count FROM auction_item", 4)
    corrupt_and_check("UPDATE auction_item SET bid_rate=0.0",
                      "bid_rate 만 틀어도 다시 계산된다",
                      "SELECT bid_rate FROM auction_item", 0.7)
    corrupt_and_check("UPDATE auction_item SET building_area=NULL",
                      "building_area 만 비워도 다시 채워진다",
                      "SELECT building_area FROM auction_item", 84.5)


def test_area_backfilled_without_address_change():
    """주소는 그대로인데 **면적만** 채워져야 하는 경우.

    왜 따로 필요한가 (2026-08-27 변이 테스트로 발견):
    면적은 `full_address` 의 순수 함수라, 위 변이 목록에서 주소를 바꾸면 면적도 같이
    바뀐다. 그래서 "면적을 자기 자신과 비교한다"는 결함을 심어도 **위 검사들이 전부
    통과했다** — 주소가 함께 바뀌어 어차피 UPDATE 가 나갔기 때문이다.

    그러나 면적만 바뀌는 상황은 실재한다:

      - `025_add_auction_item_area_columns.sql` 로 컬럼을 갓 추가한 직후(전부 NULL)
      - `extract_areas()` 의 파싱 규칙이 좋아져 예전에 못 읽던 주소를 읽게 됐을 때
        (`backfill_area.py` 가 있는 이유가 바로 이것이다)

    두 경우 모두 주소 원문은 한 글자도 안 바뀐다. 비교에서 면적을 빠뜨리면 그 값들은
    **영원히 NULL 로 남는다.** 그러면 면적 범위 검색이 조용히 그 물건들을 빼고 답한다.
    """
    print("\n--- 2-c. 주소 불변, 면적만 채워지는 경우 ---")
    path = scratch_db()
    dbmod.upsert_batch([row(1)])
    me = fresh_migrate()
    with contextlib.redirect_stdout(io.StringIO()):
        me.execute()
    check("최초 building_area", one(path, "SELECT building_area FROM auction_item"), 84.5)

    # 025 직후 / 파서 개선 전 상태를 재현한다 — 주소는 그대로 두고 면적만 비운다
    c = sqlite3.connect(path)
    c.execute("UPDATE auction_item SET building_area=NULL, land_area=NULL")
    c.commit()
    c.close()
    check("비운 상태 확인", one(path, "SELECT building_area FROM auction_item"), None)

    me = fresh_migrate()
    with contextlib.redirect_stdout(io.StringIO()):
        me.execute()
    check("주소가 안 바뀌어도 면적이 다시 채워진다",
          one(path, "SELECT building_area FROM auction_item"), 84.5)


def test_bid_rate_recomputed():
    print("\n--- 2-b. 파생 필드 bid_rate 재계산 ---")
    path = scratch_db()
    dbmod.upsert_batch([row(1, appraisal_price=100000000, minimum_bid_price=70000000)])
    me = fresh_migrate()
    with contextlib.redirect_stdout(io.StringIO()):
        me.execute()
    check("최초 bid_rate", one(path, "SELECT bid_rate FROM auction_item"), 0.7)

    dbmod.upsert_batch([row(1, appraisal_price=100000000, minimum_bid_price=49000000)])
    me = fresh_migrate()
    with contextlib.redirect_stdout(io.StringIO()):
        me.execute()
    check("가격 변경 후 bid_rate", one(path, "SELECT bid_rate FROM auction_item"), 0.49)


# ---------------------------------------------------------------------------
# 3. 신규 행은 그대로 들어온다 (auction_case / auction_item / document_status)
# ---------------------------------------------------------------------------
def test_new_rows_still_inserted():
    print("\n--- 3. 신규 사건/물건/문서상태 삽입 ---")
    path = scratch_db()
    dbmod.upsert_batch([row(i) for i in range(10)])
    me = fresh_migrate()
    with contextlib.redirect_stdout(io.StringIO()):
        me.execute()
    check("auction_item 10건", one(path, "SELECT COUNT(*) FROM auction_item"), 10)
    check("document_status 30건", one(path, "SELECT COUNT(*) FROM document_status"), 30)
    # 법원 3곳 x 사건 10건이지만 사건번호가 전부 달라 사건도 10건
    check("auction_case 10건", one(path, "SELECT COUNT(*) FROM auction_case"), 10)

    # 하루 뒤: 5건 추가
    dbmod.upsert_batch([row(i) for i in range(10, 15)])
    me = fresh_migrate()
    with contextlib.redirect_stdout(io.StringIO()):
        me.execute()
    check("auction_item 15건", one(path, "SELECT COUNT(*) FROM auction_item"), 15)
    check("document_status 45건", one(path, "SELECT COUNT(*) FROM document_status"), 45)
    check("auction_case 15건", one(path, "SELECT COUNT(*) FROM auction_case"), 15)

    # 모든 물건이 case_id 를 제대로 물고 있어야 한다(선조회/후삽입 순서가 깨지면 여기서 잡힌다)
    check("case_id 가 NULL 인 물건 없음",
          one(path, "SELECT COUNT(*) FROM auction_item WHERE case_id IS NULL"), 0)
    check("고아 case_id 없음",
          one(path, "SELECT COUNT(*) FROM auction_item ai "
                    "LEFT JOIN auction_case ac ON ai.case_id=ac.id WHERE ac.id IS NULL"), 0)


# ---------------------------------------------------------------------------
# 4. document_status 는 **되살아나지 않는다**
#
#    `INSERT OR IGNORE` 의 원래 성질이다 — 이미 있는 행은 상태가 무엇이든 그대로 둔다.
#    선조회 방식으로 바꾸면서 이 성질이 바뀌면 doc_worker 가 수집해 READY 로 만든 것이
#    매일 밤 COLLECTING 으로 되돌아간다. 그래서 따로 고정한다.
# ---------------------------------------------------------------------------
def test_existing_document_status_preserved():
    print("\n--- 4. 이미 있는 document_status 는 덮이지 않는다 ---")
    path = scratch_db()
    dbmod.upsert_batch([row(1)])
    me = fresh_migrate()
    with contextlib.redirect_stdout(io.StringIO()):
        me.execute()

    c = sqlite3.connect(path)
    c.execute("UPDATE document_status SET status='READY' WHERE doc_type='SPEC'")
    # doc_worker 가 만드는 IMAGE 행도 섞어 둔다 — 이 스크립트가 모르는 종류다
    item_id = c.execute("SELECT id FROM auction_item").fetchone()[0]
    c.execute("INSERT INTO document_status (item_id, doc_type, status, updated_at) "
              "VALUES (?, 'IMAGE', 'READY', '2026-08-27')", (item_id,))
    c.commit()
    c.close()

    me = fresh_migrate()
    with contextlib.redirect_stdout(io.StringIO()):
        me.execute()

    check("SPEC 은 READY 로 남는다",
          one(path, "SELECT status FROM document_status WHERE doc_type='SPEC'"), "READY")
    check("IMAGE 행이 살아남는다",
          one(path, "SELECT COUNT(*) FROM document_status WHERE doc_type='IMAGE'"), 1)
    check("행이 늘지 않는다", one(path, "SELECT COUNT(*) FROM document_status"), 4)


# ---------------------------------------------------------------------------
# 5. 여러 번 돌려도 같은 결과 (멱등)
# ---------------------------------------------------------------------------
def test_idempotent_across_runs():
    print("\n--- 5. 3회 반복 실행 멱등성 ---")
    path = scratch_db()
    dbmod.upsert_batch([row(i) for i in range(50)])
    snaps = []
    for _ in range(3):
        me = fresh_migrate()
        with contextlib.redirect_stdout(io.StringIO()):
            me.execute()
        snaps.append(item_fields(path))
    check_true("1회차 == 2회차", snaps[0] == snaps[1], "다름")
    check_true("2회차 == 3회차", snaps[1] == snaps[2], "다름")
    check("중복 물건 없음",
          one(path, "SELECT COUNT(*) FROM (SELECT case_id,item_no FROM auction_item "
                    "GROUP BY 1,2 HAVING COUNT(*)>1)"), 0)
    check("중복 사건 없음",
          one(path, "SELECT COUNT(*) FROM (SELECT court_code,case_no FROM auction_case "
                    "GROUP BY 1,2 HAVING COUNT(*)>1)"), 0)
    check("중복 문서상태 없음",
          one(path, "SELECT COUNT(*) FROM (SELECT item_id,doc_type FROM document_status "
                    "GROUP BY 1,2 HAVING COUNT(*)>1)"), 0)


# ---------------------------------------------------------------------------
# 6. 실패는 통째로 롤백된다 (부분 커밋 없음)
#
#    `execute()` 는 마지막에 한 번 commit 한다. 중간에 죽으면 그날 치가 전부
#    버려져야 하고, **절반만 반영된 상태**로 남으면 안 된다.
# ---------------------------------------------------------------------------
def test_failure_rolls_back_everything():
    print("\n--- 6. 중간 실패 시 부분 커밋이 없다 ---")
    path = scratch_db()
    dbmod.upsert_batch([row(i) for i in range(20)])
    me = fresh_migrate()
    with contextlib.redirect_stdout(io.StringIO()):
        me.execute()
    base = item_fields(path)
    base_ds = one(path, "SELECT COUNT(*) FROM document_status")

    # 새 물건 10건을 넣고, document_status 단계에서 죽게 만든다
    dbmod.upsert_batch([row(i) for i in range(20, 30)])
    me = fresh_migrate()
    boom = RuntimeError("주입된 실패")

    def explode(*a, **kw):
        raise boom
    me.MIGRATED_DOC_TYPE_COLUMNS = property(explode)   # §3 진입 시 폭발

    raised = None
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            me.execute()
    except Exception as e:      # noqa: BLE001
        raised = e
    check_true("실패가 예외로 올라온다", raised is not None, raised)
    check("auction_item 이 늘지 않았다(롤백)",
          one(path, "SELECT COUNT(*) FROM auction_item"), 20)
    check("document_status 도 그대로", one(path, "SELECT COUNT(*) FROM document_status"), base_ds)
    check_true("기존 데이터가 손상되지 않았다", item_fields(path) == base, "달라졌다")

    # 그리고 다시 정상 실행하면 밀린 10건이 들어온다(이어받기)
    me = fresh_migrate()
    with contextlib.redirect_stdout(io.StringIO()):
        me.execute()
    check("재실행으로 30건이 된다", one(path, "SELECT COUNT(*) FROM auction_item"), 30)
    check("document_status 90건", one(path, "SELECT COUNT(*) FROM document_status"), 90)


if __name__ == "__main__":
    try:
        test_noop_rerun_is_cheap_and_identical()
        test_every_written_field_still_updates()
        test_fields_that_can_change_alone()
        test_derived_columns_repaired()
        test_area_backfilled_without_address_change()
        test_bid_rate_recomputed()
        test_new_rows_still_inserted()
        test_existing_document_status_preserved()
        test_idempotent_across_runs()
        test_failure_rolls_back_everything()
    finally:
        for d in _TMP:
            shutil.rmtree(d, ignore_errors=True)
    print("")
    if failures:
        print("FAILED %d: %s" % (len(failures), ", ".join(failures)))
        sys.exit(1)
    print("ALL PASS")
    sys.exit(0)
