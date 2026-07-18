import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import logging
from models.auction_item import AuctionItem
from validator.validation_engine import ValidationEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def main():
    filename = "auction_20260703.csv"
    logger.info("CSV 로드: %s", filename)
    df = pd.read_csv(filename, encoding="utf-8-sig")
    logger.info("총 %d건 로드", len(df))

    items = []
    for _, row in df.iterrows():
        item = AuctionItem(
            case_no=str(row.get("case_no", "-")),
            item_no=str(row.get("item_no", "-")),
            address=str(row.get("full_address", "-")),
            property_type=str(row.get("property_type", "-")),
            appraisal_price=str(int(row.get("appraisal_price", 0))) if row.get("appraisal_price", 0) else "-",
            minimum_bid_price=str(int(row.get("minimum_bid_price", 0))) if row.get("minimum_bid_price", 0) else "-",
            auction_date=str(row.get("auction_date", "-")),
            status=str(row.get("status", "-")),
            court_code=str(row.get("court_code", "-")),
            court_name=str(row.get("court_name", "-")),
            appraisal_summary="",
            crawl_date=str(row.get("crawl_date", "-")),
        )
        items.append(item)

    engine = ValidationEngine(log_path="logs/revalidation.jsonl")
    items = engine.validate_batch(items)
    summary = engine.summary(items)

    print("")
    print("=" * 50)
    print("[재검증 결과]")
    print("  전체  :", summary["total"], "건")
    print("  PASS  :", summary["pass"], "건")
    print("  FAIL  :", summary["fail"], "건")
    print("  정확도:", str(summary["accuracy"]) + "%")
    print("=" * 50)
    for item in items:
        if item.validation_status == "FAIL":
            print("  FAIL | " + item.case_no + " | " + " / ".join(item.validation_reasons))

if __name__ == "__main__":
    main()
