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
    conn = get_connection()
    rows = conn.execute("SELECT * FROM auction").fetchall()

    # auction_case 중복 제거
    case_map = {}
    for row in rows:
        case_no = row["case_no"]
        if case_no not in case_map:
            case_map[case_no] = {
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

    conn.close()

if __name__ == "__main__":
    dryrun()
