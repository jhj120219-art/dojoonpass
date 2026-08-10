"""
api/v1/search.py의 /api/v1/search 엔드포인트 회귀 테스트.

이 파일의 관심사는 **주소 의도(Intent) 파싱이 올바른 SQL 조건으로 번역되는가**다
(`intent/analyzer.py` + `api/v1/search.py:_address_detail_condition()`).

2026-08-10(Sprint 47) 재설계 — 고정 row count 단언 제거
------------------------------------------------------
예전 버전은 `address_detail="서울" -> total == 284`처럼 **절대 건수**를 하드코딩했다.
크롤러가 매일 데이터를 넣기 때문에 이 값은 필연적으로 드리프트했고, 실제로 두 번
(2026-08-09, 2026-08-10) "실패 3건"이 났지만 **전부 검색 로직 결함이 아니라 기대값 노후화**였다.
회귀를 못 잡으면서 매번 사람을 부르는 테스트는 오히려 신호를 가린다.

그래서 "몇 건인가" 대신 **반환된 행이 실제로 그 의도에 맞는가**를 검증한다.
예: `address_detail="오금동"`이면 돌아온 모든 행의 `dong`에 "오금동"이 들어 있어야 한다.
이건 데이터가 늘어도 항상 참이어야 하는 성질이고, 조건이 엉뚱한 컬럼에 걸리면
(원래 이 테스트가 잡으려던 결함) 즉시 실패한다 — 즉 검증력은 오히려 강해졌다.

여기에 데이터와 무관하게 성립하는 **관계 불변식**을 추가한다.
- 표기 동치: "서울" == "서울시" == "서울특별시" (축약 정규화, 원래 Bug Fix 대상)
- 분해 동치: address_detail="서울 송파구 오금동" == sido/sigungu/dong 개별 지정
- 포함 관계: 더 구체적인 검색은 덜 구체적인 검색보다 결과가 많을 수 없다

실행: python test_search.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient
from api_server import app

client = TestClient(app)

PASS = 0
FAILURES = []


def check(name, ok, detail=""):
    global PASS
    if ok:
        PASS += 1
        print(f"[PASS] {name}")
    else:
        FAILURES.append(name)
        print(f"[FAIL] {name} {detail}")


def search(**params):
    """주소 파싱 자체를 보는 테스트이므로 D7 기본 필터(auction_date >= 오늘)는 제외한다
    (매각기일 필터는 이 파일의 관심사가 아니다)."""
    r = client.get("/api/v1/search", params={**params, "include_closed": True})
    assert r.status_code == 200, (params, r.status_code, r.text)
    return r.json()


def total(**params):
    return search(size=1, **params)["total"]


def items(size=100, **params):
    return search(size=size, **params)["items"]


# (설명, address_detail, 각 행이 만족해야 하는 조건)
# 절대 건수 대신 "돌아온 행이 그 의도에 맞는가"를 본다.
INTENT_CASES = [
    ("시도(축약) -> sido 정확일치", "서울",
     lambda it: it["sido"] == "서울"),
    ("시도(-시 축약형) -> sido 정확일치", "서울시",
     lambda it: it["sido"] == "서울"),
    ("시도(정식) -> sido 정확일치", "서울특별시",
     lambda it: it["sido"] == "서울"),
    ("시군구 -> sigungu 부분일치", "송파구",
     lambda it: "송파구" in (it["sigungu"] or "")),
    ("법정동 -> dong 부분일치", "오금동",
     lambda it: "오금동" in (it["dong"] or "")),
    ("전체주소 -> sido+sigungu+dong 동시 적용", "서울 송파구 오금동",
     lambda it: it["sido"] == "서울" and "송파구" in (it["sigungu"] or "") and "오금동" in (it["dong"] or "")),
    ("전체주소(축약형 포함)", "서울시 송파구 오금동",
     lambda it: it["sido"] == "서울" and "송파구" in (it["sigungu"] or "") and "오금동" in (it["dong"] or "")),
    ("혼합입력(시군구+동+일반명사) -> 잔여어는 full_address", "강서구 화곡동 빌라",
     lambda it: "강서구" in (it["sigungu"] or "") and "화곡동" in (it["dong"] or "") and "빌라" in (it["full_address"] or "")),
    ("건물명(UNKNOWN) -> full_address LIKE 폴백", "엘시티",
     lambda it: "엘시티" in (it["full_address"] or "")),
    ("법정동(STEP7 백필분)", "빛가람동",
     lambda it: "빛가람동" in (it["dong"] or "")),
    ("법정동(STEP6/7 오탐 수정분)", "성남동",
     lambda it: "성남동" in (it["dong"] or "")),
]


def run():
    print("=" * 70)
    print(" /api/v1/search 주소 Intent 회귀 (건수 비의존)")
    print("=" * 70)

    # --- 1. 의도별 행 단위 검증 -------------------------------------------
    for name, value, predicate in INTENT_CASES:
        rows = items(address_detail=value)
        if not rows:
            # 0건 자체는 실패가 아니다(데이터가 없을 수 있다). 다만 검증할 게 없으므로 표시만 한다.
            check(f"{name} - 대상 데이터 없음(검증 생략)", True)
            continue
        bad = [it for it in rows if not predicate(it)]
        check(
            f"{name} ({len(rows)}건 전수 확인)",
            not bad,
            f"-> 조건 불일치 {len(bad)}건, 예: {bad[0]['full_address'] if bad else ''!r}",
        )

    # --- 2. 표기 동치 (축약 정규화) — 데이터 무관 불변식 --------------------
    t_short, t_si, t_full = total(address_detail="서울"), total(address_detail="서울시"), total(address_detail="서울특별시")
    check(
        "표기 동치: '서울' == '서울시' == '서울특별시'",
        t_short == t_si == t_full,
        f"-> {t_short}/{t_si}/{t_full}",
    )

    check(
        "기존 sido 파라미터 정규화 회귀 없음('서울특별시' == '서울')",
        total(sido="서울특별시") == total(sido="서울"),
    )

    # --- 2-b. 컬럼 매핑 고정: 자유텍스트 의도 == 같은 뜻의 명시적 파라미터 ----
    #
    # 이게 이 파일에서 가장 중요한 검사다. 위 "행 단위 검증"은 조건이 엉뚱한 컬럼에 걸려
    # **0건**이 되면 검증할 행이 없어 조용히 통과해버린다(실제로 mutation 테스트에서 확인).
    # 아래 동치는 결과가 0건이든 아니든 항상 성립해야 하므로, 컬럼이 바뀌는 순간 깨진다.
    for label, free_kw, explicit in [
        ("시도", {"address_detail": "서울"}, {"sido": "서울"}),
        ("시군구", {"address_detail": "송파구"}, {"sigungu": "송파구"}),
        ("법정동", {"address_detail": "오금동"}, {"dong": "오금동"}),
    ]:
        a, b = total(**free_kw), total(**explicit)
        check(
            f"컬럼 매핑 고정({label}): address_detail 검색 == 해당 파라미터 검색",
            a == b,
            f"-> address_detail={a} vs 명시적={b} (의도가 다른 컬럼에 걸렸을 수 있음)",
        )

    # --- 3. 분해 동치: 자유텍스트 전체주소 == 개별 파라미터 지정 -------------
    t_free = total(address_detail="서울 송파구 오금동")
    t_explicit = total(sido="서울", sigungu="송파구", dong="오금동")
    check(
        "분해 동치: address_detail 전체주소 == sido/sigungu/dong 개별 지정",
        t_free == t_explicit,
        f"-> free={t_free} explicit={t_explicit}",
    )

    # --- 4. 포함 관계: 구체적일수록 결과가 늘어날 수 없다 -------------------
    t_dong = total(address_detail="오금동")
    check(
        "포함 관계: '서울 송파구 오금동' <= '오금동'",
        t_free <= t_dong,
        f"-> {t_free} > {t_dong}",
    )
    t_sigungu_only = total(sigungu="송파구")
    check(
        "포함 관계: sido+sigungu <= sigungu 단독",
        total(sido="서울", sigungu="송파구") <= t_sigungu_only,
    )

    # --- 5. 매칭이 불가능한 입력은 항상 0건 (데이터 무관) -------------------
    check("존재하지 않는 검색어는 0건", total(address_detail="존재하지않는검색어123") == 0)

    # --- 6. 기존 동작 보존 --------------------------------------------------
    check(
        "빈 문자열 address_detail == 무필터",
        total(address_detail="") == total(),
    )
    solo, combined = total(address_detail="오금동"), total(address_detail="오금동", min_appraisal=0)
    check(
        "address_detail + 가격조건 AND 결합",
        combined == solo,
        f"-> combined={combined} solo={solo}",
    )

    # --- 7. 응답 계약 --------------------------------------------------------
    body = search(address_detail="오금동", size=1)
    check(
        "응답 스키마 불변",
        set(body.keys()) == {"total", "page", "size", "total_pages", "items"},
        f"-> {set(body.keys())}",
    )
    check("page/size 반영", body["page"] == 1 and body["size"] == 1)

    required = {
        "id", "case_no", "item_no", "court_name", "property_type",
        "sido", "sigungu", "dong", "full_address",
        "appraisal_price", "minimum_bid_price", "bid_rate",
        "auction_date", "status", "fail_count",
        "validation_status", "crawl_date", "is_favorited",
    }
    sample = items(size=1)
    if sample:
        missing = required - set(sample[0].keys())
        check("item 필수 필드 전부 존재", not missing, f"-> 누락 {missing}")
    else:
        check("item 필수 필드 - 데이터 없음(검증 생략)", True)

    print()
    if FAILURES:
        print(f"{len(FAILURES)}건 실패: {FAILURES}")
        return 1
    print(f"전체 {PASS}건 통과")
    return 0


if __name__ == "__main__":
    sys.exit(run())
