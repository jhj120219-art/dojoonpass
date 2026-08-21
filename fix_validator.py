"""검증 실패로 잡힌 특정 사건을 수동으로 PASS 처리한다.

2026-08-21 Sprint 248 — **무방비 상태였다.** 원래 이 파일은 `python fix_validator.py`
만 치면 곧바로 운영 `auction` 테이블을 UPDATE 하고 commit 했다. 확인 절차도,
되돌릴 방법도 없었다.

저장소의 다른 데이터 수정 도구는 전부 같은 관례를 따른다 —
`backfill_*.py` / `repair_*.py` / `reset_failures.py` / `unlock_retry.py` 는
**기본이 dry-run 이고 `--apply` 를 줘야 실제로 쓴다.** 이 파일만 예외였다.

    python fix_validator.py            # dry-run (기본) - 무엇이 바뀔지만 보여준다
    python fix_validator.py --apply    # 실제 반영

두 번째 수정: `sys.path` 를 `os.getcwd()` 가 아니라 **이 파일 위치** 기준으로 잡는다.
cwd 기준이면 저장소 밖에서 실행했을 때 import 가 깨진다(Sprint 246 과 같은 계열).

동작 자체는 바꾸지 않았다 — `--apply` 를 주면 예전과 똑같이 그 한 사건을 PASS 로 만든다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from storage.database import get_connection

TARGET_CASE_NO = "2024타경653"
APPLY = "--apply" in sys.argv

conn = get_connection()

before = conn.execute(
    "SELECT COUNT(*) AS cnt FROM auction"
    " WHERE case_no = ? AND validation_status != 'PASS'", (TARGET_CASE_NO,)
).fetchone()["cnt"]
print("PASS 로 바꿀 대상 (%s): %d건" % (TARGET_CASE_NO, before))

fail_total = conn.execute(
    "SELECT COUNT(*) AS cnt FROM auction WHERE validation_status = 'FAIL'"
).fetchone()["cnt"]
print("현재 FAIL 건수            : %d건" % fail_total)

if not APPLY:
    print("\n[DRY-RUN] 아무것도 바꾸지 않았다. 반영하려면 --apply 를 붙여라.")
    conn.close()
    sys.exit(0)

cur = conn.execute(
    "UPDATE auction SET validation_status = 'PASS', validation_reasons = ''"
    " WHERE case_no = ?", (TARGET_CASE_NO,))
conn.commit()
print("\n%s -> PASS 처리 완료: %d건" % (TARGET_CASE_NO, cur.rowcount))

after = conn.execute(
    "SELECT COUNT(*) AS cnt FROM auction WHERE validation_status = 'FAIL'"
).fetchone()["cnt"]
print("남은 FAIL 건수            : %d건" % after)
conn.close()
