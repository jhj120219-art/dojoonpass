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
]

export default function SortBar() {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()

  const currentSortBy = searchParams.get('sort_by') || 'auction_date'
  const currentSortOrder = searchParams.get('sort_order') || 'desc'

  function handleSortClick(value: SortBy) {
    const params = new URLSearchParams(searchParams.toString())
    if (currentSortBy === value) {
      params.set('sort_order', currentSortOrder === 'asc' ? 'desc' : 'asc')
    } else {
      params.set('sort_by', value)
      params.set('sort_order', 'desc')
    }
    router.push(`${pathname}?${params.toString()}`)
  }

  return (
    <div className="flex gap-1.5 overflow-x-auto pb-1 mb-3">
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
