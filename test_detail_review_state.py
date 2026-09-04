"""상세 한 번으로 REVIEW 상태가 전부 오는가 (2026-09-05 신설).

## 왜 이 파일이 있나

이 제품이 줄이겠다고 말한 것은 **판단까지 걸리는 시간**이다. 그 시간이 가장 많이
새는 곳은 기능이 아니라 **가장 자주 열리는 화면이 치르는 왕복**이다.

상세 화면은 진입할 때 두 번 요청했다.

    GET /api/v1/item/{id}            <- 물건 + 내 관심/임장 상태
    GET /api/v1/registry-requests    <- 내 등기부 신청 **전체**  (이어서, 순차로)

두 번째가 나쁜 이유가 둘이다.

    1. **순차다.** 첫 응답이 와야 시작하므로 지연이 겹치지 않고 더해진다.
    2. **한 건이 필요한데 전부를 받았다.** 프런트가 `find(r => r.item_id === id)`
       로 하나만 골라 썼다. 비용이 사용자의 이력에 비례해 커진다.

실측(2026-09-05, 스크래치 사본):

        내 신청 수    예전(목록 전체)   지금(상세의 한 필드)
             0            66 B              4 B
             1           335 B            127 B
             5         1,258 B            127 B
            20         5,973 B            127 B
            50        14,736 B            127 B

한 물건의 상태를 알려고 14 KB 를 실어 나르던 것이 127 B 로 **평평해진다.**
SQL 개수는 양쪽 다 1개다 — 바뀐 것은 왕복 수와 실어 나르는 양이지 질의 수가 아니다.
(그래서 "요청이 줄었으니 빨라졌다"고 적지 않는다. 줄어든 것을 정확히 적는다.)

## 무엇을 고정하나

상세 응답의 **개인화 3종**이 한 번에 온다: `is_favorited` / `field_visit` /
`registry_request`. 그리고 그 셋이 **남의 것을 보여 주지 않는다.**

특히 `registry_request` 는 프런트가 하던 선택을 서버가 **그대로** 이어받아야 한다 —
목록은 `requested_at DESC, id DESC` 였고 `find()` 는 그 첫 항목을 잡았다. 즉
**가장 최근 신청**이다. 정렬을 빠뜨리면 같은 물건에 신청이 둘 이상일 때 조용히
다른 건을 보여 준다. 그 조용함이 정확히 이 저장소가 반복해서 잡아 온 부류다.

    python test_detail_review_state.py
"""
import os
import secrets
import sqlite3
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# api/auth.py 는 모듈 최상단에서 한 번만 읽으므로 import 전에 넣는다
# (test_field_visits.py 와 같은 방식·같은 이유).
if not os.getenv("SUPABASE_JWT_SECRET"):
    os.environ["SUPABASE_JWT_SECRET"] = "qa-review-" + secrets.token_hex(16)

# ★ 운영 `auction.db` 를 건드리지 않는다 (docs/BUGS.md #186).
#   `get_connection()` 은 호출 시점에 모듈 전역을 읽으므로 이 재지정 한 줄이
#   API 라우터까지 함께 돌린다. `import api_server` **보다 먼저** 와야 한다.
import atexit as _qa_atexit                              # noqa: E402
import shutil as _qa_shutil                              # noqa: E402
import tempfile as _qa_tempfile                          # noqa: E402
import storage.database as _qa_dbmod                     # noqa: E402

_qa_tmp = _qa_tempfile.mkdtemp(prefix="dojoonpass-qa-review-")
_qa_atexit.register(_qa_shutil.rmtree, _qa_tmp, True)
_qa_scratch = os.path.join(_qa_tmp, "auction.db")
if os.path.exists(_qa_dbmod.DB_PATH):
    _qa_dbmod.snapshot_live_db(_qa_scratch)
_qa_dbmod.DB_PATH = _qa_scratch

from jose import jwt                                     # noqa: E402
from fastapi.testclient import TestClient                # noqa: E402
import api_server                                        # noqa: E402
from api.auth import SUPABASE_JWT_SECRET                 # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))
client = TestClient(api_server.app)
failures = []

USER_A = "qa-rv-a-" + uuid.uuid4().hex[:10]
USER_B = "qa-rv-b-" + uuid.uuid4().hex[:10]


def _out(text):
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    return str(text).encode(enc, errors="replace").decode(enc, errors="replace")


def check(name, actual, expected):
    ok = actual == expected
    print(_out("[%s] %s: %r (expected %r)"
               % ("PASS" if ok else "FAIL", name, actual, expected)))
    if not ok:
        failures.append(name)


