"""검색 UI 물건종류 어휘와 DB 값의 **계약** (docs/BUGS.md #33).

## 무엇을 지키는가

사용자는 `PropertyTypeTree` 의 69개 항목으로 물건종류를 고른다. 크롤러는
법원 표기를 `auction_item.property_type` 에 그대로 저장한다. 두 어휘는 원래
다르고, 그 사이를 `api/v1/search.PROPERTY_TYPE_ALIASES` 가 잇는다.

#33 은 그 다리가 없던 때의 기록이다 —

    "다세대주택"을 선택하면 0건. 그런데 DB에는 `다세대` 물건이 246건 있다.

**2026-08-28 재측정: 그 증상은 해소됐다.**

    다세대주택  패턴['다세대주택','다세대'] -> 379건
    오피스텔     -> 307건    근린시설 -> 369건    아파트 -> 201건

그런데 **그 계약을 지키는 검사가 하나도 없었다.** 크롤러가 새 표기를 저장하기
시작하거나 누가 트리 항목을 고치면, 그 물건은 화면에서 조용히 사라진다 —
오류도 나지 않고 그냥 0건이 된다. #33 이 정확히 그렇게 생겼고, 발견까지
오래 걸린 이유도 그것이다.

## 두 방향을 모두 본다

    도달성    DB 에 있는 값이 **어떤 UI 항목으로도 걸리지 않는** 경우
              -> 재고가 있는데 사용자가 찾을 수 없다 (#33 의 해악)
    과다매칭   한 UI 항목이 **서로 다른 값 여럿**을 끌어오는 경우
              -> "아파트"를 골랐는데 전답이 섞여 나온다

0건 자체는 결함이 아니다. `묘지`/`광업권`/`덤프트럭` 은 **그런 물건이 아직
없다**는 사실이고, 그건 어휘 문제가 아니다(`search.py` 주석이 같은 판단을
이미 적어 두었다).

실제 `auction.db` 를 **읽기 전용**으로만 연다.

    python test_property_type_vocabulary.py
"""
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api.v1.search import PROPERTY_TYPE_ALIASES, _property_type_patterns

ROOT = os.path.dirname(os.path.abspath(__file__))
TREE = os.path.join(ROOT, "src", "components", "PropertyTypeTree.tsx")

failures = []


def _safe(text):
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    return str(text).encode(enc, "replace").decode(enc, "replace")


def check(name, ok, detail=""):
    print(_safe("[%s] %s%s" % ("PASS" if ok else "FAIL", name,
                               "" if ok else "  -> %s" % (detail,))))
    if not ok:
        failures.append(name)


def ui_items():
    """트리가 실제로 보여 주는 항목. **소스에서 읽는다** — 목록을 여기 베끼면
    한쪽만 갱신되는 날이 오고, 그때 이 검사는 옛 목록을 지키게 된다."""
    src = open(TREE, encoding="utf-8-sig").read()
    items = []
    for block in re.finditer(r"items:\s*\[(.*?)\]", src, re.S):
        items += re.findall(r"'([^']+)'", block.group(1))
    return sorted(set(items))


def db_types():
    """실제 저장된 물건종류 -> 건수. 읽기 전용."""
    conn = sqlite3.connect("file:auction.db?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT property_type, COUNT(*) FROM auction_item"
            " WHERE property_type IS NOT NULL AND TRIM(property_type) <> ''"
            " GROUP BY property_type"
        ).fetchall()
    finally:
        conn.close()
    return {t: n for t, n in rows}


def matches(item, values):
    """UI 항목 하나가 걸어내는 DB 값들. 백엔드와 **같은 규칙**을 쓴다."""
    hit = set()
    for pattern in _property_type_patterns([item]):
        for value in values:
            if pattern in value:      # 백엔드는 LIKE %pattern% 이다
                hit.add(value)
    return hit


