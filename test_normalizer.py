"""
normalizer.normalize_address() 단위 테스트.

배경: 고양시/성남시/수원시 등 "일반구"를 둔 시는 기존 정규식이 구(區) 단위를
누락시켜, sigungu LIKE 검색에서 "일산동구" 같은 구 단위 검색이 영구히 0건이
되는 버그가 있었다 (Sprint: Search Upgrade Phase 1). 이 파일은 그 수정의
회귀 방지 테스트다. DB/storage 의존성이 전혀 없는 순수 함수 테스트이므로
개발환경(노트북)에서도 100% 실행 가능하다.

실행: python test_normalizer.py
"""
import sys
import io
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from normalizer.normalizer import (
    normalize_address, extract_sido,
    normalize_price, normalize_date, normalize_case_no,
    extract_areas, address_without_brackets,
)


CASES = [
    # (설명, 입력주소, 기대 sido, 기대 sigungu, 기대 dong)

    # --- 일반구를 둔 시: 이번 수정으로 고쳐진 케이스 ---
    ("고양시 일산동구", "경기도 고양시 일산동구 마두동 123-4", "경기", "고양시 일산동구", "마두동"),
    ("성남시 분당구", "경기도 성남시 분당구 정자동 100번지", "경기", "성남시 분당구", "정자동"),
    ("수원시 영통구", "경기도 수원시 영통구 매탄동 55-1", "경기", "수원시 영통구", "매탄동"),
    ("안양시 동안구", "경기도 안양시 동안구 관양동 300", "경기", "안양시 동안구", "관양동"),
    ("청주시 흥덕구", "충청북도 청주시 흥덕구 복대동 300", "충북", "청주시 흥덕구", "복대동"),
    ("포항시 남구", "경상북도 포항시 남구 대잠동 12", "경북", "포항시 남구", "대잠동"),
    ("전주시 완산구", "전라북도 전주시 완산구 효자동 50", "전북", "전주시 완산구", "효자동"),
    ("창원시 성산구", "경상남도 창원시 성산구 상남동 10", "경남", "창원시 성산구", "상남동"),

    # --- 회귀 방지: 기존에 정상이던 단일 레벨 구 (광역시 산하 자치구) ---
    ("서울 강남구 (회귀)", "서울특별시 강남구 역삼동 736-1", "서울", "강남구", "역삼동"),
    ("부산 해운대구 (회귀)", "부산광역시 해운대구 우동 1234", "부산", "해운대구", "우동"),

    # --- 회귀 방지: 구가 없는 군/읍 지역 (오탐 없어야 함) ---
    ("인천 강화군 (구 없음)", "인천광역시 강화군 불은면 신현리 100", "인천", "강화군", "불은면"),
    ("화성시 봉담읍 (구 없음)", "경기도 화성시 봉담읍 와우리 123", "경기", "화성시", "봉담읍"),

    # --- Sprint 3 STEP1: 도로명주소 + 괄호 안 법정동(콤마 바로 뒤따름) 케이스 ---
    # 실제 auction_item.full_address 샘플 기반 (콤마 뒤 lookahead 실패로 dong이
    # 빈 값이 되던 버그의 회귀 방지 테스트).
    ("송파구 문정동 (콤마, 공백없음)",
     "서울특별시 송파구 법원로4길 5 지2층비202호 (문정동,송파법조타운푸르지오시티) [집합건물 철근콘크리트구조 49.06㎡]",
     "서울", "송파구", "문정동"),
    ("양천구 신월동 (콤마+공백)",
     "서울특별시 양천구 남부순환로59길 7 제3층 제302호 (신월동, 토브하우스) [집합건물 철근콘크리트구조 29.06㎡]",
     "서울", "양천구", "신월동"),
    ("금천구 가산동 (콤마+공백)",
     "서울특별시 금천구 가산디지털1로 100 제9층 제908호 (가산동, 에이스골드타워) [집합건물 철근콘크리트구조 88.09㎡]",
     "서울", "금천구", "가산동"),

    # --- Sprint 4 STEP6: 괄호 앞 "건물동 라벨"/고유명사 오탐 회귀 방지 ---
    # 실제 auction_item.full_address 샘플 기반. 괄호 이전에 "OO동/리"로 끝나는
    # 건물동 표기나 고유명사가 있어도, 괄호 안 법정동을 우선해야 한다.
    ("송파구 오금동 (건물동 '에이동' 오탐 방지)",
     "서울특별시 송파구 동남로29길 4 에이동 2층204호 (오금동,센트럴오금) [집합건물 철근콘크리트조 92.48㎡]",
     "서울", "송파구", "오금동"),
    ("은평구 응암동 (건물동 '비동' 오탐 방지)",
     "서울특별시 은평구 은평로13길 12-12 비동 8층802호 (응암동,에스엠벨리체) [집합건물 철근콘크리트구조 25.59㎡]",
     "서울", "은평구", "응암동"),
    ("부천시 고강동 (건물동 '마동' 오탐 방지)",
     "경기도 부천시 오정구 지양로158번길 75-1 마동 지층 1호 (고강동, 성원빌라) [집합건물 벽돌조 40.98㎡]",
     "경기", "부천시 오정구", "고강동"),
    ("남양주시 별내동 (건물동 '판매시설동' 오탐 방지)",
     "경기도 남양주시 별내1로 6 판매시설동 2층205호 (별내동,힐스테이트별내역) [집합건물 철근콘크리트구조 64.9172㎡]",
     "경기", "남양주시", "별내동"),
    ("울산 중구 성남동 (고유명사 '젊음의거리' 오탐 방지 - 건물동 라벨이 아닌 일반 명칭 사례)",
     "울산광역시 중구 젊음의거리 20 3층301호 (성남동,울산호텔리버사이드) [집합건물 철근콘크리트구조 30.51㎡]",
     "울산", "중구", "성남동"),

    # --- 회귀 방지: 괄호가 아예 없는 주소는 기존 폴백 로직이 그대로 동작해야 함 ---
    ("괄호 없는 주소 (기존 폴백 로직 유지 확인)",
     "경기도 고양시 일산동구 마두동 123-4",
     "경기", "고양시 일산동구", "마두동"),

    # --- Bug Fix: 시도 축약형("-시")이 SIDO_PREFIXES 누락으로 sigungu로 오인식되던
    # 문제의 회귀 방지. 접두어가 안 지워지면 "서울시" 자체가 시군구 정규식에 매치되어
    # sigungu="서울시"가 되던 버그였다. ---
    ("시도 축약형 단독 (서울시)", "서울시", "서울", "", ""),
    ("시도 축약형 + 시군구 + 동 (서울시 송파구 오금동)",
     "서울시 송파구 오금동", "서울", "송파구", "오금동"),
    ("시도 축약형 + 시군구 (인천시 서구)", "인천시 서구", "인천", "서구", ""),
    ("시도 축약형 + 시군구 (부산시 해운대구)", "부산시 해운대구", "부산", "해운대구", ""),
    ("시도 축약형 단독, 시군구 계층 없음 (세종시)", "세종시", "세종", "", ""),
]


