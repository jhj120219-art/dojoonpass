import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import logging

os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/doc_run.log", encoding="utf-8"),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)

from storage.database import init_db, refresh_queue_priority


def main() -> None:
    logger.info("===== document_queue 우선순위 재계산 시작 =====")
    init_db()
    updated = refresh_queue_priority()
    logger.info("===== 우선순위 재계산 완료: %d건 =====", updated)


if __name__ == "__main__":
    main()
