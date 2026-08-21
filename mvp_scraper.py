import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import logging
import pandas as pd
from datetime import datetime
from typing import List

from config.settings import CourtInfo
from config.courts import ALL_COURTS
from models.auction_item import AuctionItem
from models.crawl_outcome import CrawlOutcome
from crawler.court_crawler import crawl_court
from validator.validation_engine import ValidationEngine
from normalizer.normalizer import normalize_batch
from storage.database import init_db, upsert_batch, get_stats, enqueue_documents
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
        logging.FileHandler(os.path.join(_HERE, "logs", "scraper.log"), encoding="utf-8"),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)

# 동시 실행 방지 (2026-08-18 Sprint 194).
# ---------------------------------------------------------------------------
# `doc_worker.py` 는 2026-08-16 Sprint 142 부터 락을 갖고 있는데 **여기에는 없었다.**
# 이 배치가 공유하는 변경 가능한 자원이 둘 있다:
#
#   logs/checkpoint.json   `CheckpointManager.save()` 가 파일 전체를 읽어 고쳐 쓴다.
#                          두 실행이 겹치면 서로의 진행 상황을 덮어써, 이어받기가
#                          엉뚱한 지점부터 시작하거나 통째로 사라진다.
#   법원 서버              같은 사건을 두 배로 긁는다. 전체 크롤은 실측 약 3.1시간
#                          (1곳 186초 x 60곳, Sprint 190)이라 겹칠 창이 넓다.
#
# 예약 작업끼리는 기본 MultipleInstances=IgnoreNew 로 안 겹치지만, **운영자의 수동
# 실행이 스케줄 실행과 겹치는 경우**는 막지 못한다 — doc_worker 가 락을 둔 것과 같은 이유다.
LOCK_PATH = os.path.join(_HERE, "logs", "mvp_scraper.lock")
# 전체 크롤 실측 3.1시간(Sprint 190)보다 넉넉하게. 이 시간이 지난 락은 죽은 실행으로 보고
# 회수한다 — 비정상 종료가 다음 날 실행을 영원히 막으면 안 된다.
LOCK_STALE_HOURS = 6


def _lock() -> RunLock:
    """지금의 `LOCK_PATH`/`LOCK_STALE_HOURS` 로 락 객체를 만든다(스냅숏으로 굳히지 않는다)."""
    return RunLock(LOCK_PATH, LOCK_STALE_HOURS, label="mvp_scraper")


def save_csv_backup(rows: list) -> str:
    df = pd.DataFrame(rows)
    filename = "auction_" + datetime.today().strftime("%Y%m%d") + ".csv"
    df.to_csv(filename, index=False, encoding="utf-8-sig")
    logger.info("CSV 백업 저장: %s (%d건)", filename, len(rows))
    return filename

def print_validation_summary(engine: ValidationEngine, items: List[AuctionItem]) -> None:
    summary = engine.summary(items)
    print("")
    print("=" * 50)
    print("[검증 결과]")
    print("  전체  :", summary["total"], "건")
    print("  PASS  :", summary["pass"], "건")
    print("  FAIL  :", summary["fail"], "건")
    print("  정확도:", str(summary["accuracy"]) + "%")
    print("=" * 50)
    for item in items:
        if item.validation_status == "FAIL":
            print("  FAIL | " + item.case_no + " | " + " / ".join(item.validation_reasons))

