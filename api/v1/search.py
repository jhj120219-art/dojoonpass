import logging
from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError
from typing import Optional
from datetime import date
from storage.database import get_connection
from api.auth import decode_supabase_jwt
from api.constants import is_sqlite_int
from normalizer.normalizer import extract_sido
from intent.analyzer import (
    analyze_intent,
    INTENT_SIDO, INTENT_SIGUNGU, INTENT_DONG, INTENT_LOT_NUMBER,
    INTENT_FULL_ADDRESS, INTENT_MIXED,
)

logger = logging.getLogger(__name__)

router = APIRouter()
# item.py와 동일한 선택적 인증 패턴 — 로그인 안 해도 검색은 그대로 동작하고,
# 로그인한 경우에만 결과에 is_favorited를 채운다.
bearer_scheme = HTTPBearer(auto_error=False)


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

def row_to_item(row, favorited_ids=frozenset(), thumbnails=None) -> dict:
    """검색 결과 1건.

    `thumbnails`는 {item_id: seq} 형태로, **대표 사진이 있는 물건만** 담긴다
    (2026-08-17 Sprint 145). 기본값 None은 종전 동작과 같다 —
    `thumbnail_url`이 항상 키로는 존재하되 값이 null이 된다.

    ★ 기존 계약을 깨지 않는다: 키를 **추가만** 했고 기존 필드는 이름·의미 모두 그대로다
      (`docs/backend.md`의 "GET /api/v1/search 응답 필드명" 불변 규칙).
    """
    thumb_seq = (thumbnails or {}).get(row["id"])
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
        "is_favorited": row["id"] in favorited_ids,
        # 대표 사진(가장 앞선 순번)의 서빙 URL. 사진이 없으면 null이다.
        # 경로 규칙은 `api/v1/item.py:_image_url()` / `api/v1/images.py` 라우트와 같아야
        # 한다 — 갈라지면 "목록에는 나오는데 열면 404"가 된다.
        "thumbnail_url": ("/api/v1/item/%d/images/%d" % (row["id"], thumb_seq)
                          if thumb_seq is not None else None),
    }

# ---------------------------------------------------------------------------
# 물건종류 어휘 별칭 (docs/BUGS.md #33)
# ---------------------------------------------------------------------------
# 문제: 검색 UI(`src/components/PropertyTypeTree.tsx`)의 물건종류 69개 중 62개가 항상
# 0건이었다. UI 어휘는 Tank Auction 검색폼 HTML을 전수 복사한 것이고, DB의
# `auction_item.property_type`은 크롤러가 courtauction.go.kr의 "물건종류"를 **원문 그대로**
# 저장한 값이라 두 어휘가 다르다(2026-08-11 Sprint 51 전수 조사: 콤마 구분 **15개 토큰**,
# 공백/NULL/표기 흔들림 0건 — 데이터 자체는 완전히 깨끗하다).
#
# 정확한 실패 메커니즘은 **LIKE 방향**이다. 매칭은 `property_type LIKE '%<입력>%'`인데,
# UI 값이 DB 토큰보다 **더 길다**:
#     '%다세대주택%'  vs  DB '다세대'   -> 패턴이 값보다 길어 절대 매치 불가
#     '%근린생활시설%' vs  DB '근린시설'  -> 동일
# 반대로 UI 값이 DB 토큰과 정확히 같거나(연립주택/아파트/임야/대지/기타…) 더 짧으면
# (전/답 -> '전답') 지금도 정상 동작한다. 즉 버그는 어휘 전사(transcription) 불일치이지
# 데이터 오염이나 정규화 실패가 아니다.
#
# 해결: 아래 표로 **입력을 확장**한다. 원래 패턴은 그대로 두고 별칭 패턴을 OR로 덧붙이므로
# **순수 가산(additive)** 이다 — 기존에 매치되던 행은 하나도 빠지지 않는다(응답 구조·파라미터명
# 무변경, `docs/CLAUDE.md`의 기존 API 유지 원칙 충족).
#
# 별칭을 넣는 기준(임의 확장 금지):
#   - 두 어휘가 **같은 실제 카테고리**를 가리키는 것이 명백할 때만 넣는다.
#   - 개별 차종(승용차/승합차/버스/화물차/기타차량/덤프트럭)은 **넣지 않는다** —
#     DB에는 차종 구분 없이 '자동차' 하나뿐이라, 매핑하면 "승용차"를 고른 사용자에게
#     화물차가 나온다(제품 의미 훼손). 차종 구분은 데이터가 생겨야 가능하다.
#   - DB에 대응 토큰이 없는 UI 항목(도시형생활주택/기숙사/공장/선박/광업권 …)은 별칭 없이
#     0건을 유지한다. 그건 버그가 아니라 "해당 물건이 아직 없다"는 사실이다.
#
# 복합값 처리: DB는 다목적 물건을 `'상가,오피스텔,근린시설'`처럼 콤마로 합쳐 저장한다.
# LIKE 부분일치라 별칭 하나로 이런 복합값도 자연히 잡힌다 — 이는 새 규칙이 아니라
# 이미 `연립주택`이 `'연립주택,다세대,빌라'`를, `단독주택`이 `'단독주택,다가구주택'`을
# 잡고 있던 기존 동작과 **완전히 같은 방식**이다.
PROPERTY_TYPE_ALIASES = {
    # 주거용 — 법원 표기가 "OO주택"의 축약형이다
    "다세대주택": ["다세대"],
    "오피스텔(주거)": ["오피스텔"],
    # 상업 및 산업용
    "근린생활시설": ["근린시설"],   # 법정 용어 "제1·2종 근린생활시설"의 법원 축약 표기
    "오피스텔(상업)": ["오피스텔"],
    "근린상가": ["상가"],           # 트리에서 법원 '상가' 토큰에 대응하는 유일한 항목
    "자동차관련": ["자동차"],       # 차종 무관 자동차 전체를 뜻하므로 1:1 대응
    # 차량 및 중장비
    "기타중기": ["중기"],
}