# ---------------------------------------------------------------------------
# 크롤 문자열 -> DB 값 변환 (2026-08-13 Sprint 75 신설)
#
# `normalize_price` / `normalize_date` / `normalize_case_no`는 **크롤한 원문을 DB에 들어갈
# 값으로 바꾸는 마지막 관문**인데 검사가 0건이었다. 이 파일은 주소만 보고 있었다.
#
# 여기서 중요한 것은 "정상 입력이 잘 변환되는가"보다 **깨진 입력이 어떻게 되는가**다.
# 법원 사이트 응답이 바뀌거나 잘리면 그대로 이 함수들로 들어온다.
#
# 현재 동작을 실측해 그대로 고정한다(규칙을 새로 정하지 않는다). 그중 둘은
# **잠재 위험이므로 명시적으로 못박아 둔다**:
#
#   (1) normalize_date는 파싱하지 못한 값을 **원문 그대로 통과**시킨다.
#       `2026-8-19`(한 자리 월)처럼 형식이 다른 값이 그대로 DB에 들어가면, 이 저장소가
#       날짜를 **문자열로 비교**하기 때문에 정렬·D7 필터·우선순위가 조용히 어긋난다
#       ('2026-8-19' > '2026-09-01' 이 참이 된다).
#   (2) normalize_price는 숫자를 못 찾으면 **0**을 돌려준다. 크롤이 깨진 것과
#       "실제로 0원"이 구분되지 않는다.
#
# 실측(2026-08-13): 실제 데이터에는 두 경우 모두 **0건**이다
# (auction_item/auction/document_queue의 auction_date 형식 위반 0건, 가격 0원 0건).
# 즉 지금 피해는 없고, 이 검사는 그 전제가 깨지는 순간을 잡기 위한 것이다.
# ---------------------------------------------------------------------------
PRICE_CASES = [
    # (입력, 기대값, 설명)
    ("1,234,000원", 1234000, "콤마와 단위를 제거한다"),
    ("1,234,000", 1234000, "콤마만 있는 형태"),
    ("500000000원(100%)", 500000000, "괄호 이후는 버린다(최저가율 표기)"),
    ("감정가 500,000,000 (70%)", 500000000, "앞에 라벨이 붙어도 숫자만 취한다"),
    ("  12,000  ", 12000, "앞뒤 공백"),
    ("0", 0, "실제 0원"),
    ("-", 0, "미표기(-)는 0"),
    ("", 0, "빈 문자열은 0"),
    (None, 0, "None도 0 (크롤 누락 시 예외를 내지 않는다)"),
    ("abc", 0, "숫자가 없으면 0 -- 깨진 입력과 실제 0원이 구분되지 않는다(잠재 위험)"),
    ("(1,000)", 0, "여는 괄호로 시작하면 앞부분이 비어 0"),
]

DATE_CASES = [
    ("2026-08-19", "2026-08-19", "이미 정규 형식"),
    ("2026.08.19", "2026-08-19", "점 구분자"),
    ("2026/08/19", "2026-08-19", "슬래시 구분자"),
    ("2026-08-19 10:00", "2026-08-19", "시각이 붙어도 날짜만"),
    ("매각기일 2026.08.19(수)", "2026-08-19", "라벨과 요일이 붙어도 추출한다"),
    ("-", "", "미표기(-)는 빈 문자열"),
    ("", "", "빈 문자열"),
    (None, "", "None도 빈 문자열 (예외를 내지 않는다)"),
    # 아래 두 개가 잠재 위험이다 -- 파싱 실패인데 원문이 그대로 남는다.
    ("2026-8-19", "2026-8-19", "한 자리 월은 정규화되지 않고 원문 통과(잠재 위험)"),
    ("20260819", "20260819", "구분자가 없으면 원문 통과(잠재 위험)"),
    ("abc", "abc", "날짜가 아니어도 원문 통과(잠재 위험)"),
]


def run_value_normalizers():
    failures = []
    print()
    print("--- normalize_price ---")
    for raw, expected, desc in PRICE_CASES:
        got = normalize_price(raw)
        ok = got == expected
        print("[%s] %-46s %r -> %r" % ("PASS" if ok else "FAIL", desc, raw, got))
        if not ok:
            failures.append("normalize_price(%r)" % (raw,))
            print("     expected %r" % (expected,))

    print()
    print("--- normalize_date ---")
    for raw, expected, desc in DATE_CASES:
        got = normalize_date(raw)
        ok = got == expected
        print("[%s] %-46s %r -> %r" % ("PASS" if ok else "FAIL", desc, raw, got))
        if not ok:
            failures.append("normalize_date(%r)" % (raw,))
            print("     expected %r" % (expected,))

    # 정규 형식으로 나온 값은 **문자열 비교로 정렬 가능**해야 한다.
    # 이 저장소는 날짜를 문자열로 비교한다(D7 필터, 우선순위, doc_worker의 기일 판정).
    ordered = [normalize_date(d) for d in ("2026.01.05", "2026.02.01", "2026.10.01", "2026.12.31")]
    ok = ordered == sorted(ordered)
    print("[%s] 정규화된 날짜는 문자열 정렬이 시간순과 같다: %r" % ("PASS" if ok else "FAIL", ordered))
    if not ok:
        failures.append("date string ordering")

    # 반대로 정규화되지 못한 값이 섞이면 정렬이 깨진다 -- 위험을 사실로 못박아 둔다.
    broken = normalize_date("2026-8-19")
    ok = broken > "2026-09-01"
    print("[%s] 미정규화 값은 문자열 비교를 깨뜨린다(%r > '2026-09-01' 이 참): %r"
          % ("PASS" if ok else "FAIL", broken, ok))
    if not ok:
        failures.append("unnormalized date ordering hazard")

    print()
    print("--- normalize_case_no ---")
    for raw, expected in (("  2024타경1234 ", "2024타경1234"),
                          ("2024타경1234", "2024타경1234"),
                          ("", "")):
        got = normalize_case_no(raw)
        ok = got == expected
        print("[%s] %r -> %r" % ("PASS" if ok else "FAIL", raw, got))
        if not ok:
            failures.append("normalize_case_no(%r)" % (raw,))

    # None은 예외가 난다. price/date와 달리 방어가 없다 -- 현재 동작을 명시적으로 고정한다.
    # (실측: auction/auction_item의 case_no 빈 값 0건이라 지금 도달하지 않는다)
    raised = False
    try:
        normalize_case_no(None)
    except AttributeError:
        raised = True
    print("[%s] None은 AttributeError (price/date와 달리 방어가 없다 -- 현재 동작)"
          % ("PASS" if raised else "FAIL"))
    if not raised:
        failures.append("normalize_case_no(None) 동작 변경")

    return failures



def run_batch_isolation():
    """`normalize_batch()`의 행 단위 실패 격리 (2026-08-13 Sprint 78 신설).

    커버리지로 찾은 미검증 경로다(`normalizer/normalizer.py` 144-150).
    `upsert_batch()`와 **같은 계약**이다 — 매일 06:00 크롤러가 법원 60곳에서 모은 수백 건을
    한 번에 정규화하는데, 그중 한 건이 기형이면 나머지가 함께 사라지면 안 된다(FR-101).

    격리가 사라지면 피해가 크다: 정규화가 파이프라인의 **첫 단계**라, 여기서 배치가 죽으면
    `upsert_batch`/`enqueue_documents`가 아예 호출되지 않아 **그날 수집이 통째로 0건**이 된다.
    (실제로 mvp_scraper는 `rows`가 비면 "적재를 건너뜁니다" 경고만 남기고 성공으로 끝낸다.)
    """
    from normalizer.normalizer import normalize_batch
    from models.auction_item import AuctionItem

    failures = []

    def good(case_no):
        return AuctionItem(
            case_no=case_no, item_no="1", address="서울특별시 강남구 역삼동 736-1",
            property_type="아파트", appraisal_price="100,000,000",
            minimum_bid_price="80,000,000", auction_date="2026.09.01",
            status="유찰", court_code="서울중앙지방법원", court_name="서울중앙지방법원",
            crawl_date="2026-08-13",
        )

    # 기형 행: address가 None이면 normalize_address 안에서 예외가 난다.
    broken = good("BROKEN")
    broken.address = None

    # 격리가 사라지면 이 호출이 그대로 던진다 -> 크래시로 중단되면 남은 검사가 실행되지
    # 않는다(변이 시험에서 확인). 예외를 FAIL로 바꿔 원인과 범위를 함께 보게 한다.
    try:
        rows = normalize_batch([good("A"), broken, good("B")])
    except Exception as exc:
        print("[FAIL] normalize_batch: 기형 행이 배치 전체를 죽였다 -> %r" % (exc,))
        failures.append("normalize_batch 행 단위 격리")
        rows = []
    ok = len(rows) == 2
    print("[%s] normalize_batch: 기형 행 하나가 배치를 죽이지 않는다 (정상 %d/2건)"
          % ("PASS" if ok else "FAIL", len(rows)))
    if not ok:
        failures.append("normalize_batch 행 단위 격리")

    got = [r["case_no"] for r in rows]
    ok = got == ["A", "B"]
    print("[%s] normalize_batch: 앞뒤 정상 행이 순서대로 살아남는다 (%r)"
          % ("PASS" if ok else "FAIL", got))
    if not ok:
        failures.append("normalize_batch 정상 행 보존")

    ok = all(r["case_no"] != "BROKEN" for r in rows)
    print("[%s] normalize_batch: 기형 행은 결과에 섞이지 않는다" % ("PASS" if ok else "FAIL"))
    if not ok:
        failures.append("normalize_batch 기형 행 제외")

    # 전부 기형이면 빈 리스트 — 예외로 죽지 않는다(호출부가 "수집 0건"으로 판단해 경고를 남긴다).
    b2 = good("B2"); b2.address = None
    try:
        rows = normalize_batch([broken, b2])
        ok = rows == []
        print("[%s] normalize_batch: 전부 기형이면 빈 리스트(예외 아님)" % ("PASS" if ok else "FAIL"))
        if not ok:
            failures.append("normalize_batch 전량 실패 처리")
    except Exception as exc:
        print("[FAIL] normalize_batch: 전부 기형일 때 예외가 올라왔다 -> %r" % (exc,))
        failures.append("normalize_batch 전량 실패 처리")

    # 빈 입력도 안전해야 한다(크롤이 0건을 돌려준 날).
    ok = normalize_batch([]) == []
    print("[%s] normalize_batch: 빈 입력은 빈 결과" % ("PASS" if ok else "FAIL"))
    if not ok:
        failures.append("normalize_batch 빈 입력")

    return failures


