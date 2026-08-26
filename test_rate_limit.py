"""요청 속도 제한 회귀 — 2026-08-26 신설 (P1-5).

## 왜 이 파일이 생겼나

`/api/v1/search` 는 인증이 없고 요청 1건마다 SQL 을 2~3회 돈다(COUNT + 페이지 + 썸네일).
지금까지 **어떤 상한도 없었다** — 익명 클라이언트 하나가 루프를 돌리면 DB 커넥션과 CPU 를
그대로 가져간다. `docs/BETA_RELEASE_CHECKLIST.md` 가 P1-5 "Rate Limit 전무"로 들고 있던
항목이다.

## 이 파일이 고정하는 것

속도 제한은 **너무 조이면 제품이 깨지고, 조이지 않으면 방어가 아니다.** 그래서 양쪽을
다 고정한다:

    (1) 상한을 넘기면 실제로 429 가 나온다            <- 방어가 동작한다
    (2) 상한 안에서는 절대 막지 않는다                 <- 정상 사용을 깨지 않는다
    (3) 429 에도 보안 헤더가 붙는다                    <- 미들웨어 순서 계약
    (4) `/api/` 밖은 세지 않는다                       <- 범위 계약
    (5) X-Forwarded-For 로 상한을 우회할 수 없다       <- 방어가 있는 척만 하지 않는다
    (6) 끌 수 있고, 끄면 정말 안 센다                  <- 운영 탈출구

특히 (5) 가 중요하다. 헤더를 무조건 믿으면 공격자가 매 요청 다른 값을 보내는 것만으로
상한을 무한히 우회한다 — 그러면 이 미들웨어는 **비용만 쓰고 아무것도 막지 못한다.**

    python test_rate_limit.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# 미들웨어는 요청마다 환경변수를 읽으므로 import 순서에 의존하지 않는다.
# 그래도 기본값이 새어 들어오지 않게 시작 시점에 명시적으로 지운다.
for _k in ("RATE_LIMIT_PER_MINUTE", "RATE_LIMIT_ENABLED", "RATE_LIMIT_TRUST_FORWARDED"):
    os.environ.pop(_k, None)

from fastapi.testclient import TestClient          # noqa: E402
from api_server import app                         # noqa: E402
from api import rate_limit as rl                   # noqa: E402

client = TestClient(app)
failures = []


def check(name, actual, expected):
    ok = actual == expected
    print("[%s] %s: %r (expected %r)" % ("PASS" if ok else "FAIL", name, actual, expected))
    if not ok:
        failures.append(name)


def check_true(name, cond, detail=""):
    print("[%s] %s%s" % ("PASS" if cond else "FAIL", name,
                         "" if cond else " -- %s" % detail))
    if not cond:
        failures.append(name)


def _fresh(limit=None, forwarded=None, enabled=None):
    """리미터 상태와 환경을 초기화한다. 검사끼리 서로 오염되지 않게 한다."""
    rl.limiter.reset()
    if limit is None:
        os.environ.pop("RATE_LIMIT_PER_MINUTE", None)
    else:
        os.environ["RATE_LIMIT_PER_MINUTE"] = str(limit)
    if forwarded is None:
        os.environ.pop("RATE_LIMIT_TRUST_FORWARDED", None)
    else:
        os.environ["RATE_LIMIT_TRUST_FORWARDED"] = forwarded
    if enabled is None:
        os.environ.pop("RATE_LIMIT_ENABLED", None)
    else:
        os.environ["RATE_LIMIT_ENABLED"] = enabled


# ---------------------------------------------------------------------------
print("\n--- 1. 슬라이딩 윈도우 카운터 자체 ---")
# ---------------------------------------------------------------------------
lim = rl.SlidingWindowLimiter()

# 고정 시각을 넘겨 시간에 의존하지 않게 한다(느린 CI 에서 흔들리면 결국 꺼진다).
allowed = [lim.check("a", 3, now=100.0)[0] for _ in range(5)]
check("상한 3 -> 앞 3건만 통과", allowed, [True, True, True, False, False])

# ★ 고정 창(fixed window)이 아니라 슬라이딩이다.
#   고정 창이면 창이 바뀌는 순간 상한만큼이 한꺼번에 열린다(경계에서 2배).
#
#   ★ 타임스탬프를 **엇갈리게** 넣는 것이 이 검사의 핵심이다 (2026-08-26 정정).
#     처음 판은 세 건을 전부 같은 시각(100.0)에 넣었는데, 그러면 "만료된 것만 버린다"와
#     "하나라도 만료면 전부 버린다"가 **똑같은 결과**를 낸다 — mutation 으로 실증했다
#     (`while ... popleft()` 를 `if ... clear()` 로 바꿔도 검사가 통과했다).
#     시각을 벌려 두면 t=161 에서 100.0 하나만 만료되므로 **한 자리만** 나야 하고,
#     전부 비우는 구현은 세 자리를 열어 곧바로 드러난다.
lim2 = rl.SlidingWindowLimiter()
for t in (100.0, 130.0, 150.0):
    lim2.check("b", 3, now=t)
check_true("창이 지나기 전에는 여전히 막힌다",
           lim2.check("b", 3, now=159.0)[0] is False)
check_true("★ 가장 오래된 요청이 창을 벗어나면 한 자리가 난다(슬라이딩)",
           lim2.check("b", 3, now=161.0)[0] is True,
           "-> 100.0 이 만료됐으므로 한 자리가 나야 한다")
check_true("★ 그러나 **한 자리뿐**이다(고정 창이면 여기서 또 열린다)",
           lim2.check("b", 3, now=161.1)[0] is False,
           "-> 여기서 True 면 창 전체를 비우는 구현이다. 경계에서 상한의 2배가 통과한다")

# ★ 2026-08-26 — 창의 **정확한 경계**를 못박는다.
#
#   경계 변이(`bucket[0] <= cutoff` -> `<`)가 **살아남는 것**을 확인하고 추가했다.
#   위 검사들은 159.0 / 161.0 / 161.1 만 보므로 `now - 60.0` 과 **정확히 같은** 시각이
#   만료로 처리되는지는 한 번도 지나지 않는다.
#
#   `_WINDOW_SECONDS = 60` 이고 판정이 `bucket[0] <= now - 60` 이므로,
#   100.0 에 넣은 요청은 now=160.0 에서 **정확히 만료**여야 한다(포함 경계).
#   `<` 로 바뀌면 그 한 건이 창에 남아 자리가 나지 않는다.
lim2b = rl.SlidingWindowLimiter()
for t in (100.0, 130.0, 150.0):
    lim2b.check("edge", 3, now=t)
check_true("★ cutoff 와 **정확히 같은** 시각의 요청은 만료로 본다(포함 경계)",
           lim2b.check("edge", 3, now=160.0)[0] is True,
           "-> 100.0 == 160.0-60.0 이다. False 면 경계가 배타적(`<`)으로 바뀐 것")
# 바로 직전(159.999)은 아직 만료가 아니어야 한다 — 경계가 한쪽으로만 열려 있는지 함께 본다.
lim2c = rl.SlidingWindowLimiter()
for t in (100.0, 130.0, 150.0):
    lim2c.check("edge2", 3, now=t)
check_true("★ cutoff 직전은 아직 만료가 아니다(경계가 한 방향으로만 열린다)",
           lim2c.check("edge2", 3, now=159.999)[0] is False,
           "-> 여기서 True 면 만료 판정이 너무 이르다")

lim3 = rl.SlidingWindowLimiter()
ok, retry = lim3.check("c", 1, now=100.0)
ok2, retry2 = lim3.check("c", 1, now=110.0)
check_true("거절될 때 남은 초를 알려준다", ok and not ok2 and 49.0 < retry2 <= 50.0,
           "-> retry=%r" % retry2)

lim4 = rl.SlidingWindowLimiter()
check_true("상한 0 이하면 제한하지 않는다",
           all(lim4.check("d", 0, now=100.0 + i)[0] for i in range(50)))

# 키가 다르면 서로 영향을 주지 않는다 - 한 사용자가 다른 사용자를 막으면 안 된다.
lim5 = rl.SlidingWindowLimiter()
for _ in range(3):
    lim5.check("user-a", 3, now=100.0)
check_true("★ 다른 클라이언트는 서로 막지 않는다",
           lim5.check("user-b", 3, now=100.0)[0] is True)

# 메모리 상한 - 없으면 IP 를 바꿔 가며 때리는 것만으로 메모리를 불릴 수 있다.
lim6 = rl.SlidingWindowLimiter(max_clients=100)
for i in range(400):
    lim6.check("k%d" % i, 10, now=100.0)
check_true("★ 추적 클라이언트 수에 상한이 있다(방어가 공격 통로가 되지 않는다)",
           len(lim6._hits) <= 100, "-> %d개" % len(lim6._hits))


# ---------------------------------------------------------------------------
print("\n--- 2. 미들웨어: 상한을 넘기면 429 ---")
# ---------------------------------------------------------------------------
_fresh(limit=4)
codes = [client.get("/api/v1/plans").status_code for _ in range(7)]
check("상한 4 -> 앞 4건 200, 이후 429", codes, [200, 200, 200, 200, 429, 429, 429])

resp = client.get("/api/v1/plans")
check("거절은 429", resp.status_code, 429)
check_true("Retry-After 헤더가 있다", resp.headers.get("retry-after") is not None,
           "-> 없으면 클라이언트가 즉시 재시도 루프를 돈다")
check_true("Retry-After 가 양의 정수다",
           (resp.headers.get("retry-after") or "").isdigit()
           and int(resp.headers["retry-after"]) >= 1,
           "-> %r" % resp.headers.get("retry-after"))
check_true("본문이 JSON detail 을 준다", "detail" in resp.json())

# ★ 미들웨어 순서 계약. 속도 제한이 보안 헤더보다 **안쪽**이어야 429 에도 헤더가 붙는다.
check("★ 429 에도 보안 헤더가 붙는다(미들웨어 순서)",
      resp.headers.get("x-content-type-options"), "nosniff")


# ---------------------------------------------------------------------------
print("\n--- 3. 정상 사용을 막지 않는다 ---")
# ---------------------------------------------------------------------------
_fresh(limit=200)
codes = [client.get("/api/v1/plans").status_code for _ in range(60)]
check_true("★ 상한 안에서는 한 건도 막히지 않는다",
           set(codes) == {200}, "-> %r" % sorted(set(codes)))

# 기본값이 사람이 쓰는 속도를 막지 않는지도 본다. 기본 1200/분 = 초당 20회.
_fresh()
check_true("기본 상한이 넉넉하다(>= 600/분)", rl.limit_per_minute() >= 600,
           "-> %d. 너무 조이면 결국 꺼 버리게 된다" % rl.limit_per_minute())
codes = [client.get("/api/v1/plans").status_code for _ in range(120)]
check_true("★ 기본값에서 연속 120회가 전부 통과한다",
           set(codes) == {200}, "-> %r" % sorted(set(codes)))


# ---------------------------------------------------------------------------
print("\n--- 4. 범위: /api/ 밖은 세지 않는다 ---")
# ---------------------------------------------------------------------------
_fresh(limit=3)
codes = [client.get("/").status_code for _ in range(10)]
check_true("루트 경로는 제한 대상이 아니다", set(codes) == {200}, "-> %r" % sorted(set(codes)))
check_true("검사가 공허하지 않다(같은 상한에서 /api/ 는 막힌다)",
           429 in [client.get("/api/v1/plans").status_code for _ in range(10)])


# ---------------------------------------------------------------------------
print("\n--- 5. ★ X-Forwarded-For 로 우회할 수 없다 ---")
# ---------------------------------------------------------------------------
# 헤더를 무조건 믿으면 매 요청 다른 값을 보내는 것만으로 상한이 무의미해진다.
_fresh(limit=3)
codes = [client.get("/api/v1/plans",
                    headers={"X-Forwarded-For": "10.0.0.%d" % i}).status_code
         for i in range(8)]
check_true("★ 신뢰 설정이 없으면 X-Forwarded-For 를 무시한다(우회 불가)",
           429 in codes, "-> %r  헤더만 바꿔 상한을 넘겼다면 방어가 없는 것이다" % codes)

# 반대로, 신뢰할 수 있는 프록시 뒤라고 **명시**하면 그때는 헤더를 쓴다.
_fresh(limit=3, forwarded="1")
codes = [client.get("/api/v1/plans",
                    headers={"X-Forwarded-For": "10.0.0.%d" % i}).status_code
         for i in range(8)]
check_true("신뢰 설정이 있으면 IP 별로 따로 센다",
           set(codes) == {200}, "-> %r" % sorted(set(codes)))
_fresh(limit=3, forwarded="1")
codes = [client.get("/api/v1/plans",
                    headers={"X-Forwarded-For": "10.0.0.7"}).status_code
         for i in range(8)]
check_true("신뢰 설정이 있어도 같은 IP 는 막힌다", 429 in codes, "-> %r" % codes)


# ---------------------------------------------------------------------------
print("\n--- 6. 끌 수 있다 ---")
# ---------------------------------------------------------------------------
_fresh(limit=2, enabled="0")
codes = [client.get("/api/v1/plans").status_code for _ in range(10)]
check_true("RATE_LIMIT_ENABLED=0 이면 세지 않는다",
           set(codes) == {200}, "-> %r" % sorted(set(codes)))
_fresh(limit=2, enabled="1")
check_true("검사가 공허하지 않다(켜면 같은 상한에서 막힌다)",
           429 in [client.get("/api/v1/plans").status_code for _ in range(10)])

# 상한을 0 으로 두는 것도 실질적인 끄기다(운영 탈출구가 둘이다).
_fresh(limit=0)
codes = [client.get("/api/v1/plans").status_code for _ in range(30)]
check_true("RATE_LIMIT_PER_MINUTE=0 이면 제한하지 않는다",
           set(codes) == {200}, "-> %r" % sorted(set(codes)))

# 잘못된 값이 들어와도 죽지 않고 기본값으로 간다.
_fresh(limit="not-a-number")
check_true("숫자가 아닌 설정은 기본값으로 떨어진다(부팅을 막지 않는다)",
           rl.limit_per_minute() == 1200, "-> %r" % rl.limit_per_minute())


# ---------------------------------------------------------------------------
print("\n--- 7. 검색 경로에도 실제로 걸린다 ---")
# ---------------------------------------------------------------------------
# 이 미들웨어의 존재 이유가 검색이다. `/plans` 로만 확인하면 정작 지켜야 할 곳을
# 안 재고 넘어갈 수 있다.
_fresh(limit=3)
codes = [client.get("/api/v1/search?size=1").status_code for _ in range(7)]
check_true("★ /api/v1/search 도 제한 대상이다", 429 in codes, "-> %r" % codes)

# 뒷정리 - 다른 테스트가 이어서 돌 때 영향을 주지 않게 한다.
_fresh()

print()
if failures:
    print("실패 %d건: %s" % (len(failures), failures))
    raise SystemExit(1)
print("전체 통과")
raise SystemExit(0)