# 한 번에 선택 가능한 물건종류 개수 상한. UI 트리의 전체 항목이 69개라 여유가 있다.
MAX_PROPERTY_TYPES = 100


def _property_type_patterns(types):
    """
    입력된 물건종류 목록을 **원본 + 별칭**으로 확장한다(순서 유지, 중복 제거).
    원본이 항상 먼저 들어가므로 기존 매칭 결과는 그대로 보존된다.
    """
    patterns = []
    for t in types:
        for candidate in [t] + PROPERTY_TYPE_ALIASES.get(t, []):
            if candidate not in patterns:
                patterns.append(candidate)
    return patterns


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
    include_closed: bool = Query(False),
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
):
    # sort_by/sort_order는 기존에 미등록 값을 조용히 기본값으로 폴백하고 있었다.
    # 안정성을 위해 여기서만 명시적으로 거부하고, 그 외 검색 조건/SQL 로직은 그대로 둔다.
    if sort_by is not None and sort_by not in SORT_COLUMNS:
        raise HTTPException(status_code=400, detail=f"허용되지 않는 sort_by 값입니다: {sort_by}")
    if sort_order is not None and str(sort_order).lower() not in ("asc", "desc"):
        raise HTTPException(status_code=400, detail=f"허용되지 않는 sort_order 값입니다: {sort_order}")

    # property_type은 콤마로 몇 개든 받는 구조라, 토큰 수만큼 LIKE 절이 늘어난다.
    # 실측(2026-08-11 Sprint 51): 500개까지는 정상(30ms)이지만 **2,000개를 보내면 SQLite의
    # 표현식/변수 한계에 걸려 500**이 났다. 클라이언트 입력으로 서버 오류를 만들 수 있는 상태다.
    # UI(PropertyTypeTree)가 낼 수 있는 최대는 69개이므로 100개면 정상 사용에는 여유가 있고,
    # 위 sort_by/sort_order와 동일한 방식(400 + 사유)으로 명확히 거부한다.
    # (별칭 확장은 고정된 소수만 더하므로 이 한계와 무관하다 — 원래부터 있던 견고성 공백이다.)
    if property_type and property_type.count(",") + 1 > MAX_PROPERTY_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"물건종류는 최대 {MAX_PROPERTY_TYPES}개까지 선택할 수 있습니다",
        )

    # 2026-08-17 Sprint 146: SQLite INTEGER 범위 밖의 숫자 조건은 **인증 없이 500**을
    # 만들 수 있었다. 파이썬 int는 무한 정밀도인데 SQLite INTEGER는 64비트라, 그대로
    # 바인딩하면 `OverflowError: Python int too large to convert to SQLite INTEGER`다.
    #
    # 실측(수정 전) — 전부 공개 경로, 토큰 불필요:
    #
    #     /api/v1/search?min_appraisal=9999999999999999999999999   500
    #     ?max_appraisal= / ?min_bid_price= / ?max_bid_price=       500
    #     ?min_fail_count= / ?max_fail_count=                      500
    #     ?page=9999999999999999999999999                          500
    #
    # `size`만 무사했다 — `Query(20, ge=1, le=100)`이 이미 막고 있었다. 나머지 숫자
    # 파라미터에는 상한이 없었다.
    #
    # Sprint 144가 `item_id`에 대해 같은 계열을 고친 `is_sqlite_int()`를 **그대로 쓴다**
    # (새 헬퍼를 만들지 않는다). 다만 상태 코드는 다르다 — 거기서는 "존재할 수 없는 id"라
    # 404가 맞았지만, 여기서는 **검색 조건 값**이므로 이 엔드포인트가 이미 쓰고 있는
    # 400(사유 포함)과 같은 방식으로 거절한다(위 sort_by / property_type과 동일한 규약).
    for _name, _value in (
        ("min_appraisal", min_appraisal), ("max_appraisal", max_appraisal),
        ("min_bid_price", min_bid_price), ("max_bid_price", max_bid_price),
        ("min_fail_count", min_fail_count), ("max_fail_count", max_fail_count),
    ):
        if _value is not None and not is_sqlite_int(_value):
            raise HTTPException(
                status_code=400,
                detail=f"{_name} 값이 허용 범위를 벗어났습니다",
            )

    # page는 값 자체가 아니라 **곱한 결과**가 넘친다 — OFFSET은 `(page-1)*size`다.
    # 실측: page=2**63-1은 값으로는 SQLite 범위 안이지만 size를 곱하는 순간 넘쳐 500이었다.
    # 그래서 page 자체가 아니라 계산된 offset을 검사한다.
    if not is_sqlite_int((page - 1) * size):
        raise HTTPException(status_code=400, detail="page 값이 허용 범위를 벗어났습니다")

    # item.py와 동일한 선택적 인증: 토큰이 없거나 유효하지 않으면 비로그인으로 취급하고
    # 검색 자체는 그대로 진행한다(검증 실패가 검색 API를 막으면 안 됨).
    user_id = None
    if credentials:
        # 예전에는 bare except라 KeyboardInterrupt/SystemExit까지 삼켰고 원인도 남지 않았다.
        try:
            # ES256(JWKS) / HS256(레거시)을 함께 다루는 공용 검증기 — api/auth.py 참고.
            # 예전에는 HS256만 검증해서, 로그인 사용자의 검색 결과에도 is_favorited가
            # 항상 false로 내려갔다(하트가 전부 빈 하트로 보이던 증상, docs/BUGS.md #27).
            payload = decode_supabase_jwt(credentials.credentials)
            user_id = payload.get("sub")
        except JWTError:
            logger.debug("search: 토큰 검증 실패 ― 비로그인으로 처리")
            user_id = None

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
                # UI 어휘 <-> 법원 원문 어휘 차이를 별칭으로 흡수한다(위 PROPERTY_TYPE_ALIASES).
                # 원본 패턴이 그대로 포함되므로 기존 결과는 줄지 않는다(순수 가산).
                patterns = _property_type_patterns(types)
                or_clause = " OR ".join(["property_type LIKE ?"] * len(patterns))
                conditions.append(f"({or_clause})")
                params.extend(f"%{p}%" for p in patterns)
        if court_name:
            conditions.append("court_name LIKE ?")
            params.append(f"%{court_name}%")
        if status:
            conditions.append("status LIKE ?")
            params.append(f"%{status}%")
        if auction_date_from:
            conditions.append("auction_date >= ?")
            params.append(auction_date_from)
        elif not include_closed:
            # D7: 종결물건 기본 제외. auction_date_from을 명시한 호출은 그 값을 그대로
            # 신뢰하고 이 기본 필터를 적용하지 않는다(기존 호출과의 호환 유지).
            conditions.append("auction_date >= ?")
            params.append(date.today().isoformat())
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
        # id를 동률 결정자로 끝에 붙인다(Sprint 26 - payments/favorites/recent_items/
        # registry_requests/search_presets에 이미 적용된 것과 같은 규칙, 방향은 주 정렬과
        # 맞춘다). 2026-08-15 Sprint 122 실측: 이 라우트만 그 정리에서 빠져 있었다 -
        # 기본 정렬(auction_date, fail_count) 동률 그룹이 실 데이터에 최대 27건까지
        # 있고(예: 2026-07-28 + fail_count=1), minimum_bid_price 동률도 최대 8건 있다.
        # offset 페이지네이션에서 동률이 페이지 경계에 걸치면 같은 물건이 두 페이지에
        # 중복 노출되거나 아예 빠질 수 있다 - 검색은 이 서비스의 가장 흔한 진입점이라
        # 영향 범위가 다른 어떤 목록보다 크다.
        order_clause = (
            f"{order_col} {order_dir}, id {order_dir}" if order_col
            # 기본 정렬은 sort_by가 없을 때만 타므로 order_dir(sort_order)와 무관하게
            # 고정이다 - 여기서도 고정 DESC로 맞춘다(order_dir을 섞으면 sort_by 없이
            # sort_order만 준 요청에서 주 정렬은 그대로인데 동률 방향만 바뀌는 상태가 된다).
            else "auction_date DESC, fail_count DESC, id DESC"
        )

        offset = (page - 1) * size
        rows = conn.execute(
            f"SELECT * FROM auction_item WHERE {where} "
            f"ORDER BY {order_clause} LIMIT ? OFFSET ?",
            params + [size, offset]
        ).fetchall()

        # 로그인 유저에 한해, 이 페이지에 나온 id들의 찜 여부를 배치 조회 1회로 확인한다
        # (아이템별 개별 조회 없음 → N+1 아님). item.py:52-56의 단일 조회 패턴을 배치로 확장.
        favorited_ids = set()
        if user_id and rows:
            ids = [r["id"] for r in rows]
            placeholders = ",".join("?" * len(ids))
            fav_rows = conn.execute(
                f"SELECT item_id FROM favorites WHERE user_id = ? AND item_id IN ({placeholders})",
                [user_id] + ids
            ).fetchall()
            favorited_ids = {r["item_id"] for r in fav_rows}

        # 이 페이지 물건들의 **대표 사진**을 배치 조회 1회로 가져온다 (2026-08-17 Sprint 145).
        # 바로 위 favorites 배치 조회와 같은 패턴이다 — 물건마다 따로 물으면 곧바로 N+1이
        # 되고, 한 페이지가 최대 size건이므로 그 비용이 페이지 크기에 비례해 늘어난다.
        #
        # 대표 = 순번이 가장 앞선 사진. `MIN(seq)`로 물건당 한 행만 받는다
        # (`api/v1/item.py`가 상세에서 `images[0]`을 대표로 쓰는 것과 같은 규칙).
        thumbnails = {}
        if rows:
            ids = [r["id"] for r in rows]
            placeholders = ",".join("?" * len(ids))
            thumb_rows = conn.execute(
                f"SELECT item_id, MIN(seq) AS seq FROM auction_image "
                f"WHERE item_id IN ({placeholders}) GROUP BY item_id",
                ids
            ).fetchall()
            thumbnails = {r["item_id"]: r["seq"] for r in thumb_rows}

        return {
            "total": total,
            "page": page,
            "size": size,
            "total_pages": (total + size - 1) // size,
            "items": [row_to_item(r, favorited_ids, thumbnails) for r in rows],
        }
    except HTTPException:
        raise
    except Exception as e:
        # 2026-08-18 Sprint 188: 원인을 로그에 남기지 않고 곧바로 HTTPException으로
        # 바꿔 던지고 있었다 — FastAPI는 HTTPException을 "의도된 응답"으로 취급해
        # 트레이스백을 찍지 않으므로, 실제 원인(예: 테이블 누락 같은 서버측 결함)이
        # 서버 로그 어디에도 남지 않고 사용자에게 보이는 일반 오류 문구만 남았다
        # (BUGS #117 실측 과정에서 발견 — `payments.py`의 웹훅 처리는 이미
        # `logger.exception()`을 쓰고 있어 같은 저장소 안에서도 일관되지 않았다).
        logger.exception("검색 처리 중 오류 (sido=%r, court_name=%r, page=%r, size=%r)",
                          sido, court_name, page, size)
        raise HTTPException(status_code=500, detail="검색 처리 중 오류가 발생했습니다") from e
    finally:
        conn.close()