# ---------------------------------------------------------------------------
# 지역 분류: 가장 앞에 나오는 표기가 이긴다 (2026-08-13 Sprint 78 신설)
#
# 예전 `extract_sido()`는 SIDO_PATTERNS를 **딕셔너리 선언 순서**로 훑어 처음 발견된 것을
# 돌려줬다. 즉 판정이 문자열 안의 위치가 아니라 사전의 줄 순서로 정해졌다.
# 주소는 시도로 시작하는데도 뒤쪽에 다른 지역명이 섞이면 그쪽이 이겼다.
#
# 실측(auction_item 1,876건) 결과 4건이 잘못 분류돼 있었고, 원인이 전부 다르다.
#
#     경기도 시흥시 서울대학로 59-21              -> 서울   도로명 (실재하는 도로다)
#     경상남도 양산시 물금읍 부산대학로 150         -> 부산   도로명 (실재하는 도로다)
#     인천광역시 계양구 ... (효성동, 뉴서울아파트)   -> 서울   건물명
#     제주특별자치도 제주시 ... 주식회사 뉴세종하우징 -> 세종   공유자(법인) 이름
#
# 마지막 건이 결함의 성격을 가장 잘 보여준다. "제주특별자치도"가 **0번 위치**에 있는데
# **539번 위치**의 "세종"에게 졌다. 오직 사전에서 세종이 제주보다 위라는 이유였다.
#
# `sido`는 검색의 1차 필터다. 잘못 분류된 물건은 제 지역에서 검색되지 않고 남의 지역을
# 오염시킨다. 도로명 사례는 실재하는 이름이라 **반드시 재발한다**.
#
# 수정 후 전수 재계산: 1,876건 중 **정확히 이 4건만** 바뀌었다(나머지 무변동).
# ---------------------------------------------------------------------------
SIDO_POSITION_CASES = [
    # (설명, 입력, 기대 시도)
    ("도로명에 다른 지역명(서울대학로)", "경기도 시흥시 서울대학로 59-21 1층189호", "경기"),
    ("도로명에 다른 지역명(부산대학로)", "경상남도 양산시 물금읍 부산대학로 150 3층304호", "경남"),
    ("건물명에 다른 지역명(뉴서울아파트)",
     "사용본거지 : 인천광역시 계양구 새벌로 88 303동 106호 (효성동, 뉴서울아파트)", "인천"),
    ("공유자 이름에 다른 지역명(뉴세종하우징)",
     "제주특별자치도 제주시 구좌읍 세화리 산29 [토지 임야 93124㎡ "
     "130번 주식회사 뉴세종하우징 지분]", "제주"),
    # 정상 주소는 그대로여야 한다.
    ("정식 명칭 접두어", "서울특별시 강남구 역삼동 736-1", "서울"),
    ("도 단위 접두어", "충청남도 논산시 은진면 시묘리 499-1", "충남"),
    ("특별자치도", "전북특별자치도 군산시 사정동 401-1", "전북"),
    # 지역명이 앞에 오지 않는 입력(사용자 검색어 등)은 기존처럼 동작해야 한다.
    ("축약형 검색어", "서울 강남구", "서울"),
    ("지역명 없음", "강남구 아파트", ""),
    ("빈 입력", "", ""),
]


def run_sido_position():
    failures = []
    print()
    print("--- extract_sido: 가장 앞선 표기가 이긴다 ---")
    for desc, text, expected in SIDO_POSITION_CASES:
        got = extract_sido(text)
        ok = got == expected
        print("[%s] %-38s -> %r" % ("PASS" if ok else "FAIL", desc, got))
        if not ok:
            failures.append(desc)
            print("     입력: %s" % text[:70])
            print("     expected %r" % (expected,))

    # 위치가 같으면 더 긴(구체적인) 표기를 택한다.
    ok = extract_sido("서울특별시") == "서울"
    print("[%s] 같은 위치면 더 긴 표기 우선" % ("PASS" if ok else "FAIL"))
    if not ok:
        failures.append("longest variant at same position")

    # 순서가 뒤집혀도 결과가 같아야 한다 - 판정이 사전 순서에 의존하지 않는다는 증거다.
    # (예전 구현은 이 검사에서 반드시 실패한다)
    import normalizer.normalizer as nm
    original = nm.SIDO_PATTERNS
    try:
        nm.SIDO_PATTERNS = dict(reversed(list(original.items())))
        reversed_result = extract_sido("경기도 시흥시 서울대학로 59-21")
    finally:
        nm.SIDO_PATTERNS = original
    ok = reversed_result == "경기"
    print("[%s] 사전 순서를 뒤집어도 결과가 같다: %r" % ("PASS" if ok else "FAIL", reversed_result))
    if not ok:
        failures.append("dict-order independence")

    # validator가 같은 함수를 쓴다 - 판정이 두 벌이면 한쪽만 고쳐질 수 있다.
    from validator.validation_engine import extract_sido as validator_extract_sido
    ok = validator_extract_sido is extract_sido
    print("[%s] validator가 같은 함수를 재사용한다(중복 판정 없음)" % ("PASS" if ok else "FAIL"))
    if not ok:
        failures.append("validator uses its own copy")

    return failures


