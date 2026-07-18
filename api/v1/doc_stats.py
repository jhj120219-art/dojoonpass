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

        def count_status(doc_type, status):
            return conn.execute(
                "SELECT COUNT(*) FROM document_status WHERE doc_type=? AND status=?",
                (doc_type, status)
            ).fetchone()[0]

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
