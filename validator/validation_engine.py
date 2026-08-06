import re
import json
import logging
from datetime import datetime
from typing import List, Dict
from models.auction_item import AuctionItem
# normalizer.py의 SIDO_PATTERNS와 이 모듈의 (구)SIDO_MAP은 완전히 동일한 내용의 별도
# 정의였다(Duplicate Code) — 한쪽만 남기고 재사용한다. 값/동작은 그대로 유지.
from normalizer.normalizer import SIDO_PATTERNS as SIDO_MAP

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

def extract_sido(text: str) -> str:
    if not text:
        return ""
    for sido, variants in SIDO_MAP.items():
        for v in variants:
            if v in text:
                return sido
    return ""

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
