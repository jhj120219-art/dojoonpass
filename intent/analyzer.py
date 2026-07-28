"""
Sprint 5 Intent Search - Intent Analyzer.

address_detail로 들어온 자유입력 문자열이 사용자의 어떤 검색 의도(Intent)에
해당하는지 판별한다. normalize_address()는 무수정으로 재사용하고, 그 결과에서
"어떤 필드가 채워졌는지"와 "인식되지 않고 남은 잔여 텍스트(residual)"를 근거로
Intent를 분류한다.

이 모듈은 순수 함수만 제공하며 DB/네트워크에 접근하지 않는다. Search API(검색
전략 SQL 생성)는 다음 STEP에서 이 모듈의 analyze_intent()를 호출해 사용한다.
"""
from normalizer.normalizer import normalize_address, SIDO_PATTERNS

# Fallback Tier3(토큰 분리 검색)에서 제외할 일반 명사.
# 이 단어들만으로는 특정 지역/물건을 좁힐 수 없어 과다매칭(오탐)을 유발한다.
GENERIC_TOKENS = {
    "아파트", "빌라", "오피스텔", "상가", "주택",
    "연립", "단독", "다세대", "근린", "시설",
}

INTENT_LOT_NUMBER = "LOT_NUMBER"
INTENT_FULL_ADDRESS = "FULL_ADDRESS"
INTENT_SIDO = "SIDO"
INTENT_SIGUNGU = "SIGUNGU"
INTENT_DONG = "DONG"
INTENT_MIXED = "MIXED"
INTENT_UNKNOWN = "UNKNOWN"


def _strip_matched(text: str, parsed: dict) -> str:
    residual = text
    if parsed["sido"]:
        for variant in SIDO_PATTERNS.get(parsed["sido"], []):
            if variant in residual:
                residual = residual.replace(variant, "", 1)
                break
    if parsed["sigungu"]:
        residual = residual.replace(parsed["sigungu"], "", 1)
    if parsed["dong"]:
        residual = residual.replace(parsed["dong"], "", 1)
    if parsed["lot_number"]:
        residual = residual.replace(parsed["lot_number"], "", 1)
    return residual.strip(" ,()[]")


def analyze_intent(text: str) -> dict:
    """
    입력 문자열을 분석해 {"parsed", "residual", "intent"}를 반환한다.

    - parsed: normalize_address(text)의 반환값 그대로(sido/sigungu/dong/lot_number/full_address)
    - residual: parsed에서 인식된 부분을 제거하고 남은 텍스트(공백/괄호/콤마 정리 후)
    - intent: LOT_NUMBER / FULL_ADDRESS / SIDO / SIGUNGU / DONG / MIXED / UNKNOWN 중 하나
    """
    if not text:
        parsed = normalize_address("")
        return {"parsed": parsed, "residual": "", "intent": INTENT_UNKNOWN}

    parsed = normalize_address(text)
    residual = _strip_matched(text, parsed)

    filled = [k for k in ("sido", "sigungu", "dong") if parsed[k]]

    if parsed["lot_number"] and not filled and not residual:
        intent = INTENT_LOT_NUMBER
    elif len(filled) == 3 and not residual:
        intent = INTENT_FULL_ADDRESS
    elif len(filled) == 1 and not residual:
        intent = {"sido": INTENT_SIDO, "sigungu": INTENT_SIGUNGU, "dong": INTENT_DONG}[filled[0]]
    elif filled:
        # 2개 필드만 잔여 없이 채워진 경우(예: sigungu+dong)나, 1~3개 필드가
        # 채워졌지만 잔여 텍스트가 남는 경우(예: "강서구 화곡동 빌라") 모두 MIXED로
        # 분류한다. Search Strategy 쪽에서 채워진 필드만으로 AND 조건을 구성하고
        # 잔여 텍스트는 버리므로, FULL_ADDRESS만큼 확정적이지 않은 이 케이스들을
        # 굳이 더 세분화할 필요가 없다.
        intent = INTENT_MIXED
    else:
        intent = INTENT_UNKNOWN

    return {"parsed": parsed, "residual": residual, "intent": intent}


def split_tokens(text: str) -> list:
    """
    Fallback Tier3용 토큰 분리. 공백으로 나눈 뒤 길이 2 미만이거나
    GENERIC_TOKENS에 속하는 토큰(오탐 유발)은 제외한다.
    """
    tokens = [t.strip(" ,()[]") for t in text.split()]
    return [t for t in tokens if len(t) >= 2 and t not in GENERIC_TOKENS]
