"""Admin 쓰기 경로에 실패를 주입한다 — 2026-08-17 Sprint 158 신설.

## 왜 이 파일이 생겼나

커버리지를 제대로(경합 테스트까지 포함해) 재니 `api/v1/admin.py`가 96%였고,
남은 것이 **전부 같은 모양**이었다.

```
api\v1\admin.py   396 stmts   16 miss   96%
   412-414   registry 상태 전이   except Exception: conn.rollback(); raise
   546-548   등기부 무료횟수 조정  〃
   876-878   webhook 재처리       〃
   945-947   결제 환불            〃
```

정상 경로와 경합(409)은 `test_race_conditions.py`가 이미 덮고 있다. **덮이지 않은
것은 "작업 도중 예상 못 한 오류가 났을 때"** 뿐이다. 그리고 이 네 곳은 전부
**돈이나 권한이 걸린 조작**이다 — 등기부 무료횟수, 결제 환불, 결제 상태를 바꾸는
webhook 재처리, 신청 상태 전이.

여기서 롤백이 빠지면 생기는 것이 이 저장소가 반복해 겪은 실패다:
**"절반만 적용된 상태"** — 환불은 기록됐는데 감사 로그가 없거나, 상태만 바뀌고
정산이 안 된 행. 그래서 정상 동작이 아니라 **실패했을 때**를 검증한다.

## 무엇을 단언하나

각 경로마다 두 가지다.

1. **예외를 삼키지 않는다** — 5xx로 올라온다. 조용히 200을 주면 운영자는 성공한 줄 안다.
2. **부분 상태가 남지 않는다** — 주입된 함수가 **쓰기를 하고 나서** 터지게 만든 뒤,
   그 쓰기가 되돌려졌는지 DB에서 직접 확인한다.

2번이 핵심이다. 아무것도 쓰지 않고 터지는 주입은 "롤백했다"를 증명하지 못한다
(원래 바뀐 게 없으니 통과해 버린다). 그래서 **일부러 UPDATE를 먼저 시키고** 터뜨린다.

## ★ 정직하게: 이 검사는 `conn.rollback()` 호출 자체를 고정하지 못한다

만들고 나서 mutation 으로 확인했더니 **네 곳의 `conn.rollback()` 을 하나씩 지워도
검사가 전부 통과했다**(4/4 생존). 원인을 실증했다.

```
네 블록 뒤에는 전부  finally: conn.close()  가 있다.
그리고 SQLite 는 커밋하지 않은 트랜잭션을 close 시점에 버린다.

  실증:  UPDATE 후 rollback 없이 close  ->  다시 열어 보면 값이 원래대로('A')
```

즉 저 `conn.rollback()` 들은 **관측 가능한 동작을 바꾸지 않는 방어 코드**다
(equivalent mutant). 어떤 행위 기반 검사로도 죽일 수 없다.

그래서 두 가지로 나눴다.

* 1~5번(행위) — **부분 상태가 남지 않는다**는 실제 계약을 검증한다. 이 계약은
  참이고, `rollback` 이 아니라 "커밋되지 않았다"는 더 튼튼한 이유로 성립한다.
* 6번(구조) — `rollback()` 호출이 소스에 남아 있는지 본다. 행위로 못 잡으니
  구조로 고정한다. 커넥션을 풀링하거나 `close` 관례가 바뀌면 그때는 **진짜로**
  필요해지는 코드라서, 지금 조용히 사라지면 안 된다.

구조 검사를 "행위 검사인 척" 적지 않기 위해 이 문단을 남긴다.

## 운영 DB를 건드리지 않는다

`auction.db` 사본을 임시 디렉터리에 두고 `storage.database.DB_PATH`를 돌린 뒤,
필요한 행을 직접 심는다. Admin 키는 합성값이다.

    python test_admin_failure_injection.py
"""
import contextlib
import io
import os
import secrets
import shutil
import sys
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_KEY = "qa-fi-" + secrets.token_hex(16)
os.environ["ADMIN_API_KEY"] = _KEY
os.environ["SUPER_ADMIN_API_KEY"] = _KEY
if not os.getenv("SUPABASE_JWT_SECRET"):
    os.environ["SUPABASE_JWT_SECRET"] = "qa-fi-" + secrets.token_hex(16)

