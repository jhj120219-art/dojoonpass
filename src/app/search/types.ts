// Search MVP DTO — search/00_SEARCH_MVP.md 기준
// 필드명은 api/v1/search.py의 기존 쿼리 파라미터명과 동일하게 맞춘다 (STEP3 연동 시 매핑 불필요하도록).

export type SearchQueryParams = {
  case_no?: string
  sido?: string
  sigungu?: string
  dong?: string
  address_detail?: string
  court_name?: string
  // 다중 물건종류 선택 시 배열(콤마join되어 URL에 실림), 단일 선택 시 문자열도 허용(하위호환)
  property_type?: string | string[]
  status?: string
  min_fail_count?: number
  max_fail_count?: number
  auction_date_from?: string
  auction_date_to?: string
  // 기본값(false)은 종결물건 제외(auction_date >= 오늘). true면 종결물건 포함.
  include_closed?: boolean
  min_appraisal?: number
  max_appraisal?: number
  min_bid_price?: number
  max_bid_price?: number
  min_bid_rate?: number
  max_bid_rate?: number
  // 면적 4종 — **2026-08-26 부터 백엔드가 실제로 읽는다** (2026-08-31 주석 정정).
  //   migration 025 가 `auction_item.building_area` / `land_area` 컬럼을,
  //   `normalizer.extract_areas()` 가 주소 원문에서 값을, `api/v1/search.py` 가
  //   WHERE 절을 맡는다. 결합 규칙은 **계열 안 AND / 계열 간 OR** 다 —
  //   한 물건은 두 면적 중 하나만 가지므로 AND 로 묶으면 항상 공집합이었다.
  //
  //   ★ 이 자리에는 2026-08-31 까지 "아래 4개 필드는 백엔드가 읽지 않는다"가 남아
  //     있었다. `SearchForm.tsx`(구현됨) 와 `tests/_search_param_contract.mjs`
  //     (목록에서 뺌) 는 이미 갱신됐는데 **이 파일만 옛 서술이었다.** 그 문장을 믿으면
  //     "죽은 파라미터니 지우자"로 갈 수 있어 실동작 필터가 사라진다.
  //     미지원 파라미터의 **단일 정본은 `tests/_search_param_contract.mjs` 의
  //     `KNOWN_UNSUPPORTED`** 이고, 이 파일이 그것과 어긋나면 소스 계약 검사가 실패한다.
  //
  //   알려진 한계(제품 판단, 미결): 면적 컬럼이 NULL 인 행은 결과에서 빠진다.
  //   다층 건물은 층별 합산, 지분 물건은 전체 면적이다. `docs/BUGS.md` #239.
  min_building_area?: number
  max_building_area?: number
  min_land_area?: number
  max_land_area?: number
  // 유일한 미지원 파라미터. `auction_item` 에도 `rights_summary` 에도 대응 데이터가
  // 없어 뽑아낼 원천 자체가 없다(면적과 다른 점이다). UI 는 "준비 중입니다".
  // 정본: tests/_search_param_contract.mjs 의 KNOWN_UNSUPPORTED
  special_conditions?: string[]
  // api/v1/search.py:SORT_COLUMNS 화이트리스트 8개와 정확히 일치해야 한다(2026-08-10
  // Sprint 43 — crawl_date가 백엔드는 지원하는데 여기 빠져 있던 불일치를 발견해 정정.
  // 다만 SortBar.tsx UI에 crawl_date 버튼을 추가할지는 별도 제품 판단이 필요해 이번에는
  // 타입 정확성만 맞추고 UI는 그대로 둔다).
  sort_by?: 'auction_date' | 'appraisal_price' | 'minimum_bid_price' | 'bid_rate' | 'fail_count' | 'crawl_date' | 'case_no' | 'full_address'
  sort_order?: 'asc' | 'desc'
  page?: number
  size?: number
}

// GET /api/v1/search 응답 아이템 (api/v1/search.py row_to_item 기준)
export type SearchResultItem = {
  id: number
  case_no: string
  item_no: string | null
  court_name: string | null
  property_type: string | null
  sido: string | null
  sigungu: string | null
  dong: string | null
  full_address: string | null
  // ★ 2026-09-03 — 숫자 4종도 nullable 이다. `api/v1/search.py:row_to_item` 은 DB 행을
  //   보정 없이 그대로 내보내는데 `auction_item` 의 이 컬럼들은 NOT NULL 이 아니다.
  //   문자열 5종은 이미 nullable 로 적혀 있었으므로 같은 표의 같은 컬럼끼리 선언이
  //   갈려 있던 것을 맞춘다(상세 화면 타입도 같은 날 함께 정정했다).
  appraisal_price: number | null
  minimum_bid_price: number | null
  bid_rate: number | null
  auction_date: string | null
  status: string | null
  fail_count: number | null
  validation_status: string | null
  crawl_date: string | null
  // 면적(㎡). **응답에는 2026-08-26 부터 실려 있었는데 이 타입에만 없었다**
  // (2026-08-31 추가). `api/v1/search.py:row_to_item` 이 내려준다.
  // 검색 **필터가 쓰는 바로 그 값**이라, 카드 표시도 이것을 우선 쓴다
  // (`src/lib/format.ts:displayArea`). 주소에서 뽑을 수 없는 물건(차량/선박)은
  // null 이고 0 이 아니다 — "면적 0㎡"와 "면적을 모른다"는 다르다.
  // optional 인 이유: migration 025 이전 스키마에서는 서버가 null 을 준다.
  building_area?: number | null
  land_area?: number | null
  is_favorited: boolean
  // 대표 사진(가장 앞선 순번)의 서빙 URL. 사진이 없는 물건은 null이다.
  // 2026-08-17 Sprint 145 추가 — optional로 두어 백엔드를 먼저 배포하지 않아도 깨지지 않는다.
  thumbnail_url?: string | null
}

export type SearchResponse = {
  total: number
  page: number
  size: number
  total_pages: number
  items: SearchResultItem[]
}
