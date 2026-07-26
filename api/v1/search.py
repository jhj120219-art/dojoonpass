from fastapi import APIRouter, Query
from typing import Optional
from storage.database import get_connection

router = APIRouter()

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
    conn = get_connection()
    try:
        conditions = ["1=1"]
        params = []

        if case_no:
            conditions.append("case_no LIKE ?")
            params.append(f"%{case_no}%")
        if sido:
            conditions.append("sido = ?")
            params.append(sido)
        if sigungu:
            conditions.append("sigungu LIKE ?")
            params.append(f"%{sigungu}%")
        if dong:
            conditions.append("dong LIKE ?")
            params.append(f"%{dong}%")
        if address_detail:
            conditions.append("full_address LIKE ?")
            params.append(f"%{address_detail}%")
        if property_type:
            conditions.append("property_type LIKE ?")
            params.append(f"%{property_type}%")
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
    finally:
        conn.close()
