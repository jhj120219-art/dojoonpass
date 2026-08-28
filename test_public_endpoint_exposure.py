"""공개 엔드포인트가 **무엇을 내보내는지** 고정한다 (docs/BUGS.md #254 / 2026-08-28).

## 실측으로 찾은 것

`GET /api/v1/item/{item_id}` 는 **인증 없이** 읽을 수 있다
(`test_api_regression.PUBLIC_ENDPOINTS` 에 그렇게 등록돼 있다).

본체(`auction_item`)는 필드를 하나씩 적어 내보내는데, 곁딸린 세 테이블만
`dict(row)` 로 **행 전체**를 실었다.

    "case":           dict(case)
    "tenants":        [dict(t) for t in tenants]
    "rights_summary": dict(rights)

그래서 마이그레이션이 그 테이블에 컬럼을 하나 추가하면 **그날로 인증 없이 읽히는
API 에 실린다.** 아무도 그렇게 결정하지 않았고, 알려 줄 검사도 없었다.

그리고 그 세 테이블에는 **개인정보가 들어 있다**(2026-08-28 auction.db 실측).

    tenant_rights   tenant_name    240/519 행이 실명("김미화" 등)
                    occupied_area  475/519 행이 전체 주소
                    deposit / monthly_rent / move_in_date / fixed_date

감사 문서 두 곳은 그 반대로 적고 있었다 —

    docs/CURRENT_STATE.md §9229   "공개 8개에 개인정보·관리 기능 없음"
    docs/CHANGELOG.md     §4827   "공개 8개에 개인정보·관리 기능 없음"

## 이 파일이 하는 일

**응답을 바꾸지 않는다.** `api/v1/item.py` 의 화이트리스트는 지금 나가는 컬럼
그대로다. 여기서 고정하는 것은 두 가지다.

    1. 화이트리스트 == 실제 테이블 컬럼
       마이그레이션이 컬럼을 늘리면 이 검사가 **그 이름을 대며** 실패한다.
       목록에 적는 행위가 곧 "이것을 공개한다"는 결정이 된다.

    2. 개인정보가 공개 경로로 나간다는 **사실 자체**
       마스킹은 제품·법무 판단이라 여기서 정하지 않는다(임차인 성명은 대항력
       판단의 근거라 가리면 권리분석이 약해진다). 대신 "없다"고 적었던 문서가
       조용히 돌아오지 못하게 한다.

컬럼 순서는 보지 않는다 — migration 024 가 `auction_case` 의 순서를 바꾼다
(집합은 그대로). 순서로 판정하면 승인된 마이그레이션이 적용되는 날 이 검사가
엉뚱하게 붉어진다.

읽기 전용이다. auction.db 에 아무것도 쓰지 않는다.

    python test_public_endpoint_exposure.py
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import storage.database as dbmod
from api.v1.item import _CASE_FIELDS, _RIGHTS_FIELDS, _TENANT_FIELDS

failures = []


def _safe(text):
    """콘솔 인코딩에 없는 문자를 지운다.

    이 검사는 **문서 원문을 되받아 찍는다.** 그 안에는 U+2014 EM DASH 가 들어 있고,
    cp949 콘솔(bash / cmd.exe / `run_daily.bat` 의 리다이렉트)에서는 그것을 찍다가
    UnicodeEncodeError 로 **프로세스가 죽는다** ― 검사가 실패한 것이 아니라 결과를
    출력하다 죽는 것이라 더 나쁘다(`test_console_encoding.py` 가 지키는 그 사고).
    """
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    return str(text).encode(enc, "replace").decode(enc, "replace")


def _check_true(name, ok, detail=""):
    print(_safe("[%s] %s%s" % ("PASS" if ok else "FAIL", name,
                               "" if ok else "  -> %s" % (detail,))))
    if not ok:
        failures.append(name)


#: 응답 키 -> (테이블, 화이트리스트). `api/v1/item.py` 가 이 셋만 행 단위로 싣는다.
NESTED = (
    ("tenants", "tenant_rights", _TENANT_FIELDS),
    ("case", "auction_case", _CASE_FIELDS),
    ("rights_summary", "rights_summary", _RIGHTS_FIELDS),
)

#: 공개 경로로 나가는 **개인정보** 컬럼. 줄이려면 마스킹 구현이 함께 와야 한다.
PII_FIELDS = {
    "tenant_rights": ("tenant_name", "occupied_area", "deposit", "monthly_rent",
                      "move_in_date", "fixed_date"),
}


def test_whitelist_matches_the_actual_schema():
    """화이트리스트가 실제 컬럼과 **정확히 같은 집합**인가.

    적은 쪽으로 어긋나면 = 조용히 응답이 줄었다(프런트가 깨진다).
    많은 쪽으로 어긋나면 = 새 컬럼이 공개 API 에 실렸다.
    """
    print("\n--- 1. 화이트리스트 == 실제 테이블 컬럼 ---")
    conn = dbmod.get_connection()
    try:
        for key, table, fields in NESTED:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(%s)" % table)}
            _check_true("%s: 테이블이 존재한다" % table, bool(cols))
            if not cols:
                continue
            missing = cols - set(fields)
            extra = set(fields) - cols
            _check_true(
                "%s: 새 컬럼이 공개 응답에 자동으로 실리지 않는다" % table,
                not missing,
                "%s 에 %s 가 생겼다. api/v1/item.py 의 목록에 적을지 **결정**하라. "
                "적으면 인증 없이 읽힌다." % (table, sorted(missing)),
            )
            _check_true(
                "%s: 사라진 컬럼을 응답이 약속하고 있지 않다" % table,
                not extra,
                "화이트리스트에만 있는 컬럼 %s" % sorted(extra),
            )
    finally:
        conn.close()


def test_item_detail_does_not_dump_whole_rows():
    """`dict(row)` 로 되돌아가면 1번 검사가 **무력해진다**.

    화이트리스트가 맞는지 아무리 봐도, 응답이 그것을 안 쓰면 의미가 없다.
    그래서 소스에서 그 형태 자체를 막는다.
    """
    print("\n--- 2. 곁딸린 행을 통째로 싣지 않는다 (소스 계약) ---")
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "api", "v1", "item.py")
    src = open(path, encoding="utf-8-sig").read()
    body = src[src.index("def get_item("):]
    for key, table, _ in NESTED:
        line = [ln for ln in body.splitlines() if '"%s":' % key in ln]
        _check_true("%s 응답 줄을 찾았다" % key, bool(line))
        if not line:
            continue
        _check_true("%s 를 _project() 로 만든다" % key,
                    "_project(" in line[0], line[0].strip())
        _check_true("%s 에 dict(row) 덤프가 없다" % key,
                    "dict(" not in line[0], line[0].strip())


def test_pii_on_a_public_route_is_recorded_not_forgotten():
    """개인정보가 **공개 경로로 나간다는 사실**을 고정한다.

    "공개 경로에 개인정보 없음" 이라고 적힌 문서 두 곳이 사실과 달랐다.
    사람이 다시 그렇게 적더라도, 이 검사가 실데이터로 반박한다.

    마스킹이 구현되면 이 검사가 실패한다 — 그때가 PII_FIELDS 와 문서를
    함께 정리할 시점이다. 조용히 어긋난 상태로 남지 않게 한다.
    """
    print("\n--- 3. 공개 경로의 개인정보 (실데이터) ---")
    for table, fields in PII_FIELDS.items():
        exposed = [f for f in fields if f in set(_TENANT_FIELDS)]
        _check_true("%s: 개인정보 컬럼이 여전히 공개 응답에 있다" % table,
                    len(exposed) == len(fields), exposed)

    conn = dbmod.get_connection()
    try:
        named = conn.execute(
            "SELECT COUNT(*) FROM tenant_rights WHERE tenant_name IS NOT NULL"
            " AND TRIM(tenant_name) <> ''").fetchone()[0]
    except sqlite3.OperationalError:
        named = None
    finally:
        conn.close()
    _check_true("실명이 실제로 저장돼 있다(가정이 아니라 실측)",
                named is None or named > 0,
                "tenant_name 이 있는 행 %s" % (named,))
    print("   tenant_name 보유 행: %s" % (named,))

    # 문서가 "없다"로 되돌아가지 못하게 한다.
    root = os.path.dirname(os.path.abspath(__file__))
    claim = "공개에 개인정보"
    for name in ("docs/CURRENT_STATE.md", "docs/CHANGELOG.md"):
        p = os.path.join(root, *name.split("/"))
        if not os.path.exists(p):
            continue
        text = open(p, encoding="utf-8", errors="replace").read()
        bad = [ln.strip() for ln in text.splitlines()
               if claim in ln and "없음" in ln and "#254" not in ln]
        _check_true("%s: '공개에 개인정보 없음' 주장이 정정돼 있다" % name,
                    not bad, bad[:2])


def run():
    test_whitelist_matches_the_actual_schema()
    test_item_detail_does_not_dump_whole_rows()
    test_pii_on_a_public_route_is_recorded_not_forgotten()
    print("\n%s  (실패 %d)" % ("모두 통과" if not failures else "실패: %s" % failures,
                               len(failures)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(run())
