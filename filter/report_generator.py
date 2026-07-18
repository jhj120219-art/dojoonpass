import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
from datetime import datetime
from typing import List, Dict
from storage.database import get_connection
from filter.scoring_engine import get_top20

logger = logging.getLogger(__name__)

def load_all_from_db() -> List[Dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM auction WHERE validation_status = 'PASS'"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def generate_report(output_dir: str = ".") -> str:
    today = datetime.today().strftime("%Y%m%d")
    filename = os.path.join(output_dir, "top20_report_" + today + ".txt")

    rows = load_all_from_db()
    if not rows:
        logger.warning("DB에 데이터 없음")
        return ""

    top20 = get_top20(rows)

    lines = []
    lines.append("=" * 60)
    lines.append("법원경매 투자후보 TOP 20 리포트")
    lines.append("생성일시: " + datetime.now().strftime("%Y-%m-%d %H:%M"))
    lines.append("전체 분석 건수: " + str(len(rows)) + "건")
    lines.append("=" * 60)
    lines.append("")

    for idx, item in enumerate(top20, 1):
        lines.append("[" + str(idx) + "위] 총점: " + str(item["total_score"]) + "점")
        lines.append("  사건번호: " + item["case_no"])
        lines.append("  법원    : " + item["court_name"])
        lines.append("  주소    : " + (item["full_address"] or "")[:50])
        lines.append("  용도    : " + (item["property_type"] or ""))
        lines.append("  감정가  : {:,}원".format(item["appraisal_price"]))
        lines.append("  최저가  : {:,}원 ({}%)".format(
            item["minimum_bid_price"],
            round(item["bid_rate"] * 100, 1)
        ))
        lines.append("  유찰    : " + str(item["fail_count"]) + "회")
        lines.append("  매각기일: " + (item["auction_date"] or ""))
        lines.append("  점수상세: 유찰 {}점 | 최저가율 {}점 | 지역 {}점 | 물건종류 {}점".format(
            item["score_fail"],
            item["score_bid"],
            item["score_sido"],
            item["score_type"],
        ))
        lines.append("")

    lines.append("=" * 60)
    lines.append("본 리포트는 자동 생성된 참고 자료입니다.")
    lines.append("실제 투자 전 반드시 현장 확인 및 전문가 상담을 받으세요.")
    lines.append("=" * 60)

    content = "\n".join(lines)

    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info("리포트 생성 완료: %s", filename)
    print(content)
    return filename

if __name__ == "__main__":
    generate_report()
