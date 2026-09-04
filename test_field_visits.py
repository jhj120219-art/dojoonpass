"""임장(현장 확인) 회귀 테스트 — FIELD 단계의 vertical slice (2026-09-04 신설).

## 무엇을 지키나

`DISCOVER → REVIEW → FIELD → DECIDE` 에서 FIELD 는 이번에 처음 생긴 칸이다.
그래서 "동작한다"가 아니라 **현장에서 실제로 쓸 수 있는가**를 본다:

    시작 -> 체크 -> 메모/위험요소 -> 완료 -> 판단
    새로고침해도 남아 있는가          (현장에서 앱이 죽는다)
    같은 버튼을 두 번 눌러도 되는가    (장갑 낀 손, 느린 회선)
    남의 기록이 보이지 않는가          (IDOR)
    다른 물건과 섞이지 않는가

## 왜 스크래치 DB 인가

migration 030 의 **운영 적용은 승인 영역**이다(`docs/CLAUDE.md`). 그래서 이 검사는
운영 `auction.db` 를 건드리지 않고, 스냅샷 사본에 030 을 적용해서 돈다.
`test_subscription_policy.py` / `test_favorites_lifecycle.py` 와 같은 방식이다
(경위: `docs/BUGS.md` #186).

    python test_field_visits.py
"""
import io
import os
import sys
import uuid
import shutil
import sqlite3
import secrets
import tempfile
import contextlib
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# api/auth.py 는 모듈 최상단에서 한 번만 읽으므로 import 전에 넣는다
# (test_api_regression.py 와 같은 방식·같은 이유).
if not os.getenv("SUPABASE_JWT_SECRET"):
    os.environ["SUPABASE_JWT_SECRET"] = "qa-field-" + secrets.token_hex(16)

# ★ 운영 `auction.db` 를 건드리지 않는다 (docs/BUGS.md #186).
#   `get_connection()` 은 호출 시점에 모듈 전역을 읽으므로 이 재지정 한 줄이
#   API 라우터까지 함께 돌린다. `import api_server` **보다 먼저** 와야 한다.
import atexit as _qa_atexit
import shutil as _qa_shutil
import tempfile as _qa_tempfile
import storage.database as _qa_dbmod
_qa_tmp = _qa_tempfile.mkdtemp(prefix="dojoonpass-qa-field-")
_qa_atexit.register(_qa_shutil.rmtree, _qa_tmp, True)
_qa_scratch = os.path.join(_qa_tmp, "auction.db")
if os.path.exists(_qa_dbmod.DB_PATH):
    _qa_dbmod.snapshot_live_db(_qa_scratch)
_qa_dbmod.DB_PATH = _qa_scratch

from jose import jwt                                    # noqa: E402
from fastapi.testclient import TestClient               # noqa: E402

import api_server                                       # noqa: E402
from api.auth import SUPABASE_JWT_SECRET                # noqa: E402
from api.constants import ErrorCode                     # noqa: E402
from api.v1.field_visits import (                       # noqa: E402
    CHECK_ITEMS, CHECK_KEYS, DECISIONS, MAX_NOTE_LEN,
    FIELD_STATUS_IN_PROGRESS, FIELD_STATUS_DONE,
    DECISION_BID, DECISION_HOLD, DECISION_DROP,
)

client = TestClient(api_server.app)
failures = []

USER_A = "qa-fv-a-" + uuid.uuid4().hex[:10]
USER_B = "qa-fv-b-" + uuid.uuid4().hex[:10]


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


def apply_030():
    """스크래치 사본에 030 / 031 을 적용한다. **운영 DB 는 건드리지 않는다.**

    031(`recent_items.first_viewed_at`)도 함께 적용한다 - §9 가 T2D 시작점이
    상한 정리에 살아남는지 보는데, 그 열이 없으면 판정 자체를 못 한다.
    """
    root = os.path.dirname(os.path.abspath(__file__))
    conn = sqlite3.connect(_qa_dbmod.DB_PATH)
    try:
        for name in ("030_create_field_visits.sql",
                     "031_add_recent_items_first_viewed_at.sql"):
            sql = io.open(os.path.join(root, "storage", "migrations", name),
                          encoding="utf-8-sig").read()
            try:
                conn.executescript(sql)
            except sqlite3.OperationalError as exc:
                # 031 은 ADD COLUMN 이라 이미 있으면 죽는다(러너는 파일명으로 거른다).
                if "duplicate column" not in str(exc).lower():
                    raise
        conn.commit()
    finally:
        conn.close()


def any_item_id():
    conn = sqlite3.connect(_qa_dbmod.DB_PATH)
    try:
        row = conn.execute("SELECT id FROM auction_item ORDER BY id LIMIT 1").fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def two_item_ids():
    conn = sqlite3.connect(_qa_dbmod.DB_PATH)
    try:
        rows = conn.execute("SELECT id FROM auction_item ORDER BY id LIMIT 2").fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


def body(res):
    try:
        return res.json()
    except Exception:                       # noqa: BLE001
        return {}


def err_of(res):
    """실패 응답의 Error Code. FastAPI 는 HTTPException.detail 을 그대로 싣는다."""
    d = body(res)
    det = d.get("detail") if isinstance(d, dict) else None
    if isinstance(det, dict):
        return det.get("error")
    return d.get("error") if isinstance(d, dict) else None


