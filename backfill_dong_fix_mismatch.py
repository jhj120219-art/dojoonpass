"""
Sprint 4 STEP7: STEP6에서 수정된 normalize_address()의 "괄호 안 법정동 우선" 로직으로
기존에 저장된 dong 값과 달라지는 행만 골라 반영하는 선택적 백필.

STEP5(빈 dong 채우기, 491건)와는 대상 선정 기준이 다르다 — 이번엔 dong이 이미
채워져 있지만 "에이동"/"비동"/"젊음의거리" 같은 오탐 값으로 잘못 채워졌던 행만 대상으로
한다. STEP5에서 이미 올바르게 채운 값은 재계산해도 동일한 값이 나오므로 자동으로
대상에서 제외된다(별도 예외 처리 불필요).

대상 조건: dong이 NULL/빈 문자열이 아니고(비어있는 행은 STEP5 담당 영역, 여기선 건드리지
않음), normalize_address(full_address)['dong']이 현재 저장된 dong과 다르고, 새 값이
비어있지 않은 행만.

기본 실행(인자 없음): dry-run — 대상/변경예정 건수만 계산하고 DB는 건드리지 않는다.
    python backfill_dong_fix_mismatch.py

실제 반영하려면 --apply 옵션을 명시적으로 줘야 한다:
    python backfill_dong_fix_mismatch.py --apply
"""
import os
import sys
import sqlite3
from normalizer.normalizer import normalize_address

# ★ DB 경로는 **현재 작업 디렉터리가 아니라 이 파일 기준**이다 (2026-08-21 Sprint 246).
#   상대경로면 다른 폴더에서 실행했을 때 그 폴더에 0바이트 auction.db 가 생기고
#   "no such table" 로 죽는다(실측). 운영 도구가 엉뚱한 DB 를 보는 것보다 낫지만,
#   찌꺼기 파일이 남고 오류 문구가 원인을 가린다.
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "auction.db")


def find_mismatches(conn: sqlite3.Connection, table: str):
    rows = conn.execute(
        f"SELECT id, full_address, dong FROM {table} "
        f"WHERE full_address IS NOT NULL AND full_address != '' "
        f"AND dong IS NOT NULL AND dong != ''"
    ).fetchall()

    mismatches = []
    for row_id, full_address, current_dong in rows:
        new_dong = normalize_address(full_address)["dong"]
        if new_dong and new_dong != current_dong:
            mismatches.append((row_id, full_address, current_dong, new_dong))
    return mismatches


def apply_table(conn: sqlite3.Connection, table: str, apply: bool):
    mismatches = find_mismatches(conn, table)
    if apply:
        for row_id, _addr, _old, new_dong in mismatches:
            conn.execute(f"UPDATE {table} SET dong = ? WHERE id = ?", (new_dong, row_id))
        conn.commit()
    return mismatches


def main():
    apply = "--apply" in sys.argv
    conn = sqlite3.connect(DB_PATH)
    try:
        auction_mismatches = apply_table(conn, "auction", apply)
        item_mismatches = apply_table(conn, "auction_item", apply)
    finally:
        conn.close()

    mode = "APPLY (실제 UPDATE 수행됨)" if apply else "DRY-RUN (DB 변경 없음)"
    print(f"=== dong 오탐 수정 백필 결과 [{mode}] ===")
    print(f"  auction: 변경 대상(불일치) {len(auction_mismatches)}건")
    print(f"  auction_item: 변경 대상(불일치) {len(item_mismatches)}건")
    print()
    print("=== auction_item Before -> After 상세 ===")
    for row_id, addr, old, new in item_mismatches:
        print(f"[id={row_id}] {old!r} -> {new!r}")
        print(f"    {addr[:80]}")


if __name__ == "__main__":
    main()
