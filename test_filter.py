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