def check_true(name, cond, detail=""):
    ok = bool(cond)
    print(_out("[%s] %s%s" % ("PASS" if ok else "FAIL", name,
                              "" if ok else " -> %r" % (detail,))))
    if not ok:
        failures.append(name)


def auth(user_id):
    return {"Authorization": "Bearer " + jwt.encode(
        {"sub": user_id}, SUPABASE_JWT_SECRET, algorithm="HS256")}


def db():
    conn = sqlite3.connect(_qa_scratch)
    conn.row_factory = sqlite3.Row
    return conn


def apply_field_migrations():
    """스크래치 사본에 030/031 을 적용한다. **운영 DB 는 건드리지 않는다.**"""
    conn = sqlite3.connect(_qa_scratch)
    try:
        for name in ("030_create_field_visits.sql",
                     "031_add_recent_items_first_viewed_at.sql"):
            path = os.path.join(ROOT, "storage", "migrations", name)
            conn.executescript(open(path, encoding="utf-8-sig").read())
        conn.commit()
    finally:
        conn.close()


def add_request(user_id, item_id, status, requested_at):
    conn = db()
    try:
        cur = conn.execute(
            "INSERT INTO registry_requests (user_id, item_id, status, requested_at)"
            " VALUES (?, ?, ?, ?)", (user_id, item_id, status, requested_at))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def detail(item_id, user_id=None):
    r = client.get("/api/v1/item/%d" % item_id,
                   headers=auth(user_id) if user_id else {})
    return r.status_code, (r.json() if r.status_code == 200 else None)


# ---------------------------------------------------------------- 1
def test_detail_carries_registry_state():
    """상세 응답이 등기부 신청 상태를 **함께** 싣는가."""
    print("\n--- 1. 상세가 등기부 상태를 함께 싣는다 ---")
    st, body = detail(TARGET, USER_A)
    check("상세가 200 이다", st, 200)
    check_true("★ 응답에 registry_request 키가 있다",
               "registry_request" in body, sorted(body)[:12])
    check("신청이 없으면 null 이다", body["registry_request"], None)

    rid = add_request(USER_A, TARGET, "PENDING", "2026-08-01T09:00:00")
    st, body = detail(TARGET, USER_A)
    rr = body["registry_request"]
    check_true("★ 신청이 있으면 실린다", rr is not None, rr)
    if rr:
        check("신청 id 가 맞다", rr["id"], rid)
        check("상태가 맞다", rr["status"], "PENDING")
        # ★ 계약을 넓히지 않는다 - 목록에 없던 값을 여기서 새로 만들지 않는다.
        #   `is_free` / `free_remaining` 은 신청을 **만든** 응답에만 있는 값이고,
        #   나중에 다시 조회했을 때의 잔여 횟수는 의미가 다르다.
        check("★ 필드 집합이 정확히 계약대로다", sorted(rr),
              ["completed_at", "id", "item_id", "reason", "requested_at", "status"])


# ---------------------------------------------------------------- 2
def test_most_recent_request_wins():
    """같은 물건에 신청이 여럿이면 **가장 최근** 것이 실리는가.

    프런트는 `requested_at DESC, id DESC` 로 내려온 목록에서 `find()` 로 첫 항목을
    잡았다. 서버가 그 선택을 그대로 이어받아야 한다 - 정렬을 빠뜨리면 SQLite 가
    아무 행이나 돌려주고, 화면은 **지난 신청의 상태**를 지금 상태인 양 보여 준다.
    """
    print("\n--- 2. 가장 최근 신청이 이긴다 ---")
    newer = add_request(USER_A, TARGET, "COMPLETED", "2026-08-20T09:00:00")
    _, body = detail(TARGET, USER_A)
    rr = body["registry_request"]
    check_true("★ 최근 신청이 실린다", rr and rr["id"] == newer,
               rr and (rr["id"], rr["requested_at"]))
    check("최근 신청의 상태다", rr and rr["status"], "COMPLETED")

    # 날짜가 같을 때는 id 가 큰 쪽 - 목록의 두 번째 정렬 키와 같아야 한다.
    same_day = add_request(USER_A, TARGET, "FAILED", "2026-08-20T09:00:00")
    _, body = detail(TARGET, USER_A)
    rr = body["registry_request"]
    check("★ 날짜가 같으면 id 가 큰 쪽이다", rr and rr["id"], same_day)