# ---------------------------------------------------------------------------
# 0. 마이그레이션 전 — **조용히 성공하지 않는다**
# ---------------------------------------------------------------------------
def test_unavailable_before_migration():
    """030 이 안 돈 환경에서 임장 API 가 정직하게 답하는가.

    이 검사가 없으면, 표가 없을 때 500(서버 오류)으로 떨어져도 아무도 모른다.
    운영자가 해야 할 일은 "서버를 고치는 것"이 아니라 **마이그레이션 적용**이고,
    그 구별이 응답에 담겨야 한다(`FAVORITE_NOTE_UNAVAILABLE` 과 같은 규약).
    """
    print("\n--- 0. migration 030 이전: 정직한 503 ---")
    item_id = any_item_id()
    check_true("전제: 물건이 하나는 있다", item_id is not None, item_id)

    r = client.post("/api/v1/field-visits", json={"item_id": item_id}, headers=auth(USER_A))
    check("시작 요청이 503", r.status_code, 503)
    check("★ 코드가 FIELD_UNAVAILABLE", err_of(r), ErrorCode.FIELD_UNAVAILABLE.value)

    r2 = client.get("/api/v1/field-visits/%d" % item_id, headers=auth(USER_A))
    check("조회도 503", r2.status_code, 503)
    check("조회도 같은 코드", err_of(r2), ErrorCode.FIELD_UNAVAILABLE.value)


# ---------------------------------------------------------------------------
# 1. 인증
# ---------------------------------------------------------------------------
def test_requires_auth():
    print("\n--- 1. 인증 없이는 아무것도 못 한다 ---")
    item_id = any_item_id()
    paths = [
        ("POST", "/api/v1/field-visits", {"item_id": item_id}),
        ("GET", "/api/v1/field-visits/%d" % item_id, None),
        ("PUT", "/api/v1/field-visits/%d/checks" % item_id,
         {"check_key": CHECK_KEYS[0], "checked": True}),
        ("PUT", "/api/v1/field-visits/%d/notes" % item_id, {"memo": "x"}),
        ("POST", "/api/v1/field-visits/%d/complete" % item_id, {}),
        ("PUT", "/api/v1/field-visits/%d/decision" % item_id, {"decision": DECISION_BID}),
    ]
    for method, path, payload in paths:
        res = client.request(method, path, json=payload)
        check("%s %s 는 인증을 요구한다" % (method, path.split("/")[-1]),
              res.status_code in (401, 403), True)


# ---------------------------------------------------------------------------
# 2. 정상 흐름 — 시작 -> 체크 -> 메모 -> 완료 -> 판단
# ---------------------------------------------------------------------------
def test_full_flow():
    print("\n--- 2. 시작 -> 체크 -> 메모 -> 완료 -> 판단 ---")
    apply_030()
    item_id = any_item_id()

    # (a) 시작
    r = client.post("/api/v1/field-visits", json={"item_id": item_id}, headers=auth(USER_A))
    check("시작 200", r.status_code, 200)
    d = body(r)["data"]
    check("상태가 IN_PROGRESS", d["status"], FIELD_STATUS_IN_PROGRESS)
    check("체크 항목 수가 정본과 같다", len(d["checks"]), len(CHECK_ITEMS))
    check("처음엔 아무것도 확인 안 됨", d["checked_count"], 0)
    check("완료 시각 없음", d["completed_at"], None)
    check("판단 없음", d["decision"], None)
    check_true("★ 서버가 항목 문구를 준다(화면이 어휘를 복제하지 않는다)",
               all(c["label"] for c in d["checks"]),
               [c["key"] for c in d["checks"] if not c["label"]])

    # (b) 중복 시작 — 오류가 아니라 같은 결과
    r2 = client.post("/api/v1/field-visits", json={"item_id": item_id}, headers=auth(USER_A))
    check("★ 두 번 시작해도 200", r2.status_code, 200)
    check("같은 시작 시각을 지킨다", body(r2)["data"]["started_at"], d["started_at"])

    # (c) 체크
    r3 = client.put("/api/v1/field-visits/%d/checks" % item_id,
                    json={"check_key": CHECK_KEYS[0], "checked": True, "note": "빈집"},
                    headers=auth(USER_A))
    check("체크 저장 200", r3.status_code, 200)
    d3 = body(r3)["data"]
    check("확인 수가 1", d3["checked_count"], 1)
    got = next(c for c in d3["checks"] if c["key"] == CHECK_KEYS[0])
    check("체크됨", got["checked"], True)
    check("항목 메모 저장", got["note"], "빈집")

    # 체크 해제도 된다(잘못 눌렀을 때)
    r4 = client.put("/api/v1/field-visits/%d/checks" % item_id,
                    json={"check_key": CHECK_KEYS[0], "checked": False},
                    headers=auth(USER_A))
    check("★ 체크 해제도 저장된다", body(r4)["data"]["checked_count"], 0)

    # (d) 메모 / 위험요소
    r5 = client.put("/api/v1/field-visits/%d/notes" % item_id,
                    json={"memo": "3층 남향", "risk_note": "옆집 소음"},
                    headers=auth(USER_A))
    d5 = body(r5)["data"]
    check("현장 메모 저장", d5["memo"], "3층 남향")
    check("위험요소 저장", d5["risk_note"], "옆집 소음")

    # ★ 하나만 보내면 다른 하나는 지워지지 않는다
    r6 = client.put("/api/v1/field-visits/%d/notes" % item_id,
                    json={"memo": "3층 남향 / 채광 좋음"}, headers=auth(USER_A))
    d6 = body(r6)["data"]
    check("메모만 바꿨다", d6["memo"], "3층 남향 / 채광 좋음")
    check("★ 보내지 않은 위험요소는 지워지지 않는다", d6["risk_note"], "옆집 소음")

    # 명시적으로 비우는 것은 된다
    r7 = client.put("/api/v1/field-visits/%d/notes" % item_id,
                    json={"risk_note": ""}, headers=auth(USER_A))
    check("빈 문자열을 보내면 지운다", body(r7)["data"]["risk_note"], None)

    # (e) 완료 — 체크를 다 하지 않아도 끝낼 수 있다
    r8 = client.post("/api/v1/field-visits/%d/complete" % item_id,
                     json={}, headers=auth(USER_A))
    d8 = body(r8)["data"]
    check("완료 200", r8.status_code, 200)
    check("상태 DONE", d8["status"], FIELD_STATUS_DONE)
    check_true("완료 시각이 찍힌다", bool(d8["completed_at"]), d8["completed_at"])
    check("★ 덜 확인해도 완료된다(기록을 포기시키지 않는다)", d8["checked_count"], 0)

    # 두 번 완료해도 처음 시각을 지킨다
    r9 = client.post("/api/v1/field-visits/%d/complete" % item_id,
                     json={}, headers=auth(USER_A))
    check("★ 완료는 멱등하다", body(r9)["data"]["completed_at"], d8["completed_at"])

    # (f) 판단 — DECIDE 로 연결되는 지점
    r10 = client.put("/api/v1/field-visits/%d/decision" % item_id,
                     json={"decision": DECISION_BID}, headers=auth(USER_A))
    d10 = body(r10)["data"]
    check("판단 저장", d10["decision"], DECISION_BID)
    check_true("판단 시각이 찍힌다", bool(d10["decided_at"]), d10["decided_at"])

    # 마음이 바뀌는 것은 정상이다
    r11 = client.put("/api/v1/field-visits/%d/decision" % item_id,
                     json={"decision": DECISION_DROP}, headers=auth(USER_A))
    check("판단을 바꿀 수 있다", body(r11)["data"]["decision"], DECISION_DROP)

    # (g) 새로고침 — 다시 읽어도 그대로다
    r12 = client.get("/api/v1/field-visits/%d" % item_id, headers=auth(USER_A))
    d12 = body(r12)["data"]
    check("새로고침 200", r12.status_code, 200)
    check("★ 새로고침해도 판단이 남는다", d12["decision"], DECISION_DROP)
    check("★ 새로고침해도 메모가 남는다", d12["memo"], "3층 남향 / 채광 좋음")
    check("★ 새로고침해도 완료 상태가 남는다", d12["status"], FIELD_STATUS_DONE)


