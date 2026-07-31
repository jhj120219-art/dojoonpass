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
  sort_by?: 'auction_date' | 'appraisal_price' | 'minimum_bid_price' | 'bid_rate' | 'fail_count' | 'case_no' | 'full_address'
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
}

export type SearchResponse = {
  total: number
  page: number
  size: number
  total_pages: number
  items: SearchResultItem[]
}
