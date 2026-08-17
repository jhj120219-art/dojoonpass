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
    mark_queue_unsupported, save_auction_images, reconcile_queue_auction_date,
)
from crawler.doc_crawler import (
    collect_document, build_download_driver, restart_download_driver,
    SIBLING_REUSE_MAX_AGE_SECONDS,
)
from crawler.doc_paths import CASE_LEVEL_DOC_TYPES, find_sibling_case_document
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

    # 실행 창이 이미 닫혔으면 여기서 끝낸다. 바로 위 락 검사와 **같은 이유**다 —
    # 어차피 한 건도 처리하지 못할 실행에 Selenium 기동 비용을 쓰지 않는다.
    #
    # 예전에는 이 검사가 아래 `while not is_time_up()` 루프 조건에만 있었다. 그래서
    # 창 밖에서 기동하면 드라이버를 **띄운 뒤에** 루프 첫 조건에서 곧바로 빠져나왔다.
    # 스케줄러 실행이 밀렸을 때나 수동으로 돌릴 때 실제로 도달한다(2026-08-17 14:22
    # 실측: `is_time_up()`이 True인데 드라이버는 그대로 기동됐다).
    #
    # `reset_stale_queue()`보다 앞에 둔다. 그 함수는 다음 실행을 위한 준비 작업이라
    # 처리할 시간이 없는 실행에서 큐 상태를 건드릴 이유가 없다.
    if is_time_up():
        logger.info("실행 창(%s)이 이미 지났다 - 브라우저를 띄우지 않고 종료",
                    DOC_WORKER_END_TIME)
        _release_lock()
        return 0

    start_ts = time_module.time()

    # 드라이버 기동까지 이 try 안에 둔다. 예전에는 `build_download_driver()`가 이 블록
    # **밖**에 있어서, 락을 해제하는 두 구간(위의 except, 아래 while의 finally) 사이에
    # 끼어 있었다. 그래서 드라이버 기동이 실패하면 락 파일이 그대로 남았다
    # (2026-08-17 실측 재현 — logs/doc_worker.lock에 죽은 PID가 남았다).
    #
    # `LOCK_STALE_HOURS=5` 덕에 영구 정지는 아니지만, 하필 **재시도하고 싶은 5시간
    # 동안** 후속 실행이 "다른 인스턴스 실행 중"으로 건너뛴다. 드라이버 기동 실패는
    # 일시적 원인(크롬 업데이트 중, 임시 자원 부족)이 많아 곧바로 다시 시도할 값어치가
    # 있는데, 바로 그 창을 막고 있었다.
    try:
        init_db()
        reset_stale_queue()
        driver = build_download_driver()
    except Exception:
        _release_lock()
        raise

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
            #
            # 2026-08-17 Sprint 145: 종결하기 **전에** 권위 있는 값과 대조한다.
            # 큐의 auction_date는 06:00에 복사해 둔 사본이라, 유찰 후 재매각으로 기일이
            # 미래로 다시 잡히면 옛 날짜가 남는다. 그 상태로 여기서 종결하면 **지금
            # 검색에 노출되는 진행 중 물건의 문서가 영원히 수집되지 않는다**
            # (실측: item 1533 = 2024타경122092-1, 큐 2026-07-15 vs 실제 2026-08-19).
            today = datetime.now().strftime("%Y-%m-%d")
            if auction_date and auction_date < today:
                # ★ court_code를 반드시 함께 넘긴다 (2026-08-17 Sprint 146).
                #   법원마다 사건번호를 독립 채번하므로 (사건,물건)만으로는 **다른 법원의
                #   물건**에 걸린다 — 실측 18행(pending 12행)이 실제로 그랬다.
                #   그 상태로 정정하면 엉뚱한 사건의 기일로 이 큐를 덮어쓴다(BUGS #103).
                auction_date = reconcile_queue_auction_date(
                    item["id"], case_no, item_no, auction_date, court_code
                )
            if auction_date and auction_date < today:
                mark_queue_skipped_expired(item["id"], court_code, case_no, item_no, doc_type, auction_date)
                continue

            # 2026-08-17 Sprint 144: 물건 사진('image')은 **버튼이 없다.** 상세페이지에
            # 진입하면 캐러셀이 이미 DOM에 있다(법원 원천 실측 — crawler/image_crawler.py
            # 모듈 주석). 버튼 id를 요구하면 아래 3차 방어선이 "미지원"으로 종결시켜
            # 사진이 영영 수집되지 않으므로, 이 종류만 검사를 건너뛴다.
            needs_button = doc_type != "image"
            btn_id = get_doc_button_id(doc_type, item_no) if needs_button else ""

            # 3차 방어선: 수집 버튼 id가 없으면 브라우저를 열지 않는다.
            #
            # 이것은 **재시도로 해결되지 않는다** — 버튼 id가 없는 이유는 둘 다 영구적이다
            # (현황조사서의 item_no != '1', 알 수 없는 doc_type). 그런데 예전에는
            # `mark_queue_failed()`를 불렀고, `reset_stale_queue()`가 하루 지난 failed를
            # 되살리기 때문에 **성공할 수 없는 항목이 4일 주기로 영원히 재시도됐다**
            # (실측: 16일에 12회 시도, 화면 상태는 FAILED <-> COLLECTING을 계속 오감).
            # 기일 경과와 같은 계열의 종결 처리로 바꿔 그 고리를 끊는다.
            if needs_button and not btn_id:
                logger.error("[%s-%s] %s 버튼 id 미지원(추가 DOM 분석 필요). 수집 대상에서 종결",
                             case_no, item_no, doc_type)
                mark_queue_unsupported(item["id"], court_code, case_no, item_no, doc_type)
                continue

            processed += 1
            try:
                # ★ 사건 단위 문서는 **브라우저를 열기 전에** 형제 물건 복사를 먼저 시도한다
                #   (2026-08-17 Sprint 147).
                #
                #   Sprint 145가 `collect_status()` 안에 형제 재사용을 넣었는데, 이 루프가
                #   `go_to_case_detail()`을 **무조건 먼저** 부르는 구조라 정작 비싼 부분이
                #   그대로 들었다. 실측(2026-08-17):
                #
                #       navigation   15.2초   <- 재사용해도 그대로 들던 비용
                #       overlay 수집  0.6초   <- 재사용이 아끼던 전부
                #       형제 복사     0.002초
                #
                #   즉 절감이 물건당 0.6초(4%)뿐이었다. 492회 기준 5분. Sprint 145 문서가
                #   적어 둔 "약 3시간 절감"은 **navigation까지 건너뛴다고 가정한 값**이라
                #   틀렸다. 순서를 바꾸면 실제로 그 가정이 성립한다 — 물건당 15.8초 -> 0.002초,
                #   492회 기준 약 130분.
                #
                #   복사가 실제로 이뤄지지 않으면(형제가 빈 캡처였다 등) `reused_from`이
                #   비어 돌아오므로 아래에서 정상 경로로 떨어진다 — 브라우저 없이 실패로
                #   종결시키지 않는다.
                result = None
                if doc_type in CASE_LEVEL_DOC_TYPES and find_sibling_case_document(
                        court_code, case_no, item_no, doc_type,
                        max_age_seconds=SIBLING_REUSE_MAX_AGE_SECONDS):
                    candidate = collect_document(None, court_code, case_no, item_no,
                                                 doc_type, btn_id)
                    if candidate.get("reused_from"):
                        result = candidate

                if result is None:
                    # item_no를 넘긴다 (2026-08-17 Sprint 144). 사진은 버튼 없이 상세페이지
                    # DOM을 그대로 읽으므로 **어느 물건의 페이지인지가 곧 결과**다.
                    ok = go_to_case_detail(driver, court_code, case_no, item_no)
                    if not ok:
                        raise Exception("사건 상세 진입 실패")

                    result = collect_document(driver, court_code, case_no, item_no,
                                              doc_type, btn_id)

                if result["success"]:
                    # 2026-08-17 Sprint 144: 사진은 "성공했는데 저장할 것이 없는" 경우가
                    # 있다 — 법원이 그 물건의 사진을 아예 제공하지 않는 것이고, 재시도해도
                    # 결과가 같은 **정상 종결**이다. 그때 READY로 쓰면 화면이 "볼 수 있다"고
                    # 거짓말하므로 상태를 구분한다(FAILED도 아니다 — 실패가 아니니까).
                    done_status = "NO_IMAGE" if result.get("no_asset") else "READY"
                    mark_queue_done(
                        item["id"], court_code, case_no, item_no, doc_type,
                        result["previous_hash"], result["new_hash"],
                        status=done_status, files_saved=result.get("files_saved"),
                    )

                    # 사진은 개수가 0~N이라 `doc_raw`(종류당 1행)에 담기지 않는다.
                    # 실체 기록은 `auction_image`가 맡는다(migration 020).
                    if doc_type == "image" and result.get("images"):
                        # 부분 수집이면 옛 행을 지우지 않는다 — 받지 못한 사진이
                        # "법원이 내린 것"인지 "이번에 실패한 것"인지 구별할 수 없고,
                        # 지우면 사용자가 보던 사진이 사라진다 (Sprint 186).
                        stat = save_auction_images(
                            court_code, case_no, item_no, result["images"],
                            complete=not result.get("partial"))
                        logger.info("[%s-%s] 사진 DB 기록: 저장 %d / 누락 %d / 오래된 행 정리 %d",
                                    case_no, item_no, stat["saved"],
                                    stat["skipped_missing"], stat["removed_stale"])

                    succeeded += 1
                    if result.get("no_asset"):
                        logger.info("[%s-%s] %s 처리 성공(원천에 자산 없음)", case_no, item_no, doc_type)
                    elif result.get("partial"):
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
