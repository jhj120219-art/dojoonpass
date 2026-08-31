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
import io
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


# 어휘를 **설명하는 글**도 계약이다 (2026-08-31 신설)
#
# `storage/migrate_v4_1.py` 주석과 `docs/backend.md` 주의사항은 이 컬럼을
# "APARTMENT / OFFICETEL / LAND / FACTORY / COMMERCIAL / MULTI_FAMILY" ENUM 이라고
# 적고 있었다. **그 값을 쓰는 행은 0건이고 그 문자열을 만드는 소스도 없다.**
# 실제 값은 법원 표기 그대로의 한국어 자유 문자열이며 콤마 복합값이 있다.
#
# 왜 검사로 잠그나 — 이 종류의 거짓 서술은 **실행해도 드러나지 않는다.** 그 문장을
# 읽고 `property_type='APARTMENT'` 로 필터를 짜면 오류 없이 그냥 0건이 나오고,
# 그것은 #33 이 발견까지 오래 걸렸던 실패 모양 그대로다.
#
# ## 어떻게 잠그나 — 산문을 읽지 않고 **표를 DB 와 대조한다**
#
# "정정 표시가 근처에 있는가" 로 판정하려다 실패했다(변이 2건이 그대로 통과했다).
# 산문은 어떤 규칙을 세워도 우회된다. 그래서 두 파일에 기계가 읽을 표를 두고
# **거기 적힌 어휘가 실제 DB 에 존재하는지**를 본다. 지어낸 어휘(ENUM 코드 포함)를
# 표에 적으면 즉시 잡히고, 표를 지우면 커버리지 단언이 잡는다.
#
#     [VOCAB-TABLE] 다음 줄부터 "<값> <건수>" 목록
#
# ★ 한계를 정직하게 적는다: 표를 정확히 둔 채 **다른 문단에서** ENUM 을 다시
#   주장하는 것까지는 기계가 판별하지 못한다. 그 경우를 위해 (d) 에서 예전 문장을
#   **그대로** 되붙이는 것만 따로 막는다. 그 이상은 사람 리뷰의 몫이다.
_ENUM_GHOSTS = ("APARTMENT", "OFFICETEL", "MULTI_FAMILY", "COMMERCIAL", "FACTORY")
_VOCAB_DOCS = (
    os.path.join(ROOT, "storage", "migrate_v4_1.py"),
    os.path.join(ROOT, "docs", "backend.md"),
)
_VOCAB_MARK = "[VOCAB-TABLE]"
# 정정 이전의 서술 그대로. 이 문자열이 다시 나타나면 정정이 되돌려진 것이다.
_OLD_CLAIMS = (
    "property_type 코드: APARTMENT/OFFICETEL/LAND/FACTORY/COMMERCIAL/MULTI_FAMILY",
    "auction_item.property_type 코드 규칙:",
)


def documented_vocab(path):
    """`[VOCAB-TABLE]` 아래에 적힌 <값> <건수> 목록을 읽는다."""
    text = io.open(path, encoding="utf-8-sig").read()
    if _VOCAB_MARK not in text:
        return None
    tail = text.split(_VOCAB_MARK, 1)[1]
    found = {}
    for line in tail.split(chr(10))[1:]:
        pairs = re.findall(r"([가-힣][가-힣,()]*)\s+(\d+)", line)
        if not pairs:
            # 표는 연속된 줄로 적는다. 값이 없는 줄을 만나면 표가 끝난 것이다.
            if found:
                break
            continue
        for value, count in pairs:
            found[value] = int(count)
    return found


def test_no_document_claims_an_enum_the_data_does_not_use():
    print("\n--- 5. 문서가 적어 둔 어휘가 실제 DB 어휘인가 ---")

    values = db_types()
    total = sum(values.values())

    # (a) 그 ENUM 이 정말로 안 쓰이는지 **데이터로** 먼저 확인한다.
    #     쓰이고 있다면 옛 서술이 옳은 것이고 이 검사가 틀린 것이다.
    used = sorted(v for v in values if any(g in v for g in _ENUM_GHOSTS))
    check("ENUM 코드를 쓰는 물건종류가 DB 에 없다", not used, used)

    for path in _VOCAB_DOCS:
        name = os.path.relpath(path, ROOT)
        documented = documented_vocab(path)

        # (b) 표가 실제로 있다 — 검사가 공허하지 않다.
        check("%s 에 %s 표가 있다" % (name, _VOCAB_MARK), documented is not None,
              "기계가 대조할 어휘 표가 없다")
        if not documented:
            continue

        # (c) 표에 적힌 어휘가 전부 DB 에 실재한다 — 지어낸 어휘를 적지 않는다.
        invented = sorted(v for v in documented if v not in values)
        check("%s 의 어휘가 전부 DB 에 실재한다" % name, not invented,
              "%s - DB 에 없는 값을 어휘로 적어 두었다" % invented)

        # (d) 표가 실제 재고를 대표한다 — 지워 버리거나 몇 줄만 남기지 못한다.
        covered = sum(values[v] for v in documented if v in values)
        ratio = covered * 100 // max(1, total)
        check("%s 의 표가 재고 대부분을 덮는다 (>=90%%)" % name, ratio >= 90,
              "%d%% (%d/%d건)" % (ratio, covered, total))
        print("   %s: %d종 / 재고의 %d%%" % (_safe(name), len(documented), ratio))

        # (e) 정정 이전 문장을 **살아 있는 주장으로** 되붙이지 않았다.
        #     사료는 지우지 않는다 - 마크다운 취소선(~~)으로 감싼 줄은 통과시킨다.
        #     취소선은 산문이 아니라 **표기**라 기계가 판별할 수 있다.
        restored = []
        for lineno, line in enumerate(io.open(path, encoding="utf-8-sig"), 1):
            for claim in _OLD_CLAIMS:
                if claim in line and "~~" not in line:
                    restored.append("%s:%d" % (name, lineno))
        check("%s 에 옛 ENUM 서술이 살아 있는 주장으로 되살아나지 않았다" % name,
              not restored, restored)

    # (f) 파서가 공허하지 않다는 것을 합성 입력으로 증명한다.
    probe = {}
    for line in ["아파트 201 / 전답 188", "임야 123"]:
        for v, n in re.findall(r"([가-힣][가-힣,()]*)\s+(\d+)", line):
            probe[v] = int(n)
    check("표 파서가 값을 실제로 읽는다",
          probe == {"아파트": 201, "전답": 188, "임야": 123}, probe)
    check("표 파서가 ENUM 코드를 어휘로 읽지 않는다",
          not re.findall(r"([가-힣][가-힣,()]*)\s+(\d+)", "APARTMENT 201"))


def run():
    test_the_tree_and_the_backend_are_both_readable()
    test_every_stored_type_is_reachable_from_the_tree()
    test_no_tree_item_drags_in_unrelated_types()
    test_the_alias_table_has_no_dead_entries()
    test_the_bridge_actually_carries_weight()
    test_no_document_claims_an_enum_the_data_does_not_use()
    print(_safe("\n%s (실패 %d)" % ("모두 통과" if not failures else "실패: %s" % failures,
                                    len(failures))))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(run())
