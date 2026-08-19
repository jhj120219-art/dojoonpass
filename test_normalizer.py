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
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from normalizer.normalizer import (
    normalize_address, extract_sido,
    normalize_price, normalize_date, normalize_case_no,
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

    print()
    if failures:
        print(f"{len(failures)}건 실패: {failures}")
        return 1
    print(f"전체 {len(CASES) + 3 + len(PRICE_CASES) + len(DATE_CASES) + 6 + len(SIDO_POSITION_CASES) + 3 + len(BRACKET_CASES) * 3}건 통과")
    return 0


if __name__ == "__main__":
    sys.exit(run())
