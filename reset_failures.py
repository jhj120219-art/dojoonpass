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

# ★ 저장소 루트는 **이 파일 기준**이다 (2026-09-04). `os.getcwd()` 를 넣으면 다른
#   폴더에서 실행했을 때 `storage` 패키지를 못 찾아 import 단계에서 죽거나, 더 나쁘게는
#   그 폴더의 다른 `storage` 를 집는다. `unlock_retry.py` 가 같은 이유로 같은 규칙을
#   쓴다(운영 도구가 엉뚱한 DB/모듈을 보는 것을 막는다).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from storage.database import (get_connection,
                              QUEUE_STATUS_SKIPPED_EXPIRED,
                              QUEUE_STATUS_SKIPPED_UNSUPPORTED)
from datetime import datetime

APPLY = "--apply" in sys.argv

# 되살리지 않는 큐 종결 상태. **상수로 가져온다** (2026-09-04).
#   예전에는 아래 SQL 에 `IN ('SKIPPED_EXPIRED', 'SKIPPED_UNSUPPORTED')` 로 박혀 있었다.
#   오타는 예외가 아니라 **0행 매치**이고, 여기서 0행 매치는 "보호 대상이 없다"가 되어
#   **성공할 수 없는 문서까지 COLLECTING 으로 되돌린다** — 이 파일 머리말이 막으려는
#   바로 그 결과다. `storage/database.py` 의 어휘 주석과 같은 이유다.
TERMINAL_QUEUE_STATUSES = (QUEUE_STATUS_SKIPPED_EXPIRED, QUEUE_STATUS_SKIPPED_UNSUPPORTED)

# 큐가 종결(SKIPPED_*)인 document_status 행. 큐 키(법원,사건,물건,문서)와
# document_status(item_id) 사이는 auction_item/auction_case를 거쳐야 이어진다 —
# `storage/database.py:_document_status_item_id()`가 쓰는 것과 같은 경로다.
#
# ★ 상태 값은 SQL 텍스트에 넣지 않고 `?` 로 바인딩한다. 아래 세 질의가 모두 이
#   조각을 쓰므로 **파라미터 순서**를 함께 맞춰야 한다(각 호출부 참고).
TERMINAL_ROWS = """
    SELECT d.id FROM document_status d
    JOIN auction_item ai ON ai.id = d.item_id
    JOIN auction_case ac ON ac.id = ai.case_id
    JOIN document_queue q
      ON q.court_code = ac.court_code
     AND q.case_no    = ai.case_no
     AND q.item_no    = ai.item_no
     AND UPPER(q.doc_type) = UPPER(d.doc_type)
    WHERE q.status IN (?, ?)
"""

conn = get_connection()
now = datetime.now().isoformat()

failed_total = conn.execute(
    "SELECT COUNT(*) FROM document_status WHERE status=?", ("FAILED",)).fetchone()[0]

# 되살릴 행을 **먼저 식별한다** — UPDATE 뒤에는 어느 행이 FAILED 였는지 알 수 없고,
# 아래 실패 사유 정리도 이 목록으로 좁힌다.
# (`storage/database.py:reset_stale_queue()` 가 쓰는 것과 같은 순서다.)
revivable = conn.execute(
    "SELECT id, item_id, doc_type FROM document_status"
    " WHERE status=? AND id NOT IN (%s)" % TERMINAL_ROWS,
    ("FAILED",) + TERMINAL_QUEUE_STATUSES).fetchall()
protected = failed_total - len(revivable)
logs = conn.execute("SELECT COUNT(*) FROM document_collect_failures").fetchone()[0]

print("FAILED 화면 상태            : %d건" % failed_total)
print("  그중 되살릴 대상          : %d건" % len(revivable))
print("  그중 종결이라 두는 것     : %d건 (SKIPPED_EXPIRED / SKIPPED_UNSUPPORTED)" % protected)
print("document_collect_failures  : %d건 (그중 되살릴 행의 것만 지운다)" % logs)

if not APPLY:
    print("\n[DRY-RUN] 아무것도 바꾸지 않았다. 반영하려면 --apply 를 붙여라.")
    conn.close()
    sys.exit(0)

# ★ 실패 사유를 **통째로 지우지 않는다** (2026-09-04).
#
#   예전에는 `DELETE FROM document_collect_failures` 였다. 그런데 이 스크립트는
#   바로 위에서 SKIPPED_* 행을 **일부러 FAILED 로 남긴다** — 사용자에게 "수집실패"가
#   사실이기 때문이다. 그 행의 사유까지 지우면 화면은 "실패"라고 말하는데 왜인지는
#   아무 데도 없다. 그 표는 정확히 그 침묵을 없애려고 채우기 시작한 것이다
#   (`storage/database.py:_record_collect_failure()`, 2026-09-02: "사용자가 보는 129개
#   물건의 문서가 왜 없는지 아무도 모른다").
#
#   그래서 **되살리는 행의 사유만** 지운다. 되살린다는 것은 "다시 시도한다"는 뜻이라
#   지난 실패 기록이 남아 있을 이유가 없고, 남겨 두는 행은 그 기록이 유일한 근거다.
#
#   `document_collect_failures.doc_type` 은 큐와 같은 소문자이고 `document_status` 는
#   대문자다(`QUEUE_TO_DOC_STATUS_TYPE`). 위 조인과 같이 `UPPER()` 로 맞춘다.
#   행마다 지운다 — `IN (...)` 을 만들면 변수 상한을 신경 써야 하는데(BUGS #243)
#   여기 대상은 화면 FAILED 행 수라 작고, 반복문이면 그 문제가 아예 없다.
purged = 0
for r in revivable:
    purged += conn.execute(
        "DELETE FROM document_collect_failures"
        " WHERE item_id=? AND UPPER(doc_type)=UPPER(?)",
        (r["item_id"], r["doc_type"])).rowcount

revived = 0
for r in revivable:
    # 식별과 이 UPDATE 사이에 다른 실행이 그 행을 바꿨을 수 있다 - `AND status=?` 로
    # 확인한다(그래서 `rowcount` 가 곧 "정말 되살린 행 수"다).
    revived += conn.execute(
        "UPDATE document_status SET status=?, updated_at=? WHERE id=? AND status=?",
        ("COLLECTING", now, r["id"], "FAILED")).rowcount
conn.commit()
print("\n되살린 행: %d건" % revived)
print("지운 실패 사유: %d건 (되살린 행의 것만)" % purged)
print("남은 FAILED: %d건" % conn.execute(
    "SELECT COUNT(*) FROM document_status WHERE status=?", ("FAILED",)).fetchone()[0])
print("남은 실패 로그: %d건 (되살리지 않은 행의 근거는 남는다)" % conn.execute(
    "SELECT COUNT(*) FROM document_collect_failures").fetchone()[0])
conn.close()