HEADERS = {"X-Admin-Key": _KEY}
NOW = datetime.now().isoformat()

failures = []
_tmpdir = None


def check(name, actual, expected):
    ok = actual == expected
    print("[%s] %s: %r (expected %r)" % ("PASS" if ok else "FAIL", name, actual, expected))
    if not ok:
        failures.append(name)


def check_true(name, cond, detail=""):
    print("[%s] %s%s" % ("PASS" if cond else "FAIL", name, ("" if cond else " -- " + str(detail))))
    if not cond:
        failures.append(name)


def _setup():
    global _tmpdir
    import storage.database as dbmod
    _tmpdir = tempfile.mkdtemp(prefix="qa_fi_")
    tmpdb = os.path.join(_tmpdir, "scratch.db")
    # 온라인 백업 스냅샷 - 워커가 쓰는 중이어도 일관된 사본을 만든다
    # (shutil.copy2 는 찢어질 수 있다. 사유: storage/database.py:snapshot_live_db)
    dbmod.snapshot_live_db(tmpdb)
    dbmod.DB_PATH = tmpdb


def _conn():
    import storage.database as dbmod
    return dbmod.get_connection()


def _client():
    import api_server
    from fastapi.testclient import TestClient
    with contextlib.redirect_stderr(io.StringIO()):
        # raise_server_exceptions=False 라야 "500으로 올라온다"를 응답으로 관찰할 수 있다.
        return TestClient(api_server.app, raise_server_exceptions=False)


def _seed_payment(status="SUCCESS", amount=12900):
    conn = _conn()
    try:
        pid = conn.execute(
            "INSERT INTO payments (user_id, payment_type, amount, status, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?)",
            ("qa-fi-user", "SUBSCRIPTION", amount, status, NOW, NOW),
        ).lastrowid
        conn.commit()
        return pid
    finally:
        conn.close()


def _seed_registry_request(status="PROCESSING"):
    conn = _conn()
    try:
        rid = conn.execute(
            "INSERT INTO registry_requests (user_id, item_id, status, requested_at)"
            " VALUES (?,?,?,?)",
            ("qa-fi-user", 1, status, NOW),
        ).lastrowid
        conn.commit()
        return rid
    finally:
        conn.close()


def _seed_webhook():
    conn = _conn()
    try:
        wid = conn.execute(
            "INSERT INTO payment_webhooks (provider, processing_status, signature_verified,"
            " raw_payload, received_at) VALUES (?,?,?,?,?)",
            ("mock", "RECEIVED", 1, "{}", NOW),
        ).lastrowid
        conn.commit()
        return wid
    finally:
        conn.close()


def _seed_subscription(status="ACTIVE"):
    conn = _conn()
    try:
        sid = conn.execute(
            "INSERT INTO subscriptions (user_id, plan, price, status, started_at, expires_at,"
            " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            ("qa-fi-user", "BASIC", 12900, status, NOW,
             (datetime.now() + timedelta(days=30)).isoformat(), NOW, NOW),
        ).lastrowid
        conn.commit()
        return sid
    finally:
        conn.close()


