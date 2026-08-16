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
    mark_queue_unsupported,
)
from crawler.doc_crawler import (
    collect_document, build_download_driver, restart_download_driver,
)
from crawler.base_crawler import go_to_case_detail
from models.crawl_outcome import DocWorkerOutcome

os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)

# 2026-08-16 Sprint 142 (Scheduler/Worker Audit): 다운로드 폴더(`crawler/doc_paths.py:
# DOWNLOAD_DIR`)가 프로세스 단위가 아니라 **경로 하나를 모든 doc_worker 실행이 공유**한다.
# `wait_for_download()`는 "다운로드 전 파일 목록"과 "다운로드 후 파일 목록"의 차집합으로
# 방금 받은 파일을 찾는데, 같은 시각에 doc_worker.py 프로세스가 두 개 떠 있으면 한쪽이
# 받은 파일을 다른 쪽이 "내가 받은 파일"로 착각해 엉뚱한 물건에 연결할 수 있다(교차 오염).
# 예약 작업 자체는 기본 MultipleInstances=IgnoreNew라 스케줄러끼리는 겹치지 않지만,
# 운영자가 수동으로 `python doc_worker.py`를 실행하는 동안 스케줄된 실행이 겹치는 경우는
# 막지 못한다. Selenium 다운로드 경로 자체를 프로세스별로 분리하는 것은 위험이 큰 변경이라
# (crawler/doc_crawler.py 0% 커버리지, 실 브라우저 없이 안전하게 검증 불가) 하지 않는다 —
# 대신 **동시 실행 자체를 막는** 가볍고 순수 파이썬-표준라이브러리인 잠금 파일을 둔다.
LOCK_PATH = os.path.join("logs", "doc_worker.lock")
# 예약 작업의 ExecutionTimeLimit(register_scheduler_tasks.ps1, 4시간)보다 여유 있게 잡는다 —
# 정상 종료(finally에서 락 해제)를 못 하고 죽은 경우(프로세스 kill 등)에도 다음 날 실행이
# 영원히 막히지 않도록, 이 시간이 지난 락은 죽은 락으로 간주하고 새로 가져간다
# (reset_stale_queue()의 10분 in_progress 회수와 같은 종류의 "죽은 소유자" 판정 — PID
# 생존 확인은 psutil 같은 새 의존성이 필요해 하지 않는다, 시간 기반 판정으로 충분하다).
LOCK_STALE_HOURS = 5


def _acquire_lock() -> bool:
    """다른 doc_worker.py 인스턴스가 실행 중이 아니면 락을 잡고 True. 이미 실행 중이면 False."""
    if os.path.exists(LOCK_PATH):
        age_hours = (time_module.time() - os.path.getmtime(LOCK_PATH)) / 3600
        if age_hours < LOCK_STALE_HOURS:
            return False
        logger.warning("오래된 락 파일 발견(%.1f시간 경과) - 죽은 실행으로 간주하고 회수", age_hours)
    with open(LOCK_PATH, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()) + " " + datetime.now().isoformat())
    return True


def _release_lock() -> None:
    try:
        os.remove(LOCK_PATH)
    except OSError:
        pass


def is_time_up() -> bool:
    if os.environ.get("DOC_WORKER_TEST_MODE") == "1":
        return False
    now = datetime.now()
    end_hour, end_minute = map(int, DOC_WORKER_END_TIME.split(":"))
    end_dt = now.replace(hour=end_hour, minute=end_minute, second=0, microsecond=0)
    return now >= end_dt


