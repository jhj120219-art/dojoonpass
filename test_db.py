import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# --- 실행 가드 (2026-08-11 Sprint 55, docs/BUGS.md #51) -----------------------
# 이 파일은 이름이 test_*.py이지만 **테스트가 아니다.** assert가 하나도 없고 PASS/FAIL도
# 없으며, 실제 `courtauction.go.kr`에 접속해 크롤링한다(일부는 `input()`으로 사람 입력까지
# 기다린다).
#
# 문서에는 "회귀에서 자동 실행하지 않는다"고 여러 곳에 적혀 있었지만, 그것은 **규약**일 뿐
# 아무것도 막지 못했다. 실제로 2026-08-11 감사 중 `test_*.py`를 전부 실행하는 스윕이
# 두 번 돌았고, selenium이 설치돼 있지 않아서 **우연히** 실제 접속이 일어나지 않았을 뿐이다.
# 규약 대신 구조로 막는다.
#
# 파일명을 바꾸지 않는 이유: 이 이름이 docs 6개 파일에 참조돼 있어, 이름을 바꾸면
# 문서가 한꺼번에 낡는다. 이름은 두고 **실행만** 막는 편이 부작용이 작다.
if __name__ == "__main__" and os.environ.get("ALLOW_LIVE_CRAWL") != "1":
    print("[SKIPPED] %s 는 실제 법원 사이트에 접속하는 수동 스크립트입니다 (회귀 대상 아님)."
          % os.path.basename(__file__))
    print("          실행하려면 명시적으로 허용하십시오:  ALLOW_LIVE_CRAWL=1 python %s"
          % os.path.basename(__file__))
    raise SystemExit(0)
# -----------------------------------------------------------------------------

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