# ---------------------------------------------------------------------------
# 주소 끝 대괄호는 **면적 데이터의 유일한 소재지**다 (2026-08-18 Sprint 203 신설)
#
# 법원 목록의 소재지 칸은 주소 뒤에 물건 표시를 대괄호로 붙여 준다.
#
#     서울특별시 종로구 성균관로7길 37(명륜3가) 2층202호 [집합건물 철근콘크리트구조 29.95㎡]
#     서울특별시 종로구 평창동 445-1 [토지 대 420㎡]
#
# `normalize_address()` 는 이 문자열을 **그대로** `full_address` 로 넘긴다. 의도해서
# 보존한 것이 아니라 손대지 않아서 남아 있는 것에 가깝다. 그런데 실측 결과
# **auction_item 1,876행 중 1,852행(98.7%)의 면적이 오직 여기에만 있다** —
# 스키마에 면적 컬럼이 없고, 크롤러의 `property_list`(목록내역)는
# `normalize_item()` 에서 통째로 버려지기 때문이다(Sprint 203 감사).
#
# 즉 누군가 "주소를 깔끔하게" 만들려고 대괄호를 떼는 순간, 이 저장소에서 면적은
# **완전히 사라진다.** 오류도 빈 값도 아니고 주소가 예뻐질 뿐이라 알아챌 방법이 없다.
# 그래서 여기에 못을 박는다. 면적 필터를 만들자는 이야기가 아니라, 이미 갖고 있는
# 데이터를 조용히 잃지 않겠다는 것이다.
#
# 두 번째 검사(지번)는 실제 오작동 가능성이 있는 자리다. `lot_number` 정규식은
# `(?=\s|$|\[)` 로 대괄호 앞에서 멈추는데, 이 lookahead 가 빠지면
# `[토지 대 420㎡]` 의 **420 을 지번으로 집어간다.**
# ---------------------------------------------------------------------------
BRACKET_CASES = [
    # (설명, 원본 주소, 기대 지번 = **실측한 현재 동작**)
    #
    # 지번 기대값은 "이래야 옳다"가 아니라 **지금 이렇게 나온다**를 고정한 것이다.
    # 첫 사례가 빈 문자열인 것은 도로명주소("...로7길 37(명륜3가)")에서 숫자 뒤에
    # 곧바로 괄호가 오면 lookahead 가 안 맞기 때문이다 - 별개의 사안이라 여기서
    # 판단하지 않는다. 이 검사가 지키려는 것은 하나다:
    # **대괄호 안의 숫자(면적/연식)가 지번으로 새어 나오지 않는다.**
    ("집합건물 + 전유면적",
     "서울특별시 종로구 성균관로7길 37(명륜3가) 2층202호 [집합건물 철근콘크리트구조 29.95\u33a1]",
     ""),
    ("토지 + 지목/면적",
     "서울특별시 종로구 평창동 445-1 [토지 대 420\u33a1]",
     "445-1"),
    ("다층 건물 (면적이 여러 개)",
     "서울특별시 중구 신당동 217-91 [건물 철근콘크리트구조 4\uce35 \ub2e4\uac00\uad6c\uc8fc\ud0dd 1\uce35 13.23\u33a1 2\uce35 164.7\u33a1]",
     "217-91"),
    ("차량 (면적 개념이 없다)",
     "\uc0ac\uc6a9\ubcf8\uac70\uc9c0 : \uc778\ucc9c \ub0a8\ub3d9\uad6c \uc778\uc8fc\ub300\ub85c676\ubc88\uae38 19 2\ub3d9 406\ud638 [\uce74\ub2c8\ubc1c 2020\ub144\uc2dd \uc2b9\uc6a9\ucc28]",
     "19"),
]


def run_bracket_preservation():
    """주소 끝 대괄호(면적의 유일한 소재지)가 그대로 살아남는가."""
    failures = []
    print()
    print("--- 주소 끝 대괄호 보존 (Sprint 203) ---")

    for name, addr, exp_lot in BRACKET_CASES:
        result = normalize_address(addr)
        # 1) full_address 는 입력과 **글자 하나까지 같아야** 한다.
        same = result["full_address"] == addr
        print("[%s] %s: full_address 무손실" % ("PASS" if same else "FAIL", name))
        if not same:
            failures.append("full_address 무손실: " + name)
            print("    got      %r" % (result["full_address"],))
            print("    expected %r" % (addr,))

        # 2) 대괄호가 살아 있고 그 안의 문자열도 그대로여야 한다.
        opened = addr[addr.rfind("["):] if "[" in addr else ""
        kept = bool(opened) and opened in result["full_address"]
        print("[%s] %s: 대괄호 내용 보존" % ("PASS" if kept else "FAIL", name))
        if not kept:
            failures.append("대괄호 보존: " + name)

        # 3) 대괄호 안의 숫자가 지번으로 새어 나오면 안 된다.
        #    실측 고정 + "대괄호 안에서 나온 값이 아니다"를 함께 본다. 후자가 본론이고,
        #    전자는 지번 규칙이 조용히 바뀌는 것을 알아채기 위한 것이다.
        inner = addr[addr.rfind("[") + 1:-1] if "[" in addr else ""
        lot = result["lot_number"]
        leaked = bool(lot) and lot in inner
        lot_ok = (lot == exp_lot) and not leaked
        print("[%s] %s: 지번이 대괄호 숫자가 아니다 (%r)"
              % ("PASS" if lot_ok else "FAIL", name, lot))
        if not lot_ok:
            failures.append("지번 오염: " + name)
            print("    expected %r / 대괄호에서 샜는가=%s" % (exp_lot, leaked))

    return failures


# ---------------------------------------------------------------------------
# extract_areas() — 주소 원문에서 건물/토지 면적 뽑기 (2026-08-26 신설)
#
# 왜 순수 함수 테스트인가: 이 함수의 출력이 곧 `auction_item.building_area` /
# `land_area` 가 되고, 그 컬럼이 검색 필터의 근거가 된다. 즉 여기가 틀리면
# **사용자가 면적으로 거른 결과가 조용히 틀린다.** DB 없이 고정할 수 있는 계약이다.
#
# 표본은 전부 실데이터에서 온 모양이다(2026-08-26, auction_item 2,444행 실측).
# ---------------------------------------------------------------------------
AREA_CASES = [
    # (주소, 기대 building, 기대 land, 설명)
    ("서울특별시 관악구 난곡로66가길 19 2층202호 [집합건물 철근콘크리트구조 17.08㎡]",
     17.08, None, "집합건물 단일 면적"),
    ("서울특별시 종로구 평창동 445-1 [토지 대 420㎡]",
     None, 420.0, "토지 단일 면적"),
    ("경상북도 포항시 북구 죽장면 월평리 690 [토지 임야 15446㎡]",
     None, 15446.0, "임야"),
    ("인천광역시 서구 건지로249번길 14 [건물 벽돌조 2층 1층 75.60㎡(소매점) 2층 70.20㎡(주택)]",
     145.8, None, "다층 건물은 층 면적을 **합**한다(연면적)"),
    ("경상북도 [토지 전[현황:묵전(죽림)] 105㎡]",
     None, 105.0, "대괄호가 한 겹 더 있어도 통째로 집는다"),
    ("경상북도 포항시 북구 죽장면 월평리 690 [토지 전 1048평]",
     None, round(1048 * 3.3057851, 4), "평은 ㎡로 환산한다"),
    ("충청북도 [토지 대 1,048㎡]",
     None, 1048.0, "쉼표가 섞인 표기"),
    ("사용본거지 : 인천 남동구 [카니발 2016년식 승용차]",
     None, None, "차량은 면적 개념이 없다 - 0이 아니라 None"),
    ("소재지 : 인천 남동구 장도로 86-13 논현동 [기타 동력선]",
     None, None, "선박도 마찬가지"),
    ("부산광역시 동래구 [집합건물 철근콘크리트조 74.5482㎡ 대지권의 표시 토지의 표시 : "
     "부산광역시 동래구 안락동 308 대 500㎡ 대지권 비율 : 500분의 21.7849]",
     74.5482, None,
     "★ 대지권의 500㎡는 **필지 전체**다. 이 물건의 몫은 비율(21.78/500)이므로 "
     "그대로 쓰면 23배 부풀려진다 - 토지는 None으로 둔다"),
    ("", None, None, "빈 문자열"),
    ("대괄호가 없는 주소 123-4", None, None, "대괄호가 없으면 아무것도 못 뽑는다"),
    ("서울 [집합건물 구조만 있고 면적이 없다]", None, None, "면적 표기가 없으면 None"),

    # ── 평/홉/작 3단 표기 (2026-08-26, `docs/BUGS.md` #240) ────────────────
    #
    # 옛 등기 표기다. 앞의 층 목록은 **건물 1동 전체**이고 이 물건은 `내 ...` 뒤의
    # 구분 호실이다. 전부 더하면 4.8㎡ 짜리 사무실이 2,509㎡ 가 된다(520배).
    # 대지권에서 이미 내린 판단과 같은 상황이라 같은 답을 쓴다 — 모르는 것으로 둔다.
    ("서울특별시 중구 신당동 217-1 [건물 3층37호 철근콩크리트조평옥개4층점포 및사무실1동 "
     "1층192평6홉9작 2층190평2홉6작 3층188평8홉 4층188평8홉 내3층1평4홉6작]",
     None, None,
     "★ 평/홉/작 3단 표기는 환산하지 않는다 - 1동 전체와 구분호실이 섞여 있다(id=13584)"),
    ("서울특별시 중구 신당동 217-1 [건물 4층가31내 철근콩크리트조 평옥개 4층점포및 사무실 1동 "
     "1층192평6홉9작 2층190평2홉6작 3층188평8홉 4층188평8홉 내 1층192평6홉9작 4층188평8홉 "
     "내 4층가제31호 건평3평3홉2작]",
     None, None,
     "★ 같은 표기, 층 목록이 두 번 반복되는 형태도 None(id=6495)"),
    ("경상북도 [토지 답 538평 채무자 김순향 지분 2분의1 전부]",
     None, round(538 * 3.3057851, 4),
     "홉/작이 없는 단순 평 표기는 그대로 환산한다(위 배제가 과하지 않다)"),

    # ── 천단위 쉼표: 프런트 parseArea 와 **같은 값**을 내야 한다 (BUGS #240) ──
    # 프런트는 `tests/format.test.mjs` 가 같은 입력으로 같은 기대값을 고정한다.
    # 한쪽만 고치면 다른 쪽이 붉어진다.
    ("서울 x [건물 1층 3,005.35㎡ 2층 1,000㎡]", 4005.35, None,
     "쉼표 다층 합산 - 프런트 parseArea 와 동일"),
    ("서울 x [건물 1층 1,000㎡]", 1000.0, None,
     "쉼표 뒤가 0뿐이어도 0이 되지 않는다"),
    ("경기도 평택시 청북읍 드림산단2로 80 (제넨코어센터피동) [건물 일반철골구조 "
     "(철근)콘크리트지붕 공장 지1층 3,005.35㎡ 1층 6,110.75㎡ 2층 5,322.75㎡ "
     "공장 및 광업재단 저당법 제6조 목록 제2022-66호, 제2022-112호]",
     14438.85, None, "실데이터 id=443 - 프런트가 438.85 로 찍던 그 행"),
]


