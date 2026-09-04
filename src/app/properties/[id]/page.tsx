'use client'
import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { useParams, useRouter, useSearchParams } from 'next/navigation'
import { fetchJSON, postJSON, deleteJSON, fetchAuthedRaw, headOk, ApiError, API_BASE_URL, ERROR_CODES } from '@/lib/api'
import { createClient } from '@/lib/supabaseClient'
import { mapSpecView, assembleRightsAnalysis, type TenantRow } from './rightsAnalysis'
import { resolveNavContext } from './navContext'
import { CONTAINER } from '@/lib/layout'
// '억' 고정 표기(0 -> "0.0억"). 공용 formatPrice()와 표기 기준이 다르며,
// 어느 쪽으로 통일할지는 미결정이라 중복만 제거했다 — src/lib/format.ts 주석 참고.
import { formatPriceEok as formatPrice, formatWon, formatDday, formatBidRate } from '@/lib/format'
import SiteHeader from '@/components/SiteHeader'
import { useFocusTrap } from '@/lib/useFocusTrap'

interface DocumentStatusItem {
  doc_type: string
  // 2026-09-03 — `document_status.status` 는 DEFAULT 'COLLECTING' 이지만 NOT NULL 이
  // 아니다(명시적 NULL 삽입을 막지 못한다). `api/v1/item.py:_document_entry` 는
  // `row["status"]` 를 그대로 실어 보내므로 응답에 null 이 올 수 있다.
  // 같은 날 정정한 `auction_item` 파생 타입들과 같은 규칙이다.
  status: string | null
  // 2026-08-17 Sprint 144에 서버가 추가한 필드들. 예전 응답에는 없으므로 전부 optional로
  // 둔다 — 백엔드를 먼저 배포하지 않아도 프런트가 깨지지 않아야 한다.
  available?: boolean
  page_count?: number | null
  file_size?: number | null
  doc_version?: number | null
  viewer_url?: string | null
  download_url?: string | null
}

// 물건 사진 1장. `GET /api/v1/item/{id}`의 `images[]` 항목.
interface AuctionImage {
  seq: number
  kind: string | null
  url: string
  thumbnail_url: string
  width: number | null
  height: number | null
  file_size: number | null
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

interface FieldVisitSummary {
  status: string
  completed_at: string | null
  decision: string | null
  decided_at: string | null
  checked_count: number
}

// 판단 문구. 값 자체는 서버가 정한다(`api/v1/field_visits.py:DECISIONS`) —
// 화면은 **문구만** 갖는다. 임장 화면의 같은 표와 값이 어긋나면 안 되지만,
// 문구를 공유 모듈로 빼는 것은 화면 두 곳이 더 생긴 뒤에 한다(지금은 둘뿐이다).
const FIELD_DECISION_LABEL: Record<string, string> = {
  BID: '입찰',
  HOLD: '보류',
  DROP: '포기',
}

interface AuctionItemDetail {
  id: number
  case_no: string
  item_no: string | null
  // ★ 2026-09-03 — 아래 11개 필드의 nullability 를 **응답이 실제로 줄 수 있는 것**에 맞췄다.
  //
  //   `api/v1/item.py` 의 직렬화는 DB 행을 **아무 보정 없이 그대로** 내보낸다
  //   (`"court_name": row["court_name"]` …). 그리고 `auction_item` 의 이 컬럼들은
  //   전부 NOT NULL 이 아니다(실측: case_no 만 NOT NULL). 즉 서버는 null 을 줄 수 있다.
  //
  //   그런데 이 타입은 11개를 non-null 로 적어 두고 있었다. 지금 이 DB 에 null 이
  //   없다는 것은 **계약이 아니라 우연**이다 — 크롤이 값을 못 읽은 물건 하나가 들어오는
  //   순간 화면이 `null회`·`Invalid Date` 를 그리거나 인덱스 접근에서 죽는다.
  //   검색 목록 타입(`src/app/search/types.ts`)은 문자열 5종을 이미 nullable 로
  //   적고 있어서, **같은 컬럼을 두 화면이 다르게 선언**하고 있기도 했다.
  //
  //   타입만 정직하게 만들고, tsc 가 짚어 준 미보호 지점 4곳에 폴백을 넣었다
  //   (런타임 동작은 값이 있을 때 종전과 완전히 같다).
  court_name: string | null
  property_type: string | null
  full_address: string | null
  // 주소 구성요소. **응답에는 계속 있었는데 이 타입에만 없었다**(2026-08-31 실측 추가,
  // `api/v1/item.py` 가 내려준다). 화면에 쓰이지 않아도 계약에는 적어 둔다 —
  // 선언되지 않은 키는 "응답에 없는 것"으로 읽혀, 이미 있는 데이터를 다시 만들게 한다
  // (같은 드리프트가 검색 쪽 면적 4종에서 실제로 일어났다).
  //
  // ★ 화면 표시는 `full_address` 하나로 한다. 세 조각을 이어 붙여 주소를 만들면
  //   같은 주소의 두 번째 계산 경로가 생긴다 — 목록 화면들이 `full_address` 가 없을
  //   때의 **폴백으로만** 쓰는 것과 같은 규칙이다.
  sido: string | null
  sigungu: string | null
  dong: string | null
  lot_number: string | null
  // 면적(㎡). 2026-08-26 migration 025 이후 응답에 실린다. optional 인 이유는
  // 그 이전 스키마에서 서버가 null 을 주기 때문이다(`api/v1/item.py:_area_of`).
  // 검색 **필터가 쓰는 바로 그 값**이다 — 상세 화면에 표시할지는 정보 구성 결정이라
  // (`docs/FRONTEND_MASTER_SPEC.md` §9.3 범위 밖) 여기서는 계약만 적어 둔다.
  building_area?: number | null
  land_area?: number | null
  appraisal_price: number | null
  minimum_bid_price: number | null
  bid_rate: number | null
  auction_date: string | null
  status: string | null
  fail_count: number | null
  validation_status: string | null
  crawl_date: string | null
  documents: DocumentStatusItem[]
  // 사진 관련 필드도 전부 optional이다(위 DocumentStatusItem과 같은 이유).
  images?: AuctionImage[]
  image_count?: number
  representative_image?: AuctionImage | null
  images_status?: string
  tenants: TenantRow[]
  rights_summary: RightsSummary | null
  case: CaseInfo | null
  is_favorited: boolean
  /** 내 임장/판단 요약. 비로그인이거나 다녀온 적이 없으면 null.
      메모·위험요소 본문은 여기 없다 — 그것은 임장 화면의 것이다. */
  field_visit: FieldVisitSummary | null
  // 내 등기부 신청 상태. 예전에는 별도로 `GET /api/v1/registry-requests`(내 신청
  // **전체**)를 받아 이 물건 것만 골라 썼다 — 화면 하나에 왕복이 둘이었고, 실어
  // 나르는 양이 사용자의 이력만큼 커졌다. 서버가 같은 선택(가장 최근 신청)을
  // 그대로 해서 여기 담아 준다.
  registry_request: RegistryRequestSummary | null
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
  // 2026-08-17 Sprint 144: 사진 전용 상태. "실패"가 아니라 **법원이 사진을 제공하지
  // 않는 물건**이라는 뜻이다(재시도해도 결과가 같다). 실패로 보이게 하면 사용자가
  // 기다리면 생길 것처럼 오해한다.
  NO_IMAGE: '사진 없음',
}

// 사진 종류(alt에서 읽은 원문)를 화면에 그대로 쓴다. 법원 표기가 이미 한국어라
// 다시 번역할 것이 없고, 모르는 종류가 와도 그대로 보여 주면 된다.
// 실측된 값: 전경도 / 위치도 / 관련사진 / 내부구조도

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
  // 문서 뷰어의 페이지/확대 상태 (2026-08-17 Sprint 144).
  // 문서를 열 때마다 1쪽·100%로 되돌린다 — 이전 문서의 8쪽을 2쪽짜리 문서에 들고 가면
  // 빈 화면이 뜬다.
  const [docPage, setDocPage] = useState(1)
  const [docZoom, setDocZoom] = useState(100)
  const [docLoading, setDocLoading] = useState(true)
  // 사진 라이트박스에서 보고 있는 사진의 seq. null이면 닫힘.
  const [viewingImageSeq, setViewingImageSeq] = useState<number | null>(null)
  // 로드에 실패한 사진의 seq 집합. 실패한 자리를 빈 칸으로 두지 않고 안내를 그린다 —
  // DB에는 있는데 파일이 사라진 경우(이 저장소가 반복해 겪은 결함)를 사용자가
  // "그냥 안 보인다"로 겪지 않게 한다.
  const [brokenImages, setBrokenImages] = useState<Record<number, true>>({})
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

