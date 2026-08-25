import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import logging
import time as time_module
from datetime import datetime

from config.settings import get_doc_button_id, DOC_WORKER_END_TIME
from storage.database import (
    init_db, reset_stale_queue, claim_next_item_rows, release_queue_rows,
    mark_queue_done, mark_queue_failed, mark_queue_skipped_expired,
    mark_queue_unsupported, save_auction_images, reconcile_queue_auction_date,
    clear_images_if_absence_confirmed,
)
from crawler.image_assets import remove_stored_image_files
from crawler.doc_crawler import (
    collect_document, build_download_driver, restart_download_driver,
    SIBLING_REUSE_MAX_AGE_SECONDS,
)
from crawler.doc_paths import CASE_LEVEL_DOC_TYPES, find_sibling_case_document
from crawler.base_crawler import go_to_case_detail, wait_for_detail
from models.crawl_outcome import DocWorkerOutcome
from storage.checkpoint import RunLock

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
LOCK_PATH = os.path.join(_HERE, "logs", "doc_worker.lock")
# 예약 작업의 ExecutionTimeLimit(register_scheduler_tasks.ps1, 4시간)보다 여유 있게 잡는다 —
# 정상 종료(finally에서 락 해제)를 못 하고 죽은 경우(프로세스 kill 등)에도 다음 날 실행이
# 영원히 막히지 않도록, 이 시간이 지난 락은 죽은 락으로 간주하고 새로 가져간다
# (reset_stale_queue()의 10분 in_progress 회수와 같은 종류의 "죽은 소유자" 판정 — PID
# 생존 확인은 psutil 같은 새 의존성이 필요해 하지 않는다, 시간 기반 판정으로 충분하다).
LOCK_STALE_HOURS = 5


def _lock() -> RunLock:
    """지금의 `LOCK_PATH`/`LOCK_STALE_HOURS` 로 락 객체를 만든다.

    ★ 모듈 로드 시점에 한 번 만들어 두지 **않는다** — 그러면 나중에 누가
      `LOCK_PATH` 를 바꿔도 락은 옛 경로를 계속 본다(스냅숏 함정).
      같은 실수를 `audit_asset_integrity.py` 가 `DB_PATH` 에서 한 번 했다(Sprint 193).
    """
    return RunLock(LOCK_PATH, LOCK_STALE_HOURS, label="doc_worker")


def _acquire_lock() -> bool:
    """다른 doc_worker.py 인스턴스가 실행 중이 아니면 락을 잡고 True. 이미 실행 중이면 False.

    2026-08-18 Sprint 194: 구현을 `storage/checkpoint.py:RunLock` 으로 옮겼다.
    (2026-08-19 Sprint 217 정정: 이 줄은 `storage/runlock.py` 라고 적고 있었는데 **그런
     파일은 없다.** 처음엔 그 이름으로 새로 만들었다가 "추적 파일이 미추적 파일을
     import 하지 않는다" 가드에 걸려 이미 추적된 모듈로 옮겼고 — 그 경위는
     `docs/BUGS.md` #132 에 정확히 남아 있는데 — 여기 주석만 옛 이름 그대로였다.)
    **동작은 그대로다** —
    같은 방어가 필요한 배치(`mvp_scraper.py`)가 하나 더 있는데 규칙을 베끼고 싶지 않았다
    (이 저장소는 "규칙이 두 벌"에서 반복해 사고를 겪었다: BUGS #107/#112/#136/#161).
    이 함수와 `LOCK_PATH`/`LOCK_STALE_HOURS` 는 회귀가 참조하는 공개 표면이라 유지한다.
    """
    return _lock().acquire()


def _release_lock() -> None:
    _lock().release()