def run_area_extraction():
    failures = []
    for address, want_b, want_l, why in AREA_CASES:
        got = extract_areas(address)
        ok = got["building_area"] == want_b and got["land_area"] == want_l
        print("[%s] %s" % ("PASS" if ok else "FAIL", why))
        if not ok:
            print("       입력: %s" % address[:90])
            print("       기대 building=%s land=%s / 실제 building=%s land=%s"
                  % (want_b, want_l, got["building_area"], got["land_area"]))
            failures.append("extract_areas: %s" % why)

    # 계약: 키는 항상 둘 다 존재한다(호출부가 KeyError를 걱정하지 않아도 된다).
    for probe in ("", "아무거나", "[토지 대 1㎡]"):
        keys = set(extract_areas(probe))
        if keys != {"building_area", "land_area"}:
            failures.append("extract_areas 반환 키가 다르다: %s" % sorted(keys))
            print("[FAIL] 반환 키가 항상 building_area/land_area 여야 한다: %s" % sorted(keys))
    print("[PASS] 반환 키는 언제나 building_area/land_area 둘 다")

    # 0은 None이 아니다 - 실제로 0㎡가 적히면 0.0을 돌려줘야 한다
    # (이 구분이 무너지면 "면적 미상"과 "면적 0"이 뒤섞인다).
    got = extract_areas("서울 [토지 대 0㎡]")
    if got["land_area"] != 0.0:
        failures.append("0㎡를 0.0으로 돌려주지 않는다: %r" % got["land_area"])
        print("[FAIL] 0㎡는 None이 아니라 0.0이어야 한다: %r" % got["land_area"])
    else:
        print("[PASS] 0㎡는 0.0이다(면적 미상 None과 구분된다)")

    return failures


# ---------------------------------------------------------------------------
# 대괄호(물건 표시)는 주소 파싱에서 제외한다 (2026-08-26 신설)
#
# `full_address` 는 "주소 + [물건 표시]" 형태다. 대괄호 안에는 구조·면적·등기부 항목이
# 들어 있고 **주소 성분은 없다.** 그런데 시군구 정규식 `[가-힣]+[구시군]` 이 그 안까지
# 훑어 **"갑구"**(등기부 갑구/을구)를 행정구역으로 집고 있었다.
#
#   실측 (2026-08-26, auction_item):
#     세종특별자치시 전의면 관정리 578-31 [토지 임야 297㎡ 갑구 2번, 3번 ...]
#       -> sigungu='갑구' 로 저장됨. 세종시는 시군구가 없어 정답은 빈 문자열이다.
#     같은 모양 2건이 DB 에 실제로 있었다.
#
# 영향: `sigungu LIKE '%갑구%'` 검색에 엉뚱한 물건이 걸리고, 지역 필터가 조용히 틀린다.
# ---------------------------------------------------------------------------
BRACKET_EXCLUSION_CASES = [
    # (주소, 기대 sigungu, 설명)
    ("세종특별자치시 전의면 관정리 578-31 [토지 임야 297㎡ 갑구 2번, 3번 공유자 주식회사]",
     "", "★ 대괄호 안의 '갑구'(등기부 항목)를 시군구로 읽지 않는다"),
    ("세종특별자치시 장군면 평기리 265-4 [토지 임야 1434㎡ 갑구 7번 양숙정 지분]",
     "", "세종시는 시군구가 없다"),
    ("경기도 고양시 일산동구 고양대로 953-9 205동 4층401호 (식사동,한울하임) [집합건물 철근콘크리트구조]",
     "고양시 일산동구", "일반구는 그대로 '시 구' 로 잡는다(기존 동작 무변경)"),
    ("제주특별자치도 제주시 구좌읍 세화리 산29 [토지 임야 93124㎡ 갑구1번 이정도 지분]",
     "제주시", "대괄호에 '갑구' 가 있어도 주소 쪽 시군구가 이긴다"),
    ("서울특별시 관악구 난곡로66가길 19 2층202호 [집합건물 철근콘크리트구조 17.08㎡]",
     "관악구", "일반적인 구"),
]


def run_bracket_exclusion():
    failures = []
    for address, want, why in BRACKET_EXCLUSION_CASES:
        got = normalize_address(address)
        if got["sigungu"] != want:
            failures.append("bracket: %s" % why)
            print("[FAIL] %s" % why)
            print("       입력: %s" % address[:90])
            print("       기대 sigungu=%r / 실제 %r" % (want, got["sigungu"]))
        else:
            print("[PASS] %s" % why)

        # ★ 원문은 절대 바뀌지 않는다. 대괄호를 떼는 것은 **파싱 입력**에서만이다.
        if got["full_address"] != address:
            failures.append("bracket: full_address 변형 (%s)" % why)
            print("[FAIL] full_address 가 바뀌었다: %r" % got["full_address"][:80])

    # 헬퍼 자체 계약
    check_pairs = [
        ("서울 강남구 1 [집합건물 10㎡]", "["),
        ("경북 [토지 전[현황:묵전(죽림)] 105㎡]", "["),
    ]
    for src, forbidden in check_pairs:
        out = address_without_brackets(src)
        if forbidden in out:
            failures.append("address_without_brackets 가 대괄호를 남겼다: %r" % out)
            print("[FAIL] 대괄호가 남았다: %r" % out)
    print("[PASS] address_without_brackets 가 중첩 대괄호까지 제거한다")

    if address_without_brackets("") != "":
        failures.append("address_without_brackets 빈 입력")
        print("[FAIL] 빈 입력 처리")
    else:
        print("[PASS] 빈 입력은 빈 문자열")

    return failures


