"""'끝나지 않는 수집중'이 몇 건이고 **왜** 그런지 센다. 아무것도 쓰지 않는다.

2026-08-14 신설. `cleanup_orphans_dryrun.py`와 같은 관례를 따른다 ―
**`--apply` 가 아예 없다.** 이 스크립트는 측정만 한다.

왜 쓰지 않는가
-----------------------------------------------------------------------------
"수집 대상이 아닌 문서를 화면에 무엇으로 표시할 것인가"는 **결정되지 않은 제품 판단**이다.
Sprint 73이 검토하고 보류했다 ― `document_status` enum은
COLLECTING / OCR / PARSING / ANALYZING / READY / FAILED 뿐이라 "대상 아님"을 담을 값이 없고,
FAILED로 쓰면 실패가 아닌 것을 실패로 표기하게 된다. 새 상태를 만드는 것은
상태머신과 화면 문구를 함께 정하는 일이라 제품 결정이다.

`test_document_status_sync.py` §6이 현재 동작(COLLECTING 유지)을 고정하고 있고,
배선하는 순간 그 검사가 실패하면서 함께 고쳐야 할 지점을 지목한다.

그래서 이 스크립트는 **결정에 필요한 숫자만** 제공한다.

무엇을 새로 알려주는가
-----------------------------------------------------------------------------
§6은 원인 하나(큐가 SKIPPED_EXPIRED로 종결됨, 183건)만 셌다.
2026-08-14 측정에서 **더 큰 두 번째 원인**이 드러났다 ― 기일 경과로 **애초에 큐에 넣지
않은** 문서다. 이쪽은 큐 행 자체가 없어 어떤 종결 함수도 지나지 않으므로,
`mark_queue_skipped_expired()`를 고쳐도 그대로 남는다.

정책을 정할 때 **두 경로를 함께** 봐야 한다는 것이 이 측정의 요점이다.

    python measure_endless_collecting.py
"""
import os
import sqlite3
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ★ DB 경로는 **현재 작업 디렉터리가 아니라 이 파일 기준**이다 (2026-08-21 Sprint 246).
#   상대경로면 다른 폴더에서 실행했을 때 그 폴더에 0바이트 auction.db 가 생기고
#   "no such table" 로 죽는다(실측). 운영 도구가 엉뚱한 DB 를 보는 것보다 낫지만,
#   찌꺼기 파일이 남고 오류 문구가 원인을 가린다.
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "auction.db")

# 2026-08-18 Sprint 189: 여기 있던 하드코딩 집합 {"pending","processing","in_progress"}는
# (1) 실제로 없는 값("processing")을 세고 (2) 새로 생긴 재수집 어휘를 못 셌다.
# 큐 상태 어휘의 단일 소스는 `storage/database.py`다 — 거기서 가져온다.
from storage.database import QUEUE_ACTIVE_STATUSES  # noqa: E402  (sys.path 설정 뒤라야 한다)

ACTIVE_QUEUE = set(QUEUE_ACTIVE_STATUSES)


def main() -> int:
    conn = sqlite3.connect("file:%s?mode=ro" % DB_PATH.replace("\\", "/"), uri=True)
    conn.row_factory = sqlite3.Row
    try:
        today = conn.execute("SELECT date('now','localtime')").fetchone()[0]

        item_key, item_date = {}, {}
        for r in conn.execute("SELECT id, court_name, case_no, item_no, auction_date"
                              " FROM auction_item"):
            item_key[r["id"]] = (r["court_name"], r["case_no"], str(r["item_no"] or "1"))
            item_date[r["id"]] = r["auction_date"] or ""

        queue = {}
        for r in conn.execute("SELECT court_code, case_no, item_no, doc_type, status"
                              " FROM document_queue"):
            # 큐는 소문자 doc_type, document_status는 대문자 ― 비교 전에 맞춘다.
            k = (r["court_code"], r["case_no"], str(r["item_no"] or "1"),
                 (r["doc_type"] or "").upper())
            queue.setdefault(k, []).append(r["status"])

        rows = conn.execute("SELECT item_id, doc_type, status FROM document_status").fetchall()
    finally:
        conn.close()

    buckets = Counter()
    live_visible = []
    for r in rows:
        if r["status"] != "COLLECTING":
            continue
        ik = item_key.get(r["item_id"])
        if ik is None:
            buckets["물건이 없는 상태행(고아)"] += 1
            continue
        st = queue.get((ik[0], ik[1], ik[2], (r["doc_type"] or "").upper()))
        if st is None:
            bucket = "(b) 큐 행이 없다 ― 기일 경과로 애초에 넣지 않음"
        elif any(s in ACTIVE_QUEUE for s in st):
            bucket = "(정상) 큐에서 대기 중 ― 언젠가 수집된다"
        else:
            bucket = "(a) 큐가 종결됨 %s ― 다시 집히지 않는다" % (tuple(sorted(set(st))),)
        buckets[bucket] += 1
        if not bucket.startswith("(정상)") and item_date.get(r["item_id"], "") >= today:
            live_visible.append((r["item_id"], ik, r["doc_type"], item_date[r["item_id"]]))

    total = sum(buckets.values())
    print("=" * 74)
    print("document_status = COLLECTING (화면에 '수집중') : %d건" % total)
    print("=" * 74)
    for k, n in sorted(buckets.items(), key=lambda x: -x[1]):
        print("  %-52s %6d" % (k, n))

    endless = sum(n for k, n in buckets.items() if not k.startswith("(정상)"))
    print("\n  -> 이 중 **아무도 수집하지 않는** 것: %d건 (%.1f%%)"
          % (endless, 100.0 * endless / max(1, total)))

    print("\n" + "=" * 74)
    print("사용자에게 지금 보이는가")
    print("=" * 74)
    print("  오늘(로컬) = %s" % today)
    print("  끝나지 않는 '수집중' 중 **기일이 남은** 물건의 문서: %d건" % len(live_visible))
    if live_visible:
        print("    ※ 이것들은 검색(D7 기본 필터)에도 노출된다 ― 우선 대상이다.")
        for iid, ik, dt, ad in live_visible[:10]:
            print("      item=%-6s %s %s-%s %-10s 기일=%s" % (iid, ik[0], ik[1], ik[2], dt, ad))
    else:
        print("    기일이 남은 것은 없다 ― 기본 검색에는 안 보이고,")
        print("    `include_closed=true` 조회 / 찜 / 최근 본 물건 / 문서 통계에만 섞인다.")

    print("\n[측정 전용] 이 스크립트는 아무것도 쓰지 않는다.")
    print("표시 정책이 정해지면 그때 반영 스크립트를 만든다"
          " (test_document_status_sync.py §6 참고).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
