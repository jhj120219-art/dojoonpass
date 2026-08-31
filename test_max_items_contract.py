# -*- coding: utf-8 -*-
"""`MAX_ITEMS` 계약 — 하나의 상수가 **서로 다른 두 가지**를 제한한다.

2026-08-20 Sprint 237 신설 (BUGS #174).

## 발견

`MAX_ITEMS = 10` 은 이름이 하나인데 쓰이는 곳이 둘이고, **의미가 다르다.**

    crawler/court_crawler.py  crawl_court()        그날 이 법원에서 몇 건을 가져올까
                                                   -> **공급 상한** (정책)
    crawler/base_crawler.py   go_to_case_detail()  이미 아는 사건을 찾으려고 몇 행을 훑을까
                                                   -> **조회 창** (검색 반경)

두 번째는 정책이 아니다. 그런데 같은 손잡이를 돌린다. 공급을 줄이려고 이 값을
내리면 **이미 큐에 들어 있는 사건을 찾지 못하게 된다** - 조용히, 그리고
"사건 매칭 실패"라는 원인을 짐작하기 어려운 로그만 남기고.

## 실측 (2026-08-20, logs/scraper.log + daily_run.log, 1,698회)

    수집 건수 분포가 1~10 에 걸쳐 있고 **10에서 205회(12.1%) 몰린다.**
    분포가 완만한데 상한값만 튀는 것은 그 상한이 **실제로 걸리고 있다**는 뜻이다.

    -> 실행의 12.1% 에서 그 법원의 물건 일부가 **아예 수집되지 않았다.**

## ★ 말할 수 없는 것

"상한을 N 으로 올리면 공급이 얼마가 된다"는 **로그로 알 수 없다.**
자료가 10에서 오른쪽으로 잘려 있다(right-censored). 그 너머를 알려면 상한 없이
크롤을 돌려야 하고 그것은 승인 영역이다. 그래서 이 파일은 반대 방향으로 계산한다 —
**처리 능력이 감당할 수 있는 공급이 얼마인가.**

    python test_max_items_contract.py
"""
import io
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import config.settings as cfg                      # noqa: E402

failures = []
CHECKS = [0]


def check(name, actual, expected):
    CHECKS[0] += 1
    ok = actual == expected
    print("[%s] %s: %r (expected %r)" % ("PASS" if ok else "FAIL", name, actual, expected))
    if not ok:
        failures.append(name)


def check_true(name, cond, detail=""):
    CHECKS[0] += 1
    print("[%s] %s%s" % ("PASS" if cond else "FAIL", name, "" if cond else " -- " + str(detail)))
    if not cond:
        failures.append(name)


# 실측 상수 (2026-08-20). 바꾸려면 다시 재고 근거를 남긴다.
NAV_SECONDS = 15.2
ROW_SECONDS = 23.2
SUPPLY_MEDIAN = 106
CAPPED_RATIO_BASELINE = 12.1        # 상한에 걸린 실행 비율(%)


def _code_of(path):
    """주석·독스트링을 걷어낸 소스. **주석을 코드로 오인하지 않기 위해서다.**"""
    src = io.open(path, encoding="utf-8-sig").read()
    kept = []
    for line in src.splitlines():
        if line.lstrip().startswith("#"):
            continue
        kept.append(line.split("  #")[0])
    body = "\n".join(kept)
    out, depth = [], 0
    for chunk in body.split('"""'):
        if depth % 2 == 0:
            out.append(chunk)
        depth += 1
    return "".join(out)


