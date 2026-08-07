from fastapi import APIRouter
from storage.database import get_connection

router = APIRouter()

@router.get("/document-stats")
def document_stats():
    conn = get_connection()
    try:
        total_items = conn.execute(
            "SELECT COUNT(*) FROM auction_item"
        ).fetchone()[0]

        # 예전에는 (doc_type, status) 조합마다 COUNT 쿼리를 따로 날려 document_status를
        # 6번 스캔했다. 한 번의 GROUP BY로 동일한 6개 값을 얻는다(응답 필드/값 동일).
        counts = {
            (r["doc_type"], r["status"]): r["cnt"]
            for r in conn.execute(
                """
                SELECT doc_type, status, COUNT(*) AS cnt
                FROM document_status
                WHERE doc_type IN ('SPEC','STATUS','APPRAISAL') AND status IN ('READY','FAILED')
                GROUP BY doc_type, status
                """
            ).fetchall()
        }

        def count_status(doc_type, status):
            return counts.get((doc_type, status), 0)

        spec_ready    = count_status("SPEC", "READY")
        status_ready  = count_status("STATUS", "READY")
        appraisal_ready = count_status("APPRAISAL", "READY")

        spec_failed    = count_status("SPEC", "FAILED")
        status_failed  = count_status("STATUS", "FAILED")
        appraisal_failed = count_status("APPRAISAL", "FAILED")

        total_failed = conn.execute(
            "SELECT COUNT(*) FROM document_collect_failures"
        ).fetchone()[0]

        return {
            "total_items": total_items,
            "spec_success": spec_ready,
            "status_success": status_ready,
            "appraisal_success": appraisal_ready,
            "spec_failed": spec_failed,
            "status_failed": status_failed,
            "appraisal_failed": appraisal_failed,
            "total_failures": total_failed,
        }
    finally:
        conn.close()
