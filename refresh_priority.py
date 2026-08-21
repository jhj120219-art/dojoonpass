import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import logging

# ★ 로그/락 경로는 **현재 작업 디렉터리가 아니라 이 파일 기준**이다 (2026-08-21 Sprint 246).
#   상대경로면 다른 cwd 에서 띄웠을 때 그 폴더에 logs/ 가 새로 생긴다. 로그가 흩어지는 건
#   그나마 낫고, **락 파일이 갈라지면 중복 실행 방지가 조용히 무력화된다** - 실측했다:
#     A(저장소 루트) 락 획득 -> B(같은 cwd) 차단 O / C(다른 cwd) **획득됨**
#   즉 doc_worker 두 개가 같은 큐/다운로드 폴더를 동시에 만진다.
#   `.bat` 3개는 `cd /d %~dp0` 로 스스로를 보호하지만 수동 실행/서비스 등록은 아니다.
_HERE = os.path.dirname(os.path.abspath(__file__))
os.makedirs(os.path.join(_HERE, "logs"), exist_ok=True)

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
