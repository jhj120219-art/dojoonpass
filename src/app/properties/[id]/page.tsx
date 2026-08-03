'use client'
import { useEffect, useState } from 'react'
import { useParams, useRouter, useSearchParams } from 'next/navigation'
import { fetchJSON, postJSON, deleteJSON, ApiError, API_BASE_URL } from '@/lib/api'
import { createClient } from '@/lib/supabaseClient'
import { decreaseViewCount, getViewCount } from './actions'
import { mapSpecView, assembleRightsAnalysis, type TenantRow } from './rightsAnalysis'
import { formatDday } from '@/app/search/ResultList'

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
  is_vacant: number | null
}

interface CaseInfo {
  case_type: string | null
  filed_date: string | null
  demand_deadline: string | null
}

interface AuctionItemDetail {
  id: number
  case_no: string
  item_no: string
  court_name: string
  property_type: string
  full_address: string
  lot_number: string | null
  appraisal_price: number
  minimum_bid_price: number
  bid_rate: number
  auction_date: string
  status: string
  fail_count: number
  validation_status: string
  crawl_date: string | null
  documents: DocumentStatusItem[]
  tenants: TenantRow[]
  rights_summary: RightsSummary | null
  case: CaseInfo | null
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

const VALIDATION_STATUS_LABEL: Record<string, string> = {
  PASS: '검증완료',
  FAIL: '검증실패',
}

export default function PropertyDetailPage() {
  const params = useParams()
  const router = useRouter()
  const searchParams = useSearchParams()
  const id = params.id as string
  // Search 결과 목록에서 넘어온 경우에만 존재하는 이동 컨텍스트(같은 페이지 안에서의 id 순서 + 현재 인덱스).
  // 직접 링크로 들어온 경우 등 컨텍스트가 없으면 이전/다음 버튼을 아예 노출하지 않는다.
  const navIds = (searchParams.get('ids') ?? '')
    .split(',')
    .map((v) => Number(v))
    .filter((n) => Number.isInteger(n))
  const navIndexRaw = Number(searchParams.get('i'))
  const navIndex = Number.isInteger(navIndexRaw) && navIndexRaw >= 0 && navIndexRaw < navIds.length ? navIndexRaw : -1
  const prevNavId = navIndex > 0 ? navIds[navIndex - 1] : null
  const nextNavId = navIndex >= 0 && navIndex < navIds.length - 1 ? navIds[navIndex + 1] : null
  function goToNav(targetId: number, targetIndex: number) {
    router.push(`/properties/${targetId}?ids=${navIds.join(',')}&i=${targetIndex}`)
  }
  const [property, setProperty] = useState<AuctionItemDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(false)
  const [revealed, setRevealed] = useState(false)
  const [remaining, setRemaining] = useState<number | null>(null)
  const [showPopup, setShowPopup] = useState(false)
  const [viewingDoc, setViewingDoc] = useState<string | null>(null)
  const [docAvailable, setDocAvailable] = useState<'checking' | 'ok' | 'notfound'>('checking')
  const [accessToken, setAccessToken] = useState<string | null>(null)
  const [favorited, setFavorited] = useState(false)
  const [favBusy, setFavBusy] = useState(false)
  const [favError, setFavError] = useState<string | null>(null)
  useEffect(() => {
    if (!viewingDoc) return
    setDocAvailable('checking')
    fetch(`${API_BASE_URL}/api/v1/item/${id}/documents/${viewingDoc}`, { method: 'HEAD' })
      .then((res) => setDocAvailable(res.ok ? 'ok' : 'notfound'))
      .catch(() => setDocAvailable('notfound'))
  }, [viewingDoc, id])
  useEffect(() => {
    async function fetchData() {
      // 이전/다음 물건 이동은 같은 라우트([id])의 파라미터만 바뀌는 클라이언트 전환이라
      // 컴포넌트가 재마운트되지 않는다 — 이전 물건에서 남은 열람/문서뷰어 상태가 새 물건에
      // 그대로 노출되지 않도록 id가 바뀔 때마다 명시적으로 초기화한다.
      setLoading(true)
      setLoadError(false)
      setProperty(null)
      setRevealed(false)
      setShowPopup(false)
      setViewingDoc(null)
      setFavError(null)
      const supabase = createClient()
      const { data: { session } } = await supabase.auth.getSession()
      const token = session?.access_token ?? null
      setAccessToken(token)
      try {
        const data = await fetchJSON<AuctionItemDetail>(`/api/v1/item/${id}`, token ?? undefined)
        setProperty(data)
        setFavorited(data.is_favorited)
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
  async function handleToggleFavorite() {
    if (favBusy || !property) return
    let token = accessToken
    if (!token) {
      const supabase = createClient()
      const { data: { session } } = await supabase.auth.getSession()
      token = session?.access_token ?? null
      setAccessToken(token)
    }
    if (!token) {
      router.push(`/login?redirect=/properties/${id}`)
      return
    }
    setFavBusy(true)
    setFavError(null)
    try {
      if (favorited) {
        const result = await deleteJSON<{ item_id: number }>(`/api/v1/favorites/${property.id}`, token)
        setFavorited(false)
        if (!result.success) setFavError(result.message ?? '즐겨찾기 삭제에 실패했습니다')
      } else {
        const result = await postJSON<{ item_id: number; created_at: string }>('/api/v1/favorites', { item_id: property.id }, token)
        setFavorited(true)
        if (!result.success) setFavError(result.message ?? '즐겨찾기 등록에 실패했습니다')
      }
    } catch (err) {
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
        setFavError('로그인이 만료되었습니다. 다시 로그인해주세요')
        router.push(`/login?redirect=/properties/${id}`)
      } else {
        setFavError('일시적인 오류가 발생했습니다. 잠시 후 다시 시도해주세요')
      }
    } finally {
      setFavBusy(false)
    }
  }
  function formatPrice(price: number) { return (price / 100000000).toFixed(1) + '억' }
  function formatWon(amount: number) { return amount.toLocaleString() + '원' }
  const specView = property ? mapSpecView(property.tenants) : undefined
  const statusTenants = property ? property.tenants.filter((t) => t.source === 'STATUS') : []
  const rightsAnalysis = property
    ? assembleRightsAnalysis(
        property.rights_summary,
        property.tenants,
        property.documents.some((d) => d.doc_type === 'SPEC' && d.status === 'READY')
      )
    : undefined
  const dday = property ? formatDday(property.auction_date) : null
  if (loading) return <div className="min-h-screen bg-white flex items-center justify-center"><p className="text-gray-400">불러오는 중...</p></div>
  if (loadError || !property) return <div className="min-h-screen bg-white flex items-center justify-center"><p className="text-gray-400">매물을 찾을 수 없습니다</p></div>
  return (
    <div className="min-h-screen bg-gray-50">
      <div className="bg-white px-5 py-4 flex items-center gap-3 border-b border-gray-100">
        <button onClick={() => router.back()} className="text-gray-500 text-lg">←</button>
        <h1 className="text-base font-bold text-gray-900">매물 상세</h1>
        <button
          type="button"
          onClick={handleToggleFavorite}
          disabled={favBusy}
          aria-label={favorited ? '즐겨찾기 해제' : '즐겨찾기 추가'}
          title={favorited ? '즐겨찾기됨' : '즐겨찾기 안됨'}
          className="text-lg disabled:opacity-50"
        >
          {favorited ? '❤️' : '🤍'}
        </button>
        {remaining !== null && <span className="ml-auto text-xs text-gray-400">등기열람 잔여 {remaining}회</span>}
      </div>
      {navIndex >= 0 && (
        <div className="bg-white px-4 py-2 flex items-center justify-between border-b border-gray-100">
          <button
            type="button"
            onClick={() => prevNavId != null && goToNav(prevNavId, navIndex - 1)}
            disabled={prevNavId == null}
            className="text-sm text-gray-500 disabled:opacity-30 disabled:cursor-not-allowed"
          >
            ← 이전 물건
          </button>
          <span className="text-xs text-gray-300">{navIndex + 1} / {navIds.length}</span>
          <button
            type="button"
            onClick={() => nextNavId != null && goToNav(nextNavId, navIndex + 1)}
            disabled={nextNavId == null}
            className="text-sm text-gray-500 disabled:opacity-30 disabled:cursor-not-allowed"
          >
            다음 물건 →
          </button>
        </div>
      )}
      {favError && (
        <div className="px-4 pt-3">
          <p className="text-xs text-red-500">{favError}</p>
        </div>
      )}
      <div className="px-4 py-4 space-y-3">
        <div className="bg-white rounded-2xl p-5 shadow-sm border border-gray-100">
          <div className="flex items-start justify-between gap-2">
            <span className="text-xs font-medium text-blue-500 bg-blue-50 px-2 py-1 rounded-lg">{property.property_type || '유형미상'}</span>
            {dday && (
              <span className="shrink-0 text-xs font-medium text-orange-500 bg-orange-50 px-2 py-1 rounded-lg">
                {dday}
              </span>
            )}
          </div>
          <h2 className="text-xl font-bold text-gray-900 mt-3 mb-1">{property.full_address || '주소 미확인'}</h2>
          <p className="text-sm text-gray-400">{property.case_no}{property.item_no && property.item_no !== '1' ? ` (${property.item_no})` : ''}</p>
          {property.lot_number && <p className="text-xs text-gray-400 mt-1">지번 {property.lot_number}</p>}
          {property.crawl_date && <p className="text-xs text-gray-300 mt-2">최근 수집일 {property.crawl_date}</p>}
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
            <div className="flex justify-between items-center">
              <span className="text-sm text-gray-400">가격 지표</span>
              <div className="flex gap-1.5">
                <span className="text-xs font-medium text-gray-600 bg-gray-50 px-2 py-1 rounded-lg">
                  입찰가율 {(property.bid_rate * 100).toFixed(1)}%
                </span>
                <span className="text-xs font-medium text-gray-600 bg-gray-50 px-2 py-1 rounded-lg">
                  유찰 {property.fail_count}회
                </span>
              </div>
            </div>
            <div className="flex justify-between">
              <span className="text-sm text-gray-400">검증상태</span>
              <span className="text-sm font-medium text-gray-700">{VALIDATION_STATUS_LABEL[property.validation_status] || property.validation_status}</span>
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
                <span className="text-sm text-gray-400">공실여부</span>
                <span className="text-sm font-medium text-gray-700">
                  {property.rights_summary.is_vacant == null ? '정보 없음' : property.rights_summary.is_vacant === 1 ? '공실' : '점유중'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-sm text-gray-400">임대차 인원수</span>
                <span className="text-sm font-medium text-gray-700">
                  {property.rights_summary.total_tenant_count != null ? `${property.rights_summary.total_tenant_count}명` : '정보 없음'}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-sm text-gray-400">명도난이도</span>
                {property.rights_summary.occupancy_difficulty ? (
                  <span
                    className={
                      'text-xs font-bold px-2 py-1 rounded-lg ' +
                      (property.rights_summary.occupancy_difficulty === 'HARD'
                        ? 'bg-red-50 text-red-600'
                        : property.rights_summary.occupancy_difficulty === 'NORMAL'
                        ? 'bg-yellow-50 text-yellow-600'
                        : 'bg-green-50 text-green-600')
                    }
                  >
                    {property.rights_summary.occupancy_difficulty}
                  </span>
                ) : (
                  <span className="text-sm font-medium text-gray-700">정보 없음</span>
                )}
              </div>
              <div className="flex justify-between items-center">
                <span className="text-sm text-gray-400">위험도</span>
                {property.rights_summary.risk_level ? (
                  <span
                    className={
                      'text-xs font-bold px-2 py-1 rounded-lg ' +
                      (property.rights_summary.risk_level === 'HIGH'
                        ? 'bg-red-50 text-red-600'
                        : property.rights_summary.risk_level === 'MID'
                        ? 'bg-yellow-50 text-yellow-600'
                        : 'bg-green-50 text-green-600')
                    }
                  >
                    {property.rights_summary.risk_level}
                  </span>
                ) : (
                  <span className="text-sm font-medium text-gray-700">정보 없음</span>
                )}
              </div>
              <div className="flex justify-between">
                <span className="text-sm text-gray-400">인수금액</span>
                <span className="text-sm font-medium text-gray-700">
                  {property.rights_summary.estimated_inheritance != null ? formatPrice(property.rights_summary.estimated_inheritance) : '정보 없음'}
                </span>
              </div>
              {property.rights_summary.foreclosure_note && (
                <div className="pt-2 border-t border-gray-50">
                  <p className="text-xs text-gray-400 mb-1">특이사항</p>
                  <p className="text-sm text-gray-700">{property.rights_summary.foreclosure_note}</p>
                </div>
              )}
            </div>
          </div>
        )}
        {rightsAnalysis && rightsAnalysis.sources.length > 0 && (
          <div className="bg-white rounded-2xl p-5 shadow-sm border border-gray-100">
            <h3 className="text-sm font-bold text-gray-900 mb-3">권리분석 신뢰도</h3>
            <div className="space-y-2">
              <div className="flex justify-between items-center">
                <span className="text-sm text-gray-400">신뢰도</span>
                <span
                  className={
                    'text-xs font-bold px-2 py-1 rounded-lg ' +
                    (rightsAnalysis.confidence === 'HIGH'
                      ? 'bg-green-50 text-green-600'
                      : rightsAnalysis.confidence === 'MEDIUM'
                      ? 'bg-yellow-50 text-yellow-600'
                      : 'bg-red-50 text-red-600')
                  }
                >
                  {rightsAnalysis.confidence}
                </span>
              </div>
              <div className="flex justify-between items-start">
                <span className="text-sm text-gray-400 shrink-0">정보원</span>
                <div className="flex flex-wrap justify-end gap-1.5">
                  {rightsAnalysis.sourceStatus
                    .filter((s) => s.source !== 'REGISTRY')
                    .map((s) => (
                      <span
                        key={s.source}
                        className={
                          'text-xs font-medium px-2 py-1 rounded-lg ' +
                          (s.available
                            ? 'bg-blue-50 text-blue-600'
                            : 'bg-gray-100 text-gray-400')
                        }
                      >
                        {s.source} {s.available ? '✓ 확보' : '미확보'}
                      </span>
                    ))}
                </div>
              </div>
              <div className="flex justify-between items-start">
                <span className="text-sm text-gray-400 shrink-0">충돌</span>
                {rightsAnalysis.conflicts.length === 0 ? (
                  <span className="text-sm font-medium text-gray-700">충돌 없음</span>
                ) : (
                  <div className="flex flex-col items-end gap-1">
                    {rightsAnalysis.conflicts.map((c, idx) => (
                      <span
                        key={idx}
                        className={
                          'text-xs font-medium px-2 py-1 rounded-lg text-right ' +
                          (c.type === 'DIRECT_CONFLICT'
                            ? 'bg-red-50 text-red-600'
                            : 'bg-orange-50 text-orange-600')
                        }
                      >
                        [{c.type}] {c.description}
                      </span>
                    ))}
                  </div>
                )}
              </div>
              <div className="flex justify-between items-start">
                <span className="text-sm text-gray-400 shrink-0">경고</span>
                {rightsAnalysis.warnings.length === 0 ? (
                  <span className="text-sm font-medium text-gray-700">경고 없음</span>
                ) : (
                  <div className="flex flex-col items-end gap-1">
                    {rightsAnalysis.warnings.map((w, idx) => (
                      <span
                        key={idx}
                        className="text-xs font-medium px-2 py-1 rounded-lg bg-orange-50 text-orange-600 text-right"
                      >
                        [{w.code}] {w.message}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
        {property.case && (
          <div className="bg-white rounded-2xl p-5 shadow-sm border border-gray-100">
            <h3 className="text-sm font-bold text-gray-900 mb-3">사건 정보</h3>
            <div className="space-y-2">
              <div className="flex justify-between">
                <span className="text-sm text-gray-400">사건종류</span>
                <span className="text-sm font-medium text-gray-700">{property.case.case_type || '-'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-sm text-gray-400">접수일</span>
                <span className="text-sm font-medium text-gray-700">{property.case.filed_date || '-'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-sm text-gray-400">배당요구종기일</span>
                <span className="text-sm font-medium text-gray-700">{property.case.demand_deadline || '-'}</span>
              </div>
            </div>
          </div>
        )}
        {specView && specView.tenants.length > 0 && (
          <div className="bg-white rounded-2xl p-5 shadow-sm border border-gray-100">
            <h3 className="text-sm font-bold text-gray-900 mb-3">임차인 상세 ({specView.tenantCount}명)</h3>
            <div className="space-y-3">
              {specView.tenants.map((tenant, idx) => (
                <div key={idx} className="pb-3 border-b border-gray-50 last:border-0 last:pb-0 space-y-1">
                  <p className="text-sm font-medium text-gray-700">{tenant.name || '성명 미상'}{tenant.occupiedArea ? ` · ${tenant.occupiedArea}` : ''}</p>
                  <div className="flex justify-between">
                    <span className="text-xs text-gray-400">보증금</span>
                    <span className="text-xs text-gray-600">{tenant.deposit != null ? formatWon(tenant.deposit) : '정보 없음'}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-xs text-gray-400">월세</span>
                    <span className="text-xs text-gray-600">{tenant.monthlyRent != null ? formatWon(tenant.monthlyRent) : '정보 없음'}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-xs text-gray-400">전입일 / 확정일자</span>
                    <span className="text-xs text-gray-600">{tenant.moveInDate || '-'} / {tenant.fixedDate || '-'}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-xs text-gray-400">배당요구</span>
                    <span className="text-xs text-gray-600">{tenant.hasDemand == null ? '정보 없음' : tenant.hasDemand ? `있음 (${tenant.demandDate || '일자 미상'})` : '없음'}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
        {statusTenants.length > 0 && (
          <div className="bg-white rounded-2xl p-5 shadow-sm border border-gray-100">
            <h3 className="text-sm font-bold text-gray-900 mb-3">현황조사서 임차인 ({statusTenants.length}명)</h3>
            <div className="space-y-3">
              {statusTenants.map((tenant, idx) => (
                <div key={idx} className="pb-3 border-b border-gray-50 last:border-0 last:pb-0 space-y-1">
                  <p className="text-sm font-medium text-gray-700">{tenant.tenant_name || '-'}{tenant.occupied_area ? ` · ${tenant.occupied_area}` : ' · -'}</p>
                  <div className="flex justify-between">
                    <span className="text-xs text-gray-400">보증금</span>
                    <span className="text-xs text-gray-600">{tenant.deposit != null ? formatWon(tenant.deposit) : '-'}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-xs text-gray-400">월세</span>
                    <span className="text-xs text-gray-600">{tenant.monthly_rent != null ? formatWon(tenant.monthly_rent) : '-'}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-xs text-gray-400">전입일 / 확정일자</span>
                    <span className="text-xs text-gray-600">{tenant.move_in_date || '-'} / {tenant.fixed_date || '-'}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-xs text-gray-400">배당요구</span>
                    <span className="text-xs text-gray-600">{tenant.has_demand == null ? '-' : tenant.has_demand ? '있음' : '없음'}</span>
                  </div>
                </div>
              ))}
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
