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
  // 아래 4개 필드는 DB에 대응 컬럼/데이터가 없어 현재 백엔드 미지원 (STEP3/4 보고 대상)
  min_building_area?: number
  max_building_area?: number
  min_land_area?: number
  max_land_area?: number
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
  appraisal_price: number
  minimum_bid_price: number
  bid_rate: number
  auction_date: string | null
  status: string | null
  fail_count: number
  validation_status: string | null
  crawl_date: string | null
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