def run_courts(courts: List[CourtInfo], outcome: CrawlOutcome = None) -> list:
    """
    사건 목록/상세 수집 전용. 문서(PDF) 관련 코드는 전혀 포함하지 않는다.
    (PDF 수집은 doc_worker.py가 02:00에 별도로 처리한다)

    반환값: normalize_batch를 거친 rows (document_queue 적재에 사용)
    `outcome`을 넘기면 실행 결과가 그 객체에 채워진다(종료 코드 판정용).
    """
    if outcome is None:
        outcome = CrawlOutcome()
    outcome.courts = len(courts)
    all_items: List[AuctionItem] = []
    skipped = []
    failed = []

    for court in courts:
        logger.info("===== [%s] 수집 시작 =====", court.name)
        try:
            items = crawl_court(court)
            if not items:
                skipped.append(court.name)
                continue
            all_items.extend(items)
            logger.info("===== [%s] 완료: %d건 =====", court.name, len(items))
        except Exception as e:
            logger.error("===== [%s] 오류: %s =====", court.name, str(e))
            failed.append(court.name)

    print("")
    print("=" * 50)
    print("[수집 완료 요약]")
    print("  총 수집 법원:", len(courts), "개")
    print("  기일 없어 스킵:", len(skipped), "개 ->", skipped)
    print("  오류 발생:", len(failed), "개 ->", failed)
    print("  총 수집 건수:", len(all_items), "건")
    print("=" * 50)

    outcome.skipped = skipped
    outcome.failed = failed
    outcome.collected = len(all_items)

    if not all_items:
        logger.info("수집된 데이터 없음")
        return []

    # 1. 검증
    engine = ValidationEngine(log_path=os.path.join(_HERE, "logs", "validation.jsonl"))
    all_items = engine.validate_batch(all_items)
    print_validation_summary(engine, all_items)

    # 2. 정규화
    rows = normalize_batch(all_items)
    logger.info("정규화 완료: %d건", len(rows))

    # 3. SQLite UPSERT
    result = upsert_batch(rows)
    outcome.inserted = result["inserted"]
    outcome.updated = result["updated"]
    outcome.upsert_failed = result["failed"]
    print("")
    print("[DB 저장 결과]")
    print("  신규    :", result["inserted"], "건")
    print("  업데이트:", result["updated"], "건")
    print("  실패    :", result["failed"], "건")

    # 4. DB 통계
    stats = get_stats()
    print("")
    print("[DB 누적 현황]")
    print("  총 누적 건수:", stats["total"], "건")
    print("  시도별 현황:")
    for s in stats["by_sido"]:
        print("    " + (s["sido"] or "미상") + ": " + str(s["cnt"]) + "건")

    # 5. CSV 백업
    save_csv_backup(rows)

    return rows

def main() -> int:
    """종료 코드를 돌려준다. 0=성공, 1=치명적 실패.

    2026-08-11 Sprint 55 (BUGS #47): 예전에는 `-> None`이었고 호출부도 종료 코드를
    쓰지 않았다. 그래서 `run_daily.bat`의 `if errorlevel 1` 검사가 **구조적으로 발동할 수
    없었다** — 59/60 법원이 실패하고 저장이 0건이어도 배치는 성공으로 끝났다(2026-08-02 실측).
    """
    logger.info("===== 법원경매 사건 수집 시작 =====")

    # 브라우저를 띄우기 전에 먼저 확인한다 — 어차피 실행하지 못할 거라면 비용을 쓰지 않는다
    # (doc_worker 와 같은 순서). 얻지 못한 것은 **실패가 아니다** — 다른 실행이 이미 그
    # 일을 하고 있으므로 종료 코드 0 으로 조용히 끝낸다.
    lock = _lock()
    if not lock.acquire():
        logger.info("다른 mvp_scraper.py 실행이 이미 진행 중으로 보임 - 이번 실행은 건너뜀"
                    "(체크포인트 충돌과 중복 크롤 방지, %s)", LOCK_PATH)
        return 0

    try:
        init_db()
        outcome = CrawlOutcome()
        rows = run_courts(ALL_COURTS, outcome)

        # 06:00 루프는 여기서 끝. PDF 다운로드는 하지 않고,
        # "아직 문서 없는 사건" 목록만 document_queue에 적재한다.
        if rows:
            enqueue_documents(rows)
        else:
            # 예전에는 이 분기가 아무 말 없이 지나갔다. 적재를 건너뛴 사실이 로그에 남아야
            # document_queue가 늘지 않은 이유를 나중에 추적할 수 있다.
            logger.warning("수집 결과가 비어 document_queue 적재를 건너뜁니다")

        # 부분 실패는 성공으로 두되 **반드시 눈에 띄게** 남긴다. 이 줄이 없으면
        # "일부 법원이 계속 실패 중"인 상태가 조용히 굳어진다.
        if outcome.failed:
            logger.warning("일부 법원 수집 실패: %d/%d곳 -> %s",
                           len(outcome.failed), outcome.courts, outcome.failed)

        reason = outcome.failure_reason()
        if reason:
            logger.error("===== 사건 수집 실패: %s =====", reason)
        else:
            logger.info("===== 사건 수집 완료: 저장 %d건(신규 %d/갱신 %d) =====",
                        outcome.persisted, outcome.inserted, outcome.updated)
        return outcome.exit_code()
    finally:
        lock.release()

if __name__ == "__main__":
    sys.exit(main())
