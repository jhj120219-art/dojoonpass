import re
import logging
from models.auction_item import AuctionItem

logger = logging.getLogger(__name__)

SIDO_PATTERNS = {
    "서울": ["서울특별시", "서울시", "서울"],
    "경기": ["경기도", "경기"],
    "인천": ["인천광역시", "인천시", "인천"],
    "부산": ["부산광역시", "부산시", "부산"],
    "대구": ["대구광역시", "대구시", "대구"],
    "광주": ["광주광역시", "광주시", "광주"],
    "대전": ["대전광역시", "대전시", "대전"],
    "울산": ["울산광역시", "울산시", "울산"],
    "세종": ["세종특별자치시", "세종시", "세종"],
    "강원": ["강원도", "강원특별자치도", "강원"],
    "충북": ["충청북도", "충북"],
    "충남": ["충청남도", "충남"],
    "전북": ["전라북도", "전북특별자치도", "전북"],
    "전남": ["전라남도", "전남"],
    "경북": ["경상북도", "경북"],
    "경남": ["경상남도", "경남"],
    "제주": ["제주특별자치도", "제주도", "제주"],
}

# 시도 접두어 목록 (주소에서 제거 후 시군구 추출)
SIDO_PREFIXES = [
    "서울특별시", "부산광역시", "대구광역시", "인천광역시",
    "광주광역시", "대전광역시", "울산광역시", "세종특별자치시",
    "경기도", "강원도", "강원특별자치도", "충청북도", "충청남도",
    "전라북도", "전북특별자치도", "전라남도", "경상북도", "경상남도",
    "제주특별자치도",
    # 사용자 축약형("서울시" 등)이 SIDO_PATTERNS엔 동의어로 등록되어 있으면서
    # 여기 없으면, 접두어가 안 지워진 채 남아 시군구 정규식(...[구시군])이 이를
    # 시/군/구로 오인식한다("서울시" -> sigungu="서울시"). 실제 크롤링 원문은 항상
    # 정식 명칭만 쓰므로(위 목록으로 이미 커버됨), 아래 8개는 사용자 검색 입력의
    # 축약형만을 위해 추가한다.
    "서울시", "인천시", "부산시", "대구시", "광주시", "대전시", "울산시", "세종시",
]

def extract_sido(text: str) -> str:
    """텍스트에서 시도를 뽑는다. **가장 앞에 나오는 표기**가 이긴다.

    2026-08-13 Sprint 78 수정. 예전에는 `SIDO_PATTERNS`를 딕셔너리 순서대로 훑어
    **처음 발견된 것**을 돌려줬다. 즉 판정이 문자열 안의 위치가 아니라 **이 사전의
    선언 순서**로 정해졌다. 주소는 시도로 시작하는데도, 뒤쪽 아무 데나 다른 지역명이
    섞여 있으면 그쪽이 이겼다. 실측으로 4건이 잘못 분류돼 있었다.

        경기도 시흥시 **서울**대학로 59-21          -> 서울 (실제 경기)   도로명
        경상남도 양산시 물금읍 **부산**대학로 150     -> 부산 (실제 경남)   도로명
        인천광역시 계양구 ... (효성동, 뉴**서울**아파트) -> 서울 (실제 인천)   건물명
        제주특별자치도 제주시 ... 주식회사 뉴**세종**하우징 -> 세종 (실제 제주)   공유자 이름

    마지막 건이 이 결함의 성격을 가장 잘 보여준다. "제주특별자치도"는 **0번 위치**에
    있는데 539번 위치의 "세종"에게 졌다. 오직 사전에서 세종이 제주보다 위에 있다는
    이유였다.

    `sido`는 검색의 1차 필터다. 잘못 분류된 물건은 **제 지역에서 검색되지 않고 남의
    지역을 오염시킨다.** `부산대학로`/`서울대학로`는 실재하는 도로명이라 재발한다.

    위치가 같으면 **더 긴 표기**를 택한다("서울특별시"와 "서울"이 같은 자리에서 만날 때
    더 구체적인 쪽). 지역명이 하나도 없으면 예전처럼 빈 문자열이다.

    ★ 이 함수는 주소만 받는 것이 아니다 — 사용자 검색어("서울 강남구")와 감정요항
    자유 텍스트에도 쓰인다. 그래서 "주소 접두어만 본다"가 아니라 **가장 앞선 언급**을
    택하는 규칙으로 고쳤다. 세 용도 모두에서 자연스럽고, 지역명이 앞에 오지 않는
    입력에 대해서는 기존 동작이 그대로 유지된다.
    """
    if not text:
        return ""
    best_key = None
    best_sido = ""
    for sido, patterns in SIDO_PATTERNS.items():
        for p in patterns:
            idx = text.find(p)
            if idx == -1:
                continue
            key = (idx, -len(p))
            if best_key is None or key < best_key:
                best_key = key
                best_sido = sido
    return best_sido

