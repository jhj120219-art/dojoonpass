import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import logging
import time as time_module
from datetime import datetime

from config.settings import get_doc_button_id, DOC_WORKER_END_TIME
from storage.database import (
    init_db, reset_stale_queue, claim_next_queue_item,
    mark_queue_done, mark_queue_failed, mark_queue_skipped_expired,
)
from crawler.doc_crawler import (
    collect_document, build_download_driver, restart_download_driver,
)
from crawler.base_crawler import go_to_case_detail

os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)


def is_time_up() -> bool:
    if os.environ.get("DOC_WORKER_TEST_MODE") == "1":
        return False
    now = datetime.now()
    end_hour, end_minute = map(int, DOC_WORKER_END_TIME.split(":"))
    end_dt = now.replace(hour=end_hour, minute=end_minute, second=0, microsecond=0)
    return now >= end_dt


def main() -> None:
    logger.info("===== PDF 수집 Worker 시작 (종료 예정: %s) =====", DOC_WORKER_END_TIME)
    start_ts = time_module.time()

    init_db()
    reset_stale_queue()

    driver = build_download_driver()
    processed = 0
    succeeded = 0

    try:
        while not is_time_up():
            item = claim_next_queue_item()
            if not item:
                logger.info("대기열 비어있음(또는 재시도 대기 중). 종료")
                break

            court_code = item["court_code"]
            case_no = item["case_no"]
            item_no = item["item_no"]
            doc_type = item["doc_type"]
            auction_date = item.get("auction_date", "")

            # 2차 방어선: 매각기일이 이미 지난 항목은 브라우저 작업 없이 즉시 종료.
            # (1차 방어선은 enqueue_documents에서 애초에 큐에 안 넣는 것이지만,
            #  이미 06:00에 적재된 뒤 시간이 흘러 오늘 자정을 넘긴 경우를 위한 대비)
            today = datetime.now().strftime("%Y-%m-%d")
            if auction_date and auction_date < today:
                mark_queue_skipped_expired(item["id"], court_code, case_no, item_no, doc_type, auction_date)
                continue

            btn_id = get_doc_button_id(doc_type, item_no)

            if not btn_id:
                logger.error("[%s-%s] %s 버튼 id 미지원(추가 DOM 분석 필요). 실패 처리",
                             case_no, item_no, doc_type)
                mark_queue_failed(item["id"], item["retry_count"])
                continue

            processed += 1
            try:
                ok = go_to_case_detail(driver, court_code, case_no)
                if not ok:
                    raise Exception("사건 상세 진입 실패")

                result = collect_document(driver, court_code, case_no, item_no, doc_type, btn_id)

                if result["success"]:
                    mark_queue_done(
                        item["id"], court_code, case_no, item_no, doc_type,
                        result["previous_hash"], result["new_hash"]
                    )
                    succeeded += 1
                    if result.get("partial"):
                        logger.warning("[%s-%s] %s 부분 성공(원본만 저장, 구조화 실패)", case_no, item_no, doc_type)
                    else:
                        logger.info("[%s-%s] %s 처리 성공", case_no, item_no, doc_type)
                else:
                    mark_queue_failed(item["id"], item["retry_count"])
                    logger.warning("[%s-%s] %s 처리 실패 (retry=%d)", case_no, item_no, doc_type, item["retry_count"] + 1)

            except Exception as e:
                logger.error("[%s-%s] %s 처리 중 오류: %s", case_no, item_no, doc_type, str(e))
                mark_queue_failed(item["id"], item["retry_count"])
                try:
                    driver = restart_download_driver(driver)
                except Exception:
                    pass

            time_module.sleep(2)

    finally:
        try:
            driver.quit()
        except Exception:
            pass
        elapsed = time_module.time() - start_ts
        logger.info("===== PDF 수집 Worker 종료 - 시도: %d건, 성공: %d건, 소요시간: %.1f초 =====",
                     processed, succeeded, elapsed)


if __name__ == "__main__":
    main()
