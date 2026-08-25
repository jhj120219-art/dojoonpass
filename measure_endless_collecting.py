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


# ---------------------------------------------------------------------------
# "큐 행이 없다"의 이유를 **증거로** 고른다 (2026-08-25 정정, BUGS #189)
#
# 예전에는 이 갈래 전체가 통짜로 "기일 경과로 애초에 넣지 않음" 이라고 찍혔다.
# 그것은 측정이 아니라 **가정**이었고, 실측하니 틀렸다 — 2026-08-25 기준 이 갈래
# 2,145건(물건 716개)은 **전부** `auction_date >= crawl_date` 다. 즉 수집 시점에
# 기일이 남아 있었고, 기일 때문에 빠진 것이 아니다.
#
# 진짜 원인은 migration 018 이 자기 헤더에 이미 적어 둔 것이다(BUGS #48):
# 018 이전의 `UNIQUE(court_code, case_no, doc_type)` 는 item_no 를 포함하지 않아
# **한 사건의 두 번째 물건부터 INSERT OR IGNORE 에 조용히 먹혔다.** 018 이 그때 센
# 숫자가 "자기 item_no 로 큐에 없는 물건 716 / 1,870 (38%)" 로, 오늘 값과 정확히 같다.
#
# 라벨이 왜 중요한가 — 이 스크립트의 존재 이유가 "표시 정책을 정하는 데 필요한 숫자"를
# 주는 것이다. "어차피 기일 지난 것"과 "스키마 결함으로 잃은 것"은 정반대의 결정을
# 부른다. 그래서 추측하지 않고 세 갈래로 나누되, 모르는 것은 모른다고 남긴다.
# ---------------------------------------------------------------------------
def no_queue_reason(court, case_no, item_no, auction_date, crawl_date, case_items):
    """큐 행이 없는 이유를 증거로 고른다. 순수 함수 — selftest 가 DB 없이 검증한다."""
    if auction_date and crawl_date and auction_date < crawl_date:
        return "(b1) 큐 행 없음 ― 수집 시점에 이미 기일 경과"
    others = case_items.get((court, case_no)) or set()
    if others and item_no not in others:
        return "(b2) 큐 행 없음 ― 같은 사건의 다른 물건만 큐에 있다 (018 이전 UNIQUE 충돌)"
    if not others:
        return "(b3) 큐 행 없음 ― 같은 사건 전체가 큐에 없다 (이유 미상)"
    return "(b4) 큐 행 없음 ― 같은 item_no 가 큐에 있는데 doc_type 만 없다"


def main() -> int:
    conn = sqlite3.connect("file:%s?mode=ro" % DB_PATH.replace("\\", "/"), uri=True)
    conn.row_factory = sqlite3.Row
    try:
        today = conn.execute("SELECT date('now','localtime')").fetchone()[0]

        item_key, item_date, item_crawl = {}, {}, {}
        for r in conn.execute("SELECT id, court_name, case_no, item_no, auction_date,"
                              " crawl_date FROM auction_item"):
            item_key[r["id"]] = (r["court_name"], r["case_no"], str(r["item_no"] or "1"))
            item_date[r["id"]] = r["auction_date"] or ""
            item_crawl[r["id"]] = r["crawl_date"] or ""

        queue = {}
        case_items = {}
        for r in conn.execute("SELECT court_code, case_no, item_no, doc_type, status"
                              " FROM document_queue"):
            # 큐는 소문자 doc_type, document_status는 대문자 ― 비교 전에 맞춘다.
            k = (r["court_code"], r["case_no"], str(r["item_no"] or "1"),
                 (r["doc_type"] or "").upper())
            queue.setdefault(k, []).append(r["status"])
            case_items.setdefault((r["court_code"], r["case_no"]), set()).add(
                str(r["item_no"] or "1"))

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
            bucket = no_queue_reason(ik[0], ik[1], ik[2],
                                     item_date.get(r["item_id"], ""),
                                     item_crawl.get(r["item_id"], ""),
                                     case_items)
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
    print("    ※ 이 숫자는 **이 머신이 여는 DB** 기준이다."
          " 개발 머신과 운영 크롤 머신이 다를 수 있고, 개발 DB 에서 나온 값을"
          " 제품 상태로 읽으면 안 된다 (docs/BUGS.md #200).")
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


# ---------------------------------------------------------------------------
# selftest - `no_queue_reason()` 만 검증한다. DB 도 네트워크도 쓰지 않는다.
#
# 왜 필요한가: 이 함수가 잘못 분류하면 나오는 것은 오류가 아니라 **그럴듯한 숫자**다.
# 예전 판이 정확히 그랬다 - 2,145건을 통짜로 "기일 경과"라고 찍었고, 그 값이 스프린트
# 문서로 옮겨져 "어차피 지난 것"이라는 결론까지 갔다. 라벨은 조용히 틀린다.
# ---------------------------------------------------------------------------
def selftest() -> int:
    fails = []

    def check(name, actual, expected):
        ok = actual == expected
        print("  [%s] %s: %r (기대 %r)" % ("PASS" if ok else "FAIL", name, actual, expected))
        if not ok:
            fails.append(name)

    def tag(r):
        return r.split(")")[0] + ")"

    print("--- selftest: 큐 행이 없는 이유 분류 ---")
    CI = {("수원지방법원", "2024타경1"): {"1"}}

    check("수집 시점에 기일이 지났으면 b1",
          tag(no_queue_reason("수원지방법원", "2024타경1", "1", "2026-07-01", "2026-07-10", CI)),
          "(b1)")
    check("★ 기일이 남아 있었으면 b1 이 아니다(예전 판의 오류)",
          tag(no_queue_reason("수원지방법원", "2024타경1", "2", "2026-09-01", "2026-07-10", CI)),
          "(b2)")
    check("같은 사건의 다른 물건만 큐에 있으면 b2 (018 충돌)",
          tag(no_queue_reason("수원지방법원", "2024타경1", "3", "", "", CI)), "(b2)")
    check("같은 사건이 큐에 아예 없으면 b3(이유 미상)",
          tag(no_queue_reason("수원지방법원", "2024타경9", "1", "", "", CI)), "(b3)")
    check("자기 item_no 가 큐에 있으면 b4(doc_type 만 빠짐)",
          tag(no_queue_reason("수원지방법원", "2024타경1", "1", "", "", CI)), "(b4)")

    # 날짜가 없으면 기일로 판정하지 않는다 - "모른다"를 "지났다"로 읽지 않는다.
    check("auction_date 가 없으면 b1 로 몰지 않는다",
          tag(no_queue_reason("수원지방법원", "2024타경1", "2", "", "2026-07-10", CI)), "(b2)")
    check("crawl_date 가 없으면 b1 로 몰지 않는다",
          tag(no_queue_reason("수원지방법원", "2024타경1", "2", "2026-01-01", "", CI)), "(b2)")
    check("case_items 가 비어도 죽지 않는다",
          tag(no_queue_reason("법원", "사건", "1", "", "", {})), "(b3)")

    print()
    if fails:
        print("selftest 실패 %d건: %s" % (len(fails), fails))
        return 1
    print("selftest 전체 통과")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    sys.exit(main())
