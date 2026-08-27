import sys, os, re
sys.path.insert(0, os.getcwd())
from storage.database import get_connection
from datetime import datetime

def extract_fail_count(status: str) -> int:
    if not status:
        return 0
    m = re.search(r"유찰\s*(\d+)회", status)
    if m:
        return int(m.group(1))
    if "유찰" in status:
        return 1
    return 0

def calc_bid_rate(appraisal: int, minimum: int) -> float:
    if appraisal > 0:
        return round(minimum / appraisal, 4)
    return 0.0

def dryrun():
    # 읽고 **바로** 놓는다 (2026-08-27, 자원 누수 감사).
    # 예전에는 함수 마지막 줄에서 닫았다. 그 사이 100줄은 전부 순수 파이썬 집계라
    # 커넥션이 필요 없는데도 잡고 있었고, 중간에서 예외가 나면 아예 닫히지 않았다.
    # 미리보기 도구라 피해가 작지만, 이 저장소의 나머지 69개 함수는 전부 finally 로
    # 닫는다 — 규칙이 두 벌이 되지 않게 여기도 맞춘다.
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM auction").fetchall()
    finally:
        conn.close()

    # auction_case 중복 제거
    #
    # ★ 키는 (court_code, case_no) 다 — `migrate_execute.py:45` 와 같아야 한다 (2026-08-14).
    #
    #   예전에는 `case_no` 단독이었다. 법원마다 사건번호를 독립 채번하므로 서로 다른 법원의
    #   같은 사건번호가 **한 건으로 합쳐져** 예고 건수가 실제보다 적게 나왔다.
    #
    #       2026-08-14 실측
    #         dryrun 방식 (case_no 만)     1,381건
    #         execute 방식 (court+case_no) 1,384건   <- 실제 auction_case 행 수와 같다
    #
    #   미리보기 도구가 **실행 결과와 다른 숫자**를 말하면, 실행 뒤 그 차이를 보고
    #   "execute 가 뭔가 잘못했다"고 오판하게 된다. 이 저장소에는 법원이 다른 같은
    #   사건번호가 3개 있다(2024타경34089 / 2024타경3700 / 2024타경4973).
    case_map = {}
    for row in rows:
        case_no = row["case_no"]
        key = (row["court_code"], case_no)
        if key not in case_map:
            case_map[key] = {
                "case_no": case_no,
                "court_name": row["court_name"],
                "case_type": None,
                "filed_date": None,
                "demand_deadline": None,
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }

    # auction_item 전체
    items = []
    for row in rows:
        items.append({
            "case_no": row["case_no"],
            "item_no": row["item_no"],
            "court_name": row["court_name"],
            "property_type": row["property_type"],
            "sido": row["sido"],
            "sigungu": row["sigungu"],
            "dong": row["dong"],
            "lot_number": row["lot_number"],
            "full_address": row["full_address"],
            "appraisal_price": row["appraisal_price"],
            "minimum_bid_price": row["minimum_bid_price"],
            "auction_date": row["auction_date"],
            "status": row["status"],
            "fail_count": extract_fail_count(row["status"]),
            "bid_rate": calc_bid_rate(row["appraisal_price"], row["minimum_bid_price"]),
            "validation_status": row["validation_status"],
            "crawl_date": row["crawl_date"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        })

    # document_status
    doc_statuses = []
    for row in rows:
        for doc_type, col in [
            ("SPEC", "has_spec_pdf"),
            ("STATUS", "has_status_doc"),
            ("APPRAISAL", "has_appraisal_pdf"),
        ]:
            status = "READY" if row[col] == 1 else "COLLECTING"
            doc_statuses.append({
                "case_no": row["case_no"],
                "item_no": row["item_no"],
                "doc_type": doc_type,
                "status": status,
            })

    print("=== Dry Run 결과 ===")
    print(f"  auction 원본        : {len(rows)}건")
    print(f"  auction_case 예정   : {len(case_map)}건 (중복 제거)")
    print(f"  auction_item 예정   : {len(items)}건")
    print(f"  document_status 예정: {len(doc_statuses)}건")

    print("")
    print("=== 샘플 auction_case (3건) ===")
    for c in list(case_map.values())[:3]:
        print(f"  {c['case_no']} | {c['court_name']}")

    print("")
    print("=== 샘플 auction_item (3건) ===")
    for it in items[:3]:
        print(f"  {it['case_no']} | {it['item_no']} | fail={it['fail_count']} | rate={it['bid_rate']}")

    print("")
    print("=== 샘플 document_status (6건) ===")
    for ds in doc_statuses[:6]:
        print(f"  {ds['case_no']} | {ds['doc_type']} | {ds['status']}")

    print("")
    print("=== fail_count 분포 ===")
    from collections import Counter
    fc = Counter(it["fail_count"] for it in items)
    for k in sorted(fc.keys()):
        print(f"  {k}회: {fc[k]}건")

if __name__ == "__main__":
    dryrun()