  // ---- 물건 사진 (2026-08-17 Sprint 144) --------------------------------
  const images = property?.images ?? []
  // 서버가 이미 순번으로 정렬해 주지만, 화면이 순서를 스스로 보장하도록 한 번 더 정렬한다
  // (응답 순서에 의존하는 UI는 백엔드 쿼리가 바뀌는 순간 조용히 어긋난다).
  const sortedImages = [...images].sort((a, b) => a.seq - b.seq)
  const viewingImageIndex = viewingImageSeq == null
    ? -1
    : sortedImages.findIndex((im) => im.seq === viewingImageSeq)
  const viewingImage = viewingImageIndex >= 0 ? sortedImages[viewingImageIndex] : null

  function showImageAt(index: number) {
    if (!sortedImages.length) return
    // 양끝에서 순환한다 — 법원 사이트의 캐러셀도 같은 동작이다.
    const next = (index + sortedImages.length) % sortedImages.length
    setViewingImageSeq(sortedImages[next].seq)
  }

  // 현재 열려 있는 문서의 메타(쪽수 등). documents[]에서 찾는다.
  const viewingDocMeta = viewingDoc
    ? (property?.documents.find((d) => d.doc_type === viewingDoc) ?? null)
    : null
  const viewingDocPageCount = viewingDocMeta?.page_count ?? null
  // 페이지 이동은 **쪽수를 아는 PDF에서만** 그린다. STATUS는 HTML이라 page_count가
  // null이고(쪽이라는 개념이 없다), 모르는 것을 아는 척해 1/? 같은 UI를 그리지 않는다.
  const canPageNavigate = typeof viewingDocPageCount === 'number' && viewingDocPageCount > 1

