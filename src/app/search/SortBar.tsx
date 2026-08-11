'use client'

import { useRouter, usePathname, useSearchParams } from 'next/navigation'
import type { SearchQueryParams } from './types'

type SortBy = NonNullable<SearchQueryParams['sort_by']>

const SORT_OPTIONS: { value: SortBy; label: string }[] = [
  { value: 'auction_date', label: '매각기일' },
  { value: 'appraisal_price', label: '감정가' },
  { value: 'minimum_bid_price', label: '최저입찰가' },
  { value: 'fail_count', label: '유찰횟수' },
  { value: 'bid_rate', label: '감정가 대비율' },
  { value: 'case_no', label: '사건번호' },
  { value: 'full_address', label: '소재지' },
  // 2026-08-11 Sprint 52 추가. 백엔드(`api/v1/search.py:SORT_COLUMNS`)와 프론트 타입
  // (`types.ts:sort_by`)은 8개를 지원하는데 UI만 7개를 노출해, `crawl_date`는 URL을 직접
  // 편집해야만 쓸 수 있는 **도달 불가 정렬**이었다(2026-08-10 Sprint 43이 타입 불일치를
  // 고치면서 UI 노출은 보류로 남겨둔 항목). 화이트리스트에 이미 있는 값을 노출만 하는 것이라
  // API 계약·정렬 규칙은 전혀 바뀌지 않는다.
  { value: 'crawl_date', label: '수집일' },
]

export default function SortBar() {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()

  const currentSortBy = searchParams.get('sort_by') || 'auction_date'
  // 파라미터가 없을 때의 기본값은 **백엔드 기본값과 같아야** 한다.
  // api/v1/search.py는 sort_order 기본값이 "desc"이고, sort_by가 없으면
  // `auction_date DESC, fail_count DESC`로 정렬한다. 여기서 'asc'를 기본으로 두면
  // ① 첫 화면이 실제로는 내림차순인데 화살표만 ↑(오름차순)로 표시되고,
  // ② "매각기일"을 처음 눌렀을 때 asc→desc 토글이 되어 이미 적용 중인 정렬과 같은 값이
  //    나가므로 사용자에게는 "눌러도 아무 변화가 없는" 버튼이 된다.
  const currentSortOrder = searchParams.get('sort_order') || 'desc'

  function handleSortClick(value: SortBy) {
    const params = new URLSearchParams(searchParams.toString())
    if (currentSortBy === value) {
      params.set('sort_order', currentSortOrder === 'asc' ? 'desc' : 'asc')
    } else {
      params.set('sort_by', value)
      params.set('sort_order', 'desc')
    }
    // 정렬 기준이 바뀌면 결과의 순서 자체가 달라지므로 현재 페이지 번호는 의미를 잃는다.
    // 예전에는 page를 그대로 두어서, 3페이지에서 "감정가 ↓"를 누르면 감정가가 가장 높은
    // 물건이 아니라 **가장 낮은 물건 1건**이 보였다(3/3페이지). Pagination.changeSize()가
    // 이미 쓰고 있는 규칙(size 변경 시 1페이지로) 및 SearchForm.handleSearch()(새 검색 시
    // page 생략)와 동일하게 맞춘다.
    params.set('page', '1')
    router.push(`${pathname}?${params.toString()}`)
  }

  return (
    <div className="flex gap-1.5 overflow-x-auto pb-1 mb-4">
      {SORT_OPTIONS.map((opt) => {
        const active = currentSortBy === opt.value
        return (
          <button
            key={opt.value}
            type="button"
            onClick={() => handleSortClick(opt.value)}
            className={
              'shrink-0 rounded-full px-3 py-1.5 text-xs font-medium transition-colors ' +
              (active
                ? 'bg-blue-500 text-white'
                : 'bg-gray-100 text-gray-600')
            }
          >
            {opt.label} {active ? (currentSortOrder === 'asc' ? '↑' : '↓') : ''}
          </button>
        )
      })}
    </div>
  )
}
