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

        # ★ 이 값만 **출처가 다르다** (2026-08-14 실측 확인).
        #
        #   spec/status/appraisal_failed  <- document_status        (살아있는 경로)
        #   total_failures                <- document_collect_failures
        #
        # `document_collect_failures`에 INSERT 하는 코드는 `collect_documents.py` 하나뿐이고,
        # **어떤 배치도 그 스크립트를 실행하지 않는다**(`run_*.bat` 전수 확인). 살아있는
        # 수집기 `doc_worker.py`는 실패를 `document_queue.status='failed'`와
        # `document_status='FAILED'`에만 남긴다.
        #
        #   document_collect_failures 최신 행  2026-07-15  (그 뒤로 멈춤)
        #   document_status 최신 갱신          2026-08-12
        #
        # 즉 이 값은 **누적 실패 "사건" 로그**이지 위 세 값의 합이 아니다. 지금 우연히
        # 둘 다 3이라 어긋남이 보이지 않지만, doc_worker가 실패를 하나 더 기록하면
        # spec/status/appraisal_failed만 늘고 이 값은 그대로 있는다.
        #
        # 무엇으로 정의할지(누적 사건 vs 현재 FAILED 개수)는 제품 결정이라 바꾸지 않았다.
        # 자세한 내용은 `docs/SPRINT101_RETRY_LOOP_AND_TIMEZONE.md` #101-3 참고.
        # (프런트는 이 엔드포인트를 쓰지 않는다 — 운영 지표 전용.)
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