def test_max_items_has_two_distinct_meanings():
    """한 상수가 두 곳에서 **다른 뜻으로** 쓰인다는 사실을 고정한다."""
    print("\n--- 1. MAX_ITEMS 가 닿는 두 곳 ---")
    sites = []
    for path in ("crawler/base_crawler.py", "crawler/court_crawler.py"):
        code = _code_of(path)
        lines = code.split("\n")
        for i, l in enumerate(lines):
            if "collect_list_items(" in l and "def " not in l:
                fn = "?"
                for j in range(i, -1, -1):
                    m = re.match(r"^def (\w+)", lines[j])
                    if m:
                        fn = m.group(1)
                        break
                sites.append((os.path.basename(path), fn))
    print("    호출 지점: %s" % sites)
    check_true("검사가 공허하지 않다(호출 지점을 실제로 찾았다)", len(sites) >= 2, sites)
    fns = sorted(set(f for _, f in sites))
    check("★ 두 곳에서 쓰인다(공급 / 조회)", fns, ["crawl_court", "go_to_case_detail"])

    # 각각이 실제로 어느 진입점의 경로인지 - grep 이 아니라 import 그래프로
    dw = _code_of("doc_worker.py")
    ms = _code_of("mvp_scraper.py")
    check_true("★ 문서 워커가 쓰는 것은 **조회** 쪽이다",
               "go_to_case_detail" in dw and "crawl_court" not in dw,
               "doc_worker 가 crawl_court 를 부르면 이 모델이 틀린다")
    check_true("★ 06:00 크롤이 쓰는 것은 **공급** 쪽이다",
               "crawl_court" in ms,
               "mvp_scraper 가 crawl_court 를 부르지 않는다")


# 조회 창 >= 공급 상한 인가. **판정은 여기 한 곳에만 둔다** — 아래 실제 검사와
# 자기 검증이 각자 구현하면 갈라진다(이 저장소가 BUGS #204/#224 에서 반복해 겪은 모양).
def _lookup_window_ok(lookup_win: int, supply_cap: int) -> bool:
    return lookup_win >= supply_cap


