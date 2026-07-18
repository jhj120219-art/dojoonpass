import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
from typing import List, Dict
from filter.filter_engine import extract_fail_count, calculate_bid_rate

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────
# 유찰횟수 점수 (최대 30점)
# ─────────────────────────────────────────
def score_fail_count(fail_count: int) -> float:
    if fail_count >= 10:
        return 30.0
    elif fail_count >= 7:
        return 25.0
    elif fail_count >= 5:
        return 20.0
    elif fail_count >= 3:
        return 15.0
    elif fail_count >= 2:
        return 10.0
    elif fail_count >= 1:
        return 5.0
    else:
        return 0.0

# ─────────────────────────────────────────
# 최저가율 점수 (최대 40점)
# 낮을수록 할인율이 높아 점수 높음
# ─────────────────────────────────────────
def score_bid_rate(bid_rate: float) -> float:
    if bid_rate <= 0:
        return 0.0
    elif bid_rate <= 0.2:
        return 40.0
    elif bid_rate <= 0.3:
        return 35.0
    elif bid_rate <= 0.4:
        return 30.0
    elif bid_rate <= 0.5:
        return 25.0
    elif bid_rate <= 0.6:
        return 18.0
    elif bid_rate <= 0.7:
        return 12.0
    elif bid_rate <= 0.8:
        return 6.0
    elif bid_rate <= 0.9:
        return 3.0
    else:
        return 0.0

# ─────────────────────────────────────────
# 지역 점수 (최대 20점)
# 수요 많은 지역일수록 높음
# ─────────────────────────────────────────
SIDO_SCORE = {
    "서울": 20,
    "경기": 16,
    "인천": 14,
    "부산": 13,
    "대구": 11,
    "광주": 10,
    "대전": 10,
    "울산": 9,
    "세종": 9,
    "충남": 7,
    "충북": 7,
    "경남": 7,
    "경북": 6,
    "전북": 6,
    "전남": 5,
    "강원": 5,
    "제주": 8,
}

def score_sido(sido: str) -> float:
    return float(SIDO_SCORE.get(sido, 5))

# ─────────────────────────────────────────
# 물건종류 점수 (최대 10점)
# ─────────────────────────────────────────
PROPERTY_SCORE = {
    "아파트": 10,
    "오피스텔": 9,
    "다세대": 8,
    "다가구": 7,
    "단독주택": 7,
    "근린생활시설": 6,
    "상가": 6,
    "토지": 5,
    "공장": 4,
    "창고": 3,
}

def score_property_type(property_type: str) -> float:
    if not property_type:
        return 3.0
    for key, score in PROPERTY_SCORE.items():
        if key in property_type:
            return float(score)
    return 3.0

# ─────────────────────────────────────────
# 종합 점수 계산
# ─────────────────────────────────────────
def calculate_score(row: Dict) -> Dict:
    fail_count = extract_fail_count(row.get("status", ""))
    bid_rate = calculate_bid_rate(row)

    s_fail = score_fail_count(fail_count)
    s_bid = score_bid_rate(bid_rate)
    s_sido = score_sido(row.get("sido", ""))
    s_type = score_property_type(row.get("property_type", ""))

    total = s_fail + s_bid + s_sido + s_type

    return {
        **row,
        "fail_count": fail_count,
        "bid_rate": round(bid_rate, 4),
        "score_fail": s_fail,
        "score_bid": s_bid,
        "score_sido": s_sido,
        "score_type": s_type,
        "total_score": round(total, 1),
    }

def score_batch(rows: List[Dict]) -> List[Dict]:
    scored = [calculate_score(r) for r in rows]
    scored.sort(key=lambda x: x["total_score"], reverse=True)
    return scored

def get_top20(rows: List[Dict]) -> List[Dict]:
    scored = score_batch(rows)
    return scored[:20]
