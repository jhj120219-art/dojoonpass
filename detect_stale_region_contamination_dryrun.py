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

판정 기준 ― **직접 적지 않고 `backfill_region_normalize.is_stale_contamination()` 을 부른다**
-----------------------------------------------------------------------------
    1. 지금 코드로 다시 계산한 값이 **비어 있다** (주소에 해당 구성요소가 원래 없다는 뜻)
    2. 저장된 값이 **주소 원문(대괄호 제외)에도 없다**

대괄호 안은 물건 표시(면적·등기부 용어)라 주소 성분이 아니다. 거기까지 보고
"주소에 있다"고 판정하면 오염을 놓친다.

★ 2026-09-01 정정 ― 예전에는 이 판정을 **여기에 따로 적어** 두었고(`stored in addr`,
  즉 대괄호까지 포함한 원문 전체와 대조), 그래서 `docs/BUGS.md` #224 가 남은 위험으로
  적어 둔 그대로 **오염을 못 잡았다.** 이 머신에서 실제로 갈렸다:

      이 스크립트                        오염 의심 **0건**
      test_pipeline_integrity.py §12     오염 **1건** (id=1768 `sigungu='갑구'`)

  같은 질문에 두 도구가 다른 답을 했고 **감사 쪽이 틀렸다.** 규칙을 세 벌 두면
  이런 날이 반드시 온다. 지금은 백필·가드·이 스크립트가 **같은 함수 하나**를 쓴다.

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

# ★ 2026-09-01 — 판정을 직접 적지 않고 **정본을 불러 쓴다.**
#
#   이 스크립트는 자기 판정을 따로 들고 있었다 — `stored in addr`, 즉 **주소 원문 전체**와
#   대조했다. 그러면 대괄호(물건 표시) 안에 우연히 같은 글자가 있는 오염을 못 잡는다.
#   `docs/BUGS.md` #224 가 그것을 남은 위험으로 적어 둉고("원문에 있으면 통과 라 위 유형을
#   여전히 못 잡는다"), 2026-09-01 이 머신에서 실제로 그렇게 갈렸다:
#
#       이 스크립트                       오염 의심 **0건**
#       test_pipeline_integrity §12    오염 **1건** (id=1768 `sigungu='갑구'`)
#
#   같은 질문에 두 도구가 다른 답을 했고, **감사 쪽이 틀렸다.** 규칙을 세 벌 두면
#   이런 날이 반드시 온다 — 그래서 백필과 가드가 이미 쓰고 있는 함수 하나를 같이 쓴다.
from backfill_region_normalize import is_stale_contamination

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
            if is_stale_contamination(stored, new, addr):
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
