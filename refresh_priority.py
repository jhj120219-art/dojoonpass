import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import logging

os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)

from storage.database import init_db, refresh_queue_priority


def main() -> None:
    logger.info("===== document_queue 우선순위 재계산 시작 =====")
    init_db()
    # 반환값은 **실제로 우선순위가 바뀐 행 수**다(검토한 행 수가 아니다 — 2026-08-12
    # Sprint 63에 정정). 대부분의 날은 0~수십 건이며, 그것이 정상이다.
    changed = refresh_queue_priority()
    logger.info("===== 우선순위 재계산 완료: %d건 변경 =====", changed)


if __name__ == "__main__":
    main()