class CaseNotReachable(Exception):
    """사건 상세로 들어가지 못했다 — **브라우저 고장이 아니다** (2026-08-20 Sprint 232).

    `go_to_case_detail()` 이 False 를 돌려주는 이유는 둘 다 정상적인 판단 결과다.

        1. 그 사건이 법원 목록에 없다 (기일이 지나 빠졌거나 취하/변경)
        2. 물건번호가 모호해 **일부러 진입하지 않았다** (Sprint 230 의 사진 오염 방어)

    둘 다 브라우저는 멀쩡하다. 그런데 예전에는 이것을 그냥 `Exception` 으로 올려
    `except` 절이 **드라이버를 통째로 재시작**했다.

    ## 왜 고치는가 — 시간보다 **연쇄 위험**이 문제다

    실측(`logs/doc_run.log`, 2026-07-08~07-12 11일치):

        "사건 매칭 실패" 255회, 전부 뒤에 드라이버 재시작이 따라붙었다
        재시작 -> 재개까지 평균 5.9초 (중앙값 5.9 / 최대 11.4)
        합계 1,506초 = 25.1분  ->  하루 평균 2.3분 (실행 창 120분의 약 2%)

    시간 낭비 자체는 **크지 않다**. 진짜 문제는 그 다음이다 —
    `restart_download_driver()` 가 실패하면 Sprint 137 의 방어가 발동해
    **그 날 실행 전체를 중단**한다. 즉 "사건 하나를 못 찾았다"는 무해한 사실이
    운 나쁘면 **하루치 수집을 통째로 죽일 수 있다.**

    그리고 Sprint 230 이 넣은 *의도적 거부*(사진 물건 모호)도 같은 경로를 타서,
    **옳은 판단이 드라이버 재시작을 부르는** 모양이 됐다.

    그래서 이 경우만 따로 잡아 재시작 없이 다음 항목으로 넘어간다.
    재시도 예산은 종전대로 소모한다(큐 의미론은 바꾸지 않는다).
    """


def _batch_order(row: dict) -> int:
    """묶음 안의 처리 순서. **사진을 먼저** 둔다 (2026-08-20 Sprint 236).

    사진만 `require_exact_item=True` 로 들어가야 한다 - 버튼이 없어 페이지에 그려진
    것을 그대로 읽으므로 물건이 틀리면 사진도 틀린다(Sprint 230). 사진을 먼저 처리하면
    그 **엄격한** 이동 한 번을 나머지 종류가 그대로 재사용한다. 반대 순서로 두면
    느슨하게 들어갔다가 사진 차례에 다시 들어가야 해서 이동이 2회가 된다.

    사진 수집은 DOM 을 읽기만 하므로(클릭도 창 열기도 없다 - crawler/image_crawler.py
    에서 driver 를 쓰는 곳은 `find_elements` 한 줄뿐이다) 뒤 순서를 망가뜨리지 않는다.
    """
    return 0 if row.get("doc_type") == "image" else 1