# 대괄호 블록(= 물건 표시)을 떼어낸 **주소 부분만** 돌려준다.
#
# `full_address` 는 "주소 + [물건 표시]" 형태다. 뒤쪽 대괄호 안에는 구조·면적·등기부
# 항목(갑구/을구) 같은 것이 들어 있고 **주소 성분은 없다.** 주소를 파싱하는 쪽은 전부
# 이 함수를 거쳐야 한다 — 안 그러면 "갑구" 를 시군구로 읽는 식의 오인식이 난다.
#
# 규칙을 여기 한 곳에만 둔다(같은 정규식이 두 곳에 있으면 갈라진다, BUGS #204).
# 안쪽에 대괄호가 한 겹 더 있는 표기도 통째로 집는다: `[토지 전[현황:묵전(죽림)] 105㎡]`.
_BRACKET_BLOCK_RE = re.compile(r"\[[^\[\]]*(?:\[[^\]]*\][^\[\]]*)*\]")


def address_without_brackets(address: str) -> str:
    """주소에서 `[...]` 물건 표시 블록을 지운 문자열. 원본은 바꾸지 않는다."""
    if not address:
        return ""
    return _BRACKET_BLOCK_RE.sub(" ", address)


def normalize_address(address: str) -> dict:
    sido = extract_sido(address)
    sigungu = ""
    dong = ""
    lot_number = ""

    # ★ 주소 성분을 뽑기 전에 **대괄호 블록을 먼저 떼어낸다** (2026-08-26).
    #
    #   `full_address` 의 대괄호는 주소가 아니라 **물건 표시**다
    #   (`[토지 임야 297㎡ 갑구 2번, 3번 공유자 ...]`). 그런데 아래 시군구 정규식은
    #   `[가-힣]+[구시군]` 이라 그 안의 **"갑구"**(등기부 갑구/을구를 가리키는 말)를
    #   행정구역으로 집었다. 실측 — 세종시 주소 2건이 `sigungu='갑구'` 로 저장돼 있었다:
    #
    #       세종특별자치시 전의면 관정리 578-31 [토지 임야 297㎡ 갑구 2번, 3번 ...]
    #                                             ^^^^ 여기를 시군구로 읽었다
    #
    #   세종시는 시군구가 없어 정답이 빈 문자열이다. 그런데 '갑구' 가 들어가면
    #   `sigungu LIKE '%갑구%'` 검색에 엉뚱하게 걸리고, 지역 필터가 조용히 틀린다.
    #
    #   대괄호를 떼는 것이 옳은 이유: 그 안에는 주소 성분이 **원래 없다.** 지번은 이미
    #   아래에서 `(?=\s|$|\[)` 로 대괄호 앞까지만 보고 있었다 — 같은 규칙을 시군구/동에도
    #   맞춘다. `full_address` 자체는 **그대로 돌려준다**(원문 무손실 계약, 아래 return).
    address_part = address_without_brackets(address)

    # 시도 접두어 제거 후 나머지에서 시군구 추출
    remainder = address_part
    for prefix in SIDO_PREFIXES:
        if prefix in remainder:
            remainder = remainder.replace(prefix, "").strip()
            break

    # 시군구: 앞에서 첫 번째로 나오는 구/시/군.
    # 고양시/성남시/수원시 등 일반구를 둔 시는 "OO시 OO구" 형태로 구까지 함께 잡아야
    # sigungu LIKE 검색에서 구 단위(예: "일산동구")가 누락되지 않는다.
    sigungu_match = re.search(r'[가-힣]+[구시군](?:\s+[가-힣]+구)?(?=\s|$)', remainder)
    if sigungu_match:
        sigungu = sigungu_match.group()

    # 동/읍/면/리
    # 1순위: "(법정동,건물명)" 괄호 표기 — 도로명주소 뒤에 참고사항으로 법정동+건물명을
    # 병기하는 공식 관용 형식이라 존재할 경우 가장 신뢰도가 높다. 이 표기가 없으면
    # "에이동"/"비동"/"판매시설동" 같은 건물 내부 동 라벨이나 "젊음의거리"처럼 우연히
    # 동/읍/면/리로 끝나는 고유명사를, 정규식이 왼쪽에서 먼저 만난다는 이유로 잘못
    # 채택해버리는 문제가 있었다.
    paren_dong_match = re.search(r'\(([가-힣]+[동읍면리])[,\s]', remainder)
    if paren_dong_match:
        dong = paren_dong_match.group(1)
    else:
        # 2순위: 괄호 표기가 아예 없는 주소(순수 도로명주소 등)에 대한 기존 로직.
        # 동 뒤에 콤마가 바로 오는 경우("...5 지2층비202호 (문정동,푸르지오시티)")도
        # 있어 콤마를 lookahead에 포함시킨다.
        dong_match = re.search(r'[가-힣]+[동읍면리](?=[\s\d,]|$)', remainder)
        if dong_match:
            dong = dong_match.group()

    # 지번
    lot_match = re.search(r'\d+[-\d]*(?=\s|$|\[)', address)
    if lot_match:
        lot_number = lot_match.group()

    return {
        "sido": sido,
        "sigungu": sigungu,
        "dong": dong,
        "lot_number": lot_number,
        "full_address": address,
    }