@router.get("/search/regions")
def get_regions(sido: str = Query(...)):
    """
    선택한 sido에 실제로 존재하는 sigungu 목록을 반환한다 (읽기 전용, 데이터 교정 없음).
    /search와 마찬가지로 인증 불필요 라우트라 {"success","data","message"} envelope를 쓰지 않는다.
    """
    # ★ 2026-08-17 Sprint 156: `/search`와 **같은 정규화**를 쓴다.
    #
    #   `/search`는 위(289~294행)에서 `extract_sido(sido) or sido`로 정규화하는데
    #   여기만 원본을 그대로 `WHERE sido = ?`에 넣고 있었다. 같은 파라미터를 두 엔드포인트가
    #   다르게 해석하니 실측상 이렇게 갈렸다:
    #
    #       sido=서울        regions 26건   search.total 9     <- 일치
    #       sido=서울특별시   regions  0건   search.total 9     <- 어긋남
    #       sido=서울시      regions  0건   search.total 9     <- 어긋남
    #       sido=경기도      regions  0건   search.total 0
    #
    #   지금 화면은 `SIDO_LIST`가 축약형("서울")을 보내므로 드러나지 않는다. 그러나
    #   검색 화면은 **URL 파라미터로 상태를 복원한다**(`SearchForm.tsx:190`
    #   `searchParams.get('sido')` -> 277행에서 그 값으로 regions 조회). 따라서
    #   `?sido=서울특별시`가 담긴 링크를 열면 **결과는 9건 나오는데 시/군/구 목록만 비어**
    #   지역을 좁힐 수 없다. 사용자에게는 "왜 구가 안 뜨지"로 보인다.
    #
    #   새 정책을 만드는 것이 아니다 — 위 주석이 이미 정한 규약을 이 함수에도 적용할 뿐이다.
    #   `extract_sido`가 못 알아들으면 원본을 그대로 쓰는 fallback도 동일하다.
    normalized_sido = extract_sido(sido) or sido
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT DISTINCT sigungu FROM auction_item "
            "WHERE sido = ? AND sigungu IS NOT NULL AND sigungu != '' "
            "ORDER BY sigungu",
            (normalized_sido,),
        ).fetchall()
        # 응답의 `sido`는 **요청받은 값 그대로** 돌려준다(정규화한 값이 아니다).
        # 조회에만 정규화를 쓰고 응답 형태는 건드리지 않는다 — 이 필드를 바꾸는 것은
        # 별개의 API 계약 변경이고, 이번 수정의 목적(빈 시/군/구 목록)과 무관하다.
        # 확인: 프런트는 `data.sigungu`만 읽는다. 경합 방지는 응답의 sido 비교가 아니라
        # 로컬 `sigunguKey` + `cancelled` 플래그로 한다(`SearchForm.tsx:265,274-287`).
        return {"sido": sido, "sigungu": [r["sigungu"] for r in rows]}
    except Exception as e:
        # 위 /search 핸들러와 같은 이유(2026-08-18 Sprint 188) — HTTPException으로
        # 바로 바꿔 던지면 FastAPI가 트레이스백을 안 찍어 원인이 로그에 안 남는다.
        logger.exception("지역 목록 조회 중 오류 (sido=%r)", sido)
        raise HTTPException(status_code=500, detail="지역 목록 조회 중 오류가 발생했습니다") from e
    finally:
        conn.close()
