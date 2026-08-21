'use client'
import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { fetchAuthedJSON, ApiError } from '@/lib/api'
import { createClient } from '@/lib/supabaseClient'
import { formatPrice } from '@/lib/format'
import SiteHeader from '@/components/SiteHeader'
import ResultThumbnail from '@/components/ResultThumbnail'
import { CONTAINER } from '@/lib/layout'

interface RecentItem {
  id: number
  case_no: string
  item_no: string | null
  court_name: string | null
  property_type: string | null
  sido: string | null
  sigungu: string | null
  full_address: string | null
  appraisal_price: number
  minimum_bid_price: number
  bid_rate: number
  auction_date: string | null
  status: string | null
  fail_count: number
  /** 대표 사진(가장 앞선 순번)의 서빙 URL. 사진이 없는 물건은 null 이다. */
  thumbnail_url: string | null
  viewed_at: string
}

export default function RecentItemsPage() {
  const router = useRouter()
  const [items, setItems] = useState<RecentItem[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function fetchData() {
      const supabase = createClient()
      const { data: { session } } = await supabase.auth.getSession()
      const token = session?.access_token ?? null
      if (!token) {
        router.push('/login?redirect=/properties/recent')
        return
      }
      try {
        const result = await fetchAuthedJSON<RecentItem[]>('/api/v1/recent-items', token)
        setItems(result.data ?? [])
      } catch (err) {
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
          router.push('/login?redirect=/properties/recent')
          return
        }
        setError('최근 본 물건을 불러오지 못했습니다')
      } finally {
        setLoading(false)
      }
    }
    fetchData()
  }, [router])

  if (loading) {
    return (
      <main className="min-h-screen bg-white flex items-center justify-center">
        <p className="text-gray-400">불러오는 중...</p>
      </main>
    )
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <SiteHeader current="recent" title="최근 본 물건" />
      <main className={`${CONTAINER} py-4`}>
        {error && <p role="alert" className="text-sm text-red-500 text-center py-20">{error}</p>}
        {!error && items && items.length === 0 && (
          <div className="text-center py-20">
            <p className="text-gray-400">최근 본 물건이 없습니다</p>
          </div>
        )}
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3 items-start">
        {!error && items && items.map((item) => (
          // ★ `min-w-0` — grid 항목의 min-width 기본값 auto 때문에 좁은 화면에서
          //   트랙이 카드 min-content 까지 벌어져 페이지가 가로로 스크롤된다.
          //   (2026-08-21 Sprint 240, 실제 320px 창 실측. 사유는
          //    src/app/search/ResultList.tsx 의 같은 자리 주석 참고.)
          <Link key={item.id} href={`/properties/${item.id}`} className="block min-w-0">
            <div className="bg-white rounded-2xl p-4 shadow-sm border border-gray-100">
              {/* 대표 사진 (2026-08-20 Sprint 224).

                  사용자는 검색목록에서 **사진을 보고** 담는다. 그런데 여기서는 사진이
                  사라져 같은 물건인지 알아보기 어려웠다. 검색목록과 같은 컴포넌트
                  (`@/components/ResultThumbnail`)와 같은 URL 규칙을 쓴다.

                  `thumbnail_url` 이 있을 때만 그린다 — 사진이 없는 물건에 빈 회색 칸을
                  만들면 오히려 카드가 나빠진다(이 저장소의 사진 보유율은 아직 낮다).
                  깨진 URL 은 컴포넌트가 onError 로 스스로 자리를 지운다. */}
              <div className="min-w-0 flex gap-3">
                {item.thumbnail_url && <ResultThumbnail url={item.thumbnail_url} />}
                <div className="min-w-0 flex-1">
                  {/* ★ `flex-wrap` — 좁은 화면에서 물건종류 배지가 세로로 한 글자씩 쪼개지는 것을 막는다.
                      실측 근거와 수치는 src/app/search/ResultList.tsx 의 같은 자리 주석 참고
                      (2026-08-21 Sprint 242, 실제 320px 뷰포트에서 9줄 -> 카드 403px). */}
                  <div className="flex flex-wrap items-start justify-between mb-1">
                    <span className="text-xs font-medium text-blue-500 bg-blue-50 px-2 py-1 rounded-lg">
                      {item.property_type || '-'}
                    </span>
                    <span className="text-xs text-gray-400">{item.auction_date || '-'} 매각</span>
                  </div>
                  <p className="text-sm font-bold text-gray-900 truncate">
                    {item.case_no}{item.item_no ? ` (${item.item_no})` : ''}
                  </p>
                  <p className="text-xs text-gray-400 truncate">
                    {item.full_address || [item.sido, item.sigungu].filter(Boolean).join(' ') || '-'}
                  </p>
                </div>
              </div>
              <div className="mt-3 grid grid-cols-2 gap-2 text-center border-t border-gray-50 pt-3">
                <div>
                  <p className="text-[0.6875rem] text-gray-400">감정가</p>
                  <p className="text-sm font-medium text-gray-700">{formatPrice(item.appraisal_price)}</p>
                </div>
                <div>
                  <p className="text-[0.6875rem] text-gray-400">최저입찰가</p>
                  <p className="text-sm font-bold text-blue-500">{formatPrice(item.minimum_bid_price)}</p>
                </div>
              </div>
              <div className="mt-2 flex items-center justify-between text-xs text-gray-400">
                <span>{item.court_name || '-'}</span>
                <span>{new Date(item.viewed_at).toLocaleDateString('ko-KR')} 조회</span>
              </div>
            </div>
          </Link>
        ))}
        </div>
      </main>
    </div>
  )
}
