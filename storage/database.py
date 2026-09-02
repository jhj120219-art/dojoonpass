import os
import sqlite3
import logging
from datetime import datetime
from typing import List, Dict, Optional

# LIKE 와일드카드 이스케이프의 **정본은 한 곳**이다(api/constants.py).
# `api.constants` 는 표준 `enum` 만 의존하는 잎 모듈이라 storage -> api 순환이 생기지
# 않는다. 같은 규칙을 여기 다시 적으면 한쪽만 고쳐지는 날이 온다.
from api.constants import escape_like

logger = logging.getLogger(__name__)

# `auction_image.storage_path` 는 프로젝트 루트 기준 상대경로다
# (`to_relative_storage_path()` 참고). 절대경로로 되돌릴 때 쓴다 —
# `api/v1/images.py:resolve_stored_path()` 와 같은 규칙이어야 한다.
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)

# ★ DB 경로는 **현재 작업 디렉터리가 아니라 이 파일 기준**이다 (2026-08-21 Sprint 246).
#
#   예전에는 `DB_PATH = "auction.db"` 였다. 상대경로라 **cwd 기준**으로 열린다.
#   그런데 `sqlite3.connect()` 는 파일이 없으면 **조용히 새로 만든다.** 그래서 저장소
#   루트가 아닌 곳에서 서버를 띄우면:
#
#       그 폴더에 0바이트 `auction.db` 가 생기고
#       모든 조회가 `no such table: auction_item` 으로 실패한다
#
#   실측(2026-08-21, 같은 코드를 cwd 만 바꿔 임포트):
#       cwd = 저장소 루트  -> auction_item 1,876행
#       cwd = 다른 폴더    -> 그 폴더에 0바이트 auction.db 생성 / no such table
#
#   같은 세션에 고친 `.env` cwd 의존(Sprint 245)과 **같은 계열**이고 더 나쁘다 —
#   환경변수는 비면 500 으로 시끄럽게 실패하지만, 이쪽은 **빈 DB 를 만들어** 놓고
#   "데이터가 없다"처럼 보이게 한다. 운영자가 크롤이 안 돈 줄로 오해한다.
#
#   `audit_schedule_health.py` 는 이미 `getattr(dbmod, "DB_PATH", os.path.join(ROOT, "auction.db"))`
#   로 루트 기준 폴백을 두고 있었다 — 상대경로 기본값을 믿을 수 없다는 것을 그 파일은
#   알고 있었다는 뜻이다. 기본값 자체를 고쳐 그 우회를 불필요하게 만든다.
#
#   ★ 모듈 변수라는 점은 그대로다. 테스트/도구가 `db.DB_PATH = ...` 로 갈아끼우는
#     기존 방식은 **아무것도 바뀌지 않는다**(실제로 여러 회귀가 그렇게 쓴다).
DB_PATH = os.path.join(PROJECT_ROOT, "auction.db")

MAX_DOC_RETRY = 3
RETRY_INTERVAL_MINUTES = 30

# claim 경쟁에서 졌을 때 **다른 행으로** 다시 시도하는 횟수 상한.
# `claim_next_queue_item()` 참고 — 진 것과 "큐가 비었다"는 완전히 다른 사건인데
# 예전에는 둘 다 None 이었고, 호출부는 후자로 읽어 실행을 끝냈다(BUGS #130).
# 상한을 두는 이유는 경쟁자가 계속 이기는 상황에서 여기 영원히 머물지 않기 위해서다.
CLAIM_RACE_MAX_ATTEMPTS = 5

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS auction (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    court_code TEXT,
    court_name TEXT,
    case_no TEXT NOT NULL,
    item_no TEXT,
    property_type TEXT,
    sido TEXT,
    sigungu TEXT,
    dong TEXT,
    lot_number TEXT,
    full_address TEXT,
    appraisal_price INTEGER DEFAULT 0,
    minimum_bid_price INTEGER DEFAULT 0,
    auction_date TEXT,
    status TEXT,
    validation_status TEXT,
    validation_reasons TEXT,
    crawl_date TEXT,
    has_spec_pdf INTEGER DEFAULT 0,
    has_status_doc INTEGER DEFAULT 0,
    has_appraisal_pdf INTEGER DEFAULT 0,
    created_at TEXT,
    updated_at TEXT,
    -- 법원마다 사건번호를 독립 채번하므로 식별키에 court_code가 반드시 있어야 한다.
    -- 예전에는 UNIQUE(case_no, item_no)라 서로 다른 법원의 같은 사건번호+물건번호가
    -- 한 행으로 취급되어 앞선 법원의 물건이 소실됐다(docs/BUGS.md #18,
    -- 기존 DB는 storage/migrations/012_auction_court_code_unique.sql로 이관 완료).
    -- fresh clone에서도 같은 제약이 만들어지도록 여기도 함께 맞춘다.
    UNIQUE(court_code, case_no, item_no)
);
"""

CREATE_INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_case_no ON auction(case_no);",
    "CREATE INDEX IF NOT EXISTS idx_auction_date ON auction(auction_date);",
    "CREATE INDEX IF NOT EXISTS idx_sido ON auction(sido);",
    "CREATE INDEX IF NOT EXISTS idx_court_name ON auction(court_name);",
    "CREATE INDEX IF NOT EXISTS idx_validation ON auction(validation_status);",
]

CREATE_QUEUE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS document_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    court_code TEXT NOT NULL,
    case_no TEXT NOT NULL,
    item_no TEXT NOT NULL DEFAULT '1',
    doc_type TEXT NOT NULL,
    priority INTEGER DEFAULT 3,
    auction_date TEXT,
    status TEXT DEFAULT 'pending',
    retry_count INTEGER DEFAULT 0,
    last_attempt_at TEXT,
    enqueued_at TEXT,
    UNIQUE(court_code, case_no, item_no, doc_type)
);
"""

CREATE_QUEUE_INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_queue_status ON document_queue(status);",
    "CREATE INDEX IF NOT EXISTS idx_queue_priority ON document_queue(priority, auction_date);",
]

