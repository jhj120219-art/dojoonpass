"""`auction_item.building_area` / `land_area` 를 `full_address` 원문에서 채운다.

2026-08-26 신설 (migration 025 와 짝). 같은 계열의 다른 백필 스크립트
(`backfill_doc_raw.py`, `backfill_region_normalize.py`)와 **같은 관례**를 따른다 —
기본은 dry-run, `--apply` 를 줘야 실제로 쓴다.

왜 필요한가
-----------------------------------------------------------------------------
검색 폼에는 건물면적·토지면적 입력이 이미 있고 값도 보낸다. 그런데 대응 컬럼이 없어
백엔드가 **읽지 않았다** — 사용자가 면적을 좁혀도 결과가 그대로였다. 오류도 안내도
없어서 틀렸다는 것을 알 수 없는 부류다.

migration 025 가 컬럼을 만들었고, 이 스크립트가 **이미 수집해 둔 주소 원문**에서 값을
뽑아 채운다. 앞으로 들어오는 행은 `migrate_execute.py` 가 같은 함수로 채운다.

무엇을 근거로 하는가
-----------------------------------------------------------------------------
추출 규칙의 정본은 `normalizer/normalizer.py:extract_areas()` 하나다. 여기서 규칙을
다시 쓰지 않는다 — 같은 어휘가 두 곳에 있으면 갈라진다(BUGS #204 가 경계한 그것).

실측 커버리지 (2026-08-26, auction_item 2,444행)

    건물면적만  1,454 (59.5%)
    토지면적만    974 (39.9%)
    둘 다 보유      0 (0.0%)   <- ★ 한 물건은 둘 중 하나만 갖는다
    둘 다 없음     16 (0.7%)   <- 전부 차량/선박/건설기계다. 면적 개념이 없다
    커버리지    99.3%          <- ★ '둘 중 하나라도 가진' 비율이다

★ 이 99.3% 를 "각 면적 컬럼의 보유율"로 읽으면 안 된다 — 그렇게 읽은 코드가 실제로
  있었다(`api/v1/search.py` / `SearchForm.tsx` 가 "면적 미상 = 차량/선박 16행"이라고
  적어 뒀다). 두 컬럼은 독립 속성이 아니라 **판별 합집합**이라 컬럼별 보유율은

    building_area 보유 60.0%  (미보유 1,023행 = 전답·임야 등 토지형)
    land_area     보유 39.3%  (미보유 1,552행 = 아파트·오피스텔 등 건물형)

  이고, 그래서 두 면적을 AND 로 묶으면 만족 가능한 행이 0이다. 자세한 것은
  `docs/BUGS.md` #239.

안전성
-----------------------------------------------------------------------------
- `building_area` / `land_area` **두 컬럼만** UPDATE 한다. 다른 컬럼은 읽기만 한다.
- 지우는 동작이 없다. 행을 만들지도 않는다.
- 값을 뽑지 못한 행은 **건드리지 않는다**(NULL 로 남는다) — 0 으로 채우면
  "면적 0㎡ 인 물건"이 되어 `min_building_area=0` 검색에 걸린다.
- `--apply` 없이는 아무것도 쓰지 않는다.
- 이미 값이 있는 행은 기본적으로 건너뛴다. `--force` 를 주면 다시 계산해 덮어쓴다
  (추출 규칙을 고친 뒤 전체를 다시 매길 때 쓴다).

    python backfill_area.py                # dry-run
    python backfill_area.py --apply
    python backfill_area.py --apply --force
"""
import argparse
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from storage.database import get_connection          # noqa: E402
from normalizer.normalizer import extract_areas      # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="실제로 DB에 쓴다 (없으면 dry-run)")
    ap.add_argument("--force", action="store_true",
                    help="이미 값이 있는 행도 다시 계산해 덮어쓴다")
    args = ap.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print("=== 면적 백필 %s%s ===" % (mode, " --force" if args.force else ""))

    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, full_address, building_area, land_area FROM auction_item"
        ).fetchall()

        total = len(rows)
        already = 0        # 이미 값이 있어 건너뛴 행
        no_area = 0        # 주소에서 면적을 못 찾은 행(차량 등)
        unchanged = 0      # 계산했지만 값이 이미 같은 행
        planned = []       # (id, building, land)

        for r in rows:
            cur_b, cur_l = r["building_area"], r["land_area"]
            if not args.force and (cur_b is not None or cur_l is not None):
                already += 1
                continue

            got = extract_areas(r["full_address"] or "")
            b, l = got["building_area"], got["land_area"]
            if b is None and l is None:
                no_area += 1
                continue
            if b == cur_b and l == cur_l:
                unchanged += 1
                continue
            planned.append((r["id"], b, l))

        print("  auction_item 전체            : %d" % total)
        print("  이미 값이 있어 건너뜀        : %d" % already)
        print("  주소에 면적 표기가 없음      : %d  (차량/선박/건설기계 등)" % no_area)
        print("  계산했으나 값이 같음         : %d" % unchanged)
        print("  기록 예정                    : %d" % len(planned))

        if planned:
            b_cnt = sum(1 for _, b, _ in planned if b is not None)
            l_cnt = sum(1 for _, _, l in planned if l is not None)
            print("    그중 건물면적 : %d" % b_cnt)
            print("    그중 토지면적 : %d" % l_cnt)
            print("  샘플:")
            for pid, b, l in planned[:5]:
                print("    id=%-6s building=%-12s land=%s" % (pid, b, l))

        if not args.apply:
            print("\n[DRY-RUN] 아무것도 쓰지 않았다.")
            print("반영하려면: python backfill_area.py --apply")
            return 0

        done = 0
        for pid, b, l in planned:
            conn.execute(
                "UPDATE auction_item SET building_area=?, land_area=? WHERE id=?",
                (b, l, pid),
            )
            done += 1
            if done % 500 == 0:
                print("  ... %d건" % done)
        conn.commit()

        filled_b = conn.execute(
            "SELECT COUNT(*) FROM auction_item WHERE building_area IS NOT NULL"
        ).fetchone()[0]
        filled_l = conn.execute(
            "SELECT COUNT(*) FROM auction_item WHERE land_area IS NOT NULL"
        ).fetchone()[0]
        covered = conn.execute(
            "SELECT COUNT(*) FROM auction_item"
            " WHERE building_area IS NOT NULL OR land_area IS NOT NULL"
        ).fetchone()[0]

        print("\n[APPLIED] %d행 기록" % done)
        print("  building_area 보유 : %d" % filled_b)
        print("  land_area 보유     : %d" % filled_l)
        print("  둘 중 하나라도 보유: %d / %d  (%.1f%%)"
              % (covered, total, 100.0 * covered / max(1, total)))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
