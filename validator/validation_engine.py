import re
import json
import logging
from datetime import datetime
from typing import List, Dict
from models.auction_item import AuctionItem
# 시도(sido) 데이터 중복 제거 이력 — 2026-08-17 Sprint 167에 import까지 정리했다.
#
# 원래 이 파일에는 `SIDO_MAP`이라는, `normalizer.py:SIDO_PATTERNS`와 **바이트 단위로
# 동일한** 별도 정의가 있었다(Duplicate Code). 먼저 그것을 지우고
# `from normalizer.normalizer import SIDO_PATTERNS as SIDO_MAP` 으로 바꿨다.
#
# 그 뒤 Sprint 78이 아래 `extract_sido`까지 normalizer 것을 쓰도록 바꾸면서, **그 데이터를
# 직접 읽던 이 파일의 함수가 사라졌다.** 그래서 별칭 import만 남고 쓰는 곳은 0곳이 됐다
# (2026-08-17 전수 확인: 이 파일 주석 2곳 외에 참조 없음, 다른 모듈의 재수출 사용도 없음).
# 재노출 의도였다면 아래 `extract_sido`처럼 `# noqa: F401`이 붙었을 텐데 그것도 없었다.
#
# 데이터는 `normalizer.SIDO_PATTERNS` 한 곳에만 있고, 이 파일은 그것을 해석하는
# `extract_sido()`만 가져다 쓴다. 필요해지면 그때 다시 import하면 된다.

logger = logging.getLogger(__name__)

# 광역시-도 인접 허용 쌍 (addr_sido, appraisal_sido)
ADJACENT_SIDO_PAIRS = {
    frozenset(["광주", "전남"]),
    frozenset(["광주", "전북"]),
    frozenset(["대전", "충남"]),
    frozenset(["대전", "충북"]),
    frozenset(["대구", "경북"]),
    frozenset(["부산", "경남"]),
    frozenset(["울산", "경남"]),
    frozenset(["인천", "경기"]),
    frozenset(["서울", "경기"]),
    frozenset(["세종", "충남"]),
    frozenset(["세종", "충북"]),
}

# 가격 오차 허용 범위 (원)
PRICE_TOLERANCE = 1000

# extract_sido는 normalizer의 것을 그대로 쓴다 (2026-08-13 Sprint 78).
#
# 예전에는 이 파일에 **바이트 단위로 동일한 복사본**이 따로 있었다. 위 SIDO_MAP 주석이
# 위 중복 제거 이력 주석대로 데이터(SIDO_PATTERNS)는 이미 합쳐 뒀는데, **그 데이터를
# 해석하는 함수는 합쳐지지 않은 채 남아 있었다.**
#
# 같은 판정을 하는 함수가 두 벌이면 한쪽만 고쳐질 수 있다. 실제로 Sprint 78에
# normalizer 쪽 판정 규칙을 고쳤을 때(가장 앞선 표기가 이기도록), 이 복사본을 그대로
# 뒀다면 **크롤 데이터는 제주로 저장되는데 검증은 세종으로 판정**하는 상태가 됐을 것이다.
# 그 불일치는 address_mismatch 오탐으로 나타나 화면에 "검증실패"로 뜬다.
#
# 재노출(re-export)이라 `from validator.validation_engine import extract_sido`를 쓰던
# 기존 호출부는 그대로 동작한다.
from normalizer.normalizer import extract_sido  # noqa: E402  (재노출)

def parse_price(price_str: str) -> int:
    if not price_str or price_str == "-":
        return 0
    digits = re.sub(r"[^\d]", "", price_str.split("(")[0])
    return int(digits) if digits else 0

def is_adjacent(sido_a: str, sido_b: str) -> bool:
    return frozenset([sido_a, sido_b]) in ADJACENT_SIDO_PAIRS

class ValidationEngine:
    def __init__(self, log_path: str = "logs/validation.jsonl"):
        self.log_path = log_path

    def validate(self, item: AuctionItem) -> AuctionItem:
        reasons: List[str] = []

        # 1. 필수 필드 검증
        if not item.case_no or item.case_no == "-":
            reasons.append("case_no missing")
        if not item.address or item.address == "-":
            reasons.append("address missing")
        if not item.appraisal_price or item.appraisal_price == "-":
            reasons.append("appraisal_price missing")
        if not item.auction_date or item.auction_date == "-":
            reasons.append("auction_date missing")

        # 2. 주소 vs 감정요항 지역 불일치 검증
        addr_sido = extract_sido(item.address)
        appraisal_sido = extract_sido(item.appraisal_summary)

        if addr_sido and appraisal_sido and addr_sido != appraisal_sido:
            if not is_adjacent(addr_sido, appraisal_sido):
                reasons.append(
                    "address_mismatch: addr=" + addr_sido +
                    " appraisal=" + appraisal_sido
                )
            else:
                logger.debug(
                    "인접 광역시-도 허용: addr=%s appraisal=%s [%s]",
                    addr_sido, appraisal_sido, item.case_no
                )

        # 3. 가격 검증: 최저가 <= 감정가 (허용 오차 1000원)
        appraisal = parse_price(item.appraisal_price)
        minimum = parse_price(item.minimum_bid_price)

        if appraisal > 0 and minimum > 0:
            if minimum > appraisal + PRICE_TOLERANCE:
                reasons.append(
                    "price_invalid: min=" + str(minimum) +
                    " > appraisal=" + str(appraisal)
                )

        # 4. 사건번호 형식 검증
        case_pat = re.compile(r"\d{4}타경\d+")
        if item.case_no and not case_pat.search(item.case_no):
            reasons.append("case_no_format_invalid: " + item.case_no)

        item.validation_status = "PASS" if not reasons else "FAIL"
        item.validation_reasons = reasons

        self._log(item)
        return item

    def validate_batch(self, items: List[AuctionItem]) -> List[AuctionItem]:
        return [self.validate(item) for item in items]

    def _log(self, item: AuctionItem) -> None:
        log_entry = {
            "case_no": item.case_no,
            "item_no": item.item_no,
            "validation": item.validation_status,
            "reasons": item.validation_reasons,
            "timestamp": datetime.now().isoformat(),
        }
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error("validation log write failed: %s", str(e))

    def summary(self, items: List[AuctionItem]) -> Dict:
        total = len(items)
        passed = sum(1 for i in items if i.validation_status == "PASS")
        failed = sum(1 for i in items if i.validation_status == "FAIL")
        return {
            "total": total,
            "pass": passed,
            "fail": failed,
            "accuracy": round(passed / total * 100, 1) if total > 0 else 0,
        }
