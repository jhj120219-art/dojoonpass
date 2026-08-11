import sqlite3
import logging
from datetime import datetime
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

DB_PATH = "auction.db"

MAX_DOC_RETRY = 3
RETRY_INTERVAL_MINUTES = 30

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

            for doc_type in ("spec", "status", "appraisal"):
                cur = conn.execute("""
                    INSERT OR IGNORE INTO document_queue
                        (court_code, case_no, item_no, doc_type, priority, auction_date, status, retry_count, enqueued_at)
                    VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?)
                """, (court_code, case_no, item_no, doc_type, priority, auction_date, now))
                if cur.rowcount > 0:
                    added += 1
        conn.commit()
        logger.info("document_queue 적재: %d건 (기일경과로 사전제외: %d건)", added, skipped_expired)
        return {"added": added, "skipped_expired": skipped_expired}
    finally:
        conn.close()


def refresh_queue_priority() -> int:
    """
    01:50에 별도 스케줄로 실행 (run_priority_refresh.bat -> refresh_priority.py).
    대기 중(pending)인 항목들의 auction_date 기준으로 priority를 다시 계산해 갱신한다.
    06:00에 enqueue 했을 때보다 시간이 지나 매각기일이 임박해진 사건의 우선순위를 끌어올리기 위함.
    """
    conn = get_connection()
    updated = 0
    try:
        rows = conn.execute(
            "SELECT id, auction_date FROM document_queue WHERE status='pending'"
        ).fetchall()
        for row in rows:
            new_priority = calc_priority(row["auction_date"])
            conn.execute(
                "UPDATE document_queue SET priority=? WHERE id=? AND priority!=?",
                (new_priority, row["id"], new_priority)
            )
            updated += 1
        conn.commit()
        logger.info("document_queue 우선순위 재계산: %d건 검토", updated)
        return updated
    finally:
        conn.close()


def reset_stale_queue() -> None:
    """
    02:00 Worker 시작 시 호출.
    - 하루 지난 failed 건은 재시도 가능하도록 pending으로 되돌림
    - in_progress 상태로 10분 넘게 멈춰있는 건(비정상 종료 추정)도 회수
    - status='SKIPPED_EXPIRED'는 이 함수가 건드리는 대상(failed, in_progress)에
      해당하지 않으므로 자동으로 재시도 대상에서 제외된다. 다만 이는 "현재 시점
      기준 검색 불가"의 기록일 뿐 "영구 재수집 불가"를 의미하지 않으므로(PM 확정
      사항), 필요 시 별도 운영 스크립트로 수동 재시도(pending 복귀)는 가능하다.
    """
    conn = get_connection()
    try:
        conn.execute("""
            UPDATE document_queue
            SET status='pending', retry_count=0
            WHERE status='failed'
              AND last_attempt_at IS NOT NULL
              AND datetime(last_attempt_at) < datetime('now', '-1 day')
        """)
        conn.execute("""
            UPDATE document_queue
            SET status='pending'
            WHERE status='in_progress'
              AND last_attempt_at IS NOT NULL
              AND datetime(last_attempt_at) < datetime('now', '-10 minutes')
        """)
        conn.commit()
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


# 큐의 doc_type(소문자)과 document_status.doc_type(대문자)의 대응.
# 두 테이블이 다른 표기를 쓰는 것은 기존 상태이며, 여기서 표기를 통일하면
# 이미 쌓인 5,610행과 어긋나므로 **변환만** 한다.
QUEUE_TO_DOC_STATUS_TYPE = {"spec": "SPEC", "status": "STATUS", "appraisal": "APPRAISAL"}


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
    row = conn.execute(
        """
        SELECT ai.id FROM auction_item ai
        JOIN auction_case ac ON ac.id = ai.case_id
        WHERE ac.court_code = ? AND ai.case_no = ? AND ai.item_no = ?
        """,
        (court_code, case_no, item_no),
    ).fetchone()
    if not row:
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
        (row["id"], ds_type, status, datetime.now().isoformat()),
    )
    return True


def claim_next_queue_item() -> Optional[Dict]:
    """
    status='pending' -> 'in_progress' 원자적 클레임.
    UPDATE ... WHERE status='pending' 조건으로 동시성 문제를 방지하고,
    성공(rowcount>0) 했을 때만 그 항목을 반환한다.
    커밋 후 즉시 커넥션을 닫아 락을 짧게 유지한다(다운로드 작업 중에는 DB를 잠그지 않음).
    """
    conn = get_connection()
    try:
        row = conn.execute("""
            SELECT id, court_code, case_no, item_no, doc_type, retry_count, auction_date
            FROM document_queue
            WHERE status='pending'
              AND (
                    last_attempt_at IS NULL
                    OR datetime(last_attempt_at) <= datetime('now', '-""" + str(RETRY_INTERVAL_MINUTES) + """ minutes')
              )
            ORDER BY priority ASC, auction_date ASC
            LIMIT 1
        """).fetchone()
        if not row:
            return None

        now = datetime.now().isoformat()
        cur = conn.execute("""
            UPDATE document_queue
            SET status='in_progress', last_attempt_at=?
            WHERE id=? AND status='pending'
        """, (now, row["id"]))
        conn.commit()

        if cur.rowcount == 0:
            return None
        return dict(row)
    finally:
        conn.close()


def mark_queue_done(queue_id: int, court_code: str, case_no: str, item_no: str, doc_type: str,
                     previous_hash: str, new_hash: str) -> None:
    conn = get_connection()
    try:
        now = datetime.now().isoformat()
        conn.execute("UPDATE document_queue SET status='done' WHERE id=?", (queue_id,))

        col = {"spec": "has_spec_pdf", "status": "has_status_doc", "appraisal": "has_appraisal_pdf"}[doc_type]
        conn.execute(
            "UPDATE auction SET " + col + "=1 WHERE court_code=? AND case_no=? AND item_no=?",
            (court_code, case_no, item_no)
        )

        # 화면이 읽는 것은 이 테이블이다 — 같은 트랜잭션에서 함께 갱신해야 두 기록이
        # 갈라지지 않는다 (BUGS #50).
        _set_document_status(conn, court_code, case_no, item_no, doc_type, "READY")

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
                _set_document_status(conn, row["court_code"], row["case_no"],
                                     row["item_no"], row["doc_type"], "FAILED")
            logger.warning("document_queue id=%d 최종 실패 처리 (재시도 %d회 소진)", queue_id, new_retry)
        else:
            conn.execute("""
                UPDATE document_queue
                SET status='pending', retry_count=?, last_attempt_at=?
                WHERE id=?
            """, (new_retry, now, queue_id))
            logger.info("document_queue id=%d 재시도 대기로 전환 (%d/%d, %d분 후 재시도 가능)",
                        queue_id, new_retry, MAX_DOC_RETRY, RETRY_INTERVAL_MINUTES)
        conn.commit()
    finally:
        conn.close()
