"""물건 상세 API의 **로그인 사용자 경로** 회귀 — 2026-08-17 Sprint 146 신설.

## 왜 이 파일이 생겼나

커버리지를 모듈별로 실측하니 `api/v1/item.py`가 80%였고, 빠진 13줄이
**한 덩어리(76~98행)** 였다 — 전부 로그인 사용자 경로다:

```python
if credentials:
    payload = decode_supabase_jwt(...)      # 토큰 해석
    user_id = payload.get("sub")
    if user_id:
        try:
            record_view(conn, user_id, item_id)     # 최근조회 기록
        except Exception:
            logger.warning(...)                     # ← 실패해도 상세는 계속돼야 한다
is_favorited = ... SELECT 1 FROM favorites ...      # 즐겨찾기 여부
```

즉 **비로그인 상세 조회만 검증되고 있었다.** 로그인 사용자에게만 보이는 것
(최근조회 자동 기록, 하트 채워짐)과, 그 기록이 실패했을 때 상세가 여전히 떠야 한다는
계약이 한 번도 실행되지 않았다.

`test_auth_jwt.py`가 `is_favorited`를 검증하지만 그건 **검색** 응답이다
(`ES256 로그인 시 결과에 is_favorited 필드가 채워진다`). 상세는 코드가 따로다.

## 왜 이 계약이 중요한가

`record_view()`는 `INSERT ... ON CONFLICT ... DO UPDATE` + `commit()`이다. 쓰기가
실패할 수 있는 경로(락, 디스크, 제약)가 실재하는데, 그때 **상세 페이지 전체가 500이
되면 안 된다.** 코드는 이미 그렇게 방어하고 있지만 검사가 없어서, 누가 `try`를 걷어내도
아무도 모른다. 이 저장소가 반복해 겪은 "조용한 실패"의 반대편 —
**"부수 기능 실패가 주 기능을 죽이는" 실패** 다.

## 운영 데이터를 건드리지 않는다

`test_asset_pipeline.Env`(임시 DB + 임시 문서 루트, 스키마는 실제 부트스트랩 절차)를
재사용한다. 토큰은 `test_auth_jwt.py`와 같은 방식으로 **합성 시크릿**으로 만든다 —
실제 credential은 쓰지도 출력하지도 않는다.

    python test_item_detail_auth.py
"""
import contextlib
import io
import os
import secrets
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# api.auth는 import 시점에 SUPABASE_JWT_SECRET을 읽는다. 없는 환경에서도 HS256 경로를
# 실행할 수 있도록 합성 값을 넣는다(test_auth_jwt.py와 같은 방식).
if not os.getenv("SUPABASE_JWT_SECRET"):
    os.environ["SUPABASE_JWT_SECRET"] = "qa-itemauth-" + secrets.token_hex(16)

failures = []


def check(name, actual, expected):
    ok = actual == expected
    print("[%s] %s: %r (expected %r)" % ("PASS" if ok else "FAIL", name, actual, expected))
    if not ok:
        failures.append(name)


def check_true(name, cond, detail=""):
    print("[%s] %s%s" % ("PASS" if cond else "FAIL", name, ("" if cond else " -- " + str(detail))))
    if not cond:
        failures.append(name)


USER = "user-under-test"


def _token(sub=USER):
    from jose import jwt
    import api.auth as auth_mod
    return jwt.encode({"sub": sub}, auth_mod.SUPABASE_JWT_SECRET, algorithm="HS256")


def _env_with_item(item_id=1):
    """임시 DB에 물건 1건을 심고 (env, client)를 돌려준다."""
    import test_asset_pipeline as tap
    from fastapi.testclient import TestClient
    import api_server

    env = tap.Env()
    env.seed_item(item_id=item_id)
    with contextlib.redirect_stderr(io.StringIO()):
        client = TestClient(api_server.app)
    return env, client


def _auth(token):
    return {"Authorization": "Bearer " + token}


# ---------------------------------------------------------------------------
# 1. 비로그인 — 기존 동작(대조군)
# ---------------------------------------------------------------------------
def test_anonymous():
    print("\n--- 1. 비로그인 상세 조회 ---")
    env, client = _env_with_item()
    try:
        r = client.get("/api/v1/item/1")
        check("200", r.status_code, 200)
        check("is_favorited는 False", r.json()["is_favorited"], False)

        conn = env.conn()
        try:
            n = conn.execute("SELECT COUNT(*) FROM recent_items").fetchone()[0]
        finally:
            conn.close()
        check("최근조회를 기록하지 않는다", n, 0)
    finally:
        env.close()


# ---------------------------------------------------------------------------
# 2. ★ 로그인 — 최근조회가 실제로 기록된다
# ---------------------------------------------------------------------------
def test_logged_in_records_view():
    print("\n--- 2. 로그인 시 최근조회 기록 ---")
    env, client = _env_with_item()
    try:
        r = client.get("/api/v1/item/1", headers=_auth(_token()))
        check("200", r.status_code, 200)

        conn = env.conn()
        try:
            rows = conn.execute(
                "SELECT user_id, item_id FROM recent_items").fetchall()
        finally:
            conn.close()
        check("★ recent_items에 1행", len(rows), 1)
        if rows:
            check("user_id가 토큰의 sub", rows[0]["user_id"], USER)
            check("item_id", rows[0]["item_id"], 1)

        # 같은 물건을 다시 봐도 행이 늘지 않는다(ON CONFLICT DO UPDATE).
        client.get("/api/v1/item/1", headers=_auth(_token()))
        conn = env.conn()
        try:
            n = conn.execute("SELECT COUNT(*) FROM recent_items").fetchone()[0]
        finally:
            conn.close()
        check("재조회해도 중복 행이 생기지 않는다", n, 1)
    finally:
        env.close()


