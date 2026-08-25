"""요청 속도 제한 (2026-08-26 신설, docs/BETA_RELEASE_CHECKLIST.md P1-5).

## 무엇을 막는가

`/api/v1/search` 는 **인증이 없고** 요청 1건마다 SQL 을 2~3회 돈다
(COUNT + 페이지 + 썸네일 배치). 지금까지 상한이 전혀 없어서, 익명 클라이언트 하나가
루프를 돌리면 DB 커넥션과 CPU 를 그대로 가져간다. 결제 웹훅(`POST /api/v1/payments/
webhook/{provider}`)도 공개 경로다 — 서명 검증에 실패하면 저장하지 않도록 이미 고쳤지만
(BUGS: 저장소 증폭), **검증 자체의 비용**은 여전히 요청마다 든다.

## 왜 외부 패키지를 쓰지 않았나

`slowapi` 같은 패키지가 있지만 이 저장소는 의존성을 `requirements.txt` 에 `==` 로 고정해
관리하고, 지금 필요한 것은 **단일 프로세스 상한** 하나뿐이다. 표준 라이브러리만으로
충분하고, 의존성이 늘면 그만큼 공급망과 버전 고정 부담이 는다.

## ★ 이 구현의 한계 — 반드시 알고 써야 한다

**프로세스 안에서만 센다.** `uvicorn --workers 4` 처럼 워커를 여러 개 띄우면 워커마다
따로 세므로 실효 상한이 워커 수만큼 곱해진다. 여러 인스턴스로 수평 확장하면 더 벌어진다.
그때는 공용 저장소(Redis 등) 기반으로 바꿔야 하고, 그것은 인프라 결정이라 여기서 하지 않는다.

즉 이것은 **완전한 방어가 아니라 하한선**이다 — "아무 상한도 없음"에서 "명백한 폭주는
막힘"으로 옮기는 것이 목적이다. 진짜 방어(WAF/리버스 프록시 속도 제한)는 배포 계층의 일이다.

## 기본값을 왜 이렇게 잡았나

    RATE_LIMIT_PER_MINUTE   기본 1200 (= 초당 20회)

사람이 브라우저로 쓰는 속도와는 비교가 안 되게 넉넉하다. 검색 화면을 아무리 빠르게
조작해도 초당 20회에 닿지 않는다. **정상 사용을 막지 않는 것이 오상한보다 중요하다** —
너무 조이면 제품이 깨지고, 그러면 결국 꺼 버리게 된다(이 저장소가 가드에서 반복해
경계해 온 실패 모양이다).

    RATE_LIMIT_ENABLED      기본 "1". "0"/"false" 로 끌 수 있다.

## 세는 단위

클라이언트 IP 다. 프록시 뒤에 있으면 `X-Forwarded-For` 의 **첫 번째** 값을 쓴다 —
다만 그 헤더는 클라이언트가 위조할 수 있으므로, 신뢰할 수 있는 프록시 뒤가 아니라면
`RATE_LIMIT_TRUST_FORWARDED=0`(기본) 으로 두고 소켓 주소만 쓴다.
"""
import os
import threading
import time
from collections import deque

# 창(window) 길이. 분당 상한이라 60초 고정이다.
_WINDOW_SECONDS = 60.0

# 메모리 상한. 서로 다른 IP 가 이보다 많아지면 가장 오래된 것부터 버린다.
# 없으면 IP 를 바꿔 가며 때리는 것만으로 메모리를 불릴 수 있다(방어 자체가 공격 통로가 된다).
_MAX_TRACKED_CLIENTS = 10000


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off")


def limit_per_minute() -> int:
    """분당 허용 요청 수. 0 이하이면 제한하지 않는다.

    호출할 때마다 읽는다 — 테스트가 `os.environ` 을 바꿔 가며 검증할 수 있어야 한다
    (모듈 최상단에서 한 번만 읽으면 그 검증이 불가능하다).
    """
    try:
        return int(os.getenv("RATE_LIMIT_PER_MINUTE", "1200"))
    except ValueError:
        return 1200


def enabled() -> bool:
    return _env_flag("RATE_LIMIT_ENABLED", True)


def trust_forwarded() -> bool:
    return _env_flag("RATE_LIMIT_TRUST_FORWARDED", False)


class SlidingWindowLimiter:
    """클라이언트별 슬라이딩 윈도우 카운터. 스레드 안전.

    고정 창(fixed window)이 아니라 슬라이딩이다 — 고정 창은 경계에서 상한의 2배까지
    통과시킨다(59초에 N번, 61초에 N번). 창 안의 타임스탬프를 큐로 들고 있다가
    만료된 것만 앞에서 버린다.
    """

    def __init__(self, max_clients: int = _MAX_TRACKED_CLIENTS):
        self._hits = {}                 # key -> deque[timestamp]
        self._lock = threading.Lock()
        self._max_clients = max_clients

    def check(self, key: str, limit: int, now: float = None):
        """(허용 여부, 재시도까지 남은 초) 를 돌려준다.

        `limit <= 0` 이면 제한하지 않는다.
        """
        if limit <= 0:
            return True, 0.0
        now = time.monotonic() if now is None else now
        cutoff = now - _WINDOW_SECONDS

        with self._lock:
            bucket = self._hits.get(key)
            if bucket is None:
                # 메모리 상한. dict 는 삽입 순서를 지키므로 가장 오래된 키가 앞에 있다.
                if len(self._hits) >= self._max_clients:
                    for stale in list(self._hits)[:max(1, self._max_clients // 10)]:
                        self._hits.pop(stale, None)
                bucket = self._hits[key] = deque()

            while bucket and bucket[0] <= cutoff:
                bucket.popleft()

            if len(bucket) >= limit:
                # 가장 오래된 요청이 창을 벗어나야 한 자리가 난다.
                retry_after = bucket[0] + _WINDOW_SECONDS - now
                return False, max(0.0, retry_after)

            bucket.append(now)
            return True, 0.0

    def reset(self):
        """테스트용. 운영 경로에서는 부르지 않는다."""
        with self._lock:
            self._hits.clear()


# 프로세스 전역 인스턴스. 미들웨어가 이것을 쓴다.
limiter = SlidingWindowLimiter()


def client_key(request) -> str:
    """요청을 어느 클라이언트로 셀 것인가.

    `X-Forwarded-For` 는 **클라이언트가 임의로 보낼 수 있다.** 신뢰할 수 있는 프록시
    뒤라고 명시(`RATE_LIMIT_TRUST_FORWARDED=1`)했을 때만 읽는다. 그러지 않으면
    공격자가 헤더만 바꿔 가며 상한을 무한히 우회한다 — 방어가 있는 척만 하게 된다.
    """
    if trust_forwarded():
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            first = fwd.split(",")[0].strip()
            if first:
                return first
    client = getattr(request, "client", None)
    return getattr(client, "host", None) or "unknown"
