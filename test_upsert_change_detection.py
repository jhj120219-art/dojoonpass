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


def scratch_db():
    d = tempfile.mkdtemp(prefix="upsert_cd_")
    _TMP.append(d)
    path = os.path.join(d, "scratch.db")
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


if __name__ == "__main__":
    try:
        test_unchanged_is_not_written()
        test_every_field_change_is_written()
        test_null_columns_are_detected()
        test_mixed_batch_counts()
        test_all_unchanged_day_is_success()
    finally:
        for d in _TMP:
            shutil.rmtree(d, ignore_errors=True)
    print("")
    if failures:
        print("FAILED %d: %s" % (len(failures), ", ".join(failures)))
        sys.exit(1)
    print("ALL PASS")
    sys.exit(0)
