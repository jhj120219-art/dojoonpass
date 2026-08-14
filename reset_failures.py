"""실패 기록을 지우고 화면 상태를 '수집중'으로 되돌리는 수동 운영 스크립트.

## 되살리면 안 되는 것이 있다 (2026-08-14)

이 스크립트의 뜻은 "다시 시도할 수 있게 실패를 푼다"이다. 그런데 큐에는 **다시 시도해도
성공할 수 없는** 종결 상태가 두 가지 있고, 그 행까지 COLLECTING으로 되돌리면
**영원히 "수집중"으로 보이는 문서**를 만든다(docs/BUGS.md #69와 같은 상태).

    SKIPPED_EXPIRED       매각기일이 지나 법원 사이트에서 조회 자체가 안 된다
    SKIPPED_UNSUPPORTED   수집 버튼 id가 없다(현황조사서 item_no != 1)

둘 다 `reset_stale_queue()`가 일부러 되살리지 않는 상태다. 화면만 "수집중"으로
바꿔 놓으면 큐는 종결인데 화면은 기다리는, 앞뒤가 안 맞는 상태가 된다.
그래서 **그 행들은 FAILED 그대로 둔다** — 사용자에게는 "수집실패"가 사실이다.

    python reset_failures.py            # 무엇이 바뀌는지 보고만 한다 (기본)
    python reset_failures.py --apply    # 실제로 반영한다
"""
import sys, os
sys.path.insert(0, os.getcwd())
from storage.database import get_connection
from datetime import datetime

APPLY = "--apply" in sys.argv

# 큐가 종결(SKIPPED_*)인 document_status 행. 큐 키(법원,사건,물건,문서)와
# document_status(item_id) 사이는 auction_item/auction_case를 거쳐야 이어진다 —
# `storage/database.py:_document_status_item_id()`가 쓰는 것과 같은 경로다.
TERMINAL_ROWS = """
    SELECT d.id FROM document_status d
    JOIN auction_item ai ON ai.id = d.item_id
    JOIN auction_case ac ON ac.id = ai.case_id
    JOIN document_queue q
      ON q.court_code = ac.court_code
     AND q.case_no    = ai.case_no
     AND q.item_no    = ai.item_no
     AND UPPER(q.doc_type) = UPPER(d.doc_type)
    WHERE q.status IN ('SKIPPED_EXPIRED', 'SKIPPED_UNSUPPORTED')
"""

conn = get_connection()
now = datetime.now().isoformat()

failed_total = conn.execute(
    "SELECT COUNT(*) FROM document_status WHERE status='FAILED'").fetchone()[0]
protected = conn.execute(
    "SELECT COUNT(*) FROM document_status WHERE status='FAILED' AND id IN (%s)"
    % TERMINAL_ROWS).fetchone()[0]
logs = conn.execute("SELECT COUNT(*) FROM document_collect_failures").fetchone()[0]

print("FAILED 화면 상태            : %d건" % failed_total)
print("  그중 되살릴 대상          : %d건" % (failed_total - protected))
print("  그중 종결이라 두는 것     : %d건 (SKIPPED_EXPIRED / SKIPPED_UNSUPPORTED)" % protected)
print("document_collect_failures  : %d건 삭제 대상" % logs)

if not APPLY:
    print("\n[DRY-RUN] 아무것도 바꾸지 않았다. 반영하려면 --apply 를 붙여라.")
    conn.close()
    sys.exit(0)

conn.execute("DELETE FROM document_collect_failures")
cur = conn.execute(
    "UPDATE document_status SET status='COLLECTING', updated_at=?"
    " WHERE status='FAILED' AND id NOT IN (%s)" % TERMINAL_ROWS, (now,))
conn.commit()
print("\n되살린 행: %d건" % cur.rowcount)
print("남은 FAILED: %d건" % conn.execute(
    "SELECT COUNT(*) FROM document_status WHERE status='FAILED'").fetchone()[0])
print("남은 실패 로그: %d건" % conn.execute(
    "SELECT COUNT(*) FROM document_collect_failures").fetchone()[0])
conn.close()