def run_normalized_keys_reach_storage():
    """`normalize_item()` 이 만든 키가 실제로 `auction` 에 도달하는가 (2026-09-01 신설).

    ## 왜 — 세 키가 계산돼서 **버려지고 있다**

    `normalize_item()` 은 `has_spec_pdf` / `has_status_pdf` / `has_appraisal_pdf`
    를 출력 dict 에 담는다. 그런데 `UPSERT_SQL` 은 그 자리에 **리터럴 0 을 박아 넣는다**:

        has_spec_pdf, has_status_doc, has_appraisal_pdf, ...
        VALUES (?,?,...,?, 0,0,0, ?,?)

    즉 dict 의 값은 한 번도 쓰이지 않는다. 갱신에서도 `_UPSERT_SET` 에 없어 보존만 된다.
    실제로 이 컬럼을 1 로 만드는 것은 문서 수집 쪽(`LEGACY_HAS_COLUMN`)이다.
    그리고 `AuctionItem` 의 세 필드는 **크롤러가 한 번도 대입하지 않는다**(전부 기본값
    `False`, 2026-09-01 `crawler/` 전수 확인). 즉 죽은 배선이다.

    지금은 무해하지만 **함정**이다. 출력 dict 의 다른 키는 전부 upsert 로 흘러가므로,
    이 셋도 그럴 것처럼 읽힌다. 게다가 `has_status_pdf` 는 **어떤 컬럼과도 이름이 맞지
    않는다** — 컬럼은 Step 9 에 `has_status_doc` 으로 개명됐는데 모델/정규화기만 옛
    이름으로 남았다. 누가 "dict 를 그대로 upsert 에 넘기자"고 고치는 날, 그 필드만
    조용히 사라진다.

    ★ 단, **죽은 것은 모델/정규화기의 세 필드이지 컴럼이 아니다.**
      `auction.has_*` 는 `migrate_execute.py` 가 `document_status` 씨앗으로
      읽는다(아래 (4) 검사). 컬럼을 드롭하면 새로 옮겨진 물건의 문서
      상태가 전부 COLLECTING 으로 시작한다.

    ★ 지우지 않는다. 필드 제거는 `models`/`normalizer` 의 공개 형태를 바꾸는 일이고
      (docs/CLAUDE.md: Mock 함수 시그니처 유지 / 임의 삭제 금지), 지금 고장난 것은
      없다. 대신 **경계를 못박는다** — 도달하지 않는 키가 늘거나 줄면 붉어진다.
    """
    failures = []
    print()
    print("--- normalize_item() 의 키가 auction 에 도달하는가 ---")

    from models.auction_item import AuctionItem
    from normalizer.normalizer import normalize_item
    import storage.database as dbmod

    item = AuctionItem(
        case_no="2026타경1", item_no="1", address="서울특별시 강남구 역삼동 736-1",
        property_type="아파트", appraisal_price="100000000",
        minimum_bid_price="80000000", auction_date="2026-09-30",
        status="유찰 1회", court_code="서울중앙지방법원",
        court_name="서울중앙지방법원", crawl_date="2026-09-01",
    )
    keys = set(normalize_item(item).keys())

    def check(name, got, expected):
        ok = got == expected
        print("[%s] %s: %r" % ("PASS" if ok else "FAIL", name, got))
        if not ok:
            print("     expected %r" % (expected,))
            failures.append(name)

    print("     normalize_item() 키 %d개" % len(keys))
    if len(keys) < 10:
        failures.append("normalize_item 키를 제대로 못 읽었다")
        print("[FAIL] 검사가 공허하다 - 키가 %d개뿐이다" % len(keys))
        return failures

    # (1) `auction` 테이블에 **이름이 아예 없는** 키.
    #     `has_status_pdf` 는 컬럼명이 `has_status_doc` 으로 개명된 잔재다.
    create_sql = dbmod.CREATE_AUCTION_SQL if hasattr(dbmod, "CREATE_AUCTION_SQL") else None
    import re
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "storage", "database.py"), encoding="utf-8-sig").read()
    m = re.search(r"CREATE TABLE IF NOT EXISTS auction\s*\((.*?)\n\s*\)", src, re.S)
    cols = set()
    if m:
        for line in m.group(1).split("\n"):
            mm = re.match(r"\s*([a-z_]+)\s+(INTEGER|TEXT|REAL)", line)
            if mm:
                cols.add(mm.group(1))
    check("전제: auction 컬럼을 실제로 읽었다(개수>10)", len(cols) > 10, True)
    # ★ `filed_date` 가 여기 있는 것은 **결함이 아니다** (2026-09-03).
    #
    #   위 정규식은 `storage/database.py` 의 `CREATE TABLE IF NOT EXISTS auction`
    #   본문만 읽는다. 그런데 `filed_date` 는 그 문장이 아니라
    #   `028_auction_filed_date.sql` 의 `ALTER TABLE ... ADD COLUMN` 이 만든다.
    #
    #   CREATE TABLE 쪽에 옮겨 적으면 **부트스트랩이 깨진다**: 빈 DB 는
    #   init_db -> migrations 순서로 도는데, 028 은 아직 적용 기록이 없어
    #   반드시 실행되고, SQLite 의 ADD COLUMN 에는 IF NOT EXISTS 가 없어
    #   `duplicate column name: filed_date` 로 죽는다. 그래서 두 곳에 적지 않는다.
    #
    #   `has_status_pdf` 와는 성격이 정반대다 — 저쪽은 **어떤 컬럼과도 이름이
    #   맞지 않는 죽은 키**이고, 이쪽은 **도달하는 키인데 만들어지는 자리가
    #   다를 뿐**이다. 그래서 그냥 통과시키지 않고, 바로 아래에서 그 자리를
    #   실제로 확인한다(마이그레이션이 없어지면 붉어진다).
    check("★ auction 에 대응 컬럼이 없는 키", sorted(keys - cols),
          ["filed_date", "has_status_pdf"])

    # (1-b) CREATE TABLE 에 없는 키는 **마이그레이션이 만들어야** 도달한다.
    #       이 확인이 없으면 위 목록은 '못 가는 키를 눈감아 주는' 명단이 된다.
    mig_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "storage", "migrations")
    added_by_migration = set()
    for fn in sorted(os.listdir(mig_dir)):
        if not fn.endswith(".sql"):
            continue
        sql = open(os.path.join(mig_dir, fn), encoding="utf-8-sig",
                   errors="replace").read()
        for mm in re.finditer(r"ALTER\s+TABLE\s+auction\s+ADD\s+COLUMN\s+([a-z_]+)", sql, re.I):
            added_by_migration.add(mm.group(1))
    check("★ CREATE TABLE 에 없는 도달 키는 마이그레이션이 만든다",
          sorted((keys - cols) & {"filed_date"} - added_by_migration), [])
    check("전제: 마이그레이션에서 ADD COLUMN 을 실제로 읽었다",
          "filed_date" in added_by_migration, True)

    # (2) 컬럼은 있는데 **upsert 가 값을 싣지 않는** 키(리터럴 0 이 박혀 있다).
    upsert = dbmod.UPSERT_SQL
    values_part = upsert.split("VALUES", 1)[1] if "VALUES" in upsert else ""
    check("전제: UPSERT_SQL 을 읽었다", "INSERT INTO auction" in upsert, True)
    check("★ upsert 가 리터럴 0 을 박는 자리가 있다(값이 버려진다)",
          "0,0,0" in values_part.replace(" ", ""), True)
    carried = keys & cols
    not_carried = sorted(k for k in carried
                         if k in ("has_spec_pdf", "has_appraisal_pdf", "has_status_doc"))
    check("★ 컬럼은 있지만 upsert 가 값을 안 싣는 키",
          not_carried, ["has_appraisal_pdf", "has_spec_pdf"])

    # (3) 크롤러가 그 필드를 정말 채우지 않는가 — 죽은 배선이라는 근거.
    root = os.path.dirname(os.path.abspath(__file__))
    assigns = []
    for dp, dn, fn in os.walk(os.path.join(root, "crawler")):
        dn[:] = [d for d in dn if d != "__pycache__"]
        for f in fn:
            if not f.endswith(".py"):
                continue
            text = open(os.path.join(dp, f), encoding="utf-8-sig", errors="replace").read()
            for field_ in ("has_spec_pdf", "has_status_pdf", "has_appraisal_pdf"):
                if re.search(r"\b%s\s*=" % field_, text):
                    assigns.append("%s:%s" % (f, field_))
    check("★ 크롤러가 has_* 필드에 값을 대입하지 않는다(죽은 배선)", sorted(assigns), [])

    # (4) 이 컬럼을 **읽는 쪽**이 있는가 — "아무도 안 읽으니 지우자"를 막는다.
    #
    #     2026-09-01 재검증에서 확인했다. `auction.has_*` 는 쓰기만 하는 컬럼이 아니다.
    #     `migrate_execute.py` 가 `document_status` 행을 처음 만들 때 **씨앗으로 읽는다**:
    #
    #         status = "READY" if row[col] == 1 else "COLLECTING"
    #
    #     즉 쓰기는 문서 수집(LEGACY_HAS_COLUMN), 읽기는 migrate_execute 하나다.
    #     죽은 것은 **모델/정규화기의 세 필드**이지 컬럼이 아니다. 이 구분을 놓치고
    #     컬럼을 드롭하면 새로 옮겨진 물건의 문서 상태가 전부 COLLECTING 으로 시작한다.
    import migrate_execute as _me
    mapped = dict(_me.MIGRATED_DOC_TYPE_COLUMNS)
    check("★ migrate_execute 가 읽는 레거시 컬럼", sorted(mapped.values()),
          ["has_appraisal_pdf", "has_spec_pdf", "has_status_doc"])
    me_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "migrate_execute.py"), encoding="utf-8-sig").read()
    check("★ 그 컬럼이 document_status 씨앗으로 실제로 읽힌다",
          'row[col] == 1' in me_src, True)

    # 자기 검증: 비교가 공허하지 않은가.
    check("자기 검증: 없는 키는 잡힌다", "qa_bogus" in ({"qa_bogus"} | keys) - cols, True)
    check("자기 검증: 실제 키는 컬럼에 있다", "case_no" in carried, True)
    return failures