class FailAfterWrite:
    """지정한 SQL을 **실행한 뒤** 터지는 커넥션 래퍼.

    핵심은 "실행한 뒤"다. 아무것도 쓰지 않고 터지는 주입은 롤백을 증명하지 못한다 —
    되돌릴 것이 없으니 무조건 통과한다. 실제 UPDATE를 성사시킨 다음 예외를 내야
    `conn.rollback()`이 그 UPDATE를 지웠는지 확인할 수 있다.

    DB 계층 오류(잠금·디스크·제약)를 흉내 내는 방식이라 프로덕션 코드를 고치지 않고도
    `except Exception: conn.rollback(); raise` 분기를 결정적으로 태울 수 있다.
    """

    def __init__(self, real, fail_marker):
        self._real = real
        self._marker = fail_marker

    def execute(self, sql, *args, **kwargs):
        cursor = self._real.execute(sql, *args, **kwargs)
        if self._marker in " ".join(sql.split()):
            raise RuntimeError("주입된 DB 오류")
        return cursor

    def __getattr__(self, name):
        return getattr(self._real, name)


def _status_of(table, row_id, col="status"):
    conn = _conn()
    try:
        row = conn.execute("SELECT %s FROM %s WHERE id=?" % (col, table), (row_id,)).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 1. ★★ 환불 도중 실패 — 부분 환불 상태가 남으면 안 된다
# ---------------------------------------------------------------------------
def test_refund_failure_rolls_back():
    print("\n--- 1. 환불 도중 실패 -> 롤백 ---")
    import api.v1.payments as pay
    client = _client()
    pid = _seed_payment(status="SUCCESS")
    before = _status_of("payments", pid)
    check("사전 조건: 결제가 SUCCESS", before, "SUCCESS")

    original = pay.refund_payment

    def boom(conn, payment_id, amount, reason, actor, user_id=None):
        # ★ 먼저 **쓰기를 하고** 터진다 — 롤백이 실제로 되돌리는지 보기 위해서다.
        conn.execute("UPDATE payments SET status='REFUNDED' WHERE id=?", (payment_id,))
        raise RuntimeError("주입된 실패: 환불 처리 중 예상 못 한 오류")

    pay.refund_payment = boom
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            r = client.post("/api/v1/admin/payments/%d/refund" % pid,
                            headers=HEADERS, json={"reason": "주입 테스트"})
    finally:
        pay.refund_payment = original

    check_true("★ 예외를 삼키지 않는다(5xx)", r.status_code >= 500, r.status_code)
    check("★★ 결제 상태가 되돌려졌다(부분 환불 없음)", _status_of("payments", pid), "SUCCESS")


# ---------------------------------------------------------------------------
# 2. ★ 신청 상태 전이 도중 실패
# ---------------------------------------------------------------------------
def test_registry_status_failure_rolls_back():
    print("\n--- 2. 신청 상태 전이 도중 실패 -> 롤백 ---")
    import api.v1.admin as adm
    client = _client()
    rid = _seed_registry_request(status="PROCESSING")
    check("사전 조건: PROCESSING", _status_of("registry_requests", rid), "PROCESSING")

    # UPDATE 를 **성사시킨 뒤** 터뜨린다 — 롤백이 그 쓰기를 지우는지 보기 위해서다.
    original = adm.get_connection
    adm.get_connection = lambda: FailAfterWrite(original(), "UPDATE registry_requests SET status")
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            r = client.patch("/api/v1/admin/registry-requests/%d" % rid,
                             headers=HEADERS, json={"status": "FAILED", "reason": "주입"})
    finally:
        adm.get_connection = original

    check_true("★ 5xx 로 올라온다", r.status_code >= 500, r.status_code)
    check("★★ 상태가 바뀌지 않았다(부분 전이 없음)",
          _status_of("registry_requests", rid), "PROCESSING")


