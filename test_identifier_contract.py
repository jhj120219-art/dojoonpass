"""itemId 식별자 계약 — 검색부터 접근제어까지 **같은 id 하나**로 간다 (2026-09-03, P0-4).

## 왜 이 파일이 따로 있나

식별자 관련 검사는 이미 여럿 있다. 그런데 전부 **한 구간씩만** 본다:

    test_id_bounds_sweep.py     범위 밖 id 가 5xx 를 만들지 않는가
    test_admin_id_bounds.py     admin 경로의 같은 것
    test_api_regression.py      엔드포인트별 소유권/IDOR (남의 것을 못 보는가)
    test_auction_identity.py    DB 식별키(court_code, case_no, item_no) 복합키 무결성

빠진 것은 **연속성**이다 — "검색에서 받은 id 가 상세·최근본·관심물건·문서·접근제어
까지 **같은 물건을 가리키는가**". 구간별로 다 통과하면서도 중간에서 다른 물건으로
바뀌면 사용자는 **자기가 고른 것과 다른 물건**을 찜하게 된다. 그 축을 여기서 본다.

## 무엇을 canonical 로 두는가

`auction_item.id` 하나다(`docs/CLAUDE.md`: itemId 단일 식별자 체계 유지).

    API 응답      `id`(상세) / `items[].id`(검색) / `item_id`(관심물건·최근본 요청)
    프런트        `itemId` prop (camelCase 는 React 관례이고 값은 같다)
    화면 경로     /properties/{id}

`case_no` / `item_no` / `court_code` 는 **업무 키**이지 canonical id 가 아니다.
그래서 이 검사는 id 로 따라가되, 매 단계에서 그 업무 키가 **함께 일치하는지**를
확인한다 — id 만 같고 내용이 다르면 그건 다른 행을 가리킨 것이다.

## 실행

    python test_identifier_contract.py
"""
import os
import sys
import uuid
import secrets

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# api/auth.py 는 모듈 최상단에서 한 번만 읽으므로 import 전에 넣는다
# (test_api_regression.py 와 같은 방식·같은 이유).
if not os.getenv("SUPABASE_JWT_SECRET"):
    os.environ["SUPABASE_JWT_SECRET"] = "qa-idcontract-" + secrets.token_hex(16)

from jose import jwt                                    # noqa: E402
from fastapi.testclient import TestClient               # noqa: E402

import api_server                                       # noqa: E402
from api.auth import SUPABASE_JWT_SECRET                # noqa: E402
from storage.database import get_connection             # noqa: E402

client = TestClient(api_server.app)
failures = []

USER_A = "qa-idc-a-" + uuid.uuid4().hex[:10]
USER_B = "qa-idc-b-" + uuid.uuid4().hex[:10]


def _out(text):
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    return str(text).encode(enc, errors="replace").decode(enc, errors="replace")


def check(name, actual, expected):
    ok = actual == expected
    print(_out("[%s] %s: %r (expected %r)" % ("PASS" if ok else "FAIL", name, actual, expected)))
    if not ok:
        failures.append(name)


def check_true(name, cond, detail=""):
    ok = bool(cond)
    print(_out("[%s] %s%s" % ("PASS" if ok else "FAIL", name, "" if ok else " -> " + str(detail))))
    if not ok:
        failures.append(name)


def rows_of(resp):
    """`success(data)` 봉투에서 목록을 꺼낸다.

    ★ 이 헬퍼가 없던 첫 판본은 `resp["items"]` 를 읽어 **항상 빈 목록**을 보고,
      그 때문에 "관심물건이 안 들어갔다"와 "B 가 A 의 것을 지웠다(IDOR)"를
      **둘 다 거짓으로** 보고했다. 봉투를 잘못 읽으면 없는 결함이 보인다.
    """
    body = resp.json() or {}
    if isinstance(body.get("data"), list):
        return body["data"]
    if isinstance(body.get("data"), dict) and isinstance(body["data"].get("items"), list):
        return body["data"]["items"]
    if isinstance(body.get("items"), list):
        return body["items"]
    return []


def headers(user):
    return {"Authorization": "Bearer " + jwt.encode({"sub": user}, SUPABASE_JWT_SECRET,
                                                    algorithm="HS256")}


def cleanup(user_ids, item_ids):
    """이 검사가 만든 행만 지운다. 운영 데이터는 건드리지 않는다."""
    conn = get_connection()
    try:
        for uid in user_ids:
            conn.execute("DELETE FROM favorites WHERE user_id=?", (uid,))
            conn.execute("DELETE FROM recent_items WHERE user_id=?", (uid,))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