def test_the_tree_and_the_backend_are_both_readable():
    print("\n--- 0. 입력 확인 (검사가 공허하지 않다) ---")
    items = ui_items()
    check("트리 항목을 소스에서 읽었다", len(items) >= 60, len(items))
    values = db_types()
    check("DB 에서 물건종류를 읽었다", len(values) >= 5, len(values))
    print("   트리 %d항목 / DB %d종 %d건" % (len(items), len(values), sum(values.values())))


def test_every_stored_type_is_reachable_from_the_tree():
    """★ #33 의 해악 그 자체 — 재고가 있는데 사용자가 찾을 수 없는 경우."""
    print("\n--- 1. DB 의 모든 값이 UI 로 도달 가능한가 ---")
    values = db_types()
    items = ui_items()
    if not values or not items:
        check("입력이 있다", False, "DB/트리를 읽지 못했다")
        return

    reachable = set()
    for item in items:
        reachable |= matches(item, values)

    unreachable = {v: n for v, n in values.items() if v not in reachable}
    lost = sum(unreachable.values())
    check(
        "어떤 UI 항목으로도 걸리지 않는 물건종류가 없다",
        not unreachable,
        "%s (%d건, 전체의 %d%%) - 이 물건들은 화면에서 조용히 사라진다. "
        "`PROPERTY_TYPE_ALIASES` 에 다리를 놓아야 한다."
        % (sorted(unreachable), lost, lost * 100 // max(1, sum(values.values()))),
    )


def test_no_tree_item_drags_in_unrelated_types():
    """과다 매칭 — 고른 것과 다른 물건이 섞여 나오면 필터가 거짓말을 한다.

    복합값(`'상가,오피스텔,근린시설'`)을 여러 항목이 함께 잡는 것은 **정상**이다.
    문제는 한 항목이 **의미가 다른 값들**까지 끌어오는 경우다. 그래서 상한을
    두되, 지금 실제로 몇 개인지 함께 보고한다.
    """
    print("\n--- 2. 한 항목이 엉뚱한 종류까지 끌어오지 않는가 ---")
    values = db_types()
    items = ui_items()
    worst = []
    for item in items:
        hit = matches(item, values)
        if len(hit) >= 4:
            worst.append((item, sorted(hit)))
    check("한 항목이 4종 이상을 끌어오지 않는다", not worst, worst[:3])


def test_the_alias_table_has_no_dead_entries():
    """별칭이 트리에 없는 항목을 가리키면 그 줄은 영원히 쓰이지 않는다."""
    print("\n--- 3. 별칭표에 죽은 항목이 없는가 ---")
    items = set(ui_items())
    dead = sorted(k for k in PROPERTY_TYPE_ALIASES if k not in items)
    check("별칭 키가 전부 트리에 있다", not dead,
          "%s - 트리에서 사라진 항목의 별칭이 남아 있다" % dead)


def test_the_bridge_actually_carries_weight():
    """별칭이 없었다면 못 찾았을 물건이 실제로 있는가 (검사가 공허하지 않다)."""
    print("\n--- 4. 별칭 다리가 실제로 무게를 지고 있는가 ---")
    values = db_types()
    carried = {}
    for key, aliases in PROPERTY_TYPE_ALIASES.items():
        only_alias = set()
        for alias in aliases:
            for value in values:
                if alias in value and key not in value:
                    only_alias.add(value)
        if only_alias:
            carried[key] = sum(values[v] for v in only_alias)
    check("별칭이 없으면 놓칠 물건이 실제로 존재한다", bool(carried), carried)
    for key, count in sorted(carried.items(), key=lambda kv: -kv[1]):
        print("   %s: 별칭 덕분에 %d건" % (_safe(key), count))


def run():
    test_the_tree_and_the_backend_are_both_readable()
    test_every_stored_type_is_reachable_from_the_tree()
    test_no_tree_item_drags_in_unrelated_types()
    test_the_alias_table_has_no_dead_entries()
    test_the_bridge_actually_carries_weight()
    print(_safe("\n%s (실패 %d)" % ("모두 통과" if not failures else "실패: %s" % failures,
                                    len(failures))))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(run())