# ---------------------------------------------------------------------------
# 3. ★ webhook 재처리 도중 실패 — 결제 상태가 어정쩡하게 바뀌면 안 된다
# ---------------------------------------------------------------------------
def test_webhook_reprocess_failure_rolls_back():
    print("\n--- 3. webhook 재처리 도중 실패 -> 롤백 ---")
    import api.v1.payments as pay
    client = _client()
    wid = _seed_webhook()
    check("사전 조건: RECEIVED", _status_of("payment_webhooks", wid, "processing_status"), "RECEIVED")

    original = pay.reprocess_webhook

    def boom(conn, webhook_id):
        conn.execute("UPDATE payment_webhooks SET processing_status='PROCESSED' WHERE id=?",
                     (webhook_id,))
        raise RuntimeError("주입된 실패: 재처리 중 오류")

    pay.reprocess_webhook = boom
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            r = client.post("/api/v1/admin/payments/webhooks/%d/reprocess" % wid, headers=HEADERS)
    finally:
        pay.reprocess_webhook = original

    check_true("★ 5xx 로 올라온다", r.status_code >= 500, r.status_code)
    check("★★ webhook 상태가 되돌려졌다",
          _status_of("payment_webhooks", wid, "processing_status"), "RECEIVED")


# ---------------------------------------------------------------------------
# 4. ★ 구독 상태 변경의 409 — 다른 요청이 먼저 바꿨을 때
#
# 경합을 스레드로 재현하지 않고 `change_status`가 던지는 예외를 직접 주입해
# **결정적으로** 409 분기를 태운다(`test_race_conditions.py` §9는 실제 경합 쪽을 본다).
# ---------------------------------------------------------------------------
def test_subscription_concurrent_change_returns_409():
    print("\n--- 4. 구독 동시 변경 -> 409 ---")
    import api.v1.subscriptions as subs
    client = _client()
    sid = _seed_subscription(status="ACTIVE")

    original = subs.change_status

    def boom(*a, **kw):
        raise subs.ConcurrentStatusChange("다른 요청이 먼저 구독 상태를 바꿨습니다")

    subs.change_status = boom
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            r = client.patch("/api/v1/admin/subscriptions/%d" % sid,
                             headers=HEADERS, json={"status": "CANCELLED"})
    finally:
        subs.change_status = original

    check("★ 409 로 응답한다(500 아님)", r.status_code, 409)
    check("★ 상태가 바뀌지 않았다", _status_of("subscriptions", sid), "ACTIVE")
    check_true("사유가 담긴다", "먼저" in r.text, r.text[:120])


# ---------------------------------------------------------------------------
# 4-B. ★ 등기부 무료횟수 조정 도중 실패
#
# 네 번째 경로. 나머지 셋과 형태가 같지만 **다른 테이블·다른 의미**다 —
# 무료 횟수는 과금에 직접 영향을 주고(그래서 SUPER_ADMIN 전용), 조정 기록이 절반만
# 남으면 "누가 왜 바꿨는지 모르는 크레딧"이 된다. 소스 주석도 그 위험을 명시한다.
# ---------------------------------------------------------------------------
def test_registry_credit_failure_rolls_back():
    print("\n--- 4-B. 무료횟수 조정 도중 실패 -> 롤백 ---")
    import api.v1.registry_credits as rc
    client = _client()
    user = "qa-fi-credit-user"

    def _credit_rows():
        conn = _conn()
        try:
            return conn.execute(
                "SELECT COUNT(*) FROM registry_credits WHERE user_id=?", (user,)
            ).fetchone()[0]
        finally:
            conn.close()

    check("사전 조건: 크레딧 기록 0건", _credit_rows(), 0)

    original = rc.add_credit

    def boom(conn, user_id, reason_type, amount, reason, created_by=None):
        # 먼저 실제로 INSERT 한 뒤 터진다 — 롤백이 그 행을 지우는지 본다.
        conn.execute(
            "INSERT INTO registry_credits (user_id, reason_type, amount, reason, created_by,"
            " created_at) VALUES (?,?,?,?,?,?)",
            (user_id, reason_type, amount, reason, created_by, NOW),
        )
        raise RuntimeError("주입된 실패: 크레딧 조정 중 오류")

    rc.add_credit = boom
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            r = client.post("/api/v1/admin/registry-credits", headers=HEADERS,
                            json={"user_id": user, "reason_type": "GRANT",
                                  "amount": 5, "reason": "주입 테스트"})
    finally:
        rc.add_credit = original

    check_true("★ 5xx 로 올라온다", r.status_code >= 500, r.status_code)
    check("★★ 크레딧 행이 남지 않았다", _credit_rows(), 0)