CREATE_VERSION_LOG_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS document_version_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    court_code TEXT,
    case_no TEXT,
    item_no TEXT,
    doc_type TEXT,
    previous_hash TEXT,
    new_hash TEXT,
    file_version TEXT,
    updated_at TEXT
);
"""


def snapshot_live_db(dest_path: str) -> str:
    """운영 DB 를 `dest_path` 에 **일관된 스냅샷**으로 복제하고 그 경로를 돌려준다.

    ## 왜 `shutil.copy2()` 로는 안 되는가 (2026-08-26 실측으로 드러났다)

    SQLite 파일을 OS 파일 복사로 뜨면 **다른 프로세스가 쓰는 중일 때 찢어진 사본**이
    나올 수 있다. 페이지 일부만 반영된 상태, 저널이 안 맞는 상태가 그대로 복사된다.

    지금까지는 이 저장소에서 그럴 일이 거의 없었다 — DocWorker 가 스케줄러에 등록돼
    있지 않아 **운영 중 DB 에 쓰는 프로세스가 사실상 없었기** 때문이다.
    2026-08-26 에 `DojoonPass-DocWorker`(02:00~04:00) 를 등록하면서 그 전제가 깨졌다.

    실제로 그날 워커를 돌리면서 스위트를 같이 돌렸더니 **두 검사가 붉어졌다**:

        test_crawl_orchestration.py   (shutil.copy2 로 실 DB 사본을 뜬다)
        test_worker_batching.py

    둘 다 **단독으로는 통과한다.** 제품 결함이 아니라 사본이 깨진 것이다.
    앞으로는 매일 밤 02:00~04:00 에 같은 조건이 만들어진다 — 그 시간대에 스위트를
    돌리면 이유 없이 붉어진다. 그러면 사람이 검사를 믿지 않게 된다.

    ## 무엇이 다른가

    SQLite 의 **온라인 백업 API**(`Connection.backup()`)를 쓴다. 쓰기 중인 DB 에서도
    **트랜잭션 일관성이 보장된 스냅샷**을 만든다(엔진이 페이지 단위로 잠금을 관리한다).

    원본은 **읽기 전용(`mode=ro`)** 으로 연다 — 스냅샷을 뜨다가 실수로 운영 DB 를
    건드리는 일이 구조적으로 불가능하게 한다.

    ## 쓰는 곳

    실 DB 사본이 필요한 **모든 검사/감사 도구**가 이 함수를 쓴다. 규칙을 여기 한 곳에만
    둔다 — 같은 복사 코드가 11곳에 흩어져 있었고, 그중 하나만 고치면 나머지가 조용히
    옛 방식으로 남는다(이 저장소가 "규칙이 두 벌"에서 반복해 겪은 사고, BUGS #204).
    """
    src_uri = "file:%s?mode=ro" % str(DB_PATH).replace("\\", "/")
    src = sqlite3.connect(src_uri, uri=True)
    try:
        dest = sqlite3.connect(dest_path)
        try:
            src.backup(dest)
        finally:
            dest.close()
    finally:
        src.close()
    return dest_path


def get_connection(enforce_foreign_keys: bool = True) -> sqlite3.Connection:
    """DB 커넥션. 기본적으로 **외래키 제약을 런타임에 강제**한다(2026-08-07 CTO 승인 1번).

    SQLite는 `REFERENCES`를 선언해도 커넥션마다 `PRAGMA foreign_keys=ON`을 켜지 않으면
    **아무 검사도 하지 않는다**(기본값 OFF, 하위호환 때문). 이 저장소는 15개 FK를 선언해
    두고도 전부 무시되고 있었다 — 존재하지 않는 item_id로 favorite를 넣어도 DB가 막지
    않는 상태였다(코드 레벨 검사에만 의존).

    `PRAGMA foreign_keys`는 **트랜잭션 밖에서만** 적용되므로 커넥션 직후에 실행한다.

    `enforce_foreign_keys=False`는 **테이블 재작성 마이그레이션 전용**이다.
    `DROP TABLE` → `RENAME` 패턴은 중간 단계에서 자식 행이 잠시 고아가 되므로,
    FK를 켠 채 실행하면 마이그레이션 자체가 실패한다
    (`storage/migrations/run_migrations.py` 참고).
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = %s" % ("ON" if enforce_foreign_keys else "OFF"))
    return conn


def init_db() -> None:
    conn = get_connection()
    try:
        conn.execute(CREATE_TABLE_SQL)
        conn.execute(CREATE_QUEUE_TABLE_SQL)
        conn.execute(CREATE_VERSION_LOG_TABLE_SQL)
        for idx_sql in CREATE_INDEX_SQL:
            conn.execute(idx_sql)
        for idx_sql in CREATE_QUEUE_INDEX_SQL:
            conn.execute(idx_sql)

        # 기존 auction.db(과거 실행분)에는 has_*_pdf 칼럼이 없을 수 있으므로
        # 존재하지 않는 경우에만 안전하게 추가한다.
        existing_cols = [r[1] for r in conn.execute("PRAGMA table_info(auction)").fetchall()]

        # Step 9에서 has_status_pdf -> has_status_doc으로 개명 확정
        # (현황조사서는 실제로 PDF가 아니라 json+html이므로).
        # 과거 테스트에서 이미 has_status_pdf 칼럼이 생성돼 있었다면 데이터 보존을 위해
        # RENAME으로 처리하고, 둘 다 없는 완전 신규 DB라면 has_status_doc을 바로 추가한다.
        if "has_status_pdf" in existing_cols and "has_status_doc" not in existing_cols:
            conn.execute("ALTER TABLE auction RENAME COLUMN has_status_pdf TO has_status_doc")
            existing_cols.remove("has_status_pdf")
            existing_cols.append("has_status_doc")

        for col in ("has_spec_pdf", "has_status_doc", "has_appraisal_pdf"):
            if col not in existing_cols:
                conn.execute("ALTER TABLE auction ADD COLUMN " + col + " INTEGER DEFAULT 0")

        # document_queue / document_version_log도 이미 만들어져 있었을 수 있으므로
        # item_no 칼럼이 없으면 안전하게 추가한다 (기존 테스트 데이터 보존)
        queue_cols = [r[1] for r in conn.execute("PRAGMA table_info(document_queue)").fetchall()]
        if "item_no" not in queue_cols:
            conn.execute("ALTER TABLE document_queue ADD COLUMN item_no TEXT NOT NULL DEFAULT '1'")

        vlog_cols = [r[1] for r in conn.execute("PRAGMA table_info(document_version_log)").fetchall()]
        if "item_no" not in vlog_cols:
            conn.execute("ALTER TABLE document_version_log ADD COLUMN item_no TEXT")

        conn.commit()
        logger.info("DB 초기화 완료: %s", DB_PATH)
    except Exception as e:
        logger.error("DB 초기화 실패: %s", str(e))
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# `upsert_batch()` 가 쓰는 **한 문장** (2026-08-27, docs/BUGS.md #256)
#
# 컬럼 목록을 세 번(SET / WHERE / VALUES) 손으로 적지 않는다 — 한 곳에서 만든다.
# 예전 구현은 SET 14개와 WHERE 14개를 각각 적어 두었고, 그 둘이 갈라지면
# **바뀐 값을 안 쓰는** 결함이 조용히 생긴다(정확히 그것을 막으려고
# `test_upsert_change_detection.py` 가 필드를 하나씩 따로 바꿔 본다).
#
# `IS NOT` 를 쓴다 — `<>` 는 한쪽이 NULL 이면 NULL(=거짓)이라 NULL 이 든 열의 변경을
# 놓친다. `IS NOT` 는 NULL 도 제대로 비교한다.
UPSERT_COMPARE_COLUMNS = (
    "court_name", "property_type", "sido", "sigungu", "dong", "lot_number",
    "full_address", "appraisal_price", "minimum_bid_price", "auction_date",
    "status", "validation_status", "validation_reasons", "crawl_date",
    # ★ 접수일 (BUGS #285). 사건이 접수된 날은 **한 번 정해지면 안 바뀐다** —
    #   그래서 비교 대상에 넣어도 첫 수집 때 한 번만 쓰기가 일어난다.
    #   빼면 나중에 값이 채워져도 UPDATE 가 안 나가 영영 NULL 로 남는다.
    "filed_date",
)

# `court_code` 는 식별키의 일부라 비교 대상이 아니지만(같지 않으면 애초에 다른 행이다)
# SET 에는 넣어 둔다 — 기존 구현과 같은 동작을 유지한다.
_UPSERT_SET = ", ".join(
    "%s=excluded.%s" % (c, c) for c in ("court_code",) + UPSERT_COMPARE_COLUMNS
) + ", updated_at=excluded.updated_at"

_UPSERT_WHERE = " OR ".join(
    "auction.%s IS NOT excluded.%s" % (c, c) for c in UPSERT_COMPARE_COLUMNS
)

# ★ `created_at` / `has_*` 는 SET 에 **없다.** 그래서 갱신에서 보존된다 —
#   예전 구현이 UPDATE 문에 그 컬럼들을 안 넣어 둔 것과 같은 효과다.
#
# ★★ 접수일(`filed_date`)은 **있을 수도 없을 수도 있다** (2026-08-30, BUGS #285).
#
#   028 이 그 컬럼을 만드는데, 마이그레이션이 아직 안 돈 DB 가 존재한다 —
#   운영 스키마를 스냅샷한 스크래치, 예전 클론, 마이그레이션 전 수동 실행.
#   무조건 쓰면 그런 DB 에서 **모든 행이 `no such column` 으로 실패한다**
#   (실제로 스위트가 68/1 -> 62/7 로 무너졌다).
#
#   그래서 문장을 두 벌 만들어 두고 실행 시점에 고른다. 두 벌 모두 **같은
#   컬럼 목록에서** 만들어지므로 한쪽만 낡을 수 없다.
def _build_upsert_sql(with_filed_date):
    cols = ["court_code", "court_name", "case_no", "item_no",
            "property_type", "sido", "sigungu", "dong", "lot_number",
            "full_address", "appraisal_price", "minimum_bid_price",
            "auction_date", "status", "validation_status",
            "validation_reasons", "crawl_date"]
    if with_filed_date:
        cols.append("filed_date")
    compare = [c for c in UPSERT_COMPARE_COLUMNS
               if with_filed_date or c != "filed_date"]
    set_sql = ", ".join("%s=excluded.%s" % (c, c)
                        for c in ["court_code"] + compare) + \
        ", updated_at=excluded.updated_at"
    where_sql = " OR ".join("auction.%s IS NOT excluded.%s" % (c, c)
                            for c in compare)
    placeholders = ",".join(["?"] * len(cols))
    return (
        "INSERT INTO auction (\n        " + ", ".join(cols) +
        ",\n        has_spec_pdf, has_status_doc, has_appraisal_pdf,"
        "\n        created_at, updated_at\n    ) VALUES (" +
        placeholders + ",0,0,0,?,?)\n"
        "    ON CONFLICT(court_code, case_no, item_no) DO UPDATE SET\n" +
        set_sql + "\n    WHERE " + where_sql + "\n")


UPSERT_SQL = _build_upsert_sql(True)
UPSERT_SQL_NO_FILED_DATE = _build_upsert_sql(False)


def auction_has_filed_date(conn) -> bool:
    """`auction.filed_date` 가 있는가 (028 적용 여부).

    배치 한 번에 한 번만 묻는다 — 행마다 물으면 #247/#249 가 없앤 그 부류가 된다.
    """
    try:
        return any(r[1] == "filed_date"
                   for r in conn.execute("PRAGMA table_info(auction)"))
    except Exception:                       # noqa: BLE001
        return False




def upsert_batch(rows: List[Dict]) -> Dict:
    """크롤 결과를 `auction` 에 반영한다.

    돌려주는 것: `{"inserted", "updated", "unchanged", "failed"}`

    ## `unchanged` 가 왜 따로 있는가 (2026-08-27, docs/BUGS.md #249)

    예전에는 **값이 같아도 매번 18컬럼 UPDATE 를 보냈다.** 법원 자료는 대부분 어제와
    같으므로 그 대부분이 아무것도 바꾸지 않는 쓰기였다. `#247`(migrate_execute)과
    `#249`(큐)에서 없앤 것과 **같은 계열**이다.

    그런데 여기만은 바로 고칠 수 없었다. `updated` 를 "실제로 쓴 행"으로 줄이면
    `CrawlOutcome.persisted` 가 함께 줄어들기 때문이다:

        persisted = inserted + updated
        if persisted == 0: -> "DB 저장 0건" -> exit 1 -> run_daily.bat [FAILED]

    법원 자료가 하루 종일 그대로인 **정상적인 날에 크롤이 실패로 판정**되고
    `migrate_execute.py` 가 아예 실행되지 않는다. 그래서 세 번째 칸을 만들었다 —
    "찾았고, 이미 올바르다". 이것도 **저장에 성공한 것**이므로
    `CrawlOutcome.persisted` 는 셋을 다 더한다(`models/crawl_outcome.py` 참고).

    ★ `updated` 를 "찾은 행 수"로 두는 손쉬운 길을 택하지 않았다. 그러면 아무것도
      안 바뀐 날에도 배치 로그가 *"업데이트: 1,876건"* 을 찍는다 — 이 저장소가 #47 에서
      고친 "배치 로그가 사실이 아닌 것을 말한다"와 정확히 같은 문제다.
      `refresh_queue_priority()` 도 같은 이유로 실제로 바뀐 행 수를 돌려준다.
    

    ## 행마다 두 문장에서 **한 문장**으로 (2026-08-27, docs/BUGS.md #256)

    예전에는 행마다 `SELECT id` 로 존재를 확인하고 `INSERT` 또는 `UPDATE` 를 보냈다.
    문장 수는 **행 수의 두 배**였고, 하루치 파이프라인 전체 문장의 **99%** 가 여기였다
    (실측 2026-08-27, 운영 2,608행: upsert 5,219문장 / 나머지 경로 전부 합쳐 51문장).

    이제 `INSERT ... ON CONFLICT DO UPDATE ... WHERE <바뀐 게 있나>` 한 문장이다.
    변경 감지는 예전과 똑같이 **DB 가** 한다(그 계약은 그대로다).

        2,608행   신규 32.0->29.8ms  변화없음 27.9->22.6ms  변경 41.3->35.7ms
       10,000행   신규113.5->104.1ms 변화없음105.6->82.9ms  변경152.2->124.7ms
       50,000행   신규580.7->529.7ms 변화없음536.4->414.4ms 변경782.3->674.6ms
                  문장 2N+3 -> N+5   (모든 규모에서 결과값은 완전히 동일)

    ### ★ `RETURNING` 은 쓰지 않는다 — 재 보고 버렸다

    분류(신규/갱신/변화없음)를 `RETURNING created_at` + `fetchone()` 으로 하는 것이
    가장 곧은 길이라 **그것을 먼저 만들었고, 그게 훨씬 느렸다.** 원인을 갈라 재 보니
    upsert 가 아니라 **커서 물질화**였다(20,000행 신규):

        plain INSERT                              99.4ms
        SELECT + plain INSERT (예전 구현)         123.7ms
        upsert, RETURNING 없음                    99.8ms   <- upsert 자체는 공짜다
        upsert + RETURNING + fetchone            622.4ms   <- 6배

    그래서 분류를 **행마다 묻지 않고** 배치 앞뒤로 두 번만 센다(아래 참고).
    `#249` 때와 같은 교훈이다 — 재 보지 않았으면 문장 수만 줄이고 **더 느려진 채**
    끝났을 것이다.
    """
    conn = get_connection()
    failed = 0
    processed = 0
    try:
        # ★ 분류를 **행마다 묻지 않는다.** 배치 앞뒤로 두 번만 센다(#256).
        #
        #   inserted  = 행 수 증가분          (그 배치가 새로 만든 행)
        #   written   = total_changes 증가분  (실제로 쓴 행: 신규 + 갱신)
        #   updated   = written - inserted
        #   unchanged = 처리한 행 - written   (값이 같아 아무것도 안 쓴 행)
        #
        #   `total_changes` 는 커넥션이 지금까지 바꾼 행 수라 **SQL 을 한 문장도 더
        #   쓰지 않는다.** 이 유도가 성립하려면 한 upsert 가 정확히 0 또는 1행만
        #   바꿔야 하는데, `auction` 에는 트리거가 없고 이 테이블을 참조하는 외래키도
        #   없다(2026-08-27 전수 확인). 그 전제가 깨지면 아래 자기 검사가 시끄럽게 운다.
        before_rows = conn.execute("SELECT COUNT(*) FROM auction").fetchone()[0]
        before_changes = conn.total_changes
        # 028 이 돌았는가. **배치당 한 번만** 묻는다.
        _has_filed = auction_has_filed_date(conn)
        _sql = UPSERT_SQL if _has_filed else UPSERT_SQL_NO_FILED_DATE
        if not _has_filed:
            logger.info("auction.filed_date 가 없다 - 접수일 없이 upsert 한다 "
                        "(마이그레이션 028 미적용)")

        for row in rows:
            try:
                now = datetime.now().isoformat()
                _values = (
                    row.get("court_code", ""),
                    row.get("court_name", ""),
                    row.get("case_no", ""),
                    row.get("item_no", ""),
                    row.get("property_type", ""),
                    row.get("sido", ""),
                    row.get("sigungu", ""),
                    row.get("dong", ""),
                    row.get("lot_number", ""),
                    row.get("full_address", ""),
                    int(row.get("appraisal_price", 0) or 0),
                    int(row.get("minimum_bid_price", 0) or 0),
                    row.get("auction_date", ""),
                    row.get("status", ""),
                    row.get("validation_status", ""),
                    row.get("validation_reasons", ""),
                    row.get("crawl_date", ""),
                ) + (
                    # 못 읽었으면 빈 문자열이 아니라 NULL 로 둔다 — "아직 모른다"와
                    # "값이 없다"를 구분해야 migrate_execute 의 `IS NULL` 보충이
                    # 성립한다. `''` 를 넣으면 그 사건은 영영 안 채워진다.
                    (row.get("filed_date") or None,) if _has_filed else ()
                ) + (now, now)
                conn.execute(_sql, _values)
                processed += 1
            except Exception as e:
                logger.warning("upsert 실패 [%s]: %s", row.get("case_no", ""), str(e))
                failed += 1

        after_rows = conn.execute("SELECT COUNT(*) FROM auction").fetchone()[0]
        written = conn.total_changes - before_changes
        inserted = after_rows - before_rows
        updated = written - inserted
        unchanged = processed - written

        # ★ 유도가 깨졌으면 **조용히 틀린 숫자를 내보내지 않는다.**
        #   이 값들은 `CrawlOutcome.persisted` 를 거쳐 크롤의 종료코드가 된다 —
        #   틀린 채로 흘러가면 배치 로그가 사실이 아닌 것을 말하게 된다(#47).
        if inserted < 0 or updated < 0 or unchanged < 0:
            logger.error(
                "upsert 집계 유도가 깨졌다 - 처리 %d행 / 행수 %d->%d / 쓴 행 %d "
                "(신규 %d, 갱신 %d, 변화없음 %d). auction 에 트리거나 참조 외래키가 "
                "생겼는지 확인하라 - 그러면 total_changes 가 한 행보다 많이 센다",
                processed, before_rows, after_rows, written,
                inserted, updated, unchanged)

        conn.commit()
        logger.info("DB UPSERT 완료 - 신규: %d, 갱신: %d, 변화없음: %d, 실패: %d",
                    inserted, updated, unchanged, failed)
        return {"inserted": inserted, "updated": updated,
                "unchanged": unchanged, "failed": failed}

    except Exception as e:
        conn.rollback()
        logger.error("DB UPSERT 전체 실패: %s", str(e))
        raise
    finally:
        conn.close()


def query(
    sido: str = None,
    court_name: str = None,
    auction_date: str = None,
    property_type: str = None,
    validation_status: str = None,
    limit: int = 100,
) -> List[Dict]:
    conn = get_connection()
    try:
        conditions = []
        params = []
        if sido:
            conditions.append("sido = ?")
            params.append(sido)
        if court_name:
            conditions.append("court_name = ?")
            params.append(court_name)
        if auction_date:
            conditions.append("auction_date = ?")
            params.append(auction_date)
        if property_type:
            conditions.append("property_type LIKE ? ESCAPE '\\'")
            params.append("%" + escape_like(property_type) + "%")
        if validation_status:
            conditions.append("validation_status = ?")
            params.append(validation_status)

        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        sql = "SELECT * FROM auction " + where + " ORDER BY auction_date DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_stats() -> Dict:
    conn = get_connection()
    try:
        total = conn.execute("SELECT COUNT(*) FROM auction").fetchone()[0]
        by_sido = conn.execute(
            "SELECT sido, COUNT(*) as cnt FROM auction GROUP BY sido ORDER BY cnt DESC"
        ).fetchall()
        by_date = conn.execute(
            "SELECT auction_date, COUNT(*) as cnt FROM auction GROUP BY auction_date ORDER BY auction_date DESC LIMIT 7"
        ).fetchall()
        return {
            "total": total,
            "by_sido": [dict(r) for r in by_sido],
            "by_date": [dict(r) for r in by_date],
        }
    finally:
        conn.close()


# ===== 02:00 PDF 수집 대기열(document_queue) =====

# 시각 비교의 기준. **로컬 시각이다** — 이 저장소가 시각을 그렇게 쓰기 때문이다.
#
# `last_attempt_at` / `enqueued_at` / `updated_at`은 전부 파이썬이
# `datetime.now().isoformat()`으로 남긴 **로컬 시각**이다. 그런데 SQLite의
# `datetime('now')`는 **UTC**다. 두 값을 그대로 비교하면 시차만큼 조용히 어긋난다.
#
# 한국(UTC+9)에서 실측한 결과가 이렇다 (2026-08-14):
#
#     저장값        2026-08-14T09:53:43   (로컬)
#     datetime('now') 2026-08-14 00:53:43 (UTC)
#
# 저장값이 9시간 "미래"로 보이므로 `datetime(last_attempt_at) <= datetime('now','-30 minutes')`는
# **실제로 9시간 30분이 지나야** 참이 된다. 즉 `RETRY_INTERVAL_MINUTES = 30`은 30분이 아니라
# 9시간 30분이었고, `reset_stale_queue()`의 "in_progress 10분" 회수도 9시간 10분이었다.
# doc_worker는 02:00~04:00 두 시간만 도는데 재시도 간격이 9시간 반이면 **한 번 실패한 문서는
# 그날 밤 안에 다시 시도될 수 없고**, 죽은 Worker가 남긴 in_progress 행도 그 밤에는 회수되지
# 않는다. 두 방어 장치가 설계대로 동작한 적이 없었다.
#
# 저장 형식을 UTC로 바꾸면 이미 쌓인 행 전부와 어긋나므로, **비교 쪽을 로컬로 맞춘다.**
_NOW_LOCAL = "datetime('now', 'localtime')"


def calc_priority(auction_date: str) -> int:
    if not auction_date:
        return 3
    try:
        target = datetime.strptime(auction_date, "%Y-%m-%d")
        days_left = (target - datetime.now()).days
        if days_left <= 3:
            return 1
        elif days_left <= 7:
            return 2
        return 3
    except Exception:
        return 3


def enqueue_documents(rows: List[Dict]) -> Dict:
    """
    06:00 사건 수집 직후 호출.

    ## 이미 받아 둔 문서를 다시 큐에 넣지 않는 방법 (2026-08-25 서술 정정)

    예전 이 자리에는 *"이미 has_*_pdf=1인 문서는 큐에 넣지 않는다"* 라고 적혀 있었다.
    **이 함수는 `has_*_pdf` 를 읽지 않는다**(2026-08-25 전수 확인). 실제 기제는 다르다 —
    `UNIQUE(court_code, case_no, item_no, doc_type)` + `INSERT OR IGNORE` 라서,
    이미 있는 행은 **상태가 무엇이든 그대로 남는다.** 한 번 `done` 이 된 행은 계속
    `done` 이므로 재수집되지 않는다(실측: 같은 배치를 다시 넣어도 added=0, done 유지).

    두 서술의 결과는 비슷해 보이지만 조사할 때 갈린다 — 옛 서술을 믿으면 "큐에
    `done` 행이 남아 있는 것"을 결함으로 오해하게 된다. 그것은 정상이고, 오히려
    **재수집 예약(`refresh`)이 그 행을 되살리는 방식**으로 동작한다(Sprint 189).

    UNIQUE 덕에 이미 대기 중인 항목도 조용히 무시된다 (중복 enqueue 방지).

    ## 기일이 다시 잡히면 `SKIPPED_EXPIRED` 를 되살린다 (2026-08-27, docs/BUGS.md #254)

    `SKIPPED_EXPIRED` 는 **"기일이 지나 지금은 대상이 아님"** 이라는 기록이다. 그런데
    유찰 후 재매각으로 기일이 미래로 다시 잡히면 그 전제가 **사실이 아니게 된다.**
    Sprint 74 가 이 함수에 `to_refresh` 를 넣어 `auction_date` 는 최신으로 맞췄지만
    `status` 는 일부러 두었고, 그래서 이런 행이 남았다 — 실측(2026-08-27 운영 DB):

        큐 36행: status=SKIPPED_EXPIRED / auction_date=2026-08-27(**오늘**)
                 전부 doc_type=appraisal
                 같은 물건의 spec/status/image 는 pending (같이 수집될 예정)
                 document_status 기록 **없음** / doc_raw **0행** (한 번도 못 받았다)

    즉 **오늘 매각이 진행되는 물건의 감정평가서만** 조용히 빠진다. 화면은 "수집중"에
    머물고, 큐는 "대상 아님"이라고 말하며, 둘 다 사실이 아니다. 그리고 아무도 다시
    보지 않는다 — `reset_stale_queue()` 는 SKIPPED_EXPIRED 를 일부러 건드리지 않고
    (성공할 수 없는 항목이 매일 되살아나는 것을 막는 규칙이다), 이 함수는 날짜만 고쳤다.
    `test_pipeline_integrity.py` 가 상한 1로 잡아 두었는데 **1 -> 36 으로 늘었다.**

    ★ 이것은 보류된 "재수집 정책"이 아니다. 그 보류는 *이미 받아 둔 것을 또 받을지*
      (`done`/`failed` 되살리기)에 대한 판단이다. 여기 36행은 **한 번도 받은 적이 없다**
      (doc_raw 0행). 되살리는 것은 재수집이 아니라 **첫 수집**이고, 고치는 것은
      "큐가 자기 필드에 사실과 다른 값을 들고 있는 것"뿐이다 — Sprint 74 와 같은 판단이다.

    ★ `done` / `failed` / `SKIPPED_UNSUPPORTED` 는 **건드리지 않는다.** 되살리는 것은
      전제가 반증된 `SKIPPED_EXPIRED` 하나뿐이다. 특히 `SKIPPED_UNSUPPORTED` 는
      "지금 구조로는 성공할 수 없다"라서, 되살리면 `mark_queue_unsupported()` 가 없앤
      "영원히 재시도하는 항목"이 그대로 돌아온다.

    ★ `retry_count` 는 0 으로 되돌린다. 그 예산은 **지난 기일의 시도**에 대한 것이고,
      지금은 새 기일이다. `reset_stale_queue()` 가 하루 지난 `failed` 를 되돌릴 때
      쓰는 규칙과 같다(새 정책이 아니다). 되돌리지 않으면 예산이 소진된 행이
      `pending` 으로 남아 "pending 인데 재시도가 소진된 행" 불변식을 깬다.

    ★ 되살린 뒤에도 이미 실체가 있으면 수집기가 "이미 존재. 스킵"으로 곧바로 `done`
      처리한다(`overwrite=False` 경로). 그래서 없던 파일을 덮어쓸 위험은 없다.

    1차 방어선(예방): auction_date가 이미 지난 사건은 큐에 넣지 않는다.
    Step 13/14 검증 결과, 매각기일이 지난 사건은 법원경매정보 사이트의
    "사건번호 직접검색"으로도 조회가 안 되어(취하/변경/매각완료 등 사유는
    미확정이나, 검색 불가 자체는 실측 8건으로 확인됨) 애초에 수집이
    불가능하므로, 큐 적재 단계에서 걸러 불필요한 재시도 자체를 방지한다.
    """
    conn = get_connection()
    added = 0
    refreshed = 0
    revived_expired = 0
    skipped_expired = 0
    try:
        now = datetime.now().isoformat()
        today = datetime.now().strftime("%Y-%m-%d")

        # ── 이미 큐에 있는 행을 **먼저 한 번에** 읽는다 (2026-08-27, BUGS #249) ──────
        #
        # 예전에는 행마다 4종을 `INSERT OR IGNORE` 로 밀어 넣고, 안 들어갔으면(=이미 있으면)
        # 다시 `UPDATE ... AND IFNULL(auction_date,'') <> ?` 를 보냈다. 두 번 다
        # **no-op 여부 판정을 DB 에 맡겨** 문장은 전부 나갔다. 실측(같은 데이터 재수집):
        #
        #     입력 25,000행 -> 200,002문장 / 실제로 추가된 행 **0건**
        #
        # `migrate_execute` 가 같은 이유로 10만 행에서 동시 writer 를 죽였던 것과
        # 같은 계열이다(#247). 여기서도 답은 "빨리 보내기"가 아니라 **안 보내기**다.
        #
        # ★ 큐 전체를 읽지 않는다. 지금 입력에 있는 **(법원,사건,물건)만** 조회한다 —
        #   `document_queue` 는 누적 테이블이라 전체를 들면 메모리가 누적을 따라간다.
        #   이렇게 하면 메모리가 **입력 크기**에만 묶인다(하루 약 1,900행).
        #
        # ★ IN 목록은 **나눈다**(#243). 키 하나가 `?` 를 3개 쓰므로 나누지 않으면
        #   입력 10,922행에서 `too many SQL variables` 로 그날 적재가 통째로 실패한다.
        wanted_keys = []
        seen_key = set()
        for row in rows:
            k = (row.get("court_code", ""), row.get("case_no", ""),
                 str(row.get("item_no", "") or "1"))
            if k not in seen_key:
                seen_key.add(k)
                wanted_keys.append(k)

        # (court_code, case_no, item_no, doc_type) -> (auction_date, status)
        # ★ `status` 를 함께 읽는다(#254). 컬럼 하나가 늘 뿐 **문장 수는 그대로**다 —
        #   되살릴 대상을 고르려고 행마다 다시 물으면 위 #249 가 없앤 N+1 이 돌아온다.
        existing_q = {}
        for key_chunk in chunked_for_sql(wanted_keys, vars_per_item=3, conn=conn):
            placeholders = ",".join(["(?,?,?)"] * len(key_chunk))
            params = [v for triple in key_chunk for v in triple]
            for q in conn.execute(
                "SELECT court_code, case_no, item_no, doc_type, auction_date, status"
                " FROM document_queue"
                " WHERE (court_code, case_no, item_no) IN (" + placeholders + ")",
                params,
            ):
                existing_q[(q["court_code"], q["case_no"], q["item_no"],
                            q["doc_type"])] = (q["auction_date"], q["status"])

        to_insert = []       # 새로 넣을 큐 행
        to_refresh = []      # 기일이 바뀌어 갱신할 큐 행
        to_revive = []       # 기일이 다시 잡혀 되살릴 SKIPPED_EXPIRED 행 (#254)

        for row in rows:
            court_code = row.get("court_code", "")
            case_no = row.get("case_no", "")
            item_no = str(row.get("item_no", "") or "1")
            auction_date = row.get("auction_date", "")
            priority = calc_priority(auction_date)

            if auction_date and auction_date < today:
                skipped_expired += 1
                continue

            # 2026-08-17 Sprint 144: 'image' 추가. 물건 사진도 같은 큐로 수집한다.
            # 사진은 문서와 달리 **버튼을 누를 필요가 없다** — 상세페이지에 진입하면
            # 캐러셀이 이미 DOM에 있다(법원 원천 실측). 그래서 doc_worker는 이 종류만
            # 버튼 id 검사를 건너뛴다.
            for doc_type in ("spec", "status", "appraisal", "image"):
                qkey = (court_code, case_no, item_no, doc_type)
                if qkey not in existing_q:
                    to_insert.append((court_code, case_no, item_no, doc_type,
                                      priority, auction_date, now))
                    # 같은 배치 안에 같은 키가 두 번 나와도 두 벌 넣지 않는다
                    # (auction 의 UNIQUE 제약상 없어야 하지만 가정에 기대지 않는다)
                    existing_q[qkey] = (auction_date, QUEUE_STATUS_PENDING)
                    added += 1
                    continue

                prev_date, prev_status = existing_q[qkey]
                if prev_status == QUEUE_STATUS_SKIPPED_EXPIRED:
                    # ★ 여기 닿았다는 것은 위 `auction_date < today` 를 통과했다는 뜻,
                    #   즉 **기일이 아직 안 지났다**는 것이다. 그 행이 "기일이 지나 대상이
                    #   아님"으로 닫혀 있으면 그 기록은 지금 사실이 아니다(#254).
                    #   날짜가 바뀌었는지와 무관하게 되살린다 — 이미 최신 날짜를 들고
                    #   `SKIPPED_EXPIRED` 로 굳은 행이 실제로 36개 있었고, "바뀔 때만"
                    #   고치면 그것들은 영원히 안 고쳐진다.
                    to_revive.append((auction_date or prev_date, priority,
                                      court_code, case_no, item_no, doc_type))
                    existing_q[qkey] = (auction_date or prev_date, QUEUE_STATUS_PENDING)
                    revived_expired += 1
                elif auction_date and (prev_date or "") != auction_date:
                    # 이미 있는 행 — 기일이 바뀌었으면 최신 값으로 맞춘다 (2026-08-13 Sprint 74).
                    #
                    # 유찰 후 재매각은 한국 경매에서 일상이고, 그때 같은
                    # (법원,사건,물건)에 새 매각기일이 잡힌다. 그런데 위 INSERT는
                    # OR IGNORE라 **기존 행을 통째로 건드리지 않아** 큐는 옛 기일을 계속 들고 있었다.
                    #
                    # 그 결과가 나쁘다. doc_worker의 2차 방어선은 큐에 저장된 auction_date를 보고
                    # `auction_date < today`면 SKIPPED_EXPIRED로 끝낸다. 즉 **기일이 미래로 다시
                    # 잡힌 살아 있는 사건이, 남아 있던 옛 날짜 때문에 수집 대상에서 빠졌다.**
                    # refresh_queue_priority()도 같은 stale 값으로 우선순위를 계산해 함께 틀렸다.
                    # (2026-08-13 실측: 큐와 실제 기일이 다른 18행, 그중 9행은 기일이 미래였다)
                    #
                    # ★ status는 바꾸지 않는다. done/failed/SKIPPED_EXPIRED를 되살려 다시 수집할
                    #   것인지는 재수집 정책이라 제품 판단이다(docs/roadmap.md 결정 대기).
                    #   여기서 고치는 것은 큐가 자기 필드에 **사실과 다른 값**을 들고 있는 것뿐이다.
                    #   그것만으로 pending 행의 오판은 사라진다.
                    to_refresh.append((auction_date, priority,
                                       court_code, case_no, item_no, doc_type,
                                       auction_date))
                    existing_q[qkey] = (auction_date, prev_status)

        # `INSERT OR IGNORE` / `IFNULL(...) <> ?` 가드를 **그대로** 둔다. 위 조회와
        # 여기 사이에 다른 실행이 같은 행을 넣었을 수 있다(운영에서 두 프로세스가 겹치는
        # 것은 락으로 막지만, 방어를 조회 시점 가정에 기대게 만들지 않는다).
        # `executemany` 는 문장을 한 번만 준비하고 N번 실행하므로, 같은 행 수라도
        # `execute()` 를 N번 부르는 것보다 훨씬 싸다.
        if to_insert:
            conn.executemany("""
                INSERT OR IGNORE INTO document_queue
                    (court_code, case_no, item_no, doc_type, priority, auction_date, status, retry_count, enqueued_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?)
            """, to_insert)
        if to_refresh:
            conn.executemany("""
                UPDATE document_queue
                   SET auction_date = ?, priority = ?
                 WHERE court_code = ? AND case_no = ? AND item_no = ? AND doc_type = ?
                   AND IFNULL(auction_date, '') <> ?
            """, to_refresh)
            refreshed = len(to_refresh)
        if to_revive:
            # `AND status=?` 가드를 둔다 — 조회와 여기 사이에 워커가 그 행을 집어
            # 다른 상태로 옮겼다면 우리 판단이 낡은 것이므로 건드리지 않는다.
            # 그래서 `rowcount` 가 곧 "정말 되살린 행 수"다.
            cur = conn.executemany("""
                UPDATE document_queue
                   SET status=?, retry_count=0, auction_date=?, priority=?
                 WHERE court_code=? AND case_no=? AND item_no=? AND doc_type=?
                   AND status=?
            """, [(QUEUE_STATUS_PENDING, d, pr, cc, cn, it, dt,
                   QUEUE_STATUS_SKIPPED_EXPIRED)
                  for (d, pr, cc, cn, it, dt) in to_revive])
            revived_expired = cur.rowcount if cur.rowcount and cur.rowcount >= 0                 else len(to_revive)
        conn.commit()
        logger.info("document_queue 적재: %d건 (기일 갱신: %d건, 기일 재공고로 되살림: %d건, "
                    "기일경과로 사전제외: %d건)",
                    added, refreshed, revived_expired, skipped_expired)
        if revived_expired:
            logger.info("기일이 다시 잡혀 SKIPPED_EXPIRED 에서 되살린 %d행 - "
                        "그 상태로 두면 진행 중인 물건의 문서가 영원히 수집되지 않는다",
                        revived_expired)
        return {"added": added, "refreshed": refreshed,
                "revived_expired": revived_expired,
                "skipped_expired": skipped_expired}
    finally:
        conn.close()


def doc_types_for_changed_fields(fields) -> tuple:
    """바뀐 필드 이름들 -> 다시 받아야 할 자산 종류(정렬된 튜플).

    매핑은 `REFRESH_DOC_TYPES_BY_FIELD` 하나뿐이다 — 호출부(`migrate_execute.py`)와
    회귀 테스트가 이 함수를 통해 같은 표를 본다(어휘를 복제하지 않는다).
    모르는 필드는 조용히 무시한다(자산과 무관한 필드가 바뀌었을 뿐이다).
    """
    out = set()
    for f in (fields or ()):
        for t in REFRESH_DOC_TYPES_BY_FIELD.get(f, ()):  # 모르는 필드 -> ()
            if t in QUEUE_TO_DOC_STATUS_TYPE:            # 큐가 다루는 종류만
                out.add(t)
    return tuple(sorted(out))


def requeue_changed_documents(changes: List[Dict],
                              max_items: Optional[int] = None) -> Dict:
    """법원 원천이 바뀐 물건의 자산을 **다시 받도록** 큐를 되돌린다 (2026-08-18 Sprint 189).

    `changes`의 각 항목: {"court_code", "case_no", "item_no", "fields": [바뀐 필드명, ...]}

    이 함수가 이 저장소에서 **처음으로 `overwrite=True` 경로에 실제로 도달하게 만드는
    지점**이다. 지금까지 재수집 기계(수집기의 overwrite, 해시 비교, document_version_log,
    부분수집 보호)는 전부 완성돼 있었지만 트리거가 없어 한 번도 돌지 않았다.

    ## 무엇을 건드리고 무엇을 안 건드리는가

        done                 -> refresh   (다시 받는다. 이 함수의 본래 일.
                                           단 **매각기일이 지나지 않은 물건만** — 아래 참고)
        SKIPPED_EXPIRED      -> pending   (기일이 **미래로 다시 잡힌 경우에만**)
        pending / refresh    그대로       (이미 대기 중 — 굳이 건드릴 이유가 없다)
        in_progress(_refresh) 그대로      (워커가 소유 중 — 뺏으면 그 실행이 끝나며
                                           done으로 덮어써 재수집 의도가 사라진다)
        failed               그대로       (자기 재시도 경로가 따로 있다. 여기서 되살리면
                                           MAX_DOC_RETRY 예산 계산이 흐트러진다)
        SKIPPED_UNSUPPORTED  그대로       (성공할 수 없는 항목의 영구 종결 —
                                           `mark_queue_unsupported()`가 끊은 무한 재시도
                                           고리를 여기서 다시 이으면 안 된다)

    `SKIPPED_EXPIRED`만 'refresh'가 아니라 'pending'인 이유: 그 행은 **한 번도 받아 본 적이
    없다.** overwrite로 갈 이유가 없고, 그렇게 두면 수집기가 "이미 존재" 스킵으로 값싸게
    넘어갈 수 있는 경우(형제 물건 복사 등)를 잃는다.

    돌려주는 값: {"items": 대상 물건 수, "refreshed": done->refresh 행 수,
                  "revived_expired": 기일부활 행 수, "skipped_over_cap": 상한으로 미룬 물건 수}
    """
    if not changes:
        return {"items": 0, "refreshed": 0, "revived_expired": 0, "skipped_over_cap": 0}

    # ★★ 2026-08-30 (BUGS #278) — **상한을 여기서 걷어냈다.**
    #
    #   예전에는 `changes[:60]` 으로 잘랐다. 그런데 잘린 물건도 `auction_item` 은
    #   이번 실행에서 이미 갱신되므로 다음 실행의 `changes` 에 **다시 들어오지 않는다.**
    #   미룬 것이 아니라 잃은 것이었다(사본 실측: 200물건 중 140물건 영구 유실).
    #   게다가 `SELECT * FROM auction` 순서라 매번 같은 앞쪽 물건만 뽑혔다.
    #
    #   상한 60 의 근거는 **워커가 하룻밤에 처리할 수 있는 양**이다(창 7,200초 /
    #   물건당 최악 4행 x 24초 -> 69물건). 그건 **소비**의 한계인데 **생산**
    #   (큐에 적는 일) 쪽에 걸려 있었다. 큐는 할 일을 담으려고 있는 것이라,
    #   담기 전에 자르면 큐가 존재하는 이유가 없어진다.
    #
    #   소비 쪽은 이미 스스로 제한한다.
    #       doc_worker  02:00~04:00 창(`is_time_up()`) - 시간이 되면 멈춘다
    #       claim       ORDER BY priority ASC, auction_date ASC - 긴급도 순
    #   전부 적어 두면 오늘 밤은 급한 것부터 하고 나머지는 큐에 남는다. 다음 밤에
    #   이어서 한다. 기일이 지나면 `SKIPPED_EXPIRED` 가 정리한다.
    #
    #   `max_items` 를 **명시적으로** 넘기면 여전히 조인다 - 검사와 운영자 수동
    #   실행을 위해 남긴다. 바뀐 것은 기본값뿐이다.
    cap = max_items
    over_cap = 0
    if cap is not None and cap >= 0 and len(changes) > cap:
        over_cap = len(changes) - cap
        logger.warning(
            "재수집 대상 %d건 중 상한(%d)을 넘는 %d건을 이번 호출에서 제외한다 "
            "- `max_items` 를 **명시적으로** 넘겼기 때문이다. 기본 실행은 상한이 "
            "없다(BUGS #278)", len(changes), cap, over_cap)
        changes = changes[:cap]
    elif len(changes) > REFRESH_MAX_ITEMS_PER_RUN:
        # 자르지는 않는다. 다만 하룻밤 처리량을 넘는다는 사실은 알린다 -
        # 큐에 남아 다음 밤으로 넘어간다는 뜻이다(유실이 아니다).
        logger.info(
            "재수집 대상 %d건은 하룻밤 처리량(%d)을 넘는다 - 전부 큐에 적고 "
            "긴급도 순으로 여러 밤에 나눠 처리한다(유실 아님)",
            len(changes), REFRESH_MAX_ITEMS_PER_RUN)

    conn = get_connection()
    refreshed = 0
    revived = 0
    items = 0
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        for ch in changes:
            court_code = ch.get("court_code", "")
            case_no = ch.get("case_no", "")
            item_no = str(ch.get("item_no", "") or "1")
            doc_types = doc_types_for_changed_fields(ch.get("fields"))
            if not doc_types:
                continue
            items += 1
            for doc_type in doc_types:
                # ★ 기일이 이미 지난 물건은 되돌리지 않는다 (실측으로 추가한 조건).
                #   실제 DB 사본으로 돌려 보니 대상이 2026-07-15 기일의 물건이었다. 그대로
                #   refresh 로 되돌리면 워커가 집어가서 2차 방어선(`auction_date < today`)에
                #   걸려 곧바로 SKIPPED_EXPIRED 로 종결한다 — 아무 것도 다시 받지 못한 채
                #   **성공 기록(done)만 잃는다.** 얻는 것이 없고 잃는 것이 있는 왕복이다.
                #   (빈 기일은 되돌린다 — "지났다"고 단정할 근거가 없다.)
                cur = conn.execute("""
                    UPDATE document_queue
                       SET status=?, retry_count=0, last_attempt_at=NULL
                     WHERE court_code=? AND case_no=? AND item_no=? AND doc_type=?
                       AND status=?
                       AND (IFNULL(auction_date, '') = '' OR auction_date >= ?)
                """, (QUEUE_STATUS_REFRESH, court_code, case_no, item_no, doc_type,
                      QUEUE_STATUS_DONE, today))
                refreshed += cur.rowcount or 0

                # 기일이 지나 종결됐던 행은, 기일이 **미래로 다시 잡혔을 때만** 되살린다.
                # (유찰 후 재매각은 한국 경매에서 일상이다 — `enqueue_documents()`가
                #  이미 큐의 auction_date를 최신값으로 맞춰 두므로 그 값을 그대로 믿는다.)
                cur = conn.execute("""
                    UPDATE document_queue
                       SET status=?, retry_count=0, last_attempt_at=NULL
                     WHERE court_code=? AND case_no=? AND item_no=? AND doc_type=?
                       AND status=?
                       AND IFNULL(auction_date, '') >= ?
                """, (QUEUE_STATUS_PENDING, court_code, case_no, item_no, doc_type,
                      QUEUE_STATUS_SKIPPED_EXPIRED, today))
                revived += cur.rowcount or 0
        conn.commit()
        if refreshed or revived:
            logger.info("변경 기반 재수집 예약: 물건 %d건 / 재수집 %d행 / 기일부활 %d행",
                        items, refreshed, revived)
        else:
            logger.info("변경 기반 재수집 예약: 대상 물건 %d건이지만 되돌릴 큐 행이 없다"
                        "(아직 수집된 적 없는 물건이거나 이미 대기 중)", items)
        return {"items": items, "refreshed": refreshed,
                "revived_expired": revived, "skipped_over_cap": over_cap}
    finally:
        conn.close()


def refresh_queue_priority() -> int:
    """
    01:50에 별도 스케줄로 실행 (run_priority_refresh.bat -> refresh_priority.py).
    대기 중(pending)인 항목들의 auction_date 기준으로 priority를 다시 계산해 갱신한다.
    06:00에 enqueue 했을 때보다 시간이 지나 매각기일이 임박해진 사건의 우선순위를 끌어올리기 위함.
    """
    conn = get_connection()
    changed = 0
    examined = 0
    try:
        # 'refresh'도 **워커가 집어갈 대기 행**이므로 같이 재계산한다 — 빠지면 재수집
        # 대기분만 옛 우선순위로 남아 임박 물건이 뒤로 밀린다(2026-08-18 Sprint 189).
        # ── 바뀌는 행만 **묶어서** 갱신한다 (2026-08-27, docs/BUGS.md #249) ─────────
        #
        # 예전에는 대기 행 하나마다 UPDATE 를 한 번씩 보냈다. no-op 걸러내기를
        # `AND priority!=?` 로 **DB 에 맡겼기 때문에** 문장은 그대로 다 나갔다.
        # 실측(하루치 재실행, 값이 안 바뀐 정상적인 밤):
        #
        #     대기 행 25,000 -> UPDATE 100,003문장 / 실제로 바뀐 행 **0건**
        #     운영 현재      ->  2,753문장 / 대부분의 밤 0건
        #
        # `pending` 은 누적을 따라간다(물건 하나당 4행). 그래서 이 비용은 그날 일감이
        # 아니라 **쌓인 양**에 붙는다 — `migrate_execute` 가 같은 이유로 10만 행에서
        # 동시 writer 를 죽였던 것과 같은 계열이다(#247).
        #
        # `priority` 를 함께 읽어 **파이썬에서** 비교하면 보낼 문장이 사라진다.
        # 그리고 남은 것은 목표 우선순위가 1/2/3 셋뿐이라 **최대 3묶음**으로 끝난다.
        #
        # ★ `AND priority<>?` 가드는 그대로 둔다. 한 묶음은 목표값이 하나라 IN 목록에
        #   그대로 얹힌다 — SELECT 와 UPDATE 사이에 다른 실행이 끼어들어도 결과가 같고,
        #   `rowcount` 가 "정말 바뀐 행 수"라는 뜻을 유지한다(아래 반환값의 근거).
        #
        # ★ IN 목록은 **나눈다**(#243). id 하나가 `?` 하나를 쓰므로 나누지 않으면
        #   대기 행 32,766개에서 `too many SQL variables` 로 죽는다 — 느려지는 게
        #   아니라 그날 우선순위 갱신이 통째로 실패한다.
        rows = conn.execute(
            "SELECT id, auction_date, priority FROM document_queue WHERE status IN ("
            + QUEUE_CLAIMABLE_PLACEHOLDERS + ")",
            QUEUE_CLAIMABLE_STATUSES,
        ).fetchall()

        by_target = {}
        for row in rows:
            examined += 1
            new_priority = calc_priority(row["auction_date"])
            if row["priority"] == new_priority:
                continue                       # 보낼 문장이 없다
            by_target.setdefault(new_priority, []).append(row["id"])

        for new_priority, ids in sorted(by_target.items()):
            # vars_per_item=1 은 id 용. 목표 우선순위 2개(SET, 가드)는 headroom 이 덮는다.
            for chunk in chunked_for_sql(ids, vars_per_item=1, conn=conn):
                placeholders = ",".join("?" * len(chunk))
                cur = conn.execute(
                    "UPDATE document_queue SET priority=? WHERE id IN ("
                    + placeholders + ") AND priority<>?",
                    (new_priority,) + tuple(chunk) + (new_priority,))
                # 예전에는 검토한 행 수를 그대로 반환해서, 배치 로그가 매일 밤
                # "우선순위 재계산 완료: 2,736건"을 남겼다 — 실제로 바뀐 것이 0건인 날에도
                # 똑같이 찍혀 운영자가 "매일 수천 건이 갱신된다"고 오해하게 만들었다
                # (BUGS #47과 같은 부류 — 배치 로그가 사실이 아닌 것을 말하는 문제).
                # 이제 **실제로 바뀐 행 수**를 반환한다.
                changed += cur.rowcount or 0
        conn.commit()
        logger.info("document_queue 우선순위 재계산: %d건 검토, %d건 변경", examined, changed)
        return changed
    finally:
        conn.close()


def reset_stale_queue() -> None:
    """
    02:00 Worker 시작 시 호출.
    - 하루 지난 failed 건은 재시도 가능하도록 pending으로 되돌림
    - in_progress 상태로 10분 넘게 멈춰있는 건(비정상 종료 추정)도 회수
    - status='SKIPPED_EXPIRED' / 'SKIPPED_UNSUPPORTED'는 이 함수가 건드리는 대상
      (failed, in_progress)에 해당하지 않으므로 자동으로 재시도 대상에서 제외된다.
      다만 이는 "현재 시점 기준 수집 불가"의 기록일 뿐 "영구 재수집 불가"를 의미하지
      않으므로(PM 확정 사항), 필요 시 별도 운영 스크립트로 수동 재시도(pending 복귀)는
      가능하다. **자동 부활은 일부러 하지 않는다** — 성공할 수 없는 항목이 매일 되살아나
      영원히 재시도하던 것이 `mark_queue_unsupported()`가 해결한 문제다.

    ## 화면 상태를 함께 되돌린다 (2026-08-13 Sprint 78, BUGS #73)

    `mark_queue_failed()`는 "재시도가 소진된 **최종** 실패만 화면에 반영한다 — 중간
    재시도까지 FAILED로 바꾸면 다음 시도에서 성공할 문서가 잠깐 '실패'로 보였다가
    돌아온다"는 규칙으로 `document_status='FAILED'`를 쓴다. 그런데 이 함수가 그 행을
    `pending` + `retry_count=0`(완전히 새 시도)으로 되돌리면서 **화면 상태는 FAILED로
    남겨두었다.** 실측:

        복구 전  queue=failed   document_status=FAILED
        복구 후  queue=pending  document_status=FAILED   <- 재시도 대기인데 "수집실패"

    같은 모듈의 #50 규약("화면이 읽는 것은 document_status다 — 같은 트랜잭션에서 함께
    갱신해야 두 기록이 갈라지지 않는다")을 이 경로만 지키지 않고 있었다. 새 정책을
    정하는 것이 아니라 위 두 규칙을 그대로 적용한다.

    **`FAILED`인 행만 되돌린다.** `in_progress` 회수분이나 이전에 수집에 성공했던
    문서(READY)까지 COLLECTING으로 바꾸면, **파일이 실제로 있는 문서를 "수집중"으로
    가려** 사용자가 볼 수 있는 것을 못 보게 된다(정반대 방향의 결함).
    """
    conn = get_connection()
    try:
        # 되돌릴 대상을 **먼저** 식별한다 — UPDATE 뒤에는 어느 행이 failed였는지 알 수 없다.
        recovered = conn.execute("""
            SELECT court_code, case_no, item_no, doc_type FROM document_queue
            WHERE status=?
              AND last_attempt_at IS NOT NULL
              AND datetime(last_attempt_at) < datetime(""" + _NOW_LOCAL + """, '-1 day')
        """, (QUEUE_STATUS_FAILED,)).fetchall()

        conn.execute("""
            UPDATE document_queue
            SET status=?, retry_count=0
            WHERE status=?
              AND last_attempt_at IS NOT NULL
              AND datetime(last_attempt_at) < datetime(""" + _NOW_LOCAL + """, '-1 day')
        """, (QUEUE_STATUS_PENDING, QUEUE_STATUS_FAILED))

        # ★ 이미 실체를 가진 문서는 'pending' 이 아니라 'refresh' 로 되돌린다
        #   (2026-08-18 Sprint 210).
        #
        #   Sprint 189 는 **중간 재시도**에서 재수집 의도가 사라지는 것을 막았다
        #   (`QUEUE_RESUME_STATUS`: in_progress_refresh -> refresh). 막지 못한 것은
        #   **재시도 소진** 경로다. 위 UPDATE 는 무조건 'pending' 으로 되돌린다.
        #
        #       refresh -> in_progress_refresh -> 실패 x3 -> failed   (refresh 정보 소실)
        #               -> 하루 뒤 여기 -> pending
        #               -> claim(overwrite=False) -> "이미 존재. 스킵" -> done
        #
        #   법원이 바꾼 문서가 영원히 옛것으로 남고 큐는 **성공**으로 끝난다.
        #   오류도 경고도 없다. fixture 로 재현했다(Sprint 210).
        #
        #   상태값을 새로 만들지 않는다 — 이미 DB 에 있는 증거로 판정한다.
        #   `document_status` 가 READY 라는 것은 **볼 수 있는 실체가 있다**는 뜻이고,
        #   그런 행을 'pending' 으로 되돌리면 수집기가 즉시 "이미 존재. 스킵"으로
        #   성공 처리하므로 그 재시도는 **구조적으로 아무 일도 하지 않는다.**
        #   반대로 실체가 없는 행은 'pending' 이 맞다(처음 받는 것이다).
        promoted = 0
        for row in recovered:
            try:
                if _current_document_status(conn, row["court_code"], row["case_no"],
                                            row["item_no"], row["doc_type"]) != "READY":
                    continue
                cur = conn.execute("""
                    UPDATE document_queue
                       SET status=?
                     WHERE court_code=? AND case_no=? AND item_no=? AND doc_type=?
                       AND status=?
                """, (QUEUE_STATUS_REFRESH, row["court_code"], row["case_no"],
                      row["item_no"], row["doc_type"], QUEUE_STATUS_PENDING))
                promoted += cur.rowcount or 0
            except Exception as exc:  # noqa: BLE001 - 판정 실패로 큐 회수를 잃지 않는다
                logger.warning(
                    "재수집 의도 복원 실패 (법원=%s, 사건=%s, 물건=%s, 문서=%s): %s",
                    row["court_code"], row["case_no"], row["item_no"], row["doc_type"], exc)
        if promoted:
            logger.info("이미 실체가 있는 %d행은 pending 이 아니라 refresh 로 되돌렸다"
                        "(그러지 않으면 '이미 존재. 스킵'으로 헛돈다)", promoted)
        # 진행 상태는 두 갈래다(`in_progress` / `in_progress_refresh`). **각자 원래 자리로**
        # 돌려놓는다 — 둘 다 'pending'으로 회수하면 비정상 종료 한 번에 재수집 의도가
        # 사라진다(위 `mark_queue_failed()`와 같은 이유, 2026-08-18 Sprint 189).
        for in_progress, back_to in QUEUE_RESUME_STATUS.items():
            conn.execute("""
                UPDATE document_queue
                SET status=?
                WHERE status=?
                  AND last_attempt_at IS NOT NULL
                  AND datetime(last_attempt_at) < datetime(""" + _NOW_LOCAL + """, '-10 minutes')
            """, (back_to, in_progress))

        # 큐 변경과 **같은 트랜잭션**에서 화면 상태를 맞춘다(#50).
        #
        # ★ 화면 동기화 실패가 **큐 복구를 되돌리면 안 된다.** 이 함수의 본 작업은
        # "재시도할 행을 pending으로 회수하는 것"이고, 화면 상태는 그것에 딸린 반영이다.
        # 예외를 그대로 올리면 커밋 전에 빠져나가 회수 UPDATE까지 사라지고, doc_worker는
        # 아무것도 회수되지 않은 채 시작한다 — 고치려던 것보다 나쁜 결과다.
        # (`_set_document_status()`가 대상 행이 없을 때 예외 대신 경고 + False를 돌려주는
        #  것과 같은 판단이다. 실제로 `document_status`/`auction_item`이 없는 축소 스키마에서
        #  이 경로가 통째로 죽는 것을 기존 테스트가 잡아냈다 — Sprint 78.)
        restored = 0
        for row in recovered:
            try:
                if _current_document_status(conn, row["court_code"], row["case_no"],
                                            row["item_no"], row["doc_type"]) != "FAILED":
                    continue
                if _set_document_status(conn, row["court_code"], row["case_no"],
                                        row["item_no"], row["doc_type"], "COLLECTING"):
                    restored += 1
            except Exception as exc:  # noqa: BLE001 - 화면 반영 실패로 큐 회수를 잃지 않는다
                logger.warning(
                    "재시도 복구 중 화면 상태 갱신 실패 (법원=%s, 사건=%s, 물건=%s, 문서=%s): %s",
                    row["court_code"], row["case_no"], row["item_no"], row["doc_type"], exc)

        conn.commit()
        if recovered or restored:
            logger.info("document_queue 재시도 복구: %d건 pending 복귀, 화면 상태 %d건 "
                        "FAILED -> COLLECTING", len(recovered), restored)
    finally:
        conn.close()


def reconcile_queue_auction_date(queue_id: int, case_no: str, item_no: str,
                                  queue_date: str, court_code: str = None) -> str:
    """큐가 들고 있는 `auction_date`를 **권위 있는 값**(`auction_item`)과 대조해 정정한다.

    ## 왜 필요한가 (2026-08-17 Sprint 145 실측)

    `document_queue.auction_date`는 06:00 적재 시점에 복사해 둔 **비정규화 사본**이다.
    Sprint 74가 이미 "유찰 후 재매각으로 기일이 미래로 다시 잡히면 큐의 옛 날짜 때문에
    살아 있는 사건이 수집 대상에서 빠진다"는 것을 찾아 `enqueue_documents()`에 갱신
    로직을 넣었다. **그런데 그 갱신은 06:00 크롤이 돌 때만 일어난다.**

    실측 결과 그 사이 구멍이 그대로 남아 있었다:

        document_queue.auction_date != auction_item.auction_date   36행
          그중 pending + 큐 날짜는 과거 + 실제 기일은 미래         3행
          -> item 1533 (2024타경122092-1, 실제 기일 2026-08-19)

    item 1533은 **지금 검색에 노출되는 진행 중 물건**인데(전체 9건 중 1건), worker의
    2차 방어선이 큐의 `2026-07-15`를 보고 `SKIPPED_EXPIRED`로 종결시킨다. 즉
    **사용자가 볼 수 있는 물건의 문서가 영원히 수집되지 않는다.**

    ## 무엇을 고치는가

    "기일 지난 사건은 수집하지 않는다"는 **정책은 그대로 둔다.** 고치는 것은 그 판단이
    참조하는 **값의 출처**뿐이다 — 사본이 아니라 `auction_item`을 본다. Sprint 74의
    주석이 같은 말을 한다: *"여기서 고치는 것은 큐가 자기 필드에 사실과 다른 값을 들고
    있는 것뿐이다."*

    드리프트를 발견하면 큐 행도 함께 정정한다(`refresh_queue_priority()`도 이 값을 보고
    우선순위를 계산하므로 한 번 고쳐 두면 그쪽 오판도 같이 사라진다).
    `status`는 건드리지 않는다 — 종결된 행을 되살릴지는 재수집 정책이라 제품 판단이다.

    ## ★ 2026-08-17 Sprint 146 — 식별키에 **법원이 빠져 있었다** (수정)

    이 함수는 처음에 `WHERE case_no=? AND item_no=?` 로만 물건을 찾았다. 근거는
    *"(case_no, item_no)는 auction_item 1,876행에서 유일하다"* 였는데, 그 확인은
    **틀린 것을 확인한 것**이다 — `auction_item` 안에서 유일한 것과, **큐 행이 자기
    법원의 물건과 맺어지는가**는 다른 문제다. 조인 상대는 큐이고 큐에는 법원이 따로 있다.

    법원마다 사건번호를 독립 채번하므로 같은 `2024타경2803`이 여러 법원에 존재한다.
    실측(2026-08-17): 큐의 (사건,물건)이 **다른 법원의** auction_item과 매칭되는 행이
    **18행**(그중 pending 12행)이었다.

        q=7204  큐법원=성남지원  vs  물건법원=통영지원   2024타경4973-1
                -> 통영 물건의 기일(2026-08-10)로 성남 큐를 "정정"하게 된다

    즉 정정하려던 함수가 **엉뚱한 사건의 날짜를 덮어쓸** 수 있었다. 이것은
    `docs/BUGS.md` #18/#14가 이미 같은 저장소에서 두 번 잡은 "법원 없는 식별키" 함정이
    새 코드에 다시 들어온 것이다.

    이제 `court_code`를 함께 받아 대조한다. **법원을 못 받으면(하위호환 호출) 정정하지
    않고 큐 값을 그대로 돌려준다** — 잘못 고치는 것보다 안 고치는 편이 낫다.

    매칭되는 물건이 없어도 큐 값을 그대로 돌려준다(판단을 바꾸지 않는다).
    """
    if not court_code:
        # 법원 없이는 물건을 안전하게 특정할 수 없다. 추측해서 고치지 않는다.
        logger.warning("큐 기일 정정 생략: court_code 미지정 (queue_id=%s, %s-%s)",
                       queue_id, case_no, item_no)
        return queue_date

    conn = get_connection()
    try:
        # 식별키는 (법원, 사건번호, 물건번호) 3자다 — 법원을 빼면 다른 법원의 같은
        # 사건번호에 걸린다(위 주석의 Sprint 146 실측: 18행이 실제로 그랬다).
        row = conn.execute(
            "SELECT auction_date FROM auction_item "
            "WHERE court_name = ? AND case_no = ? AND CAST(item_no AS TEXT) = ?",
            (court_code, case_no, str(item_no)),
        ).fetchone()
        if row is None:
            return queue_date

        actual = row["auction_date"]
        if not actual or actual == queue_date:
            return queue_date

        conn.execute(
            "UPDATE document_queue SET auction_date = ?, priority = ? WHERE id = ?",
            (actual, calc_priority(actual), queue_id),
        )
        conn.commit()
        logger.info(
            "[%s-%s] 큐의 매각기일이 실제와 달라 정정: %s -> %s (queue_id=%s)",
            case_no, item_no, queue_date, actual, queue_id,
        )
        return actual
    finally:
        conn.close()


def mark_queue_skipped_expired(queue_id: int, court_code: str, case_no: str, item_no: str,
                                doc_type: str, auction_date: str,
                                claim_token: Optional[str] = None) -> None:
    """
    Worker가 브라우저 작업을 시작하기 전, auction_date < today를 발견했을 때 호출.
    - 브라우저 작업 없이 즉시 종료 (해당 함수 자체가 그 무작업 종료 지점)
    - retry_count는 증가시키지 않음 (실패가 아니라 "애초에 대상이 아님"이므로)
    - status를 'SKIPPED_EXPIRED'로 기록
    - 종료 사유를 로그로 남김 (사유 추적용)

    ## `document_status`를 **일부러** 건드리지 않는다 (제품 판단 대기)

    같은 모듈의 다른 종결 함수는 전부 화면 상태를 함께 쓴다 — `mark_queue_done`은 READY,
    `mark_queue_failed`와 `mark_queue_unsupported`는 FAILED. **이 함수만 큐만 닫는다.**
    그래서 화면(`document_status`)은 `COLLECTING`("수집중")에 남는다.

    이것은 누락이 아니라 Sprint 73이 검토하고 **보류한** 상태다:
    `document_status` enum에 "대상 아님"이 없어 FAILED로 쓰면 실패가 아닌 것을 실패로
    표기하게 되고, 새 상태를 만드는 것은 상태머신·화면 문구 결정이라 제품 판단이다.
    자세한 근거·측정값·함께 고쳐야 할 지점은
    `test_document_status_sync.py` §6이 들고 있고, 그 검사가 현재 동작을 고정한다
    (배선하는 순간 실패하도록).

    ## ★ 우리 claim 이 아직 살아 있을 때만 종결한다 (2026-08-25, docs/BUGS.md #202)

    `mark_queue_done` / `mark_queue_failed` 는 BUGS #181 에서 이 검사를 받았는데
    **이 함수와 `mark_queue_unsupported` 만 빠져 있었다.** 그 비대칭을 합성 물건으로
    재현했다(2026-08-25):

        A 가 집는다 -> 멈춘다 -> reset_stale_queue 가 회수 -> B 가 집어 실제로 수집
        -> 좀비 A 가 뒤늦게 이 함수를 부른다
           => 큐 = SKIPPED_EXPIRED  (B 가 작업 중인데 종결됐다)
           => 게다가 여기서 last_attempt_at 을 덮으므로 **B 의 claim 토큰이 무효가 된다**
        -> B 가 수집을 끝내고 mark_queue_done(claim_token=B) 을 부른다
           => 토큰이 안 맞아 큐는 그대로, 문서만 기록된다
           => 최종: document_status=READY / doc_raw 1행 / **큐=SKIPPED_EXPIRED**

    즉 실제로 받아 놓은 문서가 큐에서는 "대상 아님"으로 남는다. 이것은 이 저장소가
    스스로 확인해 온 불변식("화면이 READY 인데 큐가 done 계열이 아닌 행 0건")을 깨는
    상태다. 좀비의 **낡은 판단**(그때의 auction_date)이 살아 있는 실행을 덮는 것이라
    방향도 틀렸다.

    `claim_token` 이 None 이면 예전 동작 그대로다(토큰을 넘기지 않는 호출부 호환).

    ★ 2026-08-14 추가 측정 — 이 상태로 남는 문서는 §6이 센 183건보다 훨씬 많다.
      원인이 **둘**이기 때문이다.

        (a) 큐가 SKIPPED_EXPIRED로 종결됨 (이 함수)          183건
        (b) 기일 경과로 **애초에 큐에 넣지 않음**            2,145건
            (`enqueue_documents()`의 1차 방어선. 716물건 x 3종,
             큐 행 자체가 없어 어떤 종결 함수도 지나지 않는다)

      (b)는 이 함수를 고쳐도 남는다. 정책을 정할 때 두 경로를 함께 봐야 한다.
    """
    conn = get_connection()
    try:
        if not _claim_is_still_ours(conn, queue_id, claim_token):
            logger.warning(
                "[%s-%s] %s 기일 경과로 종결하려 했으나 그 사이 큐 행(id=%s)이 회수돼 "
                "다른 실행이 집어갔다 - 종결하지 않는다(그쪽 판단에 맡긴다)",
                case_no, item_no, doc_type, queue_id)
            return
        now = datetime.now().isoformat()
        conn.execute("""
            UPDATE document_queue
            SET status=?, last_attempt_at=?
            WHERE id=?
        """, (QUEUE_STATUS_SKIPPED_EXPIRED, now, queue_id))

        conn.commit()
        logger.info(
            "[%s-%s] %s SKIPPED_EXPIRED 처리 (사유: auction_date=%s 경과, 법원=%s)",
            case_no, item_no, doc_type, auction_date, court_code
        )
    finally:
        conn.close()


def mark_queue_unsupported(queue_id: int, court_code: str, case_no: str, item_no: str,
                            doc_type: str, claim_token: Optional[str] = None) -> None:
    """수집 버튼 id가 아예 없는(= 지금 구조로는 성공할 수 없는) 항목의 종결 처리.

    2026-08-14 신설. `doc_worker.py`는 큐에서 집은 항목마다
    `get_doc_button_id(doc_type, item_no)`를 부르고, None이면 브라우저를 열지 않는다.
    None이 되는 경우는 **둘 다 영구적**이다 — 현황조사서의 item_no != '1'
    (DOM으로 확인된 버튼 id가 없다), 그리고 알 수 없는 doc_type.

    ## 왜 `mark_queue_failed()`로는 안 되는가 (실측 재현)

    예전에는 이 경로도 `mark_queue_failed()`를 불렀다. 그런데 실패는 **재시도 대상**이고,
    `reset_stale_queue()`는 하루 지난 failed를 pending + retry_count=0으로 되살린다.
    성공할 수 없는 항목이 그 고리에 들어가면 **영원히 빠져나오지 못한다**:

        1일차  pending  retry=1   화면 COLLECTING
        2일차  pending  retry=2   화면 COLLECTING
        3일차  failed   retry=3   화면 FAILED      <- 재시도 소진
        4일차  (reset_stale_queue가 되살린다)
        5일차  pending  retry=1   화면 COLLECTING  <- 처음으로 되돌아간다
        ...  16일 동안 12회 시도. 성공 가능성은 0.

    두 가지가 나쁘다. (a) 절대 성공하지 못할 항목이 매일 claim 슬롯을 먹는다.
    (b) **화면 상태가 4일 주기로 "수집실패" <-> "수집중"을 오간다** — 사용자는 같은
    문서가 며칠마다 상태를 바꾸는 것을 보는데, 실제로는 아무것도 달라지지 않았다.

    ## 그래서 `SKIPPED_EXPIRED`와 같은 계열로 끝낸다

    "실패"가 아니라 **"애초에 대상이 아님"**이다. `mark_queue_skipped_expired()`와 같은
    모양을 따른다 — retry_count를 소모하지 않고, `reset_stale_queue()`가 건드리는
    대상(failed, in_progress)에서 벗어나므로 자동으로 재시도 고리에서 빠진다.

    `SKIPPED_EXPIRED`와 마찬가지로 이것도 "현재 구조 기준"의 기록일 뿐 영구 불가를
    뜻하지 않는다. 현황조사서의 다른 item_no 버튼 id가 DOM 분석으로 밝혀지면, 그때
    별도 운영 스크립트로 pending 복귀시키면 된다(자동 부활은 일부러 하지 않는다 —
    그것이 바로 위 무한 고리였다).

    ## 화면 상태는 FAILED로 **한 번만** 쓴다

    Sprint 75가 이미 정한 것을 그대로 유지한다 — "큐에서 빼면 document_status가
    COLLECTING(수집중)에 영원히 머문다(BUGS #69와 같은 상태). 빠르게 실패로 남기는 쪽이
    더 정직하다." 달라지는 것은 **시점과 안정성**뿐이다: 3일 뒤가 아니라 즉시,
    그리고 다시 뒤집히지 않는다.
    """
    conn = get_connection()
    try:
        # ★ `mark_queue_skipped_expired()` 와 같은 이유로 claim 을 확인한다
        #   (2026-08-25, docs/BUGS.md #202). 이 함수도 last_attempt_at 을 덮으므로,
        #   남의 claim 을 무효로 만들면서 종결까지 해 버린다.
        if not _claim_is_still_ours(conn, queue_id, claim_token):
            logger.warning(
                "[%s-%s] %s 미지원으로 종결하려 했으나 그 사이 큐 행(id=%s)이 회수돼 "
                "다른 실행이 집어갔다 - 종결하지 않는다(그쪽 판단에 맡긴다)",
                case_no, item_no, doc_type, queue_id)
            return
        now = datetime.now().isoformat()
        conn.execute("""
            UPDATE document_queue
            SET status=?, last_attempt_at=?
            WHERE id=?
        """, (QUEUE_STATUS_SKIPPED_UNSUPPORTED, now, queue_id))

        # 화면이 읽는 것은 document_status다 — 같은 트랜잭션에서 함께 갱신한다 (BUGS #50).
        _set_document_status(conn, court_code, case_no, item_no, doc_type, "FAILED")

        conn.commit()
        logger.warning(
            "[%s-%s] %s SKIPPED_UNSUPPORTED 처리 (사유: 수집 버튼 id 없음, 법원=%s) "
            "― 재시도해도 성공할 수 없으므로 큐에서 종결한다",
            case_no, item_no, doc_type, court_code
        )
    finally:
        conn.close()


# 큐의 doc_type(소문자)과 document_status.doc_type(대문자)의 대응.
# 두 테이블이 다른 표기를 쓰는 것은 기존 상태이며, 여기서 표기를 통일하면
# 이미 쌓인 5,610행과 어긋나므로 **변환만** 한다.
#
# 2026-08-17 Sprint 144: 물건 사진('image'/'IMAGE')을 넷째 종류로 넣었다. 사진 파일 자체는
# 개수가 0~N이라 `auction_image` 테이블에 따로 담지만, **"이 물건의 사진을 수집했는가"라는
# 상태는 문서와 완전히 같은 성질**이라 큐/상태 테이블을 새로 만들지 않고 그대로 쓴다
# (재시도 횟수·우선순위·stale 회수·동시 실행 잠금이 전부 이미 있고 검증돼 있다).
QUEUE_TO_DOC_STATUS_TYPE = {"spec": "SPEC", "status": "STATUS", "appraisal": "APPRAISAL",
                            "image": "IMAGE"}

# =====================================================================
# 큐 상태 어휘 (2026-08-18 Sprint 189 — 변경 기반 재수집)
# =====================================================================
#
# 지금까지 `document_queue`는 **한 번 done이 되면 영원히 done**이었다. 그래서 문서·사진은
# 물건당 딱 한 번만 수집됐고, 법원이 명세서를 다시 올리거나 사진을 바꿔 끼워도 화면은
# 최초 수집분을 계속 보여 줬다. 수집기에는 `overwrite=True` 경로가 이미 완성돼 있었지만
# **아무도 그 값을 넘기지 않았다**(Sprint 186/187이 남긴 마지막 공백).
#
# 여기서 채우는 것이 그 공백이다. 새 컬럼을 만들지 않고 **status 어휘를 늘린다** —
# `document_queue.status`는 TEXT에 CHECK 제약이 없어 값 추가는 스키마 변경이 아니다
# (스키마 변경은 승인 영역, docs/CLAUDE.md).
#
#     pending              한 번도 수집한 적 없다        -> overwrite=False
#     refresh              이미 있지만 다시 받아야 한다  -> overwrite=True
#     in_progress          pending을 집어간 상태
#     in_progress_refresh  refresh를 집어간 상태
#
# in_progress를 두 갈래로 나누는 이유: 재시도(`mark_queue_failed`)와 stale 회수
# (`reset_stale_queue`)가 **원래 어느 쪽이었는지 알아야** 제자리로 돌려놓을 수 있다.
# 하나로 합치면 재수집 의도가 첫 실패에서 조용히 사라진다.
QUEUE_STATUS_PENDING = "pending"
QUEUE_STATUS_REFRESH = "refresh"
QUEUE_STATUS_IN_PROGRESS = "in_progress"
QUEUE_STATUS_IN_PROGRESS_REFRESH = "in_progress_refresh"

# 종결 상태 — 워커가 다시 집지 않는다.
#
#   SKIPPED_EXPIRED       기일이 지나 **지금은** 대상이 아니다
#   SKIPPED_UNSUPPORTED   지금 구조로는 성공할 수 없다(수집 버튼 id 자체가 없다)
#
# ★ 둘의 성격이 다르다. `SKIPPED_UNSUPPORTED` 는 시간이 지나도 그대로지만,
#   `SKIPPED_EXPIRED` 는 **기일이 다시 잡히면 전제가 반증된다.** 그래서
#   `enqueue_documents()` 는 앞의 것만 되살린다(#254). 이름을 상수로 두는 이유가
#   그것이다 — 되살리는 쪽과 되살리지 않는 쪽을 문자열로 구별하면 언젠가 어긋난다.
QUEUE_STATUS_SKIPPED_EXPIRED = "SKIPPED_EXPIRED"
QUEUE_STATUS_SKIPPED_UNSUPPORTED = "SKIPPED_UNSUPPORTED"

# 워커가 끝낸 상태. **2026-08-31 신설** — 이 둘만 상수 없이 SQL 문자열에 직접 박혀
# 있었다. 같은 컬럼의 나머지 여섯은 상수인데 종결 둘만 리터럴이라, 바로 위 주석이
# 경고한 것("문자열로 구별하면 언젠가 어긋난다")이 같은 파일 안에서 반쯤 지켜지고
# 있었다. 값은 DB 에 들어 있는 것 그대로다(`api/constants.py` 가 상태값을 모을 때
# 세운 규칙과 같다 — 리터럴을 모으되 값은 새로 정하지 않는다).
#
#   done    수집이 실제로 끝났다
#   failed  재시도 예산(MAX_DOC_RETRY)을 다 쓰고도 실패했다
#
# ★ 왜 오타가 위험한가: 이 값들은 전부 `WHERE status='...'` 로 **비교**된다.
#   오타가 나면 예외가 아니라 **0행 매치**다. `mark_queue_done()` 이 아무 행도 바꾸지
#   못하면 그 행은 `in_progress` 로 남아 stale 회수까지 붙잡혀 있고, 화면에는 수집이
#   끝난 것으로 보인다. 조용한 실패라 로그로도 드러나지 않는다.
QUEUE_STATUS_DONE = "done"
QUEUE_STATUS_FAILED = "failed"

# 이 컬럼이 가질 수 있는 값 전부. 여기 없는 값이 DB 에 있으면 어딘가가 어휘를 늘렸거나
# 오타를 냈다는 뜻이다 — `test_queue_safety_invariants.py` 가 실제 DB 와 대조한다.
QUEUE_STATUSES = frozenset({
    QUEUE_STATUS_PENDING,
    QUEUE_STATUS_REFRESH,
    QUEUE_STATUS_IN_PROGRESS,
    QUEUE_STATUS_IN_PROGRESS_REFRESH,
    QUEUE_STATUS_DONE,
    QUEUE_STATUS_FAILED,
    QUEUE_STATUS_SKIPPED_EXPIRED,
    QUEUE_STATUS_SKIPPED_UNSUPPORTED,
})

# 워커가 집어갈 수 있는 상태. `claim_next_queue_item()`과 `refresh_queue_priority()`가
# **같은 목록**을 봐야 한다 — 갈라지면 refresh 행이 우선순위 재계산에서 빠진다.
QUEUE_CLAIMABLE_STATUSES = (QUEUE_STATUS_PENDING, QUEUE_STATUS_REFRESH)

# `IN (...)` 자리에 넣을 **`?` 반복만** 만든다. 상태 값 자체는 SQL 문자열에 절대 넣지 않고
# 예외 없이 바인딩한다 — `test_schema_hygiene.py`의 SQL 조립 감사가 허용하는 형태
# (`api/v1/payments.py`의 `IN (%s)`와 같은 패턴)이고, 어휘가 늘어도 자동으로 따라간다.
QUEUE_CLAIMABLE_PLACEHOLDERS = ", ".join("?" * len(QUEUE_CLAIMABLE_STATUSES))


# ---------------------------------------------------------------------------
# `IN (...)` 을 만들 때의 **바인딩 변수 상한** (2026-08-27, `docs/BUGS.md` #243)
#
# SQLite 는 한 문장에 넣을 수 있는 `?` 개수에 상한이 있다
# (`SQLITE_LIMIT_VARIABLE_NUMBER`, 이 환경 실측 **32,766**). 넘으면 실행 자체가
# `OperationalError: too many SQL variables` 로 죽는다 — 느려지는 것이 아니라 **멈춘다.**
#
# 이것이 실제로 매일 크롤링을 통째로 죽일 수 있는 자리였다. `migrate_execute.py` 가
# `(court_code, case_no)` 쌍을 한 문장에 몰아넣어 조회했는데, 쌍당 변수가 2개라
# **유니크 사건 16,384건째부터 파이프라인 전체가 실패**한다(실측: 16,383 정상 /
# 16,384 파손). 60개 법원을 매일 도는 구조라 수집 범위가 넓어지면 닿는 수다.
#
# 그래서 "얼마나 큰 입력이 와도 문장 하나에 다 넣지 않는다"를 **한 곳에서** 정한다.
# 값을 SQL 텍스트로 넣는 우회(인젝션 위험)로 풀지 않는다 — 나누기만 한다.
# 이 환경 실측은 32,766 이지만 **그 숫자를 믿고 박아 두지 않는다.** SQLite 3.31 이하의
# 기본값은 999 라, 상한을 상수로 가정하면 낮은 빌드에서 **500건대부터** 같은 사고가 난다.
# 그래서 실제 커넥션에 물어보고, 못 물어보면 가장 낮은 쪽(999)으로 보수적으로 잡는다.
SQLITE_MAX_VARIABLES_FALLBACK = 999


def sql_variable_limit(conn=None) -> int:
    """이 커넥션이 실제로 허용하는 `?` 개수. 모르면 보수적인 하한을 돌려준다."""
    if conn is not None:
        try:
            return int(conn.getlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER))
        except Exception:      # noqa: BLE001 - getlimit 은 Python 3.11+ 에만 있다
            pass
    return SQLITE_MAX_VARIABLES_FALLBACK


