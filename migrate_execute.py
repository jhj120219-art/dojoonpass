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
        # 식별키는 (court_code, case_no) 복합키다 — 법원마다 사건번호를 독립 채번하므로
        # case_no 단독으로 dedup하면 서로 다른 법원의 동일 사건번호가 한 row로 병합된다
        # (011_auction_case_court_code_unique.sql에서 해소한 Release Blocking 버그).
        logger.info("auction_case 마이그레이션 시작...")
        case_map = {}
        for row in rows:
            key = (row["court_code"], row["case_no"])
            if key not in case_map:
                case_map[key] = row

        for (court_code, case_no), row in case_map.items():
            conn.execute("""
                INSERT OR IGNORE INTO auction_case
                (case_no, court_code, court_name, case_type, filed_date, demand_deadline, created_at, updated_at)
                VALUES (?, ?, ?, NULL, NULL, NULL, ?, ?)
            """, (case_no, court_code, row["court_name"],
                  row["created_at"] or now, row["updated_at"] or now))

        logger.info("auction_case 완료: %d건", len(case_map))

        # 2. auction_item UPSERT
        # Sprint: auction -> auction_item 최신화 동기화.
        # 기존 INSERT OR IGNORE는 최초 삽입 이후 재크롤링 값(가격/기일/상태/유찰횟수)이
        # 영원히 반영되지 않는 문제가 있어, 기존 row는 UPDATE로 갱신한다.
        # 단, 크롤링 값이 빈 문자열/0(파싱 실패 등)이면 기존 정상값을 지우지 않고 유지한다.
        #
        # 2026-08-07: 위 "Critical TODO"(court_code+case_no+item_no 식별키)의 남은 절반을 해소한다.
        # auction_case는 2026-08-06 Migration으로 (court_code, case_no) 복합키가 됐지만,
        # auction_item 조회/갱신은 여전히 `WHERE case_no=? AND item_no=?`로 **법원 구분이 없었다**.
        # 법원마다 사건번호를 독립 채번하므로 서로 다른 법원이 같은 (case_no, item_no)를 쓰면
        # 매일 크롤링이 한쪽 법원 데이터로 다른 법원 row를 덮어쓴다(docs/BUGS.md #14와 같은 계열).
        # 실측 결과 현재 그런 쌍은 0건이지만(사건번호 충돌 3건이 마침 item_no가 달랐다),
        # 사건번호 충돌 자체는 이미 존재하므로 언제든 터질 수 있는 잠재 결함이다.
        # 바로 위에서 (court_code, case_no)로 구한 case_id는 이미 법원까지 특정된 값이므로,
        # 식별키를 (case_id, item_no)로 바꾸면 스키마 변경 없이 법원 구분이 생긴다.
        logger.info("auction_item 마이그레이션 시작...")
        item_count = 0
        item_inserted = 0
        item_updated = 0
        for row in rows:
            # 조회도 복합키 기준이어야 한다 — case_no만으로 찾으면 동일 사건번호를 쓰는
            # 다른 법원의 auction_case row를 잘못 연결하게 된다(위 UPSERT와 동일한 이유).
            case_id = conn.execute(
                "SELECT id FROM auction_case WHERE court_code = ? AND case_no = ?",
                (row["court_code"], row["case_no"])
            ).fetchone()["id"]

            existing = conn.execute(
                "SELECT * FROM auction_item WHERE case_id=? AND item_no=?",
                (case_id, row["item_no"])
            ).fetchone()

            if existing:
                court_name = row["court_name"] or existing["court_name"]
                property_type = row["property_type"] or existing["property_type"]
                sido = row["sido"] or existing["sido"]
                sigungu = row["sigungu"] or existing["sigungu"]
                dong = row["dong"] or existing["dong"]
                lot_number = row["lot_number"] or existing["lot_number"]
                full_address = row["full_address"] or existing["full_address"]
                appraisal_price = row["appraisal_price"] or existing["appraisal_price"]
                minimum_bid_price = row["minimum_bid_price"] or existing["minimum_bid_price"]
                auction_date = row["auction_date"] or existing["auction_date"]
                status = row["status"] or existing["status"]
                validation_status = row["validation_status"] or existing["validation_status"]
                crawl_date = row["crawl_date"] or existing["crawl_date"]
                fail_count = extract_fail_count(status)
                bid_rate = calc_bid_rate(appraisal_price, minimum_bid_price)

                conn.execute("""
                    UPDATE auction_item SET
                        court_name=?, property_type=?, sido=?, sigungu=?, dong=?,
                        lot_number=?, full_address=?, appraisal_price=?,
                        minimum_bid_price=?, auction_date=?, status=?,
                        fail_count=?, bid_rate=?, validation_status=?,
                        crawl_date=?, updated_at=?
                    WHERE case_id=? AND item_no=?
                """, (
                    court_name, property_type, sido, sigungu, dong,
                    lot_number, full_address, appraisal_price,
                    minimum_bid_price, auction_date, status,
                    fail_count, bid_rate, validation_status,
                    crawl_date, now,
                    case_id, row["item_no"],
                ))
                item_updated += 1
            else:
                conn.execute("""
                    INSERT INTO auction_item
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
                    now,
                ))
                item_inserted += 1
            item_count += 1

        logger.info("auction_item 완료: %d건 (신규 %d건, 갱신 %d건)",
                    item_count, item_inserted, item_updated)

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

        # 이모지(✅/❌)를 쓰지 않는다 — run_daily.bat이 stdout을 로그 파일로 리다이렉트하면
        # 이 환경의 파이썬이 cp949로 인코딩하는데 이모지가 cp949에 없어 UnicodeEncodeError로
        # 죽는다. 커밋은 이미 끝난 뒤라 데이터는 정상이지만 스크립트가 exit 1로 종료되어
        # 매일 배치가 실패로 보고됐다(logs/migrate_execute.log에 11회 발생 실측).
        if ai == orig:
            print("  [OK] auction_item 건수 일치")
        else:
            print(f"  [FAIL] auction_item 불일치: {ai} != {orig}")

        if ds == orig * 3:
            print("  [OK] document_status 건수 일치")
        else:
            print(f"  [FAIL] document_status 불일치: {ds} != {orig * 3}")

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
