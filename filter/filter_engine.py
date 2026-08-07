import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import logging
from typing import List, Dict
from storage.database import get_connection

logger = logging.getLogger(__name__)

def filter_auctions(
    sido: str = None,
    sigungu: str = None,
    court_name: str = None,
    property_type: str = None,
    auction_date_from: str = None,
    auction_date_to: str = None,
    min_appraisal: int = None,
    max_appraisal: int = None,
    min_bid_rate: float = None,
    max_bid_rate: float = None,
    min_fail_count: int = None,
    max_fail_count: int = None,
    validation_status: str = "PASS",
    limit: int = 100,
) -> List[Dict]:
    """
    조건 기반 경매 물건 필터링
    - sido: 시도 (예: 서울, 경기)
    - sigungu: 시군구 (예: 강남구)
    - property_type: 물건종류 (예: 다세대, 아파트)
    - auction_date_from/to: 매각기일 범위 (예: 2026-07-01)
    - min/max_appraisal: 감정가 범위 (원)
    - min/max_bid_rate: 최저가율 범위 (0.0~1.0, 예: 0.5 = 50%)
    - min/max_fail_count: 유찰 횟수 범위
    """
    conn = get_connection()
    try:
        conditions = ["1=1"]
        params = []

        if validation_status:
            conditions.append("validation_status = ?")
            params.append(validation_status)
        if sido:
            conditions.append("sido = ?")
            params.append(sido)
        if sigungu:
            conditions.append("sigungu LIKE ?")
            params.append("%" + sigungu + "%")
        if court_name:
            conditions.append("court_name = ?")
            params.append(court_name)
        if property_type:
            conditions.append("property_type LIKE ?")
            params.append("%" + property_type + "%")
        if auction_date_from:
            conditions.append("auction_date >= ?")
            params.append(auction_date_from)
        if auction_date_to:
            conditions.append("auction_date <= ?")
            params.append(auction_date_to)
        if min_appraisal is not None:
            conditions.append("appraisal_price >= ?")
            params.append(min_appraisal)
        if max_appraisal is not None:
            conditions.append("appraisal_price <= ?")
            params.append(max_appraisal)

        where = "WHERE " + " AND ".join(conditions)
        sql = "SELECT * FROM auction " + where + " ORDER BY auction_date DESC, appraisal_price DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        results = [dict(r) for r in rows]

        # 최저가율 필터 (DB에서 계산 어려워 Python에서 처리)
        if min_bid_rate is not None or max_bid_rate is not None:
            filtered = []
            for r in results:
                appraisal = r.get("appraisal_price", 0)
                minimum = r.get("minimum_bid_price", 0)
                if appraisal > 0:
                    rate = minimum / appraisal
                    if min_bid_rate is not None and rate < min_bid_rate:
                        continue
                    if max_bid_rate is not None and rate > max_bid_rate:
                        continue
                filtered.append(r)
            results = filtered

        # 유찰 횟수 필터
        if min_fail_count is not None or max_fail_count is not None:
            filtered = []
            for r in results:
                status = r.get("status", "")
                count = extract_fail_count(status)
                if min_fail_count is not None and count < min_fail_count:
                    continue
                if max_fail_count is not None and count > max_fail_count:
                    continue
                filtered.append(r)
            results = filtered

        return results

    finally:
        conn.close()

def extract_fail_count(status: str) -> int:
    import re
    if not status:
        return 0
    m = re.search(r"유찰\s*(\d+)회", status)
    if m:
        return int(m.group(1))
    if "유찰" in status:
        return 1
    return 0

def calculate_bid_rate(row: Dict) -> float:
    appraisal = row.get("appraisal_price", 0)
    minimum = row.get("minimum_bid_price", 0)
    if appraisal > 0:
        return round(minimum / appraisal, 4)
    return 0.0

def print_results(results: List[Dict], title: str = "필터 결과") -> None:
    print("")
    print("=" * 60)
    print("[" + title + "] 총 " + str(len(results)) + "건")
    print("=" * 60)
    for r in results:
        rate = calculate_bid_rate(r)
        fail = extract_fail_count(r.get("status", ""))
        print("[" + r["case_no"] + "]")
        print("  법원: " + r["court_name"])
        print("  주소: " + (r["full_address"] or "")[:50])
        print("  용도: " + (r["property_type"] or ""))
        print("  감정가: {:,}원".format(r["appraisal_price"]))
        print("  최저가: {:,}원 ({}%)".format(
            r["minimum_bid_price"],
            round(rate * 100, 1)
        ))
        print("  유찰: " + str(fail) + "회")
        print("  매각기일: " + (r["auction_date"] or ""))
        print("")