  // 모달이 열린 동안 키보드 포커스를 모달 안에 가둔다(Sprint 223, BUGS #151).
  // Escape/화살표는 이미 있었지만 **Tab 은 오버레이 뒤로 그대로 빠져나갔다** —
  // 사진 라이트박스를 열고 Tab 을 누르면 검은 배경에 가려 **보이지 않는 버튼**에 섬다(실측).
  const docModalRef = useFocusTrap<HTMLDivElement>(!!viewingDoc)
  const photoModalRef = useFocusTrap<HTMLDivElement>(!!viewingImage)

  // 라이트박스/뷰어 키보드 조작. 모달이 열려 있을 때만 리스너를 단다.
  useEffect(() => {
    if (viewingImageSeq == null && !viewingDoc) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        if (viewingImageSeq != null) setViewingImageSeq(null)
        else setViewingDoc(null)
        return
      }
      if (viewingImageSeq != null) {
        if (e.key === 'ArrowLeft') showImageAt(viewingImageIndex - 1)
        if (e.key === 'ArrowRight') showImageAt(viewingImageIndex + 1)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // showImageAt은 렌더마다 새로 만들어지지만 sortedImages/index에만 의존하므로
    // 그 둘을 의존성으로 둔다(함수 자체를 넣으면 매 렌더 재구독한다).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewingImageSeq, viewingDoc, viewingImageIndex, sortedImages.length])
  useEffect(() => {
    if (!docCheckKey || !viewingDoc) return
    // 이미 확인한 문서는 다시 묻지 않는다(같은 페이지 세션 안에서만 유효한 캐시).
    if (docCheckResult[docCheckKey]) return
    const key = docCheckKey
    // 2026-08-24 Sprint 252: 맨 fetch 였다 — 시간 제한이 없어 백엔드가 멈추면 then/catch
    // 어느 쪽도 불리지 않고 뷰어가 확인 상태에 영원히 남았다. api.ts 의 headOk 로 옮겨
    // 다른 요청과 같은 한도를 쓴다(실패는 전부 notfound 로 떨어지는 기존 동작 유지).
    headOk(`/api/v1/item/${id}/documents/${viewingDoc}`)
      .then((ok) => setDocCheckResult((prev) => ({ ...prev, [key]: ok ? 'ok' : 'notfound' })))
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
      // 이전 물건에서 열려 있던 사진/문서 뷰어 상태도 함께 초기화한다 — 같은 라우트
      // 파라미터 전환이라 컴포넌트가 재마운트되지 않는다(위 주석과 같은 이유).
      setViewingImageSeq(null)
      setBrokenImages({})
      setDocPage(1)
      setDocZoom(100)
      setFavError(null)
      // 이전 물건에서 즐겨찾기 요청이 아직 끝나지 않은 채로 넘어온 경우, 그 요청은 위 idRef
      // 가드로 무시되므로 favBusy가 절대 풀리지 않는다 — 새 물건에서는 항상 false로 시작한다.
      setFavBusy(false)
      // 2026-08-26 (BUGS #225): 등기부 쪽 busy 도 여기서 함께 내린다.
      // 여태 `favBusy` 만 여기 있었고 `registryBusy` 는 각 핸들러의 finally 가 **가드 없이**
      // 내려 주는 것에 기대고 있었다. 아래에서 그 finally 에 idRef 가드를 붙이는 순간
      // (붙이지 않으면 늦게 온 응답이 새 물건 화면을 덮는다) 이 줄이 없으면 물건을 넘긴 뒤
      // 버튼이 "처리 중..." 에서 영원히 돌아오지 않는다. 두 상태를 대칭으로 맞춘다.
      setRegistryBusy(false)
      // handleToggleFavorite와 동일한 idRef 가드: 이 요청이 시작된 뒤 다른 물건으로
      // 넘어가 있으면(idRef.current !== requestId) 늦게 도착한 응답은 화면에 반영하지 않는다.
      const requestId = id
      const supabase = await createClient()
      const { data: { session } } = await supabase.auth.getSession()
      if (idRef.current !== requestId) return
      const token = session?.access_token ?? null
      setAccessToken(token)
      try {
        const data = await fetchJSON<AuctionItemDetail>(`/api/v1/item/${id}`, token ?? undefined)
        if (idRef.current !== requestId) return
        setProperty(data)
        setFavorited(data.is_favorited)
        setRegistryRequest(data.registry_request ?? null)
      } catch (err) {
        if (idRef.current !== requestId) return
        setLoadError(err instanceof ApiError && err.status === 404 ? 'notfound' : 'unavailable')
      }
      // 등기부 신청 여부/상태는 백엔드(registry_requests)가 유일한 근거다 — 프론트는
      // 무료횟수를 스스로 계산하지 않는다. 그 상태는 위 상세 응답의 `registry_request`
      // 로 함께 온다(2026-09-05). 예전에는 여기서 `GET /api/v1/registry-requests` 를
      // **이어서** 한 번 더 불러 내 신청 전체를 받아 `find()` 로 한 건만 골랐다.
      // 순차 왕복이라 지연이 더해졌고, 페이로드는 이력이 쌓일수록 커졌다.
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
      const supabase = await createClient()
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
  // `requestId` = 이 요청을 시작한 시점의 물건 id. 호출부가 잡아서 넘긴다
  // (handleSubscribe 가 구독 성공 직후 이어서 부르는 경로에서도 **같은 물건**이어야 한다).
  async function performRegistryRequest(requestId: string) {
    const token = await requireToken()
    if (!token) return
    const result = await postJSON<RegistryRequestSummary>('/api/v1/registry-requests', { item_id: Number(requestId) }, token)
    // ★ 2026-08-26 (BUGS #225) — handleToggleFavorite 와 동일한 idRef 가드.
    //   이 응답이 오기 전에 사용자가 다른 물건으로 넘어갔다면 화면에 반영하지 않는다.
    //   여기서 반영하면 `registryRequest` 가 **이전 물건의 신청 건**으로 채워지는데,
    //   그 값은 문구가 아니라 **다운로드 URL(`/registry-requests/{id}/download`)과
    //   결제 금액**을 만든다 — 다른 물건 화면에서 이전 물건의 등기부를 받게 된다.
    if (idRef.current !== requestId) return
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
    const requestId = id
    setRegistryBusy(true)
    setRegistryMessage(null)
    setRegistryErrorCode(null)
    try {
      await performRegistryRequest(requestId)
    } catch {
      if (idRef.current !== requestId) return
      setRegistryMessage('일시적인 오류가 발생했습니다. 잠시 후 다시 시도해주세요')
    } finally {
      // 넘어간 뒤라면 새 물건의 busy 를 대신 내려 주지 않는다(그 물건이 자기 요청을
      // 진행 중일 수 있다). 넘어간 물건 쪽 busy 는 [id] 효과가 내린다.
      if (idRef.current === requestId) setRegistryBusy(false)
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
    const requestId = id
    setRegistryBusy(true)
    setRegistryMessage(null)
    try {
      const token = await requireToken()
      if (!token) return
      const planOption = planOptions.find((p) => p.plan === plan)
      if (!planOption || !planOption.prices[cycle]) {
        if (idRef.current !== requestId) return
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
      if (idRef.current !== requestId) return
      if (!result.success) {
        setRegistryMessage(result.message ?? '구독 처리에 실패했습니다')
        return
      }
      // 같은 물건일 때만 이어서 신청한다. 물건을 넘겼다면 그 신청은 **새 물건에 대한
      // 것이 되어 버리므로** 이어가지 않는다(구독 자체는 이미 성공했고 물건과 무관하다).
      await performRegistryRequest(requestId)
    } catch {
      if (idRef.current !== requestId) return
      setRegistryMessage('일시적인 오류가 발생했습니다. 잠시 후 다시 시도해주세요')
    } finally {
      if (idRef.current === requestId) setRegistryBusy(false)
    }
  }

  // 무료 초과(PAYMENT_REQUIRED) 건별 결제 — api/v1/payments.py가 결제 성공 시 가장 오래된
  // PAYMENT_REQUIRED 신청을 찾아 payment_id를 연결하고 status를 PENDING으로 바꾼 뒤 그 결과를
  // 응답에 함께 실어준다. 프론트는 그 값을 그대로 반영만 한다(직접 상태를 추정하지 않음).
  async function handlePayOverage() {
    // 2026-08-09 Sprint 39 — 나머지 등기부/구독 핸들러와 동일하게 busy를 await 이전에
    // 동기적으로 세운다.
    if (registryBusy) return
    const requestId = id
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
      // ★ BUGS #225 — 결제 응답이 늦게 오는 사이 물건을 넘겼으면 반영하지 않는다.
      //   여기서 반영하면 새 물건 화면이 **이전 물건의 결제 결과**를 자기 것으로 보여 준다.
      if (idRef.current !== requestId) return
      if (!result.success || !result.data) {
        setRegistryMessage(result.message ?? '결제에 실패했습니다')
        return
      }
      if (result.data.registry_request) {
        setRegistryRequest(result.data.registry_request)
      }
    } catch {
      if (idRef.current !== requestId) return
      setRegistryMessage('일시적인 오류가 발생했습니다. 잠시 후 다시 시도해주세요')
    } finally {
      if (idRef.current === requestId) setRegistryBusy(false)
    }
  }

  // 등기부 문서 실제 다운로드 — api/v1/registry.py:download_registry()는 COMPLETED가 아니면
  // {success:false} JSON을(200으로) 돌려주고, COMPLETED면 실제 파일을 응답 바디로 돌려준다.
  // 두 경우를 Content-Type으로 구분해서 처리한다(거짓 성공 표시 금지).
  async function handleDownloadRegistry() {
    // 2026-08-09 Sprint 39 — 나머지 등기부/구독 핸들러와 동일하게 busy를 await 이전에
    // 동기적으로 세운다.
    if (registryBusy) return
    const requestId = id
    setRegistryBusy(true)
    setRegistryMessage(null)
    try {
      const token = await requireToken()
      if (!token || !registryRequest) return
      const res = await fetchAuthedRaw(`/api/v1/registry-requests/${registryRequest.id}/download`, token)
      const contentType = res.headers.get('content-type') ?? ''
      if (!res.ok || contentType.includes('application/json')) {
        const body = await res.json().catch(() => null)
        // 파일 저장 자체는 사용자가 그 물건에서 직접 누른 행동이라 물건을 넘겨도 그대로
        // 진행한다. 화면에 남기는 **문구**만 가드한다 — 그것이 새 물건 것으로 읽히면 안 된다.
        if (idRef.current !== requestId) return
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
      if (idRef.current !== requestId) return
      setRegistryMessage('일시적인 오류가 발생했습니다. 잠시 후 다시 시도해주세요')
    } finally {
      if (idRef.current === requestId) setRegistryBusy(false)
    }
  }

  async function handleToggleFavorite() {
    if (favBusy || !property) return
    // ★ busy 는 **await 이전에 동기적으로** 세운다 (2026-09-03, P0-7).
    //
    //   예전에는 아래 `getSession()` 을 기다린 **뒤에** 세웠다. 토큰이 아직
    //   캐시되지 않은 첫 조작에서는 그 await 동안 favBusy 가 여전히 false 라,
    //   빠른 두 번째 클릭이 위 가드를 그대로 통과해 요청이 두 번 나갔다.
    //   `search/FavoriteButton.tsx` 는 이미 이 순서를 지키고 있었다 — 같은
    //   화면 두 곳이 서로 다른 연타 규칙을 갖고 있던 것이다.
    //
    //   백엔드는 UNIQUE(user_id, item_id) 로 이미 안전하므로 데이터가 깨지지는
    //   않았다. 고치는 것은 **불필요한 중복 요청**과 두 화면의 규칙 불일치다.
    //
    //   되돌아가는 길목(로그인 리다이렉트)에서는 반드시 다시 풀어 준다 —
    //   안 풀면 하트가 영영 눌리지 않는다.
    setFavBusy(true)
    const requestId = id
    let token = accessToken
    if (!token) {
      const supabase = await createClient()
      const { data: { session } } = await supabase.auth.getSession()
      token = session?.access_token ?? null
      if (idRef.current === requestId) setAccessToken(token)
    }
    if (!token) {
      if (idRef.current === requestId) setFavBusy(false)
      router.push(loginRedirectUrl())
      return
    }
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
      <main className="flex items-center justify-center py-20"><p className="text-gray-400">불러오는 중...</p></main>
    </div>
  )
  if (loadError || !property) return (
    <div className="min-h-screen bg-gray-50">
      <SiteHeader />
      <main className="flex flex-col items-center justify-center py-20 gap-1">
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
      </main>
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
        {/* 임장(현장 확인) 진입 — DISCOVER→REVIEW→**FIELD**→DECIDE 를 실제로 잇는 지점.
            이 링크가 없으면 임장 화면은 주소를 직접 쳐야만 닿는 "있지만 쓸 수 없는 기능"이다.
            상세를 다 본 뒤 현장으로 가는 순서라 즐겨찾기 옆에 둔다. */}
        {/* ★ 다녀온 결과를 여기서 보여 준다 (2026-09-04).
            예전에는 늘 "임장"이라고만 적혀 있어서, 이미 다녀와 "포기"로 정해 둔
            물건을 다시 열어도 그 사실이 화면 어디에도 없었다 — 사용자는 끝낸
            검토를 처음부터 다시 한다. DECIDE 가 보이지 않으면 판단은 사라진다. */}
        <Link
          href={`/properties/${id}/field`}
          className={`ml-3 rounded-lg border px-3 py-1.5 text-sm font-bold ${
            property.field_visit?.decision
              ? 'border-gray-900 bg-gray-900 text-white'
              : 'border-gray-300 text-gray-800'
          }`}
        >
          {property.field_visit?.decision
            ? `임장 · ${FIELD_DECISION_LABEL[property.field_visit.decision] ?? property.field_visit.decision}`
            : property.field_visit?.completed_at
              ? '임장 완료'
              : property.field_visit
                ? '임장 중'
                : '임장'}
        </Link>
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
        <div role="alert" className={`${CONTAINER} pt-3`}>
          <p className="text-xs text-red-500">{favError}</p>
        </div>
      )}
      {/* 데스크톱에서 카드가 1320px를 가로지르지 않도록 xl에서 2열로 나눈다.
          카드 순서(DOM 순서)는 그대로 유지된다 — 정보 구성은 변경 대상이 아니다(§9.3). */}
      <main className={`${CONTAINER} py-4 space-y-3 xl:space-y-0 xl:grid xl:grid-cols-2 xl:gap-3 xl:items-start`}>
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
              {/* ★ null 을 그대로 넘기면 안 된다 — 이 화면이 쓰는 표기는 `formatPriceEok`
                  이고 그것은 0 을 "0.0억" 으로 그린다(의도된 동작). 값을 **모르는** 물건에
                  "0.0억" 을 그리면 감정가가 0원이라고 단언하는 거짓말이 된다.
                  같은 파일이 임차인 보증금·인수금액에 이미 쓰는 `!= null` 관문과 같은 규칙. */}
              <p className="text-lg font-medium text-gray-700">
                {property.appraisal_price != null ? formatPrice(property.appraisal_price) : '-'}</p>
            </div>
            <div className="text-right">
              <p className="text-xs text-gray-400 mb-1">최저입찰가</p>
              <p className="text-2xl font-bold text-blue-500">
                {property.minimum_bid_price != null ? formatPrice(property.minimum_bid_price) : '-'}</p>
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
                  입찰가율 {formatBidRate(property.bid_rate)}
                </span>
                <span className="text-xs font-medium text-gray-600 bg-gray-50 px-2 py-1 rounded-lg">
                  유찰 {property.fail_count}회
                </span>
              </div>
            </div>
            <div className="flex justify-between">
              <span className="text-sm text-gray-400">검증상태</span>
              <span className="text-sm font-medium text-gray-700">{(property.validation_status && VALIDATION_STATUS_LABEL[property.validation_status]) || property.validation_status || '-'}</span>
            </div>
          </div>
        </div>
        {/* 물건 사진 (2026-08-17 Sprint 144).
            법원 원천(courtauction.go.kr 물건상세)의 사진 캐러셀을 그대로 가져온 것이다.
            대표 이미지 1장 + 썸네일 줄 + 클릭 시 라이트박스(이전/다음) 구성이며,
            사진이 없는 경우를 **상태별로 다르게** 안내한다 — "수집중"과 "법원에 사진이
            없음"은 사용자가 취할 행동이 다르기 때문이다(전자는 기다리면 되고 후자는
            기다려도 생기지 않는다). */}
        <div className="bg-white rounded-2xl p-5 shadow-sm border border-gray-100">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-bold text-gray-900">물건 사진</h3>
            {sortedImages.length > 0 && (
              <span className="text-xs text-gray-400">{sortedImages.length}장</span>
            )}
          </div>
          {sortedImages.length > 0 ? (
            <div>
              <button
                type="button"
                onClick={() => setViewingImageSeq(sortedImages[0].seq)}
                className="block w-full rounded-xl overflow-hidden bg-gray-50 border border-gray-100"
                aria-label="대표 사진 크게 보기"
              >
                {brokenImages[sortedImages[0].seq] ? (
                  <div className="w-full aspect-[4/3] flex items-center justify-center">
                    <p className="text-sm text-gray-400">사진을 불러오지 못했습니다</p>
                  </div>
                ) : (
                  /* next/image를 쓰지 않는다 — 이 저장소는 이미지 최적화 파이프라인을
                     쓰지 않기로 되어 있고(docs/SPRINT124), 사진은 이미 법원이 준
                     700px 안팎의 완성본이라 재가공할 이유가 없다.
                     width/height를 넣어 로딩 중 레이아웃이 튀지 않게 한다. */
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={`${API_BASE_URL}${sortedImages[0].url}`}
                    alt={`${sortedImages[0].kind ?? '물건 사진'} 1`}
                    width={sortedImages[0].width ?? undefined}
                    height={sortedImages[0].height ?? undefined}
                    onError={() => setBrokenImages((p) => ({ ...p, [sortedImages[0].seq]: true }))}
                    className="w-full h-auto max-h-[420px] object-contain bg-white"
                  />
                )}
              </button>
              {sortedImages.length > 1 && (
                <div className="mt-3 flex gap-2 overflow-x-auto pb-1">
                  {sortedImages.map((im, i) => (
                    <button
                      key={im.seq}
                      type="button"
                      onClick={() => setViewingImageSeq(im.seq)}
                      className="shrink-0 w-20 h-20 rounded-lg overflow-hidden border border-gray-200 bg-gray-50"
                      aria-label={`${im.kind ?? '사진'} ${i + 1}번 크게 보기`}
                    >
                      {brokenImages[im.seq] ? (
                        <span className="text-[0.625rem] text-gray-400 flex w-full h-full items-center justify-center">없음</span>
                      ) : (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={`${API_BASE_URL}${im.thumbnail_url}`}
                          alt={`${im.kind ?? '물건 사진'} ${i + 1}`}
                          /* 썸네일은 화면에 처음부터 다 보이지 않는 가로 스크롤 줄이라
                             지연 로딩이 실제로 효과가 있다. 현재 서버 측 축소가 없어
                             원본을 받으므로(장당 약 40~160KB) 더더욱 필요하다. */
                          loading="lazy"
                          onError={() => setBrokenImages((p) => ({ ...p, [im.seq]: true }))}
                          className="w-full h-full object-cover"
                        />
                      )}
                    </button>
                  ))}
                </div>
              )}
            </div>
          ) : property.images_status === 'NO_IMAGE' ? (
            <p className="text-sm text-gray-400 text-center py-6">
              법원이 이 물건의 사진을 제공하지 않습니다
            </p>
          ) : property.images_status === 'FAILED' ? (
            <p className="text-sm text-gray-400 text-center py-6">
              사진을 가져오지 못했습니다 (다음 수집에서 다시 시도합니다)
            </p>
          ) : (
            <p className="text-sm text-gray-400 text-center py-6">
              사진 수집 중입니다
            </p>
          )}
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
          <div className="space-y-1">
            {property.documents
              /* 사진은 바로 위 "물건 사진" 카드가 담당한다. document_status에는
                 IMAGE 행도 들어 있으므로 이 목록에서는 제외한다 — 그러지 않으면
                 "IMAGE / 수집완료"라는 열 수 없는 항목이 문서 목록에 끼어든다. */
              .filter((doc) => doc.doc_type !== 'IMAGE')
              .map((doc) => {
                /* 서버가 available을 주면 그대로 쓰고, 옛 응답이면 status로 판단한다. */
                const ready = doc.available ?? doc.status === 'READY'
                return (
                  <div key={doc.doc_type} className="flex justify-between items-center gap-3 py-1.5">
                    <div className="min-w-0">
                      {ready ? (
                        <button
                          type="button"
                          onClick={() => {
                            setViewingDoc(doc.doc_type)
                            setDocPage(1)
                            setDocZoom(100)
                            setDocLoading(true)
                          }}
                          className="text-sm text-blue-500 underline text-left"
                        >
                          {DOC_TYPE_LABEL[doc.doc_type] || doc.doc_type}
                        </button>
                      ) : (
                        /* 열 수 없는 문서를 링크처럼 보이게 하지 않는다. 예전에는
                           수집중인 문서도 파란 밑줄 링크였고, 누르면 "문서를 찾을 수
                           없습니다"만 뜨는 빈 모달이 열렸다. */
                        <span className="text-sm text-gray-400">
                          {DOC_TYPE_LABEL[doc.doc_type] || doc.doc_type}
                        </span>
                      )}
                      {ready && typeof doc.page_count === 'number' && (
                        <span className="ml-2 text-xs text-gray-400">{doc.page_count}쪽</span>
                      )}
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <span className={`text-sm font-medium ${ready ? 'text-gray-700' : 'text-gray-400'}`}>
                        {(doc.status && DOC_STATUS_LABEL[doc.status]) || doc.status || '-'}
                      </span>
                      {ready && (
                        /* 다운로드는 새 탭으로 연다. 뷰어(모달)와 별개의 경로를 두는
                           이유는 259쪽/6MB짜리 감정평가서가 실재하기 때문이다 —
                           브라우저 안에서 다 넘겨 보기보다 받아서 보는 편이 나은
                           경우가 있다(실측: appraisal 최대 259쪽, 평균 31.6쪽). */
                        <a
                          href={`${API_BASE_URL}${doc.download_url ?? `/api/v1/item/${id}/documents/${doc.doc_type}`}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-xs text-gray-500 border border-gray-200 rounded-lg px-2 py-1"
                        >
                          새 탭
                        </a>
                      )}
                    </div>
                  </div>
                )
              })}
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
                              {formatWon(p.list_price)}
                            </span>
                          )}
                          {formatWon(p.price)}{billingCycle === 'MONTHLY' ? '/월' : '/년'}
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
                    ? `구독하기 (${formatWon(selectedPlanPrice.price)}${billingCycle === 'MONTHLY' ? '/월' : '/년'})`
                    : '요금제를 불러오는 중...'}
              </button>
            </div>
          ) : registryRequest?.status === 'PAYMENT_REQUIRED' ? (
            <div className="text-center py-4">
              <p className="text-sm text-gray-400 mb-2">무료 열람 횟수를 모두 사용했습니다</p>
              <p className="text-xs text-gray-300 mb-5">
                건당 {formatWon(registryRequest.charged_amount ?? overageFee ?? 0)} 결제가 필요합니다
              </p>
              <button
                onClick={handlePayOverage}
                disabled={registryBusy}
                className="w-full py-4 bg-blue-500 hover:bg-blue-600 text-white font-semibold rounded-2xl transition-all duration-200 disabled:opacity-50"
              >
                {registryBusy ? '처리 중...' : `${formatWon(registryRequest.charged_amount ?? overageFee ?? 0)} 결제하기`}
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
            <p role="alert" className="text-xs text-red-400 mt-2">{registryMessage}</p>
          )}
        </div>
      </main>
      {/* role/aria-modal 은 **픽셀을 바꾸지 않는다** (2026-08-19 Sprint 221).
          없으면 스크린리더가 "모달이 열렸다"를 알리지 못하고, 뒤의 목록·가격이
          여전히 읽힌다 - 사용자는 자기가 어디에 있는지 알 수 없다.
          제목(h2)을 aria-labelledby 로 가리켜 모달의 이름도 준다. */}
      {viewingDoc && (
        <div ref={docModalRef}
             className="fixed inset-0 bg-black bg-opacity-50 flex flex-col z-50"
             role="dialog" aria-modal="true" aria-labelledby="doc-viewer-title">
          <div className="bg-white px-4 py-3 flex items-center gap-3 border-b border-gray-100 flex-wrap">
            <button onClick={() => setViewingDoc(null)} className="text-gray-500 text-lg" aria-label="닫기">✕</button>
            <h2 id="doc-viewer-title" className="text-sm font-bold text-gray-900">{DOC_TYPE_LABEL[viewingDoc] || viewingDoc}</h2>
            {docAvailable === 'ok' && (
              <div className="ml-auto flex items-center gap-3">
                {canPageNavigate && (
                  <div className="flex items-center gap-1.5">
                    <button
                      type="button"
                      onClick={() => { setDocPage((p) => Math.max(1, p - 1)); setDocLoading(true) }}
                      disabled={docPage <= 1}
                      className="text-xs text-gray-600 border border-gray-200 rounded-lg px-2 py-1 disabled:opacity-40"
                      aria-label="이전 쪽"
                    >
                      ‹
                    </button>
                    <span className="text-xs text-gray-500 tabular-nums">
                      {docPage} / {viewingDocPageCount}
                    </span>
                    <button
                      type="button"
                      onClick={() => { setDocPage((p) => Math.min(viewingDocPageCount as number, p + 1)); setDocLoading(true) }}
                      disabled={docPage >= (viewingDocPageCount as number)}
                      className="text-xs text-gray-600 border border-gray-200 rounded-lg px-2 py-1 disabled:opacity-40"
                      aria-label="다음 쪽"
                    >
                      ›
                    </button>
                  </div>
                )}
                <div className="flex items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => setDocZoom((z) => Math.max(50, z - 25))}
                    disabled={docZoom <= 50}
                    className="text-xs text-gray-600 border border-gray-200 rounded-lg px-2 py-1 disabled:opacity-40"
                    aria-label="축소"
                  >
                    −
                  </button>
                  <span className="text-xs text-gray-500 tabular-nums w-11 text-center">{docZoom}%</span>
                  <button
                    type="button"
                    onClick={() => setDocZoom((z) => Math.min(300, z + 25))}
                    disabled={docZoom >= 300}
                    className="text-xs text-gray-600 border border-gray-200 rounded-lg px-2 py-1 disabled:opacity-40"
                    aria-label="확대"
                  >
                    +
                  </button>
                </div>
                <a
                  href={`${API_BASE_URL}${viewingDocMeta?.download_url ?? `/api/v1/item/${id}/documents/${viewingDoc}`}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs text-gray-600 border border-gray-200 rounded-lg px-2 py-1"
                >
                  새 탭
                </a>
              </div>
            )}
          </div>
          {docAvailable === 'checking' ? (
            <div className="flex-1 w-full bg-white flex items-center justify-center">
              <p className="text-sm text-gray-400">문서를 확인하는 중입니다...</p>
            </div>
          ) : docAvailable === 'notfound' ? (
            <div className="flex-1 w-full bg-white flex flex-col items-center justify-center gap-2">
              <p className="text-sm text-gray-500">문서를 찾을 수 없습니다.</p>
              <p className="text-xs text-gray-400">
                수집 기록은 있으나 원본 파일을 열 수 없습니다. 다음 수집에서 다시 시도합니다.
              </p>
            </div>
          ) : (
            /* 확대/축소는 iframe **요소 자체**를 CSS로 키운다. 안쪽 문서는 다른
               origin(포트가 다르다)이라 내용에 직접 손댈 수 없기 때문이고, 이 방식은
               PDF와 HTML(현황조사서)에 똑같이 통한다.
               페이지 이동은 PDF 뷰어가 이해하는 `#page=` 프래그먼트로 넘긴다.
               프래그먼트만 바꾸면 브라우저가 다시 읽지 않는 경우가 있어 `key`로 강제
               재마운트한다 — 그래서 쪽 이동에는 로딩이 한 번 든다(그 사이를 빈 화면으로
               두지 않으려고 아래 로딩 안내를 겹쳐 놓는다). */
            <div className="flex-1 w-full bg-white overflow-auto relative">
              {docLoading && (
                <div className="absolute inset-0 flex items-center justify-center bg-white/80 pointer-events-none">
                  <p className="text-sm text-gray-400">불러오는 중...</p>
                </div>
              )}
              {/* 200%로 키우려면 iframe을 컨테이너의 **절반 크기**로 만든 뒤 2배로
                  확대한다(= 10000/zoom %, scale(zoom/100)). 그러면 안쪽 문서는 좁은
                  뷰포트에 배치된 뒤 2배로 그려져 실제로 커 보이고, 확대된 결과가
                  컨테이너를 정확히 채운다. 바깥 div가 overflow-auto라 넘치는 만큼
                  스크롤된다. */}
              <div
                style={{
                  width: `${10000 / docZoom}%`,
                  height: `${10000 / docZoom}%`,
                  transform: `scale(${docZoom / 100})`,
                  transformOrigin: 'top left',
                }}
              >
                <iframe
                  key={`${viewingDoc}:${docPage}`}
                  src={`${API_BASE_URL}${viewingDocMeta?.viewer_url ?? `/api/v1/item/${id}/documents/${viewingDoc}`}${canPageNavigate ? `#page=${docPage}` : ''}`}
                  onLoad={() => setDocLoading(false)}
                  className="w-full h-full bg-white"
                  title={DOC_TYPE_LABEL[viewingDoc] || viewingDoc}
                />
              </div>
            </div>
          )}
        </div>
      )}
      {/* 사진 라이트박스 (2026-08-17 Sprint 144).
          좌우 화살표와 키보드(←/→/Esc)로 넘긴다. */}
      {viewingImage && (
        <div ref={photoModalRef}
             className="fixed inset-0 bg-black bg-opacity-90 flex flex-col z-50"
             role="dialog" aria-modal="true" aria-labelledby="photo-viewer-title">
          <div className="px-4 py-3 flex items-center gap-3 text-white">
            <button onClick={() => setViewingImageSeq(null)} className="text-lg" aria-label="닫기">✕</button>
            <h2 id="photo-viewer-title" className="text-sm font-bold">
              {viewingImage.kind ?? '물건 사진'}
            </h2>
            <span className="ml-auto text-xs text-gray-300 tabular-nums">
              {viewingImageIndex + 1} / {sortedImages.length}
            </span>
          </div>
          <div className="flex-1 flex items-center justify-center px-2 pb-4 min-h-0">
            {sortedImages.length > 1 && (
              <button
                type="button"
                onClick={() => showImageAt(viewingImageIndex - 1)}
                className="text-white text-3xl px-3 shrink-0"
                aria-label="이전 사진"
              >
                ‹
              </button>
            )}
            {brokenImages[viewingImage.seq] ? (
              <p className="text-sm text-gray-300">사진을 불러오지 못했습니다</p>
            ) : (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={`${API_BASE_URL}${viewingImage.url}`}
                alt={`${viewingImage.kind ?? '물건 사진'} ${viewingImageIndex + 1}`}
                onError={() => setBrokenImages((p) => ({ ...p, [viewingImage.seq]: true }))}
                className="max-h-full max-w-full object-contain"
              />
            )}
            {sortedImages.length > 1 && (
              <button
                type="button"
                onClick={() => showImageAt(viewingImageIndex + 1)}
                className="text-white text-3xl px-3 shrink-0"
                aria-label="다음 사진"
              >
                ›
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
