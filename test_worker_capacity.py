# -*- coding: utf-8 -*-
"""문서 워커 처리 능력 계약 (Sprint 235 신설, 2026-08-20 Sprint 236 재측정).

## 왜 이 파일이 있나

이 저장소에는 큐의 **정확성** 검사는 많지만(claim 원자성 / 재시도 / 회수 / 멱등),
**처리 능력**을 보는 검사가 하나도 없었다. 그런데 출시 후 조용히 무너지는 쪽은 정확성이
아니라 능력이다 — 큐는 정상적으로 쌓이고 워커도 정상적으로 돌지만 **따라잡지 못한다.**
그 상태는 오류 로그를 남기지 않는다. 큐 길이만 매일 조금씩 늘어난다.

## 실측 (2026-08-20 Sprint 236 재측정, `logs/doc_run.log`)

★ Sprint 235 는 `법원 선택` 로그 줄 사이의 간격을 **navigate 비용**이라고 불렀다.
  그 간격에는 **수집 시간과 sleep 까지 들어 있다.** 즉 그것은 이동 비용이 아니라
  **한 행의 전체 주기**였다. 그 위에 세운 계산(능력 165건/일, batching 4.0배)은
  그래서 틀렸다. 이번에는 모델 없이 잴 수 있는 것부터 쟀다.

    의미 있는 실행 7회 합계   행 897 / 이동 897 / 물건 313 / 5.8시간
      -> 행 1개당 **23.2초**          <- 나눗셈 하나. 논쟁의 여지가 없다
      -> 행/이동 = **1.00** (전 실행)  <- 예전 코드는 행마다 이동했다

    구간 분해
      법원선택 -> 결과        중앙값 14.1초   (이동의 뒷부분 + 그 종류의 수집)
      결과 -> 다음 법원선택   중앙값  9.2초   (sleep 2초 + 이동의 앞부분, p90 9.3 - 매우 일정)
      법원선택 -> 법원선택    중앙값 23.9초   (= 위 둘의 합, 행 1개 주기)

    이동 1회 비용 = **15.2초** (Sprint 147 이 형제 재사용을 재며 독립적으로 측정한 값.
    위 분해에서 나오는 16.4초와 일치한다 - 서로 다른 두 측정이 같은 값을 가리킨다.
    둘 중 **작은 쪽**을 쓴다: 이득을 부풀리지 않기 위해서다.)

## 지금 구조 (Sprint 236 이후)

`doc_worker` 는 **한 물건의 큐 행을 한꺼번에** claim 하고 상세페이지에 **한 번만**
들어간다. 그 사실은 `test_worker_batching.py` 가 진짜 `main()` 을 돌려 확인한다
(물건 12개 x 4종 = 48행 -> 이동 12회).

    물건 1건 = 이동 1회(15.2초) + 종류마다 수집+sleep(23.2 - 15.2 = 8.0초)

## 이 검사가 잠그는 것

    doc_type 수 (config.DOC_TYPE_LIST)
    x 행당 비용 + 이동 1회
    vs 실행 창 (DOC_WORKER_START_TIME ~ DOC_WORKER_END_TIME)
    vs 실제 공급량 (auction_item.crawl_date 실측)

새 doc_type 을 추가하거나 창을 줄이면 **여기서 먼저 운다.**

    python test_worker_capacity.py
"""
import io
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import config.settings as cfg                      # noqa: E402

failures = []


def check(name, actual, expected):
    ok = actual == expected
    print("[%s] %s: %r (expected %r)" % ("PASS" if ok else "FAIL", name, actual, expected))
    if not ok:
        failures.append(name)


def check_true(name, cond, detail=""):
    print("[%s] %s%s" % ("PASS" if cond else "FAIL", name, "" if cond else " -- " + str(detail)))
    if not cond:
        failures.append(name)


