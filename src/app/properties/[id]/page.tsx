'use client'
import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { createClient } from '@/lib/supabaseClient'
import { decreaseViewCount, getViewCount } from './actions'
export default function PropertyDetailPage() {
  const params = useParams()
  const router = useRouter()
  const id = params.id as string
  const [property, setProperty] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [revealed, setRevealed] = useState(false)
  const [remaining, setRemaining] = useState<number | null>(null)
  const [showPopup, setShowPopup] = useState(false)
  useEffect(() => {
    async function fetchData() {
      const supabase = createClient()
      const { data } = await supabase.from('properties').select('*').eq('id', id).single()
      setProperty(data)
      const count = await getViewCount()
      setRemaining(count)
      setLoading(false)
    }
    fetchData()
  }, [id])
  async function handleReveal() {
    const result = await decreaseViewCount(Number(id))
    if (result.error) { setShowPopup(true); return }
    setRevealed(true)
    setRemaining(result.remaining ?? null)
  }
  function formatPrice(price: number) { return (price / 100000000).toFixed(1) + '억' }
  if (loading) return <div className="min-h-screen bg-white flex items-center justify-center"><p className="text-gray-400">불러오는 중...</p></div>
  if (!property) return <div className="min-h-screen bg-white flex items-center justify-center"><p className="text-gray-400">매물을 찾을 수 없습니다</p></div>
  return (
    <div className="min-h-screen bg-gray-50">
      <div className="bg-white px-5 py-4 flex items-center gap-3 border-b border-gray-100">
        <button onClick={() => router.back()} className="text-gray-500 text-lg">←</button>
        <h1 className="text-base font-bold text-gray-900">매물 상세</h1>
        {remaining !== null && <span className="ml-auto text-xs text-gray-400">등기열람 잔여 {remaining}회</span>}
      </div>
      <div className="px-4 py-4 space-y-3">
        <div className="bg-white rounded-2xl p-5 shadow-sm border border-gray-100">
          <span className="text-xs font-medium text-blue-500 bg-blue-50 px-2 py-1 rounded-lg">{property.property_type}</span>
          <h2 className="text-xl font-bold text-gray-900 mt-3 mb-1">{property.title}</h2>
          <p className="text-sm text-gray-400">{property.address}</p>
        </div>
        <div className="bg-white rounded-2xl p-5 shadow-sm border border-gray-100">
          <div className="flex justify-between items-center mb-4">
            <div>
              <p className="text-xs text-gray-400 mb-1">감정가</p>
              <p className="text-lg font-medium text-gray-700">{formatPrice(property.appraisal_price)}</p>
            </div>
            <div className="text-right">
              <p className="text-xs text-gray-400 mb-1">최저입찰가</p>
              <p className="text-2xl font-bold text-blue-500">{formatPrice(property.minimum_bid_price)}</p>
            </div>
          </div>
          <div className="pt-4 border-t border-gray-50 space-y-2">
            <div className="flex justify-between">
              <span className="text-sm text-gray-400">입찰기일</span>
              <span className="text-sm font-medium text-gray-700">{property.bid_date}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-sm text-gray-400">담당법원</span>
              <span className="text-sm font-medium text-gray-700">{property.court_name}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-sm text-gray-400">사건번호</span>
              <span className="text-sm font-medium text-gray-700">{property.case_number}</span>
            </div>
          </div>
        </div>
        <div className="bg-white rounded-2xl p-5 shadow-sm border border-gray-100">
          <h3 className="text-sm font-bold text-gray-900 mb-3">📋 등기부등본</h3>
          {revealed ? (
            <div>
              <div className="bg-green-50 border border-green-100 rounded-xl p-3 mb-3">
                <p className="text-xs text-green-600 font-medium">✅ 열람 완료</p>
              </div>
              <p className="text-sm text-gray-600 leading-relaxed">{property.detail_info}</p>
            </div>
          ) : (
            <div className="text-center py-4">
              <p className="text-sm text-gray-400 mb-2">열람 시 <span className="text-blue-500 font-medium">1회 차감</span>됩니다</p>
              <p className="text-xs text-gray-300 mb-5">잔여 횟수: {remaining}회 / 월 5회</p>
              <button onClick={handleReveal} className="w-full py-4 bg-blue-500 hover:bg-blue-600 text-white font-semibold rounded-2xl transition-all duration-200">📄 등기부등본 열람하기</button>
            </div>
          )}
        </div>
      </div>
      {showPopup && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-end justify-center z-50">
          <div className="bg-white rounded-t-3xl p-6 w-full">
            <div className="w-12 h-12 bg-orange-100 rounded-2xl flex items-center justify-center mx-auto mb-4">
              <span className="text-2xl">😢</span>
            </div>
            <h2 className="text-lg font-bold text-gray-900 text-center mb-2">이번 달 열람 횟수를 모두 소진하셨습니다</h2>
            <p className="text-sm text-gray-400 text-center mb-6">추가 충전하시겠습니까?</p>
            <button className="w-full py-4 bg-blue-500 text-white font-semibold rounded-2xl mb-3" onClick={() => setShowPopup(false)}>추가 충전하기</button>
            <button className="w-full py-4 bg-gray-100 text-gray-500 font-semibold rounded-2xl" onClick={() => setShowPopup(false)}>다음에 하기</button>
          </div>
        </div>
      )}
    </div>
  )
}