def _ensure_detail_page(driver, state: dict, court_code: str, case_no: str,
                        item_no: str, require_exact: bool) -> bool:
    """상세페이지에 서 있게 만든다. **이미 서 있으면 이동하지 않는다.**

    ## 왜 (2026-08-20 Sprint 236, BUGS #173)

    `go_to_case_detail()` 은 실측 중앙값 10.9초다. 같은 물건의 4종을 받으려고 같은
    페이지에 네 번 들어가던 것을 한 번으로 줄인다 - 이 저장소에서 가장 큰 단일 비용이다.

    ## ★ 믿지 않고 확인한다

    "아까 들어갔으니 아직 그 페이지일 것"이라고 **가정하지 않는다.** 문서 수집기는
    새 창을 열고 닫은 뒤 원래 창으로 돌아오는데, 그 복구가 전부 `try/except: pass`
    다(crawler/doc_crawler.py 의 finally 두 곳). 돌아오지 못한 채로 다음 종류를
    처리하면 **엉뚱한 화면에서 남의 문서를 긁는다** - 이 저장소가 사진에서 겪은
    (Sprint 230) 것과 같은 계열의, 조용히 틀리는 결함이다.

    그래서 재사용 전에 `wait_for_detail()` 로 화면을 실제로 확인한다. 이미 그 페이지면
    첫 폴에서 곧바로 True 라 비용이 사실상 없고, 벗어나 있으면 정직하게 다시 이동한다.

    ## 엄격도

    엄격하게(`require_exact_item=True`) 들어간 페이지는 느슨한 요구에도 쓸 수 있지만,
    그 반대는 안 된다. 느슨하게 들어간 페이지를 사진이 재사용하면 Sprint 230 이 막은
    "다른 물건의 사진"이 그대로 돌아온다.
    """
    key = (court_code, case_no, item_no)
    if state.get("key") == key and (state.get("exact") or not require_exact):
        if wait_for_detail(driver, case_no):
            logger.info("[%s-%s] 상세페이지 재사용 - 이동 생략", case_no, item_no)
            state["reused"] = state.get("reused", 0) + 1
            return True
        logger.warning("[%s-%s] 상세페이지를 벗어나 있다 - 다시 이동한다", case_no, item_no)

    # 이 시점부터 우리는 브라우저가 어디에 있는지 모른다. 이동이 성공해야만 다시 안다.
    state["key"] = None
    ok = go_to_case_detail(driver, court_code, case_no, item_no,
                           require_exact_item=require_exact)
    state["navigations"] = state.get("navigations", 0) + 1
    if ok:
        state["key"] = key
        state["exact"] = require_exact
    return ok


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

    # ★ 물건 단위 처리 (2026-08-20 Sprint 236).
    #   `batch` = 지금 집어 둔 한 물건의 아직 처리하지 않은 큐 행.
    #   `page`  = 브라우저가 지금 어느 물건의 상세페이지에 서 있는지.
    #   둘 다 이 실행 안에서만 사는 값이라 모듈 전역으로 두지 않는다
    #   (전역이면 테스트가 서로의 상태를 물려받는다).
    batch = []
    page = {}

    try:
        while not is_time_up():
            if not batch:
                # 한 물건의 행을 한꺼번에 집는다. 사진을 먼저 처리하도록 정렬한다.
                batch = sorted(claim_next_item_rows(), key=_batch_order)
                if not batch:
                    logger.info("대기열 비어있음(또는 재시도 대기 중). 종료")
                    break
            item = batch.pop(0)

            court_code = item["court_code"]
            case_no = item["case_no"]
            item_no = item["item_no"]
            doc_type = item["doc_type"]
            auction_date = item.get("auction_date", "")
            # 2026-08-18 Sprint 189: 'refresh'로 집어간 항목은 **이미 받아 둔 것이 있는데
            # 다시 받아야 한다**는 뜻이다. 이 값을 안 넘기면 수집기가 "이미 존재. 스킵"으로
            # 곧바로 성공 처리해, 큐만 done으로 돌고 파일은 그대로인 헛수집이 된다.
            # 판단은 `claim_next_queue_item()`이 이미 했다(어휘를 여기서 복제하지 않는다).
            overwrite = bool(item.get("overwrite"))

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
                mark_queue_skipped_expired(item["id"], court_code, case_no, item_no,
                                           doc_type, auction_date,
                                           item.get("claim_token"))
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
                mark_queue_unsupported(item["id"], court_code, case_no, item_no,
                                       doc_type, item.get("claim_token"))
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
                # ★ 재수집(overwrite)일 때는 형제 복사를 쓰지 않는다 (Sprint 189).
                #   형제 물건의 사본도 **같은 옛 수집분**이다. 그것을 복사해 오면
                #   법원이 갱신한 새 문서 대신 옛 내용을 다시 저장하고, 큐는 done이 되어
                #   재수집 기회가 사라진다 — 재수집을 켠 의미가 정확히 없어진다.
                #   (최초 수집에서는 여전히 브라우저 navigation 15초를 아끼는 큰 최적화다.)
                if (not overwrite and doc_type in CASE_LEVEL_DOC_TYPES
                        and find_sibling_case_document(
                            court_code, case_no, item_no, doc_type,
                            max_age_seconds=SIBLING_REUSE_MAX_AGE_SECONDS)):
                    candidate = collect_document(None, court_code, case_no, item_no,
                                                 doc_type, btn_id)
                    if candidate.get("reused_from"):
                        result = candidate

                if result is None:
                    # item_no를 넘긴다 (2026-08-17 Sprint 144). 사진은 버튼 없이 상세페이지
                    # DOM을 그대로 읽으므로 **어느 물건의 페이지인지가 곧 결과**다.
                    # ★ 사진일 때만 물건번호 정확 일치를 요구한다 (Sprint 230).
                    #   문서(spec/appraisal)는 버튼 id 에 물건번호가 붙어 있어 어느 물건의
                    #   페이지에서 눌러도 그 물건의 문서가 나온다(실측: 다중물건 22건에서
                    #   서로 다른 물건이 같은 바이트인 경우 0건). 사진은 버튼이 없어
                    #   **페이지에 그려진 것을 그대로** 읽으므로 물건이 틀리면 사진도 틀린다.
                    ok = _ensure_detail_page(driver, page, court_code, case_no,
                                             item_no,
                                             require_exact=(doc_type == "image"))
                    if not ok:
                        # 브라우저 고장이 아니다 - 재시작 없이 이 항목만 실패 처리한다.
                        raise CaseNotReachable("사건 상세 진입 실패")

                    result = collect_document(driver, court_code, case_no, item_no,
                                              doc_type, btn_id, overwrite=overwrite)

                if result["success"]:
                    # 2026-08-17 Sprint 144: 사진은 "성공했는데 저장할 것이 없는" 경우가
                    # 있다 — 법원이 그 물건의 사진을 아예 제공하지 않는 것이고, 재시도해도
                    # 결과가 같은 **정상 종결**이다. 그때 READY로 쓰면 화면이 "볼 수 있다"고
                    # 거짓말하므로 상태를 구분한다(FAILED도 아니다 — 실패가 아니니까).
                    done_status = "NO_IMAGE" if result.get("no_asset") else "READY"

                    # ★ 법원이 사진을 **전부** 내린 경우는 여기서만 처리된다
                    #   (2026-08-18 Sprint 191, BUGS #128).
                    #   아래 `save_auction_images()` 호출은 `result["images"]` 가 비면
                    #   건너뛰므로 — 그 가드 자체는 옳다(빈 목록은 전체 실패와 구별되지
                    #   않는다) — 0장으로 줄어드는 경우만 아무도 정리하지 않았다.
                    #   `mark_queue_done()` **보다 먼저** 부른다: 그 함수가 상태를
                    #   NO_IMAGE 로 덮고 나면 1회차인지 2회차인지 알 수 없게 된다.
                    if doc_type == "image" and result.get("no_asset"):
                        absent = clear_images_if_absence_confirmed(
                            court_code, case_no, item_no)
                        if absent["cleared"]:
                            gone = remove_stored_image_files(absent["paths"])
                            logger.info("[%s-%s] 사진 정리: 행 %d / 파일 %d",
                                        case_no, item_no, absent["cleared"], gone)

                    # 사진은 개수가 0~N이라 `doc_raw`(종류당 1행)에 담기지 않는다.
                    # 실체 기록은 `auction_image`가 맡는다(migration 020).
                    #
                    # ★ `mark_queue_done()` **보다 먼저** 부른다 (2026-08-18 Sprint 208).
                    #
                    #   예전에는 순서가 반대였다 — 성공을 먼저 기록하고 사진을 나중에 적었다.
                    #   그 사이에서 이 호출이 실패하면(DB 잠금, 파일 접근 실패 등) 바깥
                    #   `except`가 큐를 되돌려 재시도는 되지만, **`document_status`는 이미
                    #   READY로 덮여 있다.** 화면은 "사진 있음"이라고 말하는데
                    #   `auction_image`는 0행이다. 재시도가 소진되면 그 거짓말이 영구가 된다.
                    #
                    #   fixture 로 재현했다(Sprint 208):
                    #       document_status = IMAGE/READY, auction_image = 0행, 큐 = pending(retry 1)
                    #
                    #   실체를 먼저 적으면 실패는 그냥 실패로 남는다 — 성공 표시가 없으니
                    #   화면도 거짓말하지 않고, 큐만 재시도한다. 순서를 바꾸는 것 말고
                    #   추가로 하는 일은 없다.
                    # ★ 기록 결과를 **판정에 쓴다** (2026-08-18 Sprint 214).
                    #
                    #   Sprint 208 이 순서를 바로잡았지만(실체 -> 성공), 그것만으로는
                    #   부족했다. `save_auction_images()` 는 **예외를 던지지 않고**
                    #   0장을 기록할 수 있다 — 디스크에 파일이 없으면 그 항목을 전부
                    #   건너뛰고 `saved=0, skipped_missing=N` 을 돌려준다(그 가드 자체는
                    #   옳다: DB 만 앞서가지 않게 하는 이 저장소의 규약이다).
                    #
                    #   그런데 호출부가 그 반환값을 **로그로만** 썼다. 그래서
                    #   수집기가 사진 2장을 줬는데 한 장도 기록되지 못한 실행이
                    #   `done` + `READY` 로 끝났다. fixture 로 두 경로를 재현했다:
                    #
                    #       C 수집기가 준 경로에 파일이 없다   -> done/READY/0행
                    #       E save 가 saved=0 을 돌려준다      -> done/READY/0행
                    #
                    #   "함수를 불렀다"와 "성공했다"는 다르다. 한 장도 남기지 못한 실행은
                    #   성공이 아니라 **재시도해야 할 실패**다.
                    #
                    #   부분 성공(`partial`)은 그대로 성공이다 — 한 장이라도 남았으면
                    #   사용자가 볼 것이 생긴다. 0장만 실패로 본다.
                    #   `no_asset`(법원이 사진을 안 준다)은 애초에 이 분기에 오지 않는다.
                    asset_recorded = True

                    # ★ 문서도 같은 계열이다 (2026-08-18 Sprint 214 §2).
                    #
                    #   `_record_doc_raw()` 의 docstring 이 이미 적고 있었다 —
                    #   "파일이 없으면 ... doc_raw 행을 만들지 않는다 — 큐/상태는
                    #    **이미 done/READY로 갔지만** ... 여기서 뒤집지는 않는다
                    #    (뒤집으려면 collect_document() 의 성공 판정을 고쳐야 한다)."
                    #
                    #   그 "고쳐야 한다"를 여기서 한다. fixture 로 재현했다:
                    #   수집기가 `files_saved=[spec.pdf]` 를 돌려줬는데 그 파일이 없으면
                    #   `queue=done` / `document_status=READY` / `doc_raw=0행` 으로 끝나고,
                    #   API 는 `available=true` 에 `viewer_url` 까지 준다.
                    #
                    #   검사 범위를 좁게 잡는다 — **수집기가 저장했다고 말한 파일만** 본다.
                    #     - `files_saved` 가 비면 검사하지 않는다: "이미 존재. 스킵" 경로가
                    #       정상적으로 빈 목록을 돌려준다(그 문서는 이전에 이미 받아 뒀다).
                    #     - `doc_exists()` 로 완성도를 요구하지 않는다: 문서에도
                    #       부분 성공(원본만 저장, 구조화 실패)이 계약으로 있어서
                    #       그것까지 실패로 뒤집으면 정책을 바꾸는 것이 된다.
                    if doc_type != "image":
                        claimed = [p for p in (result.get("files_saved") or []) if p]
                        missing = [p for p in claimed
                                   if not (os.path.isfile(p) and os.path.getsize(p) > 0)]
                        if missing:
                            logger.warning(
                                "[%s-%s] %s 저장했다는 파일이 실제로 없다 %s "
                                "- 성공으로 종결하지 않고 재시도한다",
                                case_no, item_no, doc_type,
                                [os.path.basename(p) for p in missing])
                            asset_recorded = False

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
                        asset_recorded = stat["saved"] > 0

                    if not asset_recorded:
                        logger.warning(
                            "[%s-%s] 사진 %d장을 받았다고 했으나 **한 장도 기록되지 못했다** "
                            "- 성공으로 종결하지 않고 재시도한다",
                            case_no, item_no, len(result.get("images") or ()))
                        mark_queue_failed(item["id"], item["retry_count"],
                                          item.get("claim_token"))
                    else:
                        mark_queue_done(
                            item["id"], court_code, case_no, item_no, doc_type,
                            result["previous_hash"], result["new_hash"],
                            status=done_status, files_saved=result.get("files_saved"),
                            claim_token=item.get("claim_token"),
                        )

                        succeeded += 1
                        if result.get("no_asset"):
                            logger.info("[%s-%s] %s 처리 성공(원천에 자산 없음)", case_no, item_no, doc_type)
                        elif result.get("partial"):
                            logger.warning("[%s-%s] %s 부분 성공(원본만 저장, 구조화 실패)", case_no, item_no, doc_type)
                        else:
                            logger.info("[%s-%s] %s 처리 성공%s", case_no, item_no, doc_type,
                                        " (재수집)" if overwrite else "")
                else:
                    mark_queue_failed(item["id"], item["retry_count"], item.get("claim_token"))
                    logger.warning("[%s-%s] %s 처리 실패 (retry=%d)", case_no, item_no, doc_type, item["retry_count"] + 1)

            except CaseNotReachable as e:
                # ★ 재시작하지 않는다 (2026-08-20 Sprint 232).
                #   브라우저는 멀쩡하고 다음 항목은 그대로 진행할 수 있다.
                #   재시작은 평균 5.9초를 쓰고(실측 255회), 그 재시작이 실패하면
                #   Sprint 137 방어가 **하루치 실행 전체를 중단**시킨다 —
                #   "사건 하나를 못 찾았다"가 그런 결과를 부를 이유가 없다.
                logger.warning("[%s-%s] %s: %s (브라우저 정상 - 재시작 없이 다음 항목으로)",
                               case_no, item_no, doc_type, str(e))
                mark_queue_failed(item["id"], item["retry_count"], item.get("claim_token"))
                time_module.sleep(1)
                continue

            except Exception as e:
                logger.error("[%s-%s] %s 처리 중 오류: %s", case_no, item_no, doc_type, str(e))
                mark_queue_failed(item["id"], item["retry_count"], item.get("claim_token"))
                # ★ 드라이버를 재시작하면 그 전에 서 있던 페이지는 사라진다.
                #   기억을 지우지 않으면 다음 종류가 "재사용 가능"으로 읽고
                #   **빈 페이지에서 수집을 시도**한다 (2026-08-20 Sprint 236).
                page.clear()
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
        # ★ 집어만 두고 **한 번도 시도하지 않은** 행을 즉시 대기 상태로 돌려놓는다
        #   (2026-08-20 Sprint 236). 실행 창이 닫혔거나 드라이버 재시작이 실패해
        #   묶음의 뒷부분이 남은 경우다.
        #
        #   되돌리지 않아도 `reset_stale_queue()` 가 10분 뒤 회수하므로 유실은 아니다.
        #   다만 그 10분 동안 화면은 '수집중'이고, 다음 실행이 그 사이에 뜨면
        #   집지 못한다. 시도하지 않은 것을 붙들고 있을 이유가 없다.
        if batch:
            release_queue_rows([r["id"] for r in batch])
        try:
            driver.quit()
        except Exception:
            pass
        _release_lock()
        elapsed = time_module.time() - start_ts
        # 이동 횟수와 재사용 횟수를 함께 남긴다 - batching 이 실제로 동작하는지는
        # 로그로 확인할 수 있어야 한다(Sprint 235 가 이 값을 로그에서 역산해야 했다).
        logger.info("===== PDF 수집 Worker 종료 - 시도: %d건, 성공: %d건, "
                    "상세페이지 이동: %d회, 재사용: %d회, 소요시간: %.1f초 =====",
                     processed, succeeded, page.get("navigations", 0),
                     page.get("reused", 0), elapsed)

    outcome = DocWorkerOutcome(processed=processed, succeeded=succeeded)
    reason = outcome.failure_reason()
    if reason:
        logger.error("===== PDF 수집 실패: %s =====", reason)
    return outcome.exit_code()


if __name__ == "__main__":
    sys.exit(main())