# ---------------------------------------------------------------------------
# 3. is_favorited 반영
# ---------------------------------------------------------------------------
def test_is_favorited():
    print("\n--- 3. 즐겨찾기 여부 ---")
    env, client = _env_with_item()
    try:
        check("찜 전에는 False",
              client.get("/api/v1/item/1", headers=_auth(_token())).json()["is_favorited"],
              False)

        conn = env.conn()
        try:
            # created_at은 NOT NULL이다 — 스키마를 손으로 베끼지 않고 실제 제약을 따른다.
            conn.execute(
                "INSERT INTO favorites (user_id, item_id, created_at) VALUES (?,?,?)",
                (USER, 1, "2026-08-17T00:00:00"))
            conn.commit()
        finally:
            conn.close()

        check("★ 찜 후에는 True",
              client.get("/api/v1/item/1", headers=_auth(_token())).json()["is_favorited"],
              True)
        # 다른 사용자에게는 보이지 않아야 한다(사용자 격리).
        check("★ 다른 사용자에게는 False",
              client.get("/api/v1/item/1", headers=_auth(_token("other-user"))).json()["is_favorited"],
              False)
    finally:
        env.close()


# ---------------------------------------------------------------------------
# 4. 잘못된 토큰 — 비로그인으로 강등(상세 자체는 막지 않는다)
# ---------------------------------------------------------------------------
def test_bad_token_degrades():
    print("\n--- 4. 잘못된 토큰은 비로그인으로 강등 ---")
    env, client = _env_with_item()
    try:
        for label, tok in (("깨진 문자열", "not-a-jwt"),
                           ("다른 시크릿 서명", None),
                           ("빈 값", "")):
            if tok is None:
                from jose import jwt
                tok = jwt.encode({"sub": USER}, "attacker-secret", algorithm="HS256")
            r = client.get("/api/v1/item/1", headers=_auth(tok))
            check("%s -> 200" % label, r.status_code, 200)
            check("%s -> is_favorited False" % label, r.json()["is_favorited"], False)

        conn = env.conn()
        try:
            n = conn.execute("SELECT COUNT(*) FROM recent_items").fetchone()[0]
        finally:
            conn.close()
        check("위조 토큰으로는 최근조회가 기록되지 않는다", n, 0)
    finally:
        env.close()


# ---------------------------------------------------------------------------
# 5. ★★ 최근조회 기록이 실패해도 상세는 뜬다 (부수 기능이 주 기능을 죽이지 않는다)
# ---------------------------------------------------------------------------
def test_record_view_failure_does_not_break_detail():
    print("\n--- 5. record_view 실패해도 상세 200 ---")
    import api.v1.item as itemmod
    env, client = _env_with_item()
    original = itemmod.record_view
    try:
        def boom(conn, user_id, item_id):
            raise RuntimeError("의도적 실패: DB 잠김 등")
        itemmod.record_view = boom

        # TestClient는 서버 예외를 **그대로 다시 던진다**(raise_server_exceptions 기본 True).
        # 보호가 사라지면 여기서 예외가 나는데, 그대로 두면 테스트가 트레이스백으로 죽어
        # "무엇이 깨졌는지"가 [FAIL] 한 줄로 보이지 않는다. 잡아서 실패로 보고한다.
        r = None
        raised = None
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                r = client.get("/api/v1/item/1", headers=_auth(_token()))
        except Exception as exc:  # noqa: BLE001 - 계약 검증이 목적
            raised = "%s: %s" % (type(exc).__name__, str(exc)[:80])

        check_true("★ record_view 예외가 상세 조회로 새어 나오지 않는다",
                   raised is None, raised)
        if r is None:
            return
        check("★ 상세는 여전히 200", r.status_code, 200)
        check_true("★ 본문이 정상 물건이다", r.json().get("id") == 1, r.json())
        # 기록만 포기했을 뿐 로그인 자체는 유지돼야 한다(is_favorited 계산은 계속된다).
        check_true("is_favorited 필드가 여전히 있다", "is_favorited" in r.json())
    finally:
        itemmod.record_view = original
        env.close()


# ---------------------------------------------------------------------------
# 6. 배선 고정 — try/except가 사라지면 5번이 무의미해진다
# ---------------------------------------------------------------------------
def test_record_view_is_guarded_in_source():
    print("\n--- 6. record_view 호출이 try로 감싸져 있다 ---")
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "api", "v1", "item.py"), encoding="utf-8-sig").read()
    i = src.find("record_view(")
    check_true("record_view 호출이 존재한다", i > 0)
    if i > 0:
        before = src[:i]
        # 호출 직전 200자 안에 try:가 있어야 한다(들여쓰기된 보호 블록).
        check_true("★ 호출 앞에 try가 있다", "try:" in before[-200:], before[-200:])
        after = src[i:i + 400]
        check_true("★ 뒤에 except가 있다", "except" in after, after[:120])


if __name__ == "__main__":
    test_anonymous()
    test_logged_in_records_view()
    test_is_favorited()
    test_bad_token_degrades()
    test_record_view_failure_does_not_break_detail()
    test_record_view_is_guarded_in_source()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        sys.exit(1)
    print("ALL ITEM DETAIL AUTH TESTS PASSED")