# ---------------------------------------------------------------------------
# 실측 상수 — 로그에서 잰 값이다. 바꾸려면 다시 재고 근거를 남긴다.
# ---------------------------------------------------------------------------
# 행 1개의 전체 주기. 로그에서 **직접** 잰 값이다(총 소요 / 총 행수 = 23.2초).
# 모델이 아니라 나눗셈이므로 여기서 시작한다.
ROW_SECONDS = 23.2             # 실행 7회 합계 897행 / 5.8시간 (2026-08-20)

# 이동 1회 비용. Sprint 147 이 형제 재사용 이득을 재며 독립 측정한 값이고,
# 이번 구간 분해(16.4초)와 일치한다. **작은 쪽**을 써서 이득을 부풀리지 않는다.
NAV_SECONDS = 15.2

# 이동을 뺀 행당 비용(수집 + sleep 2초). 파생값이므로 따로 재지 않는다.
PER_ROW_NON_NAV = ROW_SECONDS - NAV_SECONDS      # = 8.0초

# 하루 공급 실측 (auction_item.crawl_date, 크롤이 실제로 돈 20일)
SUPPLY_MEDIAN = 106
SUPPLY_MAX = 278

# 능력 래칫 기준선 — 2026-08-20 Sprint 236 실측 기준(batching 후, doc_type 4종, 창 120분).
# 이보다 낮아지면 실패한다. 낮출 때는 **근거와 함께** 이 값을 갱신한다.
CAPACITY_BASELINE = 152