# ---------------------------------------------------------------------------
# 크롤러가 **채웠는데 저장되지 않는** AuctionItem 필드 (2026-09-02 신설)
#
# ## 왜
#
# `AuctionItem` 은 크롤러가 상세페이지에서 긁은 것을 담는 그릇이다. 그런데 그중
# 다섯 개는 **채워지기만 하고 DB 로 가지 않는다.** 코드만 읽으면 "수집한다"고 읽히고,
# 실제로 수집도 하는데, 저장을 안 하니 화면에서는 존재하지 않는다.
#
# 실측(2026-09-02, `crawler/` 전수 + `normalize_item()` + `auction` 컬럼 대조):
#
#     basic_info         상세페이지의 **모든 th/td** 를 통째로 담는다   -> 버려진다
#     schedule           기일 내역                                    -> 버려진다
#     property_list      물건 목록                                    -> 버려진다
#     appraisal_summary  감정요항 원문                                 -> 버려진다
#     nearby_cases       인근 사건                                    -> 버려진다
#
# ## 왜 이것이 중요한가 (두 가지가 여기서 걸린다)
#
# 1. ★ 2026-09-03 정정 — **실크롤로 확인했고, 그중 하나는 배선했다.**
#
#    위 ※ 가 남긴 '실크롤로만 확인된다'를 실제로 돌려서 판정했다
#    (서울중앙·수원·인천, 상세페이지 표를 그대로 덤프):
#
#        사건접수      2008.08.26 / 2024.03.20 / 2024.10.14   4물건 4/4 에 있었다
#        배당요구종기   2008.11.28 / 2024.06.04                4물건 4/4 에 있었다
#        경매개시일     2008.08.27 / 2024.03.22                4물건 4/4 에 있었다
#
#    즉 추측이 맞았다 — 새 크롤 설계가 아니라 **이미 파싱된 것을 저장**하는 일이었다.
#
#    `filed_date` 는 그래서 **배선했다**(normalize_item -> auction.filed_date ->
#    migrate_execute -> auction_case.filed_date). 스키마 변경이 필요 없었다 —
#    두 컬럼이 이미 있었다(011, 028). 인천 10사건으로 끝에서 끝까지 확인했다.
#
#    `demand_deadline` / `case_type` 은 **배선하지 않았다.** 값을 못 구해서가
#    아니라 원시 `auction` 표에 받아 둘 컬럼이 없어 `ALTER TABLE` 이 필요하고,
#    스키마 변경은 승인 사항이기 때문이다(docs/CLAUDE.md).
#    근거와 다음 단계: docs/SPRINT285_CASE_DATE_PRODUCER.md
#
#    ※ 그래서 `basic_info` 는 이제 **통째로 버려지지는 않는다** — `normalize_item()`
#      이 '사건접수' 한 키를 읽는다. 그래도 이 목록에 남는다: 저장되는 것은
#      거기서 뽑은 값 하나뿐이고, 나머지 수십 개 th/td 는 여전히 버려진다.
#
# 2. `appraisal_summary` 는 `validator/validation_engine.py` 가 **크롤 시점에** 읽어
#    `address_mismatch` 를 판정하는 바로 그 입력이다. 그런데 저장하지 않으므로
#    **왜 검증실패인지 사후에 재현할 수 없다.** 실제로 이 저장소의
#    `validation_reasons` 에 남은 `addr=부산 appraisal=서울` 같은 판정을 지금은
#    아무도 검증할 수 없다(같은 건물 4세대가 한 감정서를 공유하는 실측 패턴이 있다).
#
# ## 무엇을 고정하나
#
# 저장할지 말지는 스키마 변경이고 수집 범위 결정이라 **여기서 하지 않는다.**
# 대신 **지금 버려진다는 사실**을 고정한다. 목록이 바뀌면 - 배선되든 필드가 사라지든 -
# 이 검사가 먼저 알려 준다. (`run_normalized_keys_reach_storage()` 가 죽은
# `has_*_pdf` 배선을 고정해 둔 것과 같은 관례다.)
# ---------------------------------------------------------------------------
CAPTURED_BUT_DISCARDED = {
    "basic_info":        "상세페이지 th/td 전부. '사건접수' 한 키만 읽고 나머지는 버린다",
    "schedule":          "기일 내역",
    "property_list":     "물건 목록",
    "appraisal_summary": "감정요항 원문. validator 가 크롤 시점에만 읽고 버린다",
    "nearby_cases":      "인근 사건",
}


def run_captured_but_discarded_fields():
    import dataclasses
    from models.auction_item import AuctionItem
    from normalizer.normalizer import normalize_item
    import storage.database as dbmod

    failures = []

    def check(name, got, expected):
        ok = got == expected
        print("[%s] %s: %r" % ("PASS" if ok else "FAIL", name, got))
        if not ok:
            print("     expected %r" % (expected,))
            failures.append(name)

    print()
    print("--- 크롤러가 채웠는데 저장되지 않는 필드 ---")

    item = AuctionItem(
        case_no="2026타경1", item_no="1", address="서울특별시 강남구 역삼동 736-1",
        property_type="아파트", appraisal_price="100000000",
        minimum_bid_price="80000000", auction_date="2026-09-30",
        status="유찰 1회", court_code="서울중앙지방법원",
        court_name="서울중앙지방법원", crawl_date="2026-09-01",
    )
    norm_keys = set(normalize_item(item).keys())
    model_fields = {f.name for f in dataclasses.fields(AuctionItem)}

    # auction 컬럼 (이 파일의 다른 검사와 같은 방식으로 소스에서 읽는다)
    import re
    root = os.path.dirname(os.path.abspath(__file__))
    src = io.open(os.path.join(root, "storage", "database.py"),
                  encoding="utf-8-sig").read()
    m = re.search(r"CREATE TABLE IF NOT EXISTS auction\s*\((.*?)\n\s*\)", src, re.S)
    cols = set()
    if m:
        for line in m.group(1).split("\n"):
            mm = re.match(r"\s*([a-z_]+)\s+(INTEGER|TEXT|REAL)", line)
            if mm:
                cols.add(mm.group(1))
    check("전제: auction 컬럼을 읽었다(개수>10)", len(cols) > 10, True)
    check("전제: 모델 필드를 읽었다(개수>10)", len(model_fields) > 10, True)

    # (1) 목록의 필드가 **정말 모델에 있고**, 정규화/컬럼 어디에도 없다.
    for field, why in sorted(CAPTURED_BUT_DISCARDED.items()):
        check("모델에 %s 가 있다 (%s)" % (field, why), field in model_fields, True)
        check("★ %s 는 normalize_item 출력에 없다" % field, field in norm_keys, False)
        check("★ %s 는 auction 컬럼에도 없다" % field, field in cols, False)

    # (2) 크롤러가 **실제로 그 필드를 채운다** — 죽은 필드가 아니라 '버려지는' 필드라는 근거.
    crawl_src = ""
    for dp, dn, fn in os.walk(os.path.join(root, "crawler")):
        dn[:] = [x for x in dn if x != "__pycache__"]
        for fl in fn:
            if fl.endswith(".py"):
                crawl_src += io.open(os.path.join(dp, fl), encoding="utf-8-sig").read()
    check("전제: crawler 소스를 읽었다", len(crawl_src) > 1000, True)
    not_filled = sorted(f for f in CAPTURED_BUT_DISCARDED if ("%s=" % f) not in crawl_src)
    check("★★ 목록의 필드를 크롤러가 실제로 채운다(버려지는 것이 맞다)", not_filled, [])

    # (3) 목록 **밖에서** 새로 버려지기 시작한 필드가 없는가.
    #     `address` 는 제외한다 - 버려지는 것이 아니라 normalize_address() 가
    #     full_address/sido/sigungu/dong 으로 **분해해서** 저장한다.
    #     `has_status_pdf` 는 이미 run_normalized_keys_reach_storage() 가 고정한다.
    KNOWN_ELSEWHERE = {"address", "has_status_pdf"}
    newly = sorted(f for f in model_fields
                   if f not in norm_keys and f not in cols
                   and f not in CAPTURED_BUT_DISCARDED and f not in KNOWN_ELSEWHERE)
    check("새로 버려지기 시작한 필드 없음", newly, [])

    return failures