# ---------------------------------------------------------------------------
# 3. 분리 — 다른 물건 / 다른 사용자
# ---------------------------------------------------------------------------
def test_isolation():
    print("\n--- 3. 물건별·사용자별로 섞이지 않는다 ---")
    ids = two_item_ids()
    check_true("전제: 물건이 둘 이상 있다", len(ids) >= 2, ids)
    first, second = ids[0], ids[1]

    # 다른 물건은 별개다
    r = client.get("/api/v1/field-visits/%d" % second, headers=auth(USER_A))
    check("★ 다른 물건에는 기록이 없다", r.status_code, 404)
    check("빈 상태 코드가 명확하다", err_of(r), ErrorCode.FIELD_VISIT_NOT_FOUND.value)

    client.post("/api/v1/field-visits", json={"item_id": second}, headers=auth(USER_A))
    client.put("/api/v1/field-visits/%d/notes" % second,
               json={"memo": "두 번째 물건"}, headers=auth(USER_A))
    a_first = body(client.get("/api/v1/field-visits/%d" % first, headers=auth(USER_A)))["data"]
    a_second = body(client.get("/api/v1/field-visits/%d" % second, headers=auth(USER_A)))["data"]
    check("★ 물건마다 메모가 따로다", a_second["memo"], "두 번째 물건")
    check_true("첫 물건 메모는 그대로", a_first["memo"] != a_second["memo"],
               (a_first["memo"], a_second["memo"]))

    # 남의 기록은 보이지 않는다 (IDOR)
    rb = client.get("/api/v1/field-visits/%d" % first, headers=auth(USER_B))
    check("★ 남의 임장 기록은 보이지 않는다", rb.status_code, 404)

    # 남의 기록을 고칠 수도 없다
    rb2 = client.put("/api/v1/field-visits/%d/notes" % first,
                     json={"memo": "침입"}, headers=auth(USER_B))
    check("★ 남의 기록을 고칠 수 없다", rb2.status_code, 404)
    still = body(client.get("/api/v1/field-visits/%d" % first, headers=auth(USER_A)))["data"]
    check("원래 메모가 그대로다", still["memo"], "3층 남향 / 채광 좋음")


