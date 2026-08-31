from fastapi import APIRouter
from api.constants import DocumentStatus, DocumentType
from storage.database import (
    get_connection,
    QUEUE_STATUS_PENDING,
    QUEUE_STATUS_REFRESH,
    QUEUE_STATUS_FAILED,
    QUEUE_IN_PROGRESS_STATUSES,
)

router = APIRouter()

# 이 화면이 세는 대상. **값을 SQL 텍스트에 넣지 않는다** — `?` 반복만 만들고 값은
# 예외 없이 바인딩한다(`storage/database.py:QUEUE_CLAIMABLE_PLACEHOLDERS` 와 같은 패턴,
# `test_schema_hygiene.py` 의 SQL 조립 감사가 허용하는 형태).
#
# 2026-08-31: 이 세 종류와 두 상태가 SQL 문자열에 직접 박혀 있었다. 같은 파일이 아래
# 큐 상태는 이미 상수로 세고 있어(`QUEUE_STATUS_*`) **한 파일 안에서 규칙이 둘**이었다.
# 값은 바뀌지 않는다 — 리터럴을 상수로 옮기기만 한다.
_STAT_DOC_TYPES = (DocumentType.SPEC.value, DocumentType.STATUS.value,
                   DocumentType.APPRAISAL.value)
_STAT_STATUSES = (DocumentStatus.READY.value, DocumentStatus.FAILED.value)


def _marks(values):
    return ", ".join("?" * len(values))


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
                WHERE doc_type IN (%s) AND status IN (%s)
                GROUP BY doc_type, status
                """ % (_marks(_STAT_DOC_TYPES), _marks(_STAT_STATUSES)),
                _STAT_DOC_TYPES + _STAT_STATUSES,
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

        # 2026-08-16 Sprint 141: document_queue 적체 규모를 추가한다. 이 API 전체를
        # grep해도 document_queue를 실제로 조회하는 곳이 이 파일 자신의 주석 한 줄뿐이었다
        # — 운영자가 "지금 큐가 얼마나 쌓여 있는지"를 API/Admin 경로 어디서도 볼 수 없었다
        # (docs/SPRINT141_SCHEDULER_STATUS_CORRECTION.md — doc_worker.py 스케줄 미등록으로
        # pending 3,996건이 최소 5주 넘게 쌓여 있었는데, 그걸 알아내려면 DB를 직접 열어
        # 봐야 했다). 순수 추가 필드라 기존 응답 구조/필드명은 그대로 유지된다.
        queue_counts = dict(
            conn.execute(
                "SELECT status, COUNT(*) AS cnt FROM document_queue GROUP BY status"
            ).fetchall()
        )

        return {
            "total_items": total_items,
            "spec_success": spec_ready,
            "status_success": status_ready,
            "appraisal_success": appraisal_ready,
            "spec_failed": spec_failed,
            "status_failed": status_failed,
            "appraisal_failed": appraisal_failed,
            "total_failures": total_failed,
            # 2026-08-18 Sprint 189: 큐 어휘가 늘었다('refresh'/'in_progress_refresh').
            # 하드코딩한 목록으로 세면 **새 값이 조용히 어느 칸에도 안 잡힌다** —
            # BUGS #119가 정확히 그 부류였다. 단일 소스(storage.database)를 참조한다.
            "queue_pending": queue_counts.get(QUEUE_STATUS_PENDING, 0),
            # 재수집 대기. 순수 추가 필드다(기존 필드 의미 불변).
            "queue_refresh": queue_counts.get(QUEUE_STATUS_REFRESH, 0),
            # "지금 작업 중인 건수"는 최초 수집이든 재수집이든 같은 뜻이므로 합산한다.
            "queue_in_progress": sum(queue_counts.get(v, 0)
                                     for v in QUEUE_IN_PROGRESS_STATUSES),
            # 2026-08-31: 이 한 칸만 리터럴이었다. 위 세 칸과 같은 단일 소스를 쓴다 —
            # 어휘가 바뀌면 여기만 조용히 0 이 되던 자리다.
            "queue_failed": queue_counts.get(QUEUE_STATUS_FAILED, 0),
        }
    finally:
        conn.close()
