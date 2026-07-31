from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from storage.database import get_connection
from normalizer.normalizer import extract_sido
from intent.analyzer import (
    analyze_intent,
    INTENT_SIDO, INTENT_SIGUNGU, INTENT_DONG, INTENT_LOT_NUMBER,
    INTENT_FULL_ADDRESS, INTENT_MIXED,
)

router = APIRouter()


def _address_detail_condition(address_detail: str):
    """
    address_detail 입력의 검색 의도(Intent)를 판별해 SQL 조건과 파라미터를 생성한다.
    구조화할 수 없는 입력(UNKNOWN, 건물명/도로명 등)은 기존 방식(full_address LIKE)을
    그대로 유지해 기존에 되던 검색을 깨뜨리지 않는다.
    """
    result = analyze_intent(address_detail)
    intent = result["intent"]
    parsed = result["parsed"]
    residual = result["residual"]

    if intent == INTENT_SIDO:
        return "sido = ?", [parsed["sido"]]
    if intent == INTENT_SIGUNGU:
        return "sigungu LIKE ?", [f"%{parsed['sigungu']}%"]
    if intent == INTENT_DONG:
        return "dong LIKE ?", [f"%{parsed['dong']}%"]
    if intent == INTENT_LOT_NUMBER:
        return "lot_number = ?", [parsed["lot_number"]]
    if intent == INTENT_FULL_ADDRESS:
        return (
            "sido = ? AND sigungu LIKE ? AND dong LIKE ?",
            [parsed["sido"], f"%{parsed['sigungu']}%", f"%{parsed['dong']}%"],
        )
    if intent == INTENT_MIXED:
        sub_conditions = []
        sub_params = []
        if parsed["sido"]:
            sub_conditions.append("sido = ?")
            sub_params.append(parsed["sido"])
        if parsed["sigungu"]:
            sub_conditions.append("sigungu LIKE ?")
            sub_params.append(f"%{parsed['sigungu']}%")
        if parsed["dong"]:
            sub_conditions.append("dong LIKE ?")
            sub_params.append(f"%{parsed['dong']}%")
        if residual:
            sub_conditions.append("full_address LIKE ?")
            sub_params.append(f"%{residual}%")
        if sub_conditions:
            return "(" + " AND ".join(sub_conditions) + ")", sub_params
        # 구조화 가능한 필드가 하나도 없으면(이론상 UNKNOWN으로 분류되어 도달하지
        # 않지만) 아래 기존 방식으로 안전하게 폴백한다.

    # UNKNOWN(건물명/도로명 등) — 기존 방식 그대로 유지
    return "full_address LIKE ?", [f"%{address_detail}%"]

def row_to_item(row) -> dict:
    return {
        "id": row["id"],
        "case_no": row["case_no"],
        "item_no": row["item_no"],
        "court_name": row["court_name"],
        "property_type": row["property_type"],
        "sido": row["sido"],
        "sigungu": row["sigungu"],
        "dong": row["dong"],
        "full_address": row["full_address"],
        "appraisal_price": row["appraisal_price"],
        "minimum_bid_price": row["minimum_bid_price"],
        "bid_rate": row["bid_rate"],
        "auction_date": row["auction_date"],
        "status": row["status"],
        "fail_count": row["fail_count"],
        "validation_status": row["validation_status"],
        "crawl_date": row["crawl_date"],
    }

# 정렬 파라미터 화이트리스트 (컬럼명을 쿼리 문자열에 직접 삽입하지 않기 위한 매핑)
SORT_COLUMNS = {
    "auction_date": "auction_date",
    "appraisal_price": "appraisal_price",
    "minimum_bid_price": "minimum_bid_price",
    "bid_rate": "bid_rate",
    "fail_count": "fail_count",
    "crawl_date": "crawl_date",
    "case_no": "case_no",
    "full_address": "full_address",
}