# ---------------------------------------------------------------------------
# 4. 잘못된 입력 — 조용히 받아들이지 않는다
# ---------------------------------------------------------------------------
def test_bad_input():
    print("\n--- 4. 잘못된 입력을 조용히 받지 않는다 ---")
    item_id = any_item_id()

    r = client.post("/api/v1/field-visits", json={"item_id": 999999999},
                    headers=auth(USER_A))
    check("없는 물건은 404", r.status_code, 404)
    check("코드가 ITEM_NOT_FOUND", err_of(r), ErrorCode.ITEM_NOT_FOUND.value)

    # ★ SQLite INTEGER 범위 밖 — Sprint 154 가 잡은 "인증된 사용자가 만드는 500"
    huge = 2 ** 63
    r2 = client.post("/api/v1/field-visits", json={"item_id": huge}, headers=auth(USER_A))
    check("★ 범위 밖 id 가 500 을 만들지 않는다", r2.status_code, 404)
    r3 = client.get("/api/v1/field-visits/%d" % huge, headers=auth(USER_A))
    check_true("★ 조회도 500 이 아니다", r3.status_code != 500, r3.status_code)

    r4 = client.put("/api/v1/field-visits/%d/checks" % item_id,
                    json={"check_key": "존재하지않는항목", "checked": True},
                    headers=auth(USER_A))
    check("모르는 확인 항목은 400", r4.status_code, 400)
    check("코드가 FIELD_INVALID_CHECK_KEY", err_of(r4),
          ErrorCode.FIELD_INVALID_CHECK_KEY.value)

    r5 = client.put("/api/v1/field-visits/%d/decision" % item_id,
                    json={"decision": "MAYBE"}, headers=auth(USER_A))
    check("모르는 판단 값은 400", r5.status_code, 400)
    check("코드가 FIELD_INVALID_DECISION", err_of(r5),
          ErrorCode.FIELD_INVALID_DECISION.value)

    r6 = client.put("/api/v1/field-visits/%d/notes" % item_id,
                    json={"memo": "가" * (MAX_NOTE_LEN + 1)}, headers=auth(USER_A))
    check("너무 긴 메모는 400", r6.status_code, 400)
    check("코드가 FIELD_NOTE_TOO_LONG", err_of(r6), ErrorCode.FIELD_NOTE_TOO_LONG.value)

    # 시작하지 않은 물건에 체크를 저장하려 하면 404 (조용히 만들지 않는다)
    ids = two_item_ids()
    conn = sqlite3.connect(_qa_dbmod.DB_PATH)
    try:
        row = conn.execute(
            "SELECT id FROM auction_item WHERE id NOT IN (?,?) ORDER BY id LIMIT 1",
            (ids[0], ids[1])).fetchone()
    finally:
        conn.close()
    if row:
        r7 = client.put("/api/v1/field-visits/%d/checks" % row[0],
                        json={"check_key": CHECK_KEYS[0], "checked": True},
                        headers=auth(USER_A))
        check("★ 시작 안 한 물건에는 체크가 안 붙는다", r7.status_code, 404)


# ---------------------------------------------------------------------------
# 5. 어휘 계약 — 정본이 하나인가
# ---------------------------------------------------------------------------
# 체크리스트에 **있어야 하는** 항목. 정본과 독립인 **두 번째 출처**다.
#
# ★ 왜 손으로 적나 (2026-09-04, 변이 F4 로 발견)
#
#   아래 검사들은 `len(응답) == len(CHECK_ITEMS)` 처럼 **양쪽 다 같은 상수**에서
#   나온다. 그래서 누가 `CHECK_ITEMS` 에서 항목을 지워도 응답과 기대값이 함께
#   줄어들어 **전부 통과한다** — 변이 F4 가 실제로 살아남았다.
#
#   체크리스트는 제품 내용이다. 실수로 한 항목이 사라지면 사용자는 현장에서 그것을
#   확인하지 않게 되고, 오류는 나지 않는다. 그래서 정본과 **독립인** 목록을 둔다
#   (`test_queue_safety_invariants.py` (e) 가 상수 오타를 잡으려고 쓰는 것과 같은 방법).
#
#   제품이 항목을 **일부러** 바꿀 때는 이 목록도 함께 고친다. 그 한 줄이
#   "체크리스트가 바뀌었다"는 사실을 리뷰에 드러내는 값이다.
EXPECTED_CHECK_KEYS = ("occupancy", "tenant", "eviction",
                       "building", "surroundings", "price")


def test_vocabulary_contract():
    print("\n--- 5. 체크/판단 어휘의 정본이 하나다 ---")
    check("체크 키가 중복 없이 선언됐다", len(set(CHECK_KEYS)), len(CHECK_KEYS))
    check_true("체크 항목이 비어 있지 않다", len(CHECK_ITEMS) >= 3, len(CHECK_ITEMS))
    # ★ 독립 출처와 대조한다 - 항목이 조용히 사라지거나 늘지 않는가.
    check("★ 체크 항목이 기대 목록과 정확히 같다(조용히 바뀌지 않았다)",
          list(CHECK_KEYS), list(EXPECTED_CHECK_KEYS))
    # 항목마다 사람이 읽을 문구가 있어야 한다 - 화면이 키를 그대로 그리면 안 된다.
    check("★ 모든 항목에 문구가 있다",
          sorted(k for k, label in CHECK_ITEMS if not (label or "").strip()), [])
    check("판단 값이 셋이다(BID/HOLD/DROP)",
          sorted(DECISIONS), sorted([DECISION_BID, DECISION_HOLD, DECISION_DROP]))

    # 서버 응답의 키 집합이 정본과 정확히 같다 — 화면이 목록을 복제하지 않아도 된다.
    item_id = any_item_id()
    d = body(client.get("/api/v1/field-visits/%d" % item_id, headers=auth(USER_A)))["data"]
    check("★ 응답의 체크 키가 정본과 같다",
          [c["key"] for c in d["checks"]], list(CHECK_KEYS))

    # ★ DB 에 저장된 키가 전부 정본 안에 있는가(어휘 밖 값이 새어 들어가지 않았는가).
    conn = sqlite3.connect(_qa_dbmod.DB_PATH)
    try:
        stored = [r[0] for r in conn.execute(
            "SELECT DISTINCT check_key FROM field_visit_checks")]
        decisions = [r[0] for r in conn.execute(
            "SELECT DISTINCT decision FROM field_visits WHERE decision IS NOT NULL")]
    finally:
        conn.close()
    check("★ DB 의 체크 키가 전부 어휘 안이다",
          sorted(k for k in stored if k not in CHECK_KEYS), [])
    check("★ DB 의 판단 값이 전부 어휘 안이다",
          sorted(v for v in decisions if v not in DECISIONS), [])


