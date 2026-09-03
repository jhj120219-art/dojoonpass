"""관심물건 lifecycle + 검색카드 즐겨찾기 계약 (2026-09-03, P0-6 / P0-7).

## 이 파일이 보는 것

`test_api_regression.py` 가 인증·소유권·고아 행을 이미 본다
(`test_favorites_and_recent_items_survive_orphaned_auction_item` 등).
`test_identifier_contract.py` 가 id 연속성을 본다.

여기서는 그 사이에 남은 **사용자 흐름의 세부**를 본다:

    중복 등록        두 번 눌러도 행이 하나인가 (DB 를 직접 센다)
    빈 상태          아무것도 없을 때 오류가 아니라 빈 목록인가
    최신순           나중에 찜한 것이 위에 오는가 (동점이면 id 로 결정적인가)
    없는 것 해제      404 가 아니라 도메인 오류 코드인가
    쓰기 경로 단일화   검색 카드와 상세가 **같은 엔드포인트**를 쓰는가 (P0-7)

## 왜 DB 를 직접 세나

API 응답만 보면 "중복이 안 보인다"와 "중복이 없다"를 구분하지 못한다. 목록 쿼리가
`DISTINCT` 를 쓰거나 JOIN 이 접으면 행이 둘이어도 화면은 하나로 보인다. 그래서
이 파일은 매 단계에서 `favorites` 행을 **직접 센다**.

## 실행

    python test_favorites_lifecycle.py
"""
import os
import sys
import uuid
import secrets

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if not os.getenv("SUPABASE_JWT_SECRET"):
    os.environ["SUPABASE_JWT_SECRET"] = "qa-favlife-" + secrets.token_hex(16)

from jose import jwt                                    # noqa: E402
from fastapi.testclient import TestClient               # noqa: E402

import api_server                                       # noqa: E402
from api.auth import SUPABASE_JWT_SECRET                # noqa: E402
from api.constants import ErrorCode                     # noqa: E402
from storage.database import get_connection             # noqa: E402

client = TestClient(api_server.app)
failures = []
USER = "qa-fav-" + uuid.uuid4().hex[:10]


def _out(t):
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    return str(t).encode(enc, errors="replace").decode(enc, errors="replace")


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


def hdr(user=USER):
    return {"Authorization": "Bearer " + jwt.encode({"sub": user}, SUPABASE_JWT_SECRET,
                                                    algorithm="HS256")}


def rows_of(resp):
    body = resp.json() or {}
    d = body.get("data")
    if isinstance(d, list):
        return d
    if isinstance(d, dict) and isinstance(d.get("items"), list):
        return d["items"]
    return body.get("items") or []


def db_count(user=USER, item_id=None):
    """`favorites` 행을 **직접** 센다 - API 가 접어서 보여주는 것과 구분한다."""
    conn = get_connection()
    try:
        if item_id is None:
            return conn.execute("SELECT COUNT(*) FROM favorites WHERE user_id=?",
                                (user,)).fetchone()[0]
        return conn.execute(
            "SELECT COUNT(*) FROM favorites WHERE user_id=? AND item_id=?",
            (user, item_id)).fetchone()[0]
    finally:
        conn.close()


def wipe(user=USER):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM favorites WHERE user_id=?", (user,))
        conn.execute("DELETE FROM recent_items WHERE user_id=?", (user,))
        conn.commit()
    finally:
        conn.close()


def some_items(n):
    conn = get_connection()
    try:
        return [r["id"] for r in conn.execute(
            "SELECT id FROM auction_item ORDER BY id LIMIT ?", (n,)).fetchall()]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
def test_empty_state_is_not_an_error():
    print("\n--- 1. 빈 상태 ---")
    wipe()
    r = client.get("/api/v1/favorites", headers=hdr())
    check("빈 목록도 200 이다", r.status_code, 200)
    check("빈 목록은 빈 배열이다(null 이 아니다)", rows_of(r), [])
    check("DB 도 0행", db_count(), 0)


