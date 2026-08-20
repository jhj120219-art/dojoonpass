import os
import sqlite3
import logging
from datetime import datetime
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

DB_PATH = "auction.db"

# `auction_image.storage_path` 는 프로젝트 루트 기준 상대경로다
# (`to_relative_storage_path()` 참고). 절대경로로 되돌릴 때 쓴다 —
# `api/v1/images.py:resolve_stored_path()` 와 같은 규칙이어야 한다.
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)

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


def upsert_batch(rows: List[Dict]) -> Dict:
    conn = get_connection()
    inserted = 0
    updated = 0
    failed = 0
    try:
        for row in rows:
            try:
                now = datetime.now().isoformat()
                # 식별키는 (court_code, case_no, item_no)다 — 2026-08-07 Migration 012에서
                # auction의 UNIQUE 제약을 여기에 맞춰 바꿨다(docs/BUGS.md #18).
                # 예전에는 법원을 빼고 (case_no, item_no)로만 찾아 UPDATE했기 때문에,
                # 서로 다른 법원이 같은 사건번호+물건번호를 쓰면 앞서 저장된 법원의 물건이
                # 통째로 교체되어 사라졌다(병합이 아니라 소실). 이제 법원별로 각자의 행을 갖는다.
                existing = conn.execute(
                    "SELECT id FROM auction WHERE court_code=? AND case_no=? AND item_no=?",
                    (row.get("court_code", ""), row.get("case_no", ""), row.get("item_no", ""))
                ).fetchone()

                if existing:
                    conn.execute("""
                        UPDATE auction SET
                            court_code=?, court_name=?, property_type=?,
                            sido=?, sigungu=?, dong=?, lot_number=?,
                            full_address=?, appraisal_price=?,
                            minimum_bid_price=?, auction_date=?,
                            status=?, validation_status=?,
                            validation_reasons=?, crawl_date=?,
                            updated_at=?
                        WHERE court_code=? AND case_no=? AND item_no=?
                    """, (
                        row.get("court_code", ""),
                        row.get("court_name", ""),
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
                        now,
                        row.get("court_code", ""),
                        row.get("case_no", ""),
                        row.get("item_no", ""),
                    ))
                    updated += 1
                else:
                    conn.execute("""
                        INSERT INTO auction (
                            court_code, court_name, case_no, item_no,
                            property_type, sido, sigungu, dong, lot_number,
                            full_address, appraisal_price, minimum_bid_price,
                            auction_date, status, validation_status,
                            validation_reasons, crawl_date,
                            has_spec_pdf, has_status_doc, has_appraisal_pdf,
                            created_at, updated_at
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,0,0,?,?)
                    """, (
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
                        now,
                        now,
                    ))
                    inserted += 1
            except Exception as e:
                logger.warning("upsert 실패 [%s]: %s", row.get("case_no", ""), str(e))
                failed += 1

        conn.commit()
        logger.info("DB UPSERT 완료 - 신규: %d, 업데이트: %d, 실패: %d",
                    inserted, updated, failed)
        return {"inserted": inserted, "updated": updated, "failed": failed}

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
            conditions.append("property_type LIKE ?")
            params.append("%" + property_type + "%")
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
    이미 has_*_pdf=1인 문서는 큐에 넣지 않는다.
    UNIQUE(court_code, case_no, item_no, doc_type) 이므로 이미 대기 중인 항목은
    INSERT OR IGNORE로 조용히 무시된다 (중복 enqueue 방지).

    1차 방어선(예방): auction_date가 이미 지난 사건은 큐에 넣지 않는다.
    Step 13/14 검증 결과, 매각기일이 지난 사건은 법원경매정보 사이트의
    "사건번호 직접검색"으로도 조회가 안 되어(취하/변경/매각완료 등 사유는
    미확정이나, 검색 불가 자체는 실측 8건으로 확인됨) 애초에 수집이
    불가능하므로, 큐 적재 단계에서 걸러 불필요한 재시도 자체를 방지한다.
    """
    conn = get_connection()
    added = 0
    refreshed = 0
    skipped_expired = 0
    try:
        now = datetime.now().isoformat()
        today = datetime.now().strftime("%Y-%m-%d")
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
                cur = conn.execute("""
                    INSERT OR IGNORE INTO document_queue
                        (court_code, case_no, item_no, doc_type, priority, auction_date, status, retry_count, enqueued_at)
                    VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?)
                """, (court_code, case_no, item_no, doc_type, priority, auction_date, now))
                if cur.rowcount > 0:
                    added += 1
                elif auction_date:
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
                    upd = conn.execute("""
                        UPDATE document_queue
                           SET auction_date = ?, priority = ?
                         WHERE court_code = ? AND case_no = ? AND item_no = ? AND doc_type = ?
                           AND IFNULL(auction_date, '') <> ?
                    """, (auction_date, priority, court_code, case_no, item_no, doc_type,
                          auction_date))
                    refreshed += upd.rowcount
        conn.commit()
        logger.info("document_queue 적재: %d건 (기일 갱신: %d건, 기일경과로 사전제외: %d건)",
                    added, refreshed, skipped_expired)
        return {"added": added, "refreshed": refreshed, "skipped_expired": skipped_expired}
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

    cap = REFRESH_MAX_ITEMS_PER_RUN if max_items is None else max_items
    over_cap = 0
    if cap is not None and cap >= 0 and len(changes) > cap:
        over_cap = len(changes) - cap
        # ★ 조용히 자르지 않는다. 잘린 건수를 로그에 남겨야 "전부 처리됐다"로 오독되지 않는다.
        logger.warning(
            "재수집 대상 %d건 중 상한(%d)을 넘는 %d건은 이번 실행에서 미룬다"
            "(큐에 그대로 남아 다음 실행에서 다시 후보가 된다)",
            len(changes), cap, over_cap)
        changes = changes[:cap]

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
                       AND status='done'
                       AND (IFNULL(auction_date, '') = '' OR auction_date >= ?)
                """, (QUEUE_STATUS_REFRESH, court_code, case_no, item_no, doc_type, today))
                refreshed += cur.rowcount or 0

                # 기일이 지나 종결됐던 행은, 기일이 **미래로 다시 잡혔을 때만** 되살린다.
                # (유찰 후 재매각은 한국 경매에서 일상이다 — `enqueue_documents()`가
                #  이미 큐의 auction_date를 최신값으로 맞춰 두므로 그 값을 그대로 믿는다.)
                cur = conn.execute("""
                    UPDATE document_queue
                       SET status=?, retry_count=0, last_attempt_at=NULL
                     WHERE court_code=? AND case_no=? AND item_no=? AND doc_type=?
                       AND status='SKIPPED_EXPIRED'
                       AND IFNULL(auction_date, '') >= ?
                """, (QUEUE_STATUS_PENDING, court_code, case_no, item_no, doc_type, today))
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
        rows = conn.execute(
            "SELECT id, auction_date FROM document_queue WHERE status IN ("
            + QUEUE_CLAIMABLE_PLACEHOLDERS + ")",
            QUEUE_CLAIMABLE_STATUSES,
        ).fetchall()
        for row in rows:
            new_priority = calc_priority(row["auction_date"])
            cur = conn.execute(
                "UPDATE document_queue SET priority=? WHERE id=? AND priority!=?",
                (new_priority, row["id"], new_priority)
            )
            examined += 1
            # UPDATE에 `AND priority!=?`가 걸려 있어 대부분의 행은 실제로 바뀌지 않는다.
            # 예전에는 검토한 행 수를 그대로 반환해서, 배치 로그가 매일 밤
            # "우선순위 재계산 완료: 2,736건"을 남겼다 — 실제로 바뀐 것이 0건인 날에도
            # 똑같이 찍혀 운영자가 "매일 수천 건이 갱신된다"고 오해하게 만들었다
            # (BUGS #47과 같은 부류 — 배치 로그가 사실이 아닌 것을 말하는 문제).
            # 이제 **실제로 바뀐 행 수**를 반환한다.
            if cur.rowcount > 0:
                changed += 1
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
            WHERE status='failed'
              AND last_attempt_at IS NOT NULL
              AND datetime(last_attempt_at) < datetime(""" + _NOW_LOCAL + """, '-1 day')
        """).fetchall()

        conn.execute("""
            UPDATE document_queue
            SET status='pending', retry_count=0
            WHERE status='failed'
              AND last_attempt_at IS NOT NULL
              AND datetime(last_attempt_at) < datetime(""" + _NOW_LOCAL + """, '-1 day')
        """)

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
                                doc_type: str, auction_date: str) -> None:
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
        now = datetime.now().isoformat()
        conn.execute("""
            UPDATE document_queue
            SET status='SKIPPED_EXPIRED', last_attempt_at=?
            WHERE id=?
        """, (now, queue_id))

        conn.commit()
        logger.info(
            "[%s-%s] %s SKIPPED_EXPIRED 처리 (사유: auction_date=%s 경과, 법원=%s)",
            case_no, item_no, doc_type, auction_date, court_code
        )
    finally:
        conn.close()


def mark_queue_unsupported(queue_id: int, court_code: str, case_no: str, item_no: str,
                            doc_type: str) -> None:
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
        now = datetime.now().isoformat()
        conn.execute("""
            UPDATE document_queue
            SET status='SKIPPED_UNSUPPORTED', last_attempt_at=?
            WHERE id=?
        """, (now, queue_id))

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

# 워커가 집어갈 수 있는 상태. `claim_next_queue_item()`과 `refresh_queue_priority()`가
# **같은 목록**을 봐야 한다 — 갈라지면 refresh 행이 우선순위 재계산에서 빠진다.
QUEUE_CLAIMABLE_STATUSES = (QUEUE_STATUS_PENDING, QUEUE_STATUS_REFRESH)

# `IN (...)` 자리에 넣을 **`?` 반복만** 만든다. 상태 값 자체는 SQL 문자열에 절대 넣지 않고
# 예외 없이 바인딩한다 — `test_schema_hygiene.py`의 SQL 조립 감사가 허용하는 형태
# (`api/v1/payments.py`의 `IN (%s)`와 같은 패턴)이고, 어휘가 늘어도 자동으로 따라간다.
QUEUE_CLAIMABLE_PLACEHOLDERS = ", ".join("?" * len(QUEUE_CLAIMABLE_STATUSES))

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

    primary = None
    if primary_ext:
        primary = next((p for p in files_saved
                        if p.lower().endswith("." + primary_ext)), None)
    if primary is None:
        primary = files_saved[0]

    try:
        size = _os.path.getsize(primary)
    except OSError:
        logger.warning("doc_raw 기록 생략: 저장했다는 파일이 실제로 없다 (%s)", primary)
        return
    if size <= 0:
        logger.warning("doc_raw 기록 생략: 0바이트 파일 (%s)", primary)
        return

    new_hash = _sha256_file(primary)

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
    # 오르는" 형태로 사용자에게 드러난다 — 아직 아무도 `overwrite=True`를 넘기지 않아
    # 지금은 첫 수집(행 없음 -> 항상 삽입)만 일어나므로 도달하지 않았다.
    #
    # 비교는 이 함수가 방금 계산한 `new_hash`(저장할 파일의 sha256) 대 직전 doc_raw 행의
    # `file_hash`로 한다 — `mark_queue_done()`이 받는 `previous_hash`/`new_hash` 인자에
    # 기대지 않는다. 그 인자들은 크롤러 계층(`crawler/doc_crawler.py`)이 doc_type마다
    # 각자 계산해 넘기는 값이라 여기 대표 파일과 반드시 같은 파일을 가리킨다는 보장이
    # 없다(예: status는 html+json 두 파일을 저장하고 대표는 json이다). doc_raw 자기
    # 행의 file_hash와 비교하면 그 가정이 필요 없다.
    if latest is not None and latest["file_hash"] and latest["file_hash"] == new_hash:
        logger.info("doc_raw 기록 생략: 내용 변경 없음 (item_id=%s, doc_type=%s, version=%s 유지)",
                    item_id, ds_type, latest["doc_version"])
        return

    version = (latest["doc_version"] + 1) if latest is not None else 1

    conn.execute(
        """
        INSERT INTO doc_raw
            (item_id, doc_type, storage_path, file_hash, file_size,
             doc_version, page_count, crawl_date, created_at)
        VALUES (?,?,?,?,?,?,?,?,?)
        """,
        (item_id, ds_type, to_relative_storage_path(primary), new_hash,
         size, version, _pdf_page_count(primary),
         datetime.now().strftime("%Y-%m-%d"), now),
    )


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


def mark_queue_done(queue_id: int, court_code: str, case_no: str, item_no: str, doc_type: str,
                     previous_hash: str, new_hash: str, status: str = "READY",
                     files_saved: Optional[List[str]] = None) -> None:
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
        conn.execute("UPDATE document_queue SET status='done' WHERE id=?", (queue_id,))

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


def mark_queue_failed(queue_id: int, retry_count: int) -> None:
    conn = get_connection()
    try:
        now = datetime.now().isoformat()
        new_retry = retry_count + 1
        if new_retry >= MAX_DOC_RETRY:
            conn.execute("""
                UPDATE document_queue
                SET status='failed', retry_count=?, last_attempt_at=?
                WHERE id=?
            """, (new_retry, now, queue_id))
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
            logger.warning("document_queue id=%d 최종 실패 처리 (재시도 %d회 소진)", queue_id, new_retry)
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
