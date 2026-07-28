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
    if not text:
        return ""
    for sido, patterns in SIDO_PATTERNS.items():
        for p in patterns:
            if p in text:
                return sido
    return ""

def normalize_address(address: str) -> dict:
    sido = extract_sido(address)
    sigungu = ""
    dong = ""
    lot_number = ""

    # 시도 접두어 제거 후 나머지에서 시군구 추출
    remainder = address
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
