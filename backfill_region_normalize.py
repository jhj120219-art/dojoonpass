"""저장된 `sido` / `sigungu` 를 **지금의 정규화 규칙**으로 다시 계산해 맞춘다.

2026-08-14 신설. `backfill_dong_normalize.py`(dong 백필)와 같은 계열이고
같은 관례를 따른다 ― 기본은 dry-run, `--apply` 를 줘야 실제로 쓴다.

왜 필요한가 (2026-08-14 실측, auction_item 1,876행)
-----------------------------------------------------------------------------
정규화 규칙이 개선됐는데 **이미 저장된 행을 다시 계산한 적이 없다.** 그래서 같은
컬럼에 옛 규칙과 새 규칙의 결과가 섞여 있다.

    sido      불일치     4행   ← 저장된 값이 **틀렸다**
    sigungu   불일치   207행 (11.0%)   ← 저장된 값이 옛 형식(구가 빠짐)
    dong      불일치     0행
    lot_number 불일치    0행

### sido 4행은 값이 틀렸다 (부분 문자열 오매칭의 잔재)

    id=8160  '경기도 시흥시 서울대학로 59-21'      저장 '서울'  -> 실제 '경기'
    id=1787  '경상남도 양산시 물금읍 부산대학로 150'  저장 '부산'  -> 실제 '경남'
    id=9977  '제주특별자치도 제주시 구좌읍 세화리'     저장 '세종'  -> 실제 '제주'
    id=550   '사용본거지 : 인천광역시 계양구 ...'    저장 '서울'  -> 실제 '인천'

주소에 든 **도로명**("서울대학로", "부산대학로")을 시도로 잘못 읽던 옛 버그의 결과다.
지금 코드는 네 건 모두 올바른 값을 낸다(재현 확인). 즉 코드는 고쳐졌고 **데이터만 남았다.**
이 행들은 지금 **엉뚱한 지역 필터에 걸린다** ― 서울을 고른 사용자에게 경기/인천 물건이 보인다.

### sigungu 207행은 형식이 옛것이다

    저장 '고양시'      -> 지금 '고양시 일산동구'
    저장 '용인시'      -> 지금 '용인시 수지구'

207행 전부 **저장값이 새 값의 접두**다(그 외 형태의 불일치는 0행). 규칙이 넓어진
방향이라는 뜻이라 덮어써도 정보가 줄지 않는다.

검색은 `sigungu LIKE '%값%'` 부분일치를 쓰므로(`api/v1/search.py`), 시 이름으로
찾으면 둘 다 나온다. 그러나 **구까지 넣어 찾으면 옛 행이 통째로 빠진다** ― 실측:

    sigungu LIKE '안산시 단원구'  ->    0행   (안산시 자체는 31행 존재)
    sigungu LIKE '용인시 기흥구'  ->    0행   (용인시 자체는  9행 존재)
    sigungu LIKE '고양시 일산동구' ->   3행   (고양시 자체는 25행 존재)

사용자에게는 "그 구에는 물건이 없다"로 보인다. 오류 메시지도 빈 화면도 아니고
**그냥 없는 것처럼 보인다** ― 가장 알아채기 어려운 실패다.

### 얼마나 급한가 (2026-08-14 측정)

    드리프트 211행 중 매각기일이 남은 행    0행
    매각기일이 지나 재크롤되지 않는 행    211행

**211행 전부가 만료 물건이다.** 그래서:

* 기본 검색(D7, 종결 제외)에는 **영향이 없다** ― 지금 뜨는 9건은 값이 정확하다.
* **"종결물건 포함"을 켠 검색에는 그대로 보인다**(`SearchForm.tsx:635`의 실제 옵션).
* 만료 물건은 다시 수집되지 않으므로 **재크롤로 저절로 낫지 않는다.**
  백필하지 않으면 영구히 틀린 채로 남는다.

즉 "당장 첫 화면이 깨진 문제"는 아니고, **놔두면 영영 안 고쳐지는 문제**다.
급하지는 않으나 미룰수록 이득이 없다.

안전성
-----------------------------------------------------------------------------
* 새 값은 `full_address` 하나에서 **결정적으로** 계산된다. 외부 입력이 없다.
* `dong` / `lot_number` 는 불일치가 0행이므로 이 스크립트가 건드리지 않는다
  (바꿀 것이 없는 컬럼을 UPDATE 대상에 넣지 않는다 ― 최소 수정).
* 새로 계산한 값이 **비어 있으면 건너뛴다.** 채워진 값을 빈 값으로 덮지 않는다.
* `auction`(크롤러 원본)과 `auction_item`(API가 읽는 표) 둘 다 맞춘다. 한쪽만 고치면
  다음 `migrate_execute.py` 실행 때 옛 값이 다시 덮어쓴다.

    python backfill_region_normalize.py            # dry-run (기본)
    python backfill_region_normalize.py --apply    # 실제 반영
"""
import os
import sys
import sqlite3

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))

