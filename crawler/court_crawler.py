import os
import time
import json
import logging
from datetime import datetime
from typing import Optional, List

from config.settings import MAX_ITEMS, MAX_RETRY, random_delay, CourtInfo
from models.auction_item import AuctionItem
from storage.checkpoint import CheckpointManager
from crawler.base_crawler import (
    build_driver, restart_driver,
    go_to_list, go_to_schedule,
    wait_for_detail,
    parse_basic_info, parse_section_table,
    parse_gamjung, collect_list_items,
)

logger = logging.getLogger(__name__)

# 크롤 오류 기록 파일. **이 파일 위치 기준**이라 어느 cwd 에서 띄워도 같은 곳에 쌓인다.
# 회귀 테스트가 갈아끼우는 공개 표면이므로 이름을 바꾸지 않는다.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ERROR_LOG_PATH = os.path.join(_REPO_ROOT, "logs", "errors.jsonl")


def log_error(case_no: str, step: str, error: Exception, retry: int) -> None:
    entry = {
        "case_no": case_no,
        "step": step,
        "error": type(error).__name__,
        "message": str(error)[:300],
        "retry": retry,
        "timestamp": datetime.now().isoformat(),
    }
    try:
        # `logs/`는 .gitignore 대상이라 새 체크아웃/배포에는 없다. 아래 except가 모든 예외를
        # 삼키므로, 디렉터리가 없으면 **크롤 오류 기록이 통째로 조용히 사라진다** — 정작
        # 가장 필요한 순간에 남는 게 없다(2026-08-13 Sprint 98).
        # 저장소의 다른 진입점(`doc_worker.py:20` 등)이 쓰는 것과 같은 한 줄이다.
        # 경로는 cwd 가 아니라 **저장소 루트 기준**이다 (2026-08-21 Sprint 246).
        # 상대경로면 다른 cwd 에서 크롤했을 때 오류 기록이 엉뚱한 폴더로 흩어진다.
        #
        # ★ 모듈 변수를 **호출 시점에** 읽는다. `doc_worker.LOCK_PATH` 와 같은 규칙이다 -
        #   회귀 테스트가 `court_crawler.ERROR_LOG_PATH = <임시경로>` 로 갈아끼워
        #   운영 `logs/` 를 건드리지 않고 검증할 수 있어야 한다. 기본값을 함수 안에서
        #   계산해 버리면 그 seam 이 사라진다(예전에는 테스트가 chdir 로 우회했는데,
        #   그건 **경로가 cwd 에 의존한다는 결함 덕분에** 동작하던 방식이다).
        os.makedirs(os.path.dirname(ERROR_LOG_PATH), exist_ok=True)
        with open(ERROR_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass

class BrowserSessionLost(Exception):
    """브라우저 세션 자체가 죽었다 - **이 항목의 문제가 아니다.**

    2026-08-24 Sprint 254 신설 (BUGS #182). `crawl_detail()` 은 예외를 전부 잡아
    MAX_RETRY 만큼 재시도했기 때문에, 브라우저가 죽어도 그것이 "이 사건을 못 읽었다"로
    처리됐다. 그 결과 `crawl_court()` 이 가지고 있던 드라이버 재시작 복구가
    **한 번도 실행되지 않았다**(실측: 항목 4 x 재시도 3 = 12회 헛돌고 restart 0회).
    """


# 세션이 죽었을 때 Selenium 이 쓰는 이름/문구. 클래스 이름과 메시지를 **둘 다** 본다 -
# 드라이버 버전에 따라 같은 사건이 다른 예외로 오기 때문이다.
#
# ★ `WebDriverException` 을 통째로 잡으면 안 된다. `NoSuchElementException` /
#   `TimeoutException` 이 그 자식이라, 평범한 "이 화면에 그 요소가 없다"까지
#   세션 사망으로 오판해 멀쩡한 브라우저를 매번 재시작하게 된다.
_SESSION_DEAD_TYPES = (
    "InvalidSessionIdException", "NoSuchWindowException", "NoSuchDriverException",
    "SessionNotCreatedException", "MaxRetryError",
)
_SESSION_DEAD_MESSAGES = (
    "invalid session id", "session deleted", "session not created",
    "chrome not reachable", "disconnected: not connected to devtools",
    "target window already closed", "no such window", "browser has closed",
    "unable to connect to renderer", "failed to establish a new connection",
    "connection refused",
)


def is_session_dead(exc: Exception) -> bool:
    """이 예외가 '브라우저가 죽었다' 인가. 회귀가 참조하는 공개 표면이다.

    두 갈래를 본다. **둘 다 필요하다** ― 어느 한쪽만으로는 실제 사례를 놓친다:

      이름   `InvalidSessionIdException` 처럼 클래스 자체가 세션 사망인 경우.
             드라이버 버전/로케일에 따라 메시지는 얼마든지 달라지므로 문구만으로는
             놓친다.
      문구   드라이버가 같은 사건을 밋밋한 `WebDriverException` 으로 던지는 경우.
             `chrome not reachable` / `disconnected: not connected to DevTools` 가
             실제로 그렇게 온다. 클래스만 보면 놓친다.

    ★ `isinstance` 로 selenium 클래스를 직접 대조하는 판을 한 번 넣었다가 **걷어냈다**
      (2026-08-24 Sprint 254). 이름 대조와 결과가 갈리는 경우는 "그 클래스의 하위
      클래스" 뿐인데 selenium 4.47 에는 그런 클래스가 하나도 없다(실측). 즉 어떤
      입력으로도 다른 결과를 내지 못하는 분기였고, mutation 으로 지워도 아무 검사가
      죽지 않았다. 검증할 수 없는 코드를 남기지 않는다.
      selenium 이 그런 하위 클래스를 만드는 날 다시 볼 것 ― 그때는 그것을 재현하는
      검사부터 쓸 수 있다.
    """
    if type(exc).__name__ in _SESSION_DEAD_TYPES:
        return True
    text = str(exc).lower()
    return any(marker in text for marker in _SESSION_DEAD_MESSAGES)


def crawl_detail(driver, item_info: dict, court: CourtInfo) -> Optional[AuctionItem]:
    case_no = item_info["case_no"]
    dtl_idx = item_info["dtl_idx"]

    for attempt in range(1, MAX_RETRY + 1):
        try:
            if not go_to_list(driver, court):
                raise Exception("go_to_list failed")

            driver.execute_script("moveDtlPage(" + str(dtl_idx) + ")")
            ok = wait_for_detail(driver, case_no)
            if not ok:
                raise Exception("wait_for_detail timeout")

            basic = parse_basic_info(driver)
            giljae = parse_section_table(driver, "기일내역")
            mokrok = parse_section_table(driver, "목록내역")
            gamjung = parse_gamjung(driver)
            inguen = parse_section_table(driver, "인근매각물건사례")

            return AuctionItem(
                case_no=case_no,
                item_no=basic.get("물건번호", item_info.get("obj_no", "-")),
                address=item_info["addr"],
                property_type=basic.get("물건종류", "-"),
                appraisal_price=basic.get("감정평가액", item_info.get("appraisal", "-")),
                minimum_bid_price=basic.get("최저매각가격 (매수신청보증금)", "-"),
                auction_date=item_info["date"],
                status=item_info["status"],
                court_code=court.code,
                court_name=court.name,
                basic_info=basic,
                schedule=giljae,
                property_list=mokrok,
                appraisal_summary=gamjung,
                nearby_cases=inguen,
                crawl_date=datetime.today().strftime("%Y-%m-%d"),
            )

        except Exception as e:
            # ★ 브라우저가 죽은 것은 **이 항목의 실패가 아니다** (Sprint 254, BUGS #182).
            #   여기서 삼키고 재시도하면 (1) 남은 재시도 2회가 확실히 헛돌고
            #   (2) 바깥의 드라이버 재시작 복구가 영영 발동하지 않으며
            #   (3) 그 법원이 빈 목록을 돌려줘 `run_courts()` 가 그것을
            #       "기일 없어 스킵" 으로 기록한다 - **사실이 아닌 요약**이다.
            #   doc_worker 가 Sprint 137/232 에서 정한 것과 같은 규칙이다.
            if is_session_dead(e):
                logger.error("[%s] 브라우저 세션이 죽었다(%s) - 이 항목의 문제가 아니므로 "
                             "재시도하지 않고 올린다", case_no, type(e).__name__)
                log_error(case_no, "session", e, attempt)
                raise BrowserSessionLost(str(e)) from e
            logger.warning("[%s] attempt %d/%d failed: %s",
                case_no, attempt, MAX_RETRY, str(e))
            log_error(case_no, "detail", e, attempt)
            if attempt < MAX_RETRY:
                time.sleep(random_delay())
            else:
                logger.error("[%s] 최대 재시도 초과. 건너뜀.", case_no)

    return None

# 순수 계산 로직이라 selenium 없이도 쓸 수 있어야 해서 crawler/resume.py로 분리했다
# (이 모듈은 base_crawler를 통해 selenium을 끌어온다 - Sprint 47). 재노출로 하위 호환 유지.
from crawler.resume import resume_start_idx  # noqa: F401


def crawl_court(court: CourtInfo) -> List[AuctionItem]:
    logger.info("크롤링 시작: %s", court.name)
    checkpoint = CheckpointManager()
    cp = checkpoint.get(court.code)
    resume_from = cp["last_case_no"] if cp else None
    if resume_from:
        logger.info("체크포인트 감지: %s 이후부터 재시작", resume_from)

    driver = build_driver()
    try:
        # 스킵 로직: 기일 없으면 즉시 반환
        ok, has_schedule = go_to_schedule(driver, court)
        if not ok:
            logger.error("페이지 접속 실패: %s", court.name)
            return []
        if not has_schedule:
            logger.info("[스킵] 기일 없음: %s", court.name)
            return []

        list_items = collect_list_items(driver, MAX_ITEMS)
        logger.info("목록 수집 완료: %d건 [%s]", len(list_items), court.name)

        if not list_items:
            logger.info("[스킵] 수집 항목 없음: %s", court.name)
            return []

        # 체크포인트 재시작
        start_idx = resume_start_idx(list_items, resume_from)
        if resume_from:
            logger.info("체크포인트 위치: %d번째부터 재시작", start_idx + 1)

        all_items: List[AuctionItem] = []
        total = len(list_items)

        for idx in range(start_idx, total):
            item_info = list_items[idx]
            case_no = item_info["case_no"]
            logger.info("[%d/%d] %s [%s]", idx + 1, total, case_no, court.name)

            if item_info["dtl_idx"] is None:
                logger.warning("dtl_idx 없음 건너뜀: %s", case_no)
                continue

            result = None
            try:
                result = crawl_detail(driver, item_info, court)
            except Exception as e:
                # 여기 도달하는 것은 이제 **세션 사망뿐**이다(그 외는 crawl_detail 이
                # 재시도하고 None 을 돌려준다). 한 번 재시작해 보고, 그래도 죽어 있으면
                # 예외를 그대로 올린다 - `run_courts()` 가 이 법원을 `failed` 로 센다.
                # 삼키면 빈 목록이 되고, 그것은 "기일 없음" 과 구별되지 않는다.
                logger.error("세션 오류 감지: %s. 드라이버 재시작", str(e))
                driver = restart_driver(driver)
                result = crawl_detail(driver, item_info, court)

            if result:
                all_items.append(result)

            checkpoint.save(court.code, case_no, idx + 1, total)

        checkpoint.clear(court.code)
        return all_items

    finally:
        # ★ `quit()` 이 던지면 **원래 오류가 그것으로 바뀐다** - 죽은 세션을 닫을 때
        #   실제로 일어나는 일이고, 그러면 `run_courts()` 의 로그가 엉뚱한 원인을
        #   가리킨다. 종료 실패는 종료 실패로만 남긴다.
        try:
            driver.quit()
        except Exception as quit_exc:  # noqa: BLE001 - 원인을 덮지 않는 것이 목적이다
            logger.warning("브라우저 종료 실패(%s): %s", court.name, quit_exc)
        logger.info("브라우저 종료: %s", court.name)
