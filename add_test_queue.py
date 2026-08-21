"""테스트용 큐 행을 하나 넣어 보는 일회성 스크립트.

2026-08-21 Sprint 248 — **무방비 상태였다.** `python add_test_queue.py` 만 치면
운영 `document_queue` 에 곧바로 행이 들어갔다(`init_db()` + `enqueue_documents()`).
저장소의 다른 데이터 수정 도구(`backfill_*` / `repair_*` / `reset_failures` /
`unlock_retry` / `fix_validator`)는 전부 **기본 dry-run + `--apply`** 관례를 따르는데
이 파일만 예외였다.

    python add_test_queue.py            # dry-run (기본) - 무엇이 들어갈지만 보여준다
    python add_test_queue.py --apply    # 실제로 큐에 넣는다

`--apply` 를 주면 동작은 예전과 같다.

`sys.path` 도 `os.getcwd()` 가 아니라 이 파일 위치 기준으로 잡는다(Sprint 246 계열).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from storage.database import init_db, enqueue_documents

ROWS = [{
    'court_code': '서울중앙지방법원',
    'case_no': '2024타경1775',
    'auction_date': '2026-07-15',
}]

APPLY = "--apply" in sys.argv

print("큐에 넣을 행: %d개" % len(ROWS))
for _r in ROWS:
    print("   %s / %s / %s" % (_r['court_code'], _r['case_no'], _r['auction_date']))

if not APPLY:
    print("")
    print("[DRY-RUN] 아무것도 바꾸지 않았다. 반영하려면 --apply 를 붙여라.")
    sys.exit(0)

init_db()
result = enqueue_documents(ROWS)
print("")
print("큐에 넣기 완료: %s" % (result,))