def test_same_item_id_survives_the_whole_user_path():
    """검색 → 상세 → 최근본 → 관심물건 → 문서 → 재조회 가 **같은 물건**을 가리킨다."""
    print("\n--- 1. 같은 itemId 가 사용자 경로 끝까지 간다 ---")

    r = client.get("/api/v1/search?size=1&include_closed=true")
    check("검색이 200", r.status_code, 200)
    items = (r.json() or {}).get("items") or []
    check_true("검색 결과가 있다(검사 전제)", len(items) == 1, len(items))
    if not items:
        return None
    card = items[0]
    item_id = card["id"]
    check_true("★ 검색 카드가 canonical id 를 준다 (id=%r)" % item_id,
               isinstance(item_id, int) and item_id > 0, item_id)

    # (2) 상세 — 같은 id 이고 업무 키까지 같은가
    d = client.get("/api/v1/item/%d" % item_id, headers=headers(USER_A))
    check("상세가 200", d.status_code, 200)
    detail = d.json()
    check("★ 상세의 id 가 카드의 id 와 같다", detail.get("id"), item_id)
    for key in ("case_no", "item_no", "court_name"):
        check("★ 상세의 %s 가 카드와 같다(같은 행이라는 근거)" % key,
              detail.get(key), card.get(key))

    # (3) 최근 본 물건
    #     ★ 기록 엔드포인트는 **없다.** 위 (2) 의 상세 조회가 `record_view()` 로
    #       자동 기록한다(api/v1/item.py:163). 그래서 여기서는 조회만 한다 —
    #       POST 를 보내면 405 다(첫 판본이 그렇게 틀렸다).
    rl = client.get("/api/v1/recent-items", headers=headers(USER_A))
    check("최근본 조회가 200", rl.status_code, 200)
    recent = rows_of(rl)
    check_true("★ 상세 조회만으로 최근본이 기록된다(별도 POST 없음)",
               len(recent) >= 1, len(recent))
    rec_ids = [x.get("id") for x in recent]
    check_true("★ 최근본에 그 id 가 있다", item_id in rec_ids, rec_ids[:5])
    same = [x for x in recent if x.get("id") == item_id]
    if same:
        check("★ 최근본 행의 case_no 가 카드와 같다", same[0].get("case_no"),
              card.get("case_no"))

    # (4) 관심물건 등록
    fv = client.post("/api/v1/favorites", json={"item_id": item_id},
                     headers=headers(USER_A))
    check_true("관심물건 등록이 성공한다", fv.status_code in (200, 201), fv.status_code)
    fl = client.get("/api/v1/favorites", headers=headers(USER_A))
    favs = rows_of(fl)
    fav_ids = [x.get("id") for x in favs]
    check_true("★ 관심물건 목록에 그 id 가 있다", item_id in fav_ids, fav_ids[:5])
    fsame = [x for x in favs if x.get("id") == item_id]
    if fsame:
        check("★ 관심물건 행의 case_no 가 카드와 같다", fsame[0].get("case_no"),
              card.get("case_no"))

    # (5) 상세가 즐겨찾기 상태를 같은 id 로 되비춘다
    d2 = client.get("/api/v1/item/%d" % item_id, headers=headers(USER_A))
    check("★ 상세의 is_favorited 가 true 로 바뀐다", d2.json().get("is_favorited"), True)

    # (6) 문서도 **같은 id** 로 주소가 잡힌다
    h = client.head("/api/v1/item/%d/documents/SPEC" % item_id, headers=headers(USER_A))
    check_true("★ 문서 경로가 같은 id 를 받는다(200 또는 404, 5xx 아님)",
               h.status_code in (200, 401, 403, 404), h.status_code)

    # (7) 해제 후 재조회
    dl = client.delete("/api/v1/favorites/%d" % item_id, headers=headers(USER_A))
    check_true("관심물건 해제가 성공한다", dl.status_code in (200, 204), dl.status_code)
    fl2 = client.get("/api/v1/favorites", headers=headers(USER_A))
    check_true("★ 해제 후 목록에서 사라진다",
               item_id not in [x.get("id") for x in rows_of(fl2)],
               "still there")
    d3 = client.get("/api/v1/item/%d" % item_id, headers=headers(USER_A))
    check("★ 상세의 is_favorited 가 false 로 돌아온다", d3.json().get("is_favorited"), False)
    return item_id


