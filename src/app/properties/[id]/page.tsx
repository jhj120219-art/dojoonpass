'use client'
import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { useParams, useRouter, useSearchParams } from 'next/navigation'
import { fetchJSON, postJSON, deleteJSON, fetchAuthedJSON, fetchAuthedRaw, ApiError, API_BASE_URL, ERROR_CODES } from '@/lib/api'
import { createClient } from '@/lib/supabaseClient'
import { mapSpecView, assembleRightsAnalysis, type TenantRow } from './rightsAnalysis'
import { resolveNavContext } from './navContext'
import { formatDday } from '@/app/search/ResultList'
import { CONTAINER } from '@/lib/layout'
// '억' 고정 표기(0 -> "0.0억"). 공용 formatPrice()와 표기 기준이 다르며,
// 어느 쪽으로 통일할지는 미결정이라 중복만 제거했다 — src/lib/format.ts 주석 참고.
import { formatPriceEok as formatPrice, formatWon } from '@/lib/format'
import SiteHeader from '@/components/SiteHeader'

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

// api/v1/registry.py의 실제 status 값(PENDING/PAYMENT_REQUIRED/PROCESSING/COMPLETED/FAILED) 그대로 표시한다.
// 다운로드 엔드포인트 자체는 구현 완료다(GET /registry-requests/{id}/download가 실제 파일을 서빙).
// 다만 **발급이 자동화된 것은 아니라서** — 운영자가 등기부를 직접 발급받아 registry_documents/에
// 배치하고 Admin API로 doc_url을 연결해야 COMPLETED가 된다 — PENDING/PROCESSING은 "접수/처리 중"
// 까지만 안내한다(거짓 완료 표시 금지). PAYMENT_REQUIRED는 아래 JSX에서 결제 버튼 분기로
// 따로 처리하므로 이 표에는 없다.
const REGISTRY_STATUS_LABEL: Record<string, string> = {
  PENDING: '신청 접수됨 (발급 처리 대기 — 아직 자동화되지 않음)',
  PROCESSING: '처리 중',
  COMPLETED: '발급 완료',
  FAILED: '신청 실패',
}

// 플랜/가격/한도는 **서버(GET /api/v1/plans)가 단일 Source of Truth**다 (2026-08-07 CTO 승인 2번).
// 예전에는 여기에 PLAN_CATALOG를 복사한 PLAN_OPTIONS 상수가 있었는데, 한쪽만 고치면 사용자가 본
// 금액으로 결제를 눌렀을 때 서버가 "결제 금액이 올바르지 않습니다"로 거절하는 상태가 됐다.
// 이제 프론트는 값을 갖지 않고 응답을 그대로 표시·전송만 한다.
type SubscriptionPlan = string
type BillingCycle = 'MONTHLY' | 'YEARLY'
interface PlanPrice {
  list_price: number
  price: number
  discounted: boolean
  discount_amount: number
  discount_start: string | null
  discount_end: string | null
  period_days: number
}
interface PlanOption {
  plan: SubscriptionPlan
  label: string
  registry_monthly_limit: number
  prices: Record<string, PlanPrice>
}
interface PlanCatalog {
  plans: PlanOption[]
  billing_cycles: BillingCycle[]
  overage_fee: number
}

interface RegistryRequestSummary {
  id: number
  item_id: number
  status: string
  reason?: string | null
  requested_at: string
  is_free?: boolean
  free_remaining?: number
  charged_amount?: number
}

