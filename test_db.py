import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import logging
from config.courts import get_courts_by_region
from crawler.court_crawler import crawl_court
from validator.validation_engine import ValidationEngine
from normalizer.normalizer import normalize_batch
from storage.database import init_db, upsert_batch, get_stats, query

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def main():
    logger.info("DB 초기화...")
    init_db()

    logger.info("서울 법원 수집 시작...")
    seoul_courts = get_courts_by_region("서울")
    all_items = []
    for court in seoul_courts:
        items = crawl_court(court)
        if items:
            all_items.extend(items)
            logger.info("[%s] %d건", court.name, len(items))

    logger.info("총 수집: %d건", len(all_items))

    engine = ValidationEngine(log_path="logs/validation.jsonl")
    all_items = engine.validate_batch(all_items)
    summary = engine.summary(all_items)
    logger.info("검증: PASS %d / FAIL %d", summary["pass"], summary["fail"])

    rows = normalize_batch(all_items)
    result = upsert_batch(rows)
    logger.info("DB UPSERT: 신규 %d / 업데이트 %d / 실패 %d",
        result["inserted"], result["updated"], result["failed"])

    stats = get_stats()
    print("")
    print("[DB 현황]")
    print("  총 누적:", stats["total"], "건")
    print("  시도별:")
    for s in stats["by_sido"]:
        print("    " + (s["sido"] or "미상") + ": " + str(s["cnt"]) + "건")

    print("")
    print("[서울 쿼리 테스트 - 상위 3건]")
    results = query(sido="서울", limit=3)
    for r in results:
        print("  " + r["case_no"] + " | " + r["full_address"][:30] + " | " + str(r["appraisal_price"]))

if __name__ == "__main__":
    main()