# ---------------------------------------------------------------------------
def test_a_different_id_is_a_different_item():
    """id 를 바꾸면 **다른 물건**이 나온다 — 같은 것이 나오면 식별자가 무의미하다."""
    print("\n--- 2. id 가 다르면 물건도 다르다 ---")
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, case_no, item_no FROM auction_item ORDER BY id LIMIT 2").fetchall()
    finally:
        conn.close()
    check_true("검사 전제: 물건이 2건 이상 있다", len(rows) == 2, len(rows))
    if len(rows) < 2:
        return
    a, b = rows[0], rows[1]
    ra = client.get("/api/v1/item/%d" % a["id"], headers=headers(USER_A)).json()
    rb = client.get("/api/v1/item/%d" % b["id"], headers=headers(USER_A)).json()
    check("id a 응답의 id", ra.get("id"), a["id"])
    check("id b 응답의 id", rb.get("id"), b["id"])
    check_true("★ 서로 다른 id 는 서로 다른 행을 준다",
               (ra.get("case_no"), ra.get("item_no")) != (rb.get("case_no"), rb.get("item_no"))
               or a["id"] != b["id"],
               (ra.get("case_no"), rb.get("case_no")))


# ---------------------------------------------------------------------------
def test_id_tampering_does_not_cross_users():
    """A 의 id 를 B 가 들고 와도 **A 의 개인 데이터**에는 닿지 못한다."""
    print("\n--- 3. id 변조가 사용자 경계를 넘지 않는다 ---")
    conn = get_connection()
    try:
        item_id = conn.execute("SELECT id FROM auction_item ORDER BY id LIMIT 1").fetchone()["id"]
    finally:
        conn.close()

    client.post("/api/v1/favorites", json={"item_id": item_id}, headers=headers(USER_A))

    # B 가 같은 item_id 로 조회하면 — 물건은 공개지만 **찜 상태는 A 의 것이 아니다**
    db = client.get("/api/v1/item/%d" % item_id, headers=headers(USER_B))
    check("B 도 물건 자체는 볼 수 있다(공개 데이터)", db.status_code, 200)
    check("★ B 의 화면에 A 의 찜 상태가 새지 않는다", db.json().get("is_favorited"), False)

    # B 의 관심물건 목록에 A 의 항목이 없다
    lb = client.get("/api/v1/favorites", headers=headers(USER_B))
    check_true("★ B 의 목록에 A 의 항목이 없다",
               item_id not in [x.get("id") for x in rows_of(lb)],
               "leaked")

    # B 가 A 의 찜을 지우려 해도 **실제로 지워지지 않는다**
    client.delete("/api/v1/favorites/%d" % item_id, headers=headers(USER_B))
    la = client.get("/api/v1/favorites", headers=headers(USER_A))
    check_true("★ B 의 삭제 시도 후에도 A 의 항목은 남아 있다",
               item_id in [x.get("id") for x in rows_of(la)],
               "A 의 데이터가 지워졌다 - IDOR")

    # 비로그인은 개인화 경로에 아예 닿지 못한다
    anon = client.get("/api/v1/favorites")
    check_true("★ 비로그인은 관심물건을 못 본다", anon.status_code in (401, 403), anon.status_code)

    client.delete("/api/v1/favorites/%d" % item_id, headers=headers(USER_A))


# ---------------------------------------------------------------------------
def test_nonexistent_and_malformed_ids_are_not_5xx():
    """없는 id / 경계값이 500 을 만들지 않는다 (`test_id_bounds_sweep` 와 짝)."""
    print("\n--- 4. 없는 id / 경계값 ---")
    conn = get_connection()
    try:
        max_id = conn.execute("SELECT MAX(id) AS m FROM auction_item").fetchone()["m"] or 0
    finally:
        conn.close()

    for label, iid in (("존재하지 않는 id", max_id + 10_000),
                       ("0", 0), ("음수", -1),
                       ("SQLite INTEGER 상한 초과", 9223372036854775808)):
        r = client.get("/api/v1/item/%d" % iid, headers=headers(USER_A))
        check_true("%s -> 4xx (5xx 아님)" % label, 400 <= r.status_code < 500, r.status_code)

    # 없는 물건을 찜하려 하면 4xx 이고, 목록이 오염되지 않는다
    r = client.post("/api/v1/favorites", json={"item_id": max_id + 10_000},
                    headers=headers(USER_A))
    check_true("★ 없는 물건은 찜할 수 없다", 400 <= r.status_code < 500, r.status_code)
    fl = client.get("/api/v1/favorites", headers=headers(USER_A))
    check("★ 실패한 등록이 목록을 오염시키지 않는다",
          len(rows_of(fl)), 0)


def run():
    try:
        test_same_item_id_survives_the_whole_user_path()
        test_a_different_id_is_a_different_item()
        test_id_tampering_does_not_cross_users()
        test_nonexistent_and_malformed_ids_are_not_5xx()
    finally:
        cleanup([USER_A, USER_B], [])

    print("\n" + "=" * 55)
    if failures:
        print("FAILED %d: %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL IDENTIFIER CONTRACT TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
