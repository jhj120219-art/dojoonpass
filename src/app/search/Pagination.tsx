'use client'

import { useRouter, usePathname, useSearchParams } from 'next/navigation'

const SIZE_OPTIONS = [20, 30, 50, 100]

type PaginationProps = {
  currentPage: number
  totalPages: number
}

export default function Pagination({ currentPage, totalPages }: PaginationProps) {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()

  const currentSize = Number(searchParams.get('size')) || 20

  function goToPage(page: number) {
    const params = new URLSearchParams(searchParams.toString())
    params.set('page', String(page))
    router.push(`${pathname}?${params.toString()}`)
  }

  function changeSize(size: number) {
    const params = new URLSearchParams(searchParams.toString())
    params.set('size', String(size))
    params.set('page', '1')
    router.push(`${pathname}?${params.toString()}`)
  }

  return (
    <div className="flex items-center justify-between mt-2 mb-4">
      <div className="flex gap-1">
        {SIZE_OPTIONS.map((size) => (
          <button
            key={size}
            type="button"
            onClick={() => changeSize(size)}
            className={
              'rounded-lg px-2 py-1 text-xs font-medium ' +
              (currentSize === size ? 'bg-blue-500 text-white' : 'bg-gray-100 text-gray-600')
            }
          >
            {size}개
          </button>
        ))}
      </div>

      <div className="flex items-center gap-2">
        <button
          type="button"
          disabled={currentPage <= 1}
          onClick={() => goToPage(currentPage - 1)}
          className="rounded-lg px-3 py-1.5 text-xs font-medium bg-gray-100 text-gray-600 disabled:opacity-40"
        >
          이전
        </button>
        <span className="text-xs text-gray-500">
          {currentPage} / {Math.max(totalPages, 1)}
        </span>
        <button
          type="button"
          disabled={currentPage >= totalPages}
          onClick={() => goToPage(currentPage + 1)}
          className="rounded-lg px-3 py-1.5 text-xs font-medium bg-gray-100 text-gray-600 disabled:opacity-40"
        >
          다음
        </button>
      </div>
    </div>
  )
}