def chunked_for_sql(items, vars_per_item: int = 1, headroom: int = 64, conn=None):
    """`IN (...)` 한 문장이 변수 상한을 넘지 않도록 `items` 를 나눠 내보낸다.

    `vars_per_item` 은 항목 하나가 쓰는 `?` 개수다(단일 값이면 1,
    `(?,?)` 같은 행-값 쌍이면 2). `headroom` 은 같은 문장의 다른 바인딩
    (예: `WHERE user_id=? AND item_id IN (...)`) 을 위한 여유분이다.
    `conn` 을 주면 **그 커넥션의 실제 상한**을 쓴다 — 주지 않으면 보수적인 하한을 쓴다.

    빈 입력에서는 아무것도 내보내지 않는다 — 빈 `IN ()` 은 SQL 구문 오류라
    호출부가 그 경우를 따로 다루지 않아도 되게 한다.
    """
    limit = sql_variable_limit(conn)
    per_chunk = max(1, (limit - headroom) // max(1, vars_per_item))
    buf = []
    for it in items:
        buf.append(it)
        if len(buf) >= per_chunk:
            yield buf
            buf = []
    if buf:
        yield buf


# ── 대량 삭제 차단기 (2026-09-02) ──────────────────────────────────────────
#
# `load_rights_data.py` / `load_spec_data.py` 의 `purge_orphans()` 는 근거 문서가
# 사라진 물건의 파생 행(권리분석·임차인)을 지운다. 안전장치는 하나뿐이었다 —
# **`evidence_found == 0` 이면 건너뛴다.** 그건 `documents/` 를 통째로 못 읽는
# 경우만 막는다.
#
# 막지 못하는 것이 **부분 유실**이다. OneDrive 가 일부만 동기화됐거나, 드라이브가
# 절반만 마운트됐거나, 경로 규칙이 바뀌어 일부 법원만 못 찾는 상황에서는
# `evidence_found` 가 0 보다 크므로 안전장치가 열리고, 남은 근거 문서 몇 건을 빼고
# **나머지 권리분석 데이터를 전부 지운다.** 무인 야간 실행이라 아침에야 안다.
#
# 이것이 `docs/BUGS.md` #245 가 이 두 스크립트의 배선을 미뤘던 실제 사유다.
# 그래서 배선하기 전에 차단기를 먼저 단다.
#
# 판정 기준 — "한 번의 실행이 기존 파생 행의 큰 몫을 지우려 하면 그건 정리가 아니라 사고다"
#
#   정상 정리는 소량이다. 문서는 한 건씩 사라진다(취하·재게시·경로 정정).
#   2026-09-02 실측: 파생 행 rights_summary 413 / tenant_rights(STATUS) 1,069 이고
#   지금 지울 대상은 **0건**이다. 즉 평상시 값은 0 근처다.
#
#   바닥값을 두는 이유: 파생 행이 3건뿐인 초기 상태에서 1건을 지우는 것이 33% 라
#   비율만 보면 막힌다. 소량 삭제는 언제나 통과시킨다.
PURGE_MAX_RATIO = 0.20      # 기존 파생 행의 20% 를 넘게 지우려 하면 막는다
PURGE_ABSOLUTE_FLOOR = 10   # 다만 이 건수 미만이면 비율과 무관하게 통과시킨다

# `purge_orphans()` 가 "막았다"를 돌려줄 때 쓰는 표식.
# 삭제 건수와 섞이지 않도록 **음수**다 - 0 으로 두면 "지울 게 없었다"와 구분되지 않고,
# 그러면 호출부가 조용히 정상 종료해 #245 와 같은 침묵이 다시 생긴다.
PURGE_BLOCKED = -1


def guard_mass_purge(existing: int, to_delete: int, label: str):
    """대량 삭제를 막을지 판단한다. 아무것도 지우지 않는다 - 판정만 한다.

    돌려주는 값
        None      진행해도 된다
        str       막아야 한다. 사람이 읽을 사유 문자열.

    `existing` 은 지우기 **전** 파생 행 수, `to_delete` 는 이번에 지울 행 수다.
    """
    if to_delete <= 0:
        return None
    if to_delete < PURGE_ABSOLUTE_FLOOR:
        return None
    if existing <= 0:
        # 기존이 0인데 지울 게 있다는 것은 세는 쪽이 어긋난 것이다. 막고 사람이 본다.
        return ("%s: 기존 파생 행이 0인데 %d행을 지우려 한다 - 계수가 어긋났다"
                % (label, to_delete))
    ratio = to_delete / float(existing)
    if ratio > PURGE_MAX_RATIO:
        return ("%s: 한 번에 %d/%d행(%.1f%%)을 지우려 한다 - 상한 %.0f%% 초과. "
                "근거 문서가 대량으로 사라진 것은 데이터가 아니라 환경 문제일 가능성이 "
                "높다(동기화 지연/드라이브 미마운트/경로 규칙 변경). 지우지 않는다."
                % (label, to_delete, existing, ratio * 100, PURGE_MAX_RATIO * 100))
    return None


# 집어갈 때: 대기 상태 -> 진행 상태
QUEUE_CLAIM_STATUS = {
    QUEUE_STATUS_PENDING: QUEUE_STATUS_IN_PROGRESS,
    QUEUE_STATUS_REFRESH: QUEUE_STATUS_IN_PROGRESS_REFRESH,
}
# 되돌릴 때: 진행 상태 -> 원래 대기 상태
QUEUE_RESUME_STATUS = {v: k for k, v in QUEUE_CLAIM_STATUS.items()}

# 진행 중(=워커가 소유 중)인 상태. 재수집 트리거가 **절대 건드리면 안 되는** 상태다.
QUEUE_IN_PROGRESS_STATUSES = tuple(QUEUE_CLAIM_STATUS.values())

# 아직 끝나지 않은(대기 또는 진행) 상태 전부. 적체 규모를 세는 쪽이 참조한다.
QUEUE_ACTIVE_STATUSES = QUEUE_CLAIMABLE_STATUSES + QUEUE_IN_PROGRESS_STATUSES

# `overwrite=True`로 다시 받아야 하는 상태. doc_worker가 이 판단을 복제하지 않도록
# `claim_next_queue_item()`이 계산해서 `overwrite` 키로 넘겨 준다.
QUEUE_OVERWRITE_STATUSES = (QUEUE_STATUS_REFRESH, QUEUE_STATUS_IN_PROGRESS_REFRESH)


# 어떤 필드가 바뀌면 어떤 자산을 다시 받아야 하는가 (2026-08-18 Sprint 189).
#
# 전건 재수집은 실측 약 1.9시간이고 표적 재수집은 84초다(docs/roadmap.md 재수집 정책).
# 그래서 "바뀐 물건의, 그 변경이 실제로 영향을 주는 자산만" 다시 받는다. 근거:
#
#   auction_date       매각기일이 바뀌면 **그 기일 기준으로 매각물건명세서가 새로 게시된다**
#                      (법원은 기일마다 명세서를 다시 올린다). 현황조사서도 함께 갱신될 수 있다.
#   minimum_bid_price  최저매각가격 변동은 유찰 저감의 결과이고, 그 값이 명세서에 적혀 있다.
#   status             유찰/변경/취하/정지 등 사건상태 변화는 명세서·현황조사서 양쪽에 반영된다.
#   appraisal_price    감정가가 바뀌었다면 **재감정**이다 — 감정평가서가 새로 나오고,
#                      재감정에는 현장 재촬영이 따르므로 사진도 함께 다시 받는다.
#
# 사진(image)을 기일/최저가 변동에 넣지 않는 이유: 사진은 감정 시점에 찍힌 것이라
# 유찰로 값만 내려갈 때는 바뀌지 않는다. 넣으면 매일 수천 장을 이유 없이 다시 받는다.
REFRESH_DOC_TYPES_BY_FIELD = {
    "auction_date": ("spec", "status"),
    "minimum_bid_price": ("spec",),
    "status": ("spec", "status"),
    "appraisal_price": ("appraisal", "image"),
}

# 한 번 실행에서 재수집으로 되돌릴 **물건 수** 상한.
#
# 상한이 없으면 법원이 하루에 수천 건을 한꺼번에 갱신한 날(실측: 2026-08-01 하루 278건
# 신규) 워커의 실행 창(02:00~04:00)을 재수집이 통째로 차지해 **한 번도 수집된 적 없는
# 물건이 밀린다.** 아직 아무것도 못 본 사용자가 이미 보고 있는 사용자보다 먼저다.
# 초과분은 큐에 그대로 남아 다음 실행에서 다시 후보가 된다(유실 아님) — 그리고
# 잘린 건수는 **반드시 로그에 남긴다**(조용한 절단 금지).
#
# ── 값의 근거 (2026-08-18 Sprint 196 실측, BUGS #134) ────────────────────────
# 처음 값 300 은 **근거 없이 정한 숫자**였고, 재 보니 실행 창을 4배 넘겼다.
#
#   실행 창                 02:00~04:00 = 7,200초
#   기일 경과 적체 소진      2,733행 x 5.1ms = 14초 (브라우저 없이 종결, sleep 도 건너뜀)
#   한 번도 못 받은 물건     20행 x 24초 = 480초      <- 이쪽이 언제나 우선이다
#   남는 예산               6,706초
#   재수집 1물건의 최악      4행 (전 필드가 동시에 바뀌면 spec/status/appraisal/image)
#   -> 최악 기준 상한        6,706 / (4 x 24) = 69 물건
#
#   옛 값 300 의 최악 소요   300 x 4 x 24 = 28,800초 = 8.0시간 (창의 400%)
#
# **최악 기준**으로 잡는다 — 어느 필드가 바뀔지 미리 알 수 없으므로, 평균이 아니라
# 최악에서 안전해야 상한이 상한 노릇을 한다. 69 에서 여유를 두고 60 으로 정한다.
# (`test_refresh_trigger.py` 가 이 산술을 상수로 검증한다 — 창이나 소요가 바뀌면 실패한다.)
# 워커가 **하룻밤에 처리할 수 있는 물건 수**의 추정치 (창 7,200초 / 물건당 최악
# 4행 x 24초 -> 69물건, 여유를 둬 60).
#
# ★ 2026-08-30 (BUGS #278): 이 값으로 `changes` 를 **자르지 않는다.** 예전에는
#   잘랐고, 잘린 물건은 `auction_item` 이 이미 갱신돼 다음 실행 후보가 되지 못해
#   영구히 잃었다. 지금은 전부 큐에 적고 긴급도 순으로 여러 밤에 나눠 처리한다.
#   이 상수는 이제 **보고용**이다 - "오늘 적은 양이 하룻밤 처리량을 넘는가"를
#   알려 준다. 자르는 것은 `max_items` 를 명시적으로 넘겼을 때뿐이다.
REFRESH_MAX_ITEMS_PER_RUN = 60


# 화면 상태 중 **실제로 보여 줄 자산이 있다**는 뜻인 값들.
#
#   READY     문서/사진 파일이 있다
#   NO_IMAGE  법원이 사진을 제공하지 않는다는 것을 확인했다 — "없음"이 곧 정확한 답이라
#             재수집이 실패해도 이 답이 틀려지지 않는다("수집 실패"와 "원래 없음"은 다르다)
#
# 재수집이 실패했을 때 이 값들을 FAILED로 덮으면, 화면은 "수집실패"인데 파일 서빙은
# 200을 내는 어긋남이 생긴다(`mark_queue_failed()` 참고).
DOC_STATUS_HAS_ARTIFACT = ("READY", "NO_IMAGE")


# `auction`(레거시) 테이블에 "수집됨" 플래그 컬럼이 있는 종류.
# 사진에는 대응 컬럼이 없다 — 레거시 `auction` 테이블은 변경 금지(docs/backend.md)라
# `has_images` 같은 컬럼을 새로 만들지 않는다. 사진의 근거는 `auction_image` 행 자체다.
LEGACY_HAS_COLUMN = {
    "spec": "has_spec_pdf",
    "status": "has_status_doc",
    "appraisal": "has_appraisal_pdf",
}


def _document_status_item_id(conn, court_code: str, case_no: str, item_no: str):
    """큐 키(법원,사건,물건) -> `document_status.item_id`. 없으면 None.

    2026-08-13 Sprint 78에 `_set_document_status()`에서 이 조회만 떼어냈다 — 읽기 쪽
    (`_current_document_status`)이 **같은 JOIN 경로**를 써야 하기 때문이다. 조회를 두 벌
    두면 한쪽만 고쳐졌을 때 "쓰기는 찾는데 읽기는 못 찾는" 어긋남이 생긴다.
    """
    row = conn.execute(
        """
        SELECT ai.id FROM auction_item ai
        JOIN auction_case ac ON ac.id = ai.case_id
        WHERE ac.court_code = ? AND ai.case_no = ? AND ai.item_no = ?
        """,
        (court_code, case_no, item_no),
    ).fetchone()
    return row["id"] if row else None


def _current_document_status(conn, court_code: str, case_no: str, item_no: str,
                             doc_type: str):
    """현재 화면 상태 문자열. 대상이 없거나 아직 기록이 없으면 None.

    "지금 FAILED인 행만 되돌린다"처럼 **조건부**로 상태를 바꿀 때 쓴다
    (`reset_stale_queue()` — 이미 READY인 문서를 COLLECTING으로 덮으면 실제로 볼 수 있는
    문서를 가린다).
    """
    ds_type = QUEUE_TO_DOC_STATUS_TYPE.get(doc_type)
    if not ds_type:
        return None
    item_id = _document_status_item_id(conn, court_code, case_no, item_no)
    if item_id is None:
        return None
    row = conn.execute(
        "SELECT status FROM document_status WHERE item_id=? AND doc_type=?",
        (item_id, ds_type),
    ).fetchone()
    return row["status"] if row else None


def _set_document_status(conn, court_code: str, case_no: str, item_no: str,
                         doc_type: str, status: str) -> bool:
    """`document_status`를 갱신한다. 갱신했으면 True.

    2026-08-11 Sprint 55 신설 (docs/BUGS.md #50).

    왜 필요한가 — 문서 상태가 **두 곳에 따로** 기록되고 있었다.

      * `auction.has_*_pdf`  : doc_worker가 수집에 성공할 때마다 갱신 (살아있는 경로)
      * `document_status`    : `collect_documents.py`만 갱신 (어떤 스케줄러도 실행하지 않음)

    그런데 화면이 읽는 것은 **후자**다(`GET /api/v1/item/{id}`의 `documents`).
    그래서 PDF를 이미 받아 둔 물건도 상세 화면에서 계속 "수집중"으로 보였다.

        실측 2026-08-11: has_spec_pdf=1인 197건 중 192건이 document_status != READY
        디스크에 파일이 있는 (법원,사건,물건) 조합 200개 vs READY 14개

    doc_worker가 성공/실패를 기록할 때 같은 트랜잭션에서 이 테이블도 갱신하면
    두 기록이 갈라질 여지가 없어진다.
    """
    ds_type = QUEUE_TO_DOC_STATUS_TYPE.get(doc_type)
    if not ds_type:
        logger.warning("document_status 갱신 생략: 알 수 없는 doc_type=%r", doc_type)
        return False

    # 큐는 (court_code, case_no, item_no)로, document_status는 auction_item.id로 식별한다.
    # 조회는 `_document_status_item_id()` 하나가 담당한다(읽기 쪽과 같은 경로 — Sprint 78).
    item_id = _document_status_item_id(conn, court_code, case_no, item_no)
    if item_id is None:
        # 큐에는 있는데 auction_item에 없는 경우. 조용히 넘기면 왜 상태가 안 변하는지
        # 추적할 수 없으므로 반드시 남긴다.
        logger.warning("document_status 갱신 대상 없음 (법원=%s, 사건=%s, 물건=%s)",
                       court_code, case_no, item_no)
        return False

    conn.execute(
        """
        INSERT OR REPLACE INTO document_status (item_id, doc_type, status, updated_at)
        VALUES (?, ?, ?, ?)
        """,
        (item_id, ds_type, status, datetime.now().isoformat()),
    )
    return True


def _sha256_file(path: str) -> str:
    """파일 해시. 읽지 못하면 빈 문자열(해시를 못 구한 것이 저장 실패 사유는 아니다)."""
    import hashlib
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def _pdf_page_count(path: str) -> Optional[int]:
    """PDF 쪽수. PDF가 아니거나 읽지 못하면 None.

    None과 0을 구분한다 — 0은 "0쪽짜리 PDF"라는 거짓말이 되고(뷰어가 페이지 이동을
    아예 못 그린다), None은 "아직 모른다"이다. `collect_documents.py:save_doc_raw()`의
    옛 구현은 예외를 0으로 뭉갰는데 같은 실수를 반복하지 않는다.
    """
    if not path.lower().endswith(".pdf"):
        return None
    try:
        import pdfplumber
    except ImportError:
        logger.debug("pdfplumber 없음 - page_count 생략")
        return None
    try:
        with pdfplumber.open(path) as pdf:
            return len(pdf.pages)
    except Exception as e:
        logger.warning("page_count 계산 실패 (%s): %s", path, str(e))
        return None


def to_relative_storage_path(path: str) -> str:
    """저장 경로를 **프로젝트 루트 기준 상대경로**로 바꾼다.

    절대경로를 DB에 넣으면 배포 위치가 바뀌는 순간 전 행이 못 쓰게 된다 — 이 저장소는
    실제로 `.bat`/Task Scheduler가 존재하지 않는 절대경로를 들고 있어 매일 배치가
    실패한 적이 있다(docs/CLAUDE.md "경로 통합 완료"). 같은 함정을 DB에 옮기지 않는다.
    루트 밖의 경로면 어쩔 수 없이 원본을 그대로 둔다(추측해서 잘라내지 않는다).
    """
    import os as _os
    root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    try:
        rel = _os.path.relpath(path, root)
    except ValueError:
        return path
    if rel.startswith(".."):
        return path
    return rel.replace("\\", "/")


# doc_raw 버전 경합 재계산 상한 (2026-08-25, docs/BUGS.md #199).
# `claim_next_queue_item()` 의 CLAIM_RACE_MAX_ATTEMPTS 와 같은 취지 -
# 경쟁자가 계속 이겨도 한 호출이 영원히 머물지 않게 한다.
DOC_RAW_VERSION_RACE_ATTEMPTS = 4


def record_doc_raw_row(conn, item_id: int, ds_type: str,
                       files_saved: Optional[List[str]], now: str,
                       primary_ext: Optional[str] = None) -> str:
    """`doc_raw` 한 행을 기록하는 **유일한 규칙**. 커밋하지 않는다.

    돌려주는 값 —

        ""            새 행을 넣었다
        "unchanged"   내용이 직전 버전과 같아 넣지 않았다. **성공이다**
        그 밖의 문자열  기록하지 못했다(사유). **실패로 다뤄야 한다**

    ## 왜 이 함수가 따로 생겼나 (2026-08-25, docs/BUGS.md #197)

    `doc_raw` 에 쓰는 곳이 **둘**이었고 규칙이 갈라져 있었다.

        storage.database._record_doc_raw()     doc_worker 경로 (스케줄러가 도는 쪽)
        collect_documents.save_doc_raw()       손으로 돌리는 진입점

    사본 DB 에 두 함수를 나란히 눌러 재 보니(2026-08-25):

        같은 파일로 두 번 저장   _record_doc_raw  -> 행 1개 (내용 지문 비교로 건너뜀)
                                 save_doc_raw     -> **행 2개** (MAX(doc_version)+1 무조건)
        storage_path 표기        _record_doc_raw  -> documents/남양주지원/.../spec.pdf
                                 save_doc_raw     -> **절대경로 그대로** (배포 위치가 바뀌면 못 쓴다)

    앞의 것은 BUGS #115/#187 이 한쪽에서만 고친 결함 그대로다 — `api/v1/item.py` 가
    `MAX(doc_version)` 을 사용자 응답에 실으므로, 손으로 두 번 돌리면 내용이 한 글자도
    안 바뀌었는데 화면의 문서 버전이 오른다.

    뒤의 것은 이 저장소가 명시한 규약 위반이다(`storage/database.py` 머리 주석,
    `to_relative_storage_path()` docstring). 지금 이 PC 에서는 `os.path.join()` 이
    절대경로를 그대로 돌려주는 덕에 우연히 열리지만, 배포 위치가 바뀌면 그 행들만
    통째로 못 쓰게 된다. 실측: 운영 `doc_raw` 556행은 **전부 상대경로**다(아직 안전).

    규칙을 두 벌 두는 대신 **한 벌만 두고 둘 다 그것을 부른다.** 이 저장소가
    `claim_next_item_rows()` 에서 이미 택한 판단과 같다 — *"그 어휘가 두 곳에 생기면
    한쪽만 고쳐지는 날이 온다."*
    """
    import os as _os

    if not files_saved:
        return "저장했다는 파일 목록이 비어 있다"

    primary = None
    if primary_ext:
        primary = next((p for p in files_saved
                        if p and p.lower().endswith("." + primary_ext)), None)
    if primary is None:
        primary = next((p for p in files_saved if p), None)
    if primary is None:
        return "저장했다는 파일 목록이 비어 있다"

    try:
        size = _os.path.getsize(primary)
    except OSError:
        return "저장했다는 파일이 실제로 없다 (%s)" % primary
    if size <= 0:
        return "0바이트 파일 (%s)" % primary

    new_hash = _sha256_file(primary)
    # ★ 버전 계산과 INSERT 사이가 경쟁 구간이다 (2026-08-25, docs/BUGS.md #199).
    #
    #   `latest` 를 읽고 `version = latest + 1` 을 계산한 다음 INSERT 하기까지 사이에
    #   다른 실행이 같은 (item, doc_type) 을 넣으면 **UNIQUE(item_id, doc_type,
    #   doc_version) 에 걸려 IntegrityError 가 올라간다.** 합성 물건에 스레드 4개로
    #   재현했다(2026-08-25): 성공 1 / IntegrityError 3.
    #
    #   `mark_queue_done()` 은 claim 을 빼앗긴 실행에 대해 *"나중에 그쪽 실행이 같은
    #   값을 다시 써도 결과는 같다(멱등)"* 이라고 적어 두었는데, 실제로는 멱등이 아니라
    #   **예외**였다. 도달 경로는 BUGS #181 이 서술한 좀비 워커다 — stale 회수로 행을
    #   빼앗긴 실행이 뒤늦게 종결하는 동안 새 실행이 같은 문서를 처리하는 경우.
    #   그때 예외가 호출부까지 올라가면 **실제로 받아 놓은 문서가 실패로 기록되고**
    #   다시 수집된다(손상은 아니지만 거짓 실패 + 헛수집이다).
    #
    #   그래서 경쟁에서 밀리면 **다시 읽고 다시 센다.** 다시 읽었을 때 상대가 이미
    #   같은 내용을 넣어 두었으면 그것이 곧 "unchanged" 다 — 둘이 같은 문서를 받은
    #   것이므로 그 답이 정확하다. 상한을 두는 이유는 `claim_next_queue_item()` 과
    #   같다: 경쟁자가 계속 이겨도 이 호출이 영원히 여기 머물면 안 된다.
    # ★ 아래 루프는 경쟁에서 밀리면 다시 돈다. 파일을 다시 여는 계산은
    #   **루프 밖에서 한 번만** 한다 - `_pdf_page_count()` 는 259쪽짜리
    #   감정평가서를 pdfplumber 로 여는 비용이라(실측: appraisal 최대 259쪽)
    #   재시도마다 반복하면 경합이 곧 지연이 된다. 값은 재시도해도 같다.
    rel_path = to_relative_storage_path(primary)
    page_count = _pdf_page_count(primary)
    crawl_day = datetime.now().strftime("%Y-%m-%d")

    for attempt in range(DOC_RAW_VERSION_RACE_ATTEMPTS):
        latest = conn.execute(
            "SELECT doc_version, file_hash FROM doc_raw WHERE item_id=? AND doc_type=?"
            " ORDER BY doc_version DESC LIMIT 1",
            (item_id, ds_type)
        ).fetchone()

        # 내용이 바뀌지 않았으면 새 행을 쌓지 않는다 (2026-08-17 Sprint 187).
        #
        # 재수집을 켜면(overwrite=True) `mark_queue_done()`이 매번 성공으로 호출되고, 그때마다
        # 여기가 무조건 새 doc_raw 행을 만들며 doc_version을 1씩 올렸다 — 내용이 한 글자도
        # 안 바뀌어도 그랬다. `document_version_log`는 `previous_hash != new_hash`로 이미
        # 이 구분을 하는데(storage/database.py:mark_queue_done), 같은 함수가 여는 같은
        # 트랜잭션 안에서 `doc_raw`만 무조건 증가시켰다 — 이미지의 BUGS #113과 같은 계열:
        # "계약은 같은데 한쪽만 변경 감지를 실제로 하지 않는다."
        #
        # `api/v1/item.py`가 MAX(doc_version)을 그대로 `doc_version`으로 응답에 실어 사용자에게
        # 노출하므로, 이 결함은 잠재 상태로 있다가 문서 재수집이 켜지는 순간 "매일 밤 버전이
        # 오르는" 형태로 사용자에게 드러난다.
        #
        # 비교는 이 함수가 방금 계산한 `new_hash`(저장할 파일의 sha256) 대 직전 doc_raw 행의
        # `file_hash`로 한다 — 호출부가 넘기는 previous/new 해시에 기대지 않는다. 그 값들은
        # 크롤러 계층이 doc_type마다 각자 계산해 넘기는 것이라 여기 대표 파일과 반드시 같은
        # 파일을 가리킨다는 보장이 없다(예: status는 html+json 두 파일을 저장하고 대표는 json).
        if latest is not None and latest["file_hash"] and latest["file_hash"] == new_hash:
            return "unchanged"

        version = (latest["doc_version"] + 1) if latest is not None else 1

        try:
            conn.execute(
                """
                INSERT INTO doc_raw
                    (item_id, doc_type, storage_path, file_hash, file_size,
                     doc_version, page_count, crawl_date, created_at)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (item_id, ds_type, rel_path, new_hash,
                 size, version, page_count, crawl_day, now),
            )
        except sqlite3.IntegrityError:
            # 경쟁에서 밀렸다. SQLite 는 제약 위반 시 **그 문장만** 되돌리므로
            # 바깥 트랜잭션은 살아 있다 — 다시 읽고 다시 센다.
            logger.debug("doc_raw 버전 경합 (item_id=%s, doc_type=%s, version=%s) - 재계산 %d/%d",
                         item_id, ds_type, version, attempt + 1, DOC_RAW_VERSION_RACE_ATTEMPTS)
            continue
        return ""

    # 상한까지 밀렸다. **조용히 성공했다고 말하지 않는다** — 호출부가 판단하도록 사유를 준다.
    logger.warning(
        "doc_raw 버전 경합이 %d회 계속됐다 (item_id=%s, doc_type=%s) - 기록하지 못했다"
        "(동시 실행 중인 워커가 있는지 확인할 것)",
        DOC_RAW_VERSION_RACE_ATTEMPTS, item_id, ds_type)
    return ("doc_raw 버전 경합이 %d회 계속돼 기록하지 못했다"
            % DOC_RAW_VERSION_RACE_ATTEMPTS)

def _record_doc_raw(conn, court_code: str, case_no: str, item_no: str, doc_type: str,
                    files_saved: Optional[List[str]], now: str) -> None:
    """수집에 성공한 문서의 실체 정보를 `doc_raw`에 남긴다.

    `mark_queue_done()`이 여는 트랜잭션 안에서 호출된다(커밋하지 않는다).

    설계상의 선택 두 가지 —

    1. **파일이 실제로 없으면 아무것도 쓰지 않는다.** 이 저장소가 반복해서 잡아 온
       결함이 정확히 "DB는 완료라는데 파일이 없다"이므로, 기록의 근거를 파일 자체에
       둔다(`os.path.getsize()`가 성공해야 한다). 파일이 없으면 경고만 남기고
       `doc_raw` 행을 만들지 않는다 — 큐/상태는 이미 done/READY로 갔지만, 그것은
       파일이 있는지 아직 안 본 상위 계층의 판단이고 여기서 뒤집지는 않는다
       (뒤집으려면 `collect_document()`의 성공 판정을 고쳐야 한다).
    2. **여러 파일 중 대표 하나만 기록한다.** `doc_raw`는 (item, doc_type)당 1행
       구조다. status는 html+json 두 개를 저장하는데, 그중 완성 판정 기준 파일
       (`doc_paths._PRIMARY_EXT` = json)이 대표다. 규칙을 여기서 새로 만들지 않고
       그 모듈의 판정을 그대로 따른다.
    """
    import os as _os

    if not files_saved:
        return

    item_id = _document_status_item_id(conn, court_code, case_no, item_no)
    if item_id is None:
        logger.warning("doc_raw 기록 대상 없음 (법원=%s, 사건=%s, 물건=%s)",
                       court_code, case_no, item_no)
        return

    ds_type = QUEUE_TO_DOC_STATUS_TYPE.get(doc_type)
    if not ds_type:
        logger.warning("doc_raw 기록 생략: 알 수 없는 doc_type=%r", doc_type)
        return

    # 사진은 `auction_image`가 담당한다 — doc_raw는 (item, doc_type)당 1행이라
    # 0~N장인 사진을 담을 수 없다(migration 020의 주석 참고).
    if doc_type == "image":
        return

    try:
        from crawler.doc_paths import _PRIMARY_EXT
        primary_ext = _PRIMARY_EXT.get(doc_type)
    except Exception:
        primary_ext = None

    # ★ 기록 규칙은 `record_doc_raw_row()` 한 곳에만 있다 (2026-08-25, BUGS #197).
    #   예전에는 같은 규칙이 `collect_documents.save_doc_raw()` 에도 따로 있었고
    #   실제로 갈라져 있었다(그쪽은 내용 지문 비교가 없어 매번 버전을 올렸고,
    #   경로도 절대경로로 넣었다). 어휘를 두 벌 두지 않는다.
    reason = record_doc_raw_row(conn, item_id, ds_type, files_saved, now, primary_ext)
    if reason == "unchanged":
        logger.info("doc_raw 기록 생략: 내용 변경 없음 (item_id=%s, doc_type=%s)",
                    item_id, ds_type)
    elif reason:
        logger.warning("doc_raw 기록 생략: %s", reason)


def save_auction_images(court_code: str, case_no: str, item_no: str,
                        images: List[Dict], complete: bool = True) -> Dict:
    """수집한 물건 사진들을 `auction_image`에 기록한다.

    `images`의 각 항목: {"seq", "kind", "path", "file_size", "file_hash",
                        "width", "height"}

    - **디스크에 실제로 없는 항목은 기록하지 않는다.** (DB만 앞서가는 것을 막는 이 저장소의 규약)
    - `INSERT OR REPLACE`로 `UNIQUE(item_id, seq)`에 얹는다 — 같은 물건을 두 번
      처리해도 사진이 두 벌 쌓이지 않는다(중복 자산 방어).
    - **이번에 받지 못한 순번의 옛 행은 지운다.** 법원이 사진을 5장에서 3장으로 줄이면
      옛 4,5번 행이 남아 화면이 없는 사진을 가리키게 된다.
      (2026-08-18 Sprint 191: `seq > max_seq` 였던 것을 **집합 차집합**으로 바꿨다 —
       가운데 순번이 빠지는 경우를 `>` 비교는 못 잡았다.)
    - 단 `complete=False`(부분 수집)면 **지우지 않는다** (2026-08-17 Sprint 186).
      이 함수만 보면 "법원이 5장에서 3장으로 줄였다"와 "5장 중 3장만 받아졌다"가
      똑같이 보인다 — 둘 다 순번 3까지만 들어온다. 그런데 결과는 정반대다.

          법원이 줄였다   -> 옛 4,5번을 지우는 것이 맞다(없는 사진을 가리키므로)
          일부만 받아졌다 -> 지우면 **사용자가 보던 사진 2장이 사라지고**,
                            그 파일들은 디스크에 고아로 남는다

      구별할 수 있는 것은 호출부다(`collect_images` 가 돌려주는 `partial`).
      판단할 수 없을 때는 **남기는 쪽**이 안전하다 — 남은 행은 여전히 실제 파일을
      가리키고 다음 정상 수집에서 정리되지만, 지운 행은 되돌릴 수 없다.

    돌려주는 값: {"saved": n, "skipped_missing": n, "removed_stale": n}
    """
    import os as _os

    conn = get_connection()
    saved = 0
    skipped = 0
    removed = 0
    try:
        item_id = _document_status_item_id(conn, court_code, case_no, item_no)
        if item_id is None:
            logger.warning("auction_image 기록 대상 없음 (법원=%s, 사건=%s, 물건=%s)",
                           court_code, case_no, item_no)
            return {"saved": 0, "skipped_missing": len(images or []), "removed_stale": 0}

        now = datetime.now().isoformat()
        today = datetime.now().strftime("%Y-%m-%d")
        max_seq = 0
        saved_seqs = set()   # 이번에 실제로 기록한 순번 — 옛 행 정리의 기준

        for img in (images or []):
            path = img.get("path")
            seq = img.get("seq")
            if not path or not isinstance(seq, int):
                skipped += 1
                continue
            try:
                size = _os.path.getsize(path)
            except OSError:
                logger.warning("auction_image 기록 생략: 파일이 없다 (%s)", path)
                skipped += 1
                continue
            # ★ "있다"의 기준을 **읽는 쪽과 같게** 맞춘다 (2026-08-19 Sprint 218, BUGS #148).
            #
            #   예전에는 `size <= 0` 만 봤다. 그런데 이 사진을 실제로 내주는 쪽은
            #   `MIN_IMAGE_BYTES`(1,024) 미만을 **404 로 거절한다**
            #   (`api/v1/images.py`, `crawler/image_assets.image_exists()`).
            #   즉 1~1,023바이트 파일은 이렇게 끝났다:
            #
            #       auction_image 에 행이 생긴다
            #       -> API image_count=1 / images_status=READY / 대표 URL 을 준다
            #       -> 검색 목록도 그 URL 을 썸네일로 준다
            #       -> 그 URL 은 404          <- 화면은 있다는데 열면 없다
            #
            #   `image_exists()` 의 docstring 이 이미 적어 둔 규약이다 —
            #   *"쓰는 쪽과 읽는 쪽의 '있다' 정의가 갈라지면 화면은 READY 인데 뷰어는
            #   404 가 된다"*. 정작 **행을 만드는 이 함수만** 그 규약 밖에 있었다.
            #
            #   수집기는 이미 같은 하한으로 걸러내므로(`len(data) < MIN_IMAGE_BYTES`)
            #   정상 경로의 동작은 바뀌지 않는다. 실측(2026-08-19): 운영 45행의
            #   최소 크기는 35,746바이트로 **영향받는 행 0건**이다.
            #   여기서 막는 것은 잘린 파일·수동 조작·옛 backfill 이 남길 수 있는 행이다.
            from crawler.image_assets import MIN_IMAGE_BYTES as _MIN_IMAGE_BYTES
            if size < _MIN_IMAGE_BYTES:
                logger.warning(
                    "auction_image 기록 생략: 너무 작다 %d바이트 < %d (%s) "
                    "- 기록하면 화면은 사진이 있다고 하는데 서빙은 404 가 된다",
                    size, _MIN_IMAGE_BYTES, path)
                skipped += 1
                continue

            conn.execute(
                """
                INSERT OR REPLACE INTO auction_image
                    (item_id, seq, kind, storage_path, file_hash, file_size,
                     width, height, crawl_date, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (item_id, seq, img.get("kind"), to_relative_storage_path(path),
                 img.get("file_hash") or "", size,
                 img.get("width"), img.get("height"), today, now),
            )
            saved += 1
            saved_seqs.add(seq)
            max_seq = max(max_seq, seq)

        # `complete=False` 면 지우지 않는다 — 위 docstring 참고.
        # `saved` 가 0일 때도 지우지 않는다(전체 실패로 기존 사진을 잃는 것을 막는다).
        if saved and complete:
            # ★ `seq > max_seq` 가 아니라 **집합 차집합**이다 (2026-08-18 Sprint 191).
            #   법원이 가운데 순번을 빼는 경우(1,2,4 만 제공)를 `>` 비교는 못 잡아
            #   3번 행이 살아남고, 그 행이 가리키는 파일은 이미 사라져 있다
            #   (= 화면은 있다는데 열면 404, 이 저장소가 반복해 잡아 온 어긋남).
            #   `crawler/image_crawler.py:_remove_files_not_in()`이 파일 쪽을 **같은
            #   기준**으로 정리하므로, 두 근거(DB/파일시스템)가 갈라지지 않는다.
            placeholders = ", ".join("?" * len(saved_seqs))
            cur = conn.execute(
                "DELETE FROM auction_image WHERE item_id=? AND seq NOT IN ("
                + placeholders + ")",
                (item_id,) + tuple(sorted(saved_seqs)))
            removed = cur.rowcount or 0
        elif saved and not complete:
            logger.warning(
                "[%s-%s] 부분 수집이라 옛 사진 행을 지우지 않는다 (저장 %d장, 최대 순번 %d)",
                case_no, item_no, saved, max_seq)

        conn.commit()
        return {"saved": saved, "skipped_missing": skipped, "removed_stale": removed}
    finally:
        conn.close()


# 2026-08-17 Sprint 150 (Architecture/Debt Audit): `get_auction_images(item_id)`를 제거했다.
#
# Sprint 144에 이미지 계층을 만들면서 "API 전용 조회" 헬퍼로 추가했는데 **끝내 아무도
# 부르지 않았다**(저장소 전체 참조 0건 — 테스트 포함). 실제로 사진을 읽는 곳은
# `api/v1/item.py:58`이고, 거기서 같은 SQL을 인라인으로 실행한다.
#
# 남겨 둘 이유가 없다. 이 저장소는 리포지토리/서비스 계층 없이 **라우터가
# get_connection()으로 직접 조회하는 구조**이므로(docs/CLAUDE.md Architecture),
# 이 헬퍼만 홀로 다른 규칙을 따르고 있었다. 즉 죽은 코드이면서 동시에 구조에서도
# 이례였다. 남겨 두면 "여기에 조회 계층이 있다"는 잘못된 신호를 준다.
#
# 사진 조회 SQL이 여러 곳에 필요해지면 그때 이 규칙 자체를 바꾸는 것이 맞다.


def clear_images_if_absence_confirmed(court_code: str, case_no: str,
                                      item_no: str) -> Dict:
    """법원이 사진을 **전부** 내린 것이 확인되면 옛 사진 기록을 정리한다.

    2026-08-18 Sprint 191 (BUGS #128). 사진 감소는 `save_auction_images()`가 처리하는데,
    **0장으로 줄어드는 경우만 그 함수에 도달하지 않는다** — `doc_worker`가
    `if result.get("images")` 로 가드하기 때문이다(빈 목록으로 부르면 전체 실패와
    구별되지 않으니 그 가드 자체는 옳다). 그 결과:

        법원이 사진을 전부 내림
          -> collect_images: no_asset=True, images=[]
          -> document_status = NO_IMAGE            (상태만 바뀐다)
          -> auction_image 행/파일은 **그대로 남는다**
          -> _images_status() 는 "행이 있으면 무조건 READY" 이므로 **READY** 를 답한다
          -> 사용자는 법원이 내린 사진을 계속 본다. 영원히.

    ## 한 번 못 봤다고 지우지 않는다

    "법원이 내렸다"와 "이번 관측이 실패했다"는 한 번의 관측으로 구별할 수 없다.
    그리고 이 파이프라인에서 **가장 파괴적인 동작**이 사용자가 보던 사진을 전부 지우는
    것이다. 그래서 **두 번 연속 확인**을 요구한다:

        1회차: document_status 가 READY -> NO_IMAGE 로 바뀐다. 사진은 남긴다.
        2회차: 이미 NO_IMAGE 인데 또 no_asset 이다 -> 그때 정리한다.

    새 컬럼이 필요 없다 — `document_status` 자체가 1회차를 기억한다.
    (부분 수집 보호가 "판단할 수 없을 때는 남기는 쪽"을 택한 것과 같은 원칙이다.)

    ★ `mark_queue_done()` **보다 먼저** 불러야 한다. 그 함수가 상태를 NO_IMAGE 로
      덮어쓰고 나면 1회차인지 2회차인지 알 수 없게 된다.

    돌려주는 값:
        {"cleared": 지운 행 수, "paths": 지워야 할 파일 절대경로들,
         "first_sighting": 1회차라 이번에는 남겼는가}
    """
    conn = get_connection()
    try:
        item_id = _document_status_item_id(conn, court_code, case_no, item_no)
        if item_id is None:
            return {"cleared": 0, "paths": [], "first_sighting": False}

        rows = conn.execute(
            "SELECT seq, storage_path FROM auction_image WHERE item_id=? ORDER BY seq",
            (item_id,)).fetchall()
        if not rows:
            return {"cleared": 0, "paths": [], "first_sighting": False}

        current = _current_document_status(conn, court_code, case_no, item_no, "image")
        if current != "NO_IMAGE":
            # 1회차 — 상태만 바뀌게 두고(호출부의 mark_queue_done 이 한다) 사진은 남긴다.
            logger.warning(
                "[%s-%s] 법원 원천에 사진이 없다고 관측됐지만 우리는 %d장을 갖고 있다 "
                "- 이번에는 지우지 않는다(다음 수집에서 한 번 더 확인되면 정리)",
                case_no, item_no, len(rows))
            return {"cleared": 0, "paths": [], "first_sighting": True}

        paths = [os.path.join(PROJECT_ROOT, r["storage_path"])
                 for r in rows if r["storage_path"]]
        cur = conn.execute("DELETE FROM auction_image WHERE item_id=?", (item_id,))
        conn.commit()
        logger.warning("[%s-%s] 법원이 사진을 전부 내린 것이 두 번 연속 확인됐다 "
                       "- 옛 사진 %d장 정리", case_no, item_no, cur.rowcount or 0)
        return {"cleared": cur.rowcount or 0, "paths": paths, "first_sighting": False}
    finally:
        conn.close()


def claim_next_queue_item() -> Optional[Dict]:
    """
    대기 상태('pending'/'refresh') -> 대응하는 진행 상태 원자적 클레임.
    UPDATE ... WHERE status=<집어갈 때 본 그 값> 조건으로 동시성 문제를 방지하고,
    성공(rowcount>0) 했을 때만 그 항목을 반환한다.
    커밋 후 즉시 커넥션을 닫아 락을 짧게 유지한다(다운로드 작업 중에는 DB를 잠그지 않음).

    ## 돌려주는 `overwrite` (2026-08-18 Sprint 189)

    'refresh'는 **이미 받아 둔 것이 있는데 다시 받아야 한다**는 뜻이다. 그대로 넘기면
    수집기의 "이미 존재. 스킵" 분기에 걸려 아무 일도 일어나지 않으므로,
    `collect_document(..., overwrite=True)`로 가야 한다. 그 판단을 doc_worker가 다시
    하지 않도록(어휘가 두 곳에 복제되는 것을 막는다) 여기서 계산해 키로 넘긴다.

    ★ 정렬은 바꾸지 않는다. 재수집을 먼저 처리하도록 순서를 뒤집고 싶어지지만,
      `priority`는 매각기일 임박도에서 계산된 값이라 이미 제품이 정한 중요도다.
      재수집을 앞세우면 **한 번도 수집된 적 없는 임박 물건**이 뒤로 밀린다.
      재수집 총량은 `REFRESH_MAX_ITEMS_PER_RUN`으로 따로 제한한다.
    """
    conn = get_connection()
    try:
        for attempt in range(CLAIM_RACE_MAX_ATTEMPTS):
            row = conn.execute("""
                SELECT id, court_code, case_no, item_no, doc_type, retry_count, auction_date, status
                FROM document_queue
                WHERE status IN (""" + QUEUE_CLAIMABLE_PLACEHOLDERS + """)
                  AND (
                        last_attempt_at IS NULL
                        OR datetime(last_attempt_at) <= datetime(""" + _NOW_LOCAL + """, '-""" + str(RETRY_INTERVAL_MINUTES) + """ minutes')
                  )
                ORDER BY priority ASC, auction_date ASC
                LIMIT 1
            """, QUEUE_CLAIMABLE_STATUSES).fetchone()
            if not row:
                return None           # 진짜로 가져갈 것이 없다

            waiting_status = row["status"]
            claimed_status = QUEUE_CLAIM_STATUS[waiting_status]

            now = datetime.now().isoformat()
            cur = conn.execute("""
                UPDATE document_queue
                SET status=?, last_attempt_at=?
                WHERE id=? AND status=?
            """, (claimed_status, now, row["id"], waiting_status))
            conn.commit()

            if cur.rowcount:
                item = dict(row)
                item["status"] = claimed_status
                item["overwrite"] = claimed_status in QUEUE_OVERWRITE_STATUSES
                # ★ claim 토큰 (2026-08-24 Sprint 254, BUGS #181).
                #   방금 우리가 써 넣은 `last_attempt_at` 이다. 종결할 때 이 값을 다시
                #   걸어 **그때 집은 그 claim 이 아직 살아 있는지** 확인한다.
                #   상태만으로는 구별할 수 없다 - 회수 후 다른 실행이 다시 집어도
                #   상태는 똑같이 'in_progress' 이기 때문이다. 스키마는 건드리지 않는다.
                item["claim_token"] = now
                return item

            # ★ 여기 도달 = **경쟁에서 졌다**. 큐가 빈 것이 아니다
            #   (2026-08-18 Sprint 191, BUGS #130).
            #
            #   예전에는 여기서 곧바로 None 을 돌려줬다. 그런데 호출부(`doc_worker.main()`)는
            #   None 을 "대기열 비어있음"으로 읽고 **그 실행 전체를 끝낸다.** 즉 claim 충돌
            #   한 번이 그날 남은 큐를 통째로 다음 날로 미룬다. 로그에도 "대기열 비어있음"
            #   이라는 **사실이 아닌 문장**이 남는다(BUGS #47 계열).
            #
            #   실측(2026-08-18, 스레드 12 / 대기 행 4): 중복 claim 은 0건으로 방어가
            #   정상 동작했지만, **행이 아직 남아 있는데 None 을 받은 스레드가 9개**였다.
            #
            #   진 쪽은 다른 행을 집으면 된다 — 다시 조회한다. 상한을 두는 이유는
            #   무한 루프를 만들지 않기 위해서다(경쟁자가 계속 이기는 상황에서도 이 실행이
            #   영원히 여기 머물면 안 된다). 상한에 걸리면 None 을 돌려주되 **왜인지를
            #   로그에 남긴다** — 그래야 "비었다"와 구별된다.
            logger.debug("claim 경쟁에서 밀렸다(id=%s) - 다시 시도 %d/%d",
                         row["id"], attempt + 1, CLAIM_RACE_MAX_ATTEMPTS)

        logger.warning(
            "claim 을 %d회 시도했지만 매번 다른 실행에 밀렸다 - 이번에는 비우고 돌아간다"
            "(큐가 빈 것이 아니다. 동시 실행 중인 워커가 있는지 확인할 것)",
            CLAIM_RACE_MAX_ATTEMPTS)
        return None
    finally:
        conn.close()


# 한 물건에서 한 번에 집어 오는 최대 행 수.
#
# 정상 상태에서는 doc_type 종류 수(현재 4)가 자연 상한이다 — migration 018 의
# UNIQUE(court_code, case_no, item_no, doc_type) 가 같은 종류의 중복 적재를 막는다.
# 그래도 고정 상한을 두는 이유는, 그 제약이 없던 시절에 적재된 행이나 스키마가
# 손상된 DB 에서 **한 실행이 한 물건에 무한정 붙들리지 않게** 하기 위해서다.
QUEUE_BATCH_MAX_ROWS = 8


def claim_next_item_rows(max_rows: int = QUEUE_BATCH_MAX_ROWS) -> List[Dict]:
    """**한 물건**(법원+사건+물건번호)의 처리 가능한 큐 행을 한꺼번에 집어 온다.

    ## 왜 필요한가 (2026-08-20 Sprint 236, BUGS #173)

    `doc_worker` 는 큐 행을 하나씩 집어 **행마다** `go_to_case_detail()` 을 불렀다.
    같은 물건의 4종(spec/status/appraisal/image)을 받으려고 같은 상세페이지에
    **네 번** 들어간 것이다. 이동 1회는 실측 중앙값 10.9초인데, 사진 수집 자체는
    0.0초다(DOM 을 그대로 읽는다). 즉 비용의 거의 전부가 중복 이동이었다.

    이 함수는 **claim 단위만** 행 -> 물건으로 바꾼다. 그 외에는 아무것도 바꾸지 않는다:

        재시도 예산      행마다 그대로 (`retry_count` 는 행의 것이다)
        성공/실패 기록    행마다 그대로 (`mark_queue_done` / `mark_queue_failed`)
        refresh 보존     행마다 그대로 (`overwrite` 를 행별로 계산한다)
        부분 실패        행마다 그대로 (한 종류가 실패해도 나머지는 각자 종결된다)

    ## 첫 행은 기존 함수가 고른다

    `claim_next_queue_item()` 을 그대로 부른다 — 어떤 행을 먼저 볼지(priority,
    auction_date), 재시도 간격, claim 경쟁에서 밀렸을 때의 재조회까지
    **판단을 여기서 복제하지 않기 위해서다.** 그 어휘가 두 곳에 생기면 한쪽만
    고쳐지는 날이 온다(이 저장소가 BUGS #130 에서 겪은 모양이다).

    ## 형제 행은 **best-effort** 다

    이미 집은 첫 행이 있으므로, 형제 행 claim 이 경쟁에서 밀리면 그냥 빼고 돌아간다
    — 실패가 아니다. 그 행은 이긴 쪽이 처리한다. 여기서 None 을 돌려주면
    Sprint 191 이 고친 결함(경쟁 1회가 그날 큐 전체를 다음 날로 미룸)을 되살린다.

    ## 형제에도 재시도 간격을 똑같이 건다

    30분 전에 실패한 행은 아직 다시 시도할 때가 아니다. 물건을 묶어 온다는
    이유로 그 규칙을 건너뛰면, **같은 실행 안에서 같은 행을 연달아 태워**
    재시도 예산 3회를 몇 분 만에 소진시킨다.

    돌려주는 것: `claim_next_queue_item()` 과 **똑같은 모양의 dict** 목록.
    집을 것이 없으면 빈 목록(호출부는 그것을 "대기열 비어있음"으로 읽는다).
    """
    head = claim_next_queue_item()
    if not head:
        return []

    rows = [head]
    if max_rows <= 1:
        return rows

    conn = get_connection()
    try:
        siblings = conn.execute("""
            SELECT id, court_code, case_no, item_no, doc_type, retry_count, auction_date, status
            FROM document_queue
            WHERE court_code=? AND case_no=? AND item_no=?
              AND id<>?
              AND status IN (""" + QUEUE_CLAIMABLE_PLACEHOLDERS + """)
              AND (
                    last_attempt_at IS NULL
                    OR datetime(last_attempt_at) <= datetime(""" + _NOW_LOCAL + """, '-""" + str(RETRY_INTERVAL_MINUTES) + """ minutes')
              )
            ORDER BY priority ASC, id ASC
            LIMIT ?
        """, (head["court_code"], head["case_no"], head["item_no"], head["id"])
             + tuple(QUEUE_CLAIMABLE_STATUSES) + (max_rows - 1,)).fetchall()

        for row in siblings:
            waiting_status = row["status"]
            claimed_status = QUEUE_CLAIM_STATUS[waiting_status]
            now = datetime.now().isoformat()
            cur = conn.execute("""
                UPDATE document_queue
                SET status=?, last_attempt_at=?
                WHERE id=? AND status=?
            """, (claimed_status, now, row["id"], waiting_status))
            conn.commit()
            if not cur.rowcount:
                # 경쟁에서 밀렸다. 첫 행은 이미 우리 것이므로 이 행만 빼고 진행한다.
                logger.debug("형제 행 claim 경쟁에서 밀렸다(id=%s) - 이번 묶음에서 제외", row["id"])
                continue
            item = dict(row)
            item["status"] = claimed_status
            item["overwrite"] = claimed_status in QUEUE_OVERWRITE_STATUSES
            item["claim_token"] = now      # 머리 행과 같은 규약 (BUGS #181)
            rows.append(item)
    finally:
        conn.close()

    if len(rows) > 1:
        logger.info("[%s-%s] 큐 %d행을 한 묶음으로 집었다(%s) - 상세페이지 이동 1회로 처리한다",
                    head["case_no"], head["item_no"], len(rows),
                    ", ".join(r["doc_type"] for r in rows))
    return rows


def release_queue_rows(queue_ids: List[int]) -> int:
    """집어 두었지만 **한 번도 시도하지 않은** 행을 즉시 대기 상태로 돌려놓는다.

    실행 창이 닫혀 묶음의 뒷부분을 처리하지 못한 경우에 쓴다.

    ★ `retry_count` 를 건드리지 않는다 — 시도하지 않았으니 예산을 깎을 이유가 없다.
      (`reset_stale_queue()` 의 `in_progress` 회수와 같은 규칙이다. 그 함수가 10분 뒤
      해 줄 일을 지금 바로 하는 것뿐이라, 새 정책을 만드는 것이 아니다.)

    ★ `last_attempt_at` 도 건드리지 않는다 — 그 값을 지우면 30분 재시도 간격이
      사라져, 방금 실패한 행이 곧바로 다시 태워질 수 있다. 회수 경로와 동일하게 둔다.
    """
    ids = [int(q) for q in queue_ids]
    if not ids:
        return 0
    conn = get_connection()
    try:
        # ★ SQL 을 문자열로 조립하지 않는다.
        #   `IN (%s)` 로 물음표만 채우는 것은 안전하지만, 이 저장소의 SQL 위생
        #   검사는 그것을 구별할 수 없다(구별하려 들면 검사가 무뎌진다).
        #   한 번에 되돌리는 행은 많아야 QUEUE_BATCH_MAX_ROWS 개라 반복문으로 충분하다.
        released = 0
        for in_progress, back_to in QUEUE_RESUME_STATUS.items():
            for queue_id in ids:
                cur = conn.execute(
                    "UPDATE document_queue SET status=? WHERE status=? AND id=?",
                    (back_to, in_progress, queue_id))
                released += cur.rowcount
        conn.commit()
        if released:
            logger.info("시도하지 않은 큐 %d행을 대기 상태로 돌려놓았다", released)
        return released
    finally:
        conn.close()


def _claim_is_still_ours(conn, queue_id: int, claim_token: Optional[str]) -> bool:
    """이 실행이 집었던 그 claim 이 아직 살아 있는가 (2026-08-24 Sprint 254, BUGS #181).

    `claim_token` 은 claim 시점에 써 넣은 `last_attempt_at` 이다. 그 뒤 누군가
    `reset_stale_queue()` 로 회수하고 다시 집었다면 그 값이 바뀌어 있다.

    ★ 상태(`in_progress`)로는 구별할 수 없다 - 회수 후 다시 집은 행도 `in_progress` 다.
      그래서 토큰이 필요하다. 컬럼을 새로 만들지 않고 이미 있는 값을 쓴다.

    `claim_token` 이 None 이면 **예전 동작 그대로** True 다 - 토큰을 넘기지 않는
    호출부(회귀 테스트 등)의 계약을 바꾸지 않는다.
    """
    if claim_token is None:
        return True
    row = conn.execute(
        "SELECT last_attempt_at FROM document_queue WHERE id=?", (queue_id,)).fetchone()
    return bool(row) and row["last_attempt_at"] == claim_token


def mark_queue_done(queue_id: int, court_code: str, case_no: str, item_no: str, doc_type: str,
                     previous_hash: str, new_hash: str, status: str = "READY",
                     files_saved: Optional[List[str]] = None,
                     claim_token: Optional[str] = None) -> None:
    """큐 항목을 성공으로 종결한다.

    2026-08-17 Sprint 144에 **뒤에 두 개의 선택 인자**가 붙었다. 기존 호출부
    (`doc_worker.py`)는 위치 인자 7개를 그대로 쓰므로 무변경으로 동작한다.

      status       화면(`document_status`)에 쓸 값. 기본 READY.
                   사진 수집이 성공했는데 **법원에 사진이 한 장도 없는** 경우가 실제로
                   있고, 그때 READY로 쓰면 "볼 수 있다"는 거짓말이 된다. 그렇다고
                   FAILED로 쓰면 실패가 아닌 것을 실패로 기록하고 재시도 대상이 된다
                   (`mark_queue_skipped_expired`가 같은 이유로 상태를 안 건드리는 것과
                   같은 고민이다). 호출부가 'NO_IMAGE'를 명시적으로 넘길 수 있게 한다.
      files_saved  이번에 저장한 파일 경로들. `doc_raw`를 채우는 데 쓴다(아래 참고).

    ## `doc_raw`를 여기서 채우는 이유 (Sprint 144에 고친 결함)

    실측: 디스크에 실제 문서가 559개 있고 `document_status` READY가 556행인데
    **`doc_raw`는 0행**이었다. `doc_raw`에 쓰는 코드는 `collect_documents.py`
    (`save_doc_raw()`) 한 곳뿐인데, 그 스크립트는 **어떤 스케줄러도 실행하지 않는다** —
    운영에서 실제로 도는 경로는 `doc_worker.py` -> `collect_document()` -> 이 함수이고,
    이 경로에는 `doc_raw` 기록이 아예 없었다.

    그 결과 `doc_raw`의 file_size / file_hash / page_count / doc_version이 전부
    비어 있어서, API가 "이 문서 몇 쪽인가"를 답할 수 없었다(상세페이지 뷰어의 페이지
    이동이 불가능했던 근본 원인). BUGS #50이 `has_*_pdf`와 `document_status` 사이에서
    고친 것과 **정확히 같은 모양의 결함**이 한 층 아래에 하나 더 있었던 셈이다.

    같은 트랜잭션 안에서 쓴다 — 세 기록(`document_queue` / `document_status` / `doc_raw`)이
    갈라질 여지를 남기지 않는다.
    """
    conn = get_connection()
    try:
        now = datetime.now().isoformat()
        # ★ 우리 claim 이 아직 살아 있을 때만 큐 행을 종결한다 (BUGS #181).
        #
        #   회수당한 뒤라면 그 행은 지금 **다른 실행이 받고 있는 중**이다. 'done' 으로
        #   덮으면 그 실행이 헛돌고(같은 문서를 두 번 받는다), 그쪽이 뒤이어 실패로
        #   종결하면 방금 성공한 문서가 'failed' 로 뒤집힌다.
        #
        #   ★ 그래도 `document_status`/`doc_raw` 는 그대로 쓴다 - 파일은 **실제로**
        #     받아졌기 때문이다. 화면이 그 사실을 반영해야 하고, 나중에 그쪽 실행이
        #     같은 값을 다시 써도 결과는 같다(멱등).
        owns = _claim_is_still_ours(conn, queue_id, claim_token)
        if owns:
            conn.execute("UPDATE document_queue SET status=? WHERE id=?",
                         (QUEUE_STATUS_DONE, queue_id))
        else:
            logger.warning(
                "[%s-%s] %s 수집은 끝났지만 그 사이 큐 행(id=%s)이 회수돼 다른 실행이 "
                "집어갔다 - 큐 상태는 그쪽에 맡기고 문서 기록만 남긴다"
                "(동시 실행 중인 워커가 있는지 확인할 것)",
                case_no, item_no, doc_type, queue_id)

        # ★ 알 수 없는 doc_type은 **여전히 예외로 죽어야 한다.**
        #
        #   예전 코드는 `{...}[doc_type]`이라 모르는 종류에 KeyError를 냈고, 그 덕분에
        #   트랜잭션이 통째로 롤백돼 큐가 거짓 'done'이 되지 않았다
        #   (`test_doc_storage_atomicity.py` §3이 지키는 불변식).
        #   Sprint 144에 'image'를 넣으면서 이것을 `.get()`으로 바꾸면 **오타 난 doc_type이
        #   조용히 성공 처리되어** 수집한 적 없는 문서가 done으로 종결된다 — 고치려던 것보다
        #   나쁜 결함이다. 그래서 "레거시 컬럼이 없는 것"과 "아예 모르는 종류"를 나눈다:
        #   전자(image)만 건너뛰고 후자는 그대로 죽는다.
        if doc_type not in QUEUE_TO_DOC_STATUS_TYPE:
            raise KeyError(doc_type)
        col = LEGACY_HAS_COLUMN.get(doc_type)
        if col:
            conn.execute(
                "UPDATE auction SET " + col + "=1 WHERE court_code=? AND case_no=? AND item_no=?",
                (court_code, case_no, item_no)
            )

        # 화면이 읽는 것은 이 테이블이다 — 같은 트랜잭션에서 함께 갱신해야 두 기록이
        # 갈라지지 않는다 (BUGS #50).
        _set_document_status(conn, court_code, case_no, item_no, doc_type, status)

        _record_doc_raw(conn, court_code, case_no, item_no, doc_type, files_saved, now)

        if previous_hash and previous_hash != new_hash:
            conn.execute("""
                INSERT INTO document_version_log
                    (court_code, case_no, item_no, doc_type, previous_hash, new_hash, file_version, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (court_code, case_no, item_no, doc_type, previous_hash, new_hash, "", now))

        conn.commit()
    finally:
        conn.close()


def _record_collect_failure(conn, row, reason: str) -> None:
    """최종 실패의 **사유**를 `document_collect_failures` 에 남긴다 (2026-09-02).

    ## 왜 필요했나 — 약속이 지켜지지 않고 있었다

    바로 아래 `mark_queue_failed()` 의 주석은 *"이 실행의 실패 사실은 로그와
    `document_collect_failures` 에 이미 남는다"* 고 적어 두고 그것을 근거로 큐 행에
    아무것도 쓰지 않는 선택을 정당화한다. **그런데 그 표에 쓰는 코드가 없었다.**
    전수 확인(2026-09-02): INSERT 하는 곳은 `collect_documents.py` 뿐이고 그 스크립트는
    2026-07-15 이후 돌지 않았다.

    결과 — 실측:
        document_queue     failed 188건 (appraisal 166 · spec 11 · image 6 · status 5)
                           그중 기일이 남아 화면에 보이는 물건 129건
        기록된 사유          0건 (전부 retry_count=3 으로 소진돼 있을 뿐)

    즉 **사용자가 보는 129개 물건의 문서가 왜 없는지 아무도 모른다.** 법원이 안 올린
    것인지, 버튼 DOM 이 바뀐 것인지, 그날 서버가 불안정했던 것인지 구분할 수 없어
    고칠 수도 없다. 이 저장소가 반복해서 경계해 온 "증거 없는 실패"다.

    ## 최종 실패만 남긴다

    중간 재시도까지 남기면 한 문서가 3행을 만든다. 화면 상태를 최종 실패에서만
    바꾸는 것과 같은 기준이다.
    """
    # ★ 기록은 **최선 노력**이다 — 여기서 예외가 나가면 큐 상태 전이가 통째로 죽는다.
    #
    #   사유를 못 남기는 것보다 큐가 망가지는 것이 훨씬 나쁘다. 실제로 이 함수를 처음
    #   넣었을 때 `document_collect_failures` 가 없는 DB(마이그레이션 017 이전 스키마로
    #   부트스트랩한 테스트 환경)에서 `no such table` 이 그대로 올라와
    #   `mark_queue_failed()` 전체가 실패했다. 운영에서 같은 일이 나면 실패한 문서가
    #   `in_progress` 로 굳어 다음 실행이 집지도 못한다.
    try:
        item = conn.execute(
            "SELECT id FROM auction_item WHERE case_no=? AND item_no=?",
            (row["case_no"], row["item_no"])).fetchone()
        if not item:
            # 큐 행은 있는데 물건이 없다 — 표의 FK 대상이 없으므로 남기지 않는다.
            logger.warning("실패 사유를 남기지 못했다 - auction_item 없음 (%s-%s)",
                           row["case_no"], row["item_no"])
            return
        conn.execute("""
            INSERT INTO document_collect_failures (item_id, doc_type, error_message, created_at)
            VALUES (?,?,?,?)
        """, (item["id"], row["doc_type"], (reason or "사유 미기록")[:500],
              datetime.now().isoformat()))
    except sqlite3.Error as exc:
        logger.warning("실패 사유를 남기지 못했다(%s: %s) - 큐 전이는 계속한다",
                       type(exc).__name__, exc)


def mark_queue_failed(queue_id: int, retry_count: int,
                      claim_token: Optional[str] = None,
                      reason: Optional[str] = None) -> None:
    conn = get_connection()
    try:
        # ★ 우리 claim 이 아직 살아 있을 때만 손댄다 (2026-08-24 Sprint 254, BUGS #181).
        #
        #   성공 쪽(`mark_queue_done`)과 달리 여기서는 **아무것도 쓰지 않는다.**
        #   회수 뒤 다시 집힌 행을 실패로 처리하면
        #     - 지금 받고 있는 실행의 claim 이 'pending' 으로 풀려 제3의 실행이 또 집고
        #     - 그 실행의 몫이 아닌 `retry_count` 가 깎이며
        #     - 그쪽이 성공할 문서가 잠깐 화면에서 '수집실패' 로 보인다.
        #   이 실행의 실패 사실은 로그와 `document_collect_failures` 에 이미 남는다.
        if not _claim_is_still_ours(conn, queue_id, claim_token):
            logger.warning(
                "실패 처리를 건너뛴다(id=%s) - 그 사이 큐 행이 회수돼 다른 실행이 집어갔다. "
                "이 실행의 재시도 예산으로 남의 행을 깎지 않는다", queue_id)
            return
        now = datetime.now().isoformat()
        new_retry = retry_count + 1
        if new_retry >= MAX_DOC_RETRY:
            conn.execute("""
                UPDATE document_queue
                SET status=?, retry_count=?, last_attempt_at=?
                WHERE id=?
            """, (QUEUE_STATUS_FAILED, new_retry, now, queue_id))
            # 재시도가 소진된 **최종** 실패만 화면에 반영한다. 중간 재시도까지 FAILED로
            # 바꾸면 다음 시도에서 성공할 문서가 잠깐 "실패"로 보였다가 돌아온다.
            row = conn.execute(
                "SELECT court_code, case_no, item_no, doc_type FROM document_queue WHERE id=?",
                (queue_id,)
            ).fetchone()
            if row:
                # ★ **이미 가지고 있는 것을 실패로 덮지 않는다** (2026-08-18 Sprint 189).
                #
                #   재수집을 켜기 전까지 이 자리는 언제나 "한 번도 못 받은 문서"였다.
                #   이제는 **이미 READY인 문서를 다시 받으려다 실패하는 경우**가 생긴다
                #   (법원이 그 문서를 내렸거나, 버튼 DOM이 바뀌었거나, 그냥 그날 서버가
                #   불안정했거나). 그때 FAILED로 쓰면 화면은 "수집실패"라고 말하는데
                #   `/api/v1/item/{id}/documents/SPEC`은 여전히 200으로 옛 문서를
                #   내려 준다 — 화면과 실체가 갈라지는, 이 저장소가 BUGS #50 이래
                #   반복해 잡아 온 바로 그 모양이다. 사용자 입장에서는 **볼 수 있던 것이
                #   갑자기 "실패"로 보이는** 순수한 퇴행이다.
                #
                #   `reset_stale_queue()`가 "파일이 실제로 있는 문서를 COLLECTING으로
                #   가리지 않는다"고 정한 것과 같은 규칙을 반대 방향에 적용한다.
                #   큐 행은 그대로 'failed'로 남으므로 실패 사실 자체는 유실되지 않는다
                #   (로그 + `document_collect_failures` + 큐 상태에 남는다).
                held = _current_document_status(conn, row["court_code"], row["case_no"],
                                                row["item_no"], row["doc_type"])
                if held in DOC_STATUS_HAS_ARTIFACT:
                    logger.warning(
                        "[%s-%s] %s 재수집 실패 - 화면 상태는 %s 유지"
                        "(이미 가진 자산을 실패로 덮지 않는다)",
                        row["case_no"], row["item_no"], row["doc_type"], held)
                else:
                    _set_document_status(conn, row["court_code"], row["case_no"],
                                         row["item_no"], row["doc_type"], "FAILED")
                # 사유를 남긴다 — 위 주석이 이 표를 근거로 큐 행에 안 쓰기로 했으므로,
                # 이 표가 비어 있으면 그 근거가 성립하지 않는다(2026-09-02).
                _record_collect_failure(conn, row, reason)
            logger.warning("document_queue id=%d 최종 실패 처리 (재시도 %d회 소진) - 사유: %s",
                           queue_id, new_retry, reason or "미기록")
        else:
            # ★ 'pending'으로 고정하지 않는다 (2026-08-18 Sprint 189).
            #   재수집으로 집어간 항목(`in_progress_refresh`)을 'pending'으로 되돌리면
            #   **첫 실패에서 재수집 의도가 조용히 사라진다** — 다음 시도는 overwrite=False라
            #   "이미 존재. 스킵"으로 성공 처리되고, 바뀐 문서는 영원히 옛것으로 남는다.
            #   원래 어느 쪽이었는지는 진행 상태가 그대로 기억하고 있다.
            cur_status = conn.execute(
                "SELECT status FROM document_queue WHERE id=?", (queue_id,)
            ).fetchone()
            back_to = QUEUE_RESUME_STATUS.get(
                cur_status["status"] if cur_status else "", QUEUE_STATUS_PENDING)
            conn.execute("""
                UPDATE document_queue
                SET status=?, retry_count=?, last_attempt_at=?
                WHERE id=?
            """, (back_to, new_retry, now, queue_id))
            logger.info("document_queue id=%d 재시도 대기로 전환 (%s, %d/%d, %d분 후 재시도 가능)",
                        queue_id, back_to, new_retry, MAX_DOC_RETRY, RETRY_INTERVAL_MINUTES)
        conn.commit()
    finally:
        conn.close()