export default function PropertyDetailPage() {
  const params = useParams()
  const router = useRouter()
  const searchParams = useSearchParams()
  const id = params.id as string
  // 이전/다음 물건 이동은 컴포넌트를 재마운트하지 않으므로, 즐겨찾기 토글이 진행 중인 상태로
  // 다른 물건으로 넘어가면 나중에 도착하는 응답이 "현재" 물건의 상태를 덮어쓸 수 있다.
  // 비동기 완료 시점마다 이 값과 비교해 이미 물건이 바뀌었으면 결과를 버린다.
  const idRef = useRef(id)
  useEffect(() => {
    idRef.current = id
  }, [id])
  // Search 결과 목록에서 넘어온 경우에만 존재하는 이동 컨텍스트(같은 페이지 안에서의 id 순서 + 현재 인덱스).
  // 직접 링크로 들어온 경우 등 컨텍스트가 없으면 이전/다음 버튼을 아예 노출하지 않는다.
  // 컨텍스트 해석은 순수 함수(navContext.ts)로 분리해 회귀 테스트로 고정한다 —
  // 이 화면은 로그인 필수 + 클라이언트 렌더라 HTTP 계약 테스트로는 볼 수 없다.
  const { ids: navIds, index: navIndex, prevId: prevNavId, nextId: nextNavId } =
    resolveNavContext(searchParams.get('ids'), searchParams.get('i'))
  function goToNav(targetId: number, targetIndex: number) {
    router.push(`/properties/${targetId}?ids=${navIds.join(',')}&i=${targetIndex}`)
  }
  // 로그인으로 보낼 때 현재 상세 URL을 **쿼리스트링까지** 보존한다
  // (docs/FRONTEND_MASTER_SPEC.md §3.4). pathname만 넘기면 로그인 후 돌아왔을 때
  // 목록 내 이전/다음 물건 컨텍스트(?ids=...&i=...)가 사라진다 — middleware.ts에서 고친 것과
  // 같은 결함이 세션 만료 후 액션(즐겨찾기/등기부 신청) 경로에도 있었다.
  function loginRedirectUrl() {
    const qs = searchParams.toString()
    const target = qs ? `/properties/${id}?${qs}` : `/properties/${id}`
    return `/login?${new URLSearchParams({ redirect: target }).toString()}`
  }
  const [property, setProperty] = useState<AuctionItemDetail | null>(null)
  const [loading, setLoading] = useState(true)
  // 실패 원인을 구분한다. 예전에는 어떤 실패든 "매물을 찾을 수 없습니다"였는데, API 서버가
  // 내려간 상황(물건은 존재함)에서도 같은 문구가 나와 사용자가 "없는 물건"으로 오해했다.
  // 검색 화면(SearchScreen)의 bad_request/unavailable 분기와 같은 기준을 적용한다.
  const [loadError, setLoadError] = useState<'notfound' | 'unavailable' | null>(null)
  const [registryRequest, setRegistryRequest] = useState<RegistryRequestSummary | null>(null)
  const [registryLoading, setRegistryLoading] = useState(true)
  const [registryBusy, setRegistryBusy] = useState(false)
  const [registryMessage, setRegistryMessage] = useState<string | null>(null)
  // 등기부 신청 실패 응답의 도메인 Error Code(docs/ERROR_CODES.md). 구독 필요 UI 분기는
  // 이 코드로만 판단한다 — registryMessage(한국어 문구)로 비교하면 백엔드가 문구를 다듬는
  // 순간 이 화면(구독 전환 퍼널)이 조용히 깨진다(FavoriteButton.tsx에서 이미 겪은 문제와 동일 축).
  const [registryErrorCode, setRegistryErrorCode] = useState<string | null>(null)
  const [viewingDoc, setViewingDoc] = useState<string | null>(null)
  // 문서 존재 확인(HEAD) 결과를 "물건id:문서종류" 키로 보관하고, 아직 결과가 없으면 렌더
  // 중에 'checking'으로 파생시킨다. effect 안에서 곧바로 setDocAvailable('checking')을
  // 호출하던 기존 구조는 cascading render를 일으켜 react-hooks/set-state-in-effect lint
  // 오류였다. 키를 함께 저장하므로 이전 문서의 늦은 응답이 현재 문서 상태를 덮어쓰지 않는다.
  const [docCheckResult, setDocCheckResult] = useState<Record<string, 'ok' | 'notfound'>>({})
  const [accessToken, setAccessToken] = useState<string | null>(null)
  const [favorited, setFavorited] = useState(false)
  const [favBusy, setFavBusy] = useState(false)
  const [favError, setFavError] = useState<string | null>(null)
  const [selectedPlan, setSelectedPlan] = useState<SubscriptionPlan>('BASIC')
  const [billingCycle, setBillingCycle] = useState<BillingCycle>('MONTHLY')
  // 서버가 내려주는 플랜 카탈로그. 도착 전에는 플랜 카드를 그리지 않는다 —
  // 임시값을 보여줬다가 서버 값으로 바뀌면 사용자가 본 금액과 청구액이 달라 보인다.
  const [planCatalog, setPlanCatalog] = useState<PlanCatalog | null>(null)
  useEffect(() => {
    let cancelled = false
    fetchJSON<{ success: boolean; data: PlanCatalog | null }>('/api/v1/plans')
      .then((res) => {
        if (!cancelled && res.data) setPlanCatalog(res.data)
      })
      .catch(() => {
        // 카탈로그를 못 받으면 구독 UI만 뜨지 않는다. 등기부 신청/다운로드 등 나머지
        // 기능은 그대로 동작해야 하므로 화면 전체를 실패로 만들지 않는다.
      })
    return () => {
      cancelled = true
    }
  }, [])
  const planOptions = planCatalog?.plans ?? []
  const overageFee = planCatalog?.overage_fee ?? null
  // 현재 선택된 플랜+주기의 가격. 카탈로그가 아직 없거나 선택값이 카탈로그에 없으면 null이며,
  // 그때는 구독 버튼을 비활성화한다 — 금액을 모른 채 결제를 보내면 서버가 거절한다.
  const selectedPlanPrice =
    planOptions.find((p) => p.plan === selectedPlan)?.prices[billingCycle] ?? null
  const docCheckKey = viewingDoc ? `${id}:${viewingDoc}` : null
  const docAvailable: 'checking' | 'ok' | 'notfound' =
    docCheckKey ? (docCheckResult[docCheckKey] ?? 'checking') : 'checking'
  useEffect(() => {
    if (!docCheckKey || !viewingDoc) return
    // 이미 확인한 문서는 다시 묻지 않는다(같은 페이지 세션 안에서만 유효한 캐시).
    if (docCheckResult[docCheckKey]) return
    const key = docCheckKey
    fetch(`${API_BASE_URL}/api/v1/item/${id}/documents/${viewingDoc}`, { method: 'HEAD' })
      .then((res) => setDocCheckResult((prev) => ({ ...prev, [key]: res.ok ? 'ok' : 'notfound' })))
      .catch(() => setDocCheckResult((prev) => ({ ...prev, [key]: 'notfound' })))
  }, [docCheckKey, viewingDoc, id, docCheckResult])
  useEffect(() => {
    async function fetchData() {
      // 이전/다음 물건 이동은 같은 라우트([id])의 파라미터만 바뀌는 클라이언트 전환이라
      // 컴포넌트가 재마운트되지 않는다 — 이전 물건에서 남은 열람/문서뷰어 상태가 새 물건에
      // 그대로 노출되지 않도록 id가 바뀔 때마다 명시적으로 초기화한다.
      setLoading(true)
      setLoadError(null)
      setProperty(null)
      setRegistryRequest(null)
      setRegistryMessage(null)
      setRegistryErrorCode(null)
      setRegistryLoading(true)
      setViewingDoc(null)
      setFavError(null)
      // 이전 물건에서 즐겨찾기 요청이 아직 끝나지 않은 채로 넘어온 경우, 그 요청은 위 idRef
      // 가드로 무시되므로 favBusy가 절대 풀리지 않는다 — 새 물건에서는 항상 false로 시작한다.
      setFavBusy(false)
      // handleToggleFavorite와 동일한 idRef 가드: 이 요청이 시작된 뒤 다른 물건으로
      // 넘어가 있으면(idRef.current !== requestId) 늦게 도착한 응답은 화면에 반영하지 않는다.
      const requestId = id
      const supabase = createClient()
      const { data: { session } } = await supabase.auth.getSession()
      if (idRef.current !== requestId) return
      const token = session?.access_token ?? null
      setAccessToken(token)
      try {
        const data = await fetchJSON<AuctionItemDetail>(`/api/v1/item/${id}`, token ?? undefined)
        if (idRef.current !== requestId) return
        setProperty(data)
        setFavorited(data.is_favorited)
      } catch (err) {
        if (idRef.current !== requestId) return
        setLoadError(err instanceof ApiError && err.status === 404 ? 'notfound' : 'unavailable')
      }
      // 등기부 신청 여부/상태는 백엔드(registry_requests)가 유일한 근거다 — 프론트는 무료횟수를
      // 스스로 계산하지 않고, 이미 신청한 기록이 있는지만 조회해 그 상태를 그대로 보여준다.
      if (token) {
        try {
          const result = await fetchAuthedJSON<RegistryRequestSummary[]>('/api/v1/registry-requests', token)
          if (idRef.current !== requestId) return
          if (result.success && result.data) {
            const existing = result.data.find((r) => r.item_id === Number(id))
            setRegistryRequest(existing ?? null)
          }
        } catch {
          // 등기부 상태 조회 실패는 조용히 무시한다 — "신청하기" 버튼을 눌렀을 때 다시 확인된다.
        }
      }
      if (idRef.current !== requestId) return
      setRegistryLoading(false)
      setLoading(false)
    }
    fetchData()
  }, [id])

  // 로그인 토큰이 없으면 로그인으로 보낸다 (handleToggleFavorite와 동일한 재조회 패턴).
  async function requireToken(): Promise<string | null> {
    let token = accessToken
    if (!token) {
      const supabase = createClient()
      const { data: { session } } = await supabase.auth.getSession()
      token = session?.access_token ?? null
      setAccessToken(token)
    }
    if (!token) {
      router.push(loginRedirectUrl())
      return null
    }
    return token
  }

  // "등기부등본 신청하기" — 무료/초과 판단은 전부 백엔드(has_active_subscription/get_free_count)가
  // 내리고, 프론트는 그 응답(status/is_free/free_remaining/charged_amount)을 그대로 반영만 한다.
  // 등기부 신청 실제 호출 — busy 관리 없이 로직만 담당한다. handleSubscribe가 구독 성공 직후
  // 이미 registryBusy를 쥔 채로 이어서 호출해야 하므로(자기 자신의 가드에 막히면 안 됨),
  // 가드/busy 관리는 각 공개 핸들러(아래 handleRegistryRequest, handleSubscribe)가 맡는다.
  async function performRegistryRequest() {
    const token = await requireToken()
    if (!token) return
    const result = await postJSON<RegistryRequestSummary>('/api/v1/registry-requests', { item_id: Number(id) }, token)
    if (!result.success || !result.data) {
      const code = result.error ?? null
      setRegistryErrorCode(code)
      // 구독 필요 상태는 아래 플랜 선택 UI 자체가 이유를 설명하므로 중복 문구를 띄우지 않는다.
      // (그 외 실패는 그대로 표시 — registryErrorCode와 무관하게 항상 렌더링된다)
      if (code !== ERROR_CODES.REGISTRY_SUBSCRIPTION_REQUIRED) {
        setRegistryMessage(result.message ?? '등기부 신청에 실패했습니다')
      }
      return
    }
    setRegistryRequest(result.data)
  }

  async function handleRegistryRequest() {
    // FavoriteButton.tsx/handleToggleFavorite와 동일한 이유로 busy 플래그를 await 이전에
    // 동기적으로 세운다 — requireToken() await 중에 재클릭이 들어오면 이 시점의 registryBusy는
    // 아직 false라 가드를 그냥 통과해버린다(백엔드는 #19로 이미 안전하지만, 불필요한 중복
    // 요청 자체를 프론트에서부터 막는 게 맞다. 2026-08-09 Sprint 39).
    if (registryBusy) return
    setRegistryBusy(true)
    setRegistryMessage(null)
    setRegistryErrorCode(null)
    try {
      await performRegistryRequest()
    } catch {
      setRegistryMessage('일시적인 오류가 발생했습니다. 잠시 후 다시 시도해주세요')
    } finally {
      setRegistryBusy(false)
    }
  }

  // Mock 구독 결제(api/v1/payments.py, PG 미연동) — 성공하면 subscriptions가 생성되어
  // has_active_subscription()이 true가 되므로, 곧바로 등기부 신청을 재시도한다.
  // amount는 서버가 내려준 카탈로그 값을 그대로 되돌려 보내고, 서버가 PLAN_CATALOG로 다시 검증한다.
  async function handleSubscribe(plan: SubscriptionPlan, cycle: BillingCycle) {
    // handleRegistryRequest와 동일한 이유로 busy를 await 이전에 동기적으로 세운다(2026-08-09
    // Sprint 39). 성공 후 이어서 등기부 신청을 재시도할 때는 이미 registryBusy를 쥐고 있으므로
    // (아래) 가드가 있는 handleRegistryRequest가 아니라 performRegistryRequest를 직접 부른다 —
    // 그렇지 않으면 handleRegistryRequest 자신의 가드에 막혀 재시도가 조용히 무시된다.
    if (registryBusy) return
    setRegistryBusy(true)
    setRegistryMessage(null)
    try {
      const token = await requireToken()
      if (!token) return
      const planOption = planOptions.find((p) => p.plan === plan)
      if (!planOption || !planOption.prices[cycle]) {
        setRegistryMessage('요금제 정보를 불러오지 못했습니다. 잠시 후 다시 시도해주세요')
        return
      }
      const result = await postJSON<unknown>(
        '/api/v1/payments',
        {
          payment_type: 'SUBSCRIPTION',
          plan: planOption.plan,
          billing_cycle: cycle,
          amount: planOption.prices[cycle].price,
        },
        token
      )
      if (!result.success) {
        setRegistryMessage(result.message ?? '구독 처리에 실패했습니다')
        return
      }
      await performRegistryRequest()
    } catch {
      setRegistryMessage('일시적인 오류가 발생했습니다. 잠시 후 다시 시도해주세요')
    } finally {
      setRegistryBusy(false)
    }
  }

  // 무료 초과(PAYMENT_REQUIRED) 건별 결제 — api/v1/payments.py가 결제 성공 시 가장 오래된
  // PAYMENT_REQUIRED 신청을 찾아 payment_id를 연결하고 status를 PENDING으로 바꾼 뒤 그 결과를
  // 응답에 함께 실어준다. 프론트는 그 값을 그대로 반영만 한다(직접 상태를 추정하지 않음).
  async function handlePayOverage() {
    // 2026-08-09 Sprint 39 — 나머지 등기부/구독 핸들러와 동일하게 busy를 await 이전에
    // 동기적으로 세운다.
    if (registryBusy) return
    setRegistryBusy(true)
    setRegistryMessage(null)
    try {
      const token = await requireToken()
      if (!token || !registryRequest) return
      const result = await postJSON<{ registry_request: RegistryRequestSummary | null }>(
        '/api/v1/payments',
        { payment_type: 'OVERAGE_USAGE', amount: registryRequest.charged_amount ?? overageFee },
        token
      )
      if (!result.success || !result.data) {
        setRegistryMessage(result.message ?? '결제에 실패했습니다')
        return
      }
      if (result.data.registry_request) {
        setRegistryRequest(result.data.registry_request)
      }
    } catch {
      setRegistryMessage('일시적인 오류가 발생했습니다. 잠시 후 다시 시도해주세요')
    } finally {
      setRegistryBusy(false)
    }
  }

  // 등기부 문서 실제 다운로드 — api/v1/registry.py:download_registry()는 COMPLETED가 아니면
  // {success:false} JSON을(200으로) 돌려주고, COMPLETED면 실제 파일을 응답 바디로 돌려준다.
  // 두 경우를 Content-Type으로 구분해서 처리한다(거짓 성공 표시 금지).
  async function handleDownloadRegistry() {
    // 2026-08-09 Sprint 39 — 나머지 등기부/구독 핸들러와 동일하게 busy를 await 이전에
    // 동기적으로 세운다.
    if (registryBusy) return
    setRegistryBusy(true)
    setRegistryMessage(null)
    try {
      const token = await requireToken()
      if (!token || !registryRequest) return
      const res = await fetchAuthedRaw(`/api/v1/registry-requests/${registryRequest.id}/download`, token)
      const contentType = res.headers.get('content-type') ?? ''
      if (!res.ok || contentType.includes('application/json')) {
        const body = await res.json().catch(() => null)
        setRegistryMessage(body?.message ?? '다운로드에 실패했습니다')
        return
      }
      const blob = await res.blob()
      const disposition = res.headers.get('content-disposition') ?? ''
      const filenameMatch = disposition.match(/filename="?([^"; ]+)"?/)
      const filename = filenameMatch?.[1] ?? `registry-${registryRequest.id}`
      const objectUrl = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = objectUrl
      link.download = filename
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(objectUrl)
    } catch {
      setRegistryMessage('일시적인 오류가 발생했습니다. 잠시 후 다시 시도해주세요')
    } finally {
      setRegistryBusy(false)
    }
  }

  async function handleToggleFavorite() {
    if (favBusy || !property) return
    const requestId = id
    let token = accessToken
    if (!token) {
      const supabase = createClient()
      const { data: { session } } = await supabase.auth.getSession()
      token = session?.access_token ?? null
      if (idRef.current === requestId) setAccessToken(token)
    }
    if (!token) {
      router.push(loginRedirectUrl())
      return
    }
    setFavBusy(true)
    setFavError(null)
    try {
      // 서버가 실패를 반환했는데도 하트를 뒤집으면 아이콘과 에러 메시지가 서로 모순된다.
      // 상태는 "서버 기준으로 그렇게 됐을 때만" 바꾼다. 다만 이미 원하는 상태인 경우
      // (중복 등록 / 이미 삭제됨)는 실패가 아니라 의도가 이미 이뤄진 것이므로 상태만 맞추고
      // 에러는 띄우지 않는다 — 이 구분이 가능한 이유가 도메인 Error Code다.
      // (search/FavoriteButton.tsx와 동일한 규칙)
      if (favorited) {
        const result = await deleteJSON<{ item_id: number }>(`/api/v1/favorites/${property.id}`, token)
        if (idRef.current !== requestId) return
        if (result.success || result.error === ERROR_CODES.FAVORITE_NOT_FOUND) {
          setFavorited(false)
        } else {
          setFavError(result.message ?? '즐겨찾기 삭제에 실패했습니다')
        }
      } else {
        const result = await postJSON<{ item_id: number; created_at: string }>('/api/v1/favorites', { item_id: property.id }, token)
        if (idRef.current !== requestId) return
        if (result.success || result.error === ERROR_CODES.FAVORITE_ALREADY_EXISTS) {
          setFavorited(true)
        } else {
          setFavError(result.message ?? '즐겨찾기 등록에 실패했습니다')
        }
      }
    } catch (err) {
      if (idRef.current !== requestId) return
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
        setFavError('로그인이 만료되었습니다. 다시 로그인해주세요')
        router.push(loginRedirectUrl())
      } else {
        setFavError('일시적인 오류가 발생했습니다. 잠시 후 다시 시도해주세요')
      }
    } finally {
      if (idRef.current === requestId) setFavBusy(false)
    }
  }

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
  // 로딩/실패 상태에서도 공통 Header를 유지한다 — 상세 진입에 실패했을 때 화면에 아무
  // 이동 수단이 없어 뒤로가기 외에는 빠져나갈 길이 없던 문제를 함께 없앤다.
  if (loading) return (
    <div className="min-h-screen bg-gray-50">
      <SiteHeader />
      <div className="flex items-center justify-center py-20"><p className="text-gray-400">불러오는 중...</p></div>
    </div>
  )
  if (loadError || !property) return (
    <div className="min-h-screen bg-gray-50">
      <SiteHeader />
      <div className="flex flex-col items-center justify-center py-20 gap-1">
        {loadError === 'unavailable' ? (
          <>
            <p className="text-gray-500 font-medium">물건 정보를 불러오지 못했습니다</p>
            <p className="text-sm text-gray-400">일시적인 오류일 수 있습니다. 잠시 후 다시 시도해주세요</p>
          </>
        ) : (
          <p className="text-gray-400">매물을 찾을 수 없습니다</p>
        )}
        <Link href="/" className="mt-4 rounded-xl bg-gray-100 px-4 py-2 text-sm font-medium text-gray-600">
          검색 화면으로
        </Link>
      </div>
    </div>
  )
  return (
    <div className="min-h-screen bg-gray-50">
      {/* 공통 Header(docs/FRONTEND_MASTER_SPEC.md §5.3) — 상세 화면에서 검색/관심물건/
          최근 본 물건으로 이동할 방법이 뒤로가기밖에 없고 로그아웃 경로도 없던 문제를 없앤다.
          아래 상세 전용 바(뒤로가기·즐겨찾기·무료잔여)는 그대로 둔다 — 기능이 다르므로
          대체가 아니라 위에 얹는다. */}
      <SiteHeader />
      {/* 상단 바/본문 모두 다른 화면과 같은 중앙 컨테이너 기준으로 정렬한다
          (docs/FRONTEND_MASTER_SPEC.md §5.2). 배경은 화면 폭 전체, 내용만 컨테이너 안. */}
      <div className="bg-white border-b border-gray-100">
      <div className={`${CONTAINER} py-4 flex items-center gap-3`}>
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
        {registryRequest?.is_free && registryRequest.free_remaining !== undefined && (
          <span className="ml-auto text-xs text-gray-400">등기열람 무료 잔여 {registryRequest.free_remaining}회</span>
        )}
      </div>
      </div>
      {navIndex >= 0 && (
        <div className="bg-white border-b border-gray-100">
        <div className={`${CONTAINER} py-2 flex items-center justify-between`}>
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
        </div>
      )}
      {favError && (
        <div className={`${CONTAINER} pt-3`}>
          <p className="text-xs text-red-500">{favError}</p>
        </div>
      )}
      {/* 데스크톱에서 카드가 1320px를 가로지르지 않도록 xl에서 2열로 나눈다.
          카드 순서(DOM 순서)는 그대로 유지된다 — 정보 구성은 변경 대상이 아니다(§9.3). */}
      <div className={`${CONTAINER} py-4 space-y-3 xl:space-y-0 xl:grid xl:grid-cols-2 xl:gap-3 xl:items-start`}>
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
          {registryLoading ? (
            <p className="text-sm text-gray-400 text-center py-4">확인 중...</p>
          ) : registryErrorCode === ERROR_CODES.REGISTRY_SUBSCRIPTION_REQUIRED ? (
            <div className="py-4">
              <p className="text-sm text-gray-400 mb-3 text-center">등기부등본 신청은 구독 후 이용할 수 있습니다</p>
              {/* 월/연 결제주기 토글. 결제주기 목록도 서버(GET /api/v1/plans)가 정한다. */}
              <div className="flex rounded-full overflow-hidden border border-gray-200 mb-3">
                {(planCatalog?.billing_cycles ?? []).map((cycle) => (
                  <button
                    key={cycle}
                    type="button"
                    onClick={() => setBillingCycle(cycle)}
                    aria-pressed={billingCycle === cycle}
                    className={`flex-1 py-1.5 text-xs font-medium transition-colors ${
                      billingCycle === cycle ? 'bg-blue-500 text-white' : 'bg-gray-50 text-gray-500'
                    }`}
                  >
                    {cycle === 'MONTHLY' ? '월 결제' : '연 결제'}
                  </button>
                ))}
              </div>
              <div className="space-y-2 mb-3">
                {planOptions.map((opt) => {
                  const p = opt.prices[billingCycle]
                  if (!p) return null
                  return (
                    <button
                      key={opt.plan}
                      type="button"
                      onClick={() => setSelectedPlan(opt.plan)}
                      aria-pressed={selectedPlan === opt.plan}
                      className={
                        'w-full text-left p-3 rounded-xl border transition-colors ' +
                        (selectedPlan === opt.plan
                          ? 'border-blue-500 bg-blue-50'
                          : 'border-gray-100 bg-white')
                      }
                    >
                      <div className="flex justify-between items-center">
                        <span className="text-sm font-semibold text-gray-900">{opt.label}</span>
                        <span className="text-sm font-bold text-blue-500">
                          {p.discounted && (
                            <span className="mr-1.5 text-xs font-normal text-gray-400 line-through">
                              {p.list_price.toLocaleString()}원
                            </span>
                          )}
                          {p.price.toLocaleString()}원{billingCycle === 'MONTHLY' ? '/월' : '/년'}
                        </span>
                      </div>
                      <p className="text-xs text-gray-400 mt-1">등기부등본 월 {opt.registry_monthly_limit}회 제공</p>
                    </button>
                  )
                })}
              </div>
              <button
                onClick={() => handleSubscribe(selectedPlan, billingCycle)}
                disabled={registryBusy || !selectedPlanPrice}
                className="w-full py-4 bg-blue-500 hover:bg-blue-600 text-white font-semibold rounded-2xl transition-all duration-200 disabled:opacity-50"
              >
                {registryBusy
                  ? '처리 중...'
                  : selectedPlanPrice
                    ? `구독하기 (${selectedPlanPrice.price.toLocaleString()}원${billingCycle === 'MONTHLY' ? '/월' : '/년'})`
                    : '요금제를 불러오는 중...'}
              </button>
            </div>
          ) : registryRequest?.status === 'PAYMENT_REQUIRED' ? (
            <div className="text-center py-4">
              <p className="text-sm text-gray-400 mb-2">무료 열람 횟수를 모두 사용했습니다</p>
              <p className="text-xs text-gray-300 mb-5">
                건당 {(registryRequest.charged_amount ?? overageFee ?? 0).toLocaleString()}원 결제가 필요합니다
              </p>
              <button
                onClick={handlePayOverage}
                disabled={registryBusy}
                className="w-full py-4 bg-blue-500 hover:bg-blue-600 text-white font-semibold rounded-2xl transition-all duration-200 disabled:opacity-50"
              >
                {registryBusy ? '처리 중...' : `${(registryRequest.charged_amount ?? overageFee ?? 0).toLocaleString()}원 결제하기`}
              </button>
            </div>
          ) : registryRequest?.status === 'COMPLETED' ? (
            <div className="text-center py-4">
              <div className="bg-green-50 border border-green-100 rounded-xl p-3 mb-3">
                <p className="text-xs text-green-600 font-medium">발급 완료</p>
              </div>
              <button
                onClick={handleDownloadRegistry}
                disabled={registryBusy}
                className="w-full py-4 bg-blue-500 hover:bg-blue-600 text-white font-semibold rounded-2xl transition-all duration-200 disabled:opacity-50"
              >
                {registryBusy ? '다운로드 중...' : '📥 등기부 다운로드'}
              </button>
            </div>
          ) : registryRequest?.status === 'FAILED' ? (
            <div className="bg-red-50 border border-red-100 rounded-xl p-3">
              <p className="text-xs text-red-600 font-medium mb-1">신청 실패</p>
              <p className="text-xs text-gray-500">{registryRequest.reason || '사유가 등록되지 않았습니다'}</p>
            </div>
          ) : registryRequest ? (
            <div className="bg-green-50 border border-green-100 rounded-xl p-3">
              <p className="text-xs text-green-600 font-medium">
                {REGISTRY_STATUS_LABEL[registryRequest.status] ?? registryRequest.status}
              </p>
            </div>
          ) : (
            <div className="text-center py-4">
              <p className="text-sm text-gray-400 mb-2">
                신청 시 무료 횟수 <span className="text-blue-500 font-medium">1회</span>가 차감됩니다(초과 시 유료)
              </p>
              <button
                onClick={handleRegistryRequest}
                disabled={registryBusy}
                className="w-full py-4 bg-blue-500 hover:bg-blue-600 text-white font-semibold rounded-2xl transition-all duration-200 disabled:opacity-50"
              >
                {registryBusy ? '처리 중...' : '📄 등기부등본 신청하기'}
              </button>
            </div>
          )}
          {registryMessage && (
            <p className="text-xs text-red-400 mt-2">{registryMessage}</p>
          )}
        </div>
      </div>
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