def test_lookup_window_is_not_smaller_than_supply_cap():
    """조회 창이 공급 상한보다 좁으면 **큐에 있는 사건을 못 찾는다.**

    ## ★ 2026-08-26 (`docs/BUGS.md` #231) — 이 검사는 **공허했다**

    예전 판은 이랬다.

        supply_cap = cfg.MAX_ITEMS
        lookup_win = getattr(cfg, "CASE_LOOKUP_MAX_ROWS", cfg.MAX_ITEMS)
        check_true("조회 창이 공급 상한보다 좁지 않다", lookup_win >= supply_cap)

    `CASE_LOOKUP_MAX_ROWS` 는 **settings 에 존재하지 않는다**(2026-08-26 확인).
    그래서 폴백이 걸려 두 값이 **같은 객체**가 되고, 단언은 `X >= X` 가 된다 —
    `MAX_ITEMS` 를 1 이든 999 든 0 이든 -5 든 **무엇으로 바꿔도 통과한다**(실측).

    앞을 내다본 의도(*"나중에 둘을 분리하더라도 관계를 지킨다"*)는 옳다. 문제는 그
    의도를 적어 두기만 하고, **오늘 검증력이 0 이라는 사실은 말하지 않았다**는 것이다.
    읽는 사람은 PASS 를 보고 관계가 확인됐다고 믿는다.

    ## 그래서 두 가지로 나눈다

    1. **지금 상태를 정직하게 보고한다** — 아직 한 상수인지, 분리됐는지.
    2. **판정 로직에 오늘 이빨을 준다** — 합성 값으로 위반/정상을 실제로 가려낸다.
       분리가 실제로 들어오는 날 이 검사가 동작한다는 것을 지금 증명해 둔다.
    """
    print("\n--- 2. 조회 창 >= 공급 상한 (BUGS #231) ---")
    supply_cap = cfg.MAX_ITEMS
    split = hasattr(cfg, "CASE_LOOKUP_MAX_ROWS")
    lookup_win = getattr(cfg, "CASE_LOOKUP_MAX_ROWS", cfg.MAX_ITEMS)
    print("    공급 상한 %d / 조회 창 %d / 상수 분리 여부: %s"
          % (supply_cap, lookup_win, "분리됨" if split else "아직 한 상수(MAX_ITEMS)"))

    check_true("공급 상한이 양수다(검사가 공허하지 않다)", supply_cap > 0, supply_cap)

    if split:
        # 분리된 뒤에는 **진짜 관계 검사**다.
        check_true("★ 조회 창이 공급 상한보다 좁지 않다",
                   _lookup_window_ok(lookup_win, supply_cap),
                   "조회 창 %d < 공급 상한 %d - 큐에 있는데 목록에서 못 찾는 사건이 생긴다"
                   % (lookup_win, supply_cap))
    else:
        # ★ 폴백이 사는 한 위 단언은 `X >= X` 라 **항상 참**이다. 통과로 세지 않는다 —
        #   "검증했다"와 "검증할 것이 없었다"를 섞지 않는 것이 이 저장소의 규약이다.
        print("    (아직 한 상수라 관계가 자동 성립한다. 이 조합에서는 검증력이 없다.")
        print("     아래 합성 검증이 '분리되는 날 이 검사가 동작한다'를 대신 증명한다)")
        check("전제: 폴백이 걸리면 두 값이 같다(그래서 위 비교는 공허하다)",
              lookup_win, supply_cap)

    # ------------------------------------------------------------------
    # ★ 오늘 이빨 — 합성 값으로 판정 로직을 실제로 태운다.
    #   `CASE_LOOKUP_MAX_ROWS` 가 생기는 날, 그 값이 작으면 붉어진다는 것을 지금 못박는다.
    # ------------------------------------------------------------------
    check("합성 검증: 조회 창이 좁으면 위반이다 (5 < 10)",
          _lookup_window_ok(5, 10), False)
    check("합성 검증: 같으면 정상이다 (10 == 10)",
          _lookup_window_ok(10, 10), True)
    check("합성 검증: 넓으면 정상이다 (20 > 10)",
          _lookup_window_ok(20, 10), True)
    check("합성 검증: 경계 바로 아래는 위반이다 (9 < 10)",
          _lookup_window_ok(9, 10), False)

    # 그리고 **분리가 실제로 들어왔을 때** 위 분기가 진짜 값을 쓰는지도 고정한다.
    # (분기 자체가 죽어 있으면 분리되는 날에도 아무 일이 일어나지 않는다)
    import types as _types
    fake = _types.SimpleNamespace(MAX_ITEMS=10, CASE_LOOKUP_MAX_ROWS=5)
    check("합성 검증: 분리된 설정을 읽으면 위반을 잡아낸다",
          _lookup_window_ok(getattr(fake, "CASE_LOOKUP_MAX_ROWS", fake.MAX_ITEMS),
                            fake.MAX_ITEMS), False)


