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

    # --- 5. 선언만 되고 한 번도 실행된 적 없는 필터 (2026-08-13 Sprint 85) ------
    #
    # 커버리지로 찾았다: api/v1/search.py 266-305가 미커버였다. court_name / status /
    # auction_date_to / min·max appraisal / min·max bid_price / min·max bid_rate /
    # min·max fail_count — **12개 필터가 선언돼 있는데 어떤 테스트도 넘겨본 적이 없었다.**
    #
    # 이 부류의 결함은 조용하다. 예를 들어 min 필터가 `<=`로 뒤집혀 있으면 사용자는
    # "최소 감정가 5억"으로 검색해 **5억 이하** 물건을 받는다. 서버는 200을 주고 로그도
    # 남지 않는다. 그래서 "몇 건인가"가 아니라 **돌아온 행이 조건을 만족하는가** +
    # **방향이 뒤집히지 않았는가**를 본다(이 파일의 기존 원칙과 같다).
    #
    # 경계값은 실제 데이터에서 뽑는다 — 하드코딩하면 데이터가 변할 때 노후화된다.
    def _numeric_bound(field):
        """그 컬럼의 중앙값 근처 값 하나. 없으면 None."""
        rows = [it[field] for it in items(size=100) if it.get(field) is not None]
        if not rows:
            return None
        rows.sort()
        return rows[len(rows) // 2]

    RANGE_FILTERS = [
        ("appraisal_price", "min_appraisal", "max_appraisal"),
        ("minimum_bid_price", "min_bid_price", "max_bid_price"),
        ("bid_rate", "min_bid_rate", "max_bid_rate"),
        ("fail_count", "min_fail_count", "max_fail_count"),
    ]
    for field, min_key, max_key in RANGE_FILTERS:
        bound = _numeric_bound(field)
        if bound is None:
            check("%s 범위 필터 - 대상 데이터 없음(검증 생략)" % field, True)
            continue

        lo = items(size=100, **{min_key: bound})
        hi = items(size=100, **{max_key: bound})
        # (a) 행 단위로 조건을 만족하는가
        bad_lo = [it for it in lo if it.get(field) is not None and it[field] < bound]
        bad_hi = [it for it in hi if it.get(field) is not None and it[field] > bound]
        check("%s: %s=%s 이면 모든 행이 그 이상" % (field, min_key, bound),
              not bad_lo, "-> 위반 %d건, 예: %r" % (len(bad_lo), bad_lo[0].get(field) if bad_lo else None))
        check("%s: %s=%s 이면 모든 행이 그 이하" % (field, max_key, bound),
              not bad_hi, "-> 위반 %d건, 예: %r" % (len(bad_hi), bad_hi[0].get(field) if bad_hi else None))

        # (b) 방향이 뒤집히지 않았는가 — min/max를 서로 바꿔 구현하면 (a)만으로는
        #     한쪽이 통과할 수 있다. 두 결과의 합이 전체를 덮고, 교집합이 경계값뿐임을 본다.
        t_all = total()
        t_lo, t_hi = total(**{min_key: bound}), total(**{max_key: bound})
        eq = len([it for it in items(size=100) if it.get(field) == bound])
        check("%s: min/max 결과가 전체를 덮는다(방향 정합)" % field,
              t_lo + t_hi >= t_all, "-> %d + %d < %d" % (t_lo, t_hi, t_all))

        # (c) 모순 범위(min > max)는 빈 결과여야 한다 — 조건이 OR로 잘못 묶이면 여기서 드러난다.
        #
        # 처음에는 float 컬럼(bid_rate)에 `max = bound`를 넘겨 "모순"이라고 불렀는데
        # min==max는 모순이 아니라 정확일치다 — 293건이 나온 것이 옳은 동작이었다(테스트 결함).
        # 타입에 맞는 실제 모순값을 만든다.
        gap = 1 if isinstance(bound, int) else 0.01
        contradictory = total(**{min_key: bound, max_key: bound - gap})
        check("%s: min>max 모순 범위는 결과가 없다" % field, contradictory == 0,
              "-> %d건 (조건이 AND가 아니라 OR로 묶였을 수 있다)" % contradictory)

    # court_name / status: 부분일치(LIKE) 필터
    sample = items(size=1)
    if sample:
        court = sample[0]["court_name"]
        rows = items(size=100, court_name=court)
        # ★ 먼저 **구분력**을 본다. 검색 대상을 실제 행에서 뽑았으므로 최소 1건은 나와야 한다.
        #   이 단언이 없으면 필터가 엉뚱한 컬럼에 걸려 0건이 나올 때 아래 "모든 행이 조건을
        #   만족한다"가 **공허하게 통과**한다(변이 시험에서 실제로 그렇게 통과했다 — Sprint 78).
        check("court_name 필터에 구분력이 있다(0건이면 검사가 무의미)", len(rows) > 0,
              "-> 0건. 필터가 다른 컬럼에 걸렸을 수 있다(court=%r)" % court)
        bad = [it for it in rows if court not in (it["court_name"] or "")]
        check("court_name 필터가 실제로 그 법원만 돌려준다(%d건)" % len(rows), not bad,
              "-> 위반 %d건" % len(bad))
        check("court_name 오타는 빈 결과(200)", total(court_name="없는법원명XYZ") == 0)

        st = sample[0]["status"]
        if st:
            rows = items(size=100, status=st)
            check("status 필터에 구분력이 있다(0건이면 검사가 무의미)", len(rows) > 0,
                  "-> 0건 (status=%r)" % st)
            bad = [it for it in rows if st not in (it["status"] or "")]
            check("status 필터가 실제로 그 상태만 돌려준다(%d건)" % len(rows), not bad,
                  "-> 위반 %d건" % len(bad))
    else:
        check("court_name/status 필터 - 데이터 없음(검증 생략)", True)

    # auction_date_to: 상한 필터. auction_date_from과 함께 쓰면 구간이 된다.
    dates = sorted(it["auction_date"] for it in items(size=100) if it.get("auction_date"))
    if dates:
        mid = dates[len(dates) // 2]
        rows = items(size=100, auction_date_to=mid)
        bad = [it for it in rows if it.get("auction_date") and it["auction_date"] > mid]
        check("auction_date_to 이후 물건은 제외된다(%d건)" % len(rows), not bad,
              "-> 위반 %d건, 예: %r" % (len(bad), bad[0].get("auction_date") if bad else None))
        # 구간 지정: from == to 면 그 날짜만 남아야 한다.
        exact = items(size=100, auction_date_from=mid, auction_date_to=mid)
        bad = [it for it in exact if it.get("auction_date") != mid]
        check("auction_date_from==to 는 그 날짜만(%d건)" % len(exact), not bad,
              "-> 위반 %d건" % len(bad))
    else:
        check("auction_date_to 필터 - 데이터 없음(검증 생략)", True)

    # --- 6. 프론트가 보내지만 백엔드가 읽지 않는 필터 (2026-08-13 Sprint 85) ----
    #
    # `src/app/search/SearchForm.tsx`는 면적/특수조건 입력값을 쿼리에 실어 보내는데,
    # `auction_item`에 대응 컬럼이 없어 백엔드가 **읽지 않는다**(소스에 TODO로 표시돼 있다).
    # 2026-08-13 실측: 극단값(min_land_area=9999)을 줘도 결과 건수가 그대로다.
    # 사용자에게는 "면적으로 걸렀다"고 보이지만 실제로는 걸러지지 않는다.
    #
    # 구현은 컬럼 추가(스키마 변경) + 크롤러 추출이 필요해 승인 사항이므로 여기서 하지 않는다.
    # 대신 **양방향 드리프트 가드**를 둔다.
    #   - 지금 무시된다는 사실을 고정한다(대조군으로 지원되는 필터가 실제로 걸리는지 함께 본다 ―
    #     대조군이 없으면 "무시된다"가 "필터가 전부 안 걸린다"와 구별되지 않는다).
    #   - 400/422로 깨지지 않는 것도 함께 고정한다. 프론트가 이미 보내고 있으므로, 백엔드가
    #     unknown 파라미터를 거부하도록 바뀌면 **검색 자체가 죽는다**.
    #   - 백엔드에 그 이름이 생기면(구현되면) 이 검사가 실패한다 ― 프론트 TODO를 정리하고
    #     기대값을 옮기라는 신호다. 조용히 어긋난 상태로 남지 않게 한다.
    UNSUPPORTED = ("min_building_area", "max_building_area", "min_land_area", "max_land_area",
                   "special_conditions")
    baseline = total(sido="서울")
    check("대조군: 기준 검색이 0건이 아니다(검사가 공허하지 않다)", baseline > 0,
          "-> baseline=%d" % baseline)
    for name in UNSUPPORTED:
        # 이 값이 반영된다면 결과는 0건이 되어야 하는 극단값을 넣는다.
        value = "유치권" if name == "special_conditions" else (9999999 if name.startswith("min") else 1)
        got = total(sido="서울", **{name: value})
        check("%s는 무시된다(건수 불변 %d)" % (name, baseline), got == baseline,
              "-> %d != %d (구현됐다면 프론트 TODO와 이 검사를 함께 정리할 것)" % (got, baseline))

    # 대조군: 지원되는 상한/하한 필터는 실제로 결과를 줄인다.
    check("대조군: 지원되는 필터(min_appraisal)는 실제로 걸린다",
          total(sido="서울", min_appraisal=10 ** 15) == 0)

    # 소스 레벨 확인 ― 백엔드는 그 이름을 아예 모르고, 프론트는 미지원임을 표시해 둔다.
    api_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "api", "v1", "search.py"), encoding="utf-8-sig").read()
    leaked = [n for n in UNSUPPORTED if n in api_src]
    check("백엔드 search.py에는 아직 그 파라미터가 없다", not leaked, "-> %r" % (leaked,))

    form_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "src", "app", "search", "SearchForm.tsx")
    if os.path.exists(form_path):
        form_src = open(form_path, encoding="utf-8-sig").read()
        check("프론트에 미지원 표시(TODO)가 남아 있다", "TODO(API 미지원)" in form_src)
        unmarked = [n for n in UNSUPPORTED if n not in form_src]
        # 프론트가 더 이상 보내지 않게 되면 이 목록 자체를 줄여야 한다 ― 그 사실도 알려준다.
        check("프론트가 여전히 그 파라미터를 보낸다(목록이 최신이다)", not unmarked,
              "-> 더 이상 보내지 않는 것: %r" % (unmarked,))
    else:
        check("SearchForm.tsx 경로 확인", False, "-> 경로가 바뀌었다: %s" % form_path)

    print()
    if FAILURES:
        print(f"{len(FAILURES)}건 실패: {FAILURES}")
        return 1
    print(f"전체 {PASS}건 통과")
    return 0


if __name__ == "__main__":
    sys.exit(run())
