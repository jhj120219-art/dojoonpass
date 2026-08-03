import Link from 'next/link'
import type { SearchResponse, SearchResultItem } from './types'
import FavoriteButton from './FavoriteButton'

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

// 1평 = 3.305785㎡(공식 환산값)
const SQM_PER_PYEONG = 3.305785

// full_address는 크롤러가 "...주소... [유형 구조 XX.XX㎡]" 형태로 저장한다(끝의 대괄호 세그먼트).
// 다가구주택 등 일부(약 2%)는 "1층 X㎡ 2층 Y㎡ ..."처럼 층별 면적이 여러 개 나열되어 있어
// 전체를 합산해 총 면적으로 표시한다. 차량/선박 등 면적 개념이 없는 물건(약 1%)은 매치되는
// 숫자가 없으므로 null을 반환해 표시하지 않는다.
function parseArea(fullAddress: string | null): { label: string; sqm: number } | null {
  if (!fullAddress) return null
  const bracketMatch = fullAddress.match(/\[([^\]]*)\]\s*$/)
  if (!bracketMatch) return null
  const inside = bracketMatch[1]
  const areaRe = /([0-9]+(?:\.[0-9]+)?)\s*(?:㎡|m2|m²)/g
  let total = 0
  let count = 0
  let m: RegExpExecArray | null
  while ((m = areaRe.exec(inside)) !== null) {
    total += Number(m[1])
    count += 1
  }
  if (count === 0) return null
  const label = inside.startsWith('토지') ? '토지' : '건물'
  return { label, sqm: total }
}

function formatArea(area: { label: string; sqm: number }): string {
  const pyeong = (area.sqm / SQM_PER_PYEONG).toFixed(2)
  return `${area.label} ${area.sqm.toFixed(2)}㎡ (${pyeong}평)`
}

// 매각기일까지 남은 일수를 "오늘" 기준으로 계산한다. 절대 날짜(auction_date)는 그대로 유지하고
// 이 값은 보조 표시로만 사용한다.
export function formatDday(auctionDate: string | null): string | null {
  if (!auctionDate) return null
  const target = new Date(`${auctionDate}T00:00:00`)
  if (Number.isNaN(target.getTime())) return null
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const diffDays = Math.round((target.getTime() - today.getTime()) / 86400000)
  if (diffDays > 0) return `입찰 ${diffDays}일전`
  if (diffDays === 0) return 'D-Day'
  return `입찰 ${Math.abs(diffDays)}일 경과`
}

function ResultItemRow({ item, navQuery }: { item: SearchResultItem; navQuery: string }) {
  const location = item.full_address || [item.sido, item.sigungu, item.dong].filter(Boolean).join(' ')
  const area = parseArea(item.full_address)
  const dday = formatDday(item.auction_date)

  return (
    <Link href={`/properties/${item.id}?${navQuery}`} className="block">
    <div className="bg-white rounded-2xl p-4 shadow-sm border border-gray-100 mb-3">
      {/* 물건 그룹: 물건종류를 가장 먼저 눈에 띄게, 그 다음 사건번호/주소/면적 */}
      <div className="flex gap-3">
        {/* 대표 이미지: auction_item에 이미지 컬럼 없음 (TODO) */}
        <div className="w-16 h-16 shrink-0 rounded-lg bg-gray-100 flex items-center justify-center text-[10px] text-gray-400">
          이미지 없음
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-2 mb-1">
            <span className="text-sm font-bold text-blue-600 bg-blue-50 px-2.5 py-1 rounded-lg">
              {item.property_type || '-'}
            </span>
            <div className="flex items-center gap-2 shrink-0">
              {dday && (
                <span className="shrink-0 text-xs font-medium text-orange-500 bg-orange-50 px-2 py-1 rounded-lg">
                  {dday}
                </span>
              )}
              <FavoriteButton itemId={item.id} />
            </div>
          </div>
          <p className="text-sm font-bold text-gray-900 truncate">
            {item.case_no}{item.item_no ? ` (${item.item_no})` : ''}
          </p>
          <p className="text-xs text-gray-400 line-clamp-2 break-all">{location || '-'}</p>
          {area && <p className="text-xs text-gray-400 mt-0.5">{formatArea(area)}</p>}
        </div>
      </div>

      {/* 가격 그룹: 실입찰 기준가인 최저입찰가를 가장 크게, 감정가는 대비용으로 보조 표시 */}
      <div className="mt-3 flex items-end justify-between border-t border-gray-50 pt-3">
        <div>
          <p className="text-[11px] text-gray-400">최저입찰가</p>
          <p className="text-lg font-bold text-blue-500 leading-tight">{formatPrice(item.minimum_bid_price)}</p>
          <p className="text-[11px] text-gray-400 mt-0.5">감정가 {formatPrice(item.appraisal_price)}</p>
        </div>
        <div className="flex gap-1.5 shrink-0">
          <span className="text-xs font-medium text-gray-600 bg-gray-50 px-2 py-1 rounded-lg">
            최저가율 {formatBidRate(item.bid_rate)}
          </span>
          <span className="text-xs font-medium text-gray-600 bg-gray-50 px-2 py-1 rounded-lg">
            유찰 {item.fail_count}회
          </span>
        </div>
      </div>

      {/* 일정 그룹: 절대 매각기일 + 법원, 상대일수는 위 물건 그룹 배지로 이미 노출됨 */}
      <div className="mt-2 flex items-center justify-between text-xs text-gray-400">
        <span>{item.court_name || '-'}</span>
        <span>{item.auction_date || '-'} 매각 · {item.status || '-'}</span>
        {/* 조회수: auction_item에 조회수 컬럼 없음 (TODO) */}
        <span>조회수 -</span>
      </div>
    </div>
    </Link>
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

  // 같은 페이지 안에서 "다음/이전 물건"으로 이동할 수 있도록, 현재 결과 목록의 id 순서와
  // 클릭한 아이템의 인덱스를 Detail로 넘긴다. 페이지를 넘어가는 이동은 다루지 않는다
  // (다음 페이지 데이터는 이 화면이 아직 모르므로, 새 API 호출 없이는 알 수 없음).
  const ids = data.items.map((item) => item.id).join(',')

  return (
    <div>
      <p className="text-xs text-gray-400 mb-2 px-1">
        총 {data.total.toLocaleString()}건 ({data.page}/{data.total_pages}페이지)
      </p>
      {data.items.map((item, index) => (
        <ResultItemRow key={item.id} item={item} navQuery={`ids=${ids}&i=${index}`} />
      ))}
    </div>
  )
}