# ---------------------------------------------------------------------------
def test_duplicate_add_creates_exactly_one_row():
    print("\n--- 2. 중복 등록 (연타) ---")
    wipe()
    item_id = some_items(1)[0]

    first = client.post("/api/v1/favorites", json={"item_id": item_id}, headers=hdr())
    check_true("첫 등록이 성공한다", first.status_code in (200, 201), first.status_code)
    check("DB 1행", db_count(item_id=item_id), 1)

    second = client.post("/api/v1/favorites", json={"item_id": item_id}, headers=hdr())
    check_true("두 번째 등록도 5xx 가 아니다", second.status_code < 500, second.status_code)
    body = second.json() or {}
    check("★ 두 번째는 '이미 등록됨' 도메인 코드로 답한다",
          body.get("error"), ErrorCode.FAVORITE_ALREADY_EXISTS)
    check("★★ 연타해도 DB 행은 하나다", db_count(item_id=item_id), 1)

    # 세 번, 네 번 눌러도 마찬가지
    for _ in range(3):
        client.post("/api/v1/favorites", json={"item_id": item_id}, headers=hdr())
    check("★★ 다섯 번 눌러도 하나다", db_count(item_id=item_id), 1)

    # 목록에도 하나만
    listed = [x["id"] for x in rows_of(client.get("/api/v1/favorites", headers=hdr()))]
    check("목록에도 한 번만 나온다", listed.count(item_id), 1)
    wipe()


