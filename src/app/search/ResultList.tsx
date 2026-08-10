import Link from 'next/link'
import type { SearchResponse, SearchResultItem } from './types'
import FavoriteButton from './FavoriteButton'
import { formatPrice } from '@/lib/format'

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
    <div className="bg-white rounded-2xl p-4 shadow-sm hover:shadow-md transition-shadow border border-gray-100">
      {/* 물건 그룹: 물건종류를 가장 먼저 눈에 띄게, 그 다음 사건번호/주소/면적.
          대표 이미지는 넣지 않는다 — auction_item에 이미지 컬럼이 없어 항상 빈 placeholder만
          차지하므로, 그 공간을 텍스트 정보가 쓰도록 비워둔다. */}
      <div className="min-w-0">
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
            <FavoriteButton itemId={item.id} initialFavorited={item.is_favorited} />
          </div>
        </div>
        <p className="text-sm font-bold text-gray-900 truncate">
          {item.case_no}{item.item_no ? ` (${item.item_no})` : ''}
        </p>
        <p className="text-xs text-gray-400 line-clamp-2 break-all">{location || '-'}</p>
        {area && <p className="text-xs text-gray-400 mt-0.5">{formatArea(area)}</p>}
      </div>

      {/* 가격 그룹: 실입찰 기준가인 최저입찰가를 가장 크게, 감정가는 대비용으로 보조 표시 */}
      <div className="mt-3 flex items-end justify-between border-t border-gray-50 pt-3">
        <div>
          <p className="text-[11px] text-gray-400">최저입찰가</p>
          <p className="text-lg font-bold text-blue-600 leading-tight">{formatPrice(item.minimum_bid_price)}</p>
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

      {/* 일정 그룹: 절대 매각기일 + 법원, 상대일수는 위 물건 그룹 배지로 이미 노출됨.
          법원명 길이가 들쭉날쭉해도 이 줄이 항상 한 줄로 유지되도록, 가변 길이인 법원명만
          truncate로 줄이고 나머지 고정 길이 항목은 줄바꿈되지 않게 고정한다. */}
      <div className="mt-2 flex items-center justify-between gap-2 text-xs text-gray-400">
        <span className="min-w-0 truncate">{item.court_name || '-'}</span>
        <span className="shrink-0 whitespace-nowrap">{item.auction_date || '-'} 매각 · {item.status || '-'}</span>
        {/* 조회수: auction_item에 조회수 컬럼 없음 (TODO) */}
        <span className="shrink-0 whitespace-nowrap">조회수 -</span>
      </div>
    </div>
    </Link>
  )
}

// basePath: 이 검색 화면이 렌더된 경로(`/` 또는 `/search`). Empty State의 "조건 없이 다시 보기"가
// 사용자를 다른 화면으로 옮기지 않고 **지금 있는 화면의 조건만** 비우도록 하기 위해 받는다
// (docs/FRONTEND_MASTER_SPEC.md §8.2 "검색 실행이 현재 pathname을 유지한다"와 같은 규칙).
export default function ResultList({ data, basePath }: { data: SearchResponse; basePath: string }) {
  if (data.items.length === 0) {
    // Empty State: 예전에는 회색 한 줄만 덩그러니 떠 있어서, 조건을 잘못 넣은 사용자가
    // 무엇을 해야 하는지도 어떻게 되돌리는지도 알 수 없었다. 원인 안내 + 복구 동선을 준다.
    return (
      <div className="text-center py-20">
        <p className="text-gray-500 font-medium">검색 결과가 없습니다</p>
        <p className="mt-1 text-sm text-gray-400">
          검색조건을 줄이거나 지역·가격 범위를 넓혀보세요
        </p>
        <Link
          href={basePath}
          className="mt-4 inline-block rounded-xl bg-gray-100 px-4 py-2 text-sm font-medium text-gray-600"
        >
          조건 없이 전체 물건 보기
        </Link>
      </div>
    )
  }

  // 같은 페이지 안에서 "다음/이전 물건"으로 이동할 수 있도록, 현재 결과 목록의 id 순서와
  // 클릭한 아이템의 인덱스를 Detail로 넘긴다. 페이지를 넘어가는 이동은 다루지 않는다
  // (다음 페이지 데이터는 이 화면이 아직 모르므로, 새 API 호출 없이는 알 수 없음).
  const ids = data.items.map((item) => item.id).join(',')

  return (
    <div>
      <p className="mb-2 px-1">
        <span className="text-sm font-bold text-blue-600">총 {data.total.toLocaleString()}건</span>
        <span className="text-xs font-medium text-gray-600"> ({data.page}/{data.total_pages}페이지)</span>
      </p>
      {/* 목록 밀도(FRONTEND_MASTER_SPEC.md §6): 모바일 1열 / 태블릿 2열 / 데스크톱 3열.
          카드 자체의 정보 구성은 그대로 두고 배치만 바꾼다(§12.4 1단계). 카드 간격은
          카드의 mb-4 대신 grid gap으로 준다 — 열이 여러 개일 때 세로 간격만 남던 문제 방지.
          items-start: 같은 행에서 짧은 카드가 억지로 늘어나지 않게 한다. */}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3 items-start">
        {data.items.map((item, index) => (
          <ResultItemRow key={item.id} item={item} navQuery={`ids=${ids}&i=${index}`} />
        ))}
      </div>
    </div>
  )
}
