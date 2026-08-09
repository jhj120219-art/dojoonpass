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
        with open("logs/errors.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass

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
            logger.warning("[%s] attempt %d/%d failed: %s",
                case_no, attempt, MAX_RETRY, str(e))
            log_error(case_no, "detail", e, attempt)
            if attempt < MAX_RETRY:
                time.sleep(random_delay())
            else:
                logger.error("[%s] 최대 재시도 초과. 건너뜀.", case_no)

    return None

def resume_start_idx(list_items: List[dict], resume_from: Optional[str]) -> int:
    """체크포인트(resume_from=마지막으로 완료한 case_no)를 기준으로 오늘자 목록
    (list_items)에서 이어서 시작할 인덱스를 계산한다(2026-08-10 Sprint 43 —
    crawl_court() 안에 인라인으로만 있던 재개 로직을 순수 함수로 분리해 Selenium 없이
    회귀 테스트할 수 있게 함, 동작은 그대로 유지).

    resume_from이 오늘 목록에 없으면(취하/기각/매각기일 변경 등으로 그 사건이 더 이상
    목록에 없는 경우) 0을 반환해 처음부터 다시 훑는다 — 데이터 손상은 아니고(upsert_batch가
    같은 사건을 다시 수집해도 멱등하게 갱신할 뿐) 이미 끝낸 항목을 다시 도는 비효율만
    생긴다. 이 함수는 그 fallback이 실제로 "0부터 안전하게 다시 시작"으로 동작하는지,
    정상 매칭 시 정확히 "그 다음 항목"부터 시작하는지를 검증 대상으로 삼는다.
    """
    if not resume_from:
        return 0
    for idx, it in enumerate(list_items):
        if resume_from in it["case_no"]:
            return idx + 1
    return 0


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
                logger.error("세션 오류 감지: %s. 드라이버 재시작", str(e))
                driver = restart_driver(driver)
                result = crawl_detail(driver, item_info, court)

            if result:
                all_items.append(result)

            checkpoint.save(court.code, case_no, idx + 1, total)

        checkpoint.clear(court.code)
        return all_items

    finally:
        driver.quit()
        logger.info("브라우저 종료: %s", court.name)
