'use client'
import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { fetchAuthedJSON, ApiError } from '@/lib/api'
import { createClient } from '@/lib/supabaseClient'
import { formatPrice } from '@/lib/format'
import SiteHeader from '@/components/SiteHeader'
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
      <div className="min-h-screen bg-white flex items-center justify-center">
        <p className="text-gray-400">불러오는 중...</p>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <SiteHeader current="recent" title="최근 본 물건" />
      <div className={`${CONTAINER} py-4`}>
        {error && <p className="text-sm text-red-500 text-center py-20">{error}</p>}
        {!error && items && items.length === 0 && (
          <div className="text-center py-20">
            <p className="text-gray-400">최근 본 물건이 없습니다</p>
          </div>
        )}
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3 items-start">
        {!error && items && items.map((item) => (
          <Link key={item.id} href={`/properties/${item.id}`} className="block">
            <div className="bg-white rounded-2xl p-4 shadow-sm border border-gray-100">
              <div className="flex items-start justify-between mb-1">
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
              <div className="mt-3 grid grid-cols-2 gap-2 text-center border-t border-gray-50 pt-3">
                <div>
                  <p className="text-[11px] text-gray-400">감정가</p>
                  <p className="text-sm font-medium text-gray-700">{formatPrice(item.appraisal_price)}</p>
                </div>
                <div>
                  <p className="text-[11px] text-gray-400">최저입찰가</p>
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
      </div>
    </div>
  )
}
