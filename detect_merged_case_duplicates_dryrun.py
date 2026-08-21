"""법원이 사건을 **병합**하면서 같은 물건이 두 행으로 남은 경우를 찾는다.

2026-08-21 Sprint 249 신설. 읽기 전용이고 `--apply` 가 없다
(`detect_stale_region_contamination_dryrun.py` / `cleanup_orphans_dryrun.py` 와 같은 관례).

## 무엇을 찾나

법원은 관련 사건을 묶으면서 사건번호 표기를 바꾼다:

    2023타경4767            <- 원래
    2023타경4767 / 2026타경51196   <- 병합 후 (같은 물건, 같은 법원, 같은 물건번호)

이 저장소의 식별키는 `auction_case(case_no, court_code)` + `auction_item(case_id, item_no)`
다. 즉 **사건번호 문자열이 바뀌면 새 사건·새 물건 행이 생긴다.** 옛 행은 남고,
법원이 더는 그 번호로 공고하지 않으므로 **영원히 갱신되지 않는다.**

실측(2026-08-21):

    case_no 에 ' / ' 가 있는 행                  425
    그 조각이 단독 행으로도 존재하는 (사건,물건) 쌍   12
      그중 **주소까지 같은** 진짜 중복              1   <- id=442 / id=1421
      주소가 다른 것(물건번호만 우연히 겹침)         11  <- 정상. 병합 시 물건번호가 재부여된다

즉 "조각이 겹친다"만으로 중복이라고 하면 **11건을 오탐한다.** 그래서 이 스크립트는
**주소까지 같은 경우만** 중복으로 센다.

## 왜 문제인가 (실측)

    검색 결과에 같은 물건이 두 번 나온다 (안성시 검색 total=10 에 두 행 모두 포함)
    CSV/클립보드 내보내기에도 두 줄로 나간다
    document_queue 에 같은 물건의 문서가 두 벌 쌓인다 (실측 6행 = 3 + 3)

## 왜 자동으로 안 지우나

어느 행을 남길지는 제품 판단이다. 옛 행에 사용자의 관심물건/최근본이 걸려 있을 수
있고, 병합 행이 항상 최신이라는 보장도 코드로는 세울 수 없다. 그래서 **탐지만 한다.**

    python detect_merged_case_duplicates_dryrun.py
"""
import os
import sqlite3
import sys

# DB 경로는 cwd 가 아니라 이 파일 기준이다 (Sprint 246 계열).
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "auction.db")


def scan(conn):
    """(주소, 법원, 물건번호) 가 같은데 사건번호만 다른 행 묶음을 돌려준다."""
    groups = {}
    for row in conn.execute(
            "SELECT id, case_no, item_no, court_name, full_address, auction_date,"
            " minimum_bid_price, crawl_date FROM auction_item"
            " WHERE full_address IS NOT NULL AND TRIM(full_address) <> ''"):
        key = (row["full_address"], row["court_name"], row["item_no"])
        groups.setdefault(key, []).append(row)
    return {k: v for k, v in groups.items() if len(v) > 1}


def main() -> int:
    if not os.path.exists(DB_PATH):
        print("auction.db 가 없다: %s" % DB_PATH)
        return 1
    conn = sqlite3.connect("file:%s?mode=ro" % DB_PATH.replace("\\", "/"), uri=True)
    conn.row_factory = sqlite3.Row
    try:
        merged = conn.execute(
            "SELECT COUNT(*) AS n FROM auction_item WHERE case_no LIKE '% / %'"
        ).fetchone()["n"]
        total = conn.execute("SELECT COUNT(*) AS n FROM auction_item").fetchone()["n"]
        print("auction_item 전체            : %d행" % total)
        print("병합 표기(' / ') 사건번호 행   : %d행" % merged)
        print()

        dups = scan(conn)
        print("== 같은 (주소, 법원, 물건번호) 인데 사건번호가 다른 묶음: %d건" % len(dups))
        for (addr, court, item_no), rows in dups.items():
            print()
            print("   %s | %s | 물건 %s" % (addr[:70], court, item_no))
            for r in rows:
                print("      id=%-7s case_no=%-34s 기일=%s 최저가=%s 수집일=%s"
                      % (r["id"], r["case_no"], r["auction_date"],
                         r["minimum_bid_price"], r["crawl_date"]))
            # 같은 물건인지 값으로 한 번 더 확인한다
            dates = {r["auction_date"] for r in rows}
            prices = {r["minimum_bid_price"] for r in rows}
            if len(dates) == 1 and len(prices) == 1:
                print("      -> 기일/최저가까지 동일. **같은 물건이 두 행**일 가능성이 높다.")
            else:
                print("      -> 기일 또는 최저가가 다르다. 주소만 같은 별개 물건일 수 있다.")

        print()
        print("[DRY-RUN] 총 %d건. 아무것도 쓰지 않았다." % len(dups))
        print("--apply 없음 - 어느 행을 남길지는 제품 판단(PM 승인) 영역이다.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
