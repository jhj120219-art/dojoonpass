import type { SearchResponse, SearchResultItem } from './types'

function formatPrice(price: number) {
  if (!price) return '-'
  if (price >= 100000000) return (price / 100000000).toFixed(1) + '억'
  if (price >= 10000) return Math.round(price / 10000) + '만'
  return String(price)
}

function formatBidRate(bidRate: number) {
  if (bidRate === null || bidRate === undefined) return '-'
  return (bidRate * 100).toFixed(1) + '%'
}

function ResultItemRow({ item }: { item: SearchResultItem }) {
  const location = item.full_address || [item.sido, item.sigungu, item.dong].filter(Boolean).join(' ')

  return (
    <div className="bg-white rounded-2xl p-4 shadow-sm border border-gray-100 mb-3">
      <div className="flex gap-3">
        {/* 대표 이미지: auction_item에 이미지 컬럼 없음 (TODO) */}
        <div className="w-16 h-16 shrink-0 rounded-lg bg-gray-100 flex items-center justify-center text-[10px] text-gray-400">
          이미지 없음
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between mb-1">
            <span className="text-xs font-medium text-blue-500 bg-blue-50 px-2 py-1 rounded-lg">
              {item.property_type || '-'}
            </span>
            <span className="text-xs text-gray-400">{item.auction_date || '-'} 매각</span>
          </div>
          <p className="text-sm font-bold text-gray-900 truncate">
            {item.case_no}{item.item_no ? ` (${item.item_no})` : ''}
          </p>
          <p className="text-xs text-gray-400 truncate">{location || '-'}</p>
        </div>
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2 text-center border-t border-gray-50 pt-3">
        <div>
          <p className="text-[11px] text-gray-400">감정가</p>
          <p className="text-sm font-medium text-gray-700">{formatPrice(item.appraisal_price)}</p>
        </div>
        <div>
          <p className="text-[11px] text-gray-400">최저입찰가</p>
          <p className="text-sm font-bold text-blue-500">{formatPrice(item.minimum_bid_price)}</p>
        </div>
        <div>
          <p className="text-[11px] text-gray-400">최저가율</p>
          <p className="text-sm font-medium text-gray-700">{formatBidRate(item.bid_rate)}</p>
        </div>
      </div>

      <div className="mt-2 flex items-center justify-between text-xs text-gray-400">
        <span>{item.court_name || '-'}</span>
        <span>{item.status || '-'} (유찰 {item.fail_count}회)</span>
        {/* 조회수: auction_item에 조회수 컬럼 없음 (TODO) */}
        <span>조회수 -</span>
      </div>
    </div>
  )
}

export default function ResultList({ data }: { data: SearchResponse }) {
  if (data.items.length === 0) {
    return (
      <div className="text-center py-20">
        <p className="text-gray-400">검색 결과가 없습니다</p>
      </div>
    )
  }

  return (
    <div>
      <p className="text-xs text-gray-400 mb-2 px-1">
        총 {data.total.toLocaleString()}건 ({data.page}/{data.total_pages}페이지)
      </p>
      {data.items.map((item) => (
        <ResultItemRow key={item.id} item={item} />
      ))}
    </div>
  )
}