# ---------------------------------------------------------------------------
# 면적 추출 (2026-08-26 신설)
#
# ## 왜 필요한가
#
# 검색 폼(`src/app/search/SearchForm.tsx`)에는 **건물면적 / 토지면적** 입력이 이미 있고
# `min_building_area` 등으로 값을 보낸다. 그런데 `auction_item` 에 대응 컬럼이 없어
# 백엔드가 그 파라미터를 **읽지 않는다** — 사용자가 면적을 좁혀도 결과가 그대로다.
# 오류도 안내도 없어서 **틀렸다는 것을 알 수 없는** 종류의 결함이다.
# (소스에 `TODO(API 미지원)` 로 표시돼 있었고 `test_search.py` 가 그 사실을 고정하고 있었다.)
#
# ## 데이터가 실제로 있는가 — 있다 (2026-08-26 실측, auction_item 2,444행)
#
#     full_address 에 ㎡ 표기가 있는 행      2,416 (98.9%)
#     대괄호 첫 토큰   집합건물 1,391 / 토지 974 / 건물 64 / 차량·선박 등 15
#     토지와 건물 대괄호를 **동시에** 가진 행     0        <- 갈래가 겹치지 않는다
#     대지권 표기가 있는 행                      1
#     ㎡ 가 없는 행                             28  (차량/선박/건설기계, 평 단위 1행)
#
# ## 규칙 (추측하지 않는다 — 위 실측에서 그대로 나온 것만)
#
#     [집합건물 ... 17.08㎡]              -> 건물면적
#     [건물 ... 1층 75.6㎡ 2층 70.2㎡]     -> 건물면적 = **합**(연면적). 다층 건물은 층별로 적힌다
#     [토지 대 420㎡]                     -> 토지면적
#     [집합건물 ... 74.5㎡ 대지권의 표시 ... 대 500㎡]
#                                        -> 대지권 **앞**은 건물, **뒤**는 토지
#     [카니발 2016년식 승용차]             -> 둘 다 없음(면적 개념이 없다)
#
# 평(坪)은 ㎡ 로 환산한다(1평 = 3.3057851㎡). 실데이터에 **13행** 있다
# (위 "평 단위 1행"은 옛 표본의 숫자다 — 2026-08-26 전수 재측: 13행).
#
# ★ 다만 **평/홉/작 3단 표기는 환산하지 않는다**(`docs/BUGS.md` #240).
#   옛 등기 표기 `1층192평6홉9작 2층190평2홉6작 ... 내 4층가제31호 건평3평3홉2작` 에서
#   앞의 층 목록은 **건물 1동 전체**이고, 이 물건은 `내 ...` 뒤의 **구분 호실**이다.
#   전부 더하면 4.8㎡ 짜리 사무실 한 칸이 2,509㎡ 로 나온다(실측 id=13584, 520배).
#   이것은 대지권 표기에서 이미 내린 판단과 **같은 상황**이다 — 지분/부분을 전체로
#   읽는 오류이므로 같은 답을 쓴다: **모르는 것으로 둔다(None).**
#
#   `src/lib/format.ts:parseArea()` 가 이미 이 결론에 도달해 있었다
#   (*"일괄 환산하면 틀린 숫자를 보여줄 위험이 있다. 아무것도 안 보여주는 편이 낫다"*).
#   화면은 그래서 옳게 비어 있었는데 **백엔드만 그 판단을 따르지 않아** DB 에 틀린 값이
#   들어갔고, 그 값이 면적 검색을 탔다. 여기서 두 쪽을 같은 규칙으로 맞춘다.
#
#   홉/작이 없는 단순 평 표기(`[토지 전 1048평]`, 11행)는 그대로 환산한다.
#
# ## 모르는 것은 None 으로 둔다
#
# 0 으로 채우면 "면적 0㎡ 인 물건"이 되어 `min_building_area=0` 같은 검색에 걸린다.
# 값이 없는 것과 0 인 것은 다르다 — 컬럼도 NULL 을 허용하고 검색도 NULL 을 거른다.
# ---------------------------------------------------------------------------