def run_case_no_two_implementations():
    """이름이 같은 `normalize_case_no()` 두 판본의 계약을 고정한다 (2026-09-02 신설).

    ## 왜

    Frankenstein 전수 감사에서 나왔다. **같은 패키지에 같은 이름**이 둘 있다.

        normalizer/normalizer.py     크롤 원천을 믿는다. 양끝 공백만 턴다.
        normalizer/mylist_import.py  사람이 붙여 넣은 잡음에서 사건번호를 뽑아낸다.

    같은 이름이라 잘못 가져다 쓰기 쉽고, 그러면 **같은 물건이 다른 식별자로 저장된다.**
    그런데 합쳐서도 안 된다 - 크롤 쪽을 가져오기 쪽으로 위임하면 `타채` 같은 다른
    사건부호가 통째로 빈 문자열이 된다(아래 표가 그것을 고정한다).

    ## 무엇을 고정하나

    (a) **정상 표기에서는 반드시 같은 답** - 여기가 갈라지면 식별자가 갈라진다.
    (b) **의도된 차이** - 어느 한쪽이 조용히 상대에게 흡수되면 (b)가 먼저 운다.

    실측(2026-09-02, 이 머신 auction.db): distinct case_no 1,381개 전부 두 함수 결과가
    동일했다. 지금 갈라져 있지는 않다 - 이 검사는 **앞으로 갈라지는 것**을 막는다.
    """
    from normalizer.normalizer import normalize_case_no as crawl_norm
    from normalizer.mylist_import import normalize_case_no as import_norm

    failures = []

    def check(name, actual, expected):
        ok = actual == expected
        print("[%s] %s: %r (expected %r)" % ("PASS" if ok else "FAIL", name, actual, expected))
        if not ok:
            failures.append(name)

    print()
    print("--- normalize_case_no 두 판본의 계약 ---")

    # 전제: 정말 서로 다른 함수다(같은 객체면 아래가 공허하다).
    check("전제: 두 판본이 서로 다른 함수다", crawl_norm is import_norm, False)

    # (a) 정상 표기 - 반드시 같은 답. 여기가 이 검사의 핵심이다.
    for value in ("2024타경1009",
                  "  2024타경1009  ",
                  "2008타경25092 / 2015타경19958",
                  ""):
        check("★ 정상 표기는 두 판본이 같은 답 (%r)" % value,
              crawl_norm(value), import_norm(value))

    # (b) 의도된 차이 - 합쳐지면 여기가 운다.
    #     왼쪽이 크롤 판본, 오른쪽이 가져오기 판본의 **정답**이다.
    for value, want_crawl, want_import in (
            ("2024타채1009",    "2024타채1009",    ""),
            ("2024타경1009-1",  "2024타경1009-1",  "2024타경1009"),
            ("사건번호 없음",     "사건번호 없음",     ""),
            ("2024 타경 1009",  "2024 타경 1009",  "2024타경1009"),
    ):
        check("의도된 차이(크롤은 원천 보존): %r" % value, crawl_norm(value), want_crawl)
        check("의도된 차이(가져오기는 추출): %r" % value, import_norm(value), want_import)

    # 크롤 판본이 **원천을 버리지 않는다** - 위임 사고를 정면으로 막는다.
    check("★★ 크롤 판본은 타경이 아닌 사건부호를 버리지 않는다",
          crawl_norm("2024타채1009") != "", True)

    # 두 판본이 한 파일에 합쳐지지 않았는지(정본 위치)도 함께 본다.
    import normalizer.normalizer as n_mod
    import normalizer.mylist_import as m_mod
    check("크롤 판본은 normalizer.py 에 있다",
          n_mod.normalize_case_no.__module__, "normalizer.normalizer")
    check("가져오기 판본은 mylist_import.py 에 있다",
          m_mod.normalize_case_no.__module__, "normalizer.mylist_import")

    # 이 구분이 왜 있는지가 코드에 적혀 있는가 - 주석이 지워지면 다음 사람이 또 합친다.
    src = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "normalizer", "normalizer.py"),
                  encoding="utf-8-sig").read()
    body = src.split("def normalize_case_no(")[1].split("\ndef ")[0]
    check("크롤 판본에 '왜 합치면 안 되는가'가 적혀 있다",
          "mylist_import" in body and "타채" in body, True)

    return failures


def run():
    failures = []

    for name, addr, exp_sido, exp_sigungu, exp_dong in CASES:
        result = normalize_address(addr)
        ok = (
            result["sido"] == exp_sido
            and result["sigungu"] == exp_sigungu
            and result["dong"] == exp_dong
        )
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name}: {addr}")
        if not ok:
            failures.append(name)
            print(f"    got      sido={result['sido']!r} sigungu={result['sigungu']!r} dong={result['dong']!r}")
            print(f"    expected sido={exp_sido!r} sigungu={exp_sigungu!r} dong={exp_dong!r}")

    # 부가 필드(lot_number, full_address)가 이번 수정과 무관하게 그대로 동작하는지 확인
    detail = normalize_address("서울특별시 강남구 역삼동 736-1")
    ok = detail["lot_number"] == "736-1" and detail["full_address"] == "서울특별시 강남구 역삼동 736-1"
    print(f"[{'PASS' if ok else 'FAIL'}] lot_number/full_address 부가필드 보존")
    if not ok:
        failures.append("lot_number/full_address 부가필드 보존")
        print(f"    got lot_number={detail['lot_number']!r} full_address={detail['full_address']!r}")

    # 빈 문자열 입력 시 예외 없이 빈 값 반환하는지 확인 (방어 코드 회귀 확인)
    try:
        empty = normalize_address("")
        ok = all(empty[k] == "" for k in ("sido", "sigungu", "dong", "lot_number"))
        print(f"[{'PASS' if ok else 'FAIL'}] 빈 문자열 입력 시 예외 없이 빈 값 반환")
        if not ok:
            failures.append("빈 문자열 입력 처리")
    except Exception as e:
        failures.append("빈 문자열 입력 처리")
        print(f"[FAIL] 빈 문자열 입력 시 예외 발생: {e!r}")

    # extract_sido 자체 회귀 확인 (normalize_address가 내부적으로 의존)
    ok = extract_sido("세종특별자치시 어진동 100") == "세종"
    print(f"[{'PASS' if ok else 'FAIL'}] extract_sido 단독 동작 확인")
    if not ok:
        failures.append("extract_sido 단독 동작")

    failures += run_value_normalizers()
    failures += run_sido_position()
    failures += run_batch_isolation()
    failures += run_bracket_preservation()
    failures += run_area_extraction()
    failures += run_bracket_exclusion()
    failures += run_normalized_keys_reach_storage()
    failures += run_case_no_two_implementations()
    failures += run_captured_but_discarded_fields()

    print()
    if failures:
        print(f"{len(failures)}건 실패: {failures}")
        return 1
    print(f"전체 {len(CASES) + 3 + len(PRICE_CASES) + len(DATE_CASES) + 6 + len(SIDO_POSITION_CASES) + 3 + len(BRACKET_CASES) * 3}건 통과")
    return 0


if __name__ == "__main__":
    sys.exit(run())
