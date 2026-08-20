"""대표 사진 URL 규칙과 배치 조회 (2026-08-20 Sprint 224).

## 왜 모듈 하나로 모으는가

`/api/v1/item/{id}/images/{seq}` 라는 경로 규칙이 저장소 안에 **세 번 따로** 적혀
있었다 — `api/v1/item.py:_image_url()`, `api/v1/search.py:row_to_item()` 안의
`"%s/api/v1/item/%d/images/%d"` 문자열, 그리고 이제 관심물건/최근 본 물건까지 하면 넷이
된다. 이 규칙이 한 곳에서만 어긋나면 증상은 **"목록에는 사진이 나오는데 열면 404"** 다.
화면은 정상으로 보이고(브라우저가 깨진 이미지를 숨기거나 회색 칸을 그린다) 로그도 조용해서
사람이 눈으로 발견하기 어려운 종류의 결함이다.

배치 조회(`MIN(seq) ... GROUP BY item_id`)도 마찬가지다. Sprint 145가 검색목록에
넣었는데, 다음 화면에서 무심코 물건마다 한 번씩 물으면 곧바로 N+1 이 된다 —
그리고 **그때도 화면은 똑같이 잘 보인다. 느려질 뿐이다.**

## "대표 사진"의 정의

순번(`seq`)이 가장 앞선 사진 한 장이다. 상세 API 가 `images[0]` 을 대표로 쓰는 것과
같은 규칙이어야 목록과 상세가 같은 사진을 보여 준다(`test_search.py` 가 이 동치를
실제 HTTP 로 확인한다).

## 없는 것과 못 찾은 것

사진이 없는 물건은 이 맵에 **키 자체가 없다.** 그래서 `thumbnail_url` 은 `None` 이
되고, 프런트는 `null` 일 때 썸네일 자리를 아예 만들지 않는다(빈 회색 칸을 남기지
않는다). 이 저장소의 사진 보유율은 아직 낮아서 이 구분이 화면 품질을 좌우한다.
"""

# 사진을 서빙하는 라우트는 `api/v1/images.py` 의 `@router.get("/item/{item_id}/images/{seq}")`
# 하나뿐이다. 이 문자열을 바꾸면 그쪽도 같이 바뀌어야 한다 —
# `test_asset_pipeline.py` 가 두 값이 어긋나면 실패하도록 잠가 둔다.
IMAGE_URL_TEMPLATE = "/api/v1/item/%d/images/%d"


def image_url(item_id: int, seq: int) -> str:
    """사진 1장의 서빙 URL. 목록·상세·어느 화면이든 이 함수만 쓴다."""
    return IMAGE_URL_TEMPLATE % (item_id, seq)


def fetch_thumbnail_seqs(conn, item_ids) -> dict:
    """물건 여러 건의 대표 사진 순번을 **쿼리 1회**로 가져온다.

    반환: `{item_id: seq}` — 사진이 있는 물건만 담긴다(없는 물건은 키가 없다).
    `item_ids` 가 비면 쿼리를 아예 내지 않는다(빈 `IN ()` 은 SQL 구문 오류다).
    """
    ids = list(item_ids)
    if not ids:
        return {}
    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT item_id, MIN(seq) AS seq FROM auction_image "
        f"WHERE item_id IN ({placeholders}) GROUP BY item_id",
        ids,
    ).fetchall()
    return {r["item_id"]: r["seq"] for r in rows}


def thumbnail_url(item_id: int, seqs: dict):
    """`fetch_thumbnail_seqs()` 결과에서 그 물건의 대표 사진 URL. 없으면 `None`."""
    seq = (seqs or {}).get(item_id)
    return image_url(item_id, seq) if seq is not None else None