# ---------------------------------------------------------------------------
# 6. 완료하면서 판단까지 한 번에 (현장에서 결론이 나는 경우)
# ---------------------------------------------------------------------------
def test_complete_with_decision():
    print("\n--- 6. 완료와 판단을 한 번에 ---")
    ids = two_item_ids()
    target = ids[1]
    r = client.post("/api/v1/field-visits/%d/complete" % target,
                    json={"decision": DECISION_HOLD}, headers=auth(USER_A))
    d = body(r)["data"]
    check("완료 200", r.status_code, 200)
    check("상태 DONE", d["status"], FIELD_STATUS_DONE)
    check("★ 판단이 함께 기록된다", d["decision"], DECISION_HOLD)
    check_true("판단 시각이 찍힌다", bool(d["decided_at"]), d["decided_at"])

    # 판단 없이 완료하면 판단은 비어 있다 — "결론 못 냄"도 사실이다
    conn = sqlite3.connect(_qa_dbmod.DB_PATH)
    try:
        row = conn.execute(
            "SELECT id FROM auction_item WHERE id NOT IN (?,?) ORDER BY id LIMIT 1",
            (ids[0], ids[1])).fetchone()
    finally:
        conn.close()
    if row:
        client.post("/api/v1/field-visits", json={"item_id": row[0]}, headers=auth(USER_A))
        r2 = client.post("/api/v1/field-visits/%d/complete" % row[0],
                         json={}, headers=auth(USER_A))
        check("★ 판단 없이 완료하면 판단은 비어 있다", body(r2)["data"]["decision"], None)


# ---------------------------------------------------------------------------
# 7. REVIEW -> FIELD 준비 (2026-09-04)
# ---------------------------------------------------------------------------
def test_review_prefills_the_checklist():
    """상세에서 이미 확인된 사실이 체크 항목에 붙어 오는가.

    ## 왜 이것이 T2D 인가

    현장에 서서 "이 물건 임차인이 몇 명이라고 했더라"를 떠올리려고 앱을 오가는
    왕복이 곧 시간이다. 그 왕복을 없애려면 자료가 **체크 항목 옆에** 있어야 한다 —
    별도 패널이면 결국 화면을 오간다.

    ## 무엇을 지키나

    (1) 이미 아는 것은 붙는다            — 붙지 않으면 준비가 아니다
    (2) 모르는 것은 **지어내지 않는다**   — `None` 이지 "정보 없음" 같은 문구가 아니다
    (3) 개인정보를 싣지 않는다            — `tenant_rights` 에는 실명·보증금이 있다
                                          (BUGS #254). 집계 수만 쓴다
    (4) 저장하지 않는다                   — 원본이 바뀌면 따라 바뀐다
    (5) 판단을 붙이지 않는다              — "위험" 같은 평가는 범위 밖이다
    """
    print(chr(10) + "--- 7. REVIEW -> FIELD 준비 (체크 항목 prefill) ---")
    conn = sqlite3.connect(_qa_dbmod.DB_PATH)
    try:
        row = conn.execute(
            "SELECT rs.item_id, rs.occupancy_status, rs.total_tenant_count,"
            "       ai.sido, ai.sigungu"
            "  FROM rights_summary rs JOIN auction_item ai ON ai.id = rs.item_id"
            " WHERE rs.occupancy_status IS NOT NULL LIMIT 1").fetchone()
    finally:
        conn.close()
    if row is None:
        # 조용히 통과시키지 않는다 - 무엇을 못 봤는지 화면에 남긴다.
        print("   [판정 안 함] 권리분석이 있는 물건이 이 DB 에 없다 - 통과가 아니다")
        return
    item_id, occ, tenant_n, sido, sigungu = row

    r = client.post("/api/v1/field-visits", json={"item_id": item_id},
                    headers=auth(USER_A))
    check("준비된 물건의 임장 시작 200", r.status_code, 200)
    d = body(r)["data"]
    by_key = {c["key"]: c for c in d["checks"]}

    # (1) 이미 아는 것이 실제로 붙는다
    check_true("★ 하나 이상의 항목이 자료로 채워진다",
               d["known_count"] >= 1, d["known_count"])
    check_true("점유 항목에 저장된 점유 상태가 붙는다",
               occ in (by_key["occupancy"]["known"] or ""),
               by_key["occupancy"]["known"])
    check_true("주변 항목에 지역이 붙는다",
               (sido or "") in (by_key["surroundings"]["known"] or ""),
               by_key["surroundings"]["known"])
    if isinstance(tenant_n, int):
        check_true("임차인 항목에 **집계 수**가 붙는다",
                   str(tenant_n) in (by_key["tenant"]["known"] or ""),
                   by_key["tenant"]["known"])

    # (2) 모르는 것은 지어내지 않는다 - 모든 known 은 문자열이거나 None 이다
    bad = [c["key"] for c in d["checks"]
           if c["known"] is not None and not isinstance(c["known"], str)]
    check("known 은 문자열이거나 None 이다", bad, [])
    check("known_count 가 실제 채워진 수와 같다",
          d["known_count"], sum(1 for c in d["checks"] if c["known"]))

    # (3) ★ 개인정보가 실리지 않는다 - 임차인 실명이 응답에 들어가면 안 된다
    conn = sqlite3.connect(_qa_dbmod.DB_PATH)
    try:
        names = [n[0] for n in conn.execute(
            "SELECT DISTINCT tenant_name FROM tenant_rights"
            " WHERE item_id = ? AND tenant_name IS NOT NULL AND tenant_name <> ''",
            (item_id,)).fetchall()]
    finally:
        conn.close()
    blob = repr(d)
    leaked = sorted(n for n in names if n and n in blob)
    check("★ 임차인 실명이 응답에 실리지 않는다", leaked, [])

    # (4) 저장하지 않는다 - 원본을 바꾸면 다음 조회에 따라 바뀐다
    conn = sqlite3.connect(_qa_dbmod.DB_PATH)
    try:
        conn.execute("UPDATE rights_summary SET occupancy_status = ? WHERE item_id = ?",
                     ("QA-변경됨", item_id))
        conn.commit()
    finally:
        conn.close()
    again = body(client.get("/api/v1/field-visits/%d" % item_id,
                            headers=auth(USER_A)))["data"]
    now_occ = {c["key"]: c for c in again["checks"]}["occupancy"]["known"]
    check_true("★ 자료는 복사되지 않고 매번 현재 값을 본다",
               "QA-변경됨" in (now_occ or ""), now_occ)

    # (5) 판단을 붙이지 않는다 - 평가 어휘가 섞이지 않았는가
    verdicts = ("위험", "안전", "추천", "입찰하", "수익률", "점수")
    found = sorted(w for w in verdicts if w in blob)
    check("★ 자료에 판단·권고 어휘가 없다(자동 투자판단은 범위 밖)", found, [])


