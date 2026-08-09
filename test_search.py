"""
api/v1/search.py의 /api/v1/search 엔드포인트 회귀 테스트.

Sprint 5 STEP2(Intent Search -> Search API 연결) 검증용. 실제 auction.db를
대상으로 FastAPI TestClient를 통해 호출한다(DB는 읽기 전용, 쓰기 없음).

기존 프로젝트에 pytest 설정이 없으므로 test_normalizer.py와 동일한 컨벤션
(CASES 리스트 + run() 함수, PASS/FAIL 출력)을 따른다.

실행: python test_search.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient
from api_server import app

client = TestClient(app)


def search_total(**params):
    # 이 파일은 주소 의도(Intent) 파싱이 옳은지를 검증한다(매각기일 필터와는 무관한 관심사).
    # /api/v1/search의 D7 기본 필터(auction_date >= 오늘)가 나중에 추가되면서, 이 파라미터
    # 없이 호출하면 예전 스냅숏(전체 매물 기준) 값과 항상 어긋난다 — 2026-08-09 실측으로
    # 확인(같은 검색어를 include_closed 유무로 비교해 D7 필터가 유일한 원인임을 검증).
    r = client.get("/api/v1/search", params={**params, "size": 1, "include_closed": True})
    assert r.status_code == 200, (params, r.status_code, r.text)
    return r.json()["total"]


# (설명, address_detail 값, 기대 total)
# 기대값은 실제 auction.db 기준 실측치이며, 매일 크롤링으로 데이터가 늘어나므로 절대 건수는
# 시점에 따라 자연히 드리프트한다(회귀가 아니다) — search_total()이 include_closed=True로
# 매각기일 필터를 빼고 호출하는 것도 같은 이유(주소 파싱 자체를 보는 테스트이므로 D7 기본
# 필터는 이 파일의 관심사가 아니다). 2026-08-09 재동기화: 서울/빛가람동 두 지역만 Sprint 4
# 이후 크롤링으로 실제 건수가 늘어 갱신했고, 나머지는 원래 값과 정확히 일치함을 실측
# 확인했다(검색 로직 자체는 무결함 — include_closed 유무로 대조해 원인이 D7 필터뿐임을 검증).
ADDRESS_DETAIL_CASES = [
    ("시도(축약)", "서울", 284),
    ("시도(-시 축약형, Bug Fix 대상)", "서울시", 284),
    ("시도(정식)", "서울특별시", 284),
    ("시군구", "송파구", 19),
    ("법정동", "오금동", 3),
    ("전체주소 - 기존 0건 문제 해결 확인", "서울 송파구 오금동", 3),
    ("전체주소(축약형 포함) - 기존 0건 문제 해결 확인", "서울시 송파구 오금동", 3),
    ("혼합입력(시군구+동+일반명사)", "강서구 화곡동 빌라", 1),
    ("건물명(UNKNOWN, 기존 LIKE 유지 회귀 확인)", "엘시티", 1),
    ("법정동(STEP7 백필분)", "빛가람동", 12),
    ("법정동(STEP6/7 오탐 수정분)", "성남동", 1),
    ("혼합입력 - 데이터 자체가 없는 케이스(정상 0건)", "고양시 일산동구 마두동", 0),
    ("존재하지 않는 검색어", "존재하지않는검색어123", 0),
]


def run():
    failures = []

    for name, value, expected in ADDRESS_DETAIL_CASES:
        actual = search_total(address_detail=value)
        ok = actual == expected
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name}: address_detail={value!r} -> total={actual} (기대 {expected})")
        if not ok:
            failures.append(name)

    # 빈 문자열: 필터 없음과 동일하게 전체 건수가 나와야 한다(기존 동작 보존).
    empty_total = search_total(address_detail="")
    baseline_total = search_total()
    ok = empty_total == baseline_total
    print(f"[{'PASS' if ok else 'FAIL'}] 빈 문자열 address_detail: total={empty_total} (무필터 total={baseline_total}과 동일해야 함)")
    if not ok:
        failures.append("빈 문자열 address_detail")

    # 기존 명시적 sido/sigungu/dong 파라미터는 이번 변경과 무관하게 그대로 동작해야 한다.
    ok = search_total(sido="서울특별시") == search_total(sido="서울")
    print(f"[{'PASS' if ok else 'FAIL'}] 기존 sido 파라미터 정규화(STEP2) 회귀 없음")
    if not ok:
        failures.append("기존 sido 파라미터 정규화 회귀")

    # address_detail(구조화 검색)과 다른 기존 필터(가격/기간 등)의 AND 결합이 깨지지 않는지 확인.
    combined = search_total(address_detail="오금동", min_appraisal=0)
    solo = search_total(address_detail="오금동")
    ok = combined == solo  # min_appraisal>=0은 전 항목이 만족하므로 결과가 같아야 함
    print(f"[{'PASS' if ok else 'FAIL'}] address_detail + 가격조건 AND 결합: combined={combined} solo={solo}")
    if not ok:
        failures.append("address_detail + 다른 필터 AND 결합")

    # 응답 스키마 불변 확인
    r = client.get("/api/v1/search", params={"address_detail": "오금동", "size": 1})
    body = r.json()
    ok = set(body.keys()) == {"total", "page", "size", "total_pages", "items"}
    print(f"[{'PASS' if ok else 'FAIL'}] 응답 스키마 불변: {set(body.keys())}")
    if not ok:
        failures.append("응답 스키마 불변")

    print()
    if failures:
        print(f"{len(failures)}건 실패: {failures}")
        return 1
    print(f"전체 {len(ADDRESS_DETAIL_CASES) + 4}건 통과")
    return 0


if __name__ == "__main__":
    sys.exit(run())