from normalizer.normalizer import normalize_address, address_without_brackets

# ★ DB 경로는 **현재 작업 디렉터리가 아니라 이 파일 기준**이다 (2026-08-21 Sprint 246).
#   상대경로면 다른 폴더에서 실행했을 때 그 폴더에 0바이트 auction.db 가 생기고
#   "no such table" 로 죽는다(실측). 운영 도구가 엉뚱한 DB 를 보는 것보다 낫지만,
#   찌꺼기 파일이 남고 오류 문구가 원인을 가린다.
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "auction.db")
TARGET_COLUMNS = ("sido", "sigungu")


def plan_table(conn: sqlite3.Connection, table: str) -> dict:
    """이 테이블에서 무엇이 바뀌는지 계산한다(쓰지 않는다)."""
    rows = conn.execute(
        "SELECT id, full_address, sido, sigungu FROM %s" % table).fetchall()
    changes = []
    skipped_empty = 0
    for row in rows:
        fresh = normalize_address(row["full_address"] or "")
        for col in TARGET_COLUMNS:
            stored = (row[col] or "").strip()
            new = (fresh.get(col) or "").strip()
            if stored == new:
                continue
            if not new:
                # 새 값이 비었다 ― 원칙적으로 **채워진 값을 지우지 않는다.**
                # 정규화기가 못 읽은 것뿐일 수 있고, 그때 지우면 정보를 잃는다.
                #
                # ★ 단 하나의 예외 (2026-08-26): 저장된 값이 **주소 원문에 아예 없으면**
                #   그것은 "정규화기가 못 읽은 값"이 아니라 **다른 물건에서 흘러든 값**이다.
                #   실측 예 — id=357 `sigungu='칠곡군'` 인데 주소는
                #   "세종특별자치시 나성로 96 ..." 이다(세종시는 시군구가 없어 정규화 결과가
                #   빈 문자열이 맞다). 이 행은 `sigungu=칠곡군` 검색에 **경북이 아닌 물건**으로
                #   섞여 나온다 — 남겨 두는 쪽이 정보 보존이 아니라 **오염 유지**다.
                #
                #   판정은 추측이 아니라 원문 대조다: 저장값이 주소 문자열에 없으면 지운다.
                #   (`detect_stale_region_contamination_dryrun.py` 가 쓰는 것과 같은 근거)
                #   ★ 대괄호(= 물건 표시) 를 **뺀 주소 부분**과 대조한다 (2026-08-26).
                #     대괄호 안에는 주소 성분이 없다. 예컨대 `sigungu='갑구'` 는
                #     "[토지 임야 297㎡ 갑구 2번 ...]" 의 등기부 용어를 시군구로 잘못 읽은
                #     것인데, 원문 전체와 대조하면 '갑구' 가 **있다**고 나와 그냥 남는다.
                #     주소 부분만 보면 없다는 것이 바로 드러난다.
                addr = address_without_brackets(row["full_address"] or "")
                if stored and stored not in addr:
                    changes.append((row["id"], col, stored, "", addr))
                    continue
                skipped_empty += 1
                continue
            changes.append((row["id"], col, stored, new,
                            (row["full_address"] or "")[:56]))
    return {"table": table, "total": len(rows), "changes": changes,
            "skipped_empty": skipped_empty}


def main() -> int:
    apply = "--apply" in sys.argv
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        plans = [plan_table(conn, t) for t in ("auction", "auction_item")]

        for p in plans:
            by_col = {}
            for _, col, _, _, _ in p["changes"]:
                by_col[col] = by_col.get(col, 0) + 1
            print("== %s (%d행)" % (p["table"], p["total"]))
            for col in TARGET_COLUMNS:
                print("   %-10s 변경 대상 %4d행" % (col, by_col.get(col, 0)))
            print("   새 값이 비어 건너뜀: %d건" % p["skipped_empty"])
            for c in p["changes"][:8]:
                print("      id=%-6s %-8s %-16r -> %-22r %s" % c)
            if len(p["changes"]) > 8:
                print("      ... 외 %d건" % (len(p["changes"]) - 8))

        total = sum(len(p["changes"]) for p in plans)
        if not apply:
            print("\n[DRY-RUN] 총 %d건이 바뀔 예정이다. 아무것도 쓰지 않았다." % total)
            print("반영하려면: python backfill_region_normalize.py --apply")
            return 0

        written = 0
        for p in plans:
            for row_id, col, _, new, _ in p["changes"]:
                conn.execute("UPDATE %s SET %s = ? WHERE id = ?" % (p["table"], col),
                             (new, row_id))
                written += 1
        conn.commit()
        print("\n[APPLIED] %d건 반영" % written)

        # 반영 후 남은 불일치를 다시 세어 보고한다 ― "썼다"가 아니라 "맞아졌다"를 확인한다.
        left = sum(len(plan_table(conn, t)["changes"]) for t in ("auction", "auction_item"))
        print("반영 후 남은 불일치: %d건" % left)
        return 0 if left == 0 else 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