# ---------------------------------------------------------------------------
# 5. 실패 응답에 내부 정보가 새지 않는다
# ---------------------------------------------------------------------------
def test_failure_response_has_no_internals():
    print("\n--- 5. 실패 응답에 내부 정보 없음 ---")
    import api.v1.payments as pay
    client = _client()
    pid = _seed_payment()
    original = pay.refund_payment

    def boom(conn, payment_id, amount, reason, actor, user_id=None):
        raise RuntimeError("주입된 실패: %s" % _KEY)   # 키가 예외 메시지에 섞여도

    pay.refund_payment = boom
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            r = client.post("/api/v1/admin/payments/%d/refund" % pid,
                            headers=HEADERS, json={"reason": "주입"})
    finally:
        pay.refund_payment = original

    check_true("응답에 Admin 키가 없다", _KEY not in r.text, r.text[:150])
    for bad in ("Traceback", "site-packages", "admin.py"):
        check_true("응답에 %r 이 없다" % bad, bad not in r.text, r.text[:150])


# ---------------------------------------------------------------------------
# 6. 구조 검사 — rollback 호출이 소스에 남아 있는가
#
# 위 1~5번(행위)으로는 이것을 잡지 못한다. mutation 으로 확인했다 —
# 네 곳의 `conn.rollback()`을 하나씩 지워도 4/4 전부 통과했다.
# `finally: conn.close()`가 뒤따르고 SQLite는 커밋 안 된 트랜잭션을 close에서 버리므로
# **관측 가능한 차이가 없기 때문**이다(equivalent mutant).
#
# 그래도 지워지면 안 되는 코드다. 커넥션 풀링을 도입하거나 `close` 관례가 바뀌면
# close가 더 이상 트랜잭션을 버리지 않고, 그때는 이 rollback이 유일한 방어가 된다.
# 행위로 못 잡으니 구조로 고정한다 — **구조 검사임을 숨기지 않는다.**
# ---------------------------------------------------------------------------
def test_rollback_calls_present_in_source():
    print("\n--- 6. 구조: except Exception 이 rollback 을 부른다 ---")
    import re
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "api", "v1", "admin.py")
    src = open(path, encoding="utf-8-sig").read()

    # `except Exception:` 블록을 전부 찾아 그 안에 rollback 이 있는지 본다.
    blocks = re.findall(r"except Exception:\n(.*?)(?=\n\s*(?:except|finally|# |@router|def ))",
                        src, re.S)
    check_true("except Exception 블록을 찾았다", len(blocks) >= 4, len(blocks))
    without = [b.strip()[:60] for b in blocks if "rollback()" not in b and "raise" in b]
    check("★ rollback 없이 raise 만 하는 블록", without, [])

    # finally: conn.close() 가 함께 있어야 위 논리(커밋 안 됨 -> 버려짐)가 성립한다.
    check_true("핸들러들이 finally 에서 커넥션을 닫는다",
               src.count("finally:") >= 4 and "conn.close()" in src)


if __name__ == "__main__":
    _setup()
    try:
        test_refund_failure_rolls_back()
        test_registry_status_failure_rolls_back()
        test_webhook_reprocess_failure_rolls_back()
        test_subscription_concurrent_change_returns_409()
        test_registry_credit_failure_rolls_back()
        test_failure_response_has_no_internals()
        test_rollback_calls_present_in_source()
    finally:
        if _tmpdir:
            shutil.rmtree(_tmpdir, ignore_errors=True)

    print("\n" + "=" * 60)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        sys.exit(1)
    print("ALL ADMIN FAILURE INJECTION TESTS PASSED")