def test_truncation_is_real():
    """`collect_list_items` 가 정말로 잘라내는지 **실제로 불러서** 확인한다.

    가짜 DOM 을 만들어 진짜 함수를 태운다. 상한이 걸리면 그 너머 행은
    돌아오지 않는다 - 이것이 12.1% 실행에서 실제로 벌어진 일이다.
    """
    print("\n--- 3. 상한이 실제로 잘라내는가 (진짜 함수) ---")
    import crawler.base_crawler as bc
    from selenium.webdriver.common.by import By

    N_ITEMS = 19          # DB 실측 최대: 성남지원 2026-07-20 에 19건

    class Cell(object):
        def __init__(self, text, onclick=None):
            self.text = text
            self._onclick = onclick

        def find_element(self, by, sel):
            if self._onclick is None:
                raise Exception("no link")
            return Link(self._onclick)

    class Link(object):
        def __init__(self, oc):
            self._oc = oc

        def get_attribute(self, name):
            return self._oc if name == "onclick" else None

    class Row(object):
        def __init__(self, cells):
            self._cells = cells

        def find_elements(self, by, tag):
            return self._cells

    class Driver(object):
        def __init__(self, rows):
            self._rows = rows

        def find_elements(self, by, sel):
            return self._rows

    rows = []
    for k in range(N_ITEMS):
        main = [
            Cell(""),                                   # 0
            Cell("2024타경%d" % (1000 + k)),            # 1 사건번호
            Cell("1"),                                  # 2 물건번호
            Cell("서울시 어딘가 %d" % k, "moveDtlPage(%d)" % k),   # 3 주소(링크)
            Cell(""), Cell(""),                          # 4,5
            Cell("100,000,000"),                        # 6 감정가
            Cell("2026.09.01"),                         # 7 기일
        ]
        rows.append(Row(main))
        rows.append(Row([Cell("유찰")]))                # 상태 줄 (i += 2)

    got_capped = bc.collect_list_items(Driver(rows), cfg.MAX_ITEMS)
    got_full = bc.collect_list_items(Driver(rows), 1000)

    print("    목록에 %d건이 있는 페이지" % N_ITEMS)
    print("    상한 %d 로 훑으면 %d건 / 상한 없이 훑으면 %d건"
          % (cfg.MAX_ITEMS, len(got_capped), len(got_full)))
    check_true("검사가 공허하지 않다(가짜 DOM 이 실제로 파싱됐다)",
               len(got_full) == N_ITEMS, (len(got_full), N_ITEMS))
    check("★ 상한이 실제로 잘라낸다", len(got_capped), cfg.MAX_ITEMS)

    # 잘린 뒤에는 그 사건을 **찾을 수 없다**
    target = "2024타경%d" % (1000 + N_ITEMS - 1)      # 마지막(19번째) 사건
    found_capped = [x for x in got_capped if target in x["case_no"]]
    found_full = [x for x in got_full if target in x["case_no"]]
    check("★ 상한 안에서는 %s 를 찾지 못한다" % target, len(found_capped), 0)
    check("상한 없이는 찾는다(대조군)", len(found_full), 1)