# 숫자 + 단위. 쉼표가 섞인 표기(1,048㎡)도 받는다.
_AREA_M2_RE = re.compile(r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*(㎡|m2|제곱미터|평)")

_PYEONG_TO_M2 = 3.3057851

# 평/홉/작 3단 표기(`192평6홉9작`). 이 표기가 보이면 그 대괄호의 면적은 **믿지 않는다** —
# 옛 등기의 '1동 전체 층 목록 + 내 구분호실' 형식이라 합산이 곧 오독이다. 위 주석 참고.
_PYEONG_SUBUNIT_RE = re.compile(r"[0-9]\s*평\s*[0-9]+\s*(?:홉|합|작)")

# 대괄호 한 덩어리. 안쪽에 대괄호가 한 겹 더 있는 표기도 통째로 집는다
# (실데이터: `[토지 전[현황:묵전(죽림)] 105㎡]`).
_BRACKET_RE = re.compile(r"\[([^\[\]]*(?:\[[^\]]*\][^\[\]]*)*)\]")

_BUILDING_HEADS = ("집합건물", "건물")
_LAND_HEADS = ("토지",)


def _sum_areas(text: str):
    """`text` 안의 모든 면적 표기를 ㎡ 로 합산한다. 하나도 없으면 None.

    평/홉/작 3단 표기가 섞여 있으면 **합산 자체가 오독**이라 None 을 돌려준다
    (`docs/BUGS.md` #240 — 1동 전체 층 목록과 구분호실이 한 문자열에 있다).
    """
    if _PYEONG_SUBUNIT_RE.search(text):
        return None
    total = None
    for raw, unit in _AREA_M2_RE.findall(text):
        try:
            value = float(raw.replace(",", ""))
        except ValueError:
            continue
        if unit == "평":
            value *= _PYEONG_TO_M2
        total = value if total is None else total + value
    return None if total is None else round(total, 4)


def extract_areas(full_address: str) -> dict:
    """주소 원문에서 건물/토지 면적(㎡)을 뽑는다.

    순수 함수 — DB 도 네트워크도 쓰지 않는다. 실패는 예외가 아니라 None 이다.
    돌려주는 키는 항상 둘 다 있다: {"building_area": float|None, "land_area": float|None}
    """
    result = {"building_area": None, "land_area": None}
    if not full_address:
        return result

    for inner in _BRACKET_RE.findall(full_address):
        stripped = inner.strip()
        if not stripped:
            continue
        head = stripped.split()[0]

        if head.startswith(_BUILDING_HEADS):
            # ★ 대지권 표기 뒤쪽은 **버린다.**
            #
            #   집합건물의 `대지권의 표시 ... 대 500㎡ 대지권 비율 : 500분의 21.7849` 에서
            #   500㎡ 는 **필지 전체**이고 이 물건의 몫은 비율(21.7849/500)이다. 앞 숫자를
            #   토지면적으로 쓰면 **23배 부풀려진다.** 비율을 곱해 계산할 수는 있지만
            #   표기 형태가 하나뿐이라(실데이터 1행) 규칙을 일반화할 근거가 없다.
            #   그래서 **모른다(None)로 둔다** — 틀린 값보다 없는 값이 낫다.
            #   (표본이 늘면 그때 비율 파싱을 근거 있게 추가한다.)
            marker = stripped.find("대지권")
            building_part = stripped[:marker] if marker >= 0 else stripped
            value = _sum_areas(building_part)
            if value is not None:
                result["building_area"] = value
        elif head.startswith(_LAND_HEADS):
            value = _sum_areas(stripped)
            if value is not None:
                result["land_area"] = value
        # 그 밖(차량/선박/건설기계 등)은 면적 개념이 없다 — 건드리지 않는다.

    return result


def normalize_price(price_str: str) -> int:
    if not price_str or price_str == "-":
        return 0
    digits = re.sub(r"[^\d]", "", price_str.split("(")[0])
    return int(digits) if digits else 0

def normalize_date(date_str: str) -> str:
    if not date_str or date_str == "-":
        return ""
    m = re.search(r"(\d{4})[.\-/](\d{2})[.\-/](\d{2})", date_str)
    if m:
        return m.group(1) + "-" + m.group(2) + "-" + m.group(3)
    return date_str

def normalize_case_no(case_no: str) -> str:
    return case_no.strip()

def normalize_item(item: AuctionItem) -> dict:
    addr_info = normalize_address(item.address)
    return {
        "court_code":         item.court_code,
        "court_name":         item.court_name,
        "case_no":            normalize_case_no(item.case_no),
        "item_no":            item.item_no,
        "property_type":      item.property_type,
        "sido":               addr_info["sido"],
        "sigungu":            addr_info["sigungu"],
        "dong":               addr_info["dong"],
        "lot_number":         addr_info["lot_number"],
        "full_address":       addr_info["full_address"],
        "appraisal_price":    normalize_price(item.appraisal_price),
        "minimum_bid_price":  normalize_price(item.minimum_bid_price),
        "auction_date":       normalize_date(item.auction_date),
        "status":             item.status,
        "validation_status":  item.validation_status,
        "validation_reasons": " | ".join(item.validation_reasons),
        "crawl_date":         item.crawl_date,
        "has_spec_pdf":       item.has_spec_pdf,
        "has_status_pdf":     item.has_status_pdf,
        "has_appraisal_pdf":  item.has_appraisal_pdf,
    }

def normalize_batch(items: list) -> list:
    result = []
    for item in items:
        try:
            result.append(normalize_item(item))
        except Exception as e:
            logger.warning("normalize_item failed [%s]: %s", item.case_no, str(e))
    return result
