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
        os.makedirs("logs", exist_ok=True)
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
