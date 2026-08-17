"""[진단 스크립트] filter_engine 출력 눈으로 보기 — **테스트가 아니다.**

## 이름은 test_ 로 시작하지만 아무것도 판정하지 않는다

이 파일에는 **판정문(assert/check)이 하나도 없다.** `filter_auctions()`를 몇 가지
조건으로 부르고 `print_results()`로 찍을 뿐이다. 결과가 틀려도 종료코드는 0이다.

그래서 `종료코드 == 0` 을 통과로 세는 집계에 이 파일이 섞이면 **검증하지 않은 것이
통과로 계산된다.** 2026-08-17 세션에서 실제로 그렇게 오집계했다(33 통과로 보고했으나
정확히는 32 통과 + 판정없음 1).

집계할 때는 `run_python_tests.py`를 쓸 것 — 그 실행기는 이 파일을 "판정문 없음
(검증했다고 말할 수 없다)"으로 따로 분류한다.

## 왜 판정문을 넣지 않는가

대상인 `filter/` 패키지는 `api_server.py`에 연결되지 않은 **죽은 코드**다
(docs/CLAUDE.md Architecture 절). 그 문서가 명시적으로 적고 있다 —
"deleting them is approval-gated; do **not** add tests for them either —
testing code nobody runs buys nothing."

즉 여기서 할 수 있는 정직한 조치는 판정문을 넣는 것이 아니라, **이 파일이 무엇인지
분명히 하는 것**이다. `filter/`가 실제로 API에 연결되는 날, 그때가 진짜 테스트를
쓸 시점이다.

    python test_filter.py     # 출력을 눈으로 확인하는 용도
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from filter.filter_engine import filter_auctions, print_results

print("===== 필터 엔진 테스트 =====")

print("[테스트 1] 서울 전체")
results = filter_auctions(sido="서울", limit=5)
print_results(results, "서울 전체 (상위 5건)")

print("[테스트 2] 최저가율 50% 이하")
results = filter_auctions(max_bid_rate=0.5, limit=5)
print_results(results, "최저가율 50% 이하 (상위 5건)")

print("[테스트 3] 유찰 5회 이상")
results = filter_auctions(min_fail_count=5, limit=5)
print_results(results, "유찰 5회 이상 (상위 5건)")

print("[테스트 4] 서울 + 유찰 3회 이상 + 최저가율 70% 이하")
results = filter_auctions(
    sido="서울",
    min_fail_count=3,
    max_bid_rate=0.7,
    limit=5
)
print_results(results, "서울 + 유찰 3회 이상 + 최저가율 70% 이하")