# ---------------------------------------------------------------------------
# 8. FIELD -> DECIDE -> 재확인 (2026-09-04)
# ---------------------------------------------------------------------------
def test_decision_is_visible_when_reopening_the_item():
    """물건을 **다시 열었을 때** 내 판단이 보이는가.

    ## 왜 이것이 없으면 판단이 사라지는가

    임장을 다녀와 "포기"로 정해 놓고 며칠 뒤 같은 물건을 다시 열면, 상세 화면에
    그 사실이 아무 데도 없었다(2026-09-04 전수 확인: 상세가 `field-visits` 를
    부르는 코드 0곳). 사용자는 **이미 끝낸 검토를 처음부터 다시 한다** —
    이 제품이 줄이겠다고 말한 시간을 정확히 되돌리는 셈이다.

    ## 무엇을 지키나

    (1) 내 판단이 상세 응답에 보인다
    (2) **남의 판단은 보이지 않는다**      — 개인화 필드다
    (3) 비로그인에는 null               — 공개 경로이므로 새면 안 된다
    (4) 요약만 싣는다                    — 메모·위험요소 본문은 여기 없다
    (5) 표가 없어도 상세는 200          — REVIEW 본체가 부가 정보로 죽으면 안 된다
    """
    print(chr(10) + "--- 8. 상세 재진입에서 판단이 보인다 ---")
    ids = two_item_ids()
    target = ids[0]

    # (1) 내 판단이 보인다 (앞 단계에서 이 물건은 DROP 으로 정해져 있다)
    r = client.get("/api/v1/item/%d" % target, headers=auth(USER_A))
    check("상세 200", r.status_code, 200)
    fv = body(r).get("field_visit")
    check_true("★ 상세 응답에 내 임장 요약이 실린다", fv is not None, fv)
    if fv:
        check("★ 판단이 그대로 보인다", fv["decision"], DECISION_DROP)
        check("임장 상태도 보인다", fv["status"], FIELD_STATUS_DONE)
        check_true("완료 시각이 보인다", bool(fv["completed_at"]), fv)
        check_true("확인 수가 숫자다", isinstance(fv["checked_count"], int), fv)

        # (4) 요약만 — 본문은 싣지 않는다
        leaked = sorted(k for k in ("memo", "risk_note") if k in fv)
        check("★ 메모·위험요소 본문은 상세에 싣지 않는다", leaked, [])

    # (2) 남의 판단은 보이지 않는다
    rb = client.get("/api/v1/item/%d" % target, headers=auth(USER_B))
    check("★ 남의 임장 요약은 보이지 않는다", body(rb).get("field_visit"), None)

    # (3) 비로그인에는 null
    ra = client.get("/api/v1/item/%d" % target)
    check("상세는 비로그인에도 200", ra.status_code, 200)
    check("★ 비로그인에는 임장 요약이 없다", body(ra).get("field_visit"), None)

    # (5) 표가 없는 환경에서도 상세는 살아 있다
    conn = sqlite3.connect(_qa_dbmod.DB_PATH)
    try:
        conn.execute("ALTER TABLE field_visits RENAME TO field_visits__qa_hidden")
        conn.commit()
    finally:
        conn.close()
    try:
        r2 = client.get("/api/v1/item/%d" % target, headers=auth(USER_A))
        check("★ 임장 표가 없어도 상세는 200", r2.status_code, 200)
        check("그때 임장 요약은 null", body(r2).get("field_visit"), None)
    finally:
        conn = sqlite3.connect(_qa_dbmod.DB_PATH)
        try:
            conn.execute("ALTER TABLE field_visits__qa_hidden RENAME TO field_visits")
            conn.commit()
        finally:
            conn.close()

    # (6) ★ **부분적으로만** 준비된 스키마에서도 상세는 살아 있다 (2026-09-04).
    #
    #   위 (5) 는 `field_visits` 자체가 없는 경우다. 그때는 `has_table` 검사가
    #   막아 주므로 쿼리가 아예 나가지 않는다 — 즉 그 경로는 `try/except` 를
    #   **지나가지 않는다.** 변이 검증(D5b)에서 `except sqlite3.Error` 를
    #   `except ZeroDivisionError` 로 바꿔도 검사가 전부 통과했다: 방어가 두 겹인데
    #   **한 겹만 검사에 묶여 있었다.**
    #
    #   여기서 두 번째 겹을 고정한다 — `field_visits` 는 있는데 곁 테이블
    #   (`field_visit_checks`)이 없는 상태다. 손으로 표를 만든 환경이나, 앞으로
    #   이 코드가 읽을 표가 늘었을 때 실제로 생길 수 있는 모양이다.
    conn = sqlite3.connect(_qa_dbmod.DB_PATH)
    try:
        conn.execute("ALTER TABLE field_visit_checks RENAME TO field_visit_checks__qa_hidden")
        conn.commit()
    finally:
        conn.close()
    try:
        r3 = client.get("/api/v1/item/%d" % target, headers=auth(USER_A))
        check("★ 곁 테이블이 없어도 상세는 200(두 번째 방어층)", r3.status_code, 200)
        check("그때도 임장 요약은 null", body(r3).get("field_visit"), None)
    finally:
        conn = sqlite3.connect(_qa_dbmod.DB_PATH)
        try:
            conn.execute("ALTER TABLE field_visit_checks__qa_hidden RENAME TO field_visit_checks")
            conn.commit()
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# 9. T2D 시작점이 20건 상한에 지워지지 않는다 (2026-09-04)
# ---------------------------------------------------------------------------
def test_visited_items_survive_the_recent_cap():
    """임장을 다녀온 물건의 **처음 본 시각**이 정리에 살아남는가.

    ## 무엇이 문제였나

    `recent_items` 는 사용자당 `RECENT_ITEMS_DISPLAY_LIMIT`(20)건만 남기고 나머지를
    지운다. 저장 공간을 묶는 장치이고, **표시 쿼리에 자체 LIMIT 이 있어** 화면과는
    무관하다.

    그런데 2026-09-04 에 `first_viewed_at`(migration 031)이 이 표에 붙었다.
    그 값은 Time-to-Decision 의 **시작점**이다. 행이 지워지면 열이 있어도 소용없고,
    물건을 많이 보는 사용자일수록 먼저 지워진다 — 즉 T2D 가 **가벼운 사용자 쪽으로
    치우쳐** 측정된다. 그리고 하필 지워지는 것이 사용자가 **오래 붙들고 판단한**
    물건이다.

    ## 무엇을 지키나

    (1) 임장을 다녀온 물건은 21건째 이후에도 남는다
    (2) 다녀오지 않은 물건은 예전처럼 정리된다 (저장 상한이 무력화되지 않았다)
    (3) 화면에 보이는 개수는 그대로 20건이다 (정책은 바뀌지 않았다)
    """
    print(chr(10) + "--- 9. 임장한 물건의 T2D 시작점이 상한에 지워지지 않는다 ---")
    from api.v1.recent_items import RECENT_ITEMS_DISPLAY_LIMIT, record_view

    user = "qa-cap-" + uuid.uuid4().hex[:8]
    conn = sqlite3.connect(_qa_dbmod.DB_PATH)
    try:
        # 031 이 없는 환경이면 first_viewed_at 자체가 없다 - 조용히 통과시키지 않는다.
        has_first = conn.execute(
            "SELECT 1 FROM pragma_table_info('recent_items')"
            " WHERE name='first_viewed_at'").fetchone() is not None
        ids = [r[0] for r in conn.execute(
            "SELECT id FROM auction_item ORDER BY id LIMIT ?",
            (RECENT_ITEMS_DISPLAY_LIMIT + 5,)).fetchall()]
    finally:
        conn.close()
    if not has_first:
        print("   [판정 안 함] migration 031 미적용 - 통과가 아니다")
        return
    check_true("전제: 상한보다 많은 물건이 있다",
               len(ids) > RECENT_ITEMS_DISPLAY_LIMIT, len(ids))

    # ── ★ T2D 의 핵심 불변식: 다시 봐도 "처음 본 시각"은 밀리지 않는다 ────────
    #
    #   `viewed_at` 은 재조회마다 덮어쓰는 것이 맞다(최근 본 물건 정렬의 의미다).
    #   `first_viewed_at` 은 반대여야 한다 — 밀리면 오래 고민한 물건일수록 T2D 가
    #   **짧게** 나와 지표가 정반대로 틀린다. 변이 검증(R4)에서 이 불변식이 아무
    #   검사에도 묶여 있지 않은 것이 드러나 여기서 붙든다.
    probe_user = "qa-first-" + uuid.uuid4().hex[:8]
    probe_item = ids[-1]
    _c = _qa_dbmod.get_connection()
    try:
        record_view(_c, probe_user, probe_item)
    finally:
        _c.close()
    conn = sqlite3.connect(_qa_dbmod.DB_PATH)
    try:
        first_1, viewed_1 = conn.execute(
            "SELECT first_viewed_at, viewed_at FROM recent_items"
            " WHERE user_id=? AND item_id=?", (probe_user, probe_item)).fetchone()
    finally:
        conn.close()
    time.sleep(0.01)          # 두 시각이 실제로 달라지도록
    _c = _qa_dbmod.get_connection()
    try:
        record_view(_c, probe_user, probe_item)
    finally:
        _c.close()
    conn = sqlite3.connect(_qa_dbmod.DB_PATH)
    try:
        first_2, viewed_2 = conn.execute(
            "SELECT first_viewed_at, viewed_at FROM recent_items"
            " WHERE user_id=? AND item_id=?", (probe_user, probe_item)).fetchone()
    finally:
        conn.close()
    check("★ 다시 봐도 처음 본 시각은 그대로다(T2D 시작점)", first_2, first_1)
    check_true("전제: 두 번째 조회가 실제로 기록됐다(검사가 공허하지 않다)",
               viewed_2 != viewed_1, (viewed_1, viewed_2))

    visited = ids[0]          # 이 물건만 임장을 다녀온다
    # 임장 기록을 먼저 만든다(다녀왔다는 사실이 정리 시점에 이미 있어야 한다).
    _qa_conn = _qa_dbmod.get_connection()
    try:
        record_view(_qa_conn, user, visited)
    finally:
        _qa_conn.close()
    client.post("/api/v1/field-visits", json={"item_id": visited}, headers=auth(user))

    # 그 뒤로 상한을 넘도록 다른 물건을 본다.
    _qa_conn = _qa_dbmod.get_connection()
    try:
        for iid in ids[1:]:
            record_view(_qa_conn, user, iid)
    finally:
        _qa_conn.close()

    conn = sqlite3.connect(_qa_dbmod.DB_PATH)
    try:
        kept = conn.execute(
            "SELECT first_viewed_at FROM recent_items WHERE user_id=? AND item_id=?",
            (user, visited)).fetchone()
        total = conn.execute(
            "SELECT COUNT(*) FROM recent_items WHERE user_id=?", (user,)).fetchone()[0]
        # 다녀오지 않은 물건 중 가장 오래된 것은 지워졌는가
        unvisited_old = conn.execute(
            "SELECT COUNT(*) FROM recent_items WHERE user_id=? AND item_id=?",
            (user, ids[1])).fetchone()[0]
    finally:
        conn.close()

    check_true("★ 임장한 물건의 행이 남아 있다", kept is not None, kept)
    if kept:
        check_true("★ 그 행의 first_viewed_at 이 살아 있다(T2D 시작점)",
                   bool(kept[0]), kept[0])
    check("★ 다녀오지 않은 가장 오래된 물건은 정리된다(상한이 살아 있다)",
          unvisited_old, 0)
    check_true("저장 행 수가 상한 + 임장분 만큼이다(무한정 늘지 않는다)",
               total <= RECENT_ITEMS_DISPLAY_LIMIT + 1, total)

    # 화면에 보이는 개수는 그대로다 - 정책이 바뀌지 않았다.
    shown = body(client.get("/api/v1/recent-items", headers=auth(user))).get("data") or []
    check_true("★ 화면에 보이는 개수는 여전히 상한 이하다",
               len(shown) <= RECENT_ITEMS_DISPLAY_LIMIT, len(shown))


