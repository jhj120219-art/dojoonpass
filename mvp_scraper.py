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

# ★ 파일 로그는 **이 파일을 직접 실행할 때만** 붙인다 (2026-08-25, docs/BUGS.md #192).
#   왜 — 예전에는 아래 basicConfig 가 **import 시점에** 루트 로거에 FileHandler 를
#   붙였다. 그런데 이 모듈을 import 하는 것은 제품 코드가 아니라 **테스트뿐**이다
#   (2026-08-25 전수 확인: 제품 모듈의 import 0건). 루트 로거에 붙으므로 그 프로세스
#   안의 **모든** 로그(crawler/* 포함)가 운영 로그 파일로 흘러들었다. 실측(2026-08-25):
#
#       logs/scraper.log      36,420줄 중 08-24~25 자 2,346줄이 QA 산출물
#                             (가짜 법원 'QA1'/'QA2', "전 법원(2곳) 수집 실패" 등)
#       logs/doc_collect.log   4,136줄 중 1,651줄(40%)이 QA 산출물('QA법원')
#
#   마지막 실제 크롤은 **2026-08-12** 다. 즉 이 로그만 보면 "오늘 크롤이 돌았고 전 법원이
#   실패했다"로 읽힌다 — 이 저장소가 9일간 크롤 중단을 몰랐던 그 함정(거짓 증거)와
#   같은 계열이다. BUGS #186 이 DB 축에서 고친 것을 파일 축에서 다시 고친다.
#
#   **운영 경로는 전혀 바뀌지 않는다** — `.bat` 은 이 파일을 `python <파일>` 로 부르므로
#   아래 `__main__` 분기에서 같은 FileHandler 가 그대로 붙는다. 나머지 진입점 둘
#   (`doc_worker.py` / `refresh_priority.py`)은 애초에 StreamHandler 하나뿐이라,
#   이 수정으로 네 진입점의 import 시점 동작이 같아진다.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)


SCRAPER_LOG_PATH = os.path.join(_HERE, "logs", "scraper.log")