def test_cap_actually_binds_in_production_logs():
    """상한이 **실제로 걸리고 있는가** — 로그에서 센다."""
    print("\n--- 4. 상한이 실제로 걸린 비율 (로그) ---")
    import glob
    from collections import Counter
    c = Counter()
    for f in glob.glob(os.path.join("logs", "*.log")):
        try:
            t = io.open(f, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        for n in re.findall(r"목록 수집 완료: (\d+)건", t):
            c[int(n)] += 1
    total = sum(c.values())
    if not total:
        print("[SKIP] 크롤 로그가 없다 (fresh clone)")
        return
    capped = c.get(cfg.MAX_ITEMS, 0)
    ratio = 100.0 * capped / total
    over = sum(v for k, v in c.items() if k > cfg.MAX_ITEMS)
    print("    실행 %d회 / 상한(%d)에 걸린 것 %d회 = **%.1f%%**"
          % (total, cfg.MAX_ITEMS, capped, ratio))
    check_true("검사가 공허하지 않다(로그에 실행 기록이 있다)", total >= 100, total)
    check("★ 상한을 넘는 수집은 존재하지 않는다(상한이 진짜 상한이다)", over, 0)
    check_true("★ 상한이 실제로 걸리고 있다(공급이 잘리고 있다)",
               ratio > 1.0,
               "%.1f%% - 걸리지 않는다면 MAX_ITEMS 는 병목이 아니다" % ratio)
    print("    -> 자료가 %d 에서 **오른쪽으로 잘려 있다.** 상한을 올렸을 때의 공급은"
          % cfg.MAX_ITEMS)
    print("       로그로 알 수 없다(승인 없이는 확인 불가). 아래는 **역산**이다.")


def test_capacity_defines_the_safe_supply_ceiling():
    """올려도 되는 한계는 **처리 능력**이 정한다 (역산)."""
    print("\n--- 5. 처리 능력이 정하는 안전 공급 상한 ---")

    def mins(h):
        a, b = h.split(":")
        return int(a) * 60 + int(b)

    n = len(cfg.DOC_TYPE_LIST)
    per_row_non_nav = ROW_SECONDS - NAV_SECONDS
    item_sec = NAV_SECONDS + n * per_row_non_nav
    window = (mins(cfg.DOC_WORKER_END_TIME) - mins(cfg.DOC_WORKER_START_TIME)) * 60
    capacity = window / item_sec
    headroom = capacity / float(SUPPLY_MEDIAN)

    print("    물건 1건 %.1f초 / 창 %d초 -> 능력 **%.0f건/일**" % (item_sec, window, capacity))
    print("    공급 중앙값 %d건 -> 여유 **%.2f배** (%+.0f건)"
          % (SUPPLY_MEDIAN, headroom, capacity - SUPPLY_MEDIAN))
    check_true("검사가 공허하지 않다(창과 능력이 양수다)",
               window > 0 and capacity > 0, (window, capacity))
    check_true("★ 지금 능력이 지금 공급을 감당한다", capacity >= SUPPLY_MEDIAN,
               "능력 %.0f < 공급 %d" % (capacity, SUPPLY_MEDIAN))
    print("    -> 공급이 지금의 %.2f배가 되기 전까지만 안전하다." % headroom)
    print("       MAX_ITEMS 를 올리면 공급이 얼마나 느는지는 알 수 없으므로,")
    print("       **먼저 창을 넓혀 여유를 만든 뒤** 올리는 것이 순서다.")

    # 창을 넓혔을 때의 여유 (정책 변경 아님 - 계산만)
    for end in ("05:38", "05:55"):
        w = (mins(end) - mins(cfg.DOC_WORKER_START_TIME)) * 60
        capw = w / item_sec
        print("       창 ~%s 이면 능력 %.0f건 -> 여유 %.2f배"
              % (end, capw, capw / float(SUPPLY_MEDIAN)))
    check_true("★ 순서가 성립한다(창을 넓히면 여유가 늘어난다)",
               ((mins("05:38") - mins(cfg.DOC_WORKER_START_TIME)) * 60 / item_sec)
               > capacity,
               "창 확대가 여유를 늘리지 않는다면 이 순서 주장이 틀린 것이다")


def test_lookup_and_supply_share_one_knob_is_recorded():
    """두 의미가 한 손잡이를 공유한다는 사실이 **문서에 남아 있는가.**"""
    print("\n--- 6. 위험이 기록돼 있는가 ---")
    doc = ""
    for p in ("docs/crawler.md", "docs/CURRENT_STATE.md", "docs/BUGS.md"):
        if os.path.exists(p):
            doc += io.open(p, encoding="utf-8-sig").read()
    check_true("검사가 공허하지 않다(문서를 실제로 읽었다)", len(doc) > 1000, len(doc))
    check_true("★ MAX_ITEMS 의 두 가지 의미가 문서에 적혀 있다",
               "go_to_case_detail" in doc and "MAX_ITEMS" in doc,
               "문서에 없으면 다음 사람이 공급만 보고 값을 내린다")


def run():
    print("=" * 66)
    print(" MAX_ITEMS 계약 (Sprint 237)")
    print("=" * 66)
    test_max_items_has_two_distinct_meanings()
    test_lookup_window_is_not_smaller_than_supply_cap()
    test_truncation_is_real()
    test_cap_actually_binds_in_production_logs()
    test_capacity_defines_the_safe_supply_ceiling()
    test_lookup_and_supply_share_one_knob_is_recorded()

    print("\n" + "=" * 66)
    if failures:
        print("FAILED (%d/%d): %s" % (len(failures), CHECKS[0], ", ".join(failures)))
        return 1
    print("ALL MAX_ITEMS CONTRACT TESTS PASSED (%d checks)" % CHECKS[0])
    return 0


if __name__ == "__main__":
    sys.exit(run())