def test_visit_says_which_property_it_is():
    """임장 응답이 **어느 물건인지** 말하는가 (2026-09-05 신설).

    ## 왜

    임장 화면은 제목이 "임장 기록" 하나였고 물건을 가리키는 말이 **한 군데도 없었다.**
    현장에서는 하루에 여러 건을 돈다. 그 화면만 보고는 지금 어느 물건에 적고 있는지
    알 수 없어, 확인하려면 상세로 나갔다 돌아와야 했다 — 이 제품이 줄이겠다고 말한
    바로 그 왕복이다. 더 나쁜 쪽은 조용한 경우다: **엉뚱한 물건에 기록해도 화면이
    아무 말을 하지 않는다.**

    ## 무엇을 고정하나

        1. 응답에 `item` 식별 블록이 있다
        2. 그 값이 **DB 의 그 물건**과 같다 (지어내지 않는다)
        3. 물건마다 다르다 (한 물건 것을 다른 물건에 붙이지 않는다)
        4. 모든 진입점이 같은 모양을 준다 (`_serialize` 한 벌)
    """
    print(chr(10) + "--- 10. 응답이 어느 물건인지 말한다 ---")
    IDENT_KEYS = ["case_no", "court_name", "full_address", "item_no"]

    ids = two_item_ids()
    check_true("전제: 물건이 둘 이상 있다", len(ids) >= 2, ids)
    if len(ids) < 2:
        return
    a, b = ids[0], ids[1]
    for item_id in (a, b):
        client.post("/api/v1/field-visits", json={"item_id": item_id}, headers=auth(USER_A))

    r = client.get("/api/v1/field-visits/%d" % a, headers=auth(USER_A))
    check("조회가 200 이다", r.status_code, 200)
    body = r.json()["data"]
    check_true("★ 응답에 item 식별 블록이 있다", "item" in body, sorted(body))
    if "item" not in body:
        return
    check("★ 식별 블록의 키가 계약대로다", sorted(body["item"]), IDENT_KEYS)

    # DB 와 대조한다 - 값을 지어내지 않는지 보는 유일한 방법이다.
    conn = sqlite3.connect(_qa_dbmod.DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT case_no, item_no, court_name, full_address FROM auction_item WHERE id=?",
        (a,)).fetchone()
    conn.close()
    for k in IDENT_KEYS:
        check("★ %s 가 DB 와 같다" % k, body["item"][k], row[k])

    # 공허하지 않은가 - 전부 None 이면 위 대조가 통과해도 의미가 없다.
    check_true("검사가 공허하지 않다 - 식별 값이 하나 이상 실제로 있다",
               any(body["item"][k] is not None for k in IDENT_KEYS), body["item"])

    other = client.get("/api/v1/field-visits/%d" % b, headers=auth(USER_A)).json()["data"]
    check_true("★ 물건이 다르면 식별도 다르다",
               other["item"] != body["item"] or other["item_id"] != body["item_id"],
               (body["item"], other["item"]))

    # 모든 진입점이 같은 모양인가 - `_serialize` 한 벌이라는 주장을 실제로 확인한다.
    same = client.post("/api/v1/field-visits", json={"item_id": a},
                       headers=auth(USER_A)).json()["data"]
    check("★ 시작 응답도 같은 식별을 준다", same.get("item"), body["item"])
    saved = client.put("/api/v1/field-visits/%d/notes" % a, json={"memo": "식별 확인"},
                       headers=auth(USER_A)).json()["data"]
    check("★ 저장 응답도 같은 식별을 준다", saved.get("item"), body["item"])


if __name__ == "__main__":
    try:
        test_unavailable_before_migration()
        test_requires_auth()
        test_full_flow()
        test_isolation()
        test_bad_input()
        test_vocabulary_contract()
        test_complete_with_decision()
        test_review_prefills_the_checklist()
        test_decision_is_visible_when_reopening_the_item()
        test_visited_items_survive_the_recent_cap()
        test_visit_says_which_property_it_is()
    finally:
        shutil.rmtree(_qa_tmp, ignore_errors=True)
    print("")
    if failures:
        print(_out("FAILED (%d): %s" % (len(failures), ", ".join(failures))))
        sys.exit(1)
    print("ALL FIELD VISIT TESTS PASSED")
    sys.exit(0)