# ---------------------------------------------------------------------------
def test_list_is_newest_first_and_deterministic():
    print("\n--- 3. 최신순 + 결정적 정렬 ---")
    wipe()
    ids = some_items(3)
    check_true("검사 전제: 물건 3건", len(ids) == 3, ids)
    if len(ids) < 3:
        return

    # created_at 을 **직접** 벌려 둔다 - API 로 연속 등록하면 같은 초에 들어가
    # 무엇이 최신인지 검사가 판정할 수 없다(그러면 검사가 공허해진다).
    conn = get_connection()
    try:
        for i, iid in enumerate(ids):
            conn.execute(
                "INSERT INTO favorites (user_id, item_id, created_at) VALUES (?,?,?)",
                (USER, iid, "2026-09-0%d T00:00:00".replace(" ", "") % (i + 1)))
        conn.commit()
    finally:
        conn.close()

    listed = [x["id"] for x in rows_of(client.get("/api/v1/favorites", headers=hdr()))]
    check("★ 나중에 찜한 것이 먼저 온다", listed, list(reversed(ids)))

    # 같은 created_at 이어도 순서가 흔들리지 않는다(id DESC 가 동점을 끊는다)
    wipe()
    conn = get_connection()
    try:
        for iid in ids:
            conn.execute(
                "INSERT INTO favorites (user_id, item_id, created_at) VALUES (?,?,?)",
                (USER, iid, "2026-09-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()
    a = [x["id"] for x in rows_of(client.get("/api/v1/favorites", headers=hdr()))]
    b = [x["id"] for x in rows_of(client.get("/api/v1/favorites", headers=hdr()))]
    check("★ 동점에서도 두 번 부른 결과가 같다(결정적)", a, b)
    check_true("동점 정렬이 임의가 아니다(id 내림차순)", a == sorted(a, reverse=True), a)
    wipe()


# ---------------------------------------------------------------------------
def test_remove_paths():
    print("\n--- 4. 해제 ---")
    wipe()
    item_id = some_items(1)[0]
    client.post("/api/v1/favorites", json={"item_id": item_id}, headers=hdr())
    check("사전: 1행", db_count(item_id=item_id), 1)

    d = client.delete("/api/v1/favorites/%d" % item_id, headers=hdr())
    check_true("해제가 성공한다", d.status_code in (200, 204), d.status_code)
    check("★ DB 에서 실제로 사라진다", db_count(item_id=item_id), 0)

    again = client.delete("/api/v1/favorites/%d" % item_id, headers=hdr())
    check_true("없는 것을 또 해제해도 5xx 가 아니다", again.status_code < 500, again.status_code)
    check("★ '없음' 도메인 코드로 답한다",
          (again.json() or {}).get("error"), ErrorCode.FAVORITE_NOT_FOUND)
    check("여전히 0행", db_count(item_id=item_id), 0)
    wipe()


# ---------------------------------------------------------------------------
def test_single_canonical_mutation_path():
    """P0-7 — 검색 카드와 상세 화면이 **같은 쓰기 경로**를 쓴다."""
    print("\n--- 5. 쓰기 경로가 하나인가 (P0-7) ---")
    import io as _io
    import re as _re

    root = os.path.dirname(os.path.abspath(__file__))

    def read(rel):
        return _io.open(os.path.join(root, rel.replace("/", os.sep)),
                        encoding="utf-8").read()

    card = read("src/app/search/FavoriteButton.tsx")
    detail = read("src/app/properties/[id]/page.tsx")

    for label, src in (("검색 카드", card), ("상세 화면", detail)):
        check_true("%s 가 POST /api/v1/favorites 를 쓴다" % label,
                   "/api/v1/favorites" in src, label)
        # 두 화면 모두 **자기만의 쓰기 SQL/다른 경로**를 만들지 않는다
        check_true("%s 가 별도 쓰기 경로를 만들지 않는다" % label,
                   "favorite_import" not in src and "INSERT INTO" not in src, label)

    # 연타 가드: await 이전에 **동기적으로** busy 를 세우는가.
    # 이 순서가 뒤집히면 getSession() 이 끝나기 전의 재클릭이 가드를 통과한다.
    for label, src in (("검색 카드", card), ("상세 화면", detail)):
        # 가드 조건은 화면마다 다르다(`favBusy` / `favBusy || !property`)이고
        # 그 사이에 주석이 얼마든지 올 수 있다. 그래서 모양을 통째로 맞추려 들지
        # 않고 보는 것을 하나로 줄인다 — 가드와 `setFavBusy(true)` **사이에
        # await 가 있는가**. (첫 판본은 `if (favBusy) return` 만 매칭해
        #  상세 화면을 오탐했다.)
        gm = _re.search(r"if \(favBusy[^)]*\)\s*return", src)
        sm = _re.search(r"setFavBusy\(true\)", src)
        between = (src[gm.end():sm.start()]
                   if (gm and sm and sm.start() > gm.end()) else None)
        # ★ 주석을 먼저 걷어낸다 — 하필 이 자리의 주석이 "await 이전에 동기적으로"
        #   라고 설명하고 있어서, 그대로 세면 **설명 문장 때문에** 검사가
        #   실패한다(2026-09-03 실제로 두 화면 다 오탐했다).
        code_between = None
        if between is not None:
            code_between = "\n".join(ln.split("//")[0] for ln in between.split("\n"))
        sync_guard = (None if code_between is None
                      else ("await" not in code_between))
        check_true("★ %s 가 await 전에 동기적으로 연타를 막는다" % label,
                   sync_guard is True,
                   "favBusy 가드와 setFavBusy(true) 사이에 await 가 끼면 안 된다 "
                   "(사이 코드: %r)" % ((code_between or "")[:160],))

    # 낙관적 UI 가 아니다 - 서버 성공을 확인한 뒤에만 하트를 뒤집는다.
    # (그래서 롤백 로직 자체가 필요 없다. 낙관적으로 바꾸는 순간 롤백이 필요해진다.)
    check_true("★ 검색 카드가 서버 확인 뒤에만 상태를 바꾼다",
               card.index("setFavorited(false)") > card.index("await deleteJSON"),
               "낙관적 UI 로 바뀌었다면 실패 시 롤백 검사를 함께 넣어야 한다")


# ---------------------------------------------------------------------------
def test_add_uses_existence_check_not_a_second_item_shape():
    """P0-1 (Frankenstein) — 담기 경로가 **물건 응답 모양을 또 조립하지 않는다.**

    2026-09-04 이전에는 `api/v1/favorites.py:get_item_summary()` 가 `SELECT *` 로
    14개 필드의 물건 dict 를 만들었고, 유일한 호출부가 그것을
    **있다/없다만 보고 버렸다.** 그런데 실제 목록 응답(`get_favorites()`)은
    그 사이 필드가 다섯 개 늘어 **같은 개념의 모양이 두 벌**이 됐다.

    이름이 더 그럴듯한 쪽(쓰이지 않는 쪽)을 고치면 **아무 일도 일어나지
    않고 오류도 안 난다** — 이 저장소가 반복해서 겉어 온 모양이라
    되돌아오지 않게 여기서 못박는다.

    두 층으로 본다 — **동작**(404/200 계약이 그대로인가)과
    **모양**(담기 응답이 물건 필드를 실어 나르지 않는가).
    동작만 보면 사본이 되살아나도 초록이다.
    """
    print("\n--- 6. 담기는 존재 확인만 한다 (P0-1 Frankenstein) ---")
    import io as _io
    import inspect as _inspect
    import api.v1.favorites as fav

    wipe()
    item_id = some_items(1)[0]

    # --- 동작: 판정 계약이 종전과 같다 ---
    ok = client.post("/api/v1/favorites", json={"item_id": item_id}, headers=hdr())
    check("있는 물건은 담긴다", ok.status_code, 200)
    check("★ DB 에 실제로 1행", db_count(item_id=item_id), 1)

    gone = client.post("/api/v1/favorites", json={"item_id": 2 ** 40}, headers=hdr())
    check("없는 물건은 404", gone.status_code, 404)
    # 범위 밖 id 는 sqlite3 OverflowError -> 500 이 될 수 있던 자리다
    # (Sprint 154). 가드가 `item_exists()` 안에 그대로 남아 있는지 본다.
    huge = client.post("/api/v1/favorites", json={"item_id": 2 ** 63}, headers=hdr())
    check("★ SQLite 범위 밖 id 도 500 이 아니라 404", huge.status_code, 404)
    neg = client.post("/api/v1/favorites", json={"item_id": -1}, headers=hdr())
    check("음수 id 도 404", neg.status_code, 404)

    # --- 모양: 담기 응답은 물건 필드를 실지 않는다 ---
    body = (ok.json() or {}).get("data") or {}
    check("담기 응답 키는 종전과 같다", sorted(body), ["created_at", "item_id"])
    leaked = sorted(k for k in body
                    if k in ("case_no", "court_name", "full_address",
                             "appraisal_price", "minimum_bid_price", "bid_rate",
                             "auction_date", "status", "fail_count"))
    check("★ 담기 응답에 물건 필드가 실리지 않는다", leaked, [])

    # --- 소스: 두 번째 물건 모양 조립기가 생기지 않는다 ---
    #   `get_favorites()` 만이 목록 모양을 만든다. 담기/해제 쪽에
    #   필드 목록이 다시 나타나면 같은 사고가 재발한 것이다.
    root = os.path.dirname(os.path.abspath(__file__))
    src = _io.open(os.path.join(root, "api", "v1", "favorites.py"),
                   encoding="utf-8-sig").read()
    builders = [name for name in ("add_favorite", "remove_favorite", "item_exists")
                if '"case_no": row[' in _inspect.getsource(getattr(fav, name))]
    check("★ 담기/해제/존재확인은 물건 모양을 조립하지 않는다", builders, [])
    check("★ 목록 모양 조립기는 get_favorites 하나다",
          src.count('"case_no": row['), 1)

    # 존재 판정은 `favorite_import` 의 정본과 **같은 모양**이어야 한다.
    exists_src = _inspect.getsource(fav.item_exists)
    check_true("★ 존재 확인은 SELECT 1 이다(행 전체를 읽지 않는다)",
               "SELECT 1 FROM auction_item" in exists_src
               and "SELECT * FROM auction_item" not in exists_src,
               exists_src)

    # 자기 검증 — 위 소스 검사가 공허하지 않다(찾는 문자열이 실재한다).
    check_true("자기 검증: 목록 조립기를 실제로 찾았다",
               '"case_no": row[' in _inspect.getsource(fav.get_favorites),
               "검사가 찾는 모양이 사라졌다 - 검사를 먼저 고쳐야 한다")
    wipe()

def run():
    try:
        test_empty_state_is_not_an_error()
        test_duplicate_add_creates_exactly_one_row()
        test_list_is_newest_first_and_deterministic()
        test_remove_paths()
        test_single_canonical_mutation_path()
        test_add_uses_existence_check_not_a_second_item_shape()
    finally:
        wipe()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED %d: %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL FAVORITES LIFECYCLE TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
