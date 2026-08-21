"""주소상 정당하게 비어야 할 지역 필드에, 그 주소와 무관한 값이 영구 보존된 행을 찾는다.

2026-08-15 Sprint 121 신설. `backfill_region_normalize.py`의 사각지대를 메운다 ―
그 스크립트는 "새로 계산한 값이 비면"(주소에 시/군/구 등이 원래 없는 경우) 건너뛴다
(좋은 기존 값을 빈 값으로 지우지 않기 위해서). 그런데 그 보호 규칙은 "원래 없어서
비었다"와 "예전에 다른 값으로 오염됐는데 지금은 못 잡는다"를 구분하지 못한다.

실제로 찾은 사례 (2026-08-15 실측)
-----------------------------------------------------------------------------
    auction.id=357  대전지방법원 2024타경11191-1
    주소: '세종특별자치시 나성로 96 1층104호 (나성동,더센트럴) ...'
    auction.sigungu      = ''      (정상 - 세종은 구/군이 없다)
    auction_item.sigungu = '칠곡군' (경상북도 소속 - 이 주소 어디에도 없는 글자)

`migrate_execute.py`의 `sigungu = row["sigungu"] or existing["sigungu"]` 병합 규칙이
원인이다. 세종 주소는 재계산해도 sigungu가 영원히 빈 문자열이라, 한 번 다른 지역
값으로 오염되면(유입 경로는 로그로 확인 불가 - court_code 복합키 도입 전
docs/BUGS.md #14 계열 case_no 충돌로 추정) **재크롤로도 절대 자연 치유되지 않는다.**

판정 기준 (보수적으로 잡는다 ― 오탐보다 누락이 낫다)
-----------------------------------------------------------------------------
    1. 지금 코드로 다시 계산한 값이 **비어 있다** (주소에 해당 구성요소가 원래 없다는 뜻)
    2. 저장된 값이 **비어 있지 않다**
    3. 저장된 값이 **주소 문자열 어디에도 부분 문자열로 나타나지 않는다**
       (나타나면 §12 "옛 규칙 잔재" 부류 - 예: 건물명 "뉴서울아파트"에 든 "서울" -
       이 스크립트가 아니라 backfill_region_normalize.py의 영역이다)

이 세 조건을 모두 만족해야 "오염 의심"으로 센다. 3번 때문에 §12가 이미 다루는
"부분 문자열 오매칭" 사례들은 자동으로 걸러진다(그 값들은 주소 안에 실제로 있다).

이 스크립트는 **탐지만 한다.** `--apply`가 없다 (cleanup_orphans_dryrun.py와 같은
관례) ― 무엇으로 덮어써야 "맞는" 값인지 이 스크립트 스스로는 알 수 없다(정답은
빈 문자열이지만, 그러면 검색 화면에서 그 필드로 걸리는 경로 자체가 사라진다는
제품 판단이 필요하다 - PM 승인 영역).

    python detect_stale_region_contamination_dryrun.py
"""
import sys
import os
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from normalizer.normalizer import normalize_address

# ★ DB 경로는 **현재 작업 디렉터리가 아니라 이 파일 기준**이다 (2026-08-21 Sprint 246).
#   상대경로면 다른 폴더에서 실행했을 때 그 폴더에 0바이트 auction.db 가 생기고
#   "no such table" 로 죽는다(실측). 운영 도구가 엉뚱한 DB 를 보는 것보다 낫지만,
#   찌꺼기 파일이 남고 오류 문구가 원인을 가린다.
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "auction.db")
TARGET_COLUMNS = ("sido", "sigungu", "dong", "lot_number")


def scan_table(conn: sqlite3.Connection, table: str) -> list:
    rows = conn.execute(
        "SELECT id, full_address, sido, sigungu, dong, lot_number FROM %s" % table
    ).fetchall()
    found = []
    for row in rows:
        addr = row["full_address"] or ""
        fresh = normalize_address(addr)
        for col in TARGET_COLUMNS:
            stored = (row[col] or "").strip()
            new = (fresh.get(col) or "").strip()
            if new:
                continue  # 지금 코드가 값을 낸다 - 이 스크립트의 대상이 아니다 (§12 영역)
            if not stored:
                continue  # 원래도 비어 있다 - 문제 없음
            if stored in addr:
                continue  # 주소 안에 실제로 있는 문자열이다 - §12(부분 문자열 오매칭) 영역
            found.append((row["id"], col, stored, addr[:70]))
    return found


def main() -> int:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        total = 0
        for table in ("auction", "auction_item"):
            hits = scan_table(conn, table)
            total += len(hits)
            print("== %s: 오염 의심 %d건" % (table, len(hits)))
            for row_id, col, stored, addr in hits:
                print("   id=%-6s %-10s 저장값=%r 주소에 없음  addr=%r" % (row_id, col, stored, addr))
        print("\n[DRY-RUN] 총 %d건. 아무것도 쓰지 않았다." % total)
        print("--apply 없음 - 무엇으로 덮어쓸지는 제품 판단(PM 승인) 영역이다.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