def main() -> int:
    """종료 코드를 돌려준다. 0=성공(또는 처리할 것이 없음), 1=시도한 것이 전부 실패.

    2026-08-11 Sprint 55 (BUGS #47): 예전에는 `-> None`이라 **큐의 모든 항목이 실패해도
    종료 코드가 0**이었다. `run_doc_worker.bat`에는 errorlevel 검사조차 없어서, 실패가
    로그 안쪽 줄에만 남고 스케줄러에는 성공으로 보고됐다.
    """
    logger.info("===== PDF 수집 Worker 시작 (종료 예정: %s) =====", DOC_WORKER_END_TIME)

    # 브라우저를 띄우기 전에 먼저 락을 확인한다 — 어차피 실행하지 못할 거라면 Selenium
    # 기동 비용(수 초~수십 초)을 쓰지 않는다.
    if not _acquire_lock():
        logger.info("다른 doc_worker.py 인스턴스가 이미 실행 중으로 보임 - 이번 실행은 건너뜀"
                    "(다운로드 폴더 교차 오염 방지, %s)", LOCK_PATH)
        return 0

    start_ts = time_module.time()

    try:
        init_db()
        reset_stale_queue()
    except Exception:
        _release_lock()
        raise

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

            # 3차 방어선: 수집 버튼 id가 없으면 브라우저를 열지 않는다.
            #
            # 이것은 **재시도로 해결되지 않는다** — 버튼 id가 없는 이유는 둘 다 영구적이다
            # (현황조사서의 item_no != '1', 알 수 없는 doc_type). 그런데 예전에는
            # `mark_queue_failed()`를 불렀고, `reset_stale_queue()`가 하루 지난 failed를
            # 되살리기 때문에 **성공할 수 없는 항목이 4일 주기로 영원히 재시도됐다**
            # (실측: 16일에 12회 시도, 화면 상태는 FAILED <-> COLLECTING을 계속 오감).
            # 기일 경과와 같은 계열의 종결 처리로 바꿔 그 고리를 끊는다.
            if not btn_id:
                logger.error("[%s-%s] %s 버튼 id 미지원(추가 DOM 분석 필요). 수집 대상에서 종결",
                             case_no, item_no, doc_type)
                mark_queue_unsupported(item["id"], court_code, case_no, item_no, doc_type)
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
                except Exception as restart_exc:
                    # 2026-08-16 Sprint 137 (Failure Recovery Audit, BUGS류): 예전에는
                    # 재시작 자체가 실패해도 여기서 조용히 넘어가 `driver`가 죽은
                    # 상태 그대로 다음 큐 항목으로 넘어갔다. 브라우저/드라이버가
                    # 근본적으로 깨진 환경 문제(ChromeDriver 실행 실패, 리소스 고갈 등)라면
                    # 남은 모든 항목이 **자기 문제와 무관하게** 연쇄로 실패하고
                    # `mark_queue_failed()`가 각자의 `retry_count`를 갉아먹는다 —
                    # MAX_DOC_RETRY(3)라 이런 실행이 3일 반복되면 아무 문제 없던 문서도
                    # 영구 실패(failed, 4일 주기 부활 대상에서도 제외)로 굳는다. 드라이버
                    # 재시작 자체가 안 되는 것은 "이 항목의 문제"가 아니라 "이 실행 전체의
                    # 문제"이므로, 남은 항목의 재시도 예산을 계속 낭비하지 않도록 이번
                    # 실행을 여기서 끝낸다(큐에는 그대로 남아 다음 실행에서 재시도된다 —
                    # 데이터 유실이 아니라 조기 중단일 뿐).
                    logger.error(
                        "드라이버 재시작 실패 - 이번 실행을 중단한다"
                        "(환경 문제로 판단, 남은 큐 항목의 재시도 예산을 계속 소모하지 않기 위해): %s",
                        str(restart_exc))
                    break

            time_module.sleep(2)

    finally:
        try:
            driver.quit()
        except Exception:
            pass
        _release_lock()
        elapsed = time_module.time() - start_ts
        logger.info("===== PDF 수집 Worker 종료 - 시도: %d건, 성공: %d건, 소요시간: %.1f초 =====",
                     processed, succeeded, elapsed)

    outcome = DocWorkerOutcome(processed=processed, succeeded=succeeded)
    reason = outcome.failure_reason()
    if reason:
        logger.error("===== PDF 수집 실패: %s =====", reason)
    return outcome.exit_code()


if __name__ == "__main__":
    sys.exit(main())