def _mins(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def window_seconds():
    return (_mins(cfg.DOC_WORKER_END_TIME) - _mins(cfg.DOC_WORKER_START_TIME)) * 60


def item_seconds(n_types, navs_per_item=1):
    """물건 1건을 끝내는 데 드는 시간.

    이동은 `navs_per_item` 회, 수집+sleep 은 종류마다 한 번씩이다.
    Sprint 236 이전 구조는 `navs_per_item=n_types` 였다(행마다 이동).
    """
    return navs_per_item * NAV_SECONDS + n_types * PER_ROW_NON_NAV


def capacity(n_types, navs_per_item=1):
    """하루에 끝낼 수 있는 **물건** 수."""
    return window_seconds() / item_seconds(n_types, navs_per_item)


def legacy_capacity(n_types):
    """Sprint 236 이전 구조(행마다 이동)의 능력."""
    return capacity(n_types, navs_per_item=n_types)


def _code_of(path):
    """주석을 걷어낸 소스. **주석을 코드로 오인하지 않기 위해서다.**

    2026-08-20 Sprint 236: Sprint 235 의 '모델 근거' 검사가 정확히 이 함정에 빠졌다.
    `"claim_next_queue_item()" in src` 가 **주석 한 줄**에 걸려 계속 통과했고,
    그래서 batching 이 들어왔는데도 초록불을 유지했다 - 자기가 잡으라고 만들어진
    바로 그 변화를 놓친 것이다. 문자열 안의 예시도 같은 위험이 있어 함께 지운다.
    """
    src = io.open(path, encoding="utf-8-sig").read()
    lines = []
    for line in src.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        lines.append(line.split("  #")[0])
    body = "\n".join(lines)
    # 독스트링 제거 (삼중 따옴표 블록)
    out = []
    depth = 0
    for chunk in body.split('"""'):
        if depth % 2 == 0:
            out.append(chunk)
        depth += 1
    return "".join(out)


def test_measured_constants_are_sane():
    """실측 상수 자체가 말이 되는가 (검사가 공허하지 않다)."""
    print("\n--- 1. 실측 상수 ---")
    check_true("행 1개 주기가 양수다", ROW_SECONDS > 0, ROW_SECONDS)
    check_true("★ 이동 비용이 행 주기보다 작다(파생값이 음수가 되지 않는다)",
               0 < NAV_SECONDS < ROW_SECONDS, (NAV_SECONDS, ROW_SECONDS))
    check_true("이동을 뺀 행당 비용이 양수다", PER_ROW_NON_NAV > 0, PER_ROW_NON_NAV)
    check_true("실행 창이 양수다", window_seconds() > 0, window_seconds())
    print("    창 %d초 (%s~%s) / navigate 중앙값 %.1f초"
          % (window_seconds(), cfg.DOC_WORKER_START_TIME, cfg.DOC_WORKER_END_TIME,
             NAV_SECONDS))


def test_doc_type_count_matches_the_measured_model():
    """`DOC_TYPE_LIST` 가 곧 **물건당 이동 횟수**다.

    워커가 큐 행을 하나씩 집고 행마다 이동하므로 종류가 늘면 그대로 이동이 는다.
    이 관계가 깨지는 유일한 경우는 batching 을 넣었을 때이고, 그때는 이 검사도
    함께 고쳐야 한다(그게 이 검사의 목적이다).
    """
    print("\n--- 2. doc_type 수 = 물건당 이동 횟수 ---")
    n = len(cfg.DOC_TYPE_LIST)
    check_true("DOC_TYPE_LIST 를 읽었다(검사가 공허하지 않다)", n >= 3, cfg.DOC_TYPE_LIST)
    print("    doc_type %d종 %s" % (n, cfg.DOC_TYPE_LIST))
    print("    -> 물건 1건당 이동 **1회**(%.1f초) + 종류마다 %.1f초 = %.1f초"
          % (NAV_SECONDS, PER_ROW_NON_NAV, item_seconds(n)))
    print("    -> 하루 처리 가능 **%.0f건** (예전 구조라면 %.0f건)"
          % (capacity(n), legacy_capacity(n)))

    # ★ 모델 근거를 **주석이 아니라 코드**에서 확인한다 (Sprint 236).
    code = _code_of(os.path.join(os.getcwd(), "doc_worker.py"))
    check_true("워커가 물건 단위로 claim 한다(모델 근거)",
               "claim_next_item_rows(" in code,
               "claim 단위가 바뀌었다면 이 모델을 다시 세워야 한다")
    check_true("워커가 이동을 재사용 경로로 감싼다(모델 근거)",
               "_ensure_detail_page(" in code,
               "이동이 다시 행마다 일어나면 능력이 절반이 된다")
    check_true("★ 옛 모델의 흔적이 코드에 남아 있지 않다",
               "claim_next_queue_item()" not in code,
               "행 단위 claim 이 살아 있다면 위 모델은 거짓이다")

    # 그리고 **실제로 재사용하는지** 불러 본다. 문자열이 있어도 동작하지 않으면
    # 모델은 거짓이다 - grep 만으로 실행 경로를 판정하지 않는다.
    import doc_worker as dw
    seen = []
    orig = (dw.go_to_case_detail, dw.wait_for_detail)
    try:
        dw.go_to_case_detail = (
            lambda d, c, cn, i=None, require_exact_item=False: (seen.append(1) or True))
        dw.wait_for_detail = lambda d, cn: True
        st = {}
        for _ in range(n):
            dw._ensure_detail_page(object(), st, "B1", "2024타경1", "1", require_exact=False)
    finally:
        dw.go_to_case_detail, dw.wait_for_detail = orig
    check("★ 종류가 %d개여도 이동은 1회다(실제 호출)" % n, len(seen), 1)


def test_capacity_covers_the_observed_supply():
    """★ 능력이 **실제 공급**을 감당하는가.

    공급은 추정이 아니라 `auction_item.crawl_date` 실측이다
    (크롤이 실제로 돈 20일: 중앙값 106건 / 최대 278건).
    """
    print("\n--- 3. 능력 vs 실제 공급 ---")
    n = len(cfg.DOC_TYPE_LIST)
    cap = capacity(n)
    print("    물건 1건 = 이동 %.1f초 + %d종 x %.1f초 = %.1f초"
          % (NAV_SECONDS, n, PER_ROW_NON_NAV, item_seconds(n)))
    print("    하루 능력 %.0f건 / 공급 중앙값 %d건 / 공급 최대 %d건"
          % (cap, SUPPLY_MEDIAN, SUPPLY_MAX))

    check_true("★ 중앙값 공급은 감당한다", cap >= SUPPLY_MEDIAN,
               "능력 %.0f < 중앙값 %d - 평상시에도 큐가 쌓인다" % (cap, SUPPLY_MEDIAN))

    # 최대치는 지금 감당하지 못한다. 그것을 **사실로 고정**한다 —
    # 통과시키는 것이 목적이 아니라, 나아지거나 나빠질 때 알아채는 것이 목적이다.
    covers_peak = cap >= SUPPLY_MAX
    print("    최대 공급일(%d건) 감당 여부: %s" % (SUPPLY_MAX, "감당" if covers_peak else "**밀린다**"))
    if not covers_peak:
        print("        부족분 %.0f건 - 그날 밀린 것은 다음 날 창을 먹는다" % (SUPPLY_MAX - cap))
    check_true("이 사실이 기록돼 있다(감당 여부를 계산할 수 있다)", isinstance(covers_peak, bool))

    # ★ 래칫 — 능력이 **기록된 값 아래로 조용히 떨어지지 않게** 한다.
    #   중앙값 공급(106)만 보면 doc_type 을 6종까지 늘려도 통과한다(132건 > 106).
    #   그래서 "기준선보다 나빠지지 않았는가"를 따로 건다. 개선은 언제나 통과하고,
    #   나빠지면 **숫자를 갱신하며 이유를 적게** 만든다.
    check_true("★ 능력이 기록된 기준선(%d건) 아래로 떨어지지 않았다" % CAPACITY_BASELINE,
               cap >= CAPACITY_BASELINE,
               "%.0f < %d - doc_type 이 늘었거나 실행 창이 줄었다. 근거와 함께 기준선을 갱신하라"
               % (cap, CAPACITY_BASELINE))

    # ★ 실행 창 재평가 - 최대 공급일을 덮으려면 창이 얼마나 필요한가.
    #   정책(창 변경)은 승인 영역이라 **바꾸지 않는다.** 숫자만 계산해 둔다.
    need_sec = SUPPLY_MAX * item_seconds(n)
    have_sec = window_seconds()
    start_min = _mins(cfg.DOC_WORKER_START_TIME)
    end_needed = start_min + need_sec / 60.0
    print("    최대 공급일(%d건)을 덮으려면 창 %.1f시간 필요 (지금 %.1f시간)"
          % (SUPPLY_MAX, need_sec / 3600.0, have_sec / 3600.0))
    print("        -> %s 시작이면 %02d:%02d 까지" %
          (cfg.DOC_WORKER_START_TIME, int(end_needed // 60) % 24, int(end_needed) % 60))

    # 06:00 일일 크롤과 겹치면 안 된다(BUGS #167 이 그 관계를 잠갔다).
    CRAWL_START_MIN = 6 * 60
    fits_before_crawl = end_needed <= CRAWL_START_MIN
    print("        06:00 크롤 전에 끝나는가: %s"
          % ("끝난다" if fits_before_crawl else "**겹친다 - 창 확대만으로는 안 된다**"))
    check_true("★ 창 요구량을 계산할 수 있다(정책 판단의 근거)",
               need_sec > 0 and have_sec > 0, (need_sec, have_sec))
    check_true("지금 창은 최대 공급일을 덮지 못한다(사실 고정)",
               have_sec < need_sec,
               "덮게 됐다면 좋은 소식이다 - 이 검사와 기준선을 갱신하라")


def test_raising_max_items_would_break_capacity():
    """★ `MAX_ITEMS` 를 올리면 능력을 넘는가 — 정책 결정의 근거를 계산으로 남긴다.

    정책은 여기서 바꾸지 않는다(승인 영역). **넘는다는 사실**만 계산해 둔다.
    """
    print("\n--- 4. MAX_ITEMS 와 능력의 관계 ---")
    try:
        from config.courts import ALL_COURTS
        n_courts = len(ALL_COURTS)
    except Exception:
        n_courts = 0
    check_true("법원 목록을 읽었다(검사가 공허하지 않다)", n_courts > 0, n_courts)
    if not n_courts:
        return

    n = len(cfg.DOC_TYPE_LIST)
    cap = capacity(n)
    theoretical = cfg.MAX_ITEMS * n_courts
    print("    MAX_ITEMS=%d x 법원 %d = 이론상 최대 공급 %d건/일"
          % (cfg.MAX_ITEMS, n_courts, theoretical))
    print("    하루 능력 %.0f건 -> %s" % (cap, "여유" if theoretical <= cap else "**초과**"))
    if theoretical > cap:
        print("        초과 %d건/일 - 상한을 올리기 전에 처리 능력을 먼저 올려야 한다"
              % (theoretical - cap))
    # ★ 어디까지 올릴 수 있는가를 계산해 둔다 - 정책은 바꾸지 않되 근거는 남긴다.
    safe_max = int(cap / n_courts)
    print("    능력 안에 들어오는 MAX_ITEMS 상한 = %d (법원 %d개 기준)"
          % (safe_max, n_courts))
    if safe_max < cfg.MAX_ITEMS:
        print("        -> 현재 %d 도 이론상으로는 능력을 넘는다. 다만 이론 최대는"
              % cfg.MAX_ITEMS)
        print("           '모든 법원이 매일 상한까지 채우는' 경우이고, 실측 공급"
              "(중앙값 %d)은 그보다 훨씬 낮다." % SUPPLY_MEDIAN)
    check_true("이론 최대와 능력을 모두 계산할 수 있다", theoretical > 0 and cap > 0,
               (theoretical, cap))
    check_true("★ 상향 판단 근거(안전 상한)를 계산할 수 있다", safe_max >= 0, safe_max)


def test_batching_gain_is_quantified():
    """물건 단위 batching 의 이득을 **숫자로** 고정한다.

    Sprint 199 가 "가능하다"를 실증하고도 구현하지 않은 이유는 그때 이득이 0이었기
    때문이다(대기 물건 2개). 지금은 능력 자체가 병목이므로 이득을 계산해 둔다.
    """
    print("\n--- 5. batching 이득 (전/후) ---")
    n = len(cfg.DOC_TYPE_LIST)
    before = legacy_capacity(n)
    after = capacity(n)
    gain = after / before
    print("    예전  이동 %d회 x %.1f초 + %d종 x %.1f초 = %.1f초 -> 하루 %.0f건"
          % (n, NAV_SECONDS, n, PER_ROW_NON_NAV, item_seconds(n, n), before))
    print("    지금  이동 1회 x %.1f초 + %d종 x %.1f초 = %.1f초 -> 하루 %.0f건"
          % (NAV_SECONDS, n, PER_ROW_NON_NAV, item_seconds(n), after))
    print("    -> 처리량 **%.2f배**" % gain)

    # ★ 이동 횟수는 4배 줄지만 **처리량은 4배가 되지 않는다.**
    #   수집과 sleep 은 종류마다 그대로 들기 때문이다. Sprint 235 가 이 둘을
    #   구분하지 않아 4.0배라고 적었다 - 그 숫자는 이동 감소 배수였다.
    nav_ratio = float(n)          # 이동 48회 -> 12회 (test_worker_batching.py 실측)
    check_true("★ 처리량 이득이 이동 감소 배수보다 작다(수집/sleep 은 남는다)",
               gain < nav_ratio,
               "이득 %.2f 가 이동 감소 %.1f 와 같다면 수집 비용을 0으로 놓은 것이다"
               % (gain, nav_ratio))
    check_true("★ batching 이 실제로 이득이다", gain > 1.0, gain)
    check_true("이득이 기록된 값(약 2.0배)에서 크게 벗어나지 않았다",
               1.7 <= gain <= 2.5,
               "%.2f - 상수가 바뀌었으면 근거와 함께 이 범위를 갱신하라" % gain)


def test_queue_growth_is_observable():
    """큐가 **늘고 있는지** 볼 수 있는가 (운영 DB 읽기 전용).

    능력 부족은 오류가 아니라 **큐 길이**로 나타난다. 그 값을 실제로 셀 수 있어야 한다.
    """
    print("\n--- 6. 큐 관측 가능성 ---")
    db = os.path.join(os.getcwd(), "auction.db")
    if not os.path.exists(db):
        print("[SKIP] auction.db 없음 (fresh clone)")
        return
    conn = sqlite3.connect("file:%s?mode=ro" % db.replace("\\", "/"), uri=True)
    try:
        total = conn.execute("SELECT COUNT(*) FROM document_queue").fetchone()[0]
        waiting = conn.execute(
            "SELECT COUNT(*) FROM document_queue WHERE status IN ('pending','refresh')"
        ).fetchone()[0]
        items = conn.execute(
            "SELECT COUNT(DISTINCT court_code||case_no||item_no) FROM document_queue "
            "WHERE status IN ('pending','refresh')").fetchone()[0]
        types = [r[0] for r in conn.execute("SELECT DISTINCT doc_type FROM document_queue")]
    finally:
        conn.close()
    print("    큐 %d행 / 대기 %d행 / 대기 물건 %d개" % (total, waiting, items))
    print("    큐에 실제로 있는 doc_type: %s" % sorted(types))
    check_true("큐를 실제로 셀 수 있다(검사가 공허하지 않다)", total > 0, total)

    # ★ 큐의 종류와 config 의 종류가 다르면 그 이유를 알아야 한다.
    missing = sorted(set(cfg.DOC_TYPE_LIST) - set(types))
    if missing:
        print("    ※ config 에는 있으나 큐에 없는 종류: %s" % missing)
        print("      -> 이 행들이 그 종류가 추가되기 **전에** 적재됐다는 뜻이다.")
        print("         새로 적재되는 물건부터는 %d종이 되어 물건당 이동이 늘어난다."
              % len(cfg.DOC_TYPE_LIST))
    check_true("큐 종류가 config 의 부분집합이다(모르는 종류가 없다)",
               set(types) <= set(cfg.DOC_TYPE_LIST), sorted(set(types) - set(cfg.DOC_TYPE_LIST)))



def test_the_model_premise_still_holds_in_code():
    """이 파일의 능력 계산이 **딛고 선 전제**가 코드에 아직 살아 있는가.

    ## 왜 필요했나 - mutation 이 이 파일을 공허하게 만들 수 있었다

    2026-08-21 실측: `storage/database.py` 의

        def claim_next_item_rows(max_rows: int = QUEUE_BATCH_MAX_ROWS)
        -> def claim_next_item_rows(max_rows: int = 1)

    로 **batching 을 행 단위로 되돌리는** mutation 을 걸었더니
    `test_worker_batching.py` 는 잡았지만 **이 파일은 그대로 통과했다.**
    그런데 이 파일은 그 상태에서도 여전히 "처리량 1.97배", "하루 능력 153건" 이라고
    출력한다 - 즉 **없어진 이득을 있다고 보고한다.**

    이유는 단순하다: 5번 검사(`test_batching_gain_is_quantified`)는 `capacity()` 와
    `legacy_capacity()` 라는 **상수 계산 두 개를 서로 비교**할 뿐, 제품 코드를 한 줄도
    지나가지 않는다. 모델로서는 정직하지만, 그 모델이 **현실과 연결돼 있는지는**
    아무도 확인하지 않았다.

    ## 그래서 무엇을 잠그나

    처리량 계산은 "물건 1건당 이동 1회"라는 전제 위에 있다. 그 전제를 실제로 만드는
    코드는 둘이다.

        (1) `claim_next_item_rows()` 가 한 물건의 **여러 행**을 집어 온다
            -> 기본값이 1 이면 물건 단위가 아니라 행 단위다(= 예전 구조)
        (2) `doc_worker` 가 그 함수와 페이지 재사용을 **실제로 쓴다**
            -> 호출이 사라지면 claim 만 묶여 있고 이동은 그대로다

    둘 중 하나라도 무너지면 이 파일의 숫자는 거짓이 된다. 여기서 그것을 잡는다.

    ★ 이 검사는 `test_worker_batching.py` 를 대신하지 않는다. 그 파일은 **행동**을
      본다(진짜 main() 을 돌려 이동 횟수를 센다). 이 검사는 **이 파일이 자기 전제를
      잃은 채로 숫자를 계속 출력하는 것**을 막는다. 서로 다른 것을 본다.
    """
    print("\n--- 7. 능력 모델의 전제가 코드에 살아 있는가 ---")
    import inspect
    import storage.database as db
    import doc_worker as dw

    n = len(cfg.DOC_TYPE_LIST)

    # (1) claim 이 물건 단위인가 - 기본값이 doc_type 수를 덮을 만큼 큰가
    sig = inspect.signature(db.claim_next_item_rows)
    default_rows = sig.parameters["max_rows"].default
    print("    claim_next_item_rows(max_rows=%r) / doc_type %d종 / QUEUE_BATCH_MAX_ROWS=%r"
          % (default_rows, n, getattr(db, "QUEUE_BATCH_MAX_ROWS", None)))
    check_true("★ claim 기본값이 1보다 크다(행 단위로 되돌아가지 않았다)",
               isinstance(default_rows, int) and default_rows > 1,
               "max_rows 기본값이 %r 이면 물건 단위 claim 이 아니다 - 이 파일의 "
               "처리량 계산(이동 1회/물건)이 거짓이 된다" % (default_rows,))
    check_true("★ 한 물건의 모든 doc_type 을 한 묶음에 담을 수 있다",
               isinstance(default_rows, int) and default_rows >= n,
               "기본값 %r < doc_type %d종 - 물건 하나가 두 묶음으로 쪼개져 이동이 늘어난다"
               % (default_rows, n))

    # (2) 워커가 그 두 기계를 실제로 쓰는가 (주석이 아니라 코드에서)
    src = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "doc_worker.py"),
                  encoding="utf-8-sig").read()
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    check_true("★ 워커가 claim_next_item_rows() 를 실제로 호출한다(코드)",
               "claim_next_item_rows()" in code,
               "호출이 사라지면 묶음 claim 이 동작하지 않는다")
    # ★ **정의**가 아니라 **호출**을 본다.
    #   처음에는 `"_ensure_detail_page(" in code` 로 썼는데, 그러면 `def
    #   _ensure_detail_page(...)` 라는 정의 줄이 검사를 통과시킨다. 실제로 호출부를
    #   `go_to_case_detail(` 로 되돌리는 mutation 을 걸었더니 **그대로 통과했다**
    #   (2026-08-21 실측). 함수는 남아 있는데 아무도 부르지 않는 상태 —
    #   이 저장소가 "기능 존재 != 실행 경로 연결" 로 부르는 바로 그 모양이다.
    call_lines = [l for l in code.splitlines()
                  if "_ensure_detail_page(" in l and not l.lstrip().startswith("def ")]
    check_true("★ 워커가 상세페이지 재사용(_ensure_detail_page)을 실제로 **호출**한다(코드)",
               len(call_lines) > 0,
               "정의만 남고 호출이 없다 - 묶어 집어도 행마다 이동해 이득이 0이 된다")
    check_true("모듈에 두 기계가 모두 존재한다",
               callable(getattr(dw, "_ensure_detail_page", None))
               and callable(getattr(dw, "claim_next_item_rows", None)),
               "이름이 바뀌었으면 이 검사를 갱신하라(검사가 공허해지지 않도록)")

def run():
    print("=" * 62)
    print(" 문서 워커 처리 능력 계약 (Sprint 235 신설 / 236 재측정)")
    print("=" * 62)
    test_measured_constants_are_sane()
    test_doc_type_count_matches_the_measured_model()
    test_capacity_covers_the_observed_supply()
    test_raising_max_items_would_break_capacity()
    test_batching_gain_is_quantified()
    test_queue_growth_is_observable()
    test_the_model_premise_still_holds_in_code()

    print("\n" + "=" * 62)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL WORKER CAPACITY TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
