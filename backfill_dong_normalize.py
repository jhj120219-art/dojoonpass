"""
Sprint 3 STEP1: normalizer.normalize_address()의 동(洞) 추출 정규식 수정 이후,
기존 auction / auction_item 테이블에 이미 저장된 dong 빈 값을 재계산해 채우는
1회성 백필 스크립트.

대상: dong이 NULL이거나 빈 문자열인 행만. 이미 값이 채워진 dong은 건드리지 않는다
(최소 수정 원칙 — 정규식 수정으로 새로 못 잡게 된 케이스는 없다는 것이 전제이므로
기존 비어있지 않은 값을 덮어쓸 이유가 없다).

기본 실행(인자 없음): dry-run — 몇 건이 채워질지만 계산해서 출력하고 DB는 건드리지 않는다.
    python backfill_dong_normalize.py

실제 반영하려면 --apply 옵션을 명시적으로 줘야 한다:
    python backfill_dong_normalize.py --apply

주의: 이 스크립트는 작성만 하고 PM(사용자) 승인 전에는 --apply로 실행하지 않는다.
"""
import sys
import sqlite3
from normalizer.normalizer import normalize_address

DB_PATH = "auction.db"


def backfill_table(conn: sqlite3.Connection, table: str, apply: bool) -> dict:
    rows = conn.execute(
        f"SELECT id, full_address FROM {table} WHERE dong IS NULL OR dong = ''"
    ).fetchall()

    fixed = 0
    still_empty = 0
    for row_id, full_address in rows:
        new_dong = normalize_address(full_address or "")["dong"]
        if new_dong:
            fixed += 1
            if apply:
                conn.execute(f"UPDATE {table} SET dong = ? WHERE id = ?", (new_dong, row_id))
        else:
            still_empty += 1

    if apply:
        conn.commit()

    return {"table": table, "target": len(rows), "fixed": fixed, "still_empty": still_empty}


def main():
    apply = "--apply" in sys.argv
    conn = sqlite3.connect(DB_PATH)
    try:
        results = [
            backfill_table(conn, "auction", apply),
            backfill_table(conn, "auction_item", apply),
        ]
    finally:
        conn.close()

    mode = "APPLY (실제 UPDATE 수행됨)" if apply else "DRY-RUN (DB 변경 없음)"
    print(f"=== dong 백필 결과 [{mode}] ===")
    for r in results:
        print(
            f"  {r['table']}: dong 빈 값 대상 {r['target']}건 중 "
            f"채움 가능 {r['fixed']}건, 여전히 빈 값 {r['still_empty']}건"
        )


if __name__ == "__main__":
    main()