def attach_file_log():
    """운영 파일 로그를 루트 로거에 붙인다. `__main__` 에서만 부른다.

    두 번 불러도 핸들러가 겹치지 않는다(같은 경로가 이미 붙어 있으면 그대로 둔다) —
    테스트가 이 함수를 직접 검증할 수 있어야 하기 때문이다(부수효과를 쓰지 않는다).
    """
    root = logging.getLogger()
    target = os.path.abspath(SCRAPER_LOG_PATH)
    for h in root.handlers:
        if isinstance(h, logging.FileHandler) and os.path.abspath(h.baseFilename) == target:
            return h
    handler = logging.FileHandler(SCRAPER_LOG_PATH, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    root.addHandler(handler)
    return handler

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

# CSV 백업이 떨어질 폴더. 기본값은 **이 파일이 있는 곳**(저장소 루트)이고 cwd 가 아니다
# (Sprint 252, 아래 `save_csv_backup()` 참고).
#
# ★ 모듈 변수로 둔 이유는 성능도 설정도 아니라 **회귀 테스트가 운영 산출물을 파괴하지
#   않게 하기 위해서다** (2026-08-27, BUGS #250).
#
#   `test_crawl_orchestration.py` 는 "CSV 가 cwd 를 따라가지 않는가"를 정적 검사로는
#   잡을 수 없어(인자가 pandas `to_csv` 의 조립된 변수다) **다른 cwd 에서 실제로**
#   `save_csv_backup()` 을 돌린다. 그런데 파일명이 `auction_<오늘>.csv` 로 고정이라
#   그 실행이 **그날 진짜 백업을 QA 데이터로 덮어썼고**, 검사가 끝나며 지웠다.
#   실측(2026-08-27): 세션 시작 시 있던 `auction_20260827.csv` 가 검사 1회 실행 뒤
#   사라졌다. CSV 는 `.gitignore` 대상이라 **git 도 알려 주지 않는다** — 조용한 소실이다.
#
#   `storage.database.DB_PATH` 를 스크래치로 갈아끼우는 것과 **정확히 같은 방식**이다.
#   그 격리를 이 산출물만 갖고 있지 않았다.
CSV_BACKUP_DIR = _HERE
# 전체 크롤 실측 3.1시간(Sprint 190)보다 넉넉하게. 이 시간이 지난 락은 죽은 실행으로 보고
# 회수한다 — 비정상 종료가 다음 날 실행을 영원히 막으면 안 된다.
LOCK_STALE_HOURS = 6


def _lock() -> RunLock:
    """지금의 `LOCK_PATH`/`LOCK_STALE_HOURS` 로 락 객체를 만든다(스냅숏으로 굳히지 않는다)."""
    return RunLock(LOCK_PATH, LOCK_STALE_HOURS, label="mvp_scraper")


def save_csv_backup(rows: list) -> str:
    """수집 결과 CSV 백업. 경로는 **이 파일 기준**이다.

    ★ 2026-08-24 Sprint 252 수정 — 예전에는 `filename` 이 상대경로("auction_YYYYMMDD.csv")라
      **현재 작업 디렉터리**에 떨어졌다. Sprint 245/246 이 같은 계열의 cwd 의존을 네 군데
      고쳤는데(`api/auth.py` 의 load_dotenv, `storage/database.py` 의 DB_PATH,
      `doc_worker.py` 의 LOCK_PATH, 운영 도구 8개) **이 한 곳만 남아 있었다.**
      이 모듈 자신도 로그/락은 이미 `_HERE` 기준인데 CSV 만 아니었다.

      ★ 2026-08-27 정정 (BUGS #263) — 위 *"이 한 곳만 남아 있었다"* 는 **사실이 아니었다.**
        그때의 감사가 (A) 모듈 최상위 상수와 (B) 경로 호출의 리터럴만 봤기 때문에,
        **함수 기본 인자값**에 숨은 세 곳을 통째로 놓치고 있었다:

            storage/checkpoint.py    CheckpointManager(path="logs/checkpoint.json")
            validator/validation_engine.py  ValidationEngine(log_path="logs/validation.jsonl")
            revalidate.py            ValidationEngine(log_path="logs/revalidation.jsonl")

        그중 체크포인트는 **재개를 조용히 무력화**하는 자리였다. 감사에 갈래 C/D 를
        추가해 셋 다 잡아 고쳤다. 목록을 세는 주석은 그 목록을 만든 도구만큼만 정확하다.

      `.bat` 은 `cd /d %~dp0` 로 보호되므로 예약 실행에서는 드러나지 않는다. 드러나는 것은
      수동 실행/서비스 등록처럼 cwd 가 다른 경우이고, 그때 백업이 엉뚱한 폴더에 흩어진다 —
      "백업이 있다"고 믿는데 저장소에는 없는 상태가 된다.

      `test_schema_hygiene.py` 의 cwd 감사가 이것을 못 잡은 이유도 남긴다: 그 검사는
      알려진 경로 호출(open/connect/makedirs...)에 **문자열 리터럴**이 들어가는 모양을
      본다. 여기는 pandas 의 `to_csv` 이고 인자도 조립된 변수라 두 조건 다 비껴간다.
      그래서 정적 검사 대신 **다른 cwd 에서 실제로 돌려 보는** 회귀를 따로 뒀다
      (`test_crawl_orchestration.py`).
      ★ 2026-08-27 BUGS #250 — 목적지 폴더를 `CSV_BACKUP_DIR` 로 뺐다(기본값은 그대로
        `_HERE`). 경로 규칙은 **아무것도 바뀌지 않는다.** 바뀐 것은 회귀 테스트가
        운영 백업을 덮어쓰지 않고도 이 규칙을 검증할 수 있다는 것뿐이다.
    """
    df = pd.DataFrame(rows)
    filename = "auction_" + datetime.today().strftime("%Y%m%d") + ".csv"
    path = os.path.join(CSV_BACKUP_DIR or _HERE, filename)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    logger.info("CSV 백업 저장: %s (%d건)", path, len(rows))
    return path

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
    #
    # ★ 떨어져 나간 건수를 **반드시 남긴다** (2026-08-27, docs/BUGS.md #261).
    #
    #   `normalize_batch()` 는 기형 행 하나가 배치를 죽이지 않도록 그 행만 버린다
    #   (Sprint 78 — 옳은 격리다). 문제는 **버렸다는 사실이 여기서 사라졌다**는 것이다.
    #   예전 이 자리는 `"정규화 완료: %d건"` 만 찍었다. 2,608건을 받아 2,600건을 찍어도
    #   그 줄만 봐서는 8건이 없어진 것을 알 수 없다 - 앞줄과 손으로 빼 봐야 안다.
    #
    #   전부 떨어지면 `persisted == 0` 으로 잡히지만(#47), **부분 손실은 어디에서도
    #   잡히지 않았다.** 크롤은 성공, 저장도 성공, 종료코드 0 - 그런데 법원에서 받아 온
    #   자료 일부가 DB 에 없다.
    before_normalize = len(all_items)
    rows = normalize_batch(all_items)
    outcome.normalize_dropped = before_normalize - len(rows)
    if outcome.normalize_dropped:
        logger.error(
            "정규화에서 %d건이 떨어졌다 (%d -> %d건). 크롤은 받아 왔는데 DB 에 닿지 "
            "못한 건수다 - 위쪽 'normalize_item failed' 경고에 사건번호가 있다",
            outcome.normalize_dropped, before_normalize, len(rows))
    logger.info("정규화 완료: %d건 (입력 %d건, 탈락 %d건)",
                len(rows), before_normalize, outcome.normalize_dropped)

    # 3. SQLite UPSERT
    result = upsert_batch(rows)
    outcome.inserted = result["inserted"]
    outcome.updated = result["updated"]
    # ★ 반드시 함께 넘긴다 — 빠뜨리면 `persisted` 가 실제보다 작아져,
    #   법원 자료가 그대로인 정상적인 날에 크롤이 "DB 저장 0건"으로 실패한다
    #   (docs/BUGS.md #249, `models/crawl_outcome.py:persisted` 주석).
    outcome.unchanged = result["unchanged"]
    outcome.upsert_failed = result["failed"]
    print("")
    print("[DB 저장 결과]")
    print("  신규    :", result["inserted"], "건")
    print("  갱신    :", result["updated"], "건")
    print("  변화없음:", result["unchanged"], "건")
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
        #
        # ★ 어휘를 여기서 복제하지 않는다 (2026-08-27, docs/BUGS.md #261).
        #   "치명적이지는 않지만 눈에 띄어야 하는 것"의 목록은 `CrawlOutcome.warnings()`
        #   하나가 들고 있다. 예전에는 법원 실패만 여기 인라인으로 적혀 있어서,
        #   같은 성격의 **정규화 탈락**이 생겼을 때 붙일 자리가 없었다.
        for warn in outcome.warnings():
            logger.warning("%s", warn)

        reason = outcome.failure_reason()
        if reason:
            logger.error("===== 사건 수집 실패: %s =====", reason)
        else:
            logger.info("===== 사건 수집 완료: 저장 %d건(신규 %d/갱신 %d/변화없음 %d)"
                        "%s =====",
                        outcome.persisted, outcome.inserted, outcome.updated,
                        outcome.unchanged,
                        (", 정규화 탈락 %d건" % outcome.normalize_dropped)
                        if outcome.normalize_dropped else "")
        return outcome.exit_code()
    finally:
        lock.release()

if __name__ == "__main__":
    attach_file_log()   # 운영 파일 로그는 직접 실행할 때만 (docs/BUGS.md #192)
    sys.exit(main())