# ---------------------------------------------------------------- 3
def test_other_users_and_items_are_isolated():
    """남의 신청 / 다른 물건의 신청이 새지 않는가."""
    print("\n--- 3. 사용자·물건 분리 ---")
    _, body = detail(TARGET, USER_B)
    check("★ 남의 신청은 보이지 않는다", body["registry_request"], None)

    st, body = detail(OTHER, USER_A)
    check("다른 물건 상세도 200 이다", st, 200)
    check("★ 다른 물건의 신청 상태가 섞이지 않는다",
          body["registry_request"], None)

    add_request(USER_B, TARGET, "PENDING", "2026-08-25T09:00:00")
    _, body = detail(TARGET, USER_A)
    rr = body["registry_request"]
    check_true("★ 다른 사용자가 같은 물건을 신청해도 내 것이 그대로다",
               rr and rr["status"] == "FAILED", rr and rr["status"])


# ---------------------------------------------------------------- 4
def test_anonymous_gets_no_personal_state():
    """비로그인은 개인화 필드를 받지 않는가.

    상세는 **선택적 인증**이다(비로그인도 본다). 개인화 필드가 비로그인에게
    채워지면 그것 자체가 정보 노출이다.
    """
    print("\n--- 4. 비로그인 ---")
    st, body = detail(TARGET)
    check("비로그인도 상세를 본다", st, 200)
    check("★ registry_request 는 null", body["registry_request"], None)
    check("★ field_visit 는 null", body["field_visit"], None)
    check("★ is_favorited 는 False", body["is_favorited"], False)


# ---------------------------------------------------------------- 5
def test_review_state_arrives_in_one_response():
    """REVIEW 개인화 상태가 **한 응답에** 다 오는가.

    셋 중 하나라도 빠지면 화면은 그것 때문에 요청을 한 번 더 하게 된다 - 이 파일이
    막으려는 바로 그 모양이다. 그래서 세 키의 **존재**를 함께 고정한다.
    """
    print("\n--- 5. 한 응답에 다 온다 ---")
    _, body = detail(TARGET, USER_A)
    for key in ("is_favorited", "field_visit", "registry_request"):
        check_true("★ 상세 응답에 %s 가 있다" % key, key in body, sorted(body)[:15])

    # 공허하지 않은가 - 응답이 비어 있으면 위 검사가 전부 조용히 통과한다.
    check_true("검사가 공허하지 않다 - 상세 응답에 물건 정보가 실려 있다",
               body.get("id") == TARGET and body.get("case_no"), body.get("id"))


# ---------------------------------------------------------------- 6
def test_detail_survives_missing_registry_table():
    """등기부 표를 읽지 못해도 상세는 살아 있는가.

    상세는 REVIEW 의 본체다. 부가 정보 하나 때문에 죽으면 **화면 전체가 사라진다.**
    `favorites.py` 가 `favorite_notes` 에, `item.py` 가 `field_visits` 에 두고 있는
    것과 같은 판단이라, 같은 성질을 여기서도 고정한다.
    """
    print("\n--- 6. 등기부 표를 못 읽어도 상세는 산다 ---")
    conn = db()
    try:
        conn.execute("ALTER TABLE registry_requests RENAME TO registry_requests_hidden")
        conn.commit()
        st, body = detail(TARGET, USER_A)
        check("★ 표가 없어도 상세는 200 이다", st, 200)
        check("★ 그때 registry_request 는 null 이다",
              body and body["registry_request"], None)
        check_true("그래도 물건 정보는 온전하다", body and body.get("id") == TARGET,
                   body and body.get("id"))
    finally:
        conn.execute("ALTER TABLE registry_requests_hidden RENAME TO registry_requests")
        conn.commit()
        conn.close()
    # 되돌린 뒤 정상으로 돌아오는지까지 봐야 위 검사가 의미를 갖는다.
    _, body = detail(TARGET, USER_A)
    check_true("복구 후 다시 실린다", body["registry_request"] is not None,
               body["registry_request"])


if __name__ == "__main__":
    apply_field_migrations()
    conn = db()
    rows = [r[0] for r in conn.execute(
        "SELECT id FROM auction_item ORDER BY id LIMIT 2")]
    conn.close()
    if len(rows) < 2:
        print("[SKIP] 스크래치 DB 에 물건이 2건 미만이다 - 비교할 대상이 없다")
        sys.exit(0)
    TARGET, OTHER = rows[0], rows[1]

    test_detail_carries_registry_state()
    test_most_recent_request_wins()
    test_other_users_and_items_are_isolated()
    test_anonymous_gets_no_personal_state()
    test_review_state_arrives_in_one_response()
    test_detail_survives_missing_registry_table()

    print("")
    if failures:
        print(_out("FAILED (%d): %s" % (len(failures), ", ".join(failures))))
        sys.exit(1)
    print("ALL DETAIL REVIEW STATE TESTS PASSED")
    sys.exit(0)
