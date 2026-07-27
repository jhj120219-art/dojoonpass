import sys, os, re
sys.path.insert(0, os.getcwd())
from storage.database import get_connection
from datetime import datetime
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)

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

def execute():
    conn = get_connection()
    now = datetime.now().isoformat()
    try:
        rows = conn.execute("SELECT * FROM auction").fetchall()
        logger.info("원본 데이터 로드: %d건", len(rows))

        # 1. auction_case UPSERT
        logger.info("auction_case 마이그레이션 시작...")
        case_map = {}
        for row in rows:
            case_no = row["case_no"]
            if case_no not in case_map:
                case_map[case_no] = row

        for case_no, row in case_map.items():
            conn.execute("""
                INSERT OR IGNORE INTO auction_case
                (case_no, court_name, case_type, filed_date, demand_deadline, created_at, updated_at)
                VALUES (?, ?, NULL, NULL, NULL, ?, ?)
            """, (case_no, row["court_name"], row["created_at"] or now, row["updated_at"] or now))

        logger.info("auction_case 완료: %d건", len(case_map))

        # 2. auction_item UPSERT
        logger.info("auction_item 마이그레이션 시작...")
        item_count = 0
        for row in rows:
            case_id = conn.execute(
                "SELECT id FROM auction_case WHERE case_no = ?",
                (row["case_no"],)
            ).fetchone()["id"]

            conn.execute("""
                INSERT OR IGNORE INTO auction_item
                (case_id, case_no, item_no, court_name, property_type,
                 sido, sigungu, dong, lot_number, full_address,
                 appraisal_price, minimum_bid_price, auction_date,
                 status, fail_count, bid_rate, validation_status,
                 crawl_date, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                case_id,
                row["case_no"], row["item_no"], row["court_name"],
                row["property_type"], row["sido"], row["sigungu"],
                row["dong"], row["lot_number"], row["full_address"],
                row["appraisal_price"], row["minimum_bid_price"],
                row["auction_date"], row["status"],
                extract_fail_count(row["status"]),
                calc_bid_rate(row["appraisal_price"], row["minimum_bid_price"]),
                row["validation_status"],
                row["crawl_date"],
                row["created_at"] or now,
                row["updated_at"] or now,
            ))
            item_count += 1

        logger.info("auction_item 완료: %d건", item_count)

        # 3. document_status 마이그레이션
        logger.info("document_status 마이그레이션 시작...")
        ds_count = 0
        for row in rows:
            item = conn.execute(
                "SELECT id FROM auction_item WHERE case_no = ? AND item_no = ?",
                (row["case_no"], row["item_no"])
            ).fetchone()
            if not item:
                continue
            item_id = item["id"]

            for doc_type, col in [
                ("SPEC", "has_spec_pdf"),
                ("STATUS", "has_status_doc"),
                ("APPRAISAL", "has_appraisal_pdf"),
            ]:
                status = "READY" if row[col] == 1 else "COLLECTING"
                conn.execute("""
                    INSERT OR IGNORE INTO document_status
                    (item_id, doc_type, status, updated_at)
                    VALUES (?, ?, ?, ?)
                """, (item_id, doc_type, status, now))
                ds_count += 1

        logger.info("document_status 완료: %d건", ds_count)

        conn.commit()
        logger.info("마이그레이션 커밋 완료")

        # 건수 검증
        print("")
        print("=== 마이그레이션 결과 검증 ===")
        ac = conn.execute("SELECT COUNT(*) FROM auction_case").fetchone()[0]
        ai = conn.execute("SELECT COUNT(*) FROM auction_item").fetchone()[0]
        ds = conn.execute("SELECT COUNT(*) FROM document_status").fetchone()[0]
        orig = conn.execute("SELECT COUNT(*) FROM auction").fetchone()[0]

        print(f"  auction 원본        : {orig}건")
        print(f"  auction_case        : {ac}건")
        print(f"  auction_item        : {ai}건")
        print(f"  document_status     : {ds}건")

        if ai == orig:
            print("  ✅ auction_item 건수 일치")
        else:
            print(f"  ❌ auction_item 불일치: {ai} != {orig}")

        if ds == orig * 3:
            print("  ✅ document_status 건수 일치")
        else:
            print(f"  ❌ document_status 불일치: {ds} != {orig * 3}")

        print("")
        print("=== 샘플 확인 ===")
        sample = conn.execute("""
            SELECT ai.case_no, ai.item_no, ai.fail_count, ai.bid_rate,
                   ac.court_name
            FROM auction_item ai
            JOIN auction_case ac ON ai.case_id = ac.id
            LIMIT 3
        """).fetchall()
        for s in sample:
            print(f"  {s['case_no']} | {s['item_no']} | fail={s['fail_count']} | rate={s['bid_rate']} | {s['court_name']}")

    except Exception as e:
        conn.rollback()
        logger.error("마이그레이션 실패: %s", str(e))
        raise
    finally:
        conn.close()
        
if __name__ == "__main__":
    try:
        execute()
        sys.exit(0)
    except Exception as e:
        print("FATAL:", str(e))
        sys.exit(1)
