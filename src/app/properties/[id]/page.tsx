'use client'
import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { fetchJSON, API_BASE_URL } from '@/lib/api'
import { decreaseViewCount, getViewCount } from './actions'

interface DocumentStatusItem {
  doc_type: string
  status: string
}

interface RightsSummary {
  risk_level: string | null
  occupancy_difficulty: string | null
  estimated_inheritance: number | null
  foreclosure_note: string | null
  occupancy_status: string | null
  total_tenant_count: number | null
}

interface AuctionItemDetail {
  id: number
  case_no: string
  item_no: string
  court_name: string
  property_type: string
  full_address: string
  appraisal_price: number
  minimum_bid_price: number
  bid_rate: number
  auction_date: string
  status: string
  fail_count: number
  validation_status: string
  documents: DocumentStatusItem[]
  rights_summary: RightsSummary | null
  is_favorited: boolean
}

const DOC_TYPE_LABEL: Record<string, string> = {
  SPEC: '매각물건명세서',
  APPRAISAL: '감정평가서',
  STATUS: '현황조사서',
}

const DOC_STATUS_LABEL: Record<string, string> = {
  READY: '수집완료',
  COLLECTING: '수집중',
  FAILED: '수집실패',
}

export default function PropertyDetailPage() {
  const params = useParams()
  const router = useRouter()
  const id = params.id as string
  const [property, setProperty] = useState<AuctionItemDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(false)
  const [revealed, setRevealed] = useState(false)
  const [remaining, setRemaining] = useState<number | null>(null)
  const [showPopup, setShowPopup] = useState(false)
  const [viewingDoc, setViewingDoc] = useState<string | null>(null)
  const [docAvailable, setDocAvailable] = useState<'checking' | 'ok' | 'notfound'>('checking')
  useEffect(() => {
    if (!viewingDoc) return
    setDocAvailable('checking')
    fetch(`${API_BASE_URL}/api/v1/item/${id}/documents/${viewingDoc}`, { method: 'HEAD' })
      .then((res) => setDocAvailable(res.ok ? 'ok' : 'notfound'))
      .catch(() => setDocAvailable('notfound'))
  }, [viewingDoc, id])
  useEffect(() => {
    async function fetchData() {
      try {
        const data = await fetchJSON<AuctionItemDetail>(`/api/v1/item/${id}`)
        setProperty(data)
      } catch {
        setLoadError(true)
      }
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
  if (loadError || !property) return <div className="min-h-screen bg-white flex items-center justify-center"><p className="text-gray-400">매물을 찾을 수 없습니다</p></div>
  return (
    <div className="min-h-screen bg-gray-50">
      <div className="bg-white px-5 py-4 flex items-center gap-3 border-b border-gray-100">
        <button onClick={() => router.back()} className="text-gray-500 text-lg">←</button>
        <h1 className="text-base font-bold text-gray-900">매물 상세</h1>
        <span className="text-lg" title={property.is_favorited ? '즐겨찾기됨' : '즐겨찾기 안됨'}>
          {property.is_favorited ? '❤️' : '🤍'}
        </span>
        {remaining !== null && <span className="ml-auto text-xs text-gray-400">등기열람 잔여 {remaining}회</span>}
      </div>
      <div className="px-4 py-4 space-y-3">
        <div className="bg-white rounded-2xl p-5 shadow-sm border border-gray-100">
          <span className="text-xs font-medium text-blue-500 bg-blue-50 px-2 py-1 rounded-lg">{property.property_type || '유형미상'}</span>
          <h2 className="text-xl font-bold text-gray-900 mt-3 mb-1">{property.full_address || '주소 미확인'}</h2>
          <p className="text-sm text-gray-400">{property.case_no}{property.item_no && property.item_no !== '1' ? ` (${property.item_no})` : ''}</p>
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
              <span className="text-sm font-medium text-gray-700">{property.auction_date}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-sm text-gray-400">담당법원</span>
              <span className="text-sm font-medium text-gray-700">{property.court_name}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-sm text-gray-400">사건번호</span>
              <span className="text-sm font-medium text-gray-700">{property.case_no}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-sm text-gray-400">진행상태</span>
              <span className="text-sm font-medium text-gray-700">{property.status || '데이터 없음'}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-sm text-gray-400">유찰횟수</span>
              <span className="text-sm font-medium text-gray-700">{property.fail_count}회</span>
            </div>
          </div>
        </div>
        {property.rights_summary && (
          <div className="bg-white rounded-2xl p-5 shadow-sm border border-gray-100">
            <h3 className="text-sm font-bold text-gray-900 mb-3">권리분석</h3>
            <div className="space-y-2">
              <div className="flex justify-between">
                <span className="text-sm text-gray-400">점유관계</span>
                <span className="text-sm font-medium text-gray-700">{property.rights_summary.occupancy_status || '정보 없음'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-sm text-gray-400">임대차 인원수</span>
                <span className="text-sm font-medium text-gray-700">
                  {property.rights_summary.total_tenant_count != null ? `${property.rights_summary.total_tenant_count}명` : '정보 없음'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-sm text-gray-400">명도난이도</span>
                <span className="text-sm font-medium text-gray-700">{property.rights_summary.occupancy_difficulty || '정보 없음'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-sm text-gray-400">위험도</span>
                <span className="text-sm font-medium text-gray-700">{property.rights_summary.risk_level || '정보 없음'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-sm text-gray-400">인수금액</span>
                <span className="text-sm font-medium text-gray-700">
                  {property.rights_summary.estimated_inheritance != null ? formatPrice(property.rights_summary.estimated_inheritance) : '정보 없음'}
                </span>
              </div>
            </div>
          </div>
        )}
        <div className="bg-white rounded-2xl p-5 shadow-sm border border-gray-100">
          <h3 className="text-sm font-bold text-gray-900 mb-3">관련 문서</h3>
          <div className="space-y-2">
            {property.documents.map((doc) => (
              <button
                key={doc.doc_type}
                type="button"
                onClick={() => setViewingDoc(doc.doc_type)}
                className="w-full flex justify-between items-center text-left"
              >
                <span className="text-sm text-blue-500 underline">{DOC_TYPE_LABEL[doc.doc_type] || doc.doc_type}</span>
                <span className="text-sm font-medium text-gray-700">{DOC_STATUS_LABEL[doc.status] || doc.status}</span>
              </button>
            ))}
          </div>
        </div>
        <div className="bg-white rounded-2xl p-5 shadow-sm border border-gray-100">
          <h3 className="text-sm font-bold text-gray-900 mb-3">📋 등기부등본</h3>
          {revealed ? (
            <div>
              <div className="bg-green-50 border border-green-100 rounded-xl p-3 mb-3">
                <p className="text-xs text-green-600 font-medium">✅ 열람 완료</p>
              </div>
              <p className="text-sm text-gray-400 leading-relaxed">등기부등본 내용 조회 기능은 준비 중입니다</p>
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
      {viewingDoc && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex flex-col z-50">
          <div className="bg-white px-4 py-3 flex items-center gap-3 border-b border-gray-100">
            <button onClick={() => setViewingDoc(null)} className="text-gray-500 text-lg">✕</button>
            <h2 className="text-sm font-bold text-gray-900">{DOC_TYPE_LABEL[viewingDoc] || viewingDoc}</h2>
          </div>
          {docAvailable === 'notfound' ? (
            <div className="flex-1 w-full bg-white flex items-center justify-center">
              <p className="text-sm text-gray-400">문서를 찾을 수 없습니다.</p>
            </div>
          ) : (
            <iframe
              src={`${API_BASE_URL}/api/v1/item/${id}/documents/${viewingDoc}`}
              className="flex-1 w-full bg-white"
              title={DOC_TYPE_LABEL[viewingDoc] || viewingDoc}
            />
          )}
        </div>
      )}
    </div>
  )
}