@router.get("/search")
def search(
    case_no: Optional[str] = Query(None),
    sido: Optional[str] = Query(None),
    sigungu: Optional[str] = Query(None),
    dong: Optional[str] = Query(None),
    address_detail: Optional[str] = Query(None),
    property_type: Optional[str] = Query(None),
    court_name: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    auction_date_from: Optional[str] = Query(None),
    auction_date_to: Optional[str] = Query(None),
    min_appraisal: Optional[int] = Query(None),
    max_appraisal: Optional[int] = Query(None),
    min_bid_price: Optional[int] = Query(None),
    max_bid_price: Optional[int] = Query(None),
    min_bid_rate: Optional[float] = Query(None),
    max_bid_rate: Optional[float] = Query(None),
    min_fail_count: Optional[int] = Query(None),
    max_fail_count: Optional[int] = Query(None),
    sort_by: Optional[str] = Query(None),
    sort_order: Optional[str] = Query("desc"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    # sort_by/sort_order는 기존에 미등록 값을 조용히 기본값으로 폴백하고 있었다.
    # 안정성을 위해 여기서만 명시적으로 거부하고, 그 외 검색 조건/SQL 로직은 그대로 둔다.
    if sort_by is not None and sort_by not in SORT_COLUMNS:
        raise HTTPException(status_code=400, detail=f"허용되지 않는 sort_by 값입니다: {sort_by}")
    if sort_order is not None and str(sort_order).lower() not in ("asc", "desc"):
        raise HTTPException(status_code=400, detail=f"허용되지 않는 sort_order 값입니다: {sort_order}")

    conn = get_connection()
    try:
        conditions = ["1=1"]
        params = []

        if case_no:
            conditions.append("case_no LIKE ?")
            params.append(f"%{case_no}%")
        if sido:
            # "서울시"/"서울특별시"처럼 축약 코드가 아닌 표기로 와도, auction_item.sido에
            # 저장된 축약 코드("서울" 등)와 매치되도록 검색 진입 시에만 정규화한다.
            # extract_sido가 못 알아들으면(빈 문자열) 원본 입력을 그대로 사용해 기존 동작을 보존한다.
            conditions.append("sido = ?")
            params.append(extract_sido(sido) or sido)
        if sigungu:
            conditions.append("sigungu LIKE ?")
            params.append(f"%{sigungu}%")
        if dong:
            conditions.append("dong LIKE ?")
            params.append(f"%{dong}%")
        if address_detail:
            addr_sql, addr_params = _address_detail_condition(address_detail)
            conditions.append(addr_sql)
            params.extend(addr_params)
        if property_type:
            # 다중 물건종류 선택 시 콤마로 join되어 들어온다("아파트,오피스텔(주거)").
            # 콤마가 없는 기존 단일값 호출도 1개짜리 리스트가 되어 동일하게 동작한다.
            types = [t.strip() for t in property_type.split(",") if t.strip()]
            if types:
                or_clause = " OR ".join(["property_type LIKE ?"] * len(types))
                conditions.append(f"({or_clause})")
                params.extend(f"%{t}%" for t in types)
        if court_name:
            conditions.append("court_name LIKE ?")
            params.append(f"%{court_name}%")
        if status:
            conditions.append("status LIKE ?")
            params.append(f"%{status}%")
        if auction_date_from:
            conditions.append("auction_date >= ?")
            params.append(auction_date_from)
        if auction_date_to:
            conditions.append("auction_date <= ?")
            params.append(auction_date_to)
        if min_appraisal is not None:
            conditions.append("appraisal_price >= ?")
            params.append(min_appraisal)
        if max_appraisal is not None:
            conditions.append("appraisal_price <= ?")
            params.append(max_appraisal)
        if min_bid_price is not None:
            conditions.append("minimum_bid_price >= ?")
            params.append(min_bid_price)
        if max_bid_price is not None:
            conditions.append("minimum_bid_price <= ?")
            params.append(max_bid_price)
        if min_bid_rate is not None:
            conditions.append("bid_rate >= ?")
            params.append(min_bid_rate)
        if max_bid_rate is not None:
            conditions.append("bid_rate <= ?")
            params.append(max_bid_rate)
        if min_fail_count is not None:
            conditions.append("fail_count >= ?")
            params.append(min_fail_count)
        if max_fail_count is not None:
            conditions.append("fail_count <= ?")
            params.append(max_fail_count)

        where = " AND ".join(conditions)
        total = conn.execute(
            f"SELECT COUNT(*) FROM auction_item WHERE {where}", params
        ).fetchone()[0]

        order_col = SORT_COLUMNS.get(sort_by)
        order_dir = "ASC" if str(sort_order).lower() == "asc" else "DESC"
        order_clause = (
            f"{order_col} {order_dir}" if order_col
            else "auction_date DESC, fail_count DESC"
        )

        offset = (page - 1) * size
        rows = conn.execute(
            f"SELECT * FROM auction_item WHERE {where} "
            f"ORDER BY {order_clause} LIMIT ? OFFSET ?",
            params + [size, offset]
        ).fetchall()

        return {
            "total": total,
            "page": page,
            "size": size,
            "total_pages": (total + size - 1) // size,
            "items": [row_to_item(r) for r in rows],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="검색 처리 중 오류가 발생했습니다") from e
    finally:
        conn.close()


@router.get("/search/regions")
def get_regions(sido: str = Query(...)):
    """
    선택한 sido에 실제로 존재하는 sigungu 목록을 반환한다 (읽기 전용, 데이터 교정 없음).
    /search와 마찬가지로 인증 불필요 라우트라 {"success","data","message"} envelope를 쓰지 않는다.
    """
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT DISTINCT sigungu FROM auction_item "
            "WHERE sido = ? AND sigungu IS NOT NULL AND sigungu != '' "
            "ORDER BY sigungu",
            (sido,),
        ).fetchall()
        return {"sido": sido, "sigungu": [r["sigungu"] for r in rows]}
    except Exception as e:
        raise HTTPException(status_code=500, detail="지역 목록 조회 중 오류가 발생했습니다") from e
    finally:
        conn.close()
