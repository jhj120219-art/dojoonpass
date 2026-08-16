# Sprint 123 ― 가장 많이 쓰는 목록(`/api/v1/search`)이 Sprint 26 정리에서 빠져 있었다 (2026-08-15)

> 앞 Sprint: `docs/SPRINT122_MIGRATION_DRIFT.md`
>
> **별도 파일 이유**: Sprint 100~122와 같다 ― `docs/BUGS.md` / `docs/CURRENT_STATE.md`는
> 다른 세션의 편집 대상이라 충돌을 피했다.

Sprint 26(`docs/BUGS.md` #16)이 "정렬 비결정성"을 전 도메인에 일괄 수정했다고 기록돼
있다 ― payments/favorites/recent_items/registry_requests/search_presets 목록에
`ORDER BY ..., id DESC`를 붙였다. **`api/v1/search.py`(가장 많이 쓰는 목록)는 그
정리에서 빠져 있었다.**

---

## 발견

```python
# api/v1/search.py (수정 전)
order_clause = (
    f"{order_col} {order_dir}" if order_col
    else "auction_date DESC, fail_count DESC"
)
```

기본 정렬도 커스텀 정렬(`sort_by=minimum_bid_price` 등)도 `id`로 전순서를 잡지 않는다.
실 DB에 동률이 실제로 크다.

```
auction_date + fail_count 동률(기본 정렬)  최대 27건 (예: 2026-07-28 + fail_count=1)
minimum_bid_price 동률(커스텀 정렬 예시)   최대 8건
```

기본 페이지 크기(20)보다 큰 동률 그룹이 있으므로 페이지 경계에 걸치기 쉽다.

## 고친 것

```python
order_clause = (
    f"{order_col} {order_dir}, id {order_dir}" if order_col
    else "auction_date DESC, fail_count DESC, id DESC"
)
```

Sprint 26과 같은 규칙(방향은 주 정렬과 맞춘다)을 그대로 적용했다. 기본 정렬 쪽은
`sort_by` 없이 `sort_order`만 오는 요청에서 주 정렬(고정 DESC)과 동률 방향이
갈라지지 않도록 `id`도 고정 `DESC`로 뒀다(`order_dir`을 그대로 쓰면 그 조합에서만
주 정렬과 동률 방향이 어긋난다).

## 회귀 테스트 ― 그리고 정직하게 남기는 한계

`test_api_regression.py`에 §13-B를 신설했다(Sprint 26 §13이 다루지 않던 `/api/v1/search`
전용). QA 사건번호로 격리한 물건 5개를 전부 동률로 만들고, 작은 페이지 크기(2)로
전부 순회해 중복/누락이 없는지, 반복 호출에도 순서가 흔들리지 않는지 확인한다.
기본 정렬과 커스텀 정렬(minimum_bid_price) 둘 다 검증한다.

**변이 검증은 시도했지만 이 정적 단일 커넥션 테스트 환경에서는 재현되지 않았다.**
tie-break를 제거한 뒤 같은 테스트를 돌려도 순서가 흔들리지 않았다 ― `EXPLAIN QUERY
PLAN`으로 원인을 확인했다.

```
SCAN auction_item USING INDEX idx_auction_item_default_sort
```

SQLite는 인덱스 스캔에서 인덱스 컬럼이 동률이면 **암묵적으로 rowid로 전순서를
매긴다**(B-tree 저장 순서 자체가 그렇다). 쓰기가 끼어들지 않는 단일 프로세스 반복
호출로는 이 암묵적 순서가 흔들리지 않아, 표면적으로는 "버그가 없는 것처럼" 보인다.

**그래도 고친 이유:**

1. 이건 SQL 표준이 보장하는 동작이 아니라 SQLite 구현 세부사항이다 ― 인덱스 선택이
   바뀌거나(데이터가 늘어 플래너가 다른 인덱스를 고르면), SQLite 버전이 바뀌거나,
   동시 쓰기(크롤러의 일간 갱신)가 페이지 조회 사이에 끼면 암묵적 안정성이 깨질 수
   있다 ― 그 순간에만 재현되는 결함은 지금 당장 재현 안 된다고 없는 게 아니다.
2. Sprint 26이 **정확히 같은 근거**("SQLite가 보장하지 않는다")로 다른 다섯 곳을
   고쳤다. 이 라우트만 다른 기준을 적용할 이유가 없다.
3. `id` 명시적 tie-break는 이 저장소가 이미 확립한 관례다. 관례를 벗어난 자리가
   있으면(전수 검색으로 찾았다) 맞추는 것 자체로 일관성 가치가 있다 ― 가장 많이
   쓰이는 목록일수록 더 그렇다.

이 세션의 "변이로 실제 검출 확인" 원칙에 못 미치는 케이스라는 것을 그대로 남긴다 ―
검사를 통과시키려고 결과를 부풀리지 않는다.

## 검증

| 항목 | 결과 |
|---|---|
| `test_search.py` | 58/58 통과 (기존 검색 동작 무변경 확인) |
| `test_api_regression.py` | 전체 통과, §13-B(신설) 포함 |
| `python -m compileall` | exit 0 |
| 변이 시도 | tie-break 제거 후 재현 안 됨(원인: SQLite 인덱스 스캔의 암묵적 rowid 순서, 위 설명 참고) - 원복 확인 |
| 실 DB | 테스트가 만든 QA 픽스처(5행)는 자체 cleanup으로 0건 확인, 그 외 쓰기 없음 |

## 수정 파일

```
api/v1/search.py             기본/커스텀 정렬에 id tie-break 추가
test_api_regression.py       §13-B(search 정렬 결정성) 신설
docs/SPRINT123_SEARCH_SORT_TIEBREAK.md   신규 (본 문서)
```

**Breaking Change 아님** ― 응답 구조/파라미터 무변경. 동률이 아닌 기존 정렬 결과는
그대로다(추가된 tie-break는 동률 구간 내부의 순서만 결정한다).

## 남은 Backlog

- 위 SKIP 표는 없음(승인 필요 항목 없이 완결).
- Sprint 105~122의 SKIP 표 항목들 (전부 승인/외부 조치 대기, 미해소)
